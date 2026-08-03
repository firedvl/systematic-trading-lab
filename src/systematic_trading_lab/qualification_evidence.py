"""Registry-backed campaign aggregation for qualification evidence."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import cast

from .experiments import ExperimentRegistry, ExperimentSplit, HoldoutAccessError
from .fingerprints import canonical_json, canonicalize, fingerprint
from .qualification import ProposalStatus, QualificationProposal, evaluate


@dataclass(frozen=True)
class CandidateEvidenceSpec:
    candidate_id: str
    strategy_id: str
    base_parameters: Mapping[str, object]
    base_cost_model_version: str
    base_execution_model_version: str
    cost_sensitivity_model_version: str
    delay_sensitivity_model_version: str
    parameter_neighbor_values: tuple[Mapping[str, object], ...]
    base_validation_ids: tuple[str, ...]
    benchmark_validation_ids: tuple[str, ...]
    cost_sensitivity_ids: tuple[str, ...]
    delay_sensitivity_ids: tuple[str, ...]
    parameter_neighbor_ids: tuple[str, ...]


@dataclass(frozen=True)
class QualificationEvidenceManifest:
    manifest_id: str
    campaign_id: str
    benchmark_strategy_id: str
    candidates: tuple[CandidateEvidenceSpec, ...]


def load_evidence_manifest(path: Path) -> QualificationEvidenceManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load qualification evidence manifest: {exc}") from exc
    root = _object(payload, "evidence manifest")
    _exact_fields(root, {"id", "campaign_id", "benchmark_strategy_id", "candidates"}, "manifest")
    raw_candidates = root["candidates"]
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError("manifest candidates must be a nonempty list")
    candidates = tuple(_candidate(value, index) for index, value in enumerate(raw_candidates))
    candidate_ids = [candidate.candidate_id for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("manifest candidate IDs must be unique")
    return QualificationEvidenceManifest(
        _text(root["id"], "manifest id"),
        _text(root["campaign_id"], "campaign id"),
        _text(root["benchmark_strategy_id"], "benchmark strategy id"),
        candidates,
    )


def build_evidence_reports(
    registry: ExperimentRegistry,
    manifest: QualificationEvidenceManifest,
    proposal: QualificationProposal,
) -> tuple[dict[str, object], ...]:
    if manifest.campaign_id != proposal.evidence_campaign_id:
        raise ValueError("proposal and evidence manifest campaigns differ")
    campaign_candidate_count = len(registry.list(manifest.campaign_id))
    reports: list[dict[str, object]] = []
    for candidate in manifest.candidates:
        metrics, candidate_specification = _aggregate_candidate(
            registry,
            manifest,
            candidate,
            campaign_candidate_count,
        )
        qualification = evaluate(candidate.candidate_id, metrics, proposal.gate_specs)
        payload: dict[str, object] = {
            "schema_version": "qualification-evidence-v1",
            "manifest_id": manifest.manifest_id,
            "manifest_fingerprint": fingerprint(manifest),
            "proposal_id": proposal.proposal_id,
            "proposal_fingerprint": fingerprint(proposal),
            "campaign_id": manifest.campaign_id,
            "candidate_id": candidate.candidate_id,
            "strategy_id": candidate.strategy_id,
            "candidate_specification": candidate_specification,
            "source_experiment_ids": sorted(_all_ids(candidate)),
            "metrics": metrics,
            "qualification": canonicalize(qualification),
        }
        payload["evidence_fingerprint"] = fingerprint(payload)
        reports.append(payload)
    return tuple(reports)


def authorize_holdout_run(
    registry: ExperimentRegistry,
    manifest: QualificationEvidenceManifest,
    proposal: QualificationProposal,
    candidate_id: str,
    authorization_id: str,
    reviewer: str,
    reason: str,
) -> dict[str, object]:
    """Rebuild evidence and store a one-use authorization only when it qualifies."""
    reports = build_evidence_reports(registry, manifest, proposal)
    report = next(
        (item for item in reports if item["candidate_id"] == candidate_id),
        None,
    )
    if report is None:
        raise HoldoutAccessError(f"qualification candidate not found: {candidate_id}")
    qualification = report["qualification"]
    if not isinstance(qualification, Mapping):
        raise HoldoutAccessError("qualification evidence is malformed")
    if proposal.status is not ProposalStatus.APPROVED or qualification.get("state") != "qualified":
        raise HoldoutAccessError("holdout run requires approved passing qualification evidence")
    registry._create_holdout_run_authorization(authorization_id, report, reviewer, reason)
    return registry.get_holdout_run_authorization(authorization_id)


def write_evidence_reports(output_directory: Path, reports: Sequence[Mapping[str, object]]) -> Path:
    if not reports:
        raise ValueError("at least one qualification evidence report is required")
    payload = {"reports": list(reports)}
    content = canonical_json(payload) + "\n"
    path = output_directory / f"qualification-{fingerprint(payload)}.json"
    output_directory.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ValueError("qualification evidence path contains different content")
        return path
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=output_directory)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_text(encoding="utf-8") != content:
                raise ValueError("qualification evidence path contains different content") from None
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _aggregate_candidate(
    registry: ExperimentRegistry,
    manifest: QualificationEvidenceManifest,
    candidate: CandidateEvidenceSpec,
    campaign_candidate_count: int,
) -> tuple[dict[str, Decimal | int], dict[str, object]]:
    base = _records(
        registry,
        manifest.campaign_id,
        candidate.strategy_id,
        candidate.base_validation_ids,
    )
    benchmark = _records(
        registry,
        manifest.campaign_id,
        manifest.benchmark_strategy_id,
        candidate.benchmark_validation_ids,
    )
    costs = _records(
        registry,
        manifest.campaign_id,
        candidate.strategy_id,
        candidate.cost_sensitivity_ids,
    )
    delays = _records(
        registry,
        manifest.campaign_id,
        candidate.strategy_id,
        candidate.delay_sensitivity_ids,
    )
    neighbors = _records(
        registry,
        manifest.campaign_id,
        candidate.strategy_id,
        candidate.parameter_neighbor_ids,
    )
    if len(base) != len(benchmark):
        raise ValueError(f"candidate {candidate.candidate_id} has unmatched benchmark folds")
    _validate_base_folds(candidate, base, benchmark)
    base_by_id = {str(record["experiment_id"]): record for record in base}
    _validate_variants(candidate, base_by_id, costs, delays, neighbors)
    base_metrics = [_metrics(record) for record in base]
    benchmark_by_period = {_period(record): record for record in benchmark}
    wins = sum(
        _metric(metrics, "total_return")
        > _metric(_metrics(benchmark_by_period[_period(record)]), "total_return")
        for record, metrics in zip(base, base_metrics, strict=True)
    )
    returns = [_metric(metrics, "total_return") for metrics in base_metrics]
    metrics: dict[str, Decimal | int] = {
        "validation_fold_count": len(base),
        "positive_validation_fold_rate": Decimal(sum(value > 0 for value in returns))
        / Decimal(len(returns)),
        "benchmark_win_rate": Decimal(wins) / Decimal(len(base)),
        "worst_validation_return": min(returns),
        "worst_validation_sharpe": min(
            _metric(metrics, "sharpe_ratio") for metrics in base_metrics
        ),
        "max_validation_drawdown": max(
            _metric(metrics, "max_drawdown") for metrics in base_metrics
        ),
        "max_average_gross_exposure": max(
            _metric(metrics, "average_gross_exposure") for metrics in base_metrics
        ),
        "max_top_5_session_profit_share": max(
            _metric(metrics, "top_5_session_profit_share") for metrics in base_metrics
        ),
        "max_top_instrument_profit_share": max(
            _metric(metrics, "top_instrument_profit_share") for metrics in base_metrics
        ),
        "min_cost2x_return_retention": _minimum_retention(costs, base_by_id),
        "min_delay2_return_retention": _minimum_retention(delays, base_by_id),
        "min_parameter_neighbor_return_retention": _minimum_retention(neighbors, base_by_id),
        "min_up_regime_sessions": min(
            _integer_metric(metrics, "up_regime_sessions") for metrics in base_metrics
        ),
        "min_down_regime_sessions": min(
            _integer_metric(metrics, "down_regime_sessions") for metrics in base_metrics
        ),
        "max_turnover": max(_metric(metrics, "turnover") for metrics in base_metrics),
        "total_validation_trade_count": sum(
            _integer_metric(metrics, "trade_count") for metrics in base_metrics
        ),
        "campaign_candidate_count": campaign_candidate_count,
    }
    return metrics, _candidate_specification(base)


def _candidate_specification(base: Sequence[Mapping[str, object]]) -> dict[str, object]:
    spec = _spec(base[0])
    return {
        "strategy_id": spec["strategy_id"],
        "strategy_version": spec["strategy_version"],
        "strategy_family": spec["strategy_family"],
        "parameters": spec["parameters"],
        "cost_model_version": spec["cost_model_version"],
        "execution_model_version": spec["execution_model_version"],
        "dataset_id": spec["dataset_id"],
        "dataset_fingerprint": spec["dataset_fingerprint"],
        "universe_id": spec["universe_id"],
        "universe_fingerprint": spec["universe_fingerprint"],
        "validation_start": min(_period(record)[0] for record in base),
        "validation_end": max(_period(record)[1] for record in base),
    }


def _validate_base_folds(
    candidate: CandidateEvidenceSpec,
    base: Sequence[Mapping[str, object]],
    benchmark: Sequence[Mapping[str, object]],
) -> None:
    periods = [_period(record) for record in base]
    if len(periods) != len(set(periods)) or set(periods) != {
        _period(record) for record in benchmark
    }:
        raise ValueError(f"candidate {candidate.candidate_id} has invalid validation periods")
    ordered = sorted(periods)
    if any(
        current[0] <= previous[1] for previous, current in zip(ordered, ordered[1:], strict=False)
    ):
        raise ValueError(f"candidate {candidate.candidate_id} has overlapping validation periods")
    base_specs = [_spec(record) for record in base]
    identity_fields = (
        "strategy_version",
        "strategy_family",
        "dataset_id",
        "dataset_fingerprint",
        "universe_id",
        "universe_fingerprint",
        "parameters",
        "cost_model_version",
        "execution_model_version",
    )
    first = base_specs[0]
    if (
        first["parameters"] != candidate.base_parameters
        or first["cost_model_version"] != candidate.base_cost_model_version
        or first["execution_model_version"] != candidate.base_execution_model_version
    ):
        raise ValueError(f"candidate {candidate.candidate_id} base specification differs")
    if any(
        any(spec[field] != first[field] for field in identity_fields) for spec in base_specs[1:]
    ):
        raise ValueError(f"candidate {candidate.candidate_id} base folds differ")
    all_records = tuple(base) + tuple(benchmark)
    provenance_fields = (
        "dataset_id",
        "dataset_fingerprint",
        "universe_id",
        "universe_fingerprint",
        "cost_model_version",
        "execution_model_version",
    )
    if any(
        any(_spec(record)[field] != first[field] for field in provenance_fields)
        for record in all_records
    ):
        raise ValueError(f"candidate {candidate.candidate_id} provenance differs")


def _validate_variants(
    candidate: CandidateEvidenceSpec,
    base_by_id: Mapping[str, Mapping[str, object]],
    costs: Sequence[Mapping[str, object]],
    delays: Sequence[Mapping[str, object]],
    neighbors: Sequence[Mapping[str, object]],
) -> None:
    for kind, records in (("cost", costs), ("delay", delays), ("parameter", neighbors)):
        for record in records:
            spec = _spec(record)
            parent_id = spec.get("parent_candidate")
            parent = base_by_id.get(str(parent_id))
            if parent is None or _period(record) != _period(parent):
                raise ValueError(
                    f"candidate {candidate.candidate_id} has an unlinked {kind} variant"
                )
            parent_spec = _spec(parent)
            common = (
                "dataset_id",
                "dataset_fingerprint",
                "universe_id",
                "universe_fingerprint",
            )
            if any(spec[field] != parent_spec[field] for field in common):
                raise ValueError(f"candidate {candidate.candidate_id} {kind} provenance differs")
            differences = {
                field
                for field in ("parameters", "cost_model_version", "execution_model_version")
                if spec[field] != parent_spec[field]
            }
            expected = {"cost_model_version" if kind == "cost" else "execution_model_version"}
            if kind == "parameter":
                expected = {"parameters"}
            if differences != expected:
                raise ValueError(f"candidate {candidate.candidate_id} invalid {kind} variant")
            if kind == "cost" and (
                spec["cost_model_version"] != candidate.cost_sensitivity_model_version
            ):
                raise ValueError(f"candidate {candidate.candidate_id} cost model differs")
            if kind == "delay" and (
                spec["execution_model_version"] != candidate.delay_sensitivity_model_version
            ):
                raise ValueError(f"candidate {candidate.candidate_id} delay model differs")
    expected_neighbors = {
        canonical_json(parameters) for parameters in candidate.parameter_neighbor_values
    }
    if len(expected_neighbors) != len(candidate.parameter_neighbor_values):
        raise ValueError(f"candidate {candidate.candidate_id} parameter neighbors repeat")
    for base_id in base_by_id:
        observed_values = [
            canonical_json(_spec(record)["parameters"])
            for record in neighbors
            if _spec(record)["parent_candidate"] == base_id
        ]
        if (
            len(observed_values) != len(expected_neighbors)
            or set(observed_values) != expected_neighbors
        ):
            raise ValueError(
                f"candidate {candidate.candidate_id} parameter neighbor coverage differs"
            )


def _minimum_retention(
    records: Sequence[Mapping[str, object]],
    base_by_id: Mapping[str, Mapping[str, object]],
) -> Decimal:
    values: list[Decimal] = []
    for record in records:
        parent_id = str(_spec(record)["parent_candidate"])
        base_return = _metric(_metrics(base_by_id[parent_id]), "total_return")
        if base_return <= 0:
            raise ValueError("return retention requires a positive base return")
        values.append(_metric(_metrics(record), "total_return") / base_return)
    return min(values)


def _records(
    registry: ExperimentRegistry,
    campaign_id: str,
    strategy_id: str,
    experiment_ids: Sequence[str],
) -> tuple[dict[str, object], ...]:
    if not experiment_ids or len(experiment_ids) != len(set(experiment_ids)):
        raise ValueError("evidence experiment ID lists must be nonempty and unique")
    records: list[dict[str, object]] = []
    for experiment_id in experiment_ids:
        record = registry.get(experiment_id)
        spec = _spec(record)
        if (
            record["campaign_id"] != campaign_id
            or record["split"] != ExperimentSplit.VALIDATION.value
            or record["status"] != "completed"
            or spec["strategy_id"] != strategy_id
        ):
            raise ValueError(f"invalid qualification evidence experiment: {experiment_id}")
        records.append(record)
    return tuple(records)


def _candidate(value: object, index: int) -> CandidateEvidenceSpec:
    item = _object(value, f"candidate {index}")
    fields = {
        "id",
        "strategy_id",
        "base_parameters",
        "base_cost_model_version",
        "base_execution_model_version",
        "cost_sensitivity_model_version",
        "delay_sensitivity_model_version",
        "parameter_neighbor_values",
        "base_validation_ids",
        "benchmark_validation_ids",
        "cost_sensitivity_ids",
        "delay_sensitivity_ids",
        "parameter_neighbor_ids",
    }
    _exact_fields(item, fields, f"candidate {index}")
    return CandidateEvidenceSpec(
        _text(item["id"], f"candidate {index} id"),
        _text(item["strategy_id"], f"candidate {index} strategy id"),
        _parameters(item["base_parameters"], f"candidate {index} base parameters"),
        _text(item["base_cost_model_version"], f"candidate {index} base cost model"),
        _text(item["base_execution_model_version"], f"candidate {index} base execution model"),
        _text(
            item["cost_sensitivity_model_version"],
            f"candidate {index} cost sensitivity model",
        ),
        _text(
            item["delay_sensitivity_model_version"],
            f"candidate {index} delay sensitivity model",
        ),
        _parameter_list(
            item["parameter_neighbor_values"], f"candidate {index} parameter neighbor values"
        ),
        _text_list(item["base_validation_ids"], f"candidate {index} base validation IDs"),
        _text_list(item["benchmark_validation_ids"], f"candidate {index} benchmark validation IDs"),
        _text_list(item["cost_sensitivity_ids"], f"candidate {index} cost sensitivity IDs"),
        _text_list(item["delay_sensitivity_ids"], f"candidate {index} delay sensitivity IDs"),
        _text_list(item["parameter_neighbor_ids"], f"candidate {index} parameter neighbor IDs"),
    )


def _all_ids(candidate: CandidateEvidenceSpec) -> tuple[str, ...]:
    return (
        candidate.base_validation_ids
        + candidate.benchmark_validation_ids
        + candidate.cost_sensitivity_ids
        + candidate.delay_sensitivity_ids
        + candidate.parameter_neighbor_ids
    )


def _object(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be an object with string keys")
    return cast(dict[str, object], value)


def _exact_fields(value: Mapping[str, object], fields: set[str], context: str) -> None:
    if set(value) != fields:
        raise ValueError(
            f"{context} fields differ; missing={sorted(fields - set(value))}, "
            f"unknown={sorted(set(value) - fields)}"
        )


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a nonempty string")
    return value


def _text_list(value: object, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{context} must be a nonempty list")
    result = tuple(_text(item, context) for item in value)
    if len(result) != len(set(result)):
        raise ValueError(f"{context} must contain unique values")
    return result


def _parameters(value: object, context: str) -> Mapping[str, object]:
    parameters = _object(value, context)
    if not parameters or any(type(item) is not int or item <= 0 for item in parameters.values()):
        raise ValueError(f"{context} must contain positive integer values")
    return parameters


def _parameter_list(value: object, context: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{context} must be a nonempty list")
    return tuple(_parameters(item, context) for item in value)


def _spec(record: Mapping[str, object]) -> Mapping[str, object]:
    value = record.get("spec_json")
    if not isinstance(value, Mapping):
        raise ValueError("experiment is missing its specification")
    return value


def _metrics(record: Mapping[str, object]) -> Mapping[str, object]:
    value = record.get("metrics_json")
    if not isinstance(value, Mapping):
        raise ValueError("experiment is missing its metrics")
    return value


def _metric(metrics: Mapping[str, object], name: str) -> Decimal:
    raw = metrics.get(name)
    try:
        value = Decimal(str(raw)) if raw is not None else Decimal("NaN")
    except ArithmeticError as exc:
        raise ValueError(f"metric {name} is invalid") from exc
    if not value.is_finite():
        raise ValueError(f"metric {name} is missing or invalid")
    return value


def _integer_metric(metrics: Mapping[str, object], name: str) -> int:
    value = _metric(metrics, name)
    if value != value.to_integral_value() or value < 0:
        raise ValueError(f"metric {name} must be a nonnegative integer")
    return int(value)


def _period(record: Mapping[str, object]) -> tuple[str, str]:
    spec = _spec(record)
    return str(spec["start_timestamp"]), str(spec["end_timestamp"])
