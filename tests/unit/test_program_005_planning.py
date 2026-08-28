from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, time
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

from systematic_trading_lab.calendar import expected_bar_timestamps, expected_sessions
from systematic_trading_lab.domain import Symbol, Timeframe
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.multi_hour_sector_etf_features import build_selection_trace
from systematic_trading_lab.multi_hour_sector_etf_plan import load_program_002_plan
from systematic_trading_lab.multi_hour_sector_etf_synthetic import (
    build_synthetic_program_002_fixture,
)

_REPOSITORY = Path(__file__).resolve().parents[2]
_PLAN_PATH = "config/research/program-005-free-alpaca-successor-plan-v1.json"
_SYMBOLS = (
    "IWM",
    "MDY",
    "SPY",
    "XLB",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
)


def _load(path: str) -> dict[str, Any]:
    value = json.loads((_REPOSITORY / path).read_text())
    assert isinstance(value, dict)
    return value


def _feature(trace: Any, symbol: str) -> Any:
    return next(item for item in trace.ordered_features if item.symbol == Symbol(symbol))


def test_program_005_plan_binds_lineage_and_grants_no_authority() -> None:
    plan = _load(_PLAN_PATH)
    unsigned = dict(plan)

    assert unsigned.pop("plan_fingerprint") == fingerprint(unsigned)
    assert plan["program_id"] == "multi-hour-sector-etf-research-004"
    assert plan["lineage"]["program_003_strategy_outcomes_generated_or_observed"] == 0
    assert plan["lineage"]["program_004_strategy_outcomes_generated_or_observed"] == 0
    assert plan["lineage"]["result_driven_adaptation"] is False
    assert plan["repository_state"]["marketparquet_purchase_occurred"] is False
    assert plan["repository_state"]["stale_runtime_exception"]["present"] is True

    predecessor = plan["predecessor_contract"]
    predecessor_path = _REPOSITORY / predecessor["plan_path"]
    predecessor_plan = json.loads(predecessor_path.read_text())
    assert sha256(predecessor_path.read_bytes()).hexdigest() == predecessor["plan_sha256"]
    assert predecessor_plan["plan_fingerprint"] == predecessor["plan_fingerprint"]

    review_path = _REPOSITORY / predecessor["review_path"]
    predecessor_review = json.loads(review_path.read_text())
    assert sha256(review_path.read_bytes()).hexdigest() == predecessor["review_sha256"]
    assert predecessor_review["review_fingerprint"] == predecessor["review_fingerprint"]

    hypothesis = plan["preserved_economic_contract"]
    assert hypothesis["ranking_and_trading_symbols"] == [
        symbol for symbol in _SYMBOLS if symbol != "SPY"
    ]
    assert hypothesis["context_and_benchmark_symbol"] == "SPY"
    assert hypothesis["configuration_count"] == 8
    assert hypothesis["lookback_minutes"] == [30, 60]
    assert hypothesis["hold_minutes"] == [120, 240]
    assert plan["search_budget"]["maximum_run_specifications"] == 232
    assert not any(plan["authority"].values())
    assert not any(plan["protected_access"].values())


def test_free_sip_contract_is_explicit_and_retention_stays_fail_closed() -> None:
    plan = _load(_PLAN_PATH)
    contract = plan["alpaca_basic_historical_sip_contract"]

    assert contract["price_usd_per_month"] == "0"
    assert contract["historical_equities_available_since"] == 2016
    assert contract["historical_api_requests_per_minute"] == 200
    assert contract["historical_sip_without_algo_trader_plus"] is True
    assert contract["endpoint"] == "https://data.alpaca.markets/v2/stocks/bars"
    assert (contract["feed"], contract["timeframe"]) == ("sip", "5Min")
    assert (contract["start_boundary"], contract["end_boundary"]) == (
        "inclusive",
        "inclusive",
    )
    assert contract["limit"] == 10_000

    architecture = plan["canonical_data_architecture"]
    assert architecture["canonical_source_view"]["adjustment"] == "raw"
    assert architecture["analytical_source_view"]["adjustment"] == "split,spin-off"
    assert architecture["generic_alpaca_provider_reuse_allowed"] is False

    retention = plan["licensing_and_retention_gate"]
    assert retention["verdict"] == "MATERIAL-AMBIGUITY-BLOCKS-PROVIDER-AUTHORITY"
    assert retention["durable_private_raw_retention_explicitly_permitted"] is False
    assert retention["hash_only_refetch_fallback_scientifically_acceptable"] is False
    assert plan["source_qualification"]["status"].endswith("CONTRACT-GATED")
    assert plan["next_authorization"]["granted_by_this_plan"] is False


def test_qualification_sample_exercises_pagination_without_requiring_known_gaps() -> None:
    plan = _load(_PLAN_PATH)
    qualification = plan["source_qualification"]
    sessions = qualification["fixed_sessions"]

    assert qualification["exact_symbols"] == list(_SYMBOLS)
    assert qualification["request_contract"]["adjustments"] == ["raw", "split,spin-off"]
    assert len(qualification["known_mdy_coordinates"]) == 9
    assert sessions["unique_session_count"] == 22
    assert sessions["expected_rows_per_adjustment_view"] == (
        21 * 78 * len(_SYMBOLS) + 42 * len(_SYMBOLS)
    )
    assert sessions["expected_paired_rows_before_known_gaps"] == (
        2 * sessions["expected_rows_per_adjustment_view"]
    )
    pagination_rows = len(sessions["pagination_and_split_block"]) * 78 * len(_SYMBOLS)
    assert pagination_rows == 10_140
    assert pagination_rows > qualification["request_contract"]["limit"]
    assert qualification["transport_budget"]["expected_http_responses"] == 28
    assert qualification["strategy_calculation_or_return_allowed"] is False


