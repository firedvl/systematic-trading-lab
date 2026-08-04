import inspect
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.message import Message
from http.client import BadStatusLine
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest

from systematic_trading_lab.alpaca_paper import (
    AlpacaPaperError,
    AlpacaPaperReader,
    _validate_request,
)
from systematic_trading_lab.broker_events import BrokerOrderEvent
from systematic_trading_lab.reconciliation import (
    PositionSnapshot,
    ReconciliationStore,
    SnapshotSource,
)

NOW = datetime(2026, 8, 3, 20, 0, tzinfo=UTC)


def _payloads(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "/v2/account": {
            "id": "paper-account",
            "status": "ACTIVE",
            "cash": "1000.00",
            "equity": "1250.00",
            "last_equity": "1300.00",
            "buying_power": "2000.00",
            "account_blocked": False,
            "trading_blocked": False,
            "trade_suspended_by_user": False,
        },
        "/v2/positions": [{"symbol": "SPY", "qty": "2"}],
        "/v2/orders": [
            {
                "client_order_id": "client-2",
                "symbol": "SPY",
                "status": "new",
                "side": "buy",
                "qty": "2",
                "filled_qty": "0",
                "type": "market",
                "limit_price": None,
                "time_in_force": "day",
                "extended_hours": False,
                "order_class": "simple",
                "notional": None,
                "legs": None,
            },
            {
                "client_order_id": "client-1",
                "symbol": "QQQ",
                "status": "partially_filled",
                "side": "sell",
                "qty": "3",
                "filled_qty": "1",
                "type": "limit",
                "limit_price": "500.25",
                "time_in_force": "day",
                "extended_hours": False,
                "order_class": "simple",
                "notional": None,
                "legs": None,
            },
        ],
        "/v2/clock": {
            "timestamp": "2026-08-03T12:59:59-07:00",
            "is_open": True,
            "next_open": "2026-08-04T09:30:00-04:00",
            "next_close": "2026-08-03T16:00:00-04:00",
        },
    }
    values.update(changes)
    return values


def _reader(
    payloads: dict[str, object],
    requests: list[Request] | None = None,
) -> AlpacaPaperReader:
    observations = iter(NOW + timedelta(seconds=offset) for offset in range(4))

    def transport(request: Request) -> bytes:
        if requests is not None:
            requests.append(request)
        return json.dumps(payloads[urlsplit(request.full_url).path]).encode()

    return AlpacaPaperReader(
        "test-key",
        "test-secret",
        account_id="paper-account",
        allowed_symbols=frozenset({"SPY", "QQQ"}),
        transport=transport,
        clock=lambda: next(observations),
    )


def test_reader_normalizes_complete_portfolio_and_clock_with_get_only_requests() -> None:
    requests: list[Request] = []
    reader = _reader(_payloads(), requests)

    portfolio = reader.read_portfolio()
    market_clock = reader.read_clock(maximum_age_seconds=30)

    assert portfolio.source is SnapshotSource.ALPACA_PAPER
    assert portfolio.account_id == "paper-account"
    assert portfolio.buying_power == 2000
    assert portfolio.account_ready
    assert portfolio.positions == (PositionSnapshot("SPY", 2),)
    assert portfolio.open_client_order_ids == ("client-1", "client-2")
    assert (
        portfolio.account_observed_at,
        portfolio.positions_observed_at,
        portfolio.orders_observed_at,
    ) == (NOW, NOW + timedelta(seconds=1), NOW + timedelta(seconds=2))
    assert market_clock.observed_at == NOW + timedelta(seconds=3)
    assert market_clock.provider_timestamp == NOW - timedelta(seconds=1)
    assert market_clock.is_open
    assert [urlsplit(request.full_url).path for request in requests] == [
        "/v2/account",
        "/v2/positions",
        "/v2/orders",
        "/v2/clock",
    ]
    assert all(request.get_method() == "GET" for request in requests)
    assert all(
        urlsplit(request.full_url).netloc == "paper-api.alpaca.markets" for request in requests
    )
    assert all(request.headers["Apca-api-key-id"] == "test-key" for request in requests)
    assert all(request.headers["Apca-api-secret-key"] == "test-secret" for request in requests)
    assert parse_qs(urlsplit(requests[2].full_url).query) == {
        "status": ["open"],
        "limit": ["500"],
        "direction": ["asc"],
        "nested": ["false"],
    }
    public_methods = {
        name
        for name, value in inspect.getmembers(AlpacaPaperReader, inspect.isfunction)
        if not name.startswith("_")
    }
    assert public_methods == {
        "read_clock",
        "read_order",
        "read_portfolio",
        "record_order_lookup",
        "record_portfolio",
    }


def test_reader_rejects_invalid_prior_close_equity() -> None:
    payloads = _payloads()
    account = payloads["/v2/account"]
    assert isinstance(account, dict)
    account["last_equity"] = "NaN"

    with pytest.raises(AlpacaPaperError, match="last_equity"):
        _reader(payloads).read_portfolio()


