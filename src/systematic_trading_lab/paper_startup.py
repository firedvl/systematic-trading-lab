"""Read-only startup assessment for the future Alpaca paper operator."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .broker_events import BrokerEventStore
from .cancel_all import CancelAllStore
from .config import Settings
from .domain import TradingMode
from .execution import JournalIntegrityError
from .paper_activation import PaperWriteActivationStore
from .paper_cancellation import PaperCancellationStore
from .paper_submission import PaperSubmissionPreflightStore
from .risk import RiskLimits, RiskStore
from .risk_context import AttestedRiskContextStore
from .risk_inputs import RiskInputEvidenceStore
from .runtime_build import InstalledRuntimeIdentity
from .settled_capacity import SettledCapacityStore


@dataclass(frozen=True)
class PaperStartupAssessment:
    ready: bool
    reasons: tuple[str, ...]
    authorization_id: str
    risk_configuration_fingerprint: str
    activation_id: str | None
    runtime_identity_fingerprint: str | None
    emergency_disabled: bool | None
    submission_unknown_count: int | None
    unresolved_cancellation_count: int | None
    assessed_at: datetime


@dataclass(frozen=True)
class PaperStorageInitialization:
    database_path: str
    table_count: int
    journal_event_count: int
    authority_evidence_unchanged: bool


def initialize_paper_storage(path: Path) -> PaperStorageInitialization:
    """Create empty M4 schema without enabling or adding broker authority."""
    if path.is_symlink():
        raise ValueError("paper execution database cannot be a symbolic link")
    before = _journal_count(path) if path.exists() else None
    RiskInputEvidenceStore(path)
    PaperSubmissionPreflightStore(path)
    PaperCancellationStore(path)
    PaperWriteActivationStore(path)
    CancelAllStore(path)
    SettledCapacityStore(path)
    journal = RiskStore(path).verify_journal()
    if before is not None and journal.event_count != before:
        raise JournalIntegrityError("paper storage initialization changed authority evidence")
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5) as connection:
        table_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
            ).fetchone()[0]
        )
    return PaperStorageInitialization(
        database_path=str(path.resolve()),
        table_count=table_count,
        journal_event_count=journal.event_count,
        authority_evidence_unchanged=before is None or journal.event_count == before,
    )


def assess_paper_startup(
    path: Path,
    settings: Settings,
    limits: RiskLimits,
    *,
    authorization_id: str,
    assessed_at: datetime,
    runtime_identity: InstalledRuntimeIdentity | None = None,
) -> PaperStartupAssessment:
    """Assess current authority and evidence without writing the execution database."""
    _utc(assessed_at)
    reasons: list[str] = []
    activation_id = (
        None if settings.paper_write_request is None else settings.paper_write_request.activation_id
    )
    emergency_disabled: bool | None = None
    submission_unknown_count: int | None = None
    unresolved_cancellation_count: int | None = None

    if settings.mode is not TradingMode.PAPER:
        reasons.append("paper-mode-required")
    if settings.paper_write_request is None:
        reasons.append("process-opt-in-missing")
    if runtime_identity is None:
        reasons.append("runtime-identity-unverified")
    if not settings.broker_writes_allowed:
        reasons.append("runtime-broker-writes-disabled")
    if assessed_at < limits.effective_at or assessed_at >= limits.expires_at:
        reasons.append("risk-configuration-inactive")
    if not path.is_file() or path.is_symlink():
        reasons.append("execution-database-missing-or-unsafe")
        return _assessment(
            reasons,
            authorization_id,
            limits,
            activation_id,
            runtime_identity,
            emergency_disabled,
            submission_unknown_count,
            unresolved_cancellation_count,
            assessed_at,
        )

    try:
        risk_store = _ReadOnlyRiskStore(path)
        authorization = risk_store.get_paper_authorization(authorization_id)
        emergency = risk_store.get_emergency()
        emergency_disabled = emergency.disabled
        if emergency.disabled:
            reasons.append("emergency-disabled")
        if (
            authorization.account_id != limits.account_id
            or authorization.risk_configuration_fingerprint != limits.configuration_fingerprint
        ):
            reasons.append("authorization-risk-mismatch")
        if not authorization.authorized_at <= assessed_at < authorization.expires_at:
            reasons.append("paper-authorization-inactive")
    except KeyError:
        reasons.append("paper-authorization-missing")
    except (JournalIntegrityError, sqlite3.DatabaseError):
        reasons.append("execution-database-integrity-failed")

    try:
        submission_unknown_count = len(_ReadOnlyBrokerEventStore(path).submission_unknown_orders())
        unresolved_cancellation_count = len(_ReadOnlyCancellationStore(path).unresolved())
        if submission_unknown_count or unresolved_cancellation_count:
            reasons.append("unresolved-mutation")
    except (JournalIntegrityError, sqlite3.DatabaseError):
        reasons.append("execution-state-incomplete")

    try:
        for symbol in limits.allowed_symbols:
            _ReadOnlyRiskContextStore(path).derive(
                authorization_id=authorization_id,
                symbol=symbol,
                limits=limits,
                evaluated_at=assessed_at,
            )
    except (JournalIntegrityError, sqlite3.DatabaseError):
        reasons.append("attested-risk-context-unavailable")

    if settings.paper_write_request is not None:
        try:
            activation_store = _ReadOnlyActivationStore(path)
            for operation in ("submit", "cancel"):
                assessment = activation_store.assess(
                    settings.paper_write_request,
                    limits,
                    operation=operation,
                    assessed_at=assessed_at,
                    runtime_identity=runtime_identity,
                )
                reasons.extend(f"{operation}:{reason}" for reason in assessment.reasons)
        except (JournalIntegrityError, KeyError, sqlite3.DatabaseError):
            reasons.append("activation-state-incomplete")

    return _assessment(
        reasons,
        authorization_id,
        limits,
        activation_id,
        runtime_identity,
        emergency_disabled,
        submission_unknown_count,
        unresolved_cancellation_count,
        assessed_at,
    )


class _ReadOnlyStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            f"{self.path.resolve().as_uri()}?mode=ro",
            uri=True,
            timeout=5,
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA query_only = ON")
        try:
            yield connection
        finally:
            connection.close()


class _ReadOnlyRiskStore(_ReadOnlyStore, RiskStore):
    pass


class _ReadOnlyBrokerEventStore(_ReadOnlyStore, BrokerEventStore):
    pass


class _ReadOnlyCancellationStore(_ReadOnlyStore, PaperCancellationStore):
    pass


class _ReadOnlyRiskContextStore(_ReadOnlyStore, AttestedRiskContextStore):
    pass


class _ReadOnlyActivationStore(_ReadOnlyStore, PaperWriteActivationStore):
    pass


def _assessment(
    reasons: list[str],
    authorization_id: str,
    limits: RiskLimits,
    activation_id: str | None,
    runtime_identity: InstalledRuntimeIdentity | None,
    emergency_disabled: bool | None,
    submission_unknown_count: int | None,
    unresolved_cancellation_count: int | None,
    assessed_at: datetime,
) -> PaperStartupAssessment:
    unique = tuple(dict.fromkeys(reasons))
    return PaperStartupAssessment(
        ready=not unique,
        reasons=unique,
        authorization_id=authorization_id,
        risk_configuration_fingerprint=limits.configuration_fingerprint,
        activation_id=activation_id,
        runtime_identity_fingerprint=(
            None if runtime_identity is None else runtime_identity.identity_fingerprint
        ),
        emergency_disabled=emergency_disabled,
        submission_unknown_count=submission_unknown_count,
        unresolved_cancellation_count=unresolved_cancellation_count,
        assessed_at=assessed_at,
    )


def _utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("paper startup assessment time must be UTC-aware")


def _journal_count(path: Path) -> int:
    try:
        with sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5
        ) as connection:
            row = connection.execute("SELECT COUNT(*) FROM journal").fetchone()
    except sqlite3.DatabaseError as error:
        raise JournalIntegrityError("execution database is unreadable") from error
    if row is None:
        raise JournalIntegrityError("execution journal is missing")
    return int(row[0])
