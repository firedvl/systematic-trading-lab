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
from .orders import OrderLifecycleStore, OrderSide, OrderState, StagedOrder, _decode_delta
from .reconciliation import (
    PositionSnapshot,
    ReconciliationBaseline,
    SnapshotSource,
    _decode_baseline,
    _decode_snapshot,
)

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
class ExpectedPositionAdvance:
    baseline_id: str
    broker_event_id: str
    prior_advance_fingerprint: str | None
    positions: tuple[PositionSnapshot, ...]
    advanced_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("baseline ID", self.baseline_id),
            ("broker event ID", self.broker_event_id),
        ):
            if not value or value != value.strip() or len(value) > 128:
                raise ValueError(f"{name} is invalid")
        if self.prior_advance_fingerprint is not None and (
            len(self.prior_advance_fingerprint) != 64
            or any(
                character not in "0123456789abcdef" for character in self.prior_advance_fingerprint
            )
        ):
            raise ValueError("prior advance fingerprint is invalid")
        if (
            self.positions != tuple(sorted(self.positions, key=lambda item: item.symbol))
            or len({item.symbol for item in self.positions}) != len(self.positions)
            or any(item.quantity < 1 for item in self.positions)
        ):
            raise ValueError("expected positions must be sorted, unique, and positive")
        if self.advanced_at.tzinfo is None or self.advanced_at.utcoffset() != UTC.utcoffset(
            self.advanced_at
        ):
            raise ValueError("position advance time must be UTC-aware")

    @property
    def advance_fingerprint(self) -> str:
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
                CREATE TABLE IF NOT EXISTS expected_position_advances (
                    broker_event_id TEXT PRIMARY KEY REFERENCES broker_events(event_id),
                    baseline_id TEXT NOT NULL REFERENCES reconciliation_baselines(baseline_id),
                    advance_fingerprint TEXT NOT NULL UNIQUE,
                    advance_json TEXT NOT NULL,
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
                CREATE TRIGGER IF NOT EXISTS expected_position_advances_no_update
                BEFORE UPDATE ON expected_position_advances BEGIN
                    SELECT RAISE(ABORT, 'expected position advances are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS expected_position_advances_no_delete
                BEFORE DELETE ON expected_position_advances BEGIN
                    SELECT RAISE(ABORT, 'expected position advances are immutable');
                END;
                """
            )
            connection.commit()
            events = self._verify_broker_events(connection)
            self._verify_lookup_not_found(connection)
            self._verify_expected_position_advances(connection, events)

    def record(
        self, event: BrokerOrderEvent, *, baseline_id: str | None = None
    ) -> BrokerOrderEvent:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._verify_connection(connection)
            self._verify_reservations(connection)
            self._verify_releases(connection)
            self._verify_orders(connection)
            events = self._verify_broker_events(connection)
            self._verify_lookup_not_found(connection)
            advances = self._verify_expected_position_advances(connection, events)
            existing = events.get(event.event_id)
            if existing is not None:
                if existing != event:
                    self._reject_event(
                        connection, event, "broker event ID is bound to different content"
                    )
                if baseline_id is not None:
                    ordered = sorted(
                        (
                            item
                            for item in events.values()
                            if item.client_order_id == event.client_order_id
                        ),
                        key=lambda item: (item.provider_timestamp, item.event_id),
                    )
                    index = ordered.index(event)
                    prior_quantity = (
                        0 if index == 0 else ordered[index - 1].cumulative_filled_quantity
                    )
                    existing_advance = advances.get(event.event_id)
                    if event.cumulative_filled_quantity > prior_quantity and (
                        existing_advance is None or existing_advance.baseline_id != baseline_id
                    ):
                        self._reject_event(
                            connection,
                            event,
                            "broker event cannot gain or change expected-position lineage",
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
            advance = None
            prior_quantity = 0 if not prior else prior[-1].cumulative_filled_quantity
            if (
                baseline_id is not None
                and event.cumulative_filled_quantity > 0
                and event.cumulative_filled_quantity == prior_quantity
                and not any(
                    item.event_id in advances and advances[item.event_id].baseline_id == baseline_id
                    for item in prior
                    if item.cumulative_filled_quantity == event.cumulative_filled_quantity
                )
            ):
                self._reject_event(
                    connection,
                    event,
                    "broker event lacks prior expected-position lineage",
                )
            if baseline_id is not None and event.cumulative_filled_quantity > prior_quantity:
                try:
                    advance = self._expected_position_advance(
                        connection,
                        event=event,
                        baseline_id=baseline_id,
                        order_json=str(order[0]),
                        reservation_id=str(order[2]),
                        prior_events=prior,
                        advances=advances,
                    )
                except (KeyError, ValueError, json.JSONDecodeError) as error:
                    self._reject_event(connection, event, str(error))
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
            if advance is not None:
                advance_sequence = self._append_event(
                    connection,
                    occurred_at=advance.advanced_at,
                    event_type="expected-position-advanced",
                    entity_type="expected-position-advance",
                    entity_id=advance.broker_event_id,
                    payload=canonicalize(advance),
                )
                connection.execute(
                    "INSERT INTO expected_position_advances VALUES (?, ?, ?, ?, ?)",
                    (
                        advance.broker_event_id,
                        advance.baseline_id,
                        advance.advance_fingerprint,
                        canonical_json(advance),
                        advance_sequence,
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
                if (
                    event.state in {OrderState.CANCELED, OrderState.REJECTED}
                    and event.cumulative_filled_quantity == 0
                ):
                    self._release_capacity(
                        connection,
                        reservation_id=str(order[2]),
                        reason=f"order-{event.state}",
                        released_at=event.observed_at,
                    )
            connection.commit()
        return event

    def expected_positions(self, baseline_id: str) -> tuple[PositionSnapshot, ...]:
        with self._connect() as connection:
            connection.execute("BEGIN")
            self._verify_connection(connection)
            self._verify_reservations(connection)
            self._verify_releases(connection)
            self._verify_orders(connection)
            events = self._verify_broker_events(connection)
            advances = self._verify_expected_position_advances(connection, events)
            try:
                baseline, initial_positions = self._baseline_anchor(connection, baseline_id)
                self._require_complete_lineage(
                    connection,
                    baseline=baseline,
                    baseline_id=baseline_id,
                    advances=advances,
                )
            except (KeyError, ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("expected-position lineage is incomplete") from error
            matching = [item for item in advances.values() if item.baseline_id == baseline_id]
            if matching:
                return matching[-1].positions
            return initial_positions

    def _expected_position_advance(
        self,
        connection: sqlite3.Connection,
        *,
        event: BrokerOrderEvent,
        baseline_id: str,
        order_json: str,
        reservation_id: str,
        prior_events: list[BrokerOrderEvent],
        advances: dict[str, ExpectedPositionAdvance],
    ) -> ExpectedPositionAdvance:
        baseline, initial_positions = self._baseline_anchor(connection, baseline_id)
        reservation = connection.execute(
            "SELECT authorization_id FROM capacity_reservations WHERE reservation_id = ?",
            (reservation_id,),
        ).fetchone()
        if (
            reservation is None
            or str(reservation[0]) != baseline.authorization_id
            or event.provider_timestamp < baseline.created_at
            or event.observed_at < baseline.created_at
        ):
            raise ValueError("broker event does not match its expected-position baseline")
        self._require_complete_lineage(
            connection,
            baseline=baseline,
            baseline_id=baseline_id,
            advances=advances,
            stop_event_id=event.event_id,
        )
        delta = _decode_delta(json.loads(order_json))
        prior_quantity = 0 if not prior_events else prior_events[-1].cumulative_filled_quantity
        increment = event.cumulative_filled_quantity - prior_quantity
        if increment < 1:
            raise ValueError("expected-position advance requires a new fill")
        lineage = [item for item in advances.values() if item.baseline_id == baseline_id]
        positions = {
            item.symbol: item.quantity
            for item in (lineage[-1].positions if lineage else initial_positions)
        }
        signed_increment = increment if delta.side is OrderSide.BUY else -increment
        quantity = positions.get(delta.symbol, 0) + signed_increment
        if quantity < 0:
            raise ValueError("expected position cannot become negative")
        if quantity:
            positions[delta.symbol] = quantity
        else:
            positions.pop(delta.symbol, None)
        return ExpectedPositionAdvance(
            baseline_id=baseline_id,
            broker_event_id=event.event_id,
            prior_advance_fingerprint=(None if not lineage else lineage[-1].advance_fingerprint),
            positions=tuple(
                PositionSnapshot(symbol=symbol, quantity=value)
                for symbol, value in sorted(positions.items())
            ),
            advanced_at=event.observed_at,
        )

    def _require_complete_lineage(
        self,
        connection: sqlite3.Connection,
        *,
        baseline: ReconciliationBaseline,
        baseline_id: str,
        advances: dict[str, ExpectedPositionAdvance],
        stop_event_id: str | None = None,
    ) -> None:
        seen_quantities: dict[str, int] = {}
        prior_rows = connection.execute(
            "SELECT b.event_json FROM broker_events b "
            "JOIN orders o ON o.order_id = b.client_order_id "
            "JOIN capacity_reservations r ON r.reservation_id = o.reservation_id "
            "WHERE json_extract(r.reservation_json, '$.account_id') = ? "
            "ORDER BY b.journal_sequence",
            (baseline.account_id,),
        ).fetchall()
        for prior_row in prior_rows:
            known_event = _decode_event(json.loads(prior_row[0]))
            if known_event.event_id == stop_event_id:
                break
            known_quantity = seen_quantities.get(known_event.client_order_id, 0)
            if (
                known_event.observed_at >= baseline.created_at
                and known_event.cumulative_filled_quantity > known_quantity
                and (
                    known_event.event_id not in advances
                    or advances[known_event.event_id].baseline_id != baseline_id
                )
            ):
                raise ValueError("expected-position lineage has an unrecorded prior fill")
            seen_quantities[known_event.client_order_id] = known_event.cumulative_filled_quantity

    def _baseline_anchor(
        self, connection: sqlite3.Connection, baseline_id: str
    ) -> tuple[ReconciliationBaseline, tuple[PositionSnapshot, ...]]:
        row = connection.execute(
            "SELECT b.baseline_json, b.journal_sequence, s.snapshot_json, "
            "s.snapshot_fingerprint FROM reconciliation_baselines b "
            "JOIN portfolio_snapshots s ON s.snapshot_id = "
            "json_extract(b.baseline_json, '$.expected_snapshot_id') "
            "WHERE b.baseline_id = ?",
            (baseline_id,),
        ).fetchone()
        if row is None:
            raise KeyError("expected-position baseline is missing")
        baseline = _decode_baseline(json.loads(row[0]))
        snapshot = _decode_snapshot(json.loads(row[2]))
        journal = connection.execute(
            "SELECT occurred_at, event_type, entity_type, entity_id, payload_json "
            "FROM journal WHERE sequence = ?",
            (row[1],),
        ).fetchone()
        if (
            baseline.baseline_id != baseline_id
            or row[0] != canonical_json(baseline)
            or snapshot.source is not SnapshotSource.LOCAL_EXPECTED
            or snapshot.snapshot_id != baseline.expected_snapshot_id
            or snapshot.snapshot_fingerprint != baseline.expected_fingerprint
            or row[2] != canonical_json(snapshot)
            or row[3] != snapshot.snapshot_fingerprint
            or journal
            != (
                _utc_text(baseline.created_at),
                "reconciliation-baseline-created",
                "reconciliation-baseline",
                baseline.baseline_id,
                canonical_json(baseline),
            )
        ):
            raise ValueError("expected-position baseline is invalid")
        return baseline, snapshot.positions

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

    def _verify_expected_position_advances(
        self,
        connection: sqlite3.Connection,
        events: dict[str, BrokerOrderEvent] | None = None,
    ) -> dict[str, ExpectedPositionAdvance]:
        broker_events = events if events is not None else self._verify_broker_events(connection)
        rows = connection.execute(
            "SELECT broker_event_id, baseline_id, advance_fingerprint, advance_json, "
            "journal_sequence FROM expected_position_advances ORDER BY journal_sequence"
        ).fetchall()
        count = connection.execute(
            "SELECT COUNT(*) FROM journal WHERE event_type = 'expected-position-advanced'"
        ).fetchone()[0]
        if len(rows) != count:
            raise JournalIntegrityError("expected-position advance and journal counts differ")
        result: dict[str, ExpectedPositionAdvance] = {}
        for row in rows:
            try:
                advance = _decode_expected_position_advance(json.loads(row[3]))
                event = broker_events[advance.broker_event_id]
                order = connection.execute(
                    "SELECT delta_json, reservation_id FROM orders WHERE order_id = ?",
                    (event.client_order_id,),
                ).fetchone()
                if order is None:
                    raise ValueError("expected-position order is missing")
                prior_row = connection.execute(
                    "SELECT event_json FROM broker_events WHERE client_order_id = ? "
                    "AND journal_sequence < (SELECT journal_sequence FROM broker_events "
                    "WHERE event_id = ?) ORDER BY journal_sequence DESC LIMIT 1",
                    (event.client_order_id, event.event_id),
                ).fetchone()
                prior = [] if prior_row is None else [_decode_event(json.loads(prior_row[0]))]
                expected = self._expected_position_advance(
                    connection,
                    event=event,
                    baseline_id=advance.baseline_id,
                    order_json=str(order[0]),
                    reservation_id=str(order[1]),
                    prior_events=prior,
                    advances=result,
                )
            except (KeyError, ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError(
                    "stored expected-position advance is invalid"
                ) from error
            payload = canonical_json(advance)
            journal = connection.execute(
                "SELECT occurred_at, event_type, entity_type, entity_id, payload_json "
                "FROM journal WHERE sequence = ?",
                (row[4],),
            ).fetchone()
            if (
                advance != expected
                or row[:3]
                != (
                    advance.broker_event_id,
                    advance.baseline_id,
                    advance.advance_fingerprint,
                )
                or row[3] != payload
                or journal
                != (
                    _utc_text(advance.advanced_at),
                    "expected-position-advanced",
                    "expected-position-advance",
                    advance.broker_event_id,
                    payload,
                )
            ):
                raise JournalIntegrityError(
                    "expected-position advance does not match its broker event or journal"
                )
            result[advance.broker_event_id] = advance
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


def _decode_expected_position_advance(value: object) -> ExpectedPositionAdvance:
    if not isinstance(value, dict):
        raise ValueError("expected-position advance must be an object")
    try:
        return ExpectedPositionAdvance(
            baseline_id=str(value["baseline_id"]),
            broker_event_id=str(value["broker_event_id"]),
            prior_advance_fingerprint=(
                None
                if value["prior_advance_fingerprint"] is None
                else str(value["prior_advance_fingerprint"])
            ),
            positions=tuple(PositionSnapshot(**item) for item in value["positions"]),
            advanced_at=_parse_utc(str(value["advanced_at"])),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("expected-position advance is invalid") from error


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
