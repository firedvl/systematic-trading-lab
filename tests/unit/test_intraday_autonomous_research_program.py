from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from systematic_trading_lab.intraday_autonomous_research_program import (
    PROGRAM_FINGERPRINT,
    PROGRAM_SHA256,
    REVIEW_FINGERPRINT,
    REVIEW_SHA256,
    STATE_SHA256,
    load_intraday_autonomous_research_program,
)

_REPOSITORY = Path(__file__).resolve().parents[2]


def _frozen_repository(destination: Path) -> None:
    shutil.copytree(_REPOSITORY / "config", destination / "config")
    shutil.copytree(
        _REPOSITORY / "docs/research-campaigns", destination / "docs/research-campaigns"
    )


def test_loads_the_exact_reviewed_program_for_campaign_one() -> None:
    program = load_intraday_autonomous_research_program(_REPOSITORY)

    assert (program.sha256, program.program_fingerprint) == (PROGRAM_SHA256, PROGRAM_FINGERPRINT)
    assert (program.review_sha256, program.review_fingerprint) == (
        REVIEW_SHA256,
        REVIEW_FINGERPRINT,
    )
    assert program.state_sha256 == STATE_SHA256
    assert [campaign["campaign_id"] for campaign in program.payload["campaigns"]] == [
        "intraday-spy-qqq-lead-lag-001",
        "intraday-relative-volume-drift-001",
        "intraday-fed-policy-absorption-001",
    ]
    assert all(value is False for value in program.payload["authority"].values())


def test_loaded_control_payload_is_deeply_immutable() -> None:
    program = load_intraday_autonomous_research_program(_REPOSITORY)

    with pytest.raises(TypeError):
        program.payload["authority"]["broker_writes"] = True
    with pytest.raises(TypeError):
        program.payload["campaigns"][0]["campaign_id"] = "changed"
    with pytest.raises(TypeError):
        program.state["authority"]["broker_writes"] = True


def test_state_hash_and_parse_use_one_byte_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _frozen_repository(tmp_path)
    state_path = (
        tmp_path / "docs/research-campaigns/intraday-autonomous-research-001-state.json"
    ).resolve()
    valid = state_path.read_bytes()
    altered = json.loads(valid)
    altered["phase"] = "campaign-3-complete"
    altered["current_campaign_index"] = 3
    altered["run_specifications_consumed"] = 270
    altered_bytes = json.dumps(altered).encode()
    original_read_bytes = Path.read_bytes
    calls = 0

    def read_bytes(path: Path) -> bytes:
        nonlocal calls
        if path.resolve() == state_path:
            calls += 1
            return valid if calls == 1 else altered_bytes
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    program = load_intraday_autonomous_research_program(tmp_path)

    assert calls == 1
    assert program.state["phase"] == "program-plan-reviewed-campaign-1-plan-pending"
    assert program.state["current_campaign_index"] == 1
    assert program.state["run_specifications_consumed"] == 0


def test_rejects_changed_program_bytes(tmp_path: Path) -> None:
    _frozen_repository(tmp_path)
    path = tmp_path / "config/research/intraday-autonomous-research-001-program-v1.json"
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="program SHA-256 differs"):
        load_intraday_autonomous_research_program(tmp_path)


def test_rejects_program_fingerprint_mismatch_after_valid_bytes_are_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _frozen_repository(tmp_path)
    path = tmp_path / "config/research/intraday-autonomous-research-001-program-v1.json"
    payload = json.loads(path.read_text())
    payload["program_fingerprint"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        "systematic_trading_lab.intraday_autonomous_research_program.PROGRAM_SHA256",
        __import__("hashlib").sha256(path.read_bytes()).hexdigest(),
    )

    with pytest.raises(ValueError, match="program fingerprint differs"):
        load_intraday_autonomous_research_program(tmp_path)


@pytest.mark.parametrize(
    ("path", "message"),
    [
        (
            "config/research/intraday-autonomous-research-001-program-independent-review-v1.json",
            "review SHA-256 differs",
        ),
        (
            "docs/research-campaigns/intraday-autonomous-research-001-state.json",
            "state SHA-256 differs",
        ),
    ],
)
def test_rejects_changed_review_or_state_binding(tmp_path: Path, path: str, message: str) -> None:
    _frozen_repository(tmp_path)
    artifact = tmp_path / path
    artifact.write_bytes(artifact.read_bytes() + b"\n")

    with pytest.raises(ValueError, match=message):
        load_intraday_autonomous_research_program(tmp_path)


@pytest.mark.parametrize(
    "path",
    [
        "config/research/intraday-event-drift-001-plan-v1.json",
        "config/research/intraday-execution-cost-model-001-v1.json",
    ],
)
def test_rejects_changed_frozen_dependency(tmp_path: Path, path: str) -> None:
    _frozen_repository(tmp_path)
    artifact = tmp_path / path
    artifact.write_bytes(artifact.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="dependency SHA-256 differs"):
        load_intraday_autonomous_research_program(tmp_path)
