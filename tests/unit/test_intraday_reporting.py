from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from systematic_trading_lab.backtesting import CostModel
from systematic_trading_lab.datasets import intraday_fixture_request, intraday_fixture_symbols
from systematic_trading_lab.domain import OHLCVBar, Symbol, Timeframe
from systematic_trading_lab.intraday_reporting import (
    IntradayMomentumPortfolioStrategy,
    build_intraday_report,
    intraday_strategy_result,
    write_intraday_report,
)
from systematic_trading_lab.providers import IntradayFixtureProvider


def _bars() -> tuple[OHLCVBar, ...]:
    records = IntradayFixtureProvider().fetch(
        intraday_fixture_symbols(), Timeframe.FIVE_MINUTES, intraday_fixture_request()
    )
    return tuple(OHLCVBar.from_record(record) for record in records)


def _costs(value: str = "0") -> CostModel:
    return CostModel(slippage_bps=Decimal(value), commission_bps=Decimal(value))


def _provenance(delay: int = 1) -> dict[str, object]:
    return {"dataset": "deterministic-intraday-fixture-v1", "fill_delay_bars": delay}


def test_intraday_baseline_reports_are_deterministic_and_immutable(tmp_path: Path) -> None:
    bars = _bars()
    first = intraday_strategy_result(
        "momentum", bars, Decimal("1000"), _costs(), Timeframe.FIVE_MINUTES
    )
    second = intraday_strategy_result(
        "momentum", bars, Decimal("1000"), _costs(), Timeframe.FIVE_MINUTES
    )
    report = build_intraday_report(_provenance(), first, bars)

    assert first.artifact_fingerprint == second.artifact_fingerprint
    assert report == build_intraday_report(_provenance(), second, bars)
    assert report["schema_version"] == "intraday-backtest-report-v1"
    assert report["report_fingerprint"]
    assert report["metrics"]["total_return"] == first.metrics.total_return
    output = tmp_path / "intraday.json"
    assert write_intraday_report(output, _provenance(), first, bars) == report
    with pytest.raises(FileExistsError):
        write_intraday_report(output, _provenance(), first, bars)


def test_cash_report_is_deterministic_for_zero_trades() -> None:
    bars = _bars()
    result = intraday_strategy_result(
        "cash", bars, Decimal("1000"), _costs(), Timeframe.FIVE_MINUTES
    )
    report = build_intraday_report(_provenance(), result, bars)

    assert result.trades == ()
    assert report["fill_count"] == 0
    assert report["completed_round_trip_count"] == 0
    assert report["average_holding_duration_seconds"] is None
    assert report["best_trade_positive_profit_concentration"] is None
    assert report["sessions_traded_percentage"] == Decimal("0")
    assert report["overnight_invariant"]["final_positions_flat"] is True


def test_day_trading_baselines_flatten_normal_and_early_close_sessions() -> None:
    bars = _bars()
    result = intraday_strategy_result(
        "momentum", bars, Decimal("1000"), _costs(), Timeframe.FIVE_MINUTES
    )

    final_positions = dict(result.equity_curve[-1].positions)
    sell_dates = {
        trade.fill_timestamp.astimezone().date() for trade in result.trades if trade.quantity < 0
    }
    assert all(quantity == 0 for quantity in final_positions.values())
    assert sell_dates == {
        datetime(2025, 11, 26, tzinfo=UTC).date(),
        datetime(2025, 11, 28, tzinfo=UTC).date(),
    }
    assert all(
        trade.decision_timestamp.date() == trade.fill_timestamp.date() for trade in result.trades
    )


def test_report_metrics_and_costs_follow_fixed_trade_sequence() -> None:
    bars = _bars()
    free = intraday_strategy_result(
        "momentum", bars, Decimal("1000"), _costs(), Timeframe.FIVE_MINUTES
    )
    costly = intraday_strategy_result(
        "momentum", bars, Decimal("1000"), _costs("10"), Timeframe.FIVE_MINUTES
    )
    report = build_intraday_report(_provenance(), free, bars)

    assert costly.metrics.total_return <= free.metrics.total_return
    assert report["benchmarks"]["cash"] == Decimal("0")
    assert set(report["benchmarks"]["continuous_underlying"]) == {"QQQ", "SPY"}
    assert report["cost_paid"]["total"] == Decimal("0")
    assert report["average_gross_exposure"] == report["average_net_exposure"]
    assert report["max_gross_exposure"] <= Decimal("1")


def test_delayed_portfolio_fills_never_precede_decision() -> None:
    bars = _bars()
    result = intraday_strategy_result(
        "moving-average",
        bars,
        Decimal("1000"),
        _costs(),
        Timeframe.FIVE_MINUTES,
        fill_delay_bars=2,
        parameters={"window": 2},
    )
    report = build_intraday_report(_provenance(2), result, bars)

    assert result.trades
    assert all(trade.fill_timestamp >= trade.decision_timestamp for trade in result.trades)
    assert report["configured_fill_delay_bars"] == 2


def test_intraday_strategies_validate_parameters_and_emit_complete_targets() -> None:
    symbols = (Symbol("SPY"), Symbol("QQQ"))
    with pytest.raises(ValueError, match="positive"):
        IntradayMomentumPortfolioStrategy(symbols, lookback=0)
    with pytest.raises(ValueError, match="only 1m and 5m"):
        intraday_strategy_result("cash", _bars(), Decimal("1000"), _costs(), Timeframe.DAILY)

    start = datetime(2025, 1, 6, 14, 30, tzinfo=UTC)
    history = {
        symbol: tuple(
            OHLCVBar(
                symbol,
                start + timedelta(minutes=5 * index),
                Decimal("100"),
                Decimal("102"),
                Decimal("99"),
                Decimal(str(100 + index)),
                10,
            )
            for index in range(2)
        )
        for symbol in symbols
    }
    targets = IntradayMomentumPortfolioStrategy(symbols).on_session(
        tuple(values[-1] for values in history.values()), history
    )
    assert {target.symbol for target in targets} == set(symbols)
    assert {target.weight for target in targets} == {Decimal("0.5")}
