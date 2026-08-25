"""Deterministic 22-session synthetic fixture for Program 002 mechanics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from .calendar import expected_bar_timestamps, expected_sessions
from .domain import OHLCVBar, Symbol, Timeframe

_NEW_YORK = ZoneInfo("America/New_York")
_SYMBOLS = tuple(
    Symbol(value)
    for value in (
        "IWM",
        "MDY",
        "SPY",
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
_NORMAL_DAY = date(2025, 11, 26)
_EARLY_DAY = date(2025, 11, 28)
_LATEST_CLOSE = {
    "SPY": Decimal("100.2"),
    "IWM": Decimal("101.2"),
    "MDY": Decimal("101.2"),
    "XLB": Decimal("100.7"),
    "XLE": Decimal("100.1"),
    "XLF": Decimal("100"),
}
_MORNING_VOLUME = {
    "IWM": 1_200_000,
    "MDY": 1_200_000,
    "XLB": 1_300_000,
    "XLE": 1_500_000,
    "XLF": 1_500_000,
}


@dataclass(frozen=True)
class SyntheticProgram002Fixture:
    bars: tuple[OHLCVBar, ...]
    prior_days: tuple[date, ...]
    normal_day: date
    early_close_day: date


def build_synthetic_program_002_fixture() -> SyntheticProgram002Fixture:
    sessions = expected_sessions(
        datetime(2025, 10, 1, tzinfo=UTC), datetime.combine(_EARLY_DAY, time.max, UTC)
    )[-22:]
    if sessions[-2:] != (_NORMAL_DAY, _EARLY_DAY):
        raise AssertionError("Program 002 synthetic calendar changed")
    bars: list[OHLCVBar] = []
    for session_day in sessions:
        timestamps = expected_bar_timestamps(
            datetime.combine(session_day, time.min, UTC),
            datetime.combine(session_day, time.max, UTC),
            Timeframe.FIVE_MINUTES,
        )
        for symbol in _SYMBOLS:
            for timestamp in timestamps:
                bars.append(_bar(symbol, timestamp, session_day))
    return SyntheticProgram002Fixture(tuple(bars), sessions[:20], _NORMAL_DAY, _EARLY_DAY)


def _bar(symbol: Symbol, timestamp: datetime, session_day: date) -> OHLCVBar:
    local_clock = timestamp.astimezone(_NEW_YORK).time()
    price = Decimal("100")
    close = (
        _LATEST_CLOSE.get(symbol.value, price)
        if session_day in {_NORMAL_DAY, _EARLY_DAY} and local_clock == time(11, 25)
        else price
    )
    if session_day == _NORMAL_DAY and local_clock in {
        time(13, 35),
        time(13, 40),
        time(13, 45),
        time(15, 35),
        time(15, 40),
        time(15, 45),
    }:
        price = Decimal("100.5") if symbol.value == "SPY" else Decimal("101")
        close = price
    volume = 1_000_000
    if session_day in {_NORMAL_DAY, _EARLY_DAY} and local_clock < time(11, 30):
        volume = _MORNING_VOLUME.get(symbol.value, volume)
    return OHLCVBar(
        symbol,
        timestamp,
        price,
        max(price, close),
        min(price, close),
        close,
        volume,
    )
