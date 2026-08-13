from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from systematic_trading_lab.backtesting import CostModel
from systematic_trading_lab.datasets import (
    intraday_fixture_request,
    intraday_fixture_symbols,
)
from systematic_trading_lab.domain import OHLCVBar, Timeframe
from systematic_trading_lab.experiments import ExperimentSplit, IntradayExperimentSpec
from systematic_trading_lab.fingerprints import canonicalize, fingerprint
from systematic_trading_lab.intraday_qualification import (
    EVIDENCE_SCHEMA,
    REPORT_SCHEMA,
    evaluate_intraday_qualification,
    load_intraday_qualification_policy,
)
from systematic_trading_lab.intraday_reporting import (
    build_intraday_report,
    intraday_strategy_result,
)
from systematic_trading_lab.providers import IntradayFixtureProvider


def _report(
    *,
    status: str = "completed",
    experiment_id: str = "candidate-1",
    candidate_ordinal: int = 1,
    parent_candidate: str | None = None,
    cost_model_version: str = "conservative-bps-v1",
    cost_bps: str = "5",
    execution_model_version: str = "next-bar-v1",
    fill_delay_bars: int = 1,
    total_return: str = "0.10",
    early_close_session_count: object = 1,
) -> dict[str, object]:
    report: dict[str, object] = {
        "schema_version": REPORT_SCHEMA,
        "status": status,
        "provenance": {
            "experiment_id": experiment_id,
            "campaign_id": "campaign-1",
            "search_budget": 5,
            "candidate_ordinal": candidate_ordinal,
            "strategy_id": "intraday-baseline",
            "strategy_version": "v1",
            "strategy_family": "baseline",
            "code_commit": "b" * 40,
            "dataset_id": "intraday-fixture-v1",
            "dataset_fingerprint": "a" * 64,
            "universe_id": "liquid-etfs-intraday-5m-v1",
            "universe_fingerprint": "c" * 64,
            "parameters": {"window": 20},
            "timeframe": "5m",
            "session_policy_version": "XNYS-regular-session-flat-v1",
            "bar_timestamp_semantics_version": "bar-open-utc-v1",
            "session_return_policy_version": "session-close-v1",
            "benchmark_policy_version": "intraday-benchmark-v1",
            "cost_model_version": cost_model_version,
            "slippage_bps": cost_bps,
            "commission_bps": "1",
            "execution_model_version": execution_model_version,
            "earliest_fill_semantics": "next-bar-open-v1",
            "execution_delay_bars": fill_delay_bars,
            "split": "validation",
            "start_timestamp": "2026-01-01T14:30:00Z",
            "end_timestamp": "2026-02-01T21:00:00Z",
            "random_seed": 0,
            "creation_reason": "test",
            "parent_candidate": parent_candidate,
            "schema_version": "intraday-experiment-v1",
        },
        "metrics": {
            "total_return": total_return,
            "completed_round_trip_count": 25,
            "sessions_in_range": 25,
            "sessions_traded": 10,
            "sessions_traded_percentage": "0.40",
            "max_drawdown": "0.10",
            "best_trade_positive_profit_concentration": "0.25",
            "best_session_positive_profit_concentration": "0.30",
            "best_5_trades_positive_profit_concentration": "0.45",
            "best_symbol_positive_profit_concentration": "0.50",
            "overnight_position_count": 0,
            "outside_session_fill_count": 0,
            "early_close_session_count": early_close_session_count,
            "fixed_search_budget": 5,
        },
    }
    report["report_fingerprint"] = fingerprint(report)
    return report


def _policy() -> Any:
    return load_intraday_qualification_policy(
        Path("config/research/intraday-qualification-policy-v1.json")
    )


def _passing_inputs() -> tuple[
    dict[str, object], dict[str, dict[str, object]], dict[str, dict[str, object]]
]:
    base = _report()
    increased_cost = _report(
        experiment_id="candidate-1-cost-increased",
        candidate_ordinal=2,
        parent_candidate="candidate-1",
        cost_model_version="conservative-bps-2x-v1",
        cost_bps="12",
        total_return="0.05",
    )
    harsher_cost = _report(
        experiment_id="candidate-1-cost-harsher",
        candidate_ordinal=3,
        parent_candidate="candidate-1",
        cost_model_version="conservative-bps-4x-v1",
        cost_bps="24",
        total_return="0.03",
    )
    plus_one = _report(
        experiment_id="candidate-1-delay-plus-1",
        candidate_ordinal=4,
        parent_candidate="candidate-1",
        execution_model_version="delayed-2-bars-v1",
        fill_delay_bars=2,
        total_return="0.04",
    )
    plus_two = _report(
        experiment_id="candidate-1-delay-plus-2",
        candidate_ordinal=5,
        parent_candidate="candidate-1",
        execution_model_version="delayed-3-bars-v1",
        fill_delay_bars=3,
        total_return="0.02",
    )
    return (
        base,
        {"increased-cost": increased_cost, "harsher-cost": harsher_cost},
        {"plus-1-bar": plus_one, "plus-2-bars": plus_two},
    )


