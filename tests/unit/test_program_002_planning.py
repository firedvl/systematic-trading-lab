from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_PLAN = Path("config/research/cross-sectional-sector-etf-program-002-plan-proposal-v1.json")
_DATA_PLAN = Path(
    "config/research/cross-sectional-sector-etf-program-002-data-acquisition-plan-proposal-v1.json"
)
_UNIVERSE = Path("config/research/multi-hour-sector-etfs-v1.json")
_IMPLEMENTATION_PLAN = Path(
    "docs/research-campaigns/multi-hour-sector-etf-research-001-implementation-plan.md"
)
_REVIEW = Path(
    "config/research/cross-sectional-sector-etf-program-002-plan-independent-review-v1.json"
)
_PLAN_FINGERPRINT = "701dc67ea2da1e45d235f4247724b2bc8eb62853561c2400c17a668342c6b81e"
_PLAN_SHA256 = "2872d4d3301df0a85e1a5a2eba6e3ee533ee5573971121e99840041e7c8d2173"
_UNIVERSE_SHA256 = "8f07f73fd93f9432501d579e43616e1d9a09d6db77c347a6bed4151f2210c312"
_DATA_PLAN_SHA256 = "26c768f422e63e9f00e6adc88be2d57f5c6447972a9de1fa4873ab2826556aae"
_IMPLEMENTATION_PLAN_SHA256 = "aebfea81a2c8a4110d369dbd23d12e0ff79a661fc8f6187df0f27939abdfede5"
_REVIEW_FINGERPRINT = "55e30955789981a4eca129856322207ceb05fa9aebccb1101d892dd92f7a5d33"
_REVIEW_SHA256 = "b5023c90a7d748a7c8ac42609bad6d1c394150bc914c51b8b65c73e3d80c17e6"
_AUTHORITY_KEYS = {
    "market_data_acquisition",
    "strategy_implementation",
    "strategy_execution",
    "research_qualification",
    "controlled_evaluation",
    "protected_holdout",
    "paper_execution",
    "broker_writes",
    "live_execution",
}


def _load(relative: Path) -> dict[str, Any]:
    def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    value = json.loads(
        (_REPOSITORY / relative).read_text(encoding="utf-8"),
        object_pairs_hook=no_duplicate_keys,
    )
    assert isinstance(value, dict)
    return value


def _assert_false_authority(value: dict[str, Any]) -> None:
    assert set(value) == _AUTHORITY_KEYS
    assert not any(value.values())


def test_program_002_proposal_is_exact_and_non_launchable() -> None:
    plan = _load(_PLAN)

    assert plan["status"] == "PROPOSED-NOT-AUTHORIZED"
    unsigned = dict(plan)
    assert unsigned.pop("plan_fingerprint") == _PLAN_FINGERPRINT
    assert fingerprint(unsigned) == _PLAN_FINGERPRINT
    _assert_false_authority(plan["authority"])
    assert plan["launch_control"] == {
        "executable_plan": False,
        "dataset_bindings_present": False,
        "cost_model_binding_present": False,
        "implementation_commit_binding_present": False,
        "strategy_execution_authority_present": False,
        "launch_allowed": False,
    }

    grid = plan["configuration_grid"]
    configurations = {item["configuration_id"]: item for item in grid["configurations"]}
    assert len(configurations) == grid["configuration_count"] == 8
    assert {item["family_id"] for item in configurations.values()} == {
        "sector-relative-continuation-v1",
        "sector-relative-reversal-v1",
    }
    assert {item["strategy_id"] for item in plan["economic_contracts"]} == {
        "multi-hour-sector-relative-continuation-v1",
        "multi-hour-sector-relative-reversal-v1",
    }
    for configuration_id, configuration in configurations.items():
        assert len(configuration["immediate_neighbors"]) == 2
        for neighbor_id in configuration["immediate_neighbors"]:
            neighbor = configurations[neighbor_id]
            assert configuration_id in neighbor["immediate_neighbors"]
            assert configuration["family_id"] == neighbor["family_id"]
            changed_axes = sum(
                configuration[key] != neighbor[key]
                for key in ("lookback_30m_bars", "hold_30m_bars")
            )
            assert changed_axes == 1

    budget = plan["campaigns_and_budget"]
    assert budget["campaign_1"]["maximum_specs"] == 114
    assert budget["campaign_2"]["maximum_specs"] == 114
    assert budget["controlled_specs"] == 4
    assert budget["maximum_run_specifications"] == 232
    assert budget["maximum_attempts_per_specification"] == 3
    assert budget["maximum_infrastructure_attempts"] == 696
    assert "regardless of Campaign 1 merit" in budget["campaign_2"]["succession"]


