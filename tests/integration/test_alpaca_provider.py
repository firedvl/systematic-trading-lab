import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

import pytest

from systematic_trading_lab.calendar import expected_bar_timestamps
from systematic_trading_lab.datasets import DatasetService, DatasetValidationError
from systematic_trading_lab.domain import AdjustmentPolicy, Symbol, Timeframe, TimestampRange
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.providers import (
    AlpacaHistoricalProvider,
    ProviderRecords,
    YahooHistoricalProvider,
)
from systematic_trading_lab.storage import StorageLayout
from systematic_trading_lab.universe import load_intraday_universe


def _alpaca_bar(timestamp: str) -> dict[str, object]:
    return {"t": timestamp, "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 10}


def _yahoo_payload(*timestamps: int) -> dict[str, object]:
    return {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {
                        "symbol": "SPY",
                        "instrumentType": "ETF",
                        "currency": "USD",
                        "exchangeTimezoneName": "America/New_York",
                        "dataGranularity": "1d",
                    },
                    "timestamp": list(timestamps),
                    "indicators": {
                        "quote": [
                            {
                                "open": [99] * len(timestamps),
                                "high": [101] * len(timestamps),
                                "low": [98] * len(timestamps),
                                "close": [100] * len(timestamps),
                                "volume": [10] * len(timestamps),
                            }
                        ],
                        "adjclose": [{"adjclose": [80] * len(timestamps)}],
                    },
                }
            ],
        }
    }


def test_alpaca_provider_paginates_and_normalizes_daily_bars() -> None:
    requests: list[Request] = []
    payloads = iter(
        [
            {
                "bars": {
                    "SPY": [
                        {
                            "t": "2025-01-06T05:00:00Z",
                            "o": 100,
                            "h": 101,
                            "l": 99,
                            "c": 100.5,
                            "v": 10,
                        }
                    ]
                },
                "next_page_token": "page-2",
            },
            {
                "bars": {
                    "SPY": [
                        {
                            "t": "2025-01-07T05:00:00Z",
                            "o": 101,
                            "h": 102,
                            "l": 100,
                            "c": 101.5,
                            "v": 11,
                        }
                    ]
                },
                "next_page_token": None,
            },
        ]
    )

    def transport(request: Request) -> bytes:
        requests.append(request)
        return json.dumps(next(payloads)).encode()

    provider = AlpacaHistoricalProvider("test-key", "test-secret", transport=transport)
    records = provider.fetch(
        [Symbol("SPY")],
        Timeframe.DAILY,
        TimestampRange(datetime(2025, 1, 6, tzinfo=UTC), datetime(2025, 1, 7, tzinfo=UTC)),
    )

    assert len(records) == 2
    assert records[0]["timestamp"] == "2025-01-06T00:00:00Z"
    assert len(requests) == 2
    assert provider.adjustment_policy is AdjustmentPolicy.PROVIDER_ADJUSTED_ALL
    first_query = parse_qs(urlparse(str(requests[0].full_url)).query)
    assert first_query["adjustment"] == ["all"]
    assert first_query["end"] == ["2025-01-08T00:00:00Z"]
    assert parse_qs(urlparse(str(requests[1].full_url)).query)["page_token"] == ["page-2"]
    assert requests[0].headers["Apca-api-key-id"] == "test-key"


@pytest.mark.parametrize(
    ("timeframe", "provider_value", "duration"),
    (
        (Timeframe.ONE_MINUTE, "1Min", timedelta(minutes=1)),
        (Timeframe.FIVE_MINUTES, "5Min", timedelta(minutes=5)),
    ),
)
def test_alpaca_provider_preserves_intraday_bar_open_timestamp(
    timeframe: Timeframe, provider_value: str, duration: timedelta
) -> None:
    requests: list[Request] = []

    def transport(request: Request) -> bytes:
        requests.append(request)
        return json.dumps(
            {
                "bars": {
                    "SPY": [
                        {
                            "t": "2025-01-06T14:30:00Z",
                            "o": 100,
                            "h": 101,
                            "l": 99,
                            "c": 100.5,
                            "v": 10,
                        }
                    ]
                },
                "next_page_token": None,
            }
        ).encode()

    requested = TimestampRange(
        datetime(2025, 1, 6, 14, 30, tzinfo=UTC),
        datetime(2025, 1, 6, 14, 30, tzinfo=UTC),
    )
    records = AlpacaHistoricalProvider("test-key", "test-secret", transport=transport).fetch(
        [Symbol("SPY")], timeframe, requested
    )

    assert records[0]["timestamp"] == "2025-01-06T14:30:00Z"
    query = parse_qs(urlparse(str(requests[0].full_url)).query)
    assert query["timeframe"] == [provider_value]
    assert query["end"] == [(requested.end + duration).isoformat().replace("+00:00", "Z")]


