from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import systematic_trading_lab.program_010_ohlcv as program_010
from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_IMPLEMENTATION_PATH = Path("config/research/program-010-raw-source-implementation-v1.json")
_PROPOSAL_PATH = Path(
    "config/research/program-010-raw-alpaca-sip-ohlcv-structural-qualification-proposal-v1.json"
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
    assert binding["fingerprint"] in {value[key] for key in value if key.endswith("_fingerprint")}
    return value


def test_program_010_implementation_and_proposal_are_bound_and_non_authorizing() -> None:
    implementation = _assert_fingerprint(_IMPLEMENTATION_PATH, "implementation_fingerprint")
    implementation_binding = implementation["implementation_binding"]
    assert implementation_binding["source_commit"] == ("a32f14c3aea7eb2448b47073934ae003413d222d")
    assert implementation_binding["implementation_root"] == fingerprint(
        implementation_binding["source_files"]
    )
    for source in implementation_binding["source_files"]:
        assert (
            hashlib.sha256((_REPOSITORY / source["path"]).read_bytes()).hexdigest()
            == source["sha256"]
        )

    proposal = _assert_fingerprint(_PROPOSAL_PATH, "proposal_fingerprint")
    for binding in proposal["bindings"].values():
        _assert_binding(binding)

    proposal_implementation = proposal["bindings"]["program_010_implementation"]
    assert proposal_implementation["fingerprint"] == implementation["implementation_fingerprint"]
    assert proposal_implementation["source_commit"] == implementation_binding["source_commit"]
    assert (
        proposal_implementation["implementation_root"]
        == implementation_binding["implementation_root"]
    )
    assert proposal["status"] == program_010.STATUS == "PROPOSED-NOT-AUTHORIZED"
    assert proposal["lineage"]["program_009"] == "TERMINAL-FAIL-CONSUMED-NO-RETRY"
    assert proposal["forensic_conclusions"]["six_page_ceiling"] == (
        "QUALIFICATION-SPECIFICATION-DEFECT"
    )
    assert proposal["forensic_conclusions"]["mdy_2023_05_19_17_10_utc"] == (
        "CONFIRMED-SOURCE-MISSING"
    )
    assert proposal["forensic_conclusions"]["xly_tail"] == ("NOT-OBSERVED-DUE-TO-PAGINATION-STOP")
    assert proposal["pagination_contract"]["terminal_condition"] == ("next_page_token is null")
    assert proposal["pagination_contract"]["maximum_pages_per_session"] == (
        program_010.MAXIMUM_PAGES_PER_SESSION
    )
    assert proposal["fresh_sample"]["expected_canonical_coordinates"] == 4_602
    assert proposal["budgets"]["qualification_maximum_requests_and_responses"] == (
        program_010.MAXIMUM_QUALIFICATION_REQUESTS
    )
    assert proposal["external_authorization_root"] is None
    assert all(value is False for value in proposal["authority"].values())
