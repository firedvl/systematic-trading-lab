from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

import systematic_trading_lab.intraday_exposed_003_runner as runner_module
from systematic_trading_lab.datasets import DatasetService
from systematic_trading_lab.fingerprints import canonical_json, canonicalize, fingerprint
from systematic_trading_lab.intraday_execution_cost_model import (
    load_intraday_execution_cost_model,
)
from systematic_trading_lab.intraday_exposed_002_plan import Exposed002Period
from systematic_trading_lab.intraday_exposed_002_runner import (
    _EvaluationBoundStrategy,
    _scenarios,
)
from systematic_trading_lab.intraday_exposed_003_plan import (
    PROGRAM_ID,
    load_intraday_exposed_003_plan,
)
from systematic_trading_lab.intraday_exposed_003_runner import (
    FINAL_REPORT_SCHEMA,
    RUN_REPORT_SCHEMA,
    IntradayExposed003Runner,
    IntradayExposed003Store,
    _effective_plan,
    _reservation_id,
    _run_id,
    intraday_exposed_003_plan_summary,
    intraday_exposed_003_status,
)
from systematic_trading_lab.public_cli import research_parser
from systematic_trading_lab.research_attempts import AttemptStateError

_REPOSITORY = Path(__file__).resolve().parents[2]
_SOURCE_SHA = "a" * 40


def _runner(tmp_path: Path) -> IntradayExposed003Runner:
    runner = IntradayExposed003Runner.__new__(IntradayExposed003Runner)
    runner.repository = _REPOSITORY
    runner.data_home = tmp_path
    runner.source_commit = _SOURCE_SHA
    runner.progress = lambda _message: None
    runner.control_plan = load_intraday_exposed_003_plan(_REPOSITORY)
    runner.plan = _effective_plan(runner.control_plan)
    runner.cost_model = load_intraday_execution_cost_model(_REPOSITORY)
    runner.datasets = ()
    runner.data_by_dataset = {}
    runner.runtime_root = tmp_path / PROGRAM_ID
    runner.attempt_store = IntradayExposed003Store(runner.runtime_root)
    runner.store = cast(Any, runner.attempt_store)
    runner.scenarios = _scenarios(runner.cost_model)
    runner._bar_cache = {}
    runner.attempt_store.bind(runner._program_binding())
    return runner


def _discovery_specification(runner: IntradayExposed003Runner) -> dict[str, object]:
    return runner._specification(
        "discovery",
        runner.plan.configurations[0],
        runner.plan.periods[0],
        "normal",
    )


def _report(
    specification: Mapping[str, object], _result: object, _period: Exposed002Period
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": RUN_REPORT_SCHEMA,
        "program_id": PROGRAM_ID,
        "run_id": _run_id(specification),
        "specification": canonicalize(specification),
        "specification_fingerprint": fingerprint(specification),
        "authority": runner_module._AUTHORITY,
    }
    payload["report_fingerprint"] = fingerprint(payload)
    return payload


def test_plan_status_and_parser_grant_no_authority(tmp_path: Path) -> None:
    plan = intraday_exposed_003_plan_summary(_REPOSITORY)
    status = intraday_exposed_003_status(tmp_path)
    arguments = research_parser().parse_args(("intraday-exposed-003", "plan"))

    assert plan["program_id"] == PROGRAM_ID
    assert plan["parent_configuration_count"] == 60
    assert plan["discovery_run_count"] == 120
    assert plan["june_status"] == "ineligible-no-read-no-substitute"
    assert not any(cast(Mapping[str, bool], plan["authority"]).values())
    assert status["database_exists"] is False
    assert not any(cast(Mapping[str, bool], status["authority"]).values())
    assert not (tmp_path / PROGRAM_ID).exists()
    assert arguments.research_command == "intraday-exposed-003"
    assert arguments.action == "plan"


