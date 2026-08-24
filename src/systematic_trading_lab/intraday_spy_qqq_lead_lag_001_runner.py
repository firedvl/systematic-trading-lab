"""Restart-safe ordinary-session runner for Intraday SPY-QQQ Lead-Lag 001."""

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
from zoneinfo import ZoneInfo

from .calendar import expected_bar_timestamps, expected_sessions
from .config import non_broker_subprocess_environment
from .datasets import DatasetService
from .domain import OHLCVBar, Symbol, Timeframe
from .fingerprints import canonical_json, canonicalize, fingerprint
from .intraday_autonomous_research_program import (
    PROGRAM_FINGERPRINT as AUTONOMOUS_PROGRAM_FINGERPRINT,
)
from .intraday_autonomous_research_program import (
    PROGRAM_RELATIVE_PATH as AUTONOMOUS_PROGRAM_RELATIVE_PATH,
)
from .intraday_autonomous_research_program import (
    PROGRAM_SHA256 as AUTONOMOUS_PROGRAM_SHA256,
)
from .intraday_autonomous_research_program import (
    REVIEW_FINGERPRINT as AUTONOMOUS_REVIEW_FINGERPRINT,
)
from .intraday_autonomous_research_program import (
    REVIEW_RELATIVE_PATH as AUTONOMOUS_REVIEW_RELATIVE_PATH,
)
from .intraday_autonomous_research_program import (
    REVIEW_SHA256 as AUTONOMOUS_REVIEW_SHA256,
)
from .intraday_event_drift_001_plan import load_intraday_event_drift_001_plan
from .intraday_event_drift_001_runner import (
    _attempt_summary as _base_attempt_summary,
)
from .intraday_event_drift_001_runner import (
    _dataset_bindings,
    _read_only_dataset_services,
    _run_dataset_inputs,
)
from .intraday_execution_cost_model import load_intraday_execution_cost_model
from .intraday_exposed_002_engine import Exposed002ReplayResult, IntradayExposed002Engine
from .intraday_exposed_002_runner import (
    _ACCOUNTING_PRECISION,
    IntradayExposed002Runner,
    _account_day,
    _exclusive_file_lock,
    _gate_results,
    _gates,
    _ledger_metric,
    _mapping,
    _positive_concentration,
    _report_metric,
    _required_text,
    _scenarios,
    _sha256_path,
    _source_commit,
    _text,
    _write_create_only,
    _write_create_only_text,
)
from .intraday_exposed_002_runner import _aggregate_reports as _source_aggregate_reports
from .intraday_exposed_002_runner import _run_report as _source_run_report
from .intraday_spy_qqq_lead_lag_001_plan import (
    PLAN_FINGERPRINT,
    PLAN_RELATIVE_PATH,
    PLAN_SHA256,
    PROGRAM_ID,
    REVIEW_FINGERPRINT,
    REVIEW_RELATIVE_PATH,
    REVIEW_SHA256,
    STATE_FINGERPRINT,
    STATE_RELATIVE_PATH,
    STATE_SHA256,
    LeadLagConfiguration,
    LeadLagPeriod,
    load_intraday_spy_qqq_lead_lag_001_plan,
)
from .intraday_spy_qqq_lead_lag_001_strategies import (
    build_intraday_spy_qqq_lead_lag_001_strategy,
)
from .research_attempts import (
    AttemptClaim,
    AttemptHeartbeat,
    AttemptStateError,
    ResearchAttemptStore,
)
from .research_executor import DEFAULT_RESEARCH_WORKERS, preflight_process_stage, run_process_stage

REVIEWED_LAUNCH_CONTROL_SHA256: str | None
REVIEWED_LAUNCH_CONTROL_FINGERPRINT: str | None
try:  # Bound only by the later reviewed launch-control slice.
    from .intraday_spy_qqq_lead_lag_001_launch_control import (
        REVIEWED_LAUNCH_CONTROL_FINGERPRINT as _reviewed_launch_control_fingerprint,
    )
    from .intraday_spy_qqq_lead_lag_001_launch_control import (
        REVIEWED_LAUNCH_CONTROL_SHA256 as _reviewed_launch_control_sha256,
    )
except ImportError:
    REVIEWED_LAUNCH_CONTROL_SHA256 = None
    REVIEWED_LAUNCH_CONTROL_FINGERPRINT = None
else:
    REVIEWED_LAUNCH_CONTROL_SHA256 = _reviewed_launch_control_sha256
    REVIEWED_LAUNCH_CONTROL_FINGERPRINT = _reviewed_launch_control_fingerprint

RUNNER_VERSION = "intraday-spy-qqq-lead-lag-001-runner-v1"
RUN_SCHEMA = "intraday-spy-qqq-lead-lag-001-run-v1"
RUN_REPORT_SCHEMA = "intraday-spy-qqq-lead-lag-001-backtest-report-v1"
FINAL_FREEZE_SCHEMA = "intraday-spy-qqq-lead-lag-001-final-freeze-v1"
FINAL_REPORT_SCHEMA = "intraday-spy-qqq-lead-lag-001-final-report-v1"
PROGRAM_BINDING_SCHEMA = "intraday-spy-qqq-lead-lag-001-program-binding-v1"
DATABASE_NAME = "intraday-spy-qqq-lead-lag-001.sqlite3"
ENGINE_VERSION = "intraday-exposed-002-engine-v1"
STRATEGY_VERSION = "intraday-spy-qqq-fixed-leader-catchup-v1"
LAUNCH_CONTROL_RELATIVE_PATH = Path(
    "config/research/intraday-spy-qqq-lead-lag-001-launch-control-review-v1.json"
)
_LAUNCH_CONTROL_SCHEMA = "intraday-spy-qqq-lead-lag-001-launch-control-review-v1"
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
    "src/systematic_trading_lab/intraday_autonomous_research_program.py",
    "src/systematic_trading_lab/intraday_event_drift_001_plan.py",
    "src/systematic_trading_lab/intraday_event_drift_001_runner.py",
    "src/systematic_trading_lab/intraday_spy_qqq_lead_lag_001_plan.py",
    "src/systematic_trading_lab/intraday_spy_qqq_lead_lag_001_strategies.py",
    "src/systematic_trading_lab/intraday_spy_qqq_lead_lag_001_runner.py",
    "src/systematic_trading_lab/intraday_spy_qqq_lead_lag_001_cli.py",
    "src/systematic_trading_lab/intraday_event_prior_low_rejection_001_cli.py",
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
    "transition-trace-fingerprint",
    "fill-trace-fingerprint",
    "round-trip-fingerprint",
    "daily-fee-ledger-fingerprint",
    "metrics",
    "session-ledger",
    "canonical-report-bytes",
    "canonical-report-sha256",
    "report-fingerprint",
)
_LAUNCH_CONTROL_POST_REVIEW_FILES = frozenset(
    {
        LAUNCH_CONTROL_RELATIVE_PATH.as_posix(),
        "src/systematic_trading_lab/intraday_spy_qqq_lead_lag_001_launch_control.py",
        "tests/unit/test_intraday_spy_qqq_lead_lag_001_runner.py",
        "CURRENT_STATE.md",
        "DECISIONS.md",
        "ROADMAP.md",
        "docs/research-campaigns/intraday-spy-qqq-lead-lag-001-program.md",
        "docs/research-campaigns/intraday-autonomous-research-001-program.md",
        "docs/research-campaigns/intraday-autonomous-research-001-state.json",
        "docs/research-campaigns/intraday-autonomous-research-001-state-v2-revision-002.json",
    }
)
_STATUSES = ("pending", "running", "completed", "failed")
_LEASE_TIMEOUT = timedelta(seconds=300)
_HEARTBEAT_INTERVAL = timedelta(seconds=60)
_ACCOUNTING_FAILURE_PREFIX = "accounting-integrity: "
_ZERO = Decimal("0")
_BPS = Decimal("10000")
_QQQ, _SPY = Symbol("QQQ"), Symbol("SPY")
_NEW_YORK = ZoneInfo("America/New_York")
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
_EQUIVALENCE_PERIOD = LeadLagPeriod(
    "synthetic-equivalence-2026-01-08-through-09",
    datetime(2026, 1, 8, 14, 30, tzinfo=UTC),
    datetime(2026, 1, 8, 14, 30, tzinfo=UTC),
    datetime(2026, 1, 9, 20, 55, tzinfo=UTC),
    2,
)


class _CoordinatorValidationError(ValueError):
    def __init__(self, classification: str, run_ids: Sequence[str], cause: str) -> None:
        self.classification = classification
        self.run_ids = tuple(sorted(set(run_ids)))
        self.cause = cause
        super().__init__(cause)


def _require_non_broker_environment(environment: Mapping[str, str] | None = None) -> None:
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
            "SPY-QQQ Lead-Lag 001 rejects broker credentials and paper-write opt-in: "
            + ", ".join(forbidden)
        )


