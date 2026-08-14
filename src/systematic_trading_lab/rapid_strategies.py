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
