import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from systematic_trading_lab.campaign_specs import load_training_campaign_plan
from systematic_trading_lab.cli import parser, run
from systematic_trading_lab.config import Settings
from systematic_trading_lab.datasets import DatasetService, fixture_request, fixture_symbols
from systematic_trading_lab.domain import OHLCVBar, Timeframe, TimestampRange, TradingMode
from systematic_trading_lab.experiment_runner import run_cataloged_experiment
from systematic_trading_lab.experiments import ExperimentError, ExperimentRegistry
from systematic_trading_lab.providers import FixtureProvider
from systematic_trading_lab.storage import StorageLayout
from systematic_trading_lab.universe import load_research_universe


def test_registry_adds_plan_fingerprint_to_existing_database(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE experiments (experiment_id TEXT PRIMARY KEY)")

    ExperimentRegistry(path)

    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(experiments)")}
    assert "campaign_plan_fingerprint" in columns
    assert "execution_provenance" in columns


def test_sealed_training_plan_preregisters_and_runs_only_stored_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = StorageLayout(tmp_path)
    service = DatasetService(layout)
    universe = load_research_universe()
    imported = service.import_from(
        FixtureProvider(), fixture_symbols(), Timeframe.DAILY, fixture_request(), universe
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "schema_version": "training-campaign-plan-v1",
                "campaign_id": "sealed-training",
                "name": "Sealed training",
                "search_budget": 1,
                "code_commit": "abc123",
                "dataset_id": imported.dataset_id,
                "dataset_fingerprint": imported.fingerprint,
                "universe_id": universe.universe_id,
                "universe_fingerprint": universe.universe_fingerprint,
                "candidates": [
                    {
                        "experiment_id": "sealed-benchmark",
                        "role": "benchmark",
                        "strategy_id": "fixed-weight",
                        "strategy_version": "1",
                        "strategy_family": "allocation",
                        "parameters": {},
                        "start_timestamp": "2025-01-06T00:00:00Z",
                        "end_timestamp": "2025-01-10T00:00:00Z",
                        "random_seed": 0,
                        "creation_reason": "sealed fixture benchmark",
                        "parent_candidate": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(TradingMode.OFFLINE, tmp_path)
    assert (
        run(
            parser().parse_args(["experiment", "plan-training", "--spec", str(plan_path)]), settings
        )
        == 0
    )

    registry = ExperimentRegistry(layout.experiments)
    plan = load_training_campaign_plan(plan_path)
    record = registry.get("sealed-benchmark")
    assert record["status"] == "pending"
    assert record["campaign_plan_fingerprint"] == plan.plan_fingerprint
    assert (
        registry.get_campaign_plan("sealed-training")["plan_fingerprint"] == plan.plan_fingerprint
    )
    invalid_plan = dict(plan.payload)
    invalid_plan["schema_version"] = "unreviewed"
    with pytest.raises(ValueError, match="schema differs"):
        registry.create_planned_campaign(invalid_plan)
    with pytest.raises(ExperimentError, match="sealed campaign already exists"):
        registry.create_planned_campaign(plan.payload)
    with pytest.raises(ExperimentError, match="not pending"):
        registry.claim("sealed-benchmark")

    reads: list[TimestampRange] = []
    original = DatasetService.load_bars_range

    def audited_range_read(
        self: DatasetService,
        dataset_id: str,
        requested: TimestampRange,
        *,
        expected_fingerprint: str,
        expected_universe_id: str,
        expected_universe_fingerprint: str,
    ) -> tuple[OHLCVBar, ...]:
        reads.append(requested)
        return original(
            self,
            dataset_id,
            requested,
            expected_fingerprint=expected_fingerprint,
            expected_universe_id=expected_universe_id,
            expected_universe_fingerprint=expected_universe_fingerprint,
        )

    monkeypatch.setattr(DatasetService, "load_bars_range", audited_range_read)
    stored = registry.get_planned_spec("sealed-benchmark")
    with pytest.raises(ExperimentError, match="active campaign not found"):
        registry.create_experiment(replace(stored, experiment_id="undeclared"))
    with pytest.raises(ExperimentError, match="differs"):
        run_cataloged_experiment(
            registry,
            service,
            replace(stored, creation_reason="override"),
            layout.reports,
            pre_registered=True,
        )
    assert reads == []

    assert (
        run(parser().parse_args(["experiment", "run-planned", "sealed-benchmark"]), settings) == 0
    )
    assert reads == [
        TimestampRange(datetime(2025, 1, 6, tzinfo=UTC), datetime(2025, 1, 10, tzinfo=UTC))
    ]
    completed = registry.get("sealed-benchmark")
    assert completed["status"] == "completed"
    assert completed["execution_provenance"] == "controlled-run"