def _evaluate(
    base: dict[str, object],
    costs: dict[str, dict[str, object]],
    delays: dict[str, dict[str, object]],
) -> dict[str, object]:
    return evaluate_intraday_qualification(_policy(), base, costs, delays)


def test_passing_synthetic_metrics_remain_unbound_diagnostics() -> None:
    base, costs, delays = _passing_inputs()

    evidence = cast(dict[str, Any], _evaluate(base, costs, delays))

    assert evidence["schema_version"] == EVIDENCE_SCHEMA
    assert evidence["state"] == "research-gates-failed"
    binding_gates = {
        gate["metric"]: gate for gate in evidence["gates"] if "evidence" in gate["metric"]
    }
    search_gate = next(
        gate for gate in evidence["gates"] if gate["metric"] == "search_budget_accounted"
    )
    assert not binding_gates["registry_evidence_bound"]["passed"]
    assert not search_gate["passed"]
    assert evidence["evidence_binding"] == "unbound-diagnostic"
    assert "holdout" not in evidence
    assert "paper" not in evidence


def test_early_close_coverage_accepts_zero_but_rejects_invalid_counts() -> None:
    base, costs, delays = _passing_inputs()
    zero = _report(early_close_session_count=0)
    zero_evidence = cast(dict[str, Any], _evaluate(zero, costs, delays))
    zero_gate = next(
        gate for gate in zero_evidence["gates"] if gate["metric"] == "early_close_coverage"
    )
    assert zero_gate["passed"]

    for invalid in (-1, "0.5", None):
        report = _report(early_close_session_count=invalid)
        evidence = cast(dict[str, Any], _evaluate(report, costs, delays))
        gate = next(gate for gate in evidence["gates"] if gate["metric"] == "early_close_coverage")
        assert not gate["passed"]

    metrics = cast(dict[str, object], base["metrics"])
    metrics.pop("early_close_session_count")
    base["report_fingerprint"] = fingerprint(
        {key: value for key, value in base.items() if key != "report_fingerprint"}
    )
    missing_evidence = cast(dict[str, Any], _evaluate(base, costs, delays))
    missing_gate = next(
        gate for gate in missing_evidence["gates"] if gate["metric"] == "early_close_coverage"
    )
    assert not missing_gate["passed"]


def test_missing_or_failed_required_stress_evidence_fails_visible_gates() -> None:
    base, costs, delays = _passing_inputs()
    missing = cast(dict[str, Any], _evaluate(base, {}, delays))
    assert missing["state"] == "research-gates-failed"
    assert {"name": "increased-cost", "status": "missing"}.items() <= missing["sources"][1].items()

    failed_cost = deepcopy(costs["increased-cost"])
    failed_cost["status"] = "failed"
    failed_cost["report_fingerprint"] = fingerprint(
        {key: value for key, value in failed_cost.items() if key != "report_fingerprint"}
    )
    evidence = cast(
        dict[str, Any],
        _evaluate(base, {**costs, "increased-cost": failed_cost}, delays),
    )
    cost_gate = next(
        gate for gate in evidence["gates"] if gate["metric"] == "cost_stress_completed"
    )
    assert not cost_gate["passed"]
    failed_source = next(
        source
        for source in evidence["sources"]
        if source["role"] == "higher-cost" and source["name"] == "increased-cost"
    )
    assert failed_source["status"] == "failed"


def test_lineage_mismatch_is_visible_and_fails_configuration_gate() -> None:
    base, costs, delays = _passing_inputs()
    mismatched = deepcopy(delays["plus-1-bar"])
    cast(dict[str, Any], mismatched["provenance"])["dataset_id"] = "another-dataset"
    mismatched["report_fingerprint"] = fingerprint(
        {key: value for key, value in mismatched.items() if key != "report_fingerprint"}
    )

    evidence = cast(
        dict[str, Any],
        _evaluate(base, costs, {**delays, "plus-1-bar": mismatched}),
    )

    assert "whole-bar-delay:plus-1-bar" in evidence["lineage_errors"]
    configuration = next(
        gate for gate in evidence["gates"] if gate["metric"] == "configuration_identity"
    )
    assert not configuration["passed"]


def test_stress_role_rejects_changes_to_other_model_assumptions() -> None:
    base, costs, delays = _passing_inputs()
    changed_delay = deepcopy(costs["increased-cost"])
    cast(dict[str, Any], changed_delay["provenance"])["execution_delay_bars"] = 9
    changed_delay["report_fingerprint"] = fingerprint(
        {key: value for key, value in changed_delay.items() if key != "report_fingerprint"}
    )

    cost_evidence = cast(
        dict[str, Any], _evaluate(base, {**costs, "increased-cost": changed_delay}, delays)
    )

    assert (
        cost_evidence["lineage_errors"]["higher-cost:increased-cost"]
        == "variant-changes-fields-outside-its-role"
    )
    assert cost_evidence["state"] == "research-gates-failed"

    changed_cost = deepcopy(delays["plus-1-bar"])
    cast(dict[str, Any], changed_cost["provenance"])["slippage_bps"] = "99"
    changed_cost["report_fingerprint"] = fingerprint(
        {key: value for key, value in changed_cost.items() if key != "report_fingerprint"}
    )
    delay_evidence = cast(
        dict[str, Any], _evaluate(base, costs, {**delays, "plus-1-bar": changed_cost})
    )

    assert (
        delay_evidence["lineage_errors"]["whole-bar-delay:plus-1-bar"]
        == "variant-changes-fields-outside-its-role"
    )


