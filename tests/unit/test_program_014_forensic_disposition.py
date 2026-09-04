from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, cast

from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_DISPOSITION = Path("config/research/program-014-predecessor-recovery-forensic-disposition-v1.json")


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_REPOSITORY / path).read_text(encoding="utf-8")))


def test_program_014_forensic_disposition_is_exact_redacted_and_non_authorizing() -> None:
    disposition = _load(_DISPOSITION)
    stored = disposition.pop("forensic_disposition_fingerprint")
    assert stored == fingerprint(disposition)

    terminal = disposition["predecessor"]["terminal_result"]
    review = disposition["predecessor"]["terminal_review"]
    for binding in (terminal, review):
        assert (
            hashlib.sha256((_REPOSITORY / binding["path"]).read_bytes()).hexdigest()
            == binding["sha256"]
        )

    conclusions = disposition["conclusions"]
    assert conclusions["completed_evidence_is_exact_whole_session_prefix"] is True
    assert conclusions["incomplete_checkpoint_kind"] == "INTENT-ONLY-PAGE-FRONTIER"
    assert conclusions["later_session_or_page_evidence_present"] is False
    assert conclusions["structural_admission_evaluated"] is False
    assert conclusions["dataset_published"] is False
    assert conclusions["strategy_work_occurred"] is False
    assert all(value is False for value in disposition["authority"].values())


def test_secret_guard_reserves_only_the_program_014_public_disposition(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    spec = importlib.util.spec_from_file_location(
        "program_014_check_secrets", _REPOSITORY / "scripts/check_secrets.py"
    )
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    monkeypatch.chdir(tmp_path)
    public = _DISPOSITION
    private = Path("config/research/program-014-market-observations.json")
    for path in (public, private):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(guard, "tracked_files", lambda: [public, private])

    assert guard.main() == 1
    errors = capsys.readouterr().err
    assert public.as_posix() in guard.PUBLIC_PROGRAM_JSON
    assert str(public) not in errors
    assert f"{private}:private-market-data-path" in errors
