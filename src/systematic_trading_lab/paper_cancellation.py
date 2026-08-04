"""Durable one-shot paper cancellation attempts without broker I/O."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .alpaca_paper import PAPER_ORIGIN
from .broker_events import BrokerEventStore, BrokerOrderEvent
from .domain import TradingMode
from .execution import JournalIntegrityError
from .fingerprints import canonical_json, canonicalize, fingerprint
from .orders import OrderState


@dataclass(frozen=True)
class OrderCancellationAttempt:
    cancel_id: str
    order_id: str
    authorization_id: str
    broker_event_id: str
    broker_event_fingerprint: str
    order_state: OrderState
    requester: str
    reason: str
    paper_origin: str
    requested_at: datetime

    def __post_init__(self) -> None:
        for name, value, limit in (
            ("cancel ID", self.cancel_id, 64),
            ("order ID", self.order_id, 128),
            ("authorization ID", self.authorization_id, 128),
            ("broker event ID", self.broker_event_id, 128),
            ("requester", self.requester, 128),
            ("reason", self.reason, 500),
        ):
            if not value or value != value.strip() or len(value) > limit:
                raise ValueError(f"{name} is invalid")
        _sha256("cancel", self.cancel_id)
        _sha256("broker event", self.broker_event_fingerprint)
        if self.order_state not in {OrderState.ACKNOWLEDGED, OrderState.PARTIALLY_FILLED}:
            raise ValueError("cancellation requires a nonterminal broker order")
        if self.paper_origin != PAPER_ORIGIN:
            raise ValueError("cancellation paper origin is invalid")
        _utc(self.requested_at)

    @property
    def attempt_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class CancellationUnknownEvidence:
    cancel_id: str
    attempt_fingerprint: str
    broker_event_id: str
    broker_event_fingerprint: str
    observed_at: datetime

    def __post_init__(self) -> None:
        _sha256("cancel", self.cancel_id)
        _sha256("cancellation attempt", self.attempt_fingerprint)
        if not self.broker_event_id or len(self.broker_event_id) > 128:
            raise ValueError("broker event ID is invalid")
        _sha256("broker event", self.broker_event_fingerprint)
        _utc(self.observed_at)

    @property
    def evidence_fingerprint(self) -> str:
        return fingerprint(self)


class PaperCancellationStore(BrokerEventStore):
    """Journal cancel intent and unknown outcome without calling a broker."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS order_cancellation_attempts (
                    cancel_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL UNIQUE REFERENCES orders(order_id),
                    attempt_fingerprint TEXT NOT NULL UNIQUE,
                    attempt_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TABLE IF NOT EXISTS cancellation_unknown_evidence (
                    cancel_id TEXT PRIMARY KEY REFERENCES order_cancellation_attempts(cancel_id),
                    evidence_fingerprint TEXT NOT NULL UNIQUE,
                    evidence_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS order_cancellation_attempts_no_update
                BEFORE UPDATE ON order_cancellation_attempts BEGIN
                    SELECT RAISE(ABORT, 'order cancellation attempts are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS order_cancellation_attempts_no_delete
                BEFORE DELETE ON order_cancellation_attempts BEGIN
                    SELECT RAISE(ABORT, 'order cancellation attempts are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS cancellation_unknown_evidence_no_update
                BEFORE UPDATE ON cancellation_unknown_evidence BEGIN
                    SELECT RAISE(ABORT, 'cancellation unknown evidence is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS cancellation_unknown_evidence_no_delete
                BEFORE DELETE ON cancellation_unknown_evidence BEGIN
                    SELECT RAISE(ABORT, 'cancellation unknown evidence is immutable');
                END;
                """
            )
            connection.commit()
            events = self._verify_broker_events(connection)
            attempts = self._verify_attempts(connection, events)
            self._verify_unknown(connection, events, attempts)

    def request(
        self,
        order_id: str,
        *,
        authorization_id: str,
        requester: str,
        reason: str,
        mode: TradingMode,
        paper_origin: str,
        requested_at: datetime,
    ) -> OrderCancellationAttempt:
        if mode is not TradingMode.PAPER or paper_origin != PAPER_ORIGIN:
            raise PermissionError("cancellation requires paper mode and the fixed paper origin")
        _utc(requested_at)
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_connection(connection)
                self._verify_orders(connection)
                events = self._verify_broker_events(connection)
                attempts = self._verify_attempts(connection, events)
                self._verify_unknown(connection, events, attempts)
                existing = next(
                    (item for item in attempts.values() if item.order_id == order_id), None
                )
                if existing is not None:
                    if (
                        existing.authorization_id != authorization_id
                        or existing.requester != requester
                        or existing.reason != reason
                        or existing.paper_origin != paper_origin
                        or existing.requested_at != requested_at
                    ):
                        raise JournalIntegrityError(
                            "order is bound to a different cancellation attempt"
                        )
                    connection.commit()
                    return existing
                order = connection.execute(
                    "SELECT o.state, o.changed_at, r.authorization_id FROM orders o "
                    "JOIN capacity_reservations r ON r.reservation_id = o.reservation_id "
                    "WHERE o.order_id = ?",
                    (order_id,),
                ).fetchone()
                if order is None:
                    raise KeyError(order_id)
                state = OrderState(order[0])
                latest = _latest_event(events, order_id)
                if (
                    state not in {OrderState.ACKNOWLEDGED, OrderState.PARTIALLY_FILLED}
                    or latest is None
                    or latest.state is not state
                    or order[2] != authorization_id
                    or requested_at < _parse_utc(str(order[1]))
                ):
                    raise JournalIntegrityError("order is not eligible for a cancellation attempt")
                cancel_id = fingerprint(
                    {
                        "order_id": order_id,
                        "broker_event": latest.event_fingerprint,
                        "requester": requester,
                        "reason": reason,
                        "requested_at": requested_at,
                    }
                )
                result = OrderCancellationAttempt(
                    cancel_id=cancel_id,
                    order_id=order_id,
                    authorization_id=authorization_id,
                    broker_event_id=latest.event_id,
                    broker_event_fingerprint=latest.event_fingerprint,
                    order_state=state,
                    requester=requester,
                    reason=reason,
                    paper_origin=paper_origin,
                    requested_at=requested_at,
                )
                sequence = self._append_event(
                    connection,
                    occurred_at=requested_at,
                    event_type="order-cancel-requested",
                    entity_type="order-cancellation-attempt",
                    entity_id=cancel_id,
                    payload=canonicalize(result),
                )
                connection.execute(
                    "INSERT INTO order_cancellation_attempts VALUES (?, ?, ?, ?, ?)",
                    (
                        cancel_id,
                        order_id,
                        result.attempt_fingerprint,
                        canonical_json(result),
                        sequence,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return result

    def mark_unknown(self, cancel_id: str, *, observed_at: datetime) -> CancellationUnknownEvidence:
        _utc(observed_at)
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_connection(connection)
                self._verify_orders(connection)
                events = self._verify_broker_events(connection)
                attempts = self._verify_attempts(connection, events)
                unknown = self._verify_unknown(connection, events, attempts)
                try:
                    attempt = attempts[cancel_id]
                except KeyError:
                    raise JournalIntegrityError("cancellation attempt is missing") from None
                existing = unknown.get(cancel_id)
                if existing is not None:
                    if existing.observed_at != observed_at:
                        raise JournalIntegrityError("cancellation has a different unknown outcome")
                    connection.commit()
                    return existing
                order = connection.execute(
                    "SELECT state FROM orders WHERE order_id = ?", (attempt.order_id,)
                ).fetchone()
                latest = _latest_event(events, attempt.order_id)
                if (
                    order is None
                    or OrderState(order[0])
                    not in {OrderState.ACKNOWLEDGED, OrderState.PARTIALLY_FILLED}
                    or latest is None
                    or observed_at < attempt.requested_at
                ):
                    raise JournalIntegrityError(
                        "cancellation outcome is already resolved or invalid"
                    )
                result = CancellationUnknownEvidence(
                    cancel_id=cancel_id,
                    attempt_fingerprint=attempt.attempt_fingerprint,
                    broker_event_id=latest.event_id,
                    broker_event_fingerprint=latest.event_fingerprint,
                    observed_at=observed_at,
                )
                sequence = self._append_event(
                    connection,
                    occurred_at=observed_at,
                    event_type="order-cancel-unknown",
                    entity_type="cancellation-unknown-evidence",
                    entity_id=cancel_id,
                    payload=canonicalize(result),
                )
                connection.execute(
                    "INSERT INTO cancellation_unknown_evidence VALUES (?, ?, ?, ?)",
                    (
                        cancel_id,
                        result.evidence_fingerprint,
                        canonical_json(result),
                        sequence,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return result

    def unresolved(self) -> tuple[OrderCancellationAttempt, ...]:
        with self._connect() as connection:
            connection.execute("BEGIN")
            self._verify_connection(connection)
            events = self._verify_broker_events(connection)
            attempts = self._verify_attempts(connection, events)
            self._verify_unknown(connection, events, attempts)
            rows = connection.execute("SELECT order_id, state FROM orders").fetchall()
        active = {
            str(row[0])
            for row in rows
            if OrderState(row[1]) in {OrderState.ACKNOWLEDGED, OrderState.PARTIALLY_FILLED}
        }
        return tuple(
            sorted(
                (item for item in attempts.values() if item.order_id in active),
                key=lambda item: item.cancel_id,
            )
        )

    def _verify_attempts(
        self, connection: sqlite3.Connection, events: dict[str, BrokerOrderEvent]
    ) -> dict[str, OrderCancellationAttempt]:
        rows = connection.execute(
            "SELECT cancel_id, order_id, attempt_fingerprint, attempt_json, journal_sequence "
            "FROM order_cancellation_attempts"
        ).fetchall()
        count = connection.execute(
            "SELECT COUNT(*) FROM journal WHERE event_type = 'order-cancel-requested'"
        ).fetchone()[0]
        if len(rows) != count:
            raise JournalIntegrityError("cancellation attempt and journal counts differ")
        result: dict[str, OrderCancellationAttempt] = {}
        for row in rows:
            try:
                attempt = _decode_attempt(json.loads(row[3]))
                event = events[attempt.broker_event_id]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("stored cancellation attempt is invalid") from error
            order = connection.execute(
                "SELECT r.authorization_id FROM orders o JOIN capacity_reservations r "
                "ON r.reservation_id = o.reservation_id WHERE o.order_id = ?",
                (attempt.order_id,),
            ).fetchone()
            journal = connection.execute(
                "SELECT occurred_at, event_type, entity_type, entity_id, payload_json "
                "FROM journal WHERE sequence = ?",
                (row[4],),
            ).fetchone()
            if (
                row[:3] != (attempt.cancel_id, attempt.order_id, attempt.attempt_fingerprint)
                or row[3] != canonical_json(attempt)
                or order != (attempt.authorization_id,)
                or event.client_order_id != attempt.order_id
                or event.event_fingerprint != attempt.broker_event_fingerprint
                or attempt.requested_at < event.observed_at
                or journal
                != (
                    _utc_text(attempt.requested_at),
                    "order-cancel-requested",
                    "order-cancellation-attempt",
                    attempt.cancel_id,
                    canonical_json(attempt),
                )
            ):
                raise JournalIntegrityError("cancellation attempt differs from its order evidence")
            result[attempt.cancel_id] = attempt
        return result

    def _verify_unknown(
        self,
        connection: sqlite3.Connection,
        events: dict[str, BrokerOrderEvent],
        attempts: dict[str, OrderCancellationAttempt],
    ) -> dict[str, CancellationUnknownEvidence]:
        rows = connection.execute(
            "SELECT cancel_id, evidence_fingerprint, evidence_json, journal_sequence "
            "FROM cancellation_unknown_evidence"
        ).fetchall()
        count = connection.execute(
            "SELECT COUNT(*) FROM journal WHERE event_type = 'order-cancel-unknown'"
        ).fetchone()[0]
        if len(rows) != count:
            raise JournalIntegrityError("cancellation unknown evidence and journal counts differ")
        result: dict[str, CancellationUnknownEvidence] = {}
        for row in rows:
            try:
                evidence = _decode_unknown(json.loads(row[2]))
                attempt = attempts[evidence.cancel_id]
                event = events[evidence.broker_event_id]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError(
                    "stored cancellation unknown evidence is invalid"
                ) from error
            journal = connection.execute(
                "SELECT occurred_at, event_type, entity_type, entity_id, payload_json "
                "FROM journal WHERE sequence = ?",
                (row[3],),
            ).fetchone()
            if (
                row[0] != evidence.cancel_id
                or row[1] != evidence.evidence_fingerprint
                or row[2] != canonical_json(evidence)
                or evidence.attempt_fingerprint != attempt.attempt_fingerprint
                or evidence.observed_at < attempt.requested_at
                or event.client_order_id != attempt.order_id
                or event.event_fingerprint != evidence.broker_event_fingerprint
                or journal
                != (
                    _utc_text(evidence.observed_at),
                    "order-cancel-unknown",
                    "cancellation-unknown-evidence",
                    evidence.cancel_id,
                    canonical_json(evidence),
                )
            ):
                raise JournalIntegrityError(
                    "cancellation unknown evidence differs from its attempt"
                )
            result[evidence.cancel_id] = evidence
        return result


def _latest_event(events: dict[str, BrokerOrderEvent], order_id: str) -> BrokerOrderEvent | None:
    matching = [item for item in events.values() if item.client_order_id == order_id]
    return (
        None
        if not matching
        else max(matching, key=lambda item: (item.provider_timestamp, item.event_id))
    )


def _decode_attempt(value: object) -> OrderCancellationAttempt:
    if not isinstance(value, dict):
        raise ValueError("cancellation attempt must be an object")
    try:
        return OrderCancellationAttempt(
            **{
                **value,
                "order_state": OrderState(value["order_state"]),
                "requested_at": _parse_utc(str(value["requested_at"])),
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("cancellation attempt is invalid") from error


def _decode_unknown(value: object) -> CancellationUnknownEvidence:
    if not isinstance(value, dict):
        raise ValueError("cancellation unknown evidence must be an object")
    try:
        return CancellationUnknownEvidence(
            **{**value, "observed_at": _parse_utc(str(value["observed_at"]))}
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("cancellation unknown evidence is invalid") from error


def _utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("cancellation time must be UTC-aware")


def _parse_utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _utc(result)
    return result


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _sha256(name: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} fingerprint is invalid")
