import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

import systematic_trading_lab.campaign_specs as campaign_specs
import systematic_trading_lab.cli as cli
from systematic_trading_lab.campaign_specs import (
    RAPID_002_CAMPAIGN_ID,
    load_intraday_research_campaign_plan,
)
from systematic_trading_lab.cli import parser, run
from systematic_trading_lab.config import Settings
from systematic_trading_lab.datasets import (
    DatasetService,
    DatasetValidationError,
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


def planned_intraday_manifests() -> dict[str, dict[str, object]]:
    plan = load_intraday_research_campaign_plan(Path("config/research/intraday-campaign-v2.json"))
    manifests: dict[str, dict[str, object]] = {}
    for period in plan.periods:
        start = period.start_timestamp.isoformat().replace("+00:00", "Z")
        end = period.end_timestamp.isoformat().replace("+00:00", "Z")
        manifests[period.role] = {
            "identity": {
                "dataset_id": f"sealed-{period.role}",
                "fingerprint": f"fingerprint-{period.role}",
            },
            "provider": "alpaca-historical-v2",
            "feed": "iex",
            "timeframe": "5m",
            "adjustment_policy": "provider-adjusted-all-v1",
            "calendar_policy": "XNYS-regular-session-bars-v1",
            "timestamp_policy": "bar-open-utc-v1",
            "requested_range": {"start": start, "end": end},
            "actual_range": {"start": start, "end": end},
            "symbols": [{"value": "SPY"}, {"value": "QQQ"}],
            "universe_id": "liquid-etfs-intraday-5m-v1",
            "universe_fingerprint": (
                "6ac4a8269f8e352536f52ddc0a3000e0b39c5551c33c03959c20a640cfddeca9"
            ),
        }
    return manifests


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


def test_cli_verifies_artifacts_before_atomically_sealing_rapid_002(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = campaign_specs._rapid_002_source_payload("f" * 40)
    monkeypatch.setattr(campaign_specs, "rapid_002_execution_source_identity", lambda: source)
    monkeypatch.setattr(
        cli,
        "verify_rapid_002_candidate_export",
        lambda path: {
            "path": str(path),
            "candidate_id": campaign_specs.RAPID_002_CANDIDATE_ID,
            "candidate_fingerprint": campaign_specs.RAPID_002_CANDIDATE_FINGERPRINT,
            "file_sha256": campaign_specs.RAPID_002_CANDIDATE_EXPORT_SHA256,
            "authority": {},
        },
    )

    def validate(self: DatasetService, dataset_id: str) -> dict[str, object]:
        return {"valid": dataset_id == campaign_specs.RAPID_002_DATASET_ID}

    def describe(self: DatasetService, dataset_id: str) -> dict[str, object]:
        assert dataset_id == campaign_specs.RAPID_002_DATASET_ID
        return {
            "identity": {
                "dataset_id": campaign_specs.RAPID_002_DATASET_ID,
                "fingerprint": campaign_specs.RAPID_002_DATASET_FINGERPRINT,
            },
            "provider": "alpaca-historical-v2",
            "symbols": [{"value": symbol} for symbol in ("SPY", "QQQ", "IWM", "TLT", "GLD")],
            "timeframe": "1d",
            "requested_range": {
                "start": "2020-07-27T00:00:00Z",
                "end": "2026-07-31T00:00:00Z",
            },
            "actual_range": {
                "start": "2020-07-27T00:00:00Z",
                "end": "2026-07-31T00:00:00Z",
            },
            "adjustment_policy": "provider-adjusted-all-v1",
            "calendar_policy": "XNYS-v1",
            "universe_id": campaign_specs.RAPID_002_UNIVERSE_ID,
            "universe_fingerprint": campaign_specs.RAPID_002_UNIVERSE_FINGERPRINT,
        }

    monkeypatch.setattr(DatasetService, "validate", validate)
    monkeypatch.setattr(DatasetService, "describe", describe)
    arguments = parser().parse_args(
        [
            "experiment",
            "plan-rapid-002",
            "--candidate-export",
            str(tmp_path / "candidate.json"),
            "--evidence-manifest",
            "config/research/qualification-evidence-rapid-002-rmm-v1.json",
            "--proposal",
            "config/research/qualification-proposal-rapid-002-rmm-v1.json",
        ]
    )

    assert run(arguments, Settings(TradingMode.OFFLINE, tmp_path)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["campaign_id"] == RAPID_002_CAMPAIGN_ID
    assert result["declared_candidates"] == 28
    assert result["independent_evaluation_authority"] is False
    assert result["paper_authority"] is False
    records = ExperimentRegistry(StorageLayout(tmp_path).experiments).list(RAPID_002_CAMPAIGN_ID)
    assert len(records) == 28
    assert {record["status"] for record in records} == {"pending"}


def test_cli_seals_campaign_v2_and_blocks_arbitrary_campaign_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(TradingMode.OFFLINE, tmp_path)
    plan_arguments = parser().parse_args(
        [
            "experiment",
            "plan-intraday",
            "--spec",
            "config/research/intraday-campaign-v2.json",
        ]
    )

    assert run(plan_arguments, settings) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["status"] == "sealed"
    assert planned["reserved_candidates"] == 60
    registry = ExperimentRegistry(StorageLayout(tmp_path).experiments)
    assert registry.get_campaign("intraday-research-v2")["status"] == "sealed"
    reservations = registry.list("intraday-research-v2")
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
            "intraday-research-v2",
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
    assert len(registry.list("intraday-research-v2")) == 60


@pytest.mark.parametrize("campaign_id", ("intraday-research-v1", "intraday-research-v2"))
def test_reserved_intraday_campaign_ids_cannot_bypass_sealed_plans(
    tmp_path: Path, campaign_id: str
) -> None:
    registry = ExperimentRegistry(StorageLayout(tmp_path).experiments)

    with pytest.raises(ExperimentError, match="reserved for a sealed plan"):
        registry.create_campaign(campaign_id, "Bypass", 1)


def test_cli_validates_and_atomically_binds_planned_intraday_datasets(
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
                    "config/research/intraday-campaign-v2.json",
                ]
            ),
            settings,
        )
        == 0
    )
    capsys.readouterr()
    manifests = planned_intraday_manifests()
    validated: list[str] = []

    def validate(self: DatasetService, dataset_id: str) -> dict[str, object]:
        validated.append(dataset_id)
        return {"valid": True}

    def describe(self: DatasetService, dataset_id: str) -> dict[str, object]:
        for manifest in manifests.values():
            identity = manifest["identity"]
            assert isinstance(identity, dict)
            if identity["dataset_id"] == dataset_id:
                return manifest
        raise KeyError(dataset_id)

    monkeypatch.setattr(
        DatasetService,
        "validate",
        validate,
    )
    monkeypatch.setattr(DatasetService, "describe", describe)
    arguments = parser().parse_args(
        [
            "experiment",
            "bind-intraday-datasets",
            "--campaign",
            "intraday-research-v2",
            "--training",
            "sealed-training",
            "--validation-a",
            "sealed-validation-a",
            "--validation-b",
            "sealed-validation-b",
            "--validation-c",
            "sealed-validation-c",
        ]
    )

    assert run(arguments, settings) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["bound_candidates"] == 60
    assert result["plan_fingerprint"] == (
        "52db8a27fa4ff86865ab69b6bd7456899329ef3b861a582e59ab32904c03c122"
    )
    registry = ExperimentRegistry(StorageLayout(tmp_path).experiments)
    records = registry.list("intraday-research-v2")
    assert len(records) == 60
    assert {record["status"] for record in records} == {"pending"}
    assert {
        record["spec_json"]["schema_version"]
        for record in records
        if isinstance(record["spec_json"], dict)
    } == {"intraday-experiment-v1"}
    record = registry.get("intraday-research-v2-previous-bar-momentum-training-harsher-cost")
    spec_json = cast(dict[str, object], record["spec_json"])
    assert spec_json["candidate_ordinal"] == 23
    assert spec_json["slippage_bps"] == "20"
    assert spec_json["commission_bps"] == "5"
    assert spec_json["execution_delay_bars"] == 1
    assert str(spec_json["parent_candidate"]).endswith("training-base")
    assert validated == [
        "sealed-training",
        "sealed-validation-a",
        "sealed-validation-b",
        "sealed-validation-c",
    ]

    with pytest.raises(ExperimentError, match="stored intraday reservations differ"):
        run(arguments, settings)
    assert all(
        record["spec_json"]["schema_version"] == "intraday-experiment-v1"
        for record in registry.list("intraday-research-v2")
        if isinstance(record["spec_json"], dict)
    )

    with pytest.raises(SystemExit):
        parser().parse_args(
            [
                "experiment",
                "run-planned-intraday",
                "intraday-research-v2-cash-training-base",
            ]
        )
    assert registry.get("intraday-research-v2-cash-training-base")["status"] == "pending"


