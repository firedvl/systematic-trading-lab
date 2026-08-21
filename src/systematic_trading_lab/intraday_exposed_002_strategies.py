"""Frozen causal decision mechanics for Intraday Exposed 002.

This module is deliberately self-contained: it turns completed, aligned five
minute SPY/QQQ bars into desired portfolio state and never submits orders.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .domain import OHLCVBar, Symbol
from .intraday_execution_cost_model import IntradayExecutionCostModel, RegulatoryFill
from .strategies import TargetPosition

if TYPE_CHECKING:
    from .intraday_exposed_002_plan import Exposed002Configuration

_NY = ZoneInfo("America/New_York")
_SYMBOLS = (Symbol("QQQ"), Symbol("SPY"))
_ZERO, _HALF, _ONE, _BPS = Decimal("0"), Decimal("0.5"), Decimal("1"), Decimal("10000")
_FAMILIES = frozenset(
    {
        "gap-down-failed-continuation-fade-v1",
        "gap-up-confirmed-continuation-v1",
        "opening-range-breakout-v1",
        "volatility-compression-breakout-v1",
        "trend-pullback-recovery-v1",
        "prior-session-level-event-v1",
        "morning-afternoon-continuation-v1",
        "cross-asset-confirmed-breakout-v1",
        "volatility-filtered-breakout-v1",
        "minimum-edge-hysteresis-one-trade-v1",
    }
)


def build_intraday_exposed_002_strategy(
    configuration: Exposed002Configuration | str,
    symbols: tuple[Symbol, ...] = _SYMBOLS,
    parameters: Mapping[str, object] | None = None,
    *,
    cost_model: IntradayExecutionCostModel,
) -> IntradayExposed002Strategy:
    """Build one exact parent configuration without runner or registry integration."""
    if isinstance(configuration, str):
        if parameters is None:
            raise ValueError("Intraday Exposed 002 parameters are required")
        family_id, candidate_id, values = configuration, None, parameters
    else:
        if parameters is not None:
            raise ValueError("configuration already supplies frozen parameters")
        family_id = configuration.family_id
        candidate_id = configuration.candidate_id
        values = configuration.parameters
    return IntradayExposed002Strategy(family_id, symbols, values, cost_model, candidate_id)


@dataclass(frozen=True)
class IntradayExposed002Strategy:
    family_id: str
    symbols: tuple[Symbol, ...]
    parameters: Mapping[str, object]
    cost_model: IntradayExecutionCostModel
    candidate_id: str | None = None
    version: str = "intraday-exposed-002-mechanics-v1"

    def __post_init__(self) -> None:
        if self.family_id not in _FAMILIES:
            raise ValueError("unknown Intraday Exposed 002 family")
        if tuple(sorted(self.symbols, key=lambda item: item.value)) != _SYMBOLS:
            raise ValueError("Intraday Exposed 002 requires exactly QQQ and SPY")
        normalized = _validate_parameters(self.family_id, self.parameters)
        object.__setattr__(self, "parameters", normalized)
        if self.candidate_id is not None and not self.candidate_id.startswith("ie002-"):
            raise ValueError("Intraday Exposed 002 candidate identity is invalid")

    @property
    def strategy_id(self) -> str:
        return self.candidate_id or self.family_id

    def on_session(
        self, bars: Sequence[OHLCVBar], history: Mapping[Symbol, Sequence[OHLCVBar]]
    ) -> Sequence[TargetPosition]:
        current, sessions = self._slice(bars, history)
        active = self._active_symbols(current, sessions, history)
        return tuple(
            TargetPosition(symbol, _HALF if symbol in active else _ZERO, self.family_id)
            for symbol in self.symbols
        )

    def _slice(
        self, bars: Sequence[OHLCVBar], history: Mapping[Symbol, Sequence[OHLCVBar]]
    ) -> tuple[dict[Symbol, OHLCVBar], dict[Symbol, tuple[OHLCVBar, ...]]]:
        current = {bar.symbol: bar for bar in bars}
        if len(bars) != 2 or set(current) != set(self.symbols) or set(history) != set(self.symbols):
            raise ValueError("Intraday Exposed 002 requires a complete QQQ/SPY slice")
        timestamps = tuple(
            tuple(item.timestamp for item in history[symbol]) for symbol in self.symbols
        )
        if (
            not timestamps[0]
            or timestamps[0] != timestamps[1]
            or any(history[symbol][-1] != current[symbol] for symbol in self.symbols)
        ):
            raise ValueError("Intraday Exposed 002 requires aligned completed histories")
        session_day = bars[0].timestamp.astimezone(_NY).date()
        if any(bar.timestamp.astimezone(_NY).date() != session_day for bar in bars):
            raise ValueError("Intraday Exposed 002 slice spans sessions")
        sessions = {
            symbol: tuple(
                item
                for item in history[symbol]
                if item.timestamp.astimezone(_NY).date() == session_day
            )
            for symbol in self.symbols
        }
        session_times = tuple(
            tuple(item.timestamp for item in sessions[symbol]) for symbol in self.symbols
        )
        if (
            not session_times[0]
            or session_times[0] != session_times[1]
            or any(
                right - left != timedelta(minutes=5)
                for left, right in zip(session_times[0], session_times[0][1:], strict=False)
            )
        ):
            raise ValueError("Intraday Exposed 002 requires contiguous completed five-minute bars")
        return current, sessions

    def _active_symbols(
        self,
        current: Mapping[Symbol, OHLCVBar],
        session: Mapping[Symbol, tuple[OHLCVBar, ...]],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> set[Symbol]:
        active: set[Symbol] = set()
        for symbol in self.symbols:
            entered, exit_now = self._state(symbol, current, session, history)
            if entered and not exit_now:
                active.add(symbol)
        return active

    def _state(
        self,
        symbol: Symbol,
        current: Mapping[Symbol, OHLCVBar],
        session: Mapping[Symbol, tuple[OHLCVBar, ...]],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> tuple[bool, bool]:
        bars, p = session[symbol], self.parameters
        index = len(bars) - 1
        entered = any(
            self._entry(
                symbol,
                item,
                _at(session, item),
                session,
                _history_to(session, history, item),
            )
            for item in range(index + 1)
        )
        if not entered:
            return False, False
        # A family can close only once; the entry scan means later signals never resize or re-enter.
        entry_index = next(
            item
            for item in range(index + 1)
            if self._entry(
                symbol,
                item,
                _at(session, item),
                session,
                _history_to(session, history, item),
            )
        )
        if self.family_id.startswith("gap-") and index >= _integer(p, "exit_bar_index"):
            return True, True
        if self.family_id == "opening-range-breakout-v1":
            floor = min(item.low for item in bars[: _integer(p, "range_bars")])
            return True, any(item.close <= floor for item in bars[entry_index : index + 1])
        if self.family_id == "volatility-compression-breakout-v1":
            floor = min(item.low for item in bars[max(0, entry_index - 1) : entry_index + 1])
            return True, any(item.close <= floor for item in bars[entry_index : index + 1])
        if self.family_id == "trend-pullback-recovery-v1":
            floor = min(item.low for item in bars[max(0, entry_index - 1) : entry_index + 1])
            return True, any(item.close <= floor for item in bars[entry_index : index + 1])
        if self.family_id == "prior-session-level-event-v1":
            floor = min(item.low for item in bars[max(0, entry_index - 1) : entry_index + 1])
            return True, any(item.close <= floor for item in bars[entry_index : index + 1])
        if self.family_id == "morning-afternoon-continuation-v1":
            return True, any(
                item.close < bars[_integer(p, "morning_cutoff_bar_index")].close
                for item in bars[entry_index : index + 1]
            )
        if self.family_id in {
            "cross-asset-confirmed-breakout-v1",
            "volatility-filtered-breakout-v1",
        }:
            floor = min(item.low for item in bars[:6])
            return True, any(item.close <= floor for item in bars[entry_index : index + 1])
        if self.family_id == "minimum-edge-hysteresis-one-trade-v1":
            cost = self._round_trip_cost_bps(symbol, bars[entry_index])
            floor = bars[entry_index].close * (
                _ONE - cost * _decimal(p, "hysteresis_cost_multiple") / _BPS
            )
            return True, any(item.close < floor for item in bars[entry_index : index + 1])
        return True, False

    def _entry(
        self,
        symbol: Symbol,
        index: int,
        current: Mapping[Symbol, OHLCVBar],
        session: Mapping[Symbol, tuple[OHLCVBar, ...]],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> bool:
        bars, p = session[symbol], self.parameters
        close = bars[index].close
        prior = _prior_session(history[symbol], bars[0].timestamp)
        if self.family_id == "gap-down-failed-continuation-fade-v1":
            if not prior or index + 1 < _integer(p, "confirmation_bars"):
                return False
            prev = prior[-1].close
            return bars[0].open <= prev * (
                1 - _decimal(p, "minimum_gap_bps") / _BPS
            ) and close >= bars[0].open + (prev - bars[0].open) * _decimal(
                p, "minimum_retrace_fraction"
            )
        if self.family_id == "gap-up-confirmed-continuation-v1":
            if not prior or index + 1 < _integer(p, "confirmation_bars"):
                return False
            prev = prior[-1].close
            return bars[0].open >= prev * (
                1 + _decimal(p, "minimum_gap_bps") / _BPS
            ) and close > max(item.high for item in bars[:index]) * (
                1 + _decimal(p, "breakout_buffer_bps") / _BPS
            )
        if self.family_id == "opening-range-breakout-v1":
            n = _integer(p, "range_bars")
            threshold = max(
                _decimal(p, "breakout_buffer_bps"),
                self._round_trip_cost_bps(symbol, bars[index])
                * _decimal(p, "minimum_edge_cost_multiple"),
            )
            return index >= n and close > max(item.high for item in bars[:n]) * (
                1 + threshold / _BPS
            )
        if self.family_id == "volatility-compression-breakout-v1":
            n = _integer(p, "compression_bars")
            if index < n:
                return False
            window = bars[index - n : index]
            return _range_bps(window) <= _decimal(
                p, "maximum_compression_range_bps"
            ) and close > max(item.high for item in window) * (
                1 + _decimal(p, "expansion_buffer_bps") / _BPS
            )
        if self.family_id == "trend-pullback-recovery-v1":
            n = _integer(p, "trend_bars")
            if index < n:
                return False
            window = bars[index - n : index]
            baseline = window[0].close
            peak_index = max(range(len(window)), key=lambda item: window[item].high)
            peak = window[peak_index].high
            trend = (peak / baseline - _ONE) * _BPS
            pullback = (
                (peak - min(item.low for item in window[peak_index + 1 :])) / (peak - baseline)
                if peak > baseline and peak_index < len(window) - 1
                else _ZERO
            )
            return (
                trend >= _decimal(p, "minimum_trend_bps")
                and pullback >= _decimal(p, "pullback_fraction")
                and close > bars[index - 1].high * (1 + _decimal(p, "recovery_buffer_bps") / _BPS)
            )
        if self.family_id == "prior-session-level-event-v1":
            if not prior or index + 1 < _integer(p, "confirmation_bars"):
                return False
            high, low = max(item.high for item in prior), min(item.low for item in prior)
            if (high / low - _ONE) * _BPS < _decimal(p, "minimum_prior_range_bps"):
                return False
            buffer = _decimal(p, "level_buffer_bps") / _BPS
            if p["event"] == "prior-high-breakout":
                return close > high * (1 + buffer)
            return min(item.low for item in bars[: index + 1]) < low * (1 - buffer) and close > low
        if self.family_id == "morning-afternoon-continuation-v1":
            cutoff = _integer(p, "morning_cutoff_bar_index")
            if index < max(cutoff, _integer(p, "earliest_entry_bar_index")):
                return False
            return (bars[cutoff].close / bars[0].open - _ONE) * _BPS >= _decimal(
                p, "minimum_morning_return_bps"
            ) and close > max(item.high for item in bars[cutoff:index])
        if self.family_id == "cross-asset-confirmed-breakout-v1":
            n = _integer(p, "opening_range_bars")
            confirmation = _integer(p, "confirmation_window_bars")
            if index < n + confirmation - 1:
                return False
            threshold = _decimal(p, "minimum_joint_breakout_bps") / _BPS
            return all(
                session[item][confirmation_index].close
                > max(bar.high for bar in session[item][:n]) * (1 + threshold)
                for item in self.symbols
                for confirmation_index in range(index - confirmation + 1, index + 1)
            )
        if self.family_id == "volatility-filtered-breakout-v1":
            n = _integer(p, "opening_range_bars")
            sessions = _completed_sessions(history[symbol], bars[0].timestamp)
            if index < n or len(sessions) < _integer(p, "prior_session_lookback"):
                return False
            expected = sum(
                (_range_bps(day) for day in sessions[-_integer(p, "prior_session_lookback") :]),
                _ZERO,
            ) / _integer(p, "prior_session_lookback")
            return expected >= self._round_trip_cost_bps(symbol, bars[index]) * _decimal(
                p,
                "minimum_expected_move_cost_multiple",
            ) and close > max(item.high for item in bars[:n]) * (
                1 + _decimal(p, "breakout_buffer_bps") / _BPS
            )
        n = _integer(p, "observation_bars")
        if index < n:
            return False
        multiple = _decimal(p, "entry_edge_cost_multiple")
        return all(
            (session[item][index].close / max(bar.high for bar in session[item][:n]) - _ONE) * _BPS
            >= self._round_trip_cost_bps(item, session[item][index]) * multiple
            for item in self.symbols
        )

    def _round_trip_cost_bps(self, symbol: Symbol, bar: OHLCVBar) -> Decimal:
        """Estimate one frozen half-weight round trip from current causal price data."""
        normal = self.cost_model.scenarios["normal"]
        notional = Decimal("50000")
        buy_price = normal.fill_price(symbol, bar.close, _ONE)
        quantity = notional / buy_price
        sell_price = normal.fill_price(symbol, bar.close, -_ONE)
        trade_id = f"edge-estimate:{symbol.value}"
        fills = (
            RegulatoryFill(bar.timestamp, trade_id, "buy", quantity, quantity * buy_price),
            RegulatoryFill(bar.timestamp, trade_id, "sell", quantity, quantity * sell_price),
        )
        fees = self.cost_model.regulatory_fees.charges_for_account_day(
            bar.timestamp.astimezone(_NY).date(), fills
        ).total
        return normal.slippage_bps_per_fill[symbol] * Decimal("2") + fees / notional * _BPS


def _at(session: Mapping[Symbol, tuple[OHLCVBar, ...]], index: int) -> dict[Symbol, OHLCVBar]:
    return {symbol: session[symbol][index] for symbol in session}


def _history_to(
    session: Mapping[Symbol, tuple[OHLCVBar, ...]],
    history: Mapping[Symbol, Sequence[OHLCVBar]],
    index: int,
) -> dict[Symbol, tuple[OHLCVBar, ...]]:
    start = {symbol: len(history[symbol]) - len(session[symbol]) for symbol in session}
    return {symbol: tuple(history[symbol][: start[symbol] + index + 1]) for symbol in session}


def _prior_session(history: Sequence[OHLCVBar], start: datetime) -> tuple[OHLCVBar, ...]:
    sessions = _completed_sessions(history, start)
    return sessions[-1] if sessions else ()


def _completed_sessions(
    history: Sequence[OHLCVBar], start: datetime
) -> tuple[tuple[OHLCVBar, ...], ...]:
    grouped: list[list[OHLCVBar]] = []
    for bar in history:
        if bar.timestamp >= start:
            break
        day = bar.timestamp.astimezone(_NY).date()
        if not grouped or grouped[-1][0].timestamp.astimezone(_NY).date() != day:
            grouped.append([])
        grouped[-1].append(bar)
    return tuple(tuple(items) for items in grouped)


def _range_bps(bars: Sequence[OHLCVBar]) -> Decimal:
    return (max(item.high for item in bars) / min(item.low for item in bars) - _ONE) * _BPS


def _integer(parameters: Mapping[str, object], name: str) -> int:
    value = parameters[name]
    assert isinstance(value, int)
    return value


def _decimal(parameters: Mapping[str, object], name: str) -> Decimal:
    value = parameters[name]
    assert isinstance(value, Decimal)
    return value


def _validate_parameters(family: str, values: Mapping[str, object]) -> dict[str, object]:
    all_expected: Mapping[str, Mapping[str, tuple[object, ...]]] = {
        "gap-down-failed-continuation-fade-v1": {
            "minimum_gap_bps": ("20", "40", "60"),
            "confirmation_bars": (3, 6),
            "minimum_retrace_fraction": ("0.5",),
            "exit_bar_index": (66,),
            "gap_side": ("down-only",),
        },
        "gap-up-confirmed-continuation-v1": {
            "minimum_gap_bps": ("20", "40", "60"),
            "confirmation_bars": (3, 6),
            "breakout_buffer_bps": ("5",),
            "exit_bar_index": (66,),
            "gap_side": ("up-only",),
        },
        "opening-range-breakout-v1": {
            "range_bars": (2, 3, 6),
            "breakout_buffer_bps": ("5", "10"),
            "minimum_edge_cost_multiple": ("4",),
            "reentry_allowed": (False,),
        },
        "volatility-compression-breakout-v1": {
            "compression_bars": (6, 12, 18),
            "maximum_compression_range_bps": ("15", "30"),
            "expansion_buffer_bps": ("5",),
            "reentry_allowed": (False,),
        },
        "trend-pullback-recovery-v1": {
            "trend_bars": (6, 12, 18),
            "minimum_trend_bps": ("20", "40"),
            "pullback_fraction": ("0.3333333333333333333333333333",),
            "recovery_buffer_bps": ("5",),
            "reentry_allowed": (False,),
        },
        "prior-session-level-event-v1": {
            "event": ("prior-high-breakout", "prior-low-rejection"),
            "minimum_prior_range_bps": ("30", "60", "90"),
            "level_buffer_bps": ("5",),
            "confirmation_bars": (2,),
            "reentry_allowed": (False,),
        },
        "morning-afternoon-continuation-v1": {
            "morning_cutoff_bar_index": (24, 30, 36),
            "minimum_morning_return_bps": ("20", "40"),
            "earliest_entry_bar_index": (48,),
            "reentry_allowed": (False,),
        },
        "cross-asset-confirmed-breakout-v1": {
            "confirmation_window_bars": (1, 2, 3),
            "minimum_joint_breakout_bps": ("5", "10"),
            "opening_range_bars": (6,),
            "require_spy_qqq_agreement": (True,),
            "reentry_allowed": (False,),
        },
        "volatility-filtered-breakout-v1": {
            "prior_session_lookback": (3, 5, 10),
            "minimum_expected_move_cost_multiple": ("4", "8"),
            "opening_range_bars": (6,),
            "breakout_buffer_bps": ("5",),
            "reentry_allowed": (False,),
        },
        "minimum-edge-hysteresis-one-trade-v1": {
            "entry_edge_cost_multiple": ("4", "8", "12"),
            "hysteresis_cost_multiple": ("1", "2"),
            "observation_bars": (6,),
            "require_spy_qqq_agreement": (True,),
            "maximum_entries_per_symbol_session": (1,),
        },
    }
    expected = all_expected[family]
    if set(values) != set(expected):
        raise ValueError("Intraday Exposed 002 parameters differ")
    result: dict[str, object] = {}
    for name, allowed in expected.items():
        raw = values[name]
        if isinstance(allowed[0], int) and not isinstance(allowed[0], bool):
            if isinstance(raw, bool) or not isinstance(raw, int) or raw not in allowed:
                raise ValueError("Intraday Exposed 002 parameters differ")
            result[name] = raw
        elif isinstance(allowed[0], bool):
            if raw is not allowed[0]:
                raise ValueError("Intraday Exposed 002 parameters differ")
            result[name] = raw
        elif isinstance(allowed[0], str):
            if name in {"event", "gap_side"}:
                if raw not in allowed:
                    raise ValueError("Intraday Exposed 002 parameters differ")
                result[name] = raw
            else:
                try:
                    parsed = Decimal(str(raw))
                except (InvalidOperation, ValueError) as error:
                    raise ValueError("Intraday Exposed 002 parameters differ") from error
                decimal_allowed = tuple(item for item in allowed if isinstance(item, str))
                if (
                    not parsed.is_finite()
                    or len(decimal_allowed) != len(allowed)
                    or all(parsed != Decimal(item) for item in decimal_allowed)
                ):
                    raise ValueError("Intraday Exposed 002 parameters differ")
                result[name] = parsed
    return result
