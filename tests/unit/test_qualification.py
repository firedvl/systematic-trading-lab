import json
from decimal import Decimal
from pathlib import Path

import pytest

from systematic_trading_lab.experiments import QualificationState
from systematic_trading_lab.qualification import (
    Comparison,
    GateSpec,
    ProposalStatus,
    evaluate,
    load_qualification_proposal,
)


def test_unapproved_thresholds_cannot_qualify() -> None:
    report = evaluate(
        "experiment-1",
        {"total_return": "0.1"},
        [
            GateSpec(
                "positive return", "total_return", Comparison.GREATER_THAN_OR_EQUAL, Decimal("0")
            )
        ],
    )
    assert report.state is QualificationState.UNAPPROVED


def test_disqualifying_and_missing_metric_gates_reject() -> None:
    gates = [
        GateSpec(
            "drawdown cap",
            "max_drawdown",
            Comparison.LESS_THAN_OR_EQUAL,
            Decimal("0.2"),
            approved=True,
        ),
        GateSpec(
            "minimum trades",
            "trade_count",
            Comparison.GREATER_THAN_OR_EQUAL,
            Decimal("10"),
            approved=True,
        ),
    ]
    rejected = evaluate("experiment-1", {"max_drawdown": "0.1", "trade_count": 2}, gates)
    missing = evaluate("experiment-2", {"max_drawdown": "0.1"}, gates)
    assert rejected.state is QualificationState.REJECTED
    assert missing.state is QualificationState.REJECTED
    assert missing.gates[1].reason == "metric-missing-or-invalid"


def test_strict_positive_gate_rejects_zero() -> None:
    gate = GateSpec(
        "positive return",
        "total_return",
        Comparison.GREATER_THAN,
        Decimal("0"),
        approved=True,
    )

    assert evaluate("zero", {"total_return": "0"}, [gate]).state is QualificationState.REJECTED
    assert (
        evaluate("positive", {"total_return": "0.0001"}, [gate]).state
        is QualificationState.QUALIFIED
    )


def test_approved_config_loads_and_can_qualify_passing_evidence() -> None:
    proposal = load_qualification_proposal(Path("config/research/qualification-proposal.json"))
    passing_metrics = {gate.spec.metric: gate.spec.threshold for gate in proposal.gates}

    report = evaluate("all-gates-pass", passing_metrics, proposal.gate_specs)

    assert proposal.status is ProposalStatus.APPROVED
    assert len(proposal.gates) == 17
    assert "total_validation_trade_count" in {gate.spec.metric for gate in proposal.gates}
    assert all(gate.spec.approved for gate in proposal.gates)
    assert all(result.passed for result in report.gates)
    assert report.state is QualificationState.QUALIFIED


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"unexpected": True}, "fields differ"),
        (
            {"status": "proposed-unapproved"},
            "unapproved proposal cannot contain approved gates",
        ),
    ],
)
def test_proposal_rejects_invalid_root(
    tmp_path: Path, change: dict[str, object], message: str
) -> None:
    source = Path("config/research/qualification-proposal.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload.update(change)
    target = tmp_path / "proposal.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_qualification_proposal(target)


def test_proposal_rejects_inconsistent_gate_and_duplicate_metric(tmp_path: Path) -> None:
    source = Path("config/research/qualification-proposal.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["gates"][0]["approved"] = False
    target = tmp_path / "proposal.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="approved proposal must contain only approved gates"):
        load_qualification_proposal(target)

    payload["gates"][0]["approved"] = True
    payload["gates"][1]["metric"] = payload["gates"][0]["metric"]
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="gate names and metrics must be unique"):
        load_qualification_proposal(target)


def test_proposal_rejects_nonfinite_threshold(tmp_path: Path) -> None:
    source = Path("config/research/qualification-proposal.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["gates"][0]["threshold"] = "NaN"
    target = tmp_path / "proposal.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="gate threshold must be finite"):
        load_qualification_proposal(target)
