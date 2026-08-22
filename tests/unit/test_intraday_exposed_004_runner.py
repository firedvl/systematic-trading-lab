from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest

import systematic_trading_lab.intraday_exposed_004_runner as runner_module
from systematic_trading_lab.fingerprints import canonical_json, canonicalize, fingerprint
from systematic_trading_lab.intraday_execution_cost_model import (
    load_intraday_execution_cost_model,
)
from systematic_trading_lab.intraday_exposed_002_plan import Exposed002Period
from systematic_trading_lab.intraday_exposed_002_runner import (
    IntradayExposed002Runner,
    _scenarios,
)
from systematic_trading_lab.intraday_exposed_004_launch_control import (
    REVIEWED_LAUNCH_CONTROL_FINGERPRINT,
)
from systematic_trading_lab.intraday_exposed_004_plan import (
    PROGRAM_ID,
    REVIEWED_PLAN_FINGERPRINT,
    REVIEWED_PLAN_SHA256,
    load_intraday_exposed_004_plan,
)
from systematic_trading_lab.intraday_exposed_004_runner import (
    DATABASE_NAME,
    RUN_REPORT_SCHEMA,
    IntradayExposed004Runner,
    IntradayExposed004Store,
    _effective_plan,
    _load_launch_control,
    _run_id,
    _verify_launch_source_lineage,
    _Worker,
    intraday_exposed_004_plan_summary,
    intraday_exposed_004_status,
)
from systematic_trading_lab.public_cli import research_parser
from systematic_trading_lab.research_attempts import (
    AttemptStateError,
    PublicationConflictError,
)

_REPOSITORY = Path(__file__).resolve().parents[2]
_SOURCE_SHA = "a" * 40


def _launch_control_repository(root: Path) -> Path:
    for relative in runner_module._LAUNCH_CONTROL_FILES:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((_REPOSITORY / relative).read_bytes())
    return root


def _launch_control(repository: Path) -> dict[str, object]:
    fixture_hash = "b" * 64
    return {
        "schema_version": runner_module._LAUNCH_CONTROL_SCHEMA,
        "review_id": runner_module._LAUNCH_CONTROL_SCHEMA,
        "status": "passed",
        "verdict": "pass",
        "review_date": "2026-08-22",
        "review_method": "Independent source, gate, equivalence, and disposition review.",
        "reviewed_plan": {
            "path": "config/research/intraday-exposed-004-plan-v1.json",
            "sha256": REVIEWED_PLAN_SHA256,
            "fingerprint": REVIEWED_PLAN_FINGERPRINT,
        },
        "implementation": {
            "source_commit": _SOURCE_SHA,
            "files": [
                {
                    "path": relative,
                    "sha256": hashlib.sha256((repository / relative).read_bytes()).hexdigest(),
                }
                for relative in runner_module._LAUNCH_CONTROL_FILES
            ],
        },
        "quality_gates": {
            "source_commit": _SOURCE_SHA,
            "results": [
                {
                    "command": command,
                    "status": "passed",
                    "exit_code": 0,
                    "summary": "passed",
                }
                for command in runner_module._LAUNCH_CONTROL_QUALITY_GATES
            ],
        },
        "equivalence": {
            "schema_version": "intraday-exposed-003-parallel-equivalence-v1",
            "program_id": "intraday-exposed-003",
            "verification_source_commit": _SOURCE_SHA,
            "source_database": "intraday-exposed-003/intraday-exposed-003.sqlite3",
            "source_database_sha256": fixture_hash,
            "source_database_mutated": False,
            "dataset_inputs_mutated": False,
            "fixture_selection": "completed-specification-configuration-and-scenario-only",
            "fixture_count": 3,
            "worker_counts": [1, 4],
            "comparisons": list(runner_module._LAUNCH_CONTROL_EQUIVALENCE_COMPARISONS),
            "sequential_seconds": "4.0",
            "parallel_seconds": "1.5",
            "speedup": "2.666667",
            "fixtures": [
                {
                    "run_id": f"ie003r-{index}",
                    "candidate_id": f"ie003-f{index + 1:02d}-a01-b01",
                    "scenario_id": "normal" if index != 1 else "zero_cost_diagnostic",
                    "run_fingerprint": fixture_hash,
                    "fill_trace_fingerprint": fixture_hash,
                    "round_trip_fingerprint": fixture_hash,
                    "report_sha256": fixture_hash,
                    "report_fingerprint": fixture_hash,
                    "specification_equal": True,
                    "metrics_equal": True,
                    "canonical_report_equal": True,
                }
                for index in range(3)
            ],
            "equivalent": True,
        },
        "intraday_exposed_003_disposition": {
            "inspection_scope": "health-and-progress-metadata-only",
            "classification": "active-materially-incomplete",
            "database_exists": True,
            "run_counts": {"pending": 77, "running": 1, "completed": 42, "failed": 0},
            "attempt_count": 44,
            "terminal": False,
            "valid_terminal_outcome": False,
            "evidence_preserved": True,
            "partial_strategy_merits_inspected": False,
            "process_stop": {"required": True, "signal": "SIGTERM", "confirmed": True},
            "intraday_exposed_004_required": True,
            "action": "stop-preserve-and-supersede-for-execution-throughput",
        },
        "independent_review": {
            "source_commit": _SOURCE_SHA,
            "status": "passed",
            "verdict": "pass",
            "findings": [],
            "reviewer": "independent-control-review",
        },
        "scope_limit": "Health metadata only; no partial strategy merits inspected.",
        "authority": dict(runner_module._AUTHORITY),
    }


