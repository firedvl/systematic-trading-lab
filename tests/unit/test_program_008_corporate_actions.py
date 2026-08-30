from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from systematic_trading_lab import program_008_corporate_actions as metadata
from systematic_trading_lab.fingerprints import fingerprint

_ROOT = Path(__file__).parents[2]
_ANALYSIS = _ROOT / (
    "config/research/program-007-corporate-action-metadata-offline-forensic-analysis-v1.json"
)
_PROPOSAL = _ROOT / (
    "config/research/program-008-corporate-action-metadata-qualification-proposal-v1.json"
)


def _event_id(index: int) -> str:
    return str(UUID(int=index))


def _cash_dividend(
    *, symbol: str = "SPY", cusip: str | None = "78462F103", event_id: int = 1
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "id": _event_id(event_id),
        "symbol": symbol,
        "rate": 1,
        "special": False,
        "foreign": False,
        "process_date": "2026-01-05",
        "ex_date": "2026-01-02",
        "isin": "",
    }
    if cusip is not None:
        event["cusip"] = cusip
    return event


def _forward_split(
    symbol: str,
    event_id: int,
    *,
    cusip: str | None = None,
    new_rate: int = 2,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "id": _event_id(event_id),
        "symbol": symbol,
        "new_rate": new_rate,
        "old_rate": 1,
        "process_date": "2025-12-05",
        "ex_date": "2025-12-05",
        "isin": "",
    }
    if cusip is not None:
        event["cusip"] = cusip
    return event


def _controls(*, cusips: bool = False) -> list[dict[str, Any]]:
    return [
        _forward_split(
            symbol,
            index,
            cusip=metadata.IDENTITIES[symbol] if cusips else None,
        )
        for index, symbol in enumerate(sorted(metadata.POSITIVE_CONTROLS), 100)
    ]


def _page(groups: dict[str, list[dict[str, Any]]], token: str | None = None) -> bytes:
    return json.dumps(
        {"corporate_actions": groups, "next_page_token": token},
        separators=(",", ":"),
    ).encode()


def test_optional_identifiers_still_require_unambiguous_public_identity() -> None:
    empty = metadata.parse_metadata_page(
        _page({"cash_dividends": [_cash_dividend(cusip="")]})
    ).events[0]
    assert empty.canonical_symbol == "SPY"
    assert empty.canonical_cusip_state == "MISSING"
    assert empty.isin_state == "MISSING"

    with pytest.raises(metadata.Program008MetadataError, match="one ledger identity"):
        metadata.parse_metadata_page(
            _page({"cash_dividends": [_cash_dividend(symbol="QQQ", cusip="")]})
        )
    with pytest.raises(metadata.Program008MetadataError, match="conflicting non-empty CUSIP"):
        metadata.parse_metadata_page(_page({"cash_dividends": [_cash_dividend(cusip="000000000")]}))
    malformed = _cash_dividend(cusip=None)
    malformed["cusip"] = []
    with pytest.raises(metadata.Program008MetadataError, match="cusip is invalid"):
        metadata.parse_metadata_page(_page({"cash_dividends": [malformed]}))


def test_forward_split_accepts_empty_or_expected_cusip_but_rejects_conflict() -> None:
    for cusip, expected_state in (("", "MISSING"), (metadata.IDENTITIES["XLB"], "CORROBORATING")):
        event = metadata.parse_metadata_page(
            _page({"forward_splits": [_forward_split("XLB", 1, cusip=cusip)]})
        ).events[0]
        assert event.canonical_cusip_state == expected_state
        assert event.exact_factor is not None

    with pytest.raises(metadata.Program008MetadataError, match="conflicting non-empty CUSIP"):
        metadata.parse_metadata_page(
            _page({"forward_splits": [_forward_split("XLB", 1, cusip="000000000")]})
        )


def test_duplicate_ids_deduplicate_equal_content_and_reject_conflicts() -> None:
    event = _cash_dividend(cusip=None)
    page = metadata.parse_metadata_page(_page({"cash_dividends": [event, deepcopy(event)]}))
    assert len(page.events) == 1
    assert page.duplicate_id_count == 1

    conflicting = deepcopy(event)
    conflicting["rate"] = 2
    with pytest.raises(metadata.Program008MetadataError, match="content conflicts"):
        metadata.parse_metadata_page(_page({"cash_dividends": [event, conflicting]}))


