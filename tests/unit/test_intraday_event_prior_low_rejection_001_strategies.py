from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from systematic_trading_lab.calendar import expected_bar_timestamps
from systematic_trading_lab.domain import OHLCVBar, Symbol, Timeframe
from systematic_trading_lab.intraday_event_prior_low_rejection_001_strategies import (
    ScheduledEventSpyPriorLowRejectionStrategy,
)

_QQQ, _SPY = Symbol("QQQ"), Symbol("SPY")
_EVENT = date(2026, 1, 8)


def _bar(symbol: Symbol, timestamp: datetime, *, low: str = "100", close: str = "100") -> OHLCVBar:
    price_low, price_close = Decimal(low), Decimal(close)
    return OHLCVBar(
        symbol,
        timestamp,
        Decimal("100"),
        max(Decimal("100"), price_close),
        price_low,
        price_close,
        1_000,
    )


def _history(
    event_lows: dict[int, str] | None = None,
    event_closes: dict[int, str] | None = None,
    *,
    event_day: date = _EVENT,
    qqq_close: str = "100",
    event_until: int = 12,
) -> dict[Symbol, tuple[OHLCVBar, ...]]:
    start = datetime.combine(event_day - timedelta(days=7), datetime.min.time(), UTC)
    end = datetime.combine(event_day, datetime.max.time(), UTC)
    timestamps = expected_bar_timestamps(start, end, Timeframe.FIVE_MINUTES)
    event_timestamps = [timestamp for timestamp in timestamps if timestamp.date() == event_day]
    result: dict[Symbol, list[OHLCVBar]] = {_QQQ: [], _SPY: []}
    event_lows, event_closes = event_lows or {}, event_closes or {}
    for timestamp in timestamps:
        index = event_timestamps.index(timestamp) if timestamp in event_timestamps else None
        if index is not None and index > event_until:
            continue
        low = event_lows.get(index, "100") if index is not None else "100"
        close = event_closes.get(index, "100") if index is not None else "100"
        result[_SPY].append(_bar(_SPY, timestamp, low=low, close=close))
        result[_QQQ].append(_bar(_QQQ, timestamp, low="1", close=qqq_close))
    return {symbol: tuple(bars) for symbol, bars in result.items()}


def _strategy(confirmation_bars: int = 1) -> ScheduledEventSpyPriorLowRejectionStrategy:
    return ScheduledEventSpyPriorLowRejectionStrategy(
        f"ieplr001-a{confirmation_bars:02d}",
        confirmation_bars,
        frozenset({_EVENT}),
        datetime(2026, 1, 8, 14, 30, tzinfo=UTC),
    )


def _targets(
    strategy: ScheduledEventSpyPriorLowRejectionStrategy,
    history: dict[Symbol, tuple[OHLCVBar, ...]],
) -> dict[Symbol, Decimal]:
    return {
        target.symbol: target.weight
        for target in strategy.on_session((history[_QQQ][-1], history[_SPY][-1]), history)
    }


def test_strict_breach_and_reclaim_boundaries() -> None:
    equality_breach = _history({2: "100"}, {6: "101"})
    equality_reclaim = _history({2: "99"}, {6: "100"})
    active = _history({2: "99"}, {6: "101"})

    assert set(_targets(_strategy(), equality_breach).values()) == {Decimal("0")}
    assert set(_targets(_strategy(), equality_reclaim).values()) == {Decimal("0")}
    assert _targets(_strategy(), active) == {_QQQ: Decimal("0"), _SPY: Decimal("0.5")}
    signal = _strategy().signal(active)
    assert (
        signal.prior_session_low,
        signal.opening_window_low,
        signal.opening_window_breach,
        signal.reclaim_decision_bar_index,
        signal.reclaim_decision_timestamp,
    ) == (Decimal("100"), Decimal("99"), True, 6, datetime(2026, 1, 8, 15, 5, tzinfo=UTC))


def test_confirmation_runs_obey_n_boundaries_and_monitor_window() -> None:
    two = _history({0: "99"}, {6: "101", 7: "101"})
    broken = _history({0: "99"}, {6: "101", 7: "100", 8: "101"})
    crosses_monitor_start = _history({0: "99"}, {4: "101", 5: "101", 6: "101"})
    late_breach = _history({6: "99"}, {7: "101"})
    late_reclaim = _history({0: "99"}, {12: "101", 13: "101", 14: "101"})

    assert _strategy(2).signal(two).reclaim_decision_bar_index == 7
    assert _strategy(3).signal(two).active is False
    assert _strategy(2).signal(broken).active is False
    assert _strategy(3).signal(crosses_monitor_start).active is False
    assert _strategy().signal(late_breach).active is False
    assert _strategy(3).signal(late_reclaim).active is False


