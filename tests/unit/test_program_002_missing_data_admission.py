from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
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
    assess_missing_data_admission,
)

_START = date(2021, 1, 1)
_REPOSITORY = Path(__file__).resolve().parents[2]


def _expected(count: int = 100) -> tuple[ExpectedSession, ...]:
    return tuple(
        ExpectedSession(_START + timedelta(days=index), "period", 78) for index in range(count)
    )


def _complete(day: date, bars: int = 78) -> SessionCoverage:
    return SessionCoverage(day, {symbol: tuple(range(bars)) for symbol in PROGRAM_002_SYMBOLS})


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
    return assess_missing_data_admission(
        dataset_id="synthetic",
        dataset_fingerprint="0" * 64,
        expected_sessions=expected,
        session_coverage=coverage,
        expected_quote_windows=(quote,),
        quote_coverage=(observed,),
    )


def _remove(coverage: SessionCoverage, symbol: str, *indices: int) -> SessionCoverage:
    values = dict(coverage.observed_bar_indices_by_symbol)
    values[symbol] = tuple(index for index in values[symbol] if index not in indices)
    return SessionCoverage(coverage.session_date, values)


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


@pytest.mark.parametrize(
    ("missing", "index"),
    (("IWM", 0), ("IWM", 23), ("IWM", 25), ("IWM", 75), ("SPY", 0)),
)
def test_any_missing_source_aggregation_entry_exit_or_spy_bar_excludes_whole_session(
    missing: str, index: int
) -> None:
    expected = _expected()
    coverage = tuple(_complete(item.session_date) for item in expected)
    coverage = (_remove(coverage[0], missing, index), *coverage[1:])

    report = _report(expected, coverage)

    assert report["admission_passed"] is True
    assert report["eligible_sessions"] == [item.session_date.isoformat() for item in expected[1:]]
    assert report["ineligible_sessions"] == [expected[0].session_date.isoformat()]
    session = report["sessions"][0]
    assert session["disposition"] == "excluded-whole-session"
    assert session["trade_eligible"] is False


def test_one_or_several_missing_symbols_never_shrink_the_cross_section() -> None:
    expected = _expected()
    first = _complete(expected[0].session_date)
    values = dict(first.observed_bar_indices_by_symbol)
    values.pop("MDY")
    values.pop("XLE")
    coverage = (SessionCoverage(first.session_date, values),) + tuple(
        _complete(item.session_date) for item in expected[1:]
    )

    report = _report(expected, coverage)

    assert report["minimum_cross_section"] == {
        "ranking_symbols_required": 12,
        "spy_required": True,
        "total_symbols_required": 13,
    }
    session = report["sessions"][0]
    assert set(session["missing_bars_by_symbol"]) == {"MDY", "XLE"}


def test_complete_early_close_is_context_only_and_not_data_loss() -> None:
    expected = _expected()
    expected = (
        replace(expected[0], expected_bars_per_symbol=42, trade_scheduled=False),
        *expected[1:],
    )
    coverage = (_complete(expected[0].session_date, 42),) + tuple(
        _complete(item.session_date) for item in expected[1:]
    )

    report = _report(expected, coverage)

    session = report["sessions"][0]
    assert session["disposition"] == "scheduled-no-trade"
    assert session["context_eligible"] is True
    assert report["period_loss"][0]["excluded_trade_sessions"] == []


def test_contiguous_bar_gap_is_recorded_and_excludes_the_session() -> None:
    expected = _expected()
    coverage = tuple(_complete(item.session_date) for item in expected)
    coverage = (_remove(coverage[0], "MDY", 27, 28), *coverage[1:])

    report = _report(expected, coverage)

    assert report["admission_passed"] is True
    assert report["sessions"][0]["disposition"] == "excluded-whole-session"
    assert report["bias_diagnostics"]["maximum_contiguous_missing_bars"] == 2


