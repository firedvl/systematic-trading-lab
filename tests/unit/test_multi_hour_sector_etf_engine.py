from __future__ import annotations

from dataclasses import replace
from datetime import time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from systematic_trading_lab.domain import Symbol
from systematic_trading_lab.intraday_execution_cost_model import RegulatoryFeeModel
from systematic_trading_lab.multi_hour_sector_etf_engine import (
    Program002CostScenario,
    maximum_drawdown,
    replay_program_002_period,
    replay_program_002_session,
)
from systematic_trading_lab.multi_hour_sector_etf_features import (
    SelectionTrace,
    build_selection_trace,
)
from systematic_trading_lab.multi_hour_sector_etf_plan import load_program_002_plan
from systematic_trading_lab.multi_hour_sector_etf_synthetic import (
    SyntheticProgram002Fixture,
    build_synthetic_program_002_fixture,
)

_REPOSITORY = Path(__file__).resolve().parents[2]
_NEW_YORK = ZoneInfo("America/New_York")
_FEE_MODEL = RegulatoryFeeModel(
    "synthetic-program-002-fees-v1",
    "America/New_York",
    Decimal("0.0000206"),
    Decimal("0.000195"),
    Decimal("9.79"),
    Decimal("0.000003"),
)


def _trace(
    configuration_id: str = "src-v1-l1-h4",
) -> tuple[SyntheticProgram002Fixture, SelectionTrace]:
    fixture = build_synthetic_program_002_fixture()
    plan = load_program_002_plan(_REPOSITORY)
    return fixture, build_selection_trace(
        fixture.bars, fixture.normal_day, plan.configurations[configuration_id]
    )


def _scenario(*, delay: int = 1, spread: str = "0", fees: bool = False) -> Program002CostScenario:
    fixture = build_synthetic_program_002_fixture()
    symbols = {bar.symbol for bar in fixture.bars}
    return Program002CostScenario(
        f"synthetic-d{delay}-s{spread}-f{int(fees)}",
        {symbol: Decimal(spread) for symbol in symbols},
        delay,
        fees,
    )


def test_atomic_top_three_entry_and_participation_matched_benchmark() -> None:
    fixture, trace = _trace()
    replay = replay_program_002_session(trace, fixture.bars, _scenario(), None)
    buys = tuple(fill for fill in replay.candidate.fills if fill.side == "buy")
    sells = tuple(fill for fill in replay.candidate.fills if fill.side == "sell")

    assert tuple(fill.symbol for fill in buys) == trace.selected_symbols
    assert len(buys) == len(sells) == 3
    assert replay.candidate.common_scale == 1
    assert replay.candidate.accounting_identity_error == 0
    assert replay.candidate.final_cash > replay.candidate.initial_cash
    assert {fill.symbol for fill in replay.benchmark.fills} == {Symbol("SPY")}
    assert len(replay.benchmark.fills) == 2
    assert max(replay.capacity_ratios.values()) < 1


@pytest.mark.parametrize(
    ("delay", "entry", "exit_clock"),
    (
        (1, time(11, 35), time(13, 35)),
        (2, time(11, 40), time(13, 40)),
        (3, time(11, 45), time(13, 45)),
    ),
)
def test_delay_and_two_hour_hold_are_measured_from_actual_entry(
    delay: int, entry: time, exit_clock: time
) -> None:
    fixture, trace = _trace()
    replay = replay_program_002_session(trace, fixture.bars, _scenario(delay=delay), None)

    assert replay.entry_timestamp is not None and replay.exit_timestamp is not None
    assert replay.entry_timestamp.astimezone(_NEW_YORK).time() == entry
    assert replay.exit_timestamp.astimezone(_NEW_YORK).time() == exit_clock
    assert replay.exit_timestamp - replay.entry_timestamp == timedelta(
        minutes=30 * trace.hold_30m_bars
    )


@pytest.mark.parametrize("delay", (1, 2, 3))
def test_four_hour_hold_uses_1535_1540_1545_exits(delay: int) -> None:
    fixture, trace = _trace("src-v1-l1-h8")
    replay = replay_program_002_session(trace, fixture.bars, _scenario(delay=delay), None)

    assert replay.exit_timestamp is not None
    assert replay.exit_timestamp.astimezone(_NEW_YORK).time() == time(15, 30 + delay * 5)


def test_fee_reserve_uses_one_common_scale_and_keeps_cash_nonnegative() -> None:
    fixture, trace = _trace()
    replay = replay_program_002_session(
        trace, fixture.bars, _scenario(spread="0.25", fees=True), _FEE_MODEL
    )
    buys = tuple(fill for fill in replay.candidate.fills if fill.side == "buy")
    entry_cash = (
        replay.candidate.initial_cash
        - sum((fill.gross_notional for fill in buys), Decimal("0"))
        - replay.candidate.preliminary_fee_reserve
    )
    market_notionals = tuple(fill.quantity * fill.market_open for fill in buys)

    assert Decimal("0") < replay.candidate.common_scale < Decimal("1")
    assert replay.candidate.regulatory_fees > 0
    assert entry_cash >= 0
    assert max(market_notionals) - min(market_notionals) < Decimal("1e-20")
    assert sum(replay.candidate.regulatory_fee_by_trade.values()) == (
        replay.candidate.regulatory_fees
    )


