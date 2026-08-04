"""Deterministic cancel-all planning without bulk broker authority."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .alpaca_paper import PAPER_ORIGIN
from .broker_events import BrokerOrderEvent
from .domain import TradingMode
from .execution import JournalIntegrityError
from .fingerprints import canonical_json, canonicalize, fingerprint
from .orders import OrderState
from .paper_cancellation import (
    FakePaperCanceler,
    FakePaperCancellationAlreadyAttempted,
    FakePaperCancellationError,
    OrderCancellationAttempt,
    PaperCancellationIneligibleError,
    PaperCancellationStore,
    _latest_event,
)


@dataclass(frozen=True)
class CancelAllOrder:
    order_id: str
    broker_event_id: str
    broker_event_fingerprint: str
    order_state: OrderState

    def __post_init__(self) -> None:
        for name, value in (
            ("order ID", self.order_id),
            ("broker event ID", self.broker_event_id),
        ):
            if not value or value != value.strip() or len(value) > 128:
                raise ValueError(f"{name} is invalid")
        _sha256("broker event", self.broker_event_fingerprint)
        if self.order_state not in {OrderState.ACKNOWLEDGED, OrderState.PARTIALLY_FILLED}:
            raise ValueError("cancel-all order must be nonterminal")


@dataclass(frozen=True)
class CancelAllPlan:
    plan_id: str
    authorization_id: str
    orders: tuple[CancelAllOrder, ...]
    requester: str
    reason: str
    paper_origin: str
    planned_at: datetime

    def __post_init__(self) -> None:
        for name, value, limit in (
            ("plan ID", self.plan_id, 128),
            ("authorization ID", self.authorization_id, 128),
            ("requester", self.requester, 128),
            ("reason", self.reason, 500),
        ):
            if not value or value != value.strip() or len(value) > limit:
                raise ValueError(f"{name} is invalid")
        if self.orders != tuple(sorted(self.orders, key=lambda item: item.order_id)) or len(
            {item.order_id for item in self.orders}
        ) != len(self.orders):
            raise ValueError("cancel-all orders must be sorted and unique")
        if self.paper_origin != PAPER_ORIGIN:
            raise ValueError("cancel-all paper origin is invalid")
        _utc(self.planned_at)

    @property
    def plan_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class CancelAllOutcome:
    order_id: str
    status: str
    cancel_id: str | None

    def __post_init__(self) -> None:
        if not self.order_id or len(self.order_id) > 128:
            raise ValueError("cancel-all outcome order ID is invalid")
        if self.status not in {"accepted", "unknown", "prior-attempt", "stale"}:
            raise ValueError("cancel-all outcome status is invalid")
        if (self.cancel_id is None) != (self.status == "stale"):
            raise ValueError("cancel-all outcome cancel ID is invalid")
        if self.cancel_id is not None:
            _sha256("cancel", self.cancel_id)


class CancelAllStore(PaperCancellationStore):
    """Bind one exact local nonterminal-order set for separate cancellation attempts."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS cancel_all_plans (
                    plan_id TEXT PRIMARY KEY,
                    plan_fingerprint TEXT NOT NULL UNIQUE,
                    plan_json TEXT NOT NULL,
                    journal_sequence INTEGER NOT NULL UNIQUE REFERENCES journal(sequence)
                );
                CREATE TRIGGER IF NOT EXISTS cancel_all_plans_no_update
                BEFORE UPDATE ON cancel_all_plans BEGIN
                    SELECT RAISE(ABORT, 'cancel-all plans are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS cancel_all_plans_no_delete
                BEFORE DELETE ON cancel_all_plans BEGIN
                    SELECT RAISE(ABORT, 'cancel-all plans are immutable');
                END;
                """
            )
            connection.commit()
            events = self._verify_broker_events(connection)
            self._verify_plans(connection, events)

    def plan(
        self,
        plan_id: str,
        *,
        authorization_id: str,
        requester: str,
        reason: str,
        mode: TradingMode,
        paper_origin: str,
        planned_at: datetime,
    ) -> CancelAllPlan:
        if mode is not TradingMode.PAPER or paper_origin != PAPER_ORIGIN:
            raise PermissionError("cancel-all requires paper mode and the fixed paper origin")
        _utc(planned_at)
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_connection(connection)
                self._verify_orders(connection)
                authorizations = self._verify_authorizations(connection)
                events = self._verify_broker_events(connection)
                plans = self._verify_plans(connection, events)
                existing = plans.get(plan_id)
                if existing is not None:
                    if (
                        existing.authorization_id != authorization_id
                        or existing.requester != requester
                        or existing.reason != reason
                        or existing.paper_origin != paper_origin
                        or existing.planned_at != planned_at
                    ):
                        raise JournalIntegrityError("cancel-all plan ID has different content")
                    connection.commit()
                    return existing
                if authorization_id not in authorizations:
                    raise JournalIntegrityError("cancel-all authorization is missing")
                rows = connection.execute(
                    "SELECT o.order_id, o.state, o.changed_at FROM orders o "
                    "JOIN capacity_reservations r ON r.reservation_id = o.reservation_id "
                    "WHERE r.authorization_id = ? AND o.state IN (?, ?) ORDER BY o.order_id",
                    (
                        authorization_id,
                        OrderState.ACKNOWLEDGED,
                        OrderState.PARTIALLY_FILLED,
                    ),
                ).fetchall()
                orders: list[CancelAllOrder] = []
                for row in rows:
                    latest = _latest_event(events, str(row[0]))
                    state = OrderState(row[1])
                    if (
                        latest is None
                        or latest.state is not state
                        or planned_at < _parse_utc(str(row[2]))
                    ):
                        raise JournalIntegrityError(
                            "cancel-all order set is not complete and current"
                        )
                    orders.append(
                        CancelAllOrder(
                            order_id=str(row[0]),
                            broker_event_id=latest.event_id,
                            broker_event_fingerprint=latest.event_fingerprint,
                            order_state=state,
                        )
                    )
                result = CancelAllPlan(
                    plan_id=plan_id,
                    authorization_id=authorization_id,
                    orders=tuple(orders),
                    requester=requester,
                    reason=reason,
                    paper_origin=paper_origin,
                    planned_at=planned_at,
                )
                sequence = self._append_event(
                    connection,
                    occurred_at=planned_at,
                    event_type="cancel-all-planned",
                    entity_type="cancel-all-plan",
                    entity_id=plan_id,
                    payload=canonicalize(result),
                )
                connection.execute(
                    "INSERT INTO cancel_all_plans VALUES (?, ?, ?, ?)",
                    (plan_id, result.plan_fingerprint, canonical_json(result), sequence),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return result

    def _verify_plans(
        self, connection: sqlite3.Connection, events: dict[str, BrokerOrderEvent]
    ) -> dict[str, CancelAllPlan]:
        return _verify_plans(connection, events)


class FakeCancelAllCanceler:
    """Consume one plan through separate restart-safe fake cancellation attempts."""

    def __init__(
        self,
        path: Path,
        transport: Callable[[OrderCancellationAttempt, BrokerOrderEvent], None],
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._path = path
        self._transport = transport
        self._clock = clock

    def consume(self, plan_id: str) -> tuple[CancelAllOutcome, ...]:
        plan_store = CancelAllStore(self._path)
        with plan_store._connect() as connection:
            connection.execute("BEGIN")
            events = plan_store._verify_broker_events(connection)
            plans = plan_store._verify_plans(connection, events)
        try:
            plan = plans[plan_id]
        except KeyError:
            raise KeyError(plan_id) from None
        outcomes: list[CancelAllOutcome] = []
        for item in plan.orders:
            cancellation_store = PaperCancellationStore(self._path)
            with cancellation_store._connect() as connection:
                events = cancellation_store._verify_broker_events(connection)
                attempts = cancellation_store._verify_attempts(connection, events)
                order = connection.execute(
                    "SELECT state FROM orders WHERE order_id = ?", (item.order_id,)
                ).fetchone()
                latest = _latest_event(events, item.order_id)
            existing = next(
                (attempt for attempt in attempts.values() if attempt.order_id == item.order_id),
                None,
            )
            if existing is not None:
                outcomes.append(
                    CancelAllOutcome(item.order_id, "prior-attempt", existing.cancel_id)
                )
                continue
            if (
                order is None
                or OrderState(order[0])
                not in {OrderState.ACKNOWLEDGED, OrderState.PARTIALLY_FILLED}
                or latest is None
                or latest.event_id != item.broker_event_id
                or latest.event_fingerprint != item.broker_event_fingerprint
            ):
                outcomes.append(CancelAllOutcome(item.order_id, "stale", None))
                continue
            try:
                attempt = FakePaperCanceler(self._path, self._transport, clock=self._clock).cancel(
                    item.order_id,
                    authorization_id=plan.authorization_id,
                    requester=plan.requester,
                    reason=f"cancel-all:{plan.plan_id}:{plan.reason}",
                    requested_at=plan.planned_at,
                    expected_broker_event_fingerprint=item.broker_event_fingerprint,
                )
            except PaperCancellationIneligibleError:
                outcomes.append(CancelAllOutcome(item.order_id, "stale", None))
            except FakePaperCancellationAlreadyAttempted:
                with cancellation_store._connect() as connection:
                    events = cancellation_store._verify_broker_events(connection)
                    attempts = cancellation_store._verify_attempts(connection, events)
                attempt = next(
                    value for value in attempts.values() if value.order_id == item.order_id
                )
                outcomes.append(CancelAllOutcome(item.order_id, "prior-attempt", attempt.cancel_id))
            except FakePaperCancellationError:
                with cancellation_store._connect() as connection:
                    events = cancellation_store._verify_broker_events(connection)
                    attempts = cancellation_store._verify_attempts(connection, events)
                attempt = next(
                    value for value in attempts.values() if value.order_id == item.order_id
                )
                outcomes.append(CancelAllOutcome(item.order_id, "unknown", attempt.cancel_id))
            else:
                outcomes.append(CancelAllOutcome(item.order_id, "accepted", attempt.cancel_id))
        return tuple(outcomes)


def _verify_plans(
    connection: sqlite3.Connection,
    events: dict[str, BrokerOrderEvent],
) -> dict[str, CancelAllPlan]:
    rows = connection.execute(
        "SELECT plan_id, plan_fingerprint, plan_json, journal_sequence FROM cancel_all_plans"
    ).fetchall()
    count = connection.execute(
        "SELECT COUNT(*) FROM journal WHERE event_type = 'cancel-all-planned'"
    ).fetchone()[0]
    if len(rows) != count:
        raise JournalIntegrityError("cancel-all plan and journal counts differ")
    result: dict[str, CancelAllPlan] = {}
    for row in rows:
        try:
            plan = _decode_plan(json.loads(row[2]))
            bound_events = [events[item.broker_event_id] for item in plan.orders]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise JournalIntegrityError("stored cancel-all plan is invalid") from error
        journal = connection.execute(
            "SELECT occurred_at, event_type, entity_type, entity_id, payload_json "
            "FROM journal WHERE sequence = ?",
            (row[3],),
        ).fetchone()
        authorization = connection.execute(
            "SELECT 1 FROM paper_authorizations WHERE authorization_id = ?",
            (plan.authorization_id,),
        ).fetchone()
        if (
            row[0] != plan.plan_id
            or row[1] != plan.plan_fingerprint
            or row[2] != canonical_json(plan)
            or authorization is None
            or any(
                event.client_order_id != item.order_id
                or event.event_fingerprint != item.broker_event_fingerprint
                or event.state is not item.order_state
                or plan.planned_at < event.observed_at
                for item, event in zip(plan.orders, bound_events, strict=True)
            )
            or journal
            != (
                _utc_text(plan.planned_at),
                "cancel-all-planned",
                "cancel-all-plan",
                plan.plan_id,
                canonical_json(plan),
            )
        ):
            raise JournalIntegrityError("cancel-all plan differs from its order evidence")
        result[plan.plan_id] = plan
    return result


def _decode_plan(value: object) -> CancelAllPlan:
    if not isinstance(value, dict):
        raise ValueError("cancel-all plan must be an object")
    try:
        raw_orders = value["orders"]
        if not isinstance(raw_orders, list):
            raise ValueError("cancel-all orders must be a list")
        orders = tuple(
            CancelAllOrder(**{**item, "order_state": OrderState(item["order_state"])})
            for item in raw_orders
            if isinstance(item, dict)
        )
        if len(orders) != len(raw_orders):
            raise ValueError("cancel-all order is invalid")
        return CancelAllPlan(
            **{
                **value,
                "orders": orders,
                "planned_at": _parse_utc(str(value["planned_at"])),
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("cancel-all plan is invalid") from error


def _utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("cancel-all time must be UTC-aware")


def _parse_utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _utc(result)
    return result


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _sha256(name: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} fingerprint is invalid")
