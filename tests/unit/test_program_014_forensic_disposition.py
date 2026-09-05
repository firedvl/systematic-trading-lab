from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, cast

from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_DISPOSITION = Path("config/research/program-014-predecessor-recovery-forensic-disposition-v1.json")
_PROPOSAL = Path(
    "config/research/program-014-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-proposal-v1.json"
)


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_REPOSITORY / path).read_text(encoding="utf-8")))


def test_program_014_forensic_disposition_is_exact_redacted_and_non_authorizing() -> None:
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
    assert (
        child_review["reviewed_child_authority"]["sha256"]
        == predecessor["child_authority"]["sha256"]
    )
    assert (
        child_review["reviewed_child_authority"]["fingerprint"]
        == predecessor["child_authority"]["fingerprint"]
    )
    assert predecessor["runtime_source"] == {
        "commit": child["runtime_binding"]["source_commit"],
        "tree": child["runtime_binding"]["source_tree"],
        "implementation_root": child["runtime_binding"]["implementation_root"],
    }
    assert terminal["authority_id"] == predecessor["child_authority"]["child_authority_id"]
    assert terminal["source_commit"] == predecessor["runtime_source"]["commit"]
    assert (
        terminal_review["reviewed_public_terminal"]["authority_fingerprint"]
        == terminal["authority_fingerprint"]
    )
    assert (
        terminal_review["reviewed_public_terminal"]["runtime_source_commit"]
        == predecessor["runtime_source"]["commit"]
    )

    conclusions = disposition["conclusions"]
    assert conclusions["completed_evidence_is_exact_whole_session_prefix"] is True
    assert conclusions["incomplete_checkpoint_kind"] == "INTENT-ONLY-PAGE-FRONTIER"
    assert conclusions["later_session_or_page_evidence_present"] is False
    assert conclusions["structural_admission_evaluated"] is False
    assert conclusions["dataset_published"] is False
    assert conclusions["strategy_work_occurred"] is False
    budget = disposition["cumulative_transport_contract"]
    assert budget["maximum_combined_request_intents"] == 22176
    assert budget["consumed_intents_without_response_before_program_014"] == 2
    assert budget["maximum_effective_combined_responses_for_program_014"] == 22174
    assert budget["automatic_retries"] == 0
    prospective = disposition["prospective_disposition"]
    assert prospective["successor_launch_must_prove_no_automatic_restart_or_relaunch"] is True
    assert (
        prospective["launchctl_submit_allowed_without_verified_disabled_restart_semantics"] is False
    )
    assert all(value is False for value in disposition["authority"].values())