def _write_launch_control(
    repository: Path,
    value: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsigned = deepcopy(value)
    unsigned.pop("review_fingerprint", None)
    value["review_fingerprint"] = fingerprint(unsigned)
    raw = (json.dumps(value, indent=2) + "\n").encode()
    path = repository / runner_module.LAUNCH_CONTROL_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    monkeypatch.setattr(
        runner_module,
        "REVIEWED_LAUNCH_CONTROL_SHA256",
        hashlib.sha256(raw).hexdigest(),
    )
    monkeypatch.setattr(
        runner_module,
        "REVIEWED_LAUNCH_CONTROL_FINGERPRINT",
        value["review_fingerprint"],
    )


def _runner(root: Path, *, workers: int = 4) -> IntradayExposed004Runner:
    runner = IntradayExposed004Runner.__new__(IntradayExposed004Runner)
    runner.repository = _REPOSITORY
    runner.data_home = root
    runner.source_commit = _SOURCE_SHA
    runner.launch_control = {
        "schema_version": "intraday-exposed-004-launch-control-review-v1",
        "status": "passed",
        "verdict": "pass",
        "runtime_source_commit": _SOURCE_SHA,
        "authority": runner_module._AUTHORITY,
    }
    runner.workers = workers
    runner.progress = lambda _message: None
    runner.control_plan = load_intraday_exposed_004_plan(_REPOSITORY)
    runner.plan = _effective_plan(runner.control_plan)
    runner.cost_model = load_intraday_execution_cost_model(_REPOSITORY)
    runner.datasets = ()
    runner.data_by_dataset = {}
    runner.runtime_root = root / PROGRAM_ID
    runner.attempt_store = IntradayExposed004Store(runner.runtime_root)
    runner.store = cast(Any, runner.attempt_store)
    runner.scenarios = _scenarios(runner.cost_model)
    runner._bar_cache = {}
    runner.attempt_store.bind(runner._program_binding())
    return runner


def _specification(runner: IntradayExposed004Runner, scenario: str = "normal") -> dict[str, object]:
    return runner._specification(
        "discovery",
        runner.plan.configurations[0],
        runner.plan.periods[0],
        scenario,
    )


def _report(
    specification: Mapping[str, object], _result: object = object(), _period: object = object()
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": RUN_REPORT_SCHEMA,
        "program_id": PROGRAM_ID,
        "run_id": _run_id(specification),
        "specification": canonicalize(specification),
        "specification_fingerprint": fingerprint(specification),
        "metrics": {"test_metric": 1},
        "details": {
            "fill_trace_fingerprint": fingerprint({"fills": 1}),
            "round_trip_fingerprint": fingerprint({"round_trips": 1}),
        },
        "authority": runner_module._AUTHORITY,
    }
    payload["report_fingerprint"] = fingerprint(payload)
    return payload


def _publish(runner: IntradayExposed004Runner, specification: Mapping[str, object]) -> str:
    run_id = _run_id(specification)
    claim = runner.attempt_store.claim(run_id, source_sha=_SOURCE_SHA)
    report = _report(specification)
    runner.attempt_store.publish(
        claim,
        Path("run-reports") / f"{run_id}.json",
        (canonical_json(report) + "\n").encode(),
        report_fingerprint=cast(str, report["report_fingerprint"]),
    )
    return run_id


def test_004_inherits_directly_from_002_and_uses_new_identities(tmp_path: Path) -> None:
    assert IntradayExposed004Runner.__bases__ == (IntradayExposed002Runner,)
    runner = _runner(tmp_path)
    specification = _specification(runner)
    context = cast(Mapping[str, object], specification["context"])
    configuration = cast(Mapping[str, object], specification["configuration"])

    assert specification["program_id"] == PROGRAM_ID
    assert str(specification["schema_version"]).startswith("intraday-exposed-004-")
    assert str(context["candidate_id"]).startswith("ie004-")
    assert str(configuration["source_exposed_003_candidate_id"]).startswith("ie003-")
    assert str(configuration["source_candidate_id"]).startswith("ie002-")
    assert _run_id(specification).startswith("ie004r-")
    assert runner.attempt_store.path.name == DATABASE_NAME
    assert runner.runtime_root.name == PROGRAM_ID


def test_plan_status_and_cli_expose_four_worker_default_without_authority(
    tmp_path: Path,
) -> None:
    plan = intraday_exposed_004_plan_summary(_REPOSITORY)
    status = intraday_exposed_004_status(tmp_path)
    arguments = research_parser().parse_args(("intraday-exposed-004", "run", "--workers", "6"))

    assert plan["parent_configuration_count"] == 60
    assert plan["discovery_run_count"] == 120
    assert plan["default_workers"] == 4
    assert plan["launch_control_exists"] is True
    assert status["database_exists"] is False
    assert arguments.workers == 6
    assert not any(cast(Mapping[str, bool], status["authority"]).values())
    assert not (tmp_path / PROGRAM_ID).exists()


def test_execute_adopts_bounded_executor_and_validates_every_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path, workers=4)
    specifications = (_specification(runner), _specification(runner, "zero_cost_diagnostic"))
    observed: dict[str, object] = {}

    def run_stage(
        tasks: Sequence[Mapping[str, object]],
        *,
        worker_factory: object,
        workers: int,
        progress: Any,
    ) -> tuple[str, ...]:
        observed.update({"tasks": tasks, "factory": worker_factory, "workers": workers})
        results = []
        for done, specification in enumerate(reversed(tasks), 1):
            results.append(_publish(runner, specification))
            progress(done, len(tasks), specification, f"completed-{done}")
        by_run_id = {result: result for result in results}
        return tuple(by_run_id[_run_id(specification)] for specification in tasks)

    monkeypatch.setattr(runner_module, "run_process_stage", run_stage)
    runner._execute(specifications)

    assert observed["workers"] == 4
    assert observed["tasks"] == specifications
    for specification in specifications:
        row = runner.attempt_store.get(_run_id(specification))
        assert row["status"] == "completed"
        assert canonical_json(runner._load_report(row)["specification"]) == canonical_json(
            specification
        )
        assert str(
            runner.attempt_store.list_attempts(_run_id(specification))[0]["attempt_id"]
        ).startswith("ie004a-")


