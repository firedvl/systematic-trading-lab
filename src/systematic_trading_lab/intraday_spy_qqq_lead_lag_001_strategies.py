"""Causal fixed-leader SPY/QQQ mechanics for Campaign 1.

The strategy only converts completed, aligned regular-session bars into desired
targets and deterministic signal evidence.  It has no market, runtime, or
execution authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .calendar import expected_bar_timestamps
from .domain import OHLCVBar, Symbol, Timeframe
from .strategies import TargetPosition

if TYPE_CHECKING:
    from .intraday_spy_qqq_lead_lag_001_plan import LeadLagConfiguration

_NEW_YORK = ZoneInfo("America/New_York")
_QQQ, _SPY = Symbol("QQQ"), Symbol("SPY")
_SYMBOLS = (_QQQ, _SPY)
_ZERO, _HALF, _BPS = Decimal("0"), Decimal("0.5"), Decimal("10000")
_CANDIDATES = {
    f"isqlll001-a{horizon_index:02d}-b{floor_index:02d}": (horizon, floor)
    for horizon_index, horizon in enumerate((6, 12, 18), start=1)
    for floor_index, floor in enumerate((Decimal("10"), Decimal("20"), Decimal("40")), start=1)
}
_BUCKET_LIMITS = (
    ("under-response-0-to-1-6", Decimal("0"), Decimal("0.1666666666666666666666666667")),
    (
        "under-response-1-6-to-1-3",
        Decimal("0.1666666666666666666666666667"),
        Decimal("0.3333333333333333333333333333"),
    ),
    ("under-response-1-3-to-1-2", Decimal("0.3333333333333333333333333333"), _HALF),
)


@dataclass(frozen=True)
class SpyQqqLeadLagSignal:
    """Cost-independent completed-bar evidence for one session decision."""

    session_day: date
    candidate_id: str
    observation_horizon_bars: int
    minimum_spy_impulse_bps: Decimal
    spy_return_bps: Decimal | None
    qqq_return_bps: Decimal | None
    under_response_ratio: Decimal | None
    under_response_bucket: str | None
    inactive_reason: str | None
    active: bool
    entry_decision_timestamp: datetime | None
    planned_exit_decision_timestamp: datetime | None


def build_intraday_spy_qqq_lead_lag_001_strategy(
    configuration: LeadLagConfiguration,
    evaluation_start: datetime,
) -> SpyQqqLeadLagStrategy:
    """Build the exact frozen configuration without loading data or a plan."""
    return SpyQqqLeadLagStrategy(
        configuration.candidate_id,
        configuration.observation_horizon_bars,
        configuration.minimum_spy_impulse_bps,
        evaluation_start,
    )


@dataclass(frozen=True)
class SpyQqqLeadLagStrategy:
    """Target QQQ once after a qualifying completed SPY impulse."""

    candidate_id: str
    observation_horizon_bars: int
    minimum_spy_impulse_bps: Decimal
    evaluation_start: datetime
    version: str = "intraday-spy-qqq-fixed-leader-catchup-v1"

    def __post_init__(self) -> None:
        if _CANDIDATES.get(self.candidate_id) != (
            self.observation_horizon_bars,
            self.minimum_spy_impulse_bps,
        ):
            raise ValueError("SPY-QQQ Lead-Lag 001 candidate identity is invalid")
        if self.evaluation_start.tzinfo is None or self.evaluation_start.utcoffset() is None:
            raise ValueError("SPY-QQQ Lead-Lag 001 evaluation start must be timezone-aware")

    @property
    def strategy_id(self) -> str:
        return self.candidate_id

    def on_session(
        self, bars: Sequence[OHLCVBar], history: Mapping[Symbol, Sequence[OHLCVBar]]
    ) -> Sequence[TargetPosition]:
        self._current_slice(bars, history)
        signal = self.signal(history)
        return self._targets(signal.active)

    def signal(self, history: Mapping[Symbol, Sequence[OHLCVBar]]) -> SpyQqqLeadLagSignal:
        """Return causal evidence from the current completed regular-session history."""
        session = self._session(history)
        current = session[_SPY][-1]
        session_day = current.timestamp.astimezone(_NEW_YORK).date()
        if current.timestamp < self.evaluation_start:
            return self._inactive(session_day, "context-only-session")
        index = len(session[_SPY]) - 1
        horizon = self.observation_horizon_bars
        expected = _expected_session(session_day)
        if len(expected) < horizon + 27:
            return self._inactive(session_day, "hold-capacity-ineligible")
        if index < horizon - 1:
            return self._inactive(session_day, "insufficient-completed-observation-bars")

        spy_return = _return_bps(session[_SPY][0], session[_SPY][horizon - 1])
        qqq_return = _return_bps(session[_QQQ][0], session[_QQQ][horizon - 1])
        if spy_return < self.minimum_spy_impulse_bps:
            return self._inactive(session_day, "spy-impulse-below-floor", spy_return, qqq_return)
        ratio = qqq_return / spy_return
        if qqq_return < _ZERO:
            return self._inactive(session_day, "qqq-return-negative", spy_return, qqq_return, ratio)
        if ratio > _HALF:
            return self._inactive(
                session_day,
                "qqq-under-response-exceeds-maximum",
                spy_return,
                qqq_return,
                ratio,
            )

        entry = session[_SPY][horizon - 1].timestamp + Timeframe.FIVE_MINUTES.duration
        exit_index = horizon + 23
        active = index < exit_index
        return SpyQqqLeadLagSignal(
            session_day,
            self.candidate_id,
            horizon,
            self.minimum_spy_impulse_bps,
            spy_return,
            qqq_return,
            ratio,
            _bucket(ratio),
            None if active else "fixed-hold-complete",
            active,
            entry,
            (
                session[_SPY][exit_index].timestamp + Timeframe.FIVE_MINUTES.duration
                if index >= exit_index
                else entry + timedelta(minutes=5 * 24)
            ),
        )

    def _inactive(
        self,
        session_day: date,
        reason: str,
        spy_return_bps: Decimal | None = None,
        qqq_return_bps: Decimal | None = None,
        ratio: Decimal | None = None,
    ) -> SpyQqqLeadLagSignal:
        return SpyQqqLeadLagSignal(
            session_day,
            self.candidate_id,
            self.observation_horizon_bars,
            self.minimum_spy_impulse_bps,
            spy_return_bps,
            qqq_return_bps,
            ratio,
            _bucket(ratio) if ratio is not None and _ZERO <= ratio <= _HALF else None,
            reason,
            False,
            None,
            None,
        )

    @staticmethod
    def _targets(active: bool) -> tuple[TargetPosition, ...]:
        return tuple(
            TargetPosition(
                symbol,
                _HALF if active and symbol == _QQQ else _ZERO,
                "spy-qqq-fixed-leader-catchup" if active else "spy-qqq-lead-lag-flat",
            )
            for symbol in _SYMBOLS
        )

    @staticmethod
    def _current_slice(
        bars: Sequence[OHLCVBar], history: Mapping[Symbol, Sequence[OHLCVBar]]
    ) -> None:
        current = {bar.symbol: bar for bar in bars}
        if len(bars) != 2 or set(current) != set(_SYMBOLS) or set(history) != set(_SYMBOLS):
            raise ValueError("SPY-QQQ Lead-Lag 001 requires a complete QQQ/SPY slice")
        if any(
            not history[symbol] or history[symbol][-1] != current[symbol] for symbol in _SYMBOLS
        ):
            raise ValueError("SPY-QQQ Lead-Lag 001 requires completed histories")
        if current[_QQQ].timestamp != current[_SPY].timestamp:
            raise ValueError("SPY-QQQ Lead-Lag 001 requires aligned current bars")

    @staticmethod
    def _session(
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> dict[Symbol, tuple[OHLCVBar, ...]]:
        if set(history) != set(_SYMBOLS) or any(not history[symbol] for symbol in _SYMBOLS):
            raise ValueError("SPY-QQQ Lead-Lag 001 requires complete QQQ/SPY histories")
        day = history[_SPY][-1].timestamp.astimezone(_NEW_YORK).date()
        session = {
            symbol: tuple(
                bar for bar in history[symbol] if bar.timestamp.astimezone(_NEW_YORK).date() == day
            )
            for symbol in _SYMBOLS
        }
        timestamps = tuple(tuple(bar.timestamp for bar in session[symbol]) for symbol in _SYMBOLS)
        if (
            not timestamps[0]
            or timestamps[0] != timestamps[1]
            or timestamps[0] != _expected_session(day)[: len(timestamps[0])]
        ):
            raise ValueError("SPY-QQQ Lead-Lag 001 requires an exact XNYS regular-session prefix")
        return session


def _return_bps(opening: OHLCVBar, observed: OHLCVBar) -> Decimal:
    return _BPS * (observed.close / opening.open - 1)


def _expected_session(session_day: date) -> tuple[datetime, ...]:
    return expected_bar_timestamps(
        datetime.combine(session_day, datetime.min.time(), UTC),
        datetime.combine(session_day, datetime.max.time(), UTC),
        Timeframe.FIVE_MINUTES,
    )


def _bucket(ratio: Decimal) -> str:
    for bucket_id, lower, upper in _BUCKET_LIMITS:
        if lower <= ratio <= upper and (bucket_id.endswith("1-2") or ratio < upper):
            return bucket_id
    raise ValueError("SPY-QQQ Lead-Lag 001 under-response ratio is outside the frozen buckets")
