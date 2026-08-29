from __future__ import annotations

import hashlib
import importlib.util
import inspect
import io
import json
import os
from copy import deepcopy
from email.message import Message
from fractions import Fraction
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request
from uuid import UUID

import pytest

import systematic_trading_lab.program_007_corporate_actions as metadata
from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_LEDGER_PATH = _REPOSITORY / "config/research/program-007-unit-changing-action-ledger-v3.json"
_LEDGER_SHA256 = "e405529489921a0ec8883aa64e855e6600a99105387cbc9ed2766c82bc0826b1"
_EVIDENCE_PATH = (
    _REPOSITORY
    / "config/research/program-007-alpaca-corporate-actions-public-contract-evidence-v1.json"
)
_PLAN_V2_PATH = (
    _REPOSITORY / "config/research/program-007-corporate-action-metadata-source-plan-v2.json"
)
_PLAN_PATH = (
    _REPOSITORY / "config/research/program-007-corporate-action-metadata-source-plan-v3.json"
)


def _id(value: int) -> str:
    return str(UUID(int=value))


def _event(array_name: str, event_id: int = 1) -> dict[str, Any]:
    common: dict[str, Any] = {"id": _id(event_id), "process_date": "2025-11-01"}
    events: dict[str, dict[str, Any]] = {
        "forward_splits": {
            **common,
            "symbol": "SPY",
            "cusip": metadata.IDENTITIES["SPY"],
            "old_rate": 1,
            "new_rate": 2,
            "ex_date": "2025-12-05",
        },
        "reverse_splits": {
            **common,
            "symbol": "SPY",
            "old_cusip": metadata.IDENTITIES["SPY"],
            "new_cusip": metadata.IDENTITIES["SPY"],
            "old_rate": 5,
            "new_rate": 1,
            "ex_date": "2025-12-05",
        },
        "unit_splits": {
            **common,
            "old_symbol": "SPY",
            "old_cusip": metadata.IDENTITIES["SPY"],
            "old_rate": 1,
            "new_symbol": "SPY.NEW",
            "new_cusip": "000000001",
            "new_rate": 1,
            "alternate_symbol": "SPY.RT",
            "alternate_cusip": "000000002",
            "alternate_rate": 1,
            "effective_date": "2025-12-05",
        },
        "cash_dividends": {
            **common,
            "symbol": "XLF",
            "cusip": metadata.IDENTITIES["XLF"],
            "rate": 0.25,
            "special": False,
            "foreign": False,
            "ex_date": "2025-12-05",
        },
        "stock_dividends": {
            **common,
            "symbol": "SPY",
            "cusip": metadata.IDENTITIES["SPY"],
            "rate": 0.1,
            "ex_date": "2025-12-05",
        },
        "spin_offs": {
            **common,
            "source_symbol": "SPY",
            "source_cusip": metadata.IDENTITIES["SPY"],
            "source_rate": 1,
            "new_symbol": "NEW",
            "new_cusip": "000000003",
            "new_rate": 0.25,
            "ex_date": "2025-12-05",
        },
        "cash_mergers": {
            **common,
            "acquiree_symbol": "SPY",
            "acquiree_cusip": metadata.IDENTITIES["SPY"],
            "rate": 500,
            "effective_date": "2025-12-05",
        },
        "stock_mergers": {
            **common,
            "acquirer_symbol": "NEW",
            "acquirer_cusip": "000000004",
            "acquirer_rate": 2,
            "acquiree_symbol": "SPY",
            "acquiree_cusip": metadata.IDENTITIES["SPY"],
            "acquiree_rate": 1,
            "effective_date": "2025-12-05",
        },
        "stock_and_cash_mergers": {
            **common,
            "acquirer_symbol": "NEW",
            "acquirer_cusip": "000000004",
            "acquirer_rate": 2,
            "acquiree_symbol": "SPY",
            "acquiree_cusip": metadata.IDENTITIES["SPY"],
            "acquiree_rate": 1,
            "cash_rate": 5,
            "effective_date": "2025-12-05",
        },
        "redemptions": {
            **common,
            "symbol": "SPY",
            "cusip": metadata.IDENTITIES["SPY"],
            "rate": 500,
        },
        "name_changes": {
            **common,
            "old_symbol": "SPY",
            "old_cusip": metadata.IDENTITIES["SPY"],
            "new_symbol": "SPY.NEW",
            "new_cusip": "000000005",
        },
        "worthless_removals": {
            **common,
            "symbol": "SPY",
            "cusip": metadata.IDENTITIES["SPY"],
        },
        "rights_distributions": {
            **common,
            "source_symbol": "SPY",
            "source_cusip": metadata.IDENTITIES["SPY"],
            "new_symbol": "SPY.RT",
            "new_cusip": "000000006",
            "rate": 1,
            "ex_date": "2025-12-05",
            "payable_date": "2025-12-10",
        },
        "partial_calls": {**common, "symbol": "SPY"},
        "reorganizations": {
            **common,
            "symbol": "SPY",
            "cusip": metadata.IDENTITIES["SPY"],
            "effective_date": "2025-12-05",
            "stock_movements": [
                {
                    "symbol": "NEW",
                    "cusip": "000000007",
                    "source_rate": 1,
                    "new_rate": 1,
                }
            ],
        },
        "capital_gains_distributions": {
            **common,
            "symbol": "SPY",
            "cusip": metadata.IDENTITIES["SPY"],
            "ex_date": "2025-12-05",
            "long_term_rate": 1.25,
        },
    }
    return deepcopy(events[array_name])


