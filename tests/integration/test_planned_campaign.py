import inspect
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

import systematic_trading_lab.campaign_specs as campaign_specs
import systematic_trading_lab.experiment_runner as experiment_runner
from systematic_trading_lab.backtesting import CostModel
from systematic_trading_lab.campaign_specs import (
    RAPID_002_CAMPAIGN_ID,
    build_rapid_002_controlled_plan,
    load_training_campaign_plan,
)
from systematic_trading_lab.cli import parser, run
from systematic_trading_lab.config import Settings
from systematic_trading_lab.datasets import DatasetService, fixture_request, fixture_symbols
from systematic_trading_lab.domain import OHLCVBar, Timeframe, TimestampRange, TradingMode
from systematic_trading_lab.experiment_runner import (
    run_cataloged_experiment,
    run_planned_cataloged_experiment,
)
from systematic_trading_lab.experiments import ExperimentError, ExperimentRegistry, ExperimentSpec
from systematic_trading_lab.fingerprints import canonical_json
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
    assert "pre_registered" not in inspect.signature(run_cataloged_experiment).parameters
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


def _rapid_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> campaign_specs.ControlledValidationCampaignPlan:
    source = campaign_specs._rapid_002_source_payload("f" * 40)
    monkeypatch.setattr(
        campaign_specs, "rapid_002_execution_source_identity", lambda **_kwargs: source
    )
    return build_rapid_002_controlled_plan()


def _rapid_dataset_manifest() -> dict[str, object]:
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


def test_rapid_002_seal_is_atomic_reserved_and_immutable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _rapid_plan(monkeypatch)
    blocked = ExperimentRegistry(tmp_path / "blocked.sqlite3")
    with pytest.raises(ExperimentError, match="reserved for a sealed plan"):
        blocked.create_campaign(RAPID_002_CAMPAIGN_ID, "bypass", 28)
    blocked.create_campaign("collision", "Collision", 1)
    blocked.create_experiment(
        replace(plan.candidates[-1].spec, campaign_id="collision", parent_candidate=None)
    )

    with pytest.raises(ExperimentError, match="sealed campaign already exists"):
        blocked.create_planned_campaign(plan.payload)
    with pytest.raises(KeyError, match="campaign not found"):
        blocked.get_campaign(RAPID_002_CAMPAIGN_ID)
    assert blocked.list(RAPID_002_CAMPAIGN_ID) == []

    registry = ExperimentRegistry(tmp_path / "sealed.sqlite3")
    sealed = registry.create_planned_campaign(plan.payload)
    assert sealed["declared_candidates"] == 28
    assert len(registry.list(RAPID_002_CAMPAIGN_ID)) == 28
    assert registry.get_controlled_validation_plan(RAPID_002_CAMPAIGN_ID) == plan

    with (
        sqlite3.connect(registry.path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="reservation is immutable"),
    ):
        connection.execute(
            "UPDATE experiments SET spec_json = '{}' WHERE experiment_id = ?",
            (plan.candidates[0].spec.experiment_id,),
        )
    with (
        sqlite3.connect(registry.path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="cannot gain reservations"),
    ):
        connection.execute(
            """
            INSERT INTO experiments
            (experiment_id, campaign_id, spec_json, split, status,
             qualification_state, created_at, campaign_plan_fingerprint)
            VALUES ('extra', ?, '{}', 'validation', 'pending', 'not-evaluated',
                    '2026-08-14T00:00:00+00:00', ?)
            """,
            (RAPID_002_CAMPAIGN_ID, plan.plan_fingerprint),
        )
    with (
        sqlite3.connect(registry.path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="sealed plan is immutable"),
    ):
        connection.execute(
            "DELETE FROM campaign_plans WHERE campaign_id = ?", (RAPID_002_CAMPAIGN_ID,)
        )


def test_rapid_002_seal_rejects_a_substituted_execution_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _rapid_plan(monkeypatch)
    changed = json.loads(json.dumps(plan.payload))
    source = changed["execution_source"]
    assert isinstance(source, dict)
    source["execution_code_commit"] = "e" * 40

    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    with pytest.raises(ExperimentError, match="differs from exact merged main"):
        registry.create_planned_campaign(changed)
    with pytest.raises(KeyError, match="campaign not found"):
        registry.get_campaign(RAPID_002_CAMPAIGN_ID)


