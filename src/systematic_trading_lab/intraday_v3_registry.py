"""Isolated, fail-closed durable registry for the prospectively sealed V3 campaign."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .datasets import DatasetService
from .experiments import ExperimentError
from .fingerprints import canonical_json, canonicalize, fingerprint
from .intraday_source_provenance import write_intraday_execution_report
from .intraday_v3 import IntradayV3ExperimentSpec
from .intraday_v3_campaign import (
    IntradayV3CampaignPlan,
    build_intraday_v3_experiments,
    load_intraday_v3_campaign_plan,
    parse_intraday_v3_campaign_plan,
    parse_intraday_v3_experiment,
)
from .intraday_v3_freshness import (
    IntradayV3PublicationSeal,
    verify_intraday_v3_publication_seal,
)
from .intraday_v3_source_provenance import (
    IntradayV3SourceAssessment,
    IntradayV3SourcePreassessment,
    assess_intraday_v3_source_preassessment,
    bind_intraday_v3_source_assessment,
)
from .storage import StorageLayout

V3_CAMPAIGN_ID = "intraday-research-v3"
_ROLES = ("training", "validation-a", "validation-b", "validation-c")
_PENDING = "pending"
_RUNNING = "running"
_COMPLETE = "completed"
_FAILED = "failed"


class IntradayV3RegistryError(ExperimentError):
    """V3 registry evidence is absent, malformed, or in an invalid lifecycle state."""


class _PublicationConflictError(Exception):
    def __init__(
        self,
        reason: str,
        observed_kind: str,
        observed_sha256: str | None = None,
        observed_size: int | None = None,
    ) -> None:
        super().__init__(reason)
        self.observed_kind = observed_kind
        self.observed_sha256 = observed_sha256
        self.observed_size = observed_size


@dataclass(frozen=True)
class IntradayV3Claim:
    spec: IntradayV3ExperimentSpec
    token: str


class IntradayV3Registry:
    """Owns only ``intraday_v3_*`` tables; it never creates execution authority."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS intraday_v3_seals (
                  campaign_id TEXT PRIMARY KEY,
                  seal_json TEXT NOT NULL,
                  seal_fingerprint TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS intraday_v3_plans (
                  campaign_id TEXT PRIMARY KEY REFERENCES intraday_v3_seals(campaign_id),
                  plan_json TEXT NOT NULL,
                  plan_fingerprint TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS intraday_v3_reservations (
                  experiment_id TEXT PRIMARY KEY,
                  campaign_id TEXT NOT NULL REFERENCES intraday_v3_plans(campaign_id),
                  candidate_ordinal INTEGER NOT NULL UNIQUE,
                  reservation_json TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS intraday_v3_datasets (
                  campaign_id TEXT NOT NULL REFERENCES intraday_v3_plans(campaign_id),
                  period_role TEXT NOT NULL,
                  manifest_json TEXT NOT NULL,
                  dataset_id TEXT NOT NULL,
                  dataset_fingerprint TEXT NOT NULL,
                  PRIMARY KEY (campaign_id, period_role),
                  UNIQUE (campaign_id, dataset_id));
                CREATE TABLE IF NOT EXISTS intraday_v3_specs (
                  experiment_id TEXT PRIMARY KEY REFERENCES intraday_v3_reservations(experiment_id),
                  spec_json TEXT NOT NULL UNIQUE,
                  spec_fingerprint TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS intraday_v3_source_reviews (
                  review_id TEXT PRIMARY KEY,
                  campaign_id TEXT NOT NULL UNIQUE REFERENCES intraday_v3_plans(campaign_id),
                  review_json TEXT NOT NULL UNIQUE,
                  review_fingerprint TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS intraday_v3_execution_sources (
                  experiment_id TEXT PRIMARY KEY REFERENCES intraday_v3_specs(experiment_id),
                  review_id TEXT NOT NULL REFERENCES intraday_v3_source_reviews(review_id),
                  binding_json TEXT NOT NULL UNIQUE,
                  binding_fingerprint TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS intraday_v3_lifecycle (
                  experiment_id TEXT PRIMARY KEY REFERENCES intraday_v3_reservations(experiment_id),
                  status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed')),
                  failure_info TEXT,
                  claim_token TEXT,
                  started_at TEXT,
                  heartbeat_at TEXT,
                  finished_at TEXT,
                  CHECK((status != 'failed') OR (failure_info IS NOT NULL
                    AND length(trim(failure_info)) > 0)),
                  CHECK((status NOT IN ('completed','failed')) OR (finished_at IS NOT NULL
                    AND heartbeat_at IS NULL)),
                  CHECK((status != 'pending') OR (failure_info IS NULL AND claim_token IS NULL
                    AND started_at IS NULL
                    AND heartbeat_at IS NULL AND finished_at IS NULL)),
                  CHECK((status != 'running') OR (failure_info IS NULL AND claim_token IS NOT NULL
                    AND started_at IS NOT NULL AND heartbeat_at IS NOT NULL
                    AND finished_at IS NULL)),
                  CHECK((status NOT IN ('completed','failed')) OR claim_token IS NULL),
                  CHECK((status != 'completed') OR failure_info IS NULL));
                CREATE TABLE IF NOT EXISTS intraday_v3_results (
                  experiment_id TEXT PRIMARY KEY REFERENCES intraday_v3_reservations(experiment_id),
                  result_json TEXT NOT NULL UNIQUE,
                  result_fingerprint TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS intraday_v3_publications (
                  experiment_id TEXT PRIMARY KEY REFERENCES intraday_v3_specs(experiment_id),
                  publication_json TEXT NOT NULL UNIQUE,
                  publication_fingerprint TEXT NOT NULL UNIQUE,
                  owner_token TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS intraday_v3_publication_conflicts (
                  experiment_id TEXT PRIMARY KEY REFERENCES intraday_v3_publications(experiment_id),
                  conflict_json TEXT NOT NULL UNIQUE,
                  conflict_fingerprint TEXT NOT NULL UNIQUE);
                """
                + "\n".join(
                    f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} "
                    f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END;\n"
                    f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} "
                    f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END;"
                    for table in (
                        "intraday_v3_seals",
                        "intraday_v3_plans",
                        "intraday_v3_reservations",
                        "intraday_v3_datasets",
                        "intraday_v3_specs",
                        "intraday_v3_source_reviews",
                        "intraday_v3_execution_sources",
                        "intraday_v3_results",
                        "intraday_v3_publications",
                        "intraday_v3_publication_conflicts",
                    )
                )
                + """
                DROP TRIGGER IF EXISTS intraday_v3_publications_no_update;
                CREATE TRIGGER IF NOT EXISTS intraday_v3_publications_owner_only
                BEFORE UPDATE ON intraday_v3_publications
                WHEN NOT (OLD.experiment_id IS NEW.experiment_id
                  AND OLD.publication_json IS NEW.publication_json
                  AND OLD.publication_fingerprint IS NEW.publication_fingerprint
                  AND OLD.owner_token IS NOT NEW.owner_token
                  AND EXISTS (
                    SELECT 1 FROM intraday_v3_lifecycle
                    WHERE experiment_id = OLD.experiment_id AND status = 'running'
                      AND claim_token = OLD.owner_token))
                BEGIN SELECT RAISE(ABORT, 'invalid V3 publication ownership transfer'); END;
                DROP TRIGGER IF EXISTS intraday_v3_lifecycle_transitions;
                CREATE TRIGGER IF NOT EXISTS intraday_v3_lifecycle_transitions
                BEFORE UPDATE ON intraday_v3_lifecycle
                WHEN NOT ((OLD.status = 'pending' AND NEW.status IN ('running','failed'))
                  OR (OLD.status = 'running' AND NEW.status IN ('completed','failed'))
                  OR (OLD.status = 'running' AND NEW.status = 'running'
                    AND OLD.failure_info IS NEW.failure_info
                    AND OLD.claim_token IS NEW.claim_token
                    AND OLD.started_at IS NEW.started_at
                    AND OLD.finished_at IS NEW.finished_at)
                  OR (OLD.status = 'running' AND NEW.status = 'running'
                    AND OLD.failure_info IS NEW.failure_info
                    AND OLD.claim_token IS NOT NEW.claim_token
                    AND OLD.started_at IS NEW.started_at
                    AND OLD.finished_at IS NEW.finished_at
                    AND EXISTS (
                      SELECT 1 FROM intraday_v3_publications
                      WHERE experiment_id = OLD.experiment_id
                        AND owner_token = NEW.claim_token)))
                BEGIN SELECT RAISE(ABORT, 'invalid V3 candidate lifecycle transition'); END;
                CREATE TRIGGER IF NOT EXISTS intraday_v3_lifecycle_no_delete
                BEFORE DELETE ON intraday_v3_lifecycle
                BEGIN SELECT RAISE(ABORT, 'V3 lifecycle evidence is durable'); END;
                """
            )

    def materialize(
        self,
        seal_path: Path,
        inventory_path: Path,
        selection_path: Path,
        plan_path: Path,
        qualification_binding_path: Path,
    ) -> dict[str, object]:
        """Atomically record a verified seal, plan, and all 60 pending reservations."""

        plan = load_intraday_v3_campaign_plan(plan_path)
        publication_seal = verify_intraday_v3_publication_seal(
            seal_path,
            inventory_path,
            selection_path,
            plan_path,
            qualification_binding_path,
        )
        self._check_plan(plan)
        self._check_seal(plan, publication_seal)
        campaign_id = _field(plan, "campaign_id")
        candidates = tuple(_field(plan, "candidates"))
        raw_seal = seal_path.read_bytes()
        if hashlib.sha256(raw_seal).hexdigest() != publication_seal.seal_sha256:
            raise IntradayV3RegistryError("V3 publication seal changed after verification")
        seal_json = {
            "artifact_json": raw_seal.decode("utf-8"),
            "verification": _json_value(publication_seal),
        }
        plan_json = _json_value(_field(plan, "payload"))
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO intraday_v3_seals VALUES (?, ?, ?)",
                    (campaign_id, canonical_json(seal_json), fingerprint(seal_json)),
                )
                connection.execute(
                    "INSERT INTO intraday_v3_plans VALUES (?, ?, ?)",
                    (campaign_id, canonical_json(plan_json), _field(plan, "plan_fingerprint")),
                )
                for candidate in candidates:
                    experiment_id = _field(candidate, "experiment_id")
                    connection.execute(
                        "INSERT INTO intraday_v3_reservations VALUES (?, ?, ?, ?)",
                        (
                            experiment_id,
                            campaign_id,
                            _field(candidate, "candidate_ordinal"),
                            canonical_json(_json_value(candidate)),
                        ),
                    )
                    connection.execute(
                        "INSERT INTO intraday_v3_lifecycle VALUES "
                        "(?, ?, NULL, NULL, NULL, NULL, NULL)",
                        (experiment_id, _PENDING),
                    )
        except sqlite3.IntegrityError as error:
            raise IntradayV3RegistryError("V3 campaign is already materialized") from error
        return {
            "campaign_id": campaign_id,
            "plan_fingerprint": _field(plan, "plan_fingerprint"),
            "reserved_candidates": len(candidates),
            "status": "sealed",
        }

    def bind_datasets(
        self, layout: StorageLayout, dataset_ids: Mapping[str, str]
    ) -> tuple[dict[str, object], ...]:
        """Validate all four dataset roles before writing any V3 binding or bound spec."""

        if type(layout) is not StorageLayout or self.path.resolve() != layout.experiments.resolve():
            raise IntradayV3RegistryError("V3 datasets and registry must share one storage root")
        plan = self._stored_plan()
        self._check_plan(plan)
        if (
            set(dataset_ids) != set(_ROLES)
            or any(not isinstance(value, str) or not value for value in dataset_ids.values())
            or len(set(dataset_ids.values())) != len(_ROLES)
        ):
            raise IntradayV3RegistryError(
                "V3 dataset bindings must name four distinct catalog datasets"
            )
        try:
            datasets = DatasetService(layout)
            manifests: dict[str, Mapping[str, object]] = {}
            for role in _ROLES:
                dataset_id = dataset_ids[role]
                before = datasets.describe(dataset_id)
                validation = datasets.validate(dataset_id)
                after = datasets.describe(dataset_id)
                identity = after.get("identity")
                if (
                    not validation.get("valid")
                    or before != after
                    or not isinstance(identity, Mapping)
                    or validation.get("dataset_id") != dataset_id
                    or validation.get("fingerprint") != identity.get("fingerprint")
                ):
                    raise ValueError("V3 catalog dataset failed full integrity validation")
                manifests[role] = after
            source_commit = self._source_commit(plan.campaign_id)
            bound_specs = build_intraday_v3_experiments(plan, source_commit, manifests)
        except (KeyError, OSError, TypeError, ValueError) as error:
            raise IntradayV3RegistryError(
                "V3 catalog datasets differ from the sealed plan or failed validation"
            ) from error
        specs = tuple(_json_value(spec) for spec in bound_specs)
        if not all(isinstance(spec, dict) for spec in specs):
            raise IntradayV3RegistryError("canonical V3 bound spec is invalid")
        campaign_id = _field(plan, "campaign_id")
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                stored = connection.execute(
                    "SELECT plan_fingerprint FROM intraday_v3_plans WHERE campaign_id = ?",
                    (campaign_id,),
                ).fetchone()
                if stored is None or stored[0] != _field(plan, "plan_fingerprint"):
                    raise IntradayV3RegistryError("V3 plan is not materialized exactly")
                for role in _ROLES:
                    manifest = manifests[role]
                    identity = _manifest_identity(manifest)
                    connection.execute(
                        "INSERT INTO intraday_v3_datasets VALUES (?, ?, ?, ?, ?)",
                        (
                            campaign_id,
                            role,
                            canonical_json(manifest),
                            identity["dataset_id"],
                            identity["fingerprint"],
                        ),
                    )
                for spec in specs:
                    connection.execute(
                        "INSERT INTO intraday_v3_specs VALUES (?, ?, ?)",
                        (
                            str(spec["experiment_id"]),
                            canonical_json(spec),
                            fingerprint(spec),
                        ),
                    )
        except sqlite3.IntegrityError as error:
            raise IntradayV3RegistryError(
                "V3 datasets are already bound or inconsistent"
            ) from error
        return specs

    def get_campaign_plan(self, campaign_id: str) -> Mapping[str, object]:
        """Return only the canonical immutable plan stored during verified materialization."""

        if campaign_id != V3_CAMPAIGN_ID:
            raise KeyError(f"V3 campaign not found: {campaign_id}")
        return self._stored_plan().payload

    def _stored_plan(self) -> IntradayV3CampaignPlan:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT plan_json, plan_fingerprint FROM intraday_v3_plans WHERE campaign_id = ?",
                (V3_CAMPAIGN_ID,),
            ).fetchone()
        if row is None:
            raise IntradayV3RegistryError("V3 plan is not materialized")
        try:
            plan = parse_intraday_v3_campaign_plan(json.loads(row[0]))
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise IntradayV3RegistryError("stored V3 plan is invalid") from error
        if plan.plan_fingerprint != row[1]:
            raise IntradayV3RegistryError("stored V3 plan fingerprint differs")
        return plan

    def _source_commit(self, campaign_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT seal_json FROM intraday_v3_seals WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()
        if row is None:
            raise IntradayV3RegistryError("V3 publication seal is absent")
        value = _stored_seal(json.loads(row[0]))
        source_commit = value["verification"].get("source_commit")
        if not isinstance(source_commit, str):
            raise IntradayV3RegistryError("V3 publication seal source commit is invalid")
        return source_commit

    def record_source_review(
        self,
        review_id: str,
        wheel: Path,
        build_manifest: Path,
        whole_package_manifest: Path,
        lockfile: Path,
        dependency_wheelhouse: Path,
        expected_assessment_fingerprint: str,
        reviewer: str,
        reason: str,
    ) -> dict[str, object]:
        plan = self._stored_plan()
        self._check_plan(plan)
        if (
            not review_id.strip()
            or not expected_assessment_fingerprint.strip()
            or not reviewer.strip()
            or not reason.strip()
        ):
            raise ValueError("review ID, expected assessment, reviewer, and reason are required")
        assessment = self.bind_source_preassessment(
            assess_intraday_v3_source_preassessment(
                wheel,
                build_manifest,
                whole_package_manifest,
                lockfile,
                dependency_wheelhouse,
            )
        )
        if assessment.assessment_fingerprint != expected_assessment_fingerprint:
            raise IntradayV3RegistryError(
                "V3 source differs from the explicitly reviewed assessment"
            )
        campaign_id = _field(plan, "campaign_id")
        with self._connect() as connection:
            pending = connection.execute(
                "SELECT COUNT(*) FROM intraday_v3_lifecycle WHERE status = 'pending'"
            ).fetchone()
            bound = connection.execute(
                "SELECT (SELECT COUNT(*) FROM intraday_v3_datasets), "
                "(SELECT COUNT(*) FROM intraday_v3_specs)"
            ).fetchone()
            if pending is None or pending[0] != 60 or bound != (4, 60):
                raise IntradayV3RegistryError("V3 source review requires all 60 candidates pending")
            seal = connection.execute(
                "SELECT seal_json FROM intraday_v3_seals WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()
            if seal is None:
                raise IntradayV3RegistryError("V3 publication seal is absent")
            source_commit = assessment.build_identity.source_commit
            seal_value = _stored_seal(json.loads(seal[0]))
            verification = seal_value["verification"]
            if (
                source_commit != verification["source_commit"]
                or assessment.campaign_id != campaign_id
                or assessment.plan_fingerprint != plan.plan_fingerprint
                or assessment.publication_fingerprint != fingerprint(seal_value)
            ):
                raise IntradayV3RegistryError(
                    "V3 source assessment is not for the sealed source commit"
                )
            unsigned = {
                "schema_version": "intraday-v3-execution-source-review-v1",
                "review_id": review_id,
                "campaign_id": campaign_id,
                "plan_fingerprint": _field(plan, "plan_fingerprint"),
                "assessment": _json_value(assessment),
                "assessment_fingerprint": _field(assessment, "assessment_fingerprint"),
                "reviewer": reviewer,
                "reason": reason,
            }
            review = {**unsigned, "review_fingerprint": fingerprint(unsigned)}
            try:
                connection.execute(
                    "INSERT INTO intraday_v3_source_reviews VALUES (?, ?, ?, ?)",
                    (review_id, campaign_id, canonical_json(review), review["review_fingerprint"]),
                )
            except sqlite3.IntegrityError as error:
                raise IntradayV3RegistryError("V3 source review already exists") from error
        return review

    def bind_source_preassessment(
        self, preassessment: IntradayV3SourcePreassessment
    ) -> IntradayV3SourceAssessment:
        """Bind a fresh artifact check to the immutable stored plan and publication seal."""

        if not isinstance(preassessment, IntradayV3SourcePreassessment):
            raise IntradayV3RegistryError("V3 source preassessment type differs")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT plan.plan_fingerprint, seal.seal_json "
                "FROM intraday_v3_plans AS plan JOIN intraday_v3_seals AS seal "
                "USING(campaign_id) WHERE plan.campaign_id = ?",
                (V3_CAMPAIGN_ID,),
            ).fetchone()
        if row is None:
            raise IntradayV3RegistryError("V3 plan and publication seal are absent")
        seal = _stored_seal(json.loads(row[1]))
        return bind_intraday_v3_source_assessment(
            preassessment,
            plan_fingerprint=str(row[0]),
            publication_fingerprint=fingerprint(seal),
        )

    def claim(self, experiment_id: str, assessment: IntradayV3SourceAssessment) -> IntradayV3Claim:
        if not isinstance(assessment, IntradayV3SourceAssessment):
            raise IntradayV3RegistryError("V3 claim requires campaign-bound source assessment")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            spec = connection.execute(
                "SELECT spec_json FROM intraday_v3_specs WHERE experiment_id = ?", (experiment_id,)
            ).fetchone()
            review = connection.execute(
                "SELECT review_id, review_json FROM intraday_v3_source_reviews "
                "WHERE campaign_id = ?",
                (V3_CAMPAIGN_ID,),
            ).fetchone()
            if spec is None or review is None:
                raise IntradayV3RegistryError("V3 bound spec or source review is absent")
            try:
                claimed_spec = parse_intraday_v3_experiment(json.loads(spec[0]))
            except (TypeError, ValueError) as error:
                raise IntradayV3RegistryError("stored V3 bound spec is invalid") from error
            review_value = json.loads(review[1])
            if (
                not isinstance(review_value, Mapping)
                or canonicalize(review_value.get("assessment")) != canonicalize(assessment)
                or review_value.get("assessment_fingerprint") != assessment.assessment_fingerprint
            ):
                raise IntradayV3RegistryError("V3 current source differs from its review")
            state = connection.execute(
                "SELECT status FROM intraday_v3_lifecycle WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
            if state is None or state[0] != _PENDING:
                raise IntradayV3RegistryError("V3 candidate is not pending; retries are forbidden")
            review_id = str(review[0])
            unsigned = {
                "schema_version": "intraday-v3-execution-source-binding-v1",
                "experiment_id": experiment_id,
                "review_id": review_id,
                "review_fingerprint": review_value["review_fingerprint"],
                "assessment_fingerprint": assessment.assessment_fingerprint,
                "execution_commit": assessment.build_identity.source_commit,
                "build_identity_fingerprint": (
                    assessment.preassessment.build_identity.identity_fingerprint
                ),
                "environment_identity_fingerprint": (
                    assessment.preassessment.environment_identity.identity_fingerprint
                ),
                "surface_identity_fingerprint": (
                    assessment.preassessment.surface_identity.identity_fingerprint
                ),
            }
            binding = {**unsigned, "binding_fingerprint": fingerprint(unsigned)}
            try:
                claimed_at = _utc_text(datetime.now(UTC))
                claim_token = secrets.token_hex(32)
                connection.execute(
                    "INSERT INTO intraday_v3_execution_sources VALUES (?, ?, ?, ?)",
                    (
                        experiment_id,
                        review_id,
                        canonical_json(binding),
                        binding["binding_fingerprint"],
                    ),
                )
                cursor = connection.execute(
                    "UPDATE intraday_v3_lifecycle SET status = ?, claim_token = ?, "
                    "started_at = ?, heartbeat_at = ? "
                    "WHERE experiment_id = ? AND status = ?",
                    (
                        _RUNNING,
                        claim_token,
                        claimed_at,
                        claimed_at,
                        experiment_id,
                        _PENDING,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise IntradayV3RegistryError(
                    "V3 candidate source binding already exists"
                ) from error
            if cursor.rowcount != 1:
                raise IntradayV3RegistryError("V3 candidate is not pending")
        return IntradayV3Claim(claimed_spec, claim_token)

    def heartbeat(self, experiment_id: str, claim_token: str) -> None:
        _claim_token(claim_token)
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE intraday_v3_lifecycle SET heartbeat_at = ? "
                "WHERE experiment_id = ? AND status = ? AND claim_token = ?",
                (_utc_text(datetime.now(UTC)), experiment_id, _RUNNING, claim_token),
            )
        if cursor.rowcount != 1:
            raise IntradayV3RegistryError("running V3 candidate not found")

    def recover_stale(self, max_age: timedelta) -> list[str]:
        if max_age <= timedelta(0):
            raise ValueError("max_age must be positive")
        now = datetime.now(UTC)
        cutoff = _utc_text(now - max_age)
        recovered: list[str] = []
        completed_conflicts: list[str] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            completed = connection.execute(
                "SELECT p.experiment_id FROM intraday_v3_publications p "
                "JOIN intraday_v3_lifecycle l USING(experiment_id) "
                "WHERE l.status = ? ORDER BY p.experiment_id",
                (_COMPLETE,),
            ).fetchall()
            for (experiment_id,) in completed:
                publication, _ = self._load_publication(connection, str(experiment_id))
                try:
                    recreated = _ensure_published_report(publication)
                except _PublicationConflictError as error:
                    self._record_publication_integrity_conflict(
                        connection, str(experiment_id), publication, error, now
                    )
                    completed_conflicts.append(str(experiment_id))
                    continue
                if recreated:
                    recovered.append(str(experiment_id))
                self._finish_publication(connection, str(experiment_id), publication, None, None)
            rows = connection.execute(
                "SELECT experiment_id, claim_token FROM intraday_v3_lifecycle "
                "WHERE status = ? AND (heartbeat_at IS NULL OR heartbeat_at < ?) "
                "ORDER BY experiment_id",
                (_RUNNING, cutoff),
            ).fetchall()
            for experiment_id, claim_token in rows:
                publication_row = connection.execute(
                    "SELECT 1 FROM intraday_v3_publications WHERE experiment_id = ?",
                    (experiment_id,),
                ).fetchone()
                if publication_row is not None:
                    publication, owner_token = self._load_publication(
                        connection, str(experiment_id)
                    )
                    if claim_token != owner_token:
                        raise IntradayV3RegistryError("V3 publication owner differs from its lease")
                    recovery_token = secrets.token_hex(32)
                    owner_cursor = connection.execute(
                        "UPDATE intraday_v3_publications SET owner_token = ? "
                        "WHERE experiment_id = ? AND owner_token = ?",
                        (recovery_token, experiment_id, owner_token),
                    )
                    lease_cursor = connection.execute(
                        "UPDATE intraday_v3_lifecycle SET claim_token = ?, heartbeat_at = ? "
                        "WHERE experiment_id = ? AND status = ? AND claim_token = ? "
                        "AND (heartbeat_at IS NULL OR heartbeat_at < ?)",
                        (
                            recovery_token,
                            _utc_text(now),
                            experiment_id,
                            _RUNNING,
                            owner_token,
                            cutoff,
                        ),
                    )
                    if owner_cursor.rowcount != 1 or lease_cursor.rowcount != 1:
                        raise IntradayV3RegistryError("stale V3 publication ownership changed")
                    try:
                        _ensure_published_report(publication)
                    except _PublicationConflictError:
                        self._fail_publication_conflict(
                            connection,
                            str(experiment_id),
                            recovery_token,
                        )
                    else:
                        self._finish_publication(
                            connection,
                            str(experiment_id),
                            publication,
                            recovery_token,
                            None,
                        )
                    recovered.append(str(experiment_id))
                    continue
                reason = "stale-run-recovered"
                cursor = connection.execute(
                    "UPDATE intraday_v3_lifecycle SET status = ?, failure_info = ?, "
                    "claim_token = NULL, finished_at = ?, heartbeat_at = NULL "
                    "WHERE experiment_id = ? AND status = ? "
                    "AND (heartbeat_at IS NULL OR heartbeat_at < ?)",
                    (_FAILED, reason, _utc_text(now), experiment_id, _RUNNING, cutoff),
                )
                if cursor.rowcount != 1:
                    continue
                evidence = _result_evidence(experiment_id, reason, {}, (), ())
                connection.execute(
                    "INSERT INTO intraday_v3_results VALUES (?, ?, ?)",
                    (experiment_id, canonical_json(evidence), fingerprint(evidence)),
                )
                recovered.append(str(experiment_id))
        if completed_conflicts:
            raise IntradayV3RegistryError(
                "completed V3 report conflicts with its durable publication journal: "
                + ", ".join(completed_conflicts)
            )
        return sorted(set(recovered))

    def verify_current_source(
        self, experiment_id: str, claim_token: str, assessment: IntradayV3SourceAssessment
    ) -> None:
        _claim_token(claim_token)
        if not isinstance(assessment, IntradayV3SourceAssessment):
            raise IntradayV3RegistryError("V3 source verification requires bound assessment")
        with self._connect() as connection:
            owner = connection.execute(
                "SELECT 1 FROM intraday_v3_lifecycle "
                "WHERE experiment_id = ? AND status = ? AND claim_token = ?",
                (experiment_id, _RUNNING, claim_token),
            ).fetchone()
        if owner is None:
            raise IntradayV3RegistryError("V3 claim lease is no longer active")
        evidence = self.get(experiment_id)["execution_source_provenance"]
        if not isinstance(evidence, Mapping):
            raise IntradayV3RegistryError("V3 execution source evidence is absent")
        review = evidence.get("review")
        binding = evidence.get("binding")
        if (
            not isinstance(review, Mapping)
            or not isinstance(binding, Mapping)
            or canonicalize(review.get("assessment")) != canonicalize(assessment)
            or review.get("assessment_fingerprint") != assessment.assessment_fingerprint
            or binding.get("assessment_fingerprint") != assessment.assessment_fingerprint
        ):
            raise IntradayV3RegistryError("V3 current source differs from its binding")

    def publish_report(
        self,
        experiment_id: str,
        claim_token: str,
        report_path: Path,
        report: Mapping[str, object],
    ) -> None:
        """Journal the report before publishing it, then commit terminal evidence."""

        _claim_token(claim_token)
        realistic = report.get("realistic")
        metrics = realistic.get("metrics") if isinstance(realistic, Mapping) else None
        report_fingerprint = report.get("report_fingerprint")
        unsigned = dict(report)
        unsigned.pop("report_fingerprint", None)
        if (
            not isinstance(metrics, Mapping)
            or not isinstance(report_fingerprint, str)
            or fingerprint(unsigned) != report_fingerprint
        ):
            raise IntradayV3RegistryError("V3 report completion evidence is malformed")
        evidence = _result_evidence(
            experiment_id, None, metrics, (str(report_path),), (report_fingerprint,)
        )
        publication: dict[str, object]
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT s.spec_json FROM intraday_v3_lifecycle l "
                    "JOIN intraday_v3_specs s USING(experiment_id) "
                    "WHERE experiment_id = ? AND status = ? AND claim_token = ?",
                    (experiment_id, _RUNNING, claim_token),
                ).fetchone()
                if row is None:
                    raise IntradayV3RegistryError("V3 claim lease is no longer active")
                spec = parse_intraday_v3_experiment(json.loads(row[0]))
                expected_path = (
                    self.path.parent / "reports" / f"{spec.configuration_fingerprint}.json"
                )
                if report_path != expected_path:
                    raise IntradayV3RegistryError("V3 report path differs from the stored spec")
                unsigned_publication = {
                    "schema_version": "intraday-v3-report-publication-v1",
                    "experiment_id": experiment_id,
                    "claim_token_fingerprint": fingerprint({"claim_token": claim_token}),
                    "report_path": str(report_path),
                    "report": canonicalize(report),
                    "result": canonicalize(evidence),
                }
                publication = {
                    **unsigned_publication,
                    "publication_fingerprint": fingerprint(unsigned_publication),
                }
                publication = _validate_publication(
                    publication,
                    str(publication["publication_fingerprint"]),
                    self.path,
                    spec,
                )
                connection.execute(
                    "INSERT INTO intraday_v3_publications VALUES (?, ?, ?, ?)",
                    (
                        experiment_id,
                        canonical_json(publication),
                        publication["publication_fingerprint"],
                        claim_token,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise IntradayV3RegistryError("V3 report publication is already journaled") from error

        try:
            _ensure_published_report(publication)
        except _PublicationConflictError as error:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                stored, owner_token = self._load_publication(connection, experiment_id)
                if canonicalize(stored) != canonicalize(publication):
                    raise IntradayV3RegistryError(
                        "V3 report publication journal differs"
                    ) from error
                self._fail_publication_conflict(connection, experiment_id, owner_token, claim_token)
            raise IntradayV3RegistryError("V3 report publication path conflicts") from error
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            stored, owner_token = self._load_publication(connection, experiment_id)
            if canonicalize(stored) != canonicalize(publication):
                raise IntradayV3RegistryError("V3 report publication journal differs")
            self._finish_publication(connection, experiment_id, stored, owner_token, claim_token)

    def _load_publication(
        self, connection: sqlite3.Connection, experiment_id: str
    ) -> tuple[dict[str, object], str]:
        row = connection.execute(
            "SELECT p.publication_json, p.publication_fingerprint, p.owner_token, s.spec_json "
            "FROM intraday_v3_publications p JOIN intraday_v3_specs s USING(experiment_id) "
            "WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchone()
        if row is None:
            raise IntradayV3RegistryError("V3 report publication journal is absent")
        try:
            publication = json.loads(row[0])
            spec = parse_intraday_v3_experiment(json.loads(row[3]))
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise IntradayV3RegistryError("stored V3 report publication is invalid") from error
        owner_token = row[2]
        if not isinstance(owner_token, str):
            raise IntradayV3RegistryError("stored V3 publication owner is invalid")
        _claim_token(owner_token)
        return _validate_publication(publication, str(row[1]), self.path, spec), owner_token

    def _finish_publication(
        self,
        connection: sqlite3.Connection,
        experiment_id: str,
        publication: Mapping[str, object],
        owner_token: str | None,
        claim_token: str | None,
    ) -> None:
        row = connection.execute(
            "SELECT l.status, l.claim_token, z.result_json "
            "FROM intraday_v3_lifecycle l LEFT JOIN intraday_v3_results z USING(experiment_id) "
            "WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchone()
        if row is None:
            raise IntradayV3RegistryError("V3 candidate lifecycle is absent")
        expected_result = publication["result"]
        if row[0] == _COMPLETE:
            if row[2] is None or canonicalize(json.loads(row[2])) != canonicalize(expected_result):
                raise IntradayV3RegistryError("completed V3 result differs from publication")
            return
        stored_token = row[1]
        if (
            row[0] != _RUNNING
            or not isinstance(stored_token, str)
            or owner_token is None
            or stored_token != owner_token
            or (claim_token is not None and claim_token != stored_token)
            or (
                claim_token is not None
                and fingerprint({"claim_token": claim_token})
                != publication["claim_token_fingerprint"]
            )
        ):
            raise IntradayV3RegistryError("V3 report publication claim is no longer active")
        cursor = connection.execute(
            "UPDATE intraday_v3_lifecycle SET status = ?, failure_info = NULL, "
            "claim_token = NULL, finished_at = ?, heartbeat_at = NULL "
            "WHERE experiment_id = ? AND status = ? AND claim_token = ?",
            (_COMPLETE, _utc_text(datetime.now(UTC)), experiment_id, _RUNNING, stored_token),
        )
        if cursor.rowcount != 1:
            raise IntradayV3RegistryError("V3 report publication claim is no longer active")
        connection.execute(
            "INSERT INTO intraday_v3_results VALUES (?, ?, ?)",
            (experiment_id, canonical_json(expected_result), fingerprint(expected_result)),
        )

    def _fail_publication_conflict(
        self,
        connection: sqlite3.Connection,
        experiment_id: str,
        owner_token: str,
        claim_token: str | None = None,
    ) -> None:
        if claim_token is not None and claim_token != owner_token:
            raise IntradayV3RegistryError("V3 publication conflict owner differs")
        cursor = connection.execute(
            "UPDATE intraday_v3_lifecycle SET status = ?, failure_info = ?, "
            "claim_token = NULL, finished_at = ?, heartbeat_at = NULL "
            "WHERE experiment_id = ? AND status = ? AND claim_token = ?",
            (
                _FAILED,
                "report-publication-conflict",
                _utc_text(datetime.now(UTC)),
                experiment_id,
                _RUNNING,
                owner_token,
            ),
        )
        if cursor.rowcount != 1:
            raise IntradayV3RegistryError("V3 publication conflict owner is no longer active")
        evidence = _result_evidence(
            experiment_id,
            "report-publication-conflict",
            {},
            (),
            (),
        )
        connection.execute(
            "INSERT INTO intraday_v3_results VALUES (?, ?, ?)",
            (experiment_id, canonical_json(evidence), fingerprint(evidence)),
        )

    def _record_publication_integrity_conflict(
        self,
        connection: sqlite3.Connection,
        experiment_id: str,
        publication: Mapping[str, object],
        error: _PublicationConflictError,
        observed_at: datetime,
    ) -> None:
        stored = connection.execute(
            "SELECT conflict_json FROM intraday_v3_publication_conflicts WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchone()
        if stored is not None:
            return
        report = publication.get("report")
        if not isinstance(report, Mapping):
            raise IntradayV3RegistryError("V3 publication report is invalid")
        unsigned = {
            "schema_version": "intraday-v3-publication-integrity-conflict-v1",
            "experiment_id": experiment_id,
            "publication_fingerprint": publication["publication_fingerprint"],
            "report_fingerprint": report.get("report_fingerprint"),
            "expected_report_sha256": hashlib.sha256(
                (canonical_json(report) + "\n").encode("utf-8")
            ).hexdigest(),
            "reason": str(error),
            "observed_kind": error.observed_kind,
            "observed_sha256": error.observed_sha256,
            "observed_size": error.observed_size,
            "observed_at": _utc_text(observed_at),
        }
        conflict = {**unsigned, "conflict_fingerprint": fingerprint(unsigned)}
        connection.execute(
            "INSERT INTO intraday_v3_publication_conflicts VALUES (?, ?, ?)",
            (
                experiment_id,
                canonical_json(conflict),
                conflict["conflict_fingerprint"],
            ),
        )

    def fail(self, experiment_id: str, claim_token: str, reason: str) -> bool:
        _claim_token(claim_token)
        if not reason.strip():
            raise ValueError("failure reason is required")
        evidence = _result_evidence(experiment_id, reason, {}, (), ())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            publication = connection.execute(
                "SELECT 1 FROM intraday_v3_publications WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
            if publication is not None:
                return False
            cursor = connection.execute(
                "UPDATE intraday_v3_lifecycle SET status = ?, failure_info = ?, "
                "claim_token = NULL, finished_at = ?, heartbeat_at = NULL "
                "WHERE experiment_id = ? AND status = ? AND claim_token = ?",
                (
                    _FAILED,
                    reason,
                    _utc_text(datetime.now(UTC)),
                    experiment_id,
                    _RUNNING,
                    claim_token,
                ),
            )
            if cursor.rowcount != 1:
                return False
            connection.execute(
                "INSERT INTO intraday_v3_results VALUES (?, ?, ?)",
                (experiment_id, canonical_json(evidence), fingerprint(evidence)),
            )
        return True

    def get(self, experiment_id: str) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT r.reservation_json, l.status, l.failure_info, s.spec_json, "
                "x.binding_json, review.review_json, z.result_json, "
                "l.started_at, l.heartbeat_at, l.finished_at, c.conflict_json "
                "FROM intraday_v3_reservations r "
                "JOIN intraday_v3_lifecycle l USING(experiment_id) "
                "LEFT JOIN intraday_v3_specs s USING(experiment_id) "
                "LEFT JOIN intraday_v3_execution_sources x USING(experiment_id) "
                "LEFT JOIN intraday_v3_source_reviews review USING(review_id) "
                "LEFT JOIN intraday_v3_results z USING(experiment_id) "
                "LEFT JOIN intraday_v3_publication_conflicts c USING(experiment_id) "
                "WHERE r.experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"V3 candidate not found: {experiment_id}")
        reservation = json.loads(row[0])
        result = json.loads(row[6]) if row[6] else {}
        return {
            "experiment_id": experiment_id,
            "campaign_id": V3_CAMPAIGN_ID,
            "spec_json": json.loads(row[3]) if row[3] else reservation,
            "status": row[1],
            "failure_info": row[2],
            "started_at": row[7],
            "heartbeat_at": row[8],
            "finished_at": row[9],
            "metrics_json": result.get("metrics"),
            "artifact_locations_json": result.get("artifact_locations"),
            "artifact_hashes_json": result.get("artifact_hashes"),
            "execution_provenance": "controlled-run" if row[1] == _COMPLETE else None,
            "publication_integrity_conflict": json.loads(row[10]) if row[10] else None,
            "execution_source_provenance": (
                {"review": json.loads(row[5]), "binding": json.loads(row[4])}
                if row[4] is not None and row[5] is not None
                else None
            ),
        }

    def list(self, campaign_id: str) -> list[dict[str, object]]:
        if campaign_id != V3_CAMPAIGN_ID:
            return []
        with self._connect() as connection:
            ids = [
                row[0]
                for row in connection.execute(
                    "SELECT experiment_id FROM intraday_v3_reservations ORDER BY candidate_ordinal"
                )
            ]
        return [self.get(experiment_id) for experiment_id in ids]

    def verify_intraday_execution_source_evidence(
        self, experiment_id: str, evidence: object
    ) -> None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT review_json, binding_json
                FROM intraday_v3_execution_sources AS binding
                JOIN intraday_v3_source_reviews AS review USING(review_id)
                WHERE binding.experiment_id = ?
                """,
                (experiment_id,),
            ).fetchone()
        if row is None:
            raise IntradayV3RegistryError("V3 execution source evidence is absent")
        stored = {"review": json.loads(row[0]), "binding": json.loads(row[1])}
        if canonicalize(stored) != canonicalize(evidence):
            raise IntradayV3RegistryError("V3 execution source evidence differs")

    @staticmethod
    def _check_plan(plan: object) -> None:
        if not isinstance(plan, IntradayV3CampaignPlan):
            raise IntradayV3RegistryError("V3 plan must use the canonical parser")
        if (
            plan.campaign_id != V3_CAMPAIGN_ID
            or plan.search_budget != 60
            or len(plan.candidates) != 60
        ):
            raise IntradayV3RegistryError("V3 plan identity or reservation count differs")

    @staticmethod
    def _check_seal(plan: IntradayV3CampaignPlan, seal: object) -> None:
        if not isinstance(seal, IntradayV3PublicationSeal):
            raise IntradayV3RegistryError("V3 publication seal must be verified")
        prospective = _field(_field(plan, "payload"), "prospective_freshness")
        qualification = _field(_field(plan, "payload"), "qualification_binding")
        if (
            _field(seal, "inventory_fingerprint") != _field(prospective, "inventory_fingerprint")
            or _field(seal, "selection_fingerprint")
            != _field(prospective, "period_selection_fingerprint")
            or _field(seal, "plan_fingerprint") != _field(plan, "plan_fingerprint")
            or _field(seal, "qualification_binding_fingerprint")
            != _field(qualification, "fingerprint")
            or _field(seal, "first_validation_bar") != _first_validation_bar(plan)
            or _field(seal, "witnessed_at") >= _field(seal, "first_validation_bar")
        ):
            raise IntradayV3RegistryError(
                "V3 publication seal does not exactly precede the first validation bar"
            )


def _field(value: object, name: str) -> Any:
    if isinstance(value, Mapping):
        if name in value:
            return value[name]
    elif hasattr(value, name):
        return getattr(value, name)
    raise IntradayV3RegistryError(f"required V3 field is absent: {name}")


def _json_value(value: object) -> Any:
    return canonicalize(value)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _claim_token(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise IntradayV3RegistryError("V3 claim token is invalid")


def _validate_publication(
    value: object,
    stored_fingerprint: str,
    registry_path: Path,
    spec: IntradayV3ExperimentSpec,
) -> dict[str, object]:
    fields = {
        "schema_version",
        "experiment_id",
        "claim_token_fingerprint",
        "report_path",
        "report",
        "result",
        "publication_fingerprint",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise IntradayV3RegistryError("stored V3 report publication fields differ")
    unsigned = dict(value)
    publication_fingerprint = unsigned.pop("publication_fingerprint")
    report = value["report"]
    result = value["result"]
    report_path = value["report_path"]
    claim_fingerprint = value["claim_token_fingerprint"]
    expected_path = registry_path.parent / "reports" / f"{spec.configuration_fingerprint}.json"
    if (
        value["schema_version"] != "intraday-v3-report-publication-v1"
        or value["experiment_id"] != spec.experiment_id
        or not isinstance(claim_fingerprint, str)
        or len(claim_fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in claim_fingerprint)
        or report_path != str(expected_path)
        or not isinstance(report, Mapping)
        or not isinstance(result, Mapping)
        or not isinstance(publication_fingerprint, str)
        or publication_fingerprint != stored_fingerprint
        or fingerprint(unsigned) != publication_fingerprint
    ):
        raise IntradayV3RegistryError("stored V3 report publication is invalid")
    report_unsigned = dict(report)
    report_fingerprint = report_unsigned.pop("report_fingerprint", None)
    provenance = report.get("provenance")
    realistic = report.get("realistic")
    metrics = realistic.get("metrics") if isinstance(realistic, Mapping) else None
    if (
        not isinstance(report_fingerprint, str)
        or fingerprint(report_unsigned) != report_fingerprint
        or not isinstance(provenance, Mapping)
        or provenance.get("experiment_id") != spec.experiment_id
        or not isinstance(metrics, Mapping)
    ):
        raise IntradayV3RegistryError("stored V3 publication report is invalid")
    expected_result = _result_evidence(
        spec.experiment_id,
        None,
        metrics,
        (str(expected_path),),
        (report_fingerprint,),
    )
    if canonicalize(result) != canonicalize(expected_result):
        raise IntradayV3RegistryError("stored V3 publication result differs from its report")
    return value


def _ensure_published_report(publication: Mapping[str, object]) -> bool:
    report_path = Path(str(publication["report_path"]))
    report = publication["report"]
    if not isinstance(report, Mapping):
        raise IntradayV3RegistryError("V3 publication report is invalid")
    expected = (canonical_json(report) + "\n").encode("utf-8")
    parent = report_path.parent
    if parent.is_symlink():
        raise _PublicationConflictError("V3 report directory conflicts", "symlink-directory")
    if parent.exists() and not parent.is_dir():
        raise _PublicationConflictError("V3 report directory conflicts", "non-directory")
    parent_was_missing = not parent.exists()
    parent.mkdir(parents=True, exist_ok=True)
    if parent.is_symlink():
        raise _PublicationConflictError("V3 report directory conflicts", "symlink-directory")
    if not parent.is_dir():
        raise _PublicationConflictError("V3 report directory conflicts", "non-directory")
    if parent_was_missing:
        _fsync_directory(parent.parent)
    if report_path.is_symlink():
        raise _PublicationConflictError("V3 report path is a symlink", "symlink")
    if report_path.exists():
        if not report_path.is_file() or report_path.read_bytes() != expected:
            raise _path_conflict(report_path, "V3 report path contains different evidence")
        _fsync_directory(parent)
        return False
    try:
        write_intraday_execution_report(report_path, report)
    except Exception as error:
        if (
            not report_path.is_symlink()
            and report_path.is_file()
            and report_path.read_bytes() == expected
        ):
            _fsync_directory(parent)
            return True
        if report_path.is_symlink() or report_path.exists():
            raise _path_conflict(
                report_path, "V3 report path contains different evidence"
            ) from error
        raise
    if report_path.is_symlink() or not report_path.is_file():
        raise _path_conflict(report_path, "V3 report publication did not create a regular file")
    observed = report_path.read_bytes()
    if observed != expected:
        raise _PublicationConflictError(
            "V3 report publication bytes differ",
            "regular-file",
            hashlib.sha256(observed).hexdigest(),
            len(observed),
        )
    _fsync_directory(parent)
    return True


def _path_conflict(path: Path, reason: str) -> _PublicationConflictError:
    if path.is_symlink():
        return _PublicationConflictError(reason, "symlink")
    if not path.exists():
        return _PublicationConflictError(reason, "missing")
    if not path.is_file():
        return _PublicationConflictError(reason, "non-regular")
    try:
        observed = path.read_bytes()
    except OSError:
        return _PublicationConflictError(reason, "unreadable-regular-file")
    return _PublicationConflictError(
        reason,
        "regular-file",
        hashlib.sha256(observed).hexdigest(),
        len(observed),
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _stored_seal(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"artifact_json", "verification"}:
        raise IntradayV3RegistryError("stored V3 publication seal is invalid")
    artifact_json = value["artifact_json"]
    verification = value["verification"]
    if not isinstance(artifact_json, str) or not isinstance(verification, Mapping):
        raise IntradayV3RegistryError("stored V3 publication seal is invalid")
    try:
        artifact = json.loads(artifact_json)
    except json.JSONDecodeError as error:
        raise IntradayV3RegistryError("stored V3 publication seal is invalid") from error
    if (
        not isinstance(artifact, Mapping)
        or hashlib.sha256(artifact_json.encode("utf-8")).hexdigest()
        != verification.get("seal_sha256")
        or artifact.get("source_commit") != verification.get("source_commit")
        or artifact.get("seal_fingerprint") != verification.get("seal_fingerprint")
    ):
        raise IntradayV3RegistryError("stored V3 publication seal differs from its verification")
    return {"artifact_json": artifact_json, "verification": verification}


def _result_evidence(
    experiment_id: str,
    reason: str | None,
    metrics: Mapping[str, object],
    locations: Sequence[str],
    hashes: Sequence[str],
) -> dict[str, object]:
    return {
        "schema_version": "intraday-v3-result-v1",
        "experiment_id": experiment_id,
        "metrics": dict(metrics),
        "artifact_locations": list(locations),
        "artifact_hashes": list(hashes),
        "failure_info": reason,
    }


def _first_validation_bar(plan: object) -> Any:
    values = [
        _field(period, "start_timestamp")
        for period in _field(plan, "periods")
        if _field(period, "role") == "validation-a"
    ]
    if len(values) != 1:
        raise IntradayV3RegistryError("V3 first validation period is absent")
    return values[0]


def _manifest_identity(manifest: Mapping[str, object]) -> Mapping[str, object]:
    identity = manifest.get("identity")
    if not isinstance(identity, Mapping):
        raise IntradayV3RegistryError("V3 dataset manifest identity is invalid")
    return identity
