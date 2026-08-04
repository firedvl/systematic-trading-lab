"""Fixed-origin HTTP transport for future Alpaca paper mutations."""

from __future__ import annotations

import json
import re
from http.client import HTTPException
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .alpaca_paper import AlpacaPaperError
from .fingerprints import canonical_json

_MAX_RESPONSE_BYTES = 1024 * 1024
_TIMEOUT_SECONDS = 10


def _urlopen_paper_mutation(request: Request, *, opener: Any = None) -> bytes:
    """Execute one exact paper mutation without retry or proxy routing."""
    _validate_mutation(request)
    transport = opener or build_opener(ProxyHandler({}), _RejectRedirects())
    try:
        with transport.open(request, timeout=_TIMEOUT_SECONDS) as response:
            if response.geturl() != request.full_url:
                raise AlpacaPaperError("Alpaca paper mutation redirected")
            method = request.get_method()
            expected_status = 200 if method == "POST" else 204
            if response.status != expected_status:
                raise AlpacaPaperError(
                    f"Alpaca paper mutation failed with HTTP status {response.status}"
                )
            body = cast(bytes, response.read(_MAX_RESPONSE_BYTES + 1))
            if len(body) > _MAX_RESPONSE_BYTES:
                raise AlpacaPaperError("Alpaca paper mutation response is too large")
            if method == "POST":
                if response.headers.get_content_type() != "application/json" or not body:
                    raise AlpacaPaperError("Alpaca paper mutation response is invalid")
            elif body:
                raise AlpacaPaperError("Alpaca paper mutation response is invalid")
            return body
    except HTTPError as error:
        raise AlpacaPaperError(
            f"Alpaca paper mutation failed with HTTP status {error.code}"
        ) from None
    except (HTTPException, URLError, TimeoutError, OSError):
        raise AlpacaPaperError("Alpaca paper mutation failed") from None


def _validate_mutation(request: Request) -> None:
    parsed = urlsplit(request.full_url)
    headers = {name.lower(): value for name, value in request.header_items()}
    method = request.get_method()
    valid_path = (
        method == "POST"
        and parsed.path == "/v2/orders"
        and isinstance(request.data, bytes)
        and _valid_post_body(request.data)
    )
    if method == "DELETE" and request.data is None:
        parts = parsed.path.split("/")
        if len(parts) == 4 and parts[:3] == ["", "v2", "orders"] and parts[3]:
            broker_order_id = unquote(parts[3])
            valid_path = (
                broker_order_id not in {".", ".."}
                and broker_order_id == broker_order_id.strip()
                and "/" not in broker_order_id
                and 0 < len(broker_order_id) <= 128
                and quote(broker_order_id, safe="") == parts[3]
            )
    if (
        parsed.scheme != "https"
        or parsed.netloc != "paper-api.alpaca.markets"
        or parsed.query
        or parsed.fragment
        or not valid_path
        or method not in {"POST", "DELETE"}
        or not _credential(headers.get("apca-api-key-id"))
        or not _credential(headers.get("apca-api-secret-key"))
        or headers.get("accept") != "application/json"
        or (method == "POST" and headers.get("content-type") != "application/json")
    ):
        raise AlpacaPaperError("Alpaca paper mutation target is not allowed")


def _valid_post_body(raw: bytes | None) -> bool:
    try:
        value = json.loads(raw or b"")
    except (UnicodeError, json.JSONDecodeError):
        return False
    fields = {
        "client_order_id",
        "extended_hours",
        "order_class",
        "qty",
        "side",
        "symbol",
        "time_in_force",
        "type",
    }
    if not isinstance(value, dict) or set(value) != fields:
        return False
    client_order_id = value["client_order_id"]
    quantity = value["qty"]
    symbol = value["symbol"]
    return (
        isinstance(client_order_id, str)
        and client_order_id == client_order_id.strip()
        and 0 < len(client_order_id) <= 128
        and isinstance(quantity, str)
        and quantity.isascii()
        and quantity.isdigit()
        and not quantity.startswith("0")
        and isinstance(symbol, str)
        and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,15}", symbol) is not None
        and value["side"] in {"buy", "sell"}
        and value["type"] == "market"
        and value["time_in_force"] == "day"
        and value["extended_hours"] is False
        and value["order_class"] == "simple"
        and canonical_json(value).encode() == raw
    )


def _credential(value: str | None) -> bool:
    return isinstance(value, str) and value == value.strip() and bool(value)


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None