def _body(
    groups: dict[str, list[dict[str, Any]]] | None = None,
    next_page: str | None = None,
) -> bytes:
    return json.dumps(
        {"corporate_actions": groups or {}, "next_page_token": next_page},
        separators=(",", ":"),
    ).encode()


def _source(*bodies: bytes) -> metadata.SyntheticMetadataSource:
    return metadata.SyntheticMetadataSource([metadata.RawResponse(200, body) for body in bodies])


def _execute_same(groups: dict[str, list[dict[str, Any]]]) -> metadata.MetadataQualificationResult:
    body = _body(groups)
    return metadata.execute_synthetic_metadata(_source(body, body))


def _ledger() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_LEDGER_PATH.read_text(encoding="utf-8")))


def _evidence_payloads(source: metadata.SyntheticMetadataSource) -> dict[str, bytes]:
    descriptor = source._evidence.fileno()
    raw = os.pread(descriptor, os.fstat(descriptor).st_size, 0)
    payloads: dict[str, bytes] = {}
    offset = 0
    while offset < len(raw):
        header_size = int.from_bytes(raw[offset : offset + 8], "big")
        offset += 8
        header = json.loads(raw[offset : offset + header_size])
        offset += header_size
        payload_size = int.from_bytes(raw[offset : offset + 8], "big")
        offset += 8
        payload = raw[offset : offset + payload_size]
        offset += payload_size
        assert len(payload) == header["payload_bytes"]
        assert hashlib.sha256(payload).hexdigest() == header["payload_sha256"]
        payloads[header["key"]] = payload
    return payloads


def test_frozen_contract_has_two_deterministic_all_type_identity_chains() -> None:
    chains = metadata.frozen_request_chains()

    assert [chain.chain_id for chain in chains] == ["symbols", "cusips"]
    assert metadata.EVENT_TYPES == (
        "forward_split",
        "reverse_split",
        "unit_split",
        "cash_dividend",
        "stock_dividend",
        "spin_off",
        "cash_merger",
        "stock_merger",
        "stock_and_cash_merger",
        "redemption",
        "name_change",
        "worthless_removal",
        "rights_distribution",
        "partial_call",
        "reorganization",
        "capital_gains_distribution",
    )
    for chain in chains:
        query = parse_qs(urlparse(chain.url()).query)
        assert query[chain.identity_parameter] == [",".join(chain.identities)]
        assert query == {
            chain.identity_parameter: [",".join(chain.identities)],
            "region": ["us"],
            "start": ["1990-01-01"],
            "end": ["2026-08-29"],
            "limit": ["1000"],
            "data_quality": ["complete"],
            "sort": ["asc"],
        }
        assert "types" not in query
        assert chain.url() == chain.url()


