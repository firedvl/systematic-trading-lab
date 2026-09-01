from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from datetime import UTC, date, datetime, time
from math import comb, floor
from pathlib import Path
from typing import Any, cast

from systematic_trading_lab.calendar import expected_bar_timestamps, expected_sessions
from systematic_trading_lab.domain import Timeframe
from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_V1_PROPOSAL_PATH = Path(
    "config/research/program-012-exposed-prefix-raw-alpaca-sip-acquisition-and-structural-admission-proposal-v1.json"
)
_V2_PROPOSAL_PATH = Path(
    "config/research/program-012-exposed-prefix-raw-alpaca-sip-acquisition-and-structural-admission-proposal-v2.json"
)
_PROPOSAL_PATH = Path(
    "config/research/program-012-exposed-prefix-raw-alpaca-sip-acquisition-and-structural-admission-proposal-v3.json"
)
_REVIEW_PATH = Path(
    "config/research/program-012-exposed-prefix-raw-alpaca-sip-acquisition-and-structural-admission-independent-review-v1.json"
)
_V1_IMPLEMENTATION_PATH = Path(
    "config/research/program-012-exposed-prefix-runtime-implementation-v1.json"
)
_IMPLEMENTATION_PATH = Path(
    "config/research/program-012-exposed-prefix-runtime-implementation-v2.json"
)


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_REPOSITORY / path).read_text(encoding="utf-8")))


def _assert_binding(binding: dict[str, str]) -> dict[str, Any]:
    path = Path(binding["path"])
    assert hashlib.sha256((_REPOSITORY / path).read_bytes()).hexdigest() == binding["sha256"]
    value = _load(path)
    if "fingerprint" in binding:
        assert binding["fingerprint"] in {
            item for key, item in value.items() if key.endswith("_fingerprint")
        }
    return value


def test_program_012_runtime_implementation_is_exact_and_non_authorizing() -> None:
    implementation = _load(_IMPLEMENTATION_PATH)
    stored_fingerprint = implementation.pop("implementation_fingerprint")
    assert stored_fingerprint == fingerprint(implementation)
    binding = implementation["implementation_binding"]

    assert binding["source_commit"] == "f64a8f33631d0736ae447c7c74ee69f396d85bd1"
    assert binding["source_tree"] == "a82f21c8fbd4c7b26564b7690db1263d98f77cf9"
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

    assert implementation["status"] == "IMPLEMENTED-PROSPECTIVE-NOT-AUTHORIZED"
    assert implementation["supersedes"]["path"] == _V1_IMPLEMENTATION_PATH.as_posix()
    _assert_binding(implementation["supersedes"])
    assert implementation["runtime_contract"]["atomic_fsynced_intent_before_transport"] is True
    assert implementation["runtime_contract"]["cumulative_budget_recovery"] is True
    assert (
        implementation["runtime_contract"]["credential_load_attempt_fsynced_before_access"] is True
    )
    assert implementation["runtime_contract"]["public_low_entropy_private_commitments"] is False
    assert implementation["runtime_contract"]["terminal_recovery_rederives_dataset_identities"]
    assert implementation["runtime_contract"]["terminal_recovery_rederives_private_gate_results"]
    assert implementation["execution_boundary"]["child_authority_present"] is False
    assert implementation["execution_boundary"]["credential_presence_or_values_accessed"] is False
    assert implementation["execution_boundary"]["provider_requests"] == 0
    assert all(value is False for value in implementation["authority"].values())
    _assert_binding(implementation["operation_contract"])
    _assert_binding(implementation["operation_contract_review"])


def _hypergeometric_tail(population: int, successes: int, draws: int, threshold: int) -> float:
    denominator = comb(population, draws)
    return sum(
        comb(successes, selected) * comb(population - successes, draws - selected) / denominator
        for selected in range(threshold, min(successes, draws) + 1)
    )


