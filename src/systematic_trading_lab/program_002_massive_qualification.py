"""Fail-closed, one-use Massive source qualification for Program 002."""

from __future__ import annotations

import argparse
import bisect
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time as system_time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse
from urllib.request import Request
from zoneinfo import ZoneInfo

from .calendar import expected_bar_timestamps
from .config import non_broker_subprocess_environment
from .domain import Timeframe
from .fingerprints import canonical_json, canonicalize, fingerprint
from .program_002_acquisition import (
    HttpPage,
    Program002AcquisitionError,
    RequestPacer,
    _request,
    _urlopen_page,
)
from .storage import StorageLayout

_NY = ZoneInfo("America/New_York")
_ORIGIN = "https://api.massive.com"
_CREDENTIAL_NAME = "PROGRAM_002_MASSIVE_API_KEY"
_PLAN_PATH = Path("config/research/program-002-replacement-data-source-plan-v1.json")
_PLAN_SHA256 = "01e89da41c3c74080c3a3e5f88c5aa11e5fa5ba6a5fc66ba73b4bfdff3562036"
_PLAN_FINGERPRINT = "4080f02cfd4ad57c2c3e4e535cc73de8743a40fb0d3e52d046e5c592cd06ae8d"
_GATE_PATH = Path("config/research/program-002-massive-pre-transport-gates-v1.json")
_GATE_SHA256 = "b1e8e298bc61d36dd1893f94230fcc11f53fddf2de755c168ed0eac5d909bb63"
_GATE_FINGERPRINT = "f0618bdbb8d6ff384778a49b0888fd5c6958874bd03c9e9c2889e9f0a982134a"
_AUTHORITY_PATH = Path("config/research/program-002-massive-source-qualification-authority-v1.json")
_AUTHORITY_REVIEW_PATH = Path(
    "config/research/program-002-massive-source-qualification-authority-independent-review-v1.json"
)
_IMPLEMENTATION_REVIEW_PATH = Path(
    "config/research/program-002-massive-source-qualification-implementation-independent-review-v1.json"
)
_IMPLEMENTATION_PATHS = (
    "src/systematic_trading_lab/program_002_massive_qualification.py",
    "src/systematic_trading_lab/program_002_acquisition.py",
    "src/systematic_trading_lab/config.py",
    "src/systematic_trading_lab/program_002_credentials.py",
    "src/systematic_trading_lab/cli.py",
    "tests/unit/test_program_002_massive_qualification.py",
    "tests/unit/test_program_002_acquisition.py",
)
_MISSING_DATA_SHA256 = "26e7c84d97c08c7ef4439333aeb444a12a145f360140e93ebc1104118ec96699"
_MISSING_DATA_FINGERPRINT = "291c7bccce40440773b32157e1518abc31fe783e0a0b0763dfd100b55e95bbfe"
_MAX_CHAINS = 630
_MAX_PAGES = 5_000
_MAX_BYTES = 5 * 1024**3
_MAX_PAGE_BYTES = 64 * 1024**2
_ACTION_START = date(2020, 6, 26)
_ACTION_END = date(2026, 7, 31)
_RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
_DOWNSTREAM_AUTHORITY_KEYS = frozenset(
    {
        "full_market_data_acquisition",
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


class MassiveQualificationError(RuntimeError):
    pass


class MassiveCredentialUnavailable(MassiveQualificationError):
    pass


@dataclass(frozen=True)
class MassiveSourcePlan:
    repository: Path
    path: Path
    sha256: str
    plan_fingerprint: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class MassiveRequestChain:
    kind: str
    symbol: str
    endpoint: str
    params: Mapping[str, str]
    session_date: str | None = None
    clock: str | None = None
    expected_timestamps: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in {"aggregate", "trade", "quote", "split", "dividend", "ticker-event"}:
            raise ValueError("Massive request kind is invalid")
        parsed = urlparse(self.endpoint)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "api.massive.com"
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Massive request endpoint differs from the frozen origin")
        object.__setattr__(self, "params", MappingProxyType(dict(sorted(self.params.items()))))

    @property
    def url(self) -> str:
        query = urlencode(tuple(self.params.items()))
        return self.endpoint if not query else f"{self.endpoint}?{query}"

    @property
    def identity(self) -> str:
        return fingerprint(
            {
                "kind": self.kind,
                "symbol": self.symbol,
                "request": self.url,
                "session_date": self.session_date,
                "clock": self.clock,
                "expected_timestamps": self.expected_timestamps,
            }
        )


@dataclass(frozen=True)
class MassiveRawPage:
    request_url: str
    body: bytes
    sha256: str
    request_id: str | int | None
    attempts: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class AcquiredMassiveChain:
    chain: MassiveRequestChain
    pages: tuple[MassiveRawPage, ...]
    records: tuple[Mapping[str, Any], ...]


@dataclass
class QualificationBudget:
    maximum_chains: int = _MAX_CHAINS
    maximum_pages: int = _MAX_PAGES
    maximum_bytes: int = _MAX_BYTES
    request_chains: int = 0
    pages: int = 0
    response_bytes: int = 0
    _chain_ids: set[str] = field(default_factory=set)

    def begin(self, chain: MassiveRequestChain) -> None:
        if chain.identity in self._chain_ids:
            raise MassiveQualificationError("duplicate Massive request chain")
        if self.request_chains >= self.maximum_chains:
            raise MassiveQualificationError("Massive request-chain ceiling exceeded")
        self._chain_ids.add(chain.identity)
        self.request_chains += 1

    def add_page(self, body: bytes, *, truncated: bool = False) -> None:
        self.add_page_size(len(body), truncated=truncated)

    def add_page_size(self, size: int, *, truncated: bool = False) -> None:
        if truncated or size > _MAX_PAGE_BYTES:
            raise MassiveQualificationError("Massive response exceeds the bounded page size")
        if self.pages >= self.maximum_pages:
            raise MassiveQualificationError("Massive 5000-page ceiling exceeded")
        if self.response_bytes + size > self.maximum_bytes:
            raise MassiveQualificationError("Massive 5-GiB response ceiling exceeded")
        self.pages += 1
        self.response_bytes += size


@dataclass(frozen=True)
class TradeAuditContract:
    source_sha256: str
    eligible_conditions: frozenset[int]
    ineligible_conditions: frozenset[int]
    eligible_corrections: frozenset[int] = frozenset({0})
    ineligible_corrections: frozenset[int] = frozenset()
    equal_timestamp_order: tuple[str, ...] = ("sip_timestamp", "sequence_number", "id")

    def __post_init__(self) -> None:
        if (
            not _is_sha256(self.source_sha256)
            or self.eligible_conditions & self.ineligible_conditions
            or not (self.eligible_conditions | self.ineligible_conditions)
            or self.eligible_corrections & self.ineligible_corrections
            or self.equal_timestamp_order != ("sip_timestamp", "sequence_number", "id")
            or not self.eligible_corrections
        ):
            raise ValueError("Massive trade-audit contract is invalid")


@dataclass(frozen=True)
class QualificationAuthority:
    path: Path
    sha256: str
    authority_fingerprint: str
    payload: Mapping[str, Any]
    review_path: Path
    review_sha256: str
    review_fingerprint: str
    review: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "review", MappingProxyType(dict(self.review)))


def load_massive_source_plan(repository: Path) -> MassiveSourcePlan:
    repository = repository.resolve()
    path = repository / _PLAN_PATH
    raw = path.read_bytes()
    payload = _load_unique_json(raw, "Massive replacement-source plan")
    unsigned = dict(payload)
    plan_fingerprint = unsigned.pop("plan_fingerprint", None)
    if (
        hashlib.sha256(raw).hexdigest() != _PLAN_SHA256
        or plan_fingerprint != _PLAN_FINGERPRINT
        or plan_fingerprint != fingerprint(unsigned)
        or payload.get("schema_version") != "program-002-replacement-data-source-plan-v1"
        or payload.get("program_id") != "multi-hour-sector-etf-research-001"
        or any(_mapping(payload.get("authority"), "replacement-source authority").values())
    ):
        raise MassiveQualificationError("Massive replacement-source plan differs")
    return MassiveSourcePlan(repository, path, _PLAN_SHA256, str(plan_fingerprint), payload)


def load_pre_transport_gates(repository: Path) -> Mapping[str, Any]:
    raw = (repository.resolve() / _GATE_PATH).read_bytes()
    payload = _load_unique_json(raw, "Massive pre-transport gates")
    unsigned = dict(payload)
    gate_fingerprint = unsigned.pop("gate_fingerprint", None)
    if (
        hashlib.sha256(raw).hexdigest() != _GATE_SHA256
        or gate_fingerprint != _GATE_FINGERPRINT
        or gate_fingerprint != fingerprint(unsigned)
        or payload.get("schema_version") != "program-002-massive-pre-transport-gates-v1"
        or any(_mapping(payload.get("authority"), "Massive gate authority").values())
    ):
        raise MassiveQualificationError("Massive pre-transport gate artifact differs")
    return payload


def pre_transport_gate_preflight(gates: Mapping[str, Any]) -> None:
    adjustment = _mapping(gates.get("adjustment_semantics"), "adjustment gate")
    eligibility = _mapping(gates.get("aggregate_eligibility_contract"), "eligibility gate")
    licensing = _mapping(gates.get("licensing_and_retention"), "licensing gate")
    if (
        gates.get("status") != "PASS"
        or adjustment.get("verdict") != "pass"
        or adjustment.get("requested_adjusted_flag") is not False
        or eligibility.get("verdict") != "pass"
        or licensing.get("verdict") != "pass"
    ):
        raise MassiveQualificationError(
            "Massive adjustment, trade-condition, and licensing gates have not passed"
        )


def build_massive_request_plan(plan: MassiveSourcePlan) -> tuple[MassiveRequestChain, ...]:
    sample = _mapping(plan.payload.get("source_qualification_design"), "qualification sample")
    symbols = _strings(sample.get("sample_symbols"), "qualification symbols")
    bars = _mapping(sample.get("bar_sessions"), "qualification bar sessions")
    full_sessions = (
        *_strings(bars.get("known_gap_full_sessions"), "known-gap sessions"),
        *_strings(bars.get("fixed_full_controls"), "full control sessions"),
    )
    early_close = str(bars.get("fixed_early_close_control"))
    chains: list[MassiveRequestChain] = []
    for raw_day in (*full_sessions, early_close):
        day = date.fromisoformat(raw_day)
        points = _session_bar_opens(day)
        expected = 42 if raw_day == early_close else 78
        if len(points) != expected:
            raise MassiveQualificationError("Massive aggregate session grid differs")
        for symbol in symbols:
            chains.append(_aggregate_chain(symbol, raw_day, points))

    trade = _mapping(sample.get("raw_trade_audit"), "raw-trade audit")
    for item in _strings(trade.get("symbol_sessions"), "raw-trade sessions"):
        symbol, raw_day = item.split("@", 1)
        chains.append(
            _trade_chain(symbol, raw_day, _session_bar_opens(date.fromisoformat(raw_day)))
        )

    clocks = _strings(sample.get("quote_fill_clocks_new_york"), "quote clocks")
    for raw_day in _strings(sample.get("quote_sessions"), "quote sessions"):
        for raw_clock in clocks:
            for symbol in symbols:
                chains.append(_quote_chain(symbol, raw_day, raw_clock))

    for symbol in symbols:
        chains.extend((_split_chain(symbol), _dividend_chain(symbol), _ticker_event_chain(symbol)))
    result = tuple(chains)
    _validate_request_plan(plan, result)
    return result


def credential_free_request_preflight(
    plan: MassiveSourcePlan, chains: Sequence[MassiveRequestChain] | None = None
) -> Mapping[str, Any]:
    requests = tuple(build_massive_request_plan(plan) if chains is None else chains)
    _validate_request_plan(plan, requests)
    by_kind: dict[str, int] = {}
    for item in requests:
        by_kind[item.kind] = by_kind.get(item.kind, 0) + 1
    return {
        "schema_version": "program-002-massive-credential-free-preflight-v1",
        "program_id": "multi-hour-sector-etf-research-001",
        "provider": "Massive.com",
        "product": "Stocks Business",
        "method": "GET",
        "origin": "api.massive.com",
        "adjusted": False,
        "request_chain_count": len(requests),
        "request_chain_counts": dict(sorted(by_kind.items())),
        "maximum_pages": _MAX_PAGES,
        "maximum_bytes": _MAX_BYTES,
        "maximum_credential_loads": 1,
        "request_plan_fingerprint": fingerprint([item.identity for item in requests]),
        "controlled_or_protected_timestamps": False,
        "credential_loaded": False,
        "requests": [
            {
                "identity": item.identity,
                "kind": item.kind,
                "symbol": item.symbol,
                "session_date": item.session_date,
                "clock": item.clock,
                "url": item.url,
            }
            for item in requests
        ],
    }


def acquire_massive_chain(
    chain: MassiveRequestChain,
    transport: Callable[[str], HttpPage],
    budget: QualificationBudget,
    *,
    pace: Callable[[], None] | None = None,
    retry_wait: Callable[[float], None] = system_time.sleep,
    wall_clock: Callable[[], float] = system_time.time,
) -> AcquiredMassiveChain:
    budget.begin(chain)
    pace = RequestPacer() if pace is None else pace
    url = chain.url
    seen_urls = {url}
    seen_page_hashes: set[str] = set()
    pages: list[MassiveRawPage] = []
    records: list[Mapping[str, Any]] = []
    observed_page: HttpPage | None = None

    def observe(page: HttpPage) -> None:
        nonlocal observed_page
        observed_page = page
        try:
            budget.add_page(page.body, truncated=page.captured_body_truncated)
        except MassiveQualificationError as error:
            error.observed_response = {  # type: ignore[attr-defined]
                "request_url": url,
                "status": page.status,
                "captured_body_truncated": page.captured_body_truncated,
            }
            raise

    try:
        while True:
            try:
                page = _request(
                    url,
                    transport,
                    pace,
                    lambda status: status in _RETRYABLE_STATUSES,
                    retry_wait,
                    wall_clock,
                    5,
                    observe,
                )
            except Program002AcquisitionError as cause:
                error = MassiveQualificationError(f"Massive transport failed: {cause}")
                error.http_attempts = getattr(cause, "http_attempts", ())  # type: ignore[attr-defined]
                raise error from cause
            page_sha256 = hashlib.sha256(page.body).hexdigest()
            pages.append(MassiveRawPage(url, page.body, page_sha256, None, page.attempts))
            if page_sha256 in seen_page_hashes:
                raise MassiveQualificationError("duplicate Massive response page")
            seen_page_hashes.add(page_sha256)
            payload, page_records = _parse_provider_page(page.body, chain.kind)
            request_id = payload.get("request_id")
            if request_id is not None and not isinstance(request_id, str | int):
                raise MassiveQualificationError("Massive response request_id is invalid")
            pages[-1] = MassiveRawPage(url, page.body, page_sha256, request_id, page.attempts)
            records.extend(page_records)
            next_url = payload.get("next_url")
            if next_url is None:
                break
            if not isinstance(next_url, str) or not next_url:
                raise MassiveQualificationError("Massive next_url is malformed")
            _validate_next_url(chain, next_url)
            if next_url in seen_urls:
                raise MassiveQualificationError("Massive next_url repeated")
            seen_urls.add(next_url)
            url = next_url
        acquired = AcquiredMassiveChain(chain, tuple(pages), tuple(records))
        _validate_chain_structure(acquired)
        return acquired
    except MassiveQualificationError as error:
        if observed_page is not None:
            observed_hash = hashlib.sha256(observed_page.body).hexdigest()
            if all(page.sha256 != observed_hash for page in pages):
                pages.append(
                    MassiveRawPage(
                        url, observed_page.body, observed_hash, None, observed_page.attempts
                    )
                )
        error.partial_pages = tuple(pages)  # type: ignore[attr-defined]
        error.failed_chain = chain  # type: ignore[attr-defined]
        raise


def store_massive_chain(
    layout: StorageLayout,
    attempt_id: str,
    acquired: AcquiredMassiveChain,
) -> tuple[str, bool]:
    _attempt_id(attempt_id)
    _validate_chain_structure(acquired)
    for page in acquired.pages:
        _response_attempt_sizes(page)
    identity = _stored_chain_identity(attempt_id, acquired.chain)
    manifest: dict[str, Any] = {
        "schema_version": "program-002-massive-qualification-chain-v1",
        "attempt_id": attempt_id,
        "identity": identity,
        "chain": _chain_manifest(acquired.chain),
        "pages": [
            {
                "file": f"page-{index:05d}.json",
                "request_url": page.request_url,
                "sha256": page.sha256,
                "request_id": page.request_id,
                "attempts": list(page.attempts),
            }
            for index, page in enumerate(acquired.pages, start=1)
        ],
        "record_count": len(acquired.records),
        "record_fingerprint": fingerprint(acquired.records),
    }
    manifest["artifact_fingerprint"] = fingerprint(manifest)
    files: dict[str, str | bytes] = {"manifest.json": canonical_json(manifest) + "\n"}
    files.update(
        {f"page-{index:05d}.json": page.body for index, page in enumerate(acquired.pages, start=1)}
    )
    created = layout.publish(identity, files)
    if not created:
        stored = load_massive_chain(layout, attempt_id, acquired.chain)
        if stored != acquired:
            raise MassiveQualificationError("stored Massive chain conflicts")
    return identity, created


def load_massive_chain(
    layout: StorageLayout, attempt_id: str, chain: MassiveRequestChain
) -> AcquiredMassiveChain:
    identity = _stored_chain_identity(attempt_id, chain)
    root = layout.dataset(identity)
    try:
        raw_manifest = (root / "manifest.json").read_bytes()
        manifest = _load_unique_json(raw_manifest, "stored Massive chain manifest")
    except OSError as error:
        raise MassiveQualificationError("stored Massive chain is absent") from error
    unsigned = dict(manifest)
    artifact_fingerprint = unsigned.pop("artifact_fingerprint", None)
    pages_value = manifest.get("pages")
    if (
        raw_manifest != (canonical_json(manifest) + "\n").encode()
        or artifact_fingerprint != fingerprint(unsigned)
        or manifest.get("schema_version") != "program-002-massive-qualification-chain-v1"
        or manifest.get("attempt_id") != attempt_id
        or manifest.get("identity") != identity
        or manifest.get("chain") != _chain_manifest(chain)
        or not isinstance(pages_value, list)
        or not pages_value
    ):
        raise MassiveQualificationError("stored Massive chain manifest differs")
    pages: list[MassiveRawPage] = []
    records: list[Mapping[str, Any]] = []
    request_urls: set[str] = set()
    for index, item in enumerate(pages_value, start=1):
        page = _mapping(item, "stored Massive page")
        filename = f"page-{index:05d}.json"
        if page.get("file") != filename:
            raise MassiveQualificationError("stored Massive page order differs")
        try:
            body = (root / filename).read_bytes()
        except OSError as error:
            raise MassiveQualificationError("stored Massive page is absent") from error
        if hashlib.sha256(body).hexdigest() != page.get("sha256"):
            raise MassiveQualificationError("stored Massive page hash differs")
        _, page_records = _parse_provider_page(body, chain.kind)
        records.extend(page_records)
        request_url = page.get("request_url")
        request_id = page.get("request_id")
        if (
            not isinstance(request_url, str)
            or request_url in request_urls
            or (index == 1 and request_url != chain.url)
            or (index > 1 and request_url == chain.url)
            or (request_id is not None and not isinstance(request_id, str | int))
        ):
            raise MassiveQualificationError("stored Massive page request differs")
        if index > 1:
            _validate_next_url(chain, request_url)
        request_urls.add(request_url)
        attempts = page.get("attempts")
        if not isinstance(attempts, list) or any(
            not isinstance(value, Mapping) for value in attempts
        ):
            raise MassiveQualificationError("stored Massive request attempts differ")
        stored_page = MassiveRawPage(
            request_url,
            body,
            str(page.get("sha256")),
            request_id,
            tuple(dict(value) for value in attempts),
        )
        _response_attempt_sizes(stored_page)
        pages.append(stored_page)
    acquired = AcquiredMassiveChain(chain, tuple(pages), tuple(records))
    if manifest.get("record_count") != len(records) or manifest.get(
        "record_fingerprint"
    ) != fingerprint(records):
        raise MassiveQualificationError("stored Massive record evidence differs")
    _validate_chain_structure(acquired)
    return acquired


def acquire_or_load_massive_chain(
    layout: StorageLayout,
    attempt_id: str,
    chain: MassiveRequestChain,
    transport: Callable[[str], HttpPage],
    budget: QualificationBudget,
    *,
    pace: Callable[[], None] | None = None,
    retry_wait: Callable[[float], None] = system_time.sleep,
    wall_clock: Callable[[], float] = system_time.time,
) -> tuple[AcquiredMassiveChain, bool]:
    root = layout.dataset(_stored_chain_identity(attempt_id, chain))
    if root.exists():
        acquired = load_massive_chain(layout, attempt_id, chain)
        _replay_budget(budget, acquired)
        return acquired, False
    acquired = acquire_massive_chain(
        chain,
        transport,
        budget,
        pace=pace,
        retry_wait=retry_wait,
        wall_clock=wall_clock,
    )
    try:
        store_massive_chain(layout, attempt_id, acquired)
    except MassiveQualificationError as error:
        error.partial_pages = acquired.pages  # type: ignore[attr-defined]
        error.failed_chain = chain  # type: ignore[attr-defined]
        raise
    return acquired, True


def trade_audit_contract_from_authority(
    authority: QualificationAuthority,
) -> TradeAuditContract:
    raw = _mapping(authority.payload.get("trade_audit_contract"), "trade-audit contract")
    if (
        raw.get("duplicate_policy") != "reject-duplicate-exchange-trf-id"
        or raw.get("cancellation_policy") != "eligible-correction-codes-only"
        or raw.get("late_report_policy") != "condition-code-contract"
        or raw.get("bucket_policy") != "xnys-regular-session-five-minute-utc-bar-open"
        or raw.get("equality_policy") != "exact-decimal-ohlcv"
    ):
        raise MassiveQualificationError("Massive trade-audit contract is incomplete")
    try:
        return TradeAuditContract(
            source_sha256=str(raw.get("source_sha256", "")),
            eligible_conditions=frozenset(
                _integers(raw.get("eligible_conditions"), "eligible trade conditions")
            ),
            ineligible_conditions=frozenset(
                _integers(raw.get("ineligible_conditions"), "ineligible trade conditions")
            ),
            eligible_corrections=frozenset(
                _integers(raw.get("eligible_corrections"), "eligible trade corrections")
            ),
            ineligible_corrections=frozenset(
                _integers(raw.get("ineligible_corrections"), "ineligible trade corrections")
            ),
            equal_timestamp_order=_strings(
                raw.get("equal_timestamp_order"), "equal-timestamp trade order"
            ),
        )
    except ValueError as error:
        raise MassiveQualificationError("Massive trade-audit contract is incomplete") from error


def validate_aggregate_chain(
    acquired: AcquiredMassiveChain,
) -> tuple[Mapping[str, Any], ...]:
    chain = acquired.chain
    if chain.kind != "aggregate":
        raise ValueError("aggregate validation requires an aggregate chain")
    for page in acquired.pages:
        payload, _ = _parse_provider_page(page.body, chain.kind)
        if payload.get("ticker") != chain.symbol or payload.get("adjusted") is not False:
            raise MassiveQualificationError("Massive aggregate response identity differs")
    expected = set(chain.expected_timestamps)
    output: list[Mapping[str, Any]] = []
    seen: set[int] = set()
    for raw in acquired.records:
        timestamp = _integer(raw.get("t"), "aggregate timestamp")
        if timestamp not in expected or timestamp in seen:
            raise MassiveQualificationError("Massive aggregate timestamp grid differs")
        seen.add(timestamp)
        open_price = _positive_decimal(raw.get("o"), "aggregate open")
        high = _positive_decimal(raw.get("h"), "aggregate high")
        low = _positive_decimal(raw.get("l"), "aggregate low")
        close = _positive_decimal(raw.get("c"), "aggregate close")
        volume = _nonnegative_integer(raw.get("v"), "aggregate volume")
        if high < max(open_price, close) or low > min(open_price, close) or high < low:
            raise MassiveQualificationError("Massive aggregate OHLC is invalid")
        output.append(
            {
                "symbol": chain.symbol,
                "timestamp_ms": timestamp,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )
    if seen != expected:
        raise MassiveQualificationError("Massive aggregate sample is incomplete")
    return tuple(sorted(output, key=lambda item: int(item["timestamp_ms"])))


def eligible_quote_observation_count(acquired: AcquiredMassiveChain) -> int:
    chain = acquired.chain
    if chain.kind != "quote" or chain.session_date is None or chain.clock is None:
        raise ValueError("quote sampling requires a quote-window chain")
    point = datetime.combine(
        date.fromisoformat(chain.session_date), time.fromisoformat(chain.clock), _NY
    ).astimezone(UTC)
    timestamps: list[int] = []
    eligible: list[bool] = []
    lower = _integer(chain.params.get("timestamp.gte"), "quote request lower bound")
    upper = _integer(chain.params.get("timestamp.lt"), "quote request upper bound")
    for raw in sorted(
        acquired.records, key=lambda item: _integer(item.get("sip_timestamp"), "quote timestamp")
    ):
        timestamp = _integer(raw.get("sip_timestamp"), "quote timestamp")
        if not lower <= timestamp < upper:
            raise MassiveQualificationError("Massive quote timestamp is outside scope")
        if timestamps and timestamp == timestamps[-1]:
            raise MassiveQualificationError("Massive quote SIP timestamp is duplicated")
        timestamps.append(timestamp)
        bid = _decimal(raw.get("bid_price"), "quote bid")
        ask = _decimal(raw.get("ask_price"), "quote ask")
        bid_size = _decimal(raw.get("bid_size"), "quote bid size")
        ask_size = _decimal(raw.get("ask_size"), "quote ask size")
        _integer(raw.get("bid_exchange"), "quote bid exchange")
        _integer(raw.get("ask_exchange"), "quote ask exchange")
        _integer(raw.get("participant_timestamp"), "quote participant timestamp")
        eligible.append(bid > 0 and ask >= bid and bid_size > 0 and ask_size > 0)
    count = 0
    first = _unix_ns(point - timedelta(seconds=30))
    for offset in range(60):
        instant = first + offset * 1_000_000_000
        index = bisect.bisect_left(timestamps, instant) - 1
        if index >= 0 and instant - timestamps[index] <= 5_000_000_000 and eligible[index]:
            count += 1
    return count


def audit_trade_chain(
    acquired: AcquiredMassiveChain,
    aggregate_records: Sequence[Mapping[str, Any]],
    contract: TradeAuditContract,
) -> Mapping[str, Any]:
    chain = acquired.chain
    if chain.kind != "trade" or chain.session_date is None:
        raise ValueError("trade audit requires a trade chain")
    points = _session_bar_opens(date.fromisoformat(chain.session_date))
    opens_ms = {_unix_ms(point) for point in points}
    by_bucket: dict[int, list[tuple[int, int, str, Decimal, Decimal]]] = {}
    known_conditions = contract.eligible_conditions | contract.ineligible_conditions
    known_corrections = contract.eligible_corrections | contract.ineligible_corrections
    lower = _integer(chain.params.get("timestamp.gte"), "trade request lower bound")
    upper = _integer(chain.params.get("timestamp.lt"), "trade request upper bound")
    trade_ids: set[tuple[int, int | None, str]] = set()
    for raw in acquired.records:
        timestamp = _integer(raw.get("sip_timestamp"), "trade SIP timestamp")
        if not lower <= timestamp < upper:
            raise MassiveQualificationError("Massive trade timestamp is outside scope")
        conditions_raw = raw.get("conditions", [])
        if not isinstance(conditions_raw, list) or any(
            not isinstance(value, int) for value in conditions_raw
        ):
            raise MassiveQualificationError("Massive trade conditions are malformed")
        conditions = frozenset(conditions_raw)
        if not conditions <= known_conditions:
            raise MassiveQualificationError("Massive trade condition is unbound")
        correction = _integer(raw.get("correction", 0), "trade correction")
        identifier = str(raw.get("id", ""))
        exchange = _integer(raw.get("exchange"), "trade exchange")
        trf_value = raw.get("trf_id")
        trf_id = None if trf_value is None else _integer(trf_value, "trade TRF")
        _integer(raw.get("participant_timestamp"), "trade participant timestamp")
        trade_identity = (exchange, trf_id, identifier)
        if not identifier:
            raise MassiveQualificationError("Massive trade id is absent")
        if trade_identity in trade_ids:
            raise MassiveQualificationError("Massive trade id is duplicated")
        trade_ids.add(trade_identity)
        if correction not in known_corrections:
            raise MassiveQualificationError("Massive trade correction is unbound")
        if (
            correction not in contract.eligible_corrections
            or conditions & contract.ineligible_conditions
        ):
            continue
        bucket = timestamp // 1_000_000
        bucket -= bucket % (5 * 60 * 1000)
        if bucket not in opens_ms:
            raise MassiveQualificationError("Massive trade timestamp is outside the session grid")
        price = _positive_decimal(raw.get("price"), "trade price")
        size_value = raw.get("decimal_size", raw.get("size"))
        size = _positive_decimal(size_value, "trade size")
        sequence = _integer(raw.get("sequence_number"), "trade sequence")
        by_bucket.setdefault(bucket, []).append((timestamp, sequence, identifier, price, size))
    expected = {int(item["timestamp_ms"]): item for item in aggregate_records}
    if set(by_bucket) != set(expected):
        raise MassiveQualificationError("Massive raw-trade audit bucket set differs")
    audit: list[Mapping[str, Any]] = []
    for bucket, values in sorted(by_bucket.items()):
        values.sort(key=lambda item: item[:3])
        volume = sum((item[4] for item in values), Decimal(0))
        if volume != volume.to_integral_value():
            raise MassiveQualificationError("Massive audited trade volume is fractional")
        derived = {
            "timestamp_ms": bucket,
            "open": values[0][3],
            "high": max(item[3] for item in values),
            "low": min(item[3] for item in values),
            "close": values[-1][3],
            "volume": int(volume),
        }
        provider = expected.get(bucket)
        if provider is None or any(provider.get(key) != value for key, value in derived.items()):
            raise MassiveQualificationError("Massive raw-trade audit differs from its aggregate")
        audit.append(derived)
    return {
        "symbol": chain.symbol,
        "session_date": chain.session_date,
        "eligible_bucket_count": len(audit),
        "audit_fingerprint": fingerprint(audit),
        "matches_provider_aggregates": True,
        "canonical_admission_allowed": False,
    }


def validate_corporate_action_chain(acquired: AcquiredMassiveChain) -> Mapping[str, Any]:
    chain = acquired.chain
    if chain.kind not in {"split", "dividend", "ticker-event"}:
        raise ValueError("corporate-action validation requires a reference chain")
    identifiers: set[str] = set()
    ticker_events: set[str] = set()
    for raw in acquired.records:
        if chain.kind == "ticker-event":
            event_type = raw.get("type")
            event_date = raw.get("date")
            change = _mapping(raw.get("ticker_change"), "Massive ticker change")
            event_ticker = change.get("ticker")
            try:
                parsed_event_date = (
                    date.fromisoformat(event_date) if isinstance(event_date, str) else None
                )
            except ValueError as error:
                raise MassiveQualificationError("Massive ticker event is malformed") from error
            if (
                event_type != "ticker_change"
                or parsed_event_date is None
                or not _ACTION_START <= parsed_event_date <= _ACTION_END
                or not isinstance(event_ticker, str)
                or not event_ticker
            ):
                raise MassiveQualificationError("Massive ticker event is malformed")
            ticker_events.add(event_ticker)
            identity = fingerprint(raw)
        else:
            if raw.get("ticker") != chain.symbol:
                raise MassiveQualificationError("Massive corporate-action ticker differs")
            field_name = "execution_date" if chain.kind == "split" else "ex_dividend_date"
            raw_date = raw.get(field_name)
            identifier = raw.get("id")
            factor = _positive_decimal(raw.get("historical_adjustment_factor"), "action factor")
            if chain.kind == "split":
                adjustment_type = raw.get("adjustment_type")
                _positive_decimal(raw.get("split_from"), "split denominator")
                _positive_decimal(raw.get("split_to"), "split numerator")
                if adjustment_type not in {
                    "forward_split",
                    "reverse_split",
                    "stock_dividend",
                }:
                    raise MassiveQualificationError("Massive split type is malformed")
            else:
                _positive_decimal(raw.get("cash_amount"), "dividend cash amount")
                currency = raw.get("currency")
                if not isinstance(currency, str) or not currency:
                    raise MassiveQualificationError("Massive dividend currency is malformed")
            if (
                not isinstance(raw_date, str)
                or not isinstance(identifier, str)
                or not identifier
                or factor <= 0
                or not _ACTION_START <= date.fromisoformat(raw_date) <= _ACTION_END
            ):
                raise MassiveQualificationError("Massive corporate action is outside scope")
            identity = identifier
        if identity in identifiers:
            raise MassiveQualificationError("Massive corporate action is duplicated")
        identifiers.add(identity)
    if ticker_events and chain.symbol not in ticker_events:
        raise MassiveQualificationError("Massive ticker continuity differs")
    return {
        "kind": chain.kind,
        "symbol": chain.symbol,
        "record_count": len(acquired.records),
        "record_fingerprint": fingerprint(acquired.records),
    }


def require_exact_adjustment_proof(proof: Mapping[str, Any]) -> None:
    required = {
        "split_price",
        "split_volume",
        "cash_dividends",
        "stock_dividends",
        "spin_offs",
        "historical_revisions",
        "point_in_time",
        "exact_program_002_match",
    }
    if (
        proof.get("adjusted_request") is not False
        or not _is_sha256(proof.get("source_sha256"))
        or any(proof.get(key) is not True for key in required)
    ):
        raise MassiveQualificationError("Massive adjustment contract is incomplete")


def assess_massive_source_qualification(
    plan: MassiveSourcePlan,
    acquired_chains: Sequence[AcquiredMassiveChain],
    *,
    adjustment_proof: Mapping[str, Any],
    trade_contract: TradeAuditContract,
) -> Mapping[str, Any]:
    require_exact_adjustment_proof(adjustment_proof)
    expected = build_massive_request_plan(plan)
    acquired = {item.chain.identity: item for item in acquired_chains}
    if len(acquired) != len(acquired_chains) or set(acquired) != {
        item.identity for item in expected
    }:
        raise MassiveQualificationError("Massive qualification chain set differs")
    aggregates: dict[tuple[str, str], tuple[Mapping[str, Any], ...]] = {}
    aggregate_rows: list[Mapping[str, Any]] = []
    quote_windows: list[Mapping[str, Any]] = []
    actions: list[Mapping[str, Any]] = []
    for chain in expected:
        item = acquired[chain.identity]
        _validate_chain_structure(item)
        if chain.kind == "aggregate":
            rows = validate_aggregate_chain(item)
            aggregates[(chain.symbol, str(chain.session_date))] = rows
            aggregate_rows.extend(rows)
        elif chain.kind == "quote":
            count = eligible_quote_observation_count(item)
            if count < 57:
                raise MassiveQualificationError(
                    "Massive quote window has fewer than 57 observations"
                )
            quote_windows.append(
                {
                    "symbol": chain.symbol,
                    "session_date": chain.session_date,
                    "clock": chain.clock,
                    "eligible_observations": count,
                    "required_observations": 57,
                }
            )
        elif chain.kind in {"split", "dividend", "ticker-event"}:
            actions.append(validate_corporate_action_chain(item))
    trade_audits = [
        audit_trade_chain(
            acquired[chain.identity],
            aggregates[(chain.symbol, str(chain.session_date))],
            trade_contract,
        )
        for chain in expected
        if chain.kind == "trade"
    ]
    if (
        len(aggregate_rows) != 8_658
        or len(quote_windows) != 468
        or len(trade_audits) != 6
        or len(actions) != 39
        or any(item["eligible_bucket_count"] == 0 for item in trade_audits)
    ):
        raise MassiveQualificationError("Massive qualification counts differ")
    mdy_coordinates = _mapping(
        plan.payload.get("known_mdy_gap_cross_check"), "known MDY cross-check"
    ).get("coordinates")
    if not isinstance(mdy_coordinates, list):
        raise MassiveQualificationError("Massive MDY coordinates differ")
    aggregate_coordinates = {
        f"{row['symbol']}@{_iso_ms(int(row['timestamp_ms']))}" for row in aggregate_rows
    }
    mdy_results = {str(value): str(value) in aggregate_coordinates for value in mdy_coordinates}
    if len(mdy_results) != 9 or not all(mdy_results.values()):
        raise MassiveQualificationError("Massive known MDY coordinate is absent")
    raw_hashes = {
        chain.identity: [page.sha256 for page in acquired[chain.identity].pages]
        for chain in expected
    }
    receipt: dict[str, Any] = {
        "schema_version": "program-002-massive-source-qualification-receipt-v1",
        "provider": "Massive.com",
        "product": "Stocks Business",
        "plan_sha256": plan.sha256,
        "request_plan_fingerprint": fingerprint([item.identity for item in expected]),
        "request_chains": len(expected),
        "http_pages": sum(len(item.pages) for item in acquired_chains),
        "response_bytes": sum(len(page.body) for item in acquired_chains for page in item.pages),
        "aggregate_rows": len(aggregate_rows),
        "aggregate_fingerprint": fingerprint(aggregate_rows),
        "known_mdy_coordinates": mdy_results,
        "raw_trade_audits": trade_audits,
        "quote_windows": quote_windows,
        "quote_grid_observations": 28_080,
        "eligible_quote_observations": sum(
            int(item["eligible_observations"]) for item in quote_windows
        ),
        "corporate_action_chains": actions,
        "adjustment_proof_sha256": adjustment_proof["source_sha256"],
        "adjustment_outcome": "exact-contract-verified",
        "raw_page_sha256_values": raw_hashes,
        "source_qualification": "PASS",
        "zero_strategy_returns_generated": True,
        "controlled_or_protected_state_touched": False,
        "authority": _terminal_authority(),
    }
    receipt["receipt_fingerprint"] = fingerprint(receipt)
    return receipt


class MassiveHttpClient:
    def __init__(
        self,
        api_key: str,
        chains: Sequence[MassiveRequestChain],
        transport: Callable[[Request], HttpPage] = _urlopen_page,
    ) -> None:
        if not api_key:
            raise ValueError("Massive qualification credential is required")
        self._api_key = api_key
        self._chains = {item.identity: item for item in chains}
        self._transport = transport

    def get(self, chain: MassiveRequestChain, url: str) -> HttpPage:
        if chain.identity not in self._chains or self._chains[chain.identity] != chain:
            raise MassiveQualificationError("Massive request chain is not authority-bound")
        if url != chain.url:
            _validate_next_url(chain, url)
        request = Request(
            url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            method="GET",
        )
        return self._transport(request)


def load_qualification_authority(
    repository: Path,
    plan: MassiveSourcePlan,
    gates: Mapping[str, Any],
    chains: Sequence[MassiveRequestChain],
) -> QualificationAuthority:
    pre_transport_gate_preflight(gates)
    authority_path = repository.resolve() / _AUTHORITY_PATH
    review_path = repository.resolve() / _AUTHORITY_REVIEW_PATH
    authority_raw = authority_path.read_bytes()
    review_raw = review_path.read_bytes()
    authority = _load_unique_json(authority_raw, "Massive qualification authority")
    review = _load_unique_json(review_raw, "Massive qualification authority review")
    authority_unsigned = dict(authority)
    authority_fingerprint = authority_unsigned.pop("authority_fingerprint", None)
    review_unsigned = dict(review)
    review_fingerprint = review_unsigned.pop("review_fingerprint", None)
    authority_sha256 = hashlib.sha256(authority_raw).hexdigest()
    review_sha256 = hashlib.sha256(review_raw).hexdigest()
    controls = _mapping(authority.get("authority"), "Massive qualification authority controls")
    limits = _mapping(authority.get("limits"), "Massive qualification authority limits")
    bindings = _mapping(authority.get("bindings"), "Massive qualification authority bindings")
    implementation = _mapping(
        bindings.get("implementation"), "Massive qualification implementation binding"
    )
    implementation_review_binding = _mapping(
        bindings.get("implementation_review"), "Massive implementation review binding"
    )
    implementation_review_path = repository.resolve() / _IMPLEMENTATION_REVIEW_PATH
    implementation_review_raw = implementation_review_path.read_bytes()
    implementation_review = _load_unique_json(
        implementation_review_raw, "Massive qualification implementation review"
    )
    implementation_review_unsigned = dict(implementation_review)
    implementation_review_fingerprint = implementation_review_unsigned.pop(
        "review_fingerprint", None
    )
    if (
        authority_fingerprint != fingerprint(authority_unsigned)
        or review_fingerprint != fingerprint(review_unsigned)
        or authority.get("schema_version")
        != "program-002-massive-source-qualification-authority-v1"
        or authority.get("program_id") != "multi-hour-sector-etf-research-001"
        or authority.get("provider") != "Massive.com"
        or authority.get("product") != "Stocks Business"
        or controls
        != {
            "source_qualification": True,
            **{key: False for key in sorted(_DOWNSTREAM_AUTHORITY_KEYS)},
        }
        or not isinstance(authority.get("attempt_id"), str)
        or bindings.get("replacement_source_plan_sha256") != plan.sha256
        or bindings.get("replacement_source_plan_fingerprint") != plan.plan_fingerprint
        or bindings.get("pre_transport_gate_sha256") != _GATE_SHA256
        or bindings.get("pre_transport_gate_fingerprint") != _GATE_FINGERPRINT
        or bindings.get("missing_data_disposition_sha256") != _MISSING_DATA_SHA256
        or bindings.get("missing_data_disposition_fingerprint") != _MISSING_DATA_FINGERPRINT
        or implementation_review_binding.get("path") != _IMPLEMENTATION_REVIEW_PATH.as_posix()
        or implementation_review_binding.get("sha256")
        != hashlib.sha256(implementation_review_raw).hexdigest()
        or implementation_review_binding.get("fingerprint") != implementation_review_fingerprint
        or implementation_review_fingerprint != fingerprint(implementation_review_unsigned)
        or implementation_review.get("schema_version")
        != "program-002-massive-source-qualification-implementation-independent-review-v1"
        or implementation_review.get("status") != "passed-before-source-authority"
        or implementation_review.get("verdict") != "pass"
        or implementation_review.get("findings") != []
        or implementation_review.get("reviewed_implementation") != implementation
        or any(
            _mapping(
                implementation_review.get("authority"),
                "Massive implementation review authority",
            ).values()
        )
        or authority.get("request_plan_fingerprint")
        != fingerprint([item.identity for item in chains])
        or limits
        != {
            "maximum_logical_request_chains": _MAX_CHAINS,
            "maximum_http_pages": _MAX_PAGES,
            "maximum_response_bytes": _MAX_BYTES,
            "maximum_credential_loads": 1,
            "maximum_qualification_attempts": 1,
        }
        or not _is_sha256(authority.get("credential_identity_hash"))
        or review.get("schema_version")
        != "program-002-massive-source-qualification-authority-independent-review-v1"
        or review.get("verdict") != "pass"
        or review.get("findings") != []
        or review.get("reviewed_authority_sha256") != authority_sha256
        or review.get("reviewed_authority_fingerprint") != authority_fingerprint
    ):
        raise MassiveQualificationError("Massive qualification authority differs")
    result = QualificationAuthority(
        authority_path,
        authority_sha256,
        str(authority_fingerprint),
        authority,
        review_path,
        review_sha256,
        str(review_fingerprint),
        review,
    )
    _attempt_id(str(authority["attempt_id"]))
    require_exact_adjustment_proof(
        _mapping(authority.get("adjustment_proof"), "Massive adjustment proof")
    )
    trade_audit_contract_from_authority(result)
    _validate_implementation_identity(repository.resolve(), implementation)
    _repository_qualification_preflight(repository.resolve(), implementation)
    return result


def _validate_implementation_identity(repository: Path, implementation: Mapping[str, Any]) -> None:
    files = implementation.get("files")
    if (
        not _is_commit(implementation.get("source_commit"))
        or not isinstance(files, list)
        or [item.get("path") if isinstance(item, Mapping) else None for item in files]
        != list(_IMPLEMENTATION_PATHS)
        or any(
            not isinstance(item, Mapping)
            or set(item) != {"path", "sha256"}
            or not _is_sha256(item.get("sha256"))
            or hashlib.sha256((repository / str(item.get("path"))).read_bytes()).hexdigest()
            != item.get("sha256")
            for item in files
        )
    ):
        raise MassiveQualificationError("Massive qualification implementation identity differs")


def _repository_qualification_preflight(
    repository: Path, implementation: Mapping[str, Any]
) -> None:
    source_commit = str(implementation["source_commit"])
    environment = non_broker_subprocess_environment()
    environment.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    command = (
        "git",
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-C",
        str(repository),
    )
    try:
        head = subprocess.run(
            (*command, "rev-parse", "HEAD"),
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout.strip()
        main_commit = subprocess.run(
            (*command, "rev-parse", "refs/heads/main"),
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout.strip()
        origin_main = subprocess.run(
            (*command, "rev-parse", "refs/remotes/origin/main"),
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout.strip()
        dirty = subprocess.run(
            (*command, "status", "--porcelain", "--untracked-files=all"),
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout
        ancestry = subprocess.run(
            (*command, "merge-base", "--is-ancestor", source_commit, head),
            check=False,
            capture_output=True,
            env=environment,
        ).returncode
        changed = subprocess.run(
            (*command, "diff", "--name-only", source_commit, head, "--", *_IMPLEMENTATION_PATHS),
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise MassiveQualificationError(
            "Massive qualification repository identity is unavailable"
        ) from error
    if dirty or head != main_commit or head != origin_main:
        raise MassiveQualificationError("Massive qualification requires clean synchronized main")
    if ancestry != 0 or changed:
        raise MassiveQualificationError("Massive reviewed implementation lineage differs")


class OneUseAttempt:
    def __init__(self, layout: StorageLayout, authority: QualificationAuthority) -> None:
        self._root = layout.reports / "program-002" / "massive-qualification"
        self._authority = authority
        self._attempt_id = _attempt_id(str(authority.payload.get("attempt_id", "")))
        self._lock_handle: Any = None

    @property
    def attempt_id(self) -> str:
        return self._attempt_id

    @property
    def consumed(self) -> bool:
        path = self._root / "consumed.json"
        if not path.exists():
            return False
        self._validate_consumption(_load_exact_record(path, "Massive qualification consumption"))
        return True

    @property
    def credential_loaded(self) -> bool:
        path = self._root / "credential-load.json"
        if not path.exists():
            return False
        stored = _load_exact_record(path, "Massive credential load")
        if stored != {
            "schema_version": "program-002-massive-credential-load-v1",
            "attempt_id": self._attempt_id,
            "maximum_loads": 1,
            "fingerprint": stored.get("fingerprint"),
        }:
            raise MassiveQualificationError("Massive credential load differs")
        return True

    def __enter__(self) -> OneUseAttempt:
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock_handle = (self._root / "attempt.lock").open("a+")
        try:
            fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self._lock_handle.close()
            raise MassiveQualificationError(
                "Massive qualification attempt is already active"
            ) from error
        self.reserve()
        return self

    def __exit__(self, *args: object) -> None:
        assert self._lock_handle is not None
        fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_UN)
        self._lock_handle.close()

    def reserve(self) -> None:
        if (self._root / "outcome.json").exists():
            raise MassiveQualificationError("Massive one-use authority is terminal")
        record = {
            "schema_version": "program-002-massive-qualification-attempt-claim-v1",
            "attempt_id": self._attempt_id,
            "authority_sha256": self._authority.sha256,
            "disposition": "reserved-one-use",
        }
        _publish_exact(self._root / "claim.json", record, allow_identical=True)

    def mark_credential_load(self) -> None:
        record = {
            "schema_version": "program-002-massive-credential-load-v1",
            "attempt_id": self._attempt_id,
            "maximum_loads": 1,
        }
        _publish_exact(self._root / "credential-load.json", record)

    def consume(self, chain: MassiveRequestChain) -> None:
        path = self._root / "consumed.json"
        if path.exists():
            stored = _load_exact_record(path, "Massive qualification consumption")
            self._validate_consumption(stored)
            return
        record = {
            "schema_version": "program-002-massive-qualification-consumption-v1",
            "attempt_id": self._attempt_id,
            "first_request_chain_identity": chain.identity,
            "disposition": "consumed-no-retry",
        }
        _publish_exact(path, record)

    def _validate_consumption(self, stored: Mapping[str, Any]) -> None:
        if (
            stored.get("schema_version") != "program-002-massive-qualification-consumption-v1"
            or stored.get("attempt_id") != self._attempt_id
            or not _is_sha256(stored.get("first_request_chain_identity"))
            or stored.get("disposition") != "consumed-no-retry"
        ):
            raise MassiveQualificationError("Massive qualification consumption differs")

    def publish_receipt(self, receipt: Mapping[str, Any]) -> None:
        _publish_exact(self._root / "receipt.json", receipt, allow_identical=True)

    def finish(self, disposition: str, evidence: Mapping[str, Any]) -> None:
        if disposition not in {"passed-terminal", "failed-no-retry"}:
            raise ValueError("Massive qualification disposition is invalid")
        record = {
            "schema_version": "program-002-massive-qualification-outcome-v1",
            "attempt_id": self._attempt_id,
            "disposition": disposition,
            "evidence": dict(evidence),
        }
        _publish_exact(self._root / "outcome.json", record, allow_identical=True)


def read_massive_credential(
    gates: Mapping[str, Any],
    authority: QualificationAuthority,
    attempt: OneUseAttempt,
    environ: Mapping[str, str] | None = None,
) -> str:
    pre_transport_gate_preflight(gates)
    values = os.environ if environ is None else environ
    value = values.get(_CREDENTIAL_NAME, "")
    if not value:
        raise MassiveCredentialUnavailable("Massive qualification credential is unavailable")
    attempt.mark_credential_load()
    if hashlib.sha256(value.encode()).hexdigest() != authority.payload.get(
        "credential_identity_hash"
    ):
        raise MassiveQualificationError("Massive qualification credential identity differs")
    return value


def execute_massive_source_qualification(
    plan: MassiveSourcePlan,
    gates: Mapping[str, Any],
    authority: QualificationAuthority,
    layout: StorageLayout,
    *,
    environ: Mapping[str, str] | None = None,
    request_transport: Callable[[Request], HttpPage] = _urlopen_page,
    pace: Callable[[], None] | None = None,
    retry_wait: Callable[[float], None] = system_time.sleep,
    wall_clock: Callable[[], float] = system_time.time,
) -> Mapping[str, Any]:
    pre_transport_gate_preflight(gates)
    chains = build_massive_request_plan(plan)
    credential_free_request_preflight(plan, chains)
    bindings = _mapping(authority.payload.get("bindings"), "Massive authority bindings")
    implementation = _mapping(bindings.get("implementation"), "Massive implementation binding")
    source_commit = implementation.get("source_commit")
    if not _is_commit(source_commit):
        raise MassiveQualificationError("Massive implementation source commit differs")
    budget = QualificationBudget()
    shared_pace = RequestPacer() if pace is None else pace
    with OneUseAttempt(layout, authority) as attempt:
        client: MassiveHttpClient | None = None
        try:
            adjustment_proof = _mapping(
                authority.payload.get("adjustment_proof"), "Massive adjustment proof"
            )
            require_exact_adjustment_proof(adjustment_proof)
            trade_contract = trade_audit_contract_from_authority(authority)

            def fetch(chain: MassiveRequestChain, url: str) -> HttpPage:
                nonlocal client
                if client is None:
                    api_key = read_massive_credential(gates, authority, attempt, environ)
                    client = MassiveHttpClient(api_key, chains, request_transport)
                attempt.consume(chain)
                return client.get(chain, url)

            acquired: list[AcquiredMassiveChain] = []
            for chain in chains:
                item, _ = acquire_or_load_massive_chain(
                    layout,
                    attempt.attempt_id,
                    chain,
                    partial(fetch, chain),
                    budget,
                    pace=shared_pace,
                    retry_wait=retry_wait,
                    wall_clock=wall_clock,
                )
                acquired.append(item)
            if not attempt.consumed:
                raise MassiveQualificationError(
                    "Massive qualification has no authority-bound transport request"
                )
            assessed = dict(
                assess_massive_source_qualification(
                    plan,
                    acquired,
                    adjustment_proof=adjustment_proof,
                    trade_contract=trade_contract,
                )
            )
            assessed.pop("receipt_fingerprint", None)
            assessed.update(
                {
                    "authority_sha256": authority.sha256,
                    "authority_fingerprint": authority.authority_fingerprint,
                    "source_commit": source_commit,
                    "credential_identity_hash": authority.payload["credential_identity_hash"],
                    "credential_loads": int(attempt.credential_loaded),
                    "request_chains": budget.request_chains,
                    "http_pages": budget.pages,
                    "response_bytes": budget.response_bytes,
                    "requests": [_chain_manifest(chain) for chain in chains],
                    "authority_consumed": True,
                    "one_use_attempt_terminal": True,
                    "authority": _terminal_authority(),
                }
            )
            receipt = {**assessed, "receipt_fingerprint": fingerprint(assessed)}
            attempt.publish_receipt(receipt)
            attempt.finish(
                "passed-terminal",
                {"receipt_fingerprint": receipt["receipt_fingerprint"]},
            )
            return receipt
        except MassiveCredentialUnavailable:
            raise
        except (
            MassiveQualificationError,
            Program002AcquisitionError,
            OSError,
            ValueError,
        ) as cause:
            error = (
                cause
                if isinstance(cause, MassiveQualificationError)
                else MassiveQualificationError(str(cause))
            )
            quarantine_identity = _quarantine_massive_failure(layout, authority, error)
            result = "FAIL" if attempt.consumed else "NOT-RUN-PRE-TRANSPORT-STOP"
            failed: dict[str, Any] = {
                "schema_version": "program-002-massive-source-qualification-receipt-v1",
                "provider": "Massive.com",
                "product": "Stocks Business",
                "plan_sha256": plan.sha256,
                "authority_sha256": authority.sha256,
                "authority_fingerprint": authority.authority_fingerprint,
                "source_commit": source_commit,
                "credential_identity_hash": authority.payload.get("credential_identity_hash"),
                "credential_loads": int(attempt.credential_loaded),
                "request_plan_fingerprint": fingerprint([chain.identity for chain in chains]),
                "request_chains": budget.request_chains,
                "http_pages": budget.pages,
                "response_bytes": budget.response_bytes,
                "failed_request_chain_identity": getattr(
                    getattr(error, "failed_chain", None), "identity", None
                ),
                "failure": str(error),
                "quarantine_identity": quarantine_identity,
                "source_qualification": result,
                "authority_consumed": attempt.consumed,
                "one_use_attempt_terminal": True,
                "zero_strategy_returns_generated": True,
                "controlled_or_protected_state_touched": False,
                "authority": _terminal_authority(),
            }
            receipt = {**failed, "receipt_fingerprint": fingerprint(failed)}
            attempt.publish_receipt(receipt)
            attempt.finish(
                "failed-no-retry",
                {
                    "receipt_fingerprint": receipt["receipt_fingerprint"],
                    "quarantine_identity": quarantine_identity,
                },
            )
            if error is cause:
                raise
            raise error from cause


def main(argv: Sequence[str] | None = None) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="trading-lab program-002 source")
    parser.add_argument("action", choices=("plan-massive", "qualify-massive"))
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--data-home", type=Path, default=Path(".trading-lab"))
    parser.add_argument("--authority", type=Path)
    parsed = parser.parse_args(
        arguments[2:] if arguments[:2] == ("program-002", "source") else arguments
    )
    try:
        plan = load_massive_source_plan(parsed.repository)
        chains = build_massive_request_plan(plan)
        preflight = credential_free_request_preflight(plan, chains)
        if parsed.action == "plan-massive":
            gates = load_pre_transport_gates(parsed.repository)
            output = {
                **preflight,
                "pre_transport_gate_status": gates["status"],
                "qualification_authority_created": False,
            }
            print(json.dumps(canonicalize(output), indent=2, sort_keys=True))
            return 0
        gates = load_pre_transport_gates(parsed.repository)
        pre_transport_gate_preflight(gates)
        expected_authority = (parsed.repository.resolve() / _AUTHORITY_PATH).resolve()
        if parsed.authority is None or parsed.authority.resolve() != expected_authority:
            raise MassiveQualificationError(
                f"Massive qualification requires exact authority path: {expected_authority}"
            )
        authority = load_qualification_authority(parsed.repository, plan, gates, chains)
        receipt = execute_massive_source_qualification(
            plan,
            gates,
            authority,
            StorageLayout(parsed.data_home.resolve()),
        )
        print(json.dumps(canonicalize(receipt), indent=2, sort_keys=True))
        return 0
    except (MassiveQualificationError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return os.EX_USAGE


def _aggregate_chain(symbol: str, raw_day: str, points: Sequence[datetime]) -> MassiveRequestChain:
    expected = tuple(_unix_ms(point) for point in points)
    endpoint = (
        f"{_ORIGIN}/v2/aggs/ticker/{quote(symbol, safe='')}/range/5/minute/"
        f"{expected[0]}/{expected[-1]}"
    )
    return MassiveRequestChain(
        "aggregate",
        symbol,
        endpoint,
        {"adjusted": "false", "limit": "50000", "sort": "asc"},
        raw_day,
        expected_timestamps=expected,
    )


def _trade_chain(symbol: str, raw_day: str, points: Sequence[datetime]) -> MassiveRequestChain:
    start = points[0]
    end = points[-1] + timedelta(minutes=5)
    return MassiveRequestChain(
        "trade",
        symbol,
        f"{_ORIGIN}/v3/trades/{quote(symbol, safe='')}",
        {
            "limit": "50000",
            "order": "asc",
            "sort": "timestamp",
            "timestamp.gte": str(_unix_ns(start)),
            "timestamp.lt": str(_unix_ns(end)),
        },
        raw_day,
    )


def _quote_chain(symbol: str, raw_day: str, raw_clock: str) -> MassiveRequestChain:
    point = datetime.combine(
        date.fromisoformat(raw_day), time.fromisoformat(raw_clock), _NY
    ).astimezone(UTC)
    return MassiveRequestChain(
        "quote",
        symbol,
        f"{_ORIGIN}/v3/quotes/{quote(symbol, safe='')}",
        {
            "limit": "50000",
            "order": "asc",
            "sort": "timestamp",
            "timestamp.gte": str(_unix_ns(point - timedelta(seconds=35))),
            "timestamp.lt": str(_unix_ns(point + timedelta(seconds=30))),
        },
        raw_day,
        raw_clock,
    )


def _split_chain(symbol: str) -> MassiveRequestChain:
    return MassiveRequestChain(
        "split",
        symbol,
        f"{_ORIGIN}/stocks/v1/splits",
        {
            "execution_date.gte": _ACTION_START.isoformat(),
            "execution_date.lte": _ACTION_END.isoformat(),
            "limit": "5000",
            "sort": "execution_date.asc",
            "ticker": symbol,
        },
    )


def _dividend_chain(symbol: str) -> MassiveRequestChain:
    return MassiveRequestChain(
        "dividend",
        symbol,
        f"{_ORIGIN}/stocks/v1/dividends",
        {
            "ex_dividend_date.gte": _ACTION_START.isoformat(),
            "ex_dividend_date.lte": _ACTION_END.isoformat(),
            "limit": "5000",
            "sort": "ex_dividend_date.asc",
            "ticker": symbol,
        },
    )


def _ticker_event_chain(symbol: str) -> MassiveRequestChain:
    return MassiveRequestChain(
        "ticker-event",
        symbol,
        f"{_ORIGIN}/vX/reference/tickers/{quote(symbol, safe='')}/events",
        {"types": "ticker_change"},
    )


def _validate_request_plan(plan: MassiveSourcePlan, chains: Sequence[MassiveRequestChain]) -> None:
    sample = _mapping(plan.payload.get("source_qualification_design"), "qualification sample")
    budget = _mapping(
        _mapping(sample.get("resource_limits"), "qualification limits").get("request_chain_budget"),
        "request-chain budget",
    )
    counts = {
        "aggregate_symbol_sessions": sum(item.kind == "aggregate" for item in chains),
        "raw_trade_symbol_sessions": sum(item.kind == "trade" for item in chains),
        "quote_symbol_windows": sum(item.kind == "quote" for item in chains),
        "corporate_action_symbol_endpoint_pairs": sum(
            item.kind in {"split", "dividend", "ticker-event"} for item in chains
        ),
    }
    if (
        len(chains) != _MAX_CHAINS
        or len({item.identity for item in chains}) != len(chains)
        or any(budget.get(key) != value for key, value in counts.items())
        or budget.get("expected_and_maximum_total") != _MAX_CHAINS
        or counts
        != {
            "aggregate_symbol_sessions": 117,
            "raw_trade_symbol_sessions": 6,
            "quote_symbol_windows": 468,
            "corporate_action_symbol_endpoint_pairs": 39,
        }
    ):
        raise MassiveQualificationError("Massive request-chain scope differs")
    controlled_start = date.fromisoformat(
        str(
            _mapping(plan.payload.get("preserved_science"), "preserved science")["controlled_a"]
        ).split("..", 1)[0]
    )
    for item in chains:
        parsed = urlparse(item.url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "api.massive.com"
            or parsed.username
            or parsed.password
            or "apiKey" in dict(parse_qsl(parsed.query))
            or (
                item.session_date is not None
                and date.fromisoformat(item.session_date) >= controlled_start
            )
            or (item.kind == "aggregate" and item.params.get("adjusted") != "false")
        ):
            raise MassiveQualificationError("Massive request exceeds the frozen scope")


def _validate_next_url(chain: MassiveRequestChain, next_url: str) -> None:
    parsed = urlparse(next_url)
    base = urlparse(chain.url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    cursors = [value for key, value in query if key == "cursor"]
    query_keys = [key for key, _ in query]
    base_query = dict(parse_qsl(base.query, keep_blank_values=True))
    if (
        parsed.scheme != "https"
        or parsed.netloc != "api.massive.com"
        or parsed.path != base.path
        or parsed.params
        or parsed.fragment
        or parsed.username
        or parsed.password
        or len(query_keys) != len(set(query_keys))
        or len(cursors) != 1
        or not cursors[0]
        or any(key not in base_query and key != "cursor" for key, _ in query)
        or any(key != "cursor" and base_query.get(key) != value for key, value in query)
    ):
        raise MassiveQualificationError("Massive next_url differs from the request chain")


def _parse_provider_page(
    body: bytes, kind: str
) -> tuple[Mapping[str, Any], tuple[Mapping[str, Any], ...]]:
    payload = _load_unique_json(body, "Massive response")
    if payload.get("status") != "OK":
        raise MassiveQualificationError("Massive response status is not OK")
    results = payload.get("results")
    if kind == "ticker-event":
        container = _mapping(results, "Massive ticker-event results")
        values = container.get("events")
    else:
        values = results
    if not isinstance(values, list) or any(not isinstance(item, Mapping) for item in values):
        raise MassiveQualificationError("Massive response results are malformed")
    return payload, tuple(dict(item) for item in values)


def _validate_chain_structure(acquired: AcquiredMassiveChain) -> None:
    if not acquired.pages:
        raise MassiveQualificationError("Massive request chain has no response page")
    _validate_acquired_pagination(acquired)
    if acquired.chain.kind == "aggregate":
        validate_aggregate_chain(acquired)
    elif acquired.chain.kind == "quote":
        eligible_quote_observation_count(acquired)
    elif acquired.chain.kind in {"split", "dividend", "ticker-event"}:
        validate_corporate_action_chain(acquired)
    elif acquired.chain.kind == "trade":
        for raw in acquired.records:
            _integer(raw.get("sip_timestamp"), "trade SIP timestamp")
            _positive_decimal(raw.get("price"), "trade price")


def _validate_acquired_pagination(acquired: AcquiredMassiveChain) -> None:
    expected_url = acquired.chain.url
    page_hashes: set[str] = set()
    for index, page in enumerate(acquired.pages):
        if (
            page.request_url != expected_url
            or page.sha256 != hashlib.sha256(page.body).hexdigest()
            or page.sha256 in page_hashes
        ):
            raise MassiveQualificationError("Massive response pagination differs")
        page_hashes.add(page.sha256)
        payload, _ = _parse_provider_page(page.body, acquired.chain.kind)
        next_url = payload.get("next_url")
        if index + 1 == len(acquired.pages):
            if next_url is not None:
                raise MassiveQualificationError("Massive response pagination is incomplete")
            continue
        if not isinstance(next_url, str) or not next_url:
            raise MassiveQualificationError("Massive response pagination differs")
        _validate_next_url(acquired.chain, next_url)
        expected_url = next_url


def _chain_manifest(chain: MassiveRequestChain) -> Mapping[str, Any]:
    return {
        "identity": chain.identity,
        "kind": chain.kind,
        "symbol": chain.symbol,
        "url": chain.url,
        "session_date": chain.session_date,
        "clock": chain.clock,
        "expected_timestamps": list(chain.expected_timestamps),
    }


def _stored_chain_identity(attempt_id: str, chain: MassiveRequestChain) -> str:
    return fingerprint({"attempt_id": _attempt_id(attempt_id), "chain_identity": chain.identity})


def _replay_budget(budget: QualificationBudget, acquired: AcquiredMassiveChain) -> None:
    budget.begin(acquired.chain)
    for page in acquired.pages:
        for size in _response_attempt_sizes(page):
            budget.add_page_size(size)


def _response_attempt_sizes(page: MassiveRawPage) -> tuple[int, ...]:
    if not page.attempts:
        raise MassiveQualificationError("stored Massive request attempts differ")
    sizes: list[int] = []
    for index, raw in enumerate(page.attempts, start=1):
        attempt = _mapping(raw, "stored Massive request attempt")
        status = attempt.get("status")
        size = _nonnegative_integer(
            attempt.get("captured_body_length"), "stored Massive response length"
        )
        body_hex = attempt.get("body_hex")
        try:
            captured = b"" if body_hex is None else bytes.fromhex(str(body_hex))
        except ValueError as error:
            raise MassiveQualificationError("stored Massive response body differs") from error
        if (
            attempt.get("attempt") != index
            or attempt.get("request_url") != page.request_url
            or (status is not None and not isinstance(status, int))
            or attempt.get("captured_body_truncated") is not False
            or len(captured) != min(size, 8192)
            or (
                status is not None
                and size <= 8192
                and hashlib.sha256(captured).hexdigest() != attempt.get("captured_body_sha256")
            )
        ):
            raise MassiveQualificationError("stored Massive request attempts differ")
        if status is not None:
            sizes.append(size)
    final = _mapping(page.attempts[-1], "stored Massive final request attempt")
    if (
        final.get("status") != 200
        or final.get("disposition") != "accepted"
        or final.get("captured_body_length") != len(page.body)
        or final.get("captured_body_sha256") != page.sha256
        or bytes.fromhex(str(final.get("body_hex") or "")) != page.body[:8192]
    ):
        raise MassiveQualificationError("stored Massive final response differs")
    return tuple(sizes)


def _session_bar_opens(day: date) -> tuple[datetime, ...]:
    return expected_bar_timestamps(
        datetime.combine(day, time.min, UTC),
        datetime.combine(day, time.max, UTC),
        Timeframe.FIVE_MINUTES,
    )


def _unix_ms(value: datetime) -> int:
    return _unix_ns(value) // 1_000_000


def _unix_ns(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    delta = value.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (
        delta.days * 86_400_000_000_000 + delta.seconds * 1_000_000_000 + delta.microseconds * 1_000
    )


def _iso_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, UTC).isoformat().replace("+00:00", "Z")


def _terminal_authority() -> Mapping[str, bool]:
    return {
        "source_requests": False,
        "source_qualification": False,
        **{key: False for key in sorted(_DOWNSTREAM_AUTHORITY_KEYS)},
    }


def _quarantine_massive_failure(
    layout: StorageLayout,
    authority: QualificationAuthority,
    error: MassiveQualificationError,
) -> str | None:
    pages = getattr(error, "partial_pages", ())
    attempts = getattr(error, "http_attempts", ())
    chain = getattr(error, "failed_chain", None)
    if not pages and not attempts:
        return None
    evidence = {
        "schema_version": "program-002-massive-qualification-quarantine-v1",
        "attempt_id": authority.payload.get("attempt_id"),
        "authority_sha256": authority.sha256,
        "failed_chain": _chain_manifest(chain) if isinstance(chain, MassiveRequestChain) else None,
        "raw_pages": [
            {
                "request_url": page.request_url,
                "sha256": page.sha256,
                "request_id": page.request_id,
                "body_hex": page.body.hex(),
                "http_attempts": list(page.attempts),
            }
            for page in pages
            if isinstance(page, MassiveRawPage)
        ],
        "http_attempts": list(attempts),
        "observed_response": getattr(error, "observed_response", None),
        "failure": str(error),
    }
    identity = fingerprint(evidence)
    contents = canonical_json(evidence) + "\n"
    path = layout.write_quarantine(identity, contents)
    if path.read_text(encoding="utf-8") != contents:
        raise MassiveQualificationError("Massive quarantine evidence conflicts")
    return identity


def _publish_exact(path: Path, record: Mapping[str, Any], *, allow_identical: bool = False) -> None:
    payload = dict(record)
    payload["fingerprint"] = fingerprint(payload)
    contents = canonical_json(payload) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if allow_identical and path.read_text(encoding="utf-8") == contents:
            return
        raise MassiveQualificationError(
            f"Massive one-use evidence already exists: {path.name}"
        ) from None


def _load_exact_record(path: Path, label: str) -> Mapping[str, Any]:
    raw = path.read_bytes()
    record = _load_unique_json(raw, label)
    unsigned = dict(record)
    stored_fingerprint = unsigned.pop("fingerprint", None)
    if raw != (canonical_json(record) + "\n").encode() or stored_fingerprint != fingerprint(
        unsigned
    ):
        raise MassiveQualificationError(f"{label} differs")
    return record


def _load_unique_json(raw: bytes, label: str) -> Mapping[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            if key in output:
                raise MassiveQualificationError(f"{label} contains duplicate JSON key")
            output[key] = value
        return output

    try:
        value = json.loads(
            raw,
            object_pairs_hook=unique,
            parse_float=Decimal,
            parse_int=int,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise MassiveQualificationError(f"{label} is malformed") from error
    return _mapping(value, label)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MassiveQualificationError(f"{label} is malformed")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise MassiveQualificationError(f"{label} is malformed")
    return tuple(value)


def _integers(value: object, label: str) -> tuple[int, ...]:
    if (
        not isinstance(value, list)
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
        or len(set(value)) != len(value)
    ):
        raise MassiveQualificationError(f"{label} is malformed")
    return tuple(value)


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool):
        raise MassiveQualificationError(f"{label} is malformed")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (ArithmeticError, ValueError) as error:
        raise MassiveQualificationError(f"{label} is malformed") from error
    if not parsed.is_finite():
        raise MassiveQualificationError(f"{label} is malformed")
    return parsed


def _positive_decimal(value: object, label: str) -> Decimal:
    parsed = _decimal(value, label)
    if parsed <= 0:
        raise MassiveQualificationError(f"{label} is malformed")
    return parsed


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise MassiveQualificationError(f"{label} is malformed")
    parsed = _decimal(value, label)
    if parsed != parsed.to_integral_value():
        raise MassiveQualificationError(f"{label} is malformed")
    return int(parsed)


def _nonnegative_integer(value: object, label: str) -> int:
    parsed = _integer(value, label)
    if parsed < 0:
        raise MassiveQualificationError(f"{label} is malformed")
    return parsed


def _attempt_id(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{7,127}", value):
        raise MassiveQualificationError("Massive qualification attempt id is invalid")
    return value


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _is_commit(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


if __name__ == "__main__":
    raise SystemExit(main())