def test_runner_enforces_source_gate_before_data_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    accessed = False

    class _DataService:
        def describe(self, dataset_id: str) -> dict[str, object]:
            nonlocal accessed
            accessed = True
            raise AssertionError(dataset_id)

    def reject_source(_repository: Path) -> str:
        raise ValueError("source gate")

    monkeypatch.setattr(runner_module, "_source_commit", reject_source)

    with pytest.raises(ValueError, match="source gate"):
        IntradayExposed003Runner(
            _REPOSITORY,
            tmp_path,
            data_service=cast(DatasetService, _DataService()),
        )
    assert accessed is False


def test_missing_catalog_creates_no_runtime_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner_module, "_source_commit", lambda _repository: _SOURCE_SHA)

    with pytest.raises(ValueError, match="dataset catalog is missing"):
        IntradayExposed003Runner(_REPOSITORY, tmp_path)

    assert not (tmp_path / PROGRAM_ID).exists()


def test_successful_run_keeps_003_evidence_and_002_strategy_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path)
    specification = _discovery_specification(runner)
    seen: dict[str, object] = {}

    class _Engine:
        def __init__(self, *_args: object) -> None:
            pass

        def run(self, bars: object, strategy: object) -> object:
            seen["bars"] = bars
            seen["strategy"] = strategy
            return object()

    monkeypatch.setattr(runner_module, "IntradayExposed002Engine", _Engine)
    monkeypatch.setattr(runner_module, "_run_report", _report)
    monkeypatch.setattr(runner, "_bars", lambda _period: ())

    runner._execute((specification,))

    run_id = _run_id(specification)
    row = runner.attempt_store.get(run_id)
    report = runner._load_report(row)
    wrapped = cast(_EvaluationBoundStrategy, seen["strategy"])
    configuration = cast(Mapping[str, object], specification["configuration"])
    assert run_id == f"ie003r-{fingerprint(specification)[:24]}"
    assert row["reservation_id"] == _reservation_id(fingerprint(specification))
    assert row["status"] == "completed"
    assert row["attempt_count"] == 1
    assert report["program_id"] == PROGRAM_ID
    assert str(configuration["candidate_id"]).startswith("ie003-")
    assert str(configuration["source_candidate_id"]).startswith("ie002-")
    assert wrapped.inner.strategy_id == configuration["source_candidate_id"]
    assert wrapped.evaluation_start == runner.plan.periods[0].evaluation_start
    attempts = runner.attempt_store.list_attempts(run_id)
    assert len(attempts) == 1
    assert attempts[0]["run_fingerprint"] == fingerprint(specification)
    assert cast(list[Mapping[str, object]], attempts[0]["events"])[-1]["kind"] == "completed"

    discovery = {"stage": "discovery", "parent_count": 1, "paired_run_count": 1}
    walk_forward = {"stage": "walk-forward", "candidate_count": 0, "paired_run_count": 0}
    serious = {
        "stage": "serious-candidate",
        "candidate_count": 0,
        "stress_run_count": 0,
        "neighbor_run_count": 0,
    }
    freeze = runner._freeze(discovery, walk_forward, serious, ())
    summary = cast(Mapping[str, object], freeze["attempt_summary"])
    histories = cast(list[Mapping[str, object]], freeze["attempt_histories"])
    assert summary["total_attempts"] == 1
    assert histories[0]["run_id"] == run_id
    assert len(cast(tuple[object, ...], histories[0]["attempts"])) == 1
    runner._final_report(discovery, walk_forward, serious, (), freeze)
    assert _runner(tmp_path).run()["outcome"] == "no-controlled-qualified-candidate"
    freeze_path = runner.runtime_root / "final-freeze.json"
    freeze_path.write_bytes(freeze_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="final freeze differs"):
        intraday_exposed_003_status(tmp_path)


