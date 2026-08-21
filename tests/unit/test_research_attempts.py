from __future__ import annotations

import hashlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any, cast

import pytest

import systematic_trading_lab.research_attempts as attempts_module
from systematic_trading_lab.fingerprints import canonical_json, fingerprint
from systematic_trading_lab.research_attempts import (
    AttemptClaim,
    AttemptStateError,
    PublicationConflictError,
    ResearchAttemptStore,
    collect_resource_telemetry,
)

_RUN_ID = "ie003r-test"
_SOURCE_SHA = "a" * 40
_START = datetime(2026, 8, 21, 12, tzinfo=UTC)
_LEASE = timedelta(seconds=30)
_SPECIFICATION = {
    "schema_version": "test-run-v1",
    "program_id": "intraday-exposed-003",
    "source_commit": _SOURCE_SHA,
    "candidate_id": "ie003-f01-a01-b01",
    "parameters": {"confirmation_bars": 3, "minimum_gap_bps": "20"},
}


def _store(root: Path) -> ResearchAttemptStore:
    store = ResearchAttemptStore(root, lease_timeout=_LEASE)
    store.bind({"program_id": "intraday-exposed-003", "source_commit": _SOURCE_SHA})
    store.reserve(_RUN_ID, _SPECIFICATION)
    return store


def _report_bytes() -> tuple[bytes, str]:
    unsigned = {"run_id": _RUN_ID, "result": "complete"}
    report_fingerprint = fingerprint(unsigned)
    return (
        (canonical_json({**unsigned, "report_fingerprint": report_fingerprint}) + "\n").encode(),
        report_fingerprint,
    )


def _publish(store: ResearchAttemptStore, claim: AttemptClaim, *, at: datetime) -> None:
    report, report_fingerprint = _report_bytes()
    store.publish(
        claim,
        Path("run-reports") / f"{_RUN_ID}.json",
        report,
        report_fingerprint=report_fingerprint,
        finished_at=at,
        exit_status=0,
    )


