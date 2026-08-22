"""Read-only sequential/process equivalence proof for completed Exposed 003 runs."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from .datasets import DatasetService
from .fingerprints import canonical_json, fingerprint
from .intraday_execution_cost_model import load_intraday_execution_cost_model
from .intraday_exposed_002_engine import IntradayExposed002Engine
from .intraday_exposed_002_runner import (
    _dataset_bindings,
    _DatasetBinding,
    _EvaluationBoundStrategy,
    _mapping,
    _scenarios,
    _source_commit,
    _text,
)
from .intraday_exposed_002_strategies import build_intraday_exposed_002_strategy
from .intraday_exposed_003_plan import PROGRAM_ID, load_intraday_exposed_003_plan
from .intraday_exposed_003_runner import (
    DATABASE_NAME,
    IntradayExposed003Runner,
    _effective_plan,
    _run_id,
    _run_report,
)
from .research_executor import DEFAULT_RESEARCH_WORKERS, run_process_stage
from .storage import StorageLayout


@dataclass(frozen=True)
class _Fixture:
    run_id: str
    specification: Mapping[str, object]
    run_fingerprint: str
    report_bytes: bytes
    report_sha256: str
    report_fingerprint: str


@dataclass(frozen=True)
class _Replay:
    run_id: str
    run_fingerprint: str
    report_bytes: bytes
    report_sha256: str
    report_fingerprint: str
    fill_trace_fingerprint: str
    round_trip_fingerprint: str


@dataclass(frozen=True)
class _WorkerFactory:
    repository: Path
    data_home: Path

    def __call__(self) -> _Worker:
        return _Worker(self.repository, self.data_home)


class _Worker:
    def __init__(self, repository: Path, data_home: Path) -> None:
        runner = IntradayExposed003Runner.__new__(IntradayExposed003Runner)
        runner.repository = repository.resolve()
        runner.data_home = data_home.resolve()
        runner.control_plan = load_intraday_exposed_003_plan(runner.repository)
        runner.plan = _effective_plan(runner.control_plan)
        runner.cost_model = load_intraday_execution_cost_model(runner.repository)
        runner.datasets = _dataset_bindings(runner.control_plan.source_plan)
        runner.data_by_dataset = _read_only_dataset_services(runner.data_home, runner.datasets)
        runner._verify_datasets()
        runner.scenarios = _scenarios(runner.cost_model)
        runner._bar_cache = {}
        self.runner = runner

    def __call__(self, specification: Mapping[str, object]) -> _Replay:
        context = _mapping(specification.get("context"), "run context")
        configuration = self.runner._configuration(_text(context, "candidate_id"))
        period = self.runner._period(_text(context, "period_id"))
        scenario = self.runner.scenarios[_text(context, "scenario_id")]
        source_commit = _required_source_commit(specification.get("source_commit"))
        self.runner.source_commit = source_commit
        expected = self.runner._specification(
            _text(context, "stage"),
            configuration,
            period,
            scenario.scenario_id,
            base_candidate_id=cast(str | None, context.get("base_candidate_id")),
        )
        if canonical_json(expected) != canonical_json(specification):
            raise ValueError("equivalence fixture specification differs from the frozen plan")
        source_configuration = self.runner._source_configuration(configuration.candidate_id)
        strategy = _EvaluationBoundStrategy(
            build_intraday_exposed_002_strategy(
                source_configuration,
                cost_model=self.runner.cost_model,
            ),
            period.evaluation_start,
        )
        result = IntradayExposed002Engine(
            Decimal(str(self.runner.plan.payload["execution"]["initial_cash"])),
            scenario,
            self.runner.cost_model.regulatory_fees,
        ).run(self.runner._bars(period), strategy)
        report = _run_report(specification, result, period)
        report_bytes = (canonical_json(report) + "\n").encode()
        details = _mapping(report.get("details"), "report details")
        return _Replay(
            _run_id(specification),
            fingerprint(specification),
            report_bytes,
            hashlib.sha256(report_bytes).hexdigest(),
            _text(report, "report_fingerprint"),
            _text(details, "fill_trace_fingerprint"),
            _text(details, "round_trip_fingerprint"),
        )


def verify_intraday_exposed_003_parallel_equivalence(
    repository: Path,
    data_home: Path,
    *,
    workers: int = DEFAULT_RESEARCH_WORKERS,
    fixture_count: int = 4,
) -> dict[str, object]:
    """Replay configuration-selected completed fixtures without changing 003 state."""

    if isinstance(workers, bool) or workers < 2:
        raise ValueError("parallel equivalence requires at least two workers")
    if isinstance(fixture_count, bool) or fixture_count < 3:
        raise ValueError("equivalence requires at least three completed fixtures")
    verification_source_commit = _source_commit(repository)
    database = data_home.resolve() / PROGRAM_ID / DATABASE_NAME
    database_sha256 = _file_sha256(database, "Intraday Exposed 003 equivalence database")
    fixtures = _load_fixtures(database, fixture_count)
    tasks = tuple(item.specification for item in fixtures)
    factory = _WorkerFactory(repository.resolve(), data_home.resolve())
    input_hashes = _dataset_input_hashes(repository, data_home)

    sequential_start = time.perf_counter()
    sequential = run_process_stage(tasks, worker_factory=factory, workers=1)
    sequential_seconds = time.perf_counter() - sequential_start
    parallel_start = time.perf_counter()
    parallel = run_process_stage(tasks, worker_factory=factory, workers=workers)
    parallel_seconds = time.perf_counter() - parallel_start
    if _file_sha256(database, "Intraday Exposed 003 equivalence database") != database_sha256:
        raise ValueError("equivalence verification changed Intraday Exposed 003 database bytes")
    if _dataset_input_hashes(repository, data_home) != input_hashes:
        raise ValueError("equivalence verification changed immutable dataset input bytes")

    evidence: list[dict[str, object]] = []
    for fixture, one, many in zip(fixtures, sequential, parallel, strict=True):
        _require_equivalent(fixture, one, "one-worker")
        _require_equivalent(fixture, many, f"{workers}-worker")
        if one != many:
            raise ValueError(f"worker-count equivalence differs for {fixture.run_id}")
        reference = _report(fixture.report_bytes, "reference report")
        replay = _report(many.report_bytes, "replayed report")
        evidence.append(
            {
                "run_id": fixture.run_id,
                "candidate_id": _text(
                    _mapping(fixture.specification.get("context"), "run context"),
                    "candidate_id",
                ),
                "scenario_id": _text(
                    _mapping(fixture.specification.get("context"), "run context"),
                    "scenario_id",
                ),
                "run_fingerprint": fixture.run_fingerprint,
                "fill_trace_fingerprint": many.fill_trace_fingerprint,
                "round_trip_fingerprint": many.round_trip_fingerprint,
                "report_sha256": many.report_sha256,
                "report_fingerprint": many.report_fingerprint,
                "specification_equal": (
                    reference.get("specification") == replay.get("specification")
                ),
                "metrics_equal": reference.get("metrics") == replay.get("metrics"),
                "canonical_report_equal": fixture.report_bytes == many.report_bytes,
            }
        )
    return {
        "schema_version": "intraday-exposed-003-parallel-equivalence-v1",
        "program_id": PROGRAM_ID,
        "verification_source_commit": verification_source_commit,
        "source_database": f"{PROGRAM_ID}/{DATABASE_NAME}",
        "source_database_sha256": database_sha256,
        "source_database_mutated": False,
        "dataset_inputs_mutated": False,
        "fixture_selection": "completed-specification-configuration-and-scenario-only",
        "fixture_count": len(fixtures),
        "worker_counts": [1, workers],
        "comparisons": [
            "run-specification",
            "run-fingerprint",
            "fill-sequence-fingerprint",
            "round-trip-fingerprint",
            "metrics",
            "canonical-report-bytes",
            "canonical-report-sha256",
            "report-fingerprint",
        ],
        "sequential_seconds": _seconds(sequential_seconds),
        "parallel_seconds": _seconds(parallel_seconds),
        "speedup": _ratio(sequential_seconds, parallel_seconds),
        "fixtures": evidence,
        "equivalent": True,
    }


def _load_fixtures(database: Path, count: int) -> tuple[_Fixture, ...]:
    if not database.is_file():
        raise ValueError("Intraday Exposed 003 equivalence database is missing")
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True, timeout=30)
    connection.execute("PRAGMA query_only = ON")
    try:
        rows = connection.execute(
            """
            SELECT run_id, specification_json, run_fingerprint,
                   canonical_report_bytes, canonical_report_sha256,
                   canonical_report_fingerprint
            FROM research_runs
            WHERE status = 'completed' AND canonical_report_sha256 IS NOT NULL
            ORDER BY run_id
            """
        ).fetchall()
    finally:
        connection.close()
    fixtures = tuple(_fixture(row) for row in rows)
    if len(fixtures) < count:
        raise ValueError(
            f"Intraday Exposed 003 has {len(fixtures)} completed runs; {count} are required"
        )
    return _select_fixtures(fixtures, count)


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
                f"Intraday Exposed 003 dataset location is missing: {binding.dataset_id}"
            ) from error
        resolved[binding.dataset_id] = service
    return MappingProxyType(resolved)


def _dataset_input_hashes(repository: Path, data_home: Path) -> dict[str, str]:
    plan = load_intraday_exposed_003_plan(repository)
    result: dict[str, str] = {}
    roots: set[Path] = set()
    for binding in _dataset_bindings(plan.source_plan):
        root = (
            data_home.resolve()
            if binding.data_namespace is None
            else data_home.resolve() / binding.data_namespace
        )
        roots.add(root)
        dataset = root / "datasets" / binding.dataset_id
        for name in ("bars.parquet", "manifest.json", "raw.jsonl"):
            path = dataset / name
            result[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    for root in roots:
        path = root / "catalog.sqlite3"
        result[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _fixture(row: Sequence[object]) -> _Fixture:
    if len(row) != 6:
        raise ValueError("equivalence fixture row differs")
    run_id = str(row[0])
    try:
        specification = _mapping(json.loads(str(row[1])), "fixture specification")
    except json.JSONDecodeError as error:
        raise ValueError("equivalence fixture specification is invalid") from error
    if not isinstance(row[3], bytes):
        raise ValueError("equivalence fixture report bytes differ")
    report_bytes = row[3]
    report_sha256 = str(row[4])
    report_fingerprint = str(row[5])
    report = _report(report_bytes, "fixture report")
    if (
        _run_id(specification) != run_id
        or fingerprint(specification) != row[2]
        or hashlib.sha256(report_bytes).hexdigest() != report_sha256
        or report.get("run_id") != run_id
        or report.get("specification") != specification
        or report.get("specification_fingerprint") != row[2]
        or report.get("report_fingerprint") != report_fingerprint
    ):
        raise ValueError(f"completed equivalence fixture integrity differs: {run_id}")
    unsigned = dict(report)
    del unsigned["report_fingerprint"]
    if fingerprint(unsigned) != report_fingerprint:
        raise ValueError(f"completed equivalence fixture report differs: {run_id}")
    return _Fixture(
        run_id,
        specification,
        str(row[2]),
        report_bytes,
        report_sha256,
        report_fingerprint,
    )


def _select_fixtures(fixtures: Sequence[_Fixture], count: int) -> tuple[_Fixture, ...]:
    remaining = list(fixtures)
    selected: list[_Fixture] = []
    seen_candidates: set[str] = set()
    seen_scenarios: set[str] = set()
    while len(selected) < count:
        ranked = sorted(
            remaining,
            key=lambda item: (
                -(
                    _fixture_context(item, "candidate_id") not in seen_candidates
                    or _fixture_context(item, "scenario_id") not in seen_scenarios
                ),
                _fixture_context(item, "family_id"),
                _fixture_context(item, "candidate_id"),
                _fixture_context(item, "scenario_id"),
                item.run_id,
            ),
        )
        chosen = ranked[0]
        remaining.remove(chosen)
        selected.append(chosen)
        seen_candidates.add(_fixture_context(chosen, "candidate_id"))
        seen_scenarios.add(_fixture_context(chosen, "scenario_id"))
    return tuple(selected)


def _fixture_context(fixture: _Fixture, key: str) -> str:
    return _text(_mapping(fixture.specification.get("context"), "fixture context"), key)


def _require_equivalent(fixture: _Fixture, replay: _Replay, label: str) -> None:
    reference = _report(fixture.report_bytes, "reference report")
    computed = _report(replay.report_bytes, "replayed report")
    reference_details = _mapping(reference.get("details"), "reference details")
    if (
        replay.run_id != fixture.run_id
        or replay.run_fingerprint != fixture.run_fingerprint
        or replay.report_bytes != fixture.report_bytes
        or replay.report_sha256 != fixture.report_sha256
        or replay.report_fingerprint != fixture.report_fingerprint
        or replay.fill_trace_fingerprint != reference_details.get("fill_trace_fingerprint")
        or replay.round_trip_fingerprint != reference_details.get("round_trip_fingerprint")
        or computed.get("specification") != reference.get("specification")
        or computed.get("metrics") != reference.get("metrics")
    ):
        raise ValueError(f"{label} deterministic equivalence differs for {fixture.run_id}")


def _report(raw: bytes, label: str) -> Mapping[str, Any]:
    try:
        return _mapping(json.loads(raw), label)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is invalid") from error


def _required_source_commit(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("equivalence fixture source commit differs")
    return value


def _seconds(value: float) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.000001")))


def _ratio(numerator: float, denominator: float) -> str:
    if denominator <= 0:
        raise ValueError("equivalence timing must be positive")
    return str((Decimal(str(numerator)) / Decimal(str(denominator))).quantize(Decimal("0.001")))


def _file_sha256(path: Path, label: str) -> str:
    if not path.is_file():
        raise ValueError(f"{label} is missing")
    return hashlib.sha256(path.read_bytes()).hexdigest()
