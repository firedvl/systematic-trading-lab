import copy
import json
from pathlib import Path

import pytest

from systematic_trading_lab.campaign_specs import (
    build_planned_intraday_experiment,
    load_intraday_research_campaign_plan,
    load_training_campaign_plan,
    parse_intraday_research_campaign_plan,
)

INTRADAY_PLAN = Path("config/research/intraday-campaign-v1.json")


def plan_payload() -> dict[str, object]:
    return {
        "schema_version": "training-campaign-plan-v1",
        "campaign_id": "sealed-training",
        "name": "Sealed training",
        "search_budget": 2,
        "code_commit": "abc123",
        "dataset_id": "dataset-1",
        "dataset_fingerprint": "dataset-fingerprint-1",
        "universe_id": "liquid-etfs-v1",
        "universe_fingerprint": "universe-fingerprint-1",
        "candidates": [
            {
                "experiment_id": "benchmark",
                "role": "benchmark",
                "strategy_id": "fixed-weight",
                "strategy_version": "1",
                "strategy_family": "allocation",
                "parameters": {},
                "start_timestamp": "2020-01-01T00:00:00Z",
                "end_timestamp": "2020-12-31T00:00:00Z",
                "random_seed": 0,
                "creation_reason": "sealed benchmark",
                "parent_candidate": None,
            },
            {
                "experiment_id": "candidate",
                "role": "base",
                "strategy_id": "moving-average-trend",
                "strategy_version": "1",
                "strategy_family": "trend",
                "parameters": {"window": 20},
                "start_timestamp": "2020-01-01T00:00:00Z",
                "end_timestamp": "2020-12-31T00:00:00Z",
                "random_seed": 0,
                "creation_reason": "sealed candidate",
                "parent_candidate": "benchmark",
            },
        ],
    }


