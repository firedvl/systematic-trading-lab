from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, cast

from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_DISPOSITION = Path("config/research/program-017-predecessor-recovery-forensic-disposition-v1.json")
_PROPOSAL_V1 = Path(
    "config/research/program-017-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-proposal-v1.json"
)
_PROPOSAL = Path(
    "config/research/program-017-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-proposal-v2.json"
)


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_REPOSITORY / path).read_text(encoding="utf-8")))


def test_program_017_forensic_disposition_is_bound_redacted_and_non_authorizing() -> None:
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
        == terminal["authority_fingerprint"]
    )

    conclusions = disposition["conclusions"]
    assert conclusions["incomplete_checkpoint_kind"] == (
        "COMPLETED-PAGE-THEN-INTENT-ONLY-NEXT-PAGE"
    )
    assert conclusions["partial_session_must_be_discarded_in_full"] is True
    assert conclusions["partial_session_requests_may_not_be_reissued"] is True
    assert conclusions["later_session_or_page_evidence_present"] is False
    assert conclusions["performance_root_cause"] == (
        "FULL-PREDECESSOR-RECONSTRUCTION-BEFORE-EVERY-TRANSPORT"
    )

    budget = disposition["cumulative_transport_contract"]
    assert budget["maximum_combined_request_intents"] == 22176
    assert budget["consumed_intents_without_response_before_program_017"] == 5
    assert budget["maximum_effective_combined_responses_for_program_017"] == 22171
    assert budget["automatic_retries"] == 0

    remediation = disposition["performance_remediation_requirement"]
    assert remediation["full_predecessor_validation_required_before_credential_presence"] is True
    assert remediation["full_predecessor_reconstruction_before_every_transport_allowed"] is False
    assert remediation["all_predecessor_and_git_controls_held_through_terminal_fsync"] is True
    assert all(value is False for value in disposition["authority"].values())

    spec = importlib.util.spec_from_file_location(
        "program_017_check_secrets", _REPOSITORY / "scripts/check_secrets.py"
    )
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    reserved = {path for path in guard.PUBLIC_PROGRAM_JSON if "program-017" in path}
    assert {_DISPOSITION.as_posix(), _PROPOSAL_V1.as_posix(), _PROPOSAL.as_posix()} <= reserved


def test_program_017_proposal_is_single_reconstruction_and_non_authorizing() -> None:
    proposal = _load(_PROPOSAL)
    stored = proposal.pop("proposal_fingerprint")
    assert stored == fingerprint(proposal)
    superseded = proposal["supersedes"]
    assert superseded["path"] == _PROPOSAL_V1.as_posix()
    assert (
        hashlib.sha256((_REPOSITORY / _PROPOSAL_V1).read_bytes()).hexdigest()
        == superseded["sha256"]
    )
    for binding in proposal["predecessor"].values():
        assert (
            hashlib.sha256((_REPOSITORY / binding["path"]).read_bytes()).hexdigest()
            == binding["sha256"]
        )

    recovery = proposal["recovery_contract"]
    assert recovery["incomplete_program_016_session_or_page_reuse_allowed"] is False
    assert recovery["incomplete_program_016_request_reissue_allowed"] is False
    assert recovery["first_program_017_request"] == (
        "NEXT-INDEPENDENT-SESSION-AFTER-DISCARDED-PARTIAL-SESSION"
    )

    reconstruction = proposal["bounded_reconstruction_contract"]
    assert reconstruction["execution_precredential_full_predecessor_validation_passes"] == 1
    assert reconstruction["execution_post_transport_final_projection_passes"] == 1
    assert reconstruction["execution_maximum_full_predecessor_passes"] == 2
    assert reconstruction["full_predecessor_reconstruction_between_transports"] is False
    assert reconstruction["separate_predecessor_spool_allowed"] is False

    boundary = proposal["transport_boundary_contract"]
    assert boundary["fixed_size_metadata_checks_only"] is True
    assert boundary["predecessor_content_reparse_forbidden"] is True
    assert boundary["any_identity_or_metadata_drift_fails_before_transport_or_closeout"] is True
    assert boundary["root_and_lock_descriptors_opened_with_o_nofollow"] is True
    assert len(boundary["descriptor_metadata_tuple"]) == 8

    budgets = proposal["cumulative_transport_contract"]
    assert budgets["maximum_combined_request_intents"] == 22176
    assert budgets["maximum_effective_combined_responses"] == 22171
    assert budgets["consumed_intent_without_response_count"] == 5
    assert budgets["automatic_retries"] == 0
    storage = proposal["storage_contract"]
    assert storage["minimum_additional_available_bytes"] == 16 * 1024**3
    assert storage["canonical_projection_hard_cap_enforced_while_writing"] is True
    assert len(proposal["lock_and_launch_contract"]["control_acquisition_order"]) == 7
    assert set(proposal["private_terminal_contract"]["exact_top_level_keys"]) >= {
        "program_017_credential_loads",
        "strategy_calculations",
        "strategy_returns",
    }
    assert proposal["public_terminal_contract"]["byte_exact_canonical_reconstruction_required"]
    assert proposal["credential_contract"][
        "process_global_latch_consumed_if_attempt_reservation_or_parsing_fails"
    ]
    assert proposal["runtime_and_child_topology_contract"][
        "runtime_source_must_merge_before_child_creation"
    ]
    assert all(value is False for value in proposal["authority"].values())
