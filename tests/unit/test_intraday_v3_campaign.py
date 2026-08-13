import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from systematic_trading_lab.datasets import _version_key
from systematic_trading_lab.domain import AdjustmentPolicy, Symbol, Timeframe, TimestampRange
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.intraday_v3_campaign import (
    REVIEWED_V3_CAMPAIGN_PLAN_FINGERPRINT,
    IntradayV3CampaignPlan,
    build_intraday_v3_experiment,
    build_intraday_v3_experiments,
    load_intraday_v3_campaign_plan,
    parse_intraday_v3_campaign_plan,
)

PLAN_PATH = Path("config/research/intraday-campaign-v3.json")
_HASH = "a" * 64


def _manifest(plan: IntradayV3CampaignPlan, role: str, number: int) -> dict[str, object]:
    periods = plan.periods
    period = next(item for item in periods if item.role == role)
    start = period.start_timestamp.isoformat().replace("+00:00", "Z")
    end = period.end_timestamp.isoformat().replace("+00:00", "Z")
    data_fingerprint = f"{number + 4:x}" * 64
    raw_fingerprint = _HASH
    dataset_id = fingerprint(
        _version_key(
            "alpaca-historical-v2",
            (Symbol("SPY"), Symbol("QQQ")),
            Timeframe.FIVE_MINUTES,
            TimestampRange(period.start_timestamp, period.end_timestamp),
            AdjustmentPolicy.PROVIDER_ADJUSTED_ALL,
            "ohlcv-normalization-v1",
            "ohlcv-v1",
            "XNYS-regular-session-bars-v1",
            "bar-open-utc-v1",
            "liquid-etfs-intraday-5m-v1",
            "6ac4a8269f8e352536f52ddc0a3000e0b39c5551c33c03959c20a640cfddeca9",
            "iex",
            data_fingerprint,
            raw_fingerprint,
        )
    )
    return {
        "identity": {"dataset_id": dataset_id, "fingerprint": data_fingerprint},
        "provider": "alpaca-historical-v2",
        "symbols": [{"value": "SPY"}, {"value": "QQQ"}],
        "timeframe": "5m",
        "requested_range": {"start": start, "end": end},
        "actual_range": {"start": start, "end": end},
        "retrieval_timestamp": "2027-04-16T12:00:00Z",
        "raw_artifact_hashes": [raw_fingerprint],
        "normalization_version": "ohlcv-normalization-v1",
        "schema_version": "ohlcv-v1",
        "adjustment_policy": "provider-adjusted-all-v1",
        "calendar_policy": "XNYS-regular-session-bars-v1",
        "timestamp_policy": "bar-open-utc-v1",
        "universe_id": "liquid-etfs-intraday-5m-v1",
        "universe_fingerprint": "6ac4a8269f8e352536f52ddc0a3000e0b39c5551c33c03959c20a640cfddeca9",
        "validation": {
            "errors": [],
            "missing_intervals": [],
            "duplicate_intervals": [],
            "conflicts": [],
            "quarantined_records": 0,
        },
        "feed": "iex",
        "parent_dataset_id": None,
    }


