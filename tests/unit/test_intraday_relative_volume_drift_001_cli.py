from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import systematic_trading_lab.intraday_relative_volume_drift_001_cli as cli_module
import systematic_trading_lab.intraday_relative_volume_drift_001_runner as runner_module
from systematic_trading_lab.config import Settings
from systematic_trading_lab.domain import TradingMode
from systematic_trading_lab.intraday_relative_volume_drift_001_plan import PROGRAM_ID


def test_cli_delegates_and_enforces_research_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    received: tuple[str, ...] | None = None

    def delegated(arguments: tuple[str, ...]) -> int:
        nonlocal received
        received = arguments
        return 17

    monkeypatch.setattr(cli_module, "lead_lag_main", delegated)
    assert cli_module.main(("research", "list-strategies")) == 17
    assert received == ("research", "list-strategies")

    monkeypatch.setattr(cli_module, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        cli_module,
        "load_settings",
        lambda: Settings(TradingMode.RESEARCH, tmp_path),
    )
    monkeypatch.setattr(
        cli_module,
        "intraday_relative_volume_drift_001_plan_summary",
        lambda _repository: {"program_id": PROGRAM_ID},
    )
    assert cli_module.main(("research", PROGRAM_ID, "plan")) == 0
    assert json.loads(capsys.readouterr().out)["program_id"] == PROGRAM_ID

    monkeypatch.setattr(
        cli_module,
        "load_settings",
        lambda: SimpleNamespace(
            mode=TradingMode.RESEARCH,
            home=tmp_path,
            paper_write_request=object(),
        ),
    )
    assert cli_module.main(("research", PROGRAM_ID, "run")) != 0
    assert "paper-write opt-in" in capsys.readouterr().err


def test_unbound_run_fails_before_runtime_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(runner_module, "REVIEWED_LAUNCH_CONTROL_SHA256", None)
    monkeypatch.setattr(runner_module, "REVIEWED_LAUNCH_CONTROL_FINGERPRINT", None)
    monkeypatch.setattr(cli_module, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        cli_module,
        "load_settings",
        lambda: Settings(TradingMode.RESEARCH, tmp_path),
    )
    assert cli_module.main(("research", PROGRAM_ID, "run")) != 0
    assert "not hash-bound" in capsys.readouterr().err
    assert not (tmp_path / PROGRAM_ID).exists()


def test_parser_keeps_worker_count_outside_run_identity() -> None:
    parsed = cli_module.relative_volume_drift_parser().parse_args(("run", "--workers", "6"))
    assert parsed.action == "run"
    assert parsed.workers == 6
