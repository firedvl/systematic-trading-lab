from __future__ import annotations

from dataclasses import replace
from datetime import time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from systematic_trading_lab.domain import Symbol
from systematic_trading_lab.multi_hour_sector_etf_features import (
    aggregate_30_minute_bars,
    build_selection_trace,
)
from systematic_trading_lab.multi_hour_sector_etf_plan import (
    REVIEWED_ACQUISITION_PLAN_SHA256,
    REVIEWED_PLAN_FINGERPRINT,
    REVIEWED_PLAN_SHA256,
    load_program_002_acquisition_plan,
    load_program_002_plan,
)
from systematic_trading_lab.multi_hour_sector_etf_synthetic import (
    build_synthetic_program_002_fixture,
)

_REPOSITORY = Path(__file__).resolve().parents[2]
_NEW_YORK = ZoneInfo("America/New_York")


def test_strict_plan_loader_binds_exact_reviewed_contracts() -> None:
    plan = load_program_002_plan(_REPOSITORY)
    acquisition = load_program_002_acquisition_plan(_REPOSITORY)

    assert plan.sha256 == REVIEWED_PLAN_SHA256
    assert plan.plan_fingerprint == REVIEWED_PLAN_FINGERPRINT
    assert acquisition.sha256 == REVIEWED_ACQUISITION_PLAN_SHA256
    assert len(plan.configurations) == 8
    assert plan.context_symbol == Symbol("SPY")
    assert plan.context_symbol not in plan.ranking_symbols


def test_six_source_bars_aggregate_exact_ohlcv_and_close_label() -> None:
    fixture = build_synthetic_program_002_fixture()
    source = tuple(
        bar
        for bar in fixture.bars
        if bar.symbol == Symbol("IWM")
        and bar.timestamp.astimezone(_NEW_YORK).date() == fixture.normal_day
    )[:6]
    source = tuple(
        replace(
            bar,
            open=Decimal(index + 1),
            high=Decimal(index + 3),
            low=Decimal(index + 1),
            close=Decimal(index + 2),
            volume=index + 1,
        )
        for index, bar in enumerate(source)
    )

    result = aggregate_30_minute_bars(source)

    assert len(result) == 1
    assert result[0].open == Decimal("1")
    assert result[0].high == Decimal("8")
    assert result[0].low == Decimal("1")
    assert result[0].close == Decimal("7")
    assert result[0].volume == 21
    assert result[0].timestamp.astimezone(_NEW_YORK).time() == time(10)


def test_1130_trace_uses_spy_relative_decimals_volume_ranks_and_symbol_ties() -> None:
    fixture = build_synthetic_program_002_fixture()
    plan = load_program_002_plan(_REPOSITORY)
    trace = build_selection_trace(
        fixture.bars,
        fixture.normal_day,
        plan.configurations["src-v1-l1-h4"],
    )
    features = {feature.symbol.value: feature for feature in trace.ordered_features}

    assert trace.decision_timestamp.astimezone(_NEW_YORK).time() == time(11, 30)
    assert trace.latest_source_bar_open.astimezone(_NEW_YORK).time() == time(11, 25)
    assert trace.selected_symbols == (Symbol("IWM"), Symbol("MDY"), Symbol("XLB"))
    assert "SPY" not in features
    assert set(features) == {symbol.value for symbol in plan.ranking_symbols}
    assert features["IWM"].lookback_return == Decimal("0.012")
    assert features["IWM"].spy_return == Decimal("0.002")
    assert features["IWM"].residual_return == Decimal("0.010")
    assert features["IWM"].same_clock_relative_volume == Decimal("1.2")
    assert features["IWM"].rank < features["MDY"].rank
    assert features["IWM"].residual_return == features["MDY"].residual_return


def test_reversal_threshold_and_rank_are_exact_and_spy_is_never_selected() -> None:
    fixture = build_synthetic_program_002_fixture()
    plan = load_program_002_plan(_REPOSITORY)
    trace = build_selection_trace(
        fixture.bars,
        fixture.normal_day,
        plan.configurations["srr-v1-l1-h4"],
    )
    features = {feature.symbol.value: feature for feature in trace.ordered_features}

    assert trace.selected_symbols == (Symbol("XLF"), Symbol("XLE"))
    assert features["XLE"].residual_return == Decimal("-0.001")
    assert features["XLE"].same_clock_relative_volume == Decimal("1.5")
    assert Symbol("SPY") not in trace.selected_symbols


