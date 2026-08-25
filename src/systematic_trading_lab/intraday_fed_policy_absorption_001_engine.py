"""Isolated five-minute replay for Fed Policy Absorption 001."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from itertools import groupby
from types import MappingProxyType
from typing import Protocol
from zoneinfo import ZoneInfo

from .backtesting import BacktestError, EquityPoint
from .calendar import expected_bar_timestamps
from .domain import OHLCVBar, Symbol, Timeframe
from .fingerprints import fingerprint
from .intraday_execution_cost_model import (
    DailyRegulatoryCharges,
    ExecutionCostScenario,
    RegulatoryFeeModel,
    RegulatoryFill,
)
from .strategies import TargetPosition

_NEW_YORK = ZoneInfo("America/New_York")
_ZERO = Decimal("0")
_HALF = Decimal("0.5")
_ONE = Decimal("1")
_SYMBOLS = (Symbol("SPY"), Symbol("QQQ"))


class Exposed002Strategy(Protocol):
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
class Exposed002Decision:
    timestamp: datetime
    desired_targets: tuple[TargetPosition, ...]
    changed_symbols: tuple[Symbol, ...]
    session_close_cutoff: bool


@dataclass(frozen=True)
class Exposed002Transition:
    sequence: int
    symbol: Symbol
    decision_timestamp: datetime
    eligible_fill_timestamp: datetime | None
    from_weight: Decimal
    to_weight: Decimal
    status: str
    source: str
    reason: str
    quantity: Decimal = _ZERO


@dataclass(frozen=True)
class Exposed002Fill:
    sequence: int
    trade_id: str
    symbol: Symbol
    decision_timestamp: datetime
    fill_timestamp: datetime
    quantity: Decimal
    market_price: Decimal
    fill_price: Decimal
    gross_notional: Decimal
    adverse_slippage: Decimal

    @property
    def side(self) -> str:
        return "buy" if self.quantity > 0 else "sell"


@dataclass(frozen=True)
class Exposed002RoundTrip:
    trade_id: str
    symbol: Symbol
    entry_timestamp: datetime
    exit_timestamp: datetime
    quantity: Decimal
    entry_market_price: Decimal
    exit_market_price: Decimal
    entry_fill_price: Decimal
    exit_fill_price: Decimal

    @property
    def gross_profit(self) -> Decimal:
        return self.quantity * (self.exit_market_price - self.entry_market_price)

    @property
    def net_before_regulatory_fees(self) -> Decimal:
        return self.quantity * (self.exit_fill_price - self.entry_fill_price)

    @property
    def holding_bars(self) -> Decimal:
        return Decimal(
            str((self.exit_timestamp - self.entry_timestamp) / Timeframe.FIVE_MINUTES.duration)
        )


@dataclass(frozen=True)
class Exposed002DailyFees:
    account_day: str
    charges: DailyRegulatoryCharges
    by_symbol: tuple[tuple[Symbol, Decimal], ...]
    fills_fingerprint: str


@dataclass(frozen=True)
class _PendingTransition:
    sequence: int
    symbol: Symbol
    decision_timestamp: datetime
    eligible_fill_timestamp: datetime
    from_weight: Decimal
    to_weight: Decimal
    source: str
    reason: str


@dataclass(frozen=True)
class Exposed002ReplayResult:
    strategy_id: str
    strategy_version: str
    scenario_id: str
    initial_cash: Decimal
    decisions: tuple[Exposed002Decision, ...]
    transitions: tuple[Exposed002Transition, ...]
    fills: tuple[Exposed002Fill, ...]
    round_trips: tuple[Exposed002RoundTrip, ...]
    fee_ledger: tuple[Exposed002DailyFees, ...]
    equity_curve: tuple[EquityPoint, ...]
    artifact_fingerprint: str


class IntradayFedPolicyAbsorption001Engine:
    """Replay frozen desired-state transitions with calibrated costs and daily fees."""

    def __init__(
        self,
        initial_cash: Decimal,
        scenario: ExecutionCostScenario,
        regulatory_fees: RegulatoryFeeModel,
    ) -> None:
        if not initial_cash.is_finite() or initial_cash <= 0:
            raise ValueError("Fed Policy Absorption 001 initial cash must be positive")
        if scenario.execution_delay_bars < 1:
            raise ValueError("Fed Policy Absorption 001 delay must be positive")
        self.initial_cash = initial_cash
        self.scenario = scenario
        self.regulatory_fees = regulatory_fees
        self.symbols = _SYMBOLS
        self.exact_joint_fills = True

    def run(
        self,
        bars: Sequence[OHLCVBar],
        strategy: Exposed002Strategy,
    ) -> Exposed002ReplayResult:
        ordered = tuple(sorted(bars, key=lambda bar: (bar.timestamp, bar.symbol.value)))
        slices, timestamps_by_session = self._validated_slices(ordered)
        index_by_timestamp = {
            timestamp: index
            for timestamps in timestamps_by_session.values()
            for index, timestamp in enumerate(timestamps)
        }

        cash = self.initial_cash
        positions: dict[Symbol, Decimal] = dict.fromkeys(self.symbols, _ZERO)
        marks: dict[Symbol, Decimal] = {}
        history: dict[Symbol, list[OHLCVBar]] = {symbol: [] for symbol in self.symbols}
        desired_state: dict[Symbol, Decimal] = dict.fromkeys(self.symbols, _ZERO)
        executed_state: dict[Symbol, Decimal] = dict.fromkeys(self.symbols, _ZERO)
        entries: dict[Symbol, int] = dict.fromkeys(self.symbols, 0)
        open_fills: dict[Symbol, Exposed002Fill] = {}
        pending: list[_PendingTransition] = []
        decisions: list[Exposed002Decision] = []
        transitions: list[Exposed002Transition] = []
        fills: list[Exposed002Fill] = []
        round_trips: list[Exposed002RoundTrip] = []
        fees: list[Exposed002DailyFees] = []
        curve: list[EquityPoint] = []
        active_session: date | None = None
        session_regulatory_fills: list[RegulatoryFill] = []
        joint_entry_equity: Decimal | None = None
        joint_spread_adjusted_return: Decimal | None = None
        sequence = 0

        for timestamp, session_slice in slices:
            session = _account_day(timestamp)
            session_timestamps = timestamps_by_session[session]
            session_index = index_by_timestamp[timestamp]
            cutoff_index = len(session_timestamps) - self.scenario.execution_delay_bars - 1
            final_timestamp = session_timestamps[-1]
            if session != active_session:
                if active_session is not None and (
                    pending or open_fills or any(positions.values()) or any(executed_state.values())
                ):
                    raise BacktestError(
                        "Fed Policy Absorption 001 session began with exposure "
                        "or queued transitions"
                    )
                active_session = session
                desired_state = dict.fromkeys(self.symbols, _ZERO)
                executed_state = dict.fromkeys(self.symbols, _ZERO)
                entries = dict.fromkeys(self.symbols, 0)
                session_regulatory_fills = []
                joint_entry_equity = None
                joint_spread_adjusted_return = None

            for bar in session_slice:
                marks[bar.symbol] = bar.open
            if any(item.eligible_fill_timestamp < timestamp for item in pending):
                raise BacktestError("Fed Policy Absorption 001 queued transition missed its fill")
            due = sorted(
                (item for item in pending if item.eligible_fill_timestamp == timestamp),
                key=lambda item: item.sequence,
            )
            pending = [item for item in pending if item.eligible_fill_timestamp != timestamp]
            changed_due = tuple(
                item for item in due if item.to_weight != executed_state[item.symbol]
            )
            if (
                self.exact_joint_fills
                and changed_due
                and (
                    len(changed_due) != len(self.symbols)
                    or {item.symbol for item in changed_due} != set(self.symbols)
                    or len({item.decision_timestamp for item in changed_due}) != 1
                    or len({item.to_weight for item in changed_due}) != 1
                    or changed_due[0].to_weight not in {_ZERO, _HALF}
                )
            ):
                raise BacktestError(
                    "Fed Policy Absorption 001 exact joint execution requires both symbols"
                )
            working_cash = cash
            working_positions = dict(positions)
            working_entries = dict(entries)
            working_open_fills = dict(open_fills)
            batch_transitions: list[Exposed002Transition] = []
            batch_fills: list[Exposed002Fill] = []
            batch_round_trips: list[Exposed002RoundTrip] = []
            batch_regulatory_fills: list[RegulatoryFill] = []
            entry_equity = (
                cash
                + sum(
                    (positions[symbol] * marks[symbol] for symbol in self.symbols),
                    _ZERO,
                )
                if self.exact_joint_fills and changed_due and changed_due[0].to_weight == _HALF
                else None
            )
            for item in due:
                current = executed_state[item.symbol]
                if item.to_weight == current:
                    batch_transitions.append(
                        Exposed002Transition(
                            item.sequence,
                            item.symbol,
                            item.decision_timestamp,
                            item.eligible_fill_timestamp,
                            item.from_weight,
                            item.to_weight,
                            "no-op",
                            item.source,
                            "state-already-realized",
                        )
                    )
                    continue
                market_price = next(bar.open for bar in session_slice if bar.symbol == item.symbol)
                working_cash, fill = self._fill(
                    item,
                    market_price,
                    working_cash,
                    working_positions,
                    marks,
                    working_entries,
                    working_open_fills,
                    entry_equity=entry_equity,
                )
                batch_fills.append(fill)
                batch_transitions.append(
                    Exposed002Transition(
                        item.sequence,
                        item.symbol,
                        item.decision_timestamp,
                        item.eligible_fill_timestamp,
                        item.from_weight,
                        item.to_weight,
                        "filled",
                        item.source,
                        item.reason,
                        fill.quantity,
                    )
                )
                regulatory_fill = RegulatoryFill(
                    fill.fill_timestamp,
                    fill.trade_id,
                    "buy" if fill.quantity > 0 else "sell",
                    abs(fill.quantity),
                    fill.gross_notional,
                )
                batch_regulatory_fills.append(regulatory_fill)
                if fill.quantity > 0:
                    working_open_fills[item.symbol] = fill
                else:
                    entry = working_open_fills.pop(item.symbol)
                    batch_round_trips.append(
                        Exposed002RoundTrip(
                            fill.trade_id,
                            item.symbol,
                            entry.fill_timestamp,
                            fill.fill_timestamp,
                            entry.quantity,
                            entry.market_price,
                            fill.market_price,
                            entry.fill_price,
                            fill.fill_price,
                        )
                    )
            if self.exact_joint_fills and changed_due:
                if changed_due[0].to_weight == _HALF:
                    if joint_entry_equity is not None or entry_equity is None:
                        raise BacktestError("Fed Policy Absorption 001 joint entry state differs")
                    joint_entry_equity = entry_equity
                    working_cash = _ZERO
                else:
                    if joint_entry_equity is None or set(working_open_fills):
                        raise BacktestError("Fed Policy Absorption 001 joint exit state differs")
                    entries_by_symbol = {fill.symbol: fill for fill in open_fills.values()}
                    exits_by_symbol = {fill.symbol: fill for fill in batch_fills}
                    joint_spread_adjusted_return = sum(
                        (
                            _HALF
                            * (
                                exits_by_symbol[symbol].fill_price
                                / entries_by_symbol[symbol].fill_price
                                - _ONE
                            )
                            for symbol in self.symbols
                        ),
                        _ZERO,
                    )
                    working_cash = joint_entry_equity * (_ONE + joint_spread_adjusted_return)
            cash = working_cash
            positions = working_positions
            entries = working_entries
            open_fills = working_open_fills
            for item in changed_due:
                executed_state[item.symbol] = item.to_weight
            transitions.extend(batch_transitions)
            fills.extend(batch_fills)
            round_trips.extend(batch_round_trips)
            session_regulatory_fills.extend(batch_regulatory_fills)

            for bar in session_slice:
                marks[bar.symbol] = bar.close
                history[bar.symbol].append(bar)
            frozen_history = MappingProxyType(
                {symbol: tuple(history[symbol]) for symbol in self.symbols}
            )
            targets = tuple(
                sorted(
                    strategy.on_session(session_slice, frozen_history),
                    key=lambda target: self.symbols.index(target.symbol),
                )
            )
            target_by_symbol = self._validated_targets(targets)
            decision_timestamp = timestamp + Timeframe.FIVE_MINUTES.duration
            changed = tuple(
                symbol
                for symbol in self.symbols
                if target_by_symbol[symbol].weight != desired_state[symbol]
            )
            decisions.append(
                Exposed002Decision(
                    decision_timestamp,
                    targets,
                    changed,
                    session_index >= cutoff_index,
                )
            )

            for symbol in changed:
                target = target_by_symbol[symbol]
                previous = desired_state[symbol]
                desired_state[symbol] = target.weight
                sequence += 1
                if session_index >= cutoff_index:
                    transitions.append(
                        Exposed002Transition(
                            sequence,
                            symbol,
                            decision_timestamp,
                            None,
                            previous,
                            target.weight,
                            "rejected",
                            "strategy",
                            "session-close-cutoff",
                        )
                    )
                    continue
                pending.append(
                    _PendingTransition(
                        sequence,
                        symbol,
                        decision_timestamp,
                        session_timestamps[session_index + self.scenario.execution_delay_bars],
                        previous,
                        target.weight,
                        "strategy",
                        target.reason,
                    )
                )

            if session_index == cutoff_index:
                for symbol in self.symbols:
                    projected_state = next(
                        (item.to_weight for item in reversed(pending) if item.symbol == symbol),
                        executed_state[symbol],
                    )
                    if projected_state == _ZERO:
                        continue
                    sequence += 1
                    pending.append(
                        _PendingTransition(
                            sequence,
                            symbol,
                            decision_timestamp,
                            final_timestamp,
                            projected_state,
                            _ZERO,
                            "mandatory-session-flatten",
                            "mandatory-session-flatten",
                        )
                    )

            if timestamp == final_timestamp:
                if pending or open_fills or any(positions.values()) or any(executed_state.values()):
                    raise BacktestError("Fed Policy Absorption 001 session ended with exposure")
                daily = self._daily_fees(session, tuple(session_regulatory_fills))
                cash = (
                    joint_entry_equity
                    * (
                        _ONE
                        + joint_spread_adjusted_return
                        - daily.charges.total / joint_entry_equity
                    )
                    if self.exact_joint_fills
                    and joint_entry_equity is not None
                    and joint_spread_adjusted_return is not None
                    else cash - daily.charges.total
                )
                fees.append(daily)
            curve.append(_equity_point(decision_timestamp, cash, positions, marks, self.symbols))

        partial = Exposed002ReplayResult(
            strategy.strategy_id,
            strategy.version,
            self.scenario.scenario_id,
            self.initial_cash,
            tuple(decisions),
            tuple(transitions),
            tuple(fills),
            tuple(round_trips),
            tuple(fees),
            tuple(curve),
            "",
        )
        return Exposed002ReplayResult(
            partial.strategy_id,
            partial.strategy_version,
            partial.scenario_id,
            partial.initial_cash,
            partial.decisions,
            partial.transitions,
            partial.fills,
            partial.round_trips,
            partial.fee_ledger,
            partial.equity_curve,
            fingerprint(partial),
        )

    def _fill(
        self,
        item: _PendingTransition,
        market_price: Decimal,
        cash: Decimal,
        positions: dict[Symbol, Decimal],
        marks: Mapping[Symbol, Decimal],
        entries: dict[Symbol, int],
        open_fills: Mapping[Symbol, Exposed002Fill],
        *,
        entry_equity: Decimal | None = None,
    ) -> tuple[Decimal, Exposed002Fill]:
        current = positions[item.symbol]
        equity = (
            entry_equity
            if entry_equity is not None
            else cash
            + sum(
                (positions[symbol] * marks[symbol] for symbol in self.symbols),
                _ZERO,
            )
        )
        if item.to_weight == _HALF and current == _ZERO:
            if entries[item.symbol] >= 1 or item.symbol in open_fills:
                raise BacktestError(
                    "Fed Policy Absorption 001 permits one entry per symbol and session"
                )
            fill_price = self.scenario.fill_price(item.symbol, market_price, _ONE)
            quantity = (
                equity * _HALF / fill_price
                if entry_equity is not None
                else min(equity * _HALF / fill_price, cash / fill_price)
            )
            entries[item.symbol] += 1
            trade_id = f"{_account_day(item.eligible_fill_timestamp)}:{item.symbol.value}:1"
        elif item.to_weight == _ZERO and current > _ZERO:
            fill_price = self.scenario.fill_price(item.symbol, market_price, -_ONE)
            quantity = -current
            entry = open_fills.get(item.symbol)
            if entry is None:
                raise BacktestError("Fed Policy Absorption 001 exit lacks an open trade")
            trade_id = entry.trade_id
        else:
            raise BacktestError("Fed Policy Absorption 001 transition is not binary 0/0.5")
        if not quantity:
            raise BacktestError("Fed Policy Absorption 001 transition has zero quantity")
        notional = (
            entry_equity * _HALF
            if entry_equity is not None and quantity > _ZERO
            else abs(quantity * fill_price)
        )
        cash = cash - notional if quantity > 0 else cash + notional
        positions[item.symbol] = current + quantity
        return cash, Exposed002Fill(
            item.sequence,
            trade_id,
            item.symbol,
            item.decision_timestamp,
            item.eligible_fill_timestamp,
            quantity,
            market_price,
            fill_price,
            notional,
            abs(fill_price - market_price) * abs(quantity),
        )

    def _daily_fees(
        self, account_day: date, regulatory_fills: tuple[RegulatoryFill, ...]
    ) -> Exposed002DailyFees:
        if self.scenario.regulatory_fee_model_id is None:
            charges = DailyRegulatoryCharges(_ZERO, _ZERO, _ZERO)
        elif self.scenario.regulatory_fee_model_id == self.regulatory_fees.model_id:
            charges = self.regulatory_fees.charges_for_account_day(account_day, regulatory_fills)
        else:
            raise BacktestError("Fed Policy Absorption 001 regulatory fee model differs")
        by_symbol_notional = {
            symbol: sum(
                (
                    fill.gross_notional
                    for fill in regulatory_fills
                    if fill.trade_id.split(":")[1] == symbol.value
                ),
                _ZERO,
            )
            for symbol in self.symbols
        }
        total_notional = sum(by_symbol_notional.values(), _ZERO)
        allocations: list[tuple[Symbol, Decimal]] = []
        remaining = charges.total
        for index, symbol in enumerate(self.symbols):
            allocated = (
                remaining
                if index == len(self.symbols) - 1
                else charges.total * by_symbol_notional[symbol] / total_notional
                if total_notional
                else _ZERO
            )
            allocations.append((symbol, allocated))
            remaining -= allocated
        return Exposed002DailyFees(
            account_day.isoformat(),
            charges,
            tuple(allocations),
            fingerprint(regulatory_fills),
        )

    def _validated_targets(self, targets: Sequence[TargetPosition]) -> dict[Symbol, TargetPosition]:
        if len(targets) != 2 or {target.symbol for target in targets} != set(self.symbols):
            raise BacktestError("Fed Policy Absorption 001 targets must cover QQQ and SPY exactly")
        if any(target.weight not in {_ZERO, _HALF} for target in targets):
            raise BacktestError("Fed Policy Absorption 001 targets must be 0 or 0.5")
        if sum((target.weight for target in targets), _ZERO) > _ONE:
            raise BacktestError("Fed Policy Absorption 001 target exposure exceeds one")
        return {target.symbol: target for target in targets}

    def _validated_slices(
        self, bars: tuple[OHLCVBar, ...]
    ) -> tuple[
        tuple[tuple[datetime, tuple[OHLCVBar, ...]], ...],
        dict[date, list[datetime]],
    ]:
        if not bars:
            raise BacktestError("Fed Policy Absorption 001 replay requires bars")
        seen: set[tuple[Symbol, datetime]] = set()
        for bar in bars:
            key = (bar.symbol, bar.timestamp)
            if key in seen:
                raise BacktestError(f"duplicate bar: {bar.symbol}@{bar.timestamp}")
            seen.add(key)
        slices = tuple(
            (timestamp, tuple(items))
            for timestamp, items in groupby(bars, key=lambda bar: bar.timestamp)
        )
        if any({bar.symbol for bar in items} != set(self.symbols) for _, items in slices):
            raise BacktestError("Fed Policy Absorption 001 requires complete QQQ/SPY slices")
        expected = set(
            expected_bar_timestamps(
                bars[0].timestamp,
                bars[-1].timestamp,
                Timeframe.FIVE_MINUTES,
            )
        )
        actual = {timestamp for timestamp, _items in slices}
        if actual != expected:
            raise BacktestError("Fed Policy Absorption 001 requires complete XNYS sessions")
        timestamps_by_session: dict[date, list[datetime]] = {}
        for timestamp, _items in slices:
            timestamps_by_session.setdefault(_account_day(timestamp), []).append(timestamp)
        if any(
            len(timestamps) <= self.scenario.execution_delay_bars
            for timestamps in timestamps_by_session.values()
        ):
            raise BacktestError("Fed Policy Absorption 001 delay leaves no safe session decision")
        return slices, timestamps_by_session


def _account_day(timestamp: datetime) -> date:
    return timestamp.astimezone(_NEW_YORK).date()


def _equity_point(
    timestamp: datetime,
    cash: Decimal,
    positions: Mapping[Symbol, Decimal],
    marks: Mapping[Symbol, Decimal],
    symbols: tuple[Symbol, Symbol] = _SYMBOLS,
) -> EquityPoint:
    equity = cash + sum(
        (positions[symbol] * marks[symbol] for symbol in symbols),
        _ZERO,
    )
    return EquityPoint(
        timestamp,
        equity,
        cash,
        tuple((symbol, positions[symbol]) for symbol in symbols),
    )
