"""Frozen exposed-data intraday research and controlled qualification runner."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import itertools
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import pstdev
from types import MappingProxyType
from typing import Any, cast
from zoneinfo import ZoneInfo

from .backtesting import (
    BacktestEngine,
    BacktestError,
    BacktestResult,
    CostModel,
    PortfolioStrategy,
    Trade,
)
from .config import non_broker_subprocess_environment
from .datasets import DatasetService
from .domain import OHLCVBar, Symbol, Timeframe, TimestampRange
from .fingerprints import canonical_json, canonicalize, fingerprint
from .intraday_exposed_strategies import build_intraday_exposed_strategy
from .intraday_qualification import (
    REVIEWED_POLICY_FINGERPRINT,
    IntradayQualificationPolicy,
    load_intraday_qualification_policy,
)
from .intraday_reporting import build_intraday_report
from .intraday_v3 import (
    DesiredStateDecision,
    StateTransitionBacktestEngine,
    V3BacktestResult,
)
from .storage import StorageLayout
from .strategies import TargetPosition

PROGRAM_ID = "intraday-exposed-001"
PLAN_SCHEMA = "intraday-exposed-research-plan-v1"
RUN_SCHEMA = "intraday-exposed-run-v1"
REPORT_SCHEMA = "intraday-exposed-backtest-report-v1"
COHORT_SCHEMA = "intraday-exposed-cohort-freeze-v1"
CONTROLLED_PLAN_SCHEMA = "intraday-exposed-controlled-plan-v1"
QUALIFICATION_SCHEMA = "intraday-exposed-qualification-evidence-v1"
FINAL_REPORT_SCHEMA = "intraday-exposed-final-report-v1"
RUNNER_VERSION = "intraday-exposed-runner-v1"
PLAN_RELATIVE_PATH = Path("config/research/intraday-exposed-001-plan-v1.json")
POLICY_RELATIVE_PATH = Path("config/research/intraday-qualification-policy-v1.json")
REVIEWED_PLAN_SHA256 = "75e33950647b83d3213fb635153961b36b80d8dbbbfe9e9220350910c09ecfc9"
REQUIRED_REPORTING_FIELDS = (
    "net_return",
    "zero_cost_return",
    "sharpe_ratio",
    "max_drawdown",
    "turnover",
    "fill_count",
    "completed_round_trips",
    "hit_rate",
    "average_trade",
    "cost_paid",
    "cost_to_zero_cost_profit_ratio",
    "average_holding_duration",
    "exposure_time",
    "long_and_flat_state_duration",
    "chronological_block_performance",
    "time_of_day_performance",
    "symbol_contribution",
    "worst_fold",
    "fold_dispersion",
    "stress_a_retention",
    "stress_b_retention",
    "parameter_neighbor_retention",
)

_NEW_YORK = ZoneInfo("America/New_York")
_ZERO = Decimal("0")
_HALF = Decimal("0.5")
_ONE = Decimal("1")
_ALLOWED_WEIGHTS = frozenset({_ZERO, _HALF, _ONE})
_AUTHORITY = MappingProxyType(
    {
        "protected_holdout": False,
        "independent_evaluation": False,
        "automatic_promotion": False,
        "paper_execution": False,
        "broker_writes": False,
        "live_execution": False,
    }
)


@dataclass(frozen=True)
class DatasetBinding:
    dataset_id: str
    fingerprint: str
    raw_fingerprint: str
    start: datetime
    end: datetime
    bar_count: int


@dataclass(frozen=True)
class EvaluationPeriod:
    period_id: str
    context_start: datetime
    evaluation_start: datetime
    evaluation_end: datetime


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    slippage_bps: Decimal
    commission_bps: Decimal
    execution_delay_bars: int


@dataclass(frozen=True)
class Configuration:
    family_id: str
    family_name: str
    strategy_id: str
    parameters: tuple[tuple[str, int], ...]
    configuration_id: str

    @classmethod
    def create(
        cls,
        family_id: str,
        family_name: str,
        strategy_id: str,
        parameters: Mapping[str, int],
    ) -> Configuration:
        canonical_parameters = tuple(sorted(parameters.items()))
        identity = {
            "family_id": family_id,
            "family_name": family_name,
            "strategy_id": strategy_id,
            "parameters": dict(canonical_parameters),
        }
        return cls(
            family_id,
            family_name,
            strategy_id,
            canonical_parameters,
            f"iec-{fingerprint(identity)[:20]}",
        )

    @property
    def parameter_mapping(self) -> Mapping[str, int]:
        return MappingProxyType(dict(self.parameters))


@dataclass(frozen=True)
class IntradayExposedPlan:
    path: Path
    payload: Mapping[str, Any]
    sha256: str
    fingerprint: str
    configurations: tuple[Configuration, ...]
    datasets: tuple[DatasetBinding, ...]
    discovery: EvaluationPeriod
    walk_forward_folds: tuple[EvaluationPeriod, ...]
    controlled_period: EvaluationPeriod
    scenarios: Mapping[str, Scenario]

    @property
    def runtime_namespace(self) -> Path:
        return Path(_text(self.payload["runtime_namespace"], "runtime namespace"))

    @property
    def symbols(self) -> tuple[Symbol, ...]:
        data = _mapping(self.payload["data"], "data")
        values = _strings(data["symbols"], "symbols")
        return tuple(Symbol(value) for value in values)

    @property
    def initial_cash(self) -> Decimal:
        execution = _mapping(self.payload["execution"], "execution")
        value = _decimal(execution["initial_cash"], "initial cash")
        if value <= 0:
            raise ValueError("Intraday Exposed 001 initial cash must be positive")
        return value

    def family_configurations(self, family_id: str) -> tuple[Configuration, ...]:
        return tuple(item for item in self.configurations if item.family_id == family_id)

    def configuration(self, configuration_id: str) -> Configuration:
        for item in self.configurations:
            if item.configuration_id == configuration_id:
                return item
        raise ValueError(f"unknown configuration: {configuration_id}")

    def neighbors(self, configuration: Configuration) -> tuple[Configuration, ...]:
        peers = tuple(
            item
            for item in self.configurations
            if item.strategy_id == configuration.strategy_id
            and item.family_id == configuration.family_id
        )
        current = dict(configuration.parameters)
        neighbors: list[tuple[str, int, Configuration]] = []
        for candidate in peers:
            if candidate == configuration:
                continue
            changed = tuple(
                name for name in current if candidate.parameter_mapping.get(name) != current[name]
            )
            if len(changed) != 1 or set(candidate.parameter_mapping) != set(current):
                continue
            name = changed[0]
            values = sorted({item.parameter_mapping[name] for item in peers})
            index = values.index(current[name])
            adjacent = {
                values[position]
                for position in (index - 1, index + 1)
                if 0 <= position < len(values)
            }
            if candidate.parameter_mapping[name] in adjacent:
                neighbors.append((name, candidate.parameter_mapping[name], candidate))
        maximum = _positive_int(
            _mapping(self.payload["robustness"], "robustness")["maximum_neighbors_per_candidate"],
            "maximum neighbors",
        )
        return tuple(
            item[2]
            for item in sorted(
                neighbors,
                key=lambda value: (value[0], value[1], value[2].configuration_id),
            )[:maximum]
        )


def load_intraday_exposed_plan(repository: Path) -> IntradayExposedPlan:
    path = (repository / PLAN_RELATIVE_PATH).resolve()
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    if sha256 != REVIEWED_PLAN_SHA256:
        raise ValueError("Intraday Exposed 001 plan SHA-256 differs")
    try:
        payload_value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("Intraday Exposed 001 plan is invalid JSON") from error
    payload = _mapping(payload_value, "plan")
    if payload.get("schema_version") != PLAN_SCHEMA or payload.get("program_id") != PROGRAM_ID:
        raise ValueError("Intraday Exposed 001 plan identity differs")
    if payload.get("status") != "frozen-before-strategy-results":
        raise ValueError("Intraday Exposed 001 plan is not frozen")
    authority = _mapping(payload["authority"], "authority")
    if authority != _AUTHORITY:
        raise ValueError("Intraday Exposed 001 authority differs")

    configurations: list[Configuration] = []
    families = payload.get("families")
    if not isinstance(families, list) or not families:
        raise ValueError("Intraday Exposed 001 families differ")
    for family_value in families:
        family = _mapping(family_value, "family")
        family_id = _text(family["id"], "family ID")
        family_name = _text(family["name"], "family name")
        contracts = family.get("contracts")
        if not isinstance(contracts, list) or not contracts:
            raise ValueError("Intraday Exposed 001 family contracts differ")
        before = len(configurations)
        for contract_value in contracts:
            contract = _mapping(contract_value, "contract")
            strategy_id = _text(contract["id"], "strategy ID")
            parameter_sets_value = contract.get("parameter_sets", [{}])
            if not isinstance(parameter_sets_value, list) or not parameter_sets_value:
                raise ValueError("Intraday Exposed 001 parameter sets differ")
            parameter_sets = tuple(
                _integer_mapping(value, "parameter set") for value in parameter_sets_value
            )
            grid = _mapping(contract.get("parameters", {}), "parameter grid")
            grid_values = {
                _text(name, "parameter name"): _integer_values(values, f"parameter {name}")
                for name, values in grid.items()
            }
            fixed = _integer_mapping(contract.get("fixed_parameters", {}), "fixed parameters")
            names = tuple(grid_values)
            selections: Iterable[tuple[int, ...]] = (
                itertools.product(*(grid_values[name] for name in names)) if names else ((),)
            )
            for parameter_set in parameter_sets:
                if set(parameter_set) & (set(names) | set(fixed)) or set(names) & set(fixed):
                    raise ValueError("Intraday Exposed 001 parameter declarations overlap")
                for selection in selections:
                    parameters = {
                        **parameter_set,
                        **dict(zip(names, selection, strict=True)),
                        **fixed,
                    }
                    configurations.append(
                        Configuration.create(family_id, family_name, strategy_id, parameters)
                    )
                selections = (
                    itertools.product(*(grid_values[name] for name in names)) if names else ((),)
                )
        observed = len(configurations) - before
        if observed != _positive_int(
            family["declared_configurations"], "declared family configurations"
        ):
            raise ValueError("Intraday Exposed 001 family count differs")
    if len({item.configuration_id for item in configurations}) != len(configurations):
        raise ValueError("Intraday Exposed 001 configuration identities collide")
    if _strings(payload["required_reporting"], "required reporting") != REQUIRED_REPORTING_FIELDS:
        raise ValueError("Intraday Exposed 001 required reporting fields differ")
    search = _mapping(payload["search"], "search")
    declared = _positive_int(search["declared_parent_configurations"], "declared count")
    maximum = _positive_int(search["maximum_parent_configurations"], "maximum count")
    if len(configurations) != declared or declared > maximum or declared != 325:
        raise ValueError("Intraday Exposed 001 configuration budget differs")

    data = _mapping(payload["data"], "data")
    dataset_values = data.get("datasets")
    if not isinstance(dataset_values, list) or len(dataset_values) != 4:
        raise ValueError("Intraday Exposed 001 dataset allowlist differs")
    datasets = tuple(_dataset_binding(value) for value in dataset_values)
    if any(left.end >= right.start for left, right in itertools.pairwise(datasets)):
        raise ValueError("Intraday Exposed 001 dataset ranges overlap or are unordered")
    chronology = _mapping(payload["chronology"], "chronology")
    discovery = _period("discovery", chronology["discovery"])
    fold_values = chronology.get("walk_forward_folds")
    if not isinstance(fold_values, list) or len(fold_values) != 4:
        raise ValueError("Intraday Exposed 001 walk-forward folds differ")
    folds = tuple(
        _period(_text(_mapping(value, "fold")["id"], "fold ID"), value) for value in fold_values
    )
    controlled = _period("controlled", chronology["controlled_qualification"])
    if any(fold.evaluation_end >= controlled.evaluation_start for fold in folds):
        raise ValueError("Intraday Exposed 001 controlled period is not reserved")
    scenarios = _scenarios(payload)
    return IntradayExposedPlan(
        path,
        payload,
        sha256,
        fingerprint(payload),
        tuple(configurations),
        datasets,
        discovery,
        folds,
        controlled,
        MappingProxyType(scenarios),
    )


def _dataset_binding(value: object) -> DatasetBinding:
    item = _mapping(value, "dataset")
    return DatasetBinding(
        _text(item["dataset_id"], "dataset ID"),
        _text(item["fingerprint"], "dataset fingerprint"),
        _text(item["raw_fingerprint"], "raw fingerprint"),
        _timestamp(item["start"], "dataset start"),
        _timestamp(item["end"], "dataset end"),
        _positive_int(item["bar_count"], "dataset bar count"),
    )


def _period(period_id: str, value: object) -> EvaluationPeriod:
    item = _mapping(value, f"period {period_id}")
    period = EvaluationPeriod(
        period_id,
        _timestamp(item["context_start"], "context start"),
        _timestamp(item["evaluation_start"], "evaluation start"),
        _timestamp(item["evaluation_end"], "evaluation end"),
    )
    if not period.context_start <= period.evaluation_start <= period.evaluation_end:
        raise ValueError(f"Intraday Exposed 001 period is invalid: {period_id}")
    return period


def _scenarios(payload: Mapping[str, Any]) -> dict[str, Scenario]:
    execution = _mapping(payload["execution"], "execution")

    def scenario(name: str, value: object) -> Scenario:
        item = _mapping(value, f"scenario {name}")
        slippage = _decimal(item["slippage_bps"], "slippage")
        commission = _decimal(item["commission_bps"], "commission")
        if slippage < 0 or commission < 0:
            raise ValueError("Intraday Exposed 001 costs must be non-negative")
        return Scenario(
            name,
            slippage,
            commission,
            _positive_int(item["execution_delay_bars"], "execution delay"),
        )

    result = {
        "normal": scenario("normal", execution["normal"]),
        "stress-a": scenario("stress-a", execution["stress_a"]),
        "stress-b": scenario("stress-b", execution["stress_b"]),
        "zero-cost": scenario("zero-cost", execution["zero_cost_diagnostic"]),
    }
    normal = result["normal"]
    delays = _integer_values(execution["isolated_delay_stresses"], "delay stresses")
    for delay in delays:
        result[f"delay-{delay}"] = Scenario(
            f"delay-{delay}", normal.slippage_bps, normal.commission_bps, delay
        )
    result["increased-cost"] = Scenario(
        "increased-cost", result["stress-a"].slippage_bps, result["stress-a"].commission_bps, 1
    )
    result["harsher-cost"] = Scenario(
        "harsher-cost", result["stress-b"].slippage_bps, result["stress-b"].commission_bps, 1
    )
    result["plus-1-bar"] = Scenario(
        "plus-1-bar", normal.slippage_bps, normal.commission_bps, normal.execution_delay_bars + 1
    )
    result["plus-2-bars"] = Scenario(
        "plus-2-bars", normal.slippage_bps, normal.commission_bps, normal.execution_delay_bars + 2
    )
    result["zero-cost-diagnostic"] = Scenario(
        "zero-cost-diagnostic",
        result["zero-cost"].slippage_bps,
        result["zero-cost"].commission_bps,
        result["zero-cost"].execution_delay_bars,
    )
    return result


class IntradayExposedStore:
    """Small isolated registry for deterministic exploratory and controlled records."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "intraday-exposed.sqlite3"
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
                    family_id TEXT NOT NULL,
                    configuration_id TEXT NOT NULL,
                    period_id TEXT NOT NULL,
                    scenario_id TEXT NOT NULL,
                    specification_json TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK (status IN ('pending','running','completed','failed')),
                    metrics_json TEXT,
                    details_json TEXT,
                    record_fingerprint TEXT,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS controlled_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    controlled_plan_fingerprint TEXT NOT NULL,
                    run_id TEXT NOT NULL UNIQUE,
                    specification_json TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK (status IN ('pending','running','completed','failed')),
                    report_path TEXT,
                    report_sha256 TEXT,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );
                """
            )

    def bind(self, binding: Mapping[str, object]) -> None:
        encoded = canonical_json(binding)
        binding_fingerprint = fingerprint(binding)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO program_binding
                    (program_id, binding_json, binding_fingerprint)
                VALUES (?, ?, ?)
                """,
                (PROGRAM_ID, encoded, binding_fingerprint),
            )
            row = connection.execute(
                """
                SELECT binding_json, binding_fingerprint
                FROM program_binding WHERE program_id = ?
                """,
                (PROGRAM_ID,),
            ).fetchone()
        if row != (encoded, binding_fingerprint):
            raise ValueError("Intraday Exposed 001 stored program binding differs")

    def get(self, run_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT stage, family_id, configuration_id, period_id, scenario_id,
                       specification_json, status, metrics_json, details_json,
                       record_fingerprint, error
                FROM runs WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": run_id,
            "stage": row[0],
            "family_id": row[1],
            "configuration_id": row[2],
            "period_id": row[3],
            "scenario_id": row[4],
            "specification": json.loads(row[5]),
            "status": row[6],
            "metrics": None if row[7] is None else json.loads(row[7]),
            "details": None if row[8] is None else json.loads(row[8]),
            "record_fingerprint": row[9],
            "error": row[10],
        }

    def begin(self, specification: Mapping[str, object]) -> dict[str, object]:
        run_id = _run_id(specification)
        existing = self.get(run_id)
        if existing is not None:
            if existing["specification"] != canonicalize(specification):
                raise ValueError("Intraday Exposed 001 stored run specification differs")
            if existing["status"] == "completed":
                return existing
            raise ValueError(f"Intraday Exposed 001 run is terminal or in progress: {run_id}")
        context = _mapping(specification["context"], "run context")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs
                    (run_id, stage, family_id, configuration_id, period_id, scenario_id,
                     specification_json, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'running')
                """,
                (
                    run_id,
                    _text(context["stage"], "stage"),
                    _text(context["family_id"], "family ID"),
                    _text(context["configuration_id"], "configuration ID"),
                    _text(context["period_id"], "period ID"),
                    _text(context["scenario_id"], "scenario ID"),
                    canonical_json(specification),
                ),
            )
        created = self.get(run_id)
        assert created is not None
        return created

    def complete(
        self,
        run_id: str,
        metrics: Mapping[str, object],
        details: Mapping[str, object],
    ) -> dict[str, object]:
        record = {
            "run_id": run_id,
            "metrics": canonicalize(metrics),
            "details": canonicalize(details),
        }
        record_fingerprint = fingerprint(record)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET status = 'completed', metrics_json = ?, details_json = ?,
                    record_fingerprint = ?
                WHERE run_id = ? AND status = 'running'
                """,
                (
                    canonical_json(metrics),
                    canonical_json(details),
                    record_fingerprint,
                    run_id,
                ),
            )
        if cursor.rowcount != 1:
            raise ValueError("Intraday Exposed 001 run completion lost its claim")
        completed = self.get(run_id)
        assert completed is not None
        return completed

    def fail(self, run_id: str, error: Exception) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE runs SET status = 'failed', error = ?
                WHERE run_id = ? AND status = 'running'
                """,
                (f"{type(error).__name__}: {error}", run_id),
            )

    def list_runs(self) -> tuple[dict[str, object], ...]:
        with self._connect() as connection:
            run_ids = tuple(
                row[0] for row in connection.execute("SELECT run_id FROM runs ORDER BY run_id")
            )
        return tuple(cast(dict[str, object], self.get(run_id)) for run_id in run_ids)

    def reserve_controlled(
        self,
        controlled_plan_fingerprint: str,
        specifications: Sequence[Mapping[str, object]],
    ) -> None:
        with self._connect() as connection:
            for specification in specifications:
                run_id = _run_id(specification)
                reservation_id = f"iecr-{fingerprint({'run_id': run_id})[:20]}"
                connection.execute(
                    """
                    INSERT OR IGNORE INTO runs
                        (run_id, stage, family_id, configuration_id, period_id, scenario_id,
                         specification_json, status)
                    VALUES (?, 'controlled', ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        run_id,
                        _mapping(specification["context"], "context")["family_id"],
                        _mapping(specification["context"], "context")["configuration_id"],
                        _mapping(specification["context"], "context")["period_id"],
                        _mapping(specification["context"], "context")["scenario_id"],
                        canonical_json(specification),
                    ),
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO controlled_reservations
                        (reservation_id, controlled_plan_fingerprint, run_id,
                         specification_json, status)
                    VALUES (?, ?, ?, ?, 'pending')
                    """,
                    (
                        reservation_id,
                        controlled_plan_fingerprint,
                        run_id,
                        canonical_json(specification),
                    ),
                )
            rows = connection.execute(
                """
                SELECT specification_json, controlled_plan_fingerprint
                FROM controlled_reservations ORDER BY reservation_id
                """
            ).fetchall()
            run_rows = connection.execute(
                """
                SELECT run_id, specification_json
                FROM runs WHERE stage = 'controlled' ORDER BY run_id
                """
            ).fetchall()
        expected = sorted(
            (canonical_json(specification), controlled_plan_fingerprint)
            for specification in specifications
        )
        if sorted(rows) != expected:
            raise ValueError("Intraday Exposed 001 controlled reservations differ")
        expected_runs = sorted(
            (_run_id(specification), canonical_json(specification))
            for specification in specifications
        )
        if run_rows != expected_runs:
            raise ValueError("Intraday Exposed 001 controlled run specifications differ")

    def claim_controlled(self, run_id: str) -> None:
        with self._connect() as connection:
            reservation = connection.execute(
                """
                UPDATE controlled_reservations SET status = 'running'
                WHERE run_id = ? AND status = 'pending'
                """,
                (run_id,),
            )
            run = connection.execute(
                "UPDATE runs SET status = 'running' WHERE run_id = ? AND status = 'pending'",
                (run_id,),
            )
            if reservation.rowcount != 1 or run.rowcount != 1:
                raise ValueError("Intraday Exposed 001 controlled reservation cannot be claimed")

    def complete_controlled(
        self,
        run_id: str,
        metrics: Mapping[str, object],
        details: Mapping[str, object],
        report_path: Path,
        report_sha256: str,
    ) -> dict[str, object]:
        record = {
            "run_id": run_id,
            "metrics": canonicalize(metrics),
            "details": canonicalize(details),
        }
        record_fingerprint = fingerprint(record)
        with self._connect() as connection:
            run = connection.execute(
                """
                UPDATE runs
                SET status = 'completed', metrics_json = ?, details_json = ?,
                    record_fingerprint = ?
                WHERE run_id = ? AND status = 'running'
                """,
                (
                    canonical_json(metrics),
                    canonical_json(details),
                    record_fingerprint,
                    run_id,
                ),
            )
            reservation = connection.execute(
                """
                UPDATE controlled_reservations
                SET status = 'completed', report_path = ?, report_sha256 = ?
                WHERE run_id = ? AND status = 'running'
                """,
                (str(report_path.resolve()), report_sha256, run_id),
            )
            if run.rowcount != 1 or reservation.rowcount != 1:
                raise ValueError("Intraday Exposed 001 controlled completion lost its claim")
        completed = self.get(run_id)
        assert completed is not None
        return completed

    def fail_controlled(self, run_id: str, error: Exception) -> None:
        message = f"{type(error).__name__}: {error}"
        with self._connect() as connection:
            run = connection.execute(
                """
                UPDATE runs SET status = 'failed', error = ?
                WHERE run_id = ? AND status = 'running'
                """,
                (message, run_id),
            )
            reservation = connection.execute(
                """
                UPDATE controlled_reservations SET status = 'failed'
                WHERE run_id = ? AND status = 'running'
                """,
                (run_id,),
            )
            if run.rowcount != 1 or reservation.rowcount != 1:
                raise ValueError("Intraday Exposed 001 controlled failure lost its claim")

    def controlled_rows(self) -> tuple[dict[str, object], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT reservation_id, controlled_plan_fingerprint, run_id,
                       specification_json, status, report_path, report_sha256
                FROM controlled_reservations ORDER BY reservation_id
                """
            ).fetchall()
        return tuple(
            {
                "reservation_id": row[0],
                "controlled_plan_fingerprint": row[1],
                "run_id": row[2],
                "specification": json.loads(row[3]),
                "status": row[4],
                "report_path": row[5],
                "report_sha256": row[6],
            }
            for row in rows
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


class IntradayExposedStateTransitionEngine(StateTransitionBacktestEngine):
    """Reuse the FIFO state-transition engine with the frozen 0/0.5/1 state set."""

    @staticmethod
    def _validate_targets(
        targets: Sequence[TargetPosition], symbols: tuple[Symbol, ...]
    ) -> dict[Symbol, TargetPosition]:
        if len(targets) != len(symbols) or {target.symbol for target in targets} != set(symbols):
            raise BacktestError("Intraday Exposed desired state must cover SPY and QQQ exactly")
        if any(target.weight not in _ALLOWED_WEIGHTS for target in targets):
            raise BacktestError("Intraday Exposed desired weight is not frozen")
        if sum((target.weight for target in targets), _ZERO) > _ONE:
            raise BacktestError("Intraday Exposed desired state exceeds full exposure")
        return {target.symbol: target for target in targets}


@dataclass
class _EvaluationBoundStrategy:
    strategy: PortfolioStrategy
    symbols: tuple[Symbol, ...]
    evaluation_start: datetime

    @property
    def strategy_id(self) -> str:
        return self.strategy.strategy_id

    @property
    def version(self) -> str:
        return self.strategy.version

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        targets = tuple(self.strategy.on_session(bars, history))
        if bars[0].timestamp >= self.evaluation_start:
            return targets
        return tuple(TargetPosition(symbol, _ZERO, "evaluation-warmup") for symbol in self.symbols)


@dataclass(frozen=True)
class _StrategyIdentity:
    strategy_id: str
    version: str


class IntradayExposedRunner:
    def __init__(
        self,
        repository: Path,
        data_home: Path,
        *,
        progress: Callable[[str], None] | None = None,
        implementation_pr: int | None = None,
    ) -> None:
        self.repository = repository.resolve()
        self.data_home = data_home.resolve()
        self.plan = load_intraday_exposed_plan(self.repository)
        self.runtime_root = self.data_home / self.plan.runtime_namespace.name
        self.store = IntradayExposedStore(self.runtime_root)
        self.data = DatasetService(StorageLayout(self.data_home))
        self.progress = progress or (lambda _message: None)
        self.source_commit = _source_commit(self.repository)
        if implementation_pr is not None and (
            isinstance(implementation_pr, bool) or implementation_pr < 1
        ):
            raise ValueError("Intraday Exposed 001 implementation PR must be positive")
        self.implementation_pr = implementation_pr
        self.policy = load_intraday_qualification_policy(self.repository / POLICY_RELATIVE_PATH)
        controlled = _mapping(self.plan.payload["controlled_qualification"], "controlled")
        if (
            controlled.get("policy_id") != self.policy.policy_id
            or self.policy.fingerprint != REVIEWED_POLICY_FINGERPRINT
        ):
            raise ValueError("Intraday Exposed 001 qualification policy differs")
        self._bar_cache: dict[tuple[datetime, datetime], tuple[OHLCVBar, ...]] = {}
        self._verify_data()
        self.store.bind(
            {
                "schema_version": "intraday-exposed-program-binding-v1",
                "program_id": PROGRAM_ID,
                "runner_version": RUNNER_VERSION,
                "source_commit": self.source_commit,
                "implementation_pr": self.implementation_pr,
                "plan_sha256": self.plan.sha256,
                "plan_fingerprint": self.plan.fingerprint,
                "policy_id": self.policy.policy_id,
                "policy_fingerprint": self.policy.fingerprint,
                "datasets": [
                    {
                        "dataset_id": item.dataset_id,
                        "fingerprint": item.fingerprint,
                        "raw_fingerprint": item.raw_fingerprint,
                    }
                    for item in self.plan.datasets
                ],
                "authority": _AUTHORITY,
            }
        )

    def _verify_data(self) -> None:
        data = _mapping(self.plan.payload["data"], "data")
        expected_symbols = _strings(data["symbols"], "symbols")
        for binding in self.plan.datasets:
            manifest = self.data.describe(binding.dataset_id)
            validation = self.data.validate(binding.dataset_id)
            symbols = tuple(sorted(item["value"] for item in manifest.get("symbols", [])))
            if (
                validation.get("valid") is not True
                or validation.get("fingerprint") != binding.fingerprint
                or manifest.get("timeframe") != "5m"
                or manifest.get("provider") != data["provider"]
                or manifest.get("feed") != data["feed"]
                or manifest.get("adjustment_policy") != data["adjustment_policy"]
                or manifest.get("calendar_policy") != data["calendar_policy"]
                or manifest.get("timestamp_policy") != data["timestamp_policy"]
                or manifest.get("universe_id") != data["universe_id"]
                or manifest.get("universe_fingerprint") != data["universe_fingerprint"]
                or symbols != expected_symbols
                or manifest.get("raw_artifact_hashes") != [binding.raw_fingerprint]
                or _mapping(manifest["requested_range"], "requested range").get("start")
                != binding.start.isoformat().replace("+00:00", "Z")
                or _mapping(manifest["requested_range"], "requested range").get("end")
                != binding.end.isoformat().replace("+00:00", "Z")
            ):
                raise ValueError(f"Intraday Exposed 001 dataset differs: {binding.dataset_id}")

    def _bars(self, period: EvaluationPeriod) -> tuple[OHLCVBar, ...]:
        key = (period.context_start, period.evaluation_end)
        cached = self._bar_cache.get(key)
        if cached is not None:
            return cached
        data = _mapping(self.plan.payload["data"], "data")
        bars: list[OHLCVBar] = []
        for binding in self.plan.datasets:
            start = max(period.context_start, binding.start)
            end = min(period.evaluation_end, binding.end)
            if start > end:
                continue
            bars.extend(
                self.data.load_bars_range(
                    binding.dataset_id,
                    TimestampRange(start, end),
                    expected_fingerprint=binding.fingerprint,
                    expected_universe_id=_text(data["universe_id"], "universe ID"),
                    expected_universe_fingerprint=_text(
                        data["universe_fingerprint"], "universe fingerprint"
                    ),
                )
            )
        ordered = tuple(sorted(bars, key=lambda bar: (bar.timestamp, bar.symbol.value)))
        if not ordered or ordered[0].timestamp != period.context_start:
            raise ValueError(f"Intraday Exposed 001 period start is missing: {period.period_id}")
        if ordered[-1].timestamp != period.evaluation_end:
            raise ValueError(f"Intraday Exposed 001 period end is missing: {period.period_id}")
        self._bar_cache[key] = ordered
        return ordered

    def _specification(
        self,
        configuration: Configuration,
        period: EvaluationPeriod,
        scenario: Scenario,
        *,
        stage: str,
        parent_run_id: str | None = None,
        controlled_plan_fingerprint: str | None = None,
        neighbor_of: str | None = None,
        controlled_role: str | None = None,
    ) -> dict[str, object]:
        return {
            "schema_version": RUN_SCHEMA,
            "program_id": PROGRAM_ID,
            "runner_version": RUNNER_VERSION,
            "source_commit": self.source_commit,
            "plan_sha256": self.plan.sha256,
            "plan_fingerprint": self.plan.fingerprint,
            "configuration": {
                "configuration_id": configuration.configuration_id,
                "family_id": configuration.family_id,
                "family_name": configuration.family_name,
                "strategy_id": configuration.strategy_id,
                "strategy_version": "1",
                "parameters": dict(configuration.parameters),
            },
            "period": {
                "period_id": period.period_id,
                "context_start": period.context_start,
                "evaluation_start": period.evaluation_start,
                "evaluation_end": period.evaluation_end,
            },
            "scenario": {
                "scenario_id": scenario.scenario_id,
                "slippage_bps": scenario.slippage_bps,
                "commission_bps": scenario.commission_bps,
                "execution_delay_bars": scenario.execution_delay_bars,
            },
            "execution": {
                "timeframe": "5m",
                "session_policy": _mapping(self.plan.payload["execution"], "execution")[
                    "session_policy"
                ],
                "execution_model": _mapping(self.plan.payload["execution"], "execution")[
                    "execution_model"
                ],
                "earliest_fill_semantics": _mapping(self.plan.payload["execution"], "execution")[
                    "earliest_fill_semantics"
                ],
                "queue_policy": _mapping(self.plan.payload["execution"], "execution")[
                    "queue_policy"
                ],
            },
            "datasets": [
                {"dataset_id": item.dataset_id, "fingerprint": item.fingerprint}
                for item in self.plan.datasets
                if item.start <= period.evaluation_end and item.end >= period.context_start
            ],
            "parent_run_id": parent_run_id,
            "neighbor_of": neighbor_of,
            "controlled_plan_fingerprint": controlled_plan_fingerprint,
            "controlled_role": controlled_role,
            "context": {
                "stage": stage,
                "family_id": configuration.family_id,
                "configuration_id": configuration.configuration_id,
                "period_id": period.period_id,
                "scenario_id": scenario.scenario_id,
                "controlled_role": controlled_role,
            },
            "authority": _AUTHORITY,
        }

    def _execute(
        self,
        configuration: Configuration,
        period: EvaluationPeriod,
        scenario: Scenario,
        *,
        stage: str,
        parent_run_id: str | None = None,
        controlled_plan_fingerprint: str | None = None,
        neighbor_of: str | None = None,
        controlled_role: str | None = None,
        controlled: bool = False,
    ) -> dict[str, object]:
        specification = self._specification(
            configuration,
            period,
            scenario,
            stage=stage,
            parent_run_id=parent_run_id,
            controlled_plan_fingerprint=controlled_plan_fingerprint,
            neighbor_of=neighbor_of,
            controlled_role=controlled_role,
        )
        run_id = _run_id(specification)
        existing = self.store.get(run_id)
        if existing is not None and existing["status"] in {"completed", "failed"}:
            return existing
        if controlled:
            self.store.claim_controlled(run_id)
            record = self.store.get(run_id)
            assert record is not None
        else:
            record = self.store.begin(specification)
            if record["status"] == "completed":
                return record
        try:
            bars = self._bars(period)
            inner = build_intraday_exposed_strategy(
                configuration.strategy_id,
                self.plan.symbols,
                configuration.parameter_mapping,
            )
            strategy = _EvaluationBoundStrategy(inner, self.plan.symbols, period.evaluation_start)
            cost_model = CostModel(
                f"intraday-exposed-{scenario.scenario_id}-v1",
                scenario.slippage_bps,
                scenario.commission_bps,
            )
            result = IntradayExposedStateTransitionEngine(
                self.plan.initial_cash,
                cost_model,
                scenario.execution_delay_bars,
            ).run(bars, strategy)
            evaluation_bars = tuple(
                bar
                for bar in bars
                if period.evaluation_start <= bar.timestamp <= period.evaluation_end
            )
            accounting = _evaluation_accounting(
                result,
                evaluation_bars,
                period,
                self.plan.initial_cash,
                cost_model,
                scenario.execution_delay_bars,
            )
            metrics, details, report = _report(
                specification,
                result,
                accounting,
                evaluation_bars,
                period,
            )
            if controlled:
                reports = self.runtime_root / "controlled-reports"
                destination = reports / f"{run_id}.json"
                _write_create_only(destination, report)
                report_sha256 = _sha256_path(destination)
                completed = self.store.complete_controlled(
                    run_id,
                    metrics,
                    details,
                    destination,
                    report_sha256,
                )
            else:
                completed = self.store.complete(run_id, metrics, details)
            return completed
        except Exception as error:
            if controlled:
                self.store.fail_controlled(run_id, error)
            else:
                self.store.fail(run_id, error)
            raise

    def run(self) -> dict[str, object]:
        with _exclusive_file_lock(self.runtime_root / "campaign.lock"):
            self._recover_interrupted_runs()
            return self._run_locked()

    def _run_locked(self) -> dict[str, object]:
        discovery = self._run_discovery()
        self._require_no_failed_runs("discovery")
        walk_forward = self._run_walk_forward(discovery["selected"])
        self._require_no_failed_runs("walk-forward")
        screens = self._run_serious_screen(walk_forward["selected"])
        self._require_no_failed_runs("final exposed stress")
        cohort = self._select_cohort(screens)
        freeze = self._freeze_cohort(cohort, screens)
        controlled = self._run_controlled(cohort, freeze) if cohort else []
        self._require_no_failed_runs("controlled qualification")
        report = self._write_final_report(
            discovery, walk_forward, screens, cohort, freeze, controlled
        )
        return {
            "program_id": PROGRAM_ID,
            "outcome": report["outcome"],
            "source_commit": self.source_commit,
            "cohort_size": len(cohort),
            "controlled_pass_count": sum(item["passed"] is True for item in controlled),
            "final_report_json": str((self.runtime_root / "final-report.json").resolve()),
            "final_report_json_sha256": _sha256_path(self.runtime_root / "final-report.json"),
            "final_report_markdown": str((self.runtime_root / "final-report.md").resolve()),
            "final_report_markdown_sha256": _sha256_path(self.runtime_root / "final-report.md"),
            "authority": _AUTHORITY,
        }

    def _require_no_failed_runs(self, stage: str) -> None:
        failed = tuple(run for run in self.store.list_runs() if run["status"] == "failed")
        if failed:
            raise RuntimeError(
                f"Intraday Exposed 001 is incomplete after {stage}: "
                f"{len(failed)} terminal runtime failure(s)"
            )

    def _recover_interrupted_runs(self) -> None:
        for row in self.store.controlled_rows():
            if row["status"] != "running":
                continue
            run_id = _text(row["run_id"], "controlled run ID")
            destination = self.runtime_root / "controlled-reports" / f"{run_id}.json"
            report, error = self._load_controlled_report(row, destination)
            if report is None:
                self.store.fail_controlled(
                    run_id,
                    RuntimeError(
                        "interrupted claimed execution was not rerun"
                        + ("" if error is None else f": {error}")
                    ),
                )
                continue
            metrics = _mapping(report["metrics"], "controlled metrics")
            evidence = _mapping(report["execution_evidence"], "execution evidence")
            details = {**evidence, "report_fingerprint": report["report_fingerprint"]}
            self.store.complete_controlled(
                run_id,
                metrics,
                details,
                destination,
                _sha256_path(destination),
            )
        for row in self.store.list_runs():
            if row["status"] == "running":
                self.store.fail(
                    _text(row["run_id"], "run ID"),
                    RuntimeError("interrupted claimed execution was not rerun"),
                )

    def _run_discovery(self) -> dict[str, object]:
        rows: dict[str, dict[str, dict[str, object]]] = {}
        strongest: list[dict[str, object]] = []
        selected: list[str] = []
        maximum = _positive_int(
            _mapping(self.plan.payload["search"], "search")[
                "maximum_walk_forward_candidates_per_family"
            ],
            "maximum walk-forward candidates",
        )
        for index, configuration in enumerate(self.plan.configurations, start=1):
            self.progress(
                f"discovery {index}/{len(self.plan.configurations)} "
                f"{configuration.configuration_id}"
            )
            normal = self._execute(
                configuration,
                self.plan.discovery,
                self.plan.scenarios["normal"],
                stage="discovery",
            )
            zero = self._execute(
                configuration,
                self.plan.discovery,
                self.plan.scenarios["zero-cost"],
                stage="discovery-zero-cost",
                parent_run_id=_text(normal["run_id"], "normal run ID"),
            )
            rows[configuration.configuration_id] = {"normal": normal, "zero-cost": zero}
        for family in _family_ids(self.plan):
            family_rows = [
                (configuration, rows[configuration.configuration_id])
                for configuration in self.plan.family_configurations(family)
            ]
            completed_family_rows = [
                item
                for item in family_rows
                if all(_record_completed(record) for record in item[1].values())
            ]
            ordered = sorted(
                completed_family_rows,
                key=lambda value: (
                    -_metric(value[1]["normal"], "total_return"),
                    -_metric(value[1]["zero-cost"], "total_return"),
                    _metric(value[1]["normal"], "turnover"),
                    value[0].configuration_id,
                ),
            )
            top = ordered[0] if ordered else family_rows[0]
            strongest.append(_configuration_summary(top[0], top[1]))
            passing_ids = [
                configuration.configuration_id
                for configuration, records in ordered
                if self._passes_discovery(records)
            ]
            selected.extend(passing_ids[:maximum])
        return {"rows": rows, "selected": tuple(selected), "strongest": strongest}

    def _passes_discovery(self, records: Mapping[str, dict[str, object]]) -> bool:
        normal = records["normal"]
        zero = records["zero-cost"]
        if not _record_completed(normal) or not _record_completed(zero):
            return False
        gates = _mapping(
            _mapping(self.plan.payload["search"], "search")["discovery_gates"],
            "discovery gates",
        )
        gross_profit = _metric(zero, "total_return") * self.plan.initial_cash
        ratio = _metric(normal, "cost_paid_total") / gross_profit if gross_profit > 0 else None
        return bool(
            _metric(normal, "total_return") > _decimal(gates["normal_total_return_gt"], "gate")
            and _metric(zero, "total_return") > _decimal(gates["zero_cost_total_return_gt"], "gate")
            and _metric(normal, "max_drawdown") <= _decimal(gates["max_drawdown_lte"], "gate")
            and _metric(normal, "completed_round_trip_count")
            >= Decimal(_positive_int(gates["completed_round_trips_gte"], "gate"))
            and _metric(normal, "turnover") <= _decimal(gates["turnover_lte"], "gate")
            and ratio is not None
            and ratio <= _decimal(gates["cost_to_zero_cost_profit_lte"], "gate")
        )

    def _run_walk_forward(self, selected_ids: object) -> dict[str, object]:
        selected_values = tuple(cast(Sequence[str], selected_ids))
        rows: dict[str, dict[str, dict[str, dict[str, object]]]] = {}
        selected: list[str] = []
        maximum = _positive_int(
            _mapping(self.plan.payload["search"], "search")[
                "maximum_serious_candidates_per_family"
            ],
            "maximum serious candidates",
        )
        for position, configuration_id in enumerate(selected_values, start=1):
            configuration = self.plan.configuration(configuration_id)
            self.progress(f"walk-forward {position}/{len(selected_values)} {configuration_id}")
            fold_rows: dict[str, dict[str, dict[str, object]]] = {}
            for fold in self.plan.walk_forward_folds:
                normal = self._execute(
                    configuration, fold, self.plan.scenarios["normal"], stage="walk-forward"
                )
                zero = self._execute(
                    configuration,
                    fold,
                    self.plan.scenarios["zero-cost"],
                    stage="walk-forward-zero-cost",
                    parent_run_id=_text(normal["run_id"], "normal run ID"),
                )
                fold_rows[fold.period_id] = {"normal": normal, "zero-cost": zero}
            rows[configuration_id] = fold_rows
        for family in _family_ids(self.plan):
            eligible = [
                (self.plan.configuration(configuration_id), rows[configuration_id])
                for configuration_id in selected_values
                if self.plan.configuration(configuration_id).family_id == family
                and self._passes_walk_forward(rows[configuration_id])
            ]
            ordered = sorted(
                eligible,
                key=lambda value: (
                    -min(
                        _metric(records["normal"], "total_return") for records in value[1].values()
                    ),
                    -sum(
                        (
                            _metric(records["normal"], "total_return")
                            for records in value[1].values()
                        ),
                        _ZERO,
                    ),
                    sum(
                        (_metric(records["normal"], "turnover") for records in value[1].values()),
                        _ZERO,
                    ),
                    value[0].configuration_id,
                ),
            )
            selected.extend(item[0].configuration_id for item in ordered[:maximum])
        return {"rows": rows, "selected": tuple(selected)}

    def _passes_walk_forward(self, folds: Mapping[str, Mapping[str, dict[str, object]]]) -> bool:
        if set(folds) != {fold.period_id for fold in self.plan.walk_forward_folds} or any(
            set(records) != {"normal", "zero-cost"}
            or any(not _record_completed(record) for record in records.values())
            for records in folds.values()
        ):
            return False
        gates = _mapping(
            _mapping(self.plan.payload["search"], "search")["walk_forward_gates"],
            "walk-forward gates",
        )
        normals = tuple(item["normal"] for item in folds.values())
        zeros = tuple(item["zero-cost"] for item in folds.values())
        normal_returns = tuple(_metric(item, "total_return") for item in normals)
        zero_returns = tuple(_metric(item, "total_return") for item in zeros)
        gross_profit = sum(zero_returns, _ZERO) * self.plan.initial_cash
        cost_ratio = (
            sum((_metric(item, "cost_paid_total") for item in normals), _ZERO) / gross_profit
            if gross_profit > 0
            else None
        )
        symbol_profit: dict[str, Decimal] = defaultdict(lambda: _ZERO)
        for item in normals:
            details = _details(item)
            for symbol, value in _mapping(details["symbol_profit"], "symbol profit").items():
                symbol_profit[symbol] += _decimal(value, "symbol profit")
        positive = tuple(value for value in symbol_profit.values() if value > 0)
        concentration = max(positive) / sum(positive, _ZERO) if positive else None
        return bool(
            sum(normal_returns, _ZERO) > _decimal(gates["aggregate_normal_total_return_gt"], "gate")
            and sum(zero_returns, _ZERO)
            > _decimal(gates["aggregate_zero_cost_total_return_gt"], "gate")
            and sum(value > 0 for value in normal_returns)
            >= _positive_int(gates["positive_normal_folds_gte"], "gate")
            and min(normal_returns) >= _decimal(gates["worst_normal_fold_return_gte"], "gate")
            and sum((_metric(item, "completed_round_trip_count") for item in normals), _ZERO)
            >= Decimal(_positive_int(gates["aggregate_completed_round_trips_gte"], "gate"))
            and max(_metric(item, "max_drawdown") for item in normals)
            <= _decimal(gates["max_fold_drawdown_lte"], "gate")
            and cost_ratio is not None
            and cost_ratio <= _decimal(gates["cost_to_zero_cost_profit_lte"], "gate")
            and concentration is not None
            and concentration
            <= _decimal(gates["best_symbol_positive_profit_concentration_lte"], "gate")
        )

    def _run_serious_screen(self, selected_ids: object) -> list[dict[str, object]]:
        selected = tuple(cast(Sequence[str], selected_ids))
        screens: list[dict[str, object]] = []
        final_fold = self.plan.walk_forward_folds[-1]
        robustness = _mapping(self.plan.payload["robustness"], "robustness")
        minimum_neighbors = _positive_int(
            robustness["minimum_neighbors_per_candidate"], "minimum neighbors"
        )
        for position, configuration_id in enumerate(selected, start=1):
            configuration = self.plan.configuration(configuration_id)
            self.progress(f"serious {position}/{len(selected)} {configuration_id}")
            normal = self._execute(
                configuration, final_fold, self.plan.scenarios["normal"], stage="walk-forward"
            )
            zero = self._execute(
                configuration,
                final_fold,
                self.plan.scenarios["zero-cost"],
                stage="walk-forward-zero-cost",
                parent_run_id=_text(normal["run_id"], "normal run ID"),
            )
            variants = {
                name: self._execute(
                    configuration,
                    final_fold,
                    self.plan.scenarios[name],
                    stage="final-exposed-stress",
                    parent_run_id=_text(normal["run_id"], "normal run ID"),
                )
                for name in ("stress-a", "stress-b", "delay-2", "delay-3")
            }
            neighbors = self.plan.neighbors(configuration)
            neighbor_rows: dict[str, dict[str, dict[str, object]]] = {}
            if len(neighbors) >= minimum_neighbors:
                for neighbor in neighbors:
                    fold_rows: dict[str, dict[str, object]] = {}
                    for fold in self.plan.walk_forward_folds:
                        fold_rows[fold.period_id] = self._execute(
                            neighbor,
                            fold,
                            self.plan.scenarios["normal"],
                            stage="parameter-neighbor",
                            parent_run_id=_text(normal["run_id"], "normal run ID"),
                            neighbor_of=configuration.configuration_id,
                        )
                    neighbor_rows[neighbor.configuration_id] = fold_rows
            screen = self._serious_screen(
                configuration, normal, zero, variants, neighbors, neighbor_rows
            )
            screens.append(screen)
        return screens

    def _serious_screen(
        self,
        configuration: Configuration,
        normal: dict[str, object],
        zero: dict[str, object],
        variants: Mapping[str, dict[str, object]],
        neighbors: Sequence[Configuration],
        neighbor_rows: Mapping[str, Mapping[str, dict[str, object]]],
    ) -> dict[str, object]:
        gates = _mapping(
            _mapping(self.plan.payload["search"], "search")["final_exposed_stress_gates"],
            "final stress gates",
        )
        candidate_fold_records = {
            fold.period_id: self._execute(
                configuration,
                fold,
                self.plan.scenarios["normal"],
                stage="walk-forward",
            )
            for fold in self.plan.walk_forward_folds
        }
        all_records = (
            normal,
            zero,
            *variants.values(),
            *candidate_fold_records.values(),
            *(record for folds in neighbor_rows.values() for record in folds.values()),
        )
        if any(not _record_completed(record) for record in all_records):
            failed_returns = {
                name: _metric_or_none(record, "total_return") for name, record in variants.items()
            }
            failed_fold_returns = {
                fold_id: _metric_or_none(record, "total_return")
                for fold_id, record in candidate_fold_records.items()
            }
            failed_neighbor_returns = {
                neighbor_id: (
                    sum(
                        (_metric(record, "total_return") for record in folds.values()),
                        _ZERO,
                    )
                    if all(_record_completed(record) for record in folds.values())
                    else None
                )
                for neighbor_id, folds in neighbor_rows.items()
            }
            return {
                "configuration": _configuration_payload(configuration),
                "passed": False,
                "reasons": ["runtime-failure"],
                "normal_run_id": normal["run_id"],
                "zero_cost_run_id": zero["run_id"],
                "variant_run_ids": {name: item["run_id"] for name, item in variants.items()},
                "normal_return": _metric_or_none(normal, "total_return"),
                "zero_cost_return": _metric_or_none(zero, "total_return"),
                "stress_returns": failed_returns,
                "stress_retentions": {name: None for name in variants},
                "neighbor_ids": [item.configuration_id for item in neighbors],
                "neighbor_returns": failed_neighbor_returns,
                "neighbor_retentions": {
                    neighbor_id: None for neighbor_id in failed_neighbor_returns
                },
                "positive_neighbor_fraction": None,
                "fold_returns": failed_fold_returns,
                "worst_fold_return": None,
                "fold_return_dispersion": None,
                "turnover": _metric_or_none(normal, "turnover"),
                "decision_trace_identity": False,
                "signal_timestamp_identity": False,
                "decision_cadence_identity": False,
            }
        base_return = _metric(normal, "total_return")
        returns = {name: _metric(record, "total_return") for name, record in variants.items()}
        retentions = {
            name: value / base_return if base_return > 0 else None
            for name, value in returns.items()
        }
        fold_returns = {
            fold_id: _metric(record, "total_return")
            for fold_id, record in candidate_fold_records.items()
        }
        candidate_fold_returns = tuple(fold_returns.values())
        candidate_aggregate = sum(candidate_fold_returns, _ZERO)
        neighbor_aggregates = {
            neighbor_id: sum((_metric(record, "total_return") for record in folds.values()), _ZERO)
            for neighbor_id, folds in neighbor_rows.items()
        }
        neighbor_retentions = {
            neighbor_id: value / candidate_aggregate if candidate_aggregate > 0 else None
            for neighbor_id, value in neighbor_aggregates.items()
        }
        valid_neighbor_retentions = tuple(
            value for value in neighbor_retentions.values() if value is not None
        )
        positive_fraction = (
            Decimal(sum(value > 0 for value in neighbor_aggregates.values()))
            / Decimal(len(neighbor_aggregates))
            if neighbor_aggregates
            else None
        )
        robustness = _mapping(self.plan.payload["robustness"], "robustness")
        traces = {
            _text(_details(item)["decision_trace_fingerprint"], "decision trace")
            for item in (normal, zero, *variants.values())
        }
        signals = {
            _text(_details(item)["signal_timestamp_fingerprint"], "signal trace")
            for item in (normal, zero, *variants.values())
        }
        decision_counts = {
            int(_metric(item, "decision_count")) for item in (normal, *variants.values())
        }
        reasons: list[str] = []
        if len(neighbors) < _positive_int(
            robustness["minimum_neighbors_per_candidate"], "minimum neighbors"
        ):
            reasons.append("insufficient-parameter-neighbors")
        if base_return <= _decimal(gates["normal_total_return_gt"], "gate"):
            reasons.append("normal-return")
        if any(
            value <= _decimal(gates[f"{name.replace('-', '_')}_total_return_gt"], "gate")
            for name, value in returns.items()
            if name in {"stress-a", "stress-b"}
        ):
            reasons.append("cost-stress-return")
        if returns["delay-2"] <= _decimal(gates["delay_2_total_return_gt"], "gate") or returns[
            "delay-3"
        ] <= _decimal(gates["delay_3_total_return_gt"], "gate"):
            reasons.append("delay-stress-return")
        minimum_retention = _decimal(gates["minimum_return_retention_gte"], "gate")
        if any(value is None or value < minimum_retention for value in retentions.values()):
            reasons.append("stress-retention")
        if positive_fraction is None or positive_fraction < _decimal(
            robustness["positive_neighbor_fraction_gte"], "neighbor gate"
        ):
            reasons.append("neighbor-positive-fraction")
        if not valid_neighbor_retentions or min(valid_neighbor_retentions) < _decimal(
            robustness["minimum_neighbor_return_retention_gte"], "neighbor gate"
        ):
            reasons.append("neighbor-retention")
        if len(traces) != 1 or len(signals) != 1 or len(decision_counts) != 1:
            reasons.append("execution-trace-identity")
        return {
            "configuration": _configuration_payload(configuration),
            "passed": not reasons,
            "reasons": reasons,
            "normal_run_id": normal["run_id"],
            "zero_cost_run_id": zero["run_id"],
            "variant_run_ids": {name: item["run_id"] for name, item in variants.items()},
            "normal_return": base_return,
            "zero_cost_return": _metric(zero, "total_return"),
            "stress_returns": returns,
            "stress_retentions": retentions,
            "neighbor_ids": [item.configuration_id for item in neighbors],
            "neighbor_returns": neighbor_aggregates,
            "neighbor_retentions": neighbor_retentions,
            "positive_neighbor_fraction": positive_fraction,
            "fold_returns": fold_returns,
            "worst_fold_return": min(candidate_fold_returns),
            "fold_return_dispersion": Decimal(str(pstdev(candidate_fold_returns))),
            "turnover": _metric(normal, "turnover"),
            "decision_trace_identity": len(traces) == 1,
            "signal_timestamp_identity": len(signals) == 1,
            "decision_cadence_identity": len(decision_counts) == 1,
        }

    def _select_cohort(self, screens: Sequence[Mapping[str, object]]) -> list[Configuration]:
        passing = [item for item in screens if item["passed"] is True]
        ordered = sorted(
            passing,
            key=lambda item: (
                -_decimal(item["worst_fold_return"], "worst fold return"),
                -_decimal(
                    _mapping(item["stress_returns"], "stress returns")["stress-b"],
                    "Stress B return",
                ),
                _decimal(item["turnover"], "turnover"),
                _mapping(item["configuration"], "configuration")["configuration_id"],
            ),
        )
        maximum = _positive_int(
            _mapping(self.plan.payload["search"], "search")["maximum_final_cohort"],
            "maximum cohort",
        )
        return [
            self.plan.configuration(
                _text(
                    _mapping(item["configuration"], "configuration")["configuration_id"],
                    "configuration ID",
                )
            )
            for item in ordered[:maximum]
        ]

    def _controlled_records(self, cohort: Sequence[Configuration]) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        minimum_neighbors = _positive_int(
            _mapping(self.plan.payload["robustness"], "robustness")[
                "minimum_neighbors_per_candidate"
            ],
            "minimum neighbors",
        )
        for configuration in cohort:
            base_specification = self._specification(
                configuration,
                self.plan.controlled_period,
                self.plan.scenarios["normal"],
                stage="controlled",
                controlled_role="base",
            )
            base_run_id = _run_id(base_specification)

            def add(
                role: str,
                run_configuration: Configuration,
                scenario: Scenario,
                *,
                parent_run_id: str | None,
                neighbor_of: str | None = None,
                specification: Mapping[str, object] | None = None,
                candidate_configuration_id: str = configuration.configuration_id,
            ) -> None:
                frozen = dict(
                    specification
                    or self._specification(
                        run_configuration,
                        self.plan.controlled_period,
                        scenario,
                        stage="controlled",
                        parent_run_id=parent_run_id,
                        neighbor_of=neighbor_of,
                        controlled_role=role,
                    )
                )
                records.append(
                    {
                        "ordinal": len(records) + 1,
                        "candidate_configuration_id": candidate_configuration_id,
                        "role": role,
                        "run_configuration_id": run_configuration.configuration_id,
                        "run_id": _run_id(frozen),
                        "specification": frozen,
                    }
                )

            add(
                "base",
                configuration,
                self.plan.scenarios["normal"],
                parent_run_id=None,
                specification=base_specification,
            )
            for role in (
                "increased-cost",
                "harsher-cost",
                "plus-1-bar",
                "plus-2-bars",
                "zero-cost-diagnostic",
            ):
                add(
                    role,
                    configuration,
                    self.plan.scenarios[role],
                    parent_run_id=base_run_id,
                )
            neighbors = self.plan.neighbors(configuration)
            if len(neighbors) < minimum_neighbors:
                raise ValueError("Intraday Exposed 001 frozen cohort lacks required neighbors")
            for neighbor in neighbors:
                add(
                    "parameter-neighbor",
                    neighbor,
                    self.plan.scenarios["normal"],
                    parent_run_id=base_run_id,
                    neighbor_of=configuration.configuration_id,
                )
        return records

    def _freeze_cohort(
        self,
        cohort: Sequence[Configuration],
        screens: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        cohort_rows = [
            {
                **_configuration_payload(configuration),
                "neighbors": [
                    _configuration_payload(neighbor)
                    for neighbor in self.plan.neighbors(configuration)
                ],
            }
            for configuration in cohort
        ]
        controlled_plan: dict[str, object] | None = None
        controlled_artifact: dict[str, object] | None = None
        if cohort:
            controlled_plan = {
                "schema_version": CONTROLLED_PLAN_SCHEMA,
                "status": "frozen-before-any-controlled-result",
                "program_id": PROGRAM_ID,
                "runner_version": RUNNER_VERSION,
                "source_commit": self.source_commit,
                "implementation_pr": self.implementation_pr,
                "plan_sha256": self.plan.sha256,
                "plan_fingerprint": self.plan.fingerprint,
                "policy_id": self.policy.policy_id,
                "policy_fingerprint": self.policy.fingerprint,
                "cohort_fingerprint": fingerprint(cohort_rows),
                "records": self._controlled_records(cohort),
                "authority": _AUTHORITY,
            }
            controlled_plan["record_count"] = len(cast(list[object], controlled_plan["records"]))
            controlled_plan["controlled_plan_fingerprint"] = fingerprint(controlled_plan)
            controlled_path = self.runtime_root / "controlled-plan.json"
            _write_create_only(controlled_path, controlled_plan)
            controlled_artifact = {
                "path": controlled_path.name,
                "sha256": _sha256_path(controlled_path),
                "fingerprint": controlled_plan["controlled_plan_fingerprint"],
                "record_count": controlled_plan["record_count"],
            }
        selected_ids = {item.configuration_id for item in cohort}
        selected_screens = [
            dict(item)
            for item in screens
            if _text(
                _mapping(item["configuration"], "configuration")["configuration_id"],
                "configuration ID",
            )
            in selected_ids
        ]
        payload: dict[str, object] = {
            "schema_version": COHORT_SCHEMA,
            "status": "frozen-before-any-controlled-result",
            "program_id": PROGRAM_ID,
            "runner_version": RUNNER_VERSION,
            "source_commit": self.source_commit,
            "implementation_pr": self.implementation_pr,
            "plan_sha256": self.plan.sha256,
            "plan_fingerprint": self.plan.fingerprint,
            "implementation": {
                "strategy_path": "src/systematic_trading_lab/intraday_exposed_strategies.py",
                "strategy_sha256": _sha256_path(
                    self.repository / "src/systematic_trading_lab/intraday_exposed_strategies.py"
                ),
                "runner_path": "src/systematic_trading_lab/intraday_exposed_runner.py",
                "runner_sha256": _sha256_path(
                    self.repository / "src/systematic_trading_lab/intraday_exposed_runner.py"
                ),
            },
            "screened_candidate_count": len(screens),
            "passing_candidate_count": sum(item["passed"] is True for item in screens),
            "screens_fingerprint": fingerprint(screens),
            "selected_screen_evidence": selected_screens,
            "cohort": cohort_rows,
            "cohort_fingerprint": fingerprint(cohort_rows),
            "controlled_plan_artifact": controlled_artifact,
            "authority": _AUTHORITY,
        }
        payload["cohort_freeze_fingerprint"] = fingerprint(payload)
        path = self.runtime_root / "cohort-freeze.json"
        _write_create_only(path, payload)
        self.progress(f"froze final cohort with {len(cohort)} candidate(s)")
        return {
            "payload": payload,
            "path": path,
            "sha256": _sha256_path(path),
            "controlled_plan": controlled_plan,
            "controlled_artifact": controlled_artifact,
        }

    def _run_controlled(
        self,
        cohort: Sequence[Configuration],
        freeze: Mapping[str, object],
    ) -> list[dict[str, object]]:
        plan = _mapping(freeze.get("controlled_plan"), "controlled plan")
        claimed_fingerprint = _text(
            plan["controlled_plan_fingerprint"], "controlled plan fingerprint"
        )
        unsigned = dict(plan)
        unsigned.pop("controlled_plan_fingerprint")
        if fingerprint(unsigned) != claimed_fingerprint:
            raise ValueError("Intraday Exposed 001 controlled plan fingerprint differs")
        controlled_path = self.runtime_root / "controlled-plan.json"
        cohort_path = self.runtime_root / "cohort-freeze.json"
        if not controlled_path.is_file() or not cohort_path.is_file():
            raise ValueError("Intraday Exposed 001 freeze artifacts are missing")
        if _sha256_path(cohort_path) != freeze.get("sha256"):
            raise ValueError("Intraday Exposed 001 cohort freeze artifact differs")
        artifact = _mapping(freeze.get("controlled_artifact"), "controlled artifact")
        if _sha256_path(controlled_path) != artifact.get("sha256"):
            raise ValueError("Intraday Exposed 001 controlled plan artifact differs")
        records_value = plan.get("records")
        if not isinstance(records_value, list) or not records_value:
            raise ValueError("Intraday Exposed 001 controlled records differ")
        records = tuple(_mapping(item, "controlled record") for item in records_value)
        specifications = tuple(
            _mapping(record["specification"], "controlled specification") for record in records
        )
        self.store.reserve_controlled(claimed_fingerprint, specifications)
        for position, record in enumerate(records, start=1):
            configuration = self.plan.configuration(
                _text(record["run_configuration_id"], "run configuration ID")
            )
            specification = _mapping(record["specification"], "controlled specification")
            context = _mapping(specification["context"], "controlled context")
            scenario_id = _text(context["scenario_id"], "controlled scenario ID")
            role = _text(record["role"], "controlled role")
            scenario = self.plan.scenarios.get(scenario_id)
            if scenario is None:
                raise ValueError(f"Intraday Exposed 001 controlled scenario differs: {scenario_id}")
            expected = self._specification(
                configuration,
                self.plan.controlled_period,
                scenario,
                stage="controlled",
                parent_run_id=cast(str | None, specification.get("parent_run_id")),
                neighbor_of=cast(str | None, specification.get("neighbor_of")),
                controlled_role=role,
            )
            if canonicalize(expected) != canonicalize(specification):
                raise ValueError("Intraday Exposed 001 controlled specification drifted")
            self.progress(f"controlled {position}/{len(records)} {record['run_id']}")
            try:
                self._execute(
                    configuration,
                    self.plan.controlled_period,
                    scenario,
                    stage="controlled",
                    parent_run_id=cast(str | None, specification.get("parent_run_id")),
                    neighbor_of=cast(str | None, specification.get("neighbor_of")),
                    controlled_role=role,
                    controlled=True,
                )
            except Exception as error:
                self.progress(
                    f"controlled failed {record['run_id']}: {type(error).__name__}: {error}"
                )
        rows = self.store.controlled_rows()
        by_run_id = {_text(row["run_id"], "controlled run ID"): row for row in rows}
        expected_ids = {_text(record["run_id"], "controlled run ID") for record in records}
        if set(by_run_id) != expected_ids:
            raise ValueError("Intraday Exposed 001 controlled registry closure differs")
        accounted = True
        for record in records:
            run_id = _text(record["run_id"], "controlled run ID")
            row = by_run_id[run_id]
            if (
                row["controlled_plan_fingerprint"] != claimed_fingerprint
                or canonicalize(row["specification"]) != canonicalize(record["specification"])
                or row["status"] not in {"completed", "failed"}
            ):
                accounted = False
        if not accounted:
            raise ValueError("Intraday Exposed 001 controlled budget is not terminal")
        return [
            self._qualify_controlled_candidate(
                configuration,
                records,
                by_run_id,
                freeze,
                claimed_fingerprint,
                accounted,
            )
            for configuration in cohort
        ]

    def _controlled_report(
        self,
        record: Mapping[str, object],
        row: Mapping[str, object],
    ) -> tuple[Mapping[str, object] | None, str | None]:
        if row.get("status") != "completed":
            return None, f"registry-status-{row.get('status')}"
        raw_path = row.get("report_path")
        claimed_sha = row.get("report_sha256")
        if not isinstance(raw_path, str) or not isinstance(claimed_sha, str):
            return None, "missing-report-binding"
        run_id = _text(record["run_id"], "controlled run ID")
        path = Path(raw_path).resolve()
        expected_path = (self.runtime_root / "controlled-reports" / f"{run_id}.json").resolve()
        if path != expected_path:
            return None, "report-path-mismatch"
        if not path.is_file() or _sha256_path(path) != claimed_sha:
            return None, "report-sha256-mismatch"
        return self._load_controlled_report(record, path)

    def _load_controlled_report(
        self,
        record: Mapping[str, object],
        path: Path,
    ) -> tuple[Mapping[str, object] | None, str | None]:
        if not path.is_file():
            return None, "report-missing"
        try:
            report_value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None, "report-json-invalid"
        report = _mapping(report_value, "controlled report")
        if (
            report.get("schema_version") != REPORT_SCHEMA
            or report.get("program_id") != PROGRAM_ID
            or report.get("status") != "completed"
        ):
            return None, "report-identity-mismatch"
        claimed = report.get("report_fingerprint")
        unsigned = dict(report)
        unsigned.pop("report_fingerprint", None)
        if not isinstance(claimed, str) or fingerprint(unsigned) != claimed:
            return None, "report-fingerprint-mismatch"
        if canonicalize(report.get("provenance")) != canonicalize(record["specification"]):
            return None, "report-provenance-mismatch"
        if not isinstance(report.get("metrics"), Mapping) or not isinstance(
            report.get("execution_evidence"), Mapping
        ):
            return None, "report-content-mismatch"
        return report, None

    def _qualify_controlled_candidate(
        self,
        configuration: Configuration,
        records: Sequence[Mapping[str, object]],
        rows: Mapping[str, Mapping[str, object]],
        freeze: Mapping[str, object],
        controlled_plan_fingerprint: str,
        accounted: bool,
    ) -> dict[str, object]:
        candidate_records = tuple(
            record
            for record in records
            if record["candidate_configuration_id"] == configuration.configuration_id
        )
        reports: dict[str, list[Mapping[str, object]]] = defaultdict(list)
        sources: list[dict[str, object]] = []
        for record in candidate_records:
            run_id = _text(record["run_id"], "controlled run ID")
            row = rows[run_id]
            report, error = self._controlled_report(record, row)
            role = _text(record["role"], "controlled role")
            if report is not None:
                reports[role].append(report)
            sources.append(
                {
                    "role": role,
                    "run_id": run_id,
                    "run_configuration_id": record["run_configuration_id"],
                    "status": row["status"],
                    "report_path": (
                        None
                        if row.get("report_path") is None
                        else Path(cast(str, row["report_path"])).name
                    ),
                    "report_sha256": row.get("report_sha256"),
                    "report_fingerprint": (
                        None if report is None else report["report_fingerprint"]
                    ),
                    "validation_error": error,
                }
            )

        def one(role: str) -> Mapping[str, object] | None:
            values = reports.get(role, [])
            return values[0] if len(values) == 1 else None

        base = one("base")
        cost_reports = tuple(one(role) for role in ("increased-cost", "harsher-cost"))
        delay_reports = tuple(one(role) for role in ("plus-1-bar", "plus-2-bars"))
        zero = one("zero-cost-diagnostic")
        neighbors = tuple(reports.get("parameter-neighbor", []))
        valid_source_count = sum(
            report is not None for values in reports.values() for report in values
        )
        expected_source_count = len(candidate_records)

        def metric(report: Mapping[str, object] | None, name: str) -> Decimal | None:
            if report is None:
                return None
            value = _mapping(report.get("metrics"), "controlled metrics").get(name)
            return _optional_decimal(value)

        base_return = metric(base, "total_return")
        cost_returns = tuple(metric(report, "total_return") for report in cost_reports)
        delay_returns = tuple(metric(report, "total_return") for report in delay_reports)
        zero_return = metric(zero, "total_return")
        policy_metrics: dict[str, Decimal | None] = {
            "registry_evidence_bound": Decimal(valid_source_count == expected_source_count),
            "search_budget_accounted": Decimal(accounted),
            "base_report_completed": Decimal(base is not None),
            "completed_round_trips": metric(base, "completed_round_trip_count"),
            "session_count": metric(base, "sessions_in_range"),
            "active_session_count": metric(base, "sessions_traded"),
            "active_session_percentage": metric(base, "sessions_traded_percentage"),
            "max_drawdown": metric(base, "max_drawdown"),
            "best_trade_profit_share": metric(base, "best_trade_positive_profit_concentration"),
            "best_session_profit_share": metric(base, "best_session_positive_profit_concentration"),
            "best_n_trades_profit_share": metric(
                base, "best_5_trades_positive_profit_concentration"
            ),
            "symbol_profit_concentration": metric(
                base, "best_symbol_positive_profit_concentration"
            ),
            "no_overnight_positions": _zero_metric(base, "overnight_position_count"),
            "no_outside_session_trades": _zero_metric(base, "outside_session_fill_count"),
            "early_close_coverage": _nonnegative_metric(base, "early_close_session_count"),
            "configuration_identity": Decimal(True),
            "cost_stress_completed": Decimal(all(report is not None for report in cost_reports)),
            "cost_stress_return_retention": _minimum_retention(base_return, cost_returns),
            "delay_stress_completed": Decimal(all(report is not None for report in delay_reports)),
            "delay_stress_return_retention": _minimum_retention(base_return, delay_returns),
        }
        policy_gates = _policy_gate_results(self.policy, policy_metrics)
        additional = _mapping(
            _mapping(self.plan.payload["controlled_qualification"], "controlled")[
                "additional_gates"
            ],
            "additional gates",
        )
        stress_returns = (*cost_returns, *delay_returns)
        stress_retention = _minimum_retention(base_return, stress_returns)
        base_cost = metric(base, "cost_paid_total")
        cost_ratio = (
            base_cost / (zero_return * self.plan.initial_cash)
            if base_cost is not None and zero_return is not None and zero_return > 0
            else None
        )
        neighbor_returns = tuple(metric(report, "total_return") for report in neighbors)
        positive_neighbor_fraction = (
            Decimal(sum(value is not None and value > 0 for value in neighbor_returns))
            / Decimal(len(neighbor_returns))
            if neighbor_returns
            else None
        )
        neighbor_retention = _minimum_retention(base_return, neighbor_returns)
        trace_reports = (base, *cost_reports, *delay_reports, zero)
        decision_traces = _evidence_values(trace_reports, "decision_trace_fingerprint")
        signal_traces = _evidence_values((base, *delay_reports), "signal_timestamp_fingerprint")
        decision_counts = tuple(
            metric(report, "decision_count") for report in (base, *delay_reports)
        )
        additional_metrics: dict[str, Decimal | None] = {
            "base_total_return": base_return,
            "zero_cost_total_return": zero_return,
            "minimum_cost_and_delay_stress_return": _minimum_optional(stress_returns),
            "minimum_stress_return_retention": stress_retention,
            "cost_to_zero_cost_profit": cost_ratio,
            "positive_neighbor_fraction": positive_neighbor_fraction,
            "minimum_neighbor_return_retention": neighbor_retention,
            "decision_trace_identity": Decimal(
                len(decision_traces) == len(trace_reports) and len(set(decision_traces)) == 1
            ),
            "delay_decision_cadence_identity": Decimal(
                all(value is not None for value in decision_counts)
                and len(set(decision_counts)) == 1
            ),
            "original_signal_timestamp_identity": Decimal(
                len(signal_traces) == 3 and len(set(signal_traces)) == 1
            ),
        }
        additional_gates = (
            _visible_gate(
                "positive base return",
                additional_metrics["base_total_return"],
                ">",
                _decimal(additional["base_total_return_gt"], "gate"),
            ),
            _visible_gate(
                "positive zero-cost return",
                additional_metrics["zero_cost_total_return"],
                ">",
                _decimal(additional["zero_cost_total_return_gt"], "gate"),
            ),
            _visible_gate(
                "all cost and delay stress returns positive",
                additional_metrics["minimum_cost_and_delay_stress_return"],
                ">",
                _ZERO,
            ),
            _visible_gate(
                "minimum stress return retention",
                additional_metrics["minimum_stress_return_retention"],
                ">=",
                _decimal(additional["minimum_stress_return_retention_gte"], "gate"),
            ),
            _visible_gate(
                "cost to zero-cost profit",
                additional_metrics["cost_to_zero_cost_profit"],
                "<=",
                _decimal(additional["cost_to_zero_cost_profit_lte"], "gate"),
            ),
            _visible_gate(
                "positive neighbor fraction",
                additional_metrics["positive_neighbor_fraction"],
                ">=",
                _decimal(additional["positive_neighbor_fraction_gte"], "gate"),
            ),
            _visible_gate(
                "minimum neighbor return retention",
                additional_metrics["minimum_neighbor_return_retention"],
                ">=",
                _decimal(additional["minimum_neighbor_return_retention_gte"], "gate"),
            ),
            _visible_gate(
                "decision trace identity",
                additional_metrics["decision_trace_identity"],
                "==",
                _ONE,
            ),
            _visible_gate(
                "delay decision cadence identity",
                additional_metrics["delay_decision_cadence_identity"],
                "==",
                _ONE,
            ),
            _visible_gate(
                "original signal timestamp identity",
                additional_metrics["original_signal_timestamp_identity"],
                "==",
                _ONE,
            ),
        )
        passed = all(gate["passed"] is True for gate in (*policy_gates, *additional_gates))
        freeze_payload = _mapping(freeze["payload"], "cohort freeze")
        evidence: dict[str, object] = {
            "schema_version": QUALIFICATION_SCHEMA,
            "program_id": PROGRAM_ID,
            "state": "controlled-qualified" if passed else "controlled-failed",
            "passed": passed,
            "candidate": _configuration_payload(configuration),
            "source_commit": self.source_commit,
            "plan_sha256": self.plan.sha256,
            "cohort_freeze_fingerprint": freeze_payload["cohort_freeze_fingerprint"],
            "controlled_plan_fingerprint": controlled_plan_fingerprint,
            "policy": {
                "id": self.policy.policy_id,
                "fingerprint": self.policy.fingerprint,
            },
            "policy_metrics": policy_metrics,
            "policy_gates": policy_gates,
            "additional_metrics": additional_metrics,
            "additional_gates": additional_gates,
            "sources": sources,
            "authority": _AUTHORITY,
        }
        evidence["evidence_fingerprint"] = fingerprint(evidence)
        path = self.runtime_root / "qualification" / f"{configuration.configuration_id}.json"
        _write_create_only(path, evidence)
        return {
            "configuration": _configuration_payload(configuration),
            "passed": passed,
            "failed_policy_gates": [
                gate["name"] for gate in policy_gates if gate["passed"] is not True
            ],
            "failed_additional_gates": [
                gate["name"] for gate in additional_gates if gate["passed"] is not True
            ],
            "base_return": base_return,
            "zero_cost_return": zero_return,
            "stress_returns": {
                role: value
                for role, value in zip(
                    ("increased-cost", "harsher-cost", "plus-1-bar", "plus-2-bars"),
                    stress_returns,
                    strict=True,
                )
            },
            "neighbor_returns": neighbor_returns,
            "evidence_path": str(path.resolve()),
            "evidence_sha256": _sha256_path(path),
            "evidence_fingerprint": evidence["evidence_fingerprint"],
        }

    def _write_final_report(
        self,
        discovery: Mapping[str, object],
        walk_forward: Mapping[str, object],
        screens: Sequence[Mapping[str, object]],
        cohort: Sequence[Configuration],
        freeze: Mapping[str, object],
        controlled: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        discovery_rows = _mapping(discovery["rows"], "discovery rows")
        discovery_pairs = [
            (
                _mapping(_mapping(value, "discovery record")["normal"], "normal record"),
                _mapping(
                    _mapping(value, "discovery record")["zero-cost"],
                    "zero-cost record",
                ),
            )
            for value in discovery_rows.values()
        ]
        completed_discovery_pairs = [
            pair
            for pair in discovery_pairs
            if _record_completed(pair[0]) and _record_completed(pair[1])
        ]
        normal_rows = [pair[0] for pair in completed_discovery_pairs]
        zero_rows = [pair[1] for pair in completed_discovery_pairs]
        runs = self.store.list_runs()
        controlled_rows = self.store.controlled_rows()
        qualified = [item for item in controlled if item["passed"] is True]
        outcome = (
            "AUTONOMOUS INTRADAY RESEARCH COMPLETE — CONTROLLED-QUALIFIED CANDIDATE(S) FOUND"
            if qualified
            else "AUTONOMOUS INTRADAY RESEARCH COMPLETE — BOUNDED INTRADAY UNIVERSE "
            "EXHAUSTED WITH NO CONTROLLED-QUALIFIED CANDIDATE"
        )
        reasons: dict[str, int] = defaultdict(int)
        for screen in screens:
            for reason in cast(Sequence[str], screen["reasons"]):
                reasons[reason] += 1
        strongest_reporting: list[dict[str, object]] = []
        for summary_value in cast(Sequence[Mapping[str, object]], discovery["strongest"]):
            summary = _mapping(summary_value, "strongest configuration")
            normal = self.store.get(_text(summary["normal_run_id"], "normal run ID"))
            zero = self.store.get(_text(summary["zero_cost_run_id"], "zero-cost run ID"))
            strongest_reporting.append(
                {
                    "configuration": summary["strongest_configuration"],
                    "metrics": _required_reporting_metrics(self.plan.initial_cash, normal, zero),
                }
            )
        serious_reporting = [
            {
                "configuration": screen["configuration"],
                "metrics": _required_reporting_metrics(
                    self.plan.initial_cash,
                    self.store.get(_text(screen["normal_run_id"], "normal run ID")),
                    self.store.get(_text(screen["zero_cost_run_id"], "zero-cost run ID")),
                    screen,
                ),
            }
            for screen in screens
        ]
        if len(strongest_reporting) != len(_family_ids(self.plan)):
            raise ValueError("Intraday Exposed 001 strongest-family reporting differs")
        freeze_payload = _mapping(freeze["payload"], "cohort freeze")
        payload: dict[str, object] = {
            "schema_version": FINAL_REPORT_SCHEMA,
            "program_id": PROGRAM_ID,
            "outcome": outcome,
            "starting_main": self.plan.payload["starting_main"],
            "final_main": self.source_commit,
            "prs_and_merges": (
                []
                if self.implementation_pr is None
                else [
                    {
                        "pull_request": self.implementation_pr,
                        "merge_commit": self.source_commit,
                        "purpose": "implementation and frozen campaign runner",
                    }
                ]
            ),
            "plan": {
                "path": str(PLAN_RELATIVE_PATH),
                "sha256": self.plan.sha256,
                "fingerprint": self.plan.fingerprint,
            },
            "datasets": [
                {
                    "dataset_id": item.dataset_id,
                    "fingerprint": item.fingerprint,
                    "raw_fingerprint": item.raw_fingerprint,
                    "start": item.start,
                    "end": item.end,
                    "bar_count": item.bar_count,
                }
                for item in self.plan.datasets
            ],
            "verified_data_totals": _mapping(
                _mapping(self.plan.payload["data"], "data")["verified_totals"],
                "verified totals",
            ),
            "chronology": _mapping(self.plan.payload["chronology"], "chronology"),
            "strategy_families": discovery["strongest"],
            "required_reporting": {
                "fields": list(REQUIRED_REPORTING_FIELDS),
                "strongest_by_family": strongest_reporting,
                "serious_candidates": serious_reporting,
            },
            "counts": {
                "declared_parent_configurations": len(self.plan.configurations),
                "discovery_runs": len(discovery_pairs) * 2,
                "completed_discovery_pairs": len(completed_discovery_pairs),
                "walk_forward_candidate_count": len(cast(Sequence[object], discovery["selected"])),
                "walk_forward_folds": len(cast(Sequence[object], discovery["selected"]))
                * len(self.plan.walk_forward_folds),
                "serious_candidate_count": len(cast(Sequence[object], walk_forward["selected"])),
                "final_exposed_stress_runs": len(screens) * 4,
                "parameter_neighbor_runs": sum(
                    run["stage"] == "parameter-neighbor" for run in runs
                ),
                "controlled_reservations": len(controlled_rows),
                "controlled_stress_runs": sum(
                    _mapping(row["specification"], "controlled specification").get(
                        "controlled_role"
                    )
                    in {"increased-cost", "harsher-cost", "plus-1-bar", "plus-2-bars"}
                    for row in controlled_rows
                ),
                "total_runtime_rows": len(runs),
                "failed_runtime_rows": sum(run["status"] == "failed" for run in runs),
            },
            "gross_vs_net_cost_findings": {
                "positive_zero_cost_configurations": sum(
                    _metric(row, "total_return") > 0 for row in zero_rows
                ),
                "positive_normal_configurations": sum(
                    _metric(row, "total_return") > 0 for row in normal_rows
                ),
                "positive_zero_cost_but_nonpositive_normal": sum(
                    _metric(zero, "total_return") > 0 and _metric(normal, "total_return") <= 0
                    for normal, zero in zip(normal_rows, zero_rows, strict=True)
                ),
                "total_normal_cost_paid": sum(
                    (_metric(row, "cost_paid_total") for row in normal_rows), _ZERO
                ),
            },
            "turnover_and_fill_findings": {
                "total_discovery_turnover": sum(
                    (_metric(row, "turnover") for row in normal_rows), _ZERO
                ),
                "total_discovery_fills": sum(
                    (_metric(row, "fill_count") for row in normal_rows), _ZERO
                ),
                "maximum_discovery_turnover": max(
                    (_metric(row, "turnover") for row in normal_rows), default=_ZERO
                ),
            },
            "delay_findings": {
                "screened_candidate_count": len(screens),
                "trace_identity_pass_count": sum(
                    screen["decision_trace_identity"] is True
                    and screen["signal_timestamp_identity"] is True
                    and screen["decision_cadence_identity"] is True
                    for screen in screens
                ),
                "delay_positive_return_pass_count": sum(
                    (
                        _optional_decimal(
                            _mapping(screen["stress_returns"], "stress returns")["delay-2"]
                        )
                        or _ZERO
                    )
                    > _ZERO
                    and (
                        _optional_decimal(
                            _mapping(screen["stress_returns"], "stress returns")["delay-3"]
                        )
                        or _ZERO
                    )
                    > _ZERO
                    for screen in screens
                ),
            },
            "robustness_findings": {
                "screen_pass_count": sum(screen["passed"] is True for screen in screens),
                "screen_failure_reasons": dict(sorted(reasons.items())),
            },
            "final_cohort": [_configuration_payload(item) for item in cohort],
            "cohort_freeze": {
                "path": "cohort-freeze.json",
                "sha256": freeze["sha256"],
                "fingerprint": freeze_payload["cohort_freeze_fingerprint"],
            },
            "controlled_plan": freeze.get("controlled_artifact"),
            "controlled_results": list(controlled),
            "recommendation": (
                None if not qualified else [item["configuration"] for item in qualified]
            ),
            "qualification_evidence": [
                {
                    "configuration_id": _mapping(item["configuration"], "configuration")[
                        "configuration_id"
                    ],
                    "path": Path(_text(item["evidence_path"], "evidence path")).name,
                    "sha256": item["evidence_sha256"],
                    "fingerprint": item["evidence_fingerprint"],
                }
                for item in controlled
            ],
            "safety_confirmation": {
                "v3_accessed_or_mutated": False,
                "protected_holdout_accessed": False,
                "paper_accessed_or_activated": False,
                "broker_read_or_write_performed": False,
                "live_accessed_or_activated": False,
                "strategic_allocation_21_accessed_or_mutated": False,
            },
            "authority": _AUTHORITY,
        }
        payload["report_fingerprint"] = fingerprint(payload)
        json_path = self.runtime_root / "final-report.json"
        _write_create_only(json_path, payload)
        markdown_path = self.runtime_root / "final-report.md"
        _write_create_only_text(
            markdown_path,
            _final_markdown(payload, _sha256_path(json_path)),
        )
        self.progress(f"wrote final report {json_path}")
        return payload


def _source_commit(repository: Path) -> str:
    command = (
        "git",
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-C",
        str(repository),
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
        raise ValueError("Intraday Exposed 001 source identity is unavailable") from error
    if dirty:
        raise ValueError("Intraday Exposed 001 requires a clean reviewed source commit")
    if commit != main or commit != origin_main:
        raise ValueError("Intraday Exposed 001 requires HEAD, main, and origin/main to match")
    return _validated_commit(commit)


def _validated_commit(value: str) -> str:
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("Intraday Exposed 001 source commit is invalid")
    return value


@contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Intraday Exposed 001 campaign is already running") from error
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
            raise FileExistsError(f"Intraday Exposed 001 artifact differs: {path}")
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


def _family_ids(plan: IntradayExposedPlan) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.family_id for item in plan.configurations))


def _configuration_payload(configuration: Configuration) -> dict[str, object]:
    return {
        "family_id": configuration.family_id,
        "family_name": configuration.family_name,
        "strategy_id": configuration.strategy_id,
        "parameters": dict(configuration.parameters),
        "configuration_id": configuration.configuration_id,
    }


def _configuration_summary(
    configuration: Configuration,
    records: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    normal = records["normal"]
    zero = records["zero-cost"]
    return {
        "family_id": configuration.family_id,
        "family_name": configuration.family_name,
        "strongest_configuration": _configuration_payload(configuration),
        "normal_run_id": normal["run_id"],
        "zero_cost_run_id": zero["run_id"],
        "normal_metrics": normal["metrics"]
        or {
            "total_return": None,
            "turnover": None,
            "fill_count": None,
        },
        "zero_cost_metrics": zero["metrics"] or {"total_return": None},
    }


def _record_completed(record: Mapping[str, object]) -> bool:
    return record.get("status") == "completed" and isinstance(record.get("metrics"), Mapping)


def _metric(record: Mapping[str, object], name: str) -> Decimal:
    metrics = _mapping(record.get("metrics"), "run metrics")
    value = _optional_decimal(metrics.get(name))
    if value is None:
        raise ValueError(f"Intraday Exposed 001 metric is missing: {name}")
    return value


def _metric_or_none(record: Mapping[str, object], name: str) -> Decimal | None:
    if not _record_completed(record):
        return None
    return _optional_decimal(_mapping(record["metrics"], "run metrics").get(name))


def _details(record: Mapping[str, object]) -> Mapping[str, Any]:
    return _mapping(record.get("details"), "run details")


def _required_reporting_metrics(
    initial_cash: Decimal,
    normal: Mapping[str, object] | None,
    zero: Mapping[str, object] | None,
    screen: Mapping[str, object] | None = None,
) -> dict[str, object]:
    normal_record = normal or {}
    zero_record = zero or {}
    normal_details = (
        _mapping(normal_record["details"], "run details")
        if _record_completed(normal_record)
        else {}
    )
    net_return = _metric_or_none(normal_record, "total_return")
    zero_cost_return = _metric_or_none(zero_record, "total_return")
    cost_paid = _metric_or_none(normal_record, "cost_paid_total")
    gross_profit = (
        zero_cost_return * initial_cash
        if zero_cost_return is not None and zero_cost_return > 0
        else None
    )
    long_duration = _metric_or_none(normal_record, "average_long_state_seconds")
    flat_duration = _metric_or_none(normal_record, "average_flat_state_seconds")
    screen_value = screen or {}
    stress_retentions = screen_value.get("stress_retentions")
    stress_mapping = (
        _mapping(stress_retentions, "stress retentions")
        if isinstance(stress_retentions, Mapping)
        else {}
    )
    values: dict[str, object] = {
        "net_return": net_return,
        "zero_cost_return": zero_cost_return,
        "sharpe_ratio": _metric_or_none(normal_record, "sharpe_ratio"),
        "max_drawdown": _metric_or_none(normal_record, "max_drawdown"),
        "turnover": _metric_or_none(normal_record, "turnover"),
        "fill_count": _metric_or_none(normal_record, "fill_count"),
        "completed_round_trips": _metric_or_none(normal_record, "completed_round_trip_count"),
        "hit_rate": _metric_or_none(normal_record, "hit_rate"),
        "average_trade": _metric_or_none(normal_record, "average_trade"),
        "cost_paid": cost_paid,
        "cost_to_zero_cost_profit_ratio": (
            cost_paid / gross_profit if cost_paid is not None and gross_profit is not None else None
        ),
        "average_holding_duration": _metric_or_none(
            normal_record, "average_holding_duration_seconds"
        ),
        "exposure_time": _metric_or_none(normal_record, "exposure_bar_percentage"),
        "long_and_flat_state_duration": (
            {
                "average_long_state_seconds": long_duration,
                "average_flat_state_seconds": flat_duration,
            }
            if long_duration is not None or flat_duration is not None
            else None
        ),
        "chronological_block_performance": screen_value.get("fold_returns"),
        "time_of_day_performance": normal_details.get("time_of_day_profit"),
        "symbol_contribution": normal_details.get("symbol_profit"),
        "worst_fold": screen_value.get("worst_fold_return"),
        "fold_dispersion": screen_value.get("fold_return_dispersion"),
        "stress_a_retention": stress_mapping.get("stress-a"),
        "stress_b_retention": stress_mapping.get("stress-b"),
        "parameter_neighbor_retention": screen_value.get("neighbor_retentions"),
    }
    if tuple(values) != REQUIRED_REPORTING_FIELDS:
        raise ValueError("Intraday Exposed 001 required reporting contract differs")
    return values


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _zero_metric(report: Mapping[str, object] | None, name: str) -> Decimal | None:
    value = _nonnegative_count(report, name)
    return None if value is None else Decimal(value == 0)


def _nonnegative_metric(report: Mapping[str, object] | None, name: str) -> Decimal | None:
    value = _nonnegative_count(report, name)
    return None if value is None else _ONE


def _nonnegative_count(report: Mapping[str, object] | None, name: str) -> int | None:
    if report is None:
        return None
    value = _mapping(report.get("metrics"), "report metrics").get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _minimum_retention(
    base_return: Decimal | None,
    values: Sequence[Decimal | None],
) -> Decimal | None:
    if (
        base_return is None
        or base_return <= 0
        or not values
        or any(value is None for value in values)
    ):
        return None
    return min(cast(Decimal, value) / base_return for value in values)


def _minimum_optional(values: Sequence[Decimal | None]) -> Decimal | None:
    if not values or any(value is None for value in values):
        return None
    return min(cast(Decimal, value) for value in values)


def _evidence_values(reports: Sequence[Mapping[str, object] | None], name: str) -> tuple[str, ...]:
    result: list[str] = []
    for report in reports:
        if report is None:
            continue
        evidence = _mapping(report.get("execution_evidence"), "execution evidence")
        value = evidence.get(name)
        if isinstance(value, str):
            result.append(value)
    return tuple(result)


def _visible_gate(
    name: str,
    observed: Decimal | None,
    comparison: str,
    threshold: Decimal,
) -> dict[str, object]:
    passed = observed is not None and {
        ">": observed > threshold if observed is not None else False,
        ">=": observed >= threshold if observed is not None else False,
        "<=": observed <= threshold if observed is not None else False,
        "==": observed == threshold if observed is not None else False,
    }.get(comparison, False)
    return {
        "name": name,
        "observed": observed,
        "comparison": comparison,
        "threshold": threshold,
        "passed": passed,
        "reason": "passed" if passed else "missing-or-threshold-failed",
    }


def _policy_gate_results(
    policy: IntradayQualificationPolicy,
    metrics: Mapping[str, Decimal | None],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            **_visible_gate(
                gate.name,
                metrics.get(gate.metric),
                gate.comparison,
                gate.threshold,
            ),
            "metric": gate.metric,
            "rationale": gate.rationale,
        }
        for gate in policy.gates
    )


def _final_markdown(report: Mapping[str, object], json_sha256: str) -> str:
    counts = _mapping(report["counts"], "report counts")
    lines = [
        "# Intraday Exposed 001 final report",
        "",
        _text(report["outcome"], "outcome"),
        "",
        f"Starting main: `{report['starting_main']}`  ",
        f"Research source/final main: `{report['final_main']}`  ",
        f"JSON SHA-256: `{json_sha256}`",
        "",
        "## Bounded program",
        "",
        f"- Parent configurations: {counts['declared_parent_configurations']}",
        f"- Walk-forward folds: {counts['walk_forward_folds']}",
        f"- Final exposed stress runs: {counts['final_exposed_stress_runs']}",
        f"- Controlled reservations: {counts['controlled_reservations']}",
        f"- Failed runtime rows: {counts['failed_runtime_rows']}",
        "",
        "## Strongest discovery configuration per family",
        "",
        "| Family | Strategy | Normal return | Zero-cost return | Turnover | Fills |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for value in cast(Sequence[Mapping[str, object]], report["strategy_families"]):
        configuration = _mapping(value["strongest_configuration"], "configuration")
        normal = _mapping(value["normal_metrics"], "normal metrics")
        zero = _mapping(value["zero_cost_metrics"], "zero-cost metrics")
        lines.append(
            "| "
            f"{value['family_id']} {value['family_name']} | {configuration['strategy_id']} | "
            f"{normal['total_return']} | {zero['total_return']} | {normal['turnover']} | "
            f"{normal['fill_count']} |"
        )
    lines.extend(["", "## Final cohort and controlled qualification", ""])
    cohort = cast(Sequence[Mapping[str, object]], report["final_cohort"])
    if not cohort:
        lines.append("The final cohort froze empty. No June strategy result was run.")
    else:
        for item in cast(Sequence[Mapping[str, object]], report["controlled_results"]):
            configuration = _mapping(item["configuration"], "configuration")
            lines.append(
                f"- `{configuration['configuration_id']}` `{configuration['strategy_id']}`: "
                f"{'PASS' if item['passed'] is True else 'FAIL'}"
            )
    safety = _mapping(report["safety_confirmation"], "safety confirmation")
    lines.extend(
        [
            "",
            "## Safety boundary",
            "",
            "V3, protected holdouts, PAPER, broker, live, and `strategic-allocation-21` "
            "remained untouched.",
            "",
            f"Report fingerprint: `{report['report_fingerprint']}`",
            "",
        ]
    )
    if any(value is not False for value in safety.values()):
        raise ValueError("Intraday Exposed 001 safety confirmation differs")
    return "\n".join(lines)


def _evaluation_accounting(
    result: V3BacktestResult,
    bars: Sequence[OHLCVBar],
    period: EvaluationPeriod,
    initial_cash: Decimal,
    cost_model: CostModel,
    execution_delay_bars: int,
) -> BacktestResult:
    start = period.evaluation_start + Timeframe.FIVE_MINUTES.duration
    end = period.evaluation_end + Timeframe.FIVE_MINUTES.duration
    curve = tuple(point for point in result.equity_curve if start <= point.timestamp <= end)
    trades = tuple(
        trade
        for trade in result.trades
        if period.evaluation_start <= trade.fill_timestamp <= period.evaluation_end
    )
    if not curve or not bars:
        raise BacktestError("Intraday Exposed evaluation slice is empty")
    positions = dict(curve[-1].positions)
    marks = {
        symbol: max(
            (bar for bar in bars if bar.symbol == symbol), key=lambda bar: bar.timestamp
        ).close
        for symbol in {bar.symbol for bar in bars}
    }
    engine = BacktestEngine(
        initial_cash,
        cost_model,
        execution_delay_bars,
        timeframe=Timeframe.FIVE_MINUTES,
    )
    return engine._result(
        cast(PortfolioStrategy, _StrategyIdentity(result.strategy_id, result.strategy_version)),
        curve,
        (),
        (),
        trades,
        bars,
        positions,
        marks,
    )


def _report(
    specification: Mapping[str, object],
    result: V3BacktestResult,
    accounting: BacktestResult,
    bars: Sequence[OHLCVBar],
    period: EvaluationPeriod,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    report = build_intraday_report(specification, accounting, bars)
    report.pop("report_fingerprint")
    report["schema_version"] = REPORT_SCHEMA
    report["program_id"] = PROGRAM_ID
    decisions = tuple(
        item
        for item in result.decisions
        if period.evaluation_start + Timeframe.FIVE_MINUTES.duration
        <= item.timestamp
        <= period.evaluation_end + Timeframe.FIVE_MINUTES.duration
    )
    trace = _decision_trace(decisions)
    state_changes = tuple(
        {
            "timestamp": item.timestamp,
            "changed_symbols": tuple(symbol.value for symbol in item.changed_symbols),
        }
        for item in decisions
        if item.changed_symbols
    )
    metrics = dict(cast(Mapping[str, object], report["metrics"]))
    round_trips = _round_trips(accounting.trades)
    total_realized = sum((cast(Decimal, item["net_profit"]) for item in round_trips), _ZERO)
    winning = sum(cast(Decimal, item["net_profit"]) > 0 for item in round_trips)
    exposure_points = [
        any(quantity > 0 for _, quantity in point.positions) for point in accounting.equity_curve
    ]
    long_runs, flat_runs = _state_durations(exposure_points)
    metrics.update(
        {
            "hit_rate": (Decimal(winning) / Decimal(len(round_trips)) if round_trips else None),
            "average_trade": (total_realized / Decimal(len(round_trips)) if round_trips else None),
            "average_holding_duration_seconds": report.get("average_holding_duration_seconds"),
            "exposure_bar_percentage": (
                Decimal(sum(exposure_points)) / Decimal(len(exposure_points))
                if exposure_points
                else None
            ),
            "average_long_state_seconds": _average(long_runs),
            "average_flat_state_seconds": _average(flat_runs),
            "desired_state_change_count": sum(len(item.changed_symbols) for item in decisions),
            "decision_count": len(decisions),
            "executed_state_transition_count": sum(
                item.status == "filled"
                and period.evaluation_start <= item.eligible_fill_timestamp <= period.evaluation_end
                for item in result.transitions
                if item.eligible_fill_timestamp is not None
            ),
        }
    )
    execution_evidence: dict[str, object] = {
        "report_schema": REPORT_SCHEMA,
        "decision_trace_fingerprint": fingerprint(trace),
        "signal_timestamp_fingerprint": fingerprint(state_changes),
        "time_of_day_profit": _time_of_day_profit(round_trips),
        "symbol_profit": report["pnl_by_symbol"],
        "long_state_run_count": len(long_runs),
        "flat_state_run_count": len(flat_runs),
        "input_bar_count": len(bars),
        "result_artifact_fingerprint": result.artifact_fingerprint,
    }
    report["metrics"] = metrics
    report["execution_evidence"] = execution_evidence
    report["report_fingerprint"] = fingerprint(report)
    details = {
        **execution_evidence,
        "report_fingerprint": report["report_fingerprint"],
    }
    return metrics, details, cast(dict[str, object], report)


def _decision_trace(decisions: Sequence[DesiredStateDecision]) -> tuple[object, ...]:
    return tuple(
        {
            "timestamp": item.timestamp,
            "desired_targets": tuple(
                (target.symbol.value, target.weight) for target in item.desired_targets
            ),
        }
        for item in decisions
    )


def _round_trips(trades: Sequence[Trade]) -> tuple[dict[str, object], ...]:
    lots: dict[Symbol, deque[tuple[Decimal, Trade]]] = defaultdict(deque)
    completed: list[dict[str, object]] = []
    for trade in trades:
        if trade.quantity > 0:
            lots[trade.symbol].append((trade.quantity, trade))
            continue
        remaining = abs(trade.quantity)
        while remaining > 0 and lots[trade.symbol]:
            lot_quantity, opened = lots[trade.symbol][0]
            matched = min(remaining, lot_quantity)
            buy_cost = opened.commission * matched / abs(opened.quantity)
            sell_cost = trade.commission * matched / abs(trade.quantity)
            completed.append(
                {
                    "symbol": trade.symbol.value,
                    "entry_timestamp": opened.fill_timestamp,
                    "exit_timestamp": trade.fill_timestamp,
                    "net_profit": matched * (trade.fill_price - opened.fill_price)
                    - buy_cost
                    - sell_cost,
                }
            )
            if matched == lot_quantity:
                lots[trade.symbol].popleft()
            else:
                lots[trade.symbol][0] = (lot_quantity - matched, opened)
            remaining -= matched
    if any(lots.values()):
        raise BacktestError("Intraday Exposed round-trip accounting ended with open lots")
    return tuple(completed)


def _state_durations(exposed: Sequence[bool]) -> tuple[list[Decimal], list[Decimal]]:
    long_runs: list[Decimal] = []
    flat_runs: list[Decimal] = []
    for state, group in itertools.groupby(exposed):
        duration = Decimal(sum(1 for _ in group) * 300)
        (long_runs if state else flat_runs).append(duration)
    return long_runs, flat_runs


def _time_of_day_profit(round_trips: Sequence[Mapping[str, object]]) -> dict[str, Decimal]:
    result = {"open": _ZERO, "morning": _ZERO, "midday": _ZERO, "afternoon": _ZERO}
    for item in round_trips:
        timestamp = cast(datetime, item["entry_timestamp"]).astimezone(_NEW_YORK)
        local = timestamp.time().replace(tzinfo=None)
        if local < time(10, 30):
            window = "open"
        elif local < time(12):
            window = "morning"
        elif local < time(14):
            window = "midday"
        else:
            window = "afternoon"
        result[window] += cast(Decimal, item["net_profit"])
    return result


def _average(values: Sequence[Decimal]) -> Decimal | None:
    return sum(values, _ZERO) / Decimal(len(values)) if values else None


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Intraday Exposed 001 {label} must be an object")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Intraday Exposed 001 {label} must be text")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"Intraday Exposed 001 {label} must be a nonempty list")
    result = tuple(_text(item, label) for item in value)
    if len(result) != len(set(result)):
        raise ValueError(f"Intraday Exposed 001 {label} must be unique")
    return result


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"Intraday Exposed 001 {label} must be a positive integer")
    return value


def _integer_values(value: object, label: str) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"Intraday Exposed 001 {label} must be a nonempty list")
    result: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise ValueError(f"Intraday Exposed 001 {label} must contain non-negative integers")
        result.append(item)
    if len(result) != len(set(result)):
        raise ValueError(f"Intraday Exposed 001 {label} must be unique")
    return tuple(result)


