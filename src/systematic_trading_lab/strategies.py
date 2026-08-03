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


@dataclass(frozen=True)
class RelativeStrengthPortfolioStrategy:
    symbols: tuple[Symbol, ...]
    lookback: int = 126
    rebalance_every: int = 21
    selection_count: int = 3
    strategy_id: str = "relative-strength-portfolio"
    version: str = "1"

    def __post_init__(self) -> None:
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("relative-strength strategy requires unique symbols")
        if self.lookback < 1 or self.rebalance_every < 1:
            raise ValueError("lookback and rebalance interval must be positive")
        if not 1 <= self.selection_count <= len(self.symbols):
            raise ValueError("selection count must fit the strategy universe")

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        expected = set(self.symbols)
        if {bar.symbol for bar in bars} != expected or set(history) != expected:
            raise ValueError("relative-strength session universe differs")
        lengths = {len(history[symbol]) for symbol in self.symbols}
        if len(lengths) != 1:
            raise ValueError("relative-strength history lengths differ")
        session_count = next(iter(lengths))
        if session_count <= self.lookback:
            return ()
        if (session_count - self.lookback - 1) % self.rebalance_every:
            return ()

        current = {bar.symbol: bar for bar in bars}
        ranked = sorted(
            (
                (
                    current[symbol].close / history[symbol][-self.lookback - 1].close
                    - Decimal("1"),
                    symbol,
                )
                for symbol in self.symbols
            ),
            key=lambda item: (-item[0], item[1].value),
        )
        selected = {
            symbol for score, symbol in ranked[: self.selection_count] if score > Decimal("0")
        }
        active_weight = Decimal("1") / Decimal(self.selection_count)
        return tuple(
            TargetPosition(
                symbol,
                active_weight if symbol in selected else Decimal("0"),
                "positive-relative-strength" if symbol in selected else "cash-filter",
            )
            for symbol in sorted(self.symbols, key=lambda item: item.value)
        )


@dataclass(frozen=True)
class RiskManagedMomentumPortfolioStrategy:
    symbols: tuple[Symbol, ...]
    lookback: int = 126
    volatility_window: int = 63
    rebalance_every: int = 5
    strategy_id: str = "risk-managed-momentum-portfolio"
    version: str = "1"

    def __post_init__(self) -> None:
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("risk-managed momentum requires unique symbols")
        if self.lookback < 1 or self.volatility_window < 2 or self.rebalance_every < 1:
            raise ValueError("risk-managed momentum parameters are invalid")

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        expected = set(self.symbols)
        if {bar.symbol for bar in bars} != expected or set(history) != expected:
            raise ValueError("risk-managed momentum session universe differs")
        lengths = {len(history[symbol]) for symbol in self.symbols}
        if len(lengths) != 1:
            raise ValueError("risk-managed momentum history lengths differ")
        session_count = next(iter(lengths))
        warmup = max(self.lookback, self.volatility_window)
        if session_count <= warmup:
            return ()
        if (session_count - warmup - 1) % self.rebalance_every:
            return ()

        current = {bar.symbol: bar for bar in bars}
        eligible = tuple(
            symbol
            for symbol in self.symbols
            if current[symbol].close > history[symbol][-self.lookback - 1].close
        )
        inverse_volatility: dict[Symbol, Decimal] = {}
        for symbol in eligible:
            closes = tuple(bar.close for bar in history[symbol][-self.volatility_window - 1 :])
            returns = tuple(
                current_close / previous_close - Decimal("1")
                for previous_close, current_close in zip(closes, closes[1:], strict=False)
            )
            mean = sum(returns, Decimal("0")) / Decimal(len(returns))
            variance = sum(((value - mean) ** 2 for value in returns), Decimal("0")) / Decimal(
                len(returns) - 1
            )
            if variance <= 0:
                raise ValueError("risk-managed momentum requires positive volatility")
            inverse_volatility[symbol] = Decimal("1") / variance.sqrt()

        weights: dict[Symbol, Decimal] = {}
        remaining = sorted(inverse_volatility, key=lambda symbol: symbol.value)
        available = Decimal("1")
        cap = Decimal("0.4")
        while remaining:
            inverse_total = sum((inverse_volatility[symbol] for symbol in remaining), Decimal("0"))
            provisional = {
                symbol: available * inverse_volatility[symbol] / inverse_total
                for symbol in remaining
            }
            capped = tuple(symbol for symbol in remaining if provisional[symbol] > cap)
            if not capped:
                weights.update(provisional)
                break
            for symbol in capped:
                weights[symbol] = cap
                remaining.remove(symbol)
                available -= cap

        return tuple(
            TargetPosition(
                symbol,
                weights.get(symbol, Decimal("0")),
                "positive-momentum-inverse-volatility" if symbol in weights else "cash-filter",
            )
            for symbol in sorted(self.symbols, key=lambda item: item.value)
        )
