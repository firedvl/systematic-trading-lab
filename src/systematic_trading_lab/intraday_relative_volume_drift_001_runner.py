"""Restart-safe ordinary-session runner for Intraday Relative-Volume Drift 001."""

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
from decimal import Decimal, InvalidOperation
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
    _gates,
    _mapping,
    _positive_concentration,
    _required_text,
    _scenarios,
    _sha256_path,
    _source_commit,
    _text,
    _write_create_only,
    _write_create_only_text,
)
from .intraday_exposed_002_runner import _run_report as _source_run_report
from .intraday_relative_volume_drift_001_plan import (
    PLAN_FINGERPRINT,
    PLAN_RELATIVE_PATH,
    PLAN_SHA256,
    PROGRAM_ID,
    REVIEW_FINGERPRINT,
    REVIEW_RELATIVE_PATH,
    REVIEW_SHA256,
    SOURCE_STATE_FINGERPRINT,
    SOURCE_STATE_RELATIVE_PATH,
    SOURCE_STATE_SHA256,
    STATE_FINGERPRINT,
    STATE_RELATIVE_PATH,
    STATE_SHA256,
    IntradayRelativeVolumeDrift001Plan,
    RelativeVolumeConfiguration,
    RelativeVolumePeriod,
    load_intraday_relative_volume_drift_001_plan,
)
from .intraday_relative_volume_drift_001_strategies import (
    build_intraday_relative_volume_drift_001_strategy,
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
    from .intraday_relative_volume_drift_001_launch_control import (
        REVIEWED_LAUNCH_CONTROL_FINGERPRINT as _reviewed_launch_control_fingerprint,
    )
    from .intraday_relative_volume_drift_001_launch_control import (
        REVIEWED_LAUNCH_CONTROL_SHA256 as _reviewed_launch_control_sha256,
    )
except ImportError:
    REVIEWED_LAUNCH_CONTROL_SHA256 = None
    REVIEWED_LAUNCH_CONTROL_FINGERPRINT = None
else:
    REVIEWED_LAUNCH_CONTROL_SHA256 = _reviewed_launch_control_sha256
    REVIEWED_LAUNCH_CONTROL_FINGERPRINT = _reviewed_launch_control_fingerprint

RUNNER_VERSION = "intraday-relative-volume-drift-001-runner-v1"
RUN_SCHEMA = "intraday-relative-volume-drift-001-run-v1"
RUN_REPORT_SCHEMA = "intraday-relative-volume-drift-001-backtest-report-v1"
FINAL_FREEZE_SCHEMA = "intraday-relative-volume-drift-001-final-freeze-v1"
FINAL_REPORT_SCHEMA = "intraday-relative-volume-drift-001-final-report-v1"
PROGRAM_BINDING_SCHEMA = "intraday-relative-volume-drift-001-program-binding-v1"
DATABASE_NAME = "intraday-relative-volume-drift-001.sqlite3"
ENGINE_VERSION = "intraday-exposed-002-engine-v1"
STRATEGY_VERSION = "intraday-joint-relative-volume-drift-v1"
LAUNCH_CONTROL_RELATIVE_PATH = Path(
    "config/research/intraday-relative-volume-drift-001-launch-control-review-v1.json"
)
_LAUNCH_CONTROL_SCHEMA = "intraday-relative-volume-drift-001-launch-control-review-v1"
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
    "src/systematic_trading_lab/intraday_relative_volume_drift_001_plan.py",
    "src/systematic_trading_lab/intraday_relative_volume_drift_001_strategies.py",
    "src/systematic_trading_lab/intraday_relative_volume_drift_001_runner.py",
    "src/systematic_trading_lab/intraday_relative_volume_drift_001_cli.py",
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
        "src/systematic_trading_lab/intraday_relative_volume_drift_001_launch_control.py",
        "tests/unit/test_intraday_relative_volume_drift_001_runner.py",
        "CURRENT_STATE.md",
        "DECISIONS.md",
        "ROADMAP.md",
        "docs/research-campaigns/intraday-relative-volume-drift-001-program.md",
        "docs/research-campaigns/intraday-autonomous-research-001-program.md",
        "docs/research-campaigns/intraday-autonomous-research-001-state.json",
        "docs/research-campaigns/intraday-autonomous-research-001-state-v2-revision-004.json",
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
        "strategy_results": False,
        "research_qualification": False,
        "controlled_evaluation": False,
        "protected_holdout": False,
        "paper_execution": False,
        "broker_writes": False,
        "live_execution": False,
    }
)
_EQUIVALENCE_PERIOD = RelativeVolumePeriod(
    "synthetic-equivalence-2025-12-23-through-2026-01-09",
    datetime(2025, 12, 23, 14, 30, tzinfo=UTC),
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


def decode_canonical_metric(value: object, *, allow_null: bool = False) -> Decimal | int | None:
    """Decode the only numeric forms permitted at a screening boundary."""
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
        decoded = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("metric must be a canonical Decimal string") from error
    if not decoded.is_finite() or canonicalize(decoded) != value:
        raise ValueError("metric Decimal string is noncanonical")
    return decoded


def _decode_frozen_threshold(value: object) -> Decimal | int:
    """Decode exact reviewed-plan threshold text, which may retain trailing zeroes."""
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
        raise ValueError("frozen gate threshold must be Decimal text") from error
    if not decoded.is_finite() or format(decoded, "f") != value:
        raise ValueError("frozen gate threshold text differs")
    return decoded


def decode_metrics(
    metrics: Mapping[str, object], required: Sequence[str]
) -> dict[str, Decimal | int]:
    decoded: dict[str, Decimal | int] = {}
    for key in required:
        if key not in metrics:
            raise ValueError(f"missing required metric: {key}")
        value = decode_canonical_metric(metrics[key])
        if value is None:
            raise ValueError(f"semantic null metric fails gate: {key}")
        decoded[key] = value
    return decoded


def gate_passes(value: Decimal | int | None, comparison: str, threshold: object) -> bool:
    if value is None:
        return False
    right = _decode_frozen_threshold(threshold)
    left_decimal, right_decimal = Decimal(value), Decimal(right)
    if comparison == ">":
        return left_decimal > right_decimal
    if comparison == ">=":
        return left_decimal >= right_decimal
    if comparison == "<":
        return left_decimal < right_decimal
    if comparison == "<=":
        return left_decimal <= right_decimal
    if comparison == "=":
        return left_decimal == right_decimal
    raise ValueError(f"unknown frozen gate comparison: {comparison}")


def validate_screen(
    metrics: Mapping[str, object], gates: Sequence[Mapping[str, object]]
) -> tuple[bool, tuple[str, ...]]:
    results = _strict_gate_results(gates, metrics)
    failures = tuple(_text(result, "metric") for result in results if not result["passed"])
    return not failures, failures


def canonical_json_reload(value: Mapping[str, object]) -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)),
    )


def recompute_terminal_cohort(
    reports: Mapping[str, Mapping[str, object]], *, final_cohort_maximum: int = 1
) -> tuple[str, ...]:
    survivors: list[str] = []
    for candidate_id, report in sorted(reports.items()):
        if report.get("candidate_id") != candidate_id:
            raise ValueError("terminal report candidate identity mismatch")
        passed = report.get("all_gates_passed")
        if not isinstance(passed, bool):
            raise ValueError("terminal all_gates_passed must be boolean")
        if passed:
            survivors.append(candidate_id)
    if len(survivors) > final_cohort_maximum:
        raise ValueError("terminal cohort exceeds frozen maximum")
    return tuple(survivors)


def validate_paired_traces(normal: Mapping[str, object], zero_cost: Mapping[str, object]) -> None:
    for field in ("signal_trace_fingerprint", "decision_trace_fingerprint"):
        value = normal.get(field)
        if not isinstance(value, str) or value != zero_cost.get(field):
            raise ValueError(f"paired Normal/zero-cost {field} mismatch")


def validate_accounting(metrics: Mapping[str, object]) -> None:
    values = decode_metrics(metrics, ("gross_profit_loss", "execution_friction", "net_profit_loss"))
    error = abs(
        Decimal(values["gross_profit_loss"])
        - Decimal(values["execution_friction"])
        - Decimal(values["net_profit_loss"])
    ).quantize(_ACCOUNTING_PRECISION)
    if error != _ZERO:
        raise ValueError("accounting identity failure")


def _strict_gate_results(
    gates: Sequence[Mapping[str, object]],
    values: Mapping[str, object],
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for gate in gates:
        metric = _text(cast(Mapping[str, Any], gate), "metric")
        comparison = _text(cast(Mapping[str, Any], gate), "comparison")
        if "threshold" not in gate:
            raise ValueError("frozen gate threshold is missing")
        if metric not in values:
            raise ValueError(f"missing required metric: {metric}")
        observed = decode_canonical_metric(values[metric], allow_null=True)
        threshold = _decode_frozen_threshold(gate["threshold"])
        results.append(
            {
                "metric": metric,
                "comparison": comparison,
                "threshold": threshold,
                "observed": observed,
                "passed": gate_passes(observed, comparison, threshold),
            }
        )
    return results


def _strict_ledger_metric(item: Mapping[str, object], key: str) -> Decimal:
    metrics = _mapping(item.get("metrics"), "screening metrics")
    if key not in metrics:
        raise ValueError(f"missing required ranking metric: {key}")
    value = decode_canonical_metric(metrics[key])
    if value is None:
        raise ValueError(f"undefined ranking metric: {key}")
    return Decimal(value)


def _report_scalars(report: Mapping[str, Any]) -> dict[str, Decimal | int | None]:
    values: dict[str, Decimal | int | None] = {}
    for key, raw in _mapping(report.get("metrics"), "report metrics").items():
        if isinstance(raw, Mapping | list | tuple):
            continue
        values[key] = decode_canonical_metric(raw, allow_null=True)
    return values


def _report_metric_strict(
    report: Mapping[str, Any], key: str, *, allow_null: bool = False
) -> Decimal | None:
    metrics = _mapping(report.get("metrics"), "report metrics")
    if key not in metrics:
        raise ValueError(f"missing required report metric: {key}")
    value = decode_canonical_metric(metrics[key], allow_null=allow_null)
    if value is None:
        return None
    return Decimal(value)


def _report_count(report: Mapping[str, Any], key: str) -> int:
    metrics = _mapping(report.get("metrics"), "report metrics")
    if key not in metrics:
        raise ValueError(f"missing required report count: {key}")
    value = decode_canonical_metric(metrics[key])
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"report count must be a JSON integer: {key}")
    return value


def _canonical_decimal(value: object, label: str) -> Decimal:
    decoded = decode_canonical_metric(value)
    if decoded is None:
        raise ValueError(f"Relative-Volume Drift 001 {label} is null")
    return Decimal(decoded)


def _accounting_values_match(left: Decimal, right: Decimal) -> bool:
    return abs(left - right).quantize(_ACCOUNTING_PRECISION) == _ZERO