def test_prospective_plan_binds_the_offline_contract_and_grants_no_authority() -> None:
    plan = cast(dict[str, Any], json.loads(_PLAN_PATH.read_text(encoding="utf-8")))
    unsigned = dict(plan)
    stored_fingerprint = unsigned.pop("proposal_fingerprint")
    evidence = cast(dict[str, Any], json.loads(_EVIDENCE_PATH.read_text(encoding="utf-8")))
    unsigned_evidence = dict(evidence)
    evidence_fingerprint = unsigned_evidence.pop("evidence_fingerprint")

    assert stored_fingerprint == fingerprint(unsigned)
    assert evidence_fingerprint == fingerprint(unsigned_evidence)
    assert hashlib.sha256(_PLAN_V2_PATH.read_bytes()).hexdigest() == plan["supersedes"]["sha256"]
    assert plan["supersedes"]["fingerprint"] == (
        "add9b3bf1cfe3b81cae4d1e856fb99b6e27bf16133173e76e725303a9e054ead"
    )
    evidence_binding = plan["documentation"]["evidence_binding"]
    assert hashlib.sha256(_EVIDENCE_PATH.read_bytes()).hexdigest() == evidence_binding["sha256"]
    assert evidence_fingerprint == evidence_binding["fingerprint"]
    assert evidence["source"]["sha256"] == evidence_binding["provider_response_sha256"]
    assert evidence["source"]["byte_count"] == evidence_binding["provider_response_bytes"]
    excerpt = evidence["contract_claims"]["creation_lag"]["minimal_exact_excerpt"]
    assert (
        hashlib.sha256(excerpt.encode()).hexdigest()
        == (evidence["contract_claims"]["creation_lag"]["excerpt_sha256"])
    )
    assert evidence["retrieval_boundary"]["data_endpoint_requests"] == 0
    assert all(value is False for value in evidence["authority"].values())
    assert plan["status"] == "PROPOSED-NOT-AUTHORIZED-FOR-PROVIDER-REQUESTS"
    assert plan["endpoint_contract"]["url"] == metadata.ENDPOINT
    assert plan["universe"]["cusips_by_symbol"] == metadata.IDENTITIES
    assert set(plan["event_inventory"]) == set(metadata.EVENT_TYPES)
    assert plan["transport_budget"] == {
        "logical_chain_count": 2,
        "minimum_expected_http_requests": 2,
        "minimum_expected_http_responses": 2,
        "maximum_pages_per_chain": metadata.MAXIMUM_PAGES_PER_CHAIN,
        "maximum_http_requests": metadata.MAXIMUM_HTTP_REQUESTS,
        "maximum_http_responses": metadata.MAXIMUM_HTTP_RESPONSES,
        "maximum_response_page_bytes": metadata.MAXIMUM_RESPONSE_PAGE_BYTES,
        "maximum_downloaded_bytes": metadata.MAXIMUM_DOWNLOADED_BYTES,
        "maximum_credential_loads": 1,
        "automatic_transport_retries": metadata.AUTOMATIC_TRANSPORT_RETRIES,
    }
    assert all(value is False for value in plan["authority"].values())
    assert plan["universe"]["identity_history_status"] == metadata.IDENTITY_HISTORY_STATUS
    assert (
        plan["query_contract"]["process_window"]["source_finality_status"]
        == metadata.SOURCE_FINALITY_STATUS
    )
    assert plan["exact_next_authorization"].startswith("Not authorized.")
    assert plan["state_at_proposal"]["program_007_provider_requests"] == 0
    assert plan["state_at_proposal"]["strategy_returns"] == 0
    assert plan["unchanged_ohlcv_sample"] == {
        "sessions": [
            "2021-07-08",
            "2022-01-25",
            "2022-11-15",
            "2023-05-16..2023-05-30",
            "2025-11-28",
            "2025-12-15",
        ],
        "expected_canonical_coordinates": 14742,
        "changed": False,
        "accessed": False,
    }
    assert hashlib.sha256(_LEDGER_PATH.read_bytes()).hexdigest() == _LEDGER_SHA256


