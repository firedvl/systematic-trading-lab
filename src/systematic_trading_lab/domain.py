"""Validated domain types shared across trusted boundaries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")


@dataclass(frozen=True, order=True)
class Symbol:
    value: str

    def __post_init__(self) -> None:
        if not _SYMBOL_PATTERN.fullmatch(self.value):
            raise ValueError(f"invalid symbol: {self.value!r}")

    def __str__(self) -> str:
        return self.value


class Timeframe(StrEnum):
    DAILY = "1d"
    HOURLY = "1h"


class TradingMode(StrEnum):
    OFFLINE = "offline"
    RESEARCH = "research"
    REPLAY = "replay"
    SHADOW = "shadow"
    PAPER = "paper"
    LIVE_DISABLED = "live-disabled"


class AdjustmentPolicy(StrEnum):
    PROVIDER_ADJUSTED_ALL = "provider-adjusted-all-v1"
    SYNTHETIC_NO_ACTIONS = "synthetic-no-actions-v1"
    UNADJUSTED = "unadjusted-v1"


@dataclass(frozen=True)
class TimestampRange:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        _require_utc(self.start)
        _require_utc(self.end)
        if self.start > self.end:
            raise ValueError("timestamp range start must not follow end")


@dataclass(frozen=True)
class OHLCVBar:
    symbol: Symbol
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

    def __post_init__(self) -> None:
        _require_utc(self.timestamp)
        prices = (self.open, self.high, self.low, self.close)
        if not all(price.is_finite() and price > 0 for price in prices):
            raise ValueError("prices must be finite and positive")
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("high is below another OHLC price")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("low is above another OHLC price")
        if isinstance(self.volume, bool) or not isinstance(self.volume, int) or self.volume < 0:
            raise ValueError("volume must be a non-negative integer")

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> OHLCVBar:
        required = {"symbol", "timestamp", "open", "high", "low", "close", "volume"}
        missing = required - record.keys()
        if missing:
            raise ValueError(f"missing fields: {', '.join(sorted(missing))}")
        timestamp = datetime.fromisoformat(str(record["timestamp"]).replace("Z", "+00:00"))
        volume = record["volume"]
        if isinstance(volume, bool) or not isinstance(volume, int):
            raise ValueError("volume must be an integer")
        return cls(
            symbol=Symbol(str(record["symbol"])),
            timestamp=timestamp,
            open=Decimal(str(record["open"])),
            high=Decimal(str(record["high"])),
            low=Decimal(str(record["low"])),
            close=Decimal(str(record["close"])),
            volume=volume,
        )

    def to_record(self) -> dict[str, object]:
        return {
            "symbol": self.symbol.value,
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass(frozen=True)
class DatasetIdentity:
    dataset_id: str
    fingerprint: str


@dataclass(frozen=True)
class DatasetManifest:
    identity: DatasetIdentity
    provider: str
    symbols: tuple[Symbol, ...]
    timeframe: Timeframe
    requested_range: TimestampRange
    actual_range: TimestampRange
    retrieval_timestamp: datetime
    raw_artifact_hashes: tuple[str, ...]
    normalization_version: str
    schema_version: str
    adjustment_policy: str
    calendar_policy: str
    validation: ValidationResult
    parent_dataset_id: str | None = None

    def __post_init__(self) -> None:
        _require_utc(self.retrieval_timestamp)


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...] = ()
    missing_intervals: tuple[str, ...] = ()
    duplicate_intervals: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    quarantined_records: int = 0

    @property
    def valid(self) -> bool:
        return not (
            self.errors
            or self.missing_intervals
            or self.duplicate_intervals
            or self.conflicts
            or self.quarantined_records
        )


@dataclass(frozen=True)
class StrategyIdentity:
    strategy_id: str
    version: str

    def __post_init__(self) -> None:
        if not self.strategy_id or not self.version:
            raise ValueError("strategy ID and version are required")


@dataclass(frozen=True)
class ExperimentIdentity:
    experiment_id: str

    def __post_init__(self) -> None:
        if not self.experiment_id:
            raise ValueError("experiment ID is required")


def _require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must be UTC-aware")