def test_program_012_proposal_is_exact_protected_and_non_authorizing() -> None:
    proposal = _load(_PROPOSAL_PATH)
    stored_fingerprint = proposal.pop("proposal_fingerprint")
    assert stored_fingerprint == fingerprint(proposal)
    for binding in proposal["bindings"].values():
        _assert_binding(binding)
    superseded = proposal["supersedes"]
    assert superseded["proposals"]["v1"]["path"] == _V1_PROPOSAL_PATH.as_posix()
    assert superseded["proposals"]["v2"]["path"] == _V2_PROPOSAL_PATH.as_posix()
    _assert_binding(superseded["proposals"]["v1"])
    _assert_binding(superseded["proposals"]["v2"])
    assert superseded["prior_provider_requests"] == 0
    assert superseded["prior_market_observations"] == 0

    chronology = proposal["chronology"]
    request = chronology["request_range"]
    start = datetime.combine(date.fromisoformat(request["start"]), time.min, tzinfo=UTC)
    end = datetime.combine(date.fromisoformat(request["end"]), time.max, tzinfo=UTC)
    sessions = expected_sessions(start, end)
    bars = expected_bar_timestamps(start, end, Timeframe.FIVE_MINUTES)
    bars_by_session = Counter(timestamp.date() for timestamp in bars)
    early_closes = tuple(
        session.isoformat() for session in sessions if bars_by_session[session] == 42
    )

    assert len(sessions) == request["session_count"] == 1_386
    assert Counter(bars_by_session.values()) == {78: 1_374, 42: 12}
    assert len(bars) * 13 == request["expected_coordinates"] == 1_399_788
    assert early_closes == tuple(chronology["early_close_sessions"])
    assert sum(block["sessions"] for block in chronology["structural_blocks"]) == 1_386
    assert sum(block["expected_coordinates"] for block in chronology["structural_blocks"]) == (
        1_399_788
    )

    protected = _load(Path(proposal["bindings"]["protected_chronology"]["path"]))
    request_start = date.fromisoformat(request["start"])
    request_end = date.fromisoformat(request["end"])
    assert all(
        request_end < date.fromisoformat(item["start"])
        or request_start > date.fromisoformat(item["end"])
        for item in protected["ranges"]
    )
    assert chronology["protected_overlap"]["request_session_count"] == 0
    assert chronology["protected_overlap"]["protected_sessions_enter_any_denominator"] is False

    budget = proposal["transport_budgets"]
    assert budget["nominal_complete_requests_and_responses"] == 1_374 * 2 + 12 == 2_760
    assert budget["maximum_requests_and_responses"] == 1_386 * 16 == 22_176
    assert budget["automatic_retries"] == budget["parallel_session_chains"] - 1 == 0
    assert budget["credential_loads_per_process_max"] == 1
    assert budget["credential_load_attempt_fsynced_before_access"] is True
    assert budget["unpaired_credential_load_attempt_counts_as_load"] is True
    assert budget["automatic_process_restart_attempts"] == 0
    assert budget["recovery_credential_loads_counted"] is True

    source = proposal["source_contract"]
    assert (
        source["method"],
        source["endpoint"],
        source["feed"],
        source["timeframe"],
        source["adjustment"],
        source["sort"],
        source["limit"],
        source["asof"],
    ) == (
        "GET",
        "https://data.alpaca.markets/v2/stocks/bars",
        "sip",
        "5Min",
        "raw",
        "asc",
        1_000,
        "2026-07-31",
    )
    assert source["symbols"] == [
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
    ]
    assert source["provider_adjusted_view_allowed"] is False
    assert source["alternate_provider_allowed"] is False
    assert source["automatic_retries"] == 0

    pagination = proposal["pagination_contract"]
    assert pagination["terminal_condition"] == "next_page_token is null"
    assert pagination["raw_body_fsynced_before_parse_or_continuation"] is True
    assert pagination["maximum_pages_per_session"] == 16
    assert pagination["incomplete_chain_allows_dataset_admission"] is False
    restart = proposal["restart_contract"]
    assert restart["restart_safe_required"] is True
    assert restart["process_recovery_allowed"] is True
    assert restart["automatic_process_restart_attempts"] == 0
    assert restart["exclusive_private_root_lock_required"] is True
    assert "_LockedRoot" in restart["lock_implementation"]
    assert restart["concurrent_owner_action"] == "BLOCK-BEFORE-CREDENTIAL-ACCESS-OR-TRANSPORT"
    assert restart["request_intent_create_only_and_atomic"] is True
    assert restart["request_intent_fsynced_before_transport"] is True
    assert restart["request_intent_binds"] == [
        "active authority fingerprint",
        "source commit",
        "session",
        "page index",
        "request identity",
        "exact private URL including the incoming page token when present",
    ]
    assert restart["request_reissue_allowed"] is False
    assert restart["completed_session_reacquisition_allowed"] is False
    assert restart["transport_without_fsynced_intent"] == "PROHIBITED-BY-RUNTIME-ORDERING"
    assert restart["intent_without_completed_page"] == (
        "AMBIGUOUS-SEND-TERMINAL-FAIL-CONSUMED-NO-RETRY"
    )
    assert restart["raw_body_without_response_receipt"] == (
        "AMBIGUOUS-PERSISTENCE-TERMINAL-FAIL-CONSUMED-NO-RETRY"
    )
    assert restart["changed_or_unverifiable_checkpoint"] == "FAIL-CONSUMED-NO-RETRY"
    assert restart["credential_loads_per_process_max"] == 1
    assert restart["credential_load_attempt_fsynced_before_access"] is True
    assert restart["credential_load_receipt_fsynced_after_access"] is True
    assert restart["unpaired_credential_load_attempt_action"] == (
        "COUNT-AS-ONE-LOAD-CONSERVATIVELY"
    )
    assert restart["credential_values_persisted_for_recovery"] is False
    assert restart["recovery_credential_loads_counted_in_terminal_evidence"] is True
    assert restart["transport_retries"] == 0
    evidence = proposal["evidence_contract"]
    assert evidence["create_only_raw_pages"] is True
    assert evidence["create_only_request_intents"] is True
    assert evidence["create_only_response_receipts"] is True

    missingness = proposal["missingness_policy"]
    loss = missingness["global_loss_limit"]
    assert loss["overall_excluded_full_session_count_max"] == floor(1_354 * 7 / 1_499) == 6
    assert loss["unexpected_excluded_full_session_count_max"] == (
        6 - missingness["fixed_quarantine"]["session_count"]
    )
    assert missingness["fixed_quarantine"]["action"] == (
        "Exclude all five sessions even if every coordinate is now present. On those five "
        "sessions only, any missing coordinate outside the exact nine-coordinate incident "
        "inventory fails admission. Missingness on another full session follows the one-slot "
        "unexpected-exclusion policy."
    )
    inventory_contract = missingness["fixed_quarantine"]["coordinate_inventory"]
    incident = _load(Path(proposal["bindings"]["program_002_fixed_quarantine_incident"]["path"]))
    inventory = sorted(
        {
            coordinate
            for segment in incident["completed_exposed_segments"]
            for coordinate in segment.get("synthesized_coordinates", [])
        }
        | set(incident["failed_segment"]["missing_intervals"])
    )
    program_005 = _load(Path(proposal["bindings"]["program_005_policy_precedent"]["path"]))
    assert inventory == program_005["source_qualification"]["known_mdy_coordinates"]
    assert len(inventory) == inventory_contract["required_coordinate_count"] == 9
    assert fingerprint(inventory) == inventory_contract["fingerprint"]
    assert {coordinate.partition("@")[0] for coordinate in inventory} == set(
        inventory_contract["required_symbols"]
    )
    assert (
        sorted({coordinate.partition("@")[2][:10] for coordinate in inventory})
        == (inventory_contract["required_sessions"])
    )
    clock = missingness["fixed_clock_concentration"]
    assert clock["uniform_coordinate_population"] == 1_354 * 78
    assert clock["exact_hypergeometric_tail_probability_at_rejection_count"] == format(
        _hypergeometric_tail(105_612, 1_354, 9, 3), ".12f"
    )
    bias = missingness["spy_mdy_morning_bias_diagnostic"]
    assert bias["tail_size_sessions"] == 339
    assert bias["exact_hypergeometric_tail_probabilities_at_rejection_count"] == {
        "5": format(_hypergeometric_tail(1_354, 339, 5, 5), ".12f"),
        "6": format(_hypergeometric_tail(1_354, 339, 6, 5), ".12f"),
    }

    canonical = proposal["canonical_data_contract"]
    admission = proposal["structural_admission_contract"]
    assert canonical["raw_prices_changed"] is False
    assert canonical["normalized_volume_materialized_during_program_012"] is False
    assert admission["program_002_admission"] is False
    assert admission["program_002_quote_windows_evaluated"] == 0
    assert admission["historical_final_exposed_fold_claim"] is False
    assert proposal["external_authorization_root"] is None
    assert all(value is False for value in proposal["authority"].values())
    implementation = proposal["implementation_boundary"]
    assert all(
        implementation[key] is False
        for key in (
            "runtime_present",
            "credential_reader_or_presence_check_added",
            "provider_transport_added",
            "private_store_added",
            "authority_activation_added",
            "dataset_admission_runtime_added",
        )
    )
    assert implementation["required_restart_tests"] == [
        "a crash after the fsynced intent but before a complete receipted page terminates "
        "without a second transport call",
        "a new process resumes after a completed nonterminal page, loads credentials once, "
        "records the load, and sends only the recorded continuation request",
        "a crash after credential access but before its receipt leaves an unpaired value-free "
        "attempt that terminal accounting counts as one load",
        "two concurrent recovery processes produce exactly one credential access owner and one "
        "continuation transport call",
    ]
    assert implementation["required_missingness_tests"] == [
        "one isolated policy-compliant nonquarantine full-session loss passes structural admission",
        "one extra missing coordinate on a fixed quarantine session fails structural admission",
        "the exact incident-source union equals the nine-coordinate fingerprint and Program 005 "
        "cross-check",
    ]
    assert implementation["focused_tests_required"] is True
    assert "PLACEHOLDER" not in (_REPOSITORY / _PROPOSAL_PATH).read_text(encoding="utf-8")