@pytest.mark.parametrize(
    ("array_name", "event_type", "effective_field", "classification"),
    [
        ("forward_splits", "forward_split", "ex_date", "DETERMINISTIC-TRANSFORMABLE"),
        ("reverse_splits", "reverse_split", "ex_date", "DETERMINISTIC-TRANSFORMABLE"),
        (
            "unit_splits",
            "unit_split",
            "effective_date",
            "NONTRANSFORMABLE-REQUIRES-SESSION-OR-WINDOW-EXCLUSION",
        ),
        ("cash_dividends", "cash_dividend", "ex_date", "NON-UNIT-METADATA"),
        (
            "stock_dividends",
            "stock_dividend",
            "ex_date",
            "NONTRANSFORMABLE-REQUIRES-SESSION-OR-WINDOW-EXCLUSION",
        ),
        (
            "spin_offs",
            "spin_off",
            "ex_date",
            "NONTRANSFORMABLE-REQUIRES-SESSION-OR-WINDOW-EXCLUSION",
        ),
        (
            "cash_mergers",
            "cash_merger",
            "effective_date",
            "NONTRANSFORMABLE-REQUIRES-SESSION-OR-WINDOW-EXCLUSION",
        ),
        (
            "stock_mergers",
            "stock_merger",
            "effective_date",
            "NONTRANSFORMABLE-REQUIRES-SESSION-OR-WINDOW-EXCLUSION",
        ),
        (
            "stock_and_cash_mergers",
            "stock_and_cash_merger",
            "effective_date",
            "NONTRANSFORMABLE-REQUIRES-SESSION-OR-WINDOW-EXCLUSION",
        ),
        (
            "redemptions",
            "redemption",
            None,
            "NONTRANSFORMABLE-REQUIRES-SESSION-OR-WINDOW-EXCLUSION",
        ),
        (
            "name_changes",
            "name_change",
            None,
            "NONTRANSFORMABLE-REQUIRES-SESSION-OR-WINDOW-EXCLUSION",
        ),
        (
            "worthless_removals",
            "worthless_removal",
            None,
            "NONTRANSFORMABLE-REQUIRES-SESSION-OR-WINDOW-EXCLUSION",
        ),
        (
            "rights_distributions",
            "rights_distribution",
            "ex_date",
            "NONTRANSFORMABLE-REQUIRES-SESSION-OR-WINDOW-EXCLUSION",
        ),
        (
            "partial_calls",
            "partial_call",
            None,
            "NONTRANSFORMABLE-REQUIRES-SESSION-OR-WINDOW-EXCLUSION",
        ),
        (
            "reorganizations",
            "reorganization",
            "effective_date",
            "NONTRANSFORMABLE-REQUIRES-SESSION-OR-WINDOW-EXCLUSION",
        ),
        (
            "capital_gains_distributions",
            "capital_gains_distribution",
            "ex_date",
            "NON-UNIT-METADATA",
        ),
    ],
)
def test_all_current_event_types_normalize_fail_closed(
    array_name: str,
    event_type: str,
    effective_field: str | None,
    classification: str,
) -> None:
    (action,), token = metadata.parse_metadata_page(_body({array_name: [_event(array_name)]}))

    assert token is None
    assert action.action_type == event_type
    assert action.effective_date_field == effective_field
    assert action.classification == classification
    assert action.target_symbols
    assert action.source_identity


def test_no_events_is_complete_only_after_both_chains_terminate() -> None:
    source = _source(_body(), _body())

    result = metadata.execute_synthetic_metadata(source)

    assert result.events == ()
    assert result.response_count == 2
    assert source.consumed_response_count == 2
    assert source.intent_records_present == (True, True)
    assert set(source.evidence_keys) == {
        "symbols-01.intent.json",
        "symbols-01.body",
        "symbols-01.receipt.json",
        "cusips-01.intent.json",
        "cusips-01.body",
        "cusips-01.receipt.json",
        "private-manifest.json",
    }


def test_forward_and_reverse_split_factors_are_exact_rationals() -> None:
    forward = _event("forward_splits")
    forward["old_rate"] = 2
    forward["new_rate"] = 3
    reverse = _event("reverse_splits", 2)

    actions, _ = metadata.parse_metadata_page(
        _body({"forward_splits": [forward], "reverse_splits": [reverse]})
    )

    by_type = {action.action_type: action for action in actions}
    assert by_type["forward_split"].exact_factor == Fraction(3, 2)
    assert by_type["reverse_split"].exact_factor == Fraction(1, 5)


def test_delayed_processing_does_not_replace_the_economic_date() -> None:
    delayed = _event("forward_splits")
    delayed["process_date"] = "2026-08-29"
    delayed["ex_date"] = "2025-12-05"

    (action,), _ = metadata.parse_metadata_page(_body({"forward_splits": [delayed]}))

    assert action.process_date.isoformat() == "2026-08-29"
    assert action.effective_date is not None
    assert action.effective_date.isoformat() == "2025-12-05"


def test_same_identity_name_change_is_nonbreaking_metadata() -> None:
    name_change = _event("name_changes")
    name_change["new_symbol"] = name_change["old_symbol"]
    name_change["new_cusip"] = name_change["old_cusip"]

    (action,), _ = metadata.parse_metadata_page(_body({"name_changes": [name_change]}))

    assert action.classification == "IDENTITY-METADATA-NO-BREAK"


def test_reverse_split_cusip_transition_fails_identity_validation() -> None:
    reverse = _event("reverse_splits")
    reverse["new_cusip"] = metadata.IDENTITIES["IWM"]

    with pytest.raises(metadata.Program007MetadataError, match="identity is inconsistent"):
        metadata.parse_metadata_page(_body({"reverse_splits": [reverse]}))


def test_predecessor_content_mismatch_between_identity_chains_fails() -> None:
    symbol_event = _event("name_changes")
    symbol_event["old_symbol"] = "SPY.OLD"
    symbol_event["old_cusip"] = "000000008"
    symbol_event["new_symbol"] = "SPY"
    symbol_event["new_cusip"] = metadata.IDENTITIES["SPY"]
    cusip_event = deepcopy(symbol_event)
    cusip_event["old_symbol"] = "SPY.PREV"

    source = _source(
        _body({"name_changes": [symbol_event]}),
        _body({"name_changes": [cusip_event]}),
    )

    with pytest.raises(metadata.Program007MetadataError, match="content differs"):
        metadata.execute_synthetic_metadata(source)


