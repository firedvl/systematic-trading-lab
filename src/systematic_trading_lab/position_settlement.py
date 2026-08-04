"""Immutable proof that expected positions reached a later paper snapshot."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

from .broker_events import BrokerEventStore, ExpectedPositionAdvance
from .execution import JournalIntegrityError
from .fingerprints import canonical_json, canonicalize, fingerprint
from .orders import OrderState
from .reconciliation import (
    ReconciliationStore,
    _decode_attestation,
    _decode_baseline,
    _decode_snapshot,
    _PaperSnapshotAttestationV2,
)
from .reconciliation import (
    _decode_evidence as _decode_reconciliation,
)
from .risk import RiskLimits

_TERMINAL_STATES = {OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED}
_FILL_SETTLEMENT_MODE = "fill-settlement-v1"
_FLAT_BASELINE_SETTLEMENT_MODE = "flat-baseline-v1"


@dataclass(frozen=True)
class PositionSettlementEvidence:
    proof_id: str
    baseline_id: str
    authorization_id: str
    account_id: str
    risk_configuration_fingerprint: str
    advance_fingerprint: str
    observed_snapshot_id: str
    observed_snapshot_fingerprint: str
    attestation_fingerprint: str
    terminal_orders: tuple[tuple[str, str, int], ...]
    emergency_generation: int
    settled_at: datetime
    settlement_mode: str = _FILL_SETTLEMENT_MODE
    reconciliation_evidence_id: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("proof ID", self.proof_id),
            ("baseline ID", self.baseline_id),
            ("authorization ID", self.authorization_id),
            ("account ID", self.account_id),
            ("observed snapshot ID", self.observed_snapshot_id),
        ):
            if not value or value != value.strip() or len(value) > 128:
                raise ValueError(f"{name} is invalid")
        for name, value in (
            ("risk configuration", self.risk_configuration_fingerprint),
            ("observed snapshot", self.observed_snapshot_fingerprint),
            ("paper attestation", self.attestation_fingerprint),
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{name} fingerprint is invalid")
        if self.settlement_mode not in {
            _FILL_SETTLEMENT_MODE,
            _FLAT_BASELINE_SETTLEMENT_MODE,
        }:
            raise ValueError("settlement mode is unsupported")
        if self.settlement_mode == _FILL_SETTLEMENT_MODE:
            if (
                len(self.advance_fingerprint) != 64
                or any(
                    character not in "0123456789abcdef" for character in self.advance_fingerprint
                )
                or self.reconciliation_evidence_id is not None
            ):
                raise ValueError("fill settlement lineage is invalid")
        elif (
            self.advance_fingerprint
            or self.terminal_orders
            or self.reconciliation_evidence_id is None
            or len(self.reconciliation_evidence_id) != 64
            or any(
                character not in "0123456789abcdef" for character in self.reconciliation_evidence_id
            )
        ):
            raise ValueError("flat baseline settlement lineage is invalid")
        if self.emergency_generation < 1:
            raise ValueError("emergency generation must be positive")
        if (
            self.terminal_orders != tuple(sorted(self.terminal_orders, key=lambda item: item[0]))
            or len({item[0] for item in self.terminal_orders}) != len(self.terminal_orders)
            or any(
                not order_id
                or state not in {item.value for item in _TERMINAL_STATES}
                or sequence < 1
                for order_id, state, sequence in self.terminal_orders
            )
        ):
            raise ValueError("terminal order proof is invalid")
        if self.settled_at.tzinfo is None or self.settled_at.utcoffset() != UTC.utcoffset(
            self.settled_at
        ):
            raise ValueError("settlement time must be UTC-aware")

    @property
    def proof_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class SettlementCapacityAssessment:
    ready: bool
    reasons: tuple[str, ...]
    proof_id: str
    reservation_ids: tuple[str, ...]
    observed_snapshot_id: str
    observed_cash: Decimal
    observed_equity: Decimal
    observed_buying_power: Decimal
    emergency_generation: int
    assessed_at: datetime

    def __post_init__(self) -> None:
        if self.ready != (not self.reasons):
            raise ValueError("capacity readiness must match its reasons")
        if any(not reason for reason in self.reasons):
            raise ValueError("capacity readiness reasons must be nonempty")
        if self.reservation_ids != tuple(sorted(set(self.reservation_ids))):
            raise ValueError("capacity readiness reservations must be sorted and unique")
        for name, amount in (
            ("cash", self.observed_cash),
            ("equity", self.observed_equity),
            ("buying power", self.observed_buying_power),
        ):
            if not amount.is_finite() or amount < 0:
                raise ValueError(f"observed {name} must be finite and nonnegative")
        if self.emergency_generation < 1:
            raise ValueError("emergency generation must be positive")
        if self.assessed_at.tzinfo is None or self.assessed_at.utcoffset() != UTC.utcoffset(
            self.assessed_at
        ):
            raise ValueError("capacity assessment time must be UTC-aware")


class PositionSettlementStore(BrokerEventStore):
    """Prove position settlement without deriving account-wide accounting."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS position_settlement_evidence (
                    proof_id TEXT PRIMARY KEY,
                    baseline_id TEXT NOT NULL REFERENCES reconciliation_baselines(baseline_id),
                    advance_fingerprint TEXT NOT NULL,
                    observed_snapshot_id TEXT NOT NULL REFERENCES portfolio_snapshots(snapshot_id),
                    evidence_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS position_settlement_evidence_no_update
                BEFORE UPDATE ON position_settlement_evidence BEGIN
                    SELECT RAISE(ABORT, 'position settlement evidence is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS position_settlement_evidence_no_delete
                BEFORE DELETE ON position_settlement_evidence BEGIN
                    SELECT RAISE(ABORT, 'position settlement evidence is immutable');
                END;
                """
            )
            connection.commit()
            self._verify_settlements(connection)

    def record_settlement(
        self,
        *,
        proof_id: str,
        baseline_id: str,
        observed_snapshot_id: str,
        settled_at: datetime,
    ) -> PositionSettlementEvidence:
        if settled_at.tzinfo is None or settled_at.utcoffset() != UTC.utcoffset(settled_at):
            raise ValueError("settlement time must be UTC-aware")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._verify_connection(connection)
            self._verify_reservations(connection)
            self._verify_releases(connection)
            self._verify_orders(connection)
            events = self._verify_broker_events(connection)
            advances = self._verify_expected_position_advances(connection, events)
            settlements = self._verify_settlements(connection)
            snapshots, attestations, baselines, _ = ReconciliationStore._verify_reconciliation(
                cast(ReconciliationStore, self), connection
            )
            emergency = self._verify_emergency(connection)
            try:
                baseline = baselines[baseline_id]
                observed = snapshots[observed_snapshot_id]
                attestation = attestations[observed_snapshot_id]
                lineage = [item for item in advances.values() if item.baseline_id == baseline_id]
                advance = lineage[-1]
            except (KeyError, IndexError) as error:
                raise JournalIntegrityError("position settlement authority is missing") from error
            self._require_complete_lineage(
                connection,
                baseline=baseline,
                baseline_id=baseline_id,
                advances=advances,
            )
            observation_times = (
                observed.account_observed_at,
                observed.positions_observed_at,
                observed.orders_observed_at,
            )
            snapshot_recorded_at = connection.execute(
                "SELECT recorded_at FROM portfolio_snapshots WHERE snapshot_id = ?",
                (observed_snapshot_id,),
            ).fetchone()
            states = connection.execute(
                "SELECT o.order_id, o.state, o.changed_at, o.journal_sequence FROM orders o "
                "JOIN capacity_reservations r ON r.reservation_id = o.reservation_id "
                "WHERE json_extract(r.reservation_json, '$.account_id') = ?",
                (baseline.account_id,),
            ).fetchall()
            if (
                emergency.disabled
                or emergency.changed_at > advance.advanced_at
                or observed.account_id != baseline.account_id
                or observed.positions != advance.positions
                or observed.open_orders
                or not observed.account_ready
                or snapshot_recorded_at is None
                or any(OrderState(row[1]) not in _TERMINAL_STATES for row in states)
                or any(_parse_utc(str(row[2])) > observed.orders_observed_at for row in states)
                or any(timestamp < advance.advanced_at for timestamp in observation_times)
                or any(
                    timestamp > settled_at
                    or (settled_at - timestamp).total_seconds() > baseline.maximum_age_seconds
                    for timestamp in observation_times
                )
                or _parse_utc(str(snapshot_recorded_at[0])) > settled_at
            ):
                raise JournalIntegrityError("position settlement proof is not complete and current")
            evidence = PositionSettlementEvidence(
                proof_id=proof_id,
                baseline_id=baseline_id,
                authorization_id=baseline.authorization_id,
                account_id=baseline.account_id,
                risk_configuration_fingerprint=baseline.risk_configuration_fingerprint,
                advance_fingerprint=advance.advance_fingerprint,
                observed_snapshot_id=observed_snapshot_id,
                observed_snapshot_fingerprint=observed.snapshot_fingerprint,
                attestation_fingerprint=attestation.attestation_fingerprint,
                terminal_orders=tuple(
                    sorted((str(row[0]), str(row[1]), int(row[3])) for row in states)
                ),
                emergency_generation=emergency.generation,
                settled_at=settled_at,
            )
            existing = settlements.get(proof_id)
            if existing is not None:
                if existing != evidence:
                    raise JournalIntegrityError("settlement proof ID is bound to different content")
                connection.commit()
                return existing
            sequence = self._append_event(
                connection,
                occurred_at=settled_at,
                event_type="position-settlement-proved",
                entity_type="position-settlement",
                entity_id=proof_id,
                payload=canonicalize(evidence),
            )
            connection.execute(
                "INSERT INTO position_settlement_evidence VALUES (?, ?, ?, ?, ?, ?)",
                (
                    proof_id,
                    baseline_id,
                    advance.advance_fingerprint,
                    observed_snapshot_id,
                    canonical_json(evidence),
                    sequence,
                ),
            )
            connection.commit()
        return evidence

    def record_flat_baseline_settlement(
        self,
        *,
        proof_id: str,
        baseline_id: str,
        observed_snapshot_id: str,
        reconciliation_evidence_id: str,
        limits: RiskLimits,
        settled_at: datetime,
    ) -> PositionSettlementEvidence:
        """Checkpoint a clean, post-clear flat state without inventing execution lineage."""
        if settled_at.tzinfo is None or settled_at.utcoffset() != UTC.utcoffset(settled_at):
            raise ValueError("settlement time must be UTC-aware")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._verify_connection(connection)
            self._verify_reservations(connection)
            self._verify_releases(connection)
            self._verify_orders(connection)
            events = self._verify_broker_events(connection)
            self._verify_expected_position_advances(connection, events)
            settlements = self._verify_settlements(connection)
            snapshots, attestations, baselines, reconciliations = (
                ReconciliationStore._verify_reconciliation(
                    cast(ReconciliationStore, self), connection
                )
            )
            authorizations = self._verify_authorizations(connection)
            emergency = self._verify_emergency(connection)
            try:
                baseline = baselines[baseline_id]
                observed = snapshots[observed_snapshot_id]
                attestation = attestations[observed_snapshot_id]
                reconciliation = reconciliations[reconciliation_evidence_id]
                authorization = authorizations[baseline.authorization_id]
            except KeyError as error:
                raise JournalIntegrityError(
                    "flat baseline settlement authority is missing"
                ) from error
            snapshot_row = connection.execute(
                "SELECT recorded_at FROM portfolio_snapshots WHERE snapshot_id = ?",
                (observed_snapshot_id,),
            ).fetchone()
            reconciliation_row = connection.execute(
                "SELECT journal_sequence FROM reconciliation_evidence WHERE evidence_id = ?",
                (reconciliation_evidence_id,),
            ).fetchone()
            execution_artifact = connection.execute(
                "SELECT 1 FROM capacity_reservations WHERE authorization_id = ? LIMIT 1",
                (authorization.authorization_id,),
            ).fetchone()
            advance = connection.execute(
                "SELECT 1 FROM expected_position_advances WHERE baseline_id = ? LIMIT 1",
                (baseline_id,),
            ).fetchone()
            if (
                emergency.disabled
                or not isinstance(attestation, _PaperSnapshotAttestationV2)
                or reconciliation.baseline_id != baseline_id
                or reconciliation.observed_snapshot_id != observed_snapshot_id
                or not reconciliation.result.clean
                or reconciliation.unresolved_mutations != 0
                or authorization.account_id != limits.account_id
                or authorization.risk_configuration_fingerprint != limits.configuration_fingerprint
                or baseline.account_id != limits.account_id
                or baseline.risk_configuration_fingerprint != limits.configuration_fingerprint
                or observed.account_id != limits.account_id
                or observed.positions
                or observed.open_orders
                or not observed.account_ready
                or snapshot_row is None
                or reconciliation_row is None
                or execution_artifact is not None
                or advance is not None
                or settled_at < authorization.authorized_at
                or settled_at >= authorization.expires_at
                or settled_at < limits.effective_at
                or settled_at >= limits.expires_at
                or any(
                    timestamp <= emergency.changed_at
                    or timestamp > settled_at
                    or (settled_at - timestamp).total_seconds() > baseline.maximum_age_seconds
                    for timestamp in (
                        observed.account_observed_at,
                        observed.positions_observed_at,
                        observed.orders_observed_at,
                    )
                )
                or _parse_utc(str(snapshot_row[0])) <= emergency.changed_at
                or _parse_utc(str(snapshot_row[0])) > settled_at
                or int(reconciliation_row[0]) <= emergency.journal_sequence
            ):
                raise JournalIntegrityError("flat baseline settlement is not complete and current")
            evidence = PositionSettlementEvidence(
                proof_id=proof_id,
                baseline_id=baseline_id,
                authorization_id=baseline.authorization_id,
                account_id=baseline.account_id,
                risk_configuration_fingerprint=baseline.risk_configuration_fingerprint,
                advance_fingerprint="",
                observed_snapshot_id=observed_snapshot_id,
                observed_snapshot_fingerprint=observed.snapshot_fingerprint,
                attestation_fingerprint=attestation.attestation_fingerprint,
                terminal_orders=(),
                emergency_generation=emergency.generation,
                settled_at=settled_at,
                settlement_mode=_FLAT_BASELINE_SETTLEMENT_MODE,
                reconciliation_evidence_id=reconciliation_evidence_id,
            )
            existing = settlements.get(proof_id)
            if existing is not None:
                if existing != evidence:
                    raise JournalIntegrityError("settlement proof ID is bound to different content")
                connection.commit()
                return existing
            sequence = self._append_event(
                connection,
                occurred_at=settled_at,
                event_type="position-settlement-proved",
                entity_type="position-settlement",
                entity_id=proof_id,
                payload=canonicalize(evidence),
            )
            connection.execute(
                "INSERT INTO position_settlement_evidence VALUES (?, ?, ?, ?, ?, ?)",
                (
                    proof_id,
                    baseline_id,
                    "",
                    observed_snapshot_id,
                    canonical_json(evidence),
                    sequence,
                ),
            )
            connection.commit()
        return evidence

    def assess_capacity(
        self, proof_id: str, *, assessed_at: datetime
    ) -> SettlementCapacityAssessment:
        if assessed_at.tzinfo is None or assessed_at.utcoffset() != UTC.utcoffset(assessed_at):
            raise ValueError("capacity assessment time must be UTC-aware")
        with self._connect() as connection:
            connection.execute("BEGIN")
            self._verify_connection(connection)
            self._verify_reservations(connection)
            self._verify_releases(connection)
            self._verify_orders(connection)
            events = self._verify_broker_events(connection)
            advances = self._verify_expected_position_advances(connection, events)
            settlements = self._verify_settlements(connection)
            snapshots, _, baselines, _ = ReconciliationStore._verify_reconciliation(
                cast(ReconciliationStore, self), connection
            )
            emergency = self._verify_emergency(connection)
            try:
                evidence = settlements[proof_id]
                baseline = baselines[evidence.baseline_id]
                snapshot = snapshots[evidence.observed_snapshot_id]
                proof_row = connection.execute(
                    "SELECT journal_sequence FROM position_settlement_evidence WHERE proof_id = ?",
                    (proof_id,),
                ).fetchone()
                proof_sequence = int(proof_row[0])
            except (KeyError, TypeError) as error:
                raise KeyError(proof_id) from error
            lineage = [
                item for item in advances.values() if item.baseline_id == baseline.baseline_id
            ]
            reasons = ["context-provenance-missing"]
            if not lineage or lineage[-1].advance_fingerprint != evidence.advance_fingerprint:
                reasons.append("lineage-changed")
            if emergency.disabled or emergency.generation != evidence.emergency_generation:
                reasons.append("emergency-state-changed")
            if any(
                timestamp > assessed_at
                or (assessed_at - timestamp).total_seconds() > baseline.maximum_age_seconds
                for timestamp in (
                    snapshot.account_observed_at,
                    snapshot.positions_observed_at,
                    snapshot.orders_observed_at,
                )
            ):
                reasons.append("settlement-snapshot-stale-or-future")
            later_order = connection.execute(
                "SELECT 1 FROM journal j JOIN orders o ON o.order_id = j.entity_id "
                "JOIN capacity_reservations r ON r.reservation_id = o.reservation_id "
                "WHERE j.entity_type = 'order' AND j.sequence > ? "
                "AND json_extract(r.reservation_json, '$.account_id') = ? LIMIT 1",
                (proof_sequence, evidence.account_id),
            ).fetchone()
            if later_order is not None:
                reasons.append("order-state-changed")
            terminal_order_ids = {item[0] for item in evidence.terminal_orders}
            rows = connection.execute(
                "SELECT r.reservation_id, r.expires_at, o.order_id, x.reservation_id, "
                "COALESCE(MAX(CAST(json_extract(b.event_json, "
                "'$.cumulative_filled_quantity') AS INTEGER)), 0) "
                "FROM capacity_reservations r "
                "LEFT JOIN orders o ON o.reservation_id = r.reservation_id "
                "LEFT JOIN broker_events b ON b.client_order_id = o.order_id "
                "LEFT JOIN capacity_releases x ON x.reservation_id = r.reservation_id "
                "WHERE json_extract(r.reservation_json, '$.account_id') = ? "
                "GROUP BY r.reservation_id, r.expires_at, o.order_id, x.reservation_id",
                (evidence.account_id,),
            ).fetchall()
            reservation_ids = tuple(
                sorted(
                    str(row[0]) for row in rows if row[2] in terminal_order_ids and int(row[4]) > 0
                )
            )
            if not reservation_ids:
                reasons.append("no-positive-fill-reservation")
            if any(
                row[0] in reservation_ids
                and (_parse_utc(str(row[1])) <= assessed_at or row[3] is not None)
                for row in rows
            ):
                reasons.append("reservation-inactive")
            if any(
                row[3] is None
                and _parse_utc(str(row[1])) > assessed_at
                and row[0] not in reservation_ids
                for row in rows
            ):
                reasons.append("unrelated-active-reservation")
        return SettlementCapacityAssessment(
            ready=not reasons,
            reasons=tuple(reasons),
            proof_id=proof_id,
            reservation_ids=reservation_ids,
            observed_snapshot_id=snapshot.snapshot_id,
            observed_cash=snapshot.cash,
            observed_equity=snapshot.equity,
            observed_buying_power=snapshot.buying_power,
            emergency_generation=emergency.generation,
            assessed_at=assessed_at,
        )

    def _verify_settlements(
        self, connection: sqlite3.Connection
    ) -> dict[str, PositionSettlementEvidence]:
        rows = connection.execute(
            "SELECT proof_id, baseline_id, advance_fingerprint, observed_snapshot_id, "
            "evidence_json, journal_sequence FROM position_settlement_evidence"
        ).fetchall()
        count = connection.execute(
            "SELECT COUNT(*) FROM journal WHERE event_type = 'position-settlement-proved'"
        ).fetchone()[0]
        if len(rows) != count:
            raise JournalIntegrityError("position settlement and journal counts differ")
        result: dict[str, PositionSettlementEvidence] = {}
        for row in rows:
            try:
                evidence = _decode_evidence(json.loads(row[4]))
                advance_row = (
                    connection.execute(
                        "SELECT advance_json, journal_sequence FROM expected_position_advances "
                        "WHERE advance_fingerprint = ? AND baseline_id = ?",
                        (evidence.advance_fingerprint, evidence.baseline_id),
                    ).fetchone()
                    if evidence.settlement_mode == _FILL_SETTLEMENT_MODE
                    else None
                )
                snapshot_row = connection.execute(
                    "SELECT snapshot_json FROM portfolio_snapshots WHERE snapshot_id = ?",
                    (evidence.observed_snapshot_id,),
                ).fetchone()
                attestation_row = connection.execute(
                    "SELECT attestation_json FROM paper_snapshot_attestations "
                    "WHERE snapshot_id = ?",
                    (evidence.observed_snapshot_id,),
                ).fetchone()
                baseline_row = connection.execute(
                    "SELECT baseline_json FROM reconciliation_baselines WHERE baseline_id = ?",
                    (evidence.baseline_id,),
                ).fetchone()
                if snapshot_row is None or attestation_row is None or baseline_row is None:
                    raise ValueError("settlement reference is missing")
                advance = (
                    _decode_advance(json.loads(advance_row[0])) if advance_row is not None else None
                )
                snapshot = _decode_snapshot(json.loads(snapshot_row[0]))
                attestation = _decode_attestation(json.loads(attestation_row[0]))
                baseline = _decode_baseline(json.loads(baseline_row[0]))
            except (ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("stored position settlement is invalid") from error
            payload = canonical_json(evidence)
            journal = connection.execute(
                "SELECT occurred_at, event_type, entity_type, entity_id, payload_json "
                "FROM journal WHERE sequence = ?",
                (row[5],),
            ).fetchone()
            later_advance = connection.execute(
                "SELECT 1 FROM expected_position_advances WHERE baseline_id = ? "
                "AND journal_sequence > ? AND journal_sequence < ? LIMIT 1",
                (
                    evidence.baseline_id,
                    -1 if advance_row is None else advance_row[1],
                    row[5],
                ),
            ).fetchone()
            emergency_event = connection.execute(
                "SELECT occurred_at, payload_json, sequence FROM journal WHERE event_type IN "
                "('emergency-initialized', 'emergency-cleared', 'emergency-disabled') "
                "AND sequence < ? ORDER BY sequence DESC LIMIT 1",
                (row[5],),
            ).fetchone()
            emergency_payload = {} if emergency_event is None else json.loads(emergency_event[1])
            terminal_orders = _terminal_orders_at(
                connection,
                account_id=evidence.account_id,
                before_sequence=int(row[5]),
            )
            observation_times = (
                snapshot.account_observed_at,
                snapshot.positions_observed_at,
                snapshot.orders_observed_at,
            )
            common_invalid = (
                row[:4]
                != (
                    evidence.proof_id,
                    evidence.baseline_id,
                    evidence.advance_fingerprint,
                    evidence.observed_snapshot_id,
                )
                or row[4] != payload
                or evidence.authorization_id != baseline.authorization_id
                or evidence.account_id != baseline.account_id
                or evidence.risk_configuration_fingerprint
                != baseline.risk_configuration_fingerprint
                or snapshot.account_id != evidence.account_id
                or snapshot.snapshot_fingerprint != evidence.observed_snapshot_fingerprint
                or snapshot.open_orders
                or not snapshot.account_ready
                or any(
                    timestamp > evidence.settled_at
                    or (evidence.settled_at - timestamp).total_seconds()
                    > baseline.maximum_age_seconds
                    for timestamp in observation_times
                )
                or attestation.attestation_fingerprint != evidence.attestation_fingerprint
                or attestation.snapshot != snapshot
                or terminal_orders != evidence.terminal_orders
                or emergency_payload.get("disabled") is not False
                or emergency_payload.get("generation") != evidence.emergency_generation
                or emergency_event is None
                or journal
                != (
                    _utc_text(evidence.settled_at),
                    "position-settlement-proved",
                    "position-settlement",
                    evidence.proof_id,
                    payload,
                )
            )
            if evidence.settlement_mode == _FILL_SETTLEMENT_MODE:
                mode_invalid = (
                    advance_row is None
                    or advance is None
                    or later_advance is not None
                    or snapshot.positions != advance.positions
                    or any(timestamp < advance.advanced_at for timestamp in observation_times)
                    or _parse_utc(str(emergency_event[0])) > advance.advanced_at
                )
            else:
                reconciliation_row = connection.execute(
                    "SELECT evidence_json, journal_sequence FROM reconciliation_evidence "
                    "WHERE evidence_id = ?",
                    (evidence.reconciliation_evidence_id,),
                ).fetchone()
                execution_artifact = connection.execute(
                    "SELECT 1 FROM capacity_reservations WHERE authorization_id = ? "
                    "AND journal_sequence < ? LIMIT 1",
                    (evidence.authorization_id, row[5]),
                ).fetchone()
                mode_invalid = (
                    not isinstance(attestation, _PaperSnapshotAttestationV2)
                    or bool(snapshot.positions)
                    or advance_row is not None
                    or later_advance is not None
                    or reconciliation_row is None
                    or execution_artifact is not None
                    or _parse_utc(str(emergency_event[0])) >= min(observation_times)
                )
                if reconciliation_row is not None:
                    try:
                        reconciliation = _decode_reconciliation(json.loads(reconciliation_row[0]))
                    except (json.JSONDecodeError, ValueError) as error:
                        raise JournalIntegrityError(
                            "stored position settlement is invalid"
                        ) from error
                    mode_invalid = mode_invalid or (
                        reconciliation.baseline_id != evidence.baseline_id
                        or reconciliation.observed_snapshot_id != evidence.observed_snapshot_id
                        or not reconciliation.result.clean
                        or reconciliation.unresolved_mutations != 0
                        or int(reconciliation_row[1]) <= int(emergency_event[2])
                    )
            if common_invalid or mode_invalid:
                raise JournalIntegrityError("position settlement does not match its evidence")
            result[evidence.proof_id] = evidence
        return result


def _decode_advance(value: object) -> ExpectedPositionAdvance:
    from .broker_events import _decode_expected_position_advance

    return _decode_expected_position_advance(value)


def _decode_evidence(value: object) -> PositionSettlementEvidence:
    if not isinstance(value, dict):
        raise ValueError("position settlement must be an object")
    try:
        return PositionSettlementEvidence(
            **{
                **value,
                "terminal_orders": tuple(tuple(item) for item in value["terminal_orders"]),
                "settled_at": _parse_utc(str(value["settled_at"])),
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("position settlement is invalid") from error


def _terminal_orders_at(
    connection: sqlite3.Connection, *, account_id: str, before_sequence: int
) -> tuple[tuple[str, str, int], ...]:
    order_ids = connection.execute(
        "SELECT o.order_id FROM orders o JOIN capacity_reservations r "
        "ON r.reservation_id = o.reservation_id "
        "WHERE json_extract(r.reservation_json, '$.account_id') = ?",
        (account_id,),
    ).fetchall()
    result: list[tuple[str, str, int]] = []
    for (order_id,) in order_ids:
        event = connection.execute(
            "SELECT sequence, event_type, payload_json FROM journal "
            "WHERE entity_type = 'order' AND entity_id = ? AND sequence < ? "
            "ORDER BY sequence DESC LIMIT 1",
            (order_id, before_sequence),
        ).fetchone()
        if event is None:
            continue
        payload = json.loads(event[2])
        state = (
            OrderState.STAGED
            if event[1] == "order-staged"
            else OrderState.SUBMITTING
            if event[1] == "order-submitter-claimed"
            else OrderState(payload["to_state"])
        )
        if state not in _TERMINAL_STATES:
            raise JournalIntegrityError("settlement proof contains a nonterminal local order")
        result.append((str(order_id), state.value, int(event[0])))
    return tuple(sorted(result))


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must be UTC-aware")
    return parsed


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
