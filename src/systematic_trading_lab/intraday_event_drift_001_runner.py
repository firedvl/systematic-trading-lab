"""Restart-safe process runner for Intraday Event Drift 001."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
from types import MappingProxyType
from typing import Any, cast

from .calendar import expected_bar_timestamps
from .config import non_broker_subprocess_environment
from .datasets import DatasetService
from .domain import OHLCVBar, Symbol, Timeframe
from .fingerprints import canonical_json, canonicalize, fingerprint
from .intraday_event_drift_001_launch_control import (
    REVIEWED_LAUNCH_CONTROL_FINGERPRINT,
    REVIEWED_LAUNCH_CONTROL_SHA256,
)
from .intraday_event_drift_001_plan import (
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
    EventDriftConfiguration,
    EventDriftEvent,
    EventDriftPeriod,
    load_intraday_event_drift_001_plan,
)
from .intraday_event_drift_001_strategies import ScheduledBroadIndexPositiveDriftStrategy
from .intraday_execution_cost_model import load_intraday_execution_cost_model
from .intraday_exposed_002_engine import Exposed002ReplayResult, IntradayExposed002Engine
from .intraday_exposed_002_runner import (
    IntradayExposed002Runner,
    _account_day,
    _DatasetBinding,
    _exclusive_file_lock,
    _gate_results,
    _gates,
    _ledger_metric,
    _mapping,
    _mapping_items,
    _optional_decimal,
    _optional_report_metric,
    _positive_concentration,
    _positive_int,
    _report_metric,
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
from .intraday_exposed_002_runner import _aggregate_reports as _source_aggregate_reports
from .intraday_exposed_002_runner import _run_report as _source_run_report
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

RUNNER_VERSION = "intraday-event-drift-001-runner-v1"
RUN_SCHEMA = "intraday-event-drift-001-run-v1"
RUN_REPORT_SCHEMA = "intraday-event-drift-001-backtest-report-v1"
FINAL_FREEZE_SCHEMA = "intraday-event-drift-001-final-freeze-v1"
FINAL_REPORT_SCHEMA = "intraday-event-drift-001-final-report-v1"
PROGRAM_BINDING_SCHEMA = "intraday-event-drift-001-program-binding-v1"
DATABASE_NAME = "intraday-event-drift-001.sqlite3"
ENGINE_VERSION = "intraday-exposed-002-engine-v1"
STRATEGY_VERSION = "scheduled-broad-index-positive-drift-v1"
LAUNCH_CONTROL_RELATIVE_PATH = Path(
    "config/research/intraday-event-drift-001-launch-control-review-v1.json"
)
_LAUNCH_CONTROL_SCHEMA = "intraday-event-drift-001-launch-control-review-v1"
_LAUNCH_CONTROL_FILES = (
    "src/systematic_trading_lab/research_attempts.py",
    "src/systematic_trading_lab/research_executor.py",
    "src/systematic_trading_lab/intraday_exposed_002_engine.py",
    "src/systematic_trading_lab/intraday_event_drift_001_plan.py",
    "src/systematic_trading_lab/intraday_event_drift_001_strategies.py",
    "src/systematic_trading_lab/intraday_event_drift_001_runner.py",
    "src/systematic_trading_lab/public_cli.py",
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
    "decision-trace-fingerprint",
    "fill-trace-fingerprint",
    "round-trip-fingerprint",
    "metrics",
    "event-ledger",
    "canonical-report-bytes",
    "canonical-report-sha256",
    "report-fingerprint",
)
_LAUNCH_CONTROL_POST_REVIEW_FILES = frozenset(
    {
        LAUNCH_CONTROL_RELATIVE_PATH.as_posix(),
        "src/systematic_trading_lab/intraday_event_drift_001_launch_control.py",
        "tests/unit/test_intraday_event_drift_001_runner.py",
        "CURRENT_STATE.md",
        "DECISIONS.md",
        "ROADMAP.md",
        "docs/research-campaigns/intraday-event-drift-001-program.md",
    }
)
_STATUSES = ("pending", "running", "completed", "failed")
_LEASE_TIMEOUT = timedelta(seconds=300)
_HEARTBEAT_INTERVAL = timedelta(seconds=60)
_ZERO = Decimal("0")
_ACCOUNTING_PRECISION = Decimal("0.000000000001")
_CALENDAR_FAILURE_PREFIX = "calendar-integrity: "
_RELEASE_NAMES = (
    "Consumer Price Index",
    "Employment Situation",
    "Producer Price Index",
)
_EQUIVALENCE_PERIOD = EventDriftPeriod(
    "synthetic-equivalence-2026-01-08-through-09",
    datetime(2026, 1, 7, 14, 30, tzinfo=UTC),
    datetime(2026, 1, 8, 14, 30, tzinfo=UTC),
    datetime(2026, 1, 9, 20, 55, tzinfo=UTC),
    2,
    2,
)
_EQUIVALENCE_EVENTS = (
    EventDriftEvent(
        "synthetic-cpi-2026-01-08",
        "Consumer Price Index",
        "2026-01-08T13:30:00Z",
        "2026-01-08",
        "2026-01-08T14:30:00Z",
        "2026-01-08T21:00:00Z",
        "eligible",
    ),
    EventDriftEvent(
        "synthetic-ppi-2026-01-09",
        "Producer Price Index",
        "2026-01-09T13:30:00Z",
        "2026-01-09",
        "2026-01-09T14:30:00Z",
        "2026-01-09T21:00:00Z",
        "eligible",
    ),
)
_AUTHORITY = MappingProxyType(
    {
        "research_qualification": False,
        "controlled_evaluation": False,
        "protected_holdout": False,
        "paper_execution": False,
        "broker_writes": False,
        "live_execution": False,
    }
)


class IntradayEventDrift001Store:
    """Campaign view over the generic append-only attempt store."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.attempts = ResearchAttemptStore(
            self.root,
            database_name=DATABASE_NAME,
            lease_timeout=_LEASE_TIMEOUT,
            reconcile_on_open=False,
            attempt_id_prefix="ied001a-",
        )
        self.path = self.attempts.path

    def bind(self, value: Mapping[str, object]) -> None:
        self.attempts.bind(value)

    def reserve(self, specifications: Sequence[Mapping[str, object]]) -> None:
        run_ids = tuple(_run_id(value) for value in specifications)
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("Event Drift 001 run specifications collide")
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


@dataclass(frozen=True)
class _WorkerFactory:
    repository: Path
    data_home: Path
    runtime_root: Path
    source_commit: str

    def __call__(self) -> _Worker:
        return _Worker(self.repository, self.data_home, self.runtime_root, self.source_commit)


