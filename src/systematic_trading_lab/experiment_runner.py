"""Controlled experiment execution and comparison helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from .backtesting import BacktestResult, CostModel
from .datasets import DatasetService
from .domain import OHLCVBar, TimestampRange
from .experiments import (
    ExperimentError,
    ExperimentRegistry,
    ExperimentSpec,
    ExperimentSplit,
    HoldoutAccessError,
)
from .fingerprints import fingerprint
from .reporting import build_report, strategy_result, summarize, write_report


@dataclass(frozen=True)
class WalkForwardSplit:
    training_start: datetime
    training_end: datetime
    validation_start: datetime
    validation_end: datetime

    def __post_init__(self) -> None:
        timestamps = (
            self.training_start,
            self.training_end,
            self.validation_start,
            self.validation_end,
        )
        if any(
            value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
            for value in timestamps
        ):
            raise ValueError("walk-forward timestamps must be UTC-aware")
        if (
            not self.training_start
            <= self.training_end
            < self.validation_start
            <= self.validation_end
        ):
            raise ValueError("training must end before validation begins")

    @property
    def split_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class SensitivityVariant:
    name: str
    cost_model: CostModel
    fill_delay_bars: int = 1

    def __post_init__(self) -> None:
        if not self.name or self.fill_delay_bars < 1:
            raise ValueError("variant name and positive fill delay are required")


def validate_walk_forward(splits: Sequence[WalkForwardSplit]) -> str:
    if not splits:
        raise ValueError("at least one walk-forward split is required")
    for previous, current in zip(splits, splits[1:], strict=False):
        if current.validation_start <= previous.validation_end:
            raise ValueError("validation windows must be chronological and non-overlapping")
        if current.training_end >= current.validation_start:
            raise ValueError("training data must precede its validation window")
    return fingerprint(tuple(splits))


def walk_forward_specs(
    base_spec: ExperimentSpec, splits: Sequence[WalkForwardSplit]
) -> tuple[ExperimentSpec, ...]:
    if base_spec.split is ExperimentSplit.HOLDOUT:
        raise HoldoutAccessError("walk-forward candidates cannot use the holdout split")
    validate_walk_forward(splits)
    candidates: list[ExperimentSpec] = []
    for index, split in enumerate(splits, start=1):
        prefix = f"{base_spec.experiment_id}-wf{index:02d}"
        candidates.extend(
            (
                replace(
                    base_spec,
                    experiment_id=f"{prefix}-training",
                    split=ExperimentSplit.TRAINING,
                    start_timestamp=split.training_start,
                    end_timestamp=split.training_end,
                    parent_candidate=base_spec.experiment_id,
                ),
                replace(
                    base_spec,
                    experiment_id=f"{prefix}-validation",
                    split=ExperimentSplit.VALIDATION,
                    start_timestamp=split.validation_start,
                    end_timestamp=split.validation_end,
                    parent_candidate=base_spec.experiment_id,
                ),
            )
        )
    return tuple(candidates)


def run_experiment(
    registry: ExperimentRegistry,
    spec: ExperimentSpec,
    bars: Sequence[OHLCVBar],
    output_directory: Path,
    initial_cash: Decimal = Decimal("100000"),
    cost_model: CostModel | None = None,
    fill_delay_bars: int = 1,
) -> BacktestResult:
    if spec.split is ExperimentSplit.HOLDOUT:
        raise HoldoutAccessError("ordinary experiment runner cannot execute holdout data")
    selected_costs = cost_model or CostModel()
    registry.create_experiment(spec)
    registry.claim(spec.experiment_id)
    try:
        execution_version = execution_model_version(fill_delay_bars)
        if spec.cost_model_version != selected_costs.version:
            raise ExperimentError("experiment cost model does not match the runner")
        if spec.execution_model_version != execution_version:
            raise ExperimentError("experiment execution model does not match the runner")
        if fingerprint(tuple(bar.to_record() for bar in bars)) != spec.dataset_fingerprint:
            raise ExperimentError("experiment dataset fingerprint does not match supplied bars")
        ordered = tuple(
            bar for bar in bars if spec.start_timestamp <= bar.timestamp <= spec.end_timestamp
        )
        registry.heartbeat(spec.experiment_id)
        result = strategy_result(
            spec.strategy_id,
            ordered,
            initial_cash,
            selected_costs,
            spec.parameters,
            fill_delay_bars,
        )
        report = build_report({spec.experiment_id: result})
        report_path = output_directory / f"{fingerprint(spec)}.json"
        write_report(report_path, {spec.experiment_id: result})
        registry.complete(
            spec.experiment_id,
            summarize(result),
            [str(report_path)],
            [str(report["report_fingerprint"])],
        )
        return result
    except Exception as error:
        registry.fail(spec.experiment_id, f"{type(error).__name__}: {error}")
        raise


def run_holdout_experiment(
    registry: ExperimentRegistry,
    datasets: DatasetService,
    authorization_id: str,
    spec: ExperimentSpec,
    initial_cash: Decimal = Decimal("100000"),
    cost_model: CostModel | None = None,
    fill_delay_bars: int = 1,
) -> dict[str, object]:
    """Run one authorized holdout without exposing its result or report."""
    if spec.split is not ExperimentSplit.HOLDOUT:
        raise HoldoutAccessError("controlled holdout runner requires the holdout split")
    selected_costs = cost_model or CostModel()
    execution_version = execution_model_version(fill_delay_bars)
    if spec.cost_model_version != selected_costs.version:
        raise ExperimentError("experiment cost model does not match the runner")
    if spec.execution_model_version != execution_version:
        raise ExperimentError("experiment execution model does not match the runner")

    registry.create_experiment(spec, holdout_authorization_id=authorization_id)
    try:
        registry.claim(spec.experiment_id)
        bars = datasets.load_bars_range(
            spec.dataset_id,
            TimestampRange(spec.start_timestamp, spec.end_timestamp),
            expected_fingerprint=spec.dataset_fingerprint,
            expected_universe_id=spec.universe_id,
            expected_universe_fingerprint=spec.universe_fingerprint,
        )
        registry.heartbeat(spec.experiment_id)
        result = strategy_result(
            spec.strategy_id,
            bars,
            initial_cash,
            selected_costs,
            spec.parameters,
            fill_delay_bars,
        )
        registry.complete(spec.experiment_id, summarize(result))
    except Exception as error:
        registry.fail(spec.experiment_id, f"{type(error).__name__}: {error}")
        raise
    return registry.get(spec.experiment_id)


def run_sensitivity(
    registry: ExperimentRegistry,
    base_spec: ExperimentSpec,
    bars: Sequence[OHLCVBar],
    output_directory: Path,
    variants: Sequence[SensitivityVariant],
    initial_cash: Decimal = Decimal("100000"),
) -> dict[str, BacktestResult | None]:
    if len({variant.name for variant in variants}) != len(variants):
        raise ValueError("sensitivity variant names must be unique")
    results: dict[str, BacktestResult | None] = {}
    for variant in variants:
        experiment_id = f"{base_spec.experiment_id}-{variant.name}"
        spec = replace(
            base_spec,
            experiment_id=experiment_id,
            parent_candidate=base_spec.experiment_id,
            cost_model_version=variant.cost_model.version,
            execution_model_version=execution_model_version(variant.fill_delay_bars),
        )
        try:
            results[experiment_id] = run_experiment(
                registry,
                spec,
                bars,
                output_directory,
                initial_cash,
                variant.cost_model,
                variant.fill_delay_bars,
            )
        except Exception:
            results[experiment_id] = None
    return results


def comparison_report(
    registry: ExperimentRegistry, experiment_ids: Sequence[str]
) -> dict[str, object]:
    candidates: list[dict[str, object]] = []
    for experiment_id in sorted(set(experiment_ids)):
        record = registry.get(experiment_id)
        if record["split"] == ExperimentSplit.HOLDOUT.value:
            raise HoldoutAccessError("ordinary comparison reports exclude holdout experiments")
        spec = record["spec_json"]
        assert isinstance(spec, Mapping)
        candidates.append(
            {
                "experiment_id": experiment_id,
                "parent_candidate": spec.get("parent_candidate"),
                "strategy_id": spec["strategy_id"],
                "cost_model_version": spec["cost_model_version"],
                "execution_model_version": spec["execution_model_version"],
                "split": record["split"],
                "status": record["status"],
                "failure_info": record["failure_info"],
                "metrics": record["metrics_json"],
            }
        )
    payload: dict[str, object] = {
        "schema_version": "candidate-comparison-v1",
        "candidates": candidates,
    }
    payload["report_fingerprint"] = fingerprint(payload)
    return payload


def execution_model_version(fill_delay_bars: int) -> str:
    if fill_delay_bars < 1:
        raise ValueError("fill delay must be at least one bar")
    return "next-bar-v1" if fill_delay_bars == 1 else f"delayed-{fill_delay_bars}-bars-v1"
