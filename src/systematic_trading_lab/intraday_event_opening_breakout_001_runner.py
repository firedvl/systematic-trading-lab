"""Restart-safe process runner for Intraday Event Opening Breakout 001."""

from __future__ import annotations

import hashlib
import json
import os
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
from .intraday_event_drift_001_plan import (
    CALENDAR_RELATIVE_PATH,
    SOURCE_EVIDENCE_RELATIVE_PATH,
    EventDriftEvent,
    EventDriftPeriod,
    load_intraday_event_drift_001_plan,
)
from .intraday_event_drift_001_runner import (
    _attempt_summary,
    _benchmark_references,
    _dataset_bindings,
    _read_only_dataset_services,
    _run_dataset_inputs,
)
from .intraday_event_opening_breakout_001_launch_control import (
    REVIEWED_LAUNCH_CONTROL_FINGERPRINT,
    REVIEWED_LAUNCH_CONTROL_SHA256,
)
from .intraday_event_opening_breakout_001_plan import (
    PLAN_FINGERPRINT,
    PLAN_RELATIVE_PATH,
    PLAN_SHA256,
    PROGRAM_ID,
    REVIEW_FINGERPRINT,
    REVIEW_RELATIVE_PATH,
    REVIEW_SHA256,
    EventOpeningBreakoutConfiguration,
    load_intraday_event_opening_breakout_001_plan,
)
from .intraday_event_opening_breakout_001_strategies import (
    ScheduledEventSpyOpeningBreakoutStrategy,
)
from .intraday_execution_cost_model import load_intraday_execution_cost_model
from .intraday_exposed_002_engine import Exposed002ReplayResult, IntradayExposed002Engine
from .intraday_exposed_002_runner import (
    IntradayExposed002Runner,
    _account_day,
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

RUNNER_VERSION = "intraday-event-opening-breakout-001-runner-v1"
RUN_SCHEMA = "intraday-event-opening-breakout-001-run-v1"
RUN_REPORT_SCHEMA = "intraday-event-opening-breakout-001-backtest-report-v1"
FINAL_FREEZE_SCHEMA = "intraday-event-opening-breakout-001-final-freeze-v1"
FINAL_REPORT_SCHEMA = "intraday-event-opening-breakout-001-final-report-v1"
PROGRAM_BINDING_SCHEMA = "intraday-event-opening-breakout-001-program-binding-v1"
DATABASE_NAME = "intraday-event-opening-breakout-001.sqlite3"
ENGINE_VERSION = "intraday-exposed-002-engine-v1"
STRATEGY_VERSION = "scheduled-event-spy-opening-breakout-v1"
LAUNCH_CONTROL_RELATIVE_PATH = Path(
    "config/research/intraday-event-opening-breakout-001-launch-control-review-v1.json"
)
_LAUNCH_CONTROL_SCHEMA = "intraday-event-opening-breakout-001-launch-control-review-v1"
_LAUNCH_CONTROL_FILES = (
    "src/systematic_trading_lab/backtesting.py",
    "src/systematic_trading_lab/calendar.py",
    "src/systematic_trading_lab/config.py",
    "src/systematic_trading_lab/datasets.py",
    "src/systematic_trading_lab/domain.py",
    "src/systematic_trading_lab/fingerprints.py",
    "src/systematic_trading_lab/storage.py",
    "src/systematic_trading_lab/strategies.py",
    "src/systematic_trading_lab/research_attempts.py",
    "src/systematic_trading_lab/research_executor.py",
    "src/systematic_trading_lab/intraday_execution_cost_model.py",
    "src/systematic_trading_lab/intraday_exposed_002_engine.py",
    "src/systematic_trading_lab/intraday_exposed_002_runner.py",
    "src/systematic_trading_lab/intraday_event_drift_001_plan.py",
    "src/systematic_trading_lab/intraday_event_drift_001_runner.py",
    "src/systematic_trading_lab/intraday_event_opening_breakout_001_plan.py",
    "src/systematic_trading_lab/intraday_event_opening_breakout_001_strategies.py",
    "src/systematic_trading_lab/intraday_event_opening_breakout_001_runner.py",
    "src/systematic_trading_lab/intraday_event_opening_breakout_001_cli.py",
    "src/systematic_trading_lab/intraday_event_repricing_001_cli.py",
    "src/systematic_trading_lab/public_cli.py",
    "pyproject.toml",
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
    "signal-trace-fingerprint",
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
        "src/systematic_trading_lab/intraday_event_opening_breakout_001_launch_control.py",
        "tests/unit/test_intraday_event_opening_breakout_001_runner.py",
        "CURRENT_STATE.md",
        "DECISIONS.md",
        "ROADMAP.md",
        "docs/research-campaigns/intraday-event-opening-breakout-001-program.md",
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


def _require_non_broker_environment(
    environment: Mapping[str, str] | None = None,
) -> None:
    values = os.environ if environment is None else environment
    forbidden = tuple(
        sorted(
            name
            for name, value in values.items()
            if value and name.startswith(("APCA_", "TRADING_LAB_PAPER_"))
        )
    )
    if forbidden:
        raise ValueError(
            "Intraday Event Opening Breakout 001 rejects broker credentials and paper-write "
            "opt-in: " + ", ".join(forbidden)
        )


class _CoordinatorValidationError(ValueError):
    def __init__(self, classification: str, run_ids: Sequence[str], cause: str) -> None:
        self.classification = classification
        self.run_ids = tuple(sorted(set(run_ids)))
        self.cause = cause
        super().__init__(cause)


class IntradayEventOpeningBreakout001Store:
    """Campaign view over the generic append-only attempt store."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.attempts = ResearchAttemptStore(
            self.root,
            database_name=DATABASE_NAME,
            lease_timeout=_LEASE_TIMEOUT,
            reconcile_on_open=False,
            attempt_id_prefix="ieb001a-",
        )
        self.path = self.attempts.path

    def bind(self, value: Mapping[str, object]) -> None:
        self.attempts.bind(value)

    def reserve(self, specifications: Sequence[Mapping[str, object]]) -> None:
        run_ids = tuple(_run_id(value) for value in specifications)
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("Event Opening Breakout 001 run specifications collide")
        existing = {str(row["run_id"]) for row in self.attempts.list_runs()}
        if len(existing | set(run_ids)) > 46:
            raise ValueError("Event Opening Breakout 001 run budget exceeds 46 specifications")
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
        _require_non_broker_environment()
        self.repository = repository.resolve()
        self.data_home = data_home.resolve()
        self.source_commit = source_commit
        self.plan = load_intraday_event_opening_breakout_001_plan(self.repository)
        self.base_plan = load_intraday_event_drift_001_plan(self.repository)
        self.cost_model = load_intraday_execution_cost_model(self.repository)
        self.datasets = _dataset_bindings(self.base_plan.payload)
        self.data_by_dataset = _read_only_dataset_services(self.data_home, self.datasets)
        IntradayExposed002Runner._verify_datasets(cast(Any, self), self.base_plan.payload)
        self.scenarios = _scenarios(self.cost_model)
        self._bar_cache: dict[str, tuple[Any, ...]] = {}
        self.attempt_store = IntradayEventOpeningBreakout001Store(runtime_root)

    def __call__(self, specification: Mapping[str, object]) -> str:
        _require_non_broker_environment()
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
                strategy = ScheduledEventSpyOpeningBreakoutStrategy(
                    configuration.candidate_id,
                    configuration.breakout_buffer_bps,
                    frozenset(
                        date.fromisoformat(str(event.xnys_session))
                        for event in self.plan.eligible_events
                    ),
                    period.evaluation_start,
                )
                failure_class = "data"
                bars = IntradayExposed002Runner._bars(
                    cast(Any, self), cast(Any, period), self.base_plan.payload
                )
                failure_class = "candidate"
                result = IntradayExposed002Engine(
                    Decimal(str(self.base_plan.payload["execution"]["initial_cash"])),
                    scenario,
                    self.cost_model.regulatory_fees,
                ).run(bars, strategy)
                failure_class = "calendar"
                report = _run_report(
                    specification,
                    result,
                    period,
                    self.plan.events,
                    bars,
                    configuration,
                )
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
            f"{_text(context, 'candidate_id')} {_text(context, 'period_id')} "
            f"{_text(context, 'scenario_id')} attempt-{claim.attempt_number}"
        )

    def _configuration(self, candidate_id: str) -> EventOpeningBreakoutConfiguration:
        for item in self.plan.configurations:
            if item.candidate_id == candidate_id:
                return item
        raise ValueError(f"unknown Event Opening Breakout 001 candidate: {candidate_id}")

    def _period(self, period_id: str) -> EventDriftPeriod:
        for item in self.plan.periods:
            if item.period_id == period_id:
                return item
        raise ValueError(f"unknown Event Opening Breakout 001 period: {period_id}")


class IntradayEventOpeningBreakout001Runner:
    """Coordinate immutable Event Opening Breakout stages through spawned workers."""

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
        if isinstance(workers, bool) or workers < 1:
            raise ValueError("research worker count must be a positive integer")
        self.repository = repository.resolve()
        self.data_home = data_home.resolve()
        if REVIEWED_LAUNCH_CONTROL_SHA256 is None or REVIEWED_LAUNCH_CONTROL_FINGERPRINT is None:
            raise ValueError("Intraday Event Opening Breakout 001 launch control is not hash-bound")
        self.source_commit = _source_commit(self.repository)
        self.launch_control = _load_launch_control(
            self.repository,
            source_commit=self.source_commit,
        )
        self.workers = workers
        self.progress = progress or (lambda _message: None)
        self.plan = load_intraday_event_opening_breakout_001_plan(self.repository)
        self.base_plan = load_intraday_event_drift_001_plan(self.repository)
        self.cost_model = load_intraday_execution_cost_model(self.repository)
        self.datasets = _dataset_bindings(self.base_plan.payload)
        self.data_by_dataset = (
            {binding.dataset_id: data_service for binding in self.datasets}
            if data_service is not None
            else _read_only_dataset_services(self.data_home, self.datasets)
        )
        IntradayExposed002Runner._verify_datasets(cast(Any, self), self.base_plan.payload)
        self.runtime_root = self.data_home / PROGRAM_ID
        self.attempt_store = IntradayEventOpeningBreakout001Store(self.runtime_root)
        self.store = cast(Any, self.attempt_store)
        self.scenarios = _scenarios(self.cost_model)
        self._bar_cache: dict[str, tuple[Any, ...]] = {}
        self.attempt_store.bind(self._program_binding())

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
            except _CoordinatorValidationError as error:
                rows = self.attempt_store.list_runs()
                if any(row["status"] == "running" for row in rows):
                    raise
                failed = tuple(row for row in rows if row["status"] == "failed")
                final = self._terminal_interruption_report(
                    failed,
                    coordinator_failure=error,
                )
            except Exception:
                rows = self.attempt_store.list_runs()
                failed = tuple(row for row in rows if row["status"] == "failed")
                if not failed or any(row["status"] == "running" for row in rows):
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
            "run_identity_fields": ["candidate_id", "period_id", "scenario_id"],
            "maximum_run_specifications": 46,
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
        configuration: EventOpeningBreakoutConfiguration,
        period: EventDriftPeriod,
        scenario_id: str,
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
            "execution": self.base_plan.payload["execution"],
            "context": {
                "candidate_id": configuration.candidate_id,
                "period_id": period.period_id,
                "scenario_id": scenario_id,
            },
            "authority": _AUTHORITY,
        }
        return cast(dict[str, object], canonicalize(specification))

    def _execute(self, specifications: Sequence[Mapping[str, object]]) -> None:
        specifications = _deduplicate_specifications(specifications)
        if not specifications:
            return
        _require_non_broker_environment()
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
                raise AttemptStateError(f"Event Opening Breakout 001 run is terminal: {run_id}")
            elif row["status"] == "running":
                raise AttemptStateError(
                    f"Event Opening Breakout 001 run has an active attempt: {run_id}"
                )
            else:
                pending.append(specification)
        if pending:
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

    def _configuration(self, candidate_id: str) -> EventOpeningBreakoutConfiguration:
        for item in self.plan.configurations:
            if item.candidate_id == candidate_id:
                return item
        raise ValueError(f"unknown Event Opening Breakout 001 candidate: {candidate_id}")

    def _load_report(self, row: Mapping[str, object]) -> Mapping[str, Any]:
        if row.get("status") != "completed":
            raise ValueError("Event Opening Breakout 001 run is not completed")
        relative = Path(_required_text(row.get("report_path"), "report path"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Event Opening Breakout 001 report path is unsafe")
        raw = (self.runtime_root / relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row.get("report_sha256"):
            raise ValueError("Event Opening Breakout 001 report SHA-256 differs")
        value = _mapping(json.loads(raw), "run report")
        stored = _text(value, "report_fingerprint")
        unsigned = dict(value)
        del unsigned["report_fingerprint"]
        specification = _mapping(value.get("specification"), "report specification")
        cost_model = _mapping(specification.get("cost_model"), "report cost model")
        context = _mapping(specification.get("context"), "report context")
        if (
            value.get("schema_version") != RUN_REPORT_SCHEMA
            or value.get("program_id") != PROGRAM_ID
            or value.get("run_id") != row.get("run_id")
            or value.get("run_id") != _run_id(specification)
            or set(context) != {"candidate_id", "period_id", "scenario_id"}
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
            raise ValueError("Event Opening Breakout 001 report fingerprint differs")
        return value

    def _report_for(
        self,
        candidate_id: str,
        period_id: str,
        scenario_id: str,
    ) -> Mapping[str, Any]:
        matches = tuple(
            row
            for row in self.attempt_store.list_runs()
            if row["candidate_id"] == candidate_id
            and row["period_id"] == period_id
            and row["scenario_id"] == scenario_id
        )
        if len(matches) != 1:
            raise ValueError("Event Opening Breakout 001 canonical run relationship differs")
        return self._load_report(matches[0])

    def _normal_zero_reports(
        self, candidate_id: str, period_id: str
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        normal = self._report_for(candidate_id, period_id, "normal")
        zero = self._report_for(candidate_id, period_id, "zero_cost_diagnostic")
        if _signal_fingerprint(normal) != _signal_fingerprint(zero):
            raise _CoordinatorValidationError(
                "cross-scenario-signal-validation",
                (_text(normal, "run_id"), _text(zero, "run_id")),
                "ValueError: Event Opening Breakout 001 cross-scenario signals differ",
            )
        return normal, zero

    def _require_no_failures(self) -> None:
        failed = tuple(row for row in self.attempt_store.list_runs() if row["status"] == "failed")
        if failed:
            raise AttemptStateError(
                f"Event Opening Breakout 001 has {len(failed)} terminal failed run(s); no retry "
                "is allowed"
            )

    def _run_discovery(self) -> dict[str, object]:
        period = self.plan.periods[0]
        specifications = tuple(
            self._specification(configuration, period, scenario_id)
            for configuration in self.plan.configurations
            for scenario_id in ("normal", "zero_cost_diagnostic")
        )
        if len(specifications) != 6:
            raise ValueError("Event Opening Breakout 001 discovery budget differs")
        self._execute(specifications)
        gates = _gates(self.plan.payload, "discovery_screen", "gates")
        ledger: list[dict[str, object]] = []
        for configuration in self.plan.configurations:
            normal, zero = self._normal_zero_reports(configuration.candidate_id, period.period_id)
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
                "normal.positive_profit_event_concentration": _optional_report_metric(
                    normal, "positive_profit_event_concentration"
                ),
                "normal.positive_profit_release_class_concentration": (
                    _optional_report_metric(normal, "positive_profit_release_class_concentration")
                ),
                "normal.signal_trace_mismatch_count": _report_metric(
                    normal, "signal_trace_mismatch_count"
                ),
                "normal.accounting_identity_error": _report_metric(
                    normal, "accounting_identity_error"
                ),
            }
            gate_results = _gate_results(gates, values)
            ledger.append(
                {
                    "candidate": _configuration_summary(configuration),
                    "normal": _run_report_evidence(normal),
                    "zero_cost_diagnostic": _run_report_evidence(zero),
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
            "run_specification_count": len(specifications),
            "eligible_count": sum(item["eligible"] is True for item in ledger),
            "selected_candidate_ids": selected,
            "ledger": ledger,
        }

    def _run_walk_forward(self, discovery: Mapping[str, object]) -> dict[str, object]:
        selected = _strings(discovery.get("selected_candidate_ids"), "discovery selection")
        periods = self.plan.periods[1:]
        specifications = tuple(
            self._specification(self._configuration(candidate_id), period, scenario_id)
            for candidate_id in selected
            for period in periods
            for scenario_id in ("normal", "zero_cost_diagnostic")
        )
        if len(specifications) > 16:
            raise ValueError("Event Opening Breakout 001 walk-forward budget differs")
        self._execute(specifications)
        gates = _gates(self.plan.payload, "walk_forward_screen", "gates")
        ledger: list[dict[str, object]] = []
        for candidate_id in selected:
            configuration = self._configuration(candidate_id)
            normal_reports: list[Mapping[str, Any]] = []
            zero_reports: list[Mapping[str, Any]] = []
            fold_runs: list[dict[str, object]] = []
            for period in periods:
                normal, zero = self._normal_zero_reports(candidate_id, period.period_id)
                normal_reports.append(normal)
                zero_reports.append(zero)
                fold_runs.append(
                    {
                        "period_id": period.period_id,
                        "normal": _run_report_evidence(normal),
                        "zero_cost_diagnostic": _run_report_evidence(zero),
                    }
                )
            normal_aggregate = _aggregate_event_reports(tuple(normal_reports))
            zero_aggregate = _aggregate_event_reports(tuple(zero_reports))
            positive = tuple(
                index for index, report in enumerate(normal_reports) if _positive_fold(report)
            )
            normal_returns = tuple(
                _report_metric(report, "total_return") for report in normal_reports
            )
            normal_drawdowns = tuple(
                _report_metric(report, "max_drawdown") for report in normal_reports
            )
            values: dict[str, Decimal | int | None] = {
                "aggregate.normal.total_return": Decimal(str(normal_aggregate["total_return"])),
                "aggregate.zero_cost_diagnostic.total_return": Decimal(
                    str(zero_aggregate["total_return"])
                ),
                "positive_normal_fold_count": len(positive),
                "final_exposed_may.normal.total_return": normal_returns[-1],
                "final_exposed_may.normal.active_event_count": _report_metric(
                    normal_reports[-1], "active_event_count"
                ),
                "minimum_active_events_in_positive_normal_fold": (
                    min(
                        _report_metric(normal_reports[index], "active_event_count")
                        for index in positive
                    )
                    if positive
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
                "aggregate.normal.signal_trace_mismatch_count": Decimal(
                    str(normal_aggregate["signal_trace_mismatch_count"])
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
        serious = _select_eligible(
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
            item["selected"] = _screen_candidate_id(item) in serious
        return {
            "stage": "walk-forward",
            "candidate_count": len(ledger),
            "run_specification_count": len(specifications),
            "eligible_count": sum(item["eligible"] is True for item in ledger),
            "selected_candidate_ids": serious,
            "ledger": ledger,
        }

    def _run_serious(self, walk_forward: Mapping[str, object]) -> dict[str, object]:
        selected = _strings(walk_forward.get("selected_candidate_ids"), "serious selection")
        periods = self.plan.periods[1:]
        screen = _mapping(
            self.plan.payload.get("serious_candidate_screen"), "serious candidate screen"
        )
        stress_scenarios = _strings(screen.get("stress_scenarios"), "stress scenarios")
        if stress_scenarios != (
            "stress_a",
            "stress_b",
            "normal-delay-2",
            "normal-delay-3",
        ):
            raise ValueError("Event Opening Breakout 001 stress scenarios differ")
        stress_specifications = tuple(
            self._specification(self._configuration(candidate_id), period, scenario_id)
            for candidate_id in selected
            for period in periods
            for scenario_id in stress_scenarios
        )
        if len(stress_specifications) > 16:
            raise ValueError("Event Opening Breakout 001 stress budget differs")
        self._execute(stress_specifications)

        neighbor_ids = tuple(
            sorted(
                {
                    neighbor_id
                    for candidate_id in selected
                    for neighbor_id in self._configuration(candidate_id).neighbor_ids
                }
            )
        )
        neighbor_specifications = _deduplicate_specifications(
            tuple(
                self._specification(self._configuration(neighbor_id), period, scenario_id)
                for neighbor_id in neighbor_ids
                for period in periods
                for scenario_id in ("normal", "zero_cost_diagnostic")
            )
        )
        existing_ids = {str(row["run_id"]) for row in self.attempt_store.list_runs()}
        new_neighbor_count = sum(
            _run_id(specification) not in existing_ids for specification in neighbor_specifications
        )
        if new_neighbor_count > 8:
            raise _CoordinatorValidationError(
                "search-budget",
                tuple(_run_id(specification) for specification in neighbor_specifications),
                "ValueError: Event Opening Breakout 001 neighbor budget differs",
            )
        self._execute(neighbor_specifications)

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
            base_normal = _mapping(base.get("normal_aggregate"), "base normal aggregate")
            base_profit = Decimal(str(base_normal["net_profit_loss"]))
            base_reports = tuple(
                self._report_for(candidate_id, period.period_id, "normal") for period in periods
            )
            base_signals = tuple(_signal_fingerprint(report) for report in base_reports)
            stress_values: dict[str, Decimal | int | None] = {}
            stress_runs: list[dict[str, object]] = []
            for scenario_id in stress_scenarios:
                reports: list[Mapping[str, Any]] = []
                stress_fold_runs: list[dict[str, object]] = []
                for period_index, period in enumerate(periods):
                    report = self._report_for(candidate_id, period.period_id, scenario_id)
                    if _signal_fingerprint(report) != base_signals[period_index]:
                        raise _CoordinatorValidationError(
                            "cross-scenario-signal-validation",
                            (
                                _text(report, "run_id"),
                                _text(base_reports[period_index], "run_id"),
                            ),
                            "ValueError: Event Opening Breakout 001 stress signal differs from "
                            "Normal",
                        )
                    reports.append(report)
                    stress_fold_runs.append(_run_report_evidence(report))
                aggregate = _aggregate_event_reports(tuple(reports))
                scenario_profit = Decimal(str(aggregate["net_profit_loss"]))
                stress_values.update(
                    {
                        f"{scenario_id}.aggregate_total_return": Decimal(
                            str(aggregate["total_return"])
                        ),
                        f"{scenario_id}.positive_fold_count": sum(
                            _positive_fold(report) for report in reports
                        ),
                        f"{scenario_id}.normal_profit_retention": (
                            scenario_profit / base_profit if base_profit > 0 else None
                        ),
                    }
                )
                stress_runs.append(
                    {
                        "scenario_id": scenario_id,
                        "fold_runs": stress_fold_runs,
                        "aggregate": aggregate,
                    }
                )

            positive_neighbors = 0
            retentions: list[Decimal] = []
            neighbor_runs: list[dict[str, object]] = []
            for neighbor_id in configuration.neighbor_ids:
                normal_reports: list[Mapping[str, Any]] = []
                zero_reports: list[Mapping[str, Any]] = []
                neighbor_fold_runs: list[dict[str, object]] = []
                for period in periods:
                    normal, zero = self._normal_zero_reports(neighbor_id, period.period_id)
                    normal_reports.append(normal)
                    zero_reports.append(zero)
                    neighbor_fold_runs.append(
                        {
                            "period_id": period.period_id,
                            "normal": _run_report_evidence(normal),
                            "zero_cost_diagnostic": _run_report_evidence(zero),
                        }
                    )
                normal_aggregate = _aggregate_event_reports(tuple(normal_reports))
                zero_aggregate = _aggregate_event_reports(tuple(zero_reports))
                neighbor_profit = Decimal(str(normal_aggregate["net_profit_loss"]))
                positive = all(
                    Decimal(str(aggregate[key])) > 0
                    for aggregate in (normal_aggregate, zero_aggregate)
                    for key in ("net_profit_loss", "total_return")
                )
                positive_neighbors += positive
                if base_profit > 0:
                    retentions.append(neighbor_profit / base_profit)
                neighbor_runs.append(
                    {
                        "neighbor_id": neighbor_id,
                        "fold_runs": neighbor_fold_runs,
                        "normal_aggregate": normal_aggregate,
                        "zero_cost_aggregate": zero_aggregate,
                        "joint_positive": positive,
                    }
                )
            complete_retention = len(retentions) == len(configuration.neighbor_ids)
            neighbor_values: dict[str, Decimal | int | None] = {
                "joint_positive_neighbor_fraction": (
                    Decimal(positive_neighbors) / Decimal(len(configuration.neighbor_ids))
                    if configuration.neighbor_ids
                    else None
                ),
                "median_neighbor_normal_profit_retention": (
                    median(sorted(retentions)) if retentions and complete_retention else None
                ),
            }
            stress_gate_results = _gate_results(stress_gates, stress_values)
            neighbor_gate_results = _gate_results(neighbor_gates, neighbor_values)
            gate_results = stress_gate_results + neighbor_gate_results
            ledger.append(
                {
                    "candidate": _configuration_summary(configuration),
                    "base_normal_aggregate": base_normal,
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
            "stress_run_specification_count": len(stress_specifications),
            "neighbor_requested_specification_count": len(neighbor_specifications),
            "neighbor_new_specification_count": new_neighbor_count,
            "eligible_count": sum(item["eligible"] is True for item in ledger),
            "ledger": ledger,
        }

    def _select_cohort(self, serious: Mapping[str, object]) -> tuple[str, ...]:
        ledger = _mapping_items(serious.get("ledger"), "serious ledger")
        cohort = tuple(
            sorted(_screen_candidate_id(item) for item in ledger if item.get("eligible") is True)
        )
        if len(cohort) > 1:
            raise ValueError("Event Opening Breakout 001 final cohort exceeds its frozen maximum")
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
        attempt_summary = _attempt_summary(runs, histories)
        if len(runs) > 46 or Decimal(str(attempt_summary["total_attempts"])) > 138:
            raise ValueError("Event Opening Breakout 001 frozen search budget exceeded")
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
            "attempt_summary": attempt_summary,
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
                else "exposed-serious-candidate-waiting-for-future-untouched-data"
            ),
            "terminal_message": (
                "INTRADAY EVENT OPENING BREAKOUT 001 COMPLETE — NO CONTROLLED-QUALIFIED CANDIDATE"
                if empty
                else "INTRADAY EVENT OPENING BREAKOUT 001 COMPLETE — WAITING FOR FUTURE "
                "UNTOUCHED DATA"
            ),
            "source_commit": self.source_commit,
            "complete_exposed_screening": True,
            "counts": {
                "discovery_parents": discovery["parent_count"],
                "discovery_run_specifications": discovery["run_specification_count"],
                "walk_forward_candidates": walk_forward["candidate_count"],
                "walk_forward_run_specifications": walk_forward["run_specification_count"],
                "serious_candidates": serious["candidate_count"],
                "stress_run_specifications": serious["stress_run_specification_count"],
                "neighbor_new_run_specifications": serious["neighbor_new_specification_count"],
                "total_run_specifications": len(self.attempt_store.list_runs()),
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
        self,
        failed: Sequence[Mapping[str, object]],
        *,
        coordinator_failure: _CoordinatorValidationError | None = None,
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
            "terminal_message": "INTRADAY EVENT OPENING BREAKOUT 001 TERMINALLY INTERRUPTED",
            "source_commit": self.source_commit,
            "complete_exposed_screening": False,
            "counts": {
                "discovery_parents": None,
                "discovery_run_specifications": None,
                "walk_forward_candidates": None,
                "walk_forward_run_specifications": None,
                "serious_candidates": None,
                "stress_run_specifications": None,
                "neighbor_new_run_specifications": None,
                "total_run_specifications": len(runs),
                "cohort": None,
                "runtime_runs": counts,
            },
            "cohort": [],
            "terminal_failures": [_run_evidence(row) for row in failed],
            "coordinator_failure": (
                None
                if coordinator_failure is None
                else {
                    "classification": coordinator_failure.classification,
                    "affected_run_ids": list(coordinator_failure.run_ids),
                    "cause": coordinator_failure.cause,
                }
            ),
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
    if set(context) != {"candidate_id", "period_id", "scenario_id"}:
        raise ValueError("Event Opening Breakout 001 canonical run context differs")
    identity = {key: _text(context, key) for key in ("candidate_id", "period_id", "scenario_id")}
    return f"ieb001r-{fingerprint(identity)[:24]}"


def _reservation_id(run_fingerprint: str) -> str:
    return f"ieb001q-{run_fingerprint[:24]}"


def _configuration_summary(
    configuration: EventOpeningBreakoutConfiguration,
) -> dict[str, object]:
    return {
        "candidate_id": configuration.candidate_id,
        "strategy_id": STRATEGY_VERSION,
        "breakout_buffer_bps": configuration.breakout_buffer_bps,
        "active_symbol": "SPY",
        "active_symbol_weight": Decimal("0.5"),
        "qqq_target_weight": _ZERO,
        "opening_range_bars": 6,
        "monitor_start_bar_index": 6,
        "monitor_end_bar_index": 11,
        "exit_bar_index": 29,
        "neighbor_ids": configuration.neighbor_ids,
    }


def _deduplicate_specifications(
    specifications: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    by_id: dict[str, Mapping[str, object]] = {}
    for specification in specifications:
        run_id = _run_id(specification)
        existing = by_id.get(run_id)
        if existing is not None and canonical_json(existing) != canonical_json(specification):
            raise ValueError("Event Opening Breakout 001 canonical run identity collides")
        by_id.setdefault(run_id, specification)
    return tuple(by_id[run_id] for run_id in sorted(by_id))


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


def _signal_fingerprint(report: Mapping[str, Any]) -> str:
    return _text(_mapping(report.get("details"), "report details"), "signal_trace_fingerprint")


def _run_report_evidence(report: Mapping[str, Any]) -> dict[str, object]:
    return {
        "run_id": report["run_id"],
        "signal_trace_fingerprint": _signal_fingerprint(report),
        "metrics": report["metrics"],
    }


def _run_evidence(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "run_id": row["run_id"],
        "reservation_id": row["reservation_id"],
        "run_fingerprint": row["run_fingerprint"],
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


def _protected_access() -> dict[str, bool]:
    return {
        "june_market_data_or_results": False,
        "intraday_v3_data_or_results": False,
        "daily_2018_2019_data_or_results": False,
        "paper_broker_or_live_state": False,
        "strategic_allocation_21": False,
    }


def _event_session(bars: Sequence[OHLCVBar], day: date) -> dict[Symbol, tuple[OHLCVBar, ...]]:
    session = {
        symbol: tuple(
            bar for bar in bars if bar.symbol == symbol and _account_day(bar.timestamp) == day
        )
        for symbol in (Symbol("QQQ"), Symbol("SPY"))
    }
    timestamps = tuple(
        tuple(bar.timestamp for bar in session[symbol]) for symbol in (Symbol("QQQ"), Symbol("SPY"))
    )
    if not timestamps[0] or timestamps[0] != timestamps[1] or len(timestamps[0]) <= 32:
        raise ValueError("Event Opening Breakout 001 event session bars differ")
    return session


def _run_report(
    specification: Mapping[str, object],
    result: Exposed002ReplayResult,
    period: EventDriftPeriod,
    events: tuple[EventDriftEvent, ...],
    bars: Sequence[OHLCVBar],
    configuration: EventOpeningBreakoutConfiguration,
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
        raise ValueError("Event Opening Breakout 001 period event count differs")
    event_by_day = {date.fromisoformat(str(event.xnys_session)): event for event in eligible}
    if len(event_by_day) != len(eligible):
        raise ValueError("Event Opening Breakout 001 eligible event sessions collide")
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
    if any(
        fill.symbol != Symbol("SPY") or _account_day(fill.fill_timestamp) not in event_by_day
        for fill in evaluation_fills
    ):
        raise ValueError("Event Opening Breakout 001 has an invalid evaluated fill")
    if any(
        trade.symbol != Symbol("SPY")
        or _account_day(trade.entry_timestamp) != _account_day(trade.exit_timestamp)
        or _account_day(trade.entry_timestamp) not in event_by_day
        for trade in evaluation_round_trips
    ):
        raise ValueError("Event Opening Breakout 001 has an invalid event round trip")
    fees_by_day = {
        date.fromisoformat(item.account_day): item
        for item in result.fee_ledger
        if period.evaluation_start.date()
        <= date.fromisoformat(item.account_day)
        <= period.evaluation_end.date()
    }
    cost_model = _mapping(specification.get("cost_model"), "report cost model")
    delay = cost_model.get("execution_delay_bars")
    if isinstance(delay, bool) or delay not in (1, 2, 3):
        raise ValueError("Event Opening Breakout 001 execution delay differs")
    ledger: list[dict[str, object]] = []
    signal_trace: list[dict[str, object]] = []
    for event in eligible:
        day = date.fromisoformat(str(event.xnys_session))
        session = _event_session(bars, day)
        spy = session[Symbol("SPY")]
        signal = ScheduledEventSpyOpeningBreakoutStrategy(
            configuration.candidate_id,
            configuration.breakout_buffer_bps,
            frozenset({day}),
            spy[0].timestamp,
        ).signal(session)
        fills = tuple(fill for fill in evaluation_fills if _account_day(fill.fill_timestamp) == day)
        trades = tuple(
            trade for trade in evaluation_round_trips if _account_day(trade.entry_timestamp) == day
        )
        daily = fees_by_day.get(day)
        if daily is None:
            raise ValueError("Event Opening Breakout 001 event lacks a daily fee ledger")
        regulatory_fees = daily.charges.total
        active = signal.active
        breakout_index = signal.breakout_bar_index
        breakout_decision = (
            None
            if breakout_index is None
            else spy[breakout_index].timestamp + Timeframe.FIVE_MINUTES.duration
        )
        exit_decision = spy[29].timestamp + Timeframe.FIVE_MINUTES.duration if active else None
        if not active:
            if fills or trades or regulatory_fees != _ZERO:
                raise ValueError("Event Opening Breakout 001 inactive event has execution evidence")
            entry_fill = exit_fill = None
            gross = slippage = net = _ZERO
        else:
            if breakout_index is None or not 6 <= breakout_index <= 11:
                raise ValueError("Event Opening Breakout 001 breakout index differs")
            entries = tuple(fill for fill in fills if fill.quantity > 0)
            exits = tuple(fill for fill in fills if fill.quantity < 0)
            expected_entry_fill = spy[breakout_index + cast(int, delay)].timestamp
            expected_exit_fill = spy[29 + cast(int, delay)].timestamp
            if (
                len(trades) != 1
                or trades[0].symbol != Symbol("SPY")
                or len(entries) != 1
                or len(exits) != 1
                or entries[0].symbol != Symbol("SPY")
                or exits[0].symbol != Symbol("SPY")
                or entries[0].decision_timestamp != breakout_decision
                or entries[0].fill_timestamp != expected_entry_fill
                or exits[0].decision_timestamp != exit_decision
                or exits[0].fill_timestamp != expected_exit_fill
                or trades[0].entry_timestamp != expected_entry_fill
                or trades[0].exit_timestamp != expected_exit_fill
            ):
                raise ValueError("Event Opening Breakout 001 event execution differs")
            entry_fill = entries[0].fill_timestamp
            exit_fill = exits[0].fill_timestamp
            gross = trades[0].gross_profit
            slippage = sum((fill.adverse_slippage for fill in fills), _ZERO)
            net = gross - slippage - regulatory_fees
        signal_trace.append(
            {
                "event_id": event.event_id,
                "breakout_buffer_bps": configuration.breakout_buffer_bps,
                "opening_range_high": signal.opening_range_high,
                "breakout_threshold": signal.breakout_threshold,
                "active": active,
                "breakout_bar_index": breakout_index,
                "breakout_decision_timestamp": breakout_decision,
                "exit_decision_timestamp": exit_decision,
            }
        )
        ledger.append(
            {
                "event_id": event.event_id,
                "release_name": event.release_name,
                "scheduled_utc": event.scheduled_utc,
                "xnys_session": event.xnys_session,
                "active": active,
                "opening_range_high": signal.opening_range_high,
                "breakout_buffer_bps": configuration.breakout_buffer_bps,
                "breakout_threshold": signal.breakout_threshold,
                "breakout_bar_index": breakout_index,
                "breakout_decision_timestamp": breakout_decision,
                "entry_fill_timestamp": entry_fill,
                "exit_decision_timestamp": exit_decision,
                "exit_fill_timestamp": exit_fill,
                "gross_profit_loss": gross,
                "adverse_slippage": slippage,
                "regulatory_fees": regulatory_fees,
                "net_profit_loss": net,
            }
        )
    event_net = sum((Decimal(str(row["net_profit_loss"])) for row in ledger), _ZERO)
    reported_net = Decimal(str(metrics["net_profit_loss"]))
    reconciliation_error = abs(event_net - reported_net).quantize(_ACCOUNTING_PRECISION)
    if reconciliation_error != _ZERO:
        raise ValueError("Event Opening Breakout 001 event accounting does not reconcile")
    release_net = {
        name: sum(
            (Decimal(str(row["net_profit_loss"])) for row in ledger if row["release_name"] == name),
            _ZERO,
        )
        for name in _RELEASE_NAMES
    }
    active_count = sum(row["active"] is True for row in ledger)
    signal_fingerprint = fingerprint(signal_trace)
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
            "signal_trace_mismatch_count": 0,
            "event_accounting_reconciliation_error": reconciliation_error,
            "benchmark_references": _benchmark_references(bars, period),
        }
    )
    details.update(
        {
            "signal_trace": signal_trace,
            "signal_trace_fingerprint": signal_fingerprint,
            "event_ledger": ledger,
        }
    )
    payload.update(
        {
            "schema_version": RUN_REPORT_SCHEMA,
            "program_id": PROGRAM_ID,
            "run_id": _run_id(specification),
            "metrics": metrics,
            "details": details,
            "execution_evidence": {
                "signal_trace_fingerprint": signal_fingerprint,
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


def _event_ledger(report: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    value = _mapping(report.get("details"), "report details").get("event_ledger")
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("Event Opening Breakout 001 event ledger differs")
    return tuple(value)


def _aggregate_event_reports(reports: tuple[Mapping[str, Any], ...]) -> dict[str, object]:
    aggregate = _source_aggregate_reports(reports)
    ledger = [dict(row) for report in reports for row in _event_ledger(report)]
    event_ids = tuple(str(row["event_id"]) for row in ledger)
    if len(set(event_ids)) != len(event_ids):
        raise ValueError("Event Opening Breakout 001 aggregate event IDs collide")
    event_net = sum((Decimal(str(row["net_profit_loss"])) for row in ledger), _ZERO)
    reported_net = Decimal(str(aggregate["net_profit_loss"]))
    reconciliation_error = abs(event_net - reported_net).quantize(_ACCOUNTING_PRECISION)
    if reconciliation_error != _ZERO:
        raise ValueError("Event Opening Breakout 001 aggregate event accounting differs")
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
            "event_ledger": ledger,
            "event_net_profit_loss": event_net,
            "positive_profit_event_concentration": _positive_concentration(
                tuple(Decimal(str(row["net_profit_loss"])) for row in ledger)
            ),
            "release_class_net_profit_loss": release_net,
            "positive_profit_release_class_concentration": _positive_concentration(
                tuple(release_net.values())
            ),
            "signal_trace_fingerprints": [_signal_fingerprint(report) for report in reports],
            "signal_trace_mismatch_count": sum(
                _report_metric(report, "signal_trace_mismatch_count") for report in reports
            ),
            "event_accounting_reconciliation_error": reconciliation_error,
        }
    )
    return aggregate


def _final_markdown(report: Mapping[str, object], json_sha256: str) -> str:
    counts = _mapping(report.get("counts"), "final counts")
    lines = [
        "# Intraday Event Opening Breakout 001 final report",
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
        ("Discovery run specifications", "discovery_run_specifications"),
        ("Walk-forward candidates", "walk_forward_candidates"),
        ("Walk-forward run specifications", "walk_forward_run_specifications"),
        ("Serious candidates", "serious_candidates"),
        ("Stress run specifications", "stress_run_specifications"),
        ("New neighbor run specifications", "neighbor_new_run_specifications"),
        ("Total run specifications", "total_run_specifications"),
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
        raise ValueError("Event Opening Breakout 001 final report differs")
    return value


def _validate_final_evidence(runtime: Path, report: Mapping[str, Any]) -> None:
    database = _mapping(report.get("runtime_database"), "runtime database")
    if database.get("path") != DATABASE_NAME or database.get("sha256") != _sha256_path(
        runtime / DATABASE_NAME
    ):
        raise ValueError("Event Opening Breakout 001 runtime database differs")
    freeze_evidence = report.get("final_freeze")
    if freeze_evidence is None:
        return
    evidence = _mapping(freeze_evidence, "final freeze evidence")
    relative = _required_text(evidence.get("path"), "freeze path")
    if relative != "final-freeze.json":
        raise ValueError("Event Opening Breakout 001 final freeze path differs")
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
        raise ValueError("Event Opening Breakout 001 final freeze differs")


def _load_launch_control(repository: Path, *, source_commit: str) -> Mapping[str, Any]:
    if REVIEWED_LAUNCH_CONTROL_SHA256 is None or REVIEWED_LAUNCH_CONTROL_FINGERPRINT is None:
        raise ValueError("Intraday Event Opening Breakout 001 launch control is not hash-bound")
    path = repository / LAUNCH_CONTROL_RELATIVE_PATH
    if not path.is_file():
        raise ValueError("Intraday Event Opening Breakout 001 launch control review is missing")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != REVIEWED_LAUNCH_CONTROL_SHA256:
        raise ValueError("Intraday Event Opening Breakout 001 launch control SHA-256 differs")
    try:
        value = _mapping(json.loads(raw), "launch control review")
    except json.JSONDecodeError as error:
        raise ValueError(
            "Intraday Event Opening Breakout 001 launch control is invalid JSON"
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
        raise ValueError("Intraday Event Opening Breakout 001 launch control differs")
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
        raise ValueError("Intraday Event Opening Breakout 001 launch review identity differs")
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
        raise ValueError("Intraday Event Opening Breakout 001 launch independent review differs")
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
            "path": CALENDAR_RELATIVE_PATH.as_posix(),
            "sha256": "fa413a30234c6b82394fcdbf99df94aa31ae38e2df12d58296bcbc03162a34ee",
            "fingerprint": "9992ee0a430abc0b59f49f6dd9e5178ff22d13a9dec5ad5de1d8578896ed2a78",
        },
        "source_evidence": {
            "path": SOURCE_EVIDENCE_RELATIVE_PATH.as_posix(),
            "sha256": "c5f1ab34c92b10ac9c75d86a3c33c9f2a445eed022a48697edaa7dfd9eabee0a",
            "fingerprint": "6616ed631b3d7e8e727b8cde85bf26e4c2cb5800812db745c327a71bf62192fd",
        },
    }
    if dict(inputs) != expected:
        raise ValueError("Intraday Event Opening Breakout 001 launch inputs differ")


def _verify_launch_implementation(repository: Path, value: Mapping[str, Any]) -> str:
    implementation = _mapping(value.get("implementation"), "launch implementation")
    _require_exact_keys(implementation, {"source_commit", "files"}, "launch implementation")
    source_commit = _validated_source_commit(implementation.get("source_commit"))
    files = implementation.get("files")
    if not isinstance(files, list) or len(files) != len(_LAUNCH_CONTROL_FILES):
        raise ValueError("Intraday Event Opening Breakout 001 launch files differ")
    for item, expected_path in zip(files, _LAUNCH_CONTROL_FILES, strict=True):
        binding = _mapping(item, "launch implementation file")
        _require_exact_keys(binding, {"path", "sha256"}, "launch implementation file")
        if binding.get("path") != expected_path or binding.get("sha256") != _sha256_path(
            repository / expected_path
        ):
            raise ValueError("Intraday Event Opening Breakout 001 implementation file differs")
    return source_commit


def _verify_launch_quality(value: Mapping[str, Any], source_commit: str) -> None:
    quality = _mapping(value.get("quality_gates"), "launch quality gates")
    _require_exact_keys(quality, {"source_commit", "results"}, "launch quality gates")
    results = quality.get("results")
    if quality.get("source_commit") != source_commit or not isinstance(results, list):
        raise ValueError("Intraday Event Opening Breakout 001 launch quality gates differ")
    if len(results) != len(_LAUNCH_CONTROL_QUALITY_GATES):
        raise ValueError("Intraday Event Opening Breakout 001 launch quality gate count differs")
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
            raise ValueError("Intraday Event Opening Breakout 001 launch quality gate differs")
        _required_text(gate.get("summary"), "launch quality gate summary")


def _verify_launch_equivalence(value: Mapping[str, Any], source_commit: str) -> None:
    equivalence = _mapping(value.get("equivalence"), "launch equivalence")
    _require_exact_keys(
        equivalence,
        {
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
        },
        "launch equivalence",
    )
    fixtures = equivalence.get("fixtures")
    fixture_count = equivalence.get("fixture_count")
    if (
        equivalence.get("schema_version")
        != "intraday-event-opening-breakout-001-parallel-equivalence-v1"
        or equivalence.get("program_id") != PROGRAM_ID
        or equivalence.get("verification_source_commit") != source_commit
        or equivalence.get("fixture_kind")
        != "synthetic-non-protected-spy-opening-breakout-five-minute-bars"
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
        raise ValueError("Intraday Event Opening Breakout 001 launch equivalence differs")
    for key in ("sequential_seconds", "parallel_seconds", "speedup"):
        _required_positive_decimal_text(equivalence.get(key), f"launch equivalence {key}")
    fixture_keys = {
        "candidate_id",
        "scenario_id",
        "run_id",
        "run_fingerprint",
        "signal_trace_fingerprint",
        "decision_trace_fingerprint",
        "fill_trace_fingerprint",
        "round_trip_fingerprint",
        "event_ledger_fingerprint",
        "report_sha256",
        "report_fingerprint",
        "specification_equal",
        "report_equal",
        "event_ledger_equal",
        "canonical_report_equal",
    }
    candidates: set[str] = set()
    scenarios: set[str] = set()
    for item in fixtures:
        fixture = _mapping(item, "launch equivalence fixture")
        _require_exact_keys(fixture, fixture_keys, "launch equivalence fixture")
        for key in ("candidate_id", "scenario_id", "run_id"):
            _required_text(fixture.get(key), f"launch equivalence fixture {key}")
        for key in fixture_keys - {
            "candidate_id",
            "scenario_id",
            "run_id",
            "specification_equal",
            "report_equal",
            "event_ledger_equal",
            "canonical_report_equal",
        }:
            _required_sha256(fixture.get(key), f"launch equivalence fixture {key}")
        if any(
            fixture.get(key) is not True
            for key in (
                "specification_equal",
                "report_equal",
                "event_ledger_equal",
                "canonical_report_equal",
            )
        ):
            raise ValueError("Intraday Event Opening Breakout 001 equivalence fixture differs")
        candidates.add(str(fixture["candidate_id"]))
        scenarios.add(str(fixture["scenario_id"]))
    if len(candidates) < 2 or len(scenarios) < 2:
        raise ValueError("Intraday Event Opening Breakout 001 equivalence lacks design span")


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
            "Intraday Event Opening Breakout 001 launch source lineage is unavailable"
        ) from error
    paths = frozenset(line for line in changed.stdout.splitlines() if line)
    required = {
        LAUNCH_CONTROL_RELATIVE_PATH.as_posix(),
        "src/systematic_trading_lab/intraday_event_opening_breakout_001_launch_control.py",
    }
    if (
        ancestor.returncode != 0
        or not required.issubset(paths)
        or not paths.issubset(_LAUNCH_CONTROL_POST_REVIEW_FILES)
    ):
        raise ValueError("Intraday Event Opening Breakout 001 launch source lineage differs")


def _require_exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"Event Opening Breakout 001 {label} fields differ")


def _validated_source_commit(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("Event Opening Breakout 001 launch source commit differs")
    return value


def _required_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"Event Opening Breakout 001 {label} differs")
    return value


def _required_positive_decimal_text(value: object, label: str) -> None:
    try:
        parsed = Decimal(str(value))
    except Exception as error:
        raise ValueError(f"Event Opening Breakout 001 {label} differs") from error
    if not isinstance(value, str) or not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"Event Opening Breakout 001 {label} differs")


@dataclass(frozen=True)
class _EquivalenceWorkerFactory:
    repository: Path

    def __call__(self) -> _EquivalenceWorker:
        return _EquivalenceWorker(self.repository)


class _EquivalenceWorker:
    def __init__(self, repository: Path) -> None:
        _require_non_broker_environment()
        self.repository = repository.resolve()
        self.plan = load_intraday_event_opening_breakout_001_plan(self.repository)
        self.cost_model = load_intraday_execution_cost_model(self.repository)
        self.scenarios = _scenarios(self.cost_model)
        self.bars = _synthetic_equivalence_bars()

    def __call__(self, task: Mapping[str, object]) -> Mapping[str, object]:
        _require_non_broker_environment()
        context = _mapping(task.get("context"), "equivalence context")
        candidate_id = _text(context, "candidate_id")
        scenario_id = _text(context, "scenario_id")
        source_commit = _text(task, "source_commit")
        configuration = next(
            (item for item in self.plan.configurations if item.candidate_id == candidate_id),
            None,
        )
        if configuration is None:
            raise ValueError("Event Opening Breakout 001 equivalence candidate differs")
        scenario = self.scenarios[scenario_id]
        specification = _synthetic_specification(
            self.plan,
            configuration,
            scenario_id,
            source_commit,
        )
        strategy = ScheduledEventSpyOpeningBreakoutStrategy(
            configuration.candidate_id,
            configuration.breakout_buffer_bps,
            frozenset((date(2026, 1, 8), date(2026, 1, 9))),
            _EQUIVALENCE_PERIOD.evaluation_start,
        )
        result = IntradayExposed002Engine(
            Decimal("100000"), scenario, self.cost_model.regulatory_fees
        ).run(self.bars, strategy)
        report = _run_report(
            specification,
            result,
            _EQUIVALENCE_PERIOD,
            _EQUIVALENCE_EVENTS,
            self.bars,
            configuration,
        )
        details = _mapping(report.get("details"), "equivalence details")
        report_bytes = (canonical_json(report) + "\n").encode()
        ledger = details["event_ledger"]
        return {
            "candidate_id": candidate_id,
            "scenario_id": scenario_id,
            "specification": specification,
            "run_id": report["run_id"],
            "run_fingerprint": fingerprint(specification),
            "signal_trace_fingerprint": details["signal_trace_fingerprint"],
            "decision_trace_fingerprint": details["decision_trace_fingerprint"],
            "fill_trace_fingerprint": details["fill_trace_fingerprint"],
            "round_trip_fingerprint": details["round_trip_fingerprint"],
            "metrics": report["metrics"],
            "signal_trace": details["signal_trace"],
            "event_ledger": ledger,
            "event_ledger_fingerprint": fingerprint(ledger),
            "report_bytes": report_bytes,
            "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "report_fingerprint": report["report_fingerprint"],
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
        qqq_price = Decimal("50") + Decimal(index) / Decimal("1000")
        if day == date(2026, 1, 8):
            spy_price = (
                Decimal("100") if index < 6 else Decimal("100.20") if index < 30 else Decimal("101")
            )
        else:
            spy_price = Decimal("100")
        bars.extend(
            (
                OHLCVBar(
                    Symbol("QQQ"),
                    timestamp,
                    qqq_price,
                    qqq_price,
                    qqq_price,
                    qqq_price,
                    1_000,
                ),
                OHLCVBar(
                    Symbol("SPY"),
                    timestamp,
                    spy_price,
                    spy_price,
                    spy_price,
                    spy_price,
                    1_000,
                ),
            )
        )
    return tuple(bars)


def _synthetic_specification(
    plan: Any,
    configuration: EventOpeningBreakoutConfiguration,
    scenario_id: str,
    source_commit: str,
) -> dict[str, object]:
    return cast(
        dict[str, object],
        canonicalize(
            {
                "schema_version": (
                    "intraday-event-opening-breakout-001-synthetic-equivalence-run-v1"
                ),
                "program_id": PROGRAM_ID,
                "runner_version": RUNNER_VERSION,
                "source_commit": source_commit,
                "plan_sha256": plan.sha256,
                "plan_fingerprint": plan.plan_fingerprint,
                "configuration": _configuration_summary(configuration),
                "period": canonicalize(_EQUIVALENCE_PERIOD),
                "cost_model": {
                    "scenario_id": scenario_id,
                    "execution_delay_bars": {
                        "normal": 1,
                        "zero_cost_diagnostic": 1,
                        "stress_a": 2,
                        "stress_b": 3,
                        "normal-delay-2": 2,
                        "normal-delay-3": 3,
                    }[scenario_id],
                },
                "context": {
                    "candidate_id": configuration.candidate_id,
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
    _require_non_broker_environment()
    plan = load_intraday_event_opening_breakout_001_plan(repository.resolve())
    choices = (
        (plan.configurations[0], "normal"),
        (plan.configurations[1], "zero_cost_diagnostic"),
        (plan.configurations[2], "stress_a"),
        (plan.configurations[0], "normal-delay-3"),
    )
    tasks = tuple(
        cast(
            dict[str, object],
            canonicalize(
                {
                    "schema_version": ("intraday-event-opening-breakout-001-equivalence-task-v1"),
                    "program_id": PROGRAM_ID,
                    "source_commit": source_commit,
                    "context": {
                        "candidate_id": configuration.candidate_id,
                        "scenario_id": scenario_id,
                    },
                    "protected_inputs_accessed": False,
                }
            ),
        )
        for configuration, scenario_id in choices
    )
    factory = _EquivalenceWorkerFactory(repository.resolve())
    preflight_process_stage(tasks, worker_factory=factory)
    started = time.perf_counter()
    sequential = run_process_stage(
        tasks,
        worker_factory=factory,
        workers=1,
        progress=lambda _done, _total, _task, _result: None,
    )
    sequential_seconds = time.perf_counter() - started
    started = time.perf_counter()
    parallel = run_process_stage(
        tasks,
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
            "report_equal": left["metrics"] == right["metrics"],
            "event_ledger_equal": left["event_ledger"] == right["event_ledger"],
            "canonical_report_equal": left["report_bytes"] == right["report_bytes"],
        }
        equivalent = equivalent and left == right and all(comparisons.values())
        fixtures.append(
            {
                key: left[key]
                for key in (
                    "candidate_id",
                    "scenario_id",
                    "run_id",
                    "run_fingerprint",
                    "signal_trace_fingerprint",
                    "decision_trace_fingerprint",
                    "fill_trace_fingerprint",
                    "round_trip_fingerprint",
                    "event_ledger_fingerprint",
                    "report_sha256",
                    "report_fingerprint",
                )
            }
            | comparisons
        )
    if not equivalent:
        raise ValueError("Event Opening Breakout 001 one-worker/four-worker equivalence differs")
    sequential_text = f"{max(sequential_seconds, 0.000001):.6f}"
    parallel_text = f"{max(parallel_seconds, 0.000001):.6f}"
    speedup_text = f"{max(sequential_seconds / parallel_seconds, 0.000001):.6f}"
    return {
        "schema_version": "intraday-event-opening-breakout-001-parallel-equivalence-v1",
        "program_id": PROGRAM_ID,
        "verification_source_commit": source_commit,
        "fixture_kind": "synthetic-non-protected-spy-opening-breakout-five-minute-bars",
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


def verify_intraday_event_opening_breakout_001_parallel_equivalence(
    repository: Path,
) -> dict[str, object]:
    repository = repository.resolve()
    return _parallel_equivalence(repository, source_commit=_source_commit(repository))


def intraday_event_opening_breakout_001_plan_summary(repository: Path) -> dict[str, object]:
    repository = repository.resolve()
    plan = load_intraday_event_opening_breakout_001_plan(repository)
    launch_bound = False
    if (
        REVIEWED_LAUNCH_CONTROL_SHA256 is not None
        and REVIEWED_LAUNCH_CONTROL_FINGERPRINT is not None
    ):
        try:
            _load_launch_control(repository, source_commit=_source_commit(repository))
        except ValueError:
            pass
        else:
            launch_bound = True
    return {
        "program_id": PROGRAM_ID,
        "status": "launch-reviewed-ready" if launch_bound else "implementation-awaiting-review",
        "terminal": False,
        "outcome": None,
        "launchable": launch_bound,
        "plan_sha256": plan.sha256,
        "plan_fingerprint": plan.plan_fingerprint,
        "calendar_sha256": plan.calendar_sha256,
        "calendar_fingerprint": plan.calendar_fingerprint,
        "source_evidence_sha256": plan.source_evidence_sha256,
        "source_evidence_fingerprint": plan.source_evidence_fingerprint,
        "plan_review_sha256": plan.review_sha256,
        "plan_review_fingerprint": plan.review_fingerprint,
        "parent_configuration_count": len(plan.configurations),
        "discovery_run_specification_count": len(plan.configurations) * 2,
        "maximum_run_specifications": 46,
        "maximum_attempts": 138,
        "period_count": len(plan.periods),
        "eligible_event_count": len(plan.eligible_events),
        "excluded_event_count": len(plan.excluded_events),
        "default_workers": DEFAULT_RESEARCH_WORKERS,
        "launch_control_bound": launch_bound,
        "controlled_range_status": "none-eligible",
        "authority": _AUTHORITY,
    }


def intraday_event_opening_breakout_001_status(data_home: Path) -> dict[str, object]:
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


def run_intraday_event_opening_breakout_001_campaign(
    repository: Path,
    data_home: Path,
    *,
    workers: int = DEFAULT_RESEARCH_WORKERS,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    return IntradayEventOpeningBreakout001Runner(
        repository,
        data_home,
        workers=workers,
        progress=progress,
    ).run()
