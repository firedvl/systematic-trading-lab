"""Fail-closed Program 002 SIP acquisition boundary."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import tempfile
import time as system_time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_CEILING, Decimal
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo

from .calendar import expected_bar_timestamps
from .catalog import DatasetCatalog
from .config import non_broker_subprocess_environment
from .datasets import DatasetService
from .domain import (
    AdjustmentPolicy,
    DatasetIdentity,
    DatasetManifest,
    OHLCVBar,
    Symbol,
    Timeframe,
    TimestampRange,
)
from .fingerprints import canonical_json, canonicalize, fingerprint
from .intraday_execution_cost_model import load_intraday_execution_cost_model
from .multi_hour_sector_etf_plan import (
    ACQUISITION_AUTHORITY_REVIEW_RELATIVE_PATH,
    ACQUISITION_SOURCE_PATHS,
    PROGRAM_002_REUSED_CONTEXT_DATASET_BINDING,
    REVIEWED_ACQUISITION_NO_TRADE_COMPLETENESS_AMENDMENT_FINGERPRINT,
    REVIEWED_ACQUISITION_NO_TRADE_COMPLETENESS_AMENDMENT_SHA256,
    Program002AcquisitionPlan,
    load_program_002_acquisition_authority_review,
    load_program_002_acquisition_plan,
)
from .parquet import to_parquet
from .program_002_credentials import credential_key_id_hash, read_acquisition_credentials
from .storage import StorageLayout
from .validation import validate_records

_NY = ZoneInfo("America/New_York")
_BARS = "https://data.alpaca.markets/v2/stocks/bars"
_QUOTES = "https://data.alpaca.markets/v2/stocks/quotes"
_BAR_SEGMENT_SCHEMA = "program-002-acquisition-segment-v2"
_LEGACY_BAR_SEGMENT_SCHEMA = "program-002-acquisition-segment-v1"
_PROGRAM_002_NORMALIZATION_VERSION = "program-002-provider-omission-normalization-v2"
_EXPOSED_BAR_ROLES = ("exposed-block-1", "exposed-block-2", "exposed-block-3")
_ALLOWED_PROVIDER_OMISSIONS = (
    (
        "exposed-block-1",
        "2020-12-01T14:30:00Z",
        "2020-12-31T20:55:00Z",
        "MDY",
        "2020-12-04T18:10:00Z",
        "2020-12-04T18:05:00Z",
        "2020-12-04T18:15:00Z",
    ),
    (
        "exposed-block-1",
        "2020-12-01T14:30:00Z",
        "2020-12-31T20:55:00Z",
        "MDY",
        "2020-12-04T18:25:00Z",
        "2020-12-04T18:20:00Z",
        "2020-12-04T18:30:00Z",
    ),
)


class Program002AcquisitionError(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpPage:
    status: int
    body: bytes
    headers: Mapping[str, str]
    attempts: tuple[Mapping[str, Any], ...] = ()
    captured_body_truncated: bool = False


class HistoricalHttpClient:
    """Fixed-origin GET transport; callers inject it into acquisition for testability."""

    def __init__(
        self,
        api_key: str,
        secret: str,
        environment: str,
        plan: Program002AcquisitionPlan,
        segments: Sequence[RequestSegment],
        transport: Callable[[Request], HttpPage] | None = None,
    ) -> None:
        acquisition_authority_preflight(
            plan,
            credential_key_hash=credential_key_id_hash(api_key),
            account_environment=environment,
        )
        if not api_key or not secret:
            raise ValueError("Program 002 acquisition credentials are required")
        supplied = tuple(segments)
        if not supplied or len({segment.kind for segment in supplied}) != 1:
            raise Program002AcquisitionError("historical client segment scope differs")
        authorized = (
            tuple(segment for role in _EXPOSED_BAR_ROLES for segment in bar_segments(plan, role))
            if supplied[0].kind == "bars"
            else quote_segments(plan)
            if supplied[0].kind == "quotes"
            else ()
        )
        supplied_identities = {
            _request_identity(segment.url(), allow_page_token=False) for segment in supplied
        }
        if len(supplied_identities) != len(supplied) or any(
            segment not in authorized for segment in supplied
        ):
            raise Program002AcquisitionError("historical client segment exceeds v6 authority")
        self._headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret}
        self._transport = transport or _urlopen_page
        self._segments = supplied_identities

    def get(self, url: str) -> HttpPage:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "data.alpaca.markets"
            or parsed.path
            not in {
                "/v2/stocks/bars",
                "/v2/stocks/quotes",
            }
        ):
            raise Program002AcquisitionError("provider endpoint differs from frozen HTTPS contract")
        if _request_identity(url, allow_page_token=True) not in self._segments:
            raise Program002AcquisitionError(
                "provider request differs from frozen authority-bound segment"
            )
        return self._transport(Request(url, headers=self._headers, method="GET"))


class RequestPacer:
    """Frozen Program 002 minimum 350 ms request spacing."""

    def __init__(
        self,
        monotonic: Callable[[], float] = system_time.monotonic,
        sleep: Callable[[float], None] = system_time.sleep,
    ) -> None:
        self._monotonic = monotonic
        self._sleep = sleep
        self._last: float | None = None
        self._minimum_interval = 0.35

    def __call__(self) -> None:
        now = self._monotonic()
        if (
            self._last is not None
            and (remaining := self._minimum_interval - (now - self._last)) > 0
        ):
            self._sleep(remaining)
        self._last = self._monotonic()

    def update_server_limit(
        self, headers: Mapping[str, str], wall_clock: Callable[[], float] = system_time.time
    ) -> None:
        """Honor a lower advertised request-per-minute ceiling for future requests."""
        values = {key.lower(): value for key, value in headers.items()}
        try:
            limit = int(values.get("x-ratelimit-limit", ""))
        except ValueError:
            limit = 0
        if 0 < limit < 180:
            self._minimum_interval = max(self._minimum_interval, 60.0 / limit)
        try:
            remaining = int(values.get("x-ratelimit-remaining", ""))
            reset = float(values.get("x-ratelimit-reset", ""))
        except ValueError:
            return
        if remaining >= 0 and reset > wall_clock():
            self._minimum_interval = max(
                self._minimum_interval, (reset - wall_clock()) / max(remaining, 1)
            )


@dataclass(frozen=True)
class RequestSegment:
    kind: str
    endpoint: str
    params: Mapping[str, str]
    page_ceiling: int

    def url(self, token: str | None = None) -> str:
        params = dict(self.params)
        if token:
            params["page_token"] = token
        return f"{self.endpoint}?{urlencode(params)}"


@dataclass(frozen=True)
class RawPage:
    request_url: str
    body: bytes
    sha256: str
    request_evidence: Mapping[str, str]
    attempts: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class AcquiredSegment:
    segment: RequestSegment
    pages: tuple[RawPage, ...]
    raw_records: tuple[Mapping[str, Any], ...]
    normalized_records: tuple[dict[str, Any], ...]
    completion_ledger: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class PublishedDataset:
    dataset_id: str
    created: bool
    bar_count: int
    manifest: Mapping[str, Any]


def load_plan(repository: Path) -> Program002AcquisitionPlan:
    try:
        return load_program_002_acquisition_plan(repository)
    except (OSError, ValueError) as error:
        raise Program002AcquisitionError(str(error)) from error


def acquisition_credentials(environ: Mapping[str, str] | None = None) -> tuple[str, str]:
    try:
        return read_acquisition_credentials(environ)
    except ValueError as error:
        raise Program002AcquisitionError(str(error)) from error


def provider_contract_preflight(plan: Program002AcquisitionPlan) -> None:
    """Require the reviewed prospective inclusive-end control before secret access."""
    contract = _mapping(
        plan.control_payload.get("corrected_request_contract"), "corrected request contract"
    )
    if (
        contract.get("start_semantics") != "inclusive"
        or contract.get("end_semantics") != "inclusive"
    ):
        raise Program002AcquisitionError("provider contract preflight blocked")


def acquisition_authority_preflight(
    plan: Program002AcquisitionPlan,
    *,
    credential_key_hash: str | None = None,
    account_environment: str | None = None,
) -> None:
    """Require reviewed acquisition authority, clean source lineage, and proof continuity."""
    bindings = _mapping(plan.authority.payload.get("bindings"), "acquisition authority bindings")
    control = bindings.get("acquisition_control_amendment")
    evidence = bindings.get("provider_contract_evidence")
    proof = bindings.get("account_isolation_proof")
    amendment = bindings.get("acquisition_no_trade_completeness_amendment")
    context = bindings.get("reused_context_dataset")
    identity = plan.authority.payload.get("account_isolation")
    if (
        plan.authority.payload.get("schema_version")
        != "program-002-exposed-acquisition-authority-v6"
        or not isinstance(control, Mapping)
        or control.get("sha256") != plan.control_sha256
        or control.get("fingerprint") != plan.control_fingerprint
        or not isinstance(evidence, Mapping)
        or evidence.get("sha256") != plan.provider_contract_evidence_sha256
        or evidence.get("fingerprint") != plan.provider_contract_evidence_fingerprint
        or not isinstance(proof, Mapping)
        or not isinstance(proof.get("sha256"), str)
        or not isinstance(proof.get("fingerprint"), str)
        or not isinstance(amendment, Mapping)
        or amendment.get("sha256") != REVIEWED_ACQUISITION_NO_TRADE_COMPLETENESS_AMENDMENT_SHA256
        or amendment.get("fingerprint")
        != REVIEWED_ACQUISITION_NO_TRADE_COMPLETENESS_AMENDMENT_FINGERPRINT
        or context != PROGRAM_002_REUSED_CONTEXT_DATASET_BINDING
        or not isinstance(identity, Mapping)
        or identity.get("proof_accepted") is not True
        or not isinstance(identity.get("credential_key_id_hash"), str)
    ):
        raise Program002AcquisitionError(
            "revised acquisition authority with account-isolation proof is absent"
        )
    try:
        review = load_program_002_acquisition_authority_review(plan.path.parents[2], plan.authority)
    except (OSError, ValueError) as error:
        raise Program002AcquisitionError(str(error)) from error
    _repository_source_preflight(plan, review)
    if (
        credential_key_hash is not None
        and identity.get("credential_key_id_hash") != credential_key_hash
    ):
        raise Program002AcquisitionError("acquisition credential key differs from account proof")
    if account_environment is not None and identity.get("environment") != account_environment:
        raise Program002AcquisitionError(
            "acquisition account environment differs from account proof"
        )


def bar_segments(plan: Program002AcquisitionPlan, role: str) -> tuple[RequestSegment, ...]:
    return tuple(_bar_segment(plan, start, end) for start, end in _months(_role(plan, role)))


def _reject_context_reacquisition(role: str) -> None:
    if role == "exposed-context-only":
        raise Program002AcquisitionError(
            "the reviewed Program 002 context dataset must be reused, not reacquired"
        )


def quote_segments(plan: Program002AcquisitionPlan) -> tuple[RequestSegment, ...]:
    quote = _mapping(plan.payload.get("quote_cost_calibration"), "quote calibration")
    sessions, clocks = quote.get("sessions"), quote.get("fill_clocks_new_york")
    if (
        not isinstance(sessions, list)
        or not isinstance(clocks, list)
        or len(sessions) != 73
        or len(clocks) != 9
    ):
        raise Program002AcquisitionError("Program 002 quote scope differs")
    return tuple(_quote_segment(plan, session, item) for session in sessions for item in clocks)


def quote_segment_ids(
    plan: Program002AcquisitionPlan, acquisition_attempt_id: str
) -> tuple[str, ...]:
    _attempt_id(acquisition_attempt_id)
    return tuple(
        fingerprint(
            {
                "plan": plan.sha256,
                "acquisition_authority": plan.authority.sha256,
                "acquisition_attempt_id": acquisition_attempt_id,
                "quote_window": index,
                "request": segment.url(),
            }
        )
        for index, segment in enumerate(quote_segments(plan))
    )


def acquire_segment(
    segment: RequestSegment,
    transport: Callable[[str], HttpPage],
    *,
    pace: Callable[[], None] | None = None,
    retryable: Callable[[int], bool] = lambda value: value in {408, 425, 429, 500, 502, 503, 504},
    retry_wait: Callable[[float], None] = system_time.sleep,
    wall_clock: Callable[[], float] = system_time.time,
    quarantine_layout: StorageLayout | None = None,
    request_attempt_limit: int = 5,
) -> AcquiredSegment:
    _endpoint(segment.endpoint, segment.kind)
    if not 1 <= request_attempt_limit <= 5:
        raise ValueError("request attempt limit must be between 1 and 5")
    pace = RequestPacer() if pace is None else pace
    token: str | None = None
    seen: set[str] = set()
    pages: list[RawPage] = []
    raw: list[Mapping[str, Any]] = []
    normalized: list[dict[str, Any]] = []

    def fail(
        error: Program002AcquisitionError, page: HttpPage | None
    ) -> Program002AcquisitionError:
        error.page = page  # type: ignore[attr-defined]
        error.http_attempts = (  # type: ignore[attr-defined]
            page.attempts
            if page is not None and page.attempts
            else getattr(error, "http_attempts", ())
        )
        error.quarantine_identity = _quarantine_page(  # type: ignore[attr-defined]
            quarantine_layout,
            segment,
            url,
            page,
            error,
            previous_pages=pages,
            raw_records=raw,
        )
        return error

    for _ in range(segment.page_ceiling):
        url = segment.url(token)
        try:
            page = _request(
                url,
                transport,
                pace,
                retryable,
                retry_wait,
                wall_clock,
                request_attempt_limit,
            )
        except Program002AcquisitionError as error:
            raise fail(error, getattr(error, "page", None)) from None
        try:
            payload = _json(page.body)
        except Program002AcquisitionError as error:
            raise fail(error, page) from None
        key = "bars" if segment.kind == "bars" else "quotes"
        try:
            rows = _mapping(payload.get(key), key)
        except Program002AcquisitionError as error:
            raise fail(error, page) from None
        if set(rows) - set(segment.params["symbols"].split(",")):
            raise fail(
                Program002AcquisitionError("provider response has an unauthorized symbol"), page
            )
        if any(not isinstance(value, list) for value in rows.values()):
            raise fail(Program002AcquisitionError("provider response has invalid records"), page)
        if sum(len(value) for value in rows.values() if isinstance(value, list)) > 10_000:
            raise fail(
                Program002AcquisitionError("provider response exceeds 10000 records per page"), page
            )
        evidence = {
            "method": "GET",
            "endpoint": segment.endpoint,
            "request_url": url,
            "retrieval_timestamp": _iso(datetime.now(UTC)),
            "credential_mechanism": "PROGRAM_002_ACQUISITION_environment_only",
            "subscription_context": "explicit_sip_request_no_fallback",
            **segment.params,
            **{
                key: value
                for key, value in page.headers.items()
                if key.lower()
                in {
                    "retry-after",
                    "x-ratelimit-reset",
                    "x-ratelimit-remaining",
                    "x-ratelimit-limit",
                    "x-request-id",
                }
            },
        }
        pages.append(
            RawPage(
                segment.url(token),
                page.body,
                hashlib.sha256(page.body).hexdigest(),
                evidence,
                page.attempts,
            )
        )
        for symbol, values in rows.items():
            for value in values:
                if not isinstance(value, dict):
                    record_error = Program002AcquisitionError(
                        "provider response has invalid record"
                    )
                    raise fail(record_error, page)
                if "symbol" in value and value["symbol"] != symbol:
                    mismatch = Program002AcquisitionError(
                        "provider record symbol differs from container"
                    )
                    raise fail(mismatch, page)
                record = {**value, "symbol": symbol}
                raw.append(record)
                try:
                    if segment.kind == "bars":
                        if (parsed_bar := _normalized_bar(record, segment)) is not None:
                            normalized.append(parsed_bar)
                    else:
                        _require_quote_in_segment(record, segment)
                except Program002AcquisitionError as error:
                    if segment.kind == "quotes" and "malformed" in str(error):
                        continue
                    raise fail(error, page) from None
        if "next_page_token" not in payload:
            raise fail(
                Program002AcquisitionError("provider response omits terminal next_page_token"), page
            )
        next_token = payload["next_page_token"]
        if next_token is None:
            return AcquiredSegment(segment, tuple(pages), tuple(raw), tuple(normalized))
        if not isinstance(next_token, str) or not next_token or next_token in seen:
            raise fail(Program002AcquisitionError("invalid or repeated next_page_token"), page)
        seen.add(next_token)
        token = next_token
    ceiling_error = Program002AcquisitionError("Program 002 page ceiling exceeded")
    last_page = (
        HttpPage(
            200,
            pages[-1].body,
            {},
            pages[-1].attempts,
        )
        if pages
        else None
    )
    raise fail(ceiling_error, last_page)


def _complete_bar_segment(
    expected_symbols: Sequence[str],
    role: str,
    segment: RequestSegment,
    acquired: AcquiredSegment,
) -> AcquiredSegment:
    expected = expected_bar_timestamps(
        _time(segment.params["start"]),
        _time(segment.params["end"]),
        Timeframe.FIVE_MINUTES,
    )
    checked = validate_records(
        acquired.normalized_records,
        Timeframe.FIVE_MINUTES,
        expected_symbols=expected_symbols,
        expected_bar_timestamps=expected,
    )
    result = checked.result
    if (
        result.errors
        or result.duplicate_intervals
        or result.conflicts
        or result.quarantined_records
    ):
        raise Program002AcquisitionError("monthly bar segment validation failed")

    allowed = {
        f"{item['symbol']}@{_time(str(item['timestamp'])).isoformat()}": (
            str(item["symbol"]),
            _time(str(item["timestamp"])),
            _time(str(item["immediate_predecessor"])),
            _time(str(item["immediate_successor"])),
        )
        for item in _eligible_bar_completions(role, segment)
    }
    missing = set(result.missing_intervals)
    if not missing <= set(allowed):
        raise Program002AcquisitionError("monthly bar segment validation failed")

    observed = {(bar.symbol.value, bar.timestamp): bar for bar in checked.bars}
    completed = [canonicalize(bar.to_record()) for bar in checked.bars]
    ledger: list[Mapping[str, Any]] = []
    for label in sorted(missing):
        symbol, timestamp, predecessor_timestamp, successor_timestamp = allowed[label]
        predecessor = observed.get((symbol, predecessor_timestamp))
        successor = observed.get((symbol, successor_timestamp))
        if (
            predecessor is None
            or successor is None
            or predecessor.timestamp + timedelta(minutes=5) != timestamp
            or timestamp + timedelta(minutes=5) != successor.timestamp
            or len(
                {
                    item.astimezone(_NY).date()
                    for item in (predecessor.timestamp, timestamp, successor.timestamp)
                }
            )
            != 1
        ):
            raise Program002AcquisitionError("monthly bar segment validation failed")
        record = canonicalize(
            {
                "symbol": symbol,
                "timestamp": timestamp,
                "open": predecessor.close,
                "high": predecessor.close,
                "low": predecessor.close,
                "close": predecessor.close,
                "volume": 0,
            }
        )
        assert isinstance(record, dict)
        completed.append(record)
        ledger.append(
            {
                "symbol": symbol,
                "timestamp": _iso(timestamp),
                "source_predecessor_timestamp": _iso(predecessor_timestamp),
                "bounding_successor_timestamp": _iso(successor_timestamp),
                "reason": "provider-omitted-complete-ohlcv-bar",
                "canonical_record": record,
            }
        )
    completed.sort(key=lambda item: (str(item["symbol"]), str(item["timestamp"])))
    return AcquiredSegment(
        acquired.segment,
        acquired.pages,
        acquired.raw_records,
        tuple(completed),
        tuple(ledger),
    )


def _eligible_bar_completions(
    role: str | None, segment: RequestSegment
) -> tuple[Mapping[str, str], ...]:
    return tuple(
        {
            "role": allowed_role,
            "segment_start": start,
            "segment_end": end,
            "symbol": symbol,
            "timestamp": timestamp,
            "immediate_predecessor": predecessor,
            "immediate_successor": successor,
        }
        for allowed_role, start, end, symbol, timestamp, predecessor, successor in (
            _ALLOWED_PROVIDER_OMISSIONS
        )
        if role == allowed_role
        and segment.params["start"] == start
        and segment.params["end"] == end
    )


def _segment_processing(
    schema: str,
    segment: RequestSegment,
    acquired: AcquiredSegment,
    *,
    role: str | None,
) -> Mapping[str, Any]:
    base = {
        "normalization_version": "ohlcv-normalization-v1",
        "schema_version": "ohlcv-v1",
        "timestamp_policy": "bar-open-utc-v1" if segment.kind == "bars" else "quote-utc-v1",
    }
    if schema == _BAR_SEGMENT_SCHEMA:
        if segment.kind != "bars":
            raise Program002AcquisitionError("bar segment schema differs")
        ledger = tuple(acquired.completion_ledger)
        processing = canonicalize(
            {
                **base,
                "program_002_normalization_version": _PROGRAM_002_NORMALIZATION_VERSION,
                "eligible_completion_coordinates": _eligible_bar_completions(role, segment),
                "provider_omission_coordinates": tuple(
                    {"symbol": item["symbol"], "timestamp": item["timestamp"]} for item in ledger
                ),
                "provider_observed_normalized_record_count": len(acquired.normalized_records)
                - len(ledger),
                "synthesized_normalized_record_count": len(ledger),
                "completion_ledger": ledger,
                "completion_ledger_fingerprint": fingerprint(ledger),
            }
        )
        assert isinstance(processing, dict)
        return processing
    if acquired.completion_ledger:
        raise Program002AcquisitionError("legacy segment contains completion evidence")
    return base


def _segment_record(
    schema: str,
    identity: str,
    segment: RequestSegment,
    acquired: AcquiredSegment,
    *,
    role: str | None = None,
    plan_sha256: str,
    authority_sha256: str,
    acquisition_attempt_id: str,
    parent_segment_id: str | None = None,
) -> dict[str, Any]:
    raw_bytes = b"".join(canonical_json(item).encode() + b"\n" for item in acquired.raw_records)
    record: dict[str, Any] = {
        "schema_version": schema,
        "identity": identity,
        "acquisition_attempt_id": acquisition_attempt_id,
        "plan_sha256": plan_sha256,
        "acquisition_authority_sha256": authority_sha256,
        "parent_segment_id": parent_segment_id,
        "request": segment.url(),
        "raw_jsonl_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "raw_page_sha256_values": [page.sha256 for page in acquired.pages],
        "raw_record_fingerprint": fingerprint(acquired.raw_records),
        "request_evidence": [page.request_evidence for page in acquired.pages],
        "http_attempts": [list(page.attempts) for page in acquired.pages],
        "processing": _segment_processing(schema, segment, acquired, role=role),
    }
    if role is not None:
        record["role"] = role
    record["content_identity"] = fingerprint(record)
    return record


def _load_segment_artifact(
    layout: StorageLayout,
    identity: str,
    segment: RequestSegment,
    schema: str,
    *,
    role: str | None = None,
    plan_sha256: str | None = None,
    authority_sha256: str | None = None,
) -> AcquiredSegment:
    """Read a create-only segment only after every stored byte is revalidated."""
    root = layout.dataset(identity)
    try:
        artifact = _json((root / "segment.json").read_bytes())
        raw_bytes = (root / "raw-records.jsonl").read_bytes()
    except OSError as error:
        raise Program002AcquisitionError("stored segment artifact is incomplete") from error
    required = {
        "schema_version",
        "identity",
        "acquisition_attempt_id",
        "plan_sha256",
        "acquisition_authority_sha256",
        "parent_segment_id",
        "request",
        "raw_jsonl_sha256",
        "raw_page_sha256_values",
        "raw_record_fingerprint",
        "request_evidence",
        "http_attempts",
        "processing",
        "content_identity",
    }
    if role is not None:
        required.add("role")
    if (
        set(artifact) != required
        or artifact.get("schema_version") != schema
        or artifact.get("identity") != identity
        or artifact.get("request") != segment.url()
        or (plan_sha256 is not None and artifact.get("plan_sha256") != plan_sha256)
        or (
            authority_sha256 is not None
            and artifact.get("acquisition_authority_sha256") != authority_sha256
        )
        or (role is not None and artifact.get("role") != role)
        or artifact.get("raw_jsonl_sha256") != hashlib.sha256(raw_bytes).hexdigest()
        or artifact.get("content_identity")
        != fingerprint({key: value for key, value in artifact.items() if key != "content_identity"})
    ):
        raise Program002AcquisitionError("stored segment artifact conflicts")
    try:
        rows = tuple(_json(line.encode()) for line in raw_bytes.decode("utf-8").splitlines())
    except UnicodeDecodeError as error:
        raise Program002AcquisitionError("stored raw records are not UTF-8") from error
    if artifact.get("raw_record_fingerprint") != fingerprint(rows):
        raise Program002AcquisitionError("stored segment integrity differs")
    expected_hashes = artifact.get("raw_page_sha256_values")
    evidence = artifact.get("request_evidence")
    attempts = artifact.get("http_attempts")
    pages = tuple(sorted(root.glob("raw-page-*.json")))
    expected_names = tuple(f"raw-page-{index:04d}.json" for index in range(1, len(pages) + 1))
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in pages]
    if (
        not isinstance(expected_hashes, list)
        or not isinstance(evidence, list)
        or not isinstance(attempts, list)
        or len(evidence) != len(pages)
        or len(attempts) != len(pages)
        or not expected_hashes
        or tuple(path.name for path in pages) != expected_names
        or hashes != expected_hashes
    ):
        raise Program002AcquisitionError("stored raw page bytes differ")
    parsed_bars = (
        tuple(_normalized_bar(row, segment) for row in rows) if segment.kind == "bars" else ()
    )
    normalized = tuple(row for row in parsed_bars if row is not None)
    acquired = AcquiredSegment(
        segment,
        tuple(
            RawPage(segment.url(), path.read_bytes(), digest, request, tuple(page_attempts))
            for path, digest, request, page_attempts in zip(
                pages, hashes, evidence, attempts, strict=True
            )
        ),
        rows,
        normalized,
    )
    if schema == _BAR_SEGMENT_SCHEMA:
        if role is None:
            raise Program002AcquisitionError("stored bar segment role is missing")
        acquired = _complete_bar_segment(
            tuple(segment.params["symbols"].split(",")), role, segment, acquired
        )
    if artifact.get("processing") != _segment_processing(schema, segment, acquired, role=role):
        raise Program002AcquisitionError("stored segment processing differs")
    return acquired


def acquire_role_segments(
    plan: Program002AcquisitionPlan,
    role: str,
    layout: StorageLayout,
    transport: Callable[[str], HttpPage],
    *,
    acquisition_attempt_id: str,
    pace: Callable[[], None] | None = None,
) -> tuple[str, ...]:
    """Acquire one frozen monthly segment at a time, resuming verified artifacts."""
    _reject_context_reacquisition(role)
    _attempt_id(acquisition_attempt_id)
    _validate_segment_journal(layout)
    _validate_terminal_attempt_journal(layout)
    completed: list[str] = []
    shared_pace = RequestPacer() if pace is None else pace
    for segment in bar_segments(plan, role):
        identity = _segment_identity(plan, role, segment, acquisition_attempt_id)
        path = layout.dataset(identity) / "segment.json"
        if path.exists():
            stored = _load_segment_artifact(
                layout,
                identity,
                segment,
                _BAR_SEGMENT_SCHEMA,
                role=role,
                plan_sha256=plan.sha256,
                authority_sha256=plan.authority.sha256,
            )
            try:
                _validate_bar_segment_complete(plan, segment, stored)
            except Program002AcquisitionError as error:
                quarantine_identity = _quarantine_acquired_segment(
                    layout, segment, stored, error, acquisition_attempt_id, identity
                )
                _append_terminal_attempt_journal(
                    layout, acquisition_attempt_id, segment, error, identity, quarantine_identity
                )
                raise
            _append_segment_journal(
                layout,
                _segment_record(
                    _BAR_SEGMENT_SCHEMA,
                    identity,
                    segment,
                    stored,
                    role=role,
                    plan_sha256=plan.sha256,
                    authority_sha256=plan.authority.sha256,
                    acquisition_attempt_id=acquisition_attempt_id,
                    parent_segment_id=stored_record_parent(layout, identity),
                ),
            )
            completed.append(identity)
            continue
        try:
            acquired = acquire_segment(
                segment, transport, pace=shared_pace, quarantine_layout=layout
            )
        except Program002AcquisitionError as error:
            _append_terminal_attempt_journal(layout, acquisition_attempt_id, segment, error)
            raise
        try:
            acquired = _complete_bar_segment(_symbols(plan), role, segment, acquired)
            _validate_bar_segment_complete(plan, segment, acquired)
        except Program002AcquisitionError as error:
            quarantine_identity = _quarantine_acquired_segment(
                layout, segment, acquired, error, acquisition_attempt_id, identity
            )
            _append_terminal_attempt_journal(
                layout, acquisition_attempt_id, segment, error, identity, quarantine_identity
            )
            raise
        record = _segment_record(
            _BAR_SEGMENT_SCHEMA,
            identity,
            segment,
            acquired,
            role=role,
            plan_sha256=plan.sha256,
            authority_sha256=plan.authority.sha256,
            acquisition_attempt_id=acquisition_attempt_id,
            parent_segment_id=_segment_correction_parent(layout, plan, segment, role),
        )
        files: dict[str, str | bytes] = {
            "segment.json": canonical_json(record) + "\n",
            "raw-records.jsonl": "".join(
                canonical_json(value) + "\n" for value in acquired.raw_records
            ),
            **{
                f"raw-page-{index:04d}.json": page.body
                for index, page in enumerate(acquired.pages, 1)
            },
        }
        if not layout.publish(identity, files):
            stored = _load_segment_artifact(
                layout,
                identity,
                segment,
                _BAR_SEGMENT_SCHEMA,
                role=role,
                plan_sha256=plan.sha256,
                authority_sha256=plan.authority.sha256,
            )
            if (
                _segment_record(
                    _BAR_SEGMENT_SCHEMA,
                    identity,
                    segment,
                    stored,
                    role=role,
                    plan_sha256=plan.sha256,
                    authority_sha256=plan.authority.sha256,
                    acquisition_attempt_id=acquisition_attempt_id,
                    parent_segment_id=stored_record_parent(layout, identity),
                )
                != record
            ):
                raise Program002AcquisitionError("stored segment artifact conflicts")
        _append_segment_journal(layout, record)
        completed.append(identity)
    return tuple(completed)


def _validate_bar_segment_complete(
    plan: Program002AcquisitionPlan, segment: RequestSegment, acquired: AcquiredSegment
) -> None:
    expected = expected_bar_timestamps(
        _time(segment.params["start"]),
        _time(segment.params["end"]),
        Timeframe.FIVE_MINUTES,
    )
    checked = validate_records(
        acquired.normalized_records,
        Timeframe.FIVE_MINUTES,
        expected_symbols=_symbols(plan),
        expected_bar_timestamps=expected,
    )
    if not checked.result.valid:
        raise Program002AcquisitionError("monthly bar segment validation failed")


def acquire_quote_segments(
    plan: Program002AcquisitionPlan,
    layout: StorageLayout,
    transport: Callable[[str], HttpPage],
    *,
    acquisition_attempt_id: str,
    pace: Callable[[], None] | None = None,
) -> tuple[str, ...]:
    """Persist one complete frozen quote window at a time for restartable calibration."""
    _attempt_id(acquisition_attempt_id)
    _validate_segment_journal(layout)
    _validate_terminal_attempt_journal(layout)
    completed: list[str] = []
    shared_pace = RequestPacer() if pace is None else pace
    for identity, segment in zip(
        quote_segment_ids(plan, acquisition_attempt_id), quote_segments(plan), strict=True
    ):
        path = layout.dataset(identity) / "segment.json"
        if path.exists():
            acquired = _load_segment_artifact(
                layout,
                identity,
                segment,
                "program-002-quote-window-v1",
                plan_sha256=plan.sha256,
                authority_sha256=plan.authority.sha256,
            )
            _append_segment_journal(
                layout,
                _segment_record(
                    "program-002-quote-window-v1",
                    identity,
                    segment,
                    acquired,
                    plan_sha256=plan.sha256,
                    authority_sha256=plan.authority.sha256,
                    acquisition_attempt_id=acquisition_attempt_id,
                    parent_segment_id=stored_record_parent(layout, identity),
                ),
            )
            completed.append(identity)
            continue
        try:
            acquired = acquire_segment(
                segment, transport, pace=shared_pace, quarantine_layout=layout
            )
        except Program002AcquisitionError as error:
            _append_terminal_attempt_journal(layout, acquisition_attempt_id, segment, error)
            raise
        artifact = _segment_record(
            "program-002-quote-window-v1",
            identity,
            segment,
            acquired,
            plan_sha256=plan.sha256,
            authority_sha256=plan.authority.sha256,
            acquisition_attempt_id=acquisition_attempt_id,
            parent_segment_id=_segment_correction_parent(layout, plan, segment, None),
        )
        published = layout.publish(
            identity,
            {
                "segment.json": canonical_json(artifact) + "\n",
                "raw-records.jsonl": "".join(
                    canonical_json(item) + "\n" for item in acquired.raw_records
                ),
                **{
                    f"raw-page-{page_index:04d}.json": page.body
                    for page_index, page in enumerate(acquired.pages, 1)
                },
            },
        )
        if not published:
            stored = _load_segment_artifact(
                layout,
                identity,
                segment,
                "program-002-quote-window-v1",
                plan_sha256=plan.sha256,
                authority_sha256=plan.authority.sha256,
            )
            if (
                _segment_record(
                    "program-002-quote-window-v1",
                    identity,
                    segment,
                    stored,
                    plan_sha256=plan.sha256,
                    authority_sha256=plan.authority.sha256,
                    acquisition_attempt_id=acquisition_attempt_id,
                    parent_segment_id=stored_record_parent(layout, identity),
                )
                != artifact
            ):
                raise Program002AcquisitionError("stored quote window conflicts")
        _append_segment_journal(layout, artifact)
        completed.append(identity)
    return tuple(completed)


def publish_role_dataset_from_artifacts(
    plan: Program002AcquisitionPlan,
    role: str,
    segment_ids: Sequence[str],
    layout: StorageLayout,
    retrieval_timestamp: datetime,
    *,
    acquisition_attempt_id: str,
) -> PublishedDataset:
    """Assemble a role from verified create-only segment artifacts, not live pages."""
    _reject_context_reacquisition(role)
    _attempt_id(acquisition_attempt_id)
    expected_ids = tuple(
        _segment_identity(plan, role, item, acquisition_attempt_id)
        for item in bar_segments(plan, role)
    )
    if tuple(segment_ids) != expected_ids:
        raise Program002AcquisitionError("role segment identities differ from frozen plan")
    normalized: list[dict[str, Any]] = []
    segment_evidence: list[Mapping[str, Any]] = []
    for identity, segment in zip(segment_ids, bar_segments(plan, role), strict=True):
        acquired = _load_segment_artifact(
            layout,
            identity,
            segment,
            _BAR_SEGMENT_SCHEMA,
            role=role,
            plan_sha256=plan.sha256,
            authority_sha256=plan.authority.sha256,
        )
        normalized.extend(acquired.normalized_records)
        segment_evidence.append(
            _segment_record(
                _BAR_SEGMENT_SCHEMA,
                identity,
                segment,
                acquired,
                role=role,
                plan_sha256=plan.sha256,
                authority_sha256=plan.authority.sha256,
                acquisition_attempt_id=acquisition_attempt_id,
                parent_segment_id=stored_record_parent(layout, identity),
            )
        )
    return _publish_normalized_role(
        plan, role, normalized, segment_evidence, layout, retrieval_timestamp
    )


def _publish_normalized_role(
    plan: Program002AcquisitionPlan,
    role: str,
    records: Sequence[dict[str, Any]],
    segments: Sequence[Mapping[str, Any]],
    layout: StorageLayout,
    retrieval_timestamp: datetime,
) -> PublishedDataset:
    del retrieval_timestamp
    target = _role(plan, role)
    provider_observed_count = 0
    eligible_completion_coordinates: list[Mapping[str, Any]] = []
    provider_omission_coordinates: list[Mapping[str, Any]] = []
    completion_ledger: list[Mapping[str, Any]] = []
    for segment in segments:
        processing = _mapping(segment.get("processing"), "bar segment processing")
        observed_count = processing.get("provider_observed_normalized_record_count")
        synthesized_count = processing.get("synthesized_normalized_record_count")
        eligible = processing.get("eligible_completion_coordinates")
        omissions = processing.get("provider_omission_coordinates")
        ledger = processing.get("completion_ledger")
        if (
            processing.get("program_002_normalization_version")
            != _PROGRAM_002_NORMALIZATION_VERSION
            or isinstance(observed_count, bool)
            or not isinstance(observed_count, int)
            or isinstance(synthesized_count, bool)
            or not isinstance(synthesized_count, int)
            or observed_count < 0
            or synthesized_count < 0
            or not isinstance(eligible, list)
            or not isinstance(omissions, list)
            or not isinstance(ledger, list)
            or synthesized_count != len(ledger)
            or omissions
            != [
                {"symbol": item.get("symbol"), "timestamp": item.get("timestamp")}
                for item in ledger
                if isinstance(item, Mapping)
            ]
            or processing.get("completion_ledger_fingerprint") != fingerprint(tuple(ledger))
            or any(not isinstance(item, Mapping) for item in eligible)
            or any(not isinstance(item, Mapping) for item in omissions)
            or any(not isinstance(item, Mapping) for item in ledger)
        ):
            raise Program002AcquisitionError("bar segment completion evidence differs")
        provider_observed_count += observed_count
        eligible_completion_coordinates.extend(eligible)
        provider_omission_coordinates.extend(omissions)
        completion_ledger.extend(ledger)
    if provider_observed_count + len(completion_ledger) != len(records):
        raise Program002AcquisitionError("bar segment completion counts differ")
    expected = expected_bar_timestamps(
        _time(target["inclusive_utc_bar_open_start"]),
        _time(target["inclusive_utc_bar_open_end"]),
        Timeframe.FIVE_MINUTES,
    )
    valid = validate_records(
        records,
        Timeframe.FIVE_MINUTES,
        expected_symbols=_symbols(plan),
        expected_bar_timestamps=expected,
    )
    if not valid.result.valid or len(valid.bars) != target["expected_rows"]:
        evidence = {
            "role": role,
            "validation": valid.result,
            "segment_ids": [item["identity"] for item in segments],
        }
        layout.write_quarantine(fingerprint(evidence), canonical_json(evidence) + "\n")
        raise Program002AcquisitionError("Program 002 bar validation failed")
    bars = tuple(sorted(valid.bars, key=lambda item: (item.symbol.value, item.timestamp)))
    _preflight(bars)
    canonical_bar_fingerprint = fingerprint(tuple(item.to_record() for item in bars))
    completion_processing = canonicalize(
        {
            "normalization_version": "ohlcv-normalization-v1",
            "schema_version": "ohlcv-v1",
            "program_002_normalization_version": _PROGRAM_002_NORMALIZATION_VERSION,
            "eligible_completion_coordinates": eligible_completion_coordinates,
            "provider_omission_coordinates": provider_omission_coordinates,
            "provider_observed_normalized_record_count": provider_observed_count,
            "synthesized_normalized_record_count": len(completion_ledger),
            "completion_ledger": completion_ledger,
            "completion_ledger_fingerprint": fingerprint(tuple(completion_ledger)),
        }
    )
    normalized_fingerprint = fingerprint(
        {
            "canonical_bar_fingerprint": canonical_bar_fingerprint,
            "processing": completion_processing,
        }
    )
    dataset_processing = {
        **completion_processing,
        "canonical_bar_fingerprint": canonical_bar_fingerprint,
        "normalized_fingerprint": normalized_fingerprint,
    }
    provider_raw_records = tuple(
        _json(line.encode())
        for item in segments
        for line in (layout.dataset(str(item["identity"])) / "raw-records.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    raw_evidence = {
        "program_002_raw_evidence": {
            "segment_content_identities": [item["content_identity"] for item in segments],
            "raw_page_sha256_values": [
                digest for item in segments for digest in item["raw_page_sha256_values"]
            ],
            "processing": dataset_processing,
        }
    }
    raw_records = (raw_evidence, *provider_raw_records)
    raw_text = "".join(canonical_json(item) + "\n" for item in raw_records)
    raw_fingerprint = fingerprint(raw_records)
    requested = TimestampRange(
        _time(target["inclusive_utc_bar_open_start"]), _time(target["inclusive_utc_bar_open_end"])
    )
    universe = _mapping(plan.payload["universe"], "universe")
    retrieval_timestamp = _segment_retrieval_timestamp(segments)
    calendar_package_and_version = {
        "package": "exchange_calendars",
        "version": importlib.metadata.version("exchange-calendars"),
    }
    dataset_id = fingerprint(
        {
            "provider": "alpaca-historical-v2",
            "symbols": tuple(sorted(_symbols(plan))),
            "timeframe": Timeframe.FIVE_MINUTES,
            "requested_range": requested,
            "adjustment_policy": AdjustmentPolicy.PROVIDER_ADJUSTED_ALL,
            "normalization_version": "ohlcv-normalization-v1",
            "schema_version": "ohlcv-v1",
            "calendar_policy": "XNYS-regular-session-bars-v1",
            "calendar_package_and_version": calendar_package_and_version,
            "timestamp_policy": "bar-open-utc-v1",
            "universe_id": universe["universe_id"],
            "universe_fingerprint": universe["universe_fingerprint"],
            "feed": "sip",
            "data_fingerprint": canonical_bar_fingerprint,
            "raw_fingerprint": raw_fingerprint,
        }
    )
    manifest = canonicalize(
        DatasetManifest(
            identity=DatasetIdentity(dataset_id, canonical_bar_fingerprint),
            provider="alpaca-historical-v2",
            symbols=tuple(Symbol(item) for item in _symbols(plan)),
            timeframe=Timeframe.FIVE_MINUTES,
            requested_range=requested,
            actual_range=TimestampRange(bars[0].timestamp, bars[-1].timestamp),
            retrieval_timestamp=retrieval_timestamp,
            raw_artifact_hashes=(raw_fingerprint,),
            normalization_version="ohlcv-normalization-v1",
            schema_version="ohlcv-v1",
            adjustment_policy="provider-adjusted-all-v1",
            calendar_policy="XNYS-regular-session-bars-v1",
            timestamp_policy="bar-open-utc-v1",
            universe_id=str(universe["universe_id"]),
            universe_fingerprint=str(universe["universe_fingerprint"]),
            validation=valid.result,
            feed="sip",
            parent_dataset_id=_correction_parent(layout, plan, role, dataset_id),
        )
    )
    assert isinstance(manifest, dict)
    manifest.update(
        {
            "dataset_id": dataset_id,
            "normalized_fingerprint": normalized_fingerprint,
            "canonical_bar_fingerprint": canonical_bar_fingerprint,
            "manifest_schema": "program-002-ohlcv-dataset-manifest-v1",
            "program_002": {
                "role": role,
                "plan_sha256": plan.sha256,
                "acquisition_authority_sha256": plan.authority.sha256,
                "allowed_use": target.get(
                    "allowed_use", "exposed-research-after-separate-authority"
                ),
                "request_segments": segments,
                "processing": {
                    **dataset_processing,
                    "calendar_package": calendar_package_and_version["package"],
                    "calendar_version": calendar_package_and_version["version"],
                },
            },
            "program_002_manifest_schema_version": "program-002-ohlcv-dataset-manifest-v1",
            "endpoint": _BARS,
            "calendar_package_and_version": calendar_package_and_version,
            "request_segments": segments,
            "raw_record_fingerprint": raw_fingerprint,
            "raw_jsonl_sha256": hashlib.sha256(raw_text.encode()).hexdigest(),
            "raw_page_sha256_values": [
                digest for item in segments for digest in item["raw_page_sha256_values"]
            ],
            "validation_evidence": {
                "expected_rows": target["expected_rows"],
                "bar_count": len(bars),
                "provider_observed_bar_count": provider_observed_count,
                "synthesized_bar_count": len(completion_ledger),
                "completion_ledger": completion_ledger,
                "completion_ledger_fingerprint": fingerprint(tuple(completion_ledger)),
                "thirty_minute_preflight": True,
            },
        }
    )
    parquet = to_parquet(bars)
    manifest["files"] = {
        "raw.jsonl": hashlib.sha256(raw_text.encode()).hexdigest(),
        "bars.parquet": hashlib.sha256(parquet).hexdigest(),
    }
    manifest_text = canonical_json(manifest) + "\n"
    manifest_sidecar = (
        canonical_json(
            {
                "dataset_id": dataset_id,
                "manifest_sha256": hashlib.sha256(manifest_text.encode()).hexdigest(),
            }
        )
        + "\n"
    )
    _validate_final_dataset_staging(dataset_id, manifest, raw_text, parquet, manifest_sidecar)
    created = layout.publish(
        dataset_id,
        {
            "raw.jsonl": raw_text,
            "bars.parquet": parquet,
            "manifest.json": manifest_text,
            "manifest.sha256.json": manifest_sidecar,
        },
    )
    path = layout.dataset(dataset_id) / "manifest.json"
    stored = _json(path.read_bytes())
    if stored != manifest or _manifest_bytes_valid(layout.dataset(dataset_id), stored) is False:
        raise Program002AcquisitionError("existing immutable dataset conflicts")
    DatasetCatalog(layout.catalog).register(dict(stored), path)
    if not DatasetService(layout).validate(dataset_id)["valid"]:
        raise Program002AcquisitionError("final dataset fails repository validation contract")
    return PublishedDataset(dataset_id, created, len(bars), stored)


def _validate_final_dataset_staging(
    dataset_id: str,
    manifest: Mapping[str, Any],
    raw_text: str,
    parquet: bytes,
    manifest_sidecar: str,
) -> None:
    """Prove full DatasetService validity before any destination becomes visible."""
    root = Path(tempfile.mkdtemp(prefix="program-002-final-validate-"))
    try:
        layout = StorageLayout(root)
        if not layout.publish(
            dataset_id,
            {
                "raw.jsonl": raw_text,
                "bars.parquet": parquet,
                "manifest.json": canonical_json(manifest) + "\n",
                "manifest.sha256.json": manifest_sidecar,
            },
        ):
            raise Program002AcquisitionError("final staging dataset identity conflicts")
        path = layout.dataset(dataset_id) / "manifest.json"
        DatasetCatalog(layout.catalog).register(dict(manifest), path)
        if (
            not _manifest_bytes_valid(layout.dataset(dataset_id), manifest)
            or not DatasetService(layout).validate(dataset_id)["valid"]
        ):
            raise Program002AcquisitionError("final dataset staging validation failed")
    finally:
        shutil.rmtree(root)


def _segment_retrieval_timestamp(segments: Sequence[Mapping[str, Any]]) -> datetime:
    values = [
        evidence.get("retrieval_timestamp")
        for segment in segments
        for evidence in segment.get("request_evidence", [])
        if isinstance(evidence, Mapping)
    ]
    if not values or any(not isinstance(value, str) for value in values):
        raise Program002AcquisitionError("segment retrieval evidence is missing")
    return max(_time(value) for value in values)


def derive_volume_context_projection(
    bars: Sequence[OHLCVBar],
    *,
    source_dataset_id: str,
    source_dataset_fingerprint: str,
    source_dataset_normalized_fingerprint: str,
    plan_sha256: str | None = None,
    authority_sha256: str | None = None,
) -> Mapping[str, Any]:
    """Publishable volume-only context with no OHLC values or returns."""
    if (
        not source_dataset_id
        or not source_dataset_fingerprint
        or not source_dataset_normalized_fingerprint
    ):
        raise Program002AcquisitionError("volume context source identity is required")
    volumes: dict[tuple[str, str], int] = {}
    counts: dict[tuple[str, str], int] = {}
    for bar in bars:
        local = bar.timestamp.astimezone(_NY)
        if not (time(9, 30) <= local.time() <= time(11, 25)):
            continue
        key = (local.date().isoformat(), bar.symbol.value)
        volumes[key] = volumes.get(key, 0) + bar.volume
        counts[key] = counts.get(key, 0) + 1
    rows = tuple(
        {
            "session_date": session,
            "symbol": symbol,
            "cumulative_volume_0930_1130": volume,
            "source_dataset_id": source_dataset_id,
            "source_dataset_fingerprint": source_dataset_fingerprint,
            "source_dataset_normalized_fingerprint": source_dataset_normalized_fingerprint,
        }
        for (session, symbol), volume in sorted(volumes.items())
    )
    if not rows:
        raise Program002AcquisitionError("volume context projection has no rows")
    if any(count != 24 for count in counts.values()):
        raise Program002AcquisitionError(
            "volume context projection requires 24 bars per symbol/session"
        )
    artifact = {
        "schema_version": "program-002-volume-context-projection-v2",
        "rows": rows,
        "source_dataset_id": source_dataset_id,
        "source_dataset_fingerprint": source_dataset_fingerprint,
        "source_dataset_normalized_fingerprint": source_dataset_normalized_fingerprint,
        "plan_sha256": plan_sha256,
        "acquisition_authority_sha256": authority_sha256,
        "allowed_use": "same-clock volume context only; no target, benchmark, P&L, or gate",
    }
    return {**artifact, "projection_fingerprint": fingerprint(artifact)}


def publish_volume_context_projection(
    plan: Program002AcquisitionPlan, layout: StorageLayout, source_dataset_id: str
) -> tuple[Path, Mapping[str, Any], bool]:
    """Freeze the exact authorized context dataset as a volume-only projection."""
    manifest, bars = _load_reused_context_dataset(plan, layout, source_dataset_id)
    source_fingerprint = str(manifest["identity"]["fingerprint"])
    source_normalized_fingerprint = str(manifest["normalized_fingerprint"])
    artifact = derive_volume_context_projection(
        bars,
        source_dataset_id=source_dataset_id,
        source_dataset_fingerprint=source_fingerprint,
        source_dataset_normalized_fingerprint=source_normalized_fingerprint,
        plan_sha256=plan.sha256,
        authority_sha256=plan.authority.sha256,
    )
    _validate_context_projection_rows(
        artifact,
        plan,
        source_dataset_id,
        source_fingerprint,
        source_normalized_fingerprint,
    )
    identity = str(artifact["projection_fingerprint"])
    path = layout.reports / "program-002" / "context-projections" / f"{identity}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    contents = canonical_json(artifact) + "\n"
    sidecar = (
        canonical_json(
            {
                "projection_id": identity,
                "projection_sha256": hashlib.sha256(contents.encode()).hexdigest(),
            }
        )
        + "\n"
    )
    sidecar_path = path.with_suffix(".sha256.json")
    try:
        _publish_immutable_report(sidecar_path, sidecar)
    except FileExistsError:
        if sidecar_path.read_text(encoding="utf-8") != sidecar:
            raise Program002AcquisitionError(
                "existing context projection byte evidence conflicts"
            ) from None
    try:
        _publish_immutable_report(path, contents)
        created = True
    except FileExistsError:
        if path.read_text(encoding="utf-8") != contents:
            raise Program002AcquisitionError(
                "existing immutable context projection conflicts"
            ) from None
        created = False
    return path, artifact, created


def _load_reused_context_dataset(
    plan: Program002AcquisitionPlan,
    layout: StorageLayout,
    source_dataset_id: str,
) -> tuple[dict[str, Any], tuple[OHLCVBar, ...]]:
    bindings = _mapping(plan.authority.payload.get("bindings"), "acquisition authority bindings")
    binding = _mapping(bindings.get("reused_context_dataset"), "reused context dataset binding")
    if set(binding) != {
        "dataset_id",
        "manifest_sha256",
        "fingerprint",
        "normalized_fingerprint",
        "normalization_version",
        "plan_sha256",
        "role",
        "original_acquisition_authority_sha256",
        "allowed_use",
        "expected_rows",
        "disposition",
    } or binding.get("disposition") != (
        "reuse-exact-bytes-without-relabeling-mutation-or-reacquisition"
    ):
        raise Program002AcquisitionError("reused context dataset authority binding differs")
    if source_dataset_id != binding.get("dataset_id"):
        raise Program002AcquisitionError("reused context dataset differs")
    path = layout.dataset(source_dataset_id) / "manifest.json"
    try:
        raw = path.read_bytes()
        service = DatasetService(layout, read_only=True)
        manifest = service.catalog.get(source_dataset_id)
        bars = service.load_bars(source_dataset_id)
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise Program002AcquisitionError("reused context dataset validation failed") from error
    identity = _mapping(manifest.get("identity") if manifest else None, "context identity")
    program = _mapping(manifest.get("program_002") if manifest else None, "context provenance")
    processing = _mapping(program.get("processing"), "context processing")
    validation = _mapping(
        manifest.get("validation_evidence") if manifest else None, "context validation evidence"
    )
    if (
        hashlib.sha256(raw).hexdigest() != binding.get("manifest_sha256")
        or manifest is None
        or manifest.get("dataset_id") != source_dataset_id
        or manifest.get("manifest_schema") != "program-002-ohlcv-dataset-manifest-v1"
        or manifest.get("normalization_version") != binding.get("normalization_version")
        or manifest.get("normalized_fingerprint") != binding.get("normalized_fingerprint")
        or identity
        != {
            "dataset_id": source_dataset_id,
            "fingerprint": binding.get("fingerprint"),
        }
        or program.get("role") != binding.get("role")
        or program.get("plan_sha256") != binding.get("plan_sha256")
        or program.get("acquisition_authority_sha256")
        != binding.get("original_acquisition_authority_sha256")
        or program.get("allowed_use") != binding.get("allowed_use")
        or processing.get("normalization_version") != binding.get("normalization_version")
        or "program_002_normalization_version" in processing
        or validation.get("expected_rows") != binding.get("expected_rows")
        or validation.get("bar_count") != binding.get("expected_rows")
        or len(bars) != binding.get("expected_rows")
    ):
        raise Program002AcquisitionError("reused context dataset differs")
    return manifest, bars


def load_volume_context_projection(
    layout: StorageLayout,
    identity: str,
    source_dataset_id: str,
    plan: Program002AcquisitionPlan,
) -> Mapping[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", identity):
        raise Program002AcquisitionError("volume context projection identity is invalid")
    path = layout.reports / "program-002" / "context-projections" / f"{identity}.json"
    try:
        artifact = _json(path.read_bytes())
    except OSError as error:
        raise Program002AcquisitionError("volume context projection is missing") from error
    try:
        sidecar = _json(path.with_suffix(".sha256.json").read_bytes())
    except OSError as error:
        raise Program002AcquisitionError("volume context projection sidecar is missing") from error
    unsigned = dict(artifact)
    fingerprint_value = unsigned.pop("projection_fingerprint", None)
    if (
        fingerprint_value != fingerprint(unsigned)
        or fingerprint_value != identity
        or artifact.get("source_dataset_id") != source_dataset_id
        or artifact.get("plan_sha256") != plan.sha256
        or artifact.get("acquisition_authority_sha256") != plan.authority.sha256
        or artifact.get("allowed_use")
        != "same-clock volume context only; no target, benchmark, P&L, or gate"
    ):
        raise Program002AcquisitionError("volume context projection integrity differs")
    if sidecar != {
        "projection_id": identity,
        "projection_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }:
        raise Program002AcquisitionError("volume context projection byte evidence differs")
    manifest, bars = _load_reused_context_dataset(plan, layout, source_dataset_id)
    source_fingerprint = str(manifest["identity"]["fingerprint"])
    source_normalized_fingerprint = str(manifest["normalized_fingerprint"])
    if (
        artifact.get("source_dataset_fingerprint") != source_fingerprint
        or artifact.get("source_dataset_normalized_fingerprint") != source_normalized_fingerprint
    ):
        raise Program002AcquisitionError("volume context source dataset differs")
    _validate_context_projection_rows(
        artifact,
        plan,
        source_dataset_id,
        source_fingerprint,
        source_normalized_fingerprint,
    )
    expected = derive_volume_context_projection(
        bars,
        source_dataset_id=source_dataset_id,
        source_dataset_fingerprint=source_fingerprint,
        source_dataset_normalized_fingerprint=source_normalized_fingerprint,
        plan_sha256=plan.sha256,
        authority_sha256=plan.authority.sha256,
    )
    if canonicalize(artifact) != canonicalize(expected):
        raise Program002AcquisitionError("volume context projection values differ")
    return artifact


def _validate_context_projection_rows(
    artifact: Mapping[str, Any],
    plan: Program002AcquisitionPlan,
    source_dataset_id: str,
    source_dataset_fingerprint: str,
    source_dataset_normalized_fingerprint: str,
) -> None:
    rows = artifact.get("rows")
    context = _role(plan, "exposed-context-only")
    if not isinstance(rows, list | tuple) or len(rows) != int(context["xnys_sessions"]) * len(
        _symbols(plan)
    ):
        raise Program002AcquisitionError("volume context projection coverage differs")
    expected_keys = {
        "session_date",
        "symbol",
        "cumulative_volume_0930_1130",
        "source_dataset_id",
        "source_dataset_fingerprint",
        "source_dataset_normalized_fingerprint",
    }
    keys: set[tuple[str, str]] = set()
    for row in rows:
        if (
            not isinstance(row, Mapping)
            or set(row) != expected_keys
            or row.get("symbol") not in _symbols(plan)
            or row.get("source_dataset_id") != source_dataset_id
            or row.get("source_dataset_fingerprint") != source_dataset_fingerprint
            or row.get("source_dataset_normalized_fingerprint")
            != source_dataset_normalized_fingerprint
            or isinstance(row.get("cumulative_volume_0930_1130"), bool)
            or not isinstance(row.get("cumulative_volume_0930_1130"), int)
            or row["cumulative_volume_0930_1130"] < 0
        ):
            raise Program002AcquisitionError("volume context projection rows differ")
        try:
            session = date.fromisoformat(str(row["session_date"]))
        except ValueError as error:
            raise Program002AcquisitionError("volume context projection rows differ") from error
        keys.add((session.isoformat(), str(row["symbol"])))
    sessions = {session for session, _ in keys}
    if len(keys) != len(rows) or len(sessions) != int(context["xnys_sessions"]):
        raise Program002AcquisitionError("volume context projection coverage differs")


def sample_quote_window(
    records: Sequence[Mapping[str, Any]], symbol: str, start: datetime
) -> tuple[Decimal, ...]:
    return _quote_window_evidence(records, symbol, start)[0]


def _quote_window_evidence(
    records: Sequence[Mapping[str, Any]], symbol: str, start: datetime
) -> tuple[tuple[Decimal, ...], Mapping[str, int]]:
    raw = [record for record in records if record.get("symbol") == symbol]
    seen: set[str] = set()
    duplicates = 0
    changed_same_timestamp = 0
    by_timestamp: dict[datetime, str] = {}
    malformed = 0
    unparseable_timestamp = False
    updates: list[tuple[datetime, tuple[datetime, Decimal, int, Decimal, int] | None]] = []
    prior: datetime | None = None
    for record in raw:
        signature = canonical_json(record)
        if signature in seen:
            duplicates += 1
            continue
        seen.add(signature)
        try:
            timestamp = _time(record.get("t"))
        except (KeyError, TypeError, ValueError, Program002AcquisitionError):
            malformed += 1
            unparseable_timestamp = True
            continue
        prior_signature = by_timestamp.get(timestamp)
        if prior_signature is not None and prior_signature != signature:
            changed_same_timestamp += 1
        by_timestamp[timestamp] = signature
        if prior is not None and timestamp < prior:
            raise Program002AcquisitionError("provider quote order is invalid")
        prior = timestamp
        try:
            value = _quote(record)
        except Program002AcquisitionError:
            malformed += 1
            updates.append((timestamp, None))
            continue
        updates.append((timestamp, value))
    values: list[Decimal] = []
    counts = {
        "missing": 0,
        "stale": 0,
        "crossed": 0,
        "one_sided": 0,
        "zero_size": 0,
        "exact_duplicates": duplicates,
        "changed_same_timestamp_updates": changed_same_timestamp,
        "malformed": malformed,
    }
    index = 0
    latest: tuple[datetime, Decimal, int, Decimal, int] | None = None
    for second in range(60):
        instant = start + timedelta(seconds=second)
        while index < len(updates) and updates[index][0] < instant:
            latest = updates[index][1]
            index += 1
        if latest is None:
            counts["missing"] += 1
            continue
        timestamp, bid, bid_size, ask, ask_size = latest
        if instant - timestamp > timedelta(seconds=5):
            counts["stale"] += 1
        elif bid <= 0 or ask <= 0:
            counts["one_sided"] += 1
        elif bid_size <= 0 or ask_size <= 0:
            counts["zero_size"] += 1
        elif ask < bid:
            counts["crossed"] += 1
        else:
            values.append(
                Decimal("10000") * ((ask - bid) / Decimal(2)) / ((ask + bid) / Decimal(2))
            )
    if len(values) < 57:
        raise Program002AcquisitionError("quote window coverage is below 57/60")
    if unparseable_timestamp:
        raise Program002AcquisitionError(
            "quote timestamp is malformed and ordering is indeterminate"
        )
    return tuple(values), counts


def derive_quote_costs(
    plan: Program002AcquisitionPlan, segments: Sequence[AcquiredSegment]
) -> Mapping[str, Any]:
    if tuple(item.segment for item in segments) != quote_segments(plan):
        raise Program002AcquisitionError("quote segments differ from frozen plan")
    values: dict[str, list[Decimal]] = {symbol: [] for symbol in _symbols(plan)}
    windows: list[Mapping[str, Any]] = []
    for item in segments:
        start = _time(item.segment.params["start"]) + timedelta(seconds=5)
        coverage: dict[str, int] = {}
        dispositions: dict[str, Mapping[str, int]] = {}
        samples: dict[str, tuple[Decimal, ...]] = {}
        for symbol in values:
            observations, counts = _quote_window_evidence(item.raw_records, symbol, start)
            values[symbol].extend(observations)
            coverage[symbol] = len(observations)
            dispositions[symbol] = counts
            samples[symbol] = observations
        windows.append(
            {
                "request": item.segment.url(),
                "raw_page_sha256_values": [page.sha256 for page in item.pages],
                "raw_record_fingerprint": fingerprint(item.raw_records),
                "coverage": coverage,
                "spread": {
                    symbol: {"minimum": min(samples[symbol]), "maximum": max(samples[symbol])}
                    for symbol in samples
                },
                "eligible_spreads": samples,
                "sampled_observation_fingerprint": fingerprint(samples),
                "dispositions": dispositions,
                "causal_selection": "latest-unique-strictly-prior-within-five-seconds",
            }
        )
    percentiles = {symbol: _percentile(value) for symbol, value in values.items()}
    repository = plan.path.parents[2]
    reviewed = load_intraday_execution_cost_model(repository)
    fees = {
        "source_cost_model_id": reviewed.payload["cost_model_id"],
        "source_cost_model_sha256": reviewed.sha256,
        "source_cost_model_fingerprint": reviewed.model_fingerprint,
        "regulatory_fees": reviewed.payload["regulatory_fees"],
    }
    artifact: dict[str, Any] = {
        "schema_version": "program-002-quote-cost-artifact-v1",
        "plan_sha256": plan.sha256,
        "acquisition_authority_sha256": plan.authority.sha256,
        "feed": "sip",
        "symbols": percentiles,
        "windows": windows,
        "window_distributions": _window_distributions(windows, plan),
        "regulatory_fee_model": fees,
        "regulatory_fee_model_fingerprint": fingerprint(fees),
        "scenarios": {
            name: {symbol: _up(value[key]) for symbol, value in percentiles.items()}
            for name, key in (("Normal", "p75"), ("Stress_A", "p95"), ("Stress_B", "p99"))
        },
    }
    artifact["scenarios"].update(
        {
            "Normal_delay_2": artifact["scenarios"]["Normal"],
            "Normal_delay_3": artifact["scenarios"]["Normal"],
            "zero_cost_diagnostic": {symbol: Decimal("0") for symbol in _symbols(plan)},
        }
    )
    artifact["scenario_metadata"] = {
        "Normal": {"percentile": "p75", "execution_delay_bars": 1, "regulatory_fees": True},
        "Stress_A": {"percentile": "p95", "execution_delay_bars": 2, "regulatory_fees": True},
        "Stress_B": {"percentile": "p99", "execution_delay_bars": 3, "regulatory_fees": True},
        "Normal_delay_2": {
            "percentile": "p75",
            "execution_delay_bars": 2,
            "regulatory_fees": True,
        },
        "Normal_delay_3": {
            "percentile": "p75",
            "execution_delay_bars": 3,
            "regulatory_fees": True,
        },
        "zero_cost_diagnostic": {
            "percentile": None,
            "execution_delay_bars": 1,
            "regulatory_fees": False,
        },
    }
    artifact["quote_artifact_fingerprint"] = fingerprint(artifact)
    return artifact


def _window_distributions(
    windows: Sequence[Mapping[str, Any]], plan: Program002AcquisitionPlan
) -> Mapping[str, Any]:
    values: dict[str, list[int]] = {symbol: [] for symbol in _symbols(plan)}
    by_clock: dict[str, dict[str, list[int]]] = {}
    by_month: dict[str, dict[str, list[int]]] = {}
    spreads: dict[str, list[Decimal]] = {symbol: [] for symbol in values}
    spread_by_clock: dict[str, dict[str, list[Decimal]]] = {}
    spread_by_month: dict[str, dict[str, list[Decimal]]] = {}
    for window in windows:
        coverage = _mapping(window.get("coverage"), "quote coverage")
        sample_values = _mapping(window.get("eligible_spreads"), "eligible quote spreads")
        query = dict(parse_qsl(urlparse(str(window["request"])).query, keep_blank_values=True))
        clock_point = _time(query["start"]) + timedelta(seconds=35)
        clock = clock_point.astimezone(_NY).strftime("%H:%M")
        month = clock_point.astimezone(_NY).strftime("%Y-%m")
        clock_values = by_clock.setdefault(clock, {symbol: [] for symbol in values})
        month_values = by_month.setdefault(month, {symbol: [] for symbol in values})
        clock_spreads = spread_by_clock.setdefault(clock, {symbol: [] for symbol in values})
        month_spreads = spread_by_month.setdefault(month, {symbol: [] for symbol in values})
        for symbol in values:
            count = int(coverage[symbol])
            values[symbol].append(count)
            clock_values[symbol].append(count)
            month_values[symbol].append(count)
            samples = sample_values.get(symbol)
            if not isinstance(samples, list | tuple):
                raise Program002AcquisitionError("eligible quote spreads differ")
            spreads[symbol].extend(Decimal(str(value)) for value in samples)
            clock_spreads[symbol].extend(Decimal(str(value)) for value in samples)
            month_spreads[symbol].extend(Decimal(str(value)) for value in samples)

    def summary(items: Mapping[str, list[int]]) -> Mapping[str, Mapping[str, int]]:
        return {
            symbol: {
                "minimum": min(counts),
                "maximum": max(counts),
                "below_60": sum(count < 60 for count in counts),
                "count": len(counts),
            }
            for symbol, counts in items.items()
        }

    return {
        "coverage": summary(values),
        "by_clock": {clock: summary(items) for clock, items in by_clock.items()},
        "by_month": {month: summary(items) for month, items in by_month.items()},
        "spread": {symbol: _spread_distribution(items) for symbol, items in spreads.items()},
        "spread_by_clock": {
            clock: {symbol: _spread_distribution(items) for symbol, items in grouped.items()}
            for clock, grouped in spread_by_clock.items()
        },
        "spread_by_month": {
            month: {symbol: _spread_distribution(items) for symbol, items in grouped.items()}
            for month, grouped in spread_by_month.items()
        },
        "window_count": len(windows),
    }


def _spread_distribution(items: Sequence[Decimal]) -> Mapping[str, Decimal | int]:
    p99 = _percentile(items)["p99"]
    return {
        "minimum": min(items),
        "maximum": max(items),
        "p99": p99,
        "extreme_count": sum(item >= p99 for item in items),
    }


def load_quote_segments_from_artifacts(
    plan: Program002AcquisitionPlan,
    layout: StorageLayout,
    segment_ids: Sequence[str],
    *,
    acquisition_attempt_id: str,
) -> tuple[AcquiredSegment, ...]:
    """Load all calibration windows from verified immutable quote artifacts."""
    segments = quote_segments(plan)
    expected_ids = quote_segment_ids(plan, acquisition_attempt_id)
    if tuple(segment_ids) != expected_ids:
        raise Program002AcquisitionError("quote segment identities differ from frozen plan")
    return tuple(
        _load_segment_artifact(
            layout,
            identity,
            segment,
            "program-002-quote-window-v1",
            plan_sha256=plan.sha256,
            authority_sha256=plan.authority.sha256,
        )
        for identity, segment in zip(segment_ids, segments, strict=True)
    )


def derive_quote_costs_from_artifacts(
    plan: Program002AcquisitionPlan,
    layout: StorageLayout,
    segment_ids: Sequence[str],
    *,
    acquisition_attempt_id: str,
) -> Mapping[str, Any]:
    return derive_quote_costs(
        plan,
        load_quote_segments_from_artifacts(
            plan, layout, segment_ids, acquisition_attempt_id=acquisition_attempt_id
        ),
    )


def publish_quote_costs(
    layout: StorageLayout,
    artifact: Mapping[str, Any],
    plan: Program002AcquisitionPlan,
    *,
    acquisition_attempt_id: str,
) -> tuple[Path, bool]:
    if artifact.get("schema_version") != "program-002-quote-cost-artifact-v1":
        raise Program002AcquisitionError("quote cost artifact schema differs")
    identity = artifact.get("quote_artifact_fingerprint")
    unsigned = dict(artifact)
    unsigned.pop("quote_artifact_fingerprint", None)
    symbols, windows, scenarios = (
        artifact.get("symbols"),
        artifact.get("windows"),
        artifact.get("scenarios"),
    )
    expected_symbols = set(_symbols(plan))
    expected_requests = [segment.url() for segment in quote_segments(plan)]
    reviewed = load_intraday_execution_cost_model(plan.path.parents[2])
    source_segments = load_quote_segments_from_artifacts(
        plan,
        layout,
        quote_segment_ids(plan, acquisition_attempt_id),
        acquisition_attempt_id=acquisition_attempt_id,
    )
    if (
        not isinstance(identity, str)
        or identity != fingerprint(unsigned)
        or artifact.get("plan_sha256") != plan.sha256
        or artifact.get("acquisition_authority_sha256") != plan.authority.sha256
        or artifact.get("feed") != "sip"
        or not isinstance(symbols, Mapping)
        or set(symbols) != expected_symbols
        or any(
            not isinstance(value, Mapping)
            or set(value) != {"p50", "p75", "p90", "p95", "p99"}
            or any(
                not isinstance(item, Decimal) or not item.is_finite() or item < 0
                for item in value.values()
            )
            for value in symbols.values()
        )
        or not isinstance(windows, list)
        or len(windows) != 657
        or [item.get("request") if isinstance(item, Mapping) else None for item in windows]
        != expected_requests
        or not isinstance(scenarios, Mapping)
        or set(scenarios)
        != {
            "Normal",
            "Stress_A",
            "Stress_B",
            "Normal_delay_2",
            "Normal_delay_3",
            "zero_cost_diagnostic",
        }
        or any(
            not isinstance(item, Mapping)
            or set(item.get("coverage", {})) != expected_symbols
            or any(
                not isinstance(count, int) or count < 57 or count > 60
                for count in item["coverage"].values()
            )
            or set(item.get("dispositions", {})) != expected_symbols
            for item in windows
        )
        or artifact.get("regulatory_fee_model_fingerprint")
        != fingerprint(artifact.get("regulatory_fee_model"))
        or not isinstance(artifact.get("regulatory_fee_model"), Mapping)
        or artifact["regulatory_fee_model"].get("source_cost_model_id")
        != reviewed.payload["cost_model_id"]
        or artifact["regulatory_fee_model"].get("source_cost_model_sha256") != reviewed.sha256
        or artifact["regulatory_fee_model"].get("source_cost_model_fingerprint")
        != reviewed.model_fingerprint
        or artifact["regulatory_fee_model"].get("regulatory_fees")
        != reviewed.payload["regulatory_fees"]
        or not _quote_window_evidence_matches(plan, windows, source_segments)
        or artifact.get("window_distributions") != _window_distributions(windows, plan)
        or not _quote_scenarios_match(symbols, scenarios)
        or artifact.get("scenario_metadata")
        != {
            "Normal": {"percentile": "p75", "execution_delay_bars": 1, "regulatory_fees": True},
            "Stress_A": {"percentile": "p95", "execution_delay_bars": 2, "regulatory_fees": True},
            "Stress_B": {"percentile": "p99", "execution_delay_bars": 3, "regulatory_fees": True},
            "Normal_delay_2": {
                "percentile": "p75",
                "execution_delay_bars": 2,
                "regulatory_fees": True,
            },
            "Normal_delay_3": {
                "percentile": "p75",
                "execution_delay_bars": 3,
                "regulatory_fees": True,
            },
            "zero_cost_diagnostic": {
                "percentile": None,
                "execution_delay_bars": 1,
                "regulatory_fees": False,
            },
        }
    ):
        raise Program002AcquisitionError("quote cost artifact fingerprint differs")
    path = layout.reports / "program-002" / f"{identity}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    contents = canonical_json(artifact) + "\n"
    sidecar = (
        canonical_json(
            {"quote_artifact_id": identity, "sha256": hashlib.sha256(contents.encode()).hexdigest()}
        )
        + "\n"
    )
    try:
        _publish_immutable_report(path, contents)
        _publish_immutable_report(path.with_suffix(".sha256.json"), sidecar)
    except FileExistsError as error:
        if path.read_text(encoding="utf-8") != contents:
            raise Program002AcquisitionError(
                "existing immutable quote artifact conflicts"
            ) from error
        if not path.with_suffix(".sha256.json").exists():
            _publish_immutable_report(path.with_suffix(".sha256.json"), sidecar)
        elif path.with_suffix(".sha256.json").read_text(encoding="utf-8") != sidecar:
            raise Program002AcquisitionError("quote artifact byte evidence conflicts") from error
        return path, False
    return path, True


def _quote_window_evidence_matches(
    plan: Program002AcquisitionPlan,
    windows: object,
    segments: Sequence[AcquiredSegment],
) -> bool:
    if not isinstance(windows, list) or len(windows) != len(segments):
        return False
    expected_disposition_keys = {
        "missing",
        "stale",
        "crossed",
        "one_sided",
        "zero_size",
        "exact_duplicates",
        "changed_same_timestamp_updates",
        "malformed",
    }
    for window, segment in zip(windows, segments, strict=True):
        if not isinstance(window, Mapping):
            return False
        required = {
            "request",
            "raw_page_sha256_values",
            "raw_record_fingerprint",
            "coverage",
            "spread",
            "eligible_spreads",
            "sampled_observation_fingerprint",
            "dispositions",
            "causal_selection",
        }
        if set(window) != required or window.get("request") != segment.segment.url():
            return False
        if window.get("raw_page_sha256_values") != [page.sha256 for page in segment.pages]:
            return False
        if window.get("raw_record_fingerprint") != fingerprint(segment.raw_records):
            return False
        if window.get("causal_selection") != "latest-unique-strictly-prior-within-five-seconds":
            return False
        start = _time(segment.segment.params["start"]) + timedelta(seconds=5)
        samples: dict[str, tuple[Decimal, ...]] = {}
        dispositions: dict[str, Mapping[str, int]] = {}
        for symbol in _symbols(plan):
            try:
                samples[symbol], dispositions[symbol] = _quote_window_evidence(
                    segment.raw_records, symbol, start
                )
            except Program002AcquisitionError:
                return False
        if (
            window.get("coverage") != {symbol: len(values) for symbol, values in samples.items()}
            or window.get("eligible_spreads") != samples
            or window.get("sampled_observation_fingerprint") != fingerprint(samples)
            or window.get("dispositions") != dispositions
            or any(set(value) != expected_disposition_keys for value in dispositions.values())
            or window.get("spread")
            != {
                symbol: {"minimum": min(values), "maximum": max(values)}
                for symbol, values in samples.items()
            }
        ):
            return False
    return True


def load_program_002_quote_cost_artifact(
    layout: StorageLayout,
    identity: str,
    plan: Program002AcquisitionPlan,
    *,
    acquisition_attempt_id: str,
) -> Mapping[str, Any]:
    path = layout.reports / "program-002" / f"{identity}.json"
    try:
        contents = path.read_bytes()
        artifact = _json(contents)
    except OSError as error:
        raise Program002AcquisitionError("stored quote cost artifact is missing") from error
    try:
        sidecar = _json(path.with_suffix(".sha256.json").read_bytes())
    except OSError as error:
        raise Program002AcquisitionError(
            "stored quote cost artifact byte evidence is missing"
        ) from error
    if sidecar != {
        "quote_artifact_id": identity,
        "sha256": hashlib.sha256(contents).hexdigest(),
    }:
        raise Program002AcquisitionError("stored quote cost artifact byte evidence differs")
    decoded = _decode_quote_artifact_decimals(dict(artifact))
    if decoded.get("quote_artifact_fingerprint") != identity:
        raise Program002AcquisitionError("stored quote cost artifact identity differs")
    publish_quote_costs(layout, decoded, plan, acquisition_attempt_id=acquisition_attempt_id)
    return decoded


def _decode_quote_artifact_decimals(artifact: dict[str, Any]) -> dict[str, Any]:
    def decimal_map(value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        return {key: Decimal(str(item)) for key, item in value.items()}

    artifact["symbols"] = {
        symbol: decimal_map(value)
        for symbol, value in _mapping(artifact.get("symbols"), "symbols").items()
    }
    artifact["scenarios"] = {
        scenario: decimal_map(value)
        for scenario, value in _mapping(artifact.get("scenarios"), "scenarios").items()
    }
    windows = artifact.get("windows")
    if isinstance(windows, list):
        for window in windows:
            if not isinstance(window, dict):
                continue
            eligible = window.get("eligible_spreads")
            if isinstance(eligible, dict):
                window["eligible_spreads"] = {
                    symbol: tuple(Decimal(str(item)) for item in items)
                    for symbol, items in eligible.items()
                    if isinstance(items, list)
                }
            spread = window.get("spread")
            if isinstance(spread, dict):
                window["spread"] = {symbol: decimal_map(item) for symbol, item in spread.items()}
    distributions = artifact.get("window_distributions")
    if isinstance(distributions, dict):
        for key in ("spread", "spread_by_clock", "spread_by_month"):
            if isinstance(distributions.get(key), dict):
                distributions[key] = _decode_spread_distributions(distributions[key])
    return artifact


def _decode_spread_distributions(value: Mapping[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, dict) and {"minimum", "maximum", "p99"} <= set(item):
            output[key] = {
                name: Decimal(str(number)) if name in {"minimum", "maximum", "p99"} else number
                for name, number in item.items()
            }
        elif isinstance(item, dict):
            output[key] = _decode_spread_distributions(item)
        else:
            output[key] = item
    return output


def _publish_immutable_report(path: Path, contents: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            file.write(contents)
            file.flush()
            os.fsync(file.fileno())
        os.link(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _quote_scenarios_match(symbols: Mapping[str, Any], scenarios: Mapping[str, Any]) -> bool:
    normal = scenarios.get("Normal")
    if not isinstance(normal, Mapping):
        return False
    expected_symbols = set(symbols)
    expected = {
        "Normal": "p75",
        "Stress_A": "p95",
        "Stress_B": "p99",
        "Normal_delay_2": "p75",
        "Normal_delay_3": "p75",
    }
    for scenario, percentile in expected.items():
        value = scenarios.get(scenario)
        if not isinstance(value, Mapping) or set(value) != expected_symbols:
            return False
        if any(value[symbol] != _up(symbols[symbol][percentile]) for symbol in expected_symbols):
            return False
    zero = scenarios.get("zero_cost_diagnostic")
    return (
        isinstance(zero, Mapping)
        and set(zero) == expected_symbols
        and all(value == Decimal("0") for value in zero.values())
    )


def _bar_segment(plan: Program002AcquisitionPlan, start: date, end: date) -> RequestSegment:
    points = expected_bar_timestamps(
        datetime.combine(start, time(0), UTC),
        datetime.combine(end, time(23, 59), UTC),
        Timeframe.FIVE_MINUTES,
    )
    if not points:
        raise Program002AcquisitionError("monthly segment contains no XNYS bars")
    return RequestSegment("bars", _BARS, _params(plan, points[0], points[-1], "5Min"), 100)


def _quote_segment(
    plan: Program002AcquisitionPlan, session: object, fill: object
) -> RequestSegment:
    point = datetime.combine(
        date.fromisoformat(str(session)), time.fromisoformat(str(fill)), _NY
    ).astimezone(UTC)
    return RequestSegment(
        "quotes",
        _QUOTES,
        _params(plan, point - timedelta(seconds=35), point + timedelta(seconds=30), None),
        100,
    )


def _params(
    plan: Program002AcquisitionPlan, start: datetime, end: datetime, timeframe: str | None
) -> dict[str, str]:
    output = {
        "symbols": ",".join(_symbols(plan)),
        "start": _iso(start),
        "end": _iso(end),
        "feed": "sip",
        "limit": "10000",
        "sort": "asc",
    }
    if timeframe:
        output.update({"timeframe": timeframe, "adjustment": "all"})
    return output


def _request(
    url: str,
    transport: Callable[[str], HttpPage],
    pace: Callable[[], None],
    retryable: Callable[[int], bool],
    wait: Callable[[float], None],
    wall_clock: Callable[[], float],
    attempt_limit: int,
    observe_page: Callable[[HttpPage], None] | None = None,
) -> HttpPage:
    attempts: list[Mapping[str, Any]] = []
    for attempt in range(1, attempt_limit + 1):
        try:
            pace()
            page = transport(url)
        except HTTPError as error:
            try:
                body = error.read(8193)
            except OSError:
                body = b""
            page = HttpPage(
                error.code,
                body[:8192],
                dict(error.headers.items()) if error.headers else {},
                captured_body_truncated=len(body) == 8193,
            )
        except (URLError, TimeoutError, ConnectionResetError) as error:
            delay = float(2 ** (attempt - 1)) if attempt < attempt_limit else None
            attempts.append(
                _http_attempt(
                    url,
                    attempt,
                    transport_error=type(error).__name__,
                    retry_delay=delay,
                    disposition="retry" if delay is not None else "exhausted",
                )
            )
            if delay is not None:
                wait(delay)
                continue
            _raise_request_error("retryable network failure exhausted", attempts)
        if observe_page is not None:
            observe_page(page)
        if page.status == 200:
            attempts.append(_http_attempt(url, attempt, page=page, disposition="accepted"))
            if isinstance(pace, RequestPacer):
                pace.update_server_limit(page.headers, wall_clock)
            return HttpPage(
                page.status,
                page.body,
                page.headers,
                tuple(attempts),
                page.captured_body_truncated,
            )
        if not retryable(page.status):
            attempts.append(_http_attempt(url, attempt, page=page, disposition="rejected"))
            _raise_request_error(f"nonretryable HTTP status {page.status}", attempts, page)
        if attempt < attempt_limit:
            headers = {key.lower(): value for key, value in page.headers.items()}
            retry_after = headers.get("retry-after")
            reset = headers.get("x-ratelimit-reset")
            retry_delay = _retry_after_delay(retry_after, wall_clock)
            try:
                reset_value = float(reset) if reset else 0.0
                reset_delay = (
                    max(0.0, reset_value - wall_clock()) if reset_value > wall_clock() else 0.0
                )
            except ValueError:
                reset_delay = 0.0
            delay = max(float(2 ** (attempt - 1)), retry_delay, reset_delay)
            attempts.append(
                _http_attempt(url, attempt, page=page, retry_delay=delay, disposition="retry")
            )
            wait(delay)
            continue
        attempts.append(_http_attempt(url, attempt, page=page, disposition="exhausted"))
        _raise_request_error("retryable HTTP status exhausted", attempts, page)
    raise AssertionError("unreachable")


def _http_attempt(
    url: str,
    number: int,
    *,
    page: HttpPage | None = None,
    transport_error: str | None = None,
    retry_delay: float | None = None,
    disposition: str,
) -> Mapping[str, Any]:
    body = page.body if page is not None else b""
    return {
        "request_url": url,
        "retrieval_timestamp": _iso(datetime.now(UTC)),
        "attempt": number,
        "status": page.status if page is not None else None,
        "transport_error": transport_error,
        "selected_headers": {
            key: value
            for key, value in (page.headers.items() if page is not None else ())
            if key.lower()
            in {
                "retry-after",
                "x-ratelimit-reset",
                "x-ratelimit-remaining",
                "x-ratelimit-limit",
                "x-request-id",
            }
        },
        "captured_body_sha256": hashlib.sha256(body).hexdigest() if page is not None else None,
        "body_hex": body[:8192].hex() if page is not None and body else None,
        "captured_body_length": len(body) if page is not None else 0,
        "captured_body_truncated": page.captured_body_truncated if page is not None else False,
        "retry_delay_seconds": Decimal(str(retry_delay)) if retry_delay is not None else None,
        "disposition": disposition,
    }


def _raise_request_error(
    message: str, attempts: Sequence[Mapping[str, Any]], page: HttpPage | None = None
) -> None:
    failure = Program002AcquisitionError(message)
    failure.page = page  # type: ignore[attr-defined]
    failure.http_attempts = tuple(attempts)  # type: ignore[attr-defined]
    raise failure


def _retry_after_delay(value: str | None, wall_clock: Callable[[], float]) -> float:
    if not value:
        return 0.0
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return 0.0
        if parsed.tzinfo is None:
            return 0.0
        return max(0.0, parsed.timestamp() - wall_clock())


def _bar(raw: Mapping[str, Any]) -> dict[str, Any]:
    required = {"symbol", "t", "o", "h", "l", "c", "v"}
    if required - set(raw):
        raise Program002AcquisitionError("provider bar is missing fields")
    output = {
        "symbol": raw["symbol"],
        "timestamp": raw["t"],
        "open": raw["o"],
        "high": raw["h"],
        "low": raw["l"],
        "close": raw["c"],
        "volume": raw["v"],
    }
    try:
        OHLCVBar.from_record(output)
    except (ArithmeticError, TypeError, ValueError) as error:
        raise Program002AcquisitionError("provider bar is malformed") from error
    return output


def _require_bar_in_segment(raw: Mapping[str, Any], segment: RequestSegment) -> datetime:
    timestamp = _time(raw["t"])
    start, end = _time(segment.params["start"]), _time(segment.params["end"])
    if timestamp < start or timestamp > end:
        raise Program002AcquisitionError("provider bar is outside its authorized segment")
    return timestamp


def _normalized_bar(raw: Mapping[str, Any], segment: RequestSegment) -> dict[str, Any] | None:
    parsed = _bar(raw)
    timestamp = _require_bar_in_segment(raw, segment)
    return (
        parsed
        if timestamp in _segment_bar_opens(segment.params["start"], segment.params["end"])
        else None
    )


@lru_cache(maxsize=128)
def _segment_bar_opens(start: str, end: str) -> frozenset[datetime]:
    return frozenset(expected_bar_timestamps(_time(start), _time(end), Timeframe.FIVE_MINUTES))


def _require_quote_in_segment(raw: Mapping[str, Any], segment: RequestSegment) -> None:
    try:
        timestamp = _time(raw["t"])
    except (KeyError, TypeError, ValueError, Program002AcquisitionError):
        # Retain malformed records for the calibration disposition evidence.
        return
    start, end = _time(segment.params["start"]), _time(segment.params["end"])
    if timestamp < start or timestamp > end:
        raise Program002AcquisitionError("provider quote is outside its authorized window")


def _quote(raw: Mapping[str, Any]) -> tuple[datetime, Decimal, int, Decimal, int]:
    required = {"symbol", "t", "bp", "bs", "ap", "as"}
    if required - set(raw):
        raise Program002AcquisitionError("provider quote is missing fields")
    try:
        output = (
            _time(raw["t"]),
            Decimal(str(raw["bp"])),
            raw["bs"],
            Decimal(str(raw["ap"])),
            raw["as"],
        )
    except (ArithmeticError, TypeError, ValueError) as error:
        raise Program002AcquisitionError("provider quote is malformed") from error
    if (
        not output[1].is_finite()
        or not output[3].is_finite()
        or any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0
            for item in (output[2], output[4])
        )
    ):
        raise Program002AcquisitionError("provider quote is malformed")
    return output


def _quotes(
    records: Sequence[Mapping[str, Any]], symbol: str
) -> tuple[tuple[datetime, Decimal, int, Decimal, int], ...]:
    seen: set[str] = set()
    output = []
    prior: datetime | None = None
    for raw in records:
        if raw.get("symbol") != symbol:
            continue
        value = _quote(raw)
        if prior is not None and value[0] < prior:
            raise Program002AcquisitionError("provider quote order is invalid")
        prior = value[0]
        signature = canonical_json(raw)
        if signature not in seen:
            seen.add(signature)
            output.append(value)
    if not output:
        raise Program002AcquisitionError("quote response omitted requested symbol")
    return tuple(output)


def _percentile(values: Sequence[Decimal]) -> Mapping[str, Decimal]:
    if not values:
        raise Program002AcquisitionError("quote distribution is empty")
    ordered = sorted(values)
    return {
        name: ordered[
            max(1, int((Decimal(p) * len(ordered)).to_integral_value(rounding=ROUND_CEILING))) - 1
        ]
        for name, p in (
            ("p50", ".50"),
            ("p75", ".75"),
            ("p90", ".90"),
            ("p95", ".95"),
            ("p99", ".99"),
        )
    }


def _up(value: Decimal) -> Decimal:
    return (value * 100).to_integral_value(rounding=ROUND_CEILING) / 100


def _preflight(values: Sequence[OHLCVBar]) -> None:
    groups: dict[str, list[OHLCVBar]] = {}
    for item in values:
        groups.setdefault(item.symbol.value, []).append(item)
    for rows in groups.values():
        for index in range(0, len(rows), 6):
            group = rows[index : index + 6]
            if len(group) != 6 or any(
                right.timestamp - left.timestamp != timedelta(minutes=5)
                for left, right in zip(group, group[1:], strict=False)
            ):
                raise Program002AcquisitionError("30-minute structural preflight failed")


def _role(plan: Program002AcquisitionPlan, role: str) -> Mapping[str, Any]:
    data = _mapping(plan.payload.get("data_classes"), "data classes")
    exposed = _mapping(data.get("A_exposed_research_and_development"), "exposed").get("datasets")
    context = _mapping(data.get("B_context_only"), "context").get("exposed_dataset")
    for value in [*(exposed if isinstance(exposed, list) else []), context]:
        if isinstance(value, dict) and value.get("role") == role:
            return value
    raise Program002AcquisitionError("unrecognized or protected Program 002 dataset role")


def _symbols(plan: Program002AcquisitionPlan) -> tuple[str, ...]:
    values = _mapping(plan.payload.get("universe"), "universe").get("symbols")
    if (
        not isinstance(values, list)
        or len(values) != 13
        or any(not isinstance(item, str) for item in values)
    ):
        raise Program002AcquisitionError("Program 002 symbols differ")
    return tuple(values)


def _months(dataset: Mapping[str, Any]) -> tuple[tuple[date, date], ...]:
    first, last = (
        date.fromisoformat(str(dataset["start_date"])),
        date.fromisoformat(str(dataset["end_date"])),
    )
    cursor = first.replace(day=1)
    output = []
    while cursor <= last:
        following = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        output.append((max(first, cursor), min(last, following - timedelta(days=1))))
        cursor = following
    return tuple(output)


def _segment_identity(
    plan: Program002AcquisitionPlan,
    role: str,
    segment: RequestSegment,
    acquisition_attempt_id: str,
) -> str:
    return fingerprint(
        {
            "plan": plan.sha256,
            "acquisition_authority": plan.authority.sha256,
            "role": role,
            "request": segment.url(),
            "acquisition_attempt_id": _attempt_id(acquisition_attempt_id),
        }
    )


def _attempt_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
        raise Program002AcquisitionError("acquisition attempt ID is invalid")
    return value


def _repository_source_preflight(
    plan: Program002AcquisitionPlan, review: Mapping[str, Any]
) -> None:
    repository = plan.path.parents[2].resolve()
    source = _mapping(plan.authority.payload.get("source_binding"), "authority source binding")
    reviewed = _mapping(review.get("reviewed_source"), "reviewed acquisition source")
    source_commit = str(source.get("source_commit"))
    proof_commit = str(source.get("proof_evidence_commit"))
    authority_commit = str(reviewed.get("authority_artifact_commit"))
    review_relative = ACQUISITION_AUTHORITY_REVIEW_RELATIVE_PATH.as_posix()
    command = (
        "git",
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-C",
        str(repository),
    )
    environment = non_broker_subprocess_environment()
    environment.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})

    def git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            (*command, *arguments),
            check=check,
            capture_output=True,
            text=True,
            env=environment,
        )

    try:
        head = git("rev-parse", "HEAD").stdout.strip()
        main = git("rev-parse", "refs/heads/main").stdout.strip()
        origin_main = git("rev-parse", "refs/remotes/origin/main").stdout.strip()
        dirty = git("status", "--porcelain", "--untracked-files=all").stdout
        ancestry = tuple(
            git("merge-base", "--is-ancestor", commit, head, check=False).returncode
            for commit in (source_commit, proof_commit, authority_commit)
        )
        ordered_ancestry = tuple(
            git("merge-base", "--is-ancestor", earlier, later, check=False).returncode
            for earlier, later in (
                (proof_commit, source_commit),
                (source_commit, authority_commit),
            )
        )
        changed = git(
            "diff", "--name-only", source_commit, head, "--", *ACQUISITION_SOURCE_PATHS
        ).stdout
        review_commits = git(
            "log", "--diff-filter=A", "--format=%H", "--", review_relative
        ).stdout.splitlines()
        if len(review_commits) != 1:
            raise Program002AcquisitionError("acquisition authority review history differs")
        review_commit = review_commits[0]
        review_ancestry = tuple(
            git("merge-base", "--is-ancestor", earlier, later, check=False).returncode
            for earlier, later in (
                (authority_commit, review_commit),
                (review_commit, head),
            )
        )
        authority_bytes = subprocess.run(
            (*command, "show", f"{authority_commit}:{plan.authority.path.relative_to(repository)}"),
            check=True,
            capture_output=True,
            env=environment,
        ).stdout
        review_bytes = subprocess.run(
            (*command, "show", f"{review_commit}:{review_relative}"),
            check=True,
            capture_output=True,
            env=environment,
        ).stdout
        current_review_bytes = (repository / review_relative).read_bytes()
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        raise Program002AcquisitionError("acquisition source identity is unavailable") from error
    if dirty or head != main or head != origin_main:
        raise Program002AcquisitionError(
            "acquisition requires clean synchronized HEAD, main, and origin/main"
        )
    if (
        len({proof_commit, source_commit, authority_commit, review_commit}) != 4
        or any((*ancestry, *ordered_ancestry, *review_ancestry))
        or changed
    ):
        raise Program002AcquisitionError(
            "acquisition source lineage differs from reviewed authority"
        )
    if hashlib.sha256(authority_bytes).hexdigest() != plan.authority.sha256:
        raise Program002AcquisitionError("acquisition authority commit bytes differ")
    if review_bytes != current_review_bytes:
        raise Program002AcquisitionError("acquisition authority review commit bytes differ")


def stored_record_parent(layout: StorageLayout, identity: str) -> str | None:
    try:
        value = _json((layout.dataset(identity) / "segment.json").read_bytes()).get(
            "parent_segment_id"
        )
    except OSError as error:
        raise Program002AcquisitionError("stored segment artifact is incomplete") from error
    return value if isinstance(value, str) else None


def _segment_correction_parent(
    layout: StorageLayout,
    plan: Program002AcquisitionPlan,
    segment: RequestSegment,
    role: str | None,
) -> str | None:
    if not layout.datasets.exists():
        return None
    supersedes = plan.authority.payload.get("supersedes")
    prior_authority = (
        supersedes.get("sha256") if role is not None and isinstance(supersedes, Mapping) else None
    )
    allowed_authorities = {plan.authority.sha256}
    if isinstance(prior_authority, str):
        allowed_authorities.add(prior_authority)
    candidates: dict[str, str | None] = {}
    for path in layout.datasets.glob("*/segment.json"):
        try:
            artifact = _json(path.read_bytes())
        except Program002AcquisitionError:
            continue
        artifact_authority = artifact.get("acquisition_authority_sha256")
        if role is None:
            schema = "program-002-quote-window-v1"
        elif artifact_authority == plan.authority.sha256:
            schema = _BAR_SEGMENT_SCHEMA
        elif artifact_authority == prior_authority:
            schema = _LEGACY_BAR_SEGMENT_SCHEMA
        else:
            continue
        if (
            artifact.get("request") != segment.url()
            or artifact.get("role") != role
            or artifact.get("plan_sha256") != plan.sha256
            or not isinstance(artifact_authority, str)
            or artifact_authority not in allowed_authorities
            or artifact.get("schema_version") != schema
        ):
            continue
        identity = artifact.get("identity")
        if not isinstance(identity, str) or path.parent != layout.dataset(identity):
            continue
        try:
            _load_segment_artifact(
                layout,
                identity,
                segment,
                schema,
                role=role,
                plan_sha256=plan.sha256,
                authority_sha256=str(artifact_authority),
            )
        except Program002AcquisitionError:
            continue
        candidates[identity] = stored_record_parent(layout, identity)
    if not candidates:
        return None
    leaves = set(candidates) - {item for item in candidates.values() if item is not None}
    if len(leaves) != 1:
        raise Program002AcquisitionError("segment correction lineage is ambiguous")
    return next(iter(leaves))


def _append_segment_journal(layout: StorageLayout, record: Mapping[str, Any]) -> None:
    path = layout.reports / "program-002" / "acquisition-segments.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = canonical_json(record) + "\n"
    if path.exists() and line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        return
    with path.open("a", encoding="utf-8", newline="\n") as file:
        file.write(line)
        file.flush()
        os.fsync(file.fileno())
    _fsync_directory(path.parent)


def _append_terminal_attempt_journal(
    layout: StorageLayout,
    acquisition_attempt_id: str,
    segment: RequestSegment,
    error: Program002AcquisitionError,
    segment_identity: str | None = None,
    quarantine_identity: str | None = None,
) -> None:
    record = {
        "schema_version": "program-002-acquisition-terminal-attempt-v1",
        "acquisition_attempt_id": _attempt_id(acquisition_attempt_id),
        "request": segment.url(),
        "endpoint": segment.endpoint,
        "kind": segment.kind,
        "disposition": "failed",
        "error": str(error),
        "segment_identity": segment_identity,
        "quarantine_identity": quarantine_identity,
        "http_attempts": list(getattr(error, "http_attempts", ())),
    }
    record["identity"] = fingerprint(record)
    path = layout.reports / "program-002" / "acquisition-terminal-attempts.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = canonical_json(record) + "\n"
    if path.exists() and line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        return
    with path.open("a", encoding="utf-8", newline="\n") as file:
        file.write(line)
        file.flush()
        os.fsync(file.fileno())
    _fsync_directory(path.parent)


def _validate_terminal_attempt_journal(layout: StorageLayout) -> None:
    path = layout.reports / "program-002" / "acquisition-terminal-attempts.jsonl"
    if not path.exists():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise Program002AcquisitionError("terminal acquisition journal is unreadable") from error
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        try:
            _json(lines[-1].encode())
        except Program002AcquisitionError:
            lines.pop()
        else:
            lines[-1] += "\n"
        _rewrite_segment_journal(path, lines)
    try:
        records = tuple(_json(line.encode()) for line in lines)
    except Program002AcquisitionError as error:
        raise Program002AcquisitionError("terminal acquisition journal is corrupt") from error
    for record in records:
        unsigned = dict(record)
        identity = unsigned.pop("identity", None)
        if (
            not isinstance(identity, str)
            or identity != fingerprint(unsigned)
            or record.get("schema_version") != "program-002-acquisition-terminal-attempt-v1"
            or record.get("disposition") != "failed"
        ):
            raise Program002AcquisitionError("terminal acquisition journal integrity differs")


def _validate_segment_journal(layout: StorageLayout) -> None:
    path = layout.reports / "program-002" / "acquisition-segments.jsonl"
    if not path.exists():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise Program002AcquisitionError("acquisition journal is unreadable") from error
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        try:
            _json(lines[-1].encode())
        except Program002AcquisitionError:
            lines.pop()
        else:
            lines[-1] += "\n"
        _rewrite_segment_journal(path, lines)
    try:
        records = tuple(_json(line.encode()) for line in lines)
    except Program002AcquisitionError:
        raise Program002AcquisitionError("acquisition journal is corrupt") from None
    identities: set[str] = set()
    for record in records:
        identity = record.get("identity")
        if not isinstance(identity, str) or identity in identities:
            raise Program002AcquisitionError("acquisition journal identity differs")
        identities.add(identity)
        try:
            stored = _json((layout.dataset(identity) / "segment.json").read_bytes())
        except OSError as error:
            raise Program002AcquisitionError(
                "acquisition journal references missing artifact"
            ) from error
        if stored != record:
            raise Program002AcquisitionError("acquisition journal artifact differs")


def _rewrite_segment_journal(path: Path, lines: Sequence[str]) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.repair-", dir=path.parent)
    temporary = Path(name)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
        file.writelines(lines)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _quarantine_page(
    layout: StorageLayout | None,
    segment: RequestSegment,
    url: str,
    page: object,
    error: Exception,
    *,
    previous_pages: Sequence[RawPage] = (),
    raw_records: Sequence[Mapping[str, Any]] = (),
) -> str | None:
    if layout is None:
        return None
    body = page.body if isinstance(page, HttpPage | RawPage) else b""
    attempts = getattr(error, "http_attempts", getattr(page, "attempts", ()))
    evidence = {
        "segment": {"kind": segment.kind, "url": url},
        "raw_page_sha256": hashlib.sha256(body).hexdigest(),
        "raw_page_hex": body.hex(),
        "http_attempts": list(attempts),
        "previous_pages": [
            {
                "request_url": item.request_url,
                "sha256": item.sha256,
                "body_hex": item.body.hex(),
                "request_evidence": item.request_evidence,
                "http_attempts": item.attempts,
            }
            for item in previous_pages
        ],
        "raw_records": list(raw_records),
        "error": str(error),
    }
    identity = fingerprint(evidence)
    layout.write_quarantine(identity, canonical_json(evidence) + "\n")
    return identity


def _quarantine_acquired_segment(
    layout: StorageLayout,
    segment: RequestSegment,
    acquired: AcquiredSegment,
    error: Exception,
    acquisition_attempt_id: str,
    segment_identity: str,
) -> str:
    evidence = {
        "segment": {"kind": segment.kind, "url": segment.url()},
        "acquisition_attempt_id": _attempt_id(acquisition_attempt_id),
        "segment_identity": segment_identity,
        "raw_pages": [
            {
                "request_url": page.request_url,
                "sha256": page.sha256,
                "body_hex": page.body.hex(),
                "request_evidence": page.request_evidence,
                "http_attempts": page.attempts,
            }
            for page in acquired.pages
        ],
        "raw_records": list(acquired.raw_records),
        "validation_error": str(error),
    }
    identity = fingerprint(evidence)
    layout.write_quarantine(identity, canonical_json(evidence) + "\n")
    return identity


def _correction_parent(
    layout: StorageLayout, plan: Program002AcquisitionPlan, role: str, dataset_id: str
) -> str | None:
    if not layout.datasets.exists():
        return None
    target = _role(plan, role)
    universe = _mapping(plan.payload["universe"], "universe")
    matches: dict[str, str | None] = {}
    for path in layout.datasets.glob("*/manifest.json"):
        try:
            manifest = _json(path.read_bytes())
        except Program002AcquisitionError:
            continue
        identity = manifest.get("identity", {}).get("dataset_id")
        if (
            not isinstance(identity, str)
            or identity == dataset_id
            or path.parent != layout.dataset(identity)
            or manifest.get("program_002", {}).get("role") != role
            or manifest.get("program_002", {}).get("plan_sha256") != plan.sha256
            or manifest.get("program_002", {}).get("acquisition_authority_sha256")
            != plan.authority.sha256
            or manifest.get("provider") != "alpaca-historical-v2"
            or manifest.get("feed") != "sip"
            or manifest.get("endpoint") != _BARS
            or manifest.get("timeframe") != Timeframe.FIVE_MINUTES.value
            or manifest.get("adjustment_policy") != "provider-adjusted-all-v1"
            or manifest.get("calendar_policy") != "XNYS-regular-session-bars-v1"
            or manifest.get("timestamp_policy") != "bar-open-utc-v1"
            or manifest.get("schema_version") != "ohlcv-v1"
            or manifest.get("manifest_schema") != "program-002-ohlcv-dataset-manifest-v1"
            or manifest.get("program_002_manifest_schema_version")
            != "program-002-ohlcv-dataset-manifest-v1"
            or manifest.get("universe_id") != universe.get("universe_id")
            or manifest.get("universe_fingerprint") != universe.get("universe_fingerprint")
            or manifest.get("symbols") != [{"value": symbol} for symbol in _symbols(plan)]
            or manifest.get("requested_range")
            != {
                "start": target.get("inclusive_utc_bar_open_start"),
                "end": target.get("inclusive_utc_bar_open_end"),
            }
            or manifest.get("actual_range")
            != {
                "start": target.get("inclusive_utc_bar_open_start"),
                "end": target.get("inclusive_utc_bar_open_end"),
            }
            or manifest.get("validation_evidence", {}).get("expected_rows")
            != target.get("expected_rows")
            or manifest.get("validation_evidence", {}).get("bar_count")
            != target.get("expected_rows")
            or not _manifest_bytes_valid(path.parent, manifest)
        ):
            continue
        try:
            if not DatasetService(layout).validate(identity)["valid"]:
                continue
        except (KeyError, OSError, ValueError):
            continue
        parent = manifest.get("parent_dataset_id")
        matches[identity] = parent if isinstance(parent, str) else None
    if not matches:
        return None
    children = {parent for parent in matches.values() if parent is not None}
    leaves = set(matches) - children
    if len(leaves) != 1:
        raise Program002AcquisitionError("Program 002 correction lineage is ambiguous")
    return next(iter(leaves))


def _endpoint(value: str, kind: str) -> None:
    expected = _BARS if kind == "bars" else _QUOTES
    parsed = urlparse(value)
    if value != expected or parsed.scheme != "https" or parsed.netloc != "data.alpaca.markets":
        raise Program002AcquisitionError("provider endpoint differs from frozen HTTPS contract")


def _request_identity(
    url: str, *, allow_page_token: bool
) -> tuple[str, tuple[tuple[str, str], ...]]:
    parsed = urlparse(url)
    if parsed.params or parsed.fragment or parsed.username or parsed.password:
        raise Program002AcquisitionError(
            "provider request differs from frozen authority-bound segment"
        )
    query = parse_qsl(parsed.query, keep_blank_values=True)
    tokens = [value for key, value in query if key == "page_token"]
    if len(tokens) > 1 or (tokens and (not allow_page_token or not tokens[0])):
        raise Program002AcquisitionError(
            "provider request differs from frozen authority-bound segment"
        )
    return parsed.path, tuple(sorted((key, value) for key, value in query if key != "page_token"))


def _manifest_bytes_valid(root: Path, manifest: Mapping[str, Any]) -> bool:
    files = manifest.get("files")
    if not isinstance(files, Mapping) or set(files) != {"raw.jsonl", "bars.parquet"}:
        return False
    try:
        files_valid = all(
            isinstance(expected, str)
            and hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
            for name, expected in files.items()
        )
        sidecar = _json((root / "manifest.sha256.json").read_bytes())
        return files_valid and sidecar == {
            "dataset_id": manifest.get("dataset_id"),
            "manifest_sha256": hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest(),
        }
    except (OSError, Program002AcquisitionError):
        return False


def _json(raw: bytes) -> Mapping[str, Any]:
    canonical_number_chars = 0

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        output = {}
        for key, value in items:
            if key in output:
                raise Program002AcquisitionError("provider JSON contains duplicate key")
            output[key] = value
        return output

    def decimal_value(token: str) -> Decimal:
        nonlocal canonical_number_chars
        value = Decimal(token)
        try:
            normalized = value.normalize()
        except ArithmeticError as error:
            raise Program002AcquisitionError(
                "provider JSON number exceeds canonical evidence bound"
            ) from error
        if normalized != value:
            raise Program002AcquisitionError(
                "provider JSON number exceeds canonical evidence bound"
            )
        sign, digits, exponent = normalized.as_tuple()
        if not isinstance(exponent, int):
            raise Program002AcquisitionError("provider JSON contains non-finite number")
        if value == 0:
            length = 1
        elif exponent >= 0:
            length = sign + len(digits) + exponent
        elif len(digits) + exponent > 0:
            length = sign + len(digits) + 1
        else:
            length = sign + 2 - exponent
        canonical_number_chars += length
        if canonical_number_chars > len(raw):
            raise Program002AcquisitionError(
                "provider JSON number exceeds canonical evidence bound"
            )
        return value

    def integer_value(token: str) -> int:
        nonlocal canonical_number_chars
        canonical_number_chars += len(token)
        if canonical_number_chars > len(raw):
            raise Program002AcquisitionError(
                "provider JSON number exceeds canonical evidence bound"
            )
        try:
            return int(token)
        except ValueError as error:
            raise Program002AcquisitionError(
                "provider JSON number exceeds canonical evidence bound"
            ) from error

    def reject_constant(_: str) -> object:
        raise Program002AcquisitionError("provider JSON contains non-finite number")

    try:
        value = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_float=decimal_value,
            parse_int=integer_value,
            parse_constant=reject_constant,
        )
    except (ArithmeticError, json.JSONDecodeError, RecursionError, TypeError, ValueError) as error:
        raise Program002AcquisitionError("malformed provider payload") from error
    return _mapping(value, "provider response")


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Program002AcquisitionError(f"{label} must be an object")
    return value


def _time(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise Program002AcquisitionError("provider timestamp must be UTC")
    return parsed


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _urlopen_page(request: Request) -> HttpPage:
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args: object, **kwargs: object) -> None:
            return None

    with build_opener(NoRedirect(), ProxyHandler({})).open(request, timeout=30) as response:
        body = response.read(64 * 1024 * 1024 + 1)
        if len(body) > 64 * 1024 * 1024:
            raise Program002AcquisitionError("provider response exceeds bounded page size")
        return HttpPage(response.status, body, dict(response.headers.items()))
