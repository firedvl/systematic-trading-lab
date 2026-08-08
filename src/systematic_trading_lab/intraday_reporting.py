"""Offline, deterministic intraday baselines and day-trading report artifacts."""

from __future__ import annotations

import os
import tempfile
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any, TypedDict
from zoneinfo import ZoneInfo

from .backtesting import (
    BacktestEngine,
    BacktestResult,
    CostModel,
    EquityPoint,
    IntradaySessionPolicy,
    PortfolioStrategy,
    Trade,
)
from .domain import OHLCVBar, Symbol, Timeframe
from .fingerprints import canonical_json, canonicalize, fingerprint
from .strategies import TargetPosition

_NEW_YORK = ZoneInfo("America/New_York")
_REPORT_SCHEMA = "intraday-backtest-report-v1"


class _RoundTrip(TypedDict):
    symbol: str
    net_profit: Decimal
    holding_duration_seconds: Decimal


@dataclass
class _Lot:
    quantity: Decimal
    trade: Trade


def _symbols(bars: Sequence[OHLCVBar]) -> tuple[Symbol, ...]:
    symbols = tuple(sorted({bar.symbol for bar in bars}, key=lambda symbol: symbol.value))
    if not symbols:
        raise ValueError("intraday strategy requires bars")
    if {symbol.value for symbol in symbols} - {"SPY", "QQQ"}:
        raise ValueError("intraday baselines support only SPY and QQQ")
    return symbols


def _validate_symbols(symbols: tuple[Symbol, ...]) -> None:
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("intraday strategy requires unique symbols")
    if {symbol.value for symbol in symbols} - {"SPY", "QQQ"}:
        raise ValueError("intraday baselines support only SPY and QQQ")


@dataclass(frozen=True)
class IntradayCashPortfolioStrategy:
    symbols: tuple[Symbol, ...]
    strategy_id: str = "intraday-cash"
    version: str = "1"

    def __post_init__(self) -> None:
        _validate_symbols(self.symbols)

    def on_session(
        self, bars: Sequence[OHLCVBar], history: Mapping[Symbol, Sequence[OHLCVBar]]
    ) -> Sequence[TargetPosition]:
        _check_session(self.symbols, bars, history)
        return ()


@dataclass(frozen=True)
class IntradayMomentumPortfolioStrategy:
    symbols: tuple[Symbol, ...]
    lookback: int = 1
    strategy_id: str = "intraday-previous-bar-momentum"
    version: str = "1"

    def __post_init__(self) -> None:
        _validate_symbols(self.symbols)
        if self.lookback < 1:
            raise ValueError("momentum lookback must be positive")

    def on_session(
        self, bars: Sequence[OHLCVBar], history: Mapping[Symbol, Sequence[OHLCVBar]]
    ) -> Sequence[TargetPosition]:
        _check_session(self.symbols, bars, history)
        if len(history[self.symbols[0]]) <= self.lookback:
            return ()
        weight = Decimal("1") / Decimal(len(self.symbols))
        current = {bar.symbol: bar for bar in bars}
        return tuple(
            TargetPosition(
                symbol,
                weight
                if current[symbol].close > history[symbol][-self.lookback - 1].close
                else Decimal("0"),
                "positive-previous-bar-momentum",
            )
            for symbol in sorted(self.symbols, key=lambda symbol: symbol.value)
        )


@dataclass(frozen=True)
class IntradayMovingAverageTrendPortfolioStrategy:
    symbols: tuple[Symbol, ...]
    window: int = 12
    strategy_id: str = "intraday-moving-average-trend"
    version: str = "1"

    def __post_init__(self) -> None:
        _validate_symbols(self.symbols)
        if self.window < 2:
            raise ValueError("moving-average window must be at least two bars")

    def on_session(
        self, bars: Sequence[OHLCVBar], history: Mapping[Symbol, Sequence[OHLCVBar]]
    ) -> Sequence[TargetPosition]:
        _check_session(self.symbols, bars, history)
        if len(history[self.symbols[0]]) < self.window:
            return ()
        weight = Decimal("1") / Decimal(len(self.symbols))
        current = {bar.symbol: bar for bar in bars}
        return tuple(
            TargetPosition(
                symbol,
                weight
                if current[symbol].close
                > sum((bar.close for bar in history[symbol][-self.window :]), Decimal("0"))
                / Decimal(self.window)
                else Decimal("0"),
                "close-above-moving-average",
            )
            for symbol in sorted(self.symbols, key=lambda symbol: symbol.value)
        )


