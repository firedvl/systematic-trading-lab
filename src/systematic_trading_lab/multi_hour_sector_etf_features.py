"""Causal Program 002 half-hour features and deterministic selection traces."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from statistics import median
from types import MappingProxyType
from zoneinfo import ZoneInfo

from .calendar import expected_bar_timestamps, expected_sessions
from .domain import OHLCVBar, Symbol, Timeframe
from .multi_hour_sector_etf_plan import Program002Configuration

_NEW_YORK = ZoneInfo("America/New_York")
_SPY = Symbol("SPY")
_RANKING_SYMBOLS = tuple(
    Symbol(value)
    for value in (
        "IWM",
        "MDY",
        "XLB",
        "XLE",
        "XLF",
        "XLI",
        "XLK",
        "XLP",
        "XLRE",
        "XLU",
        "XLV",
        "XLY",
    )
)
_ALL_SYMBOLS = (*_RANKING_SYMBOLS, _SPY)
_DECISION_TIME = time(11, 30)
_MORNING_BAR_COUNT = 24
_PRIOR_SESSION_COUNT = 20
_ZERO = Decimal("0")


@dataclass(frozen=True)
class HalfHourBar:
    symbol: Symbol
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True)
class RankedFeature:
    symbol: Symbol
    lookback_return: Decimal
    spy_return: Decimal
    residual_return: Decimal
    same_clock_relative_volume: Decimal
    prior_morning_volume_mean: Decimal
    prior_median_dollar_volume: Decimal
    active: bool
    rank: int


@dataclass(frozen=True)
class SelectionTrace:
    configuration_id: str
    strategy_id: str
    family_id: str
    session_day: date
    decision_timestamp: datetime
    latest_source_bar_open: datetime
    lookback_30m_bars: int
    hold_30m_bars: int
    ordered_features: tuple[RankedFeature, ...]
    selected_symbols: tuple[Symbol, ...]
    inactive_reason: str | None

    def __post_init__(self) -> None:
        if _SPY in self.selected_symbols or len(self.selected_symbols) > 3:
            raise ValueError("Program 002 selection trace contains an invalid candidate set")


def aggregate_30_minute_bars(source: Sequence[OHLCVBar]) -> tuple[HalfHourBar, ...]:
    """Aggregate one complete symbol/session from six consecutive five-minute bars."""
    if not source or len(source) % 6:
        raise ValueError("Program 002 half-hour aggregation requires complete six-bar buckets")
    ordered = tuple(source)
    symbol = ordered[0].symbol
    for earlier, later in zip(ordered, ordered[1:], strict=False):
        if earlier.symbol != symbol or later.symbol != symbol:
            raise ValueError("Program 002 half-hour aggregation requires one symbol")
        if later.timestamp != earlier.timestamp + timedelta(minutes=5):
            raise ValueError("Program 002 source bars must be consecutive")
    result: list[HalfHourBar] = []
    for offset in range(0, len(ordered), 6):
        bucket = ordered[offset : offset + 6]
        first = bucket[0].timestamp.astimezone(_NEW_YORK)
        if first.minute not in {0, 30}:
            raise ValueError("Program 002 half-hour buckets must align to the XNYS open")
        result.append(
            HalfHourBar(
                symbol,
                bucket[-1].timestamp + timedelta(minutes=5),
                bucket[0].open,
                max(bar.high for bar in bucket),
                min(bar.low for bar in bucket),
                bucket[-1].close,
                sum(bar.volume for bar in bucket),
            )
        )
    return tuple(result)


def build_selection_trace(
    bars: Sequence[OHLCVBar],
    session_day: date,
    configuration: Program002Configuration,
) -> SelectionTrace:
    """Build the frozen 11:30 decision from one current and twenty prior sessions."""
    sessions = _validated_sessions(bars)
    if session_day not in sessions:
        raise ValueError("Program 002 decision session is missing")
    ordered_days = tuple(sorted(sessions))
    index = ordered_days.index(session_day)
    if index < _PRIOR_SESSION_COUNT:
        raise ValueError("Program 002 decision requires twenty prior complete sessions")
    prior_days = ordered_days[index - _PRIOR_SESSION_COUNT : index]
    current = sessions[session_day]
    session_grid = tuple(current[_SPY][index].timestamp for index in range(len(current[_SPY])))
    decision_timestamp = _clock(session_day, _DECISION_TIME)
    latest_source = decision_timestamp - timedelta(minutes=5)
    early_close = len(session_grid) != 78

    raw_features: list[
        tuple[Symbol, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, bool]
    ] = []
    spy_half_hours = aggregate_30_minute_bars(current[_SPY])
    latest_index = _bucket_index(spy_half_hours, decision_timestamp)
    base_index = latest_index - configuration.lookback_30m_bars
    if base_index < 0:
        raise ValueError("Program 002 lookback history is incomplete")
    spy_return = spy_half_hours[latest_index].close / spy_half_hours[base_index].close - 1
    for symbol in _RANKING_SYMBOLS:
        half_hours = aggregate_30_minute_bars(current[symbol])
        if half_hours[latest_index].timestamp != decision_timestamp:
            raise ValueError("Program 002 synchronized decision bucket differs")
        lookback_return = half_hours[latest_index].close / half_hours[base_index].close - 1
        residual = lookback_return - spy_return
        current_volume = sum(bar.volume for bar in current[symbol][:_MORNING_BAR_COUNT])
        prior_volumes = tuple(
            sum(bar.volume for bar in sessions[day][symbol][:_MORNING_BAR_COUNT])
            for day in prior_days
        )
        prior_mean = Decimal(sum(prior_volumes)) / _PRIOR_SESSION_COUNT
        if prior_mean <= 0:
            raise ValueError("Program 002 relative-volume denominator must be positive")
        relative_volume = Decimal(current_volume) / prior_mean
        dollar_volumes = tuple(
            bar.close * bar.volume for day in prior_days for bar in sessions[day][symbol]
        )
        capacity_median = Decimal(median(dollar_volumes))
        active = _active(configuration.family_id, residual, relative_volume) and not early_close
        raw_features.append(
            (
                symbol,
                lookback_return,
                spy_return,
                residual,
                relative_volume,
                prior_mean,
                capacity_median,
                active,
            )
        )
    reverse = configuration.family_id == "sector-relative-continuation-v1"
    ordered = sorted(
        raw_features,
        key=lambda item: ((-item[3] if reverse else item[3]), item[0].value),
    )
    features = tuple(RankedFeature(*item, rank) for rank, item in enumerate(ordered, start=1))
    selected = tuple(feature.symbol for feature in features if feature.active)[:3]
    return SelectionTrace(
        configuration.configuration_id,
        configuration.strategy_id,
        configuration.family_id,
        session_day,
        decision_timestamp,
        latest_source,
        configuration.lookback_30m_bars,
        configuration.hold_30m_bars,
        features,
        selected,
        "early-close-session" if early_close else ("no-active-symbol" if not selected else None),
    )


def _validated_sessions(
    bars: Sequence[OHLCVBar],
) -> Mapping[date, Mapping[Symbol, tuple[OHLCVBar, ...]]]:
    if not bars:
        raise ValueError("Program 002 feature input is empty")
    grouped: dict[date, dict[Symbol, list[OHLCVBar]]] = defaultdict(lambda: defaultdict(list))
    seen: set[tuple[Symbol, datetime]] = set()
    for bar in bars:
        key = (bar.symbol, bar.timestamp)
        if key in seen:
            raise ValueError("Program 002 feature input contains a duplicate bar")
        seen.add(key)
        if bar.symbol not in _ALL_SYMBOLS:
            raise ValueError("Program 002 feature input contains an unexpected symbol")
        grouped[bar.timestamp.astimezone(_NEW_YORK).date()][bar.symbol].append(bar)
    first, last = min(grouped), max(grouped)
    calendar_days = expected_sessions(
        datetime.combine(first, time.min, UTC), datetime.combine(last, time.max, UTC)
    )
    if tuple(sorted(grouped)) != calendar_days:
        raise ValueError("Program 002 feature input omits an XNYS session")
    result: dict[date, Mapping[Symbol, tuple[OHLCVBar, ...]]] = {}
    for day in calendar_days:
        expected = expected_bar_timestamps(
            datetime.combine(day, time.min, UTC),
            datetime.combine(day, time.max, UTC),
            Timeframe.FIVE_MINUTES,
        )
        if set(grouped[day]) != set(_ALL_SYMBOLS):
            raise ValueError("Program 002 feature input must contain all thirteen symbols")
        by_symbol: dict[Symbol, tuple[OHLCVBar, ...]] = {}
        for symbol in _ALL_SYMBOLS:
            source = tuple(sorted(grouped[day][symbol], key=lambda bar: bar.timestamp))
            if tuple(bar.timestamp for bar in source) != expected:
                raise ValueError("Program 002 feature input has a missing or unexpected bar")
            by_symbol[symbol] = source
        result[day] = MappingProxyType(by_symbol)
    return MappingProxyType(result)


def _bucket_index(bars: Sequence[HalfHourBar], timestamp: datetime) -> int:
    try:
        return tuple(bar.timestamp for bar in bars).index(timestamp)
    except ValueError as error:
        raise ValueError("Program 002 decision bucket is missing") from error


def _active(family_id: str, residual: Decimal, relative_volume: Decimal) -> bool:
    if family_id == "sector-relative-continuation-v1":
        return residual > _ZERO and relative_volume >= Decimal("1.2")
    if family_id == "sector-relative-reversal-v1":
        return residual <= Decimal("-0.001") and relative_volume >= Decimal("1.5")
    raise ValueError("Program 002 family identity differs")


def _clock(day: date, value: time) -> datetime:
    return datetime.combine(day, value, _NEW_YORK).astimezone(UTC)