def _integer_mapping(value: object, label: str) -> dict[str, int]:
    item = _mapping(value, label)
    result: dict[str, int] = {}
    for name, raw in item.items():
        if not isinstance(name, str) or not name:
            raise ValueError(f"Intraday Exposed 001 {label} names differ")
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise ValueError(f"Intraday Exposed 001 {label} values differ")
        result[name] = raw
    return result


def _timestamp(value: object, label: str) -> datetime:
    text = _text(value, label)
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Intraday Exposed 001 {label} is invalid") from error
    if result.utcoffset() != UTC.utcoffset(result):
        raise ValueError(f"Intraday Exposed 001 {label} must use UTC")
    return result.astimezone(UTC)


def _decimal(value: object, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"Intraday Exposed 001 {label} is invalid") from error
    if not result.is_finite():
        raise ValueError(f"Intraday Exposed 001 {label} must be finite")
    return result


def _run_id(specification: Mapping[str, object]) -> str:
    return f"iexr-{fingerprint(specification)[:24]}"


def run_intraday_exposed_campaign(
    repository: Path,
    data_home: Path,
    *,
    progress: Callable[[str], None] | None = None,
    implementation_pr: int | None = None,
) -> dict[str, object]:
    return IntradayExposedRunner(
        repository,
        data_home,
        progress=progress,
        implementation_pr=implementation_pr,
    ).run()


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--data-home", type=Path, required=True)
    parser.add_argument("--implementation-pr", type=int)
    parsed = parser.parse_args(arguments)
    result = run_intraday_exposed_campaign(
        parsed.repository,
        parsed.data_home,
        progress=lambda message: print(message, file=sys.stderr, flush=True),
        implementation_pr=parsed.implementation_pr,
    )
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
