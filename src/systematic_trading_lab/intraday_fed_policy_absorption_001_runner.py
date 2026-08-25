"""Restart-safe process runner for Intraday Fed Policy Absorption 001."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import Any, cast

from .calendar import expected_bar_timestamps, expected_sessions
from .config import non_broker_subprocess_environment
from .datasets import DatasetService
from .domain import OHLCVBar, Symbol, Timeframe
from .fingerprints import canonical_json, canonicalize, fingerprint

try:  # The implementation remains read-only until a later exact-main review binds this.
    from .intraday_fed_policy_absorption_001_launch_control import (
        REVIEWED_LAUNCH_CONTROL_FINGERPRINT,
        REVIEWED_LAUNCH_CONTROL_SHA256,
    )
except ImportError:
    REVIEWED_LAUNCH_CONTROL_SHA256 = None
    REVIEWED_LAUNCH_CONTROL_FINGERPRINT = None
from .intraday_execution_cost_model import load_intraday_execution_cost_model
from .intraday_exposed_002_runner import (
    IntradayExposed002Runner,
    _account_day,
    _DatasetBinding,
    _exclusive_file_lock,
    _mapping_items,
    _positive_concentration,
    _positive_int,
    _required_text,
    _scenarios,
    _sha256_path,
    _source_commit,
    _strings,
    _text,
    _timestamp,
    _write_create_only,
    _write_create_only_text,
)
from .intraday_fed_policy_absorption_001_engine import (
    Exposed002ReplayResult,
    IntradayFedPolicyAbsorption001Engine,
)
from .intraday_fed_policy_absorption_001_plan import (
    ATTESTATION_FINGERPRINT,
    ATTESTATION_RELATIVE_PATH,
    ATTESTATION_SHA256,
    CALENDAR_FINGERPRINT,
    CALENDAR_RELATIVE_PATH,
    CALENDAR_SHA256,
    PLAN_FINGERPRINT,
    PLAN_RELATIVE_PATH,
    PLAN_SHA256,
    PROGRAM_ID,
    REVIEW_FINGERPRINT,
    REVIEW_RELATIVE_PATH,
    REVIEW_SHA256,
    SOURCE_EVIDENCE_FINGERPRINT,
    SOURCE_EVIDENCE_RELATIVE_PATH,
    SOURCE_EVIDENCE_SHA256,
    SOURCE_STATE_FINGERPRINT,
    SOURCE_STATE_RELATIVE_PATH,
    SOURCE_STATE_SHA256,
    STATE_FINGERPRINT,
    STATE_RELATIVE_PATH,
    STATE_SHA256,
    FedPolicyAbsorptionConfiguration,
    FedPolicyAbsorptionEvent,
    FedPolicyAbsorptionPeriod,
    load_intraday_fed_policy_absorption_001_plan,
)
from .intraday_fed_policy_absorption_001_strategies import (
    build_intraday_fed_policy_absorption_001_strategy,
)
from .research_attempts import (
    AttemptClaim,
    AttemptHeartbeat,
    AttemptStateError,
    ResearchAttemptStore,
)
from .research_executor import (
    DEFAULT_RESEARCH_WORKERS,
    preflight_process_stage,
    run_process_stage,
)
from .storage import StorageLayout

RUNNER_VERSION = "intraday-fed-policy-absorption-001-runner-v1"
RUN_SCHEMA = "intraday-fed-policy-absorption-001-run-v1"
RUN_REPORT_SCHEMA = "intraday-fed-policy-absorption-001-backtest-report-v1"
FINAL_FREEZE_SCHEMA = "intraday-fed-policy-absorption-001-final-freeze-v1"
FINAL_REPORT_SCHEMA = "intraday-fed-policy-absorption-001-final-report-v1"
PROGRAM_BINDING_SCHEMA = "intraday-fed-policy-absorption-001-program-binding-v1"
DATABASE_NAME = "intraday-fed-policy-absorption-001.sqlite3"
ENGINE_VERSION = "intraday-exposed-002-engine-v1"
STRATEGY_VERSION = "intraday-fed-policy-absorption-v1"
LAUNCH_CONTROL_RELATIVE_PATH = Path(
    "config/research/intraday-fed-policy-absorption-001-launch-control-review-v1.json"
)
_LAUNCH_CONTROL_SCHEMA = "intraday-fed-policy-absorption-001-launch-control-review-v1"
_LAUNCH_CONTROL_FILES = (
    "pyproject.toml",
    "src/systematic_trading_lab/research_attempts.py",
    "src/systematic_trading_lab/research_executor.py",
    "src/systematic_trading_lab/intraday_fed_policy_absorption_001_engine.py",
    "src/systematic_trading_lab/intraday_fed_policy_absorption_001_plan.py",
    "src/systematic_trading_lab/intraday_fed_policy_absorption_001_strategies.py",
    "src/systematic_trading_lab/intraday_fed_policy_absorption_001_runner.py",
    "src/systematic_trading_lab/intraday_fed_policy_absorption_001_cli.py",
)
_LAUNCH_CONTROL_QUALITY_GATES = (
    "uv run ruff format --check .",
    "uv run ruff check .",
    "uv run mypy src tests",
    "uv run pytest",
    "uv run python scripts/check_secrets.py",
    "bash -n scripts/*.sh",
    "uv build",
)
_LAUNCH_CONTROL_EQUIVALENCE_COMPARISONS = (
    "run-specification",
    "run-fingerprint",
    "cross-scenario-trace-hash",
    "execution-trace-hash",
    "metrics",
    "event-ledger",
    "canonical-report-bytes",
    "canonical-report-sha256",
    "report-fingerprint",
)
_LAUNCH_CONTROL_POST_REVIEW_FILES = frozenset(
    {
        LAUNCH_CONTROL_RELATIVE_PATH.as_posix(),
        "src/systematic_trading_lab/intraday_fed_policy_absorption_001_launch_control.py",
        "tests/unit/test_intraday_fed_policy_absorption_001_runner.py",
        "CURRENT_STATE.md",
        "DECISIONS.md",
        "ROADMAP.md",
        "docs/research-campaigns/intraday-fed-policy-absorption-001-program.md",
    }
)
_STATUSES = ("pending", "running", "completed", "failed")
_LEASE_TIMEOUT = timedelta(seconds=300)
_HEARTBEAT_INTERVAL = timedelta(seconds=60)
_WORKER_ATTESTATION_TIMEOUT = timedelta(seconds=300)
_ZERO = Decimal("0")
_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)
_CALENDAR_FAILURE_PREFIX = "calendar-integrity: "
_PUBLICATION_CLASSES = ("fomc-meeting-minutes", "fomc-policy-statement")
_SPY, _QQQ = Symbol("SPY"), Symbol("QQQ")
_SYMBOLS = (_SPY, _QQQ)
_ONE, _HALF, _BPS = Decimal("1"), Decimal("0.5"), Decimal("10000")
_MAXIMUM_RUN_SPECIFICATIONS = 90
_NODE_PATTERN = re.compile(r"fedabs-h(?P<horizon>\d{2})-f(?P<floor>\d{4})")
_PERIOD_IDS = (
    "discovery-2025-07-through-10",
    "walk-forward-2025-11-through-12",
    "walk-forward-2026-01-through-02",
    "walk-forward-2026-03-through-04",
    "final-exposed-2026-05",
)
_PARENT_IDS = tuple(
    f"fedabs-h{horizon:02d}-f{floor:04d}" for horizon in (2, 4, 6) for floor in (8, 16, 24)
)
_COST_MODEL_SCENARIO_IDS = MappingProxyType(
    {
        "normal": "normal",
        "zero_cost_diagnostic": "zero_cost_diagnostic",
        "stress_a": "stress_a",
        "stress_b": "stress_b",
        "normal-delay-2": "normal",
        "normal-delay-3": "normal",
    }
)
_REPORT_IDENTITY_FIELDS = (
    "source_commit",
    "plan_sha256",
    "plan_fingerprint",
    "plan_review_sha256",
    "plan_review_fingerprint",
    "autonomous_program_sha256",
    "autonomous_program_fingerprint",
    "source_state_sha256",
    "source_state_fingerprint",
    "state_sha256",
    "state_fingerprint",
    "calendar_sha256",
    "calendar_fingerprint",
    "source_evidence_sha256",
    "source_evidence_fingerprint",
    "attestation_sha256",
    "attestation_fingerprint",
    "dataset_inputs",
    "cost_model_sha256",
    "cost_model_fingerprint",
)


def _mapping(value: object, label: str | None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label or 'value'} must be an object")
    return value


def _require_non_broker_environment(environment: Mapping[str, str] | None = None) -> None:
    """Reject credentials before controls, data bindings, or runtime state exist."""
    values = os.environ if environment is None else environment
    forbidden = sorted(
        key
        for key, value in values.items()
        if value and (key.startswith("APCA_") or key.startswith("TRADING_LAB_PAPER_"))
    )
    if forbidden:
        raise ValueError(
            "Fed Policy Absorption 001 rejects broker environment: " + ", ".join(forbidden)
        )


def decode_canonical_metric(value: object, *, allow_null: bool = False) -> Decimal | int | None:
    """Decode only canonical JSON integers, nulls, and finite Decimal strings."""
    if value is None:
        if allow_null:
            return None
        raise ValueError("semantic null metric fails the gate")
    if isinstance(value, bool | float):
        raise ValueError("metric must not be bool or float")
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("metric Decimal must be finite")
        return value
    if not isinstance(value, str) or not value or value.strip() != value or "e" in value.lower():
        raise ValueError("metric must be a canonical finite Decimal string")
    try:
        decimal = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("metric must be a canonical finite Decimal string") from error
    if not decimal.is_finite() or canonicalize(decimal) != value:
        raise ValueError("metric must be a canonical finite Decimal string")
    return decimal


def _decode_frozen_threshold(value: object) -> Decimal | int:
    if isinstance(value, bool | float) or value is None:
        raise ValueError("frozen gate threshold must not be bool, float, or null")
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("frozen gate threshold must be finite")
        return value
    if not isinstance(value, str) or not value or value.strip() != value or "e" in value.lower():
        raise ValueError("frozen gate threshold must be finite Decimal text")
    try:
        decoded = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("frozen gate threshold must be finite Decimal text") from error
    if not decoded.is_finite() or format(decoded, "f") != value:
        raise ValueError("frozen gate threshold text differs")
    return decoded


def _required_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def _utc_timestamp(value: object, label: str) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError(f"{label} must be a UTC timestamp")
        return value
    return _timestamp(value, label)


def _required_metric(value: Mapping[str, object], name: str) -> Decimal:
    if name not in value:
        raise ValueError(f"missing required metric: {name}")
    decoded = decode_canonical_metric(value[name])
    if decoded is None:
        raise ValueError(f"semantic null metric fails gate: {name}")
    return decoded if isinstance(decoded, Decimal) else Decimal(decoded)


def _optional_metric(value: Mapping[str, object], name: str) -> Decimal | None:
    if name not in value:
        raise ValueError(f"missing required metric: {name}")
    decoded = decode_canonical_metric(value[name], allow_null=True)
    if decoded is None:
        return None
    return decoded if isinstance(decoded, Decimal) else Decimal(decoded)


def _report_metrics(report: Mapping[str, Any]) -> Mapping[str, object]:
    return _mapping(report.get("metrics"), "report metrics")


def _required_report_metric(report: Mapping[str, Any], name: str) -> Decimal:
    return _required_metric(_report_metrics(report), name)


def _plan_gates(
    payload: Mapping[str, Any], screen_name: str, gate_name: str
) -> tuple[Mapping[str, object], ...]:
    screen = _mapping(payload.get(screen_name), screen_name.replace("_", " "))
    raw = screen.get(gate_name)
    if not isinstance(raw, list | tuple) or not raw:
        raise ValueError(f"Fed Policy Absorption 001 {screen_name} gates differ")
    gates = tuple(_mapping(item, "frozen gate") for item in raw)
    for gate in gates:
        if set(gate) != {"metric", "comparison", "threshold"}:
            raise ValueError("Fed Policy Absorption 001 frozen gate shape differs")
        _text(gate, "metric")
        comparison = _text(gate, "comparison")
        if comparison not in {">", ">=", "<", "<=", "="}:
            raise ValueError("Fed Policy Absorption 001 frozen comparison differs")
        _decode_frozen_threshold(gate["threshold"])
    return gates


def _gate_passes(value: object, comparison: str, threshold: object) -> bool:
    decoded = decode_canonical_metric(value, allow_null=True)
    if decoded is None:
        return False
    left = decoded if isinstance(decoded, Decimal) else Decimal(decoded)
    right_value = _decode_frozen_threshold(threshold)
    right = right_value if isinstance(right_value, Decimal) else Decimal(right_value)
    if comparison == ">":
        return left > right
    if comparison == ">=":
        return left >= right
    if comparison == "<":
        return left < right
    if comparison == "<=":
        return left <= right
    if comparison == "=":
        return left == right
    raise ValueError("Fed Policy Absorption 001 frozen comparison differs")


def _exact_gate_results(
    gates: Sequence[Mapping[str, object]], values: Mapping[str, object]
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for gate in gates:
        metric = _text(cast(Mapping[str, Any], gate), "metric")
        comparison = _text(cast(Mapping[str, Any], gate), "comparison")
        if metric not in values:
            raise ValueError(f"missing required metric: {metric}")
        value = values[metric]
        results.append(
            {
                "metric": metric,
                "comparison": comparison,
                "threshold": gate["threshold"],
                "value": value,
                "passed": _gate_passes(value, comparison, gate["threshold"]),
            }
        )
    return results


def _configuration_by_id(
    configurations: Sequence[FedPolicyAbsorptionConfiguration], candidate_id: str
) -> FedPolicyAbsorptionConfiguration:
    matches = tuple(item for item in configurations if item.candidate_id == candidate_id)
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ValueError("Fed Policy Absorption 001 candidate identities collide")
    match = _NODE_PATTERN.fullmatch(candidate_id)
    if match is None:
        raise ValueError(f"unknown Fed Policy Absorption 001 candidate: {candidate_id}")
    horizon = int(match.group("horizon"))
    floor = Decimal(int(match.group("floor")))
    if horizon not in range(1, 8) or floor not in {Decimal(value) for value in range(4, 29, 4)}:
        raise ValueError(f"unknown Fed Policy Absorption 001 candidate: {candidate_id}")
    return FedPolicyAbsorptionConfiguration(candidate_id, horizon, floor, ())


def _event_sessions_for_period(
    events: Sequence[FedPolicyAbsorptionEvent], period: FedPolicyAbsorptionPeriod
) -> frozenset[date]:
    sessions = frozenset(
        date.fromisoformat(event.xnys_session)
        for event in events
        if event.period_id == period.period_id
    )
    if len(sessions) != period.eligible_event_count:
        raise ValueError("Fed Policy Absorption 001 period event sessions differ")
    return sessions


def _event_session_bars(
    bars: Sequence[OHLCVBar], session: date
) -> Mapping[Symbol, tuple[OHLCVBar, ...]]:
    grouped = {
        symbol: tuple(
            sorted(
                (
                    bar
                    for bar in bars
                    if bar.symbol == symbol and _account_day(bar.timestamp) == session
                ),
                key=lambda bar: bar.timestamp,
            )
        )
        for symbol in _SYMBOLS
    }
    spy, qqq = grouped[_SPY], grouped[_QQQ]
    if (
        len(spy) != 78
        or len(qqq) != 78
        or tuple(bar.timestamp for bar in spy) != tuple(bar.timestamp for bar in qqq)
    ):
        raise ValueError("Fed Policy Absorption 001 event session bars differ")
    return MappingProxyType(grouped)


_EQUIVALENCE_PERIOD = FedPolicyAbsorptionPeriod(
    "synthetic-equivalence-2026-01-08-through-09",
    datetime(2026, 1, 7, 14, 30, tzinfo=UTC),
    datetime(2026, 1, 8, 14, 30, tzinfo=UTC),
    datetime(2026, 1, 9, 20, 55, tzinfo=UTC),
    2,
    2,
)
_EQUIVALENCE_EVENTS = (
    FedPolicyAbsorptionEvent(
        "synthetic-minutes-2026-01-08",
        "fomc-meeting-minutes",
        datetime(2026, 1, 8, 19, 0, tzinfo=UTC),
        datetime(2026, 1, 8, 14, 0, tzinfo=UTC),
        "2026-01-08",
        _EQUIVALENCE_PERIOD.period_id,
    ),
    FedPolicyAbsorptionEvent(
        "synthetic-statement-2026-01-09",
        "fomc-policy-statement",
        datetime(2026, 1, 9, 19, 0, tzinfo=UTC),
        datetime(2026, 1, 9, 14, 0, tzinfo=UTC),
        "2026-01-09",
        _EQUIVALENCE_PERIOD.period_id,
    ),
)
_AUTHORITY = MappingProxyType(
    {
        "strategy_implementation": False,
        "strategy_execution": False,
        "strategy_results": False,
        "market_data_read": False,
        "research_qualification": False,
        "controlled_evaluation": False,
        "protected_holdout": False,
        "paper_execution": False,
        "broker_writes": False,
        "live_execution": False,
    }
)


class IntradayFedPolicyAbsorption001Store:
    """Campaign view over the generic append-only attempt store."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.attempts = ResearchAttemptStore(
            self.root,
            database_name=DATABASE_NAME,
            lease_timeout=_LEASE_TIMEOUT,
            reconcile_on_open=False,
            attempt_id_prefix="fedabs001a-",
        )
        self.path = self.attempts.path
        self._enable_canonical_report_rejection()

    def _enable_canonical_report_rejection(self) -> None:
        with sqlite3.connect(self.path, timeout=30) as connection:
            connection.execute("PRAGMA busy_timeout = 30000")
            row = connection.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'trigger' AND name = 'research_run_status_forward_only'"
            ).fetchone()
            if row is not None and "canonical-report-invalid" in str(row[0]):
                return
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DROP TRIGGER research_run_status_forward_only")
            connection.execute(
                """
                CREATE TRIGGER research_run_status_forward_only
                BEFORE UPDATE OF status ON research_runs
                WHEN NOT (
                    (OLD.status = 'pending' AND NEW.status = 'running')
                    OR (OLD.status = 'running'
                        AND NEW.status IN ('pending','completed','failed'))
                    OR (OLD.status = 'completed' AND NEW.status = 'failed'
                        AND NEW.failure_class IN (
                            'publication-conflict','canonical-report-invalid'
                        ))
                    OR OLD.status = NEW.status
                ) BEGIN
                    SELECT RAISE(ABORT, 'research run state transition is invalid');
                END
                """
            )

    def bind(self, value: Mapping[str, object]) -> None:
        self.attempts.bind(value)

    def reserve(self, specifications: Sequence[Mapping[str, object]]) -> None:
        run_ids = tuple(_run_id(value) for value in specifications)
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("Fed Policy Absorption 001 run specifications collide")
        for run_id, specification in zip(run_ids, specifications, strict=True):
            self.attempts.reserve(run_id, specification)

    def claim(self, run_id: str, *, source_sha: str) -> AttemptClaim:
        return self.attempts.claim(run_id, source_sha=source_sha, started_at=datetime.now(UTC))

    def publish(
        self,
        claim: AttemptClaim,
        report_path: Path,
        report_bytes: bytes,
        *,
        report_fingerprint: str,
    ) -> None:
        self.attempts.publish(
            claim,
            report_path,
            report_bytes,
            report_fingerprint=report_fingerprint,
            finished_at=datetime.now(UTC),
            exit_status=0,
        )

    def fail(self, claim: AttemptClaim, *, failure_class: str, reason: str) -> None:
        stored_class = "data" if failure_class == "calendar" else failure_class
        stored_reason = (
            f"{_CALENDAR_FAILURE_PREFIX}{reason}" if failure_class == "calendar" else reason
        )[:4000]
        self.attempts.fail(
            claim,
            failure_class=stored_class,
            reason=stored_reason,
            finished_at=datetime.now(UTC),
            exit_status=1,
        )

    @contextmanager
    def capture_output(self, claim: AttemptClaim) -> Iterator[None]:
        with self.attempts.capture_output(claim):
            yield

    def expire_stale(self) -> tuple[str, ...]:
        return self.attempts.expire_stale(datetime.now(UTC))

    def reconcile_reports(self) -> tuple[Path, ...]:
        return self.attempts.reconcile_reports()

    def reject_canonical_report(self, run_id: str, *, reason: str) -> None:
        reason = reason[:4000]
        if not reason:
            raise ValueError("Fed Policy Absorption 001 report rejection reason is empty")
        observed_at = datetime.now(UTC)
        occurred_at = observed_at.isoformat().replace("+00:00", "Z")
        with sqlite3.connect(self.path, timeout=30) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 30000")
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, failure_class, canonical_report_sha256 "
                "FROM research_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is not None and row[:2] == ("failed", "canonical-report-invalid"):
                return
            if row is None or row[0] != "completed" or row[2] is None:
                raise AttemptStateError(
                    "Fed Policy Absorption 001 report rejection has no canonical result"
                )
            attempt = connection.execute(
                """
                SELECT a.attempt_id FROM research_attempts a
                JOIN research_attempt_events e ON e.attempt_id = a.attempt_id
                WHERE a.run_id = ? AND e.kind = 'completed'
                ORDER BY e.event_id DESC LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            if attempt is None:
                raise AttemptStateError("Fed Policy Absorption 001 completed report has no attempt")
            attempt_id = str(attempt[0])
            details = {"reason": reason}
            event = {
                "attempt_id": attempt_id,
                "kind": "canonical-report-invalid",
                "occurred_at": observed_at,
                "details": details,
            }
            connection.execute(
                """
                INSERT INTO research_attempt_events (
                    attempt_id, kind, occurred_at, details_json, event_fingerprint
                ) VALUES (?, 'canonical-report-invalid', ?, ?, ?)
                """,
                (
                    attempt_id,
                    occurred_at,
                    canonical_json(details),
                    fingerprint(event),
                ),
            )
            changed = connection.execute(
                """
                UPDATE research_runs
                SET status = 'failed', failure_class = 'canonical-report-invalid',
                    failure_reason = ?
                WHERE run_id = ? AND status = 'completed'
                """,
                (reason, run_id),
            )
            if changed.rowcount != 1:
                raise AttemptStateError(
                    "Fed Policy Absorption 001 report rejection lost its transition"
                )

    def get(self, run_id: str) -> dict[str, object]:
        row = self.attempts.get(run_id)
        specification = _mapping(row.get("specification"), "run specification")
        context = _mapping(specification.get("context"), "run context")
        report = row.get("canonical_report_path")
        relative_report: str | None = None
        if isinstance(report, Path):
            relative_report = report.resolve().relative_to(self.root).as_posix()
        failure_class = row.get("failure_class")
        failure_reason = row.get("failure_reason")
        if (
            failure_class == "data"
            and isinstance(failure_reason, str)
            and failure_reason.startswith(_CALENDAR_FAILURE_PREFIX)
        ):
            failure_class = "calendar"
            failure_reason = failure_reason.removeprefix(_CALENDAR_FAILURE_PREFIX)
        return {
            **row,
            "reservation_id": _reservation_id(str(row["run_fingerprint"])),
            "stage": _text(context, "stage"),
            "base_candidate_id": context.get("base_candidate_id"),
            "candidate_id": _text(context, "candidate_id"),
            "period_id": _text(context, "period_id"),
            "scenario_id": _text(context, "scenario_id"),
            "report_path": relative_report,
            "report_sha256": row.get("canonical_report_sha256"),
            "report_fingerprint": row.get("canonical_report_fingerprint"),
            "failure_class": failure_class,
            "failure_reason": failure_reason,
            "error": None if failure_reason is None else f"{failure_class}: {failure_reason}",
        }

    def list_runs(self) -> tuple[dict[str, object], ...]:
        return tuple(self.get(str(row["run_id"])) for row in self.attempts.list_runs())

    def list_attempts(self, run_id: str) -> tuple[dict[str, object], ...]:
        return self.attempts.list_attempts(run_id)


def _record_worker_attestation_failure(root: Path) -> None:
    with suppress(OSError):
        (root / f"failed-{os.getpid()}").touch(exist_ok=True)


def _await_worker_attestations(root: Path, *, source_commit: str, workers: int) -> None:
    if workers < 1:
        raise ValueError("Fed Policy Absorption 001 attestation worker count differs")
    marker = root / f"ready-{os.getpid()}"
    marker_written = False
    deadline = time.monotonic() + _WORKER_ATTESTATION_TIMEOUT.total_seconds()
    while True:
        if any(root.glob("failed-*")):
            raise ValueError("Fed Policy Absorption 001 worker attestation peer failed")
        ready = tuple(root.glob("ready-*"))
        if len(ready) == workers:
            try:
                observed = {item.read_text(encoding="ascii", errors="strict") for item in ready}
            except (OSError, UnicodeError) as error:
                raise ValueError(
                    "Fed Policy Absorption 001 worker attestation read failed"
                ) from error
            if observed != {source_commit}:
                raise ValueError("Fed Policy Absorption 001 worker attestation source differs")
            return
        if len(ready) > workers or time.monotonic() >= deadline:
            raise ValueError("Fed Policy Absorption 001 worker attestation barrier failed")
        if not marker_written:
            try:
                _write_create_only_text(marker, source_commit)
            except OSError as error:
                raise ValueError(
                    "Fed Policy Absorption 001 worker attestation write failed"
                ) from error
            marker_written = True
            continue
        time.sleep(0.05)


@dataclass(frozen=True)
class _WorkerFactory:
    repository: Path
    data_home: Path
    runtime_root: Path
    source_commit: str
    stage_specifications: tuple[Mapping[str, object], ...]
    attestation_root: Path
    attestation_workers: int

    def __call__(self) -> _Worker:
        try:
            return _Worker(
                self.repository,
                self.data_home,
                self.runtime_root,
                self.source_commit,
                self.stage_specifications,
                self.attestation_root,
                self.attestation_workers,
            )
        except Exception:
            _record_worker_attestation_failure(self.attestation_root)
            raise


class _Worker:
    """One process worker with private immutable dataset state."""

    def __init__(
        self,
        repository: Path,
        data_home: Path,
        runtime_root: Path,
        source_commit: str,
        stage_specifications: Sequence[Mapping[str, object]],
        attestation_root: Path,
        attestation_workers: int,
    ) -> None:
        self.repository = repository.resolve()
        self.data_home = data_home.resolve()
        self.source_commit = source_commit
        if _source_commit(self.repository) != self.source_commit:
            raise ValueError("Fed Policy Absorption 001 worker source commit differs")
        if any(
            specification.get("source_commit") != self.source_commit
            for specification in stage_specifications
        ):
            raise ValueError("Fed Policy Absorption 001 worker stage source differs")
        self.plan = load_intraday_fed_policy_absorption_001_plan(self.repository)
        self.cost_model = load_intraday_execution_cost_model(self.repository)
        self.datasets = _dataset_bindings(self.plan.payload)
        self.data_by_dataset = _read_only_dataset_services(self.data_home, self.datasets)
        IntradayExposed002Runner._verify_datasets(cast(Any, self))
        self.scenarios = _scenarios(self.cost_model)
        self._bar_cache: dict[str, tuple[Any, ...]] = {}
        _await_worker_attestations(
            attestation_root,
            source_commit=self.source_commit,
            workers=attestation_workers,
        )
        self.attempt_store = IntradayFedPolicyAbsorption001Store(runtime_root)
        self.attempt_store.reserve(stage_specifications)

    def __call__(self, specification: Mapping[str, object]) -> str:
        if specification.get("source_commit") != self.source_commit:
            raise ValueError("Fed Policy Absorption 001 worker specification source differs")
        run_id = _run_id(specification)
        claim = self.attempt_store.claim(run_id, source_sha=self.source_commit)
        context = _mapping(specification.get("context"), "run context")
        with (
            self.attempt_store.capture_output(claim),
            AttemptHeartbeat(self.attempt_store.attempts, claim, interval=_HEARTBEAT_INTERVAL),
        ):
            failure_class = "candidate"
            try:
                configuration = self._configuration(_text(context, "candidate_id"))
                period = self._period(_text(context, "period_id"))
                scenario = self.scenarios[_text(context, "scenario_id")]
                strategy = build_intraday_fed_policy_absorption_001_strategy(
                    configuration,
                    _event_sessions_for_period(self.plan.events, period),
                )
                failure_class = "data"
                bars = IntradayExposed002Runner._bars(cast(Any, self), cast(Any, period))
                failure_class = "candidate"
                with localcontext(_CONTEXT):
                    result = IntradayFedPolicyAbsorption001Engine(
                        Decimal(str(self.plan.payload["execution"]["initial_cash"])),
                        scenario,
                        self.cost_model.regulatory_fees,
                    ).run(bars, strategy)
                    failure_class = "calendar"
                    report = _run_report(specification, result, period, self.plan.events, bars)
                report_bytes = (canonical_json(report) + "\n").encode()
            except AttemptStateError:
                raise
            except Exception as error:
                self.attempt_store.fail(
                    claim,
                    failure_class=failure_class,
                    reason=f"{type(error).__name__}: {error}",
                )
                raise
        self.attempt_store.publish(
            claim,
            Path("run-reports") / f"{run_id}.json",
            report_bytes,
            report_fingerprint=_text(report, "report_fingerprint"),
        )
        return (
            f"{_text(context, 'stage')} {_text(context, 'candidate_id')} "
            f"{_text(context, 'period_id')} {_text(context, 'scenario_id')} "
            f"attempt-{claim.attempt_number}"
        )

    def _configuration(self, candidate_id: str) -> FedPolicyAbsorptionConfiguration:
        return _configuration_by_id(self.plan.configurations, candidate_id)

    def _period(self, period_id: str) -> FedPolicyAbsorptionPeriod:
        for item in self.plan.periods:
            if item.period_id == period_id:
                return item
        raise ValueError(f"unknown Fed Policy Absorption 001 period: {period_id}")


@dataclass(frozen=True)
class _EquivalenceWorkerFactory:
    repository: Path

    def __call__(self) -> _EquivalenceWorker:
        return _EquivalenceWorker(self.repository)


class _EquivalenceWorker:
    def __init__(self, repository: Path) -> None:
        self.model = load_intraday_execution_cost_model(repository.resolve())
        self.scenarios = _scenarios(self.model)

    def __call__(self, specification: Mapping[str, object]) -> Mapping[str, object]:
        configuration = _mapping(specification.get("configuration"), "equivalence configuration")
        candidate_id = _text(configuration, "candidate_id")
        strategy = build_intraday_fed_policy_absorption_001_strategy(
            FedPolicyAbsorptionConfiguration(
                candidate_id,
                cast(int, configuration["observation_horizon_bars"]),
                Decimal(str(configuration["minimum_joint_reaction_bps"])),
                (),
            ),
            frozenset({date(2026, 1, 8), date(2026, 1, 9)}),
        )
        scenario = self.scenarios[
            _text(_mapping(specification["context"], "context"), "scenario_id")
        ]
        bars = _synthetic_equivalence_bars()
        with localcontext(_CONTEXT):
            result = IntradayFedPolicyAbsorption001Engine(
                Decimal("100000"),
                scenario,
                self.model.regulatory_fees,
            ).run(bars, strategy)
            report = _run_report(
                specification,
                result,
                _EQUIVALENCE_PERIOD,
                _EQUIVALENCE_EVENTS,
                bars,
            )
        details = _mapping(report.get("details"), "equivalence details")
        report_bytes = (canonical_json(report) + "\n").encode()
        return {
            "specification": specification,
            "run_id": _run_id(specification),
            "run_fingerprint": fingerprint(specification),
            "candidate_id": candidate_id,
            "scenario_id": result.scenario_id,
            "cross_scenario_trace_hash": details["cross_scenario_trace_hash"],
            "execution_trace_hash": details["execution_trace_hash"],
            "metrics": report["metrics"],
            "event_ledger": details["event_ledger"],
            "report_bytes": report_bytes,
            "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "report_fingerprint": report["report_fingerprint"],
        }


class IntradayFedPolicyAbsorption001Runner:
    """Coordinate the frozen Campaign 3 stages through spawned workers."""

    def __init__(
        self,
        repository: Path,
        data_home: Path,
        *,
        workers: int = DEFAULT_RESEARCH_WORKERS,
        progress: Callable[[str], None] | None = None,
        data_service: DatasetService | None = None,
    ) -> None:
        _require_non_broker_environment()
        if isinstance(workers, bool) or workers != 4:
            raise ValueError("Fed Policy Absorption 001 requires exactly four workers")
        self.repository = repository.resolve()
        self.data_home = data_home.resolve()
        if REVIEWED_LAUNCH_CONTROL_SHA256 is None or REVIEWED_LAUNCH_CONTROL_FINGERPRINT is None:
            raise ValueError(
                "Intraday Fed Policy Absorption 001 launch control review is not hash-bound"
            )
        self.source_commit = _source_commit(self.repository)
        self.launch_control = _load_launch_control(
            self.repository,
            source_commit=self.source_commit,
        )
        self.workers = workers
        self.progress = progress or (lambda _message: None)
        self.plan = load_intraday_fed_policy_absorption_001_plan(self.repository)
        self.cost_model = load_intraday_execution_cost_model(self.repository)
        self.datasets = _dataset_bindings(self.plan.payload)
        self.data_by_dataset = (
            {binding.dataset_id: data_service for binding in self.datasets}
            if data_service is not None
            else _read_only_dataset_services(self.data_home, self.datasets)
        )
        self._verify_datasets()
        self.runtime_root = self.data_home / PROGRAM_ID
        self.attempt_store = IntradayFedPolicyAbsorption001Store(self.runtime_root)
        self.store = cast(Any, self.attempt_store)
        self.scenarios = _scenarios(self.cost_model)
        self._bar_cache: dict[str, tuple[Any, ...]] = {}
        self.attempt_store.bind(self._program_binding())

    def _verify_datasets(self) -> None:
        IntradayExposed002Runner._verify_datasets(cast(Any, self))

    def run(self) -> dict[str, object]:
        with localcontext(_CONTEXT), _exclusive_file_lock(self.runtime_root / "campaign.lock"):
            existing = self._load_final_report_if_present()
            if existing is not None:
                return self._result(existing)
            try:
                self.attempt_store.reconcile_reports()
                self.attempt_store.expire_stale()
                self._require_no_failures()
                discovery = self._run_discovery()
                walk_forward = self._run_walk_forward(discovery)
                stress = self._run_stress(walk_forward)
                neighbors = self._run_neighbors(stress)
                cohort = self._select_cohort(stress, neighbors)
                freeze = self._freeze(discovery, walk_forward, stress, neighbors, cohort)
                final = self._final_report(
                    discovery, walk_forward, stress, neighbors, cohort, freeze
                )
            except Exception:
                rows = self.attempt_store.list_runs()
                failed = tuple(row for row in rows if row["status"] == "failed")
                running = tuple(row for row in rows if row["status"] == "running")
                if not failed or running:
                    raise
                final = self._terminal_interruption_report(failed)
            return self._result(final)

    def _program_binding(self) -> dict[str, object]:
        return {
            "schema_version": PROGRAM_BINDING_SCHEMA,
            "program_id": PROGRAM_ID,
            "runner_version": RUNNER_VERSION,
            "engine_version": ENGINE_VERSION,
            "strategy_version": STRATEGY_VERSION,
            "source_commit": self.source_commit,
            "plan": self._plan_evidence(),
            "cost_model": {
                "model_id": self.cost_model.payload["cost_model_id"],
                "sha256": self.cost_model.sha256,
                "fingerprint": self.cost_model.model_fingerprint,
            },
            "datasets": [canonicalize(value) for value in self.datasets],
            "attempt_policy": {
                "lease_timeout_seconds": int(_LEASE_TIMEOUT.total_seconds()),
                "heartbeat_interval_seconds": int(_HEARTBEAT_INTERVAL.total_seconds()),
                "maximum_infrastructure_attempts": 3,
                "retry_condition": "expired-no-result-infrastructure-lease-only",
            },
            "process_policy": {
                "start_method": "spawn",
                "default_workers": 4,
                "worker_count_configurable": False,
                "maximum_active_claims_per_worker": 1,
                "worker_count_excluded_from_run_identity": True,
            },
            "launch_control": self.launch_control,
            "authority": _AUTHORITY,
        }

    def _plan_evidence(self) -> dict[str, object]:
        return _frozen_plan_evidence(self.plan)

    def _specification(
        self,
        stage: str,
        configuration: FedPolicyAbsorptionConfiguration,
        period: FedPolicyAbsorptionPeriod,
        scenario_id: str,
        *,
        base_candidate_id: str | None = None,
    ) -> dict[str, object]:
        scenario = self.scenarios[scenario_id]
        specification: dict[str, object] = {
            "schema_version": RUN_SCHEMA,
            "program_id": PROGRAM_ID,
            "runner_version": RUNNER_VERSION,
            "engine_version": ENGINE_VERSION,
            "strategy_version": STRATEGY_VERSION,
            "source_commit": self.source_commit,
            "plan_sha256": self.plan.sha256,
            "plan_fingerprint": self.plan.plan_fingerprint,
            "calendar_sha256": self.plan.calendar_sha256,
            "calendar_fingerprint": self.plan.calendar_fingerprint,
            "source_evidence_sha256": self.plan.source_evidence_sha256,
            "source_evidence_fingerprint": self.plan.source_evidence_fingerprint,
            "plan_review_sha256": self.plan.review_sha256,
            "plan_review_fingerprint": self.plan.review_fingerprint,
            "autonomous_program_sha256": self.plan.payload["autonomous_program"]["sha256"],
            "autonomous_program_fingerprint": self.plan.payload["autonomous_program"][
                "fingerprint"
            ],
            "source_state_sha256": self.plan.source_state_sha256,
            "source_state_fingerprint": self.plan.source_state_fingerprint,
            "state_sha256": self.plan.state_sha256,
            "state_fingerprint": self.plan.state_fingerprint,
            "attestation_sha256": ATTESTATION_SHA256,
            "attestation_fingerprint": ATTESTATION_FINGERPRINT,
            "cost_model_sha256": self.cost_model.sha256,
            "cost_model_fingerprint": self.cost_model.model_fingerprint,
            "cost_model": {
                "model_id": self.cost_model.payload["cost_model_id"],
                "sha256": self.cost_model.sha256,
                "fingerprint": self.cost_model.model_fingerprint,
                "run_scenario_id": scenario_id,
                "cost_model_scenario_id": _COST_MODEL_SCENARIO_IDS[scenario_id],
                "slippage_bps_per_fill": scenario.slippage_bps_per_fill,
                "execution_delay_bars": scenario.execution_delay_bars,
                "regulatory_fee_model_id": scenario.regulatory_fee_model_id,
            },
            "configuration": _configuration_summary(configuration),
            "period": canonicalize(period),
            "dataset_inputs": _run_dataset_inputs(self.datasets, period),
            "execution": self.plan.payload["execution"],
            "context": {
                "stage": stage,
                "base_candidate_id": base_candidate_id,
                "candidate_id": configuration.candidate_id,
                "family_id": STRATEGY_VERSION,
                "period_id": period.period_id,
                "scenario_id": scenario_id,
            },
            "authority": _AUTHORITY,
        }
        return cast(dict[str, object], canonicalize(specification))

    def _execute(self, specifications: Sequence[Mapping[str, object]]) -> None:
        if not specifications:
            return
        _validate_stage_specifications(specifications)
        existing = self.attempt_store.list_runs()
        stage = _text(_mapping(specifications[0].get("context"), "run context"), "stage")
        self._require_stage_frontier(stage, existing)
        existing_ids = {str(row["run_id"]) for row in existing}
        new_ids = {_run_id(specification) for specification in specifications} - existing_ids
        if len(existing_ids) + len(new_ids) > _MAXIMUM_RUN_SPECIFICATIONS:
            raise ValueError("Fed Policy Absorption 001 exceeds its 90-run budget")
        by_run_id = {str(row["run_id"]): row for row in existing}
        pending: list[Mapping[str, object]] = []
        for specification in specifications:
            run_id = _run_id(specification)
            row = by_run_id.get(run_id)
            if row is None or row["status"] == "pending":
                pending.append(specification)
            elif row["status"] == "completed":
                self._load_report(row)
            elif row["status"] == "failed":
                raise AttemptStateError(f"Fed Policy Absorption 001 run is terminal: {run_id}")
            elif row["status"] == "running":
                raise AttemptStateError(
                    f"Fed Policy Absorption 001 run has an active attempt: {run_id}"
                )
            else:
                raise AttemptStateError(f"Fed Policy Absorption 001 run status differs: {run_id}")
        if pending:
            with TemporaryDirectory(prefix="fedabs001-worker-attestation-") as temporary:
                worker_factory = _WorkerFactory(
                    self.repository,
                    self.data_home,
                    self.runtime_root,
                    self.source_commit,
                    tuple(specifications),
                    Path(temporary),
                    min(self.workers, len(pending)),
                )
                run_process_stage(
                    tuple(pending),
                    worker_factory=worker_factory,
                    workers=self.workers,
                    progress=lambda done, total, _task, result: self.progress(
                        f"{done}/{total} {result}"
                    ),
                )
        for specification in specifications:
            self._load_report(self.attempt_store.get(_run_id(specification)))

    @staticmethod
    def _require_stage_frontier(stage: str, rows: Sequence[Mapping[str, object]]) -> None:
        order = ("discovery", "walk-forward", "stress", "neighbor")
        if stage not in order or any(row.get("stage") not in order for row in rows):
            raise ValueError("Fed Policy Absorption 001 reservation stage differs")
        stage_index = order.index(stage)
        if any(order.index(cast(str, row["stage"])) > stage_index for row in rows):
            raise ValueError("Fed Policy Absorption 001 reservation stage regressed")
        by_stage = {name: tuple(row for row in rows if row.get("stage") == name) for name in order}
        prior_counts: Mapping[str, int | tuple[int, ...]] = {}
        if stage == "walk-forward":
            prior_counts = {"discovery": 18}
        elif stage == "stress":
            prior_counts = {"discovery": 18, "walk-forward": (8, 16, 24)}
        elif stage == "neighbor":
            prior_counts = {
                "discovery": 18,
                "walk-forward": (8, 16, 24),
                "stress": 16,
            }
        for name, expected in prior_counts.items():
            prior = by_stage[name]
            allowed = expected if isinstance(expected, tuple) else (expected,)
            if len(prior) not in allowed or any(row.get("status") != "completed" for row in prior):
                raise ValueError("Fed Policy Absorption 001 stage barrier is incomplete")

    def _configuration(self, candidate_id: str) -> FedPolicyAbsorptionConfiguration:
        return _configuration_by_id(self.plan.configurations, candidate_id)

    def _period(self, period_id: str) -> FedPolicyAbsorptionPeriod:
        for item in self.plan.periods:
            if item.period_id == period_id:
                return item
        raise ValueError(f"unknown Fed Policy Absorption 001 period: {period_id}")

    def _load_report(self, row: Mapping[str, object]) -> Mapping[str, Any]:
        if row.get("status") != "completed":
            raise ValueError("Fed Policy Absorption 001 run is not completed")
        try:
            relative = Path(_required_text(row.get("report_path"), "report path"))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Fed Policy Absorption 001 report path is unsafe")
            raw = (self.runtime_root / relative).read_bytes()
            if hashlib.sha256(raw).hexdigest() != row.get("report_sha256"):
                raise ValueError("Fed Policy Absorption 001 report SHA-256 differs")
            value = _mapping(json.loads(raw), "run report")
            stored = _text(value, "report_fingerprint")
            unsigned = dict(value)
            del unsigned["report_fingerprint"]
            specification = _mapping(value.get("specification"), "report specification")
            cost_model = _mapping(specification.get("cost_model"), "report cost model")
            if (
                value.get("schema_version") != RUN_REPORT_SCHEMA
                or value.get("program_id") != PROGRAM_ID
                or value.get("run_id") != row.get("run_id")
                or value.get("specification_fingerprint") != fingerprint(specification)
                or fingerprint(specification) != row.get("run_fingerprint")
                or stored != row.get("report_fingerprint")
                or fingerprint(unsigned) != stored
                or value.get("calendar_sha256") != specification.get("calendar_sha256")
                or value.get("calendar_fingerprint") != specification.get("calendar_fingerprint")
                or value.get("source_evidence_sha256")
                != specification.get("source_evidence_sha256")
                or value.get("source_evidence_fingerprint")
                != specification.get("source_evidence_fingerprint")
                or value.get("plan_sha256") != specification.get("plan_sha256")
                or value.get("plan_fingerprint") != specification.get("plan_fingerprint")
                or value.get("dataset_inputs") != specification.get("dataset_inputs")
                or value.get("cost_model_fingerprint") != cost_model.get("fingerprint")
                or value.get("source_commit") != specification.get("source_commit")
                or value.get("authority") != _AUTHORITY
            ):
                raise ValueError("Fed Policy Absorption 001 report fingerprint differs")
            _validate_run_report_payload(value, self.plan.events)
            return value
        except (ArithmeticError, KeyError, TypeError, UnicodeError, ValueError) as error:
            self.attempt_store.reject_canonical_report(
                _required_text(row.get("run_id"), "run ID"),
                reason=f"{type(error).__name__}: {error}",
            )
            raise

    def _paired_reports(
        self,
        stage: str,
        candidate_id: str,
        period_id: str,
        *,
        base_candidate_id: str | None = None,
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        normal = self._report_for(
            stage,
            candidate_id,
            period_id,
            "normal",
            base_candidate_id=base_candidate_id,
        )
        zero = self._report_for(
            stage,
            candidate_id,
            period_id,
            "zero_cost_diagnostic",
            base_candidate_id=base_candidate_id,
        )
        normal_evidence = _mapping(normal.get("execution_evidence"), "normal evidence")
        zero_evidence = _mapping(zero.get("execution_evidence"), "zero-cost evidence")
        if normal_evidence.get("cross_scenario_trace_hash") != zero_evidence.get(
            "cross_scenario_trace_hash"
        ):
            raise ValueError("Fed Policy Absorption 001 paired decision traces differ")
        return normal, zero

    def _report_for(
        self,
        stage: str,
        candidate_id: str,
        period_id: str,
        scenario_id: str,
        *,
        base_candidate_id: str | None = None,
    ) -> Mapping[str, Any]:
        matches = tuple(
            row
            for row in self.attempt_store.list_runs()
            if row["stage"] == stage
            and row["candidate_id"] == candidate_id
            and row["period_id"] == period_id
            and row["scenario_id"] == scenario_id
            and row["base_candidate_id"] == base_candidate_id
        )
        if len(matches) != 1:
            raise ValueError("Fed Policy Absorption 001 run relationship differs")
        return self._load_report(matches[0])

    def _require_no_failures(self) -> None:
        failed = tuple(row for row in self.attempt_store.list_runs() if row["status"] == "failed")
        if failed:
            raise AttemptStateError(
                "Fed Policy Absorption 001 has "
                f"{len(failed)} terminal failed run(s); no retry is allowed"
            )

    def _run_discovery(self) -> dict[str, object]:
        period = self.plan.periods[0]
        specifications = tuple(
            self._specification("discovery", configuration, period, scenario_id)
            for configuration in self.plan.configurations
            for scenario_id in ("normal", "zero_cost_diagnostic")
        )
        self._execute(specifications)
        gates = _plan_gates(self.plan.payload, "discovery_screen", "gates")
        ledger: list[dict[str, object]] = []
        for configuration in self.plan.configurations:
            normal, zero = self._paired_reports(
                "discovery", configuration.candidate_id, period.period_id
            )
            values = _paired_metric_values(_report_metrics(normal), _report_metrics(zero))
            gate_results = _exact_gate_results(gates, values)
            ledger.append(
                {
                    "candidate": _configuration_summary(configuration),
                    "normal_run_id": normal["run_id"],
                    "zero_cost_run_id": zero["run_id"],
                    "metrics": values,
                    "gate_results": gate_results,
                    "eligible": all(item["passed"] is True for item in gate_results),
                    "selected": False,
                }
            )
        screen = _mapping(self.plan.payload.get("discovery_screen"), "discovery screen")
        selected = _select_eligible(
            ledger,
            _positive_int(screen.get("selection_cap"), "discovery selection cap"),
            key=lambda _item: (),
        )
        for item in ledger:
            item["selected"] = _screen_candidate_id(item) in selected
        return {
            "stage": "discovery",
            "period_id": period.period_id,
            "parent_count": len(ledger),
            "paired_run_count": len(specifications),
            "eligible_count": sum(item["eligible"] is True for item in ledger),
            "selected_candidate_ids": selected,
            "ledger": ledger,
        }

    def _run_walk_forward(self, discovery: Mapping[str, object]) -> dict[str, object]:
        selected = _strings(discovery.get("selected_candidate_ids"), "discovery selection")
        periods = self.plan.periods[1:]
        specifications = tuple(
            self._specification(
                "walk-forward", self._configuration(candidate_id), period, scenario_id
            )
            for candidate_id in selected
            for period in periods
            for scenario_id in ("normal", "zero_cost_diagnostic")
        )
        self._execute(specifications)
        period_gates = _plan_gates(self.plan.payload, "walk_forward_screen", "per_period_gates")
        serious_gates = _plan_gates(self.plan.payload, "serious_candidate_screen", "gates")
        discovery_by_id = {
            _screen_candidate_id(item): item
            for item in _mapping_items(discovery.get("ledger"), "discovery ledger")
        }
        ledger: list[dict[str, object]] = []
        for candidate_id in selected:
            configuration = self._configuration(candidate_id)
            normal_reports: list[Mapping[str, Any]] = []
            zero_reports: list[Mapping[str, Any]] = []
            period_rows: list[dict[str, object]] = []
            for period in periods:
                normal, zero = self._paired_reports("walk-forward", candidate_id, period.period_id)
                normal_reports.append(normal)
                zero_reports.append(zero)
                values = _paired_metric_values(_report_metrics(normal), _report_metrics(zero))
                gate_results = _exact_gate_results(period_gates, values)
                period_rows.append(
                    {
                        "period_id": period.period_id,
                        "normal_run_id": normal["run_id"],
                        "zero_cost_run_id": zero["run_id"],
                        "metrics": values,
                        "gate_results": gate_results,
                        "eligible": all(result["passed"] is True for result in gate_results),
                    }
                )
            normal_aggregate = _aggregate_reports(tuple(normal_reports), self.plan.events)
            zero_aggregate = _aggregate_reports(tuple(zero_reports), self.plan.events)
            discovery_pair = self._paired_reports(
                "discovery", candidate_id, self.plan.periods[0].period_id
            )
            combined_normal = _aggregate_reports(
                (discovery_pair[0], *normal_reports), self.plan.events
            )
            combined_zero = _aggregate_reports((discovery_pair[1], *zero_reports), self.plan.events)
            walk_values = _paired_metric_values(normal_aggregate, zero_aggregate)
            combined_values = _paired_metric_values(combined_normal, combined_zero)
            values = {
                "walk_forward.active_event_count": walk_values["active_event_count"],
                "walk_forward.periods_with_activation": sum(
                    _required_metric(
                        _mapping(row.get("metrics"), "period metrics"), "active_event_count"
                    )
                    > 0
                    for row in period_rows
                ),
                "combined.active_event_count": combined_values["active_event_count"],
                "combined.active_statement_count": combined_values["active_statement_count"],
                "combined.active_minutes_count": combined_values["active_minutes_count"],
                **{
                    f"combined.{key}": value
                    for key, value in combined_values.items()
                    if key.startswith("normal.")
                    or key.startswith("zero_cost_diagnostic.")
                    or key == "gross_edge_bps"
                },
                **{
                    f"walk_forward.{key}": value
                    for key, value in walk_values.items()
                    if key in {"normal.total_return", "zero_cost_diagnostic.total_return"}
                },
            }
            gate_results = _exact_gate_results(serious_gates, values)
            discovery_passed = discovery_by_id[candidate_id].get("eligible") is True
            periods_passed = all(row["eligible"] is True for row in period_rows)
            ledger.append(
                {
                    "candidate": _configuration_summary(configuration),
                    "periods": period_rows,
                    "walk_forward_normal_aggregate": normal_aggregate,
                    "walk_forward_zero_cost_aggregate": zero_aggregate,
                    "combined_normal_aggregate": combined_normal,
                    "combined_zero_cost_aggregate": combined_zero,
                    "metrics": values,
                    "gate_results": gate_results,
                    "eligible": discovery_passed
                    and periods_passed
                    and all(item["passed"] is True for item in gate_results),
                    "selected": False,
                }
            )
        screen = _mapping(
            self.plan.payload.get("serious_candidate_screen"), "serious candidate screen"
        )
        selected_serious = _select_eligible(
            ledger,
            _positive_int(screen.get("selection_cap"), "serious candidate cap"),
            key=lambda _item: (),
        )
        for item in ledger:
            item["selected"] = _screen_candidate_id(item) in selected_serious
        return {
            "stage": "walk-forward-and-serious-selection",
            "candidate_count": len(ledger),
            "paired_run_count": len(specifications),
            "eligible_count": sum(item["eligible"] is True for item in ledger),
            "selected_candidate_ids": selected_serious,
            "ledger": ledger,
        }

    def _run_stress(self, walk_forward: Mapping[str, object]) -> dict[str, object]:
        selected = _strings(walk_forward.get("selected_candidate_ids"), "serious selection")
        periods = self.plan.periods[1:]
        stress_scenarios = ("stress_a", "stress_b", "normal-delay-2", "normal-delay-3")
        stress_specs = tuple(
            self._specification("stress", self._configuration(candidate_id), period, scenario_id)
            for candidate_id in selected
            for period in periods
            for scenario_id in stress_scenarios
        )
        self._execute(stress_specs)
        stress_gates = _plan_gates(self.plan.payload, "stress_delay_screen", "per_scenario_gates")
        walk_by_id = {
            _screen_candidate_id(item): item
            for item in _mapping_items(walk_forward.get("ledger"), "walk-forward ledger")
        }
        ledger: list[dict[str, object]] = []
        for candidate_id in selected:
            configuration = self._configuration(candidate_id)
            base = _mapping(walk_by_id[candidate_id], "base walk-forward screen")
            zero_base = _mapping(base.get("walk_forward_zero_cost_aggregate"), "zero-cost baseline")
            zero_return = _required_metric(zero_base, "total_return")
            scenario_rows: list[dict[str, object]] = []
            for scenario_id in stress_scenarios:
                reports = tuple(
                    self._report_for("stress", candidate_id, period.period_id, scenario_id)
                    for period in periods
                )
                for period, report in zip(periods, reports, strict=True):
                    baseline = self._report_for(
                        "walk-forward", candidate_id, period.period_id, "normal"
                    )
                    if _cross_trace_hash(report) != _cross_trace_hash(baseline):
                        raise ValueError("Fed Policy Absorption 001 stress causal trace differs")
                aggregate = _aggregate_reports(reports, self.plan.events)
                scenario_return = _required_metric(aggregate, "total_return")
                degradation = (
                    (zero_return - scenario_return) / zero_return if zero_return > 0 else None
                )
                values = {
                    "aggregate.total_return": scenario_return,
                    "minimum_period_return": min(
                        _required_report_metric(report, "total_return") for report in reports
                    ),
                    "aggregate.maximum_drawdown": _required_metric(aggregate, "maximum_drawdown"),
                    "degradation_ratio": degradation,
                    "aggregate.session_concentration": _optional_metric(
                        aggregate, "session_concentration"
                    ),
                    "aggregate.event_concentration": _optional_metric(
                        aggregate, "event_concentration"
                    ),
                    "aggregate.publication_class_concentration": _optional_metric(
                        aggregate, "publication_class_concentration"
                    ),
                    "aggregate.period_concentration": _optional_metric(
                        aggregate, "period_concentration"
                    ),
                }
                gate_results = _exact_gate_results(stress_gates, values)
                required_passed = (
                    zero_return > 0
                    and _required_metric(aggregate, "statement_aggregate_contribution") > 0
                    and _required_metric(aggregate, "minutes_aggregate_contribution") > 0
                )
                scenario_rows.append(
                    {
                        "scenario_id": scenario_id,
                        "run_ids": [report["run_id"] for report in reports],
                        "aggregate": aggregate,
                        "metrics": values,
                        "gate_results": gate_results,
                        "eligible": required_passed
                        and all(result["passed"] is True for result in gate_results),
                    }
                )
            ledger.append(
                {
                    "candidate": _configuration_summary(configuration),
                    "scenarios": scenario_rows,
                    "eligible": all(row["eligible"] is True for row in scenario_rows),
                    "selected_for_neighbors": all(row["eligible"] is True for row in scenario_rows),
                }
            )
        selected_for_neighbors = tuple(
            _screen_candidate_id(item) for item in ledger if item["eligible"] is True
        )
        if len(selected_for_neighbors) > 1:
            raise ValueError("Fed Policy Absorption 001 stress selection exceeds one")
        return {
            "stage": "stress-delay",
            "candidate_count": len(ledger),
            "stress_run_count": len(stress_specs),
            "eligible_count": sum(item["eligible"] is True for item in ledger),
            "selected_candidate_ids": selected_for_neighbors,
            "ledger": ledger,
        }

    def _run_neighbors(self, stress: Mapping[str, object]) -> dict[str, object]:
        selected = _strings(stress.get("selected_candidate_ids"), "stress selection")
        periods = self.plan.periods[1:]
        specifications = tuple(
            self._specification(
                "neighbor",
                self._configuration(neighbor_id),
                period,
                scenario_id,
                base_candidate_id=parent_id,
            )
            for parent_id in selected
            for neighbor_id in self._configuration(parent_id).neighbor_ids
            for period in periods
            for scenario_id in ("normal", "zero_cost_diagnostic")
        )
        self._execute(specifications)
        gates = _plan_gates(self.plan.payload, "neighbor_screen", "per_neighbor_gates")
        ledger: list[dict[str, object]] = []
        for parent_id in selected:
            neighbor_rows: list[dict[str, object]] = []
            for neighbor_id in self._configuration(parent_id).neighbor_ids:
                normal_reports: list[Mapping[str, Any]] = []
                zero_reports: list[Mapping[str, Any]] = []
                period_rows: list[dict[str, object]] = []
                for period in periods:
                    normal, zero = self._paired_reports(
                        "neighbor", neighbor_id, period.period_id, base_candidate_id=parent_id
                    )
                    normal_reports.append(normal)
                    zero_reports.append(zero)
                    period_rows.append(
                        {
                            "period_id": period.period_id,
                            "normal_run_id": normal["run_id"],
                            "zero_cost_run_id": zero["run_id"],
                            "active_event_count": _required_report_metric(
                                normal, "active_event_count"
                            ),
                        }
                    )
                normal_aggregate = _aggregate_reports(tuple(normal_reports), self.plan.events)
                zero_aggregate = _aggregate_reports(tuple(zero_reports), self.plan.events)
                pair_values = _paired_metric_values(normal_aggregate, zero_aggregate)
                values = {
                    "walk_forward.active_event_count": pair_values["active_event_count"],
                    "walk_forward.periods_with_activation": sum(
                        _required_metric(row, "active_event_count") > 0 for row in period_rows
                    ),
                    **{
                        f"aggregate.{key}": value
                        for key, value in pair_values.items()
                        if key.startswith("normal.")
                        or key.startswith("zero_cost_diagnostic.")
                        or key == "gross_edge_bps"
                    },
                }
                gate_results = _exact_gate_results(gates, values)
                required_passed = (
                    _required_integer(
                        pair_values.get("active_statement_count"), "active statement count"
                    )
                    >= 1
                    and _required_integer(
                        pair_values.get("active_minutes_count"), "active minutes count"
                    )
                    >= 1
                )
                neighbor_rows.append(
                    {
                        "neighbor_id": neighbor_id,
                        "periods": period_rows,
                        "normal_aggregate": normal_aggregate,
                        "zero_cost_aggregate": zero_aggregate,
                        "metrics": values,
                        "gate_results": gate_results,
                        "eligible": required_passed
                        and all(result["passed"] is True for result in gate_results),
                    }
                )
            ledger.append(
                {
                    "candidate": _configuration_summary(self._configuration(parent_id)),
                    "neighbors": neighbor_rows,
                    "eligible": len(neighbor_rows) == 4
                    and all(row["eligible"] is True for row in neighbor_rows),
                    "selected": False,
                }
            )
        selected_cohort = tuple(
            _screen_candidate_id(item) for item in ledger if item["eligible"] is True
        )
        if len(selected_cohort) > 1:
            raise ValueError("Fed Policy Absorption 001 neighbor selection exceeds one")
        for item in ledger:
            item["selected"] = _screen_candidate_id(item) in selected_cohort
        return {
            "stage": "immediate-neighbors",
            "candidate_count": len(ledger),
            "neighbor_run_count": len(specifications),
            "eligible_count": len(selected_cohort),
            "selected_candidate_ids": selected_cohort,
            "ledger": ledger,
        }

    def _select_cohort(
        self, stress: Mapping[str, object], neighbors: Mapping[str, object]
    ) -> tuple[str, ...]:
        stress_ids = _strings(stress.get("selected_candidate_ids"), "stress selection")
        cohort = _strings(neighbors.get("selected_candidate_ids"), "neighbor selection")
        if len(cohort) > 1 or any(candidate_id not in stress_ids for candidate_id in cohort):
            raise ValueError("Fed Policy Absorption 001 final cohort differs")
        return cohort

    def _freeze(
        self,
        discovery: Mapping[str, object],
        walk_forward: Mapping[str, object],
        stress: Mapping[str, object],
        neighbors: Mapping[str, object],
        cohort: Sequence[str],
    ) -> Mapping[str, Any]:
        runs = self.attempt_store.list_runs()
        canonical_reports = [self._load_report(row) for row in runs]
        screened = {
            "discovery": discovery,
            "walk_forward": walk_forward,
            "stress": stress,
            "neighbors": neighbors,
        }
        validate_terminal_screening(self.plan, canonical_reports, screened, cohort)
        histories = [
            {
                "run_id": row["run_id"],
                "reservation_id": row["reservation_id"],
                "attempts": self.attempt_store.list_attempts(str(row["run_id"])),
            }
            for row in runs
        ]
        payload: dict[str, object] = {
            "schema_version": FINAL_FREEZE_SCHEMA,
            "program_id": PROGRAM_ID,
            "status": "frozen-after-complete-exposed-screening",
            "source_commit": self.source_commit,
            "runner_version": RUNNER_VERSION,
            "engine_version": ENGINE_VERSION,
            "strategy_version": STRATEGY_VERSION,
            "plan": self._plan_evidence(),
            "launch_control": self.launch_control,
            "cost_model": {
                "sha256": self.cost_model.sha256,
                "fingerprint": self.cost_model.model_fingerprint,
            },
            "datasets": [canonicalize(value) for value in self.datasets],
            "screened_ledger": screened,
            "cohort": [
                _configuration_summary(self._configuration(candidate_id)) for candidate_id in cohort
            ],
            "cohort_size": len(cohort),
            "all_runtime_runs": [_run_evidence(row) for row in runs],
            "attempt_summary": _attempt_summary(runs, histories),
            "attempt_histories": histories,
            "controlled_boundary": {
                "range_status": "none-eligible",
                "june_read": False,
                "substitute_range": False,
                "controlled_evaluation_performed": False,
                "terminal_action": (
                    "close-empty-cohort-as-negative-exposed-evidence"
                    if not cohort
                    else "freeze-cohort-and-wait-for-future-untouched-data"
                ),
            },
            "protected_access": _protected_access(),
            "authority": _AUTHORITY,
        }
        payload["freeze_fingerprint"] = fingerprint(payload)
        _write_create_only(self.runtime_root / "final-freeze.json", payload)
        return payload

    def _final_report(
        self,
        discovery: Mapping[str, object],
        walk_forward: Mapping[str, object],
        stress: Mapping[str, object],
        neighbors: Mapping[str, object],
        cohort: Sequence[str],
        freeze: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        empty = not cohort
        payload: dict[str, object] = {
            "schema_version": FINAL_REPORT_SCHEMA,
            "program_id": PROGRAM_ID,
            "outcome": (
                "no-controlled-qualified-candidate"
                if empty
                else "exposed-serious-candidates-waiting-for-future-untouched-data"
            ),
            "terminal_message": (
                "INTRADAY FED POLICY ABSORPTION 001 COMPLETE — NO CONTROLLED-QUALIFIED CANDIDATE"
                if empty
                else "INTRADAY FED POLICY ABSORPTION 001 COMPLETE — "
                "WAITING FOR FUTURE UNTOUCHED DATA"
            ),
            "source_commit": self.source_commit,
            "plan": self._plan_evidence(),
            "launch_control": {
                "path": LAUNCH_CONTROL_RELATIVE_PATH.as_posix(),
                "sha256": REVIEWED_LAUNCH_CONTROL_SHA256,
                "fingerprint": REVIEWED_LAUNCH_CONTROL_FINGERPRINT,
            },
            "complete_exposed_screening": True,
            "counts": {
                "discovery_parents": discovery["parent_count"],
                "discovery_runs": discovery["paired_run_count"],
                "walk_forward_candidates": walk_forward["candidate_count"],
                "walk_forward_runs": walk_forward["paired_run_count"],
                "serious_candidates": walk_forward["eligible_count"],
                "stress_candidates": stress["candidate_count"],
                "stress_runs": stress["stress_run_count"],
                "neighbor_candidates": neighbors["candidate_count"],
                "neighbor_runs": neighbors["neighbor_run_count"],
                "total_runs": len(self.attempt_store.list_runs()),
                "cohort": len(cohort),
            },
            "cohort": [
                _configuration_summary(self._configuration(candidate_id)) for candidate_id in cohort
            ],
            "attempt_summary": freeze["attempt_summary"],
            "runtime_database": {
                "path": DATABASE_NAME,
                "sha256": _sha256_path(self.attempt_store.path),
            },
            "final_freeze": {
                "path": "final-freeze.json",
                "sha256": _sha256_path(self.runtime_root / "final-freeze.json"),
                "fingerprint": freeze["freeze_fingerprint"],
            },
            "controlled_evaluation": {
                "performed": False,
                "reason": "No eligible untouched controlled range exists.",
                "controlled_qualified_claim": False,
            },
            "protected_access": _protected_access(),
            "authority": _AUTHORITY,
        }
        return self._publish_final_report(payload)

    def _terminal_interruption_report(
        self, failed: Sequence[Mapping[str, object]]
    ) -> Mapping[str, Any]:
        runs = self.attempt_store.list_runs()
        histories = [
            {
                "run_id": row["run_id"],
                "reservation_id": row["reservation_id"],
                "attempts": self.attempt_store.list_attempts(str(row["run_id"])),
            }
            for row in runs
        ]
        counts = {status: sum(row["status"] == status for row in runs) for status in _STATUSES}
        payload: dict[str, object] = {
            "schema_version": FINAL_REPORT_SCHEMA,
            "program_id": PROGRAM_ID,
            "outcome": "terminally-interrupted",
            "terminal_message": "INTRADAY FED POLICY ABSORPTION 001 TERMINALLY INTERRUPTED",
            "source_commit": self.source_commit,
            "plan": self._plan_evidence(),
            "launch_control": {
                "path": LAUNCH_CONTROL_RELATIVE_PATH.as_posix(),
                "sha256": REVIEWED_LAUNCH_CONTROL_SHA256,
                "fingerprint": REVIEWED_LAUNCH_CONTROL_FINGERPRINT,
            },
            "complete_exposed_screening": False,
            "counts": {
                "discovery_parents": None,
                "discovery_runs": None,
                "walk_forward_candidates": None,
                "walk_forward_runs": None,
                "serious_candidates": None,
                "stress_candidates": None,
                "stress_runs": None,
                "neighbor_candidates": None,
                "neighbor_runs": None,
                "total_runs": len(runs),
                "cohort": None,
                "runtime_runs": counts,
            },
            "cohort": [],
            "terminal_failures": [_run_evidence(row) for row in failed],
            "attempt_summary": _attempt_summary(runs, histories),
            "attempt_histories": histories,
            "runtime_database": {
                "path": DATABASE_NAME,
                "sha256": _sha256_path(self.attempt_store.path),
            },
            "final_freeze": None,
            "controlled_evaluation": {
                "performed": False,
                "reason": "Campaign stopped on terminal fail-closed runtime evidence.",
                "controlled_qualified_claim": False,
            },
            "protected_access": _protected_access(),
            "authority": _AUTHORITY,
        }
        return self._publish_final_report(payload)

    def _publish_final_report(self, payload: dict[str, object]) -> Mapping[str, Any]:
        payload["report_fingerprint"] = fingerprint(payload)
        json_path = self.runtime_root / "final-report.json"
        _write_create_only(json_path, payload)
        _write_create_only_text(
            self.runtime_root / "final-report.md",
            _final_markdown(payload, _sha256_path(json_path)),
        )
        return payload

    def _load_final_report_if_present(self) -> Mapping[str, Any] | None:
        path = self.runtime_root / "final-report.json"
        if not path.exists():
            return None
        value = _read_final_report(path, source_commit=self.source_commit)
        _validate_final_evidence(self.runtime_root, value)
        _write_create_only_text(
            self.runtime_root / "final-report.md",
            _final_markdown(value, _sha256_path(path)),
        )
        return value

    def _result(self, final: Mapping[str, Any]) -> dict[str, object]:
        counts = _mapping(final.get("counts"), "final counts")
        return {
            "program_id": PROGRAM_ID,
            "outcome": final["outcome"],
            "terminal_message": final["terminal_message"],
            "source_commit": self.source_commit,
            "workers": self.workers,
            "cohort_size": counts.get("cohort"),
            "final_freeze": (
                None
                if final.get("final_freeze") is None
                else str((self.runtime_root / "final-freeze.json").resolve())
            ),
            "final_report_json": str((self.runtime_root / "final-report.json").resolve()),
            "final_report_markdown": str((self.runtime_root / "final-report.md").resolve()),
            "authority": _AUTHORITY,
        }


def _run_id(specification: Mapping[str, object]) -> str:
    context = _mapping(specification.get("context"), "run context")
    identity = {key: _text(context, key) for key in ("candidate_id", "period_id", "scenario_id")}
    return f"fedabs001r-{fingerprint(identity)[:24]}"


def _frozen_plan_evidence(plan: Any) -> dict[str, object]:
    return {
        "sha256": plan.sha256,
        "fingerprint": plan.plan_fingerprint,
        "review_sha256": plan.review_sha256,
        "review_fingerprint": plan.review_fingerprint,
        "autonomous_program_sha256": plan.payload["autonomous_program"]["sha256"],
        "autonomous_program_fingerprint": plan.payload["autonomous_program"]["fingerprint"],
        "source_state_sha256": plan.source_state_sha256,
        "source_state_fingerprint": plan.source_state_fingerprint,
        "state_sha256": plan.state_sha256,
        "state_fingerprint": plan.state_fingerprint,
        "calendar_sha256": plan.calendar_sha256,
        "calendar_fingerprint": plan.calendar_fingerprint,
        "source_evidence_sha256": plan.source_evidence_sha256,
        "source_evidence_fingerprint": plan.source_evidence_fingerprint,
        "attestation_sha256": ATTESTATION_SHA256,
        "attestation_fingerprint": ATTESTATION_FINGERPRINT,
    }


def _reservation_id(run_fingerprint: str) -> str:
    return f"fedabs001q-{run_fingerprint[:24]}"


def _neighbor_ids(candidate_id: str) -> tuple[str, ...]:
    match = _NODE_PATTERN.fullmatch(candidate_id)
    if match is None or candidate_id not in _PARENT_IDS:
        raise ValueError("Fed Policy Absorption 001 parent identity differs")
    horizon, floor = int(match.group("horizon")), int(match.group("floor"))
    return (
        f"fedabs-h{horizon - 1:02d}-f{floor:04d}",
        f"fedabs-h{horizon + 1:02d}-f{floor:04d}",
        f"fedabs-h{horizon:02d}-f{floor - 4:04d}",
        f"fedabs-h{horizon:02d}-f{floor + 4:04d}",
    )


def _validate_stage_specifications(specifications: Sequence[Mapping[str, object]]) -> None:
    if not specifications:
        return
    identities: list[tuple[str, str | None, str, str, str]] = []
    for specification in specifications:
        context = _mapping(specification.get("context"), "run context")
        configuration = _mapping(specification.get("configuration"), "run configuration")
        period = _mapping(specification.get("period"), "run period")
        cost = _mapping(specification.get("cost_model"), "run cost model")
        stage = _text(context, "stage")
        base = context.get("base_candidate_id")
        if base is not None and not isinstance(base, str):
            raise ValueError("Fed Policy Absorption 001 base candidate identity differs")
        candidate = _text(context, "candidate_id")
        period_id = _text(context, "period_id")
        scenario = _text(context, "scenario_id")
        if (
            specification.get("schema_version") != RUN_SCHEMA
            or specification.get("program_id") != PROGRAM_ID
            or configuration.get("candidate_id") != candidate
            or period.get("period_id") != period_id
            or cost.get("run_scenario_id") != scenario
            or cost.get("cost_model_scenario_id") != _COST_MODEL_SCENARIO_IDS.get(scenario)
        ):
            raise ValueError("Fed Policy Absorption 001 run specification binding differs")
        identities.append((stage, base, candidate, period_id, scenario))
    if len({_run_id(item) for item in specifications}) != len(specifications):
        raise ValueError("Fed Policy Absorption 001 run specifications collide")
    stages = {item[0] for item in identities}
    if len(stages) != 1:
        raise ValueError("Fed Policy Absorption 001 stage specifications are mixed")
    stage = identities[0][0]
    expected: list[tuple[str, str | None, str, str, str]]
    if stage == "discovery":
        expected = [
            (stage, None, candidate, _PERIOD_IDS[0], scenario)
            for candidate in _PARENT_IDS
            for scenario in ("normal", "zero_cost_diagnostic")
        ]
    elif stage == "walk-forward":
        candidates = tuple(dict.fromkeys(item[2] for item in identities))
        if not 1 <= len(candidates) <= 3 or any(
            candidate not in _PARENT_IDS for candidate in candidates
        ):
            raise ValueError("Fed Policy Absorption 001 walk-forward candidates differ")
        expected = [
            (stage, None, candidate, period, scenario)
            for candidate in candidates
            for period in _PERIOD_IDS[1:]
            for scenario in ("normal", "zero_cost_diagnostic")
        ]
    elif stage == "stress":
        candidates = tuple(dict.fromkeys(item[2] for item in identities))
        if len(candidates) != 1 or candidates[0] not in _PARENT_IDS:
            raise ValueError("Fed Policy Absorption 001 stress candidate differs")
        expected = [
            (stage, None, candidates[0], period, scenario)
            for period in _PERIOD_IDS[1:]
            for scenario in ("stress_a", "stress_b", "normal-delay-2", "normal-delay-3")
        ]
    elif stage == "neighbor":
        bases = tuple(dict.fromkeys(item[1] for item in identities))
        if len(bases) != 1 or bases[0] is None:
            raise ValueError("Fed Policy Absorption 001 neighbor parent differs")
        expected = [
            (stage, bases[0], candidate, period, scenario)
            for candidate in _neighbor_ids(bases[0])
            for period in _PERIOD_IDS[1:]
            for scenario in ("normal", "zero_cost_diagnostic")
        ]
    else:
        raise ValueError("Fed Policy Absorption 001 stage differs")
    if identities != expected:
        raise ValueError("Fed Policy Absorption 001 frozen stage specification order differs")


def _dataset_bindings(payload: Mapping[str, Any]) -> tuple[_DatasetBinding, ...]:
    data = _mapping(payload.get("data"), "plan data")
    values = data.get("dataset_bindings")
    if not isinstance(values, list | tuple) or len(values) != 4:
        raise ValueError("Fed Policy Absorption 001 dataset bindings differ")
    bindings: list[_DatasetBinding] = []
    for index, value in enumerate(values):
        item = _mapping(value, "dataset binding")
        bindings.append(
            _DatasetBinding(
                _text(item, "dataset_id"),
                _text(item, "fingerprint"),
                _text(item, "raw_fingerprint"),
                _timestamp(item.get("allowed_read_start"), "allowed read start"),
                _timestamp(item.get("allowed_read_end"), "allowed read end"),
                "intraday-exposed" if index < 3 else None,
                cast(str | None, item.get("raw_sha256")),
                cast(str | None, item.get("bars_sha256")),
                cast(str | None, item.get("manifest_sha256")),
            )
        )
    result = tuple(bindings)
    if any(left.end >= right.start for left, right in zip(result, result[1:], strict=False)):
        raise ValueError("Fed Policy Absorption 001 dataset ranges overlap")
    return result


def _read_only_dataset_services(
    data_home: Path,
    bindings: Sequence[_DatasetBinding],
) -> Mapping[str, DatasetService]:
    base = data_home.resolve()
    services: dict[Path, DatasetService] = {}
    resolved: dict[str, DatasetService] = {}
    for binding in bindings:
        root = base if binding.data_namespace is None else base / binding.data_namespace
        service = services.get(root)
        if service is None:
            service = DatasetService(StorageLayout(root), read_only=True)
            services[root] = service
        try:
            service.describe(binding.dataset_id)
        except KeyError as error:
            raise ValueError(
                f"Fed Policy Absorption 001 dataset location is missing: {binding.dataset_id}"
            ) from error
        resolved[binding.dataset_id] = service
    return MappingProxyType(resolved)


def _run_dataset_inputs(
    bindings: Sequence[_DatasetBinding], period: FedPolicyAbsorptionPeriod
) -> list[dict[str, object]]:
    inputs: list[dict[str, object]] = []
    for binding in bindings:
        if binding.start > period.evaluation_end or binding.end < period.context_start:
            continue
        evaluation_start = max(binding.start, period.evaluation_start)
        evaluation_end = min(binding.end, period.evaluation_end)
        has_evaluation = evaluation_start <= evaluation_end
        inputs.append(
            {
                "dataset_id": binding.dataset_id,
                "fingerprint": binding.data_fingerprint,
                "raw_fingerprint": binding.raw_fingerprint,
                "read_start": max(binding.start, period.context_start),
                "read_end": min(binding.end, period.evaluation_end),
                "evaluation_read_start": evaluation_start if has_evaluation else None,
                "evaluation_read_end": evaluation_end if has_evaluation else None,
            }
        )
    if not inputs:
        raise ValueError("Fed Policy Absorption 001 run has no dataset input")
    return inputs


def _configuration_summary(configuration: FedPolicyAbsorptionConfiguration) -> dict[str, object]:
    return {
        "candidate_id": configuration.candidate_id,
        "strategy_id": STRATEGY_VERSION,
        "observation_horizon_bars": configuration.observation_horizon_bars,
        "minimum_joint_reaction_bps": configuration.minimum_joint_reaction_bps,
        "neighbor_ids": configuration.neighbor_ids,
    }


def _screen_candidate_id(item: Mapping[str, object]) -> str:
    return _text(_mapping(item.get("candidate"), "candidate"), "candidate_id")


def _select_eligible(
    ledger: Sequence[Mapping[str, object]],
    cap: int,
    *,
    key: Callable[[Mapping[str, object]], tuple[Any, ...]],
) -> tuple[str, ...]:
    # Frozen parent order is the only selection order.  Results never rank candidates.
    del key
    return tuple(_screen_candidate_id(item) for item in ledger if item.get("eligible") is True)[
        :cap
    ]


def _run_evidence(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "run_id": row["run_id"],
        "reservation_id": row["reservation_id"],
        "run_fingerprint": row["run_fingerprint"],
        "stage": row["stage"],
        "base_candidate_id": row["base_candidate_id"],
        "candidate_id": row["candidate_id"],
        "period_id": row["period_id"],
        "scenario_id": row["scenario_id"],
        "status": row["status"],
        "attempt_count": row["attempt_count"],
        "report_path": row["report_path"],
        "report_sha256": row["report_sha256"],
        "report_fingerprint": row["report_fingerprint"],
        "failure_class": row["failure_class"],
        "failure_reason": row["failure_reason"],
    }


def _attempt_summary(
    runs: Sequence[Mapping[str, object]],
    histories: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    attempts = [
        attempt
        for history in histories
        for attempt in cast(Sequence[Mapping[str, object]], history["attempts"])
    ]
    events = [
        event
        for attempt in attempts
        for event in cast(Sequence[Mapping[str, object]], attempt["events"])
    ]
    return {
        "total_attempts": len(attempts),
        "retried_run_count": sum(cast(int, row["attempt_count"]) > 1 for row in runs),
        "infrastructure_interruption_count": sum(
            event.get("kind") == "infrastructure-interruption" for event in events
        ),
        "candidate_failure_count": sum(row.get("failure_class") == "candidate" for row in runs),
        "data_failure_count": sum(row.get("failure_class") == "data" for row in runs),
        "calendar_failure_count": sum(row.get("failure_class") == "calendar" for row in runs),
        "publication_conflict_count": sum(
            row.get("failure_class") == "publication-conflict" for row in runs
        ),
        "canonical_report_invalid_count": sum(
            row.get("failure_class") == "canonical-report-invalid" for row in runs
        ),
        "terminal_infrastructure_failure_count": sum(
            row.get("failure_class") == "infrastructure" for row in runs
        ),
        "maximum_attempts_for_one_run": max(
            (cast(int, row["attempt_count"]) for row in runs), default=0
        ),
    }


def _protected_access() -> dict[str, bool]:
    return {
        "june_market_data_or_results": False,
        "intraday_v3_data_or_results": False,
        "daily_2018_2019_data_or_results": False,
        "protected_campaign_results": False,
        "paper_broker_or_live_state": False,
        "strategic_allocation_21": False,
        "live_market_or_execution_data": False,
        "federal_reserve_release_contents": False,
        "new_price_or_volume_acquisition": False,
        "partial_result_adaptation": False,
        "campaign_4": False,
    }


def _synthetic_equivalence_bars() -> tuple[OHLCVBar, ...]:
    indices: dict[date, int] = {}
    bars: list[OHLCVBar] = []
    for timestamp in expected_bar_timestamps(
        _EQUIVALENCE_PERIOD.context_start,
        _EQUIVALENCE_PERIOD.evaluation_end,
        Timeframe.FIVE_MINUTES,
    ):
        day = timestamp.date()
        index = indices.get(day, 0)
        indices[day] = index + 1
        for symbol in _SYMBOLS:
            base = Decimal("100") if symbol == _SPY else Decimal("200")
            if day == date(2026, 1, 7) or index <= 53:
                opening = closing = base
            elif index < 75:
                opening = closing = base * Decimal("1.005")
            else:
                opening = closing = base * Decimal("1.01")
            bars.append(
                OHLCVBar(
                    symbol,
                    timestamp,
                    opening,
                    max(opening, closing),
                    min(opening, closing),
                    closing,
                    1_000,
                )
            )
    return tuple(bars)


def _run_report(
    specification: Mapping[str, object],
    result: Exposed002ReplayResult,
    period: FedPolicyAbsorptionPeriod,
    events: tuple[FedPolicyAbsorptionEvent, ...],
    bars: Sequence[OHLCVBar],
) -> dict[str, object]:
    with localcontext(_CONTEXT):
        raw_configuration = _mapping(specification.get("configuration"), "report configuration")
        configuration = FedPolicyAbsorptionConfiguration(
            _text(raw_configuration, "candidate_id"),
            _required_integer(
                raw_configuration.get("observation_horizon_bars"), "observation horizon"
            ),
            _required_metric(raw_configuration, "minimum_joint_reaction_bps"),
            (),
        )
        context = _mapping(specification.get("context"), "report context")
        scenario_id = _text(context, "scenario_id")
        cost = _mapping(specification.get("cost_model"), "report cost model")
        delay = _required_integer(cost.get("execution_delay_bars"), "execution delay")
        strategy = build_intraday_fed_policy_absorption_001_strategy(
            configuration, _event_sessions_for_period(events, period)
        )
        eligible = tuple(
            event
            for event in sorted(events, key=lambda item: (item.scheduled_utc, item.event_id))
            if period.evaluation_start.date()
            <= date.fromisoformat(event.xnys_session)
            <= period.evaluation_end.date()
        )
        if len(eligible) != period.eligible_event_count:
            raise ValueError("Fed Policy Absorption 001 period event count differs")
        event_days = {date.fromisoformat(event.xnys_session) for event in eligible}
        if len(event_days) != len(eligible):
            raise ValueError("Fed Policy Absorption 001 event sessions collide")
        evaluation_fills = tuple(
            fill
            for fill in result.fills
            if period.evaluation_start <= fill.fill_timestamp <= period.evaluation_end
        )
        evaluation_trades = tuple(
            trade
            for trade in result.round_trips
            if period.evaluation_start <= trade.entry_timestamp
            and trade.exit_timestamp <= period.evaluation_end
        )
        if any(_account_day(fill.fill_timestamp) not in event_days for fill in evaluation_fills):
            raise ValueError("Fed Policy Absorption 001 has a non-event fill")
        if any(
            _account_day(trade.entry_timestamp) != _account_day(trade.exit_timestamp)
            or _account_day(trade.entry_timestamp) not in event_days
            for trade in evaluation_trades
        ):
            raise ValueError("Fed Policy Absorption 001 has an invalid event round trip")
        session_days = tuple(expected_sessions(period.evaluation_start, period.evaluation_end))
        points_by_day = {
            day: tuple(
                point for point in result.equity_curve if _account_day(point.timestamp) == day
            )
            for day in session_days
        }
        if len(session_days) != period.session_count or any(
            len(points) != 78 for points in points_by_day.values()
        ):
            raise ValueError("Fed Policy Absorption 001 evaluation session curve differs")
        fees_by_day = {
            date.fromisoformat(item.account_day): item
            for item in result.fee_ledger
            if date.fromisoformat(item.account_day) in set(session_days)
        }
        if set(fees_by_day) != set(session_days):
            raise ValueError("Fed Policy Absorption 001 daily fee ledger differs")

        causal_rows: list[dict[str, object]] = []
        ledger: list[dict[str, object]] = []
        for event in eligible:
            day = date.fromisoformat(event.xnys_session)
            session = _event_session_bars(bars, day)
            signal = strategy.signal(session)
            terminal = 53 + configuration.observation_horizon_bars
            decision_timestamp = session[_SPY][terminal].timestamp + Timeframe.FIVE_MINUTES.duration
            causal = {
                "event_id": event.event_id,
                "publication_class": event.publication_class,
                "scheduled_local": event.scheduled_local.isoformat(),
                "scheduled_utc": event.scheduled_utc,
                "xnys_session": event.xnys_session,
                "reference_index_53": 53,
                "spy_reference_close": session[_SPY][53].close,
                "qqq_reference_close": session[_QQQ][53].close,
                "terminal_index": terminal,
                "spy_terminal_close": session[_SPY][terminal].close,
                "qqq_terminal_close": session[_QQQ][terminal].close,
                "spy_reaction_bps": signal.spy_reaction_bps,
                "qqq_reaction_bps": signal.qqq_reaction_bps,
                "activation": signal.active,
                "decision_index": terminal,
                "decision_timestamp": decision_timestamp,
                "no_signal_reason": signal.no_signal_reason,
            }
            causal_rows.append(causal)
            day_fills = tuple(
                fill for fill in evaluation_fills if _account_day(fill.fill_timestamp) == day
            )
            day_trades = tuple(
                trade for trade in evaluation_trades if _account_day(trade.entry_timestamp) == day
            )
            daily = fees_by_day[day]
            points = points_by_day[day]
            pre_points = tuple(point for point in points if point.timestamp == decision_timestamp)
            if len(pre_points) != 1:
                raise ValueError("Fed Policy Absorption 001 pre-event equity point differs")
            pre_point, end_point = pre_points[0], points[-1]
            if (
                pre_point.cash != pre_point.equity
                or any(value != _ZERO for _symbol, value in pre_point.positions)
                or end_point.cash != end_point.equity
                or any(value != _ZERO for _symbol, value in end_point.positions)
            ):
                raise ValueError("Fed Policy Absorption 001 event exposure differs")
            fee_record = {
                "account_day": daily.account_day,
                "sec": daily.charges.sec,
                "taf": daily.charges.taf,
                "cat": daily.charges.cat,
                "total": daily.charges.total,
                "by_symbol": {symbol.value: value for symbol, value in daily.by_symbol},
                "fills_fingerprint": daily.fills_fingerprint,
            }
            common: dict[str, object] = {
                **causal,
                "period_id": period.period_id,
                "pre_event_equity": pre_point.equity,
                "pre_event_cash": pre_point.cash,
                "entry_decision_index": terminal,
                "entry_decision_timestamp": decision_timestamp,
                "exit_decision_index": 74,
                "exit_decision_timestamp": (
                    session[_SPY][74].timestamp + Timeframe.FIVE_MINUTES.duration
                ),
                "intended_entry_fill_index": terminal + delay if signal.active else None,
                "intended_exit_fill_index": 74 + delay if signal.active else None,
                "regulatory_fee_record": fee_record,
            }
            if not signal.active:
                if day_fills or day_trades or daily.charges.total != _ZERO:
                    raise ValueError(
                        "Fed Policy Absorption 001 inactive event has execution evidence"
                    )
                if end_point.equity != pre_point.equity:
                    raise ValueError("Fed Policy Absorption 001 inactive equity changed")
                ledger.append(
                    {
                        **common,
                        "entry_fill_count": 0,
                        "exit_fill_count": 0,
                        "fill_count": 0,
                        "symbol_round_trip_count": 0,
                        "legs": {},
                        "gross_event_return": _ZERO,
                        "spread_adjusted_event_return": _ZERO,
                        "regulatory_fees": _ZERO,
                        "net_event_return": _ZERO,
                        "gross_event_profit_loss": _ZERO,
                        "spread_adjusted_event_profit_loss": _ZERO,
                        "net_event_profit_loss": _ZERO,
                        "positive_contribution": _ZERO,
                        "end_event_cash": end_point.cash,
                        "end_event_exposure": {
                            "SPY": _ZERO,
                            "QQQ": _ZERO,
                            "aggregate": _ZERO,
                        },
                        "flat_at_close": True,
                        "missed_fill": False,
                        "accounting_identity_results": {
                            "inactive_equity_unchanged": True,
                            "inactive_execution_absent": True,
                            "flat_at_close": True,
                        },
                    }
                )
                continue
            entries = tuple(fill for fill in day_fills if fill.quantity > 0)
            exits = tuple(fill for fill in day_fills if fill.quantity < 0)
            if (
                len(entries) != 2
                or len(exits) != 2
                or len(day_trades) != 2
                or tuple(fill.symbol for fill in entries) != _SYMBOLS
                or tuple(fill.symbol for fill in exits) != _SYMBOLS
                or {trade.symbol for trade in day_trades} != set(_SYMBOLS)
            ):
                raise ValueError("Fed Policy Absorption 001 atomic joint fills differ")
            entry_by_symbol = {fill.symbol: fill for fill in entries}
            exit_by_symbol = {fill.symbol: fill for fill in exits}
            trade_by_symbol = {trade.symbol: trade for trade in day_trades}
            expected_entry_timestamp = session[_SPY][terminal + delay].timestamp
            expected_exit_timestamp = session[_SPY][74 + delay].timestamp
            if any(
                entry_by_symbol[symbol].decision_timestamp != decision_timestamp
                or entry_by_symbol[symbol].fill_timestamp != expected_entry_timestamp
                or exit_by_symbol[symbol].decision_timestamp
                != session[_SPY][74].timestamp + Timeframe.FIVE_MINUTES.duration
                or exit_by_symbol[symbol].fill_timestamp != expected_exit_timestamp
                for symbol in _SYMBOLS
            ):
                raise ValueError("Fed Policy Absorption 001 fill chronology differs")
            legs: dict[str, object] = {}
            gross_return = _ZERO
            spread_return = _ZERO
            for symbol in _SYMBOLS:
                entry, exit_fill = entry_by_symbol[symbol], exit_by_symbol[symbol]
                trade = trade_by_symbol[symbol]
                raw_return = exit_fill.market_price / entry.market_price - _ONE
                execution_return = exit_fill.fill_price / entry.fill_price - _ONE
                if (
                    exit_fill.quantity != -entry.quantity
                    or trade.trade_id != entry.trade_id
                    or trade.trade_id != exit_fill.trade_id
                    or trade.quantity != entry.quantity
                    or trade.entry_market_price != entry.market_price
                    or trade.exit_market_price != exit_fill.market_price
                    or trade.entry_fill_price != entry.fill_price
                    or trade.exit_fill_price != exit_fill.fill_price
                    or entry.gross_notional != pre_point.equity * _HALF
                    or exit_fill.gross_notional != abs(exit_fill.quantity) * exit_fill.fill_price
                ):
                    raise ValueError("Fed Policy Absorption 001 leg accounting differs")
                gross_return += _HALF * raw_return
                spread_return += _HALF * execution_return
                legs[symbol.value] = {
                    "trade_id": trade.trade_id,
                    "entry": {
                        "decision_timestamp": entry.decision_timestamp,
                        "fill_timestamp": entry.fill_timestamp,
                        "stored_provider_adjusted_raw_open": entry.market_price,
                        "adverse_slippage": entry.adverse_slippage,
                        "modeled_execution_price": entry.fill_price,
                        "quantity": entry.quantity,
                        "notional": entry.gross_notional,
                        "sequence": entry.sequence,
                    },
                    "exit": {
                        "decision_timestamp": exit_fill.decision_timestamp,
                        "fill_timestamp": exit_fill.fill_timestamp,
                        "stored_provider_adjusted_raw_open": exit_fill.market_price,
                        "adverse_slippage": exit_fill.adverse_slippage,
                        "modeled_execution_price": exit_fill.fill_price,
                        "quantity": exit_fill.quantity,
                        "notional": exit_fill.gross_notional,
                        "sequence": exit_fill.sequence,
                    },
                    "raw_return": raw_return,
                    "execution_return": execution_return,
                    "gross_portfolio_contribution": _HALF * raw_return,
                    "spread_adjusted_portfolio_contribution": _HALF * execution_return,
                    "regulatory_fee_allocation": dict(daily.by_symbol)[symbol],
                }
            net_return = spread_return - daily.charges.total / pre_point.equity
            expected_end = pre_point.equity * (_ONE + net_return)
            if end_point.equity != expected_end:
                raise ValueError("Fed Policy Absorption 001 ending equity does not reconcile")
            ledger.append(
                {
                    **common,
                    "entry_fill_count": 2,
                    "exit_fill_count": 2,
                    "fill_count": 4,
                    "symbol_round_trip_count": 2,
                    "legs": legs,
                    "gross_event_return": gross_return,
                    "spread_adjusted_event_return": spread_return,
                    "regulatory_fees": daily.charges.total,
                    "net_event_return": net_return,
                    "gross_event_profit_loss": pre_point.equity * gross_return,
                    "spread_adjusted_event_profit_loss": pre_point.equity * spread_return,
                    "net_event_profit_loss": end_point.equity - pre_point.equity,
                    "positive_contribution": max(net_return, _ZERO),
                    "end_event_cash": end_point.cash,
                    "end_event_exposure": {
                        "SPY": _ZERO,
                        "QQQ": _ZERO,
                        "aggregate": _ZERO,
                    },
                    "flat_at_close": True,
                    "missed_fill": False,
                    "accounting_identity_results": {
                        "atomic_entry": True,
                        "atomic_exit": True,
                        "half_weight_entry_notionals": True,
                        "net_return": True,
                        "ending_equity": True,
                        "fee_aggregation": sum(dict(daily.by_symbol).values(), _ZERO)
                        == daily.charges.total,
                        "flat_at_close": True,
                    },
                }
            )
        cross_scenario_trace = {
            "schema_version": "intraday-fed-policy-absorption-cross-scenario-trace-v1",
            "campaign_id": PROGRAM_ID,
            "candidate_id": configuration.candidate_id,
            "horizon": configuration.observation_horizon_bars,
            "floor": configuration.minimum_joint_reaction_bps,
            "period_id": period.period_id,
            "source_commit": specification.get("source_commit"),
            "attestation_sha256": specification.get("attestation_sha256"),
            "attestation_fingerprint": specification.get("attestation_fingerprint"),
            "autonomous_program_sha256": specification.get("autonomous_program_sha256"),
            "autonomous_program_fingerprint": specification.get("autonomous_program_fingerprint"),
            "state_sha256": specification.get("state_sha256"),
            "state_fingerprint": specification.get("state_fingerprint"),
            "calendar_sha256": specification.get("calendar_sha256"),
            "calendar_fingerprint": specification.get("calendar_fingerprint"),
            "source_evidence_sha256": specification.get("source_evidence_sha256"),
            "source_evidence_fingerprint": specification.get("source_evidence_fingerprint"),
            "dataset_ids": [
                _text(_mapping(item, "dataset input"), "dataset_id")
                for item in _mapping_items(specification.get("dataset_inputs"), "dataset inputs")
            ],
            "plan_sha256": specification.get("plan_sha256"),
            "plan_fingerprint": specification.get("plan_fingerprint"),
            "events": causal_rows,
        }
        cross_scenario_trace_hash = hashlib.sha256(
            canonical_json(cross_scenario_trace).encode()
        ).hexdigest()
        metrics = _metrics_from_event_ledger(
            ledger,
            initial_cash=result.initial_cash,
            expected_ending_equity=points_by_day[session_days[-1]][-1].equity,
            validate_stored_equity=True,
        )
        metrics.update(
            {
                "session_count": period.session_count,
                "period_count": 1,
                "benchmark_references": _benchmark_references(bars, period),
            }
        )
        execution_trace = {
            "schema_version": "intraday-fed-policy-absorption-execution-trace-v1",
            "campaign_id": PROGRAM_ID,
            "candidate_id": configuration.candidate_id,
            "period_id": period.period_id,
            "cross_scenario_trace_hash": cross_scenario_trace_hash,
            "run_scenario_id": scenario_id,
            "cost_model_scenario_id": cost.get("cost_model_scenario_id"),
            "cost_model_sha256": cost.get("sha256"),
            "cost_model_fingerprint": cost.get("fingerprint"),
            "execution_delay_bars": delay,
            "events": ledger,
            "account_day_fee_aggregation": [row["regulatory_fee_record"] for row in ledger],
            "metrics": metrics,
            "accounting_identity_results": metrics["accounting_identity_results"],
        }
        execution_trace_hash = hashlib.sha256(canonical_json(execution_trace).encode()).hexdigest()
        details = {
            "cross_scenario_trace": cross_scenario_trace,
            "cross_scenario_trace_hash": cross_scenario_trace_hash,
            "execution_trace": execution_trace,
            "execution_trace_hash": execution_trace_hash,
            "event_ledger": ledger,
            "decision_trace_fingerprint": fingerprint(result.decisions),
            "transition_trace_fingerprint": fingerprint(result.transitions),
            "fill_trace_fingerprint": fingerprint(evaluation_fills),
            "round_trip_fingerprint": fingerprint(evaluation_trades),
            "daily_fee_ledger_fingerprint": fingerprint(
                tuple(fees_by_day[day] for day in session_days)
            ),
            "engine_artifact_fingerprint": result.artifact_fingerprint,
        }
        payload: dict[str, object] = {
            "schema_version": RUN_REPORT_SCHEMA,
            "program_id": PROGRAM_ID,
            "run_id": _run_id(specification),
            "specification": specification,
            "specification_fingerprint": fingerprint(specification),
            "metrics": metrics,
            "details": details,
            "execution_evidence": {
                "cross_scenario_trace_hash": cross_scenario_trace_hash,
                "execution_trace_hash": execution_trace_hash,
            },
            **{key: specification[key] for key in _REPORT_IDENTITY_FIELDS if key in specification},
            "authority": _AUTHORITY,
        }
        canonical_payload = cast(dict[str, object], canonicalize(payload))
        canonical_payload["report_fingerprint"] = fingerprint(canonical_payload)
        _validate_run_report_payload(canonical_payload, events)
        return canonical_payload


def _validate_run_report_payload(
    report: Mapping[str, Any], events: Sequence[FedPolicyAbsorptionEvent]
) -> None:
    with localcontext(_CONTEXT):
        _validate_run_report_payload_exact(report)
        _validate_run_report_event_sequence(report, events)


def _validate_run_report_event_sequence(
    report: Mapping[str, Any], events: Sequence[FedPolicyAbsorptionEvent]
) -> None:
    specification = _mapping(report.get("specification"), "run specification")
    context = _mapping(specification.get("context"), "run context")
    period_id = _required_text(context.get("period_id"), "run period ID")
    expected = tuple(
        (
            event.event_id,
            event.publication_class,
            event.scheduled_local.isoformat(),
            canonicalize(event.scheduled_utc),
            event.xnys_session,
        )
        for event in events
        if event.period_id == period_id
    )
    details = _mapping(report.get("details"), "run details")
    cross = _mapping(details.get("cross_scenario_trace"), "cross-scenario trace")
    raw_cross_events = cross.get("events")
    raw_ledger = details.get("event_ledger")
    if not isinstance(raw_cross_events, list) or not isinstance(raw_ledger, list):
        raise ValueError("Fed Policy Absorption 001 trace events differ")
    fields = (
        "event_id",
        "publication_class",
        "scheduled_local",
        "scheduled_utc",
        "xnys_session",
    )
    cross_events = tuple(_mapping(item, "cross-scenario event") for item in raw_cross_events)
    ledger = tuple(_mapping(item, "event ledger row") for item in raw_ledger)
    if (
        tuple(tuple(row.get(key) for key in fields) for row in cross_events) != expected
        or tuple(tuple(row.get(key) for key in fields) for row in ledger) != expected
        or any(row.get("period_id") != period_id for row in ledger)
    ):
        raise ValueError("Fed Policy Absorption 001 frozen calendar event sequence differs")


def _validate_run_report_payload_exact(report: Mapping[str, Any]) -> None:
    specification = _mapping(report.get("specification"), "run specification")
    context = _mapping(specification.get("context"), "run context")
    cost = _mapping(specification.get("cost_model"), "run cost model")
    period = _mapping(specification.get("period"), "run period")
    configuration = _mapping(specification.get("configuration"), "run configuration")
    metrics = _report_metrics(report)
    details = _mapping(report.get("details"), "run details")
    evidence = _mapping(report.get("execution_evidence"), "execution evidence")
    stored = _required_text(report.get("report_fingerprint"), "report fingerprint")
    unsigned = dict(report)
    del unsigned["report_fingerprint"]
    expected_report_keys = {
        "schema_version",
        "program_id",
        "run_id",
        "specification",
        "specification_fingerprint",
        "metrics",
        "details",
        "execution_evidence",
        *_REPORT_IDENTITY_FIELDS,
        "authority",
        "report_fingerprint",
    }
    if (
        set(report) != expected_report_keys
        or report.get("schema_version") != RUN_REPORT_SCHEMA
        or report.get("program_id") != PROGRAM_ID
        or specification.get("schema_version") != RUN_SCHEMA
        or specification.get("program_id") != PROGRAM_ID
        or report.get("run_id") != _run_id(specification)
        or report.get("specification_fingerprint") != fingerprint(specification)
        or stored != fingerprint(unsigned)
        or report.get("authority") != _AUTHORITY
        or any(report.get(key) != specification.get(key) for key in _REPORT_IDENTITY_FIELDS)
        or specification.get("cost_model_sha256") != cost.get("sha256")
        or specification.get("cost_model_fingerprint") != cost.get("fingerprint")
        or cost.get("run_scenario_id") != context.get("scenario_id")
        or cost.get("cost_model_scenario_id")
        != _COST_MODEL_SCENARIO_IDS.get(cast(str, context.get("scenario_id")))
        or configuration.get("candidate_id") != context.get("candidate_id")
        or period.get("period_id") != context.get("period_id")
    ):
        raise ValueError("Fed Policy Absorption 001 report binding differs")
    if set(evidence) != {"cross_scenario_trace_hash", "execution_trace_hash"}:
        raise ValueError("Fed Policy Absorption 001 execution evidence differs")
    expected_detail_keys = {
        "cross_scenario_trace",
        "cross_scenario_trace_hash",
        "execution_trace",
        "execution_trace_hash",
        "event_ledger",
        "decision_trace_fingerprint",
        "transition_trace_fingerprint",
        "fill_trace_fingerprint",
        "round_trip_fingerprint",
        "daily_fee_ledger_fingerprint",
        "engine_artifact_fingerprint",
    }
    if set(details) != expected_detail_keys:
        raise ValueError("Fed Policy Absorption 001 report details differ")
    cross = _mapping(details.get("cross_scenario_trace"), "cross-scenario trace")
    execution = _mapping(details.get("execution_trace"), "execution trace")
    cross_hash = hashlib.sha256(canonical_json(cross).encode()).hexdigest()
    execution_hash = hashlib.sha256(canonical_json(execution).encode()).hexdigest()
    if (
        details.get("cross_scenario_trace_hash") != cross_hash
        or evidence.get("cross_scenario_trace_hash") != cross_hash
        or details.get("execution_trace_hash") != execution_hash
        or evidence.get("execution_trace_hash") != execution_hash
        or "cross_scenario_trace_hash" in cross
        or "execution_trace_hash" in execution
    ):
        raise ValueError("Fed Policy Absorption 001 trace hash differs")

    expected_cross_keys = {
        "schema_version",
        "campaign_id",
        "candidate_id",
        "horizon",
        "floor",
        "period_id",
        "source_commit",
        "attestation_sha256",
        "attestation_fingerprint",
        "autonomous_program_sha256",
        "autonomous_program_fingerprint",
        "state_sha256",
        "state_fingerprint",
        "calendar_sha256",
        "calendar_fingerprint",
        "source_evidence_sha256",
        "source_evidence_fingerprint",
        "dataset_ids",
        "plan_sha256",
        "plan_fingerprint",
        "events",
    }
    cross_identity = {
        "candidate_id": context.get("candidate_id"),
        "horizon": configuration.get("observation_horizon_bars"),
        "floor": configuration.get("minimum_joint_reaction_bps"),
        "period_id": context.get("period_id"),
        "source_commit": specification.get("source_commit"),
        "attestation_sha256": specification.get("attestation_sha256"),
        "attestation_fingerprint": specification.get("attestation_fingerprint"),
        "autonomous_program_sha256": specification.get("autonomous_program_sha256"),
        "autonomous_program_fingerprint": specification.get("autonomous_program_fingerprint"),
        "state_sha256": specification.get("state_sha256"),
        "state_fingerprint": specification.get("state_fingerprint"),
        "calendar_sha256": specification.get("calendar_sha256"),
        "calendar_fingerprint": specification.get("calendar_fingerprint"),
        "source_evidence_sha256": specification.get("source_evidence_sha256"),
        "source_evidence_fingerprint": specification.get("source_evidence_fingerprint"),
        "plan_sha256": specification.get("plan_sha256"),
        "plan_fingerprint": specification.get("plan_fingerprint"),
    }
    dataset_ids = [
        _text(item, "dataset_id")
        for item in _mapping_items(specification.get("dataset_inputs"), "dataset inputs")
    ]
    if (
        set(cross) != expected_cross_keys
        or cross.get("schema_version") != "intraday-fed-policy-absorption-cross-scenario-trace-v1"
        or cross.get("campaign_id") != PROGRAM_ID
        or any(
            canonicalize(cross.get(key)) != canonicalize(value)
            for key, value in cross_identity.items()
        )
        or cross.get("dataset_ids") != dataset_ids
    ):
        raise ValueError("Fed Policy Absorption 001 cross-scenario trace binding differs")
    raw_cross_events = cross.get("events")
    raw_ledger = details.get("event_ledger")
    if not isinstance(raw_cross_events, list) or not isinstance(raw_ledger, list):
        raise ValueError("Fed Policy Absorption 001 trace events differ")
    cross_events = tuple(_mapping(item, "cross-scenario event") for item in raw_cross_events)
    ledger = tuple(_mapping(item, "event ledger row") for item in raw_ledger)
    cross_event_keys = {
        "event_id",
        "publication_class",
        "scheduled_local",
        "scheduled_utc",
        "xnys_session",
        "reference_index_53",
        "spy_reference_close",
        "qqq_reference_close",
        "terminal_index",
        "spy_terminal_close",
        "qqq_terminal_close",
        "spy_reaction_bps",
        "qqq_reaction_bps",
        "activation",
        "decision_index",
        "decision_timestamp",
        "no_signal_reason",
    }
    if len(cross_events) != len(ledger):
        raise ValueError("Fed Policy Absorption 001 trace event count differs")
    horizon = _required_integer(configuration.get("observation_horizon_bars"), "horizon")
    floor = _required_metric(configuration, "minimum_joint_reaction_bps")
    delay = _required_integer(cost.get("execution_delay_bars"), "execution delay")
    for causal, row in zip(cross_events, ledger, strict=True):
        if set(causal) != cross_event_keys or any(
            canonicalize(row.get(key)) != canonicalize(value) for key, value in causal.items()
        ):
            raise ValueError("Fed Policy Absorption 001 causal ledger identity differs")
        spy_reaction = _required_metric(causal, "spy_reaction_bps")
        qqq_reaction = _required_metric(causal, "qqq_reaction_bps")
        active = spy_reaction >= floor and qqq_reaction >= floor
        reason = (
            None
            if active
            else "both-below-floor"
            if spy_reaction < floor and qqq_reaction < floor
            else "spy-below-floor"
            if spy_reaction < floor
            else "qqq-below-floor"
        )
        terminal = 53 + horizon
        decision = _utc_timestamp(causal.get("decision_timestamp"), "decision timestamp")
        entry_fill = terminal + delay if active else None
        exit_fill = 74 + delay if active else None
        if (
            causal.get("reference_index_53") != 53
            or causal.get("terminal_index") != terminal
            or causal.get("decision_index") != terminal
            or causal.get("activation") is not active
            or causal.get("no_signal_reason") != reason
            or row.get("entry_decision_index") != terminal
            or row.get("entry_decision_timestamp") != causal.get("decision_timestamp")
            or row.get("exit_decision_index") != 74
            or row.get("intended_entry_fill_index") != entry_fill
            or row.get("intended_exit_fill_index") != exit_fill
        ):
            raise ValueError("Fed Policy Absorption 001 causal event semantics differ")
        if active:
            legs = _mapping(row.get("legs"), "event legs")
            for symbol in ("SPY", "QQQ"):
                leg = _mapping(legs.get(symbol), "event leg")
                entry = _mapping(leg.get("entry"), "entry fill")
                exit_fill_record = _mapping(leg.get("exit"), "exit fill")
                entry_quantity = _required_metric(entry, "quantity")
                exit_quantity = _required_metric(exit_fill_record, "quantity")
                entry_price = _required_metric(entry, "modeled_execution_price")
                exit_price = _required_metric(exit_fill_record, "modeled_execution_price")
                entry_open = _required_metric(entry, "stored_provider_adjusted_raw_open")
                exit_open = _required_metric(exit_fill_record, "stored_provider_adjusted_raw_open")
                if (
                    entry_quantity <= _ZERO
                    or exit_quantity != -entry_quantity
                    or _required_metric(entry, "notional")
                    != _HALF * _required_metric(row, "pre_event_equity")
                    or _required_metric(exit_fill_record, "notional") != -exit_quantity * exit_price
                    or _required_metric(leg, "raw_return") != exit_open / entry_open - _ONE
                    or _required_metric(leg, "execution_return") != exit_price / entry_price - _ONE
                    or _required_metric(leg, "gross_portfolio_contribution")
                    != _HALF * _required_metric(leg, "raw_return")
                    or _required_metric(leg, "spread_adjusted_portfolio_contribution")
                    != _HALF * _required_metric(leg, "execution_return")
                    or _utc_timestamp(entry.get("decision_timestamp"), "entry decision") != decision
                    or _utc_timestamp(entry.get("fill_timestamp"), "entry fill")
                    != decision + Timeframe.FIVE_MINUTES.duration * (delay - 1)
                    or _utc_timestamp(exit_fill_record.get("fill_timestamp"), "exit fill")
                    != _utc_timestamp(row.get("exit_decision_timestamp"), "exit decision")
                    + Timeframe.FIVE_MINUTES.duration * (delay - 1)
                ):
                    raise ValueError("Fed Policy Absorption 001 event leg semantics differ")

    expected_execution_keys = {
        "schema_version",
        "campaign_id",
        "candidate_id",
        "period_id",
        "cross_scenario_trace_hash",
        "run_scenario_id",
        "cost_model_scenario_id",
        "cost_model_sha256",
        "cost_model_fingerprint",
        "execution_delay_bars",
        "events",
        "account_day_fee_aggregation",
        "metrics",
        "accounting_identity_results",
    }
    if (
        set(execution) != expected_execution_keys
        or execution.get("schema_version") != "intraday-fed-policy-absorption-execution-trace-v1"
        or execution.get("campaign_id") != PROGRAM_ID
        or execution.get("candidate_id") != context.get("candidate_id")
        or execution.get("period_id") != context.get("period_id")
        or execution.get("cross_scenario_trace_hash") != cross_hash
        or execution.get("run_scenario_id") != context.get("scenario_id")
        or execution.get("cost_model_scenario_id") != cost.get("cost_model_scenario_id")
        or execution.get("cost_model_sha256") != specification.get("cost_model_sha256")
        or execution.get("cost_model_fingerprint") != specification.get("cost_model_fingerprint")
        or execution.get("execution_delay_bars") != delay
        or canonicalize(execution.get("events")) != canonicalize(raw_ledger)
        or canonicalize(execution.get("metrics")) != canonicalize(metrics)
        or canonicalize(execution.get("accounting_identity_results"))
        != canonicalize(metrics.get("accounting_identity_results"))
        or canonicalize(execution.get("account_day_fee_aggregation"))
        != canonicalize([row["regulatory_fee_record"] for row in ledger])
    ):
        raise ValueError("Fed Policy Absorption 001 execution trace differs")
    initial_cash = _required_metric(metrics, "initial_cash")
    ending_equity = _required_metric(metrics, "ending_equity")
    recomputed = _metrics_from_event_ledger(
        ledger,
        initial_cash=initial_cash,
        expected_ending_equity=ending_equity,
        validate_stored_equity=True,
    )
    expected_metric_keys = {
        *recomputed,
        "session_count",
        "period_count",
        "benchmark_references",
    }
    benchmark = _mapping(metrics.get("benchmark_references"), "benchmark references")
    for key in benchmark:
        _required_metric(benchmark, key)
    if (
        set(metrics) != expected_metric_keys
        or any(
            canonicalize(metrics.get(key)) != canonicalize(value)
            for key, value in recomputed.items()
        )
        or _required_integer(metrics.get("session_count"), "session count")
        != _required_integer(period.get("session_count"), "period session count")
        or _required_integer(metrics.get("period_count"), "period count") != 1
        or set(benchmark) != {"cash", "spy_continuous", "qqq_continuous", "fixed_50_50_continuous"}
    ):
        raise ValueError("Fed Policy Absorption 001 report metrics differ")
    if _required_integer(
        metrics.get("eligible_event_count"), "eligible event count"
    ) != _required_integer(
        period.get("eligible_event_count"), "period eligible event count"
    ) or len(ledger) != _required_integer(metrics.get("eligible_event_count"), "eligible events"):
        raise ValueError("Fed Policy Absorption 001 report event count differs")


def _benchmark_references(
    bars: Sequence[OHLCVBar], period: FedPolicyAbsorptionPeriod
) -> dict[str, Decimal]:
    returns: dict[str, Decimal] = {}
    for symbol in (Symbol("QQQ"), Symbol("SPY")):
        evaluation = tuple(
            sorted(
                (
                    bar
                    for bar in bars
                    if bar.symbol == symbol
                    and period.evaluation_start <= bar.timestamp <= period.evaluation_end
                ),
                key=lambda bar: bar.timestamp,
            )
        )
        if (
            not evaluation
            or evaluation[0].timestamp != period.evaluation_start
            or evaluation[-1].timestamp != period.evaluation_end
        ):
            raise ValueError("Fed Policy Absorption 001 benchmark evaluation bars differ")
        returns[symbol.value] = evaluation[-1].close / evaluation[0].open - Decimal("1")
    return {
        "cash": _ZERO,
        "spy_continuous": returns["SPY"],
        "qqq_continuous": returns["QQQ"],
        "fixed_50_50_continuous": (returns["SPY"] + returns["QQQ"]) / Decimal("2"),
    }


def _metrics_from_event_ledger(
    ledger: Sequence[Mapping[str, object]],
    *,
    initial_cash: Decimal,
    expected_ending_equity: Decimal | None = None,
    validate_stored_equity: bool,
) -> dict[str, object]:
    if not ledger or not initial_cash.is_finite() or initial_cash <= _ZERO:
        raise ValueError("Fed Policy Absorption 001 event ledger is empty")
    ordered = tuple(
        sorted(
            ledger,
            key=lambda row: (
                _utc_timestamp(row.get("scheduled_utc"), "event scheduled UTC"),
                _required_text(row.get("event_id"), "event ID"),
            ),
        )
    )
    if tuple(ledger) != ordered:
        raise ValueError("Fed Policy Absorption 001 event ledger order differs")
    event_ids = tuple(_required_text(row.get("event_id"), "event ID") for row in ledger)
    sessions = tuple(_required_text(row.get("xnys_session"), "event session") for row in ledger)
    if len(set(event_ids)) != len(event_ids) or len(set(sessions)) != len(sessions):
        raise ValueError("Fed Policy Absorption 001 event identities collide")

    current = gross_equity = spread_equity = peak = initial_cash
    maximum_drawdown = _ZERO
    active = statements = minutes = entries = exits = fills = round_trips = 0
    fee_total = _ZERO
    gross_active_returns: list[Decimal] = []
    class_net = dict.fromkeys(_PUBLICATION_CLASSES, _ZERO)
    positive_by_event: list[Decimal] = []
    positive_by_class = dict.fromkeys(_PUBLICATION_CLASSES, _ZERO)
    positive_by_period: dict[str, Decimal] = {}
    for row in ledger:
        publication_class = _required_text(row.get("publication_class"), "publication class")
        if publication_class not in _PUBLICATION_CLASSES:
            raise ValueError("Fed Policy Absorption 001 publication class differs")
        activation = row.get("activation")
        if not isinstance(activation, bool):
            raise ValueError("Fed Policy Absorption 001 activation must be boolean")
        period_id = _required_text(row.get("period_id"), "period ID")
        if period_id not in _PERIOD_IDS and not period_id.startswith("synthetic-"):
            raise ValueError("Fed Policy Absorption 001 event period differs")
        pre_equity = _required_metric(row, "pre_event_equity")
        pre_cash = _required_metric(row, "pre_event_cash")
        end_cash = _required_metric(row, "end_event_cash")
        gross_return = _required_metric(row, "gross_event_return")
        spread_return = _required_metric(row, "spread_adjusted_event_return")
        net_return = _required_metric(row, "net_event_return")
        fees_for_event = _required_metric(row, "regulatory_fees")
        positive = _required_metric(row, "positive_contribution")
        if (
            pre_equity <= _ZERO
            or pre_cash != pre_equity
            or positive != max(net_return, _ZERO)
            or _required_metric(row, "gross_event_profit_loss") != pre_equity * gross_return
            or _required_metric(row, "spread_adjusted_event_profit_loss")
            != pre_equity * spread_return
            or _required_metric(row, "net_event_profit_loss") != end_cash - pre_equity
            or net_return != spread_return - fees_for_event / pre_equity
            or end_cash != pre_equity * (_ONE + net_return)
            or row.get("flat_at_close") is not True
            or row.get("missed_fill") is not False
        ):
            raise ValueError("Fed Policy Absorption 001 event accounting differs")
        exposure = _mapping(row.get("end_event_exposure"), "event ending exposure")
        if set(exposure) != {"SPY", "QQQ", "aggregate"} or any(
            _required_metric(exposure, key) != _ZERO for key in exposure
        ):
            raise ValueError("Fed Policy Absorption 001 event ending exposure differs")
        identities = _mapping(row.get("accounting_identity_results"), "event identities")
        if not identities or any(value is not True for value in identities.values()):
            raise ValueError("Fed Policy Absorption 001 event identity failed")
        fee_record = _mapping(row.get("regulatory_fee_record"), "event fee record")
        by_symbol = _mapping(fee_record.get("by_symbol"), "event fees by symbol")
        if (
            set(by_symbol) != {"SPY", "QQQ"}
            or _required_metric(fee_record, "total") != fees_for_event
            or sum((_required_metric(by_symbol, symbol) for symbol in ("SPY", "QQQ")), _ZERO)
            != fees_for_event
        ):
            raise ValueError("Fed Policy Absorption 001 fee allocation differs")
        entry_count = _required_integer(row.get("entry_fill_count"), "entry fill count")
        exit_count = _required_integer(row.get("exit_fill_count"), "exit fill count")
        fill_count = _required_integer(row.get("fill_count"), "fill count")
        round_trip_count = _required_integer(
            row.get("symbol_round_trip_count"), "symbol round-trip count"
        )
        legs = _mapping(row.get("legs"), "event legs")
        expected_counts = (2, 2, 4, 2) if activation else (0, 0, 0, 0)
        if (
            (entry_count, exit_count, fill_count, round_trip_count) != expected_counts
            or set(legs) != ({"SPY", "QQQ"} if activation else set())
            or (not activation and any((gross_return, spread_return, net_return, fees_for_event)))
        ):
            raise ValueError("Fed Policy Absorption 001 event execution counts differ")
        if validate_stored_equity and pre_equity != current:
            raise ValueError("Fed Policy Absorption 001 stored event equity differs")
        current *= _ONE + net_return
        gross_equity *= _ONE + gross_return
        spread_equity *= _ONE + spread_return
        if validate_stored_equity and current != end_cash:
            raise ValueError("Fed Policy Absorption 001 stored ending equity differs")
        peak = max(peak, current)
        maximum_drawdown = max(maximum_drawdown, (peak - current) / peak)
        active += int(activation)
        statements += int(activation and publication_class == "fomc-policy-statement")
        minutes += int(activation and publication_class == "fomc-meeting-minutes")
        entries += entry_count
        exits += exit_count
        fills += fill_count
        round_trips += round_trip_count
        fee_total += fees_for_event
        if activation:
            gross_active_returns.append(gross_return)
        class_net[publication_class] += net_return
        positive_by_event.append(positive)
        positive_by_class[publication_class] += positive
        positive_by_period[period_id] = positive_by_period.get(period_id, _ZERO) + positive

    if expected_ending_equity is not None and current != expected_ending_equity:
        raise ValueError("Fed Policy Absorption 001 report ending equity differs")
    event_concentration = _positive_concentration(tuple(positive_by_event))
    session_concentration = _positive_concentration(tuple(positive_by_event))
    metrics: dict[str, object] = {
        "initial_cash": initial_cash,
        "ending_equity": current,
        "total_return": current / initial_cash - _ONE,
        "gross_portfolio_return": gross_equity / initial_cash - _ONE,
        "spread_adjusted_return": spread_equity / initial_cash - _ONE,
        "gross_profit_loss": gross_equity - initial_cash,
        "spread_adjusted_profit_loss": spread_equity - initial_cash,
        "net_profit_loss": current - initial_cash,
        "execution_friction": gross_equity - current,
        "eligible_event_count": len(ledger),
        "active_event_count": active,
        "activity_rate": Decimal(active) / Decimal(len(ledger)),
        "active_statement_count": statements,
        "active_minutes_count": minutes,
        "entry_fill_count": entries,
        "exit_fill_count": exits,
        "fill_count": fills,
        "symbol_round_trip_count": round_trips,
        "gross_edge_bps": (
            sum(gross_active_returns, _ZERO) * _BPS / Decimal(active) if active else None
        ),
        "regulatory_fee_total": fee_total,
        "maximum_drawdown": maximum_drawdown,
        "session_concentration": session_concentration,
        "event_concentration": event_concentration,
        "publication_class_concentration": _positive_concentration(
            tuple(positive_by_class[name] for name in _PUBLICATION_CLASSES)
        ),
        "period_concentration": _positive_concentration(tuple(positive_by_period.values())),
        "statement_aggregate_contribution": class_net["fomc-policy-statement"],
        "minutes_aggregate_contribution": class_net["fomc-meeting-minutes"],
        "accounting_identity_results": {
            "chronological_compounding": True,
            "ending_equity": True,
            "event_session_identity": event_concentration == session_concentration,
            "fill_counts": entries == exits == 2 * active and fills == 4 * active,
            "round_trip_counts": round_trips == 2 * active,
            "flat_at_close": True,
            "net_profit_loss": current - initial_cash
            == initial_cash * (current / initial_cash - _ONE),
        },
    }
    identity_results = _mapping(
        metrics["accounting_identity_results"], "aggregate accounting identities"
    )
    if any(value is not True for value in identity_results.values()):
        raise ValueError("Fed Policy Absorption 001 aggregate accounting identity failed")
    return metrics


def _paired_metric_values(
    normal: Mapping[str, object], zero: Mapping[str, object]
) -> dict[str, object]:
    count_fields = (
        "eligible_event_count",
        "active_event_count",
        "active_statement_count",
        "active_minutes_count",
        "entry_fill_count",
        "exit_fill_count",
        "fill_count",
        "symbol_round_trip_count",
    )
    counts = {name: _required_integer(normal.get(name), name) for name in count_fields}
    if any(_required_integer(zero.get(name), name) != value for name, value in counts.items()):
        raise ValueError("Fed Policy Absorption 001 paired activity differs")
    zero_return = _required_metric(zero, "total_return")
    normal_return = _required_metric(normal, "total_return")
    if (
        zero_return != _required_metric(zero, "gross_portfolio_return")
        or zero_return != _required_metric(zero, "spread_adjusted_return")
        or _required_metric(zero, "regulatory_fee_total") != _ZERO
    ):
        raise ValueError("Fed Policy Absorption 001 zero-cost identity differs")
    cost_drag = zero_return - normal_return
    if cost_drag < _ZERO:
        raise ValueError("Fed Policy Absorption 001 cost drag is negative")
    values: dict[str, object] = {
        **counts,
        "gross_edge_bps": _optional_metric(zero, "gross_edge_bps"),
        "cost_drag": cost_drag,
    }
    for prefix, metrics in (("normal", normal), ("zero_cost_diagnostic", zero)):
        for name in (
            "total_return",
            "maximum_drawdown",
            "session_concentration",
            "event_concentration",
            "publication_class_concentration",
            "period_concentration",
            "statement_aggregate_contribution",
            "minutes_aggregate_contribution",
        ):
            values[f"{prefix}.{name}"] = _optional_metric(metrics, name)
    values["normal.cost_ratio"] = cost_drag / zero_return if zero_return > _ZERO else None
    return values


def _cross_trace_hash(report: Mapping[str, Any]) -> str:
    details = _mapping(report.get("details"), "report details")
    value = _required_text(details.get("cross_scenario_trace_hash"), "cross-scenario trace hash")
    evidence = _mapping(report.get("execution_evidence"), "execution evidence")
    if evidence.get("cross_scenario_trace_hash") != value:
        raise ValueError("Fed Policy Absorption 001 cross-scenario trace linkage differs")
    return value


def _aggregate_reports(
    reports: tuple[Mapping[str, Any], ...], events: Sequence[FedPolicyAbsorptionEvent]
) -> dict[str, object]:
    if not reports:
        raise ValueError("Fed Policy Absorption 001 aggregate requires reports")
    for report in reports:
        _validate_run_report_payload(report, events)
    contexts = tuple(
        _mapping(_mapping(report.get("specification"), "specification").get("context"), "context")
        for report in reports
    )
    candidates = {_text(context, "candidate_id") for context in contexts}
    scenarios = {_text(context, "scenario_id") for context in contexts}
    period_ids = tuple(_text(context, "period_id") for context in contexts)
    known_periods = tuple(period for period in period_ids if period in _PERIOD_IDS)
    if (
        len(candidates) != 1
        or len(scenarios) != 1
        or len(set(period_ids)) != len(period_ids)
        or (known_periods and known_periods != tuple(sorted(known_periods, key=_PERIOD_IDS.index)))
    ):
        raise ValueError("Fed Policy Absorption 001 aggregate report order differs")
    ledger = [
        dict(row)
        for report in reports
        for row in _event_ledger(_mapping(report.get("details"), "report details"))
    ]
    initial_cash = _required_report_metric(reports[0], "initial_cash")
    if any(_required_report_metric(report, "initial_cash") != initial_cash for report in reports):
        raise ValueError("Fed Policy Absorption 001 aggregate initial cash differs")
    aggregate = _metrics_from_event_ledger(
        ledger,
        initial_cash=initial_cash,
        validate_stored_equity=False,
    )
    aggregate.update(
        {
            "session_count": sum(
                _required_integer(_report_metrics(report).get("session_count"), "session count")
                for report in reports
            ),
            "period_count": len(reports),
            "event_ledger": ledger,
            "cross_scenario_trace_hashes": [_cross_trace_hash(report) for report in reports],
            "execution_trace_hashes": [
                _required_text(
                    _mapping(report.get("details"), "report details").get("execution_trace_hash"),
                    "execution trace hash",
                )
                for report in reports
            ],
        }
    )
    return aggregate


def _event_ledger(details: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    value = details.get("event_ledger")
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("Fed Policy Absorption 001 event ledger differs")
    return tuple(value)


def _recompute_terminal_screening(
    plan: Any, reports: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, object], tuple[str, ...]]:
    indexed: dict[tuple[str, str | None, str, str, str], Mapping[str, Any]] = {}
    run_identities: set[tuple[str, str, str]] = set()
    for report in reports:
        _validate_run_report_payload(report, plan.events)
        specification = _mapping(report.get("specification"), "terminal specification")
        context = _mapping(specification.get("context"), "terminal context")
        base = context.get("base_candidate_id")
        if base is not None and not isinstance(base, str):
            raise ValueError("Fed Policy Absorption 001 terminal base candidate differs")
        key = (
            _text(context, "stage"),
            base,
            _text(context, "candidate_id"),
            _text(context, "period_id"),
            _text(context, "scenario_id"),
        )
        identity = key[2:]
        if key in indexed or identity in run_identities:
            raise ValueError("Fed Policy Absorption 001 duplicate terminal report identity")
        indexed[key] = report
        run_identities.add(identity)
    if len(indexed) > _MAXIMUM_RUN_SPECIFICATIONS:
        raise ValueError("Fed Policy Absorption 001 terminal run budget differs")
    expected: set[tuple[str, str | None, str, str, str]] = set()

    def report_for(
        stage: str,
        candidate: str,
        period: str,
        scenario: str,
        *,
        base: str | None = None,
    ) -> Mapping[str, Any]:
        key = (stage, base, candidate, period, scenario)
        expected.add(key)
        try:
            return indexed[key]
        except KeyError as error:
            raise ValueError(
                "Fed Policy Absorption 001 required terminal report is missing"
            ) from error

    def pair(
        stage: str, candidate: str, period: str, *, base: str | None = None
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        normal = report_for(stage, candidate, period, "normal", base=base)
        zero = report_for(stage, candidate, period, "zero_cost_diagnostic", base=base)
        if _cross_trace_hash(normal) != _cross_trace_hash(zero):
            raise ValueError("Fed Policy Absorption 001 terminal paired traces differ")
        return normal, zero

    discovery_period = plan.periods[0]
    discovery_gates = _plan_gates(plan.payload, "discovery_screen", "gates")
    discovery_ledger: list[dict[str, object]] = []
    for configuration in plan.configurations:
        normal, zero = pair("discovery", configuration.candidate_id, discovery_period.period_id)
        values = _paired_metric_values(_report_metrics(normal), _report_metrics(zero))
        gate_results = _exact_gate_results(discovery_gates, values)
        discovery_ledger.append(
            {
                "candidate": _configuration_summary(configuration),
                "normal_run_id": normal["run_id"],
                "zero_cost_run_id": zero["run_id"],
                "metrics": values,
                "gate_results": gate_results,
                "eligible": all(item["passed"] is True for item in gate_results),
                "selected": False,
            }
        )
    discovery_screen = _mapping(plan.payload.get("discovery_screen"), "discovery screen")
    discovery_selected = _select_eligible(
        discovery_ledger,
        _positive_int(discovery_screen.get("selection_cap"), "discovery selection cap"),
        key=lambda _item: (),
    )
    for item in discovery_ledger:
        item["selected"] = _screen_candidate_id(item) in discovery_selected
    discovery: dict[str, object] = {
        "stage": "discovery",
        "period_id": discovery_period.period_id,
        "parent_count": len(discovery_ledger),
        "paired_run_count": 18,
        "eligible_count": sum(item["eligible"] is True for item in discovery_ledger),
        "selected_candidate_ids": discovery_selected,
        "ledger": discovery_ledger,
    }

    periods = plan.periods[1:]
    period_gates = _plan_gates(plan.payload, "walk_forward_screen", "per_period_gates")
    serious_gates = _plan_gates(plan.payload, "serious_candidate_screen", "gates")
    discovery_by_id = {_screen_candidate_id(item): item for item in discovery_ledger}
    walk_ledger: list[dict[str, object]] = []
    for candidate_id in discovery_selected:
        configuration = _configuration_by_id(plan.configurations, candidate_id)
        normal_reports: list[Mapping[str, Any]] = []
        zero_reports: list[Mapping[str, Any]] = []
        period_rows: list[dict[str, object]] = []
        for period in periods:
            normal, zero = pair("walk-forward", candidate_id, period.period_id)
            normal_reports.append(normal)
            zero_reports.append(zero)
            values = _paired_metric_values(_report_metrics(normal), _report_metrics(zero))
            gate_results = _exact_gate_results(period_gates, values)
            period_rows.append(
                {
                    "period_id": period.period_id,
                    "normal_run_id": normal["run_id"],
                    "zero_cost_run_id": zero["run_id"],
                    "metrics": values,
                    "gate_results": gate_results,
                    "eligible": all(item["passed"] is True for item in gate_results),
                }
            )
        normal_aggregate = _aggregate_reports(tuple(normal_reports), plan.events)
        zero_aggregate = _aggregate_reports(tuple(zero_reports), plan.events)
        discovery_pair = pair("discovery", candidate_id, discovery_period.period_id)
        combined_normal = _aggregate_reports((discovery_pair[0], *normal_reports), plan.events)
        combined_zero = _aggregate_reports((discovery_pair[1], *zero_reports), plan.events)
        walk_values = _paired_metric_values(normal_aggregate, zero_aggregate)
        combined_values = _paired_metric_values(combined_normal, combined_zero)
        values = {
            "walk_forward.active_event_count": walk_values["active_event_count"],
            "walk_forward.periods_with_activation": sum(
                _required_metric(_mapping(row["metrics"], "period metrics"), "active_event_count")
                > 0
                for row in period_rows
            ),
            "combined.active_event_count": combined_values["active_event_count"],
            "combined.active_statement_count": combined_values["active_statement_count"],
            "combined.active_minutes_count": combined_values["active_minutes_count"],
            **{
                f"combined.{key}": value
                for key, value in combined_values.items()
                if key.startswith("normal.")
                or key.startswith("zero_cost_diagnostic.")
                or key == "gross_edge_bps"
            },
            **{
                f"walk_forward.{key}": value
                for key, value in walk_values.items()
                if key in {"normal.total_return", "zero_cost_diagnostic.total_return"}
            },
        }
        gate_results = _exact_gate_results(serious_gates, values)
        walk_ledger.append(
            {
                "candidate": _configuration_summary(configuration),
                "periods": period_rows,
                "walk_forward_normal_aggregate": normal_aggregate,
                "walk_forward_zero_cost_aggregate": zero_aggregate,
                "combined_normal_aggregate": combined_normal,
                "combined_zero_cost_aggregate": combined_zero,
                "metrics": values,
                "gate_results": gate_results,
                "eligible": discovery_by_id[candidate_id]["eligible"] is True
                and all(row["eligible"] is True for row in period_rows)
                and all(item["passed"] is True for item in gate_results),
                "selected": False,
            }
        )
    serious_screen = _mapping(
        plan.payload.get("serious_candidate_screen"), "serious candidate screen"
    )
    serious_selected = _select_eligible(
        walk_ledger,
        _positive_int(serious_screen.get("selection_cap"), "serious candidate cap"),
        key=lambda _item: (),
    )
    for item in walk_ledger:
        item["selected"] = _screen_candidate_id(item) in serious_selected
    walk: dict[str, object] = {
        "stage": "walk-forward-and-serious-selection",
        "candidate_count": len(walk_ledger),
        "paired_run_count": len(discovery_selected) * 8,
        "eligible_count": sum(item["eligible"] is True for item in walk_ledger),
        "selected_candidate_ids": serious_selected,
        "ledger": walk_ledger,
    }

    stress_scenarios = ("stress_a", "stress_b", "normal-delay-2", "normal-delay-3")
    stress_gates = _plan_gates(plan.payload, "stress_delay_screen", "per_scenario_gates")
    walk_by_id = {_screen_candidate_id(item): item for item in walk_ledger}
    stress_ledger: list[dict[str, object]] = []
    for candidate_id in serious_selected:
        base_walk = _mapping(walk_by_id[candidate_id], "base walk-forward screen")
        zero_base = _mapping(
            base_walk.get("walk_forward_zero_cost_aggregate"), "zero-cost baseline"
        )
        zero_return = _required_metric(zero_base, "total_return")
        scenario_rows: list[dict[str, object]] = []
        for scenario_id in stress_scenarios:
            scenario_reports = tuple(
                report_for("stress", candidate_id, period.period_id, scenario_id)
                for period in periods
            )
            for period, scenario_report in zip(periods, scenario_reports, strict=True):
                baseline = report_for("walk-forward", candidate_id, period.period_id, "normal")
                if _cross_trace_hash(scenario_report) != _cross_trace_hash(baseline):
                    raise ValueError("Fed Policy Absorption 001 terminal stress trace differs")
            aggregate = _aggregate_reports(scenario_reports, plan.events)
            scenario_return = _required_metric(aggregate, "total_return")
            degradation = (zero_return - scenario_return) / zero_return if zero_return > 0 else None
            values = {
                "aggregate.total_return": scenario_return,
                "minimum_period_return": min(
                    _required_report_metric(report, "total_return") for report in scenario_reports
                ),
                "aggregate.maximum_drawdown": _required_metric(aggregate, "maximum_drawdown"),
                "degradation_ratio": degradation,
                "aggregate.session_concentration": _optional_metric(
                    aggregate, "session_concentration"
                ),
                "aggregate.event_concentration": _optional_metric(aggregate, "event_concentration"),
                "aggregate.publication_class_concentration": _optional_metric(
                    aggregate, "publication_class_concentration"
                ),
                "aggregate.period_concentration": _optional_metric(
                    aggregate, "period_concentration"
                ),
            }
            gate_results = _exact_gate_results(stress_gates, values)
            required_passed = (
                zero_return > 0
                and _required_metric(aggregate, "statement_aggregate_contribution") > 0
                and _required_metric(aggregate, "minutes_aggregate_contribution") > 0
            )
            scenario_rows.append(
                {
                    "scenario_id": scenario_id,
                    "run_ids": [report["run_id"] for report in scenario_reports],
                    "aggregate": aggregate,
                    "metrics": values,
                    "gate_results": gate_results,
                    "eligible": required_passed
                    and all(result["passed"] is True for result in gate_results),
                }
            )
        eligible = all(row["eligible"] is True for row in scenario_rows)
        stress_ledger.append(
            {
                "candidate": _configuration_summary(
                    _configuration_by_id(plan.configurations, candidate_id)
                ),
                "scenarios": scenario_rows,
                "eligible": eligible,
                "selected_for_neighbors": eligible,
            }
        )
    stress_selected = tuple(
        _screen_candidate_id(item) for item in stress_ledger if item["eligible"] is True
    )
    if len(stress_selected) > 1:
        raise ValueError("Fed Policy Absorption 001 terminal stress selection exceeds one")
    stress: dict[str, object] = {
        "stage": "stress-delay",
        "candidate_count": len(stress_ledger),
        "stress_run_count": len(serious_selected) * 16,
        "eligible_count": sum(item["eligible"] is True for item in stress_ledger),
        "selected_candidate_ids": stress_selected,
        "ledger": stress_ledger,
    }

    neighbor_gates = _plan_gates(plan.payload, "neighbor_screen", "per_neighbor_gates")
    neighbor_ledger: list[dict[str, object]] = []
    for parent_id in stress_selected:
        parent = _configuration_by_id(plan.configurations, parent_id)
        neighbor_rows: list[dict[str, object]] = []
        for neighbor_id in parent.neighbor_ids:
            normals: list[Mapping[str, Any]] = []
            zeros: list[Mapping[str, Any]] = []
            neighbor_period_rows: list[dict[str, object]] = []
            for period in periods:
                normal, zero = pair("neighbor", neighbor_id, period.period_id, base=parent_id)
                normals.append(normal)
                zeros.append(zero)
                neighbor_period_rows.append(
                    {
                        "period_id": period.period_id,
                        "normal_run_id": normal["run_id"],
                        "zero_cost_run_id": zero["run_id"],
                        "active_event_count": _required_report_metric(normal, "active_event_count"),
                    }
                )
            normal_aggregate = _aggregate_reports(tuple(normals), plan.events)
            zero_aggregate = _aggregate_reports(tuple(zeros), plan.events)
            pair_values = _paired_metric_values(normal_aggregate, zero_aggregate)
            values = {
                "walk_forward.active_event_count": pair_values["active_event_count"],
                "walk_forward.periods_with_activation": sum(
                    _required_metric(row, "active_event_count") > 0 for row in neighbor_period_rows
                ),
                **{
                    f"aggregate.{key}": value
                    for key, value in pair_values.items()
                    if key.startswith("normal.")
                    or key.startswith("zero_cost_diagnostic.")
                    or key == "gross_edge_bps"
                },
            }
            gate_results = _exact_gate_results(neighbor_gates, values)
            required_passed = (
                _required_integer(
                    pair_values.get("active_statement_count"), "active statement count"
                )
                >= 1
                and _required_integer(
                    pair_values.get("active_minutes_count"), "active minutes count"
                )
                >= 1
            )
            neighbor_rows.append(
                {
                    "neighbor_id": neighbor_id,
                    "periods": neighbor_period_rows,
                    "normal_aggregate": normal_aggregate,
                    "zero_cost_aggregate": zero_aggregate,
                    "metrics": values,
                    "gate_results": gate_results,
                    "eligible": required_passed
                    and all(result["passed"] is True for result in gate_results),
                }
            )
        eligible = len(neighbor_rows) == 4 and all(row["eligible"] is True for row in neighbor_rows)
        neighbor_ledger.append(
            {
                "candidate": _configuration_summary(parent),
                "neighbors": neighbor_rows,
                "eligible": eligible,
                "selected": eligible,
            }
        )
    cohort = tuple(
        _screen_candidate_id(item) for item in neighbor_ledger if item["eligible"] is True
    )
    if len(cohort) > 1 or any(candidate not in stress_selected for candidate in cohort):
        raise ValueError("Fed Policy Absorption 001 terminal cohort differs")
    neighbors: dict[str, object] = {
        "stage": "immediate-neighbors",
        "candidate_count": len(neighbor_ledger),
        "neighbor_run_count": len(stress_selected) * 32,
        "eligible_count": len(cohort),
        "selected_candidate_ids": cohort,
        "ledger": neighbor_ledger,
    }
    if set(indexed) != expected:
        raise ValueError("Fed Policy Absorption 001 terminal report graph differs")
    return (
        {
            "discovery": discovery,
            "walk_forward": walk,
            "stress": stress,
            "neighbors": neighbors,
        },
        cohort,
    )


def validate_terminal_screening(
    plan: Any,
    reports: Sequence[Mapping[str, Any]],
    screened: Mapping[str, object],
    cohort: Sequence[str],
) -> None:
    recomputed, recomputed_cohort = _recompute_terminal_screening(plan, reports)
    if (
        canonicalize(screened) != canonicalize(recomputed)
        or tuple(cohort) != recomputed_cohort
        or len(cohort) > 1
    ):
        raise ValueError("Fed Policy Absorption 001 terminal screening differs")


def _final_markdown(report: Mapping[str, object], json_sha256: str) -> str:
    counts = _mapping(report.get("counts"), "final counts")
    lines = [
        "# Intraday Fed Policy Absorption 001 final report",
        "",
        f"Outcome: `{report['outcome']}`",
        "",
        f"Source commit: `{report['source_commit']}`",
        "",
        f"JSON SHA-256: `{json_sha256}`",
        "",
        "## Counts",
        "",
    ]
    for label, key in (
        ("Discovery parents", "discovery_parents"),
        ("Discovery runs", "discovery_runs"),
        ("Walk-forward candidates", "walk_forward_candidates"),
        ("Walk-forward runs", "walk_forward_runs"),
        ("Serious candidates", "serious_candidates"),
        ("Stress runs", "stress_runs"),
        ("Neighbor runs", "neighbor_runs"),
        ("Final cohort", "cohort"),
    ):
        lines.append(f"- {label}: {counts.get(key)}")
    lines.extend(
        (
            "",
            "No controlled evaluation occurred. June and every protected boundary remained unread.",
            "",
            f"**{report['terminal_message']}**",
            "",
        )
    )
    return "\n".join(lines)


def _read_final_report(path: Path, *, source_commit: str | None = None) -> Mapping[str, Any]:
    value = _mapping(json.loads(path.read_bytes()), "final report")
    stored = _text(value, "report_fingerprint")
    unsigned = dict(value)
    del unsigned["report_fingerprint"]
    repository = Path(__file__).resolve().parents[2]
    plan = load_intraday_fed_policy_absorption_001_plan(repository)
    launch = _mapping(value.get("launch_control"), "final launch control")
    controlled = _mapping(value.get("controlled_evaluation"), "controlled evaluation")
    counts = _mapping(value.get("counts"), "final counts")
    cohort = value.get("cohort")
    interrupted = value.get("final_freeze") is None
    expected_keys = {
        "schema_version",
        "program_id",
        "outcome",
        "terminal_message",
        "source_commit",
        "plan",
        "launch_control",
        "complete_exposed_screening",
        "counts",
        "cohort",
        "attempt_summary",
        "runtime_database",
        "final_freeze",
        "controlled_evaluation",
        "protected_access",
        "authority",
        "report_fingerprint",
    }
    if interrupted:
        expected_keys.update({"terminal_failures", "attempt_histories"})
    if (
        set(value) != expected_keys
        or value.get("schema_version") != FINAL_REPORT_SCHEMA
        or value.get("program_id") != PROGRAM_ID
        or (source_commit is not None and value.get("source_commit") != source_commit)
        or value.get("plan") != _frozen_plan_evidence(plan)
        or launch
        != {
            "path": LAUNCH_CONTROL_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_LAUNCH_CONTROL_SHA256,
            "fingerprint": REVIEWED_LAUNCH_CONTROL_FINGERPRINT,
        }
        or not isinstance(cohort, list)
        or counts.get("cohort") != (None if interrupted else len(cohort))
        or set(controlled) != {"performed", "reason", "controlled_qualified_claim"}
        or controlled.get("performed") is not False
        or controlled.get("controlled_qualified_claim") is not False
        or not isinstance(controlled.get("reason"), str)
        or not controlled.get("reason")
        or value.get("protected_access") != _protected_access()
        or fingerprint(unsigned) != stored
        or value.get("authority") != _AUTHORITY
        or (
            interrupted
            and (
                value.get("outcome") != "terminally-interrupted"
                or value.get("complete_exposed_screening") is not False
                or cohort != []
            )
        )
        or (
            not interrupted
            and (
                value.get("complete_exposed_screening") is not True
                or value.get("outcome")
                != (
                    "no-controlled-qualified-candidate"
                    if not cohort
                    else "exposed-serious-candidates-waiting-for-future-untouched-data"
                )
            )
        )
    ):
        raise ValueError("Fed Policy Absorption 001 final report differs")
    return value


def _validate_final_evidence(runtime: Path, report: Mapping[str, Any]) -> None:
    database = _mapping(report.get("runtime_database"), "runtime database")
    if database.get("path") != DATABASE_NAME or database.get("sha256") != _sha256_path(
        runtime / DATABASE_NAME
    ):
        raise ValueError("Fed Policy Absorption 001 runtime database differs")
    freeze_evidence = report.get("final_freeze")
    if freeze_evidence is None:
        return
    evidence = _mapping(freeze_evidence, "final freeze evidence")
    relative = _required_text(evidence.get("path"), "freeze path")
    if relative != "final-freeze.json":
        raise ValueError("Fed Policy Absorption 001 final freeze path differs")
    freeze_path = runtime / relative
    freeze = _mapping(json.loads(freeze_path.read_bytes()), "final freeze")
    stored = _text(freeze, "freeze_fingerprint")
    unsigned = dict(freeze)
    del unsigned["freeze_fingerprint"]
    repository = Path(__file__).resolve().parents[2]
    plan = load_intraday_fed_policy_absorption_001_plan(repository)
    plan_evidence = _mapping(freeze.get("plan"), "freeze plan")
    launch = _mapping(freeze.get("launch_control"), "freeze launch control")
    cost_model = _mapping(freeze.get("cost_model"), "freeze cost model")
    screened = _mapping(freeze.get("screened_ledger"), "freeze screened ledger")
    boundary = _mapping(freeze.get("controlled_boundary"), "controlled boundary")
    cohort = freeze.get("cohort")
    all_runs = freeze.get("all_runtime_runs")
    histories = freeze.get("attempt_histories")
    if (
        evidence.get("sha256") != _sha256_path(freeze_path)
        or evidence.get("fingerprint") != stored
        or set(freeze)
        != {
            "schema_version",
            "program_id",
            "status",
            "source_commit",
            "runner_version",
            "engine_version",
            "strategy_version",
            "plan",
            "launch_control",
            "cost_model",
            "datasets",
            "screened_ledger",
            "cohort",
            "cohort_size",
            "all_runtime_runs",
            "attempt_summary",
            "attempt_histories",
            "controlled_boundary",
            "protected_access",
            "authority",
            "freeze_fingerprint",
        }
        or freeze.get("schema_version") != FINAL_FREEZE_SCHEMA
        or freeze.get("program_id") != PROGRAM_ID
        or freeze.get("status") != "frozen-after-complete-exposed-screening"
        or freeze.get("source_commit") != report.get("source_commit")
        or freeze.get("runner_version") != RUNNER_VERSION
        or freeze.get("engine_version") != ENGINE_VERSION
        or freeze.get("strategy_version") != STRATEGY_VERSION
        or plan_evidence != _frozen_plan_evidence(plan)
        or launch.get("review_fingerprint") != REVIEWED_LAUNCH_CONTROL_FINGERPRINT
        or launch.get("status") != "passed"
        or launch.get("verdict") != "pass"
        or cost_model
        != {
            "sha256": plan.payload["execution"]["cost_model"]["sha256"],
            "fingerprint": plan.payload["execution"]["cost_model"]["fingerprint"],
        }
        or canonicalize(freeze.get("datasets"))
        != canonicalize([canonicalize(value) for value in _dataset_bindings(plan.payload)])
        or set(screened) != {"discovery", "walk_forward", "stress", "neighbors"}
        or not isinstance(cohort, list)
        or freeze.get("cohort_size") != len(cohort)
        or cohort != report.get("cohort")
        or freeze.get("attempt_summary") != report.get("attempt_summary")
        or not isinstance(all_runs, list)
        or not isinstance(histories, list)
        or boundary.get("range_status") != "none-eligible"
        or boundary.get("june_read") is not False
        or boundary.get("substitute_range") is not False
        or boundary.get("controlled_evaluation_performed") is not False
        or freeze.get("protected_access") != _protected_access()
        or freeze.get("authority") != _AUTHORITY
        or fingerprint(unsigned) != stored
    ):
        raise ValueError("Fed Policy Absorption 001 final freeze differs")
    canonical_reports: list[Mapping[str, Any]] = []
    for item in all_runs:
        run = _mapping(item, "terminal run evidence")
        relative_report = Path(_required_text(run.get("report_path"), "terminal report path"))
        if relative_report.is_absolute() or ".." in relative_report.parts:
            raise ValueError("Fed Policy Absorption 001 terminal report path is unsafe")
        raw = (runtime / relative_report).read_bytes()
        run_report = _mapping(json.loads(raw), "terminal run report")
        if (
            run.get("status") != "completed"
            or hashlib.sha256(raw).hexdigest() != run.get("report_sha256")
            or run_report.get("report_fingerprint") != run.get("report_fingerprint")
            or run_report.get("run_id") != run.get("run_id")
            or run_report.get("source_commit") != report.get("source_commit")
        ):
            raise ValueError("Fed Policy Absorption 001 terminal run evidence differs")
        _validate_run_report_payload(run_report, plan.events)
        canonical_reports.append(run_report)
    cohort_ids = tuple(
        _text(_mapping(item, "freeze cohort candidate"), "candidate_id") for item in cohort
    )
    validate_terminal_screening(plan, canonical_reports, screened, cohort_ids)
    expected_cohort = [
        _configuration_summary(_configuration_by_id(plan.configurations, candidate_id))
        for candidate_id in cohort_ids
    ]
    attempt_summary = _attempt_summary(
        tuple(_mapping(item, "terminal run evidence") for item in all_runs),
        tuple(_mapping(item, "terminal attempt history") for item in histories),
    )
    if (
        canonicalize(cohort) != canonicalize(expected_cohort)
        or freeze.get("attempt_summary") != attempt_summary
        or _required_integer(attempt_summary.get("total_attempts"), "total attempts") > 270
        or _required_integer(
            attempt_summary.get("maximum_attempts_for_one_run"), "maximum attempts"
        )
        > 3
    ):
        raise ValueError("Fed Policy Absorption 001 terminal attempt evidence differs")
    discovery = _mapping(screened.get("discovery"), "terminal discovery")
    walk = _mapping(screened.get("walk_forward"), "terminal walk-forward")
    stress = _mapping(screened.get("stress"), "terminal stress")
    neighbors = _mapping(screened.get("neighbors"), "terminal neighbors")
    counts = _mapping(report.get("counts"), "terminal counts")
    expected_counts = {
        "discovery_parents": discovery.get("parent_count"),
        "discovery_runs": discovery.get("paired_run_count"),
        "walk_forward_candidates": walk.get("candidate_count"),
        "walk_forward_runs": walk.get("paired_run_count"),
        "serious_candidates": walk.get("eligible_count"),
        "stress_candidates": stress.get("candidate_count"),
        "stress_runs": stress.get("stress_run_count"),
        "neighbor_candidates": neighbors.get("candidate_count"),
        "neighbor_runs": neighbors.get("neighbor_run_count"),
        "total_runs": len(canonical_reports),
        "cohort": len(cohort_ids),
    }
    if dict(counts) != expected_counts:
        raise ValueError("Fed Policy Absorption 001 terminal counts differ")


def _load_launch_control(repository: Path, *, source_commit: str) -> Mapping[str, Any]:
    if REVIEWED_LAUNCH_CONTROL_SHA256 is None or REVIEWED_LAUNCH_CONTROL_FINGERPRINT is None:
        raise ValueError(
            "Intraday Fed Policy Absorption 001 launch control review is not hash-bound"
        )
    path = repository / LAUNCH_CONTROL_RELATIVE_PATH
    if not path.is_file():
        raise ValueError("Intraday Fed Policy Absorption 001 launch control review is missing")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != REVIEWED_LAUNCH_CONTROL_SHA256:
        raise ValueError("Intraday Fed Policy Absorption 001 launch control review SHA-256 differs")
    try:
        value = _mapping(json.loads(raw), "launch control review")
    except json.JSONDecodeError as error:
        raise ValueError(
            "Intraday Fed Policy Absorption 001 launch control review is invalid JSON"
        ) from error
    unsigned = dict(value)
    stored = unsigned.pop("review_fingerprint", None)
    if (
        value.get("schema_version") != _LAUNCH_CONTROL_SCHEMA
        or stored != REVIEWED_LAUNCH_CONTROL_FINGERPRINT
        or fingerprint(unsigned) != stored
        or value.get("status") != "passed"
        or value.get("verdict") != "pass"
        or value.get("authority") != _AUTHORITY
    ):
        raise ValueError("Intraday Fed Policy Absorption 001 launch control review differs")
    _require_exact_keys(
        value,
        {
            "schema_version",
            "review_id",
            "status",
            "verdict",
            "review_date",
            "review_method",
            "reviewed_inputs",
            "implementation",
            "quality_gates",
            "equivalence",
            "independent_review",
            "scope_limit",
            "authority",
            "review_fingerprint",
        },
        "launch control review",
    )
    if value.get("review_id") != _LAUNCH_CONTROL_SCHEMA:
        raise ValueError(
            "Intraday Fed Policy Absorption 001 launch control review identity differs"
        )
    for key in ("review_date", "review_method", "scope_limit"):
        _required_text(value.get(key), f"launch control {key.replace('_', ' ')}")
    _verify_launch_inputs(repository, value)
    implementation_commit = _verify_launch_implementation(repository, value)
    _verify_launch_quality(value, implementation_commit)
    _verify_launch_equivalence(value, implementation_commit)
    review = _mapping(value.get("independent_review"), "launch independent review")
    _require_exact_keys(
        review,
        {"source_commit", "status", "verdict", "findings", "reviewer"},
        "launch independent review",
    )
    if (
        review.get("source_commit") != implementation_commit
        or review.get("status") != "passed"
        or review.get("verdict") != "pass"
        or review.get("findings") != []
    ):
        raise ValueError("Intraday Fed Policy Absorption 001 launch independent review differs")
    _required_text(review.get("reviewer"), "launch independent reviewer")
    _verify_launch_source_lineage(repository, implementation_commit, source_commit)
    return MappingProxyType(dict(value))


def _verify_launch_inputs(repository: Path, value: Mapping[str, Any]) -> None:
    plan = load_intraday_fed_policy_absorption_001_plan(repository)
    autonomous = _mapping(plan.payload.get("autonomous_program"), "autonomous program")
    dependencies = _mapping(plan.payload.get("frozen_dependencies"), "frozen dependencies")
    data = _mapping(plan.payload.get("data"), "plan data")
    inputs = _mapping(value.get("reviewed_inputs"), "launch reviewed inputs")
    expected = {
        "plan": {
            "path": PLAN_RELATIVE_PATH.as_posix(),
            "sha256": PLAN_SHA256,
            "fingerprint": PLAN_FINGERPRINT,
        },
        "calendar": {
            "path": CALENDAR_RELATIVE_PATH.as_posix(),
            "sha256": CALENDAR_SHA256,
            "fingerprint": CALENDAR_FINGERPRINT,
        },
        "source_evidence": {
            "path": SOURCE_EVIDENCE_RELATIVE_PATH.as_posix(),
            "sha256": SOURCE_EVIDENCE_SHA256,
            "fingerprint": SOURCE_EVIDENCE_FINGERPRINT,
        },
        "plan_review": {
            "path": REVIEW_RELATIVE_PATH.as_posix(),
            "sha256": REVIEW_SHA256,
            "fingerprint": REVIEW_FINGERPRINT,
        },
        "autonomous_program": {key: autonomous[key] for key in ("path", "sha256", "fingerprint")},
        "autonomous_program_review": dict(
            _mapping(dependencies.get("autonomous_program_review"), "program review")
        ),
        "source_state": {
            "path": SOURCE_STATE_RELATIVE_PATH.as_posix(),
            "sha256": SOURCE_STATE_SHA256,
            "fingerprint": SOURCE_STATE_FINGERPRINT,
        },
        "state": {
            "path": STATE_RELATIVE_PATH.as_posix(),
            "sha256": STATE_SHA256,
            "fingerprint": STATE_FINGERPRINT,
        },
        "attestation": {
            "path": ATTESTATION_RELATIVE_PATH.as_posix(),
            "sha256": ATTESTATION_SHA256,
            "fingerprint": ATTESTATION_FINGERPRINT,
        },
        "cost_model": dict(_mapping(dependencies.get("execution_cost_model"), "cost model")),
        "cost_model_review": dict(
            _mapping(dependencies.get("execution_cost_review"), "cost model review")
        ),
        "dataset_bindings": data.get("dataset_bindings"),
    }
    if canonicalize(inputs) != canonicalize(expected):
        raise ValueError("Intraday Fed Policy Absorption 001 launch reviewed inputs differ")


def _verify_launch_implementation(repository: Path, value: Mapping[str, Any]) -> str:
    implementation = _mapping(value.get("implementation"), "launch implementation")
    _require_exact_keys(implementation, {"source_commit", "files"}, "launch implementation")
    source_commit = _validated_source_commit(implementation.get("source_commit"))
    files = implementation.get("files")
    if not isinstance(files, list) or len(files) != len(_LAUNCH_CONTROL_FILES):
        raise ValueError("Intraday Fed Policy Absorption 001 launch implementation files differ")
    for item, expected_path in zip(files, _LAUNCH_CONTROL_FILES, strict=True):
        binding = _mapping(item, "launch implementation file")
        _require_exact_keys(binding, {"path", "sha256"}, "launch implementation file")
        if binding.get("path") != expected_path or binding.get("sha256") != _sha256_path(
            repository / expected_path
        ):
            raise ValueError(
                "Intraday Fed Policy Absorption 001 launch implementation file differs"
            )
    return source_commit


def _verify_launch_quality(value: Mapping[str, Any], source_commit: str) -> None:
    quality = _mapping(value.get("quality_gates"), "launch quality gates")
    _require_exact_keys(quality, {"source_commit", "results"}, "launch quality gates")
    results = quality.get("results")
    if quality.get("source_commit") != source_commit or not isinstance(results, list):
        raise ValueError("Intraday Fed Policy Absorption 001 launch quality gates differ")
    if len(results) != len(_LAUNCH_CONTROL_QUALITY_GATES):
        raise ValueError("Intraday Fed Policy Absorption 001 launch quality gate count differs")
    for result, command in zip(results, _LAUNCH_CONTROL_QUALITY_GATES, strict=True):
        gate = _mapping(result, "launch quality gate")
        _require_exact_keys(
            gate, {"command", "status", "exit_code", "summary"}, "launch quality gate"
        )
        if (
            gate.get("command") != command
            or gate.get("status") != "passed"
            or isinstance(gate.get("exit_code"), bool)
            or gate.get("exit_code") != 0
        ):
            raise ValueError("Intraday Fed Policy Absorption 001 launch quality gate differs")
        _required_text(gate.get("summary"), "launch quality gate summary")


def _verify_launch_equivalence(value: Mapping[str, Any], source_commit: str) -> None:
    equivalence = _mapping(value.get("equivalence"), "launch equivalence")
    required = {
        "schema_version",
        "program_id",
        "verification_source_commit",
        "fixture_kind",
        "protected_inputs_accessed",
        "worker_counts",
        "comparisons",
        "fixture_count",
        "sequential_seconds",
        "parallel_seconds",
        "speedup",
        "fixtures",
        "equivalent",
    }
    _require_exact_keys(equivalence, required, "launch equivalence")
    fixtures = equivalence.get("fixtures")
    fixture_count = equivalence.get("fixture_count")
    if (
        equivalence.get("schema_version")
        != "intraday-fed-policy-absorption-001-parallel-equivalence-v1"
        or equivalence.get("program_id") != PROGRAM_ID
        or equivalence.get("verification_source_commit") != source_commit
        or equivalence.get("fixture_kind") != "synthetic-non-protected-five-minute-bars"
        or equivalence.get("protected_inputs_accessed") is not False
        or equivalence.get("worker_counts") != [1, 4]
        or equivalence.get("comparisons") != list(_LAUNCH_CONTROL_EQUIVALENCE_COMPARISONS)
        or isinstance(fixture_count, bool)
        or not isinstance(fixture_count, int)
        or fixture_count < 3
        or not isinstance(fixtures, list)
        or len(fixtures) != fixture_count
        or equivalence.get("equivalent") is not True
    ):
        raise ValueError("Intraday Fed Policy Absorption 001 launch equivalence differs")
    for key in ("sequential_seconds", "parallel_seconds", "speedup"):
        _required_positive_decimal_text(equivalence.get(key), f"launch equivalence {key}")
    fixture_keys = {
        "run_id",
        "candidate_id",
        "scenario_id",
        "run_fingerprint",
        "cross_scenario_trace_hash",
        "execution_trace_hash",
        "report_sha256",
        "report_fingerprint",
        "specification_equal",
        "run_fingerprint_equal",
        "cross_scenario_trace_hash_equal",
        "execution_trace_hash_equal",
        "metrics_equal",
        "event_ledger_equal",
        "canonical_report_equal",
        "report_sha256_equal",
        "report_fingerprint_equal",
    }
    candidates: set[str] = set()
    scenarios: set[str] = set()
    for item in fixtures:
        fixture = _mapping(item, "launch equivalence fixture")
        _require_exact_keys(fixture, fixture_keys, "launch equivalence fixture")
        for key in ("run_id", "candidate_id", "scenario_id"):
            _required_text(fixture.get(key), f"launch equivalence fixture {key}")
        for key in (
            "run_fingerprint",
            "cross_scenario_trace_hash",
            "execution_trace_hash",
            "report_sha256",
            "report_fingerprint",
        ):
            _required_sha256(fixture.get(key), f"launch equivalence fixture {key}")
        if any(
            fixture.get(key) is not True
            for key in (
                "specification_equal",
                "run_fingerprint_equal",
                "cross_scenario_trace_hash_equal",
                "execution_trace_hash_equal",
                "metrics_equal",
                "event_ledger_equal",
                "canonical_report_equal",
                "report_sha256_equal",
                "report_fingerprint_equal",
            )
        ):
            raise ValueError(
                "Intraday Fed Policy Absorption 001 launch equivalence fixture differs"
            )
        candidates.add(str(fixture["candidate_id"]))
        scenarios.add(str(fixture["scenario_id"]))
    if len(candidates) < 2 or len(scenarios) < 2:
        raise ValueError("Intraday Fed Policy Absorption 001 launch equivalence lacks design span")


def _verify_launch_source_lineage(
    repository: Path, implementation_commit: str, runtime_commit: str
) -> None:
    implementation_commit = _validated_source_commit(implementation_commit)
    runtime_commit = _validated_source_commit(runtime_commit)
    if implementation_commit == runtime_commit:
        return
    command = (
        "git",
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-C",
        str(repository.resolve()),
    )
    environment = non_broker_subprocess_environment()
    environment.update({"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"})
    try:
        ancestor = subprocess.run(
            (*command, "merge-base", "--is-ancestor", implementation_commit, runtime_commit),
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        changed = subprocess.run(
            (*command, "diff", "--name-only", implementation_commit, runtime_commit, "--"),
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(
            "Intraday Fed Policy Absorption 001 launch source lineage is unavailable"
        ) from error
    paths = frozenset(line for line in changed.stdout.splitlines() if line)
    required = {
        LAUNCH_CONTROL_RELATIVE_PATH.as_posix(),
        "src/systematic_trading_lab/intraday_fed_policy_absorption_001_launch_control.py",
    }
    if (
        ancestor.returncode != 0
        or not required.issubset(paths)
        or not paths.issubset(_LAUNCH_CONTROL_POST_REVIEW_FILES)
    ):
        raise ValueError("Intraday Fed Policy Absorption 001 launch source lineage differs")


def _require_exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"Fed Policy Absorption 001 {label} fields differ")


def _validated_source_commit(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("Fed Policy Absorption 001 launch source commit differs")
    return value


def _required_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"Fed Policy Absorption 001 {label} differs")
    return value


def _required_positive_decimal_text(value: object, label: str) -> None:
    try:
        parsed = Decimal(str(value))
    except Exception as error:
        raise ValueError(f"Fed Policy Absorption 001 {label} differs") from error
    if not isinstance(value, str) or not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"Fed Policy Absorption 001 {label} differs")


def _equivalence_specification(
    plan: Any,
    model: Any,
    configuration: FedPolicyAbsorptionConfiguration,
    scenario_id: str,
    source_commit: str,
) -> dict[str, object]:
    scenario = _scenarios(model)[scenario_id]
    bars_fingerprint = fingerprint(_synthetic_equivalence_bars())
    return cast(
        dict[str, object],
        canonicalize(
            {
                "schema_version": RUN_SCHEMA,
                "program_id": PROGRAM_ID,
                "runner_version": RUNNER_VERSION,
                "engine_version": ENGINE_VERSION,
                "strategy_version": STRATEGY_VERSION,
                "source_commit": source_commit,
                "plan_sha256": plan.sha256,
                "plan_fingerprint": plan.plan_fingerprint,
                "plan_review_sha256": plan.review_sha256,
                "plan_review_fingerprint": plan.review_fingerprint,
                "autonomous_program_sha256": plan.payload["autonomous_program"]["sha256"],
                "autonomous_program_fingerprint": plan.payload["autonomous_program"]["fingerprint"],
                "source_state_sha256": plan.source_state_sha256,
                "source_state_fingerprint": plan.source_state_fingerprint,
                "state_sha256": plan.state_sha256,
                "state_fingerprint": plan.state_fingerprint,
                "calendar_sha256": plan.calendar_sha256,
                "calendar_fingerprint": plan.calendar_fingerprint,
                "source_evidence_sha256": plan.source_evidence_sha256,
                "source_evidence_fingerprint": plan.source_evidence_fingerprint,
                "attestation_sha256": ATTESTATION_SHA256,
                "attestation_fingerprint": ATTESTATION_FINGERPRINT,
                "cost_model_sha256": model.sha256,
                "cost_model_fingerprint": model.model_fingerprint,
                "cost_model": {
                    "model_id": model.payload["cost_model_id"],
                    "sha256": model.sha256,
                    "fingerprint": model.model_fingerprint,
                    "run_scenario_id": scenario_id,
                    "cost_model_scenario_id": _COST_MODEL_SCENARIO_IDS[scenario_id],
                    "slippage_bps_per_fill": scenario.slippage_bps_per_fill,
                    "execution_delay_bars": scenario.execution_delay_bars,
                    "regulatory_fee_model_id": scenario.regulatory_fee_model_id,
                },
                "configuration": _configuration_summary(configuration),
                "period": canonicalize(_EQUIVALENCE_PERIOD),
                "dataset_inputs": [
                    {
                        "dataset_id": f"synthetic-{bars_fingerprint}",
                        "fingerprint": bars_fingerprint,
                        "raw_fingerprint": bars_fingerprint,
                        "read_start": _EQUIVALENCE_PERIOD.context_start,
                        "read_end": _EQUIVALENCE_PERIOD.evaluation_end,
                        "evaluation_read_start": _EQUIVALENCE_PERIOD.evaluation_start,
                        "evaluation_read_end": _EQUIVALENCE_PERIOD.evaluation_end,
                    }
                ],
                "execution": plan.payload["execution"],
                "context": {
                    "stage": "synthetic-equivalence",
                    "base_candidate_id": None,
                    "candidate_id": configuration.candidate_id,
                    "family_id": STRATEGY_VERSION,
                    "period_id": _EQUIVALENCE_PERIOD.period_id,
                    "scenario_id": scenario_id,
                },
                "synthetic_fixture": True,
                "protected_inputs_accessed": False,
                "authority": _AUTHORITY,
            }
        ),
    )


def _parallel_equivalence(repository: Path, *, source_commit: str) -> dict[str, object]:
    plan = load_intraday_fed_policy_absorption_001_plan(repository.resolve())
    model = load_intraday_execution_cost_model(repository.resolve())
    choices = (
        (plan.configurations[0], "normal"),
        (plan.configurations[0], "zero_cost_diagnostic"),
        (plan.configurations[4], "normal"),
        (plan.configurations[4], "stress_a"),
        (plan.configurations[8], "normal-delay-3"),
    )
    specifications = tuple(
        _equivalence_specification(plan, model, configuration, scenario_id, source_commit)
        for configuration, scenario_id in choices
    )
    factory = _EquivalenceWorkerFactory(repository.resolve())
    preflight_process_stage(specifications, worker_factory=factory)
    started = time.perf_counter()
    sequential = run_process_stage(
        specifications,
        worker_factory=factory,
        workers=1,
        progress=lambda _done, _total, _task, _result: None,
    )
    sequential_seconds = time.perf_counter() - started
    started = time.perf_counter()
    parallel = run_process_stage(
        specifications,
        worker_factory=factory,
        workers=4,
        progress=lambda _done, _total, _task, _result: None,
    )
    parallel_seconds = time.perf_counter() - started
    fixtures: list[dict[str, object]] = []
    equivalent = True
    for left_value, right_value in zip(sequential, parallel, strict=True):
        left = _mapping(left_value, "sequential equivalence result")
        right = _mapping(right_value, "parallel equivalence result")
        comparisons = {
            "specification_equal": left["specification"] == right["specification"],
            "run_fingerprint_equal": left["run_fingerprint"] == right["run_fingerprint"],
            "cross_scenario_trace_hash_equal": left["cross_scenario_trace_hash"]
            == right["cross_scenario_trace_hash"],
            "execution_trace_hash_equal": left["execution_trace_hash"]
            == right["execution_trace_hash"],
            "metrics_equal": left["metrics"] == right["metrics"],
            "event_ledger_equal": left["event_ledger"] == right["event_ledger"],
            "canonical_report_equal": left["report_bytes"] == right["report_bytes"],
            "report_sha256_equal": left["report_sha256"] == right["report_sha256"],
            "report_fingerprint_equal": left["report_fingerprint"] == right["report_fingerprint"],
        }
        equivalent = equivalent and left == right and all(comparisons.values())
        fixtures.append(
            {
                "run_id": left["run_id"],
                "candidate_id": left["candidate_id"],
                "scenario_id": left["scenario_id"],
                "run_fingerprint": left["run_fingerprint"],
                "cross_scenario_trace_hash": left["cross_scenario_trace_hash"],
                "execution_trace_hash": left["execution_trace_hash"],
                "report_sha256": left["report_sha256"],
                "report_fingerprint": left["report_fingerprint"],
                **comparisons,
            }
        )
    if not equivalent:
        raise ValueError("Fed Policy Absorption 001 one-worker/four-worker equivalence differs")
    by_identity = {(str(item["candidate_id"]), str(item["scenario_id"])): item for item in fixtures}
    for candidate, left_scenario, right_scenario in (
        (plan.configurations[0].candidate_id, "normal", "zero_cost_diagnostic"),
        (plan.configurations[4].candidate_id, "normal", "stress_a"),
    ):
        left = by_identity[(candidate, left_scenario)]
        right = by_identity[(candidate, right_scenario)]
        if (
            left["cross_scenario_trace_hash"] != right["cross_scenario_trace_hash"]
            or left["execution_trace_hash"] == right["execution_trace_hash"]
        ):
            raise ValueError("Fed Policy Absorption 001 synthetic scenario traces differ")
    sequential_text = f"{max(sequential_seconds, 0.000001):.6f}"
    parallel_text = f"{max(parallel_seconds, 0.000001):.6f}"
    speedup_text = f"{max(sequential_seconds / parallel_seconds, 0.000001):.6f}"
    return {
        "schema_version": "intraday-fed-policy-absorption-001-parallel-equivalence-v1",
        "program_id": PROGRAM_ID,
        "verification_source_commit": source_commit,
        "fixture_kind": "synthetic-non-protected-five-minute-bars",
        "protected_inputs_accessed": False,
        "worker_counts": [1, 4],
        "comparisons": list(_LAUNCH_CONTROL_EQUIVALENCE_COMPARISONS),
        "fixture_count": len(fixtures),
        "sequential_seconds": sequential_text,
        "parallel_seconds": parallel_text,
        "speedup": speedup_text,
        "fixtures": fixtures,
        "equivalent": True,
    }


def verify_intraday_fed_policy_absorption_001_parallel_equivalence(
    repository: Path,
) -> dict[str, object]:
    repository = repository.resolve()
    return _parallel_equivalence(repository, source_commit=_source_commit(repository))


def intraday_fed_policy_absorption_001_plan_summary(repository: Path) -> dict[str, object]:
    plan = load_intraday_fed_policy_absorption_001_plan(repository.resolve())
    launch_control_bound = (
        REVIEWED_LAUNCH_CONTROL_SHA256 is not None
        and REVIEWED_LAUNCH_CONTROL_FINGERPRINT is not None
        and (repository / LAUNCH_CONTROL_RELATIVE_PATH).is_file()
    )
    return {
        "program_id": PROGRAM_ID,
        "status": (
            "launch-control-bound"
            if launch_control_bound
            else "implementation-launch-review-pending"
        ),
        "plan_sha256": plan.sha256,
        "plan_fingerprint": plan.plan_fingerprint,
        "calendar_sha256": plan.calendar_sha256,
        "calendar_fingerprint": plan.calendar_fingerprint,
        "source_evidence_sha256": plan.source_evidence_sha256,
        "source_evidence_fingerprint": plan.source_evidence_fingerprint,
        "plan_review_sha256": plan.review_sha256,
        "plan_review_fingerprint": plan.review_fingerprint,
        "parent_configuration_count": len(plan.configurations),
        "discovery_run_count": len(plan.configurations) * 2,
        "period_count": len(plan.periods),
        "eligible_event_count": len(plan.events),
        "excluded_event_count": 0,
        "default_workers": DEFAULT_RESEARCH_WORKERS,
        "launch_control_bound": launch_control_bound,
        "controlled_range_status": "none-eligible",
        "authority": _AUTHORITY,
    }


def intraday_fed_policy_absorption_001_status(data_home: Path) -> dict[str, object]:
    runtime = data_home.resolve() / PROGRAM_ID
    database = runtime / DATABASE_NAME
    counts = {status: 0 for status in _STATUSES}
    attempts = 0
    failures: dict[str, int] = {}
    if database.exists():
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only = ON")
        try:
            for status, count in connection.execute(
                "SELECT status, COUNT(*) FROM research_runs GROUP BY status"
            ).fetchall():
                counts[str(status)] = int(count)
            attempts = int(
                connection.execute(
                    "SELECT COALESCE(SUM(attempt_count), 0) FROM research_runs"
                ).fetchone()[0]
            )
            for failure_class, failure_reason in connection.execute(
                "SELECT failure_class, failure_reason FROM research_runs "
                "WHERE failure_class IS NOT NULL"
            ).fetchall():
                display_class = str(failure_class)
                if display_class == "data" and str(failure_reason).startswith(
                    _CALENDAR_FAILURE_PREFIX
                ):
                    display_class = "calendar"
                failures[display_class] = failures.get(display_class, 0) + 1
        finally:
            connection.close()
    final_path = runtime / "final-report.json"
    final: Mapping[str, Any] | None = None
    if final_path.exists():
        final = _read_final_report(final_path)
        _validate_final_evidence(runtime, final)
    return {
        "program_id": PROGRAM_ID,
        "database_exists": database.exists(),
        "run_counts": counts,
        "attempt_count": attempts,
        "failure_counts": failures,
        "terminal": final is not None,
        "outcome": None if final is None else final.get("outcome"),
        "cohort_size": (
            None if final is None else _mapping(final.get("counts"), "final counts").get("cohort")
        ),
        "authority": _AUTHORITY,
    }


def run_intraday_fed_policy_absorption_001_campaign(
    repository: Path,
    data_home: Path,
    *,
    workers: int = DEFAULT_RESEARCH_WORKERS,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    return IntradayFedPolicyAbsorption001Runner(
        repository,
        data_home,
        workers=workers,
        progress=progress,
    ).run()
