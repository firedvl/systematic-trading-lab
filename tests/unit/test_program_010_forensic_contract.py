from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

from systematic_trading_lab import program_010_ohlcv as program_010
from systematic_trading_lab.calendar import expected_bar_timestamps, expected_sessions
from systematic_trading_lab.domain import Timeframe
from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_CONTRACT_PATH = Path("config/research/program-010-alpaca-bars-public-contract-evidence-v1.json")
_FORENSIC_PATH = Path("config/research/program-009-raw-sip-ohlcv-offline-forensic-analysis-v1.json")
_PROGRAM_007_PROPOSAL = Path(
    "config/research/program-007-alpaca-raw-source-qualification-proposal-v1.json"
)
_PROGRAM_009_TERMINAL = Path(
    "config/research/program-009-raw-alpaca-sip-ohlcv-structural-qualification-terminal-failure-v1.json"
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
    if "fingerprint" in binding:
        fields = [key for key in value if key.endswith("_fingerprint")]
        assert binding["fingerprint"] in {value[key] for key in fields}
    return value


def test_public_contract_and_forensics_are_bound_and_non_authorizing() -> None:
    contract = _assert_fingerprint(_CONTRACT_PATH, "evidence_fingerprint")
    forensic = _assert_fingerprint(_FORENSIC_PATH, "analysis_fingerprint")

    _assert_binding(forensic["terminal_state"]["terminal_failure"])
    _assert_binding(forensic["terminal_state"]["terminal_review"])
    _assert_binding(forensic["evidence"]["current_provider_contract"])

    assert forensic["terminal_state"]["status"] == "TERMINAL-FAIL-CONSUMED-NO-RETRY"
    assert forensic["terminal_state"]["replay_allowed"] is False
    assert forensic["questions"]["a_pagination_transport_failure"]["classification"] == (
        "QUALIFICATION-SPECIFICATION-DEFECT"
    )
    assert forensic["questions"]["b_retained_pagination_missingness"]["classification"] == (
        "VALID-DATASET-QUALITY-FINDING"
    )
    assert (
        forensic["questions"]["c_qualification_dataset_responsibility"]["classification"]
        == "QUALIFICATION-SPECIFICATION-DEFECT"
    )
    assert forensic["missingness_refinement"]["confirmed_source_missing"] == 1
    assert forensic["missingness_refinement"]["unobserved_because_chain_stopped"] == 244
    assert contract["contract_conclusion"]["limit_is_minimum_fill_guarantee"] is False
    assert contract["retrieval_boundary"]["data_endpoint_requests"] == 0
    assert all(value is False for value in contract["authority"].values())
    assert all(value == 0 for value in forensic["scope_boundary"].values())


def test_fresh_sample_rederives_from_public_request_inventory() -> None:
    forensic = _load(_FORENSIC_PATH)
    predecessor = _assert_fingerprint(_PROGRAM_007_PROPOSAL, "proposal_fingerprint")
    terminal = _assert_fingerprint(_PROGRAM_009_TERMINAL, "failure_fingerprint")
    audit = predecessor["prior_provider_observation_audit"]

    start = datetime(2020, 6, 26, tzinfo=UTC)
    end = datetime(2026, 7, 31, 23, 59, tzinfo=UTC)
    sessions = expected_sessions(start, end)
    grid_counts = Counter(
        timestamp.date()
        for timestamp in expected_bar_timestamps(start, end, Timeframe.FIVE_MINUTES)
    )
    program_002 = set(
        expected_sessions(
            datetime(2020, 6, 26, tzinfo=UTC),
            datetime(2021, 2, 26, 23, 59, tzinfo=UTC),
        )
    )
    program_006 = {date.fromisoformat(value) for value in audit["program_006_observed_sessions"]}
    program_009_sessions = terminal["qualification_contract"]["sessions"]
    pages = terminal["runtime_outcome"]["pages_per_chain"]
    assert pages["split-pre-early-close-2025-11-28"] == 0
    assert pages["split-post-2025-12-15"] == 0
    program_009 = {date.fromisoformat(value) for value in program_009_sessions[:-2]}

    for path in (
        Path(
            "config/research/program-007-corporate-action-metadata-qualification-terminal-failure-v1.json"
        ),
        Path(
            "config/research/program-008-corporate-action-metadata-qualification-terminal-success-v1.json"
        ),
    ):
        metadata_outcome = _load(path)
        assert metadata_outcome["effective_final_authority"]["market_data_acquisition"] is False
        assert (
            metadata_outcome["runtime_outcome"]["private_dataset_count"] == 0
            if ("private_dataset_count" in metadata_outcome["runtime_outcome"])
            else metadata_outcome["runtime_outcome"]["dataset_admitted"] is False
        )

    observed = program_002 | program_006 | program_009
    protected_ranges = audit["protected_or_controlled_exclusion_inventory"]["ranges"]
    protected = {
        session
        for session in sessions
        if any(
            date.fromisoformat(item["start"]) <= session <= date.fromisoformat(item["end"])
            for item in protected_ranges
        )
    }
    eligible = tuple(session for session in sessions if session not in observed | protected)
    controls = {date(2025, 11, 28), date(2025, 12, 15)}
    seed = forensic["prospective_freshness"]["seed"]
    candidates = sorted(
        (
            hashlib.sha256(f"{seed}|normal|{session}".encode()).hexdigest(),
            session,
        )
        for session in eligible
        if grid_counts[session] == 78 and session not in controls
    )
    selected = tuple(sorted(controls | {session for _, session in candidates[:3]}))

    assert len(observed) == 198
    assert (
        fingerprint([str(value) for value in sorted(observed)])
        == (forensic["prospective_freshness"]["observed_union_fingerprint"])
    )
    assert len(eligible) == 1189
    assert (
        fingerprint([str(value) for value in eligible])
        == (forensic["prospective_freshness"]["eligible_fingerprint"])
    )
    assert [str(value) for value in selected] == forensic["prospective_freshness"][
        "selected_sessions"
    ]
    assert (
        fingerprint([str(value) for value in selected])
        == forensic["prospective_freshness"]["selected_session_fingerprint"]
    )
    assert not set(selected) & observed
    assert not set(selected) & protected
    assert sum(grid_counts[value] * 13 for value in selected) == 4_602


def test_offline_implementation_matches_frozen_forensic_design() -> None:
    forensic = _load(_FORENSIC_PATH)
    architecture = forensic["prospective_architecture"]

    assert program_010.PROGRAM_ID == "multi-hour-sector-etf-research-009"
    assert program_010.STATUS == "PROPOSED-NOT-AUTHORIZED"
    assert architecture["selection"] == "SESSION-SCOPED-MULTI-SYMBOL"
    assert architecture["limit"] == program_010.PAGE_ROW_LIMIT == 1000
    assert (
        architecture["resource_safety_cap"]["pages_per_session"]
        == program_010.MAXIMUM_PAGES_PER_SESSION
        == 16
    )
    assert [session.isoformat() for session in program_010.SELECTED_SESSIONS] == forensic[
        "prospective_freshness"
    ]["selected_sessions"]
    assert program_010.MAXIMUM_QUALIFICATION_REQUESTS == 80
    assert program_010.AUTOMATIC_RETRIES == 0