def test_pagination_is_exhausted_and_reconciled_by_provider_event_id() -> None:
    event = _event("forward_splits")
    first = _body({"forward_splits": [event]}, "next")
    terminal = _body()
    source = _source(first, terminal, _body({"forward_splits": [event]}))

    result = metadata.execute_synthetic_metadata(source)

    assert len(result.events) == 1
    assert result.response_count == 3
    assert result.chains[0].pages[1].incoming_page_token == "next"
    assert parse_qs(urlparse(source.intents[1].url).query)["page_token"] == ["next"]


def test_duplicate_events_and_symbol_cusip_inventory_conflicts_fail() -> None:
    event = _event("forward_splits")
    with pytest.raises(metadata.Program007MetadataError, match="duplicate event"):
        metadata.parse_metadata_page(_body({"forward_splits": [event, deepcopy(event)]}))

    source = _source(_body({"forward_splits": [event]}), _body())
    with pytest.raises(metadata.Program007MetadataError, match="inventories differ"):
        metadata.execute_synthetic_metadata(source)


def test_missing_dates_identity_conflicts_malformed_factors_and_unknown_arrays_fail() -> None:
    missing_date = _event("forward_splits")
    del missing_date["ex_date"]
    inconsistent = _event("forward_splits", 2)
    inconsistent["cusip"] = metadata.IDENTITIES["IWM"]
    malformed = _event("forward_splits", 3)
    malformed["new_rate"] = "2"
    out_of_window = _event("forward_splits", 4)
    out_of_window["process_date"] = "1989-12-31"

    cases = [
        (_body({"forward_splits": [missing_date]}), "schema differs"),
        (_body({"forward_splits": [inconsistent]}), "identity is inconsistent"),
        (_body({"forward_splits": [malformed]}), "exact number"),
        (_body({"forward_splits": [out_of_window]}), "outside the frozen query bounds"),
        (_body({"future_actions": []}), "unknown event arrays"),
    ]
    for body, message in cases:
        with pytest.raises(metadata.Program007MetadataError, match=message):
            metadata.parse_metadata_page(body)


def test_known_five_sector_positive_controls_generate_only_a_synthetic_candidate() -> None:
    events: list[dict[str, Any]] = []
    for index, symbol in enumerate(sorted(metadata.POSITIVE_CONTROLS), start=1):
        event = _event("forward_splits", index)
        event["symbol"] = symbol
        event["cusip"] = metadata.IDENTITIES[symbol]
        events.append(event)
    result = _execute_same({"forward_splits": events})

    candidate = metadata.generate_successor_ledger_candidate(result, _ledger())

    assert candidate["status"] == "SYNTHETIC-CORROBORATION-CANDIDATE-NOT-AUTHORITATIVE"
    assert candidate["identity_history_status"] == metadata.IDENTITY_HISTORY_STATUS
    assert candidate["source_finality_status"] == metadata.SOURCE_FINALITY_STATUS
    assert len(candidate["actions"]) == 5
    assert all(
        action["exact_factor"] == {"numerator": 2, "denominator": 1}
        for action in candidate["actions"]
    )
    assert all(value is False for value in candidate["authority"].values())
    assert hashlib.sha256(_LEDGER_PATH.read_bytes()).hexdigest() == _LEDGER_SHA256


def test_old_economic_event_is_retained_but_outside_feature_relevance() -> None:
    events: list[dict[str, Any]] = []
    for index, symbol in enumerate(sorted(metadata.POSITIVE_CONTROLS), start=1):
        event = _event("forward_splits", index)
        event["symbol"] = symbol
        event["cusip"] = metadata.IDENTITIES[symbol]
        events.append(event)
    old = _event("forward_splits", 100)
    old["symbol"] = "IWM"
    old["cusip"] = metadata.IDENTITIES["IWM"]
    old["ex_date"] = "2005-06-09"
    old["process_date"] = "2026-08-29"
    result = _execute_same({"forward_splits": [*events, old]})

    candidate = metadata.generate_successor_ledger_candidate(result, _ledger())

    assert len(result.events) == 6
    assert len(candidate["actions"]) == 5