def test_alpaca_provider_ends_partial_range_after_last_expected_bar() -> None:
    requests: list[Request] = []

    def transport(request: Request) -> bytes:
        requests.append(request)
        return json.dumps(
            {
                "bars": {
                    "SPY": [
                        {
                            "t": "2025-01-06T14:30:00Z",
                            "o": 100,
                            "h": 101,
                            "l": 99,
                            "c": 100.5,
                            "v": 10,
                        }
                    ]
                },
                "next_page_token": None,
            }
        ).encode()

    provider = AlpacaHistoricalProvider("test-key", "test-secret", transport=transport)
    records = provider.fetch(
        [Symbol("SPY")],
        Timeframe.FIVE_MINUTES,
        TimestampRange(
            datetime(2025, 1, 6, 14, 30, tzinfo=UTC),
            datetime(2025, 1, 6, 14, 32, tzinfo=UTC),
        ),
    )

    assert len(records) == 1
    query = parse_qs(urlparse(str(requests[0].full_url)).query)
    assert query["end"] == ["2025-01-06T14:35:00Z"]


@pytest.mark.parametrize(
    ("timeframe", "last_normal", "last_early"),
    (
        (Timeframe.ONE_MINUTE, "20:59:00Z", "17:59:00Z"),
        (Timeframe.FIVE_MINUTES, "20:55:00Z", "17:55:00Z"),
    ),
)
def test_alpaca_provider_returns_only_requested_xnys_bar_opens(
    timeframe: Timeframe, last_normal: str, last_early: str
) -> None:
    requested = TimestampRange(
        datetime(2025, 11, 26, 14, 30, tzinfo=UTC),
        datetime.fromisoformat(f"2025-11-28T{last_early}".replace("Z", "+00:00")),
    )
    expected = expected_bar_timestamps(requested.start, requested.end, timeframe)
    normal = [timestamp for timestamp in expected if timestamp.date().day == 26]
    early = [timestamp for timestamp in expected if timestamp.date().day == 28]
    timestamps = [
        "2025-11-26T13:00:00Z",  # premarket
        *(timestamp.isoformat().replace("+00:00", "Z") for timestamp in normal),
        "2025-11-26T21:00:00Z",  # normal close boundary
        "2025-11-26T21:05:00Z",  # postmarket
        *(timestamp.isoformat().replace("+00:00", "Z") for timestamp in early),
        "2025-11-28T18:00:00Z",  # early-close boundary
        "2025-11-28T18:05:00Z",  # after the early close
    ]

    def transport(request: Request) -> bytes:
        return json.dumps(
            {
                "bars": {"SPY": [_alpaca_bar(timestamp) for timestamp in timestamps]},
                "next_page_token": None,
            }
        ).encode()

    records = AlpacaHistoricalProvider("test-key", "test-secret", transport=transport).fetch(
        [Symbol("SPY")],
        timeframe,
        requested,
    )

    assert [record["timestamp"] for record in records] == [
        timestamp.isoformat().replace("+00:00", "Z") for timestamp in expected
    ]


