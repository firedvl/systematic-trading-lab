"""Durable experiment campaigns, lifecycle state, and holdout protection."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from .fingerprints import canonical_json, canonicalize, fingerprint

if TYPE_CHECKING:
    from .campaign_specs import IntradayCandidateReservation, IntradayResearchCampaignPlan


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


@dataclass(frozen=True)
class IntradayExperimentSpec:
    """Versioned provenance contract for one offline intraday candidate."""

    experiment_id: str
    campaign_id: str
    search_budget: int
    candidate_ordinal: int
    strategy_id: str
    strategy_version: str
    strategy_family: str
    code_commit: str
    dataset_id: str
    dataset_fingerprint: str
    universe_id: str
    universe_fingerprint: str
    parameters: Mapping[str, object]
    timeframe: str
    session_policy_version: str
    bar_timestamp_semantics_version: str
    session_return_policy_version: str
    benchmark_policy_version: str
    cost_model_version: str
    slippage_bps: Decimal
    commission_bps: Decimal
    execution_model_version: str
    earliest_fill_semantics: str
    execution_delay_bars: int
    split: ExperimentSplit
    start_timestamp: datetime
    end_timestamp: datetime
    random_seed: int | None
    creation_reason: str
    parent_candidate: str | None = None
    schema_version: str = "intraday-experiment-v1"

    def __post_init__(self) -> None:
        identifiers = (
            self.experiment_id,
            self.campaign_id,
            self.strategy_id,
            self.strategy_version,
            self.strategy_family,
            self.code_commit,
            self.dataset_id,
            self.dataset_fingerprint,
            self.universe_id,
            self.universe_fingerprint,
        )
        if any(not value for value in identifiers):
            raise ValueError("intraday experiment provenance fields are required")
        if self.schema_version != "intraday-experiment-v1":
            raise ValueError("unsupported intraday experiment schema")
        if self.search_budget < 1 or not 1 <= self.candidate_ordinal <= self.search_budget:
            raise ValueError("candidate ordinal must fit the positive search budget")
        if self.timeframe not in {"1m", "5m"}:
            raise ValueError("intraday experiments require a 1m or 5m timeframe")
        if self.split is ExperimentSplit.HOLDOUT:
            raise ValueError("intraday protected holdout is not authorized")
        if self.execution_delay_bars < 1:
            raise ValueError("intraday execution delay must be at least one bar")
        if self.slippage_bps < 0 or self.commission_bps < 0:
            raise ValueError("intraday cost values must not be negative")
        versions = (
            self.session_policy_version,
            self.bar_timestamp_semantics_version,
            self.session_return_policy_version,
            self.benchmark_policy_version,
            self.cost_model_version,
            self.execution_model_version,
            self.earliest_fill_semantics,
        )
        if any(not value for value in versions):
            raise ValueError("intraday model and policy versions are required")
        if any(
            value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
            for value in (self.start_timestamp, self.end_timestamp)
        ):
            raise ValueError("experiment timestamps must be UTC-aware")
        if self.start_timestamp > self.end_timestamp:
            raise ValueError("experiment start must not follow end")
        if not self.creation_reason:
            raise ValueError("creation reason is required")

    @property
    def configuration_fingerprint(self) -> str:
        """Bind every assumption that can materially change replay results."""

        return fingerprint(self)


ExperimentContract = ExperimentSpec | IntradayExperimentSpec


class ExperimentRegistry:
    _RESERVED_CAMPAIGN_IDS = frozenset({"intraday-research-v1"})

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
                    created_at TEXT NOT NULL,
                    proposal_fingerprint TEXT
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
                CREATE TABLE IF NOT EXISTS intraday_execution_source_reviews (
                    review_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL UNIQUE,
                    review_json TEXT NOT NULL,
                    review_fingerprint TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS intraday_experiment_execution_sources (
                    experiment_id TEXT PRIMARY KEY REFERENCES experiments(experiment_id),
                    review_id TEXT NOT NULL REFERENCES intraday_execution_source_reviews(review_id),
                    binding_json TEXT NOT NULL,
                    binding_fingerprint TEXT NOT NULL UNIQUE
                );
                CREATE TRIGGER IF NOT EXISTS intraday_execution_source_reviews_no_update
                BEFORE UPDATE ON intraday_execution_source_reviews
                BEGIN SELECT RAISE(ABORT, 'intraday execution source reviews are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS intraday_execution_source_reviews_no_delete
                BEFORE DELETE ON intraday_execution_source_reviews
                BEGIN SELECT RAISE(ABORT, 'intraday execution source reviews are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS intraday_execution_source_bindings_no_update
                BEFORE UPDATE ON intraday_experiment_execution_sources
                BEGIN SELECT RAISE(ABORT, 'intraday execution source bindings are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS intraday_execution_source_bindings_no_delete
                BEFORE DELETE ON intraday_experiment_execution_sources
                BEGIN SELECT RAISE(ABORT, 'intraday execution source bindings are immutable'); END;
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
            access_columns = {
                column[1] for column in connection.execute("PRAGMA table_info(holdout_access)")
            }
            if "proposal_fingerprint" not in access_columns:
                connection.execute(
                    "ALTER TABLE holdout_access ADD COLUMN proposal_fingerprint TEXT"
                )
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
        if campaign_id in self._RESERVED_CAMPAIGN_IDS:
            raise ExperimentError(f"campaign ID is reserved for a sealed plan: {campaign_id}")
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

    def get_campaign(self, campaign_id: str) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT campaign_id, name, created_at, status, search_budget "
                "FROM campaigns WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"campaign not found: {campaign_id}")
        return {
            "campaign_id": row[0],
            "name": row[1],
            "created_at": row[2],
            "status": row[3],
            "search_budget": int(row[4]),
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

    def create_planned_intraday_campaign(self, plan: Mapping[str, object]) -> dict[str, object]:
        from .campaign_specs import parse_intraday_research_campaign_plan

        parsed = parse_intraday_research_campaign_plan(plan)
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
                for reservation in parsed.candidates:
                    connection.execute(
                        """
                        INSERT INTO experiments
                        (experiment_id, campaign_id, spec_json, split, status,
                         qualification_state, created_at, campaign_plan_fingerprint)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            reservation.experiment_id,
                            parsed.campaign_id,
                            canonical_json(_planned_intraday_reservation(parsed, reservation)),
                            reservation.split.value,
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
            "reserved_candidates": len(parsed.candidates),
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

    def record_intraday_execution_source_review(
        self,
        review_id: str,
        wheel: Path,
        manifest: Path,
        lockfile: Path,
        dependency_wheelhouse: Path,
        expected_assessment_fingerprint: str,
        reviewer: str,
        reason: str,
    ) -> dict[str, object]:
        """Verify and record one immutable review of Campaign V1's actual build."""

        from .campaign_specs import parse_intraday_research_campaign_plan
        from .intraday_source_provenance import (
            INTRADAY_CAMPAIGN_ID,
            INTRADAY_FOUNDATION_COMMIT,
            INTRADAY_PLAN_FINGERPRINT,
            assess_intraday_execution_source,
        )

        if (
            not review_id.strip()
            or not expected_assessment_fingerprint.strip()
            or not reviewer.strip()
            or not reason.strip()
        ):
            raise ValueError(
                "source review ID, expected assessment fingerprint, reviewer, and reason "
                "are required"
            )
        assessment = assess_intraday_execution_source(
            wheel, manifest, lockfile, dependency_wheelhouse
        )
        if (
            assessment.campaign_id != INTRADAY_CAMPAIGN_ID
            or assessment.plan_fingerprint != INTRADAY_PLAN_FINGERPRINT
            or assessment.surface_comparison.foundation_commit != INTRADAY_FOUNDATION_COMMIT
            or not assessment.surface_comparison.equivalent
        ):
            raise ExperimentError(
                "execution source differs from the reviewed foundation; "
                "a new intraday campaign version is required"
            )
        assessment_json = canonicalize(assessment)
        assert isinstance(assessment_json, dict)
        assessment_fingerprint = assessment.assessment_fingerprint
        if assessment_fingerprint != expected_assessment_fingerprint:
            raise ExperimentError(
                "execution source differs from the explicitly reviewed assessment"
            )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT review_json FROM intraday_execution_source_reviews
                WHERE review_id = ? OR campaign_id = ?
                """,
                (review_id, INTRADAY_CAMPAIGN_ID),
            ).fetchone()
            if existing is not None:
                review = _fingerprinted_record(
                    json.loads(str(existing[0])),
                    _INTRADAY_SOURCE_REVIEW_FIELDS,
                    "review_fingerprint",
                    "intraday execution source review",
                )
                if (
                    review["review_id"] == review_id
                    and canonicalize(review["assessment"]) == assessment_json
                    and review["reviewer"] == reviewer
                    and review["reason"] == reason
                ):
                    return review
                raise ExperimentError("Campaign V1 already has a different execution source review")
            plan_row = connection.execute(
                """
                SELECT plan_json, plan_fingerprint FROM campaign_plans
                WHERE campaign_id = ?
                """,
                (INTRADAY_CAMPAIGN_ID,),
            ).fetchone()
            if plan_row is None:
                raise ExperimentError("Campaign V1 must be sealed before source review")
            plan = parse_intraday_research_campaign_plan(json.loads(str(plan_row[0])))
            if (
                plan_row[1] != INTRADAY_PLAN_FINGERPRINT
                or plan.plan_fingerprint != INTRADAY_PLAN_FINGERPRINT
                or plan.base_code_commit != INTRADAY_FOUNDATION_COMMIT
            ):
                raise ExperimentError("sealed Campaign V1 identity differs")
            statuses = connection.execute(
                "SELECT status FROM experiments WHERE campaign_id = ?",
                (INTRADAY_CAMPAIGN_ID,),
            ).fetchall()
            if len(statuses) != plan.search_budget or any(
                row[0] != ExperimentStatus.PENDING.value for row in statuses
            ):
                raise ExperimentError(
                    "execution source review requires every Campaign V1 candidate to be pending"
                )
            unsigned: dict[str, object] = {
                "schema_version": "intraday-execution-source-review-v1",
                "review_id": review_id,
                "campaign_id": INTRADAY_CAMPAIGN_ID,
                "plan_fingerprint": INTRADAY_PLAN_FINGERPRINT,
                "foundation_commit": INTRADAY_FOUNDATION_COMMIT,
                "execution_commit": assessment.build_identity.source_commit,
                "assessment": assessment_json,
                "assessment_fingerprint": assessment_fingerprint,
                "build_identity_fingerprint": assessment.build_identity.identity_fingerprint,
                "environment_identity_fingerprint": (
                    assessment.environment_identity.identity_fingerprint
                ),
                "surface_comparison_fingerprint": (
                    assessment.surface_comparison.comparison_fingerprint
                ),
                "reviewer": reviewer,
                "reason": reason,
                "reviewed_at": _now(),
            }
            review = {**unsigned, "review_fingerprint": fingerprint(unsigned)}
            connection.execute(
                """
                INSERT INTO intraday_execution_source_reviews
                (review_id, campaign_id, review_json, review_fingerprint)
                VALUES (?, ?, ?, ?)
                """,
                (
                    review_id,
                    INTRADAY_CAMPAIGN_ID,
                    canonical_json(review),
                    review["review_fingerprint"],
                ),
            )
        return review

    def get_intraday_execution_source_review(self, review_id: str) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT campaign_id, review_json, review_fingerprint
                FROM intraday_execution_source_reviews WHERE review_id = ?
                """,
                (review_id,),
            ).fetchone()
        if row is None:
            raise ExperimentError(f"intraday execution source review not found: {review_id}")
        review = _fingerprinted_record(
            json.loads(str(row[1])),
            _INTRADAY_SOURCE_REVIEW_FIELDS,
            "review_fingerprint",
            "intraday execution source review",
        )
        if (
            review["review_id"] != review_id
            or review["campaign_id"] != row[0]
            or review["review_fingerprint"] != row[2]
        ):
            raise ExperimentError("stored intraday execution source review differs")
        return review

    def verify_intraday_execution_source_review(
        self,
        review_id: str,
        wheel: Path,
        manifest: Path,
        lockfile: Path,
        dependency_wheelhouse: Path,
    ) -> None:
        """Reverify the executing build against its immutable review."""

        from .intraday_source_provenance import assess_intraday_execution_source

        assessment = assess_intraday_execution_source(
            wheel, manifest, lockfile, dependency_wheelhouse
        )
        review = self.get_intraday_execution_source_review(review_id)
        if (
            review["assessment_fingerprint"] != assessment.assessment_fingerprint
            or review["execution_commit"] != assessment.build_identity.source_commit
            or review["build_identity_fingerprint"]
            != assessment.build_identity.identity_fingerprint
            or review["environment_identity_fingerprint"]
            != assessment.environment_identity.identity_fingerprint
            or canonicalize(review["assessment"]) != canonicalize(assessment)
        ):
            raise ExperimentError(
                "current execution build differs from its recorded Campaign V1 review; "
                "a new campaign version is required"
            )

    def get_intraday_execution_source_binding(self, experiment_id: str) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT review_id, binding_json, binding_fingerprint
                FROM intraday_experiment_execution_sources WHERE experiment_id = ?
                """,
                (experiment_id,),
            ).fetchone()
        if row is None:
            raise ExperimentError(f"intraday execution source binding not found: {experiment_id}")
        binding = _fingerprinted_record(
            json.loads(str(row[1])),
            _INTRADAY_SOURCE_BINDING_FIELDS,
            "binding_fingerprint",
            "intraday execution source binding",
        )
        if (
            binding["experiment_id"] != experiment_id
            or binding["review_id"] != row[0]
            or binding["binding_fingerprint"] != row[2]
        ):
            raise ExperimentError("stored intraday execution source binding differs")
        return binding

    def intraday_execution_source_evidence(self, experiment_id: str) -> dict[str, object]:
        binding = self.get_intraday_execution_source_binding(experiment_id)
        review_id = binding["review_id"]
        assert isinstance(review_id, str)
        return {
            "review": self.get_intraday_execution_source_review(review_id),
            "binding": binding,
        }

    def verify_intraday_execution_source_evidence(
        self, experiment_id: str, evidence: object
    ) -> None:
        if canonicalize(evidence) != canonicalize(
            self.intraday_execution_source_evidence(experiment_id)
        ):
            raise ExperimentError("intraday report execution source provenance differs")

    def get_planned_spec(self, experiment_id: str) -> ExperimentSpec:
        record = self.get(experiment_id)
        if record.get("campaign_plan_fingerprint") is None:
            raise ExperimentError(f"experiment is not from a sealed plan: {experiment_id}")
        spec = record["spec_json"]
        assert isinstance(spec, Mapping)
        parsed = _experiment_spec(spec)
        if not isinstance(parsed, ExperimentSpec):
            raise ExperimentError("sealed daily plan contains an intraday experiment")
        return parsed

    def bind_planned_intraday_experiments(self, specs: Sequence[IntradayExperimentSpec]) -> None:
        from .campaign_specs import parse_intraday_research_campaign_plan

        campaign_ids = {spec.campaign_id for spec in specs}
        if len(campaign_ids) != 1:
            raise ExperimentError("intraday dataset binding requires one sealed campaign")
        campaign_id = next(iter(campaign_ids))
        stored_plan = self.get_campaign_plan(campaign_id)
        plan_json = stored_plan["plan_json"]
        assert isinstance(plan_json, Mapping)
        plan = parse_intraday_research_campaign_plan(plan_json)
        if stored_plan["plan_fingerprint"] != plan.plan_fingerprint:
            raise ExperimentError("stored intraday campaign plan fingerprint differs")
        expected_ids = {candidate.experiment_id for candidate in plan.candidates}
        specs_by_id = {spec.experiment_id: spec for spec in specs}
        if len(specs) != plan.search_budget or set(specs_by_id) != expected_ids:
            raise ExperimentError("intraday dataset binding must include every sealed reservation")
        for spec in specs:
            _validate_planned_intraday_spec(plan, spec)
        with self._connect() as connection:
            campaign = connection.execute(
                "SELECT status, search_budget FROM campaigns WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            if campaign != ("sealed", plan.search_budget):
                raise ExperimentError("sealed intraday campaign differs from its plan")
            rows = connection.execute(
                """
                SELECT experiment_id, spec_json, status, campaign_plan_fingerprint
                FROM experiments WHERE campaign_id = ?
                """,
                (campaign_id,),
            ).fetchall()
            rows_by_id = {str(row[0]): row for row in rows}
            if set(rows_by_id) != expected_ids:
                raise ExperimentError("stored intraday reservations differ from the sealed plan")
            for reservation in plan.candidates:
                row = rows_by_id[reservation.experiment_id]
                expected_reservation = canonicalize(
                    _planned_intraday_reservation(plan, reservation)
                )
                if (
                    canonicalize(json.loads(str(row[1]))) != expected_reservation
                    or row[2] != ExperimentStatus.PENDING.value
                    or row[3] != plan.plan_fingerprint
                ):
                    raise ExperimentError(
                        "stored intraday reservations differ from the sealed plan"
                    )
            for reservation in plan.candidates:
                spec = specs_by_id[reservation.experiment_id]
                cursor = connection.execute(
                    """
                    UPDATE experiments SET spec_json = ?
                    WHERE experiment_id = ? AND campaign_id = ? AND status = ?
                      AND campaign_plan_fingerprint = ?
                    """,
                    (
                        canonical_json(spec),
                        spec.experiment_id,
                        campaign_id,
                        ExperimentStatus.PENDING.value,
                        plan.plan_fingerprint,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ExperimentError("planned intraday datasets could not be bound")

    def get_planned_intraday_spec(self, experiment_id: str) -> IntradayExperimentSpec:
        record = self.get(experiment_id)
        if record.get("campaign_plan_fingerprint") is None:
            raise ExperimentError(f"experiment is not from a sealed plan: {experiment_id}")
        spec = record["spec_json"]
        assert isinstance(spec, Mapping)
        if spec.get("schema_version") == "intraday-candidate-reservation-v1":
            raise ExperimentError(
                f"planned intraday experiment is not bound to a dataset: {experiment_id}"
            )
        parsed = _experiment_spec(spec)
        if not isinstance(parsed, IntradayExperimentSpec):
            raise ExperimentError("sealed intraday plan contains a daily experiment")
        return parsed

    def _create_holdout_run_authorization(
        self,
        authorization_id: str,
        evidence_report: Mapping[str, object],
        reviewer: str,
        reason: str,
    ) -> None:
        if not authorization_id or not reviewer or not reason:
            raise ValueError("authorization ID, reviewer, and reason are required")
        report = validate_passing_qualification_evidence(evidence_report)
        evidence_fingerprint = report["evidence_fingerprint"]
        assert isinstance(evidence_fingerprint, str)
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
        self, spec: ExperimentContract, holdout_authorization_id: str | None = None
    ) -> None:
        if isinstance(spec, IntradayExperimentSpec) and holdout_authorization_id is not None:
            raise HoldoutAccessError("intraday experiments cannot use holdout authorization")
        if spec.split is not ExperimentSplit.HOLDOUT and holdout_authorization_id is not None:
            raise HoldoutAccessError("holdout authorization cannot be used for another split")
        created_at = _now()
        with self._connect() as connection:
            if spec.split is ExperimentSplit.HOLDOUT:
                if not isinstance(spec, ExperimentSpec):
                    raise HoldoutAccessError("intraday protected holdout is not authorized")
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
            if isinstance(spec, IntradayExperimentSpec):
                if int(campaign[0]) != spec.search_budget:
                    raise ExperimentError("intraday experiment search budget differs from campaign")
                ordinals = {
                    json.loads(str(row[0])).get("candidate_ordinal")
                    for row in connection.execute(
                        "SELECT spec_json FROM experiments WHERE campaign_id = ?",
                        (spec.campaign_id,),
                    )
                }
                if spec.candidate_ordinal in ordinals:
                    raise ExperimentError("intraday candidate ordinal already exists in campaign")
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

    def _claim_planned_intraday(
        self,
        spec: IntradayExperimentSpec,
        review_id: str | None = None,
        wheel: Path | None = None,
        manifest: Path | None = None,
        lockfile: Path | None = None,
        dependency_wheelhouse: Path | None = None,
    ) -> dict[str, object] | None:
        if self.get_planned_intraday_spec(spec.experiment_id) != spec:
            raise ExperimentError("stored planned intraday experiment differs")
        if spec.campaign_id == "intraday-research-v1":
            if (
                review_id is None
                or wheel is None
                or manifest is None
                or lockfile is None
                or dependency_wheelhouse is None
            ):
                raise ExperimentError(
                    "Campaign V1 execution requires an explicit reviewed execution build"
                )
            return self._claim_campaign_v1_intraday(
                spec, review_id, wheel, manifest, lockfile, dependency_wheelhouse
            )
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
                raise ExperimentError(
                    f"planned intraday experiment is not pending: {spec.experiment_id}"
                )
        return None

    def _claim_campaign_v1_intraday(
        self,
        spec: IntradayExperimentSpec,
        review_id: str,
        wheel: Path,
        manifest: Path,
        lockfile: Path,
        dependency_wheelhouse: Path,
    ) -> dict[str, object]:
        from .intraday_source_provenance import (
            INTRADAY_CAMPAIGN_ID,
            INTRADAY_FOUNDATION_COMMIT,
            INTRADAY_PLAN_FINGERPRINT,
            assess_intraday_execution_source,
        )

        assessment = assess_intraday_execution_source(
            wheel, manifest, lockfile, dependency_wheelhouse
        )
        if spec.campaign_id != INTRADAY_CAMPAIGN_ID or not assessment.surface_comparison.equivalent:
            raise ExperimentError(
                "execution source differs from the reviewed foundation; "
                "a new intraday campaign version is required"
            )
        assessment_json = canonicalize(assessment)
        timestamp = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            review_row = connection.execute(
                """
                SELECT review_json, review_fingerprint
                FROM intraday_execution_source_reviews WHERE review_id = ?
                """,
                (review_id,),
            ).fetchone()
            if review_row is None:
                raise ExperimentError(f"intraday execution source review not found: {review_id}")
            review = _fingerprinted_record(
                json.loads(str(review_row[0])),
                _INTRADAY_SOURCE_REVIEW_FIELDS,
                "review_fingerprint",
                "intraday execution source review",
            )
            if (
                review["review_fingerprint"] != review_row[1]
                or review["campaign_id"] != INTRADAY_CAMPAIGN_ID
                or review["plan_fingerprint"] != INTRADAY_PLAN_FINGERPRINT
                or review["foundation_commit"] != INTRADAY_FOUNDATION_COMMIT
                or review["execution_commit"] != assessment.build_identity.source_commit
                or review["assessment_fingerprint"] != assessment.assessment_fingerprint
                or review["build_identity_fingerprint"]
                != assessment.build_identity.identity_fingerprint
                or review["environment_identity_fingerprint"]
                != assessment.environment_identity.identity_fingerprint
                or canonicalize(review["assessment"]) != assessment_json
            ):
                raise ExperimentError(
                    "current execution source differs from its recorded Campaign V1 review"
                )
            row = connection.execute(
                """
                SELECT spec_json, status, campaign_plan_fingerprint
                FROM experiments WHERE experiment_id = ? AND campaign_id = ?
                """,
                (spec.experiment_id, INTRADAY_CAMPAIGN_ID),
            ).fetchone()
            if (
                row is None
                or canonicalize(json.loads(str(row[0]))) != canonicalize(spec)
                or row[1] != ExperimentStatus.PENDING.value
                or row[2] != INTRADAY_PLAN_FINGERPRINT
            ):
                raise ExperimentError(
                    f"planned intraday experiment is not pending: {spec.experiment_id}"
                )
            unsigned: dict[str, object] = {
                "schema_version": "intraday-execution-source-binding-v1",
                "experiment_id": spec.experiment_id,
                "review_id": review_id,
                "review_fingerprint": review["review_fingerprint"],
                "assessment_fingerprint": assessment.assessment_fingerprint,
                "execution_commit": assessment.build_identity.source_commit,
                "build_identity_fingerprint": assessment.build_identity.identity_fingerprint,
                "environment_identity_fingerprint": (
                    assessment.environment_identity.identity_fingerprint
                ),
                "verified_at": timestamp,
            }
            binding = {**unsigned, "binding_fingerprint": fingerprint(unsigned)}
            try:
                connection.execute(
                    """
                    INSERT INTO intraday_experiment_execution_sources
                    (experiment_id, review_id, binding_json, binding_fingerprint)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        spec.experiment_id,
                        review_id,
                        canonical_json(binding),
                        binding["binding_fingerprint"],
                    ),
                )
                cursor = connection.execute(
                    """
                    UPDATE experiments
                    SET status = ?, started_at = COALESCE(started_at, ?), heartbeat_at = ?
                    WHERE experiment_id = ? AND status = ?
                      AND campaign_plan_fingerprint = ?
                    """,
                    (
                        ExperimentStatus.RUNNING.value,
                        timestamp,
                        timestamp,
                        spec.experiment_id,
                        ExperimentStatus.PENDING.value,
                        INTRADAY_PLAN_FINGERPRINT,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ExperimentError(
                    "planned intraday execution source could not be bound"
                ) from error
            if cursor.rowcount != 1:
                raise ExperimentError(
                    f"planned intraday experiment is not pending: {spec.experiment_id}"
                )
        return binding

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

    def _complete_planned_intraday(
        self,
        spec: IntradayExperimentSpec,
        metrics: Mapping[str, object],
        artifact_locations: list[str],
        artifact_hashes: list[str],
    ) -> None:
        if self.get_planned_intraday_spec(spec.experiment_id) != spec:
            raise ExperimentError("stored planned intraday experiment differs")
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
                raise ExperimentError(
                    f"planned intraday experiment is not running: {spec.experiment_id}"
                )

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
        self,
        experiment_id: str,
        event_id: str,
        reviewer: str,
        reason: str,
        proposal_fingerprint: str | None = None,
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
                    "INSERT INTO holdout_access "
                    "(event_id, experiment_id, reviewer, reason, created_at, proposal_fingerprint) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (event_id, experiment_id, reviewer, reason, _now(), proposal_fingerprint),
                )
            except sqlite3.IntegrityError as error:
                raise HoldoutAccessError(
                    f"holdout access already exists for experiment: {experiment_id}"
                ) from error

    def get_holdout_access(self, event_id: str) -> dict[str, str | None]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT event_id, experiment_id, reviewer, reason, created_at, "
                "proposal_fingerprint "
                "FROM holdout_access WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"holdout access event not found: {event_id}")
        return dict(
            zip(
                (
                    "event_id",
                    "experiment_id",
                    "reviewer",
                    "reason",
                    "created_at",
                    "proposal_fingerprint",
                ),
                (str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]), row[5]),
                strict=True,
            )
        )

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
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()


