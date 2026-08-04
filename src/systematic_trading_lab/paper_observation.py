"""Durable read-only paper observation campaigns."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .alpaca_paper import AlpacaPaperError, AlpacaPaperReader
from .execution import JournalIntegrityError
from .fingerprints import canonical_json, canonicalize, fingerprint
from .reconciliation import PortfolioSnapshot, PositionSnapshot, ReconciliationStore


@dataclass(frozen=True)
class PaperObservationCampaign:
    campaign_id: str
    account_id: str
    baseline_snapshot_id: str
    baseline_snapshot_fingerprint: str
    expected_positions: tuple[PositionSnapshot, ...]
    maximum_gap_seconds: int
    starts_at: datetime
    ends_at: datetime

    def __post_init__(self) -> None:
        if (
            not self.campaign_id
            or self.campaign_id != self.campaign_id.strip()
            or len(self.campaign_id) > 128
        ):
            raise ValueError("paper observation campaign ID is invalid")
        if (
            not self.account_id
            or self.account_id != self.account_id.strip()
            or len(self.account_id) > 128
        ):
            raise ValueError("paper observation account ID is invalid")
        _sha256(self.baseline_snapshot_fingerprint)
        if isinstance(self.maximum_gap_seconds, bool) or self.maximum_gap_seconds < 1:
            raise ValueError("paper observation maximum gap must be positive")
        _utc(self.starts_at)
        _utc(self.ends_at)
        if self.ends_at <= self.starts_at:
            raise ValueError("paper observation campaign end must follow its start")

    @property
    def campaign_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class PaperObservation:
    observation_id: str
    campaign_id: str
    snapshot_id: str | None
    snapshot_fingerprint: str | None
    status: str
    reasons: tuple[str, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        _sha256(self.observation_id)
        if not self.campaign_id or len(self.campaign_id) > 128:
            raise ValueError("paper observation campaign ID is invalid")
        if self.status not in {"healthy", "drift", "read-failed"}:
            raise ValueError("paper observation status is invalid")
        if self.status == "healthy" and self.reasons:
            raise ValueError("healthy paper observation cannot have reasons")
        if self.status != "healthy" and not self.reasons:
            raise ValueError("unhealthy paper observation requires reasons")
        if (self.snapshot_id is None) != (self.snapshot_fingerprint is None):
            raise ValueError("paper observation snapshot binding is incomplete")
        if self.status == "read-failed" and self.snapshot_id is not None:
            raise ValueError("failed paper observation cannot bind a snapshot")
        if self.snapshot_fingerprint is not None:
            _sha256(self.snapshot_fingerprint)
        _utc(self.observed_at)


@dataclass(frozen=True)
class PaperObservationStatus:
    campaign_id: str
    healthy_now: bool
    campaign_complete: bool
    reasons: tuple[str, ...]
    success_count: int
    drift_count: int
    failure_count: int
    maximum_observed_gap_seconds: int
    latest_observed_at: datetime
    assessed_at: datetime


class PaperObservationStore(ReconciliationStore):
    """Bind operational samples to production-attested paper snapshots."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_observation_campaigns (
                    campaign_id TEXT PRIMARY KEY,
                    campaign_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TABLE IF NOT EXISTS paper_observations (
                    observation_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES paper_observation_campaigns(campaign_id),
                    observation_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS paper_observation_campaigns_no_update
                BEFORE UPDATE ON paper_observation_campaigns BEGIN
                    SELECT RAISE(ABORT, 'paper observation campaigns are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS paper_observation_campaigns_no_delete
                BEFORE DELETE ON paper_observation_campaigns BEGIN
                    SELECT RAISE(ABORT, 'paper observation campaigns are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS paper_observations_no_update
                BEFORE UPDATE ON paper_observations BEGIN
                    SELECT RAISE(ABORT, 'paper observations are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS paper_observations_no_delete
                BEFORE DELETE ON paper_observations BEGIN
                    SELECT RAISE(ABORT, 'paper observations are immutable');
                END;
                """
            )
            connection.commit()
            self._verify_observations(connection)

    def start(
        self,
        *,
        campaign_id: str,
        baseline_snapshot_id: str,
        maximum_gap_seconds: int,
        duration: timedelta,
    ) -> PaperObservationCampaign:
        if duration <= timedelta(0):
            raise ValueError("paper observation duration must be positive")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            campaigns, _ = self._verify_observations(connection)
            snapshots, attestations, _, _ = self._verify_reconciliation(connection)
            try:
                snapshot = snapshots[baseline_snapshot_id]
                attestation = attestations[baseline_snapshot_id]
            except KeyError as error:
                raise JournalIntegrityError("paper observation baseline is missing") from error
            campaign = PaperObservationCampaign(
                campaign_id=campaign_id,
                account_id=snapshot.account_id,
                baseline_snapshot_id=snapshot.snapshot_id,
                baseline_snapshot_fingerprint=snapshot.snapshot_fingerprint,
                expected_positions=snapshot.positions,
                maximum_gap_seconds=maximum_gap_seconds,
                starts_at=attestation.completed_at,
                ends_at=attestation.completed_at + duration,
            )
            existing = campaigns.get(campaign_id)
            if existing is not None:
                if existing != campaign:
                    raise JournalIntegrityError("paper observation campaign ID has other content")
                connection.commit()
                return existing
            sequence = self._append_event(
                connection,
                occurred_at=campaign.starts_at,
                event_type="paper-observation-campaign-started",
                entity_type="paper-observation-campaign",
                entity_id=campaign.campaign_id,
                payload=canonicalize(campaign),
            )
            connection.execute(
                "INSERT INTO paper_observation_campaigns VALUES (?, ?, ?)",
                (campaign.campaign_id, canonical_json(campaign), sequence),
            )
            self._record_snapshot_observation(
                connection, campaign, snapshot, attestation.completed_at
            )
            connection.commit()
        return campaign

    def record_sample(self, campaign_id: str, snapshot_id: str) -> PaperObservation:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            campaigns, observations = self._verify_observations(connection)
            snapshots, attestations, _, _ = self._verify_reconciliation(connection)
            try:
                campaign = campaigns[campaign_id]
                snapshot = snapshots[snapshot_id]
                attestation = attestations[snapshot_id]
            except KeyError as error:
                raise JournalIntegrityError("paper observation authority is missing") from error
            result = self._snapshot_observation(campaign, snapshot, attestation.completed_at)
            existing = observations.get(result.observation_id)
            if existing is not None:
                connection.commit()
                return existing
            self._insert_observation(connection, result)
            connection.commit()
        return result

    def record_failure(self, campaign_id: str, *, observed_at: datetime) -> PaperObservation:
        _utc(observed_at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            campaigns, observations = self._verify_observations(connection)
            try:
                campaign = campaigns[campaign_id]
            except KeyError as error:
                raise KeyError(campaign_id) from error
            if not campaign.starts_at <= observed_at <= campaign.ends_at:
                raise JournalIntegrityError("paper observation failure is outside its campaign")
            result = PaperObservation(
                observation_id=fingerprint(
                    {"campaign_id": campaign_id, "status": "read-failed", "at": observed_at}
                ),
                campaign_id=campaign_id,
                snapshot_id=None,
                snapshot_fingerprint=None,
                status="read-failed",
                reasons=("paper-read-failed",),
                observed_at=observed_at,
            )
            existing = observations.get(result.observation_id)
            if existing is not None:
                connection.commit()
                return existing
            self._insert_observation(connection, result)
            connection.commit()
        return result

    def assess(self, campaign_id: str, *, assessed_at: datetime) -> PaperObservationStatus:
        _utc(assessed_at)
        with self._connect() as connection:
            connection.execute("BEGIN")
            campaigns, observations = self._verify_observations(connection)
        try:
            campaign = campaigns[campaign_id]
        except KeyError as error:
            raise KeyError(campaign_id) from error
        samples = sorted(
            (item for item in observations.values() if item.campaign_id == campaign_id),
            key=lambda item: (item.observed_at, item.observation_id),
        )
        latest = samples[-1]
        gaps = tuple(
            int((later.observed_at - earlier.observed_at).total_seconds())
            for earlier, later in zip(samples, samples[1:], strict=False)
        )
        reasons = list(latest.reasons)
        if assessed_at < campaign.starts_at:
            reasons.append("campaign-not-started")
        elif (
            min(assessed_at, campaign.ends_at) - latest.observed_at
        ).total_seconds() > campaign.maximum_gap_seconds:
            reasons.append("observation-stale")
        return PaperObservationStatus(
            campaign_id=campaign_id,
            healthy_now=not reasons,
            campaign_complete=assessed_at >= campaign.ends_at,
            reasons=tuple(dict.fromkeys(reasons)),
            success_count=sum(item.status == "healthy" for item in samples),
            drift_count=sum(item.status == "drift" for item in samples),
            failure_count=sum(item.status == "read-failed" for item in samples),
            maximum_observed_gap_seconds=max(gaps, default=0),
            latest_observed_at=latest.observed_at,
            assessed_at=assessed_at,
        )

    def _record_snapshot_observation(
        self,
        connection: sqlite3.Connection,
        campaign: PaperObservationCampaign,
        snapshot: PortfolioSnapshot,
        observed_at: datetime,
    ) -> PaperObservation:
        result = self._snapshot_observation(campaign, snapshot, observed_at)
        self._insert_observation(connection, result)
        return result

    @staticmethod
    def _snapshot_observation(
        campaign: PaperObservationCampaign,
        snapshot: PortfolioSnapshot,
        observed_at: datetime,
    ) -> PaperObservation:
        if not campaign.starts_at <= observed_at <= campaign.ends_at:
            raise JournalIntegrityError("paper snapshot is outside its observation campaign")
        reasons: list[str] = []
        if snapshot.account_id != campaign.account_id:
            reasons.append("account-mismatch")
        if not snapshot.account_ready:
            reasons.append("account-not-ready")
        if snapshot.positions != campaign.expected_positions:
            reasons.append("positions-drift")
        if snapshot.open_orders:
            reasons.append("open-orders-present")
        status = "healthy" if not reasons else "drift"
        return PaperObservation(
            observation_id=fingerprint(
                {
                    "campaign": campaign.campaign_fingerprint,
                    "snapshot": snapshot.snapshot_fingerprint,
                }
            ),
            campaign_id=campaign.campaign_id,
            snapshot_id=snapshot.snapshot_id,
            snapshot_fingerprint=snapshot.snapshot_fingerprint,
            status=status,
            reasons=tuple(reasons),
            observed_at=observed_at,
        )

    def _insert_observation(
        self, connection: sqlite3.Connection, observation: PaperObservation
    ) -> None:
        sequence = self._append_event(
            connection,
            occurred_at=observation.observed_at,
            event_type="paper-observation-recorded",
            entity_type="paper-observation",
            entity_id=observation.observation_id,
            payload=canonicalize(observation),
        )
        connection.execute(
            "INSERT INTO paper_observations VALUES (?, ?, ?, ?)",
            (
                observation.observation_id,
                observation.campaign_id,
                canonical_json(observation),
                sequence,
            ),
        )

    def _verify_observations(
        self, connection: sqlite3.Connection
    ) -> tuple[dict[str, PaperObservationCampaign], dict[str, PaperObservation]]:
        self._verify_all(connection)
        snapshots, attestations, _, _ = self._verify_reconciliation(connection)
        campaigns: dict[str, PaperObservationCampaign] = {}
        campaign_rows = connection.execute(
            "SELECT campaign_id, campaign_json, journal_sequence FROM paper_observation_campaigns"
        ).fetchall()
        campaign_event_count = connection.execute(
            "SELECT COUNT(*) FROM journal WHERE event_type = 'paper-observation-campaign-started'"
        ).fetchone()[0]
        if len(campaign_rows) != campaign_event_count:
            raise JournalIntegrityError("paper observation campaign count differs")
        for row in campaign_rows:
            try:
                campaign = _decode_campaign(json.loads(row[1]))
                snapshot = snapshots[campaign.baseline_snapshot_id]
                attestation = attestations[campaign.baseline_snapshot_id]
            except (KeyError, ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError(
                    "stored paper observation campaign is invalid"
                ) from error
            if (
                row[0] != campaign.campaign_id
                or row[1] != canonical_json(campaign)
                or snapshot.snapshot_fingerprint != campaign.baseline_snapshot_fingerprint
                or snapshot.account_id != campaign.account_id
                or snapshot.positions != campaign.expected_positions
                or attestation.completed_at != campaign.starts_at
                or not _journal_matches(
                    connection,
                    int(row[2]),
                    campaign.starts_at,
                    "paper-observation-campaign-started",
                    "paper-observation-campaign",
                    campaign.campaign_id,
                    canonical_json(campaign),
                )
            ):
                raise JournalIntegrityError("paper observation campaign differs from its evidence")
            campaigns[campaign.campaign_id] = campaign
        observations: dict[str, PaperObservation] = {}
        observation_rows = connection.execute(
            "SELECT observation_id, campaign_id, observation_json, journal_sequence "
            "FROM paper_observations"
        ).fetchall()
        observation_event_count = connection.execute(
            "SELECT COUNT(*) FROM journal WHERE event_type = 'paper-observation-recorded'"
        ).fetchone()[0]
        if len(observation_rows) != observation_event_count:
            raise JournalIntegrityError("paper observation count differs")
        for row in observation_rows:
            try:
                observation = _decode_observation(json.loads(row[2]))
                campaign = campaigns[observation.campaign_id]
            except (KeyError, ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("stored paper observation is invalid") from error
            expected = observation
            if observation.snapshot_id is not None:
                try:
                    snapshot = snapshots[observation.snapshot_id]
                    attestation = attestations[observation.snapshot_id]
                except KeyError as error:
                    raise JournalIntegrityError("stored paper observation is invalid") from error
                expected = self._snapshot_observation(campaign, snapshot, attestation.completed_at)
            elif (
                observation.status != "read-failed"
                or observation.reasons != ("paper-read-failed",)
                or not campaign.starts_at <= observation.observed_at <= campaign.ends_at
                or observation.observation_id
                != fingerprint(
                    {
                        "campaign_id": campaign.campaign_id,
                        "status": "read-failed",
                        "at": observation.observed_at,
                    }
                )
            ):
                raise JournalIntegrityError("stored paper observation is invalid")
            if (
                observation != expected
                or row[:3]
                != (
                    observation.observation_id,
                    observation.campaign_id,
                    canonical_json(observation),
                )
                or not _journal_matches(
                    connection,
                    int(row[3]),
                    observation.observed_at,
                    "paper-observation-recorded",
                    "paper-observation",
                    observation.observation_id,
                    canonical_json(observation),
                )
            ):
                raise JournalIntegrityError("paper observation differs from its evidence")
            observations[observation.observation_id] = observation
        return campaigns, observations


def record_production_observation(
    store: PaperObservationStore,
    reader: AlpacaPaperReader,
    *,
    campaign_id: str,
    observed_at: datetime | None = None,
) -> PaperObservation:
    """Record a production GET result without storing broker error text."""
    try:
        snapshot = reader.record_portfolio(ReconciliationStore(store.path))
    except AlpacaPaperError:
        return store.record_failure(campaign_id, observed_at=observed_at or datetime.now(UTC))
    return store.record_sample(campaign_id, snapshot.snapshot_id)


def _decode_campaign(value: object) -> PaperObservationCampaign:
    if not isinstance(value, dict):
        raise ValueError("paper observation campaign must be an object")
    try:
        return PaperObservationCampaign(
            **{
                **value,
                "expected_positions": tuple(
                    PositionSnapshot(**item) for item in value["expected_positions"]
                ),
                "starts_at": _parse_utc(value["starts_at"]),
                "ends_at": _parse_utc(value["ends_at"]),
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("paper observation campaign is invalid") from error


def _decode_observation(value: object) -> PaperObservation:
    if not isinstance(value, dict):
        raise ValueError("paper observation must be an object")
    try:
        return PaperObservation(
            **{
                **value,
                "reasons": tuple(value["reasons"]),
                "observed_at": _parse_utc(value["observed_at"]),
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("paper observation is invalid") from error


def _journal_matches(
    connection: sqlite3.Connection,
    sequence: int,
    occurred_at: datetime,
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload: str,
) -> bool:
    return bool(
        connection.execute(
            "SELECT occurred_at, event_type, entity_type, entity_id, payload_json "
            "FROM journal WHERE sequence = ?",
            (sequence,),
        ).fetchone()
        == (
            _utc_text(occurred_at),
            event_type,
            entity_type,
            entity_id,
            payload,
        )
    )


def _parse_utc(value: str) -> datetime:
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    _utc(result)
    return result


def _utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("paper observation time must be UTC-aware")


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("paper observation fingerprint is invalid")