class IntradaySpyQqqLeadLag001Store:
    """Campaign names and budget over the common immutable attempt journal."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.attempts = ResearchAttemptStore(
            self.root,
            database_name=DATABASE_NAME,
            lease_timeout=_LEASE_TIMEOUT,
            reconcile_on_open=False,
            attempt_id_prefix="isqlll001a-",
        )
        self.path = self.attempts.path

    def bind(self, value: Mapping[str, object]) -> None:
        self.attempts.bind(value)

    def reserve(self, specifications: Sequence[Mapping[str, object]]) -> None:
        values = _deduplicate_specifications(specifications)
        existing = {str(row["run_id"]) for row in self.attempts.list_runs()}
        if len(existing | {_run_id(value) for value in values}) > 90:
            raise ValueError("SPY-QQQ Lead-Lag 001 run budget exceeds 90 specifications")
        for value in values:
            self.attempts.reserve(_run_id(value), value)

    def claim(self, run_id: str, *, source_sha: str) -> AttemptClaim:
        return self.attempts.claim(run_id, source_sha=source_sha, started_at=datetime.now(UTC))

    def publish(
        self, claim: AttemptClaim, path: Path, raw: bytes, *, report_fingerprint: str
    ) -> None:
        self.attempts.publish(
            claim,
            path,
            raw,
            report_fingerprint=report_fingerprint,
            finished_at=datetime.now(UTC),
            exit_status=0,
        )

    def fail(self, claim: AttemptClaim, *, failure_class: str, reason: str) -> None:
        stored_class = "candidate" if failure_class == "accounting" else failure_class
        stored_reason = (
            f"{_ACCOUNTING_FAILURE_PREFIX}{reason}" if failure_class == "accounting" else reason
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

    def get(self, run_id: str) -> dict[str, object]:
        row = self.attempts.get(run_id)
        specification = _mapping(row.get("specification"), "run specification")
        context = _mapping(specification.get("context"), "run context")
        report = row.get("canonical_report_path")
        relative = (
            None
            if not isinstance(report, Path)
            else report.resolve().relative_to(self.root).as_posix()
        )
        failure_class = row.get("failure_class")
        failure_reason = row.get("failure_reason")
        if (
            failure_class == "candidate"
            and isinstance(failure_reason, str)
            and failure_reason.startswith(_ACCOUNTING_FAILURE_PREFIX)
        ):
            failure_class = "accounting"
            failure_reason = failure_reason.removeprefix(_ACCOUNTING_FAILURE_PREFIX)
        return {
            **row,
            "reservation_id": _reservation_id(str(row["run_fingerprint"])),
            "candidate_id": _text(context, "candidate_id"),
            "period_id": _text(context, "period_id"),
            "scenario_id": _text(context, "scenario_id"),
            "report_path": relative,
            "report_sha256": row.get("canonical_report_sha256"),
            "report_fingerprint": row.get("canonical_report_fingerprint"),
            "failure_class": failure_class,
            "failure_reason": failure_reason,
        }

    def list_runs(self) -> tuple[dict[str, object], ...]:
        return tuple(self.get(str(row["run_id"])) for row in self.attempts.list_runs())

    def list_attempts(self, run_id: str) -> tuple[dict[str, object], ...]:
        return self.attempts.list_attempts(run_id)

    def expire_stale(self) -> tuple[str, ...]:
        return self.attempts.expire_stale(datetime.now(UTC))

    def reconcile_reports(self) -> tuple[Path, ...]:
        return self.attempts.reconcile_reports()


@dataclass(frozen=True)
class _WorkerFactory:
    repository: Path
    data_home: Path
    runtime_root: Path
    source_commit: str

    def __call__(self) -> _Worker:
        return _Worker(self.repository, self.data_home, self.runtime_root, self.source_commit)


class _Worker:
    def __init__(
        self, repository: Path, data_home: Path, runtime_root: Path, source_commit: str
    ) -> None:
        _require_non_broker_environment()
        self.repository, self.data_home, self.source_commit = (
            repository.resolve(),
            data_home.resolve(),
            source_commit,
        )
        self.plan = load_intraday_spy_qqq_lead_lag_001_plan(self.repository)
        self.base_plan = load_intraday_event_drift_001_plan(self.repository)
        self.cost_model = load_intraday_execution_cost_model(self.repository)
        self.datasets = _dataset_bindings(self.base_plan.payload)
        self.data_by_dataset = _read_only_dataset_services(self.data_home, self.datasets)
        IntradayExposed002Runner._verify_datasets(cast(Any, self), self.base_plan.payload)
        self.scenarios = _scenarios(self.cost_model)
        self._bar_cache: dict[str, tuple[Any, ...]] = {}
        self.attempt_store = IntradaySpyQqqLeadLag001Store(runtime_root)

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
                failure_class = "data"
                bars = IntradayExposed002Runner._bars(
                    cast(Any, self), cast(Any, period), self.base_plan.payload
                )
                _validate_campaign_bars(bars)
                failure_class = "candidate"
                result = IntradayExposed002Engine(
                    Decimal(str(self.base_plan.payload["execution"]["initial_cash"])),
                    scenario,
                    self.cost_model.regulatory_fees,
                ).run(
                    bars,
                    build_intraday_spy_qqq_lead_lag_001_strategy(
                        configuration, period.evaluation_start
                    ),
                )
                failure_class = "accounting"
                report = _run_report(specification, result, period, bars, configuration)
                raw = (canonical_json(report) + "\n").encode()
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
            raw,
            report_fingerprint=_text(report, "report_fingerprint"),
        )
        return (
            f"{context['candidate_id']} {context['period_id']} "
            f"{context['scenario_id']} attempt-{claim.attempt_number}"
        )

    def _configuration(self, candidate_id: str) -> LeadLagConfiguration:
        for item in self.plan.configurations:
            if item.candidate_id == candidate_id:
                return item
        raise ValueError(f"unknown SPY-QQQ Lead-Lag 001 candidate: {candidate_id}")

    def _period(self, period_id: str) -> LeadLagPeriod:
        for item in self.plan.periods:
            if item.period_id == period_id:
                return item
        raise ValueError(f"unknown SPY-QQQ Lead-Lag 001 period: {period_id}")


class IntradaySpyQqqLeadLag001Runner:
    """Coordinate the frozen 18 + 24 + 16 + 32 maximum run graph."""

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
        if REVIEWED_LAUNCH_CONTROL_SHA256 is None or REVIEWED_LAUNCH_CONTROL_FINGERPRINT is None:
            raise ValueError("SPY-QQQ Lead-Lag 001 launch control is not hash-bound")
        self.repository, self.data_home, self.workers = (
            repository.resolve(),
            data_home.resolve(),
            workers,
        )
        self.source_commit, self.progress = (
            _source_commit(self.repository),
            progress or (lambda _message: None),
        )
        self.launch_control = _load_launch_control(
            self.repository, source_commit=self.source_commit
        )
        self.plan = load_intraday_spy_qqq_lead_lag_001_plan(self.repository)
        self.base_plan = load_intraday_event_drift_001_plan(self.repository)
        self.cost_model = load_intraday_execution_cost_model(self.repository)
        self.datasets = _dataset_bindings(self.base_plan.payload)
        self.data_by_dataset = (
            {item.dataset_id: data_service for item in self.datasets}
            if data_service
            else _read_only_dataset_services(self.data_home, self.datasets)
        )
        IntradayExposed002Runner._verify_datasets(cast(Any, self), self.base_plan.payload)
        self.scenarios = _scenarios(self.cost_model)
        self.runtime_root = self.data_home / PROGRAM_ID
        self.attempt_store = IntradaySpyQqqLeadLag001Store(self.runtime_root)
        self.attempt_store.bind(self._program_binding())

    def _program_binding(self) -> dict[str, object]:
        return {
            "schema_version": PROGRAM_BINDING_SCHEMA,
            "program_id": PROGRAM_ID,
            "runner_version": RUNNER_VERSION,
            "engine_version": ENGINE_VERSION,
            "strategy_version": STRATEGY_VERSION,
            "source_commit": self.source_commit,
            "plan": {
                "sha256": self.plan.sha256,
                "fingerprint": self.plan.plan_fingerprint,
                "review_sha256": self.plan.review_sha256,
                "review_fingerprint": self.plan.review_fingerprint,
                "state_sha256": self.plan.state_sha256,
                "state_fingerprint": self.plan.state_fingerprint,
            },
            "cost_model": {
                "model_id": self.cost_model.payload["cost_model_id"],
                "sha256": self.cost_model.sha256,
                "fingerprint": self.cost_model.model_fingerprint,
            },
            "datasets": [canonicalize(item) for item in self.datasets],
            "run_identity_fields": ["candidate_id", "period_id", "scenario_id"],
            "maximum_run_specifications": 90,
            "maximum_attempts": 270,
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

    def _specification(
        self, configuration: LeadLagConfiguration, period: LeadLagPeriod, scenario_id: str
    ) -> dict[str, object]:
        scenario = self.scenarios[scenario_id]
        return cast(
            dict[str, object],
            canonicalize(
                {
                    "schema_version": RUN_SCHEMA,
                    "program_id": PROGRAM_ID,
                    "runner_version": RUNNER_VERSION,
                    "engine_version": ENGINE_VERSION,
                    "strategy_version": STRATEGY_VERSION,
                    "source_commit": self.source_commit,
                    "plan_sha256": self.plan.sha256,
                    "plan_fingerprint": self.plan.plan_fingerprint,
                    "autonomous_program_sha256": self.plan.payload["autonomous_program"]["sha256"],
                    "autonomous_program_fingerprint": self.plan.payload["autonomous_program"][
                        "fingerprint"
                    ],
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
                    "dataset_inputs": _run_dataset_inputs(self.datasets, cast(Any, period)),
                    "execution": self.base_plan.payload["execution"],
                    "context": {
                        "candidate_id": configuration.candidate_id,
                        "period_id": period.period_id,
                        "scenario_id": scenario_id,
                    },
                    "authority": _AUTHORITY,
                }
            ),
        )

    def _execute(self, specifications: Sequence[Mapping[str, object]]) -> None:
        values = _deduplicate_specifications(specifications)
        if not values:
            return
        factory = _WorkerFactory(
            self.repository, self.data_home, self.runtime_root, self.source_commit
        )
        preflight_process_stage(values, worker_factory=factory)
        self.attempt_store.reserve(values)
        pending = []
        for value in values:
            row = self.attempt_store.get(_run_id(value))
            if row["status"] == "pending":
                pending.append(value)
            elif row["status"] != "completed":
                raise AttemptStateError(
                    f"SPY-QQQ Lead-Lag 001 run is not reusable: {row['run_id']}"
                )
        if pending:
            run_process_stage(
                tuple(pending),
                worker_factory=factory,
                workers=self.workers,
                progress=lambda done, total, _task, result: self.progress(
                    f"{done}/{total} {result}"
                ),
            )
        for value in values:
            self._load_report(self.attempt_store.get(_run_id(value)))

    def _load_report(self, row: Mapping[str, object]) -> Mapping[str, Any]:
        if row.get("status") != "completed":
            raise ValueError("SPY-QQQ Lead-Lag 001 run is not completed")
        relative = Path(cast(str, row["report_path"]))
        raw = (self.runtime_root / relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row.get("report_sha256"):
            raise ValueError("SPY-QQQ Lead-Lag 001 report SHA-256 differs")
        report = _mapping(json.loads(raw), "run report")
        unsigned = dict(report)
        stored = unsigned.pop("report_fingerprint", None)
        specification = _mapping(report.get("specification"), "specification")
        context = _mapping(specification.get("context"), "context")
        if (
            set(context) != {"candidate_id", "period_id", "scenario_id"}
            or report.get("run_id") != _run_id(specification)
            or report.get("specification_fingerprint") != fingerprint(specification)
            or stored != row.get("report_fingerprint")
            or fingerprint(unsigned) != stored
        ):
            raise ValueError("SPY-QQQ Lead-Lag 001 report identity differs")
        return report

    def _report_for(self, candidate_id: str, period_id: str, scenario_id: str) -> Mapping[str, Any]:
        matches = tuple(
            row
            for row in self.attempt_store.list_runs()
            if row["candidate_id"] == candidate_id
            and row["period_id"] == period_id
            and row["scenario_id"] == scenario_id
        )
        if len(matches) != 1:
            raise ValueError("SPY-QQQ Lead-Lag 001 canonical run relationship differs")
        return self._load_report(matches[0])

    def _normal_zero(
        self, candidate_id: str, period_id: str
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        normal, zero = (
            self._report_for(candidate_id, period_id, "normal"),
            self._report_for(candidate_id, period_id, "zero_cost_diagnostic"),
        )
        if normal["lead_signal_trace_fingerprint"] != zero["lead_signal_trace_fingerprint"]:
            raise _CoordinatorValidationError(
                "cross-scenario-signal-validation",
                (_text(normal, "run_id"), _text(zero, "run_id")),
                "ValueError: SPY-QQQ Lead-Lag 001 paired signal trace differs",
            )
        return normal, zero

    def _require_no_failures(self) -> None:
        failed = tuple(row for row in self.attempt_store.list_runs() if row["status"] == "failed")
        if failed:
            raise AttemptStateError(
                f"SPY-QQQ Lead-Lag 001 has {len(failed)} terminal failed run(s); no retry is "
                "allowed"
            )

    def _run_discovery(self) -> dict[str, object]:
        period = self.plan.periods[0]
        self._execute(
            tuple(
                self._specification(item, period, scenario)
                for item in self.plan.configurations
                for scenario in ("normal", "zero_cost_diagnostic")
            )
        )
        ledger: list[dict[str, object]] = []
        for item in self.plan.configurations:
            normal, zero = self._normal_zero(item.candidate_id, period.period_id)
            values = _pair_values(normal, zero, "normal", "zero_cost_diagnostic")
            gates = _gate_results(
                _gates(canonicalize(self.plan.payload), "discovery_screen", "gates"), values
            )
            ledger.append(
                {
                    "candidate": _configuration_summary(item),
                    "metrics": values,
                    "gates": gates,
                    "eligible": all(cast(bool, gate["passed"]) for gate in gates),
                }
            )
        chosen = tuple(
            _text(cast(Mapping[str, Any], item["candidate"]), "candidate_id")
            for item in sorted(
                (item for item in ledger if item["eligible"]),
                key=lambda item: (
                    -_ledger_metric(item, "normal.total_return"),
                    _ledger_metric(item, "normal.positive_profit_session_concentration"),
                    _ledger_metric(item, "normal.cost_to_gross_profit"),
                    _text(cast(Mapping[str, Any], item["candidate"]), "candidate_id"),
                ),
            )[:3]
        )
        return {"ledger": ledger, "selected": chosen}

    def _run_walk_forward(self, discovery: Mapping[str, object]) -> dict[str, object]:
        candidates = cast(tuple[str, ...], discovery["selected"])
        periods = self.plan.periods[1:]
        self._execute(
            tuple(
                self._specification(self._configuration(candidate), period, scenario)
                for candidate in candidates
                for period in periods
                for scenario in ("normal", "zero_cost_diagnostic")
            )
        )
        ledger: list[dict[str, object]] = []
        for candidate in candidates:
            normals, zeros = zip(
                *(self._normal_zero(candidate, period.period_id) for period in periods), strict=True
            )
            normal_aggregate, zero_aggregate = (
                _aggregate_lead_lag_reports(normals),
                _aggregate_lead_lag_reports(zeros),
            )
            positive = tuple(report for report in normals if _positive_fold(report))
            values = _walk_values(normals, normal_aggregate, zero_aggregate, positive)
            gates = _gate_results(
                _gates(canonicalize(self.plan.payload), "walk_forward_screen", "gates"), values
            )
            ledger.append(
                {
                    "candidate": _configuration_summary(self._configuration(candidate)),
                    "metrics": values,
                    "gates": gates,
                    "eligible": all(cast(bool, gate["passed"]) for gate in gates),
                }
            )
        chosen = tuple(
            _text(cast(Mapping[str, Any], item["candidate"]), "candidate_id")
            for item in sorted(
                (item for item in ledger if item["eligible"]),
                key=lambda item: (
                    -_ledger_metric(item, "positive_normal_fold_count"),
                    -_ledger_metric(item, "aggregate.normal.total_return"),
                    _ledger_metric(item, "aggregate.normal.positive_profit_session_concentration"),
                    _text(cast(Mapping[str, Any], item["candidate"]), "candidate_id"),
                ),
            )[:1]
        )
        return {"ledger": ledger, "selected": chosen}

    def _run_serious(self, walk: Mapping[str, object]) -> dict[str, object]:
        candidates = cast(tuple[str, ...], walk["selected"])
        periods = self.plan.periods[1:]
        scenarios = ("stress_a", "stress_b", "normal-delay-2", "normal-delay-3")
        self._execute(
            tuple(
                self._specification(self._configuration(candidate), period, scenario)
                for candidate in candidates
                for period in periods
                for scenario in scenarios
            )
        )
        ledger: list[dict[str, object]] = []
        for candidate in candidates:
            normal = _aggregate_lead_lag_reports(
                tuple(self._report_for(candidate, period.period_id, "normal") for period in periods)
            )
            values: dict[str, Decimal | int | None] = {}
            for scenario in scenarios:
                reports = tuple(
                    self._report_for(candidate, period.period_id, scenario) for period in periods
                )
                for report, period in zip(reports, periods, strict=True):
                    if (
                        report["lead_signal_trace_fingerprint"]
                        != self._report_for(candidate, period.period_id, "normal")[
                            "lead_signal_trace_fingerprint"
                        ]
                    ):
                        raise _CoordinatorValidationError(
                            "cross-scenario-signal-validation",
                            (
                                _text(report, "run_id"),
                                _text(
                                    self._report_for(candidate, period.period_id, "normal"),
                                    "run_id",
                                ),
                            ),
                            "ValueError: SPY-QQQ Lead-Lag 001 stress signal trace differs",
                        )
                aggregate = _aggregate_lead_lag_reports(reports)
                values[f"{scenario}.aggregate_total_return"] = Decimal(
                    cast(Any, aggregate)["total_return"]
                )
                values[f"{scenario}.positive_fold_count"] = sum(
                    _positive_fold(report) for report in reports
                )
                values[f"{scenario}.normal_profit_retention"] = (
                    Decimal(cast(Any, aggregate)["net_profit_loss"])
                    / Decimal(cast(Any, normal)["net_profit_loss"])
                    if Decimal(cast(Any, normal)["net_profit_loss"]) > 0
                    else None
                )
            gates = _gate_results(
                _gates(
                    canonicalize(self.plan.payload),
                    "serious_candidate_screen",
                    "stress_gates",
                ),
                values,
            )
            ledger.append(
                {
                    "candidate": _configuration_summary(self._configuration(candidate)),
                    "metrics": values,
                    "gates": gates,
                    "eligible": all(cast(bool, gate["passed"]) for gate in gates),
                }
            )
        return {
            "ledger": ledger,
            "selected": tuple(
                _text(cast(Mapping[str, Any], item["candidate"]), "candidate_id")
                for item in ledger
                if item["eligible"]
            ),
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
                walk = self._run_walk_forward(discovery)
                serious = self._run_serious(walk)
                neighbors = self._run_neighbors(serious)
                cohort = cast(tuple[str, ...], neighbors["selected"])
                freeze = self._freeze(discovery, walk, serious, neighbors, cohort)
                final = self._final_report(discovery, walk, serious, neighbors, cohort, freeze)
            except _CoordinatorValidationError as error:
                rows = self.attempt_store.list_runs()
                if any(row["status"] == "running" for row in rows):
                    raise
                failed = tuple(row for row in rows if row["status"] == "failed")
                final = self._terminal_interruption_report(failed, coordinator_failure=error)
            except Exception as error:
                rows = self.attempt_store.list_runs()
                failed = tuple(row for row in rows if row["status"] == "failed")
                if any(row["status"] == "running" for row in rows):
                    raise
                if failed:
                    final = self._terminal_interruption_report(failed)
                elif isinstance(error, ValueError | FileExistsError):
                    final = self._terminal_interruption_report(
                        (),
                        coordinator_failure=_CoordinatorValidationError(
                            "coordinator-validation",
                            tuple(str(row["run_id"]) for row in rows),
                            f"{type(error).__name__}: {error}",
                        ),
                    )
                else:
                    raise
            return self._result(final)

    def _run_neighbors(self, serious: Mapping[str, object]) -> dict[str, object]:
        candidates = cast(tuple[str, ...], serious["selected"])
        if not candidates:
            return {
                "stage": "immediate-neighbor",
                "candidate_count": 0,
                "requested_run_specification_count": 0,
                "new_run_specification_count": 0,
                "ledger": [],
                "selected": (),
            }
        candidate = candidates[0]
        configuration = self._configuration(candidate)
        periods = self.plan.periods[1:]
        neighbors = tuple(configuration.neighbor_ids)
        specifications = _deduplicate_specifications(
            tuple(
                self._specification(self._configuration(neighbor), period, scenario)
                for neighbor in neighbors
                for period in periods
                for scenario in ("normal", "zero_cost_diagnostic")
            )
        )
        existing = {str(row["run_id"]) for row in self.attempt_store.list_runs()}
        new_count = sum(_run_id(value) not in existing for value in specifications)
        if new_count > 32:
            raise _CoordinatorValidationError(
                "search-budget",
                tuple(_run_id(value) for value in specifications),
                "ValueError: SPY-QQQ Lead-Lag 001 neighbor budget differs",
            )
        self._execute(specifications)
        base_normal = _aggregate_lead_lag_reports(
            tuple(self._report_for(candidate, period.period_id, "normal") for period in periods)
        )
        joint, retentions, mismatch = 0, [], 0
        for neighbor in neighbors:
            normals, zeros = zip(
                *(self._normal_zero(neighbor, period.period_id) for period in periods), strict=True
            )
            normal, zero = _aggregate_lead_lag_reports(normals), _aggregate_lead_lag_reports(zeros)
            joint += (
                Decimal(cast(Any, normal)["total_return"]) > 0
                and Decimal(cast(Any, normal)["net_profit_loss"]) > 0
                and Decimal(cast(Any, zero)["total_return"]) > 0
                and Decimal(cast(Any, zero)["net_profit_loss"]) > 0
            )
            if Decimal(cast(Any, base_normal)["net_profit_loss"]) > 0:
                retentions.append(
                    Decimal(cast(Any, normal)["net_profit_loss"])
                    / Decimal(cast(Any, base_normal)["net_profit_loss"])
                )
            mismatch += int(cast(Any, normal)["signal_trace_mismatch_count"])
        values = {
            "joint_positive_neighbor_fraction": Decimal(joint) / Decimal(len(neighbors)),
            "median_neighbor_normal_profit_retention": median(retentions) if retentions else None,
            "neighbor_signal_trace_mismatch_count": mismatch,
        }
        gates = _gate_results(
            _gates(
                canonicalize(self.plan.payload),
                "serious_candidate_screen",
                "neighbor_gates",
            ),
            values,
        )
        eligible = all(gate["passed"] for gate in gates)
        return {
            "stage": "immediate-neighbor",
            "candidate_count": 1,
            "requested_run_specification_count": len(specifications),
            "new_run_specification_count": new_count,
            "ledger": [
                {
                    "candidate": _configuration_summary(configuration),
                    "neighbor_ids": neighbors,
                    "metrics": values,
                    "gates": gates,
                    "eligible": eligible,
                }
            ],
            "selected": (candidate,) if eligible else (),
        }

    def _configuration(self, candidate_id: str) -> LeadLagConfiguration:
        for item in self.plan.configurations:
            if item.candidate_id == candidate_id:
                return item
        raise ValueError(f"unknown SPY-QQQ Lead-Lag 001 candidate: {candidate_id}")

    def _freeze(
        self,
        discovery: Mapping[str, object],
        walk: Mapping[str, object],
        serious: Mapping[str, object],
        neighbors: Mapping[str, object],
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
        summary = _attempt_summary(runs, histories)
        total_attempts = summary.get("total_attempts")
        if (
            isinstance(total_attempts, bool)
            or not isinstance(total_attempts, int)
            or len(runs) > 90
            or total_attempts > 270
        ):
            raise ValueError("SPY-QQQ Lead-Lag 001 frozen search budget exceeded")
        if any(row["status"] != "completed" for row in runs):
            raise ValueError("SPY-QQQ Lead-Lag 001 freeze requires completed runs")
        payload: dict[str, object] = {
            "schema_version": FINAL_FREEZE_SCHEMA,
            "program_id": PROGRAM_ID,
            "status": "frozen-after-complete-exposed-screening",
            "source_commit": self.source_commit,
            "runner_version": RUNNER_VERSION,
            "engine_version": ENGINE_VERSION,
            "strategy_version": STRATEGY_VERSION,
            "plan": {
                "sha256": self.plan.sha256,
                "fingerprint": self.plan.plan_fingerprint,
                "review_sha256": self.plan.review_sha256,
                "review_fingerprint": self.plan.review_fingerprint,
                "state_sha256": self.plan.state_sha256,
                "state_fingerprint": self.plan.state_fingerprint,
            },
            "launch_control": self.launch_control,
            "cost_model": {
                "sha256": self.cost_model.sha256,
                "fingerprint": self.cost_model.model_fingerprint,
            },
            "datasets": [canonicalize(item) for item in self.datasets],
            "screened_ledger": {
                "discovery": discovery,
                "walk_forward": walk,
                "stress": serious,
                "neighbors": neighbors,
            },
            "cohort": [
                _configuration_summary(self._configuration(candidate)) for candidate in cohort
            ],
            "cohort_size": len(cohort),
            "all_runtime_runs": [_run_evidence(row) for row in runs],
            "attempt_summary": summary,
            "attempt_histories": histories,
            "controlled_boundary": {
                "range_status": "none-eligible",
                "june_read": False,
                "substitute_range": False,
                "controlled_evaluation_performed": False,
                "terminal_action": (
                    "close-empty-cohort-and-advance-under-frozen-program"
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
        walk: Mapping[str, object],
        serious: Mapping[str, object],
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
                else "exposed-serious-candidate-waiting-for-future-untouched-data"
            ),
            "terminal_message": (
                "INTRADAY SPY-QQQ LEAD-LAG 001 COMPLETE — NO CONTROLLED-QUALIFIED CANDIDATE"
                if empty
                else "INTRADAY SPY-QQQ LEAD-LAG 001 COMPLETE — WAITING FOR FUTURE UNTOUCHED DATA"
            ),
            "source_commit": self.source_commit,
            "plan_sha256": self.plan.sha256,
            "plan_fingerprint": self.plan.plan_fingerprint,
            "launch_control": {
                "path": LAUNCH_CONTROL_RELATIVE_PATH.as_posix(),
                "sha256": REVIEWED_LAUNCH_CONTROL_SHA256,
                "fingerprint": REVIEWED_LAUNCH_CONTROL_FINGERPRINT,
            },
            "complete_exposed_screening": True,
            "counts": {
                "discovery_parents": len(self.plan.configurations),
                "discovery_run_specifications": 18,
                "walk_forward_candidates": len(cast(tuple[str, ...], discovery["selected"])),
                "walk_forward_run_specifications": len(cast(tuple[str, ...], discovery["selected"]))
                * 8,
                "serious_candidates": len(cast(tuple[str, ...], walk["selected"])),
                "stress_run_specifications": len(cast(tuple[str, ...], walk["selected"])) * 16,
                "neighbor_new_run_specifications": neighbors["new_run_specification_count"],
                "total_run_specifications": len(self.attempt_store.list_runs()),
                "cohort": len(cohort),
            },
            "cohort": [
                _configuration_summary(self._configuration(candidate)) for candidate in cohort
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
            "terminal_message": "INTRADAY SPY-QQQ LEAD-LAG 001 TERMINALLY INTERRUPTED",
            "source_commit": self.source_commit,
            "plan_sha256": self.plan.sha256,
            "plan_fingerprint": self.plan.plan_fingerprint,
            "launch_control": {
                "path": LAUNCH_CONTROL_RELATIVE_PATH.as_posix(),
                "sha256": REVIEWED_LAUNCH_CONTROL_SHA256,
                "fingerprint": REVIEWED_LAUNCH_CONTROL_FINGERPRINT,
            },
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
        path = self.runtime_root / "final-report.json"
        _write_create_only(path, payload)
        _write_create_only_text(
            self.runtime_root / "final-report.md",
            _final_markdown(payload, _sha256_path(path)),
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


def _configuration_summary(configuration: LeadLagConfiguration) -> dict[str, object]:
    return {
        "candidate_id": configuration.candidate_id,
        "strategy_id": STRATEGY_VERSION,
        "observation_horizon_bars": configuration.observation_horizon_bars,
        "minimum_spy_impulse_bps": configuration.minimum_spy_impulse_bps,
        "qqq_target_weight": Decimal("0.5"),
        "hold_bars": 24,
        "neighbor_ids": configuration.neighbor_ids,
    }


def _run_id(specification: Mapping[str, object]) -> str:
    context = _mapping(specification.get("context"), "run context")
    if set(context) != {"candidate_id", "period_id", "scenario_id"}:
        raise ValueError("SPY-QQQ Lead-Lag 001 canonical run context differs")
    identity = {key: context[key] for key in ("candidate_id", "period_id", "scenario_id")}
    return f"isqlll001r-{fingerprint(identity)[:24]}"


def _reservation_id(run_fingerprint: str) -> str:
    return f"isqlll001q-{run_fingerprint[:24]}"


def _run_evidence(row: Mapping[str, object]) -> dict[str, object]:
    return {
        key: row[key]
        for key in (
            "run_id",
            "reservation_id",
            "run_fingerprint",
            "candidate_id",
            "period_id",
            "scenario_id",
            "status",
            "attempt_count",
            "report_path",
            "report_sha256",
            "report_fingerprint",
            "failure_class",
            "failure_reason",
        )
    }


def _attempt_summary(
    runs: Sequence[Mapping[str, object]],
    histories: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    summary = _base_attempt_summary(runs, histories)
    summary["accounting_failure_count"] = sum(
        row.get("failure_class") == "accounting" for row in runs
    )
    return summary


def _protected_access() -> dict[str, bool]:
    return {
        "june_market_data_or_results": False,
        "intraday_v3_data_or_results": False,
        "daily_2018_2019_data_or_results": False,
        "paper_broker_or_live_state": False,
        "strategic_allocation_21": False,
    }


def _deduplicate_specifications(
    specifications: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    by_id: dict[str, Mapping[str, object]] = {}
    for specification in specifications:
        run_id = _run_id(specification)
        previous = by_id.get(run_id)
        if previous is not None and canonical_json(previous) != canonical_json(specification):
            raise ValueError("SPY-QQQ Lead-Lag 001 canonical run identity collides")
        by_id[run_id] = specification
    return tuple(by_id[key] for key in sorted(by_id))


def _validate_campaign_bars(bars: Sequence[OHLCVBar]) -> None:
    if not bars:
        raise ValueError("SPY-QQQ Lead-Lag 001 data contains no bars")
    by_symbol = {
        symbol: tuple(sorted(bar.timestamp for bar in bars if bar.symbol == symbol))
        for symbol in (_QQQ, _SPY)
    }
    if len(bars) != sum(len(value) for value in by_symbol.values()):
        raise ValueError("SPY-QQQ Lead-Lag 001 data contains an unexpected symbol")
    if any(len(value) != len(set(value)) for value in by_symbol.values()):
        raise ValueError("SPY-QQQ Lead-Lag 001 data contains duplicate bars")
    expected = expected_bar_timestamps(
        min(bar.timestamp for bar in bars),
        max(bar.timestamp for bar in bars),
        Timeframe.FIVE_MINUTES,
    )
    if not expected or any(value != expected for value in by_symbol.values()):
        raise ValueError("SPY-QQQ Lead-Lag 001 data differs from exact XNYS sessions")


def _final_markdown(report: Mapping[str, Any], report_sha256: str) -> str:
    counts = _mapping(report.get("counts"), "final counts")
    protected = _mapping(report.get("protected_access"), "protected access")
    lines = [
        "# Intraday SPY-QQQ Lead-Lag 001 final report",
        "",
        f"Outcome: `{report['outcome']}`",
        f"Source commit: `{report['source_commit']}`",
        f"Final report SHA-256: `{report_sha256}`",
        f"Total run specifications: `{counts.get('total_run_specifications')}`",
        f"Cohort size: `{counts.get('cohort')}`",
        "",
        "Protected access:",
        "",
    ]
    lines.extend(f"- `{key}`: `{value}`" for key, value in protected.items())
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
    launch = _mapping(value.get("launch_control"), "final launch control")
    terminal = value.get("final_freeze") is None
    expected_keys = {
        "schema_version",
        "program_id",
        "outcome",
        "terminal_message",
        "source_commit",
        "plan_sha256",
        "plan_fingerprint",
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
    if terminal:
        expected_keys.update({"terminal_failures", "coordinator_failure", "attempt_histories"})
    counts = _mapping(value.get("counts"), "final counts")
    cohort = value.get("cohort")
    controlled = _mapping(value.get("controlled_evaluation"), "controlled evaluation")
    if not isinstance(cohort, list):
        raise ValueError("SPY-QQQ Lead-Lag 001 final cohort differs")
    if (
        set(value) != expected_keys
        or value.get("schema_version") != FINAL_REPORT_SCHEMA
        or value.get("program_id") != PROGRAM_ID
        or (source_commit is not None and value.get("source_commit") != source_commit)
        or value.get("plan_sha256") != PLAN_SHA256
        or value.get("plan_fingerprint") != PLAN_FINGERPRINT
        or launch
        != {
            "path": LAUNCH_CONTROL_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_LAUNCH_CONTROL_SHA256,
            "fingerprint": REVIEWED_LAUNCH_CONTROL_FINGERPRINT,
        }
        or value.get("protected_access") != _protected_access()
        or value.get("authority") != _AUTHORITY
        or set(controlled) != {"performed", "reason", "controlled_qualified_claim"}
        or controlled.get("performed") is not False
        or controlled.get("controlled_qualified_claim") is not False
        or not isinstance(controlled.get("reason"), str)
        or not controlled["reason"]
        or counts.get("cohort") != (None if terminal else len(cohort))
        or (
            terminal
            and (
                value.get("outcome") != "terminally-interrupted"
                or value.get("complete_exposed_screening") is not False
                or cohort != []
            )
        )
        or (
            not terminal
            and (
                value.get("complete_exposed_screening") is not True
                or value.get("outcome")
                != (
                    "no-controlled-qualified-candidate"
                    if not cohort
                    else "exposed-serious-candidate-waiting-for-future-untouched-data"
                )
            )
        )
        or fingerprint(unsigned) != stored
    ):
        raise ValueError("SPY-QQQ Lead-Lag 001 final report differs")
    return value


def _validate_final_evidence(runtime: Path, report: Mapping[str, Any]) -> None:
    database = _mapping(report.get("runtime_database"), "runtime database")
    if database.get("path") != DATABASE_NAME or database.get("sha256") != _sha256_path(
        runtime / DATABASE_NAME
    ):
        raise ValueError("SPY-QQQ Lead-Lag 001 runtime database differs")
    freeze_evidence = report.get("final_freeze")
    if freeze_evidence is None:
        return
    evidence = _mapping(freeze_evidence, "final freeze evidence")
    relative = _required_text(evidence.get("path"), "freeze path")
    if relative != "final-freeze.json":
        raise ValueError("SPY-QQQ Lead-Lag 001 final freeze path differs")
    path = runtime / relative
    freeze = _mapping(json.loads(path.read_bytes()), "final freeze")
    stored = _text(freeze, "freeze_fingerprint")
    unsigned = dict(freeze)
    del unsigned["freeze_fingerprint"]
    launch = _mapping(freeze.get("launch_control"), "freeze launch control")
    plan = _mapping(freeze.get("plan"), "freeze plan")
    boundary = _mapping(freeze.get("controlled_boundary"), "controlled boundary")
    screened = _mapping(freeze.get("screened_ledger"), "screened ledger")
    cohort = freeze.get("cohort")
    final_cohort = report.get("cohort")
    all_runs = freeze.get("all_runtime_runs")
    histories = freeze.get("attempt_histories")
    if (
        evidence.get("sha256") != _sha256_path(path)
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
        or plan
        != {
            "sha256": PLAN_SHA256,
            "fingerprint": PLAN_FINGERPRINT,
            "review_sha256": REVIEW_SHA256,
            "review_fingerprint": REVIEW_FINGERPRINT,
            "state_sha256": STATE_SHA256,
            "state_fingerprint": STATE_FINGERPRINT,
        }
        or launch.get("review_fingerprint") != REVIEWED_LAUNCH_CONTROL_FINGERPRINT
        or launch.get("status") != "passed"
        or launch.get("verdict") != "pass"
        or set(screened) != {"discovery", "walk_forward", "stress", "neighbors"}
        or not isinstance(cohort, list)
        or cohort != final_cohort
        or freeze.get("cohort_size") != len(cohort)
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
        raise ValueError("SPY-QQQ Lead-Lag 001 final freeze differs")


def _run_report(
    specification: Mapping[str, object],
    result: Exposed002ReplayResult,
    period: LeadLagPeriod,
    bars: Sequence[OHLCVBar],
    configuration: LeadLagConfiguration,
) -> dict[str, object]:
    """Add Campaign 1's one-row-per-ordinary-session evidence to engine accounting."""
    payload = _source_run_report(specification, result, cast(Any, period))
    payload.pop("report_fingerprint")
    metrics, details = (
        dict(_mapping(payload["metrics"], "metrics")),
        dict(_mapping(payload["details"], "details")),
    )
    sessions = tuple(expected_sessions(period.evaluation_start, period.evaluation_end))
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
    evaluation_fees = tuple(
        item for item in result.fee_ledger if date.fromisoformat(item.account_day) in sessions
    )
    fees = {date.fromisoformat(item.account_day): item for item in evaluation_fees}
    if len(evaluation_fees) != len(sessions) or set(fees) != set(sessions):
        raise ValueError("SPY-QQQ Lead-Lag 001 requires one daily fee ledger per session")
    ledger, signal_trace = [], []
    for day in sessions:
        qqq = tuple(
            sorted(
                (bar for bar in bars if bar.symbol == _QQQ and _account_day(bar.timestamp) == day),
                key=lambda bar: bar.timestamp,
            )
        )
        spy = tuple(
            sorted(
                (bar for bar in bars if bar.symbol == _SPY and _account_day(bar.timestamp) == day),
                key=lambda bar: bar.timestamp,
            )
        )
        row, trace = _session_row(
            day,
            qqq,
            spy,
            configuration,
            evaluation_fills,
            evaluation_trades,
            fees.get(day),
            int(_mapping(specification["cost_model"], "cost model")["execution_delay_bars"]),
        )
        ledger.append(row)
        signal_trace.append(trace)
    if len(ledger) != period.session_count:
        raise ValueError("SPY-QQQ Lead-Lag 001 session count differs")
    net = sum((Decimal(str(row["net_profit_loss"])) for row in ledger), _ZERO)
    gross = sum((Decimal(str(row["gross_profit_loss"])) for row in ledger), _ZERO)
    friction = sum((Decimal(str(row["execution_friction"])) for row in ledger), _ZERO)
    if (
        abs(net - Decimal(str(metrics["net_profit_loss"]))).quantize(_ACCOUNTING_PRECISION) != _ZERO
        or abs(gross - friction - net).quantize(_ACCOUNTING_PRECISION) != _ZERO
    ):
        raise ValueError("SPY-QQQ Lead-Lag 001 session accounting does not reconcile")
    buckets = {
        bucket: sum(
            (
                Decimal(str(row["net_profit_loss"]))
                for row in ledger
                if row["under_response_bucket"] == bucket
            ),
            _ZERO,
        )
        for bucket in (
            "under-response-0-to-1-6",
            "under-response-1-6-to-1-3",
            "under-response-1-3-to-1-2",
        )
    }
    active = sum(row["disposition"] == "active" for row in ledger)
    if int(metrics["completed_round_trips"]) != active or int(metrics["fill_count"]) != active * 2:
        raise ValueError("SPY-QQQ Lead-Lag 001 session execution does not reconcile")
    metrics.update(
        {
            "signal_eligible_session_count": sum(
                cast(bool, row["signal_eligible"]) for row in ledger
            ),
            "hold_capacity_ineligible_session_count": sum(
                row["disposition"] == "hold-capacity-ineligible" for row in ledger
            ),
            "active_session_count": active,
            "session_disposition_counts": {
                code: sum(row["disposition"] == code for row in ledger)
                for code in (
                    "active",
                    "inactive-spy-below-floor",
                    "inactive-qqq-negative",
                    "inactive-qqq-over-response",
                    "hold-capacity-ineligible",
                )
            },
            "positive_profit_session_concentration": _positive_concentration(
                tuple(Decimal(str(row["net_profit_loss"])) for row in ledger)
            ),
            "positive_profit_period_concentration": _positive_concentration((net,)),
            "signal_bucket_net_profit_loss": buckets,
            "positive_profit_signal_bucket_concentration": _positive_concentration(
                tuple(buckets.values())
            ),
            "signal_trace_mismatch_count": 0,
            "symbol_concentration_disposition": "not-applicable-by-design",
        }
    )
    details.update({"session_ledger": ledger, "lead_signal_trace": signal_trace})
    payload.update(
        {
            "schema_version": RUN_REPORT_SCHEMA,
            "program_id": PROGRAM_ID,
            "run_id": _run_id(specification),
            "metrics": metrics,
            "details": details,
            "lead_signal_trace_fingerprint": fingerprint(signal_trace),
            "execution_evidence": {
                key: details[key]
                for key in (
                    "decision_trace_fingerprint",
                    "transition_trace_fingerprint",
                    "fill_trace_fingerprint",
                    "round_trip_fingerprint",
                    "daily_fee_ledger_fingerprint",
                )
            },
            "source_commit": specification["source_commit"],
            "authority": _AUTHORITY,
        }
    )
    if specification.get("schema_version") == RUN_SCHEMA:
        cost_model = _mapping(specification["cost_model"], "cost model")
        payload.update(
            {
                "plan_sha256": specification["plan_sha256"],
                "plan_fingerprint": specification["plan_fingerprint"],
                "dataset_inputs": specification["dataset_inputs"],
                "cost_model_fingerprint": cost_model["fingerprint"],
            }
        )
    payload["report_fingerprint"] = fingerprint(payload)
    return payload


