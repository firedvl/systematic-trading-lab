"""Causal SPY-only strategy for Intraday Event Prior Low Rejection 001."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from .calendar import expected_bar_timestamps, expected_sessions
from .domain import OHLCVBar, Symbol, Timeframe
from .strategies import TargetPosition

_NEW_YORK = ZoneInfo("America/New_York")
_QQQ, _SPY = Symbol("QQQ"), Symbol("SPY")
_SYMBOLS = (_QQQ, _SPY)
_ZERO, _HALF = Decimal("0"), Decimal("0.5")
_BREACH_END, _MONITOR_START, _MONITOR_END, _EXIT_INDEX = 5, 6, 11, 29


@dataclass(frozen=True)
class EventPriorLowRejectionSignal:
    """Deterministic completed-bar evidence for one event-session decision."""

    session_day: date
    prior_session_low: Decimal
    opening_window_low: Decimal
    opening_window_breach: bool
    confirmation_bars: int
    reclaim_decision_bar_index: int | None
    reclaim_decision_timestamp: datetime | None
    active: bool


@dataclass(frozen=True)
class ScheduledEventSpyPriorLowRejectionStrategy:
    """Target SPY once after an event-session prior-low rejection is confirmed."""

    candidate_id: str
    confirmation_bars: int
    event_sessions: frozenset[date]
    evaluation_start: datetime
    version: str = "scheduled-event-spy-prior-low-rejection-v1"

    def __post_init__(self) -> None:
        if self.candidate_id not in {"ieplr001-a01", "ieplr001-a02", "ieplr001-a03"}:
            raise ValueError("Event Prior Low Rejection 001 candidate identity is invalid")
        if self.confirmation_bars not in {1, 2, 3}:
            raise ValueError("Event Prior Low Rejection 001 confirmation bars differ")
        if self.evaluation_start.tzinfo is None:
            raise ValueError(
                "Event Prior Low Rejection 001 evaluation start must be timezone-aware"
            )

    @property
    def strategy_id(self) -> str:
        return self.candidate_id

    def on_session(
        self, bars: Sequence[OHLCVBar], history: Mapping[Symbol, Sequence[OHLCVBar]]
    ) -> Sequence[TargetPosition]:
        self._current_slice(bars, history)
        current = bars[0]
        session_day = current.timestamp.astimezone(_NEW_YORK).date()
        eligible = current.timestamp >= self.evaluation_start and session_day in self.event_sessions
        if not eligible:
            return self._targets(False)
        signal = self.signal(history)
        active = (
            signal.active
            and len(self._current_session(history, session_day)[_SPY]) - 1 < _EXIT_INDEX
        )
        return self._targets(active)

    def signal(self, history: Mapping[Symbol, Sequence[OHLCVBar]]) -> EventPriorLowRejectionSignal:
        """Derive the immutable prior low and first qualifying completed reclaim run."""
        current_day = self._history_day(history)
        session = self._current_session(history, current_day)
        previous = self._prior_session(history, current_day)
        prior_low = min(bar.low for bar in previous[_SPY])
        observed = len(session[_SPY]) - 1
        opening = session[_SPY][: min(len(session[_SPY]), _BREACH_END + 1)]
        opening_low = min(bar.low for bar in opening)
        breach = any(bar.low < prior_low for bar in opening)
        reclaim_index = self._reclaim_index(session[_SPY], prior_low, observed) if breach else None
        return EventPriorLowRejectionSignal(
            current_day,
            prior_low,
            opening_low,
            breach,
            self.confirmation_bars,
            reclaim_index,
            (
                session[_SPY][reclaim_index].timestamp + Timeframe.FIVE_MINUTES.duration
                if reclaim_index is not None
                else None
            ),
            reclaim_index is not None,
        )

    def _reclaim_index(
        self, spy: Sequence[OHLCVBar], prior_low: Decimal, observed: int
    ) -> int | None:
        for index in range(
            _MONITOR_START + self.confirmation_bars - 1, min(observed, _MONITOR_END) + 1
        ):
            if all(
                bar.close > prior_low for bar in spy[index - self.confirmation_bars + 1 : index + 1]
            ):
                return index
        return None

    @staticmethod
    def _targets(active: bool) -> tuple[TargetPosition, ...]:
        return tuple(
            TargetPosition(
                symbol,
                _HALF if active and symbol == _SPY else _ZERO,
                "scheduled-event-spy-prior-low-rejection"
                if active
                else "event-prior-low-rejection-flat",
            )
            for symbol in _SYMBOLS
        )

    @staticmethod
    def _current_slice(
        bars: Sequence[OHLCVBar], history: Mapping[Symbol, Sequence[OHLCVBar]]
    ) -> None:
        current = {bar.symbol: bar for bar in bars}
        if len(bars) != 2 or set(current) != set(_SYMBOLS) or set(history) != set(_SYMBOLS):
            raise ValueError("Event Prior Low Rejection 001 requires a complete QQQ/SPY slice")
        if any(
            not history[symbol] or history[symbol][-1] != current[symbol] for symbol in _SYMBOLS
        ):
            raise ValueError("Event Prior Low Rejection 001 requires completed histories")
        if current[_QQQ].timestamp != current[_SPY].timestamp:
            raise ValueError("Event Prior Low Rejection 001 requires aligned current bars")

    @staticmethod
    def _history_day(history: Mapping[Symbol, Sequence[OHLCVBar]]) -> date:
        days = {history[symbol][-1].timestamp.astimezone(_NEW_YORK).date() for symbol in _SYMBOLS}
        if len(days) != 1:
            raise ValueError("Event Prior Low Rejection 001 current session is misaligned")
        return next(iter(days))

    @staticmethod
    def _current_session(
        history: Mapping[Symbol, Sequence[OHLCVBar]], current_day: date
    ) -> dict[Symbol, tuple[OHLCVBar, ...]]:
        return {
            symbol: tuple(
                bar
                for bar in history[symbol]
                if bar.timestamp.astimezone(_NEW_YORK).date() == current_day
            )
            for symbol in _SYMBOLS
        }

    @staticmethod
    def _prior_session(
        history: Mapping[Symbol, Sequence[OHLCVBar]], current_day: date
    ) -> dict[Symbol, tuple[OHLCVBar, ...]]:
        timestamps = tuple(tuple(bar.timestamp for bar in history[symbol]) for symbol in _SYMBOLS)
        if not timestamps[0] or timestamps[0] != timestamps[1]:
            raise ValueError("Event Prior Low Rejection 001 requires aligned histories")
        earlier_days = {
            bar.timestamp.astimezone(_NEW_YORK).date()
            for bar in history[_SPY]
            if bar.timestamp.astimezone(_NEW_YORK).date() < current_day
        }
        if not earlier_days:
            raise ValueError("Event Prior Low Rejection 001 event lacks prior-session data")
        previous_day = max(earlier_days)
        first = datetime.combine(previous_day, datetime.min.time(), UTC)
        current = datetime.combine(current_day, datetime.max.time(), UTC)
        sessions = expected_sessions(first, current)
        if len(sessions) < 2 or sessions[-1] != current_day or sessions[-2] != previous_day:
            raise ValueError(
                "Event Prior Low Rejection 001 prior session is not immediately preceding XNYS"
            )
        previous = {
            symbol: tuple(
                bar
                for bar in history[symbol]
                if bar.timestamp.astimezone(_NEW_YORK).date() == previous_day
            )
            for symbol in _SYMBOLS
        }
        expected = expected_bar_timestamps(
            datetime.combine(previous_day, datetime.min.time(), UTC),
            datetime.combine(previous_day, datetime.max.time(), UTC),
            Timeframe.FIVE_MINUTES,
        )
        if not expected or any(
            tuple(bar.timestamp for bar in previous[symbol]) != expected for symbol in _SYMBOLS
        ):
            raise ValueError(
                "Event Prior Low Rejection 001 prior session is incomplete or misaligned"
            )
        return previous
