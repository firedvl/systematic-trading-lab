import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from systematic_trading_lab.backtesting import CostModel
from systematic_trading_lab.campaign_specs import (
    build_planned_intraday_experiments,
    load_intraday_research_campaign_plan,
)
from systematic_trading_lab.datasets import (
    DatasetService,
    fixture_request,
    fixture_symbols,
    intraday_fixture_request,
    intraday_fixture_symbols,
)
from systematic_trading_lab.domain import OHLCVBar, Symbol, Timeframe, TimestampRange
from systematic_trading_lab.experiment_runner import (
    SensitivityVariant,
    WalkForwardSplit,
    comparison_report,
    run_cataloged_experiment,
    run_cataloged_intraday_experiment,
    run_experiment,
    run_holdout_experiment,
    run_sensitivity,
    validate_walk_forward,
    walk_forward_specs,
)
from systematic_trading_lab.experiments import (
    ExperimentError,
    ExperimentRegistry,
    ExperimentSpec,
    ExperimentSplit,
    HoldoutAccessError,
    IntradayExperimentSpec,
)
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.intraday_qualification import (
    evaluate_registered_intraday_qualification,
    load_intraday_qualification_policy,
)
from systematic_trading_lab.parquet import to_parquet
from systematic_trading_lab.providers import FixtureProvider, IntradayFixtureProvider
from systematic_trading_lab.rapid_data import import_local_data, resolve_research_dataset
from systematic_trading_lab.rapid_store import RapidResearchStore
from systematic_trading_lab.storage import StorageLayout
from systematic_trading_lab.universe import load_intraday_universe, load_research_universe


def bars() -> tuple[OHLCVBar, ...]:
    start = datetime(2025, 1, 6, tzinfo=UTC)
    return tuple(
        OHLCVBar(
            Symbol("SPY"),
            start + timedelta(days=index),
            Decimal(str(price)),
            Decimal(str(price + 2)),
            Decimal(str(price - 2)),
            Decimal(str(price + 1)),
            100,
        )
        for index, price in enumerate((100, 101, 102, 103))
    )


def spec(source: tuple[OHLCVBar, ...], experiment_id: str = "candidate") -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id=experiment_id,
        campaign_id="campaign",
        strategy_id="buy-and-hold",
        strategy_version="1",
        strategy_family="baseline",
        code_commit="abc123",
        dataset_id="fixture",
        dataset_fingerprint=fingerprint(tuple(bar.to_record() for bar in source)),
        universe_id="liquid-etfs-v1",
        universe_fingerprint="universe-fingerprint-1",
        parameters={},
        cost_model_version="conservative-bps-v1",
        execution_model_version="next-bar-v1",
        split=ExperimentSplit.VALIDATION,
        start_timestamp=source[0].timestamp,
        end_timestamp=source[-1].timestamp,
        random_seed=0,
        creation_reason="runner test",
    )


