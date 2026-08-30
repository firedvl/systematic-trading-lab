"""Offline Program 007 raw-first source contract and unit normalization."""

from __future__ import annotations

import base64
import binascii
import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
from _thread import RLock
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType
from typing import Any, BinaryIO
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from .calendar import expected_bar_timestamps, expected_sessions
from .domain import Timeframe
from .fingerprints import canonical_json, fingerprint

PROGRAM_ID = "multi-hour-sector-etf-research-006"
STATUS = "PROPOSED-NOT-AUTHORIZED"
ENDPOINT = "https://data.alpaca.markets/v2/stocks/bars"
SYMBOLS = (
    "IWM",
    "MDY",
    "SPY",
    "XLB",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
)
MAXIMUM_HTTP_REQUESTS = 11
MAXIMUM_HTTP_RESPONSES = 11
MAXIMUM_DOWNLOADED_BYTES = 16 * 1024 * 1024
MAXIMUM_RESPONSE_PAGE_BYTES = 8 * 1024 * 1024
MAXIMUM_REQUESTS_PER_MINUTE = 120
AUTOMATIC_TRANSPORT_RETRIES = 0

_NEW_YORK = ZoneInfo("America/New_York")
_CHAIN_ID = re.compile(r"[a-z0-9][a-z0-9-]*")
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_ACTION_SYMBOLS = frozenset({"XLB", "XLE", "XLK", "XLU", "XLY"})
_CUSIPS_BY_SYMBOL = {
    "IWM": "464287655",
    "MDY": "78467Y107",
    "SPY": "78462F103",
    "XLB": "81369Y100",
    "XLE": "81369Y506",
    "XLF": "81369Y605",
    "XLI": "81369Y704",
    "XLK": "81369Y803",
    "XLP": "81369Y308",
    "XLRE": "81369Y860",
    "XLU": "81369Y886",
    "XLV": "81369Y209",
    "XLY": "81369Y407",
}
_CIKS_BY_SYMBOL = {
    **{symbol: "0001064641" for symbol in SYMBOLS if symbol.startswith("XL")},
    "IWM": "0001100663",
    "MDY": "0000936958",
    "SPY": "0000884394",
}
_AUTHORITY_FIELDS = frozenset(
    {
        "provider_contact",
        "subscription_purchase",
        "credential_access",
        "source_requests",
        "source_qualification",
        "market_data_acquisition",
        "real_dataset_admission",
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
_PROPOSAL_SHA256 = "5e92effb829e70d7bbf4636d88519c104565a10bd6f57235169419542cb05b34"
_PROPOSAL_FINGERPRINT = "d0ec31e7b6947ed6fe3e1118a6f5536daddae34ebbe9dffcc3b3f932dd9d41c0"
_FROZEN_REQUEST_PLAN = (
    ("normal-2021-07-08", "2021-07-08T13:30:00Z", "2021-07-08T19:55:00Z", 1, 1),
    ("normal-2022-01-25", "2022-01-25T14:30:00Z", "2022-01-25T20:55:00Z", 1, 1),
    ("normal-2022-11-15", "2022-11-15T14:30:00Z", "2022-11-15T20:55:00Z", 1, 1),
    (
        "pagination-2023-05-16-to-2023-05-30",
        "2023-05-16T13:30:00Z",
        "2023-05-30T19:55:00Z",
        10,
        6,
    ),
    (
        "split-pre-early-close-2025-11-28",
        "2025-11-28T14:30:00Z",
        "2025-11-28T17:55:00Z",
        1,
        1,
    ),
    (
        "split-post-2025-12-15",
        "2025-12-15T14:30:00Z",
        "2025-12-15T20:55:00Z",
        1,
        1,
    ),
)


class Program007Error(ValueError):
    """Fail-closed Program 007 contract error."""


@dataclass(frozen=True)
class RequestChain:
    chain_id: str
    start: datetime
    end: datetime
    symbols: tuple[str, ...]
    maximum_pages: int

    def __post_init__(self) -> None:
        if (
            not _CHAIN_ID.fullmatch(self.chain_id)
            or not _is_utc(self.start)
            or not _is_utc(self.end)
            or self.start > self.end
            or not self.symbols
            or tuple(sorted(set(self.symbols))) != self.symbols
            or not set(self.symbols) <= set(SYMBOLS)
            or not 1 <= self.maximum_pages <= 6
            or not self.session_dates
        ):
            raise Program007Error("Program 007 request chain is invalid")

    @property
    def session_dates(self) -> tuple[date, ...]:
        return expected_sessions(self.start, self.end)

    @property
    def parameters(self) -> tuple[tuple[str, str], ...]:
        return (
            ("symbols", ",".join(self.symbols)),
            ("start", _iso_utc(self.start)),
            ("end", _iso_utc(self.end)),
            ("feed", "sip"),
            ("timeframe", "5Min"),
            ("adjustment", "raw"),
            ("sort", "asc"),
            ("limit", "10000"),
            ("asof", "2026-07-31"),
        )

    def url(self, page_token: str | None = None) -> str:
        parameters = self.parameters
        if page_token is not None:
            if not page_token:
                raise Program007Error("Program 007 page token must be non-empty")
            parameters = (*parameters, ("page_token", page_token))
        return f"{ENDPOINT}?{urlencode(parameters)}"

    @property
    def identity(self) -> str:
        return fingerprint(
            {
                "chain_id": self.chain_id,
                "method": "GET",
                "endpoint": ENDPOINT,
                "parameters": dict(self.parameters),
                "maximum_pages": self.maximum_pages,
                "redirects": False,
            }
        )


@dataclass(frozen=True)
class RequestIntent:
    chain_id: str
    chain_identity: str
    page_index: int
    url: str
    incoming_page_token: str | None
    method: str = "GET"
    redirects: bool = False


@dataclass(frozen=True)
class RawResponse:
    status: int
    body: bytes

    def __post_init__(self) -> None:
        if type(self.status) is not int:
            raise Program007Error("Program 007 response status is invalid")
        if type(self.body) is not bytes:
            raise Program007Error("Program 007 response body must be bytes")


class SyntheticPageSource:
    """Finite in-memory responses retained in a capability-held evidence log."""

    __slots__ = (
        "_responses",
        "_intents",
        "_intent_files_present",
        "_workspace",
        "_private_root",
        "_root_identity",
        "_evidence",
        "_evidence_identity",
        "_evidence_lock",
    )

    _responses: tuple[RawResponse | None, ...]
    _intents: list[RequestIntent]
    _intent_files_present: list[bool]
    _workspace: tempfile.TemporaryDirectory[str]
    _private_root: Path
    _root_identity: tuple[int, int]
    _evidence: BinaryIO
    _evidence_identity: tuple[int, int]
    _evidence_lock: RLock

    def __init__(self, responses: Sequence[RawResponse | None]) -> None:
        if type(responses) not in {list, tuple} or any(
            response is not None and type(response) is not RawResponse for response in responses
        ):
            raise Program007Error("Program 007 synthetic responses are invalid")
        workspace = tempfile.TemporaryDirectory(prefix="program-007-synthetic-")
        object.__setattr__(self, "_responses", tuple(responses))
        object.__setattr__(self, "_intents", [])
        object.__setattr__(self, "_intent_files_present", [])
        object.__setattr__(self, "_workspace", workspace)
        private_root = Path(workspace.name)
        root_stat = os.lstat(private_root)
        evidence = tempfile.TemporaryFile(  # noqa: SIM115 - held for source lifetime
            mode="w+b", buffering=0, dir=private_root
        )
        evidence_stat = os.fstat(evidence.fileno())
        object.__setattr__(self, "_private_root", private_root)
        object.__setattr__(self, "_root_identity", (root_stat.st_dev, root_stat.st_ino))
        object.__setattr__(self, "_evidence", evidence)
        object.__setattr__(self, "_evidence_identity", (evidence_stat.st_dev, evidence_stat.st_ino))
        object.__setattr__(self, "_evidence_lock", RLock())

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Program 007 synthetic source is immutable")

    @property
    def private_root(self) -> Path:
        return self._private_root

    @property
    def intents(self) -> tuple[RequestIntent, ...]:
        return tuple(self._intents)

    @property
    def intent_files_present(self) -> tuple[bool, ...]:
        return tuple(self._intent_files_present)


@dataclass
class _EvidenceStore:
    descriptor: int
    entries: dict[str, bytes]

    def exists(self, key: str) -> bool:
        return key in self.entries

    def read(self, key: str) -> bytes:
        try:
            return self.entries[key]
        except KeyError as error:
            raise Program007Error(f"Program 007 evidence entry is missing: {key}") from error

    def publish(self, key: str, payload: bytes, *, allow_identical: bool = False) -> None:
        existing = self.entries.get(key)
        if existing is not None:
            if allow_identical and existing == payload:
                return
            raise Program007Error(
                f"Program 007 create-only artifact exists: {key.rsplit('/', 1)[-1]}"
            )
        _append_evidence(self.descriptor, key, payload)
        self.entries[key] = payload


@dataclass(frozen=True, order=True)
class RawBar:
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trade_count: int | None = field(compare=False, default=None)
    vwap: Decimal | None = field(compare=False, default=None)

    @property
    def coordinate(self) -> tuple[str, datetime]:
        return self.symbol, self.timestamp


@dataclass(frozen=True)
class PageEvidence:
    chain_id: str
    chain_identity: str
    page_index: int
    request_url: str
    incoming_page_token: str | None
    outgoing_page_token: str | None
    response_sha256: str
    response_bytes: int
    page_identity: str
    raw_row_count: int
    canonical_row_count: int
    extended_hours_row_count: int


@dataclass(frozen=True)
class ChainResult:
    chain: RequestChain
    raw_rows: tuple[RawBar, ...]
    canonical_rows: tuple[RawBar, ...]
    pages: tuple[PageEvidence, ...]


@dataclass(frozen=True)
class QualificationResult:
    chains: tuple[ChainResult, ...]

    @property
    def raw_row_count(self) -> int:
        return sum(len(chain.raw_rows) for chain in self.chains)

    @property
    def canonical_row_count(self) -> int:
        return sum(len(chain.canonical_rows) for chain in self.chains)

    @property
    def response_count(self) -> int:
        return sum(len(chain.pages) for chain in self.chains)

    @property
    def response_bytes(self) -> int:
        return sum(page.response_bytes for chain in self.chains for page in chain.pages)

    def private_manifest(self) -> Mapping[str, Any]:
        pages = [
            {
                "chain_id": page.chain_id,
                "chain_identity": page.chain_identity,
                "page_index": page.page_index,
                "request_url": page.request_url,
                "incoming_page_token": page.incoming_page_token,
                "outgoing_page_token": page.outgoing_page_token,
                "response_sha256": page.response_sha256,
                "response_bytes": page.response_bytes,
                "page_identity": page.page_identity,
                "parse_status": "PASS",
                "raw_structural_status": "PASS",
                "rth_projection_status": "PASS",
                "raw_row_count": page.raw_row_count,
                "canonical_row_count": page.canonical_row_count,
                "extended_hours_row_count": page.extended_hours_row_count,
            }
            for chain in self.chains
            for page in chain.pages
        ]
        return {
            "schema_version": "program-007-private-raw-source-manifest-v1",
            "program_id": PROGRAM_ID,
            "status": "SYNTHETIC-CONTRACT-PASS",
            "pages": pages,
            "response_count": self.response_count,
            "response_bytes": self.response_bytes,
            "raw_row_count": self.raw_row_count,
            "canonical_row_count": self.canonical_row_count,
            "credentials_stored": False,
            "strategy_outputs": 0,
        }

    def public_summary(self, ledger_fingerprint: str) -> Mapping[str, Any]:
        if not _HEX_64.fullmatch(ledger_fingerprint):
            raise Program007Error("Program 007 ledger fingerprint is invalid")
        page_hashes = sorted(page.response_sha256 for chain in self.chains for page in chain.pages)
        return {
            "schema_version": "program-007-public-source-summary-v1",
            "program_id": PROGRAM_ID,
            "status": "SYNTHETIC-IMPLEMENTATION-ONLY",
            "chain_count": len(self.chains),
            "response_count": self.response_count,
            "response_bytes": self.response_bytes,
            "raw_row_count": self.raw_row_count,
            "canonical_row_count": self.canonical_row_count,
            "extended_hours_row_count": self.raw_row_count - self.canonical_row_count,
            "private_evidence_fingerprint": fingerprint(page_hashes),
            "action_ledger_fingerprint": ledger_fingerprint,
            "private_market_observations": False,
            "reconstructable_private_values": False,
            "strategy_outputs": 0,
        }


@dataclass
class _Budget:
    requests: int = 0
    responses: int = 0
    response_bytes: int = 0

    def reserve_request(self) -> None:
        if self.requests >= MAXIMUM_HTTP_REQUESTS:
            raise Program007Error("Program 007 HTTP request ceiling exceeded")
        if self.responses >= MAXIMUM_HTTP_RESPONSES:
            raise Program007Error("Program 007 HTTP response ceiling exceeded")
        self.requests += 1

    def accept_response(self, body: bytes) -> None:
        if type(body) is not bytes:
            raise Program007Error("Program 007 response body must be bytes")
        if self.responses >= MAXIMUM_HTTP_RESPONSES:
            raise Program007Error("Program 007 HTTP response ceiling exceeded")
        if len(body) > MAXIMUM_RESPONSE_PAGE_BYTES:
            raise Program007Error("Program 007 response exceeds the 8 MiB page ceiling")
        if self.response_bytes + len(body) > MAXIMUM_DOWNLOADED_BYTES:
            raise Program007Error("Program 007 downloaded-byte ceiling exceeded")
        self.responses += 1
        self.response_bytes += len(body)


def frozen_request_chains(proposal_bytes: bytes) -> tuple[RequestChain, ...]:
    if type(proposal_bytes) is not bytes:
        raise Program007Error("Program 007 proposal must be exact bytes")
    proposal = _load_json_object(proposal_bytes, "Program 007 proposal")
    unsigned = dict(proposal)
    stored_fingerprint = unsigned.pop("proposal_fingerprint", None)
    if (
        stored_fingerprint != _PROPOSAL_FINGERPRINT
        or fingerprint(unsigned) != _PROPOSAL_FINGERPRINT
    ):
        raise Program007Error("Program 007 proposal fingerprint differs")
    if hashlib.sha256(proposal_bytes).hexdigest() != _PROPOSAL_SHA256:
        raise Program007Error("Program 007 proposal bytes differ")
    if proposal.get("program_id") != PROGRAM_ID or proposal.get("status") != STATUS:
        raise Program007Error("Program 007 proposal identity differs")
    authority = _mapping(proposal.get("authority"), "proposal authority")
    if set(authority) != _AUTHORITY_FIELDS or any(
        value is not False for value in authority.values()
    ):
        raise Program007Error("Program 007 proposal grants authority")
    plan = tuple(
        (
            _string(item.get("range_id"), "range id"),
            _string(item.get("start"), "request start"),
            _string(item.get("end"), "request end"),
            _integer(item.get("session_count"), "session count"),
            _integer(item.get("maximum_pages"), "maximum pages"),
        )
        for item in (
            _mapping(raw, "request range")
            for raw in _sequence(proposal.get("request_plan"), "request plan")
        )
    )
    if plan != _FROZEN_REQUEST_PLAN:
        raise Program007Error("Program 007 frozen request ranges differ")
    chains = _frozen_request_chains()
    budget = _mapping(proposal.get("transport_budget"), "transport budget")
    frozen_budget = {
        "logical_chain_count": 6,
        "minimum_expected_http_requests": 7,
        "minimum_expected_http_responses": 7,
        "maximum_http_requests": MAXIMUM_HTTP_REQUESTS,
        "maximum_http_responses": MAXIMUM_HTTP_RESPONSES,
        "maximum_downloaded_bytes": MAXIMUM_DOWNLOADED_BYTES,
        "maximum_response_page_bytes": MAXIMUM_RESPONSE_PAGE_BYTES,
        "maximum_requests_per_minute": MAXIMUM_REQUESTS_PER_MINUTE,
        "maximum_credential_loads": 1,
        "automatic_transport_retries": AUTOMATIC_TRANSPORT_RETRIES,
        "minimum_pagination_pages": 2,
    }
    if any(budget.get(key) != value for key, value in frozen_budget.items()):
        raise Program007Error("Program 007 transport budget differs")
    if len(chains) != 6 or sum(chain.maximum_pages for chain in chains) != 11:
        raise Program007Error("Program 007 frozen request shape differs")
    return chains


def _frozen_request_chains() -> tuple[RequestChain, ...]:
    return tuple(
        RequestChain(
            chain_id=range_id,
            start=_parse_utc(start),
            end=_parse_utc(end),
            symbols=SYMBOLS,
            maximum_pages=maximum_pages,
        )
        for range_id, start, end, _session_count, maximum_pages in _FROZEN_REQUEST_PLAN
    )


def parse_raw_page(
    body: bytes, chain: RequestChain, *, preserve_received_order: bool = False
) -> tuple[tuple[RawBar, ...], str | None]:
    payload = _load_json_object(body, "Program 007 response")
    if set(payload) != {"bars", "next_page_token"}:
        raise Program007Error("Program 007 response schema differs")
    next_token = payload["next_page_token"]
    if next_token is not None and (not isinstance(next_token, str) or not next_token):
        raise Program007Error("Program 007 next_page_token is malformed")
    bars_by_symbol = _mapping(payload["bars"], "response bars")
    allowed_symbols = set(chain.symbols)
    session_dates = set(chain.session_dates)
    bars: list[RawBar] = []
    coordinates: set[tuple[str, datetime]] = set()
    for symbol, raw_rows in bars_by_symbol.items():
        if not isinstance(symbol, str) or symbol not in allowed_symbols:
            raise Program007Error("Program 007 response contains a foreign symbol")
        rows = _sequence(raw_rows, "symbol bars")
        for raw_row in rows:
            row = _mapping(raw_row, "bar")
            if (
                not {"t", "o", "h", "l", "c", "v"}
                <= set(row)
                <= {
                    "t",
                    "o",
                    "h",
                    "l",
                    "c",
                    "v",
                    "n",
                    "vw",
                }
            ):
                raise Program007Error("Program 007 bar schema differs")
            timestamp = _parse_bar_timestamp(row["t"])
            if not chain.start <= timestamp <= chain.end:
                raise Program007Error("Program 007 bar is outside the inclusive request bounds")
            if timestamp.astimezone(_NEW_YORK).date() not in session_dates:
                raise Program007Error("Program 007 bar is outside an XNYS session date")
            bar = RawBar(
                symbol=symbol,
                timestamp=timestamp,
                open=_positive_decimal(row["o"], "open"),
                high=_positive_decimal(row["h"], "high"),
                low=_positive_decimal(row["l"], "low"),
                close=_positive_decimal(row["c"], "close"),
                volume=_nonnegative_decimal(row["v"], "volume"),
                trade_count=_optional_nonnegative_integer(row.get("n"), "trade count"),
                vwap=_optional_positive_decimal(row.get("vw"), "VWAP"),
            )
            if bar.high < max(bar.open, bar.low, bar.close) or bar.low > min(
                bar.open, bar.high, bar.close
            ):
                raise Program007Error("Program 007 OHLC range is invalid")
            if bar.coordinate in coordinates:
                raise Program007Error("Program 007 response contains a duplicate coordinate")
            coordinates.add(bar.coordinate)
            bars.append(bar)
            if len(bars) > 10_000:
                raise Program007Error("Program 007 response exceeds the 10,000-row page limit")
    return tuple(bars if preserve_received_order else sorted(bars)), next_token


def project_rth(rows: Sequence[RawBar], chain: RequestChain) -> tuple[RawBar, ...]:
    grid = set(expected_bar_timestamps(chain.start, chain.end, Timeframe.FIVE_MINUTES))
    return tuple(sorted(row for row in rows if row.timestamp in grid))


def execute_synthetic_qualification(
    proposal_bytes: bytes,
    page_source: SyntheticPageSource,
    *,
    observed_at: datetime | None = None,
) -> QualificationResult:
    """Run the exact frozen proposal against finite in-memory responses."""
    _require_synthetic_source(page_source)
    exact_observed_at = datetime.now(UTC) if observed_at is None else observed_at
    _require_synthetic_observed_at(exact_observed_at)
    return _execute_qualification(
        frozen_request_chains(proposal_bytes), page_source, observed_at=exact_observed_at
    )


def _execute_qualification(
    chains: Sequence[RequestChain],
    page_source: SyntheticPageSource,
    *,
    observed_at: datetime,
) -> QualificationResult:
    _require_synthetic_observed_at(observed_at)
    exact_chains = tuple(chains)
    if any(type(chain) is not RequestChain for chain in exact_chains) or (
        exact_chains != _frozen_request_chains()
    ):
        raise Program007Error("Program 007 execution requires the exact frozen request plan")
    _require_synthetic_source(page_source)
    with _evidence_store(page_source) as store:
        _validate_restart_state(store, exact_chains)
        budget = _Budget()
        results = tuple(
            _execute_chain_store(chain, page_source, budget, observed_at, store)
            for chain in exact_chains
        )
        result = QualificationResult(results)
        _publish_record(
            store,
            "private-manifest.json",
            result.private_manifest(),
            allow_identical=True,
        )
        return result


def validate_action_ledger(ledger: Mapping[str, Any]) -> None:
    expected_top_level = {
        "schema_version",
        "ledger_id",
        "program_id",
        "status",
        "schema_binding",
        "chronology",
        "normalization",
        "non_transformable_policy",
        "symbols",
        "actions",
        "historical_context",
        "evidence",
        "archive_coverage",
        "authority",
        "ledger_fingerprint",
    }
    _exact_keys(ledger, expected_top_level, "action ledger")
    unsigned = dict(ledger)
    stored_fingerprint = unsigned.pop("ledger_fingerprint")
    if stored_fingerprint != fingerprint(unsigned):
        raise Program007Error("Program 007 action ledger fingerprint differs")
    if (
        ledger["schema_version"] != "program-007-unit-changing-action-ledger-v3"
        or not _string(ledger["ledger_id"], "ledger id")
        or ledger["program_id"] != PROGRAM_ID
        or ledger["status"] != "PUBLIC-EVIDENCE-SUFFICIENT-FOR-FROZEN-FEATURE"
    ):
        raise Program007Error("Program 007 action ledger identity differs")
    schema_binding = _mapping(ledger["schema_binding"], "schema binding")
    _exact_keys(schema_binding, {"path", "sha256"}, "schema binding")
    if (
        schema_binding["path"]
        != "config/research/program-007-unit-changing-action-ledger-v3.schema.json"
        or not _HEX_64.fullmatch(_string(schema_binding["sha256"], "schema SHA-256"))
    ):
        raise Program007Error("Program 007 action schema SHA-256 differs")
    chronology = _mapping(ledger["chronology"], "ledger chronology")
    _exact_keys(
        chronology,
        {"start_session", "end_session", "prehistory_rule"},
        "ledger chronology",
    )
    if chronology["start_session"] != "2020-06-26" or chronology["end_session"] != "2026-07-31":
        raise Program007Error("Program 007 action chronology differs")
    _string(chronology["prehistory_rule"], "prehistory rule")

    evidence_items = _sequence(ledger["evidence"], "ledger evidence")
    evidence_ids: set[str] = set()
    for raw in evidence_items:
        item = _mapping(raw, "evidence item")
        _exact_keys(
            item,
            {"evidence_id", "classification", "title", "url", "retrieved_date", "supports"},
            "evidence item",
        )
        evidence_id = _string(item["evidence_id"], "evidence id")
        if evidence_id in evidence_ids or not _string(item["url"], "evidence URL").startswith(
            "https://"
        ):
            raise Program007Error("Program 007 action evidence differs")
        evidence_ids.add(evidence_id)
        if item["classification"] not in {
            "ISSUER-PRIMARY",
            "EXCHANGE-PRIMARY",
            "SEC-PRIMARY",
            "REGULATOR-PRIMARY",
        }:
            raise Program007Error("Program 007 evidence classification differs")
        _parse_date(_string(item["retrieved_date"], "retrieval date"))
        _string(item["title"], "evidence title")
        supports = _strings(item["supports"], "evidence supports")
        if not supports or len(supports) != len(set(supports)):
            raise Program007Error("Program 007 evidence support is empty")

    action_items = _sequence(ledger["actions"], "ledger actions")
    action_ids: set[str] = set()
    actions_by_symbol: dict[str, list[Mapping[str, Any]]] = {symbol: [] for symbol in SYMBOLS}
    for raw in action_items:
        action = _mapping(raw, "ledger action")
        _exact_keys(
            action,
            {
                "action_id",
                "symbol",
                "fund_identity",
                "action_type",
                "announcement_date",
                "record_date",
                "payable_date",
                "effective_session",
                "effective_time_semantics",
                "old_shares",
                "new_shares",
                "transformable",
                "price_unit_effect",
                "share_volume_unit_effect",
                "normalization_rule",
                "affects_program_history",
                "evidence_ids",
            },
            "ledger action",
        )
        action_id = _string(action["action_id"], "action id")
        symbol = _string(action["symbol"], "action symbol")
        if action_id in action_ids or symbol not in actions_by_symbol:
            raise Program007Error("Program 007 action identity differs")
        action_ids.add(action_id)
        old_shares = _positive_integer(action["old_shares"], "old shares")
        new_shares = _positive_integer(action["new_shares"], "new shares")
        for key in (
            "fund_identity",
            "effective_time_semantics",
            "price_unit_effect",
            "share_volume_unit_effect",
            "normalization_rule",
        ):
            _string(action[key], key.replace("_", " "))
        action_type = action["action_type"]
        if (
            action_type not in {"forward_split", "reverse_split"}
            or (action_type == "forward_split" and new_shares <= old_shares)
            or (action_type == "reverse_split" and new_shares >= old_shares)
            or action["transformable"] is not True
            or action["affects_program_history"] is not True
        ):
            raise Program007Error("Program 007 split ratio is inconsistent")
        action_dates = [
            _parse_date(_string(action[key], key.replace("_", " ")))
            for key in ("announcement_date", "record_date", "payable_date", "effective_session")
        ]
        if action_dates != sorted(action_dates):
            raise Program007Error("Program 007 split chronology is inconsistent")
        action_evidence = _strings(action["evidence_ids"], "action evidence ids")
        linked_evidence = set(action_evidence)
        if (
            not linked_evidence
            or len(linked_evidence) != len(action_evidence)
            or not linked_evidence <= evidence_ids
        ):
            raise Program007Error("Program 007 action evidence binding differs")
        actions_by_symbol[symbol].append(action)

    if set(actions_by_symbol) != set(SYMBOLS) or set(actions_by_symbol) - _ACTION_SYMBOLS != {
        symbol for symbol, actions in actions_by_symbol.items() if not actions
    }:
        raise Program007Error("Program 007 action symbol coverage differs")
    for symbol in _ACTION_SYMBOLS:
        actions = actions_by_symbol[symbol]
        if (
            len(actions) != 1
            or actions[0]["effective_session"] != "2025-12-05"
            or actions[0]["old_shares"] != 1
            or actions[0]["new_shares"] != 2
        ):
            raise Program007Error("Program 007 frozen split control differs")

    symbol_items = _sequence(ledger["symbols"], "ledger symbols")
    if len(symbol_items) != len(SYMBOLS):
        raise Program007Error("Program 007 ledger symbol count differs")
    seen_symbols: list[str] = []
    for raw in symbol_items:
        item = _mapping(raw, "symbol coverage")
        _exact_keys(
            item,
            {
                "symbol",
                "cusip",
                "sec_cik",
                "exchange",
                "fund_identity",
                "known_names",
                "coverage_start",
                "coverage_end",
                "identity_continuity_classification",
                "action_coverage_classification",
                "coverage_status",
                "conclusion",
                "action_ids",
                "evidence_ids",
                "continuity_notes",
            },
            "symbol coverage",
        )
        symbol = _string(item["symbol"], "coverage symbol")
        _string(item["fund_identity"], "coverage fund identity")
        _string(item["continuity_notes"], "coverage continuity notes")
        known_names = _strings(item["known_names"], "known fund names")
        seen_symbols.append(symbol)
        action_links = _strings(item["action_ids"], "coverage action ids")
        evidence_links = _strings(item["evidence_ids"], "coverage evidence ids")
        linked_actions = set(action_links)
        expected_actions = {
            str(action["action_id"]) for action in actions_by_symbol.get(symbol, [])
        }
        linked_evidence = set(evidence_links)
        expected_conclusion = (
            "APPLICABLE-ACTIONS-RECORDED" if expected_actions else "NO-APPLICABLE-ACTION-FOUND"
        )
        expected_classification = (
            "CONFIRMED-ACTION" if expected_actions else "SUPPORTED-NO-KNOWN-ACTION"
        )
        if (
            item["coverage_start"] != "2020-06-26"
            or item["coverage_end"] != "2026-07-31"
            or item["coverage_status"] != "COMPLETE"
            or item["conclusion"] != expected_conclusion
            or item["cusip"] != _CUSIPS_BY_SYMBOL.get(symbol)
            or item["sec_cik"] != _CIKS_BY_SYMBOL.get(symbol)
            or item["exchange"] != "NYSE Arca"
            or item["identity_continuity_classification"] != "CONTINUOUS-CANONICAL-IDENTITY"
            or item["action_coverage_classification"] != expected_classification
            or not known_names
            or len(known_names) != len(set(known_names))
            or linked_actions != expected_actions
            or len(linked_actions) != len(action_links)
            or not linked_evidence
            or len(linked_evidence) != len(evidence_links)
            or not linked_evidence <= evidence_ids
        ):
            raise Program007Error("Program 007 symbol action coverage differs")
    if tuple(seen_symbols) != SYMBOLS:
        raise Program007Error("Program 007 ledger symbols are not canonical")

    authority = _mapping(ledger["authority"], "ledger authority")
    if set(authority) != _AUTHORITY_FIELDS or any(
        value is not False for value in authority.values()
    ):
        raise Program007Error("Program 007 action ledger grants authority")
    normalization = _mapping(ledger["normalization"], "normalization contract")
    _exact_keys(
        normalization,
        {
            "basis",
            "factor_representation",
            "effective_boundary",
            "prior_volume_rule",
            "same_session_price_rule",
            "same_session_return_proof",
            "raw_dollar_volume_proof",
            "reverse_split_rule",
            "multiple_action_rule",
        },
        "normalization contract",
    )
    if normalization.get("factor_representation") != "exact Fraction new_shares/old_shares":
        raise Program007Error("Program 007 normalization representation differs")
    for key, value in normalization.items():
        _string(value, key.replace("_", " "))
    policy = _mapping(ledger["non_transformable_policy"], "non-transformable policy")
    _exact_keys(
        policy,
        {"scope", "action", "missingness_budget_can_override", "reason"},
        "non-transformable policy",
    )
    if (
        policy.get("action") != "FAIL-DATASET-ADMISSION-BEFORE-STRATEGY"
        or policy.get("missingness_budget_can_override") is not False
    ):
        raise Program007Error("Program 007 non-transformable action policy differs")
    _string(policy["scope"], "non-transformable scope")
    _string(policy["reason"], "non-transformable reason")

    context_items = _sequence(ledger["historical_context"], "historical context")
    context_ids: set[str] = set()
    for raw in context_items:
        item = _mapping(raw, "historical context item")
        _exact_keys(
            item,
            {
                "context_id",
                "symbols",
                "effective_date",
                "classification",
                "description",
                "program_effect",
                "evidence_ids",
            },
            "historical context item",
        )
        context_id = _string(item["context_id"], "historical context id")
        context_symbols = _strings(item["symbols"], "historical context symbols")
        context_evidence = _strings(item["evidence_ids"], "historical context evidence")
        if (
            context_id in context_ids
            or not context_symbols
            or not set(context_symbols) <= set(SYMBOLS)
            or len(context_symbols) != len(set(context_symbols))
            or not context_evidence
            or not set(context_evidence) <= evidence_ids
            or len(context_evidence) != len(set(context_evidence))
            or item["classification"] not in {"OUTSIDE-CHRONOLOGY", "NON-UNIT-CHANGING"}
        ):
            raise Program007Error("Program 007 historical context differs")
        context_ids.add(context_id)
        _parse_date(_string(item["effective_date"], "historical context date"))
        _string(item["description"], "historical context description")
        _string(item["program_effect"], "historical context program effect")

    _validate_archive_coverage(ledger["archive_coverage"])


def _validate_archive_coverage(raw: Any) -> None:
    coverage = _mapping(raw, "archive coverage")
    _exact_keys(
        coverage,
        {
            "status",
            "dataset_admission",
            "resolved_symbols",
            "unresolved_symbols",
            "coverage_standard",
            "limitations",
            "nyse_corpax",
            "primary_corpora",
        },
        "archive coverage",
    )
    if (
        coverage["status"] != "SUFFICIENT-FOR-FROZEN-FEATURE"
        or coverage["dataset_admission"] != "ACTION-COVERAGE-GATE-PASS"
        or _strings(coverage["resolved_symbols"], "resolved symbols") != SYMBOLS
        or _strings(coverage["unresolved_symbols"], "unresolved symbols") != ()
    ):
        raise Program007Error("Program 007 archive coverage disposition differs")
    _string(coverage["coverage_standard"], "archive coverage standard")
    _string(coverage["limitations"], "archive limitations")

    nyse = _mapping(coverage["nyse_corpax"], "NYSE archive coverage")
    _exact_keys(
        nyse,
        {
            "archive_id",
            "source",
            "url",
            "retrieved_at_utc",
            "coverage_start",
            "coverage_end",
            "retrieval_method",
            "interval_count",
            "request_count",
            "dated_record_count",
            "unique_market_event_count",
            "out_of_window_dated_count",
            "null_dated_rows_excluded",
            "retrieval_manifest_binding",
            "dated_records_sha256",
            "forward_splits_in_scope",
            "scope_includes",
            "scope_excludes",
            "target_record_count",
            "target_records_fingerprint",
            "target_records",
            "conclusion",
        },
        "NYSE archive coverage",
    )
    if (
        nyse["archive_id"] != "nyse-corpax-2020-06-26-to-2026-07-31-v1"
        or nyse["source"] != "NYSE Corporate Actions"
        or nyse["url"] != "https://www.nyse.com/api/nyseservice/v1/corpax/"
        or nyse["coverage_start"] != "2020-06-26"
        or nyse["coverage_end"] != "2026-07-31"
        or nyse["interval_count"] != 319
        or nyse["request_count"] != 326
        or nyse["dated_record_count"] != 11_345
        or nyse["unique_market_event_count"] != 11_345
        or nyse["out_of_window_dated_count"] != 0
        or nyse["null_dated_rows_excluded"] is not True
        or nyse["dated_records_sha256"]
        != "a7150d3bada745e3046ddeccd64a9be27fb1b23735674accc5dba318b2b3605b"
        or nyse["forward_splits_in_scope"] is not False
        or nyse["target_record_count"] != 12
        or nyse["target_records_fingerprint"]
        != "e4d28699ea6ca7ed3a147c12a92706bb9ecbc2ef6e1313531103dd864d89dba8"
        or nyse["conclusion"] != "COMPLETE-FOR-CORPAX-SCOPE-NOT-FOR-FORWARD-SPLITS"
    ):
        raise Program007Error("Program 007 NYSE archive evidence differs")
    _parse_utc(_string(nyse["retrieved_at_utc"], "NYSE retrieval timestamp"))
    _string(nyse["retrieval_method"], "NYSE retrieval method")
    if not _strings(nyse["scope_includes"], "NYSE included scope") or not _strings(
        nyse["scope_excludes"], "NYSE excluded scope"
    ):
        raise Program007Error("Program 007 NYSE archive scope is empty")

    binding = _mapping(nyse["retrieval_manifest_binding"], "NYSE manifest binding")
    _exact_keys(
        binding,
        {"path", "sha256", "fingerprint", "entries_fingerprint"},
        "NYSE manifest binding",
    )
    expected_binding = {
        "path": "config/research/program-007-nyse-corpax-retrieval-manifest-v1.json",
        "sha256": "48b85bb63c02e59b8538eed741237d9d9a386dc36caa4c3cc1e7b5856bd735f5",
        "fingerprint": "b0fc71436088824df6126bbfd950232e0b55da6233b34c11b40480c3495dcbeb",
        "entries_fingerprint": "bdcea47c663440353ce3b31abdd43222d907f9b7c93f55247d79da19414cbac1",
    }
    if dict(binding) != expected_binding:
        raise Program007Error("Program 007 NYSE retrieval manifest binding differs")

    target_items = _sequence(nyse["target_records"], "NYSE target records")
    expected_targets = (
        ("XLB", "2025-12-01", "Change Product Name", "727d94c6-0065-492c-901d-19d20cdfb8ff"),
        ("XLE", "2025-12-01", "Change Product Name", "2536ba87-e518-4aed-b20f-e82d5d717ebd"),
        ("XLF", "2025-12-01", "Change Product Name", "236199eb-e4de-4523-aea5-dafb8ec35942"),
        ("XLI", "2025-12-01", "Change Product Name", "330db11e-fd66-4da2-ad06-9974e0131303"),
        ("XLK", "2025-12-01", "Change Product Name", "32d4c86b-ba68-4d86-a98b-b2a325ef27b4"),
        ("XLP", "2025-12-01", "Change Product Name", "25319a73-7e10-4a0b-875d-274d58c318ca"),
        ("XLRE", "2025-12-01", "Change Product Name", "3b953281-3bd8-44fe-9884-c26b8e9ad5ff"),
        ("XLU", "2025-12-01", "Change Product Name", "12bd1f06-51df-4493-a3ab-17fb4d2ce43d"),
        ("XLV", "2025-12-01", "Change Product Name", "24491509-c0dd-42e1-9a1e-89057cb4ad73"),
        ("XLY", "2025-12-01", "Change Product Name", "e32db1a5-bea2-42b6-a2d7-4bfd69f61de7"),
        ("SPY", "2026-01-26", "Change Name", "4e289aed-4467-49a5-b7c0-3cea1ad5e644"),
        ("MDY", "2026-01-28", "Change Name", "5358a165-d737-4e29-99d7-d631d1320a61"),
    )
    observed_targets: list[tuple[str, str, str, str]] = []
    for raw_item in target_items:
        item = _mapping(raw_item, "NYSE target record")
        _exact_keys(
            item,
            {
                "market_event",
                "action_date",
                "action_status",
                "action_type",
                "symbol",
                "issuer_name",
                "updated_at",
                "classification",
                "ledger_action_id",
            },
            "NYSE target record",
        )
        observed_targets.append(
            (
                _string(item["symbol"], "NYSE target symbol"),
                _string(item["action_date"], "NYSE target date"),
                _string(item["action_type"], "NYSE target action type"),
                _string(item["market_event"], "NYSE target event"),
            )
        )
        _parse_date(_string(item["action_date"], "NYSE target date"))
        for key in ("action_status", "issuer_name", "updated_at"):
            _string(item[key], f"NYSE target {key}")
        if (
            item["classification"] != "NON-UNIT-CHANGING-IDENTITY-CONTINUITY"
            or item["ledger_action_id"] is not None
        ):
            raise Program007Error("Program 007 NYSE target classification differs")
    if (
        tuple(observed_targets) != expected_targets
        or fingerprint(target_items) != nyse["target_records_fingerprint"]
    ):
        raise Program007Error("Program 007 NYSE target records differ")

    corpus_items = _sequence(coverage["primary_corpora"], "primary corpora")
    expected_corpora = {
        "sec-select-sector-spdr-2020-06-26-to-2026-07-31-v1": (
            tuple(symbol for symbol in SYMBOLS if symbol.startswith("XL")),
            51,
            51,
            "https://data.sec.gov/submissions/CIK0001064641.json",
            "c99870acd2ae8360c9c99c4e0abbc44318f787cf412096e8676324d9eda9c752",
            "FIVE-SPLITS-FOUND-NO-OTHER-UNIT-ACTION-IN-SCREEN",
        ),
        "sec-ishares-trust-2020-06-26-to-2026-07-31-v1": (
            ("IWM",),
            1_038,
            383,
            "https://data.sec.gov/submissions/CIK0001100663.json",
            "3eea92ce0d8af4be24671e6fabe49ab560c99b68b5230847666e8018233247c1",
            "NO-APPLICABLE-ACTION-FOUND-IN-BOUNDED-SCREEN",
        ),
        "sec-spy-2020-06-26-to-2026-07-31-v1": (
            ("SPY",),
            68,
            68,
            "https://data.sec.gov/submissions/CIK0000884394.json",
            "6d5e8853788fa245b40daa3f47583da2f05b70212c68380b929a155f8ea5e16a",
            "NO-APPLICABLE-ACTION-FOUND-IN-BOUNDED-SCREEN",
        ),
        "sec-mdy-2020-06-26-to-2026-07-31-v1": (
            ("MDY",),
            54,
            54,
            "https://data.sec.gov/submissions/CIK0000936958.json",
            "6322b7a15c642e4c376e383b3b14ee883ac101b5312302bf9bf2a9ccdc6839be",
            "NO-APPLICABLE-ACTION-FOUND-IN-BOUNDED-SCREEN",
        ),
    }
    seen_corpora: list[str] = []
    for raw_item in corpus_items:
        item = _mapping(raw_item, "primary corpus")
        _exact_keys(
            item,
            {
                "corpus_id",
                "authority",
                "issuer",
                "symbols",
                "endpoint",
                "coverage_start",
                "coverage_end",
                "retrieval_date",
                "manifest_definition",
                "candidate_document_count",
                "screened_document_count",
                "subject_document_count",
                "form_counts",
                "manifest_sha256",
                "finding",
                "limitations",
            },
            "primary corpus",
        )
        corpus_id = _string(item["corpus_id"], "corpus id")
        seen_corpora.append(corpus_id)
        expected = expected_corpora.get(corpus_id)
        if expected is None:
            raise Program007Error("Program 007 primary corpus differs")
        symbols, candidate_count, subject_count, endpoint, manifest_sha256, finding = expected
        if (
            item["authority"] != "SEC"
            or _strings(item["symbols"], "corpus symbols") != symbols
            or item["endpoint"] != endpoint
            or item["coverage_start"] != "2020-06-26"
            or item["coverage_end"] != "2026-07-31"
            or item["retrieval_date"] != "2026-08-28"
            or item["candidate_document_count"] != candidate_count
            or item["screened_document_count"] != candidate_count
            or item["subject_document_count"] != subject_count
            or item["manifest_sha256"] != manifest_sha256
            or item["finding"] != finding
        ):
            raise Program007Error("Program 007 primary corpus evidence differs")
        for key in ("issuer", "manifest_definition", "limitations"):
            _string(item[key], f"corpus {key}")
        form_items = _sequence(item["form_counts"], "corpus form counts")
        seen_forms: set[str] = set()
        form_total = 0
        for raw_form in form_items:
            form = _mapping(raw_form, "corpus form count")
            _exact_keys(form, {"form", "count"}, "corpus form count")
            form_name = _string(form["form"], "corpus form")
            if form_name in seen_forms:
                raise Program007Error("Program 007 corpus form is repeated")
            seen_forms.add(form_name)
            form_total += _positive_integer(form["count"], "corpus form count")
        if form_total != candidate_count:
            raise Program007Error("Program 007 corpus form count differs")
    if tuple(seen_corpora) != tuple(expected_corpora):
        raise Program007Error("Program 007 primary corpus order differs")


def require_action_ledger_admission(ledger: Mapping[str, Any]) -> None:
    """Reject normalization until every symbol has sufficient public action coverage."""
    validate_action_ledger(ledger)
    coverage = _mapping(ledger["archive_coverage"], "archive coverage")
    unresolved = _strings(coverage["unresolved_symbols"], "unresolved symbols")
    if unresolved or coverage["dataset_admission"] != "ACTION-COVERAGE-GATE-PASS":
        raise Program007Error(
            "Program 007 action coverage is unresolved for "
            f"{', '.join(unresolved)}; normalization is blocked"
        )


def load_action_ledger(path: Path) -> Mapping[str, Any]:
    ledger = _load_json_object(path.read_bytes(), "action ledger")
    validate_action_ledger(ledger)
    return MappingProxyType(ledger)


def share_unit_factor(
    ledger: Mapping[str, Any], symbol: str, source_session: date, basis_session: date
) -> Fraction:
    """Map one source-session share unit into the requested basis-session unit."""
    require_action_ledger_admission(ledger)
    if symbol not in SYMBOLS:
        raise Program007Error("Program 007 normalization symbol is unknown")
    chronology = _mapping(ledger["chronology"], "ledger chronology")
    start = _parse_date(_string(chronology["start_session"], "chronology start"))
    end = _parse_date(_string(chronology["end_session"], "chronology end"))
    if not start <= source_session <= end or not start <= basis_session <= end:
        raise Program007Error("Program 007 normalization session is outside ledger coverage")
    return share_unit_factor_for_actions(
        _sequence(ledger["actions"], "ledger actions"),
        symbol,
        source_session,
        basis_session,
    )


def share_unit_factor_for_actions(
    actions: Sequence[Mapping[str, Any]],
    symbol: str,
    source_session: date,
    basis_session: date,
) -> Fraction:
    """Return an exact factor for synthetic or ledger-validated split actions."""
    factor = Fraction(1)
    effective_actions: list[tuple[date, Fraction]] = []
    for action in actions:
        if action.get("symbol") != symbol:
            continue
        if action.get("transformable") is not True or action.get("action_type") not in {
            "forward_split",
            "reverse_split",
        }:
            raise Program007Error("Program 007 action is not safely transformable")
        effective = _parse_date(_string(action.get("effective_session"), "effective session"))
        ratio = Fraction(
            _positive_integer(action.get("new_shares"), "new shares"),
            _positive_integer(action.get("old_shares"), "old shares"),
        )
        action_type = action["action_type"]
        if (action_type == "forward_split" and ratio <= 1) or (
            action_type == "reverse_split" and ratio >= 1
        ):
            raise Program007Error("Program 007 split ratio is inconsistent")
        effective_actions.append((effective, ratio))
    for effective, ratio in sorted(effective_actions):
        if source_session < effective <= basis_session:
            factor *= ratio
        elif basis_session < effective <= source_session:
            factor /= ratio
    return factor


def normalize_share_volume(
    volume: int | Decimal | Fraction,
    ledger: Mapping[str, Any],
    symbol: str,
    source_session: date,
    basis_session: date,
) -> Fraction:
    if isinstance(volume, bool) or not isinstance(volume, int | Decimal | Fraction):
        raise Program007Error("Program 007 volume must be exact numeric data")
    exact = Fraction(volume)
    if exact < 0:
        raise Program007Error("Program 007 volume must be nonnegative")
    return exact * share_unit_factor(ledger, symbol, source_session, basis_session)


def _execute_chain(
    chain: RequestChain,
    page_source: SyntheticPageSource,
    budget: _Budget,
    observed_at: datetime,
) -> ChainResult:
    _require_synthetic_observed_at(observed_at)
    if type(chain) is not RequestChain or chain not in _frozen_request_chains():
        raise Program007Error("Program 007 request chain is outside the exact frozen plan")
    _require_synthetic_source(page_source)
    with _evidence_store(page_source) as store:
        _validate_restart_state(store, (chain,))
        return _execute_chain_store(chain, page_source, budget, observed_at, store)


def _execute_chain_store(
    chain: RequestChain,
    page_source: SyntheticPageSource,
    budget: _Budget,
    observed_at: datetime,
    store: _EvidenceStore,
) -> ChainResult:
    rows: list[RawBar] = []
    pages: list[PageEvidence] = []
    seen_coordinates: set[tuple[str, datetime]] = set()
    seen_tokens: set[str] = set()
    seen_hashes: set[str] = set()
    incoming_token: str | None = None
    chain_prefix = f"chains/{chain.identity}"

    for page_index in range(1, chain.maximum_pages + 1):
        intent = RequestIntent(
            chain.chain_id,
            chain.identity,
            page_index,
            chain.url(incoming_token),
            incoming_token,
        )
        page_name = f"{page_index:05d}"
        intent_key = f"{chain_prefix}/requests/{page_name}.json"
        page_prefix = f"{chain_prefix}/pages/{page_name}"
        outcome_key = f"{page_prefix}/validation.json"
        budget.reserve_request()
        retained_response = store.exists(intent_key)
        if retained_response:
            intent_record = _load_record(store, intent_key)
            _validate_intent(intent_record, intent)
            if not (
                store.exists(f"{page_prefix}/body.json")
                and store.exists(f"{page_prefix}/receipt.json")
            ):
                raise Program007Error(
                    "Program 007 request outcome is ambiguous; zero-retry policy blocks replay"
                )
        else:
            _publish_record(
                store,
                intent_key,
                {
                    "schema_version": "program-007-private-request-intent-v1",
                    **_intent_record(intent),
                    "created_at_utc": _iso_utc(observed_at),
                    "automatic_transport_retries": AUTOMATIC_TRANSPORT_RETRIES,
                    "credentials_stored": False,
                },
            )
            try:
                response = _next_synthetic_response(page_source, intent)
            except Exception:
                raise Program007Error(
                    "Program 007 request outcome is ambiguous; zero-retry policy blocks replay"
                ) from None
            if type(response) is not RawResponse:
                raise Program007Error(
                    "Program 007 request outcome is ambiguous; zero-retry policy blocks replay"
                )
            budget.accept_response(response.body)
            _retain_response(store, page_prefix, intent, response, observed_at)

        response = _load_response(store, page_prefix, intent)
        if retained_response:
            budget.accept_response(response.body)

        existing_outcome = _load_record(store, outcome_key) if store.exists(outcome_key) else None
        if existing_outcome is not None and existing_outcome.get("raw_structural_status") == "FAIL":
            raise Program007Error(_string(existing_outcome.get("failure"), "stored failure"))
        try:
            if response.status != 200:
                raise Program007Error("Program 007 response status is not 200")
            page_rows, outgoing_token = parse_raw_page(response.body, chain)
            response_sha256 = hashlib.sha256(response.body).hexdigest()
            if response_sha256 in seen_hashes:
                raise Program007Error("Program 007 response page is repeated")
            duplicates = seen_coordinates & {row.coordinate for row in page_rows}
            if duplicates:
                raise Program007Error("Program 007 coordinate repeats across pages")
            if outgoing_token is not None:
                if outgoing_token in seen_tokens or outgoing_token == incoming_token:
                    raise Program007Error("Program 007 pagination token is repeated")
                if not page_rows:
                    raise Program007Error("Program 007 nonterminal page is empty")
                if page_index == chain.maximum_pages:
                    raise Program007Error("Program 007 chain page ceiling exceeded")
            canonical = project_rth(page_rows, chain)
            page_identity = fingerprint(
                {
                    "chain_identity": chain.identity,
                    "page_index": page_index,
                    "incoming_page_token": incoming_token,
                    "outgoing_page_token": outgoing_token,
                    "response_sha256": response_sha256,
                }
            )
            outcome = {
                "schema_version": "program-007-private-page-validation-v1",
                "chain_identity": chain.identity,
                "page_index": page_index,
                "page_identity": page_identity,
                "incoming_page_token": incoming_token,
                "outgoing_page_token": outgoing_token,
                "response_sha256": response_sha256,
                "parse_status": "PASS",
                "raw_structural_status": "PASS",
                "rth_projection_status": "PASS",
                "raw_row_count": len(page_rows),
                "canonical_row_count": len(canonical),
                "extended_hours_row_count": len(page_rows) - len(canonical),
            }
            _publish_validation(store, outcome_key, outcome, observed_at, existing_outcome)
        except Program007Error as error:
            failure = {
                "schema_version": "program-007-private-page-validation-v1",
                "chain_identity": chain.identity,
                "page_index": page_index,
                "response_sha256": hashlib.sha256(response.body).hexdigest(),
                "parse_status": "FAIL",
                "raw_structural_status": "FAIL",
                "rth_projection_status": "NOT-RUN",
                "failure": str(error),
            }
            _publish_validation(store, outcome_key, failure, observed_at, existing_outcome)
            raise

        seen_hashes.add(response_sha256)
        seen_coordinates.update(row.coordinate for row in page_rows)
        if outgoing_token is not None:
            seen_tokens.add(outgoing_token)
        rows.extend(page_rows)
        pages.append(
            PageEvidence(
                chain.chain_id,
                chain.identity,
                page_index,
                intent.url,
                incoming_token,
                outgoing_token,
                response_sha256,
                len(response.body),
                page_identity,
                len(page_rows),
                len(canonical),
                len(page_rows) - len(canonical),
            )
        )
        if outgoing_token is None:
            break
        incoming_token = outgoing_token
    else:
        raise Program007Error("Program 007 chain did not terminate")

    raw_rows = tuple(sorted(rows))
    canonical_rows = project_rth(raw_rows, chain)
    expected_coordinates = {
        (symbol, timestamp)
        for symbol in chain.symbols
        for timestamp in expected_bar_timestamps(chain.start, chain.end, Timeframe.FIVE_MINUTES)
    }
    actual_coordinates = {row.coordinate for row in canonical_rows}
    missing = expected_coordinates - actual_coordinates
    extra = actual_coordinates - expected_coordinates
    chain_outcome = {
        "schema_version": "program-007-private-chain-validation-v1",
        "chain_identity": chain.identity,
        "page_count": len(pages),
        "raw_row_count": len(raw_rows),
        "canonical_row_count": len(canonical_rows),
        "expected_canonical_row_count": len(expected_coordinates),
        "extended_hours_row_count": len(raw_rows) - len(canonical_rows),
        "missing_coordinate_count": len(missing),
        "extra_coordinate_count": len(extra),
        "incomplete_sessions": sorted({timestamp.date().isoformat() for _, timestamp in missing}),
        "status": "PASS" if not missing and not extra else "FAIL",
    }
    chain_outcome_key = f"{chain_prefix}/validation.json"
    existing_chain_outcome = (
        _load_record(store, chain_outcome_key) if store.exists(chain_outcome_key) else None
    )
    _publish_validation(
        store, chain_outcome_key, chain_outcome, observed_at, existing_chain_outcome
    )
    if missing or extra:
        raise Program007Error(
            "Program 007 canonical RTH completeness failed; the whole session is ineligible"
        )
    return ChainResult(chain, raw_rows, canonical_rows, tuple(pages))


def _require_synthetic_source(page_source: SyntheticPageSource) -> None:
    if type(page_source) is not SyntheticPageSource:
        raise Program007Error("Program 007 execution accepts synthetic responses only")


def _require_synthetic_observed_at(observed_at: datetime) -> None:
    if type(observed_at) is not datetime or observed_at.tzinfo is not UTC:
        raise Program007Error(
            "Program 007 synthetic observation time must be a concrete UTC datetime"
        )


def _next_synthetic_response(
    page_source: SyntheticPageSource, intent: RequestIntent
) -> RawResponse:
    _require_synthetic_source(page_source)
    if type(intent) is not RequestIntent:
        raise Program007Error("Program 007 synthetic request intent is invalid")
    response_index = len(page_source._intents)
    page_source._intents.append(intent)
    page_source._intent_files_present.append(True)
    if response_index >= len(page_source._responses):
        raise Program007Error("Program 007 synthetic response is missing")
    response = page_source._responses[response_index]
    if response is None:
        raise Program007Error("Program 007 synthetic response is ambiguous")
    return response


def _validate_restart_state(store: _EvidenceStore, chains: Sequence[RequestChain]) -> None:
    chain_by_identity = {chain.identity: chain for chain in chains}
    requests: dict[str, set[int]] = {identity: set() for identity in chain_by_identity}
    page_entries: dict[str, dict[int, set[str]]] = {identity: {} for identity in chain_by_identity}
    for key in store.entries:
        if key == "private-manifest.json":
            continue
        parts = key.split("/")
        chain = chain_by_identity.get(parts[1])
        if chain is None:
            raise Program007Error("Program 007 private evidence contains a foreign chain")
        if len(parts) == 3:
            continue
        page_index = int(parts[3].removesuffix(".json"))
        if not 1 <= page_index <= chain.maximum_pages:
            raise Program007Error("Program 007 private evidence contains a foreign page")
        if parts[2] == "requests":
            requests[chain.identity].add(page_index)
        else:
            page_entries[chain.identity].setdefault(page_index, set()).add(parts[4])

    for identity in chain_by_identity:
        request_indexes = requests[identity]
        pages = page_entries[identity]
        if request_indexes and request_indexes != set(range(1, max(request_indexes) + 1)):
            raise Program007Error("Program 007 private evidence contains a foreign request")
        if set(pages) != request_indexes or any(
            not {"body.json", "receipt.json"} <= entries for entries in pages.values()
        ):
            raise Program007Error(
                "Program 007 request outcome is ambiguous; zero-retry policy blocks replay"
            )


def _retain_response(
    store: _EvidenceStore,
    page_prefix: str,
    intent: RequestIntent,
    response: RawResponse,
    observed_at: datetime,
) -> None:
    sha256 = hashlib.sha256(response.body).hexdigest()
    receipt = {
        "schema_version": "program-007-private-raw-page-receipt-v1",
        "chain_id": intent.chain_id,
        "chain_identity": intent.chain_identity,
        "page_index": intent.page_index,
        "request_intent_fingerprint": fingerprint(_intent_record(intent)),
        "response_status": response.status,
        "response_sha256": sha256,
        "response_bytes": len(response.body),
        "received_at_utc": _iso_utc(observed_at),
        "provider": "Alpaca",
        "feed": "sip",
        "timeframe": "5Min",
        "adjustment": "raw",
        "credentials_stored": False,
    }
    store.publish(f"{page_prefix}/body.json", response.body)
    _publish_record(store, f"{page_prefix}/receipt.json", receipt)


def _load_response(store: _EvidenceStore, page_prefix: str, intent: RequestIntent) -> RawResponse:
    receipt = _load_record(store, f"{page_prefix}/receipt.json")
    body = store.read(f"{page_prefix}/body.json")
    sha256 = hashlib.sha256(body).hexdigest()
    if (
        receipt.get("schema_version") != "program-007-private-raw-page-receipt-v1"
        or receipt.get("chain_id") != intent.chain_id
        or receipt.get("chain_identity") != intent.chain_identity
        or receipt.get("page_index") != intent.page_index
        or receipt.get("request_intent_fingerprint") != fingerprint(_intent_record(intent))
        or receipt.get("response_sha256") != sha256
        or receipt.get("response_bytes") != len(body)
        or receipt.get("provider") != "Alpaca"
        or receipt.get("feed") != "sip"
        or receipt.get("timeframe") != "5Min"
        or receipt.get("adjustment") != "raw"
        or receipt.get("credentials_stored") is not False
    ):
        raise Program007Error("Program 007 retained raw response differs")
    return RawResponse(_integer(receipt.get("response_status"), "response status"), body)


def _intent_record(intent: RequestIntent) -> dict[str, Any]:
    return {
        "chain_id": intent.chain_id,
        "chain_identity": intent.chain_identity,
        "page_index": intent.page_index,
        "method": intent.method,
        "request_url": intent.url,
        "incoming_page_token": intent.incoming_page_token,
        "redirects": intent.redirects,
    }


def _validate_intent(record: Mapping[str, Any], intent: RequestIntent) -> None:
    expected = _intent_record(intent)
    if (
        record.get("schema_version") != "program-007-private-request-intent-v1"
        or any(record.get(key) != value for key, value in expected.items())
        or record.get("automatic_transport_retries") != AUTOMATIC_TRANSPORT_RETRIES
        or record.get("credentials_stored") is not False
    ):
        raise Program007Error("Program 007 request intent differs")


def _publish_validation(
    store: _EvidenceStore,
    key: str,
    record: Mapping[str, Any],
    observed_at: datetime,
    existing: Mapping[str, Any] | None,
) -> None:
    if existing is not None:
        comparable = dict(existing)
        comparable.pop("validated_at_utc", None)
        comparable.pop("record_fingerprint", None)
        if comparable != dict(record):
            raise Program007Error("Program 007 immutable validation outcome differs")
        return
    _publish_record(store, key, {**record, "validated_at_utc": _iso_utc(observed_at)})


def _publish_record(
    store: _EvidenceStore,
    key: str,
    record: Mapping[str, Any],
    *,
    allow_identical: bool = False,
) -> None:
    payload = dict(record)
    payload["record_fingerprint"] = fingerprint(payload)
    contents = (canonical_json(payload) + "\n").encode()
    store.publish(key, contents, allow_identical=allow_identical)


def _load_record(store: _EvidenceStore, key: str) -> Mapping[str, Any]:
    raw = store.read(key)
    record = _load_json_object(raw, key)
    unsigned = dict(record)
    stored = unsigned.pop("record_fingerprint", None)
    if raw != (canonical_json(record) + "\n").encode() or stored != fingerprint(unsigned):
        raise Program007Error(f"Program 007 record differs: {key}")
    return record


def _load_json_object(raw: bytes, label: str) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise Program007Error(f"{label} must be exact bytes")

    def reject_constant(value: str) -> None:
        raise Program007Error(f"{label} contains non-finite number: {value}")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise Program007Error(f"{label} contains a duplicate JSON key")
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
        raise Program007Error(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise Program007Error(f"{label} must be a JSON object")
    return value


_STORAGE_PATH_ERROR = (
    "Program 007 private storage is outside its owned root or contains a foreign entry"
)
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


@contextmanager
def _private_root_fd(page_source: SyntheticPageSource) -> Iterator[int]:
    _require_synthetic_source(page_source)
    descriptor: int | None = None
    try:
        workspace_name = page_source._workspace.name
        stored_identity = page_source._root_identity
        if (
            page_source._private_root != Path(workspace_name)
            or type(stored_identity) is not tuple
            or len(stored_identity) != 2
            or any(type(value) is not int for value in stored_identity)
        ):
            raise ValueError
        descriptor = os.open(workspace_name, _DIRECTORY_FLAGS)
        opened = os.fstat(descriptor)
        linked = os.stat(workspace_name, follow_symlinks=False)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or not stat.S_ISDIR(linked.st_mode)
            or (opened.st_dev, opened.st_ino) != stored_identity
            or (linked.st_dev, linked.st_ino) != stored_identity
        ):
            raise ValueError
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        if descriptor is not None:
            os.close(descriptor)
        raise Program007Error(_STORAGE_PATH_ERROR) from error
    try:
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _evidence_store(page_source: SyntheticPageSource) -> Iterator[_EvidenceStore]:
    _require_synthetic_source(page_source)
    lock = page_source._evidence_lock
    if type(lock) is not RLock:
        raise Program007Error(_STORAGE_PATH_ERROR)
    with lock:
        descriptor: int | None = None
        locked = False
        try:
            with _private_root_fd(page_source) as root_fd:
                if os.listdir(root_fd):
                    raise ValueError
                stored_identity = page_source._evidence_identity
                if (
                    type(stored_identity) is not tuple
                    or len(stored_identity) != 2
                    or any(type(value) is not int for value in stored_identity)
                ):
                    raise ValueError
                descriptor = page_source._evidence.fileno()
                if type(descriptor) is not int:
                    raise ValueError
                opened = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_nlink != 0
                    or (opened.st_dev, opened.st_ino) != stored_identity
                ):
                    raise ValueError
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                locked = True
                yield _EvidenceStore(descriptor, _load_evidence(descriptor))
        except Program007Error:
            raise
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise Program007Error(_STORAGE_PATH_ERROR) from error
        finally:
            if locked and descriptor is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)


