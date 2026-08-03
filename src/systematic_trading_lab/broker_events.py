"""Normalized broker order-event evidence without broker access."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Never

from .execution import JournalIntegrityError
from .fingerprints import canonical_json, canonicalize, fingerprint
from .orders import OrderLifecycleStore, OrderState

_BROKER_STATES = {
    OrderState.ACKNOWLEDGED,
    OrderState.PARTIALLY_FILLED,
    OrderState.FILLED,
    OrderState.CANCELED,
    OrderState.REJECTED,
}
_BROKER_TRANSITIONS = {
    OrderState.ACKNOWLEDGED: {
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.CANCELED,
        OrderState.REJECTED,
    },
    OrderState.PARTIALLY_FILLED: {
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.CANCELED,
    },
    OrderState.FILLED: set(),
    OrderState.CANCELED: set(),
    OrderState.REJECTED: set(),
}
_LOCAL_BROKER_TRANSITIONS = {
    OrderState.SUBMITTING: _BROKER_STATES,
    OrderState.SUBMISSION_UNKNOWN: _BROKER_STATES,
    OrderState.ACKNOWLEDGED: _BROKER_TRANSITIONS[OrderState.ACKNOWLEDGED],
    OrderState.PARTIALLY_FILLED: _BROKER_TRANSITIONS[OrderState.PARTIALLY_FILLED],
    OrderState.FILLED: set(),
    OrderState.CANCELED: set(),
    OrderState.REJECTED: set(),
    OrderState.STAGED: set(),
}


@dataclass(frozen=True)
class BrokerOrderEvent:
    event_id: str
    broker_order_id: str
    client_order_id: str
    state: OrderState
    cumulative_filled_quantity: int
    provider_timestamp: datetime
    observed_at: datetime

    def __post_init__(self) -> None:
        for name, text_value in (
            ("event ID", self.event_id),
            ("broker order ID", self.broker_order_id),
            ("client order ID", self.client_order_id),
        ):
            if not text_value or text_value != text_value.strip() or len(text_value) > 128:
                raise ValueError(f"{name} is invalid")
        if self.state not in _BROKER_STATES:
            raise ValueError("broker event state is unsupported")
        if isinstance(self.cumulative_filled_quantity, bool) or self.cumulative_filled_quantity < 0:
            raise ValueError("filled quantity must be nonnegative")
        for name, timestamp in (
            ("provider timestamp", self.provider_timestamp),
            ("observation time", self.observed_at),
        ):
            if timestamp.tzinfo is None or timestamp.utcoffset() != UTC.utcoffset(timestamp):
                raise ValueError(f"{name} must be UTC-aware")
        if self.observed_at < self.provider_timestamp:
            raise ValueError("broker event cannot be observed before its provider timestamp")

    @property
    def event_fingerprint(self) -> str:
        return fingerprint(self)


class BrokerEventStore(OrderLifecycleStore):
    """Store sanitized broker events without applying them or contacting a broker."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS broker_events (
                    event_id TEXT PRIMARY KEY,
                    event_fingerprint TEXT NOT NULL UNIQUE,
                    client_order_id TEXT NOT NULL REFERENCES orders(order_id),
                    event_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS broker_events_no_update
                BEFORE UPDATE ON broker_events BEGIN
                    SELECT RAISE(ABORT, 'broker events are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS broker_events_no_delete
                BEFORE DELETE ON broker_events BEGIN
                    SELECT RAISE(ABORT, 'broker events are immutable');
                END;
                """
            )
            connection.commit()
            self._verify_broker_events(connection)

    def record(self, event: BrokerOrderEvent) -> BrokerOrderEvent:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._verify_connection(connection)
            self._verify_orders(connection)
            events = self._verify_broker_events(connection)
            existing = events.get(event.event_id)
            if existing is not None:
                if existing != event:
                    self._reject_event(
                        connection, event, "broker event ID is bound to different content"
                    )
                connection.commit()
                return existing
            order = connection.execute(
                "SELECT delta_json, state, reservation_id, changed_at FROM orders "
                "WHERE order_id = ?",
                (event.client_order_id,),
            ).fetchone()
            if order is None:
                self._reject_event(connection, event, "broker event order is missing")
            quantity = int(json.loads(order[0])["quantity"])
            prior = sorted(
                (item for item in events.values() if item.client_order_id == event.client_order_id),
                key=lambda item: (item.provider_timestamp, item.event_id),
            )
            if (
                event.cumulative_filled_quantity > quantity
                or (
                    event.state is OrderState.FILLED
                    and event.cumulative_filled_quantity != quantity
                )
                or not _can_follow(prior, event)
            ):
                self._reject_event(
                    connection,
                    event,
                    "broker event is out of order or exceeds order quantity",
                )
            current = OrderState(order[1])
            if event.state != current and event.state not in _LOCAL_BROKER_TRANSITIONS[current]:
                self._reject_event(
                    connection, event, "broker event conflicts with local order state"
                )
            sequence = self._append_event(
                connection,
                occurred_at=event.observed_at,
                event_type="broker-event-recorded",
                entity_type="broker-event",
                entity_id=event.event_id,
                payload=canonicalize(event),
            )
            connection.execute(
                "INSERT INTO broker_events VALUES (?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.event_fingerprint,
                    event.client_order_id,
                    canonical_json(event),
                    sequence,
                ),
            )
            if event.state != current:
                transition = {
                    "order_id": event.client_order_id,
                    "from_state": current,
                    "to_state": event.state,
                    "changed_at": event.observed_at,
                    "broker_event_id": event.event_id,
                }
                order_sequence = self._append_event(
                    connection,
                    occurred_at=event.observed_at,
                    event_type="order-transitioned",
                    entity_type="order",
                    entity_id=event.client_order_id,
                    payload=canonicalize(transition),
                )
                connection.execute(
                    "UPDATE orders SET state = ?, changed_at = ?, journal_sequence = ? "
                    "WHERE order_id = ?",
                    (
                        event.state,
                        _utc_text(event.observed_at),
                        order_sequence,
                        event.client_order_id,
                    ),
                )
                if event.state in {OrderState.CANCELED, OrderState.REJECTED}:
                    self._release_capacity(
                        connection,
                        reservation_id=str(order[2]),
                        reason=f"order-{event.state}",
                        released_at=event.observed_at,
                    )
            connection.commit()
        return event

    def _reject_event(
        self, connection: sqlite3.Connection, event: BrokerOrderEvent, message: str
    ) -> Never:
        emergency = self._verify_emergency(connection)
        if not emergency.disabled:
            payload = {
                "cause_fingerprint": event.event_fingerprint,
                "disabled": True,
                "generation": emergency.generation + 1,
                "reason": message,
                "operator": "system",
                "changed_at": _utc_text(event.observed_at),
            }
            sequence = self._append_event(
                connection,
                occurred_at=event.observed_at,
                event_type="emergency-disabled",
                entity_type="emergency-state",
                entity_id="global",
                payload=payload,
            )
            updated = connection.execute(
                "UPDATE emergency_state SET disabled = 1, generation = ?, reason = ?, "
                "operator = ?, changed_at = ?, journal_sequence = ? "
                "WHERE singleton = 1 AND generation = ? AND disabled = 0",
                (
                    payload["generation"],
                    message,
                    "system",
                    payload["changed_at"],
                    sequence,
                    emergency.generation,
                ),
            )
            if updated.rowcount != 1:
                raise JournalIntegrityError("emergency state changed during broker-event rejection")
            connection.commit()
        raise JournalIntegrityError(message)

    def _verify_broker_events(self, connection: sqlite3.Connection) -> dict[str, BrokerOrderEvent]:
        rows = connection.execute(
            "SELECT event_id, event_fingerprint, client_order_id, event_json, journal_sequence "
            "FROM broker_events"
        ).fetchall()
        count = connection.execute(
            "SELECT COUNT(*) FROM journal WHERE event_type = 'broker-event-recorded'"
        ).fetchone()[0]
        if len(rows) != count:
            raise JournalIntegrityError("broker event and journal counts differ")
        result: dict[str, BrokerOrderEvent] = {}
        by_order: dict[str, list[BrokerOrderEvent]] = {}
        for row in rows:
            try:
                event = _decode_event(json.loads(row[3]))
            except (ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("stored broker event is invalid") from error
            journal = connection.execute(
                "SELECT occurred_at, event_type, entity_type, entity_id, payload_json "
                "FROM journal WHERE sequence = ?",
                (row[4],),
            ).fetchone()
            order = connection.execute(
                "SELECT delta_json FROM orders WHERE order_id = ?", (event.client_order_id,)
            ).fetchone()
            quantity = None if order is None else int(json.loads(order[0])["quantity"])
            if (
                row[:3] != (event.event_id, event.event_fingerprint, event.client_order_id)
                or row[3] != canonical_json(event)
                or journal
                != (
                    _utc_text(event.observed_at),
                    "broker-event-recorded",
                    "broker-event",
                    event.event_id,
                    canonical_json(event),
                )
                or quantity is None
                or event.cumulative_filled_quantity > quantity
                or (
                    event.state is OrderState.FILLED
                    and event.cumulative_filled_quantity != quantity
                )
            ):
                raise JournalIntegrityError("broker event does not match its journal or order")
            result[event.event_id] = event
            by_order.setdefault(event.client_order_id, []).append(event)
        for events in by_order.values():
            ordered = sorted(events, key=lambda item: (item.provider_timestamp, item.event_id))
            if any(not _can_follow(ordered[:index], event) for index, event in enumerate(ordered)):
                raise JournalIntegrityError("stored broker event sequence is invalid")
        return result


def _can_follow(prior: list[BrokerOrderEvent], event: BrokerOrderEvent) -> bool:
    if not prior:
        return event.state in _BROKER_STATES
    previous = prior[-1]
    return (
        event.provider_timestamp >= previous.provider_timestamp
        and event.cumulative_filled_quantity >= previous.cumulative_filled_quantity
        and event.state in _BROKER_TRANSITIONS[previous.state]
    )


def _decode_event(value: object) -> BrokerOrderEvent:
    if not isinstance(value, dict):
        raise ValueError("broker event must be an object")
    try:
        return BrokerOrderEvent(
            event_id=str(value["event_id"]),
            broker_order_id=str(value["broker_order_id"]),
            client_order_id=str(value["client_order_id"]),
            state=OrderState(value["state"]),
            cumulative_filled_quantity=int(value["cumulative_filled_quantity"]),
            provider_timestamp=_parse_utc(str(value["provider_timestamp"])),
            observed_at=_parse_utc(str(value["observed_at"])),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("broker event is invalid") from error


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must be UTC-aware")
    return parsed


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
