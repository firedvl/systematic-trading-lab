from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
from math import comb
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pytest

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
_EVIDENCE_PATH = "config/research/program-005-alpaca-public-contract-evidence-v1.json"
_PROGRAM_003_PATH = "config/research/program-003-low-cost-successor-plan-v1.json"
_PROGRAM_002_PATH = "config/research/cross-sectional-sector-etf-program-002-plan-proposal-v1.json"
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


def _full_session_count(start: datetime, end: datetime) -> int:
    bars = expected_bar_timestamps(start, end, Timeframe.FIVE_MINUTES)
    return sum(count == 78 for count in Counter(bar.date() for bar in bars).values())


def _qualification_requests(plan: dict[str, Any]) -> list[dict[str, Any]]:
    qualification = plan["source_qualification"]
    contract = qualification["request_contract"]
    return [
        {
            "chain_id": request_range["logical_chain_ids"][adjustment_index],
            "method": contract["method"],
            "url": contract["endpoint"],
            "params": {
                "symbols": ",".join(qualification["exact_symbols"]),
                "start": request_range["start_inclusive"],
                "end": request_range["end_inclusive"],
                "feed": contract["feed"],
                "timeframe": contract["timeframe"],
                "adjustment": adjustment,
                "sort": contract["sort"],
                "limit": contract["limit"],
                "asof": contract["asof"],
            },
        }
        for request_range in qualification["request_ranges"]
        for adjustment_index, adjustment in enumerate(contract["adjustments"])
    ]


def _run_mock_transport(
    *,
    authorized: bool,
    requests: list[dict[str, Any]],
    expected_requests: list[dict[str, Any]],
    load_credentials: Any,
    fetch: Any,
    maximum_pages: int = 4,
) -> list[Any]:
    if not authorized:
        raise PermissionError("source request authority is false")
    if requests != expected_requests:
        raise ValueError("request differs from the frozen contract")
    for request in requests:
        parsed = urlsplit(request["url"])
        if request["method"] != "GET" or (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.query,
            parsed.fragment,
        ) != (
            "https",
            "data.alpaca.markets",
            "/v2/stocks/bars",
            "",
            "",
        ):
            raise PermissionError("endpoint is outside the frozen GET-only origin and path")

    credentials = load_credentials()
    rows: list[Any] = []
    for request in requests:
        token: str | None = None
        seen_tokens: set[str] = set()
        for _ in range(maximum_pages):
            page_request = deepcopy(request)
            if token is not None:
                page_request["params"]["page_token"] = token
            page = fetch(credentials, page_request)
            if "next_page_token" not in page:
                raise ValueError("next_page_token field is required")
            rows.extend(page["rows"])
            next_token = page["next_page_token"]
            if next_token is None:
                break
            if next_token in seen_tokens:
                raise ValueError("repeated next_page_token")
            seen_tokens.add(next_token)
            token = next_token
        else:
            raise ValueError("page cap exceeded")
    return rows


def _run_mock_strategy(*, dataset_admitted: bool, authorized: bool, execute: Any) -> Any:
    if not dataset_admitted or not authorized:
        raise PermissionError("strategy execution requires admission and separate authority")
    return execute()


