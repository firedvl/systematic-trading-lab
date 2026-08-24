from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

import systematic_trading_lab.intraday_event_repricing_001_runner as runner_module
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.intraday_event_drift_001_plan import (
    load_intraday_event_drift_001_plan,
)
from systematic_trading_lab.intraday_event_drift_001_runner import _dataset_bindings
from systematic_trading_lab.intraday_event_repricing_001_cli import (
    event_repricing_parser,
)
from systematic_trading_lab.intraday_event_repricing_001_launch_control import (
    REVIEWED_LAUNCH_CONTROL_FINGERPRINT,
    REVIEWED_LAUNCH_CONTROL_SHA256,
)
from systematic_trading_lab.intraday_event_repricing_001_plan import (
    PLAN_FINGERPRINT,
    PLAN_RELATIVE_PATH,
    PLAN_SHA256,
    PROGRAM_ID,
    REVIEW_FINGERPRINT,
    REVIEW_RELATIVE_PATH,
    REVIEW_SHA256,
    load_intraday_event_repricing_001_plan,
)
from systematic_trading_lab.intraday_event_repricing_001_runner import (
    IntradayEventRepricing001Runner,
    IntradayEventRepricing001Store,
    _aggregate_pairs,
    _deduplicate_specifications,
    _pair_reports,
    _parallel_equivalence,
    _require_non_broker_environment,
    _run_id,
    _stress_gates,
    intraday_event_repricing_001_plan_summary,
    intraday_event_repricing_001_status,
)
from systematic_trading_lab.intraday_execution_cost_model import (
    load_intraday_execution_cost_model,
)
from systematic_trading_lab.intraday_exposed_002_runner import _gate_results, _scenarios

_REPOSITORY = Path(__file__).resolve().parents[2]
_SOURCE = "0" * 40


def _runner() -> IntradayEventRepricing001Runner:
    runner = object.__new__(IntradayEventRepricing001Runner)
    runner.repository = _REPOSITORY
    runner.source_commit = _SOURCE
    runner.plan = load_intraday_event_repricing_001_plan(_REPOSITORY)
    runner.base_plan = load_intraday_event_drift_001_plan(_REPOSITORY)
    runner.cost_model = load_intraday_execution_cost_model(_REPOSITORY)
    runner.datasets = _dataset_bindings(runner.base_plan.payload)
    runner.scenarios = _scenarios(runner.cost_model)
    return runner


def test_plan_status_cli_and_bound_launch_control_are_read_only_without_runtime_write(
    tmp_path: Path,
) -> None:
    plan = intraday_event_repricing_001_plan_summary(_REPOSITORY)
    status = intraday_event_repricing_001_status(tmp_path)
    arguments = event_repricing_parser().parse_args(("run", "--workers", "6"))

    assert plan["parent_configuration_count"] == 9
    assert plan["discovery_run_specification_count"] == 36
    assert plan["maximum_run_specifications"] == 244
    assert plan["maximum_attempts"] == 732
    assert plan["status"] == "launch-control-bound"
    assert plan["launch_control_bound"] is True
    assert status["database_exists"] is False
    assert arguments.workers == 6
    assert not any(cast(dict[str, bool], status["authority"]).values())
    assert not (tmp_path / PROGRAM_ID).exists()
    assert REVIEWED_LAUNCH_CONTROL_SHA256 == (
        "11572b8f61d797b2a664866eb88d8b39be2ae07cbb57f9891899725b0a7293c2"
    )
    assert REVIEWED_LAUNCH_CONTROL_FINGERPRINT == (
        "3d35f8d088e11ad6f07d81015c1b037b457e00b824ea908f37cef64a8fbf4a6b"
    )
    loaded = runner_module._load_launch_control(
        _REPOSITORY,
        source_commit="94bc182efe952839d7e3384ea8a148554dd0149d",
    )
    assert loaded["review_fingerprint"] == REVIEWED_LAUNCH_CONTROL_FINGERPRINT


