from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request

import pytest

from systematic_trading_lab.multi_hour_sector_etf_plan import load_program_002_acquisition_plan
from systematic_trading_lab.program_002_account_isolation import (
    AccountPage,
    AccountProofClient,
    Program002AccountIsolationError,
    verify_account_isolation,
)

_REPOSITORY = Path(__file__).resolve().parents[2]
_KEY = "dedicated-key-never-persist"
_AUTH_VALUE = "dedicated-auth-value-never-persist"


def _transport(
    *,
    created_at: str = "2026-08-25T12:00:00Z",
    cash: str = "0",
    orders: list[object] | None = None,
) -> tuple[Callable[[Request], AccountPage], list[Request]]:
    seen: list[Request] = []

    def get(request: Request) -> AccountPage:
        seen.append(request)
        path = urlparse(request.full_url).path
        payload: object
        if path == "/v2/account":
            payload = {
                "id": "account-id-never-persist",
                "account_number": "account-number-never-persist",
                "created_at": created_at,
                "status": "ACTIVE",
                "cash": cash,
                "equity": cash,
                "portfolio_value": cash,
                "long_market_value": "0",
                "short_market_value": "0",
            }
        elif path == "/v2/orders":
            payload = [] if orders is None else orders
        else:
            payload = []
        return AccountPage(
            200,
            json.dumps(payload).encode(),
            {"X-Request-ID": f"request-{len(seen)}"},
        )

    return get, seen


def test_paper_proof_is_get_only_redacted_and_bound() -> None:
    transport, seen = _transport()
    artifact = verify_account_isolation(
        load_program_002_acquisition_plan(_REPOSITORY),
        AccountProofClient("paper", _KEY, _AUTH_VALUE, transport),
        created_at=datetime(2026, 8, 25, 13, tzinfo=UTC),
    )

    assert [request.method for request in seen] == ["GET"] * 4
    assert {urlparse(request.full_url).netloc for request in seen} == {"paper-api.alpaca.markets"}
    assert artifact["positions_empty"] is artifact["open_orders_empty"] is True
    assert artifact["orders_empty"] is True
    assert artifact["credential_key_id_hash"] == hashlib.sha256(_KEY.encode()).hexdigest()
    assert urlparse(seen[2].full_url).query == "status=all&limit=1&direction=asc"
    assert urlparse(seen[3].full_url).query == "direction=asc&page_size=1"
    assert artifact["order_history_disposition"] == "empty-first-page"
    assert artifact["order_page_count"] == 1
    assert artifact["activity_history_disposition"] == "empty-first-page"
    assert artifact["activity_page_count"] == 1
    encoded = json.dumps(artifact)
    assert not any(
        value in encoded
        for value in (
            _KEY,
            _AUTH_VALUE,
            "account-id-never-persist",
            "account-number-never-persist",
        )
    )


def test_old_reused_or_funded_accounts_fail_closed() -> None:
    plan = load_program_002_acquisition_plan(_REPOSITORY)
    transport, _ = _transport(created_at="2026-08-24T23:59:59Z")
    with pytest.raises(Program002AccountIsolationError, match="predates"):
        verify_account_isolation(
            plan,
            AccountProofClient("paper", _KEY, _AUTH_VALUE, transport),
            created_at=datetime(2026, 8, 25, 13, tzinfo=UTC),
        )

    transport, _ = _transport(cash="1")
    with pytest.raises(Program002AccountIsolationError, match="funded"):
        verify_account_isolation(
            plan,
            AccountProofClient("live", _KEY, _AUTH_VALUE, transport),
            created_at=datetime(2026, 8, 25, 13, tzinfo=UTC),
        )

    transport, seen = _transport(orders=[{"id": "prior-order"}])
    with pytest.raises(Program002AccountIsolationError, match="prior or open orders"):
        verify_account_isolation(
            plan,
            AccountProofClient("paper", _KEY, _AUTH_VALUE, transport),
            created_at=datetime(2026, 8, 25, 13, tzinfo=UTC),
        )
    assert [urlparse(request.full_url).path for request in seen] == [
        "/v2/account",
        "/v2/positions",
        "/v2/orders",
    ]


def test_account_client_rejects_non_get_scope() -> None:
    client = AccountProofClient("paper", _KEY, _AUTH_VALUE, lambda _: AccountPage(200, b"[]", {}))
    with pytest.raises(Program002AccountIsolationError, match="order query differs"):
        client.get("/v2/orders", {"status": "open"})
    with pytest.raises(Program002AccountIsolationError, match="outside GET scope"):
        client.get("/v2/assets")


def test_activity_check_stops_after_first_nonempty_page() -> None:
    base, _ = _transport()
    activity_requests: list[Request] = []

    def transport(request: Request) -> AccountPage:
        parsed = urlparse(request.full_url)
        if parsed.path != "/v2/account/activities":
            return base(request)
        activity_requests.append(request)
        activities = [{"id": f"activity-{index}"} for index in range(100)]
        return AccountPage(200, json.dumps(activities).encode(), {})

    with pytest.raises(Program002AccountIsolationError, match="prior activity"):
        verify_account_isolation(
            load_program_002_acquisition_plan(_REPOSITORY),
            AccountProofClient("paper", _KEY, _AUTH_VALUE, transport),
            created_at=datetime(2026, 8, 25, 13, tzinfo=UTC),
        )
    assert len(activity_requests) == 1