def test_program_012_review_binds_finding_free_source_and_grants_no_authority() -> None:
    review = _load(_REVIEW_PATH)
    stored_fingerprint = review.pop("review_fingerprint")
    assert stored_fingerprint == fingerprint(review)
    for binding in review["reviewed_artifacts"].values():
        _assert_binding(binding)

    source = review["reviewed_source"]
    tree = subprocess.run(
        ("git", "-C", str(_REPOSITORY), "rev-parse", f"{source['source_commit']}^{{tree}}"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    diff = subprocess.run(
        (
            "git",
            "-C",
            str(_REPOSITORY),
            "diff",
            "--no-ext-diff",
            source["base_commit"],
            source["source_commit"],
        ),
        check=True,
        capture_output=True,
    ).stdout
    assert tree == source["source_tree"]
    assert hashlib.sha256(diff).hexdigest() == source["diff_sha256"]
    assert review["verdict"] == "PASS"
    assert review["findings"] == []
    assert all(axis["verdict"] == "PASS" for axis in review["review_axes"].values())
    assert review["remediation_history"]["v3_disposition"] == (
        "ALL-PRIOR-FINDINGS-REMEDIATED-BEFORE-EXECUTION"
    )
    assert all(value is False for value in review["authority"].values())
    assert "PLACEHOLDER" not in (_REPOSITORY / _REVIEW_PATH).read_text(encoding="utf-8")