_INTRADAY_SOURCE_REVIEW_FIELDS = {
    "schema_version",
    "review_id",
    "campaign_id",
    "plan_fingerprint",
    "foundation_commit",
    "execution_commit",
    "assessment",
    "assessment_fingerprint",
    "build_identity_fingerprint",
    "environment_identity_fingerprint",
    "surface_comparison_fingerprint",
    "reviewer",
    "reason",
    "reviewed_at",
    "review_fingerprint",
}
_INTRADAY_SOURCE_BINDING_FIELDS = {
    "schema_version",
    "experiment_id",
    "review_id",
    "review_fingerprint",
    "assessment_fingerprint",
    "execution_commit",
    "build_identity_fingerprint",
    "environment_identity_fingerprint",
    "verified_at",
    "binding_fingerprint",
}


def _fingerprinted_record(
    value: object,
    fields: set[str],
    fingerprint_field: str,
    context: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ExperimentError(f"stored {context} fields differ")
    claimed = value.get(fingerprint_field)
    unsigned = dict(value)
    unsigned.pop(fingerprint_field, None)
    if not isinstance(claimed, str) or fingerprint(unsigned) != claimed:
        raise ExperimentError(f"stored {context} fingerprint differs")
    return value


_CANDIDATE_SPEC_FIELDS = {
    "strategy_id",
    "strategy_version",
    "strategy_family",
    "code_commit",
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


def validate_passing_qualification_evidence(
    evidence_report: Mapping[str, object],
) -> dict[str, object]:
    """Return canonical evidence only when every approved qualification gate passes."""
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
        raise HoldoutAccessError("qualification evidence requires approved passing gates")
    candidate = report["candidate_specification"]
    assert isinstance(candidate, dict)
    _validate_candidate_specification(candidate)
    return report


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
        "code_commit",
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


def _experiment_spec(value: Mapping[str, object]) -> ExperimentContract:
    parameters = value["parameters"]
    random_seed = value["random_seed"]
    parent = value["parent_candidate"]
    if not isinstance(parameters, Mapping):
        raise ExperimentError("stored experiment parameters are invalid")
    if random_seed is not None and type(random_seed) is not int:
        raise ExperimentError("stored experiment random seed is invalid")
    if parent is not None and not isinstance(parent, str):
        raise ExperimentError("stored experiment parent is invalid")
    if value.get("schema_version") == "intraday-experiment-v1":
        return IntradayExperimentSpec(
            experiment_id=str(value["experiment_id"]),
            campaign_id=str(value["campaign_id"]),
            search_budget=_stored_positive_int(value, "search_budget"),
            candidate_ordinal=_stored_positive_int(value, "candidate_ordinal"),
            strategy_id=str(value["strategy_id"]),
            strategy_version=str(value["strategy_version"]),
            strategy_family=str(value["strategy_family"]),
            code_commit=str(value["code_commit"]),
            dataset_id=str(value["dataset_id"]),
            dataset_fingerprint=str(value["dataset_fingerprint"]),
            universe_id=str(value["universe_id"]),
            universe_fingerprint=str(value["universe_fingerprint"]),
            parameters=parameters,
            timeframe=str(value["timeframe"]),
            session_policy_version=str(value["session_policy_version"]),
            bar_timestamp_semantics_version=str(value["bar_timestamp_semantics_version"]),
            session_return_policy_version=str(value["session_return_policy_version"]),
            benchmark_policy_version=str(value["benchmark_policy_version"]),
            cost_model_version=str(value["cost_model_version"]),
            slippage_bps=Decimal(str(value["slippage_bps"])),
            commission_bps=Decimal(str(value["commission_bps"])),
            execution_model_version=str(value["execution_model_version"]),
            earliest_fill_semantics=str(value["earliest_fill_semantics"]),
            execution_delay_bars=_stored_positive_int(value, "execution_delay_bars"),
            split=ExperimentSplit(str(value["split"])),
            start_timestamp=_parse_utc(str(value["start_timestamp"])),
            end_timestamp=_parse_utc(str(value["end_timestamp"])),
            random_seed=random_seed,
            creation_reason=str(value["creation_reason"]),
            parent_candidate=parent,
        )
    if value.get("schema_version") is not None:
        raise ExperimentError("stored experiment schema version is unsupported")
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


def _validate_planned_intraday_spec(
    plan: IntradayResearchCampaignPlan, spec: IntradayExperimentSpec
) -> None:
    reservation = next(
        (
            candidate
            for candidate in plan.candidates
            if candidate.experiment_id == spec.experiment_id
        ),
        None,
    )
    if reservation is None:
        raise ExperimentError("intraday experiment is not reserved by the sealed plan")
    expected = {
        "campaign_id": plan.campaign_id,
        "search_budget": plan.search_budget,
        "candidate_ordinal": reservation.candidate_ordinal,
        "strategy_id": reservation.strategy_id,
        "strategy_version": "1",
        "strategy_family": reservation.strategy_family,
        "code_commit": plan.base_code_commit,
        "parameters": canonicalize(reservation.parameters),
        "timeframe": "5m",
        "session_policy_version": "XNYS-regular-session-flat-v1",
        "bar_timestamp_semantics_version": "bar-open-utc-v1",
        "session_return_policy_version": "XNYS-session-close-equity-v1",
        "benchmark_policy_version": "cash-and-continuous-underlying-v1",
        "cost_model_version": reservation.cost_model_version,
        "slippage_bps": reservation.slippage_bps,
        "commission_bps": reservation.commission_bps,
        "execution_model_version": "deterministic-next-bar-open-v1",
        "earliest_fill_semantics": "completed-bar-next-bar-open-v1",
        "execution_delay_bars": reservation.execution_delay_bars,
        "split": reservation.split,
        "start_timestamp": reservation.start_timestamp,
        "end_timestamp": reservation.end_timestamp,
        "random_seed": 0,
        "creation_reason": (
            f"preregistered {reservation.variant_role} evidence for "
            f"{reservation.strategy_id} {reservation.period_role}"
        ),
        "parent_candidate": reservation.parent_candidate,
    }
    observed = {
        field: canonicalize(spec.parameters) if field == "parameters" else getattr(spec, field)
        for field in expected
    }
    if observed != expected:
        raise ExperimentError("intraday experiment differs from its sealed reservation")


def _planned_intraday_reservation(
    plan: IntradayResearchCampaignPlan,
    reservation: IntradayCandidateReservation,
) -> dict[str, object]:
    """Represent one immutable candidate before a period dataset is bound."""

    return {
        "schema_version": "intraday-candidate-reservation-v1",
        "experiment_id": reservation.experiment_id,
        "campaign_id": plan.campaign_id,
        "search_budget": plan.search_budget,
        "candidate_ordinal": reservation.candidate_ordinal,
        "strategy_id": reservation.strategy_id,
        "strategy_version": "1",
        "strategy_family": reservation.strategy_family,
        "code_commit": plan.base_code_commit,
        "parameters": reservation.parameters,
        "timeframe": "5m",
        "session_policy_version": "XNYS-regular-session-flat-v1",
        "bar_timestamp_semantics_version": "bar-open-utc-v1",
        "session_return_policy_version": "XNYS-session-close-equity-v1",
        "benchmark_policy_version": "cash-and-continuous-underlying-v1",
        "cost_model_version": reservation.cost_model_version,
        "slippage_bps": reservation.slippage_bps,
        "commission_bps": reservation.commission_bps,
        "execution_model_version": "deterministic-next-bar-open-v1",
        "earliest_fill_semantics": "completed-bar-next-bar-open-v1",
        "execution_delay_bars": reservation.execution_delay_bars,
        "split": reservation.split,
        "start_timestamp": reservation.start_timestamp,
        "end_timestamp": reservation.end_timestamp,
        "random_seed": 0,
        "creation_reason": (
            f"preregistered {reservation.variant_role} evidence for "
            f"{reservation.strategy_id} {reservation.period_role}"
        ),
        "parent_candidate": reservation.parent_candidate,
        "period_role": reservation.period_role,
        "variant_role": reservation.variant_role,
    }


def _stored_positive_int(value: Mapping[str, object], field: str) -> int:
    candidate = value.get(field)
    if isinstance(candidate, bool) or not isinstance(candidate, int) or candidate < 1:
        raise ExperimentError(f"stored experiment {field.replace('_', ' ')} is invalid")
    return candidate


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
