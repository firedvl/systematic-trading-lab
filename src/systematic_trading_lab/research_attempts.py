"""Append-only execution attempts for restart-safe deterministic research."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import resource
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO, cast

from .fingerprints import canonical_json, fingerprint

_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
_FINGERPRINT_PATTERN = re.compile(r"[0-9a-f]{64}")
_FAILURE_CLASSES = frozenset({"candidate", "data"})
_LEASE_EVENTS = ("started", "heartbeat")
MAX_INFRASTRUCTURE_ATTEMPTS = 3


class AttemptStateError(RuntimeError):
    """The requested attempt transition is not legal."""


class PublicationConflictError(AttemptStateError):
    """A canonical report path contains different bytes."""


@dataclass(frozen=True)
class AttemptClaim:
    run_id: str
    attempt_id: str
    attempt_number: int
    lease_token: str
    started_at: datetime
    stdout_path: Path
    stderr_path: Path


class ResearchAttemptStore:
    """Small SQLite lease and attempt journal for deterministic research runs."""

    def __init__(
        self,
        root: Path,
        *,
        database_name: str = "research-attempts.sqlite3",
        lease_timeout: timedelta = timedelta(minutes=5),
        reconcile_on_open: bool = True,
    ) -> None:
        if lease_timeout <= timedelta(0):
            raise ValueError("research attempt lease timeout must be positive")
        if Path(database_name).name != database_name:
            raise ValueError("research attempt database name must be a file name")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / database_name
        self.lease_timeout = lease_timeout
        self.output_root = self.root / "attempt-output"
        self.output_root.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_program_binding (
                    program_id TEXT PRIMARY KEY,
                    binding_json TEXT NOT NULL,
                    binding_fingerprint TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_runs (
                    run_id TEXT PRIMARY KEY,
                    specification_json TEXT NOT NULL,
                    run_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK (status IN ('pending','running','completed','failed')),
                    active_attempt_id TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0
                        CHECK (attempt_count BETWEEN 0 AND 3),
                    canonical_report_relative_path TEXT,
                    canonical_report_bytes BLOB,
                    canonical_report_sha256 TEXT,
                    canonical_report_fingerprint TEXT,
                    failure_class TEXT,
                    failure_reason TEXT,
                    created_at TEXT NOT NULL,
                    finished_at TEXT,
                    CHECK (
                        (status = 'pending' AND active_attempt_id IS NULL
                            AND canonical_report_sha256 IS NULL
                            AND failure_class IS NULL)
                        OR (status = 'running' AND active_attempt_id IS NOT NULL
                            AND canonical_report_sha256 IS NULL
                            AND failure_class IS NULL)
                        OR (status = 'completed' AND active_attempt_id IS NULL
                            AND canonical_report_sha256 IS NOT NULL
                            AND failure_class IS NULL)
                        OR (status = 'failed' AND active_attempt_id IS NULL
                            AND failure_class IS NOT NULL)
                    ),
                    CHECK (
                        (canonical_report_sha256 IS NULL
                            AND canonical_report_bytes IS NULL
                            AND canonical_report_relative_path IS NULL
                            AND canonical_report_fingerprint IS NULL)
                        OR (canonical_report_sha256 IS NOT NULL
                            AND canonical_report_bytes IS NOT NULL
                            AND canonical_report_relative_path IS NOT NULL
                            AND canonical_report_fingerprint IS NOT NULL)
                    )
                );
                CREATE TABLE IF NOT EXISTS research_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES research_runs(run_id),
                    attempt_number INTEGER NOT NULL CHECK (attempt_number BETWEEN 1 AND 3),
                    lease_token_hash TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    hostname TEXT NOT NULL,
                    pid INTEGER NOT NULL CHECK (pid > 0),
                    source_sha TEXT NOT NULL,
                    run_fingerprint TEXT NOT NULL,
                    stdout_path TEXT NOT NULL,
                    stderr_path TEXT NOT NULL,
                    start_telemetry_json TEXT NOT NULL,
                    UNIQUE (run_id, attempt_number)
                );
                CREATE TABLE IF NOT EXISTS research_attempt_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attempt_id TEXT NOT NULL REFERENCES research_attempts(attempt_id),
                    kind TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    event_fingerprint TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS research_program_binding_no_update
                BEFORE UPDATE ON research_program_binding BEGIN
                    SELECT RAISE(ABORT, 'program bindings are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS research_program_binding_no_delete
                BEFORE DELETE ON research_program_binding BEGIN
                    SELECT RAISE(ABORT, 'program bindings are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS research_runs_no_delete
                BEFORE DELETE ON research_runs BEGIN
                    SELECT RAISE(ABORT, 'research runs are immutable evidence');
                END;
                CREATE TRIGGER IF NOT EXISTS research_run_specifications_no_update
                BEFORE UPDATE OF run_id, specification_json, run_fingerprint ON research_runs BEGIN
                    SELECT RAISE(ABORT, 'run specifications are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS research_canonical_results_no_update
                BEFORE UPDATE OF canonical_report_relative_path, canonical_report_bytes,
                    canonical_report_sha256, canonical_report_fingerprint
                ON research_runs
                WHEN OLD.canonical_report_sha256 IS NOT NULL BEGIN
                    SELECT RAISE(ABORT, 'canonical research results are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS research_run_status_forward_only
                BEFORE UPDATE OF status ON research_runs
                WHEN NOT (
                    (OLD.status = 'pending' AND NEW.status = 'running')
                    OR (OLD.status = 'running' AND NEW.status IN ('pending','completed','failed'))
                    OR (OLD.status = 'completed' AND NEW.status = 'failed'
                        AND NEW.failure_class = 'publication-conflict')
                    OR OLD.status = NEW.status
                ) BEGIN
                    SELECT RAISE(ABORT, 'research run state transition is invalid');
                END;
                CREATE TRIGGER IF NOT EXISTS research_attempts_no_update
                BEFORE UPDATE ON research_attempts BEGIN
                    SELECT RAISE(ABORT, 'attempts are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS research_attempts_no_delete
                BEFORE DELETE ON research_attempts BEGIN
                    SELECT RAISE(ABORT, 'attempts are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS research_attempt_events_no_update
                BEFORE UPDATE ON research_attempt_events BEGIN
                    SELECT RAISE(ABORT, 'attempt events are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS research_attempt_events_no_delete
                BEFORE DELETE ON research_attempt_events BEGIN
                    SELECT RAISE(ABORT, 'attempt events are immutable');
                END;
                """
            )
        if reconcile_on_open:
            self.reconcile_reports()

    def bind(self, value: Mapping[str, object]) -> None:
        program_id = value.get("program_id")
        if not isinstance(program_id, str) or not program_id:
            raise ValueError("research program binding requires a program_id")
        encoded = canonical_json(value)
        binding_fingerprint = fingerprint(value)
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO research_program_binding VALUES (?, ?, ?)",
                (program_id, encoded, binding_fingerprint),
            )
            row = connection.execute(
                "SELECT binding_json, binding_fingerprint "
                "FROM research_program_binding WHERE program_id = ?",
                (program_id,),
            ).fetchone()
        if row != (encoded, binding_fingerprint):
            raise ValueError("stored research program binding differs")

    def reserve(self, run_id: str, specification: Mapping[str, object]) -> None:
        if not run_id:
            raise ValueError("research run ID cannot be empty")
        source_commit = specification.get("source_commit")
        if not isinstance(source_commit, str):
            raise ValueError("research run specification requires source_commit")
        _require_source_sha(source_commit)
        encoded = canonical_json(specification)
        run_fingerprint = fingerprint(specification)
        created_at = _utc_text(datetime.now(UTC))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO research_runs (
                    run_id, specification_json, run_fingerprint, status, created_at
                ) VALUES (?, ?, ?, 'pending', ?)
                """,
                (run_id, encoded, run_fingerprint, created_at),
            )
            row = connection.execute(
                "SELECT specification_json, run_fingerprint FROM research_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row != (encoded, run_fingerprint):
            raise ValueError("stored immutable research run differs")

    def claim(self, run_id: str, *, source_sha: str, started_at: datetime) -> AttemptClaim:
        _require_source_sha(source_sha)
        _require_utc(started_at)
        token = secrets.token_hex(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        telemetry = _safe_resource_telemetry(self.root, observed_at=started_at)
        hostname = socket.gethostname()
        pid = os.getpid()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT specification_json, run_fingerprint, status, active_attempt_id,
                       attempt_count, canonical_report_sha256
                FROM research_runs WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            if row[5] is not None:
                raise AttemptStateError("canonical result already exists; retry is impossible")
            if row[2] == "failed":
                raise AttemptStateError("research run is terminal; retry is impossible")
            if row[2] != "pending" or row[3] is not None:
                raise AttemptStateError("research run already has an active attempt")
            attempt_number = int(row[4]) + 1
            if attempt_number > MAX_INFRASTRUCTURE_ATTEMPTS:
                raise AttemptStateError("research run exhausted its attempt limit")
            specification = _decode_mapping(str(row[0]), "research run specification")
            expected_source = specification["source_commit"]
            if expected_source != source_sha:
                raise AttemptStateError("attempt source SHA differs from its immutable run")
            attempt_id = (
                "ra-"
                + fingerprint(
                    {
                        "run_id": run_id,
                        "attempt_number": attempt_number,
                        "started_at": started_at,
                        "lease_token_hash": token_hash,
                    }
                )[:24]
            )
            stdout_path = self.output_root / f"{attempt_id}.stdout.log"
            stderr_path = self.output_root / f"{attempt_id}.stderr.log"
            _create_empty(stdout_path)
            try:
                _create_empty(stderr_path)
                connection.execute(
                    """
                    INSERT INTO research_attempts (
                        attempt_id, run_id, attempt_number, lease_token_hash, started_at,
                        hostname, pid, source_sha, run_fingerprint, stdout_path, stderr_path,
                        start_telemetry_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        attempt_id,
                        run_id,
                        attempt_number,
                        token_hash,
                        _utc_text(started_at),
                        hostname,
                        pid,
                        source_sha,
                        str(row[1]),
                        str(stdout_path),
                        str(stderr_path),
                        canonical_json(telemetry),
                    ),
                )
                self._append_event(
                    connection,
                    attempt_id,
                    "started",
                    started_at,
                    {"telemetry": telemetry},
                )
                changed = connection.execute(
                    """
                    UPDATE research_runs
                    SET status = 'running', active_attempt_id = ?, attempt_count = ?
                    WHERE run_id = ? AND status = 'pending' AND active_attempt_id IS NULL
                    """,
                    (attempt_id, attempt_number, run_id),
                )
                if changed.rowcount != 1:
                    raise AttemptStateError("research run claim lost its transaction")
            except Exception:
                stdout_path.unlink(missing_ok=True)
                stderr_path.unlink(missing_ok=True)
                raise
        return AttemptClaim(
            run_id=run_id,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            lease_token=token,
            started_at=started_at,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

    def heartbeat(self, claim: AttemptClaim, *, observed_at: datetime) -> None:
        _require_utc(observed_at)
        telemetry = _safe_resource_telemetry(self.root, observed_at=observed_at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_active_claim(connection, claim)
            lease = connection.execute(
                """
                SELECT occurred_at FROM research_attempt_events
                WHERE attempt_id = ? AND kind IN ('started','heartbeat')
                ORDER BY event_id DESC LIMIT 1
                """,
                (claim.attempt_id,),
            ).fetchone()
            if lease is None:
                raise AttemptStateError("active research attempt has no lease event")
            previous = _parse_utc(str(lease[0]))
            if observed_at <= previous:
                raise ValueError("research attempt heartbeat timestamp must increase")
            if observed_at - previous >= self.lease_timeout:
                raise AttemptStateError("research attempt lease already expired")
            self._append_event(
                connection,
                claim.attempt_id,
                "heartbeat",
                observed_at,
                {"telemetry": telemetry},
            )

    def expire_stale(self, observed_at: datetime) -> tuple[str, ...]:
        _require_utc(observed_at)
        recovery_telemetry = _safe_resource_telemetry(self.root, observed_at=observed_at)
        expired: list[str] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT r.run_id, r.active_attempt_id, r.attempt_count,
                       a.stdout_path, a.stderr_path, a.started_at
                FROM research_runs r
                JOIN research_attempts a ON a.attempt_id = r.active_attempt_id
                WHERE r.status = 'running' ORDER BY r.run_id
                """
            ).fetchall()
            for (
                run_id,
                attempt_id,
                attempt_count,
                stdout_path,
                stderr_path,
                started_at,
            ) in rows:
                lease = connection.execute(
                    """
                    SELECT occurred_at FROM research_attempt_events
                    WHERE attempt_id = ? AND kind IN ('started','heartbeat')
                    ORDER BY event_id DESC LIMIT 1
                    """,
                    (attempt_id,),
                ).fetchone()
                if lease is None:
                    raise AttemptStateError("active research attempt has no lease event")
                last_heartbeat = _parse_utc(str(lease[0]))
                if observed_at - last_heartbeat < self.lease_timeout:
                    continue
                exhausted = int(attempt_count) >= MAX_INFRASTRUCTURE_ATTEMPTS
                self._append_event(
                    connection,
                    str(attempt_id),
                    "infrastructure-interruption",
                    observed_at,
                    {
                        "reason": "lease-expired",
                        "duration_seconds": _duration(_parse_utc(str(started_at)), observed_at),
                        "exit_status": None,
                        "last_heartbeat_at": last_heartbeat,
                        "lease_timeout_seconds": int(self.lease_timeout.total_seconds()),
                        "output": _seal_output(Path(str(stdout_path)), Path(str(stderr_path))),
                        "recovery_telemetry": recovery_telemetry,
                    },
                )
                if exhausted:
                    connection.execute(
                        """
                        UPDATE research_runs
                        SET status = 'failed', active_attempt_id = NULL,
                            failure_class = 'infrastructure',
                            failure_reason = 'attempt-limit-exhausted:lease-expired',
                            finished_at = ?
                        WHERE run_id = ? AND status = 'running' AND active_attempt_id = ?
                        """,
                        (_utc_text(observed_at), run_id, attempt_id),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE research_runs
                        SET status = 'pending', active_attempt_id = NULL
                        WHERE run_id = ? AND status = 'running' AND active_attempt_id = ?
                        """,
                        (run_id, attempt_id),
                    )
                expired.append(str(run_id))
        return tuple(expired)

    def publish(
        self,
        claim: AttemptClaim,
        report_path: Path,
        report_bytes: bytes,
        *,
        report_fingerprint: str,
        finished_at: datetime,
        exit_status: int | None,
    ) -> None:
        _require_utc(finished_at)
        _require_fingerprint(report_fingerprint, "report fingerprint")
        relative = _safe_relative_path(report_path)
        if not report_bytes:
            raise ValueError("canonical research report cannot be empty")
        report_sha256 = hashlib.sha256(report_bytes).hexdigest()
        end_telemetry = _safe_resource_telemetry(self.root, observed_at=finished_at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_active_claim(connection, claim)
            self._append_event(
                connection,
                claim.attempt_id,
                "completed",
                finished_at,
                {
                    "duration_seconds": _duration(claim.started_at, finished_at),
                    "end_telemetry": end_telemetry,
                    "exit_status": exit_status,
                    "output": _seal_output(claim.stdout_path, claim.stderr_path),
                    "report_path": relative,
                    "report_sha256": report_sha256,
                    "report_fingerprint": report_fingerprint,
                },
            )
            changed = connection.execute(
                """
                UPDATE research_runs
                SET status = 'completed', active_attempt_id = NULL,
                    canonical_report_relative_path = ?, canonical_report_bytes = ?,
                    canonical_report_sha256 = ?, canonical_report_fingerprint = ?,
                    finished_at = ?
                WHERE run_id = ? AND status = 'running' AND active_attempt_id = ?
                    AND canonical_report_sha256 IS NULL
                """,
                (
                    relative.as_posix(),
                    report_bytes,
                    report_sha256,
                    report_fingerprint,
                    _utc_text(finished_at),
                    claim.run_id,
                    claim.attempt_id,
                ),
            )
            if changed.rowcount != 1:
                raise AttemptStateError("canonical research publication lost its claim")
        try:
            self._materialize(relative, report_bytes)
        except PublicationConflictError as error:
            self._mark_publication_conflict(
                claim.run_id,
                claim.attempt_id,
                finished_at,
                str(error),
            )
            raise

    def fail(
        self,
        claim: AttemptClaim,
        *,
        failure_class: str,
        reason: str,
        finished_at: datetime,
        exit_status: int | None,
    ) -> None:
        if failure_class not in _FAILURE_CLASSES:
            raise ValueError("research failure class must be candidate or data")
        if not reason or len(reason) > 4000:
            raise ValueError("research failure reason is empty or too long")
        _require_utc(finished_at)
        end_telemetry = _safe_resource_telemetry(self.root, observed_at=finished_at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_active_claim(connection, claim)
            self._append_event(
                connection,
                claim.attempt_id,
                f"{failure_class}-failure",
                finished_at,
                {
                    "duration_seconds": _duration(claim.started_at, finished_at),
                    "end_telemetry": end_telemetry,
                    "exit_status": exit_status,
                    "output": _seal_output(claim.stdout_path, claim.stderr_path),
                    "reason": reason,
                },
            )
            changed = connection.execute(
                """
                UPDATE research_runs
                SET status = 'failed', active_attempt_id = NULL,
                    failure_class = ?, failure_reason = ?, finished_at = ?
                WHERE run_id = ? AND status = 'running' AND active_attempt_id = ?
                """,
                (
                    failure_class,
                    reason,
                    _utc_text(finished_at),
                    claim.run_id,
                    claim.attempt_id,
                ),
            )
            if changed.rowcount != 1:
                raise AttemptStateError("terminal research failure lost its claim")

    @contextmanager
    def capture_output(self, claim: AttemptClaim) -> Iterator[None]:
        with (
            claim.stdout_path.open("a", encoding="utf-8", buffering=1) as stdout,
            claim.stderr_path.open("a", encoding="utf-8", buffering=1) as stderr,
            redirect_stdout(cast(TextIO, stdout)),
            redirect_stderr(cast(TextIO, stderr)),
        ):
            yield

    def reconcile_reports(self) -> tuple[Path, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT run_id, canonical_report_relative_path, canonical_report_bytes,
                       active_attempt_id, finished_at
                FROM research_runs
                WHERE status = 'completed' AND canonical_report_sha256 IS NOT NULL
                ORDER BY run_id
                """
            ).fetchall()
        reconciled: list[Path] = []
        for run_id, relative_value, report_bytes, _active_attempt, finished_value in rows:
            relative = _safe_relative_path(Path(str(relative_value)))
            try:
                self._materialize(relative, bytes(report_bytes))
            except PublicationConflictError as error:
                attempt_id = self._completion_attempt_id(str(run_id))
                self._mark_publication_conflict(
                    str(run_id),
                    attempt_id,
                    _parse_utc(str(finished_value)),
                    str(error),
                )
                raise
            reconciled.append(self.root / relative)
        return tuple(reconciled)

    def get(self, run_id: str) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT run_id, specification_json, run_fingerprint, status,
                       active_attempt_id, attempt_count, canonical_report_relative_path,
                       canonical_report_sha256, canonical_report_fingerprint,
                       failure_class, failure_reason, created_at, finished_at
                FROM research_runs WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        relative = None if row[6] is None else _safe_relative_path(Path(str(row[6])))
        return {
            "run_id": str(row[0]),
            "specification": _decode_mapping(str(row[1]), "research run specification"),
            "run_fingerprint": str(row[2]),
            "status": str(row[3]),
            "active_attempt_id": row[4],
            "attempt_count": int(row[5]),
            "canonical_report_path": None if relative is None else self.root / relative,
            "canonical_report_sha256": row[7],
            "canonical_report_fingerprint": row[8],
            "failure_class": row[9],
            "failure_reason": row[10],
            "created_at": row[11],
            "finished_at": row[12],
        }

    def list_runs(self) -> tuple[dict[str, object], ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT run_id FROM research_runs ORDER BY run_id").fetchall()
        return tuple(self.get(str(row[0])) for row in rows)

    def list_attempts(self, run_id: str) -> tuple[dict[str, object], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT attempt_id, attempt_number, started_at, hostname, pid, source_sha,
                       run_fingerprint, stdout_path, stderr_path, start_telemetry_json
                FROM research_attempts WHERE run_id = ? ORDER BY attempt_number
                """,
                (run_id,),
            ).fetchall()
            result: list[dict[str, object]] = []
            for row in rows:
                events = connection.execute(
                    """
                    SELECT event_id, kind, occurred_at, details_json, event_fingerprint
                    FROM research_attempt_events WHERE attempt_id = ? ORDER BY event_id
                    """,
                    (row[0],),
                ).fetchall()
                result.append(
                    {
                        "attempt_id": str(row[0]),
                        "run_id": run_id,
                        "attempt_number": int(row[1]),
                        "started_at": str(row[2]),
                        "hostname": str(row[3]),
                        "pid": int(row[4]),
                        "source_sha": str(row[5]),
                        "run_fingerprint": str(row[6]),
                        "stdout_path": str(row[7]),
                        "stderr_path": str(row[8]),
                        "start_telemetry": _decode_mapping(str(row[9]), "attempt start telemetry"),
                        "events": [
                            {
                                "event_id": int(event[0]),
                                "kind": str(event[1]),
                                "occurred_at": str(event[2]),
                                "details": _decode_mapping(str(event[3]), "attempt event details"),
                                "event_fingerprint": str(event[4]),
                            }
                            for event in events
                        ],
                    }
                )
        return tuple(result)

    def _completion_attempt_id(self, run_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT a.attempt_id FROM research_attempts a
                JOIN research_attempt_events e ON e.attempt_id = a.attempt_id
                WHERE a.run_id = ? AND e.kind = 'completed'
                ORDER BY e.event_id DESC LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            raise AttemptStateError("completed research run has no completion attempt")
        return str(row[0])

    def _mark_publication_conflict(
        self,
        run_id: str,
        attempt_id: str,
        observed_at: datetime,
        reason: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, failure_class FROM research_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row == ("failed", "publication-conflict"):
                return
            if row is None or row[0] != "completed":
                raise AttemptStateError("publication conflict has no canonical result")
            self._append_event(
                connection,
                attempt_id,
                "publication-conflict",
                observed_at,
                {"reason": reason},
            )
            connection.execute(
                """
                UPDATE research_runs
                SET status = 'failed', failure_class = 'publication-conflict',
                    failure_reason = ?
                WHERE run_id = ? AND status = 'completed'
                """,
                (reason, run_id),
            )

    def _materialize(self, relative: Path, report_bytes: bytes) -> None:
        destination = (self.root / relative).resolve(strict=False)
        if not destination.is_relative_to(self.root):
            raise ValueError("canonical research report path escapes its runtime root")
        _write_create_only_bytes(
            destination,
            report_bytes,
            error_type=PublicationConflictError,
            error_message="canonical report path differs",
        )

    def _require_active_claim(self, connection: sqlite3.Connection, claim: AttemptClaim) -> None:
        row = connection.execute(
            """
            SELECT r.status, r.active_attempt_id, r.canonical_report_sha256,
                   a.lease_token_hash, a.run_id
            FROM research_runs r
            JOIN research_attempts a ON a.attempt_id = r.active_attempt_id
            WHERE r.run_id = ?
            """,
            (claim.run_id,),
        ).fetchone()
        if row is None:
            raise AttemptStateError("research attempt claim is missing")
        token_hash = hashlib.sha256(claim.lease_token.encode()).hexdigest()
        if (
            row[0] != "running"
            or row[1] != claim.attempt_id
            or row[2] is not None
            or row[4] != claim.run_id
            or not hmac.compare_digest(str(row[3]), token_hash)
        ):
            raise AttemptStateError("research attempt lease is no longer active")

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        attempt_id: str,
        kind: str,
        occurred_at: datetime,
        details: Mapping[str, object],
    ) -> None:
        payload = {
            "attempt_id": attempt_id,
            "kind": kind,
            "occurred_at": occurred_at,
            "details": details,
        }
        connection.execute(
            """
            INSERT INTO research_attempt_events (
                attempt_id, kind, occurred_at, details_json, event_fingerprint
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                kind,
                _utc_text(occurred_at),
                canonical_json(details),
                fingerprint(payload),
            ),
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


class AttemptHeartbeat:
    """Append lease heartbeats while one in-process attempt computes."""

    def __init__(
        self,
        store: ResearchAttemptStore,
        claim: AttemptClaim,
        *,
        interval: timedelta,
    ) -> None:
        if interval <= timedelta(0) or interval >= store.lease_timeout:
            raise ValueError("heartbeat interval must be positive and shorter than the lease")
        self.store = store
        self.claim = claim
        self.interval = interval.total_seconds()
        self._stop = threading.Event()
        self._error: Exception | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> AttemptHeartbeat:
        self._thread.start()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: Any,
    ) -> None:
        self._stop.set()
        self._thread.join()
        if exception is None and self._error is not None:
            raise self._error

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.store.heartbeat(self.claim, observed_at=datetime.now(UTC))
            except Exception as error:
                self._error = error
                self._stop.set()


def collect_resource_telemetry(
    runtime_root: Path, *, observed_at: datetime | None = None
) -> dict[str, object]:
    at = observed_at or datetime.now(UTC)
    _require_utc(at)
    probes: tuple[tuple[str, Callable[[], object]], ...] = (
        ("available_memory_bytes", _available_memory_bytes),
        ("process_rss_bytes", _process_rss_bytes),
        ("process_peak_rss_bytes", _process_peak_rss_bytes),
        ("disk_free_bytes", lambda: shutil.disk_usage(runtime_root).free),
        ("load_average", lambda: tuple(str(value) for value in os.getloadavg())),
    )
    telemetry: dict[str, object] = {"observed_at": at}
    errors: dict[str, object] = {}
    for name, probe in probes:
        try:
            telemetry[name] = probe()
        except Exception as error:
            telemetry[name] = None
            errors[name] = _telemetry_error(error)
    if errors:
        telemetry["telemetry_errors"] = errors
    return telemetry


def _safe_resource_telemetry(runtime_root: Path, *, observed_at: datetime) -> dict[str, object]:
    try:
        return collect_resource_telemetry(runtime_root, observed_at=observed_at)
    except Exception as error:
        return {
            "observed_at": observed_at,
            "telemetry_errors": {"collector": _telemetry_error(error)},
        }


def _telemetry_error(error: Exception) -> dict[str, str]:
    return {"type": type(error).__name__, "message": str(error)[:500]}


def _available_memory_bytes() -> int | None:
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    if sys.platform == "darwin" and Path("/usr/bin/vm_stat").is_file():
        result = subprocess.run(
            ["/usr/bin/vm_stat"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            page_match = re.search(r"page size of (\d+) bytes", result.stdout)
            if page_match is not None:
                pages = 0
                for label in ("Pages free", "Pages inactive", "Pages speculative"):
                    match = re.search(rf"^{label}:\s+(\d+)\.", result.stdout, re.MULTILINE)
                    if match is not None:
                        pages += int(match.group(1))
                return pages * int(page_match.group(1))
    try:
        return int(os.sysconf("SC_AVPHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError):
        return None


def _process_rss_bytes() -> int | None:
    statm = Path("/proc/self/statm")
    if statm.is_file():
        fields = statm.read_text(encoding="utf-8").split()
        if len(fields) >= 2:
            return int(fields[1]) * int(os.sysconf("SC_PAGE_SIZE"))
    ps = Path("/bin/ps")
    if ps.is_file():
        result = subprocess.run(
            [str(ps), "-o", "rss=", "-p", str(os.getpid())],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        value = result.stdout.strip()
        if result.returncode == 0 and value.isdigit():
            return int(value) * 1024
    return None


def _process_peak_rss_bytes() -> int:
    maximum = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return maximum if sys.platform == "darwin" else maximum * 1024


def _duration(started_at: datetime, finished_at: datetime) -> Decimal:
    if finished_at < started_at:
        raise ValueError("research attempt end precedes its start")
    return Decimal(str((finished_at - started_at).total_seconds()))


def _safe_relative_path(path: Path) -> Path:
    if path.is_absolute() or not path.parts or ".." in path.parts or path == Path("."):
        raise ValueError("canonical research report path must be safe and relative")
    return path


def _create_empty(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.flush()
        os.fsync(handle.fileno())


def _seal_output(stdout_path: Path, stderr_path: Path) -> dict[str, object]:
    result: dict[str, object] = {}
    for label, path in (("stdout", stdout_path), ("stderr", stderr_path)):
        sealed_path = path.with_name(f"{path.name}.sealed")
        if sealed_path.exists():
            if not sealed_path.is_file():
                raise AttemptStateError("sealed attempt output is not a file")
            contents = sealed_path.read_bytes()
        else:
            contents = path.read_bytes()
            _write_create_only_bytes(
                sealed_path,
                contents,
                error_type=AttemptStateError,
                error_message="sealed attempt output differs",
            )
        sealed_path.chmod(0o400)
        result[label] = {
            "byte_count": len(contents),
            "path": sealed_path,
            "sha256": hashlib.sha256(contents).hexdigest(),
        }
    return result


def _write_create_only_bytes(
    destination: Path,
    contents: bytes,
    *,
    error_type: type[AttemptStateError],
    error_message: str,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not destination.is_file() or destination.read_bytes() != contents:
            raise error_type(error_message)
        return
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if not destination.is_file() or destination.read_bytes() != contents:
                raise error_type(error_message) from None
        directory = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _require_source_sha(value: str) -> None:
    if _SHA_PATTERN.fullmatch(value) is None:
        raise ValueError("attempt source SHA must be a full lowercase Git SHA-1")


def _require_fingerprint(value: str, label: str) -> None:
    if _FINGERPRINT_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256")


def _require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("research attempt timestamp must be UTC-aware")


def _utc_text(value: datetime) -> str:
    _require_utc(value)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require_utc(parsed)
    return parsed


def _decode_mapping(value: str, label: str) -> dict[str, object]:
    decoded = json.loads(value)
    if not isinstance(decoded, dict) or any(not isinstance(key, str) for key in decoded):
        raise AttemptStateError(f"{label} is not an object")
    return cast(dict[str, object], decoded)
