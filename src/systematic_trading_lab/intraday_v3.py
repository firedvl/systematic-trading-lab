"""Development-only Campaign V3 state-transition replay and diagnostics."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from decimal import Decimal
from itertools import groupby
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, cast
from zoneinfo import ZoneInfo

from .backtesting import (
    BacktestEngine,
    BacktestError,
    BacktestMetrics,
    BacktestResult,
    CostModel,
    EquityPoint,
    IntradaySessionPolicy,
    Order,
    OrderEvent,
    PortfolioStrategy,
    Trade,
)
from .calendar import expected_bar_timestamps
from .domain import OHLCVBar, Symbol, Timeframe
from .experiments import ExperimentSplit
from .fingerprints import canonical_json, canonicalize, fingerprint
from .strategies import TargetPosition

V3_CAMPAIGN_ID = "intraday-research-v3"
V3_CAMPAIGN_DRAFT_SCHEMA = "intraday-research-campaign-v3-draft-v1"
V3_EXPERIMENT_SCHEMA = "intraday-experiment-v2"
V3_REPORT_SCHEMA = "intraday-backtest-report-v2"
V3_EXECUTION_MODEL = "state-transition-delayed-fifo-v1"
V3_EARLIEST_FILL_SEMANTICS = "completed-bar-nth-later-open-v1"
V3_QUEUE_POLICY = "fifo-no-supersession-session-close-override-v1"
V3_SESSION_POLICY = "XNYS-regular-session-state-transition-flat-v2"
V3_PERIODIC_REBALANCE_POLICY = "none-v1"
V3_DIAGNOSTIC_POLICY = "paired-exact-zero-cost-counterfactual-v1"
V3_AUTHORITY_POLICY = "research-diagnostic-no-authority-v1"
V3_ZERO_COST_MODEL = "zero-cost-counterfactual-v1"
V3_INITIAL_CASH = Decimal("100000")

V3_MA_STRATEGY_ID = "intraday-event-driven-ma-trend"
V3_MOMENTUM_STRATEGY_ID = "intraday-30-minute-momentum"
V3_OPENING_RANGE_STRATEGY_ID = "intraday-30-minute-opening-range-breakout"

_NEW_YORK = ZoneInfo("America/New_York")
_V3_SYMBOL_VALUES = frozenset({"SPY", "QQQ"})
_ZERO = Decimal("0")
_SYMBOL_WEIGHT = Decimal("0.5")
_AUTHORITY_FLAGS = {
    "research_qualification": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}
_STRATEGY_CONTRACTS: Mapping[str, tuple[str, Mapping[str, object]]] = {
    V3_MA_STRATEGY_ID: ("intraday-trend", {"window": 12}),
    V3_MOMENTUM_STRATEGY_ID: ("intraday-directional-momentum", {"lookback": 6}),
    V3_OPENING_RANGE_STRATEGY_ID: (
        "intraday-opening-range-breakout",
        {"opening_range_bars": 6},
    ),
}


class V3PortfolioStrategy(Protocol):
    @property
    def strategy_id(self) -> str: ...

    @property
    def version(self) -> str: ...

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]: ...


def _validated_symbols(symbols: Sequence[Symbol]) -> tuple[Symbol, ...]:
    canonical = tuple(sorted(symbols, key=lambda symbol: symbol.value))
    if len(canonical) != 2 or {symbol.value for symbol in canonical} != _V3_SYMBOL_VALUES:
        raise ValueError("V3 intraday strategies require exactly SPY and QQQ")
    return canonical


def _check_strategy_slice(
    symbols: tuple[Symbol, ...],
    bars: Sequence[OHLCVBar],
    history: Mapping[Symbol, Sequence[OHLCVBar]],
) -> None:
    current = {bar.symbol: bar for bar in bars}
    if set(current) != set(symbols) or set(history) != set(symbols):
        raise ValueError("V3 intraday strategy universe differs")
    if len({bar.timestamp for bar in bars}) != 1:
        raise ValueError("V3 intraday strategy requires one complete timestamp slice")
    if len({len(history[symbol]) for symbol in symbols}) != 1:
        raise ValueError("V3 intraday strategy history lengths differ")
    if any(not history[symbol] or history[symbol][-1] != current[symbol] for symbol in symbols):
        raise ValueError("V3 intraday strategy history does not end at the current slice")


def _targets(
    symbols: tuple[Symbol, ...], weights: Mapping[Symbol, Decimal], reason: str
) -> tuple[TargetPosition, ...]:
    return tuple(TargetPosition(symbol, weights[symbol], reason) for symbol in symbols)


@dataclass(frozen=True)
class EventDrivenMovingAverageTrendStrategy:
    """The V2 12-bar signal with V3 state-transition execution."""

    symbols: tuple[Symbol, ...]
    strategy_id: str = V3_MA_STRATEGY_ID
    version: str = "1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", _validated_symbols(self.symbols))

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        _check_strategy_slice(self.symbols, bars, history)
        if len(history[self.symbols[0]]) < 12:
            return _targets(self.symbols, dict.fromkeys(self.symbols, _ZERO), "ma-warmup")
        current = {bar.symbol: bar for bar in bars}
        weights = {
            symbol: (
                _SYMBOL_WEIGHT
                if current[symbol].close
                > sum((bar.close for bar in history[symbol][-12:]), _ZERO) / Decimal("12")
                else _ZERO
            )
            for symbol in self.symbols
        }
        return _targets(self.symbols, weights, "close-above-12-bar-moving-average")


@dataclass(frozen=True)
class ThirtyMinuteMomentumStrategy:
    """Long when the completed close exceeds the completed close six bars earlier."""

    symbols: tuple[Symbol, ...]
    strategy_id: str = V3_MOMENTUM_STRATEGY_ID
    version: str = "1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", _validated_symbols(self.symbols))

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        _check_strategy_slice(self.symbols, bars, history)
        if len(history[self.symbols[0]]) <= 6:
            return _targets(self.symbols, dict.fromkeys(self.symbols, _ZERO), "momentum-warmup")
        current = {bar.symbol: bar for bar in bars}
        weights = {
            symbol: (_SYMBOL_WEIGHT if current[symbol].close > history[symbol][-7].close else _ZERO)
            for symbol in self.symbols
        }
        return _targets(self.symbols, weights, "positive-30-minute-completed-bar-momentum")


@dataclass(frozen=True)
class ThirtyMinuteOpeningRangeBreakoutStrategy:
    """Enter once after a completed close breaks the first six bars' high."""

    symbols: tuple[Symbol, ...]
    strategy_id: str = V3_OPENING_RANGE_STRATEGY_ID
    version: str = "1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", _validated_symbols(self.symbols))

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        _check_strategy_slice(self.symbols, bars, history)
        current_session = _exchange_session(bars[0])
        weights: dict[Symbol, Decimal] = {}
        for symbol in self.symbols:
            session_history = tuple(
                bar for bar in history[symbol] if _exchange_session(bar) == current_session
            )
            if len(session_history) <= 6:
                weights[symbol] = _ZERO
                continue
            opening_range_high = max(bar.high for bar in session_history[:6])
            breakout_seen = any(bar.close > opening_range_high for bar in session_history[6:])
            weights[symbol] = _SYMBOL_WEIGHT if breakout_seen else _ZERO
        return _targets(self.symbols, weights, "completed-close-above-30-minute-opening-range")