def _require_metric_match(report: Mapping[str, Any], key: str, expected: Decimal | None) -> None:
    observed = _report_metric_strict(report, key, allow_null=True)
    if expected is None:
        matches = observed is None
    else:
        matches = observed is not None and _accounting_values_match(observed, expected)
    if not matches:
        raise ValueError(f"Relative-Volume Drift 001 report metric differs: {key}")


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
            "Relative-Volume Drift 001 rejects broker credentials and paper-write opt-in: "
            + ", ".join(forbidden)
        )


class IntradayRelativeVolumeDrift001Store:
    """Campaign names and budget over the common immutable attempt journal."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.attempts = ResearchAttemptStore(
            self.root,
            database_name=DATABASE_NAME,
            lease_timeout=_LEASE_TIMEOUT,
            reconcile_on_open=False,
            attempt_id_prefix="irvd001a-",
        )
        self.path = self.attempts.path

    def bind(self, value: Mapping[str, object]) -> None:
        self.attempts.bind(value)

    def reserve(self, specifications: Sequence[Mapping[str, object]]) -> None:
        values = _deduplicate_specifications(specifications)
        existing = {str(row["run_id"]) for row in self.attempts.list_runs()}
        if len(existing | {_run_id(value) for value in values}) > 90:
            raise ValueError("Relative-Volume Drift 001 run budget exceeds 90 specifications")
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
        self.plan = load_intraday_relative_volume_drift_001_plan(self.repository)
        self.base_plan = load_intraday_event_drift_001_plan(self.repository)
        self.cost_model = load_intraday_execution_cost_model(self.repository)
        self.datasets = _dataset_bindings(self.base_plan.payload)
        self.data_by_dataset = _read_only_dataset_services(self.data_home, self.datasets)
        IntradayExposed002Runner._verify_datasets(cast(Any, self), self.base_plan.payload)
        self.scenarios = _scenarios(self.cost_model)
        self._bar_cache: dict[str, tuple[Any, ...]] = {}
        self.attempt_store = IntradayRelativeVolumeDrift001Store(runtime_root)

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
                    build_intraday_relative_volume_drift_001_strategy(
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

    def _configuration(self, candidate_id: str) -> RelativeVolumeConfiguration:
        for item in self.plan.configurations:
            if item.candidate_id == candidate_id:
                return item
        raise ValueError(f"unknown Relative-Volume Drift 001 candidate: {candidate_id}")

    def _period(self, period_id: str) -> RelativeVolumePeriod:
        for item in self.plan.periods:
            if item.period_id == period_id:
                return item
        raise ValueError(f"unknown Relative-Volume Drift 001 period: {period_id}")


class IntradayRelativeVolumeDrift001Runner:
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
            raise ValueError("Relative-Volume Drift 001 launch control is not hash-bound")
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
        self.plan = load_intraday_relative_volume_drift_001_plan(self.repository)
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
        self.attempt_store = IntradayRelativeVolumeDrift001Store(self.runtime_root)
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
                "source_state_sha256": self.plan.source_state_sha256,
                "source_state_fingerprint": self.plan.source_state_fingerprint,
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
        self,
        configuration: RelativeVolumeConfiguration,
        period: RelativeVolumePeriod,
        scenario_id: str,
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
                    "source_state_sha256": self.plan.source_state_sha256,
                    "source_state_fingerprint": self.plan.source_state_fingerprint,
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
                    "execution": self.plan.payload["execution"],
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
                    f"Relative-Volume Drift 001 run is not reusable: {row['run_id']}"
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
            raise ValueError("Relative-Volume Drift 001 run is not completed")
        relative = Path(cast(str, row["report_path"]))
        raw = (self.runtime_root / relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row.get("report_sha256"):
            raise ValueError("Relative-Volume Drift 001 report SHA-256 differs")
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
            raise ValueError("Relative-Volume Drift 001 report identity differs")
        _validate_run_report_semantics(report)
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
            raise ValueError("Relative-Volume Drift 001 canonical run relationship differs")
        return self._load_report(matches[0])

    def _normal_zero(
        self, candidate_id: str, period_id: str
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        normal, zero = (
            self._report_for(candidate_id, period_id, "normal"),
            self._report_for(candidate_id, period_id, "zero_cost_diagnostic"),
        )
        if normal["signal_trace_fingerprint"] != zero["signal_trace_fingerprint"]:
            raise _CoordinatorValidationError(
                "cross-scenario-signal-validation",
                (_text(normal, "run_id"), _text(zero, "run_id")),
                "ValueError: Relative-Volume Drift 001 paired signal trace differs",
            )
        normal_execution = _mapping(normal.get("execution_evidence"), "normal execution evidence")
        zero_execution = _mapping(zero.get("execution_evidence"), "zero-cost execution evidence")
        if _text(normal_execution, "decision_trace_fingerprint") != _text(
            zero_execution, "decision_trace_fingerprint"
        ):
            raise _CoordinatorValidationError(
                "cross-scenario-decision-validation",
                (_text(normal, "run_id"), _text(zero, "run_id")),
                "ValueError: Relative-Volume Drift 001 paired decision trace differs",
            )
        return normal, zero

    def _require_no_failures(self) -> None:
        failed = tuple(row for row in self.attempt_store.list_runs() if row["status"] == "failed")
        if failed:
            raise AttemptStateError(
                f"Relative-Volume Drift 001 has {len(failed)} terminal failed run(s); no retry is "
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
            gates = _strict_gate_results(
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
                    -_strict_ledger_metric(item, "normal.total_return"),
                    _strict_ledger_metric(item, "normal.positive_profit_session_concentration"),
                    _strict_ledger_metric(item, "normal.cost_to_gross_profit"),
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
                _aggregate_relative_volume_reports(normals),
                _aggregate_relative_volume_reports(zeros),
            )
            positive = tuple(report for report in normals if _positive_fold(report))
            values = _walk_values(normals, normal_aggregate, zero_aggregate, positive)
            gates = _strict_gate_results(
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
                    -_strict_ledger_metric(item, "positive_normal_fold_count"),
                    -_strict_ledger_metric(item, "aggregate.normal.total_return"),
                    _strict_ledger_metric(
                        item, "aggregate.normal.positive_profit_session_concentration"
                    ),
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
            normal = _aggregate_relative_volume_reports(
                tuple(self._report_for(candidate, period.period_id, "normal") for period in periods)
            )
            values: dict[str, Decimal | int | None] = {}
            for scenario in scenarios:
                reports = tuple(
                    self._report_for(candidate, period.period_id, scenario) for period in periods
                )
                for report, period in zip(reports, periods, strict=True):
                    if (
                        report["signal_trace_fingerprint"]
                        != self._report_for(candidate, period.period_id, "normal")[
                            "signal_trace_fingerprint"
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
                            "ValueError: Relative-Volume Drift 001 stress signal trace differs",
                        )
                aggregate = _aggregate_relative_volume_reports(reports)
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
            gates = _strict_gate_results(
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
                "ValueError: Relative-Volume Drift 001 neighbor budget differs",
            )
        self._execute(specifications)
        base_normal = _aggregate_relative_volume_reports(
            tuple(self._report_for(candidate, period.period_id, "normal") for period in periods)
        )
        joint, retentions, mismatch = 0, [], 0
        for neighbor in neighbors:
            normals, zeros = zip(
                *(self._normal_zero(neighbor, period.period_id) for period in periods), strict=True
            )
            normal, zero = (
                _aggregate_relative_volume_reports(normals),
                _aggregate_relative_volume_reports(zeros),
            )
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
        gates = _strict_gate_results(
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

    def _configuration(self, candidate_id: str) -> RelativeVolumeConfiguration:
        for item in self.plan.configurations:
            if item.candidate_id == candidate_id:
                return item
        raise ValueError(f"unknown Relative-Volume Drift 001 candidate: {candidate_id}")

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
            raise ValueError("Relative-Volume Drift 001 frozen search budget exceeded")
        if any(row["status"] != "completed" for row in runs):
            raise ValueError("Relative-Volume Drift 001 freeze requires completed runs")
        canonical_reports = tuple(self._load_report(row) for row in runs)
        screened = {
            "discovery": discovery,
            "walk_forward": walk,
            "stress": serious,
            "neighbors": neighbors,
        }
        validate_terminal_screening(self.plan, canonical_reports, screened, cohort)
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
                "source_state_sha256": self.plan.source_state_sha256,
                "source_state_fingerprint": self.plan.source_state_fingerprint,
                "state_sha256": self.plan.state_sha256,
                "state_fingerprint": self.plan.state_fingerprint,
            },
            "launch_control": self.launch_control,
            "cost_model": {
                "sha256": self.cost_model.sha256,
                "fingerprint": self.cost_model.model_fingerprint,
            },
            "datasets": [canonicalize(item) for item in self.datasets],
            "screened_ledger": screened,
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
                "INTRADAY RELATIVE-VOLUME DRIFT 001 COMPLETE — NO CONTROLLED-QUALIFIED CANDIDATE"
                if empty
                else (
                    "INTRADAY RELATIVE-VOLUME DRIFT 001 COMPLETE — "
                    "WAITING FOR FUTURE UNTOUCHED DATA"
                )
            ),
            "source_commit": self.source_commit,
            "plan_sha256": self.plan.sha256,
            "plan_fingerprint": self.plan.plan_fingerprint,
            "autonomous_program_sha256": self.plan.payload["autonomous_program"]["sha256"],
            "autonomous_program_fingerprint": self.plan.payload["autonomous_program"][
                "fingerprint"
            ],
            "source_state_sha256": self.plan.source_state_sha256,
            "source_state_fingerprint": self.plan.source_state_fingerprint,
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
            "terminal_message": "INTRADAY RELATIVE-VOLUME DRIFT 001 TERMINALLY INTERRUPTED",
            "source_commit": self.source_commit,
            "plan_sha256": self.plan.sha256,
            "plan_fingerprint": self.plan.plan_fingerprint,
            "autonomous_program_sha256": self.plan.payload["autonomous_program"]["sha256"],
            "autonomous_program_fingerprint": self.plan.payload["autonomous_program"][
                "fingerprint"
            ],
            "source_state_sha256": self.plan.source_state_sha256,
            "source_state_fingerprint": self.plan.source_state_fingerprint,
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


def _configuration_summary(configuration: RelativeVolumeConfiguration) -> dict[str, object]:
    return {
        "candidate_id": configuration.candidate_id,
        "strategy_id": STRATEGY_VERSION,
        "observation_horizon_bars": configuration.observation_horizon_bars,
        "minimum_joint_relative_volume": configuration.minimum_joint_relative_volume,
        "qqq_target_weight": Decimal("0.5"),
        "spy_target_weight": Decimal("0.5"),
        "minimum_qqq_return_bps": Decimal("15"),
        "minimum_spy_return_bps": Decimal("15"),
        "prior_complete_session_lookback": 10,
        "hold_bars": 24,
        "neighbor_ids": configuration.neighbor_ids,
    }


def _run_id(specification: Mapping[str, object]) -> str:
    context = _mapping(specification.get("context"), "run context")
    if set(context) != {"candidate_id", "period_id", "scenario_id"}:
        raise ValueError("Relative-Volume Drift 001 canonical run context differs")
    identity = {key: context[key] for key in ("candidate_id", "period_id", "scenario_id")}
    return f"irvd001r-{fingerprint(identity)[:24]}"


def _reservation_id(run_fingerprint: str) -> str:
    return f"irvd001q-{run_fingerprint[:24]}"


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
        "paper_or_broker_state": False,
        "strategic_allocation_21": False,
        "live_execution": False,
        "partial_result_adaptation": False,
    }


def _deduplicate_specifications(
    specifications: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    by_id: dict[str, Mapping[str, object]] = {}
    for specification in specifications:
        run_id = _run_id(specification)
        previous = by_id.get(run_id)
        if previous is not None and canonical_json(previous) != canonical_json(specification):
            raise ValueError("Relative-Volume Drift 001 canonical run identity collides")
        by_id[run_id] = specification
    return tuple(by_id[key] for key in sorted(by_id))


def _validate_campaign_bars(bars: Sequence[OHLCVBar]) -> None:
    if not bars:
        raise ValueError("Relative-Volume Drift 001 data contains no bars")
    by_symbol = {
        symbol: tuple(sorted(bar.timestamp for bar in bars if bar.symbol == symbol))
        for symbol in (_QQQ, _SPY)
    }
    if len(bars) != sum(len(value) for value in by_symbol.values()):
        raise ValueError("Relative-Volume Drift 001 data contains an unexpected symbol")
    if any(len(value) != len(set(value)) for value in by_symbol.values()):
        raise ValueError("Relative-Volume Drift 001 data contains duplicate bars")
    expected = expected_bar_timestamps(
        min(bar.timestamp for bar in bars),
        max(bar.timestamp for bar in bars),
        Timeframe.FIVE_MINUTES,
    )
    if not expected or any(value != expected for value in by_symbol.values()):
        raise ValueError("Relative-Volume Drift 001 data differs from exact XNYS sessions")


def _validate_run_report_semantics(report: Mapping[str, Any]) -> None:
    specification = _mapping(report.get("specification"), "run specification")
    details = _mapping(report.get("details"), "run details")
    metrics = _mapping(report.get("metrics"), "run metrics")
    context = _mapping(specification.get("context"), "run context")
    if (
        report.get("schema_version") != RUN_REPORT_SCHEMA
        or report.get("program_id") != PROGRAM_ID
        or specification.get("schema_version") != RUN_SCHEMA
        or report.get("source_commit") != specification.get("source_commit")
        or report.get("plan_sha256") != specification.get("plan_sha256")
        or report.get("plan_fingerprint") != specification.get("plan_fingerprint")
        or report.get("autonomous_program_sha256") != specification.get("autonomous_program_sha256")
        or report.get("autonomous_program_fingerprint")
        != specification.get("autonomous_program_fingerprint")
        or report.get("source_state_sha256") != specification.get("source_state_sha256")
        or report.get("source_state_fingerprint") != specification.get("source_state_fingerprint")
        or report.get("dataset_inputs") != specification.get("dataset_inputs")
        or report.get("cost_model_fingerprint")
        != _mapping(specification.get("cost_model"), "cost model").get("fingerprint")
        or report.get("authority") != _AUTHORITY
        or set(context) != {"candidate_id", "period_id", "scenario_id"}
    ):
        raise ValueError("Relative-Volume Drift 001 report binding differs")

    _report_scalars(report)
    validate_accounting(metrics)
    if _required_report_decimal(report, "accounting_identity_error") != _ZERO:
        raise ValueError("Relative-Volume Drift 001 report accounting identity differs")
    session_count = _report_count(report, "session_count")
    active_count = _report_count(report, "active_session_count")
    completed = _report_count(report, "completed_round_trips")
    fill_count = _report_count(report, "fill_count")
    signal_mismatch = _report_count(report, "signal_trace_mismatch_count")
    if signal_mismatch != 0 or completed != active_count * 2 or fill_count != active_count * 4:
        raise ValueError("Relative-Volume Drift 001 report execution counts differ")

    raw_ledger, raw_trace = details.get("session_ledger"), details.get("signal_trace")
    if not isinstance(raw_ledger, list) or not isinstance(raw_trace, list):
        raise ValueError("Relative-Volume Drift 001 report trace is missing")
    ledger = tuple(_mapping(row, "session ledger row") for row in raw_ledger)
    trace = tuple(_mapping(row, "signal trace row") for row in raw_trace)
    if (
        len(ledger) != session_count
        or len(trace) != session_count
        or report.get("signal_trace_fingerprint") != fingerprint(trace)
    ):
        raise ValueError("Relative-Volume Drift 001 report signal trace differs")

    dispositions = (
        "active",
        "lookback-ineligible",
        "hold-capacity-ineligible",
        "inactive-joint-return",
        "inactive-joint-relative-volume",
    )
    disposition_counts = _mapping(
        metrics.get("session_disposition_counts"), "session disposition counts"
    )
    if set(disposition_counts) != set(dispositions):
        raise ValueError("Relative-Volume Drift 001 disposition fields differ")
    for code in dispositions:
        count = decode_canonical_metric(disposition_counts[code])
        if not isinstance(count, int):
            raise ValueError("Relative-Volume Drift 001 disposition count is not an integer")
        if count != sum(row.get("disposition") == code for row in ledger):
            raise ValueError("Relative-Volume Drift 001 disposition count differs")

    symbols = ("QQQ", "SPY")
    buckets = (
        "participation-q-1-to-1-2",
        "participation-q-1-2-to-1-5",
        "participation-q-1-5-plus",
    )
    accounting_fields = (
        "gross_profit_loss",
        "gross_profitable_trade_profit",
        "gross_trade_edge_bps_sum",
        "holding_bars_sum",
        "adverse_slippage",
        "regulatory_fees",
        "execution_friction",
        "net_profit_loss",
    )
    symbol_fields = {
        "symbol_gross_profit_loss": "gross_profit_loss",
        "symbol_adverse_slippage": "adverse_slippage",
        "symbol_regulatory_fees": "regulatory_fees",
        "symbol_net_profit_loss": "net_profit_loss",
    }
    aggregate_values = {key: _ZERO for key in accounting_fields}
    aggregate_symbols = {key: {symbol: _ZERO for symbol in symbols} for key in symbol_fields}
    row_net: list[Decimal] = []
    ending_equities: list[Decimal] = []
    session_days: list[date] = []
    ledger_fill_count = 0
    ledger_round_trip_count = 0
    for row, signal in zip(ledger, trace, strict=True):
        if set(signal) - set(row) or any(row[key] != value for key, value in signal.items()):
            raise ValueError("Relative-Volume Drift 001 signal-to-ledger identity differs")
        raw_session = row.get("session")
        if not isinstance(raw_session, str):
            raise ValueError("Relative-Volume Drift 001 session identity differs")
        try:
            session_days.append(date.fromisoformat(raw_session))
        except ValueError as error:
            raise ValueError("Relative-Volume Drift 001 session identity differs") from error
        disposition = row.get("disposition")
        if disposition not in dispositions:
            raise ValueError("Relative-Volume Drift 001 disposition differs")
        for key in (
            "lookback_eligible",
            "hold_capacity",
            "signal_eligible",
            "active",
            "qualifying_signal",
        ):
            if not isinstance(row.get(key), bool):
                raise ValueError(f"Relative-Volume Drift 001 boolean field differs: {key}")
        for key in ("joint_return_passed", "joint_relative_volume_passed"):
            if row.get(key) is not None and not isinstance(row.get(key), bool):
                raise ValueError(f"Relative-Volume Drift 001 predicate differs: {key}")
        for key in ("return_predicates", "relative_volume_predicates"):
            predicates = _mapping(row.get(key), f"session {key}")
            if set(predicates) != {"QQQ", "SPY"} or any(
                value is not None and not isinstance(value, bool) for value in predicates.values()
            ):
                raise ValueError(f"Relative-Volume Drift 001 session {key} differs")
        for key in (
            "minimum_joint_relative_volume",
            "joint_relative_volume",
            "participation_strength",
        ):
            decode_canonical_metric(
                row.get(key),
                allow_null=key
                in {
                    "joint_relative_volume",
                    "participation_strength",
                },
            )
        for key in accounting_fields + ("ending_equity",):
            decode_canonical_metric(row.get(key))
        for key in (
            "prior_cumulative_volumes",
            "baseline_medians",
            "current_cumulative_volumes",
            "relative_volumes",
            "returns_bps",
            "symbol_gross_profit_loss",
            "symbol_adverse_slippage",
            "symbol_regulatory_fees",
            "symbol_net_profit_loss",
        ):
            values = _mapping(row.get(key), f"session {key}")
            if set(values) != set(symbols):
                raise ValueError(f"Relative-Volume Drift 001 session {key} fields differ")
            for value in values.values():
                if isinstance(value, list):
                    for item in value:
                        decode_canonical_metric(item)
                else:
                    decode_canonical_metric(value, allow_null=True)
        for key in ("fill_counts", "round_trip_counts"):
            counts = _mapping(row.get(key), f"session {key}")
            if set(counts) != set(symbols) or any(
                isinstance(value, bool) or not isinstance(value, int) for value in counts.values()
            ):
                raise ValueError(f"Relative-Volume Drift 001 session {key} differs")
        active = disposition == "active"
        participation_bucket = row.get("participation_bucket")
        if (
            row.get("active") is not active
            or row.get("qualifying_signal") is not active
            or (active and participation_bucket not in buckets)
            or (not active and participation_bucket is not None)
            or _integer_value(row.get("completed_round_trips"), "session round trips")
            != (2 if active else 0)
            or any(
                value != (2 if active else 0)
                for value in _mapping(row["fill_counts"], "fill counts").values()
            )
            or any(
                value != (1 if active else 0)
                for value in _mapping(row["round_trip_counts"], "round trip counts").values()
            )
        ):
            raise ValueError("Relative-Volume Drift 001 session execution invariant differs")

        values = {
            key: _canonical_decimal(row.get(key), f"session {key}") for key in accounting_fields
        }
        ending_equity = _canonical_decimal(row.get("ending_equity"), "session ending equity")
        decoded_symbols = {
            key: {
                symbol: _canonical_decimal(
                    _mapping(row.get(key), f"session {key}").get(symbol),
                    f"session {key}.{symbol}",
                )
                for symbol in symbols
            }
            for key in symbol_fields
        }
        if (
            not _accounting_values_match(
                values["execution_friction"],
                values["adverse_slippage"] + values["regulatory_fees"],
            )
            or not _accounting_values_match(
                values["net_profit_loss"],
                values["gross_profit_loss"] - values["execution_friction"],
            )
            or values["gross_profitable_trade_profit"] < _ZERO
            or values["holding_bars_sum"] < _ZERO
        ):
            raise ValueError("Relative-Volume Drift 001 session accounting differs")
        for symbol in symbols:
            if not _accounting_values_match(
                decoded_symbols["symbol_net_profit_loss"][symbol],
                decoded_symbols["symbol_gross_profit_loss"][symbol]
                - decoded_symbols["symbol_adverse_slippage"][symbol]
                - decoded_symbols["symbol_regulatory_fees"][symbol],
            ):
                raise ValueError("Relative-Volume Drift 001 session symbol accounting differs")
        for key, total_key in symbol_fields.items():
            if not _accounting_values_match(
                sum(decoded_symbols[key].values(), _ZERO), values[total_key]
            ):
                raise ValueError("Relative-Volume Drift 001 session symbol total differs")
        if not _accounting_values_match(
            values["gross_profitable_trade_profit"],
            sum(
                (
                    max(value, _ZERO)
                    for value in decoded_symbols["symbol_gross_profit_loss"].values()
                ),
                _ZERO,
            ),
        ):
            raise ValueError("Relative-Volume Drift 001 profitable gross differs")
        if active:
            if values["holding_bars_sum"] != Decimal("48"):
                raise ValueError("Relative-Volume Drift 001 fixed holding period differs")
        elif any(values[key] != _ZERO for key in accounting_fields):
            raise ValueError("Relative-Volume Drift 001 inactive session has performance")

        for key in accounting_fields:
            aggregate_values[key] += values[key]
        for key in symbol_fields:
            for symbol in symbols:
                aggregate_symbols[key][symbol] += decoded_symbols[key][symbol]
        row_net.append(values["net_profit_loss"])
        ending_equities.append(ending_equity)
        ledger_fill_count += sum(
            cast(int, value) for value in _mapping(row["fill_counts"], "fill counts").values()
        )
        ledger_round_trip_count += _integer_value(
            row.get("completed_round_trips"), "session round trips"
        )

    if not ledger or session_days != sorted(set(session_days)):
        raise ValueError("Relative-Volume Drift 001 session chronology differs")

    execution = _mapping(specification.get("execution"), "run execution")
    initial_cash = _required_report_decimal(report, "initial_cash")
    source_initial_cash = _canonical_decimal(execution.get("initial_cash"), "initial cash")
    if initial_cash <= _ZERO or not _accounting_values_match(initial_cash, source_initial_cash):
        raise ValueError("Relative-Volume Drift 001 initial cash differs")
    running_equity = initial_cash
    for net_value, ending_equity in zip(row_net, ending_equities, strict=True):
        running_equity += net_value
        if not _accounting_values_match(running_equity, ending_equity):
            raise ValueError("Relative-Volume Drift 001 session equity path differs")

    final_equity = ending_equities[-1]
    peak = initial_cash
    max_drawdown = _ZERO
    for ending_equity in ending_equities:
        peak = max(peak, ending_equity)
        max_drawdown = max(
            max_drawdown,
            (peak - ending_equity) / peak if peak else _ZERO,
        )
    expected_total_return = (final_equity - initial_cash) / initial_cash

    if (
        ledger_round_trip_count != completed
        or ledger_fill_count != fill_count
        or sum(row.get("disposition") == "active" for row in ledger) != active_count
        or _report_count(report, "lookback_ineligible_session_count")
        != sum(row.get("disposition") == "lookback-ineligible" for row in ledger)
        or _report_count(report, "hold_capacity_ineligible_session_count")
        != sum(row.get("disposition") == "hold-capacity-ineligible" for row in ledger)
        or _report_count(report, "signal_eligible_session_count")
        != sum(row.get("signal_eligible") is True for row in ledger)
    ):
        raise ValueError("Relative-Volume Drift 001 session aggregate differs")

    for key in accounting_fields:
        _require_metric_match(report, key, aggregate_values[key])
    _require_metric_match(report, "final_equity", final_equity)
    _require_metric_match(report, "total_return", expected_total_return)
    _require_metric_match(report, "max_drawdown", max_drawdown)
    _require_metric_match(
        report,
        "average_round_trips_per_session",
        Decimal(completed) / Decimal(session_count),
    )
    _require_metric_match(
        report,
        "cost_to_gross_profit",
        (
            aggregate_values["execution_friction"]
            / aggregate_values["gross_profitable_trade_profit"]
            if aggregate_values["gross_profitable_trade_profit"] > _ZERO
            else None
        ),
    )
    _require_metric_match(
        report,
        "average_gross_trade_edge_bps",
        (aggregate_values["gross_trade_edge_bps_sum"] / Decimal(completed) if completed else None),
    )
    _require_metric_match(
        report,
        "average_holding_bars",
        aggregate_values["holding_bars_sum"] / Decimal(completed) if completed else None,
    )

    bucket_values = _mapping(
        metrics.get("participation_bucket_net_profit_loss"),
        "participation bucket profit",
    )
    if set(bucket_values) != set(buckets):
        raise ValueError("Relative-Volume Drift 001 participation buckets differ")
    decoded_buckets = {
        bucket: _canonical_decimal(bucket_values[bucket], f"participation bucket {bucket}")
        for bucket in buckets
    }
    expected_buckets = {
        bucket: sum(
            (
                value
                for row, value in zip(ledger, row_net, strict=True)
                if row.get("participation_bucket") == bucket
            ),
            _ZERO,
        )
        for bucket in buckets
    }
    if any(
        not _accounting_values_match(decoded_buckets[bucket], expected_buckets[bucket])
        for bucket in buckets
    ):
        raise ValueError("Relative-Volume Drift 001 participation bucket total differs")

    detail_symbol_values: dict[str, dict[str, Decimal]] = {}
    for detail_key in symbol_fields:
        raw_values = _mapping(details.get(detail_key), detail_key)
        if set(raw_values) != set(symbols):
            raise ValueError("Relative-Volume Drift 001 detail symbol fields differ")
        detail_symbol_values[detail_key] = {
            symbol: _canonical_decimal(raw_values[symbol], f"{detail_key}.{symbol}")
            for symbol in symbols
        }
        if any(
            not _accounting_values_match(
                detail_symbol_values[detail_key][symbol],
                aggregate_symbols[detail_key][symbol],
            )
            for symbol in symbols
        ):
            raise ValueError("Relative-Volume Drift 001 detail symbol total differs")
    gross_less_friction = _canonical_decimal(
        details.get("gross_profit_loss_minus_execution_friction"),
        "gross less friction",
    )
    if not _accounting_values_match(
        gross_less_friction,
        aggregate_values["gross_profit_loss"] - aggregate_values["execution_friction"],
    ):
        raise ValueError("Relative-Volume Drift 001 detail accounting differs")

    _require_metric_match(
        report,
        "positive_profit_symbol_concentration",
        _positive_concentration(tuple(detail_symbol_values["symbol_net_profit_loss"].values())),
    )
    _require_metric_match(
        report,
        "positive_profit_session_concentration",
        _positive_concentration(tuple(row_net)),
    )
    _require_metric_match(
        report,
        "positive_profit_period_concentration",
        _positive_concentration((sum(row_net, _ZERO),)),
    )
    _require_metric_match(
        report,
        "positive_profit_participation_bucket_concentration",
        _positive_concentration(tuple(expected_buckets.values())),
    )
    benchmarks = _mapping(details.get("benchmarks"), "benchmark returns")
    if set(benchmarks) != {
        "qqq_continuous",
        "spy_continuous",
        "fixed_50_50_continuous",
        "cash",
    }:
        raise ValueError("Relative-Volume Drift 001 benchmark fields differ")
    for value in benchmarks.values():
        decode_canonical_metric(value)
    execution = _mapping(report.get("execution_evidence"), "execution evidence")
    expected_execution_keys = {
        "decision_trace_fingerprint",
        "transition_trace_fingerprint",
        "fill_trace_fingerprint",
        "round_trip_fingerprint",
        "daily_fee_ledger_fingerprint",
    }
    if set(execution) != expected_execution_keys or any(
        execution[key] != details.get(key) for key in expected_execution_keys
    ):
        raise ValueError("Relative-Volume Drift 001 execution evidence differs")


def _integer_value(value: object, label: str) -> int:
    decoded = decode_canonical_metric(value)
    if isinstance(decoded, bool) or not isinstance(decoded, int):
        raise ValueError(f"Relative-Volume Drift 001 {label} must be an integer")
    return decoded


def _final_markdown(report: Mapping[str, Any], report_sha256: str) -> str:
    counts = _mapping(report.get("counts"), "final counts")
    protected = _mapping(report.get("protected_access"), "protected access")
    lines = [
        "# Intraday Relative-Volume Drift 001 final report",
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
        "autonomous_program_sha256",
        "autonomous_program_fingerprint",
        "source_state_sha256",
        "source_state_fingerprint",
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
        raise ValueError("Relative-Volume Drift 001 final cohort differs")
    if (
        set(value) != expected_keys
        or value.get("schema_version") != FINAL_REPORT_SCHEMA
        or value.get("program_id") != PROGRAM_ID
        or (source_commit is not None and value.get("source_commit") != source_commit)
        or value.get("plan_sha256") != PLAN_SHA256
        or value.get("plan_fingerprint") != PLAN_FINGERPRINT
        or value.get("autonomous_program_sha256") != AUTONOMOUS_PROGRAM_SHA256
        or value.get("autonomous_program_fingerprint") != AUTONOMOUS_PROGRAM_FINGERPRINT
        or value.get("source_state_sha256") != SOURCE_STATE_SHA256
        or value.get("source_state_fingerprint") != SOURCE_STATE_FINGERPRINT
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
        raise ValueError("Relative-Volume Drift 001 final report differs")
    return value


def _validate_final_evidence(runtime: Path, report: Mapping[str, Any]) -> None:
    database = _mapping(report.get("runtime_database"), "runtime database")
    if database.get("path") != DATABASE_NAME or database.get("sha256") != _sha256_path(
        runtime / DATABASE_NAME
    ):
        raise ValueError("Relative-Volume Drift 001 runtime database differs")
    freeze_evidence = report.get("final_freeze")
    if freeze_evidence is None:
        return
    evidence = _mapping(freeze_evidence, "final freeze evidence")
    relative = _required_text(evidence.get("path"), "freeze path")
    if relative != "final-freeze.json":
        raise ValueError("Relative-Volume Drift 001 final freeze path differs")
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
            "source_state_sha256": SOURCE_STATE_SHA256,
            "source_state_fingerprint": SOURCE_STATE_FINGERPRINT,
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
        raise ValueError("Relative-Volume Drift 001 final freeze differs")
    canonical_reports: list[Mapping[str, Any]] = []
    for item in all_runs:
        evidence_row = _mapping(item, "runtime run evidence")
        relative_report = _required_text(evidence_row.get("report_path"), "runtime report path")
        report_path = runtime / relative_report
        raw = report_path.read_bytes()
        if evidence_row.get("status") != "completed" or hashlib.sha256(
            raw
        ).hexdigest() != evidence_row.get("report_sha256"):
            raise ValueError("Relative-Volume Drift 001 terminal run evidence differs")
        run_report = _mapping(json.loads(raw), "terminal run report")
        if (
            run_report.get("report_fingerprint") != evidence_row.get("report_fingerprint")
            or run_report.get("run_id") != evidence_row.get("run_id")
            or run_report.get("source_commit") != report.get("source_commit")
        ):
            raise ValueError("Relative-Volume Drift 001 terminal report identity differs")
        canonical_reports.append(run_report)
    repository = Path(__file__).resolve().parents[2]
    plan_object = load_intraday_relative_volume_drift_001_plan(repository)
    recomputed, recomputed_cohort = _recompute_terminal_screening(plan_object, canonical_reports)
    expected_cohort = [
        _configuration_summary(
            next(
                configuration
                for configuration in plan_object.configurations
                if configuration.candidate_id == candidate_id
            )
        )
        for candidate_id in recomputed_cohort
    ]
    if (
        canonicalize(screened) != canonicalize(recomputed)
        or canonicalize(cohort) != canonicalize(expected_cohort)
        or report.get("cohort") != cohort
    ):
        raise ValueError("Relative-Volume Drift 001 terminal semantic recomputation differs")


def _run_report(
    specification: Mapping[str, object],
    result: Exposed002ReplayResult,
    period: RelativeVolumePeriod,
    bars: Sequence[OHLCVBar],
    configuration: RelativeVolumeConfiguration,
) -> dict[str, object]:
    """Add one reconciled row for every evaluated ordinary session."""
    payload = _source_run_report(specification, result, cast(Any, period))
    payload.pop("report_fingerprint")
    metrics = dict(_mapping(payload["metrics"], "metrics"))
    details = dict(_mapping(payload["details"], "details"))
    sessions = tuple(expected_sessions(period.evaluation_start, period.evaluation_end))
    all_days = tuple(expected_sessions(period.context_start, period.evaluation_end))
    grouped: dict[date, dict[Symbol, tuple[OHLCVBar, ...]]] = {}
    for day in all_days:
        grouped[day] = {
            symbol: tuple(
                sorted(
                    (
                        bar
                        for bar in bars
                        if bar.symbol == symbol and _account_day(bar.timestamp) == day
                    ),
                    key=lambda bar: bar.timestamp,
                )
            )
            for symbol in (_QQQ, _SPY)
        }
        expected = expected_bar_timestamps(
            datetime.combine(day, datetime.min.time(), UTC),
            datetime.combine(day, datetime.max.time(), UTC),
            Timeframe.FIVE_MINUTES,
        )
        if any(
            tuple(bar.timestamp for bar in grouped[day][symbol]) != expected
            for symbol in (_QQQ, _SPY)
        ):
            raise ValueError("Relative-Volume Drift 001 session bars differ from XNYS")

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
        raise ValueError("Relative-Volume Drift 001 requires one daily fee ledger per session")
    ending_equity = {
        _account_day(point.timestamp): point.equity
        for point in result.equity_curve
        if _account_day(point.timestamp) in sessions
    }
    if set(ending_equity) != set(sessions):
        raise ValueError("Relative-Volume Drift 001 session equity differs")

    ledger: list[dict[str, object]] = []
    signal_trace: list[dict[str, object]] = []
    for day in sessions:
        prior = tuple(grouped[value] for value in all_days if value < day)
        row, trace = _session_row(
            day,
            grouped[day],
            prior,
            configuration,
            evaluation_fills,
            evaluation_trades,
            fees.get(day),
            ending_equity[day],
            int(_mapping(specification["cost_model"], "cost model")["execution_delay_bars"]),
        )
        ledger.append(row)
        signal_trace.append(trace)
    if len(ledger) != period.session_count:
        raise ValueError("Relative-Volume Drift 001 session count differs")

    net = sum((Decimal(cast(Any, row["net_profit_loss"])) for row in ledger), _ZERO)
    gross = sum((Decimal(cast(Any, row["gross_profit_loss"])) for row in ledger), _ZERO)
    friction = sum((Decimal(cast(Any, row["execution_friction"])) for row in ledger), _ZERO)
    if (
        abs(net - Decimal(cast(Any, metrics["net_profit_loss"]))).quantize(_ACCOUNTING_PRECISION)
        != _ZERO
        or abs(gross - friction - net).quantize(_ACCOUNTING_PRECISION) != _ZERO
    ):
        raise ValueError("Relative-Volume Drift 001 session accounting does not reconcile")

    buckets = {
        bucket: sum(
            (
                Decimal(cast(Any, row["net_profit_loss"]))
                for row in ledger
                if row["participation_bucket"] == bucket
            ),
            _ZERO,
        )
        for bucket in (
            "participation-q-1-to-1-2",
            "participation-q-1-2-to-1-5",
            "participation-q-1-5-plus",
        )
    }
    active = sum(row["disposition"] == "active" for row in ledger)
    if (
        int(cast(Any, metrics["completed_round_trips"])) != active * 2
        or int(cast(Any, metrics["fill_count"])) != active * 4
    ):
        raise ValueError("Relative-Volume Drift 001 session execution does not reconcile")

    signal_fingerprint = fingerprint(signal_trace)
    metrics.update(
        {
            "signal_eligible_session_count": sum(
                cast(bool, row["signal_eligible"]) for row in ledger
            ),
            "lookback_ineligible_session_count": sum(
                row["disposition"] == "lookback-ineligible" for row in ledger
            ),
            "hold_capacity_ineligible_session_count": sum(
                row["disposition"] == "hold-capacity-ineligible" for row in ledger
            ),
            "active_session_count": active,
            "session_disposition_counts": {
                code: sum(row["disposition"] == code for row in ledger)
                for code in (
                    "active",
                    "lookback-ineligible",
                    "hold-capacity-ineligible",
                    "inactive-joint-return",
                    "inactive-joint-relative-volume",
                )
            },
            "positive_profit_session_concentration": _positive_concentration(
                tuple(Decimal(cast(Any, row["net_profit_loss"])) for row in ledger)
            ),
            "positive_profit_period_concentration": _positive_concentration((net,)),
            "participation_bucket_net_profit_loss": buckets,
            "positive_profit_participation_bucket_concentration": _positive_concentration(
                tuple(buckets.values())
            ),
            "signal_trace_mismatch_count": 0,
        }
    )
    benchmarks = _benchmark_returns(bars, period)
    details.update(
        {
            "session_ledger": ledger,
            "signal_trace": signal_trace,
            "benchmarks": benchmarks,
        }
    )
    payload.update(
        {
            "schema_version": RUN_REPORT_SCHEMA,
            "program_id": PROGRAM_ID,
            "run_id": _run_id(specification),
            "metrics": metrics,
            "details": details,
            "signal_trace_fingerprint": signal_fingerprint,
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
            "autonomous_program_sha256": specification["autonomous_program_sha256"],
            "autonomous_program_fingerprint": specification["autonomous_program_fingerprint"],
            "source_state_sha256": specification["source_state_sha256"],
            "source_state_fingerprint": specification["source_state_fingerprint"],
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
    current: Mapping[Symbol, Sequence[OHLCVBar]],
    prior: Sequence[Mapping[Symbol, Sequence[OHLCVBar]]],
    configuration: RelativeVolumeConfiguration,
    fills: Sequence[Any],
    trades: Sequence[Any],
    daily: Any,
    ending_equity: Decimal,
    delay: int,
) -> tuple[dict[str, object], dict[str, object]]:
    horizon = configuration.observation_horizon_bars
    expected = expected_bar_timestamps(
        datetime.combine(day, datetime.min.time(), UTC),
        datetime.combine(day, datetime.max.time(), UTC),
        Timeframe.FIVE_MINUTES,
    )
    if (
        not expected
        or any(
            tuple(bar.timestamp for bar in current[symbol]) != expected for symbol in (_QQQ, _SPY)
        )
        or delay not in {1, 2, 3}
    ):
        raise ValueError("Relative-Volume Drift 001 session or delay differs")

    lookback = len(prior) >= 10
    capacity = len(expected) >= horizon + 27
    signal_eligible = lookback and capacity
    baseline_days: tuple[str, ...] = ()
    prior_volumes: dict[str, tuple[int, ...]] = {"QQQ": (), "SPY": ()}
    baselines: dict[str, Decimal | None] = {"QQQ": None, "SPY": None}
    current_volumes: dict[str, int | None] = {"QQQ": None, "SPY": None}
    relative_volumes: dict[str, Decimal | None] = {"QQQ": None, "SPY": None}
    returns: dict[str, Decimal | None] = {"QQQ": None, "SPY": None}
    return_predicates: dict[str, bool | None] = {"QQQ": None, "SPY": None}
    relative_volume_predicates: dict[str, bool | None] = {"QQQ": None, "SPY": None}
    joint_return_passed = joint_relative_volume_passed = None
    joint_relative_volume = participation_strength = None
    participation_bucket = None
    qualified = False
    entry_decision = planned_exit_decision = None

    if not lookback:
        reason = "lookback-ineligible"
    elif not capacity:
        reason = "hold-capacity-ineligible"
    else:
        baseline_sessions = tuple(prior[-10:])
        baseline_days = tuple(
            baseline[_SPY][0].timestamp.astimezone(_NEW_YORK).date().isoformat()
            for baseline in baseline_sessions
        )
        for symbol in (_QQQ, _SPY):
            values = tuple(
                sum(bar.volume for bar in baseline[symbol][:horizon])
                for baseline in baseline_sessions
            )
            if any(len(baseline[symbol]) < horizon for baseline in baseline_sessions):
                raise ValueError("Relative-Volume Drift 001 baseline lacks the horizon")
            ordered = sorted(values)
            median_value = (Decimal(ordered[4]) + Decimal(ordered[5])) / 2
            if median_value <= _ZERO:
                raise ValueError("Relative-Volume Drift 001 same-clock baseline must be positive")
            key = symbol.value
            prior_volumes[key] = values
            baselines[key] = median_value
            current_value = sum(bar.volume for bar in current[symbol][:horizon])
            current_volumes[key] = current_value
            relative_volume = Decimal(current_value) / median_value
            observed_return = _BPS * (
                current[symbol][horizon - 1].close / current[symbol][0].open - 1
            )
            relative_volumes[key] = relative_volume
            returns[key] = observed_return
            return_predicates[key] = observed_return >= Decimal("15")
            relative_volume_predicates[key] = (
                relative_volume >= configuration.minimum_joint_relative_volume
            )
        joint_relative_volume = min(
            cast(Decimal, relative_volumes["QQQ"]),
            cast(Decimal, relative_volumes["SPY"]),
        )
        joint_return_passed = all(cast(bool, value) for value in return_predicates.values())
        joint_relative_volume_passed = all(
            cast(bool, value) for value in relative_volume_predicates.values()
        )
        qualified = joint_return_passed and joint_relative_volume_passed
        if not joint_return_passed:
            reason = "inactive-joint-return"
        elif not joint_relative_volume_passed:
            reason = "inactive-joint-relative-volume"
        else:
            reason = None
            participation_strength = (
                joint_relative_volume / configuration.minimum_joint_relative_volume
            )
            participation_bucket = _bucket(participation_strength)
            entry_decision = current[_SPY][horizon - 1].timestamp + Timeframe.FIVE_MINUTES.duration
            planned_exit_decision = (
                current[_SPY][horizon + 23].timestamp + Timeframe.FIVE_MINUTES.duration
            )

    session_fills = tuple(fill for fill in fills if _account_day(fill.fill_timestamp) == day)
    session_trades = tuple(trade for trade in trades if _account_day(trade.entry_timestamp) == day)
    by_symbol_fills = {
        symbol: tuple(fill for fill in session_fills if fill.symbol == symbol)
        for symbol in (_QQQ, _SPY)
    }
    by_symbol_trades = {
        symbol: tuple(trade for trade in session_trades if trade.symbol == symbol)
        for symbol in (_QQQ, _SPY)
    }
    entries: dict[Symbol, Any] = {}
    exits: dict[Symbol, Any] = {}
    if qualified:
        expected_entry_fill = expected[horizon - 1 + delay]
        expected_exit_fill = expected[horizon + 23 + delay]
        for symbol in (_QQQ, _SPY):
            symbol_entries = tuple(fill for fill in by_symbol_fills[symbol] if fill.quantity > 0)
            symbol_exits = tuple(fill for fill in by_symbol_fills[symbol] if fill.quantity < 0)
            symbol_trades = by_symbol_trades[symbol]
            if len(symbol_entries) != 1 or len(symbol_exits) != 1 or len(symbol_trades) != 1:
                raise ValueError("Relative-Volume Drift 001 active session execution differs")
            entry, exit_, trade = symbol_entries[0], symbol_exits[0], symbol_trades[0]
            if (
                entry.decision_timestamp != entry_decision
                or exit_.decision_timestamp != planned_exit_decision
                or entry.fill_timestamp != expected_entry_fill
                or exit_.fill_timestamp != expected_exit_fill
                or trade.entry_timestamp != expected_entry_fill
                or trade.exit_timestamp != expected_exit_fill
                or trade.holding_bars != Decimal("24")
            ):
                raise ValueError("Relative-Volume Drift 001 active session timing differs")
            entries[symbol], exits[symbol] = entry, exit_
        if len(session_fills) != 4 or len(session_trades) != 2:
            raise ValueError("Relative-Volume Drift 001 active session count differs")
    else:
        if session_fills or session_trades:
            raise ValueError("Relative-Volume Drift 001 inactive session has execution")

    if daily is None or date.fromisoformat(daily.account_day) != day:
        raise ValueError("Relative-Volume Drift 001 daily fee ledger differs")
    symbol_fees = dict(daily.by_symbol)
    if set(symbol_fees) != {_QQQ, _SPY} or sum(symbol_fees.values(), _ZERO) != daily.charges.total:
        raise ValueError("Relative-Volume Drift 001 symbol fee ledger differs")
    symbol_gross = {
        symbol: sum((trade.gross_profit for trade in by_symbol_trades[symbol]), _ZERO)
        for symbol in (_QQQ, _SPY)
    }
    symbol_slippage = {
        symbol: sum((fill.adverse_slippage for fill in by_symbol_fills[symbol]), _ZERO)
        for symbol in (_QQQ, _SPY)
    }
    symbol_net = {
        symbol: symbol_gross[symbol] - symbol_slippage[symbol] - symbol_fees[symbol]
        for symbol in (_QQQ, _SPY)
    }
    gross = sum(symbol_gross.values(), _ZERO)
    slip = sum(symbol_slippage.values(), _ZERO)
    fees = daily.charges.total
    if not qualified and (gross != _ZERO or slip != _ZERO or fees != _ZERO):
        raise ValueError("Relative-Volume Drift 001 inactive session has accounting")

    trace = {
        "session": day.isoformat(),
        "candidate_id": configuration.candidate_id,
        "observation_horizon_bars": horizon,
        "minimum_joint_relative_volume": configuration.minimum_joint_relative_volume,
        "baseline_session_days": baseline_days,
        "prior_cumulative_volumes": prior_volumes,
        "baseline_medians": baselines,
        "current_cumulative_volumes": current_volumes,
        "relative_volumes": relative_volumes,
        "returns_bps": returns,
        "return_predicates": return_predicates,
        "relative_volume_predicates": relative_volume_predicates,
        "joint_return_passed": joint_return_passed,
        "joint_relative_volume_passed": joint_relative_volume_passed,
        "joint_relative_volume": joint_relative_volume,
        "participation_strength": participation_strength,
        "participation_bucket": participation_bucket,
        "qualifying_signal": qualified,
        "inactive_reason": None if qualified else reason,
        "entry_decision_timestamp": entry_decision,
        "planned_exit_decision_timestamp": planned_exit_decision,
    }
    return (
        {
            **trace,
            "disposition": "active" if qualified else cast(str, reason),
            "lookback_eligible": lookback,
            "hold_capacity": capacity,
            "signal_eligible": signal_eligible,
            "active": qualified,
            "entry_fill_timestamp": (None if not qualified else entries[_SPY].fill_timestamp),
            "exit_fill_timestamp": (None if not qualified else exits[_SPY].fill_timestamp),
            "fill_counts": {symbol.value: len(by_symbol_fills[symbol]) for symbol in (_QQQ, _SPY)},
            "round_trip_counts": {
                symbol.value: len(by_symbol_trades[symbol]) for symbol in (_QQQ, _SPY)
            },
            "completed_round_trips": len(session_trades),
            "symbol_gross_profit_loss": {
                symbol.value: symbol_gross[symbol] for symbol in (_QQQ, _SPY)
            },
            "symbol_adverse_slippage": {
                symbol.value: symbol_slippage[symbol] for symbol in (_QQQ, _SPY)
            },
            "symbol_regulatory_fees": {
                symbol.value: symbol_fees[symbol] for symbol in (_QQQ, _SPY)
            },
            "symbol_net_profit_loss": {symbol.value: symbol_net[symbol] for symbol in (_QQQ, _SPY)},
            "gross_profit_loss": gross,
            "gross_profitable_trade_profit": sum(
                (max(trade.gross_profit, _ZERO) for trade in session_trades), _ZERO
            ),
            "gross_trade_edge_bps_sum": sum(
                (
                    trade.gross_profit / (trade.quantity * trade.entry_market_price) * _BPS
                    for trade in session_trades
                ),
                _ZERO,
            ),
            "holding_bars_sum": sum((trade.holding_bars for trade in session_trades), _ZERO),
            "adverse_slippage": slip,
            "regulatory_fees": fees,
            "execution_friction": slip + fees,
            "net_profit_loss": gross - slip - fees,
            "ending_equity": ending_equity,
        },
        trace,
    )


def _bucket(value: Decimal) -> str:
    if value < Decimal("1.2"):
        return "participation-q-1-to-1-2"
    if value < Decimal("1.5"):
        return "participation-q-1-2-to-1-5"
    return "participation-q-1-5-plus"


def _benchmark_returns(
    bars: Sequence[OHLCVBar], period: RelativeVolumePeriod
) -> dict[str, Decimal]:
    values: dict[str, Decimal] = {}
    for symbol in (_QQQ, _SPY):
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
        if not evaluation:
            raise ValueError("Relative-Volume Drift 001 benchmark bars are missing")
        values[f"{symbol.value.lower()}_continuous"] = evaluation[-1].close / evaluation[0].open - 1
    values["fixed_50_50_continuous"] = (values["qqq_continuous"] + values["spy_continuous"]) / 2
    values["cash"] = _ZERO
    return values


def _required_report_decimal(report: Mapping[str, Any], key: str) -> Decimal:
    value = _report_metric_strict(report, key)
    if value is None:
        raise ValueError(f"required report metric is null: {key}")
    return value


def _aggregate_relative_volume_reports(
    reports: Sequence[Mapping[str, Any]],
) -> dict[str, object]:
    if not reports:
        raise ValueError("Relative-Volume Drift 001 aggregate requires reports")
    completed = sum(_report_count(report, "completed_round_trips") for report in reports)
    sessions = sum(_report_count(report, "session_count") for report in reports)
    gross = sum(
        (_required_report_decimal(report, "gross_profit_loss") for report in reports),
        _ZERO,
    )
    profitable = sum(
        (_required_report_decimal(report, "gross_profitable_trade_profit") for report in reports),
        _ZERO,
    )
    friction = sum(
        (_required_report_decimal(report, "execution_friction") for report in reports),
        _ZERO,
    )
    net = sum(
        (_required_report_decimal(report, "net_profit_loss") for report in reports),
        _ZERO,
    )
    edge_sum = sum(
        (_required_report_decimal(report, "gross_trade_edge_bps_sum") for report in reports),
        _ZERO,
    )
    holding_sum = sum(
        (_required_report_decimal(report, "holding_bars_sum") for report in reports),
        _ZERO,
    )
    aggregate_return = sum(
        (_required_report_decimal(report, "total_return") for report in reports),
        _ZERO,
    )
    for report in reports:
        validate_accounting(_mapping(report.get("metrics"), "report metrics"))
        if _required_report_decimal(report, "accounting_identity_error") != _ZERO:
            raise ValueError("Relative-Volume Drift 001 report accounting differs")

    ledger: list[Mapping[str, Any]] = []
    symbol_net = {"QQQ": _ZERO, "SPY": _ZERO}
    for report in reports:
        details = _mapping(report.get("details"), "report details")
        raw_ledger = details.get("session_ledger")
        if not isinstance(raw_ledger, list):
            raise ValueError("Relative-Volume Drift 001 session ledger is missing")
        ledger.extend(_mapping(row, "session ledger row") for row in raw_ledger)
        raw_symbol = _mapping(details.get("symbol_net_profit_loss"), "symbol net profit")
        if set(raw_symbol) != {"QQQ", "SPY"}:
            raise ValueError("Relative-Volume Drift 001 symbol profit fields differ")
        for symbol in symbol_net:
            value = decode_canonical_metric(raw_symbol[symbol])
            if value is None:
                raise ValueError("Relative-Volume Drift 001 symbol profit is null")
            symbol_net[symbol] += Decimal(value)

    session_ids = tuple(_text(row, "session") for row in ledger)
    if len(set(session_ids)) != len(session_ids) or len(ledger) != sessions:
        raise ValueError("Relative-Volume Drift 001 aggregate sessions collide")
    row_net = tuple(
        Decimal(cast(Decimal | int, decode_canonical_metric(row.get("net_profit_loss"))))
        for row in ledger
    )
    if abs(sum(row_net, _ZERO) - net).quantize(_ACCOUNTING_PRECISION) != _ZERO:
        raise ValueError("Relative-Volume Drift 001 aggregate ledger accounting differs")

    buckets = {
        bucket: sum(
            (
                Decimal(
                    cast(
                        Decimal | int,
                        decode_canonical_metric(row.get("net_profit_loss")),
                    )
                )
                for row in ledger
                if row.get("participation_bucket") == bucket
            ),
            _ZERO,
        )
        for bucket in (
            "participation-q-1-to-1-2",
            "participation-q-1-2-to-1-5",
            "participation-q-1-5-plus",
        )
    }
    result: dict[str, object] = {
        "fold_count": len(reports),
        "total_return": aggregate_return,
        "worst_fold_return": min(
            _required_report_decimal(report, "total_return") for report in reports
        ),
        "max_drawdown": max(_required_report_decimal(report, "max_drawdown") for report in reports),
        "completed_round_trips": completed,
        "session_count": sessions,
        "average_round_trips_per_session": Decimal(completed) / Decimal(sessions),
        "gross_profit_loss": gross,
        "gross_profitable_trade_profit": profitable,
        "execution_friction": friction,
        "net_profit_loss": net,
        "cost_to_gross_profit": friction / profitable if profitable > 0 else None,
        "gross_trade_edge_bps_sum": edge_sum,
        "average_gross_trade_edge_bps": (edge_sum / Decimal(completed) if completed else None),
        "holding_bars_sum": holding_sum,
        "average_holding_bars": (holding_sum / Decimal(completed) if completed else None),
        "symbol_net_profit_loss": symbol_net,
        "positive_profit_symbol_concentration": _positive_concentration(tuple(symbol_net.values())),
        "session_ledger": ledger,
        "active_session_count": sum(row.get("disposition") == "active" for row in ledger),
        "signal_eligible_session_count": sum(row.get("signal_eligible") is True for row in ledger),
        "lookback_ineligible_session_count": sum(
            row.get("disposition") == "lookback-ineligible" for row in ledger
        ),
        "hold_capacity_ineligible_session_count": sum(
            row.get("disposition") == "hold-capacity-ineligible" for row in ledger
        ),
        "positive_profit_session_concentration": _positive_concentration(row_net),
        "positive_profit_period_concentration": _positive_concentration(
            tuple(_required_report_decimal(report, "net_profit_loss") for report in reports)
        ),
        "participation_bucket_net_profit_loss": buckets,
        "positive_profit_participation_bucket_concentration": _positive_concentration(
            tuple(buckets.values())
        ),
        "signal_trace_mismatch_count": sum(
            _report_count(report, "signal_trace_mismatch_count") for report in reports
        ),
        "accounting_identity_error": abs(gross - friction - net).quantize(_ACCOUNTING_PRECISION),
    }
    return result


_aggregate_reports = _aggregate_relative_volume_reports


def _pair_values(
    normal: Mapping[str, Any], zero: Mapping[str, Any], normal_name: str, zero_name: str
) -> dict[str, Decimal | int | None]:
    values = {f"{normal_name}.{key}": value for key, value in _report_scalars(normal).items()}
    values.update({f"{zero_name}.{key}": value for key, value in _report_scalars(zero).items()})
    values[f"{normal_name}.signal_trace_mismatch_count"] = (
        0 if normal["signal_trace_fingerprint"] == zero["signal_trace_fingerprint"] else 1
    )
    return values


def _positive_fold(report: Mapping[str, Any]) -> bool:
    return (
        _required_report_decimal(report, "net_profit_loss") > 0
        and _required_report_decimal(report, "total_return") > 0
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
            (_report_count(report, "active_session_count") for report in positive),
            default=None,
        ),
        "worst_normal_fold_return": min(
            _required_report_decimal(report, "total_return") for report in normals
        ),
        "worst_normal_fold_drawdown": max(
            _required_report_decimal(report, "max_drawdown") for report in normals
        ),
    }
    for prefix, aggregate in (
        ("aggregate.normal", normal),
        ("aggregate.zero_cost_diagnostic", zero),
    ):
        for key, value in aggregate.items():
            if isinstance(value, Decimal | int) or value is None:
                values[f"{prefix}.{key}"] = value
    values.update(
        {f"final_exposed_may.normal.{key}": value for key, value in _report_scalars(final).items()}
    )
    return values


def _recompute_terminal_screening(
    plan: IntradayRelativeVolumeDrift001Plan,
    reports: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, object], tuple[str, ...]]:
    """Rebuild every reached gate and cohort from canonical run reports."""
    indexed: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for report in reports:
        _validate_run_report_semantics(report)
        specification = _mapping(report.get("specification"), "run specification")
        context = _mapping(specification.get("context"), "run context")
        key = (
            _text(context, "candidate_id"),
            _text(context, "period_id"),
            _text(context, "scenario_id"),
        )
        if key in indexed:
            raise ValueError("Relative-Volume Drift 001 duplicate canonical report identity")
        indexed[key] = report

    configurations = {item.candidate_id: item for item in plan.configurations}
    expected: set[tuple[str, str, str]] = set()

    def report_for(candidate: str, period: str, scenario: str) -> Mapping[str, Any]:
        key = (candidate, period, scenario)
        expected.add(key)
        try:
            return indexed[key]
        except KeyError as error:
            raise ValueError(
                "Relative-Volume Drift 001 required canonical report is missing"
            ) from error

    def normal_zero(candidate: str, period: str) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        normal = report_for(candidate, period, "normal")
        zero = report_for(candidate, period, "zero_cost_diagnostic")
        normal_execution = _mapping(normal.get("execution_evidence"), "normal execution evidence")
        zero_execution = _mapping(zero.get("execution_evidence"), "zero-cost execution evidence")
        if normal.get("signal_trace_fingerprint") != zero.get(
            "signal_trace_fingerprint"
        ) or normal_execution.get("decision_trace_fingerprint") != zero_execution.get(
            "decision_trace_fingerprint"
        ):
            raise ValueError("Relative-Volume Drift 001 paired canonical traces differ")
        return normal, zero

    payload = canonicalize(plan.payload)
    discovery_period = plan.periods[0]
    discovery_ledger: list[dict[str, object]] = []
    for configuration in plan.configurations:
        normal, zero = normal_zero(configuration.candidate_id, discovery_period.period_id)
        values = _pair_values(normal, zero, "normal", "zero_cost_diagnostic")
        gates = _strict_gate_results(_gates(payload, "discovery_screen", "gates"), values)
        discovery_ledger.append(
            {
                "candidate": _configuration_summary(configuration),
                "metrics": values,
                "gates": gates,
                "eligible": all(cast(bool, gate["passed"]) for gate in gates),
            }
        )
    discovery_selected = tuple(
        _text(cast(Mapping[str, Any], item["candidate"]), "candidate_id")
        for item in sorted(
            (item for item in discovery_ledger if item["eligible"]),
            key=lambda item: (
                -_strict_ledger_metric(item, "normal.total_return"),
                _strict_ledger_metric(item, "normal.positive_profit_session_concentration"),
                _strict_ledger_metric(item, "normal.cost_to_gross_profit"),
                _text(cast(Mapping[str, Any], item["candidate"]), "candidate_id"),
            ),
        )[:3]
    )
    discovery: dict[str, object] = {
        "ledger": discovery_ledger,
        "selected": discovery_selected,
    }

    periods = plan.periods[1:]
    walk_ledger: list[dict[str, object]] = []
    for candidate in discovery_selected:
        normals, zeros = zip(
            *(normal_zero(candidate, period.period_id) for period in periods),
            strict=True,
        )
        normal_aggregate = _aggregate_relative_volume_reports(normals)
        zero_aggregate = _aggregate_relative_volume_reports(zeros)
        positive = tuple(report for report in normals if _positive_fold(report))
        values = _walk_values(normals, normal_aggregate, zero_aggregate, positive)
        gates = _strict_gate_results(_gates(payload, "walk_forward_screen", "gates"), values)
        walk_ledger.append(
            {
                "candidate": _configuration_summary(configurations[candidate]),
                "metrics": values,
                "gates": gates,
                "eligible": all(cast(bool, gate["passed"]) for gate in gates),
            }
        )
    walk_selected = tuple(
        _text(cast(Mapping[str, Any], item["candidate"]), "candidate_id")
        for item in sorted(
            (item for item in walk_ledger if item["eligible"]),
            key=lambda item: (
                -_strict_ledger_metric(item, "positive_normal_fold_count"),
                -_strict_ledger_metric(item, "aggregate.normal.total_return"),
                _strict_ledger_metric(
                    item,
                    "aggregate.normal.positive_profit_session_concentration",
                ),
                _text(cast(Mapping[str, Any], item["candidate"]), "candidate_id"),
            ),
        )[:1]
    )
    walk: dict[str, object] = {"ledger": walk_ledger, "selected": walk_selected}

    stress_scenarios = (
        "stress_a",
        "stress_b",
        "normal-delay-2",
        "normal-delay-3",
    )
    stress_ledger: list[dict[str, object]] = []
    for candidate in walk_selected:
        normal_reports = tuple(
            report_for(candidate, period.period_id, "normal") for period in periods
        )
        normal_aggregate = _aggregate_relative_volume_reports(normal_reports)
        stress_values: dict[str, Decimal | int | None] = {}
        for scenario in stress_scenarios:
            scenario_reports = tuple(
                report_for(candidate, period.period_id, scenario) for period in periods
            )
            for scenario_report, normal_report in zip(
                scenario_reports, normal_reports, strict=True
            ):
                if scenario_report.get("signal_trace_fingerprint") != normal_report.get(
                    "signal_trace_fingerprint"
                ):
                    raise ValueError("Relative-Volume Drift 001 stress signal trace differs")
            aggregate = _aggregate_relative_volume_reports(scenario_reports)
            aggregate_net = Decimal(cast(Any, aggregate["net_profit_loss"]))
            normal_net = Decimal(cast(Any, normal_aggregate["net_profit_loss"]))
            stress_values[f"{scenario}.aggregate_total_return"] = Decimal(
                cast(Any, aggregate["total_return"])
            )
            stress_values[f"{scenario}.positive_fold_count"] = sum(
                _positive_fold(report) for report in scenario_reports
            )
            stress_values[f"{scenario}.normal_profit_retention"] = (
                aggregate_net / normal_net if normal_net > 0 else None
            )
        gates = _strict_gate_results(
            _gates(payload, "serious_candidate_screen", "stress_gates"),
            stress_values,
        )
        stress_ledger.append(
            {
                "candidate": _configuration_summary(configurations[candidate]),
                "metrics": stress_values,
                "gates": gates,
                "eligible": all(cast(bool, gate["passed"]) for gate in gates),
            }
        )
    stress_selected = tuple(
        _text(cast(Mapping[str, Any], item["candidate"]), "candidate_id")
        for item in stress_ledger
        if item["eligible"]
    )
    stress: dict[str, object] = {
        "ledger": stress_ledger,
        "selected": stress_selected,
    }

    before_neighbors = set(expected)
    if not stress_selected:
        neighbors: dict[str, object] = {
            "stage": "immediate-neighbor",
            "candidate_count": 0,
            "requested_run_specification_count": 0,
            "new_run_specification_count": 0,
            "ledger": [],
            "selected": (),
        }
        cohort: tuple[str, ...] = ()
    else:
        candidate = stress_selected[0]
        configuration = configurations[candidate]
        requested = {
            (neighbor, period.period_id, scenario)
            for neighbor in configuration.neighbor_ids
            for period in periods
            for scenario in ("normal", "zero_cost_diagnostic")
        }
        base_normal = _aggregate_relative_volume_reports(
            tuple(report_for(candidate, period.period_id, "normal") for period in periods)
        )
        joint = mismatch = 0
        retentions: list[Decimal] = []
        for neighbor in configuration.neighbor_ids:
            normals, zeros = zip(
                *(normal_zero(neighbor, period.period_id) for period in periods),
                strict=True,
            )
            normal = _aggregate_relative_volume_reports(normals)
            zero = _aggregate_relative_volume_reports(zeros)
            joint += (
                Decimal(cast(Any, normal["total_return"])) > 0
                and Decimal(cast(Any, normal["net_profit_loss"])) > 0
                and Decimal(cast(Any, zero["total_return"])) > 0
                and Decimal(cast(Any, zero["net_profit_loss"])) > 0
            )
            base_net = Decimal(cast(Any, base_normal["net_profit_loss"]))
            if base_net > 0:
                retentions.append(Decimal(cast(Any, normal["net_profit_loss"])) / base_net)
            mismatch += int(cast(Any, normal["signal_trace_mismatch_count"]))
        values = {
            "joint_positive_neighbor_fraction": Decimal(joint)
            / Decimal(len(configuration.neighbor_ids)),
            "median_neighbor_normal_profit_retention": (median(retentions) if retentions else None),
            "neighbor_signal_trace_mismatch_count": mismatch,
        }
        gates = _strict_gate_results(
            _gates(payload, "serious_candidate_screen", "neighbor_gates"),
            values,
        )
        eligible = all(cast(bool, gate["passed"]) for gate in gates)
        cohort = (candidate,) if eligible else ()
        neighbors = {
            "stage": "immediate-neighbor",
            "candidate_count": 1,
            "requested_run_specification_count": len(requested),
            "new_run_specification_count": len(requested - before_neighbors),
            "ledger": [
                {
                    "candidate": _configuration_summary(configuration),
                    "neighbor_ids": configuration.neighbor_ids,
                    "metrics": values,
                    "gates": gates,
                    "eligible": eligible,
                }
            ],
            "selected": cohort,
        }

    if set(indexed) != expected:
        raise ValueError(
            "Relative-Volume Drift 001 canonical report graph differs from reached stages"
        )
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
    plan: IntradayRelativeVolumeDrift001Plan,
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
        raise ValueError("Relative-Volume Drift 001 terminal screening differs")


def _load_launch_control(repository: Path, *, source_commit: str) -> Mapping[str, Any]:
    if REVIEWED_LAUNCH_CONTROL_SHA256 is None or REVIEWED_LAUNCH_CONTROL_FINGERPRINT is None:
        raise ValueError("Relative-Volume Drift 001 launch control is not hash-bound")
    path = repository / LAUNCH_CONTROL_RELATIVE_PATH
    if not path.is_file():
        raise ValueError("Relative-Volume Drift 001 launch control review is missing")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != REVIEWED_LAUNCH_CONTROL_SHA256:
        raise ValueError("Relative-Volume Drift 001 launch control SHA-256 differs")
    try:
        value = _mapping(json.loads(raw), "launch control review")
    except json.JSONDecodeError as error:
        raise ValueError("Relative-Volume Drift 001 launch control is invalid JSON") from error
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
        raise ValueError("Relative-Volume Drift 001 launch control differs")
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
        raise ValueError("Relative-Volume Drift 001 launch review identity differs")
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
        raise ValueError("Relative-Volume Drift 001 launch independent review differs")
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
        "source_state": {
            "path": SOURCE_STATE_RELATIVE_PATH.as_posix(),
            "sha256": SOURCE_STATE_SHA256,
            "fingerprint": SOURCE_STATE_FINGERPRINT,
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
        raise ValueError("Relative-Volume Drift 001 launch inputs differ")


def _verify_launch_implementation(repository: Path, value: Mapping[str, Any]) -> str:
    implementation = _mapping(value.get("implementation"), "launch implementation")
    _require_exact_keys(implementation, {"source_commit", "files"}, "launch implementation")
    source_commit = _validated_source_commit(implementation.get("source_commit"))
    files = implementation.get("files")
    if not isinstance(files, list) or len(files) != len(_LAUNCH_CONTROL_FILES):
        raise ValueError("Relative-Volume Drift 001 launch files differ")
    for item, expected_path in zip(files, _LAUNCH_CONTROL_FILES, strict=True):
        binding = _mapping(item, "launch implementation file")
        _require_exact_keys(binding, {"path", "sha256"}, "launch implementation file")
        if binding.get("path") != expected_path or binding.get("sha256") != _sha256_path(
            repository / expected_path
        ):
            raise ValueError("Relative-Volume Drift 001 implementation file differs")
    return source_commit


def _verify_launch_quality(value: Mapping[str, Any], source_commit: str) -> None:
    quality = _mapping(value.get("quality_gates"), "launch quality gates")
    _require_exact_keys(quality, {"source_commit", "results"}, "launch quality gates")
    results = quality.get("results")
    if quality.get("source_commit") != source_commit or not isinstance(results, list):
        raise ValueError("Relative-Volume Drift 001 launch quality gates differ")
    if len(results) != len(_LAUNCH_CONTROL_QUALITY_GATES):
        raise ValueError("Relative-Volume Drift 001 launch quality gate count differs")
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
            raise ValueError("Relative-Volume Drift 001 launch quality gate differs")
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
        equivalence.get("schema_version")
        != "intraday-relative-volume-drift-001-parallel-equivalence-v1"
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
        raise ValueError("Relative-Volume Drift 001 launch equivalence differs")
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
            raise ValueError("Relative-Volume Drift 001 equivalence fixture differs")
        candidates.add(str(fixture["candidate_id"]))
        scenarios.add(str(fixture["scenario_id"]))
    if len(candidates) < 2 or len(scenarios) < 2:
        raise ValueError("Relative-Volume Drift 001 equivalence lacks design span")


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
            "Relative-Volume Drift 001 launch source lineage is unavailable"
        ) from error
    paths = frozenset(line for line in changed.stdout.splitlines() if line)
    required = {
        LAUNCH_CONTROL_RELATIVE_PATH.as_posix(),
        "src/systematic_trading_lab/intraday_relative_volume_drift_001_launch_control.py",
    }
    if (
        ancestor.returncode != 0
        or not required.issubset(paths)
        or not paths.issubset(_LAUNCH_CONTROL_POST_REVIEW_FILES)
    ):
        raise ValueError("Relative-Volume Drift 001 launch source lineage differs")


def _require_exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"Relative-Volume Drift 001 {label} fields differ")


def _validated_source_commit(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("Relative-Volume Drift 001 launch source commit differs")
    return value


def _required_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"Relative-Volume Drift 001 {label} differs")
    return value


def _required_positive_decimal_text(value: object, label: str) -> None:
    try:
        parsed = Decimal(str(value))
    except Exception as error:
        raise ValueError(f"Relative-Volume Drift 001 {label} differs") from error
    if not isinstance(value, str) or not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"Relative-Volume Drift 001 {label} differs")


@dataclass(frozen=True)
class _EquivalenceWorkerFactory:
    repository: Path

    def __call__(self) -> _EquivalenceWorker:
        return _EquivalenceWorker(self.repository)


class _EquivalenceWorker:
    def __init__(self, repository: Path) -> None:
        _require_non_broker_environment()
        self.repository = repository.resolve()
        self.plan = load_intraday_relative_volume_drift_001_plan(self.repository)
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
                    "schema_version": RUN_SCHEMA,
                    "program_id": PROGRAM_ID,
                    "runner_version": RUNNER_VERSION,
                    "engine_version": ENGINE_VERSION,
                    "strategy_version": STRATEGY_VERSION,
                    "source_commit": _text(task, "source_commit"),
                    "plan_sha256": self.plan.sha256,
                    "plan_fingerprint": self.plan.plan_fingerprint,
                    "plan_review_sha256": self.plan.review_sha256,
                    "plan_review_fingerprint": self.plan.review_fingerprint,
                    "autonomous_program_sha256": self.plan.payload["autonomous_program"]["sha256"],
                    "autonomous_program_fingerprint": self.plan.payload["autonomous_program"][
                        "fingerprint"
                    ],
                    "source_state_sha256": self.plan.source_state_sha256,
                    "source_state_fingerprint": self.plan.source_state_fingerprint,
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
                    "period": canonicalize(_EQUIVALENCE_PERIOD),
                    "dataset_inputs": [],
                    "execution": self.plan.payload["execution"],
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
            build_intraday_relative_volume_drift_001_strategy(
                configuration, _EQUIVALENCE_PERIOD.evaluation_start
            ),
        )
        report = _run_report(specification, result, _EQUIVALENCE_PERIOD, self.bars, configuration)
        raw = (canonical_json(report) + "\n").encode()
        _validate_run_report_semantics(_mapping(json.loads(raw), "equivalence report"))
        execution = _mapping(report["execution_evidence"], "execution evidence")
        details = _mapping(report["details"], "report details")
        return {
            "candidate_id": configuration.candidate_id,
            "scenario_id": scenario.scenario_id,
            "run_id": report["run_id"],
            "specification": specification,
            "run_fingerprint": fingerprint(specification),
            "signal_trace_fingerprint": report["signal_trace_fingerprint"],
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
            if day == date(2026, 1, 8) and index < 32:
                closing = Decimal("100.2")
            if day == date(2026, 1, 8) and index >= 32:
                opening = closing = Decimal("101")
            bars.append(
                OHLCVBar(
                    symbol,
                    timestamp,
                    opening,
                    max(opening, closing),
                    min(opening, closing),
                    closing,
                    2_000 if day == date(2026, 1, 8) else 1_000,
                )
            )
    return tuple(bars)


def _parallel_equivalence(repository: Path, *, source_commit: str) -> dict[str, object]:
    plan = load_intraday_relative_volume_drift_001_plan(repository.resolve())
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
        raise ValueError("Relative-Volume Drift 001 one-worker/four-worker equivalence differs")
    sequential_seconds = max(sequential_seconds, 0.000001)
    parallel_seconds = max(parallel_seconds, 0.000001)
    return {
        "schema_version": "intraday-relative-volume-drift-001-parallel-equivalence-v1",
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


def verify_intraday_relative_volume_drift_001_parallel_equivalence(
    repository: Path,
) -> dict[str, object]:
    repository = repository.resolve()
    return _parallel_equivalence(repository, source_commit=_source_commit(repository))


def intraday_relative_volume_drift_001_plan_summary(repository: Path) -> dict[str, object]:
    repository = repository.resolve()
    plan = load_intraday_relative_volume_drift_001_plan(repository)
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


def intraday_relative_volume_drift_001_status(data_home: Path) -> dict[str, object]:
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


def run_intraday_relative_volume_drift_001_campaign(
    repository: Path,
    data_home: Path,
    *,
    workers: int = DEFAULT_RESEARCH_WORKERS,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    return IntradayRelativeVolumeDrift001Runner(
        repository, data_home, workers=workers, progress=progress
    ).run()