def test_reader_looks_up_one_exact_client_order_id() -> None:
    requests: list[Request] = []
    order = {
        "id": "broker-order-1",
        "client_order_id": "client-1",
        "symbol": "SPY",
        "status": "filled",
        "side": "buy",
        "qty": "2",
        "filled_qty": "2",
        "filled_avg_price": "101.25",
        "type": "market",
        "limit_price": None,
        "time_in_force": "day",
        "extended_hours": False,
        "order_class": "simple",
        "notional": None,
        "legs": None,
        "updated_at": "2026-08-03T20:00:00Z",
    }
    reader = _reader(_payloads(**{"/v2/orders:by_client_order_id": order}), requests)

    result = reader.read_order("client-1")

    assert result.broker_order_id == "broker-order-1"
    assert result.client_order_id == "client-1"
    assert result.status == "filled"
    assert result.filled_average_price == Decimal("101.25")
    assert parse_qs(urlsplit(requests[0].full_url).query) == {"client_order_id": ["client-1"]}
    with pytest.raises(AlpacaPaperError, match="order is invalid"):
        _reader(
            _payloads(**{"/v2/orders:by_client_order_id": {**order, "filled_avg_price": None}})
        ).read_order("client-1")
    with pytest.raises(AlpacaPaperError, match="order is invalid"):
        _reader(
            _payloads(
                **{
                    "/v2/orders:by_client_order_id": {
                        **order,
                        "filled_qty": "0",
                        "filled_avg_price": "101.25",
                    }
                }
            )
        ).read_order("client-1")


def test_only_production_lookup_path_can_record_normalized_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "id": "broker-order-1",
        "client_order_id": "client-1",
        "symbol": "SPY",
        "status": "filled",
        "side": "buy",
        "qty": "2",
        "filled_qty": "2",
        "filled_avg_price": "101.25",
        "type": "market",
        "limit_price": None,
        "time_in_force": "day",
        "extended_hours": False,
        "order_class": "simple",
        "notional": None,
        "legs": None,
        "updated_at": "2026-08-03T20:00:00Z",
    }
    injected = _reader(_payloads(**{"/v2/orders:by_client_order_id": payload}))
    with pytest.raises(AlpacaPaperError, match="injected transport"):
        injected.record_order_lookup(cast(Any, object()), client_order_id="client-1")

    def transport(request: Request) -> bytes:
        return json.dumps(payload).encode()

    class Sink:
        def _record_lookup_found(self, event: object, **_kwargs: object) -> object:
            return event

    monkeypatch.setattr("systematic_trading_lab.alpaca_paper._urlopen_bytes", transport)
    reader = AlpacaPaperReader(
        "test-key",
        "test-secret",
        account_id="paper-account",
        allowed_symbols=frozenset({"SPY"}),
        clock=lambda: NOW,
    )
    event = reader.record_order_lookup(cast(Any, Sink()), client_order_id="client-1")
    assert isinstance(event, BrokerOrderEvent)
    assert event.client_order_id == "client-1"
    assert event.cumulative_filled_quantity == 2
    assert event.cumulative_average_fill_price == Decimal("101.25")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"/v2/account": {"id": "other", "cash": "1", "equity": "1"}}, "account"),
        ({"/v2/account": {"id": "paper-account", "cash": 1, "equity": "1"}}, "cash"),
        ({"/v2/positions": [{"symbol": "DIA", "qty": "1"}]}, "symbol"),
        ({"/v2/positions": [{"symbol": "SPY", "qty": "1.5"}]}, "whole shares"),
        (
            {"/v2/orders": [{"client_order_id": "client", "symbol": "SPY", "status": "filled"}]},
            "status",
        ),
        (
            {
                "/v2/orders": [
                    {
                        "client_order_id": "client",
                        "symbol": "SPY",
                        "status": "new",
                        "time_in_force": "day",
                        "extended_hours": False,
                        "order_class": "bracket",
                    }
                ]
            },
            "supported envelope",
        ),
        (
            {
                "/v2/clock": {
                    "timestamp": "bad",
                    "is_open": True,
                    "next_open": "bad",
                    "next_close": "bad",
                }
            },
            "timestamp",
        ),
    ],
)
def test_reader_rejects_malformed_or_unexpected_state(
    changes: dict[str, object], message: str
) -> None:
    reader = _reader(_payloads(**changes))

    def action() -> object:
        if "/v2/clock" in changes:
            return reader.read_clock(maximum_age_seconds=30)
        return reader.read_portfolio()

    with pytest.raises(AlpacaPaperError, match=message):
        action()


def test_reader_fails_closed_when_open_order_read_may_be_incomplete() -> None:
    orders = [
        {"client_order_id": f"client-{index}", "symbol": "SPY", "status": "new"}
        for index in range(500)
    ]

    with pytest.raises(AlpacaPaperError, match="complete-read limit"):
        _reader(_payloads(**{"/v2/orders": orders})).read_portfolio()


