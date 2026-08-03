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

from .fingerprints import canonical_json, canonicalize, fingerprint


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
                    heartbeat_at TEXT,
                    execution_provenance TEXT
                );
                CREATE TABLE IF NOT EXISTS campaign_plans (
                    campaign_id TEXT PRIMARY KEY REFERENCES campaigns(campaign_id),
                    plan_json TEXT NOT NULL,
                    plan_fingerprint TEXT NOT NULL UNIQUE,
                    sealed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS holdout_access (
                    event_id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
                    reviewer TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_holdout_access_per_experiment
                ON holdout_access(experiment_id);
                CREATE TABLE IF NOT EXISTS holdout_run_authorizations (
                    authorization_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    qualification_key TEXT,
                    evidence_fingerprint TEXT NOT NULL UNIQUE,
                    evidence_report_json TEXT NOT NULL,
                    candidate_spec_json TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    authorized_at TEXT NOT NULL,
                    consumed_by_experiment_id TEXT UNIQUE REFERENCES experiments(experiment_id),
                    consumed_at TEXT
                );
                """
            )
            experiment_columns = {
                column[1] for column in connection.execute("PRAGMA table_info(experiments)")
            }
            if "campaign_plan_fingerprint" not in experiment_columns:
                connection.execute(
                    "ALTER TABLE experiments ADD COLUMN campaign_plan_fingerprint TEXT"
                )
            if "execution_provenance" not in experiment_columns:
                connection.execute("ALTER TABLE experiments ADD COLUMN execution_provenance TEXT")
            authorization_columns = {
                column[1]
                for column in connection.execute("PRAGMA table_info(holdout_run_authorizations)")
            }
            if "qualification_key" not in authorization_columns:
                connection.execute(
                    "ALTER TABLE holdout_run_authorizations ADD COLUMN qualification_key TEXT"
                )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS one_authorization_per_qualification
                ON holdout_run_authorizations(qualification_key)
                WHERE qualification_key IS NOT NULL
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

    def create_planned_campaign(self, plan: Mapping[str, object]) -> dict[str, object]:
        from .campaign_specs import parse_training_campaign_plan

        parsed = parse_training_campaign_plan(plan)
        timestamp = _now()
        with self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO campaigns VALUES (?, ?, ?, ?, ?)",
                    (
                        parsed.campaign_id,
                        parsed.name,
                        timestamp,
                        "sealed",
                        parsed.search_budget,
                    ),
                )
                connection.execute(
                    "INSERT INTO campaign_plans VALUES (?, ?, ?, ?)",
                    (
                        parsed.campaign_id,
                        canonical_json(parsed.payload),
                        parsed.plan_fingerprint,
                        timestamp,
                    ),
                )
                for spec in parsed.candidates:
                    connection.execute(
                        """
                        INSERT INTO experiments
                        (experiment_id, campaign_id, spec_json, split, status,
                         qualification_state, created_at, campaign_plan_fingerprint)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            spec.experiment_id,
                            parsed.campaign_id,
                            canonical_json(spec),
                            spec.split.value,
                            ExperimentStatus.PENDING.value,
                            QualificationState.NOT_EVALUATED.value,
                            timestamp,
                            parsed.plan_fingerprint,
                        ),
                    )
            except sqlite3.IntegrityError as error:
                raise ExperimentError(
                    f"sealed campaign already exists: {parsed.campaign_id}"
                ) from error
        return {
            "campaign_id": parsed.campaign_id,
            "name": parsed.name,
            "status": "sealed",
            "search_budget": parsed.search_budget,
            "plan_fingerprint": parsed.plan_fingerprint,
            "declared_candidates": len(parsed.candidates),
        }

    def get_campaign_plan(self, campaign_id: str) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT plan_json, plan_fingerprint, sealed_at
                FROM campaign_plans WHERE campaign_id = ?
                """,
                (campaign_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"sealed campaign plan not found: {campaign_id}")
        return {
            "plan_json": json.loads(str(row[0])),
            "plan_fingerprint": row[1],
            "sealed_at": row[2],
        }

    def get_planned_spec(self, experiment_id: str) -> ExperimentSpec:
        record = self.get(experiment_id)
        if record.get("campaign_plan_fingerprint") is None:
            raise ExperimentError(f"experiment is not from a sealed plan: {experiment_id}")
        spec = record["spec_json"]
        assert isinstance(spec, Mapping)
        return _experiment_spec(spec)

    def _create_holdout_run_authorization(
        self,
        authorization_id: str,
        evidence_report: Mapping[str, object],
        reviewer: str,
        reason: str,
    ) -> None:
        if not authorization_id or not reviewer or not reason:
            raise ValueError("authorization ID, reviewer, and reason are required")
        report = canonicalize(evidence_report)
        if not isinstance(report, dict):
            raise HoldoutAccessError("qualification evidence must be an object")
        _validate_qualification_evidence_report(report)
        evidence_fingerprint = report.get("evidence_fingerprint")
        unsigned_report = dict(report)
        unsigned_report.pop("evidence_fingerprint", None)
        if (
            not isinstance(evidence_fingerprint, str)
            or fingerprint(unsigned_report) != evidence_fingerprint
        ):
            raise HoldoutAccessError("qualification evidence fingerprint does not match")
        qualification = report["qualification"]
        assert isinstance(qualification, dict)
        gates = qualification.get("gates")
        if (
            not isinstance(gates, list)
            or not gates
            or any(
                not isinstance(gate, dict) or not gate.get("approved") or not gate.get("passed")
                for gate in gates
            )
        ):
            raise HoldoutAccessError("holdout run requires approved passing gates")
        candidate_id = report["candidate_id"]
        candidate_spec = report["candidate_specification"]
        assert isinstance(candidate_id, str)
        assert isinstance(candidate_spec, dict)
        _validate_candidate_specification(candidate_spec)
        qualification_key = fingerprint(
            {
                "candidate_id": candidate_id,
                "manifest_fingerprint": report["manifest_fingerprint"],
                "proposal_fingerprint": report["proposal_fingerprint"],
                "source_experiment_ids": report["source_experiment_ids"],
            }
        )
        with self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO holdout_run_authorizations
                    (authorization_id, candidate_id, qualification_key, evidence_fingerprint,
                     evidence_report_json, candidate_spec_json, reviewer, reason, authorized_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        authorization_id,
                        candidate_id,
                        qualification_key,
                        evidence_fingerprint,
                        canonical_json(report),
                        canonical_json(candidate_spec),
                        reviewer,
                        reason,
                        _now(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise HoldoutAccessError(
                    "holdout authorization or qualification evidence already exists"
                ) from error

    def get_holdout_run_authorization(self, authorization_id: str) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM holdout_run_authorizations WHERE authorization_id = ?",
                (authorization_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"holdout authorization not found: {authorization_id}")
            columns = [
                column[1]
                for column in connection.execute("PRAGMA table_info(holdout_run_authorizations)")
            ]
        record = dict(zip(columns, row, strict=True))
        record["evidence_report_json"] = json.loads(str(record["evidence_report_json"]))
        record["candidate_spec_json"] = json.loads(str(record["candidate_spec_json"]))
        return record

    def create_experiment(
        self, spec: ExperimentSpec, holdout_authorization_id: str | None = None
    ) -> None:
        if spec.split is not ExperimentSplit.HOLDOUT and holdout_authorization_id is not None:
            raise HoldoutAccessError("holdout authorization cannot be used for another split")
        created_at = _now()
        with self._connect() as connection:
            if spec.split is ExperimentSplit.HOLDOUT:
                authorization = connection.execute(
                    """
                    SELECT candidate_id, candidate_spec_json
                    FROM holdout_run_authorizations
                    WHERE authorization_id = ? AND consumed_by_experiment_id IS NULL
                    """,
                    (holdout_authorization_id,),
                ).fetchone()
                if authorization is None:
                    raise HoldoutAccessError(
                        "holdout experiment requires an unused stored authorization"
                    )
                _validate_holdout_spec(spec, str(authorization[0]), json.loads(authorization[1]))
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
            if spec.split is ExperimentSplit.HOLDOUT:
                consumed = connection.execute(
                    """
                    UPDATE holdout_run_authorizations
                    SET consumed_by_experiment_id = ?, consumed_at = ?
                    WHERE authorization_id = ? AND consumed_by_experiment_id IS NULL
                    """,
                    (spec.experiment_id, created_at, holdout_authorization_id),
                )
                if consumed.rowcount != 1:
                    raise HoldoutAccessError("holdout authorization was already consumed")

    def claim(self, experiment_id: str) -> None:
        timestamp = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE experiments
                SET status = ?, started_at = COALESCE(started_at, ?), heartbeat_at = ?
                WHERE experiment_id = ? AND status = ?
                  AND campaign_plan_fingerprint IS NULL
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

    def _claim_planned(self, spec: ExperimentSpec) -> None:
        if self.get_planned_spec(spec.experiment_id) != spec:
            raise ExperimentError("stored planned experiment differs")
        timestamp = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE experiments
                SET status = ?, started_at = COALESCE(started_at, ?), heartbeat_at = ?
                WHERE experiment_id = ? AND status = ?
                  AND campaign_plan_fingerprint IS NOT NULL
                """,
                (
                    ExperimentStatus.RUNNING.value,
                    timestamp,
                    timestamp,
                    spec.experiment_id,
                    ExperimentStatus.PENDING.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ExperimentError(f"planned experiment is not pending: {spec.experiment_id}")

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
                    artifact_hashes_json = ?, finished_at = ?, heartbeat_at = NULL,
                    execution_provenance = 'legacy-manual'
                WHERE experiment_id = ? AND status = ?
                  AND campaign_plan_fingerprint IS NULL
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

    def _complete_controlled(
        self,
        experiment_id: str,
        metrics: Mapping[str, object],
        artifact_locations: list[str],
        artifact_hashes: list[str],
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE experiments SET status = ?, metrics_json = ?, artifact_locations_json = ?,
                    artifact_hashes_json = ?, finished_at = ?, heartbeat_at = NULL,
                    execution_provenance = 'controlled-run'
                WHERE experiment_id = ? AND status = ?
                  AND campaign_plan_fingerprint IS NULL AND split != ?
                """,
                (
                    ExperimentStatus.COMPLETED.value,
                    canonical_json(metrics),
                    canonical_json(artifact_locations),
                    canonical_json(artifact_hashes),
                    _now(),
                    experiment_id,
                    ExperimentStatus.RUNNING.value,
                    ExperimentSplit.HOLDOUT.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ExperimentError(f"controlled experiment is not running: {experiment_id}")

    def _complete_planned(
        self,
        spec: ExperimentSpec,
        metrics: Mapping[str, object],
        artifact_locations: list[str],
        artifact_hashes: list[str],
    ) -> None:
        if self.get_planned_spec(spec.experiment_id) != spec:
            raise ExperimentError("stored planned experiment differs")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE experiments SET status = ?, metrics_json = ?, artifact_locations_json = ?,
                    artifact_hashes_json = ?, finished_at = ?, heartbeat_at = NULL,
                    execution_provenance = 'controlled-run'
                WHERE experiment_id = ? AND status = ?
                  AND campaign_plan_fingerprint IS NOT NULL
                """,
                (
                    ExperimentStatus.COMPLETED.value,
                    canonical_json(metrics),
                    canonical_json(artifact_locations),
                    canonical_json(artifact_hashes),
                    _now(),
                    spec.experiment_id,
                    ExperimentStatus.RUNNING.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ExperimentError(f"planned experiment is not running: {spec.experiment_id}")

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
                raise HoldoutAccessError(
                    f"holdout access already exists for experiment: {experiment_id}"
                ) from error

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


_CANDIDATE_SPEC_FIELDS = {
    "strategy_id",
    "strategy_version",
    "strategy_family",
    "parameters",
    "cost_model_version",
    "execution_model_version",
    "dataset_id",
    "dataset_fingerprint",
    "universe_id",
    "universe_fingerprint",
    "validation_start",
    "validation_end",
}

_EVIDENCE_REPORT_FIELDS = {
    "schema_version",
    "manifest_id",
    "manifest_fingerprint",
    "proposal_id",
    "proposal_fingerprint",
    "campaign_id",
    "candidate_id",
    "strategy_id",
    "candidate_specification",
    "source_experiment_ids",
    "metrics",
    "qualification",
    "evidence_fingerprint",
}


def _validate_qualification_evidence_report(report: Mapping[str, object]) -> None:
    if (
        set(report) != _EVIDENCE_REPORT_FIELDS
        or report["schema_version"] != "qualification-evidence-v1"
    ):
        raise HoldoutAccessError("qualification evidence fields differ")
    text_fields = {
        "manifest_id",
        "manifest_fingerprint",
        "proposal_id",
        "proposal_fingerprint",
        "campaign_id",
        "candidate_id",
        "strategy_id",
    }
    if any(not isinstance(report[field], str) or not report[field] for field in text_fields):
        raise HoldoutAccessError("qualification evidence contains an invalid value")
    candidate = report["candidate_specification"]
    if not isinstance(candidate, Mapping) or candidate.get("strategy_id") != report["strategy_id"]:
        raise HoldoutAccessError("qualification evidence candidate differs")
    source_ids = report["source_experiment_ids"]
    if (
        not isinstance(source_ids, list)
        or not source_ids
        or any(not isinstance(item, str) or not item for item in source_ids)
        or len(source_ids) != len(set(source_ids))
    ):
        raise HoldoutAccessError("qualification evidence sources are invalid")
    if not isinstance(report["metrics"], Mapping):
        raise HoldoutAccessError("qualification evidence metrics are invalid")
    qualification = report["qualification"]
    if not isinstance(qualification, dict) or set(qualification) != {
        "experiment_id",
        "state",
        "gates",
        "report_fingerprint",
    }:
        raise HoldoutAccessError("qualification report fields differ")
    if (
        qualification["experiment_id"] != report["candidate_id"]
        or qualification["state"] != QualificationState.QUALIFIED.value
    ):
        raise HoldoutAccessError("holdout run requires qualified evidence")
    unsigned_qualification = dict(qualification)
    report_fingerprint = unsigned_qualification.pop("report_fingerprint")
    if (
        not isinstance(report_fingerprint, str)
        or fingerprint(unsigned_qualification) != report_fingerprint
    ):
        raise HoldoutAccessError("qualification report fingerprint does not match")


def _validate_candidate_specification(candidate: Mapping[str, object]) -> None:
    if set(candidate) != _CANDIDATE_SPEC_FIELDS:
        raise HoldoutAccessError("candidate specification fields differ")
    text_fields = _CANDIDATE_SPEC_FIELDS - {"parameters"}
    if any(not isinstance(candidate[field], str) or not candidate[field] for field in text_fields):
        raise HoldoutAccessError("candidate specification contains an invalid value")
    if not isinstance(candidate["parameters"], Mapping):
        raise HoldoutAccessError("candidate parameters must be an object")
    start = _parse_utc(str(candidate["validation_start"]))
    end = _parse_utc(str(candidate["validation_end"]))
    if start > end:
        raise HoldoutAccessError("candidate validation period is invalid")


def _validate_holdout_spec(
    spec: ExperimentSpec, candidate_id: str, candidate: Mapping[str, object]
) -> None:
    _validate_candidate_specification(candidate)
    if spec.parent_candidate != candidate_id:
        raise HoldoutAccessError("holdout parent does not match the qualified candidate")
    fields = (
        "strategy_id",
        "strategy_version",
        "strategy_family",
        "cost_model_version",
        "execution_model_version",
        "dataset_id",
        "dataset_fingerprint",
        "universe_id",
        "universe_fingerprint",
    )
    if any(getattr(spec, field) != candidate[field] for field in fields) or canonicalize(
        spec.parameters
    ) != canonicalize(candidate["parameters"]):
        raise HoldoutAccessError("holdout specification differs from the qualified candidate")
    if spec.start_timestamp <= _parse_utc(str(candidate["validation_end"])):
        raise HoldoutAccessError("holdout must begin after the validation period")


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise HoldoutAccessError("candidate timestamp is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise HoldoutAccessError("candidate timestamp must be UTC")
    return parsed.astimezone(UTC)


def _experiment_spec(value: Mapping[str, object]) -> ExperimentSpec:
    parameters = value["parameters"]
    random_seed = value["random_seed"]
    parent = value["parent_candidate"]
    if not isinstance(parameters, Mapping):
        raise ExperimentError("stored experiment parameters are invalid")
    if random_seed is not None and type(random_seed) is not int:
        raise ExperimentError("stored experiment random seed is invalid")
    if parent is not None and not isinstance(parent, str):
        raise ExperimentError("stored experiment parent is invalid")
    return ExperimentSpec(
        experiment_id=str(value["experiment_id"]),
        campaign_id=str(value["campaign_id"]),
        strategy_id=str(value["strategy_id"]),
        strategy_version=str(value["strategy_version"]),
        strategy_family=str(value["strategy_family"]),
        code_commit=str(value["code_commit"]),
        dataset_id=str(value["dataset_id"]),
        dataset_fingerprint=str(value["dataset_fingerprint"]),
        universe_id=str(value["universe_id"]),
        universe_fingerprint=str(value["universe_fingerprint"]),
        parameters=parameters,
        cost_model_version=str(value["cost_model_version"]),
        execution_model_version=str(value["execution_model_version"]),
        split=ExperimentSplit(str(value["split"])),
        start_timestamp=_parse_utc(str(value["start_timestamp"])),
        end_timestamp=_parse_utc(str(value["end_timestamp"])),
        random_seed=random_seed,
        creation_reason=str(value["creation_reason"]),
        parent_candidate=parent,
    )


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
