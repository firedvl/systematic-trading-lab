"""Frozen, causal strategy contracts for Intraday Exposed 001.

The module deliberately contains no runner or registry integration.  It is the
small, research-only decision layer declared by the frozen plan.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

from .backtesting import PortfolioStrategy
from .calendar import expected_bar_timestamps
from .domain import OHLCVBar, Symbol, Timeframe
from .strategies import TargetPosition

_SYMBOLS = frozenset({"SPY", "QQQ"})
_NY = ZoneInfo("America/New_York")
_ZERO = Decimal("0")
_HALF = Decimal("0.5")
_ONE = Decimal("1")

# Values are copied from the frozen plan.  Fixed fields are deliberately part
# of the public parameter contract, so a configuration is fully explicit.
_SPEC: dict[str, dict[str, tuple[int, ...]]] = {
    "orb-time-exit": {"opening_bars": (1, 2, 3, 6), "exit_bar": (24, 48, 72)},
    "orb-trend-confirmed": {
        "opening_bars": (1, 2, 3, 6),
        "trend_window": (12, 24),
        "exit_bar": (48,),
    },
    "orb-volume-filtered": {
        "opening_bars": (1, 2, 3, 6),
        "volume_window": (6, 12),
        "volume_ratio_percent": (100, 125),
        "exit_bar": (48,),
    },
    "orb-opposite-range-exit": {"opening_bars": (1, 2, 3, 6)},
    "orb-trailing-exit": {"opening_bars": (1, 2, 3, 6), "trailing_bars": (3, 6)},
    "moving-average-crossover": {"fast_window": (3, 6, 12), "slow_window": (12, 18, 24)},
    "price-above-moving-average": {"window": (6, 12, 24, 36)},
    "multi-horizon-trend": {"fast_window": (3, 6, 12), "slow_window": (12, 24, 36)},
    "trend-pullback-continuation": {
        "trend_window": (12, 24, 36),
        "pullback_bars": (3, 6),
        "pullback_threshold_bps": (5, 10),
    },
    "absolute-momentum": {"lookback": (3, 6, 12, 24), "threshold_bps": (0, 5, 10)},
    "momentum-with-trend": {"lookback": (3, 6, 12, 24), "trend_window": (12, 24)},
    "relative-momentum": {"lookback": (3, 6, 12, 24), "threshold_bps": (0, 5)},
    "moving-average-deviation-reversion": {
        "window": (6, 12, 24),
        "entry_z_hundredths": (75, 100, 150),
        "exit_z_hundredths": (0, 25),
    },
    "short-term-reversal": {"lookback": (1, 2, 3, 6), "threshold_bps": (5, 10)},
    "pullback-in-trend": {
        "trend_window": (12, 24),
        "pullback_bars": (3, 6),
        "threshold_bps": (5, 10),
    },
    "volatility-normalized-pullback": {"window": (6, 12, 24), "entry_z_hundredths": (75, 100, 150)},
    "gap-continuation": {"gap_threshold_bps": (10, 20, 30, 50), "entry_delay_bars": (1, 3, 6)},
    "gap-fade": {"gap_threshold_bps": (10, 20, 30, 50), "entry_delay_bars": (1, 3, 6)},
    "gap-continuation-with-trend": {"gap_threshold_bps": (20, 50), "trend_window": (12, 24)},
    "gap-fade-with-trend": {"gap_threshold_bps": (20, 50), "trend_window": (12, 24)},
    "windowed-momentum": {
        "window_start_bar": (0, 12, 30, 54),
        "window_end_bar": (11, 29, 53, 71),
        "lookback": (3, 6),
        "threshold_bps": (0, 5),
    },
    "rolling-range-breakout": {"lookback": (3, 6, 12, 24), "threshold_half_ranges": (1, 2, 3)},
    "average-range-breakout": {"window": (6, 12, 24), "threshold_half_ranges": (1, 2)},
    "momentum-volatility-filter": {
        "lookback": (6, 12),
        "volatility_window": (12, 24),
        "maximum_average_absolute_return_bps": (10, 20),
    },
    "trend-volatility-filter": {
        "trend_window": (12, 24),
        "volatility_window": (12, 24),
        "maximum_average_absolute_return_bps": (10, 20),
    },
    "cross-asset-momentum-confirmation": {"lookback": (3, 6, 12, 24), "threshold_bps": (0, 5)},
    "cross-asset-trend-confirmation": {"window": (6, 12, 24, 36), "threshold_bps": (0, 5)},
    "single-horizon-relative-strength": {"lookback": (3, 6, 12, 24), "threshold_bps": (0, 5, 10)},
    "dual-horizon-relative-strength": {
        "fast_lookback": (3, 6, 12),
        "slow_lookback": (12, 24, 36),
        "threshold_bps": (0, 5),
    },
    "completed-session-channel-breakout": {
        "entry_lookback": (3, 6, 12, 24),
        "exit_lookback": (2, 3, 6),
    },
    "price-above-cumulative-vwap": {"threshold_bps": (0, 5, 10, 20), "minimum_bars": (3, 6, 12)},
    "cumulative-vwap-reversion": {
        "entry_threshold_bps": (10, 20, 30),
        "exit_threshold_bps": (0, 5),
    },
    "opening-range-plus-market-trend": {"opening_bars": (2, 3, 6), "trend_window": (12, 24)},
    "momentum-plus-volatility-filter": {"lookback": (6, 12, 24), "volatility_window": (12, 24)},
    "pullback-plus-long-trend": {"trend_window": (12, 24, 36), "pullback_bars": (3, 6)},
}
_PAIRS = {
    "moving-average-crossover": {
        (3, 12),
        (3, 18),
        (3, 24),
        (6, 12),
        (6, 18),
        (6, 24),
        (12, 18),
        (12, 24),
    },
    "multi-horizon-trend": {
        (3, 12),
        (3, 24),
        (3, 36),
        (6, 12),
        (6, 24),
        (6, 36),
        (12, 24),
        (12, 36),
    },
    "dual-horizon-relative-strength": {
        (3, 12),
        (3, 24),
        (3, 36),
        (6, 12),
        (6, 24),
        (6, 36),
        (12, 24),
        (12, 36),
    },
}


def _session(bar: OHLCVBar) -> date:
    return bar.timestamp.astimezone(_NY).date()


def _return(current: OHLCVBar, past: OHLCVBar) -> Decimal:
    return current.close / past.close - _ONE


def _mean(items: Sequence[Decimal]) -> Decimal:
    return sum(items, _ZERO) / Decimal(len(items))


@dataclass(frozen=True)
class IntradayExposedStrategy:
    symbols: tuple[Symbol, ...]
    strategy_id: str
    parameters: Mapping[str, int]
    evaluation_start: datetime | None = None
    version: str = "1"

    def on_session(
        self, bars: Sequence[OHLCVBar], history: Mapping[Symbol, Sequence[OHLCVBar]]
    ) -> Sequence[TargetPosition]:
        current, session_history = self._check_slice(bars, history)
        if self.evaluation_start is not None and bars[0].timestamp < self.evaluation_start:
            return self._targets({}, "before-evaluation-start")
        active = self._signals(current, session_history, history)
        if self.strategy_id in {
            "relative-momentum",
            "single-horizon-relative-strength",
            "dual-horizon-relative-strength",
        }:
            positive = {symbol: score for symbol, score in active.items() if score > _ZERO}
            if not positive:
                return self._targets({}, "relative-strength-cash")
            winner = max(sorted(positive, key=lambda item: item.value), key=positive.__getitem__)
            if len(session_history[winner]) > 1:
                prior_session = {symbol: items[:-1] for symbol, items in session_history.items()}
                prior_history = {symbol: tuple(history[symbol][:-1]) for symbol in self.symbols}
                prior_active = self._signals(
                    {symbol: prior_session[symbol][-1] for symbol in self.symbols},
                    prior_session,
                    prior_history,
                )
                prior_positive = {
                    symbol: score for symbol, score in prior_active.items() if score > _ZERO
                }
                if prior_positive:
                    prior_winner = max(
                        sorted(prior_positive, key=lambda item: item.value),
                        key=prior_positive.__getitem__,
                    )
                    if prior_winner != winner:
                        return self._targets({}, "relative-strength-rotation-flat-bridge")
            return self._targets({winner: _ONE}, "relative-strength-rotation")
        return self._targets(
            {symbol: _HALF for symbol, value in active.items() if value > _ZERO}, self.strategy_id
        )

    def _targets(
        self, weights: Mapping[Symbol, Decimal], reason: str
    ) -> tuple[TargetPosition, ...]:
        return tuple(
            TargetPosition(symbol, weights.get(symbol, _ZERO), reason) for symbol in self.symbols
        )

    def _check_slice(
        self, bars: Sequence[OHLCVBar], history: Mapping[Symbol, Sequence[OHLCVBar]]
    ) -> tuple[dict[Symbol, OHLCVBar], dict[Symbol, tuple[OHLCVBar, ...]]]:
        current = {bar.symbol: bar for bar in bars}
        if (
            len(bars) != 2
            or set(current) != set(self.symbols)
            or set(history) != set(self.symbols)
            or len({bar.timestamp for bar in bars}) != 1
        ):
            raise ValueError("intraday exposed strategy requires one complete SPY/QQQ slice")
        timestamps = [tuple(bar.timestamp for bar in history[symbol]) for symbol in self.symbols]
        if (
            not timestamps[0]
            or timestamps[0] != timestamps[1]
            or any(history[symbol][-1] != current[symbol] for symbol in self.symbols)
        ):
            raise ValueError("intraday exposed strategy requires aligned completed histories")
        day = _session(bars[0])
        session_history = {
            symbol: tuple(bar for bar in history[symbol] if _session(bar) == day)
            for symbol in self.symbols
        }
        expected = expected_bar_timestamps(
            datetime.combine(day, time.min, UTC), bars[0].timestamp, Timeframe.FIVE_MINUTES
        )
        if (
            not expected
            or tuple(bar.timestamp for bar in session_history[self.symbols[0]]) != expected
        ):
            raise ValueError("intraday exposed strategy requires full completed session slices")
        return current, session_history

    def _signals(
        self,
        current: Mapping[Symbol, OHLCVBar],
        session: Mapping[Symbol, tuple[OHLCVBar, ...]],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> dict[Symbol, Decimal]:
        result: dict[Symbol, Decimal] = {}
        for symbol in self.symbols:
            bars = session[symbol]
            all_bars = history[symbol]
            i = len(bars) - 1
            p = self.parameters
            close = current[symbol].close

            def enough(n: int, items: tuple[OHLCVBar, ...] = bars) -> bool:
                return len(items) > n

            def momentum(
                n: int,
                item: OHLCVBar = current[symbol],
                items: tuple[OHLCVBar, ...] = bars,
            ) -> Decimal | None:
                return _return(item, items[-n - 1]) if enough(n, items) else None

            def ma(n: int, items: tuple[OHLCVBar, ...] = bars) -> Decimal | None:
                return _mean([bar.close for bar in items[-n:]]) if len(items) >= n else None

            def trend(n: int, item_close: Decimal = close) -> bool:
                return (value := ma(n)) is not None and item_close > value

            def avg_abs_return(n: int, items: tuple[OHLCVBar, ...] = bars) -> Decimal | None:
                if len(items) <= n:
                    return None
                return _mean(
                    [
                        abs(_return(items[j], items[j - 1]))
                        for j in range(len(items) - n, len(items))
                    ]
                )

            value = _ZERO
            if self.strategy_id.startswith("orb-"):
                opening = p["opening_bars"]
                if len(bars) > opening:
                    high, low = (
                        max(bar.high for bar in bars[:opening]),
                        min(bar.low for bar in bars[:opening]),
                    )
                    active = False
                    for index in range(opening, len(bars)):
                        item = bars[index]
                        entry = item.close > high
                        if self.strategy_id == "orb-trend-confirmed":
                            window = p["trend_window"]
                            entry = (
                                entry
                                and index + 1 >= window
                                and item.close
                                > _mean([bar.close for bar in bars[index - window + 1 : index + 1]])
                            )
                        elif self.strategy_id == "orb-volume-filtered":
                            window = p["volume_window"]
                            prior = bars[max(0, index - window) : index]
                            entry = (
                                entry
                                and len(prior) == window
                                and all(bar.volume > 0 for bar in prior)
                                and Decimal(item.volume) * Decimal(100)
                                >= _mean([Decimal(bar.volume) for bar in prior])
                                * p["volume_ratio_percent"]
                            )
                        if not active and entry:
                            active = True
                        if self.strategy_id in {
                            "orb-time-exit",
                            "orb-trend-confirmed",
                            "orb-volume-filtered",
                        }:
                            active = active and index < p["exit_bar"]
                        elif self.strategy_id == "orb-opposite-range-exit" and active:
                            active = item.close >= low
                        elif self.strategy_id == "orb-trailing-exit" and active:
                            trailing = bars[max(opening, index - p["trailing_bars"]) : index]
                            if trailing and item.close < min(bar.low for bar in trailing):
                                active = False
                    value = _ONE if active else _ZERO
            elif self.strategy_id in {"moving-average-crossover", "multi-horizon-trend"}:
                fast, slow = ma(p["fast_window"]), ma(p["slow_window"])
                value = (
                    _ONE
                    if fast is not None
                    and slow is not None
                    and fast > slow
                    and (self.strategy_id != "multi-horizon-trend" or close > slow)
                    else _ZERO
                )
            elif self.strategy_id == "price-above-moving-average":
                value = _ONE if trend(p["window"]) else _ZERO
            elif self.strategy_id in {
                "trend-pullback-continuation",
                "pullback-in-trend",
                "pullback-plus-long-trend",
            }:
                tw, pb = p["trend_window"], p["pullback_bars"]
                threshold = Decimal(
                    p.get("pullback_threshold_bps", p.get("threshold_bps", 0))
                ) / Decimal(10000)
                value = (
                    _ONE
                    if trend(tw) and (m := momentum(pb)) is not None and m <= -threshold
                    else _ZERO
                )
            elif self.strategy_id in {
                "absolute-momentum",
                "momentum-with-trend",
                "windowed-momentum",
                "momentum-volatility-filter",
                "momentum-plus-volatility-filter",
            }:
                m = momentum(p["lookback"])
                threshold = Decimal(p.get("threshold_bps", 0)) / Decimal(10000)
                value = _ONE if m is not None and m > threshold else _ZERO
                if self.strategy_id == "momentum-with-trend":
                    value *= Decimal(trend(p["trend_window"]))
                if self.strategy_id == "windowed-momentum":
                    value *= Decimal(p["window_start_bar"] <= i <= p["window_end_bar"])
                if "volatility_window" in p:
                    average = avg_abs_return(p["volatility_window"])
                    limit = Decimal(p.get("maximum_average_absolute_return_bps", 20)) / Decimal(
                        10000
                    )
                    value *= Decimal(average is not None and average <= limit)
            elif self.strategy_id == "short-term-reversal":
                m = momentum(p["lookback"])
                value = (
                    _ONE
                    if m is not None and m <= -Decimal(p["threshold_bps"]) / Decimal(10000)
                    else _ZERO
                )
            elif self.strategy_id in {
                "moving-average-deviation-reversion",
                "volatility-normalized-pullback",
            }:
                window = p["window"]
                if self.strategy_id == "moving-average-deviation-reversion":
                    active = False
                    entry_threshold = Decimal(p["entry_z_hundredths"]) / Decimal(100)
                    exit_ = Decimal(p["exit_z_hundredths"]) / Decimal(100)
                    for index in range(window - 1, len(bars)):
                        recent = bars[index - window + 1 : index + 1]
                        rolling_mean = _mean([bar.close for bar in recent])
                        deviations = [bar.close / rolling_mean - _ONE for bar in recent]
                        scale = _mean([abs(item) for item in deviations])
                        deviation = bars[index].close / rolling_mean - _ONE
                        if not active and scale > _ZERO and deviation <= -entry_threshold * scale:
                            active = True
                        elif active and deviation >= -exit_ * scale:
                            active = False
                    value = _ONE if active else _ZERO
                else:
                    current_mean = ma(window)
                    if current_mean is not None:
                        deviations = [bar.close / current_mean - _ONE for bar in bars[-window:]]
                        scale = _mean([abs(item) for item in deviations])
                        threshold = Decimal(p["entry_z_hundredths"]) / Decimal(100)
                        value = (
                            _ONE
                            if scale > _ZERO and (close / current_mean - _ONE) <= -threshold * scale
                            else _ZERO
                        )
            elif self.strategy_id in {
                "gap-continuation",
                "gap-fade",
                "gap-continuation-with-trend",
                "gap-fade-with-trend",
            }:
                prior_close_bar = next(
                    (
                        bar
                        for bar in reversed(all_bars[: -len(bars)])
                        if _session(bar) != _session(current[symbol])
                    ),
                    None,
                )
                if prior_close_bar is not None:
                    gap = bars[0].open / prior_close_bar.close - _ONE
                    threshold = Decimal(p["gap_threshold_bps"]) / Decimal(10000)
                    delay = p.get("entry_delay_bars", 0)
                    good = (
                        gap >= threshold
                        if "continuation" in self.strategy_id
                        else gap <= -threshold
                    )
                    value = _ONE if i >= delay and good else _ZERO
                    if "with-trend" in self.strategy_id:
                        value *= Decimal(trend(p["trend_window"]))
            elif self.strategy_id in {"rolling-range-breakout", "average-range-breakout"}:
                n = p["lookback"] if self.strategy_id == "rolling-range-breakout" else p["window"]
                recent = bars[-n:] if len(bars) >= n else ()
                if recent:
                    avg_range = _mean([bar.high - bar.low for bar in recent])
                    reference = (
                        max(bar.high for bar in recent[:-1]) if len(recent) > 1 else recent[0].high
                    )
                    value = (
                        _ONE
                        if close > reference + Decimal(p["threshold_half_ranges"]) * avg_range / 2
                        else _ZERO
                    )
            elif self.strategy_id in {"trend-volatility-filter"}:
                average = avg_abs_return(p["volatility_window"])
                value = (
                    _ONE
                    if trend(p["trend_window"])
                    and average is not None
                    and average
                    <= Decimal(p["maximum_average_absolute_return_bps"]) / Decimal(10000)
                    else _ZERO
                )
            elif self.strategy_id in {
                "cross-asset-momentum-confirmation",
                "cross-asset-trend-confirmation",
            }:
                other = next(item for item in self.symbols if item != symbol)
                if self.strategy_id.endswith("momentum-confirmation"):
                    own, peer = (
                        momentum(p["lookback"]),
                        _return(current[other], session[other][-p["lookback"] - 1])
                        if len(session[other]) > p["lookback"]
                        else None,
                    )
                    value = (
                        _ONE
                        if own is not None
                        and peer is not None
                        and own > Decimal(p["threshold_bps"]) / Decimal(10000)
                        and peer > _ZERO
                        else _ZERO
                    )
                else:
                    peer_mean = (
                        _mean([bar.close for bar in session[other][-p["window"] :]])
                        if len(session[other]) >= p["window"]
                        else None
                    )
                    value = (
                        _ONE
                        if trend(p["window"])
                        and peer_mean is not None
                        and current[other].close / peer_mean - _ONE
                        > Decimal(p["threshold_bps"]) / Decimal(10000)
                        else _ZERO
                    )
            elif self.strategy_id in {
                "relative-momentum",
                "single-horizon-relative-strength",
                "dual-horizon-relative-strength",
            }:
                if self.strategy_id == "dual-horizon-relative-strength":
                    a, b = momentum(p["fast_lookback"]), momentum(p["slow_lookback"])
                    value = (
                        (a + b)
                        if a is not None and b is not None and a > _ZERO and b > _ZERO
                        else _ZERO
                    )
                else:
                    value = momentum(p["lookback"]) or _ZERO
                value = value if value > Decimal(p["threshold_bps"]) / Decimal(10000) else _ZERO
            elif self.strategy_id == "completed-session-channel-breakout":
                active = False
                for index, item in enumerate(bars):
                    if not active and index >= p["entry_lookback"]:
                        prior = bars[index - p["entry_lookback"] : index]
                        active = item.close > max(bar.high for bar in prior)
                    elif active and index >= p["exit_lookback"]:
                        prior = bars[index - p["exit_lookback"] : index]
                        active = item.close >= min(bar.low for bar in prior)
                value = _ONE if active else _ZERO
            elif self.strategy_id.startswith("price-above-cumulative-vwap"):
                if all(bar.volume > 0 for bar in bars):
                    vwap = sum((bar.close * bar.volume for bar in bars), _ZERO) / sum(
                        bar.volume for bar in bars
                    )
                    value = (
                        _ONE
                        if len(bars) >= p["minimum_bars"]
                        and close / vwap - _ONE > Decimal(p["threshold_bps"]) / Decimal(10000)
                        else _ZERO
                    )
            elif self.strategy_id == "cumulative-vwap-reversion":
                if all(bar.volume > 0 for bar in bars):
                    active = False
                    cumulative_value = _ZERO
                    cumulative_volume = 0
                    entry_threshold = Decimal(p["entry_threshold_bps"]) / Decimal(10000)
                    exit_ = Decimal(p["exit_threshold_bps"]) / Decimal(10000)
                    for item in bars:
                        cumulative_value += item.close * item.volume
                        cumulative_volume += item.volume
                        deviation = item.close / (cumulative_value / cumulative_volume) - _ONE
                        if not active and deviation <= -entry_threshold:
                            active = True
                        elif active and deviation >= -exit_:
                            active = False
                    value = _ONE if active else _ZERO
            elif self.strategy_id == "opening-range-plus-market-trend":
                opening = p["opening_bars"]
                spy = next(item for item in self.symbols if item.value == "SPY")
                value = (
                    _ONE
                    if len(bars) > opening
                    and close > max(bar.high for bar in bars[:opening])
                    and len(session[spy]) >= p["trend_window"]
                    and current[spy].close
                    > _mean([bar.close for bar in session[spy][-p["trend_window"] :]])
                    else _ZERO
                )
            result[symbol] = value
        return result


def build_intraday_exposed_strategy(
    strategy_id: str,
    symbols: Sequence[Symbol],
    parameters: Mapping[str, object],
    *,
    evaluation_start: datetime | None = None,
) -> PortfolioStrategy:
    """Build exactly one frozen Exposed 001 contract; reject configuration drift."""
    spec = _SPEC.get(strategy_id)
    if spec is None:
        raise ValueError(f"unknown intraday exposed strategy: {strategy_id}")
    canonical = tuple(sorted(symbols, key=lambda symbol: symbol.value))
    if len(canonical) != 2 or {symbol.value for symbol in canonical} != _SYMBOLS:
        raise ValueError("intraday exposed strategies require exactly SPY and QQQ")
    if set(parameters) != set(spec) or any(
        type(parameters[name]) is not int or parameters[name] not in spec[name] for name in spec
    ):
        raise ValueError(f"parameters differ for {strategy_id}")
    if strategy_id == "windowed-momentum" and (
        parameters["window_start_bar"],
        parameters["window_end_bar"],
    ) not in {(0, 11), (12, 29), (30, 53), (54, 71)}:
        raise ValueError("parameters differ for windowed-momentum")
    if (
        strategy_id in _PAIRS
        and (
            parameters[
                "fast_window"
                if strategy_id != "dual-horizon-relative-strength"
                else "fast_lookback"
            ],
            parameters[
                "slow_window"
                if strategy_id != "dual-horizon-relative-strength"
                else "slow_lookback"
            ],
        )
        not in _PAIRS[strategy_id]
    ):
        raise ValueError(f"parameters differ for {strategy_id}")
    if evaluation_start is not None and (
        evaluation_start.tzinfo is None
        or evaluation_start.utcoffset() != UTC.utcoffset(evaluation_start)
    ):
        raise ValueError("evaluation_start must be UTC-aware")
    return IntradayExposedStrategy(
        canonical,
        strategy_id,
        {name: cast(int, parameters[name]) for name in spec},
        evaluation_start,
    )