class _Worker:
    """One process worker with private immutable dataset state."""

    def __init__(
        self,
        repository: Path,
        data_home: Path,
        runtime_root: Path,
        source_commit: str,
    ) -> None:
        self.repository = repository.resolve()
        self.data_home = data_home.resolve()
        self.source_commit = source_commit
        self.plan = load_intraday_event_drift_001_plan(self.repository)
        self.cost_model = load_intraday_execution_cost_model(self.repository)
        self.datasets = _dataset_bindings(self.plan.payload)
        self.data_by_dataset = _read_only_dataset_services(self.data_home, self.datasets)
        IntradayExposed002Runner._verify_datasets(cast(Any, self))
        self.scenarios = _scenarios(self.cost_model)
        self._bar_cache: dict[str, tuple[Any, ...]] = {}
        self.attempt_store = IntradayEventDrift001Store(runtime_root)

    def __call__(self, specification: Mapping[str, object]) -> str:
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
                strategy = ScheduledBroadIndexPositiveDriftStrategy(
                    configuration.candidate_id,
                    configuration.reaction_bars,
                    configuration.minimum_reaction_bps,
                    frozenset(
                        date.fromisoformat(str(event.xnys_session))
                        for event in self.plan.eligible_events
                    ),
                    period.evaluation_start,
                )
                failure_class = "data"
                bars = IntradayExposed002Runner._bars(cast(Any, self), cast(Any, period))
                failure_class = "candidate"
                result = IntradayExposed002Engine(
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

    def _configuration(self, candidate_id: str) -> EventDriftConfiguration:
        for item in self.plan.configurations:
            if item.candidate_id == candidate_id:
                return item
        raise ValueError(f"unknown Event Drift 001 candidate: {candidate_id}")

    def _period(self, period_id: str) -> EventDriftPeriod:
        for item in self.plan.periods:
            if item.period_id == period_id:
                return item
        raise ValueError(f"unknown Event Drift 001 period: {period_id}")


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
        strategy = ScheduledBroadIndexPositiveDriftStrategy(
            candidate_id,
            cast(int, configuration["reaction_bars"]),
            Decimal(str(configuration["minimum_reaction_bps"])),
            frozenset({date(2026, 1, 8), date(2026, 1, 9)}),
            _EQUIVALENCE_PERIOD.evaluation_start,
        )
        scenario = self.scenarios[
            _text(_mapping(specification["context"], "context"), "scenario_id")
        ]
        bars = _synthetic_equivalence_bars()
        result = IntradayExposed002Engine(
            Decimal("100000"), scenario, self.model.regulatory_fees
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
            "decision_trace_fingerprint": details["decision_trace_fingerprint"],
            "fill_trace_fingerprint": details["fill_trace_fingerprint"],
            "round_trip_fingerprint": details["round_trip_fingerprint"],
            "metrics": report["metrics"],
            "event_ledger": details["event_ledger"],
            "report_bytes": report_bytes,
            "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "report_fingerprint": report["report_fingerprint"],
        }


class IntradayEventDrift001Runner:
    """Coordinate immutable Event Drift stages through spawned workers."""

    def __init__(
        self,
        repository: Path,
        data_home: Path,
        *,
        workers: int = DEFAULT_RESEARCH_WORKERS,
        progress: Callable[[str], None] | None = None,
        data_service: DatasetService | None = None,
    ) -> None:
        if isinstance(workers, bool) or workers < 1:
            raise ValueError("research worker count must be a positive integer")
        self.repository = repository.resolve()
        self.data_home = data_home.resolve()
        if REVIEWED_LAUNCH_CONTROL_SHA256 is None or REVIEWED_LAUNCH_CONTROL_FINGERPRINT is None:
            raise ValueError("Intraday Event Drift 001 launch control review is not hash-bound")
        self.source_commit = _source_commit(self.repository)
        self.launch_control = _load_launch_control(
            self.repository,
            source_commit=self.source_commit,
        )
        self.workers = workers
        self.progress = progress or (lambda _message: None)
        self.plan = load_intraday_event_drift_001_plan(self.repository)
        self.cost_model = load_intraday_execution_cost_model(self.repository)
        self.datasets = _dataset_bindings(self.plan.payload)
        self.data_by_dataset = (
            {binding.dataset_id: data_service for binding in self.datasets}
            if data_service is not None
            else _read_only_dataset_services(self.data_home, self.datasets)
        )
        self._verify_datasets()
        self.runtime_root = self.data_home / PROGRAM_ID
        self.attempt_store = IntradayEventDrift001Store(self.runtime_root)
        self.store = cast(Any, self.attempt_store)
        self.scenarios = _scenarios(self.cost_model)
        self._bar_cache: dict[str, tuple[Any, ...]] = {}
        self.attempt_store.bind(self._program_binding())

    def _verify_datasets(self) -> None:
        IntradayExposed002Runner._verify_datasets(cast(Any, self))

    def run(self) -> dict[str, object]:
        with _exclusive_file_lock(self.runtime_root / "campaign.lock"):
            existing = self._load_final_report_if_present()
            if existing is not None:
                return self._result(existing)
            try:
                self.attempt_store.reconcile_reports()
                self.attempt_store.expire_stale()
                self._require_no_failures()
                discovery = self._run_discovery()
                walk_forward = self._run_walk_forward(discovery)
                serious = self._run_serious(walk_forward)
                cohort = self._select_cohort(serious)
                freeze = self._freeze(discovery, walk_forward, serious, cohort)
                final = self._final_report(discovery, walk_forward, serious, cohort, freeze)
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
                "default_workers": DEFAULT_RESEARCH_WORKERS,
                "worker_count_configurable": True,
                "maximum_active_claims_per_worker": 1,
                "worker_count_excluded_from_run_identity": True,
            },
            "launch_control": self.launch_control,
            "authority": _AUTHORITY,
        }

    def _plan_evidence(self) -> dict[str, object]:
        return {
            "sha256": self.plan.sha256,
            "fingerprint": self.plan.plan_fingerprint,
            "calendar_sha256": self.plan.calendar_sha256,
            "calendar_fingerprint": self.plan.calendar_fingerprint,
            "source_evidence_sha256": self.plan.source_evidence_sha256,
            "source_evidence_fingerprint": self.plan.source_evidence_fingerprint,
            "review_sha256": self.plan.review_sha256,
            "review_fingerprint": self.plan.review_fingerprint,
        }

    def _specification(
        self,
        stage: str,
        configuration: EventDriftConfiguration,
        period: EventDriftPeriod,
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
            "event_calendar_sha256": self.plan.calendar_sha256,
            "event_calendar_fingerprint": self.plan.calendar_fingerprint,
            "event_source_evidence_sha256": self.plan.source_evidence_sha256,
            "event_source_evidence_fingerprint": self.plan.source_evidence_fingerprint,
            "plan_review_sha256": self.plan.review_sha256,
            "plan_review_fingerprint": self.plan.review_fingerprint,
            "cost_model": {
                "model_id": self.cost_model.payload["cost_model_id"],
                "sha256": self.cost_model.sha256,
                "fingerprint": self.cost_model.model_fingerprint,
                "scenario_id": scenario.scenario_id,
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
        worker_factory = _WorkerFactory(
            self.repository,
            self.data_home,
            self.runtime_root,
            self.source_commit,
        )
        preflight_process_stage(specifications, worker_factory=worker_factory)
        self.attempt_store.reserve(specifications)
        pending: list[Mapping[str, object]] = []
        for specification in specifications:
            run_id = _run_id(specification)
            row = self.attempt_store.get(run_id)
            if row["status"] == "completed":
                self._load_report(row)
            elif row["status"] == "failed":
                raise AttemptStateError(f"Event Drift 001 run is terminal: {run_id}")
            elif row["status"] == "running":
                raise AttemptStateError(f"Event Drift 001 run has an active attempt: {run_id}")
            else:
                pending.append(specification)
        run_process_stage(
            tuple(pending),
            worker_factory=worker_factory,
            workers=self.workers,
            progress=lambda done, total, _task, result: self.progress(f"{done}/{total} {result}"),
        )
        for specification in specifications:
            self._load_report(self.attempt_store.get(_run_id(specification)))

    def _configuration(self, candidate_id: str) -> EventDriftConfiguration:
        for item in self.plan.configurations:
            if item.candidate_id == candidate_id:
                return item
        raise ValueError(f"unknown Event Drift 001 candidate: {candidate_id}")

    def _period(self, period_id: str) -> EventDriftPeriod:
        for item in self.plan.periods:
            if item.period_id == period_id:
                return item
        raise ValueError(f"unknown Event Drift 001 period: {period_id}")

    def _load_report(self, row: Mapping[str, object]) -> Mapping[str, Any]:
        if row.get("status") != "completed":
            raise ValueError("Event Drift 001 run is not completed")
        relative = Path(_required_text(row.get("report_path"), "report path"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Event Drift 001 report path is unsafe")
        raw = (self.runtime_root / relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row.get("report_sha256"):
            raise ValueError("Event Drift 001 report SHA-256 differs")
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
            or value.get("event_calendar_sha256") != specification.get("event_calendar_sha256")
            or value.get("event_calendar_fingerprint")
            != specification.get("event_calendar_fingerprint")
            or value.get("event_source_evidence_sha256")
            != specification.get("event_source_evidence_sha256")
            or value.get("event_source_evidence_fingerprint")
            != specification.get("event_source_evidence_fingerprint")
            or value.get("plan_sha256") != specification.get("plan_sha256")
            or value.get("plan_fingerprint") != specification.get("plan_fingerprint")
            or value.get("dataset_inputs") != specification.get("dataset_inputs")
            or value.get("cost_model_fingerprint") != cost_model.get("fingerprint")
            or value.get("source_commit") != specification.get("source_commit")
            or value.get("authority") != _AUTHORITY
        ):
            raise ValueError("Event Drift 001 report fingerprint differs")
        return value

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
        if normal_evidence.get("decision_trace_fingerprint") != zero_evidence.get(
            "decision_trace_fingerprint"
        ):
            raise ValueError("Event Drift 001 paired decision traces differ")
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
            raise ValueError("Event Drift 001 run relationship differs")
        return self._load_report(matches[0])

    def _require_no_failures(self) -> None:
        failed = tuple(row for row in self.attempt_store.list_runs() if row["status"] == "failed")
        if failed:
            raise AttemptStateError(
                f"Event Drift 001 has {len(failed)} terminal failed run(s); no retry is allowed"
            )

    def _run_discovery(self) -> dict[str, object]:
        period = self.plan.periods[0]
        specifications = tuple(
            self._specification("discovery", configuration, period, scenario_id)
            for configuration in self.plan.configurations
            for scenario_id in ("normal", "zero_cost_diagnostic")
        )
        self._execute(specifications)
        gates = _gates(self.plan.payload, "discovery_screen", "gates")
        ledger: list[dict[str, object]] = []
        for configuration in self.plan.configurations:
            normal, zero = self._paired_reports(
                "discovery", configuration.candidate_id, period.period_id
            )
            values: dict[str, Decimal | int | None] = {
                "normal.total_return": _report_metric(normal, "total_return"),
                "zero_cost_diagnostic.total_return": _report_metric(zero, "total_return"),
                "normal.active_event_count": _report_metric(normal, "active_event_count"),
                "normal.completed_round_trips": _report_metric(normal, "completed_round_trips"),
                "normal.max_drawdown": _report_metric(normal, "max_drawdown"),
                "normal.cost_to_gross_profit": _optional_report_metric(
                    normal, "cost_to_gross_profit"
                ),
                "normal.average_gross_trade_edge_bps": _optional_report_metric(
                    normal, "average_gross_trade_edge_bps"
                ),
                "normal.positive_profit_symbol_concentration": _optional_report_metric(
                    normal, "positive_profit_symbol_concentration"
                ),
                "normal.positive_profit_event_concentration": _optional_report_metric(
                    normal, "positive_profit_event_concentration"
                ),
                "normal.positive_profit_release_class_concentration": _optional_report_metric(
                    normal, "positive_profit_release_class_concentration"
                ),
                "normal.accounting_identity_error": _report_metric(
                    normal, "accounting_identity_error"
                ),
            }
            gate_results = _gate_results(gates, values)
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
            _positive_int(screen.get("walk_forward_cap"), "walk-forward cap"),
            key=lambda item: (
                -_ledger_metric(item, "normal.total_return"),
                _ledger_metric(item, "normal.positive_profit_event_concentration"),
                _ledger_metric(item, "normal.cost_to_gross_profit"),
                _screen_candidate_id(item),
            ),
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
        gates = _gates(self.plan.payload, "walk_forward_screen", "gates")
        ledger: list[dict[str, object]] = []
        for candidate_id in selected:
            configuration = self._configuration(candidate_id)
            normal_reports: list[Mapping[str, Any]] = []
            zero_reports: list[Mapping[str, Any]] = []
            fold_runs: list[dict[str, object]] = []
            for period in periods:
                normal, zero = self._paired_reports("walk-forward", candidate_id, period.period_id)
                normal_reports.append(normal)
                zero_reports.append(zero)
                fold_runs.append(
                    {
                        "period_id": period.period_id,
                        "normal_run_id": normal["run_id"],
                        "zero_cost_run_id": zero["run_id"],
                    }
                )
            normal_aggregate = _aggregate_reports(tuple(normal_reports))
            zero_aggregate = _aggregate_reports(tuple(zero_reports))
            normal_returns = tuple(
                _report_metric(report, "total_return") for report in normal_reports
            )
            normal_drawdowns = tuple(
                _report_metric(report, "max_drawdown") for report in normal_reports
            )
            positive_normal = tuple(report for report in normal_reports if _positive_fold(report))
            values: dict[str, Decimal | int | None] = {
                "aggregate.normal.total_return": Decimal(str(normal_aggregate["total_return"])),
                "positive_normal_fold_count": len(positive_normal),
                "final_exposed_may.normal.total_return": normal_returns[-1],
                "final_exposed_may.normal.active_event_count": _report_metric(
                    normal_reports[-1], "active_event_count"
                ),
                "minimum_active_events_in_positive_normal_fold": (
                    min(_report_metric(report, "active_event_count") for report in positive_normal)
                    if positive_normal
                    else None
                ),
                "worst_normal_fold_return": min(normal_returns),
                "worst_normal_fold_drawdown": max(normal_drawdowns),
                "aggregate.normal.active_event_count": Decimal(
                    str(normal_aggregate["active_event_count"])
                ),
                "aggregate.normal.completed_round_trips": Decimal(
                    str(normal_aggregate["completed_round_trips"])
                ),
                "aggregate.normal.cost_to_gross_profit": _optional_decimal(
                    normal_aggregate.get("cost_to_gross_profit"), "aggregate cost ratio"
                ),
                "aggregate.normal.average_gross_trade_edge_bps": _optional_decimal(
                    normal_aggregate.get("average_gross_trade_edge_bps"),
                    "aggregate trade edge",
                ),
                "aggregate.normal.positive_profit_symbol_concentration": _optional_decimal(
                    normal_aggregate.get("positive_profit_symbol_concentration"),
                    "aggregate symbol concentration",
                ),
                "aggregate.normal.positive_profit_event_concentration": _optional_decimal(
                    normal_aggregate.get("positive_profit_event_concentration"),
                    "aggregate event concentration",
                ),
                "aggregate.normal.positive_profit_release_class_concentration": (
                    _optional_decimal(
                        normal_aggregate.get("positive_profit_release_class_concentration"),
                        "aggregate release concentration",
                    )
                ),
                "aggregate.normal.accounting_identity_error": Decimal(
                    str(normal_aggregate["accounting_identity_error"])
                ),
            }
            gate_results = _gate_results(gates, values)
            ledger.append(
                {
                    "candidate": _configuration_summary(configuration),
                    "fold_runs": fold_runs,
                    "normal_aggregate": normal_aggregate,
                    "zero_cost_aggregate": zero_aggregate,
                    "metrics": values,
                    "gate_results": gate_results,
                    "eligible": all(item["passed"] is True for item in gate_results),
                    "selected": False,
                }
            )
        screen = _mapping(self.plan.payload.get("walk_forward_screen"), "walk-forward screen")
        selected_serious = _select_eligible(
            ledger,
            _positive_int(screen.get("serious_candidate_cap"), "serious candidate cap"),
            key=lambda item: (
                -_ledger_metric(item, "positive_normal_fold_count"),
                -_ledger_metric(item, "aggregate.normal.total_return"),
                _ledger_metric(item, "aggregate.normal.positive_profit_event_concentration"),
                _screen_candidate_id(item),
            ),
        )
        for item in ledger:
            item["selected"] = _screen_candidate_id(item) in selected_serious
        return {
            "stage": "walk-forward",
            "candidate_count": len(ledger),
            "paired_run_count": len(specifications),
            "eligible_count": sum(item["eligible"] is True for item in ledger),
            "selected_candidate_ids": selected_serious,
            "ledger": ledger,
        }

    def _run_serious(self, walk_forward: Mapping[str, object]) -> dict[str, object]:
        selected = _strings(walk_forward.get("selected_candidate_ids"), "serious selection")
        periods = self.plan.periods[1:]
        stress_scenarios = ("stress_a", "stress_b", "normal-delay-2", "normal-delay-3")
        stress_specs = tuple(
            self._specification("stress", self._configuration(candidate_id), period, scenario_id)
            for candidate_id in selected
            for period in periods
            for scenario_id in stress_scenarios
        )
        neighbor_specs = tuple(
            self._specification(
                "neighbor",
                self._configuration(neighbor_id),
                period,
                scenario_id,
                base_candidate_id=base_candidate_id,
            )
            for base_candidate_id in selected
            for neighbor_id in self._configuration(base_candidate_id).neighbor_ids
            for period in periods
            for scenario_id in ("normal", "zero_cost_diagnostic")
        )
        self._execute(stress_specs + neighbor_specs)
        screen = _mapping(
            self.plan.payload.get("serious_candidate_screen"), "serious candidate screen"
        )
        stress_gates = _gates(screen, None, "stress_gates")
        neighbor_gates = _gates(screen, None, "neighbor_gates")
        walk_by_id = {
            _screen_candidate_id(item): item
            for item in _mapping_items(walk_forward.get("ledger"), "walk-forward ledger")
        }
        ledger: list[dict[str, object]] = []
        for candidate_id in selected:
            configuration = self._configuration(candidate_id)
            base = _mapping(walk_by_id[candidate_id], "base walk-forward screen")
            base_aggregate = _mapping(base.get("normal_aggregate"), "base aggregate")
            base_profit = Decimal(str(base_aggregate["net_profit_loss"]))
            stress_values: dict[str, Decimal | int | None] = {}
            stress_runs: list[dict[str, object]] = []
            for scenario_id in stress_scenarios:
                reports = tuple(
                    self._report_for("stress", candidate_id, period.period_id, scenario_id)
                    for period in periods
                )
                aggregate = _aggregate_reports(reports)
                stress_values[f"{scenario_id}.aggregate_total_return"] = Decimal(
                    str(aggregate["total_return"])
                )
                stress_values[f"{scenario_id}.positive_fold_count"] = sum(
                    _positive_fold(report) for report in reports
                )
                stress_values[f"{scenario_id}.normal_profit_retention"] = (
                    Decimal(str(aggregate["net_profit_loss"])) / base_profit
                    if base_profit > 0
                    else None
                )
                stress_runs.append(
                    {
                        "scenario_id": scenario_id,
                        "run_ids": [report["run_id"] for report in reports],
                        "aggregate": aggregate,
                    }
                )
            neighbor_profits: list[Decimal] = []
            neighbor_runs: list[dict[str, object]] = []
            for neighbor_id in configuration.neighbor_ids:
                normal_reports: list[Mapping[str, Any]] = []
                zero_reports: list[Mapping[str, Any]] = []
                for period in periods:
                    normal, zero = self._paired_reports(
                        "neighbor",
                        neighbor_id,
                        period.period_id,
                        base_candidate_id=candidate_id,
                    )
                    normal_reports.append(normal)
                    zero_reports.append(zero)
                normal_aggregate = _aggregate_reports(tuple(normal_reports))
                zero_aggregate = _aggregate_reports(tuple(zero_reports))
                neighbor_profits.append(Decimal(str(normal_aggregate["net_profit_loss"])))
                neighbor_runs.append(
                    {
                        "neighbor_id": neighbor_id,
                        "normal_run_ids": [report["run_id"] for report in normal_reports],
                        "zero_cost_run_ids": [report["run_id"] for report in zero_reports],
                        "normal_aggregate": normal_aggregate,
                        "zero_cost_aggregate": zero_aggregate,
                    }
                )
            positive_neighbors = sum(profit > 0 for profit in neighbor_profits)
            neighbor_values: dict[str, Decimal | int | None] = {
                "positive_neighbor_fraction": (
                    Decimal(positive_neighbors) / Decimal(len(neighbor_profits))
                    if neighbor_profits
                    else None
                ),
                "median_neighbor_normal_profit_retention": (
                    median(neighbor_profits) / base_profit
                    if neighbor_profits and base_profit > 0
                    else None
                ),
            }
            stress_gate_results = _gate_results(stress_gates, stress_values)
            neighbor_gate_results = _gate_results(neighbor_gates, neighbor_values)
            gate_results = stress_gate_results + neighbor_gate_results
            ledger.append(
                {
                    "candidate": _configuration_summary(configuration),
                    "base_normal_aggregate": base_aggregate,
                    "stress_runs": stress_runs,
                    "neighbor_runs": neighbor_runs,
                    "metrics": {**stress_values, **neighbor_values},
                    "gate_results": gate_results,
                    "eligible": all(item["passed"] is True for item in gate_results),
                    "selected": False,
                }
            )
        return {
            "stage": "serious-candidate",
            "candidate_count": len(ledger),
            "stress_run_count": len(stress_specs),
            "neighbor_run_count": len(neighbor_specs),
            "eligible_count": sum(item["eligible"] is True for item in ledger),
            "ledger": ledger,
        }

    def _select_cohort(self, serious: Mapping[str, object]) -> tuple[str, ...]:
        ledger = _mapping_items(serious.get("ledger"), "serious ledger")
        cohort = tuple(
            sorted(_screen_candidate_id(item) for item in ledger if item.get("eligible") is True)
        )
        if len(cohort) > 2:
            raise ValueError("Event Drift 001 final cohort exceeds its frozen maximum")
        for item in ledger:
            cast(dict[str, object], item)["selected"] = _screen_candidate_id(item) in cohort
        return cohort

    def _freeze(
        self,
        discovery: Mapping[str, object],
        walk_forward: Mapping[str, object],
        serious: Mapping[str, object],
        cohort: Sequence[str],
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
        payload: dict[str, object] = {
            "schema_version": FINAL_FREEZE_SCHEMA,
            "program_id": PROGRAM_ID,
            "status": "frozen-after-complete-exposed-screening",
            "source_commit": self.source_commit,
            "runner_version": RUNNER_VERSION,
            "engine_version": ENGINE_VERSION,
            "strategy_version": STRATEGY_VERSION,
            "plan": self._plan_evidence(),
            "cost_model": {
                "sha256": self.cost_model.sha256,
                "fingerprint": self.cost_model.model_fingerprint,
            },
            "datasets": [canonicalize(value) for value in self.datasets],
            "screened_ledger": {
                "discovery": discovery,
                "walk_forward": walk_forward,
                "serious": serious,
            },
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
        serious: Mapping[str, object],
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
                "INTRADAY EVENT DRIFT 001 COMPLETE — NO CONTROLLED-QUALIFIED CANDIDATE"
                if empty
                else "INTRADAY EVENT DRIFT 001 COMPLETE — WAITING FOR FUTURE UNTOUCHED DATA"
            ),
            "source_commit": self.source_commit,
            "complete_exposed_screening": True,
            "counts": {
                "discovery_parents": discovery["parent_count"],
                "discovery_runs": discovery["paired_run_count"],
                "walk_forward_candidates": walk_forward["candidate_count"],
                "walk_forward_runs": walk_forward["paired_run_count"],
                "serious_candidates": serious["candidate_count"],
                "stress_runs": serious["stress_run_count"],
                "neighbor_runs": serious["neighbor_run_count"],
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
            "terminal_message": "INTRADAY EVENT DRIFT 001 TERMINALLY INTERRUPTED",
            "source_commit": self.source_commit,
            "complete_exposed_screening": False,
            "counts": {
                "discovery_parents": None,
                "discovery_runs": None,
                "walk_forward_candidates": None,
                "walk_forward_runs": None,
                "serious_candidates": None,
                "stress_runs": None,
                "neighbor_runs": None,
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
    return f"ied001r-{fingerprint(specification)[:24]}"


def _reservation_id(run_fingerprint: str) -> str:
    return f"ied001q-{run_fingerprint[:24]}"


def _dataset_bindings(payload: Mapping[str, Any]) -> tuple[_DatasetBinding, ...]:
    data = _mapping(payload.get("data"), "plan data")
    values = data.get("dataset_bindings")
    if not isinstance(values, list) or len(values) != 4:
        raise ValueError("Event Drift 001 dataset bindings differ")
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
        raise ValueError("Event Drift 001 dataset ranges overlap")
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
                f"Event Drift 001 dataset location is missing: {binding.dataset_id}"
            ) from error
        resolved[binding.dataset_id] = service
    return MappingProxyType(resolved)


def _run_dataset_inputs(
    bindings: Sequence[_DatasetBinding], period: EventDriftPeriod
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
        raise ValueError("Event Drift 001 run has no dataset input")
    return inputs


def _configuration_summary(configuration: EventDriftConfiguration) -> dict[str, object]:
    return {
        "candidate_id": configuration.candidate_id,
        "strategy_id": STRATEGY_VERSION,
        "reaction_bars": configuration.reaction_bars,
        "minimum_reaction_bps": configuration.minimum_reaction_bps,
        "minimum_opening_gap_bps": Decimal("10"),
        "exit_bar_index": 60,
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
    return tuple(
        _screen_candidate_id(item)
        for item in sorted((item for item in ledger if item.get("eligible") is True), key=key)[:cap]
    )


def _positive_fold(report: Mapping[str, Any]) -> bool:
    return (
        _report_metric(report, "net_profit_loss") > 0 and _report_metric(report, "total_return") > 0
    )


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
        "paper_broker_or_live_state": False,
        "strategic_allocation_21": False,
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
        if day == date(2026, 1, 7):
            opening = closing = Decimal("100")
        elif day == date(2026, 1, 8):
            opening = Decimal("100.2") if index == 0 else Decimal("100.5")
            closing = (
                Decimal("100.3") + Decimal(index) / Decimal("10") if index < 12 else Decimal("102")
            )
        else:
            opening = closing = Decimal("101.8")
        for symbol in (Symbol("QQQ"), Symbol("SPY")):
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
    period: EventDriftPeriod,
    events: tuple[EventDriftEvent, ...],
    bars: Sequence[OHLCVBar],
) -> dict[str, object]:
    payload = _source_run_report(specification, result, period)  # type: ignore[arg-type]
    payload.pop("report_fingerprint")
    metrics = dict(_mapping(payload.get("metrics"), "report metrics"))
    details = dict(_mapping(payload.get("details"), "report details"))
    eligible = tuple(
        sorted(
            (
                event
                for event in events
                if event.eligible
                and event.xnys_session is not None
                and period.evaluation_start.date()
                <= date.fromisoformat(event.xnys_session)
                <= period.evaluation_end.date()
            ),
            key=lambda event: (event.scheduled_utc, event.event_id),
        )
    )
    if len(eligible) != period.eligible_event_count:
        raise ValueError("Event Drift 001 period event count differs")
    event_by_day = {date.fromisoformat(str(event.xnys_session)): event for event in eligible}
    if len(event_by_day) != len(eligible):
        raise ValueError("Event Drift 001 eligible event sessions collide")

    evaluation_fills = tuple(
        fill
        for fill in result.fills
        if period.evaluation_start <= fill.fill_timestamp <= period.evaluation_end
    )
    evaluation_round_trips = tuple(
        trade
        for trade in result.round_trips
        if period.evaluation_start <= trade.entry_timestamp
        and trade.exit_timestamp <= period.evaluation_end
    )
    if any(_account_day(fill.fill_timestamp) not in event_by_day for fill in evaluation_fills):
        raise ValueError("Event Drift 001 has an evaluated non-event fill")
    if any(
        _account_day(trade.entry_timestamp) != _account_day(trade.exit_timestamp)
        or _account_day(trade.entry_timestamp) not in event_by_day
        for trade in evaluation_round_trips
    ):
        raise ValueError("Event Drift 001 has an invalid event round trip")
    fees_by_day = {
        date.fromisoformat(item.account_day): item
        for item in result.fee_ledger
        if period.evaluation_start.date()
        <= date.fromisoformat(item.account_day)
        <= period.evaluation_end.date()
    }

    ledger: list[dict[str, object]] = []
    for event in eligible:
        day = date.fromisoformat(str(event.xnys_session))
        fills = tuple(fill for fill in evaluation_fills if _account_day(fill.fill_timestamp) == day)
        trades = tuple(
            trade for trade in evaluation_round_trips if _account_day(trade.entry_timestamp) == day
        )
        daily = fees_by_day.get(day)
        if daily is None:
            raise ValueError("Event Drift 001 event lacks a daily fee ledger")
        regulatory_fees = daily.charges.total
        active = bool(fills or trades)
        if not active:
            if regulatory_fees != _ZERO:
                raise ValueError("Event Drift 001 inactive event has regulatory fees")
            ledger.append(
                {
                    "event_id": event.event_id,
                    "release_name": event.release_name,
                    "scheduled_utc": event.scheduled_utc,
                    "xnys_session": event.xnys_session,
                    "active": False,
                    "entry_decision_timestamp": None,
                    "entry_fill_timestamp": None,
                    "exit_decision_timestamp": None,
                    "exit_fill_timestamp": None,
                    "gross_profit_loss": _ZERO,
                    "adverse_slippage": _ZERO,
                    "regulatory_fees": _ZERO,
                    "net_profit_loss": _ZERO,
                }
            )
            continue
        entries = tuple(fill for fill in fills if fill.quantity > 0)
        exits = tuple(fill for fill in fills if fill.quantity < 0)
        if (
            len(trades) != 2
            or {trade.symbol.value for trade in trades} != {"QQQ", "SPY"}
            or len(entries) != 2
            or len(exits) != 2
            or {fill.symbol.value for fill in entries} != {"QQQ", "SPY"}
            or {fill.symbol.value for fill in exits} != {"QQQ", "SPY"}
            or len({fill.decision_timestamp for fill in entries}) != 1
            or len({fill.fill_timestamp for fill in entries}) != 1
            or len({fill.decision_timestamp for fill in exits}) != 1
            or len({fill.fill_timestamp for fill in exits}) != 1
        ):
            raise ValueError("Event Drift 001 joint event execution differs")
        gross = sum((trade.gross_profit for trade in trades), _ZERO)
        slippage = sum((fill.adverse_slippage for fill in fills), _ZERO)
        ledger.append(
            {
                "event_id": event.event_id,
                "release_name": event.release_name,
                "scheduled_utc": event.scheduled_utc,
                "xnys_session": event.xnys_session,
                "active": True,
                "entry_decision_timestamp": entries[0].decision_timestamp,
                "entry_fill_timestamp": entries[0].fill_timestamp,
                "exit_decision_timestamp": exits[0].decision_timestamp,
                "exit_fill_timestamp": exits[0].fill_timestamp,
                "gross_profit_loss": gross,
                "adverse_slippage": slippage,
                "regulatory_fees": regulatory_fees,
                "net_profit_loss": gross - slippage - regulatory_fees,
            }
        )

    event_net = sum((Decimal(str(row["net_profit_loss"])) for row in ledger), _ZERO)
    reported_net = Decimal(str(metrics["net_profit_loss"]))
    reconciliation_error = abs(event_net - reported_net).quantize(_ACCOUNTING_PRECISION)
    if reconciliation_error != _ZERO:
        raise ValueError("Event Drift 001 event accounting does not reconcile")
    release_net = {
        name: sum(
            (Decimal(str(row["net_profit_loss"])) for row in ledger if row["release_name"] == name),
            _ZERO,
        )
        for name in _RELEASE_NAMES
    }
    active_count = sum(row["active"] is True for row in ledger)
    metrics.update(
        {
            "eligible_event_count": len(ledger),
            "active_event_count": active_count,
            "event_activation_fraction": (
                Decimal(active_count) / Decimal(len(ledger)) if ledger else None
            ),
            "event_net_profit_loss": event_net,
            "positive_profit_event_concentration": _positive_concentration(
                tuple(Decimal(str(row["net_profit_loss"])) for row in ledger)
            ),
            "release_class_net_profit_loss": release_net,
            "positive_profit_release_class_concentration": _positive_concentration(
                tuple(release_net.values())
            ),
            "event_accounting_reconciliation_error": reconciliation_error,
            "benchmark_references": _benchmark_references(bars, period),
        }
    )
    details.update({"event_ledger": ledger})
    payload.update(
        {
            "schema_version": RUN_REPORT_SCHEMA,
            "program_id": PROGRAM_ID,
            "run_id": _run_id(specification),
            "metrics": metrics,
            "details": details,
            "execution_evidence": {
                "decision_trace_fingerprint": details["decision_trace_fingerprint"],
                "transition_trace_fingerprint": details["transition_trace_fingerprint"],
                "fill_trace_fingerprint": details["fill_trace_fingerprint"],
                "round_trip_fingerprint": details["round_trip_fingerprint"],
                "daily_fee_ledger_fingerprint": details["daily_fee_ledger_fingerprint"],
            },
            "authority": _AUTHORITY,
        }
    )
    if specification.get("schema_version") == RUN_SCHEMA:
        cost_model = _mapping(specification.get("cost_model"), "report cost model")
        payload.update(
            {
                "event_calendar_sha256": specification["event_calendar_sha256"],
                "event_calendar_fingerprint": specification["event_calendar_fingerprint"],
                "event_source_evidence_sha256": specification["event_source_evidence_sha256"],
                "event_source_evidence_fingerprint": specification[
                    "event_source_evidence_fingerprint"
                ],
                "plan_sha256": specification["plan_sha256"],
                "plan_fingerprint": specification["plan_fingerprint"],
                "dataset_inputs": specification["dataset_inputs"],
                "cost_model_fingerprint": cost_model["fingerprint"],
                "source_commit": specification["source_commit"],
            }
        )
    payload["report_fingerprint"] = fingerprint(payload)
    return payload


def _benchmark_references(bars: Sequence[OHLCVBar], period: EventDriftPeriod) -> dict[str, Decimal]:
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
            raise ValueError("Event Drift 001 benchmark evaluation bars differ")
        returns[symbol.value] = evaluation[-1].close / evaluation[0].open - Decimal("1")
    return {
        "cash": _ZERO,
        "spy_continuous": returns["SPY"],
        "qqq_continuous": returns["QQQ"],
        "fixed_50_50_continuous": (returns["SPY"] + returns["QQQ"]) / Decimal("2"),
    }


def _aggregate_reports(reports: tuple[Mapping[str, Any], ...]) -> dict[str, object]:
    aggregate = _source_aggregate_reports(reports)
    ledger = [
        dict(row)
        for report in reports
        for row in _event_ledger(_mapping(report.get("details"), "report details"))
    ]
    event_ids = tuple(str(row["event_id"]) for row in ledger)
    if len(set(event_ids)) != len(event_ids):
        raise ValueError("Event Drift 001 aggregate event IDs collide")
    event_net = sum((Decimal(str(row["net_profit_loss"])) for row in ledger), _ZERO)
    reported_net = Decimal(str(aggregate["net_profit_loss"]))
    reconciliation_error = abs(event_net - reported_net).quantize(_ACCOUNTING_PRECISION)
    if reconciliation_error != _ZERO:
        raise ValueError("Event Drift 001 aggregate event accounting does not reconcile")
    release_net = {
        name: sum(
            (Decimal(str(row["net_profit_loss"])) for row in ledger if row["release_name"] == name),
            _ZERO,
        )
        for name in _RELEASE_NAMES
    }
    active_count = sum(row["active"] is True for row in ledger)
    aggregate.update(
        {
            "eligible_event_count": len(ledger),
            "active_event_count": active_count,
            "event_activation_fraction": (
                Decimal(active_count) / Decimal(len(ledger)) if ledger else None
            ),
            "event_ledger": ledger,
            "event_net_profit_loss": event_net,
            "positive_profit_event_concentration": _positive_concentration(
                tuple(Decimal(str(row["net_profit_loss"])) for row in ledger)
            ),
            "release_class_net_profit_loss": release_net,
            "positive_profit_release_class_concentration": _positive_concentration(
                tuple(release_net.values())
            ),
            "event_accounting_reconciliation_error": reconciliation_error,
        }
    )
    return aggregate


def _event_ledger(details: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    value = details.get("event_ledger")
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("Event Drift 001 event ledger differs")
    return tuple(value)


def _final_markdown(report: Mapping[str, object], json_sha256: str) -> str:
    counts = _mapping(report.get("counts"), "final counts")
    lines = [
        "# Intraday Event Drift 001 final report",
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
    if (
        value.get("schema_version") != FINAL_REPORT_SCHEMA
        or value.get("program_id") != PROGRAM_ID
        or (source_commit is not None and value.get("source_commit") != source_commit)
        or fingerprint(unsigned) != stored
        or value.get("authority") != _AUTHORITY
    ):
        raise ValueError("Event Drift 001 final report differs")
    return value


def _validate_final_evidence(runtime: Path, report: Mapping[str, Any]) -> None:
    database = _mapping(report.get("runtime_database"), "runtime database")
    if database.get("path") != DATABASE_NAME or database.get("sha256") != _sha256_path(
        runtime / DATABASE_NAME
    ):
        raise ValueError("Event Drift 001 runtime database differs")
    freeze_evidence = report.get("final_freeze")
    if freeze_evidence is None:
        return
    evidence = _mapping(freeze_evidence, "final freeze evidence")
    relative = _required_text(evidence.get("path"), "freeze path")
    if relative != "final-freeze.json":
        raise ValueError("Event Drift 001 final freeze path differs")
    freeze_path = runtime / relative
    freeze = _mapping(json.loads(freeze_path.read_bytes()), "final freeze")
    stored = _text(freeze, "freeze_fingerprint")
    unsigned = dict(freeze)
    del unsigned["freeze_fingerprint"]
    if (
        evidence.get("sha256") != _sha256_path(freeze_path)
        or evidence.get("fingerprint") != stored
        or freeze.get("schema_version") != FINAL_FREEZE_SCHEMA
        or freeze.get("program_id") != PROGRAM_ID
        or freeze.get("source_commit") != report.get("source_commit")
        or freeze.get("authority") != _AUTHORITY
        or fingerprint(unsigned) != stored
    ):
        raise ValueError("Event Drift 001 final freeze differs")


def _load_launch_control(repository: Path, *, source_commit: str) -> Mapping[str, Any]:
    if REVIEWED_LAUNCH_CONTROL_SHA256 is None or REVIEWED_LAUNCH_CONTROL_FINGERPRINT is None:
        raise ValueError("Intraday Event Drift 001 launch control review is not hash-bound")
    path = repository / LAUNCH_CONTROL_RELATIVE_PATH
    if not path.is_file():
        raise ValueError("Intraday Event Drift 001 launch control review is missing")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != REVIEWED_LAUNCH_CONTROL_SHA256:
        raise ValueError("Intraday Event Drift 001 launch control review SHA-256 differs")
    try:
        value = _mapping(json.loads(raw), "launch control review")
    except json.JSONDecodeError as error:
        raise ValueError(
            "Intraday Event Drift 001 launch control review is invalid JSON"
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
        raise ValueError("Intraday Event Drift 001 launch control review differs")
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
        raise ValueError("Intraday Event Drift 001 launch control review identity differs")
    for key in ("review_date", "review_method", "scope_limit"):
        _required_text(value.get(key), f"launch control {key.replace('_', ' ')}")
    _verify_launch_inputs(value)
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
        raise ValueError("Intraday Event Drift 001 launch independent review differs")
    _required_text(review.get("reviewer"), "launch independent reviewer")
    _verify_launch_source_lineage(repository, implementation_commit, source_commit)
    return MappingProxyType(dict(value))


def _verify_launch_inputs(value: Mapping[str, Any]) -> None:
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
    }
    if dict(inputs) != expected:
        raise ValueError("Intraday Event Drift 001 launch reviewed inputs differ")


def _verify_launch_implementation(repository: Path, value: Mapping[str, Any]) -> str:
    implementation = _mapping(value.get("implementation"), "launch implementation")
    _require_exact_keys(implementation, {"source_commit", "files"}, "launch implementation")
    source_commit = _validated_source_commit(implementation.get("source_commit"))
    files = implementation.get("files")
    if not isinstance(files, list) or len(files) != len(_LAUNCH_CONTROL_FILES):
        raise ValueError("Intraday Event Drift 001 launch implementation files differ")
    for item, expected_path in zip(files, _LAUNCH_CONTROL_FILES, strict=True):
        binding = _mapping(item, "launch implementation file")
        _require_exact_keys(binding, {"path", "sha256"}, "launch implementation file")
        if binding.get("path") != expected_path or binding.get("sha256") != _sha256_path(
            repository / expected_path
        ):
            raise ValueError("Intraday Event Drift 001 launch implementation file differs")
    return source_commit


def _verify_launch_quality(value: Mapping[str, Any], source_commit: str) -> None:
    quality = _mapping(value.get("quality_gates"), "launch quality gates")
    _require_exact_keys(quality, {"source_commit", "results"}, "launch quality gates")
    results = quality.get("results")
    if quality.get("source_commit") != source_commit or not isinstance(results, list):
        raise ValueError("Intraday Event Drift 001 launch quality gates differ")
    if len(results) != len(_LAUNCH_CONTROL_QUALITY_GATES):
        raise ValueError("Intraday Event Drift 001 launch quality gate count differs")
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
            raise ValueError("Intraday Event Drift 001 launch quality gate differs")
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
        equivalence.get("schema_version") != "intraday-event-drift-001-parallel-equivalence-v1"
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
        raise ValueError("Intraday Event Drift 001 launch equivalence differs")
    for key in ("sequential_seconds", "parallel_seconds", "speedup"):
        _required_positive_decimal_text(equivalence.get(key), f"launch equivalence {key}")
    fixture_keys = {
        "run_id",
        "candidate_id",
        "scenario_id",
        "run_fingerprint",
        "decision_trace_fingerprint",
        "fill_trace_fingerprint",
        "round_trip_fingerprint",
        "report_sha256",
        "report_fingerprint",
        "specification_equal",
        "metrics_equal",
        "event_ledger_equal",
        "canonical_report_equal",
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
            "decision_trace_fingerprint",
            "fill_trace_fingerprint",
            "round_trip_fingerprint",
            "report_sha256",
            "report_fingerprint",
        ):
            _required_sha256(fixture.get(key), f"launch equivalence fixture {key}")
        if any(
            fixture.get(key) is not True
            for key in (
                "specification_equal",
                "metrics_equal",
                "event_ledger_equal",
                "canonical_report_equal",
            )
        ):
            raise ValueError("Intraday Event Drift 001 launch equivalence fixture differs")
        candidates.add(str(fixture["candidate_id"]))
        scenarios.add(str(fixture["scenario_id"]))
    if len(candidates) < 2 or len(scenarios) < 2:
        raise ValueError("Intraday Event Drift 001 launch equivalence lacks design span")


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
        raise ValueError("Intraday Event Drift 001 launch source lineage is unavailable") from error
    paths = frozenset(line for line in changed.stdout.splitlines() if line)
    required = {
        LAUNCH_CONTROL_RELATIVE_PATH.as_posix(),
        "src/systematic_trading_lab/intraday_event_drift_001_launch_control.py",
    }
    if (
        ancestor.returncode != 0
        or not required.issubset(paths)
        or not paths.issubset(_LAUNCH_CONTROL_POST_REVIEW_FILES)
    ):
        raise ValueError("Intraday Event Drift 001 launch source lineage differs")


def _require_exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"Event Drift 001 {label} fields differ")


def _validated_source_commit(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("Event Drift 001 launch source commit differs")
    return value


def _required_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"Event Drift 001 {label} differs")
    return value


def _required_positive_decimal_text(value: object, label: str) -> None:
    try:
        parsed = Decimal(str(value))
    except Exception as error:
        raise ValueError(f"Event Drift 001 {label} differs") from error
    if not isinstance(value, str) or not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"Event Drift 001 {label} differs")


def _parallel_equivalence(repository: Path, *, source_commit: str) -> dict[str, object]:
    plan = load_intraday_event_drift_001_plan(repository.resolve())
    choices = (
        (plan.configurations[0], "normal"),
        (plan.configurations[4], "zero_cost_diagnostic"),
        (plan.configurations[8], "stress_a"),
        (plan.configurations[2], "normal-delay-3"),
    )
    specifications = tuple(
        cast(
            dict[str, object],
            canonicalize(
                {
                    "schema_version": "intraday-event-drift-001-synthetic-equivalence-run-v1",
                    "program_id": PROGRAM_ID,
                    "runner_version": RUNNER_VERSION,
                    "source_commit": source_commit,
                    "plan_sha256": plan.sha256,
                    "plan_fingerprint": plan.plan_fingerprint,
                    "configuration": _configuration_summary(configuration),
                    "period": canonicalize(_EQUIVALENCE_PERIOD),
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
            "metrics_equal": left["metrics"] == right["metrics"],
            "event_ledger_equal": left["event_ledger"] == right["event_ledger"],
            "canonical_report_equal": left["report_bytes"] == right["report_bytes"],
        }
        equivalent = equivalent and left == right and all(comparisons.values())
        fixtures.append(
            {
                "run_id": left["run_id"],
                "candidate_id": left["candidate_id"],
                "scenario_id": left["scenario_id"],
                "run_fingerprint": left["run_fingerprint"],
                "decision_trace_fingerprint": left["decision_trace_fingerprint"],
                "fill_trace_fingerprint": left["fill_trace_fingerprint"],
                "round_trip_fingerprint": left["round_trip_fingerprint"],
                "report_sha256": left["report_sha256"],
                "report_fingerprint": left["report_fingerprint"],
                **comparisons,
            }
        )
    if not equivalent:
        raise ValueError("Event Drift 001 one-worker/four-worker equivalence differs")
    sequential_text = f"{max(sequential_seconds, 0.000001):.6f}"
    parallel_text = f"{max(parallel_seconds, 0.000001):.6f}"
    speedup_text = f"{max(sequential_seconds / parallel_seconds, 0.000001):.6f}"
    return {
        "schema_version": "intraday-event-drift-001-parallel-equivalence-v1",
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


def verify_intraday_event_drift_001_parallel_equivalence(repository: Path) -> dict[str, object]:
    repository = repository.resolve()
    return _parallel_equivalence(repository, source_commit=_source_commit(repository))


def intraday_event_drift_001_plan_summary(repository: Path) -> dict[str, object]:
    plan = load_intraday_event_drift_001_plan(repository.resolve())
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
        "eligible_event_count": len(plan.eligible_events),
        "excluded_event_count": len(plan.excluded_events),
        "default_workers": DEFAULT_RESEARCH_WORKERS,
        "launch_control_bound": launch_control_bound,
        "controlled_range_status": "none-eligible",
        "authority": _AUTHORITY,
    }


def intraday_event_drift_001_status(data_home: Path) -> dict[str, object]:
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


def run_intraday_event_drift_001_campaign(
    repository: Path,
    data_home: Path,
    *,
    workers: int = DEFAULT_RESEARCH_WORKERS,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    return IntradayEventDrift001Runner(
        repository,
        data_home,
        workers=workers,
        progress=progress,
    ).run()