def v3_strategy(
    strategy_id: str,
    symbols: Sequence[Symbol],
    parameters: Mapping[str, object],
) -> V3PortfolioStrategy:
    """Build one fixed V3 strategy and reject parameter drift."""

    contract = _STRATEGY_CONTRACTS.get(strategy_id)
    if contract is None:
        raise ValueError(f"unknown V3 intraday strategy: {strategy_id}")
    expected = contract[1]
    if set(parameters) != set(expected) or any(
        type(parameters[name]) is not type(value) or parameters[name] != value
        for name, value in expected.items()
    ):
        raise ValueError(f"V3 parameters differ for {strategy_id}")
    canonical_symbols = _validated_symbols(symbols)
    if strategy_id == V3_MA_STRATEGY_ID:
        return EventDrivenMovingAverageTrendStrategy(canonical_symbols)
    if strategy_id == V3_MOMENTUM_STRATEGY_ID:
        return ThirtyMinuteMomentumStrategy(canonical_symbols)
    return ThirtyMinuteOpeningRangeBreakoutStrategy(canonical_symbols)


@dataclass(frozen=True)
class IntradayV3ExperimentSpec:
    """Fingerprintable research-only V3 replay provenance."""

    experiment_id: str
    campaign_id: str
    search_budget: int
    candidate_ordinal: int
    strategy_id: str
    strategy_version: str
    strategy_family: str
    code_commit: str
    dataset_id: str
    dataset_fingerprint: str
    universe_id: str
    universe_fingerprint: str
    parameters: Mapping[str, object]
    timeframe: str
    session_policy_version: str
    bar_timestamp_semantics_version: str
    session_return_policy_version: str
    benchmark_policy_version: str
    cost_model_version: str
    slippage_bps: Decimal
    commission_bps: Decimal
    execution_model_version: str
    earliest_fill_semantics: str
    decision_queue_policy_version: str
    execution_delay_bars: int
    periodic_rebalance_policy_version: str
    diagnostic_policy_version: str
    authority_policy_version: str
    split: ExperimentSplit
    start_timestamp: datetime
    end_timestamp: datetime
    random_seed: int
    creation_reason: str
    parent_candidate: str | None = None
    schema_version: str = V3_EXPERIMENT_SCHEMA

    def __post_init__(self) -> None:
        identifiers = (
            self.experiment_id,
            self.campaign_id,
            self.strategy_id,
            self.strategy_version,
            self.strategy_family,
            self.code_commit,
            self.dataset_id,
            self.dataset_fingerprint,
            self.universe_id,
            self.universe_fingerprint,
            self.cost_model_version,
            self.creation_reason,
        )
        if any(not value for value in identifiers):
            raise ValueError("V3 experiment provenance fields are required")
        if self.schema_version != V3_EXPERIMENT_SCHEMA:
            raise ValueError("unsupported V3 intraday experiment schema")
        if self.campaign_id != V3_CAMPAIGN_ID:
            raise ValueError("V3 experiment campaign identity differs")
        if (
            type(self.search_budget) is not int
            or type(self.candidate_ordinal) is not int
            or self.search_budget < 1
            or not 1 <= self.candidate_ordinal <= self.search_budget
        ):
            raise ValueError("V3 candidate ordinal must fit its positive search budget")
        contract = _STRATEGY_CONTRACTS.get(self.strategy_id)
        if contract is None or self.strategy_version != "1" or self.strategy_family != contract[0]:
            raise ValueError("V3 strategy identity differs")
        v3_strategy(self.strategy_id, (Symbol("SPY"), Symbol("QQQ")), self.parameters)
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        expected_versions = {
            "timeframe": "5m",
            "session_policy_version": V3_SESSION_POLICY,
            "bar_timestamp_semantics_version": "bar-open-utc-v1",
            "session_return_policy_version": "XNYS-session-close-equity-v1",
            "benchmark_policy_version": "cash-and-continuous-underlying-v1",
            "execution_model_version": V3_EXECUTION_MODEL,
            "earliest_fill_semantics": V3_EARLIEST_FILL_SEMANTICS,
            "decision_queue_policy_version": V3_QUEUE_POLICY,
            "periodic_rebalance_policy_version": V3_PERIODIC_REBALANCE_POLICY,
            "diagnostic_policy_version": V3_DIAGNOSTIC_POLICY,
            "authority_policy_version": V3_AUTHORITY_POLICY,
        }
        if any(getattr(self, field) != value for field, value in expected_versions.items()):
            raise ValueError("V3 replay contract differs")
        if type(self.execution_delay_bars) is not int or self.execution_delay_bars < 1:
            raise ValueError("V3 execution delay must be positive")
        if any(
            not isinstance(value, Decimal) or not value.is_finite() or value < 0
            for value in (self.slippage_bps, self.commission_bps)
        ):
            raise ValueError("V3 costs must be finite and non-negative")
        if self.split not in {ExperimentSplit.TRAINING, ExperimentSplit.VALIDATION}:
            raise ValueError("V3 foundation authorizes only training and validation")
        if any(
            value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
            for value in (self.start_timestamp, self.end_timestamp)
        ):
            raise ValueError("V3 experiment timestamps must be UTC-aware")
        if self.start_timestamp > self.end_timestamp:
            raise ValueError("V3 experiment range is reversed")
        if type(self.random_seed) is not int or self.random_seed < 0:
            raise ValueError("V3 random seed must be a non-negative integer")

    @property
    def configuration_fingerprint(self) -> str:
        return fingerprint(self)

    @property
    def authorities(self) -> Mapping[str, bool]:
        return MappingProxyType(dict(_AUTHORITY_FLAGS))