def write_plan(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_training_campaign_plan_is_strict_and_deterministic(tmp_path: Path) -> None:
    path = write_plan(tmp_path / "plan.json", plan_payload())
    first = load_training_campaign_plan(path)
    second = load_training_campaign_plan(path)

    assert first.plan_fingerprint == second.plan_fingerprint
    assert len(first.candidates) == first.search_budget == 2
    assert first.candidates[1].parameters == {"window": 20}


@pytest.mark.parametrize("defect", ("unknown-field", "budget", "parent", "parameters"))
def test_training_campaign_plan_rejects_unsealed_variation(tmp_path: Path, defect: str) -> None:
    payload = copy.deepcopy(plan_payload())
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    second = candidates[1]
    assert isinstance(second, dict)
    if defect == "unknown-field":
        payload["unexpected"] = True
    elif defect == "budget":
        payload["search_budget"] = 3
    elif defect == "parent":
        second["parent_candidate"] = "undeclared"
    else:
        second["parameters"] = {}

    with pytest.raises(ValueError):
        load_training_campaign_plan(write_plan(tmp_path / f"{defect}.json", payload))


@pytest.mark.parametrize(
    ("strategy_id", "family", "parameter"),
    (
        ("moving-average-mean-reversion", "mean-reversion", "window"),
        ("volatility-targeted-exposure", "volatility", "volatility_window"),
    ),
)
def test_training_plan_rejects_invalid_new_baseline_windows(
    tmp_path: Path, strategy_id: str, family: str, parameter: str
) -> None:
    payload = plan_payload()
    candidates = payload["candidates"]
    assert isinstance(candidates, list) and isinstance(candidates[1], dict)
    candidates[1].update(
        strategy_id=strategy_id,
        strategy_family=family,
        parameters={parameter: 1},
    )

    with pytest.raises(ValueError, match="planned parameters differ"):
        load_training_campaign_plan(write_plan(tmp_path / "invalid-window.json", payload))


def test_training_plan_accepts_strategic_allocation(tmp_path: Path) -> None:
    payload = plan_payload()
    candidates = payload["candidates"]
    assert isinstance(candidates, list) and isinstance(candidates[1], dict)
    candidates[1].update(
        strategy_id="strategic-allocation-portfolio",
        strategy_family="portfolio-allocation",
        parameters={"rebalance_every": 21},
    )

    plan = load_training_campaign_plan(write_plan(tmp_path / "allocation.json", payload))

    assert plan.candidates[1].parameters == {"rebalance_every": 21}


def test_intraday_campaign_v1_reserves_the_complete_fixed_matrix() -> None:
    first = load_intraday_research_campaign_plan(INTRADAY_PLAN)
    second = load_intraday_research_campaign_plan(INTRADAY_PLAN)

    assert first.plan_fingerprint == second.plan_fingerprint
    assert (
        first.plan_fingerprint == "ce81be36d02cc15f421390bf3d3787714bb0b025797ccfb8de2c1d1236052c1a"
    )
    assert first.base_code_commit == "b1774f547da2976348430b820faf2ebdacdf46af"
    assert len(first.candidates) == first.search_budget == 60
    assert [candidate.candidate_ordinal for candidate in first.candidates] == list(range(1, 61))
    assert [period.role for period in first.periods] == [
        "training",
        "validation-a",
        "validation-b",
        "validation-c",
    ]
    assert sum(candidate.variant_role == "base" for candidate in first.candidates) == 12
    assert sum(candidate.variant_role.endswith("cost") for candidate in first.candidates) == 24
    assert sum(candidate.variant_role.startswith("plus-") for candidate in first.candidates) == 24
    for offset in range(0, first.search_budget, 5):
        group = first.candidates[offset : offset + 5]
        assert [candidate.variant_role for candidate in group] == [
            "base",
            "increased-cost",
            "harsher-cost",
            "plus-1-bar",
            "plus-2-bars",
        ]
        assert group[0].parent_candidate is None
        assert all(candidate.parent_candidate == group[0].experiment_id for candidate in group[1:])
        assert [candidate.execution_delay_bars for candidate in group] == [1, 1, 1, 2, 3]


def test_intraday_campaign_v1_binds_only_the_exact_planned_dataset() -> None:
    plan = load_intraday_research_campaign_plan(INTRADAY_PLAN)
    manifest: dict[str, object] = {
        "identity": {"dataset_id": "dataset-1", "fingerprint": "dataset-fingerprint-1"},
        "provider": "alpaca",
        "timeframe": "5m",
        "adjustment_policy": "provider-adjusted-all-v1",
        "calendar_policy": "XNYS-regular-session-bars-v1",
        "timestamp_policy": "bar-open-utc-v1",
        "requested_range": {
            "start": "2025-07-01T13:30:00Z",
            "end": "2025-12-31T20:55:00Z",
        },
        "actual_range": {
            "start": "2025-07-01T13:30:00Z",
            "end": "2025-12-31T20:55:00Z",
        },
        "symbols": [{"value": "SPY"}, {"value": "QQQ"}],
        "universe_id": "liquid-etfs-intraday-5m-v1",
        "universe_fingerprint": "6ac4a8269f8e352536f52ddc0a3000e0b39c5551c33c03959c20a640cfddeca9",
    }

    spec = build_planned_intraday_experiment(
        plan,
        "intraday-research-v1-cash-training-base",
        manifest,
    )

    assert spec.candidate_ordinal == 1
    assert spec.strategy_id == "intraday-cash"
    assert spec.dataset_id == "dataset-1"
    assert spec.start_timestamp == plan.periods[0].start_timestamp
    assert spec.parent_candidate is None

    changed = copy.deepcopy(manifest)
    actual_range = changed["actual_range"]
    assert isinstance(actual_range, dict)
    actual_range["start"] = "2025-07-02T13:30:00Z"
    with pytest.raises(ValueError, match="does not match the planned intraday period"):
        build_planned_intraday_experiment(
            plan,
            "intraday-research-v1-cash-training-base",
            changed,
        )


@pytest.mark.parametrize(
    ("defect", "message"),
    (
        ("strategy", "fixed strategy contract differs"),
        ("period", "UTC bounds do not cover exact XNYS sessions"),
        ("cost", "cost stresses must increase"),
        ("ordered-cost-change", "differs from the reviewed v1 preregistration"),
        ("group", "candidate group ordering differs"),
        ("neighbors", "does not authorize parameter neighbors"),
        ("holdout", "authority boundary differs"),
        ("policy", "qualification policy differs"),
    ),
)
def test_intraday_campaign_v1_rejects_post_registration_variation(
    defect: str, message: str
) -> None:
    payload = json.loads(INTRADAY_PLAN.read_text(encoding="utf-8"))
    if defect == "strategy":
        payload["strategies"][1]["parameters"]["lookback"] = 2
    elif defect == "period":
        payload["periods"][1]["start_timestamp"] = "2026-01-05T14:30:00Z"
    elif defect == "cost":
        payload["cost_models"][2]["slippage_bps"] = "5"
    elif defect == "ordered-cost-change":
        payload["cost_models"][2]["slippage_bps"] = "21"
    elif defect == "group":
        payload["candidate_groups"][1]["ordinal_start"] = 7
    elif defect == "neighbors":
        payload["parameter_neighbors"] = [{"window": 11}]
    elif defect == "holdout":
        payload["authorities"]["protected_holdout"] = True
    else:
        payload["qualification_policy_fingerprint"] = "changed"

    with pytest.raises(ValueError, match=message):
        parse_intraday_research_campaign_plan(payload)
