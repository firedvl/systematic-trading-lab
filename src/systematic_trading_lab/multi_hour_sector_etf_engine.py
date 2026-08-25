"""Atomic long/flat replay mechanics for Program 002."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from zoneinfo import ZoneInfo

from .domain import OHLCVBar, Symbol
from .intraday_execution_cost_model import RegulatoryFeeModel, RegulatoryFill
from .multi_hour_sector_etf_features import SelectionTrace

_NEW_YORK = ZoneInfo("America/New_York")
_SPY = Symbol("SPY")
_BPS = Decimal("10000")
_INITIAL_CASH = Decimal("100000")
_SLOT_WEIGHT = Decimal("0.3333333333333333333333333333")


@dataclass(frozen=True)
class Program002CostScenario:
    scenario_id: str
    slippage_bps_per_fill: Mapping[Symbol, Decimal]
    execution_delay_bars: int
    regulatory_fees_enabled: bool

    def __post_init__(self) -> None:
        expected_symbols = {
            Symbol(value)
            for value in (
                "IWM",
                "MDY",
                "SPY",
                "XLB",
                "XLE",
                "XLF",
                "XLI",
                "XLK",
                "XLP",
                "XLRE",
                "XLU",
                "XLV",
                "XLY",
            )
        }
        if not self.scenario_id or self.execution_delay_bars not in {1, 2, 3}:
            raise ValueError("Program 002 cost scenario identity differs")
        if set(self.slippage_bps_per_fill) != expected_symbols or any(
            not value.is_finite() or value < 0 for value in self.slippage_bps_per_fill.values()
        ):
            raise ValueError("Program 002 cost scenario spreads are invalid")
        object.__setattr__(
            self,
            "slippage_bps_per_fill",
            MappingProxyType(dict(self.slippage_bps_per_fill)),
        )

    def fill_price(self, symbol: Symbol, market_open: Decimal, side: str) -> Decimal:
        try:
            spread = self.slippage_bps_per_fill[symbol]
        except KeyError as error:
            raise ValueError("Program 002 cost scenario omits a symbol") from error
        direction = Decimal("1") if side == "buy" else Decimal("-1") if side == "sell" else None
        if direction is None or market_open <= 0:
            raise ValueError("Program 002 fill inputs are invalid")
        return market_open * (Decimal("1") + direction * spread / _BPS)


@dataclass(frozen=True)
class Program002Fill:
    symbol: Symbol
    trade_id: str
    side: str
    executed_at: datetime
    quantity: Decimal
    market_open: Decimal
    fill_price: Decimal
    gross_notional: Decimal


@dataclass(frozen=True)
class AccountReplay:
    initial_cash: Decimal
    final_cash: Decimal
    common_scale: Decimal
    preliminary_fee_reserve: Decimal
    regulatory_fees: Decimal
    adverse_spread_cost: Decimal
    gross_market_profit: Decimal
    net_profit: Decimal
    fills: tuple[Program002Fill, ...]
    regulatory_fee_by_trade: Mapping[str, Decimal]
    accounting_identity_error: Decimal
    equity_curve: tuple[tuple[datetime, Decimal], ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "regulatory_fee_by_trade",
            MappingProxyType(dict(self.regulatory_fee_by_trade)),
        )


@dataclass(frozen=True)
class SessionReplay:
    trace: SelectionTrace
    scenario_id: str
    candidate: AccountReplay
    benchmark: AccountReplay
    entry_timestamp: datetime | None
    exit_timestamp: datetime | None
    capacity_ratios: Mapping[Symbol, Decimal]

    def __post_init__(self) -> None:
        object.__setattr__(self, "capacity_ratios", MappingProxyType(dict(self.capacity_ratios)))


@dataclass(frozen=True)
class PeriodReplay:
    scenario_id: str
    sessions: tuple[SessionReplay, ...]
    candidate_initial_cash: Decimal
    candidate_final_cash: Decimal
    benchmark_initial_cash: Decimal
    benchmark_final_cash: Decimal

    @property
    def candidate_return(self) -> Decimal:
        return self.candidate_final_cash / self.candidate_initial_cash - 1

    @property
    def benchmark_return(self) -> Decimal:
        return self.benchmark_final_cash / self.benchmark_initial_cash - 1


def replay_program_002_session(
    trace: SelectionTrace,
    bars: Sequence[OHLCVBar],
    scenario: Program002CostScenario,
    fee_model: RegulatoryFeeModel | None,
    *,
    candidate_initial_cash: Decimal = _INITIAL_CASH,
    benchmark_initial_cash: Decimal = _INITIAL_CASH,
) -> SessionReplay:
    """Replay one immutable trace without resizing, reentry, or symbol-order sizing."""
    if scenario.regulatory_fees_enabled != (fee_model is not None):
        raise ValueError("Program 002 regulatory fee binding differs")
    if any(
        not value.is_finite() or value <= 0
        for value in (candidate_initial_cash, benchmark_initial_cash)
    ):
        raise ValueError("Program 002 initial cash must be finite and positive")
    if not trace.selected_symbols:
        return SessionReplay(
            trace,
            scenario.scenario_id,
            _empty_account(candidate_initial_cash),
            _empty_account(benchmark_initial_cash),
            None,
            None,
            {},
        )
    entry_timestamp = trace.decision_timestamp + timedelta(
        minutes=5 * scenario.execution_delay_bars
    )
    exit_timestamp = entry_timestamp + timedelta(minutes=30 * trace.hold_30m_bars)
    session = _session_bars(bars, trace.session_day)
    candidate_weights = {symbol: _SLOT_WEIGHT for symbol in trace.selected_symbols}
    candidate = _replay_account(
        trace,
        session,
        candidate_weights,
        scenario,
        fee_model,
        entry_timestamp,
        exit_timestamp,
        candidate_initial_cash,
    )
    features = {feature.symbol: feature for feature in trace.ordered_features}
    capacity_ratios: dict[Symbol, Decimal] = {}
    for fill in candidate.fills:
        if fill.side != "buy":
            continue
        capacity = features[fill.symbol].prior_median_dollar_volume * Decimal("0.01")
        if capacity <= 0:
            raise ValueError("Program 002 entry capacity denominator is invalid")
        market_notional = fill.quantity * fill.market_open
        ratio = market_notional / capacity
        capacity_ratios[fill.symbol] = ratio
        if ratio > 1:
            raise ValueError("Program 002 selected entry exceeds frozen capacity")
    benchmark = _replay_account(
        trace,
        session,
        {_SPY: Decimal(len(trace.selected_symbols)) * _SLOT_WEIGHT},
        scenario,
        fee_model,
        entry_timestamp,
        exit_timestamp,
        benchmark_initial_cash,
    )
    return SessionReplay(
        trace,
        scenario.scenario_id,
        candidate,
        benchmark,
        entry_timestamp,
        exit_timestamp,
        capacity_ratios,
    )


def replay_program_002_period(
    traces: Sequence[SelectionTrace],
    bars: Sequence[OHLCVBar],
    scenario: Program002CostScenario,
    fee_model: RegulatoryFeeModel | None,
    *,
    initial_cash: Decimal = _INITIAL_CASH,
) -> PeriodReplay:
    """Replay chronological flat-at-close sessions with independently carried account cash."""
    ordered = tuple(traces)
    if not ordered or tuple(trace.session_day for trace in ordered) != tuple(
        sorted({trace.session_day for trace in ordered})
    ):
        raise ValueError("Program 002 period traces must be unique and chronological")
    candidate_cash = benchmark_cash = initial_cash
    sessions: list[SessionReplay] = []
    for trace in ordered:
        replay = replay_program_002_session(
            trace,
            bars,
            scenario,
            fee_model,
            candidate_initial_cash=candidate_cash,
            benchmark_initial_cash=benchmark_cash,
        )
        candidate_cash = replay.candidate.final_cash
        benchmark_cash = replay.benchmark.final_cash
        sessions.append(replay)
    return PeriodReplay(
        scenario.scenario_id,
        tuple(sessions),
        initial_cash,
        candidate_cash,
        initial_cash,
        benchmark_cash,
    )


def _replay_account(
    trace: SelectionTrace,
    session: Mapping[Symbol, Mapping[datetime, OHLCVBar]],
    weights: Mapping[Symbol, Decimal],
    scenario: Program002CostScenario,
    fee_model: RegulatoryFeeModel | None,
    entry_timestamp: datetime,
    exit_timestamp: datetime,
    initial_cash: Decimal,
) -> AccountReplay:
    if not weights:
        return _empty_account(initial_cash)
    symbols = tuple(sorted(weights, key=lambda symbol: symbol.value))
    if any(weight <= 0 for weight in weights.values()) or sum(weights.values()) > 1:
        raise ValueError("Program 002 account weights are invalid")
    market_entries = {symbol: _bar(session, symbol, entry_timestamp).open for symbol in symbols}
    market_exits = {symbol: _bar(session, symbol, exit_timestamp).open for symbol in symbols}
    buy_prices = {
        symbol: scenario.fill_price(symbol, market_entries[symbol], "buy") for symbol in symbols
    }
    preliminary_quantities = {
        symbol: weights[symbol] * initial_cash / buy_prices[symbol] for symbol in symbols
    }
    preliminary_buys = _regulatory_fills(
        trace.session_day,
        symbols,
        preliminary_quantities,
        buy_prices,
        entry_timestamp,
        "buy",
    )
    fee_reserve = _charges(fee_model, trace.session_day, preliminary_buys)
    occupied_budget = sum(weights.values()) * initial_cash
    if fee_reserve < 0 or fee_reserve >= occupied_budget:
        raise ValueError("Program 002 preliminary fee reserve is invalid")
    scale = (occupied_budget - fee_reserve) / occupied_budget
    quantities = {symbol: scale * preliminary_quantities[symbol] for symbol in symbols}
    buys = _regulatory_fills(
        trace.session_day,
        symbols,
        quantities,
        buy_prices,
        entry_timestamp,
        "buy",
    )
    final_buy_fees = _charges(fee_model, trace.session_day, buys)
    if final_buy_fees > fee_reserve:
        raise ValueError("Program 002 fee model violates monotonicity")
    buy_notional = sum((fill.gross_notional for fill in buys), Decimal("0"))
    if initial_cash - buy_notional - final_buy_fees < 0:
        raise ValueError("Program 002 atomic entry would create negative cash")

    sell_prices = {
        symbol: scenario.fill_price(symbol, market_exits[symbol], "sell") for symbol in symbols
    }
    sells = _regulatory_fills(
        trace.session_day,
        symbols,
        quantities,
        sell_prices,
        exit_timestamp,
        "sell",
    )
    all_regulatory = (*buys, *sells)
    fees = _charges(fee_model, trace.session_day, all_regulatory)
    sell_notional = sum((fill.gross_notional for fill in sells), Decimal("0"))
    final_cash = initial_cash - buy_notional + sell_notional - fees
    if final_cash < 0:
        raise ValueError("Program 002 replay produced negative cash")
    program_fills = tuple(
        Program002Fill(
            fill_symbol,
            fill.trade_id,
            fill.side,
            fill.executed_at,
            fill.quantity,
            (market_entries if fill.side == "buy" else market_exits)[fill_symbol],
            fill.gross_notional / fill.quantity,
            fill.gross_notional,
        )
        for fill, fill_symbol in (
            *((fill, symbol) for fill, symbol in zip(buys, symbols, strict=True)),
            *((fill, symbol) for fill, symbol in zip(sells, symbols, strict=True)),
        )
    )
    gross_market_profit = sum(
        (
            quantities[symbol] * (market_exits[symbol] - market_entries[symbol])
            for symbol in symbols
        ),
        Decimal("0"),
    )
    spread_cost = sum(
        (
            quantities[symbol]
            * (
                (buy_prices[symbol] - market_entries[symbol])
                + (market_exits[symbol] - sell_prices[symbol])
            )
            for symbol in symbols
        ),
        Decimal("0"),
    )
    net_profit = final_cash - initial_cash
    independently_recomputed = initial_cash + gross_market_profit - spread_cost - fees
    buy_fees = _charges(fee_model, trace.session_day, buys)
    equity_curve = _marked_equity_curve(
        session,
        symbols,
        quantities,
        entry_timestamp,
        exit_timestamp,
        initial_cash - buy_notional - buy_fees,
        final_cash,
    )
    accounting_error = max(
        abs(final_cash - independently_recomputed),
        abs(equity_curve[-1][1] - final_cash),
    )
    if accounting_error != 0:
        raise ValueError("Program 002 accounting identity differs")
    return AccountReplay(
        initial_cash,
        final_cash,
        scale,
        fee_reserve,
        fees,
        spread_cost,
        gross_market_profit,
        net_profit,
        program_fills,
        _allocate_fees_by_trade(fee_model, trace.session_day, all_regulatory),
        accounting_error,
        equity_curve,
    )


def _regulatory_fills(
    session_day: date,
    symbols: Sequence[Symbol],
    quantities: Mapping[Symbol, Decimal],
    prices: Mapping[Symbol, Decimal],
    executed_at: datetime,
    side: str,
) -> tuple[RegulatoryFill, ...]:
    return tuple(
        RegulatoryFill(
            executed_at,
            f"{session_day.isoformat()}:{symbol.value}",
            side,  # type: ignore[arg-type]
            quantities[symbol],
            quantities[symbol] * prices[symbol],
        )
        for symbol in symbols
    )


def _charges(
    fee_model: RegulatoryFeeModel | None,
    session_day: date,
    fills: Sequence[RegulatoryFill],
) -> Decimal:
    return (
        Decimal("0")
        if fee_model is None
        else fee_model.charges_for_account_day(session_day, tuple(fills)).total
    )


def _allocate_fees_by_trade(
    fee_model: RegulatoryFeeModel | None,
    session_day: date,
    fills: Sequence[RegulatoryFill],
) -> dict[str, Decimal]:
    trade_ids = tuple(sorted({fill.trade_id for fill in fills}))
    result = {trade_id: Decimal("0") for trade_id in trade_ids}
    if fee_model is None:
        return result
    charges = fee_model.charges_for_account_day(session_day, tuple(fills))
    contribution_sets = (
        (
            charges.sec,
            {
                trade_id: sum(
                    (
                        fill.gross_notional * fee_model.sec_rate_per_dollar
                        for fill in fills
                        if fill.trade_id == trade_id and fill.side == "sell"
                    ),
                    Decimal("0"),
                )
                for trade_id in trade_ids
            },
        ),
        (
            charges.taf,
            {
                trade_id: min(
                    sum(
                        (
                            fill.quantity
                            for fill in fills
                            if fill.trade_id == trade_id and fill.side == "sell"
                        ),
                        Decimal("0"),
                    )
                    * fee_model.taf_rate_per_share,
                    fee_model.taf_maximum_per_trade,
                )
                for trade_id in trade_ids
            },
        ),
        (
            charges.cat,
            {
                trade_id: sum(
                    (fill.quantity for fill in fills if fill.trade_id == trade_id),
                    Decimal("0"),
                )
                * fee_model.cat_rate_per_share
                for trade_id in trade_ids
            },
        ),
    )
    for component, contributions in contribution_sets:
        total = sum(contributions.values(), Decimal("0"))
        if component == 0 or total == 0:
            continue
        allocated = Decimal("0")
        for trade_id in trade_ids[:-1]:
            share = component * contributions[trade_id] / total
            result[trade_id] += share
            allocated += share
        result[trade_ids[-1]] += component - allocated
    if sum(result.values(), Decimal("0")) != charges.total:
        raise ValueError("Program 002 fee allocation does not reconcile")
    return result


def _session_bars(
    bars: Sequence[OHLCVBar], session_day: date
) -> Mapping[Symbol, Mapping[datetime, OHLCVBar]]:
    result: dict[Symbol, dict[datetime, OHLCVBar]] = {}
    for bar in bars:
        if bar.timestamp.astimezone(_NEW_YORK).date() != session_day:
            continue
        symbol_bars = result.setdefault(bar.symbol, {})
        if bar.timestamp in symbol_bars:
            raise ValueError("Program 002 replay input contains a duplicate fill bar")
        symbol_bars[bar.timestamp] = bar
    return MappingProxyType(
        {symbol: MappingProxyType(symbol_bars) for symbol, symbol_bars in result.items()}
    )


def _bar(
    session: Mapping[Symbol, Mapping[datetime, OHLCVBar]],
    symbol: Symbol,
    timestamp: datetime,
) -> OHLCVBar:
    try:
        return session[symbol][timestamp]
    except KeyError as error:
        raise ValueError("Program 002 scheduled fill bar is missing") from error


def _empty_account(initial_cash: Decimal) -> AccountReplay:
    return AccountReplay(
        initial_cash,
        initial_cash,
        Decimal("1"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        (),
        {},
        Decimal("0"),
        (),
    )


def _marked_equity_curve(
    session: Mapping[Symbol, Mapping[datetime, OHLCVBar]],
    symbols: Sequence[Symbol],
    quantities: Mapping[Symbol, Decimal],
    entry_timestamp: datetime,
    exit_timestamp: datetime,
    entry_cash: Decimal,
    final_cash: Decimal,
) -> tuple[tuple[datetime, Decimal], ...]:
    timestamps = tuple(
        timestamp
        for timestamp in sorted(session[symbols[0]])
        if entry_timestamp <= timestamp <= exit_timestamp
    )
    if not timestamps or timestamps[0] != entry_timestamp or timestamps[-1] != exit_timestamp:
        raise ValueError("Program 002 marked-equity grid is incomplete")
    # The entry fill exists before the source bar closes.  Preserve that adverse
    # spread/fee mark so an intra-bar recovery cannot hide the entry drawdown.
    result = [
        (
            entry_timestamp,
            entry_cash
            + sum(
                (
                    quantities[symbol] * _bar(session, symbol, entry_timestamp).open
                    for symbol in symbols
                ),
                Decimal("0"),
            ),
        )
    ]
    for timestamp in timestamps[:-1]:
        result.append(
            (
                timestamp,
                entry_cash
                + sum(
                    (
                        quantities[symbol] * _bar(session, symbol, timestamp).close
                        for symbol in symbols
                    ),
                    Decimal("0"),
                ),
            )
        )
    result.append((exit_timestamp, final_cash))
    return tuple(result)


def maximum_drawdown(account: AccountReplay) -> Decimal:
    """Exact peak-to-trough drawdown over the synchronized five-minute mark curve."""
    if not account.equity_curve:
        return Decimal("0")
    peak = account.initial_cash
    drawdown = Decimal("0")
    for _timestamp, equity in account.equity_curve:
        peak = max(peak, equity)
        if peak <= 0:
            raise ValueError("Program 002 marked equity peak is invalid")
        drawdown = max(drawdown, (peak - equity) / peak)
    return drawdown
