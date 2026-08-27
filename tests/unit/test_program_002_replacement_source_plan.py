from __future__ import annotations

import hashlib
import json
from pathlib import Path

from systematic_trading_lab.fingerprints import fingerprint

ROOT = Path(__file__).parents[2]
PLAN = ROOT / "config/research/program-002-replacement-data-source-plan-v1.json"


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def test_replacement_source_plan_is_frozen_and_non_authoritative() -> None:
    plan = json.loads(PLAN.read_text(), object_pairs_hook=_strict_object)
    unsigned = dict(plan)

    assert (
        fingerprint(plan["source_neutral_requirements"])
        == plan["source_neutral_requirements_fingerprint"]
    )
    assert unsigned.pop("plan_fingerprint") == fingerprint(unsigned)
    assert not any(plan["authority"].values())
    assert plan["architecture_decision"]["fallback"] is None
    assert plan["architecture_decision"]["maximum_provider_qualification_attempts"] == 1

    for binding in plan["immutable_bindings"].values():
        path = ROOT / binding["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"]

    sample = plan["source_qualification_design"]
    assert sample["bar_sessions"]["expected_aggregate_rows"] == 13 * (8 * 78 + 42)
    assert sample["quote_symbol_windows"] == 13 * 4 * 9
    assert sample["quote_grid_observations"] == sample["quote_symbol_windows"] * 60
    budget = sample["resource_limits"]["request_chain_budget"]
    assert (
        sum(
            budget[key]
            for key in (
                "aggregate_symbol_sessions",
                "raw_trade_symbol_sessions",
                "quote_symbol_windows",
                "corporate_action_symbol_endpoint_pairs",
            )
        )
        == budget["expected_and_maximum_total"]
        == 630
    )
