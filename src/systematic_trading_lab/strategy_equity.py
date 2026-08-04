"""Immutable strategy equity derived from fills and attested bid marks."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

from .broker_events import BrokerOrderEvent, ExpectedPositionAdvance, _filled_notional
from .execution import JournalIntegrityError
from .fingerprints import canonical_json, canonicalize, fingerprint
from .orders import OrderSide, _decode_delta
from .position_settlement import PositionSettlementEvidence, PositionSettlementStore
from .reconciliation import (
    PositionSnapshot,
    ReconciliationStore,
    StrategyEquityBaseline,
)
from .risk import RiskLimits
from .risk_inputs import RiskInputEvidence, RiskInputEvidenceStore

_BPS = Decimal(10_000)
_MARKING_BASIS = "iex-bid-liquidation-v1"


@dataclass(frozen=True)
class StrategyEquityCheckpoint:
    checkpoint_id: str
    strategy_equity_baseline_id: str
    strategy_equity_baseline_fingerprint: str
    prior_checkpoint_fingerprint: str | None
    authorization_id: str
    account_id: str
    strategy_id: str
    strategy_version: str
    risk_configuration_fingerprint: str
    settlement_proof_id: str
    settlement_proof_fingerprint: str
    risk_input_evidence_id: str
    advance_fingerprint: str
    fill_event_ids: tuple[str, ...]
    fill_cost_bps: Decimal
    allocated_capital: Decimal
    gross_buy_notional: Decimal
    gross_sell_notional: Decimal
    fill_cost_reserve: Decimal
    strategy_cash: Decimal
    positions: tuple[PositionSnapshot, ...]
    position_market_value: Decimal
    strategy_equity: Decimal
    peak_equity: Decimal
    strategy_drawdown: Decimal
    marking_basis: str
    marked_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("strategy equity baseline ID", self.strategy_equity_baseline_id),
            ("authorization ID", self.authorization_id),
            ("account ID", self.account_id),
            ("strategy ID", self.strategy_id),
            ("strategy version", self.strategy_version),
            ("settlement proof ID", self.settlement_proof_id),
        ):
            if not value or value != value.strip() or len(value) > 128:
                raise ValueError(f"{name} is invalid")
        for name, value in (
            ("checkpoint", self.checkpoint_id),
            ("strategy equity baseline", self.strategy_equity_baseline_fingerprint),
            ("risk configuration", self.risk_configuration_fingerprint),
            ("settlement proof", self.settlement_proof_fingerprint),
            ("risk input", self.risk_input_evidence_id),
            ("advance", self.advance_fingerprint),
        ):
            _sha256(name, value)
        if self.prior_checkpoint_fingerprint is not None:
            _sha256("prior checkpoint", self.prior_checkpoint_fingerprint)
        if not self.fill_event_ids or self.fill_event_ids != tuple(
            sorted(set(self.fill_event_ids))
        ):
            raise ValueError("fill event IDs must be sorted and unique")
        for event_id in self.fill_event_ids:
            if not event_id or event_id != event_id.strip() or len(event_id) > 128:
                raise ValueError("fill event ID is invalid")
        for name, decimal_value in (
            ("fill cost", self.fill_cost_bps),
            ("allocated capital", self.allocated_capital),
            ("gross buy notional", self.gross_buy_notional),
            ("gross sell notional", self.gross_sell_notional),
            ("fill cost reserve", self.fill_cost_reserve),
            ("position market value", self.position_market_value),
            ("strategy equity", self.strategy_equity),
            ("peak equity", self.peak_equity),
            ("strategy drawdown", self.strategy_drawdown),
        ):
            if not decimal_value.is_finite() or decimal_value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if not self.strategy_cash.is_finite():
            raise ValueError("strategy cash must be finite")
        if (
            self.allocated_capital <= 0
            or self.fill_cost_reserve
            != (self.gross_buy_notional + self.gross_sell_notional) * self.fill_cost_bps / _BPS
            or self.strategy_cash
            != self.allocated_capital
            - self.gross_buy_notional
            + self.gross_sell_notional
            - self.fill_cost_reserve
            or self.strategy_equity != self.strategy_cash + self.position_market_value
            or self.strategy_equity <= 0
            or self.peak_equity < self.strategy_equity
            or self.strategy_drawdown
            != (self.peak_equity - self.strategy_equity) / self.peak_equity
        ):
            raise ValueError("strategy equity and drawdown are inconsistent")
        if (
            self.positions != tuple(sorted(self.positions, key=lambda item: item.symbol))
            or self.marking_basis != _MARKING_BASIS
        ):
            raise ValueError("strategy position marks are invalid")
        if self.marked_at.tzinfo is None or self.marked_at.utcoffset() != UTC.utcoffset(
            self.marked_at
        ):
            raise ValueError("strategy equity mark time must be UTC-aware")

    @property
    def checkpoint_fingerprint(self) -> str:
        return fingerprint(self)


class StrategyEquityStore(PositionSettlementStore):
    """Derive strategy equity without creating risk or broker authority."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        with self._connect() as connection:
            required = {"strategy_equity_baselines", "risk_input_evidence"}
            present = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if not required.issubset(present):
                raise JournalIntegrityError("strategy equity prerequisite storage is missing")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS strategy_equity_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    strategy_equity_baseline_id TEXT NOT NULL
                        REFERENCES strategy_equity_baselines(baseline_id),
                    settlement_proof_id TEXT NOT NULL
                        REFERENCES position_settlement_evidence(proof_id),
                    risk_input_evidence_id TEXT NOT NULL UNIQUE
                        REFERENCES risk_input_evidence(evidence_id),
                    checkpoint_fingerprint TEXT NOT NULL UNIQUE,
                    checkpoint_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS strategy_equity_checkpoints_no_update
                BEFORE UPDATE ON strategy_equity_checkpoints BEGIN
                    SELECT RAISE(ABORT, 'strategy equity checkpoints are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS strategy_equity_checkpoints_no_delete
                BEFORE DELETE ON strategy_equity_checkpoints BEGIN
                    SELECT RAISE(ABORT, 'strategy equity checkpoints are immutable');
                END;
                """
            )
            connection.commit()
            self._verify_checkpoints(connection)

    def record_checkpoint(
        self,
        *,
        strategy_equity_baseline_id: str,
        settlement_proof_id: str,
        risk_input_evidence_id: str,
        limits: RiskLimits,
        marked_at: datetime,
    ) -> StrategyEquityCheckpoint:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            checkpoints = self._verify_checkpoints(connection)
            authorities = self._authorities(connection)
            baseline = authorities[0].get(strategy_equity_baseline_id)
            settlement = authorities[1].get(settlement_proof_id)
            risk_input = authorities[2].get(risk_input_evidence_id)
            if baseline is None or settlement is None or risk_input is None:
                raise JournalIntegrityError("strategy equity checkpoint authority is missing")
            replay = next(
                (
                    item
                    for item in checkpoints.values()
                    if item.risk_input_evidence_id == risk_input_evidence_id
                ),
                None,
            )
            if replay is not None:
                if (
                    replay.strategy_equity_baseline_id != strategy_equity_baseline_id
                    or replay.settlement_proof_id != settlement_proof_id
                    or replay.fill_cost_bps != limits.strategy_fill_cost_bps
                    or replay.marked_at != marked_at
                    or limits.configuration_fingerprint != baseline.risk_configuration_fingerprint
                    or limits.account_id != baseline.account_id
                    or marked_at < limits.effective_at
                    or marked_at >= limits.expires_at
                ):
                    raise JournalIntegrityError(
                        "risk input is bound to a different strategy equity checkpoint"
                    )
                connection.commit()
                return replay
            prior = _latest_checkpoint(checkpoints, strategy_equity_baseline_id)
            checkpoint = self._derive_checkpoint(
                connection,
                baseline=baseline,
                settlement=settlement,
                risk_input=risk_input,
                fill_cost_bps=limits.strategy_fill_cost_bps,
                prior=prior,
                marked_at=marked_at,
                before_sequence=None,
            )
            if (
                limits.configuration_fingerprint != baseline.risk_configuration_fingerprint
                or limits.account_id != baseline.account_id
                or marked_at < limits.effective_at
                or marked_at >= limits.expires_at
            ):
                raise JournalIntegrityError("strategy equity limits differ from the baseline")
            existing = checkpoints.get(checkpoint.checkpoint_id)
            if existing is not None:
                connection.commit()
                return existing
            sequence = self._append_event(
                connection,
                occurred_at=marked_at,
                event_type="strategy-equity-checkpoint-recorded",
                entity_type="strategy-equity-checkpoint",
                entity_id=checkpoint.checkpoint_id,
                payload=canonicalize(checkpoint),
            )
            connection.execute(
                "INSERT INTO strategy_equity_checkpoints VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    checkpoint.checkpoint_id,
                    checkpoint.strategy_equity_baseline_id,
                    checkpoint.settlement_proof_id,
                    checkpoint.risk_input_evidence_id,
                    checkpoint.checkpoint_fingerprint,
                    canonical_json(checkpoint),
                    sequence,
                ),
            )
            connection.commit()
        return checkpoint

    def latest_checkpoint(self, authorization_id: str) -> StrategyEquityCheckpoint:
        with self._connect() as connection:
            connection.execute("BEGIN")
            checkpoints = self._verify_checkpoints(connection)
        matching = [
            item for item in checkpoints.values() if item.authorization_id == authorization_id
        ]
        if not matching:
            raise JournalIntegrityError("strategy equity checkpoint is missing")
        return matching[-1]

    def _authorities(
        self, connection: sqlite3.Connection
    ) -> tuple[
        dict[str, StrategyEquityBaseline],
        dict[str, PositionSettlementEvidence],
        dict[str, RiskInputEvidence],
        dict[str, BrokerOrderEvent],
        dict[str, ExpectedPositionAdvance],
    ]:
        self._verify_connection(connection)
        events = self._verify_broker_events(connection)
        advances = self._verify_expected_position_advances(connection, events)
        settlements = self._verify_settlements(connection)
        _, _, reconciliation_baselines, _ = ReconciliationStore._verify_reconciliation(
            cast(ReconciliationStore, self), connection
        )
        authorizations = self._verify_authorizations(connection)
        baselines = ReconciliationStore._verify_strategy_equity_baselines(
            cast(ReconciliationStore, self),
            connection,
            reconciliation_baselines,
            authorizations,
        )
        risk_inputs = RiskInputEvidenceStore._verify_risk_inputs(
            cast(RiskInputEvidenceStore, self), connection
        )
        return baselines, settlements, risk_inputs, events, advances

    def _verify_checkpoints(
        self, connection: sqlite3.Connection
    ) -> dict[str, StrategyEquityCheckpoint]:
        authorities = self._authorities(connection)
        rows = connection.execute(
            "SELECT checkpoint_id, strategy_equity_baseline_id, settlement_proof_id, "
            "risk_input_evidence_id, checkpoint_fingerprint, checkpoint_json, "
            "journal_sequence FROM strategy_equity_checkpoints ORDER BY journal_sequence"
        ).fetchall()
        count = connection.execute(
            "SELECT COUNT(*) FROM journal WHERE event_type = 'strategy-equity-checkpoint-recorded'"
        ).fetchone()[0]
        if len(rows) != count:
            raise JournalIntegrityError("strategy equity checkpoint and journal counts differ")
        result: dict[str, StrategyEquityCheckpoint] = {}
        for row in rows:
            try:
                stored = _decode_checkpoint(json.loads(row[5]))
                baseline = authorities[0][stored.strategy_equity_baseline_id]
                settlement = authorities[1][stored.settlement_proof_id]
                risk_input = authorities[2][stored.risk_input_evidence_id]
                prior = _latest_checkpoint(result, stored.strategy_equity_baseline_id)
                expected = self._derive_checkpoint(
                    connection,
                    baseline=baseline,
                    settlement=settlement,
                    risk_input=risk_input,
                    fill_cost_bps=stored.fill_cost_bps,
                    prior=prior,
                    marked_at=stored.marked_at,
                    before_sequence=int(row[6]),
                )
            except (KeyError, ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError(
                    "stored strategy equity checkpoint is invalid"
                ) from error
            journal = connection.execute(
                "SELECT occurred_at, event_type, entity_type, entity_id, payload_json "
                "FROM journal WHERE sequence = ?",
                (row[6],),
            ).fetchone()
            if (
                row[:5]
                != (
                    expected.checkpoint_id,
                    expected.strategy_equity_baseline_id,
                    expected.settlement_proof_id,
                    expected.risk_input_evidence_id,
                    expected.checkpoint_fingerprint,
                )
                or stored != expected
                or row[5] != canonical_json(expected)
                or journal
                != (
                    _utc_text(expected.marked_at),
                    "strategy-equity-checkpoint-recorded",
                    "strategy-equity-checkpoint",
                    expected.checkpoint_id,
                    canonical_json(expected),
                )
            ):
                raise JournalIntegrityError("strategy equity checkpoint differs from its evidence")
            result[expected.checkpoint_id] = expected
        return result

    def _derive_checkpoint(
        self,
        connection: sqlite3.Connection,
        *,
        baseline: StrategyEquityBaseline,
        settlement: PositionSettlementEvidence,
        risk_input: RiskInputEvidence,
        fill_cost_bps: Decimal,
        prior: StrategyEquityCheckpoint | None,
        marked_at: datetime,
        before_sequence: int | None,
    ) -> StrategyEquityCheckpoint:
        if not fill_cost_bps.is_finite() or fill_cost_bps < 0:
            raise ValueError("strategy fill cost must be finite and nonnegative")
        authorization = self._verify_authorizations(connection).get(baseline.authorization_id)
        if (
            authorization is None
            or marked_at < authorization.authorized_at
            or marked_at >= authorization.expires_at
            or settlement.baseline_id != baseline.reconciliation_baseline_id
            or settlement.authorization_id != baseline.authorization_id
            or settlement.account_id != baseline.account_id
            or settlement.risk_configuration_fingerprint != baseline.risk_configuration_fingerprint
            or risk_input.authorization_id != baseline.authorization_id
            or risk_input.account_id != baseline.account_id
            or risk_input.risk_configuration_fingerprint != baseline.risk_configuration_fingerprint
            or risk_input.portfolio_snapshot_id != settlement.observed_snapshot_id
            or risk_input.portfolio_snapshot_fingerprint != settlement.observed_snapshot_fingerprint
            or risk_input.portfolio_attestation_fingerprint != settlement.attestation_fingerprint
            or risk_input.completed_at > marked_at
            or any(
                quote.observed_at > marked_at
                or (marked_at - quote.observed_at).total_seconds() > risk_input.maximum_age_seconds
                for quote in risk_input.quotes
            )
            or (prior is not None and marked_at <= prior.marked_at)
        ):
            raise ValueError("strategy equity authorities do not align")
        advance_row = connection.execute(
            "SELECT advance_json, journal_sequence FROM expected_position_advances "
            "WHERE advance_fingerprint = ? AND baseline_id = ?",
            (settlement.advance_fingerprint, settlement.baseline_id),
        ).fetchone()
        if advance_row is None:
            raise ValueError("strategy equity advance is missing")
        advance = _decode_advance(json.loads(str(advance_row[0])))
        latest_advance = connection.execute(
            "SELECT advance_fingerprint FROM expected_position_advances "
            "WHERE baseline_id = ? AND (? IS NULL OR journal_sequence < ?) "
            "ORDER BY journal_sequence DESC LIMIT 1",
            (
                baseline.reconciliation_baseline_id,
                before_sequence,
                before_sequence,
            ),
        ).fetchone()
        if latest_advance != (settlement.advance_fingerprint,):
            raise ValueError("strategy equity settlement does not cover the latest fill")
        quotes = {item.symbol: item.bid_price for item in risk_input.quotes}
        if not set(item.symbol for item in advance.positions).issubset(quotes):
            raise ValueError("strategy equity requires a bid for every position")
        rows = connection.execute(
            "SELECT b.event_json, o.delta_json FROM expected_position_advances a "
            "JOIN broker_events b ON b.event_id = a.broker_event_id "
            "JOIN orders o ON o.order_id = b.client_order_id "
            "JOIN capacity_reservations r ON r.reservation_id = o.reservation_id "
            "WHERE a.baseline_id = ? AND r.authorization_id = ? "
            "AND a.journal_sequence <= ? "
            "ORDER BY a.journal_sequence",
            (
                baseline.reconciliation_baseline_id,
                baseline.authorization_id,
                int(advance_row[1]),
            ),
        ).fetchall()
        prior_notional: dict[str, Decimal] = {}
        gross_buy = Decimal(0)
        gross_sell = Decimal(0)
        event_ids: list[str] = []
        for event_json, delta_json in rows:
            event = _decode_event(json.loads(str(event_json)))
            delta = _decode_delta(json.loads(str(delta_json)))
            cumulative = _filled_notional(event)
            increment = cumulative - prior_notional.get(event.client_order_id, Decimal(0))
            if increment <= 0:
                raise ValueError("strategy fill notional must advance")
            prior_notional[event.client_order_id] = cumulative
            event_ids.append(event.event_id)
            if delta.side is OrderSide.BUY:
                gross_buy += increment
            else:
                gross_sell += increment
        fill_cost = (gross_buy + gross_sell) * fill_cost_bps / _BPS
        cash = baseline.allocated_capital - gross_buy + gross_sell - fill_cost
        market_value = sum(
            (quotes[item.symbol] * item.quantity for item in advance.positions), Decimal(0)
        )
        equity = cash + market_value
        prior_peak = baseline.allocated_capital if prior is None else prior.peak_equity
        peak = max(prior_peak, equity)
        checkpoint_id = fingerprint(
            {
                "strategy_equity_baseline": baseline.baseline_fingerprint,
                "prior_checkpoint": (None if prior is None else prior.checkpoint_fingerprint),
                "settlement": settlement.proof_fingerprint,
                "risk_input": risk_input.evidence_id,
                "fill_cost_bps": fill_cost_bps,
                "marked_at": marked_at,
            }
        )
        return StrategyEquityCheckpoint(
            checkpoint_id=checkpoint_id,
            strategy_equity_baseline_id=baseline.baseline_id,
            strategy_equity_baseline_fingerprint=baseline.baseline_fingerprint,
            prior_checkpoint_fingerprint=(None if prior is None else prior.checkpoint_fingerprint),
            authorization_id=baseline.authorization_id,
            account_id=baseline.account_id,
            strategy_id=baseline.strategy_id,
            strategy_version=baseline.strategy_version,
            risk_configuration_fingerprint=baseline.risk_configuration_fingerprint,
            settlement_proof_id=settlement.proof_id,
            settlement_proof_fingerprint=settlement.proof_fingerprint,
            risk_input_evidence_id=risk_input.evidence_id,
            advance_fingerprint=advance.advance_fingerprint,
            fill_event_ids=tuple(sorted(event_ids)),
            fill_cost_bps=fill_cost_bps,
            allocated_capital=baseline.allocated_capital,
            gross_buy_notional=gross_buy,
            gross_sell_notional=gross_sell,
            fill_cost_reserve=fill_cost,
            strategy_cash=cash,
            positions=advance.positions,
            position_market_value=market_value,
            strategy_equity=equity,
            peak_equity=peak,
            strategy_drawdown=(peak - equity) / peak,
            marking_basis=_MARKING_BASIS,
            marked_at=marked_at,
        )


def _latest_checkpoint(
    checkpoints: dict[str, StrategyEquityCheckpoint], baseline_id: str
) -> StrategyEquityCheckpoint | None:
    matching = [
        item for item in checkpoints.values() if item.strategy_equity_baseline_id == baseline_id
    ]
    return None if not matching else matching[-1]


def _decode_checkpoint(value: object) -> StrategyEquityCheckpoint:
    if not isinstance(value, dict):
        raise ValueError("strategy equity checkpoint must be an object")
    try:
        return StrategyEquityCheckpoint(
            **{
                **value,
                "fill_event_ids": tuple(value["fill_event_ids"]),
                "fill_cost_bps": Decimal(str(value["fill_cost_bps"])),
                "allocated_capital": Decimal(str(value["allocated_capital"])),
                "gross_buy_notional": Decimal(str(value["gross_buy_notional"])),
                "gross_sell_notional": Decimal(str(value["gross_sell_notional"])),
                "fill_cost_reserve": Decimal(str(value["fill_cost_reserve"])),
                "strategy_cash": Decimal(str(value["strategy_cash"])),
                "positions": tuple(PositionSnapshot(**item) for item in value["positions"]),
                "position_market_value": Decimal(str(value["position_market_value"])),
                "strategy_equity": Decimal(str(value["strategy_equity"])),
                "peak_equity": Decimal(str(value["peak_equity"])),
                "strategy_drawdown": Decimal(str(value["strategy_drawdown"])),
                "marked_at": _parse_utc(str(value["marked_at"])),
            }
        )
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        raise ValueError("strategy equity checkpoint is invalid") from error


def _decode_event(value: object) -> BrokerOrderEvent:
    from .broker_events import _decode_event as decode

    return decode(value)


def _decode_advance(value: object) -> ExpectedPositionAdvance:
    from .broker_events import _decode_expected_position_advance

    return _decode_expected_position_advance(value)


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must be UTC-aware")
    return parsed


def _sha256(name: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} fingerprint is invalid")