def _mock_admission(
    quarantine: dict[int, set[str]],
    unexpected: dict[int, set[str]],
    *,
    policy: dict[str, Any],
    year_by_session: dict[int, int],
    block_by_session: dict[int, str],
    ambiguous_actions: set[int] | None = None,
    initial_context: set[int] | None = None,
    action_ledger_resolved: bool = True,
) -> tuple[set[int], set[str]]:
    unexpected = {index: set(symbols) for index, symbols in unexpected.items()}
    for index in ambiguous_actions or set():
        unexpected.setdefault(index, set()).add("AMBIGUOUS_ACTION")
    excluded = set(quarantine) | set(unexpected)
    failures: set[str] = set()
    loss = policy["global_loss_limit"]
    limits = policy["concentration_limits"]

    if len(excluded) > loss["overall_excluded_full_session_count_max"]:
        failures.add("global-count")
    if len(unexpected) > loss["unexpected_excluded_full_session_count_max"]:
        failures.add("unexpected-count")
    if any(
        sum(year_by_session[index] == year for index in unexpected)
        > limits["unexpected_exclusions_per_calendar_year_max"]
        for year in set(year_by_session.values())
    ):
        failures.add("calendar-year")

    quarantine_blocks = {block_by_session[index] for index in quarantine}
    unexpected_blocks = [block_by_session[index] for index in unexpected]
    if any(
        unexpected_blocks.count(block)
        > limits["unexpected_exclusions_per_predeclared_discovery_or_test_block_max"]
        for block in set(unexpected_blocks)
    ):
        failures.add("fixed-block")
    quarantine_overlap_allowed = limits[
        "unexpected_exclusion_in_block_or_rolling_63_window_containing_the_known_quarantine_allowed"
    ]
    if not quarantine_overlap_allowed and quarantine_blocks.intersection(unexpected_blocks):
        failures.add("quarantine-block")

    ordered = sorted(excluded)
    longest_run = 0
    current_run = 0
    previous: int | None = None
    for index in ordered:
        current_run = current_run + 1 if previous is not None and index == previous + 1 else 1
        longest_run = max(longest_run, current_run)
        previous = index
    if (
        not limits[
            "unexpected_exclusion_adjacent_to_any_quarantined_or_unexpected_exclusion_allowed"
        ]
        and longest_run > limits["maximum_consecutive_total_exclusions"]
    ):
        failures.add("adjacent")
    rolling_window = limits["unexpected_exclusion_rolling_window_sessions"]
    if any(
        sum(abs(index - other) < rolling_window for other in unexpected)
        > limits["unexpected_exclusions_per_rolling_63_expected_sessions_max"]
        for index in unexpected
    ):
        failures.add("rolling-63")
    if not quarantine_overlap_allowed and any(
        abs(index - other) < rolling_window for index in unexpected for other in quarantine
    ):
        failures.add("quarantine-rolling-63")
    same_symbol_window = limits["same_missing_symbol_rolling_window_sessions"]
    if any(
        sum(
            abs(index - other) < same_symbol_window
            and bool(symbols.intersection((quarantine | unexpected)[other]))
            for other in excluded
        )
        > limits[
            "unexpected_sessions_with_same_missing_symbol_per_rolling_252_expected_sessions_max"
        ]
        for index, symbols in unexpected.items()
    ):
        failures.add("same-symbol-rolling-252")
    if (
        len(excluded.intersection(initial_context or set()))
        > limits["required_initial_context_loss_max"]
    ):
        failures.add("initial-context")
    if not action_ledger_resolved:
        failures.add("action-ledger")
    return excluded, failures


def _hypergeometric_tail_probability(
    *, population: int, tail_size: int, draws: int, at_least: int
) -> Decimal:
    numerator = sum(
        comb(tail_size, count) * comb(population - tail_size, draws - count)
        for count in range(at_least, min(tail_size, draws) + 1)
    )
    return Decimal(numerator) / Decimal(comb(population, draws))


def _mock_morning_bias_failures(
    policy: dict[str, Any],
    excluded: set[int],
    metrics_by_symbol: dict[str, dict[int, tuple[Decimal, Decimal, Decimal] | None]],
) -> set[str]:
    gate = policy["bias_audit"]["spy_and_mdy_morning_diagnostics"]
    if any(
        metrics_by_symbol[symbol].get(session) is None
        for symbol in gate["reference_symbols"]
        for session in excluded
    ):
        return {"morning-diagnostic-unavailable"}
    if str(len(excluded)) not in gate["rejection_counts_by_total_exclusions"]:
        return {"unsupported-exclusion-count"}

    rejection_count = gate["rejection_counts_by_total_exclusions"][str(len(excluded))]
    failures: set[str] = set()
    for symbol in gate["reference_symbols"]:
        available = {
            session: value
            for session, value in metrics_by_symbol[symbol].items()
            if value is not None
        }
        tail_size = (len(available) + 3) // 4
        ordered = [
            sorted(available, key=lambda session: (available[session][metric_index], session))
            for metric_index in range(3)
        ]
        tails = {
            "high-absolute-return": set(ordered[0][-tail_size:]),
            "high-range": set(ordered[1][-tail_size:]),
            "low-volume": set(ordered[2][:tail_size]),
        }
        failures.update(
            f"{symbol}-{name}"
            for name, tail in tails.items()
            if len(excluded.intersection(tail)) >= rejection_count
        )
    return failures