def test_program_002_causal_portfolio_and_gate_contracts_are_frozen() -> None:
    plan = _load(_PLAN)

    decision = plan["feature_contract"]["decision"]
    assert decision["clock"] == "11:30:00 America/New_York"
    assert decision["latest_completed_bucket"] == "[11:00,11:30)"
    assert decision["latest_source_bar_open"] == "11:25:00 America/New_York"
    volume = plan["feature_contract"]["same_clock_relative_volume"]
    assert (
        "exactly the twenty immediately preceding complete XNYS sessions" in volume["denominator"]
    )
    assert volume["causality"] == "The decision session never contributes to its denominator."
    assert (
        "fails the whole dataset or run specification"
        in plan["feature_contract"]["invalid_input_action"]
    )

    portfolio = plan["portfolio_contract"]
    assert portfolio["construction"] == "long-flat"
    assert portfolio["maximum_positions"] == 3
    assert portfolio["unused_slots"] == "remain-cash-without-rescaling"
    assert portfolio["reentry"] is portfolio["resize"] is False
    scaling = portfolio["fee_reserve_and_uniform_scaling"]
    assert "scale = (B - R0) / B" in scaling["common_scale"]
    assert "post-entry cash" in scaling["cash_proof"]
    assert "Symbol iteration order cannot change quantities" in portfolio["simultaneous_sizing"]

    execution = plan["execution_contract"]
    assert "11:30 bar open is contemporaneous" in execution["order_creation"]
    assert execution["entry_fill_clocks"] == {
        "delay_1": "11:35",
        "delay_2": "11:40",
        "delay_3": "11:45",
    }
    assert execution["two_hour_exit_fill_clocks"] == {
        "delay_1": "13:35",
        "delay_2": "13:40",
        "delay_3": "13:45",
    }
    assert execution["four_hour_exit_fill_clocks"] == {
        "delay_1": "15:35",
        "delay_2": "15:40",
        "delay_3": "15:45",
    }
    assert "trade-ineligible and remains flat" in execution["early_close"]
    assert execution["market_impact_model"] is None
    assert execution["queue_position_model"] is None
    assert execution["partial_fill_model"] is None

    benchmark = plan["benchmark_contract"]
    assert "Generate the candidate selection trace once" in benchmark["signal_trace"]
    assert "Candidate and benchmark consume that same trace" in benchmark["signal_trace"]
    assert (
        fingerprint(plan["gates"])
        == "05214829bb3b8d78608d5777e4acb362d40a949805bcd56140d06394159bd22c"
    )


def test_program_002_universe_and_chronology_are_frozen() -> None:
    plan = _load(_PLAN)
    universe = _load(_UNIVERSE)

    assert universe["status"] == "PROPOSED-NOT-AUTHORIZED-FOR-ACQUISITION"
    _assert_false_authority(universe["authority"])
    assert len(universe["traded_symbols"]) == len(universe["ranking_symbols"]) == 12
    assert universe["traded_symbols"] == universe["ranking_symbols"]
    assert universe["context_and_benchmark_symbols"] == ["SPY"]
    assert "SPY" not in universe["traded_symbols"]
    assert {item["symbol"] for item in universe["memberships"]} == {
        *universe["traded_symbols"],
        "SPY",
    }
    universe_sha256 = hashlib.sha256((_REPOSITORY / _UNIVERSE).read_bytes()).hexdigest()
    assert plan["universe"]["sha256"] == universe_sha256

    chronology = plan["chronology"]
    assert chronology["engineering_development"]["market_period"] is None
    assert chronology["exposed_context_only"]["session_count"] == 20
    assert sum(block["xnys_sessions"] for block in chronology["discovery_blocks"]) == 377
    assert (
        sum(block["trade_eligible_full_sessions"] for block in chronology["discovery_blocks"])
        == 374
    )
    folds = chronology["walk_forward"]["folds"]
    assert len(folds) == 9
    assert chronology["base_selection_discovery_only"]["end"] < folds[0]["test_start"]
    assert all(
        left["test_end"] < right["test_start"]
        for left, right in zip(folds, folds[1:], strict=False)
    )
    assert folds[-1]["fold_id"] == chronology["walk_forward"]["final_exposed_fold"]
    assert folds[-1]["test_start"] == "2026-01-30"
    assert folds[-1]["test_end"] == "2026-07-31"
    assert (
        chronology["controlled_blocks"][0]["intraday_v3_overlap_acquired_by_program_002"] is False
    )
    assert chronology["substitute_range_allowed"] is False


