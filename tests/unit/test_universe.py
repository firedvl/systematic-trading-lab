import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from systematic_trading_lab.domain import Symbol, Timeframe, TimestampRange
from systematic_trading_lab.universe import UniverseError, load_research_universe


def date(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def symbols(*values: str) -> tuple[Symbol, ...]:
    return tuple(Symbol(value) for value in values)


def test_research_universe_has_deterministic_full_range_membership() -> None:
    universe = load_research_universe()
    requested = TimestampRange(date("2004-11-18"), date("2025-01-10"))

    universe.require_full_coverage(
        symbols("SPY", "QQQ", "IWM", "TLT", "GLD"), Timeframe.DAILY, requested
    )

    assert universe.universe_fingerprint == load_research_universe().universe_fingerprint


def test_research_universe_rejects_inception_crossing_and_incomplete_requests() -> None:
    universe = load_research_universe()
    all_symbols = symbols("SPY", "QQQ", "IWM", "TLT", "GLD")

    with pytest.raises(UniverseError, match="lack full-range membership"):
        universe.require_full_coverage(
            all_symbols,
            Timeframe.DAILY,
            TimestampRange(date("2004-11-17"), date("2004-11-19")),
        )

    with pytest.raises(UniverseError, match="missing active symbols: GLD"):
        universe.require_full_coverage(
            symbols("SPY", "QQQ", "IWM", "TLT"),
            Timeframe.DAILY,
            TimestampRange(date("2005-01-01"), date("2005-01-31")),
        )


def test_extended_universe_binds_and_enforces_its_acquisition_policy(tmp_path: Path) -> None:
    path = tmp_path / "universe.json"
    payload = {
        "schema_version": "test-universe-v1",
        "id": "test-universe-v1",
        "timeframe": "1d",
        "acquisition": {"start": "2020-01-01", "end": "2020-12-31"},
        "sealed_boundaries": {"independent_access_allowed": False},
        "memberships": [
            {
                "symbol": "SPY",
                "start": "1993-01-22",
                "end": None,
                "source": "https://example.com/spy",
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    universe = load_research_universe(path)

    universe.require_acquisition_range(TimestampRange(date("2020-01-02"), date("2020-12-30")))
    with pytest.raises(UniverseError, match="outside the universe acquisition range"):
        universe.require_acquisition_range(TimestampRange(date("2019-12-31"), date("2020-01-02")))

    payload["sealed_boundaries"] = {"independent_access_allowed": True}
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_research_universe(path).universe_fingerprint != universe.universe_fingerprint