def _require_evidence_key(key: str) -> None:
    if type(key) is not str:
        raise Program007Error("Program 007 evidence key is invalid")
    if key == "private-manifest.json":
        return
    parts = key.split("/")
    valid_chain = (
        len(parts) >= 3 and parts[0] == "chains" and _HEX_64.fullmatch(parts[1]) is not None
    )
    if valid_chain and len(parts) == 3 and parts[2] == "validation.json":
        return
    if (
        valid_chain
        and len(parts) == 4
        and parts[2] == "requests"
        and re.fullmatch(r"[0-9]{5}\.json", parts[3]) is not None
        and int(parts[3][:5]) > 0
    ):
        return
    if (
        valid_chain
        and len(parts) == 5
        and parts[2] == "pages"
        and re.fullmatch(r"[0-9]{5}", parts[3]) is not None
        and int(parts[3]) > 0
        and parts[4] in {"body.json", "receipt.json", "validation.json"}
    ):
        return
    raise Program007Error("Program 007 evidence key is invalid")


def _load_evidence(descriptor: int) -> dict[str, bytes]:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
    except OSError as error:
        raise Program007Error("Program 007 evidence log cannot be read") from error
    raw = b"".join(chunks)
    if not raw:
        return {}
    if not raw.endswith(b"\n"):
        raise Program007Error("Program 007 evidence log is incomplete")

    entries: dict[str, bytes] = {}
    for line_number, line in enumerate(raw[:-1].split(b"\n"), start=1):
        record = _load_json_object(line, f"evidence log line {line_number}")
        _exact_keys(
            record,
            {
                "schema_version",
                "key",
                "payload_base64",
                "payload_bytes",
                "payload_sha256",
                "entry_fingerprint",
            },
            "evidence log entry",
        )
        unsigned = dict(record)
        stored_fingerprint = unsigned.pop("entry_fingerprint")
        key = record["key"]
        encoded = record["payload_base64"]
        payload_bytes = record["payload_bytes"]
        payload_sha256 = record["payload_sha256"]
        try:
            payload = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (AttributeError, UnicodeEncodeError, binascii.Error) as error:
            raise Program007Error("Program 007 evidence payload is not strict Base64") from error
        if (
            record["schema_version"] != "program-007-private-evidence-log-entry-v1"
            or type(encoded) is not str
            or base64.b64encode(payload).decode("ascii") != encoded
            or type(payload_bytes) is not int
            or payload_bytes != len(payload)
            or type(payload_sha256) is not str
            or _HEX_64.fullmatch(payload_sha256) is None
            or payload_sha256 != hashlib.sha256(payload).hexdigest()
            or type(stored_fingerprint) is not str
            or stored_fingerprint != fingerprint(unsigned)
            or line != canonical_json(record).encode()
        ):
            raise Program007Error("Program 007 evidence log entry differs")
        _require_evidence_key(key)
        if key in entries:
            raise Program007Error("Program 007 evidence key is repeated")
        entries[key] = payload
    return entries


