from __future__ import annotations

import hashlib
import json
from decimal import ROUND_DOWN, ROUND_UP, localcontext
from pathlib import Path
from typing import Any, cast

import pytest

import systematic_trading_lab.intraday_fed_policy_absorption_001_runner as runner_module
from systematic_trading_lab.fingerprints import canonical_json, fingerprint
from systematic_trading_lab.intraday_execution_cost_model import (
    load_intraday_execution_cost_model,
)
from systematic_trading_lab.intraday_exposed_002_runner import _scenarios
from systematic_trading_lab.intraday_fed_policy_absorption_001_plan import (
    load_intraday_fed_policy_absorption_001_plan,
)
from systematic_trading_lab.intraday_fed_policy_absorption_001_runner import (
    _EQUIVALENCE_EVENTS,
    IntradayFedPolicyAbsorption001Runner,
    IntradayFedPolicyAbsorption001Store,
    _equivalence_specification,
    _EquivalenceWorker,
    _parallel_equivalence,
    _select_eligible,
    _validate_run_report_payload,
    _validate_stage_specifications,
    decode_canonical_metric,
    intraday_fed_policy_absorption_001_plan_summary,
)

_SOURCE_COMMIT = "a" * 40


def _synthetic_report(
    repository: Path, *, scenario_id: str = "normal", configuration_index: int = 0
) -> tuple[dict[str, Any], dict[str, object]]:
    plan = load_intraday_fed_policy_absorption_001_plan(repository)
    model = load_intraday_execution_cost_model(repository)
    specification = _equivalence_specification(
        plan,
        model,
        plan.configurations[configuration_index],
        scenario_id,
        _SOURCE_COMMIT,
    )
    result = _EquivalenceWorker(repository)(specification)
    raw = result["report_bytes"]
    assert isinstance(raw, bytes)
    return cast(dict[str, Any], json.loads(raw)), dict(result)


def test_canonical_metric_decoder_is_strict() -> None:
    assert str(decode_canonical_metric("0.25")) == "0.25"
    assert decode_canonical_metric(3) == 3
    assert decode_canonical_metric(None, allow_null=True) is None
    for value in (True, 0.25, " 0.25", "2.50", "1e-2", "NaN", None):
        with pytest.raises(ValueError):
            decode_canonical_metric(value)


def test_selection_preserves_frozen_parent_order() -> None:
    ledger = (
        {"candidate": {"candidate_id": "first"}, "eligible": True},
        {"candidate": {"candidate_id": "second"}, "eligible": True},
        {"candidate": {"candidate_id": "third"}, "eligible": True},
    )
    assert _select_eligible(ledger, 2, key=lambda _: (0,)) == ("first", "second")


def test_unbound_runner_fails_before_runtime_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = Path.cwd()
    runtime = tmp_path / "runtime"
    assert (
        intraday_fed_policy_absorption_001_plan_summary(repository)["launch_control_bound"] is False
    )
    with pytest.raises(ValueError, match="launch control"):
        IntradayFedPolicyAbsorption001Runner(repository, runtime)
    assert not runtime.exists()
    monkeypatch.setenv("APCA_API_KEY_ID", "not-a-secret-test-value")
    with pytest.raises(ValueError, match="broker environment"):
        IntradayFedPolicyAbsorption001Runner(repository, runtime)
    assert not runtime.exists()


def test_synthetic_report_binds_split_traces_and_exact_timing() -> None:
    report, _result = _synthetic_report(Path.cwd())

    _validate_run_report_payload(report, _EQUIVALENCE_EVENTS)
    details = cast(dict[str, Any], report["details"])
    evidence = cast(dict[str, str], report["execution_evidence"])
    causal = cast(dict[str, Any], details["cross_scenario_trace"])
    execution = cast(dict[str, Any], details["execution_trace"])
    assert "cross_scenario_trace_hash" not in causal
    assert "execution_trace_hash" not in execution
    assert details["cross_scenario_trace_hash"] == evidence["cross_scenario_trace_hash"]
    assert details["execution_trace_hash"] == evidence["execution_trace_hash"]
    assert (
        details["cross_scenario_trace_hash"]
        == hashlib.sha256(canonical_json(causal).encode()).hexdigest()
    )
    assert (
        details["execution_trace_hash"]
        == hashlib.sha256(canonical_json(execution).encode()).hexdigest()
    )
    for row in cast(list[dict[str, Any]], details["event_ledger"]):
        assert row["activation"] is True
        assert row["entry_decision_index"] == row["terminal_index"] == 55
        assert row["intended_entry_fill_index"] == 56
        assert row["exit_decision_index"] == 74
        assert row["intended_exit_fill_index"] == 75


