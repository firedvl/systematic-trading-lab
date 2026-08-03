import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from systematic_trading_lab.cli import parser, run
from systematic_trading_lab.config import Settings
from systematic_trading_lab.datasets import DatasetService, fixture_request, fixture_symbols
from systematic_trading_lab.domain import OHLCVBar, Timeframe, TimestampRange, TradingMode
from systematic_trading_lab.experiments import ExperimentRegistry
from systematic_trading_lab.providers import FixtureProvider
from systematic_trading_lab.storage import StorageLayout
from systematic_trading_lab.universe import load_research_universe


def test_cli_runs_cataloged_experiment_and_compares_candidates(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = StorageLayout(tmp_path)
    imported = DatasetService(layout).import_from(
        FixtureProvider(),
        fixture_symbols(),
        Timeframe.DAILY,
        fixture_request(),
        load_research_universe(),
    )
    ExperimentRegistry(layout.experiments).create_campaign("campaign", "CLI", 2)
    settings = Settings(TradingMode.OFFLINE, tmp_path)
    original_range_loader = DatasetService.load_bars_range
    loaded_ranges: list[TimestampRange] = []

    def reject_full_load(self: DatasetService, dataset_id: str | None = None) -> None:
        raise AssertionError("cataloged experiment attempted a full dataset load")

    def audit_range_load(
        self: DatasetService,
        dataset_id: str,
        requested: TimestampRange,
        *,
        expected_fingerprint: str,
        expected_universe_id: str,
        expected_universe_fingerprint: str,
    ) -> tuple[OHLCVBar, ...]:
        loaded_ranges.append(requested)
        return original_range_loader(
            self,
            dataset_id,
            requested,
            expected_fingerprint=expected_fingerprint,
            expected_universe_id=expected_universe_id,
            expected_universe_fingerprint=expected_universe_fingerprint,
        )

    monkeypatch.setattr(DatasetService, "load_bars", reject_full_load)
    monkeypatch.setattr(DatasetService, "load_bars_range", audit_range_load)
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
        "2025-01-08",
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
    assert loaded_ranges == [
        TimestampRange(datetime(2025, 1, 8, tzinfo=UTC), datetime(2025, 1, 10, tzinfo=UTC))
    ]
    record = ExperimentRegistry(layout.experiments).get("candidate")
    assert record["status"] == "completed"
    stored_spec = record["spec_json"]
    assert isinstance(stored_spec, dict)
    assert stored_spec["execution_model_version"] == "delayed-2-bars-v1"
    manifest = DatasetService(layout).describe(imported.dataset_id)
    assert stored_spec["universe_id"] == manifest["universe_id"]
    assert stored_spec["universe_fingerprint"] == manifest["universe_fingerprint"]
    assert list(layout.reports.glob("*.json"))

    manual = parser().parse_args(
        [
            "experiment",
            "create",
            "manual-candidate",
            "--campaign",
            "campaign",
            "--strategy-id",
            "moving-average",
            "--strategy-version",
            "1",
            "--strategy-family",
            "trend",
            "--code-commit",
            "abc123",
            "--dataset-id",
            imported.dataset_id,
            "--split",
            "training",
            "--start",
            "2025-01-06",
            "--end",
            "2025-01-10",
            "--reason",
            "Manual CLI integration",
        ]
    )
    assert run(manual, settings) == 0
    manual_spec = ExperimentRegistry(layout.experiments).get("manual-candidate")["spec_json"]
    assert isinstance(manual_spec, dict)
    assert manual_spec["dataset_fingerprint"] == manifest["identity"]["fingerprint"]
    assert manual_spec["universe_fingerprint"] == manifest["universe_fingerprint"]

    capsys.readouterr()
    compare = parser().parse_args(["experiment", "compare", "candidate"])
    assert run(compare, settings) == 0
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["candidates"][0]["experiment_id"] == "candidate"
    assert "score" not in report

    with pytest.raises(ValueError, match="unsupported parameters"):
        run(parser().parse_args(command + ["--parameter", "lookback=2"]), settings)

    ExperimentRegistry(layout.experiments).create_campaign("portfolio-campaign", "Portfolio", 1)
    portfolio = parser().parse_args(
        [
            "experiment",
            "run",
            "portfolio-candidate",
            "--campaign",
            "portfolio-campaign",
            "--strategy",
            "relative-strength",
            "--code-commit",
            "abc123",
            "--dataset",
            imported.dataset_id,
            "--split",
            "training",
            "--start",
            "2025-01-06",
            "--end",
            "2025-01-10",
            "--reason",
            "Portfolio CLI integration",
            "--parameter",
            "lookback=2",
            "--parameter",
            "rebalance_every=1",
            "--parameter",
            "selection_count=3",
        ]
    )
    assert run(portfolio, settings) == 0
    portfolio_record = ExperimentRegistry(layout.experiments).get("portfolio-candidate")
    portfolio_spec = portfolio_record["spec_json"]
    assert portfolio_record["status"] == "completed"
    assert isinstance(portfolio_spec, dict)
    assert portfolio_spec["strategy_id"] == "relative-strength-portfolio"
    assert portfolio_spec["strategy_family"] == "portfolio-momentum"

    ExperimentRegistry(layout.experiments).create_campaign("risk-campaign", "Risk", 1)
    risk_managed = parser().parse_args(
        [
            "experiment",
            "run",
            "risk-candidate",
            "--campaign",
            "risk-campaign",
            "--strategy",
            "risk-managed-momentum",
            "--code-commit",
            "abc123",
            "--dataset",
            imported.dataset_id,
            "--split",
            "training",
            "--start",
            "2025-01-06",
            "--end",
            "2025-01-10",
            "--reason",
            "Risk-managed CLI integration",
            "--parameter",
            "lookback=2",
            "--parameter",
            "volatility_window=2",
            "--parameter",
            "rebalance_every=1",
        ]
    )
    assert run(risk_managed, settings) == 0
    risk_record = ExperimentRegistry(layout.experiments).get("risk-candidate")
    risk_spec = risk_record["spec_json"]
    assert risk_record["status"] == "completed"
    assert isinstance(risk_spec, dict)
    assert risk_spec["strategy_id"] == "risk-managed-momentum-portfolio"
    assert risk_spec["strategy_family"] == "portfolio-momentum"

    ExperimentRegistry(layout.experiments).create_campaign("volatility-campaign", "Volatility", 1)
    volatility_balanced = parser().parse_args(
        [
            "experiment",
            "run",
            "volatility-candidate",
            "--campaign",
            "volatility-campaign",
            "--strategy",
            "volatility-balanced",
            "--code-commit",
            "abc123",
            "--dataset",
            imported.dataset_id,
            "--split",
            "training",
            "--start",
            "2025-01-06",
            "--end",
            "2025-01-10",
            "--reason",
            "Volatility-balanced CLI integration",
            "--parameter",
            "volatility_window=2",
            "--parameter",
            "rebalance_every=1",
        ]
    )
    assert run(volatility_balanced, settings) == 0
    volatility_record = ExperimentRegistry(layout.experiments).get("volatility-candidate")
    volatility_spec = volatility_record["spec_json"]
    assert volatility_record["status"] == "completed"
    assert isinstance(volatility_spec, dict)
    assert volatility_spec["strategy_id"] == "volatility-balanced-portfolio"
    assert volatility_spec["strategy_family"] == "portfolio-allocation"
