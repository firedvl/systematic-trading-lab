import hashlib
import importlib.util
import json
from pathlib import Path

from pytest import CaptureFixture, MonkeyPatch

from systematic_trading_lab.fingerprints import fingerprint

ROOT = Path(__file__).resolve().parents[2]
PATH = Path("config/research/program-019-predecessor-recovery-forensic-disposition-v1.json")


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
    public = Path(PATH)
    public.write_text("{}\n")
    monkeypatch.setattr(guard, "tracked_files", lambda: [private, public])
    assert guard.main() == 1
    errors = capsys.readouterr().err
    assert f"{private}:private-market-data-path" in errors
    assert str(public) not in errors
