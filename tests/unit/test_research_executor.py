from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import cast

import pytest

from systematic_trading_lab.fingerprints import canonical_json, fingerprint
from systematic_trading_lab.research_attempts import (
    AttemptHeartbeat,
    AttemptStateError,
    ResearchAttemptStore,
)
from systematic_trading_lab.research_executor import ResearchProcessError, run_process_stage

_SOURCE_SHA = "a" * 40


@dataclass(frozen=True)
class _AttemptTask:
    run_id: str
    value: int
    delay_seconds: float = 0
    wait_for_running: int = 0
    crash: bool = False
    leave_lease_running: bool = False
    failure_class: str | None = None
    publication_conflict: bool = False


@dataclass(frozen=True)
class _AttemptWorkerFactory:
    root: Path
    lease_seconds: float = 1

    def __call__(self) -> _AttemptWorker:
        return _AttemptWorker(self.root, self.lease_seconds)


class _AttemptWorker:
    def __init__(self, root: Path, lease_seconds: float) -> None:
        self.store = ResearchAttemptStore(
            root,
            lease_timeout=timedelta(seconds=lease_seconds),
            reconcile_on_open=False,
        )
        self.heartbeat_interval = timedelta(seconds=min(0.05, lease_seconds / 3))

    def __call__(self, task: _AttemptTask) -> int:
        claim = self.store.claim(task.run_id, source_sha=_SOURCE_SHA, started_at=datetime.now(UTC))
        if task.leave_lease_running:
            raise RuntimeError("post-claim infrastructure failure")
        try:
            with (
                self.store.capture_output(claim),
                AttemptHeartbeat(self.store, claim, interval=self.heartbeat_interval),
            ):
                if task.wait_for_running:
                    gate = self.store.root / "worker-gate"
                    gate.mkdir(exist_ok=True)
                    (gate / task.run_id).touch()
                    deadline = time.monotonic() + 10
                    while len(tuple(gate.iterdir())) < task.wait_for_running:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("workers did not claim the stage concurrently")
                        time.sleep(0.01)
                if task.crash:
                    os._exit(23)
                if task.failure_class is not None:
                    raise ValueError(f"deterministic {task.failure_class} failure")
                time.sleep(task.delay_seconds)
                unsigned = {"run_id": task.run_id, "value": task.value}
                report_fingerprint = fingerprint(unsigned)
                report = (
                    canonical_json({**unsigned, "report_fingerprint": report_fingerprint}) + "\n"
                ).encode()
        except Exception as error:
            self.store.fail(
                claim,
                failure_class=task.failure_class or "candidate",
                reason=f"{type(error).__name__}: {error}",
                finished_at=datetime.now(UTC),
                exit_status=1,
            )
            raise
        report_path = Path("reports") / f"{task.run_id}.json"
        if task.publication_conflict:
            destination = self.store.root / report_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"conflicting bytes")
        self.store.publish(
            claim,
            report_path,
            report,
            report_fingerprint=report_fingerprint,
            finished_at=datetime.now(UTC),
            exit_status=0,
        )
        return task.value


def _specification(task: _AttemptTask) -> dict[str, object]:
    return {
        "schema_version": "parallel-test-run-v1",
        "source_commit": _SOURCE_SHA,
        "run_id": task.run_id,
        "value": task.value,
    }


def _prepare(root: Path, tasks: tuple[_AttemptTask, ...]) -> ResearchAttemptStore:
    store = ResearchAttemptStore(root, lease_timeout=timedelta(seconds=1))
    store.bind({"program_id": "parallel-test", "source_commit": _SOURCE_SHA})
    for task in tasks:
        store.reserve(task.run_id, _specification(task))
    return store


def _report_bytes(store: ResearchAttemptStore, run_id: str) -> bytes:
    path = store.get(run_id)["canonical_report_path"]
    assert isinstance(path, Path)
    return path.read_bytes()


