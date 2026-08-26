from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import systematic_trading_lab.multi_hour_sector_etf_plan as plan_module
from systematic_trading_lab.fingerprints import canonical_json, fingerprint
from systematic_trading_lab.multi_hour_sector_etf_launch_control import (
    program_002_prelaunch_status,
)
from systematic_trading_lab.multi_hour_sector_etf_plan import (
    ACQUISITION_AUTHORITY_RELATIVE_PATH,
    ACQUISITION_AUTHORITY_REVIEW_RELATIVE_PATH,
    ACQUISITION_CONTROL_AMENDMENT_RELATIVE_PATH,
    ACQUISITION_PLAN_RELATIVE_PATH,
    AUTHORITY_RELATIVE_PATH,
    IMPLEMENTATION_PLAN_RELATIVE_PATH,
    PLAN_RELATIVE_PATH,
    PLANNING_REVIEW_RELATIVE_PATH,
    PROVIDER_CONTRACT_EVIDENCE_RELATIVE_PATH,
    REVIEWED_ACQUISITION_CONTROL_AMENDMENT_SHA256,
    REVIEWED_AUTHORITY_SHA256,
    REVIEWED_PROVIDER_CONTRACT_EVIDENCE_SHA256,
    UNIVERSE_RELATIVE_PATH,
    Program002Authority,
    load_program_002_account_proof_plan,
    load_program_002_acquisition_authority_review,
    load_program_002_authority,
    load_program_002_plan,
)

_REPOSITORY = Path(__file__).resolve().parents[2]


def test_authority_binds_every_reviewed_input_and_keeps_execution_false() -> None:
    authority = load_program_002_authority(_REPOSITORY)
    plan = load_program_002_plan(_REPOSITORY)
    acquisition = load_program_002_account_proof_plan(_REPOSITORY)

    assert authority.sha256 == REVIEWED_AUTHORITY_SHA256
    assert plan.authority == authority == acquisition.authority
    assert authority.payload["authority"]["market_data_acquisition"] is True
    assert authority.payload["authority"]["strategy_implementation"] is True
    assert authority.payload["authority"]["strategy_execution"] is False
    assert acquisition.control_path == _REPOSITORY / ACQUISITION_CONTROL_AMENDMENT_RELATIVE_PATH
    assert acquisition.control_sha256 == REVIEWED_ACQUISITION_CONTROL_AMENDMENT_SHA256
    assert (
        acquisition.provider_contract_evidence_path
        == _REPOSITORY / PROVIDER_CONTRACT_EVIDENCE_RELATIVE_PATH
    )
    assert (
        acquisition.provider_contract_evidence_sha256 == REVIEWED_PROVIDER_CONTRACT_EVIDENCE_SHA256
    )


def test_account_proof_keeps_v1_while_acquisition_requires_separate_v2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof = load_program_002_account_proof_plan(_REPOSITORY)
    assert proof.authority.sha256 == REVIEWED_AUTHORITY_SHA256

    monkeypatch.setattr(
        plan_module,
        "ACQUISITION_AUTHORITY_RELATIVE_PATH",
        Path("config/research/missing-program-002-acquisition-authority-v2.json"),
    )
    with pytest.raises(FileNotFoundError):
        plan_module.load_program_002_acquisition_plan(_REPOSITORY)


def test_acquisition_review_requires_exact_false_authority(tmp_path: Path) -> None:
    source_commit = "1" * 40
    files: list[object] = []
    authority = Program002Authority(
        tmp_path / ACQUISITION_AUTHORITY_RELATIVE_PATH,
        "2" * 64,
        "program-002-exposed-acquisition-2026-08-25-v2",
        {
            "authority_fingerprint": "3" * 64,
            "source_binding": {"source_commit": source_commit, "files": files},
        },
    )
    false_authority = {
        "market_data_acquisition": False,
        "strategy_implementation": False,
        "strategy_execution": False,
        "research_qualification": False,
        "controlled_evaluation": False,
        "protected_holdout": False,
        "paper_execution": False,
        "broker_writes": False,
        "live_execution": False,
    }
    review = {
        "schema_version": "program-002-exposed-acquisition-authority-independent-review-v1",
        "program_id": "multi-hour-sector-etf-research-001",
        "status": "passed-before-market-data-acquisition",
        "verdict": "pass",
        "findings": [],
        "reviewed_authority": {
            "path": ACQUISITION_AUTHORITY_RELATIVE_PATH.as_posix(),
            "sha256": authority.sha256,
            "fingerprint": authority.payload["authority_fingerprint"],
        },
        "reviewed_source": {
            "source_commit": source_commit,
            "authority_artifact_commit": "4" * 40,
            "files": files,
        },
        "authority": false_authority,
    }
    review["review_fingerprint"] = fingerprint(review)
    path = tmp_path / ACQUISITION_AUTHORITY_REVIEW_RELATIVE_PATH
    path.parent.mkdir(parents=True)
    path.write_text(canonical_json(review) + "\n", encoding="utf-8")
    assert load_program_002_acquisition_authority_review(tmp_path, authority)["verdict"] == "pass"

    review["authority"] = {}
    review["review_fingerprint"] = fingerprint(
        {key: value for key, value in review.items() if key != "review_fingerprint"}
    )
    path.write_text(canonical_json(review) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="review differs"):
        load_program_002_acquisition_authority_review(tmp_path, authority)


def test_authority_tampering_fails_before_plan_use(tmp_path: Path) -> None:
    paths = (
        AUTHORITY_RELATIVE_PATH,
        PLAN_RELATIVE_PATH,
        ACQUISITION_PLAN_RELATIVE_PATH,
        UNIVERSE_RELATIVE_PATH,
        IMPLEMENTATION_PLAN_RELATIVE_PATH,
        PLANNING_REVIEW_RELATIVE_PATH,
    )
    for relative in paths:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_REPOSITORY / relative, target)
    path = tmp_path / AUTHORITY_RELATIVE_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["authority"]["strategy_execution"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="authority SHA-256"):
        load_program_002_plan(tmp_path)


def test_prelaunch_is_pure_false_authority_and_rejects_credentials(tmp_path: Path) -> None:
    status = program_002_prelaunch_status(_REPOSITORY, environ={})

    assert status["ready_for_separate_strategy_execution_authorization"] is False
    assert status["strategy_execution_authority_present"] is False
    assert status["launch_allowed"] is False
    assert len(status["required_dataset_roles"]) == 4
    assert len(status["known_bindings"]["implementation_files"]) == 10

    with pytest.raises(ValueError, match="forbids credentials"):
        program_002_prelaunch_status(
            tmp_path,
            environ={"PROGRAM_002_ACQUISITION_API_KEY_ID": "test-only"},
        )

    for name in (
        "apca_api_key_id",
        "Alpaca_API_KEY_ID",
        "broker_token",
        "IBKR_API_KEY",
        "Paper_API_KEY",
        "paperTrading_api_key",
        "Live_API_KEY",
        "liveTrading_api_key",
    ):
        with pytest.raises(ValueError, match="forbids credentials"):
            program_002_prelaunch_status(_REPOSITORY, environ={name: "test-only"})
