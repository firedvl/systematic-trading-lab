from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest

import systematic_trading_lab.intraday_cost_calibration as calibration
from systematic_trading_lab.intraday_cost_calibration import (
    REVIEWED_PLAN_SHA256,
    AlpacaHistoricalQuoteClient,
    CalibrationWindow,
    HistoricalQuote,
    QuoteAcquisitionError,
    _distribution,
    _logical_key,
    _selected_feed,
    _verify_artifact,
    load_calibration_plan,
    sample_quotes,
    validate_quote_sequence,
)
from systematic_trading_lab.storage import StorageLayout

_REPOSITORY = Path(__file__).resolve().parents[2]


def _quote(timestamp: str, bid: str, ask: str) -> HistoricalQuote:
    base, fraction = timestamp.removesuffix("Z").split(".")
    seconds = int(
        (
            datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
            - datetime(1970, 1, 1, tzinfo=UTC)
        ).total_seconds()
    )
    timestamp_ns = seconds * 1_000_000_000 + int(fraction.ljust(9, "0"))
    return HistoricalQuote(
        "SPY",
        timestamp,
        timestamp_ns,
        "V",
        Decimal(bid),
        10,
        "V",
        Decimal(ask),
        12,
        ("R",),
        "B",
    )


def test_frozen_plan_derives_calendar_sample_without_june() -> None:
    plan = load_calibration_plan(_REPOSITORY)

    assert plan.sha256 == REVIEWED_PLAN_SHA256
    assert len(plan.sessions) == 14
    assert len(plan.windows) == 67
    assert date(2025, 7, 3) in plan.sessions
    assert date(2025, 11, 28) in plan.sessions
    assert date(2025, 12, 24) in plan.sessions
    assert all(session < date(2026, 6, 1) for session in plan.sessions)


def test_historical_quote_client_paginates_and_keeps_nanoseconds() -> None:
    pages = [
        {
            "quotes": {
                "SPY": [
                    {
                        "t": "2025-07-15T13:34:59.123456789Z",
                        "bx": "V",
                        "bp": 600.01,
                        "bs": 10,
                        "ax": "V",
                        "ap": 600.02,
                        "as": 12,
                        "c": ["R"],
                        "z": "B",
                    }
                ]
            },
            "next_page_token": "next",
        },
        {
            "quotes": {
                "SPY": [
                    {
                        "t": "2025-07-15T13:34:59.123456790Z",
                        "bx": "V",
                        "bp": 600.02,
                        "bs": 11,
                        "ax": "V",
                        "ap": 600.03,
                        "as": 13,
                        "c": ["R"],
                        "z": "B",
                    }
                ]
            },
            "next_page_token": None,
        },
    ]
    requests: list[Request] = []

    def transport(request: Request) -> bytes:
        requests.append(request)
        return json.dumps(pages[len(requests) - 1]).encode()

    client = AlpacaHistoricalQuoteClient("key", "secret", "iex", transport=transport)
    quotes = client.fetch(
        "SPY",
        datetime(2025, 7, 15, 13, 34, 55, tzinfo=UTC),
        datetime(2025, 7, 15, 13, 45, tzinfo=UTC),
    )

    assert len(requests) == 2
    assert parse_qs(urlsplit(requests[1].full_url).query)["page_token"] == ["next"]
    assert quotes[1].timestamp_ns - quotes[0].timestamp_ns == 1
    assert quotes[0].bid_price == Decimal("600.01")


def test_quote_client_records_data_before_later_entitlement_failure() -> None:
    requests = 0

    def transport(request: Request) -> bytes:
        nonlocal requests
        requests += 1
        if requests == 1:
            return json.dumps(
                {
                    "quotes": {
                        "SPY": [
                            {
                                "t": "2025-07-15T13:34:59.123456789Z",
                                "bx": "V",
                                "bp": 600.01,
                                "bs": 10,
                                "ax": "V",
                                "ap": 600.02,
                                "as": 12,
                                "c": ["R"],
                                "z": "B",
                            }
                        ]
                    },
                    "next_page_token": "next",
                }
            ).encode()
        raise HTTPError(request.full_url, 403, "forbidden", Message(), None)

    client = AlpacaHistoricalQuoteClient("key", "secret", "sip", transport=transport)

    with pytest.raises(QuoteAcquisitionError) as raised:
        client.fetch(
            "SPY",
            datetime(2025, 7, 15, 13, 34, 55, tzinfo=UTC),
            datetime(2025, 7, 15, 13, 45, tzinfo=UTC),
        )

    assert raised.value.status_code == 403
    assert raised.value.quote_data_returned


