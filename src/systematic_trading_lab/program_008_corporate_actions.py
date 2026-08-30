"""Offline parser and prospective contract for Program 008 metadata evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any
from uuid import UUID

from . import program_007_corporate_actions as predecessor
from .fingerprints import fingerprint

PROGRAM_ID = "multi-hour-sector-etf-research-007"
STATUS = "PROGRAM-008-PROPOSED-NOT-AUTHORIZED"
PROCESS_START = predecessor.PROCESS_START
PROCESS_END = predecessor.PROCESS_END
COVERAGE_START = predecessor.COVERAGE_START
COVERAGE_END = predecessor.COVERAGE_END
MAXIMUM_RESPONSE_PAGE_BYTES = 1024 * 1024
MAXIMUM_PAGES = 4
MAXIMUM_REQUESTS = 4
MAXIMUM_RESPONSES = 4
MAXIMUM_RESPONSE_BYTES = 4 * 1024 * 1024
AUTOMATIC_RETRIES = 0

IDENTITIES = predecessor.IDENTITIES
POSITIVE_CONTROLS = predecessor.POSITIVE_CONTROLS
_CONTRACTS = {contract.array_name: contract for contract in predecessor._CONTRACTS}
_DATE_FIELDS = predecessor._DATE_FIELDS
_NUMBER_FIELDS = predecessor._NUMBER_FIELDS
_NON_UNIT_TYPES = frozenset({"cash_dividend", "capital_gains_distribution"})

_IDENTITY_PAIRS = (
    ("symbol", "cusip"),
    ("old_symbol", "old_cusip"),
    ("new_symbol", "new_cusip"),
    ("alternate_symbol", "alternate_cusip"),
    ("source_symbol", "source_cusip"),
    ("acquiree_symbol", "acquiree_cusip"),
    ("acquirer_symbol", "acquirer_cusip"),
)


class Program008MetadataError(ValueError):
    """Fail-closed successor metadata-contract error."""


@dataclass(frozen=True)
class SuccessorAction:
    provider_event_id: str
    action_type: str
    canonical_symbol: str
    process_date: date
    economic_date: date | None
    exact_factor: Fraction | None
    classification: str
    canonical_cusip_state: str
    isin_state: str
    nonempty_cusips: tuple[str, ...]
    nonempty_isins: tuple[str, ...]
    core_fingerprint: str

    @property
    def sort_key(self) -> tuple[date, str, str]:
        return self.process_date, self.action_type, self.provider_event_id


@dataclass(frozen=True)
class ParsedPage:
    events: tuple[SuccessorAction, ...]
    next_page_token: str | None
    duplicate_id_count: int
    process_date_ascending_by_type: tuple[tuple[str, bool], ...]


@dataclass(frozen=True)
class ParsedChain:
    events: tuple[SuccessorAction, ...]
    page_count: int
    response_bytes: int
    duplicate_id_count: int


@dataclass(frozen=True)
class ReconciliationResult:
    overlapping_event_ids: int
    stable_positive_controls: tuple[str, ...]
    exposed_only_events: int
    fresh_only_events: int


def parse_metadata_page(body: bytes) -> ParsedPage:
    """Parse one retained or synthetic page without using credentials or transport."""
    if type(body) is not bytes:
        raise Program008MetadataError("Program 008 metadata response must be bytes")
    if len(body) > MAXIMUM_RESPONSE_PAGE_BYTES:
        raise Program008MetadataError("Program 008 metadata response exceeds the byte ceiling")
    try:
        payload = json.loads(body, parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Program008MetadataError("Program 008 metadata response is not valid JSON") from error
    if type(payload) is not dict or set(payload) != {"corporate_actions", "next_page_token"}:
        raise Program008MetadataError("Program 008 metadata response schema differs")
    next_token = payload["next_page_token"]
    if next_token is not None and (not isinstance(next_token, str) or not next_token):
        raise Program008MetadataError("Program 008 metadata next_page_token is malformed")
    grouped = _mapping(payload["corporate_actions"], "corporate_actions")
    unknown = set(grouped) - set(_CONTRACTS)
    if unknown:
        raise Program008MetadataError(
            f"Program 008 metadata has unknown event arrays: {sorted(unknown)}"
        )

    by_id: dict[str, SuccessorAction] = {}
    duplicate_count = 0
    ordering: list[tuple[str, bool]] = []
    row_count = 0
    for array_name, raw_rows in grouped.items():
        contract = _CONTRACTS[array_name]
        process_dates: list[date] = []
        for raw_row in _sequence(raw_rows, array_name):
            row_count += 1
            if row_count > 1000:
                raise Program008MetadataError("Program 008 metadata page exceeds 1000 events")
            action = _normalize_event(contract, _mapping(raw_row, contract.event_type))
            process_dates.append(action.process_date)
            existing = by_id.get(action.provider_event_id)
            if existing is None:
                by_id[action.provider_event_id] = action
                continue
            _require_compatible_duplicate(existing, action)
            duplicate_count += 1
        ordering.append(
            (
                contract.event_type,
                all(
                    left <= right
                    for left, right in zip(process_dates, process_dates[1:], strict=False)
                ),
            )
        )
    return ParsedPage(
        tuple(sorted(by_id.values(), key=lambda action: action.sort_key)),
        next_token,
        duplicate_count,
        tuple(sorted(ordering)),
    )


def parse_metadata_chain(bodies: Sequence[bytes]) -> ParsedChain:
    """Parse a complete offline response chain and enforce its pagination budget."""
    if not isinstance(bodies, list | tuple) or not bodies:
        raise Program008MetadataError("Program 008 metadata chain must contain response pages")
    if len(bodies) > MAXIMUM_PAGES:
        raise Program008MetadataError("Program 008 metadata chain exceeds the page ceiling")

    response_bytes = 0
    duplicate_count = 0
    seen_tokens: set[str] = set()
    by_id: dict[str, SuccessorAction] = {}
    for index, body in enumerate(bodies):
        if type(body) is not bytes:
            raise Program008MetadataError("Program 008 metadata response must be bytes")
        response_bytes += len(body)
        if response_bytes > MAXIMUM_RESPONSE_BYTES:
            raise Program008MetadataError("Program 008 metadata chain exceeds the byte ceiling")
        page = parse_metadata_page(body)
        duplicate_count += page.duplicate_id_count
        token = page.next_page_token
        if token is not None:
            if token in seen_tokens:
                raise Program008MetadataError("Program 008 metadata pagination token repeated")
            seen_tokens.add(token)
        if index < len(bodies) - 1 and token is None:
            raise Program008MetadataError(
                "Program 008 metadata pagination ended before the last page"
            )
        if index == len(bodies) - 1 and token is not None:
            raise Program008MetadataError("Program 008 metadata pagination did not end")
        for action in page.events:
            existing = by_id.get(action.provider_event_id)
            if existing is None:
                by_id[action.provider_event_id] = action
                continue
            _require_compatible_duplicate(existing, action)
            duplicate_count += 1
    return ParsedChain(
        events=tuple(sorted(by_id.values(), key=lambda action: action.sort_key)),
        page_count=len(bodies),
        response_bytes=response_bytes,
        duplicate_id_count=duplicate_count,
    )


def validate_unit_action_qualification(events: Sequence[SuccessorAction]) -> None:
    """Require the five ledger controls and reject any other in-scope relevant event."""
    if not isinstance(events, Sequence) or any(
        type(event) is not SuccessorAction for event in events
    ):
        raise Program008MetadataError("Program 008 metadata events are invalid")
    controls: dict[str, list[SuccessorAction]] = {symbol: [] for symbol in POSITIVE_CONTROLS}
    for action in events:
        if action.classification in {"NON-UNIT-METADATA", "IDENTITY-METADATA-NO-BREAK"}:
            continue
        if action.economic_date is None:
            raise Program008MetadataError(
                f"Program 008 {action.action_type} lacks a usable economic date"
            )
        if not COVERAGE_START <= action.economic_date <= COVERAGE_END:
            continue
        if action.canonical_symbol in controls:
            controls[action.canonical_symbol].append(action)
            continue
        raise Program008MetadataError(
            f"Program 008 has an unexpected relevant event for {action.canonical_symbol}"
        )

    for symbol, matches in controls.items():
        if (
            len(matches) != 1
            or matches[0].action_type != "forward_split"
            or matches[0].economic_date != date(2025, 12, 5)
            or matches[0].exact_factor != Fraction(2, 1)
        ):
            raise Program008MetadataError(f"Program 008 positive control failed for {symbol}")


def reconcile_with_exposed_symbol_response(
    exposed_events: Sequence[SuccessorAction],
    fresh_cusip_events: Sequence[SuccessorAction],
) -> ReconciliationResult:
    """Compare fresh CUSIP evidence to the exposed symbol baseline without requiring replay."""
    validate_unit_action_qualification(exposed_events)
    validate_unit_action_qualification(fresh_cusip_events)
    exposed = _events_by_id(exposed_events)
    fresh = _events_by_id(fresh_cusip_events)
    for event_id in exposed.keys() & fresh.keys():
        _require_compatible_duplicate(exposed[event_id], fresh[event_id])

    stable_controls: list[str] = []
    for symbol in sorted(POSITIVE_CONTROLS):
        exposed_control = _positive_control_for(exposed_events, symbol)
        fresh_control = _positive_control_for(fresh_cusip_events, symbol)
        if exposed_control.provider_event_id != fresh_control.provider_event_id:
            raise Program008MetadataError(
                f"Program 008 provider event ID changed across filters for {symbol}"
            )
        _require_compatible_duplicate(exposed_control, fresh_control)
        stable_controls.append(symbol)
    return ReconciliationResult(
        overlapping_event_ids=len(exposed.keys() & fresh.keys()),
        stable_positive_controls=tuple(stable_controls),
        exposed_only_events=len(exposed.keys() - fresh.keys()),
        fresh_only_events=len(fresh.keys() - exposed.keys()),
    )


def _normalize_event(
    contract: predecessor.EventContract, event: Mapping[str, Any]
) -> SuccessorAction:
    keys = set(event)
    required = {
        key
        for key in contract.required
        if not _is_optional_identifier(key) and key != contract.effective_field
    }
    if not required <= keys <= contract.allowed:
        raise Program008MetadataError(f"Program 008 {contract.event_type} schema differs")
    event_id = _uuid(event.get("id"))
    dates: dict[str, date] = {}
    numbers: dict[str, Decimal] = {}
    for key, value in event.items():
        if key in _DATE_FIELDS:
            if (value is None or value == "") and key != "process_date":
                continue
            dates[key] = _date(value, key)
        elif key in _NUMBER_FIELDS:
            if (value is None or value == "") and key not in required:
                continue
            numbers[key] = _decimal(value, key)
        elif key in {"special", "foreign"}:
            if type(value) is not bool:
                raise Program008MetadataError(f"Program 008 {key} is invalid")
        elif key == "stock_movements":
            _validate_stock_movements(value)
        elif _is_optional_identifier(key):
            if value is not None and value != "" and not isinstance(value, str):
                raise Program008MetadataError(f"Program 008 {key} is invalid")
        elif key != "id" and not isinstance(value, str):
            raise Program008MetadataError(f"Program 008 {key} is invalid")
    for key in required:
        if key in _DATE_FIELDS and key not in dates:
            raise Program008MetadataError(f"Program 008 required {key} is empty")
        if key in _NUMBER_FIELDS and key not in numbers:
            raise Program008MetadataError(f"Program 008 required {key} is empty")
        if key not in _DATE_FIELDS | _NUMBER_FIELDS | {"id", "special", "foreign"} and (
            not isinstance(event[key], str) or not event[key]
        ):
            raise Program008MetadataError(f"Program 008 required {key} is empty")
    if event.get("sub_type") not in (None, "", "interest", "return_of_capital"):
        raise Program008MetadataError("Program 008 cash-dividend subtype is invalid")
    if event.get("lottery_type") not in (None, "", "original", "supplemental"):
        raise Program008MetadataError("Program 008 partial-call lottery type is invalid")
    if (
        contract.event_type == "capital_gains_distribution"
        and not {
            "long_term_rate",
            "short_term_rate",
        }
        & numbers.keys()
    ):
        raise Program008MetadataError("Program 008 capital-gains rates are missing")

    process_date = dates["process_date"]
    if not PROCESS_START <= process_date <= PROCESS_END:
        raise Program008MetadataError("Program 008 process date is outside the query interval")
    canonical_symbol, cusip_state, cusips, isins = _canonical_identity(event)
    exact_factor = None
    if contract.event_type in {"forward_split", "reverse_split"}:
        old_rate = _positive_fraction(numbers["old_rate"], "old_rate")
        new_rate = _positive_fraction(numbers["new_rate"], "new_rate")
        exact_factor = new_rate / old_rate

    classification = "RELEVANT-ACTION"
    if contract.event_type in _NON_UNIT_TYPES:
        classification = "NON-UNIT-METADATA"
    elif contract.event_type == "name_change" and _same_identity_name_change(event):
        classification = "IDENTITY-METADATA-NO-BREAK"
    core = {
        key: value
        for key, value in event.items()
        if key != "id" and not _is_optional_identifier(key)
    }
    return SuccessorAction(
        provider_event_id=event_id,
        action_type=contract.event_type,
        canonical_symbol=canonical_symbol,
        process_date=process_date,
        economic_date=dates.get(contract.effective_field) if contract.effective_field else None,
        exact_factor=exact_factor,
        classification=classification,
        canonical_cusip_state=cusip_state,
        isin_state="NONEMPTY" if isins else "MISSING",
        nonempty_cusips=cusips,
        nonempty_isins=isins,
        core_fingerprint=fingerprint(
            {
                "provider": "alpaca",
                "action_type": contract.event_type,
                "canonical_symbol": canonical_symbol,
                "event": core,
            }
        ),
    )


def _canonical_identity(
    event: Mapping[str, Any],
) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    symbols = {
        value
        for key, value in event.items()
        if (key == "symbol" or key.endswith("_symbol")) and isinstance(value, str) and value
    }
    cusips = {
        value
        for key, value in event.items()
        if (key == "cusip" or key.endswith("_cusip")) and isinstance(value, str) and value
    }
    isins = {
        value
        for key, value in event.items()
        if (key == "isin" or key.endswith("_isin")) and isinstance(value, str) and value
    }
    movements = event.get("stock_movements")
    if isinstance(movements, list):
        for raw in movements:
            movement = _mapping(raw, "reorganization stock movement")
            symbols.add(_nonempty_string(movement.get("symbol"), "movement symbol"))
            if isinstance(movement.get("cusip"), str) and movement["cusip"]:
                cusips.add(movement["cusip"])
            if isinstance(movement.get("isin"), str) and movement["isin"]:
                isins.add(movement["isin"])

    if len(isins) > 1:
        raise Program008MetadataError("Program 008 event has conflicting non-empty ISIN values")

    by_cusip = {cusip: symbol for symbol, cusip in IDENTITIES.items()}
    targets = {symbol for symbol in symbols if symbol in IDENTITIES}
    targets.update(by_cusip[cusip] for cusip in cusips if cusip in by_cusip)
    if len(targets) != 1:
        raise Program008MetadataError("Program 008 event does not map to one ledger identity")
    canonical_symbol = next(iter(targets))
    for symbol_key, cusip_key in _identity_pairs(event):
        symbol, cusip = event.get(symbol_key), event.get(cusip_key)
        if not isinstance(cusip, str) or not cusip:
            continue
        if isinstance(symbol, str) and symbol in IDENTITIES and cusip != IDENTITIES[symbol]:
            raise Program008MetadataError("Program 008 has a conflicting non-empty CUSIP")
        if cusip in by_cusip and isinstance(symbol, str) and symbol and by_cusip[cusip] != symbol:
            raise Program008MetadataError("Program 008 has a conflicting symbol/CUSIP pair")
    expected = IDENTITIES[canonical_symbol]
    return (
        canonical_symbol,
        "CORROBORATING" if expected in cusips else "MISSING",
        tuple(sorted(cusips)),
        tuple(sorted(isins)),
    )


def _identity_pairs(event: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    pairs = list(_IDENTITY_PAIRS)
    if "old_cusip" in event:
        pairs.append(("symbol", "old_cusip"))
    if "new_cusip" in event:
        pairs.append(("symbol", "new_cusip"))
    return tuple(pairs)


def _same_identity_name_change(event: Mapping[str, Any]) -> bool:
    if event.get("old_symbol") != event.get("new_symbol"):
        return False
    symbol = event.get("old_symbol")
    if not isinstance(symbol, str) or symbol not in IDENTITIES:
        return False
    expected = IDENTITIES[symbol]
    return all(event.get(key) in (None, "", expected) for key in ("old_cusip", "new_cusip"))


def _require_compatible_duplicate(left: SuccessorAction, right: SuccessorAction) -> None:
    if left.core_fingerprint != right.core_fingerprint:
        raise Program008MetadataError("Program 008 duplicate event content conflicts")
    if (
        left.nonempty_cusips
        and right.nonempty_cusips
        and left.nonempty_cusips != right.nonempty_cusips
    ):
        raise Program008MetadataError("Program 008 duplicate CUSIP metadata conflicts")
    if left.nonempty_isins and right.nonempty_isins and left.nonempty_isins != right.nonempty_isins:
        raise Program008MetadataError("Program 008 duplicate ISIN metadata conflicts")


def _events_by_id(events: Sequence[SuccessorAction]) -> dict[str, SuccessorAction]:
    result: dict[str, SuccessorAction] = {}
    for event in events:
        existing = result.get(event.provider_event_id)
        if existing is not None:
            _require_compatible_duplicate(existing, event)
        result[event.provider_event_id] = event
    return result


def _positive_control_for(events: Sequence[SuccessorAction], symbol: str) -> SuccessorAction:
    matches = [
        event
        for event in events
        if event.canonical_symbol == symbol
        and event.action_type == "forward_split"
        and event.economic_date == date(2025, 12, 5)
        and event.exact_factor == Fraction(2, 1)
    ]
    if len(matches) != 1:
        raise Program008MetadataError(f"Program 008 positive control failed for {symbol}")
    return matches[0]


def _validate_stock_movements(value: Any) -> None:
    for raw in _sequence(value, "reorganization stock movements"):
        movement = _mapping(raw, "reorganization stock movement")
        required = {"symbol", "new_rate", "source_rate"}
        if not required <= set(movement) <= required | {"cusip", "isin"}:
            raise Program008MetadataError("Program 008 stock-movement schema differs")
        _nonempty_string(movement["symbol"], "movement symbol")
        for key in ("cusip", "isin"):
            if (
                movement.get(key) is not None
                and movement.get(key) != ""
                and not isinstance(movement[key], str)
            ):
                raise Program008MetadataError(f"Program 008 movement {key} is invalid")
        _positive_fraction(_decimal(movement["new_rate"], "movement new_rate"), "new_rate")
        _positive_fraction(_decimal(movement["source_rate"], "movement source_rate"), "source_rate")


def _is_optional_identifier(key: str) -> bool:
    return key in {"cusip", "isin"} or key.endswith("_cusip") or key.endswith("_isin")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise Program008MetadataError(f"Program 008 {label} must be an object")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, list | tuple):
        raise Program008MetadataError(f"Program 008 {label} must be an array")
    return value


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise Program008MetadataError(f"Program 008 {label} must be a non-empty string")
    return value


def _uuid(value: Any) -> str:
    raw = _nonempty_string(value, "event ID")
    try:
        parsed = UUID(raw)
    except ValueError as error:
        raise Program008MetadataError("Program 008 event ID is not a UUID") from error
    if str(parsed) != raw:
        raise Program008MetadataError("Program 008 event ID is not canonical")
    return raw


def _date(value: Any, label: str) -> date:
    if not isinstance(value, str):
        raise Program008MetadataError(f"Program 008 {label} must be a date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise Program008MetadataError(f"Program 008 {label} must be YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise Program008MetadataError(f"Program 008 {label} must be canonical")
    return parsed


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | Decimal):
        raise Program008MetadataError(f"Program 008 {label} must be an exact number")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise Program008MetadataError(f"Program 008 {label} is invalid") from error
    if not parsed.is_finite():
        raise Program008MetadataError(f"Program 008 {label} must be finite")
    return parsed


def _positive_fraction(value: Decimal, label: str) -> Fraction:
    if value <= 0:
        raise Program008MetadataError(f"Program 008 {label} must be positive")
    return Fraction(value)
