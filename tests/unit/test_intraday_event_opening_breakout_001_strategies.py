from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from systematic_trading_lab.calendar import expected_bar_timestamps
from systematic_trading_lab.domain import OHLCVBar, Symbol, Timeframe
from systematic_trading_lab.intraday_event_opening_breakout_001_strategies import (
    ScheduledEventSpyOpeningBreakoutStrategy,
)
from systematic_trading_lab.intraday_execution_cost_model import (
    ExecutionCostScenario,
    RegulatoryFeeModel,
)
from systematic_trading_lab.intraday_exposed_002_engine import IntradayExposed002Engine

_QQQ, _SPY = Symbol("QQQ"), Symbol("SPY")
_START = datetime(2026, 1, 8, 14, 30, tzinfo=UTC)


def _bar(symbol: Symbol, index: int, high: str, close: str) -> OHLCVBar:
    opening = Decimal("100")
    return OHLCVBar(
        symbol,
        _START + timedelta(minutes=5 * index),
        opening,
        Decimal(high),
        min(opening, Decimal(close)),
        Decimal(close),
        1_000,
    )


def _history(
    spy: list[tuple[str, str]], qqq_close: str = "1"
) -> dict[Symbol, tuple[OHLCVBar, ...]]:
    return {
        _SPY: tuple(_bar(_SPY, index, high, close) for index, (high, close) in enumerate(spy)),
        _QQQ: tuple(_bar(_QQQ, index, "1000000", qqq_close) for index in range(len(spy))),
    }


def _strategy() -> ScheduledEventSpyOpeningBreakoutStrategy:
    return ScheduledEventSpyOpeningBreakoutStrategy(
        "ieb001-a01", Decimal("2"), frozenset({date(2026, 1, 8)}), _START
    )


def _targets(
    strategy: ScheduledEventSpyOpeningBreakoutStrategy,
    history: dict[Symbol, tuple[OHLCVBar, ...]],
) -> dict[Symbol, Decimal]:
    return {
        target.symbol: target.weight
        for target in strategy.on_session((history[_QQQ][-1], history[_SPY][-1]), history)
    }


def _spy_session(
    count: int, *, breakout_index: int | None = None, high_only: bool = False
) -> list[tuple[str, str]]:
    values = [("100", "100") for _ in range(count)]
    if high_only and count > 6:
        values[6] = ("101", "100")
    if breakout_index is not None and breakout_index < count:
        values[breakout_index] = ("100.1", "100.02")
    return values


def test_waits_for_range_then_uses_close_equality_not_high_only_breach() -> None:
    strategy = _strategy()
    before_range = _history(_spy_session(5))
    high_only = _history(_spy_session(7, high_only=True))
    equality = _history(_spy_session(7, breakout_index=6))

    assert _targets(strategy, before_range) == {_QQQ: Decimal("0"), _SPY: Decimal("0")}
    assert _targets(strategy, high_only) == {_QQQ: Decimal("0"), _SPY: Decimal("0")}
    assert _targets(strategy, equality) == {_QQQ: Decimal("0"), _SPY: Decimal("0.5")}
    signal = strategy.signal({symbol: bars for symbol, bars in equality.items()})
    assert (signal.opening_range_high, signal.breakout_threshold, signal.breakout_bar_index) == (
        Decimal("100"),
        Decimal("100.02"),
        6,
    )


def test_late_breakout_never_activates_and_one_entry_stays_active_until_exit() -> None:
    strategy = _strategy()
    late = _history(_spy_session(13, breakout_index=12))
    entered = _history(_spy_session(12, breakout_index=6))
    exit_history = _history(_spy_session(30, breakout_index=6))

    assert set(_targets(strategy, late).values()) == {Decimal("0")}
    assert _targets(strategy, entered) == {_QQQ: Decimal("0"), _SPY: Decimal("0.5")}
    assert _targets(strategy, exit_history) == {_QQQ: Decimal("0"), _SPY: Decimal("0")}


def test_qqq_prices_do_not_affect_spy_signal_or_zero_qqq_exposure() -> None:
    strategy = _strategy()
    spy = _spy_session(10, breakout_index=6)
    low_qqq = _history(spy, "0.0001")
    high_qqq = _history(spy, "999999")

    assert (
        _targets(strategy, low_qqq)
        == _targets(strategy, high_qqq)
        == {
            _QQQ: Decimal("0"),
            _SPY: Decimal("0.5"),
        }
    )
    assert (
        strategy.signal(low_qqq).breakout_bar_index == strategy.signal(high_qqq).breakout_bar_index
    )


def test_session_reset_and_context_or_non_event_sessions_stay_flat() -> None:
    strategy = _strategy()
    event = _history(_spy_session(10, breakout_index=6))
    context_start = ScheduledEventSpyOpeningBreakoutStrategy(
        "ieb001-a01", Decimal("2"), frozenset({date(2026, 1, 8)}), _START + timedelta(days=1)
    )
    no_event = ScheduledEventSpyOpeningBreakoutStrategy(
        "ieb001-a01", Decimal("2"), frozenset(), _START
    )
    next_day_start = _START + timedelta(days=1)
    next_day = {
        symbol: tuple(
            OHLCVBar(
                symbol,
                next_day_start + timedelta(minutes=5 * index),
                Decimal("100"),
                Decimal("100"),
                Decimal("100"),
                Decimal("100"),
                1_000,
            )
            for index in range(7)
        )
        for symbol in (_QQQ, _SPY)
    }

    assert _targets(context_start, event) == {_QQQ: Decimal("0"), _SPY: Decimal("0")}
    assert _targets(no_event, event) == {_QQQ: Decimal("0"), _SPY: Decimal("0")}
    assert _targets(strategy, next_day) == {_QQQ: Decimal("0"), _SPY: Decimal("0")}


def test_engine_makes_one_spy_entry_then_exits_at_the_frozen_noon_decision() -> None:
    bars: list[OHLCVBar] = []
    timestamps = expected_bar_timestamps(
        _START, datetime(2026, 1, 8, 20, 55, tzinfo=UTC), Timeframe.FIVE_MINUTES
    )
    for index, timestamp in enumerate(timestamps):
        spy_close = Decimal("100.02") if index == 6 else Decimal("100")
        bars.extend(
            (
                OHLCVBar(
                    _QQQ,
                    timestamp,
                    Decimal("100"),
                    Decimal("1000000"),
                    Decimal("100"),
                    Decimal("100"),
                    1_000,
                ),
                OHLCVBar(
                    _SPY,
                    timestamp,
                    Decimal("100"),
                    max(Decimal("100"), spy_close),
                    Decimal("100"),
                    spy_close,
                    1_000,
                ),
            )
        )
    fees = RegulatoryFeeModel(
        "fees", "America/New_York", Decimal("0"), Decimal("0"), Decimal("1"), Decimal("0")
    )
    scenario = ExecutionCostScenario(
        "normal", None, {_QQQ: Decimal("0"), _SPY: Decimal("0")}, 1, fees.model_id
    )
    result = IntradayExposed002Engine(Decimal("100000"), scenario, fees).run(
        tuple(bars), _strategy()
    )

    assert len(result.round_trips) == 1
    assert result.round_trips[0].symbol == _SPY
    assert {fill.symbol for fill in result.fills} == {_SPY}
    assert [fill.fill_timestamp for fill in result.fills] == [timestamps[7], timestamps[30]]
