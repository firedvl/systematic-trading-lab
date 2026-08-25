from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_UP, localcontext
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any, cast

import pytest

import systematic_trading_lab.intraday_fed_policy_absorption_001_runner as runner_module
from systematic_trading_lab.fingerprints import canonical_json, fingerprint
from systematic_trading_lab.intraday_execution_cost_model import (
    load_intraday_execution_cost_model,
)
from systematic_trading_lab.intraday_exposed_002_runner import (
    IntradayExposed002Runner,
    _scenarios,
)
from systematic_trading_lab.intraday_fed_policy_absorption_001_launch_control import (
    REVIEWED_LAUNCH_CONTROL_FINGERPRINT,
    REVIEWED_LAUNCH_CONTROL_SHA256,
)
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
    _Worker,
    decode_canonical_metric,
    intraday_fed_policy_absorption_001_plan_summary,
)
from systematic_trading_lab.research_executor import ResearchProcessError, run_process_stage

_SOURCE_COMMIT = "a" * 40


@dataclass(frozen=True)
class _RejectingWorkerFactory:
    repository: Path
    data_home: Path
    runtime_root: Path
    source_commit: str
    stage_specifications: tuple[object, ...]
    attestation_root: Path
    attestation_workers: int

    def __call__(self) -> Any:
        raise ValueError("worker source commit differs")


@dataclass(frozen=True)
class _AttestedReplacementWorkerFactory:
    root: Path

    def __call__(self) -> _AttestedReplacementWorker:
        return _AttestedReplacementWorker(self.root)


class _AttestedReplacementWorker:
    def __init__(self, root: Path) -> None:
        self.root = root
        runner_module._await_worker_attestations(
            root,
            source_commit=_SOURCE_COMMIT,
            workers=1,
        )

    def __call__(self, task: str) -> str:
        if task == "fail":
            raise RuntimeError("forced worker retirement")
        (self.root / f"completed-{task}").write_text(str(os.getpid()), encoding="ascii")
        return task


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


def test_unbound_repair_fails_before_runtime_creation(tmp_path: Path) -> None:
    repository = Path.cwd()
    runtime = tmp_path / "runtime"
    assert REVIEWED_LAUNCH_CONTROL_SHA256 is None
    assert REVIEWED_LAUNCH_CONTROL_FINGERPRINT is None
    assert (
        intraday_fed_policy_absorption_001_plan_summary(repository)["launch_control_bound"] is False
    )
    with pytest.raises(ValueError, match="launch control"):
        IntradayFedPolicyAbsorption001Runner(repository, runtime)
    assert not runtime.exists()


def test_dataset_validation_thaws_frozen_plan_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = object.__new__(IntradayFedPolicyAbsorption001Runner)
    runner.plan = load_intraday_fed_policy_absorption_001_plan(Path.cwd())

    def verify(_self: object, payload: object | None = None) -> None:
        assert isinstance(payload, dict)
        assert isinstance(payload.get("data"), dict)

    monkeypatch.setattr(IntradayExposed002Runner, "_verify_datasets", verify)

    runner._verify_datasets()


def test_broker_environment_fails_before_runtime_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = Path.cwd()
    runtime = tmp_path / "runtime"
    monkeypatch.setenv("APCA_API_KEY_ID", "not-a-secret-test-value")
    with pytest.raises(ValueError, match="broker environment"):
        IntradayFedPolicyAbsorption001Runner(repository, runtime)
    assert not runtime.exists()


def test_worker_rejects_source_drift_before_data_access_or_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = "a" * 40
    observed = "b" * 40
    monkeypatch.setattr(runner_module, "_source_commit", lambda _repository: observed)
    monkeypatch.setattr(
        runner_module,
        "load_intraday_fed_policy_absorption_001_plan",
        lambda _repository: pytest.fail("worker read the plan before checking source"),
    )

    with pytest.raises(ValueError, match="worker source commit differs"):
        _Worker(
            Path.cwd(),
            tmp_path / "data",
            tmp_path / "runtime",
            expected,
            (),
            tmp_path / "attestation",
            1,
        )
    assert not (tmp_path / "runtime").exists()

    worker = object.__new__(_Worker)
    worker.source_commit = expected
    worker.attempt_store = cast(Any, pytest.fail)
    with pytest.raises(ValueError, match="worker specification source differs"):
        worker({"source_commit": observed})


