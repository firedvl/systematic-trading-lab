from __future__ import annotations

import hashlib
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


def test_account_proof_keeps_v1_while_acquisition_requires_separate_v6(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof = load_program_002_account_proof_plan(_REPOSITORY)
    assert proof.authority.sha256 == REVIEWED_AUTHORITY_SHA256
    plan_module._verify_acquisition_pagination_amendment(_REPOSITORY)
    plan_module._verify_acquisition_no_trade_completeness_amendment(_REPOSITORY)
    with monkeypatch.context() as context:
        context.setattr(
            plan_module,
            "REVIEWED_ACQUISITION_PAGINATION_AMENDMENT_SHA256",
            "0" * 64,
        )
        with pytest.raises(ValueError, match="pagination amendment SHA-256"):
            plan_module._verify_acquisition_pagination_amendment(_REPOSITORY)
    with monkeypatch.context() as context:
        context.setattr(
            plan_module,
            "REVIEWED_ACQUISITION_NO_TRADE_COMPLETENESS_AMENDMENT_SHA256",
            "0" * 64,
        )
        with pytest.raises(ValueError, match="no-trade completeness amendment SHA-256"):
            plan_module._verify_acquisition_no_trade_completeness_amendment(_REPOSITORY)

    monkeypatch.setattr(
        plan_module,
        "ACQUISITION_AUTHORITY_RELATIVE_PATH",
        Path("config/research/missing-program-002-acquisition-authority-v6.json"),
    )
    with pytest.raises(FileNotFoundError):
        plan_module.load_program_002_acquisition_plan(_REPOSITORY)


def test_acquisition_review_requires_exact_false_authority(tmp_path: Path) -> None:
    source_commit = "1" * 40
    files: list[object] = []
    authority = Program002Authority(
        tmp_path / ACQUISITION_AUTHORITY_RELATIVE_PATH,
        "2" * 64,
        "program-002-exposed-acquisition-2026-08-26-v6",
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
        "schema_version": "program-002-exposed-acquisition-authority-independent-review-v4",
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


def test_v6_authority_requires_exact_amendment_context_and_exposed_only_scope() -> None:
    proof = json.loads(
        (_REPOSITORY / plan_module.ACCOUNT_ISOLATION_PROOF_RELATIVE_PATH).read_text()
    )
    acquisition_plan = json.loads(
        (_REPOSITORY / plan_module.ACQUISITION_PLAN_RELATIVE_PATH).read_text()
    )
    payload = {
        "schema_version": "program-002-exposed-acquisition-authority-v6",
        "authority_id": "program-002-exposed-acquisition-2026-08-26-v6",
        "program_id": plan_module.PROGRAM_ID,
        "issued_date": "2026-08-26",
        "status": "active-until-complete-or-terminal-blocker",
        "source_authorization": {
            "kind": "user-supplied-authorization-packet",
            "sha256": "fd1a468fb152c6c18c0babda29c8393507a68558161b325d7f17348422093480",
        },
        "source_binding": {
            "source_commit": "1" * 40,
            "proof_evidence_commit": plan_module.REVIEWED_ACCOUNT_ISOLATION_PROOF_COMMIT,
            "relationship": "ancestor-of-clean-synchronized-main-with-identical-bound-files",
            "files": [
                {
                    "path": path,
                    "sha256": hashlib.sha256((_REPOSITORY / path).read_bytes()).hexdigest(),
                }
                for path in plan_module.ACQUISITION_SOURCE_PATHS
            ],
        },
        "bindings": plan_module._expected_acquisition_authority_bindings(),
        "supersedes": {
            "path": plan_module.ACQUISITION_AUTHORITY_V5_RELATIVE_PATH.as_posix(),
            "sha256": plan_module.REVIEWED_ACQUISITION_AUTHORITY_V5_SHA256,
            "disposition": (
                "immutable-and-revoked-before-credential-loading-by-bound-source-drift"
            ),
        },
        "authorized_scope": plan_module._expected_acquisition_scope(acquisition_plan),
        "account_isolation": {
            "proof_accepted": True,
            "environment": proof["environment"],
            "account_identity_hash": proof["account_identity_hash"],
            "credential_key_id_hash": proof["credential_key_id_hash"],
        },
        "prohibited": {
            key: True
            for key in (
                "strategy_execution_on_acquired_data",
                "strategy_result_generation_or_read",
                "discovery",
                "walk_forward",
                "robustness",
                "controlled_dataset_acquisition_or_access",
                "qualification",
                "protected_holdout",
                "paper_execution",
                "broker_writes",
                "live_execution",
                "strategic_allocation_21_access",
                "context_dataset_reacquisition_relabel_mutation_or_republication",
            )
        },
        "authority": {
            **{key: False for key in plan_module._AUTHORITY_KEYS},
            "market_data_acquisition": True,
            "strategy_implementation": True,
        },
    }
    payload["authority_fingerprint"] = fingerprint(payload)
    plan_module._verify_acquisition_authority_v6(_REPOSITORY, payload, proof)

    tampered = json.loads(json.dumps(payload))
    tampered["bindings"]["reused_context_dataset"]["dataset_id"] = "0" * 64
    tampered["authority_fingerprint"] = fingerprint(
        {key: value for key, value in tampered.items() if key != "authority_fingerprint"}
    )
    with pytest.raises(ValueError, match="bindings differ"):
        plan_module._verify_acquisition_authority_v6(_REPOSITORY, tampered, proof)

    v5 = {**payload, "schema_version": "program-002-exposed-acquisition-authority-v5"}
    v5["authority_fingerprint"] = fingerprint(
        {key: value for key, value in v5.items() if key != "authority_fingerprint"}
    )
    with pytest.raises(ValueError, match="identity or source differs"):
        plan_module._verify_acquisition_authority_v6(_REPOSITORY, v5, proof)


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