def _check_session(
    symbols: tuple[Symbol, ...],
    bars: Sequence[OHLCVBar],
    history: Mapping[Symbol, Sequence[OHLCVBar]],
) -> None:
    if {bar.symbol for bar in bars} != set(symbols) or set(history) != set(symbols):
        raise ValueError("intraday session universe differs")
    if len({len(history[symbol]) for symbol in symbols}) != 1:
        raise ValueError("intraday history lengths differ")


def intraday_strategy_result(
    name: str,
    bars: Sequence[OHLCVBar],
    initial_cash: Decimal,
    cost_model: CostModel,
    timeframe: Timeframe,
    fill_delay_bars: int = 1,
    parameters: Mapping[str, object] | None = None,
) -> BacktestResult:
    """Run one fixed intraday baseline under the mandatory flat-at-close policy."""
    if not timeframe.is_supported_intraday:
        raise ValueError("intraday reports support only 1m and 5m timeframes")
    parameters = parameters or {}
    symbols = _symbols(bars)
    strategy: PortfolioStrategy
    if name in ("cash", "intraday-cash"):
        _require_parameter_names(parameters, set())
        strategy = IntradayCashPortfolioStrategy(symbols)
    elif name in ("momentum", "previous-bar-momentum", "intraday-previous-bar-momentum"):
        _require_parameter_names(parameters, {"lookback"})
        strategy = IntradayMomentumPortfolioStrategy(
            symbols, _positive_int(parameters, "lookback", 1)
        )
    elif name in ("moving-average", "moving-average-trend", "intraday-moving-average-trend"):
        _require_parameter_names(parameters, {"window"})
        strategy = IntradayMovingAverageTrendPortfolioStrategy(
            symbols, _positive_int(parameters, "window", 12)
        )
    else:
        raise ValueError(f"unknown intraday strategy: {name}")
    return BacktestEngine(
        initial_cash,
        cost_model,
        fill_delay_bars,
        timeframe,
        IntradaySessionPolicy.DAY_TRADING_FLAT,
    ).run_portfolio(bars, strategy)


def _positive_int(parameters: Mapping[str, object], name: str, default: int) -> int:
    value = parameters.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _require_parameter_names(parameters: Mapping[str, object], allowed: set[str]) -> None:
    unknown = parameters.keys() - allowed
    if unknown:
        raise ValueError(f"unsupported intraday parameters: {', '.join(sorted(unknown))}")


