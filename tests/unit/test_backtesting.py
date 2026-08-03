from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from systematic_trading_lab.backtesting import (
    BacktestEngine,
    BacktestError,
    CostModel,
    SessionDecision,
)
from systematic_trading_lab.domain import OHLCVBar, Symbol
from systematic_trading_lab.strategies import (
    BuyAndHoldStrategy,
    CashStrategy,
    FixedWeightStrategy,
    TargetPosition,
)


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


def portfolio_bars() -> tuple[OHLCVBar, ...]:
    start = datetime(2025, 1, 6, tzinfo=UTC)
    return tuple(
        OHLCVBar(
            Symbol(symbol),
            start + timedelta(days=day),
            Decimal("100"),
            Decimal("110"),
            Decimal("90"),
            Decimal(str(100 + day)),
            100,
        )
        for day in range(3)
        for symbol in ("QQQ", "SPY")
    )


class FirstSessionPortfolio:
    strategy_id = "first-session-portfolio"
    version = "1"

    def __init__(self) -> None:
        self.history_lengths: list[dict[Symbol, int]] = []

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        timestamp = bars[0].timestamp
        assert all(item.timestamp <= timestamp for values in history.values() for item in values)
        self.history_lengths.append({symbol: len(values) for symbol, values in history.items()})
        if len(self.history_lengths) == 1:
            return (
                TargetPosition(Symbol("SPY"), Decimal("0.6"), "initial-allocation"),
                TargetPosition(Symbol("QQQ"), Decimal("0.4"), "initial-allocation"),
            )
        return ()


class StaticPortfolio:
    strategy_id = "static-portfolio"
    version = "1"

    def __init__(self, targets: Sequence[TargetPosition]) -> None:
        self.targets = targets

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        return self.targets


class RotatingPortfolio:
    strategy_id = "rotating-portfolio"
    version = "1"

    def __init__(self) -> None:
        self.sessions = 0

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        self.sessions += 1
        if self.sessions == 1:
            return (
                TargetPosition(Symbol("QQQ"), Decimal("0"), "initial-allocation"),
                TargetPosition(Symbol("SPY"), Decimal("1"), "initial-allocation"),
            )
        if self.sessions == 2:
            return (
                TargetPosition(Symbol("QQQ"), Decimal("1"), "rotation"),
                TargetPosition(Symbol("SPY"), Decimal("0"), "rotation"),
            )
        return ()


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


def test_portfolio_targets_use_complete_history_and_fill_next_session() -> None:
    strategy = FirstSessionPortfolio()
    result = BacktestEngine(
        Decimal("1000"), CostModel(slippage_bps=Decimal("0"), commission_bps=Decimal("0"))
    ).run_portfolio(portfolio_bars(), strategy)

    assert len(result.decisions) == 3
    assert all(isinstance(decision, SessionDecision) for decision in result.decisions)
    first = result.decisions[0]
    assert isinstance(first, SessionDecision)
    assert [target.symbol.value for target in first.targets] == ["QQQ", "SPY"]
    assert strategy.history_lengths == [
        {Symbol("QQQ"): 1, Symbol("SPY"): 1},
        {Symbol("QQQ"): 2, Symbol("SPY"): 2},
        {Symbol("QQQ"): 3, Symbol("SPY"): 3},
    ]
    assert len(result.trades) == 2
    assert {trade.symbol.value for trade in result.trades} == {"QQQ", "SPY"}
    assert all(
        trade.decision_timestamp == portfolio_bars()[0].timestamp
        and trade.fill_timestamp == portfolio_bars()[2].timestamp
        for trade in result.trades
    )
    assert len(result.equity_curve) == 3


@pytest.mark.parametrize(
    ("targets", "reason"),
    (
        (
            (
                TargetPosition(Symbol("QQQ"), Decimal("0.6"), "overweight"),
                TargetPosition(Symbol("SPY"), Decimal("0.6"), "overweight"),
            ),
            "portfolio-weight-out-of-range",
        ),
        (
            (
                TargetPosition(Symbol("SPY"), Decimal("0.5"), "duplicate"),
                TargetPosition(Symbol("SPY"), Decimal("0.5"), "duplicate"),
            ),
            "duplicate-portfolio-target",
        ),
        (
            (TargetPosition(Symbol("GLD"), Decimal("0.5"), "missing"),),
            "portfolio-symbols-differ",
        ),
    ),
)
def test_invalid_portfolio_target_sets_are_rejected_atomically(
    targets: Sequence[TargetPosition], reason: str
) -> None:
    result = BacktestEngine(Decimal("1000")).run_portfolio(
        portfolio_bars(), StaticPortfolio(targets)
    )

    assert result.trades == ()
    assert result.orders
    assert {event.reason for event in result.orders} == {reason}


def test_portfolio_backtest_rejects_incomplete_symbol_sessions() -> None:
    incomplete = tuple(
        bar
        for bar in portfolio_bars()
        if not (bar.symbol == Symbol("QQQ") and bar.timestamp == portfolio_bars()[-1].timestamp)
    )

    with pytest.raises(BacktestError, match="complete symbol sessions"):
        BacktestEngine(Decimal("1000")).run_portfolio(incomplete, FirstSessionPortfolio())


def test_portfolio_rebalance_sells_before_funding_buys() -> None:
    result = BacktestEngine(
        Decimal("1000"), CostModel(slippage_bps=Decimal("0"), commission_bps=Decimal("0"))
    ).run_portfolio(portfolio_bars(), RotatingPortfolio())

    assert [trade.symbol.value for trade in result.trades] == ["SPY", "SPY", "QQQ"]
    final_positions = dict(result.equity_curve[-1].positions)
    assert final_positions[Symbol("SPY")] == Decimal("0")
    assert final_positions[Symbol("QQQ")] > Decimal("0")
