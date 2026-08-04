from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from systematic_trading_lab.broker_events import BrokerOrderEvent, _can_follow, _decode_event
from systematic_trading_lab.orders import OrderState

NOW = datetime(2026, 8, 3, 20, tzinfo=UTC)


def test_cumulative_fill_price_matches_quantity_and_forward_notional() -> None:
    acknowledged = BrokerOrderEvent(
        event_id="event-1",
        broker_order_id="broker-order-1",
        client_order_id="client-order-1",
        state=OrderState.ACKNOWLEDGED,
        cumulative_filled_quantity=0,
        cumulative_average_fill_price=None,
        provider_timestamp=NOW,
        observed_at=NOW,
    )
    partial = replace(
        acknowledged,
        event_id="event-2",
        state=OrderState.PARTIALLY_FILLED,
        cumulative_filled_quantity=2,
        cumulative_average_fill_price=Decimal("100"),
        provider_timestamp=NOW + timedelta(seconds=1),
        observed_at=NOW + timedelta(seconds=1),
    )

    assert _can_follow([acknowledged], partial)
    assert not _can_follow(
        [partial],
        replace(
            partial,
            event_id="event-3",
            cumulative_filled_quantity=3,
            cumulative_average_fill_price=Decimal("60"),
        ),
    )
    assert not _can_follow(
        [partial],
        replace(partial, event_id="event-4", cumulative_average_fill_price=Decimal("101")),
    )
    filled = replace(
        partial,
        event_id="event-5",
        state=OrderState.FILLED,
        provider_timestamp=NOW + timedelta(seconds=2),
        observed_at=NOW + timedelta(seconds=2),
    )
    assert _can_follow(
        [filled],
        replace(
            filled,
            event_id="event-6",
            observed_at=NOW + timedelta(seconds=3),
        ),
    )
    assert not _can_follow(
        [filled],
        replace(
            filled,
            event_id="event-7",
            cumulative_average_fill_price=Decimal("101"),
        ),
    )
    with pytest.raises(ValueError, match="unfilled"):
        replace(acknowledged, cumulative_average_fill_price=Decimal("100"))
    with pytest.raises(ValueError, match="requires"):
        replace(partial, cumulative_average_fill_price=None)


def test_legacy_positive_fill_without_price_fails_closed() -> None:
    with pytest.raises(ValueError, match="broker event is invalid"):
        _decode_event(
            {
                "event_id": "event-1",
                "broker_order_id": "broker-order-1",
                "client_order_id": "client-order-1",
                "state": OrderState.PARTIALLY_FILLED,
                "cumulative_filled_quantity": 1,
                "provider_timestamp": NOW.isoformat(),
                "observed_at": NOW.isoformat(),
            }
        )
