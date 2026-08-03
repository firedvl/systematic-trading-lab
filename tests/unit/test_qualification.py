from decimal import Decimal

from systematic_trading_lab.experiments import QualificationState
from systematic_trading_lab.qualification import Comparison, GateSpec, evaluate


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
