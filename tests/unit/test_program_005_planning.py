from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, time
from decimal import Decimal
from hashlib import sha256
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


def _run_mock_transport(
    *,
    authorized: bool,
    endpoint: str,
    load_credentials: Any,
    fetch: Any,
    maximum_pages: int = 4,
) -> list[Any]:
    parsed = urlsplit(endpoint)
    if not authorized:
        raise PermissionError("source request authority is false")
    if (parsed.scheme, parsed.netloc, parsed.path, parsed.query, parsed.fragment) != (
        "https",
        "data.alpaca.markets",
        "/v2/stocks/bars",
        "",
        "",
    ):
        raise PermissionError("endpoint is outside the frozen GET-only origin and path")

    credentials = load_credentials()
    token: str | None = None
    seen_tokens: set[str] = set()
    rows: list[Any] = []
    for _ in range(maximum_pages):
        page = fetch(credentials, token)
        if "next_page_token" not in page:
            raise ValueError("next_page_token field is required")
        rows.extend(page["rows"])
        next_token = page["next_page_token"]
        if next_token is None:
            return rows
        if next_token in seen_tokens:
            raise ValueError("repeated next_page_token")
        seen_tokens.add(next_token)
        token = next_token
    raise ValueError("page cap exceeded")


def _run_mock_strategy(*, dataset_admitted: bool, authorized: bool, execute: Any) -> Any:
    if not dataset_admitted or not authorized:
        raise PermissionError("strategy execution requires admission and separate authority")
    return execute()


def _mock_admission(
    quarantine: dict[int, set[str]],
    unexpected: dict[int, set[str]],
    *,
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

    if len(excluded) > 7:
        failures.add("global-count")
    if len(unexpected) > 2:
        failures.add("unexpected-count")
    if any(
        sum(year_by_session[index] == year for index in unexpected) > 1
        for year in set(year_by_session.values())
    ):
        failures.add("calendar-year")

    quarantine_blocks = {block_by_session[index] for index in quarantine}
    unexpected_blocks = [block_by_session[index] for index in unexpected]
    if len(unexpected_blocks) != len(set(unexpected_blocks)):
        failures.add("fixed-block")
    if quarantine_blocks.intersection(unexpected_blocks):
        failures.add("quarantine-block")

    ordered = sorted(excluded)
    if any(right - left == 1 for left, right in zip(ordered, ordered[1:], strict=False)):
        failures.add("adjacent")
    if any(
        0 < abs(index - other) <= 62 for index in unexpected for other in excluded if index != other
    ):
        failures.add("rolling-63")
    if any(
        0 < abs(index - other) <= 251
        and bool(symbols.intersection((quarantine | unexpected)[other]))
        for index, symbols in unexpected.items()
        for other in excluded
        if index != other
    ):
        failures.add("same-symbol-rolling-252")
    if excluded.intersection(initial_context or set()):
        failures.add("initial-context")
    if not action_ledger_resolved:
        failures.add("action-ledger")
    return excluded, failures


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
    assert loss["represented_calendar_years"] == list(range(2020, 2027))
    assert loss["source_exclusion_slots_per_represented_calendar_year"] == 1
    numerator, denominator = map(int, loss["overall_excluded_full_session_rate_exact"].split("/"))
    assert numerator == len(loss["represented_calendar_years"])
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
        year_by_session=years,
        block_by_session=blocks,
    )
    assert len(excluded) == 7
    assert failures == set()

    _, threshold_failures = _mock_admission(
        quarantine,
        passing_unexpected,
        year_by_session=years,
        block_by_session=blocks,
        ambiguous_actions={700},
    )
    assert {"global-count", "unexpected-count"} <= threshold_failures

    _, rolling_failures = _mock_admission(
        {},
        {500: {"XLF"}, 562: {"XLE"}},
        year_by_session=years,
        block_by_session=blocks,
    )
    assert "rolling-63" in rolling_failures

    _, adjacency_failures = _mock_admission(
        {},
        {500: {"XLF"}, 501: {"XLE"}},
        year_by_session=years,
        block_by_session=blocks,
    )
    assert {"adjacent", "rolling-63", "calendar-year", "fixed-block"} <= adjacency_failures

    _, symbol_failures = _mock_admission(
        {100: {"MDY"}},
        {300: {"MDY"}},
        year_by_session=years,
        block_by_session=blocks,
    )
    assert "same-symbol-rolling-252" in symbol_failures

    action_exclusions, action_failures = _mock_admission(
        {},
        {},
        year_by_session=years,
        block_by_session=blocks,
        ambiguous_actions={700},
        action_ledger_resolved=False,
    )
    assert action_exclusions == {700}
    assert "action-ledger" in action_failures


def test_mock_completeness_detects_missing_bars_across_sessions_and_spy() -> None:
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
    excluded, _ = _mock_admission(
        {},
        {
            index: {symbol for symbol, _ in missing_by_day[day.date()]}
            for index, day in enumerate(days, start=500)
        },
        year_by_session={500: 2025, 501: 2025},
        block_by_session={500: "block-a", 501: "block-b"},
    )
    assert excluded == {500, 501}
    assert all(
        timestamp.minute % 5 == 0
        for expected in expected_by_day.values()
        for _, timestamp in expected
    )


def test_mock_transport_paginates_and_denies_ungranted_actions() -> None:
    plan = _load(_PLAN_PATH)
    calls = {"credential_loads": 0, "fetches": 0, "strategies": 0}
    synthetic_credentials = object()
    start = "2025-12-01T14:30:00Z"
    end = "2025-12-12T20:55:00Z"

    def load_credentials() -> object:
        calls["credential_loads"] += 1
        return synthetic_credentials

    def fetch(credentials: object, token: str | None) -> dict[str, Any]:
        assert credentials is synthetic_credentials
        calls["fetches"] += 1
        if token is None:
            return {"rows": [start], "next_page_token": "page-2"}
        assert token == "page-2"
        return {"rows": [end], "next_page_token": None}

    with pytest.raises(PermissionError, match="authority is false"):
        _run_mock_transport(
            authorized=plan["authority"]["source_requests"],
            endpoint=plan["alpaca_basic_historical_sip_contract"]["endpoint"],
            load_credentials=load_credentials,
            fetch=fetch,
        )
    assert calls == {"credential_loads": 0, "fetches": 0, "strategies": 0}

    rows = _run_mock_transport(
        authorized=True,
        endpoint=plan["alpaca_basic_historical_sip_contract"]["endpoint"],
        load_credentials=load_credentials,
        fetch=fetch,
    )
    assert rows == [start, end]
    assert calls["credential_loads"] == 1
    assert calls["fetches"] == 2

    def repeated_token_fetch(credentials: object, token: str | None) -> dict[str, Any]:
        assert credentials is synthetic_credentials
        return {"rows": [], "next_page_token": "repeat"}

    with pytest.raises(ValueError, match="repeated next_page_token"):
        _run_mock_transport(
            authorized=True,
            endpoint=plan["alpaca_basic_historical_sip_contract"]["endpoint"],
            load_credentials=load_credentials,
            fetch=repeated_token_fetch,
        )
    with pytest.raises(PermissionError, match="outside the frozen"):
        _run_mock_transport(
            authorized=True,
            endpoint="https://api.alpaca.markets/v2/orders",
            load_credentials=load_credentials,
            fetch=fetch,
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
