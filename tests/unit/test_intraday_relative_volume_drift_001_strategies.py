from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from systematic_trading_lab.calendar import expected_bar_timestamps, expected_sessions
from systematic_trading_lab.domain import OHLCVBar, Symbol, Timeframe
from systematic_trading_lab.intraday_relative_volume_drift_001_strategies import (
    RelativeVolumeDriftStrategy,
)

_QQQ, _SPY = Symbol("QQQ"), Symbol("SPY")


def _session_timestamps(day: date) -> tuple[datetime, ...]:
    return expected_bar_timestamps(
        datetime.combine(day, datetime.min.time(), UTC),
        datetime.combine(day, datetime.max.time(), UTC),
        Timeframe.FIVE_MINUTES,
    )


def _history(
    *,
    day: date = date(2026, 1, 8),
    prior_totals: tuple[int, ...] = (10,) * 10,
    current_total: int = 20,
    current_return_bps: tuple[Decimal, Decimal] = (Decimal("20"), Decimal("20")),
    current_bar_count: int = 8,
) -> dict[Symbol, tuple[OHLCVBar, ...]]:
    prior_days = tuple(
        expected_sessions(
            datetime.combine(day, datetime.min.time(), UTC).replace(day=1)
            if day.day > 10
            else datetime(2025, 12, 1, tzinfo=UTC),
            datetime.combine(day, datetime.min.time(), UTC),
        )
    )
    prior_days = tuple(value for value in prior_days if value < day)[-len(prior_totals) :]
    if len(prior_days) != len(prior_totals):
        raise AssertionError("fixture does not have enough prior sessions")
    by_symbol: dict[Symbol, list[OHLCVBar]] = {_QQQ: [], _SPY: []}
    for prior_day, total in zip(prior_days, prior_totals, strict=True):
        for index, timestamp in enumerate(_session_timestamps(prior_day)):
            for symbol in (_QQQ, _SPY):
                by_symbol[symbol].append(
                    OHLCVBar(
                        symbol,
                        timestamp,
                        Decimal("100"),
                        Decimal("100"),
                        Decimal("100"),
                        Decimal("100"),
                        total if index == 0 else 0,
                    )
                )
    returns = {_QQQ: current_return_bps[0], _SPY: current_return_bps[1]}
    for index, timestamp in enumerate(_session_timestamps(day)[:current_bar_count]):
        for symbol in (_QQQ, _SPY):
            close = (
                Decimal("100") * (1 + returns[symbol] / Decimal("10000"))
                if index == 7
                else Decimal("100")
            )
            by_symbol[symbol].append(
                OHLCVBar(
                    symbol,
                    timestamp,
                    Decimal("100"),
                    max(Decimal("100"), close),
                    min(Decimal("100"), close),
                    close,
                    current_total if index == 0 else 0,
                )
            )
    return {symbol: tuple(values) for symbol, values in by_symbol.items()}


def _strategy(
    *,
    candidate_id: str = "irvd001-a01-b01",
    horizon: int = 8,
    floor: str = "1.2",
    evaluation_start: datetime = datetime(2025, 1, 1, tzinfo=UTC),
) -> RelativeVolumeDriftStrategy:
    return RelativeVolumeDriftStrategy(
        candidate_id,
        horizon,
        Decimal(floor),
        evaluation_start,
    )


def _targets(
    strategy: RelativeVolumeDriftStrategy,
    history: dict[Symbol, tuple[OHLCVBar, ...]],
) -> dict[Symbol, Decimal]:
    return {
        target.symbol: target.weight
        for target in strategy.on_session((history[_QQQ][-1], history[_SPY][-1]), history)
    }


def test_prior_only_exact_even_median_and_current_session_exclusion() -> None:
    history = _history(prior_totals=tuple(range(1, 11)), current_total=11)
    signal = _strategy(candidate_id="irvd001-a01-b03", floor="2").signal(history)

    assert signal.baseline_session_days[-1] == date(2026, 1, 7)
    assert date(2026, 1, 8) not in signal.baseline_session_days
    assert signal.qqq_prior_cumulative_volumes == tuple(range(1, 11))
    assert signal.spy_prior_cumulative_volumes == tuple(range(1, 11))
    assert signal.qqq_baseline_median == Decimal("5.5")
    assert signal.spy_baseline_median == Decimal("5.5")
    assert signal.qqq_current_cumulative_volume == 11
    assert signal.qqq_relative_volume == Decimal("2")
    assert signal.active is True

    future = _history(
        prior_totals=tuple(range(1, 11)),
        current_total=11,
        current_bar_count=40,
    )
    future_signal = _strategy(candidate_id="irvd001-a01-b03", floor="2").signal(future)
    assert future_signal.baseline_session_days == signal.baseline_session_days
    assert future_signal.qqq_current_cumulative_volume == 11
    assert future_signal.qqq_relative_volume == signal.qqq_relative_volume


