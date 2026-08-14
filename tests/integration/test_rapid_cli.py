from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

FIXTURE_DATASET_ID = "042e1e94eee7bbc1fe47c2f473bbbf93d773296a135486fa74fb34861c46e06d"


def _run(home: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for name in (
        "APCA_API_KEY_ID",
        "APCA_API_SECRET_KEY",
        "TRADING_LAB_PAPER_ACTIVATION_ID",
        "TRADING_LAB_PAPER_CODE_COMMIT",
    ):
        environment.pop(name, None)
    environment["TRADING_LAB_HOME"] = str(home)
    environment["TRADING_LAB_MODE"] = "offline"
    command = Path(sys.executable).with_name("trading-lab")
    return subprocess.run(
        (str(command), *arguments),
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )


def _json(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    value = json.loads(result.stdout)
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def test_documented_newcomer_path_runs_in_a_clean_home(tmp_path: Path) -> None:
    home = tmp_path / "state"

    doctor = _json(_run(home, "doctor"))
    imported = _json(_run(home, "data", "import-fixture"))
    datasets = _json(_run(home, "data", "list"))
    strategies = _json(_run(home, "research", "list-strategies"))
    backtest = _json(
        _run(
            home,
            "research",
            "backtest",
            "--dataset",
            FIXTURE_DATASET_ID,
            "--strategy",
            "moving-average",
            "--parameter",
            "window=2",
        )
    )
    shown = _json(_run(home, "research", "show", str(backtest["run_id"])))
    walk_forward = _json(
        _run(
            home,
            "research",
            "walk-forward",
            "--dataset",
            FIXTURE_DATASET_ID,
            "--strategy",
            "moving-average",
            "--parameter",
            "window=2",
            "--training-window",
            "2",
            "--test-window",
            "2",
            "--step-size",
            "2",
        )
    )
    stress = _json(_run(home, "research", "stress", str(backtest["run_id"])))
    stress_run = cast(dict[str, object], stress["stress"])
    compared = _json(
        _run(
            home,
            "research",
            "compare",
            str(backtest["run_id"]),
            str(stress_run["run_id"]),
        )
    )
    candidate = _json(_run(home, "research", "export-candidate", str(backtest["run_id"])))

    assert all(cast(dict[str, bool], doctor["checks"]).values())
    assert imported["dataset_id"] == FIXTURE_DATASET_ID
    assert len(cast(list[object], datasets["datasets"])) == 1
    assert len(cast(list[object], strategies["strategies"])) == 14
    assert backtest["status"] == "completed"
    assert shown["run_id"] == backtest["run_id"]
    assert not any(cast(dict[str, bool], shown["authority"]).values())
    walk_run = cast(dict[str, object], walk_forward["run"])
    assert walk_run["status"] == "completed"
    assert len(cast(list[object], walk_forward["folds"])) == 1
    assert stress_run["status"] == "completed"
    assert len(cast(list[object], compared["runs"])) == 2
    assert Path(str(candidate["path"])).is_file()
    assert not (home / "experiments.sqlite3").exists()
    assert not (home / "execution.sqlite3").exists()


def test_public_wrapper_imports_local_csv_and_delegates_legacy_status(tmp_path: Path) -> None:
    source = tmp_path / "bars.csv"
    source.write_text(
        "timestamp,symbol,open,high,low,close,volume\n"
        "2025-01-06T00:00:00Z,SPY,100,102,99,101,1000000\n"
        "2025-01-07T00:00:00Z,SPY,101,103,100,102,1000001\n",
        encoding="utf-8",
    )
    home = tmp_path / "state"

    imported = _json(_run(home, "data", "import-local", str(source)))
    status = _json(_run(home, "status"))
    stress_help = _run(home, "research", "stress", "--help").stdout

    assert imported["data_origin"] == "user-supplied"
    assert status["mode"] == "offline"
    assert "(default: 10)" in stress_help


def test_sweep_prints_count_before_running_every_configuration(tmp_path: Path) -> None:
    home = tmp_path / "state"
    _run(home, "data", "import-fixture")

    result = _run(
        home,
        "research",
        "sweep",
        "--dataset",
        FIXTURE_DATASET_ID,
        "--strategy",
        "moving-average",
        "--parameter",
        "window=2,3",
        "--max-runs",
        "2",
    )
    payload = _json(result)

    assert result.stderr == "parameter configurations: 2 (cap: 2)\n"
    assert payload["configuration_count"] == 2
    assert len(cast(list[object], payload["runs"])) == 2
