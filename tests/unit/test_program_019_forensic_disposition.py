import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

from pytest import CaptureFixture, MonkeyPatch

from systematic_trading_lab.fingerprints import fingerprint

ROOT = Path(__file__).resolve().parents[2]
PATH = Path("config/research/program-019-predecessor-recovery-forensic-disposition-v1.json")
PROPOSAL = Path(
    "config/research/program-019-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-proposal-v2.json"
)
PROPOSAL_V1 = Path(
    "config/research/program-019-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-proposal-v1.json"
)
REVIEW = Path(
    "config/research/program-019-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-independent-review-v1.json"
)


def _changed_leaves(left: object, right: object, path: str = "") -> dict[str, list[object]]:
    if type(left) is not type(right):
        return {path: [left, right]}
    if isinstance(left, dict) and isinstance(right, dict):
        changed: dict[str, list[object]] = {}
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}" if path else key
            if key not in left:
                changed[child] = [None, right[key]]
            elif key not in right:
                changed[child] = [left[key], None]
            else:
                changed.update(_changed_leaves(left[key], right[key], child))
        return changed
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return {path: [left, right]}
        changed = {}
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            changed.update(_changed_leaves(left_item, right_item, f"{path}[{index}]"))
        return changed
    return {} if left == right else {path: [left, right]}


def test_program_019_forensic_disposition_is_bound_and_non_authorizing() -> None:
    value = json.loads((ROOT / PATH).read_text())
    stored = value.pop("forensic_disposition_fingerprint")
    assert stored == fingerprint(value)
    for name in (
        "scientific_contract",
        "scientific_contract_review",
        "runtime_implementation",
        "child_authority",
        "child_authority_review",
        "terminal_result",
        "terminal_review",
    ):
        binding = value["predecessor"][name]
        assert (
            hashlib.sha256((ROOT / binding["path"]).read_bytes()).hexdigest() == binding["sha256"]
        )
    assert value["conclusions"]["partial_session_must_be_discarded_in_full"] is True
    assert value["conclusions"]["later_session_or_page_evidence_present"] is False
    budget = value["cumulative_transport_contract"]
    assert budget["consumed_intents_without_response_before_program_019"] == 7
    assert budget["maximum_effective_combined_responses_for_program_019"] == 22169
    assert all(flag is False for flag in value["authority"].values())


def test_program_019_proposal_is_exact_and_non_authorizing() -> None:
    value = json.loads((ROOT / PROPOSAL).read_text())
    stored = value.pop("proposal_fingerprint")
    assert stored == fingerprint(value)
    assert value["supersedes"]["path"] == PROPOSAL_V1.as_posix()
    inherited = json.loads(
        (ROOT / value["predecessor"]["program_018_scientific_contract"]["path"]).read_text()
    )
    exception = value["exact_inheritance_contract"]["predecessor_revision_metadata_not_inherited"]
    assert exception == ["supersedes", "resolved_findings"]
    assert all(key in inherited for key in exception)
    delta = _changed_leaves(inherited, {**value, "proposal_fingerprint": stored})
    assert len(delta) == 146
    assert fingerprint(delta) == "245dd9c60c7851a77f40d581fe39a03cbc21d8e2d3e79b4ba82ed3e54c6f9591"
    for binding in value["predecessor"].values():
        assert (
            hashlib.sha256((ROOT / binding["path"]).read_bytes()).hexdigest() == binding["sha256"]
        )
    assert value["program_ordinal"] == 19
    assert value["recovery_contract"]["incomplete_program_018_request_reissue_allowed"] is False
    assert value["transport_boundary_contract"]["all_nine_controls_held_continuously"] is True
    budget = value["cumulative_transport_contract"]
    assert budget["consumed_intent_without_response_count"] == 7
    assert budget["maximum_effective_combined_responses"] == 22169
    assert (
        value["public_terminal_contract"]["exact_static_identity_values"]["program_ordinal"] == 19
    )
    assert all(flag is False for flag in value["authority"].values())


def test_program_019_independent_review_binds_exact_source_and_proposal() -> None:
    value = json.loads((ROOT / REVIEW).read_text())
    assert value.pop("review_fingerprint") == fingerprint(value)
    assert value["status"] == "PASS-FINDING-FREE"
    assert value["findings"] == []
    assert all(item["status"] == "PASS-FINDING-FREE" for item in value["independent_reviewers"])
    assert all(item["verdict"] == "PASS" for item in value["challenge_results"])
    assert all(flag is False for flag in value["authority"].values())
    binding = value["reviewed_proposal"]
    assert binding["path"] == PROPOSAL.as_posix()
    assert hashlib.sha256((ROOT / PROPOSAL).read_bytes()).hexdigest() == binding["sha256"]
    assert (
        json.loads((ROOT / PROPOSAL).read_text())["proposal_fingerprint"] == binding["fingerprint"]
    )
    commit = value["reviewed_source_commit"]
    tree = subprocess.check_output(["git", "rev-parse", f"{commit}^{{tree}}"], cwd=ROOT, text=True)
    assert tree.strip() == value["reviewed_source_tree"]
    reviewed = subprocess.check_output(["git", "show", f"{commit}:{PROPOSAL}"], cwd=ROOT)
    assert reviewed == (ROOT / PROPOSAL).read_bytes()
    diff = subprocess.check_output(
        ["git", "diff", "--binary", value["reviewed_diff"]["base_commit"], commit], cwd=ROOT
    )
    assert hashlib.sha256(diff).hexdigest() == value["reviewed_diff"]["sha256"]


def test_program_019_secret_guard_rejects_private_json(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    spec = importlib.util.spec_from_file_location(
        "program_019_guard", ROOT / "scripts/check_secrets.py"
    )
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    monkeypatch.chdir(tmp_path)
    private = Path("config/research/program-019-private-terminal.json")
    private.parent.mkdir(parents=True)
    private.write_text("{}\n")
    public_paths = [Path(path) for path in guard.PUBLIC_PROGRAM_JSON if "program-019" in path]
    for public in public_paths:
        public.parent.mkdir(parents=True, exist_ok=True)
        public.write_text("{}\n")
    monkeypatch.setattr(guard, "tracked_files", lambda: [private, *public_paths])
    assert guard.main() == 1
    errors = capsys.readouterr().err
    assert f"{private}:private-market-data-path" in errors
    assert all(str(public) not in errors for public in public_paths)