def test_dataset_retains_filtered_transport_extras_as_raw_evidence(tmp_path: Path) -> None:
    timeframe = Timeframe.FIVE_MINUTES
    requested = TimestampRange(
        datetime(2025, 11, 26, 14, 30, tzinfo=UTC),
        datetime(2025, 11, 28, 17, 55, tzinfo=UTC),
    )
    expected = expected_bar_timestamps(requested.start, requested.end, timeframe)
    bars = {
        symbol: [
            _alpaca_bar("2025-11-26T13:00:00Z"),
            *(_alpaca_bar(timestamp.isoformat().replace("+00:00", "Z")) for timestamp in expected),
            _alpaca_bar("2025-11-28T18:00:00Z"),
        ]
        for symbol in ("SPY", "QQQ")
    }

    def transport(request: Request) -> bytes:
        return json.dumps({"bars": bars, "next_page_token": None}).encode()

    service = DatasetService(StorageLayout(tmp_path))
    imported = service.import_from(
        AlpacaHistoricalProvider("test-key", "test-secret", transport=transport),
        (Symbol("SPY"), Symbol("QQQ")),
        timeframe,
        requested,
        load_intraday_universe(timeframe),
    )

    normalized = service.load_bars(imported.dataset_id)
    raw = [
        json.loads(line)
        for line in (service.layout.dataset(imported.dataset_id) / "raw.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    manifest = service.describe(imported.dataset_id)
    assert len(normalized) == 2 * len(expected)
    assert len(raw) == len(normalized) + 4
    assert {record["timestamp"] for record in raw} >= {
        "2025-11-26T13:00:00Z",
        "2025-11-28T18:00:00Z",
    }
    assert fingerprint(raw) == manifest["raw_artifact_hashes"][0]
    assert service.validate(imported.dataset_id)["valid"] is True


@pytest.mark.parametrize(
    "defect", ("missing", "duplicate", "invalid", "invalid-extra", "unexpected-symbol")
)
def test_filtered_alpaca_records_still_fail_dataset_validation(tmp_path: Path, defect: str) -> None:
    timeframe = Timeframe.FIVE_MINUTES
    requested = TimestampRange(
        datetime(2025, 1, 6, 14, 30, tzinfo=UTC),
        datetime(2025, 1, 6, 14, 35, tzinfo=UTC),
    )
    timestamps = ("2025-01-06T14:30:00Z", "2025-01-06T14:35:00Z")
    bars = {
        symbol: [
            _alpaca_bar("2025-01-06T13:00:00Z"),
            *(_alpaca_bar(value) for value in timestamps),
        ]
        for symbol in ("SPY", "QQQ")
    }
    if defect == "missing":
        bars["SPY"].pop()
    elif defect == "duplicate":
        bars["SPY"].append(_alpaca_bar(timestamps[-1]))
    elif defect == "invalid":
        bars["SPY"][1]["h"] = 0
    elif defect == "invalid-extra":
        bars["SPY"][0]["h"] = 0
    else:
        bars["IWM"] = [_alpaca_bar("2025-01-06T13:00:00Z")]

    def transport(request: Request) -> bytes:
        return json.dumps({"bars": bars, "next_page_token": None}).encode()

    layout = StorageLayout(tmp_path)
    with pytest.raises(DatasetValidationError, match="dataset rejected"):
        DatasetService(layout).import_from(
            AlpacaHistoricalProvider("test-key", "test-secret", transport=transport),
            (Symbol("SPY"), Symbol("QQQ")),
            timeframe,
            requested,
            load_intraday_universe(timeframe),
        )

    evidence = json.loads(next(layout.quarantine.glob("*.json")).read_text(encoding="utf-8"))
    assert not list(layout.datasets.iterdir())
    acquisition_raw = evidence["acquisition_raw_records"]
    assert any(record["timestamp"] == "2025-01-06T13:00:00Z" for record in acquisition_raw)
    assert fingerprint(acquisition_raw) == evidence["acquisition_raw_fingerprint"]
    if defect == "missing":
        assert evidence["validation"]["missing_intervals"]
    elif defect == "duplicate":
        assert evidence["validation"]["duplicate_intervals"]
    else:
        assert evidence["validation"]["errors"]


@pytest.mark.parametrize(
    "payload",
    (
        {"bars": []},
        {"bars": {"SPY": [{"t": "2025-01-06T14:30:00Z"}]}},
        {"bars": {"SPY": [{"t": "2025-01-06T13:00:00Z"}]}},
    ),
)
def test_alpaca_provider_rejects_malformed_responses(payload: object) -> None:
    def transport(request: Request) -> bytes:
        return json.dumps(payload).encode()

    with pytest.raises(RuntimeError, match="Alpaca"):
        AlpacaHistoricalProvider("test-key", "test-secret", transport=transport).fetch(
            [Symbol("SPY")],
            Timeframe.FIVE_MINUTES,
            TimestampRange(
                datetime(2025, 1, 6, 14, 30, tzinfo=UTC),
                datetime(2025, 1, 6, 14, 30, tzinfo=UTC),
            ),
        )


def test_yahoo_provider_binds_metadata_and_scales_daily_ohlc() -> None:
    requests: list[Request] = []
    vendor_timestamp = int(datetime(2025, 1, 6, 14, 30, tzinfo=UTC).timestamp())

    def transport(request: Request) -> bytes:
        requests.append(request)
        return json.dumps(_yahoo_payload(vendor_timestamp)).encode()

    requested = TimestampRange(datetime(2025, 1, 6, tzinfo=UTC), datetime(2025, 1, 6, tzinfo=UTC))
    records = YahooHistoricalProvider(transport=transport).fetch(
        [Symbol("SPY")], Timeframe.DAILY, requested
    )

    assert isinstance(records, ProviderRecords)
    assert records[0] == {
        "symbol": "SPY",
        "timestamp": "2025-01-06T00:00:00Z",
        "open": "79.2",
        "high": "80.8",
        "low": "78.4",
        "close": "80",
        "volume": 10,
    }
    assert records.raw_records[0]["vendor_timestamp"] == vendor_timestamp
    assert records.raw_records[0]["adjusted_close"] == 80
    assert records.raw_records[0]["instrument_type"] == "ETF"
    assert records.raw_records[0]["currency"] == "USD"
    assert records.raw_records[0]["exchange_timezone"] == "America/New_York"
    assert records.raw_records[0]["data_granularity"] == "1d"
    assert requests[0].headers["User-agent"].startswith("Mozilla/5.0")
    query = parse_qs(urlparse(str(requests[0].full_url)).query)
    assert query["period1"] == [str(int(requested.start.timestamp()))]
    assert query["period2"] == [str(int((requested.end + timedelta(days=1)).timestamp()))]
    assert query["includeAdjustedClose"] == ["true"]


def test_yahoo_provider_rejects_non_xnys_daily_records() -> None:
    saturday = int(datetime(2025, 1, 11, 14, 30, tzinfo=UTC).timestamp())

    def transport(request: Request) -> bytes:
        return json.dumps(_yahoo_payload(saturday)).encode()

    with pytest.raises(RuntimeError, match="Yahoo historical data request failed"):
        YahooHistoricalProvider(transport=transport).fetch(
            [Symbol("SPY")],
            Timeframe.DAILY,
            TimestampRange(datetime(2025, 1, 6, tzinfo=UTC), datetime(2025, 1, 11, tzinfo=UTC)),
        )
