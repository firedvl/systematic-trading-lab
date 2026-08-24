from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

import systematic_trading_lab.intraday_spy_qqq_lead_lag_001_reassessment as reassessment
from systematic_trading_lab.fingerprints import canonical_json
from systematic_trading_lab.intraday_spy_qqq_lead_lag_001_plan import (
    load_intraday_spy_qqq_lead_lag_001_plan,
)

_REPOSITORY = Path(__file__).resolve().parents[2]


def _reports() -> tuple[dict[tuple[str, str], dict[str, Any]], tuple[Any, ...], tuple[Any, ...]]:
    plan = load_intraday_spy_qqq_lead_lag_001_plan(_REPOSITORY)
    gates = reassessment._discovery_gates(plan.payload)
    active_counts = (3, 1, 0, 0, 0, 0, 2, 1, 0)
    reports: dict[tuple[str, str], dict[str, Any]] = {}
    for configuration, active_count in zip(plan.configurations, active_counts, strict=True):
        candidate = configuration.candidate_id
        session_ledger = [
            {
                "session": f"2025-07-{index + 1:02d}",
                "active": index < active_count,
                "disposition": "active" if index < active_count else "inactive-spy-below-floor",
                "completed_round_trips": 1 if index < active_count else 0,
            }
            for index in range(87)
        ]
        for scenario in ("normal", "zero_cost_diagnostic"):
            friction = Decimal("1") if scenario == "normal" else Decimal("0")
            report = {
                "lead_signal_trace_fingerprint": f"signal-{candidate}",
                "execution_evidence": {"decision_trace_fingerprint": f"decision-{candidate}"},
                "metrics": {
                    "total_return": Decimal("0.01"),
                    "active_session_count": active_count,
                    "completed_round_trips": active_count,
                    "max_drawdown": Decimal("0.01"),
                    "cost_to_gross_profit": Decimal("0.1"),
                    "average_gross_trade_edge_bps": Decimal("6"),
                    "positive_profit_session_concentration": Decimal("0.4"),
                    "positive_profit_signal_bucket_concentration": Decimal("0.5"),
                    "accounting_identity_error": Decimal("0"),
                    "gross_profit_loss": Decimal("10"),
                    "execution_friction": friction,
                    "net_profit_loss": Decimal("10") - friction,
                },
                "details": {"session_ledger": session_ledger},
            }
            reports[(candidate, scenario)] = json.loads(canonical_json(report))
    return reports, plan.configurations, gates


def test_reassessment_restores_serialized_decimals_and_proves_empty_activity() -> None:
    reports, configurations, gates = _reports()

    result = reassessment._recompute_discovery(reports, configurations, gates)

    assert result["selected"] == []
    ledger = cast(list[dict[str, object]], result["ledger"])
    assert max(cast(int, row["normal_active_sessions"]) for row in ledger) == 3
    assert all(row["activity_gate_failed"] is True for row in ledger)
    first_metrics = cast(dict[str, object], ledger[0]["metrics"])
    assert first_metrics["normal.total_return"] == Decimal("0.01")
    assert first_metrics["normal.accounting_identity_error"] == Decimal("0")


def test_reassessment_rejects_tampered_activity_accounting() -> None:
    reports, configurations, gates = _reports()
    first = configurations[0].candidate_id
    reports[(first, "normal")]["metrics"]["active_session_count"] = 12

    with pytest.raises(ValueError, match="activity accounting differs"):
        reassessment._recompute_discovery(reports, configurations, gates)


@pytest.mark.parametrize("value", [True, "NaN", " 1", "1.0", {}, []])
def test_reassessment_rejects_invalid_numeric_metric(value: object) -> None:
    with pytest.raises(ValueError, match="metric"):
        reassessment._required_metric(value, "test")


def test_reassessment_treats_semantic_null_as_a_failed_gate() -> None:
    reports, configurations, gates = _reports()
    first = configurations[0].candidate_id
    reports[(first, "normal")]["metrics"]["cost_to_gross_profit"] = None

    result = reassessment._recompute_discovery(reports, configurations, gates)

    first_row = cast(list[dict[str, Any]], result["ledger"])[0]
    gate = next(
        item for item in first_row["gates"] if item["metric"] == "normal.cost_to_gross_profit"
    )
    assert gate["observed"] is None
    assert gate["passed"] is False


def test_reassessment_rejects_downstream_work_after_empty_discovery() -> None:
    reports, configurations, gates = _reports()
    result = reassessment._recompute_discovery(reports, configurations, gates)
    final_report = {
        "outcome": "no-controlled-qualified-candidate",
        "cohort": [],
        "counts": {
            "total_run_specifications": 18,
            "walk_forward_run_specifications": 0,
            "stress_run_specifications": 0,
            "neighbor_new_run_specifications": 0,
        },
    }
    final_freeze = {
        "cohort": [],
        "screened_ledger": {
            "walk_forward": {"ledger": [], "selected": []},
            "stress": {"ledger": [], "selected": []},
            "neighbors": {
                "ledger": [],
                "selected": [],
                "requested_run_specification_count": 1,
                "new_run_specification_count": 0,
            },
        },
    }

    with pytest.raises(ValueError, match="downstream disposition differs"):
        reassessment._validate_empty_downstream(final_report, final_freeze, result)
