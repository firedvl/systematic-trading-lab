"""Immutable proof that expected positions reached a later paper snapshot."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from .broker_events import BrokerEventStore, ExpectedPositionAdvance
from .execution import JournalIntegrityError
from .fingerprints import canonical_json, canonicalize, fingerprint
from .orders import OrderState
from .reconciliation import (
    ReconciliationStore,
    _decode_attestation,
    _decode_baseline,
    _decode_snapshot,
)

_TERMINAL_STATES = {OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED}


@dataclass(frozen=True)
class PositionSettlementEvidence:
    proof_id: str
    baseline_id: str
    authorization_id: str
    account_id: str
    risk_configuration_fingerprint: str
    advance_fingerprint: str
    observed_snapshot_id: str
    observed_snapshot_fingerprint: str
    attestation_fingerprint: str
    terminal_orders: tuple[tuple[str, str, int], ...]
    emergency_generation: int
    settled_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("proof ID", self.proof_id),
            ("baseline ID", self.baseline_id),
            ("authorization ID", self.authorization_id),
            ("account ID", self.account_id),
            ("observed snapshot ID", self.observed_snapshot_id),
        ):
            if not value or value != value.strip() or len(value) > 128:
                raise ValueError(f"{name} is invalid")
        for name, value in (
            ("risk configuration", self.risk_configuration_fingerprint),
            ("advance", self.advance_fingerprint),
            ("observed snapshot", self.observed_snapshot_fingerprint),
            ("paper attestation", self.attestation_fingerprint),
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{name} fingerprint is invalid")
        if self.emergency_generation < 1:
            raise ValueError("emergency generation must be positive")
        if (
            self.terminal_orders != tuple(sorted(self.terminal_orders, key=lambda item: item[0]))
            or len({item[0] for item in self.terminal_orders}) != len(self.terminal_orders)
            or any(
                not order_id
                or state not in {item.value for item in _TERMINAL_STATES}
                or sequence < 1
                for order_id, state, sequence in self.terminal_orders
            )
        ):
            raise ValueError("terminal order proof is invalid")
        if self.settled_at.tzinfo is None or self.settled_at.utcoffset() != UTC.utcoffset(
            self.settled_at
        ):
            raise ValueError("settlement time must be UTC-aware")

    @property
    def proof_fingerprint(self) -> str:
        return fingerprint(self)


class PositionSettlementStore(BrokerEventStore):
    """Prove position settlement without deriving account-wide accounting."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS position_settlement_evidence (
                    proof_id TEXT PRIMARY KEY,
                    baseline_id TEXT NOT NULL REFERENCES reconciliation_baselines(baseline_id),
                    advance_fingerprint TEXT NOT NULL,
                    observed_snapshot_id TEXT NOT NULL REFERENCES portfolio_snapshots(snapshot_id),
                    evidence_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS position_settlement_evidence_no_update
                BEFORE UPDATE ON position_settlement_evidence BEGIN
                    SELECT RAISE(ABORT, 'position settlement evidence is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS position_settlement_evidence_no_delete
                BEFORE DELETE ON position_settlement_evidence BEGIN
                    SELECT RAISE(ABORT, 'position settlement evidence is immutable');
                END;
                """
            )
            connection.commit()
            self._verify_settlements(connection)

    def record_settlement(
        self,
        *,
        proof_id: str,
        baseline_id: str,
        observed_snapshot_id: str,
        settled_at: datetime,
    ) -> PositionSettlementEvidence:
        if settled_at.tzinfo is None or settled_at.utcoffset() != UTC.utcoffset(settled_at):
            raise ValueError("settlement time must be UTC-aware")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._verify_connection(connection)
            self._verify_reservations(connection)
            self._verify_releases(connection)
            self._verify_orders(connection)
            events = self._verify_broker_events(connection)
            advances = self._verify_expected_position_advances(connection, events)
            settlements = self._verify_settlements(connection)
            snapshots, attestations, baselines, _ = ReconciliationStore._verify_reconciliation(
                cast(ReconciliationStore, self), connection
            )
            emergency = self._verify_emergency(connection)
            try:
                baseline = baselines[baseline_id]
                observed = snapshots[observed_snapshot_id]
                attestation = attestations[observed_snapshot_id]
                lineage = [item for item in advances.values() if item.baseline_id == baseline_id]
                advance = lineage[-1]
            except (KeyError, IndexError) as error:
                raise JournalIntegrityError("position settlement authority is missing") from error
            self._require_complete_lineage(
                connection,
                baseline=baseline,
                baseline_id=baseline_id,
                advances=advances,
            )
            observation_times = (
                observed.account_observed_at,
                observed.positions_observed_at,
                observed.orders_observed_at,
            )
            snapshot_recorded_at = connection.execute(
                "SELECT recorded_at FROM portfolio_snapshots WHERE snapshot_id = ?",
                (observed_snapshot_id,),
            ).fetchone()
            states = connection.execute(
                "SELECT o.order_id, o.state, o.changed_at, o.journal_sequence FROM orders o "
                "JOIN capacity_reservations r ON r.reservation_id = o.reservation_id "
                "WHERE json_extract(r.reservation_json, '$.account_id') = ?",
                (baseline.account_id,),
            ).fetchall()
            if (
                emergency.disabled
                or emergency.changed_at > advance.advanced_at
                or observed.account_id != baseline.account_id
                or observed.positions != advance.positions
                or observed.open_orders
                or not observed.account_ready
                or snapshot_recorded_at is None
                or any(OrderState(row[1]) not in _TERMINAL_STATES for row in states)
                or any(_parse_utc(str(row[2])) > observed.orders_observed_at for row in states)
                or any(timestamp < advance.advanced_at for timestamp in observation_times)
                or any(
                    timestamp > settled_at
                    or (settled_at - timestamp).total_seconds() > baseline.maximum_age_seconds
                    for timestamp in observation_times
                )
                or _parse_utc(str(snapshot_recorded_at[0])) > settled_at
            ):
                raise JournalIntegrityError("position settlement proof is not complete and current")
            evidence = PositionSettlementEvidence(
                proof_id=proof_id,
                baseline_id=baseline_id,
                authorization_id=baseline.authorization_id,
                account_id=baseline.account_id,
                risk_configuration_fingerprint=baseline.risk_configuration_fingerprint,
                advance_fingerprint=advance.advance_fingerprint,
                observed_snapshot_id=observed_snapshot_id,
                observed_snapshot_fingerprint=observed.snapshot_fingerprint,
                attestation_fingerprint=attestation.attestation_fingerprint,
                terminal_orders=tuple(
                    sorted((str(row[0]), str(row[1]), int(row[3])) for row in states)
                ),
                emergency_generation=emergency.generation,
                settled_at=settled_at,
            )
            existing = settlements.get(proof_id)
            if existing is not None:
                if existing != evidence:
                    raise JournalIntegrityError("settlement proof ID is bound to different content")
                connection.commit()
                return existing
            sequence = self._append_event(
                connection,
                occurred_at=settled_at,
                event_type="position-settlement-proved",
                entity_type="position-settlement",
                entity_id=proof_id,
                payload=canonicalize(evidence),
            )
            connection.execute(
                "INSERT INTO position_settlement_evidence VALUES (?, ?, ?, ?, ?, ?)",
                (
                    proof_id,
                    baseline_id,
                    advance.advance_fingerprint,
                    observed_snapshot_id,
                    canonical_json(evidence),
                    sequence,
                ),
            )
            connection.commit()
        return evidence

    def _verify_settlements(
        self, connection: sqlite3.Connection
    ) -> dict[str, PositionSettlementEvidence]:
        rows = connection.execute(
            "SELECT proof_id, baseline_id, advance_fingerprint, observed_snapshot_id, "
            "evidence_json, journal_sequence FROM position_settlement_evidence"
        ).fetchall()
        count = connection.execute(
            "SELECT COUNT(*) FROM journal WHERE event_type = 'position-settlement-proved'"
        ).fetchone()[0]
        if len(rows) != count:
            raise JournalIntegrityError("position settlement and journal counts differ")
        result: dict[str, PositionSettlementEvidence] = {}
        for row in rows:
            try:
                evidence = _decode_evidence(json.loads(row[4]))
                advance_row = connection.execute(
                    "SELECT advance_json, journal_sequence FROM expected_position_advances "
                    "WHERE advance_fingerprint = ? AND baseline_id = ?",
                    (evidence.advance_fingerprint, evidence.baseline_id),
                ).fetchone()
                snapshot_row = connection.execute(
                    "SELECT snapshot_json FROM portfolio_snapshots WHERE snapshot_id = ?",
                    (evidence.observed_snapshot_id,),
                ).fetchone()
                attestation_row = connection.execute(
                    "SELECT attestation_json FROM paper_snapshot_attestations "
                    "WHERE snapshot_id = ?",
                    (evidence.observed_snapshot_id,),
                ).fetchone()
                baseline_row = connection.execute(
                    "SELECT baseline_json FROM reconciliation_baselines WHERE baseline_id = ?",
                    (evidence.baseline_id,),
                ).fetchone()
                if (
                    advance_row is None
                    or snapshot_row is None
                    or attestation_row is None
                    or baseline_row is None
                ):
                    raise ValueError("settlement reference is missing")
                advance = _decode_advance(json.loads(advance_row[0]))
                snapshot = _decode_snapshot(json.loads(snapshot_row[0]))
                attestation = _decode_attestation(json.loads(attestation_row[0]))
                baseline = _decode_baseline(json.loads(baseline_row[0]))
            except (ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError("stored position settlement is invalid") from error
            payload = canonical_json(evidence)
            journal = connection.execute(
                "SELECT occurred_at, event_type, entity_type, entity_id, payload_json "
                "FROM journal WHERE sequence = ?",
                (row[5],),
            ).fetchone()
            later_advance = connection.execute(
                "SELECT 1 FROM expected_position_advances WHERE baseline_id = ? "
                "AND journal_sequence > ? AND journal_sequence < ? LIMIT 1",
                (evidence.baseline_id, advance_row[1], row[5]),
            ).fetchone()
            emergency_event = connection.execute(
                "SELECT occurred_at, payload_json FROM journal WHERE event_type IN "
                "('emergency-initialized', 'emergency-cleared', 'emergency-disabled') "
                "AND sequence < ? ORDER BY sequence DESC LIMIT 1",
                (row[5],),
            ).fetchone()
            emergency_payload = {} if emergency_event is None else json.loads(emergency_event[1])
            terminal_orders = _terminal_orders_at(
                connection,
                account_id=evidence.account_id,
                before_sequence=int(row[5]),
            )
            observation_times = (
                snapshot.account_observed_at,
                snapshot.positions_observed_at,
                snapshot.orders_observed_at,
            )
            if (
                row[:4]
                != (
                    evidence.proof_id,
                    evidence.baseline_id,
                    evidence.advance_fingerprint,
                    evidence.observed_snapshot_id,
                )
                or row[4] != payload
                or later_advance is not None
                or evidence.authorization_id != baseline.authorization_id
                or evidence.account_id != baseline.account_id
                or evidence.risk_configuration_fingerprint
                != baseline.risk_configuration_fingerprint
                or snapshot.account_id != evidence.account_id
                or snapshot.snapshot_fingerprint != evidence.observed_snapshot_fingerprint
                or snapshot.positions != advance.positions
                or snapshot.open_orders
                or not snapshot.account_ready
                or any(timestamp < advance.advanced_at for timestamp in observation_times)
                or any(
                    timestamp > evidence.settled_at
                    or (evidence.settled_at - timestamp).total_seconds()
                    > baseline.maximum_age_seconds
                    for timestamp in observation_times
                )
                or attestation.attestation_fingerprint != evidence.attestation_fingerprint
                or attestation.snapshot != snapshot
                or terminal_orders != evidence.terminal_orders
                or emergency_payload.get("disabled") is not False
                or emergency_payload.get("generation") != evidence.emergency_generation
                or emergency_event is None
                or _parse_utc(str(emergency_event[0])) > advance.advanced_at
                or journal
                != (
                    _utc_text(evidence.settled_at),
                    "position-settlement-proved",
                    "position-settlement",
                    evidence.proof_id,
                    payload,
                )
            ):
                raise JournalIntegrityError("position settlement does not match its evidence")
            result[evidence.proof_id] = evidence
        return result


def _decode_advance(value: object) -> ExpectedPositionAdvance:
    from .broker_events import _decode_expected_position_advance

    return _decode_expected_position_advance(value)


def _decode_evidence(value: object) -> PositionSettlementEvidence:
    if not isinstance(value, dict):
        raise ValueError("position settlement must be an object")
    try:
        return PositionSettlementEvidence(
            **{
                **value,
                "terminal_orders": tuple(tuple(item) for item in value["terminal_orders"]),
                "settled_at": _parse_utc(str(value["settled_at"])),
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("position settlement is invalid") from error


def _terminal_orders_at(
    connection: sqlite3.Connection, *, account_id: str, before_sequence: int
) -> tuple[tuple[str, str, int], ...]:
    order_ids = connection.execute(
        "SELECT o.order_id FROM orders o JOIN capacity_reservations r "
        "ON r.reservation_id = o.reservation_id "
        "WHERE json_extract(r.reservation_json, '$.account_id') = ?",
        (account_id,),
    ).fetchall()
    result: list[tuple[str, str, int]] = []
    for (order_id,) in order_ids:
        event = connection.execute(
            "SELECT sequence, event_type, payload_json FROM journal "
            "WHERE entity_type = 'order' AND entity_id = ? AND sequence < ? "
            "ORDER BY sequence DESC LIMIT 1",
            (order_id, before_sequence),
        ).fetchone()
        if event is None:
            continue
        payload = json.loads(event[2])
        state = (
            OrderState.STAGED
            if event[1] == "order-staged"
            else OrderState.SUBMITTING
            if event[1] == "order-submitter-claimed"
            else OrderState(payload["to_state"])
        )
        if state not in _TERMINAL_STATES:
            raise JournalIntegrityError("settlement proof contains a nonterminal local order")
        result.append((str(order_id), state.value, int(event[0])))
    return tuple(sorted(result))


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must be UTC-aware")
    return parsed


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