def test_symbol_and_bar_order_cannot_change_quantities_cash_or_report_identity() -> None:
    fixture, trace = _trace()
    scenario = _scenario(spread="0.25", fees=True)
    forward = replay_program_002_session(trace, fixture.bars, scenario, _FEE_MODEL)
    reverse = replay_program_002_session(trace, tuple(reversed(fixture.bars)), scenario, _FEE_MODEL)

    assert forward == reverse


def test_higher_fixed_trace_cost_never_improves_net_profit() -> None:
    fixture, trace = _trace()
    zero = replay_program_002_session(trace, fixture.bars, _scenario(), None)
    costly = replay_program_002_session(
        trace, fixture.bars, _scenario(spread="1", fees=True), _FEE_MODEL
    )

    assert costly.candidate.net_profit < zero.candidate.net_profit
    assert costly.benchmark.net_profit < zero.benchmark.net_profit
    assert costly.candidate.adverse_spread_cost > 0


def test_one_two_three_positions_use_only_occupied_slots_without_rescaling() -> None:
    fixture, trace = _trace()
    final_cash: list[Decimal] = []
    for count in (1, 2, 3):
        selected = trace.selected_symbols[:count]
        replay = replay_program_002_session(
            replace(trace, selected_symbols=selected), fixture.bars, _scenario(), None
        )
        buys = tuple(fill for fill in replay.candidate.fills if fill.side == "buy")
        assert len(buys) == count
        assert len(replay.candidate.fills) == 2 * count
        final_cash.append(replay.candidate.final_cash)
    assert final_cash[0] < final_cash[1] < final_cash[2]


def test_missing_scheduled_fill_bar_and_capacity_breach_fail_closed() -> None:
    fixture, trace = _trace()
    missing = tuple(
        bar
        for bar in fixture.bars
        if not (
            bar.symbol == trace.selected_symbols[0]
            and bar.timestamp.astimezone(_NEW_YORK).date() == fixture.normal_day
            and bar.timestamp.astimezone(_NEW_YORK).time() == time(11, 35)
        )
    )
    with pytest.raises(ValueError, match="fill bar"):
        replay_program_002_session(trace, missing, _scenario(), None)

    first = replace(trace.ordered_features[0], prior_median_dollar_volume=Decimal("1"))
    constrained = replace(trace, ordered_features=(first, *trace.ordered_features[1:]))
    with pytest.raises(ValueError, match="capacity"):
        replay_program_002_session(constrained, fixture.bars, _scenario(), None)


def test_early_close_trace_stays_flat_without_fill_access() -> None:
    fixture = build_synthetic_program_002_fixture()
    configuration = load_program_002_plan(_REPOSITORY).configurations["src-v1-l1-h8"]
    trace = build_selection_trace(fixture.bars, fixture.early_close_day, configuration)
    replay = replay_program_002_session(trace, (), _scenario(), None)

    assert replay.candidate.fills == replay.benchmark.fills == ()
    assert replay.candidate.final_cash == replay.candidate.initial_cash
    assert replay.entry_timestamp is replay.exit_timestamp is None


def test_period_replay_carries_candidate_and_benchmark_cash_between_sessions() -> None:
    fixture, active = _trace()
    configuration = load_program_002_plan(_REPOSITORY).configurations["src-v1-l1-h4"]
    inactive = build_selection_trace(fixture.bars, fixture.early_close_day, configuration)

    replay = replay_program_002_period((active, inactive), fixture.bars, _scenario(), None)

    assert replay.sessions[1].candidate.initial_cash == replay.sessions[0].candidate.final_cash
    assert replay.sessions[1].benchmark.initial_cash == replay.sessions[0].benchmark.final_cash
    assert replay.candidate_final_cash == replay.sessions[1].candidate.final_cash
    assert replay.benchmark_final_cash == replay.sessions[1].benchmark.final_cash
    assert replay.candidate_return == replay.candidate_final_cash / Decimal("100000") - 1


def test_cost_scenario_requires_all_and_only_thirteen_symbols() -> None:
    scenario = _scenario()
    missing_spy = dict(scenario.slippage_bps_per_fill)
    del missing_spy[Symbol("SPY")]

    with pytest.raises(ValueError, match="spreads"):
        Program002CostScenario("missing-spy", missing_spy, 1, False)


def test_five_minute_marked_equity_derives_drawdown_and_exact_accounting() -> None:
    fixture, trace = _trace()
    bars = tuple(
        replace(bar, high=Decimal("101"), close=Decimal("101"))
        if bar.symbol in trace.selected_symbols
        and bar.timestamp == trace.decision_timestamp + timedelta(minutes=5)
        else bar
        for bar in fixture.bars
    )
    replay = replay_program_002_session(
        trace, bars, _scenario(spread="0.25", fees=True), _FEE_MODEL
    )

    curve = replay.candidate.equity_curve
    assert curve[0][0] == replay.entry_timestamp
    assert curve[-1] == (replay.exit_timestamp, replay.candidate.final_cash)
    assert len(curve) == 26
    assert curve[0][1] < curve[1][1]
    assert maximum_drawdown(replay.candidate) >= 0
    assert replay.candidate.accounting_identity_error == 0
