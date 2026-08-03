"""Read-only, fixed-origin Alpaca paper account state."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from http.client import HTTPException
from typing import TYPE_CHECKING, Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .fingerprints import fingerprint
from .reconciliation import (
    OpenOrderSnapshot,
    PortfolioSnapshot,
    PositionSnapshot,
    SnapshotSource,
)

if TYPE_CHECKING:
    from .broker_events import BrokerEventStore, BrokerOrderEvent, OrderLookupNotFoundEvidence
    from .reconciliation import ReconciliationStore

PAPER_ORIGIN = "https://paper-api.alpaca.markets"
_ALLOWED_PATHS = frozenset(
    {"/v2/account", "/v2/positions", "/v2/orders", "/v2/orders:by_client_order_id", "/v2/clock"}
)
_OPEN_ORDER_STATUSES = frozenset(
    {
        "accepted",
        "accepted_for_bidding",
        "calculated",
        "done_for_day",
        "new",
        "partially_filled",
        "pending_cancel",
        "pending_new",
        "pending_replace",
        "pending_validation",
        "stopped",
        "suspended",
    }
)
_ORDER_STATUSES = _OPEN_ORDER_STATUSES | {"filled", "canceled", "expired", "rejected"}
_Transport = Callable[[Request], bytes]
_Clock = Callable[[], datetime]


class AlpacaPaperError(RuntimeError):
    """A sanitized paper-state read or validation failure."""


class _OrderLookupNotFound(AlpacaPaperError):
    pass


@dataclass(frozen=True)
class MarketClockSnapshot:
    observed_at: datetime
    provider_timestamp: datetime
    is_open: bool
    next_open: datetime
    next_close: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("clock observation", self.observed_at),
            ("provider timestamp", self.provider_timestamp),
            ("next open", self.next_open),
            ("next close", self.next_close),
        ):
            if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
                raise ValueError(f"{name} must be UTC-aware")
        if not isinstance(self.is_open, bool):
            raise ValueError("market-open state must be boolean")


@dataclass(frozen=True)
class PaperOrderSnapshot:
    broker_order_id: str
    client_order_id: str
    symbol: str
    side: str
    quantity: int
    filled_quantity: int
    order_type: str
    limit_price: Decimal | None
    status: str
    updated_at: datetime
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.side not in {"buy", "sell"} or self.order_type not in {"market", "limit"}:
            raise ValueError("paper order type or side is unsupported")
        if self.quantity < 1 or not 0 <= self.filled_quantity <= self.quantity:
            raise ValueError("paper order quantity is invalid")
        if self.status not in _ORDER_STATUSES:
            raise ValueError("paper order status is unsupported")
        if self.observed_at < self.updated_at:
            raise ValueError("paper order cannot be observed before its update time")


class AlpacaPaperReader:
    """Fetch normalized paper state without exposing any broker mutation."""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        *,
        account_id: str,
        allowed_symbols: frozenset[str],
        transport: _Transport | None = None,
        clock: _Clock | None = None,
    ) -> None:
        if not api_key or not secret_key:
            raise ValueError("Alpaca API credentials are required at the runtime boundary")
        if not account_id or account_id != account_id.strip() or len(account_id) > 128:
            raise ValueError("expected paper account ID is invalid")
        if not allowed_symbols:
            raise ValueError("at least one allowed paper symbol is required")
        for symbol in allowed_symbols:
            PositionSnapshot(symbol=symbol, quantity=0)
        self._api_key = api_key
        self._secret_key = secret_key
        self._account_id = account_id
        self._allowed_symbols = allowed_symbols
        self._allows_persistence = transport is None
        self._transport = transport or _urlopen_bytes
        self._clock = clock or (lambda: datetime.now(UTC))

    def read_portfolio(self) -> PortfolioSnapshot:
        account = self._get_object("/v2/account")
        account_observed_at = self._now()
        observed_account = _text(account, "id", "account")
        if observed_account != self._account_id:
            raise AlpacaPaperError("Alpaca paper response is for an unexpected account")
        cash = _amount(account, "cash")
        equity = _amount(account, "equity")
        buying_power = _amount(account, "buying_power")
        account_ready = _account_ready(account)

        position_values = self._get_list("/v2/positions")
        positions_observed_at = self._now()
        positions = tuple(
            sorted(
                (self._position(value) for value in position_values),
                key=lambda item: item.symbol,
            )
        )

        order_values = self._get_list(
            "/v2/orders",
            {"status": "open", "limit": "500", "direction": "asc", "nested": "false"},
        )
        orders_observed_at = self._now()
        if len(order_values) == 500:
            raise AlpacaPaperError("Alpaca paper open orders exceed the complete-read limit")
        open_orders = tuple(
            sorted(
                (self._open_order(value) for value in order_values),
                key=lambda item: item.client_order_id,
            )
        )

        snapshot_id = f"alpaca-paper-{
            fingerprint(
                {
                    'source': SnapshotSource.ALPACA_PAPER,
                    'account_id': observed_account,
                    'cash': cash,
                    'equity': equity,
                    'buying_power': buying_power,
                    'account_ready': account_ready,
                    'positions': positions,
                    'open_orders': open_orders,
                    'account_observed_at': account_observed_at,
                    'positions_observed_at': positions_observed_at,
                    'orders_observed_at': orders_observed_at,
                }
            )
        }"
        return PortfolioSnapshot(
            snapshot_id=snapshot_id,
            source=SnapshotSource.ALPACA_PAPER,
            account_id=observed_account,
            cash=cash,
            equity=equity,
            buying_power=buying_power,
            account_ready=account_ready,
            positions=positions,
            open_orders=open_orders,
            account_observed_at=account_observed_at,
            positions_observed_at=positions_observed_at,
            orders_observed_at=orders_observed_at,
        )

    def record_portfolio(
        self, store: ReconciliationStore, *, recorded_at: datetime
    ) -> PortfolioSnapshot:
        if not self._allows_persistence:
            raise AlpacaPaperError("injected transport cannot produce durable paper provenance")
        from .reconciliation import _ALPACA_READER_CAPABILITY

        snapshot = self.read_portfolio()
        return store._record_adapter_snapshot(
            snapshot,
            adapter_version="alpaca-paper-reader-v1",
            paper_origin=PAPER_ORIGIN,
            recorded_at=recorded_at,
            _capability=_ALPACA_READER_CAPABILITY,
        )

    def read_clock(self, *, maximum_age_seconds: int) -> MarketClockSnapshot:
        if isinstance(maximum_age_seconds, bool) or maximum_age_seconds < 1:
            raise ValueError("clock maximum age must be positive")
        value = self._get_object("/v2/clock")
        observed_at = self._now()
        is_open = value.get("is_open")
        if not isinstance(is_open, bool):
            raise AlpacaPaperError("Alpaca paper clock has an invalid market-open state")
        result = MarketClockSnapshot(
            observed_at=observed_at,
            provider_timestamp=_timestamp(value, "timestamp"),
            is_open=is_open,
            next_open=_timestamp(value, "next_open"),
            next_close=_timestamp(value, "next_close"),
        )
        if (
            result.provider_timestamp > observed_at
            or (observed_at - result.provider_timestamp).total_seconds() > maximum_age_seconds
        ):
            raise AlpacaPaperError("Alpaca paper clock is stale or future-dated")
        if (
            result.next_open <= result.provider_timestamp
            or result.next_close <= result.provider_timestamp
            or (result.is_open and result.next_close >= result.next_open)
            or (not result.is_open and result.next_open >= result.next_close)
        ):
            raise AlpacaPaperError("Alpaca paper clock session times are inconsistent")
        return result

    def read_order(self, client_order_id: str) -> PaperOrderSnapshot:
        if (
            not client_order_id
            or client_order_id != client_order_id.strip()
            or len(client_order_id) > 128
        ):
            raise ValueError("client order ID is invalid")
        value = self._get_object(
            "/v2/orders:by_client_order_id", {"client_order_id": client_order_id}
        )
        observed_at = self._now()
        if _text(value, "client_order_id", "order") != client_order_id:
            raise AlpacaPaperError("Alpaca paper lookup returned an unexpected client order ID")
        try:
            return PaperOrderSnapshot(
                broker_order_id=_text(value, "id", "order"),
                client_order_id=client_order_id,
                symbol=self._order_symbol(value),
                side=_text(value, "side", "order"),
                quantity=_whole_shares(value, "qty", positive=True),
                filled_quantity=_whole_shares(value, "filled_qty", positive=False),
                order_type=_text(value, "type", "order"),
                limit_price=_optional_amount(value, "limit_price"),
                status=_lookup_status(value),
                updated_at=_timestamp(value, "updated_at"),
                observed_at=observed_at,
            )
        except ValueError as error:
            raise AlpacaPaperError("Alpaca paper order is invalid") from error

    def record_order_lookup(
        self, store: BrokerEventStore, *, client_order_id: str
    ) -> BrokerOrderEvent | OrderLookupNotFoundEvidence:
        if not self._allows_persistence:
            raise AlpacaPaperError("injected transport cannot produce durable paper provenance")
        from .broker_events import _ALPACA_READER_CAPABILITY, BrokerOrderEvent
        from .orders import OrderState

        try:
            snapshot = self.read_order(client_order_id)
        except _OrderLookupNotFound:
            account = self._get_object("/v2/account")
            if _text(account, "id", "account") != self._account_id:
                raise AlpacaPaperError(
                    "Alpaca paper response is for an unexpected account"
                ) from None
            return store._record_lookup_not_found(
                client_order_id=client_order_id,
                account_id=self._account_id,
                observed_at=self._now(),
                _capability=_ALPACA_READER_CAPABILITY,
            )
        state = {
            "partially_filled": OrderState.PARTIALLY_FILLED,
            "filled": OrderState.FILLED,
            "canceled": OrderState.CANCELED,
            "expired": OrderState.CANCELED,
            "rejected": OrderState.REJECTED,
        }.get(snapshot.status, OrderState.ACKNOWLEDGED)
        event = BrokerOrderEvent(
            event_id=f"alpaca-lookup-{fingerprint(snapshot)}",
            broker_order_id=snapshot.broker_order_id,
            client_order_id=snapshot.client_order_id,
            state=state,
            cumulative_filled_quantity=snapshot.filled_quantity,
            provider_timestamp=snapshot.updated_at,
            observed_at=snapshot.observed_at,
        )
        return store.record(event)

    def _order_symbol(self, value: dict[str, Any]) -> str:
        symbol = _text(value, "symbol", "order")
        if symbol not in self._allowed_symbols:
            raise AlpacaPaperError("Alpaca paper response contains an unexpected symbol")
        _supported_order_envelope(value)
        return symbol

    def _position(self, value: Any) -> PositionSnapshot:
        if not isinstance(value, dict):
            raise AlpacaPaperError("Alpaca paper position has an invalid shape")
        symbol = _text(value, "symbol", "position")
        if symbol not in self._allowed_symbols:
            raise AlpacaPaperError("Alpaca paper response contains an unexpected symbol")
        quantity = _amount(value, "qty")
        if quantity != quantity.to_integral_value() or quantity <= 0:
            raise AlpacaPaperError("Alpaca paper position quantity is not positive whole shares")
        return PositionSnapshot(symbol=symbol, quantity=int(quantity))

    def _open_order(self, value: Any) -> OpenOrderSnapshot:
        return self._order(value, statuses=_OPEN_ORDER_STATUSES)

    def _order(self, value: Any, *, statuses: frozenset[str]) -> OpenOrderSnapshot:
        if not isinstance(value, dict):
            raise AlpacaPaperError("Alpaca paper order has an invalid shape")
        symbol = _text(value, "symbol", "order")
        if symbol not in self._allowed_symbols:
            raise AlpacaPaperError("Alpaca paper response contains an unexpected symbol")
        status = _text(value, "status", "order")
        if status not in statuses:
            raise AlpacaPaperError("Alpaca paper order has an unexpected status")
        _supported_order_envelope(value)
        try:
            return OpenOrderSnapshot(
                client_order_id=_text(value, "client_order_id", "order"),
                symbol=symbol,
                side=_text(value, "side", "order"),
                quantity=_whole_shares(value, "qty", positive=True),
                filled_quantity=_whole_shares(value, "filled_qty", positive=False),
                order_type=_text(value, "type", "order"),
                limit_price=_optional_amount(value, "limit_price"),
                status=status,
            )
        except ValueError as error:
            raise AlpacaPaperError("Alpaca paper open order is invalid") from error

    def _get_object(self, path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
        value = self._get(path, query)
        if not isinstance(value, dict):
            raise AlpacaPaperError("Alpaca paper response has an invalid object shape")
        return value

    def _get_list(self, path: str, query: dict[str, str] | None = None) -> list[Any]:
        value = self._get(path, query)
        if not isinstance(value, list):
            raise AlpacaPaperError("Alpaca paper response has an invalid list shape")
        return value

    def _get(self, path: str, query: dict[str, str] | None = None) -> Any:
        if path not in _ALLOWED_PATHS:
            raise AlpacaPaperError("Alpaca paper path is not allowed")
        suffix = f"?{urlencode(query)}" if query else ""
        request = Request(
            f"{PAPER_ORIGIN}{path}{suffix}",
            headers={
                "APCA-API-KEY-ID": self._api_key,
                "APCA-API-SECRET-KEY": self._secret_key,
                "Accept": "application/json",
            },
            method="GET",
        )
        _validate_request(request)
        try:
            return json.loads(self._transport(request))
        except HTTPError as error:
            if error.code == 404 and path == "/v2/orders:by_client_order_id":
                raise _OrderLookupNotFound("Alpaca paper order was not found") from None
            raise AlpacaPaperError(
                f"Alpaca paper request failed with HTTP status {error.code}"
            ) from None
        except (
            HTTPException,
            URLError,
            TimeoutError,
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            ValueError,
        ):
            raise AlpacaPaperError("Alpaca paper request failed") from None

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise AlpacaPaperError("paper observation clock must be UTC-aware")
        return value


def _text(value: dict[str, Any], field: str, subject: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result or result != result.strip() or len(result) > 128:
        raise AlpacaPaperError(f"Alpaca paper {subject} has an invalid {field} field")
    return result


def _amount(value: dict[str, Any], field: str) -> Decimal:
    raw = value.get(field)
    if not isinstance(raw, str):
        raise AlpacaPaperError(f"Alpaca paper response has an invalid {field} amount")
    try:
        result = Decimal(raw)
    except InvalidOperation:
        raise AlpacaPaperError(f"Alpaca paper response has an invalid {field} amount") from None
    if not result.is_finite() or result < 0:
        raise AlpacaPaperError(f"Alpaca paper response has an invalid {field} amount")
    return result


def _optional_amount(value: dict[str, Any], field: str) -> Decimal | None:
    return None if value.get(field) is None else _amount(value, field)


def _whole_shares(value: dict[str, Any], field: str, *, positive: bool) -> int:
    amount = _amount(value, field)
    if amount != amount.to_integral_value() or (amount <= 0 if positive else amount < 0):
        raise AlpacaPaperError(f"Alpaca paper order has an invalid {field} quantity")
    return int(amount)


def _account_ready(value: dict[str, Any]) -> bool:
    status = _text(value, "status", "account")
    flags = []
    for field in ("account_blocked", "trading_blocked", "trade_suspended_by_user"):
        flag = value.get(field)
        if not isinstance(flag, bool):
            raise AlpacaPaperError(f"Alpaca paper account has an invalid {field} field")
        flags.append(flag)
    return status == "ACTIVE" and not any(flags)


def _lookup_status(value: dict[str, Any]) -> str:
    status = _text(value, "status", "order")
    if status not in _ORDER_STATUSES:
        raise AlpacaPaperError("Alpaca paper order has an unexpected status")
    return status


def _supported_order_envelope(value: dict[str, Any]) -> None:
    if (
        value.get("time_in_force") != "day"
        or value.get("extended_hours") is not False
        or value.get("order_class") != "simple"
        or value.get("notional") is not None
        or value.get("legs") is not None
    ):
        raise AlpacaPaperError("Alpaca paper order is outside the supported envelope")


def _timestamp(value: dict[str, Any], field: str) -> datetime:
    raw = value.get(field)
    if not isinstance(raw, str):
        raise AlpacaPaperError(f"Alpaca paper clock has an invalid {field} timestamp")
    try:
        result = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise AlpacaPaperError(f"Alpaca paper clock has an invalid {field} timestamp") from None
    if result.tzinfo is None:
        raise AlpacaPaperError(f"Alpaca paper clock has an invalid {field} timestamp")
    return result.astimezone(UTC)


def _validate_request(request: Request) -> None:
    parsed = urlsplit(request.full_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    valid_query = (
        (parsed.path in {"/v2/account", "/v2/positions", "/v2/clock"} and not query)
        or (
            parsed.path == "/v2/orders"
            and query
            == {"status": ["open"], "limit": ["500"], "direction": ["asc"], "nested": ["false"]}
        )
        or (
            parsed.path == "/v2/orders:by_client_order_id"
            and set(query) == {"client_order_id"}
            and len(query["client_order_id"]) == 1
            and bool(query["client_order_id"][0])
            and len(query["client_order_id"][0]) <= 128
        )
    )
    if (
        request.get_method() != "GET"
        or parsed.scheme != "https"
        or parsed.netloc != "paper-api.alpaca.markets"
        or parsed.path not in _ALLOWED_PATHS
        or parsed.fragment
        or not valid_query
    ):
        raise AlpacaPaperError("Alpaca paper request target is not allowed")


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _urlopen_bytes(request: Request) -> bytes:
    _validate_request(request)
    with build_opener(_RejectRedirects).open(request, timeout=30) as response:
        if response.geturl() != request.full_url:
            raise AlpacaPaperError("Alpaca paper response redirected")
        return cast(bytes, response.read())
