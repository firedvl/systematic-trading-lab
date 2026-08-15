"""Rapid-only strategy implementations and evaluation wrappers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .backtesting import PortfolioStrategy, Strategy
from .domain import OHLCVBar, Symbol
from .strategies import TargetPosition


def _complete_session(
    name: str,
    symbols: tuple[Symbol, ...],
    bars: Sequence[OHLCVBar],
    history: Mapping[Symbol, Sequence[OHLCVBar]],
) -> tuple[int, dict[Symbol, OHLCVBar]]:
    expected = set(symbols)
    if {bar.symbol for bar in bars} != expected or set(history) != expected:
        raise ValueError(f"{name} session universe differs")
    lengths = {len(history[symbol]) for symbol in symbols}
    if len(lengths) != 1:
        raise ValueError(f"{name} history lengths differ")
    return next(iter(lengths)), {bar.symbol: bar for bar in bars}


def _sleeve_targets(
    symbols: tuple[Symbol, ...], active: frozenset[Symbol], reason: str
) -> tuple[TargetPosition, ...]:
    weight = Decimal("1") / Decimal(len(symbols))
    return tuple(
        TargetPosition(symbol, weight if symbol in active else Decimal("0"), reason)
        for symbol in sorted(symbols, key=lambda item: item.value)
    )


def _weighted_targets(
    symbols: tuple[Symbol, ...], weights: Mapping[Symbol, Decimal], reason: str
) -> tuple[TargetPosition, ...]:
    return tuple(
        TargetPosition(symbol, weights.get(symbol, Decimal("0")), reason)
        for symbol in sorted(symbols, key=lambda item: item.value)
    )


def _fixed_roles(symbols: tuple[Symbol, ...]) -> tuple[tuple[Symbol, ...], tuple[Symbol, ...]]:
    if len(symbols) != 5 or {symbol.value for symbol in symbols} != {
        "SPY",
        "QQQ",
        "IWM",
        "TLT",
        "GLD",
    }:
        raise ValueError("strategy requires the fixed ETF universe")
    risk = tuple(symbol for symbol in symbols if symbol.value in {"SPY", "QQQ", "IWM"})
    defensive = tuple(symbol for symbol in symbols if symbol.value in {"TLT", "GLD"})
    return risk, defensive


def _multi_horizon_score(
    symbol: Symbol,
    current: Mapping[Symbol, OHLCVBar],
    history: Mapping[Symbol, Sequence[OHLCVBar]],
    short_lookback: int,
    long_lookback: int,
) -> Decimal | None:
    short_return = current[symbol].close / history[symbol][-short_lookback - 1].close - Decimal("1")
    long_return = current[symbol].close / history[symbol][-long_lookback - 1].close - Decimal("1")
    return short_return + long_return if short_return > 0 and long_return > 0 else None


def _reevaluate(session_count: int, warmup: int, rebalance_every: int) -> bool:
    return session_count > warmup and not (session_count - warmup - 1) % rebalance_every


@dataclass
class MovingAverageStatePortfolioStrategy:
    """Change fixed sleeves only when their moving-average state changes."""

    symbols: tuple[Symbol, ...]
    window: int = 40
    strategy_id: str = "moving-average-state-portfolio"
    version: str = "1"
    _active: frozenset[Symbol] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("moving-average state strategy requires unique symbols")
        if self.window < 2:
            raise ValueError("moving-average state window must be at least two bars")

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        session_count, current = _complete_session(
            "moving-average state", self.symbols, bars, history
        )
        if session_count < self.window:
            return ()
        active = frozenset(
            symbol
            for symbol in self.symbols
            if current[symbol].close
            > sum((item.close for item in history[symbol][-self.window :]), Decimal("0"))
            / self.window
        )
        if active == self._active:
            return ()
        self._active = active
        return _sleeve_targets(self.symbols, active, "moving-average-state-transition")


@dataclass
class TrendPullbackPortfolioStrategy:
    """Buy a short pullback inside a longer uptrend and exit on recovery."""

    symbols: tuple[Symbol, ...]
    trend_window: int = 63
    pullback_window: int = 5
    strategy_id: str = "trend-pullback-portfolio"
    version: str = "1"
    _active: frozenset[Symbol] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("trend pullback strategy requires unique symbols")
        if self.trend_window < 2 or not 1 < self.pullback_window < self.trend_window:
            raise ValueError("pullback window must be between one and the trend window")

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        session_count, current = _complete_session("trend pullback", self.symbols, bars, history)
        if session_count < self.trend_window:
            return ()
        active = set(self._active or ())
        for symbol in self.symbols:
            close = current[symbol].close
            trend_average = (
                sum((item.close for item in history[symbol][-self.trend_window :]), Decimal("0"))
                / self.trend_window
            )
            pullback_average = (
                sum((item.close for item in history[symbol][-self.pullback_window :]), Decimal("0"))
                / self.pullback_window
            )
            if symbol in active:
                if close <= trend_average or close >= pullback_average:
                    active.remove(symbol)
            elif trend_average < close < pullback_average:
                active.add(symbol)
        next_active = frozenset(active)
        if next_active == self._active:
            return ()
        self._active = next_active
        return _sleeve_targets(self.symbols, next_active, "trend-pullback-state-transition")


@dataclass
class ChannelBreakoutPortfolioStrategy:
    """Enter on a close above prior highs and exit below prior lows."""

    symbols: tuple[Symbol, ...]
    entry_window: int = 20
    exit_window: int = 10
    strategy_id: str = "channel-breakout-portfolio"
    version: str = "1"
    _active: frozenset[Symbol] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("channel breakout strategy requires unique symbols")
        if self.entry_window < 2 or not 1 <= self.exit_window < self.entry_window:
            raise ValueError("exit window must be positive and shorter than the entry window")

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        session_count, current = _complete_session("channel breakout", self.symbols, bars, history)
        if session_count <= self.entry_window:
            return ()
        active = set(self._active or ())
        for symbol in self.symbols:
            close = current[symbol].close
            if symbol in active:
                prior = history[symbol][-self.exit_window - 1 : -1]
                if close < min(item.low for item in prior):
                    active.remove(symbol)
            else:
                prior = history[symbol][-self.entry_window - 1 : -1]
                if close > max(item.high for item in prior):
                    active.add(symbol)
        next_active = frozenset(active)
        if next_active == self._active:
            return ()
        self._active = next_active
        return _sleeve_targets(self.symbols, next_active, "channel-breakout-state-transition")


@dataclass
class MultiHorizonMomentumPortfolioStrategy:
    """Hold an equal-weight top-N subset only when both momentum horizons are positive."""

    symbols: tuple[Symbol, ...]
    short_lookback: int = 20
    long_lookback: int = 126
    selection_count: int = 3
    rebalance_every: int = 5
    strategy_id: str = "multi-horizon-momentum-portfolio"
    version: str = "1"
    _active: frozenset[Symbol] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("multi-horizon momentum requires unique symbols")
        if not 1 <= self.short_lookback < self.long_lookback:
            raise ValueError("short lookback must be positive and shorter than long lookback")
        if not 1 <= self.selection_count <= len(self.symbols) or self.rebalance_every < 1:
            raise ValueError("selection count and rebalance interval are invalid")

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        session_count, current = _complete_session(
            "multi-horizon momentum", self.symbols, bars, history
        )
        if not _reevaluate(session_count, self.long_lookback, self.rebalance_every):
            return ()
        ranked = sorted(
            (
                (score, symbol)
                for symbol in self.symbols
                if (
                    score := _multi_horizon_score(
                        symbol,
                        current,
                        history,
                        self.short_lookback,
                        self.long_lookback,
                    )
                )
                is not None
            ),
            key=lambda item: (-item[0], item[1].value),
        )
        active = frozenset(symbol for _score, symbol in ranked[: self.selection_count])
        if active == self._active:
            return ()
        self._active = active
        weight = Decimal("1") / Decimal(self.selection_count)
        return _weighted_targets(
            self.symbols,
            {symbol: weight for symbol in active},
            "positive-multi-horizon-top-n",
        )


@dataclass
class DualMomentumPortfolioStrategy:
    """Rank positive risk assets, then fall back to positive defense or cash."""

    symbols: tuple[Symbol, ...]
    short_lookback: int = 20
    long_lookback: int = 126
    selection_count: int = 2
    rebalance_every: int = 5
    strategy_id: str = "dual-momentum-portfolio"
    version: str = "1"
    defensive_selection_count: int = 1
    _active: frozenset[Symbol] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        risk, defensive = _fixed_roles(self.symbols)
        if not 1 <= self.short_lookback < self.long_lookback:
            raise ValueError("short lookback must be positive and shorter than long lookback")
        if not 1 <= self.selection_count <= len(risk) or self.rebalance_every < 1:
            raise ValueError("selection count and rebalance interval are invalid")
        if not 1 <= self.defensive_selection_count <= len(defensive):
            raise ValueError("defensive selection count is invalid")

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        session_count, current = _complete_session("dual momentum", self.symbols, bars, history)
        if not _reevaluate(session_count, self.long_lookback, self.rebalance_every):
            return ()
        risk, defensive = _fixed_roles(self.symbols)
        ranked_risk = sorted(
            (
                (score, symbol)
                for symbol in risk
                if (
                    score := _multi_horizon_score(
                        symbol,
                        current,
                        history,
                        self.short_lookback,
                        self.long_lookback,
                    )
                )
                is not None
            ),
            key=lambda item: (-item[0], item[1].value),
        )
        active = frozenset(symbol for _score, symbol in ranked_risk[: self.selection_count])
        defensive_mode = not active
        if defensive_mode:
            ranked_defensive = sorted(
                (
                    (score, symbol)
                    for symbol in defensive
                    if (
                        score := _multi_horizon_score(
                            symbol,
                            current,
                            history,
                            self.short_lookback,
                            self.long_lookback,
                        )
                    )
                    is not None
                ),
                key=lambda item: (-item[0], item[1].value),
            )
            active = frozenset(
                symbol for _score, symbol in ranked_defensive[: self.defensive_selection_count]
            )
        if active == self._active:
            return ()
        self._active = active
        weight = (
            Decimal("1") / Decimal(len(active))
            if defensive_mode and active
            else Decimal("1") / Decimal(self.selection_count)
        )
        return _weighted_targets(
            self.symbols,
            {symbol: weight for symbol in active},
            "dual-momentum-defensive" if defensive_mode else "dual-momentum-risk",
        )


@dataclass
class RegimeAllocationPortfolioStrategy:
    """Switch fixed sleeves using SPY trend and realized volatility."""

    symbols: tuple[Symbol, ...]
    trend_window: int = 126
    volatility_window: int = 20
    volatility_limit_percent: int = 20
    rebalance_every: int = 5
    strategy_id: str = "regime-allocation-portfolio"
    version: str = "1"
    _active: frozenset[Symbol] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        _fixed_roles(self.symbols)
        if self.trend_window < 2 or self.volatility_window < 2:
            raise ValueError("trend and volatility windows must be at least two")
        if not 1 <= self.volatility_limit_percent <= 100 or self.rebalance_every < 1:
            raise ValueError("volatility limit and rebalance interval are invalid")

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        session_count, current = _complete_session("regime allocation", self.symbols, bars, history)
        warmup = max(self.trend_window, self.volatility_window + 1)
        if not _reevaluate(session_count, warmup, self.rebalance_every):
            return ()
        risk, defensive = _fixed_roles(self.symbols)
        spy = next(symbol for symbol in risk if symbol.value == "SPY")
        spy_closes = tuple(bar.close for bar in history[spy][-self.volatility_window - 1 :])
        returns = tuple(
            current_close / prior_close - Decimal("1")
            for prior_close, current_close in zip(spy_closes, spy_closes[1:], strict=False)
        )
        mean = sum(returns, Decimal("0")) / Decimal(len(returns))
        variance = sum(((value - mean) ** 2 for value in returns), Decimal("0")) / Decimal(
            len(returns) - 1
        )
        if variance <= 0:
            raise ValueError("regime allocation requires positive SPY volatility")
        annualized_volatility = variance.sqrt() * Decimal("252").sqrt()
        spy_average = (
            sum((bar.close for bar in history[spy][-self.trend_window :]), Decimal("0"))
            / self.trend_window
        )
        risk_on = current[spy].close > spy_average and annualized_volatility <= Decimal(
            self.volatility_limit_percent
        ) / Decimal("100")
        if risk_on:
            active = frozenset(risk)
            weights = {symbol: Decimal("1") / Decimal(len(risk)) for symbol in active}
        else:
            active = frozenset(
                symbol
                for symbol in defensive
                if current[symbol].close
                > sum((bar.close for bar in history[symbol][-self.trend_window :]), Decimal("0"))
                / self.trend_window
            )
            weights = {symbol: Decimal("0.5") for symbol in active}
        if active == self._active:
            return ()
        self._active = active
        return _weighted_targets(
            self.symbols,
            weights,
            "trend-volatility-risk-on" if risk_on else "trend-volatility-risk-off",
        )


@dataclass
class DrawdownAwareAllocationPortfolioStrategy:
    """Hold equal risk sleeves until SPY crosses a trailing drawdown threshold."""

    symbols: tuple[Symbol, ...]
    lookback: int = 126
    trigger_percent: int = 10
    rebalance_every: int = 5
    strategy_id: str = "drawdown-aware-allocation-portfolio"
    version: str = "1"
    _active: frozenset[Symbol] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        _fixed_roles(self.symbols)
        if self.lookback < 2 or not 1 <= self.trigger_percent <= 100:
            raise ValueError("drawdown lookback or trigger is invalid")
        if self.rebalance_every < 1:
            raise ValueError("rebalance interval must be positive")

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        session_count, current = _complete_session(
            "drawdown-aware allocation", self.symbols, bars, history
        )
        if not _reevaluate(session_count, self.lookback, self.rebalance_every):
            return ()
        risk, _defensive = _fixed_roles(self.symbols)
        spy = next(symbol for symbol in risk if symbol.value == "SPY")
        peak = max(bar.close for bar in history[spy][-self.lookback :])
        drawdown = Decimal("1") - current[spy].close / peak
        active = (
            frozenset(risk)
            if drawdown < Decimal(self.trigger_percent) / Decimal("100")
            else frozenset()
        )
        if active == self._active:
            return ()
        self._active = active
        return _weighted_targets(
            self.symbols,
            {symbol: Decimal("1") / Decimal(len(risk)) for symbol in active},
            "drawdown-risk-on" if active else "drawdown-cash",
        )


@dataclass
class StartBoundStrategy:
    strategy: Strategy
    start: datetime

    @property
    def strategy_id(self) -> str:
        return self.strategy.strategy_id

    @property
    def version(self) -> str:
        return self.strategy.version

    def on_bar(self, bar: OHLCVBar, history: Sequence[OHLCVBar]) -> Sequence[TargetPosition]:
        return () if bar.timestamp < self.start else self.strategy.on_bar(bar, history)


@dataclass
class StartBoundPortfolioStrategy:
    strategy: PortfolioStrategy
    start: datetime

    @property
    def strategy_id(self) -> str:
        return self.strategy.strategy_id

    @property
    def version(self) -> str:
        return self.strategy.version

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        return () if bars[0].timestamp < self.start else self.strategy.on_session(bars, history)
