import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from systematic_trading_lab.backtesting import (
    BacktestEngine,
    BacktestError,
    CostModel,
    IntradaySessionPolicy,
)
from systematic_trading_lab.calendar import expected_bar_timestamps
from systematic_trading_lab.cli import parser, run
from systematic_trading_lab.config import load_settings
from systematic_trading_lab.datasets import (
    DatasetService,
    DatasetValidationError,
    intraday_fixture_request,
    intraday_fixture_symbols,
)
from systematic_trading_lab.domain import OHLCVBar, Symbol, Timeframe, TimestampRange
from systematic_trading_lab.providers import IntradayFixtureProvider
from systematic_trading_lab.storage import StorageLayout
from systematic_trading_lab.strategies import BuyAndHoldStrategy, TargetPosition
from systematic_trading_lab.universe import load_intraday_universe
from systematic_trading_lab.validation import validate_records


def test_xnys_intraday_grid_uses_full_and_early_close_session_bounds() -> None:
    one_minute_request = intraday_fixture_request(Timeframe.ONE_MINUTE)
    five_minute_request = intraday_fixture_request(Timeframe.FIVE_MINUTES)

    one_minute = expected_bar_timestamps(
        one_minute_request.start, one_minute_request.end, Timeframe.ONE_MINUTE
    )
    five_minutes = expected_bar_timestamps(
        five_minute_request.start, five_minute_request.end, Timeframe.FIVE_MINUTES
    )

    assert len(one_minute) == 390 + 210
    assert len(five_minutes) == 78 + 42
    assert one_minute[-1] == datetime(2025, 11, 28, 17, 59, tzinfo=UTC)
    assert five_minutes[-1] == datetime(2025, 11, 28, 17, 55, tzinfo=UTC)
    assert {timestamp.date().isoformat() for timestamp in five_minutes} == {
        "2025-11-26",
        "2025-11-28",
    }


def test_intraday_validation_records_gaps_and_quarantines_bad_intervals() -> None:
    timeframe = Timeframe.FIVE_MINUTES
    requested = intraday_fixture_request()
    provider = IntradayFixtureProvider()
    records = list(provider.fetch(intraday_fixture_symbols()[:1], timeframe, requested))
    expected = expected_bar_timestamps(requested.start, requested.end, timeframe)

    missing_timestamp = records[1]["timestamp"]
    missing = validate_records(
        records[:1] + records[2:],
        timeframe,
        expected_symbols=("SPY",),
        expected_bar_timestamps=expected,
    )
    assert missing.result.missing_intervals == (
        f"SPY@{str(missing_timestamp).replace('Z', '+00:00')}",
    )

    duplicate = validate_records(
        records[:2] + [records[1]] + records[2:],
        timeframe,
        expected_symbols=("SPY",),
        expected_bar_timestamps=expected,
    )
    assert duplicate.result.duplicate_intervals

    out_of_session = {
        **records[0],
        "timestamp": "2025-11-26T14:25:00Z",
    }
    outside = validate_records(
        [out_of_session, *records],
        timeframe,
        expected_symbols=("SPY",),
        expected_bar_timestamps=expected,
    )
    assert any("outside requested XNYS" in error for error in outside.result.errors)
    assert outside.result.quarantined_records == 1

    non_monotonic = validate_records(
        [records[1], records[0], *records[2:]],
        timeframe,
        expected_symbols=("SPY",),
        expected_bar_timestamps=expected,
    )
    assert any("timestamps are not increasing" in error for error in non_monotonic.result.errors)

    malformed = validate_records(
        [{**records[0], "high": "0"}, {**records[1], "volume": -1}],
        timeframe,
        expected_symbols=("SPY",),
        expected_bar_timestamps=expected[:2],
    )
    assert any("prices must be finite and positive" in error for error in malformed.result.errors)
    assert any(
        "volume must be a non-negative integer" in error for error in malformed.result.errors
    )
    assert malformed.result.quarantined_records == 2