def test_context_or_non_event_stays_flat_without_prior_lookup() -> None:
    timestamp = datetime(2026, 1, 8, 14, 30, tzinfo=UTC)
    current: dict[Symbol, tuple[OHLCVBar, ...]] = {
        symbol: (_bar(symbol, timestamp),) for symbol in (_QQQ, _SPY)
    }
    context = ScheduledEventSpyPriorLowRejectionStrategy(
        "ieplr001-a01", 1, frozenset({_EVENT}), datetime(2026, 1, 9, 14, 30, tzinfo=UTC)
    )
    no_event = ScheduledEventSpyPriorLowRejectionStrategy("ieplr001-a01", 1, frozenset(), timestamp)

    assert _targets(context, current) == {_QQQ: Decimal("0"), _SPY: Decimal("0")}
    assert _targets(no_event, current) == {_QQQ: Decimal("0"), _SPY: Decimal("0")}


def test_qqq_is_invariant_and_prior_sessions_must_be_complete_aligned() -> None:
    active = _history({0: "99"}, {6: "101"})
    changed_qqq = _history({0: "99"}, {6: "101"}, qqq_close="999999")
    previous_day = max(
        bar.timestamp.date() for bar in active[_SPY] if bar.timestamp.date() < _EVENT
    )
    missing_first = {
        symbol: tuple(
            bar
            for bar in bars
            if bar.timestamp.date() != previous_day
            or bar.timestamp
            != min(item.timestamp for item in bars if item.timestamp.date() == previous_day)
        )
        for symbol, bars in active.items()
    }
    missing_final = {
        symbol: tuple(
            bar
            for bar in bars
            if bar.timestamp.date() != previous_day
            or bar.timestamp
            != max(item.timestamp for item in bars if item.timestamp.date() == previous_day)
        )
        for symbol, bars in active.items()
    }
    current_mismatch = dict(active)
    current_mismatch[_QQQ] = current_mismatch[_QQQ][:-1]
    prior_mismatch = dict(active)
    prior_mismatch[_QQQ] = tuple(
        bar
        for bar in prior_mismatch[_QQQ]
        if bar.timestamp.date() != previous_day
        or bar.timestamp
        != min(
            item.timestamp for item in prior_mismatch[_QQQ] if item.timestamp.date() == previous_day
        )
    )

    assert (
        _targets(_strategy(), active)
        == _targets(_strategy(), changed_qqq)
        == {_QQQ: Decimal("0"), _SPY: Decimal("0.5")}
    )
    with pytest.raises(ValueError, match="prior session is incomplete or misaligned"):
        _targets(_strategy(), missing_first)
    with pytest.raises(ValueError, match="prior session is incomplete or misaligned"):
        _targets(_strategy(), missing_final)
    with pytest.raises(ValueError, match="aligned current bars"):
        _targets(_strategy(), current_mismatch)
    with pytest.raises(ValueError, match="aligned histories"):
        _targets(_strategy(), prior_mismatch)


def test_early_close_prior_session_uses_the_full_exchange_schedule() -> None:
    event_day = date(2025, 7, 7)
    history = _history({0: "99"}, {6: "101"}, event_day=event_day)
    strategy = ScheduledEventSpyPriorLowRejectionStrategy(
        "ieplr001-a01", 1, frozenset({event_day}), datetime(2025, 7, 7, 13, 30, tzinfo=UTC)
    )

    assert _targets(strategy, history) == {_QQQ: Decimal("0"), _SPY: Decimal("0.5")}


def test_holiday_previous_session_and_bar_29_exit() -> None:
    event_day = date(2026, 1, 20)
    history = _history({0: "99"}, {6: "101"}, event_day=event_day, event_until=29)
    strategy = ScheduledEventSpyPriorLowRejectionStrategy(
        "ieplr001-a01", 1, frozenset({event_day}), datetime(2026, 1, 20, 14, 30, tzinfo=UTC)
    )

    assert _targets(strategy, history) == {_QQQ: Decimal("0"), _SPY: Decimal("0")}
    assert _targets(strategy, history) == {_QQQ: Decimal("0"), _SPY: Decimal("0")}
