from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, time
from decimal import Decimal
from hashlib import sha256
from math import comb
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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


def _qualification_requests(plan: dict[str, Any], *, start: str, end: str) -> list[dict[str, Any]]:
    qualification = plan["source_qualification"]
    contract = qualification["request_contract"]
    return [
        {
            "method": contract["method"],
            "url": contract["endpoint"],
            "params": {
                "symbols": ",".join(qualification["exact_symbols"]),
                "start": start,
                "end": end,
                "feed": contract["feed"],
                "timeframe": contract["timeframe"],
                "adjustment": adjustment,
                "sort": contract["sort"],
                "limit": contract["limit"],
                "asof": contract["asof"],
            },
        }
        for adjustment in contract["adjustments"]
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


def _binomial_cdf(*, successes: int, trials: int, probability: Decimal) -> Decimal:
    return sum(
        (
            Decimal(comb(trials, count))
            * probability**count
            * (Decimal(1) - probability) ** (trials - count)
            for count in range(successes + 1)
        ),
        start=Decimal(0),
    )


def _mock_spy_bias_failures(
    policy: dict[str, Any],
    excluded: set[int],
    metrics: dict[int, tuple[Decimal, Decimal, Decimal] | None],
) -> set[str]:
    gate = policy["bias_audit"]["spy_morning_diagnostics"]
    if any(metrics.get(session) is None for session in excluded):
        return {"spy-diagnostic-unavailable"}
    if str(len(excluded)) not in gate["rejection_counts_by_total_exclusions"]:
        return {"unsupported-exclusion-count"}

    available = {session: value for session, value in metrics.items() if value is not None}
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
    rejection_count = gate["rejection_counts_by_total_exclusions"][str(len(excluded))]
    return {
        name for name, tail in tails.items() if len(excluded.intersection(tail)) >= rejection_count
    }


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
    predecessor_chronology = _load(_PROGRAM_003_PATH)["chronology"]
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
        == loss["fixed_discovery_or_test_block_full_session_counts"]
        == [
            125,
            126,
        ]
    )
    assert loss["fixed_block_source_loss_rate_ceiling"] == "0.01"
    trials = loss["expected_full_trade_eligible_sessions"]
    probability = Decimal(loss["null_source_loss_probability"])
    cdf_at_seven = _binomial_cdf(successes=7, trials=trials, probability=probability)
    cdf_at_eight = _binomial_cdf(successes=8, trials=trials, probability=probability)
    assert cdf_at_seven.quantize(Decimal("0.000000000001")) == Decimal(
        loss["binomial_cdf_at_p_0_01_for_k_7"]
    )
    assert cdf_at_eight.quantize(Decimal("0.000000000001")) == Decimal(
        loss["binomial_cdf_at_p_0_01_for_k_8"]
    )
    assert cdf_at_seven < Decimal(loss["upper_tail_alpha"])
    assert cdf_at_eight > Decimal(loss["upper_tail_alpha"])
    numerator, denominator = map(int, loss["overall_excluded_full_session_rate_exact"].split("/"))
    assert numerator == 7
    assert denominator == loss["expected_full_trade_eligible_sessions"]
    assert Decimal(numerator) / Decimal(denominator) < Decimal("0.005")
    assert loss["overall_excluded_full_session_count_max"] == 7
    assert loss["minimum_retained_full_trade_eligible_sessions"] == 1_492
    assert loss["unexpected_excluded_full_session_count_max"] == 2
    assert loss["prompt_suggested_rate_used_as_derivation_input"] is False
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


def test_spy_bias_gate_has_objective_tail_thresholds_and_unavailable_failure() -> None:
    policy = _load(_PLAN_PATH)["missing_data_policy"]
    gate = policy["bias_audit"]["spy_morning_diagnostics"]
    metrics: dict[int, tuple[Decimal, Decimal, Decimal] | None] = {
        session: (Decimal(session), Decimal(session), Decimal(session)) for session in range(40)
    }

    assert gate["per_test_alpha_exact"] == "1/60"
    assert gate["rejection_counts_by_total_exclusions"] == {"5": 4, "6": 5, "7": 5}
    assert gate["exact_binomial_tail_probabilities_at_rejection_count"] == {
        "5": "0.015625",
        "6": "0.004638671875",
        "7": "0.01287841796875",
    }
    assert _mock_spy_bias_failures(policy, {0, 10, 20, 25, 30}, metrics) == set()
    assert _mock_spy_bias_failures(policy, {15, 36, 37, 38, 39}, metrics) == {
        "high-absolute-return",
        "high-range",
    }

    unavailable = dict(metrics)
    unavailable[20] = None
    assert _mock_spy_bias_failures(policy, {0, 10, 20, 25, 30}, unavailable) == {
        "spy-diagnostic-unavailable"
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
    calls = {"credential_loads": 0, "fetches": 0, "strategies": 0}
    request_calls: list[dict[str, Any]] = []
    synthetic_credentials = object()
    start = "2025-12-01T14:30:00Z"
    end = "2025-12-12T20:55:00Z"
    requests = _qualification_requests(plan, start=start, end=end)
    expected_requests = [
        {
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
        for adjustment in ("raw", "split,spin-off")
    ]
    maximum_pages = plan["full_acquisition_design"]["maximum_pages_per_chain"]
    assert requests == expected_requests

    def load_credentials() -> object:
        calls["credential_loads"] += 1
        return synthetic_credentials

    def fetch(credentials: object, request: dict[str, Any]) -> dict[str, Any]:
        assert credentials is synthetic_credentials
        calls["fetches"] += 1
        request_calls.append(deepcopy(request))
        adjustment = request["params"]["adjustment"]
        token = request["params"].get("page_token")
        if token is None:
            return {"rows": [start], "next_page_token": f"{adjustment}-page-2"}
        assert token == f"{adjustment}-page-2"
        return {"rows": [end], "next_page_token": None}

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
    assert rows == [start, end, start, end]
    assert calls["credential_loads"] == 1
    assert calls["fetches"] == 4
    assert [request["params"]["adjustment"] for request in request_calls] == [
        "raw",
        "raw",
        "split,spin-off",
        "split,spin-off",
    ]
    assert "page_token" not in request_calls[0]["params"]
    assert request_calls[1]["params"]["page_token"] == "raw-page-2"

    missing_feed = deepcopy(requests)
    missing_feed[0]["params"].pop("feed")
    extended_end = deepcopy(requests)
    extended_end[0]["params"]["end"] = "2025-12-12T21:00:00Z"
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