def test_rapid_002_tampering_fails_before_claim_or_dataset_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = StorageLayout(tmp_path)
    plan = _rapid_plan(monkeypatch)
    registry = ExperimentRegistry(layout.experiments)
    registry.create_planned_campaign(plan.payload)
    experiment_id = "r2-rmm-base-2023"
    record = registry.get(experiment_id)
    spec = record["spec_json"]
    assert isinstance(spec, dict)
    spec["creation_reason"] = "substituted"
    with sqlite3.connect(registry.path) as connection:
        connection.execute("DROP TRIGGER rapid_002_reservation_no_identity_update")
        connection.execute(
            "UPDATE experiments SET spec_json = ? WHERE experiment_id = ?",
            (canonical_json(spec), experiment_id),
        )
    dataset_reads: list[str] = []

    def audited_validation(self: DatasetService, dataset_id: str) -> dict[str, object]:
        dataset_reads.append(dataset_id)
        return {"valid": True}

    monkeypatch.setattr(DatasetService, "validate", audited_validation)
    with pytest.raises(ExperimentError, match="reservations differ"):
        run_planned_cataloged_experiment(
            registry, DatasetService(layout), experiment_id, layout.reports
        )
    assert dataset_reads == []
    assert registry.get(experiment_id)["status"] == "pending"


def test_rapid_002_runner_derives_every_execution_model_from_the_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _rapid_plan(monkeypatch)
    observed: dict[str, tuple[Decimal, Decimal, Decimal, int]] = {}

    def valid_dataset(self: DatasetService, dataset_id: str) -> dict[str, object]:
        return {"valid": dataset_id == campaign_specs.RAPID_002_DATASET_ID}

    def describe_dataset(self: DatasetService, dataset_id: str) -> dict[str, object]:
        assert dataset_id == campaign_specs.RAPID_002_DATASET_ID
        return _rapid_dataset_manifest()

    def capture_inputs(
        registry: ExperimentRegistry,
        datasets: DatasetService,
        spec: object,
        output_directory: Path,
        initial_cash: Decimal,
        costs: object,
        fill_delay_bars: int,
        *,
        planned: bool,
    ) -> object:
        assert planned
        assert isinstance(spec, ExperimentSpec)
        assert isinstance(costs, CostModel)
        observed[spec.experiment_id] = (
            initial_cash,
            costs.slippage_bps,
            costs.commission_bps,
            fill_delay_bars,
        )
        return object()

    monkeypatch.setattr(DatasetService, "validate", valid_dataset)
    monkeypatch.setattr(DatasetService, "describe", describe_dataset)
    monkeypatch.setattr(experiment_runner, "_run_claimed_cataloged_experiment", capture_inputs)
    experiment_ids = (
        "r2-rmm-base-2025",
        "r2-rmm-cost2x-2025",
        "r2-rmm-delay2-2025",
        "r2-rmm-stress-a-2025",
        "r2-rmm-stress-b-2025",
    )
    for experiment_id in experiment_ids:
        layout = StorageLayout(tmp_path / experiment_id)
        registry = ExperimentRegistry(layout.experiments)
        registry.create_planned_campaign(plan.payload)
        run_planned_cataloged_experiment(
            registry, DatasetService(layout), experiment_id, layout.reports
        )

    assert observed == {
        "r2-rmm-base-2025": (Decimal("100000"), Decimal("5"), Decimal("1"), 1),
        "r2-rmm-cost2x-2025": (Decimal("100000"), Decimal("10"), Decimal("2"), 1),
        "r2-rmm-delay2-2025": (Decimal("100000"), Decimal("5"), Decimal("1"), 2),
        "r2-rmm-stress-a-2025": (Decimal("100000"), Decimal("10"), Decimal("2"), 2),
        "r2-rmm-stress-b-2025": (Decimal("100000"), Decimal("20"), Decimal("5"), 3),
    }


def test_rapid_002_completed_and_failed_reservations_cannot_run_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = StorageLayout(tmp_path)
    plan = _rapid_plan(monkeypatch)
    registry = ExperimentRegistry(layout.experiments)
    registry.create_planned_campaign(plan.payload)
    completed = plan.candidates[0].spec
    failed = plan.candidates[1].spec
    registry._claim_planned(completed)
    registry._complete_planned(completed, {}, [], [])
    registry.fail(failed.experiment_id, "forced terminal evidence")

    for experiment_id in (completed.experiment_id, failed.experiment_id):
        with pytest.raises(ExperimentError, match="not pending"):
            run_planned_cataloged_experiment(
                registry, DatasetService(layout), experiment_id, layout.reports
            )