def test_unbound_launch_control_fails_before_runtime_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner_module, "REVIEWED_LAUNCH_CONTROL_SHA256", None)
    monkeypatch.setattr(runner_module, "REVIEWED_LAUNCH_CONTROL_FINGERPRINT", None)

    with pytest.raises(ValueError, match="launch control is not hash-bound"):
        IntradayEventRepricing001Runner(_REPOSITORY, tmp_path)
    assert not (tmp_path / PROGRAM_ID).exists()


def test_broker_environment_fails_before_runtime_or_worker_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = False

    def unexpected_start(*_args: object, **_kwargs: object) -> tuple[object, ...]:
        nonlocal started
        started = True
        return ()

    monkeypatch.setenv("APCA_API_SECRET_KEY", "must-not-reach-research-worker")
    monkeypatch.setattr(runner_module, "run_process_stage", unexpected_start)

    with pytest.raises(ValueError, match="rejects broker credentials") as error:
        IntradayEventRepricing001Runner(_REPOSITORY, tmp_path)

    assert "APCA_API_SECRET_KEY" in str(error.value)
    assert "must-not-reach-research-worker" not in str(error.value)
    assert started is False
    assert not (tmp_path / PROGRAM_ID).exists()
    isolated = _runner()
    specification = isolated._specification(
        isolated.plan.configurations[0],
        isolated.plan.periods[0],
        "leader",
        "normal",
    )
    with pytest.raises(ValueError, match="rejects broker credentials"):
        isolated._execute((specification,))
    assert started is False
    with pytest.raises(ValueError, match="paper-write opt-in"):
        _require_non_broker_environment({"TRADING_LAB_PAPER_ACTIVATION_ID": "value"})


def test_broker_environment_fails_inside_direct_workers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded_plan = False

    def unexpected_plan_load(*_args: object, **_kwargs: object) -> object:
        nonlocal loaded_plan
        loaded_plan = True
        raise AssertionError("worker loaded its plan")

    monkeypatch.setattr(
        runner_module,
        "load_intraday_event_repricing_001_plan",
        unexpected_plan_load,
    )
    monkeypatch.setenv("APCA_API_KEY_ID", "must-not-reach-research-worker")
    worker_factory = runner_module._WorkerFactory(
        _REPOSITORY,
        tmp_path,
        tmp_path / PROGRAM_ID,
        _SOURCE,
    )

    with pytest.raises(ValueError, match="APCA_API_KEY_ID"):
        worker_factory()
    with pytest.raises(ValueError, match="APCA_API_KEY_ID"):
        object.__new__(runner_module._Worker)({})

    monkeypatch.delenv("APCA_API_KEY_ID")
    monkeypatch.setenv("TRADING_LAB_PAPER_CODE_COMMIT", "must-not-reach-research-worker")
    equivalence_factory = runner_module._EquivalenceWorkerFactory(_REPOSITORY)

    with pytest.raises(ValueError, match="TRADING_LAB_PAPER_CODE_COMMIT"):
        equivalence_factory()
    with pytest.raises(ValueError, match="TRADING_LAB_PAPER_CODE_COMMIT"):
        object.__new__(runner_module._EquivalenceWorker)({})

    assert loaded_plan is False
    assert not (tmp_path / PROGRAM_ID).exists()


