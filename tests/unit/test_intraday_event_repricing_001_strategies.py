from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from systematic_trading_lab.calendar import expected_bar_timestamps
from systematic_trading_lab.domain import OHLCVBar, Symbol, Timeframe
from systematic_trading_lab.intraday_event_repricing_001_strategies import (
    ScheduledEventRelativeLeaderStrategy,
)
from systematic_trading_lab.intraday_execution_cost_model import (
    ExecutionCostScenario,
    RegulatoryFeeModel,
)
from systematic_trading_lab.intraday_exposed_002_engine import IntradayExposed002Engine

_QQQ, _SPY = Symbol("QQQ"), Symbol("SPY")


def _bar(symbol: Symbol, timestamp: datetime, opening: Decimal, closing: Decimal) -> OHLCVBar:
    return OHLCVBar(
        symbol, timestamp, opening, max(opening, closing), min(opening, closing), closing, 1_000
    )


def _history(qqq: tuple[str, ...], spy: tuple[str, ...]) -> dict[Symbol, tuple[OHLCVBar, ...]]:
    start = datetime(2026, 1, 8, 14, 30, tzinfo=UTC)
    return {
        symbol: tuple(
            _bar(
                symbol,
                start.replace(minute=start.minute + 5 * index),
                Decimal("100"),
                Decimal(close),
            )
            for index, close in enumerate(closes)
        )
        for symbol, closes in ((_QQQ, qqq), (_SPY, spy))
    }


def _targets(
    strategy: ScheduledEventRelativeLeaderStrategy, history: dict[Symbol, tuple[OHLCVBar, ...]]
) -> dict[Symbol, Decimal]:
    return {
        target.symbol: target.weight
        for target in strategy.on_session((history[_QQQ][-1], history[_SPY][-1]), history)
    }


def _strategy(arm: str, threshold: str = "5") -> ScheduledEventRelativeLeaderStrategy:
    return ScheduledEventRelativeLeaderStrategy(
        "ier001-a01-b01",
        3,
        Decimal(threshold),
        frozenset({date(2026, 1, 8)}),
        datetime(2026, 1, 8, 14, 30, tzinfo=UTC),
        arm,
    )


def test_positive_and_negative_reactions_select_opposite_long_arms() -> None:
    positive = _history(("100", "100", "100.2"), ("100", "100", "100.05"))
    negative = _history(("100", "100", "100.05"), ("100", "100", "100.2"))

    assert _targets(_strategy("leader"), positive) == {_QQQ: Decimal("0.5"), _SPY: Decimal("0")}
    assert _targets(_strategy("laggard-control"), positive) == {
        _QQQ: Decimal("0"),
        _SPY: Decimal("0.5"),
    }
    assert _targets(_strategy("leader"), negative) == {_QQQ: Decimal("0"), _SPY: Decimal("0.5")}
    assert _targets(_strategy("laggard-control"), negative) == {
        _QQQ: Decimal("0.5"),
        _SPY: Decimal("0"),
    }


def test_subthreshold_and_zero_reactions_stay_flat() -> None:
    subthreshold = _history(("100", "100", "100.04"), ("100", "100", "100"))
    zero = _history(("100", "100", "100"), ("100", "100", "100"))

    assert set(_targets(_strategy("leader", "5"), subthreshold).values()) == {Decimal("0")}
    assert set(_targets(_strategy("leader"), zero).values()) == {Decimal("0")}


def test_engine_holds_exactly_24_fill_to_fill_bars_and_exits_before_early_close() -> None:
    start = datetime(2025, 7, 2, 13, 30, tzinfo=UTC)
    end = datetime(2025, 7, 3, 16, 55, tzinfo=UTC)
    bars: list[OHLCVBar] = []
    indices: dict[date, int] = {}
    for timestamp in expected_bar_timestamps(start, end, Timeframe.FIVE_MINUTES):
        index = indices.get(timestamp.date(), 0)
        indices[timestamp.date()] = index + 1
        for symbol in (_QQQ, _SPY):
            opening = Decimal("100")
            closing = Decimal("100")
            if timestamp.date() == date(2025, 7, 3):
                closing = Decimal("100.2") if symbol == _QQQ and index >= 2 else Decimal("100")
            bars.append(_bar(symbol, timestamp, opening, closing))
    strategy = ScheduledEventRelativeLeaderStrategy(
        "ier001-a01-b01",
        3,
        Decimal("5"),
        frozenset({date(2025, 7, 3)}),
        datetime(2025, 7, 3, 13, 30, tzinfo=UTC),
        "leader",
    )
    fees = RegulatoryFeeModel(
        "fees", "America/New_York", Decimal("0"), Decimal("0"), Decimal("1"), Decimal("0")
    )
    scenario = ExecutionCostScenario(
        "normal", None, {_QQQ: Decimal("0"), _SPY: Decimal("0")}, 3, fees.model_id
    )
    result = IntradayExposed002Engine(Decimal("100000"), scenario, fees).run(tuple(bars), strategy)

    assert len(result.round_trips) == 1
    trip = result.round_trips[0]
    assert trip.symbol == _QQQ
    assert trip.exit_timestamp - trip.entry_timestamp == Timeframe.FIVE_MINUTES.duration * 24
    assert trip.exit_timestamp < datetime(2025, 7, 3, 17, 0, tzinfo=UTC)
