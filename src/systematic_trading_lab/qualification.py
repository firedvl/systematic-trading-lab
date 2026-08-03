"""Gate-based qualification with no hidden aggregate score."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from .experiments import QualificationState
from .fingerprints import fingerprint


class Comparison(StrEnum):
    GREATER_THAN_OR_EQUAL = ">="
    LESS_THAN_OR_EQUAL = "<="


@dataclass(frozen=True)
class GateSpec:
    name: str
    metric: str
    comparison: Comparison
    threshold: Decimal
    disqualifying: bool = True
    approved: bool = False

    def __post_init__(self) -> None:
        if not self.name or not self.metric:
            raise ValueError("gate name and metric are required")


@dataclass(frozen=True)
class GateResult:
    name: str
    metric: str
    observed: Decimal | None
    comparison: Comparison
    threshold: Decimal
    passed: bool
    disqualifying: bool
    approved: bool
    reason: str


@dataclass(frozen=True)
class QualificationReport:
    experiment_id: str
    state: QualificationState
    gates: tuple[GateResult, ...]
    report_fingerprint: str


def evaluate(
    experiment_id: str,
    metrics: Mapping[str, object],
    gates: Sequence[GateSpec],
) -> QualificationReport:
    if not experiment_id or not gates:
        raise ValueError("experiment ID and at least one gate are required")
    results: list[GateResult] = []
    for gate in gates:
        raw = metrics.get(gate.metric)
        try:
            observed = Decimal(str(raw)) if raw is not None else None
        except ArithmeticError:
            observed = None
        if observed is None or not observed.is_finite():
            passed = False
            reason = "metric-missing-or-invalid"
        elif gate.comparison is Comparison.GREATER_THAN_OR_EQUAL:
            passed = observed >= gate.threshold
            reason = "passed" if passed else "below-threshold"
        else:
            passed = observed <= gate.threshold
            reason = "passed" if passed else "above-threshold"
        results.append(
            GateResult(
                gate.name,
                gate.metric,
                observed,
                gate.comparison,
                gate.threshold,
                passed,
                gate.disqualifying,
                gate.approved,
                reason,
            )
        )
    if not all(result.approved for result in results):
        state = QualificationState.UNAPPROVED
    elif any(not result.passed and result.disqualifying for result in results):
        state = QualificationState.REJECTED
    elif all(result.passed for result in results):
        state = QualificationState.QUALIFIED
    else:
        state = QualificationState.REJECTED
    content = {"experiment_id": experiment_id, "state": state, "gates": tuple(results)}
    return QualificationReport(experiment_id, state, tuple(results), fingerprint(content))
