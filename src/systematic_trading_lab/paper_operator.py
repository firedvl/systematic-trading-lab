"""Disabled production coordinator for one-shot Alpaca paper mutations."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .alpaca_paper import PAPER_ORIGIN
from .alpaca_paper_transport import _urlopen_paper_mutation
from .broker_events import BrokerEventStore, BrokerOrderEvent
from .config import PaperWriteRequest, Settings
from .domain import TradingMode
from .execution import JournalIntegrityError
from .orders import OrderState, _decode_delta
from .paper_cancellation import (
    InjectedAlpacaPaperDelete,
    OrderCancellationAttempt,
    PaperCancellationStore,
)
from .paper_submission import InjectedAlpacaPaperPost, PaperSubmissionPreflightStore
from .risk import RiskLimits
from .runtime_build import InstalledRuntimeIdentity


class PaperOperatorError(RuntimeError):
    pass


class AlpacaPaperOperator:
    """Coordinate production paper calls after every durable authority check."""

    def __init__(
        self,
        path: Path,
        api_key: str,
        secret_key: str,
        *,
        settings: Settings,
        limits: RiskLimits,
        runtime_identity: InstalledRuntimeIdentity,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not settings.broker_writes_allowed:
            raise PermissionError("production paper broker writes are disabled")
        if (
            settings.mode is not TradingMode.PAPER
            or settings.paper_write_request is None
            or runtime_identity.source_commit != settings.paper_write_request.code_commit
        ):
            raise PermissionError("production paper broker authority is invalid")
        if (
            not api_key
            or api_key != api_key.strip()
            or not secret_key
            or secret_key != secret_key.strip()
        ):
            raise ValueError("Alpaca API credentials are required at the runtime boundary")
        self._path = path
        self._settings = settings
        self._limits = limits
        self._runtime_identity = runtime_identity
        self._clock = clock or (lambda: datetime.now(UTC))
        self._post = InjectedAlpacaPaperPost(
            api_key,
            secret_key,
            transport=_urlopen_paper_mutation,
            clock=self._clock,
        )
        self._delete = InjectedAlpacaPaperDelete(
            api_key,
            secret_key,
            transport=_urlopen_paper_mutation,
        )

    def submit(
        self,
        order_id: str,
        *,
        submitter_id: str,
        authorization_id: str,
        claimed_at: datetime,
        baseline_id: str | None = None,
    ) -> BrokerOrderEvent:
        request = self._require_enabled()
        self._require_current(claimed_at)
        store = PaperSubmissionPreflightStore(self._path)
        preflight, created = store._claim_once(
            order_id,
            submitter_id=submitter_id,
            authorization_id=authorization_id,
            limits=self._limits,
            mode=TradingMode.PAPER,
            paper_origin=PAPER_ORIGIN,
            claimed_at=claimed_at,
            paper_write_request=request,
            runtime_identity=self._runtime_identity,
        )
        if not created:
            raise PaperOperatorError(
                "paper submission was already attempted; reconcile before any retry"
            )
        with store._connect() as connection:
            row = connection.execute(
                "SELECT delta_json FROM orders WHERE order_id = ?", (order_id,)
            ).fetchone()
        if row is None:
            raise JournalIntegrityError("paper submission order disappeared after preflight")
        event: BrokerOrderEvent | None = None
        try:
            event = self._post(_decode_delta(json.loads(row[0])), preflight)
            if event.client_order_id != order_id or event.observed_at < claimed_at:
                raise ValueError("paper submission returned mismatched evidence")
            return BrokerEventStore(self._path).record(event, baseline_id=baseline_id)
        except Exception:
            failed_at = max(
                self._now(), claimed_at, claimed_at if event is None else event.observed_at
            )
            store.transition(order_id, OrderState.SUBMISSION_UNKNOWN, changed_at=failed_at)
            raise PaperOperatorError("paper submission outcome is unknown") from None

    def cancel(
        self,
        order_id: str,
        *,
        authorization_id: str,
        requester: str,
        reason: str,
        requested_at: datetime,
        expected_broker_event_fingerprint: str | None = None,
    ) -> OrderCancellationAttempt:
        request = self._require_enabled()
        self._require_current(requested_at)
        store = PaperCancellationStore(self._path)
        attempt, created = store._request_once(
            order_id,
            authorization_id=authorization_id,
            requester=requester,
            reason=reason,
            mode=TradingMode.PAPER,
            paper_origin=PAPER_ORIGIN,
            requested_at=requested_at,
            expected_broker_event_fingerprint=expected_broker_event_fingerprint,
            paper_write_request=request,
            limits=self._limits,
            runtime_identity=self._runtime_identity,
        )
        if not created:
            raise PaperOperatorError(
                "paper cancellation was already attempted; reconcile before any retry"
            )
        with store._connect() as connection:
            event = store._verify_broker_events(connection)[attempt.broker_event_id]
        try:
            self._delete(attempt, event)
        except Exception:
            store.mark_unknown(attempt.cancel_id, observed_at=max(self._now(), requested_at))
            raise PaperOperatorError("paper cancellation outcome is unknown") from None
        return attempt

    def _require_enabled(self) -> PaperWriteRequest:
        if not self._settings.broker_writes_allowed or self._settings.paper_write_request is None:
            raise PermissionError("production paper broker writes are disabled")
        return self._settings.paper_write_request

    def _require_current(self, attempted_at: datetime) -> None:
        if attempted_at.tzinfo is None or attempted_at.utcoffset() != UTC.utcoffset(attempted_at):
            raise PermissionError("paper mutation attempt time must be UTC-aware")
        now = self._now()
        if attempted_at > now or now - attempted_at > timedelta(seconds=1):
            raise PermissionError("paper mutation attempt time is stale or future-dated")

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise PaperOperatorError("paper operator clock must be UTC-aware")
        return value