def _append_evidence(descriptor: int, key: str, payload: bytes) -> None:
    _require_evidence_key(key)
    if type(payload) is not bytes:
        raise Program007Error("Program 007 evidence payload must be exact bytes")
    unsigned = {
        "schema_version": "program-007-private-evidence-log-entry-v1",
        "key": key,
        "payload_base64": base64.b64encode(payload).decode("ascii"),
        "payload_bytes": len(payload),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
    }
    record = {**unsigned, "entry_fingerprint": fingerprint(unsigned)}
    remaining = memoryview((canonical_json(record) + "\n").encode())
    try:
        os.lseek(descriptor, 0, os.SEEK_END)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("evidence append made no progress")
            remaining = remaining[written:]
        os.fsync(descriptor)
    except OSError as error:
        raise Program007Error("Program 007 evidence log cannot be appended") from error


def _parse_bar_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise Program007Error("Program 007 bar timestamp must be UTC RFC-3339")
    try:
        timestamp = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise Program007Error("Program 007 bar timestamp is malformed") from error
    if (
        not _is_utc(timestamp)
        or timestamp.second != 0
        or timestamp.microsecond != 0
        or timestamp.minute % 5
    ):
        raise Program007Error("Program 007 bar timestamp is not a five-minute UTC bar open")
    return timestamp.astimezone(UTC)


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise Program007Error("Program 007 timestamp is invalid") from error
    if not _is_utc(parsed):
        raise Program007Error("Program 007 timestamp must be UTC")
    return parsed.astimezone(UTC)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise Program007Error("Program 007 date is invalid") from error