def test_program_014_proposal_is_bound_cumulative_nonrestarting_and_non_authorizing() -> None:
    proposal = _load(_PROPOSAL)
    stored = proposal.pop("proposal_fingerprint")
    assert stored == fingerprint(proposal)

    predecessor = proposal["predecessor"]
    for binding in predecessor.values():
        assert (
            hashlib.sha256((_REPOSITORY / binding["path"]).read_bytes()).hexdigest()
            == binding["sha256"]
        )
    forensic = predecessor["redacted_private_forensic_disposition"]
    disposition = _load(Path(forensic["path"]))
    assert forensic["fingerprint"] == disposition["forensic_disposition_fingerprint"]
    scientific_contract = predecessor["program_013_scientific_contract"]
    contract = _load(Path(scientific_contract["path"]))
    assert scientific_contract["fingerprint"] == contract["proposal_fingerprint"]

    inheritance = proposal["inheritance_contract"]
    assert inheritance["base_contract"] == "program_013_scientific_contract"
    assert inheritance["fields_inherited_exactly_without_change"] == [
        "source_contract",
        "chronology",
        "pagination_contract",
        "scientific_contract",
        "structural_admission",
        "evidence_contract",
        "credential secrecy and one-load semantics",
        "raw-first persistence ordering",
        "protected firewall",
        "privacy assertions",
        "no-strategy boundary",
    ]
    for key in (
        "program_012_history_mutation_allowed",
        "program_013_history_mutation_allowed",
        "observed_result_gate_changes_allowed",
        "source_or_chronology_changes_allowed",
        "missingness_or_admission_changes_allowed",
    ):
        assert inheritance[key] is False

    recovery = proposal["recovery_contract"]
    assert recovery["program_012_private_evidence_access"] == "READ-ONLY"
    assert recovery["program_013_private_evidence_access"] == "READ-ONLY"
    assert (
        len(
            {
                recovery["program_012_private_root"],
                recovery["program_013_private_root"],
                recovery["program_014_private_root"],
            }
        )
        == 3
    )
    assert recovery["completed_predecessor_pages_are_never_requested_again"] is True
    assert recovery["incomplete_program_013_session_or_page_reuse_allowed"] is False

    budgets = proposal["cumulative_transport_and_working_space_budgets"]
    assert budgets["maximum_combined_request_intents"] == 22176
    assert budgets["consumed_intent_without_response_count"] == 2
    assert budgets["maximum_effective_combined_responses"] == 22174
    assert budgets["automatic_retries"] == 0

    launch = proposal["restart_and_launch_contract"]
    for key in (
        "automatic_restart",
        "automatic_relaunch",
        "launchctl_submit_allowed",
        "scheduler_keepalive_allowed",
        "scheduler_restart_on_exit_allowed",
        "process_manager_retry_allowed",
    ):
        assert launch[key] is False
    assert launch["single_nonrestarting_process_required"] is True
    assert all(value is False for value in proposal["authority"].values())


def test_secret_guard_reserves_only_planned_program_014_public_artifacts(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    spec = importlib.util.spec_from_file_location(
        "program_014_check_secrets", _REPOSITORY / "scripts/check_secrets.py"
    )
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    monkeypatch.chdir(tmp_path)
    reserved = (
        _DISPOSITION,
        Path(
            "config/research/program-014-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-proposal-v1.json"
        ),
        Path(
            "config/research/program-014-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-independent-review-v1.json"
        ),
        Path("config/research/program-014-exposed-prefix-runtime-implementation-v1.json"),
        Path(
            "config/research/program-014-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-child-authority-v1.json"
        ),
        Path(
            "config/research/program-014-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-child-authority-independent-review-v1.json"
        ),
        Path(
            "config/research/program-014-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-terminal-result-v1.json"
        ),
        Path(
            "config/research/program-014-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-terminal-result-independent-review-v1.json"
        ),
    )
    private = Path("config/research/program-014-market-observations.json")
    for path in (*reserved, private):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(guard, "tracked_files", lambda: [*reserved, private])

    assert guard.main() == 1
    errors = capsys.readouterr().err
    for path in reserved:
        assert path.as_posix() in guard.PUBLIC_PROGRAM_JSON
        assert str(path) not in errors
    assert f"{private}:private-market-data-path" in errors


def test_secret_guard_rejects_program_014_credentials_in_public_json_and_shell(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    spec = importlib.util.spec_from_file_location(
        "program_014_check_secrets_credentials", _REPOSITORY / "scripts/check_secrets.py"
    )
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    monkeypatch.chdir(tmp_path)

    public = _PROPOSAL
    shell = Path("program-014-credentials.env")
    public.parent.mkdir(parents=True, exist_ok=True)
    public.write_text(
        '{\n  "PROGRAM_014_ALPACA_API_KEY_ID":\n  "synthetic-value"\n}\n',
        encoding="utf-8",
    )
    shell.write_text("PROGRAM_014_ALPACA_API_SECRET_KEY=synthetic-value\n", encoding="utf-8")
    monkeypatch.setattr(guard, "tracked_files", lambda: [public, shell])

    assert guard.main() == 1
    errors = capsys.readouterr().err
    assert f"{public}:2" in errors
    assert f"{shell}:1" in errors
