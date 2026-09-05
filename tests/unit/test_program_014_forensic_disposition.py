from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, cast

from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_DISPOSITION = Path("config/research/program-014-predecessor-recovery-forensic-disposition-v1.json")
_PROPOSAL_V1 = Path(
    "config/research/program-014-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-proposal-v1.json"
)
_PROPOSAL_V2 = Path(
    "config/research/program-014-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-proposal-v2.json"
)
_PROPOSAL = Path(
    "config/research/program-014-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-proposal-v3.json"
)
_TERMINAL = Path(
    "config/research/program-014-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-terminal-result-v1.json"
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

    supersedes = proposal["supersedes"]
    assert supersedes["path"] == _PROPOSAL_V2.as_posix()
    assert (
        hashlib.sha256((_REPOSITORY / supersedes["path"]).read_bytes()).hexdigest()
        == supersedes["sha256"]
    )
    correction = proposal["correction_basis"]
    assert (
        hashlib.sha256((_REPOSITORY / correction["path"]).read_bytes()).hexdigest()
        == correction["sha256"]
    )
    review = _load(Path(correction["path"]))
    stored_review_fingerprint = review.pop("review_fingerprint")
    assert correction["fingerprint"] == stored_review_fingerprint
    assert stored_review_fingerprint == fingerprint(review)
    assert correction["resolved_findings"] == ["P014-V2-DESIGN-001", "P014-V2-SECURITY-001"]

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

    private_terminal = proposal["private_terminal_contract"]
    assert private_terminal["exact_top_level_and_private_evidence_key_set_equality_required"]
    assert private_terminal["missing_or_unknown_top_level_or_private_evidence_keys_rejected"]
    assert private_terminal["exact_static_values"] == {
        "schema_version": "program-014-private-terminal-v1",
        "program_id": "multi-hour-sector-etf-research-013",
        "public_terminal_path": _TERMINAL.as_posix(),
        "scientific_use_consumed": True,
        "automatic_retries": 0,
        "credentials_stored": False,
        "program_002_admission": False,
        "strategy_calculations": 0,
        "strategy_returns": 0,
    }
    for key in ("strategy_calculations", "strategy_returns"):
        assert type(private_terminal["exact_static_values"][key]) is int
        assert private_terminal["exact_integer_zero_fields"][key] == {
            "required_value": 0,
            "python_type_predicate": "type(value) is int",
        }

    public_terminal = proposal["public_terminal_contract"]
    assert public_terminal["exact_top_level_and_nested_key_set_equality_required"]
    assert public_terminal["missing_or_unknown_top_level_or_nested_keys_rejected"]
    assert public_terminal[
        "observed_at_is_the_sole_public_timestamp_and_records_terminal_closeout_only"
    ]
    assert all(
        value is False for value in public_terminal["disabled_authority_exact_value"].values()
    )
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
        _PROPOSAL_V1,
        _PROPOSAL_V2,
        _PROPOSAL,
        Path(
            "config/research/program-014-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-independent-review-v1.json"
        ),
        Path(
            "config/research/program-014-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-independent-review-v2.json"
        ),
        Path(
            "config/research/program-014-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-independent-review-v3.json"
        ),
        Path("config/research/program-014-exposed-prefix-runtime-implementation-v1.json"),
        Path(
            "config/research/program-014-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-child-authority-v1.json"
        ),
        Path(
            "config/research/program-014-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-child-authority-independent-review-v1.json"
        ),
        _TERMINAL,
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


def test_secret_guard_rejects_escaped_credential_keys_in_json_and_jsonl(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    spec = importlib.util.spec_from_file_location(
        "program_014_check_secrets_escaped_credentials",
        _REPOSITORY / "scripts/check_secrets.py",
    )
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    monkeypatch.chdir(tmp_path)

    public = _PROPOSAL
    records = Path("credential-keys.jsonl")
    public.parent.mkdir(parents=True, exist_ok=True)
    public.write_text(
        '{"nested":{"PROGRAM\\u005f014_ALPACA_API_KEY_ID":"synthetic-value"}}\n',
        encoding="utf-8",
    )
    records.write_text(
        '\n{"items":[{"PROGRAM\\u005f014_ALPACA_API_SECRET_KEY":"synthetic-value"}]}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(guard, "tracked_files", lambda: [public, records])

    assert guard.main() == 1
    errors = capsys.readouterr().err
    assert f"{public}:1" in errors
    assert f"{records}:2" in errors
