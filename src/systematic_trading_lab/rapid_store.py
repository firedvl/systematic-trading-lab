"""Separate storage for exploratory Rapid Research data and results."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .fingerprints import canonical_json, canonicalize, fingerprint

RAPID_AUTHORITY: Mapping[str, bool] = MappingProxyType(
    {
        "controlled_research_evidence": False,
        "qualification": False,
        "protected_holdout": False,
        "paper_execution": False,
        "broker_writes": False,
        "live_execution": False,
        "automatic_promotion": False,
    }
)


def rapid_authority() -> dict[str, bool]:
    authority = dict(RAPID_AUTHORITY)
    if any(value is not False for value in authority.values()):
        raise ValueError("Rapid Research authority flags must all be false")
    return authority


class RapidResearchStore:
    """SQLite index plus create-only artifacts outside controlled registries."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.path = self.root / "rapid-research.sqlite3"
        self.artifacts = self.root / "rapid-research"
        self.datasets = self.artifacts / "datasets"
        self.reports = self.artifacts / "reports"
        self.candidates = self.artifacts / "candidates"
        self.root.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS rapid_datasets (
                    dataset_id TEXT PRIMARY KEY,
                    dataset_fingerprint TEXT NOT NULL,
                    source_format TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    data_origin TEXT NOT NULL,
                    adjustment_policy TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    start_timestamp TEXT NOT NULL,
                    end_timestamp TEXT NOT NULL,
                    symbols_json TEXT NOT NULL,
                    bar_count INTEGER NOT NULL,
                    artifact_path TEXT NOT NULL UNIQUE,
                    imported_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rapid_runs (
                    run_id TEXT PRIMARY KEY,
                    configuration_fingerprint TEXT NOT NULL UNIQUE,
                    run_type TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
                    group_id TEXT,
                    parent_run_id TEXT,
                    dataset_id TEXT NOT NULL,
                    dataset_fingerprint TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    start_timestamp TEXT NOT NULL,
                    end_timestamp TEXT NOT NULL,
                    cost_model_version TEXT NOT NULL,
                    slippage_bps TEXT NOT NULL,
                    commission_bps TEXT NOT NULL,
                    fill_delay_bars INTEGER NOT NULL,
                    code_commit TEXT,
                    code_dirty INTEGER,
                    specification_json TEXT NOT NULL,
                    metrics_json TEXT,
                    report_path TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS rapid_runs_created
                    ON rapid_runs(created_at DESC, run_id DESC);
                CREATE INDEX IF NOT EXISTS rapid_runs_group
                    ON rapid_runs(group_id, created_at, run_id);
                """
            )

    def put_dataset(
        self,
        metadata: Mapping[str, object],
        artifact: bytes,
    ) -> dict[str, object]:
        required = {
            "dataset_id",
            "dataset_fingerprint",
            "source_format",
            "source_sha256",
            "source_path",
            "data_origin",
            "adjustment_policy",
            "timeframe",
            "start_timestamp",
            "end_timestamp",
            "symbols",
            "bar_count",
            "imported_at",
        }
        if set(metadata) != required:
            raise ValueError("rapid dataset metadata fields differ")
        dataset_id = _text(metadata["dataset_id"], "dataset ID")
        path = self.datasets / f"{dataset_id}.parquet"
        self.datasets.mkdir(parents=True, exist_ok=True)
        _write_create_only(path, artifact)
        encoded = canonicalize(metadata)
        assert isinstance(encoded, dict)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO rapid_datasets (
                    dataset_id, dataset_fingerprint, source_format, source_sha256,
                    source_path, data_origin, adjustment_policy, timeframe,
                    start_timestamp, end_timestamp,
                    symbols_json, bar_count, artifact_path, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    encoded["dataset_fingerprint"],
                    encoded["source_format"],
                    encoded["source_sha256"],
                    encoded["source_path"],
                    encoded["data_origin"],
                    encoded["adjustment_policy"],
                    encoded["timeframe"],
                    encoded["start_timestamp"],
                    encoded["end_timestamp"],
                    canonical_json(encoded["symbols"]),
                    encoded["bar_count"],
                    str(path),
                    encoded["imported_at"],
                ),
            )
        stored = self.get_dataset(dataset_id)
        if stored is None or any(stored[key] != encoded[key] for key in required):
            raise ValueError("stored rapid dataset differs from the import")
        return stored

    def get_dataset(self, dataset_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT dataset_id, dataset_fingerprint, source_format, source_sha256,
                       source_path, data_origin, adjustment_policy, timeframe,
                       start_timestamp, end_timestamp,
                       symbols_json, bar_count, artifact_path, imported_at
                FROM rapid_datasets WHERE dataset_id = ?
                """,
                (dataset_id,),
            ).fetchone()
        return None if row is None else _dataset_record(row)

    def list_datasets(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT dataset_id, dataset_fingerprint, source_format, source_sha256,
                       source_path, data_origin, adjustment_policy, timeframe,
                       start_timestamp, end_timestamp,
                       symbols_json, bar_count, artifact_path, imported_at
                FROM rapid_datasets ORDER BY imported_at DESC, dataset_id DESC
                """
            ).fetchall()
        return [_dataset_record(row) for row in rows]

    def begin_run(self, specification: Mapping[str, object]) -> dict[str, object]:
        _validate_run_specification(specification)
        canonical = canonicalize(specification)
        assert isinstance(canonical, dict)
        configuration_fingerprint = fingerprint(canonical)
        run_id = f"rr-{configuration_fingerprint[:20]}"
        strategy = _mapping(canonical["strategy"], "strategy")
        dataset = _mapping(canonical["dataset"], "dataset")
        costs = _mapping(canonical["costs"], "costs")
        execution = _mapping(canonical["execution"], "execution")
        code = _mapping(canonical["code"], "code")
        created_at = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO rapid_runs (
                    run_id, configuration_fingerprint, run_type, status, group_id,
                    parent_run_id, dataset_id, dataset_fingerprint, strategy_name,
                    strategy_id, strategy_version, parameters_json, timeframe,
                    start_timestamp, end_timestamp, cost_model_version, slippage_bps,
                    commission_bps, fill_delay_bars, code_commit, code_dirty,
                    specification_json, created_at
                ) VALUES (
                    ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    run_id,
                    configuration_fingerprint,
                    canonical["run_type"],
                    canonical.get("group_id"),
                    canonical.get("parent_run_id"),
                    dataset["id"],
                    dataset["fingerprint"],
                    strategy["name"],
                    strategy["id"],
                    strategy["version"],
                    canonical_json(strategy["parameters"]),
                    dataset["timeframe"],
                    canonical["start_timestamp"],
                    canonical["end_timestamp"],
                    costs["version"],
                    costs["slippage_bps"],
                    costs["commission_bps"],
                    execution["fill_delay_bars"],
                    code.get("commit"),
                    None if code.get("dirty") is None else int(bool(code["dirty"])),
                    canonical_json(canonical),
                    created_at,
                ),
            )
        record = self.get_run(run_id)
        if record["configuration_fingerprint"] != configuration_fingerprint:
            raise ValueError("rapid run ID collision")
        return record

    def finish_run(
        self,
        run_id: str,
        metrics: Mapping[str, object] | None,
        details: Mapping[str, object],
        *,
        error: str | None = None,
    ) -> dict[str, object]:
        record = self.get_run(run_id)
        status = "failed" if error is not None else "completed"
        path = self.reports / f"{run_id}.json"
        completed_at = _now()
        if path.exists():
            stored_report = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(stored_report, dict):
                raise ValueError("stored Rapid Research report must be an object")
            completed_at = _text(stored_report.get("completed_at"), "report completion time")
        report = {
            "schema_version": "rapid-research-report-v1",
            "evidence_class": "exploratory-uncontrolled",
            "run_id": run_id,
            "status": status,
            "created_at": record["created_at"],
            "completed_at": completed_at,
            "specification": record["specification"],
            "metrics": metrics,
            "details": details,
            "error": error,
            "authority": rapid_authority(),
        }
        report["report_fingerprint"] = fingerprint(report)
        self.reports.mkdir(parents=True, exist_ok=True)
        _write_create_only(path, (canonical_json(report) + "\n").encode())
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE rapid_runs
                SET status = ?, metrics_json = ?, report_path = ?, error = ?, completed_at = ?
                WHERE run_id = ? AND status = 'pending'
                """,
                (
                    status,
                    None if metrics is None else canonical_json(metrics),
                    str(path),
                    error,
                    report["completed_at"],
                    run_id,
                ),
            )
            if cursor.rowcount == 0 and record["status"] == "pending":
                raise ValueError("rapid run state changed during completion")
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM rapid_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError("rapid research run not found")
        return _run_record(row)

    def list_runs(self, *, group_id: str | None = None) -> list[dict[str, object]]:
        query = "SELECT * FROM rapid_runs"
        parameters: tuple[str, ...] = ()
        if group_id is not None:
            query += " WHERE group_id = ?"
            parameters = (group_id,)
        query += " ORDER BY created_at DESC, run_id DESC"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_run_record(row) for row in rows]

    def export_candidate(self, run_id: str) -> dict[str, object]:
        run = self.get_run(run_id)
        if run["status"] != "completed":
            raise ValueError("only a completed Rapid Research run can be exported")
        group_id = run.get("group_id")
        records = self.list_runs(group_id=str(group_id)) if group_id else [run]
        ledger = sorted(
            (_candidate_run(record) for record in records),
            key=lambda item: str(item["run_id"]),
        )
        payload = {
            "schema_version": "rapid-research-candidate-export-v1",
            "evidence_class": "exploratory-uncontrolled",
            "selected_run_id": run_id,
            "selected_run": _candidate_run(run),
            "search_ledger": ledger,
            "search_ledger_fingerprint": fingerprint(ledger),
            "authority": rapid_authority(),
            "promotion_instruction": (
                "Review and create a separate controlled plan; this artifact grants no authority."
            ),
        }
        payload["candidate_fingerprint"] = fingerprint(payload)
        path = self.candidates / f"{run_id}.json"
        self.candidates.mkdir(parents=True, exist_ok=True)
        _write_create_only(path, (canonical_json(payload) + "\n").encode())
        return {**payload, "path": str(path)}

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()


