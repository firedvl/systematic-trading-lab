from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from systematic_trading_lab.backtesting import CostModel
from systematic_trading_lab.domain import OHLCVBar, Symbol
from systematic_trading_lab.experiment_runner import (
    SensitivityVariant,
    WalkForwardSplit,
    comparison_report,
    run_experiment,
    run_sensitivity,
    validate_walk_forward,
    walk_forward_specs,
)
from systematic_trading_lab.experiments import (
    ExperimentRegistry,
    ExperimentSpec,
    ExperimentSplit,
    HoldoutAccessError,
)
from systematic_trading_lab.fingerprints import fingerprint


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