def _session_row(
    day: date,
    qqq: Sequence[OHLCVBar],
    spy: Sequence[OHLCVBar],
    configuration: LeadLagConfiguration,
    fills: Sequence[Any],
    trades: Sequence[Any],
    daily: Any,
    delay: int,
) -> tuple[dict[str, object], dict[str, object]]:
    horizon = configuration.observation_horizon_bars
    expected = expected_bar_timestamps(
        datetime.combine(day, datetime.min.time(), UTC),
        datetime.combine(day, datetime.max.time(), UTC),
        Timeframe.FIVE_MINUTES,
    )
    timestamps = tuple(bar.timestamp for bar in spy)
    if not expected or timestamps != expected or tuple(bar.timestamp for bar in qqq) != expected:
        raise ValueError("SPY-QQQ Lead-Lag 001 session bars differ from XNYS")
    if delay not in {1, 2, 3}:
        raise ValueError("SPY-QQQ Lead-Lag 001 execution delay differs")
    capacity = len(expected) >= horizon + 27
    spy_return = qqq_return = ratio = bucket = None
    reason = "hold-capacity-ineligible" if not capacity else None
    qualified = False
    entry_decision = planned_exit_decision = None
    if capacity:
        spy_return = _BPS * (spy[horizon - 1].close / spy[0].open - 1)
        qqq_return = _BPS * (qqq[horizon - 1].close / qqq[0].open - 1)
        if spy_return < configuration.minimum_spy_impulse_bps:
            reason = "inactive-spy-below-floor"
        else:
            ratio = qqq_return / spy_return
            if qqq_return < 0:
                reason = "inactive-qqq-negative"
            elif ratio > Decimal("0.5"):
                reason = "inactive-qqq-over-response"
            else:
                qualified, bucket = True, _bucket(ratio)
                entry_decision = spy[horizon - 1].timestamp + Timeframe.FIVE_MINUTES.duration
                planned_exit_decision = (
                    spy[horizon + 23].timestamp + Timeframe.FIVE_MINUTES.duration
                )
    session_fills = tuple(fill for fill in fills if _account_day(fill.fill_timestamp) == day)
    session_trades = tuple(trade for trade in trades if _account_day(trade.entry_timestamp) == day)
    qqq_fills, spy_fills = (
        tuple(fill for fill in session_fills if fill.symbol == _QQQ),
        tuple(fill for fill in session_fills if fill.symbol == _SPY),
    )
    entry_fills = tuple(fill for fill in qqq_fills if fill.quantity > 0)
    exit_fills = tuple(fill for fill in qqq_fills if fill.quantity < 0)
    if qualified:
        if len(entry_fills) != 1 or len(exit_fills) != 1 or spy_fills or len(session_trades) != 1:
            raise ValueError("SPY-QQQ Lead-Lag 001 active session execution differs")
        entry, exit_, trade = entry_fills[0], exit_fills[0], session_trades[0]
        expected_entry_fill = expected[horizon - 1 + delay]
        expected_exit_fill = expected[horizon + 23 + delay]
        if (
            entry.symbol != _QQQ
            or exit_.symbol != _QQQ
            or trade.symbol != _QQQ
            or entry.decision_timestamp != entry_decision
            or exit_.decision_timestamp != planned_exit_decision
            or entry.fill_timestamp != expected_entry_fill
            or exit_.fill_timestamp != expected_exit_fill
            or trade.entry_timestamp != expected_entry_fill
            or trade.exit_timestamp != expected_exit_fill
            or trade.holding_bars != Decimal("24")
        ):
            raise ValueError("SPY-QQQ Lead-Lag 001 active session timing differs")
        active = True
    else:
        if session_fills or session_trades:
            raise ValueError("SPY-QQQ Lead-Lag 001 inactive session has execution")
        entry = exit_ = None
        active = False
    gross = sum((trade.gross_profit for trade in session_trades), _ZERO)
    slip = sum((fill.adverse_slippage for fill in session_fills), _ZERO)
    if daily is None or date.fromisoformat(daily.account_day) != day:
        raise ValueError("SPY-QQQ Lead-Lag 001 daily fee ledger differs")
    fees = daily.charges.total
    if not active and (gross != _ZERO or slip != _ZERO or fees != _ZERO):
        raise ValueError("SPY-QQQ Lead-Lag 001 inactive session has accounting")
    disposition = "active" if active else cast(str, reason)
    trace = {
        "session": day.isoformat(),
        "candidate_id": configuration.candidate_id,
        "observation_horizon_bars": horizon,
        "minimum_spy_impulse_bps": configuration.minimum_spy_impulse_bps,
        "signal_eligible": capacity,
        "spy_return_bps": spy_return,
        "qqq_return_bps": qqq_return,
        "under_response_ratio": ratio,
        "under_response_bucket": bucket,
        "qualifying_signal": qualified,
        "inactive_reason": None if qualified else reason,
        "entry_decision_timestamp": entry_decision,
        "planned_exit_decision_timestamp": planned_exit_decision,
    }
    return (
        {
            **trace,
            "disposition": disposition,
            "hold_capacity": capacity,
            "active": active,
            "entry_decision_timestamp": entry_decision,
            "entry_fill_timestamp": None if entry is None else entry.fill_timestamp,
            "exit_decision_timestamp": planned_exit_decision,
            "exit_fill_timestamp": None if exit_ is None else exit_.fill_timestamp,
            "qqq_fill_count": len(qqq_fills),
            "spy_fill_count": len(spy_fills),
            "completed_round_trips": len(session_trades),
            "gross_profit_loss": gross,
            "adverse_slippage": slip,
            "regulatory_fees": fees,
            "execution_friction": slip + fees,
            "net_profit_loss": gross - slip - fees,
        },
        trace,
    )


