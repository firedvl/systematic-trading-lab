"""Deterministic Parquet encoding for normalized OHLCV artifacts."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from .domain import OHLCVBar


def to_parquet(bars: Iterable[OHLCVBar]) -> bytes:
    rows = tuple(bars)
    table = pa.table(
        {
            "symbol": [bar.symbol.value for bar in rows],
            "timestamp": [bar.timestamp for bar in rows],
            "open": [str(bar.open) for bar in rows],
            "high": [str(bar.high) for bar in rows],
            "low": [str(bar.low) for bar in rows],
            "close": [str(bar.close) for bar in rows],
            "volume": [bar.volume for bar in rows],
        },
        schema=pa.schema(
            [
                pa.field("symbol", pa.string(), nullable=False),
                pa.field("timestamp", pa.timestamp("us", tz="UTC"), nullable=False),
                pa.field("open", pa.string(), nullable=False),
                pa.field("high", pa.string(), nullable=False),
                pa.field("low", pa.string(), nullable=False),
                pa.field("close", pa.string(), nullable=False),
                pa.field("volume", pa.int64(), nullable=False),
            ]
        ),
    )
    output = BytesIO()
    pq.write_table(
        table,
        output,
        compression="zstd",
        data_page_version="1.0",
        use_dictionary=False,
        write_statistics=False,
        version="2.6",
    )
    return output.getvalue()


def from_parquet(contents: bytes) -> tuple[dict[str, Any], ...]:
    table = pq.read_table(BytesIO(contents))
    return _records(table)


def from_parquet_range(path: Path, start: datetime, end: datetime) -> tuple[dict[str, Any], ...]:
    if (
        start.tzinfo is None
        or start.utcoffset() != UTC.utcoffset(start)
        or end.tzinfo is None
        or end.utcoffset() != UTC.utcoffset(end)
    ):
        raise ValueError("Parquet range timestamps must be UTC-aware")
    if start > end:
        raise ValueError("Parquet range start must not follow end")
    table = pq.read_table(
        path,
        filters=[("timestamp", ">=", start), ("timestamp", "<=", end)],
    )
    return _records(table)


def _records(table: pa.Table) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    for row in table.to_pylist():
        timestamp = row["timestamp"]
        if isinstance(timestamp, datetime):
            timestamp = timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
        records.append({**row, "timestamp": timestamp})
    return tuple(records)
