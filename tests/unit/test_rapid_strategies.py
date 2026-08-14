from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from systematic_trading_lab.backtesting import PortfolioStrategy
from systematic_trading_lab.domain import OHLCVBar, Symbol
from systematic_trading_lab.rapid_strategies import (
    ChannelBreakoutPortfolioStrategy,
    DrawdownAwareAllocationPortfolioStrategy,
    DualMomentumPortfolioStrategy,
    MovingAverageStatePortfolioStrategy,
    MultiHorizonMomentumPortfolioStrategy,
    RegimeAllocationPortfolioStrategy,
    TrendPullbackPortfolioStrategy,
)
from systematic_trading_lab.strategies import TargetPosition
from systematic_trading_lab.strategy_registry import run_registered_strategy


def _history(closes: tuple[str, ...], symbol_value: str = "SPY") -> tuple[OHLCVBar, ...]:
    symbol = Symbol(symbol_value)
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


def _portfolio_decision(
    strategy: PortfolioStrategy, closes: Mapping[str, tuple[str, ...]]
) -> tuple[TargetPosition, ...]:
    history = {
        Symbol(symbol): _history(values, symbol) for symbol, values in sorted(closes.items())
    }
    return tuple(
        strategy.on_session(
            tuple(series[-1] for series in history.values()),
            history,
        )
    )


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


def test_multi_horizon_momentum_selects_top_n_only_on_state_change() -> None:
    symbols = tuple(Symbol(value) for value in ("SPY", "QQQ", "IWM", "TLT", "GLD"))
    strategy = MultiHorizonMomentumPortfolioStrategy(
        symbols, short_lookback=2, long_lookback=4, selection_count=2, rebalance_every=1
    )
    closes = {
        "SPY": ("100", "101", "102", "103", "110"),
        "QQQ": ("100", "100", "101", "102", "108"),
        "IWM": ("110", "108", "105", "103", "100"),
        "TLT": ("105", "104", "103", "102", "101"),
        "GLD": ("105", "104", "103", "102", "101"),
    }

    decision = _portfolio_decision(strategy, closes)

    assert {target.symbol.value: target.weight for target in decision} == {
        "GLD": Decimal("0"),
        "IWM": Decimal("0"),
        "QQQ": Decimal("0.5"),
        "SPY": Decimal("0.5"),
        "TLT": Decimal("0"),
    }
    assert _portfolio_decision(strategy, closes) == ()


def test_dual_momentum_falls_back_to_strongest_positive_defense() -> None:
    symbols = tuple(Symbol(value) for value in ("SPY", "QQQ", "IWM", "TLT", "GLD"))
    strategy = DualMomentumPortfolioStrategy(
        symbols, short_lookback=2, long_lookback=4, selection_count=2, rebalance_every=1
    )

    decision = _portfolio_decision(
        strategy,
        {
            "SPY": ("110", "108", "105", "103", "100"),
            "QQQ": ("110", "108", "105", "103", "100"),
            "IWM": ("110", "108", "105", "103", "100"),
            "TLT": ("100", "101", "102", "103", "105"),
            "GLD": ("100", "101", "103", "106", "110"),
        },
    )

    assert {target.symbol.value: target.weight for target in decision}["GLD"] == Decimal("1")
    assert sum((target.weight for target in decision), Decimal("0")) == Decimal("1")


