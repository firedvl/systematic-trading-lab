"""Causal SPY-only strategy for Intraday Event Opening Breakout 001."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from .domain import OHLCVBar, Symbol
from .strategies import TargetPosition

_NEW_YORK = ZoneInfo("America/New_York")
_QQQ, _SPY = Symbol("QQQ"), Symbol("SPY")
_SYMBOLS = (_QQQ, _SPY)
_ZERO, _HALF, _BPS = Decimal("0"), Decimal("0.5"), Decimal("10000")
_OPENING_RANGE_END, _MONITOR_START, _MONITOR_END, _EXIT_INDEX = 5, 6, 11, 29


@dataclass(frozen=True)
class EventOpeningBreakoutSignal:
    """Deterministic completed-bar signal detail for campaign event evidence."""

    session_day: date
    observed_bar_index: int
    opening_range_high: Decimal | None
    breakout_threshold: Decimal | None
    breakout_bar_index: int | None
    active: bool


@dataclass(frozen=True)
class ScheduledEventSpyOpeningBreakoutStrategy:
    """Target SPY once after its own close-confirmed opening-range breakout."""

    candidate_id: str
    breakout_buffer_bps: Decimal
    event_sessions: frozenset[date]
    evaluation_start: datetime
    version: str = "scheduled-event-spy-opening-breakout-v1"

    def __post_init__(self) -> None:
        if self.candidate_id not in {"ieb001-a01", "ieb001-a02", "ieb001-a03"}:
            raise ValueError("Event Opening Breakout 001 candidate identity is invalid")
        if self.breakout_buffer_bps not in {Decimal("2"), Decimal("4"), Decimal("8")}:
            raise ValueError("Event Opening Breakout 001 breakout buffer differs")
        if self.evaluation_start.tzinfo is None:
            raise ValueError("Event Opening Breakout 001 evaluation start must be timezone-aware")

    @property
    def strategy_id(self) -> str:
        return self.candidate_id

    def on_session(
        self, bars: Sequence[OHLCVBar], history: Mapping[Symbol, Sequence[OHLCVBar]]
    ) -> Sequence[TargetPosition]:
        session = self._session(bars, history)
        signal = self.signal(session)
        current = bars[0]
        active = (
            current.timestamp >= self.evaluation_start
            and signal.session_day in self.event_sessions
            and signal.active
            and signal.observed_bar_index < _EXIT_INDEX
        )
        return tuple(
            TargetPosition(
                symbol,
                _HALF if active and symbol == _SPY else _ZERO,
                "scheduled-event-spy-opening-breakout" if active else "event-opening-breakout-flat",
            )
            for symbol in _SYMBOLS
        )

    def signal(self, session: Mapping[Symbol, Sequence[OHLCVBar]]) -> EventOpeningBreakoutSignal:
        """Return the SPY-only opening range and first qualifying completed close."""
        spy = tuple(session[_SPY])
        index = len(spy) - 1
        day = spy[-1].timestamp.astimezone(_NEW_YORK).date()
        if index < _OPENING_RANGE_END:
            return EventOpeningBreakoutSignal(day, index, None, None, None, False)
        opening_range_high = max(bar.high for bar in spy[: _OPENING_RANGE_END + 1])
        threshold = opening_range_high * (Decimal("1") + self.breakout_buffer_bps / _BPS)
        breakout_index = next(
            (
                item_index
                for item_index in range(_MONITOR_START, min(index, _MONITOR_END) + 1)
                if spy[item_index].close >= threshold
            ),
            None,
        )
        return EventOpeningBreakoutSignal(
            day, index, opening_range_high, threshold, breakout_index, breakout_index is not None
        )

    @staticmethod
    def _session(
        bars: Sequence[OHLCVBar], history: Mapping[Symbol, Sequence[OHLCVBar]]
    ) -> dict[Symbol, tuple[OHLCVBar, ...]]:
        current = {bar.symbol: bar for bar in bars}
        if len(bars) != 2 or set(current) != set(_SYMBOLS) or set(history) != set(_SYMBOLS):
            raise ValueError("Event Opening Breakout 001 requires a complete QQQ/SPY slice")
        timestamps = tuple(tuple(item.timestamp for item in history[symbol]) for symbol in _SYMBOLS)
        if (
            not timestamps[0]
            or timestamps[0] != timestamps[1]
            or any(history[symbol][-1] != current[symbol] for symbol in _SYMBOLS)
        ):
            raise ValueError("Event Opening Breakout 001 requires aligned completed histories")
        day = bars[0].timestamp.astimezone(_NEW_YORK).date()
        session = {
            symbol: tuple(
                item
                for item in history[symbol]
                if item.timestamp.astimezone(_NEW_YORK).date() == day
            )
            for symbol in _SYMBOLS
        }
        session_times = tuple(
            tuple(item.timestamp for item in session[symbol]) for symbol in _SYMBOLS
        )
        if (
            not session_times[0]
            or session_times[0] != session_times[1]
            or any(
                right - left != timedelta(minutes=5)
                for left, right in zip(session_times[0], session_times[0][1:], strict=False)
            )
        ):
            raise ValueError(
                "Event Opening Breakout 001 requires contiguous completed five-minute bars"
            )
        return session
