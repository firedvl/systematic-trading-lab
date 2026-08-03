from datetime import UTC, datetime

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
