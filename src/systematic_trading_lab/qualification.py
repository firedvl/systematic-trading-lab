"""Gate-based qualification with no hidden aggregate score."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import cast

from .experiments import (
    ExperimentRegistry,
    ExperimentSplit,
    ExperimentStatus,
    HoldoutAccessError,
    QualificationState,
)
from .fingerprints import canonicalize, fingerprint


class Comparison(StrEnum):
    GREATER_THAN_OR_EQUAL = ">="
    LESS_THAN_OR_EQUAL = "<="


class ProposalStatus(StrEnum):
    PROPOSED_UNAPPROVED = "proposed-unapproved"
    APPROVED = "approved"


class GateScope(StrEnum):
    CAMPAIGN = "campaign"


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
        if not self.threshold.is_finite():
            raise ValueError("gate threshold must be finite")


@dataclass(frozen=True)
class ProposedGate:
    spec: GateSpec
    scope: GateScope
    rationale: str

    def __post_init__(self) -> None:
        if not self.rationale.strip():
            raise ValueError("gate rationale is required")


@dataclass(frozen=True)
class QualificationProposal:
    proposal_id: str
    status: ProposalStatus
    evidence_campaign_id: str
    gates: tuple[ProposedGate, ...]

    def __post_init__(self) -> None:
        if not self.proposal_id or not self.evidence_campaign_id or not self.gates:
            raise ValueError("proposal ID, evidence campaign ID, and gates are required")
        names = [gate.spec.name for gate in self.gates]
        metrics = [gate.spec.metric for gate in self.gates]
        if len(names) != len(set(names)) or len(metrics) != len(set(metrics)):
            raise ValueError("gate names and metrics must be unique")
        approvals = [gate.spec.approved for gate in self.gates]
        if self.status is ProposalStatus.PROPOSED_UNAPPROVED and any(approvals):
            raise ValueError("an unapproved proposal cannot contain approved gates")
        if self.status is ProposalStatus.APPROVED and not all(approvals):
            raise ValueError("an approved proposal must contain only approved gates")

    @property
    def gate_specs(self) -> tuple[GateSpec, ...]:
        return tuple(gate.spec for gate in self.gates)


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


def load_qualification_proposal(path: Path) -> QualificationProposal:
    """Load an exact, reviewable qualification proposal and fail closed."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load qualification proposal: {exc}") from exc
    root = _require_object(payload, "proposal")
    _require_exact_fields(root, {"id", "status", "evidence_campaign_id", "gates"}, "proposal")
    raw_gates = root["gates"]
    if not isinstance(raw_gates, list):
        raise ValueError("proposal gates must be a list")
    gates = tuple(_parse_proposed_gate(item, index) for index, item in enumerate(raw_gates))
    try:
        return QualificationProposal(
            proposal_id=_require_text(root["id"], "proposal id"),
            status=ProposalStatus(_require_text(root["status"], "proposal status")),
            evidence_campaign_id=_require_text(
                root["evidence_campaign_id"], "evidence campaign ID"
            ),
            gates=gates,
        )
    except ValueError as exc:
        raise ValueError(f"invalid qualification proposal: {exc}") from exc


def _parse_proposed_gate(value: object, index: int) -> ProposedGate:
    context = f"gate {index}"
    gate = _require_object(value, context)
    _require_exact_fields(
        gate,
        {
            "name",
            "metric",
            "comparison",
            "threshold",
            "disqualifying",
            "approved",
            "scope",
            "rationale",
        },
        context,
    )
    threshold_text = _require_text(gate["threshold"], f"{context} threshold")
    disqualifying = _require_bool(gate["disqualifying"], f"{context} disqualifying")
    approved = _require_bool(gate["approved"], f"{context} approved")
    try:
        threshold = Decimal(threshold_text)
        spec = GateSpec(
            name=_require_text(gate["name"], f"{context} name"),
            metric=_require_text(gate["metric"], f"{context} metric"),
            comparison=Comparison(_require_text(gate["comparison"], f"{context} comparison")),
            threshold=threshold,
            disqualifying=disqualifying,
            approved=approved,
        )
        scope = GateScope(_require_text(gate["scope"], f"{context} scope"))
        rationale = _require_text(gate["rationale"], f"{context} rationale")
    except (ArithmeticError, ValueError) as exc:
        raise ValueError(f"invalid {context}: {exc}") from exc
    return ProposedGate(spec, scope, rationale)


def _require_object(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be an object with string keys")
    return cast(dict[str, object], value)


def _require_exact_fields(value: Mapping[str, object], fields: set[str], context: str) -> None:
    actual = set(value)
    if actual != fields:
        missing = sorted(fields - actual)
        unknown = sorted(actual - fields)
        raise ValueError(f"{context} fields differ; missing={missing}, unknown={unknown}")


def _require_text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a nonempty string")
    return value


def _require_bool(value: object, context: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{context} must be a boolean")
    return value


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


def review_holdout(
    registry: ExperimentRegistry,
    experiment_id: str,
    event_id: str,
    reviewer: str,
    reason: str,
    proposal: QualificationProposal,
) -> dict[str, object]:
    if proposal.status is not ProposalStatus.APPROVED:
        raise HoldoutAccessError("holdout review requires an approved gate proposal")
    protected = registry.get(experiment_id)
    spec = protected.get("spec_json")
    if (
        protected.get("split") != ExperimentSplit.HOLDOUT.value
        or protected.get("status") != ExperimentStatus.COMPLETED.value
        or not isinstance(spec, Mapping)
        or spec.get("campaign_id") != proposal.evidence_campaign_id
    ):
        raise HoldoutAccessError("holdout review differs from its approved proposal")
    proposal_fingerprint = fingerprint(proposal)
    try:
        registry.authorize_holdout(experiment_id, event_id, reviewer, reason, proposal_fingerprint)
    except HoldoutAccessError as error:
        try:
            access = registry.get_holdout_access(event_id)
        except KeyError:
            raise error from None
        expected = {
            "event_id": event_id,
            "experiment_id": experiment_id,
            "reviewer": reviewer,
            "reason": reason,
            "proposal_fingerprint": proposal_fingerprint,
        }
        if any(access[field] != value for field, value in expected.items()):
            raise error from None
    revealed = registry.get(experiment_id, event_id)
    metrics = revealed.get("metrics_json")
    if not isinstance(metrics, Mapping):
        raise HoldoutAccessError("holdout metrics are unavailable")
    report = evaluate(experiment_id, metrics, proposal.gate_specs)
    payload = canonicalize(report)
    assert isinstance(payload, dict)
    payload.update(
        {
            "schema_version": "holdout-review-v1",
            "proposal_id": proposal.proposal_id,
            "proposal_fingerprint": proposal_fingerprint,
            "holdout_event_id": event_id,
        }
    )
    payload["review_fingerprint"] = fingerprint(payload)
    existing = revealed.get("qualification_report_json")
    if existing is not None:
        if existing != payload:
            raise HoldoutAccessError("holdout review already differs")
        return payload
    registry.record_qualification(experiment_id, report.state, payload, event_id)
    return payload
