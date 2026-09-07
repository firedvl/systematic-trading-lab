from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, cast

from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_DISPOSITION = Path("config/research/program-017-predecessor-recovery-forensic-disposition-v1.json")


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
    assert len(reserved) == 8
    assert _DISPOSITION.as_posix() in reserved