def test_semantic_metric_tamper_is_rejected_after_rehashing() -> None:
    report, _result = _synthetic_report(Path.cwd())
    tampered = cast(dict[str, Any], json.loads(json.dumps(report)))
    metrics = cast(dict[str, Any], tampered["metrics"])
    details = cast(dict[str, Any], tampered["details"])
    execution = cast(dict[str, Any], details["execution_trace"])
    execution_metrics = cast(dict[str, Any], execution["metrics"])
    changed = "0" if metrics["event_concentration"] != "0" else "1"
    metrics["event_concentration"] = changed
    execution_metrics["event_concentration"] = changed
    execution_hash = hashlib.sha256(canonical_json(execution).encode()).hexdigest()
    details["execution_trace_hash"] = execution_hash
    cast(dict[str, Any], tampered["execution_evidence"])["execution_trace_hash"] = execution_hash
    unsigned = dict(tampered)
    del unsigned["report_fingerprint"]
    tampered["report_fingerprint"] = fingerprint(unsigned)

    with pytest.raises(ValueError, match="report metrics differ"):
        _validate_run_report_payload(tampered, _EQUIVALENCE_EVENTS)


def test_rehashed_frozen_calendar_event_substitution_is_rejected() -> None:
    report, _result = _synthetic_report(Path.cwd())
    tampered = cast(dict[str, Any], json.loads(json.dumps(report)))
    details = cast(dict[str, Any], tampered["details"])
    cross = cast(dict[str, Any], details["cross_scenario_trace"])
    ledger = cast(list[dict[str, Any]], details["event_ledger"])
    execution = cast(dict[str, Any], details["execution_trace"])
    execution_events = cast(list[dict[str, Any]], execution["events"])
    for row in (cast(list[dict[str, Any]], cross["events"])[0], ledger[0], execution_events[0]):
        row["event_id"] = "not-in-frozen-calendar"
    cross_hash = hashlib.sha256(canonical_json(cross).encode()).hexdigest()
    details["cross_scenario_trace_hash"] = cross_hash
    cast(dict[str, Any], tampered["execution_evidence"])["cross_scenario_trace_hash"] = cross_hash
    execution["cross_scenario_trace_hash"] = cross_hash
    execution_hash = hashlib.sha256(canonical_json(execution).encode()).hexdigest()
    details["execution_trace_hash"] = execution_hash
    cast(dict[str, Any], tampered["execution_evidence"])["execution_trace_hash"] = execution_hash
    unsigned = dict(tampered)
    del unsigned["report_fingerprint"]
    tampered["report_fingerprint"] = fingerprint(unsigned)

    with pytest.raises(ValueError, match="frozen calendar event sequence differs"):
        _validate_run_report_payload(tampered, _EQUIVALENCE_EVENTS)


def test_report_bytes_ignore_ambient_decimal_context() -> None:
    repository = Path.cwd()
    plan = load_intraday_fed_policy_absorption_001_plan(repository)
    model = load_intraday_execution_cost_model(repository)
    specification = _equivalence_specification(
        plan, model, plan.configurations[0], "normal", _SOURCE_COMMIT
    )
    worker = _EquivalenceWorker(repository)
    with localcontext() as context:
        context.prec = 7
        context.rounding = ROUND_DOWN
        low_precision = worker(specification)["report_bytes"]
    with localcontext() as context:
        context.prec = 83
        context.rounding = ROUND_UP
        high_precision = worker(specification)["report_bytes"]

    assert low_precision == high_precision