def test_cash_dividend_only_is_non_unit_negative_control_metadata() -> None:
    cash_dividend = _event("cash_dividends")
    controls: list[dict[str, Any]] = []
    for index, symbol in enumerate(sorted(metadata.POSITIVE_CONTROLS), start=10):
        event = _event("forward_splits", index)
        event["symbol"] = symbol
        event["cusip"] = metadata.IDENTITIES[symbol]
        controls.append(event)
    result = _execute_same({"cash_dividends": [cash_dividend], "forward_splits": controls})

    candidate = metadata.generate_successor_ledger_candidate(result, _ledger())

    xlf = next(item for item in candidate["symbols"] if item["symbol"] == "XLF")
    assert xlf["conclusion"] == "NO-ADDITIONAL-APPLICABLE-ACTION-OBSERVED-AS-OF-QUERY"
    assert all(action["action_type"] != "cash_dividend" for action in candidate["actions"])


@pytest.mark.parametrize("symbol", ["IWM", "MDY", "SPY", "XLF", "XLI", "XLP", "XLRE", "XLV"])
def test_unexpected_unit_event_for_closed_no_known_action_symbol_fails(symbol: str) -> None:
    events: list[dict[str, Any]] = []
    for index, control in enumerate(sorted(metadata.POSITIVE_CONTROLS), start=1):
        event = _event("forward_splits", index)
        event["symbol"] = control
        event["cusip"] = metadata.IDENTITIES[control]
        events.append(event)
    unexpected = _event("forward_splits", 100)
    unexpected["symbol"] = symbol
    unexpected["cusip"] = metadata.IDENTITIES[symbol]
    result = _execute_same({"forward_splits": [*events, unexpected]})

    with pytest.raises(
        metadata.Program007MetadataError, match="discrepancies require investigation"
    ):
        metadata.generate_successor_ledger_candidate(result, _ledger())


def test_nontransformable_action_and_missing_effective_semantics_block_candidate() -> None:
    unit_split = _execute_same({"unit_splits": [_event("unit_splits")]})
    with pytest.raises(
        metadata.Program007MetadataError, match="not deterministically transformable"
    ):
        metadata.generate_successor_ledger_candidate(unit_split, _ledger())

    redemption = _execute_same({"redemptions": [_event("redemptions")]})
    with pytest.raises(metadata.Program007MetadataError, match="no unambiguous effective date"):
        metadata.generate_successor_ledger_candidate(redemption, _ledger())


@pytest.mark.parametrize(
    ("response", "error", "message"),
    [
        (
            metadata.RawResponse(401, b'{"error":"authentication"}'),
            metadata.MetadataAuthenticationError,
            "METADATA-AUTHENTICATION-FAIL-USE-CONSUMED-NO-RETRY",
        ),
        (
            metadata.RawResponse(403, b'{"error":"entitlement"}'),
            metadata.MetadataAccessError,
            "METADATA-ACCESS-FAIL-USE-CONSUMED-NO-RETRY-NO-PURCHASE",
        ),
        (
            metadata.RawResponse(429, b'{"error":"rate limit"}'),
            metadata.MetadataAccessError,
            "METADATA-ACCESS-FAIL-USE-CONSUMED-NO-RETRY",
        ),
        (
            metadata.RawResponse(302, b"redirect"),
            metadata.Program007MetadataError,
            "redirect attempt rejected",
        ),
        (
            metadata.RawResponse(200, b"not-json"),
            metadata.Program007MetadataError,
            "is not valid JSON",
        ),
    ],
)
def test_bounded_raw_response_and_receipt_precede_status_or_schema_failure(
    response: metadata.RawResponse,
    error: type[Exception],
    message: str,
) -> None:
    source = metadata.SyntheticMetadataSource([response])

    with pytest.raises(error, match=message):
        metadata.execute_synthetic_metadata(source)

    payloads = _evidence_payloads(source)
    assert payloads["symbols-01.body"] == response.body
    receipt = json.loads(payloads["symbols-01.receipt.json"])
    assert receipt["status"] == response.status
    assert receipt["response_sha256"] == hashlib.sha256(response.body).hexdigest()
    assert source.intent_records_present == (True,)


def test_oversized_response_is_retained_before_size_failure() -> None:
    body = b"x" * (metadata.MAXIMUM_RESPONSE_PAGE_BYTES + 1)
    source = metadata.SyntheticMetadataSource([metadata.RawResponse(200, body)])

    with pytest.raises(metadata.Program007MetadataError, match="exceeds 1 MiB"):
        metadata.execute_synthetic_metadata(source)

    payloads = _evidence_payloads(source)
    assert payloads["symbols-01.body"] == body
    receipt = json.loads(payloads["symbols-01.receipt.json"])
    assert receipt["response_bytes"] == len(body)
    assert receipt["response_sha256"] == hashlib.sha256(body).hexdigest()


def test_total_response_byte_budget_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metadata, "MAXIMUM_DOWNLOADED_BYTES", 3)
    budget = metadata._Budget()

    budget.accept_response(b"12")
    with pytest.raises(metadata.Program007MetadataError, match="byte ceiling exceeded"):
        budget.accept_response(b"34")