def _bucket(value: Decimal) -> str:
    if value < Decimal(1) / 6:
        return "under-response-0-to-1-6"
    if value < Decimal(1) / 3:
        return "under-response-1-6-to-1-3"
    return "under-response-1-3-to-1-2"


def _aggregate_lead_lag_reports(reports: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    aggregate = _source_aggregate_reports(reports)
    ledger = [
        row
        for report in reports
        for row in cast(
            list[dict[str, object]], _mapping(report["details"], "details")["session_ledger"]
        )
    ]
    if len({str(row["session"]) for row in ledger}) != len(ledger):
        raise ValueError("SPY-QQQ Lead-Lag 001 aggregate sessions collide")
    buckets = {
        bucket: sum(
            (
                Decimal(str(row["net_profit_loss"]))
                for row in ledger
                if row["under_response_bucket"] == bucket
            ),
            _ZERO,
        )
        for bucket in (
            "under-response-0-to-1-6",
            "under-response-1-6-to-1-3",
            "under-response-1-3-to-1-2",
        )
    }
    net = sum((Decimal(str(row["net_profit_loss"])) for row in ledger), _ZERO)
    if (
        abs(net - Decimal(str(aggregate["net_profit_loss"]))).quantize(_ACCOUNTING_PRECISION)
        != _ZERO
    ):
        raise ValueError("SPY-QQQ Lead-Lag 001 aggregate accounting differs")
    aggregate.update(
        {
            "session_ledger": ledger,
            "active_session_count": sum(row["disposition"] == "active" for row in ledger),
            "signal_eligible_session_count": sum(
                cast(bool, row["signal_eligible"]) for row in ledger
            ),
            "hold_capacity_ineligible_session_count": sum(
                row["disposition"] == "hold-capacity-ineligible" for row in ledger
            ),
            "positive_profit_session_concentration": _positive_concentration(
                tuple(Decimal(str(row["net_profit_loss"])) for row in ledger)
            ),
            "positive_profit_period_concentration": _positive_concentration(
                tuple(
                    Decimal(str(_mapping(report["metrics"], "metrics")["net_profit_loss"]))
                    for report in reports
                )
            ),
            "signal_bucket_net_profit_loss": buckets,
            "positive_profit_signal_bucket_concentration": _positive_concentration(
                tuple(buckets.values())
            ),
            "signal_trace_mismatch_count": sum(
                int(_mapping(report["metrics"], "metrics")["signal_trace_mismatch_count"])
                for report in reports
            ),
        }
    )
    return aggregate


_aggregate_reports = _aggregate_lead_lag_reports


def _pair_values(
    normal: Mapping[str, Any], zero: Mapping[str, Any], normal_name: str, zero_name: str
) -> dict[str, Decimal | int | None]:
    values = {
        f"{normal_name}.{key}": value
        for key, value in _mapping(normal["metrics"], "metrics").items()
        if isinstance(value, Decimal | int) or value is None
    }
    values.update(
        {
            f"{zero_name}.{key}": value
            for key, value in _mapping(zero["metrics"], "metrics").items()
            if isinstance(value, Decimal | int) or value is None
        }
    )
    values[f"{normal_name}.signal_trace_mismatch_count"] = (
        0 if normal["lead_signal_trace_fingerprint"] == zero["lead_signal_trace_fingerprint"] else 1
    )
    return values


def _positive_fold(report: Mapping[str, Any]) -> bool:
    return (
        _report_metric(report, "net_profit_loss") > 0 and _report_metric(report, "total_return") > 0
    )


def _walk_values(
    normals: Sequence[Mapping[str, Any]],
    normal: Mapping[str, object],
    zero: Mapping[str, object],
    positive: Sequence[Mapping[str, Any]],
) -> dict[str, Decimal | int | None]:
    final = normals[-1]
    values: dict[str, Decimal | int | None] = {
        "positive_normal_fold_count": len(positive),
        "minimum_active_sessions_in_positive_normal_fold": min(
            (
                int(_mapping(report["metrics"], "metrics")["active_session_count"])
                for report in positive
            ),
            default=None,
        ),
        "worst_normal_fold_return": min(
            _report_metric(report, "total_return") for report in normals
        ),
        "worst_normal_fold_drawdown": max(
            _report_metric(report, "max_drawdown") for report in normals
        ),
    }
    for prefix, aggregate in (
        ("aggregate.normal", normal),
        ("aggregate.zero_cost_diagnostic", zero),
    ):
        for key, value in aggregate.items():
            if isinstance(value, Decimal | int) or value is None:
                values[f"{prefix}.{key}"] = value
    for key, value in _mapping(final["metrics"], "metrics").items():
        if isinstance(value, Decimal | int) or value is None:
            values[f"final_exposed_may.normal.{key}"] = value
    return values


def _load_launch_control(repository: Path, *, source_commit: str) -> Mapping[str, Any]:
    if REVIEWED_LAUNCH_CONTROL_SHA256 is None or REVIEWED_LAUNCH_CONTROL_FINGERPRINT is None:
        raise ValueError("SPY-QQQ Lead-Lag 001 launch control is not hash-bound")
    path = repository / LAUNCH_CONTROL_RELATIVE_PATH
    if not path.is_file():
        raise ValueError("SPY-QQQ Lead-Lag 001 launch control review is missing")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != REVIEWED_LAUNCH_CONTROL_SHA256:
        raise ValueError("SPY-QQQ Lead-Lag 001 launch control SHA-256 differs")
    try:
        value = _mapping(json.loads(raw), "launch control review")
    except json.JSONDecodeError as error:
        raise ValueError("SPY-QQQ Lead-Lag 001 launch control is invalid JSON") from error
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
        raise ValueError("SPY-QQQ Lead-Lag 001 launch control differs")
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
        raise ValueError("SPY-QQQ Lead-Lag 001 launch review identity differs")
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
        raise ValueError("SPY-QQQ Lead-Lag 001 launch independent review differs")
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
        "program_state": {
            "path": STATE_RELATIVE_PATH.as_posix(),
            "sha256": STATE_SHA256,
            "fingerprint": STATE_FINGERPRINT,
        },
        "autonomous_program": {
            "path": AUTONOMOUS_PROGRAM_RELATIVE_PATH.as_posix(),
            "sha256": AUTONOMOUS_PROGRAM_SHA256,
            "fingerprint": AUTONOMOUS_PROGRAM_FINGERPRINT,
        },
        "autonomous_program_review": {
            "path": AUTONOMOUS_REVIEW_RELATIVE_PATH.as_posix(),
            "sha256": AUTONOMOUS_REVIEW_SHA256,
            "fingerprint": AUTONOMOUS_REVIEW_FINGERPRINT,
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
        "execution_cost_model": {
            "path": "config/research/intraday-execution-cost-model-001-v1.json",
            "sha256": "a9e6c2b86c6623d73e089de591c55eeec0711fa55f0933a4e3ea9a1c0c2392af",
            "fingerprint": "94fc3ba4663b422fbb0dc0cce7e3d78a7ba81f22d71d5fa986ab6847b7925bb4",
        },
        "execution_cost_review": {
            "path": "config/research/intraday-execution-cost-model-001-independent-review-v1.json",
            "sha256": "fb197856b9229349e5de4bca742f328a8f1e5e53f9558dfd7324744e91a795aa",
            "fingerprint": "8ade5190bb64330af037f88bf0911ed3cdb04578ca7a6d6e27a5fa6d651349b2",
        },
    }
    if dict(inputs) != expected:
        raise ValueError("SPY-QQQ Lead-Lag 001 launch inputs differ")


def _verify_launch_implementation(repository: Path, value: Mapping[str, Any]) -> str:
    implementation = _mapping(value.get("implementation"), "launch implementation")
    _require_exact_keys(implementation, {"source_commit", "files"}, "launch implementation")
    source_commit = _validated_source_commit(implementation.get("source_commit"))
    files = implementation.get("files")
    if not isinstance(files, list) or len(files) != len(_LAUNCH_CONTROL_FILES):
        raise ValueError("SPY-QQQ Lead-Lag 001 launch files differ")
    for item, expected_path in zip(files, _LAUNCH_CONTROL_FILES, strict=True):
        binding = _mapping(item, "launch implementation file")
        _require_exact_keys(binding, {"path", "sha256"}, "launch implementation file")
        if binding.get("path") != expected_path or binding.get("sha256") != _sha256_path(
            repository / expected_path
        ):
            raise ValueError("SPY-QQQ Lead-Lag 001 implementation file differs")
    return source_commit


def _verify_launch_quality(value: Mapping[str, Any], source_commit: str) -> None:
    quality = _mapping(value.get("quality_gates"), "launch quality gates")
    _require_exact_keys(quality, {"source_commit", "results"}, "launch quality gates")
    results = quality.get("results")
    if quality.get("source_commit") != source_commit or not isinstance(results, list):
        raise ValueError("SPY-QQQ Lead-Lag 001 launch quality gates differ")
    if len(results) != len(_LAUNCH_CONTROL_QUALITY_GATES):
        raise ValueError("SPY-QQQ Lead-Lag 001 launch quality gate count differs")
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
            raise ValueError("SPY-QQQ Lead-Lag 001 launch quality gate differs")
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
    count = equivalence.get("fixture_count")
    if (
        equivalence.get("schema_version") != "intraday-spy-qqq-lead-lag-001-parallel-equivalence-v1"
        or equivalence.get("program_id") != PROGRAM_ID
        or equivalence.get("verification_source_commit") != source_commit
        or equivalence.get("fixture_kind") != "synthetic-non-protected-spy-qqq-five-minute-bars"
        or equivalence.get("protected_inputs_accessed") is not False
        or equivalence.get("worker_counts") != [1, 4]
        or equivalence.get("comparisons") != list(_LAUNCH_CONTROL_EQUIVALENCE_COMPARISONS)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count < 3
        or not isinstance(fixtures, list)
        or len(fixtures) != count
        or equivalence.get("equivalent") is not True
    ):
        raise ValueError("SPY-QQQ Lead-Lag 001 launch equivalence differs")
    for key in ("sequential_seconds", "parallel_seconds", "speedup"):
        _required_positive_decimal_text(equivalence.get(key), f"launch equivalence {key}")
    fixture_keys = {
        "candidate_id",
        "scenario_id",
        "run_id",
        "run_fingerprint",
        "signal_trace_fingerprint",
        "decision_trace_fingerprint",
        "transition_trace_fingerprint",
        "fill_trace_fingerprint",
        "round_trip_fingerprint",
        "daily_fee_ledger_fingerprint",
        "session_ledger_fingerprint",
        "report_sha256",
        "report_fingerprint",
        "specification_equal",
        "report_equal",
        "session_ledger_equal",
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
            "session_ledger_equal",
            "canonical_report_equal",
        }:
            _required_sha256(fixture.get(key), f"launch equivalence fixture {key}")
        if any(
            fixture.get(key) is not True
            for key in (
                "specification_equal",
                "report_equal",
                "session_ledger_equal",
                "canonical_report_equal",
            )
        ):
            raise ValueError("SPY-QQQ Lead-Lag 001 equivalence fixture differs")
        candidates.add(str(fixture["candidate_id"]))
        scenarios.add(str(fixture["scenario_id"]))
    if len(candidates) < 2 or len(scenarios) < 2:
        raise ValueError("SPY-QQQ Lead-Lag 001 equivalence lacks design span")


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
        raise ValueError("SPY-QQQ Lead-Lag 001 launch source lineage is unavailable") from error
    paths = frozenset(line for line in changed.stdout.splitlines() if line)
    required = {
        LAUNCH_CONTROL_RELATIVE_PATH.as_posix(),
        "src/systematic_trading_lab/intraday_spy_qqq_lead_lag_001_launch_control.py",
    }
    if (
        ancestor.returncode != 0
        or not required.issubset(paths)
        or not paths.issubset(_LAUNCH_CONTROL_POST_REVIEW_FILES)
    ):
        raise ValueError("SPY-QQQ Lead-Lag 001 launch source lineage differs")


def _require_exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"SPY-QQQ Lead-Lag 001 {label} fields differ")