def test_intraday_dataset_import_is_deterministic_and_binds_semantics(
    tmp_path: Path,
) -> None:
    timeframe = Timeframe.FIVE_MINUTES
    requested = intraday_fixture_request()
    symbols = intraday_fixture_symbols()
    service = DatasetService(StorageLayout(tmp_path))
    universe = load_intraday_universe(timeframe)

    first = service.import_from(IntradayFixtureProvider(), symbols, timeframe, requested, universe)
    second = service.import_from(IntradayFixtureProvider(), symbols, timeframe, requested, universe)

    assert first.created is True
    assert second.created is False
    assert first.dataset_id == second.dataset_id
    assert first.fingerprint == second.fingerprint
    assert first.bar_count == 2 * (78 + 42)
    manifest = service.describe(first.dataset_id)
    assert manifest["timeframe"] == "5m"
    assert manifest["timestamp_policy"] == "bar-open-utc-v1"
    assert manifest["calendar_policy"] == "XNYS-regular-session-bars-v1"
    assert service.validate(first.dataset_id)["valid"] is True
    loaded = service.load_bars_range(
        first.dataset_id,
        requested,
        expected_fingerprint=first.fingerprint,
        expected_universe_id=universe.universe_id,
        expected_universe_fingerprint=universe.universe_fingerprint,
    )
    assert len(loaded) == first.bar_count

    one_minute = service.import_from(
        IntradayFixtureProvider(),
        symbols,
        Timeframe.ONE_MINUTE,
        intraday_fixture_request(Timeframe.ONE_MINUTE),
        load_intraday_universe(Timeframe.ONE_MINUTE),
    )
    assert one_minute.dataset_id != first.dataset_id
    assert one_minute.bar_count == 2 * (390 + 210)
    assert service.validate(one_minute.dataset_id)["valid"] is True

    manifest_path = service.layout.dataset(first.dataset_id) / "manifest.json"
    tampered = json.loads(manifest_path.read_text(encoding="utf-8"))
    tampered["timeframe"] = "1d"
    tampered["calendar_policy"] = "XNYS-v1"
    tampered.pop("timestamp_policy")
    manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
    service.layout.catalog.unlink()
    rebuilt = DatasetService(service.layout)
    assert rebuilt.rebuild_catalog() == 2
    validation = rebuilt.validate(first.dataset_id)
    assert validation["valid"] is False
    assert validation["identity_matches_manifest"] is False
    with pytest.raises(DatasetValidationError, match="manifest identity"):
        rebuilt.load_bars_range(
            first.dataset_id,
            requested,
            expected_fingerprint=first.fingerprint,
            expected_universe_id=universe.universe_id,
            expected_universe_fingerprint=universe.universe_fingerprint,
        )


def test_intraday_missing_bar_rejects_import_with_interval_evidence(tmp_path: Path) -> None:
    class MissingBarProvider(IntradayFixtureProvider):
        name = "missing-intraday-fixture-v1"

        def fetch(
            self,
            symbols: Sequence[Symbol],
            timeframe: Timeframe,
            requested: TimestampRange,
        ) -> list[dict[str, Any]]:
            records = list(super().fetch(symbols, timeframe, requested))
            records.pop(1)
            return records

    timeframe = Timeframe.FIVE_MINUTES
    requested = intraday_fixture_request(timeframe)
    layout = StorageLayout(tmp_path)

    with pytest.raises(ValueError, match="1 missing intervals"):
        DatasetService(layout).import_from(
            MissingBarProvider(),
            intraday_fixture_symbols(),
            timeframe,
            requested,
            load_intraday_universe(timeframe),
        )

    evidence = json.loads(next(layout.quarantine.glob("*.json")).read_text(encoding="utf-8"))
    assert evidence["validation"]["missing_intervals"]
    assert not list(layout.datasets.iterdir())


