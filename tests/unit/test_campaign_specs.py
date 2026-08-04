import copy
import json
from pathlib import Path

import pytest

from systematic_trading_lab.campaign_specs import load_training_campaign_plan


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
