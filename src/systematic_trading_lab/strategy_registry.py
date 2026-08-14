"""Public strategy registry for ordinary daily research."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import cast

from .backtesting import (
    BacktestEngine,
    BacktestResult,
    CostModel,
    PortfolioStrategy,
    Strategy,
)
from .domain import OHLCVBar, Symbol
from .rapid_strategies import (
    ChannelBreakoutPortfolioStrategy,
    MovingAverageStatePortfolioStrategy,
    StartBoundPortfolioStrategy,
    StartBoundStrategy,
    TrendPullbackPortfolioStrategy,
)
from .strategies import (
    BuyAndHoldStrategy,
    CashStrategy,
    FixedWeightStrategy,
    MeanReversionStrategy,
    MovingAverageTrendStrategy,
    RelativeStrengthPortfolioStrategy,
    RiskManagedMomentumPortfolioStrategy,
    StrategicAllocationPortfolioStrategy,
    TimeSeriesMomentumStrategy,
    VolatilityBalancedPortfolioStrategy,
    VolatilityTargetedExposureStrategy,
)


@dataclass(frozen=True)
class StrategyParameter:
    name: str
    default: int
    minimum: int = 1


StrategyFactory = Callable[[tuple[Symbol, ...], Mapping[str, int]], object]


@dataclass(frozen=True)
class StrategyDefinition:
    name: str
    strategy_id: str
    family: str
    description: str
    parameters: tuple[StrategyParameter, ...]
    factory: StrategyFactory
    portfolio: bool = False


def _parameter(parameters: Mapping[str, int], name: str) -> int:
    return parameters[name]


STRATEGIES: dict[str, StrategyDefinition] = {
    "cash": StrategyDefinition(
        "cash", "cash", "baseline", "Hold cash.", (), lambda _symbols, _parameters: CashStrategy()
    ),
    "buy-and-hold": StrategyDefinition(
        "buy-and-hold",
        "buy-and-hold",
        "baseline",
        "Buy the first symbol and hold it.",
        (),
        lambda _symbols, _parameters: BuyAndHoldStrategy(),
    ),
    "fixed-weight": StrategyDefinition(
        "fixed-weight",
        "fixed-weight",
        "allocation",
        "Rebalance equal weights every five sessions.",
        (),
        lambda symbols, _parameters: FixedWeightStrategy(symbols),
    ),
    "moving-average": StrategyDefinition(
        "moving-average",
        "moving-average-trend",
        "trend",
        "Hold assets whose close is above a trailing moving average.",
        (StrategyParameter("window", 20, 2),),
        lambda symbols, parameters: MovingAverageTrendStrategy(
            window=_parameter(parameters, "window"),
            target_weight=Decimal("1") / Decimal(len(symbols)),
        ),
    ),
    "moving-average-state": StrategyDefinition(
        "moving-average-state",
        "moving-average-state-portfolio",
        "trend",
        "Change fixed sleeves only when their moving-average state changes.",
        (StrategyParameter("window", 40, 2),),
        lambda symbols, parameters: MovingAverageStatePortfolioStrategy(
            symbols, window=_parameter(parameters, "window")
        ),
        portfolio=True,
    ),
    "mean-reversion": StrategyDefinition(
        "mean-reversion",
        "moving-average-mean-reversion",
        "mean-reversion",
        "Hold assets whose close is below a trailing moving average.",
        (StrategyParameter("window", 20, 2),),
        lambda symbols, parameters: MeanReversionStrategy(
            window=_parameter(parameters, "window"),
            target_weight=Decimal("1") / Decimal(len(symbols)),
        ),
    ),
    "momentum": StrategyDefinition(
        "momentum",
        "time-series-momentum",
        "momentum",
        "Hold assets with a positive trailing return.",
        (StrategyParameter("lookback", 20),),
        lambda symbols, parameters: TimeSeriesMomentumStrategy(
            lookback=_parameter(parameters, "lookback"),
            target_weight=Decimal("1") / Decimal(len(symbols)),
        ),
    ),
    "trend-pullback": StrategyDefinition(
        "trend-pullback",
        "trend-pullback-portfolio",
        "mean-reversion",
        "Buy short pullbacks inside longer uptrends and exit on recovery.",
        (
            StrategyParameter("trend_window", 63, 2),
            StrategyParameter("pullback_window", 5, 2),
        ),
        lambda symbols, parameters: TrendPullbackPortfolioStrategy(
            symbols,
            trend_window=_parameter(parameters, "trend_window"),
            pullback_window=_parameter(parameters, "pullback_window"),
        ),
        portfolio=True,
    ),
    "channel-breakout": StrategyDefinition(
        "channel-breakout",
        "channel-breakout-portfolio",
        "breakout",
        "Enter above prior highs and exit below prior lows.",
        (
            StrategyParameter("entry_window", 20, 2),
            StrategyParameter("exit_window", 10),
        ),
        lambda symbols, parameters: ChannelBreakoutPortfolioStrategy(
            symbols,
            entry_window=_parameter(parameters, "entry_window"),
            exit_window=_parameter(parameters, "exit_window"),
        ),
        portfolio=True,
    ),
    "relative-strength": StrategyDefinition(
        "relative-strength",
        "relative-strength-portfolio",
        "portfolio-momentum",
        "Allocate to the strongest assets with positive momentum.",
        (
            StrategyParameter("lookback", 126),
            StrategyParameter("rebalance_every", 21),
            StrategyParameter("selection_count", 3),
        ),
        lambda symbols, parameters: RelativeStrengthPortfolioStrategy(
            symbols,
            lookback=_parameter(parameters, "lookback"),
            rebalance_every=_parameter(parameters, "rebalance_every"),
            selection_count=_parameter(parameters, "selection_count"),
        ),
        portfolio=True,
    ),
    "risk-managed-momentum": StrategyDefinition(
        "risk-managed-momentum",
        "risk-managed-momentum-portfolio",
        "portfolio-momentum",
        "Weight positive-momentum assets by inverse volatility.",
        (
            StrategyParameter("lookback", 126),
            StrategyParameter("volatility_window", 63, 2),
            StrategyParameter("rebalance_every", 5),
        ),
        lambda symbols, parameters: RiskManagedMomentumPortfolioStrategy(
            symbols,
            lookback=_parameter(parameters, "lookback"),
            volatility_window=_parameter(parameters, "volatility_window"),
            rebalance_every=_parameter(parameters, "rebalance_every"),
        ),
        portfolio=True,
    ),
    "strategic-allocation": StrategyDefinition(
        "strategic-allocation",
        "strategic-allocation-portfolio",
        "portfolio-allocation",
        "Use the fixed strategic ETF allocation.",
        (StrategyParameter("rebalance_every", 21),),
        lambda symbols, parameters: StrategicAllocationPortfolioStrategy(
            symbols, rebalance_every=_parameter(parameters, "rebalance_every")
        ),
        portfolio=True,
    ),
    "volatility-balanced": StrategyDefinition(
        "volatility-balanced",
        "volatility-balanced-portfolio",
        "portfolio-allocation",
        "Allocate with capped inverse-volatility weights.",
        (
            StrategyParameter("volatility_window", 63, 2),
            StrategyParameter("rebalance_every", 5),
        ),
        lambda symbols, parameters: VolatilityBalancedPortfolioStrategy(
            symbols,
            volatility_window=_parameter(parameters, "volatility_window"),
            rebalance_every=_parameter(parameters, "rebalance_every"),
        ),
        portfolio=True,
    ),
    "volatility-targeted": StrategyDefinition(
        "volatility-targeted",
        "volatility-targeted-exposure",
        "volatility",
        "Scale long exposure toward a fixed volatility target.",
        (StrategyParameter("volatility_window", 20, 2),),
        lambda symbols, parameters: VolatilityTargetedExposureStrategy(
            volatility_window=_parameter(parameters, "volatility_window"),
            maximum_weight=Decimal("1") / Decimal(len(symbols)),
        ),
    ),
}

_ALIASES = {definition.strategy_id: name for name, definition in STRATEGIES.items()} | {
    "relative-strength-portfolio": "relative-strength",
    "risk-managed-momentum-portfolio": "risk-managed-momentum",
    "strategic-allocation-portfolio": "strategic-allocation",
    "volatility-balanced-portfolio": "volatility-balanced",
}


def strategy_names() -> tuple[str, ...]:
    return tuple(STRATEGIES)


def get_strategy_definition(name: str) -> StrategyDefinition:
    canonical_name = _ALIASES.get(name, name)
    try:
        return STRATEGIES[canonical_name]
    except KeyError as error:
        raise ValueError(f"unknown backtest strategy: {name}") from error


def validate_strategy_parameters(name: str, parameters: Mapping[str, object]) -> dict[str, int]:
    definition = get_strategy_definition(name)
    specifications = {parameter.name: parameter for parameter in definition.parameters}
    unknown = parameters.keys() - specifications.keys()
    if unknown:
        raise ValueError(
            f"unsupported parameters for {definition.name}: {', '.join(sorted(unknown))}"
        )
    validated: dict[str, int] = {}
    for parameter in definition.parameters:
        value = parameters.get(parameter.name, parameter.default)
        if isinstance(value, bool) or not isinstance(value, int) or value < parameter.minimum:
            if parameter.minimum == 1:
                raise ValueError(f"{parameter.name} must be a positive integer")
            raise ValueError(f"{parameter.name} must be at least {parameter.minimum}")
        validated[parameter.name] = value
    return validated


def run_registered_strategy(
    name: str,
    bars: Sequence[OHLCVBar],
    initial_cash: Decimal,
    cost_model: CostModel | None = None,
    parameters: Mapping[str, object] | None = None,
    fill_delay_bars: int = 1,
    trade_start: datetime | None = None,
) -> BacktestResult:
    definition = get_strategy_definition(name)
    validated = validate_strategy_parameters(name, parameters or {})
    symbols = tuple(sorted({bar.symbol for bar in bars}, key=lambda symbol: symbol.value))
    selected_bars = tuple(bars)
    if definition.name == "buy-and-hold":
        if not symbols:
            raise ValueError("buy-and-hold requires at least one symbol")
        selected_bars = tuple(bar for bar in bars if bar.symbol == symbols[0])
        symbols = (symbols[0],)
    if not symbols:
        raise ValueError("strategy requires at least one symbol")
    built = definition.factory(symbols, validated)
    engine = BacktestEngine(initial_cash, cost_model, fill_delay_bars)
    if definition.portfolio:
        portfolio = cast(PortfolioStrategy, built)
        if trade_start is not None:
            portfolio = StartBoundPortfolioStrategy(portfolio, trade_start)
        return engine.run_portfolio(selected_bars, portfolio)
    strategy = cast(Strategy, built)
    if trade_start is not None:
        strategy = StartBoundStrategy(strategy, trade_start)
    return engine.run(selected_bars, strategy)