@dataclass(frozen=True)
class DesiredStateDecision:
    timestamp: datetime
    strategy_id: str
    strategy_version: str
    desired_targets: tuple[TargetPosition, ...]
    changed_symbols: tuple[Symbol, ...]
    session_close_cutoff: bool


@dataclass(frozen=True)
class StateTransition:
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
class _StrategyIdentity:
    strategy_id: str
    version: str

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        raise AssertionError("accounting identity does not make strategy decisions")


@dataclass(frozen=True)
class V3BacktestResult:
    strategy_id: str
    strategy_version: str
    timeframe: Timeframe
    execution_delay_bars: int
    cost_model: CostModel
    accounting: BacktestResult
    decisions: tuple[DesiredStateDecision, ...]
    transitions: tuple[StateTransition, ...]
    desired_state_change_count: int
    executed_state_transition_count: int
    periodic_rebalance_count: int
    artifact_fingerprint: str

    @property
    def initial_cash(self) -> Decimal:
        return self.accounting.initial_cash

    @property
    def equity_curve(self) -> tuple[EquityPoint, ...]:
        return self.accounting.equity_curve

    @property
    def trades(self) -> tuple[Trade, ...]:
        return self.accounting.trades

    @property
    def metrics(self) -> BacktestMetrics:
        return self.accounting.metrics