def _validate_run_specification(value: Mapping[str, object]) -> None:
    required = {
        "schema_version",
        "run_type",
        "dataset",
        "strategy",
        "start_timestamp",
        "end_timestamp",
        "initial_cash",
        "costs",
        "execution",
        "code",
    }
    optional = {"group_id", "parent_run_id", "fold", "exploratory_context", "campaign"}
    if set(value) - optional != required or value["schema_version"] != "rapid-research-run-v1":
        raise ValueError("rapid research run fields differ")
    for name in ("dataset", "strategy", "costs", "execution", "code"):
        _mapping(value[name], name)
    if value.get("campaign") is not None:
        _mapping(value["campaign"], "campaign")


def _dataset_record(row: sqlite3.Row) -> dict[str, object]:
    return {
        "dataset_id": row["dataset_id"],
        "dataset_fingerprint": row["dataset_fingerprint"],
        "source_format": row["source_format"],
        "source_sha256": row["source_sha256"],
        "source_path": row["source_path"],
        "data_origin": row["data_origin"],
        "adjustment_policy": row["adjustment_policy"],
        "timeframe": row["timeframe"],
        "start_timestamp": row["start_timestamp"],
        "end_timestamp": row["end_timestamp"],
        "symbols": json.loads(row["symbols_json"]),
        "bar_count": row["bar_count"],
        "artifact_path": row["artifact_path"],
        "imported_at": row["imported_at"],
    }


