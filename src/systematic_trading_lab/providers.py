"""Provider-neutral market-data boundary and deterministic offline fixture."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from .domain import Symbol, Timeframe, TimestampRange


class MarketDataProvider(Protocol):
    name: str
    retrieval_timestamp: datetime

    def fetch(
        self, symbols: Sequence[Symbol], timeframe: Timeframe, requested: TimestampRange
    ) -> Sequence[dict[str, Any]]: ...


class FixtureProvider:
    name = "deterministic-fixture-v1"
    retrieval_timestamp = datetime(2025, 1, 10, tzinfo=UTC)

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
