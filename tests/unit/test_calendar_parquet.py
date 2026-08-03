from datetime import UTC, datetime

from systematic_trading_lab.calendar import expected_sessions
from systematic_trading_lab.datasets import fixture_request, fixture_symbols
from systematic_trading_lab.domain import Timeframe
from systematic_trading_lab.parquet import from_parquet, to_parquet
from systematic_trading_lab.providers import FixtureProvider
from systematic_trading_lab.validation import validate_records


def test_nyse_calendar_excludes_market_holiday() -> None:
    sessions = expected_sessions(
        datetime(2025, 1, 17, tzinfo=UTC), datetime(2025, 1, 21, tzinfo=UTC)
    )
    assert [session.isoformat() for session in sessions] == ["2025-01-17", "2025-01-21"]


def test_parquet_encoding_is_deterministic_and_round_trips() -> None:
    records = FixtureProvider().fetch(fixture_symbols()[:1], Timeframe.DAILY, fixture_request())
    bars = validate_records(records, Timeframe.DAILY).bars
    first = to_parquet(bars)
    assert first == to_parquet(bars)
    assert from_parquet(first)[0]["symbol"] == "SPY"