def _run_record(row: sqlite3.Row) -> dict[str, object]:
    return {
        "run_id": row["run_id"],
        "configuration_fingerprint": row["configuration_fingerprint"],
        "run_type": row["run_type"],
        "status": row["status"],
        "group_id": row["group_id"],
        "parent_run_id": row["parent_run_id"],
        "dataset_id": row["dataset_id"],
        "dataset_fingerprint": row["dataset_fingerprint"],
        "strategy_name": row["strategy_name"],
        "strategy_id": row["strategy_id"],
        "strategy_version": row["strategy_version"],
        "parameters": json.loads(row["parameters_json"]),
        "timeframe": row["timeframe"],
        "start_timestamp": row["start_timestamp"],
        "end_timestamp": row["end_timestamp"],
        "cost_model_version": row["cost_model_version"],
        "slippage_bps": row["slippage_bps"],
        "commission_bps": row["commission_bps"],
        "fill_delay_bars": row["fill_delay_bars"],
        "code_commit": row["code_commit"],
        "code_dirty": None if row["code_dirty"] is None else bool(row["code_dirty"]),
        "specification": json.loads(row["specification_json"]),
        "metrics": None if row["metrics_json"] is None else json.loads(row["metrics_json"]),
        "report_path": row["report_path"],
        "error": row["error"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
    }


def _candidate_run(run: Mapping[str, object]) -> dict[str, object]:
    return {
        "run_id": run["run_id"],
        "configuration_fingerprint": run["configuration_fingerprint"],
        "run_type": run["run_type"],
        "status": run["status"],
        "group_id": run.get("group_id"),
        "parent_run_id": run.get("parent_run_id"),
        "specification": run["specification"],
        "metrics": run["metrics"],
        "error": run["error"],
    }


def _write_create_only(path: Path, contents: bytes) -> None:
    if path.exists():
        if path.read_bytes() != contents:
            raise FileExistsError(
                f"rapid research artifact already exists with other bytes: {path}"
            )
        return
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(temporary_name)
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


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"rapid {label} must be an object")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"rapid {label} must be nonempty text")
    return value


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
