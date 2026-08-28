"""Private, GET-only Alpaca SIP acquisition for Program 005."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from .calendar import expected_bar_timestamps, expected_sessions
from .domain import Timeframe
from .fingerprints import canonical_json, fingerprint

_PLAN_PATH = Path("config/research/program-005-free-alpaca-successor-plan-v1.json")
_PLAN_SHA256 = "3a71573086418aa8ff53d8359110dee1a951caa333ffd35eccedd8d38678cb11"
_PLAN_FINGERPRINT = "79a73d143700c643d67c2f862b5bfe3655df9706276a1b70e189c425d4397cb7"
_RETENTION_PATH = Path("config/research/program-005-private-data-retention-policy-v1.json")
_RETENTION_SHA256 = "af2c733852e65d3958553d64e214b11856f0d44e2cf11c876839e61a9ce62ac7"
_RETENTION_FINGERPRINT = "0b14f3afdd012a4b8f3e021ddaee1460528b70b5509f2bee92371378a65953e0"
_PUBLIC_CONTRACT_PATH = Path("config/research/program-005-public-dataset-contract-v1.json")
_PUBLIC_CONTRACT_SHA256 = "4f9a7c8b7e1efe9ffe20235cf88f26b2eefc71f27c483539b79d3ee7a52784ae"
_PUBLIC_CONTRACT_FINGERPRINT = "9e3e91e1e28a76f3bf636c64e2e2d52b6a9886171f740ed71ca29bf1bbd79415"
_ACTION_LEDGER_PATH = Path("config/research/program-005-corporate-action-ledger-v1.json")
_ACTION_LEDGER_SHA256 = "0e9b24d27085cc97108cc614697e5655cfc0b8aa42d09251504acc12e659da0f"
_ACTION_LEDGER_FINGERPRINT = "a7b1e169e2add558f3ca991f565646cdd00d1fa56598cbcba8f0755252f32efb"
_ORIGIN = "https://data.alpaca.markets"
_ENDPOINT = f"{_ORIGIN}/v2/stocks/bars"
_CREDENTIAL_NAMES = (
    "PROGRAM_005_ALPACA_API_KEY_ID",
    "PROGRAM_005_ALPACA_API_SECRET_KEY",
)
_MAX_PAGE_BYTES = 64 * 1024**2
_RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
_AUTHORITY_FALSE_KEYS = frozenset(
    {
        "strategy_implementation",
        "strategy_execution",
        "research_qualification",
        "controlled_evaluation",
        "protected_holdout",
        "paper_execution",
        "broker_writes",
        "live_execution",
    }
)
_AUTHORITY_SOURCE_PATHS = (
    Path("pyproject.toml"),
    Path("scripts/check_secrets.py"),
    Path("src/systematic_trading_lab/__init__.py"),
    Path("src/systematic_trading_lab/calendar.py"),
    Path("src/systematic_trading_lab/cli.py"),
    Path("src/systematic_trading_lab/config.py"),
    Path("src/systematic_trading_lab/domain.py"),
    Path("src/systematic_trading_lab/fingerprints.py"),
    Path("src/systematic_trading_lab/program_005_alpaca.py"),
    Path("uv.lock"),
)
_FIXED_BLOCKS = (
    ("discovery-01", date(2020, 7, 27), date(2021, 1, 22)),
    ("discovery-02", date(2021, 1, 25), date(2021, 7, 23)),
    ("discovery-03", date(2021, 7, 26), date(2022, 1, 21)),
    ("wf-01", date(2022, 1, 24), date(2022, 7, 25)),
    ("wf-02", date(2022, 7, 26), date(2023, 1, 24)),
    ("wf-03", date(2023, 1, 25), date(2023, 7, 26)),
    ("wf-04", date(2023, 7, 27), date(2024, 1, 25)),
    ("wf-05", date(2024, 1, 26), date(2024, 7, 26)),
    ("wf-06", date(2024, 7, 29), date(2025, 1, 28)),
    ("wf-07", date(2025, 1, 29), date(2025, 7, 30)),
    ("wf-08", date(2025, 7, 31), date(2026, 1, 29)),
    ("wf-09-final-exposed", date(2026, 1, 30), date(2026, 7, 31)),
)


class Program005Error(ValueError):
    """Fail-closed Program 005 boundary error."""


class Program005TransportError(Program005Error):
    def __init__(self, message: str, *, status: int | None, retryable: bool) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


@dataclass(frozen=True)
class ContractBundle:
    repository: Path
    plan: Mapping[str, Any]
    retention: Mapping[str, Any]
    public_contract: Mapping[str, Any]
    action_ledger: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in ("plan", "retention", "public_contract", "action_ledger"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


@dataclass(frozen=True)
class RequestChain:
    chain_id: str
    range_id: str
    adjustment: str
    start: datetime
    end: datetime
    symbols: tuple[str, ...]
    session_dates: tuple[date, ...]
    maximum_pages: int
    reused_from_qualification: bool = False

    def __post_init__(self) -> None:
        if (
            self.adjustment not in {"raw", "split,spin-off"}
            or self.start.tzinfo is None
            or self.start.utcoffset() != UTC.utcoffset(self.start)
            or self.end.tzinfo is None
            or self.end.utcoffset() != UTC.utcoffset(self.end)
            or self.start > self.end
            or not self.symbols
            or tuple(sorted(self.symbols)) != self.symbols
            or self.maximum_pages < 1
        ):
            raise Program005Error("Program 005 request chain is invalid")
        expected = tuple(
            point.date()
            for point in expected_bar_timestamps(self.start, self.end, Timeframe.FIVE_MINUTES)
        )
        if tuple(dict.fromkeys(expected)) != self.session_dates:
            raise Program005Error("Program 005 request sessions differ from XNYS")

    @property
    def parameters(self) -> tuple[tuple[str, str], ...]:
        return (
            ("symbols", ",".join(self.symbols)),
            ("start", _iso_utc(self.start)),
            ("end", _iso_utc(self.end)),
            ("feed", "sip"),
            ("timeframe", "5Min"),
            ("adjustment", self.adjustment),
            ("sort", "asc"),
            ("limit", "10000"),
            ("asof", "2026-07-31"),
        )

    def url(self, page_token: str | None = None) -> str:
        parameters = self.parameters
        if page_token is not None:
            if not page_token:
                raise Program005Error("Alpaca page token must be non-empty")
            parameters = (*parameters, ("page_token", page_token))
        return f"{_ENDPOINT}?{urlencode(parameters)}"

    @property
    def identity(self) -> str:
        return fingerprint(
            {
                "chain_id": self.chain_id,
                "method": "GET",
                "endpoint": _ENDPOINT,
                "parameters": dict(self.parameters),
                "maximum_pages": self.maximum_pages,
            }
        )


@dataclass(frozen=True)
class HttpPage:
    status: int
    body: bytes
    final_url: str
    headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


@dataclass(frozen=True, order=True)
class CanonicalBar:
    timestamp: datetime
    symbol: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trade_count: int | None = field(compare=False, default=None)
    vwap: Decimal | None = field(compare=False, default=None)

    def record(self) -> Mapping[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": _iso_utc(self.timestamp),
            "open": str(self.open),
            "high": str(self.high),
            "low": str(self.low),
            "close": str(self.close),
            "volume": str(self.volume),
            "trade_count": self.trade_count,
            "vwap": None if self.vwap is None else str(self.vwap),
        }

    @property
    def coordinate(self) -> tuple[str, datetime]:
        return self.symbol, self.timestamp


@dataclass(frozen=True)
class StoredPage:
    index: int
    body: bytes
    sha256: str
    request_url: str
    incoming_token: str | None
    outgoing_token: str | None
    retrieved_at: str


@dataclass
class AcquisitionBudget:
    maximum_responses: int
    maximum_bytes: int
    responses: int = 0
    response_bytes: int = 0

    def add(self, body: bytes) -> None:
        if self.responses >= self.maximum_responses:
            raise Program005Error("Program 005 HTTP response ceiling exceeded")
        if len(body) > _MAX_PAGE_BYTES:
            raise Program005Error("Program 005 response page exceeds 64 MiB")
        if self.response_bytes + len(body) > self.maximum_bytes:
            raise Program005Error("Program 005 downloaded-byte ceiling exceeded")
        self.responses += 1
        self.response_bytes += len(body)


class RequestPacer:
    def __init__(
        self,
        *,
        interval_seconds: float = 0.5,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = interval_seconds
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def __call__(self) -> None:
        now = self._clock()
        if self._last is not None:
            remaining = self._interval - (now - self._last)
            if remaining > 0:
                self._sleep(remaining)
                now = self._clock()
        self._last = now


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(  # type: ignore[override]
        self,
        req: Request,
        fp: BinaryIO,
        code: int,
        msg: str,
        headers: Mapping[str, str],
        newurl: str,
    ) -> None:
        return None


def _urlopen_page(request: Request) -> HttpPage:
    try:
        with build_opener(_NoRedirect()).open(request, timeout=30) as response:
            body = response.read(_MAX_PAGE_BYTES + 1)
            return HttpPage(
                int(response.status),
                body,
                str(response.geturl()),
                dict(response.headers.items()),
            )
    except HTTPError as error:
        body = error.read(_MAX_PAGE_BYTES + 1)
        return HttpPage(error.code, body, str(error.geturl()), dict(error.headers.items()))


class AlpacaBarsClient:
    def __init__(
        self,
        key_id: str,
        secret_key: str,
        *,
        transport: Callable[[Request], HttpPage] = _urlopen_page,
        pace: Callable[[], None] | None = None,
    ) -> None:
        if not key_id or not secret_key:
            raise Program005Error("Program 005 acquisition credentials are required")
        self._headers = {
            "Accept": "application/json",
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
        }
        self._transport = transport
        self._pace = RequestPacer() if pace is None else pace

    def get(self, chain: RequestChain, page_token: str | None = None) -> HttpPage:
        url = chain.url(page_token)
        _validate_request_url(url, chain)
        request = Request(url, headers=self._headers, method="GET")
        self._pace()
        try:
            page = self._transport(request)
        except (TimeoutError, ConnectionError, URLError, OSError) as error:
            raise Program005TransportError(
                "Program 005 transport disconnected",
                status=None,
                retryable=True,
            ) from error
        if page.status != 200:
            raise Program005TransportError(
                f"Program 005 provider returned HTTP {page.status}",
                status=page.status,
                retryable=page.status in _RETRYABLE_STATUSES,
            )
        if len(page.body) > _MAX_PAGE_BYTES:
            raise Program005Error("Program 005 response page exceeds 64 MiB")
        parsed = urlsplit(page.final_url)
        if (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
        ) != ("https", "data.alpaca.markets", "/v2/stocks/bars"):
            raise Program005TransportError(
                "Program 005 response redirected outside the frozen endpoint",
                status=page.status,
                retryable=False,
            )
        return page


def load_contract(repository: Path) -> ContractBundle:
    repository = repository.resolve()
    plan = _load_bound_artifact(
        repository / _PLAN_PATH,
        _PLAN_SHA256,
        "plan_fingerprint",
        _PLAN_FINGERPRINT,
        "Program 005 plan",
    )
    retention = _load_bound_artifact(
        repository / _RETENTION_PATH,
        _RETENTION_SHA256,
        "policy_fingerprint",
        _RETENTION_FINGERPRINT,
        "Program 005 retention policy",
    )
    public_contract = _load_bound_artifact(
        repository / _PUBLIC_CONTRACT_PATH,
        _PUBLIC_CONTRACT_SHA256,
        "contract_fingerprint",
        _PUBLIC_CONTRACT_FINGERPRINT,
        "Program 005 public dataset contract",
    )
    action_ledger = _load_bound_artifact(
        repository / _ACTION_LEDGER_PATH,
        _ACTION_LEDGER_SHA256,
        "ledger_fingerprint",
        _ACTION_LEDGER_FINGERPRINT,
        "Program 005 corporate-action ledger",
    )
    if (
        plan.get("schema_version") != "program-005-free-alpaca-successor-plan-v1"
        or retention.get("schema_version") != "program-005-private-data-retention-policy-v1"
        or public_contract.get("schema_version") != "program-005-public-dataset-contract-v1"
        or action_ledger.get("schema_version") != "program-005-corporate-action-ledger-v1"
        or retention.get("authority", {}).get("source_requests") is not False
        or public_contract.get("observation_count") != 0
        or action_ledger.get("provider_observation_count") != 0
    ):
        raise Program005Error("Program 005 public contract artifacts differ")
    _require_binding(
        retention.get("resolved_plan_binding"),
        _PLAN_PATH,
        _PLAN_SHA256,
        _PLAN_FINGERPRINT,
        "retention plan binding",
    )
    _require_binding(
        public_contract.get("retention_policy"),
        _RETENTION_PATH,
        _RETENTION_SHA256,
        _RETENTION_FINGERPRINT,
        "public retention binding",
    )
    _require_binding(
        public_contract.get("corporate_action_ledger"),
        _ACTION_LEDGER_PATH,
        _ACTION_LEDGER_SHA256,
        _ACTION_LEDGER_FINGERPRINT,
        "public corporate-action ledger binding",
    )
    ledger_bindings = _mapping(action_ledger.get("bindings"), "action-ledger bindings")
    _require_binding(
        ledger_bindings.get("program_plan"),
        _PLAN_PATH,
        _PLAN_SHA256,
        _PLAN_FINGERPRINT,
        "action-ledger plan binding",
    )
    _require_binding(
        ledger_bindings.get("retention_policy"),
        _RETENTION_PATH,
        _RETENTION_SHA256,
        _RETENTION_FINGERPRINT,
        "action-ledger retention binding",
    )
    return ContractBundle(repository, plan, retention, public_contract, action_ledger)


def build_request_plan(bundle: ContractBundle, scope: str) -> tuple[RequestChain, ...]:
    if scope not in {"qualification", "full"}:
        raise Program005Error("Program 005 scope must be qualification or full")
    qualification = _qualification_chains(bundle.plan)
    if scope == "qualification":
        return qualification
    full = _mapping(bundle.plan.get("full_acquisition_design"), "full acquisition design")
    exact_range = _mapping(full.get("exact_range"), "full acquisition range")
    start = date.fromisoformat(str(exact_range.get("start")))
    end = date.fromisoformat(str(exact_range.get("end")))
    sessions = expected_sessions(_day_start(start), _day_end(end))
    qualification_sessions = {day for chain in qualification for day in chain.session_dates}
    additional: list[RequestChain] = []
    symbols = qualification[0].symbols
    for session in sessions:
        if session in qualification_sessions:
            continue
        timestamps = expected_bar_timestamps(
            _day_start(session), _day_end(session), Timeframe.FIVE_MINUTES
        )
        if not timestamps:
            raise Program005Error("Program 005 full range contains an empty XNYS session")
        range_id = f"full-{session.isoformat()}"
        for adjustment, suffix in (("raw", "raw"), ("split,spin-off", "split-spin-off")):
            additional.append(
                RequestChain(
                    f"{range_id}--{suffix}",
                    range_id,
                    adjustment,
                    timestamps[0],
                    timestamps[-1],
                    symbols,
                    (session,),
                    _integer(full.get("maximum_pages_per_chain"), "full chain page limit"),
                )
            )
    reused = tuple(
        RequestChain(
            chain.chain_id,
            chain.range_id,
            chain.adjustment,
            chain.start,
            chain.end,
            chain.symbols,
            chain.session_dates,
            chain.maximum_pages,
            True,
        )
        for chain in qualification
    )
    result = (*reused, *additional)
    if (
        len(sessions) != exact_range.get("expected_xnys_sessions")
        or len(additional) != full.get("maximum_additional_logical_chains")
        or len(result) != 3044
    ):
        raise Program005Error("Program 005 full request plan differs")
    return result


def credential_free_preflight(repository: Path, scope: str) -> Mapping[str, Any]:
    bundle = load_contract(repository)
    chains = build_request_plan(bundle, scope)
    acquired = tuple(chain for chain in chains if not chain.reused_from_qualification)
    if scope == "qualification":
        budget = _mapping(
            _mapping(bundle.plan.get("source_qualification"), "source qualification").get(
                "transport_budget"
            ),
            "qualification transport budget",
        )
        maximum_responses = _integer(
            budget.get("maximum_http_responses"), "qualification response limit"
        )
        maximum_bytes = _integer(budget.get("maximum_downloaded_bytes"), "qualification byte limit")
        expected_responses = _integer(
            budget.get("expected_http_responses"), "qualification expected responses"
        )
    else:
        full = _mapping(bundle.plan.get("full_acquisition_design"), "full acquisition design")
        maximum_responses = _integer(
            full.get("maximum_additional_http_responses"), "full response limit"
        )
        maximum_bytes = _integer(full.get("maximum_source_bytes"), "full byte limit")
        expected_responses = _integer(
            full.get("expected_additional_http_responses"), "full expected responses"
        )
    request_fingerprint = fingerprint([chain.identity for chain in chains])
    acquired_fingerprint = fingerprint([chain.identity for chain in acquired])
    return {
        "schema_version": "program-005-credential-free-preflight-v1",
        "program_id": "multi-hour-sector-etf-research-004",
        "scope": scope,
        "method": "GET",
        "origin": _ORIGIN,
        "path": "/v2/stocks/bars",
        "feed": "sip",
        "timeframe": "5Min",
        "adjustments": ["raw", "split,spin-off"],
        "asof": "2026-07-31",
        "requests_per_minute": 120,
        "logical_chain_count": len(chains),
        "reused_qualification_chain_count": len(chains) - len(acquired),
        "request_chains_to_acquire": len(acquired),
        "expected_http_responses_to_acquire": expected_responses,
        "maximum_http_responses_to_acquire": maximum_responses,
        "maximum_downloaded_bytes": maximum_bytes,
        "maximum_credential_loads": 1,
        "automatic_transport_retries": 0,
        "request_plan_fingerprint": request_fingerprint,
        "acquisition_plan_fingerprint": acquired_fingerprint,
        "plan_sha256": _PLAN_SHA256,
        "retention_policy_sha256": _RETENTION_SHA256,
        "public_contract_sha256": _PUBLIC_CONTRACT_SHA256,
        "action_ledger_sha256": _ACTION_LEDGER_SHA256,
        "credential_loaded": False,
        "provider_request_made": False,
        "strategy_calculation_allowed": False,
        "controlled_or_protected_access_allowed": False,
    }


def read_credentials(environ: Mapping[str, str] | None = None) -> tuple[str, str]:
    values = os.environ if environ is None else environ
    key_id, secret_key = (values.get(name, "").strip() for name in _CREDENTIAL_NAMES)
    if not key_id or not secret_key:
        raise Program005Error("Program 005 acquisition credentials are required")
    return key_id, secret_key


def parse_bars_page(
    body: bytes, chain: RequestChain
) -> tuple[tuple[CanonicalBar, ...], str | None]:
    payload = _load_provider_json(body)
    if "next_page_token" not in payload:
        raise Program005Error("Alpaca response omits next_page_token")
    next_token = payload.get("next_page_token")
    if next_token is not None and (not isinstance(next_token, str) or not next_token):
        raise Program005Error("Alpaca next_page_token is malformed")
    bars_value = payload.get("bars")
    if not isinstance(bars_value, Mapping):
        raise Program005Error("Alpaca response bars must be an object")
    allowed_timestamps = set(
        expected_bar_timestamps(chain.start, chain.end, Timeframe.FIVE_MINUTES)
    )
    allowed_symbols = set(chain.symbols)
    bars: list[CanonicalBar] = []
    coordinates: set[tuple[str, datetime]] = set()
    for symbol, rows_value in bars_value.items():
        if not isinstance(symbol, str) or symbol not in allowed_symbols:
            raise Program005Error("Alpaca response contains a foreign symbol")
        if not isinstance(rows_value, list):
            raise Program005Error("Alpaca symbol bars must be a list")
        for raw in rows_value:
            row = _mapping(raw, "Alpaca bar")
            timestamp = _parse_bar_timestamp(row.get("t"))
            if timestamp not in allowed_timestamps:
                raise Program005Error("Alpaca bar timestamp is outside the exact XNYS grid")
            bar = CanonicalBar(
                timestamp,
                symbol,
                _positive_decimal(row.get("o"), "open"),
                _positive_decimal(row.get("h"), "high"),
                _positive_decimal(row.get("l"), "low"),
                _positive_decimal(row.get("c"), "close"),
                _positive_decimal(row.get("v"), "volume"),
                _optional_nonnegative_integer(row.get("n"), "trade count"),
                _optional_positive_decimal(row.get("vw"), "VWAP"),
            )
            if bar.high < max(bar.open, bar.low, bar.close) or bar.low > min(
                bar.open, bar.high, bar.close
            ):
                raise Program005Error("Alpaca OHLC range is invalid")
            if bar.coordinate in coordinates:
                raise Program005Error("Alpaca response contains a duplicate coordinate")
            coordinates.add(bar.coordinate)
            bars.append(bar)
    return tuple(sorted(bars)), next_token


def acquire_chain(
    chain: RequestChain,
    chain_root: Path,
    client: AlpacaBarsClient,
    budget: AcquisitionBudget,
    *,
    source_commit: str,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[CanonicalBar, ...]:
    chain_root.mkdir(parents=True, exist_ok=True)
    checkpoint = _load_checkpoint(chain_root, chain)
    page_index = int(checkpoint["completed_pages"]) + 1
    incoming_token = checkpoint.get("next_page_token")
    seen_tokens = set(_strings(checkpoint.get("seen_page_tokens"), "seen page tokens"))
    page_hashes = list(_strings(checkpoint.get("page_sha256s"), "page hashes"))
    seen_hashes = set(page_hashes)
    terminal = bool(checkpoint.get("terminal"))
    budgeted_hashes: set[str] = set()

    while not terminal:
        if page_index > chain.maximum_pages:
            raise Program005Error("Program 005 chain page ceiling exceeded")
        stored_root = chain_root / "pages" / f"{page_index:05d}"
        if stored_root.exists():
            stored = _load_stored_page(stored_root, chain, page_index, incoming_token)
            budget.add(stored.body)
        else:
            http_page = client.get(
                chain, incoming_token if isinstance(incoming_token, str) else None
            )
            budget.add(http_page.body)
            _, outgoing_token = parse_bars_page(http_page.body, chain)
            stored = _store_page(
                stored_root,
                chain,
                page_index,
                http_page,
                incoming_token if isinstance(incoming_token, str) else None,
                outgoing_token,
                source_commit,
                now,
            )
        budgeted_hashes.add(stored.sha256)
        if stored.sha256 in seen_hashes:
            raise Program005Error("Program 005 response page repeated")
        seen_hashes.add(stored.sha256)
        page_hashes.append(stored.sha256)
        outgoing = stored.outgoing_token
        if outgoing is not None:
            if outgoing in seen_tokens or outgoing == incoming_token:
                raise Program005Error("Program 005 next_page_token repeated")
            seen_tokens.add(outgoing)
        terminal = outgoing is None
        incoming_token = outgoing
        checkpoint = {
            "schema_version": "program-005-private-chain-checkpoint-v1",
            "chain_identity": chain.identity,
            "completed_pages": page_index,
            "next_page_token": incoming_token,
            "seen_page_tokens": sorted(seen_tokens),
            "page_sha256s": page_hashes,
            "terminal": terminal,
        }
        _replace_record(chain_root / "checkpoint.json", checkpoint)
        page_index += 1

    pages = _load_chain_pages(chain_root, chain)
    for stored_page in pages:
        if stored_page.sha256 not in budgeted_hashes:
            budget.add(stored_page.body)
    if chain.range_id.startswith("pagination-split-") and len(pages) < 2:
        raise Program005Error("Program 005 pagination control did not paginate")
    bars: list[CanonicalBar] = []
    coordinates: set[tuple[str, datetime]] = set()
    for page in pages:
        page_bars, _ = parse_bars_page(page.body, chain)
        for bar in page_bars:
            if bar.coordinate in coordinates:
                raise Program005Error("Program 005 chain contains a duplicate coordinate")
            coordinates.add(bar.coordinate)
            bars.append(bar)
    return tuple(sorted(bars))


def load_chain(chain: RequestChain, chain_root: Path) -> tuple[CanonicalBar, ...]:
    checkpoint = _load_checkpoint(chain_root, chain)
    if checkpoint.get("terminal") is not True:
        raise Program005Error("Program 005 chain is incomplete")
    pages = _load_chain_pages(chain_root, chain)
    if chain.range_id.startswith("pagination-split-") and len(pages) < 2:
        raise Program005Error("Program 005 pagination control did not paginate")
    bars: list[CanonicalBar] = []
    coordinates: set[tuple[str, datetime]] = set()
    for page in pages:
        page_bars, _ = parse_bars_page(page.body, chain)
        for bar in page_bars:
            if bar.coordinate in coordinates:
                raise Program005Error("Program 005 chain contains a duplicate coordinate")
            coordinates.add(bar.coordinate)
            bars.append(bar)
    return tuple(sorted(bars))


def validate_action_pair(
    raw_bars: Sequence[CanonicalBar],
    analytical_bars: Sequence[CanonicalBar],
    ledger: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    raw = {bar.coordinate: bar for bar in raw_bars}
    analytical = {bar.coordinate: bar for bar in analytical_bars}
    if raw.keys() != analytical.keys():
        raise Program005Error("Program 005 raw and analytical coordinate sets differ")
    factors: dict[tuple[str, date], Decimal] = {}
    observations: list[Mapping[str, Any]] = []
    for coordinate in sorted(raw, key=lambda item: (item[1], item[0])):
        raw_bar = raw[coordinate]
        adjusted_bar = analytical[coordinate]
        price_factor = adjusted_bar.open / raw_bar.open
        if not price_factor.is_finite() or price_factor <= 0:
            raise Program005Error("Program 005 action price factor is invalid")
        if any(
            adjusted != source * price_factor
            for adjusted, source in (
                (adjusted_bar.open, raw_bar.open),
                (adjusted_bar.high, raw_bar.high),
                (adjusted_bar.low, raw_bar.low),
                (adjusted_bar.close, raw_bar.close),
            )
        ):
            raise Program005Error("Program 005 action price factor is not constant")
        if adjusted_bar.volume * price_factor != raw_bar.volume:
            raise Program005Error("Program 005 action volume is not reciprocal")
        session_key = (raw_bar.symbol, raw_bar.timestamp.date())
        if session_key in factors and factors[session_key] != price_factor:
            raise Program005Error("Program 005 action factor changes within a session")
        factors[session_key] = price_factor
    for (symbol, session), observed in sorted(factors.items()):
        expected = _expected_price_factor(ledger, symbol, session)
        if observed != expected:
            raise Program005Error("Program 005 action factor is absent from the frozen ledger")
        observations.append(
            {
                "symbol": symbol,
                "session": session.isoformat(),
                "analytical_price_factor": str(observed),
                "analytical_volume_factor": str(Decimal(1) / observed),
            }
        )
    return tuple(observations)


def _assess_fixed_quarantine_contract(
    plan: Mapping[str, Any],
    quarantine_values: Sequence[str],
    known_coordinate_values: Sequence[str],
    full_sessions: set[date],
    all_sessions: Sequence[date],
) -> tuple[Mapping[str, Any], set[str]]:
    policy = _mapping(plan.get("missing_data_policy"), "missing-data policy")
    quarantine_policy = _mapping(
        policy.get("pre_exposed_design_quarantine"), "pre-exposed quarantine"
    )
    limits = _mapping(policy.get("concentration_limits"), "missingness concentration limits")
    contract = _mapping(
        limits.get("pre_exposed_design_quarantine_concentration_contract"),
        "fixed quarantine concentration contract",
    )
    chronology = _mapping(plan.get("chronology_and_protected_boundaries"), "chronology")
    quarantine = {date.fromisoformat(value) for value in quarantine_values}
    known_coordinates = set(known_coordinate_values)
    failures: set[str] = set()
    checks: dict[str, bool] = {}

    def check(name: str, passed: bool) -> None:
        checks[name] = passed
        if not passed:
            failures.add(f"fixed-quarantine:{name}")

    coordinate_dates = {
        _parse_bar_timestamp(value.split("@", 1)[1]).date()
        for value in known_coordinates
        if "@" in value
    }
    incident_binding = _mapping(
        quarantine_policy.get("incident_inventory_binding"), "quarantine incident binding"
    )
    check(
        "membership",
        len(quarantine) == len(quarantine_values)
        and len(known_coordinates) == len(known_coordinate_values)
        and quarantine_policy.get("session_count") == len(quarantine)
        and quarantine_policy.get("incident_coordinate_count") == len(known_coordinates)
        and coordinate_dates == quarantine
        and all(value.startswith("MDY@") for value in known_coordinates)
        and quarantine_policy.get("incident_inventory_complete") is True
        and quarantine_policy.get("selected_subset_allowed") is False
        and quarantine_policy.get("future_membership_allowed") is False
        and incident_binding.get("coordinate_inventory_target")
        == "source_qualification.known_mdy_coordinates"
        and contract.get("eligibility_is_reusable_for_future_incidents") is False
        and contract.get("post_acquisition_change_or_waiver_allowed") is False,
    )

    recorded_pre_counts = _mapping(
        contract.get("pre_quarantine_full_trade_eligible_sessions_by_discovery_block"),
        "fixed quarantine pre-counts",
    )
    block_ids = tuple(str(value) for value in recorded_pre_counts)
    pre_counts = {
        block_id: sum(_block_id(session) == block_id for session in full_sessions)
        for block_id in block_ids
    }
    fixed_counts = {
        block_id: sum(_block_id(session) == block_id for session in quarantine)
        for block_id in block_ids
    }
    post_counts = {
        block_id: pre_counts[block_id] - fixed_counts[block_id] for block_id in block_ids
    }
    check(
        "block-counts",
        dict(recorded_pre_counts) == pre_counts
        and dict(
            _mapping(
                contract.get("fixed_counts_by_predeclared_discovery_block"),
                "fixed quarantine block counts",
            )
        )
        == {key: value for key, value in fixed_counts.items() if value}
        and dict(
            _mapping(
                contract.get("post_quarantine_full_trade_eligible_sessions_by_discovery_block"),
                "fixed quarantine post-counts",
            )
        )
        == post_counts,
    )
    minimum_retained = _integer(
        contract.get("minimum_retained_full_sessions_per_discovery_block"),
        "fixed quarantine block retention floor",
    )
    check("block-retention", min(post_counts.values()) >= minimum_retained)
    pre_difference = max(pre_counts.values()) - min(pre_counts.values())
    post_difference = max(post_counts.values()) - min(post_counts.values())
    check(
        "block-balance",
        pre_difference
        == _integer(
            contract.get("pre_quarantine_maximum_discovery_block_session_count_difference"),
            "fixed quarantine pre-balance",
        )
        and post_difference
        == _integer(
            contract.get("post_quarantine_maximum_discovery_block_session_count_difference"),
            "fixed quarantine post-balance",
        )
        and post_difference <= pre_difference,
    )

    context_start = date.fromisoformat(str(chronology.get("context_start")))
    context_end = date.fromisoformat(str(chronology.get("context_end")))
    quarantine_blocks = {_block_id(session) for session in quarantine}
    context_count = sum(context_start <= session <= context_end for session in quarantine)
    walk_forward_count = sum(block_id.startswith("wf-") for block_id in quarantine_blocks)
    controlled_count = 0
    for name in ("controlled_a", "controlled_b"):
        controlled = _mapping(chronology.get(name), name)
        controlled_start = date.fromisoformat(str(controlled.get("start")))
        controlled_end = date.fromisoformat(str(controlled.get("end")))
        controlled_count += sum(
            controlled_start <= session <= controlled_end for session in quarantine
        )
    check(
        "protected-boundaries",
        all(block_id.startswith("discovery-") for block_id in quarantine_blocks)
        and context_count == contract.get("pre_exposed_quarantine_sessions_in_initial_context") == 0
        and walk_forward_count
        == contract.get("pre_exposed_quarantine_sessions_in_walk_forward_test_folds")
        == 0
        and controlled_count
        == contract.get("pre_exposed_quarantine_sessions_in_controlled_blocks")
        == 0,
    )
    session_index = {session: index for index, session in enumerate(all_sessions)}
    ordered_indexes = sorted(session_index[session] for session in quarantine)
    maximum_consecutive = 1
    current_consecutive = 1
    for left, right in zip(ordered_indexes, ordered_indexes[1:], strict=False):
        current_consecutive = current_consecutive + 1 if right == left + 1 else 1
        maximum_consecutive = max(maximum_consecutive, current_consecutive)
    check(
        "nonadjacency",
        maximum_consecutive
        == contract.get("observed_maximum_consecutive_fixed_quarantine_sessions")
        and maximum_consecutive
        <= _integer(
            contract.get("maximum_consecutive_fixed_quarantine_sessions"),
            "fixed quarantine consecutive limit",
        ),
    )

    calendar_contract = _mapping(
        contract.get("calendar_concentration_contract"), "fixed quarantine calendar contract"
    )
    affected_months: dict[str, Mapping[str, int]] = {}
    for month in sorted({session.strftime("%Y-%m") for session in quarantine}):
        year, month_number = (int(value) for value in month.split("-"))
        before = sum(
            session.year == year and session.month == month_number for session in full_sessions
        )
        fixed = sum(
            session.year == year and session.month == month_number for session in quarantine
        )
        affected_months[month] = {
            "full_sessions_before_quarantine": before,
            "fixed_quarantine_sessions": fixed,
            "retained_full_sessions": before - fixed,
        }
    discovery_start = date.fromisoformat(str(chronology.get("discovery_start")))
    exposed_end = date.fromisoformat(str(chronology.get("exposed_end")))
    complete_years = {
        session.year
        for session in quarantine
        if session.year not in {discovery_start.year, exposed_end.year}
    }
    affected_complete_years = {
        str(year): {
            "full_sessions_before_quarantine": sum(
                session.year == year for session in full_sessions
            ),
            "fixed_quarantine_sessions": sum(session.year == year for session in quarantine),
            "retained_full_sessions": sum(session.year == year for session in full_sessions)
            - sum(session.year == year for session in quarantine),
        }
        for year in sorted(complete_years)
    }
    partial_years = {session.year for session in quarantine} - complete_years
    affected_partial_years: dict[str, Mapping[str, Any]] = {}
    for year in sorted(partial_years):
        governing_blocks = {_block_id(session) for session in quarantine if session.year == year}
        affected_partial_years[str(year)] = {
            "fixed_quarantine_sessions": sum(session.year == year for session in quarantine),
            "governing_fixed_block": next(iter(governing_blocks))
            if len(governing_blocks) == 1
            else "invalid",
        }
    month_floor = _integer(
        calendar_contract.get("minimum_retained_full_sessions_per_affected_month"),
        "fixed quarantine month floor",
    )
    year_floor = _integer(
        calendar_contract.get("minimum_retained_full_sessions_per_affected_complete_calendar_year"),
        "fixed quarantine year floor",
    )
    check(
        "calendar",
        dict(_mapping(calendar_contract.get("affected_months"), "affected months"))
        == affected_months
        and dict(
            _mapping(
                calendar_contract.get("affected_complete_calendar_years"),
                "affected complete years",
            )
        )
        == affected_complete_years
        and dict(
            _mapping(
                calendar_contract.get("affected_partial_calendar_years"),
                "affected partial years",
            )
        )
        == affected_partial_years
        and all(
            value["retained_full_sessions"] >= month_floor for value in affected_months.values()
        )
        and all(
            value["retained_full_sessions"] >= year_floor
            for value in affected_complete_years.values()
        ),
    )

    new_york = ZoneInfo("America/New_York")
    coordinate_times = {
        value: _parse_bar_timestamp(value.split("@", 1)[1]).astimezone(new_york)
        for value in known_coordinates
    }
    clock_counts = Counter(value.strftime("%H:%M") for value in coordinate_times.values())
    clock_contract = _mapping(
        contract.get("clock_concentration_contract"), "fixed quarantine clock contract"
    )
    recorded_strategy_counts = _mapping(
        clock_contract.get("fixed_sessions_missing_at_exact_strategy_clocks"),
        "fixed quarantine strategy-clock counts",
    )
    strategy_counts = {
        str(name): len(
            {
                timestamp.date()
                for timestamp in coordinate_times.values()
                if timestamp.strftime("%H:%M") == str(name)[:5]
            }
        )
        for name in recorded_strategy_counts
    }
    regular_clock_count = len(
        expected_bar_timestamps(
            _day_start(min(full_sessions)), _day_end(min(full_sessions)), Timeframe.FIVE_MINUTES
        )
    )
    observed_maximum = max(clock_counts.values(), default=0)
    check(
        "clock",
        clock_contract.get("missing_coordinate_count") == len(known_coordinates)
        and clock_contract.get("regular_session_five_minute_clock_count") == regular_clock_count
        and dict(clock_contract.get("fixed_coordinate_counts_by_new_york_clock", {}))
        == dict(sorted(clock_counts.items()))
        and clock_contract.get("uniform_coordinate_reference_population")
        == len(full_sessions) * regular_clock_count
        and clock_contract.get("coordinates_per_clock") == len(full_sessions)
        and clock_contract.get("bonferroni_clock_test_count") == regular_clock_count
        and clock_contract.get("observed_maximum_coordinates_at_one_clock") == observed_maximum
        and observed_maximum
        < _integer(
            clock_contract.get("rejection_count_at_one_clock"),
            "fixed quarantine clock rejection count",
        )
        and dict(recorded_strategy_counts) == strategy_counts
        and max(strategy_counts.values(), default=0)
        <= _integer(
            clock_contract.get("maximum_fixed_sessions_missing_at_any_exact_strategy_clock"),
            "fixed quarantine strategy-clock limit",
        ),
    )
    return {
        "checks": dict(sorted(checks.items())),
        "fixed_counts_by_block": fixed_counts,
        "retained_sessions_by_block": post_counts,
        "affected_months": affected_months,
        "affected_complete_years": affected_complete_years,
        "affected_partial_years": affected_partial_years,
        "fixed_coordinate_counts_by_new_york_clock": dict(sorted(clock_counts.items())),
        "fixed_sessions_missing_at_exact_strategy_clocks": strategy_counts,
    }, failures


def assess_missingness(
    plan: Mapping[str, Any],
    missing_coordinates: Mapping[date, set[str]],
    morning_metrics: Mapping[date, Mapping[str, tuple[Decimal, Decimal, Decimal]]],
) -> Mapping[str, Any]:
    policy = _mapping(plan.get("missing_data_policy"), "missing-data policy")
    quarantine_policy = _mapping(
        policy.get("pre_exposed_design_quarantine"), "pre-exposed quarantine"
    )
    quarantine_values = _strings(quarantine_policy.get("sessions"), "quarantine sessions")
    quarantine = {date.fromisoformat(value) for value in quarantine_values}
    known_coordinate_values = _strings(
        _mapping(plan.get("source_qualification"), "source qualification").get(
            "known_mdy_coordinates"
        ),
        "known MDY coordinates",
    )
    known_coordinates = set(known_coordinate_values)
    chronology = _mapping(plan.get("chronology_and_protected_boundaries"), "chronology")
    context_start = date.fromisoformat(str(chronology.get("context_start")))
    exposed_end = date.fromisoformat(str(chronology.get("exposed_end")))
    all_sessions = expected_sessions(_day_start(context_start), _day_end(exposed_end))
    session_index = {session: index for index, session in enumerate(all_sessions)}
    full_sessions = {
        session
        for session in all_sessions
        if len(
            expected_bar_timestamps(_day_start(session), _day_end(session), Timeframe.FIVE_MINUTES)
        )
        == 78
        and session >= date.fromisoformat(str(chronology.get("discovery_start")))
    }
    failures: set[str] = set()
    fixed_quarantine_diagnostics, fixed_quarantine_failures = _assess_fixed_quarantine_contract(
        plan,
        quarantine_values,
        known_coordinate_values,
        full_sessions,
        all_sessions,
    )
    failures.update(fixed_quarantine_failures)
    unexpected: dict[date, set[str]] = {}
    incomplete_non_trade: set[date] = set()
    for session, coordinates in missing_coordinates.items():
        if session in quarantine:
            if any(coordinate not in known_coordinates for coordinate in coordinates):
                failures.add("quarantine-unexpected-coordinate")
            continue
        symbols = {coordinate.split("@", 1)[0] for coordinate in coordinates}
        if session in full_sessions:
            unexpected[session] = symbols
        else:
            incomplete_non_trade.add(session)
    limits = _mapping(policy.get("concentration_limits"), "missingness concentration limits")
    loss = _mapping(policy.get("global_loss_limit"), "global missingness limit")
    excluded_full = quarantine | set(unexpected)
    if len(excluded_full) > _integer(
        loss.get("overall_excluded_full_session_count_max"), "global exclusion limit"
    ):
        failures.add("global-count")
    if len(unexpected) > _integer(
        loss.get("unexpected_excluded_full_session_count_max"), "unexpected exclusion limit"
    ):
        failures.add("unexpected-count")
    for year, count in Counter(session.year for session in unexpected).items():
        if count > _integer(
            limits.get("unexpected_exclusions_per_calendar_year_max"),
            "annual exclusion limit",
        ):
            failures.add(f"calendar-year:{year}")
    block_by_session = {session: _block_id(session) for session in full_sessions}
    unexpected_by_block = Counter(block_by_session[session] for session in unexpected)
    for block, count in unexpected_by_block.items():
        if count > _integer(
            limits.get("unexpected_exclusions_per_predeclared_discovery_or_test_block_max"),
            "fixed-block exclusion limit",
        ):
            failures.add(f"fixed-block:{block}")
    quarantine_blocks = {block_by_session[session] for session in quarantine}
    if (
        limits.get(
            "unexpected_exclusion_in_block_or_rolling_63_window_containing_the_pre_exposed_design_quarantine_allowed"
        )
        is not True
    ):
        for session in unexpected:
            if block_by_session[session] in quarantine_blocks:
                failures.add("quarantine-block")
    ordered_excluded = sorted(session_index[session] for session in excluded_full)
    if any(
        right == left + 1
        for left, right in zip(ordered_excluded, ordered_excluded[1:], strict=False)
    ):
        failures.add("adjacent")
    rolling = _integer(limits.get("unexpected_exclusion_rolling_window_sessions"), "rolling window")
    unexpected_indexes = {session: session_index[session] for session in unexpected}
    if any(
        sum(abs(index - other) < rolling for other in unexpected_indexes.values())
        > _integer(
            limits.get("unexpected_exclusions_per_rolling_63_expected_sessions_max"),
            "rolling exclusion limit",
        )
        for index in unexpected_indexes.values()
    ):
        failures.add("rolling-63")
    quarantine_indexes = {session_index[session] for session in quarantine}
    if any(
        abs(index - fixed) < rolling
        for index in unexpected_indexes.values()
        for fixed in quarantine_indexes
    ):
        failures.add("quarantine-rolling-63")
    same_symbol_window = _integer(
        limits.get("same_missing_symbol_rolling_window_sessions"), "same-symbol window"
    )
    fixed_symbols = {session: {"MDY"} for session in quarantine}
    combined_symbols = {**fixed_symbols, **unexpected}
    for session, symbols in unexpected.items():
        if any(
            other != session
            and abs(session_index[session] - session_index[other]) < same_symbol_window
            and bool(symbols & other_symbols)
            for other, other_symbols in combined_symbols.items()
        ):
            failures.add("same-symbol-rolling-252")
    context_end = date.fromisoformat(str(chronology.get("context_end")))
    if any(context_start <= session <= context_end for session in missing_coordinates):
        failures.add("initial-context")
    bias_report, bias_failures = _assess_morning_bias(
        policy, excluded_full, full_sessions, morning_metrics
    )
    failures.update(bias_failures)
    missing_by_symbol = Counter(
        coordinate.split("@", 1)[0]
        for coordinates in missing_coordinates.values()
        for coordinate in coordinates
    )
    missing_by_clock = Counter(
        coordinate.split("T", 1)[1][0:5]
        for coordinates in missing_coordinates.values()
        for coordinate in coordinates
    )
    report = {
        "schema_version": "program-005-structural-missingness-report-v1",
        "expected_full_trade_eligible_sessions": len(full_sessions),
        "fixed_quarantine_sessions": [session.isoformat() for session in sorted(quarantine)],
        "unexpected_excluded_sessions": [session.isoformat() for session in sorted(unexpected)],
        "incomplete_non_trade_sessions": [
            session.isoformat() for session in sorted(incomplete_non_trade)
        ],
        "excluded_full_session_count": len(excluded_full),
        "retained_full_trade_eligible_sessions": len(full_sessions - excluded_full),
        "missing_coordinate_count": sum(len(value) for value in missing_coordinates.values()),
        "missing_coordinates": sorted(
            coordinate for coordinates in missing_coordinates.values() for coordinate in coordinates
        ),
        "missing_coordinates_by_symbol": dict(sorted(missing_by_symbol.items())),
        "missing_coordinates_by_clock_utc": dict(sorted(missing_by_clock.items())),
        "unexpected_exclusions_by_year": dict(
            sorted(Counter(session.year for session in unexpected).items())
        ),
        "unexpected_exclusions_by_block": dict(sorted(unexpected_by_block.items())),
        "fixed_quarantine_diagnostics": fixed_quarantine_diagnostics,
        "morning_bias_diagnostics": bias_report,
        "failures": sorted(failures),
        "admission_passed": not failures,
        "strategy_metrics_present": False,
    }
    return report


def freeze_dataset(
    bundle: ContractBundle,
    scope: str,
    chains: Sequence[RequestChain],
    private_root: Path,
    *,
    source_commit: str,
) -> Mapping[str, Any]:
    if scope not in {"qualification", "full"}:
        raise Program005Error("Program 005 freeze scope is invalid")
    by_range: dict[str, dict[str, RequestChain]] = defaultdict(dict)
    for chain in chains:
        if chain.adjustment in by_range[chain.range_id]:
            raise Program005Error("Program 005 paired range is duplicated")
        by_range[chain.range_id][chain.adjustment] = chain
    if any(set(pair) != {"raw", "split,spin-off"} for pair in by_range.values()):
        raise Program005Error("Program 005 paired range is incomplete")

    private_root.mkdir(parents=True, exist_ok=True)
    staging_parent = private_root / ".staging"
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{scope}-", dir=staging_parent))
    missing: dict[date, set[str]] = defaultdict(set)
    morning_metrics: dict[date, dict[str, tuple[Decimal, Decimal, Decimal]]] = {}
    action_observations: list[Mapping[str, Any]] = []
    source_pages: list[Mapping[str, Any]] = []
    raw_count = 0
    analytical_count = 0
    try:
        raw_path = staging / "canonical-raw.jsonl"
        analytical_path = staging / "canonical-analytical.jsonl"
        with (
            raw_path.open("x", encoding="utf-8", newline="\n") as raw_file,
            analytical_path.open("x", encoding="utf-8", newline="\n") as analytical_file,
        ):
            ordered_pairs = sorted(by_range.values(), key=lambda pair: pair["raw"].start)
            for pair in ordered_pairs:
                raw_chain = pair["raw"]
                analytical_chain = pair["split,spin-off"]
                raw_root = _chain_root(private_root, scope, raw_chain)
                analytical_root = _chain_root(private_root, scope, analytical_chain)
                raw_bars = load_chain(raw_chain, raw_root)
                analytical_bars = load_chain(analytical_chain, analytical_root)
                action_observations.extend(
                    validate_action_pair(raw_bars, analytical_bars, bundle.action_ledger)
                )
                expected = {
                    (symbol, timestamp)
                    for timestamp in expected_bar_timestamps(
                        raw_chain.start, raw_chain.end, Timeframe.FIVE_MINUTES
                    )
                    for symbol in raw_chain.symbols
                }
                raw_coordinates = {bar.coordinate for bar in raw_bars}
                analytical_coordinates = {bar.coordinate for bar in analytical_bars}
                missing_coordinates = (expected - raw_coordinates) | (
                    expected - analytical_coordinates
                )
                for symbol, timestamp in missing_coordinates:
                    missing[timestamp.date()].add(f"{symbol}@{_iso_utc(timestamp)}")
                if scope == "full":
                    _collect_morning_metrics(raw_bars, morning_metrics)
                for bar in raw_bars:
                    raw_file.write(canonical_json(bar.record()) + "\n")
                    raw_count += 1
                for bar in analytical_bars:
                    analytical_file.write(canonical_json(bar.record()) + "\n")
                    analytical_count += 1
                source_pages.extend(_private_page_manifest(private_root, raw_root, raw_chain))
                source_pages.extend(
                    _private_page_manifest(private_root, analytical_root, analytical_chain)
                )
            raw_file.flush()
            os.fsync(raw_file.fileno())
            analytical_file.flush()
            os.fsync(analytical_file.fileno())

        if scope == "qualification":
            missingness = _assess_qualification_missingness(bundle.plan, missing)
        else:
            missingness = assess_missingness(bundle.plan, missing, morning_metrics)
        if missingness.get("admission_passed") is not True:
            _publish_record(
                private_root / scope / "structural-failure.json",
                {
                    "schema_version": "program-005-structural-failure-v1",
                    "scope": scope,
                    "missingness_report": missingness,
                    "strategy_calculation_performed": False,
                },
                allow_identical=True,
            )
            raise Program005Error(
                "Program 005 structural admission failed: "
                + ", ".join(_strings(missingness.get("failures"), "missingness failures"))
            )
        raw_sha256 = _file_sha256(raw_path)
        analytical_sha256 = _file_sha256(analytical_path)
        action_report = _action_report(bundle.action_ledger, action_observations)
        action_contents = canonical_json(action_report) + "\n"
        missingness_contents = canonical_json(missingness) + "\n"
        (staging / "corporate-action-report.json").write_text(
            action_contents, encoding="utf-8", newline="\n"
        )
        (staging / "missingness-report.json").write_text(
            missingness_contents, encoding="utf-8", newline="\n"
        )
        action_sha256 = hashlib.sha256(action_contents.encode()).hexdigest()
        missingness_sha256 = hashlib.sha256(missingness_contents.encode()).hexdigest()
        stable_identity = {
            "schema_version": "program-005-private-dataset-identity-v1",
            "program_id": "multi-hour-sector-etf-research-004",
            "scope": scope,
            "source_commit": source_commit,
            "plan_sha256": _PLAN_SHA256,
            "retention_policy_sha256": _RETENTION_SHA256,
            "public_contract_sha256": _PUBLIC_CONTRACT_SHA256,
            "action_ledger_sha256": _ACTION_LEDGER_SHA256,
            "canonical_raw_sha256": raw_sha256,
            "canonical_analytical_sha256": analytical_sha256,
            "missingness_report_sha256": missingness_sha256,
            "corporate_action_report_sha256": action_sha256,
            "raw_row_count": raw_count,
            "analytical_row_count": analytical_count,
        }
        dataset_id = fingerprint(stable_identity)
        source_manifest = {
            "schema_version": "program-005-private-source-manifest-v1",
            "dataset_id": dataset_id,
            "scope": scope,
            "source_commit": source_commit,
            "pages": source_pages,
            "page_count": len(source_pages),
            "response_bytes": sum(int(page["byte_count"]) for page in source_pages),
            "credential_names": list(_CREDENTIAL_NAMES),
            "credentials_stored": False,
        }
        private_manifest = {
            **stable_identity,
            "dataset_id": dataset_id,
            "private_source_manifest_sha256": hashlib.sha256(
                (canonical_json(source_manifest) + "\n").encode()
            ).hexdigest(),
            "private_files": {
                "canonical_raw": "canonical-raw.jsonl",
                "canonical_analytical": "canonical-analytical.jsonl",
                "missingness": "missingness-report.json",
                "corporate_actions": "corporate-action-report.json",
                "source_manifest": "source-manifest.json",
            },
            "strategy_calculation_performed": False,
        }
        public_manifest = _public_manifest(
            bundle,
            scope,
            dataset_id,
            source_commit,
            raw_sha256,
            analytical_sha256,
            missingness_sha256,
            action_sha256,
            raw_count,
            analytical_count,
            missingness,
            action_report,
        )
        for filename, record in (
            ("source-manifest.json", source_manifest),
            ("private-manifest.json", private_manifest),
            ("public-manifest.json", public_manifest),
        ):
            (staging / filename).write_text(
                canonical_json(record) + "\n", encoding="utf-8", newline="\n"
            )
        _fsync_tree(staging)
        destination = private_root / "datasets" / dataset_id
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(staging, destination)
        except OSError as error:
            if destination.exists():
                raise Program005Error("Program 005 dataset identity already exists") from error
            raise
        _fsync_directory(destination.parent)
        return public_manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def execute_acquisition(
    repository: Path,
    private_root: Path,
    scope: str,
    authority_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    transport: Callable[[Request], HttpPage] = _urlopen_page,
    pace: Callable[[], None] | None = None,
) -> Mapping[str, Any]:
    bundle = load_contract(repository)
    chains = build_request_plan(bundle, scope)
    preflight = credential_free_preflight(repository, scope)
    if scope == "full":
        raise Program005Error(
            "Program 005 full acquisition remains blocked pending exact qualification "
            "bytes, receipt, and independent-review bindings"
        )
    authority = load_active_authority(
        repository, authority_path, scope, str(preflight["request_plan_fingerprint"])
    )
    expected_private_root = repository.resolve() / ".trading-lab/program-005-free-alpaca"
    if private_root.resolve() != expected_private_root:
        raise Program005Error("Program 005 private root differs from the frozen repository root")
    if scope == "full":
        qualification_receipt = _load_record(private_root / "qualification" / "receipt.json")
        if qualification_receipt.get("source_qualification") is not True:
            raise Program005Error("Program 005 full acquisition requires a passed qualification")
    scope_root = private_root / scope
    scope_root.mkdir(parents=True, exist_ok=True)
    lock_path = scope_root / "run.lock"
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if (scope_root / "receipt.json").exists():
            raise Program005Error("Program 005 scope already has a terminal receipt")
        if (scope_root / "terminal-transport-failure.json").exists():
            raise Program005Error("Program 005 scope already has a terminal transport failure")
        _publish_record(
            scope_root / "claim.json",
            {
                "schema_version": "program-005-private-authority-claim-v1",
                "scope": scope,
                "authority_id": authority.get("authority_id"),
                "authority_fingerprint": authority.get("authority_fingerprint"),
                "source_commit": authority.get("source_commit"),
                "request_plan_fingerprint": preflight["request_plan_fingerprint"],
            },
            allow_identical=True,
        )
        key_id, secret_key = read_credentials(environ)
        client = AlpacaBarsClient(
            key_id,
            secret_key,
            transport=transport,
            pace=pace,
        )
        budget = AcquisitionBudget(
            int(preflight["maximum_http_responses_to_acquire"]),
            int(preflight["maximum_downloaded_bytes"]),
        )
        try:
            for chain in chains:
                if chain.reused_from_qualification:
                    load_chain(chain, _chain_root(private_root, scope, chain))
                    continue
                acquire_chain(
                    chain,
                    _chain_root(private_root, scope, chain),
                    client,
                    budget,
                    source_commit=str(authority.get("source_commit")),
                )
            public_manifest = freeze_dataset(
                bundle,
                scope,
                chains,
                private_root,
                source_commit=str(authority.get("source_commit")),
            )
        except Program005TransportError as error:
            failure = {
                "schema_version": "program-005-private-transport-failure-v1",
                "scope": scope,
                "status": error.status,
                "retryable_infrastructure_failure": error.retryable,
                "automatic_retry_count": 0,
                "completed_response_count": budget.responses,
                "completed_response_bytes": budget.response_bytes,
                "credentials_stored": False,
            }
            if scope == "qualification" or not error.retryable:
                _publish_record(scope_root / "terminal-transport-failure.json", failure)
            else:
                _replace_record(scope_root / "last-transport-failure.json", failure)
            raise
        receipt = {
            "schema_version": "program-005-private-acquisition-receipt-v1",
            "scope": scope,
            "authority_id": authority.get("authority_id"),
            "authority_fingerprint": authority.get("authority_fingerprint"),
            "dataset_id": public_manifest.get("dataset_id"),
            "source_qualification": scope == "qualification",
            "full_market_data_acquisition": scope == "full",
            "real_dataset_admission": scope == "full",
            "http_response_count": budget.responses,
            "response_bytes": budget.response_bytes,
            "credential_loads": 1,
            "automatic_transport_retries": 0,
            "strategy_calculation_performed": False,
            "controlled_or_protected_accessed": False,
            "broker_write_performed": False,
        }
        _publish_record(scope_root / "receipt.json", receipt)
        return public_manifest


def load_active_authority(
    repository: Path,
    path: Path,
    scope: str,
    request_plan_fingerprint: str,
) -> Mapping[str, Any]:
    try:
        raw = path.resolve().read_bytes()
    except OSError as error:
        raise Program005Error("Program 005 source authority is absent or unreadable") from error
    authority = _load_json_object(raw, "Program 005 authority")
    unsigned = dict(authority)
    stored_fingerprint = unsigned.pop("authority_fingerprint", None)
    if (
        stored_fingerprint != fingerprint(unsigned)
        or authority.get("schema_version") != "program-005-source-authority-v1"
        or authority.get("status") != "ACTIVE-ONE-USE"
        or authority.get("program_id") != "multi-hour-sector-etf-research-004"
        or authority.get("scope") != scope
        or authority.get("request_plan_fingerprint") != request_plan_fingerprint
    ):
        raise Program005Error("Program 005 source authority is not active or differs")
    flags = _mapping(authority.get("authority"), "Program 005 authority flags")
    expected_true = {
        "provider_contact",
        "credential_access",
        "source_requests",
        "source_qualification" if scope == "qualification" else "market_data_acquisition",
    }
    if scope == "full":
        expected_true.add("real_dataset_admission")
    if any(flags.get(name) is not True for name in expected_true) or any(
        flags.get(name) is not False for name in _AUTHORITY_FALSE_KEYS
    ):
        raise Program005Error("Program 005 source authority flags differ")
    if scope == "qualification" and any(
        flags.get(name) is not False
        for name in ("market_data_acquisition", "real_dataset_admission")
    ):
        raise Program005Error("Program 005 qualification authority is overbroad")
    bindings = _mapping(authority.get("bindings"), "Program 005 authority bindings")
    exact_bindings = {
        "program_plan": (_PLAN_PATH, _PLAN_SHA256, _PLAN_FINGERPRINT),
        "retention_policy": (
            _RETENTION_PATH,
            _RETENTION_SHA256,
            _RETENTION_FINGERPRINT,
        ),
        "public_dataset_contract": (
            _PUBLIC_CONTRACT_PATH,
            _PUBLIC_CONTRACT_SHA256,
            _PUBLIC_CONTRACT_FINGERPRINT,
        ),
        "corporate_action_ledger": (
            _ACTION_LEDGER_PATH,
            _ACTION_LEDGER_SHA256,
            _ACTION_LEDGER_FINGERPRINT,
        ),
    }
    for name, (expected_path, sha256, fingerprint_value) in exact_bindings.items():
        _require_binding(bindings.get(name), expected_path, sha256, fingerprint_value, name)
    source_commit = authority.get("source_commit")
    if (
        not isinstance(source_commit, str)
        or len(source_commit) != 40
        or any(value not in "0123456789abcdef" for value in source_commit)
    ):
        raise Program005Error("Program 005 authority source commit is invalid")
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", source_commit, "HEAD"],
        cwd=repository,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise Program005Error("Program 005 authority source commit is not an ancestor")
    source_files = authority.get("source_files")
    if not isinstance(source_files, list) or len(source_files) != len(_AUTHORITY_SOURCE_PATHS):
        raise Program005Error("Program 005 authority source files are absent")
    for raw_file, expected_path in zip(source_files, _AUTHORITY_SOURCE_PATHS, strict=True):
        item = _mapping(raw_file, "Program 005 source file")
        relative = item.get("path")
        file_sha256 = item.get("sha256")
        if (
            relative != expected_path.as_posix()
            or not isinstance(file_sha256, str)
            or _file_sha256(repository / expected_path) != file_sha256
            or _git_file_sha256(repository, source_commit, expected_path) != file_sha256
        ):
            raise Program005Error("Program 005 authority source binding differs")
    return authority


def _qualification_chains(plan: Mapping[str, Any]) -> tuple[RequestChain, ...]:
    qualification = _mapping(plan.get("source_qualification"), "source qualification")
    contract = _mapping(qualification.get("request_contract"), "qualification request contract")
    symbols = tuple(_strings(qualification.get("exact_symbols"), "qualification symbols"))
    if (
        contract.get("method") != "GET"
        or contract.get("endpoint") != _ENDPOINT
        or contract.get("feed") != "sip"
        or contract.get("timeframe") != "5Min"
        or contract.get("adjustments") != ["raw", "split,spin-off"]
        or contract.get("sort") != "asc"
        or contract.get("limit") != 10000
        or contract.get("asof") != "2026-07-31"
        or contract.get("redirects") is not False
        or contract.get("rate_limit_requests_per_minute") != 120
        or tuple(sorted(symbols)) != symbols
    ):
        raise Program005Error("Program 005 qualification request contract differs")
    chains: list[RequestChain] = []
    for raw_range in _sequence(qualification.get("request_ranges"), "qualification ranges"):
        request_range = _mapping(raw_range, "qualification range")
        range_id = request_range.get("range_id")
        if not isinstance(range_id, str):
            raise Program005Error("Program 005 qualification range ID is invalid")
        start = _parse_utc(str(request_range.get("start_inclusive")))
        end = _parse_utc(str(request_range.get("end_inclusive")))
        session_dates = tuple(
            date.fromisoformat(value)
            for value in _strings(request_range.get("session_dates"), "qualification sessions")
        )
        ids = _strings(request_range.get("logical_chain_ids"), "qualification chain IDs")
        maximum_pages = _integer(
            request_range.get("maximum_pages_per_adjustment_view"),
            "qualification page limit",
        )
        for chain_id, adjustment in zip(ids, ("raw", "split,spin-off"), strict=True):
            chains.append(
                RequestChain(
                    chain_id,
                    range_id,
                    adjustment,
                    start,
                    end,
                    symbols,
                    session_dates,
                    maximum_pages,
                )
            )
    budget = _mapping(qualification.get("transport_budget"), "qualification budget")
    if (
        len(chains) != budget.get("maximum_logical_chains")
        or sum(chain.maximum_pages for chain in chains) != budget.get("maximum_http_responses")
        or len({chain.identity for chain in chains}) != len(chains)
    ):
        raise Program005Error("Program 005 qualification chain manifest differs")
    return tuple(chains)


def _load_bound_artifact(
    path: Path,
    sha256: str,
    fingerprint_field: str,
    expected_fingerprint: str,
    label: str,
) -> Mapping[str, Any]:
    raw = path.read_bytes()
    payload = _load_json_object(raw, label)
    unsigned = dict(payload)
    stored_fingerprint = unsigned.pop(fingerprint_field, None)
    if (
        hashlib.sha256(raw).hexdigest() != sha256
        or stored_fingerprint != expected_fingerprint
        or stored_fingerprint != fingerprint(unsigned)
    ):
        raise Program005Error(f"{label} differs")
    return payload


def _load_json_object(raw: bytes, label: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise Program005Error(f"{label} contains a duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Program005Error(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise Program005Error(f"{label} must be a JSON object")
    return value


def _load_provider_json(raw: bytes) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise Program005Error(f"Alpaca response contains non-finite number: {value}")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise Program005Error("Alpaca response contains a duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=unique,
            parse_float=Decimal,
            parse_int=int,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, InvalidOperation) as error:
        raise Program005Error("Alpaca response is not valid JSON") from error
    if not isinstance(value, dict):
        raise Program005Error("Alpaca response must be a JSON object")
    return value


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Program005Error(f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise Program005Error(f"{label} must be a list")
    return value


def _strings(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise Program005Error(f"{label} must contain strings")
    return tuple(value)


def _require_binding(
    value: Any,
    path: Path,
    sha256: str,
    fingerprint_value: str,
    label: str,
) -> None:
    binding = _mapping(value, label)
    if (
        binding.get("path") != path.as_posix()
        or binding.get("sha256") != sha256
        or binding.get("fingerprint") != fingerprint_value
    ):
        raise Program005Error(f"{label} differs")


def _validate_request_url(url: str, chain: RequestChain) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.fragment,
    ) != ("https", "data.alpaca.markets", "/v2/stocks/bars", ""):
        raise Program005Error("Program 005 request is outside the frozen GET-only endpoint")
    parameters = parse_qsl(parsed.query, keep_blank_values=True)
    base = list(chain.parameters)
    if parameters[: len(base)] != base or len(parameters) not in {len(base), len(base) + 1}:
        raise Program005Error("Program 005 request parameters differ")
    if len(parameters) == len(base) + 1 and (
        parameters[-1][0] != "page_token" or not parameters[-1][1]
    ):
        raise Program005Error("Program 005 pagination parameter differs")


def _parse_bar_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise Program005Error("Alpaca bar timestamp must be UTC RFC-3339")
    try:
        timestamp = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise Program005Error("Alpaca bar timestamp is malformed") from error
    if (
        timestamp.utcoffset() != UTC.utcoffset(timestamp)
        or timestamp.second != 0
        or timestamp.microsecond != 0
        or timestamp.minute % 5
    ):
        raise Program005Error("Alpaca bar timestamp is not a five-minute UTC bar open")
    return timestamp.astimezone(UTC)


def _positive_decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | Decimal):
        raise Program005Error(f"Alpaca {label} must be numeric")
    result = Decimal(value)
    if not result.is_finite() or result <= 0:
        raise Program005Error(f"Alpaca {label} must be finite and positive")
    return result


def _optional_positive_decimal(value: Any, label: str) -> Decimal | None:
    return None if value is None else _positive_decimal(value, label)


def _optional_nonnegative_integer(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Program005Error(f"Alpaca {label} must be a nonnegative integer")
    return int(value)


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Program005Error(f"{label} must be an integer")
    return int(value)


def _load_checkpoint(chain_root: Path, chain: RequestChain) -> Mapping[str, Any]:
    path = chain_root / "checkpoint.json"
    if not path.exists():
        return {
            "schema_version": "program-005-private-chain-checkpoint-v1",
            "chain_identity": chain.identity,
            "completed_pages": 0,
            "next_page_token": None,
            "seen_page_tokens": [],
            "page_sha256s": [],
            "terminal": False,
        }
    record = _load_record(path)
    completed = record.get("completed_pages")
    if (
        record.get("schema_version") != "program-005-private-chain-checkpoint-v1"
        or record.get("chain_identity") != chain.identity
        or isinstance(completed, bool)
        or not isinstance(completed, int)
        or completed < 0
        or completed > chain.maximum_pages
        or not isinstance(record.get("terminal"), bool)
        or len(_strings(record.get("page_sha256s"), "checkpoint page hashes")) != completed
    ):
        raise Program005Error("Program 005 chain checkpoint differs")
    next_token = record.get("next_page_token")
    if next_token is not None and (not isinstance(next_token, str) or not next_token):
        raise Program005Error("Program 005 checkpoint page token differs")
    if record.get("terminal") is True and next_token is not None:
        raise Program005Error("Program 005 terminal checkpoint retains a page token")
    return record


def _store_page(
    target: Path,
    chain: RequestChain,
    index: int,
    page: HttpPage,
    incoming_token: str | None,
    outgoing_token: str | None,
    source_commit: str,
    now: Callable[[], datetime],
) -> StoredPage:
    retrieved = now().astimezone(UTC).isoformat().replace("+00:00", "Z")
    sha256 = hashlib.sha256(page.body).hexdigest()
    metadata = {
        "schema_version": "program-005-private-raw-page-v1",
        "chain_id": chain.chain_id,
        "chain_identity": chain.identity,
        "page_index": index,
        "request_url": chain.url(incoming_token),
        "incoming_page_token": incoming_token,
        "outgoing_page_token": outgoing_token,
        "retrieved_at_utc": retrieved,
        "response_status": page.status,
        "response_sha256": sha256,
        "response_bytes": len(page.body),
        "provider": "Alpaca",
        "feed": "sip",
        "timeframe": "5Min",
        "adjustment": chain.adjustment,
        "source_commit": source_commit,
        "credentials_stored": False,
    }
    metadata["record_fingerprint"] = fingerprint(metadata)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    try:
        _write_fsynced(temporary / "body.json", page.body)
        _write_fsynced(temporary / "metadata.json", (canonical_json(metadata) + "\n").encode())
        _fsync_directory(temporary)
        try:
            os.rename(temporary, target)
        except FileExistsError:
            stored = _load_stored_page(target, chain, index, incoming_token)
            if stored.sha256 != sha256 or stored.outgoing_token != outgoing_token:
                raise Program005Error("Program 005 raw page conflicts") from None
            return stored
        _fsync_directory(target.parent)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return StoredPage(
        index,
        page.body,
        sha256,
        chain.url(incoming_token),
        incoming_token,
        outgoing_token,
        retrieved,
    )


def _load_stored_page(
    root: Path,
    chain: RequestChain,
    index: int,
    incoming_token: str | None,
) -> StoredPage:
    metadata = _load_record(root / "metadata.json", fingerprint_field="record_fingerprint")
    body = (root / "body.json").read_bytes()
    sha256 = hashlib.sha256(body).hexdigest()
    _, parsed_outgoing = parse_bars_page(body, chain)
    outgoing = metadata.get("outgoing_page_token")
    retrieved = metadata.get("retrieved_at_utc")
    if (
        metadata.get("schema_version") != "program-005-private-raw-page-v1"
        or metadata.get("chain_id") != chain.chain_id
        or metadata.get("chain_identity") != chain.identity
        or metadata.get("page_index") != index
        or metadata.get("request_url") != chain.url(incoming_token)
        or metadata.get("incoming_page_token") != incoming_token
        or outgoing != parsed_outgoing
        or metadata.get("response_status") != 200
        or metadata.get("response_sha256") != sha256
        or metadata.get("response_bytes") != len(body)
        or metadata.get("credentials_stored") is not False
        or not isinstance(retrieved, str)
    ):
        raise Program005Error("Program 005 stored raw page differs")
    if outgoing is not None and not isinstance(outgoing, str):
        raise Program005Error("Program 005 stored page token differs")
    return StoredPage(
        index,
        body,
        sha256,
        chain.url(incoming_token),
        incoming_token,
        outgoing,
        str(retrieved),
    )


def _load_chain_pages(chain_root: Path, chain: RequestChain) -> tuple[StoredPage, ...]:
    checkpoint = _load_checkpoint(chain_root, chain)
    completed = int(checkpoint["completed_pages"])
    pages: list[StoredPage] = []
    incoming: str | None = None
    hashes: list[str] = []
    for index in range(1, completed + 1):
        page = _load_stored_page(chain_root / "pages" / f"{index:05d}", chain, index, incoming)
        pages.append(page)
        hashes.append(page.sha256)
        incoming = page.outgoing_token
    if (
        hashes != checkpoint.get("page_sha256s")
        or incoming != checkpoint.get("next_page_token")
        or (
            checkpoint.get("terminal") is True
            and (not pages or pages[-1].outgoing_token is not None)
        )
        or (checkpoint.get("terminal") is False and pages and pages[-1].outgoing_token is None)
    ):
        raise Program005Error("Program 005 stored page sequence differs")
    pages_root = chain_root / "pages"
    if pages_root.exists() and any(
        child.name != f"{index:05d}"
        for index, child in enumerate(sorted(pages_root.iterdir()), start=1)
    ):
        raise Program005Error("Program 005 stored page sequence has a gap")
    return tuple(pages)


def _expected_price_factor(ledger: Mapping[str, Any], symbol: str, session: date) -> Decimal:
    matches: list[Decimal] = []
    for kind in ("split_events", "spin_off_events"):
        raw_events = ledger.get(kind, [])
        if not isinstance(raw_events, list):
            raise Program005Error("Program 005 action ledger event list differs")
        for raw_event in raw_events:
            event = _mapping(raw_event, "Program 005 action event")
            symbols = set(_strings(event.get("symbols"), "action symbols"))
            if symbol not in symbols:
                continue
            effective = date.fromisoformat(str(event.get("first_post_action_trading_session")))
            field_name = (
                "analytical_price_factor_before_effective_session"
                if session < effective
                else "analytical_price_factor_from_effective_session"
            )
            matches.append(Decimal(str(event.get(field_name))))
    if len(matches) > 1:
        factor = math.prod(matches, start=Decimal(1))
    elif matches:
        factor = matches[0]
    else:
        default = _mapping(ledger.get("default_factor_rule"), "default action factor")
        factor = Decimal(str(default.get("analytical_price_factor")))
    if not factor.is_finite() or factor <= 0:
        raise Program005Error("Program 005 ledger factor is invalid")
    return factor


def _assess_qualification_missingness(
    plan: Mapping[str, Any], missing_coordinates: Mapping[date, set[str]]
) -> Mapping[str, Any]:
    qualification = _mapping(plan.get("source_qualification"), "source qualification")
    policy = _mapping(plan.get("missing_data_policy"), "missing-data policy")
    quarantine = {
        date.fromisoformat(value)
        for value in _strings(
            _mapping(policy.get("pre_exposed_design_quarantine"), "pre-exposed quarantine").get(
                "sessions"
            ),
            "quarantine sessions",
        )
    }
    known = set(_strings(qualification.get("known_mdy_coordinates"), "known MDY coordinates"))
    observed_missing = {
        coordinate for coordinates in missing_coordinates.values() for coordinate in coordinates
    }
    failures: set[str] = set()
    if observed_missing - known:
        failures.add("unexpected-missing-coordinate")
    if any(session not in quarantine for session in missing_coordinates):
        failures.add("missing-outside-quarantine")
    return {
        "schema_version": "program-005-structural-missingness-report-v1",
        "scope": "qualification",
        "fixed_quarantine_sessions": [session.isoformat() for session in sorted(quarantine)],
        "excluded_session_count": len(quarantine),
        "missing_coordinate_count": len(observed_missing),
        "missing_coordinates": sorted(observed_missing),
        "permitted_known_coordinate_count": len(observed_missing & known),
        "failures": sorted(failures),
        "admission_passed": not failures,
        "strategy_metrics_present": False,
    }


def _collect_morning_metrics(
    bars: Sequence[CanonicalBar],
    output: dict[date, dict[str, tuple[Decimal, Decimal, Decimal]]],
) -> None:
    by_session_symbol: dict[tuple[date, str], list[CanonicalBar]] = defaultdict(list)
    for bar in bars:
        if bar.symbol in {"SPY", "MDY"}:
            by_session_symbol[(bar.timestamp.date(), bar.symbol)].append(bar)
    for (session, symbol), values in by_session_symbol.items():
        ordered = sorted(values)
        morning = ordered[:24]
        if len(morning) != 24:
            continue
        opening = morning[0].open
        absolute_return = abs(morning[-1].close / opening - Decimal(1))
        minimum = min(bar.low for bar in morning)
        range_ratio = (max(bar.high for bar in morning) - minimum) / minimum
        volume = sum((bar.volume for bar in morning), start=Decimal(0))
        output.setdefault(session, {})[symbol] = (absolute_return, range_ratio, volume)


def _assess_morning_bias(
    policy: Mapping[str, Any],
    excluded: set[date],
    full_sessions: set[date],
    metrics: Mapping[date, Mapping[str, tuple[Decimal, Decimal, Decimal]]],
) -> tuple[Mapping[str, Any], set[str]]:
    gate = _mapping(
        _mapping(policy.get("bias_audit"), "missingness bias audit").get(
            "spy_and_mdy_morning_diagnostics"
        ),
        "SPY/MDY morning diagnostics",
    )
    symbols = _strings(gate.get("reference_symbols"), "morning reference symbols")
    failures: set[str] = set()
    if len(full_sessions) != _integer(gate.get("finite_population_sessions"), "morning population"):
        failures.add("morning-population")
    if any(
        session not in metrics or symbol not in metrics[session]
        for session in full_sessions
        for symbol in symbols
    ):
        failures.add("morning-diagnostic-unavailable")
        return {
            "population_sessions": len(full_sessions),
            "available": False,
            "tests": [],
        }, failures
    rejection_counts = _mapping(
        gate.get("rejection_counts_by_total_exclusions"), "morning rejection counts"
    )
    threshold = rejection_counts.get(str(len(excluded)))
    if not isinstance(threshold, int):
        failures.add("unsupported-exclusion-count")
        return {
            "population_sessions": len(full_sessions),
            "available": True,
            "tests": [],
        }, failures
    tail_size = _integer(gate.get("tail_size_sessions"), "morning tail size")
    tests: list[Mapping[str, Any]] = []
    definitions = ((0, "absolute-return", "high"), (1, "range", "high"), (2, "volume", "low"))
    for symbol in symbols:
        for metric_index, metric_name, tail in definitions:
            ordered = sorted(
                full_sessions,
                key=lambda session: (metrics[session][symbol][metric_index], session),
            )
            selected = set(ordered[-tail_size:] if tail == "high" else ordered[:tail_size])
            count = len(excluded & selected)
            passed = count < threshold
            if not passed:
                failures.add(f"morning-bias:{symbol}:{metric_name}:{tail}")
            tests.append(
                {
                    "symbol": symbol,
                    "metric": metric_name,
                    "tail": tail,
                    "excluded_in_tail": count,
                    "rejection_count": threshold,
                    "passed": passed,
                }
            )
    return {
        "population_sessions": len(full_sessions),
        "tail_size_sessions": tail_size,
        "available": True,
        "per_test_alpha_exact": gate.get("per_test_alpha_exact"),
        "tests": tests,
    }, failures


def _block_id(session: date) -> str:
    for block_id, start, end in _FIXED_BLOCKS:
        if start <= session <= end:
            return block_id
    raise Program005Error(f"Program 005 session is outside fixed blocks: {session}")


def _action_report(
    ledger: Mapping[str, Any], observations: Sequence[Mapping[str, Any]]
) -> Mapping[str, Any]:
    unique = {(str(item["symbol"]), str(item["session"])): dict(item) for item in observations}
    factor_counts = Counter(str(item["analytical_price_factor"]) for item in unique.values())
    return {
        "schema_version": "program-005-corporate-action-report-v1",
        "ledger_id": ledger.get("ledger_id"),
        "ledger_sha256": _ACTION_LEDGER_SHA256,
        "ledger_fingerprint": _ACTION_LEDGER_FINGERPRINT,
        "symbol_session_factor_count": len(unique),
        "price_factor_counts": dict(sorted(factor_counts.items())),
        "factor_observations": [unique[key] for key in sorted(unique)],
        "qualification_realized_spin_off_count": _mapping(
            ledger.get("spin_off_controls"), "spin-off controls"
        ).get("qualification_realized_event_count"),
        "realized_spin_off_semantics_qualified": False,
        "dividend_adjustment_requested": False,
        "dividend_cash_credit_applied": False,
        "failures": [],
        "admission_passed": True,
        "strategy_calculation_performed": False,
    }


def _public_manifest(
    bundle: ContractBundle,
    scope: str,
    dataset_id: str,
    source_commit: str,
    raw_sha256: str,
    analytical_sha256: str,
    missingness_sha256: str,
    action_sha256: str,
    raw_count: int,
    analytical_count: int,
    missingness: Mapping[str, Any],
    action_report: Mapping[str, Any],
) -> Mapping[str, Any]:
    contract = _mapping(bundle.public_contract.get("provider_contract"), "provider contract")
    result = {
        "schema_version": "program-005-public-dataset-manifest-v1",
        "dataset_id": dataset_id,
        "program_id": "multi-hour-sector-etf-research-004",
        "scope": scope,
        "provider": contract.get("provider"),
        "feed": contract.get("feed"),
        "timeframe": contract.get("timeframe"),
        "symbols": bundle.public_contract.get("symbols"),
        "requested_range": (
            bundle.public_contract.get("qualification_shape")
            if scope == "qualification"
            else bundle.public_contract.get("full_range")
        ),
        "adjustments": contract.get("adjustments"),
        "source_commit": source_commit,
        "schema_versions": bundle.public_contract.get("private_artifacts"),
        "structural_counts": {
            "canonical_raw_rows": raw_count,
            "canonical_analytical_rows": analytical_count,
            "excluded_sessions": missingness.get(
                "excluded_full_session_count", missingness.get("excluded_session_count")
            ),
            "missing_coordinates": missingness.get("missing_coordinate_count"),
            "action_factor_symbol_sessions": action_report.get("symbol_session_factor_count"),
        },
        "canonical_hashes": {
            "raw_sha256": raw_sha256,
            "analytical_sha256": analytical_sha256,
            "missingness_report_sha256": missingness_sha256,
            "corporate_action_report_sha256": action_sha256,
        },
        "acquisition_algorithm_version": "program-005-alpaca-acquisition-v1",
        "missingness_disposition": {
            "policy_id": _mapping(
                bundle.plan.get("missing_data_policy"), "missing-data policy"
            ).get("policy_id"),
            "admission_passed": missingness.get("admission_passed"),
            "fixed_quarantine_session_count": 5,
        },
        "corporate_action_policy": {
            "ledger_id": bundle.action_ledger.get("ledger_id"),
            "ledger_fingerprint": _ACTION_LEDGER_FINGERPRINT,
            "admission_passed": action_report.get("admission_passed"),
            "realized_spin_off_semantics_qualified": False,
        },
        "authority": {
            "strategy_execution": False,
            "controlled_evaluation": False,
            "protected_holdout": False,
            "paper_execution": False,
            "broker_writes": False,
            "live_execution": False,
        },
    }
    prohibited = set(
        _strings(
            bundle.public_contract.get("private_manifest_fields_prohibited_in_public_projection"),
            "prohibited public fields",
        )
    )
    if prohibited & _recursive_keys(result):
        raise Program005Error("Program 005 public manifest contains a private field")
    return result


def _private_page_manifest(
    private_root: Path, chain_root: Path, chain: RequestChain
) -> list[Mapping[str, Any]]:
    pages = _load_chain_pages(chain_root, chain)
    return [
        {
            "chain_id": chain.chain_id,
            "chain_identity": chain.identity,
            "page_index": page.index,
            "raw_file": str(
                (chain_root / "pages" / f"{page.index:05d}" / "body.json").relative_to(private_root)
            ),
            "request_url": page.request_url,
            "incoming_page_token": page.incoming_token,
            "outgoing_page_token": page.outgoing_token,
            "retrieved_at_utc": page.retrieved_at,
            "sha256": page.sha256,
            "byte_count": len(page.body),
        }
        for page in pages
    ]


def _chain_root(private_root: Path, scope: str, chain: RequestChain) -> Path:
    owning_scope = "qualification" if chain.reused_from_qualification else scope
    return private_root / owning_scope / "chains" / chain.identity


def _recursive_keys(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        return set(value) | set().union(*(_recursive_keys(item) for item in value.values()), set())
    if isinstance(value, list | tuple):
        return set().union(*(_recursive_keys(item) for item in value), set())
    return set()


def _publish_record(
    path: Path, record: Mapping[str, Any], *, allow_identical: bool = False
) -> None:
    payload = dict(record)
    payload["record_fingerprint"] = fingerprint(payload)
    contents = (canonical_json(payload) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _write_fsynced(path, contents, exclusive=True)
    except FileExistsError:
        if allow_identical and path.read_bytes() == contents:
            return
        raise Program005Error(f"Program 005 create-only artifact exists: {path.name}") from None
    _fsync_directory(path.parent)


def _replace_record(path: Path, record: Mapping[str, Any]) -> None:
    payload = dict(record)
    payload["record_fingerprint"] = fingerprint(payload)
    contents = (canonical_json(payload) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(raw_temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_record(path: Path, *, fingerprint_field: str = "record_fingerprint") -> Mapping[str, Any]:
    raw = path.read_bytes()
    payload = _load_json_object(raw, path.name)
    unsigned = dict(payload)
    stored = unsigned.pop(fingerprint_field, None)
    if raw != (canonical_json(payload) + "\n").encode() or stored != fingerprint(unsigned):
        raise Program005Error(f"Program 005 record differs: {path.name}")
    return payload


def _write_fsynced(path: Path, contents: bytes, *, exclusive: bool = False) -> None:
    mode = "xb" if exclusive else "wb"
    with path.open(mode) as handle:
        handle.write(contents)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_tree(root: Path) -> None:
    for path in sorted(root.iterdir()):
        if path.is_file():
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
    _fsync_directory(root)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _git_file_sha256(repository: Path, commit: str, path: Path) -> str:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path.as_posix()}"],
        cwd=repository,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise Program005Error("Program 005 authority source commit lacks a bound file")
    return hashlib.sha256(result.stdout).hexdigest()


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise Program005Error("Program 005 timestamp must be UTC")
    return value.isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise Program005Error("Program 005 timestamp is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise Program005Error("Program 005 timestamp must be UTC")
    return parsed.astimezone(UTC)


def _day_start(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def _day_end(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, 23, 59, 59, tzinfo=UTC)
