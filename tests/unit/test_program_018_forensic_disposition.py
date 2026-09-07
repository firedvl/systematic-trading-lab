from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, cast

from pytest import CaptureFixture, MonkeyPatch

from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_DISPOSITION = Path("config/research/program-018-predecessor-recovery-forensic-disposition-v1.json")
_PROPOSAL_V1 = Path(
    "config/research/program-018-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-proposal-v1.json"
)
_PROPOSAL_V2 = Path(
    "config/research/program-018-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-proposal-v2.json"
)
_PROPOSAL = Path(
    "config/research/program-018-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-proposal-v3.json"
)


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_REPOSITORY / path).read_text(encoding="utf-8")))


def test_program_018_forensic_disposition_is_bound_redacted_and_non_authorizing() -> None:
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
    terminal = _load(Path(predecessor["terminal_result"]["path"]))
    terminal_review = _load(Path(predecessor["terminal_review"]["path"]))
    assert predecessor["runtime_source"] == {
        "commit": child["runtime_binding"]["source_commit"],
        "tree": child["runtime_binding"]["source_tree"],
        "implementation_root": child["runtime_binding"]["implementation_root"],
    }
    assert (
        terminal_review["reviewed_public_terminal"]["derived_active_authority_fingerprint"]
        == (terminal["authority_fingerprint"])
    )

    conclusions = disposition["conclusions"]
    assert conclusions["incomplete_checkpoint_kind"] == (
        "COMPLETED-PAGE-THEN-INTENT-ONLY-NEXT-PAGE"
    )
    assert conclusions["partial_session_must_be_discarded_in_full"] is True
    assert conclusions["partial_session_requests_may_not_be_reissued"] is True
    assert conclusions["later_session_or_page_evidence_present"] is False
    assert conclusions["next_independent_session_exists"] is True
    assert conclusions["interruption_cause_established"] is False

    budget = disposition["cumulative_transport_contract"]
    assert budget["maximum_combined_request_intents"] == 22176
    assert budget["consumed_intents_without_response_before_program_018"] == 6
    assert budget["maximum_effective_combined_responses_for_program_018"] == 22170
    assert budget["automatic_retries"] == 0

    runtime = disposition["runtime_requirement"]
    assert runtime["inherit_program_017_bounded_reconstruction_design"] is True
    assert runtime["full_predecessor_validation_required_before_credential_presence"] is True
    assert runtime["full_predecessor_reconstruction_before_every_transport_allowed"] is False
    assert all(value is False for value in disposition["authority"].values())

    spec = importlib.util.spec_from_file_location(
        "program_018_check_secrets", _REPOSITORY / "scripts/check_secrets.py"
    )
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    assert _DISPOSITION.as_posix() in guard.PUBLIC_PROGRAM_JSON


def test_program_018_proposal_is_an_exact_non_authorizing_delta() -> None:
    proposal = _load(_PROPOSAL)
    stored = proposal.pop("proposal_fingerprint")
    assert stored == fingerprint(proposal)
    superseded = proposal["supersedes"]
    assert superseded["path"] == _PROPOSAL_V2.as_posix()
    assert (
        hashlib.sha256((_REPOSITORY / _PROPOSAL_V2).read_bytes()).hexdigest()
        == superseded["sha256"]
    )
    for binding in proposal["predecessor"].values():
        assert (
            hashlib.sha256((_REPOSITORY / binding["path"]).read_bytes()).hexdigest()
            == binding["sha256"]
        )

    inheritance = proposal["exact_inheritance_contract"]
    assert inheritance["all_unlisted_program_017_v5_fields_and_semantics_inherited_exactly"]
    assert len(inheritance["allowed_delta_keys"]) == 8
    assert all(
        value is False
        for key, value in inheritance.items()
        if key.endswith("_changed") or key == "authority_expanded"
    )

    recovery = proposal["recovery_contract"]
    assert len(recovery["predecessor_private_roots_in_lock_order"]) == 6
    assert recovery["partial_session_coordinates_classification"] == (
        "UNOBSERVED-BECAUSE-CHAIN-INCOMPLETE"
    )
    assert recovery["incomplete_program_017_request_reissue_allowed"] is False
    assert (
        recovery["first_program_018_request_private_derivation"][
            "skipped_scheduled_session_allowed"
        ]
        is False
    )

    bounded = proposal["bounded_reconstruction_contract"]
    assert bounded["execution_maximum_full_predecessor_passes"] == 2
    assert bounded["full_predecessor_reconstruction_between_transports"] is False
    boundary = proposal["transport_boundary_contract"]
    assert boundary["all_eight_controls_held_continuously"]
    assert len(boundary["immutable_predecessor_root_and_all_lock_descriptor_metadata_tuple"]) == 8
    assert len(boundary["program_018_mutable_root_stable_identity_tuple"]) == 5
    assert len(boundary["program_018_mutable_root_expected_full_tuple"]) == 8
    assert boundary["root_and_lock_descriptors_opened_with_o_nofollow"]
    assert boundary[
        "program_018_root_expected_full_tuple_refreshed_only_after_authorized_create_only_write_and_parent_fsync"
    ]
    budget = proposal["cumulative_transport_contract"]
    assert budget["maximum_combined_request_intents"] == 22176
    assert budget["consumed_intent_without_response_count"] == 6
    assert budget["maximum_effective_combined_responses"] == 22170
    assert budget["automatic_retries"] == 0
    assert proposal["storage_contract"]["minimum_additional_available_bytes"] == 16 * 1024**3
    private_terminal = proposal["private_terminal_contract"]
    assert "program_018_credential_loads" in private_terminal["exact_top_level_keys"]
    assert "program_018_response_manifest_sha256" in private_terminal["private_evidence_exact_keys"]
    assert private_terminal["result_branches"]["ADMISSION-PASS"]["status"] == (
        "ADMITTED-PROGRAM-018-RAW-STRUCTURAL-PREFIX"
    )
    public_terminal = proposal["public_terminal_contract"]
    assert public_terminal["exact_static_identity_values"]["program_ordinal"] == 18
    assert public_terminal["pass_branch_semantics"]["status"] == (
        "ADMITTED-PROGRAM-018-RAW-STRUCTURAL-PREFIX"
    )
    assert proposal["public_pass_lineage_contract"]["schema_version"] == (
        "program-018-public-raw-structural-prefix-lineage-manifest-v1"
    )
    assert "proposal v3" in proposal["required_next_action"]
    assert all(value is False for value in proposal["authority"].values())


def test_program_018_secret_guard_rejects_private_json(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    spec = importlib.util.spec_from_file_location(
        "program_018_private_check_secrets", _REPOSITORY / "scripts/check_secrets.py"
    )
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    monkeypatch.chdir(tmp_path)
    private = Path("config/research/program-018-private-terminal.json")
    private.parent.mkdir(parents=True)
    private.write_text("{}\n", encoding="utf-8")
    public_paths = [Path(path) for path in guard.PUBLIC_PROGRAM_JSON if "program-018" in path]
    for public in public_paths:
        public.parent.mkdir(parents=True, exist_ok=True)
        public.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(guard, "tracked_files", lambda: [private, *public_paths])

    assert guard.main() == 1
    errors = capsys.readouterr().err
    assert f"{private}:private-market-data-path" in errors
    assert all(str(public) not in errors for public in public_paths)
