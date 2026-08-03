"""Normalized broker order-event evidence without broker access."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Never

from .execution import JournalIntegrityError
from .fingerprints import canonical_json, canonicalize, fingerprint
from .orders import OrderLifecycleStore, OrderState, StagedOrder

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
_ALPACA_READER_CAPABILITY = object()


@dataclass(frozen=True)
class BrokerOrderEvent:
    event_id: str
    broker_order_id: str
    client_order_id: str
    state: OrderState
    cumulative_filled_quantity: int
    cumulative_average_fill_price: Decimal | None
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
        if self.cumulative_filled_quantity == 0:
            if self.cumulative_average_fill_price is not None:
                raise ValueError("unfilled broker event cannot have an average fill price")
        elif (
            self.cumulative_average_fill_price is None
            or not self.cumulative_average_fill_price.is_finite()
            or self.cumulative_average_fill_price <= 0
        ):
            raise ValueError("filled broker event requires a positive average fill price")
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


@dataclass(frozen=True)
class OrderLookupNotFoundEvidence:
    client_order_id: str
    account_id: str
    paper_origin: str
    lookup_path: str
    adapter_version: str
    http_status: int
    observed_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("client order ID", self.client_order_id),
            ("account ID", self.account_id),
        ):
            if not value or value != value.strip() or len(value) > 128:
                raise ValueError(f"{name} is invalid")
        if (
            self.paper_origin != "https://paper-api.alpaca.markets"
            or self.lookup_path != "/v2/orders:by_client_order_id"
            or self.adapter_version != "alpaca-paper-reader-v1"
            or self.http_status != 404
        ):
            raise ValueError("negative lookup provenance is unsupported")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() != UTC.utcoffset(
            self.observed_at
        ):
            raise ValueError("lookup observation time must be UTC-aware")

    @property
    def evidence_id(self) -> str:
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
                CREATE TABLE IF NOT EXISTS order_lookup_not_found (
                    evidence_id TEXT PRIMARY KEY,
                    client_order_id TEXT NOT NULL REFERENCES orders(order_id),
                    evidence_json TEXT NOT NULL,
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
                CREATE TRIGGER IF NOT EXISTS order_lookup_not_found_no_update
                BEFORE UPDATE ON order_lookup_not_found BEGIN
                    SELECT RAISE(ABORT, 'negative order lookups are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS order_lookup_not_found_no_delete
                BEFORE DELETE ON order_lookup_not_found BEGIN
                    SELECT RAISE(ABORT, 'negative order lookups are immutable');
                END;
                """
            )
            connection.commit()
            self._verify_broker_events(connection)
            self._verify_lookup_not_found(connection)

    def record(self, event: BrokerOrderEvent) -> BrokerOrderEvent:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._verify_connection(connection)
            self._verify_orders(connection)
            events = self._verify_broker_events(connection)
            self._verify_lookup_not_found(connection)
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

    def _record_lookup_not_found(
        self,
        *,
        client_order_id: str,
        account_id: str,
        observed_at: datetime,
        _capability: object,
    ) -> OrderLookupNotFoundEvidence:
        if _capability is not _ALPACA_READER_CAPABILITY:
            raise PermissionError("only the production Alpaca reader can attest a missing order")
        evidence = OrderLookupNotFoundEvidence(
            client_order_id=client_order_id,
            account_id=account_id,
            paper_origin="https://paper-api.alpaca.markets",
            lookup_path="/v2/orders:by_client_order_id",
            adapter_version="alpaca-paper-reader-v1",
            http_status=404,
            observed_at=observed_at,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._verify_connection(connection)
            self._verify_reservations(connection)
            self._verify_releases(connection)
            self._verify_orders(connection)
            self._verify_broker_events(connection)
            existing = self._verify_lookup_not_found(connection).get(evidence.evidence_id)
            if existing is not None:
                connection.commit()
                return existing
            order = connection.execute(
                "SELECT o.state, o.changed_at, r.authorization_id FROM orders o "
                "JOIN capacity_reservations r ON r.reservation_id = o.reservation_id "
                "WHERE o.order_id = ?",
                (client_order_id,),
            ).fetchone()
            authorizations = self._verify_authorizations(connection)
            authorization = None if order is None else authorizations.get(str(order[2]))
            if (
                order is None
                or OrderState(order[0]) is not OrderState.SUBMISSION_UNKNOWN
                or observed_at < _parse_utc(str(order[1]))
                or authorization is None
                or authorization.account_id != account_id
            ):
                raise JournalIntegrityError(
                    "negative lookup requires a matching submission-unknown paper order"
                )
            sequence = self._append_event(
                connection,
                occurred_at=observed_at,
                event_type="order-lookup-not-found",
                entity_type="order-lookup",
                entity_id=evidence.evidence_id,
                payload=canonicalize(evidence),
            )
            connection.execute(
                "INSERT INTO order_lookup_not_found VALUES (?, ?, ?, ?)",
                (
                    evidence.evidence_id,
                    client_order_id,
                    canonical_json(evidence),
                    sequence,
                ),
            )
            connection.commit()
        return evidence

    def submission_unknown_orders(self) -> tuple[StagedOrder, ...]:
        """Return unknown orders after verifying all local and broker evidence."""
        with self._connect() as connection:
            connection.execute("BEGIN")
            self._verify_connection(connection)
            self._verify_reservations(connection)
            self._verify_releases(connection)
            self._verify_orders(connection)
            self._verify_broker_events(connection)
            self._verify_lookup_not_found(connection)
            return self._submission_unknown_orders(connection)

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
                raw_event = json.loads(row[3])
                event = _decode_event(raw_event)
            except (ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("stored broker event is invalid") from error
            legacy = "cumulative_average_fill_price" not in raw_event
            stored_payload = raw_event if legacy else canonicalize(event)
            stored_json = canonical_json(stored_payload)
            stored_fingerprint = fingerprint(stored_payload)
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
                row[:3] != (event.event_id, stored_fingerprint, event.client_order_id)
                or row[3] != stored_json
                or journal
                != (
                    _utc_text(event.observed_at),
                    "broker-event-recorded",
                    "broker-event",
                    event.event_id,
                    stored_json,
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

    def _verify_lookup_not_found(
        self, connection: sqlite3.Connection
    ) -> dict[str, OrderLookupNotFoundEvidence]:
        rows = connection.execute(
            "SELECT evidence_id, client_order_id, evidence_json, journal_sequence "
            "FROM order_lookup_not_found"
        ).fetchall()
        count = connection.execute(
            "SELECT COUNT(*) FROM journal WHERE event_type = 'order-lookup-not-found'"
        ).fetchone()[0]
        if len(rows) != count:
            raise JournalIntegrityError("negative order lookup and journal counts differ")
        authorizations = self._verify_authorizations(connection)
        result: dict[str, OrderLookupNotFoundEvidence] = {}
        for row in rows:
            try:
                evidence = _decode_lookup_not_found(json.loads(row[2]))
                order = connection.execute(
                    "SELECT r.authorization_id FROM orders o "
                    "JOIN capacity_reservations r ON r.reservation_id = o.reservation_id "
                    "WHERE o.order_id = ?",
                    (evidence.client_order_id,),
                ).fetchone()
                prior_order_event = connection.execute(
                    "SELECT occurred_at, event_type, payload_json FROM journal "
                    "WHERE entity_type = 'order' AND entity_id = ? AND sequence < ? "
                    "ORDER BY sequence DESC LIMIT 1",
                    (evidence.client_order_id, row[3]),
                ).fetchone()
            except (ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("stored negative order lookup is invalid") from error
            journal = connection.execute(
                "SELECT occurred_at, event_type, entity_type, entity_id, payload_json "
                "FROM journal WHERE sequence = ?",
                (row[3],),
            ).fetchone()
            unknown_before_lookup = (
                prior_order_event is not None
                and prior_order_event[1] == "order-transitioned"
                and json.loads(prior_order_event[2]).get("to_state")
                == OrderState.SUBMISSION_UNKNOWN
                and _parse_utc(str(prior_order_event[0])) <= evidence.observed_at
            )
            authorization = None if order is None else authorizations.get(str(order[0]))
            if (
                row[:2] != (evidence.evidence_id, evidence.client_order_id)
                or row[2] != canonical_json(evidence)
                or journal
                != (
                    _utc_text(evidence.observed_at),
                    "order-lookup-not-found",
                    "order-lookup",
                    evidence.evidence_id,
                    canonical_json(evidence),
                )
                or order is None
                or authorization is None
                or authorization.account_id != evidence.account_id
                or not unknown_before_lookup
            ):
                raise JournalIntegrityError("negative order lookup does not match its evidence")
            result[evidence.evidence_id] = evidence
        return result


def _can_follow(prior: list[BrokerOrderEvent], event: BrokerOrderEvent) -> bool:
    if not prior:
        return event.state in _BROKER_STATES
    previous = prior[-1]
    same_quantity = event.cumulative_filled_quantity == previous.cumulative_filled_quantity
    return (
        event.provider_timestamp >= previous.provider_timestamp
        and event.cumulative_filled_quantity >= previous.cumulative_filled_quantity
        and (
            event.cumulative_average_fill_price == previous.cumulative_average_fill_price
            if same_quantity
            else _filled_notional(event) > _filled_notional(previous)
        )
        and event.state in _BROKER_TRANSITIONS[previous.state]
    )


def _filled_notional(event: BrokerOrderEvent) -> Decimal:
    return Decimal(event.cumulative_filled_quantity) * (
        event.cumulative_average_fill_price or Decimal("0")
    )


def _decode_event(value: object) -> BrokerOrderEvent:
    if not isinstance(value, dict):
        raise ValueError("broker event must be an object")
    try:
        quantity = int(value["cumulative_filled_quantity"])
        raw_average_price = value.get("cumulative_average_fill_price")
        if "cumulative_average_fill_price" not in value and quantity:
            raise ValueError("legacy positive fill lacks average price")
        return BrokerOrderEvent(
            event_id=str(value["event_id"]),
            broker_order_id=str(value["broker_order_id"]),
            client_order_id=str(value["client_order_id"]),
            state=OrderState(value["state"]),
            cumulative_filled_quantity=quantity,
            cumulative_average_fill_price=(
                None if raw_average_price is None else Decimal(str(raw_average_price))
            ),
            provider_timestamp=_parse_utc(str(value["provider_timestamp"])),
            observed_at=_parse_utc(str(value["observed_at"])),
        )
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        raise ValueError("broker event is invalid") from error


def _decode_lookup_not_found(value: object) -> OrderLookupNotFoundEvidence:
    if not isinstance(value, dict) or set(value) != {
        "client_order_id",
        "account_id",
        "paper_origin",
        "lookup_path",
        "adapter_version",
        "http_status",
        "observed_at",
    }:
        raise ValueError("negative order lookup has an unsupported schema")
    try:
        return OrderLookupNotFoundEvidence(
            client_order_id=str(value["client_order_id"]),
            account_id=str(value["account_id"]),
            paper_origin=str(value["paper_origin"]),
            lookup_path=str(value["lookup_path"]),
            adapter_version=str(value["adapter_version"]),
            http_status=int(value["http_status"]),
            observed_at=_parse_utc(str(value["observed_at"])),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("negative order lookup is invalid") from error


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must be UTC-aware")
    return parsed


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