def test_killed_worker_expires_then_retries_same_run_once(tmp_path: Path) -> None:
    store = _store(tmp_path)
    script = """
import os
import signal
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from systematic_trading_lab.research_attempts import ResearchAttemptStore

store = ResearchAttemptStore(Path(sys.argv[1]), lease_timeout=timedelta(seconds=30))
claim = store.claim(
    "ie003r-test",
    source_sha="a" * 40,
    started_at=datetime(2026, 8, 21, 12, tzinfo=UTC),
)
with store.capture_output(claim):
    print("worker stdout", flush=True)
    print("worker stderr", file=sys.stderr, flush=True)
    os.kill(os.getpid(), signal.SIGKILL)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        check=False,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[2] / "src")},
    )
    assert result.returncode == -signal.SIGKILL

    assert store.expire_stale(_START + _LEASE) == (_RUN_ID,)
    first = store.list_attempts(_RUN_ID)[0]
    assert first["attempt_number"] == 1
    assert first["run_fingerprint"] == fingerprint(_SPECIFICATION)
    assert Path(str(first["stdout_path"])).read_text() == "worker stdout\n"
    assert Path(str(first["stderr_path"])).read_text() == "worker stderr\n"
    events = cast(list[dict[str, object]], first["events"])
    details = cast(dict[str, object], events[-1]["details"])
    output = cast(dict[str, object], details["output"])
    stdout = cast(dict[str, object], output["stdout"])
    stderr = cast(dict[str, object], output["stderr"])
    assert events[-1]["kind"] == "infrastructure-interruption"
    assert details["reason"] == "lease-expired"
    assert details["duration_seconds"] == "30"
    assert details["exit_status"] is None
    assert stdout == {
        "byte_count": len(b"worker stdout\n"),
        "path": f"{first['stdout_path']}.sealed",
        "sha256": hashlib.sha256(b"worker stdout\n").hexdigest(),
    }
    assert stderr == {
        "byte_count": len(b"worker stderr\n"),
        "path": f"{first['stderr_path']}.sealed",
        "sha256": hashlib.sha256(b"worker stderr\n").hexdigest(),
    }
    assert Path(str(stdout["path"])).read_bytes() == b"worker stdout\n"
    assert Path(str(stderr["path"])).read_bytes() == b"worker stderr\n"

    second = store.claim(
        _RUN_ID,
        source_sha=_SOURCE_SHA,
        started_at=_START + _LEASE + timedelta(seconds=1),
    )
    _publish(store, second, at=_START + _LEASE + timedelta(seconds=2))

    run = store.get(_RUN_ID)
    assert run["status"] == "completed"
    assert run["attempt_count"] == 2
    assert len(store.list_attempts(_RUN_ID)) == 2
    assert Path(str(run["canonical_report_path"])).read_bytes() == _report_bytes()[0]


def test_completed_result_cannot_be_retried(tmp_path: Path) -> None:
    store = _store(tmp_path)
    claim = store.claim(_RUN_ID, source_sha=_SOURCE_SHA, started_at=_START)
    _publish(store, claim, at=_START + timedelta(seconds=1))

    with pytest.raises(AttemptStateError, match="canonical result already exists"):
        store.claim(
            _RUN_ID,
            source_sha=_SOURCE_SHA,
            started_at=_START + timedelta(seconds=2),
        )
    assert len(store.list_attempts(_RUN_ID)) == 1


def test_two_expired_attempts_permit_a_third(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.claim(_RUN_ID, source_sha=_SOURCE_SHA, started_at=_START)
    assert first.attempt_number == 1
    assert store.expire_stale(_START + _LEASE) == (_RUN_ID,)

    second_start = _START + _LEASE + timedelta(seconds=1)
    second = store.claim(_RUN_ID, source_sha=_SOURCE_SHA, started_at=second_start)
    assert second.attempt_number == 2
    assert store.expire_stale(second_start + _LEASE) == (_RUN_ID,)

    third = store.claim(
        _RUN_ID,
        source_sha=_SOURCE_SHA,
        started_at=second_start + _LEASE + timedelta(seconds=1),
    )
    assert third.attempt_number == 3
    assert store.get(_RUN_ID)["status"] == "running"


def test_third_expired_attempt_is_terminal_infrastructure_failure(tmp_path: Path) -> None:
    store = _store(tmp_path)
    started_at = _START
    for attempt_number in range(1, 4):
        claim = store.claim(_RUN_ID, source_sha=_SOURCE_SHA, started_at=started_at)
        assert claim.attempt_number == attempt_number
        assert store.expire_stale(started_at + _LEASE) == (_RUN_ID,)
        started_at += _LEASE + timedelta(seconds=1)

    run = store.get(_RUN_ID)
    assert run["status"] == "failed"
    assert run["failure_class"] == "infrastructure"
    assert run["failure_reason"] == "attempt-limit-exhausted:lease-expired"
    with pytest.raises(AttemptStateError, match="terminal"):
        store.claim(_RUN_ID, source_sha=_SOURCE_SHA, started_at=started_at)


def test_deterministic_strategy_exception_is_terminal_without_retry(tmp_path: Path) -> None:
    store = _store(tmp_path)
    claim = store.claim(_RUN_ID, source_sha=_SOURCE_SHA, started_at=_START)
    store.fail(
        claim,
        failure_class="candidate",
        reason="ValueError: deterministic strategy exception",
        finished_at=_START + timedelta(seconds=1),
        exit_status=1,
    )

    run = store.get(_RUN_ID)
    assert run["status"] == "failed"
    assert run["failure_class"] == "candidate"
    assert run["attempt_count"] == 1
    with pytest.raises(AttemptStateError, match="terminal"):
        store.claim(
            _RUN_ID,
            source_sha=_SOURCE_SHA,
            started_at=_START + timedelta(seconds=2),
        )


def test_publication_conflict_fails_closed_without_retry(tmp_path: Path) -> None:
    store = _store(tmp_path)
    claim = store.claim(_RUN_ID, source_sha=_SOURCE_SHA, started_at=_START)
    destination = tmp_path / "run-reports" / f"{_RUN_ID}.json"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"conflicting bytes")

    with pytest.raises(PublicationConflictError, match="canonical report path differs"):
        _publish(store, claim, at=_START + timedelta(seconds=1))

    run = store.get(_RUN_ID)
    assert run["status"] == "failed"
    assert run["failure_class"] == "publication-conflict"
    assert run["canonical_report_sha256"] is not None
    with pytest.raises(AttemptStateError, match="canonical result already exists"):
        store.claim(
            _RUN_ID,
            source_sha=_SOURCE_SHA,
            started_at=_START + timedelta(seconds=2),
        )


def test_host_restart_recovers_pending_work_from_same_database(tmp_path: Path) -> None:
    original = _store(tmp_path)
    first = original.claim(_RUN_ID, source_sha=_SOURCE_SHA, started_at=_START)
    original.heartbeat(first, observed_at=_START + timedelta(seconds=10))

    restarted = ResearchAttemptStore(tmp_path, lease_timeout=_LEASE)
    assert restarted.expire_stale(_START + timedelta(seconds=40)) == (_RUN_ID,)
    second = restarted.claim(
        _RUN_ID,
        source_sha=_SOURCE_SHA,
        started_at=_START + timedelta(seconds=41),
    )
    assert second.attempt_number == 2
    assert restarted.get(_RUN_ID)["run_fingerprint"] == fingerprint(_SPECIFICATION)


def test_attempt_history_and_run_specification_are_immutable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    claim = store.claim(_RUN_ID, source_sha=_SOURCE_SHA, started_at=_START)
    store.heartbeat(claim, observed_at=_START + timedelta(seconds=1))
    attempt = store.list_attempts(_RUN_ID)[0]
    events = cast(list[dict[str, object]], attempt["events"])
    event_id = events[0]["event_id"]

    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="attempts are immutable"):
            connection.execute(
                "UPDATE research_attempts SET hostname = 'changed' WHERE attempt_id = ?",
                (claim.attempt_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="attempts are immutable"):
            connection.execute(
                "DELETE FROM research_attempts WHERE attempt_id = ?", (claim.attempt_id,)
            )
        with pytest.raises(sqlite3.IntegrityError, match="attempt events are immutable"):
            connection.execute(
                "UPDATE research_attempt_events SET kind = 'changed' WHERE event_id = ?",
                (event_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="run specifications are immutable"):
            connection.execute(
                "UPDATE research_runs SET specification_json = ? WHERE run_id = ?",
                (json.dumps({"changed": True}), _RUN_ID),
            )

    stored = store.get(_RUN_ID)
    assert stored["specification"] == _SPECIFICATION
    telemetry = cast(dict[str, object], attempt["start_telemetry"])
    assert set(telemetry) == {
        "available_memory_bytes",
        "disk_free_bytes",
        "load_average",
        "observed_at",
        "process_peak_rss_bytes",
        "process_rss_bytes",
    }
    assert isinstance(telemetry["disk_free_bytes"], int)
    assert telemetry["disk_free_bytes"] > 0
    assert isinstance(telemetry["process_peak_rss_bytes"], int)
    assert telemetry["process_peak_rss_bytes"] > 0


def test_attempt_limit_cannot_be_configured_above_three(tmp_path: Path) -> None:
    constructor = cast(Any, ResearchAttemptStore)
    with pytest.raises(TypeError, match="max_attempts"):
        constructor(tmp_path, max_attempts=4)


def test_run_requires_source_commit_and_attempts_cannot_change_it(tmp_path: Path) -> None:
    store = ResearchAttemptStore(tmp_path, lease_timeout=_LEASE)
    specification = dict(_SPECIFICATION)
    del specification["source_commit"]
    with pytest.raises(ValueError, match="requires source_commit"):
        store.reserve(_RUN_ID, specification)

    store.reserve(_RUN_ID, _SPECIFICATION)
    with pytest.raises(AttemptStateError, match="source SHA differs"):
        store.claim(_RUN_ID, source_sha="b" * 40, started_at=_START)
    assert store.get(_RUN_ID)["attempt_count"] == 0

    first = store.claim(_RUN_ID, source_sha=_SOURCE_SHA, started_at=_START)
    store.expire_stale(_START + _LEASE)
    with pytest.raises(AttemptStateError, match="source SHA differs"):
        store.claim(
            _RUN_ID,
            source_sha="b" * 40,
            started_at=_START + _LEASE + timedelta(seconds=1),
        )
    assert store.get(_RUN_ID)["attempt_count"] == 1
    assert store.list_attempts(_RUN_ID)[0]["attempt_id"] == first.attempt_id


def test_stale_writer_cannot_change_sealed_output(tmp_path: Path) -> None:
    store = _store(tmp_path)
    claim = store.claim(_RUN_ID, source_sha=_SOURCE_SHA, started_at=_START)
    with claim.stdout_path.open("ab", buffering=0) as stale_stdout:
        stale_stdout.write(b"before expiry\n")
        store.expire_stale(_START + _LEASE)
        attempt = store.list_attempts(_RUN_ID)[0]
        events = cast(list[dict[str, object]], attempt["events"])
        details = cast(dict[str, object], events[-1]["details"])
        output = cast(dict[str, object], details["output"])
        stdout = cast(dict[str, object], output["stdout"])
        sealed_path = Path(str(stdout["path"]))
        stale_stdout.write(b"after expiry\n")

    assert claim.stdout_path.read_bytes() == b"before expiry\nafter expiry\n"
    assert sealed_path.read_bytes() == b"before expiry\n"
    assert stdout["sha256"] == hashlib.sha256(b"before expiry\n").hexdigest()


def test_expiry_reuses_output_sealed_before_recovery_restart(tmp_path: Path) -> None:
    store = _store(tmp_path)
    claim = store.claim(_RUN_ID, source_sha=_SOURCE_SHA, started_at=_START)
    claim.stdout_path.write_bytes(b"before recovery restart\n")
    sealed_path = claim.stdout_path.with_name(f"{claim.stdout_path.name}.sealed")
    sealed_path.write_bytes(claim.stdout_path.read_bytes())
    claim.stdout_path.write_bytes(b"before recovery restart\nafter recovery restart\n")

    assert store.expire_stale(_START + _LEASE) == (_RUN_ID,)
    attempt = store.list_attempts(_RUN_ID)[0]
    events = cast(list[dict[str, object]], attempt["events"])
    details = cast(dict[str, object], events[-1]["details"])
    output = cast(dict[str, object], details["output"])
    stdout = cast(dict[str, object], output["stdout"])
    assert stdout["sha256"] == hashlib.sha256(b"before recovery restart\n").hexdigest()
    assert sealed_path.read_bytes() == b"before recovery restart\n"


def test_store_startup_reconciles_journaled_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    claim = store.claim(_RUN_ID, source_sha=_SOURCE_SHA, started_at=_START)

    def fail_materialization(relative: Path, report_bytes: bytes) -> None:
        raise OSError("simulated interruption after journal commit")

    monkeypatch.setattr(store, "_materialize", fail_materialization)
    with pytest.raises(OSError, match="after journal commit"):
        _publish(store, claim, at=_START + timedelta(seconds=1))

    report_path = cast(Path, store.get(_RUN_ID)["canonical_report_path"])
    assert store.get(_RUN_ID)["status"] == "completed"
    assert not report_path.exists()

    restarted = ResearchAttemptStore(tmp_path, lease_timeout=_LEASE)
    assert report_path.read_bytes() == _report_bytes()[0]
    assert restarted.get(_RUN_ID)["status"] == "completed"


def test_simultaneous_claims_create_one_attempt(tmp_path: Path) -> None:
    store = _store(tmp_path)
    barrier = Barrier(2)

    def claim_once() -> AttemptClaim | str:
        barrier.wait()
        try:
            return store.claim(_RUN_ID, source_sha=_SOURCE_SHA, started_at=_START)
        except AttemptStateError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(executor.submit(claim_once) for _ in range(2))
        results = tuple(future.result() for future in futures)

    claims = tuple(result for result in results if isinstance(result, AttemptClaim))
    errors = tuple(result for result in results if isinstance(result, str))
    assert len(claims) == 1
    assert errors == ("research run already has an active attempt",)
    assert store.get(_RUN_ID)["attempt_count"] == 1
    assert len(store.list_attempts(_RUN_ID)) == 1


def test_telemetry_failure_does_not_block_stale_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    store.claim(_RUN_ID, source_sha=_SOURCE_SHA, started_at=_START)

    def unavailable_telemetry(
        runtime_root: Path, *, observed_at: datetime | None = None
    ) -> dict[str, object]:
        raise OSError("telemetry unavailable")

    monkeypatch.setattr(attempts_module, "collect_resource_telemetry", unavailable_telemetry)
    assert store.expire_stale(_START + _LEASE) == (_RUN_ID,)
    events = cast(list[dict[str, object]], store.list_attempts(_RUN_ID)[0]["events"])
    details = cast(dict[str, object], events[-1]["details"])
    telemetry = cast(dict[str, object], details["recovery_telemetry"])
    errors = cast(dict[str, object], telemetry["telemetry_errors"])
    assert errors == {"collector": {"message": "telemetry unavailable", "type": "OSError"}}


def test_late_future_heartbeat_cannot_defer_stale_recovery(tmp_path: Path) -> None:
    store = _store(tmp_path)
    claim = store.claim(_RUN_ID, source_sha=_SOURCE_SHA, started_at=_START)
    with pytest.raises(ValueError, match="timestamp must increase"):
        store.heartbeat(claim, observed_at=_START)
    with pytest.raises(AttemptStateError, match="lease already expired"):
        store.heartbeat(claim, observed_at=_START + timedelta(days=365))

    assert store.expire_stale(_START + _LEASE) == (_RUN_ID,)


@pytest.mark.parametrize("operation", ("claim", "heartbeat", "publish", "fail"))
def test_telemetry_outage_does_not_block_attempt_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    store = _store(tmp_path)
    claim: AttemptClaim | None = None
    if operation != "claim":
        claim = store.claim(_RUN_ID, source_sha=_SOURCE_SHA, started_at=_START)

    def unavailable_telemetry(
        runtime_root: Path, *, observed_at: datetime | None = None
    ) -> dict[str, object]:
        raise OSError("telemetry unavailable")

    monkeypatch.setattr(attempts_module, "collect_resource_telemetry", unavailable_telemetry)
    if operation == "claim":
        claim = store.claim(_RUN_ID, source_sha=_SOURCE_SHA, started_at=_START)
        telemetry_key = "telemetry"
    elif operation == "heartbeat":
        assert claim is not None
        store.heartbeat(claim, observed_at=_START + timedelta(seconds=1))
        telemetry_key = "telemetry"
    elif operation == "publish":
        assert claim is not None
        _publish(store, claim, at=_START + timedelta(seconds=1))
        telemetry_key = "end_telemetry"
    else:
        assert claim is not None
        store.fail(
            claim,
            failure_class="candidate",
            reason="deterministic failure",
            finished_at=_START + timedelta(seconds=1),
            exit_status=1,
        )
        telemetry_key = "end_telemetry"

    events = cast(list[dict[str, object]], store.list_attempts(_RUN_ID)[0]["events"])
    details = cast(dict[str, object], events[-1]["details"])
    telemetry = cast(dict[str, object], details[telemetry_key])
    errors = cast(dict[str, object], telemetry["telemetry_errors"])
    assert errors == {"collector": {"message": "telemetry unavailable", "type": "OSError"}}


def test_telemetry_probe_failure_preserves_other_measurements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable_memory() -> int:
        raise OSError("memory probe unavailable")

    monkeypatch.setattr(attempts_module, "_available_memory_bytes", unavailable_memory)
    telemetry = collect_resource_telemetry(tmp_path, observed_at=_START)
    errors = cast(dict[str, object], telemetry["telemetry_errors"])
    assert telemetry["available_memory_bytes"] is None
    assert isinstance(telemetry["disk_free_bytes"], int)
    assert errors == {
        "available_memory_bytes": {
            "message": "memory probe unavailable",
            "type": "OSError",
        }
    }
