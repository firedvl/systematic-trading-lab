from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from systematic_trading_lab.multi_hour_sector_etf_launch_control import (
    program_002_prelaunch_status,
)
from systematic_trading_lab.multi_hour_sector_etf_plan import (
    ACQUISITION_PLAN_RELATIVE_PATH,
    AUTHORITY_RELATIVE_PATH,
    IMPLEMENTATION_PLAN_RELATIVE_PATH,
    PLAN_RELATIVE_PATH,
    PLANNING_REVIEW_RELATIVE_PATH,
    REVIEWED_AUTHORITY_SHA256,
    UNIVERSE_RELATIVE_PATH,
    load_program_002_acquisition_plan,
    load_program_002_authority,
    load_program_002_plan,
)

_REPOSITORY = Path(__file__).resolve().parents[2]


def test_authority_binds_every_reviewed_input_and_keeps_execution_false() -> None:
    authority = load_program_002_authority(_REPOSITORY)
    plan = load_program_002_plan(_REPOSITORY)
    acquisition = load_program_002_acquisition_plan(_REPOSITORY)

    assert authority.sha256 == REVIEWED_AUTHORITY_SHA256
    assert plan.authority == authority == acquisition.authority
    assert authority.payload["authority"]["market_data_acquisition"] is True
    assert authority.payload["authority"]["strategy_implementation"] is True
    assert authority.payload["authority"]["strategy_execution"] is False


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
    assert len(status["known_bindings"]["implementation_files"]) == 8

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
