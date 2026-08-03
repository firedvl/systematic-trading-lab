"""Broker-free deterministic order deltas."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from .execution import ExecutionIntent, JournalIntegrityError
from .fingerprints import canonical_json, canonicalize, fingerprint
from .risk import RiskStore


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderState(StrEnum):
    STAGED = "staged"
    SUBMITTING = "submitting"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_FILLED = "partially-filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    SUBMISSION_UNKNOWN = "submission-unknown"


_ORDER_TRANSITIONS = {
    OrderState.STAGED: set(),
    OrderState.SUBMITTING: {OrderState.ACKNOWLEDGED, OrderState.SUBMISSION_UNKNOWN},
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
    OrderState.SUBMISSION_UNKNOWN: {OrderState.ACKNOWLEDGED, OrderState.REJECTED},
}


@dataclass(frozen=True)
class OrderDelta:
    client_order_id: str
    intent_id: str
    intent_fingerprint: str
    symbol: str
    side: OrderSide
    quantity: int
    order_type: str
    time_in_force: str
    extended_hours: bool
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.client_order_id or len(self.client_order_id) > 128:
            raise ValueError("client order ID is invalid")
        if not self.intent_id or not self.intent_id.strip():
            raise ValueError("intent ID is invalid")
        if len(self.intent_fingerprint) != 64:
            raise ValueError("intent fingerprint is invalid")
        if not self.symbol or self.symbol != self.symbol.upper():
            raise ValueError("order symbol is invalid")
        if self.quantity < 1:
            raise ValueError("order quantity must be positive")
        if self.order_type != "market" or self.time_in_force != "day":
            raise ValueError("only day market orders are supported")
        if self.extended_hours:
            raise ValueError("extended-hours orders are disabled")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != UTC.utcoffset(
            self.created_at
        ):
            raise ValueError("order creation time must be UTC-aware")


@dataclass(frozen=True)
class StagedOrder:
    order_id: str
    reservation_id: str
    delta: OrderDelta
    state: OrderState
    changed_at: datetime
    submitter_id: str | None = None
    claimed_at: datetime | None = None


class OrderLifecycleStore(RiskStore):
    """Persist staged local orders without exposing broker mutation authority."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    reservation_id TEXT NOT NULL UNIQUE,
                    delta_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    changed_at TEXT NOT NULL,
                    submitter_id TEXT,
                    claimed_at TEXT,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                """
            )
            columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(orders)").fetchall()
            }
            if "submitter_id" not in columns:
                connection.execute("ALTER TABLE orders ADD COLUMN submitter_id TEXT")
            if "claimed_at" not in columns:
                connection.execute("ALTER TABLE orders ADD COLUMN claimed_at TEXT")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS orders_reservation_unique "
                "ON orders(reservation_id)"
            )
            connection.commit()
            self._verify_orders(connection)

    def _verify_orders(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT order_id, reservation_id, delta_json, state, changed_at, submitter_id, "
            "claimed_at, journal_sequence FROM orders"
        ).fetchall()
        event_count = connection.execute(
            "SELECT COUNT(*) FROM journal WHERE entity_type = 'order'"
        ).fetchone()[0]
        linked_count = connection.execute(
            "SELECT COUNT(*) FROM journal j JOIN orders o ON o.order_id = j.entity_id "
            "WHERE j.entity_type = 'order'"
        ).fetchone()[0]
        if event_count != linked_count:
            raise JournalIntegrityError("order journal contains an unknown order")
        for row in rows:
            try:
                delta = _decode_delta(json.loads(row[2]))
                state = OrderState(row[3])
                changed_at = _parse_utc(str(row[4]))
                claimed_at = None if row[6] is None else _parse_utc(str(row[6]))
            except (ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("stored order is invalid") from error
            reservation = connection.execute(
                "SELECT intent_id FROM capacity_reservations WHERE reservation_id = ?",
                (row[1],),
            ).fetchone()
            stage_event = connection.execute(
                "SELECT occurred_at, payload_json FROM journal "
                "WHERE event_type = 'order-staged' AND entity_id = ?",
                (row[0],),
            ).fetchall()
            latest = connection.execute(
                "SELECT occurred_at, event_type, entity_type, entity_id, payload_json "
                "FROM journal WHERE sequence = ?",
                (row[7],),
            ).fetchone()
            if (
                row[0] != delta.client_order_id
                or reservation != (delta.intent_id,)
                or len(stage_event) != 1
                or json.loads(stage_event[0][1])
                != canonicalize(
                    StagedOrder(
                        row[0],
                        row[1],
                        delta,
                        OrderState.STAGED,
                        _parse_utc(stage_event[0][0]),
                    )
                )
                or latest is None
                or latest[0] != row[4]
                or latest[2:4] != ("order", row[0])
            ):
                raise JournalIntegrityError("order does not match its journal or reservation")
            payload = json.loads(latest[4])
            if state is OrderState.STAGED:
                valid_latest = latest[1] == "order-staged" and row[5] is None and claimed_at is None
            elif state is OrderState.SUBMITTING:
                valid_latest = (
                    latest[1] == "order-submitter-claimed"
                    and payload.get("submitter_id") == row[5]
                    and payload.get("claimed_at") == row[6]
                    and claimed_at == changed_at
                )
            else:
                valid_latest = (
                    latest[1] == "order-transitioned"
                    and payload.get("to_state") == state
                    and payload.get("changed_at") == row[4]
                    and row[5] is not None
                    and claimed_at is not None
                )
            if not valid_latest:
                raise JournalIntegrityError("order state does not match its latest journal event")

    def stage(self, delta: OrderDelta, *, reservation_id: str, staged_at: datetime) -> StagedOrder:
        if not reservation_id or not reservation_id.strip():
            raise ValueError("reservation ID is required")
        if staged_at.tzinfo is None or staged_at.utcoffset() != UTC.utcoffset(staged_at):
            raise ValueError("staged time must be UTC-aware")
        order_id = delta.client_order_id
        staged = StagedOrder(order_id, reservation_id, delta, OrderState.STAGED, staged_at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._verify_connection(connection)
            self._verify_reservations(connection)
            self._verify_orders(connection)
            existing = connection.execute(
                "SELECT reservation_id, delta_json, state, changed_at, submitter_id, claimed_at "
                "FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if existing is not None:
                if existing[0] != reservation_id or existing[1] != canonical_json(delta):
                    raise JournalIntegrityError("client order ID is bound to different content")
                connection.commit()
                return StagedOrder(
                    order_id,
                    str(existing[0]),
                    delta,
                    OrderState(existing[2]),
                    _parse_utc(str(existing[3])),
                    None if existing[4] is None else str(existing[4]),
                    None if existing[5] is None else _parse_utc(str(existing[5])),
                )
            reservation = connection.execute(
                "SELECT intent_id, reserved_at, expires_at FROM capacity_reservations "
                "WHERE reservation_id = ?",
                (reservation_id,),
            ).fetchone()
            if reservation is None:
                raise JournalIntegrityError("capacity reservation is missing")
            intent = self._read_intent(connection, delta.intent_id)
            if (
                reservation[0] != delta.intent_id
                or intent.intent_fingerprint != delta.intent_fingerprint
                or delta.created_at < _parse_utc(str(reservation[1]))
                or staged_at < delta.created_at
                or staged_at >= _parse_utc(str(reservation[2]))
            ):
                raise JournalIntegrityError("order differs from its active capacity reservation")
            sequence = self._append_event(
                connection,
                occurred_at=staged_at,
                event_type="order-staged",
                entity_type="order",
                entity_id=order_id,
                payload=canonicalize(staged),
            )
            connection.execute(
                "INSERT INTO orders VALUES (?, ?, ?, ?, ?, NULL, NULL, ?)",
                (
                    order_id,
                    reservation_id,
                    canonical_json(delta),
                    staged.state,
                    _utc_text(staged_at),
                    sequence,
                ),
            )
            connection.commit()
        return staged

    def claim_submitter(
        self, order_id: str, *, submitter_id: str, claimed_at: datetime
    ) -> StagedOrder:
        if not submitter_id or submitter_id != submitter_id.strip():
            raise ValueError("submitter ID is required")
        if claimed_at.tzinfo is None or claimed_at.utcoffset() != UTC.utcoffset(claimed_at):
            raise ValueError("claim time must be UTC-aware")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._verify_connection(connection)
            self._verify_orders(connection)
            row = connection.execute(
                "SELECT reservation_id, delta_json, state, changed_at, submitter_id, claimed_at "
                "FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if row is None:
                raise KeyError(order_id)
            delta = _decode_delta(json.loads(row[1]))
            if row[4] is not None:
                if row[4] != submitter_id or row[5] != _utc_text(claimed_at):
                    raise JournalIntegrityError("order already has a different submitter claim")
                connection.commit()
                return StagedOrder(
                    order_id,
                    str(row[0]),
                    delta,
                    OrderState(row[2]),
                    _parse_utc(str(row[3])),
                    submitter_id,
                    claimed_at,
                )
            if OrderState(row[2]) is not OrderState.STAGED or claimed_at < _parse_utc(str(row[3])):
                raise JournalIntegrityError("order cannot be claimed from its current state")
            payload = {
                "order_id": order_id,
                "from_state": OrderState.STAGED,
                "to_state": OrderState.SUBMITTING,
                "submitter_id": submitter_id,
                "claimed_at": claimed_at,
            }
            sequence = self._append_event(
                connection,
                occurred_at=claimed_at,
                event_type="order-submitter-claimed",
                entity_type="order",
                entity_id=order_id,
                payload=canonicalize(payload),
            )
            updated = connection.execute(
                "UPDATE orders SET state = ?, changed_at = ?, submitter_id = ?, claimed_at = ?, "
                "journal_sequence = ? WHERE order_id = ? AND state = ? AND submitter_id IS NULL",
                (
                    OrderState.SUBMITTING,
                    _utc_text(claimed_at),
                    submitter_id,
                    _utc_text(claimed_at),
                    sequence,
                    order_id,
                    OrderState.STAGED,
                ),
            )
            if updated.rowcount != 1:
                raise JournalIntegrityError("order submitter claim lost its atomic race")
            connection.commit()
        return StagedOrder(
            order_id,
            str(row[0]),
            delta,
            OrderState.SUBMITTING,
            claimed_at,
            submitter_id,
            claimed_at,
        )

    def transition(self, order_id: str, state: OrderState, *, changed_at: datetime) -> StagedOrder:
        if changed_at.tzinfo is None or changed_at.utcoffset() != UTC.utcoffset(changed_at):
            raise ValueError("transition time must be UTC-aware")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._verify_connection(connection)
            self._verify_orders(connection)
            row = connection.execute(
                "SELECT reservation_id, delta_json, state, changed_at, submitter_id, claimed_at "
                "FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if row is None:
                raise KeyError(order_id)
            current = OrderState(row[2])
            if (
                state not in _ORDER_TRANSITIONS[current]
                or row[4] is None
                or changed_at < _parse_utc(str(row[3]))
            ):
                raise JournalIntegrityError(f"invalid order transition: {current} -> {state}")
            delta = _decode_delta(json.loads(row[1]))
            payload = {
                "order_id": order_id,
                "from_state": current,
                "to_state": state,
                "changed_at": changed_at,
            }
            sequence = self._append_event(
                connection,
                occurred_at=changed_at,
                event_type="order-transitioned",
                entity_type="order",
                entity_id=order_id,
                payload=canonicalize(payload),
            )
            connection.execute(
                "UPDATE orders SET state = ?, changed_at = ?, journal_sequence = ? "
                "WHERE order_id = ?",
                (state, _utc_text(changed_at), sequence, order_id),
            )
            connection.commit()
        return StagedOrder(
            order_id,
            str(row[0]),
            delta,
            state,
            changed_at,
            str(row[4]),
            _parse_utc(str(row[5])),
        )


def build_order_delta(
    intent: ExecutionIntent,
    *,
    target_quantity: int,
    current_quantity: int,
    created_at: datetime,
) -> OrderDelta | None:
    """Build one long-only whole-share delta without broker or persistence authority."""
    if isinstance(target_quantity, bool) or target_quantity < 0:
        raise ValueError("target quantity must be a nonnegative whole share count")
    if isinstance(current_quantity, bool) or current_quantity < 0:
        raise ValueError("current quantity must be a nonnegative whole share count")
    if created_at.tzinfo is None or created_at.utcoffset() != UTC.utcoffset(created_at):
        raise ValueError("order creation time must be UTC-aware")
    delta = target_quantity - current_quantity
    if delta == 0:
        return None
    side = OrderSide.BUY if delta > 0 else OrderSide.SELL
    quantity = abs(delta)
    identity = fingerprint(
        {
            "intent_id": intent.idempotency_key,
            "intent_fingerprint": intent.intent_fingerprint,
            "target_quantity": target_quantity,
            "current_quantity": current_quantity,
        }
    )
    return OrderDelta(
        client_order_id=f"stl-{identity[:32]}",
        intent_id=intent.idempotency_key,
        intent_fingerprint=intent.intent_fingerprint,
        symbol=intent.symbol,
        side=side,
        quantity=quantity,
        order_type="market",
        time_in_force="day",
        extended_hours=False,
        created_at=created_at,
    )


def _decode_delta(value: object) -> OrderDelta:
    if not isinstance(value, dict):
        raise ValueError("order delta must be an object")
    try:
        return OrderDelta(
            client_order_id=str(value["client_order_id"]),
            intent_id=str(value["intent_id"]),
            intent_fingerprint=str(value["intent_fingerprint"]),
            symbol=str(value["symbol"]),
            side=OrderSide(value["side"]),
            quantity=int(value["quantity"]),
            order_type=str(value["order_type"]),
            time_in_force=str(value["time_in_force"]),
            extended_hours=bool(value["extended_hours"]),
            created_at=_parse_utc(str(value["created_at"])),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("order delta is invalid") from error


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must be UTC-aware")
    return parsed


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