def test_risk_critical_account_and_order_changes_change_snapshot_identity() -> None:
    changed = _payloads()
    account = changed["/v2/account"]
    orders = changed["/v2/orders"]
    assert isinstance(account, dict)
    assert isinstance(orders, list) and isinstance(orders[0], dict)
    account["buying_power"] = "1999.00"
    orders[0]["qty"] = "4"

    original = _reader(_payloads()).read_portfolio()
    modified = _reader(changed).read_portfolio()

    assert original.snapshot_id != modified.snapshot_id
    assert original.open_orders != modified.open_orders


def test_injected_transport_cannot_create_durable_provenance(tmp_path: Path) -> None:
    reader = _reader(_payloads())

    with pytest.raises(AlpacaPaperError, match="injected transport"):
        reader.record_portfolio(
            ReconciliationStore(tmp_path / "execution.sqlite3"), recorded_at=NOW
        )


@pytest.mark.parametrize(
    ("clock", "message"),
    [
        (
            {
                "timestamp": "2020-01-01T00:00:00Z",
                "is_open": False,
                "next_open": "2026-08-04T13:30:00Z",
                "next_close": "2026-08-04T20:00:00Z",
            },
            "stale or future",
        ),
        (
            {
                "timestamp": "2026-08-03T20:00:10Z",
                "is_open": True,
                "next_open": "2026-08-04T13:30:00Z",
                "next_close": "2026-08-03T21:00:00Z",
            },
            "stale or future",
        ),
        (
            {
                "timestamp": "2026-08-03T20:00:00Z",
                "is_open": True,
                "next_open": "2026-08-03T20:30:00Z",
                "next_close": "2026-08-04T20:00:00Z",
            },
            "inconsistent",
        ),
    ],
)
def test_clock_rejects_stale_future_or_inconsistent_provider_state(
    clock: dict[str, object], message: str
) -> None:
    with pytest.raises(AlpacaPaperError, match=message):
        _reader(_payloads(**{"/v2/clock": clock})).read_clock(maximum_age_seconds=30)


@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 429, 500, 503])
def test_http_failures_are_sanitized(status: int) -> None:
    def transport(request: Request) -> bytes:
        raise HTTPError(request.full_url, status, "secret raw error", Message(), None)

    reader = AlpacaPaperReader(
        "test-key",
        "test-secret",
        account_id="paper-account",
        allowed_symbols=frozenset({"SPY"}),
        transport=transport,
    )

    with pytest.raises(AlpacaPaperError) as caught:
        reader.read_portfolio()
    assert str(caught.value) == f"Alpaca paper request failed with HTTP status {status}"
    assert "secret" not in str(caught.value)


def test_exact_order_404_is_sanitized() -> None:
    def transport(request: Request) -> bytes:
        raise HTTPError(request.full_url, 404, "secret raw error", Message(), None)

    reader = AlpacaPaperReader(
        "test-key",
        "test-secret",
        account_id="paper-account",
        allowed_symbols=frozenset({"SPY"}),
        transport=transport,
    )

    with pytest.raises(AlpacaPaperError) as caught:
        reader.read_order("client-1")
    assert str(caught.value) == "Alpaca paper order was not found"
    assert "secret" not in str(caught.value)


def test_negative_lookup_requires_the_expected_account(monkeypatch: pytest.MonkeyPatch) -> None:
    def transport(request: Request) -> bytes:
        if urlsplit(request.full_url).path == "/v2/account":
            return json.dumps({"id": "other-account"}).encode()
        raise HTTPError(request.full_url, 404, "secret raw error", Message(), None)

    monkeypatch.setattr("systematic_trading_lab.alpaca_paper._urlopen_bytes", transport)
    reader = AlpacaPaperReader(
        "test-key",
        "test-secret",
        account_id="paper-account",
        allowed_symbols=frozenset({"SPY"}),
    )

    with pytest.raises(AlpacaPaperError, match="unexpected account"):
        reader.record_order_lookup(cast(Any, object()), client_order_id="client-1")


def test_low_level_http_failures_are_sanitized() -> None:
    def transport(request: Request) -> bytes:
        raise BadStatusLine("secret raw status")

    reader = AlpacaPaperReader(
        "test-key",
        "test-secret",
        account_id="paper-account",
        allowed_symbols=frozenset({"SPY"}),
        transport=transport,
    )

    with pytest.raises(AlpacaPaperError) as caught:
        reader.read_portfolio()
    assert str(caught.value) == "Alpaca paper request failed"


@pytest.mark.parametrize(
    "candidate_request",
    [
        Request("https://api.alpaca.markets/v2/account", method="GET"),
        Request("https://paper-api.alpaca.markets/v2/account", method="POST"),
        Request("https://paper-api.alpaca.markets/v2/orders/client", method="GET"),
        Request("http://paper-api.alpaca.markets/v2/account", method="GET"),
    ],
)
def test_request_boundary_rejects_production_host_mutations_and_unknown_paths(
    candidate_request: Request,
) -> None:
    with pytest.raises(AlpacaPaperError, match="target is not allowed"):
        _validate_request(candidate_request)
