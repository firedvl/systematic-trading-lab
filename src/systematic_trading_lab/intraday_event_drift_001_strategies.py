"""Causal strategy for the frozen Intraday Event Drift 001 campaign."""

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


@dataclass(frozen=True)
class ScheduledBroadIndexPositiveDriftStrategy:
    """Target both broad-index ETFs after one fixed positive event reaction."""

    candidate_id: str
    reaction_bars: int
    minimum_reaction_bps: Decimal
    event_sessions: frozenset[date]
    evaluation_start: datetime
    minimum_opening_gap_bps: Decimal = Decimal("10")
    exit_bar_index: int = 60
    version: str = "scheduled-broad-index-positive-drift-v1"

    def __post_init__(self) -> None:
        if not self.candidate_id.startswith("ied001-a"):
            raise ValueError("Event Drift 001 candidate identity is invalid")
        if self.reaction_bars not in {3, 6, 12}:
            raise ValueError("Event Drift 001 reaction bars differ")
        if self.minimum_reaction_bps not in {
            Decimal("10"),
            Decimal("20"),
            Decimal("40"),
        }:
            raise ValueError("Event Drift 001 reaction threshold differs")
        if self.minimum_opening_gap_bps != Decimal("10") or self.exit_bar_index != 60:
            raise ValueError("Event Drift 001 fixed parameters differ")
        if self.evaluation_start.tzinfo is None:
            raise ValueError("Event Drift 001 evaluation start must be timezone-aware")

    @property
    def strategy_id(self) -> str:
        return self.candidate_id

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        session = self._session(bars, history)
        session_day = bars[0].timestamp.astimezone(_NEW_YORK).date()
        index = len(session[_SPY]) - 1
        active = (
            bars[0].timestamp >= self.evaluation_start
            and session_day in self.event_sessions
            and self.reaction_bars - 1 <= index < self.exit_bar_index
            and self._signal(session, history, session_day)
        )
        return tuple(
            TargetPosition(
                symbol,
                _HALF if active else _ZERO,
                "scheduled-event-positive-drift" if active else "event-drift-flat",
            )
            for symbol in _SYMBOLS
        )

    def _signal(
        self,
        session: Mapping[Symbol, tuple[OHLCVBar, ...]],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
        session_day: date,
    ) -> bool:
        previous = {
            symbol: tuple(
                bar
                for bar in history[symbol]
                if bar.timestamp.astimezone(_NEW_YORK).date() < session_day
            )
            for symbol in _SYMBOLS
        }
        if any(not bars for bars in previous.values()):
            raise ValueError("Event Drift 001 event lacks prior-session data")
        previous_days = {
            previous[symbol][-1].timestamp.astimezone(_NEW_YORK).date() for symbol in _SYMBOLS
        }
        if len(previous_days) != 1:
            raise ValueError("Event Drift 001 prior sessions are not aligned")
        for symbol in _SYMBOLS:
            opening = session[symbol][0].open
            reaction_close = session[symbol][self.reaction_bars - 1].close
            prior_close = previous[symbol][-1].close
            opening_gap = _BPS * (opening / prior_close - Decimal("1"))
            reaction = _BPS * (reaction_close / opening - Decimal("1"))
            if opening_gap < self.minimum_opening_gap_bps or reaction < self.minimum_reaction_bps:
                return False
        return True

    @staticmethod
    def _session(
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> dict[Symbol, tuple[OHLCVBar, ...]]:
        current = {bar.symbol: bar for bar in bars}
        if len(bars) != 2 or set(current) != set(_SYMBOLS) or set(history) != set(_SYMBOLS):
            raise ValueError("Event Drift 001 requires a complete QQQ/SPY slice")
        timestamps = tuple(tuple(item.timestamp for item in history[symbol]) for symbol in _SYMBOLS)
        if (
            not timestamps[0]
            or timestamps[0] != timestamps[1]
            or any(history[symbol][-1] != current[symbol] for symbol in _SYMBOLS)
        ):
            raise ValueError("Event Drift 001 requires aligned completed histories")
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
            raise ValueError("Event Drift 001 requires contiguous completed five-minute bars")
        return session