class StateTransitionBacktestEngine:
    """Apply every changed desired state after N bars without implicit rebalancing."""

    def __init__(
        self,
        initial_cash: Decimal,
        cost_model: CostModel,
        execution_delay_bars: int,
        timeframe: Timeframe = Timeframe.FIVE_MINUTES,
    ) -> None:
        if timeframe is not Timeframe.FIVE_MINUTES:
            raise ValueError("V3 state-transition replay requires 5m bars")
        if execution_delay_bars < 1:
            raise ValueError("V3 execution delay must be positive")
        self.initial_cash = initial_cash
        self.cost_model = cost_model
        self.execution_delay_bars = execution_delay_bars
        self.timeframe = timeframe
        self._accounting = BacktestEngine(
            initial_cash,
            cost_model,
            execution_delay_bars,
            timeframe,
            IntradaySessionPolicy.DAY_TRADING_FLAT,
        )

    def run(self, bars: Sequence[OHLCVBar], strategy: V3PortfolioStrategy) -> V3BacktestResult:
        ordered = tuple(sorted(bars, key=lambda bar: (bar.timestamp, bar.symbol.value)))
        self._accounting._check_bars(ordered)
        self._accounting._check_day_trading_sessions(ordered)
        symbols = _validated_symbols(tuple({bar.symbol for bar in ordered}))
        slices = tuple(
            (timestamp, tuple(group))
            for timestamp, group in groupby(ordered, key=lambda bar: bar.timestamp)
        )
        if any(
            {bar.symbol for bar in session_slice} != set(symbols) for _, session_slice in slices
        ):
            raise BacktestError("V3 portfolio replay requires complete SPY/QQQ slices")
        timestamps_by_session: dict[date, list[datetime]] = {}
        for timestamp, _ in slices:
            timestamps_by_session.setdefault(_exchange_session_timestamp(timestamp), []).append(
                timestamp
            )
        if any(
            len(timestamps) <= self.execution_delay_bars
            for timestamps in timestamps_by_session.values()
        ):
            raise BacktestError("V3 execution delay leaves no safe session decision")
        index_by_timestamp = {
            timestamp: index
            for timestamps in timestamps_by_session.values()
            for index, timestamp in enumerate(timestamps)
        }

        cash = self.initial_cash
        positions: dict[Symbol, Decimal] = {}
        marks: dict[Symbol, Decimal] = {}
        history: dict[Symbol, list[OHLCVBar]] = {symbol: [] for symbol in symbols}
        desired_state: dict[Symbol, Decimal] = dict.fromkeys(symbols, _ZERO)
        executed_state: dict[Symbol, Decimal] = dict.fromkeys(symbols, _ZERO)
        pending: list[_PendingTransition] = []
        decisions: list[DesiredStateDecision] = []
        transitions: list[StateTransition] = []
        orders: list[OrderEvent] = []
        trades: list[Trade] = []
        curve: list[EquityPoint] = []
        desired_change_count = 0
        sequence = 0
        active_session: date | None = None

        for timestamp, session_slice in slices:
            session_date = _exchange_session_timestamp(timestamp)
            session_timestamps = timestamps_by_session[session_date]
            session_index = index_by_timestamp[timestamp]
            cutoff_index = len(session_timestamps) - self.execution_delay_bars - 1
            final_timestamp = session_timestamps[-1]
            if session_date != active_session:
                if pending or any(positions.get(symbol, _ZERO) != 0 for symbol in symbols):
                    raise BacktestError("V3 session began with exposure or queued transitions")
                active_session = session_date
                desired_state = dict.fromkeys(symbols, _ZERO)
                executed_state = dict.fromkeys(symbols, _ZERO)

            for bar in session_slice:
                marks[bar.symbol] = bar.open
            due = [item for item in pending if item.eligible_fill_timestamp == timestamp]
            if any(item.eligible_fill_timestamp < timestamp for item in pending):
                raise BacktestError("V3 queued transition missed its eligible fill")
            pending = [item for item in pending if item.eligible_fill_timestamp != timestamp]
            due.sort(key=lambda item: item.sequence)
            for item in due:
                current_state = executed_state[item.symbol]
                if item.to_weight == current_state:
                    transitions.append(
                        StateTransition(
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
                order = Order(
                    item.symbol,
                    item.decision_timestamp,
                    item.decision_timestamp,
                    item.eligible_fill_timestamp,
                    TargetPosition(item.symbol, item.to_weight, item.reason),
                )
                cash, event, trade = self._accounting._execute(
                    order,
                    next(bar.open for bar in session_slice if bar.symbol == item.symbol),
                    cash,
                    positions,
                    marks,
                )
                if event.status != "filled" or trade is None:
                    raise BacktestError("V3 state transition did not produce its required fill")
                orders.append(event)
                trades.append(trade)
                executed_state[item.symbol] = item.to_weight
                transitions.append(
                    StateTransition(
                        item.sequence,
                        item.symbol,
                        item.decision_timestamp,
                        item.eligible_fill_timestamp,
                        item.from_weight,
                        item.to_weight,
                        "filled",
                        item.source,
                        item.reason,
                        trade.quantity,
                    )
                )

            for bar in session_slice:
                marks[bar.symbol] = bar.close
                history[bar.symbol].append(bar)
            frozen_history = MappingProxyType(
                {symbol: tuple(history[symbol]) for symbol in symbols}
            )
            raw_targets = tuple(
                sorted(
                    strategy.on_session(session_slice, frozen_history),
                    key=lambda target: target.symbol.value,
                )
            )
            target_by_symbol = self._validate_targets(raw_targets, symbols)
            decision_timestamp = timestamp + self.timeframe.duration
            changed = tuple(
                symbol
                for symbol in symbols
                if target_by_symbol[symbol].weight != desired_state[symbol]
            )
            desired_change_count += len(changed)
            decisions.append(
                DesiredStateDecision(
                    decision_timestamp,
                    strategy.strategy_id,
                    strategy.version,
                    raw_targets,
                    changed,
                    session_index >= cutoff_index,
                )
            )

            if session_index == cutoff_index:
                for item in pending:
                    transitions.append(
                        StateTransition(
                            item.sequence,
                            item.symbol,
                            item.decision_timestamp,
                            item.eligible_fill_timestamp,
                            item.from_weight,
                            item.to_weight,
                            "canceled",
                            item.source,
                            "session-close-override",
                        )
                    )
                pending.clear()

            for symbol in changed:
                target = target_by_symbol[symbol]
                previous = desired_state[symbol]
                desired_state[symbol] = target.weight
                sequence += 1
                if session_index >= cutoff_index:
                    transitions.append(
                        StateTransition(
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
                fill_timestamp = session_timestamps[session_index + self.execution_delay_bars]
                if fill_timestamp < decision_timestamp:
                    raise BacktestError("V3 delayed fill precedes completed-bar observability")
                pending.append(
                    _PendingTransition(
                        sequence,
                        symbol,
                        decision_timestamp,
                        fill_timestamp,
                        previous,
                        target.weight,
                        "strategy",
                        target.reason,
                    )
                )

            if session_index == cutoff_index:
                for symbol in symbols:
                    if executed_state[symbol] == 0:
                        continue
                    sequence += 1
                    pending.append(
                        _PendingTransition(
                            sequence,
                            symbol,
                            decision_timestamp,
                            final_timestamp,
                            executed_state[symbol],
                            _ZERO,
                            "mandatory-session-flatten",
                            "mandatory-session-flatten",
                        )
                    )

            curve.append(self._accounting._equity_point(decision_timestamp, cash, positions, marks))
            if timestamp == final_timestamp and (
                pending
                or any(positions.get(symbol, _ZERO) != 0 for symbol in symbols)
                or any(executed_state[symbol] != 0 for symbol in symbols)
            ):
                raise BacktestError("V3 day-trading session ended with exposure")

        identity = _StrategyIdentity(strategy.strategy_id, strategy.version)
        accounting = self._accounting._result(
            cast(PortfolioStrategy, identity),
            curve,
            (),
            orders,
            trades,
            ordered,
            positions,
            marks,
        )
        result = V3BacktestResult(
            strategy.strategy_id,
            strategy.version,
            self.timeframe,
            self.execution_delay_bars,
            self.cost_model,
            accounting,
            tuple(decisions),
            tuple(transitions),
            desired_change_count,
            sum(item.status == "filled" for item in transitions),
            0,
            "",
        )
        return V3BacktestResult(
            result.strategy_id,
            result.strategy_version,
            result.timeframe,
            result.execution_delay_bars,
            result.cost_model,
            result.accounting,
            result.decisions,
            result.transitions,
            result.desired_state_change_count,
            result.executed_state_transition_count,
            result.periodic_rebalance_count,
            fingerprint(result),
        )

    @staticmethod
    def _validate_targets(
        targets: Sequence[TargetPosition], symbols: tuple[Symbol, ...]
    ) -> dict[Symbol, TargetPosition]:
        if len(targets) != len(symbols) or {target.symbol for target in targets} != set(symbols):
            raise BacktestError("V3 desired state must cover SPY and QQQ exactly once")
        if any(target.weight not in {_ZERO, _SYMBOL_WEIGHT} for target in targets):
            raise BacktestError("V3 desired state must be binary cash or 0.5 weight")
        if sum((target.weight for target in targets), _ZERO) > 1:
            raise BacktestError("V3 desired state exceeds unlevered portfolio weight")
        return {target.symbol: target for target in targets}


@dataclass(frozen=True)
class V3DiagnosticReplay:
    realistic: V3BacktestResult
    zero_cost: V3BacktestResult
    semantic_trace_fingerprint: str
    configuration_provenance_fingerprint: str
    input_bars_fingerprint: str
    artifact_fingerprint: str


def run_v3_diagnostic(
    spec: IntradayV3ExperimentSpec,
    bars: Sequence[OHLCVBar],
    initial_cash: Decimal = V3_INITIAL_CASH,
) -> V3DiagnosticReplay:
    """Run paired realistic and exact zero-cost replays without registry authority."""

    if initial_cash != V3_INITIAL_CASH:
        raise ValueError("V3 diagnostic initial cash differs")
    input_fingerprint = _validate_v3_input_bars(spec, bars)
    symbols = tuple({bar.symbol for bar in bars})
    realistic = StateTransitionBacktestEngine(
        initial_cash,
        CostModel(spec.cost_model_version, spec.slippage_bps, spec.commission_bps),
        spec.execution_delay_bars,
        Timeframe(spec.timeframe),
    ).run(bars, v3_strategy(spec.strategy_id, symbols, spec.parameters))
    zero_cost = StateTransitionBacktestEngine(
        initial_cash,
        CostModel(V3_ZERO_COST_MODEL, _ZERO, _ZERO),
        spec.execution_delay_bars,
        Timeframe(spec.timeframe),
    ).run(bars, v3_strategy(spec.strategy_id, symbols, spec.parameters))
    realistic_trace = _semantic_trace(realistic)
    zero_cost_trace = _semantic_trace(zero_cost)
    if realistic_trace != zero_cost_trace:
        raise BacktestError("V3 zero-cost replay changed decision or execution semantics")
    trace_fingerprint = fingerprint(realistic_trace)
    partial = V3DiagnosticReplay(
        realistic,
        zero_cost,
        trace_fingerprint,
        spec.configuration_fingerprint,
        input_fingerprint,
        "",
    )
    return replace(partial, artifact_fingerprint=fingerprint(partial))


def _semantic_trace(result: V3BacktestResult) -> object:
    return canonicalize(
        {
            "decisions": result.decisions,
            "transitions": tuple(
                {
                    "sequence": item.sequence,
                    "symbol": item.symbol,
                    "decision_timestamp": item.decision_timestamp,
                    "eligible_fill_timestamp": item.eligible_fill_timestamp,
                    "from_weight": item.from_weight,
                    "to_weight": item.to_weight,
                    "status": item.status,
                    "source": item.source,
                    "reason": item.reason,
                }
                for item in result.transitions
            ),
        }
    )


def build_v3_diagnostic_report(
    spec: IntradayV3ExperimentSpec,
    replay: V3DiagnosticReplay,
    bars: Sequence[OHLCVBar],
) -> dict[str, object]:
    """Build deterministic diagnostic evidence; only realistic costs remain gate-eligible later."""

    input_fingerprint = _validate_v3_input_bars(spec, bars)
    realistic = replay.realistic
    zero_cost = replay.zero_cost
    if (
        realistic.strategy_id != spec.strategy_id
        or realistic.strategy_version != spec.strategy_version
        or realistic.execution_delay_bars != spec.execution_delay_bars
        or realistic.timeframe.value != spec.timeframe
        or realistic.cost_model.version != spec.cost_model_version
        or realistic.cost_model.slippage_bps != spec.slippage_bps
        or realistic.cost_model.commission_bps != spec.commission_bps
        or zero_cost.cost_model.version != V3_ZERO_COST_MODEL
        or zero_cost.cost_model.slippage_bps != 0
        or zero_cost.cost_model.commission_bps != 0
        or zero_cost.strategy_id != spec.strategy_id
        or zero_cost.strategy_version != spec.strategy_version
        or zero_cost.execution_delay_bars != spec.execution_delay_bars
        or zero_cost.timeframe.value != spec.timeframe
        or realistic.initial_cash != zero_cost.initial_cash
        or realistic.accounting.strategy_id != realistic.strategy_id
        or realistic.accounting.strategy_version != realistic.strategy_version
        or zero_cost.accounting.strategy_id != zero_cost.strategy_id
        or zero_cost.accounting.strategy_version != zero_cost.strategy_version
        or realistic.initial_cash != V3_INITIAL_CASH
    ):
        raise ValueError("V3 diagnostic replay differs from its experiment provenance")
    realistic_trace = _semantic_trace(realistic)
    zero_cost_trace = _semantic_trace(zero_cost)
    trace_fingerprint = fingerprint(realistic_trace)
    if realistic_trace != zero_cost_trace:
        raise ValueError("V3 diagnostic semantic traces differ")
    if (
        replay.configuration_provenance_fingerprint != spec.configuration_fingerprint
        or replay.input_bars_fingerprint != input_fingerprint
        or replay.semantic_trace_fingerprint != trace_fingerprint
        or realistic.artifact_fingerprint
        != fingerprint(replace(realistic, artifact_fingerprint=""))
        or zero_cost.artifact_fingerprint
        != fingerprint(replace(zero_cost, artifact_fingerprint=""))
        or realistic.accounting.artifact_fingerprint
        != fingerprint(replace(realistic.accounting, artifact_fingerprint=""))
        or zero_cost.accounting.artifact_fingerprint
        != fingerprint(replace(zero_cost.accounting, artifact_fingerprint=""))
        or replay.artifact_fingerprint != fingerprint(replace(replay, artifact_fingerprint=""))
    ):
        raise ValueError("V3 diagnostic artifact fingerprint differs")
    sessions = tuple(sorted({_exchange_session(bar) for bar in bars}))
    session_count = len(sessions)
    realistic_cost = sum((trade.commission + trade.slippage for trade in realistic.trades), _ZERO)
    zero_cost_paid = sum((trade.commission + trade.slippage for trade in zero_cost.trades), _ZERO)
    completed_round_trips = sum(trade.quantity < 0 for trade in realistic.trades)
    overnight_count = _overnight_position_count(realistic)
    valid_fill_timestamps = {bar.timestamp for bar in bars}
    outside_session_count = sum(
        trade.fill_timestamp not in valid_fill_timestamps
        or not time(9, 30)
        <= trade.fill_timestamp.astimezone(_NEW_YORK).time().replace(tzinfo=None)
        < time(16)
        for trade in realistic.trades
    )
    round_trips, pnl_by_symbol = _v3_round_trips(realistic)
    session_profits = _v3_session_profits(realistic)
    traded_sessions = {
        trade.fill_timestamp.astimezone(_NEW_YORK).date() for trade in realistic.trades
    }
    positive_trades = sorted((profit for profit in round_trips if profit > 0), reverse=True)
    total_positive_trades = sum(positive_trades, _ZERO)
    positive_symbol_profits = tuple(profit for profit in pnl_by_symbol.values() if profit > 0)
    total_positive_symbol_profit = sum(positive_symbol_profits, _ZERO)
    realistic_metrics: dict[str, object] = {
        "total_return": realistic.metrics.total_return,
        "transaction_cost_drag": zero_cost.metrics.total_return - realistic.metrics.total_return,
        "cost_paid_total": realistic_cost,
        "turnover": realistic.metrics.turnover,
        "turnover_per_session": _per_session(realistic.metrics.turnover, session_count),
        "fill_count": len(realistic.trades),
        "fills_per_session": _per_session(Decimal(len(realistic.trades)), session_count),
        "completed_round_trip_count": completed_round_trips,
        "round_trips_per_session": _per_session(Decimal(completed_round_trips), session_count),
        "sessions_in_range": session_count,
        "sessions_traded": len(traded_sessions),
        "sessions_traded_percentage": _per_session(Decimal(len(traded_sessions)), session_count),
        "best_trade_positive_profit_concentration": _v3_concentration(
            positive_trades[:1], total_positive_trades
        ),
        "best_session_positive_profit_concentration": _v3_best_session_concentration(
            session_profits
        ),
        "best_5_trades_positive_profit_concentration": _v3_concentration(
            positive_trades[:5], total_positive_trades
        ),
        "best_symbol_positive_profit_concentration": (
            max(positive_symbol_profits) / total_positive_symbol_profit
            if total_positive_symbol_profit
            else None
        ),
        "desired_state_evaluation_count": len(realistic.decisions),
        "desired_state_change_count": realistic.desired_state_change_count,
        "executed_state_transition_count": realistic.executed_state_transition_count,
        "periodic_rebalance_count": realistic.periodic_rebalance_count,
        "canceled_transition_count": sum(
            item.status == "canceled" for item in realistic.transitions
        ),
        "rejected_transition_count": sum(
            item.status == "rejected" for item in realistic.transitions
        ),
        "no_op_transition_count": sum(item.status == "no-op" for item in realistic.transitions),
        "overnight_position_count": overnight_count,
        "outside_session_fill_count": outside_session_count,
        "early_close_session_count": _v3_early_close_session_count(bars),
        "max_drawdown": realistic.metrics.max_drawdown,
    }
    unsigned: dict[str, object] = {
        "schema_version": V3_REPORT_SCHEMA,
        "status": "completed-diagnostic-only",
        "provenance": canonicalize(spec),
        "configuration_provenance_fingerprint": spec.configuration_fingerprint,
        "input_bars_fingerprint": input_fingerprint,
        "input_bar_count": len(bars),
        "strategy": {"id": realistic.strategy_id, "version": realistic.strategy_version},
        "execution_contract": {
            "model": V3_EXECUTION_MODEL,
            "earliest_fill_semantics": V3_EARLIEST_FILL_SEMANTICS,
            "queue_policy": V3_QUEUE_POLICY,
            "session_policy": V3_SESSION_POLICY,
            "execution_delay_bars": spec.execution_delay_bars,
            "periodic_rebalance_policy": V3_PERIODIC_REBALANCE_POLICY,
            "initial_cash": V3_INITIAL_CASH,
        },
        "realistic": {
            "result_artifact_fingerprint": realistic.artifact_fingerprint,
            "cost_model_version": realistic.cost_model.version,
            "net_return": realistic.metrics.total_return,
            "cost_paid_total": realistic_cost,
            "metrics": realistic_metrics,
        },
        "zero_cost_counterfactual": {
            "diagnostic_policy": V3_DIAGNOSTIC_POLICY,
            "result_artifact_fingerprint": zero_cost.artifact_fingerprint,
            "cost_model_version": zero_cost.cost_model.version,
            "return": zero_cost.metrics.total_return,
            "cost_paid_total": zero_cost_paid,
            "semantic_trace_matches_realistic": True,
        },
        "decomposition_methodology": (
            "exact paired replay on identical bars, desired-state decisions, FIFO delay, and "
            "session-close semantics; the signed drag is zero-cost return minus realistic return"
        ),
        "diagnostic_replay_fingerprint": replay.artifact_fingerprint,
        "semantic_trace_fingerprint": replay.semantic_trace_fingerprint,
        "authority": dict(_AUTHORITY_FLAGS),
        "qualification_metric_source": (
            "realistic-cost metrics only, and only after a separate reviewed V3 "
            "qualification contract"
        ),
    }
    integrity = {
        "configuration_provenance_fingerprint": unsigned["configuration_provenance_fingerprint"],
        "input_bars_fingerprint": unsigned["input_bars_fingerprint"],
        "realistic_result_artifact_fingerprint": realistic.artifact_fingerprint,
        "zero_cost_result_artifact_fingerprint": zero_cost.artifact_fingerprint,
        "semantic_trace_fingerprint": unsigned["semantic_trace_fingerprint"],
        "diagnostic_replay_fingerprint": unsigned["diagnostic_replay_fingerprint"],
        "execution_contract": unsigned["execution_contract"],
    }
    unsigned["evidence_integrity_fingerprint"] = fingerprint(integrity)
    return {**unsigned, "report_fingerprint": fingerprint(unsigned)}


def _validate_v3_input_bars(spec: IntradayV3ExperimentSpec, bars: Sequence[OHLCVBar]) -> str:
    if not bars:
        raise ValueError("V3 diagnostic requires input bars")
    ordered = tuple(sorted(bars, key=lambda bar: (bar.symbol.value, bar.timestamp)))
    if (
        min(bar.timestamp for bar in ordered) != spec.start_timestamp
        or max(bar.timestamp for bar in ordered) != spec.end_timestamp
    ):
        raise ValueError("V3 diagnostic bars differ from the experiment range")
    observed = fingerprint(tuple(bar.to_record() for bar in ordered))
    if observed != spec.dataset_fingerprint:
        raise ValueError("V3 diagnostic bars differ from the dataset fingerprint")
    return observed


def write_v3_diagnostic_report(
    path: Path,
    spec: IntradayV3ExperimentSpec,
    replay: V3DiagnosticReplay,
    bars: Sequence[OHLCVBar],
) -> dict[str, object]:
    """Publish one immutable V3 diagnostic report without registry or authority changes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        report = build_v3_diagnostic_report(spec, replay, bars)
        temporary.write_text(canonical_json(report) + "\n", encoding="utf-8", newline="\n")
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise FileExistsError(f"report already exists: {path}") from error
    finally:
        temporary.unlink(missing_ok=True)
    return report


def _overnight_position_count(result: V3BacktestResult) -> int:
    final_by_session: dict[date, EquityPoint] = {}
    for point in result.equity_curve:
        final_by_session[_exchange_session_timestamp(point.timestamp)] = point
    return sum(
        quantity != 0 for point in final_by_session.values() for _, quantity in point.positions
    )


def _per_session(value: Decimal, session_count: int) -> Decimal:
    if session_count < 1:
        raise ValueError("V3 report requires at least one session")
    return value / Decimal(session_count)


def _v3_round_trips(
    result: V3BacktestResult,
) -> tuple[tuple[Decimal, ...], Mapping[Symbol, Decimal]]:
    entries: dict[Symbol, tuple[Decimal, Trade] | None] = {}
    profits: list[Decimal] = []
    by_symbol: dict[Symbol, Decimal] = {}
    for trade in result.trades:
        if trade.quantity > 0:
            entries[trade.symbol] = (trade.quantity, trade)
            continue
        entry = entries.pop(trade.symbol, None)
        if entry is None or entry[0] != abs(trade.quantity):
            raise ValueError("V3 report trade sequence does not form exact round trips")
        quantity, opened = entry
        profit = quantity * (trade.fill_price - opened.fill_price) - (
            opened.commission + trade.commission
        )
        profits.append(profit)
        by_symbol[trade.symbol] = by_symbol.get(trade.symbol, _ZERO) + profit
    if entries:
        raise ValueError("V3 report contains an open round trip")
    return tuple(profits), MappingProxyType(by_symbol)


def _v3_session_profits(result: V3BacktestResult) -> tuple[Decimal, ...]:
    end_equity: dict[date, Decimal] = {}
    for point in result.equity_curve:
        end_equity[_exchange_session_timestamp(point.timestamp)] = point.equity
    prior = result.initial_cash
    profits: list[Decimal] = []
    for equity in end_equity.values():
        profits.append(equity - prior)
        prior = equity
    return tuple(profits)


def _v3_concentration(values: Sequence[Decimal], total: Decimal) -> Decimal | None:
    return sum(values, _ZERO) / total if total else None


def _v3_best_session_concentration(profits: Sequence[Decimal]) -> Decimal | None:
    positive = tuple(profit for profit in profits if profit > 0)
    return max(positive) / sum(positive, _ZERO) if positive else None


def _v3_early_close_session_count(bars: Sequence[OHLCVBar]) -> int:
    final_by_session: dict[date, time] = {}
    for bar in bars:
        local = bar.timestamp.astimezone(_NEW_YORK)
        final_by_session[local.date()] = max(
            local.time().replace(tzinfo=None),
            final_by_session.get(local.date(), time.min),
        )
    return sum(final < time(15) for final in final_by_session.values())


@dataclass(frozen=True)
class V3CampaignDraft:
    payload: Mapping[str, object]
    draft_fingerprint: str
    candidate_count: int
    exposed_periods: tuple[tuple[date, date], ...]


@dataclass(frozen=True)
class V3Period:
    role: str
    split: ExperimentSplit
    new_york_session_start: date
    new_york_session_end: date
    start_timestamp: datetime
    end_timestamp: datetime


@dataclass(frozen=True)
class V3PeriodSelection:
    periods: tuple[V3Period, ...]
    known_exposure_fingerprint: str
    selection_fingerprint: str
    status: str = "candidate-selection-requires-independent-review"


def load_v3_campaign_draft(path: Path) -> V3CampaignDraft:
    return parse_v3_campaign_draft(json.loads(path.read_text(encoding="utf-8")))


def parse_v3_campaign_draft(value: object) -> V3CampaignDraft:
    """Validate the non-sealable V3 design without creating campaign state."""

    fields = {
        "schema_version",
        "campaign_id",
        "status",
        "purpose",
        "search_budget",
        "data_contract",
        "execution_contract",
        "known_exposed_periods",
        "period_selection",
        "periods",
        "strategies",
        "variants",
        "cash_sanity_test",
        "qualification",
        "source_provenance",
        "authorities",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("V3 campaign draft fields differ")
    if (
        value["schema_version"] != V3_CAMPAIGN_DRAFT_SCHEMA
        or value["campaign_id"] != V3_CAMPAIGN_ID
        or value["status"] != "draft-unpreregistered"
        or not isinstance(value["purpose"], str)
        or "not financial validation" not in value["purpose"].lower()
    ):
        raise ValueError("V3 campaign draft identity differs")
    if value["data_contract"] != {
        "provider": "alpaca",
        "feed": "iex",
        "adjustment": "all",
        "timeframe": "5m",
        "symbols": ["SPY", "QQQ"],
    }:
        raise ValueError("V3 campaign draft data contract differs")
    if value["execution_contract"] != {
        "experiment_schema": V3_EXPERIMENT_SCHEMA,
        "report_schema": V3_REPORT_SCHEMA,
        "execution_model": V3_EXECUTION_MODEL,
        "earliest_fill_semantics": V3_EARLIEST_FILL_SEMANTICS,
        "queue_policy": V3_QUEUE_POLICY,
        "session_policy": V3_SESSION_POLICY,
        "periodic_rebalance_policy": V3_PERIODIC_REBALANCE_POLICY,
        "diagnostic_policy": V3_DIAGNOSTIC_POLICY,
        "initial_cash": "100000",
    }:
        raise ValueError("V3 campaign draft execution contract differs")
    periods = value["periods"]
    expected_periods = [
        {"role": "training", "split": "training", "selection_status": "unselected"},
        {"role": "validation-a", "split": "validation", "selection_status": "unselected"},
        {"role": "validation-b", "split": "validation", "selection_status": "unselected"},
        {"role": "validation-c", "split": "validation", "selection_status": "unselected"},
    ]
    if periods != expected_periods:
        raise ValueError("V3 campaign periods must remain unselected in the draft")
    strategies = value["strategies"]
    expected_strategies = [
        {
            "strategy_id": strategy_id,
            "strategy_version": "1",
            "strategy_family": family,
            "parameters": dict(parameters),
        }
        for strategy_id, (family, parameters) in _STRATEGY_CONTRACTS.items()
    ]
    if strategies != expected_strategies:
        raise ValueError("V3 campaign fixed strategy contract differs")
    variants = value["variants"]
    expected_variants = [
        {
            "role": "base",
            "cost_model_version": "conservative-bps-v1",
            "slippage_bps": "5",
            "commission_bps": "1",
            "execution_delay_bars": 1,
        },
        {
            "role": "increased-cost",
            "cost_model_version": "intraday-increased-cost-bps-v1",
            "slippage_bps": "10",
            "commission_bps": "2",
            "execution_delay_bars": 1,
        },
        {
            "role": "harsher-cost",
            "cost_model_version": "intraday-harsher-cost-bps-v1",
            "slippage_bps": "20",
            "commission_bps": "5",
            "execution_delay_bars": 1,
        },
        {
            "role": "plus-1-bar",
            "cost_model_version": "conservative-bps-v1",
            "slippage_bps": "5",
            "commission_bps": "1",
            "execution_delay_bars": 2,
        },
        {
            "role": "plus-2-bars",
            "cost_model_version": "conservative-bps-v1",
            "slippage_bps": "5",
            "commission_bps": "1",
            "execution_delay_bars": 3,
        },
    ]
    if variants != expected_variants:
        raise ValueError("V3 campaign variant contract differs")
    candidate_count = len(periods) * len(strategies) * len(variants)
    if value["search_budget"] != candidate_count or candidate_count != 60:
        raise ValueError("V3 campaign draft must reserve exactly 60 candidates")
    if value["cash_sanity_test"] != {
        "strategy_id": "intraday-cash",
        "budgeted": False,
        "authority": "software-sanity-only",
    }:
        raise ValueError("V3 cash sanity-test boundary differs")
    if value["qualification"] != {
        "threshold_source": "intraday-qualification-policy-v1",
        "thresholds_changed": False,
        "activation_status": "requires-reviewed-v3-qualification-contract",
        "turnover_gate_status": "not-proposed",
        "zero_cost_results_are_qualification_inputs": False,
    }:
        raise ValueError("V3 qualification draft differs")
    if value["source_provenance"] != {
        "status": "required-before-preregistration",
        "surface_scope": "whole-application-package-exact-bytes-v1",
        "required_new_modules": ["systematic_trading_lab/intraday_v3.py"],
        "reviewed_source_merged": False,
        "main_attested_wheel": False,
        "exact_runtime_closure": False,
        "source_assessment": False,
        "human_review": False,
        "immutable_source_review": False,
        "atomic_dataset_binding": False,
    }:
        raise ValueError("V3 source-provenance draft differs")
    authorities = value["authorities"]
    if (
        not isinstance(authorities, dict)
        or authorities != _AUTHORITY_FLAGS
        or any(type(item) is not bool for item in authorities.values())
    ):
        raise ValueError("V3 campaign draft authority boundary differs")
    if value["period_selection"] != {
        "policy": "known-exposure-exclusion-and-independent-review-v1",
        "validation_preference": "forward",
        "status": "unselected",
        "selection_does_not_certify_unobserved": True,
    }:
        raise ValueError("V3 period-selection policy differs")
    exposures_value = value["known_exposed_periods"]
    if not isinstance(exposures_value, list) or not exposures_value:
        raise ValueError("V3 known exposed periods are required")
    exposures: list[tuple[date, date]] = []
    for item in exposures_value:
        if not isinstance(item, dict) or set(item) != {"source", "start", "end"}:
            raise ValueError("V3 known exposed period is malformed")
        if not isinstance(item["source"], str) or not item["source"]:
            raise ValueError("V3 known exposed period source is required")
        start = date.fromisoformat(str(item["start"]))
        end = date.fromisoformat(str(item["end"]))
        if start > end:
            raise ValueError("V3 known exposed period is reversed")
        exposures.append((start, end))
    required_v2_exposure = (date(2025, 7, 1), date(2026, 6, 30))
    if required_v2_exposure not in exposures:
        raise ValueError("V3 draft must treat the full V2 window as exposed")
    frozen = _deep_freeze(value)
    assert isinstance(frozen, Mapping)
    return V3CampaignDraft(frozen, fingerprint(value), candidate_count, tuple(exposures))


def validate_v3_period_selection(draft: V3CampaignDraft, value: object) -> V3PeriodSelection:
    """Reject known exposure overlap; independent review must still prove freshness."""

    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("V3 period selection requires Training and Validation A/B/C")
    expected_roles = ("training", "validation-a", "validation-b", "validation-c")
    periods: list[V3Period] = []
    for index, item in enumerate(value):
        fields = {
            "role",
            "split",
            "new_york_session_start",
            "new_york_session_end",
            "start_timestamp",
            "end_timestamp",
        }
        if (
            not isinstance(item, dict)
            or set(item) != fields
            or item["role"] != expected_roles[index]
        ):
            raise ValueError("V3 selected period fields or role ordering differ")
        split = ExperimentSplit(str(item["split"]))
        expected_split = ExperimentSplit.TRAINING if index == 0 else ExperimentSplit.VALIDATION
        if split is not expected_split:
            raise ValueError("V3 selected period split ordering differs")
        session_start = date.fromisoformat(str(item["new_york_session_start"]))
        session_end = date.fromisoformat(str(item["new_york_session_end"]))
        start = _parse_utc(item["start_timestamp"])
        end = _parse_utc(item["end_timestamp"])
        expected = expected_bar_timestamps(
            datetime.combine(session_start, time.min, UTC),
            datetime.combine(session_end, time.max, UTC),
            Timeframe.FIVE_MINUTES,
        )
        if (
            session_start > session_end
            or not expected
            or (start, end) != (expected[0], expected[-1])
        ):
            raise ValueError("V3 selected period does not cover exact XNYS sessions")
        if periods and (
            periods[-1].new_york_session_end >= session_start or periods[-1].end_timestamp >= start
        ):
            raise ValueError("V3 selected periods must be chronological and non-overlapping")
        if split is ExperimentSplit.VALIDATION and any(
            not (session_end < exposed_start or session_start > exposed_end)
            for exposed_start, exposed_end in draft.exposed_periods
        ):
            raise ValueError("V3 validation period overlaps known exposed evidence")
        periods.append(V3Period(item["role"], split, session_start, session_end, start, end))
    exposure_fingerprint = fingerprint(draft.payload["known_exposed_periods"])
    unsigned = {
        "periods": tuple(
            {
                "role": period.role,
                "split": period.split,
                "new_york_session_start": period.new_york_session_start.isoformat(),
                "new_york_session_end": period.new_york_session_end.isoformat(),
                "start_timestamp": period.start_timestamp,
                "end_timestamp": period.end_timestamp,
            }
            for period in periods
        ),
        "known_exposure_fingerprint": exposure_fingerprint,
        "status": "candidate-selection-requires-independent-review",
    }
    return V3PeriodSelection(tuple(periods), exposure_fingerprint, fingerprint(unsigned))


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("V3 selected timestamp must be text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("V3 selected timestamp must be UTC")
    return parsed.astimezone(UTC)


def _deep_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _exchange_session(bar: OHLCVBar) -> date:
    return _exchange_session_timestamp(bar.timestamp)


def _exchange_session_timestamp(timestamp: datetime) -> date:
    return timestamp.astimezone(_NEW_YORK).date()
