from __future__ import annotations

import csv
import json
import sqlite3
import subprocess
from datetime import UTC, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

import systematic_trading_lab.rapid_research as rapid_research
from systematic_trading_lab.calendar import expected_sessions
from systematic_trading_lab.rapid_data import import_local_data, parse_utc
from systematic_trading_lab.rapid_research import (
    ResearchInputs,
    parse_parameter_grid,
    parse_parameters,
    run_backtest,
    run_stress,
    run_sweep,
    run_walk_forward,
)
from systematic_trading_lab.rapid_store import RAPID_AUTHORITY, RapidResearchStore
from systematic_trading_lab.strategy_registry import validate_strategy_parameters

FIELDS = ("timestamp", "symbol", "open", "high", "low", "close", "volume")


def _dataset(tmp_path: Path, count: int = 14) -> tuple[Path, RapidResearchStore, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    sessions = expected_sessions(
        datetime(2025, 1, 6, tzinfo=UTC), datetime(2025, 3, 31, tzinfo=UTC)
    )[:count]
    records = [
        {
            "timestamp": datetime.combine(session, time.min, tzinfo=UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "symbol": "SPY",
            "open": str(100 + index),
            "high": str(102 + index),
            "low": str(99 + index),
            "close": str(101 + index),
            "volume": 1_000_000 + index,
        }
        for index, session in enumerate(sessions)
    ]
    path = tmp_path / "bars.csv"
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)
    root = tmp_path / "state"
    store = RapidResearchStore(root)
    imported = import_local_data(path, store)
    return root, store, str(imported["dataset_id"])


def _inputs(dataset_id: str, strategy: str = "moving-average") -> ResearchInputs:
    return ResearchInputs(
        dataset_id, strategy, {"window": 2} if strategy == "moving-average" else {}
    )


def test_parameter_parsing_and_registry_validation() -> None:
    assert parse_parameters(("window=20",)) == {"window": 20}
    assert parse_parameter_grid(("slow=50,100", "fast=10,20")) == {
        "slow": (50, 100),
        "fast": (10, 20),
    }
    assert validate_strategy_parameters("moving-average", {}) == {"window": 20}

    with pytest.raises(ValueError, match="unsupported parameters"):
        validate_strategy_parameters("moving-average", {"unknown": 1})
    with pytest.raises(ValueError, match="unique NAME=INTEGER"):
        parse_parameters(("window=2", "window=3"))


@pytest.mark.parametrize(
    ("strategy", "parameters", "message"),
    (
        (
            "multi-horizon-momentum",
            {"short_lookback": 126, "long_lookback": 20},
            "short_lookback must be shorter",
        ),
        (
            "dual-momentum",
            {"short_lookback": 126, "long_lookback": 20},
            "short_lookback must be shorter",
        ),
        ("dual-momentum", {"selection_count": 4}, "must not exceed three"),
    ),
)
def test_registry_rejects_invalid_strategy_parameter_combinations(
    strategy: str, parameters: dict[str, int], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_strategy_parameters(strategy, parameters)


def test_code_identity_scrubs_broker_and_untrusted_git_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Path(rapid_research.__file__).resolve().parents[2]
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
    for name in (
        "APCA_API_SECRET_KEY",
        "TRADING_LAB_PAPER_ACTIVATION_ID",
        "GIT_WORK_TREE",
        "GIT_CONFIG_GLOBAL",
    ):
        monkeypatch.setenv(name, "must-not-reach-git")

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[object]:
        calls.append((command, kwargs))
        if "--show-toplevel" in command:
            stdout: object = f"{repository}\n"
        elif command[-2:] == ("rev-parse", "HEAD"):
            stdout = f"{'a' * 40}\n"
        elif "status" in command:
            stdout = b" M src/systematic_trading_lab/rapid_research.py\n"
        elif "diff" in command:
            stdout = b"diff"
        else:
            stdout = b""
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    monkeypatch.setattr(subprocess, "run", run)

    identity = rapid_research._code_identity()

    assert identity["commit"] == "a" * 40
    assert len(calls) == 5
    for command, kwargs in calls:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        assert environment["GIT_CONFIG_GLOBAL"] == "/dev/null"
        assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
        assert environment["HOME"] == "/nonexistent"
        assert environment["XDG_CONFIG_HOME"] == "/nonexistent"
        assert "APCA_API_SECRET_KEY" not in environment
        assert "TRADING_LAB_PAPER_ACTIVATION_ID" not in environment
        assert "GIT_WORK_TREE" not in environment
        assert command[1:4] == ("--no-replace-objects", "-c", "core.fsmonitor=false")


def test_backtest_replay_is_deterministic_and_create_only(tmp_path: Path) -> None:
    root, store, dataset_id = _dataset(tmp_path)

    first = run_backtest(root, store, _inputs(dataset_id))
    report = Path(str(first["report_path"]))
    first_bytes = report.read_bytes()
    replay = run_backtest(root, store, _inputs(dataset_id))

    assert first["status"] == "completed"
    assert replay == first
    assert report.read_bytes() == first_bytes
    assert len(store.list_runs()) == 1
    assert cast(dict[str, object], first["metrics"])["net_of_costs"] is True


def test_pending_run_recovers_after_report_precedes_database_completion(
    tmp_path: Path,
) -> None:
    root, store, dataset_id = _dataset(tmp_path)
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            """
            CREATE TRIGGER interrupt_rapid_completion
            BEFORE UPDATE OF status ON rapid_runs
            BEGIN
                SELECT RAISE(ABORT, 'injected completion interruption');
            END
            """
        )

    with pytest.raises(FileExistsError):
        run_backtest(root, store, _inputs(dataset_id))
    pending = store.list_runs()[0]
    report = store.reports / f"{pending['run_id']}.json"
    report_bytes = report.read_bytes()

    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP TRIGGER interrupt_rapid_completion")
    recovered = run_backtest(root, store, _inputs(dataset_id))

    assert recovered["status"] == "completed"
    assert report.read_bytes() == report_bytes


def test_sweep_enforces_cap_and_retains_every_failed_configuration(tmp_path: Path) -> None:
    root, store, dataset_id = _dataset(tmp_path)

    with pytest.raises(ValueError, match="3 configurations; cap is 2"):
        run_sweep(root, store, _inputs(dataset_id), {"window": (2, 3, 4)}, 2)
    sweep = run_sweep(
        root,
        store,
        ResearchInputs(dataset_id, "relative-strength", {}),
        {"selection_count": (1, 2)},
        100,
    )

    assert sweep["configuration_count"] == 2
    runs = cast(list[dict[str, object]], sweep["runs"])
    assert [run["status"] for run in runs] == ["completed", "failed"]
    stored = store.list_runs(group_id=str(sweep["group_id"]))
    assert len(stored) == 2
    failed = next(run for run in stored if run["status"] == "failed")
    assert "selection count must fit" in str(failed["error"])


@pytest.mark.parametrize("expanding", (False, True))
def test_walk_forward_is_chronological_and_reports_fold_dispersion(
    tmp_path: Path, expanding: bool
) -> None:
    root, store, dataset_id = _dataset(tmp_path)

    result = run_walk_forward(
        root,
        store,
        _inputs(dataset_id),
        training_window=4,
        test_window=2,
        step_size=2,
        expanding=expanding,
    )

    parent_summary = cast(dict[str, object], result["run"])
    folds = cast(list[dict[str, object]], result["folds"])
    assert parent_summary["status"] == "completed"
    assert len(folds) == 5
    parent = store.get_run(str(parent_summary["run_id"]))
    metrics = parent["metrics"]
    assert isinstance(metrics, dict)
    assert metrics["fold_count"] == 5
    assert metrics["fold_return_dispersion"] is not None
    training_starts: list[datetime] = []
    previous_validation_end: datetime | None = None
    for compact in folds:
        fold = store.get_run(str(compact["run_id"]))
        specification = fold["specification"]
        assert isinstance(specification, dict)
        fold_range = specification["fold"]
        assert isinstance(fold_range, dict)
        training_start = parse_utc(str(fold_range["training_start"]))
        training_end = parse_utc(str(fold_range["training_end"]))
        validation_start = parse_utc(str(fold_range["validation_start"]))
        validation_end = parse_utc(str(fold_range["validation_end"]))
        assert training_end < validation_start <= validation_end
        if previous_validation_end is not None:
            assert previous_validation_end < validation_start
        previous_validation_end = validation_end
        training_starts.append(training_start)
        report = json.loads(Path(str(fold["report_path"])).read_text(encoding="utf-8"))
        assert report["metrics"]["session_count"] == 2
    if expanding:
        assert len(set(training_starts)) == 1
    else:
        assert training_starts == sorted(set(training_starts))


def test_stress_requires_worse_cost_or_delay_assumptions(tmp_path: Path) -> None:
    root, store, dataset_id = _dataset(tmp_path)
    source = run_backtest(root, store, _inputs(dataset_id))

    with pytest.raises(ValueError, match="strictly worse"):
        run_stress(root, store, str(source["run_id"]), Decimal("5"), Decimal("1"), 1)
    stressed = run_stress(
        root,
        store,
        str(source["run_id"]),
        Decimal("10"),
        Decimal("2"),
        2,
    )

    stress_summary = cast(dict[str, object], stressed["stress"])
    assert stress_summary["status"] == "completed"
    assert stress_summary["fill_delay_bars"] == 2

    walk_forward = run_walk_forward(
        root,
        store,
        _inputs(dataset_id),
        training_window=4,
        test_window=2,
        step_size=2,
        expanding=False,
    )
    fold = cast(list[dict[str, object]], walk_forward["folds"])[0]
    with pytest.raises(ValueError, match="non-walk-forward"):
        run_stress(
            root,
            store,
            str(fold["run_id"]),
            Decimal("10"),
            Decimal("2"),
            2,
        )


def test_candidate_export_has_complete_ledger_and_zero_authority(tmp_path: Path) -> None:
    root, store, dataset_id = _dataset(tmp_path)
    sweep = run_sweep(
        root,
        store,
        ResearchInputs(dataset_id, "relative-strength", {}),
        {"selection_count": (1, 2)},
        100,
    )
    runs = cast(list[dict[str, object]], sweep["runs"])
    selected = str(next(run["run_id"] for run in runs if run["status"] == "completed"))

    candidate = store.export_candidate(selected)

    assert candidate["authority"] == RAPID_AUTHORITY
    assert not any(RAPID_AUTHORITY.values())
    ledger = cast(list[dict[str, object]], candidate["search_ledger"])
    assert len(ledger) == 2
    assert {run["status"] for run in ledger} == {"completed", "failed"}
    assert Path(str(candidate["path"])).is_file()
    selected_run = cast(dict[str, object], candidate["selected_run"])
    assert "created_at" not in selected_run
    assert "report_path" not in selected_run

    cast(dict[str, bool], candidate["authority"])["paper_execution"] = True
    replay = store.export_candidate(selected)
    assert cast(dict[str, bool], replay["authority"])["paper_execution"] is False
    stored = json.loads(Path(str(replay["path"])).read_text(encoding="utf-8"))
    assert stored["authority"]["paper_execution"] is False


def test_candidate_export_bytes_repeat_across_runtime_homes(tmp_path: Path) -> None:
    artifacts: list[bytes] = []
    for name in ("first", "second"):
        root, store, dataset_id = _dataset(tmp_path / name)
        run = run_backtest(root, store, _inputs(dataset_id))
        candidate = store.export_candidate(str(run["run_id"]))
        artifacts.append(Path(str(candidate["path"])).read_bytes())

    assert artifacts[0] == artifacts[1]