def test_regime_allocation_uses_risk_and_defensive_sleeves() -> None:
    symbols = tuple(Symbol(value) for value in ("SPY", "QQQ", "IWM", "TLT", "GLD"))
    closes = {
        "SPY": ("100", "101", "103", "104"),
        "QQQ": ("100", "101", "102", "103"),
        "IWM": ("100", "101", "102", "103"),
        "TLT": ("100", "101", "102", "103"),
        "GLD": ("100", "101", "102", "103"),
    }

    risk_on = _portfolio_decision(
        RegimeAllocationPortfolioStrategy(
            symbols,
            trend_window=3,
            volatility_window=2,
            volatility_limit_percent=100,
            rebalance_every=1,
        ),
        closes,
    )
    risk_off = _portfolio_decision(
        RegimeAllocationPortfolioStrategy(
            symbols,
            trend_window=3,
            volatility_window=2,
            volatility_limit_percent=1,
            rebalance_every=1,
        ),
        closes,
    )

    assert {target.symbol.value for target in risk_on if target.weight > 0} == {
        "SPY",
        "QQQ",
        "IWM",
    }
    assert {target.symbol.value: target.weight for target in risk_off if target.weight > 0} == {
        "GLD": Decimal("0.5"),
        "TLT": Decimal("0.5"),
    }


def test_drawdown_aware_allocation_moves_to_cash() -> None:
    symbols = tuple(Symbol(value) for value in ("SPY", "QQQ", "IWM", "TLT", "GLD"))
    strategy = DrawdownAwareAllocationPortfolioStrategy(
        symbols, lookback=4, trigger_percent=10, rebalance_every=1
    )

    decision = _portfolio_decision(
        strategy,
        {
            "SPY": ("100", "120", "115", "110", "100"),
            "QQQ": ("100", "100", "100", "100", "100"),
            "IWM": ("100", "100", "100", "100", "100"),
            "TLT": ("100", "100", "100", "100", "100"),
            "GLD": ("100", "100", "100", "100", "100"),
        },
    )

    assert decision
    assert all(target.weight == 0 for target in decision)


@pytest.mark.parametrize(
    "strategy",
    (
        lambda symbols: DualMomentumPortfolioStrategy(symbols),
        lambda symbols: RegimeAllocationPortfolioStrategy(symbols),
        lambda symbols: DrawdownAwareAllocationPortfolioStrategy(symbols),
    ),
)
def test_fixed_universe_strategies_reject_duplicate_symbols(
    strategy: Callable[[tuple[Symbol, ...]], object],
) -> None:
    duplicate = tuple(Symbol(value) for value in ("SPY", "QQQ", "IWM", "GLD", "GLD"))

    with pytest.raises(ValueError, match="fixed ETF universe"):
        strategy(duplicate)


def test_buy_and_hold_selects_requested_symbol() -> None:
    bars = tuple(
        sorted(
            (bar for symbol in ("GLD", "SPY") for bar in _history(("100", "101", "102"), symbol)),
            key=lambda bar: (bar.timestamp, bar.symbol.value),
        )
    )

    result = run_registered_strategy(
        "buy-and-hold",
        bars,
        Decimal("1000"),
        parameters={"symbol_number": 2},
    )

    assert result.trades[0].symbol == Symbol("SPY")

    with pytest.raises(ValueError, match="exceeds the strategy universe"):
        run_registered_strategy(
            "buy-and-hold",
            bars,
            Decimal("1000"),
            parameters={"symbol_number": 3},
        )


@pytest.mark.parametrize(
    "strategy",
    (
        lambda: MovingAverageStatePortfolioStrategy((Symbol("SPY"),), window=1),
        lambda: TrendPullbackPortfolioStrategy((Symbol("SPY"),), trend_window=5, pullback_window=5),
        lambda: ChannelBreakoutPortfolioStrategy((Symbol("SPY"),), entry_window=5, exit_window=5),
        lambda: MultiHorizonMomentumPortfolioStrategy(
            (Symbol("SPY"),), short_lookback=5, long_lookback=5
        ),
        lambda: DrawdownAwareAllocationPortfolioStrategy(
            tuple(Symbol(value) for value in ("SPY", "QQQ", "IWM", "TLT", "GLD")),
            trigger_percent=101,
        ),
    ),
)
def test_state_transition_strategies_reject_invalid_windows(
    strategy: Callable[[], object],
) -> None:
    with pytest.raises(ValueError):
        strategy()
