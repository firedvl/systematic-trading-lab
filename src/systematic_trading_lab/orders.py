"""Broker-free deterministic order deltas."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from .execution import ExecutionIntent, ExecutionStore, JournalIntegrityError
from .fingerprints import canonical_json, canonicalize, fingerprint


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
    OrderState.STAGED: {OrderState.SUBMITTING},
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


class OrderLifecycleStore(ExecutionStore):
    """Persist staged local orders without exposing broker mutation authority."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    reservation_id TEXT NOT NULL,
                    delta_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    changed_at TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                """
            )
            connection.commit()

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
            existing = connection.execute(
                "SELECT reservation_id, delta_json, state, changed_at "
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
                )
            sequence = self._append_event(
                connection,
                occurred_at=staged_at,
                event_type="order-staged",
                entity_type="order",
                entity_id=order_id,
                payload=canonicalize(staged),
            )
            connection.execute(
                "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)",
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

    def transition(self, order_id: str, state: OrderState, *, changed_at: datetime) -> StagedOrder:
        if changed_at.tzinfo is None or changed_at.utcoffset() != UTC.utcoffset(changed_at):
            raise ValueError("transition time must be UTC-aware")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._verify_connection(connection)
            row = connection.execute(
                "SELECT reservation_id, delta_json, state, changed_at "
                "FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if row is None:
                raise KeyError(order_id)
            current = OrderState(row[2])
            if state not in _ORDER_TRANSITIONS[current]:
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
        return StagedOrder(order_id, str(row[0]), delta, state, changed_at)


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