def test_nonempty_isin_conflict_fails_even_though_isin_is_not_identity() -> None:
    first = _cash_dividend(cusip=None)
    second = deepcopy(first)
    first["isin"] = "US0000000001"
    second["isin"] = "US0000000002"
    with pytest.raises(metadata.Program008MetadataError, match="ISIN metadata conflicts"):
        metadata.parse_metadata_page(_page({"cash_dividends": [first, second]}))


def test_relevant_events_need_dates_terms_and_exact_positive_controls() -> None:
    valid = metadata.parse_metadata_page(_page({"forward_splits": _controls()})).events
    metadata.validate_unit_action_qualification(valid)

    dividend_without_economic_date = _cash_dividend(cusip="")
    dividend_without_economic_date.pop("ex_date")
    relevance_aware = metadata.parse_metadata_page(
        _page(
            {
                "cash_dividends": [dividend_without_economic_date],
                "forward_splits": _controls(),
            }
        )
    ).events
    metadata.validate_unit_action_qualification(relevance_aware)

    missing_date = _controls()
    missing_date[0].pop("ex_date")
    parsed = metadata.parse_metadata_page(_page({"forward_splits": missing_date})).events
    with pytest.raises(metadata.Program008MetadataError, match="usable economic date"):
        metadata.validate_unit_action_qualification(parsed)

    wrong_ratio = _controls()
    wrong_ratio[0]["new_rate"] = 3
    parsed = metadata.parse_metadata_page(_page({"forward_splits": wrong_ratio})).events
    with pytest.raises(metadata.Program008MetadataError, match="positive control failed"):
        metadata.validate_unit_action_qualification(parsed)

    with pytest.raises(metadata.Program008MetadataError, match="positive control failed"):
        metadata.validate_unit_action_qualification(
            metadata.parse_metadata_page(
                _page({"cash_dividends": [_cash_dividend(cusip=None)]})
            ).events
        )

    unexpected = _controls()
    unexpected.append(_forward_split("SPY", 999, cusip=None))
    parsed = metadata.parse_metadata_page(_page({"forward_splits": unexpected})).events
    with pytest.raises(metadata.Program008MetadataError, match="unexpected relevant event"):
        metadata.validate_unit_action_qualification(parsed)


def test_same_identity_name_change_needs_no_invented_economic_date() -> None:
    same_identity = {
        "id": _event_id(50),
        "old_symbol": "SPY",
        "old_cusip": "",
        "new_symbol": "SPY",
        "new_cusip": "",
        "process_date": "2026-01-26",
    }
    parsed = metadata.parse_metadata_page(
        _page({"name_changes": [same_identity], "forward_splits": _controls()})
    ).events
    assert next(event for event in parsed if event.action_type == "name_change").classification == (
        "IDENTITY-METADATA-NO-BREAK"
    )
    metadata.validate_unit_action_qualification(parsed)

    changed_identity = deepcopy(same_identity)
    changed_identity["new_symbol"] = "QQQ"
    parsed = metadata.parse_metadata_page(
        _page({"name_changes": [changed_identity], "forward_splits": _controls()})
    ).events
    with pytest.raises(metadata.Program008MetadataError, match="usable economic date"):
        metadata.validate_unit_action_qualification(parsed)


def test_process_date_pagination_schema_and_size_fail_closed() -> None:
    invalid_date = _cash_dividend(cusip=None)
    invalid_date["process_date"] = "2026-08-30"
    with pytest.raises(metadata.Program008MetadataError, match="outside the query interval"):
        metadata.parse_metadata_page(_page({"cash_dividends": [invalid_date]}))

    assert metadata.parse_metadata_page(_page({}, None)).next_page_token is None
    assert metadata.parse_metadata_page(_page({}, "page-2")).next_page_token == "page-2"
    with pytest.raises(metadata.Program008MetadataError, match="malformed"):
        metadata.parse_metadata_page(_page({}, ""))
    with pytest.raises(metadata.Program008MetadataError, match="unknown event arrays"):
        metadata.parse_metadata_page(_page({"new_provider_type": []}))
    with pytest.raises(metadata.Program008MetadataError, match="byte ceiling"):
        metadata.parse_metadata_page(b" " * (metadata.MAXIMUM_RESPONSE_PAGE_BYTES + 1))


