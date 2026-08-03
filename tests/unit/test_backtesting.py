from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from systematic_trading_lab.backtesting import BacktestEngine, BacktestError, CostModel
from systematic_trading_lab.domain import OHLCVBar, Symbol
from systematic_trading_lab.strategies import BuyAndHoldStrategy, CashStrategy, FixedWeightStrategy


def bars() -> tuple[OHLCVBar, ...]:
    start = datetime(2025, 1, 6, tzinfo=UTC)
    return tuple(
        OHLCVBar(
            Symbol("SPY"),
            start + timedelta(days=index),
            Decimal(str(opening)),
            Decimal(str(max(opening, close) + 5)),
            Decimal(str(min(opening, close) - 5)),
            Decimal(str(close)),
            100,
        )
        for index, (opening, close) in enumerate(((100, 105), (110, 115), (120, 130)))
    )


def test_cash_baseline_has_no_trades_and_buy_hold_fills_next_bar() -> None:
    engine = BacktestEngine(
        Decimal("1000"), CostModel(slippage_bps=Decimal("0"), commission_bps=Decimal("0"))
    )
    cash = engine.run(bars(), CashStrategy())
    result = engine.run(bars(), BuyAndHoldStrategy())

    assert cash.metrics.trade_count == 0
    assert cash.metrics.total_return == Decimal("0")
    assert cash.metrics.annualized_volatility == Decimal("0")
    assert cash.metrics.sharpe_ratio is None
    assert cash.metrics.average_gross_exposure == Decimal("0")
    assert cash.metrics.top_5_session_profit_share is None
    assert result.metrics.trade_count == 1
    assert result.trades[0].decision_timestamp < result.trades[0].fill_timestamp
    assert abs(result.metrics.total_return - Decimal("2") / Decimal("11")) < Decimal("1e-25")
    assert result.metrics.annualized_volatility > 0
    assert result.metrics.sharpe_ratio is not None
    assert result.metrics.max_gross_exposure > 0
    assert result.metrics.top_5_session_profit_share == Decimal("1")
    assert result.metrics.top_instrument_profit_share == Decimal("1")
    assert result.metrics.up_regime_sessions == 2
    assert result.metrics.down_regime_sessions == 0


def test_higher_costs_do_not_improve_fixed_transactions() -> None:
    free = BacktestEngine(
        Decimal("1000"), CostModel(slippage_bps=Decimal("0"), commission_bps=Decimal("0"))
    ).run(bars(), BuyAndHoldStrategy())
    costly = BacktestEngine(
        Decimal("1000"), CostModel(slippage_bps=Decimal("10"), commission_bps=Decimal("10"))
    ).run(bars(), BuyAndHoldStrategy())
    assert costly.metrics.total_return < free.metrics.total_return


def test_duplicate_bars_and_final_bar_orders_fail_closed() -> None:
    engine = BacktestEngine(Decimal("1000"))
    with pytest.raises(BacktestError, match="duplicate"):
        engine.run(bars() + (bars()[0],), CashStrategy())
    result = engine.run((bars()[0],), BuyAndHoldStrategy())
    assert result.trades == ()
    assert result.orders[-1].reason == "no-future-fill"


def test_delayed_fill_waits_for_the_configured_symbol_bar() -> None:
    result = BacktestEngine(Decimal("1000"), fill_delay_bars=2).run(
        bars(), FixedWeightStrategy((Symbol("SPY"),), rebalance_every=1)
    )
    assert result.trades[0].fill_timestamp == bars()[2].timestamp
    assert any(event.reason == "pending-order-exists" for event in result.orders)


def test_metrics_use_complete_sessions_instead_of_symbol_processing_order() -> None:
    start = datetime(2025, 1, 6, tzinfo=UTC)
    source = tuple(
        OHLCVBar(
            Symbol(symbol),
            start + timedelta(days=day),
            Decimal("100"),
            Decimal("150"),
            Decimal("50"),
            close,
            100,
        )
        for day, closes in enumerate(
            (
                (Decimal("100"), Decimal("100")),
                (Decimal("100"), Decimal("100")),
                (Decimal("50"), Decimal("150")),
            )
        )
        for symbol, close in zip(("AAA", "ZZZ"), closes, strict=True)
    )
    result = BacktestEngine(
        Decimal("1000"), CostModel(slippage_bps=Decimal("0"), commission_bps=Decimal("0"))
    ).run(source, FixedWeightStrategy((Symbol("AAA"), Symbol("ZZZ")), rebalance_every=10))

    assert result.metrics.total_return == Decimal("0")
    assert result.metrics.max_drawdown == Decimal("0")