def test_canonical_budget_is_exact_and_reuses_overlapping_neighbor_evidence(
    tmp_path: Path,
) -> None:
    runner = _runner()
    periods = runner.plan.periods[1:]
    discovery = tuple(
        runner._specification(configuration, runner.plan.periods[0], arm, scenario)
        for configuration in runner.plan.configurations
        for arm in runner_module._ARMS
        for scenario in ("normal", "zero_cost_diagnostic")
    )
    walk_ids = (
        "ier001-a01-b01",
        "ier001-a01-b02",
        "ier001-a02-b03",
        "ier001-a03-b01",
    )
    walk = tuple(
        runner._specification(runner._configuration(candidate), period, arm, scenario)
        for candidate in walk_ids
        for period in periods
        for arm in runner_module._ARMS
        for scenario in ("normal", "zero_cost_diagnostic")
    )
    serious_ids = ("ier001-a02-b03", "ier001-a03-b01")
    stress = tuple(
        runner._specification(runner._configuration(candidate), period, arm, scenario)
        for candidate in serious_ids
        for period in periods
        for arm in runner_module._ARMS
        for scenario in ("stress_a", "stress_b", "normal-delay-2", "normal-delay-3")
    )
    requested_neighbors = tuple(
        runner._specification(runner._configuration(neighbor), period, arm, scenario)
        for candidate in serious_ids
        for neighbor in runner._configuration(candidate).neighbor_ids
        for period in periods
        for arm in runner_module._ARMS
        for scenario in ("normal", "zero_cost_diagnostic")
    )
    specifications = _deduplicate_specifications(discovery + walk + stress + requested_neighbors)

    assert (len(discovery), len(walk), len(stress)) == (36, 64, 64)
    assert len(specifications) == 244
    assert (
        sum(
            _run_id(item) not in {_run_id(value) for value in discovery + walk + stress}
            for item in _deduplicate_specifications(requested_neighbors)
        )
        == 80
    )
    sample = discovery[0]
    changed_fixed_metadata = dict(sample, source_commit="f" * 40)
    assert _run_id(sample) == _run_id(changed_fixed_metadata)
    with pytest.raises(ValueError, match="canonical run context differs"):
        _run_id(
            dict(
                sample,
                context={**cast(dict[str, object], sample["context"]), "stage": "neighbor"},
            )
        )
    with pytest.raises(ValueError, match="canonical run identity collides"):
        _deduplicate_specifications((sample, changed_fixed_metadata))

    store = IntradayEventRepricing001Store(tmp_path)
    store.reserve(specifications)
    assert len(store.list_runs()) == 244
    extra = deepcopy(specifications[0])
    cast(dict[str, object], extra["context"])["candidate_id"] = "ier001-extra"
    with pytest.raises(ValueError, match="budget exceeds 244"):
        store.reserve((extra,))


def _arm_report(arm: str) -> dict[str, Any]:
    symbol = "QQQ" if arm == "leader" else "SPY"
    active = {
        "event_id": "event-1",
        "release_name": "Consumer Price Index",
        "active": True,
        "selected_symbol": symbol,
        "signed_reaction_bps": "20",
        "round_trip_count": 1,
        "fill_count": 2,
        "holding_bars": "24",
        "entry_decision_timestamp": "2026-01-08T14:40:00Z",
        "entry_fill_timestamp": "2026-01-08T14:45:00Z",
        "exit_decision_timestamp": "2026-01-08T16:40:00Z",
        "exit_fill_timestamp": "2026-01-08T16:45:00Z",
        "entry_market_price": "100",
        "exit_market_price": "102" if arm == "leader" else "101",
    }
    inactive = {
        "event_id": "event-2",
        "release_name": "Producer Price Index",
        "active": False,
        "selected_symbol": None,
        "signed_reaction_bps": "0",
        "round_trip_count": 0,
        "fill_count": 0,
        "holding_bars": None,
        "entry_decision_timestamp": None,
        "entry_fill_timestamp": None,
        "exit_decision_timestamp": None,
        "exit_fill_timestamp": None,
        "entry_market_price": None,
        "exit_market_price": None,
    }
    return {
        "run_id": f"run-{arm}",
        "specification": {
            "context": {
                "candidate_id": "ier001-a01-b01",
                "period_id": "period-1",
                "arm_id": arm,
                "scenario_id": "normal",
            }
        },
        "details": {
            "selection_trace_fingerprint": "a" * 64,
            "event_ledger": [active, inactive],
        },
    }


