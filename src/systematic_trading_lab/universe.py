"""Versioned point-in-time research universe definitions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .domain import Symbol, Timeframe, TimestampRange
from .fingerprints import fingerprint


class UniverseError(ValueError):
    pass


@dataclass(frozen=True)
class Membership:
    symbol: Symbol
    start: datetime
    end: datetime | None
    source: str

    def __post_init__(self) -> None:
        for value in (self.start, self.end):
            if value is not None and (
                value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
            ):
                raise UniverseError("membership timestamps must be UTC-aware")
        if self.end is not None and self.start > self.end:
            raise UniverseError("membership start must not follow end")
        if not self.source.startswith("https://"):
            raise UniverseError("membership source must be an HTTPS URL")

    def covers(self, requested: TimestampRange) -> bool:
        return self.start <= requested.start and (self.end is None or requested.end <= self.end)


@dataclass(frozen=True)
class UniverseDefinition:
    universe_id: str
    timeframe: Timeframe
    memberships: tuple[Membership, ...]
    universe_fingerprint: str

    def require_full_coverage(
        self, symbols: tuple[Symbol, ...], timeframe: Timeframe, requested: TimestampRange
    ) -> None:
        if timeframe != self.timeframe:
            raise UniverseError("request timeframe does not match the universe")
        requested_symbols = set(symbols)
        if len(requested_symbols) != len(symbols):
            raise UniverseError("request symbols must be unique")
        covered = {
            membership.symbol for membership in self.memberships if membership.covers(requested)
        }
        if requested_symbols != covered:
            missing = sorted(str(symbol) for symbol in covered - requested_symbols)
            unsupported = sorted(str(symbol) for symbol in requested_symbols - covered)
            details = []
            if missing:
                details.append(f"missing active symbols: {', '.join(missing)}")
            if unsupported:
                details.append(f"symbols lack full-range membership: {', '.join(unsupported)}")
            raise UniverseError("; ".join(details))


def load_research_universe(path: Path | None = None) -> UniverseDefinition:
    source = path or Path(__file__).resolve().parents[2] / "config" / "research" / "universe.json"
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        universe_id = payload["id"]
        timeframe = Timeframe(payload["timeframe"])
        raw_memberships = payload["memberships"]
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise UniverseError(f"invalid universe file: {source}") from error
    if not isinstance(universe_id, str) or not universe_id or not isinstance(raw_memberships, list):
        raise UniverseError("universe ID and memberships are required")
    memberships = tuple(_membership(item) for item in raw_memberships)
    if not memberships:
        raise UniverseError("universe requires at least one membership")
    if len({membership.symbol for membership in memberships}) != len(memberships):
        raise UniverseError("universe v1 requires one interval per symbol")
    content = {"id": universe_id, "timeframe": timeframe, "memberships": memberships}
    return UniverseDefinition(universe_id, timeframe, memberships, fingerprint(content))


def load_intraday_universe(timeframe: Timeframe) -> UniverseDefinition:
    if not timeframe.is_supported_intraday:
        raise UniverseError("intraday universe supports only 1m and 5m")
    path = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "research"
        / f"intraday-universe-{timeframe.value}.json"
    )
    return load_research_universe(path)


def _membership(value: object) -> Membership:
    if not isinstance(value, dict):
        raise UniverseError("membership must be an object")
    try:
        start = _date(value["start"])
        end = _date(value["end"]) if value.get("end") is not None else None
        return Membership(Symbol(str(value["symbol"])), start, end, str(value["source"]))
    except (KeyError, TypeError, ValueError) as error:
        raise UniverseError("invalid universe membership") from error


def _date(value: object) -> datetime:
    if not isinstance(value, str):
        raise UniverseError("membership dates must use YYYY-MM-DD")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise UniverseError("membership dates must use YYYY-MM-DD") from error
    if parsed.strftime("%Y-%m-%d") != value:
        raise UniverseError("membership dates must use YYYY-MM-DD")
    return parsed.replace(tzinfo=UTC)
