"""Independent broker-free risk evaluation and emergency state."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .execution import ExecutionIntent, ExecutionStore, JournalIntegrityError
from .experiments import HoldoutAccessError, validate_passing_qualification_evidence
from .fingerprints import canonical_json, canonicalize, fingerprint

_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,15}")


@dataclass(frozen=True)
class RiskLimits:
    configuration_id: str
    account_id: str
    allowed_symbols: tuple[str, ...]
    max_order_notional: Decimal
    max_position_notional: Decimal
    max_gross_exposure: Decimal
    strategy_capital_allocation: Decimal
    strategy_fill_cost_bps: Decimal
    min_cash: Decimal
    max_open_orders: int
    max_orders_per_minute: int
    max_daily_loss: Decimal
    max_strategy_drawdown: Decimal
    max_price_deviation_bps: Decimal
    max_snapshot_age_seconds: int
    min_reconciliation_stability_seconds: int
    reviewed_by: str
    review_reason: str
    effective_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for text_name, text_value in (
            ("configuration ID", self.configuration_id),
            ("account ID", self.account_id),
            ("reviewer", self.reviewed_by),
            ("review reason", self.review_reason),
        ):
            _text(text_name, text_value)
        if (
            not self.allowed_symbols
            or self.allowed_symbols != tuple(sorted(set(self.allowed_symbols)))
            or any(_SYMBOL.fullmatch(symbol) is None for symbol in self.allowed_symbols)
        ):
            raise ValueError("allowed symbols must be a sorted unique uppercase tuple")
        for decimal_name, decimal_value in (
            ("maximum order notional", self.max_order_notional),
            ("maximum position notional", self.max_position_notional),
            ("maximum gross exposure", self.max_gross_exposure),
            ("strategy capital allocation", self.strategy_capital_allocation),
            ("maximum daily loss", self.max_daily_loss),
            ("maximum strategy drawdown", self.max_strategy_drawdown),
            ("maximum price deviation", self.max_price_deviation_bps),
        ):
            _positive_decimal(decimal_name, decimal_value)
        if not self.strategy_fill_cost_bps.is_finite() or self.strategy_fill_cost_bps < 0:
            raise ValueError("strategy fill cost must be finite and nonnegative")
        if not self.min_cash.is_finite() or self.min_cash < 0:
            raise ValueError("minimum cash must be finite and nonnegative")
        if self.max_strategy_drawdown > 1:
            raise ValueError("maximum strategy drawdown cannot exceed one")
        if self.max_open_orders < 1 or self.max_orders_per_minute < 1:
            raise ValueError("order limits must be positive")
        if isinstance(self.max_snapshot_age_seconds, bool) or self.max_snapshot_age_seconds < 1:
            raise ValueError("snapshot maximum age must be positive")
        if (
            isinstance(self.min_reconciliation_stability_seconds, bool)
            or self.min_reconciliation_stability_seconds < 1
        ):
            raise ValueError("reconciliation stability interval must be positive")
        _utc("risk effective time", self.effective_at)
        _utc("risk expiry", self.expires_at)
        if self.expires_at <= self.effective_at:
            raise ValueError("risk expiry must follow its effective time")

    @property
    def configuration_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class RiskContext:
    account_id: str
    evaluated_at: datetime
    equity: Decimal
    cash: Decimal
    buying_power: Decimal
    current_gross_exposure: Decimal
    current_symbol_notional: Decimal
    current_symbol_quantity: int
    pending_buy_notional: Decimal
    pending_order_notional: Decimal
    active_reservation_set_fingerprint: str
    open_order_count: int
    pending_order_count: int
    orders_last_minute: int
    daily_pnl: Decimal
    strategy_drawdown: Decimal
    quote_bid_price: Decimal
    quote_ask_price: Decimal
    account_observed_at: datetime
    positions_observed_at: datetime
    orders_observed_at: datetime
    quote_observed_at: datetime
    clock_observed_at: datetime
    regular_session_open: bool
    emergency_disabled: bool

    def __post_init__(self) -> None:
        _text("account ID", self.account_id)
        _positive_decimal("equity", self.equity)
        for time_name, time_value in (
            ("evaluation time", self.evaluated_at),
            ("account observation", self.account_observed_at),
            ("position observation", self.positions_observed_at),
            ("order observation", self.orders_observed_at),
            ("quote observation", self.quote_observed_at),
            ("clock observation", self.clock_observed_at),
        ):
            _utc(time_name, time_value)
        for decimal_name, decimal_value in (
            ("cash", self.cash),
            ("buying power", self.buying_power),
            ("gross exposure", self.current_gross_exposure),
            ("symbol notional", self.current_symbol_notional),
            ("pending buy notional", self.pending_buy_notional),
            ("pending order notional", self.pending_order_notional),
            ("strategy drawdown", self.strategy_drawdown),
        ):
            if not decimal_value.is_finite() or decimal_value < 0:
                raise ValueError(f"{decimal_name} must be finite and nonnegative")
        if not self.daily_pnl.is_finite():
            raise ValueError("daily PnL must be finite")
        _sha256("active reservation set", self.active_reservation_set_fingerprint)
        if self.current_symbol_notional > self.current_gross_exposure:
            raise ValueError("symbol notional cannot exceed gross exposure")
        _positive_decimal("quote bid price", self.quote_bid_price)
        _positive_decimal("quote ask price", self.quote_ask_price)
        if self.quote_bid_price > self.quote_ask_price:
            raise ValueError("quote bid price cannot exceed ask price")
        if isinstance(self.current_symbol_quantity, bool) or self.current_symbol_quantity < 0:
            raise ValueError("current symbol quantity must be nonnegative")
        if self.current_symbol_notional != self.quote_ask_price * self.current_symbol_quantity:
            raise ValueError("current symbol notional must use the ask price")
        if min(self.open_order_count, self.pending_order_count, self.orders_last_minute) < 0:
            raise ValueError("order counts must be nonnegative")

    @property
    def context_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reasons: tuple[str, ...]
    intent_fingerprint: str
    configuration_fingerprint: str
    context_fingerprint: str
    decided_at: datetime
    order_notional: Decimal
    cash_reservation: Decimal
    gross_exposure_reservation: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.approved, bool) or self.approved != (not self.reasons):
            raise ValueError("risk approval must match its reasons")
        if any(not isinstance(reason, str) or not reason for reason in self.reasons):
            raise ValueError("risk decision reasons must be nonempty strings")
        for fingerprint_name, fingerprint_value in (
            ("intent", self.intent_fingerprint),
            ("configuration", self.configuration_fingerprint),
            ("context", self.context_fingerprint),
        ):
            _sha256(fingerprint_name, fingerprint_value)
        _utc("risk decision time", self.decided_at)
        for amount_name, amount_value in (
            ("order notional", self.order_notional),
            ("cash reservation", self.cash_reservation),
            ("gross exposure reservation", self.gross_exposure_reservation),
        ):
            if not amount_value.is_finite() or amount_value < 0:
                raise ValueError(f"{amount_name} must be finite and nonnegative")


def evaluate_risk(
    intent: ExecutionIntent, limits: RiskLimits, context: RiskContext
) -> RiskDecision:
    """Evaluate one intent without broker or persistence authority."""
    reasons: list[str] = []
    now = context.evaluated_at
    if context.emergency_disabled:
        reasons.append("emergency-disabled")
    if context.account_id != limits.account_id:
        reasons.append("account-mismatch")
    if intent.symbol not in limits.allowed_symbols:
        reasons.append("symbol-not-allowed")
    if now < limits.effective_at or now >= limits.expires_at:
        reasons.append("risk-configuration-inactive")
    if intent.decision_timestamp > now or intent.expires_at <= now:
        reasons.append("intent-stale-or-future")
    observed = (
        context.account_observed_at,
        context.positions_observed_at,
        context.orders_observed_at,
        context.quote_observed_at,
        context.clock_observed_at,
    )
    if any(
        timestamp > now or (now - timestamp).total_seconds() > limits.max_snapshot_age_seconds
        for timestamp in observed
    ):
        reasons.append("snapshot-stale-or-future")
    if not context.regular_session_open:
        reasons.append("regular-session-closed")
    if context.daily_pnl <= -limits.max_daily_loss:
        reasons.append("daily-loss-limit")
    if context.strategy_drawdown >= limits.max_strategy_drawdown:
        reasons.append("strategy-drawdown-limit")
    if intent.target_weight is not None:
        target_notional = context.equity * intent.target_weight
        increasing = target_notional >= context.current_symbol_notional
        order_notional = abs(target_notional - context.current_symbol_notional)
    else:
        target_quantity = intent.target_quantity or 0
        quantity_delta = target_quantity - context.current_symbol_quantity
        increasing = quantity_delta >= 0
        target_notional = context.quote_ask_price * target_quantity
        order_notional = abs(quantity_delta) * (
            context.quote_ask_price if increasing else context.quote_bid_price
        )
    execution_quote = context.quote_ask_price if increasing else context.quote_bid_price
    deviation_bps = (
        abs(execution_quote - intent.reference_price) / intent.reference_price * Decimal(10_000)
    )
    if deviation_bps > limits.max_price_deviation_bps:
        reasons.append("price-deviation-limit")

    increase = max(Decimal(0), target_notional - context.current_symbol_notional)
    projected_position = target_notional + context.pending_order_notional
    projected_gross = (
        context.current_gross_exposure
        - context.current_symbol_notional
        + target_notional
        + context.pending_order_notional
    )
    cash_reservation = increase
    if order_notional > limits.max_order_notional:
        reasons.append("order-notional-limit")
    if projected_position > limits.max_position_notional:
        reasons.append("position-notional-limit")
    if projected_gross > limits.max_gross_exposure:
        reasons.append("gross-exposure-limit")
    if cash_reservation + context.pending_buy_notional > context.buying_power:
        reasons.append("buying-power-limit")
    if context.cash - cash_reservation - context.pending_buy_notional < limits.min_cash:
        reasons.append("minimum-cash-limit")
    if context.open_order_count + context.pending_order_count >= limits.max_open_orders:
        reasons.append("open-order-limit")
    if context.orders_last_minute + context.pending_order_count >= limits.max_orders_per_minute:
        reasons.append("order-rate-limit")

    return RiskDecision(
        approved=not reasons,
        reasons=tuple(reasons),
        intent_fingerprint=intent.intent_fingerprint,
        configuration_fingerprint=limits.configuration_fingerprint,
        context_fingerprint=context.context_fingerprint,
        decided_at=now,
        order_notional=order_notional,
        cash_reservation=cash_reservation,
        gross_exposure_reservation=increase,
    )


@dataclass(frozen=True)
class EmergencyState:
    disabled: bool
    generation: int
    reason: str
    operator: str
    changed_at: datetime
    journal_sequence: int


@dataclass(frozen=True)
class PaperAuthorization:
    authorization_id: str
    candidate_id: str
    strategy_id: str
    strategy_version: str
    parameters_fingerprint: str
    code_commit: str
    dataset_id: str
    dataset_fingerprint: str
    universe_id: str
    universe_fingerprint: str
    qualification_evidence_fingerprint: str
    account_id: str
    risk_configuration_fingerprint: str
    authorized_by: str
    authorization_reason: str
    authorized_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for name, text_value in (
            ("authorization ID", self.authorization_id),
            ("candidate ID", self.candidate_id),
            ("strategy ID", self.strategy_id),
            ("strategy version", self.strategy_version),
            ("code commit", self.code_commit),
            ("dataset ID", self.dataset_id),
            ("universe ID", self.universe_id),
            ("account ID", self.account_id),
            ("authorizer", self.authorized_by),
            ("authorization reason", self.authorization_reason),
        ):
            _text(name, text_value)
        for name, value in (
            ("parameters", self.parameters_fingerprint),
            ("dataset", self.dataset_fingerprint),
            ("universe", self.universe_fingerprint),
            ("qualification evidence", self.qualification_evidence_fingerprint),
            ("risk configuration", self.risk_configuration_fingerprint),
        ):
            _sha256(name, value)
        _utc("authorization time", self.authorized_at)
        _utc("authorization expiry", self.expires_at)
        if self.expires_at <= self.authorized_at:
            raise ValueError("paper authorization expiry must follow authorization time")

    @property
    def authorization_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class RiskDecisionReceipt:
    decision_id: str
    intent_id: str
    authorization_id: str
    approved: bool
    reasons: tuple[str, ...]
    decided_at: datetime
    journal_sequence: int


@dataclass(frozen=True)
class CapacityReservation:
    reservation_id: str
    decision_id: str
    intent_id: str
    authorization_id: str
    account_id: str
    configuration_fingerprint: str
    cash: Decimal
    gross_exposure: Decimal
    order_notional: Decimal
    reserved_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for name, text_value in (
            ("reservation ID", self.reservation_id),
            ("decision ID", self.decision_id),
            ("intent ID", self.intent_id),
            ("authorization ID", self.authorization_id),
            ("account ID", self.account_id),
        ):
            _text(name, text_value)
        _sha256("configuration", self.configuration_fingerprint)
        for name, amount in (
            ("cash reservation", self.cash),
            ("gross exposure reservation", self.gross_exposure),
            ("order notional", self.order_notional),
        ):
            if not amount.is_finite() or amount < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        _utc("reservation time", self.reserved_at)
        _utc("reservation expiry", self.expires_at)
        if self.expires_at <= self.reserved_at:
            raise ValueError("reservation expiry must follow reservation time")

    @property
    def reservation_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class ActiveReservationSet:
    account_id: str
    evaluated_at: datetime
    reservation_ids: tuple[str, ...]
    reservation_fingerprints: tuple[str, ...]
    cash: Decimal
    gross_exposure: Decimal
    order_notional: Decimal

    def __post_init__(self) -> None:
        _text("reservation-set account ID", self.account_id)
        _utc("reservation-set evaluation time", self.evaluated_at)
        if (
            self.reservation_ids != tuple(sorted(self.reservation_ids))
            or len(set(self.reservation_ids)) != len(self.reservation_ids)
            or len(self.reservation_ids) != len(self.reservation_fingerprints)
        ):
            raise ValueError("reservation set IDs must be sorted and unique")
        for reservation_fingerprint in self.reservation_fingerprints:
            _sha256("reservation", reservation_fingerprint)
        for name, amount in (
            ("reservation-set cash", self.cash),
            ("reservation-set gross exposure", self.gross_exposure),
            ("reservation-set order notional", self.order_notional),
        ):
            if not amount.is_finite() or amount < 0:
                raise ValueError(f"{name} must be finite and nonnegative")

    @property
    def reservation_count(self) -> int:
        return len(self.reservation_ids)

    @property
    def set_fingerprint(self) -> str:
        return fingerprint(self)


class RiskStore(ExecutionStore):
    """Extend the execution database with persistent fail-closed emergency state."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS emergency_state (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    disabled INTEGER NOT NULL CHECK (disabled IN (0, 1)),
                    generation INTEGER NOT NULL CHECK (generation > 0),
                    reason TEXT NOT NULL,
                    operator TEXT NOT NULL,
                    changed_at TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL REFERENCES journal(sequence)
                )
                """
            )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_authorizations (
                    authorization_id TEXT PRIMARY KEY,
                    authorization_fingerprint TEXT NOT NULL UNIQUE,
                    authorization_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS paper_authorizations_no_update
                BEFORE UPDATE ON paper_authorizations BEGIN
                    SELECT RAISE(ABORT, 'paper authorizations are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS paper_authorizations_no_delete
                BEFORE DELETE ON paper_authorizations BEGIN
                    SELECT RAISE(ABORT, 'paper authorizations are immutable');
                END;
                CREATE TABLE IF NOT EXISTS risk_decisions (
                    decision_id TEXT PRIMARY KEY,
                    intent_id TEXT NOT NULL REFERENCES intents(idempotency_key),
                    authorization_id TEXT NOT NULL
                        REFERENCES paper_authorizations(authorization_id),
                    decision_json TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS risk_decisions_no_update
                BEFORE UPDATE ON risk_decisions BEGIN
                    SELECT RAISE(ABORT, 'risk decisions are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS risk_decisions_no_delete
                BEFORE DELETE ON risk_decisions BEGIN
                    SELECT RAISE(ABORT, 'risk decisions are immutable');
                END;
                CREATE TABLE IF NOT EXISTS capacity_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    decision_id TEXT NOT NULL UNIQUE REFERENCES risk_decisions(decision_id),
                    intent_id TEXT NOT NULL REFERENCES intents(idempotency_key),
                    authorization_id TEXT NOT NULL
                        REFERENCES paper_authorizations(authorization_id),
                    reservation_json TEXT NOT NULL,
                    reserved_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS capacity_reservations_no_update
                BEFORE UPDATE ON capacity_reservations BEGIN
                    SELECT RAISE(ABORT, 'capacity reservations are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS capacity_reservations_no_delete
                BEFORE DELETE ON capacity_reservations BEGIN
                    SELECT RAISE(ABORT, 'capacity reservations are immutable');
                END;
                CREATE TABLE IF NOT EXISTS capacity_releases (
                    reservation_id TEXT PRIMARY KEY
                        REFERENCES capacity_reservations(reservation_id),
                    reason TEXT NOT NULL,
                    released_at TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS capacity_releases_no_update
                BEFORE UPDATE ON capacity_releases BEGIN
                    SELECT RAISE(ABORT, 'capacity releases are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS capacity_releases_no_delete
                BEFORE DELETE ON capacity_releases BEGIN
                    SELECT RAISE(ABORT, 'capacity releases are immutable');
                END;
                """
            )
            connection.commit()
            connection.execute("BEGIN IMMEDIATE")
            self._verify_connection(connection)
            row = connection.execute("SELECT 1 FROM emergency_state WHERE singleton = 1").fetchone()
            if row is None:
                prior = connection.execute(
                    "SELECT 1 FROM journal WHERE entity_type = 'emergency-state' LIMIT 1"
                ).fetchone()
                if prior is not None:
                    raise JournalIntegrityError("emergency state is missing")
                changed_at = datetime.now(UTC)
                payload = {
                    "disabled": True,
                    "generation": 1,
                    "reason": "paper execution is not enabled",
                    "operator": "system",
                }
                sequence = self._append_event(
                    connection,
                    occurred_at=changed_at,
                    event_type="emergency-initialized",
                    entity_type="emergency-state",
                    entity_id="global",
                    payload=payload,
                )
                connection.execute(
                    "INSERT INTO emergency_state VALUES (1, 1, 1, ?, ?, ?, ?)",
                    (payload["reason"], payload["operator"], _utc_text(changed_at), sequence),
                )
            connection.commit()
            self._verify_emergency(connection)
            self._verify_authorizations(connection)
            self._verify_decisions(connection)
            self._verify_reservations(connection)
            self._verify_releases(connection)

    def authorize_paper(
        self,
        authorization: PaperAuthorization,
        evidence_report: dict[str, object],
        limits: RiskLimits,
    ) -> PaperAuthorization:
        report = validate_passing_qualification_evidence(evidence_report)
        expected = {
            **_evidence_bindings(report),
            "account_id": limits.account_id,
            "risk_configuration_fingerprint": limits.configuration_fingerprint,
        }
        if any(getattr(authorization, key) != value for key, value in expected.items()):
            raise HoldoutAccessError("paper authorization differs from qualification or limits")
        if (
            authorization.authorized_at < limits.effective_at
            or authorization.authorized_at >= limits.expires_at
            or authorization.expires_at > limits.expires_at
        ):
            raise HoldoutAccessError("paper authorization is outside the risk configuration period")
        authorization_json = canonical_json(authorization)
        evidence_json = canonical_json(report)
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_connection(connection)
                self._verify_emergency(connection)
                self._verify_authorizations(connection)
                row = connection.execute(
                    """
                    SELECT authorization_json, evidence_json FROM paper_authorizations
                    WHERE authorization_id = ?
                    """,
                    (authorization.authorization_id,),
                ).fetchone()
                if row is not None:
                    if row != (authorization_json, evidence_json):
                        raise HoldoutAccessError("authorization ID is bound to different content")
                    connection.commit()
                    return authorization
                sequence = self._append_event(
                    connection,
                    occurred_at=authorization.authorized_at,
                    event_type="paper-authorized",
                    entity_type="paper-authorization",
                    entity_id=authorization.authorization_id,
                    payload=canonicalize(authorization),
                )
                connection.execute(
                    "INSERT INTO paper_authorizations VALUES (?, ?, ?, ?, ?)",
                    (
                        authorization.authorization_id,
                        authorization.authorization_fingerprint,
                        authorization_json,
                        evidence_json,
                        sequence,
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise HoldoutAccessError("paper authorization already exists") from error
            except Exception:
                connection.rollback()
                raise
        return authorization

    def get_paper_authorization(self, authorization_id: str) -> PaperAuthorization:
        _text("authorization ID", authorization_id)
        with self._connect() as connection:
            connection.execute("BEGIN")
            self._verify_connection(connection)
            self._verify_emergency(connection)
            authorizations = self._verify_authorizations(connection)
        try:
            return authorizations[authorization_id]
        except KeyError:
            raise KeyError(authorization_id) from None

    def record_risk_decision(
        self,
        intent_id: str,
        authorization_id: str,
        limits: RiskLimits,
        context: RiskContext,
    ) -> RiskDecisionReceipt:
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_connection(connection)
                emergency = self._verify_emergency(connection)
                authorizations = self._verify_authorizations(connection)
                self._verify_decisions(connection)
                self._verify_reservations(connection)
                self._verify_releases(connection)
                try:
                    authorization = authorizations[authorization_id]
                except KeyError:
                    raise HoldoutAccessError("paper authorization not found") from None
                intent = self._read_intent(connection, intent_id)
                if (
                    authorization.strategy_id != intent.strategy_id
                    or authorization.strategy_version != intent.strategy_version
                    or authorization.parameters_fingerprint != intent.configuration_fingerprint
                    or authorization.dataset_fingerprint != intent.source_data_fingerprint
                    or authorization.account_id != context.account_id
                    or authorization.risk_configuration_fingerprint
                    != limits.configuration_fingerprint
                    or context.evaluated_at < authorization.authorized_at
                    or context.evaluated_at >= authorization.expires_at
                ):
                    raise HoldoutAccessError(
                        "intent, context, limits, or time differs from paper authorization"
                    )
                reservation_set = self._active_reservation_set(
                    connection,
                    account_id=context.account_id,
                    at=context.evaluated_at,
                    exclude_intent_id=intent_id,
                )
                bound_context = replace(
                    context,
                    emergency_disabled=emergency.disabled,
                    active_reservation_set_fingerprint=reservation_set.set_fingerprint,
                    pending_buy_notional=reservation_set.cash,
                    pending_order_notional=reservation_set.order_notional,
                    pending_order_count=reservation_set.reservation_count,
                )
                decision = evaluate_risk(intent, limits, bound_context)
                decision_id = fingerprint(
                    {
                        "intent": intent.intent_fingerprint,
                        "authorization": authorization.authorization_fingerprint,
                        "decision": decision,
                    }
                )
                existing = connection.execute(
                    """
                    SELECT intent_id, authorization_id, decision_json, decided_at,
                           journal_sequence
                    FROM risk_decisions WHERE decision_id = ?
                    """,
                    (decision_id,),
                ).fetchone()
                if existing is not None:
                    receipt = _decision_receipt(decision_id, existing)
                    connection.commit()
                    return receipt
                payload = {
                    "decision_id": decision_id,
                    "intent_id": intent_id,
                    "authorization_id": authorization_id,
                    "decision": canonicalize(decision),
                }
                sequence = self._append_event(
                    connection,
                    occurred_at=decision.decided_at,
                    event_type="risk-decided",
                    entity_type="risk-decision",
                    entity_id=decision_id,
                    payload=payload,
                )
                decision_json = canonical_json(decision)
                connection.execute(
                    "INSERT INTO risk_decisions VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        decision_id,
                        intent_id,
                        authorization_id,
                        decision_json,
                        _utc_text(decision.decided_at),
                        sequence,
                    ),
                )
                if decision.approved:
                    reservation = CapacityReservation(
                        reservation_id=fingerprint({"decision_id": decision_id}),
                        decision_id=decision_id,
                        intent_id=intent_id,
                        authorization_id=authorization_id,
                        account_id=context.account_id,
                        configuration_fingerprint=limits.configuration_fingerprint,
                        cash=decision.cash_reservation,
                        gross_exposure=decision.gross_exposure_reservation,
                        order_notional=decision.order_notional,
                        reserved_at=decision.decided_at,
                        expires_at=min(
                            intent.expires_at, authorization.expires_at, limits.expires_at
                        ),
                    )
                    reservation_sequence = self._append_event(
                        connection,
                        occurred_at=reservation.reserved_at,
                        event_type="capacity-reserved",
                        entity_type="capacity-reservation",
                        entity_id=reservation.reservation_id,
                        payload=canonicalize(reservation),
                    )
                    connection.execute(
                        "INSERT INTO capacity_reservations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            reservation.reservation_id,
                            reservation.decision_id,
                            reservation.intent_id,
                            reservation.authorization_id,
                            canonical_json(reservation),
                            _utc_text(reservation.reserved_at),
                            _utc_text(reservation.expires_at),
                            reservation_sequence,
                        ),
                    )
                connection.commit()
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise HoldoutAccessError("risk decision or reservation already exists") from error
            except Exception:
                connection.rollback()
                raise
        return RiskDecisionReceipt(
            decision_id,
            intent_id,
            authorization_id,
            decision.approved,
            decision.reasons,
            decision.decided_at,
            sequence,
        )

    def get_emergency(self) -> EmergencyState:
        with self._connect() as connection:
            connection.execute("BEGIN")
            self._verify_connection(connection)
            return self._verify_emergency(connection)

    def _verify_emergency(self, connection: sqlite3.Connection) -> EmergencyState:
        row = connection.execute(
            """
            SELECT disabled, generation, reason, operator, changed_at, journal_sequence
            FROM emergency_state WHERE singleton = 1
            """
        ).fetchone()
        if row is None:
            raise JournalIntegrityError("emergency state is missing")
        event = connection.execute(
            """
            SELECT occurred_at, event_type, entity_type, entity_id, payload_json
            FROM journal WHERE sequence = ?
            """,
            (row[5],),
        ).fetchone()
        payload = {
            "disabled": bool(row[0]),
            "generation": int(row[1]),
            "reason": str(row[2]),
            "operator": str(row[3]),
        }
        try:
            event_payload = json.loads(event[4]) if event is not None else None
        except json.JSONDecodeError:
            event_payload = None
        if (
            event is None
            or event[0] != row[4]
            or event[2] != "emergency-state"
            or event[3] != "global"
            or event[1] not in {"emergency-initialized", "emergency-cleared", "emergency-disabled"}
            or not isinstance(event_payload, dict)
            or any(event_payload.get(key) != value for key, value in payload.items())
        ):
            raise JournalIntegrityError("emergency state does not match its journal event")
        if event[1] == "emergency-initialized" and (
            not payload["disabled"] or payload["generation"] != 1
        ):
            raise JournalIntegrityError("emergency initialization is invalid")
        if event[1] == "emergency-cleared" and payload["disabled"]:
            raise JournalIntegrityError("emergency clear state is invalid")
        if event[1] == "emergency-disabled" and not payload["disabled"]:
            raise JournalIntegrityError("emergency disable state is invalid")
        if event[1] in {"emergency-cleared", "emergency-disabled"} and not isinstance(
            event_payload.get("cause_fingerprint"), str
        ):
            raise JournalIntegrityError("emergency transition proof is missing")
        if event[1] in {"emergency-cleared", "emergency-disabled"}:
            try:
                _sha256("emergency transition cause", event_payload["cause_fingerprint"])
            except (KeyError, ValueError) as error:
                raise JournalIntegrityError("emergency transition proof is invalid") from error
        return EmergencyState(
            disabled=bool(row[0]),
            generation=int(row[1]),
            reason=str(row[2]),
            operator=str(row[3]),
            changed_at=_parse_utc(str(row[4])),
            journal_sequence=int(row[5]),
        )

    def _verify_authorizations(
        self, connection: sqlite3.Connection
    ) -> dict[str, PaperAuthorization]:
        rows = connection.execute(
            """
            SELECT authorization_id, authorization_fingerprint, authorization_json,
                   evidence_json, journal_sequence
            FROM paper_authorizations
            """
        ).fetchall()
        event_count = connection.execute(
            "SELECT COUNT(*) FROM journal WHERE event_type = 'paper-authorized'"
        ).fetchone()[0]
        if len(rows) != event_count:
            raise JournalIntegrityError("paper authorization and journal counts differ")
        result: dict[str, PaperAuthorization] = {}
        for row in rows:
            try:
                value: Any = json.loads(row[2])
                evidence: Any = json.loads(row[3])
                authorization = _decode_authorization(value)
                validated_evidence = validate_passing_qualification_evidence(evidence)
            except (ValueError, HoldoutAccessError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("stored paper authorization is invalid") from error
            event = connection.execute(
                """
                SELECT occurred_at, event_type, entity_type, entity_id, payload_json
                FROM journal WHERE sequence = ?
                """,
                (row[4],),
            ).fetchone()
            if (
                row[0] != authorization.authorization_id
                or row[1] != authorization.authorization_fingerprint
                or row[2] != canonical_json(authorization)
                or row[3] != canonical_json(validated_evidence)
                or any(
                    getattr(authorization, key) != value
                    for key, value in _evidence_bindings(validated_evidence).items()
                )
                or event
                != (
                    _utc_text(authorization.authorized_at),
                    "paper-authorized",
                    "paper-authorization",
                    authorization.authorization_id,
                    canonical_json(authorization),
                )
            ):
                raise JournalIntegrityError("paper authorization does not match its journal event")
            result[authorization.authorization_id] = authorization
        return result

    def _active_reservation_set(
        self,
        connection: sqlite3.Connection,
        *,
        account_id: str,
        at: datetime,
        exclude_intent_id: str | None = None,
    ) -> ActiveReservationSet:
        rows = connection.execute(
            """
            SELECT r.reservation_json FROM capacity_reservations r
            LEFT JOIN capacity_releases x ON x.reservation_id = r.reservation_id
            WHERE json_extract(r.reservation_json, '$.account_id') = ?
              AND r.expires_at > ?
              AND r.reserved_at <= ?
              AND (x.reservation_id IS NULL OR x.released_at > ?)
              AND (? IS NULL OR r.intent_id != ?)
            """,
            (
                account_id,
                _utc_text(at),
                _utc_text(at),
                _utc_text(at),
                exclude_intent_id,
                exclude_intent_id,
            ),
        ).fetchall()
        reservations = [_decode_reservation(json.loads(row[0])) for row in rows]
        reservations.sort(key=lambda item: item.reservation_id)
        return ActiveReservationSet(
            account_id=account_id,
            evaluated_at=at,
            reservation_ids=tuple(item.reservation_id for item in reservations),
            reservation_fingerprints=tuple(item.reservation_fingerprint for item in reservations),
            cash=sum((item.cash for item in reservations), Decimal("0")),
            gross_exposure=sum((item.gross_exposure for item in reservations), Decimal("0")),
            order_notional=sum((item.order_notional for item in reservations), Decimal("0")),
        )

    def _verify_reservations(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT reservation_id, decision_id, intent_id, authorization_id,
                   reservation_json, reserved_at, expires_at, journal_sequence
            FROM capacity_reservations
            """
        ).fetchall()
        event_count = connection.execute(
            "SELECT COUNT(*) FROM journal WHERE event_type = 'capacity-reserved'"
        ).fetchone()[0]
        if len(rows) != event_count:
            raise JournalIntegrityError("capacity reservation and journal counts differ")
        for row in rows:
            try:
                reservation = _decode_reservation(json.loads(row[4]))
            except (ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("stored capacity reservation is invalid") from error
            payload = canonical_json(reservation)
            event = connection.execute(
                """
                SELECT occurred_at, event_type, entity_type, entity_id, payload_json
                FROM journal WHERE sequence = ?
                """,
                (row[7],),
            ).fetchone()
            if (
                row[0] != reservation.reservation_id
                or row[1] != reservation.decision_id
                or row[2] != reservation.intent_id
                or row[3] != reservation.authorization_id
                or row[4] != payload
                or row[5] != _utc_text(reservation.reserved_at)
                or row[6] != _utc_text(reservation.expires_at)
                or event
                != (
                    row[5],
                    "capacity-reserved",
                    "capacity-reservation",
                    row[0],
                    payload,
                )
            ):
                raise JournalIntegrityError("capacity reservation does not match its journal event")
            decision_row = connection.execute(
                "SELECT decision_json FROM risk_decisions WHERE decision_id = ?",
                (reservation.decision_id,),
            ).fetchone()
            if decision_row is None or not _decode_decision(json.loads(decision_row[0])).approved:
                raise JournalIntegrityError("capacity reservation lacks approved risk decision")

    def _release_capacity(
        self,
        connection: sqlite3.Connection,
        *,
        reservation_id: str,
        reason: str,
        released_at: datetime,
    ) -> None:
        existing = connection.execute(
            "SELECT reason, released_at FROM capacity_releases WHERE reservation_id = ?",
            (reservation_id,),
        ).fetchone()
        if existing is not None:
            if existing != (reason, _utc_text(released_at)):
                raise JournalIntegrityError("capacity release differs from existing content")
            return
        payload = {
            "reservation_id": reservation_id,
            "reason": reason,
            "released_at": released_at,
        }
        sequence = self._append_event(
            connection,
            occurred_at=released_at,
            event_type="capacity-released",
            entity_type="capacity-reservation",
            entity_id=reservation_id,
            payload=canonicalize(payload),
        )
        connection.execute(
            "INSERT INTO capacity_releases VALUES (?, ?, ?, ?)",
            (reservation_id, reason, _utc_text(released_at), sequence),
        )

    def _verify_releases(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT reservation_id, reason, released_at, journal_sequence FROM capacity_releases"
        ).fetchall()
        count = connection.execute(
            "SELECT COUNT(*) FROM journal WHERE event_type = 'capacity-released'"
        ).fetchone()[0]
        if len(rows) != count:
            raise JournalIntegrityError("capacity release and journal counts differ")
        for row in rows:
            reservation = connection.execute(
                "SELECT reserved_at FROM capacity_reservations WHERE reservation_id = ?",
                (row[0],),
            ).fetchone()
            payload = {
                "reservation_id": row[0],
                "reason": row[1],
                "released_at": _parse_utc(row[2]),
            }
            event = connection.execute(
                "SELECT occurred_at, event_type, entity_type, entity_id, payload_json "
                "FROM journal WHERE sequence = ?",
                (row[3],),
            ).fetchone()
            broker_events_exist = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'broker_events'"
            ).fetchone()
            filled_order = (
                None
                if broker_events_exist is None
                else connection.execute(
                    "SELECT 1 FROM broker_events b JOIN orders o "
                    "ON o.order_id = b.client_order_id WHERE o.reservation_id = ? "
                    "AND CAST(json_extract(b.event_json, '$.cumulative_filled_quantity') "
                    "AS INTEGER) > 0 LIMIT 1",
                    (row[0],),
                ).fetchone()
            )
            if (
                reservation is None
                or _parse_utc(row[2]) < _parse_utc(reservation[0])
                or (row[1] in {"order-canceled", "order-rejected"} and filled_order is not None)
                or event
                != (
                    row[2],
                    "capacity-released",
                    "capacity-reservation",
                    row[0],
                    canonical_json(payload),
                )
            ):
                raise JournalIntegrityError("capacity release does not match its reservation")

    def _verify_decisions(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT decision_id, intent_id, authorization_id, decision_json, decided_at,
                   journal_sequence
            FROM risk_decisions
            """
        ).fetchall()
        event_count = connection.execute(
            "SELECT COUNT(*) FROM journal WHERE event_type = 'risk-decided'"
        ).fetchone()[0]
        if len(rows) != event_count:
            raise JournalIntegrityError("risk decision and journal counts differ")
        for row in rows:
            try:
                decision = _decode_decision(json.loads(row[3]))
            except (ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("stored risk decision is invalid") from error
            payload = {
                "decision_id": row[0],
                "intent_id": row[1],
                "authorization_id": row[2],
                "decision": canonicalize(decision),
            }
            event = connection.execute(
                """
                SELECT occurred_at, event_type, entity_type, entity_id, payload_json
                FROM journal WHERE sequence = ?
                """,
                (row[5],),
            ).fetchone()
            references = connection.execute(
                """
                SELECT i.intent_fingerprint, a.authorization_fingerprint,
                       a.authorization_json
                FROM intents i, paper_authorizations a
                WHERE i.idempotency_key = ? AND a.authorization_id = ?
                """,
                (row[1], row[2]),
            ).fetchone()
            try:
                authorization = (
                    None if references is None else _decode_authorization(json.loads(references[2]))
                )
            except (ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("risk decision authorization is invalid") from error
            expected_id = (
                None
                if references is None
                else fingerprint(
                    {
                        "intent": references[0],
                        "authorization": references[1],
                        "decision": decision,
                    }
                )
            )
            if (
                row[0] != expected_id
                or authorization is None
                or decision.intent_fingerprint != references[0]
                or decision.configuration_fingerprint
                != authorization.risk_configuration_fingerprint
                or row[3] != canonical_json(decision)
                or row[4] != _utc_text(decision.decided_at)
                or event
                != (
                    row[4],
                    "risk-decided",
                    "risk-decision",
                    row[0],
                    canonical_json(payload),
                )
                or (
                    decision.approved
                    and connection.execute(
                        "SELECT 1 FROM capacity_reservations WHERE decision_id = ?",
                        (row[0],),
                    ).fetchone()
                    is None
                )
            ):
                raise JournalIntegrityError("risk decision does not match its journal event")


def _text(name: str, value: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{name} must be nonempty and trimmed")


def _positive_decimal(name: str, value: Decimal) -> None:
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


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


def _decode_authorization(value: Any) -> PaperAuthorization:
    if not isinstance(value, dict):
        raise ValueError("paper authorization must be an object")
    try:
        return PaperAuthorization(
            **{
                **value,
                "authorized_at": _parse_utc(value["authorized_at"]),
                "expires_at": _parse_utc(value["expires_at"]),
            }
        )
    except (KeyError, TypeError) as error:
        raise ValueError("paper authorization fields differ") from error


def _evidence_bindings(report: dict[str, object]) -> dict[str, object]:
    candidate = report["candidate_specification"]
    assert isinstance(candidate, dict)
    return {
        "candidate_id": report["candidate_id"],
        "strategy_id": candidate["strategy_id"],
        "strategy_version": candidate["strategy_version"],
        "parameters_fingerprint": fingerprint(candidate["parameters"]),
        "code_commit": candidate["code_commit"],
        "dataset_id": candidate["dataset_id"],
        "dataset_fingerprint": candidate["dataset_fingerprint"],
        "universe_id": candidate["universe_id"],
        "universe_fingerprint": candidate["universe_fingerprint"],
        "qualification_evidence_fingerprint": report["evidence_fingerprint"],
    }


def _decode_decision(value: Any) -> RiskDecision:
    fields = {
        "approved",
        "reasons",
        "intent_fingerprint",
        "configuration_fingerprint",
        "context_fingerprint",
        "decided_at",
        "order_notional",
        "cash_reservation",
        "gross_exposure_reservation",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("risk decision fields differ")
    reasons = value["reasons"]
    if not isinstance(reasons, list) or any(not isinstance(item, str) for item in reasons):
        raise ValueError("risk decision reasons are invalid")
    try:
        return RiskDecision(
            approved=value["approved"],
            reasons=tuple(reasons),
            intent_fingerprint=value["intent_fingerprint"],
            configuration_fingerprint=value["configuration_fingerprint"],
            context_fingerprint=value["context_fingerprint"],
            decided_at=_parse_utc(value["decided_at"]),
            order_notional=Decimal(value["order_notional"]),
            cash_reservation=Decimal(value["cash_reservation"]),
            gross_exposure_reservation=Decimal(value["gross_exposure_reservation"]),
        )
    except (KeyError, TypeError, ArithmeticError) as error:
        raise ValueError("risk decision value is invalid") from error


def _decode_reservation(value: Any) -> CapacityReservation:
    if not isinstance(value, dict):
        raise ValueError("capacity reservation must be an object")
    try:
        return CapacityReservation(
            reservation_id=value["reservation_id"],
            decision_id=value["decision_id"],
            intent_id=value["intent_id"],
            authorization_id=value["authorization_id"],
            account_id=value["account_id"],
            configuration_fingerprint=value["configuration_fingerprint"],
            cash=Decimal(value["cash"]),
            gross_exposure=Decimal(value["gross_exposure"]),
            order_notional=Decimal(value["order_notional"]),
            reserved_at=_parse_utc(value["reserved_at"]),
            expires_at=_parse_utc(value["expires_at"]),
        )
    except (KeyError, TypeError, ArithmeticError) as error:
        raise ValueError("capacity reservation value is invalid") from error


def _decision_receipt(decision_id: str, row: tuple[Any, ...]) -> RiskDecisionReceipt:
    decision = _decode_decision(json.loads(row[2]))
    return RiskDecisionReceipt(
        decision_id=decision_id,
        intent_id=str(row[0]),
        authorization_id=str(row[1]),
        approved=decision.approved,
        reasons=decision.reasons,
        decided_at=_parse_utc(str(row[3])),
        journal_sequence=int(row[4]),
    )


def _sha256(name: str, value: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} fingerprint must be a lowercase SHA-256 value")