def holdout_setup(
    tmp_path: Path,
) -> tuple[ExperimentRegistry, DatasetService, ExperimentSpec]:
    layout = StorageLayout(tmp_path)
    datasets = DatasetService(layout)
    controlled_request = TimestampRange(
        datetime(2025, 2, 3, tzinfo=UTC), datetime(2025, 2, 7, tzinfo=UTC)
    )
    imported = datasets.import_from(
        FixtureProvider(),
        fixture_symbols(),
        Timeframe.DAILY,
        controlled_request,
        load_research_universe(),
    )
    registry = ExperimentRegistry(layout.experiments)
    registry.create_campaign("holdout-campaign", "Controlled holdout", 1)
    qualification: dict[str, object] = {
        "experiment_id": "qualified-candidate",
        "state": "qualified",
        "gates": [{"name": "all-gates", "approved": True, "passed": True}],
    }
    qualification["report_fingerprint"] = fingerprint(qualification)
    report: dict[str, object] = {
        "schema_version": "qualification-evidence-v1",
        "manifest_id": "fixture-manifest",
        "manifest_fingerprint": "fixture-manifest-fingerprint",
        "proposal_id": "approved-proposal",
        "proposal_fingerprint": "approved-proposal-fingerprint",
        "campaign_id": "holdout-campaign",
        "candidate_id": "qualified-candidate",
        "strategy_id": "buy-and-hold",
        "candidate_specification": {
            "strategy_id": "buy-and-hold",
            "strategy_version": "1",
            "strategy_family": "baseline",
            "code_commit": "abc123",
            "parameters": {},
            "cost_model_version": "conservative-bps-v1",
            "execution_model_version": "next-bar-v1",
            "dataset_id": imported.dataset_id,
            "dataset_fingerprint": imported.fingerprint,
            "universe_id": load_research_universe().universe_id,
            "universe_fingerprint": load_research_universe().universe_fingerprint,
            "validation_start": "2025-02-03T00:00:00Z",
            "validation_end": "2025-02-04T00:00:00Z",
        },
        "source_experiment_ids": ["fixture-validation"],
        "metrics": {"total_return": "0.1"},
        "qualification": qualification,
    }
    report["evidence_fingerprint"] = fingerprint(report)
    registry._create_holdout_run_authorization(
        "fixture-authorization", report, "reviewer", "fixture-only control test"
    )
    holdout = ExperimentSpec(
        experiment_id="controlled-holdout",
        campaign_id="holdout-campaign",
        strategy_id="buy-and-hold",
        strategy_version="1",
        strategy_family="baseline",
        code_commit="abc123",
        dataset_id=imported.dataset_id,
        dataset_fingerprint=imported.fingerprint,
        universe_id=load_research_universe().universe_id,
        universe_fingerprint=load_research_universe().universe_fingerprint,
        parameters={},
        cost_model_version="conservative-bps-v1",
        execution_model_version="next-bar-v1",
        split=ExperimentSplit.HOLDOUT,
        start_timestamp=datetime(2025, 2, 5, tzinfo=UTC),
        end_timestamp=datetime(2025, 2, 7, tzinfo=UTC),
        random_seed=0,
        creation_reason="fixture-only controlled holdout",
        parent_candidate="qualified-candidate",
    )
    return registry, datasets, holdout


def test_walk_forward_splits_reject_leakage_and_fingerprint_deterministically() -> None:
    first = WalkForwardSplit(
        datetime(2020, 1, 1, tzinfo=UTC),
        datetime(2020, 12, 31, tzinfo=UTC),
        datetime(2021, 1, 1, tzinfo=UTC),
        datetime(2021, 6, 30, tzinfo=UTC),
    )
    second = WalkForwardSplit(
        datetime(2020, 7, 1, tzinfo=UTC),
        datetime(2021, 6, 30, tzinfo=UTC),
        datetime(2021, 7, 1, tzinfo=UTC),
        datetime(2021, 12, 31, tzinfo=UTC),
    )
    assert validate_walk_forward((first, second)) == validate_walk_forward((first, second))
    assert first.split_fingerprint == first.split_fingerprint
    candidates = walk_forward_specs(spec(bars()), (first, second))
    assert [candidate.split for candidate in candidates] == [
        ExperimentSplit.TRAINING,
        ExperimentSplit.VALIDATION,
        ExperimentSplit.TRAINING,
        ExperimentSplit.VALIDATION,
    ]
    assert all(candidate.parent_candidate == "candidate" for candidate in candidates)
    with pytest.raises(ValueError, match="training must end"):
        WalkForwardSplit(
            first.training_start,
            first.validation_start,
            first.training_end,
            first.validation_end,
        )
    with pytest.raises(ValueError, match="non-overlapping"):
        validate_walk_forward(
            (
                first,
                replace(
                    second,
                    training_end=first.validation_end - timedelta(days=1),
                    validation_start=first.validation_end,
                ),
            )
        )


