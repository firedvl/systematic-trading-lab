"""Structural, return-blind Program 002 missing-data admission."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from .fingerprints import fingerprint

PROGRAM_002_SYMBOLS = (
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


@dataclass(frozen=True)
class ExpectedSession:
    session_date: date
    period_id: str
    expected_bars_per_symbol: int
    trade_scheduled: bool = True
    required_context: bool = False

    def __post_init__(self) -> None:
        if not self.period_id or self.expected_bars_per_symbol not in {42, 78}:
            raise ValueError("Program 002 expected session is invalid")
        if self.required_context and self.trade_scheduled:
            raise ValueError("Program 002 required context cannot be trade scheduled")


@dataclass(frozen=True)
class SessionCoverage:
    session_date: date
    observed_bar_indices_by_symbol: Mapping[str, Sequence[int]]

    def __post_init__(self) -> None:
        frozen: dict[str, tuple[int, ...]] = {}
        for symbol, indices in self.observed_bar_indices_by_symbol.items():
            ordered = tuple(indices)
            if any(isinstance(index, bool) or not isinstance(index, int) for index in ordered):
                raise ValueError("Program 002 bar index is invalid")
            if len(set(ordered)) != len(ordered):
                raise ValueError("Program 002 bar coverage contains a duplicate")
            frozen[symbol] = tuple(sorted(ordered))
        object.__setattr__(
            self,
            "observed_bar_indices_by_symbol",
            MappingProxyType(dict(sorted(frozen.items()))),
        )


@dataclass(frozen=True, order=True)
class ExpectedQuoteWindow:
    session_date: date
    clock: str


@dataclass(frozen=True)
class QuoteWindowCoverage:
    session_date: date
    clock: str
    eligible_grid_observations_by_symbol: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "eligible_grid_observations_by_symbol",
            MappingProxyType(dict(sorted(self.eligible_grid_observations_by_symbol.items()))),
        )


@dataclass(frozen=True)
class AdmissionPolicy:
    maximum_excluded_session_fraction_per_period: Decimal = Decimal("0.01")
    maximum_excluded_sessions_per_period: int = 1
    rolling_session_window: int = 20
    maximum_incomplete_sessions_per_rolling_window: int = 1
    maximum_contiguous_incomplete_sessions: int = 1
    quote_grid_observations: int = 60
    minimum_eligible_quote_observations: int = 57


def assess_missing_data_admission(
    *,
    dataset_id: str,
    dataset_fingerprint: str,
    expected_sessions: Sequence[ExpectedSession],
    session_coverage: Sequence[SessionCoverage],
    expected_quote_windows: Sequence[ExpectedQuoteWindow],
    quote_coverage: Sequence[QuoteWindowCoverage],
    policy: AdmissionPolicy | None = None,
) -> dict[str, Any]:
    """Return deterministic structural facts without candidate or return computation."""
    policy = AdmissionPolicy() if policy is None else policy
    if not dataset_id or not dataset_fingerprint:
        raise ValueError("Program 002 dataset identity is required")
    if (
        policy.maximum_excluded_sessions_per_period < 0
        or not Decimal(0) <= policy.maximum_excluded_session_fraction_per_period <= Decimal(1)
        or policy.rolling_session_window < 1
        or policy.maximum_incomplete_sessions_per_rolling_window < 0
        or policy.maximum_contiguous_incomplete_sessions < 0
        or not 0 <= policy.minimum_eligible_quote_observations <= policy.quote_grid_observations
    ):
        raise ValueError("Program 002 admission policy is invalid")
    expected = tuple(sorted(expected_sessions, key=lambda item: item.session_date))
    if not expected or len({item.session_date for item in expected}) != len(expected):
        raise ValueError("Program 002 expected sessions are empty or duplicated")
    sessions = _unique_by_date(session_coverage)
    unexpected_sessions = set(sessions) - {item.session_date for item in expected}
    if unexpected_sessions:
        raise ValueError("Program 002 coverage contains an unexpected session")

    failure_conditions: set[str] = set()
    session_rows: list[dict[str, Any]] = []
    missing_sessions_by_symbol: Counter[str] = Counter()
    missing_bars_by_symbol: Counter[str] = Counter()
    missing_dates_by_symbol: dict[str, set[date]] = {
        symbol: set() for symbol in PROGRAM_002_SYMBOLS
    }
    incomplete_dates: set[date] = set()
    max_contiguous_missing_bars = 0

    for item in expected:
        coverage = sessions.get(item.session_date)
        observed = coverage.observed_bar_indices_by_symbol if coverage is not None else {}
        if set(observed) - set(PROGRAM_002_SYMBOLS):
            raise ValueError("Program 002 coverage contains an unexpected symbol")
        expected_indices = set(range(item.expected_bars_per_symbol))
        missing: dict[str, tuple[int, ...]] = {}
        for symbol in PROGRAM_002_SYMBOLS:
            indices = tuple(observed.get(symbol, ()))
            if any(index < 0 or index >= item.expected_bars_per_symbol for index in indices):
                raise ValueError("Program 002 coverage contains an unexpected bar")
            absent = tuple(sorted(expected_indices - set(indices)))
            if absent:
                missing[symbol] = absent
                missing_sessions_by_symbol[symbol] += 1
                missing_bars_by_symbol[symbol] += len(absent)
                missing_dates_by_symbol[symbol].add(item.session_date)
                max_contiguous_missing_bars = max(
                    max_contiguous_missing_bars, _maximum_contiguous(absent)
                )
        complete = not missing
        if not complete:
            incomplete_dates.add(item.session_date)
        if item.required_context and not complete:
            failure_conditions.add(f"required-context-incomplete:{item.period_id}")
        session_rows.append(
            {
                "session_date": item.session_date.isoformat(),
                "period_id": item.period_id,
                "scheduled_role": (
                    "trade"
                    if item.trade_scheduled
                    else "required-context"
                    if item.required_context
                    else "scheduled-no-trade-context"
                ),
                "expected_bars_per_symbol": item.expected_bars_per_symbol,
                "cross_section_complete": complete,
                "trade_eligible": item.trade_scheduled and complete,
                "context_eligible": complete,
                "missing_bars_by_symbol": {
                    symbol: list(indices) for symbol, indices in sorted(missing.items())
                },
                "disposition": (
                    "eligible"
                    if item.trade_scheduled and complete
                    else "scheduled-no-trade"
                    if complete
                    else "excluded-whole-session"
                ),
            }
        )

    period_rows = _period_diagnostics(expected, incomplete_dates, policy, failure_conditions)
    rolling = _rolling_diagnostics(
        expected,
        incomplete_dates,
        missing_dates_by_symbol,
        policy,
        failure_conditions,
    )
    contiguous_incomplete_sessions = _maximum_contiguous_sessions(expected, incomplete_dates)
    if contiguous_incomplete_sessions > policy.maximum_contiguous_incomplete_sessions:
        failure_conditions.add("contiguous-session-loss-ceiling-exceeded")
    quote_rows = _quote_diagnostics(
        expected_quote_windows, quote_coverage, policy, failure_conditions
    )
    eligible_sessions = tuple(row["session_date"] for row in session_rows if row["trade_eligible"])
    ineligible_sessions = tuple(
        row["session_date"]
        for row in session_rows
        if row["disposition"] == "excluded-whole-session"
    )
    payload: dict[str, Any] = {
        "schema_version": "program-002-missing-data-admission-report-v1",
        "dataset_id": dataset_id,
        "dataset_fingerprint": dataset_fingerprint,
        "admission_passed": not failure_conditions,
        "failure_conditions": sorted(failure_conditions),
        "eligible_sessions": list(eligible_sessions),
        "ineligible_sessions": list(ineligible_sessions),
        "minimum_cross_section": {
            "ranking_symbols_required": 12,
            "spy_required": True,
            "total_symbols_required": 13,
        },
        "sessions": session_rows,
        "period_loss": period_rows,
        "quote_windows": quote_rows,
        "bias_diagnostics": {
            "missing_session_count_by_symbol": dict(sorted(missing_sessions_by_symbol.items())),
            "missing_bar_count_by_symbol": dict(sorted(missing_bars_by_symbol.items())),
            "incomplete_session_count_by_month": dict(
                sorted(Counter(day.strftime("%Y-%m") for day in incomplete_dates).items())
            ),
            "maximum_incomplete_sessions_in_rolling_window": rolling[0],
            "maximum_same_symbol_incomplete_sessions_in_rolling_window": rolling[1],
            "maximum_contiguous_incomplete_sessions": contiguous_incomplete_sessions,
            "maximum_contiguous_missing_bars": max_contiguous_missing_bars,
        },
        "authority": {
            "market_data_acquisition": False,
            "strategy_implementation": False,
            "strategy_execution": False,
            "research_qualification": False,
            "controlled_evaluation": False,
            "protected_holdout": False,
            "paper_execution": False,
            "broker_writes": False,
            "live_execution": False,
        },
    }
    payload["admission_fingerprint"] = fingerprint(payload)
    return payload


def _unique_by_date(values: Sequence[SessionCoverage]) -> dict[date, SessionCoverage]:
    result = {item.session_date: item for item in values}
    if len(result) != len(values):
        raise ValueError("Program 002 session coverage is duplicated")
    return result


def _maximum_contiguous(indices: Sequence[int]) -> int:
    maximum = current = 0
    previous: int | None = None
    for index in indices:
        current = current + 1 if previous is not None and index == previous + 1 else 1
        maximum = max(maximum, current)
        previous = index
    return maximum


def _maximum_contiguous_sessions(
    expected: Sequence[ExpectedSession], incomplete_dates: set[date]
) -> int:
    maximum = current = 0
    for item in expected:
        current = current + 1 if item.session_date in incomplete_dates else 0
        maximum = max(maximum, current)
    return maximum


def _period_diagnostics(
    expected: Sequence[ExpectedSession],
    incomplete_dates: set[date],
    policy: AdmissionPolicy,
    failure_conditions: set[str],
) -> list[dict[str, Any]]:
    periods = sorted({item.period_id for item in expected})
    rows: list[dict[str, Any]] = []
    for period_id in periods:
        trade_dates = tuple(
            item.session_date
            for item in expected
            if item.period_id == period_id and item.trade_scheduled
        )
        excluded = tuple(day for day in trade_dates if day in incomplete_dates)
        fraction = Decimal(len(excluded)) / len(trade_dates) if trade_dates else Decimal(0)
        if (
            len(excluded) > policy.maximum_excluded_sessions_per_period
            or fraction > policy.maximum_excluded_session_fraction_per_period
        ):
            failure_conditions.add(f"period-session-loss-ceiling-exceeded:{period_id}")
        rows.append(
            {
                "period_id": period_id,
                "scheduled_trade_sessions": len(trade_dates),
                "excluded_trade_sessions": list(map(date.isoformat, excluded)),
                "excluded_session_fraction": format(fraction, "f"),
            }
        )
    return rows


def _rolling_diagnostics(
    expected: Sequence[ExpectedSession],
    incomplete_dates: set[date],
    missing_dates_by_symbol: Mapping[str, set[date]],
    policy: AdmissionPolicy,
    failure_conditions: set[str],
) -> tuple[int, int]:
    maximum_incomplete = 0
    maximum_same_symbol = 0
    rows = tuple(expected)
    for offset in range(max(1, len(rows) - policy.rolling_session_window + 1)):
        window = rows[offset : offset + policy.rolling_session_window]
        if len(window) < policy.rolling_session_window:
            continue
        count = sum(item.session_date in incomplete_dates for item in window)
        maximum_incomplete = max(maximum_incomplete, count)
        if count > policy.maximum_incomplete_sessions_per_rolling_window:
            failure_conditions.add("rolling-session-loss-ceiling-exceeded")
        window_dates = {item.session_date for item in window}
        same_symbol = max(
            (len(window_dates & missing_dates_by_symbol[symbol]) for symbol in PROGRAM_002_SYMBOLS),
            default=0,
        )
        maximum_same_symbol = max(maximum_same_symbol, same_symbol)
        if same_symbol > policy.maximum_incomplete_sessions_per_rolling_window:
            failure_conditions.add("rolling-symbol-concentration-ceiling-exceeded")
    return maximum_incomplete, maximum_same_symbol


def _quote_diagnostics(
    expected: Sequence[ExpectedQuoteWindow],
    observed: Sequence[QuoteWindowCoverage],
    policy: AdmissionPolicy,
    failure_conditions: set[str],
) -> list[dict[str, Any]]:
    expected_keys = tuple(sorted(expected))
    if not expected_keys or len(set(expected_keys)) != len(expected_keys):
        raise ValueError("Program 002 expected quote windows are empty or duplicated")
    by_key = {(item.session_date, item.clock): item for item in observed}
    if len(by_key) != len(observed):
        raise ValueError("Program 002 quote coverage is duplicated")
    if set(by_key) - {(item.session_date, item.clock) for item in expected_keys}:
        raise ValueError("Program 002 quote coverage contains an unexpected window")
    rows: list[dict[str, Any]] = []
    for item in expected_keys:
        coverage = by_key.get((item.session_date, item.clock))
        values = coverage.eligible_grid_observations_by_symbol if coverage is not None else {}
        if set(values) - set(PROGRAM_002_SYMBOLS):
            raise ValueError("Program 002 quote coverage contains an unexpected symbol")
        resolved: dict[str, int] = {}
        for symbol in PROGRAM_002_SYMBOLS:
            count = values.get(symbol, 0)
            if (
                isinstance(count, bool)
                or not isinstance(count, int)
                or not 0 <= count <= policy.quote_grid_observations
            ):
                raise ValueError("Program 002 quote coverage count is invalid")
            resolved[symbol] = count
            if count < policy.minimum_eligible_quote_observations:
                failure_conditions.add("quote-calibration-coverage-failed")
        rows.append(
            {
                "session_date": item.session_date.isoformat(),
                "clock": item.clock,
                "eligible_grid_observations_by_symbol": resolved,
                "coverage_passed": all(
                    count >= policy.minimum_eligible_quote_observations
                    for count in resolved.values()
                ),
            }
        )
    return rows
