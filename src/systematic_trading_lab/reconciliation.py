"""Pure fail-closed reconciliation of normalized portfolio state."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from pathlib import Path
from typing import Any

from .execution import JournalIntegrityError
from .experiments import HoldoutAccessError
from .fingerprints import canonical_json, canonicalize, fingerprint
from .risk import EmergencyState, RiskLimits, RiskStore

_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,15}")
_ALPACA_READER_CAPABILITY = object()


class SnapshotSource(StrEnum):
    LOCAL_EXPECTED = "local-expected"
    ALPACA_PAPER = "alpaca-paper"


@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    quantity: int

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or _SYMBOL.fullmatch(self.symbol) is None:
            raise ValueError("position symbol must be an uppercase security identifier")
        if isinstance(self.quantity, bool) or self.quantity < 0:
            raise ValueError("position quantity must be a nonnegative whole share count")


@dataclass(frozen=True)
class OpenOrderSnapshot:
    client_order_id: str
    symbol: str
    side: str
    quantity: int
    filled_quantity: int
    order_type: str
    limit_price: Decimal | None
    status: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.client_order_id, str)
            or not self.client_order_id
            or self.client_order_id != self.client_order_id.strip()
            or len(self.client_order_id) > 128
        ):
            raise ValueError("open-order client ID must be nonempty, trimmed, and bounded")
        if not isinstance(self.symbol, str) or _SYMBOL.fullmatch(self.symbol) is None:
            raise ValueError("open-order symbol must be an uppercase security identifier")
        if self.side not in {"buy", "sell"}:
            raise ValueError("open-order side is unsupported")
        if self.order_type not in {"market", "limit"}:
            raise ValueError("open-order type is unsupported")
        if self.status not in {
            "accepted",
            "accepted_for_bidding",
            "calculated",
            "done_for_day",
            "new",
            "partially_filled",
            "pending_cancel",
            "pending_new",
            "pending_replace",
            "pending_validation",
            "stopped",
            "suspended",
        }:
            raise ValueError("open-order status is unsupported")
        if (
            isinstance(self.quantity, bool)
            or isinstance(self.filled_quantity, bool)
            or self.quantity < 1
            or self.filled_quantity < 0
            or self.filled_quantity > self.quantity
        ):
            raise ValueError("open-order quantities must be valid whole shares")
        if self.order_type == "limit":
            if (
                self.limit_price is None
                or not self.limit_price.is_finite()
                or self.limit_price <= 0
            ):
                raise ValueError("limit order requires a positive finite limit price")
        elif self.limit_price is not None:
            raise ValueError("market order cannot have a limit price")


@dataclass(frozen=True)
class PortfolioSnapshot:
    snapshot_id: str
    source: SnapshotSource
    account_id: str
    cash: Decimal
    equity: Decimal
    buying_power: Decimal
    account_ready: bool
    positions: tuple[PositionSnapshot, ...]
    open_orders: tuple[OpenOrderSnapshot, ...]
    account_observed_at: datetime
    positions_observed_at: datetime
    orders_observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.source, SnapshotSource):
            raise ValueError("snapshot source is unsupported")
        for text_name, text_value in (
            ("snapshot ID", self.snapshot_id),
            ("account ID", self.account_id),
        ):
            if (
                not isinstance(text_value, str)
                or not text_value
                or text_value != text_value.strip()
                or len(text_value) > 128
            ):
                raise ValueError(
                    f"{text_name} must be nonempty, trimmed, and at most 128 characters"
                )
        for amount_name, amount_value in (
            ("cash", self.cash),
            ("equity", self.equity),
            ("buying power", self.buying_power),
        ):
            if not amount_value.is_finite() or amount_value < 0:
                raise ValueError(f"{amount_name} must be finite and nonnegative")
        if not isinstance(self.account_ready, bool):
            raise ValueError("account readiness must be boolean")
        if (
            any(not isinstance(position, PositionSnapshot) for position in self.positions)
            or self.positions != tuple(sorted(self.positions, key=lambda item: item.symbol))
            or len({position.symbol for position in self.positions}) != len(self.positions)
        ):
            raise ValueError("positions must be sorted with unique symbols")
        if (
            any(not isinstance(order, OpenOrderSnapshot) for order in self.open_orders)
            or self.open_orders
            != tuple(sorted(self.open_orders, key=lambda item: item.client_order_id))
            or len({order.client_order_id for order in self.open_orders}) != len(self.open_orders)
        ):
            raise ValueError("open orders must be sorted with unique client IDs")
        for time_name, time_value in (
            ("account observation", self.account_observed_at),
            ("position observation", self.positions_observed_at),
            ("order observation", self.orders_observed_at),
        ):
            if time_value.tzinfo is None or time_value.utcoffset() != UTC.utcoffset(time_value):
                raise ValueError(f"{time_name} must be UTC-aware")

    @property
    def snapshot_fingerprint(self) -> str:
        return fingerprint(self)

    @property
    def open_client_order_ids(self) -> tuple[str, ...]:
        return tuple(order.client_order_id for order in self.open_orders)


@dataclass(frozen=True)
class ReconciliationResult:
    clean: bool
    reasons: tuple[str, ...]
    expected_fingerprint: str
    observed_fingerprint: str
    compared_at: datetime

    def __post_init__(self) -> None:
        if self.clean != (not self.reasons):
            raise ValueError("reconciliation state must match its reasons")
        if any(not reason or not isinstance(reason, str) for reason in self.reasons):
            raise ValueError("reconciliation reasons must be nonempty strings")
        _sha256("expected", self.expected_fingerprint)
        _sha256("observed", self.observed_fingerprint)
        _utc("comparison time", self.compared_at)

    @property
    def result_fingerprint(self) -> str:
        return fingerprint(self)


def reconcile(
    expected: PortfolioSnapshot,
    observed: PortfolioSnapshot,
    *,
    compared_at: datetime,
    maximum_age_seconds: int,
    unresolved_mutations: int,
) -> ReconciliationResult:
    """Compare complete normalized state without changing either authority."""
    if compared_at.tzinfo is None or compared_at.utcoffset() != UTC.utcoffset(compared_at):
        raise ValueError("comparison timestamp must be UTC-aware")
    if isinstance(maximum_age_seconds, bool) or maximum_age_seconds < 1:
        raise ValueError("maximum snapshot age must be positive")
    if isinstance(unresolved_mutations, bool) or unresolved_mutations < 0:
        raise ValueError("unresolved mutation count must be nonnegative")
    reasons: list[str] = []
    if expected.source is not SnapshotSource.LOCAL_EXPECTED:
        reasons.append("expected-source-invalid")
    if observed.source is not SnapshotSource.ALPACA_PAPER:
        reasons.append("observed-source-invalid")
    if expected.account_id != observed.account_id:
        reasons.append("account-mismatch")
    observed_times = (
        observed.account_observed_at,
        observed.positions_observed_at,
        observed.orders_observed_at,
    )
    if any(
        timestamp > compared_at or (compared_at - timestamp).total_seconds() > maximum_age_seconds
        for timestamp in observed_times
    ):
        reasons.append("observed-state-stale-or-future")
    if expected.cash != observed.cash:
        reasons.append("cash-mismatch")
    if expected.equity != observed.equity:
        reasons.append("equity-mismatch")
    if expected.buying_power != observed.buying_power:
        reasons.append("buying-power-mismatch")
    if expected.account_ready != observed.account_ready:
        reasons.append("account-readiness-mismatch")
    if not observed.account_ready:
        reasons.append("account-not-ready")
    if expected.positions != observed.positions:
        reasons.append("position-mismatch")
    if expected.open_orders != observed.open_orders:
        reasons.append("open-order-mismatch")
    if unresolved_mutations:
        reasons.append("unresolved-broker-mutation")
    return ReconciliationResult(
        clean=not reasons,
        reasons=tuple(reasons),
        expected_fingerprint=expected.snapshot_fingerprint,
        observed_fingerprint=observed.snapshot_fingerprint,
        compared_at=compared_at,
    )


@dataclass(frozen=True)
class ReconciliationBaseline:
    baseline_id: str
    authorization_id: str
    expected_snapshot_id: str
    observed_snapshot_id: str
    expected_fingerprint: str
    observed_fingerprint: str
    account_id: str
    risk_configuration_fingerprint: str
    comparison_fingerprint: str
    maximum_age_seconds: int
    operator: str
    reason: str
    created_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("baseline ID", self.baseline_id),
            ("authorization ID", self.authorization_id),
            ("expected snapshot ID", self.expected_snapshot_id),
            ("observed snapshot ID", self.observed_snapshot_id),
            ("account ID", self.account_id),
            ("operator", self.operator),
            ("reason", self.reason),
        ):
            _bounded_text(name, value)
        for name, value in (
            ("expected", self.expected_fingerprint),
            ("observed", self.observed_fingerprint),
            ("risk configuration", self.risk_configuration_fingerprint),
            ("comparison", self.comparison_fingerprint),
        ):
            _sha256(name, value)
        _utc("baseline creation time", self.created_at)
        if isinstance(self.maximum_age_seconds, bool) or self.maximum_age_seconds < 1:
            raise ValueError("baseline maximum age must be positive")


@dataclass(frozen=True)
class ReconciliationEvidence:
    evidence_id: str
    baseline_id: str
    observed_snapshot_id: str
    maximum_age_seconds: int
    unresolved_mutations: int
    result: ReconciliationResult

    def __post_init__(self) -> None:
        _sha256("reconciliation evidence", self.evidence_id)
        _bounded_text("baseline ID", self.baseline_id)
        _bounded_text("observed snapshot ID", self.observed_snapshot_id)
        if (
            isinstance(self.maximum_age_seconds, bool)
            or isinstance(self.unresolved_mutations, bool)
            or self.maximum_age_seconds < 1
            or self.unresolved_mutations < 0
        ):
            raise ValueError("reconciliation evidence limits are invalid")


@dataclass(frozen=True)
class EmergencyClearReadiness:
    ready: bool
    reasons: tuple[str, ...]
    baseline_id: str
    authorization_id: str
    risk_configuration_fingerprint: str
    evidence_ids: tuple[str, ...]
    observed_snapshot_ids: tuple[str, ...]
    attestation_fingerprints: tuple[str, ...]
    emergency_generation: int
    assessed_at: datetime

    def __post_init__(self) -> None:
        if self.ready != (not self.reasons and len(self.evidence_ids) == 3):
            raise ValueError("clear readiness must match its proof and reasons")
        if any(not reason for reason in self.reasons):
            raise ValueError("clear-readiness reasons must be nonempty")
        _bounded_text("baseline ID", self.baseline_id)
        _bounded_text("authorization ID", self.authorization_id)
        _sha256("risk configuration", self.risk_configuration_fingerprint)
        if not (
            len(self.evidence_ids)
            == len(self.observed_snapshot_ids)
            == len(self.attestation_fingerprints)
            <= 3
        ):
            raise ValueError("clear-readiness proof fields must align")
        for value in self.evidence_ids:
            _sha256("reconciliation evidence", value)
        for value in self.attestation_fingerprints:
            _sha256("paper attestation", value)
        if self.emergency_generation < 1:
            raise ValueError("emergency generation must be positive")
        _utc("clear-readiness assessment", self.assessed_at)

    @property
    def proof_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class _PaperSnapshotAttestation:
    snapshot: PortfolioSnapshot
    adapter_version: str
    paper_origin: str
    completed_at: datetime

    def __post_init__(self) -> None:
        if self.snapshot.source is not SnapshotSource.ALPACA_PAPER:
            raise ValueError("only Alpaca-paper snapshots can be adapter-attested")
        if self.adapter_version != "alpaca-paper-reader-v1":
            raise ValueError("paper snapshot adapter version is unsupported")
        if self.paper_origin != "https://paper-api.alpaca.markets":
            raise ValueError("paper snapshot origin is unsupported")
        _utc("paper snapshot completion time", self.completed_at)
        if self.completed_at != max(
            self.snapshot.account_observed_at,
            self.snapshot.positions_observed_at,
            self.snapshot.orders_observed_at,
        ):
            raise ValueError("paper snapshot completion must match its final observation")

    @property
    def attestation_fingerprint(self) -> str:
        return fingerprint(self)


class ReconciliationStore(RiskStore):
    """Persist normalized snapshots, explicit flat baselines, and comparisons."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    snapshot_fingerprint TEXT NOT NULL UNIQUE,
                    snapshot_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TABLE IF NOT EXISTS reconciliation_baselines (
                    baseline_id TEXT PRIMARY KEY,
                    baseline_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TABLE IF NOT EXISTS reconciliation_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    evidence_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TABLE IF NOT EXISTS paper_snapshot_attestations (
                    snapshot_id TEXT PRIMARY KEY REFERENCES portfolio_snapshots(snapshot_id),
                    attestation_fingerprint TEXT NOT NULL UNIQUE,
                    attestation_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS portfolio_snapshots_no_update
                BEFORE UPDATE ON portfolio_snapshots BEGIN
                    SELECT RAISE(ABORT, 'portfolio snapshots are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS portfolio_snapshots_no_delete
                BEFORE DELETE ON portfolio_snapshots BEGIN
                    SELECT RAISE(ABORT, 'portfolio snapshots are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS reconciliation_baselines_no_update
                BEFORE UPDATE ON reconciliation_baselines BEGIN
                    SELECT RAISE(ABORT, 'reconciliation baselines are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS reconciliation_baselines_no_delete
                BEFORE DELETE ON reconciliation_baselines BEGIN
                    SELECT RAISE(ABORT, 'reconciliation baselines are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS reconciliation_evidence_no_update
                BEFORE UPDATE ON reconciliation_evidence BEGIN
                    SELECT RAISE(ABORT, 'reconciliation evidence is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS reconciliation_evidence_no_delete
                BEFORE DELETE ON reconciliation_evidence BEGIN
                    SELECT RAISE(ABORT, 'reconciliation evidence is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS paper_snapshot_attestations_no_update
                BEFORE UPDATE ON paper_snapshot_attestations BEGIN
                    SELECT RAISE(ABORT, 'paper snapshot attestations are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS paper_snapshot_attestations_no_delete
                BEFORE DELETE ON paper_snapshot_attestations BEGIN
                    SELECT RAISE(ABORT, 'paper snapshot attestations are immutable');
                END;
                """
            )
            connection.commit()
            self._verify_reconciliation(connection)

    def record_snapshot(
        self, snapshot: PortfolioSnapshot, *, recorded_at: datetime
    ) -> PortfolioSnapshot:
        _validate_snapshot_record(snapshot, recorded_at)
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_all(connection)
                self._record_snapshot(connection, snapshot, recorded_at)
                connection.commit()
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise JournalIntegrityError("snapshot already exists") from error
            except Exception:
                connection.rollback()
                raise
        return snapshot

    def _record_adapter_snapshot(
        self,
        snapshot: PortfolioSnapshot,
        *,
        adapter_version: str,
        paper_origin: str,
        recorded_at: datetime,
        _capability: object,
    ) -> PortfolioSnapshot:
        if _capability is not _ALPACA_READER_CAPABILITY:
            raise PermissionError("only the production Alpaca reader can attest a snapshot")
        attestation = _PaperSnapshotAttestation(
            snapshot=snapshot,
            adapter_version=adapter_version,
            paper_origin=paper_origin,
            completed_at=snapshot.orders_observed_at,
        )
        _validate_snapshot_record(snapshot, recorded_at)
        if recorded_at < attestation.completed_at:
            raise ValueError("attestation record time cannot predate completion")
        attestation_json = canonical_json(attestation)
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_all(connection)
                existing_snapshot = connection.execute(
                    "SELECT 1 FROM portfolio_snapshots WHERE snapshot_id = ?",
                    (snapshot.snapshot_id,),
                ).fetchone()
                existing_attestation = connection.execute(
                    """
                    SELECT attestation_json FROM paper_snapshot_attestations
                    WHERE snapshot_id = ?
                    """,
                    (snapshot.snapshot_id,),
                ).fetchone()
                if existing_snapshot is not None and existing_attestation is None:
                    raise JournalIntegrityError(
                        "caller-recorded snapshot cannot gain adapter provenance"
                    )
                if existing_attestation is not None:
                    if existing_attestation[0] != attestation_json:
                        raise JournalIntegrityError(
                            "snapshot ID is bound to a different paper attestation"
                        )
                    connection.commit()
                    return snapshot
                self._record_snapshot(connection, snapshot, recorded_at)
                snapshot_recorded_at = connection.execute(
                    "SELECT recorded_at FROM portfolio_snapshots WHERE snapshot_id = ?",
                    (snapshot.snapshot_id,),
                ).fetchone()
                if (
                    snapshot_recorded_at is None
                    or _parse_utc(snapshot_recorded_at[0]) > recorded_at
                ):
                    raise JournalIntegrityError("paper attestation cannot predate its snapshot")
                sequence = self._append_event(
                    connection,
                    occurred_at=recorded_at,
                    event_type="paper-snapshot-attested",
                    entity_type="paper-snapshot-attestation",
                    entity_id=snapshot.snapshot_id,
                    payload=canonicalize(attestation),
                )
                connection.execute(
                    "INSERT INTO paper_snapshot_attestations VALUES (?, ?, ?, ?, ?)",
                    (
                        snapshot.snapshot_id,
                        attestation.attestation_fingerprint,
                        attestation_json,
                        _utc_text(recorded_at),
                        sequence,
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise JournalIntegrityError("paper snapshot attestation already exists") from error
            except Exception:
                connection.rollback()
                raise
        return snapshot

    def _record_snapshot(
        self,
        connection: sqlite3.Connection,
        snapshot: PortfolioSnapshot,
        recorded_at: datetime,
    ) -> None:
        snapshot_json = canonical_json(snapshot)
        row = connection.execute(
            "SELECT snapshot_json FROM portfolio_snapshots WHERE snapshot_id = ?",
            (snapshot.snapshot_id,),
        ).fetchone()
        if row is not None:
            if row[0] != snapshot_json:
                raise JournalIntegrityError("snapshot ID is bound to different normalized state")
            return
        sequence = self._append_event(
            connection,
            occurred_at=recorded_at,
            event_type="portfolio-snapshot-recorded",
            entity_type="portfolio-snapshot",
            entity_id=snapshot.snapshot_id,
            payload=canonicalize(snapshot),
        )
        connection.execute(
            "INSERT INTO portfolio_snapshots VALUES (?, ?, ?, ?, ?)",
            (
                snapshot.snapshot_id,
                snapshot.snapshot_fingerprint,
                snapshot_json,
                _utc_text(recorded_at),
                sequence,
            ),
        )

    def create_flat_baseline(
        self,
        *,
        baseline_id: str,
        authorization_id: str,
        expected_snapshot_id: str,
        observed_snapshot_id: str,
        limits: RiskLimits,
        operator: str,
        reason: str,
        created_at: datetime,
    ) -> ReconciliationBaseline:
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                snapshots, attestations, baselines, _ = self._verify_all(connection)
                authorizations = self._verify_authorizations(connection)
                try:
                    authorization = authorizations[authorization_id]
                    expected = snapshots[expected_snapshot_id]
                    observed = snapshots[observed_snapshot_id]
                except KeyError as error:
                    raise HoldoutAccessError("baseline authority or snapshot is missing") from error
                comparison = reconcile(
                    expected,
                    observed,
                    compared_at=created_at,
                    maximum_age_seconds=limits.max_snapshot_age_seconds,
                    unresolved_mutations=0,
                )
                recorded_times = connection.execute(
                    """
                    SELECT recorded_at FROM portfolio_snapshots
                    WHERE snapshot_id IN (?, ?)
                    """,
                    (expected_snapshot_id, observed_snapshot_id),
                ).fetchall()
                if (
                    not comparison.clean
                    or expected.positions
                    or expected.open_client_order_ids
                    or observed_snapshot_id not in attestations
                    or authorization.account_id != expected.account_id
                    or authorization.risk_configuration_fingerprint
                    != limits.configuration_fingerprint
                    or limits.account_id != expected.account_id
                    or created_at < authorization.authorized_at
                    or created_at >= authorization.expires_at
                    or created_at < limits.effective_at
                    or created_at >= limits.expires_at
                    or len(recorded_times) != 2
                    or any(_parse_utc(row[0]) > created_at for row in recorded_times)
                ):
                    raise HoldoutAccessError(
                        "baseline requires matching fresh flat state and active authorization"
                    )
                baseline = ReconciliationBaseline(
                    baseline_id=baseline_id,
                    authorization_id=authorization_id,
                    expected_snapshot_id=expected_snapshot_id,
                    observed_snapshot_id=observed_snapshot_id,
                    expected_fingerprint=expected.snapshot_fingerprint,
                    observed_fingerprint=observed.snapshot_fingerprint,
                    account_id=expected.account_id,
                    risk_configuration_fingerprint=limits.configuration_fingerprint,
                    comparison_fingerprint=comparison.result_fingerprint,
                    maximum_age_seconds=limits.max_snapshot_age_seconds,
                    operator=operator,
                    reason=reason,
                    created_at=created_at,
                )
                existing = baselines.get(baseline_id)
                if existing is not None:
                    if existing != baseline:
                        raise JournalIntegrityError("baseline ID is bound to different content")
                    connection.commit()
                    return existing
                sequence = self._append_event(
                    connection,
                    occurred_at=created_at,
                    event_type="reconciliation-baseline-created",
                    entity_type="reconciliation-baseline",
                    entity_id=baseline_id,
                    payload=canonicalize(baseline),
                )
                connection.execute(
                    "INSERT INTO reconciliation_baselines VALUES (?, ?, ?)",
                    (baseline_id, canonical_json(baseline), sequence),
                )
                connection.commit()
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise JournalIntegrityError("baseline already exists") from error
            except Exception:
                connection.rollback()
                raise
        return baseline

    def record_reconciliation(
        self,
        *,
        baseline_id: str,
        observed_snapshot_id: str,
        compared_at: datetime,
        unresolved_mutations: int,
    ) -> ReconciliationEvidence:
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                snapshots, attestations, baselines, evidence_by_id = self._verify_all(connection)
                emergency = self._verify_emergency(connection)
                try:
                    baseline = baselines[baseline_id]
                    expected = snapshots[baseline.expected_snapshot_id]
                    observed = snapshots[observed_snapshot_id]
                except KeyError as error:
                    raise KeyError("reconciliation baseline or snapshot is missing") from error
                result = reconcile(
                    expected,
                    observed,
                    compared_at=compared_at,
                    maximum_age_seconds=baseline.maximum_age_seconds,
                    unresolved_mutations=unresolved_mutations,
                )
                recorded_at = connection.execute(
                    "SELECT recorded_at FROM portfolio_snapshots WHERE snapshot_id = ?",
                    (observed_snapshot_id,),
                ).fetchone()
                if (
                    compared_at < baseline.created_at
                    or observed_snapshot_id not in attestations
                    or recorded_at is None
                    or compared_at < _parse_utc(recorded_at[0])
                ):
                    raise ValueError("reconciliation cannot predate its durable evidence")
                evidence_id = fingerprint(
                    {
                        "baseline_id": baseline_id,
                        "observed_snapshot_id": observed_snapshot_id,
                        "maximum_age_seconds": baseline.maximum_age_seconds,
                        "unresolved_mutations": unresolved_mutations,
                        "result": result,
                    }
                )
                evidence = ReconciliationEvidence(
                    evidence_id,
                    baseline_id,
                    observed_snapshot_id,
                    baseline.maximum_age_seconds,
                    unresolved_mutations,
                    result,
                )
                existing = evidence_by_id.get(evidence_id)
                if existing is not None:
                    if not result.clean and not emergency.disabled:
                        self._disable_for_reconciliation(connection, result, compared_at, emergency)
                    connection.commit()
                    return existing
                sequence = self._append_event(
                    connection,
                    occurred_at=compared_at,
                    event_type="reconciliation-recorded",
                    entity_type="reconciliation-evidence",
                    entity_id=evidence_id,
                    payload=canonicalize(evidence),
                )
                connection.execute(
                    "INSERT INTO reconciliation_evidence VALUES (?, ?, ?)",
                    (evidence_id, canonical_json(evidence), sequence),
                )
                if not result.clean and not emergency.disabled:
                    self._disable_for_reconciliation(connection, result, compared_at, emergency)
                connection.commit()
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise JournalIntegrityError("reconciliation evidence already exists") from error
            except Exception:
                connection.rollback()
                raise
        return evidence

    def clear_emergency(
        self,
        *,
        clear_id: str,
        baseline_id: str,
        limits: RiskLimits,
        operator: str,
        reason: str,
        cleared_at: datetime,
    ) -> EmergencyState:
        _bounded_text("clear ID", clear_id)
        _bounded_text("operator", operator)
        _bounded_text("reason", reason)
        _utc("emergency-clear time", cleared_at)
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_all(connection)
                emergency = self._verify_emergency(connection)
                prior = next(
                    (
                        row
                        for row in connection.execute(
                            "SELECT payload_json FROM journal "
                            "WHERE event_type = 'emergency-cleared'"
                        ).fetchall()
                        if json.loads(row[0]).get("clear_id") == clear_id
                    ),
                    None,
                )
                if prior is not None:
                    stored = json.loads(prior[0])
                    request = {
                        "clear_id": clear_id,
                        "baseline_id": baseline_id,
                        "operator": operator,
                        "reason": reason,
                        "cleared_at": _utc_text(cleared_at),
                    }
                    if any(stored.get(key) != value for key, value in request.items()):
                        raise JournalIntegrityError("clear ID is bound to different content")
                    connection.commit()
                    return emergency
                if not emergency.disabled:
                    raise HoldoutAccessError("emergency disable is already clear")
                readiness = self.assess_emergency_clear_readiness(
                    baseline_id=baseline_id,
                    limits=limits,
                    assessed_at=cleared_at,
                    _connection=connection,
                )
                if not readiness.ready:
                    raise HoldoutAccessError(
                        "emergency clear requires stable clean reconciliation readiness"
                    )
                new_generation = emergency.generation + 1
                payload = {
                    "clear_id": clear_id,
                    "baseline_id": baseline_id,
                    "authorization_id": readiness.authorization_id,
                    "risk_configuration_fingerprint": limits.configuration_fingerprint,
                    "evidence_ids": readiness.evidence_ids,
                    "observed_snapshot_ids": readiness.observed_snapshot_ids,
                    "attestation_fingerprints": readiness.attestation_fingerprints,
                    "proof_fingerprint": readiness.proof_fingerprint,
                    "cause_fingerprint": readiness.proof_fingerprint,
                    "disabled": False,
                    "generation": new_generation,
                    "reason": reason,
                    "operator": operator,
                    "changed_at": _utc_text(cleared_at),
                    "cleared_at": _utc_text(cleared_at),
                }
                sequence = self._append_event(
                    connection,
                    occurred_at=cleared_at,
                    event_type="emergency-cleared",
                    entity_type="emergency-state",
                    entity_id="global",
                    payload=payload,
                )
                updated = connection.execute(
                    """
                    UPDATE emergency_state
                    SET disabled = 0, generation = ?, reason = ?, operator = ?,
                        changed_at = ?, journal_sequence = ?
                    WHERE singleton = 1 AND generation = ? AND disabled = 1
                    """,
                    (
                        new_generation,
                        reason,
                        operator,
                        payload["changed_at"],
                        sequence,
                        emergency.generation,
                    ),
                )
                if updated.rowcount != 1:
                    raise JournalIntegrityError("emergency state changed during clear")
                connection.commit()
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise JournalIntegrityError("emergency clear already exists") from error
            except Exception:
                connection.rollback()
                raise
        return EmergencyState(
            disabled=False,
            generation=new_generation,
            reason=reason,
            operator=operator,
            changed_at=cleared_at,
            journal_sequence=sequence,
        )

    def _disable_for_reconciliation(
        self,
        connection: sqlite3.Connection,
        result: ReconciliationResult,
        changed_at: datetime,
        emergency: EmergencyState,
    ) -> None:
        payload = {
            "cause_fingerprint": result.result_fingerprint,
            "disabled": True,
            "generation": emergency.generation + 1,
            "reason": "reconciliation mismatch",
            "operator": "system",
            "changed_at": _utc_text(changed_at),
        }
        sequence = self._append_event(
            connection,
            occurred_at=changed_at,
            event_type="emergency-disabled",
            entity_type="emergency-state",
            entity_id="global",
            payload=payload,
        )
        updated = connection.execute(
            """
            UPDATE emergency_state
            SET disabled = 1, generation = ?, reason = ?, operator = ?,
                changed_at = ?, journal_sequence = ?
            WHERE singleton = 1 AND generation = ? AND disabled = 0
            """,
            (
                payload["generation"],
                payload["reason"],
                payload["operator"],
                payload["changed_at"],
                sequence,
                emergency.generation,
            ),
        )
        if updated.rowcount != 1:
            raise JournalIntegrityError("emergency state changed during reconciliation disable")

    def assess_emergency_clear_readiness(
        self,
        *,
        baseline_id: str,
        limits: RiskLimits,
        assessed_at: datetime,
        _connection: sqlite3.Connection | None = None,
    ) -> EmergencyClearReadiness:
        _bounded_text("baseline ID", baseline_id)
        _utc("clear-readiness assessment", assessed_at)
        manager = self._connect() if _connection is None else nullcontext(_connection)
        with manager as connection:
            if _connection is None:
                connection.execute("BEGIN")
            snapshots, attestations, baselines, evidence_by_id = self._verify_all(connection)
            emergency = self._verify_emergency(connection)
            authorizations = self._verify_authorizations(connection)
            try:
                baseline = baselines[baseline_id]
                authorization = authorizations[baseline.authorization_id]
            except KeyError as error:
                raise HoldoutAccessError("clear-readiness authority is missing") from error
            sequenced = [
                (row[1], evidence_by_id[row[0]])
                for row in connection.execute(
                    "SELECT evidence_id, journal_sequence FROM reconciliation_evidence"
                ).fetchall()
                if evidence_by_id[row[0]].baseline_id == baseline_id
            ]
            latest = [item[1] for item in sorted(sequenced)[-3:]]

        reasons: list[str] = []
        if not emergency.disabled:
            reasons.append("emergency-already-clear")
        if (
            baseline.risk_configuration_fingerprint != limits.configuration_fingerprint
            or authorization.risk_configuration_fingerprint != limits.configuration_fingerprint
            or authorization.account_id != limits.account_id
        ):
            reasons.append("authority-or-limits-mismatch")
        if (
            assessed_at < limits.effective_at
            or assessed_at >= limits.expires_at
            or assessed_at < authorization.authorized_at
            or assessed_at >= authorization.expires_at
        ):
            reasons.append("authority-or-limits-inactive")
        if len(latest) < 3:
            reasons.append("insufficient-clean-samples")
        elif any(not item.result.clean or item.unresolved_mutations for item in latest):
            reasons.append("latest-samples-not-clean")

        snapshot_ids = tuple(item.observed_snapshot_id for item in latest)
        compared_at = tuple(item.result.compared_at for item in latest)
        attestation_values = tuple(attestations[snapshot_id] for snapshot_id in snapshot_ids)
        completion_times = tuple(value.completed_at for value in attestation_values)
        if len(set(snapshot_ids)) != len(snapshot_ids):
            reasons.append("samples-not-distinct")
        if len(latest) == 3:
            stability = limits.min_reconciliation_stability_seconds
            if completion_times[0] < baseline.created_at:
                reasons.append("samples-predate-baseline")
            if any(
                later <= earlier or (later - earlier).total_seconds() < stability
                for earlier, later in pairwise(compared_at)
            ) or any(
                later <= earlier or (later - earlier).total_seconds() < stability
                for earlier, later in pairwise(completion_times)
            ):
                reasons.append("samples-not-stable")
            latest_snapshot = snapshots[snapshot_ids[-1]]
            if compared_at[-1] > assessed_at or any(
                observed > assessed_at
                or (assessed_at - observed).total_seconds() > limits.max_snapshot_age_seconds
                for observed in (
                    latest_snapshot.account_observed_at,
                    latest_snapshot.positions_observed_at,
                    latest_snapshot.orders_observed_at,
                )
            ):
                reasons.append("latest-sample-stale-or-future")

        unique_reasons = tuple(dict.fromkeys(reasons))
        return EmergencyClearReadiness(
            ready=not unique_reasons and len(latest) == 3,
            reasons=unique_reasons,
            baseline_id=baseline_id,
            authorization_id=baseline.authorization_id,
            risk_configuration_fingerprint=limits.configuration_fingerprint,
            evidence_ids=tuple(item.evidence_id for item in latest),
            observed_snapshot_ids=snapshot_ids,
            attestation_fingerprints=tuple(
                value.attestation_fingerprint for value in attestation_values
            ),
            emergency_generation=emergency.generation,
            assessed_at=assessed_at,
        )

    def _verify_all(
        self, connection: sqlite3.Connection
    ) -> tuple[
        dict[str, PortfolioSnapshot],
        dict[str, _PaperSnapshotAttestation],
        dict[str, ReconciliationBaseline],
        dict[str, ReconciliationEvidence],
    ]:
        self._verify_connection(connection)
        self._verify_emergency(connection)
        self._verify_authorizations(connection)
        self._verify_decisions(connection)
        return self._verify_reconciliation(connection)

    def _verify_reconciliation(
        self, connection: sqlite3.Connection
    ) -> tuple[
        dict[str, PortfolioSnapshot],
        dict[str, _PaperSnapshotAttestation],
        dict[str, ReconciliationBaseline],
        dict[str, ReconciliationEvidence],
    ]:
        snapshots: dict[str, PortfolioSnapshot] = {}
        snapshot_recorded_at: dict[str, datetime] = {}
        rows = connection.execute(
            """
            SELECT snapshot_id, snapshot_fingerprint, snapshot_json, recorded_at, journal_sequence
            FROM portfolio_snapshots
            """
        ).fetchall()
        _require_event_count(connection, "portfolio-snapshot-recorded", len(rows))
        for row in rows:
            try:
                snapshot = _decode_snapshot(json.loads(row[2]))
                recorded_at = _parse_utc(row[3])
            except (ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("stored portfolio snapshot is invalid") from error
            if (
                row[0] != snapshot.snapshot_id
                or row[1] != snapshot.snapshot_fingerprint
                or row[2] != canonical_json(snapshot)
                or not _event_matches(
                    connection,
                    row[4],
                    row[3],
                    "portfolio-snapshot-recorded",
                    "portfolio-snapshot",
                    row[0],
                    canonical_json(snapshot),
                )
            ):
                raise JournalIntegrityError("portfolio snapshot does not match its journal event")
            snapshots[snapshot.snapshot_id] = snapshot
            snapshot_recorded_at[snapshot.snapshot_id] = recorded_at

        attestations: dict[str, _PaperSnapshotAttestation] = {}
        rows = connection.execute(
            """
            SELECT snapshot_id, attestation_fingerprint, attestation_json, recorded_at,
                   journal_sequence
            FROM paper_snapshot_attestations
            """
        ).fetchall()
        _require_event_count(connection, "paper-snapshot-attested", len(rows))
        for row in rows:
            try:
                attestation = _decode_attestation(json.loads(row[2]))
                snapshot = snapshots[row[0]]
                attestation_recorded_at = _parse_utc(row[3])
            except (KeyError, ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError(
                    "stored paper snapshot attestation is invalid"
                ) from error
            if (
                attestation.snapshot != snapshot
                or row[1] != attestation.attestation_fingerprint
                or row[2] != canonical_json(attestation)
                or attestation_recorded_at < attestation.completed_at
                or attestation_recorded_at < snapshot_recorded_at[row[0]]
                or not _event_matches(
                    connection,
                    row[4],
                    row[3],
                    "paper-snapshot-attested",
                    "paper-snapshot-attestation",
                    row[0],
                    canonical_json(attestation),
                )
            ):
                raise JournalIntegrityError("paper snapshot attestation differs from its evidence")
            attestations[row[0]] = attestation

        authorizations = self._verify_authorizations(connection)
        baselines: dict[str, ReconciliationBaseline] = {}
        rows = connection.execute(
            "SELECT baseline_id, baseline_json, journal_sequence FROM reconciliation_baselines"
        ).fetchall()
        _require_event_count(connection, "reconciliation-baseline-created", len(rows))
        for row in rows:
            try:
                baseline = _decode_baseline(json.loads(row[1]))
                expected = snapshots[baseline.expected_snapshot_id]
                observed = snapshots[baseline.observed_snapshot_id]
                authorization = authorizations[baseline.authorization_id]
                comparison = reconcile(
                    expected,
                    observed,
                    compared_at=baseline.created_at,
                    maximum_age_seconds=baseline.maximum_age_seconds,
                    unresolved_mutations=0,
                )
            except (KeyError, ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("stored reconciliation baseline is invalid") from error
            baseline_recorded_times = connection.execute(
                """
                SELECT recorded_at FROM portfolio_snapshots
                WHERE snapshot_id IN (?, ?)
                """,
                (baseline.expected_snapshot_id, baseline.observed_snapshot_id),
            ).fetchall()
            if (
                row[0] != baseline.baseline_id
                or row[1] != canonical_json(baseline)
                or not comparison.clean
                or comparison.result_fingerprint != baseline.comparison_fingerprint
                or baseline.expected_fingerprint != expected.snapshot_fingerprint
                or baseline.observed_fingerprint != observed.snapshot_fingerprint
                or expected.positions
                or expected.open_client_order_ids
                or baseline.observed_snapshot_id not in attestations
                or authorization.account_id != baseline.account_id
                or authorization.risk_configuration_fingerprint
                != baseline.risk_configuration_fingerprint
                or baseline.created_at < authorization.authorized_at
                or baseline.created_at >= authorization.expires_at
                or len(baseline_recorded_times) != 2
                or any(
                    _parse_utc(recorded[0]) > baseline.created_at
                    for recorded in baseline_recorded_times
                )
                or not _event_matches(
                    connection,
                    row[2],
                    _utc_text(baseline.created_at),
                    "reconciliation-baseline-created",
                    "reconciliation-baseline",
                    row[0],
                    canonical_json(baseline),
                )
            ):
                raise JournalIntegrityError("reconciliation baseline does not match its evidence")
            baselines[baseline.baseline_id] = baseline

        evidence_by_id: dict[str, ReconciliationEvidence] = {}
        rows = connection.execute(
            "SELECT evidence_id, evidence_json, journal_sequence FROM reconciliation_evidence"
        ).fetchall()
        _require_event_count(connection, "reconciliation-recorded", len(rows))
        for row in rows:
            try:
                evidence = _decode_evidence(json.loads(row[1]))
                baseline = baselines[evidence.baseline_id]
                expected = snapshots[baseline.expected_snapshot_id]
                observed = snapshots[evidence.observed_snapshot_id]
                result = reconcile(
                    expected,
                    observed,
                    compared_at=evidence.result.compared_at,
                    maximum_age_seconds=evidence.maximum_age_seconds,
                    unresolved_mutations=evidence.unresolved_mutations,
                )
                observed_recorded_at = connection.execute(
                    "SELECT recorded_at FROM portfolio_snapshots WHERE snapshot_id = ?",
                    (evidence.observed_snapshot_id,),
                ).fetchone()
            except (KeyError, ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("stored reconciliation evidence is invalid") from error
            expected_id = fingerprint(
                {
                    "baseline_id": evidence.baseline_id,
                    "observed_snapshot_id": evidence.observed_snapshot_id,
                    "maximum_age_seconds": evidence.maximum_age_seconds,
                    "unresolved_mutations": evidence.unresolved_mutations,
                    "result": result,
                }
            )
            if (
                row[0] != evidence.evidence_id
                or evidence.evidence_id != expected_id
                or evidence.result != result
                or evidence.observed_snapshot_id not in attestations
                or row[1] != canonical_json(evidence)
                or result.compared_at < baseline.created_at
                or observed_recorded_at is None
                or result.compared_at < _parse_utc(observed_recorded_at[0])
                or not _event_matches(
                    connection,
                    row[2],
                    _utc_text(result.compared_at),
                    "reconciliation-recorded",
                    "reconciliation-evidence",
                    row[0],
                    canonical_json(evidence),
                )
            ):
                raise JournalIntegrityError("reconciliation evidence does not match its inputs")
            evidence_by_id[evidence.evidence_id] = evidence
        return snapshots, attestations, baselines, evidence_by_id


def _decode_snapshot(value: Any) -> PortfolioSnapshot:
    if not isinstance(value, dict):
        raise ValueError("portfolio snapshot must be an object")
    try:
        positions = tuple(PositionSnapshot(**item) for item in value["positions"])
        open_orders = tuple(
            OpenOrderSnapshot(
                **{
                    **item,
                    "limit_price": (
                        Decimal(item["limit_price"]) if item["limit_price"] is not None else None
                    ),
                }
            )
            for item in value["open_orders"]
        )
        return PortfolioSnapshot(
            **{
                **value,
                "source": SnapshotSource(value["source"]),
                "cash": Decimal(value["cash"]),
                "equity": Decimal(value["equity"]),
                "buying_power": Decimal(value["buying_power"]),
                "positions": positions,
                "open_orders": open_orders,
                "account_observed_at": _parse_utc(value["account_observed_at"]),
                "positions_observed_at": _parse_utc(value["positions_observed_at"]),
                "orders_observed_at": _parse_utc(value["orders_observed_at"]),
            }
        )
    except (KeyError, TypeError, ArithmeticError) as error:
        raise ValueError("portfolio snapshot fields differ") from error


def _decode_attestation(value: Any) -> _PaperSnapshotAttestation:
    if not isinstance(value, dict):
        raise ValueError("paper snapshot attestation must be an object")
    try:
        return _PaperSnapshotAttestation(
            snapshot=_decode_snapshot(value["snapshot"]),
            adapter_version=value["adapter_version"],
            paper_origin=value["paper_origin"],
            completed_at=_parse_utc(value["completed_at"]),
        )
    except (KeyError, TypeError) as error:
        raise ValueError("paper snapshot attestation fields differ") from error


def _decode_baseline(value: Any) -> ReconciliationBaseline:
    if not isinstance(value, dict):
        raise ValueError("reconciliation baseline must be an object")
    try:
        return ReconciliationBaseline(**{**value, "created_at": _parse_utc(value["created_at"])})
    except (KeyError, TypeError) as error:
        raise ValueError("reconciliation baseline fields differ") from error


def _decode_evidence(value: Any) -> ReconciliationEvidence:
    if not isinstance(value, dict) or not isinstance(value.get("result"), dict):
        raise ValueError("reconciliation evidence must be an object")
    result_value = value["result"]
    try:
        result = ReconciliationResult(
            **{
                **result_value,
                "reasons": tuple(result_value["reasons"]),
                "compared_at": _parse_utc(result_value["compared_at"]),
            }
        )
        return ReconciliationEvidence(**{**value, "result": result})
    except (KeyError, TypeError) as error:
        raise ValueError("reconciliation evidence fields differ") from error


def _event_matches(
    connection: sqlite3.Connection,
    sequence: int,
    occurred_at: str,
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload_json: str,
) -> bool:
    row = connection.execute(
        """
        SELECT occurred_at, event_type, entity_type, entity_id, payload_json
        FROM journal WHERE sequence = ?
        """,
        (sequence,),
    ).fetchone()
    return bool(row == (occurred_at, event_type, entity_type, entity_id, payload_json))


def _require_event_count(connection: sqlite3.Connection, event_type: str, count: int) -> None:
    stored = connection.execute(
        "SELECT COUNT(*) FROM journal WHERE event_type = ?", (event_type,)
    ).fetchone()[0]
    if stored != count:
        raise JournalIntegrityError(f"{event_type} journal count differs")


def _bounded_text(name: str, value: str) -> None:
    if not value or value != value.strip() or len(value) > 500:
        raise ValueError(f"{name} must be nonempty, trimmed, and at most 500 characters")


def _validate_snapshot_record(snapshot: PortfolioSnapshot, recorded_at: datetime) -> None:
    _utc("snapshot record time", recorded_at)
    if any(
        observed_at > recorded_at
        for observed_at in (
            snapshot.account_observed_at,
            snapshot.positions_observed_at,
            snapshot.orders_observed_at,
        )
    ):
        raise ValueError("snapshot record time cannot predate an observation")


def _sha256(name: str, value: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} fingerprint must be a lowercase SHA-256 value")


def _utc(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{name} must be UTC-aware")


def _utc_text(value: datetime) -> str:
    result = canonicalize(value)
    assert isinstance(result, str)
    return result


def _parse_utc(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _utc("stored timestamp", timestamp)
    return timestamp