def test_delay_stress_roles_require_the_named_whole_bar_offsets() -> None:
    base, costs, delays = _passing_inputs()
    duplicate_plus_one = deepcopy(delays["plus-2-bars"])
    provenance = cast(dict[str, Any], duplicate_plus_one["provenance"])
    provenance["execution_model_version"] = "delayed-2-bars-v1"
    provenance["execution_delay_bars"] = 2
    duplicate_plus_one["report_fingerprint"] = fingerprint(
        {key: value for key, value in duplicate_plus_one.items() if key != "report_fingerprint"}
    )

    evidence = cast(
        dict[str, Any],
        _evaluate(base, costs, {**delays, "plus-2-bars": duplicate_plus_one}),
    )

    assert (
        evidence["lineage_errors"]["whole-bar-delay:plus-2-bars"]
        == "delay-variant-does-not-match-required-whole-bar-offset"
    )
    delay_gate = next(
        gate for gate in evidence["gates"] if gate["metric"] == "delay_stress_completed"
    )
    assert not delay_gate["passed"]


def test_harsher_cost_role_must_exceed_the_increased_cost_role() -> None:
    base, costs, delays = _passing_inputs()
    duplicate_increased = deepcopy(costs["harsher-cost"])
    provenance = cast(dict[str, Any], duplicate_increased["provenance"])
    provenance["cost_model_version"] = "another-increased-cost-v1"
    provenance["slippage_bps"] = "12"
    duplicate_increased["report_fingerprint"] = fingerprint(
        {key: value for key, value in duplicate_increased.items() if key != "report_fingerprint"}
    )

    evidence = cast(
        dict[str, Any],
        _evaluate(base, {**costs, "harsher-cost": duplicate_increased}, delays),
    )

    assert (
        evidence["lineage_errors"]["higher-cost:harsher-cost"]
        == "harsher-cost-variant-is-not-higher-than-increased-cost"
    )


def test_evidence_is_deterministic_and_has_no_authority_fields() -> None:
    base, costs, delays = _passing_inputs()

    first = cast(dict[str, Any], _evaluate(base, costs, delays))
    second = cast(dict[str, Any], _evaluate(base, costs, delays))

    assert first == second
    assert (
        fingerprint({key: value for key, value in first.items() if key != "report_fingerprint"})
        == first["report_fingerprint"]
    )
    assert not {"holdout_authorization", "paper_authorization", "broker_authorization"} & set(first)


def test_actual_intraday_report_contract_is_accepted_without_stress_evidence() -> None:
    timeframe = Timeframe.FIVE_MINUTES
    request = intraday_fixture_request(timeframe)
    bars = tuple(
        OHLCVBar.from_record(record)
        for record in IntradayFixtureProvider().fetch(
            intraday_fixture_symbols(), timeframe, request
        )
    )
    spec = IntradayExperimentSpec(
        experiment_id="actual-cash",
        campaign_id="actual-contract",
        search_budget=1,
        candidate_ordinal=1,
        strategy_id="intraday-cash",
        strategy_version="1",
        strategy_family="intraday-cash-baseline",
        code_commit="abc123",
        dataset_id="fixture",
        dataset_fingerprint="fixture-fingerprint",
        universe_id="liquid-etfs-intraday-5m-v1",
        universe_fingerprint="universe-fingerprint",
        parameters={},
        timeframe="5m",
        session_policy_version="XNYS-regular-session-flat-v1",
        bar_timestamp_semantics_version="bar-open-utc-v1",
        session_return_policy_version="XNYS-session-close-equity-v1",
        benchmark_policy_version="cash-and-continuous-underlying-v1",
        cost_model_version="conservative-bps-v1",
        slippage_bps=Decimal("5"),
        commission_bps=Decimal("1"),
        execution_model_version="deterministic-next-bar-open-v1",
        earliest_fill_semantics="completed-bar-next-bar-open-v1",
        execution_delay_bars=1,
        split=ExperimentSplit.TRAINING,
        start_timestamp=datetime(2025, 11, 26, 14, 30, tzinfo=UTC),
        end_timestamp=datetime(2025, 11, 28, 17, 55, tzinfo=UTC),
        random_seed=0,
        creation_reason="contract compatibility",
    )
    result = intraday_strategy_result(
        spec.strategy_id, bars, Decimal("1000"), CostModel(), timeframe
    )
    provenance = cast(dict[str, object], canonicalize(spec))
    report = build_intraday_report(provenance, result, bars)

    evidence = evaluate_intraday_qualification(_policy(), report, {}, {})

    assert evidence["state"] == "research-gates-failed"
    assert evidence["candidate_id"] == spec.experiment_id
    sources = cast(list[dict[str, object]], evidence["sources"])
    assert any(source["status"] == "missing" for source in sources)
