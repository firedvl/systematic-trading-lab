"""Provider-neutral market-data boundaries and offline/Alpaca providers."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .calendar import expected_bar_timestamps
from .domain import AdjustmentPolicy, Symbol, Timeframe, TimestampRange


class MarketDataProvider(Protocol):
    name: str
    retrieval_timestamp: datetime
    adjustment_policy: AdjustmentPolicy

    def fetch(
        self, symbols: Sequence[Symbol], timeframe: Timeframe, requested: TimestampRange
    ) -> Sequence[dict[str, Any]]: ...


HttpTransport = Callable[[Request], bytes]


class AlpacaHistoricalProvider:
    """Read-only adapter for Alpaca's historical stock-bars endpoint."""

    name = "alpaca-historical-v2"
    adjustment_policy = AdjustmentPolicy.PROVIDER_ADJUSTED_ALL

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        base_url: str = "https://data.alpaca.markets/v2/stocks/bars",
        transport: HttpTransport | None = None,
        max_pages: int = 100,
    ) -> None:
        if not api_key or not secret_key:
            raise ValueError("Alpaca API credentials are required at the runtime boundary")
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = base_url
        self.transport = transport or _urlopen_bytes
        self.max_pages = max_pages
        self.retrieval_timestamp = datetime.now(UTC)

    def fetch(
        self, symbols: Sequence[Symbol], timeframe: Timeframe, requested: TimestampRange
    ) -> Sequence[dict[str, Any]]:
        alpaca_timeframe = {
            Timeframe.DAILY: "1Day",
            Timeframe.ONE_MINUTE: "1Min",
            Timeframe.FIVE_MINUTES: "5Min",
        }.get(timeframe)
        if alpaca_timeframe is None:
            raise ValueError("Alpaca adapter supports only 1d, 1m, and 5m bars")
        if not symbols:
            raise ValueError("at least one symbol is required")
        if timeframe is Timeframe.DAILY:
            exclusive_end = requested.end + timedelta(days=1)
        else:
            expected = expected_bar_timestamps(requested.start, requested.end, timeframe)
            if not expected:
                raise ValueError("intraday request contains no XNYS regular-session bar opens")
            exclusive_end = expected[-1] + timeframe.duration
        params = {
            "symbols": ",".join(symbol.value for symbol in symbols),
            "timeframe": alpaca_timeframe,
            "start": requested.start.isoformat().replace("+00:00", "Z"),
            # Alpaca's end boundary is exclusive. Extend it by one interval so the
            # repository's inclusive bar-open range retains its final interval.
            "end": exclusive_end.isoformat().replace("+00:00", "Z"),
            "adjustment": "all",
            "feed": "iex",
            "sort": "asc",
        }
        headers = {"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.secret_key}
        records: list[dict[str, Any]] = []
        token: str | None = None
        for _ in range(self.max_pages):
            query = dict(params)
            if token:
                query["page_token"] = token
            request = Request(f"{self.base_url}?{urlencode(query)}", headers=headers)
            try:
                payload = json.loads(self.transport(request))
            except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
                raise RuntimeError("Alpaca historical data request failed") from error
            if not isinstance(payload, dict) or not isinstance(payload.get("bars"), dict):
                raise RuntimeError("Alpaca historical data response has an invalid bars shape")
            for symbol, bars in payload["bars"].items():
                if not isinstance(bars, list):
                    raise RuntimeError("Alpaca historical data response has invalid symbol bars")
                for bar in bars:
                    if not isinstance(bar, dict):
                        raise RuntimeError("Alpaca historical data response has an invalid bar")
                    records.append(_alpaca_bar_record(symbol, bar, timeframe))
            token_value = payload.get("next_page_token")
            token = token_value if isinstance(token_value, str) and token_value else None
            if token is None:
                return records
        raise RuntimeError("Alpaca historical data exceeded the configured page limit")


class FixtureProvider:
    name = "deterministic-fixture-v1"
    retrieval_timestamp = datetime(2025, 1, 10, tzinfo=UTC)
    adjustment_policy = AdjustmentPolicy.SYNTHETIC_NO_ACTIONS

    def fetch(
        self, symbols: Sequence[Symbol], timeframe: Timeframe, requested: TimestampRange
    ) -> Sequence[dict[str, Any]]:
        if timeframe is not Timeframe.DAILY:
            raise ValueError("fixture provider supports daily bars only")
        records: list[dict[str, Any]] = []
        for symbol_index, symbol in enumerate(symbols):
            base = Decimal(100 + symbol_index * 20)
            current = requested.start
            sequence = 0
            while current <= requested.end:
                if current.weekday() < 5:
                    opening = base + Decimal(sequence)
                    records.append(
                        {
                            "symbol": symbol.value,
                            "timestamp": current.isoformat().replace("+00:00", "Z"),
                            "open": str(opening),
                            "high": str(opening + Decimal("1.25")),
                            "low": str(opening - Decimal("0.75")),
                            "close": str(opening + Decimal("0.5")),
                            "volume": 1_000_000 + symbol_index * 10_000 + sequence * 1_000,
                        }
                    )
                    sequence += 1
                current += timedelta(days=1)
        return records


class IntradayFixtureProvider:
    """Deterministic SPY/QQQ regular-session bars for offline intraday checks."""

    name = "deterministic-intraday-fixture-v1"
    retrieval_timestamp = datetime(2025, 11, 29, tzinfo=UTC)
    adjustment_policy = AdjustmentPolicy.SYNTHETIC_NO_ACTIONS

    def fetch(
        self, symbols: Sequence[Symbol], timeframe: Timeframe, requested: TimestampRange
    ) -> Sequence[dict[str, Any]]:
        if not timeframe.is_supported_intraday:
            raise ValueError("intraday fixture supports only 1m and 5m bars")
        timestamps = expected_bar_timestamps(requested.start, requested.end, timeframe)
        records: list[dict[str, Any]] = []
        for symbol_index, symbol in enumerate(symbols):
            base = Decimal(500 + symbol_index * 100)
            for sequence, timestamp in enumerate(timestamps):
                opening = base + Decimal(sequence) / Decimal("100")
                records.append(
                    {
                        "symbol": symbol.value,
                        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
                        "open": str(opening),
                        "high": str(opening + Decimal("0.10")),
                        "low": str(opening - Decimal("0.10")),
                        "close": str(opening + Decimal("0.02")),
                        "volume": 10_000 + symbol_index * 1_000 + sequence,
                    }
                )
        return records


def _alpaca_bar_record(symbol: str, bar: dict[str, Any], timeframe: Timeframe) -> dict[str, Any]:
    required = {"t", "o", "h", "l", "c", "v"}
    if required - bar.keys():
        raise RuntimeError(f"Alpaca bar for {symbol} is missing required fields")
    timestamp = datetime.fromisoformat(str(bar["t"]).replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise RuntimeError(f"Alpaca bar for {symbol} has a timezone-naive timestamp")
    timestamp = timestamp.astimezone(UTC)
    if timeframe is Timeframe.DAILY:
        timestamp = datetime(timestamp.year, timestamp.month, timestamp.day, tzinfo=UTC)
    return {
        "symbol": symbol,
        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "open": str(bar["o"]),
        "high": str(bar["h"]),
        "low": str(bar["l"]),
        "close": str(bar["c"]),
        "volume": bar["v"],
    }


def _urlopen_bytes(request: Request) -> bytes:
    with urlopen(request, timeout=30) as response:
        return cast(bytes, response.read())
