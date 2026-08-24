"""Frozen Intraday Exposed 002 campaign runner."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
import subprocess
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from types import MappingProxyType
from typing import Any

from .calendar import expected_sessions
from .config import non_broker_subprocess_environment
from .datasets import DatasetService
from .domain import OHLCVBar, Symbol, TimestampRange
from .fingerprints import canonical_json, canonicalize, fingerprint
from .intraday_execution_cost_model import (
    ExecutionCostScenario,
    IntradayExecutionCostModel,
    load_intraday_execution_cost_model,
)
from .intraday_exposed_002_engine import (
    Exposed002ReplayResult,
    Exposed002Strategy,
    IntradayExposed002Engine,
)
from .intraday_exposed_002_plan import (
    PLAN_ID,
    Exposed002Configuration,
    Exposed002Period,
    IntradayExposed002Plan,
    load_intraday_exposed_002_plan,
)
from .intraday_exposed_002_strategies import build_intraday_exposed_002_strategy
from .storage import StorageLayout
from .strategies import TargetPosition

RUNNER_VERSION = "intraday-exposed-002-runner-v2"
ENGINE_VERSION = "intraday-exposed-002-engine-v1"
STRATEGY_VERSION = "intraday-exposed-002-mechanics-v1"
RUN_SCHEMA = "intraday-exposed-002-run-v1"
RUN_REPORT_SCHEMA = "intraday-exposed-002-backtest-report-v1"
FINAL_FREEZE_SCHEMA = "intraday-exposed-002-final-freeze-v1"
FINAL_REPORT_SCHEMA = "intraday-exposed-002-final-report-v1"
DATABASE_NAME = "intraday-exposed-002.sqlite3"
_JUNE_START = datetime(2026, 6, 1, tzinfo=UTC)
_ZERO = Decimal("0")
_ONE = Decimal("1")
_ACCOUNTING_PRECISION = Decimal("0.000000000001")
_SYMBOLS = (Symbol("QQQ"), Symbol("SPY"))
_EXPOSED_DATA_NAMESPACE = "intraday-exposed"
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


@dataclass(frozen=True)
class _DatasetBinding:
    dataset_id: str
    data_fingerprint: str
    raw_fingerprint: str
    start: datetime
    end: datetime
    data_namespace: str | None
    raw_sha256: str | None = None
    bars_sha256: str | None = None
    manifest_sha256: str | None = None


@dataclass
class _EvaluationBoundStrategy:
    inner: Exposed002Strategy
    evaluation_start: datetime

    @property
    def strategy_id(self) -> str:
        return self.inner.strategy_id

    @property
    def version(self) -> str:
        return self.inner.version

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        if bars[0].timestamp < self.evaluation_start:
            return tuple(TargetPosition(symbol, _ZERO, "evaluation-warmup") for symbol in _SYMBOLS)
        return self.inner.on_session(bars, history)


class IntradayExposed002Store:
    """Isolated terminal-state registry for the frozen campaign."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / DATABASE_NAME
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS program_binding (
                    program_id TEXT PRIMARY KEY,
                    binding_json TEXT NOT NULL,
                    binding_fingerprint TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    stage TEXT NOT NULL,
                    base_candidate_id TEXT,
                    candidate_id TEXT NOT NULL,
                    family_id TEXT NOT NULL,
                    period_id TEXT NOT NULL,
                    scenario_id TEXT NOT NULL,
                    specification_json TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK (status IN ('pending','running','completed','failed')),
                    report_path TEXT,
                    report_sha256 TEXT,
                    report_fingerprint TEXT,
                    error TEXT
                );
                """
            )

    def bind(self, value: Mapping[str, object]) -> None:
        encoded = canonical_json(value)
        binding_fingerprint = fingerprint(value)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO program_binding
                    (program_id, binding_json, binding_fingerprint)
                VALUES (?, ?, ?)
                """,
                (PLAN_ID, encoded, binding_fingerprint),
            )
            row = connection.execute(
                """
                SELECT binding_json, binding_fingerprint
                FROM program_binding WHERE program_id = ?
                """,
                (PLAN_ID,),
            ).fetchone()
        if row != (encoded, binding_fingerprint):
            raise ValueError("Intraday Exposed 002 stored program binding differs")

    def reserve(self, specifications: Sequence[Mapping[str, object]]) -> None:
        if len({_run_id(value) for value in specifications}) != len(specifications):
            raise ValueError("Intraday Exposed 002 run specifications collide")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for specification in specifications:
                context = _mapping(specification.get("context"), "run context")
                run_id = _run_id(specification)
                encoded = canonical_json(specification)
                connection.execute(
                    """
                    INSERT OR IGNORE INTO runs (
                        run_id, stage, base_candidate_id, candidate_id, family_id,
                        period_id, scenario_id, specification_json, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        run_id,
                        _text(context, "stage"),
                        context.get("base_candidate_id"),
                        _text(context, "candidate_id"),
                        _text(context, "family_id"),
                        _text(context, "period_id"),
                        _text(context, "scenario_id"),
                        encoded,
                    ),
                )
                row = connection.execute(
                    "SELECT specification_json FROM runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                if row != (encoded,):
                    raise ValueError("Intraday Exposed 002 stored run differs")

    def claim(self, run_id: str) -> bool:
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE runs SET status = 'running' WHERE run_id = ? AND status = 'pending'",
                (run_id,),
            )
            if changed.rowcount == 1:
                return True
            row = connection.execute(
                "SELECT status FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row == ("completed",):
            return False
        if row is None:
            raise KeyError(run_id)
        raise ValueError(f"Intraday Exposed 002 run is terminal or claimed: {run_id}")

    def complete(
        self,
        run_id: str,
        report_path: str,
        report_sha256: str,
        report_fingerprint: str,
    ) -> None:
        with self._connect() as connection:
            changed = connection.execute(
                """
                UPDATE runs
                SET status = 'completed', report_path = ?, report_sha256 = ?,
                    report_fingerprint = ?
                WHERE run_id = ? AND status = 'running'
                """,
                (report_path, report_sha256, report_fingerprint, run_id),
            )
            if changed.rowcount != 1:
                raise ValueError("Intraday Exposed 002 completion lost its claim")

    def fail(self, run_id: str, error: Exception) -> None:
        message = f"{type(error).__name__}: {error}"
        with self._connect() as connection:
            changed = connection.execute(
                """
                UPDATE runs SET status = 'failed', error = ?
                WHERE run_id = ? AND status = 'running'
                """,
                (message, run_id),
            )
            if changed.rowcount != 1:
                raise ValueError("Intraday Exposed 002 failure lost its claim")

    def recover_running(self) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT run_id FROM runs WHERE status = 'running' ORDER BY run_id"
            ).fetchall()
            for (run_id,) in rows:
                connection.execute(
                    """
                    UPDATE runs SET status = 'failed', error = ?
                    WHERE run_id = ? AND status = 'running'
                    """,
                    ("RuntimeError: interrupted run is terminal and was not retried", run_id),
                )
        return tuple(row[0] for row in rows)

    def get(self, run_id: str) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT run_id, stage, base_candidate_id, candidate_id, family_id,
                       period_id, scenario_id, specification_json, status,
                       report_path, report_sha256, report_fingerprint, error
                FROM runs WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return _run_row(row)

    def list_runs(self) -> tuple[dict[str, object], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT run_id, stage, base_candidate_id, candidate_id, family_id,
                       period_id, scenario_id, specification_json, status,
                       report_path, report_sha256, report_fingerprint, error
                FROM runs ORDER BY run_id
                """
            ).fetchall()
        return tuple(_run_row(row) for row in rows)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


