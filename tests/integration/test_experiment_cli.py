import json
from pathlib import Path

import pytest

from systematic_trading_lab.cli import parser, run
from systematic_trading_lab.config import Settings
from systematic_trading_lab.datasets import DatasetService, fixture_request, fixture_symbols
from systematic_trading_lab.domain import Timeframe, TradingMode
from systematic_trading_lab.experiments import ExperimentRegistry
from systematic_trading_lab.providers import FixtureProvider
from systematic_trading_lab.storage import StorageLayout


def test_cli_runs_cataloged_experiment_and_compares_candidates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    layout = StorageLayout(tmp_path)
    imported = DatasetService(layout).import_from(
        FixtureProvider(), fixture_symbols(), Timeframe.DAILY, fixture_request()
    )
    ExperimentRegistry(layout.experiments).create_campaign("campaign", "CLI", 2)
    settings = Settings(TradingMode.OFFLINE, tmp_path)
    command = [
        "experiment",
        "run",
        "candidate",
        "--campaign",
        "campaign",
        "--strategy",
        "moving-average",
        "--code-commit",
        "abc123",
        "--dataset",
        imported.dataset_id,
        "--split",
        "validation",
        "--start",
        "2025-01-06",
        "--end",
        "2025-01-10",
        "--reason",
        "CLI integration",
        "--parameter",
        "window=2",
        "--fill-delay-bars",
        "2",
    ]
    arguments = parser().parse_args(command)
    assert run(arguments, settings) == 0
    record = ExperimentRegistry(layout.experiments).get("candidate")
    assert record["status"] == "completed"
    stored_spec = record["spec_json"]
    assert isinstance(stored_spec, dict)
    assert stored_spec["execution_model_version"] == "delayed-2-bars-v1"
    assert list(layout.reports.glob("*.json"))

    capsys.readouterr()
    compare = parser().parse_args(["experiment", "compare", "candidate"])
    assert run(compare, settings) == 0
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["candidates"][0]["experiment_id"] == "candidate"
    assert "score" not in report

    with pytest.raises(ValueError, match="unsupported parameters"):
        run(parser().parse_args(command + ["--parameter", "lookback=2"]), settings)
