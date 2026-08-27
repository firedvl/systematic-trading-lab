from __future__ import annotations

import inspect
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest

from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.program_002_missing_data_admission import (
    PROGRAM_002_SYMBOLS,
    ExpectedQuoteWindow,
    ExpectedSession,
    QuoteWindowCoverage,
    SessionCoverage,
    _assess_missing_data_admission,
    _load_exposed_contract,
    assess_program_002_exposed_missing_data_admission,
)

_START = date(2021, 1, 1)
_CONTEXT_SESSIONS = 20
_REPOSITORY = Path(__file__).resolve().parents[2]


def _bar_opens(day: date, count: int = 78) -> tuple[datetime, ...]:
    start = datetime.combine(day, time(14, 30), UTC)
    return tuple(start + timedelta(minutes=5 * index) for index in range(count))


def _expected(count: int = 100) -> tuple[ExpectedSession, ...]:
    context = tuple(
        ExpectedSession(
            _START + timedelta(days=index),
            "context",
            _bar_opens(_START + timedelta(days=index)),
            "required-context",
        )
        for index in range(_CONTEXT_SESSIONS)
    )
    evaluation = tuple(
        ExpectedSession(
            _START + timedelta(days=_CONTEXT_SESSIONS + index),
            "period",
            _bar_opens(_START + timedelta(days=_CONTEXT_SESSIONS + index)),
        )
        for index in range(count)
    )
    return context + evaluation


def _complete(expected: ExpectedSession) -> SessionCoverage:
    return SessionCoverage(
        expected.session_date,
        {symbol: expected.expected_bar_opens for symbol in PROGRAM_002_SYMBOLS},
    )


def _quotes(count: int = 57) -> tuple[ExpectedQuoteWindow, QuoteWindowCoverage]:
    expected = ExpectedQuoteWindow(_START, "11:35")
    return expected, QuoteWindowCoverage(
        expected.session_date,
        expected.clock,
        {symbol: count for symbol in PROGRAM_002_SYMBOLS},
    )


def _report(
    expected: tuple[ExpectedSession, ...],
    coverage: tuple[SessionCoverage, ...],
    *,
    quote_count: int = 57,
) -> dict[str, Any]:
    quote, observed = _quotes(quote_count)
    return _assess_missing_data_admission(
        dataset_id="synthetic",
        dataset_fingerprint="0" * 64,
        expected_sessions=expected,
        session_coverage=coverage,
        expected_quote_windows=(quote,),
        quote_coverage=(observed,),
        contract_binding={"kind": "synthetic-mechanics-only"},
    )


def _remove(coverage: SessionCoverage, symbol: str, *indices: int) -> SessionCoverage:
    values = dict(coverage.observed_bar_opens_by_symbol)
    values[symbol] = tuple(
        point for index, point in enumerate(values[symbol]) if index not in indices
    )
    return SessionCoverage(coverage.session_date, values)


def _trade_offset(index: int = 0) -> int:
    return _CONTEXT_SESSIONS + index


def test_frozen_disposition_binds_the_return_blind_control() -> None:
    path = _REPOSITORY / "config/research/program-002-missing-data-disposition-v1.json"

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    bound = dict(payload)
    expected_fingerprint = bound.pop("disposition_fingerprint")

    assert fingerprint(bound) == expected_fingerprint
    assert payload["deterministic_rules"]["unit_of_disposition"] == "whole XNYS session"
    assert payload["deterministic_rules"]["minimum_cross_sectional_coverage"] == {
        "ranking_symbols": 12,
        "spy": 1,
        "total_symbols": 13,
        "coverage_fraction": "1",
    }
    assert (
        payload["bar_completeness_requirements"]["maximum_missing_bars_in_an_eligible_session"] == 0
    )
    assert (
        payload["quote_completeness_requirements"][
            "minimum_eligible_grid_observations_per_symbol_window"
        ]
        == 57
    )
    loss = payload["maximum_allowable_data_loss"]
    assert loss["maximum_excluded_trade_session_fraction_per_fixed_evaluation_period"] == "0.01"
    assert loss["maximum_excluded_trade_sessions_per_fixed_evaluation_period"] == 1
    assert loss["rolling_session_window"] == 20
    assert loss["maximum_incomplete_sessions_per_rolling_window"] == 1
    assert loss["maximum_same_symbol_incomplete_sessions_per_rolling_window"] == 1
    assert loss["maximum_contiguous_incomplete_sessions"] == 1
    assert loss["required_context_session_loss"] == 0
    assert (
        payload["known_evidence_assessment"][
            "attempted_source_scientifically_admissible_under_disposition"
        ]
        is False
    )
    assert payload["known_evidence_assessment"]["different_source_recommended"] is True
    assert set(payload["authority"].values()) == {False}


