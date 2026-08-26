"""GET-only, non-secret Program 002 account-isolation proof."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .fingerprints import canonical_json, canonicalize, fingerprint
from .multi_hour_sector_etf_plan import Program002AcquisitionPlan, load_program_002_acquisition_plan
from .program_002_credentials import (
    acquisition_account_environment,
    credential_key_id_hash,
    read_acquisition_credentials,
)

_HOSTS = {
    "paper": "paper-api.alpaca.markets",
    "live": "api.alpaca.markets",
}
_CREATED_AFTER = datetime(2026, 8, 25, tzinfo=UTC)
_LIVE_ZERO_FIELDS = (
    "cash",
    "equity",
    "portfolio_value",
    "long_market_value",
    "short_market_value",
)


class Program002AccountIsolationError(RuntimeError):
    pass


@dataclass(frozen=True)
class AccountPage:
    status: int
    body: bytes
    headers: Mapping[str, str]


class AccountProofClient:
    """Fixed-host GET transport separate from the historical-data client."""

    def __init__(
        self,
        environment: str,
        api_key: str,
        secret: str,
        transport: Callable[[Request], AccountPage] | None = None,
    ) -> None:
        if environment not in _HOSTS or not api_key or not secret:
            raise ValueError("account proof environment and credentials are required")
        self.environment = environment
        self._host = _HOSTS[environment]
        self.credential_key_id_hash = credential_key_id_hash(api_key)
        self._headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret}
        self._transport = transport or _urlopen_page

    def get(self, path: str, params: Mapping[str, str] | None = None) -> AccountPage:
        query = dict(params or {})
        allowed = {
            "/v2/account": set(),
            "/v2/positions": set(),
            "/v2/orders": {"status", "limit", "direction"},
            "/v2/account/activities": {"direction", "page_size"},
        }
        if path not in allowed or set(query) - allowed[path]:
            raise Program002AccountIsolationError("account proof request is outside GET scope")
        if path == "/v2/orders" and query != {
            "status": "all",
            "limit": "1",
            "direction": "asc",
        }:
            raise Program002AccountIsolationError("account proof order query differs")
        if path == "/v2/account/activities" and (
            query.get("direction") != "asc"
            or query.get("page_size") != "1"
            or set(query) != {"direction", "page_size"}
        ):
            raise Program002AccountIsolationError("account proof activity query differs")
        url = f"https://{self._host}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        page = self._transport(Request(url, headers=self._headers, method="GET"))
        if page.status != 200:
            raise Program002AccountIsolationError(
                f"account proof GET {path} returned HTTP {page.status}"
            )
        return page


def verify_account_isolation(
    plan: Program002AcquisitionPlan,
    client: AccountProofClient,
    *,
    created_at: datetime,
) -> dict[str, Any]:
    proof_contract = _mapping(
        plan.control_payload.get("account_isolation_proof_contract"),
        "account isolation proof contract",
    )
    launch = _mapping(plan.control_payload.get("launch_control"), "control launch")
    if (
        launch.get("account_isolation_verification_allowed") is not True
        or launch.get("market_data_acquisition_allowed") is not False
        or proof_contract.get("account_created_at_or_after") != "2026-08-25T00:00:00Z"
    ):
        raise Program002AccountIsolationError("account-isolation control is not active")
    if created_at.tzinfo is None or created_at.utcoffset() != UTC.utcoffset(created_at):
        raise ValueError("proof timestamp must be UTC-aware")

    account_page = client.get("/v2/account")
    account = _mapping(_json(account_page.body), "account response")
    account_id = _text(account, "id")
    account_number = _text(account, "account_number")
    provider_created_at = _utc(_text(account, "created_at"))
    if provider_created_at < _CREATED_AFTER:
        raise Program002AccountIsolationError(
            "account predates the prospective dedicated-account proof boundary"
        )
    if account.get("status") != "ACTIVE":
        raise Program002AccountIsolationError("account status is not ACTIVE")
    if client.environment == "live":
        try:
            nonzero = [field for field in _LIVE_ZERO_FIELDS if Decimal(str(account[field])) != 0]
        except (ArithmeticError, KeyError) as error:
            raise Program002AccountIsolationError(
                "live account funding fields are invalid"
            ) from error
        if nonzero:
            raise Program002AccountIsolationError("live account is funded")

    positions_page = client.get("/v2/positions")
    positions = _list(_json(positions_page.body), "positions response")
    if positions:
        raise Program002AccountIsolationError("account has open positions")
    orders_page = client.get(
        "/v2/orders",
        {"status": "all", "limit": "1", "direction": "asc"},
    )
    orders = _list(_json(orders_page.body), "orders response")
    if orders:
        raise Program002AccountIsolationError("account has prior or open orders")
    activity_pages, activity_count, activity_request_ids = _account_activities(client)
    if activity_count:
        raise Program002AccountIsolationError("account has prior activity")

    request_ids: dict[str, Any] = {
        name: value
        for name, page in {
            "account": account_page,
            "positions": positions_page,
            "orders": orders_page,
        }.items()
        if (value := _header(page.headers, "x-request-id"))
    }
    if activity_request_ids:
        request_ids["activities"] = activity_request_ids
    artifact: dict[str, Any] = {
        "schema_version": "program-002-account-isolation-proof-v1",
        "proof_id": "program-002-account-isolation-2026-08-25-v1",
        "program_id": "multi-hour-sector-etf-research-001",
        "created_at": created_at,
        "provider": "Alpaca Trading API",
        "environment": client.environment,
        "credential_key_id_hash": client.credential_key_id_hash,
        "account_identity_hash": hashlib.sha256(account_id.encode()).hexdigest(),
        "account_number_hash": hashlib.sha256(account_number.encode()).hexdigest(),
        "provider_account_created_at": provider_created_at,
        "account_status": "ACTIVE",
        "dedicated_account_assertion": "new-account-with-empty-trading-surfaces",
        "non_reused_assertion": "no-orders-or-account-activities-returned",
        "funding_isolation_assertion": (
            "paper-credential-has-no-live-host-authority"
            if client.environment == "paper"
            else "live-account-balance-and-market-value-fields-are-zero"
        ),
        "positions_empty": True,
        "orders_empty": True,
        "open_orders_empty": True,
        "order_history_disposition": "empty-first-page",
        "order_page_count": 1,
        "activity_history_disposition": "empty-first-page",
        "activity_page_count": activity_pages,
        "request_ids": request_ids,
        "raw_responses_persisted": False,
        "market_data_requested": False,
        "broker_write_requested": False,
        "control_amendment_sha256": plan.control_sha256,
    }
    artifact["proof_fingerprint"] = fingerprint(artifact)
    canonical = canonicalize(artifact)
    if not isinstance(canonical, dict):
        raise AssertionError("canonical account proof must be an object")
    return {str(key): value for key, value in canonical.items()}


def publish_proof(path: Path, artifact: Mapping[str, Any]) -> tuple[str, bool]:
    encoded = (canonical_json(artifact) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != encoded:
            raise Program002AccountIsolationError("account proof publication conflicts")
        return hashlib.sha256(encoded).hexdigest(), False
    try:
        with path.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as error:
        raise Program002AccountIsolationError("account proof publication raced") from error
    return hashlib.sha256(encoded).hexdigest(), True


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m systematic_trading_lab.program_002_account_isolation"
    )
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".trading-lab/program-002/account-isolation-proof-v1.json"),
    )
    parsed = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        plan = load_program_002_acquisition_plan(parsed.repository)
        environment = acquisition_account_environment()
        key_id, secret = read_acquisition_credentials()
        artifact = verify_account_isolation(
            plan,
            AccountProofClient(environment, key_id, secret),
            created_at=datetime.now(UTC),
        )
        sha256, created = publish_proof(parsed.output, artifact)
        print(
            json.dumps(
                {
                    "created": created,
                    "path": str(parsed.output),
                    "proof_fingerprint": artifact["proof_fingerprint"],
                    "proof_sha256": sha256,
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, Program002AccountIsolationError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return os.EX_USAGE


def _json(raw: bytes) -> object:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            if key in output:
                raise Program002AccountIsolationError("account response contains duplicate key")
            output[key] = value
        return output

    try:
        return json.loads(raw, object_pairs_hook=unique)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Program002AccountIsolationError("account response is malformed") from error


def _account_activities(client: AccountProofClient) -> tuple[int, int, list[str]]:
    page = client.get(
        "/v2/account/activities",
        {"direction": "asc", "page_size": "1"},
    )
    values = _list(_json(page.body), "account activities response")
    request_id = _header(page.headers, "x-request-id")
    return 1, len(values), [request_id] if request_id else []


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Program002AccountIsolationError(f"{label} must be an object")
    return value


def _list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise Program002AccountIsolationError(f"{label} must be a list")
    return value


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise Program002AccountIsolationError(f"account response omitted {key}")
    return item


def _utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise Program002AccountIsolationError("account created_at is malformed") from error
    if parsed.tzinfo is None:
        raise Program002AccountIsolationError("account created_at is not timezone-aware")
    return parsed.astimezone(UTC)


def _header(headers: Mapping[str, str], name: str) -> str:
    return next((value for key, value in headers.items() if key.lower() == name), "")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


def _urlopen_page(request: Request) -> AccountPage:
    parsed = urlparse(request.full_url)
    if (
        request.method != "GET"
        or parsed.scheme != "https"
        or parsed.netloc not in set(_HOSTS.values())
        or parsed.path
        not in {"/v2/account", "/v2/positions", "/v2/orders", "/v2/account/activities"}
        or len(parse_qsl(parsed.query, keep_blank_values=True))
        != len(dict(parse_qsl(parsed.query)))
    ):
        raise Program002AccountIsolationError("account proof transport scope differs")
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=30) as response:
            body = response.read(4 * 1024 * 1024 + 1)
            if len(body) > 4 * 1024 * 1024:
                raise Program002AccountIsolationError("account proof response exceeds limit")
            return AccountPage(response.status, body, dict(response.headers.items()))
    except HTTPError as error:
        return AccountPage(error.code, b"", dict(error.headers.items()) if error.headers else {})
    except (TimeoutError, URLError) as error:
        raise Program002AccountIsolationError("account proof GET failed") from error


if __name__ == "__main__":
    raise SystemExit(main())
