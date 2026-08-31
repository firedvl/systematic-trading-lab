from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, cast

from systematic_trading_lab import program_011_ohlcv as program_011
from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_IMPLEMENTATION_PATH = Path("config/research/program-011-raw-source-implementation-v1.json")
_PROPOSAL_PATH = Path(
    "config/research/program-011-raw-alpaca-sip-ohlcv-structural-qualification-proposal-v1.json"
)


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_REPOSITORY / path).read_text(encoding="utf-8")))


def _assert_fingerprint(path: Path, field: str) -> dict[str, Any]:
    value = _load(path)
    stored = value.pop(field)
    assert stored == fingerprint(value)
    return {**value, field: stored}


def _assert_binding(binding: dict[str, str]) -> dict[str, Any]:
    path = Path(binding["path"])
    assert hashlib.sha256((_REPOSITORY / path).read_bytes()).hexdigest() == binding["sha256"]
    value = _load(path)
    assert binding["fingerprint"] in {
        item for key, item in value.items() if key.endswith("_fingerprint")
    }
    return value


def test_program_011_implementation_is_exact_and_synthetic_only() -> None:
    implementation = _assert_fingerprint(_IMPLEMENTATION_PATH, "implementation_fingerprint")
    binding = implementation["implementation_binding"]

    assert binding["source_commit"] == "15477e31543b132da4994587d993a84fb7af801a"
    assert binding["source_tree"] == "6d690298d1939473cd76f45ec106a82c02fa3267"
    assert binding["implementation_root"] == fingerprint(binding["source_files"])
    for source in binding["source_files"]:
        committed = subprocess.run(
            (
                "git",
                "-C",
                str(_REPOSITORY),
                "show",
                f"{binding['source_commit']}:{source['path']}",
            ),
            check=True,
            capture_output=True,
        ).stdout
        assert hashlib.sha256(committed).hexdigest() == source["sha256"]

    assert implementation["program_ordinal"] == program_011.PROGRAM_ORDINAL == 11
    assert implementation["program_id"] == program_011.PROGRAM_ID
    assert implementation["status"] == "FROZEN-PROSPECTIVE-SYNTHETIC-ONLY"
    assert (
        implementation["ordering_contract"]["json_object_member_order_has_semantic_meaning"]
        is False
    )
    assert implementation["ordering_contract"]["received_symbol_array_timestamp_order"] == (
        "STRICTLY-ASCENDING"
    )
    assert implementation["reuse_boundary"]["program_010_terminal_revocation_changed"] is False
    assert implementation["execution_boundary"]["provider_transport_present"] is False
    assert implementation["execution_boundary"]["authority_activation_present"] is False
    assert all(value is False for value in implementation["authority"].values())


def test_program_011_proposal_binds_fresh_sample_and_grants_no_authority() -> None:
    proposal = _assert_fingerprint(_PROPOSAL_PATH, "proposal_fingerprint")
    for binding in proposal["bindings"].values():
        _assert_binding(binding)

    implementation = _load(_IMPLEMENTATION_PATH)
    implementation_binding = proposal["bindings"]["program_011_implementation"]
    assert implementation_binding["fingerprint"] == implementation["implementation_fingerprint"]
    assert (
        implementation_binding["source_commit"]
        == implementation["implementation_binding"]["source_commit"]
    )
    assert (
        implementation_binding["implementation_root"]
        == implementation["implementation_binding"]["implementation_root"]
    )

    assert proposal["status"] == program_011.STATUS == "PROPOSED-NOT-AUTHORIZED"
    assert proposal["lineage"]["program_010"] == "TERMINAL-FAIL-CONSUMED-NO-RETRY"
    assert proposal["lineage"]["program_010_replay_allowed"] is False
    assert proposal["forensic_conclusions"]["program_010_global_json_object_member_order"] == (
        "QUALIFICATION-SPECIFICATION-DEFECT"
    )
    pagination = proposal["pagination_contract"]
    assert pagination["json_object_member_order_has_semantic_meaning"] is False
    assert pagination["per_symbol_order_checked_before_normalization"] is True
    assert pagination["post_validation_normalization"] == (
        "DETERMINISTIC-SYMBOL-THEN-TIMESTAMP-SORT"
    )
    assert pagination["maximum_pages_per_session"] == program_011.MAXIMUM_PAGES_PER_SESSION

    fresh = proposal["fresh_sample"]
    assert fresh["observed_program_002_through_010_union_sessions"] == 199
    assert fresh["eligible_unobserved_unprotected_sessions"] == 1_188
    assert [item["date"] for item in fresh["sessions"]] == [
        session.isoformat() for session in program_011.SELECTED_SESSIONS
    ]
    assert fresh["sample_fingerprint"] == (
        "549a83f7af681088012d2867dfa63aebe6878f817fc13e692e3fe948e9ca62bc"
    )
    assert fresh["expected_canonical_coordinates"] == 4_602
    assert fresh["program_010_2021_05_25_excluded"] is True

    assert proposal["external_authorization_root"] is None
    assert all(value is False for value in proposal["authority"].values())
    assert all(value is False for value in proposal["protected_firewall"].values())
    assert "PLACEHOLDER" not in (_REPOSITORY / _PROPOSAL_PATH).read_text(encoding="utf-8")
