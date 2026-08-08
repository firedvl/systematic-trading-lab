import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from systematic_trading_lab.cli import parser, run
from systematic_trading_lab.config import Settings
from systematic_trading_lab.datasets import (
    DatasetService,
    fixture_request,
    fixture_symbols,
    intraday_fixture_request,
    intraday_fixture_symbols,
)
from systematic_trading_lab.domain import OHLCVBar, Timeframe, TimestampRange, TradingMode
from systematic_trading_lab.experiments import ExperimentRegistry
from systematic_trading_lab.providers import FixtureProvider, IntradayFixtureProvider
from systematic_trading_lab.storage import StorageLayout
from systematic_trading_lab.universe import load_intraday_universe, load_research_universe


def test_fixture_all_reports_every_bootstrap_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = parser().parse_args(["backtest", "fixture", "--strategy", "all"])

    assert run(arguments, Settings(TradingMode.OFFLINE, tmp_path)) == 0
    report = json.loads(capsys.readouterr().out)
    assert {
        "cash",
        "fixed-weight",
        "moving-average",
        "mean-reversion",
        "momentum",
        "volatility-targeted",
    } <= report["results"].keys()


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
    assert record["execution_provenance"] == "controlled-run"
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

    for name, parameter in (
        ("mean-reversion", "window=1"),
        ("volatility-targeted", "volatility_window=1"),
    ):
        campaign_id = f"invalid-{name}"
        ExperimentRegistry(layout.experiments).create_campaign(campaign_id, name, 1)
        invalid = [
            {
                "candidate": f"invalid-{name}",
                "campaign": campaign_id,
                "moving-average": name,
                "window=2": parameter,
            }.get(value, value)
            for value in command
        ]
        with pytest.raises(ValueError, match="must be at least 2"):
            run(parser().parse_args(invalid), settings)
        assert ExperimentRegistry(layout.experiments).list(campaign_id) == []

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


def test_cli_runs_isolated_intraday_baseline_without_execution_authority(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    layout = StorageLayout(tmp_path)
    timeframe = Timeframe.FIVE_MINUTES
    requested = intraday_fixture_request(timeframe)
    universe = load_intraday_universe(timeframe)
    imported = DatasetService(layout).import_from(
        IntradayFixtureProvider(),
        intraday_fixture_symbols(),
        timeframe,
        requested,
        universe,
    )
    ExperimentRegistry(layout.experiments).create_campaign("m5b-cli", "M5B CLI", 1)
    command = parser().parse_args(
        [
            "experiment",
            "run-intraday",
            "m5b-cash",
            "--campaign",
            "m5b-cli",
            "--strategy",
            "cash",
            "--candidate-ordinal",
            "1",
            "--code-commit",
            "abc123",
            "--dataset",
            imported.dataset_id,
            "--timeframe",
            "5m",
            "--split",
            "training",
            "--start",
            requested.start.isoformat(),
            "--end",
            requested.end.isoformat(),
            "--reason",
            "fixed CLI engineering baseline",
        ]
    )

    assert run(command, Settings(TradingMode.OFFLINE, tmp_path)) == 0
    output = json.loads(capsys.readouterr().out)
    stored = output["spec_json"]

    assert output["status"] == "completed"
    assert output["execution_provenance"] == "controlled-run"
    assert stored["schema_version"] == "intraday-experiment-v1"
    assert stored["timeframe"] == "5m"
    assert stored["session_policy_version"] == "XNYS-regular-session-flat-v1"
    assert output["metrics_json"]["fill_count"] == 0
    assert len(output["artifact_hashes_json"]) == 1
    assert not layout.execution.exists()
