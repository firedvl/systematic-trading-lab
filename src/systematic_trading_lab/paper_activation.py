"""Dormant multi-control authority records for future paper broker writes."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .alpaca_paper import PAPER_ORIGIN
from .config import PaperWriteRequest
from .execution import JournalIntegrityError
from .fingerprints import canonical_json, canonicalize, fingerprint
from .risk import RiskLimits, RiskStore


@dataclass(frozen=True)
class PaperWriteActivation:
    authorization_id: str
    authorization_fingerprint: str
    risk_configuration_fingerprint: str
    account_id: str
    code_commit: str
    paper_origin: str
    operations: tuple[str, ...]
    approved_by: str
    operator: str
    reason: str
    max_attempts: int
    emergency_generation: int
    starts_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for name, value, limit in (
            ("authorization ID", self.authorization_id, 128),
            ("account ID", self.account_id, 128),
            ("code commit", self.code_commit, 128),
            ("approver", self.approved_by, 128),
            ("operator", self.operator, 128),
            ("reason", self.reason, 500),
        ):
            if not value or value != value.strip() or len(value) > limit:
                raise ValueError(f"{name} is invalid")
        _sha256("authorization", self.authorization_fingerprint)
        _sha256("risk configuration", self.risk_configuration_fingerprint)
        if self.paper_origin != PAPER_ORIGIN:
            raise ValueError("paper activation origin is invalid")
        if (
            self.operations != tuple(sorted(set(self.operations)))
            or not self.operations
            or any(value not in {"cancel", "submit"} for value in self.operations)
        ):
            raise ValueError("paper activation operations are invalid")
        if self.approved_by == self.operator:
            raise ValueError("paper activation approver and operator must differ")
        if isinstance(self.max_attempts, bool) or self.max_attempts < 1:
            raise ValueError("paper activation attempt limit must be positive")
        if isinstance(self.emergency_generation, bool) or self.emergency_generation < 1:
            raise ValueError("paper activation emergency generation must be positive")
        _utc(self.starts_at)
        _utc(self.expires_at)
        if self.expires_at <= self.starts_at:
            raise ValueError("paper activation expiry must follow its start")

    @property
    def activation_id(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class PaperWriteRevocation:
    activation_id: str
    operator: str
    reason: str
    revoked_at: datetime

    def __post_init__(self) -> None:
        _sha256("activation", self.activation_id)
        for name, value, limit in (
            ("operator", self.operator, 128),
            ("reason", self.reason, 500),
        ):
            if not value or value != value.strip() or len(value) > limit:
                raise ValueError(f"revocation {name} is invalid")
        _utc(self.revoked_at)

    @property
    def revocation_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class PaperWriteAssessment:
    eligible: bool
    reasons: tuple[str, ...]
    activation_id: str
    operation: str
    attempts_used: int
    max_attempts: int
    assessed_at: datetime

    def __post_init__(self) -> None:
        if self.eligible != (not self.reasons):
            raise ValueError("paper write eligibility must match its reasons")
        _sha256("activation", self.activation_id)
        if self.operation not in {"cancel", "submit"}:
            raise ValueError("paper write operation is invalid")
        if self.attempts_used < 0 or self.max_attempts < 1:
            raise ValueError("paper write attempt counts are invalid")
        _utc(self.assessed_at)

    @property
    def assessment_fingerprint(self) -> str:
        return fingerprint(self)


class PaperWriteActivationStore(RiskStore):
    """Store activation evidence without exposing a broker transport."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_write_activations (
                    activation_id TEXT PRIMARY KEY,
                    activation_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TABLE IF NOT EXISTS paper_write_revocations (
                    activation_id TEXT PRIMARY KEY
                        REFERENCES paper_write_activations(activation_id),
                    revocation_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS paper_write_activations_no_update
                BEFORE UPDATE ON paper_write_activations BEGIN
                    SELECT RAISE(ABORT, 'paper write activations are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS paper_write_activations_no_delete
                BEFORE DELETE ON paper_write_activations BEGIN
                    SELECT RAISE(ABORT, 'paper write activations are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS paper_write_revocations_no_update
                BEFORE UPDATE ON paper_write_revocations BEGIN
                    SELECT RAISE(ABORT, 'paper write revocations are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS paper_write_revocations_no_delete
                BEFORE DELETE ON paper_write_revocations BEGIN
                    SELECT RAISE(ABORT, 'paper write revocations are immutable');
                END;
                """
            )
            connection.commit()
            self._verify_activation_state(connection)

    def activate(
        self, activation: PaperWriteActivation, limits: RiskLimits
    ) -> PaperWriteActivation:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._verify_connection(connection)
            emergency = self._verify_emergency(connection)
            authorizations = self._verify_authorizations(connection)
            activations, _ = self._verify_activation_state(connection)
            authorization = authorizations.get(activation.authorization_id)
            if (
                authorization is None
                or authorization.authorization_fingerprint != activation.authorization_fingerprint
                or authorization.risk_configuration_fingerprint
                != activation.risk_configuration_fingerprint
                or activation.risk_configuration_fingerprint != limits.configuration_fingerprint
                or authorization.account_id != activation.account_id
                or limits.account_id != activation.account_id
                or authorization.code_commit != activation.code_commit
                or emergency.disabled
                or emergency.generation != activation.emergency_generation
                or activation.starts_at < authorization.authorized_at
                or activation.expires_at > authorization.expires_at
                or activation.starts_at < limits.effective_at
                or activation.expires_at > limits.expires_at
            ):
                raise JournalIntegrityError("paper write activation lacks exact current authority")
            existing = activations.get(activation.activation_id)
            if existing is not None:
                connection.commit()
                return existing
            sequence = self._append_event(
                connection,
                occurred_at=activation.starts_at,
                event_type="paper-write-activated",
                entity_type="paper-write-activation",
                entity_id=activation.activation_id,
                payload=canonicalize(activation),
            )
            connection.execute(
                "INSERT INTO paper_write_activations VALUES (?, ?, ?)",
                (activation.activation_id, canonical_json(activation), sequence),
            )
            connection.commit()
        return activation

    def revoke(self, revocation: PaperWriteRevocation) -> PaperWriteRevocation:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._verify_connection(connection)
            activations, revocations = self._verify_activation_state(connection)
            activation = activations.get(revocation.activation_id)
            if activation is None or revocation.revoked_at < activation.starts_at:
                raise JournalIntegrityError("paper write revocation lacks its activation")
            existing = revocations.get(revocation.activation_id)
            if existing is not None:
                if existing != revocation:
                    raise JournalIntegrityError("paper write activation has a different revocation")
                connection.commit()
                return existing
            sequence = self._append_event(
                connection,
                occurred_at=revocation.revoked_at,
                event_type="paper-write-revoked",
                entity_type="paper-write-revocation",
                entity_id=revocation.activation_id,
                payload=canonicalize(revocation),
            )
            connection.execute(
                "INSERT INTO paper_write_revocations VALUES (?, ?, ?)",
                (revocation.activation_id, canonical_json(revocation), sequence),
            )
            connection.commit()
        return revocation

    def assess(
        self,
        request: PaperWriteRequest,
        limits: RiskLimits,
        *,
        operation: str,
        assessed_at: datetime,
    ) -> PaperWriteAssessment:
        if operation not in {"cancel", "submit"}:
            raise ValueError("paper write operation is invalid")
        _utc(assessed_at)
        with self._connect() as connection:
            connection.execute("BEGIN")
            self._verify_connection(connection)
            emergency = self._verify_emergency(connection)
            authorizations = self._verify_authorizations(connection)
            activations, revocations = self._verify_activation_state(connection)
            try:
                activation = activations[request.activation_id]
                authorization = authorizations[activation.authorization_id]
            except KeyError:
                raise KeyError("paper write authority is missing") from None
        reasons = ["runtime-code-identity-unverified", "attempt-binding-absent"]
        if request.code_commit != activation.code_commit:
            reasons.append("code-commit-mismatch")
        if operation not in activation.operations:
            reasons.append("operation-not-authorized")
        if activation.activation_id in revocations:
            reasons.append("activation-revoked")
        if not activation.starts_at <= assessed_at < activation.expires_at:
            reasons.append("activation-inactive")
        if (
            authorization.authorization_fingerprint != activation.authorization_fingerprint
            or authorization.risk_configuration_fingerprint
            != activation.risk_configuration_fingerprint
            or limits.configuration_fingerprint != activation.risk_configuration_fingerprint
            or authorization.account_id != activation.account_id
            or limits.account_id != activation.account_id
            or not authorization.authorized_at <= assessed_at < authorization.expires_at
            or not limits.effective_at <= assessed_at < limits.expires_at
        ):
            reasons.append("authority-or-limits-mismatch")
        if emergency.disabled or emergency.generation != activation.emergency_generation:
            reasons.append("emergency-state-mismatch")
        unique = tuple(dict.fromkeys(reasons))
        return PaperWriteAssessment(
            eligible=not unique,
            reasons=unique,
            activation_id=activation.activation_id,
            operation=operation,
            attempts_used=0,
            max_attempts=activation.max_attempts,
            assessed_at=assessed_at,
        )

    def _verify_activation_state(
        self, connection: sqlite3.Connection
    ) -> tuple[dict[str, PaperWriteActivation], dict[str, PaperWriteRevocation]]:
        authorizations = self._verify_authorizations(connection)
        activation_rows = connection.execute(
            "SELECT activation_id, activation_json, journal_sequence FROM paper_write_activations"
        ).fetchall()
        if (
            len(activation_rows)
            != connection.execute(
                "SELECT COUNT(*) FROM journal WHERE event_type = 'paper-write-activated'"
            ).fetchone()[0]
        ):
            raise JournalIntegrityError("paper write activation and journal counts differ")
        activations: dict[str, PaperWriteActivation] = {}
        for row in activation_rows:
            try:
                activation_value = _decode_activation(json.loads(row[1]))
                authorization = authorizations[activation_value.authorization_id]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("stored paper write activation is invalid") from error
            journal = connection.execute(
                "SELECT occurred_at, event_type, entity_type, entity_id, payload_json "
                "FROM journal WHERE sequence = ?",
                (row[2],),
            ).fetchone()
            if (
                row[:2] != (activation_value.activation_id, canonical_json(activation_value))
                or authorization.authorization_fingerprint
                != activation_value.authorization_fingerprint
                or journal
                != (
                    _utc_text(activation_value.starts_at),
                    "paper-write-activated",
                    "paper-write-activation",
                    activation_value.activation_id,
                    canonical_json(activation_value),
                )
            ):
                raise JournalIntegrityError("paper write activation differs from its authority")
            activations[activation_value.activation_id] = activation_value
        revocation_rows = connection.execute(
            "SELECT activation_id, revocation_json, journal_sequence FROM paper_write_revocations"
        ).fetchall()
        if (
            len(revocation_rows)
            != connection.execute(
                "SELECT COUNT(*) FROM journal WHERE event_type = 'paper-write-revoked'"
            ).fetchone()[0]
        ):
            raise JournalIntegrityError("paper write revocation and journal counts differ")
        revocations: dict[str, PaperWriteRevocation] = {}
        for row in revocation_rows:
            try:
                revocation_value = _decode_revocation(json.loads(row[1]))
                activation = activations[revocation_value.activation_id]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("stored paper write revocation is invalid") from error
            journal = connection.execute(
                "SELECT occurred_at, event_type, entity_type, entity_id, payload_json "
                "FROM journal WHERE sequence = ?",
                (row[2],),
            ).fetchone()
            if (
                row[:2] != (revocation_value.activation_id, canonical_json(revocation_value))
                or revocation_value.revoked_at < activation.starts_at
                or journal
                != (
                    _utc_text(revocation_value.revoked_at),
                    "paper-write-revoked",
                    "paper-write-revocation",
                    revocation_value.activation_id,
                    canonical_json(revocation_value),
                )
            ):
                raise JournalIntegrityError("paper write revocation differs from its activation")
            revocations[revocation_value.activation_id] = revocation_value
        return activations, revocations


def _decode_activation(value: object) -> PaperWriteActivation:
    if not isinstance(value, dict):
        raise ValueError("paper write activation must be an object")
    return PaperWriteActivation(
        **{
            **value,
            "operations": tuple(value["operations"]),
            "starts_at": _parse_utc(str(value["starts_at"])),
            "expires_at": _parse_utc(str(value["expires_at"])),
        }
    )


def _decode_revocation(value: object) -> PaperWriteRevocation:
    if not isinstance(value, dict):
        raise ValueError("paper write revocation must be an object")
    return PaperWriteRevocation(**{**value, "revoked_at": _parse_utc(str(value["revoked_at"]))})


def _utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("paper write time must be UTC-aware")


def _parse_utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _utc(result)
    return result


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _sha256(name: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} fingerprint is invalid")