def test_missing_session_policy_is_whole_date_and_has_two_unexpected_slots() -> None:
    plan = _load(_PLAN_PATH)
    policy = plan["missing_data_policy"]
    quarantine = policy["known_quarantine"]
    loss = policy["global_loss_limit"]
    limits = policy["concentration_limits"]

    assert quarantine["session_count"] == len(quarantine["sessions"]) == 5
    assert loss["overall_excluded_full_session_count_max"] == int(
        loss["expected_full_trade_eligible_sessions"]
        * Decimal(loss["overall_excluded_full_session_rate_max"])
    )
    assert loss["overall_excluded_full_session_count_max"] == 7
    assert loss["unexpected_excluded_full_session_count_max"] == 2
    assert limits["maximum_consecutive_total_exclusions"] == 1
    assert limits["required_initial_context_loss_max"] == 0

    day = datetime(2025, 1, 6, tzinfo=UTC)
    timestamps = expected_bar_timestamps(
        day, day.replace(hour=23, minute=59), Timeframe.FIVE_MINUTES
    )
    expected = {(symbol, timestamp) for symbol in _SYMBOLS for timestamp in timestamps}
    assert len(expected) == 78 * len(_SYMBOLS)

    complete = set(expected)
    missing_one = complete - {("MDY", timestamps[10])}
    missing_two_same_session = missing_one - {("MDY", timestamps[20])}
    missing_spy = complete - {("SPY", timestamps[10])}
    assert complete == expected
    assert missing_one != expected
    assert missing_two_same_session != expected
    assert missing_spy != expected
    assert policy["incomplete_session_action"].startswith("Exclude the whole session")
    assert policy["symbol_drop_or_rerank_allowed"] is False
    assert policy["forward_fill_backward_fill_interpolation_or_synthesis_allowed"] is False


def test_split_normalization_and_dividend_gap_preserve_same_session_features() -> None:
    plan = _load(_PLAN_PATH)
    fixture = build_synthetic_program_002_fixture()
    configuration = load_program_002_plan(_REPOSITORY).configurations["src-v1-l1-h4"]
    prior_days = set(fixture.prior_days)

    contemporaneous = tuple(
        replace(
            bar,
            open=bar.open * 2,
            high=bar.high * 2,
            low=bar.low * 2,
            close=bar.close * 2,
            volume=bar.volume // 2,
        )
        if bar.symbol == Symbol("IWM") and bar.timestamp.date() in prior_days
        else bar
        for bar in fixture.bars
    )
    normalized = tuple(
        replace(
            bar,
            open=bar.open / 2,
            high=bar.high / 2,
            low=bar.low / 2,
            close=bar.close / 2,
            volume=bar.volume * 2,
        )
        if bar.symbol == Symbol("IWM") and bar.timestamp.date() in prior_days
        else bar
        for bar in contemporaneous
    )

    raw_trace = build_selection_trace(contemporaneous, fixture.normal_day, configuration)
    normalized_trace = build_selection_trace(normalized, fixture.normal_day, configuration)
    baseline_trace = build_selection_trace(fixture.bars, fixture.normal_day, configuration)
    assert _feature(raw_trace, "IWM").same_clock_relative_volume == Decimal("2.4")
    assert _feature(normalized_trace, "IWM") == _feature(baseline_trace, "IWM")

    dividend_gap = tuple(
        replace(
            bar,
            open=bar.open * Decimal("0.99"),
            high=bar.high * Decimal("0.99"),
            low=bar.low * Decimal("0.99"),
            close=bar.close * Decimal("0.99"),
        )
        if bar.symbol == Symbol("IWM") and bar.timestamp.date() == fixture.normal_day
        else bar
        for bar in fixture.bars
    )
    dividend_trace = build_selection_trace(dividend_gap, fixture.normal_day, configuration)
    baseline_iwm = _feature(baseline_trace, "IWM")
    dividend_iwm = _feature(dividend_trace, "IWM")
    assert dividend_iwm.lookback_return == baseline_iwm.lookback_return
    assert dividend_iwm.same_clock_relative_volume == baseline_iwm.same_clock_relative_volume
    assert plan["corporate_action_policy"]["ordinary_dividend_session_action"].startswith(
        "Eligible"
    )


def test_full_acquisition_counts_calendar_rows_requests_and_storage() -> None:
    plan = _load(_PLAN_PATH)
    acquisition = plan["full_acquisition_design"]
    exact = acquisition["exact_range"]
    start = datetime.fromisoformat(exact["start"]).replace(tzinfo=UTC)
    end = datetime.combine(datetime.fromisoformat(exact["end"]).date(), time.max, UTC)
    sessions = expected_sessions(start, end)
    row_counts = tuple(
        len(
            expected_bar_timestamps(
                datetime.combine(day, time.min, UTC),
                datetime.combine(day, time.max, UTC),
                Timeframe.FIVE_MINUTES,
            )
        )
        for day in sessions
    )

    assert len(sessions) == exact["expected_xnys_sessions"] == 1_531
    assert row_counts.count(78) == exact["full_sessions"] == 1_519
    assert row_counts.count(42) == exact["early_close_sessions"] == 12
    assert sum(row_counts) * len(_SYMBOLS) == exact["expected_rows_per_adjustment_view"]
    assert exact["expected_paired_rows"] == 2 * exact["expected_rows_per_adjustment_view"]
    assert acquisition["remaining_sessions_after_qualification"] == 1_509
    assert acquisition["maximum_additional_logical_chains"] == 2 * 1_509
    assert acquisition["expected_additional_http_responses"] == 3_018
    assert acquisition["maximum_additional_http_responses"] == 4 * 3_018
    assert acquisition["strategy_execution_allowed"] is False
