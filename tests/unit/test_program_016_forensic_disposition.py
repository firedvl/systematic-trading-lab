from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, cast

from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_DISPOSITION = Path("config/research/program-016-predecessor-recovery-forensic-disposition-v1.json")


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
    assert _DISPOSITION.as_posix() in guard.PUBLIC_PROGRAM_JSON
