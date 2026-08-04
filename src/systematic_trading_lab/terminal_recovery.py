"""Narrow recovery for a false terminal-order replay emergency."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import cast

from .broker_events import BrokerEventStore, BrokerOrderEvent
from .execution import JournalIntegrityError
from .experiments import HoldoutAccessError
from .fingerprints import canonicalize, fingerprint
from .orders import OrderSide, OrderState, _decode_delta
from .reconciliation import ReconciliationStore
from .risk import EmergencyState, RiskLimits

_REPLAY_EMERGENCY_REASON = "broker event is out of order or exceeds order quantity"
_TERMINAL_STATES = {OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED}


@dataclass(frozen=True)
class TerminalReplayRecoveryProof:
    ready: bool
    reasons: tuple[str, ...]
    baseline_id: str
    authorization_id: str
    risk_configuration_fingerprint: str
    order_ids: tuple[str, ...]
    terminal_event_ids: tuple[str, ...]
    observed_snapshot_ids: tuple[str, ...]
    attestation_fingerprints: tuple[str, ...]
    expected_cash: Decimal
    emergency_generation: int
    assessed_at: datetime

    @property
    def proof_fingerprint(self) -> str:
        return fingerprint(self)


class TerminalReplayRecoveryStore(BrokerEventStore):
    """Clear only a proven unchanged-terminal replay false positive."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)

    def assess(
        self, *, baseline_id: str, limits: RiskLimits, assessed_at: datetime
    ) -> TerminalReplayRecoveryProof:
        _utc(assessed_at)
        with self._connect() as connection:
            connection.execute("BEGIN")
            return self._assess(
                connection,
                baseline_id=baseline_id,
                limits=limits,
                assessed_at=assessed_at,
            )

    def clear(
        self,
        *,
        clear_id: str,
        baseline_id: str,
        limits: RiskLimits,
        operator: str,
        reason: str,
        cleared_at: datetime,
    ) -> EmergencyState:
        for name, value in (("clear ID", clear_id), ("operator", operator), ("reason", reason)):
            if not value or value != value.strip() or len(value) > 500:
                raise ValueError(f"{name} is invalid")
        _utc(cleared_at)
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                emergency = self._verify_emergency(connection)
                prior = next(
                    (
                        json.loads(row[0])
                        for row in connection.execute(
                            "SELECT payload_json FROM journal "
                            "WHERE event_type = 'emergency-cleared'"
                        ).fetchall()
                        if json.loads(row[0]).get("clear_id") == clear_id
                    ),
                    None,
                )
                if prior is not None:
                    request = {
                        "clear_id": clear_id,
                        "baseline_id": baseline_id,
                        "operator": operator,
                        "reason": reason,
                        "cleared_at": _utc_text(cleared_at),
                    }
                    if any(prior.get(key) != value for key, value in request.items()):
                        raise JournalIntegrityError("clear ID is bound to different content")
                    connection.commit()
                    return emergency
                proof = self._assess(
                    connection,
                    baseline_id=baseline_id,
                    limits=limits,
                    assessed_at=cleared_at,
                )
                if not proof.ready:
                    raise HoldoutAccessError(
                        "terminal replay recovery requires complete stable evidence"
                    )
                new_generation = emergency.generation + 1
                payload = {
                    "clear_id": clear_id,
                    "baseline_id": baseline_id,
                    "authorization_id": proof.authorization_id,
                    "risk_configuration_fingerprint": limits.configuration_fingerprint,
                    "order_ids": proof.order_ids,
                    "terminal_event_ids": proof.terminal_event_ids,
                    "observed_snapshot_ids": proof.observed_snapshot_ids,
                    "attestation_fingerprints": proof.attestation_fingerprints,
                    "expected_cash": proof.expected_cash,
                    "proof_fingerprint": proof.proof_fingerprint,
                    "cause_fingerprint": proof.proof_fingerprint,
                    "disabled": False,
                    "generation": new_generation,
                    "reason": reason,
                    "operator": operator,
                    "changed_at": _utc_text(cleared_at),
                    "cleared_at": _utc_text(cleared_at),
                }
                sequence = self._append_event(
                    connection,
                    occurred_at=cleared_at,
                    event_type="emergency-cleared",
                    entity_type="emergency-state",
                    entity_id="global",
                    payload=canonicalize(payload),
                )
                updated = connection.execute(
                    "UPDATE emergency_state SET disabled = 0, generation = ?, reason = ?, "
                    "operator = ?, changed_at = ?, journal_sequence = ? "
                    "WHERE singleton = 1 AND generation = ? AND disabled = 1",
                    (
                        new_generation,
                        reason,
                        operator,
                        _utc_text(cleared_at),
                        sequence,
                        emergency.generation,
                    ),
                )
                if updated.rowcount != 1:
                    raise JournalIntegrityError("emergency state changed during recovery clear")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return EmergencyState(
            disabled=False,
            generation=new_generation,
            reason=reason,
            operator=operator,
            changed_at=cleared_at,
            journal_sequence=sequence,
        )

    def _assess(
        self,
        connection: sqlite3.Connection,
        *,
        baseline_id: str,
        limits: RiskLimits,
        assessed_at: datetime,
    ) -> TerminalReplayRecoveryProof:
        self._verify_connection(connection)
        self._verify_reservations(connection)
        self._verify_releases(connection)
        self._verify_orders(connection)
        events = self._verify_broker_events(connection)
        lookup_evidence = self._verify_lookup_found(connection, events)
        advances = self._verify_expected_position_advances(connection, events)
        snapshots, attestations, baselines, _ = ReconciliationStore._verify_reconciliation(
            cast(ReconciliationStore, self), connection
        )
        authorizations = self._verify_authorizations(connection)
        emergency = self._verify_emergency(connection)
        try:
            baseline = baselines[baseline_id]
            authorization = authorizations[baseline.authorization_id]
            initial_snapshot = snapshots[baseline.expected_snapshot_id]
        except KeyError as error:
            raise HoldoutAccessError("terminal recovery authority is missing") from error

        order_rows = connection.execute(
            "SELECT o.order_id, o.state, o.delta_json FROM orders o "
            "JOIN capacity_reservations r ON r.reservation_id = o.reservation_id "
            "WHERE r.authorization_id = ? ORDER BY o.order_id",
            (authorization.authorization_id,),
        ).fetchall()
        order_ids = tuple(str(row[0]) for row in order_rows)
        by_order = {
            order_id: sorted(
                (event for event in events.values() if event.client_order_id == order_id),
                key=lambda event: (event.provider_timestamp, event.event_id),
            )
            for order_id in order_ids
        }
        lookup_event_ids = {item.event_id for item in lookup_evidence.values()}
        terminal_events: list[BrokerOrderEvent] = []
        expected_cash = initial_snapshot.cash
        reasons: list[str] = []

        if not emergency.disabled:
            reasons.append("emergency-already-clear")
        elif emergency.reason != _REPLAY_EMERGENCY_REASON:
            reasons.append("emergency-reason-mismatch")
        if (
            authorization.account_id != limits.account_id
            or authorization.risk_configuration_fingerprint != limits.configuration_fingerprint
            or baseline.risk_configuration_fingerprint != limits.configuration_fingerprint
        ):
            reasons.append("authority-or-limits-mismatch")
        if not (
            limits.effective_at <= assessed_at < limits.expires_at
            and authorization.authorized_at <= assessed_at < authorization.expires_at
        ):
            reasons.append("authority-or-limits-inactive")
        if not order_rows or any(OrderState(row[1]) not in _TERMINAL_STATES for row in order_rows):
            reasons.append("orders-not-terminal")

        for order_id, state, delta_json in order_rows:
            ordered = by_order[str(order_id)]
            if not ordered:
                reasons.append("terminal-event-missing")
                continue
            latest = ordered[-1]
            terminal_events.append(latest)
            matching = [
                event
                for event in ordered
                if _terminal_facts(event) == _terminal_facts(latest)
                and event.event_id in lookup_event_ids
            ]
            if (
                OrderState(state) != latest.state
                or latest.state not in _TERMINAL_STATES
                or len(matching) < 2
                or matching[-1].observed_at <= emergency.changed_at
            ):
                reasons.append("unchanged-terminal-replay-unproved")
            delta = _decode_delta(json.loads(str(delta_json)))
            notional = Decimal(latest.cumulative_filled_quantity) * (
                latest.cumulative_average_fill_price or Decimal(0)
            )
            expected_cash += notional if delta.side is OrderSide.SELL else -notional

        lineage = [item for item in advances.values() if item.baseline_id == baseline_id]
        expected_positions = () if not lineage else lineage[-1].positions
        if not terminal_events or not any(
            event.cumulative_filled_quantity > 0 for event in terminal_events
        ):
            reasons.append("positive-fill-missing")
        if any(event.cumulative_filled_quantity > 0 for event in terminal_events) and not lineage:
            reasons.append("expected-position-lineage-missing")
        candidates = sorted(
            (
                (attestation.completed_at, snapshot, attestation.attestation_fingerprint)
                for snapshot_id, attestation in attestations.items()
                if (snapshot := snapshots[snapshot_id]).account_observed_at > emergency.changed_at
            ),
            key=lambda item: (item[0], item[1].snapshot_id),
        )[-3:]
        if len(candidates) < 3:
            reasons.append("insufficient-stable-snapshots")
        else:
            completion_times = tuple(item[0] for item in candidates)
            if any(
                (later - earlier).total_seconds() < limits.min_reconciliation_stability_seconds
                for earlier, later in pairwise(completion_times)
            ):
                reasons.append("snapshots-not-stable")
            if any(
                snapshot.account_id != limits.account_id
                or not snapshot.account_ready
                or snapshot.positions != expected_positions
                or snapshot.open_orders
                or snapshot.cash != expected_cash
                or any(
                    observed <= emergency.changed_at
                    for observed in (
                        snapshot.account_observed_at,
                        snapshot.positions_observed_at,
                        snapshot.orders_observed_at,
                    )
                )
                for _, snapshot, _ in candidates
            ):
                reasons.append("snapshot-state-mismatch")
            latest_snapshot = candidates[-1][1]
            if any(
                observed > assessed_at
                or (assessed_at - observed).total_seconds() > limits.max_snapshot_age_seconds
                for observed in (
                    latest_snapshot.account_observed_at,
                    latest_snapshot.positions_observed_at,
                    latest_snapshot.orders_observed_at,
                )
            ):
                reasons.append("latest-snapshot-stale-or-future")

        unique = tuple(dict.fromkeys(reasons))
        return TerminalReplayRecoveryProof(
            ready=not unique,
            reasons=unique,
            baseline_id=baseline_id,
            authorization_id=authorization.authorization_id,
            risk_configuration_fingerprint=limits.configuration_fingerprint,
            order_ids=order_ids,
            terminal_event_ids=tuple(event.event_id for event in terminal_events),
            observed_snapshot_ids=tuple(item[1].snapshot_id for item in candidates),
            attestation_fingerprints=tuple(item[2] for item in candidates),
            expected_cash=expected_cash,
            emergency_generation=emergency.generation,
            assessed_at=assessed_at,
        )


def _terminal_facts(event: BrokerOrderEvent) -> tuple[object, ...]:
    return (
        event.broker_order_id,
        event.client_order_id,
        event.state,
        event.cumulative_filled_quantity,
        event.cumulative_average_fill_price,
        event.provider_timestamp,
    )


def _utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("terminal recovery time must be UTC-aware")


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