def test_program_005_plan_binds_lineage_and_grants_no_authority() -> None:
    plan = _load(_PLAN_PATH)
    unsigned = dict(plan)

    assert unsigned.pop("plan_fingerprint") == fingerprint(unsigned)
    assert plan["program_id"] == "multi-hour-sector-etf-research-004"
    assert plan["lineage"]["program_003_strategy_outcomes_generated_or_observed"] == 0
    assert plan["lineage"]["program_004_strategy_outcomes_generated_or_observed"] == 0
    assert plan["lineage"]["result_driven_adaptation"] is False
    assert plan["lineage"]["program_004_marketparquet_path_abandoned_without_purchase"] is True
    assert plan["lineage"]["candidate_return_evidence_informed_source_changes"] is False
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

    binding = plan["public_contract_evidence"]
    assert binding["path"] == _EVIDENCE_PATH
    evidence_path = _REPOSITORY / binding["path"]
    evidence = json.loads(evidence_path.read_text())
    unsigned_evidence = dict(evidence)
    assert unsigned_evidence.pop("evidence_fingerprint") == fingerprint(unsigned_evidence)
    assert sha256(evidence_path.read_bytes()).hexdigest() == binding["sha256"]
    assert evidence["evidence_fingerprint"] == binding["fingerprint"]
    assert evidence["access_history"]["remaining_access_gap"] is False
    assert evidence["retention_assessment"]["verdict"] == retention["verdict"]
    assert {source["source_id"] for source in evidence["sources"]} >= {
        "nasdaq-global-subscriber-agreement",
        "nyse-market-data-display-agreement",
    }


def test_current_issuer_spread_evidence_binds_the_normal_cost_review() -> None:
    plan = _load(_PLAN_PATH)
    cost = plan["transaction_cost_model"]
    review = cost["cost_review"]
    evidence = review["issuer_spread_evidence"]
    expected_tickers = plan["preserved_economic_contract"]["ranking_and_trading_symbols"]

    assert [item["ticker"] for item in evidence] == expected_tickers
    assert all(item["url"].startswith("https://") for item in evidence)
    assert all(len(item["sha256"]) == 64 for item in evidence)
    assert all(item["byte_count"] > 100_000 for item in evidence)
    spreads = [Decimal(item["reported_30_day_median_full_spread_bps"]) for item in evidence]
    assert all(
        Decimal(item["reported_30_day_median_full_spread_percent"]) * 100
        == Decimal(item["reported_30_day_median_full_spread_bps"])
        for item in evidence
    )
    assert (min(spreads), max(spreads)) == (Decimal(0), Decimal(2))
    assert review["current_issuer_median_full_spread_range_bps"] == "0-2"
    assert cost["scenarios"]["normal"]["total_bps_per_side"] == "6"
    assert cost["historical_nbbo_required"] is False
    assert review["source_bodies_committed"] is False
    assert review["mutable_source_warning"]


def test_qualification_sample_exercises_pagination_without_requiring_known_gaps() -> None:
    plan = _load(_PLAN_PATH)
    qualification = plan["source_qualification"]
    sessions = qualification["fixed_sessions"]

    assert qualification["exact_symbols"] == list(_SYMBOLS)
    assert qualification["request_contract"]["adjustments"] == ["raw", "split,spin-off"]
    request_ranges = qualification["request_ranges"]
    assert len(request_ranges) == 13
    assert len({item["range_id"] for item in request_ranges}) == 13
    assert (
        len({chain_id for item in request_ranges for chain_id in item["logical_chain_ids"]}) == 26
    )
    assert {session for item in request_ranges for session in item["session_dates"]} == {
        session
        for group in (
            "known_quarantine_sessions",
            "normal_controls",
            "early_close_control",
            "distribution_neighborhood",
            "pagination_and_split_block",
        )
        for session in sessions[group]
    }
    for item in request_ranges:
        timestamps = expected_bar_timestamps(
            datetime.fromisoformat(item["start_inclusive"].replace("Z", "+00:00")),
            datetime.fromisoformat(item["end_inclusive"].replace("Z", "+00:00")),
            Timeframe.FIVE_MINUTES,
        )
        assert timestamps[0].isoformat().replace("+00:00", "Z") == item["start_inclusive"]
        assert timestamps[-1].isoformat().replace("+00:00", "Z") == item["end_inclusive"]
        assert {timestamp.date().isoformat() for timestamp in timestamps} == set(
            item["session_dates"]
        )
        assert len(timestamps) * len(_SYMBOLS) == item["expected_rows_per_adjustment_view"]
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
    budget = qualification["transport_budget"]
    assert budget["logical_chains_per_adjustment_view"] == len(request_ranges) == 13
    assert (
        budget["maximum_logical_chains"]
        == sum(len(item["logical_chain_ids"]) for item in request_ranges)
        == 26
    )
    assert (
        budget["expected_http_responses"]
        == sum(
            item["expected_pages_per_adjustment_view"]
            * len(qualification["request_contract"]["adjustments"])
            for item in request_ranges
        )
        == 28
    )
    assert (
        budget["maximum_http_responses"]
        == sum(
            item["maximum_pages_per_adjustment_view"]
            * len(qualification["request_contract"]["adjustments"])
            for item in request_ranges
        )
        == 60
    )
    assert qualification["strategy_calculation_or_return_allowed"] is False


