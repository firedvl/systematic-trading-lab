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
from systematic_trading_lab.experiments import ExperimentError, ExperimentRegistry
from systematic_trading_lab.providers import FixtureProvider, IntradayFixtureProvider
from systematic_trading_lab.storage import StorageLayout
from systematic_trading_lab.universe import load_intraday_universe, load_research_universe


def test_cli_inspects_intraday_plan_without_creating_runtime_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime_home = tmp_path / "runtime"
    arguments = parser().parse_args(
        [
            "experiment",
            "inspect-intraday-plan",
            "--spec",
            "config/research/intraday-campaign-v1.json",
        ]
    )

    assert run(arguments, Settings(TradingMode.OFFLINE, runtime_home)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["campaign_id"] == "intraday-research-v1"
    assert result["status"] == "preregistered"
    assert result["search_budget"] == 60
    assert result["reserved_candidate_ordinals"] == list(range(1, 61))
    assert result["protected_holdout_authority"] is False
    assert not runtime_home.exists()


def test_cli_seals_intraday_plan_and_blocks_arbitrary_campaign_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(TradingMode.OFFLINE, tmp_path)
    plan_arguments = parser().parse_args(
        [
            "experiment",
            "plan-intraday",
            "--spec",
            "config/research/intraday-campaign-v1.json",
        ]
    )

    assert run(plan_arguments, settings) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["status"] == "sealed"
    assert planned["reserved_candidates"] == 60
    registry = ExperimentRegistry(StorageLayout(tmp_path).experiments)
    assert registry.get_campaign("intraday-research-v1")["status"] == "sealed"
    reservations = registry.list("intraday-research-v1")
    assert len(reservations) == 60
    assert {record["status"] for record in reservations} == {"pending"}
    reservation_specs = [record["spec_json"] for record in reservations]
    assert all(isinstance(spec, dict) for spec in reservation_specs)
    assert sorted(
        int(spec["candidate_ordinal"]) for spec in reservation_specs if isinstance(spec, dict)
    ) == list(range(1, 61))
    assert {
        str(spec["schema_version"]) for spec in reservation_specs if isinstance(spec, dict)
    } == {"intraday-candidate-reservation-v1"}

    imported = DatasetService(StorageLayout(tmp_path)).import_from(
        IntradayFixtureProvider(),
        intraday_fixture_symbols(),
        Timeframe.FIVE_MINUTES,
        intraday_fixture_request(Timeframe.FIVE_MINUTES),
        load_intraday_universe(Timeframe.FIVE_MINUTES),
    )
    arbitrary = parser().parse_args(
        [
            "experiment",
            "run-intraday",
            "not-reserved",
            "--campaign",
            "intraday-research-v1",
            "--strategy",
            "cash",
            "--candidate-ordinal",
            "1",
            "--code-commit",
            "changed",
            "--dataset",
            imported.dataset_id,
            "--timeframe",
            "5m",
            "--split",
            "training",
            "--start",
            "2025-11-26T14:30:00Z",
            "--end",
            "2025-11-28T17:55:00Z",
            "--reason",
            "attempted plan bypass",
        ]
    )

    with pytest.raises(ExperimentError, match="active campaign not found"):
        run(arbitrary, settings)
    assert len(registry.list("intraday-research-v1")) == 60


def test_cli_derives_planned_intraday_candidate_before_execution(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(TradingMode.OFFLINE, tmp_path)
    assert (
        run(
            parser().parse_args(
                [
                    "experiment",
                    "plan-intraday",
                    "--spec",
                    "config/research/intraday-campaign-v1.json",
                ]
            ),
            settings,
        )
        == 0
    )
    capsys.readouterr()
    manifest = {
        "identity": {"dataset_id": "sealed-training", "fingerprint": "dataset-fingerprint"},
        "provider": "alpaca",
        "timeframe": "5m",
        "adjustment_policy": "provider-adjusted-all-v1",
        "calendar_policy": "XNYS-regular-session-bars-v1",
        "timestamp_policy": "bar-open-utc-v1",
        "requested_range": {
            "start": "2025-07-01T13:30:00Z",
            "end": "2025-12-31T20:55:00Z",
        },
        "actual_range": {
            "start": "2025-07-01T13:30:00Z",
            "end": "2025-12-31T20:55:00Z",
        },
        "symbols": [{"value": "SPY"}, {"value": "QQQ"}],
        "universe_id": "liquid-etfs-intraday-5m-v1",
        "universe_fingerprint": "6ac4a8269f8e352536f52ddc0a3000e0b39c5551c33c03959c20a640cfddeca9",
    }
    monkeypatch.setattr(DatasetService, "validate", lambda self, dataset_id: {"valid": True})
    monkeypatch.setattr(DatasetService, "describe", lambda self, dataset_id: manifest)
    executed: list[object] = []
    monkeypatch.setattr(
        "systematic_trading_lab.cli.run_cataloged_intraday_experiment",
        lambda registry, service, spec, reports, **kwargs: executed.append(spec),
    )

    arguments = parser().parse_args(
        [
            "experiment",
            "run-planned-intraday",
            "intraday-research-v1-previous-bar-momentum-training-harsher-cost",
            "--campaign",
            "intraday-research-v1",
            "--dataset",
            "sealed-training",
        ]
    )

    assert run(arguments, settings) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["status"] == "pending"
    assert record["campaign_plan_fingerprint"] == (
        "ce81be36d02cc15f421390bf3d3787714bb0b025797ccfb8de2c1d1236052c1a"
    )
    assert record["spec_json"]["candidate_ordinal"] == 23
    assert record["spec_json"]["slippage_bps"] == "20"
    assert record["spec_json"]["commission_bps"] == "5"
    assert record["spec_json"]["execution_delay_bars"] == 1
    assert record["spec_json"]["parent_candidate"].endswith("training-base")
    assert len(executed) == 1

    with pytest.raises(ExperimentError, match="stored intraday reservation differs"):
        run(arguments, settings)
    retry_record = ExperimentRegistry(StorageLayout(tmp_path).experiments).get(
        "intraday-research-v1-previous-bar-momentum-training-harsher-cost"
    )
    assert retry_record["status"] == "pending"
    assert retry_record["failure_info"] is None
    assert len(executed) == 1


def test_cli_retains_failed_planned_intraday_dataset_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(TradingMode.OFFLINE, tmp_path)
    assert (
        run(
            parser().parse_args(
                [
                    "experiment",
                    "plan-intraday",
                    "--spec",
                    "config/research/intraday-campaign-v1.json",
                ]
            ),
            settings,
        )
        == 0
    )
    monkeypatch.setattr(
        DatasetService,
        "describe",
        lambda self, dataset_id: (_ for _ in ()).throw(KeyError("dataset not found")),
    )
    experiment_id = "intraday-research-v1-cash-training-base"

    with pytest.raises(KeyError, match="dataset not found"):
        run(
            parser().parse_args(
                [
                    "experiment",
                    "run-planned-intraday",
                    experiment_id,
                    "--campaign",
                    "intraday-research-v1",
                    "--dataset",
                    "missing-dataset",
                ]
            ),
            settings,
        )

    record = ExperimentRegistry(StorageLayout(tmp_path).experiments).get(experiment_id)
    assert record["status"] == "failed"
    assert record["failure_info"] == "KeyError: 'dataset not found'"
    reservation_spec = record["spec_json"]
    assert isinstance(reservation_spec, dict)
    assert reservation_spec["schema_version"] == "intraday-candidate-reservation-v1"


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


def test_intraday_assessment_does_not_accept_a_policy_override(tmp_path: Path) -> None:
    policy = json.loads(
        Path("config/research/intraday-qualification-policy-v1.json").read_text(encoding="utf-8")
    )
    policy["gates"][0]["threshold"] = "0"
    unreviewed = tmp_path / "unreviewed.json"
    unreviewed.write_text(json.dumps(policy), encoding="utf-8")
    arguments = parser().parse_args(
        [
            "experiment",
            "assess-intraday",
            "--base",
            "candidate",
            "--policy",
            str(unreviewed),
        ]
    )

    with pytest.raises(ValueError, match="differs from the committed reviewed policy"):
        run(arguments, Settings(TradingMode.OFFLINE, tmp_path))