def test_pagination_token_cycle_and_page_ceiling_fail() -> None:
    cycle = _source(_body(next_page="same"), _body(next_page="same"))
    with pytest.raises(metadata.Program007MetadataError, match="token repeats"):
        metadata.execute_synthetic_metadata(cycle)

    pages = [_body(next_page=f"page-{index}") for index in range(1, 5)]
    ceiling = _source(*pages)
    with pytest.raises(metadata.Program007MetadataError, match="exceeds four pages"):
        metadata.execute_synthetic_metadata(ceiling)


def test_mock_persistent_transport_writes_private_create_only_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [metadata.RawResponse(200, _body()), metadata.RawResponse(200, _body())]
    transport = metadata.MockMetadataTransport(responses)
    loads = 0
    original_loader = metadata._load_explicit_credentials
    private_root = tmp_path / metadata.PRIVATE_ROOT

    def counted_loader(environ: dict[str, str]) -> tuple[str, str]:
        nonlocal loads
        loads += 1
        return original_loader(environ)

    monkeypatch.setattr(metadata, "_load_explicit_credentials", counted_loader)
    result = metadata.execute_mock_persistent_metadata(
        tmp_path,
        environ={
            metadata.CREDENTIAL_NAMES[0]: "synthetic-key-id",
            metadata.CREDENTIAL_NAMES[1]: "synthetic-secret-key",
        },
        transport=transport,
    )

    assert result.response_count == 2
    assert loads == 1
    assert all(request.get_method() == "GET" for request in transport.requests)
    assert all(
        (
            urlparse(request.full_url).scheme,
            urlparse(request.full_url).netloc,
            urlparse(request.full_url).path,
        )
        == ("https", "data.alpaca.markets", "/v1/corporate-actions")
        for request in transport.requests
    )
    assert all(
        request.get_header("Apca-api-key-id") == "synthetic-key-id"
        for request in transport.requests
    )
    assert all(
        request.get_header("Apca-api-secret-key") == "synthetic-secret-key"
        for request in transport.requests
    )
    assert {path.name for path in private_root.iterdir()} == {
        "run.lock",
        "symbols-01.intent.json",
        "symbols-01.body",
        "symbols-01.receipt.json",
        "cusips-01.intent.json",
        "cusips-01.body",
        "cusips-01.receipt.json",
        "private-manifest.json",
    }
    assert private_root.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in private_root.iterdir())
    manifest = json.loads((private_root / "private-manifest.json").read_bytes())
    assert manifest["status"] == "MOCK-TRANSPORT-PERSISTENT-CONTRACT-PASS"
    assert manifest["metadata_query_end"] == "2026-08-29"
    assert manifest["metadata_observation_as_of"].endswith("Z")
    assert manifest["synthetic_credential_loads"] == 1
    assert manifest["provider_requests"] == 0
    private_bytes = b"".join(path.read_bytes() for path in private_root.iterdir() if path.is_file())
    assert b"synthetic-key-id" not in private_bytes
    assert b"synthetic-secret-key" not in private_bytes

    with pytest.raises(metadata.Program007MetadataError, match="evidence already exists"):
        metadata.execute_mock_persistent_metadata(
            tmp_path,
            environ={
                metadata.CREDENTIAL_NAMES[0]: "synthetic-key-id",
                metadata.CREDENTIAL_NAMES[1]: "synthetic-secret-key",
            },
            transport=metadata.MockMetadataTransport(responses),
        )
    assert loads == 1


def test_persistent_writes_remain_anchored_after_private_root_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_root = tmp_path / metadata.PRIVATE_ROOT
    relocated_root = private_root.with_name(private_root.name + "-relocated")
    external_root = tmp_path / "external"
    original_loader = metadata._load_explicit_credentials

    def swapping_loader(environ: dict[str, str]) -> tuple[str, str]:
        external_root.mkdir()
        private_root.rename(relocated_root)
        private_root.symlink_to(external_root, target_is_directory=True)
        return original_loader(environ)

    monkeypatch.setattr(metadata, "_load_explicit_credentials", swapping_loader)
    metadata.execute_mock_persistent_metadata(
        tmp_path,
        environ={
            metadata.CREDENTIAL_NAMES[0]: "synthetic-key-id",
            metadata.CREDENTIAL_NAMES[1]: "synthetic-secret-key",
        },
        transport=metadata.MockMetadataTransport(
            [metadata.RawResponse(200, _body()), metadata.RawResponse(200, _body())]
        ),
    )

    assert private_root.is_symlink()
    assert not any(external_root.iterdir())
    assert (relocated_root / "private-manifest.json").is_file()


