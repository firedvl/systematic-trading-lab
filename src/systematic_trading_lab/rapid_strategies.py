"""Rapid-only strategy implementations and evaluation wrappers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from .backtesting import PortfolioStrategy, Strategy
from .domain import OHLCVBar, Symbol
from .strategies import TargetPosition


@dataclass
class StartBoundStrategy:
    strategy: Strategy
    start: datetime

    @property
    def strategy_id(self) -> str:
        return self.strategy.strategy_id

    @property
    def version(self) -> str:
        return self.strategy.version

    def on_bar(self, bar: OHLCVBar, history: Sequence[OHLCVBar]) -> Sequence[TargetPosition]:
        return () if bar.timestamp < self.start else self.strategy.on_bar(bar, history)


@dataclass
class StartBoundPortfolioStrategy:
    strategy: PortfolioStrategy
    start: datetime

    @property
    def strategy_id(self) -> str:
        return self.strategy.strategy_id

    @property
    def version(self) -> str:
        return self.strategy.version

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        return () if bars[0].timestamp < self.start else self.strategy.on_session(bars, history)