def test_restart_skips_completed_canonical_run_and_resumes_only_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path)
    specifications = (_specification(runner), _specification(runner, "zero_cost_diagnostic"))
    runner.attempt_store.reserve(specifications)
    completed_run_id = _publish(runner, specifications[0])
    completed_bytes = cast(
        Path, runner.attempt_store.get(completed_run_id)["canonical_report_path"]
    )
    before = completed_bytes.read_bytes()
    dispatched: tuple[Mapping[str, object], ...] = ()

    def run_stage(
        tasks: Sequence[Mapping[str, object]],
        **_kwargs: object,
    ) -> tuple[str, ...]:
        nonlocal dispatched
        dispatched = tuple(tasks)
        return tuple(_publish(runner, task) for task in tasks)

    monkeypatch.setattr(runner_module, "run_process_stage", run_stage)
    runner._execute(specifications)

    assert dispatched == (specifications[1],)
    assert completed_bytes.read_bytes() == before
    assert runner.attempt_store.get(completed_run_id)["attempt_count"] == 1
    assert runner.attempt_store.get(_run_id(specifications[1]))["status"] == "completed"


@pytest.mark.parametrize("failure_class", ("candidate", "data"))
def test_worker_deterministic_failure_is_terminal_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_class: str,
) -> None:
    runner = _runner(tmp_path)
    specification = _specification(runner)
    runner.attempt_store.reserve((specification,))
    worker = _worker_from_runner(runner)

    if failure_class == "data":

        def fail_bars(_runner: object, _period: Exposed002Period) -> tuple[()]:
            raise ValueError("deterministic data failure")

        monkeypatch.setattr(IntradayExposed002Runner, "_bars", fail_bars)
    else:
        monkeypatch.setattr(IntradayExposed002Runner, "_bars", lambda *_args: ())

        class _FailingEngine:
            def __init__(self, *_args: object) -> None:
                pass

            def run(self, *_args: object) -> object:
                raise ValueError("deterministic candidate failure")

        monkeypatch.setattr(runner_module, "IntradayExposed002Engine", _FailingEngine)

    with pytest.raises(ValueError, match=f"deterministic {failure_class} failure"):
        worker(specification)

    run_id = _run_id(specification)
    row = runner.attempt_store.get(run_id)
    assert row["status"] == "failed"
    assert row["failure_class"] == failure_class
    assert row["attempt_count"] == 1
    with pytest.raises(AttemptStateError, match="terminal"):
        runner.attempt_store.claim(run_id, source_sha=_SOURCE_SHA)