def test_worker_initialization_failure_precedes_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reserve_calls = 0

    class Store:
        @staticmethod
        def list_runs() -> tuple[object, ...]:
            return ()

        @staticmethod
        def get(_run_id: str) -> object:
            return pytest.fail("run state read before reservation")

        @staticmethod
        def reserve(_specifications: object) -> None:
            nonlocal reserve_calls
            reserve_calls += 1

    runtime = tmp_path / "runtime"
    runner = object.__new__(IntradayFedPolicyAbsorption001Runner)
    runner.repository = Path.cwd()
    runner.data_home = tmp_path / "data"
    runner.runtime_root = runtime
    runner.source_commit = _SOURCE_COMMIT
    runner.attempt_store = cast(Any, Store())
    runner.workers = 4
    runner.progress = lambda _message: None
    specification = {
        "source_commit": _SOURCE_COMMIT,
        "context": {
            "stage": "discovery",
            "candidate_id": "fedabs-h02-f0008",
            "period_id": "discovery-2025-07-through-10",
            "scenario_id": "normal",
        },
    }
    monkeypatch.setattr(runner_module, "_WorkerFactory", _RejectingWorkerFactory)
    monkeypatch.setattr(runner_module, "_validate_stage_specifications", lambda _values: None)

    with pytest.raises(ResearchProcessError, match="worker source commit differs"):
        runner._execute((specification,))

    assert reserve_calls == 0
    assert not runtime.exists()


def test_worker_attestation_rejects_peer_failure(tmp_path: Path) -> None:
    (tmp_path / "failed-peer").touch()

    with pytest.raises(ValueError, match="worker attestation peer failed"):
        runner_module._await_worker_attestations(
            tmp_path,
            source_commit=_SOURCE_COMMIT,
            workers=1,
        )


def test_worker_attestation_rejects_mixed_sources(tmp_path: Path) -> None:
    (tmp_path / "ready-peer").write_text("b" * 40, encoding="ascii")

    with pytest.raises(ValueError, match="worker attestation source differs"):
        runner_module._await_worker_attestations(
            tmp_path,
            source_commit=_SOURCE_COMMIT,
            workers=2,
        )


def test_worker_attestation_publishes_complete_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_link = os.link

    def link(
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
    ) -> None:
        assert Path(source).read_text(encoding="ascii") == _SOURCE_COMMIT
        assert not tuple(tmp_path.glob("ready-*"))
        original_link(source, destination)

    monkeypatch.setattr(os, "link", link)

    runner_module._await_worker_attestations(
        tmp_path,
        source_commit=_SOURCE_COMMIT,
        workers=1,
    )

    ready = tuple(tmp_path.glob("ready-*"))
    assert len(ready) == 1
    assert ready[0].read_text(encoding="ascii") == _SOURCE_COMMIT


def test_worker_dataset_validation_and_attestation_precede_stage_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attestation_root = tmp_path / "attestations"
    attestation_root.mkdir()
    (attestation_root / "ready-peer").write_text(_SOURCE_COMMIT, encoding="ascii")
    specification = {"source_commit": _SOURCE_COMMIT}
    reserve_calls = 0

    class Store:
        def __init__(self, _runtime_root: Path) -> None:
            ready = tuple(attestation_root.glob("ready-*"))
            assert len(ready) == 2
            assert {item.read_text(encoding="ascii") for item in ready} == {_SOURCE_COMMIT}

        @staticmethod
        def reserve(_specifications: object) -> None:
            nonlocal reserve_calls
            reserve_calls += 1

    monkeypatch.setattr(runner_module, "_source_commit", lambda _repository: _SOURCE_COMMIT)
    monkeypatch.setattr(
        runner_module,
        "load_intraday_fed_policy_absorption_001_plan",
        lambda _repository: SimpleNamespace(
            payload=MappingProxyType({"data": MappingProxyType({})})
        ),
    )
    monkeypatch.setattr(
        runner_module,
        "load_intraday_execution_cost_model",
        lambda _repository: object(),
    )
    monkeypatch.setattr(runner_module, "_dataset_bindings", lambda _payload: ())
    monkeypatch.setattr(runner_module, "_read_only_dataset_services", lambda *_args: {})

    def verify(_self: object, payload: object | None = None) -> None:
        assert isinstance(payload, dict)
        assert isinstance(payload.get("data"), dict)

    monkeypatch.setattr(IntradayExposed002Runner, "_verify_datasets", verify)
    monkeypatch.setattr(runner_module, "_scenarios", lambda _model: {})
    monkeypatch.setattr(runner_module, "IntradayFedPolicyAbsorption001Store", Store)

    _Worker(
        Path.cwd(),
        tmp_path / "data",
        tmp_path / "runtime",
        _SOURCE_COMMIT,
        (specification,),
        attestation_root,
        2,
    )

    assert reserve_calls == 1


def test_worker_replacement_reuses_completed_attestation_barrier(tmp_path: Path) -> None:
    with pytest.raises(ResearchProcessError, match="forced worker retirement"):
        run_process_stage(
            ("fail", "unaffected"),
            worker_factory=_AttestedReplacementWorkerFactory(tmp_path),
            workers=1,
        )

    completion_pid = (tmp_path / "completed-unaffected").read_text(encoding="ascii")
    ready = tuple(tmp_path.glob("ready-*"))
    assert len(ready) == 1
    assert ready[0].name != f"ready-{completion_pid}"


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
