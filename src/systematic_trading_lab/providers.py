"""Provider-neutral market-data boundaries and offline/Alpaca providers."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol, cast, overload
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .calendar import expected_bar_timestamps, expected_sessions
from .domain import AdjustmentPolicy, OHLCVBar, Symbol, Timeframe, TimestampRange


class MarketDataProvider(Protocol):
    name: str
    feed: str | None
    retrieval_timestamp: datetime
    adjustment_policy: AdjustmentPolicy

    def fetch(
        self, symbols: Sequence[Symbol], timeframe: Timeframe, requested: TimestampRange
    ) -> Sequence[dict[str, Any]]: ...


HttpTransport = Callable[[Request], bytes]
ALPACA_HISTORICAL_PROVIDER_NAME = "alpaca-historical-v2"
YAHOO_HISTORICAL_PROVIDER_NAME = "yahoo-chart-v8"


@dataclass(frozen=True)
class ProviderRecords(Sequence[dict[str, Any]]):
    """Requested records plus every mapped record retained as acquisition evidence."""

    records: tuple[dict[str, Any], ...]
    raw_records: tuple[dict[str, Any], ...]

    def __len__(self) -> int:
        return len(self.records)

    @overload
    def __getitem__(self, index: int) -> dict[str, Any]: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[dict[str, Any], ...]: ...

    def __getitem__(self, index: int | slice) -> dict[str, Any] | tuple[dict[str, Any], ...]:
        return self.records[index]


class AlpacaHistoricalProvider:
    """Read-only adapter for Alpaca's historical stock-bars endpoint."""

    name = ALPACA_HISTORICAL_PROVIDER_NAME
    feed: str | None = "iex"
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
            expected_timestamps: set[str] | None = None
        else:
            expected = expected_bar_timestamps(requested.start, requested.end, timeframe)
            if not expected:
                raise ValueError("intraday request contains no XNYS regular-session bar opens")
            exclusive_end = expected[-1] + timeframe.duration
            expected_timestamps = {
                timestamp.isoformat().replace("+00:00", "Z") for timestamp in expected
            }
        params = {
            "symbols": ",".join(symbol.value for symbol in symbols),
            "timeframe": alpaca_timeframe,
            "start": requested.start.isoformat().replace("+00:00", "Z"),
            # Alpaca's end boundary is exclusive. Extend it by one interval so the
            # repository's inclusive bar-open range retains its final interval.
            "end": exclusive_end.isoformat().replace("+00:00", "Z"),
            "adjustment": "all",
            "feed": self.feed,
            "sort": "asc",
        }
        headers = {"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.secret_key}
        records: list[dict[str, Any]] = []
        raw_records: list[dict[str, Any]] = []
        requested_symbols = {symbol.value for symbol in symbols}
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
                    record = _alpaca_bar_record(symbol, bar, timeframe)
                    raw_records.append(record)
                    try:
                        OHLCVBar.from_record(record)
                    except (ArithmeticError, TypeError, ValueError):
                        records.append(record)
                        continue
                    if (
                        expected_timestamps is None
                        or symbol not in requested_symbols
                        or record["timestamp"] in expected_timestamps
                    ):
                        records.append(record)
            token_value = payload.get("next_page_token")
            token = token_value if isinstance(token_value, str) and token_value else None
            if token is None:
                return ProviderRecords(tuple(records), tuple(raw_records))
        raise RuntimeError("Alpaca historical data exceeded the configured page limit")


class YahooHistoricalProvider:
    """Daily ETF adapter for Yahoo's chart endpoint and adjusted close series."""

    name = YAHOO_HISTORICAL_PROVIDER_NAME
    feed: str | None = None
    adjustment_policy = AdjustmentPolicy.YAHOO_ADJUSTED_OHLC

    def __init__(
        self,
        base_url: str = "https://query2.finance.yahoo.com/v8/finance/chart",
        transport: HttpTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport or _urlopen_bytes
        self.retrieval_timestamp = datetime.now(UTC)

    def fetch(
        self, symbols: Sequence[Symbol], timeframe: Timeframe, requested: TimestampRange
    ) -> Sequence[dict[str, Any]]:
        if timeframe is not Timeframe.DAILY:
            raise ValueError("Yahoo adapter supports daily bars only")
        if not symbols:
            raise ValueError("at least one symbol is required")
        records: list[dict[str, Any]] = []
        raw_records: list[dict[str, Any]] = []
        for symbol in symbols:
            params = {
                "period1": int(requested.start.timestamp()),
                "period2": int((requested.end + timedelta(days=1)).timestamp()),
                "interval": "1d",
                "includeAdjustedClose": "true",
            }
            request = Request(
                f"{self.base_url}/{quote(symbol.value)}?{urlencode(params)}",
                headers={"User-Agent": "Mozilla/5.0 systematic-trading-lab/1.0"},
            )
            try:
                payload = json.loads(self.transport(request))
                result = _yahoo_chart_result(payload, symbol)
                normalized, raw = _yahoo_chart_records(result, symbol, requested)
            except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
                raise RuntimeError(f"Yahoo historical data request failed for {symbol}") from error
            records.extend(normalized)
            raw_records.extend(raw)
        return ProviderRecords(tuple(records), tuple(raw_records))


class FixtureProvider:
    name = "deterministic-fixture-v1"
    feed: str | None = None
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
    feed: str | None = None
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


def _yahoo_chart_result(payload: object, symbol: Symbol) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("chart"), dict):
        raise ValueError("invalid Yahoo chart response")
    chart = payload["chart"]
    result = chart.get("result")
    if chart.get("error") is not None or not isinstance(result, list) or len(result) != 1:
        raise ValueError("invalid Yahoo chart result")
    item = result[0]
    if not isinstance(item, dict) or not isinstance(item.get("meta"), dict):
        raise ValueError("invalid Yahoo chart metadata")
    meta = item["meta"]
    if (
        meta.get("symbol") != symbol.value
        or meta.get("instrumentType") != "ETF"
        or meta.get("currency") != "USD"
        or meta.get("exchangeTimezoneName") != "America/New_York"
        or meta.get("dataGranularity") != "1d"
    ):
        raise ValueError("Yahoo chart metadata differs from the requested US ETF")
    return item


def _yahoo_chart_records(
    result: dict[str, Any], symbol: Symbol, requested: TimestampRange
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    timestamps = result.get("timestamp")
    indicators = result.get("indicators")
    if not isinstance(timestamps, list) or not isinstance(indicators, dict):
        raise ValueError("invalid Yahoo chart series")
    quotes = indicators.get("quote")
    adjusted = indicators.get("adjclose")
    if (
        not isinstance(quotes, list)
        or len(quotes) != 1
        or not isinstance(quotes[0], dict)
        or not isinstance(adjusted, list)
        or len(adjusted) != 1
        or not isinstance(adjusted[0], dict)
    ):
        raise ValueError("invalid Yahoo chart indicators")
    quote_values = quotes[0]
    fields = {
        "open": quote_values.get("open"),
        "high": quote_values.get("high"),
        "low": quote_values.get("low"),
        "close": quote_values.get("close"),
        "volume": quote_values.get("volume"),
        "adjusted_close": adjusted[0].get("adjclose"),
    }
    if any(
        not isinstance(values, list) or len(values) != len(timestamps) for values in fields.values()
    ):
        raise ValueError("Yahoo chart indicator lengths differ")
    series = cast(dict[str, list[object]], fields)

    eastern = ZoneInfo("America/New_York")
    meta = result["meta"]
    allowed_sessions = set(expected_sessions(requested.start, requested.end))
    records: list[dict[str, Any]] = []
    raw_records: list[dict[str, Any]] = []
    for index, vendor_timestamp in enumerate(timestamps):
        if isinstance(vendor_timestamp, bool) or not isinstance(vendor_timestamp, int):
            raise ValueError("invalid Yahoo chart timestamp")
        session = datetime.fromtimestamp(vendor_timestamp, UTC).astimezone(eastern).date()
        if session not in allowed_sessions:
            raise ValueError("Yahoo chart returned a non-XNYS session")
        timestamp = datetime(session.year, session.month, session.day, tzinfo=UTC)
        if not requested.start <= timestamp <= requested.end:
            raise ValueError("Yahoo chart returned a bar outside the requested range")
        raw = {
            "source": YAHOO_HISTORICAL_PROVIDER_NAME,
            "symbol": symbol.value,
            "instrument_type": meta["instrumentType"],
            "currency": meta["currency"],
            "exchange_timezone": meta["exchangeTimezoneName"],
            "data_granularity": meta["dataGranularity"],
            "vendor_timestamp": vendor_timestamp,
            "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
            **{
                name: (
                    values[index]
                    if name == "volume" or values[index] is None
                    else str(values[index])
                )
                for name, values in series.items()
            },
        }
        raw_records.append(raw)
        close = _positive_decimal(raw["close"], "close")
        adjusted_close = _positive_decimal(raw["adjusted_close"], "adjusted close")
        factor = adjusted_close / close
        volume = raw["volume"]
        if isinstance(volume, bool) or not isinstance(volume, int) or volume < 0:
            raise ValueError("invalid Yahoo chart volume")
        records.append(
            {
                "symbol": symbol.value,
                "timestamp": raw["timestamp"],
                "open": str(_positive_decimal(raw["open"], "open") * factor),
                "high": str(_positive_decimal(raw["high"], "high") * factor),
                "low": str(_positive_decimal(raw["low"], "low") * factor),
                "close": str(adjusted_close),
                "volume": volume,
            }
        )
    return records, raw_records


def _positive_decimal(value: object, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (ArithmeticError, ValueError) as error:
        raise ValueError(f"invalid Yahoo chart {field}") from error
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"invalid Yahoo chart {field}")
    return parsed


def _urlopen_bytes(request: Request) -> bytes:
    with urlopen(request, timeout=30) as response:
        return cast(bytes, response.read())