def test_missing_session_policy_is_whole_date_and_has_two_unexpected_slots() -> None:
    plan = _load(_PLAN_PATH)
    policy = plan["missing_data_policy"]
    quarantine = policy["known_quarantine"]
    loss = policy["global_loss_limit"]
    limits = policy["concentration_limits"]

    assert quarantine["session_count"] == len(quarantine["sessions"]) == 5
    program_003 = _load(_PROGRAM_003_PATH)
    predecessor_chronology = program_003["chronology"]
    blocks = [
        (block["start"], block["end"]) for block in predecessor_chronology["discovery_blocks"]
    ] + [
        (fold["test_start"], fold["test_end"])
        for fold in predecessor_chronology["walk_forward"]["folds"]
    ]
    block_counts = {
        len(
            expected_sessions(
                datetime.fromisoformat(start).replace(tzinfo=UTC),
                datetime.combine(datetime.fromisoformat(end).date(), time.max, UTC),
            )
        )
        for start, end in blocks
    }
    assert (
        sorted(block_counts)
        == limits["fixed_discovery_or_test_block_full_session_counts"]
        == [
            125,
            126,
        ]
    )
    fixed_counts = {
        block["block_id"]: sum(
            block["start"] <= session <= block["end"] for session in quarantine["sessions"]
        )
        for block in predecessor_chronology["discovery_blocks"]
    }
    fixed_counts = {block: count for block, count in fixed_counts.items() if count}
    fixed_contract = limits["known_quarantine_concentration_contract"]
    assert (
        fixed_counts
        == fixed_contract["fixed_counts_by_predeclared_discovery_block"]
        == {
            "discovery-01": 1,
            "discovery-02": 4,
        }
    )
    assert fixed_contract["unexpected_recurrence_limits_apply"] is False
    assert fixed_contract["post_acquisition_change_or_waiver_allowed"] is False
    origin_path = _REPOSITORY / loss["origin_plan_path"]
    origin_review_path = _REPOSITORY / loss["origin_review_path"]
    assert sha256(origin_path.read_bytes()).hexdigest() == loss["origin_plan_sha256"]
    assert sha256(origin_review_path.read_bytes()).hexdigest() == loss["origin_review_sha256"]
    assert program_003["plan_fingerprint"] == loss["origin_plan_fingerprint"]
    assert (
        _load(loss["origin_review_path"])["review_fingerprint"] == loss["origin_review_fingerprint"]
    )
    origin_loss = program_003["missing_data_policy"]["maximum_loss"]
    assert origin_loss["overall_excluded_full_session_rate_max"] == "0.005"
    assert origin_loss["overall_excluded_full_session_count_max"] == 7
    numerator, denominator = map(int, loss["overall_excluded_full_session_rate_exact"].split("/"))
    assert numerator == 7
    assert denominator == loss["expected_full_trade_eligible_sessions"]
    assert Decimal(numerator) / Decimal(denominator) < Decimal("0.005")
    assert loss["overall_excluded_full_session_count_max"] == 7
    assert loss["minimum_retained_full_trade_eligible_sessions"] == 1_492
    assert loss["unexpected_excluded_full_session_count_max"] == 2
    assert loss["prompt_suggested_rate_used_as_derivation_input"] is False

    program_002_blocks = _load(_PROGRAM_002_PATH)["chronology"]["discovery_blocks"]
    pre_quarantine = {
        block["block_id"]: block["trade_eligible_full_sessions"] for block in program_002_blocks
    }
    post_quarantine = {
        block: count - fixed_counts.get(block, 0) for block, count in pre_quarantine.items()
    }
    assert (
        pre_quarantine
        == fixed_contract["pre_quarantine_full_trade_eligible_sessions_by_discovery_block"]
    )
    assert (
        post_quarantine
        == fixed_contract["post_quarantine_full_trade_eligible_sessions_by_discovery_block"]
    )
    assert (
        min(post_quarantine.values())
        >= fixed_contract["minimum_retained_full_sessions_per_discovery_block"]
        == 2 * fixed_contract["frozen_minimum_active_sessions_per_discovery_block"]
    )
    assert (
        max(pre_quarantine.values()) - min(pre_quarantine.values())
        == fixed_contract["pre_quarantine_maximum_discovery_block_session_count_difference"]
    )
    assert (
        max(post_quarantine.values()) - min(post_quarantine.values())
        == fixed_contract["post_quarantine_maximum_discovery_block_session_count_difference"]
    )

    quarantine_dates = {datetime.fromisoformat(value).date() for value in quarantine["sessions"]}
    test_ranges = [
        (
            datetime.fromisoformat(fold["test_start"]).date(),
            datetime.fromisoformat(fold["test_end"]).date(),
        )
        for fold in predecessor_chronology["walk_forward"]["folds"]
    ]
    assert (
        sum(start <= day <= end for day in quarantine_dates for start, end in test_ranges)
        == (fixed_contract["fixed_quarantine_sessions_in_walk_forward_test_folds"])
    )
    exposed_dates = expected_sessions(
        datetime(2020, 7, 27, tzinfo=UTC), datetime(2021, 2, 22, 23, 59, tzinfo=UTC)
    )
    quarantine_indices = sorted(exposed_dates.index(day) for day in quarantine_dates)
    assert all(
        right - left > 1
        for left, right in zip(quarantine_indices, quarantine_indices[1:], strict=False)
    )
    assert fixed_contract["observed_maximum_consecutive_fixed_quarantine_sessions"] == 1

    calendar_gate = fixed_contract["calendar_concentration_contract"]
    for month, values in calendar_gate["affected_months"].items():
        year, month_number = map(int, month.split("-"))
        next_month = (
            datetime(year + 1, 1, 1, tzinfo=UTC)
            if month_number == 12
            else datetime(year, month_number + 1, 1, tzinfo=UTC)
        )
        full_sessions = _full_session_count(
            datetime(year, month_number, 1, tzinfo=UTC), next_month - timedelta(minutes=1)
        )
        fixed_count = sum(day.strftime("%Y-%m") == month for day in quarantine_dates)
        assert full_sessions == values["full_sessions_before_quarantine"]
        assert fixed_count == values["fixed_quarantine_sessions"]
        assert full_sessions - fixed_count == values["retained_full_sessions"]
        assert (
            values["retained_full_sessions"]
            >= calendar_gate["minimum_retained_full_sessions_per_affected_month"]
        )
    complete_year = calendar_gate["affected_complete_calendar_years"]["2021"]
    full_2021 = _full_session_count(
        datetime(2021, 1, 1, tzinfo=UTC), datetime(2021, 12, 31, 23, 59, tzinfo=UTC)
    )
    fixed_2021 = sum(day.year == 2021 for day in quarantine_dates)
    assert full_2021 == complete_year["full_sessions_before_quarantine"]
    assert fixed_2021 == complete_year["fixed_quarantine_sessions"]
    assert full_2021 - fixed_2021 == complete_year["retained_full_sessions"]
    assert (
        complete_year["retained_full_sessions"]
        >= calendar_gate["minimum_retained_full_sessions_per_affected_complete_calendar_year"]
        == 2 * fixed_contract["minimum_retained_full_sessions_per_discovery_block"]
    )

    clock_gate = fixed_contract["clock_concentration_contract"]
    new_york = ZoneInfo("America/New_York")
    coordinate_clock_counts = Counter(
        datetime.fromisoformat(coordinate.split("@")[1].replace("Z", "+00:00"))
        .astimezone(new_york)
        .strftime("%H:%M")
        for coordinate in plan["source_qualification"]["known_mdy_coordinates"]
    )
    assert (
        dict(sorted(coordinate_clock_counts.items()))
        == clock_gate["fixed_coordinate_counts_by_new_york_clock"]
    )
    assert (
        max(coordinate_clock_counts.values())
        == clock_gate["observed_maximum_coordinates_at_one_clock"]
        < clock_gate["rejection_count_at_one_clock"]
    )
    clock_tail = _hypergeometric_tail_probability(
        population=clock_gate["uniform_coordinate_reference_population"],
        tail_size=clock_gate["coordinates_per_clock"],
        draws=clock_gate["missing_coordinate_count"],
        at_least=clock_gate["rejection_count_at_one_clock"],
    )
    assert clock_tail.quantize(Decimal("0.000000000001")) == Decimal(
        clock_gate["exact_hypergeometric_tail_probability_at_rejection_count"]
    )
    assert (clock_tail * clock_gate["bonferroni_clock_test_count"]).quantize(
        Decimal("0.000000000001")
    ) == Decimal(clock_gate["bonferroni_union_bound_at_rejection_count"])
    hypothesis = plan["preserved_economic_contract"]
    costs = plan["transaction_cost_model"]["scenarios"]
    exact_strategy_clocks = {
        hypothesis["decision_time_new_york"],
        *(scenario["entry_time_new_york"] for scenario in costs.values()),
        *(clock for clocks in hypothesis["exit_times_new_york"].values() for clock in clocks),
    }
    stored_strategy_counts = clock_gate["fixed_sessions_missing_at_exact_strategy_clocks"]
    assert {label.split("-", 1)[0] for label in stored_strategy_counts} == exact_strategy_clocks
    derived_strategy_counts = {
        label: len(
            {
                datetime.fromisoformat(coordinate.split("@")[1].replace("Z", "+00:00")).date()
                for coordinate in plan["source_qualification"]["known_mdy_coordinates"]
                if datetime.fromisoformat(coordinate.split("@")[1].replace("Z", "+00:00"))
                .astimezone(new_york)
                .strftime("%H:%M")
                == label.split("-", 1)[0]
            }
        )
        for label in stored_strategy_counts
    }
    assert derived_strategy_counts == stored_strategy_counts
    assert (
        max(derived_strategy_counts.values())
        <= (clock_gate["maximum_fixed_sessions_missing_at_any_exact_strategy_clock"])
    )
    assert limits["unexpected_exclusions_per_calendar_year_max"] == 1
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