def test_v3_campaign_plan_reserves_the_complete_sealed_matrix() -> None:
    plan = load_intraday_v3_campaign_plan(PLAN_PATH)

    assert plan.plan_fingerprint == REVIEWED_V3_CAMPAIGN_PLAN_FINGERPRINT
    assert len(plan.candidates) == plan.search_budget == 60
    assert [item.candidate_ordinal for item in plan.candidates] == list(range(1, 61))
    assert [item.role for item in plan.periods] == [
        "training",
        "validation-a",
        "validation-b",
        "validation-c",
    ]
    assert [(item.session_count, item.per_symbol_bar_opens) for item in plan.periods] == [
        (251, 19470),
        (45, 3474),
        (45, 3474),
        (45, 3510),
    ]
    assert [item.strategy_id for item in plan.candidates[::20]] == [
        "intraday-event-driven-ma-trend",
        "intraday-30-minute-momentum",
        "intraday-30-minute-opening-range-breakout",
    ]
    for offset in range(0, 60, 5):
        group = plan.candidates[offset : offset + 5]
        assert [item.variant_role for item in group] == [
            "base",
            "increased-cost",
            "harsher-cost",
            "plus-1-bar",
            "plus-2-bars",
        ]
        assert group[0].parent_candidate is None
        assert [item.parent_candidate for item in group[1:]] == [group[0].experiment_id] * 4
        assert [
            (item.slippage_bps, item.commission_bps, item.execution_delay_bars) for item in group
        ] == [
            (Decimal("5"), Decimal("1"), 1),
            (Decimal("10"), Decimal("2"), 1),
            (Decimal("20"), Decimal("5"), 1),
            (Decimal("5"), Decimal("1"), 2),
            (Decimal("5"), Decimal("1"), 3),
        ]


@pytest.mark.parametrize(
    "mutation",
    ("fingerprint", "inventory", "selection", "qualification", "authority", "range", "reservation"),
)
def test_v3_campaign_plan_rejects_any_bound_contract_mutation(mutation: str) -> None:
    payload = cast(dict[str, Any], json.loads(PLAN_PATH.read_text(encoding="utf-8")))
    changed = copy.deepcopy(payload)
    if mutation == "fingerprint":
        changed["plan_fingerprint"] = "0" * 64
    elif mutation == "inventory":
        changed["prospective_freshness"]["inventory_fingerprint"] = "0" * 64
    elif mutation == "selection":
        changed["prospective_freshness"]["period_selection_fingerprint"] = "0" * 64
    elif mutation == "qualification":
        changed["qualification_binding"]["fingerprint"] = "0" * 64
    elif mutation == "authority":
        changed["authorities"]["protected_holdout"] = True
    elif mutation == "range":
        changed["periods"][1]["per_symbol_bar_opens"] = 1
    else:
        changed["qualification_groups"][0]["roles"]["base"] = "different"

    with pytest.raises(ValueError):
        parse_intraday_v3_campaign_plan(changed)


def test_v3_campaign_builds_all_candidates_from_exact_four_dataset_roles() -> None:
    plan = load_intraday_v3_campaign_plan(PLAN_PATH)
    manifests = {
        role: _manifest(plan, role, index + 1)
        for index, role in enumerate(("training", "validation-a", "validation-b", "validation-c"))
    }

    specs = build_intraday_v3_experiments(plan, "b" * 40, manifests)

    assert len(specs) == 60
    assert {item.dataset_id for item in specs} == {
        cast(dict[str, object], manifests[role]["identity"])["dataset_id"] for role in manifests
    }
    assert specs[0].experiment_id == plan.candidates[0].experiment_id
    assert specs[-1].experiment_id == plan.candidates[-1].experiment_id
    with pytest.raises(ValueError, match="dataset roles differ"):
        build_intraday_v3_experiments(plan, "b" * 40, {"training": manifests["training"]})


@pytest.mark.parametrize("defect", ("range", "integrity", "raw", "backdated", "unknown"))
def test_v3_campaign_rejects_manifest_without_exact_range_and_integrity(defect: str) -> None:
    plan = load_intraday_v3_campaign_plan(PLAN_PATH)
    manifest = _manifest(plan, "training", 1)
    if defect == "range":
        manifest["actual_range"] = {"start": "2025-07-02T13:30:00Z", "end": "2026-06-30T19:55:00Z"}
    elif defect == "integrity":
        cast(dict[str, object], manifest["validation"])["missing_intervals"] = ["missing"]
    elif defect == "raw":
        manifest["raw_artifact_hashes"] = []
    elif defect == "backdated":
        manifest["retrieval_timestamp"] = "2026-06-01T12:00:00Z"
    else:
        manifest["unexpected"] = True

    with pytest.raises(ValueError):
        build_intraday_v3_experiment(plan, "b" * 40, plan.candidates[0].experiment_id, manifest)