def test_worker_publication_conflict_is_terminal_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path)
    specification = _specification(runner)
    runner.attempt_store.reserve((specification,))
    worker = _worker_from_runner(runner)
    monkeypatch.setattr(IntradayExposed002Runner, "_bars", lambda *_args: ())
    monkeypatch.setattr(runner_module, "_run_report", _report)

    class _Engine:
        def __init__(self, *_args: object) -> None:
            pass

        def run(self, *_args: object) -> object:
            return object()

    monkeypatch.setattr(runner_module, "IntradayExposed002Engine", _Engine)
    destination = runner.runtime_root / "run-reports" / f"{_run_id(specification)}.json"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"conflicting bytes")

    with pytest.raises(PublicationConflictError, match="canonical report path differs"):
        worker(specification)

    row = runner.attempt_store.get(_run_id(specification))
    assert row["status"] == "failed"
    assert row["failure_class"] == "publication-conflict"
    assert row["attempt_count"] == 1


def test_stage_barriers_remain_coordinator_owned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(tmp_path)
    order: list[str] = []
    discovery = {"parent_count": 0, "paired_run_count": 0}
    walk_forward = {"candidate_count": 0, "paired_run_count": 0}
    serious = {"candidate_count": 0, "stress_run_count": 0, "neighbor_run_count": 0}

    monkeypatch.setattr(runner, "_load_final_report_if_present", lambda: None)

    def run_discovery() -> Mapping[str, object]:
        order.append("discovery")
        return discovery

    def run_walk_forward(_value: object) -> Mapping[str, object]:
        order.append("walk-forward")
        return walk_forward

    def run_serious(_value: object) -> Mapping[str, object]:
        order.append("serious")
        return serious

    def select_cohort(_value: object) -> tuple[()]:
        order.append("cohort")
        return ()

    def freeze(*_args: object) -> Mapping[str, object]:
        order.append("freeze")
        return {"attempt_summary": {}}

    def final_report(*_args: object) -> Mapping[str, object]:
        order.append("final")
        return {
            "outcome": "no-controlled-qualified-candidate",
            "terminal_message": "complete",
            "counts": {"cohort": 0},
            "final_freeze": {},
        }

    monkeypatch.setattr(runner, "_run_discovery", run_discovery)
    monkeypatch.setattr(runner, "_run_walk_forward", run_walk_forward)
    monkeypatch.setattr(runner, "_run_serious", run_serious)
    monkeypatch.setattr(runner, "_select_cohort", select_cohort)
    monkeypatch.setattr(runner, "_freeze", freeze)
    monkeypatch.setattr(runner, "_final_report", final_report)

    assert runner.run()["outcome"] == "no-controlled-qualified-candidate"
    assert order == ["discovery", "walk-forward", "serious", "cohort", "freeze", "final"]