def test_pair_validation_precedes_metrics_and_uses_market_price_continuation() -> None:
    leader = _arm_report("leader")
    control = _arm_report("laggard-control")
    pair = _pair_reports(leader, control)

    assert pair["active_event_count"] == 1
    assert pair["aggregate_relative_continuation_bps"] == Decimal("100")
    assert pair["average_relative_continuation_bps"] == Decimal("100")
    assert pair["positive_relative_event_concentration"] == Decimal("1")
    assert pair["positive_relative_release_class_concentration"] == Decimal("1")
    assert pair["active_direction_counts"] == {"QQQ": 1, "SPY": 0}
    assert pair["active_direction_concentration"] == Decimal("1")

    mutations: tuple[tuple[str, Callable[[dict[str, Any]], None]], ...] = (
        (
            "paired report arms differ",
            lambda value: value["specification"]["context"].update(arm_id="leader"),
        ),
        (
            "paired selection traces differ",
            lambda value: value["details"].update(selection_trace_fingerprint="b" * 64),
        ),
        (
            "paired symbols differ",
            lambda value: value["details"]["event_ledger"][0].update(selected_symbol="QQQ"),
        ),
        (
            "paired timestamps differ",
            lambda value: value["details"]["event_ledger"][0].update(
                entry_fill_timestamp="2026-01-08T14:50:00Z"
            ),
        ),
        (
            "paired trip count differs",
            lambda value: value["details"]["event_ledger"][0].update(round_trip_count=0),
        ),
        (
            "paired trip count differs",
            lambda value: value["details"]["event_ledger"][0].update(holding_bars="23"),
        ),
    )
    for message, mutate in mutations:
        changed = deepcopy(control)
        mutate(changed)
        with pytest.raises((ValueError, ArithmeticError), match=message):
            _pair_reports(leader, changed)


def test_pair_mismatch_freezes_create_only_terminal_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()
    runner.runtime_root = tmp_path / PROGRAM_ID
    runner.attempt_store = IntradayEventRepricing001Store(runner.runtime_root)
    runner.store = runner.attempt_store
    runner.workers = 4
    runner.progress = lambda _message: None
    candidate = runner.plan.configurations[0]
    period = runner.plan.periods[0]
    specifications = tuple(
        runner._specification(candidate, period, arm, "normal") for arm in runner_module._ARMS
    )
    runner.attempt_store.reserve(specifications)
    reports: dict[str, dict[str, Any]] = {}
    for specification, arm in zip(specifications, runner_module._ARMS, strict=True):
        run_id = _run_id(specification)
        claim = runner.attempt_store.claim(run_id, source_sha=_SOURCE)
        runner.attempt_store.publish(
            claim,
            Path("run-reports") / f"{run_id}.json",
            b"{}\n",
            report_fingerprint="0" * 64,
        )
        report = _arm_report(arm)
        report["run_id"] = run_id
        cast(dict[str, object], report["specification"])["context"] = dict(
            cast(dict[str, object], specification["context"])
        )
        reports[arm] = report
    reports["laggard-control"]["details"]["selection_trace_fingerprint"] = "b" * 64

    monkeypatch.setattr(
        runner,
        "_report_for",
        lambda _candidate, _period, arm, _scenario: reports[arm],
    )
    monkeypatch.setattr(
        runner,
        "_run_discovery",
        lambda: runner._scenario_pair(candidate.candidate_id, period.period_id, "normal"),
    )

    result = runner.run()
    report_path = runner.runtime_root / "final-report.json"
    first_bytes = report_path.read_bytes()
    report = cast(dict[str, Any], json.loads(first_bytes))
    failure = cast(dict[str, Any], report["coordinator_failure"])

    assert result["outcome"] == "terminally-interrupted"
    assert failure == {
        "affected_run_ids": sorted(_run_id(value) for value in specifications),
        "cause": "ValueError: Event Repricing 001 paired selection traces differ",
        "classification": "paired-report-validation",
    }
    assert report["terminal_failures"] == []
    assert all(row["status"] == "completed" for row in runner.attempt_store.list_runs())
    assert runner.run()["outcome"] == "terminally-interrupted"
    assert report_path.read_bytes() == first_bytes


