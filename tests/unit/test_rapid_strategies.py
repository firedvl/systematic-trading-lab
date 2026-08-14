from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from systematic_trading_lab.backtesting import PortfolioStrategy
from systematic_trading_lab.domain import OHLCVBar, Symbol
from systematic_trading_lab.rapid_strategies import (
    ChannelBreakoutPortfolioStrategy,
    MovingAverageStatePortfolioStrategy,
    TrendPullbackPortfolioStrategy,
)
from systematic_trading_lab.strategies import TargetPosition


def _history(closes: tuple[str, ...]) -> tuple[OHLCVBar, ...]:
    symbol = Symbol("SPY")
    start = datetime(2025, 1, 6, tzinfo=UTC)
    return tuple(
        OHLCVBar(
            symbol,
            start + timedelta(days=index),
            Decimal(close),
            Decimal(close),
            Decimal(close),
            Decimal(close),
            100,
        )
        for index, close in enumerate(closes)
    )


def _decision(
    strategy: PortfolioStrategy, history: tuple[OHLCVBar, ...]
) -> tuple[TargetPosition, ...]:
    symbol = Symbol("SPY")
    return tuple(strategy.on_session((history[-1],), {symbol: history}))


def test_moving_average_trades_only_on_state_changes() -> None:
    strategy = MovingAverageStatePortfolioStrategy((Symbol("SPY"),), window=3)

    assert _decision(strategy, _history(("100", "101"))) == ()
    assert _decision(strategy, _history(("100", "101", "103")))[0].weight == Decimal("1")
    assert _decision(strategy, _history(("100", "101", "103", "104"))) == ()
    assert _decision(strategy, _history(("100", "101", "103", "104", "90")))[0].weight == 0


def test_trend_pullback_enters_and_exits_on_recovery() -> None:
    strategy = TrendPullbackPortfolioStrategy((Symbol("SPY"),), trend_window=4, pullback_window=2)

    assert _decision(strategy, _history(("100", "102", "104"))) == ()
    assert _decision(strategy, _history(("100", "102", "104", "103")))[0].weight == Decimal("1")
    assert _decision(strategy, _history(("100", "102", "104", "103", "105")))[0].weight == 0


def test_channel_breakout_enters_holds_and_exits() -> None:
    strategy = ChannelBreakoutPortfolioStrategy((Symbol("SPY"),), entry_window=3, exit_window=2)

    assert _decision(strategy, _history(("100", "101", "102"))) == ()
    assert _decision(strategy, _history(("100", "101", "102", "105")))[0].weight == Decimal("1")
    assert _decision(strategy, _history(("100", "101", "102", "105", "104"))) == ()
    assert _decision(strategy, _history(("100", "101", "102", "105", "104", "90")))[0].weight == 0


@pytest.mark.parametrize(
    "strategy",
    (
        lambda: MovingAverageStatePortfolioStrategy((Symbol("SPY"),), window=1),
        lambda: TrendPullbackPortfolioStrategy((Symbol("SPY"),), trend_window=5, pullback_window=5),
        lambda: ChannelBreakoutPortfolioStrategy((Symbol("SPY"),), entry_window=5, exit_window=5),
    ),
)
def test_state_transition_strategies_reject_invalid_windows(
    strategy: Callable[[], object],
) -> None:
    with pytest.raises(ValueError):
        strategy()
