"""Baseline strategies that emit targets, never broker orders."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from .domain import OHLCVBar, Symbol


@dataclass(frozen=True)
class TargetPosition:
    symbol: Symbol
    weight: Decimal
    reason: str


class CashStrategy:
    strategy_id = "cash"
    version = "1"

    def on_bar(self, bar: OHLCVBar, history: Sequence[OHLCVBar]) -> Sequence[TargetPosition]:
        return ()


@dataclass
class BuyAndHoldStrategy:
    strategy_id: str = "buy-and-hold"
    version: str = "1"
    _seen: set[Symbol] = field(default_factory=set, init=False, repr=False)

    def on_bar(self, bar: OHLCVBar, history: Sequence[OHLCVBar]) -> Sequence[TargetPosition]:
        if bar.symbol in self._seen:
            return ()
        self._seen.add(bar.symbol)
        return (TargetPosition(bar.symbol, Decimal("1"), "initial-entry"),)


@dataclass(frozen=True)
class FixedWeightStrategy:
    symbols: tuple[Symbol, ...]
    rebalance_every: int = 5
    weights: Mapping[Symbol, Decimal] | None = None
    strategy_id: str = "fixed-weight"
    version: str = "1"

    def __post_init__(self) -> None:
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("fixed-weight strategy requires unique symbols")
        if self.rebalance_every < 1:
            raise ValueError("rebalance_every must be positive")
        configured = self.weights or {
            symbol: Decimal("1") / Decimal(str(len(self.symbols))) for symbol in self.symbols
        }
        if set(configured) != set(self.symbols) or any(
            weight < 0 for weight in configured.values()
        ):
            raise ValueError("weights must cover symbols and be non-negative")
        if sum(configured.values(), Decimal("0")) > Decimal("1"):
            raise ValueError("weights must not exceed full exposure")
        object.__setattr__(self, "weights", dict(configured))

    def on_bar(self, bar: OHLCVBar, history: Sequence[OHLCVBar]) -> Sequence[TargetPosition]:
        if bar.symbol not in self.symbols:
            return ()
        if len(history) != 1 and (len(history) - 1) % self.rebalance_every:
            return ()
        assert self.weights is not None
        return (TargetPosition(bar.symbol, self.weights[bar.symbol], "periodic-rebalance"),)


@dataclass(frozen=True)
class MovingAverageTrendStrategy:
    window: int = 20
    target_weight: Decimal = Decimal("1")
    strategy_id: str = "moving-average-trend"
    version: str = "1"

    def __post_init__(self) -> None:
        if self.window < 2:
            raise ValueError("moving-average window must be at least two bars")
        if not Decimal("0") < self.target_weight <= Decimal("1"):
            raise ValueError("moving-average target weight must be in (0, 1]")

    def on_bar(self, bar: OHLCVBar, history: Sequence[OHLCVBar]) -> Sequence[TargetPosition]:
        if len(history) < self.window:
            return ()
        average = sum((item.close for item in history[-self.window :]), Decimal("0")) / self.window
        weight = self.target_weight if bar.close > average else Decimal("0")
        return (TargetPosition(bar.symbol, weight, "close-vs-moving-average"),)


@dataclass(frozen=True)
class TimeSeriesMomentumStrategy:
    lookback: int = 20
    target_weight: Decimal = Decimal("1")
    strategy_id: str = "time-series-momentum"
    version: str = "1"

    def __post_init__(self) -> None:
        if self.lookback < 1:
            raise ValueError("momentum lookback must be positive")
        if not Decimal("0") < self.target_weight <= Decimal("1"):
            raise ValueError("momentum target weight must be in (0, 1]")

    def on_bar(self, bar: OHLCVBar, history: Sequence[OHLCVBar]) -> Sequence[TargetPosition]:
        if len(history) <= self.lookback:
            return ()
        weight = (
            self.target_weight if bar.close > history[-self.lookback - 1].close else Decimal("0")
        )
        return (TargetPosition(bar.symbol, weight, "close-vs-lookback"),)