def test_pair_aggregation_recomputes_exact_fractions_and_concentrations() -> None:
    pairs = (
        {
            "relative_continuation_by_event": [
                {
                    "event_id": "event-1",
                    "release_name": "Consumer Price Index",
                    "active": True,
                    "leader_symbol": "QQQ",
                    "relative_continuation_bps": Decimal("10"),
                },
                {
                    "event_id": "event-2",
                    "release_name": "Producer Price Index",
                    "active": True,
                    "leader_symbol": "SPY",
                    "relative_continuation_bps": Decimal("-5"),
                },
            ],
            "selection_trace_mismatch_count": 0,
            "paired_fill_mismatch_count": 0,
        },
        {
            "relative_continuation_by_event": [
                {
                    "event_id": "event-3",
                    "release_name": "Consumer Price Index",
                    "active": True,
                    "leader_symbol": "QQQ",
                    "relative_continuation_bps": Decimal("20"),
                }
            ],
            "selection_trace_mismatch_count": 0,
            "paired_fill_mismatch_count": 0,
        },
    )
    aggregate = _aggregate_pairs(pairs)

    assert aggregate["aggregate_relative_continuation_bps"] == Decimal("25")
    assert aggregate["average_relative_continuation_bps"] == Decimal("25") / Decimal("3")
    assert aggregate["positive_relative_event_concentration"] == Decimal("2") / Decimal("3")
    assert aggregate["positive_relative_release_class_concentration"] == Decimal("1")
    assert aggregate["active_direction_concentration"] == Decimal("2") / Decimal("3")


def test_stress_and_neighbor_gates_fail_undefined_and_do_not_round_fractions() -> None:
    plan = load_intraday_event_repricing_001_plan(_REPOSITORY)
    screen = cast(dict[str, Any], plan.payload["serious_candidate_screen"])
    scenarios = cast(tuple[str, ...], tuple(screen["stress_scenarios"]))
    gates = _stress_gates(screen, scenarios)
    values: dict[str, Decimal | int | None] = {}
    for scenario in scenarios:
        values.update(
            {
                f"{scenario}.leader.aggregate.total_return": Decimal("0.01"),
                f"{scenario}.aggregate_relative_continuation_bps": Decimal("1"),
                f"{scenario}.joint_positive_fold_count": 3,
                f"{scenario}.leader_normal_profit_retention": Decimal("1"),
                f"{scenario}.normal_relative_continuation_retention": Decimal("1"),
            }
        )
    assert len(gates) == 20
    assert all(item["passed"] is True for item in _gate_results(gates, values))
    values["stress_a.leader_normal_profit_retention"] = None
    assert any(item["passed"] is False for item in _gate_results(gates, values))

    neighbor_gates = cast(list[dict[str, Any]], screen["neighbor_gates"])
    failing = {
        "positive_relative_neighbor_fraction": Decimal(2) / Decimal(3),
        "median_neighbor_leader_normal_profit_retention": Decimal("0.60"),
        "median_neighbor_relative_continuation_retention": Decimal("0.60"),
    }
    passing = dict(failing, positive_relative_neighbor_fraction=Decimal(3) / Decimal(4))
    assert _gate_results(neighbor_gates, failing)[0]["passed"] is False
    assert all(item["passed"] is True for item in _gate_results(neighbor_gates, passing))


def test_synthetic_one_worker_and_four_worker_pairs_are_byte_identical() -> None:
    result = _parallel_equivalence(_REPOSITORY, source_commit=_SOURCE)

    assert result["equivalent"] is True
    assert result["worker_counts"] == [1, 4]
    assert result["fixture_count"] == 4
    assert result["protected_inputs_accessed"] is False
    for fixture in cast(list[dict[str, object]], result["fixtures"]):
        assert fixture["leader_run_id"] != fixture["laggard_control_run_id"]
        assert fixture["specifications_equal"] is True
        assert fixture["arm_reports_equal"] is True
        assert fixture["paired_event_ledger_equal"] is True
        assert fixture["canonical_reports_equal"] is True


