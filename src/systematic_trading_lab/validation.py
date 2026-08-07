"""Normalization and fail-closed bar validation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from .domain import OHLCVBar, Timeframe, ValidationResult


@dataclass(frozen=True)
class ValidatedBars:
    bars: tuple[OHLCVBar, ...]
    result: ValidationResult
    quarantined: tuple[dict[str, Any], ...]


def validate_records(
    records: Sequence[dict[str, Any]],
    timeframe: Timeframe,
    expected_sessions: Sequence[date] | None = None,
    expected_symbols: Sequence[str] | None = None,
    expected_bar_timestamps: Sequence[datetime] | None = None,
) -> ValidatedBars:
    parsed: list[OHLCVBar] = []
    quarantined: list[dict[str, Any]] = []
    errors: list[str] = []
    duplicates: list[str] = []
    missing: list[str] = []
    seen: set[tuple[str, object]] = set()
    last_seen: dict[str, datetime] = {}
    allowed_intraday = (
        set(expected_bar_timestamps or ()) if timeframe.is_supported_intraday else None
    )
    allowed_symbols = set(expected_symbols) if expected_symbols is not None else None

    for index, record in enumerate(records):
        try:
            bar = OHLCVBar.from_record(record)
            if allowed_symbols is not None and bar.symbol.value not in allowed_symbols:
                errors.append(f"record {index}: unexpected symbol {bar.symbol}")
                quarantined.append(record)
                continue
            if allowed_intraday is not None and bar.timestamp not in allowed_intraday:
                errors.append(
                    f"record {index}: {bar.symbol}@{bar.timestamp.isoformat()} is outside "
                    "requested XNYS regular-session intervals"
                )
                quarantined.append(record)
                continue
            key = (bar.symbol.value, bar.timestamp)
            if key in seen:
                duplicates.append(f"{bar.symbol}@{bar.timestamp.isoformat()}")
                quarantined.append(record)
                continue
            previous = last_seen.get(bar.symbol.value)
            if previous is not None and bar.timestamp <= previous:
                errors.append(f"record {index}: timestamps are not increasing for {bar.symbol}")
                quarantined.append(record)
                continue
            seen.add(key)
            last_seen[bar.symbol.value] = bar.timestamp
            parsed.append(bar)
        except (ArithmeticError, TypeError, ValueError) as error:
            errors.append(f"record {index}: {error}")
            quarantined.append(record)

    if not records:
        errors.append("provider returned no records")

    by_symbol: dict[str, list[OHLCVBar]] = defaultdict(list)
    for bar in parsed:
        by_symbol[bar.symbol.value].append(bar)
    symbols = tuple(expected_symbols or by_symbol)
    if timeframe is Timeframe.DAILY and expected_sessions is None:
        for symbol in symbols:
            bars = by_symbol.get(symbol, [])
            for earlier, later in zip(bars, bars[1:], strict=False):
                current = earlier.timestamp + timedelta(days=1)
                while current < later.timestamp:
                    if current.weekday() < 5:
                        missing.append(f"{symbol}@{current.date().isoformat()}")
                    current += timedelta(days=1)
    elif timeframe is Timeframe.DAILY:
        for symbol in symbols:
            bars = by_symbol.get(symbol, [])
            present = {bar.timestamp.date() for bar in bars}
            if not bars:
                errors.append(f"no records for expected symbol {symbol}")
            missing.extend(
                f"{symbol}@{session.isoformat()}"
                for session in expected_sessions or ()
                if session not in present
            )
    elif timeframe.is_supported_intraday:
        if expected_bar_timestamps is None:
            errors.append("intraday validation requires expected XNYS bar intervals")
        for symbol in symbols:
            bars = by_symbol.get(symbol, [])
            present = {bar.timestamp for bar in bars}
            if not bars:
                errors.append(f"no records for expected symbol {symbol}")
            missing.extend(
                f"{symbol}@{timestamp.isoformat()}"
                for timestamp in expected_bar_timestamps or ()
                if timestamp not in present
            )

    result = ValidationResult(
        errors=tuple(errors),
        missing_intervals=tuple(missing),
        duplicate_intervals=tuple(duplicates),
        quarantined_records=len(quarantined),
    )
    return ValidatedBars(tuple(parsed), result, tuple(quarantined))
