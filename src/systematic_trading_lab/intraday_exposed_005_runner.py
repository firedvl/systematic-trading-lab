"""Process-parallel runner for the frozen Intraday Exposed 005 campaign."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from .config import non_broker_subprocess_environment
from .datasets import DatasetService
from .fingerprints import canonical_json, canonicalize, fingerprint
from .intraday_execution_cost_model import load_intraday_execution_cost_model
from .intraday_exposed_002_engine import IntradayExposed002Engine
from .intraday_exposed_002_plan import (
    Exposed002Configuration,
    Exposed002Period,
    IntradayExposed002Plan,
)
from .intraday_exposed_002_runner import (
    IntradayExposed002Runner,
    _configuration_summary,
    _dataset_bindings,
    _DatasetBinding,
    _EvaluationBoundStrategy,
    _exclusive_file_lock,
    _mapping,
    _required_text,
    _scenarios,
    _sha256_path,
    _source_commit,
    _text,
    _write_create_only,
    _write_create_only_text,
)
from .intraday_exposed_002_runner import _run_report as _source_run_report
from .intraday_exposed_002_strategies import build_intraday_exposed_002_strategy
from .intraday_exposed_004_runner import (
    FAILURE_RELATIVE_PATH as EXPOSED_004_FAILURE_RELATIVE_PATH,
)
from .intraday_exposed_004_runner import (
    REVIEWED_FAILURE_FINGERPRINT as REVIEWED_EXPOSED_004_FAILURE_FINGERPRINT,
)
from .intraday_exposed_004_runner import (
    REVIEWED_FAILURE_SHA256 as REVIEWED_EXPOSED_004_FAILURE_SHA256,
)
from .intraday_exposed_004_runner import (
    _load_failure as _load_exposed_004_failure,
)
from .intraday_exposed_005_launch_control import (
    REVIEWED_LAUNCH_CONTROL_FINGERPRINT,
    REVIEWED_LAUNCH_CONTROL_SHA256,
)
from .intraday_exposed_005_plan import (
    PROGRAM_ID,
    REVIEWED_JUNE_DISPOSITION_FINGERPRINT,
    REVIEWED_JUNE_DISPOSITION_SHA256,
    REVIEWED_PLAN_FINGERPRINT,
    REVIEWED_PLAN_REVIEW_FINGERPRINT,
    REVIEWED_PLAN_REVIEW_SHA256,
    REVIEWED_PLAN_SHA256,
    Exposed005Configuration,
    IntradayExposed005Plan,
    load_intraday_exposed_005_plan,
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

RUNNER_VERSION = "intraday-exposed-005-runner-v1"
RUN_SCHEMA = "intraday-exposed-005-run-v1"
RUN_REPORT_SCHEMA = "intraday-exposed-005-backtest-report-v1"
FINAL_FREEZE_SCHEMA = "intraday-exposed-005-final-freeze-v1"
FINAL_REPORT_SCHEMA = "intraday-exposed-005-final-report-v1"
PROGRAM_BINDING_SCHEMA = "intraday-exposed-005-program-binding-v1"
DATABASE_NAME = "intraday-exposed-005.sqlite3"
ENGINE_VERSION = "intraday-exposed-002-engine-v1"
STRATEGY_VERSION = "intraday-exposed-002-mechanics-v1"
LAUNCH_CONTROL_RELATIVE_PATH = Path(
    "config/research/intraday-exposed-005-launch-control-review-v1.json"
)
_LAUNCH_CONTROL_SCHEMA = "intraday-exposed-005-launch-control-review-v1"
_LAUNCH_CONTROL_FILES = (
    "src/systematic_trading_lab/research_executor.py",
    "src/systematic_trading_lab/research_attempts.py",
    "src/systematic_trading_lab/intraday_exposed_004_runner.py",
    "src/systematic_trading_lab/intraday_exposed_005_plan.py",
    "src/systematic_trading_lab/intraday_exposed_005_runner.py",
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
    "fill-sequence-fingerprint",
    "round-trip-fingerprint",
    "metrics",
    "canonical-report-bytes",
    "canonical-report-sha256",
    "report-fingerprint",
)
_LAUNCH_CONTROL_POST_REVIEW_FILES = frozenset(
    {
        LAUNCH_CONTROL_RELATIVE_PATH.as_posix(),
        "src/systematic_trading_lab/intraday_exposed_005_launch_control.py",
        "tests/unit/test_intraday_exposed_005_runner.py",
        "CURRENT_STATE.md",
        "DECISIONS.md",
        "ROADMAP.md",
        "docs/research-campaigns/intraday-exposed-003-program.md",
        "docs/research-campaigns/intraday-exposed-004-program.md",
        "docs/research-campaigns/intraday-exposed-005-program.md",
    }
)
_LEASE_TIMEOUT = timedelta(seconds=300)
_HEARTBEAT_INTERVAL = timedelta(seconds=60)
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


class IntradayExposed005Store:
    """005 view over the generic append-only attempt store."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.attempts = ResearchAttemptStore(
            self.root,
            database_name=DATABASE_NAME,
            lease_timeout=_LEASE_TIMEOUT,
            reconcile_on_open=False,
            attempt_id_prefix="ie005a-",
        )
        self.path = self.attempts.path

    def bind(self, value: Mapping[str, object]) -> None:
        self.attempts.bind(value)

    def reserve(self, specifications: Sequence[Mapping[str, object]]) -> None:
        run_ids = tuple(_run_id(value) for value in specifications)
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("Intraday Exposed 005 run specifications collide")
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
        self.attempts.fail(
            claim,
            failure_class=failure_class,
            reason=reason[:4000],
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
        return {
            **row,
            "reservation_id": _reservation_id(str(row["run_fingerprint"])),
            "stage": _text(context, "stage"),
            "base_candidate_id": context.get("base_candidate_id"),
            "candidate_id": _text(context, "candidate_id"),
            "family_id": _text(context, "family_id"),
            "period_id": _text(context, "period_id"),
            "scenario_id": _text(context, "scenario_id"),
            "report_path": relative_report,
            "report_sha256": row.get("canonical_report_sha256"),
            "report_fingerprint": row.get("canonical_report_fingerprint"),
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
    """One persistent stage worker with private immutable data state."""

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
        self.control_plan = load_intraday_exposed_005_plan(self.repository)
        self.plan = _effective_plan(self.control_plan)
        self.cost_model = load_intraday_execution_cost_model(self.repository)
        self.datasets = _dataset_bindings(self.plan)
        self.data_by_dataset = _read_only_dataset_services(self.data_home, self.datasets)
        IntradayExposed002Runner._verify_datasets(cast(Any, self))
        self.scenarios = _scenarios(self.cost_model)
        self._bar_cache: dict[str, tuple[Any, ...]] = {}
        self.attempt_store = IntradayExposed005Store(runtime_root)

    def __call__(self, specification: Mapping[str, object]) -> str:
        run_id = _run_id(specification)
        claim = self.attempt_store.claim(run_id, source_sha=self.source_commit)
        context = _mapping(specification.get("context"), "run context")
        with (
            self.attempt_store.capture_output(claim),
            AttemptHeartbeat(
                self.attempt_store.attempts,
                claim,
                interval=_HEARTBEAT_INTERVAL,
            ),
        ):
            failure_class = "candidate"
            try:
                configuration = self._configuration(_text(context, "candidate_id"))
                source_configuration = self._source_configuration(configuration.candidate_id)
                period = self._period(_text(context, "period_id"))
                scenario = self.scenarios[_text(context, "scenario_id")]
                strategy = _EvaluationBoundStrategy(
                    build_intraday_exposed_002_strategy(
                        source_configuration,
                        cost_model=self.cost_model,
                    ),
                    period.evaluation_start,
                )
                failure_class = "data"
                bars = IntradayExposed002Runner._bars(cast(Any, self), period)
                failure_class = "candidate"
                result = IntradayExposed002Engine(
                    Decimal(str(self.plan.payload["execution"]["initial_cash"])),
                    scenario,
                    self.cost_model.regulatory_fees,
                ).run(bars, strategy)
                report = _run_report(specification, result, period)
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

    def _configuration(self, candidate_id: str) -> Exposed002Configuration:
        for item in self.plan.configurations:
            if item.candidate_id == candidate_id:
                return item
        raise ValueError(f"unknown Intraday Exposed 005 candidate: {candidate_id}")

    def _source_configuration(self, candidate_id: str) -> Exposed002Configuration:
        control = self._control_configuration(candidate_id)
        for item in self.control_plan.source_plan.source_plan.source_plan.configurations:
            if item.candidate_id == control.source_candidate_id:
                return item
        raise ValueError(
            f"unknown Intraday Exposed 005 source candidate: {control.source_candidate_id}"
        )

    def _control_configuration(self, candidate_id: str) -> Exposed005Configuration:
        for item in self.control_plan.configurations:
            if item.candidate_id == candidate_id:
                return item
        raise ValueError(f"unknown Intraday Exposed 005 candidate: {candidate_id}")

    def _period(self, period_id: str) -> Exposed002Period:
        for item in self.plan.periods:
            if item.period_id == period_id:
                return item
        raise ValueError(f"unknown Intraday Exposed 005 period: {period_id}")


class IntradayExposed005Runner(IntradayExposed002Runner):
    """Reuse frozen 002 stage logic and replace only same-stage scheduling."""

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
        self.source_commit = _source_commit(self.repository)
        self.launch_control = _load_launch_control(
            self.repository,
            source_commit=self.source_commit,
        )
        self.workers = workers
        self.progress = progress or (lambda _message: None)
        self.control_plan = load_intraday_exposed_005_plan(self.repository)
        self.plan = _effective_plan(self.control_plan)
        self.cost_model = load_intraday_execution_cost_model(self.repository)
        self.datasets = _dataset_bindings(self.plan)
        self.data_by_dataset = (
            {binding.dataset_id: data_service for binding in self.datasets}
            if data_service is not None
            else _read_only_dataset_services(self.data_home, self.datasets)
        )
        self._verify_datasets()
        self.runtime_root = self.data_home / PROGRAM_ID
        self.attempt_store = IntradayExposed005Store(self.runtime_root)
        self.store = cast(Any, self.attempt_store)
        self.scenarios = _scenarios(self.cost_model)
        self._bar_cache = {}
        self.attempt_store.bind(self._program_binding())

    def _program_binding(self) -> dict[str, object]:
        source = self.control_plan.source_plan.source_plan.source_plan
        return {
            "schema_version": PROGRAM_BINDING_SCHEMA,
            "program_id": PROGRAM_ID,
            "runner_version": RUNNER_VERSION,
            "engine_version": ENGINE_VERSION,
            "strategy_version": STRATEGY_VERSION,
            "source_commit": self.source_commit,
            "plan": self._plan_evidence(),
            "source_design": {
                "plan_sha256": source.sha256,
                "plan_fingerprint": source.plan_fingerprint,
                "amendment_sha256": source.amendment_sha256,
                "amendment_fingerprint": source.amendment_fingerprint,
                "data_binding_sha256": source.data_binding_sha256,
                "data_binding_fingerprint": source.data_binding_fingerprint,
            },
            "cost_model_id": self.cost_model.payload["cost_model_id"],
            "cost_model_sha256": self.cost_model.sha256,
            "cost_model_fingerprint": self.cost_model.model_fingerprint,
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

    def _require_no_failures(self) -> None:
        failed = tuple(row for row in self.attempt_store.list_runs() if row["status"] == "failed")
        if failed:
            raise AttemptStateError(
                f"Intraday Exposed 005 has {len(failed)} terminal failed run(s); "
                "no retry is allowed"
            )

    def _specification(
        self,
        stage: str,
        configuration: Exposed002Configuration,
        period: Exposed002Period,
        scenario_id: str,
        *,
        base_candidate_id: str | None = None,
    ) -> dict[str, object]:
        specification = super()._specification(
            stage,
            configuration,
            period,
            scenario_id,
            base_candidate_id=base_candidate_id,
        )
        control = self._control_configuration(configuration.candidate_id)
        configuration_value = dict(
            _mapping(specification.get("configuration"), "run configuration")
        )
        configuration_value.update(
            {
                "source_candidate_id": control.source_candidate_id,
                "source_exposed_003_candidate_id": control.source_exposed_003_candidate_id,
                "source_exposed_004_candidate_id": control.source_exposed_004_candidate_id,
            }
        )
        specification.update(
            {
                "schema_version": RUN_SCHEMA,
                "program_id": PROGRAM_ID,
                "runner_version": RUNNER_VERSION,
                "plan_sha256": REVIEWED_PLAN_SHA256,
                "plan_fingerprint": REVIEWED_PLAN_FINGERPRINT,
                "plan_review_sha256": REVIEWED_PLAN_REVIEW_SHA256,
                "plan_review_fingerprint": REVIEWED_PLAN_REVIEW_FINGERPRINT,
                "june_disposition_sha256": REVIEWED_JUNE_DISPOSITION_SHA256,
                "june_disposition_fingerprint": REVIEWED_JUNE_DISPOSITION_FINGERPRINT,
                "source_exposed_004_plan_sha256": self.control_plan.source_plan.sha256,
                "source_exposed_004_plan_fingerprint": (
                    self.control_plan.source_plan.plan_fingerprint
                ),
                "source_exposed_003_plan_sha256": (
                    self.control_plan.source_plan.source_plan.sha256
                ),
                "source_exposed_003_plan_fingerprint": (
                    self.control_plan.source_plan.source_plan.plan_fingerprint
                ),
                "source_plan_sha256": (
                    self.control_plan.source_plan.source_plan.source_plan.sha256
                ),
                "source_plan_fingerprint": (
                    self.control_plan.source_plan.source_plan.source_plan.plan_fingerprint
                ),
                "configuration": configuration_value,
                "authority": _AUTHORITY,
            }
        )
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
                raise AttemptStateError(f"Intraday Exposed 005 run is terminal: {run_id}")
            elif row["status"] == "running":
                raise AttemptStateError(f"Intraday Exposed 005 run has an active attempt: {run_id}")
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

    def _source_configuration(self, candidate_id: str) -> Exposed002Configuration:
        source_id = self._control_configuration(candidate_id).source_candidate_id
        for item in self.control_plan.source_plan.source_plan.source_plan.configurations:
            if item.candidate_id == source_id:
                return item
        raise ValueError(f"unknown Intraday Exposed 005 source candidate: {source_id}")

    def _control_configuration(self, candidate_id: str) -> Exposed005Configuration:
        for item in self.control_plan.configurations:
            if item.candidate_id == candidate_id:
                return item
        raise ValueError(f"unknown Intraday Exposed 005 candidate: {candidate_id}")

    def _load_report(self, row: Mapping[str, object]) -> Mapping[str, Any]:
        if row.get("status") != "completed":
            raise ValueError("Intraday Exposed 005 run is not completed")
        relative = Path(_required_text(row.get("report_path"), "report path"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Intraday Exposed 005 report path is unsafe")
        raw = (self.runtime_root / relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row.get("report_sha256"):
            raise ValueError("Intraday Exposed 005 report SHA-256 differs")
        value = _mapping(json.loads(raw), "run report")
        stored_fingerprint = _text(value, "report_fingerprint")
        unsigned = dict(value)
        del unsigned["report_fingerprint"]
        specification = _mapping(value.get("specification"), "report specification")
        if (
            value.get("schema_version") != RUN_REPORT_SCHEMA
            or value.get("program_id") != PROGRAM_ID
            or value.get("run_id") != row.get("run_id")
            or value.get("specification_fingerprint") != fingerprint(specification)
            or fingerprint(specification) != row.get("run_fingerprint")
            or stored_fingerprint != row.get("report_fingerprint")
            or fingerprint(unsigned) != stored_fingerprint
            or value.get("authority") != _AUTHORITY
        ):
            raise ValueError("Intraday Exposed 005 report fingerprint differs")
        return value

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
            "cohort": [self._configuration_summary(value) for value in cohort],
            "cohort_size": len(cohort),
            "all_runtime_runs": [_run_evidence(row) for row in runs],
            "attempt_summary": _attempt_summary(runs, histories),
            "attempt_histories": histories,
            "june_blocker": {
                "path": "config/research/intraday-exposed-005-june-disposition-v1.json",
                "sha256": REVIEWED_JUNE_DISPOSITION_SHA256,
                "fingerprint": REVIEWED_JUNE_DISPOSITION_FINGERPRINT,
                "range_status": "ineligible",
                "june_read": False,
                "substitute_range": False,
                "controlled_plan_created": False,
                "terminal_action": (
                    "close-empty-cohort-with-no-controlled-qualified-candidate"
                    if not cohort
                    else "terminal-stop-before-controlled-evaluation"
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
                else "terminally-interrupted-controlled-range-ineligible"
            ),
            "terminal_message": (
                "AUTONOMOUS INTRADAY EXPOSED 005 COMPLETE — NO CONTROLLED-QUALIFIED CANDIDATE"
                if empty
                else "AUTONOMOUS INTRADAY EXPOSED 005 TERMINALLY INTERRUPTED"
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
            "cohort": [self._configuration_summary(value) for value in cohort],
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
                "reason": "June is ineligible and no substitute range is allowed.",
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
            "terminal_message": "AUTONOMOUS INTRADAY EXPOSED 005 TERMINALLY INTERRUPTED",
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

    def _plan_evidence(self) -> dict[str, object]:
        source_004 = self.control_plan.source_plan
        source_003 = source_004.source_plan
        source_002 = source_003.source_plan
        return {
            "sha256": self.control_plan.sha256,
            "fingerprint": self.control_plan.plan_fingerprint,
            "review_sha256": REVIEWED_PLAN_REVIEW_SHA256,
            "review_fingerprint": REVIEWED_PLAN_REVIEW_FINGERPRINT,
            "source_exposed_004_plan_sha256": source_004.sha256,
            "source_exposed_004_plan_fingerprint": source_004.plan_fingerprint,
            "source_exposed_003_plan_sha256": source_003.sha256,
            "source_exposed_003_plan_fingerprint": source_003.plan_fingerprint,
            "source_plan_sha256": source_002.sha256,
            "source_plan_fingerprint": source_002.plan_fingerprint,
            "source_amendment_sha256": source_002.amendment_sha256,
            "source_amendment_fingerprint": source_002.amendment_fingerprint,
            "source_data_binding_sha256": source_002.data_binding_sha256,
            "source_data_binding_fingerprint": source_002.data_binding_fingerprint,
            "june_disposition_sha256": self.control_plan.june_disposition_sha256,
            "june_disposition_fingerprint": self.control_plan.june_disposition_fingerprint,
        }

    def _configuration_summary(self, candidate_id: str) -> dict[str, object]:
        summary = _configuration_summary(self._configuration(candidate_id))
        control = self._control_configuration(candidate_id)
        summary.update(
            {
                "source_candidate_id": control.source_candidate_id,
                "source_exposed_003_candidate_id": control.source_exposed_003_candidate_id,
                "source_exposed_004_candidate_id": control.source_exposed_004_candidate_id,
            }
        )
        return summary


_STATUSES = ("pending", "running", "completed", "failed")


def _effective_plan(control: IntradayExposed005Plan) -> IntradayExposed002Plan:
    source = control.source_plan.source_plan.source_plan
    configurations = tuple(
        Exposed002Configuration(
            item.candidate_id,
            item.family_id,
            item.family_ordinal,
            item.parameters,
            item.neighbor_ids,
        )
        for item in control.configurations
    )
    return IntradayExposed002Plan(
        control.path,
        control.sha256,
        control.plan_fingerprint,
        source.amendment_path,
        source.amendment_sha256,
        source.amendment_fingerprint,
        source.data_binding_path,
        source.data_binding_sha256,
        source.data_binding_fingerprint,
        source.payload,
        source.amendment,
        source.data_binding,
        configurations,
        source.periods,
    )


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
                f"Intraday Exposed 005 dataset location is missing: {binding.dataset_id}"
            ) from error
        resolved[binding.dataset_id] = service
    return MappingProxyType(resolved)


def _run_id(specification: Mapping[str, object]) -> str:
    return f"ie005r-{fingerprint(specification)[:24]}"


def _reservation_id(run_fingerprint: str) -> str:
    return f"ie005q-{run_fingerprint[:24]}"


def _run_report(
    specification: Mapping[str, object],
    result: Any,
    period: Exposed002Period,
) -> dict[str, object]:
    payload = _source_run_report(specification, result, period)
    del payload["report_fingerprint"]
    payload.update(
        {
            "schema_version": RUN_REPORT_SCHEMA,
            "program_id": PROGRAM_ID,
            "run_id": _run_id(specification),
            "authority": _AUTHORITY,
        }
    )
    payload["report_fingerprint"] = fingerprint(payload)
    return payload


def _run_evidence(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "run_id": row["run_id"],
        "reservation_id": row["reservation_id"],
        "run_fingerprint": row["run_fingerprint"],
        "stage": row["stage"],
        "base_candidate_id": row["base_candidate_id"],
        "candidate_id": row["candidate_id"],
        "family_id": row["family_id"],
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
    runs: Sequence[Mapping[str, object]], histories: Sequence[Mapping[str, object]]
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
        "v3_data_or_results": False,
        "protected_campaign_results": False,
        "paper_broker_or_live_state": False,
        "strategic_allocation_21": False,
    }


def _final_markdown(report: Mapping[str, object], json_sha256: str) -> str:
    counts = _mapping(report.get("counts"), "final counts")
    lines = [
        "# Intraday Exposed 005 final report",
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
            "June remained unread. Committed V2 exposure makes it ineligible, and no substitute "
            "range or controlled plan was used.",
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
        raise ValueError("Intraday Exposed 005 final report differs")
    return value


def _validate_final_evidence(runtime: Path, report: Mapping[str, Any]) -> None:
    database = _mapping(report.get("runtime_database"), "runtime database")
    if database.get("path") != DATABASE_NAME or database.get("sha256") != _sha256_path(
        runtime / DATABASE_NAME
    ):
        raise ValueError("Intraday Exposed 005 runtime database differs")
    freeze_evidence = report.get("final_freeze")
    if freeze_evidence is None:
        return
    evidence = _mapping(freeze_evidence, "final freeze evidence")
    relative = _required_text(evidence.get("path"), "freeze path")
    if relative != "final-freeze.json":
        raise ValueError("Intraday Exposed 005 final freeze path differs")
    freeze_path = runtime / relative
    freeze = _mapping(json.loads(freeze_path.read_bytes()), "final freeze")
    stored_freeze = _text(freeze, "freeze_fingerprint")
    unsigned_freeze = dict(freeze)
    del unsigned_freeze["freeze_fingerprint"]
    if (
        evidence.get("sha256") != _sha256_path(freeze_path)
        or evidence.get("fingerprint") != stored_freeze
        or freeze.get("schema_version") != FINAL_FREEZE_SCHEMA
        or freeze.get("program_id") != PROGRAM_ID
        or freeze.get("source_commit") != report.get("source_commit")
        or freeze.get("authority") != _AUTHORITY
        or fingerprint(unsigned_freeze) != stored_freeze
    ):
        raise ValueError("Intraday Exposed 005 final freeze differs")


def _load_launch_control(repository: Path, *, source_commit: str) -> Mapping[str, Any]:
    path = repository / LAUNCH_CONTROL_RELATIVE_PATH
    if not path.is_file():
        raise ValueError("Intraday Exposed 005 launch control review is missing")
    if REVIEWED_LAUNCH_CONTROL_SHA256 is None or REVIEWED_LAUNCH_CONTROL_FINGERPRINT is None:
        raise ValueError("Intraday Exposed 005 launch control review is not hash-bound")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != REVIEWED_LAUNCH_CONTROL_SHA256:
        raise ValueError("Intraday Exposed 005 launch control review SHA-256 differs")
    try:
        value = _mapping(json.loads(raw), "launch control review")
    except json.JSONDecodeError as error:
        raise ValueError("Intraday Exposed 005 launch control review is invalid JSON") from error
    unsigned = dict(value)
    stored_fingerprint = unsigned.pop("review_fingerprint", None)
    if (
        stored_fingerprint != REVIEWED_LAUNCH_CONTROL_FINGERPRINT
        or fingerprint(unsigned) != REVIEWED_LAUNCH_CONTROL_FINGERPRINT
        or value.get("schema_version") != _LAUNCH_CONTROL_SCHEMA
        or value.get("review_id") != _LAUNCH_CONTROL_SCHEMA
        or value.get("status") != "passed"
        or value.get("verdict") != "pass"
        or value.get("authority") != _AUTHORITY
    ):
        raise ValueError("Intraday Exposed 005 launch control review differs")
    _require_exact_keys(
        value,
        {
            "schema_version",
            "review_id",
            "status",
            "verdict",
            "review_date",
            "review_method",
            "reviewed_plan",
            "implementation",
            "quality_gates",
            "equivalence",
            "intraday_exposed_003_disposition",
            "intraday_exposed_004_disposition",
            "independent_review",
            "scope_limit",
            "authority",
            "review_fingerprint",
        },
        "launch control review",
    )
    for key in ("review_date", "review_method", "scope_limit"):
        _required_text(value.get(key), f"launch control {key.replace('_', ' ')}")
    implementation_commit = _verify_launch_implementation(repository, value)
    _verify_launch_quality_gates(value, implementation_commit)
    _verify_launch_equivalence(value, implementation_commit)
    _verify_launch_disposition(value)
    _verify_launch_004_disposition(repository, value)
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
        raise ValueError("Intraday Exposed 005 launch independent review differs")
    _required_text(review.get("reviewer"), "launch independent reviewer")
    _verify_launch_source_lineage(repository, implementation_commit, source_commit)
    return MappingProxyType(dict(value))


def _verify_launch_implementation(repository: Path, value: Mapping[str, Any]) -> str:
    reviewed_plan = _mapping(value.get("reviewed_plan"), "launch reviewed plan")
    _require_exact_keys(
        reviewed_plan,
        {"path", "sha256", "fingerprint"},
        "launch reviewed plan",
    )
    if reviewed_plan != {
        "path": "config/research/intraday-exposed-005-plan-v1.json",
        "sha256": REVIEWED_PLAN_SHA256,
        "fingerprint": REVIEWED_PLAN_FINGERPRINT,
    }:
        raise ValueError("Intraday Exposed 005 launch reviewed plan differs")

    implementation = _mapping(value.get("implementation"), "launch implementation")
    _require_exact_keys(implementation, {"source_commit", "files"}, "launch implementation")
    implementation_commit = _validated_source_commit(implementation.get("source_commit"))
    files = implementation.get("files")
    if not isinstance(files, list) or len(files) != len(_LAUNCH_CONTROL_FILES):
        raise ValueError("Intraday Exposed 005 launch implementation files differ")
    for item, expected_path in zip(files, _LAUNCH_CONTROL_FILES, strict=True):
        binding = _mapping(item, "launch implementation file")
        _require_exact_keys(binding, {"path", "sha256"}, "launch implementation file")
        source_path = repository / expected_path
        if binding.get("path") != expected_path or binding.get("sha256") != _sha256_path(
            source_path
        ):
            raise ValueError("Intraday Exposed 005 launch implementation file differs")
    return implementation_commit


def _verify_launch_source_lineage(
    repository: Path,
    implementation_commit: str,
    runtime_commit: str,
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
        raise ValueError("Intraday Exposed 005 launch source lineage is unavailable") from error
    paths = frozenset(line for line in changed.stdout.splitlines() if line)
    required = {
        LAUNCH_CONTROL_RELATIVE_PATH.as_posix(),
        "src/systematic_trading_lab/intraday_exposed_005_launch_control.py",
    }
    if (
        ancestor.returncode != 0
        or not required.issubset(paths)
        or not paths.issubset(_LAUNCH_CONTROL_POST_REVIEW_FILES)
    ):
        raise ValueError("Intraday Exposed 005 launch source lineage differs")


def _verify_launch_quality_gates(value: Mapping[str, Any], source_commit: str) -> None:
    quality = _mapping(value.get("quality_gates"), "launch quality gates")
    _require_exact_keys(quality, {"source_commit", "results"}, "launch quality gates")
    results = quality.get("results")
    if quality.get("source_commit") != source_commit or not isinstance(results, list):
        raise ValueError("Intraday Exposed 005 launch quality gates differ")
    if len(results) != len(_LAUNCH_CONTROL_QUALITY_GATES):
        raise ValueError("Intraday Exposed 005 launch quality gate count differs")
    for result, command in zip(results, _LAUNCH_CONTROL_QUALITY_GATES, strict=True):
        gate = _mapping(result, "launch quality gate")
        _require_exact_keys(
            gate,
            {"command", "status", "exit_code", "summary"},
            "launch quality gate",
        )
        if (
            gate.get("command") != command
            or gate.get("status") != "passed"
            or isinstance(gate.get("exit_code"), bool)
            or gate.get("exit_code") != 0
        ):
            raise ValueError("Intraday Exposed 005 launch quality gate differs")
        _required_text(gate.get("summary"), "launch quality gate summary")


def _verify_launch_equivalence(value: Mapping[str, Any], source_commit: str) -> None:
    equivalence = _mapping(value.get("equivalence"), "launch equivalence")
    required = {
        "schema_version",
        "program_id",
        "verification_source_commit",
        "source_database",
        "source_database_sha256",
        "source_database_mutated",
        "dataset_inputs_mutated",
        "fixture_selection",
        "fixture_count",
        "worker_counts",
        "comparisons",
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
        equivalence.get("schema_version") != "intraday-exposed-003-parallel-equivalence-v1"
        or equivalence.get("program_id") != "intraday-exposed-003"
        or equivalence.get("verification_source_commit") != source_commit
        or equivalence.get("source_database") != "intraday-exposed-003/intraday-exposed-003.sqlite3"
        or _required_sha256(
            equivalence.get("source_database_sha256"),
            "launch equivalence source database SHA-256",
        )
        != equivalence.get("source_database_sha256")
        or equivalence.get("source_database_mutated") is not False
        or equivalence.get("dataset_inputs_mutated") is not False
        or equivalence.get("fixture_selection")
        != "completed-specification-configuration-and-scenario-only"
        or not isinstance(equivalence.get("worker_counts"), list)
        or any(type(item) is not int for item in equivalence.get("worker_counts", []))
        or equivalence.get("worker_counts") != [1, 4]
        or equivalence.get("comparisons") != list(_LAUNCH_CONTROL_EQUIVALENCE_COMPARISONS)
        or isinstance(fixture_count, bool)
        or not isinstance(fixture_count, int)
        or fixture_count < 3
        or not isinstance(fixtures, list)
        or len(fixtures) != fixture_count
        or equivalence.get("equivalent") is not True
    ):
        raise ValueError("Intraday Exposed 005 launch equivalence differs")
    for key in ("sequential_seconds", "parallel_seconds", "speedup"):
        _required_positive_decimal_text(equivalence.get(key), f"launch equivalence {key}")
    fixture_keys = {
        "run_id",
        "candidate_id",
        "scenario_id",
        "run_fingerprint",
        "fill_trace_fingerprint",
        "round_trip_fingerprint",
        "report_sha256",
        "report_fingerprint",
        "specification_equal",
        "metrics_equal",
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
            "fill_trace_fingerprint",
            "round_trip_fingerprint",
            "report_sha256",
            "report_fingerprint",
        ):
            _required_sha256(fixture.get(key), f"launch equivalence fixture {key}")
        if any(
            fixture.get(key) is not True
            for key in ("specification_equal", "metrics_equal", "canonical_report_equal")
        ):
            raise ValueError("Intraday Exposed 005 launch equivalence fixture differs")
        candidates.add(str(fixture["candidate_id"]))
        scenarios.add(str(fixture["scenario_id"]))
    if len(candidates) < 2 or len(scenarios) < 2:
        raise ValueError("Intraday Exposed 005 launch equivalence fixtures lack design span")


def _verify_launch_disposition(value: Mapping[str, Any]) -> None:
    disposition = _mapping(
        value.get("intraday_exposed_003_disposition"),
        "launch Intraday Exposed 003 disposition",
    )
    _require_exact_keys(
        disposition,
        {
            "inspection_scope",
            "classification",
            "database_exists",
            "run_counts",
            "attempt_count",
            "terminal",
            "valid_terminal_outcome",
            "evidence_preserved",
            "partial_strategy_merits_inspected",
            "process_stop",
            "intraday_exposed_005_required",
            "action",
        },
        "launch Intraday Exposed 003 disposition",
    )
    counts = _mapping(disposition.get("run_counts"), "launch Intraday Exposed 003 counts")
    _require_exact_keys(counts, set(_STATUSES), "launch Intraday Exposed 003 counts")
    if (
        disposition.get("inspection_scope") != "health-and-progress-metadata-only"
        or disposition.get("database_exists") is not True
        or any(
            isinstance(count, bool) or not isinstance(count, int) or count < 0
            for count in counts.values()
        )
        or isinstance(disposition.get("attempt_count"), bool)
        or not isinstance(disposition.get("attempt_count"), int)
        or cast(int, disposition["attempt_count"]) < 0
        or disposition.get("evidence_preserved") is not True
        or disposition.get("partial_strategy_merits_inspected") is not False
    ):
        raise ValueError("Intraday Exposed 005 launch Intraday Exposed 003 disposition differs")
    process_stop = _mapping(
        disposition.get("process_stop"),
        "launch Intraday Exposed 003 process stop",
    )
    _require_exact_keys(
        process_stop,
        {"required", "signal", "confirmed"},
        "launch Intraday Exposed 003 process stop",
    )
    classification = disposition.get("classification")
    terminal = disposition.get("terminal")
    valid = disposition.get("valid_terminal_outcome")
    required = disposition.get("intraday_exposed_005_required")
    action = disposition.get("action")
    if any(
        not isinstance(item, bool)
        for item in (
            terminal,
            valid,
            required,
            process_stop.get("required"),
            process_stop.get("confirmed"),
        )
    ):
        raise ValueError("Intraday Exposed 005 launch Intraday Exposed 003 flags differ")
    expected: tuple[object, ...]
    if classification == "valid-completed-terminal":
        raise ValueError(
            "Intraday Exposed 005 launch is not required after valid Exposed 003 completion"
        )
    elif classification == "incomplete-or-invalid-terminal":
        expected = (
            True,
            False,
            True,
            False,
            None,
            True,
            "preserve-and-supersede-for-execution-throughput",
        )
    elif classification == "active-materially-incomplete":
        expected = (
            False,
            False,
            True,
            True,
            "SIGTERM",
            True,
            "stop-preserve-and-supersede-for-execution-throughput",
        )
    else:
        raise ValueError("Intraday Exposed 005 launch Intraday Exposed 003 classification differs")
    observed = (
        terminal,
        valid,
        required,
        process_stop.get("required"),
        process_stop.get("signal"),
        process_stop.get("confirmed"),
        action,
    )
    if observed != expected:
        raise ValueError("Intraday Exposed 005 launch Intraday Exposed 003 action differs")


def _verify_launch_004_disposition(repository: Path, value: Mapping[str, Any]) -> None:
    observed = _mapping(
        value.get("intraday_exposed_004_disposition"),
        "launch Intraday Exposed 004 disposition",
    )
    failure = _load_exposed_004_failure(repository)
    runtime = _mapping(failure.get("runtime"), "Intraday Exposed 004 failure runtime")
    inspection = _mapping(failure.get("inspection"), "Intraday Exposed 004 failure inspection")
    disposition = _mapping(failure.get("disposition"), "Intraday Exposed 004 failure disposition")
    expected = {
        "artifact": {
            "path": EXPOSED_004_FAILURE_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_EXPOSED_004_FAILURE_SHA256,
            "fingerprint": REVIEWED_EXPOSED_004_FAILURE_FINGERPRINT,
        },
        "inspection_scope": inspection["scope"],
        "classification": failure["classification"],
        "source_commit": failure["source_commit"],
        "database_sha256": runtime["database_sha256"],
        "file_count": runtime["file_count"],
        "run_counts": runtime["run_counts"],
        "attempt_count": runtime["attempt_count"],
        "canonical_report_count": runtime["canonical_report_count"],
        "strategy_execution_started": runtime["strategy_execution_started"],
        "evidence_preserved": runtime["evidence_preserved"],
        "partial_strategy_merits_inspected": inspection["strategy_merits_inspected"],
        "successor_program_id": disposition["successor_program_id"],
        "action": disposition["action"],
    }
    if dict(observed) != expected:
        raise ValueError("Intraday Exposed 005 launch Intraday Exposed 004 disposition differs")


def _require_exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} fields differ")


def _validated_source_commit(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("Intraday Exposed 005 launch source commit differs")
    return value


def _required_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} differs")
    return value


def _required_positive_decimal_text(value: object, label: str) -> None:
    try:
        parsed = Decimal(str(value))
    except Exception as error:
        raise ValueError(f"{label} differs") from error
    if not isinstance(value, str) or not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"{label} differs")


def intraday_exposed_005_plan_summary(repository: Path) -> dict[str, object]:
    plan = load_intraday_exposed_005_plan(repository.resolve())
    return {
        "program_id": PROGRAM_ID,
        "status": "implementation-review-pending",
        "plan_sha256": plan.sha256,
        "plan_fingerprint": plan.plan_fingerprint,
        "plan_review_sha256": REVIEWED_PLAN_REVIEW_SHA256,
        "plan_review_fingerprint": REVIEWED_PLAN_REVIEW_FINGERPRINT,
        "source_exposed_004_plan_sha256": plan.source_plan.sha256,
        "source_exposed_004_plan_fingerprint": plan.source_plan.plan_fingerprint,
        "source_exposed_003_plan_sha256": plan.source_plan.source_plan.sha256,
        "source_exposed_003_plan_fingerprint": plan.source_plan.source_plan.plan_fingerprint,
        "source_plan_sha256": plan.source_plan.source_plan.source_plan.sha256,
        "source_plan_fingerprint": plan.source_plan.source_plan.source_plan.plan_fingerprint,
        "parent_configuration_count": len(plan.configurations),
        "discovery_run_count": len(plan.configurations) * 2,
        "period_count": len(plan.periods),
        "latest_evaluation_bar": plan.periods[-1].evaluation_end,
        "default_workers": DEFAULT_RESEARCH_WORKERS,
        "launch_control_exists": (repository / LAUNCH_CONTROL_RELATIVE_PATH).is_file(),
        "june_status": "ineligible-no-read-no-substitute",
        "authority": _AUTHORITY,
    }


def intraday_exposed_005_status(data_home: Path) -> dict[str, object]:
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
            for failure_class, count in connection.execute(
                "SELECT failure_class, COUNT(*) FROM research_runs "
                "WHERE failure_class IS NOT NULL GROUP BY failure_class"
            ).fetchall():
                failures[str(failure_class)] = int(count)
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
        "cohort_size": None
        if final is None
        else _mapping(final.get("counts"), "final counts").get("cohort"),
        "authority": _AUTHORITY,
    }


def run_intraday_exposed_005_campaign(
    repository: Path,
    data_home: Path,
    *,
    workers: int = DEFAULT_RESEARCH_WORKERS,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    return IntradayExposed005Runner(
        repository,
        data_home,
        workers=workers,
        progress=progress,
    ).run()
