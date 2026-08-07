from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from systematic_trading_lab.backtesting import CostModel
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
)
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.providers import FixtureProvider, IntradayFixtureProvider
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
    datasets = DatasetService(StorageLayout(tmp_path / "data"))
    imported = datasets.import_from(
        FixtureProvider(),
        fixture_symbols(),
        Timeframe.DAILY,
        fixture_request(),
        load_research_universe(),
    )
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
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
            "validation_start": "2025-01-06T00:00:00Z",
            "validation_end": "2025-01-07T00:00:00Z",
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
        start_timestamp=datetime(2025, 1, 8, tzinfo=UTC),
        end_timestamp=datetime(2025, 1, 10, tzinfo=UTC),
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


def test_holdout_range_failure_remains_failed_and_consumes_authorization(
    tmp_path: Path,
) -> None:
    registry, datasets, holdout = holdout_setup(tmp_path)
    outside_dataset = replace(
        holdout,
        start_timestamp=datetime(2025, 1, 11, tzinfo=UTC),
        end_timestamp=datetime(2025, 1, 12, tzinfo=UTC),
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