def test_session_loss_boundary_passes_at_one_percent_and_fails_by_one() -> None:
    expected = _expected()
    complete = tuple(_complete(item.session_date) for item in expected)
    one = (_remove(complete[0], "MDY", 0), *complete[1:])
    two = (
        _remove(complete[0], "MDY", 0),
        *complete[1:50],
        _remove(complete[50], "XLE", 0),
        *complete[51:],
    )

    assert _report(expected, one)["admission_passed"] is True
    failed = _report(expected, two)
    assert failed["admission_passed"] is False
    assert "period-session-loss-ceiling-exceeded:period" in failed["failure_conditions"]


def test_repeated_missingness_inside_twenty_sessions_fails_nonrandomness_diagnostic() -> None:
    expected = _expected()
    complete = tuple(_complete(item.session_date) for item in expected)
    coverage = (
        _remove(complete[0], "MDY", 0),
        *complete[1:10],
        _remove(complete[10], "MDY", 0),
        *complete[11:],
    )

    report = _report(expected, coverage)

    assert report["admission_passed"] is False
    assert "rolling-session-loss-ceiling-exceeded" in report["failure_conditions"]
    assert "rolling-symbol-concentration-ceiling-exceeded" in report["failure_conditions"]
    assert report["bias_diagnostics"]["missing_session_count_by_symbol"] == {"MDY": 2}


def test_contiguous_incomplete_sessions_fail_the_contiguity_ceiling() -> None:
    expected = _expected()
    complete = tuple(_complete(item.session_date) for item in expected)
    coverage = (
        _remove(complete[0], "MDY", 0),
        _remove(complete[1], "XLE", 0),
        *complete[2:],
    )

    report = _report(expected, coverage)

    assert "contiguous-session-loss-ceiling-exceeded" in report["failure_conditions"]
    assert report["bias_diagnostics"]["maximum_contiguous_incomplete_sessions"] == 2


def test_required_context_gap_fails_instead_of_extending_the_chronology() -> None:
    expected = _expected()
    expected = (replace(expected[0], trade_scheduled=False, required_context=True), *expected[1:])
    coverage = tuple(_complete(item.session_date) for item in expected)
    coverage = (_remove(coverage[0], "MDY", 0), *coverage[1:])

    report = _report(expected, coverage)

    assert report["admission_passed"] is False
    assert "required-context-incomplete:period" in report["failure_conditions"]


def test_quote_grid_threshold_is_exact_and_missing_window_fails() -> None:
    expected = _expected()
    coverage = tuple(_complete(item.session_date) for item in expected)

    assert _report(expected, coverage, quote_count=57)["admission_passed"] is True
    missed = _report(expected, coverage, quote_count=56)
    assert missed["admission_passed"] is False
    assert "quote-calibration-coverage-failed" in missed["failure_conditions"]

    quote, _ = _quotes()
    missing = assess_missing_data_admission(
        dataset_id="synthetic",
        dataset_fingerprint="0" * 64,
        expected_sessions=expected,
        session_coverage=coverage,
        expected_quote_windows=(quote,),
        quote_coverage=(),
    )
    assert missing["admission_passed"] is False


def test_admission_is_order_independent_and_parallel_repetition_is_identical() -> None:
    expected = _expected()
    coverage = tuple(_complete(item.session_date) for item in expected)
    quote, observed = _quotes()

    def run() -> dict[str, Any]:
        return assess_missing_data_admission(
            dataset_id="synthetic",
            dataset_fingerprint="0" * 64,
            expected_sessions=tuple(reversed(expected)),
            session_coverage=tuple(reversed(coverage)),
            expected_quote_windows=(quote,),
            quote_coverage=(observed,),
        )

    sequential = run()

    with ThreadPoolExecutor(max_workers=4) as pool:
        parallel = tuple(pool.map(lambda _: run(), range(4)))

    assert all(item == sequential for item in parallel)
    assert len({item["admission_fingerprint"] for item in parallel}) == 1
