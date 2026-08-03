"""Broker-free execution intents and append-only evidence."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .fingerprints import canonical_json, canonicalize, fingerprint

_SCHEMA_VERSION = "execution-intent-journal-v1"
_GENESIS_HASH = "0" * 64
_KNOWN_EVENT_TYPES = {
    "intent-recorded",
    "emergency-initialized",
    "emergency-cleared",
    "emergency-disabled",
    "paper-authorized",
    "risk-decided",
    "capacity-reserved",
    "capacity-released",
    "order-staged",
    "order-submitter-claimed",
    "order-transitioned",
    "broker-event-recorded",
    "expected-position-advanced",
    "position-settlement-proved",
    "order-lookup-not-found",
    "portfolio-snapshot-recorded",
    "paper-snapshot-attested",
    "reconciliation-baseline-created",
    "reconciliation-recorded",
}
_FINGERPRINT = re.compile(r"[0-9a-f]{64}")
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,15}")


class ExecutionStoreError(RuntimeError):
    pass


class DuplicateIntentError(ExecutionStoreError):
    pass


class JournalIntegrityError(ExecutionStoreError):
    pass


@dataclass(frozen=True)
class ExecutionIntent:
    idempotency_key: str
    strategy_id: str
    strategy_version: str
    symbol: str
    decision_timestamp: datetime
    target_weight: Decimal | None
    target_quantity: int | None
    reason: str
    source_data_fingerprint: str
    configuration_fingerprint: str
    reference_price: Decimal
    expires_at: datetime

    def __post_init__(self) -> None:
        _bounded("idempotency key", self.idempotency_key, 128)
        _bounded("strategy ID", self.strategy_id, 128)
        _bounded("strategy version", self.strategy_version, 128)
        _bounded("reason", self.reason, 500)
        if _SYMBOL.fullmatch(self.symbol) is None:
            raise ValueError("symbol must be an uppercase security identifier")
        _require_utc("decision timestamp", self.decision_timestamp)
        _require_utc("expiry", self.expires_at)
        if self.expires_at <= self.decision_timestamp:
            raise ValueError("intent expiry must follow its decision timestamp")
        if (self.target_weight is None) == (self.target_quantity is None):
            raise ValueError("intent requires exactly one target weight or quantity")
        if self.target_weight is not None and (
            not self.target_weight.is_finite() or self.target_weight < 0 or self.target_weight > 1
        ):
            raise ValueError("target weight must be finite and between zero and one")
        if self.target_quantity is not None and (
            isinstance(self.target_quantity, bool) or self.target_quantity < 0
        ):
            raise ValueError("target quantity must be a nonnegative whole share count")
        if not self.reference_price.is_finite() or self.reference_price <= 0:
            raise ValueError("reference price must be finite and positive")
        _require_fingerprint("source data", self.source_data_fingerprint)
        _require_fingerprint("configuration", self.configuration_fingerprint)

    @property
    def intent_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class IntentReceipt:
    idempotency_key: str
    intent_fingerprint: str
    received_at: datetime
    journal_sequence: int


@dataclass(frozen=True)
class JournalHead:
    event_count: int
    event_hash: str


class ExecutionStore:
    """Own immutable intent receipts and their hash-chained journal events."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        try:
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS journal (
                        sequence INTEGER PRIMARY KEY CHECK (sequence > 0),
                        occurred_at TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        entity_type TEXT NOT NULL,
                        entity_id TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        previous_hash TEXT NOT NULL,
                        event_hash TEXT NOT NULL UNIQUE
                    );
                    CREATE TABLE IF NOT EXISTS journal_head (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        event_count INTEGER NOT NULL CHECK (event_count >= 0),
                        event_hash TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS intents (
                        idempotency_key TEXT PRIMARY KEY,
                        intent_fingerprint TEXT NOT NULL UNIQUE,
                        intent_json TEXT NOT NULL,
                        configuration_fingerprint TEXT NOT NULL,
                        received_at TEXT NOT NULL,
                        journal_sequence INTEGER NOT NULL UNIQUE
                            REFERENCES journal(sequence)
                    );
                    CREATE TRIGGER IF NOT EXISTS intents_no_update
                    BEFORE UPDATE ON intents BEGIN
                        SELECT RAISE(ABORT, 'intents are immutable');
                    END;
                    CREATE TRIGGER IF NOT EXISTS intents_no_delete
                    BEFORE DELETE ON intents BEGIN
                        SELECT RAISE(ABORT, 'intents are immutable');
                    END;
                    CREATE TRIGGER IF NOT EXISTS journal_no_update
                    BEFORE UPDATE ON journal BEGIN
                        SELECT RAISE(ABORT, 'journal is append-only');
                    END;
                    CREATE TRIGGER IF NOT EXISTS journal_no_delete
                    BEFORE DELETE ON journal BEGIN
                        SELECT RAISE(ABORT, 'journal is append-only');
                    END;
                    """
                )
                connection.execute(
                    "INSERT OR IGNORE INTO metadata(key, value) VALUES ('schema_version', ?)",
                    (_SCHEMA_VERSION,),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO journal_head VALUES (1, 0, ?)", (_GENESIS_HASH,)
                )
                connection.commit()
                self._verify_connection(connection)
        except JournalIntegrityError:
            raise
        except sqlite3.DatabaseError as error:
            raise JournalIntegrityError("execution database is unreadable") from error

    def record_intent(
        self, intent: ExecutionIntent, *, received_at: datetime | None = None
    ) -> IntentReceipt:
        received = received_at or datetime.now(UTC)
        _require_utc("received timestamp", received)
        intent_json = canonical_json(intent)
        intent_hash = intent.intent_fingerprint
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_connection(connection)
                existing = connection.execute(
                    """
                    SELECT idempotency_key, intent_fingerprint, received_at, journal_sequence
                    FROM intents WHERE idempotency_key = ?
                    """,
                    (intent.idempotency_key,),
                ).fetchone()
                if existing is not None:
                    if existing[1] != intent_hash:
                        raise DuplicateIntentError(
                            "idempotency key is already bound to different intent content"
                        )
                    connection.commit()
                    return _receipt(existing)
                if received >= intent.expires_at:
                    raise ExecutionStoreError("cannot record an expired intent")

                occurred_at = _utc_text(received)
                sequence = self._append_event(
                    connection,
                    occurred_at=received,
                    event_type="intent-recorded",
                    entity_type="intent",
                    entity_id=intent.idempotency_key,
                    payload=json.loads(intent_json),
                )
                connection.execute(
                    "INSERT INTO intents VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        intent.idempotency_key,
                        intent_hash,
                        intent_json,
                        intent.configuration_fingerprint,
                        occurred_at,
                        sequence,
                    ),
                )
                connection.commit()
            except DuplicateIntentError:
                connection.rollback()
                raise
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise ExecutionStoreError("intent transaction violated an invariant") from error
            except Exception:
                connection.rollback()
                raise
        return IntentReceipt(intent.idempotency_key, intent_hash, received, sequence)

    def get_receipt(self, idempotency_key: str) -> IntentReceipt:
        _bounded("idempotency key", idempotency_key, 128)
        with self._connect() as connection:
            connection.execute("BEGIN")
            self._verify_connection(connection)
            row = connection.execute(
                """
                SELECT idempotency_key, intent_fingerprint, received_at, journal_sequence
                FROM intents WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
        if row is None:
            raise KeyError(idempotency_key)
        return _receipt(row)

    def get_intent(self, idempotency_key: str) -> ExecutionIntent:
        _bounded("idempotency key", idempotency_key, 128)
        with self._connect() as connection:
            connection.execute("BEGIN")
            self._verify_connection(connection)
            return self._read_intent(connection, idempotency_key)

    def _read_intent(self, connection: sqlite3.Connection, idempotency_key: str) -> ExecutionIntent:
        row = connection.execute(
            "SELECT intent_json FROM intents WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        if row is None:
            raise KeyError(idempotency_key)
        try:
            return _decode_intent(json.loads(row[0]))
        except json.JSONDecodeError as error:
            raise JournalIntegrityError("stored intent is not valid JSON") from error

    def verify_journal(self) -> JournalHead:
        try:
            with self._connect() as connection:
                return self._verify_connection(connection)
        except sqlite3.DatabaseError as error:
            raise JournalIntegrityError("execution database is unreadable") from error

    def _verify_connection(self, connection: sqlite3.Connection) -> JournalHead:
        check = connection.execute("PRAGMA quick_check").fetchone()
        if check is None or check[0] != "ok":
            raise JournalIntegrityError("execution database integrity check failed")
        version = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        if version is None or version[0] != _SCHEMA_VERSION:
            raise JournalIntegrityError("unsupported execution database schema")
        rows = connection.execute(
            """
            SELECT sequence, occurred_at, event_type, entity_type, entity_id,
                   payload_json, previous_hash, event_hash
            FROM journal ORDER BY sequence
            """
        ).fetchall()
        previous_hash = _GENESIS_HASH
        for expected_sequence, row in enumerate(rows, start=1):
            try:
                payload: Any = json.loads(row[5])
                canonical_payload = canonical_json(payload)
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                raise JournalIntegrityError("journal payload is not canonical JSON") from error
            expected_hash = _event_hash(
                sequence=expected_sequence,
                occurred_at=str(row[1]),
                event_type=str(row[2]),
                entity_type=str(row[3]),
                entity_id=str(row[4]),
                payload=payload,
                previous_hash=previous_hash,
            )
            if (
                row[0] != expected_sequence
                or row[2] not in _KNOWN_EVENT_TYPES
                or row[5] != canonical_payload
                or row[6] != previous_hash
                or row[7] != expected_hash
            ):
                raise JournalIntegrityError("journal sequence or hash chain is invalid")
            previous_hash = str(row[7])

        intent_event_count = connection.execute(
            "SELECT COUNT(*) FROM journal WHERE event_type = 'intent-recorded'"
        ).fetchone()[0]
        intents = connection.execute(
            """
            SELECT i.idempotency_key, i.intent_fingerprint, i.intent_json,
                   i.configuration_fingerprint, i.received_at, i.journal_sequence,
                   j.occurred_at, j.event_type, j.entity_type, j.entity_id, j.payload_json
            FROM intents i LEFT JOIN journal j ON j.sequence = i.journal_sequence
            """
        ).fetchall()
        if len(intents) != intent_event_count:
            raise JournalIntegrityError("intent and journal event counts differ")
        for row in intents:
            try:
                raw_payload: Any = json.loads(row[2])
            except json.JSONDecodeError as error:
                raise JournalIntegrityError("stored intent is not valid JSON") from error
            stored_intent = _decode_intent(raw_payload)
            payload = canonicalize(stored_intent)
            if (
                row[2] != canonical_json(payload)
                or row[1] != stored_intent.intent_fingerprint
                or stored_intent.idempotency_key != row[0]
                or stored_intent.configuration_fingerprint != row[3]
                or row[4] != row[6]
                or row[7] != "intent-recorded"
                or row[8] != "intent"
                or row[9] != row[0]
                or row[10] != row[2]
            ):
                raise JournalIntegrityError("intent receipt does not match its journal event")
        stored_head = connection.execute(
            "SELECT event_count, event_hash FROM journal_head WHERE singleton = 1"
        ).fetchone()
        if stored_head is None or stored_head[0] != len(rows) or stored_head[1] != previous_hash:
            raise JournalIntegrityError("stored journal head does not match the hash chain")
        return JournalHead(len(rows), previous_hash)

    def _append_event(
        self,
        connection: sqlite3.Connection,
        *,
        occurred_at: datetime,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: Any,
    ) -> int:
        previous = connection.execute(
            "SELECT sequence, event_hash FROM journal ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        sequence = 1 if previous is None else int(previous[0]) + 1
        previous_hash = _GENESIS_HASH if previous is None else str(previous[1])
        occurred_at_text = _utc_text(occurred_at)
        payload_json = canonical_json(payload)
        event_hash = _event_hash(
            sequence=sequence,
            occurred_at=occurred_at_text,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=json.loads(payload_json),
            previous_hash=previous_hash,
        )
        connection.execute(
            "INSERT INTO journal VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sequence,
                occurred_at_text,
                event_type,
                entity_type,
                entity_id,
                payload_json,
                previous_hash,
                event_hash,
            ),
        )
        connection.execute(
            "UPDATE journal_head SET event_count = ?, event_hash = ? WHERE singleton = 1",
            (sequence, event_hash),
        )
        return sequence

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        finally:
            connection.close()


def _event_hash(
    *,
    sequence: int,
    occurred_at: str,
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload: Any,
    previous_hash: str,
) -> str:
    return fingerprint(
        {
            "schema_version": _SCHEMA_VERSION,
            "sequence": sequence,
            "occurred_at": occurred_at,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "payload": canonicalize(payload),
            "previous_hash": previous_hash,
        }
    )


def _receipt(row: tuple[Any, ...]) -> IntentReceipt:
    return IntentReceipt(str(row[0]), str(row[1]), _parse_utc(str(row[2])), int(row[3]))


def _decode_intent(value: Any) -> ExecutionIntent:
    fields = {
        "idempotency_key",
        "strategy_id",
        "strategy_version",
        "symbol",
        "decision_timestamp",
        "target_weight",
        "target_quantity",
        "reason",
        "source_data_fingerprint",
        "configuration_fingerprint",
        "reference_price",
        "expires_at",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise JournalIntegrityError("stored intent has an unsupported schema")
    string_fields = fields - {"target_weight", "target_quantity"}
    if any(not isinstance(value[field], str) for field in string_fields):
        raise JournalIntegrityError("stored intent has an invalid field type")
    quantity = value["target_quantity"]
    if quantity is not None and (not isinstance(quantity, int) or isinstance(quantity, bool)):
        raise JournalIntegrityError("stored intent has an invalid quantity")
    weight = value["target_weight"]
    if weight is not None and not isinstance(weight, str):
        raise JournalIntegrityError("stored intent has an invalid target weight")
    try:
        return ExecutionIntent(
            idempotency_key=value["idempotency_key"],
            strategy_id=value["strategy_id"],
            strategy_version=value["strategy_version"],
            symbol=value["symbol"],
            decision_timestamp=_parse_utc(value["decision_timestamp"]),
            target_weight=None if weight is None else Decimal(weight),
            target_quantity=quantity,
            reason=value["reason"],
            source_data_fingerprint=value["source_data_fingerprint"],
            configuration_fingerprint=value["configuration_fingerprint"],
            reference_price=Decimal(value["reference_price"]),
            expires_at=_parse_utc(value["expires_at"]),
        )
    except (ValueError, ArithmeticError) as error:
        raise JournalIntegrityError("stored intent failed validation") from error


def _parse_utc(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require_utc("stored timestamp", timestamp)
    return timestamp


def _utc_text(value: datetime) -> str:
    result = canonicalize(value)
    assert isinstance(result, str)
    return result


def _bounded(name: str, value: str, maximum: int) -> None:
    if not value or value != value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be nonempty, trimmed, and at most {maximum} characters")


def _require_utc(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{name} must be UTC-aware")


def _require_fingerprint(name: str, value: str) -> None:
    if _FINGERPRINT.fullmatch(value) is None:
        raise ValueError(f"{name} fingerprint must be a lowercase SHA-256 value")