def _launch_review(repository: Path, equivalence: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": runner_module._LAUNCH_CONTROL_SCHEMA,
        "review_id": runner_module._LAUNCH_CONTROL_SCHEMA,
        "status": "passed",
        "verdict": "pass",
        "review_date": "2026-08-23",
        "review_method": "Independent synthetic and source review.",
        "reviewed_inputs": {
            "plan": {
                "path": PLAN_RELATIVE_PATH.as_posix(),
                "sha256": PLAN_SHA256,
                "fingerprint": PLAN_FINGERPRINT,
            },
            "plan_review": {
                "path": REVIEW_RELATIVE_PATH.as_posix(),
                "sha256": REVIEW_SHA256,
                "fingerprint": REVIEW_FINGERPRINT,
            },
            "base_plan": {
                "path": "config/research/intraday-event-drift-001-plan-v1.json",
                "sha256": "c0dade2573405ddcd38d88814c10a27c3caae11bfb925a21179f6741cc20233c",
                "fingerprint": "73933d470feb52c1135746ab57db742019077b8b39e8e2545e9aba37c9a8d838",
            },
            "base_plan_review": {
                "path": "config/research/intraday-event-drift-001-plan-independent-review-v1.json",
                "sha256": "25e92a85cee47aa261b4a85dce57666effbfbe329c203d3ac78df7b5bba9df96",
                "fingerprint": "0a464aca264ad4a8583d12fc4912898461ecf9e6121a1119322229e12bfb4077",
            },
            "calendar": {
                "path": "config/research/intraday-event-calendar-001-v1.json",
                "sha256": "fa413a30234c6b82394fcdbf99df94aa31ae38e2df12d58296bcbc03162a34ee",
                "fingerprint": "9992ee0a430abc0b59f49f6dd9e5178ff22d13a9dec5ad5de1d8578896ed2a78",
            },
            "source_evidence": {
                "path": "config/research/intraday-event-calendar-001-source-evidence-v1.json",
                "sha256": "c5f1ab34c92b10ac9c75d86a3c33c9f2a445eed022a48697edaa7dfd9eabee0a",
                "fingerprint": "6616ed631b3d7e8e727b8cde85bf26e4c2cb5800812db745c327a71bf62192fd",
            },
        },
        "implementation": {
            "source_commit": _SOURCE,
            "files": [
                {
                    "path": path,
                    "sha256": hashlib.sha256((repository / path).read_bytes()).hexdigest(),
                }
                for path in runner_module._LAUNCH_CONTROL_FILES
            ],
        },
        "quality_gates": {
            "source_commit": _SOURCE,
            "results": [
                {"command": command, "status": "passed", "exit_code": 0, "summary": "passed"}
                for command in runner_module._LAUNCH_CONTROL_QUALITY_GATES
            ],
        },
        "equivalence": equivalence,
        "independent_review": {
            "source_commit": _SOURCE,
            "status": "passed",
            "verdict": "pass",
            "findings": [],
            "reviewer": "independent-launch-reviewer",
        },
        "scope_limit": "Synthetic fixtures only; protected and broker state excluded.",
        "authority": dict(runner_module._AUTHORITY),
    }


def test_launch_control_requires_exact_hashes_and_finding_free_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for relative in runner_module._LAUNCH_CONTROL_FILES:
        source = _REPOSITORY / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    equivalence = _parallel_equivalence(_REPOSITORY, source_commit=_SOURCE)
    review = _launch_review(tmp_path, equivalence)
    unsigned = deepcopy(review)
    review["review_fingerprint"] = fingerprint(unsigned)
    raw = (json.dumps(review, indent=2) + "\n").encode()
    path = tmp_path / runner_module.LAUNCH_CONTROL_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    monkeypatch.setattr(
        runner_module, "REVIEWED_LAUNCH_CONTROL_SHA256", hashlib.sha256(raw).hexdigest()
    )
    monkeypatch.setattr(
        runner_module,
        "REVIEWED_LAUNCH_CONTROL_FINGERPRINT",
        review["review_fingerprint"],
    )

    loaded = runner_module._load_launch_control(tmp_path, source_commit=_SOURCE)
    assert loaded["verdict"] == "pass"

    cast(dict[str, Any], review["independent_review"])["findings"] = ["finding"]
    unsigned = deepcopy(review)
    unsigned.pop("review_fingerprint")
    review["review_fingerprint"] = fingerprint(unsigned)
    raw = (json.dumps(review, indent=2) + "\n").encode()
    path.write_bytes(raw)
    monkeypatch.setattr(
        runner_module, "REVIEWED_LAUNCH_CONTROL_SHA256", hashlib.sha256(raw).hexdigest()
    )
    monkeypatch.setattr(
        runner_module,
        "REVIEWED_LAUNCH_CONTROL_FINGERPRINT",
        review["review_fingerprint"],
    )
    with pytest.raises(ValueError, match="independent review differs"):
        runner_module._load_launch_control(tmp_path, source_commit=_SOURCE)