def test_partial_sip_data_cannot_trigger_iex_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    constructed_feeds: list[str] = []

    class PartialSipClient:
        endpoint = calibration.ALPACA_QUOTES_ENDPOINT

        def __init__(self, api_key: str, secret_key: str, feed: str) -> None:
            constructed_feeds.append(feed)
            self.feed = feed

        def fetch(self, symbol: str, start: datetime, end: datetime) -> tuple[HistoricalQuote, ...]:
            raise QuoteAcquisitionError(
                "partial SIP response failed",
                403,
                quote_data_returned=True,
            )

    monkeypatch.setattr(calibration, "AlpacaHistoricalQuoteClient", PartialSipClient)

    with pytest.raises(QuoteAcquisitionError, match="partial SIP response failed"):
        calibration.acquire_calibration_quotes(_REPOSITORY, tmp_path, "key", "secret")

    assert constructed_feeds == ["sip"]


def test_quote_validation_and_grid_sampling_are_causal() -> None:
    start = datetime(2025, 7, 15, 13, 35, tzinfo=UTC)
    window = CalibrationWindow(
        date(2025, 7, 15),
        "opening",
        start,
        start + timedelta(seconds=3),
        start - timedelta(minutes=5),
        start + timedelta(hours=6, minutes=25),
    )
    first = _quote("2025-07-15T13:34:59.000000000Z", "100.00", "100.02")
    changed = _quote("2025-07-15T13:35:00.000000000Z", "100.01", "100.03")
    same_timestamp = _quote("2025-07-15T13:35:00.000000000Z", "100.02", "100.04")
    latest = _quote("2025-07-15T13:35:00.500000000Z", "100.03", "100.05")
    quotes, validation = validate_quote_sequence(
        (first, first, changed, same_timestamp, latest),
        "SPY",
        window.request_start,
        window.end,
    )
    observations, missing = sample_quotes(quotes, "iex", window)

    assert validation["exact_duplicate_count"] == 1
    assert validation["same_timestamp_update_count"] == 1
    assert missing == 0
    assert len(observations) == 3
    assert observations[0].quote_timestamp == first.timestamp
    assert observations[1].quote_timestamp == latest.timestamp
    assert observations[0].spread_dollars == Decimal("0.02")


def test_distribution_uses_nearest_rank_percentiles() -> None:
    rows = [
        {
            "spread_dollars": str(value),
            "spread_bps": str(value),
            "half_spread_bps": str(value / 2),
            "quote_age_ms": str(value * 10),
        }
        for value in map(Decimal, ("1", "2", "3", "4"))
    ]

    distribution = _distribution(rows)

    assert distribution["spread_bps"]["median"] == Decimal("2")  # type: ignore[index]
    assert distribution["spread_bps"]["p75"] == Decimal("3")  # type: ignore[index]
    assert distribution["spread_bps"]["p99"] == Decimal("4")  # type: ignore[index]


def test_quote_artifact_identity_is_rederived_before_reuse(tmp_path: Path) -> None:
    plan = load_calibration_plan(_REPOSITORY)
    window = plan.windows[0]
    identity = {
        "dataset_id": "0" * 64,
        "logical_key": _logical_key(plan, "sip", "QQQ", window),
        "plan_fingerprint": plan.plan_fingerprint,
        "feed": "sip",
        "symbol": "QQQ",
        "session_date": window.session_date.isoformat(),
        "window_id": window.window_id,
        "raw_sha256": "1" * 64,
        "observation_sha256": "2" * 64,
    }
    manifest = {
        "schema_version": "intraday-quote-calibration-dataset-v1",
        "identity": identity,
        "plan_sha256": plan.sha256,
        "raw_sha256": identity["raw_sha256"],
        "observation_sha256": identity["observation_sha256"],
    }

    with pytest.raises(ValueError, match="ID differs"):
        _verify_artifact(StorageLayout(tmp_path), plan, manifest)


def test_feed_selection_requires_its_frozen_probe_dataset(tmp_path: Path) -> None:
    plan = load_calibration_plan(_REPOSITORY)
    selection = {
        "schema_version": "intraday-quote-feed-selection-v1",
        "program_id": "intraday-execution-calibration-001",
        "plan_fingerprint": plan.plan_fingerprint,
        "feed": "sip",
        "reason": "sip-authorized",
        "probe_dataset_id": "0" * 64,
        "selected_at": "2026-08-20T22:00:00Z",
    }

    with pytest.raises(ValueError, match="probe differs"):
        _selected_feed(StorageLayout(tmp_path), plan, selection)
