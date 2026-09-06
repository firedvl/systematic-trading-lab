from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, cast

from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_DISPOSITION = Path("config/research/program-016-predecessor-recovery-forensic-disposition-v1.json")
_PROPOSAL = Path(
    "config/research/program-016-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-proposal-v1.json"
)
_REVIEW = Path(
    "config/research/program-016-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-independent-review-v1.json"
)


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_REPOSITORY / path).read_text(encoding="utf-8")))


def test_program_016_forensic_disposition_is_bound_redacted_and_non_authorizing() -> None:
    disposition = _load(_DISPOSITION)
    stored = disposition.pop("forensic_disposition_fingerprint")
    assert stored == fingerprint(disposition)

    predecessor = disposition["predecessor"]
    for name in (
        "scientific_contract",
        "scientific_contract_review",
        "runtime_implementation",
        "child_authority",
        "child_authority_review",
        "terminal_result",
        "terminal_review",
    ):
        binding = predecessor[name]
        assert (
            hashlib.sha256((_REPOSITORY / binding["path"]).read_bytes()).hexdigest()
            == binding["sha256"]
        )

    child = _load(Path(predecessor["child_authority"]["path"]))
    child_review = _load(Path(predecessor["child_authority_review"]["path"]))
    terminal = _load(Path(predecessor["terminal_result"]["path"]))
    terminal_review = _load(Path(predecessor["terminal_review"]["path"]))
    assert predecessor["child_authority"]["fingerprint"] == child["child_authority_fingerprint"]
    assert (
        predecessor["child_authority_review"]["fingerprint"] == child_review["review_fingerprint"]
    )
    assert predecessor["runtime_source"] == {
        "commit": child["runtime_binding"]["source_commit"],
        "tree": child["runtime_binding"]["source_tree"],
        "implementation_root": child["runtime_binding"]["implementation_root"],
    }
    assert (
        terminal_review["reviewed_public_terminal"]["derived_active_authority_fingerprint"]
        == (terminal["authority_fingerprint"])
    )

    assert disposition["conclusions"]["incomplete_checkpoint_kind"] == ("INTENT-ONLY-PAGE-FRONTIER")
    assert disposition["conclusions"]["later_session_or_page_evidence_present"] is False
    budget = disposition["cumulative_transport_contract"]
    assert budget["maximum_combined_request_intents"] == 22176
    assert budget["consumed_intents_without_response_before_program_016"] == 4
    assert budget["maximum_effective_combined_responses_for_program_016"] == 22172
    assert budget["automatic_retries"] == 0
    assert all(value is False for value in disposition["authority"].values())

    spec = importlib.util.spec_from_file_location(
        "program_016_check_secrets", _REPOSITORY / "scripts/check_secrets.py"
    )
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    reserved = {path for path in guard.PUBLIC_PROGRAM_JSON if "program-016" in path}
    assert len(reserved) == 8
    assert {_DISPOSITION.as_posix(), _PROPOSAL.as_posix()} <= reserved


def test_program_016_proposal_is_cumulative_nonrestarting_and_non_authorizing() -> None:
    proposal = _load(_PROPOSAL)
    stored = proposal.pop("proposal_fingerprint")
    assert stored == fingerprint(proposal)

    for binding in proposal["predecessor"].values():
        assert (
            hashlib.sha256((_REPOSITORY / binding["path"]).read_bytes()).hexdigest()
            == binding["sha256"]
        )
    forensic = proposal["predecessor"]["redacted_private_forensic_disposition"]
    assert (
        forensic["fingerprint"] == _load(Path(forensic["path"]))["forensic_disposition_fingerprint"]
    )

    inheritance = proposal["inheritance_contract"]
    assert inheritance["base_contract"] == "program_015_scientific_contract"
    for ordinal in (12, 13, 14, 15):
        assert inheritance[f"program_{ordinal:03d}_history_mutation_allowed"] is False

    recovery = proposal["recovery_contract"]
    roots = {recovery[f"program_{ordinal:03d}_private_root"] for ordinal in range(12, 17)}
    assert len(roots) == 5
    for ordinal in (12, 13, 14, 15):
        assert recovery[f"program_{ordinal:03d}_private_evidence_access"] == "READ-ONLY"
    assert recovery["completed_predecessor_pages_are_never_requested_again"] is True
    assert recovery["incomplete_program_015_session_or_page_reuse_allowed"] is False
    assert recovery["frontier_request_under_program_016_max"] == 1
    assert recovery["program_016_request_reissue_allowed"] is False

    credentials = proposal["credential_contract"]
    assert credentials["standalone_callable_credential_readers_allowed"] is False
    assert credentials["prohibited_reader_scopes"] == ["module", "class", "static", "instance"]
    assert credentials["credential_parsing_location"] == (
        "INLINE-ONLY-IN-LOCK-BOUND-LOADER-OPERATION"
    )
    assert credentials["credential_attempt_create_only_fsynced_before_environment_access"] is True
    assert credentials["terminal_replay_and_recovery_paths_must_not_access_credential_environment"]

    budgets = proposal["cumulative_transport_and_working_space_budgets"]
    assert budgets["maximum_combined_request_intents"] == 22176
    assert budgets["maximum_effective_combined_responses"] == 22172
    assert budgets["consumed_intent_without_response_count"] == 4
    assert budgets["automatic_retries"] == 0

    launch = proposal["restart_and_launch_contract"]
    assert launch["control_acquisition_order"][:5] == [
        "Program 016 exclusive lock",
        "Program 015 read-only shared lock",
        "Program 014 read-only shared lock",
        "Program 013 read-only shared lock",
        "Program 012 read-only shared lock",
    ]
    for key in (
        "automatic_restart",
        "automatic_relaunch",
        "launchctl_submit_allowed",
        "scheduler_keepalive_allowed",
        "scheduler_restart_on_exit_allowed",
        "process_manager_retry_allowed",
    ):
        assert launch[key] is False

    private_terminal = proposal["private_terminal_contract"]
    assert private_terminal["exact_static_values"]["schema_version"] == (
        "program-016-private-terminal-v1"
    )
    assert type(private_terminal["exact_static_values"]["strategy_calculations"]) is int
    assert private_terminal["exact_static_values"]["strategy_calculations"] == 0
    public_terminal = proposal["public_terminal_contract"]
    assert public_terminal["exact_static_identity_values"]["program_ordinal"] == 16
    assert public_terminal["pass_branch_semantics"]["status"] == (
        "ADMITTED-PROGRAM-016-RAW-STRUCTURAL-PREFIX"
    )
    assert all(value is False for value in proposal["authority"].values())


def test_program_016_proposal_review_is_bound_and_finding_free() -> None:
    review = _load(_REVIEW)
    stored = review.pop("review_fingerprint")
    assert stored == fingerprint(review)
    assert review["reviewed_source_commit"] == "699e175f269763e974bdbd9f5d319b2e094bcb7c"
    assert review["reviewed_source_tree"] == "0526c8c33677a4ad1e5b048b6cb6826fc039f774"
    binding = review["reviewed_proposal"]
    assert (
        hashlib.sha256((_REPOSITORY / binding["path"]).read_bytes()).hexdigest()
        == binding["sha256"]
    )
    assert binding["fingerprint"] == _load(Path(binding["path"]))["proposal_fingerprint"]
    assert review["verdict"] == "PASS"
    assert review["findings"] == []
    assert all(result["verdict"] == "PASS" for result in review["challenge_results"])
    assert all(value is False for value in review["authority"].values())