def test_workers_one_and_four_have_identical_specs_and_report_bytes(tmp_path: Path) -> None:
    one = _runner(tmp_path / "one", workers=1)
    four = _runner(tmp_path / "four", workers=4)
    one_specification = _specification(one)
    four_specification = _specification(four)

    assert one_specification == four_specification
    assert _run_id(one_specification) == _run_id(four_specification)
    assert canonical_json(_report(one_specification)) == canonical_json(_report(four_specification))
    assert "workers" not in one_specification


def test_004_store_never_reads_or_imports_003_runtime_rows(tmp_path: Path) -> None:
    exposed_003 = tmp_path / "intraday-exposed-003"
    exposed_003.mkdir()
    sentinel = exposed_003 / "intraday-exposed-003.sqlite3"
    sentinel.write_bytes(b"immutable-003-sentinel")
    before = hashlib.sha256(sentinel.read_bytes()).hexdigest()
    runner = _runner(tmp_path)
    specification = _specification(runner)
    runner.attempt_store.reserve((specification,))

    with sqlite3.connect(runner.attempt_store.path) as connection:
        run_ids = tuple(
            str(row[0]) for row in connection.execute("SELECT run_id FROM research_runs").fetchall()
        )

    assert run_ids == (_run_id(specification),)
    assert all(run_id.startswith("ie004r-") for run_id in run_ids)
    assert hashlib.sha256(sentinel.read_bytes()).hexdigest() == before


def test_launch_control_missing_blocks_runtime_before_data_or_004_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _launch_control_repository(tmp_path / "repository")
    data_home = tmp_path / "data"
    monkeypatch.setattr(runner_module, "_source_commit", lambda _repository: _SOURCE_SHA)

    with pytest.raises(ValueError, match="launch control review is missing"):
        IntradayExposed004Runner(repository, data_home)

    assert not (data_home / PROGRAM_ID).exists()


def test_launch_control_accepts_only_hash_bound_complete_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _launch_control_repository(tmp_path / "repository")
    value = _launch_control(repository)
    _write_launch_control(repository, value, monkeypatch)

    loaded = _load_launch_control(repository, source_commit=_SOURCE_SHA)

    assert loaded["review_fingerprint"] == value["review_fingerprint"]
    assert loaded["implementation"] == value["implementation"]


def test_repository_launch_control_is_hash_bound_to_reviewed_evidence() -> None:
    path = _REPOSITORY / runner_module.LAUNCH_CONTROL_RELATIVE_PATH
    value = cast(dict[str, object], json.loads(path.read_bytes()))
    implementation = cast(dict[str, object], value["implementation"])

    loaded = _load_launch_control(
        _REPOSITORY,
        source_commit=cast(str, implementation["source_commit"]),
    )

    assert loaded["status"] == "passed"
    assert loaded["verdict"] == "pass"
    assert loaded["review_fingerprint"] == REVIEWED_LAUNCH_CONTROL_FINGERPRINT


def test_launch_control_rejects_minimal_fake_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _launch_control_repository(tmp_path / "repository")
    value: dict[str, object] = {
        "schema_version": runner_module._LAUNCH_CONTROL_SCHEMA,
        "review_id": runner_module._LAUNCH_CONTROL_SCHEMA,
        "status": "passed",
        "verdict": "pass",
        "authority": dict(runner_module._AUTHORITY),
    }
    _write_launch_control(repository, value, monkeypatch)

    with pytest.raises(ValueError, match="fields differ"):
        _load_launch_control(repository, source_commit=_SOURCE_SHA)