def _validated_source_commit(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("SPY-QQQ Lead-Lag 001 launch source commit differs")
    return value


def _required_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"SPY-QQQ Lead-Lag 001 {label} differs")
    return value


def _required_positive_decimal_text(value: object, label: str) -> None:
    try:
        parsed = Decimal(str(value))
    except Exception as error:
        raise ValueError(f"SPY-QQQ Lead-Lag 001 {label} differs") from error
    if not isinstance(value, str) or not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"SPY-QQQ Lead-Lag 001 {label} differs")


@dataclass(frozen=True)
class _EquivalenceWorkerFactory:
    repository: Path

    def __call__(self) -> _EquivalenceWorker:
        return _EquivalenceWorker(self.repository)


class _EquivalenceWorker:
    def __init__(self, repository: Path) -> None:
        _require_non_broker_environment()
        self.repository = repository.resolve()
        self.plan = load_intraday_spy_qqq_lead_lag_001_plan(self.repository)
        self.cost_model = load_intraday_execution_cost_model(self.repository)
        self.scenarios = _scenarios(self.cost_model)
        self.bars = _synthetic_equivalence_bars()

    def __call__(self, task: Mapping[str, object]) -> Mapping[str, object]:
        context = _mapping(task["context"], "context")
        configuration = next(
            item
            for item in self.plan.configurations
            if item.candidate_id == _text(context, "candidate_id")
        )
        scenario = self.scenarios[_text(context, "scenario_id")]
        specification = cast(
            dict[str, object],
            canonicalize(
                {
                    "schema_version": "intraday-spy-qqq-lead-lag-001-synthetic-equivalence-v1",
                    "program_id": PROGRAM_ID,
                    "source_commit": _text(task, "source_commit"),
                    "cost_model": {
                        "execution_delay_bars": scenario.execution_delay_bars,
                    },
                    "context": {
                        "candidate_id": configuration.candidate_id,
                        "period_id": _EQUIVALENCE_PERIOD.period_id,
                        "scenario_id": scenario.scenario_id,
                    },
                    "authority": _AUTHORITY,
                }
            ),
        )
        result = IntradayExposed002Engine(
            Decimal("100000"), scenario, self.cost_model.regulatory_fees
        ).run(
            self.bars,
            build_intraday_spy_qqq_lead_lag_001_strategy(
                configuration, _EQUIVALENCE_PERIOD.evaluation_start
            ),
        )
        report = _run_report(specification, result, _EQUIVALENCE_PERIOD, self.bars, configuration)
        raw = (canonical_json(report) + "\n").encode()
        execution = _mapping(report["execution_evidence"], "execution evidence")
        details = _mapping(report["details"], "report details")
        return {
            "candidate_id": configuration.candidate_id,
            "scenario_id": scenario.scenario_id,
            "run_id": report["run_id"],
            "specification": specification,
            "run_fingerprint": fingerprint(specification),
            "signal_trace_fingerprint": report["lead_signal_trace_fingerprint"],
            "decision_trace_fingerprint": execution["decision_trace_fingerprint"],
            "transition_trace_fingerprint": execution["transition_trace_fingerprint"],
            "fill_trace_fingerprint": execution["fill_trace_fingerprint"],
            "round_trip_fingerprint": execution["round_trip_fingerprint"],
            "daily_fee_ledger_fingerprint": execution["daily_fee_ledger_fingerprint"],
            "metrics": report["metrics"],
            "session_ledger": details["session_ledger"],
            "session_ledger_fingerprint": fingerprint(details["session_ledger"]),
            "report_bytes": raw,
            "report_sha256": hashlib.sha256(raw).hexdigest(),
            "report_fingerprint": report["report_fingerprint"],
        }


