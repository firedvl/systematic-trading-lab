"""Bounded process execution for independent deterministic research runs."""

from __future__ import annotations

import multiprocessing
import queue
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, cast

DEFAULT_RESEARCH_WORKERS = 4


@dataclass(frozen=True)
class ResearchProcessFailure:
    """One task or worker initialization that did not return normally."""

    task_index: int | None
    error_type: str
    message: str
    worker_exit_code: int | None = None


class ResearchProcessError(RuntimeError):
    """A bounded stage drained its unaffected work but did not fully complete."""

    def __init__(self, failures: Sequence[ResearchProcessFailure]) -> None:
        self.failures = tuple(failures)
        first = self.failures[0]
        location = (
            "worker initialization" if first.task_index is None else f"task {first.task_index}"
        )
        super().__init__(
            f"research process stage failed at {location}: {first.error_type}: {first.message}"
        )


@dataclass(frozen=True)
class _TaskEnvelope[TaskT]:
    index: int
    task: TaskT


@dataclass(frozen=True)
class _WorkerMessage[ResultT]:
    kind: str
    worker_id: int
    task_index: int | None = None
    result: ResultT | None = None
    error_type: str | None = None
    message: str | None = None


@dataclass
class _WorkerSlot[TaskT]:
    process: Any
    input_queue: Any
    ready: bool = False
    initialization_failed: bool = False
    task: _TaskEnvelope[TaskT] | None = None


def run_process_stage[TaskT, ResultT](
    tasks: Sequence[TaskT],
    *,
    worker_factory: Callable[[], Callable[[TaskT], ResultT]],
    workers: int = DEFAULT_RESEARCH_WORKERS,
    progress: Callable[[int, int, TaskT, ResultT], None] | None = None,
) -> tuple[ResultT, ...]:
    """Run one dependency-free stage with at most ``workers`` spawned processes.

    Each process constructs its worker once and handles one task at a time. If a
    process exits abruptly, its task is not reassigned: the campaign's persisted
    lease remains authoritative. Unaffected workers finish the remaining tasks.
    Returned results always follow input order, never completion order.
    """

    if isinstance(workers, bool) or workers < 1:
        raise ValueError("research worker count must be a positive integer")
    pending = deque(_TaskEnvelope(index, task) for index, task in enumerate(tasks))
    if not pending:
        return ()

    context = multiprocessing.get_context("spawn")
    output_queue = context.Queue()
    slots: dict[int, _WorkerSlot[TaskT]] = {}
    results: dict[int, ResultT] = {}
    failures: list[ResearchProcessFailure] = []
    finished = 0
    next_worker_id = 0

    def start_worker() -> None:
        nonlocal next_worker_id
        worker_id = next_worker_id
        next_worker_id += 1
        input_queue = context.Queue(maxsize=1)
        process = context.Process(
            target=_worker_main,
            args=(worker_id, worker_factory, input_queue, output_queue),
            name=f"research-worker-{worker_id}",
        )
        process.start()
        slots[worker_id] = _WorkerSlot(process, input_queue)

    def dispatch() -> None:
        for slot in slots.values():
            if not pending:
                return
            if slot.ready and slot.task is None and slot.process.is_alive():
                envelope = pending.popleft()
                slot.task = envelope
                slot.input_queue.put(envelope)

    def handle(message: _WorkerMessage[ResultT]) -> None:
        nonlocal finished
        slot = slots.get(message.worker_id)
        if slot is None:
            return
        if message.kind == "ready":
            slot.ready = True
            return
        if message.kind == "initialization-error":
            failures.append(
                ResearchProcessFailure(
                    None,
                    message.error_type or "WorkerInitializationError",
                    message.message or "worker initialization failed",
                )
            )
            slot.ready = False
            slot.initialization_failed = True
            return
        envelope = slot.task
        if envelope is None or message.task_index != envelope.index:
            failures.append(
                ResearchProcessFailure(
                    message.task_index,
                    "WorkerProtocolError",
                    "worker returned an unexpected task identity",
                )
            )
            return
        slot.task = None
        finished += 1
        if message.kind == "completed":
            result = cast(ResultT, message.result)
            results[envelope.index] = result
            if progress is not None:
                progress(finished, len(tasks), envelope.task, result)
        else:
            slot.ready = False
            failures.append(
                ResearchProcessFailure(
                    envelope.index,
                    message.error_type or "ResearchWorkerError",
                    message.message or "research worker failed",
                )
            )

    for _ in range(min(workers, len(pending))):
        start_worker()

    try:
        while pending or any(slot.task is not None for slot in slots.values()):
            dispatch()
            try:
                handle(cast(_WorkerMessage[ResultT], output_queue.get(timeout=0.1)))
                while True:
                    handle(cast(_WorkerMessage[ResultT], output_queue.get_nowait()))
            except queue.Empty:
                pass

            for worker_id, slot in tuple(slots.items()):
                if slot.process.is_alive():
                    continue
                slot.process.join()
                envelope = slot.task
                if envelope is not None:
                    failures.append(
                        ResearchProcessFailure(
                            envelope.index,
                            "WorkerProcessExit",
                            "worker exited before returning its task",
                            slot.process.exitcode,
                        )
                    )
                    finished += 1
                slot.input_queue.close()
                slot.input_queue.join_thread()
                del slots[worker_id]
                if pending and not slot.initialization_failed:
                    start_worker()

            if pending and not slots:
                failures.append(
                    ResearchProcessFailure(
                        None,
                        "WorkerPoolUnavailable",
                        "no research worker remained available",
                    )
                )
                break
    finally:
        for slot in slots.values():
            if slot.process.is_alive():
                slot.input_queue.put(None)
        for slot in slots.values():
            slot.process.join()
            slot.input_queue.close()
            slot.input_queue.join_thread()
        output_queue.close()
        output_queue.join_thread()

    if failures:
        raise ResearchProcessError(failures)
    return tuple(results[index] for index in range(len(tasks)))


def _worker_main[TaskT, ResultT](
    worker_id: int,
    worker_factory: Callable[[], Callable[[TaskT], ResultT]],
    input_queue: Any,
    output_queue: Any,
) -> None:
    try:
        worker = worker_factory()
    except Exception as error:
        output_queue.put(
            _WorkerMessage[ResultT](
                "initialization-error",
                worker_id,
                error_type=type(error).__name__,
                message=str(error),
            )
        )
        return
    output_queue.put(_WorkerMessage[ResultT]("ready", worker_id))
    while True:
        envelope = input_queue.get()
        if envelope is None:
            return
        try:
            result = worker(envelope.task)
        except Exception as error:
            output_queue.put(
                _WorkerMessage[ResultT](
                    "error",
                    worker_id,
                    envelope.index,
                    error_type=type(error).__name__,
                    message=str(error),
                )
            )
            return
        else:
            output_queue.put(
                _WorkerMessage[ResultT]("completed", worker_id, envelope.index, result=result)
            )
