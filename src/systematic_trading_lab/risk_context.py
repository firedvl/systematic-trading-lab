"""Read-only RiskContext derived from verified execution evidence."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from .execution import JournalIntegrityError
from .fingerprints import fingerprint
from .reconciliation import (
    AccountDailyPnlEvidence,
    ReconciliationStore,
    _PaperSnapshotAttestationV2,
)
from .risk import RiskContext, RiskLimits
from .risk_inputs import derive_long_exposure
from .strategy_equity import StrategyEquityCheckpoint, StrategyEquityStore


@dataclass(frozen=True)
class AttestedRiskContext:
    context: RiskContext
    authorization_id: str
    authorization_fingerprint: str
    risk_configuration_fingerprint: str
    portfolio_snapshot_fingerprint: str
    portfolio_attestation_fingerprint: str
    risk_input_evidence_id: str
    settlement_proof_fingerprint: str
    strategy_equity_checkpoint_fingerprint: str
    daily_pnl_evidence_fingerprint: str
    active_reservation_set_fingerprint: str
    emergency_generation: int

    def __post_init__(self) -> None:
        if not self.authorization_id or self.authorization_id != self.authorization_id.strip():
            raise ValueError("authorization ID is invalid")
        for value in (
            self.authorization_fingerprint,
            self.risk_configuration_fingerprint,
            self.portfolio_snapshot_fingerprint,
            self.portfolio_attestation_fingerprint,
            self.risk_input_evidence_id,
            self.settlement_proof_fingerprint,
            self.strategy_equity_checkpoint_fingerprint,
            self.daily_pnl_evidence_fingerprint,
            self.active_reservation_set_fingerprint,
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError("attested risk-context fingerprint is invalid")
        if (
            self.context.active_reservation_set_fingerprint
            != self.active_reservation_set_fingerprint
            or self.emergency_generation < 1
        ):
            raise ValueError("attested risk-context authority is inconsistent")

    @property
    def proof_fingerprint(self) -> str:
        return fingerprint(self)


class AttestedRiskContextStore(StrategyEquityStore):
    """Verify and compose all current risk inputs without mutating state."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)

    def derive(
        self,
        *,
        authorization_id: str,
        symbol: str,
        limits: RiskLimits,
        evaluated_at: datetime,
    ) -> AttestedRiskContext:
        _utc(evaluated_at)
        with self._connect() as connection:
            connection.execute("BEGIN")
            return self._derive(
                connection,
                authorization_id=authorization_id,
                symbol=symbol,
                limits=limits,
                evaluated_at=evaluated_at,
            )

    def _derive(
        self,
        connection: sqlite3.Connection,
        *,
        authorization_id: str,
        symbol: str,
        limits: RiskLimits,
        evaluated_at: datetime,
    ) -> AttestedRiskContext:
        self._verify_connection(connection)
        self._verify_reservations(connection)
        self._verify_releases(connection)
        self._verify_orders(connection)
        authorities = self._authorities(connection)
        checkpoints = self._verify_checkpoints(connection)
        snapshots, attestations, _, _ = ReconciliationStore._verify_reconciliation(
            cast(ReconciliationStore, self), connection
        )
        authorizations = self._verify_authorizations(connection)
        emergency = self._verify_emergency(connection)
        try:
            authorization = authorizations[authorization_id]
            checkpoint = _latest_checkpoint(checkpoints, authorization_id)
            risk_input = authorities[2][checkpoint.risk_input_evidence_id]
            settlement = authorities[1][checkpoint.settlement_proof_id]
            snapshot = snapshots[risk_input.portfolio_snapshot_id]
            attestation = attestations[snapshot.snapshot_id]
        except (KeyError, IndexError) as error:
            raise JournalIntegrityError("attested risk-context authority is missing") from error
        if not isinstance(attestation, _PaperSnapshotAttestationV2):
            raise JournalIntegrityError("attested risk context requires prior-close equity")
        reservation_set = self._active_reservation_set(
            connection, account_id=limits.account_id, at=evaluated_at
        )
        daily_pnl = AccountDailyPnlEvidence(
            snapshot_id=snapshot.snapshot_id,
            snapshot_fingerprint=snapshot.snapshot_fingerprint,
            attestation_fingerprint=attestation.attestation_fingerprint,
            account_id=snapshot.account_id,
            equity=snapshot.equity,
            previous_close_equity=attestation.previous_close_equity,
            daily_pnl=snapshot.equity - attestation.previous_close_equity,
            observed_at=snapshot.account_observed_at,
        )
        try:
            valuation = derive_long_exposure(risk_input, snapshot, symbol=symbol)
            quote = next(item for item in risk_input.quotes if item.symbol == symbol)
        except (ValueError, StopIteration) as error:
            raise JournalIntegrityError("attested risk-context valuation is incomplete") from error
        if (
            authorization.account_id != limits.account_id
            or authorization.risk_configuration_fingerprint != limits.configuration_fingerprint
            or checkpoint.authorization_id != authorization_id
            or checkpoint.risk_configuration_fingerprint != limits.configuration_fingerprint
            or checkpoint.settlement_proof_fingerprint != settlement.proof_fingerprint
            or checkpoint.advance_fingerprint != settlement.advance_fingerprint
            or settlement.emergency_generation != emergency.generation
            or checkpoint.marked_at > evaluated_at
            or checkpoint.risk_input_evidence_id != risk_input.evidence_id
            or settlement.observed_snapshot_id != snapshot.snapshot_id
            or risk_input.completed_at > evaluated_at
            or evaluated_at < authorization.authorized_at
            or evaluated_at >= authorization.expires_at
            or evaluated_at < limits.effective_at
            or evaluated_at >= limits.expires_at
            or symbol not in limits.allowed_symbols
            or any(
                observed > evaluated_at
                or (evaluated_at - observed).total_seconds() > limits.max_snapshot_age_seconds
                for observed in (
                    snapshot.account_observed_at,
                    snapshot.positions_observed_at,
                    snapshot.orders_observed_at,
                    quote.observed_at,
                    risk_input.clock.observed_at,
                    checkpoint.marked_at,
                )
            )
        ):
            raise JournalIntegrityError("attested risk-context evidence is stale or mismatched")
        orders_last_minute = connection.execute(
            "SELECT COUNT(*) FROM capacity_reservations "
            "WHERE json_extract(reservation_json, '$.account_id') = ? "
            "AND reserved_at > ? AND reserved_at <= ?",
            (
                limits.account_id,
                _utc_text(evaluated_at - timedelta(minutes=1)),
                _utc_text(evaluated_at),
            ),
        ).fetchone()[0]
        context = RiskContext(
            account_id=snapshot.account_id,
            evaluated_at=evaluated_at,
            equity=snapshot.equity,
            cash=snapshot.cash,
            buying_power=snapshot.buying_power,
            current_gross_exposure=valuation.current_gross_exposure,
            current_symbol_notional=valuation.current_symbol_notional,
            current_symbol_quantity=valuation.current_quantity,
            pending_buy_notional=reservation_set.cash,
            pending_order_notional=reservation_set.order_notional,
            active_reservation_set_fingerprint=reservation_set.set_fingerprint,
            open_order_count=len(snapshot.open_orders),
            pending_order_count=reservation_set.reservation_count,
            orders_last_minute=int(orders_last_minute),
            daily_pnl=daily_pnl.daily_pnl,
            strategy_drawdown=checkpoint.strategy_drawdown,
            quote_bid_price=quote.bid_price,
            quote_ask_price=quote.ask_price,
            account_observed_at=snapshot.account_observed_at,
            positions_observed_at=snapshot.positions_observed_at,
            orders_observed_at=snapshot.orders_observed_at,
            quote_observed_at=quote.observed_at,
            clock_observed_at=risk_input.clock.observed_at,
            regular_session_open=risk_input.clock.regular_session_open,
            emergency_disabled=emergency.disabled,
        )
        return AttestedRiskContext(
            context=context,
            authorization_id=authorization.authorization_id,
            authorization_fingerprint=authorization.authorization_fingerprint,
            risk_configuration_fingerprint=limits.configuration_fingerprint,
            portfolio_snapshot_fingerprint=snapshot.snapshot_fingerprint,
            portfolio_attestation_fingerprint=attestation.attestation_fingerprint,
            risk_input_evidence_id=risk_input.evidence_id,
            settlement_proof_fingerprint=settlement.proof_fingerprint,
            strategy_equity_checkpoint_fingerprint=checkpoint.checkpoint_fingerprint,
            daily_pnl_evidence_fingerprint=daily_pnl.evidence_fingerprint,
            active_reservation_set_fingerprint=reservation_set.set_fingerprint,
            emergency_generation=emergency.generation,
        )


def _latest_checkpoint(
    checkpoints: dict[str, StrategyEquityCheckpoint], authorization_id: str
) -> StrategyEquityCheckpoint:
    matching = [item for item in checkpoints.values() if item.authorization_id == authorization_id]
    if not matching:
        raise IndexError(authorization_id)
    return matching[-1]


def _utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("risk-context evaluation time must be UTC-aware")


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
