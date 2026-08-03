"""Deterministic backtest report artifacts and benchmark helpers."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path

from .backtesting import BacktestEngine, BacktestResult, CostModel, Strategy
from .domain import OHLCVBar
from .fingerprints import canonical_json, fingerprint
from .strategies import (
    BuyAndHoldStrategy,
    CashStrategy,
    FixedWeightStrategy,
    MovingAverageTrendStrategy,
    TimeSeriesMomentumStrategy,
)


def summarize(result: BacktestResult) -> dict[str, object]:
    return {
        "strategy_id": result.strategy_id,
        "strategy_version": result.strategy_version,
        "initial_cash": result.initial_cash,
        "total_return": result.metrics.total_return,
        "max_drawdown": result.metrics.max_drawdown,
        "turnover": result.metrics.turnover,
        "trade_count": result.metrics.trade_count,
        "artifact_fingerprint": result.artifact_fingerprint,
    }


def build_report(results: Mapping[str, BacktestResult]) -> dict[str, object]:
    cash_return = results["cash"].metrics.total_return if "cash" in results else None
    payload: dict[str, object] = {
        "schema_version": "backtest-report-v1",
        "results": {name: summarize(result) for name, result in sorted(results.items())},
        "comparisons": {
            name: {"excess_return_vs_cash": result.metrics.total_return - cash_return}
            for name, result in sorted(results.items())
            if cash_return is not None
        },
    }
    payload["report_fingerprint"] = fingerprint(payload)
    return payload


def report_json(results: Mapping[str, BacktestResult]) -> str:
    return canonical_json(build_report(results)) + "\n"


def write_report(path: Path, results: Mapping[str, BacktestResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = report_json(results)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise FileExistsError(f"report already exists: {path}") from error
    finally:
        temporary.unlink(missing_ok=True)


def benchmark_suite(
    bars: Sequence[OHLCVBar],
    initial_cash: Decimal,
    cost_model: CostModel | None = None,
) -> dict[str, BacktestResult]:
    symbols = tuple(sorted({bar.symbol for bar in bars}, key=lambda symbol: symbol.value))

    def engine() -> BacktestEngine:
        return BacktestEngine(initial_cash, cost_model)

    results: dict[str, BacktestResult] = {"cash": engine().run(bars, CashStrategy())}
    for symbol in symbols:
        symbol_bars = tuple(bar for bar in bars if bar.symbol == symbol)
        results[f"buy-and-hold:{symbol}"] = engine().run(symbol_bars, BuyAndHoldStrategy())
    if symbols:
        results["fixed-weight"] = engine().run(bars, FixedWeightStrategy(symbols))
    return results


def strategy_result(
    name: str,
    bars: Sequence[OHLCVBar],
    initial_cash: Decimal,
    cost_model: CostModel | None = None,
    parameters: Mapping[str, object] | None = None,
    fill_delay_bars: int = 1,
) -> BacktestResult:
    parameters = parameters or {}
    symbols = tuple(sorted({bar.symbol for bar in bars}, key=lambda symbol: symbol.value))
    target_weight = Decimal("1") / Decimal(len(symbols)) if symbols else Decimal("1")
    if name == "buy-and-hold":
        symbol = min((bar.symbol for bar in bars), key=lambda item: item.value)
        bars = tuple(bar for bar in bars if bar.symbol == symbol)
        strategy: Strategy = BuyAndHoldStrategy()
    elif name == "cash":
        strategy = CashStrategy()
    elif name == "fixed-weight":
        strategy = FixedWeightStrategy(
            tuple(sorted({bar.symbol for bar in bars}, key=lambda symbol: symbol.value))
        )
    elif name in ("moving-average", "moving-average-trend"):
        strategy = MovingAverageTrendStrategy(
            window=_positive_int_parameter(parameters, "window", 20),
            target_weight=target_weight,
        )
    elif name in ("momentum", "time-series-momentum"):
        strategy = TimeSeriesMomentumStrategy(
            lookback=_positive_int_parameter(parameters, "lookback", 20),
            target_weight=target_weight,
        )
    else:
        raise ValueError(f"unknown backtest strategy: {name}")
    return BacktestEngine(initial_cash, cost_model, fill_delay_bars).run(bars, strategy)


def _positive_int_parameter(parameters: Mapping[str, object], name: str, default: int) -> int:
    value = parameters.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value