def test_intraday_fixture_cli_stays_offline_and_writes_only_dataset_state(
    tmp_path: Path,
) -> None:
    settings = load_settings({"TRADING_LAB_HOME": str(tmp_path)})

    assert (
        run(
            parser().parse_args(["data", "import-intraday-fixture", "--timeframe", "5m"]),
            settings,
        )
        == 0
    )
    assert DatasetService(StorageLayout(tmp_path)).describe()["timeframe"] == "5m"
    assert not (tmp_path / "execution.sqlite3").exists()


def test_intraday_next_bar_fill_waits_until_signal_bar_is_observable() -> None:
    timeframe = Timeframe.FIVE_MINUTES
    records = IntradayFixtureProvider().fetch(
        intraday_fixture_symbols()[:1], timeframe, intraday_fixture_request()
    )
    bars = tuple(OHLCVBar.from_record(record) for record in records[:3])
    free_engine = BacktestEngine(
        Decimal("1000"),
        CostModel(slippage_bps=Decimal("0"), commission_bps=Decimal("0")),
        timeframe=timeframe,
    )

    first = free_engine.run(bars, BuyAndHoldStrategy())
    repeated = free_engine.run(bars, BuyAndHoldStrategy())
    delayed = BacktestEngine(Decimal("1000"), fill_delay_bars=2, timeframe=timeframe).run(
        bars, BuyAndHoldStrategy()
    )
    costly = BacktestEngine(
        Decimal("1000"),
        CostModel(slippage_bps=Decimal("10"), commission_bps=Decimal("10")),
        timeframe=timeframe,
    ).run(bars, BuyAndHoldStrategy())

    assert bars[0].timestamp == datetime(2025, 11, 26, 14, 30, tzinfo=UTC)
    assert first.decisions[0].timestamp == datetime(2025, 11, 26, 14, 35, tzinfo=UTC)
    assert first.trades[0].decision_timestamp == first.trades[0].fill_timestamp
    assert first.trades[0].fill_timestamp == bars[1].timestamp
    assert first.trades[0].market_price == bars[1].open
    assert delayed.trades[0].fill_timestamp == bars[2].timestamp
    assert repeated.artifact_fingerprint == first.artifact_fingerprint
    assert costly.metrics.total_return < first.metrics.total_return


@pytest.mark.parametrize("fill_delay_bars", (1, 2))
def test_day_trading_policy_flattens_normal_and_early_close_sessions(
    fill_delay_bars: int,
) -> None:
    class SessionOpenEntry:
        strategy_id = "session-open-entry"
        version = "1"

        def on_bar(self, bar: OHLCVBar, history: Sequence[OHLCVBar]) -> Sequence[TargetPosition]:
            if len(history) == 1 or history[-2].timestamp.date() != bar.timestamp.date():
                return (TargetPosition(bar.symbol, Decimal("1"), "session-entry"),)
            return ()

    timeframe = Timeframe.FIVE_MINUTES
    records = IntradayFixtureProvider().fetch(
        intraday_fixture_symbols()[:1], timeframe, intraday_fixture_request(timeframe)
    )
    bars = tuple(OHLCVBar.from_record(record) for record in records)
    result = BacktestEngine(
        Decimal("1000"),
        CostModel(slippage_bps=Decimal("0"), commission_bps=Decimal("0")),
        fill_delay_bars=fill_delay_bars,
        timeframe=timeframe,
        session_policy=IntradaySessionPolicy.DAY_TRADING_FLAT,
    ).run(bars, SessionOpenEntry())

    sells = tuple(trade for trade in result.trades if trade.quantity < 0)
    assert [trade.fill_timestamp for trade in sells] == [
        datetime(2025, 11, 26, 20, 55, tzinfo=UTC),
        datetime(2025, 11, 28, 17, 55, tzinfo=UTC),
    ]
    assert all(trade.decision_timestamp <= trade.fill_timestamp for trade in sells)
    if fill_delay_bars == 1:
        assert all(trade.decision_timestamp == trade.fill_timestamp for trade in sells)
    assert all(
        point.positions == ((Symbol("SPY"), Decimal("0")),) for point in result.equity_curve[-1:]
    )
    assert all(
        trade.decision_timestamp.date() == trade.fill_timestamp.date() for trade in result.trades
    )
    assert (
        sum(
            target.reason == "mandatory-session-flatten"
            for decision in result.decisions
            for target in decision.targets
        )
        == 2
    )


