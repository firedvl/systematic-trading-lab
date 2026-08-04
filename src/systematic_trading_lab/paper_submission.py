"""Transaction-bound paper submission preflight without broker I/O."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from .alpaca_paper import PAPER_ORIGIN
from .domain import TradingMode
from .execution import JournalIntegrityError
from .fingerprints import canonical_json, canonicalize, fingerprint
from .orders import OrderState, _decode_delta, build_order_delta
from .risk import RiskLimits, evaluate_risk
from .risk_context import AttestedRiskContextStore


@dataclass(frozen=True)
class PaperSubmissionPreflight:
    order_id: str
    reservation_id: str
    decision_id: str
    authorization_id: str
    intent_fingerprint: str
    order_delta_fingerprint: str
    risk_limits_fingerprint: str
    attested_context_proof_fingerprint: str
    reevaluated_risk_fingerprint: str
    submitter_id: str
    paper_origin: str
    claimed_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("order ID", self.order_id),
            ("reservation ID", self.reservation_id),
            ("decision ID", self.decision_id),
            ("authorization ID", self.authorization_id),
            ("submitter ID", self.submitter_id),
        ):
            if not value or value != value.strip() or len(value) > 128:
                raise ValueError(f"{name} is invalid")
        for name, value in (
            ("intent", self.intent_fingerprint),
            ("order delta", self.order_delta_fingerprint),
            ("risk limits", self.risk_limits_fingerprint),
            ("attested context", self.attested_context_proof_fingerprint),
            ("reevaluated risk", self.reevaluated_risk_fingerprint),
        ):
            _sha256(name, value)
        if self.paper_origin != PAPER_ORIGIN:
            raise ValueError("paper submission origin is invalid")
        _utc(self.claimed_at)

    @property
    def proof_fingerprint(self) -> str:
        return fingerprint(self)


class PaperSubmissionPreflightStore(AttestedRiskContextStore):
    """Atomically recheck protected controls and claim one fake-adapter submission."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_submission_preflights (
                    order_id TEXT PRIMARY KEY REFERENCES orders(order_id),
                    proof_fingerprint TEXT NOT NULL UNIQUE,
                    proof_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS paper_submission_preflights_no_update
                BEFORE UPDATE ON paper_submission_preflights BEGIN
                    SELECT RAISE(ABORT, 'paper submission preflights are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS paper_submission_preflights_no_delete
                BEFORE DELETE ON paper_submission_preflights BEGIN
                    SELECT RAISE(ABORT, 'paper submission preflights are immutable');
                END;
                """
            )
            connection.commit()
            self._verify_preflights(connection)

    def claim(
        self,
        order_id: str,
        *,
        submitter_id: str,
        authorization_id: str,
        limits: RiskLimits,
        mode: TradingMode,
        paper_origin: str,
        claimed_at: datetime,
    ) -> PaperSubmissionPreflight:
        if mode is not TradingMode.PAPER or paper_origin != PAPER_ORIGIN:
            raise PermissionError("paper submission requires paper mode and the fixed paper origin")
        _utc(claimed_at)
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_connection(connection)
                self._verify_reservations(connection)
                self._verify_releases(connection)
                self._verify_orders(connection)
                self._verify_decisions(connection)
                self._verify_authorizations(connection)
                existing = self._verify_preflights(connection).get(order_id)
                if existing is not None:
                    if (
                        existing.submitter_id != submitter_id
                        or existing.authorization_id != authorization_id
                        or existing.risk_limits_fingerprint != limits.configuration_fingerprint
                        or existing.paper_origin != paper_origin
                        or existing.claimed_at != claimed_at
                    ):
                        raise JournalIntegrityError(
                            "order is bound to a different paper submission preflight"
                        )
                    connection.commit()
                    return existing
                row = connection.execute(
                    "SELECT o.reservation_id, o.delta_json, o.state, r.decision_id, "
                    "r.intent_id, r.authorization_id, r.reservation_json, d.decision_json "
                    "FROM orders o JOIN capacity_reservations r "
                    "ON r.reservation_id = o.reservation_id JOIN risk_decisions d "
                    "ON d.decision_id = r.decision_id WHERE o.order_id = ?",
                    (order_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(order_id)
                delta = _decode_delta(json.loads(row[1]))
                intent = self._read_intent(connection, str(row[4]))
                if OrderState(row[2]) is not OrderState.STAGED:
                    raise JournalIntegrityError("paper submission requires a staged order")
                if row[5] != authorization_id:
                    raise JournalIntegrityError("paper submission authorization is mismatched")
                if intent.target_quantity is None:
                    raise JournalIntegrityError(
                        "weight-target order submission requires a reviewed share-rounding rule"
                    )
                proof = self._derive(
                    connection,
                    authorization_id=authorization_id,
                    symbol=delta.symbol,
                    limits=limits,
                    evaluated_at=claimed_at,
                    exclude_intent_id=intent.idempotency_key,
                )
                expected = build_order_delta(
                    intent,
                    target_quantity=intent.target_quantity,
                    current_quantity=proof.context.current_symbol_quantity,
                    created_at=delta.created_at,
                )
                current_decision = evaluate_risk(intent, limits, proof.context)
                reservation = json.loads(row[6])
                stored_decision = json.loads(row[7])
                if (
                    expected != delta
                    or not current_decision.approved
                    or stored_decision.get("approved") is not True
                    or not stored_decision.get("context_provenance_fingerprint")
                    or current_decision.order_notional > Decimal(reservation["order_notional"])
                    or current_decision.cash_reservation > Decimal(reservation["cash"])
                    or current_decision.gross_exposure_reservation
                    > Decimal(reservation["gross_exposure"])
                ):
                    raise JournalIntegrityError(
                        "paper submission differs from its current risk authority"
                    )
                result = PaperSubmissionPreflight(
                    order_id=order_id,
                    reservation_id=str(row[0]),
                    decision_id=str(row[3]),
                    authorization_id=authorization_id,
                    intent_fingerprint=intent.intent_fingerprint,
                    order_delta_fingerprint=fingerprint(delta),
                    risk_limits_fingerprint=limits.configuration_fingerprint,
                    attested_context_proof_fingerprint=proof.proof_fingerprint,
                    reevaluated_risk_fingerprint=fingerprint(current_decision),
                    submitter_id=submitter_id,
                    paper_origin=paper_origin,
                    claimed_at=claimed_at,
                )
                claimed = self._claim_submitter(
                    connection,
                    order_id,
                    submitter_id,
                    claimed_at,
                    evidence=result,
                )
                if claimed.state is not OrderState.SUBMITTING:
                    raise JournalIntegrityError("paper submission claim did not enter submitting")
                sequence = connection.execute(
                    "SELECT journal_sequence FROM orders WHERE order_id = ?", (order_id,)
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO paper_submission_preflights VALUES (?, ?, ?, ?)",
                    (order_id, result.proof_fingerprint, canonical_json(result), sequence),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return result

    def _verify_preflights(
        self, connection: sqlite3.Connection
    ) -> dict[str, PaperSubmissionPreflight]:
        rows = connection.execute(
            "SELECT order_id, proof_fingerprint, proof_json, journal_sequence "
            "FROM paper_submission_preflights"
        ).fetchall()
        result: dict[str, PaperSubmissionPreflight] = {}
        for row in rows:
            try:
                proof = _decode_preflight(json.loads(row[2]))
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                raise JournalIntegrityError(
                    "stored paper submission preflight is invalid"
                ) from error
            order = connection.execute(
                "SELECT o.reservation_id, o.delta_json, o.submitter_id, o.claimed_at, "
                "r.decision_id, r.authorization_id, "
                "json_extract(r.reservation_json, '$.configuration_fingerprint'), "
                "i.intent_fingerprint FROM orders o JOIN capacity_reservations r "
                "ON r.reservation_id = o.reservation_id JOIN intents i "
                "ON i.idempotency_key = r.intent_id WHERE o.order_id = ?",
                (proof.order_id,),
            ).fetchone()
            journal = connection.execute(
                "SELECT event_type, entity_type, entity_id, payload_json FROM journal "
                "WHERE sequence = ?",
                (row[3],),
            ).fetchone()
            try:
                payload = json.loads(journal[3]) if journal is not None else None
            except json.JSONDecodeError:
                payload = None
            if (
                row[0] != proof.order_id
                or row[1] != proof.proof_fingerprint
                or row[2] != canonical_json(proof)
                or order is None
                or order[0] != proof.reservation_id
                or fingerprint(_decode_delta(json.loads(order[1]))) != proof.order_delta_fingerprint
                or order[2:]
                != (
                    proof.submitter_id,
                    _utc_text(proof.claimed_at),
                    proof.decision_id,
                    proof.authorization_id,
                    proof.risk_limits_fingerprint,
                    proof.intent_fingerprint,
                )
                or journal is None
                or journal[:3] != ("order-submitter-claimed", "order", proof.order_id)
                or not isinstance(payload, dict)
                or payload.get("submission_preflight") != canonicalize(proof)
            ):
                raise JournalIntegrityError(
                    "paper submission preflight differs from its order claim"
                )
            result[proof.order_id] = proof
        return result


def _decode_preflight(value: object) -> PaperSubmissionPreflight:
    if not isinstance(value, dict):
        raise ValueError("paper submission preflight must be an object")
    try:
        return PaperSubmissionPreflight(
            **{
                **value,
                "claimed_at": datetime.fromisoformat(
                    str(value["claimed_at"]).replace("Z", "+00:00")
                ),
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("paper submission preflight is invalid") from error


def _utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("paper submission time must be UTC-aware")


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _sha256(name: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} fingerprint is invalid")