@pytest.mark.parametrize("failure_class", ("candidate", "data"))
def test_deterministic_run_failure_is_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_class: str,
) -> None:
    runner = _runner(tmp_path)
    specification = _discovery_specification(runner)

    class _FailingEngine:
        def __init__(self, *_args: object) -> None:
            pass

        def run(self, _bars: object, _strategy: object) -> object:
            raise ValueError("deterministic candidate failure")

    monkeypatch.setattr(runner_module, "IntradayExposed002Engine", _FailingEngine)
    if failure_class == "data":

        def fail_bars(_period: Exposed002Period) -> tuple[()]:
            raise ValueError("deterministic data failure")

        monkeypatch.setattr(runner, "_bars", fail_bars)
    else:
        monkeypatch.setattr(runner, "_bars", lambda _period: ())

    with pytest.raises(ValueError, match=f"deterministic {failure_class} failure"):
        runner._execute((specification,))

    run_id = _run_id(specification)
    row = runner.attempt_store.get(run_id)
    assert row["status"] == "failed"
    assert row["failure_class"] == failure_class
    assert row["attempt_count"] == 1
    with pytest.raises(AttemptStateError, match="terminal"):
        runner.attempt_store.claim(run_id, source_sha=_SOURCE_SHA)


def test_attempt_infrastructure_error_waits_for_lease_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path)
    specification = _discovery_specification(runner)

    @contextmanager
    def interrupted_capture(_claim: object) -> Iterator[None]:
        raise OSError("attempt output unavailable")
        yield

    monkeypatch.setattr(runner.attempt_store, "capture_output", interrupted_capture)

    with pytest.raises(OSError, match="output unavailable"):
        runner._execute((specification,))

    run_id = _run_id(specification)
    row = runner.attempt_store.get(run_id)
    assert row["status"] == "running"
    assert row["failure_class"] is None
    assert runner.attempt_store.attempts.expire_stale(
        datetime.now(UTC) + timedelta(seconds=301)
    ) == (run_id,)
    assert runner.attempt_store.get(run_id)["status"] == "pending"


def test_journaled_report_recovers_after_materialization_interruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / PROGRAM_ID
    store = IntradayExposed003Store(root)
    store.bind({"program_id": PROGRAM_ID, "source_commit": _SOURCE_SHA})
    specification = {
        "schema_version": "test-run-v1",
        "program_id": PROGRAM_ID,
        "source_commit": _SOURCE_SHA,
        "context": {
            "stage": "discovery",
            "base_candidate_id": None,
            "candidate_id": "ie003-f01-a01-b01",
            "family_id": "gap-down-failed-continuation-fade-v1",
            "period_id": "discovery-2025-07-through-10",
            "scenario_id": "normal",
        },
    }
    store.reserve((specification,))
    run_id = _run_id(specification)
    claim = store.claim(run_id, source_sha=_SOURCE_SHA)
    report = (canonical_json({"result": "complete"}) + "\n").encode()
    report_fingerprint = fingerprint({"result": "complete"})

    def interrupt_materialization(_relative: Path, _report: bytes) -> None:
        raise OSError("simulated interruption after journal commit")

    monkeypatch.setattr(store.attempts, "_materialize", interrupt_materialization)
    with pytest.raises(OSError, match="after journal commit"):
        store.publish(
            claim,
            Path("run-reports") / f"{run_id}.json",
            report,
            report_fingerprint=report_fingerprint,
        )

    report_path = root / "run-reports" / f"{run_id}.json"
    assert store.get(run_id)["status"] == "completed"
    assert not report_path.exists()

    restarted = IntradayExposed003Store(root)
    assert restarted.reconcile_reports() == (report_path,)
    assert report_path.read_bytes() == report
    assert restarted.get(run_id)["status"] == "completed"


