from __future__ import annotations

import hashlib
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
    QUOTE_DATASET_SCHEMA,
    REVIEWED_PLAN_SHA256,
    RUN_ID,
    AlpacaHistoricalQuoteClient,
    CalibrationWindow,
    HistoricalQuote,
    QuoteAcquisitionError,
    _distribution,
    _logical_key,
    _selected_feed,
    _verify_artifact,
    acquire_quote_window,
    load_calibration_plan,
    sample_quotes,
    validate_quote_sequence,
)
from systematic_trading_lab.storage import StorageLayout

_REPOSITORY = Path(__file__).resolve().parents[2]


def _quote(
    timestamp: str,
    bid: str,
    ask: str,
    *,
    bid_size: int = 10,
    ask_size: int = 12,
) -> HistoricalQuote:
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
        bid_size,
        "V",
        Decimal(ask),
        ask_size,
        ("R",),
        "B",
    )


def test_frozen_plan_derives_calendar_sample_without_june() -> None:
    plan = load_calibration_plan(_REPOSITORY)

    assert plan.sha256 == REVIEWED_PLAN_SHA256
    assert plan.run_id == RUN_ID
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

        def __init__(
            self,
            api_key: str,
            secret_key: str,
            feed: str,
            *,
            on_quote_data_returned: calibration.QuoteDataCallback | None = None,
        ) -> None:
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


def test_prior_sip_data_marker_blocks_later_iex_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    constructed_feeds: list[str] = []
    sip_attempts = 0

    class RetryClient:
        endpoint = calibration.ALPACA_QUOTES_ENDPOINT

        def __init__(
            self,
            api_key: str,
            secret_key: str,
            feed: str,
            *,
            on_quote_data_returned: calibration.QuoteDataCallback | None = None,
        ) -> None:
            constructed_feeds.append(feed)
            self.feed = feed
            self.on_quote_data_returned = on_quote_data_returned

        def fetch(self, symbol: str, start: datetime, end: datetime) -> tuple[HistoricalQuote, ...]:
            nonlocal sip_attempts
            assert self.feed == "sip"
            sip_attempts += 1
            if sip_attempts == 1:
                assert self.on_quote_data_returned is not None
                self.on_quote_data_returned()
                raise QuoteAcquisitionError(
                    "SIP failed after returning data",
                    500,
                    quote_data_returned=True,
                )
            raise QuoteAcquisitionError("SIP forbidden", 403)

    monkeypatch.setattr(calibration, "AlpacaHistoricalQuoteClient", RetryClient)

    with pytest.raises(QuoteAcquisitionError, match="after returning data"):
        calibration.acquire_calibration_quotes(_REPOSITORY, tmp_path, "key", "secret")
    marker = tmp_path / RUN_ID / "sip-quote-data-returned.json"
    assert marker.exists()

    with pytest.raises(QuoteAcquisitionError, match="SIP forbidden"):
        calibration.acquire_calibration_quotes(_REPOSITORY, tmp_path, "key", "secret")

    assert constructed_feeds == ["sip", "sip"]


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
    observations, exclusions = sample_quotes(quotes, "iex", window)

    assert validation["exact_duplicate_count"] == 1
    assert validation["same_timestamp_update_count"] == 1
    assert exclusions["total"] == 0
    assert len(observations) == 3
    assert observations[0].quote_timestamp == first.timestamp
    assert observations[1].quote_timestamp == latest.timestamp
    assert observations[0].spread_dollars == Decimal("0.02")


def test_crossed_latest_state_is_excluded_without_backfill() -> None:
    start = datetime(2025, 7, 15, 13, 35, tzinfo=UTC)
    window = CalibrationWindow(
        date(2025, 7, 15),
        "opening",
        start,
        start + timedelta(seconds=3),
        start - timedelta(minutes=5),
        start + timedelta(hours=6, minutes=25),
    )
    first = _quote("2025-07-15T13:34:59.900000000Z", "100.00", "100.02")
    crossed = _quote("2025-07-15T13:35:00.500000000Z", "100.03", "100.02")
    recovered = _quote("2025-07-15T13:35:01.500000000Z", "100.02", "100.04")
    quotes, validation = validate_quote_sequence(
        (first, crossed, recovered),
        "SPY",
        window.request_start,
        window.end,
    )

    observations, exclusions = sample_quotes(quotes, "sip", window)

    assert validation["raw_crossed_market_count"] == 1
    assert exclusions["crossed_market"] == 1
    assert exclusions["total"] == 1
    assert [item.quote_timestamp for item in observations] == [first.timestamp, recovered.timestamp]


