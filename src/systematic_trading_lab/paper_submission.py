"""Transaction-bound paper submission preflight without broker I/O."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from http.client import HTTPException
from pathlib import Path
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request

from .alpaca_paper import (
    PAPER_ORIGIN,
    AlpacaPaperError,
    _lookup_status,
    _optional_amount,
    _supported_order_envelope,
    _text,
    _timestamp,
    _whole_shares,
)
from .broker_events import BrokerEventStore, BrokerOrderEvent
from .config import PaperWriteRequest
from .domain import TradingMode
from .execution import JournalIntegrityError
from .fingerprints import canonical_json, canonicalize, fingerprint
from .orders import OrderDelta, OrderState, _decode_delta, build_order_delta
from .paper_activation import _assess_paper_write, _verify_paper_write_binding
from .risk import RiskLimits, evaluate_risk
from .risk_context import AttestedRiskContextStore
from .runtime_build import InstalledRuntimeIdentity


@dataclass(frozen=True)
class PaperSubmissionPreflight:
    order_id: str
    reservation_id: str
    decision_id: str
    authorization_id: str
    intent_fingerprint: str
    order_delta_fingerprint: str
    risk_limits_fingerprint: str
    attested_context_proof_fingerprint: str
    reevaluated_risk_fingerprint: str
    submitter_id: str
    paper_origin: str
    claimed_at: datetime
    activation_id: str | None = None
    paper_write_request_fingerprint: str | None = None
    runtime_identity_fingerprint: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("order ID", self.order_id),
            ("reservation ID", self.reservation_id),
            ("decision ID", self.decision_id),
            ("authorization ID", self.authorization_id),
            ("submitter ID", self.submitter_id),
        ):
            if not value or value != value.strip() or len(value) > 128:
                raise ValueError(f"{name} is invalid")
        for name, value in (
            ("intent", self.intent_fingerprint),
            ("order delta", self.order_delta_fingerprint),
            ("risk limits", self.risk_limits_fingerprint),
            ("attested context", self.attested_context_proof_fingerprint),
            ("reevaluated risk", self.reevaluated_risk_fingerprint),
        ):
            _sha256(name, value)
        if self.paper_origin != PAPER_ORIGIN:
            raise ValueError("paper submission origin is invalid")
        if (self.activation_id is None) != (self.paper_write_request_fingerprint is None):
            raise ValueError("paper submission activation binding is incomplete")
        if self.activation_id is not None:
            assert self.paper_write_request_fingerprint is not None
            _sha256("activation", self.activation_id)
            _sha256("paper write request", self.paper_write_request_fingerprint)
        if self.runtime_identity_fingerprint is not None:
            if self.activation_id is None:
                raise ValueError("paper submission runtime identity lacks activation")
            _sha256("runtime identity", self.runtime_identity_fingerprint)
        _utc(self.claimed_at)

    @property
    def proof_fingerprint(self) -> str:
        return fingerprint(_preflight_value(self))


class PaperSubmissionPreflightStore(AttestedRiskContextStore):
    """Atomically recheck protected controls and claim one fake-adapter submission."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_submission_preflights (
                    order_id TEXT PRIMARY KEY REFERENCES orders(order_id),
                    proof_fingerprint TEXT NOT NULL UNIQUE,
                    proof_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS paper_submission_preflights_no_update
                BEFORE UPDATE ON paper_submission_preflights BEGIN
                    SELECT RAISE(ABORT, 'paper submission preflights are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS paper_submission_preflights_no_delete
                BEFORE DELETE ON paper_submission_preflights BEGIN
                    SELECT RAISE(ABORT, 'paper submission preflights are immutable');
                END;
                """
            )
            connection.commit()
            self._verify_preflights(connection)

    def claim(
        self,
        order_id: str,
        *,
        submitter_id: str,
        authorization_id: str,
        limits: RiskLimits,
        mode: TradingMode,
        paper_origin: str,
        claimed_at: datetime,
        paper_write_request: PaperWriteRequest | None = None,
        runtime_identity: InstalledRuntimeIdentity | None = None,
    ) -> PaperSubmissionPreflight:
        result, _ = self._claim_once(
            order_id,
            submitter_id=submitter_id,
            authorization_id=authorization_id,
            limits=limits,
            mode=mode,
            paper_origin=paper_origin,
            claimed_at=claimed_at,
            paper_write_request=paper_write_request,
            runtime_identity=runtime_identity,
        )
        return result

    def _claim_once(
        self,
        order_id: str,
        *,
        submitter_id: str,
        authorization_id: str,
        limits: RiskLimits,
        mode: TradingMode,
        paper_origin: str,
        claimed_at: datetime,
        paper_write_request: PaperWriteRequest | None = None,
        runtime_identity: InstalledRuntimeIdentity | None = None,
    ) -> tuple[PaperSubmissionPreflight, bool]:
        if mode is not TradingMode.PAPER or paper_origin != PAPER_ORIGIN:
            raise PermissionError("paper submission requires paper mode and the fixed paper origin")
        if (paper_write_request is None) != (runtime_identity is None):
            raise ValueError("paper submission activation requires runtime identity")
        _utc(claimed_at)
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_connection(connection)
                self._verify_reservations(connection)
                self._verify_releases(connection)
                self._verify_orders(connection)
                self._verify_decisions(connection)
                self._verify_authorizations(connection)
                existing = self._verify_preflights(connection).get(order_id)
                if existing is not None:
                    if (
                        existing.submitter_id != submitter_id
                        or existing.authorization_id != authorization_id
                        or existing.risk_limits_fingerprint != limits.configuration_fingerprint
                        or existing.paper_origin != paper_origin
                        or existing.claimed_at != claimed_at
                        or existing.activation_id
                        != (
                            None
                            if paper_write_request is None
                            else paper_write_request.activation_id
                        )
                        or existing.paper_write_request_fingerprint
                        != (
                            None
                            if paper_write_request is None
                            else paper_write_request.request_fingerprint
                        )
                        or existing.runtime_identity_fingerprint
                        != (
                            None
                            if runtime_identity is None
                            else runtime_identity.identity_fingerprint
                        )
                    ):
                        raise JournalIntegrityError(
                            "order is bound to a different paper submission preflight"
                        )
                    connection.commit()
                    return existing, False
                row = connection.execute(
                    "SELECT o.reservation_id, o.delta_json, o.state, r.decision_id, "
                    "r.intent_id, r.authorization_id, r.reservation_json, d.decision_json "
                    "FROM orders o JOIN capacity_reservations r "
                    "ON r.reservation_id = o.reservation_id JOIN risk_decisions d "
                    "ON d.decision_id = r.decision_id WHERE o.order_id = ?",
                    (order_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(order_id)
                delta = _decode_delta(json.loads(row[1]))
                intent = self._read_intent(connection, str(row[4]))
                if OrderState(row[2]) is not OrderState.STAGED:
                    raise JournalIntegrityError("paper submission requires a staged order")
                if row[5] != authorization_id:
                    raise JournalIntegrityError("paper submission authorization is mismatched")
                if paper_write_request is not None:
                    assessment = _assess_paper_write(
                        self,
                        connection,
                        paper_write_request,
                        limits,
                        operation="submit",
                        assessed_at=claimed_at,
                        authorization_id=authorization_id,
                        runtime_identity=runtime_identity,
                    )
                    if not assessment.eligible:
                        raise PermissionError(
                            "paper submission lacks exact dormant activation authority"
                        )
                if intent.target_quantity is None:
                    raise JournalIntegrityError(
                        "weight-target order submission requires a reviewed share-rounding rule"
                    )
                proof = self._derive(
                    connection,
                    authorization_id=authorization_id,
                    symbol=delta.symbol,
                    limits=limits,
                    evaluated_at=claimed_at,
                    exclude_intent_id=intent.idempotency_key,
                )
                expected = build_order_delta(
                    intent,
                    target_quantity=intent.target_quantity,
                    current_quantity=proof.context.current_symbol_quantity,
                    created_at=delta.created_at,
                )
                current_decision = evaluate_risk(intent, limits, proof.context)
                reservation = json.loads(row[6])
                stored_decision = json.loads(row[7])
                if (
                    expected != delta
                    or not current_decision.approved
                    or stored_decision.get("approved") is not True
                    or not stored_decision.get("context_provenance_fingerprint")
                    or current_decision.order_notional > Decimal(reservation["order_notional"])
                    or current_decision.cash_reservation > Decimal(reservation["cash"])
                    or current_decision.gross_exposure_reservation
                    > Decimal(reservation["gross_exposure"])
                ):
                    raise JournalIntegrityError(
                        "paper submission differs from its current risk authority"
                    )
                result = PaperSubmissionPreflight(
                    order_id=order_id,
                    reservation_id=str(row[0]),
                    decision_id=str(row[3]),
                    authorization_id=authorization_id,
                    intent_fingerprint=intent.intent_fingerprint,
                    order_delta_fingerprint=fingerprint(delta),
                    risk_limits_fingerprint=limits.configuration_fingerprint,
                    attested_context_proof_fingerprint=proof.proof_fingerprint,
                    reevaluated_risk_fingerprint=fingerprint(current_decision),
                    submitter_id=submitter_id,
                    paper_origin=paper_origin,
                    claimed_at=claimed_at,
                    activation_id=(
                        None if paper_write_request is None else paper_write_request.activation_id
                    ),
                    paper_write_request_fingerprint=(
                        None
                        if paper_write_request is None
                        else paper_write_request.request_fingerprint
                    ),
                    runtime_identity_fingerprint=(
                        None if runtime_identity is None else runtime_identity.identity_fingerprint
                    ),
                )
                claimed = self._claim_submitter(
                    connection,
                    order_id,
                    submitter_id,
                    claimed_at,
                    evidence=_preflight_value(result),
                )
                if claimed.state is not OrderState.SUBMITTING:
                    raise JournalIntegrityError("paper submission claim did not enter submitting")
                sequence = connection.execute(
                    "SELECT journal_sequence FROM orders WHERE order_id = ?", (order_id,)
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO paper_submission_preflights VALUES (?, ?, ?, ?)",
                    (
                        order_id,
                        result.proof_fingerprint,
                        canonical_json(_preflight_value(result)),
                        sequence,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return result, True

    def _verify_preflights(
        self, connection: sqlite3.Connection
    ) -> dict[str, PaperSubmissionPreflight]:
        rows = connection.execute(
            "SELECT order_id, proof_fingerprint, proof_json, journal_sequence "
            "FROM paper_submission_preflights"
        ).fetchall()
        result: dict[str, PaperSubmissionPreflight] = {}
        for row in rows:
            try:
                proof = _decode_preflight(json.loads(row[2]))
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError(
                    "stored paper submission preflight is invalid"
                ) from error
            if proof.activation_id is not None:
                assert proof.paper_write_request_fingerprint is not None
                _verify_paper_write_binding(
                    self,
                    connection,
                    activation_id=proof.activation_id,
                    request_fingerprint=proof.paper_write_request_fingerprint,
                    authorization_id=proof.authorization_id,
                    operation="submit",
                    attempted_at=proof.claimed_at,
                    runtime_identity_fingerprint=proof.runtime_identity_fingerprint,
                )
            order = connection.execute(
                "SELECT o.reservation_id, o.delta_json, o.submitter_id, o.claimed_at, "
                "r.decision_id, r.authorization_id, "
                "json_extract(r.reservation_json, '$.configuration_fingerprint'), "
                "i.intent_fingerprint FROM orders o JOIN capacity_reservations r "
                "ON r.reservation_id = o.reservation_id JOIN intents i "
                "ON i.idempotency_key = r.intent_id WHERE o.order_id = ?",
                (proof.order_id,),
            ).fetchone()
            journal = connection.execute(
                "SELECT event_type, entity_type, entity_id, payload_json FROM journal "
                "WHERE sequence = ?",
                (row[3],),
            ).fetchone()
            try:
                payload = json.loads(journal[3]) if journal is not None else None
            except json.JSONDecodeError:
                payload = None
            if (
                row[0] != proof.order_id
                or row[1] != proof.proof_fingerprint
                or row[2] != canonical_json(_preflight_value(proof))
                or order is None
                or order[0] != proof.reservation_id
                or fingerprint(_decode_delta(json.loads(order[1]))) != proof.order_delta_fingerprint
                or order[2:]
                != (
                    proof.submitter_id,
                    _utc_text(proof.claimed_at),
                    proof.decision_id,
                    proof.authorization_id,
                    proof.risk_limits_fingerprint,
                    proof.intent_fingerprint,
                )
                or journal is None
                or journal[:3] != ("order-submitter-claimed", "order", proof.order_id)
                or not isinstance(payload, dict)
                or payload.get("submission_preflight") != _preflight_value(proof)
            ):
                raise JournalIntegrityError(
                    "paper submission preflight differs from its order claim"
                )
            result[proof.order_id] = proof
        return result


class FakePaperSubmissionError(RuntimeError):
    pass


class InjectedAlpacaPaperPost:
    """Normalize one fixed-origin paper order POST through a required test transport."""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        *,
        transport: Callable[[Request], bytes],
        clock: Callable[[], datetime],
    ) -> None:
        if not api_key or not secret_key:
            raise ValueError("Alpaca API credentials are required")
        self._api_key = api_key
        self._secret_key = secret_key
        self._transport = transport
        self._clock = clock

    def __call__(self, delta: OrderDelta, preflight: PaperSubmissionPreflight) -> BrokerOrderEvent:
        if (
            delta.client_order_id != preflight.order_id
            or fingerprint(delta) != preflight.order_delta_fingerprint
            or preflight.paper_origin != PAPER_ORIGIN
        ):
            raise AlpacaPaperError("paper order differs from its submission preflight")
        body = {
            "client_order_id": delta.client_order_id,
            "extended_hours": False,
            "order_class": "simple",
            "qty": str(delta.quantity),
            "side": delta.side.value,
            "symbol": delta.symbol,
            "time_in_force": "day",
            "type": "market",
        }
        request = Request(
            f"{PAPER_ORIGIN}/v2/orders",
            data=canonical_json(body).encode(),
            headers={
                "APCA-API-KEY-ID": self._api_key,
                "APCA-API-SECRET-KEY": self._secret_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        _validate_post(request, body)
        try:
            value = json.loads(self._transport(request))
        except HTTPError as error:
            raise AlpacaPaperError(
                f"Alpaca paper submission failed with HTTP status {error.code}"
            ) from None
        except (
            HTTPException,
            URLError,
            TimeoutError,
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            ValueError,
        ):
            raise AlpacaPaperError("Alpaca paper submission failed") from None
        if not isinstance(value, dict):
            raise AlpacaPaperError("Alpaca paper submission response has an invalid shape")
        status = _lookup_status(value)
        _supported_order_envelope(value)
        filled_quantity = _whole_shares(value, "filled_qty", positive=False)
        filled_average_price = _optional_amount(value, "filled_avg_price")
        if (
            _text(value, "client_order_id", "order") != delta.client_order_id
            or _text(value, "symbol", "order") != delta.symbol
            or _text(value, "side", "order") != delta.side.value
            or _text(value, "type", "order") != delta.order_type
            or _whole_shares(value, "qty", positive=True) != delta.quantity
            or (filled_quantity == 0) != (filled_average_price is None)
        ):
            raise AlpacaPaperError("Alpaca paper submission response differs from the order")
        provider_timestamp = _timestamp(value, "updated_at")
        observed_at = self._now()
        broker_order_id = _text(value, "id", "order")
        event_identity = {
            "broker_order_id": broker_order_id,
            "client_order_id": delta.client_order_id,
            "status": status,
            "filled_quantity": filled_quantity,
            "filled_average_price": filled_average_price,
            "provider_timestamp": provider_timestamp,
            "observed_at": observed_at,
        }
        try:
            return BrokerOrderEvent(
                event_id=f"alpaca-submit-{fingerprint(event_identity)}",
                broker_order_id=broker_order_id,
                client_order_id=delta.client_order_id,
                state={
                    "partially_filled": OrderState.PARTIALLY_FILLED,
                    "filled": OrderState.FILLED,
                    "canceled": OrderState.CANCELED,
                    "expired": OrderState.CANCELED,
                    "rejected": OrderState.REJECTED,
                }.get(status, OrderState.ACKNOWLEDGED),
                cumulative_filled_quantity=filled_quantity,
                cumulative_average_fill_price=filled_average_price,
                provider_timestamp=provider_timestamp,
                observed_at=observed_at,
            )
        except ValueError as error:
            raise AlpacaPaperError("Alpaca paper submission response is invalid") from error

    def _now(self) -> datetime:
        value = self._clock()
        _utc(value)
        return value


class FakePaperSubmitter:
    """Exercise one submission outcome without exposing an HTTP transport."""

    def __init__(
        self,
        path: Path,
        transport: Callable[[OrderDelta, PaperSubmissionPreflight], BrokerOrderEvent],
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._path = path
        self._transport = transport
        self._clock = clock

    def submit(
        self,
        order_id: str,
        *,
        submitter_id: str,
        authorization_id: str,
        limits: RiskLimits,
        claimed_at: datetime,
        baseline_id: str | None = None,
    ) -> BrokerOrderEvent:
        store = PaperSubmissionPreflightStore(self._path)
        preflight, created = store._claim_once(
            order_id,
            submitter_id=submitter_id,
            authorization_id=authorization_id,
            limits=limits,
            mode=TradingMode.PAPER,
            paper_origin=PAPER_ORIGIN,
            claimed_at=claimed_at,
        )
        if not created:
            raise FakePaperSubmissionError(
                "paper submission was already attempted; reconcile before any retry"
            )
        with store._connect() as connection:
            row = connection.execute(
                "SELECT delta_json FROM orders WHERE order_id = ?", (order_id,)
            ).fetchone()
        if row is None:
            raise JournalIntegrityError("paper submission order disappeared after preflight")
        delta = _decode_delta(json.loads(row[0]))
        event: BrokerOrderEvent | None = None
        try:
            event = self._transport(delta, preflight)
            if event.client_order_id != order_id or event.observed_at < claimed_at:
                raise ValueError("fake paper submission returned mismatched evidence")
            return BrokerEventStore(self._path).record(event, baseline_id=baseline_id)
        except Exception as error:
            failed_at = max(
                self._now(), claimed_at, claimed_at if event is None else event.observed_at
            )
            store.transition(order_id, OrderState.SUBMISSION_UNKNOWN, changed_at=failed_at)
            raise FakePaperSubmissionError("fake paper submission outcome is unknown") from error

    def _now(self) -> datetime:
        value = self._clock()
        _utc(value)
        return value


def _decode_preflight(value: object) -> PaperSubmissionPreflight:
    if not isinstance(value, dict):
        raise ValueError("paper submission preflight must be an object")
    try:
        return PaperSubmissionPreflight(
            **{
                **value,
                "activation_id": value.get("activation_id"),
                "paper_write_request_fingerprint": value.get("paper_write_request_fingerprint"),
                "runtime_identity_fingerprint": value.get("runtime_identity_fingerprint"),
                "claimed_at": datetime.fromisoformat(
                    str(value["claimed_at"]).replace("Z", "+00:00")
                ),
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("paper submission preflight is invalid") from error


def _preflight_value(preflight: PaperSubmissionPreflight) -> dict[str, object]:
    value = canonicalize(preflight)
    if not isinstance(value, dict):
        raise TypeError("paper submission preflight must be an object")
    if preflight.activation_id is None:
        value.pop("activation_id")
        value.pop("paper_write_request_fingerprint")
    if preflight.runtime_identity_fingerprint is None:
        value.pop("runtime_identity_fingerprint")
    return value


def _utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("paper submission time must be UTC-aware")


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _sha256(name: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} fingerprint is invalid")


def _validate_post(request: Request, expected_body: dict[str, object]) -> None:
    parsed = urlsplit(request.full_url)
    try:
        body = json.loads(cast(bytes, request.data) or b"")
    except (UnicodeError, json.JSONDecodeError):
        body = None
    if (
        request.get_method() != "POST"
        or parsed.scheme != "https"
        or parsed.netloc != "paper-api.alpaca.markets"
        or parsed.path != "/v2/orders"
        or parsed.query
        or parsed.fragment
        or body != expected_body
    ):
        raise AlpacaPaperError("Alpaca paper submission target is not allowed")
