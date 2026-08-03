from datetime import UTC, datetime, timedelta
from decimal import Decimal

from systematic_trading_lab.execution import ExecutionIntent
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.orders import OrderSide, build_order_delta

NOW = datetime(2026, 8, 3, 20, tzinfo=UTC)


def _intent() -> ExecutionIntent:
    return ExecutionIntent(
        idempotency_key="intent-1",
        strategy_id="strategy",
        strategy_version="1",
        symbol="SPY",
        decision_timestamp=NOW,
        target_weight=None,
        target_quantity=10,
        reason="rebalance",
        source_data_fingerprint=fingerprint({"data": 1}),
        configuration_fingerprint=fingerprint({"config": 1}),
        reference_price=Decimal("100"),
        expires_at=NOW + timedelta(minutes=5),
    )


def test_order_delta_is_deterministic_and_long_only() -> None:
    intent = _intent()
    buy = build_order_delta(intent, target_quantity=10, current_quantity=3, created_at=NOW)
    replay = build_order_delta(
        intent, target_quantity=10, current_quantity=3, created_at=NOW + timedelta(seconds=1)
    )
    sell = build_order_delta(intent, target_quantity=2, current_quantity=3, created_at=NOW)

    assert buy is not None and buy.side == OrderSide.BUY and buy.quantity == 7
    assert replay is not None and replay.client_order_id == buy.client_order_id
    assert sell is not None and sell.side == OrderSide.SELL and sell.quantity == 1
    assert build_order_delta(intent, target_quantity=3, current_quantity=3, created_at=NOW) is None