def test_runner_records_completion_failure_and_blocks_holdout(tmp_path: Path) -> None:
    source = bars()
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    registry.create_campaign("campaign", "Runner", 3)
    result = run_experiment(registry, spec(source), source, tmp_path / "reports")
    record = registry.get("candidate")
    assert result.metrics.trade_count == 1
    assert record["status"] == "completed"
    assert record["execution_provenance"] == "legacy-manual"
    assert record["artifact_hashes_json"]

    broken = replace(spec(source, "broken"), strategy_id="unknown")
    with pytest.raises(ValueError, match="unknown"):
        run_experiment(registry, broken, source, tmp_path / "reports")
    assert registry.get("broken")["status"] == "failed"
    failed_report = comparison_report(registry, ("candidate", "broken"))
    failed_candidates = cast(list[dict[str, object]], failed_report["candidates"])
    assert failed_candidates[0]["metrics"] is None
    assert failed_candidates[0]["failure_info"]
    with pytest.raises(HoldoutAccessError):
        run_experiment(
            registry,
            replace(spec(source, "holdout"), split=ExperimentSplit.HOLDOUT),
            source,
            tmp_path / "reports",
        )
    with pytest.raises(HoldoutAccessError):
        run_cataloged_experiment(
            registry,
            DatasetService(StorageLayout(tmp_path / "data")),
            replace(spec(source, "cataloged-holdout"), split=ExperimentSplit.HOLDOUT),
            tmp_path / "reports",
        )


def test_cataloged_experiment_runner_rejects_intraday_dataset(tmp_path: Path) -> None:
    timeframe = Timeframe.FIVE_MINUTES
    requested = intraday_fixture_request(timeframe)
    universe = load_intraday_universe(timeframe)
    datasets = DatasetService(StorageLayout(tmp_path / "data"))
    imported = datasets.import_from(
        IntradayFixtureProvider(),
        intraday_fixture_symbols(),
        timeframe,
        requested,
        universe,
    )
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    registry.create_campaign("intraday-campaign", "Must remain daily-only", 1)
    intraday_spec = ExperimentSpec(
        experiment_id="intraday-candidate",
        campaign_id="intraday-campaign",
        strategy_id="buy-and-hold",
        strategy_version="1",
        strategy_family="baseline",
        code_commit="abc123",
        dataset_id=imported.dataset_id,
        dataset_fingerprint=imported.fingerprint,
        universe_id=universe.universe_id,
        universe_fingerprint=universe.universe_fingerprint,
        parameters={},
        cost_model_version="conservative-bps-v1",
        execution_model_version="next-bar-v1",
        split=ExperimentSplit.VALIDATION,
        start_timestamp=requested.start,
        end_timestamp=requested.end,
        random_seed=0,
        creation_reason="prove daily runner isolation",
    )

    with pytest.raises(ExperimentError, match="daily datasets only"):
        run_cataloged_experiment(registry, datasets, intraday_spec, tmp_path / "reports")

    assert registry.get(intraday_spec.experiment_id)["status"] == "failed"


