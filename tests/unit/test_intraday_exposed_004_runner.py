from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from systematic_trading_lab.intraday_exposed_004_runner import (
    REVIEWED_FAILURE_FINGERPRINT,
    _load_failure,
    intraday_exposed_004_plan_summary,
    intraday_exposed_004_status,
    run_intraday_exposed_004_campaign,
)
from systematic_trading_lab.public_cli import research_parser

_REPOSITORY = Path(__file__).resolve().parents[2]


def test_failure_disposition_is_hash_bound_and_names_clean_successor() -> None:
    value = _load_failure(_REPOSITORY)
    runtime = cast(Mapping[str, object], value["runtime"])
    disposition = cast(Mapping[str, object], value["disposition"])

    assert value["failure_fingerprint"] == REVIEWED_FAILURE_FINGERPRINT
    assert runtime["run_counts"] == {
        "pending": 120,
        "running": 0,
        "completed": 0,
        "failed": 0,
    }
    assert runtime["attempt_count"] == 0
    assert runtime["strategy_execution_started"] is False
    assert disposition["action"] == "preserve-do-not-retry-or-rebind"
    assert disposition["successor_program_id"] == "intraday-exposed-005"


def test_004_plan_and_missing_runtime_status_remain_read_only(tmp_path: Path) -> None:
    plan = intraday_exposed_004_plan_summary(_REPOSITORY)
    status = intraday_exposed_004_status(tmp_path)

    assert plan["status"] == "aborted-before-attempt-task-transport-failure"
    assert plan["successor_program_id"] == "intraday-exposed-005"
    assert status["terminal"] is True
    assert status["database_exists"] is False
    assert status["evidence_matches_disposition"] is False
    assert not any(cast(Mapping[str, bool], status["authority"]).values())
    assert not any(tmp_path.iterdir())


def test_004_run_is_disabled_before_repository_or_runtime_access(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="immutable.*use Intraday Exposed 005"):
        run_intraday_exposed_004_campaign(
            tmp_path / "missing-repository",
            tmp_path / "missing-data",
            workers=4,
        )

    assert not any(tmp_path.iterdir())


def test_004_cli_keeps_historical_plan_status_and_disabled_run_actions() -> None:
    parser = research_parser()

    for action in ("plan", "status", "run"):
        arguments = parser.parse_args(("intraday-exposed-004", action))
        assert arguments.research_command == "intraday-exposed-004"
        assert arguments.action == action
