from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, cast

from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_DISPOSITION = Path("config/research/program-015-predecessor-recovery-forensic-disposition-v1.json")
_PROPOSAL_V1 = Path(
    "config/research/program-015-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-proposal-v1.json"
)
_PROPOSAL = Path(
    "config/research/program-015-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-proposal-v2.json"
)
_FAILED_REVIEW = Path(
    "config/research/program-015-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-independent-review-v1.json"
)
_REVIEW = Path(
    "config/research/program-015-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-independent-review-v2.json"
)


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_REPOSITORY / path).read_text(encoding="utf-8")))


def test_program_015_forensic_disposition_binds_terminal_predecessor() -> None:
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
    assert predecessor["child_authority"]["child_authority_id"] == child["child_authority_id"]
    assert predecessor["child_authority"]["fingerprint"] == child["child_authority_fingerprint"]
    assert predecessor["child_authority_review"]["review_id"] == child_review["review_id"]
    assert (
        predecessor["child_authority_review"]["fingerprint"] == child_review["review_fingerprint"]
    )
    assert predecessor["runtime_source"] == {
        "commit": child["runtime_binding"]["source_commit"],
        "tree": child["runtime_binding"]["source_tree"],
        "implementation_root": child["runtime_binding"]["implementation_root"],
    }
    assert terminal["authority_id"] == child["child_authority_id"]
    assert terminal["source_commit"] == predecessor["runtime_source"]["commit"]
    assert (
        terminal_review["reviewed_public_terminal"]["authority_fingerprint"]
        == terminal["authority_fingerprint"]
    )

    conclusions = disposition["conclusions"]
    assert conclusions["completed_evidence_is_exact_whole_session_prefix"] is True
    assert conclusions["incomplete_checkpoint_kind"] == "INTENT-ONLY-PAGE-FRONTIER"
    assert conclusions["frontier_body_retained"] is False
    assert conclusions["frontier_response_receipt_retained"] is False
    assert conclusions["later_session_or_page_evidence_present"] is False
    assert conclusions["program_014_zero_reissue_rule_followed"] is True
    budget = disposition["cumulative_transport_contract"]
    assert budget["maximum_combined_request_intents"] == 22176
    assert budget["consumed_intents_without_response_before_program_015"] == 3
    assert budget["maximum_effective_combined_responses_for_program_015"] == 22173
    assert budget["automatic_retries"] == 0
    assert all(value is False for value in disposition["authority"].values())


