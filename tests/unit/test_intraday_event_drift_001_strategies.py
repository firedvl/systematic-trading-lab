from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from systematic_trading_lab.calendar import expected_bar_timestamps
from systematic_trading_lab.domain import OHLCVBar, Symbol, Timeframe
from systematic_trading_lab.intraday_event_drift_001_strategies import (
    ScheduledBroadIndexPositiveDriftStrategy,
)
from systematic_trading_lab.intraday_execution_cost_model import (
    ExecutionCostScenario,
    RegulatoryFeeModel,
)
from systematic_trading_lab.intraday_exposed_002_engine import IntradayExposed002Engine

_QQQ, _SPY = Symbol("QQQ"), Symbol("SPY")


def _bar(
    symbol: Symbol,
    timestamp: datetime,
    *,
    open_price: str,
    close_price: str,
) -> OHLCVBar:
    opening = Decimal(open_price)
    closing = Decimal(close_price)
    return OHLCVBar(
        symbol,
        timestamp,
        opening,
        max(opening, closing),
        min(opening, closing),
        closing,
        1_000,
    )


def _history(
    qqq_closes: tuple[str, ...],
    spy_closes: tuple[str, ...],
    *,
    opening: str = "100.2",
) -> dict[Symbol, tuple[OHLCVBar, ...]]:
    prior = datetime(2026, 1, 7, 20, 55, tzinfo=UTC)
    current = datetime(2026, 1, 8, 14, 30, tzinfo=UTC)
    result: dict[Symbol, list[OHLCVBar]] = {_QQQ: [], _SPY: []}
    for symbol in result:
        result[symbol].append(_bar(symbol, prior, open_price="100", close_price="100"))
    for symbol, closes in ((_QQQ, qqq_closes), (_SPY, spy_closes)):
        result[symbol].extend(
            _bar(
                symbol,
                current + timedelta(minutes=5 * index),
                open_price=opening if index == 0 else closes[index - 1],
                close_price=close,
            )
            for index, close in enumerate(closes)
        )
    return {symbol: tuple(bars) for symbol, bars in result.items()}


def _weights(
    strategy: ScheduledBroadIndexPositiveDriftStrategy,
    history: dict[Symbol, tuple[OHLCVBar, ...]],
) -> dict[Symbol, Decimal]:
    targets = strategy.on_session(
        (history[_QQQ][-1], history[_SPY][-1]),
        history,
    )
    return {target.symbol: target.weight for target in targets}


def test_waits_for_completed_reaction_bars_then_enters_both_symbols() -> None:
    strategy = ScheduledBroadIndexPositiveDriftStrategy(
        candidate_id="ied001-a01-b02",
        reaction_bars=3,
        minimum_reaction_bps=Decimal("20"),
        event_sessions=frozenset({date(2026, 1, 8)}),
        evaluation_start=datetime(2026, 1, 8, 14, 30, tzinfo=UTC),
    )

    before = _history(("100.3", "100.4"), ("100.3", "100.4"))
    ready = _history(("100.3", "100.4", "100.5"), ("100.3", "100.4", "100.5"))

    assert set(_weights(strategy, before).values()) == {Decimal("0")}
    assert set(_weights(strategy, ready).values()) == {Decimal("0.5")}


def test_requires_each_symbol_to_pass_gap_and_reaction_floors() -> None:
    strategy = ScheduledBroadIndexPositiveDriftStrategy(
        candidate_id="ied001-a01-b02",
        reaction_bars=3,
        minimum_reaction_bps=Decimal("20"),
        event_sessions=frozenset({date(2026, 1, 8)}),
        evaluation_start=datetime(2026, 1, 8, 14, 30, tzinfo=UTC),
    )

    weak_reaction = _history(
        ("100.3", "100.4", "100.5"),
        ("100.2", "100.21", "100.21"),
    )
    weak_gap = _history(
        ("100.3", "100.4", "100.5"),
        ("100.1", "100.3", "100.4"),
        opening="100.05",
    )

    assert set(_weights(strategy, weak_reaction).values()) == {Decimal("0")}
    assert set(_weights(strategy, weak_gap).values()) == {Decimal("0")}