def test_mock_admission_covers_threshold_concentration_and_action_failures() -> None:
    policy = _load(_PLAN_PATH)["missing_data_policy"]
    quarantine = {
        10: {"MDY"},
        100: {"MDY"},
        200: {"MDY"},
        300: {"MDY"},
        400: {"MDY"},
    }
    years = {index: 2020 + index // 100 for index in range(800)}
    blocks = {index: f"block-{index // 80}" for index in range(800)}
    passing_unexpected = {500: {"SPY"}, 600: {"XLK"}}

    excluded, failures = _mock_admission(
        quarantine,
        passing_unexpected,
        policy=policy,
        year_by_session=years,
        block_by_session=blocks,
    )
    assert len(excluded) == 7
    assert failures == set()

    _, threshold_failures = _mock_admission(
        quarantine,
        passing_unexpected,
        policy=policy,
        year_by_session=years,
        block_by_session=blocks,
        ambiguous_actions={700},
    )
    assert {"global-count", "unexpected-count"} <= threshold_failures

    _, rolling_failures = _mock_admission(
        {},
        {500: {"XLF"}, 562: {"XLE"}},
        policy=policy,
        year_by_session=years,
        block_by_session=blocks,
    )
    assert "rolling-63" in rolling_failures

    _, adjacency_failures = _mock_admission(
        {},
        {500: {"XLF"}, 501: {"XLE"}},
        policy=policy,
        year_by_session=years,
        block_by_session=blocks,
    )
    assert {"adjacent", "rolling-63", "calendar-year", "fixed-block"} <= adjacency_failures

    _, symbol_failures = _mock_admission(
        {100: {"MDY"}},
        {300: {"MDY"}},
        policy=policy,
        year_by_session=years,
        block_by_session=blocks,
    )
    assert "same-symbol-rolling-252" in symbol_failures

    action_exclusions, action_failures = _mock_admission(
        {},
        {},
        policy=policy,
        year_by_session=years,
        block_by_session=blocks,
        ambiguous_actions={700},
        action_ledger_resolved=False,
    )
    assert action_exclusions == {700}
    assert "action-ledger" in action_failures


def test_spy_and_mdy_bias_gate_has_objective_tail_thresholds_and_unavailable_failure() -> None:
    policy = _load(_PLAN_PATH)["missing_data_policy"]
    gate = policy["bias_audit"]["spy_and_mdy_morning_diagnostics"]
    metrics: dict[int, tuple[Decimal, Decimal, Decimal] | None] = {
        session: (Decimal(session), Decimal(session), Decimal(session)) for session in range(40)
    }
    metrics_by_symbol = {symbol: dict(metrics) for symbol in gate["reference_symbols"]}

    assert gate["reference_symbols"] == ["SPY", "MDY"]
    assert gate["per_test_alpha_exact"] == "1/120"
    assert gate["reference_null"] == (
        "uniform selection of exclusion dates without replacement from the deterministic "
        "1,499-session population"
    )
    assert "neither proves missing-completely-at-random" in gate["interpretation_limit"]
    assert gate["rejection_counts_by_total_exclusions"] == {"5": 5, "6": 5, "7": 6}
    assert gate["finite_population_sessions"] == 1_499
    assert gate["tail_size_sessions"] == 375
    assert gate["exact_hypergeometric_tail_probabilities_at_rejection_count"] == {
        "5": "0.000960330049",
        "6": "0.004572816581",
        "7": "0.001312142201",
    }
    for draws, rejection_count in gate["rejection_counts_by_total_exclusions"].items():
        probability = _hypergeometric_tail_probability(
            population=gate["finite_population_sessions"],
            tail_size=gate["tail_size_sessions"],
            draws=int(draws),
            at_least=rejection_count,
        )
        assert probability.quantize(Decimal("0.000000000001")) == Decimal(
            gate["exact_hypergeometric_tail_probabilities_at_rejection_count"][draws]
        )
        assert probability < Decimal(1) / Decimal(120)
    assert _mock_morning_bias_failures(policy, {0, 10, 20, 25, 30}, metrics_by_symbol) == set()
    assert _mock_morning_bias_failures(policy, {35, 36, 37, 38, 39}, metrics_by_symbol) == {
        "SPY-high-absolute-return",
        "SPY-high-range",
        "MDY-high-absolute-return",
        "MDY-high-range",
    }

    unavailable = {symbol: dict(values) for symbol, values in metrics_by_symbol.items()}
    unavailable["MDY"][20] = None
    assert _mock_morning_bias_failures(policy, {0, 10, 20, 25, 30}, unavailable) == {
        "morning-diagnostic-unavailable"
    }


def test_mock_completeness_detects_missing_bars_across_sessions_and_spy() -> None:
    policy = _load(_PLAN_PATH)["missing_data_policy"]
    days = (datetime(2025, 1, 6, tzinfo=UTC), datetime(2025, 1, 7, tzinfo=UTC))
    expected_by_day = {
        day.date(): {
            (symbol, timestamp)
            for symbol in _SYMBOLS
            for timestamp in expected_bar_timestamps(
                day, day.replace(hour=23, minute=59), Timeframe.FIVE_MINUTES
            )
        }
        for day in days
    }
    actual = set().union(*expected_by_day.values())
    first_timestamps = sorted(
        timestamp for symbol, timestamp in expected_by_day[days[0].date()] if symbol == "MDY"
    )
    second_timestamps = sorted(
        timestamp for symbol, timestamp in expected_by_day[days[1].date()] if symbol == "SPY"
    )
    actual.remove(("MDY", first_timestamps[10]))
    actual.remove(("SPY", second_timestamps[-1]))

    missing_by_day = {
        day: expected - actual for day, expected in expected_by_day.items() if expected - actual
    }
    assert set(missing_by_day) == {day.date() for day in days}
    assert {symbol for missing in missing_by_day.values() for symbol, _ in missing} == {
        "MDY",
        "SPY",
    }
    excluded, failures = _mock_admission(
        {},
        {
            index: {symbol for symbol, _ in missing_by_day[day.date()]}
            for index, day in enumerate(days, start=500)
        },
        policy=policy,
        year_by_session={500: 2025, 501: 2025},
        block_by_session={500: "block-a", 501: "block-b"},
    )
    assert excluded == {500, 501}
    assert {"calendar-year", "adjacent", "rolling-63"} <= failures
    assert all(
        timestamp.minute % 5 == 0
        for expected in expected_by_day.values()
        for _, timestamp in expected
    )


def test_mock_transport_paginates_and_denies_ungranted_actions() -> None:
    plan = _load(_PLAN_PATH)
    qualification = plan["source_qualification"]
    calls = {"credential_loads": 0, "fetches": 0, "strategies": 0}
    request_calls: list[dict[str, Any]] = []
    synthetic_credentials = object()
    expected_range_identities = [
        ("normal-2020-07-27", "2020-07-27T13:30:00Z", "2020-07-27T19:55:00Z"),
        ("quarantine-2020-12-04", "2020-12-04T14:30:00Z", "2020-12-04T20:55:00Z"),
        ("quarantine-2021-02-03", "2021-02-03T14:30:00Z", "2021-02-03T20:55:00Z"),
        ("quarantine-2021-02-05", "2021-02-05T14:30:00Z", "2021-02-05T20:55:00Z"),
        ("quarantine-2021-02-10", "2021-02-10T14:30:00Z", "2021-02-10T20:55:00Z"),
        ("quarantine-2021-02-22", "2021-02-22T14:30:00Z", "2021-02-22T20:55:00Z"),
        ("early-close-2022-11-25", "2022-11-25T14:30:00Z", "2022-11-25T17:55:00Z"),
        ("normal-2023-07-17", "2023-07-17T13:30:00Z", "2023-07-17T19:55:00Z"),
        ("distribution-2024-06-10", "2024-06-10T13:30:00Z", "2024-06-10T19:55:00Z"),
        ("distribution-2024-06-11", "2024-06-11T13:30:00Z", "2024-06-11T19:55:00Z"),
        ("distribution-2024-06-12", "2024-06-12T13:30:00Z", "2024-06-12T19:55:00Z"),
        (
            "pagination-split-2025-12-01-to-2025-12-12",
            "2025-12-01T14:30:00Z",
            "2025-12-12T20:55:00Z",
        ),
        ("normal-2026-07-15", "2026-07-15T13:30:00Z", "2026-07-15T19:55:00Z"),
    ]
    assert [
        (item["range_id"], item["start_inclusive"], item["end_inclusive"])
        for item in qualification["request_ranges"]
    ] == expected_range_identities
    requests = _qualification_requests(plan)
    expected_requests = [
        {
            "chain_id": f"{range_id}--{chain_suffix}",
            "method": "GET",
            "url": "https://data.alpaca.markets/v2/stocks/bars",
            "params": {
                "symbols": ",".join(_SYMBOLS),
                "start": start,
                "end": end,
                "feed": "sip",
                "timeframe": "5Min",
                "adjustment": adjustment,
                "sort": "asc",
                "limit": 10_000,
                "asof": "2026-07-31",
            },
        }
        for range_id, start, end in expected_range_identities
        for adjustment, chain_suffix in (("raw", "raw"), ("split,spin-off", "split-spin-off"))
    ]
    maximum_pages = max(
        item["maximum_pages_per_adjustment_view"] for item in qualification["request_ranges"]
    )
    assert requests == expected_requests

    def load_credentials() -> object:
        calls["credential_loads"] += 1
        return synthetic_credentials

    def fetch(credentials: object, request: dict[str, Any]) -> dict[str, Any]:
        assert credentials is synthetic_credentials
        calls["fetches"] += 1
        request_calls.append(deepcopy(request))
        chain_id = request["chain_id"]
        token = request["params"].get("page_token")
        if chain_id.startswith("pagination-split"):
            if token is None:
                return {"rows": [chain_id], "next_page_token": f"{chain_id}-page-2"}
            assert token == f"{chain_id}-page-2"
            return {"rows": [f"{chain_id}-page-2"], "next_page_token": None}
        assert token is None
        return {"rows": [chain_id], "next_page_token": None}

    with pytest.raises(PermissionError, match="authority is false"):
        _run_mock_transport(
            authorized=plan["authority"]["source_requests"],
            requests=requests,
            expected_requests=expected_requests,
            load_credentials=load_credentials,
            fetch=fetch,
            maximum_pages=maximum_pages,
        )
    assert calls == {"credential_loads": 0, "fetches": 0, "strategies": 0}

    rows = _run_mock_transport(
        authorized=True,
        requests=requests,
        expected_requests=expected_requests,
        load_credentials=load_credentials,
        fetch=fetch,
        maximum_pages=maximum_pages,
    )
    assert len(rows) == qualification["transport_budget"]["expected_http_responses"] == 28
    assert calls["credential_loads"] == 1
    assert calls["fetches"] == 28
    first_page_calls = [
        request for request in request_calls if "page_token" not in request["params"]
    ]
    assert first_page_calls == expected_requests
    pagination_calls = [request for request in request_calls if "page_token" in request["params"]]
    assert len(pagination_calls) == 2
    assert all(
        request["params"]["page_token"] == f"{request['chain_id']}-page-2"
        for request in pagination_calls
    )

    missing_feed = deepcopy(requests)
    missing_feed[0]["params"].pop("feed")
    extended_end = deepcopy(requests)
    extended_end[0]["params"]["end"] = "2020-07-27T20:00:00Z"
    for invalid_requests in (missing_feed, extended_end):
        credential_loads = calls["credential_loads"]
        with pytest.raises(ValueError, match="differs from the frozen"):
            _run_mock_transport(
                authorized=True,
                requests=invalid_requests,
                expected_requests=expected_requests,
                load_credentials=load_credentials,
                fetch=fetch,
                maximum_pages=maximum_pages,
            )
        assert calls["credential_loads"] == credential_loads

    def repeated_token_fetch(credentials: object, request: dict[str, Any]) -> dict[str, Any]:
        assert credentials is synthetic_credentials
        return {"rows": [], "next_page_token": "repeat"}

    with pytest.raises(ValueError, match="repeated next_page_token"):
        _run_mock_transport(
            authorized=True,
            requests=requests[:1],
            expected_requests=expected_requests[:1],
            load_credentials=load_credentials,
            fetch=repeated_token_fetch,
            maximum_pages=maximum_pages,
        )
    outside_requests = deepcopy(requests[:1])
    outside_requests[0]["url"] = "https://api.alpaca.markets/v2/orders"
    with pytest.raises(PermissionError, match="outside the frozen"):
        _run_mock_transport(
            authorized=True,
            requests=outside_requests,
            expected_requests=outside_requests,
            load_credentials=load_credentials,
            fetch=fetch,
            maximum_pages=maximum_pages,
        )

    def execute_strategy() -> None:
        calls["strategies"] += 1

    with pytest.raises(PermissionError, match="admission and separate authority"):
        _run_mock_strategy(
            dataset_admitted=False,
            authorized=True,
            execute=execute_strategy,
        )
    with pytest.raises(PermissionError, match="admission and separate authority"):
        _run_mock_strategy(
            dataset_admitted=True,
            authorized=plan["authority"]["strategy_execution"],
            execute=execute_strategy,
        )
    assert calls["strategies"] == 0


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