def test_dormant_http_transport_is_get_only_no_redirect_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self, size: int) -> bytes:
            assert size == metadata.MAXIMUM_RESPONSE_PAGE_BYTES + 1
            return b"bounded"

    class Opener:
        def open(self, request: Any, *, timeout: int) -> Response:
            assert request.get_method() == "GET"
            assert timeout == 30
            return Response()

    def opener(handler: Any) -> Opener:
        assert isinstance(handler, metadata._NoRedirect)
        return Opener()

    monkeypatch.setattr(metadata, "_REAL_TRANSPORT_AUTHORIZED", True)
    monkeypatch.setattr(metadata, "build_opener", opener)
    request = Request(metadata.frozen_request_chains()[0].url(), method="GET")

    assert metadata._urlopen_response(request) == metadata.RawResponse(200, b"bounded")
    with pytest.raises(metadata.Program007MetadataError, match="endpoint differs"):
        metadata._urlopen_response(
            Request("https://paper-api.alpaca.markets/v2/orders", method="GET")
        )


def test_dormant_http_transport_closes_http_error_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = io.BytesIO(b"denied")
    error = HTTPError(metadata.ENDPOINT, 401, "unauthorized", Message(), body)

    class Opener:
        def open(self, _request: Any, *, timeout: int) -> None:
            assert timeout == 30
            raise error

    monkeypatch.setattr(metadata, "_REAL_TRANSPORT_AUTHORIZED", True)
    monkeypatch.setattr(metadata, "build_opener", lambda _handler: Opener())
    request = Request(metadata.frozen_request_chains()[0].url(), method="GET")

    assert metadata._urlopen_response(request) == metadata.RawResponse(401, b"denied")
    assert body.closed


def test_dormant_http_transport_is_source_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    opener_called = False

    def opener(_handler: Any) -> None:
        nonlocal opener_called
        opener_called = True

    monkeypatch.setattr(metadata, "build_opener", opener)
    request = Request(metadata.frozen_request_chains()[0].url(), method="GET")

    with pytest.raises(metadata.Program007MetadataError, match="transport is not authorized"):
        metadata._urlopen_response(request)
    assert not opener_called


def test_source_is_immutable_and_real_transport_has_no_execution_entrypoint(tmp_path: Path) -> None:
    source = _source(_body(), _body())

    with pytest.raises(AttributeError, match="immutable"):
        source._responses = ()

    assert tuple(inspect.signature(metadata.execute_synthetic_metadata).parameters) == ("source",)
    mock_signature = inspect.signature(metadata.execute_mock_persistent_metadata)
    assert mock_signature.parameters["transport"].default is inspect.Signature.empty
    with pytest.raises(metadata.Program007MetadataError, match="requires a finite mock"):
        metadata.execute_mock_persistent_metadata(
            tmp_path,
            environ={},
            transport=cast(Any, metadata._urlopen_response),
        )
    assert not (tmp_path / metadata.PRIVATE_ROOT).exists()
    assert not any(name.startswith("APCA") for name in vars(metadata))
    assert metadata.CREDENTIAL_NAMES == (
        "PROGRAM_007_CORPORATE_ACTIONS_API_KEY_ID",
        "PROGRAM_007_CORPORATE_ACTIONS_API_SECRET_KEY",
    )
    assert all(value is False for value in metadata._AUTHORITY.values())
    assert metadata.AUTOMATIC_TRANSPORT_RETRIES == 0


def test_synthetic_source_context_closes_its_evidence_descriptor() -> None:
    with _source(_body(), _body()) as source:
        assert not source._evidence.closed
    assert source._evidence.closed
    with pytest.raises(metadata.Program007MetadataError, match="evidence is closed"):
        metadata.execute_synthetic_metadata(source)


def test_secret_guard_covers_metadata_credential_names() -> None:
    spec = importlib.util.spec_from_file_location(
        "program_007_metadata_check_secrets", _REPOSITORY / "scripts/check_secrets.py"
    )
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    public_program_artifacts = {
        path.relative_to(_REPOSITORY).as_posix()
        for path in (_REPOSITORY / "config/research").glob("program-007*.json")
    }
    assert public_program_artifacts <= guard.PUBLIC_PROGRAM_JSON
    for suffix in ("KEY_ID", "SECRET_KEY"):
        name = "PROGRAM_007_CORPORATE_ACTIONS_API_" + suffix
        assert any(pattern.search(f"{name}=example") for pattern in guard.PATTERNS)
        assert guard.PROGRAM_JSON_CREDENTIAL.search(json.dumps({name: "example"}))
