from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, cast

from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_DISPOSITION = Path("config/research/program-018-predecessor-recovery-forensic-disposition-v1.json")


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