def test_stays_flat_outside_evaluation_or_event_and_exits_after_bar_60() -> None:
    event_strategy = ScheduledBroadIndexPositiveDriftStrategy(
        candidate_id="ied001-a01-b01",
        reaction_bars=3,
        minimum_reaction_bps=Decimal("10"),
        event_sessions=frozenset({date(2026, 1, 8)}),
        evaluation_start=datetime(2026, 1, 8, 14, 30, tzinfo=UTC),
    )
    context_strategy = ScheduledBroadIndexPositiveDriftStrategy(
        candidate_id="ied001-a01-b01",
        reaction_bars=3,
        minimum_reaction_bps=Decimal("10"),
        event_sessions=frozenset({date(2026, 1, 8)}),
        evaluation_start=datetime(2026, 1, 9, 14, 30, tzinfo=UTC),
    )
    no_event_strategy = ScheduledBroadIndexPositiveDriftStrategy(
        candidate_id="ied001-a01-b01",
        reaction_bars=3,
        minimum_reaction_bps=Decimal("10"),
        event_sessions=frozenset(),
        evaluation_start=datetime(2026, 1, 8, 14, 30, tzinfo=UTC),
    )
    active_history = _history(("100.5",) * 60, ("100.5",) * 60)
    exit_history = _history(("100.5",) * 61, ("100.5",) * 61)

    assert set(_weights(event_strategy, active_history).values()) == {Decimal("0.5")}
    assert set(_weights(event_strategy, exit_history).values()) == {Decimal("0")}
    assert set(_weights(context_strategy, active_history).values()) == {Decimal("0")}
    assert set(_weights(no_event_strategy, active_history).values()) == {Decimal("0")}


def test_zero_cost_preserves_decisions_and_early_close_flattens_jointly() -> None:
    start = datetime(2025, 7, 2, 13, 30, tzinfo=UTC)
    end = datetime(2025, 7, 3, 16, 55, tzinfo=UTC)
    bars: list[OHLCVBar] = []
    indices: dict[date, int] = {}
    for timestamp in expected_bar_timestamps(start, end, Timeframe.FIVE_MINUTES):
        day = timestamp.date()
        index = indices.get(day, 0)
        indices[day] = index + 1
        if day == date(2025, 7, 2):
            opening = closing = Decimal("100")
        else:
            opening = Decimal("100.2") if index == 0 else Decimal("100.5")
            closing = Decimal("100.3") + Decimal(index) / 10 if index < 3 else Decimal("101")
        bars.extend(
            OHLCVBar(
                symbol,
                timestamp,
                opening,
                max(opening, closing),
                min(opening, closing),
                closing,
                1_000,
            )
            for symbol in (_QQQ, _SPY)
        )
    fees = RegulatoryFeeModel(
        "alpaca-us-equity-regulatory-fees-2026-07-20-v1",
        "America/New_York",
        Decimal("0.0000206"),
        Decimal("0.000195"),
        Decimal("9.79"),
        Decimal("0.000003"),
    )
    strategy = ScheduledBroadIndexPositiveDriftStrategy(
        "ied001-a01-b01",
        3,
        Decimal("10"),
        frozenset({date(2025, 7, 3)}),
        datetime(2025, 7, 3, 13, 30, tzinfo=UTC),
    )
    normal = IntradayExposed002Engine(
        Decimal("100000"),
        ExecutionCostScenario(
            "normal", None, {_QQQ: Decimal("1"), _SPY: Decimal("1")}, 1, fees.model_id
        ),
        fees,
    ).run(tuple(bars), strategy)
    zero = IntradayExposed002Engine(
        Decimal("100000"),
        ExecutionCostScenario(
            "zero_cost_diagnostic", None, {_QQQ: Decimal("0"), _SPY: Decimal("0")}, 1, None
        ),
        fees,
    ).run(tuple(bars), strategy)

    assert normal.decisions == zero.decisions
    assert {fill.fill_timestamp for fill in normal.fills if fill.quantity < 0} == {
        datetime(2025, 7, 3, 16, 55, tzinfo=UTC)
    }
    assert len(normal.round_trips) == 2
    assert all(fill.adverse_slippage == 0 for fill in zero.fills)
