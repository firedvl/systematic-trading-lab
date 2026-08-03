"""Broker-free deterministic order deltas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from .execution import ExecutionIntent
from .fingerprints import fingerprint


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


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