def test_parser_records_provider_order_but_sorts_canonical_events() -> None:
    later = _cash_dividend(symbol="IWM", cusip=None, event_id=1)
    later["process_date"] = "2026-01-06"
    earlier = _cash_dividend(symbol="MDY", cusip=None, event_id=2)
    parsed = metadata.parse_metadata_page(_page({"cash_dividends": [later, earlier]}))
    assert parsed.process_date_ascending_by_type == (("cash_dividend", False),)
    assert [event.process_date.isoformat() for event in parsed.events] == [
        "2026-01-05",
        "2026-01-06",
    ]


def test_fresh_cusip_chain_reconciles_controls_without_symbol_query_replay() -> None:
    exposed = metadata.parse_metadata_page(_page({"forward_splits": _controls()})).events
    fresh = metadata.parse_metadata_page(_page({"forward_splits": _controls(cusips=True)})).events
    result = metadata.reconcile_with_exposed_symbol_response(exposed, fresh)
    assert result.stable_positive_controls == tuple(sorted(metadata.POSITIVE_CONTROLS))
    assert result.overlapping_event_ids == 5

    changed_id = _controls(cusips=True)
    changed_id[0]["id"] = _event_id(999)
    fresh = metadata.parse_metadata_page(_page({"forward_splits": changed_id})).events
    with pytest.raises(metadata.Program008MetadataError, match="event ID changed"):
        metadata.reconcile_with_exposed_symbol_response(exposed, fresh)


def test_public_forensic_analysis_and_successor_proposal_are_bound_and_inert() -> None:
    analysis = json.loads(_ANALYSIS.read_text())
    claimed_analysis = analysis.pop("analysis_fingerprint")
    assert claimed_analysis == fingerprint(analysis)
    assert analysis["status"] == ("OFFLINE-FORENSICS-COMPLETE-PROGRAM-007-REMAINS-TERMINAL-FAIL")
    assert analysis["retained_response"]["byte_count"] == 115628
    assert analysis["retained_response"]["total_event_count"] == 543
    assert analysis["type_inventory"]["cash_dividend"]["record_count"] == 538
    assert analysis["type_inventory"]["cash_dividend"]["cusip_empty_count"] == 189
    assert analysis["type_inventory"]["forward_split"]["record_count"] == 5
    assert analysis["provider_documentation"]["frozen_universal_cusip_rule_classification"] == (
        "QUALIFICATION-SPECIFICATION-DEFECT"
    )
    assert analysis["additional_source_checks"]["deeper_terminal_source_incompatibility"] == (
        "NONE-FOUND"
    )
    assert not any(
        analysis["scope"].get(key)
        for key in (
            "provider_data_requests",
            "credential_presence_checks",
            "credential_value_accesses",
            "ohlcv_requests",
            "strategy_calculations",
        )
    )

    proposal = json.loads(_PROPOSAL.read_text())
    claimed_proposal = proposal.pop("proposal_fingerprint")
    assert claimed_proposal == fingerprint(proposal)
    assert proposal["status"] == metadata.STATUS
    assert proposal["program_id"] == metadata.PROGRAM_ID
    assert proposal["fresh_request"]["identity_parameter"] == "cusips"
    assert proposal["fresh_request"]["identity_count"] == 13
    assert not proposal["fresh_request"]["program_007_symbol_query_replayed"]
    assert proposal["request_budget"]["maximum_requests"] == metadata.MAXIMUM_REQUESTS
    assert proposal["request_budget"]["maximum_responses"] == metadata.MAXIMUM_RESPONSES
    assert proposal["request_budget"]["maximum_accepted_response_bytes_total"] == (
        metadata.MAXIMUM_RESPONSE_BYTES
    )
    assert not any(proposal["authority"].values())
    assert proposal["execution_state"]["authority_id"] is None
    assert proposal["execution_state"]["external_root"] is None
    assert proposal["execution_state"]["credential_names"] == []
    assert (
        proposal["bindings"]["offline_parser"]["sha256"]
        == hashlib.sha256(
            (_ROOT / "src/systematic_trading_lab/program_008_corporate_actions.py").read_bytes()
        ).hexdigest()
    )