def test_cold_start_alignment_and_nonpositive_baseline_fail_closed() -> None:
    cold = _history(prior_totals=(10,) * 9)
    assert _strategy().signal(cold).inactive_reason == "lookback-ineligible"

    misaligned = _history()
    misaligned[_QQQ] = misaligned[_QQQ][:-2] + misaligned[_QQQ][-1:]
    with pytest.raises(ValueError, match="aligned"):
        _strategy().signal(misaligned)

    with pytest.raises(ValueError, match="baseline must be positive"):
        _strategy().signal(_history(prior_totals=(0,) * 10))


def test_joint_return_and_relative_volume_boundaries_are_inclusive() -> None:
    at_boundary = _history(
        current_total=12,
        current_return_bps=(Decimal("15"), Decimal("15")),
    )
    signal = _strategy().signal(at_boundary)
    assert signal.joint_return_passed is True
    assert signal.joint_relative_volume_passed is True
    assert signal.qqq_relative_volume == Decimal("1.2")
    assert signal.spy_relative_volume == Decimal("1.2")
    assert set(_targets(_strategy(), at_boundary).values()) == {Decimal("0.5")}

    return_fail = _history(
        current_total=12,
        current_return_bps=(Decimal("14.999"), Decimal("15")),
    )
    assert _strategy().signal(return_fail).inactive_reason == "inactive-joint-return"

    volume_fail = _history(
        current_total=0,
        current_return_bps=(Decimal("15"), Decimal("15")),
    )
    volume_signal = _strategy().signal(volume_fail)
    assert volume_signal.qqq_relative_volume == Decimal("0")
    assert volume_signal.inactive_reason == "inactive-joint-relative-volume"


def test_early_close_capacity_and_fixed_hold_lifecycle() -> None:
    early_day = date(2025, 11, 28)
    early = _history(
        day=early_day,
        current_total=20,
        current_bar_count=len(_session_timestamps(early_day)),
    )
    assert _strategy().signal(early).qualifying_signal is True
    assert (
        _strategy(candidate_id="irvd001-a02-b01", horizon=16).signal(early).inactive_reason
        == "hold-capacity-ineligible"
    )
    assert (
        _strategy(candidate_id="irvd001-a03-b01", horizon=24).signal(early).inactive_reason
        == "hold-capacity-ineligible"
    )

    active = _history(current_bar_count=31)
    exit_now = _history(current_bar_count=32)
    after_exit = _history(current_bar_count=50)
    assert set(_targets(_strategy(), active).values()) == {Decimal("0.5")}
    assert set(_targets(_strategy(), exit_now).values()) == {Decimal("0")}
    assert set(_targets(_strategy(), after_exit).values()) == {Decimal("0")}
    assert _strategy().signal(exit_now).inactive_reason == "fixed-hold-complete"


@pytest.mark.parametrize(
    ("candidate_id", "horizon", "floor"),
    [
        ("irvd001-a04-b01", 8, "1.2"),
        ("irvd001-a01-b01-extra", 8, "1.2"),
        ("irvd001-a01-b01", 16, "1.2"),
        ("irvd001-a01-b01", 8, "1.5"),
    ],
)
def test_candidate_identity_binds_exact_axes(candidate_id: str, horizon: int, floor: str) -> None:
    with pytest.raises(ValueError, match="candidate identity"):
        _strategy(candidate_id=candidate_id, horizon=horizon, floor=floor)


def test_context_session_is_seed_only_and_never_targets() -> None:
    history = _history()
    strategy = _strategy(evaluation_start=datetime(2026, 1, 9, 14, 30, tzinfo=UTC))
    assert strategy.signal(history).inactive_reason == "context-only-session"
    assert set(_targets(strategy, history).values()) == {Decimal("0")}