@pytest.mark.parametrize(
    ("bid", "ask", "bid_size", "ask_size", "reason"),
    (
        ("0", "100.02", 10, 12, "nonpositive_bid"),
        ("100", "0", 10, 12, "nonpositive_ask"),
        ("100", "100.02", 0, 12, "zero_bid_size"),
        ("100", "100.02", 10, 0, "zero_ask_size"),
    ),
)
def test_one_sided_latest_state_is_grid_ineligible(
    bid: str,
    ask: str,
    bid_size: int,
    ask_size: int,
    reason: str,
) -> None:
    start = datetime(2025, 7, 15, 13, 35, tzinfo=UTC)
    window = CalibrationWindow(
        date(2025, 7, 15),
        "opening",
        start,
        start + timedelta(seconds=1),
        start - timedelta(minutes=5),
        start + timedelta(hours=6, minutes=25),
    )
    quote = _quote(
        "2025-07-15T13:34:59.500000000Z",
        bid,
        ask,
        bid_size=bid_size,
        ask_size=ask_size,
    )

    observations, exclusions = sample_quotes((quote,), "sip", window)

    assert observations == ()
    assert exclusions[reason] == 1
    assert exclusions["total"] == 1


def test_locked_latest_state_is_eligible_with_zero_spread() -> None:
    start = datetime(2025, 7, 15, 13, 35, tzinfo=UTC)
    window = CalibrationWindow(
        date(2025, 7, 15),
        "opening",
        start,
        start + timedelta(seconds=1),
        start - timedelta(minutes=5),
        start + timedelta(hours=6, minutes=25),
    )
    quote = _quote("2025-07-15T13:34:59.500000000Z", "100.00", "100.00")

    observations, exclusions = sample_quotes((quote,), "sip", window)

    assert observations[0].spread_bps == 0
    assert exclusions["eligible_locked_market_count"] == 1
    assert exclusions["total"] == 0


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
        "run_id": plan.run_id,
        "feed": "sip",
        "symbol": "QQQ",
        "session_date": window.session_date.isoformat(),
        "window_id": window.window_id,
        "raw_sha256": "1" * 64,
        "observation_sha256": "2" * 64,
    }
    manifest = {
        "schema_version": QUOTE_DATASET_SCHEMA,
        "program_id": "intraday-execution-calibration-001",
        "run_id": plan.run_id,
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
        "schema_version": "intraday-quote-feed-selection-v2",
        "program_id": "intraday-execution-calibration-001",
        "run_id": plan.run_id,
        "plan_fingerprint": plan.plan_fingerprint,
        "feed": "sip",
        "reason": "sip-authorized",
        "probe_dataset_id": "0" * 64,
        "selected_at": "2026-08-20T22:00:00Z",
    }

    with pytest.raises(ValueError, match="probe differs"):
        _selected_feed(StorageLayout(tmp_path), plan, selection)


def test_v1_plan_and_failure_record_remain_closed_evidence() -> None:
    plan = _REPOSITORY / "config/research/intraday-execution-calibration-001-plan-v1.json"
    failure = (
        _REPOSITORY / "config/research/intraday-execution-calibration-001-plan-v1-failure-v1.json"
    )

    assert hashlib.sha256(plan.read_bytes()).hexdigest() == (
        "7f762cb4195b406c8b86197bc02f36e562d65af559f8ae1c0070ce05a40d9e38"
    )
    assert hashlib.sha256(failure.read_bytes()).hexdigest() == (
        "2bab01f3cc5b4e5809e80d4ce2ab11e32038d23ba129d754ca1a46419a129ef0"
    )
    assert json.loads(failure.read_text())["outcome"] == "failed-before-dataset-publication"
    assert RUN_ID != "intraday-execution-calibration-001"


def test_failed_v2_window_records_bound_quarantine_without_dataset(tmp_path: Path) -> None:
    plan = load_calibration_plan(_REPOSITORY)
    window = plan.windows[0]
    timestamp = (window.start - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    response = {
        "quotes": {
            "SPY": [
                {
                    "t": timestamp,
                    "bx": "V",
                    "bp": 100,
                    "bs": 10,
                    "ax": "V",
                    "ap": 100.01,
                    "as": 12,
                    "c": ["R"],
                    "z": "B",
                }
            ]
        },
        "next_page_token": None,
    }
    client = AlpacaHistoricalQuoteClient(
        "key",
        "secret",
        "sip",
        transport=lambda request: json.dumps(response).encode(),
    )

    with pytest.raises(ValueError, match="eligible grid coverage"):
        acquire_quote_window(tmp_path, plan, client, window, "SPY")

    quarantine = next((tmp_path / plan.run_id / "quarantine").glob("*.json"))
    evidence = json.loads(quarantine.read_text())
    assert evidence["plan_sha256"] == plan.sha256
    assert evidence["plan_fingerprint"] == plan.plan_fingerprint
    assert evidence["run_id"] == plan.run_id
    assert evidence["feed"] == "sip"
    assert evidence["symbol"] == "SPY"
    assert Decimal(evidence["validation"]["eligible_grid_coverage"]) < Decimal("0.99")
    assert not any((tmp_path / plan.run_id / "datasets").iterdir())