def test_default_four_workers_claim_four_distinct_runs(tmp_path: Path) -> None:
    tasks = tuple(
        _AttemptTask(f"run-{index}", index, delay_seconds=0.1, wait_for_running=4)
        for index in range(4)
    )
    store = _prepare(tmp_path, tasks)

    assert run_process_stage(tasks, worker_factory=_AttemptWorkerFactory(tmp_path)) == (0, 1, 2, 3)

    attempts = [store.list_attempts(task.run_id)[0] for task in tasks]
    assert len({attempt["pid"] for attempt in attempts}) == 4
    assert all(store.get(task.run_id)["status"] == "completed" for task in tasks)


def test_unpickleable_task_is_rejected_before_workers_start(tmp_path: Path) -> None:
    task = cast(_AttemptTask, MappingProxyType({"run_id": "never-dispatched"}))
    with pytest.raises(TypeError, match="task 0 is not spawn-pickleable"):
        run_process_stage(
            (task,),
            worker_factory=_AttemptWorkerFactory(tmp_path),
        )

    assert not any(tmp_path.iterdir())


def test_unpickleable_worker_factory_is_rejected_before_workers_start(tmp_path: Path) -> None:
    factory = cast(_AttemptWorkerFactory, MappingProxyType({"factory": "invalid"}))
    with pytest.raises(TypeError, match="worker factory is not spawn-pickleable"):
        run_process_stage(
            (_AttemptTask("never-dispatched", 1),),
            worker_factory=factory,
        )

    assert not any(tmp_path.iterdir())


def test_two_process_workers_never_own_the_same_run(tmp_path: Path) -> None:
    task = _AttemptTask("same-run", 1, delay_seconds=0.2)
    store = _prepare(tmp_path, (task,))

    with pytest.raises(ResearchProcessError, match="AttemptStateError"):
        run_process_stage((task, task), worker_factory=_AttemptWorkerFactory(tmp_path), workers=2)

    assert store.get(task.run_id)["status"] == "completed"
    assert len(store.list_attempts(task.run_id)) == 1


def test_worker_death_leaves_only_its_run_retryable_and_other_workers_finish(
    tmp_path: Path,
) -> None:
    tasks = tuple(
        _AttemptTask(f"run-{index}", index, delay_seconds=0.05, crash=index == 0)
        for index in range(5)
    )
    store = _prepare(tmp_path, tasks)

    with pytest.raises(ResearchProcessError) as caught:
        run_process_stage(tasks, worker_factory=_AttemptWorkerFactory(tmp_path, 5), workers=2)

    assert [(item.task_index, item.worker_exit_code) for item in caught.value.failures] == [(0, 23)]
    assert store.get("run-0")["status"] == "running"
    assert all(store.get(f"run-{index}")["status"] == "completed" for index in range(1, 5))

    assert store.expire_stale(datetime.now(UTC) + timedelta(seconds=6)) == ("run-0",)
    assert store.get("run-0")["status"] == "pending"
    retry = replace(tasks[0], crash=False)
    assert run_process_stage(
        (retry,), worker_factory=_AttemptWorkerFactory(tmp_path, 5), workers=1
    ) == (0,)
    assert store.get("run-0")["status"] == "completed"
    assert store.get("run-0")["attempt_count"] == 2
    assert all(store.get(f"run-{index}")["attempt_count"] == 1 for index in range(1, 5))


def test_concurrent_worker_heartbeats_remain_valid(tmp_path: Path) -> None:
    tasks = tuple(_AttemptTask(f"run-{index}", index, delay_seconds=0.25) for index in range(4))
    store = _prepare(tmp_path, tasks)

    run_process_stage(tasks, worker_factory=_AttemptWorkerFactory(tmp_path), workers=4)

    for task in tasks:
        events = store.list_attempts(task.run_id)[0]["events"]
        assert isinstance(events, list)
        kinds = [event["kind"] for event in events]
        assert kinds[0] == "started"
        assert kinds[-1] == "completed"
        assert kinds.count("heartbeat") >= 1


