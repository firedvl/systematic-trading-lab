"""Stored-spec-only controlled runner for the prospectively sealed V3 campaign."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .datasets import DatasetService, DatasetValidationError
from .domain import TimestampRange
from .experiments import ExperimentError
from .intraday_source_provenance import (
    bind_intraday_execution_source,
)
from .intraday_v3 import V3DiagnosticReplay, build_v3_diagnostic_report, run_v3_diagnostic
from .intraday_v3_registry import IntradayV3Registry
from .intraday_v3_source_provenance import (
    IntradayV3SourceAssessment,
    assess_intraday_v3_source_preassessment,
)
from .storage import StorageLayout


@dataclass(frozen=True)
class IntradayV3SourceArtifacts:
    wheel: Path
    build_manifest: Path
    whole_package_manifest: Path
    lockfile: Path
    dependency_wheelhouse: Path


def run_cataloged_intraday_v3_experiment(
    experiment_id: str,
    layout: StorageLayout,
    source_artifacts: IntradayV3SourceArtifacts,
) -> V3DiagnosticReplay:
    """Run only the exact V3 spec, data, source, and report path stored under one root."""

    if not experiment_id or type(layout) is not StorageLayout:
        raise ExperimentError("V3 execution requires a candidate ID and concrete storage layout")
    registry = IntradayV3Registry(layout.experiments)
    datasets = DatasetService(layout)
    claim = None
    try:
        assessment = _assess(registry, source_artifacts)
        claim = registry.claim(experiment_id, assessment)
        spec = claim.spec
        registry.heartbeat(experiment_id, claim.token)
        validation = datasets.validate(spec.dataset_id)
        if not validation["valid"]:
            raise DatasetValidationError("V3 dataset integrity validation failed")
        bars = datasets.load_bars_range(
            spec.dataset_id,
            TimestampRange(spec.start_timestamp, spec.end_timestamp),
            expected_fingerprint=spec.dataset_fingerprint,
            expected_universe_id=spec.universe_id,
            expected_universe_fingerprint=spec.universe_fingerprint,
        )
        replay = run_v3_diagnostic(spec, bars)
        registry.heartbeat(experiment_id, claim.token)
        report = build_v3_diagnostic_report(spec, replay, bars)
        registry.verify_current_source(
            experiment_id, claim.token, _assess(registry, source_artifacts)
        )
        registry.heartbeat(experiment_id, claim.token)
        evidence = registry.get(experiment_id)["execution_source_provenance"]
        if not isinstance(evidence, dict):
            raise ExperimentError("V3 execution source evidence is absent")
        report = bind_intraday_execution_source(report, evidence)
        report_path = layout.reports / f"{spec.configuration_fingerprint}.json"
        registry.publish_report(experiment_id, claim.token, report_path, report)
        return replay
    except Exception as error:
        if claim is not None:
            registry.fail(
                experiment_id, claim.token, f"controlled-run-error:{type(error).__name__}"
            )
        raise


def _assess(
    registry: IntradayV3Registry, artifacts: IntradayV3SourceArtifacts
) -> IntradayV3SourceAssessment:
    if not isinstance(artifacts, IntradayV3SourceArtifacts):
        raise ExperimentError("V3 execution source artifacts differ")
    preassessment = assess_intraday_v3_source_preassessment(
        artifacts.wheel,
        artifacts.build_manifest,
        artifacts.whole_package_manifest,
        artifacts.lockfile,
        artifacts.dependency_wheelhouse,
    )
    return registry.bind_source_preassessment(preassessment)