def test_independent_review_is_finding_free_and_fingerprint_bound() -> None:
    path = (
        _REPOSITORY
        / "config/research/program-002-missing-data-disposition-independent-review-v1.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    bound = dict(payload)
    review_fingerprint = bound.pop("review_fingerprint")

    assert fingerprint(bound) == review_fingerprint
    assert payload["reviewed_commit"] == "2fde3d53682763e7e125b1940aa9971249dab4ef"
    assert payload["reviewed_disposition"]["sha256"] == (
        "26e7c84d97c08c7ef4439333aeb444a12a145f360140e93ebc1104118ec96699"
    )
    assert payload["verdict"] == "pass"
    assert payload["findings"] == []
    assert payload["known_source_assessment"]["attempted_source_admissible"] is False
    assert set(payload["authority"].values()) == {False}


def test_public_admission_boundary_has_no_schedule_or_policy_override() -> None:
    parameters = set(
        inspect.signature(assess_program_002_exposed_missing_data_admission).parameters
    )

    assert parameters == {
        "repository",
        "dataset_id",
        "dataset_fingerprint",
        "session_coverage",
        "quote_coverage",
    }


def test_exposed_contract_binds_exact_session_table_and_quote_grid() -> None:
    sessions, quote_windows, binding = _load_exposed_contract(_REPOSITORY)

    assert len(sessions) == 1531
    assert sum(item.required_context for item in sessions) == 20
    assert len(quote_windows) == 657
    assert binding["kind"] == "exact-exposed-program-002-v1"
    assert binding["expected_session_table_fingerprint"]
    assert binding["expected_quote_grid_fingerprint"]


@pytest.mark.parametrize(
    ("missing", "index"),
    (("IWM", 0), ("IWM", 23), ("IWM", 25), ("IWM", 75), ("SPY", 0)),
)
def test_any_missing_source_aggregation_entry_exit_or_spy_bar_excludes_whole_session(
    missing: str, index: int
) -> None:
    expected = _expected()
    coverage = tuple(_complete(item) for item in expected)
    target = _trade_offset()
    coverage = (
        *coverage[:target],
        _remove(coverage[target], missing, index),
        *coverage[target + 1 :],
    )

    report = _report(expected, coverage)

    assert report["admission_passed"] is True
    assert expected[target].session_date.isoformat() in report["ineligible_sessions"]
    session = report["sessions"][target]
    assert session["disposition"] == "excluded-whole-session"
    assert session["trade_eligible"] is False
    assert report["missing_coordinates"] == [
        {
            "session_date": expected[target].session_date.isoformat(),
            "symbol": missing,
            "bar_open_utc": expected[target]
            .expected_bar_opens[index]
            .isoformat()
            .replace("+00:00", "Z"),
            "reason": "expected-observation-absent",
        }
    ]


def test_one_or_several_missing_symbols_never_shrink_the_cross_section() -> None:
    expected = _expected()
    coverage = list(_complete(item) for item in expected)
    target = _trade_offset()
    values = dict(coverage[target].observed_bar_opens_by_symbol)
    values.pop("MDY")
    values.pop("XLE")
    coverage[target] = SessionCoverage(expected[target].session_date, values)

    report = _report(expected, tuple(coverage))

    assert report["minimum_cross_section"] == {
        "ranking_symbols_required": 12,
        "spy_required": True,
        "total_symbols_required": 13,
    }
    session = report["sessions"][target]
    assert set(session["missing_bar_opens_by_symbol"]) == {"MDY", "XLE"}
    assert session["eligible_symbol_count"] == 11


def test_complete_early_close_is_context_only_and_not_data_loss() -> None:
    expected = list(_expected())
    target = _trade_offset()
    expected[target] = replace(
        expected[target], expected_bar_opens=expected[target].expected_bar_opens[:42]
    )
    coverage = tuple(_complete(item) for item in expected)

    report = _report(tuple(expected), coverage)

    assert expected[target].trade_scheduled is False
    session = report["sessions"][target]
    assert session["disposition"] == "scheduled-early-close"
    assert session["trade_eligible"] is False
    assert session["context_eligible"] is True
    assert report["period_loss"][0]["excluded_trade_sessions"] == []


def test_contiguous_bar_gap_is_recorded_and_excludes_the_session() -> None:
    expected = _expected()
    coverage = list(_complete(item) for item in expected)
    target = _trade_offset()
    coverage[target] = _remove(coverage[target], "MDY", 27, 28)

    report = _report(expected, tuple(coverage))

    assert report["admission_passed"] is True
    assert report["sessions"][target]["disposition"] == "excluded-whole-session"
    assert report["bias_diagnostics"]["maximum_contiguous_missing_bars"] == 2
    assert report["bias_diagnostics"]["missing_coordinate_count_by_new_york_clock"] == {
        "11:45": 1,
        "11:50": 1,
    }


def test_session_loss_boundary_passes_at_one_percent_and_fails_by_one() -> None:
    expected = _expected()
    complete = tuple(_complete(item) for item in expected)
    first, second = _trade_offset(), _trade_offset(50)
    one = (*complete[:first], _remove(complete[first], "MDY", 0), *complete[first + 1 :])
    two = (
        *complete[:first],
        _remove(complete[first], "MDY", 0),
        *complete[first + 1 : second],
        _remove(complete[second], "XLE", 0),
        *complete[second + 1 :],
    )

    assert _report(expected, one)["admission_passed"] is True
    failed = _report(expected, two)
    assert failed["admission_passed"] is False
    assert "period-session-loss-ceiling-exceeded:period" in failed["failure_conditions"]


def test_repeated_missingness_inside_twenty_sessions_fails_nonrandomness_diagnostic() -> None:
    expected = _expected()
    coverage = list(_complete(item) for item in expected)
    first, second = _trade_offset(), _trade_offset(10)
    coverage[first] = _remove(coverage[first], "MDY", 0)
    coverage[second] = _remove(coverage[second], "MDY", 0)

    report = _report(expected, tuple(coverage))

    assert report["admission_passed"] is False
    assert "rolling-session-loss-ceiling-exceeded" in report["failure_conditions"]
    assert "rolling-symbol-concentration-ceiling-exceeded:MDY" in report["failure_conditions"]
    assert report["bias_diagnostics"]["missing_session_count_by_symbol"] == {"MDY": 2}


def test_contiguous_incomplete_sessions_fail_the_contiguity_ceiling() -> None:
    expected = _expected()
    coverage = list(_complete(item) for item in expected)
    first, second = _trade_offset(), _trade_offset(1)
    coverage[first] = _remove(coverage[first], "MDY", 0)
    coverage[second] = _remove(coverage[second], "XLE", 0)

    report = _report(expected, tuple(coverage))

    assert "contiguous-session-loss-ceiling-exceeded" in report["failure_conditions"]
    assert report["bias_diagnostics"]["maximum_contiguous_incomplete_sessions"] == 2


def test_required_context_gap_fails_and_removes_first_trade_session_context() -> None:
    expected = _expected()
    coverage = list(_complete(item) for item in expected)
    coverage[0] = _remove(coverage[0], "MDY", 0)

    report = _report(expected, tuple(coverage))

    first_trade = report["sessions"][_trade_offset()]
    assert report["admission_passed"] is False
    assert "required-context-incomplete:context" in report["failure_conditions"]
    assert first_trade["causal_context_complete"] is False
    assert first_trade["disposition"] == "excluded-insufficient-prior-context"


def test_quote_grid_threshold_is_exact_and_missing_window_fails() -> None:
    expected = _expected()
    coverage = tuple(_complete(item) for item in expected)

    assert _report(expected, coverage, quote_count=57)["admission_passed"] is True
    missed = _report(expected, coverage, quote_count=56)
    assert missed["admission_passed"] is False
    assert "quote-calibration-coverage-failed" in missed["failure_conditions"]

    quote, _ = _quotes()
    missing = _assess_missing_data_admission(
        dataset_id="synthetic",
        dataset_fingerprint="0" * 64,
        expected_sessions=expected,
        session_coverage=coverage,
        expected_quote_windows=(quote,),
        quote_coverage=(),
        contract_binding={"kind": "synthetic-mechanics-only"},
    )
    assert missing["admission_passed"] is False


def test_admission_is_order_independent_and_parallel_repetition_is_identical() -> None:
    expected = _expected()
    coverage = tuple(_complete(item) for item in expected)
    quote, observed = _quotes()

    def run() -> dict[str, Any]:
        return _assess_missing_data_admission(
            dataset_id="synthetic",
            dataset_fingerprint="0" * 64,
            expected_sessions=tuple(reversed(expected)),
            session_coverage=tuple(reversed(coverage)),
            expected_quote_windows=(quote,),
            quote_coverage=(observed,),
            contract_binding={"kind": "synthetic-mechanics-only"},
        )

    sequential = run()
    with ThreadPoolExecutor(max_workers=4) as pool:
        parallel = tuple(pool.map(lambda _: run(), range(4)))

    assert all(item == sequential for item in parallel)
    assert len({item["admission_fingerprint"] for item in parallel}) == 1