def test_program_015_proposal_is_cumulative_nonrestarting_and_non_authorizing() -> None:
    proposal = _load(_PROPOSAL)
    stored = proposal.pop("proposal_fingerprint")
    assert stored == fingerprint(proposal)

    supersedes = proposal["supersedes"]
    assert supersedes["path"] == _PROPOSAL_V1.as_posix()
    assert (
        hashlib.sha256((_REPOSITORY / _PROPOSAL_V1).read_bytes()).hexdigest()
        == supersedes["sha256"]
    )
    assert supersedes["fingerprint"] == _load(_PROPOSAL_V1)["proposal_fingerprint"]
    correction = proposal["correction_basis"]
    assert correction["path"] == _FAILED_REVIEW.as_posix()
    assert (
        hashlib.sha256((_REPOSITORY / _FAILED_REVIEW).read_bytes()).hexdigest()
        == correction["sha256"]
    )
    failed_review = _load(_FAILED_REVIEW)
    assert correction["fingerprint"] == failed_review["review_fingerprint"]
    assert correction["resolved_findings"] == ["P015-V1-SECURITY-001"]

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
    assert inheritance["base_contract"] == "program_014_scientific_contract"
    for ordinal in (12, 13, 14):
        assert inheritance[f"program_{ordinal:03d}_history_mutation_allowed"] is False

    recovery = proposal["recovery_contract"]
    roots = {recovery[f"program_{ordinal:03d}_private_root"] for ordinal in (12, 13, 14, 15)}
    assert len(roots) == 4
    for ordinal in (12, 13, 14):
        assert recovery[f"program_{ordinal:03d}_private_evidence_access"] == "READ-ONLY"
    assert recovery["completed_predecessor_pages_are_never_requested_again"] is True
    assert recovery["incomplete_program_014_session_or_page_reuse_allowed"] is False
    assert recovery["frontier_request_under_program_015_max"] == 1
    assert recovery["program_015_request_reissue_allowed"] is False

    credentials = proposal["credential_contract"]
    assert credentials["standalone_callable_credential_readers_allowed"] is False
    assert credentials["prohibited_reader_scopes"] == ["module", "class", "static", "instance"]
    assert credentials["credential_parsing_location"] == (
        "INLINE-ONLY-IN-LOCK-BOUND-LOADER-OPERATION"
    )
    for key in (
        "launcher_revalidated_immediately_before_credential_attempt",
        "credential_attempt_create_only_fsynced_before_environment_access",
        "credential_attempt_binds_authority_source_and_predecessor_identity",
        "process_global_credential_latch_consumed_before_environment_access",
        "process_global_credential_latch_consumed_if_attempt_reservation_fails",
        "process_global_credential_latch_consumed_if_parsing_fails",
        "credential_failure_receipt_fsynced_before_error_propagation",
        "credential_success_receipt_fsynced_before_client_construction",
        "credential_success_receipt_fsynced_before_transport",
        "terminal_replay_and_recovery_paths_must_not_access_credential_environment",
        "ast_and_api_absence_regression_required",
        "forbidden_environment_terminal_replay_and_recovery_regressions_required",
    ):
        assert credentials[key] is True

    budgets = proposal["cumulative_transport_and_working_space_budgets"]
    assert budgets["maximum_combined_request_intents"] == 22176
    assert budgets["maximum_effective_combined_responses"] == 22173
    assert budgets["consumed_intent_without_response_count"] == 3
    assert budgets["automatic_retries"] == 0

    launch = proposal["restart_and_launch_contract"]
    assert launch["control_acquisition_order"][:4] == [
        "Program 015 exclusive lock",
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
    static = private_terminal["exact_static_values"]
    assert static["schema_version"] == "program-015-private-terminal-v1"
    assert static["program_id"] == "multi-hour-sector-etf-research-014"
    assert type(static["strategy_calculations"]) is int and static["strategy_calculations"] == 0
    assert type(static["strategy_returns"]) is int and static["strategy_returns"] == 0
    public_terminal = proposal["public_terminal_contract"]
    assert public_terminal["exact_static_identity_values"]["program_ordinal"] == 15
    assert public_terminal["pass_branch_semantics"]["status"] == (
        "ADMITTED-PROGRAM-015-RAW-STRUCTURAL-PREFIX"
    )
    assert all(
        value is False for value in public_terminal["disabled_authority_exact_value"].values()
    )
    assert all(value is False for value in proposal["authority"].values())


def test_secret_guard_reserves_program_015_public_artifacts(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    spec = importlib.util.spec_from_file_location(
        "program_015_check_secrets", _REPOSITORY / "scripts/check_secrets.py"
    )
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    monkeypatch.chdir(tmp_path)
    reserved = tuple(Path(path) for path in guard.PUBLIC_PROGRAM_JSON if "program-015" in path)
    assert len(reserved) == 10
    private = Path("config/research/program-015-market-observations.json")
    for path in (*reserved, private):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(guard, "tracked_files", lambda: [*reserved, private])

    assert guard.main() == 1
    errors = capsys.readouterr().err
    assert all(path.as_posix() in guard.PUBLIC_PROGRAM_JSON for path in reserved)
    assert all(str(path) not in errors for path in reserved)
    assert f"{private}:private-market-data-path" in errors


def test_program_015_v2_review_is_finding_free_bound_and_non_authorizing() -> None:
    review = _load(_REVIEW)
    stored = review.pop("review_fingerprint")
    assert stored == fingerprint(review)
    assert review["reviewed_source_commit"] == "c1084e2aa2f20230e2c1c03c0903a73be4e29d2c"
    assert review["verdict"] == "PASS"
    assert review["findings"] == []
    for name in ("reviewed_proposal", "reviewed_failed_review"):
        binding = review[name]
        assert (
            hashlib.sha256((_REPOSITORY / binding["path"]).read_bytes()).hexdigest()
            == binding["sha256"]
        )
    assert review["reviewed_proposal"]["fingerprint"] == _load(_PROPOSAL)["proposal_fingerprint"]
    assert (
        review["reviewed_failed_review"]["fingerprint"]
        == _load(_FAILED_REVIEW)["review_fingerprint"]
    )
    assert review["design_review_result"]["verdict"] == "PASS"
    assert review["security_review_result"]["verdict"] == "PASS"
    assert review["security_review_result"]["resolved_finding"] == "P015-V1-SECURITY-001"
    assert all(value is False for value in review["authority"].values())