def build_intraday_report(
    provenance: Mapping[str, object], result: BacktestResult, bars: Sequence[OHLCVBar]
) -> dict[str, Any]:
    """Build a self-contained, fingerprinted report from offline replay evidence."""
    canonical_provenance = canonicalize(provenance)
    sessions = _sessions(bars)
    round_trips, pnl_by_symbol = _round_trips(result.trades, bars)
    session_profits = _session_profits(result)
    exposures = _exposures(result)
    positive_trades = sorted(
        (trade["net_profit"] for trade in round_trips if trade["net_profit"] > 0), reverse=True
    )
    total_positive = sum(positive_trades, Decimal("0"))
    final_positions = {
        symbol.value: quantity for symbol, quantity in result.equity_curve[-1].positions
    }
    traded_sessions = {
        trade.fill_timestamp.astimezone(_NEW_YORK).date().isoformat() for trade in result.trades
    }
    holding_durations = [trade["holding_duration_seconds"] for trade in round_trips]
    early_close_sessions = _early_close_sessions(bars)
    outside_session_fill_count = sum(
        not time(9, 30)
        <= trade.fill_timestamp.astimezone(_NEW_YORK).time().replace(tzinfo=None)
        < time(16)
        for trade in result.trades
    )
    positive_symbol_profits = [profit for profit in pnl_by_symbol.values() if profit > 0]
    total_positive_symbol_profit = sum(positive_symbol_profits, Decimal("0"))
    session_end_positions = _session_end_positions(result)
    overnight_position_count = sum(
        quantity != 0
        for positions in session_end_positions.values()
        for quantity in positions.values()
    )
    report: dict[str, object] = {
        "schema_version": _REPORT_SCHEMA,
        "status": "completed",
        "provenance": canonical_provenance,
        "configuration_provenance_fingerprint": fingerprint(canonical_provenance),
        "result_artifact_fingerprint": result.artifact_fingerprint,
        "strategy": {"id": result.strategy_id, "version": result.strategy_version},
        "total_return": result.metrics.total_return,
        "benchmarks": _benchmarks(bars),
        "risk_methodology": (
            "252-session, zero-rate sample volatility and Sharpe from New York "
            "session-close equity returns"
        ),
        "annualized_volatility": result.metrics.annualized_volatility,
        "sharpe_ratio": result.metrics.sharpe_ratio,
        "max_drawdown": result.metrics.max_drawdown,
        "turnover": result.metrics.turnover,
        "fill_count": len(result.trades),
        "round_trip_methodology": (
            "FIFO lots; net profit includes allocated buy and sell commission and slippage"
        ),
        "completed_round_trip_count": len(round_trips),
        "winning_round_trips": sum(trade["net_profit"] > 0 for trade in round_trips),
        "losing_round_trips": sum(trade["net_profit"] < 0 for trade in round_trips),
        "flat_round_trips": sum(trade["net_profit"] == 0 for trade in round_trips),
        "average_holding_duration_seconds": _average(holding_durations),
        "median_holding_duration_seconds": _median(holding_durations),
        "fills_per_session": _ratio(Decimal(len(result.trades)), len(sessions)),
        "round_trips_per_session": _ratio(Decimal(len(round_trips)), len(sessions)),
        "sessions_in_range": len(sessions),
        "sessions_traded": len(traded_sessions),
        "sessions_traded_percentage": _ratio(Decimal(len(traded_sessions)), len(sessions)),
        "pnl_by_symbol": pnl_by_symbol,
        "best_trade_positive_profit_concentration": _concentration(
            positive_trades[:1], total_positive
        ),
        "best_session_positive_profit_concentration": _best_session_concentration(session_profits),
        "best_5_trades_positive_profit_concentration": _concentration(
            positive_trades[:5], total_positive
        ),
        "best_symbol_positive_profit_concentration": (
            max(positive_symbol_profits) / total_positive_symbol_profit
            if total_positive_symbol_profit
            else None
        ),
        "cost_paid": {
            "commission": sum((trade.commission for trade in result.trades), Decimal("0")),
            "slippage": sum((trade.slippage for trade in result.trades), Decimal("0")),
        },
        "average_gross_exposure": _average(exposures),
        "max_gross_exposure": max(exposures, default=Decimal("0")),
        "average_net_exposure": _average(exposures),
        "max_net_exposure": max(exposures, default=Decimal("0")),
        "final_positions": final_positions,
        "overnight_invariant": {
            "final_positions_flat": all(quantity == 0 for quantity in final_positions.values()),
            "fills_remain_in_exchange_session": all(
                trade.decision_timestamp.astimezone(_NEW_YORK).date()
                == trade.fill_timestamp.astimezone(_NEW_YORK).date()
                for trade in result.trades
            ),
            "overnight_position_count": overnight_position_count,
            "session_end_positions": session_end_positions,
            "violating_sessions": tuple(
                session
                for session, positions in session_end_positions.items()
                if any(quantity != 0 for quantity in positions.values())
            ),
        },
        "session_evidence": {
            "outside_session_fill_count": outside_session_fill_count,
            "early_close_session_count": len(early_close_sessions),
            "early_close_sessions": early_close_sessions,
        },
        "configured_fill_delay_bars": canonical_provenance.get(
            "execution_delay_bars", canonical_provenance.get("fill_delay_bars")
        ),
        "configured_delay_result": {"total_return": result.metrics.total_return},
    }
    costs = report["cost_paid"]
    assert isinstance(costs, dict)
    costs["total"] = costs["commission"] + costs["slippage"]
    report["metrics"] = {
        "total_return": report["total_return"],
        "annualized_volatility": report["annualized_volatility"],
        "sharpe_ratio": report["sharpe_ratio"],
        "max_drawdown": report["max_drawdown"],
        "turnover": report["turnover"],
        "fill_count": report["fill_count"],
        "completed_round_trip_count": report["completed_round_trip_count"],
        "sessions_in_range": report["sessions_in_range"],
        "sessions_traded": report["sessions_traded"],
        "sessions_traded_percentage": report["sessions_traded_percentage"],
        "average_gross_exposure": report["average_gross_exposure"],
        "max_gross_exposure": report["max_gross_exposure"],
        "average_net_exposure": report["average_net_exposure"],
        "max_net_exposure": report["max_net_exposure"],
        "best_trade_positive_profit_concentration": report[
            "best_trade_positive_profit_concentration"
        ],
        "best_session_positive_profit_concentration": report[
            "best_session_positive_profit_concentration"
        ],
        "best_5_trades_positive_profit_concentration": report[
            "best_5_trades_positive_profit_concentration"
        ],
        "best_symbol_positive_profit_concentration": report[
            "best_symbol_positive_profit_concentration"
        ],
        "cost_paid_total": costs["total"],
        "overnight_position_count": overnight_position_count,
        "outside_session_fill_count": outside_session_fill_count,
        "early_close_session_count": len(early_close_sessions),
    }
    report["report_fingerprint"] = fingerprint(report)
    return report


