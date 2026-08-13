"""Immutable known-exposure inventory and V3 period-selection checks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Literal, cast

from .calendar import expected_bar_timestamps, expected_sessions
from .domain import Timeframe
from .fingerprints import fingerprint

ExposureClass = Literal[
    "real-market-result-observed",
    "real-market-data-acquired-no-result",
    "synthetic-fixture",
    "date-only-reference",
    "unknown-or-external",
]

_EXPOSURE_CLASSES = frozenset(
    (
        "real-market-result-observed",
        "real-market-data-acquired-no-result",
        "synthetic-fixture",
        "date-only-reference",
        "unknown-or-external",
    )
)
_DISQUALIFYING_CLASSES = frozenset(
    ("real-market-result-observed", "real-market-data-acquired-no-result")
)
_NON_DISQUALIFYING_CLASSES = frozenset(("synthetic-fixture", "date-only-reference"))
_PERIOD_ROLES = ("training", "validation-a", "validation-b", "validation-c")


@dataclass(frozen=True)
class ExposureEntry:
    entry_id: str
    source: str
    start: date | None
    end: date | None
    symbols: tuple[str, ...]
    timeframe: str
    classification: ExposureClass
    disqualifies_v3_validation: bool
    evidence_rationale: str


@dataclass(frozen=True)
class ExposureInventory:
    audit_scope: str
    audited_foundation_commit: str
    universal_freshness_limit: str
    entries: tuple[ExposureEntry, ...]
    inventory_fingerprint: str


@dataclass(frozen=True)
class ExposureAssessment:
    status: Literal["accepted", "rejected", "unresolved"]
    overlapping_entry_ids: tuple[str, ...]
    unresolved_entry_ids: tuple[str, ...]


@dataclass(frozen=True)
class IntradayPeriod:
    role: str
    start: date
    end: date
    start_timestamp: datetime
    end_timestamp: datetime
    session_count: int
    per_symbol_bar_opens: int
    two_symbol_bar_opens: int
    selection_rationale: str
    review_status: str
    approved_for_v3_validation: bool
    prospective_freshness_eligible: bool
    exposed_training: bool


@dataclass(frozen=True)
class V3PeriodSelection:
    selection_date: date
    selection_date_is_authoritative: bool
    trusted_cutoff_source: str
    inventory_fingerprint: str
    periods: tuple[IntradayPeriod, ...]
    status: str
    universal_freshness_proven: bool
    prospective_market_data_freshness: bool
    prospective_market_data_freshness_eligible: bool
    freshness_basis: str
    selection_fingerprint: str


def load_intraday_exposure_inventory(path: Path) -> ExposureInventory:
    return parse_intraday_exposure_inventory(json.loads(path.read_text(encoding="utf-8")))


def parse_intraday_exposure_inventory(value: object) -> ExposureInventory:
    required = {
        "schema_version",
        "audit_scope",
        "audited_foundation_commit",
        "universal_freshness_limit",
        "entries",
        "inventory_fingerprint",
    }
    payload = _mapping(value, "exposure inventory")
    if set(payload) != required or payload["schema_version"] != "intraday-known-exposures-v1":
        raise ValueError("intraday exposure inventory fields differ")
    audit_scope = _text(payload["audit_scope"], "audit scope")
    commit = _text(payload["audited_foundation_commit"], "audited foundation commit")
    limit = _text(payload["universal_freshness_limit"], "universal freshness limit")
    if commit != "d03be5eaa1e5d2d360424a6c0d06c1ce0bc6a723":
        raise ValueError("intraday exposure inventory foundation commit differs")
    if "cannot prove universal freshness" not in limit.lower():
        raise ValueError("intraday exposure inventory must state its universal-freshness limit")
    entries_value = payload["entries"]
    if not isinstance(entries_value, list) or not entries_value:
        raise ValueError("intraday exposure inventory entries are required")
    entries = tuple(_parse_entry(item) for item in entries_value)
    if len({entry.entry_id for entry in entries}) != len(entries):
        raise ValueError("intraday exposure entry IDs must be unique")
    unsigned = {key: item for key, item in payload.items() if key != "inventory_fingerprint"}
    claimed = payload["inventory_fingerprint"]
    if not isinstance(claimed, str) or fingerprint(unsigned) != claimed:
        raise ValueError("intraday exposure inventory fingerprint differs")
    return ExposureInventory(audit_scope, commit, limit, entries, claimed)


def assess_validation_exposure(
    inventory: ExposureInventory, start: date, end: date
) -> ExposureAssessment:
    if start > end:
        raise ValueError("validation range is reversed")
    overlaps = tuple(
        entry.entry_id
        for entry in inventory.entries
        if entry.disqualifies_v3_validation
        and entry.start is not None
        and entry.end is not None
        and not (end < entry.start or start > entry.end)
    )
    unresolved = tuple(
        entry.entry_id
        for entry in inventory.entries
        if entry.classification == "unknown-or-external"
    )
    if overlaps:
        return ExposureAssessment("rejected", overlaps, unresolved)
    if unresolved:
        return ExposureAssessment("unresolved", (), unresolved)
    return ExposureAssessment("accepted", (), ())


def load_intraday_v3_period_selection(
    path: Path, inventory: ExposureInventory
) -> V3PeriodSelection:
    value = json.loads(path.read_text(encoding="utf-8"))
    return parse_intraday_v3_period_selection(value, inventory)


def parse_intraday_v3_period_selection(
    value: object, inventory: ExposureInventory
) -> V3PeriodSelection:
    required = {
        "schema_version",
        "selection_date",
        "inventory_fingerprint",
        "freshness_contract",
        "periods",
        "status",
        "selection_fingerprint",
    }
    payload = _mapping(value, "V3 period selection")
    if set(payload) != required or payload["schema_version"] != "intraday-v3-period-selection-v2":
        raise ValueError("V3 period selection fields differ")
    if payload["inventory_fingerprint"] != inventory.inventory_fingerprint:
        raise ValueError("V3 period selection inventory fingerprint differs")
    selection_date = _date(payload["selection_date"], "selection date")
    if selection_date != date(2026, 8, 13):
        raise ValueError("V3 period selection date differs")
    if payload["status"] != "prospective-freshness-eligible-awaiting-pre-bar-main-attestation":
        raise ValueError("V3 period selection status differs")
    freshness = _mapping(payload["freshness_contract"], "V3 freshness contract")
    if freshness != {
        "universal_freshness_proven": False,
        "prospective_market_data_freshness": False,
        "prospective_market_data_freshness_eligible": True,
        "basis": "main-attested-design-before-first-market-bar-v1",
        "selection_date_is_authoritative": False,
        "trusted_cutoff_source": "verified-main-seal-tlog-timestamp",
        "known_dated_overlap_absent": True,
        "immutable_design_required_before_selected_period_data_observation": True,
        "future_data_acquisition_may_change_design": False,
        "trusted_main_attestation_required_before_runtime_sealing": True,
    }:
        raise ValueError("V3 prospective freshness contract differs")
    values = payload["periods"]
    if not isinstance(values, list) or len(values) != len(_PERIOD_ROLES):
        raise ValueError("V3 period selection requires four periods")
    periods = tuple(_parse_period(item, index, inventory) for index, item in enumerate(values))
    for prior, current in zip(periods[:-1], periods[1:], strict=True):
        if prior.end >= current.start or prior.end_timestamp >= current.start_timestamp:
            raise ValueError("V3 selected periods must be chronological and non-overlapping")
    unsigned = {key: item for key, item in payload.items() if key != "selection_fingerprint"}
    claimed = payload["selection_fingerprint"]
    if not isinstance(claimed, str) or fingerprint(unsigned) != claimed:
        raise ValueError("V3 period selection fingerprint differs")
    return V3PeriodSelection(
        selection_date,
        False,
        "verified-main-seal-tlog-timestamp",
        inventory.inventory_fingerprint,
        periods,
        payload["status"],
        False,
        False,
        True,
        "main-attested-design-before-first-market-bar-v1",
        claimed,
    )


def _parse_entry(value: object) -> ExposureEntry:
    required = {
        "id",
        "source",
        "start",
        "end",
        "symbols",
        "timeframe",
        "class",
        "disqualifies_v3_validation",
        "evidence_rationale",
    }
    item = _mapping(value, "intraday exposure entry")
    if set(item) != required:
        raise ValueError("intraday exposure entry fields differ")
    classification = item["class"]
    if not isinstance(classification, str) or classification not in _EXPOSURE_CLASSES:
        raise ValueError("intraday exposure class differs")
    start = _optional_date(item["start"], "intraday exposure start")
    end = _optional_date(item["end"], "intraday exposure end")
    if classification == "unknown-or-external":
        if start is not None or end is not None or item["disqualifies_v3_validation"] is not False:
            raise ValueError("unknown external exposure must remain unresolved")
    elif start is None or end is None or start > end:
        raise ValueError("known intraday exposure requires an ordered date range")
    expected_disqualifies = classification in _DISQUALIFYING_CLASSES
    if classification in _NON_DISQUALIFYING_CLASSES | _DISQUALIFYING_CLASSES and (
        item["disqualifies_v3_validation"] is not expected_disqualifies
    ):
        raise ValueError("intraday exposure disqualification rule differs")
    symbols = item["symbols"]
    if (
        not isinstance(symbols, list)
        or any(not isinstance(symbol, str) or not symbol for symbol in symbols)
        or len(set(symbols)) != len(symbols)
    ):
        raise ValueError("intraday exposure symbols differ")
    return ExposureEntry(
        _text(item["id"], "intraday exposure ID"),
        _text(item["source"], "intraday exposure source"),
        start,
        end,
        tuple(symbols),
        _text(item["timeframe"], "intraday exposure timeframe"),
        cast(ExposureClass, classification),
        cast(bool, item["disqualifies_v3_validation"]),
        _text(item["evidence_rationale"], "intraday exposure rationale"),
    )


def _parse_period(value: object, index: int, inventory: ExposureInventory) -> IntradayPeriod:
    required = {
        "role",
        "start",
        "end",
        "start_timestamp",
        "end_timestamp",
        "symbols",
        "timeframe",
        "session_count",
        "per_symbol_bar_opens",
        "two_symbol_bar_opens",
        "selection_rationale",
        "review_status",
        "approved_for_v3_validation",
        "prospective_freshness_eligible",
        "exposed_training",
    }
    item = _mapping(value, "V3 selected period")
    if set(item) != required or item["role"] != _PERIOD_ROLES[index]:
        raise ValueError("V3 selected period fields or role ordering differ")
    start, end = _date(item["start"], "V3 period start"), _date(item["end"], "V3 period end")
    if start > end or item["symbols"] != ["SPY", "QQQ"] or item["timeframe"] != "5m":
        raise ValueError("V3 selected period contract differs")
    range_start = datetime.combine(start, time.min, UTC)
    range_end = datetime.combine(end, time.max, UTC)
    timestamps = expected_bar_timestamps(range_start, range_end, Timeframe.FIVE_MINUTES)
    if not timestamps:
        raise ValueError("V3 selected period has no XNYS sessions")
    actual = (len(expected_sessions(range_start, range_end)), len(timestamps))
    if (
        _timestamp(item["start_timestamp"]) != timestamps[0]
        or _timestamp(item["end_timestamp"]) != timestamps[-1]
        or item["session_count"] != actual[0]
        or item["per_symbol_bar_opens"] != actual[1]
        or item["two_symbol_bar_opens"] != actual[1] * 2
    ):
        raise ValueError("V3 selected period calendar counts differ")
    validation = index > 0
    if validation:
        if (
            item["review_status"]
            != "prospective-freshness-eligible-awaiting-pre-bar-main-attestation"
            or item["approved_for_v3_validation"] is not False
            or item["prospective_freshness_eligible"] is not True
            or item["exposed_training"] is not False
        ):
            raise ValueError("V3 validation period review status differs")
        assessment = assess_validation_exposure(inventory, start, end)
        if assessment.status == "rejected":
            raise ValueError("V3 validation period overlaps known exposure")
        # Unknown historical or external state remains unresolved, but it cannot
        # contain real bars from a period that had not begun at review time.
        if not assessment.unresolved_entry_ids:
            raise ValueError("V3 selection must retain the universal-freshness limit")
    elif (
        item["review_status"] != "explicitly-exposed-training-only"
        or item["approved_for_v3_validation"] is not False
        or item["prospective_freshness_eligible"] is not False
        or item["exposed_training"] is not True
    ):
        raise ValueError("V3 training period must be explicitly exposed")
    return IntradayPeriod(
        item["role"],
        start,
        end,
        _timestamp(item["start_timestamp"]),
        _timestamp(item["end_timestamp"]),
        actual[0],
        actual[1],
        actual[1] * 2,
        _text(item["selection_rationale"], "V3 period selection rationale"),
        item["review_status"],
        item["approved_for_v3_validation"],
        item["prospective_freshness_eligible"],
        item["exposed_training"],
    )


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be an object")
    return cast(dict[str, object], value)


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} is required")
    return value


def _date(value: object, name: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an ISO date") from error


def _optional_date(value: object, name: str) -> date | None:
    return None if value is None else _date(value, name)


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("V3 selected timestamp must be UTC text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("V3 selected timestamp must be UTC text") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("V3 selected timestamp must be UTC")
    return parsed.astimezone(UTC)