def test_task_exception_retires_worker_before_another_claim(tmp_path: Path) -> None:
    tasks = (
        _AttemptTask("interrupted", 1, leave_lease_running=True),
        _AttemptTask("unaffected", 2),
    )
    store = _prepare(tmp_path, tasks)

    with pytest.raises(ResearchProcessError, match="post-claim infrastructure failure"):
        run_process_stage(tasks, worker_factory=_AttemptWorkerFactory(tmp_path, 5), workers=1)

    assert store.get("interrupted")["status"] == "running"
    assert store.get("unaffected")["status"] == "completed"
    assert (
        store.list_attempts("interrupted")[0]["pid"] != store.list_attempts("unaffected")[0]["pid"]
    )


@pytest.mark.parametrize("failure_class", ("candidate", "data"))
def test_deterministic_worker_failure_is_terminal_without_retry(
    tmp_path: Path, failure_class: str
) -> None:
    task = _AttemptTask("failed-run", 1, failure_class=failure_class)
    store = _prepare(tmp_path, (task,))

    with pytest.raises(ResearchProcessError, match=f"deterministic {failure_class} failure"):
        run_process_stage((task,), worker_factory=_AttemptWorkerFactory(tmp_path), workers=1)

    run = store.get(task.run_id)
    assert run["status"] == "failed"
    assert run["failure_class"] == failure_class
    assert run["attempt_count"] == 1
    with pytest.raises(AttemptStateError, match="terminal"):
        store.claim(task.run_id, source_sha=_SOURCE_SHA, started_at=datetime.now(UTC))


def test_publication_conflict_is_terminal_without_retry(tmp_path: Path) -> None:
    task = _AttemptTask("conflict-run", 1, publication_conflict=True)
    store = _prepare(tmp_path, (task,))

    with pytest.raises(ResearchProcessError, match="canonical report path differs"):
        run_process_stage((task,), worker_factory=_AttemptWorkerFactory(tmp_path), workers=1)

    run = store.get(task.run_id)
    assert run["status"] == "failed"
    assert run["failure_class"] == "publication-conflict"
    assert run["attempt_count"] == 1
    with pytest.raises(AttemptStateError, match="canonical result already exists"):
        store.claim(task.run_id, source_sha=_SOURCE_SHA, started_at=datetime.now(UTC))


def test_sequential_one_worker_and_four_workers_publish_identical_ordered_results(
    tmp_path: Path,
) -> None:
    tasks = tuple(
        _AttemptTask(f"run-{index}", value, delay_seconds=delay)
        for index, (value, delay) in enumerate(((9, 0.3), (2, 0.2), (7, 0.1), (4, 0.0)))
    )
    one_root = tmp_path / "one"
    four_root = tmp_path / "four"
    sequential_root = tmp_path / "sequential"
    one = _prepare(one_root, tasks)
    four = _prepare(four_root, tasks)
    sequential = _prepare(sequential_root, tasks)
    completion_order: list[str] = []

    one_results = run_process_stage(
        tasks, worker_factory=_AttemptWorkerFactory(one_root, 10), workers=1
    )
    parallel_tasks = tuple(replace(task, wait_for_running=4) for task in tasks)
    four_results = run_process_stage(
        parallel_tasks,
        worker_factory=_AttemptWorkerFactory(four_root, 10),
        workers=4,
        progress=lambda _done, _total, task, _result: completion_order.append(task.run_id),
    )
    worker = _AttemptWorkerFactory(sequential_root, 10)()
    sequential_results = tuple(worker(task) for task in tasks)

    assert sorted(completion_order) == [task.run_id for task in tasks]
    assert one_results == four_results == sequential_results == (9, 2, 7, 4)
    assert tuple(value for value in four_results if value >= 7) == (9, 7)
    for task in tasks:
        expected = _report_bytes(sequential, task.run_id)
        assert _report_bytes(one, task.run_id) == expected
        assert _report_bytes(four, task.run_id) == expected
        assert one.get(task.run_id)["run_fingerprint"] == four.get(task.run_id)["run_fingerprint"]
        assert (
            hashlib.sha256(expected).hexdigest() == one.get(task.run_id)["canonical_report_sha256"]
        )


@pytest.mark.parametrize("workers", (0, -1, True))
def test_worker_count_must_be_positive(workers: int) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        run_process_stage((1,), worker_factory=lambda: lambda value: value, workers=workers)