def _is_utc(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() == UTC.utcoffset(value)


def _iso_utc(value: datetime) -> str:
    if not _is_utc(value):
        raise Program007Error("Program 007 timestamp must be UTC")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Program007Error(f"Program 007 {label} must be an object")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise Program007Error(f"Program 007 {label} must be a list")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise Program007Error(f"Program 007 {label} must be a non-empty string")
    return value


def _strings(value: Any, label: str) -> tuple[str, ...]:
    values = _sequence(value, label)
    if any(not isinstance(item, str) or not item for item in values):
        raise Program007Error(f"Program 007 {label} must contain non-empty strings")
    return tuple(values)


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Program007Error(f"Program 007 {label} must be an integer")
    return int(value)


def _positive_integer(value: Any, label: str) -> int:
    result = _integer(value, label)
    if result <= 0:
        raise Program007Error(f"Program 007 {label} must be positive")
    return result


def _positive_decimal(value: Any, label: str) -> Decimal:
    result = _decimal(value, label)
    if result <= 0:
        raise Program007Error(f"Program 007 {label} must be positive")
    return result


def _nonnegative_decimal(value: Any, label: str) -> Decimal:
    result = _decimal(value, label)
    if result < 0:
        raise Program007Error(f"Program 007 {label} must be nonnegative")
    return result


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | Decimal):
        raise Program007Error(f"Program 007 {label} must be numeric")
    result = Decimal(value)
    if not result.is_finite():
        raise Program007Error(f"Program 007 {label} must be finite")
    return result


def _optional_positive_decimal(value: Any, label: str) -> Decimal | None:
    return None if value is None else _positive_decimal(value, label)


def _optional_nonnegative_integer(value: Any, label: str) -> int | None:
    if value is None:
        return None
    result = _integer(value, label)
    if result < 0:
        raise Program007Error(f"Program 007 {label} must be nonnegative")
    return result


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise Program007Error(f"Program 007 {label} schema differs")