def test_day_trading_policy_rejects_entry_without_time_to_flatten() -> None:
    class LateEntry:
        strategy_id = "late-entry"
        version = "1"

        def on_bar(self, bar: OHLCVBar, history: Sequence[OHLCVBar]) -> Sequence[TargetPosition]:
            if bar.timestamp in {
                datetime(2025, 11, 26, 20, 50, tzinfo=UTC),
                datetime(2025, 11, 28, 17, 50, tzinfo=UTC),
            }:
                return (TargetPosition(bar.symbol, Decimal("1"), "unsafe-late-entry"),)
            return ()

    timeframe = Timeframe.FIVE_MINUTES
    records = IntradayFixtureProvider().fetch(
        intraday_fixture_symbols()[:1], timeframe, intraday_fixture_request(timeframe)
    )
    bars = tuple(OHLCVBar.from_record(record) for record in records)
    result = BacktestEngine(
        Decimal("1000"),
        timeframe=timeframe,
        session_policy=IntradaySessionPolicy.DAY_TRADING_FLAT,
    ).run(bars, LateEntry())

    assert result.trades == ()
    assert result.equity_curve[-1].positions == ()
    assert sum(event.reason == "session-close-cutoff" for event in result.orders) == 2


def test_day_trading_policy_rejects_partial_session_input() -> None:
    timeframe = Timeframe.FIVE_MINUTES
    records = IntradayFixtureProvider().fetch(
        intraday_fixture_symbols()[:1], timeframe, intraday_fixture_request(timeframe)
    )
    partial = tuple(OHLCVBar.from_record(record) for record in records[:3])

    with pytest.raises(BacktestError, match="complete XNYS sessions"):
        BacktestEngine(
            Decimal("1000"),
            timeframe=timeframe,
            session_policy=IntradaySessionPolicy.DAY_TRADING_FLAT,
        ).run(partial, BuyAndHoldStrategy())


@pytest.mark.parametrize("fill_delay_bars", (1, 2))
def test_day_trading_policy_flattens_complete_symbol_slice_atomically(
    fill_delay_bars: int,
) -> None:
    class SessionOpenPortfolio:
        strategy_id = "session-open-portfolio"
        version = "1"

        def on_session(
            self,
            bars: Sequence[OHLCVBar],
            history: Mapping[Symbol, Sequence[OHLCVBar]],
        ) -> Sequence[TargetPosition]:
            first = min(history.values(), key=len)
            if len(first) == 1 or first[-2].timestamp.date() != bars[0].timestamp.date():
                return tuple(
                    TargetPosition(bar.symbol, Decimal("0.5"), "session-entry") for bar in bars
                )
            return ()

    timeframe = Timeframe.FIVE_MINUTES
    records = IntradayFixtureProvider().fetch(
        intraday_fixture_symbols(), timeframe, intraday_fixture_request(timeframe)
    )
    bars = tuple(OHLCVBar.from_record(record) for record in records)
    result = BacktestEngine(
        Decimal("1000"),
        CostModel(slippage_bps=Decimal("0"), commission_bps=Decimal("0")),
        fill_delay_bars=fill_delay_bars,
        timeframe=timeframe,
        session_policy=IntradaySessionPolicy.DAY_TRADING_FLAT,
    ).run_portfolio(bars, SessionOpenPortfolio())

    assert all(quantity == 0 for _, quantity in result.equity_curve[-1].positions)
    assert {
        (trade.symbol, trade.fill_timestamp) for trade in result.trades if trade.quantity < 0
    } == {
        (Symbol(symbol), timestamp)
        for symbol in ("QQQ", "SPY")
        for timestamp in (
            datetime(2025, 11, 26, 20, 55, tzinfo=UTC),
            datetime(2025, 11, 28, 17, 55, tzinfo=UTC),
        )
    }
