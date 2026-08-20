"""Prospective intraday quote calibration without strategy-result access."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import exchange_calendars as xcals  # type: ignore[import-untyped]

from .fingerprints import canonical_json, fingerprint
from .storage import StorageLayout

PROGRAM_ID = "intraday-execution-calibration-001"
RUN_ID = "intraday-execution-calibration-001-v2"
PLAN_SCHEMA = "intraday-execution-calibration-plan-v2"
QUOTE_DATASET_SCHEMA = "intraday-quote-calibration-dataset-v2"
ANALYSIS_SCHEMA = "intraday-execution-calibration-analysis-v2"
PLAN_RELATIVE_PATH = Path("config/research/intraday-execution-calibration-001-plan-v2.json")
REVIEWED_PLAN_SHA256 = "67dc2a2155a91f5ab26395a4c3f34457ebcb6e1813f95f7e02c642129c9db546"
ALPACA_QUOTES_ENDPOINT = "https://data.alpaca.markets/v2/stocks/quotes"
_TIMESTAMP = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z$")
_BPS = Decimal("10000")
_NANOSECONDS = 1_000_000_000


@dataclass(frozen=True)
class CalibrationWindow:
    session_date: date
    window_id: str
    start: datetime
    end: datetime
    session_open: datetime
    session_close: datetime

    @property
    def request_start(self) -> datetime:
        return self.start - timedelta(seconds=5)

    @property
    def logical_id(self) -> str:
        return f"{self.session_date.isoformat()}:{self.window_id}"


@dataclass(frozen=True)
class CalibrationPlan:
    path: Path
    payload: Mapping[str, Any]
    sha256: str
    plan_fingerprint: str
    run_id: str
    symbols: tuple[str, ...]
    sessions: tuple[date, ...]
    windows: tuple[CalibrationWindow, ...]
    grid_interval_seconds: int
    quote_lookback_seconds: int
    minimum_coverage: Decimal


@dataclass(frozen=True)
class HistoricalQuote:
    symbol: str
    timestamp: str
    timestamp_ns: int
    bid_exchange: str
    bid_price: Decimal
    bid_size: int
    ask_exchange: str
    ask_price: Decimal
    ask_size: int
    conditions: tuple[str, ...]
    tape: str

    def to_record(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "bid_exchange": self.bid_exchange,
            "bid_price": self.bid_price,
            "bid_size": self.bid_size,
            "ask_exchange": self.ask_exchange,
            "ask_price": self.ask_price,
            "ask_size": self.ask_size,
            "conditions": self.conditions,
            "tape": self.tape,
        }


@dataclass(frozen=True)
class QuoteObservation:
    symbol: str
    feed: str
    session_date: str
    window_id: str
    grid_timestamp: datetime
    quote_timestamp: str
    quote_age_ms: Decimal
    bid_price: Decimal
    ask_price: Decimal
    spread_dollars: Decimal
    spread_bps: Decimal
    half_spread_bps: Decimal

    def to_record(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "feed": self.feed,
            "session_date": self.session_date,
            "window_id": self.window_id,
            "grid_timestamp": self.grid_timestamp,
            "quote_timestamp": self.quote_timestamp,
            "quote_age_ms": self.quote_age_ms,
            "bid_price": self.bid_price,
            "ask_price": self.ask_price,
            "spread_dollars": self.spread_dollars,
            "spread_bps": self.spread_bps,
            "half_spread_bps": self.half_spread_bps,
        }


class QuoteAcquisitionError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        *,
        quote_data_returned: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.quote_data_returned = quote_data_returned


QuoteTransport = Callable[[Request], bytes]
QuoteDataCallback = Callable[[], None]


class AlpacaHistoricalQuoteClient:
    """GET-only historical quote client with explicit feed and pagination."""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        feed: str,
        *,
        endpoint: str = ALPACA_QUOTES_ENDPOINT,
        transport: QuoteTransport | None = None,
        on_quote_data_returned: QuoteDataCallback | None = None,
        max_pages: int = 1000,
    ) -> None:
        if not api_key or not secret_key:
            raise ValueError("Alpaca market-data credentials are required")
        if feed not in {"sip", "iex"}:
            raise ValueError("historical quote feed must be sip or iex")
        if max_pages < 1:
            raise ValueError("maximum quote pages must be positive")
        self._api_key = api_key
        self._secret_key = secret_key
        self.feed = feed
        self.endpoint = endpoint
        self.transport = transport or _urlopen_bytes
        self.on_quote_data_returned = on_quote_data_returned
        self.max_pages = max_pages

    def fetch(self, symbol: str, start: datetime, end: datetime) -> tuple[HistoricalQuote, ...]:
        if start.tzinfo is None or start.utcoffset() != timedelta(0):
            raise ValueError("quote request start must use UTC")
        if end.tzinfo is None or end.utcoffset() != timedelta(0) or end <= start:
            raise ValueError("quote request end must follow a UTC start")
        parameters = {
            "symbols": symbol,
            "start": _iso(start),
            "end": _iso(end),
            "feed": self.feed,
            "sort": "asc",
            "limit": "10000",
        }
        headers = {
            "APCA-API-KEY-ID": self._api_key,
            "APCA-API-SECRET-KEY": self._secret_key,
        }
        records: list[HistoricalQuote] = []
        token: str | None = None
        for _ in range(self.max_pages):
            query = dict(parameters)
            if token is not None:
                query["page_token"] = token
            request = Request(f"{self.endpoint}?{urlencode(query)}", headers=headers)
            try:
                payload = json.loads(self.transport(request), parse_float=Decimal)
            except HTTPError as error:
                raise QuoteAcquisitionError(
                    "Alpaca historical quote request failed",
                    error.code,
                    quote_data_returned=bool(records),
                ) from error
            except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
                raise QuoteAcquisitionError("Alpaca historical quote request failed") from error
            item = _mapping(payload, "historical quote response")
            quote_map = _mapping(item.get("quotes"), "historical quote response quotes")
            if self.on_quote_data_returned is not None and any(
                bool(value) for value in quote_map.values()
            ):
                self.on_quote_data_returned()
            unexpected = set(quote_map) - {symbol}
            if unexpected:
                raise QuoteAcquisitionError("Alpaca historical quote response changed symbol")
            values = quote_map.get(symbol, [])
            if not isinstance(values, list):
                raise QuoteAcquisitionError("Alpaca historical quote response has invalid quotes")
            records.extend(_quote(symbol, value) for value in values)
            raw_token = item.get("next_page_token")
            token = raw_token if isinstance(raw_token, str) and raw_token else None
            if token is None:
                return tuple(records)
        raise QuoteAcquisitionError("Alpaca historical quote request exceeded page limit")


def load_calibration_plan(repository: Path) -> CalibrationPlan:
    path = repository / PLAN_RELATIVE_PATH
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    if sha256 != REVIEWED_PLAN_SHA256:
        raise ValueError("intraday calibration plan SHA-256 differs")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("intraday calibration plan is invalid JSON") from error
    plan = _mapping(payload, "calibration plan")
    if (
        plan.get("schema_version") != PLAN_SCHEMA
        or plan.get("program_id") != PROGRAM_ID
        or plan.get("run_id") != RUN_ID
    ):
        raise ValueError("intraday calibration plan identity differs")
    if plan.get("status") != "frozen-before-v2-quote-reacquisition":
        raise ValueError("intraday calibration plan is not frozen")
    source = _mapping(plan.get("source"), "calibration source")
    if source.get("endpoint") != ALPACA_QUOTES_ENDPOINT:
        raise ValueError("intraday calibration quote endpoint differs")
    symbols_value = source.get("symbols")
    if symbols_value != ["QQQ", "SPY"]:
        raise ValueError("intraday calibration symbols differ")
    sessions = _derived_sessions()
    declared = _mapping(plan.get("session_selection"), "session selection").get("sessions")
    if not isinstance(declared, list):
        raise ValueError("intraday calibration sessions are missing")
    declared_sessions = tuple(date.fromisoformat(_text(item, "date")) for item in declared)
    if declared_sessions != sessions:
        raise ValueError("intraday calibration sessions differ from the calendar rule")
    windows = tuple(window for session in sessions for window in _session_windows(session))
    if len(windows) != 67 or any(
        window.session_date.month == 6 and window.session_date.year == 2026 for window in windows
    ):
        raise ValueError("intraday calibration windows differ")
    sampling = _mapping(plan.get("sampling"), "sampling")
    validation = _mapping(plan.get("validation"), "validation")
    grid_interval = _positive_int(sampling.get("grid_interval_seconds"), "grid interval")
    lookback = _positive_int(sampling.get("quote_lookback_seconds"), "quote lookback")
    if grid_interval != 1 or lookback != 5:
        raise ValueError("intraday calibration sampling differs")
    coverage = _decimal(validation.get("minimum_eligible_grid_coverage_per_window"), "coverage")
    if coverage != Decimal("0.99"):
        raise ValueError("intraday calibration coverage differs")
    return CalibrationPlan(
        path,
        plan,
        sha256,
        fingerprint(plan),
        RUN_ID,
        ("QQQ", "SPY"),
        sessions,
        windows,
        grid_interval,
        lookback,
        coverage,
    )


def validate_quote_sequence(
    quotes: Sequence[HistoricalQuote],
    symbol: str,
    request_start: datetime,
    request_end: datetime,
) -> tuple[tuple[HistoricalQuote, ...], dict[str, int | Decimal]]:
    start_ns = _datetime_ns(request_start)
    end_ns = _datetime_ns(request_end)
    previous_ns: int | None = None
    seen: set[str] = set()
    validated: list[HistoricalQuote] = []
    exact_duplicates = 0
    same_timestamp_updates = 0
    maximum_gap_ns = 0
    for quote in quotes:
        if quote.symbol != symbol:
            raise ValueError("historical quote symbol differs")
        if not start_ns <= quote.timestamp_ns <= end_ns:
            raise ValueError("historical quote is outside the request boundary")
        if previous_ns is not None and quote.timestamp_ns < previous_ns:
            raise ValueError("historical quote timestamps are not ordered")
        if quote.bid_price < 0 or quote.ask_price < 0:
            raise ValueError("historical quote has a negative price")
        if quote.bid_size < 0 or quote.ask_size < 0:
            raise ValueError("historical quote has an invalid size")
        signature = canonical_json(quote.to_record())
        if signature in seen:
            exact_duplicates += 1
            previous_ns = quote.timestamp_ns
            continue
        seen.add(signature)
        if validated:
            gap = quote.timestamp_ns - validated[-1].timestamp_ns
            maximum_gap_ns = max(maximum_gap_ns, gap)
            if gap == 0:
                same_timestamp_updates += 1
        validated.append(quote)
        previous_ns = quote.timestamp_ns
    return tuple(validated), {
        "raw_quote_count": len(quotes),
        "unique_quote_count": len(validated),
        "exact_duplicate_count": exact_duplicates,
        "same_timestamp_update_count": same_timestamp_updates,
        "maximum_raw_update_gap_ms": Decimal(maximum_gap_ns) / Decimal(1_000_000),
        "raw_nonpositive_bid_count": sum(quote.bid_price <= 0 for quote in validated),
        "raw_nonpositive_ask_count": sum(quote.ask_price <= 0 for quote in validated),
        "raw_zero_bid_size_count": sum(quote.bid_size == 0 for quote in validated),
        "raw_zero_ask_size_count": sum(quote.ask_size == 0 for quote in validated),
        "raw_crossed_market_count": sum(
            quote.bid_price > 0
            and quote.ask_price > 0
            and quote.bid_size > 0
            and quote.ask_size > 0
            and quote.ask_price < quote.bid_price
            for quote in validated
        ),
        "raw_locked_market_count": sum(
            quote.bid_price > 0
            and quote.ask_price == quote.bid_price
            and quote.bid_size > 0
            and quote.ask_size > 0
            for quote in validated
        ),
    }


def sample_quotes(
    quotes: Sequence[HistoricalQuote],
    feed: str,
    window: CalibrationWindow,
    *,
    grid_interval_seconds: int = 1,
    quote_lookback_seconds: int = 5,
) -> tuple[tuple[QuoteObservation, ...], dict[str, int]]:
    if grid_interval_seconds < 1 or quote_lookback_seconds < 1:
        raise ValueError("quote sampling intervals must be positive")
    observations: list[QuoteObservation] = []
    quote_index = 0
    latest: HistoricalQuote | None = None
    exclusions = {
        "no_quote": 0,
        "stale_quote": 0,
        "nonpositive_bid": 0,
        "nonpositive_ask": 0,
        "zero_bid_size": 0,
        "zero_ask_size": 0,
        "crossed_market": 0,
    }
    locked = 0
    grid = window.start
    while grid < window.end:
        grid_ns = _datetime_ns(grid)
        while quote_index < len(quotes) and quotes[quote_index].timestamp_ns < grid_ns:
            latest = quotes[quote_index]
            quote_index += 1
        age_ns = grid_ns - latest.timestamp_ns if latest is not None else None
        if latest is None or age_ns is None:
            exclusions["no_quote"] += 1
        elif age_ns > quote_lookback_seconds * _NANOSECONDS:
            exclusions["stale_quote"] += 1
        elif latest.bid_price <= 0:
            exclusions["nonpositive_bid"] += 1
        elif latest.ask_price <= 0:
            exclusions["nonpositive_ask"] += 1
        elif latest.bid_size <= 0:
            exclusions["zero_bid_size"] += 1
        elif latest.ask_size <= 0:
            exclusions["zero_ask_size"] += 1
        elif latest.ask_price < latest.bid_price:
            exclusions["crossed_market"] += 1
        else:
            spread = latest.ask_price - latest.bid_price
            midpoint = (latest.ask_price + latest.bid_price) / Decimal("2")
            locked += int(spread == 0)
            spread_bps = spread / midpoint * _BPS
            observations.append(
                QuoteObservation(
                    latest.symbol,
                    feed,
                    window.session_date.isoformat(),
                    window.window_id,
                    grid,
                    latest.timestamp,
                    Decimal(age_ns) / Decimal(1_000_000),
                    latest.bid_price,
                    latest.ask_price,
                    spread,
                    spread_bps,
                    spread_bps / Decimal("2"),
                )
            )
        grid += timedelta(seconds=grid_interval_seconds)
    return tuple(observations), {
        **exclusions,
        "total": sum(exclusions.values()),
        "eligible_locked_market_count": locked,
    }


def acquire_quote_window(
    data_home: Path,
    plan: CalibrationPlan,
    client: AlpacaHistoricalQuoteClient,
    window: CalibrationWindow,
    symbol: str,
) -> Mapping[str, Any]:
    layout = StorageLayout(data_home / plan.run_id)
    logical_key = _logical_key(plan, client.feed, symbol, window)
    existing = _existing_artifact(layout, plan, logical_key)
    if existing is not None:
        return existing
    raw_quotes = client.fetch(symbol, window.request_start, window.end)
    raw_text = "".join(canonical_json(quote.to_record()) + "\n" for quote in raw_quotes)
    raw_sha256 = hashlib.sha256(raw_text.encode()).hexdigest()
    validation_evidence: dict[str, object] = {}
    try:
        quotes, validation = validate_quote_sequence(
            raw_quotes, symbol, window.request_start, window.end
        )
        observations, exclusions = sample_quotes(
            quotes,
            client.feed,
            window,
            grid_interval_seconds=plan.grid_interval_seconds,
            quote_lookback_seconds=plan.quote_lookback_seconds,
        )
        expected = int((window.end - window.start).total_seconds()) // plan.grid_interval_seconds
        coverage = Decimal(len(observations)) / Decimal(expected)
        validation_evidence = {
            **validation,
            "expected_grid_count": expected,
            "observation_count": len(observations),
            "grid_exclusions": exclusions,
            "eligible_grid_coverage": coverage,
        }
        if coverage < plan.minimum_coverage:
            raise ValueError("historical quote window failed eligible grid coverage")
    except (ArithmeticError, TypeError, ValueError) as error:
        evidence = {
            "schema_version": "intraday-quote-calibration-quarantine-v2",
            "program_id": PROGRAM_ID,
            "run_id": plan.run_id,
            "plan_sha256": plan.sha256,
            "plan_fingerprint": plan.plan_fingerprint,
            "logical_key": logical_key,
            "feed": client.feed,
            "symbol": symbol,
            "session_date": window.session_date.isoformat(),
            "window_id": window.window_id,
            "request": {"start": window.request_start, "end": window.end},
            "error_type": type(error).__name__,
            "error": str(error),
            "raw_sha256": raw_sha256,
            "validation": validation_evidence,
            "raw_quotes": tuple(quote.to_record() for quote in raw_quotes),
        }
        evidence_id = fingerprint(evidence)
        layout.write_quarantine(evidence_id, canonical_json(evidence) + "\n")
        raise
    observation_text = "".join(
        canonical_json(observation.to_record()) + "\n" for observation in observations
    )
    observation_sha256 = hashlib.sha256(observation_text.encode()).hexdigest()
    identity = {
        "logical_key": logical_key,
        "plan_fingerprint": plan.plan_fingerprint,
        "run_id": plan.run_id,
        "feed": client.feed,
        "symbol": symbol,
        "session_date": window.session_date.isoformat(),
        "window_id": window.window_id,
        "raw_sha256": raw_sha256,
        "observation_sha256": observation_sha256,
    }
    dataset_id = fingerprint(identity)
    manifest = {
        "schema_version": QUOTE_DATASET_SCHEMA,
        "program_id": PROGRAM_ID,
        "run_id": plan.run_id,
        "identity": {"dataset_id": dataset_id, **identity},
        "plan_sha256": plan.sha256,
        "provider": "alpaca-market-data-api-v2-historical-quotes",
        "endpoint": client.endpoint,
        "retrieved_at": datetime.now(UTC),
        "request": {
            "start": window.request_start,
            "end": window.end,
            "feed": client.feed,
            "symbol": symbol,
        },
        "observation_window": {"start": window.start, "end": window.end},
        "validation": validation_evidence,
        "raw_sha256": raw_sha256,
        "observation_sha256": observation_sha256,
    }
    created = layout.publish(
        dataset_id,
        {
            "raw.jsonl": raw_text,
            "observations.jsonl": observation_text,
            "manifest.json": canonical_json(manifest) + "\n",
        },
    )
    if not created:
        stored = _read_json(layout.dataset(dataset_id) / "manifest.json")
        _verify_artifact(layout, plan, stored)
        return stored
    return cast(Mapping[str, Any], json.loads(canonical_json(manifest)))


def acquire_calibration_quotes(
    repository: Path,
    data_home: Path,
    api_key: str,
    secret_key: str,
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    plan = load_calibration_plan(repository)
    root = data_home / plan.run_id
    layout = StorageLayout(root)
    selection_path = root / "feed-selection.json"
    sip_data_path = root / "sip-quote-data-returned.json"
    sip_data_marker: Mapping[str, object] = {
        "schema_version": "intraday-sip-quote-data-returned-v1",
        "program_id": PROGRAM_ID,
        "run_id": plan.run_id,
        "plan_sha256": plan.sha256,
        "plan_fingerprint": plan.plan_fingerprint,
        "feed": "sip",
        "status": "sip-data-returned-before-feed-selection",
    }
    if sip_data_path.exists():
        _write_create_only(sip_data_path, sip_data_marker)
    selection = _read_json(selection_path) if selection_path.exists() else None
    first_window = plan.windows[0]
    first_symbol = plan.symbols[0]
    if selection is None:
        sip = AlpacaHistoricalQuoteClient(
            api_key,
            secret_key,
            "sip",
            on_quote_data_returned=lambda: _write_create_only(sip_data_path, sip_data_marker),
        )
        try:
            probe = acquire_quote_window(data_home, plan, sip, first_window, first_symbol)
            feed = "sip"
            reason = "sip-authorized"
        except QuoteAcquisitionError as error:
            if error.status_code != 403 or error.quote_data_returned or sip_data_path.exists():
                raise
            iex = AlpacaHistoricalQuoteClient(api_key, secret_key, "iex")
            probe = acquire_quote_window(data_home, plan, iex, first_window, first_symbol)
            feed = "iex"
            reason = "sip-http-403-entitlement-fallback"
        selection = {
            "schema_version": "intraday-quote-feed-selection-v2",
            "program_id": PROGRAM_ID,
            "run_id": plan.run_id,
            "plan_fingerprint": plan.plan_fingerprint,
            "feed": feed,
            "reason": reason,
            "probe_dataset_id": _mapping(probe.get("identity"), "probe identity")["dataset_id"],
            "selected_at": datetime.now(UTC),
        }
        _write_create_only(selection_path, selection)
        selection = _read_json(selection_path)
    feed = _selected_feed(layout, plan, selection)
    if feed == "iex" and sip_data_path.exists():
        raise ValueError("IEX feed selection conflicts with prior SIP quote data")
    client = AlpacaHistoricalQuoteClient(api_key, secret_key, feed)
    manifests: list[Mapping[str, Any]] = []
    for window in plan.windows:
        for symbol in plan.symbols:
            manifest = acquire_quote_window(data_home, plan, client, window, symbol)
            manifests.append(manifest)
            if progress is not None:
                progress(f"{window.logical_id} {symbol} complete")
    return {
        "program_id": PROGRAM_ID,
        "run_id": plan.run_id,
        "plan_sha256": plan.sha256,
        "plan_fingerprint": plan.plan_fingerprint,
        "feed": feed,
        "dataset_count": len(manifests),
        "dataset_ids_fingerprint": fingerprint(
            tuple(_mapping(item.get("identity"), "identity")["dataset_id"] for item in manifests)
        ),
    }


def analyze_calibration_quotes(repository: Path, data_home: Path) -> dict[str, object]:
    plan = load_calibration_plan(repository)
    root = data_home / plan.run_id
    selection = _read_json(root / "feed-selection.json")
    layout = StorageLayout(root)
    feed = _selected_feed(layout, plan, selection)
    if feed == "iex" and (root / "sip-quote-data-returned.json").exists():
        raise ValueError("IEX feed selection conflicts with prior SIP quote data")
    manifests: list[Mapping[str, Any]] = []
    observations: list[Mapping[str, Any]] = []
    for window in plan.windows:
        for symbol in plan.symbols:
            logical_key = _logical_key(plan, feed, symbol, window)
            manifest = _existing_artifact(layout, plan, logical_key)
            if manifest is None:
                raise ValueError(f"quote calibration artifact is missing: {logical_key}")
            manifests.append(manifest)
            dataset_id = _text(_mapping(manifest.get("identity"), "identity"), "dataset_id")
            observations.extend(_read_json_lines(layout.dataset(dataset_id) / "observations.jsonl"))
    groups: dict[str, dict[str, list[Mapping[str, Any]]]] = {
        "combined": {"combined": observations},
        "symbol": {},
        "time_window": {},
        "symbol_and_time_window": {},
    }
    for observation in observations:
        symbol = _text(observation, "symbol")
        window_id = _text(observation, "window_id")
        groups["symbol"].setdefault(symbol, []).append(observation)
        groups["time_window"].setdefault(window_id, []).append(observation)
        groups["symbol_and_time_window"].setdefault(f"{symbol}:{window_id}", []).append(observation)
    distributions = {
        group: {name: _distribution(values) for name, values in members.items()}
        for group, members in groups.items()
    }
    dataset_rows = tuple(
        {
            "dataset_id": _mapping(manifest.get("identity"), "identity")["dataset_id"],
            "raw_sha256": manifest["raw_sha256"],
            "observation_sha256": manifest["observation_sha256"],
            "logical_key": _mapping(manifest.get("identity"), "identity")["logical_key"],
        }
        for manifest in manifests
    )
    validation_rows = tuple(_mapping(item.get("validation"), "validation") for item in manifests)
    analysis: dict[str, object] = {
        "schema_version": ANALYSIS_SCHEMA,
        "program_id": PROGRAM_ID,
        "run_id": plan.run_id,
        "plan_sha256": plan.sha256,
        "plan_fingerprint": plan.plan_fingerprint,
        "feed": feed,
        "sample": {
            "session_count": len(plan.sessions),
            "window_count": len(plan.windows),
            "dataset_count": len(manifests),
            "observation_count": len(observations),
            "minimum_eligible_grid_coverage": min(
                _decimal(row.get("eligible_grid_coverage"), "eligible grid coverage")
                for row in validation_rows
            ),
            "exact_duplicate_count": sum(
                int(row.get("exact_duplicate_count", 0)) for row in validation_rows
            ),
            "same_timestamp_update_count": sum(
                int(row.get("same_timestamp_update_count", 0)) for row in validation_rows
            ),
            "raw_nonpositive_bid_count": sum(
                int(row.get("raw_nonpositive_bid_count", 0)) for row in validation_rows
            ),
            "raw_nonpositive_ask_count": sum(
                int(row.get("raw_nonpositive_ask_count", 0)) for row in validation_rows
            ),
            "raw_zero_bid_size_count": sum(
                int(row.get("raw_zero_bid_size_count", 0)) for row in validation_rows
            ),
            "raw_zero_ask_size_count": sum(
                int(row.get("raw_zero_ask_size_count", 0)) for row in validation_rows
            ),
            "raw_crossed_market_count": sum(
                int(row.get("raw_crossed_market_count", 0)) for row in validation_rows
            ),
            "raw_locked_market_count": sum(
                int(row.get("raw_locked_market_count", 0)) for row in validation_rows
            ),
            "grid_exclusions": {
                reason: sum(
                    int(_mapping(row.get("grid_exclusions"), "grid exclusions").get(reason, 0))
                    for row in validation_rows
                )
                for reason in (
                    "no_quote",
                    "stale_quote",
                    "nonpositive_bid",
                    "nonpositive_ask",
                    "zero_bid_size",
                    "zero_ask_size",
                    "crossed_market",
                    "total",
                    "eligible_locked_market_count",
                )
            },
            "maximum_raw_update_gap_ms": max(
                _decimal(row.get("maximum_raw_update_gap_ms"), "raw update gap")
                for row in validation_rows
            ),
        },
        "distributions": distributions,
        "quote_datasets": dataset_rows,
        "quote_datasets_fingerprint": fingerprint(dataset_rows),
        "authority": {
            "strategy_results": False,
            "protected_holdout": False,
            "paper_execution": False,
            "broker_writes": False,
            "live_execution": False,
        },
    }
    analysis["analysis_fingerprint"] = fingerprint(analysis)
    path = root / "analysis" / f"{analysis['analysis_fingerprint']}.json"
    _write_create_only(path, analysis)
    return cast(dict[str, object], json.loads(canonical_json(analysis)))


def _distribution(values: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    if not values:
        raise ValueError("quote distribution group is empty")
    result: dict[str, object] = {"count": len(values)}
    for metric in ("spread_dollars", "spread_bps", "half_spread_bps", "quote_age_ms"):
        ordered = sorted(_decimal(item.get(metric), metric) for item in values)
        percentiles = {
            name: _nearest_rank(ordered, percentile)
            for name, percentile in (
                ("p50", Decimal("0.50")),
                ("p75", Decimal("0.75")),
                ("p90", Decimal("0.90")),
                ("p95", Decimal("0.95")),
                ("p99", Decimal("0.99")),
            )
        }
        result[metric] = {
            "minimum": ordered[0],
            "median": percentiles["p50"],
            **percentiles,
            "maximum": ordered[-1],
        }
    return result


def _nearest_rank(values: Sequence[Decimal], percentile: Decimal) -> Decimal:
    rank = int((percentile * Decimal(len(values))).to_integral_value(rounding=ROUND_CEILING))
    return values[max(1, rank) - 1]


def _derived_sessions() -> tuple[date, ...]:
    calendar = xcals.get_calendar("XNYS")
    sessions = tuple(calendar.sessions_in_range("2025-07-01", "2026-05-31"))
    selected: set[date] = set()
    for year, month in (
        *((2025, month) for month in range(7, 13)),
        *((2026, month) for month in range(1, 6)),
    ):
        selected.add(
            next(
                item.date()
                for item in sessions
                if item.year == year and item.month == month and item.day >= 15
            )
        )
    for session in sessions:
        if calendar.session_close(session) - calendar.session_open(session) < timedelta(hours=6):
            selected.add(session.date())
    return tuple(sorted(selected))


def _session_windows(session: date) -> tuple[CalibrationWindow, ...]:
    calendar = xcals.get_calendar("XNYS")
    label = calendar.date_to_session(session.isoformat())
    opening = calendar.session_open(label).to_pydatetime().astimezone(UTC)
    closing = calendar.session_close(label).to_pydatetime().astimezone(UTC)
    duration = closing - opening
    starts = [
        ("opening", opening + timedelta(minutes=5)),
        ("morning", opening + timedelta(minutes=60)),
        ("midday", opening + duration / 2 - timedelta(minutes=5)),
    ]
    if duration >= timedelta(hours=6):
        starts.append(("afternoon", opening + timedelta(minutes=300)))
    starts.append(("closing", closing - timedelta(minutes=10)))
    return tuple(
        CalibrationWindow(session, name, start, start + timedelta(minutes=10), opening, closing)
        for name, start in starts
    )


def _quote(symbol: str, value: object) -> HistoricalQuote:
    item = _mapping(value, "historical quote")
    required = {"t", "bx", "bp", "bs", "ax", "ap", "as", "c", "z"}
    if required - set(item):
        raise QuoteAcquisitionError("Alpaca historical quote is missing fields")
    timestamp = _text(item, "t")
    conditions = item["c"]
    if (
        not isinstance(conditions, list)
        or len(conditions) not in {1, 2}
        or any(not isinstance(value, str) or not value for value in conditions)
    ):
        raise QuoteAcquisitionError("Alpaca historical quote conditions differ")
    return HistoricalQuote(
        symbol,
        timestamp,
        _timestamp_ns(timestamp),
        _text(item, "bx", allow_empty=True),
        _decimal(item["bp"], "bid price"),
        _nonnegative_int(item["bs"], "bid size"),
        _text(item, "ax", allow_empty=True),
        _decimal(item["ap"], "ask price"),
        _nonnegative_int(item["as"], "ask size"),
        tuple(conditions),
        _text(item, "z", allow_empty=True),
    )


def _timestamp_ns(value: str) -> int:
    match = _TIMESTAMP.fullmatch(value)
    if match is None:
        raise QuoteAcquisitionError("Alpaca historical quote timestamp differs")
    base = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    fraction = (match.group(2) or "").ljust(9, "0")
    return _datetime_ns(base) + int(fraction or "0")


def _datetime_ns(value: datetime) -> int:
    utc = value.astimezone(UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = utc - epoch
    return (delta.days * 86_400 + delta.seconds) * _NANOSECONDS + utc.microsecond * 1000


def _logical_key(plan: CalibrationPlan, feed: str, symbol: str, window: CalibrationWindow) -> str:
    return fingerprint(
        {
            "run_id": plan.run_id,
            "plan_fingerprint": plan.plan_fingerprint,
            "feed": feed,
            "symbol": symbol,
            "session_date": window.session_date.isoformat(),
            "window_id": window.window_id,
            "start": window.start,
            "end": window.end,
        }
    )


def _existing_artifact(
    layout: StorageLayout,
    plan: CalibrationPlan,
    logical_key: str,
) -> Mapping[str, Any] | None:
    matches: list[Mapping[str, Any]] = []
    if not layout.datasets.exists():
        return None
    for path in sorted(layout.datasets.glob("*/manifest.json")):
        manifest = _read_json(path)
        identity = _mapping(manifest.get("identity"), "quote dataset identity")
        if identity.get("logical_key") == logical_key:
            _verify_artifact(layout, plan, manifest)
            matches.append(manifest)
    if len(matches) > 1:
        raise ValueError("multiple immutable quote artifacts share one logical window")
    return matches[0] if matches else None


def _verify_artifact(
    layout: StorageLayout,
    plan: CalibrationPlan,
    manifest: Mapping[str, Any],
) -> None:
    if manifest.get("schema_version") != QUOTE_DATASET_SCHEMA:
        raise ValueError("quote dataset schema differs")
    identity = _mapping(manifest.get("identity"), "quote dataset identity")
    identity_fields = (
        "logical_key",
        "plan_fingerprint",
        "run_id",
        "feed",
        "symbol",
        "session_date",
        "window_id",
        "raw_sha256",
        "observation_sha256",
    )
    if set(identity) != {"dataset_id", *identity_fields}:
        raise ValueError("quote dataset identity fields differ")
    dataset_id = _text(identity, "dataset_id")
    feed = _text(identity, "feed")
    symbol = _text(identity, "symbol")
    session_date = date.fromisoformat(_text(identity, "session_date"))
    window_id = _text(identity, "window_id")
    window = next(
        (
            item
            for item in plan.windows
            if item.session_date == session_date and item.window_id == window_id
        ),
        None,
    )
    if (
        identity.get("plan_fingerprint") != plan.plan_fingerprint
        or identity.get("run_id") != plan.run_id
        or manifest.get("program_id") != PROGRAM_ID
        or manifest.get("run_id") != plan.run_id
        or manifest.get("plan_sha256") != plan.sha256
        or feed not in {"sip", "iex"}
        or symbol not in plan.symbols
        or window is None
        or identity.get("logical_key") != _logical_key(plan, feed, symbol, window)
    ):
        raise ValueError("quote dataset identity differs from the frozen plan")
    derived_identity = {field: identity[field] for field in identity_fields}
    if dataset_id != fingerprint(derived_identity):
        raise ValueError("quote dataset ID differs from its identity")
    if manifest.get("raw_sha256") != identity.get("raw_sha256") or manifest.get(
        "observation_sha256"
    ) != identity.get("observation_sha256"):
        raise ValueError("quote dataset manifest hashes differ from its identity")
    path = layout.dataset(dataset_id)
    raw_sha = hashlib.sha256((path / "raw.jsonl").read_bytes()).hexdigest()
    observation_sha = hashlib.sha256((path / "observations.jsonl").read_bytes()).hexdigest()
    if raw_sha != manifest.get("raw_sha256") or observation_sha != manifest.get(
        "observation_sha256"
    ):
        raise ValueError("quote dataset artifact hash differs")
    if _read_json(path / "manifest.json") != manifest:
        raise ValueError("quote dataset manifest differs")


def _selected_feed(
    layout: StorageLayout,
    plan: CalibrationPlan,
    selection: Mapping[str, Any],
) -> str:
    if set(selection) != {
        "schema_version",
        "program_id",
        "run_id",
        "plan_fingerprint",
        "feed",
        "reason",
        "probe_dataset_id",
        "selected_at",
    }:
        raise ValueError("stored quote feed selection fields differ")
    feed = _text(selection, "feed")
    expected_reason = {
        "sip": "sip-authorized",
        "iex": "sip-http-403-entitlement-fallback",
    }.get(feed)
    if (
        selection.get("schema_version") != "intraday-quote-feed-selection-v2"
        or selection.get("program_id") != PROGRAM_ID
        or selection.get("run_id") != plan.run_id
        or selection.get("plan_fingerprint") != plan.plan_fingerprint
        or selection.get("reason") != expected_reason
    ):
        raise ValueError("stored quote feed selection differs from the frozen plan")
    _timestamp_ns(_text(selection, "selected_at"))
    logical_key = _logical_key(plan, feed, plan.symbols[0], plan.windows[0])
    probe = _existing_artifact(layout, plan, logical_key)
    if probe is None or _mapping(probe.get("identity"), "probe identity").get(
        "dataset_id"
    ) != _text(selection, "probe_dataset_id"):
        raise ValueError("stored quote feed selection probe differs")
    return feed


def _write_create_only(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = canonical_json(value) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != serialized:
            raise ValueError(f"immutable artifact differs: {path}")
        return
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(serialized)
        stream.flush()
        os.fsync(stream.fileno())


def _read_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return _mapping(value, str(path))


def _read_json_lines(path: Path) -> list[Mapping[str, Any]]:
    return [
        _mapping(json.loads(line), str(path))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _text(value: Mapping[str, Any], key: str, *, allow_empty: bool = False) -> str:
    item = value.get(key)
    if not isinstance(item, str) or (not allow_empty and not item):
        raise ValueError(f"{key} must be text")
    return item


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise QuoteAcquisitionError(f"Alpaca historical quote {label} differs")
    return value


def _decimal(value: object, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{label} must be decimal") from error
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _urlopen_bytes(request: Request) -> bytes:
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed endpoint in reviewed plan
        return cast(bytes, response.read())


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect-plan", "acquire", "analyze"))
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--data-home", type=Path, required=True)
    parsed = parser.parse_args(arguments)
    if parsed.action == "inspect-plan":
        plan = load_calibration_plan(parsed.repository)
        result: Mapping[str, object] = {
            "program_id": PROGRAM_ID,
            "run_id": plan.run_id,
            "plan_sha256": plan.sha256,
            "plan_fingerprint": plan.plan_fingerprint,
            "session_count": len(plan.sessions),
            "window_count": len(plan.windows),
            "dataset_count": len(plan.windows) * len(plan.symbols),
        }
    elif parsed.action == "acquire":
        api_key = os.environ.get("APCA_API_KEY_ID", "")
        secret_key = os.environ.get("APCA_API_SECRET_KEY", "")
        result = acquire_calibration_quotes(
            parsed.repository,
            parsed.data_home,
            api_key,
            secret_key,
            progress=lambda message: print(message, file=sys.stderr, flush=True),
        )
    else:
        result = analyze_calibration_quotes(parsed.repository, parsed.data_home)
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
