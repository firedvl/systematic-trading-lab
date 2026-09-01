"""Program 012 exposed-prefix raw SIP acquisition and structural admission."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import UTC, date, datetime, time
from decimal import Decimal
from functools import lru_cache
from typing import Any, cast

from . import program_005_alpaca as program_005
from . import program_007_alpaca as raw_contract
from . import program_011_ohlcv as program_011
from .calendar import expected_sessions
from .fingerprints import fingerprint

PROGRAM_ID = "multi-hour-sector-etf-research-011"
PROGRAM_ORDINAL = 12
STATUS = "PROPOSED-NOT-AUTHORIZED"
CONTEXT_START = date(2020, 6, 26)
CONTEXT_END = date(2020, 7, 24)
EXPOSED_START = date(2020, 7, 27)
EXPOSED_END = date(2025, 12, 31)
SYMBOLS = program_011.SYMBOLS
FIXED_QUARANTINE = (
    date(2020, 12, 4),
    date(2021, 2, 3),
    date(2021, 2, 5),
    date(2021, 2, 10),
    date(2021, 2, 22),
)
INCIDENT_INVENTORY_FINGERPRINT = "b725b51b5854a9297f8514c282a15b9729b44a4666de6c09066e5316aef8e9fe"
EXPECTED_SESSION_COUNT = 1_386
EXPECTED_FULL_SESSION_COUNT = 1_374
EXPECTED_EARLY_CLOSE_COUNT = 12
EXPECTED_COORDINATE_COUNT = 1_399_788
MAXIMUM_PAGES_PER_SESSION = 16
MAXIMUM_REQUESTS_AND_RESPONSES = EXPECTED_SESSION_COUNT * MAXIMUM_PAGES_PER_SESSION
MAXIMUM_RESPONSE_PAGE_BYTES = 8 * 1024 * 1024
MAXIMUM_SESSION_RESPONSE_BYTES = 8 * 1024 * 1024
MAXIMUM_TOTAL_RESPONSE_BYTES = 4 * 1024 * 1024 * 1024
WORKING_DISK_RESERVATION_BYTES = 8 * 1024 * 1024 * 1024
MAXIMUM_REQUESTS_PER_MINUTE = 120
REQUEST_TIMEOUT_SECONDS = 30


class Program012Error(ValueError):
    """Fail-closed Program 012 contract or admission error."""


class StructuralAdmissionError(Program012Error):
    """The acquired raw prefix failed the frozen structural gates."""

    def __init__(self, report: Mapping[str, Any]) -> None:
        failures = _strings(report.get("failures"), "admission failures")
        super().__init__("Program 012 structural admission failed: " + ", ".join(failures))
        self.report = report


@lru_cache(maxsize=1)
def acquisition_requests() -> tuple[program_011.SessionRequest, ...]:
    sessions = expected_sessions(
        datetime.combine(CONTEXT_START, time.min, tzinfo=UTC),
        datetime.combine(EXPOSED_END, time.max, tzinfo=UTC),
    )
    requests = tuple(program_011.SessionRequest(session) for session in sessions)
    grid_counts = [len(request.grid) for request in requests]
    if (
        len(requests) != EXPECTED_SESSION_COUNT
        or grid_counts.count(78) != EXPECTED_FULL_SESSION_COUNT
        or grid_counts.count(42) != EXPECTED_EARLY_CLOSE_COUNT
        or sum(grid_counts) * len(SYMBOLS) != EXPECTED_COORDINATE_COUNT
    ):
        raise Program012Error("Program 012 request chronology differs")
    return requests


@lru_cache(maxsize=1)
def full_trade_sessions() -> frozenset[date]:
    return frozenset(
        request.session
        for request in acquisition_requests()
        if request.session >= EXPOSED_START and len(request.grid) == 78
    )


def derive_incident_inventory(
    incident: Mapping[str, Any], program_005_plan: Mapping[str, Any]
) -> tuple[str, ...]:
    completed = _sequence(incident.get("completed_exposed_segments"), "completed segments")
    coordinates = {
        coordinate
        for item in completed
        for coordinate in _strings(
            _mapping(item, "completed segment").get("synthesized_coordinates", ()),
            "synthesized coordinates",
        )
    }
    failed = _mapping(incident.get("failed_segment"), "failed segment")
    coordinates.update(_strings(failed.get("missing_intervals"), "failed missing intervals"))
    inventory = tuple(sorted(coordinates))
    program_005_inventory = _strings(
        _mapping(program_005_plan.get("source_qualification"), "Program 005 qualification").get(
            "known_mdy_coordinates"
        ),
        "Program 005 known coordinates",
    )
    if (
        inventory != program_005_inventory
        or len(inventory) != 9
        or fingerprint(inventory) != INCIDENT_INVENTORY_FINGERPRINT
        or {value.split("@", 1)[0] for value in inventory} != {"MDY"}
        or {date.fromisoformat(value.split("@", 1)[1][:10]) for value in inventory}
        != set(FIXED_QUARANTINE)
    ):
        raise Program012Error("Program 012 incident inventory differs")
    return inventory


def assess_structural_admission(
    proposal: Mapping[str, Any],
    program_005_plan: Mapping[str, Any],
    incident: Mapping[str, Any],
    missing_coordinates: Mapping[date, set[str]],
    morning_metrics: Mapping[date, Mapping[str, tuple[Decimal, Decimal, Decimal]]],
) -> Mapping[str, Any]:
    inventory = derive_incident_inventory(incident, program_005_plan)
    translated = _program_005_admission_plan(proposal, program_005_plan, inventory)
    requests_by_session = {request.session: request for request in acquisition_requests()}
    if any(
        type(session) is not date
        or type(coordinates) is not set
        or any(type(coordinate) is not str for coordinate in coordinates)
        for session, coordinates in missing_coordinates.items()
    ):
        raise Program012Error("Program 012 missing-coordinate inventory is invalid")
    for session, coordinates in missing_coordinates.items():
        request = requests_by_session.get(session)
        if request is None or any(
            not _is_expected_coordinate(coordinate, request) for coordinate in coordinates
        ):
            raise Program012Error("Program 012 missing coordinate is outside the request plan")
    try:
        report = dict(
            program_005.assess_missingness(translated, missing_coordinates, morning_metrics)
        )
    except program_005.Program005Error as error:
        raise Program012Error(str(error).replace("Program 005", "Program 012")) from None

    failures = set(_strings(report.get("failures"), "admission failures"))
    full_sessions = full_trade_sessions()
    for session in missing_coordinates:
        if session > CONTEXT_END and session not in full_sessions:
            failures.add("early-close")
    report.update(
        {
            "schema_version": "program-012-private-structural-admission-report-v1",
            "program_id": PROGRAM_ID,
            "status": (
                "ADMITTED-PROGRAM-012-RAW-STRUCTURAL-PREFIX"
                if not failures
                else "TERMINAL-FAIL-CONSUMED-NO-RETRY"
            ),
            "incident_inventory_fingerprint": INCIDENT_INVENTORY_FINGERPRINT,
            "failures": sorted(failures),
            "admission_passed": not failures,
            "program_002_admission": False,
            "program_002_quote_windows_evaluated": 0,
            "strategy_metrics_present": False,
        }
    )
    unsigned = dict(report)
    unsigned.pop("admission_fingerprint", None)
    report["admission_fingerprint"] = fingerprint(unsigned)
    return report


def collect_morning_metrics(
    rows: Sequence[raw_contract.RawBar],
    output: dict[date, dict[str, tuple[Decimal, Decimal, Decimal]]],
) -> None:
    by_session_symbol: dict[tuple[date, str], list[raw_contract.RawBar]] = defaultdict(list)
    for row in rows:
        if row.symbol in {"SPY", "MDY"}:
            by_session_symbol[(row.timestamp.date(), row.symbol)].append(row)
    for (session, symbol), values in by_session_symbol.items():
        morning = sorted(values, key=lambda value: value.timestamp)[:24]
        expected = program_011.SessionRequest(session).grid[:24]
        if tuple(row.timestamp for row in morning) != expected:
            continue
        opening = morning[0].open
        minimum = min(row.low for row in morning)
        output.setdefault(session, {})[symbol] = (
            abs(morning[-1].close / opening - Decimal(1)),
            (max(row.high for row in morning) - minimum) / minimum,
            sum((row.volume for row in morning), start=Decimal(0)),
        )


def canonical_bar_record(row: raw_contract.RawBar) -> Mapping[str, Any]:
    return {
        "symbol": row.symbol,
        "timestamp": row.timestamp,
        "open": row.open,
        "high": row.high,
        "low": row.low,
        "close": row.close,
        "volume": row.volume,
        "trade_count": row.trade_count,
        "vwap": row.vwap,
    }


def _is_expected_coordinate(coordinate: str, request: program_011.SessionRequest) -> bool:
    symbol, separator, timestamp_value = coordinate.partition("@")
    if separator != "@" or symbol not in SYMBOLS:
        return False
    try:
        timestamp = datetime.fromisoformat(timestamp_value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (
        timestamp.tzinfo is not None
        and timestamp.utcoffset() == UTC.utcoffset(timestamp)
        and timestamp in request.grid
        and timestamp_value == timestamp.isoformat().replace("+00:00", "Z")
    )


def _program_005_admission_plan(
    proposal: Mapping[str, Any],
    program_005_plan: Mapping[str, Any],
    inventory: Sequence[str],
) -> dict[str, Any]:
    """Translate renamed Program 012 fields into the reviewed Program 005 gate implementation."""
    plan = deepcopy(dict(program_005_plan))
    chronology = _dict(plan.get("chronology_and_protected_boundaries"), "Program 005 chronology")
    chronology["exposed_end"] = EXPOSED_END.isoformat()
    qualification = _dict(plan.get("source_qualification"), "Program 005 qualification")
    qualification["known_mdy_coordinates"] = list(inventory)

    source_policy = _mapping(proposal.get("missingness_policy"), "Program 012 missingness policy")
    fixed = _mapping(source_policy.get("fixed_quarantine"), "Program 012 fixed quarantine")
    global_loss = _mapping(source_policy.get("global_loss_limit"), "Program 012 global loss")
    concentration = _mapping(
        source_policy.get("unexpected_concentration_limits"), "Program 012 concentration limits"
    )
    source_clock = _mapping(
        source_policy.get("fixed_clock_concentration"), "Program 012 clock gate"
    )
    source_bias = _mapping(
        source_policy.get("spy_mdy_morning_bias_diagnostic"), "Program 012 morning gate"
    )

    policy = _dict(plan.get("missing_data_policy"), "Program 005 missingness policy")
    policy["policy_id"] = source_policy.get("policy_id")
    target_fixed = _dict(policy.get("pre_exposed_design_quarantine"), "fixed quarantine")
    target_fixed.update(
        {
            "sessions": list(fixed.get("sessions", ())),
            "session_count": fixed.get("session_count"),
            "incident_coordinate_count": fixed.get("known_mdy_coordinate_count"),
        }
    )
    target_loss = _dict(policy.get("global_loss_limit"), "global loss")
    target_loss.update(
        {
            "expected_full_trade_eligible_sessions": global_loss.get(
                "prefix_full_session_population"
            ),
            "overall_excluded_full_session_count_max": global_loss.get(
                "overall_excluded_full_session_count_max"
            ),
            "minimum_retained_full_trade_eligible_sessions": global_loss.get(
                "minimum_retained_full_trade_eligible_sessions"
            ),
            "pre_exposed_design_quarantine_count": global_loss.get("fixed_quarantine_count"),
            "unexpected_excluded_full_session_count_max": global_loss.get(
                "unexpected_excluded_full_session_count_max"
            ),
        }
    )
    limits = _dict(policy.get("concentration_limits"), "concentration limits")
    limits.update(
        {
            "unexpected_exclusions_per_calendar_year_max": concentration.get(
                "per_calendar_year_max"
            ),
            "unexpected_exclusions_per_predeclared_discovery_or_test_block_max": concentration.get(
                "per_structural_block_max"
            ),
            "unexpected_exclusion_rolling_window_sessions": concentration.get(
                "rolling_window_sessions"
            ),
            "unexpected_exclusions_per_rolling_63_expected_sessions_max": concentration.get(
                "per_rolling_63_expected_sessions_max"
            ),
            "maximum_consecutive_total_exclusions": concentration.get(
                "maximum_consecutive_total_exclusions"
            ),
            "same_missing_symbol_rolling_window_sessions": concentration.get(
                "same_missing_symbol_rolling_window_sessions"
            ),
            "required_initial_context_loss_max": source_policy.get("context_loss_max"),
        }
    )
    limits["unexpected_exclusion_adjacent_to_any_quarantined_or_unexpected_exclusion_allowed"] = (
        concentration.get("adjacent_to_any_fixed_or_unexpected_exclusion_allowed")
    )
    limits["unexpected_sessions_with_same_missing_symbol_per_rolling_252_expected_sessions_max"] = (
        concentration.get("same_missing_symbol_per_rolling_252_expected_sessions_max")
    )
    limits[
        "unexpected_exclusion_in_block_or_rolling_63_window_containing_"
        "the_pre_exposed_design_quarantine_allowed"
    ] = concentration.get("in_block_or_rolling_63_window_containing_fixed_quarantine_allowed")
    limits[
        "unexpected_mdy_exclusion_in_rolling_252_window_containing_a_"
        "pre_exposed_mdy_session_allowed"
    ] = concentration.get("unexpected_mdy_in_rolling_252_window_containing_fixed_mdy_allowed")
    fixed_contract = _dict(
        limits.get("pre_exposed_design_quarantine_concentration_contract"),
        "fixed quarantine concentration contract",
    )
    fixed_contract.update(
        {
            "fixed_counts_by_predeclared_discovery_block": dict(
                _mapping(fixed.get("fixed_counts_by_block"), "fixed block counts")
            ),
            "pre_quarantine_full_trade_eligible_sessions_by_discovery_block": dict(
                _mapping(
                    fixed.get("pre_quarantine_full_sessions_by_discovery_block"),
                    "pre-quarantine block counts",
                )
            ),
            "post_quarantine_full_trade_eligible_sessions_by_discovery_block": dict(
                _mapping(
                    fixed.get("post_quarantine_full_sessions_by_discovery_block"),
                    "post-quarantine block counts",
                )
            ),
            "minimum_retained_full_sessions_per_discovery_block": fixed.get(
                "minimum_retained_full_sessions_per_discovery_block"
            ),
            "pre_quarantine_maximum_discovery_block_session_count_difference": fixed.get(
                "maximum_pre_quarantine_discovery_block_imbalance"
            ),
            "post_quarantine_maximum_discovery_block_session_count_difference": fixed.get(
                "maximum_post_quarantine_discovery_block_imbalance"
            ),
            "maximum_consecutive_fixed_quarantine_sessions": fixed.get(
                "maximum_consecutive_fixed_quarantine_sessions"
            ),
            "observed_maximum_consecutive_fixed_quarantine_sessions": 1,
        }
    )
    calendar_gate = _dict(
        fixed_contract.get("calendar_concentration_contract"), "fixed calendar gate"
    )
    calendar_gate.update(
        {
            "affected_months": dict(_mapping(fixed.get("affected_months"), "affected months")),
            "minimum_retained_full_sessions_per_affected_month": fixed.get(
                "minimum_retained_full_sessions_per_affected_month"
            ),
            "affected_complete_calendar_years": dict(
                _mapping(fixed.get("affected_complete_years"), "affected complete years")
            ),
            "minimum_retained_full_sessions_per_affected_complete_calendar_year": fixed.get(
                "minimum_retained_full_sessions_per_affected_complete_year"
            ),
            "affected_partial_calendar_years": {
                year: {
                    "fixed_quarantine_sessions": value.get("fixed_quarantine_sessions"),
                    "governing_fixed_block": value.get("governing_structural_block"),
                }
                for year, value in (
                    (
                        str(year),
                        _mapping(item, "affected partial year"),
                    )
                    for year, item in _mapping(
                        fixed.get("affected_partial_years"), "affected partial years"
                    ).items()
                )
            },
        }
    )
    clock_gate = _dict(fixed_contract.get("clock_concentration_contract"), "fixed clock gate")
    clock_gate.update(
        {
            "missing_coordinate_count": source_clock.get("fixed_missing_coordinates"),
            "regular_session_five_minute_clock_count": source_clock.get(
                "regular_session_five_minute_clocks"
            ),
            "fixed_coordinate_counts_by_new_york_clock": dict(
                _mapping(
                    source_clock.get("fixed_coordinate_counts_by_new_york_clock"),
                    "fixed clock counts",
                )
            ),
            "uniform_coordinate_reference_population": source_clock.get(
                "uniform_coordinate_population"
            ),
            "coordinates_per_clock": source_clock.get("coordinates_per_clock"),
            "bonferroni_clock_test_count": source_clock.get("bonferroni_clock_test_count"),
            "rejection_count_at_one_clock": source_clock.get("rejection_count_at_one_clock"),
            "observed_maximum_coordinates_at_one_clock": source_clock.get(
                "observed_maximum_coordinates_at_one_clock"
            ),
            "fixed_sessions_missing_at_exact_strategy_clocks": dict(
                _mapping(
                    source_clock.get("fixed_sessions_missing_at_exact_strategy_clocks"),
                    "fixed strategy clocks",
                )
            ),
            "maximum_fixed_sessions_missing_at_any_exact_strategy_clock": source_clock.get(
                "maximum_fixed_sessions_missing_at_any_exact_strategy_clock"
            ),
        }
    )
    bias = _dict(policy.get("bias_audit"), "bias audit")
    bias_gate = _dict(bias.get("spy_and_mdy_morning_diagnostics"), "morning gate")
    bias_gate.update(
        {
            "reference_symbols": list(source_bias.get("reference_symbols", ())),
            "finite_population_sessions": source_bias.get("population_full_sessions"),
            "tail_size_sessions": source_bias.get("tail_size_sessions"),
            "rejection_counts_by_total_exclusions": dict(
                _mapping(
                    source_bias.get("rejection_counts_by_total_exclusions"),
                    "morning rejection counts",
                )
            ),
            "per_test_alpha_exact": source_bias.get("per_test_alpha_exact"),
        }
    )
    return plan


def _dict(value: Any, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise Program012Error(f"Program 012 {label} is invalid")
    return cast(dict[str, Any], value)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Program012Error(f"Program 012 {label} is invalid")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise Program012Error(f"Program 012 {label} is invalid")
    return value


def _strings(value: Any, label: str) -> tuple[str, ...]:
    values = _sequence(value, label)
    if any(type(item) is not str or not item for item in values):
        raise Program012Error(f"Program 012 {label} is invalid")
    return cast(tuple[str, ...], tuple(values))
