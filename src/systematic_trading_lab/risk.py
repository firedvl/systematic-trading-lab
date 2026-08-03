"""Independent broker-free risk evaluation and emergency state."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
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
    min_cash: Decimal
    max_open_orders: int
    max_orders_per_minute: int
    max_daily_loss: Decimal
    max_strategy_drawdown: Decimal
    max_price_deviation_bps: Decimal
    max_snapshot_age_seconds: int
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
            ("maximum daily loss", self.max_daily_loss),
            ("maximum strategy drawdown", self.max_strategy_drawdown),
            ("maximum price deviation", self.max_price_deviation_bps),
        ):
            _positive_decimal(decimal_name, decimal_value)
        if not self.min_cash.is_finite() or self.min_cash < 0:
            raise ValueError("minimum cash must be finite and nonnegative")
        if self.max_strategy_drawdown > 1:
            raise ValueError("maximum strategy drawdown cannot exceed one")
        if self.max_open_orders < 1 or self.max_orders_per_minute < 1:
            raise ValueError("order limits must be positive")
        if self.max_snapshot_age_seconds < 1:
            raise ValueError("snapshot maximum age must be positive")
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
    pending_buy_notional: Decimal
    pending_order_notional: Decimal
    open_order_count: int
    pending_order_count: int
    orders_last_minute: int
    daily_pnl: Decimal
    strategy_drawdown: Decimal
    quote_price: Decimal
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
        if self.current_symbol_notional > self.current_gross_exposure:
            raise ValueError("symbol notional cannot exceed gross exposure")
        _positive_decimal("quote price", self.quote_price)
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
    deviation_bps = (
        abs(context.quote_price - intent.reference_price) / intent.reference_price * Decimal(10_000)
    )
    if deviation_bps > limits.max_price_deviation_bps:
        reasons.append("price-deviation-limit")

    target_notional = (
        context.equity * intent.target_weight
        if intent.target_weight is not None
        else context.quote_price * Decimal(intent.target_quantity or 0)
    )
    order_notional = abs(target_notional - context.current_symbol_notional)
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
        for name, value in (
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
            _text(name, value)
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
        if (
            event is None
            or event[0] != row[4]
            or event[1:]
            != (
                "emergency-initialized",
                "emergency-state",
                "global",
                canonical_json(payload),
            )
        ):
            raise JournalIntegrityError("emergency state does not match its journal event")
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


def _sha256(name: str, value: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} fingerprint must be a lowercase SHA-256 value")