def test_cataloged_intraday_runner_records_deterministic_zero_trade_report_and_failures(
    tmp_path: Path,
) -> None:
    timeframe = Timeframe.FIVE_MINUTES
    requested = intraday_fixture_request(timeframe)
    universe = load_intraday_universe(timeframe)
    layout = StorageLayout(tmp_path / "data")
    datasets = DatasetService(layout)
    imported = datasets.import_from(
        IntradayFixtureProvider(),
        intraday_fixture_symbols(),
        timeframe,
        requested,
        universe,
    )
    registry = ExperimentRegistry(layout.experiments)
    registry.create_campaign("m5b", "M5B fixed baselines", 2)
    base = IntradayExperimentSpec(
        experiment_id="m5b-cash",
        campaign_id="m5b",
        search_budget=2,
        candidate_ordinal=1,
        strategy_id="intraday-cash",
        strategy_version="1",
        strategy_family="intraday-cash-baseline",
        code_commit="abc123",
        dataset_id=imported.dataset_id,
        dataset_fingerprint=imported.fingerprint,
        universe_id=universe.universe_id,
        universe_fingerprint=universe.universe_fingerprint,
        parameters={},
        timeframe=timeframe.value,
        session_policy_version="XNYS-regular-session-flat-v1",
        bar_timestamp_semantics_version="bar-open-utc-v1",
        session_return_policy_version="XNYS-session-close-equity-v1",
        benchmark_policy_version="cash-and-continuous-underlying-v1",
        cost_model_version="conservative-bps-v1",
        slippage_bps=Decimal("5"),
        commission_bps=Decimal("1"),
        execution_model_version="deterministic-next-bar-open-v1",
        earliest_fill_semantics="completed-bar-next-bar-open-v1",
        execution_delay_bars=1,
        split=ExperimentSplit.TRAINING,
        start_timestamp=requested.start,
        end_timestamp=requested.end,
        random_seed=0,
        creation_reason="fixed cash baseline",
    )

    result = run_cataloged_intraday_experiment(registry, datasets, base, layout.reports)
    record = registry.get(base.experiment_id)
    stored_metrics = cast(dict[str, object], record["metrics_json"])
    report_path = Path(cast(list[str], record["artifact_locations_json"])[0])
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert result.trades == ()
    assert record["status"] == "completed"
    assert record["execution_provenance"] == "controlled-run"
    assert stored_metrics["fill_count"] == 0
    assert report["schema_version"] == "intraday-backtest-report-v1"
    assert report["provenance"]["timeframe"] == "5m"
    assert report["provenance"]["execution_delay_bars"] == 1
    assert report["configured_fill_delay_bars"] == 1
    assert report["report_fingerprint"] == cast(list[str], record["artifact_hashes_json"])[0]
    assert not layout.execution.exists()

    broken = replace(
        base,
        experiment_id="m5b-broken",
        candidate_ordinal=2,
        execution_model_version="unsupported-execution-v9",
    )
    with pytest.raises(ExperimentError, match="unsupported intraday execution model"):
        run_cataloged_intraday_experiment(registry, datasets, broken, layout.reports)
    failed = registry.get(broken.experiment_id)
    assert failed["status"] == "failed"
    assert "unsupported intraday execution model" in str(failed["failure_info"])
    assert not layout.execution.exists()

    evidence = evaluate_registered_intraday_qualification(
        registry,
        load_intraday_qualification_policy(
            Path("config/research/intraday-qualification-policy-v1.json")
        ),
        base.experiment_id,
        {},
        {},
    )
    campaign_sources = cast(list[dict[str, object]], evidence["campaign_sources"])
    search_accounting = cast(dict[str, object], evidence["search_accounting"])
    assert evidence["evidence_binding"] == "controlled-registry"
    assert evidence["state"] == "research-gates-failed"
    assert search_accounting["search_budget_accounted"] is True
    assert any(
        source["experiment_id"] == broken.experiment_id and source["status"] == "failed"
        for source in campaign_sources
    )

    failed_stress_evidence = evaluate_registered_intraday_qualification(
        registry,
        load_intraday_qualification_policy(
            Path("config/research/intraday-qualification-policy-v1.json")
        ),
        base.experiment_id,
        {"increased-cost": broken.experiment_id},
        {},
    )
    failed_stress_source = next(
        source
        for source in cast(list[dict[str, object]], failed_stress_evidence["sources"])
        if source["role"] == "higher-cost" and source["name"] == "increased-cost"
    )
    assert failed_stress_source["status"] == "failed"
    assert failed_stress_evidence["state"] == "research-gates-failed"

    reviewed_policy = load_intraday_qualification_policy(
        Path("config/research/intraday-qualification-policy-v1.json")
    )
    with pytest.raises(ValueError, match="differs from the committed reviewed policy"):
        evaluate_registered_intraday_qualification(
            registry,
            replace(reviewed_policy, fingerprint="unreviewed"),
            base.experiment_id,
            {},
            {},
        )

    daily = datasets.import_from(
        FixtureProvider(),
        fixture_symbols(),
        Timeframe.DAILY,
        fixture_request(),
        load_research_universe(),
    )
    daily_manifest = datasets.describe(daily.dataset_id)
    registry.create_campaign("m5b-daily-block", "Reject daily data", 1)
    wrong_timeframe = replace(
        base,
        experiment_id="m5b-daily-data",
        campaign_id="m5b-daily-block",
        search_budget=1,
        candidate_ordinal=1,
        dataset_id=daily.dataset_id,
        dataset_fingerprint=daily.fingerprint,
        universe_id=cast(str, daily_manifest["universe_id"]),
        universe_fingerprint=cast(str, daily_manifest["universe_fingerprint"]),
    )
    with pytest.raises(ExperimentError, match="timeframe does not match"):
        run_cataloged_intraday_experiment(registry, datasets, wrong_timeframe, layout.reports)
    assert registry.get(wrong_timeframe.experiment_id)["status"] == "failed"


