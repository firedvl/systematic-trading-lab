"""Pure fail-closed reconciliation of normalized portfolio state."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from pathlib import Path
from typing import Any

from .execution import JournalIntegrityError
from .experiments import HoldoutAccessError
from .fingerprints import canonical_json, canonicalize, fingerprint
from .risk import EmergencyState, PaperAuthorization, RiskLimits, RiskStore

_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,15}")
_ALPACA_READER_CAPABILITY = object()
_CONTINUATION_TABLES = {
    "paper_continuation_declarations",
    "paper_continuation_handoffs",
}
_CONTINUATION_EVENTS = {
    "paper-continuation-declared",
    "paper-continuation-completed",
}


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
class StrategyEquityBaseline:
    baseline_id: str
    authorization_id: str
    authorization_fingerprint: str
    reconciliation_baseline_id: str
    reconciliation_baseline_fingerprint: str
    account_id: str
    strategy_id: str
    strategy_version: str
    risk_configuration_fingerprint: str
    allocated_capital: Decimal
    operator: str
    reason: str
    created_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("strategy equity baseline ID", self.baseline_id),
            ("authorization ID", self.authorization_id),
            ("reconciliation baseline ID", self.reconciliation_baseline_id),
            ("account ID", self.account_id),
            ("strategy ID", self.strategy_id),
            ("strategy version", self.strategy_version),
            ("operator", self.operator),
            ("reason", self.reason),
        ):
            _bounded_text(name, value)
        for name, value in (
            ("paper authorization", self.authorization_fingerprint),
            ("reconciliation baseline", self.reconciliation_baseline_fingerprint),
            ("risk configuration", self.risk_configuration_fingerprint),
        ):
            _sha256(name, value)
        if not self.allocated_capital.is_finite() or self.allocated_capital <= 0:
            raise ValueError("allocated capital must be finite and positive")
        _utc("strategy equity baseline creation time", self.created_at)

    @property
    def baseline_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class PaperContinuationDeclaration:
    authorization_id: str
    authorization_fingerprint: str
    previous_authorization_id: str
    previous_authorization_fingerprint: str
    candidate_id: str
    strategy_id: str
    strategy_version: str
    account_id: str
    risk_configuration_fingerprint: str
    declared_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("authorization ID", self.authorization_id),
            ("previous authorization ID", self.previous_authorization_id),
            ("candidate ID", self.candidate_id),
            ("strategy ID", self.strategy_id),
            ("strategy version", self.strategy_version),
            ("account ID", self.account_id),
        ):
            _bounded_text(name, value)
        if self.authorization_id == self.previous_authorization_id:
            raise ValueError("continuation authorization must follow another authorization")
        for name, value in (
            ("authorization", self.authorization_fingerprint),
            ("previous authorization", self.previous_authorization_fingerprint),
            ("risk configuration", self.risk_configuration_fingerprint),
        ):
            _sha256(name, value)
        _utc("continuation declaration time", self.declared_at)

    @property
    def declaration_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class PaperContinuationHandoff:
    authorization_id: str
    declaration_fingerprint: str
    previous_authorization_id: str
    source_authorization_fingerprint: str
    candidate_id: str
    strategy_id: str
    strategy_version: str
    account_id: str
    risk_configuration_fingerprint: str
    source_reconciliation_baseline_id: str
    source_settlement_proof_id: str
    source_settlement_proof_fingerprint: str
    source_strategy_equity_checkpoint_id: str
    source_strategy_equity_checkpoint_fingerprint: str
    source_fill_event_ids: tuple[str, ...]
    current_snapshot_id: str
    current_snapshot_fingerprint: str
    current_attestation_fingerprint: str
    current_risk_input_evidence_id: str
    reconciliation_baseline_id: str
    reconciliation_baseline_fingerprint: str
    reconciliation_evidence_id: str
    strategy_equity_baseline_id: str
    strategy_equity_baseline_fingerprint: str
    settlement_proof_id: str
    settlement_proof_fingerprint: str
    strategy_equity_checkpoint_id: str
    strategy_equity_checkpoint_fingerprint: str
    cash: Decimal
    equity: Decimal
    buying_power: Decimal
    positions: tuple[PositionSnapshot, ...]
    allocated_capital: Decimal
    gross_buy_notional: Decimal
    gross_sell_notional: Decimal
    fill_cost_reserve: Decimal
    strategy_cash: Decimal
    strategy_equity: Decimal
    peak_equity: Decimal
    strategy_drawdown: Decimal
    emergency_generation: int
    completed_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("authorization ID", self.authorization_id),
            ("previous authorization ID", self.previous_authorization_id),
            ("candidate ID", self.candidate_id),
            ("strategy ID", self.strategy_id),
            ("strategy version", self.strategy_version),
            ("account ID", self.account_id),
            ("source reconciliation baseline ID", self.source_reconciliation_baseline_id),
            ("source settlement proof ID", self.source_settlement_proof_id),
            ("source strategy equity checkpoint ID", self.source_strategy_equity_checkpoint_id),
            ("current snapshot ID", self.current_snapshot_id),
            ("reconciliation baseline ID", self.reconciliation_baseline_id),
            ("strategy equity baseline ID", self.strategy_equity_baseline_id),
            ("settlement proof ID", self.settlement_proof_id),
            ("strategy equity checkpoint ID", self.strategy_equity_checkpoint_id),
        ):
            _bounded_text(name, value)
        for name, value in (
            ("declaration", self.declaration_fingerprint),
            ("source authorization", self.source_authorization_fingerprint),
            ("risk configuration", self.risk_configuration_fingerprint),
            ("source settlement", self.source_settlement_proof_fingerprint),
            (
                "source strategy equity checkpoint",
                self.source_strategy_equity_checkpoint_fingerprint,
            ),
            ("current snapshot", self.current_snapshot_fingerprint),
            ("current attestation", self.current_attestation_fingerprint),
            ("current risk input", self.current_risk_input_evidence_id),
            ("reconciliation baseline", self.reconciliation_baseline_fingerprint),
            ("reconciliation evidence", self.reconciliation_evidence_id),
            ("strategy equity baseline", self.strategy_equity_baseline_fingerprint),
            ("settlement", self.settlement_proof_fingerprint),
            ("strategy equity checkpoint", self.strategy_equity_checkpoint_fingerprint),
        ):
            _sha256(name, value)
        if self.source_fill_event_ids != tuple(sorted(set(self.source_fill_event_ids))):
            raise ValueError("continuation fill-event lineage must be sorted and unique")
        for event_id in self.source_fill_event_ids:
            _bounded_text("source fill-event ID", event_id)
        if self.positions != tuple(sorted(self.positions, key=lambda item: item.symbol)) or len(
            {item.symbol for item in self.positions}
        ) != len(self.positions):
            raise ValueError("continuation positions must be sorted and unique")
        for amount_name, amount in (
            ("cash", self.cash),
            ("equity", self.equity),
            ("buying power", self.buying_power),
            ("allocated capital", self.allocated_capital),
            ("gross buy notional", self.gross_buy_notional),
            ("gross sell notional", self.gross_sell_notional),
            ("fill cost reserve", self.fill_cost_reserve),
            ("strategy equity", self.strategy_equity),
            ("peak equity", self.peak_equity),
            ("strategy drawdown", self.strategy_drawdown),
        ):
            if not amount.is_finite() or amount < 0:
                raise ValueError(f"continuation {amount_name} must be finite and nonnegative")
        if (
            not self.strategy_cash.is_finite()
            or self.allocated_capital <= 0
            or self.strategy_equity <= 0
            or self.peak_equity < self.strategy_equity
            or self.strategy_drawdown
            != (self.peak_equity - self.strategy_equity) / self.peak_equity
            or self.emergency_generation < 1
        ):
            raise ValueError("continuation strategy equity lineage is inconsistent")
        _utc("continuation completion time", self.completed_at)

    @property
    def handoff_fingerprint(self) -> str:
        return fingerprint(self)


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
        if self.adapter_version != "alpaca-paper-reader-v1":
            raise ValueError("paper snapshot adapter version is unsupported")
        _validate_paper_attestation(self.snapshot, self.paper_origin, self.completed_at)

    @property
    def attestation_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class _PaperSnapshotAttestationV2:
    snapshot: PortfolioSnapshot
    adapter_version: str
    paper_origin: str
    completed_at: datetime
    previous_close_equity: Decimal

    def __post_init__(self) -> None:
        if self.adapter_version != "alpaca-paper-reader-v2":
            raise ValueError("paper snapshot adapter version is unsupported")
        _validate_paper_attestation(self.snapshot, self.paper_origin, self.completed_at)
        if not self.previous_close_equity.is_finite() or self.previous_close_equity <= 0:
            raise ValueError("paper snapshot requires positive prior-close equity")

    @property
    def attestation_fingerprint(self) -> str:
        return fingerprint(self)


_PaperAttestation = _PaperSnapshotAttestation | _PaperSnapshotAttestationV2


def _validate_paper_attestation(
    snapshot: PortfolioSnapshot, paper_origin: str, completed_at: datetime
) -> None:
    if snapshot.source is not SnapshotSource.ALPACA_PAPER:
        raise ValueError("only Alpaca-paper snapshots can be adapter-attested")
    if paper_origin != "https://paper-api.alpaca.markets":
        raise ValueError("paper snapshot origin is unsupported")
    _utc("paper snapshot completion time", completed_at)
    if completed_at != max(
        snapshot.account_observed_at,
        snapshot.positions_observed_at,
        snapshot.orders_observed_at,
    ):
        raise ValueError("paper snapshot completion must match its final observation")


@dataclass(frozen=True)
class AccountDailyPnlEvidence:
    snapshot_id: str
    snapshot_fingerprint: str
    attestation_fingerprint: str
    account_id: str
    equity: Decimal
    previous_close_equity: Decimal
    daily_pnl: Decimal
    observed_at: datetime

    def __post_init__(self) -> None:
        _bounded_text("snapshot ID", self.snapshot_id)
        _bounded_text("account ID", self.account_id)
        _sha256("snapshot", self.snapshot_fingerprint)
        _sha256("paper attestation", self.attestation_fingerprint)
        for name, value in (
            ("equity", self.equity),
            ("previous close equity", self.previous_close_equity),
        ):
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not self.daily_pnl.is_finite() or self.daily_pnl != (
            self.equity - self.previous_close_equity
        ):
            raise ValueError("daily PnL must match equity change")
        _utc("account observation", self.observed_at)

    @property
    def evidence_fingerprint(self) -> str:
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
                CREATE TABLE IF NOT EXISTS strategy_equity_baselines (
                    baseline_id TEXT PRIMARY KEY,
                    authorization_id TEXT NOT NULL UNIQUE
                        REFERENCES paper_authorizations(authorization_id),
                    reconciliation_baseline_id TEXT NOT NULL UNIQUE
                        REFERENCES reconciliation_baselines(baseline_id),
                    baseline_fingerprint TEXT NOT NULL UNIQUE,
                    baseline_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TABLE IF NOT EXISTS paper_continuation_declarations (
                    authorization_id TEXT PRIMARY KEY
                        REFERENCES paper_authorizations(authorization_id),
                    previous_authorization_id TEXT NOT NULL
                        REFERENCES paper_authorizations(authorization_id),
                    declaration_fingerprint TEXT NOT NULL UNIQUE,
                    declaration_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TABLE IF NOT EXISTS paper_continuation_handoffs (
                    authorization_id TEXT PRIMARY KEY
                        REFERENCES paper_continuation_declarations(authorization_id),
                    handoff_fingerprint TEXT NOT NULL UNIQUE,
                    handoff_json TEXT NOT NULL,
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
                CREATE TRIGGER IF NOT EXISTS strategy_equity_baselines_no_update
                BEFORE UPDATE ON strategy_equity_baselines BEGIN
                    SELECT RAISE(ABORT, 'strategy equity baselines are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS strategy_equity_baselines_no_delete
                BEFORE DELETE ON strategy_equity_baselines BEGIN
                    SELECT RAISE(ABORT, 'strategy equity baselines are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS paper_continuation_declarations_no_update
                BEFORE UPDATE ON paper_continuation_declarations BEGIN
                    SELECT RAISE(ABORT, 'paper continuation declarations are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS paper_continuation_declarations_no_delete
                BEFORE DELETE ON paper_continuation_declarations BEGIN
                    SELECT RAISE(ABORT, 'paper continuation declarations are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS paper_continuation_handoffs_no_update
                BEFORE UPDATE ON paper_continuation_handoffs BEGIN
                    SELECT RAISE(ABORT, 'paper continuation handoffs are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS paper_continuation_handoffs_no_delete
                BEFORE DELETE ON paper_continuation_handoffs BEGIN
                    SELECT RAISE(ABORT, 'paper continuation handoffs are immutable');
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

    def account_daily_pnl(self, snapshot_id: str) -> AccountDailyPnlEvidence:
        _bounded_text("snapshot ID", snapshot_id)
        with self._connect() as connection:
            connection.execute("BEGIN")
            snapshots, attestations, _, _ = self._verify_all(connection)
        try:
            snapshot = snapshots[snapshot_id]
            attestation = attestations[snapshot_id]
        except KeyError:
            raise KeyError(snapshot_id) from None
        if not isinstance(attestation, _PaperSnapshotAttestationV2):
            raise ValueError("paper snapshot lacks prior-close equity evidence")
        return AccountDailyPnlEvidence(
            snapshot_id=snapshot.snapshot_id,
            snapshot_fingerprint=snapshot.snapshot_fingerprint,
            attestation_fingerprint=attestation.attestation_fingerprint,
            account_id=snapshot.account_id,
            equity=snapshot.equity,
            previous_close_equity=attestation.previous_close_equity,
            daily_pnl=snapshot.equity - attestation.previous_close_equity,
            observed_at=snapshot.account_observed_at,
        )

    def _record_adapter_snapshot(
        self,
        snapshot: PortfolioSnapshot,
        *,
        adapter_version: str,
        paper_origin: str,
        recorded_at: datetime,
        _capability: object,
        previous_close_equity: Decimal | None = None,
    ) -> PortfolioSnapshot:
        if _capability is not _ALPACA_READER_CAPABILITY:
            raise PermissionError("only the production Alpaca reader can attest a snapshot")
        if adapter_version == "alpaca-paper-reader-v1" and previous_close_equity is None:
            attestation: _PaperAttestation = _PaperSnapshotAttestation(
                snapshot=snapshot,
                adapter_version=adapter_version,
                paper_origin=paper_origin,
                completed_at=snapshot.orders_observed_at,
            )
        elif adapter_version == "alpaca-paper-reader-v2" and previous_close_equity is not None:
            attestation = _PaperSnapshotAttestationV2(
                snapshot=snapshot,
                adapter_version=adapter_version,
                paper_origin=paper_origin,
                completed_at=snapshot.orders_observed_at,
                previous_close_equity=previous_close_equity,
            )
        else:
            raise ValueError("paper snapshot adapter evidence is incomplete")
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

    def authorize_continuation(
        self,
        *,
        authorization_id: str,
        previous_authorization_id: str,
        limits: RiskLimits,
        authorized_by: str,
        reason: str,
        authorized_at: datetime,
        expires_at: datetime,
    ) -> tuple[PaperAuthorization, PaperContinuationDeclaration]:
        """Declare a continuation authorization without granting usable risk context."""
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_all(connection)
                authorizations = self._verify_authorizations(connection)
                declarations = self._verify_continuation_declarations(connection, authorizations)
                try:
                    previous = authorizations[previous_authorization_id]
                except KeyError as error:
                    raise HoldoutAccessError("previous paper authorization is missing") from error
                authorization = replace(
                    previous,
                    authorization_id=authorization_id,
                    authorized_by=authorized_by,
                    authorization_reason=reason,
                    authorized_at=authorized_at,
                    expires_at=expires_at,
                )
                declaration = PaperContinuationDeclaration(
                    authorization_id=authorization.authorization_id,
                    authorization_fingerprint=authorization.authorization_fingerprint,
                    previous_authorization_id=previous.authorization_id,
                    previous_authorization_fingerprint=previous.authorization_fingerprint,
                    candidate_id=authorization.candidate_id,
                    strategy_id=authorization.strategy_id,
                    strategy_version=authorization.strategy_version,
                    account_id=authorization.account_id,
                    risk_configuration_fingerprint=authorization.risk_configuration_fingerprint,
                    declared_at=authorization.authorized_at,
                )
                existing = declarations.get(authorization_id)
                if existing is not None:
                    if (
                        existing != declaration
                        or authorizations.get(authorization_id) != authorization
                    ):
                        raise HoldoutAccessError(
                            "continuation authorization ID is bound to different content"
                        )
                    connection.commit()
                    return authorization, existing
                if authorization_id in authorizations:
                    raise HoldoutAccessError(
                        "existing paper authorization cannot become a continuation"
                    )
                if any(
                    item.previous_authorization_id == previous_authorization_id
                    for item in declarations.values()
                ):
                    raise HoldoutAccessError(
                        "previous paper authorization already has a continuation successor"
                    )
                if previous_authorization_id in declarations:
                    completed = connection.execute(
                        "SELECT 1 FROM paper_continuation_handoffs WHERE authorization_id = ?",
                        (previous_authorization_id,),
                    ).fetchone()
                    if completed is None:
                        raise HoldoutAccessError(
                            "previous continuation authorization has no completed handoff"
                        )
                emergency = self._verify_emergency(connection)
                required_tables = {
                    "orders",
                    "position_settlement_evidence",
                    "strategy_equity_checkpoints",
                }
                present_tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                source_checkpoint = (
                    connection.execute(
                        "SELECT checkpoint_json FROM strategy_equity_checkpoints "
                        "WHERE json_extract(checkpoint_json, '$.authorization_id') = ? "
                        "ORDER BY journal_sequence DESC LIMIT 1",
                        (previous_authorization_id,),
                    ).fetchone()
                    if required_tables.issubset(present_tables)
                    else None
                )
                nonterminal_order = (
                    connection.execute(
                        "SELECT 1 FROM orders WHERE state NOT IN "
                        "('filled', 'canceled', 'rejected') "
                        "LIMIT 1"
                    ).fetchone()
                    if "orders" in present_tables
                    else None
                )
                if source_checkpoint is None:
                    raise HoldoutAccessError(
                        "continuation requires established strategy equity lineage"
                    )
                try:
                    checkpoint_value = json.loads(str(source_checkpoint[0]))
                    checkpoint_marked_at = _parse_utc(checkpoint_value["marked_at"])
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                    raise JournalIntegrityError(
                        "source strategy equity checkpoint is invalid"
                    ) from error
                evidence_row = connection.execute(
                    "SELECT evidence_json FROM paper_authorizations WHERE authorization_id = ?",
                    (previous_authorization_id,),
                ).fetchone()
                if evidence_row is None:
                    raise JournalIntegrityError("previous authorization evidence is missing")
                try:
                    evidence_report = json.loads(str(evidence_row[0]))
                except json.JSONDecodeError as error:
                    raise JournalIntegrityError(
                        "previous authorization evidence is invalid"
                    ) from error
                self._validate_paper_authorization(authorization, evidence_report, limits)
                if (
                    emergency.disabled
                    or nonterminal_order is not None
                    or authorization.authorized_at <= previous.authorized_at
                    or authorization.authorized_at < previous.expires_at
                    or authorization.authorized_at < checkpoint_marked_at
                    or authorization.expires_at > authorization.authorized_at + timedelta(hours=24)
                ):
                    raise HoldoutAccessError(
                        "continuation requires clear settled lineage and a maximum "
                        "24-hour authorization"
                    )
                self._record_paper_authorization(connection, authorization, evidence_report)
                sequence = self._append_event(
                    connection,
                    occurred_at=declaration.declared_at,
                    event_type="paper-continuation-declared",
                    entity_type="paper-continuation-declaration",
                    entity_id=declaration.authorization_id,
                    payload=canonicalize(declaration),
                )
                connection.execute(
                    "INSERT INTO paper_continuation_declarations VALUES (?, ?, ?, ?, ?)",
                    (
                        declaration.authorization_id,
                        declaration.previous_authorization_id,
                        declaration.declaration_fingerprint,
                        canonical_json(declaration),
                        sequence,
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise HoldoutAccessError("paper continuation declaration already exists") from error
            except Exception:
                connection.rollback()
                raise
        return authorization, declaration

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
                continuation_declarations = self._verify_continuation_declarations(
                    connection, authorizations
                )
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
                    or authorization_id in continuation_declarations
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

    def create_strategy_equity_baseline(
        self,
        *,
        baseline_id: str,
        reconciliation_baseline_id: str,
        limits: RiskLimits,
        operator: str,
        reason: str,
        created_at: datetime,
    ) -> StrategyEquityBaseline:
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                _, _, reconciliation_baselines, _ = self._verify_all(connection)
                authorizations = self._verify_authorizations(connection)
                equity_baselines = self._verify_strategy_equity_baselines(
                    connection, reconciliation_baselines, authorizations
                )
                try:
                    reconciliation_baseline = reconciliation_baselines[reconciliation_baseline_id]
                    authorization = authorizations[reconciliation_baseline.authorization_id]
                except KeyError as error:
                    raise HoldoutAccessError(
                        "strategy equity baseline authority is missing"
                    ) from error
                baseline = StrategyEquityBaseline(
                    baseline_id=baseline_id,
                    authorization_id=authorization.authorization_id,
                    authorization_fingerprint=authorization.authorization_fingerprint,
                    reconciliation_baseline_id=reconciliation_baseline.baseline_id,
                    reconciliation_baseline_fingerprint=fingerprint(reconciliation_baseline),
                    account_id=authorization.account_id,
                    strategy_id=authorization.strategy_id,
                    strategy_version=authorization.strategy_version,
                    risk_configuration_fingerprint=limits.configuration_fingerprint,
                    allocated_capital=limits.strategy_capital_allocation,
                    operator=operator,
                    reason=reason,
                    created_at=created_at,
                )
                if (
                    authorization.account_id != limits.account_id
                    or authorization.risk_configuration_fingerprint
                    != limits.configuration_fingerprint
                    or reconciliation_baseline.account_id != limits.account_id
                    or reconciliation_baseline.risk_configuration_fingerprint
                    != limits.configuration_fingerprint
                    or created_at < reconciliation_baseline.created_at
                    or created_at < authorization.authorized_at
                    or created_at >= authorization.expires_at
                    or created_at < limits.effective_at
                    or created_at >= limits.expires_at
                ):
                    raise HoldoutAccessError(
                        "strategy equity baseline requires matching active authority"
                    )
                existing = equity_baselines.get(baseline_id)
                if existing is not None:
                    if existing != baseline:
                        raise JournalIntegrityError(
                            "strategy equity baseline ID is bound to different content"
                        )
                    connection.commit()
                    return existing
                if any(
                    item.authorization_id == authorization.authorization_id
                    for item in equity_baselines.values()
                ):
                    raise HoldoutAccessError(
                        "paper authorization already has a strategy equity baseline"
                    )
                sequence = self._append_event(
                    connection,
                    occurred_at=created_at,
                    event_type="strategy-equity-baseline-created",
                    entity_type="strategy-equity-baseline",
                    entity_id=baseline_id,
                    payload=canonicalize(baseline),
                )
                connection.execute(
                    "INSERT INTO strategy_equity_baselines VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        baseline.baseline_id,
                        baseline.authorization_id,
                        baseline.reconciliation_baseline_id,
                        baseline.baseline_fingerprint,
                        canonical_json(baseline),
                        sequence,
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise HoldoutAccessError("strategy equity baseline already exists") from error
            except Exception:
                connection.rollback()
                raise
        return baseline

    def get_strategy_equity_baseline(self, authorization_id: str) -> StrategyEquityBaseline:
        _bounded_text("authorization ID", authorization_id)
        with self._connect() as connection:
            connection.execute("BEGIN")
            _, _, reconciliation_baselines, _ = self._verify_all(connection)
            authorizations = self._verify_authorizations(connection)
            baselines = self._verify_strategy_equity_baselines(
                connection, reconciliation_baselines, authorizations
            )
        for baseline in baselines.values():
            if baseline.authorization_id == authorization_id:
                return baseline
        raise HoldoutAccessError("strategy equity baseline is missing")

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
        dict[str, _PaperAttestation],
        dict[str, ReconciliationBaseline],
        dict[str, ReconciliationEvidence],
    ]:
        self._verify_connection(connection)
        self._verify_emergency(connection)
        self._verify_authorizations(connection)
        self._verify_decisions(connection)
        return self._verify_reconciliation(connection)

    def _verify_continuation_declarations(
        self,
        connection: sqlite3.Connection,
        authorizations: dict[str, PaperAuthorization] | None = None,
    ) -> dict[str, PaperContinuationDeclaration]:
        authorizations = authorizations or self._verify_authorizations(connection)
        if not _continuation_tables_present(connection):
            return {}
        rows = connection.execute(
            "SELECT authorization_id, previous_authorization_id, declaration_fingerprint, "
            "declaration_json, journal_sequence FROM paper_continuation_declarations"
        ).fetchall()
        _require_event_count(connection, "paper-continuation-declared", len(rows))
        result: dict[str, PaperContinuationDeclaration] = {}
        predecessor_ids: set[str] = set()
        continuation_ids = {str(row[0]) for row in rows}
        completed_ids = {
            str(row[0])
            for row in connection.execute(
                "SELECT authorization_id FROM paper_continuation_handoffs"
            ).fetchall()
        }
        for row in rows:
            try:
                declaration = _decode_continuation_declaration(json.loads(row[3]))
                authorization = authorizations[declaration.authorization_id]
                previous = authorizations[declaration.previous_authorization_id]
            except (KeyError, ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError(
                    "stored paper continuation declaration is invalid"
                ) from error
            same_lineage = all(
                getattr(authorization, name) == getattr(previous, name)
                for name in (
                    "candidate_id",
                    "strategy_id",
                    "strategy_version",
                    "parameters_fingerprint",
                    "code_commit",
                    "dataset_id",
                    "dataset_fingerprint",
                    "universe_id",
                    "universe_fingerprint",
                    "qualification_evidence_fingerprint",
                    "account_id",
                    "risk_configuration_fingerprint",
                )
            )
            if (
                row[:4]
                != (
                    declaration.authorization_id,
                    declaration.previous_authorization_id,
                    declaration.declaration_fingerprint,
                    canonical_json(declaration),
                )
                or declaration.authorization_fingerprint != authorization.authorization_fingerprint
                or declaration.previous_authorization_fingerprint
                != previous.authorization_fingerprint
                or declaration.candidate_id != authorization.candidate_id
                or declaration.strategy_id != authorization.strategy_id
                or declaration.strategy_version != authorization.strategy_version
                or declaration.account_id != authorization.account_id
                or declaration.risk_configuration_fingerprint
                != authorization.risk_configuration_fingerprint
                or declaration.declared_at != authorization.authorized_at
                or authorization.authorized_at <= previous.authorized_at
                or authorization.authorized_at < previous.expires_at
                or authorization.expires_at > authorization.authorized_at + timedelta(hours=24)
                or declaration.previous_authorization_id in predecessor_ids
                or (
                    declaration.previous_authorization_id in continuation_ids
                    and declaration.previous_authorization_id not in completed_ids
                )
                or not same_lineage
                or not _event_matches(
                    connection,
                    row[4],
                    _utc_text(declaration.declared_at),
                    "paper-continuation-declared",
                    "paper-continuation-declaration",
                    declaration.authorization_id,
                    canonical_json(declaration),
                )
            ):
                raise JournalIntegrityError(
                    "paper continuation declaration differs from its authority"
                )
            predecessor_ids.add(declaration.previous_authorization_id)
            result[declaration.authorization_id] = declaration
        return result

    def _verify_continuation_handoffs(
        self,
        connection: sqlite3.Connection,
        *,
        authorizations: dict[str, PaperAuthorization],
        declarations: dict[str, PaperContinuationDeclaration],
        snapshots: dict[str, PortfolioSnapshot],
        attestations: dict[str, _PaperAttestation],
        reconciliation_baselines: dict[str, ReconciliationBaseline],
        reconciliations: dict[str, ReconciliationEvidence],
        strategy_equity_baselines: dict[str, StrategyEquityBaseline],
    ) -> dict[str, PaperContinuationHandoff]:
        if not _continuation_tables_present(connection):
            return {}
        rows = connection.execute(
            "SELECT authorization_id, handoff_fingerprint, handoff_json, journal_sequence "
            "FROM paper_continuation_handoffs"
        ).fetchall()
        _require_event_count(connection, "paper-continuation-completed", len(rows))
        result: dict[str, PaperContinuationHandoff] = {}
        for row in rows:
            try:
                handoff = _decode_continuation_handoff(json.loads(row[2]))
                declaration = declarations[handoff.authorization_id]
                authorization = authorizations[handoff.authorization_id]
                previous = authorizations[handoff.previous_authorization_id]
                snapshot = snapshots[handoff.current_snapshot_id]
                attestation = attestations[handoff.current_snapshot_id]
                baseline = reconciliation_baselines[handoff.reconciliation_baseline_id]
                reconciliation = reconciliations[handoff.reconciliation_evidence_id]
                strategy_baseline = strategy_equity_baselines[handoff.strategy_equity_baseline_id]
                source_baseline = reconciliation_baselines[
                    handoff.source_reconciliation_baseline_id
                ]
                risk_input_row = connection.execute(
                    "SELECT portfolio_snapshot_id, authorization_id, evidence_json "
                    "FROM risk_input_evidence WHERE evidence_id = ?",
                    (handoff.current_risk_input_evidence_id,),
                ).fetchone()
                source_settlement_row = connection.execute(
                    "SELECT evidence_json FROM position_settlement_evidence WHERE proof_id = ?",
                    (handoff.source_settlement_proof_id,),
                ).fetchone()
                settlement_row = connection.execute(
                    "SELECT evidence_json FROM position_settlement_evidence WHERE proof_id = ?",
                    (handoff.settlement_proof_id,),
                ).fetchone()
                source_checkpoint_row = connection.execute(
                    "SELECT checkpoint_fingerprint, checkpoint_json, journal_sequence "
                    "FROM strategy_equity_checkpoints WHERE checkpoint_id = ?",
                    (handoff.source_strategy_equity_checkpoint_id,),
                ).fetchone()
                checkpoint_row = connection.execute(
                    "SELECT checkpoint_fingerprint, checkpoint_json FROM "
                    "strategy_equity_checkpoints WHERE checkpoint_id = ?",
                    (handoff.strategy_equity_checkpoint_id,),
                ).fetchone()
                if any(
                    item is None
                    for item in (
                        risk_input_row,
                        source_settlement_row,
                        settlement_row,
                        source_checkpoint_row,
                        checkpoint_row,
                    )
                ):
                    raise ValueError("continuation evidence is missing")
                assert risk_input_row is not None
                assert source_settlement_row is not None
                assert settlement_row is not None
                assert source_checkpoint_row is not None
                assert checkpoint_row is not None
                risk_input = json.loads(str(risk_input_row[2]))
                source_settlement = json.loads(str(source_settlement_row[0]))
                settlement = json.loads(str(settlement_row[0]))
                source_checkpoint = json.loads(str(source_checkpoint_row[1]))
                checkpoint = json.loads(str(checkpoint_row[1]))
                checkpoint_amounts = {
                    name: Decimal(str(checkpoint[name]))
                    for name in (
                        "allocated_capital",
                        "gross_buy_notional",
                        "gross_sell_notional",
                        "fill_cost_reserve",
                        "strategy_cash",
                        "strategy_equity",
                        "peak_equity",
                        "strategy_drawdown",
                    )
                }
            except (
                ArithmeticError,
                KeyError,
                TypeError,
                ValueError,
                sqlite3.OperationalError,
                json.JSONDecodeError,
            ) as error:
                raise JournalIntegrityError(
                    "stored paper continuation handoff is invalid"
                ) from error
            latest_source_checkpoint = connection.execute(
                "SELECT checkpoint_id FROM strategy_equity_checkpoints "
                "WHERE json_extract(checkpoint_json, '$.authorization_id') = ? "
                "AND journal_sequence < ? ORDER BY journal_sequence DESC LIMIT 1",
                (handoff.previous_authorization_id, row[3]),
            ).fetchone()
            emergency_event = connection.execute(
                "SELECT payload_json FROM journal WHERE event_type IN "
                "('emergency-initialized', 'emergency-cleared', 'emergency-disabled') "
                "AND sequence < ? ORDER BY sequence DESC LIMIT 1",
                (row[3],),
            ).fetchone()
            emergency_payload = (
                {} if emergency_event is None else json.loads(str(emergency_event[0]))
            )
            expected = snapshots[baseline.expected_snapshot_id]
            if (
                row[:3]
                != (
                    handoff.authorization_id,
                    handoff.handoff_fingerprint,
                    canonical_json(handoff),
                )
                or declaration.declaration_fingerprint != handoff.declaration_fingerprint
                or authorization.authorization_fingerprint != declaration.authorization_fingerprint
                or previous.authorization_fingerprint != handoff.source_authorization_fingerprint
                or handoff.candidate_id != authorization.candidate_id
                or handoff.strategy_id != authorization.strategy_id
                or handoff.strategy_version != authorization.strategy_version
                or handoff.account_id != authorization.account_id
                or handoff.risk_configuration_fingerprint
                != authorization.risk_configuration_fingerprint
                or handoff.completed_at < authorization.authorized_at
                or handoff.completed_at >= authorization.expires_at
                or snapshot.snapshot_fingerprint != handoff.current_snapshot_fingerprint
                or attestation.attestation_fingerprint != handoff.current_attestation_fingerprint
                or snapshot.account_id != handoff.account_id
                or not snapshot.account_ready
                or snapshot.open_orders
                or snapshot.positions != handoff.positions
                or any(
                    observed > handoff.completed_at
                    or (handoff.completed_at - observed).total_seconds()
                    > baseline.maximum_age_seconds
                    for observed in (
                        snapshot.account_observed_at,
                        snapshot.positions_observed_at,
                        snapshot.orders_observed_at,
                    )
                )
                or risk_input_row[:2] != (handoff.current_snapshot_id, handoff.authorization_id)
                or risk_input.get("risk_configuration_fingerprint")
                != handoff.risk_configuration_fingerprint
                or risk_input.get("completed_at") is None
                or _parse_utc(str(risk_input["completed_at"])) > handoff.completed_at
                or baseline.authorization_id != handoff.authorization_id
                or fingerprint(baseline) != handoff.reconciliation_baseline_fingerprint
                or expected.source is not SnapshotSource.LOCAL_EXPECTED
                or expected.account_id != snapshot.account_id
                or expected.cash != snapshot.cash
                or expected.equity != snapshot.equity
                or expected.buying_power != snapshot.buying_power
                or expected.positions != snapshot.positions
                or expected.open_orders
                or reconciliation.baseline_id != baseline.baseline_id
                or reconciliation.observed_snapshot_id != snapshot.snapshot_id
                or not reconciliation.result.clean
                or reconciliation.unresolved_mutations != 0
                or strategy_baseline.authorization_id != handoff.authorization_id
                or strategy_baseline.baseline_fingerprint
                != handoff.strategy_equity_baseline_fingerprint
                or source_checkpoint_row[0] != handoff.source_strategy_equity_checkpoint_fingerprint
                or source_checkpoint.get("authorization_id") != handoff.previous_authorization_id
                or source_checkpoint.get("settlement_proof_id")
                != handoff.source_settlement_proof_id
                or tuple(source_checkpoint.get("fill_event_ids", ()))
                != handoff.source_fill_event_ids
                or fingerprint(source_settlement) != handoff.source_settlement_proof_fingerprint
                or source_settlement.get("authorization_id") != handoff.previous_authorization_id
                or source_settlement.get("baseline_id") != handoff.source_reconciliation_baseline_id
                or source_baseline.authorization_id != handoff.previous_authorization_id
                or source_baseline.account_id != handoff.account_id
                or source_baseline.risk_configuration_fingerprint
                != handoff.risk_configuration_fingerprint
                or latest_source_checkpoint != (handoff.source_strategy_equity_checkpoint_id,)
                or settlement.get("settlement_mode") != "authorization-continuation-v1"
                or settlement.get("authorization_id") != handoff.authorization_id
                or settlement.get("observed_snapshot_id") != handoff.current_snapshot_id
                or settlement.get("reconciliation_evidence_id")
                != handoff.reconciliation_evidence_id
                or fingerprint(settlement) != handoff.settlement_proof_fingerprint
                or checkpoint_row[0] != handoff.strategy_equity_checkpoint_fingerprint
                or checkpoint.get("checkpoint_mode") != "authorization-continuation-v1"
                or checkpoint.get("authorization_id") != handoff.authorization_id
                or checkpoint.get("prior_checkpoint_fingerprint")
                != handoff.source_strategy_equity_checkpoint_fingerprint
                or checkpoint.get("settlement_proof_id") != handoff.settlement_proof_id
                or checkpoint.get("risk_input_evidence_id")
                != handoff.current_risk_input_evidence_id
                or tuple(checkpoint.get("fill_event_ids", ())) != handoff.source_fill_event_ids
                or checkpoint_amounts["allocated_capital"] != handoff.allocated_capital
                or checkpoint_amounts["gross_buy_notional"] != handoff.gross_buy_notional
                or checkpoint_amounts["gross_sell_notional"] != handoff.gross_sell_notional
                or checkpoint_amounts["fill_cost_reserve"] != handoff.fill_cost_reserve
                or checkpoint_amounts["strategy_cash"] != handoff.strategy_cash
                or checkpoint_amounts["strategy_equity"] != handoff.strategy_equity
                or checkpoint_amounts["peak_equity"] != handoff.peak_equity
                or checkpoint_amounts["strategy_drawdown"] != handoff.strategy_drawdown
                or snapshot.cash != handoff.cash
                or snapshot.equity != handoff.equity
                or snapshot.buying_power != handoff.buying_power
                or emergency_payload.get("disabled") is not False
                or emergency_payload.get("generation") != handoff.emergency_generation
                or not _event_matches(
                    connection,
                    row[3],
                    _utc_text(handoff.completed_at),
                    "paper-continuation-completed",
                    "paper-continuation-handoff",
                    handoff.authorization_id,
                    canonical_json(handoff),
                )
            ):
                raise JournalIntegrityError("paper continuation handoff differs from its evidence")
            result[handoff.authorization_id] = handoff
        return result

    def _verify_reconciliation(
        self, connection: sqlite3.Connection
    ) -> tuple[
        dict[str, PortfolioSnapshot],
        dict[str, _PaperAttestation],
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

        attestations: dict[str, _PaperAttestation] = {}
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
        continuation_declarations = ReconciliationStore._verify_continuation_declarations(
            self, connection, authorizations
        )
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
                or (
                    expected.positions
                    and baseline.authorization_id not in continuation_declarations
                )
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
        strategy_equity_baselines = ReconciliationStore._verify_strategy_equity_baselines(
            self, connection, baselines, authorizations
        )
        ReconciliationStore._verify_continuation_handoffs(
            self,
            connection,
            authorizations=authorizations,
            declarations=continuation_declarations,
            snapshots=snapshots,
            attestations=attestations,
            reconciliation_baselines=baselines,
            reconciliations=evidence_by_id,
            strategy_equity_baselines=strategy_equity_baselines,
        )
        return snapshots, attestations, baselines, evidence_by_id

    def _verify_strategy_equity_baselines(
        self,
        connection: sqlite3.Connection,
        reconciliation_baselines: dict[str, ReconciliationBaseline],
        authorizations: dict[str, PaperAuthorization],
    ) -> dict[str, StrategyEquityBaseline]:
        baselines: dict[str, StrategyEquityBaseline] = {}
        rows = connection.execute(
            """
            SELECT baseline_id, authorization_id, reconciliation_baseline_id,
                   baseline_fingerprint, baseline_json, journal_sequence
            FROM strategy_equity_baselines
            """
        ).fetchall()
        _require_event_count(connection, "strategy-equity-baseline-created", len(rows))
        for row in rows:
            try:
                baseline = _decode_strategy_equity_baseline(json.loads(row[4]))
                reconciliation_baseline = reconciliation_baselines[
                    baseline.reconciliation_baseline_id
                ]
                authorization = authorizations[baseline.authorization_id]
            except (KeyError, ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("stored strategy equity baseline is invalid") from error
            if (
                row[0] != baseline.baseline_id
                or row[1] != baseline.authorization_id
                or row[2] != baseline.reconciliation_baseline_id
                or row[3] != baseline.baseline_fingerprint
                or row[4] != canonical_json(baseline)
                or reconciliation_baseline.authorization_id != baseline.authorization_id
                or fingerprint(reconciliation_baseline)
                != baseline.reconciliation_baseline_fingerprint
                or reconciliation_baseline.account_id != baseline.account_id
                or reconciliation_baseline.risk_configuration_fingerprint
                != baseline.risk_configuration_fingerprint
                or authorization.account_id != baseline.account_id
                or authorization.authorization_fingerprint != baseline.authorization_fingerprint
                or authorization.strategy_id != baseline.strategy_id
                or authorization.strategy_version != baseline.strategy_version
                or authorization.risk_configuration_fingerprint
                != baseline.risk_configuration_fingerprint
                or baseline.created_at < reconciliation_baseline.created_at
                or baseline.created_at < authorization.authorized_at
                or baseline.created_at >= authorization.expires_at
                or not _event_matches(
                    connection,
                    row[5],
                    _utc_text(baseline.created_at),
                    "strategy-equity-baseline-created",
                    "strategy-equity-baseline",
                    row[0],
                    canonical_json(baseline),
                )
            ):
                raise JournalIntegrityError("strategy equity baseline does not match its authority")
            baselines[baseline.baseline_id] = baseline
        return baselines


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


def _decode_attestation(value: Any) -> _PaperAttestation:
    if not isinstance(value, dict):
        raise ValueError("paper snapshot attestation must be an object")
    try:
        common = {
            "snapshot": _decode_snapshot(value["snapshot"]),
            "adapter_version": value["adapter_version"],
            "paper_origin": value["paper_origin"],
            "completed_at": _parse_utc(value["completed_at"]),
        }
        if value["adapter_version"] == "alpaca-paper-reader-v1":
            return _PaperSnapshotAttestation(**common)
        return _PaperSnapshotAttestationV2(
            **common,
            previous_close_equity=Decimal(value["previous_close_equity"]),
        )
    except (KeyError, TypeError, ArithmeticError) as error:
        raise ValueError("paper snapshot attestation fields differ") from error


def _decode_baseline(value: Any) -> ReconciliationBaseline:
    if not isinstance(value, dict):
        raise ValueError("reconciliation baseline must be an object")
    try:
        return ReconciliationBaseline(**{**value, "created_at": _parse_utc(value["created_at"])})
    except (KeyError, TypeError) as error:
        raise ValueError("reconciliation baseline fields differ") from error


def _decode_strategy_equity_baseline(value: Any) -> StrategyEquityBaseline:
    if not isinstance(value, dict):
        raise ValueError("strategy equity baseline must be an object")
    try:
        return StrategyEquityBaseline(
            **{
                **value,
                "allocated_capital": Decimal(value["allocated_capital"]),
                "created_at": _parse_utc(value["created_at"]),
            }
        )
    except (KeyError, TypeError, ArithmeticError) as error:
        raise ValueError("strategy equity baseline fields differ") from error


def _decode_continuation_declaration(value: Any) -> PaperContinuationDeclaration:
    if not isinstance(value, dict):
        raise ValueError("paper continuation declaration must be an object")
    try:
        return PaperContinuationDeclaration(
            **{
                **value,
                "declared_at": _parse_utc(value["declared_at"]),
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("paper continuation declaration fields differ") from error


def _decode_continuation_handoff(value: Any) -> PaperContinuationHandoff:
    if not isinstance(value, dict):
        raise ValueError("paper continuation handoff must be an object")
    decimal_fields = {
        "cash",
        "equity",
        "buying_power",
        "allocated_capital",
        "gross_buy_notional",
        "gross_sell_notional",
        "fill_cost_reserve",
        "strategy_cash",
        "strategy_equity",
        "peak_equity",
        "strategy_drawdown",
    }
    try:
        return PaperContinuationHandoff(
            **{
                **value,
                **{name: Decimal(value[name]) for name in decimal_fields},
                "positions": tuple(PositionSnapshot(**item) for item in value["positions"]),
                "source_fill_event_ids": tuple(value["source_fill_event_ids"]),
                "completed_at": _parse_utc(value["completed_at"]),
            }
        )
    except (ArithmeticError, KeyError, TypeError, ValueError) as error:
        raise ValueError("paper continuation handoff fields differ") from error


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


def _continuation_tables_present(connection: sqlite3.Connection) -> bool:
    present = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name IN ('paper_continuation_declarations', "
            "'paper_continuation_handoffs')"
        ).fetchall()
    }
    if present == _CONTINUATION_TABLES:
        return True
    event_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM journal WHERE event_type IN "
            "('paper-continuation-declared', 'paper-continuation-completed')"
        ).fetchone()[0]
    )
    if present or event_count:
        raise JournalIntegrityError("paper continuation schema and journal differ")
    return False


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
