"""Canonical serialization and SHA-256 fingerprints."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any


def canonicalize(value: Any) -> Any:
    """Convert supported domain values to deterministic JSON-compatible values."""
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: canonicalize(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): canonicalize(item) for key, item in sorted(value.items())}
    if isinstance(value, list | tuple):
        return [canonicalize(item) for item in value]
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("cannot canonicalize a non-UTC timestamp")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("cannot canonicalize a non-finite decimal")
        return "0" if value == 0 else format(value.normalize(), "f")
    if isinstance(value, Enum):
        return canonicalize(value.value)
    if isinstance(value, Path):
        return value.as_posix()
    if value is None or isinstance(value, str | int | bool):
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        canonicalize(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()