def test_campaign_v2_binding_is_atomic_and_execution_requires_source_review(
    tmp_path: Path,
) -> None:
    layout = StorageLayout(tmp_path)
    registry = ExperimentRegistry(layout.experiments)
    datasets = DatasetService(layout)
    plan = load_intraday_research_campaign_plan(Path("config/research/intraday-campaign-v2.json"))
    registry.create_planned_intraday_campaign(plan.payload)
    manifests: dict[str, dict[str, object]] = {}
    for period in plan.periods:
        start = period.start_timestamp.isoformat().replace("+00:00", "Z")
        end = period.end_timestamp.isoformat().replace("+00:00", "Z")
        manifests[period.role] = {
            "identity": {
                "dataset_id": f"planned-{period.role}",
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
    planned_specs = build_planned_intraday_experiments(plan, manifests)
    specs_by_id = {planned.experiment_id: planned for planned in planned_specs}
    with sqlite3.connect(layout.experiments) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_final_intraday_binding
            BEFORE UPDATE OF spec_json ON experiments
            WHEN OLD.experiment_id =
                'intraday-research-v2-moving-average-trend-validation-c-plus-2-bars'
            BEGIN SELECT RAISE(ABORT, 'forced atomic binding failure'); END
            """
        )
    with pytest.raises(sqlite3.IntegrityError, match="forced atomic binding failure"):
        registry.bind_planned_intraday_experiments(planned_specs)
    assert {
        record["spec_json"]["schema_version"]
        for record in registry.list(plan.campaign_id)
        if isinstance(record["spec_json"], dict)
    } == {"intraday-candidate-reservation-v1"}
    with sqlite3.connect(layout.experiments) as connection:
        connection.execute("DROP TRIGGER reject_final_intraday_binding")
    registry.bind_planned_intraday_experiments(planned_specs)
    spec = specs_by_id["intraday-research-v2-cash-training-base"]
    assert {
        record["spec_json"]["schema_version"]
        for record in registry.list(plan.campaign_id)
        if isinstance(record["spec_json"], dict)
    } == {"intraday-experiment-v1"}
    with pytest.raises(ExperimentError, match="stored intraday reservations differ"):
        registry.bind_planned_intraday_experiments(planned_specs)
    with pytest.raises(ExperimentError, match="reviewed execution build"):
        run_cataloged_intraday_experiment(
            registry,
            datasets,
            spec,
            layout.reports,
            pre_registered=True,
        )
    assert registry.get(spec.experiment_id)["status"] == "pending"


def test_holdout_runner_consumes_authorization_before_exact_range_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, datasets, holdout = holdout_setup(tmp_path)
    original = datasets.load_bars_range
    reads: list[tuple[datetime, datetime]] = []

    def audited_range_read(
        dataset_id: str,
        requested: TimestampRange,
        *,
        expected_fingerprint: str,
        expected_universe_id: str,
        expected_universe_fingerprint: str,
    ) -> tuple[OHLCVBar, ...]:
        reads.append((requested.start, requested.end))
        return original(
            dataset_id,
            requested,
            expected_fingerprint=expected_fingerprint,
            expected_universe_id=expected_universe_id,
            expected_universe_fingerprint=expected_universe_fingerprint,
        )

    monkeypatch.setattr(datasets, "load_bars_range", audited_range_read)
    with pytest.raises(HoldoutAccessError, match="unused stored authorization"):
        run_holdout_experiment(registry, datasets, "missing-authorization", holdout)
    assert reads == []

    protected = run_holdout_experiment(registry, datasets, "fixture-authorization", holdout)

    assert reads == [(holdout.start_timestamp, holdout.end_timestamp)]
    assert protected["status"] == "completed"
    assert protected["metrics_json"] is None
    assert protected["holdout_metrics_protected"] is True
    assert protected["artifact_locations_json"] == []
    assert (
        registry.get_holdout_run_authorization("fixture-authorization")["consumed_by_experiment_id"]
        == holdout.experiment_id
    )
    registry.authorize_holdout(
        holdout.experiment_id, "fixture-read", "reviewer", "inspect fixture result once"
    )
    revealed = registry.get(holdout.experiment_id, "fixture-read")
    assert revealed["metrics_json"] is not None


def test_rapid_research_rejects_controlled_holdout_before_and_after_consumption(
    tmp_path: Path,
) -> None:
    registry, _datasets, holdout = holdout_setup(tmp_path)
    rapid = RapidResearchStore(tmp_path)
    controlled_bytes = registry.path.read_bytes()

    exposed = resolve_research_dataset(
        tmp_path,
        rapid,
        holdout.dataset_id,
        datetime(2025, 2, 3, tzinfo=UTC),
        datetime(2025, 2, 4, tzinfo=UTC),
    )
    for requested_start, requested_end in (
        (holdout.start_timestamp, holdout.end_timestamp),
        (holdout.start_timestamp, None),
        (None, holdout.end_timestamp),
        (None, None),
    ):
        with pytest.raises(ValueError, match="protected controlled holdout"):
            resolve_research_dataset(
                tmp_path,
                rapid,
                holdout.dataset_id,
                requested_start,
                requested_end,
            )

    assert len(exposed.bars) == 10
    assert (
        registry.get_holdout_run_authorization("fixture-authorization")["consumed_by_experiment_id"]
        is None
    )
    assert registry.path.read_bytes() == controlled_bytes

    registry.create_experiment(holdout, "fixture-authorization")
    with pytest.raises(ValueError, match="protected controlled holdout"):
        resolve_research_dataset(
            tmp_path,
            rapid,
            holdout.dataset_id,
            holdout.start_timestamp,
            holdout.end_timestamp,
        )
    assert (
        registry.get_holdout_run_authorization("fixture-authorization")["consumed_by_experiment_id"]
        == holdout.experiment_id
    )


def test_rapid_local_data_cannot_launder_a_controlled_holdout(tmp_path: Path) -> None:
    registry, _datasets, holdout = holdout_setup(tmp_path)
    rapid = RapidResearchStore(tmp_path)
    controlled = StorageLayout(tmp_path).dataset(holdout.dataset_id) / "bars.parquet"
    copied = tmp_path / "copied-bars.parquet"
    copied.write_bytes(controlled.read_bytes())
    controlled_registry = registry.path.read_bytes()

    with pytest.raises(ValueError, match="controlled dataset artifacts cannot be imported"):
        import_local_data(controlled, rapid)
    with pytest.raises(ValueError, match="controlled dataset artifacts cannot be imported"):
        import_local_data(controlled, RapidResearchStore(tmp_path / "other-state"))
    with pytest.raises(ValueError, match="protected controlled holdout"):
        import_local_data(copied, rapid)

    exposed = resolve_research_dataset(
        tmp_path,
        rapid,
        holdout.dataset_id,
        datetime(2025, 2, 3, tzinfo=UTC),
        datetime(2025, 2, 4, tzinfo=UTC),
    )
    exposed_path = tmp_path / "exposed-bars.parquet"
    exposed_path.write_bytes(to_parquet(exposed.bars))
    assert import_local_data(exposed_path, rapid)["data_origin"] == "user-supplied"

    backup = tmp_path / "experiments-before-rapid-alias.sqlite3"
    registry.path.rename(backup)
    try:
        legacy_alias = import_local_data(copied, rapid)
    finally:
        backup.rename(registry.path)
    with pytest.raises(ValueError, match="protected controlled holdout"):
        resolve_research_dataset(
            tmp_path,
            rapid,
            str(legacy_alias["dataset_id"]),
            holdout.start_timestamp,
            holdout.end_timestamp,
        )

    assert (
        registry.get_holdout_run_authorization("fixture-authorization")["consumed_by_experiment_id"]
        is None
    )
    assert registry.path.read_bytes() == controlled_registry


def test_rapid_research_fails_closed_on_an_inverted_stored_holdout_range(
    tmp_path: Path,
) -> None:
    registry, _datasets, holdout = holdout_setup(tmp_path)
    registry.create_experiment(holdout, "fixture-authorization")
    with sqlite3.connect(registry.path) as connection:
        row = connection.execute(
            "SELECT spec_json FROM experiments WHERE experiment_id = ?",
            (holdout.experiment_id,),
        ).fetchone()
        assert row is not None
        stored = json.loads(str(row[0]))
        stored["start_timestamp"], stored["end_timestamp"] = (
            stored["end_timestamp"],
            stored["start_timestamp"],
        )
        connection.execute(
            "UPDATE experiments SET spec_json = ? WHERE experiment_id = ?",
            (json.dumps(stored), holdout.experiment_id),
        )

    with pytest.raises(ValueError, match="controlled holdout registry is malformed"):
        resolve_research_dataset(
            tmp_path,
            RapidResearchStore(tmp_path),
            holdout.dataset_id,
            datetime(2025, 2, 6, tzinfo=UTC),
            datetime(2025, 2, 6, tzinfo=UTC),
        )


def test_rapid_research_fails_closed_on_an_inverted_authorization_range(
    tmp_path: Path,
) -> None:
    registry, _datasets, holdout = holdout_setup(tmp_path)
    with sqlite3.connect(registry.path) as connection:
        row = connection.execute(
            "SELECT candidate_spec_json FROM holdout_run_authorizations WHERE authorization_id = ?",
            ("fixture-authorization",),
        ).fetchone()
        assert row is not None
        stored = json.loads(str(row[0]))
        stored["validation_start"], stored["validation_end"] = (
            stored["validation_end"],
            stored["validation_start"],
        )
        connection.execute(
            "UPDATE holdout_run_authorizations SET candidate_spec_json = ? "
            "WHERE authorization_id = ?",
            (json.dumps(stored), "fixture-authorization"),
        )

    with pytest.raises(ValueError, match="controlled holdout registry is malformed"):
        resolve_research_dataset(
            tmp_path,
            RapidResearchStore(tmp_path),
            holdout.dataset_id,
            datetime(2025, 2, 4, tzinfo=UTC),
            datetime(2025, 2, 4, tzinfo=UTC),
        )


def test_holdout_range_failure_remains_failed_and_consumes_authorization(
    tmp_path: Path,
) -> None:
    registry, datasets, holdout = holdout_setup(tmp_path)
    outside_dataset = replace(
        holdout,
        start_timestamp=datetime(2025, 2, 10, tzinfo=UTC),
        end_timestamp=datetime(2025, 2, 11, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="exceeds the dataset range"):
        run_holdout_experiment(registry, datasets, "fixture-authorization", outside_dataset)

    failed = registry.get(holdout.experiment_id)
    assert failed["status"] == "failed"
    assert "DatasetValidationError" in str(failed["failure_info"])
    assert (
        registry.get_holdout_run_authorization("fixture-authorization")["consumed_by_experiment_id"]
        == holdout.experiment_id
    )


def test_sensitivity_variants_are_candidates_and_comparison_has_no_score(tmp_path: Path) -> None:
    source = bars()
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    registry.create_campaign("campaign", "Sensitivity", 3)
    variants = (
        SensitivityVariant("base", CostModel()),
        SensitivityVariant(
            "delayed",
            CostModel(version="high-cost-v1", slippage_bps=Decimal("10")),
            2,
        ),
    )
    results = run_sensitivity(registry, spec(source), source, tmp_path / "reports", variants)
    assert all(result is not None for result in results.values())
    stored_spec = registry.get("candidate-delayed")["spec_json"]
    assert isinstance(stored_spec, dict)
    assert stored_spec["parent_candidate"] == "candidate"
    report = comparison_report(registry, tuple(reversed(results)))
    assert "score" not in report
    candidates = cast(list[dict[str, object]], report["candidates"])
    assert [row["experiment_id"] for row in candidates] == sorted(results)
    assert report == comparison_report(registry, tuple(results))
