from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from systematic_trading_lab.domain import OHLCVBar, Symbol
from systematic_trading_lab.intraday_spy_qqq_lead_lag_001_strategies import (
    SpyQqqLeadLagStrategy,
)

_QQQ, _SPY = Symbol("QQQ"), Symbol("SPY")


def _bar(symbol: Symbol, timestamp: datetime, price: str) -> OHLCVBar:
    value = Decimal(price)
    return OHLCVBar(symbol, timestamp, value, value, value, value, 100)


def _history(
    spy: tuple[str, ...],
    qqq: tuple[str, ...],
    start: datetime = datetime(2026, 1, 8, 14, 30, tzinfo=UTC),
) -> dict[Symbol, tuple[OHLCVBar, ...]]:
    return {
        symbol: tuple(
            _bar(symbol, start + timedelta(minutes=5 * index), value)
            for index, value in enumerate(values)
        )
        for symbol, values in ((_SPY, spy), (_QQQ, qqq))
    }


def _targets(
    strategy: SpyQqqLeadLagStrategy, history: dict[Symbol, tuple[OHLCVBar, ...]]
) -> dict[Symbol, Decimal]:
    return {
        target.symbol: target.weight
        for target in strategy.on_session((history[_QQQ][-1], history[_SPY][-1]), history)
    }


def _strategy(floor: str = "10") -> SpyQqqLeadLagStrategy:
    return SpyQqqLeadLagStrategy(
        "isqlll001-a01-b01",
        6,
        Decimal(floor),
        datetime(2026, 1, 8, 14, 30, tzinfo=UTC),
    )


def test_signal_uses_only_completed_horizon_bars() -> None:
    before = _history(("100",) * 5, ("100",) * 5)
    qualifying = _history(("100",) * 5 + ("100.10",), ("100",) * 6)
    future_changed = _history(("100",) * 5 + ("100.10", "50"), ("100",) * 7)

    assert set(_targets(_strategy(), before).values()) == {Decimal("0")}
    assert _targets(_strategy(), qualifying) == {_QQQ: Decimal("0.5"), _SPY: Decimal("0")}
    assert _targets(_strategy(), future_changed) == {_QQQ: Decimal("0.5"), _SPY: Decimal("0")}


def test_inclusive_floor_and_qqq_boundaries() -> None:
    spy = ("100",) * 5 + ("100.10",)
    at_upper = _history(spy, ("100",) * 5 + ("100.05",))
    negative = _history(spy, ("100",) * 5 + ("99.99",))
    above_upper = _history(spy, ("100",) * 5 + ("100.050001",))

    assert _targets(_strategy(), at_upper) == {_QQQ: Decimal("0.5"), _SPY: Decimal("0")}
    assert set(_targets(_strategy(), negative).values()) == {Decimal("0")}
    assert set(_targets(_strategy(), above_upper).values()) == {Decimal("0")}


def test_fixed_exit_has_no_resize_or_reentry() -> None:
    active = _history(("100",) * 5 + ("100.10",) + ("50",) * 22, ("100",) * 28)
    exit_now = _history(("100",) * 5 + ("100.10",) + ("50",) * 24, ("100",) * 30)

    assert _targets(_strategy(), active) == {_QQQ: Decimal("0.5"), _SPY: Decimal("0")}
    assert _targets(_strategy(), exit_now) == {_QQQ: Decimal("0"), _SPY: Decimal("0")}
    assert _strategy().signal(exit_now).inactive_reason == "fixed-hold-complete"


def test_short_and_misaligned_histories_fail_closed() -> None:
    short = _history(("100",) * 5, ("100",) * 5)
    missing = _history(("100",) * 6, ("100",) * 6)
    missing[_QQQ] = missing[_QQQ][:3] + missing[_QQQ][4:]

    assert set(_targets(_strategy(), short).values()) == {Decimal("0")}
    with pytest.raises(ValueError, match="exact XNYS regular-session prefix"):
        _targets(_strategy(), missing)


def test_signal_evidence_is_immutable_and_bucketed() -> None:
    history = _history(("100",) * 5 + ("100.10",), ("100",) * 5 + ("100.02",))
    signal = _strategy().signal(history)

    assert signal.under_response_bucket == "under-response-1-6-to-1-3"
    with pytest.raises(AttributeError):
        signal.active = False  # type: ignore[misc]


def test_full_session_capacity_is_checked_before_entry() -> None:
    early_close = datetime(2025, 11, 28, 14, 30, tzinfo=UTC)
    short_session = _history(
        ("100",) * 17 + ("100.10",),
        ("100",) * 18,
        early_close,
    )
    normal_session = _history(("100",) * 17 + ("100.10",), ("100",) * 18)
    strategy = SpyQqqLeadLagStrategy(
        "isqlll001-a03-b01",
        18,
        Decimal("10"),
        datetime(2025, 1, 1, tzinfo=UTC),
    )

    assert strategy.signal(short_session).inactive_reason == "hold-capacity-ineligible"
    assert set(_targets(strategy, short_session).values()) == {Decimal("0")}
    assert _targets(strategy, normal_session) == {_QQQ: Decimal("0.5"), _SPY: Decimal("0")}


def test_extended_hours_history_fails_closed() -> None:
    before_open = datetime(2026, 1, 8, 14, 25, tzinfo=UTC)
    history = _history(("100",) * 6, ("100",) * 6, before_open)

    with pytest.raises(ValueError, match="exact XNYS regular-session prefix"):
        _targets(_strategy(), history)


@pytest.mark.parametrize(
    ("candidate_id", "horizon", "floor"),
    [
        ("isqlll001-a04-b01", 6, "10"),
        ("isqlll001-a01-b01-extra", 6, "10"),
        ("isqlll001-a01-b01", 12, "10"),
        ("isqlll001-a01-b01", 6, "20"),
    ],
)
def test_candidate_identity_binds_exact_horizon_and_floor(
    candidate_id: str, horizon: int, floor: str
) -> None:
    with pytest.raises(ValueError, match="candidate identity"):
        SpyQqqLeadLagStrategy(
            candidate_id,
            horizon,
            Decimal(floor),
            datetime(2026, 1, 8, 14, 30, tzinfo=UTC),
        )


def test_negative_qqq_trace_retains_ratio_without_bucket() -> None:
    history = _history(("100",) * 5 + ("100.10",), ("100",) * 5 + ("99.99",))

    signal = _strategy().signal(history)

    assert signal.inactive_reason == "qqq-return-negative"
    assert signal.under_response_ratio == Decimal("-0.1")
    assert signal.under_response_bucket is None


def test_context_only_session_remains_flat() -> None:
    history = _history(("100",) * 5 + ("101",), ("100",) * 6)
    strategy = SpyQqqLeadLagStrategy(
        "isqlll001-a01-b01",
        6,
        Decimal("10"),
        datetime(2026, 1, 9, 14, 30, tzinfo=UTC),
    )

    assert strategy.signal(history).inactive_reason == "context-only-session"
    assert set(_targets(strategy, history).values()) == {Decimal("0")}