def test_program_002_acquisition_plan_keeps_all_data_authority_false() -> None:
    data_plan = _load(_DATA_PLAN)

    assert data_plan["status"] == "PROPOSED-NOT-AUTHORIZED-FOR-ACQUISITION"
    _assert_false_authority(data_plan["authority"])
    assert not any(data_plan["launch_control"].values())
    assert data_plan["historical_bars"]["feed"] == "sip"
    assert data_plan["historical_bars"]["timeframe"] == "5Min"
    assert data_plan["quote_cost_calibration"]["iex_fallback"] is False
    assert data_plan["quote_cost_calibration"]["signal_prohibition"]

    exposed = data_plan["data_classes"]["A_exposed_research_and_development"]
    assert [item["role"] for item in exposed["datasets"]] == [
        "exposed-block-1",
        "exposed-block-2",
        "exposed-block-3",
    ]
    assert sum(item["expected_rows"] for item in exposed["datasets"]) == 1_526_538
    assert exposed["total_expected_rows"] == 1_526_538
    context = data_plan["data_classes"]["B_context_only"]
    assert context["exposed_dataset"]["role"] == "exposed-context-only"
    assert context["total_expected_rows"] == context["exposed_dataset"]["expected_rows"] == 20_280
    storage = data_plan["cost_storage_and_duration"]
    assert (
        storage["combined_bar_rows"]
        == (storage["exposed_evaluation_bar_rows"] + storage["context_only_bar_rows"])
        == 1_546_818
    )

    chunking = data_plan["request_chunking"]
    assert chunking["bar_segment_project_page_ceiling"] == 10
    assert chunking["quote_segment_project_page_ceiling"] == 100
    assert "not provider limits" in chunking["page_ceiling_semantics"]
    assert "no response-level feed attestation" in data_plan["historical_bars"]["feed_provenance"]
    quote_plan = data_plan["quote_cost_calibration"]
    assert len(quote_plan["sessions"]) == 73
    assert quote_plan["fill_clocks_new_york"] == [
        "11:35",
        "11:40",
        "11:45",
        "13:35",
        "13:40",
        "13:45",
        "15:35",
        "15:40",
        "15:45",
    ]
    assert len(quote_plan["symbols"]) == 13
    assert quote_plan["maximum_grid_observations"] == 73 * 9 * 60 * 13

    controlled = data_plan["data_classes"]["C_future_untouched_controlled_evaluation"]
    assert all(
        item["current_state"].startswith("UNACQUIRED-SEALED") for item in controlled["blocks"]
    )
    assert all("acquisition-only" in item["earliest_acquisition"] for item in controlled["blocks"])
    assert all(
        "separate one-use authority" in item["evaluation_authority"]
        for item in controlled["blocks"]
    )
    assert data_plan["regulatory_and_broker_fees"]["numeric_rates_frozen_now"] is False