def _synthetic_equivalence_bars() -> tuple[OHLCVBar, ...]:
    bars: list[OHLCVBar] = []
    indices: dict[date, int] = {}
    for timestamp in expected_bar_timestamps(
        _EQUIVALENCE_PERIOD.context_start,
        _EQUIVALENCE_PERIOD.evaluation_end,
        Timeframe.FIVE_MINUTES,
    ):
        day, index = _account_day(timestamp), indices.get(_account_day(timestamp), 0)
        indices[day] = index + 1
        for symbol in (_QQQ, _SPY):
            opening = Decimal("100")
            closing = Decimal("100")
            if day == date(2026, 1, 8) and index >= 5:
                closing = Decimal("101") if symbol == _SPY else Decimal("100.2")
            if day == date(2026, 1, 8) and index >= 30 and symbol == _QQQ:
                opening = closing = Decimal("101")
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


def _parallel_equivalence(repository: Path, *, source_commit: str) -> dict[str, object]:
    plan = load_intraday_spy_qqq_lead_lag_001_plan(repository.resolve())
    choices = (
        (plan.configurations[0], "normal"),
        (plan.configurations[4], "zero_cost_diagnostic"),
        (plan.configurations[8], "stress_a"),
        (plan.configurations[2], "normal-delay-3"),
    )
    tasks = tuple(
        {
            "source_commit": source_commit,
            "context": {"candidate_id": config.candidate_id, "scenario_id": scenario},
        }
        for config, scenario in choices
    )
    factory = _EquivalenceWorkerFactory(repository.resolve())
    preflight_process_stage(tasks, worker_factory=factory)
    started = time.perf_counter()
    sequential = run_process_stage(tasks, worker_factory=factory, workers=1)
    sequential_seconds = time.perf_counter() - started
    started = time.perf_counter()
    parallel = run_process_stage(tasks, worker_factory=factory, workers=4)
    parallel_seconds = time.perf_counter() - started
    fixtures: list[dict[str, object]] = []
    equivalent = True
    for left_value, right_value in zip(sequential, parallel, strict=True):
        left = _mapping(left_value, "sequential equivalence result")
        right = _mapping(right_value, "parallel equivalence result")
        comparisons = {
            "specification_equal": left["specification"] == right["specification"],
            "report_equal": left["metrics"] == right["metrics"],
            "session_ledger_equal": left["session_ledger"] == right["session_ledger"],
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
                    "transition_trace_fingerprint",
                    "fill_trace_fingerprint",
                    "round_trip_fingerprint",
                    "daily_fee_ledger_fingerprint",
                    "session_ledger_fingerprint",
                    "report_sha256",
                    "report_fingerprint",
                )
            }
            | comparisons
        )
    if not equivalent:
        raise ValueError("SPY-QQQ Lead-Lag 001 one-worker/four-worker equivalence differs")
    sequential_seconds = max(sequential_seconds, 0.000001)
    parallel_seconds = max(parallel_seconds, 0.000001)
    return {
        "schema_version": "intraday-spy-qqq-lead-lag-001-parallel-equivalence-v1",
        "program_id": PROGRAM_ID,
        "verification_source_commit": source_commit,
        "fixture_kind": "synthetic-non-protected-spy-qqq-five-minute-bars",
        "worker_counts": [1, 4],
        "comparisons": list(_LAUNCH_CONTROL_EQUIVALENCE_COMPARISONS),
        "fixture_count": len(fixtures),
        "sequential_seconds": f"{sequential_seconds:.6f}",
        "parallel_seconds": f"{parallel_seconds:.6f}",
        "speedup": f"{sequential_seconds / parallel_seconds:.6f}",
        "fixtures": fixtures,
        "equivalent": True,
        "protected_inputs_accessed": False,
    }


