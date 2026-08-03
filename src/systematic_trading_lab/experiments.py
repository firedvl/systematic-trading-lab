"""Durable experiment campaigns, lifecycle state, and holdout protection."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from .fingerprints import canonical_json, canonicalize


class ExperimentSplit(StrEnum):
    TRAINING = "training"
    VALIDATION = "validation"
    HOLDOUT = "holdout"


class ExperimentStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class QualificationState(StrEnum):
    NOT_EVALUATED = "not-evaluated"
    UNAPPROVED = "unapproved"
    QUALIFIED = "qualified"
    REJECTED = "rejected"


class ExperimentError(RuntimeError):
    pass


class HoldoutAccessError(ExperimentError):
    pass


@dataclass(frozen=True)
class ExperimentSpec:
    experiment_id: str
    campaign_id: str
    strategy_id: str
    strategy_version: str
    strategy_family: str
    code_commit: str
    dataset_id: str
    dataset_fingerprint: str
    universe_id: str
    universe_fingerprint: str
    parameters: Mapping[str, object]
    cost_model_version: str
    execution_model_version: str
    split: ExperimentSplit
    start_timestamp: datetime
    end_timestamp: datetime
    random_seed: int | None
    creation_reason: str
    parent_candidate: str | None = None

    def __post_init__(self) -> None:
        if not self.experiment_id or not self.campaign_id:
            raise ValueError("experiment and campaign IDs are required")
        if any(
            value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
            for value in (self.start_timestamp, self.end_timestamp)
        ):
            raise ValueError("experiment timestamps must be UTC-aware")
        if self.start_timestamp > self.end_timestamp:
            raise ValueError("experiment start must not follow end")
        if not self.creation_reason:
            raise ValueError("creation reason is required")


class ExperimentRegistry:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS campaigns (
                    campaign_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    search_budget INTEGER NOT NULL CHECK (search_budget > 0)
                );
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
                    spec_json TEXT NOT NULL,
                    split TEXT NOT NULL,
                    status TEXT NOT NULL,
                    failure_info TEXT,
                    metrics_json TEXT,
                    artifact_locations_json TEXT,
                    artifact_hashes_json TEXT,
                    qualification_state TEXT NOT NULL,
                    qualification_report_json TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    heartbeat_at TEXT
                );
                CREATE TABLE IF NOT EXISTS holdout_access (
                    event_id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
                    reviewer TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def create_campaign(self, campaign_id: str, name: str, search_budget: int) -> dict[str, object]:
        if not campaign_id or not name or search_budget < 1:
            raise ValueError("campaign ID, name, and positive search budget are required")
        created_at = _now()
        with self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO campaigns VALUES (?, ?, ?, ?, ?)",
                    (campaign_id, name, created_at, "active", search_budget),
                )
            except sqlite3.IntegrityError as error:
                raise ExperimentError(f"campaign already exists: {campaign_id}") from error
        return {
            "campaign_id": campaign_id,
            "name": name,
            "status": "active",
            "search_budget": search_budget,
        }

    def create_experiment(self, spec: ExperimentSpec, holdout_authorized: bool = False) -> None:
        if spec.split is ExperimentSplit.HOLDOUT and not holdout_authorized:
            raise HoldoutAccessError("holdout experiments require an explicit qualification event")
        created_at = _now()
        with self._connect() as connection:
            campaign = connection.execute(
                "SELECT search_budget FROM campaigns WHERE campaign_id = ? AND status = 'active'",
                (spec.campaign_id,),
            ).fetchone()
            if campaign is None:
                raise ExperimentError(f"active campaign not found: {spec.campaign_id}")
            count = connection.execute(
                "SELECT COUNT(*) FROM experiments WHERE campaign_id = ?", (spec.campaign_id,)
            ).fetchone()
            assert count is not None
            if int(count[0]) >= int(campaign[0]):
                raise ExperimentError("campaign search budget exhausted")
            try:
                connection.execute(
                    """
                    INSERT INTO experiments
                    (experiment_id, campaign_id, spec_json, split, status,
                     qualification_state, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        spec.experiment_id,
                        spec.campaign_id,
                        canonical_json(spec),
                        spec.split.value,
                        ExperimentStatus.PENDING.value,
                        QualificationState.NOT_EVALUATED.value,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ExperimentError(f"experiment already exists: {spec.experiment_id}") from error

    def claim(self, experiment_id: str) -> None:
        timestamp = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE experiments
                SET status = ?, started_at = COALESCE(started_at, ?), heartbeat_at = ?
                WHERE experiment_id = ? AND status = ?
                """,
                (
                    ExperimentStatus.RUNNING.value,
                    timestamp,
                    timestamp,
                    experiment_id,
                    ExperimentStatus.PENDING.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ExperimentError(f"experiment is not pending: {experiment_id}")

    def heartbeat(self, experiment_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE experiments SET heartbeat_at = ? WHERE experiment_id = ? AND status = ?",
                (_now(), experiment_id, ExperimentStatus.RUNNING.value),
            )
            if cursor.rowcount != 1:
                raise ExperimentError(f"running experiment not found: {experiment_id}")

    def complete(
        self,
        experiment_id: str,
        metrics: Mapping[str, object],
        artifact_locations: list[str] | None = None,
        artifact_hashes: list[str] | None = None,
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE experiments SET status = ?, metrics_json = ?, artifact_locations_json = ?,
                    artifact_hashes_json = ?, finished_at = ?, heartbeat_at = NULL
                WHERE experiment_id = ? AND status = ?
                """,
                (
                    ExperimentStatus.COMPLETED.value,
                    canonical_json(metrics),
                    canonical_json(artifact_locations or []),
                    canonical_json(artifact_hashes or []),
                    _now(),
                    experiment_id,
                    ExperimentStatus.RUNNING.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ExperimentError(f"experiment is not running: {experiment_id}")

    def fail(self, experiment_id: str, reason: str) -> None:
        if not reason:
            raise ValueError("failure reason is required")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE experiments
                SET status = ?, failure_info = ?, finished_at = ?, heartbeat_at = NULL
                WHERE experiment_id = ? AND status IN (?, ?)
                """,
                (
                    ExperimentStatus.FAILED.value,
                    reason,
                    _now(),
                    experiment_id,
                    ExperimentStatus.PENDING.value,
                    ExperimentStatus.RUNNING.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ExperimentError(f"experiment cannot be failed: {experiment_id}")

    def recover_stale(self, max_age: timedelta) -> list[str]:
        if max_age <= timedelta(0):
            raise ValueError("max_age must be positive")
        cutoff = datetime.now(UTC) - max_age
        recovered: list[str] = []
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT experiment_id, heartbeat_at FROM experiments WHERE status = ?",
                (ExperimentStatus.RUNNING.value,),
            ).fetchall()
            for experiment_id, heartbeat in rows:
                if heartbeat is None or datetime.fromisoformat(heartbeat) < cutoff:
                    connection.execute(
                        """
                        UPDATE experiments
                        SET status = ?, failure_info = ?, finished_at = ?, heartbeat_at = NULL
                        WHERE experiment_id = ?
                        """,
                        (
                            ExperimentStatus.FAILED.value,
                            "stale-run-recovered",
                            _now(),
                            experiment_id,
                        ),
                    )
                    recovered.append(experiment_id)
        return recovered

    def authorize_holdout(
        self, experiment_id: str, event_id: str, reviewer: str, reason: str
    ) -> None:
        if not event_id or not reviewer or not reason:
            raise ValueError("holdout event ID, reviewer, and reason are required")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT split, status FROM experiments WHERE experiment_id = ?", (experiment_id,)
            ).fetchone()
            if row is None or row[0] != ExperimentSplit.HOLDOUT.value:
                raise HoldoutAccessError("experiment is not a holdout")
            if row[1] != ExperimentStatus.COMPLETED.value:
                raise HoldoutAccessError("only completed holdouts can be evaluated")
            try:
                connection.execute(
                    "INSERT INTO holdout_access VALUES (?, ?, ?, ?, ?)",
                    (event_id, experiment_id, reviewer, reason, _now()),
                )
            except sqlite3.IntegrityError as error:
                raise HoldoutAccessError(f"holdout event already exists: {event_id}") from error

    def record_qualification(
        self,
        experiment_id: str,
        state: QualificationState,
        report: object,
        holdout_event_id: str | None = None,
    ) -> None:
        if state is QualificationState.NOT_EVALUATED:
            raise ValueError("qualification result must be evaluated")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT split, status FROM experiments WHERE experiment_id = ?", (experiment_id,)
            ).fetchone()
            if row is None or row[1] != ExperimentStatus.COMPLETED.value:
                raise ExperimentError("only completed experiments can be qualified")
            if row[0] == ExperimentSplit.HOLDOUT.value:
                authorized = connection.execute(
                    "SELECT 1 FROM holdout_access WHERE event_id = ? AND experiment_id = ?",
                    (holdout_event_id, experiment_id),
                ).fetchone()
                if authorized is None:
                    raise HoldoutAccessError("holdout qualification requires its access event")
            report_data = canonicalize(report)
            if not isinstance(report_data, dict) or report_data.get("state") != state.value:
                raise ExperimentError("qualification report state does not match registry state")
            gates = report_data.get("gates")
            if not isinstance(gates, list) or not gates:
                raise ExperimentError("qualification report requires gate evidence")
            if state is QualificationState.QUALIFIED and any(
                not isinstance(gate, dict) or not gate.get("approved") or not gate.get("passed")
                for gate in gates
            ):
                raise ExperimentError("qualified state requires approved passing gates")
            connection.execute(
                """
                UPDATE experiments
                SET qualification_state = ?, qualification_report_json = ?
                WHERE experiment_id = ?
                """,
                (state.value, canonical_json(report_data), experiment_id),
            )

    def get(self, experiment_id: str, holdout_event_id: str | None = None) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM experiments WHERE experiment_id = ?", (experiment_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"experiment not found: {experiment_id}")
            columns = [column[1] for column in connection.execute("PRAGMA table_info(experiments)")]
            record = dict(zip(columns, row, strict=True))
            if record["split"] == ExperimentSplit.HOLDOUT.value:
                authorized = connection.execute(
                    "SELECT 1 FROM holdout_access WHERE event_id = ? AND experiment_id = ?",
                    (holdout_event_id, experiment_id),
                ).fetchone()
                if authorized is None:
                    record["metrics_json"] = None
                    record["holdout_metrics_protected"] = True
            for key in (
                "spec_json",
                "metrics_json",
                "artifact_locations_json",
                "artifact_hashes_json",
                "qualification_report_json",
            ):
                if record[key] is not None:
                    record[key] = json.loads(record[key])
            return record

    def list(self, campaign_id: str | None = None) -> list[dict[str, object]]:
        query = "SELECT experiment_id FROM experiments"
        parameters: tuple[str, ...] = ()
        if campaign_id is not None:
            query += " WHERE campaign_id = ?"
            parameters = (campaign_id,)
        query += " ORDER BY created_at, experiment_id"
        with self._connect() as connection:
            identifiers = connection.execute(query, parameters).fetchall()
        return [self.get(row[0]) for row in identifiers]

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
