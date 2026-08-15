"""Small event-driven bar backtester with explicit fill timing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import StrEnum
from itertools import groupby
from types import MappingProxyType
from typing import Protocol
from zoneinfo import ZoneInfo

from .calendar import expected_bar_timestamps
from .domain import OHLCVBar, Symbol, Timeframe
from .fingerprints import fingerprint
from .strategies import TargetPosition


class IntradaySessionPolicy(StrEnum):
    DAY_TRADING_FLAT = "XNYS-regular-session-flat-v1"


class Strategy(Protocol):
    @property
    def strategy_id(self) -> str: ...

    @property
    def version(self) -> str: ...

    def on_bar(self, bar: OHLCVBar, history: Sequence[OHLCVBar]) -> Sequence[TargetPosition]: ...


class PortfolioStrategy(Protocol):
    @property
    def strategy_id(self) -> str: ...

    @property
    def version(self) -> str: ...

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]: ...


@dataclass(frozen=True)
class CostModel:
    version: str = "conservative-bps-v1"
    slippage_bps: Decimal = Decimal("5")
    commission_bps: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("cost model version is required")
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
class SessionDecision:
    timestamp: datetime
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
    annualized_volatility: Decimal
    sharpe_ratio: Decimal | None
    average_gross_exposure: Decimal
    max_gross_exposure: Decimal
    profitable_session_rate: Decimal
    top_5_session_profit_share: Decimal | None
    top_instrument_profit_share: Decimal | None
    up_regime_return: Decimal | None
    down_regime_return: Decimal | None
    up_regime_sessions: int
    down_regime_sessions: int


@dataclass(frozen=True)
class BacktestResult:
    strategy_id: str
    strategy_version: str
    initial_cash: Decimal
    equity_curve: tuple[EquityPoint, ...]
    decisions: tuple[Decision | SessionDecision, ...]
    orders: tuple[OrderEvent, ...]
    trades: tuple[Trade, ...]
    metrics: BacktestMetrics
    artifact_fingerprint: str


class BacktestError(ValueError):
    pass


class BacktestEngine:
    def __init__(
        self,
        initial_cash: Decimal,
        cost_model: CostModel | None = None,
        fill_delay_bars: int = 1,
        timeframe: Timeframe = Timeframe.DAILY,
        session_policy: IntradaySessionPolicy | None = None,
        queue_portfolio_targets: bool = False,
    ) -> None:
        if initial_cash <= 0:
            raise ValueError("initial cash must be positive")
        if fill_delay_bars < 1:
            raise ValueError("fill delay must be at least one bar")
        if timeframe is not Timeframe.DAILY and not timeframe.is_supported_intraday:
            raise ValueError("backtests support only 1d, 1m, and 5m bars")
        if session_policy is not None and not timeframe.is_supported_intraday:
            raise ValueError("intraday session policy requires an intraday timeframe")
        self.initial_cash = initial_cash
        self.cost_model = cost_model or CostModel()
        self.fill_delay_bars = fill_delay_bars
        self.timeframe = timeframe
        self.session_policy = session_policy
        self.queue_portfolio_targets = queue_portfolio_targets

    def run(self, bars: Sequence[OHLCVBar], strategy: Strategy) -> BacktestResult:
        ordered = tuple(sorted(bars, key=lambda bar: (bar.timestamp, bar.symbol.value)))
        self._check_bars(ordered)
        self._check_day_trading_sessions(ordered)
        next_bar = self._next_bars(ordered)
        final_session_bars = self._final_session_bars(ordered)
        cash = self.initial_cash
        positions: dict[Symbol, Decimal] = {}
        marks: dict[Symbol, Decimal] = {}
        history: dict[Symbol, list[OHLCVBar]] = {}
        pending: dict[Symbol, Order] = {}
        decisions: list[Decision] = []
        orders: list[OrderEvent] = []
        trades: list[Trade] = []
        curve: list[EquityPoint] = []

        for bar in ordered:
            marks[bar.symbol] = bar.open
            pending_order = pending.get(bar.symbol)
            if pending_order is not None and bar.timestamp >= pending_order.earliest_fill_timestamp:
                pending.pop(bar.symbol)
                cash, event, trade = self._execute(pending_order, bar.open, cash, positions, marks)
                orders.append(event)
                if trade is not None:
                    trades.append(trade)

            marks[bar.symbol] = bar.close
            symbol_history = history.setdefault(bar.symbol, [])
            symbol_history.append(bar)
            strategy_targets = tuple(strategy.on_bar(bar, tuple(symbol_history)))
            targets: tuple[TargetPosition, ...]
            decision_timestamp = _bar_observable_timestamp(bar, self.timeframe)
            if self._must_flatten(bar, next_bar, final_session_bars):
                pending_order = pending.pop(bar.symbol, None)
                if pending_order is not None:
                    orders.append(
                        OrderEvent(
                            bar.symbol,
                            decision_timestamp,
                            "rejected",
                            "session-close-cutoff",
                        )
                    )
                orders.extend(
                    OrderEvent(
                        target.symbol,
                        decision_timestamp,
                        "rejected",
                        "session-close-cutoff",
                    )
                    for target in strategy_targets
                    if target.weight > 0
                )
                targets = (
                    (TargetPosition(bar.symbol, Decimal("0"), "mandatory-session-flatten"),)
                    if positions.get(bar.symbol, Decimal("0")) > 0
                    else ()
                )
            else:
                targets = strategy_targets
            decisions.append(
                Decision(
                    decision_timestamp,
                    bar.symbol,
                    strategy.strategy_id,
                    strategy.version,
                    targets,
                )
            )
            for target in targets:
                if target.symbol != bar.symbol:
                    orders.append(
                        OrderEvent(
                            target.symbol,
                            decision_timestamp,
                            "rejected",
                            "cross-symbol-target",
                        )
                    )
                    continue
                if not Decimal("0") <= target.weight <= Decimal("1"):
                    orders.append(
                        OrderEvent(
                            target.symbol,
                            decision_timestamp,
                            "rejected",
                            "weight-out-of-range",
                        )
                    )
                    continue
                if target.symbol in pending:
                    orders.append(
                        OrderEvent(
                            target.symbol,
                            decision_timestamp,
                            "rejected",
                            "pending-order-exists",
                        )
                    )
                    continue
                following = next_bar.get((bar.symbol, bar.timestamp))
                if following is None:
                    orders.append(
                        OrderEvent(
                            target.symbol,
                            decision_timestamp,
                            "rejected",
                            "no-future-fill",
                        )
                    )
                    continue
                if following.timestamp < decision_timestamp:
                    raise BacktestError("next-bar fill precedes completed-bar observability")
                pending[bar.symbol] = Order(
                    bar.symbol,
                    decision_timestamp,
                    decision_timestamp,
                    following.timestamp,
                    target,
                )
            curve.append(self._equity_point(decision_timestamp, cash, positions, marks))
            if self._is_final_session_bar(bar, final_session_bars) and (
                positions.get(bar.symbol, Decimal("0")) != 0 or bar.symbol in pending
            ):
                raise BacktestError("day-trading session ended with exposure")

        for order in pending.values():
            orders.append(
                OrderEvent(
                    order.symbol, order.earliest_fill_timestamp, "rejected", "no-future-fill"
                )
            )
        return self._result(strategy, curve, decisions, orders, trades, ordered, positions, marks)

    def run_portfolio(
        self, bars: Sequence[OHLCVBar], strategy: PortfolioStrategy
    ) -> BacktestResult:
        ordered = tuple(sorted(bars, key=lambda bar: (bar.timestamp, bar.symbol.value)))
        self._check_bars(ordered)
        self._check_day_trading_sessions(ordered)
        next_bar = self._next_bars(ordered)
        final_session_bars = self._final_session_bars(ordered)
        universe = {bar.symbol for bar in ordered}
        cash = self.initial_cash
        positions: dict[Symbol, Decimal] = {}
        marks: dict[Symbol, Decimal] = {}
        history: dict[Symbol, list[OHLCVBar]] = {}
        pending: dict[Symbol, list[Order]] = {}
        decisions: list[Decision | SessionDecision] = []
        orders: list[OrderEvent] = []
        trades: list[Trade] = []
        curve: list[EquityPoint] = []

        for timestamp, grouped in groupby(ordered, key=lambda bar: bar.timestamp):
            session = tuple(grouped)
            session_symbols = {bar.symbol for bar in session}
            if session_symbols != universe:
                raise BacktestError("portfolio backtest requires complete symbol sessions")

            for bar in session:
                marks[bar.symbol] = bar.open
            due: list[tuple[OHLCVBar, Order]] = []
            for bar in session:
                queued = pending.get(bar.symbol)
                pending_order = queued[0] if queued else None
                if (
                    pending_order is not None
                    and bar.timestamp >= pending_order.earliest_fill_timestamp
                ):
                    due.append((bar, pending_order))
            due.sort(
                key=lambda item: (
                    not self._reduces_position(item[1], item[0].open, cash, positions, marks),
                    item[0].symbol.value,
                )
            )
            for bar, pending_order in due:
                queued = pending[bar.symbol]
                if queued.pop(0) != pending_order:
                    raise BacktestError("portfolio pending order queue differs")
                if not queued:
                    del pending[bar.symbol]
                cash, event, trade = self._execute(pending_order, bar.open, cash, positions, marks)
                orders.append(event)
                if trade is not None:
                    trades.append(trade)

            for bar in session:
                marks[bar.symbol] = bar.close
                history.setdefault(bar.symbol, []).append(bar)
            frozen_history = MappingProxyType(
                {
                    symbol: tuple(symbol_history)
                    for symbol, symbol_history in sorted(
                        history.items(), key=lambda item: item[0].value
                    )
                }
            )
            targets = tuple(
                sorted(
                    strategy.on_session(session, frozen_history),
                    key=lambda target: target.symbol.value,
                )
            )
            decision_timestamp = _bar_observable_timestamp(session[0], self.timeframe)
            if self._must_flatten(session[0], next_bar, final_session_bars):
                for symbol, queued in tuple(pending.items()):
                    del pending[symbol]
                    orders.extend(
                        OrderEvent(
                            pending_order.symbol,
                            decision_timestamp,
                            "rejected",
                            "session-close-cutoff",
                        )
                        for pending_order in queued
                    )
                orders.extend(
                    OrderEvent(
                        target.symbol,
                        decision_timestamp,
                        "rejected",
                        "session-close-cutoff",
                    )
                    for target in targets
                    if target.weight > 0
                )
                targets = (
                    tuple(
                        TargetPosition(symbol, Decimal("0"), "mandatory-session-flatten")
                        for symbol in sorted(universe, key=lambda item: item.value)
                    )
                    if any(positions.get(symbol, Decimal("0")) > 0 for symbol in universe)
                    else ()
                )
            decisions.append(
                SessionDecision(decision_timestamp, strategy.strategy_id, strategy.version, targets)
            )
            rejection = self._portfolio_rejection(
                targets,
                timestamp,
                session_symbols,
                pending,
                next_bar,
                queue_pending=self.queue_portfolio_targets,
            )
            if rejection is not None:
                orders.extend(
                    OrderEvent(target.symbol, decision_timestamp, "rejected", rejection)
                    for target in targets
                )
            else:
                for target in targets:
                    following = next_bar[(target.symbol, timestamp)]
                    if following.timestamp < decision_timestamp:
                        raise BacktestError("next-bar fill precedes completed-bar observability")
                    pending.setdefault(target.symbol, []).append(
                        Order(
                            target.symbol,
                            decision_timestamp,
                            decision_timestamp,
                            following.timestamp,
                            target,
                        )
                    )
            curve.append(self._equity_point(decision_timestamp, cash, positions, marks))
            if self._is_final_session_bar(session[0], final_session_bars) and (
                any(positions.get(symbol, Decimal("0")) != 0 for symbol in universe) or pending
            ):
                raise BacktestError("day-trading session ended with exposure")

        for queued in pending.values():
            for order in queued:
                orders.append(
                    OrderEvent(
                        order.symbol,
                        order.earliest_fill_timestamp,
                        "rejected",
                        "no-future-fill",
                    )
                )
        return self._result(strategy, curve, decisions, orders, trades, ordered, positions, marks)

    def _result(
        self,
        strategy: Strategy | PortfolioStrategy,
        curve: Sequence[EquityPoint],
        decisions: Sequence[Decision | SessionDecision],
        orders: Sequence[OrderEvent],
        trades: Sequence[Trade],
        bars: Sequence[OHLCVBar],
        positions: Mapping[Symbol, Decimal],
        marks: Mapping[Symbol, Decimal],
    ) -> BacktestResult:
        metrics = self._metrics(curve, trades, bars, positions, marks)
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

    def _next_bars(self, bars: Sequence[OHLCVBar]) -> dict[tuple[Symbol, datetime], OHLCVBar]:
        next_bar: dict[tuple[Symbol, datetime], OHLCVBar] = {}
        for symbol in {bar.symbol for bar in bars}:
            symbol_bars = tuple(bar for bar in bars if bar.symbol == symbol)
            for index, bar in enumerate(symbol_bars[: -self.fill_delay_bars]):
                following = symbol_bars[index + self.fill_delay_bars]
                if self.session_policy is None or _exchange_session(bar) == _exchange_session(
                    following
                ):
                    next_bar[(symbol, bar.timestamp)] = following
        return next_bar

    def _must_flatten(
        self,
        bar: OHLCVBar,
        next_bars: Mapping[tuple[Symbol, datetime], OHLCVBar],
        final_session_bars: set[tuple[Symbol, datetime]],
    ) -> bool:
        if self.session_policy is not IntradaySessionPolicy.DAY_TRADING_FLAT:
            return False
        following = next_bars.get((bar.symbol, bar.timestamp))
        return following is not None and self._is_final_session_bar(following, final_session_bars)

    def _is_final_session_bar(
        self, bar: OHLCVBar, final_session_bars: set[tuple[Symbol, datetime]]
    ) -> bool:
        return self.session_policy is not None and (bar.symbol, bar.timestamp) in final_session_bars

    def _final_session_bars(self, bars: Sequence[OHLCVBar]) -> set[tuple[Symbol, datetime]]:
        if self.session_policy is None:
            return set()
        final: dict[tuple[Symbol, date], datetime] = {}
        for bar in bars:
            final[(bar.symbol, _exchange_session(bar))] = bar.timestamp
        return {(symbol, timestamp) for (symbol, _), timestamp in final.items()}

    def _check_day_trading_sessions(self, bars: Sequence[OHLCVBar]) -> None:
        if self.session_policy is None or not bars:
            return
        sessions = tuple(_exchange_session(bar) for bar in bars)
        expected = set(
            expected_bar_timestamps(
                datetime.combine(min(sessions), time.min, tzinfo=UTC),
                datetime.combine(max(sessions), time.max, tzinfo=UTC),
                self.timeframe,
            )
        )
        for symbol in {bar.symbol for bar in bars}:
            actual = {bar.timestamp for bar in bars if bar.symbol == symbol}
            if actual != expected:
                raise BacktestError("day-trading policy requires complete XNYS sessions")

    @staticmethod
    def _portfolio_rejection(
        targets: Sequence[TargetPosition],
        timestamp: datetime,
        session_symbols: set[Symbol],
        pending: Mapping[Symbol, Sequence[Order]],
        next_bars: Mapping[tuple[Symbol, datetime], OHLCVBar],
        *,
        queue_pending: bool = False,
    ) -> str | None:
        symbols = tuple(target.symbol for target in targets)
        if len(symbols) != len(set(symbols)):
            return "duplicate-portfolio-target"
        if targets and set(symbols) != session_symbols:
            return "portfolio-symbols-differ"
        if any(not Decimal("0") <= target.weight <= Decimal("1") for target in targets):
            return "weight-out-of-range"
        if sum((target.weight for target in targets), Decimal("0")) > Decimal("1"):
            return "portfolio-weight-out-of-range"
        if not queue_pending and any(symbol in pending for symbol in symbols):
            return "pending-order-exists"
        if any((symbol, timestamp) not in next_bars for symbol in symbols):
            return "no-future-fill"
        return None

    def _reduces_position(
        self,
        order: Order,
        market_price: Decimal,
        cash: Decimal,
        positions: Mapping[Symbol, Decimal],
        marks: Mapping[Symbol, Decimal],
    ) -> bool:
        current = positions.get(order.symbol, Decimal("0"))
        equity = cash + sum(
            (quantity * marks[symbol] for symbol, quantity in positions.items()), Decimal("0")
        )
        desired_buy = (
            equity * order.target.weight / self.cost_model.fill_price(market_price, Decimal("1"))
        )
        return desired_buy < current

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

    def _metrics(
        self,
        curve: Sequence[EquityPoint],
        trades: Sequence[Trade],
        bars: Sequence[OHLCVBar],
        positions: Mapping[Symbol, Decimal],
        marks: Mapping[Symbol, Decimal],
    ) -> BacktestMetrics:
        sessions = _session_points(curve, self.timeframe)
        final = sessions[-1].equity
        peak = self.initial_cash
        drawdown = Decimal("0")
        for point in sessions:
            peak = max(peak, point.equity)
            drawdown = max(drawdown, (peak - point.equity) / peak if peak else Decimal("0"))
        turnover = sum((trade.gross_notional for trade in trades), Decimal("0")) / self.initial_cash
        returns = _session_returns(sessions, self.initial_cash)
        mean_return = sum(returns, Decimal("0")) / Decimal(len(returns))
        variance = (
            sum(((value - mean_return) ** 2 for value in returns), Decimal("0"))
            / Decimal(len(returns) - 1)
            if len(returns) > 1
            else Decimal("0")
        )
        daily_volatility = variance.sqrt()
        annualized_volatility = daily_volatility * Decimal("252").sqrt()
        sharpe_ratio = (
            mean_return / daily_volatility * Decimal("252").sqrt() if daily_volatility else None
        )
        exposures = tuple(
            max(Decimal("0"), (point.equity - point.cash) / point.equity)
            if point.equity
            else Decimal("0")
            for point in sessions
        )
        session_profits = _session_profits(sessions, self.initial_cash)
        positive_profits = sorted(
            (profit for profit in session_profits if profit > 0), reverse=True
        )
        total_positive_profit = sum(positive_profits, Decimal("0"))
        top_session_share = (
            sum(positive_profits[:5], Decimal("0")) / total_positive_profit
            if total_positive_profit
            else None
        )
        instrument_share = _top_instrument_profit_share(trades, positions, marks)
        up_return, down_return, up_sessions, down_sessions = _regime_metrics(
            bars, sessions, self.initial_cash, self.timeframe
        )
        return BacktestMetrics(
            total_return=final / self.initial_cash - Decimal("1"),
            max_drawdown=drawdown,
            turnover=turnover,
            trade_count=len(trades),
            annualized_volatility=annualized_volatility,
            sharpe_ratio=sharpe_ratio,
            average_gross_exposure=sum(exposures, Decimal("0")) / Decimal(len(exposures)),
            max_gross_exposure=max(exposures),
            profitable_session_rate=Decimal(len(positive_profits)) / Decimal(len(returns)),
            top_5_session_profit_share=top_session_share,
            top_instrument_profit_share=instrument_share,
            up_regime_return=up_return,
            down_regime_return=down_return,
            up_regime_sessions=up_sessions,
            down_regime_sessions=down_sessions,
        )


def _session_points(curve: Sequence[EquityPoint], timeframe: Timeframe) -> tuple[EquityPoint, ...]:
    if not timeframe.is_supported_intraday:
        by_timestamp: dict[datetime, EquityPoint] = {}
        for point in curve:
            by_timestamp[point.timestamp] = point
        return tuple(by_timestamp.values())
    by_session: dict[object, EquityPoint] = {}
    for point in curve:
        by_session[point.timestamp.astimezone(ZoneInfo("America/New_York")).date()] = point
    return tuple(by_session.values())


def _session_returns(sessions: Sequence[EquityPoint], initial_cash: Decimal) -> tuple[Decimal, ...]:
    previous = initial_cash
    returns: list[Decimal] = []
    for point in sessions:
        returns.append(point.equity / previous - Decimal("1"))
        previous = point.equity
    return tuple(returns)


def _session_profits(sessions: Sequence[EquityPoint], initial_cash: Decimal) -> tuple[Decimal, ...]:
    previous = initial_cash
    profits: list[Decimal] = []
    for point in sessions:
        profits.append(point.equity - previous)
        previous = point.equity
    return tuple(profits)


def _top_instrument_profit_share(
    trades: Sequence[Trade],
    positions: Mapping[Symbol, Decimal],
    marks: Mapping[Symbol, Decimal],
) -> Decimal | None:
    symbols = set(positions) | {trade.symbol for trade in trades}
    profits: list[Decimal] = []
    for symbol in symbols:
        net_investment = sum(
            (
                trade.quantity * trade.fill_price + trade.commission
                for trade in trades
                if trade.symbol == symbol
            ),
            Decimal("0"),
        )
        final_value = positions.get(symbol, Decimal("0")) * marks[symbol]
        profit = final_value - net_investment
        if profit > 0:
            profits.append(profit)
    total = sum(profits, Decimal("0"))
    return max(profits) / total if total else None


def _regime_metrics(
    bars: Sequence[OHLCVBar],
    sessions: Sequence[EquityPoint],
    initial_cash: Decimal,
    timeframe: Timeframe,
) -> tuple[Decimal | None, Decimal | None, int, int]:
    spy = Symbol("SPY")
    benchmark = tuple(bar for bar in bars if bar.symbol == spy)
    if timeframe.is_supported_intraday:
        by_session: dict[object, OHLCVBar] = {}
        exchange_timezone = ZoneInfo("America/New_York")
        for bar in benchmark:
            by_session[bar.timestamp.astimezone(exchange_timezone).date()] = bar
        benchmark = tuple(by_session.values())
    if len(benchmark) < 2:
        return None, None, 0, 0
    strategy_returns = {
        point.timestamp: value
        for point, value in zip(sessions, _session_returns(sessions, initial_cash), strict=True)
    }
    up: list[Decimal] = []
    down: list[Decimal] = []
    for previous, current in zip(benchmark, benchmark[1:], strict=False):
        strategy_return = strategy_returns.get(_bar_observable_timestamp(current, timeframe))
        if strategy_return is None:
            continue
        benchmark_return = current.close / previous.close - Decimal("1")
        (up if benchmark_return >= 0 else down).append(strategy_return)
    return _compound(up), _compound(down), len(up), len(down)


def _bar_observable_timestamp(bar: OHLCVBar, timeframe: Timeframe) -> datetime:
    return bar.timestamp + timeframe.duration if timeframe.is_supported_intraday else bar.timestamp


def _exchange_session(bar: OHLCVBar) -> date:
    return bar.timestamp.astimezone(ZoneInfo("America/New_York")).date()


def _compound(returns: Sequence[Decimal]) -> Decimal | None:
    if not returns:
        return None
    value = Decimal("1")
    for result in returns:
        value *= Decimal("1") + result
    return value - Decimal("1")
