"""Read-only proof for recovery of submission-unknown paper orders."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .broker_events import BrokerEventStore
from .execution import JournalIntegrityError
from .fingerprints import fingerprint
from .orders import OrderState
from .reconciliation import ReconciliationStore
from .risk import RiskLimits


@dataclass(frozen=True)
class SubmissionRecoveryProof:
    ready_for_review: bool
    reasons: tuple[str, ...]
    order_id: str
    lookup_evidence_id: str
    reconciliation_evidence_id: str
    baseline_id: str
    authorization_id: str
    account_id: str
    observed_snapshot_id: str
    emergency_generation: int
    assessed_at: datetime

    def __post_init__(self) -> None:
        if self.ready_for_review != (not self.reasons):
            raise ValueError("recovery readiness must match its reasons")
        if any(not reason for reason in self.reasons):
            raise ValueError("recovery reasons must be nonempty")
        if self.assessed_at.tzinfo is None or self.assessed_at.utcoffset() != UTC.utcoffset(
            self.assessed_at
        ):
            raise ValueError("recovery assessment time must be UTC-aware")

    @property
    def proof_fingerprint(self) -> str:
        return fingerprint(self)


class _RecoveryVerifier(BrokerEventStore, ReconciliationStore):
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            f"{self.path.resolve().as_uri()}?mode=ro", uri=True, timeout=30
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        finally:
            connection.close()


class SubmissionRecoveryStore:
    """Expose only read-only verification of submission recovery evidence."""

    def __init__(self, path: Path) -> None:
        self.path = path
        if not path.is_file():
            raise JournalIntegrityError("execution database is missing")

    def assess(
        self,
        *,
        order_id: str,
        lookup_evidence_id: str,
        reconciliation_evidence_id: str,
        limits: RiskLimits,
        assessed_at: datetime,
    ) -> SubmissionRecoveryProof:
        if not order_id or order_id != order_id.strip() or len(order_id) > 128:
            raise ValueError("order ID is invalid")
        if any(
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
            for value in (lookup_evidence_id, reconciliation_evidence_id)
        ):
            raise ValueError("recovery evidence ID is invalid")
        if assessed_at.tzinfo is None or assessed_at.utcoffset() != UTC.utcoffset(assessed_at):
            raise ValueError("recovery assessment time must be UTC-aware")

        verifier = _RecoveryVerifier(self.path)
        with verifier._connect() as connection:
            connection.execute("BEGIN")
            verifier._verify_reservations(connection)
            verifier._verify_releases(connection)
            verifier._verify_orders(connection)
            verifier._verify_broker_events(connection)
            lookups = verifier._verify_lookup_not_found(connection)
            snapshots, _, baselines, reconciliations = verifier._verify_all(connection)
            emergency = verifier._verify_emergency(connection)
            authorizations = verifier._verify_authorizations(connection)
            lookup = lookups.get(lookup_evidence_id)
            reconciliation = reconciliations.get(reconciliation_evidence_id)
            if lookup is None or reconciliation is None:
                raise KeyError("recovery evidence is missing")
            baseline = baselines[reconciliation.baseline_id]
            authorization = authorizations[baseline.authorization_id]
            observed = snapshots[reconciliation.observed_snapshot_id]
            order = connection.execute(
                "SELECT o.state, r.authorization_id, r.expires_at, x.reservation_id FROM orders o "
                "JOIN capacity_reservations r ON r.reservation_id = o.reservation_id "
                "LEFT JOIN capacity_releases x ON x.reservation_id = r.reservation_id "
                "WHERE o.order_id = ?",
                (order_id,),
            ).fetchone()
            unresolved = connection.execute(
                "SELECT order_id, state FROM orders WHERE state IN (?, ?)",
                (OrderState.SUBMITTING, OrderState.SUBMISSION_UNKNOWN),
            ).fetchall()
            lookup_sequence = connection.execute(
                "SELECT journal_sequence FROM order_lookup_not_found WHERE evidence_id = ?",
                (lookup_evidence_id,),
            ).fetchone()[0]
            emergency_changes = connection.execute(
                "SELECT COUNT(*) FROM journal WHERE sequence > ? "
                "AND event_type IN ('emergency-disabled', 'emergency-cleared')",
                (lookup_sequence,),
            ).fetchone()[0]

        reasons: list[str] = []
        if order is None or OrderState(order[0]) is not OrderState.SUBMISSION_UNKNOWN:
            reasons.append("order-not-submission-unknown")
        if order is None or order[3] is not None or assessed_at >= datetime.fromisoformat(order[2]):
            reasons.append("capacity-not-reserved")
        if lookup.client_order_id != order_id:
            reasons.append("lookup-order-mismatch")
        if (
            order is None
            or order[1] != baseline.authorization_id
            or lookup.account_id != authorization.account_id
            or authorization.account_id != limits.account_id
        ):
            reasons.append("authority-or-account-mismatch")
        if (
            baseline.risk_configuration_fingerprint != limits.configuration_fingerprint
            or authorization.risk_configuration_fingerprint != limits.configuration_fingerprint
        ):
            reasons.append("authority-or-limits-mismatch")
        if (
            assessed_at < authorization.authorized_at
            or assessed_at >= authorization.expires_at
            or assessed_at < limits.effective_at
            or assessed_at >= limits.expires_at
        ):
            reasons.append("authority-or-limits-inactive")
        if emergency.disabled:
            reasons.append("emergency-disabled")
        if emergency_changes:
            reasons.append("emergency-state-changed-after-lookup")
        if not reconciliation.result.clean or reconciliation.unresolved_mutations:
            reasons.append("reconciliation-not-clean")
        observation_times = (
            observed.account_observed_at,
            observed.positions_observed_at,
            observed.orders_observed_at,
        )
        if reconciliation.result.compared_at < lookup.observed_at or any(
            value < lookup.observed_at for value in observation_times
        ):
            reasons.append("reconciliation-predates-lookup")
        if reconciliation.result.compared_at > assessed_at or any(
            value > assessed_at
            or (assessed_at - value).total_seconds() > limits.max_snapshot_age_seconds
            for value in observation_times
        ):
            reasons.append("reconciliation-stale-or-future")
        if observed.account_id != lookup.account_id or order_id in observed.open_client_order_ids:
            reasons.append("observed-order-or-account-mismatch")
        if unresolved != [(order_id, OrderState.SUBMISSION_UNKNOWN)]:
            reasons.append("other-unresolved-submissions")

        unique_reasons = tuple(dict.fromkeys(reasons))
        return SubmissionRecoveryProof(
            ready_for_review=not unique_reasons,
            reasons=unique_reasons,
            order_id=order_id,
            lookup_evidence_id=lookup_evidence_id,
            reconciliation_evidence_id=reconciliation_evidence_id,
            baseline_id=baseline.baseline_id,
            authorization_id=authorization.authorization_id,
            account_id=authorization.account_id,
            observed_snapshot_id=observed.snapshot_id,
            emergency_generation=emergency.generation,
            assessed_at=assessed_at,
        )