def test_stage_order_frontiers_and_budget_are_frozen() -> None:
    repository = Path.cwd()
    plan = load_intraday_fed_policy_absorption_001_plan(repository)
    model = load_intraday_execution_cost_model(repository)
    runner = object.__new__(IntradayFedPolicyAbsorption001Runner)
    runner.plan = plan
    runner.cost_model = model
    runner.scenarios = _scenarios(model)
    runner.datasets = runner_module._dataset_bindings(plan.payload)
    runner.source_commit = _SOURCE_COMMIT
    discovery = tuple(
        runner._specification("discovery", configuration, plan.periods[0], scenario)
        for configuration in plan.configurations
        for scenario in ("normal", "zero_cost_diagnostic")
    )

    _validate_stage_specifications(discovery)
    with pytest.raises(ValueError, match="order"):
        _validate_stage_specifications(tuple(reversed(discovery)))
    with pytest.raises(ValueError, match="order"):
        _validate_stage_specifications(discovery[:-1])

    def complete(stage: str, count: int) -> tuple[dict[str, object], ...]:
        return tuple({"stage": stage, "status": "completed"} for _ in range(count))

    rows = complete("discovery", 18) + complete("walk-forward", 24) + complete("stress", 16)
    runner._require_stage_frontier("neighbor", rows)
    with pytest.raises(ValueError, match="barrier"):
        runner._require_stage_frontier("neighbor", rows[:-1])
    with pytest.raises(ValueError, match="regressed"):
        runner._require_stage_frontier("stress", rows + complete("neighbor", 1))
    assert (18, 24, 16, 32, runner_module._MAXIMUM_RUN_SPECIFICATIONS) == (18, 24, 16, 32, 90)


def test_five_fixture_parallel_equivalence_is_byte_exact() -> None:
    result = _parallel_equivalence(Path.cwd(), source_commit=_SOURCE_COMMIT)
    fixtures = cast(list[dict[str, Any]], result["fixtures"])
    assert result["fixture_count"] == 5
    assert all(fixture["canonical_report_equal"] is True for fixture in fixtures)
    by_identity = {
        (fixture["candidate_id"], fixture["scenario_id"]): fixture for fixture in fixtures
    }
    for candidate, left_scenario, right_scenario in (
        ("fedabs-h02-f0008", "normal", "zero_cost_diagnostic"),
        ("fedabs-h04-f0016", "normal", "stress_a"),
    ):
        left = by_identity[(candidate, left_scenario)]
        right = by_identity[(candidate, right_scenario)]
        assert left["cross_scenario_trace_hash"] == right["cross_scenario_trace_hash"]
        assert left["execution_trace_hash"] != right["execution_trace_hash"]


def test_invalid_completed_report_becomes_terminal_in_same_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    store = IntradayFedPolicyAbsorption001Store(runtime)
    specification = {
        "source_commit": _SOURCE_COMMIT,
        "context": {
            "stage": "discovery",
            "base_candidate_id": None,
            "candidate_id": "fedabs-h02-f0008",
            "period_id": "discovery-2025-07-through-10",
            "scenario_id": "normal",
        },
    }
    store.reserve((specification,))
    run_id = runner_module._run_id(specification)
    claim = store.claim(run_id, source_sha=_SOURCE_COMMIT)
    invalid = b"{}\n"
    store.publish(
        claim,
        Path("run-reports") / f"{run_id}.json",
        invalid,
        report_fingerprint=fingerprint({}),
    )
    runner = object.__new__(IntradayFedPolicyAbsorption001Runner)
    runner.runtime_root = runtime
    runner.attempt_store = store
    monkeypatch.setattr(runner, "_load_final_report_if_present", lambda: None)
    monkeypatch.setattr(runner, "_require_no_failures", lambda: None)
    monkeypatch.setattr(runner, "_run_discovery", lambda: runner._load_report(store.get(run_id)))
    monkeypatch.setattr(
        runner,
        "_terminal_interruption_report",
        lambda failed: {"outcome": "terminally-interrupted", "failed": failed},
    )
    monkeypatch.setattr(runner, "_result", lambda final: dict(final))

    result = runner.run()
    row = store.get(run_id)
    report_path = cast(Path, row["canonical_report_path"])
    assert result["outcome"] == "terminally-interrupted"
    assert row["status"] == "failed"
    assert row["failure_class"] == "canonical-report-invalid"
    assert report_path.read_bytes() == invalid