class IntradayExposed002Runner:
    def __init__(
        self,
        repository: Path,
        data_home: Path,
        *,
        progress: Callable[[str], None] | None = None,
        data_service: DatasetService | None = None,
    ) -> None:
        self.repository = repository.resolve()
        self.data_home = data_home.resolve()
        self.source_commit = _source_commit(self.repository)
        self.progress = progress or (lambda _message: None)
        self.plan = load_intraday_exposed_002_plan(self.repository)
        self.cost_model = load_intraday_execution_cost_model(self.repository)
        self.datasets = _dataset_bindings(self.plan)
        self.data_by_dataset = (
            {binding.dataset_id: data_service for binding in self.datasets}
            if data_service is not None
            else _resolve_dataset_services(self.data_home, self.datasets)
        )
        self._verify_datasets()
        self.runtime_root = self.data_home / PLAN_ID
        self.store = IntradayExposed002Store(self.runtime_root)
        self.scenarios = _scenarios(self.cost_model)
        self._bar_cache: dict[str, tuple[OHLCVBar, ...]] = {}
        self.store.bind(self._program_binding())

    def _program_binding(self) -> dict[str, object]:
        return {
            "schema_version": "intraday-exposed-002-program-binding-v1",
            "program_id": PLAN_ID,
            "runner_version": RUNNER_VERSION,
            "engine_version": ENGINE_VERSION,
            "strategy_version": STRATEGY_VERSION,
            "source_commit": self.source_commit,
            "plan_sha256": self.plan.sha256,
            "plan_fingerprint": self.plan.plan_fingerprint,
            "amendment_sha256": self.plan.amendment_sha256,
            "amendment_fingerprint": self.plan.amendment_fingerprint,
            "data_binding_sha256": self.plan.data_binding_sha256,
            "data_binding_fingerprint": self.plan.data_binding_fingerprint,
            "cost_model_id": self.cost_model.payload["cost_model_id"],
            "cost_model_sha256": self.cost_model.sha256,
            "cost_model_fingerprint": self.cost_model.model_fingerprint,
            "datasets": [canonicalize(value) for value in self.datasets],
            "authority": _AUTHORITY,
        }

    def _verify_datasets(self, plan_payload: Mapping[str, Any] | None = None) -> None:
        payload = self.plan.payload if plan_payload is None else plan_payload
        data = _mapping(payload.get("data"), "plan data")
        for binding in self.datasets:
            service = self.data_by_dataset[binding.dataset_id]
            manifest = service.describe(binding.dataset_id)
            identity = _mapping(manifest.get("identity"), "dataset identity")
            requested = _mapping(manifest.get("requested_range"), "requested range")
            actual = _mapping(manifest.get("actual_range"), "actual range")
            symbols = tuple(
                sorted(
                    _text(_mapping(value, "symbol"), "value")
                    for value in manifest.get("symbols", [])
                )
            )
            if (
                identity.get("dataset_id") != binding.dataset_id
                or identity.get("fingerprint") != binding.data_fingerprint
                or manifest.get("provider") != data.get("provider")
                or manifest.get("feed") != data.get("feed")
                or manifest.get("timeframe") != "5m"
                or manifest.get("adjustment_policy") != data.get("adjustment_policy")
                or manifest.get("calendar_policy") != data.get("calendar_policy")
                or manifest.get("timestamp_policy") != data.get("timestamp_policy")
                or manifest.get("universe_id") != data.get("universe_id")
                or manifest.get("universe_fingerprint") != data.get("universe_fingerprint")
                or manifest.get("raw_artifact_hashes") != [binding.raw_fingerprint]
                or symbols != ("QQQ", "SPY")
                or _timestamp(requested.get("start"), "requested start") != binding.start
                or _timestamp(requested.get("end"), "requested end") != binding.end
                or _timestamp(actual.get("start"), "actual start") != binding.start
                or _timestamp(actual.get("end"), "actual end") != binding.end
                or binding.end >= _JUNE_START
            ):
                raise ValueError(f"Intraday Exposed 002 dataset differs: {binding.dataset_id}")
            if binding.raw_sha256 is not None:
                dataset_path = service.layout.dataset(binding.dataset_id)
                expected_hashes = {
                    "raw.jsonl": binding.raw_sha256,
                    "bars.parquet": binding.bars_sha256,
                    "manifest.json": binding.manifest_sha256,
                }
                if any(
                    expected is None or _sha256_path(dataset_path / name) != expected
                    for name, expected in expected_hashes.items()
                ):
                    raise ValueError("Intraday Exposed 002 May artifact bytes differ")
            validation = service.validate(binding.dataset_id)
            if (
                validation.get("valid") is not True
                or validation.get("fingerprint") != binding.data_fingerprint
                or validation.get("raw_artifact_matches") is not True
            ):
                raise ValueError(
                    f"Intraday Exposed 002 dataset validation failed: {binding.dataset_id}"
                )

    def run(self) -> dict[str, object]:
        with _exclusive_file_lock(self.runtime_root / "campaign.lock"):
            recovered = self.store.recover_running()
            if recovered:
                raise RuntimeError(
                    f"Intraday Exposed 002 recovered {len(recovered)} terminal interrupted run(s)"
                )
            self._require_no_failures()
            discovery = self._run_discovery()
            walk_forward = self._run_walk_forward(discovery)
            serious = self._run_serious(walk_forward)
            cohort = self._select_cohort(serious)
            freeze = self._freeze(discovery, walk_forward, serious, cohort)
            final = self._final_report(discovery, walk_forward, serious, cohort, freeze)
            return {
                "program_id": PLAN_ID,
                "outcome": final["outcome"],
                "terminal_message": final["terminal_message"],
                "source_commit": self.source_commit,
                "cohort_size": len(cohort),
                "final_freeze": str((self.runtime_root / "final-freeze.json").resolve()),
                "final_report_json": str((self.runtime_root / "final-report.json").resolve()),
                "final_report_markdown": str((self.runtime_root / "final-report.md").resolve()),
                "authority": _AUTHORITY,
            }

    def _require_no_failures(self) -> None:
        failed = tuple(row for row in self.store.list_runs() if row["status"] == "failed")
        if failed:
            raise RuntimeError(
                f"Intraday Exposed 002 has {len(failed)} terminal failed run(s); "
                "no retry is allowed"
            )

    def _bars(
        self,
        period: Exposed002Period,
        plan_payload: Mapping[str, Any] | None = None,
    ) -> tuple[OHLCVBar, ...]:
        cached = self._bar_cache.get(period.period_id)
        if cached is not None:
            return cached
        bars: list[OHLCVBar] = []
        payload = self.plan.payload if plan_payload is None else plan_payload
        data = _mapping(payload.get("data"), "plan data")
        for binding in self.datasets:
            start = max(binding.start, period.context_start)
            end = min(binding.end, period.evaluation_end)
            if start > end:
                continue
            bars.extend(
                self.data_by_dataset[binding.dataset_id].load_bars_range(
                    binding.dataset_id,
                    TimestampRange(start, end),
                    expected_fingerprint=binding.data_fingerprint,
                    expected_universe_id=_text(data, "universe_id"),
                    expected_universe_fingerprint=_text(data, "universe_fingerprint"),
                )
            )
        ordered = tuple(sorted(bars, key=lambda bar: (bar.timestamp, bar.symbol.value)))
        if (
            not ordered
            or ordered[0].timestamp != period.context_start
            or ordered[-1].timestamp != period.evaluation_end
            or any(bar.timestamp >= _JUNE_START for bar in ordered)
        ):
            raise ValueError(f"Intraday Exposed 002 period bars differ: {period.period_id}")
        self._bar_cache[period.period_id] = ordered
        return ordered

    def _specification(
        self,
        stage: str,
        configuration: Exposed002Configuration,
        period: Exposed002Period,
        scenario_id: str,
        *,
        base_candidate_id: str | None = None,
    ) -> dict[str, object]:
        scenario = self.scenarios[scenario_id]
        datasets = [
            {
                "dataset_id": item.dataset_id,
                "fingerprint": item.data_fingerprint,
                "read_start": max(item.start, period.context_start),
                "read_end": min(item.end, period.evaluation_end),
            }
            for item in self.datasets
            if item.start <= period.evaluation_end and item.end >= period.context_start
        ]
        return {
            "schema_version": RUN_SCHEMA,
            "program_id": PLAN_ID,
            "runner_version": RUNNER_VERSION,
            "engine_version": ENGINE_VERSION,
            "strategy_version": STRATEGY_VERSION,
            "source_commit": self.source_commit,
            "plan_sha256": self.plan.sha256,
            "plan_fingerprint": self.plan.plan_fingerprint,
            "amendment_sha256": self.plan.amendment_sha256,
            "amendment_fingerprint": self.plan.amendment_fingerprint,
            "data_binding_sha256": self.plan.data_binding_sha256,
            "data_binding_fingerprint": self.plan.data_binding_fingerprint,
            "cost_model": {
                "model_id": self.cost_model.payload["cost_model_id"],
                "sha256": self.cost_model.sha256,
                "fingerprint": self.cost_model.model_fingerprint,
                "scenario_id": scenario.scenario_id,
                "slippage_bps_per_fill": scenario.slippage_bps_per_fill,
                "execution_delay_bars": scenario.execution_delay_bars,
                "regulatory_fee_model_id": scenario.regulatory_fee_model_id,
            },
            "configuration": {
                "candidate_id": configuration.candidate_id,
                "family_id": configuration.family_id,
                "family_ordinal": configuration.family_ordinal,
                "parameters": configuration.parameters,
                "neighbor_ids": configuration.neighbor_ids,
            },
            "period": canonicalize(period),
            "datasets": datasets,
            "execution": self.plan.payload["execution"],
            "context": {
                "stage": stage,
                "base_candidate_id": base_candidate_id,
                "candidate_id": configuration.candidate_id,
                "family_id": configuration.family_id,
                "period_id": period.period_id,
                "scenario_id": scenario_id,
            },
            "authority": _AUTHORITY,
        }

    def _execute(self, specifications: Sequence[Mapping[str, object]]) -> None:
        self.store.reserve(specifications)
        total = len(specifications)
        for ordinal, specification in enumerate(specifications, 1):
            run_id = _run_id(specification)
            if not self.store.claim(run_id):
                self._load_report(self.store.get(run_id))
                continue
            context = _mapping(specification.get("context"), "run context")
            try:
                configuration = self._configuration(_text(context, "candidate_id"))
                period = self._period(_text(context, "period_id"))
                scenario = self.scenarios[_text(context, "scenario_id")]
                strategy = _EvaluationBoundStrategy(
                    build_intraday_exposed_002_strategy(
                        configuration,
                        cost_model=self.cost_model,
                    ),
                    period.evaluation_start,
                )
                result = IntradayExposed002Engine(
                    Decimal(str(self.plan.payload["execution"]["initial_cash"])),
                    scenario,
                    self.cost_model.regulatory_fees,
                ).run(self._bars(period), strategy)
                report = _run_report(specification, result, period)
                relative = Path("run-reports") / f"{run_id}.json"
                destination = self.runtime_root / relative
                _write_create_only(destination, report)
                self.store.complete(
                    run_id,
                    relative.as_posix(),
                    _sha256_path(destination),
                    _text(report, "report_fingerprint"),
                )
                self.progress(
                    f"{ordinal}/{total} {_text(context, 'stage')} "
                    f"{_text(context, 'candidate_id')} {_text(context, 'period_id')} "
                    f"{_text(context, 'scenario_id')}"
                )
            except Exception as error:
                self.store.fail(run_id, error)
                raise

    def _configuration(self, candidate_id: str) -> Exposed002Configuration:
        for item in self.plan.configurations:
            if item.candidate_id == candidate_id:
                return item
        raise ValueError(f"unknown Intraday Exposed 002 candidate: {candidate_id}")

    def _period(self, period_id: str) -> Exposed002Period:
        for item in self.plan.periods:
            if item.period_id == period_id:
                return item
        raise ValueError(f"unknown Intraday Exposed 002 period: {period_id}")

    def _load_report(self, row: Mapping[str, object]) -> Mapping[str, Any]:
        if row.get("status") != "completed":
            raise ValueError("Intraday Exposed 002 run is not completed")
        relative = Path(_required_text(row.get("report_path"), "report path"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Intraday Exposed 002 report path is unsafe")
        path = self.runtime_root / relative
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row.get("report_sha256"):
            raise ValueError("Intraday Exposed 002 report SHA-256 differs")
        value = _mapping(json.loads(raw), "run report")
        stored_fingerprint = _text(value, "report_fingerprint")
        unsigned = dict(value)
        del unsigned["report_fingerprint"]
        if (
            value.get("schema_version") != RUN_REPORT_SCHEMA
            or stored_fingerprint != row.get("report_fingerprint")
            or fingerprint(unsigned) != stored_fingerprint
        ):
            raise ValueError("Intraday Exposed 002 report fingerprint differs")
        return value

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
            for row in self.store.list_runs()
            if row["stage"] == stage
            and row["candidate_id"] == candidate_id
            and row["period_id"] == period_id
            and row["scenario_id"] == scenario_id
            and row["base_candidate_id"] == base_candidate_id
        )
        if len(matches) != 1:
            raise ValueError("Intraday Exposed 002 run relationship differs")
        return self._load_report(matches[0])

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
                "normal.completed_round_trips": _report_metric(normal, "completed_round_trips"),
                "normal.average_round_trips_per_session": _report_metric(
                    normal, "average_round_trips_per_session"
                ),
                "normal.max_drawdown": _report_metric(normal, "max_drawdown"),
                "normal.cost_to_gross_profit": _optional_report_metric(
                    normal, "cost_to_gross_profit"
                ),
                "normal.average_gross_trade_edge_bps": _optional_report_metric(
                    normal, "average_gross_trade_edge_bps"
                ),
                "normal.average_holding_bars": _optional_report_metric(
                    normal, "average_holding_bars"
                ),
                "normal.positive_profit_symbol_concentration": _optional_report_metric(
                    normal, "positive_profit_symbol_concentration"
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
        selected = _select_with_caps(
            ledger,
            global_cap=_positive_int(screen.get("walk_forward_cap"), "walk-forward cap"),
            per_family_cap=_positive_int(screen.get("per_family_cap"), "family cap"),
            key=lambda item: (
                -_ledger_metric(item, "normal.total_return"),
                _ledger_metric(item, "normal.cost_to_gross_profit"),
                _candidate_id(item),
            ),
        )
        for item in ledger:
            item["selected"] = _candidate_id(item) in selected
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
            self._specification("walk-forward", self._configuration(candidate_id), period, scenario)
            for candidate_id in selected
            for period in periods
            for scenario in ("normal", "zero_cost_diagnostic")
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
            normal_aggregate = _aggregate_reports(normal_reports)
            zero_aggregate = _aggregate_reports(zero_reports)
            normal_returns = tuple(
                _report_metric(report, "total_return") for report in normal_reports
            )
            normal_drawdowns = tuple(
                _report_metric(report, "max_drawdown") for report in normal_reports
            )
            values: dict[str, Decimal | int | None] = {
                "aggregate.normal.total_return": _decimal(
                    normal_aggregate.get("total_return"), "aggregate return"
                ),
                "positive_normal_fold_count": sum(value > 0 for value in normal_returns),
                "final_exposed_may.normal.total_return": normal_returns[-1],
                "worst_normal_fold_return": min(normal_returns),
                "worst_normal_fold_drawdown": max(normal_drawdowns),
                "aggregate.normal.completed_round_trips": _integer(
                    normal_aggregate.get("completed_round_trips"), "aggregate round trips"
                ),
                "aggregate.normal.average_round_trips_per_session": _decimal(
                    normal_aggregate.get("average_round_trips_per_session"),
                    "aggregate round trips per session",
                ),
                "aggregate.normal.cost_to_gross_profit": _optional_decimal(
                    normal_aggregate.get("cost_to_gross_profit"), "aggregate cost ratio"
                ),
                "aggregate.normal.average_gross_trade_edge_bps": _optional_decimal(
                    normal_aggregate.get("average_gross_trade_edge_bps"),
                    "aggregate trade edge",
                ),
                "aggregate.normal.average_holding_bars": _optional_decimal(
                    normal_aggregate.get("average_holding_bars"), "aggregate holding bars"
                ),
                "aggregate.normal.positive_profit_symbol_concentration": _optional_decimal(
                    normal_aggregate.get("positive_profit_symbol_concentration"),
                    "aggregate symbol concentration",
                ),
                "aggregate.normal.accounting_identity_error": _decimal(
                    normal_aggregate.get("accounting_identity_error"), "accounting error"
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
        selected_serious = _select_with_caps(
            ledger,
            global_cap=_positive_int(screen.get("serious_candidate_cap"), "serious candidate cap"),
            per_family_cap=_positive_int(screen.get("per_family_cap"), "family cap"),
            key=lambda item: (
                -_ledger_metric(item, "positive_normal_fold_count"),
                -_ledger_metric(item, "aggregate.normal.total_return"),
                _ledger_metric(item, "aggregate.normal.cost_to_gross_profit"),
                _candidate_id(item),
            ),
        )
        for item in ledger:
            item["selected"] = _candidate_id(item) in selected_serious
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
        stress_scenarios = (
            "stress_a",
            "stress_b",
            "normal-delay-2",
            "normal-delay-3",
        )
        stress_specs = tuple(
            self._specification("stress", self._configuration(candidate_id), period, scenario)
            for candidate_id in selected
            for period in periods
            for scenario in stress_scenarios
        )
        neighbor_specs = tuple(
            self._specification(
                "neighbor",
                self._configuration(neighbor_id),
                period,
                scenario,
                base_candidate_id=base_candidate_id,
            )
            for base_candidate_id in selected
            for neighbor_id in self._configuration(base_candidate_id).neighbor_ids
            for period in periods
            for scenario in ("normal", "zero_cost_diagnostic")
        )
        self._execute(stress_specs + neighbor_specs)
        serious_screen = _mapping(
            self.plan.payload.get("serious_candidate_screen"), "serious screen"
        )
        stress_gates = _gates(serious_screen, None, "stress_gates")
        neighbor_gates = _gates(serious_screen, None, "neighbor_gates")
        walk_by_id = {
            _candidate_id(item): item
            for item in _mapping_items(walk_forward.get("ledger"), "walk-forward ledger")
        }
        ledger: list[dict[str, object]] = []
        for candidate_id in selected:
            configuration = self._configuration(candidate_id)
            base = _mapping(walk_by_id[candidate_id], "base walk-forward screen")
            base_aggregate = _mapping(base.get("normal_aggregate"), "base aggregate")
            base_profit = _decimal(base_aggregate.get("net_profit_loss"), "base profit")
            stress_values: dict[str, Decimal | int | None] = {}
            stress_runs: list[dict[str, object]] = []
            for scenario in stress_scenarios:
                reports = [
                    self._report_for("stress", candidate_id, period.period_id, scenario)
                    for period in periods
                ]
                aggregate = _aggregate_reports(reports)
                prefix = scenario
                stress_values[f"{prefix}.aggregate_total_return"] = _decimal(
                    aggregate.get("total_return"), "stress aggregate return"
                )
                stress_values[f"{prefix}.positive_fold_count"] = sum(
                    _report_metric(report, "total_return") > 0 for report in reports
                )
                stress_values[f"{prefix}.normal_profit_retention"] = (
                    _decimal(aggregate.get("net_profit_loss"), "stress profit") / base_profit
                    if base_profit > 0
                    else None
                )
                stress_runs.append(
                    {
                        "scenario_id": scenario,
                        "run_ids": [report["run_id"] for report in reports],
                        "aggregate": aggregate,
                    }
                )
            neighbor_profits: list[Decimal] = []
            positive_neighbors = 0
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
                aggregate = _aggregate_reports(normal_reports)
                zero_aggregate = _aggregate_reports(zero_reports)
                profit = _decimal(aggregate.get("net_profit_loss"), "neighbor profit")
                positive_neighbors += profit > 0
                neighbor_profits.append(profit)
                neighbor_runs.append(
                    {
                        "neighbor_id": neighbor_id,
                        "normal_run_ids": [item["run_id"] for item in normal_reports],
                        "zero_cost_run_ids": [item["run_id"] for item in zero_reports],
                        "normal_aggregate": aggregate,
                        "zero_cost_aggregate": zero_aggregate,
                    }
                )
            neighbor_values: dict[str, Decimal | int | None] = {
                "positive_neighbor_fraction": Decimal(positive_neighbors)
                / Decimal(len(neighbor_profits)),
                "median_neighbor_normal_profit_retention": (
                    median(neighbor_profits) / base_profit if base_profit > 0 else None
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
        normal_details = _mapping(normal.get("details"), "normal details")
        zero_details = _mapping(zero.get("details"), "zero-cost details")
        if normal_details.get("decision_trace_fingerprint") != zero_details.get(
            "decision_trace_fingerprint"
        ):
            raise ValueError("Intraday Exposed 002 paired decision traces differ")
        return normal, zero

    def _select_cohort(self, serious: Mapping[str, object]) -> tuple[str, ...]:
        raw_ledger = serious.get("ledger")
        if not isinstance(raw_ledger, list) or any(
            not isinstance(item, dict) for item in raw_ledger
        ):
            raise ValueError("serious ledger must be a list of objects")
        ledger = raw_ledger
        cohort = _select_with_caps(
            ledger,
            global_cap=5,
            per_family_cap=1,
            key=lambda item: (
                -_ledger_metric(item, "stress_b.positive_fold_count"),
                -_ledger_metric(item, "stress_b.aggregate_total_return"),
                _decimal(
                    _mapping(item.get("base_normal_aggregate"), "base aggregate").get(
                        "cost_to_gross_profit"
                    ),
                    "base cost ratio",
                ),
                _candidate_id(item),
            ),
        )
        for item in ledger:
            item["selected"] = _candidate_id(item) in cohort
        return cohort

    def _freeze(
        self,
        discovery: Mapping[str, object],
        walk_forward: Mapping[str, object],
        serious: Mapping[str, object],
        cohort: Sequence[str],
    ) -> Mapping[str, Any]:
        disposition = _mapping(
            self.plan.payload["frozen_dependencies"]["june_disposition"],
            "June disposition",
        )
        payload: dict[str, object] = {
            "schema_version": FINAL_FREEZE_SCHEMA,
            "program_id": PLAN_ID,
            "status": "frozen-after-complete-exposed-screening",
            "source_commit": self.source_commit,
            "runner_version": RUNNER_VERSION,
            "engine_version": ENGINE_VERSION,
            "strategy_version": STRATEGY_VERSION,
            "plan": {
                "sha256": self.plan.sha256,
                "fingerprint": self.plan.plan_fingerprint,
                "amendment_sha256": self.plan.amendment_sha256,
                "amendment_fingerprint": self.plan.amendment_fingerprint,
                "data_binding_sha256": self.plan.data_binding_sha256,
                "data_binding_fingerprint": self.plan.data_binding_fingerprint,
            },
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
            "all_runtime_runs": [
                {
                    "run_id": row["run_id"],
                    "stage": row["stage"],
                    "base_candidate_id": row["base_candidate_id"],
                    "candidate_id": row["candidate_id"],
                    "period_id": row["period_id"],
                    "scenario_id": row["scenario_id"],
                    "status": row["status"],
                    "report_sha256": row["report_sha256"],
                    "report_fingerprint": row["report_fingerprint"],
                }
                for row in self.store.list_runs()
            ],
            "june_blocker": {
                "path": disposition["path"],
                "sha256": disposition["sha256"],
                "fingerprint": disposition["fingerprint"],
                "range_status": "ineligible",
                "june_read": False,
                "substitute_range": False,
                "controlled_plan_created": False,
                "terminal_action": (
                    "close-empty-cohort-as-failed-evidence"
                    if not cohort
                    else "stop-with-exposed-serious-cohort-before-controlled-evaluation"
                ),
            },
            "protected_access": {
                "june_market_data_or_results": False,
                "v3_data_or_results": False,
                "protected_campaign_results": False,
                "paper_broker_or_live_state": False,
                "strategic_allocation_21": False,
            },
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
        terminal = (
            "AUTONOMOUS INTRADAY EXPOSED 002 COMPLETE — NO CONTROLLED-QUALIFIED CANDIDATE"
            if empty
            else "INTRADAY EXPOSED 002 STOPPED — EXPOSED-SERIOUS COHORT; JUNE INELIGIBLE"
        )
        payload: dict[str, object] = {
            "schema_version": FINAL_REPORT_SCHEMA,
            "program_id": PLAN_ID,
            "outcome": (
                "no-controlled-qualified-candidate"
                if empty
                else "exposed-serious-candidates-blocked-before-controlled-evaluation"
            ),
            "terminal_message": terminal,
            "source_commit": self.source_commit,
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
            "authority": _AUTHORITY,
        }
        payload["report_fingerprint"] = fingerprint(payload)
        json_path = self.runtime_root / "final-report.json"
        _write_create_only(json_path, payload)
        _write_create_only_text(
            self.runtime_root / "final-report.md",
            _final_markdown(payload, _sha256_path(json_path)),
        )
        return payload


def _run_report(
    specification: Mapping[str, object],
    result: Exposed002ReplayResult,
    period: Exposed002Period,
) -> dict[str, object]:
    session_days = set(expected_sessions(period.evaluation_start, period.evaluation_end))
    points_by_day = {
        _account_day(point.timestamp): point
        for point in result.equity_curve
        if _account_day(point.timestamp) in session_days
    }
    if set(points_by_day) != session_days or len(points_by_day) != period.session_count:
        raise ValueError("Intraday Exposed 002 evaluation session curve differs")
    session_points = tuple(points_by_day[day] for day in sorted(session_days))
    fills = tuple(
        fill
        for fill in result.fills
        if period.evaluation_start <= fill.fill_timestamp <= period.evaluation_end
    )
    round_trips = tuple(
        item
        for item in result.round_trips
        if period.evaluation_start <= item.entry_timestamp
        and item.exit_timestamp <= period.evaluation_end
    )
    fees = tuple(
        item for item in result.fee_ledger if date.fromisoformat(item.account_day) in session_days
    )
    if any(
        item.entry_timestamp < period.evaluation_start
        or item.exit_timestamp > period.evaluation_end
        for item in result.round_trips
    ):
        raise ValueError("Intraday Exposed 002 round trip crosses its evaluation boundary")

    gross_profit_loss = sum((item.gross_profit for item in round_trips), _ZERO)
    adverse_slippage = sum((item.adverse_slippage for item in fills), _ZERO)
    regulatory_fees = sum((item.charges.total for item in fees), _ZERO)
    execution_friction = adverse_slippage + regulatory_fees
    net_profit_loss = session_points[-1].equity - result.initial_cash
    accounting_error = abs(gross_profit_loss - execution_friction - net_profit_loss).quantize(
        _ACCOUNTING_PRECISION
    )
    gross_profitable = sum((max(item.gross_profit, _ZERO) for item in round_trips), _ZERO)
    edge_sum = sum(
        (
            item.gross_profit / (item.quantity * item.entry_market_price) * Decimal("10000")
            for item in round_trips
        ),
        _ZERO,
    )
    holding_sum = sum((item.holding_bars for item in round_trips), _ZERO)
    turnover_notional = sum((abs(item.quantity) * item.market_price for item in fills), _ZERO)
    symbol_gross = {
        symbol: sum((item.gross_profit for item in round_trips if item.symbol == symbol), _ZERO)
        for symbol in _SYMBOLS
    }
    symbol_slippage = {
        symbol: sum((item.adverse_slippage for item in fills if item.symbol == symbol), _ZERO)
        for symbol in _SYMBOLS
    }
    symbol_fees = {
        symbol: sum(
            (
                value
                for daily in fees
                for fee_symbol, value in daily.by_symbol
                if fee_symbol == symbol
            ),
            _ZERO,
        )
        for symbol in _SYMBOLS
    }
    symbol_net = {
        symbol: symbol_gross[symbol] - symbol_slippage[symbol] - symbol_fees[symbol]
        for symbol in _SYMBOLS
    }
    positive_concentration = _positive_concentration(tuple(symbol_net.values()))
    peak = result.initial_cash
    max_drawdown = _ZERO
    for point in session_points:
        peak = max(peak, point.equity)
        max_drawdown = max(
            max_drawdown,
            (peak - point.equity) / peak if peak else _ZERO,
        )
    completed = len(round_trips)
    metrics: dict[str, object] = {
        "initial_cash": result.initial_cash,
        "final_equity": session_points[-1].equity,
        "total_return": net_profit_loss / result.initial_cash,
        "max_drawdown": max_drawdown,
        "turnover": turnover_notional / result.initial_cash,
        "turnover_notional": turnover_notional,
        "fill_count": len(fills),
        "completed_round_trips": completed,
        "session_count": period.session_count,
        "average_round_trips_per_session": Decimal(completed) / Decimal(period.session_count),
        "gross_profit_loss": gross_profit_loss,
        "gross_profitable_trade_profit": gross_profitable,
        "execution_friction": execution_friction,
        "adverse_slippage": adverse_slippage,
        "regulatory_fees": regulatory_fees,
        "net_profit_loss": net_profit_loss,
        "cost_to_gross_profit": (
            execution_friction / gross_profitable if gross_profitable > 0 else None
        ),
        "gross_trade_edge_bps_sum": edge_sum,
        "average_gross_trade_edge_bps": (edge_sum / Decimal(completed) if completed else None),
        "holding_bars_sum": holding_sum,
        "average_holding_bars": (holding_sum / Decimal(completed) if completed else None),
        "positive_profit_symbol_concentration": positive_concentration,
        "accounting_identity_error": accounting_error,
    }
    details: dict[str, object] = {
        "decision_trace_fingerprint": fingerprint(result.decisions),
        "transition_trace_fingerprint": fingerprint(result.transitions),
        "fill_trace_fingerprint": fingerprint(fills),
        "round_trip_fingerprint": fingerprint(round_trips),
        "daily_fee_ledger_fingerprint": fingerprint(fees),
        "daily_fee_ledger": fees,
        "symbol_gross_profit_loss": {symbol.value: value for symbol, value in symbol_gross.items()},
        "symbol_adverse_slippage": {
            symbol.value: value for symbol, value in symbol_slippage.items()
        },
        "symbol_regulatory_fees": {symbol.value: value for symbol, value in symbol_fees.items()},
        "symbol_net_profit_loss": {symbol.value: value for symbol, value in symbol_net.items()},
        "gross_profit_loss_minus_execution_friction": (gross_profit_loss - execution_friction),
        "engine_artifact_fingerprint": result.artifact_fingerprint,
    }
    payload: dict[str, object] = {
        "schema_version": RUN_REPORT_SCHEMA,
        "program_id": PLAN_ID,
        "run_id": _run_id(specification),
        "specification": specification,
        "specification_fingerprint": fingerprint(specification),
        "metrics": metrics,
        "details": details,
        "authority": _AUTHORITY,
    }
    payload["report_fingerprint"] = fingerprint(payload)
    return payload


def _aggregate_reports(reports: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    if not reports:
        raise ValueError("Intraday Exposed 002 aggregate requires reports")
    metrics = tuple(_mapping(report.get("metrics"), "report metrics") for report in reports)
    details = tuple(_mapping(report.get("details"), "report details") for report in reports)
    completed = sum(
        _integer(value.get("completed_round_trips"), "round trips") for value in metrics
    )
    sessions = sum(_integer(value.get("session_count"), "session count") for value in metrics)
    gross = sum(
        (_decimal(value.get("gross_profit_loss"), "gross profit") for value in metrics), _ZERO
    )
    profitable = sum(
        (
            _decimal(value.get("gross_profitable_trade_profit"), "profitable gross")
            for value in metrics
        ),
        _ZERO,
    )
    friction = sum(
        (_decimal(value.get("execution_friction"), "execution friction") for value in metrics),
        _ZERO,
    )
    net = sum((_decimal(value.get("net_profit_loss"), "net profit") for value in metrics), _ZERO)
    edge_sum = sum(
        (_decimal(value.get("gross_trade_edge_bps_sum"), "edge sum") for value in metrics),
        _ZERO,
    )
    holding_sum = sum(
        (_decimal(value.get("holding_bars_sum"), "holding sum") for value in metrics),
        _ZERO,
    )
    aggregate_return = sum(
        (_decimal(value.get("total_return"), "fold return") for value in metrics),
        _ZERO,
    )
    symbol_net = {
        symbol.value: sum(
            (
                _decimal(
                    _mapping(detail.get("symbol_net_profit_loss"), "symbol net").get(symbol.value),
                    "symbol profit",
                )
                for detail in details
            ),
            _ZERO,
        )
        for symbol in _SYMBOLS
    }
    return {
        "fold_count": len(reports),
        "total_return": aggregate_return,
        "worst_fold_return": min(
            _decimal(value.get("total_return"), "fold return") for value in metrics
        ),
        "max_drawdown": max(
            _decimal(value.get("max_drawdown"), "fold drawdown") for value in metrics
        ),
        "completed_round_trips": completed,
        "session_count": sessions,
        "average_round_trips_per_session": Decimal(completed) / Decimal(sessions),
        "gross_profit_loss": gross,
        "gross_profitable_trade_profit": profitable,
        "execution_friction": friction,
        "net_profit_loss": net,
        "cost_to_gross_profit": friction / profitable if profitable > 0 else None,
        "gross_trade_edge_bps_sum": edge_sum,
        "average_gross_trade_edge_bps": edge_sum / Decimal(completed) if completed else None,
        "holding_bars_sum": holding_sum,
        "average_holding_bars": holding_sum / Decimal(completed) if completed else None,
        "symbol_net_profit_loss": symbol_net,
        "positive_profit_symbol_concentration": _positive_concentration(tuple(symbol_net.values())),
        "accounting_identity_error": abs(gross - friction - net).quantize(_ACCOUNTING_PRECISION),
    }


def _gate_results(
    gates: Sequence[Mapping[str, Any]],
    values: Mapping[str, Decimal | int | None],
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for gate in gates:
        metric = _text(gate, "metric")
        comparison = _text(gate, "comparison")
        threshold = _decimal(gate.get("threshold"), "gate threshold")
        observed = values.get(metric)
        numeric = None if observed is None else Decimal(observed)
        passed = (
            numeric is not None
            and {
                ">": numeric > threshold if numeric is not None else False,
                ">=": numeric >= threshold if numeric is not None else False,
                "<=": numeric <= threshold if numeric is not None else False,
                "=": numeric == threshold if numeric is not None else False,
            }[comparison]
        )
        results.append(
            {
                "metric": metric,
                "comparison": comparison,
                "threshold": threshold,
                "observed": numeric,
                "passed": passed,
            }
        )
    return results


def _select_with_caps(
    ledger: Sequence[Mapping[str, object]],
    *,
    global_cap: int,
    per_family_cap: int,
    key: Callable[[Mapping[str, object]], tuple[Any, ...]],
) -> tuple[str, ...]:
    family_counts: dict[str, int] = {}
    selected: list[str] = []
    for item in sorted((value for value in ledger if value.get("eligible") is True), key=key):
        candidate = _mapping(item.get("candidate"), "candidate")
        family_id = _text(candidate, "family_id")
        if family_counts.get(family_id, 0) >= per_family_cap:
            continue
        selected.append(_text(candidate, "candidate_id"))
        family_counts[family_id] = family_counts.get(family_id, 0) + 1
        if len(selected) == global_cap:
            break
    return tuple(selected)


def _resolve_dataset_services(
    data_home: Path,
    bindings: Sequence[_DatasetBinding],
) -> Mapping[str, DatasetService]:
    base = data_home.resolve()
    services: dict[Path, DatasetService] = {}
    resolved: dict[str, DatasetService] = {}
    for binding in bindings:
        root = base if binding.data_namespace is None else base / binding.data_namespace
        if not (root / "catalog.sqlite3").is_file():
            raise ValueError(
                f"Intraday Exposed 002 dataset catalog is missing: {binding.dataset_id}"
            )
        service = services.get(root)
        if service is None:
            service = DatasetService(StorageLayout(root))
            services[root] = service
        try:
            service.describe(binding.dataset_id)
        except KeyError as error:
            raise ValueError(
                f"Intraday Exposed 002 dataset location is missing: {binding.dataset_id}"
            ) from error
        resolved[binding.dataset_id] = service
    return MappingProxyType(resolved)


def _dataset_bindings(plan: IntradayExposed002Plan) -> tuple[_DatasetBinding, ...]:
    data = _mapping(plan.payload.get("data"), "plan data")
    values = data.get("dataset_bindings")
    if not isinstance(values, list):
        raise ValueError("Intraday Exposed 002 dataset bindings differ")
    result = [
        _DatasetBinding(
            _text(_mapping(value, "dataset binding"), "dataset_id"),
            _text(_mapping(value, "dataset binding"), "fingerprint"),
            _text(_mapping(value, "dataset binding"), "raw_fingerprint"),
            _timestamp(
                _mapping(value, "dataset binding").get("allowed_read_start"),
                "allowed start",
            ),
            _timestamp(
                _mapping(value, "dataset binding").get("allowed_read_end"),
                "allowed end",
            ),
            _EXPOSED_DATA_NAMESPACE,
        )
        for value in values
    ]
    may = _mapping(plan.data_binding.get("may_dataset"), "May dataset")
    result.append(
        _DatasetBinding(
            _text(may, "dataset_id"),
            _text(may, "fingerprint"),
            _text(may, "raw_fingerprint"),
            _timestamp(may.get("actual_start"), "May start"),
            _timestamp(may.get("actual_end"), "May end"),
            None,
            _text(may, "raw_sha256"),
            _text(may, "bars_sha256"),
            _text(may, "manifest_sha256"),
        )
    )
    bindings = tuple(result)
    if len(bindings) != 4 or any(
        left.end >= right.start for left, right in zip(bindings, bindings[1:], strict=False)
    ):
        raise ValueError("Intraday Exposed 002 dataset ranges differ")
    return bindings


def _scenarios(model: IntradayExecutionCostModel) -> Mapping[str, ExecutionCostScenario]:
    normal = model.scenarios["normal"]
    values = dict(model.scenarios)
    values["normal-delay-2"] = ExecutionCostScenario(
        "normal-delay-2",
        normal.percentile,
        normal.slippage_bps_per_fill,
        2,
        normal.regulatory_fee_model_id,
    )
    values["normal-delay-3"] = ExecutionCostScenario(
        "normal-delay-3",
        normal.percentile,
        normal.slippage_bps_per_fill,
        3,
        normal.regulatory_fee_model_id,
    )
    return MappingProxyType(values)


def _run_row(row: Sequence[object]) -> dict[str, object]:
    return {
        "run_id": row[0],
        "stage": row[1],
        "base_candidate_id": row[2],
        "candidate_id": row[3],
        "family_id": row[4],
        "period_id": row[5],
        "scenario_id": row[6],
        "specification": json.loads(str(row[7])),
        "status": row[8],
        "report_path": row[9],
        "report_sha256": row[10],
        "report_fingerprint": row[11],
        "error": row[12],
    }


def _configuration_summary(configuration: Exposed002Configuration) -> dict[str, object]:
    return {
        "candidate_id": configuration.candidate_id,
        "family_id": configuration.family_id,
        "family_ordinal": configuration.family_ordinal,
        "parameters": configuration.parameters,
        "neighbor_ids": configuration.neighbor_ids,
    }


def _report_metric(report: Mapping[str, Any], name: str) -> Decimal:
    return _decimal(_mapping(report.get("metrics"), "report metrics").get(name), name)


def _optional_report_metric(report: Mapping[str, Any], name: str) -> Decimal | None:
    value = _mapping(report.get("metrics"), "report metrics").get(name)
    return None if value is None else _decimal(value, name)


def _ledger_metric(item: Mapping[str, object], name: str) -> Decimal:
    value = _mapping(item.get("metrics"), "screen metrics").get(name)
    if value is None:
        raise ValueError(f"Intraday Exposed 002 selection metric is undefined: {name}")
    return _decimal(value, name)


def _candidate_id(item: Mapping[str, object]) -> str:
    return _text(_mapping(item.get("candidate"), "candidate"), "candidate_id")


def _positive_concentration(values: Sequence[Decimal]) -> Decimal | None:
    positive = tuple(value for value in values if value > 0)
    total = sum(positive, _ZERO)
    return max(positive) / total if total else None


def _gates(
    payload: Mapping[str, Any], section: str | None, key: str
) -> tuple[Mapping[str, Any], ...]:
    source = _mapping(payload.get(section), section) if section is not None else payload
    values = source.get(key)
    if not isinstance(values, list):
        raise ValueError("Intraday Exposed 002 gates differ")
    return tuple(_mapping(value, "gate") for value in values)


def _mapping_items(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must be a list of objects")
    return tuple(value)


def _mapping(value: object, label: str | None) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label or 'value'} must be an object")
    return value


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} must be text")
    return item


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be text")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list | tuple) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be text values")
    return tuple(value)


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be positive")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str | int | Decimal):
        raise ValueError(f"{label} must be decimal")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{label} must be decimal") from error
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


def _optional_decimal(value: object, label: str) -> Decimal | None:
    return None if value is None else _decimal(value, label)


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} must be a UTC timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError(f"{label} must be a UTC timestamp")
    return parsed


def _account_day(timestamp: datetime) -> date:
    from zoneinfo import ZoneInfo

    return timestamp.astimezone(ZoneInfo("America/New_York")).date()


def _run_id(specification: Mapping[str, object]) -> str:
    return f"ie002r-{fingerprint(specification)[:24]}"


def _validated_commit(value: str) -> str:
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("Intraday Exposed 002 source commit is invalid")
    return value


def _source_commit(repository: Path) -> str:
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
        commit = subprocess.run(
            (*command, "rev-parse", "HEAD"),
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout.strip()
        main = subprocess.run(
            (*command, "rev-parse", "refs/heads/main"),
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout.strip()
        origin_main = subprocess.run(
            (*command, "rev-parse", "refs/remotes/origin/main"),
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout.strip()
        dirty = subprocess.run(
            (*command, "status", "--porcelain", "--untracked-files=all"),
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError("Intraday Exposed 002 source identity is unavailable") from error
    if dirty:
        raise ValueError("Intraday Exposed 002 requires a clean reviewed source commit")
    if commit != main or commit != origin_main:
        raise ValueError("Intraday Exposed 002 requires HEAD, main, and origin/main to match")
    return _validated_commit(commit)


@contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Intraday Exposed 002 campaign is already running") from error
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _write_create_only(path: Path, payload: Mapping[str, object]) -> None:
    _write_create_only_bytes(path, (canonical_json(payload) + "\n").encode())


def _write_create_only_text(path: Path, contents: str) -> None:
    _write_create_only_bytes(path, contents.encode())


def _write_create_only_bytes(path: Path, contents: bytes) -> None:
    if path.exists():
        if path.read_bytes() != contents:
            raise FileExistsError(f"Intraday Exposed 002 artifact differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != contents:
                raise
    finally:
        temporary.unlink(missing_ok=True)


def _sha256_path(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _final_markdown(report: Mapping[str, object], json_sha256: str) -> str:
    counts = _mapping(report.get("counts"), "final counts")
    cohort = report.get("cohort")
    assert isinstance(cohort, list)
    lines = [
        "# Intraday Exposed 002 final report",
        "",
        f"Outcome: `{report['outcome']}`",
        "",
        f"Source commit: `{report['source_commit']}`",
        "",
        f"JSON SHA-256: `{json_sha256}`",
        "",
        "## Counts",
        "",
        f"- Discovery parents: {counts['discovery_parents']}",
        f"- Discovery runs: {counts['discovery_runs']}",
        f"- Walk-forward candidates: {counts['walk_forward_candidates']}",
        f"- Walk-forward runs: {counts['walk_forward_runs']}",
        f"- Serious candidates: {counts['serious_candidates']}",
        f"- Stress runs: {counts['stress_runs']}",
        f"- Neighbor runs: {counts['neighbor_runs']}",
        f"- Final cohort: {counts['cohort']}",
        "",
        "June remained unread. Its committed V2 exposure makes it ineligible, and no substitute "
        "range or controlled plan was used.",
        "",
        f"**{report['terminal_message']}**",
        "",
    ]
    return "\n".join(lines)


def intraday_exposed_002_plan_summary(repository: Path) -> dict[str, object]:
    plan = load_intraday_exposed_002_plan(repository.resolve())
    return {
        "program_id": PLAN_ID,
        "status": "ready-for-merged-implementation-gate",
        "plan_sha256": plan.sha256,
        "plan_fingerprint": plan.plan_fingerprint,
        "amendment_sha256": plan.amendment_sha256,
        "amendment_fingerprint": plan.amendment_fingerprint,
        "data_binding_sha256": plan.data_binding_sha256,
        "data_binding_fingerprint": plan.data_binding_fingerprint,
        "parent_configuration_count": len(plan.configurations),
        "period_count": len(plan.periods),
        "latest_evaluation_bar": plan.periods[-1].evaluation_end,
        "june_status": "ineligible-no-read-no-substitute",
        "authority": _AUTHORITY,
    }


def intraday_exposed_002_status(data_home: Path) -> dict[str, object]:
    runtime = data_home.resolve() / PLAN_ID
    database = runtime / DATABASE_NAME
    counts = {status: 0 for status in ("pending", "running", "completed", "failed")}
    if database.exists():
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            for status, count in connection.execute(
                "SELECT status, COUNT(*) FROM runs GROUP BY status"
            ).fetchall():
                counts[str(status)] = int(count)
        finally:
            connection.close()
    final_path = runtime / "final-report.json"
    final: Mapping[str, Any] | None = None
    if final_path.exists():
        final = _mapping(json.loads(final_path.read_bytes()), "final report")
    return {
        "program_id": PLAN_ID,
        "database_exists": database.exists(),
        "run_counts": counts,
        "terminal": final is not None,
        "outcome": None if final is None else final.get("outcome"),
        "cohort_size": None
        if final is None
        else _mapping(final.get("counts"), "final counts").get("cohort"),
        "authority": _AUTHORITY,
    }


def run_intraday_exposed_002_campaign(
    repository: Path,
    data_home: Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    return IntradayExposed002Runner(
        repository,
        data_home,
        progress=progress,
    ).run()
