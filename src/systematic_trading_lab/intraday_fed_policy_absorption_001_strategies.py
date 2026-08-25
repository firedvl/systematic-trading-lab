"""Causal joint-reaction mechanics for Intraday Fed Policy Absorption 001."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .domain import OHLCVBar, Symbol
from .strategies import TargetPosition

if TYPE_CHECKING:
    from .intraday_fed_policy_absorption_001_plan import FedPolicyAbsorptionConfiguration

_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)
_NEW_YORK = ZoneInfo("America/New_York")
_SPY, _QQQ = Symbol("SPY"), Symbol("QQQ")
_SYMBOLS = (_SPY, _QQQ)
_ZERO, _HALF, _BPS = Decimal("0"), Decimal("0.5"), Decimal("10000")


@dataclass(frozen=True)
class FedPolicyAbsorptionSignal:
    session_day: date
    horizon: int
    floor_bps: Decimal
    terminal_index: int
    spy_reaction_bps: Decimal
    qqq_reaction_bps: Decimal
    active: bool
    no_signal_reason: str | None


@dataclass(frozen=True)
class FedPolicyAbsorptionStrategy:
    candidate_id: str
    observation_horizon_bars: int
    minimum_joint_reaction_bps: Decimal
    event_sessions: frozenset[date]
    version: str = "intraday-fed-policy-absorption-v1"

    def __post_init__(self) -> None:
        expected = (
            f"fedabs-h{self.observation_horizon_bars:02d}-"
            f"f{int(self.minimum_joint_reaction_bps):04d}"
        )
        if (
            self.candidate_id != expected
            or self.observation_horizon_bars not in range(1, 8)
            or self.minimum_joint_reaction_bps not in {Decimal(value) for value in range(4, 29, 4)}
        ):
            raise ValueError("Fed Policy Absorption 001 candidate identity is invalid")

    @property
    def strategy_id(self) -> str:
        return self.candidate_id

    def signal(self, session: Mapping[Symbol, Sequence[OHLCVBar]]) -> FedPolicyAbsorptionSignal:
        spy, qqq = _validated_session(session)
        terminal = 53 + self.observation_horizon_bars
        if len(spy) <= terminal:
            raise ValueError("Fed Policy Absorption 001 requires causal terminal bars")
        with localcontext(_CONTEXT):
            spy_reaction = _reaction(spy[53].close, spy[terminal].close)
            qqq_reaction = _reaction(qqq[53].close, qqq[terminal].close)
        spy_passed = spy_reaction >= self.minimum_joint_reaction_bps
        qqq_passed = qqq_reaction >= self.minimum_joint_reaction_bps
        reason = (
            None
            if spy_passed and qqq_passed
            else (
                "both-below-floor"
                if not spy_passed and not qqq_passed
                else "spy-below-floor"
                if not spy_passed
                else "qqq-below-floor"
            )
        )
        return FedPolicyAbsorptionSignal(
            spy[0].timestamp.astimezone(_NEW_YORK).date(),
            self.observation_horizon_bars,
            self.minimum_joint_reaction_bps,
            terminal,
            spy_reaction,
            qqq_reaction,
            reason is None,
            reason,
        )

    def on_session(
        self, bars: Sequence[OHLCVBar], history: Mapping[Symbol, Sequence[OHLCVBar]]
    ) -> Sequence[TargetPosition]:
        current = {bar.symbol: bar for bar in bars}
        if (
            len(bars) != 2
            or set(current) != set(_SYMBOLS)
            or set(history) != set(_SYMBOLS)
            or any(
                not history[symbol] or history[symbol][-1] != current[symbol] for symbol in _SYMBOLS
            )
        ):
            raise ValueError("Fed Policy Absorption 001 requires a complete aligned slice")
        day = bars[0].timestamp.astimezone(_NEW_YORK).date()
        session = {
            symbol: tuple(
                bar for bar in history[symbol] if bar.timestamp.astimezone(_NEW_YORK).date() == day
            )
            for symbol in _SYMBOLS
        }
        index = len(session[_SPY]) - 1
        signal = (
            self.signal(session)
            if day in self.event_sessions and index >= 53 + self.observation_horizon_bars
            else None
        )
        active = signal is not None and signal.active and index < 74
        return tuple(
            TargetPosition(
                symbol,
                _HALF if active else _ZERO,
                "fed-policy-absorption-joint" if active else "fed-policy-absorption-flat",
            )
            for symbol in _SYMBOLS
        )


def build_intraday_fed_policy_absorption_001_strategy(
    configuration: FedPolicyAbsorptionConfiguration, event_sessions: frozenset[date]
) -> FedPolicyAbsorptionStrategy:
    """Build a strategy from the frozen plan configuration without loading data."""
    return FedPolicyAbsorptionStrategy(
        configuration.candidate_id,
        configuration.observation_horizon_bars,
        configuration.minimum_joint_reaction_bps,
        event_sessions,
    )


def _reaction(reference: Decimal, terminal: Decimal) -> Decimal:
    if (
        not reference.is_finite()
        or not terminal.is_finite()
        or reference <= _ZERO
        or terminal <= _ZERO
    ):
        raise ValueError("Fed Policy Absorption 001 causal close is invalid")
    return _BPS * (terminal / reference - Decimal("1"))


def _validated_session(
    session: Mapping[Symbol, Sequence[OHLCVBar]],
) -> tuple[tuple[OHLCVBar, ...], tuple[OHLCVBar, ...]]:
    if set(session) != set(_SYMBOLS):
        raise ValueError("Fed Policy Absorption 001 requires SPY and QQQ")
    spy, qqq = tuple(session[_SPY]), tuple(session[_QQQ])
    if len(spy) != len(qqq) or len(spy) < 56:
        raise ValueError("Fed Policy Absorption 001 session capacity differs")
    times = tuple(bar.timestamp for bar in spy)
    if times != tuple(bar.timestamp for bar in qqq) or any(
        right - left != timedelta(minutes=5) for left, right in zip(times, times[1:], strict=False)
    ):
        raise ValueError("Fed Policy Absorption 001 requires aligned contiguous bars")
    if len(spy) > 78 or any(
        bar.symbol != symbol for symbol, bars in ((_SPY, spy), (_QQQ, qqq)) for bar in bars
    ):
        raise ValueError("Fed Policy Absorption 001 bar identities differ")
    return spy, qqq
