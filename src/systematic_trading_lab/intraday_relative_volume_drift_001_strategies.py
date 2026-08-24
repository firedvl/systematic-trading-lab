"""Causal joint same-clock relative-volume mechanics for Campaign 2.

The strategy converts completed, aligned regular-session bars into fixed
targets and deterministic signal evidence. It has no market, runtime, or
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
    from .intraday_relative_volume_drift_001_plan import RelativeVolumeConfiguration

_NEW_YORK = ZoneInfo("America/New_York")
_QQQ, _SPY = Symbol("QQQ"), Symbol("SPY")
_SYMBOLS = (_QQQ, _SPY)
_ZERO, _HALF, _BPS = Decimal("0"), Decimal("0.5"), Decimal("10000")
_RETURN_FLOOR_BPS = Decimal("15")
_LOOKBACK_SESSIONS = 10
_CANDIDATES = {
    f"irvd001-a{horizon_index:02d}-b{floor_index:02d}": (horizon, floor)
    for horizon_index, horizon in enumerate((8, 16, 24), start=1)
    for floor_index, floor in enumerate((Decimal("1.2"), Decimal("1.5"), Decimal("2")), start=1)
}


@dataclass(frozen=True)
class RelativeVolumeDriftSignal:
    """Cost-independent completed-bar evidence for one session decision."""

    session_day: date
    candidate_id: str
    observation_horizon_bars: int
    minimum_joint_relative_volume: Decimal
    baseline_session_days: tuple[date, ...]
    qqq_prior_cumulative_volumes: tuple[int, ...]
    spy_prior_cumulative_volumes: tuple[int, ...]
    qqq_baseline_median: Decimal | None
    spy_baseline_median: Decimal | None
    qqq_current_cumulative_volume: int | None
    spy_current_cumulative_volume: int | None
    qqq_relative_volume: Decimal | None
    spy_relative_volume: Decimal | None
    qqq_return_bps: Decimal | None
    spy_return_bps: Decimal | None
    joint_return_passed: bool | None
    joint_relative_volume_passed: bool | None
    joint_relative_volume: Decimal | None
    participation_strength: Decimal | None
    participation_bucket: str | None
    inactive_reason: str | None
    qualifying_signal: bool
    active: bool
    entry_decision_timestamp: datetime | None
    planned_exit_decision_timestamp: datetime | None


def build_intraday_relative_volume_drift_001_strategy(
    configuration: RelativeVolumeConfiguration,
    evaluation_start: datetime,
) -> RelativeVolumeDriftStrategy:
    """Build the exact frozen configuration without loading data or a plan."""
    return RelativeVolumeDriftStrategy(
        configuration.candidate_id,
        configuration.observation_horizon_bars,
        configuration.minimum_joint_relative_volume,
        evaluation_start,
    )


@dataclass(frozen=True)
class RelativeVolumeDriftStrategy:
    """Target SPY and QQQ together after a causal participation shock."""

    candidate_id: str
    observation_horizon_bars: int
    minimum_joint_relative_volume: Decimal
    evaluation_start: datetime
    version: str = "intraday-joint-relative-volume-drift-v1"

    def __post_init__(self) -> None:
        if _CANDIDATES.get(self.candidate_id) != (
            self.observation_horizon_bars,
            self.minimum_joint_relative_volume,
        ):
            raise ValueError("Relative-Volume Drift 001 candidate identity is invalid")
        if self.evaluation_start.tzinfo is None or self.evaluation_start.utcoffset() is None:
            raise ValueError("Relative-Volume Drift 001 evaluation start must be timezone-aware")

    @property
    def strategy_id(self) -> str:
        return self.candidate_id

    def on_session(
        self, bars: Sequence[OHLCVBar], history: Mapping[Symbol, Sequence[OHLCVBar]]
    ) -> Sequence[TargetPosition]:
        self._current_slice(bars, history)
        signal = self.signal(history)
        return tuple(
            TargetPosition(
                symbol,
                _HALF if signal.active else _ZERO,
                ("joint-relative-volume-drift" if signal.active else "relative-volume-drift-flat"),
            )
            for symbol in _SYMBOLS
        )

    def signal(self, history: Mapping[Symbol, Sequence[OHLCVBar]]) -> RelativeVolumeDriftSignal:
        """Return causal evidence from the current and ten prior complete sessions."""
        current, prior = self._sessions(history)
        current_spy = current[_SPY]
        session_day = current_spy[-1].timestamp.astimezone(_NEW_YORK).date()
        current_timestamp = current_spy[-1].timestamp
        if current_timestamp < self.evaluation_start:
            return self._ineligible(session_day, "context-only-session")
        if len(prior) < _LOOKBACK_SESSIONS:
            return self._ineligible(session_day, "lookback-ineligible")

        expected = _expected_session(session_day)
        horizon = self.observation_horizon_bars
        if len(expected) < horizon + 27:
            return self._ineligible(session_day, "hold-capacity-ineligible")

        baselines = prior[-_LOOKBACK_SESSIONS:]
        baseline_days = tuple(
            session[_SPY][0].timestamp.astimezone(_NEW_YORK).date() for session in baselines
        )
        qqq_prefixes = tuple(_prefix_volume(session[_QQQ], horizon) for session in baselines)
        spy_prefixes = tuple(_prefix_volume(session[_SPY], horizon) for session in baselines)
        qqq_median, spy_median = _median(qqq_prefixes), _median(spy_prefixes)
        if qqq_median <= _ZERO or spy_median <= _ZERO:
            raise ValueError("Relative-Volume Drift 001 same-clock baseline must be positive")
        if len(current_spy) < horizon:
            return self._ineligible(
                session_day,
                "insufficient-completed-observation-bars",
                baseline_days=baseline_days,
                qqq_prefixes=qqq_prefixes,
                spy_prefixes=spy_prefixes,
                qqq_median=qqq_median,
                spy_median=spy_median,
            )

        qqq_current = _prefix_volume(current[_QQQ], horizon)
        spy_current = _prefix_volume(current[_SPY], horizon)
        qqq_relative = Decimal(qqq_current) / qqq_median
        spy_relative = Decimal(spy_current) / spy_median
        qqq_return = _return_bps(current[_QQQ][0], current[_QQQ][horizon - 1])
        spy_return = _return_bps(current[_SPY][0], current[_SPY][horizon - 1])
        return_passed = qqq_return >= _RETURN_FLOOR_BPS and spy_return >= _RETURN_FLOOR_BPS
        volume_passed = (
            qqq_relative >= self.minimum_joint_relative_volume
            and spy_relative >= self.minimum_joint_relative_volume
        )
        joint_relative = min(qqq_relative, spy_relative)
        qualified = return_passed and volume_passed
        reason = (
            None
            if qualified
            else (
                "inactive-joint-return" if not return_passed else "inactive-joint-relative-volume"
            )
        )
        entry = current[_SPY][horizon - 1].timestamp + Timeframe.FIVE_MINUTES.duration
        exit_index = horizon + 23
        active = qualified and len(current_spy) - 1 < exit_index
        strength = joint_relative / self.minimum_joint_relative_volume if qualified else None
        return RelativeVolumeDriftSignal(
            session_day,
            self.candidate_id,
            horizon,
            self.minimum_joint_relative_volume,
            baseline_days,
            qqq_prefixes,
            spy_prefixes,
            qqq_median,
            spy_median,
            qqq_current,
            spy_current,
            qqq_relative,
            spy_relative,
            qqq_return,
            spy_return,
            return_passed,
            volume_passed,
            joint_relative,
            strength,
            _bucket(strength) if strength is not None else None,
            (reason if not qualified else (None if active else "fixed-hold-complete")),
            qualified,
            active,
            entry if qualified else None,
            (
                current[_SPY][exit_index].timestamp + Timeframe.FIVE_MINUTES.duration
                if qualified and len(current_spy) - 1 >= exit_index
                else entry + timedelta(minutes=5 * 24)
                if qualified
                else None
            ),
        )

    def _ineligible(
        self,
        session_day: date,
        reason: str,
        *,
        baseline_days: tuple[date, ...] = (),
        qqq_prefixes: tuple[int, ...] = (),
        spy_prefixes: tuple[int, ...] = (),
        qqq_median: Decimal | None = None,
        spy_median: Decimal | None = None,
    ) -> RelativeVolumeDriftSignal:
        return RelativeVolumeDriftSignal(
            session_day,
            self.candidate_id,
            self.observation_horizon_bars,
            self.minimum_joint_relative_volume,
            baseline_days,
            qqq_prefixes,
            spy_prefixes,
            qqq_median,
            spy_median,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            reason,
            False,
            False,
            None,
            None,
        )

    @staticmethod
    def _current_slice(
        bars: Sequence[OHLCVBar], history: Mapping[Symbol, Sequence[OHLCVBar]]
    ) -> None:
        current = {bar.symbol: bar for bar in bars}
        if len(bars) != 2 or set(current) != set(_SYMBOLS) or set(history) != set(_SYMBOLS):
            raise ValueError("Relative-Volume Drift 001 requires a complete QQQ/SPY slice")
        if any(
            not history[symbol] or history[symbol][-1] != current[symbol] for symbol in _SYMBOLS
        ):
            raise ValueError("Relative-Volume Drift 001 requires completed histories")
        if current[_QQQ].timestamp != current[_SPY].timestamp:
            raise ValueError("Relative-Volume Drift 001 requires aligned current bars")

    @staticmethod
    def _sessions(
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> tuple[
        dict[Symbol, tuple[OHLCVBar, ...]],
        tuple[dict[Symbol, tuple[OHLCVBar, ...]], ...],
    ]:
        if set(history) != set(_SYMBOLS) or any(not history[symbol] for symbol in _SYMBOLS):
            raise ValueError("Relative-Volume Drift 001 requires complete QQQ/SPY histories")
        timestamps = tuple(tuple(bar.timestamp for bar in history[symbol]) for symbol in _SYMBOLS)
        if timestamps[0] != timestamps[1]:
            raise ValueError("Relative-Volume Drift 001 requires aligned QQQ/SPY histories")
        current_day = history[_SPY][-1].timestamp.astimezone(_NEW_YORK).date()
        days = tuple(
            dict.fromkeys(bar.timestamp.astimezone(_NEW_YORK).date() for bar in history[_SPY])
        )
        sessions: list[dict[Symbol, tuple[OHLCVBar, ...]]] = []
        for day in days:
            session = {
                symbol: tuple(
                    bar
                    for bar in history[symbol]
                    if bar.timestamp.astimezone(_NEW_YORK).date() == day
                )
                for symbol in _SYMBOLS
            }
            expected = _expected_session(day)
            session_timestamps = tuple(
                tuple(bar.timestamp for bar in session[symbol]) for symbol in _SYMBOLS
            )
            complete = day != current_day
            if (
                not session_timestamps[0]
                or session_timestamps[0] != session_timestamps[1]
                or session_timestamps[0]
                != (expected if complete else expected[: len(session_timestamps[0])])
            ):
                raise ValueError(
                    "Relative-Volume Drift 001 requires exact aligned XNYS session bars"
                )
            sessions.append(session)
        return sessions[-1], tuple(sessions[:-1])


def _prefix_volume(bars: Sequence[OHLCVBar], horizon: int) -> int:
    if len(bars) < horizon:
        raise ValueError("Relative-Volume Drift 001 complete baseline lacks the horizon")
    return sum(bar.volume for bar in bars[:horizon])


def _median(values: Sequence[int]) -> Decimal:
    if len(values) != _LOOKBACK_SESSIONS:
        raise ValueError("Relative-Volume Drift 001 baseline requires ten sessions")
    ordered = sorted(values)
    return (Decimal(ordered[4]) + Decimal(ordered[5])) / 2


def _return_bps(opening: OHLCVBar, observed: OHLCVBar) -> Decimal:
    return _BPS * (observed.close / opening.open - 1)


def _expected_session(session_day: date) -> tuple[datetime, ...]:
    return expected_bar_timestamps(
        datetime.combine(session_day, datetime.min.time(), UTC),
        datetime.combine(session_day, datetime.max.time(), UTC),
        Timeframe.FIVE_MINUTES,
    )


def _bucket(strength: Decimal) -> str:
    if strength < Decimal("1.2"):
        return "participation-q-1-to-1-2"
    if strength < Decimal("1.5"):
        return "participation-q-1-2-to-1-5"
    return "participation-q-1-5-plus"
