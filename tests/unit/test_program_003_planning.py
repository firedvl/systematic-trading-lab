from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]


def _load(path: str) -> dict[str, Any]:
    value = json.loads((_REPOSITORY / path).read_text())
    assert isinstance(value, dict)
    return value


def test_program_003_plan_is_exact_and_grants_no_authority() -> None:
    plan = _load("config/research/program-003-low-cost-successor-plan-v1.json")
    unsigned = dict(plan)

    assert unsigned.pop("plan_fingerprint") == fingerprint(unsigned)
    assert plan["program_id"] == "multi-hour-sector-etf-research-002"
    assert plan["lineage"] == {
        "predecessor_program_id": "multi-hour-sector-etf-research-001",
        "predecessor_disposition": "STOPPED-TERMINAL",
        "termination_reason": (
            "Program 002 stopped before strategy execution because its frozen Alpaca source "
            "could not reconstruct required bars and its conditional Massive replacement failed "
            "adjustment, aggregate-eligibility, and licensing pre-transport gates."
        ),
        "strategy_outcomes_generated_or_observed": 0,
        "result_driven_adaptation": False,
        "successor_change": (
            "Data, corporate-action, missingness, and transaction-cost architecture only."
        ),
        "program_002_controls_mutable_by_this_plan": False,
        "program_002_retry_or_relaunch_allowed": False,
    }

    hypothesis = plan["scientific_hypothesis"]
    assert hypothesis["configuration_count"] == 8
    assert {
        (item["family_id"], item["lookback_minutes"], item["hold_minutes"])
        for item in hypothesis["configurations"]
    } == {
        (family, lookback, hold)
        for family in ("sector-relative-continuation-v1", "sector-relative-reversal-v1")
        for lookback in (30, 60)
        for hold in (120, 240)
    }

    data = plan["data_architecture"]
    assert data["primary_candidate"]["endpoint_path_template"] == (
        "/tiingo/equity/intraday/<ticker>/prices"
    )
    assert data["primary_candidate"]["documentation_status"] == "BETA"
    assert data["primary_candidate"]["fallback"] is None
    assert data["required_effective_request_semantics"]["force_fill"] is False
    assert data["historical_nbbo_acquisition_required"] is False
    assert set(plan["force_fill_policy"].values()) >= {False}

    missing = plan["missing_data_policy"]["maximum_loss"]
    assert missing["overall_excluded_full_session_rate_max"] == "0.005"
    assert missing["overall_excluded_full_session_count_max"] == 7
    assert missing["excluded_sessions_per_rolling_63_expected_sessions_max"] == 1
    assert missing["sessions_with_same_symbol_missing_per_rolling_252_expected_sessions_max"] == 1

    costs = plan["transaction_cost_model"]["scenarios"]
    assert {
        key: (value["total_bps_per_side"], value["execution_delay_minutes"])
        for key, value in costs.items()
    } == {"normal": ("6", 5), "stress_a": ("12", 10), "stress_b": ("25", 15)}
    assert plan["transaction_cost_model"]["historical_quote_or_nbbo_acquisition_required"] is False

    qualification = plan["source_qualification"]
    assert qualification["status"] == "DESIGNED-BUT-BLOCKED-BEFORE-AUTHORITY"
    assert qualification["fixed_sessions"]["expected_bar_rows"] == 14_742
    assert qualification["request_budget"]["maximum_logical_request_chains"] == 221
    assert qualification["request_budget"]["maximum_http_responses"] == 221
    assert (
        plan["free_tier_and_low_cost_feasibility"]["starter"]["durable_persistence_allowed"]
        is False
    )
    assert plan["next_authorization"]["current_state"] == "BLOCKED-BEFORE-AUTHORITY"
    assert not any(plan["authority"].values())
    assert not any(plan["protected_access"].values())
