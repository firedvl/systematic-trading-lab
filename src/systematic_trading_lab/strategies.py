"""Baseline strategies that emit targets, never broker orders."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from .domain import OHLCVBar, Symbol


@dataclass(frozen=True)
class TargetPosition:
    symbol: Symbol
    weight: Decimal
    reason: str


class CashStrategy:
    strategy_id = "cash"
    version = "1"

    def on_bar(self, bar: OHLCVBar, history: Sequence[OHLCVBar]) -> Sequence[TargetPosition]:
        return ()


@dataclass
class BuyAndHoldStrategy:
    strategy_id: str = "buy-and-hold"
    version: str = "1"
    _seen: set[Symbol] = field(default_factory=set, init=False, repr=False)

    def on_bar(self, bar: OHLCVBar, history: Sequence[OHLCVBar]) -> Sequence[TargetPosition]:
        if bar.symbol in self._seen:
            return ()
        self._seen.add(bar.symbol)
        return (TargetPosition(bar.symbol, Decimal("1"), "initial-entry"),)