def test_program_002_controlled_authorities_are_separate_and_block_b_is_conditional() -> None:
    plan = _load(_PLAN)
    implementation_plan = (_REPOSITORY / _IMPLEMENTATION_PLAN).read_text()

    controlled = plan["controlled_evaluation"]
    assert controlled["current_authority"] is False
    assert len(controlled["authority_sequence"]) == 5
    assert "acquisition-only authority" in controlled["authority_sequence"][0]
    assert "independent of acquisition" in controlled["authority_sequence"][2]
    assert "separate user evaluation authority" in controlled["authority_sequence"][3]
    assert "Acquisition authority can never" in controlled["authority_sequence"][4]
    assert "distinct one-use Block A evaluation authority" in controlled["block_a"]["evaluation"]
    assert (
        "Do not acquire, bind, or evaluate Block B unless Block A passed every controlled gate"
        in (controlled["block_b"]["dependency"])
    )
    assert "distinct one-use Block B evaluation authority" in controlled["block_b"]["evaluation"]
    receipt = controlled["protected_read_receipt"]
    assert "before opening any controlled artifact" in receipt["atomic_transition"]
    assert "authority remains unconsumed" in receipt["pre_receipt_failure"]
    assert "Do not issue another attempt" in receipt["post_receipt_failure"]
    trace = controlled["controlled_trace_artifact"]
    assert trace["producer"] == "candidate Normal specification only"
    assert "receipt exists before any full-universe" in trace["read_order"]
    assert "Exactly one trace exists" in trace["publication"]
    assert "every field except selection_trace_identity" in trace["benchmark_template"]
    assert (
        "replace only the template's null selection_trace_identity" in trace["benchmark_derivation"]
    )
    handoff = trace["handoff"]
    assert "re-derives the final benchmark specification" in handoff
    assert "registers it immutably" in handoff
    assert "consumes the template-bound benchmark grant" in handoff
    assert "creates its protected-read receipt before opening" in handoff
    assert "only the exact bound trace artifact and SPY bars" in trace["benchmark_read_scope"]
    assert (
        "status-and-hash attestation that exposes no metric bytes"
        in controlled["block_pair_processing"]
    )
    assert "The benchmark cannot load traded-symbol bars" in controlled["block_pair_processing"]
    assert "consume its SPY-only grant and receipt" not in controlled["block_pair_processing"]
    assert "immutable benchmark template whose only" in implementation_plan
    assert "substituting only the trace identity" in implementation_plan
    assert "consumes its full-universe grant, and creates its receipt" in implementation_plan
    assert "registers it immutably, consumes its grant" in implementation_plan
    assert "pre-registers two specifications" not in implementation_plan
    assert (
        "no protected-read receipt exists" in plan["campaigns_and_budget"]["controlled_retry_rule"]
    )


def test_program_002_planning_artifacts_bind_the_same_universe() -> None:
    plan = _load(_PLAN)
    data_plan = _load(_DATA_PLAN)
    universe = _load(_UNIVERSE)

    assert plan["program_id"] == data_plan["program_id"] == "multi-hour-sector-etf-research-001"
    assert plan["universe"]["universe_id"] == data_plan["universe"]["universe_id"] == universe["id"]
    assert plan["universe"]["sha256"] == data_plan["universe"]["sha256"]
    assert plan["universe"]["universe_fingerprint"] == data_plan["universe"]["universe_fingerprint"]
    plan_bytes = (_REPOSITORY / _PLAN).read_bytes()
    assert hashlib.sha256(plan_bytes).hexdigest() == _PLAN_SHA256
    assert data_plan["program_plan"] == {
        "path": _PLAN.as_posix(),
        "status_required": "PROPOSED-NOT-AUTHORIZED",
        "sha256": _PLAN_SHA256,
        "plan_fingerprint": _PLAN_FINGERPRINT,
    }


def test_program_002_independent_review_binds_exact_primary_artifacts() -> None:
    review_bytes = (_REPOSITORY / _REVIEW).read_bytes()
    review = _load(_REVIEW)
    unsigned = dict(review)

    assert hashlib.sha256(review_bytes).hexdigest() == _REVIEW_SHA256
    assert unsigned.pop("review_fingerprint") == _REVIEW_FINGERPRINT
    assert fingerprint(unsigned) == _REVIEW_FINGERPRINT
    assert review["status"] == "passed-planning-only-before-implementation-acquisition-or-execution"
    assert review["verdict"] == "pass"
    assert review["findings"] == []
    assert not any(review["authority"].values())
    assert not any(review["protected_access"].values())

    artifacts = review["reviewed_artifacts"]
    expected = {
        "universe": (_UNIVERSE, _UNIVERSE_SHA256),
        "program_plan": (_PLAN, _PLAN_SHA256),
        "data_acquisition_plan": (_DATA_PLAN, _DATA_PLAN_SHA256),
        "implementation_plan": (_IMPLEMENTATION_PLAN, _IMPLEMENTATION_PLAN_SHA256),
    }
    for name, (path, sha256) in expected.items():
        assert artifacts[name]["path"] == path.as_posix()
        assert hashlib.sha256((_REPOSITORY / path).read_bytes()).hexdigest() == sha256
        assert artifacts[name]["sha256"] == sha256