@pytest.mark.parametrize(
    "case",
    (
        "plan",
        "executor",
        "quality",
        "equivalence-source",
        "equivalence-mutation",
        "equivalence-output",
        "equivalence-span",
        "disposition-merits",
        "disposition-action",
        "disposition-completed",
        "review",
    ),
)
def test_launch_control_enforces_every_required_evidence_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    repository = _launch_control_repository(tmp_path / case)
    value = _launch_control(repository)
    reviewed_plan = cast(dict[str, object], value["reviewed_plan"])
    implementation = cast(dict[str, object], value["implementation"])
    quality = cast(dict[str, object], value["quality_gates"])
    equivalence = cast(dict[str, object], value["equivalence"])
    disposition = cast(dict[str, object], value["intraday_exposed_003_disposition"])
    review = cast(dict[str, object], value["independent_review"])
    if case == "plan":
        reviewed_plan["sha256"] = "0" * 64
    elif case == "executor":
        files = cast(list[dict[str, object]], implementation["files"])
        files[0]["sha256"] = "0" * 64
    elif case == "quality":
        results = cast(list[dict[str, object]], quality["results"])
        results[-1]["status"] = "failed"
    elif case == "equivalence-source":
        equivalence["verification_source_commit"] = "c" * 40
    elif case == "equivalence-mutation":
        equivalence["source_database_mutated"] = True
    elif case == "equivalence-output":
        fixtures = cast(list[dict[str, object]], equivalence["fixtures"])
        fixtures[0]["metrics_equal"] = False
    elif case == "equivalence-span":
        fixtures = cast(list[dict[str, object]], equivalence["fixtures"])
        for fixture in fixtures:
            fixture["candidate_id"] = "ie003-f01-a01-b01"
            fixture["scenario_id"] = "normal"
    elif case == "disposition-merits":
        disposition["partial_strategy_merits_inspected"] = True
    elif case == "disposition-action":
        disposition["action"] = "launch"
    elif case == "disposition-completed":
        disposition.update(
            {
                "classification": "valid-completed-terminal",
                "terminal": True,
                "valid_terminal_outcome": True,
                "process_stop": {"required": False, "signal": None, "confirmed": True},
                "intraday_exposed_004_required": False,
                "action": "preserve-do-not-launch",
            }
        )
    else:
        review["findings"] = ["unresolved"]
    _write_launch_control(repository, value, monkeypatch)

    with pytest.raises(ValueError, match="Intraday Exposed 004 launch"):
        _load_launch_control(repository, source_commit=_SOURCE_SHA)


def test_valid_completed_003_disposition_blocks_004_before_runtime_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _launch_control_repository(tmp_path / "repository")
    value = _launch_control(repository)
    disposition = cast(dict[str, object], value["intraday_exposed_003_disposition"])
    disposition.update(
        {
            "classification": "valid-completed-terminal",
            "terminal": True,
            "valid_terminal_outcome": True,
            "process_stop": {"required": False, "signal": None, "confirmed": True},
            "intraday_exposed_004_required": False,
            "action": "preserve-do-not-launch",
        }
    )
    _write_launch_control(repository, value, monkeypatch)
    monkeypatch.setattr(runner_module, "_source_commit", lambda _repository: _SOURCE_SHA)
    data_home = tmp_path / "data"

    with pytest.raises(ValueError, match="not required after valid Exposed 003 completion"):
        IntradayExposed004Runner(repository, data_home)

    assert not (data_home / PROGRAM_ID).exists()


def test_launch_control_runtime_commit_allows_only_the_review_binding_slice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = "\n".join(
        (
            runner_module.LAUNCH_CONTROL_RELATIVE_PATH.as_posix(),
            "src/systematic_trading_lab/intraday_exposed_004_launch_control.py",
            "CURRENT_STATE.md",
        )
    )

    def run(
        command: tuple[str, ...],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        output = allowed if "diff" in command else ""
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(subprocess, "run", run)
    _verify_launch_source_lineage(tmp_path, "a" * 40, "b" * 40)

    allowed_with_unreviewed_source = f"{allowed}\nsrc/systematic_trading_lab/backtesting.py"

    def changed_source(
        command: tuple[str, ...],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        output = allowed_with_unreviewed_source if "diff" in command else ""
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(subprocess, "run", changed_source)
    with pytest.raises(ValueError, match="source lineage differs"):
        _verify_launch_source_lineage(tmp_path, "a" * 40, "b" * 40)


def _worker_from_runner(runner: IntradayExposed004Runner) -> _Worker:
    worker = _Worker.__new__(_Worker)
    worker.repository = runner.repository
    worker.data_home = runner.data_home
    worker.source_commit = runner.source_commit
    worker.control_plan = runner.control_plan
    worker.plan = runner.plan
    worker.cost_model = runner.cost_model
    worker.datasets = ()
    worker.data_by_dataset = {}
    worker.scenarios = runner.scenarios
    worker._bar_cache = {}
    worker.attempt_store = runner.attempt_store
    return worker