def verify_intraday_spy_qqq_lead_lag_001_parallel_equivalence(
    repository: Path,
) -> dict[str, object]:
    repository = repository.resolve()
    return _parallel_equivalence(repository, source_commit=_source_commit(repository))


def intraday_spy_qqq_lead_lag_001_plan_summary(repository: Path) -> dict[str, object]:
    repository = repository.resolve()
    plan = load_intraday_spy_qqq_lead_lag_001_plan(repository)
    bound = False
    if (
        REVIEWED_LAUNCH_CONTROL_SHA256 is not None
        and REVIEWED_LAUNCH_CONTROL_FINGERPRINT is not None
    ):
        try:
            _load_launch_control(repository, source_commit=_source_commit(repository))
        except ValueError:
            pass
        else:
            bound = True
    return {
        "program_id": PROGRAM_ID,
        "status": "launch-reviewed-ready" if bound else "implementation-awaiting-review",
        "terminal": False,
        "outcome": None,
        "launchable": bound,
        "launch_control_bound": bound,
        "plan_sha256": plan.sha256,
        "plan_fingerprint": plan.plan_fingerprint,
        "plan_review_sha256": plan.review_sha256,
        "plan_review_fingerprint": plan.review_fingerprint,
        "parent_configuration_count": len(plan.configurations),
        "discovery_run_specification_count": 18,
        "maximum_run_specifications": 90,
        "maximum_attempts": 270,
        "period_count": len(plan.periods),
        "default_workers": DEFAULT_RESEARCH_WORKERS,
        "authority": _AUTHORITY,
    }


def intraday_spy_qqq_lead_lag_001_status(data_home: Path) -> dict[str, object]:
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
            ):
                counts[str(status)] = int(count)
            attempts = int(
                connection.execute(
                    "SELECT COALESCE(SUM(attempt_count), 0) FROM research_runs"
                ).fetchone()[0]
            )
            for failure_class, count in connection.execute(
                "SELECT failure_class, COUNT(*) FROM research_runs "
                "WHERE failure_class IS NOT NULL GROUP BY failure_class"
            ):
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
        "cohort_size": (
            None if final is None else _mapping(final.get("counts"), "final counts").get("cohort")
        ),
        "authority": _AUTHORITY,
    }


def run_intraday_spy_qqq_lead_lag_001_campaign(
    repository: Path,
    data_home: Path,
    *,
    workers: int = DEFAULT_RESEARCH_WORKERS,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    return IntradaySpyQqqLeadLag001Runner(
        repository, data_home, workers=workers, progress=progress
    ).run()
