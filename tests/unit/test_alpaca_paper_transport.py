from __future__ import annotations

from datetime import UTC, datetime
from email.message import Message
from pathlib import Path
from urllib.request import Request

import pytest

from systematic_trading_lab.alpaca_paper import AlpacaPaperError
from systematic_trading_lab.alpaca_paper_transport import _urlopen_paper_mutation
from systematic_trading_lab.config import PaperWriteRequest, Settings
from systematic_trading_lab.domain import TradingMode
from systematic_trading_lab.fingerprints import canonical_json
from systematic_trading_lab.paper_operator import AlpacaPaperOperator
from systematic_trading_lab.risk import load_risk_limits
from systematic_trading_lab.runtime_build import InstalledRuntimeIdentity


class _Response:
    def __init__(
        self,
        url: str,
        *,
        status: int,
        body: bytes,
        content_type: str | None = None,
    ) -> None:
        self._url = url
        self.status = status
        self._body = body
        self.headers = Message()
        if content_type is not None:
            self.headers["Content-Type"] = content_type

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, size: int) -> bytes:
        return self._body[:size]


class _Opener:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[Request, int]] = []

    def open(self, request: Request, *, timeout: int) -> _Response:
        self.calls.append((request, timeout))
        return self.response


class _FailingOpener:
    def open(self, request: Request, *, timeout: int) -> _Response:
        raise TimeoutError("unsanitized transport detail")


def _request(method: str, url: str, *, body: bytes | None = None) -> Request:
    post_body = canonical_json(
        {
            "client_order_id": "order-1",
            "extended_hours": False,
            "order_class": "simple",
            "qty": "1",
            "side": "buy",
            "symbol": "SPY",
            "time_in_force": "day",
            "type": "market",
        }
    ).encode()
    return Request(
        url,
        data=(post_body if body is None else body) if method == "POST" else None,
        headers={
            "APCA-API-KEY-ID": "test-key",
            "APCA-API-SECRET-KEY": "test-secret",
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if method == "POST" else {}),
        },
        method=method,
    )


def test_paper_mutation_transport_accepts_only_exact_post_and_delete() -> None:
    post = _request("POST", "https://paper-api.alpaca.markets/v2/orders")
    post_opener = _Opener(
        _Response(post.full_url, status=200, body=b"{}", content_type="application/json")
    )
    assert _urlopen_paper_mutation(post, opener=post_opener) == b"{}"
    assert post_opener.calls == [(post, 10)]

    delete = _request("DELETE", "https://paper-api.alpaca.markets/v2/orders/order-1")
    assert (
        _urlopen_paper_mutation(
            delete, opener=_Opener(_Response(delete.full_url, status=204, body=b""))
        )
        == b""
    )

    for url in (
        "https://api.alpaca.markets/v2/orders",
        "https://paper-api.alpaca.markets/v2/orders?status=open",
        "https://paper-api.alpaca.markets/v2/orders/..",
    ):
        with pytest.raises(AlpacaPaperError, match="target is not allowed"):
            _urlopen_paper_mutation(_request("POST", url), opener=post_opener)
    with pytest.raises(AlpacaPaperError, match="target is not allowed"):
        _urlopen_paper_mutation(_request("POST", post.full_url, body=b"{}"), opener=post_opener)
    assert post_opener.calls == [(post, 10)]


def test_paper_mutation_transport_rejects_redirect_status_and_large_response() -> None:
    request = _request("POST", "https://paper-api.alpaca.markets/v2/orders")
    cases = (
        (_Response("https://example.com", status=200, body=b"{}"), "redirected"),
        (_Response(request.full_url, status=201, body=b"{}"), "HTTP status 201"),
        (
            _Response(
                request.full_url,
                status=200,
                body=b"x" * (1024 * 1024 + 1),
                content_type="application/json",
            ),
            "too large",
        ),
    )
    for response, message in cases:
        with pytest.raises(AlpacaPaperError, match=message):
            _urlopen_paper_mutation(request, opener=_Opener(response))
    with pytest.raises(AlpacaPaperError, match="^Alpaca paper mutation failed$"):
        _urlopen_paper_mutation(request, opener=_FailingOpener())


def test_production_paper_operator_requires_exact_process_opt_in(
    tmp_path: Path,
) -> None:
    request = PaperWriteRequest("a" * 64, "b" * 40)
    runtime_identity = InstalledRuntimeIdentity(
        build_identity_fingerprint="c" * 64,
        source_commit=request.code_commit,
        wheel_sha256="d" * 64,
        distribution_record_sha256="e" * 64,
        source_files_fingerprint="f" * 64,
        verified_at=datetime(2026, 8, 4, tzinfo=UTC),
    )

    with pytest.raises(PermissionError, match="broker writes are disabled"):
        AlpacaPaperOperator(
            tmp_path / "execution.sqlite3",
            "test-key",
            "test-secret",
            settings=Settings(TradingMode.PAPER, tmp_path),
            limits=load_risk_limits(Path("config/risk/alpaca-paper-v1.json")),
            runtime_identity=runtime_identity,
        )
    assert not (tmp_path / "execution.sqlite3").exists()

    operator = AlpacaPaperOperator(
        tmp_path / "execution.sqlite3",
        "test-key",
        "test-secret",
        settings=Settings(TradingMode.PAPER, tmp_path, request),
        limits=load_risk_limits(Path("config/risk/alpaca-paper-v1.json")),
        runtime_identity=runtime_identity,
    )
    assert operator is not None
    assert not (tmp_path / "execution.sqlite3").exists()
