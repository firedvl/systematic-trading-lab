"""Frozen, local-only portfolio mechanics for RAPID-004.

This module deliberately is not part of the ordinary strategy registry.  Its
factory accepts the already-validated campaign roles and exposes only the
contracts sealed in the RAPID-004 predeclaration.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import cast

from .domain import OHLCVBar, Symbol
from .strategies import TargetPosition

_ZERO = Decimal("0")
_ONE = Decimal("1")
_STATIC_WEIGHTS = {
    "SPY": Decimal(".40"),
    "EFA": Decimal(".20"),
    "AGG": Decimal(".30"),
    "GLD": Decimal(".10"),
}
_KNOWN_CONTRACTS = frozenset(
    {
        "ranked-equal-v1",
        "ranked-inverse-volatility-v1",
        "dual-momentum-v1",
        "multi-horizon-v1",
        "multi-horizon-inverse-volatility-v1",
        "trend-relative-strength-v1",
        "independent-trend-v1",
        "independent-trend-inverse-volatility-v1",
        "channel-breakout-v1",
        "channel-breakout-inverse-volatility-v1",
        "equity-bond-gold-regime-v1",
        "inverse-volatility-allocation-v1",
        "hierarchical-sleeve-v1",
        "breadth-scale-v1",
        "one-per-sleeve-v1",
        "defensive-breadth-v1",
        "normalized-mean-reversion-v1",
        "core-satellite-v1",
        "signal-consensus-v1",
        "fixed-weight-configured-v1",
    }
)


def build_rapid_004_portfolio_strategy(
    strategy_id: str,
    symbols: tuple[Symbol, ...],
    groups: Mapping[str, Sequence[Symbol | str]],
    sleeves: Mapping[str, Sequence[Symbol | str]],
    profiles: Mapping[str, Mapping[str, object]],
    parameters: Mapping[str, object],
    *,
    configured_weights: Mapping[Symbol | str, Decimal | str] | None = None,
    evaluation_start: datetime | None = None,
) -> Rapid004PortfolioStrategy:
    """Build one predeclared RAPID-004 strategy without registry exposure."""
    return Rapid004PortfolioStrategy(
        strategy_id,
        symbols,
        cast(Mapping[str, Sequence[Symbol]], groups),
        cast(Mapping[str, Sequence[Symbol]], sleeves),
        profiles,
        parameters,
        cast(Mapping[Symbol, Decimal] | None, configured_weights),
        evaluation_start,
    )


@dataclass
class Rapid004PortfolioStrategy:
    strategy_id: str
    symbols: tuple[Symbol, ...]
    groups: Mapping[str, Sequence[Symbol]]
    sleeves: Mapping[str, Sequence[Symbol]]
    profiles: Mapping[str, Mapping[str, object]]
    parameters: Mapping[str, object]
    configured_weights: Mapping[Symbol, Decimal] | None = None
    evaluation_start: datetime | None = None
    version: str = "rapid-004-mechanics-v1"
    _observed_active: frozenset[Symbol] | None = field(default=None, init=False, repr=False)
    _evaluation_started: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("Rapid-004 requires unique frozen symbols")
        if tuple(sorted(self.symbols, key=lambda item: item.value)) != self.symbols:
            raise ValueError("Rapid-004 frozen symbols must be sorted ascending")
        known = {symbol.value: symbol for symbol in self.symbols}
        self.groups = self._normalize_roles(self.groups, known, "group")
        self.sleeves = self._normalize_roles(self.sleeves, known, "sleeve")
        if self.strategy_id not in self.profiles:
            raise ValueError("unknown Rapid-004 strategy profile")
        profile = self.profiles[self.strategy_id]
        contract = profile.get("contract")
        group = profile.get("group")
        if not isinstance(contract, str) or contract not in _KNOWN_CONTRACTS:
            raise ValueError("unknown Rapid-004 mechanics contract")
        if not isinstance(group, str) or group not in self.groups:
            raise ValueError("Rapid-004 profile has an unknown group")
        frozen = set(self.symbols)
        for label, mapping in (("group", self.groups), ("sleeve", self.sleeves)):
            for name, members in mapping.items():
                if not members or len(set(members)) != len(members) or not set(members) <= frozen:
                    raise ValueError(f"Rapid-004 {label} {name} is invalid")
        self._require_parameters(contract)
        if contract == "fixed-weight-configured-v1":
            if not self.configured_weights:
                raise ValueError("configured fixed-weight strategy requires weights")
            parsed_weights: dict[Symbol, Decimal] = {}
            for item, weight in self.configured_weights.items():
                symbol = item if isinstance(item, Symbol) else known.get(item)
                if symbol is None or isinstance(weight, bool):
                    raise ValueError("configured fixed weights are invalid")
                try:
                    parsed_weights[symbol] = Decimal(str(weight))
                except Exception as error:
                    raise ValueError("configured fixed weights are invalid") from error
            self.configured_weights = parsed_weights
            if (
                set(self.configured_weights) - frozen
                or any(
                    weight < _ZERO or not weight.is_finite()
                    for weight in self.configured_weights.values()
                )
                or sum(self.configured_weights.values(), _ZERO) > _ONE
            ):
                raise ValueError("configured fixed weights are invalid")

    @staticmethod
    def _normalize_roles(
        roles: Mapping[str, Sequence[Symbol]], known: Mapping[str, Symbol], label: str
    ) -> dict[str, tuple[Symbol, ...]]:
        result: dict[str, tuple[Symbol, ...]] = {}
        for name, members in roles.items():
            if not isinstance(name, str) or isinstance(members, str):
                raise ValueError(f"Rapid-004 {label} is invalid")
            converted = tuple(
                item if isinstance(item, Symbol) else known.get(item) for item in members
            )
            if any(item is None for item in converted):
                raise ValueError(f"Rapid-004 {label} {name} is invalid")
            result[name] = tuple(item for item in converted if item is not None)
        return result

    def _require_parameters(self, contract: str) -> None:
        integers = (
            "lookback",
            "short_lookback",
            "long_lookback",
            "selection_count",
            "rebalance_every",
            "window",
            "entry_window",
            "exit_window",
            "trend_window",
            "rank_lookback",
            "volatility_window",
            "reversal_lookback",
            "tactical_lookback",
            "momentum_lookback",
            "defensive_selection_count",
        )
        for name in integers:
            value = self.parameters.get(name)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 1
            ):
                raise ValueError(f"Rapid-004 parameter {name} must be a positive integer")
        if "rebalance_every" in self.parameters and self._int("rebalance_every") < 1:
            raise ValueError("Rapid-004 rebalance cadence must be positive")
        if contract.startswith("channel-breakout") and self._int("exit_window") >= self._int(
            "entry_window"
        ):
            raise ValueError("Rapid-004 breakout exit window must be shorter than entry window")
        if contract in {
            "dual-momentum-v1",
            "multi-horizon-v1",
            "multi-horizon-inverse-volatility-v1",
        } and self._int("short_lookback") >= self._int("long_lookback"):
            raise ValueError("Rapid-004 short lookback must be shorter than long lookback")
        count = self.parameters.get("selection_count", self._profile().get("selection_count"))
        if count is not None and (
            not isinstance(count, int) or count < 1 or count > len(self._group())
        ):
            raise ValueError("Rapid-004 selection count does not fit its group")

    def _profile(self) -> Mapping[str, object]:
        return self.profiles[self.strategy_id]

    def _contract(self) -> str:
        return str(self._profile()["contract"])

    def _group(self, name: str | None = None) -> tuple[Symbol, ...]:
        requested = name or str(self._profile()["group"])
        try:
            return tuple(self.groups[requested])
        except KeyError as error:
            raise ValueError(f"unknown Rapid-004 group: {requested}") from error

    def _symbols(self, value: object, label: str) -> tuple[Symbol, ...]:
        if not isinstance(value, Sequence) or isinstance(value, str):
            raise ValueError(f"Rapid-004 {label} is invalid")
        known = {symbol.value: symbol for symbol in self.symbols}
        result: list[Symbol] = []
        for item in value:
            symbol = (
                item
                if isinstance(item, Symbol)
                else known.get(item)
                if isinstance(item, str)
                else None
            )
            if symbol is None or symbol not in self.symbols or symbol in result:
                raise ValueError(f"Rapid-004 {label} is invalid")
            result.append(symbol)
        return tuple(result)

    def _int(self, name: str, default: int | None = None) -> int:
        value = self.parameters.get(name, self._profile().get(name, default))
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"Rapid-004 requires positive {name}")
        return value

    def _decimal(self, name: str, default: Decimal | None = None) -> Decimal:
        value = self.parameters.get(name, self._profile().get(name, default))
        if isinstance(value, Decimal):
            result = value
        elif isinstance(value, int | str) and not isinstance(value, bool):
            result = Decimal(str(value))
        else:
            raise ValueError(f"Rapid-004 requires decimal {name}")
        if not result.is_finite():
            raise ValueError(f"Rapid-004 {name} must be finite")
        return result

    def _session(
        self, bars: Sequence[OHLCVBar], history: Mapping[Symbol, Sequence[OHLCVBar]]
    ) -> tuple[int, Mapping[Symbol, OHLCVBar]]:
        if (
            len(bars) != len(self.symbols)
            or {bar.symbol for bar in bars} != set(self.symbols)
            or set(history) != set(self.symbols)
        ):
            raise ValueError("Rapid-004 session must contain the full frozen universe")
        lengths = {len(history[symbol]) for symbol in self.symbols}
        if len(lengths) != 1 or not lengths or next(iter(lengths)) == 0:
            raise ValueError("Rapid-004 histories must be complete and aligned")
        current = {bar.symbol: bar for bar in bars}
        for symbol in self.symbols:
            if (
                history[symbol][-1].timestamp != current[symbol].timestamp
                or history[symbol][-1].close != current[symbol].close
            ):
                raise ValueError("Rapid-004 current bar must be the completed history close")
        return next(iter(lengths)), current

    def _schedule(self, session_count: int, warmup: int) -> bool:
        return (
            session_count > warmup
            and (session_count - warmup - 1) % self._int("rebalance_every", 1) == 0
        )

    def _return(
        self, symbol: Symbol, history: Mapping[Symbol, Sequence[OHLCVBar]], lookback: int
    ) -> Decimal:
        if len(history[symbol]) <= lookback:
            raise ValueError("Rapid-004 history is shorter than lookback")
        return history[symbol][-1].close / history[symbol][-lookback - 1].close - _ONE

    def _ma(
        self, symbol: Symbol, history: Mapping[Symbol, Sequence[OHLCVBar]], window: int
    ) -> Decimal:
        if len(history[symbol]) < window:
            raise ValueError("Rapid-004 history is shorter than moving-average window")
        return sum((bar.close for bar in history[symbol][-window:]), _ZERO) / Decimal(window)

    def _vol(
        self, symbol: Symbol, history: Mapping[Symbol, Sequence[OHLCVBar]], window: int
    ) -> Decimal:
        if len(history[symbol]) <= window:
            raise ValueError("Rapid-004 history is shorter than volatility window")
        closes = [bar.close for bar in history[symbol][-window - 1 :]]
        returns = [
            current / previous - _ONE for previous, current in zip(closes, closes[1:], strict=False)
        ]
        mean = sum(returns, _ZERO) / Decimal(len(returns))
        variance = sum(((item - mean) ** 2 for item in returns), _ZERO) / Decimal(len(returns) - 1)
        return variance.sqrt()

    def _iv(
        self,
        chosen: Sequence[Symbol],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
        window: int,
        cap: Decimal,
    ) -> dict[Symbol, Decimal]:
        if cap <= _ZERO or cap > _ONE:
            raise ValueError("Rapid-004 inverse-volatility cap is invalid")
        volatility = {symbol: self._vol(symbol, history, window) for symbol in chosen}
        inverse = {symbol: _ONE / value for symbol, value in volatility.items() if value > _ZERO}
        remaining = sorted(inverse, key=lambda item: item.value)
        available = _ONE
        weights: dict[Symbol, Decimal] = {}
        while remaining and available > _ZERO:
            total = sum((inverse[item] for item in remaining), _ZERO)
            capped = [item for item in remaining if available * inverse[item] / total > cap]
            if not capped:
                weights.update({item: available * inverse[item] / total for item in remaining})
                break
            for item in capped:
                weights[item] = cap
                available -= cap
                remaining.remove(item)
        total = sum(weights.values(), _ZERO)
        if total > _ONE:
            weights[min(weights, key=lambda item: item.value)] -= total - _ONE
        return weights

    def _targets(
        self, weights: Mapping[Symbol, Decimal], reason: str
    ) -> tuple[TargetPosition, ...]:
        if (
            any(symbol not in self.symbols or weight < _ZERO for symbol, weight in weights.items())
            or sum(weights.values(), _ZERO) > _ONE
        ):
            raise ValueError("Rapid-004 target weights are invalid")
        return tuple(
            TargetPosition(symbol, weights.get(symbol, _ZERO), reason) for symbol in self.symbols
        )

    def _rank(
        self, values: Mapping[Symbol, Decimal], count: int, *, lowest: bool = False
    ) -> tuple[Symbol, ...]:
        return tuple(
            symbol
            for symbol, _ in sorted(
                values.items(), key=lambda x: (x[1], x[0].value) if lowest else (-x[1], x[0].value)
            )[:count]
        )

    def _breadth(
        self, history: Mapping[Symbol, Sequence[OHLCVBar]], window: int, group: str
    ) -> Decimal:
        members = self._group(group)
        return Decimal(
            sum(history[s][-1].close > self._ma(s, history, window) for s in members)
        ) / Decimal(len(members))

    def on_session(
        self, bars: Sequence[OHLCVBar], history: Mapping[Symbol, Sequence[OHLCVBar]]
    ) -> Sequence[TargetPosition]:
        count, current = self._session(bars, history)
        timestamp = next(iter(current.values())).timestamp
        contract = self._contract()
        group = self._group()
        p = self._profile()
        if contract == "fixed-weight-configured-v1":
            if count != 1 and not self._schedule(count, 0):
                return ()
            return self._targets(self.configured_weights or {}, "fixed-weight-configured")
        warmup_values = [
            value
            for key in (
                "lookback",
                "short_lookback",
                "long_lookback",
                "window",
                "entry_window",
                "trend_window",
                "rank_lookback",
                "volatility_window",
                "reversal_lookback",
                "tactical_lookback",
                "momentum_lookback",
            )
            if isinstance((value := self.parameters.get(key, p.get(key, 1))), int)
        ]
        warmup = max(warmup_values, default=1)
        if contract.startswith("channel-breakout"):
            return self._breakout(count, timestamp, history, group)
        if contract.startswith("independent-trend"):
            return self._trend_state(count, timestamp, history, group)
        if not self._schedule(count, warmup):
            return ()
        profile_count = p.get("selection_count", 1)
        if not isinstance(profile_count, int):
            raise ValueError("Rapid-004 profile selection count is invalid")
        select = self._int("selection_count", profile_count)
        lb = self._int("lookback", 1)
        if contract in {"ranked-equal-v1", "ranked-inverse-volatility-v1"}:
            floor = (
                self._decimal("minimum_return_bps", _ZERO) / Decimal("10000")
                if "minimum_return_bps" in self.parameters
                else _ZERO
            )
            scores = {s: self._return(s, history, lb) for s in group}
            chosen = tuple(
                s for s in self._rank(scores, select) if scores[s] >= floor and scores[s] > _ZERO
            )
            weights = (
                self._iv(chosen, history, self._int("volatility_window", 63), self._decimal("cap"))
                if contract.endswith("inverse-volatility-v1")
                else {s: _ONE / Decimal(select) for s in chosen}
            )
        elif contract in {
            "multi-horizon-v1",
            "multi-horizon-inverse-volatility-v1",
            "dual-momentum-v1",
        }:
            short, long = self._int("short_lookback"), self._int("long_lookback")
            risk = self._group(str(p.get("risk_group", p.get("group"))))
            scores = {
                s: self._return(s, history, short) + self._return(s, history, long)
                for s in risk
                if self._return(s, history, short) > _ZERO
                and self._return(s, history, long) > _ZERO
            }
            chosen = self._rank(scores, select)
            if contract == "dual-momentum-v1" and not chosen:
                raw = p.get("fallback", self.groups.get(str(p.get("fallback_group")), ()))
                fallback = self._symbols(raw, "fallback")
                eligible = {
                    s: self._return(s, history, long)
                    for s in fallback
                    if self._return(s, history, long) > _ZERO
                }
                chosen = self._rank(eligible, self._int("defensive_selection_count", len(fallback)))
                cap = self._decimal("fallback_cap", _ONE)
                slots = len(chosen)
            else:
                cap = self._decimal("risk_cap", self._decimal("cap", Decimal(".40")))
                slots = select
            inverse = (
                contract.endswith("inverse-volatility-v1")
                or p.get("weighting") == "inverse-volatility"
            )
            weights = (
                self._iv(chosen, history, self._int("volatility_window", 63), cap)
                if inverse
                else {s: _ONE / Decimal(slots) for s in chosen}
            )
        elif contract == "trend-relative-strength-v1":
            trend = self._int(
                str(p.get("trend_window_parameter", "trend_window")), self._int("trend_window", lb)
            )
            rank = self._int(
                str(p.get("rank_lookback_parameter", "rank_lookback")),
                self._int("rank_lookback", lb),
            )
            scores = {
                s: self._return(s, history, rank)
                for s in group
                if history[s][-1].close > self._ma(s, history, trend)
                and self._return(s, history, rank) > _ZERO
            }
            chosen = self._rank(scores, select)
            weights = {s: _ONE / Decimal(select) for s in chosen}
        elif contract == "inverse-volatility-allocation-v1":
            weights = self._iv(group, history, self._int("volatility_window"), self._decimal("cap"))
        elif contract == "hierarchical-sleeve-v1":
            winners: list[Symbol] = []
            for members in self.sleeves.values():
                positive = {
                    s: self._return(s, history, lb)
                    for s in members
                    if self._return(s, history, lb) > _ZERO
                }
                if positive:
                    winners.extend(self._rank(positive, 1))
            weights = (
                self._iv(
                    winners,
                    history,
                    self._int("volatility_window", 63),
                    self._decimal("cap", Decimal(".40")),
                )
                if p.get("weighting") == "inverse-volatility"
                else {s: Decimal(".25") for s in winners}
            )
        elif contract == "breadth-scale-v1":
            breadth = self._breadth(history, self._int("trend_window"), str(p["breadth_group"]))
            threshold = self._decimal("breadth_threshold_percent") / Decimal("100")
            weights = (
                {
                    s: _STATIC_WEIGHTS[s.value] * breadth
                    for s in self._group(str(p["allocation_group"]))
                }
                if breadth >= threshold
                else {}
            )
        elif contract == "one-per-sleeve-v1":
            sleeve_winners: list[Symbol] = []
            for members in self.sleeves.values():
                positive = {
                    s: self._return(s, history, lb)
                    for s in members
                    if self._return(s, history, lb) > _ZERO
                }
                if positive:
                    sleeve_winners.extend(self._rank(positive, 1))
            scores = {s: self._return(s, history, lb) for s in sleeve_winners}
            chosen = self._rank(scores, select)
            weights = {s: _ONE / Decimal(select) for s in chosen}
        elif contract == "equity-bond-gold-regime-v1":
            spy = Symbol("SPY")
            risk_on = history[spy][-1].close > self._ma(
                spy, history, self._int("trend_window")
            ) and self._vol(spy, history, self._int("volatility_window")) * Decimal(
                "252"
            ).sqrt() <= self._decimal("volatility_limit_percent") / Decimal("100")
            weights = (
                {Symbol("SPY"): Decimal(".70"), Symbol("EFA"): Decimal(".30")}
                if risk_on
                else {
                    s: Decimal(1) / Decimal(3)
                    for s in (Symbol("IEF"), Symbol("TLT"), Symbol("GLD"))
                    if history[s][-1].close > self._ma(s, history, self._int("trend_window"))
                }
            )
        elif contract == "defensive-breadth-v1":
            broad = self._breadth(
                history, self._int("trend_window"), str(p.get("breadth_group", "risk-breadth"))
            ) >= self._decimal("breadth_threshold_percent") / Decimal("100")
            if broad:
                weights = {s: _STATIC_WEIGHTS[s.value] for s in self._group("static-core")}
            elif p.get("fallback") == "SHY":
                weights = {Symbol("SHY"): _ONE}
            elif p.get("fallback") == "cash":
                weights = {}
            else:
                fallback = self._group(str(p["fallback_group"]))
                scores = {
                    s: self._return(s, history, self._int("trend_window"))
                    for s in fallback
                    if self._return(s, history, self._int("trend_window")) > _ZERO
                }
                chosen = self._rank(scores, self._int("defensive_selection_count"))
                weights = {
                    s: _ONE / Decimal(self._int("defensive_selection_count")) for s in chosen
                }
        elif contract == "normalized-mean-reversion-v1":
            trend = self._int("trend_window")
            rev = self._int("reversal_lookback")
            scores = {}
            for symbol in group:
                volatility = self._vol(symbol, history, self._int("volatility_window"))
                reversal = self._return(symbol, history, rev)
                if (
                    volatility > _ZERO
                    and history[symbol][-1].close > self._ma(symbol, history, trend)
                    and reversal < _ZERO
                ):
                    scores[symbol] = reversal / volatility
            chosen = self._rank(scores, select, lowest=True)
            weights = {s: _ONE / Decimal(select) for s in chosen}
        elif contract == "core-satellite-v1":
            core = self._decimal("core_weight_percent") / Decimal("100")
            weights = {
                s: _STATIC_WEIGHTS[s.value] * core for s in self._group(str(p["core_group"]))
            }
            sat_value = p["satellite"]
            sat = self._symbols(sat_value, "satellite")
            scores = {
                s: self._return(s, history, self._int("tactical_lookback"))
                for s in sat
                if self._return(s, history, self._int("tactical_lookback")) > _ZERO
            }
            chosen = self._rank(scores, select)
            weights.update({s: (_ONE - core) / Decimal(select) for s in chosen})
        elif contract == "signal-consensus-v1":
            momentum = self._int("momentum_lookback")
            trend = self._int("trend_window")
            broad = self._breadth(history, trend, str(p["breadth_group"])) >= self._decimal(
                "breadth_threshold_percent"
            ) / Decimal("100")
            scores = {
                s: self._return(s, history, momentum)
                for s in group
                if (self._return(s, history, momentum) > _ZERO)
                + (history[s][-1].close > self._ma(s, history, trend))
                + broad
                >= self._int("minimum_votes", 2)
            }
            chosen = self._rank(scores, select)
            weights = {s: _ONE / Decimal(select) for s in chosen}
        else:
            raise AssertionError(contract)
        return self._targets(weights, contract)

    def _trend_state(
        self,
        count: int,
        timestamp: datetime,
        history: Mapping[Symbol, Sequence[OHLCVBar]],
        group: tuple[Symbol, ...],
    ) -> Sequence[TargetPosition]:
        window = self._int("window")
        inverse = self._contract().endswith("inverse-volatility-v1")
        if count < window or (inverse and count <= max(window, self._int("volatility_window", 63))):
            return ()
        active = frozenset(s for s in group if history[s][-1].close > self._ma(s, history, window))
        weights = (
            self._iv(
                tuple(active),
                history,
                self._int("volatility_window", 63),
                self._decimal("cap", Decimal(".25")),
            )
            if inverse
            else {s: _ONE / Decimal(len(group)) for s in active}
        )
        return self._state_targets(timestamp, active, weights)

    def _breakout(
        self,
        count: int,
        timestamp: datetime,
        history: Mapping[Symbol, Sequence[OHLCVBar]],
        group: tuple[Symbol, ...],
    ) -> Sequence[TargetPosition]:
        entry = self._int("entry_window")
        exit_ = self._int("exit_window")
        inverse = self._contract().endswith("inverse-volatility-v1")
        if count <= max(entry, self._int("volatility_window", 63) if inverse else entry):
            return ()
        active = set(self._observed_active or ())
        for s in group:
            close = history[s][-1].close
            if s in active:
                if close < min(bar.low for bar in history[s][-exit_ - 1 : -1]):
                    active.remove(s)
            elif close > max(bar.high for bar in history[s][-entry - 1 : -1]):
                active.add(s)
        next_active = frozenset(active)
        weights = (
            self._iv(
                tuple(next_active),
                history,
                self._int("volatility_window", 63),
                self._decimal("cap", Decimal(".25")),
            )
            if inverse
            else {s: _ONE / Decimal(len(group)) for s in next_active}
        )
        return self._state_targets(timestamp, next_active, weights)

    def _state_targets(
        self,
        timestamp: datetime,
        active: frozenset[Symbol],
        weights: Mapping[Symbol, Decimal],
    ) -> Sequence[TargetPosition]:
        previous = self._observed_active
        self._observed_active = active
        if self.evaluation_start is not None and timestamp < self.evaluation_start:
            return ()
        if self._evaluation_started and active == previous:
            return ()
        self._evaluation_started = True
        return self._targets(weights, self._contract())
