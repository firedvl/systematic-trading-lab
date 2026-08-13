"""Controlled experiment execution and comparison helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from .backtesting import BacktestResult, CostModel
from .catalog import DatasetCatalog
from .datasets import DatasetService, DatasetValidationError
from .domain import OHLCVBar, Timeframe, TimestampRange
from .experiments import (
    ExperimentError,
    ExperimentRegistry,
    ExperimentSpec,
    ExperimentSplit,
    HoldoutAccessError,
    IntradayExperimentSpec,
)
from .fingerprints import canonicalize, fingerprint
from .intraday_reporting import (
    build_intraday_report,
    intraday_strategy_result,
    write_intraday_report,
)
from .intraday_source_provenance import (
    bind_intraday_execution_source,
    write_intraday_execution_report,
)
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
        _validate_execution_models(spec, selected_costs, fill_delay_bars)
        if fingerprint(tuple(bar.to_record() for bar in bars)) != spec.dataset_fingerprint:
            raise ExperimentError("experiment dataset fingerprint does not match supplied bars")
        ordered = tuple(
            bar for bar in bars if spec.start_timestamp <= bar.timestamp <= spec.end_timestamp
        )
        return _complete_research_run(
            registry,
            spec,
            ordered,
            output_directory,
            initial_cash,
            selected_costs,
            fill_delay_bars,
            False,
            False,
        )
    except Exception as error:
        registry.fail(spec.experiment_id, f"{type(error).__name__}: {error}")
        raise


def run_cataloged_experiment(
    registry: ExperimentRegistry,
    datasets: DatasetService,
    spec: ExperimentSpec,
    output_directory: Path,
    initial_cash: Decimal = Decimal("100000"),
    cost_model: CostModel | None = None,
    fill_delay_bars: int = 1,
    *,
    pre_registered: bool = False,
) -> BacktestResult:
    """Run training or validation from only its cataloged timestamp range."""
    if spec.split is ExperimentSplit.HOLDOUT:
        raise HoldoutAccessError("cataloged research runner cannot execute holdout data")
    selected_costs = cost_model or CostModel()
    if pre_registered:
        if registry.get_planned_spec(spec.experiment_id) != spec:
            raise ExperimentError("stored planned experiment differs")
    else:
        registry.create_experiment(spec)
    if pre_registered:
        registry._claim_planned(spec)
    else:
        registry.claim(spec.experiment_id)
    try:
        _validate_execution_models(spec, selected_costs, fill_delay_bars)
        _require_daily_dataset(datasets, spec.dataset_id)
        bars = datasets.load_bars_range(
            spec.dataset_id,
            TimestampRange(spec.start_timestamp, spec.end_timestamp),
            expected_fingerprint=spec.dataset_fingerprint,
            expected_universe_id=spec.universe_id,
            expected_universe_fingerprint=spec.universe_fingerprint,
        )
        return _complete_research_run(
            registry,
            spec,
            bars,
            output_directory,
            initial_cash,
            selected_costs,
            fill_delay_bars,
            pre_registered,
            True,
        )
    except Exception as error:
        registry.fail(spec.experiment_id, f"{type(error).__name__}: {error}")
        raise


def run_cataloged_intraday_experiment(
    registry: ExperimentRegistry,
    datasets: DatasetService,
    spec: IntradayExperimentSpec,
    output_directory: Path,
    initial_cash: Decimal = Decimal("100000"),
    cost_model: CostModel | None = None,
    *,
    pre_registered: bool = False,
    execution_source_review_id: str | None = None,
    execution_source_wheel: Path | None = None,
    execution_source_manifest: Path | None = None,
    execution_source_lockfile: Path | None = None,
    execution_source_dependency_wheelhouse: Path | None = None,
) -> BacktestResult:
    """Run one training or validation candidate under the M5B contract."""

    selected_costs = (
        _campaign_v1_execution_inputs(
            registry,
            datasets,
            spec,
            output_directory,
            initial_cash,
            cost_model,
        )
        if pre_registered and spec.campaign_id == "intraday-research-v1"
        else cost_model or CostModel()
    )
    source_binding: dict[str, object] | None = None
    if pre_registered:
        if registry.get_planned_intraday_spec(spec.experiment_id) != spec:
            raise ExperimentError("stored planned intraday experiment differs")
        source_binding = registry._claim_planned_intraday(
            spec,
            execution_source_review_id,
            execution_source_wheel,
            execution_source_manifest,
            execution_source_lockfile,
            execution_source_dependency_wheelhouse,
        )
    else:
        registry.create_experiment(spec)
        registry.claim(spec.experiment_id)
    try:
        if pre_registered and not datasets.validate(spec.dataset_id)["valid"]:
            raise DatasetValidationError("dataset integrity validation failed")
        registry.heartbeat(spec.experiment_id)
        result, report, bars = _intraday_computation(datasets, spec, initial_cash, selected_costs)
        if source_binding is not None:
            assert execution_source_review_id is not None
            assert execution_source_wheel is not None
            assert execution_source_manifest is not None
            assert execution_source_lockfile is not None
            assert execution_source_dependency_wheelhouse is not None
            registry.verify_intraday_execution_source_review(
                execution_source_review_id,
                execution_source_wheel,
                execution_source_manifest,
                execution_source_lockfile,
                execution_source_dependency_wheelhouse,
            )
        provenance = report["provenance"]
        assert isinstance(provenance, dict)
        report_path = output_directory / f"{spec.configuration_fingerprint}.json"
        if source_binding is None:
            write_intraday_report(report_path, provenance, result, bars)
        else:
            report = bind_intraday_execution_source(
                report,
                registry.intraday_execution_source_evidence(spec.experiment_id),
            )
            write_intraday_execution_report(report_path, report)
        metrics = report.get("metrics")
        if not isinstance(metrics, Mapping):
            raise ExperimentError("intraday report metrics are malformed")
        report_fingerprint = report.get("report_fingerprint")
        if not isinstance(report_fingerprint, str):
            raise ExperimentError("intraday report fingerprint is missing")
        if pre_registered:
            registry._complete_planned_intraday(
                spec,
                metrics,
                [str(report_path)],
                [report_fingerprint],
            )
        else:
            registry._complete_controlled(
                spec.experiment_id,
                metrics,
                [str(report_path)],
                [report_fingerprint],
            )
        return result
    except Exception as error:
        registry.fail(spec.experiment_id, f"{type(error).__name__}: {error}")
        raise


def _intraday_computation(
    datasets: DatasetService,
    spec: IntradayExperimentSpec,
    initial_cash: Decimal,
    selected_costs: CostModel,
) -> tuple[BacktestResult, dict[str, object], tuple[OHLCVBar, ...]]:
    """Compute one candidate; provenance and lifecycle plumbing stay outside this surface."""

    manifest = datasets.describe(spec.dataset_id)
    _validate_intraday_models(spec, selected_costs, manifest)
    bars = datasets.load_bars_range(
        spec.dataset_id,
        TimestampRange(spec.start_timestamp, spec.end_timestamp),
        expected_fingerprint=spec.dataset_fingerprint,
        expected_universe_id=spec.universe_id,
        expected_universe_fingerprint=spec.universe_fingerprint,
    )
    result = intraday_strategy_result(
        spec.strategy_id,
        bars,
        initial_cash,
        selected_costs,
        Timeframe(spec.timeframe),
        spec.execution_delay_bars,
        spec.parameters,
    )
    if (result.strategy_id, result.strategy_version) != (
        spec.strategy_id,
        spec.strategy_version,
    ):
        raise ExperimentError("intraday strategy identity does not match the experiment")
    provenance = canonicalize(spec)
    assert isinstance(provenance, dict)
    report = build_intraday_report(provenance, result, bars)
    return result, report, bars


def _campaign_v1_execution_inputs(
    registry: ExperimentRegistry,
    datasets: DatasetService,
    spec: IntradayExperimentSpec,
    output_directory: Path,
    initial_cash: Decimal,
    cost_model: CostModel | None,
) -> CostModel:
    """Derive Campaign V1 inputs from its stored spec and one storage root."""

    if (
        type(registry) is not ExperimentRegistry
        or type(datasets) is not DatasetService
        or type(datasets.catalog) is not DatasetCatalog
    ):
        raise ExperimentError("Campaign V1 requires the concrete registry and dataset service")
    if type(initial_cash) is not Decimal or initial_cash != Decimal("100000"):
        raise ExperimentError("Campaign V1 initial cash differs from its reviewed foundation")
    if cost_model is not None:
        raise ExperimentError("Campaign V1 costs are derived from its sealed stored spec")
    layout = datasets.layout
    if (
        registry.path.resolve() != layout.experiments.resolve()
        or datasets.catalog.path.resolve() != layout.catalog.resolve()
        or output_directory.resolve() != layout.reports.resolve()
    ):
        raise ExperimentError("Campaign V1 registry, datasets, and reports must share one root")
    return CostModel(
        spec.cost_model_version,
        spec.slippage_bps,
        spec.commission_bps,
    )


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
    _validate_execution_models(spec, selected_costs, fill_delay_bars)

    registry.create_experiment(spec, holdout_authorization_id=authorization_id)
    try:
        registry.claim(spec.experiment_id)
        _require_daily_dataset(datasets, spec.dataset_id)
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
        candidate: dict[str, object] = {
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
        if spec.get("schema_version") == "intraday-experiment-v1":
            candidate["intraday_contract"] = spec
            candidate["artifact_locations"] = record["artifact_locations_json"]
            candidate["artifact_fingerprints"] = record["artifact_hashes_json"]
        candidates.append(candidate)
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


def _require_daily_dataset(datasets: DatasetService, dataset_id: str) -> None:
    if datasets.describe(dataset_id).get("timeframe") != Timeframe.DAILY.value:
        raise ExperimentError("existing experiment runners accept daily datasets only")


def _validate_execution_models(
    spec: ExperimentSpec, cost_model: CostModel, fill_delay_bars: int
) -> None:
    if spec.cost_model_version != cost_model.version:
        raise ExperimentError("experiment cost model does not match the runner")
    if spec.execution_model_version != execution_model_version(fill_delay_bars):
        raise ExperimentError("experiment execution model does not match the runner")


def _validate_intraday_models(
    spec: IntradayExperimentSpec,
    cost_model: CostModel,
    manifest: Mapping[str, object],
) -> None:
    if manifest.get("timeframe") != spec.timeframe:
        raise ExperimentError("intraday experiment timeframe does not match its dataset")
    if manifest.get("calendar_policy") != "XNYS-regular-session-bars-v1":
        raise ExperimentError("intraday experiment requires the XNYS regular-session dataset")
    if manifest.get("timestamp_policy") != spec.bar_timestamp_semantics_version:
        raise ExperimentError("intraday bar timestamp semantics do not match the dataset")
    required = {
        "session_policy_version": "XNYS-regular-session-flat-v1",
        "bar_timestamp_semantics_version": "bar-open-utc-v1",
        "session_return_policy_version": "XNYS-session-close-equity-v1",
        "benchmark_policy_version": "cash-and-continuous-underlying-v1",
        "execution_model_version": "deterministic-next-bar-open-v1",
        "earliest_fill_semantics": "completed-bar-next-bar-open-v1",
    }
    for field, expected in required.items():
        if getattr(spec, field) != expected:
            raise ExperimentError(f"unsupported intraday {field.replace('_', ' ')}")
    if (
        spec.cost_model_version != cost_model.version
        or spec.slippage_bps != cost_model.slippage_bps
        or spec.commission_bps != cost_model.commission_bps
    ):
        raise ExperimentError("intraday experiment cost configuration does not match the runner")


def _complete_research_run(
    registry: ExperimentRegistry,
    spec: ExperimentSpec,
    bars: Sequence[OHLCVBar],
    output_directory: Path,
    initial_cash: Decimal,
    cost_model: CostModel,
    fill_delay_bars: int,
    allow_planned_completion: bool,
    controlled_completion: bool,
) -> BacktestResult:
    registry.heartbeat(spec.experiment_id)
    result = strategy_result(
        spec.strategy_id,
        bars,
        initial_cash,
        cost_model,
        spec.parameters,
        fill_delay_bars,
    )
    report = build_report({spec.experiment_id: result})
    report_path = output_directory / f"{fingerprint(spec)}.json"
    write_report(report_path, {spec.experiment_id: result})
    metrics = summarize(result)
    locations = [str(report_path)]
    hashes = [str(report["report_fingerprint"])]
    if allow_planned_completion:
        registry._complete_planned(spec, metrics, locations, hashes)
    elif controlled_completion:
        registry._complete_controlled(spec.experiment_id, metrics, locations, hashes)
    else:
        registry.complete(spec.experiment_id, metrics, locations, hashes)
    return result
