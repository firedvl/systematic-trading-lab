"""Small event-driven daily-bar backtester with explicit fill timing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from .domain import OHLCVBar, Symbol
from .fingerprints import fingerprint
from .strategies import TargetPosition


class Strategy(Protocol):
    strategy_id: str
    version: str

    def on_bar(self, bar: OHLCVBar, history: Sequence[OHLCVBar]) -> Sequence[TargetPosition]: ...


@dataclass(frozen=True)
class CostModel:
    version: str = "conservative-bps-v1"
    slippage_bps: Decimal = Decimal("5")
    commission_bps: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if self.slippage_bps < 0 or self.commission_bps < 0:
            raise ValueError("cost rates must not be negative")

    def fill_price(self, market_price: Decimal, quantity: Decimal) -> Decimal:
        direction = Decimal("1") if quantity > 0 else Decimal("-1")
        return market_price * (Decimal("1") + direction * self.slippage_bps / Decimal("10000"))

    def commission(self, notional: Decimal) -> Decimal:
        return abs(notional) * self.commission_bps / Decimal("10000")


@dataclass(frozen=True)
class Decision:
    timestamp: datetime
    symbol: Symbol
    strategy_id: str
    strategy_version: str
    targets: tuple[TargetPosition, ...]


@dataclass(frozen=True)
class Order:
    symbol: Symbol
    decision_timestamp: datetime
    order_timestamp: datetime
    earliest_fill_timestamp: datetime
    target: TargetPosition


@dataclass(frozen=True)
class OrderEvent:
    symbol: Symbol
    timestamp: datetime
    status: str
    reason: str
    quantity: Decimal = Decimal("0")


@dataclass(frozen=True)
class Trade:
    symbol: Symbol
    decision_timestamp: datetime
    fill_timestamp: datetime
    quantity: Decimal
    market_price: Decimal
    fill_price: Decimal
    gross_notional: Decimal
    commission: Decimal
    slippage: Decimal


@dataclass(frozen=True)
class EquityPoint:
    timestamp: datetime
    equity: Decimal
    cash: Decimal
    positions: tuple[tuple[Symbol, Decimal], ...]


@dataclass(frozen=True)
class BacktestMetrics:
    total_return: Decimal
    max_drawdown: Decimal
    turnover: Decimal
    trade_count: int


@dataclass(frozen=True)
class BacktestResult:
    strategy_id: str
    strategy_version: str
    initial_cash: Decimal
    equity_curve: tuple[EquityPoint, ...]
    decisions: tuple[Decision, ...]
    orders: tuple[OrderEvent, ...]
    trades: tuple[Trade, ...]
    metrics: BacktestMetrics
    artifact_fingerprint: str


class BacktestError(ValueError):
    pass


class BacktestEngine:
    def __init__(self, initial_cash: Decimal, cost_model: CostModel | None = None) -> None:
        if initial_cash <= 0:
            raise ValueError("initial cash must be positive")
        self.initial_cash = initial_cash
        self.cost_model = cost_model or CostModel()

    def run(self, bars: Sequence[OHLCVBar], strategy: Strategy) -> BacktestResult:
        ordered = tuple(sorted(bars, key=lambda bar: (bar.timestamp, bar.symbol.value)))
        self._check_bars(ordered)
        next_bar: dict[tuple[Symbol, int], OHLCVBar] = {}
        next_index: dict[Symbol, int] = {}
        for index in range(len(ordered) - 1, -1, -1):
            bar = ordered[index]
            if bar.symbol in next_index:
                next_bar[(bar.symbol, index)] = ordered[next_index[bar.symbol]]
            next_index[bar.symbol] = index
        cash = self.initial_cash
        positions: dict[Symbol, Decimal] = {}
        marks: dict[Symbol, Decimal] = {}
        history: dict[Symbol, list[OHLCVBar]] = {}
        pending: dict[Symbol, Order] = {}
        decisions: list[Decision] = []
        orders: list[OrderEvent] = []
        trades: list[Trade] = []
        curve: list[EquityPoint] = []

        for index, bar in enumerate(ordered):
            marks[bar.symbol] = bar.open
            pending_order = pending.pop(bar.symbol, None)
            if pending_order is not None:
                cash, event, trade = self._execute(pending_order, bar.open, cash, positions, marks)
                orders.append(event)
                if trade is not None:
                    trades.append(trade)

            marks[bar.symbol] = bar.close
            symbol_history = history.setdefault(bar.symbol, [])
            symbol_history.append(bar)
            targets = tuple(strategy.on_bar(bar, tuple(symbol_history)))
            decisions.append(
                Decision(bar.timestamp, bar.symbol, strategy.strategy_id, strategy.version, targets)
            )
            for target in targets:
                if target.symbol != bar.symbol:
                    orders.append(
                        OrderEvent(target.symbol, bar.timestamp, "rejected", "cross-symbol-target")
                    )
                    continue
                if not Decimal("0") <= target.weight <= Decimal("1"):
                    orders.append(
                        OrderEvent(target.symbol, bar.timestamp, "rejected", "weight-out-of-range")
                    )
                    continue
                following = next_bar.get((bar.symbol, index))
                if following is None:
                    orders.append(
                        OrderEvent(target.symbol, bar.timestamp, "rejected", "no-future-fill")
                    )
                    continue
                pending[bar.symbol] = Order(
                    bar.symbol, bar.timestamp, bar.timestamp, following.timestamp, target
                )
            curve.append(self._equity_point(bar.timestamp, cash, positions, marks))

        for order in pending.values():
            orders.append(
                OrderEvent(
                    order.symbol, order.earliest_fill_timestamp, "rejected", "no-future-fill"
                )
            )
        metrics = self._metrics(curve, trades)
        result = BacktestResult(
            strategy.strategy_id,
            strategy.version,
            self.initial_cash,
            tuple(curve),
            tuple(decisions),
            tuple(orders),
            tuple(trades),
            metrics,
            "",
        )
        return BacktestResult(
            result.strategy_id,
            result.strategy_version,
            result.initial_cash,
            result.equity_curve,
            result.decisions,
            result.orders,
            result.trades,
            result.metrics,
            fingerprint(result),
        )

    def _execute(
        self,
        order: Order,
        market_price: Decimal,
        cash: Decimal,
        positions: dict[Symbol, Decimal],
        marks: Mapping[Symbol, Decimal],
    ) -> tuple[Decimal, OrderEvent, Trade | None]:
        current = positions.get(order.symbol, Decimal("0"))
        equity = cash + sum(
            (quantity * marks[symbol] for symbol, quantity in positions.items()), Decimal("0")
        )
        buy_price = self.cost_model.fill_price(market_price, Decimal("1"))
        sell_price = self.cost_model.fill_price(market_price, Decimal("-1"))
        desired_buy = equity * order.target.weight / buy_price
        desired_sell = equity * order.target.weight / sell_price
        delta = desired_buy - current if desired_buy >= current else desired_sell - current
        fill_price = buy_price if delta > 0 else sell_price
        if delta > 0:
            rate = Decimal("1") + self.cost_model.commission_bps / Decimal("10000")
            quantity = min(delta, cash / (fill_price * rate))
        else:
            quantity = max(delta, -current)
        if quantity == 0:
            return (
                cash,
                OrderEvent(
                    order.symbol, order.earliest_fill_timestamp, "rejected", "zero-quantity"
                ),
                None,
            )
        fill_price = self.cost_model.fill_price(market_price, quantity)
        gross = abs(quantity * fill_price)
        commission = self.cost_model.commission(gross)
        if quantity > 0:
            cash -= gross + commission
            positions[order.symbol] = current + quantity
        else:
            cash += gross - commission
            positions[order.symbol] = current + quantity
        trade = Trade(
            order.symbol,
            order.decision_timestamp,
            order.earliest_fill_timestamp,
            quantity,
            market_price,
            fill_price,
            gross,
            commission,
            abs(fill_price - market_price) * abs(quantity),
        )
        return (
            cash,
            OrderEvent(order.symbol, order.earliest_fill_timestamp, "filled", "", quantity),
            trade,
        )

    @staticmethod
    def _check_bars(bars: Sequence[OHLCVBar]) -> None:
        if not bars:
            raise BacktestError("backtest requires at least one bar")
        seen: set[tuple[Symbol, object]] = set()
        for bar in bars:
            key = (bar.symbol, bar.timestamp)
            if key in seen:
                raise BacktestError(f"duplicate bar: {bar.symbol}@{bar.timestamp}")
            seen.add(key)

    @staticmethod
    def _equity_point(
        timestamp: datetime,
        cash: Decimal,
        positions: Mapping[Symbol, Decimal],
        marks: Mapping[Symbol, Decimal],
    ) -> EquityPoint:
        equity = cash + sum(
            (quantity * marks[symbol] for symbol, quantity in positions.items()), Decimal("0")
        )
        return EquityPoint(
            timestamp,
            equity,
            cash,
            tuple(sorted(positions.items(), key=lambda item: item[0].value)),
        )

    @staticmethod
    def _metrics(curve: Sequence[EquityPoint], trades: Sequence[Trade]) -> BacktestMetrics:
        initial = curve[0].equity
        final = curve[-1].equity
        peak = initial
        drawdown = Decimal("0")
        for point in curve:
            peak = max(peak, point.equity)
            drawdown = max(drawdown, (peak - point.equity) / peak if peak else Decimal("0"))
        turnover = sum((trade.gross_notional for trade in trades), Decimal("0")) / initial
        return BacktestMetrics(final / initial - Decimal("1"), drawdown, turnover, len(trades))