def test_restart_publication_conflict_publishes_terminal_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path)
    specification = _discovery_specification(runner)
    runner.attempt_store.reserve((specification,))
    run_id = _run_id(specification)
    claim = runner.attempt_store.claim(run_id, source_sha=_SOURCE_SHA)
    report = (canonical_json({"result": "complete"}) + "\n").encode()
    report_fingerprint = fingerprint({"result": "complete"})

    def interrupt_materialization(_relative: Path, _report: bytes) -> None:
        raise OSError("simulated interruption after journal commit")

    monkeypatch.setattr(runner.attempt_store.attempts, "_materialize", interrupt_materialization)
    with pytest.raises(OSError, match="after journal commit"):
        runner.attempt_store.publish(
            claim,
            Path("run-reports") / f"{run_id}.json",
            report,
            report_fingerprint=report_fingerprint,
        )

    report_path = runner.runtime_root / "run-reports" / f"{run_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(b"conflicting bytes")
    restarted = _runner(tmp_path)

    result = restarted.run()

    row = restarted.attempt_store.get(run_id)
    assert result["outcome"] == "terminally-interrupted"
    assert row["status"] == "failed"
    assert row["failure_class"] == "publication-conflict"
    final = cast(
        Mapping[str, object],
        json.loads((restarted.runtime_root / "final-report.json").read_bytes()),
    )
    assert (
        cast(list[Mapping[str, object]], final["terminal_failures"])[0]["failure_class"]
        == "publication-conflict"
    )


def test_active_unexpired_lease_does_not_publish_terminal_report(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    specification = _discovery_specification(runner)
    runner.attempt_store.reserve((specification,))
    runner.attempt_store.claim(_run_id(specification), source_sha=_SOURCE_SHA)

    with pytest.raises(AttemptStateError, match="active attempt"):
        runner.run()

    assert not (runner.runtime_root / "final-report.json").exists()


def test_terminal_failure_publishes_attempt_aware_report(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    specification = _discovery_specification(runner)
    runner.attempt_store.reserve((specification,))
    run_id = _run_id(specification)
    claim = runner.attempt_store.claim(run_id, source_sha=_SOURCE_SHA)
    runner.attempt_store.fail(
        claim,
        failure_class="candidate",
        reason="ValueError: deterministic candidate failure",
    )

    result = runner.run()
    report = cast(
        Mapping[str, object],
        json.loads((runner.runtime_root / "final-report.json").read_bytes()),
    )
    assert result["outcome"] == "terminally-interrupted"
    assert report["schema_version"] == FINAL_REPORT_SCHEMA
    assert report["program_id"] == PROGRAM_ID
    assert cast(Mapping[str, object], report["attempt_summary"])["total_attempts"] == 1
    assert cast(list[Mapping[str, object]], report["terminal_failures"])[0]["run_id"] == run_id
    assert cast(list[Mapping[str, object]], report["attempt_histories"])[0]["run_id"] == run_id
    assert report["final_freeze"] is None

    markdown = runner.runtime_root / "final-report.md"
    markdown.unlink()
    assert _runner(tmp_path).run() == result
    assert markdown.is_file()
    with sqlite3.connect(runner.attempt_store.path) as connection:
        connection.execute("PRAGMA user_version = 1")
    with pytest.raises(ValueError, match="runtime database differs"):
        intraday_exposed_003_status(tmp_path)


def test_third_stale_attempt_is_terminal_through_003_store(tmp_path: Path) -> None:
    store = IntradayExposed003Store(tmp_path / PROGRAM_ID)
    store.bind({"program_id": PROGRAM_ID, "source_commit": _SOURCE_SHA})
    specification = {
        "schema_version": "test-run-v1",
        "program_id": PROGRAM_ID,
        "source_commit": _SOURCE_SHA,
        "context": {
            "stage": "discovery",
            "base_candidate_id": None,
            "candidate_id": "ie003-f01-a01-b01",
            "family_id": "gap-down-failed-continuation-fade-v1",
            "period_id": "discovery-2025-07-through-10",
            "scenario_id": "normal",
        },
    }
    store.reserve((specification,))
    run_id = _run_id(specification)
    started = datetime.now(UTC) - timedelta(minutes=20)
    for attempt_number in range(1, 4):
        claim = store.attempts.claim(run_id, source_sha=_SOURCE_SHA, started_at=started)
        assert claim.attempt_number == attempt_number
        store.attempts.expire_stale(started + timedelta(seconds=300))
        started += timedelta(seconds=301)

    row = store.get(run_id)
    assert row["status"] == "failed"
    assert row["failure_class"] == "infrastructure"
    assert row["attempt_count"] == 3