def intraday_report_json(
    provenance: Mapping[str, object], result: BacktestResult, bars: Sequence[OHLCVBar]
) -> str:
    return canonical_json(build_intraday_report(provenance, result, bars)) + "\n"


def write_intraday_report(
    path: Path, provenance: Mapping[str, object], result: BacktestResult, bars: Sequence[OHLCVBar]
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        report = build_intraday_report(provenance, result, bars)
        temporary.write_text(canonical_json(report) + "\n", encoding="utf-8", newline="\n")
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise FileExistsError(f"report already exists: {path}") from error
    finally:
        temporary.unlink(missing_ok=True)
    return report


def _sessions(bars: Sequence[OHLCVBar]) -> tuple[str, ...]:
    return tuple(sorted({bar.timestamp.astimezone(_NEW_YORK).date().isoformat() for bar in bars}))


def _benchmarks(bars: Sequence[OHLCVBar]) -> dict[str, object]:
    by_symbol: dict[Symbol, list[OHLCVBar]] = defaultdict(list)
    for bar in bars:
        by_symbol[bar.symbol].append(bar)
    return {
        "methodology": (
            "cash return is fixed at zero; underlying return continuously holds one unit from "
            "first bar open to last bar close per symbol, before costs"
        ),
        "cash": Decimal("0"),
        "continuous_underlying": {
            symbol.value: sorted(symbol_bars, key=lambda bar: bar.timestamp)[-1].close
            / sorted(symbol_bars, key=lambda bar: bar.timestamp)[0].open
            - Decimal("1")
            for symbol, symbol_bars in sorted(by_symbol.items(), key=lambda item: item[0].value)
        },
    }


def _round_trips(
    trades: Sequence[Trade], bars: Sequence[OHLCVBar]
) -> tuple[list[_RoundTrip], dict[str, Decimal]]:
    lots: dict[Symbol, deque[_Lot]] = defaultdict(deque)
    completed: list[_RoundTrip] = []
    realized: dict[Symbol, Decimal] = defaultdict(lambda: Decimal("0"))
    for trade in trades:
        quantity = abs(trade.quantity)
        if trade.quantity > 0:
            lots[trade.symbol].append(_Lot(quantity, trade))
            continue
        remaining = quantity
        while remaining > 0 and lots[trade.symbol]:
            lot = lots[trade.symbol][0]
            opened = lot.trade
            matched = min(remaining, lot.quantity)
            buy_cost = opened.commission * matched / abs(opened.quantity)
            sell_cost = trade.commission * matched / abs(trade.quantity)
            profit = matched * (trade.fill_price - opened.fill_price) - buy_cost - sell_cost
            holding_seconds = Decimal(
                str((trade.fill_timestamp - opened.fill_timestamp).total_seconds())
            )
            completed.append(
                {
                    "symbol": trade.symbol.value,
                    "net_profit": profit,
                    "holding_duration_seconds": holding_seconds,
                }
            )
            realized[trade.symbol] += profit
            lot.quantity -= matched
            if lot.quantity == 0:
                lots[trade.symbol].popleft()
            remaining -= matched
    closes = {bar.symbol: bar.close for bar in sorted(bars, key=lambda bar: bar.timestamp)}
    for symbol, symbol_lots in lots.items():
        for lot in symbol_lots:
            opened = lot.trade
            quantity = lot.quantity
            realized[symbol] += quantity * (closes[symbol] - opened.fill_price) - (
                opened.commission * quantity / abs(opened.quantity)
            )
    return completed, {
        symbol.value: realized[symbol]
        for symbol in sorted({bar.symbol for bar in bars}, key=lambda item: item.value)
    }


def _session_profits(result: BacktestResult) -> list[Decimal]:
    previous = result.initial_cash
    values: list[Decimal] = []
    by_session: dict[str, Decimal] = {}
    for point in result.equity_curve:
        by_session[point.timestamp.astimezone(_NEW_YORK).date().isoformat()] = point.equity
    for equity in by_session.values():
        values.append(equity - previous)
        previous = equity
    return values


def _exposures(result: BacktestResult) -> list[Decimal]:
    return [
        max(Decimal("0"), (point.equity - point.cash) / point.equity)
        if point.equity
        else Decimal("0")
        for point in result.equity_curve
    ]


def _ratio(numerator: Decimal, denominator: int) -> Decimal | None:
    return numerator / Decimal(denominator) if denominator else None


def _average(values: Sequence[Decimal]) -> Decimal | None:
    return sum(values, Decimal("0")) / Decimal(len(values)) if values else None


def _median(values: Sequence[Decimal]) -> Decimal | None:
    return Decimal(str(median(values))) if values else None


def _concentration(values: Sequence[Decimal], total: Decimal) -> Decimal | None:
    return sum(values, Decimal("0")) / total if total else None


def _best_session_concentration(session_profits: Sequence[Decimal]) -> Decimal | None:
    positives = [profit for profit in session_profits if profit > 0]
    return max(positives) / sum(positives, Decimal("0")) if positives else None


def _early_close_sessions(bars: Sequence[OHLCVBar]) -> tuple[str, ...]:
    final_by_session: dict[str, datetime] = {}
    for bar in bars:
        local = bar.timestamp.astimezone(_NEW_YORK)
        key = local.date().isoformat()
        final_by_session[key] = max(local, final_by_session.get(key, local))
    return tuple(
        session
        for session, final in sorted(final_by_session.items())
        if final.time().replace(tzinfo=None) < time(15)
    )


def _session_end_positions(result: BacktestResult) -> dict[str, dict[str, Decimal]]:
    final_by_session: dict[str, EquityPoint] = {}
    for point in result.equity_curve:
        final_by_session[point.timestamp.astimezone(_NEW_YORK).date().isoformat()] = point
    return {
        session: {symbol.value: quantity for symbol, quantity in point.positions}
        for session, point in final_by_session.items()
    }
