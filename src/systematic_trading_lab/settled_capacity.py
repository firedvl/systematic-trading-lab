"""Atomic release of capacity already represented by settled broker positions."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .execution import JournalIntegrityError
from .fingerprints import canonical_json, canonicalize, fingerprint
from .risk import RiskLimits
from .risk_context import AttestedRiskContextStore


@dataclass(frozen=True)
class SettledCapacityRelease:
    release_id: str
    authorization_id: str
    settlement_proof_id: str
    symbol: str
    risk_limits_fingerprint: str
    settlement_proof_fingerprint: str
    attested_context_proof_fingerprint: str
    active_reservation_set_fingerprint: str
    reservation_ids: tuple[str, ...]
    released_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("authorization ID", self.authorization_id),
            ("settlement proof ID", self.settlement_proof_id),
            ("symbol", self.symbol),
        ):
            if not value or value != value.strip() or len(value) > 128:
                raise ValueError(f"{name} is invalid")
        for name, value in (
            ("release", self.release_id),
            ("risk limits", self.risk_limits_fingerprint),
            ("settlement proof", self.settlement_proof_fingerprint),
            ("attested context", self.attested_context_proof_fingerprint),
            ("active reservation set", self.active_reservation_set_fingerprint),
        ):
            _sha256(name, value)
        if not self.reservation_ids or self.reservation_ids != tuple(
            sorted(set(self.reservation_ids))
        ):
            raise ValueError("settled reservation IDs must be sorted and unique")
        if any(not value or value != value.strip() for value in self.reservation_ids):
            raise ValueError("settled reservation ID is invalid")
        _utc(self.released_at)


class SettledCapacityStore(AttestedRiskContextStore):
    """Replace settled pending capacity with current attested portfolio state."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS settled_capacity_releases (
                    release_id TEXT PRIMARY KEY,
                    settlement_proof_id TEXT NOT NULL UNIQUE
                        REFERENCES position_settlement_evidence(proof_id),
                    release_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS settled_capacity_releases_no_update
                BEFORE UPDATE ON settled_capacity_releases BEGIN
                    SELECT RAISE(ABORT, 'settled capacity releases are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS settled_capacity_releases_no_delete
                BEFORE DELETE ON settled_capacity_releases BEGIN
                    SELECT RAISE(ABORT, 'settled capacity releases are immutable');
                END;
                """
            )
            connection.commit()
            self._verify_settled_releases(connection)

    def release(
        self,
        *,
        authorization_id: str,
        settlement_proof_id: str,
        symbol: str,
        limits: RiskLimits,
        released_at: datetime,
    ) -> SettledCapacityRelease:
        _utc(released_at)
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = self._verify_settled_releases(connection).get(settlement_proof_id)
                if existing is not None:
                    if (
                        existing.authorization_id != authorization_id
                        or existing.symbol != symbol
                        or existing.risk_limits_fingerprint != limits.configuration_fingerprint
                        or existing.released_at != released_at
                    ):
                        raise JournalIntegrityError(
                            "settlement proof is bound to a different capacity release"
                        )
                    connection.commit()
                    return existing
                proof = self._derive(
                    connection,
                    authorization_id=authorization_id,
                    symbol=symbol,
                    limits=limits,
                    evaluated_at=released_at,
                    exclude_intent_id=None,
                )
                settlements = self._verify_settlements(connection)
                try:
                    settlement = settlements[settlement_proof_id]
                except KeyError:
                    raise JournalIntegrityError("settled capacity proof is missing") from None
                if (
                    settlement.authorization_id != authorization_id
                    or settlement.proof_fingerprint != proof.settlement_proof_fingerprint
                    or settlement.emergency_generation != proof.emergency_generation
                ):
                    raise JournalIntegrityError(
                        "settled capacity differs from the attested context"
                    )
                proof_row = connection.execute(
                    "SELECT journal_sequence FROM position_settlement_evidence WHERE proof_id = ?",
                    (settlement_proof_id,),
                ).fetchone()
                if proof_row is None:
                    raise JournalIntegrityError("settled capacity proof row is missing")
                terminal_order_ids = {item[0] for item in settlement.terminal_orders}
                rows = connection.execute(
                    "SELECT r.reservation_id, r.intent_id, r.expires_at, o.order_id, "
                    "x.reservation_id, COALESCE(MAX(CAST(json_extract(b.event_json, "
                    "'$.cumulative_filled_quantity') AS INTEGER)), 0) "
                    "FROM capacity_reservations r "
                    "LEFT JOIN orders o ON o.reservation_id = r.reservation_id "
                    "LEFT JOIN broker_events b ON b.client_order_id = o.order_id "
                    "LEFT JOIN capacity_releases x ON x.reservation_id = r.reservation_id "
                    "WHERE r.authorization_id = ? "
                    "GROUP BY r.reservation_id, r.intent_id, r.expires_at, o.order_id, "
                    "x.reservation_id",
                    (authorization_id,),
                ).fetchall()
                reservation_ids = tuple(
                    sorted(
                        str(row[0])
                        for row in rows
                        if row[3] in terminal_order_ids and int(row[5]) > 0 and row[4] is None
                    )
                )
                active = self._active_reservation_set(
                    connection, account_id=limits.account_id, at=released_at
                )
                later_order = connection.execute(
                    "SELECT 1 FROM journal j JOIN orders o ON o.order_id = j.entity_id "
                    "JOIN capacity_reservations r ON r.reservation_id = o.reservation_id "
                    "WHERE j.entity_type = 'order' AND j.sequence > ? "
                    "AND json_extract(r.reservation_json, '$.account_id') = ? LIMIT 1",
                    (int(proof_row[0]), limits.account_id),
                ).fetchone()
                if (
                    not reservation_ids
                    or active.reservation_ids != reservation_ids
                    or later_order is not None
                    or any(
                        row[0] in reservation_ids
                        and (
                            row[4] is not None
                            or datetime.fromisoformat(str(row[2]).replace("Z", "+00:00"))
                            <= released_at
                        )
                        for row in rows
                    )
                ):
                    raise JournalIntegrityError(
                        "settled capacity is not complete, current, and exclusive"
                    )
                release_id = fingerprint(
                    {
                        "authorization_id": authorization_id,
                        "symbol": symbol,
                        "risk_limits": limits.configuration_fingerprint,
                        "settlement_proof": settlement.proof_fingerprint,
                        "attested_context": proof.proof_fingerprint,
                        "reservation_ids": reservation_ids,
                        "released_at": released_at,
                    }
                )
                result = SettledCapacityRelease(
                    release_id=release_id,
                    authorization_id=authorization_id,
                    settlement_proof_id=settlement_proof_id,
                    symbol=symbol,
                    risk_limits_fingerprint=limits.configuration_fingerprint,
                    settlement_proof_fingerprint=settlement.proof_fingerprint,
                    attested_context_proof_fingerprint=proof.proof_fingerprint,
                    active_reservation_set_fingerprint=active.set_fingerprint,
                    reservation_ids=reservation_ids,
                    released_at=released_at,
                )
                reason = f"settled-position:{release_id}"
                for reservation_id in reservation_ids:
                    self._release_capacity(
                        connection,
                        reservation_id=reservation_id,
                        reason=reason,
                        released_at=released_at,
                    )
                sequence = self._append_event(
                    connection,
                    occurred_at=released_at,
                    event_type="settled-capacity-released",
                    entity_type="settled-capacity-release",
                    entity_id=release_id,
                    payload=canonicalize(result),
                )
                connection.execute(
                    "INSERT INTO settled_capacity_releases VALUES (?, ?, ?, ?)",
                    (
                        release_id,
                        settlement_proof_id,
                        canonical_json(result),
                        sequence,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return result

    def _verify_settled_releases(
        self, connection: sqlite3.Connection
    ) -> dict[str, SettledCapacityRelease]:
        self._verify_connection(connection)
        self._verify_releases(connection)
        settlements = self._verify_settlements(connection)
        rows = connection.execute(
            "SELECT release_id, settlement_proof_id, release_json, journal_sequence "
            "FROM settled_capacity_releases"
        ).fetchall()
        count = connection.execute(
            "SELECT COUNT(*) FROM journal WHERE event_type = 'settled-capacity-released'"
        ).fetchone()[0]
        if len(rows) != count:
            raise JournalIntegrityError("settled capacity release and journal counts differ")
        result: dict[str, SettledCapacityRelease] = {}
        for row in rows:
            try:
                release = _decode_release(json.loads(row[2]))
                settlement = settlements[release.settlement_proof_id]
            except (KeyError, ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("stored settled capacity release is invalid") from error
            journal = connection.execute(
                "SELECT occurred_at, event_type, entity_type, entity_id, payload_json "
                "FROM journal WHERE sequence = ?",
                (row[3],),
            ).fetchone()
            reason = f"settled-position:{release.release_id}"
            capacity_releases = connection.execute(
                "SELECT reservation_id, reason, released_at FROM capacity_releases "
                f"WHERE reservation_id IN ({','.join('?' for _ in release.reservation_ids)})",
                release.reservation_ids,
            ).fetchall()
            reservation_evidence = connection.execute(
                "SELECT r.reservation_id, r.authorization_id, o.order_id, "
                "COALESCE(MAX(CAST(json_extract(b.event_json, "
                "'$.cumulative_filled_quantity') AS INTEGER)), 0) "
                "FROM capacity_reservations r "
                "LEFT JOIN orders o ON o.reservation_id = r.reservation_id "
                "LEFT JOIN broker_events b ON b.client_order_id = o.order_id "
                f"WHERE r.reservation_id IN ({','.join('?' for _ in release.reservation_ids)}) "
                "GROUP BY r.reservation_id, r.authorization_id, o.order_id",
                release.reservation_ids,
            ).fetchall()
            terminal_order_ids = {item[0] for item in settlement.terminal_orders}
            expected_release_id = fingerprint(
                {
                    "authorization_id": release.authorization_id,
                    "symbol": release.symbol,
                    "risk_limits": release.risk_limits_fingerprint,
                    "settlement_proof": release.settlement_proof_fingerprint,
                    "attested_context": release.attested_context_proof_fingerprint,
                    "reservation_ids": release.reservation_ids,
                    "released_at": release.released_at,
                }
            )
            if (
                release.release_id != expected_release_id
                or row[0] != release.release_id
                or row[1] != release.settlement_proof_id
                or row[2] != canonical_json(release)
                or settlement.authorization_id != release.authorization_id
                or settlement.proof_fingerprint != release.settlement_proof_fingerprint
                or tuple(sorted(item[0] for item in capacity_releases)) != release.reservation_ids
                or tuple(sorted(item[0] for item in reservation_evidence))
                != release.reservation_ids
                or any(
                    item[1] != release.authorization_id
                    or item[2] not in terminal_order_ids
                    or int(item[3]) <= 0
                    for item in reservation_evidence
                )
                or any(
                    item[1:] != (reason, _utc_text(release.released_at))
                    for item in capacity_releases
                )
                or journal
                != (
                    _utc_text(release.released_at),
                    "settled-capacity-released",
                    "settled-capacity-release",
                    release.release_id,
                    canonical_json(release),
                )
            ):
                raise JournalIntegrityError("settled capacity release differs from its evidence")
            result[release.settlement_proof_id] = release
        return result


def _decode_release(value: object) -> SettledCapacityRelease:
    if not isinstance(value, dict):
        raise ValueError("settled capacity release must be an object")
    try:
        return SettledCapacityRelease(
            **{
                **value,
                "reservation_ids": tuple(value["reservation_ids"]),
                "released_at": datetime.fromisoformat(
                    str(value["released_at"]).replace("Z", "+00:00")
                ),
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("settled capacity release is invalid") from error


def _utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("settled capacity release time must be UTC-aware")


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _sha256(name: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} fingerprint is invalid")
