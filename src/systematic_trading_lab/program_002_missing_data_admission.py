"""Structural, return-blind Program 002 missing-data admission."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

from .calendar import expected_bar_timestamps
from .domain import Timeframe
from .fingerprints import fingerprint
from .multi_hour_sector_etf_plan import (
    load_program_002_account_proof_plan,
    load_program_002_plan,
)

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

_NY = ZoneInfo("America/New_York")
_DISPOSITION_PATH = Path("config/research/program-002-missing-data-disposition-v1.json")
_DISPOSITION_SHA256 = "26e7c84d97c08c7ef4439333aeb444a12a145f360140e93ebc1104118ec96699"
_DISPOSITION_FINGERPRINT = "291c7bccce40440773b32157e1518abc31fe783e0a0b0763dfd100b55e95bbfe"
_EXPOSED_SESSION_TABLE_FINGERPRINT = (
    "868722db6433197ea2ea8baf4b4ec86609433d73c5f0b56e7194c250dd3cc25e"
)
_QUOTE_GRID_FINGERPRINT = "3eb70161181aab68f6fd23475e46fbe17b620ff5584c78f525e8816ece135577"
_MAXIMUM_EXCLUDED_SESSION_FRACTION_PER_PERIOD = Decimal("0.01")
_MAXIMUM_EXCLUDED_SESSIONS_PER_PERIOD = 1
_ROLLING_SESSION_WINDOW = 20
_MAXIMUM_INCOMPLETE_SESSIONS_PER_ROLLING_WINDOW = 1
_MAXIMUM_CONTIGUOUS_INCOMPLETE_SESSIONS = 1
_QUOTE_GRID_OBSERVATIONS = 60
_MINIMUM_ELIGIBLE_QUOTE_OBSERVATIONS = 57


@dataclass(frozen=True)
class ExpectedSession:
    session_date: date
    period_id: str
    expected_bar_opens: Sequence[datetime]
    role: str = "evaluation"

    def __post_init__(self) -> None:
        points = tuple(self.expected_bar_opens)
        if (
            not self.period_id
            or self.role not in {"evaluation", "required-context"}
            or len(points) not in {42, 78}
            or len(set(points)) != len(points)
            or points != tuple(sorted(points))
            or any(
                point.tzinfo is None
                or point.utcoffset() != timedelta(0)
                or point.astimezone(_NY).date() != self.session_date
                for point in points
            )
        ):
            raise ValueError("Program 002 expected session is invalid")
        object.__setattr__(self, "expected_bar_opens", points)

    @property
    def required_context(self) -> bool:
        return self.role == "required-context"

    @property
    def early_close(self) -> bool:
        return len(self.expected_bar_opens) == 42

    @property
    def trade_scheduled(self) -> bool:
        return self.role == "evaluation" and not self.early_close


@dataclass(frozen=True)
class SessionCoverage:
    session_date: date
    observed_bar_opens_by_symbol: Mapping[str, Sequence[datetime]]

    def __post_init__(self) -> None:
        frozen: dict[str, tuple[datetime, ...]] = {}
        for symbol, points in self.observed_bar_opens_by_symbol.items():
            ordered = tuple(points)
            if len(set(ordered)) != len(ordered) or any(
                point.tzinfo is None or point.utcoffset() != timedelta(0) for point in ordered
            ):
                raise ValueError("Program 002 bar coverage is invalid")
            frozen[symbol] = tuple(sorted(ordered))
        object.__setattr__(
            self,
            "observed_bar_opens_by_symbol",
            MappingProxyType(dict(sorted(frozen.items()))),
        )


@dataclass(frozen=True, order=True)
class ExpectedQuoteWindow:
    session_date: date
    clock: str

    def __post_init__(self) -> None:
        try:
            parsed = time.fromisoformat(self.clock)
        except ValueError as error:
            raise ValueError("Program 002 quote clock is invalid") from error
        if parsed.second or parsed.microsecond:
            raise ValueError("Program 002 quote clock is invalid")


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


def assess_program_002_exposed_missing_data_admission(
    *,
    repository: Path,
    dataset_id: str,
    dataset_fingerprint: str,
    session_coverage: Sequence[SessionCoverage],
    quote_coverage: Sequence[QuoteWindowCoverage],
) -> dict[str, Any]:
    """Assess only the exact frozen exposed Program 002 contract."""
    if not re.fullmatch(r"[0-9a-f]{64}", dataset_id) or not re.fullmatch(
        r"[0-9a-f]{64}", dataset_fingerprint
    ):
        raise ValueError("Program 002 dataset identity is invalid")
    expected_sessions, expected_quote_windows, binding = _load_exposed_contract(repository)
    return _assess_missing_data_admission(
        dataset_id=dataset_id,
        dataset_fingerprint=dataset_fingerprint,
        expected_sessions=expected_sessions,
        session_coverage=session_coverage,
        expected_quote_windows=expected_quote_windows,
        quote_coverage=quote_coverage,
        contract_binding=binding,
    )


def _assess_missing_data_admission(
    *,
    dataset_id: str,
    dataset_fingerprint: str,
    expected_sessions: Sequence[ExpectedSession],
    session_coverage: Sequence[SessionCoverage],
    expected_quote_windows: Sequence[ExpectedQuoteWindow],
    quote_coverage: Sequence[QuoteWindowCoverage],
    contract_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate frozen mechanics; tests use this privately with synthetic contracts."""
    if not dataset_id or not dataset_fingerprint or not contract_binding:
        raise ValueError("Program 002 dataset and contract identity are required")
    expected = tuple(sorted(expected_sessions, key=lambda item: item.session_date))
    if not expected or len({item.session_date for item in expected}) != len(expected):
        raise ValueError("Program 002 expected sessions are empty or duplicated")
    sessions = _unique_by_date(session_coverage)
    if set(sessions) - {item.session_date for item in expected}:
        raise ValueError("Program 002 coverage contains an unexpected session")

    failure_conditions: set[str] = set()
    session_rows: list[dict[str, Any]] = []
    missing_coordinates: list[dict[str, str]] = []
    missing_sessions_by_symbol: Counter[str] = Counter()
    missing_bars_by_symbol: Counter[str] = Counter()
    missing_bars_by_month: Counter[str] = Counter()
    missing_bars_by_clock: Counter[str] = Counter()
    missing_dates_by_symbol: dict[str, set[date]] = {
        symbol: set() for symbol in PROGRAM_002_SYMBOLS
    }
    incomplete_dates: set[date] = set()
    prior_complete_dates: list[date] = []
    max_contiguous_missing_bars = 0

    for item in expected:
        coverage = sessions.get(item.session_date)
        observed = coverage.observed_bar_opens_by_symbol if coverage is not None else {}
        if set(observed) - set(PROGRAM_002_SYMBOLS):
            raise ValueError("Program 002 coverage contains an unexpected symbol")
        expected_points = set(item.expected_bar_opens)
        missing: dict[str, tuple[datetime, ...]] = {}
        complete_symbol_count = 0
        for symbol in PROGRAM_002_SYMBOLS:
            points = tuple(observed.get(symbol, ()))
            if set(points) - expected_points:
                raise ValueError("Program 002 coverage contains an unexpected bar")
            absent = tuple(sorted(expected_points - set(points)))
            if not absent:
                complete_symbol_count += 1
                continue
            missing[symbol] = absent
            missing_sessions_by_symbol[symbol] += 1
            missing_bars_by_symbol[symbol] += len(absent)
            missing_dates_by_symbol[symbol].add(item.session_date)
            max_contiguous_missing_bars = max(
                max_contiguous_missing_bars, _maximum_contiguous_bars(absent)
            )
            for point in absent:
                missing_bars_by_month[point.astimezone(_NY).strftime("%Y-%m")] += 1
                missing_bars_by_clock[point.astimezone(_NY).strftime("%H:%M")] += 1
                missing_coordinates.append(
                    {
                        "session_date": item.session_date.isoformat(),
                        "symbol": symbol,
                        "bar_open_utc": _iso(point),
                        "reason": "expected-observation-absent",
                    }
                )
        complete = not missing
        if not complete:
            incomplete_dates.add(item.session_date)
        prior_context = tuple(prior_complete_dates[-_ROLLING_SESSION_WINDOW:])
        causal_context_complete = len(prior_context) == _ROLLING_SESSION_WINDOW
        if item.required_context and not complete:
            failure_conditions.add(f"required-context-incomplete:{item.period_id}")
        trade_eligible = item.trade_scheduled and complete and causal_context_complete
        if item.trade_scheduled and complete and not causal_context_complete:
            failure_conditions.add(f"insufficient-prior-context:{item.session_date.isoformat()}")
        disposition = (
            "excluded-whole-session"
            if not complete
            else "required-context"
            if item.required_context
            else "scheduled-early-close"
            if item.early_close
            else "eligible"
            if trade_eligible
            else "excluded-insufficient-prior-context"
        )
        expected_count = len(item.expected_bar_opens) * len(PROGRAM_002_SYMBOLS)
        observed_count = expected_count - sum(len(points) for points in missing.values())
        session_rows.append(
            {
                "session_date": item.session_date.isoformat(),
                "period_id": item.period_id,
                "scheduled_role": (
                    "required-context"
                    if item.required_context
                    else "scheduled-early-close"
                    if item.early_close
                    else "trade"
                ),
                "expected_bars_per_symbol": len(item.expected_bar_opens),
                "eligible_symbol_count": complete_symbol_count,
                "completeness_ratio": format(Decimal(observed_count) / expected_count, "f"),
                "cross_section_complete": complete,
                "causal_context_complete": causal_context_complete,
                "prior_context_sessions": [day.isoformat() for day in prior_context],
                "trade_eligible": trade_eligible,
                "context_eligible": complete,
                "missing_bar_opens_by_symbol": {
                    symbol: [_iso(point) for point in points]
                    for symbol, points in sorted(missing.items())
                },
                "missingness_reason": "expected-observation-absent" if missing else None,
                "disposition": disposition,
            }
        )
        if complete:
            prior_complete_dates.append(item.session_date)

    period_rows = _period_diagnostics(session_rows, failure_conditions)
    rolling = _rolling_diagnostics(
        expected, incomplete_dates, missing_dates_by_symbol, failure_conditions
    )
    contiguous_incomplete_sessions = _maximum_contiguous_sessions(expected, incomplete_dates)
    if contiguous_incomplete_sessions > _MAXIMUM_CONTIGUOUS_INCOMPLETE_SESSIONS:
        failure_conditions.add("contiguous-session-loss-ceiling-exceeded")
    quote_rows, quote_summary = _quote_diagnostics(
        expected_quote_windows, quote_coverage, failure_conditions
    )
    payload: dict[str, Any] = {
        "schema_version": "program-002-missing-data-admission-report-v1",
        "dataset_id": dataset_id,
        "dataset_fingerprint": dataset_fingerprint,
        "contract_binding": dict(contract_binding),
        "admission_passed": not failure_conditions,
        "failure_conditions": sorted(failure_conditions),
        "eligible_sessions": [row["session_date"] for row in session_rows if row["trade_eligible"]],
        "ineligible_sessions": [
            row["session_date"]
            for row in session_rows
            if str(row["disposition"]).startswith("excluded-")
        ],
        "minimum_cross_section": {
            "ranking_symbols_required": 12,
            "spy_required": True,
            "total_symbols_required": 13,
        },
        "sessions": session_rows,
        "missing_coordinates": missing_coordinates,
        "period_loss": period_rows,
        "quote_windows": quote_rows,
        "quote_summary": quote_summary,
        "bias_diagnostics": {
            "missing_session_count_by_symbol": dict(sorted(missing_sessions_by_symbol.items())),
            "missing_bar_count_by_symbol": dict(sorted(missing_bars_by_symbol.items())),
            "incomplete_session_count_by_month": dict(
                sorted(Counter(day.strftime("%Y-%m") for day in incomplete_dates).items())
            ),
            "missing_coordinate_count_by_month": dict(sorted(missing_bars_by_month.items())),
            "missing_coordinate_count_by_new_york_clock": dict(
                sorted(missing_bars_by_clock.items())
            ),
            "full_and_early_close_missingness": {
                "scheduled_full_sessions": sum(not item.early_close for item in expected),
                "scheduled_early_closes": sum(item.early_close for item in expected),
                "incomplete_full_sessions": sum(
                    item.session_date in incomplete_dates and not item.early_close
                    for item in expected
                ),
                "incomplete_early_closes": sum(
                    item.session_date in incomplete_dates and item.early_close for item in expected
                ),
            },
            "maximum_incomplete_sessions_in_rolling_window": rolling[0],
            "maximum_same_symbol_incomplete_sessions_in_rolling_window": rolling[1],
            "maximum_contiguous_incomplete_sessions": contiguous_incomplete_sessions,
            "maximum_contiguous_missing_bars": max_contiguous_missing_bars,
        },
        "frozen_policy": {
            "maximum_excluded_session_fraction_per_period": "0.01",
            "maximum_excluded_sessions_per_period": 1,
            "rolling_session_window": 20,
            "maximum_incomplete_sessions_per_rolling_window": 1,
            "maximum_same_symbol_incomplete_sessions_per_rolling_window": 1,
            "maximum_contiguous_incomplete_sessions": 1,
            "quote_grid_observations": 60,
            "minimum_eligible_quote_observations": 57,
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


def _load_exposed_contract(
    repository: Path,
) -> tuple[tuple[ExpectedSession, ...], tuple[ExpectedQuoteWindow, ...], Mapping[str, Any]]:
    repository = repository.resolve()
    disposition_sha256, disposition_fingerprint = _verify_disposition(repository)
    plan = load_program_002_plan(repository)
    acquisition = load_program_002_account_proof_plan(repository)
    chronology = _mapping(plan.payload.get("chronology"), "Program 002 chronology")

    context = _mapping(chronology.get("exposed_context_only"), "Program 002 context")
    sessions = list(
        _expected_session_range(
            context["start"],
            context["end"],
            "exposed-context-only",
            "required-context",
        )
    )
    if len(sessions) != context.get("session_count"):
        raise ValueError("Program 002 exposed context session table differs")

    discovery = chronology.get("discovery_blocks")
    if not isinstance(discovery, list):
        raise ValueError("Program 002 discovery chronology differs")
    for raw in discovery:
        block = _mapping(raw, "Program 002 discovery block")
        rows = _expected_session_range(
            block["start"], block["end"], str(block["block_id"]), "evaluation"
        )
        if len(rows) != block.get("xnys_sessions") or sum(
            row.trade_scheduled for row in rows
        ) != block.get("trade_eligible_full_sessions"):
            raise ValueError("Program 002 discovery session table differs")
        sessions.extend(rows)

    walk_forward = _mapping(chronology.get("walk_forward"), "Program 002 walk-forward")
    folds = walk_forward.get("folds")
    if not isinstance(folds, list):
        raise ValueError("Program 002 walk-forward chronology differs")
    for raw in folds:
        fold = _mapping(raw, "Program 002 walk-forward fold")
        rows = _expected_session_range(
            fold["test_start"], fold["test_end"], str(fold["fold_id"]), "evaluation"
        )
        if len(rows) != walk_forward.get("test_sessions"):
            raise ValueError("Program 002 walk-forward session table differs")
        sessions.extend(rows)

    expected_sessions = tuple(sessions)
    if len({item.session_date for item in expected_sessions}) != len(expected_sessions):
        raise ValueError("Program 002 exposed session table overlaps")
    session_fingerprint = _session_table_fingerprint(expected_sessions)
    if session_fingerprint != _EXPOSED_SESSION_TABLE_FINGERPRINT:
        raise ValueError("Program 002 exposed session table fingerprint differs")

    quote = _mapping(acquisition.payload.get("quote_cost_calibration"), "quote calibration")
    quote_sessions, clocks = quote.get("sessions"), quote.get("fill_clocks_new_york")
    if not isinstance(quote_sessions, list) or not isinstance(clocks, list):
        raise ValueError("Program 002 quote grid differs")
    expected_quote_windows = tuple(
        ExpectedQuoteWindow(date.fromisoformat(str(day)), str(clock))
        for day in quote_sessions
        for clock in clocks
    )
    quote_fingerprint = fingerprint(
        [
            {"session_date": item.session_date.isoformat(), "clock": item.clock}
            for item in expected_quote_windows
        ]
    )
    if (
        len(quote_sessions) != 73
        or len(clocks) != 9
        or len(expected_quote_windows) != 657
        or quote_fingerprint != _QUOTE_GRID_FINGERPRINT
    ):
        raise ValueError("Program 002 quote grid fingerprint differs")
    binding = MappingProxyType(
        {
            "kind": "exact-exposed-program-002-v1",
            "plan_sha256": plan.sha256,
            "plan_fingerprint": plan.plan_fingerprint,
            "acquisition_plan_sha256": acquisition.sha256,
            "disposition_sha256": disposition_sha256,
            "disposition_fingerprint": disposition_fingerprint,
            "expected_session_count": len(expected_sessions),
            "expected_session_table_fingerprint": session_fingerprint,
            "expected_quote_window_count": len(expected_quote_windows),
            "expected_quote_grid_fingerprint": quote_fingerprint,
        }
    )
    return expected_sessions, expected_quote_windows, binding


def _verify_disposition(repository: Path) -> tuple[str, str]:
    raw = (repository / _DISPOSITION_PATH).read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    payload = _load_unique_json(raw)
    unsigned = dict(payload)
    disposition_fingerprint = unsigned.pop("disposition_fingerprint", None)
    authority = payload.get("authority")
    reference = payload.get("admission_output_contract")
    if (
        sha256 != _DISPOSITION_SHA256
        or disposition_fingerprint != _DISPOSITION_FINGERPRINT
        or disposition_fingerprint != fingerprint(unsigned)
        or payload.get("status") != "PROPOSED-FROZEN-NOT-ACQUISITION-AUTHORITY"
        or not isinstance(authority, Mapping)
        or not authority
        or any(value is not False for value in authority.values())
        or not isinstance(reference, Mapping)
        or reference.get("reference_implementation")
        != "src/systematic_trading_lab/program_002_missing_data_admission.py"
    ):
        raise ValueError("Program 002 missing-data disposition differs")
    return sha256, str(disposition_fingerprint)


def _expected_session_range(
    start: object, end: object, period_id: str, role: str
) -> tuple[ExpectedSession, ...]:
    first, last = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    points = expected_bar_timestamps(
        datetime.combine(first, time.min, UTC),
        datetime.combine(last, time.max, UTC),
        Timeframe.FIVE_MINUTES,
    )
    by_date: dict[date, list[datetime]] = {}
    for point in points:
        by_date.setdefault(point.astimezone(_NY).date(), []).append(point)
    return tuple(
        ExpectedSession(day, period_id, tuple(values), role)
        for day, values in sorted(by_date.items())
    )


def _session_table_fingerprint(expected: Sequence[ExpectedSession]) -> str:
    return fingerprint(
        [
            {
                "session_date": item.session_date.isoformat(),
                "period_id": item.period_id,
                "role": item.role,
                "expected_bar_opens_utc": [_iso(point) for point in item.expected_bar_opens],
            }
            for item in expected
        ]
    )


def _unique_by_date(values: Sequence[SessionCoverage]) -> dict[date, SessionCoverage]:
    result = {item.session_date: item for item in values}
    if len(result) != len(values):
        raise ValueError("Program 002 session coverage is duplicated")
    return result


def _maximum_contiguous_bars(points: Sequence[datetime]) -> int:
    maximum = current = 0
    previous: datetime | None = None
    for point in points:
        current = (
            current + 1 if previous is not None and point - previous == timedelta(minutes=5) else 1
        )
        maximum = max(maximum, current)
        previous = point
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
    session_rows: Sequence[Mapping[str, Any]], failure_conditions: set[str]
) -> list[dict[str, Any]]:
    periods = sorted(
        {str(row["period_id"]) for row in session_rows if row["scheduled_role"] == "trade"}
    )
    rows: list[dict[str, Any]] = []
    for period_id in periods:
        trade_rows = tuple(
            row
            for row in session_rows
            if row["period_id"] == period_id and row["scheduled_role"] == "trade"
        )
        excluded = tuple(
            str(row["session_date"]) for row in trade_rows if not row["trade_eligible"]
        )
        fraction = Decimal(len(excluded)) / len(trade_rows)
        if (
            len(excluded) > _MAXIMUM_EXCLUDED_SESSIONS_PER_PERIOD
            or fraction > _MAXIMUM_EXCLUDED_SESSION_FRACTION_PER_PERIOD
        ):
            failure_conditions.add(f"period-session-loss-ceiling-exceeded:{period_id}")
        rows.append(
            {
                "period_id": period_id,
                "scheduled_trade_sessions": len(trade_rows),
                "excluded_trade_sessions": list(excluded),
                "excluded_session_fraction": format(fraction, "f"),
            }
        )
    return rows


def _rolling_diagnostics(
    expected: Sequence[ExpectedSession],
    incomplete_dates: set[date],
    missing_dates_by_symbol: Mapping[str, set[date]],
    failure_conditions: set[str],
) -> tuple[int, int]:
    maximum_incomplete = 0
    maximum_same_symbol = 0
    rows = tuple(expected)
    for offset in range(max(0, len(rows) - _ROLLING_SESSION_WINDOW + 1)):
        window = rows[offset : offset + _ROLLING_SESSION_WINDOW]
        count = sum(item.session_date in incomplete_dates for item in window)
        maximum_incomplete = max(maximum_incomplete, count)
        if count > _MAXIMUM_INCOMPLETE_SESSIONS_PER_ROLLING_WINDOW:
            failure_conditions.add("rolling-session-loss-ceiling-exceeded")
        window_dates = {item.session_date for item in window}
        for symbol in PROGRAM_002_SYMBOLS:
            symbol_count = len(window_dates & missing_dates_by_symbol[symbol])
            maximum_same_symbol = max(maximum_same_symbol, symbol_count)
            if symbol_count > _MAXIMUM_INCOMPLETE_SESSIONS_PER_ROLLING_WINDOW:
                failure_conditions.add(f"rolling-symbol-concentration-ceiling-exceeded:{symbol}")
    return maximum_incomplete, maximum_same_symbol


def _quote_diagnostics(
    expected: Sequence[ExpectedQuoteWindow],
    observed: Sequence[QuoteWindowCoverage],
    failure_conditions: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    expected_keys = tuple(sorted(expected))
    if not expected_keys or len(set(expected_keys)) != len(expected_keys):
        raise ValueError("Program 002 expected quote windows are empty or duplicated")
    by_key = {(item.session_date, item.clock): item for item in observed}
    if len(by_key) != len(observed):
        raise ValueError("Program 002 quote coverage is duplicated")
    if set(by_key) - {(item.session_date, item.clock) for item in expected_keys}:
        raise ValueError("Program 002 quote coverage contains an unexpected window")
    rows: list[dict[str, Any]] = []
    totals: Counter[str] = Counter()
    failed_windows = 0
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
                or not 0 <= count <= _QUOTE_GRID_OBSERVATIONS
            ):
                raise ValueError("Program 002 quote coverage count is invalid")
            resolved[symbol] = count
            totals[symbol] += count
        passed = all(count >= _MINIMUM_ELIGIBLE_QUOTE_OBSERVATIONS for count in resolved.values())
        if not passed:
            failed_windows += 1
            failure_conditions.add("quote-calibration-coverage-failed")
        rows.append(
            {
                "session_date": item.session_date.isoformat(),
                "clock": item.clock,
                "eligible_grid_observations_by_symbol": resolved,
                "coverage_passed": passed,
            }
        )
    return rows, {
        "expected_windows": len(expected_keys),
        "failed_windows": failed_windows,
        "eligible_observations_by_symbol": dict(sorted(totals.items())),
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} differs")
    return value


def _load_unique_json(raw: bytes) -> Mapping[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Program 002 disposition contains a duplicate JSON key")
            value[key] = item
        return value

    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, Mapping):
        raise ValueError("Program 002 disposition is invalid")
    return value


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
