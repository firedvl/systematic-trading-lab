import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

import pytest

from systematic_trading_lab.domain import AdjustmentPolicy, Symbol, Timeframe, TimestampRange
from systematic_trading_lab.providers import AlpacaHistoricalProvider


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
