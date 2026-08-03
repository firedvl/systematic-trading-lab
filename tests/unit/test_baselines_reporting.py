from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from systematic_trading_lab.domain import OHLCVBar, Symbol
from systematic_trading_lab.reporting import (
    benchmark_suite,
    build_report,
    report_json,
    write_report,
)
from systematic_trading_lab.strategies import (
    FixedWeightStrategy,
    MovingAverageTrendStrategy,
    TimeSeriesMomentumStrategy,
)


def test_baselines_emit_targets_only_when_their_data_is_ready() -> None:
    symbol = Symbol("SPY")
    bars = tuple(
        OHLCVBar(
            symbol,
            datetime(2025, 1, 6, tzinfo=UTC) + timedelta(days=index),
            Decimal(str(price)),
            Decimal(str(price + 2)),
            Decimal(str(price - 2)),
            Decimal(str(price + 1)),
            100,
        )
        for index, price in enumerate((100, 101, 102, 103))
    )
    fixed = FixedWeightStrategy((symbol,), rebalance_every=2)
    assert fixed.on_bar(bars[0], (bars[0],))[0].weight == Decimal("1")
    assert fixed.on_bar(bars[1], bars[:2]) == ()
    assert fixed.on_bar(bars[2], bars[:3])[0].reason == "periodic-rebalance"
    assert MovingAverageTrendStrategy(window=3).on_bar(bars[1], bars[:2]) == ()
    assert MovingAverageTrendStrategy(window=3).on_bar(bars[2], bars[:3])[0].weight == Decimal("1")
    assert TimeSeriesMomentumStrategy(lookback=2).on_bar(bars[1], bars[:2]) == ()
    assert TimeSeriesMomentumStrategy(lookback=2).on_bar(bars[2], bars)[0].weight == Decimal("1")


def test_benchmark_report_is_deterministic_and_immutable(tmp_path: Path) -> None:
    symbol = Symbol("SPY")
    bars = tuple(
        OHLCVBar(
            symbol,
            datetime(2025, 1, 6, tzinfo=UTC) + timedelta(days=index),
            Decimal("100"),
            Decimal("105"),
            Decimal("95"),
            Decimal(str(100 + index)),
            100,
        )
        for index in range(3)
    )
    results = benchmark_suite(bars, Decimal("1000"))
    assert {"cash", "buy-and-hold:SPY", "fixed-weight"} <= results.keys()
    report = build_report(results)
    comparisons = report["comparisons"]
    assert isinstance(comparisons, dict)
    assert comparisons["cash"] == {"excess_return_vs_cash": Decimal("0")}
    assert report_json(results) == report_json(results)
    output = tmp_path / "report.json"
    write_report(output, results)
    with pytest.raises(FileExistsError):
        write_report(output, results)