def test_cli_invalid_intraday_dataset_preflight_leaves_every_reservation_pending(
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
                    "config/research/intraday-campaign-v2.json",
                ]
            ),
            settings,
        )
        == 0
    )
    validated: list[str] = []

    def validate(self: DatasetService, dataset_id: str) -> dict[str, object]:
        validated.append(dataset_id)
        return {"valid": dataset_id != "sealed-validation-c"}

    monkeypatch.setattr(
        DatasetService,
        "validate",
        validate,
    )
    monkeypatch.setattr(
        DatasetService,
        "describe",
        lambda *args, **kwargs: pytest.fail("invalid dataset preflight described a manifest"),
    )

    with pytest.raises(DatasetValidationError, match="integrity validation failed: validation-c"):
        run(
            parser().parse_args(
                [
                    "experiment",
                    "bind-intraday-datasets",
                    "--campaign",
                    "intraday-research-v2",
                    "--training",
                    "sealed-training",
                    "--validation-a",
                    "sealed-validation-a",
                    "--validation-b",
                    "sealed-validation-b",
                    "--validation-c",
                    "sealed-validation-c",
                ]
            ),
            settings,
        )

    assert validated == [
        "sealed-training",
        "sealed-validation-a",
        "sealed-validation-b",
        "sealed-validation-c",
    ]
    records = ExperimentRegistry(StorageLayout(tmp_path).experiments).list("intraday-research-v2")
    assert {record["status"] for record in records} == {"pending"}
    assert {
        record["spec_json"]["schema_version"]
        for record in records
        if isinstance(record["spec_json"], dict)
    } == {"intraday-candidate-reservation-v1"}


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
