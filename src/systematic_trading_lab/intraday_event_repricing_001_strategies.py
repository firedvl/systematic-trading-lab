"""Paired causal strategies for the frozen Intraday Event Repricing 001 plan."""

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
class EventRepricingSelection:
    signed_reaction_bps: Decimal
    leader: Symbol | None
    laggard: Symbol | None
    active: bool


@dataclass(frozen=True)
class ScheduledEventRelativeLeaderStrategy:
    """Replay one long-only leader or laggard-control arm from a signed event reaction."""

    candidate_id: str
    reaction_bars: int
    minimum_relative_reaction_bps: Decimal
    event_sessions: frozenset[date]
    evaluation_start: datetime
    arm: str
    version: str = "scheduled-event-relative-leader-continuation-v1"

    def __post_init__(self) -> None:
        if not self.candidate_id.startswith("ier001-a"):
            raise ValueError("Event Repricing 001 candidate identity is invalid")
        if self.reaction_bars not in {3, 6, 12}:
            raise ValueError("Event Repricing 001 reaction bars differ")
        if self.minimum_relative_reaction_bps not in {Decimal("5"), Decimal("10"), Decimal("20")}:
            raise ValueError("Event Repricing 001 reaction threshold differs")
        if self.arm not in {"leader", "laggard-control"}:
            raise ValueError("Event Repricing 001 arm differs")
        if self.evaluation_start.tzinfo is None:
            raise ValueError("Event Repricing 001 evaluation start must be timezone-aware")

    @property
    def strategy_id(self) -> str:
        return f"{self.candidate_id}-{self.arm}"

    def on_session(
        self, bars: Sequence[OHLCVBar], history: Mapping[Symbol, Sequence[OHLCVBar]]
    ) -> Sequence[TargetPosition]:
        session = self._session(bars, history)
        session_day = bars[0].timestamp.astimezone(_NEW_YORK).date()
        index = len(session[_QQQ]) - 1
        selection = self.selection(session)
        active_window = self.reaction_bars - 1 <= index < self.reaction_bars + 23
        symbol = selection.leader if self.arm == "leader" else selection.laggard
        active = (
            bars[0].timestamp >= self.evaluation_start
            and session_day in self.event_sessions
            and active_window
            and selection.active
            and symbol is not None
        )
        return tuple(
            TargetPosition(
                item,
                _HALF if active and item == symbol else _ZERO,
                f"scheduled-event-relative-{self.arm}" if active else "event-repricing-flat",
            )
            for item in _SYMBOLS
        )

    def selection(self, session: Mapping[Symbol, Sequence[OHLCVBar]]) -> EventRepricingSelection:
        qqq = session[_QQQ]
        spy = session[_SPY]
        if len(qqq) < self.reaction_bars or len(spy) < self.reaction_bars:
            return EventRepricingSelection(_ZERO, None, None, False)
        signed = _BPS * (
            (qqq[self.reaction_bars - 1].close / qqq[0].open)
            - (spy[self.reaction_bars - 1].close / spy[0].open)
        )
        if signed == _ZERO or abs(signed) < self.minimum_relative_reaction_bps:
            return EventRepricingSelection(signed, None, None, False)
        leader, laggard = (_QQQ, _SPY) if signed > _ZERO else (_SPY, _QQQ)
        return EventRepricingSelection(signed, leader, laggard, True)

    @staticmethod
    def _session(
        bars: Sequence[OHLCVBar], history: Mapping[Symbol, Sequence[OHLCVBar]]
    ) -> dict[Symbol, tuple[OHLCVBar, ...]]:
        current = {bar.symbol: bar for bar in bars}
        if len(bars) != 2 or set(current) != set(_SYMBOLS) or set(history) != set(_SYMBOLS):
            raise ValueError("Event Repricing 001 requires a complete QQQ/SPY slice")
        timestamps = tuple(tuple(item.timestamp for item in history[symbol]) for symbol in _SYMBOLS)
        if (
            not timestamps[0]
            or timestamps[0] != timestamps[1]
            or any(history[symbol][-1] != current[symbol] for symbol in _SYMBOLS)
        ):
            raise ValueError("Event Repricing 001 requires aligned completed histories")
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
            raise ValueError("Event Repricing 001 requires contiguous completed five-minute bars")
        return session