def test_30_and_60_minute_lookbacks_use_different_completed_bucket_closes() -> None:
    fixture = build_synthetic_program_002_fixture()
    plan = load_program_002_plan(_REPOSITORY)
    changed = tuple(
        replace(bar, high=Decimal("200"), close=Decimal("200"))
        if bar.symbol == Symbol("IWM")
        and bar.timestamp.astimezone(_NEW_YORK).date() == fixture.normal_day
        and bar.timestamp.astimezone(_NEW_YORK).time() == time(10, 55)
        else bar
        for bar in fixture.bars
    )

    thirty = build_selection_trace(changed, fixture.normal_day, plan.configurations["src-v1-l1-h4"])
    sixty = build_selection_trace(changed, fixture.normal_day, plan.configurations["src-v1-l2-h4"])
    thirty_iwm = next(
        feature for feature in thirty.ordered_features if feature.symbol.value == "IWM"
    )
    sixty_iwm = next(feature for feature in sixty.ordered_features if feature.symbol.value == "IWM")

    assert thirty_iwm.lookback_return == Decimal("-0.494")
    assert sixty_iwm.lookback_return == Decimal("0.012")


def test_bars_opening_at_or_after_1130_cannot_change_the_decision() -> None:
    fixture = build_synthetic_program_002_fixture()
    configuration = load_program_002_plan(_REPOSITORY).configurations["src-v1-l1-h4"]
    original = build_selection_trace(fixture.bars, fixture.normal_day, configuration)
    changed = tuple(
        replace(
            bar,
            open=bar.open * 2,
            high=bar.high * 2,
            low=bar.low * 2,
            close=bar.close * 2,
            volume=bar.volume * 3,
        )
        if bar.timestamp.astimezone(_NEW_YORK).date() == fixture.normal_day
        and bar.timestamp.astimezone(_NEW_YORK).time() >= time(11, 30)
        else bar
        for bar in fixture.bars
    )

    replay = build_selection_trace(changed, fixture.normal_day, configuration)

    assert replay == original


@pytest.mark.parametrize("defect", ("missing-bar", "missing-symbol", "duplicate"))
def test_missing_symbol_bar_or_duplicate_fails_the_complete_input(defect: str) -> None:
    fixture = build_synthetic_program_002_fixture()
    configuration = load_program_002_plan(_REPOSITORY).configurations["src-v1-l1-h4"]
    target = next(
        bar
        for bar in fixture.bars
        if bar.symbol == Symbol("IWM")
        and bar.timestamp.astimezone(_NEW_YORK).date() == fixture.normal_day
    )
    if defect == "missing-bar":
        bars = tuple(bar for bar in fixture.bars if bar != target)
    elif defect == "missing-symbol":
        bars = tuple(
            bar
            for bar in fixture.bars
            if not (
                bar.symbol == Symbol("XLY")
                and bar.timestamp.astimezone(_NEW_YORK).date() == fixture.normal_day
            )
        )
    else:
        bars = (*fixture.bars, target)

    with pytest.raises(ValueError, match="missing|thirteen|duplicate"):
        build_selection_trace(bars, fixture.normal_day, configuration)


def test_nonpositive_prior_volume_denominator_fails_instead_of_shrinking_rank() -> None:
    fixture = build_synthetic_program_002_fixture()
    configuration = load_program_002_plan(_REPOSITORY).configurations["src-v1-l1-h4"]
    bars = tuple(
        replace(bar, volume=0)
        if bar.timestamp.astimezone(_NEW_YORK).date() in fixture.prior_days
        else bar
        for bar in fixture.bars
    )

    with pytest.raises(ValueError, match="denominator"):
        build_selection_trace(bars, fixture.normal_day, configuration)


def test_early_close_is_flat_but_passes_complete_context_validation() -> None:
    fixture = build_synthetic_program_002_fixture()
    configuration = load_program_002_plan(_REPOSITORY).configurations["src-v1-l1-h8"]
    trace = build_selection_trace(fixture.bars, fixture.early_close_day, configuration)

    assert trace.selected_symbols == ()
    assert trace.inactive_reason == "early-close-session"
