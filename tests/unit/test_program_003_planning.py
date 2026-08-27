from __future__ import annotations

import json
from hashlib import sha256
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

    predecessor = plan["inherited_predecessor_contract"]
    predecessor_path = _REPOSITORY / predecessor["path"]
    predecessor_plan = json.loads(predecessor_path.read_text())
    predecessor_unsigned = dict(predecessor_plan)
    assert predecessor["sha256"] == sha256(predecessor_path.read_bytes()).hexdigest()
    assert predecessor_unsigned.pop("plan_fingerprint") == predecessor["fingerprint"]
    assert predecessor["fingerprint"] == fingerprint(predecessor_unsigned)
    assert "controlled_evaluation" in predecessor["inherited_paths"]
    assert predecessor["unlisted_inherited_change_allowed"] is False

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
    force_fill = plan["force_fill_policy"]
    assert all(
        force_fill[key] is False
        for key in (
            "required_value",
            "forward_fill",
            "backward_fill",
            "interpolation",
            "synthetic_ohlc",
            "previous_close_substitution",
        )
    )

    missing = plan["missing_data_policy"]["maximum_loss"]
    assert missing["overall_excluded_full_session_rate_max"] == "0.005"
    assert missing["overall_excluded_full_session_count_max"] == 7
    assert missing["excluded_sessions_per_rolling_63_expected_sessions_max"] == 1
    assert missing["sessions_with_same_symbol_missing_per_rolling_252_expected_sessions_max"] == 1
    assert plan["missing_data_policy"]["return_blind_numeric_derivation"][
        "global_half_percent_and_seven_sessions"
    ].startswith("The global rate is half")

    costs = plan["transaction_cost_model"]["scenarios"]
    assert {
        key: (value["total_bps_per_side"], value["execution_delay_minutes"])
        for key, value in costs.items()
    } == {"normal": ("6", 5), "stress_a": ("12", 10), "stress_b": ("25", 15)}
    assert {
        key: (value["total_bps_per_side"], value["execution_delay_minutes"])
        for key, value in plan["transaction_cost_model"]["isolated_delay_scenarios"].items()
    } == {"normal-delay-2": ("6", 10), "normal-delay-3": ("6", 15)}
    assert plan["transaction_cost_model"]["historical_quote_or_nbbo_acquisition_required"] is False

    controlled = plan["chronology"]["controlled_evaluation_invariants"]
    assert plan["chronology"]["controlled_blocks"][0]["warmup_context_sessions"] == 20
    assert plan["chronology"]["controlled_blocks"][0]["evaluation_begins_session_ordinal"] == 21
    assert controlled["acquisition_authority_can_grant_evaluation"] is False
    assert controlled["replacement_read_grants_allowed"] is False
    assert controlled["post_receipt_retry_or_reread_allowed"] is False
    assert controlled["block_b_independent_acquisition_allowed"] is False

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


def test_program_003_independent_review_binds_the_plan() -> None:
    review = _load("config/research/program-003-low-cost-successor-plan-independent-review-v1.json")
    unsigned = dict(review)

    assert unsigned.pop("review_fingerprint") == fingerprint(unsigned)
    assert review["verdict"] == "pass"
    assert review["findings"] == []
    assert [item["verdict"] for item in review["review_iterations"]] == ["fail", "pass"]

    plan_binding = review["reviewed_plan"]
    plan_path = _REPOSITORY / plan_binding["path"]
    plan = json.loads(plan_path.read_text())
    assert sha256(plan_path.read_bytes()).hexdigest() == plan_binding["sha256"]
    assert plan["plan_fingerprint"] == plan_binding["fingerprint"]

    documentation = review["reviewed_documentation"]
    assert (
        sha256((_REPOSITORY / documentation["path"]).read_bytes()).hexdigest()
        == documentation["sha256"]
    )
    assert not any(review["authority"].values())
    assert not any(review["protected_access"].values())
