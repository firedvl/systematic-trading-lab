# Strategy development

A daily strategy receives completed bars and returns target positions. It never creates broker orders, reads credentials, or writes an execution registry.

## Interface

Per-symbol strategies satisfy `backtesting.Strategy`:

```python
class Strategy(Protocol):
    @property
    def strategy_id(self) -> str: ...

    @property
    def version(self) -> str: ...

    def on_bar(
        self,
        bar: OHLCVBar,
        history: Sequence[OHLCVBar],
    ) -> Sequence[TargetPosition]: ...
```

Portfolio strategies satisfy `backtesting.PortfolioStrategy` and receive one complete timestamp slice plus immutable per-symbol history. Use that interface when a decision compares or allocates across symbols.

## Add a strategy

1. Add the strategy class to `src/systematic_trading_lab/rapid_strategies.py`. Keep it target-only. Do not edit `strategies.py`; its exact bytes belong to the frozen V2 source surface.
2. Import the class in `src/systematic_trading_lab/strategy_registry.py`.
3. Add one `StrategyDefinition` to the public `STRATEGIES` mapping.
4. Declare each integer parameter with a default and minimum.
5. Add a focused unit test for warmup, signal, and parameter failure behavior.
6. Run it through `trading-lab research`.

Example class:

```python
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from .domain import OHLCVBar
from .strategies import TargetPosition


@dataclass(frozen=True)
class BreakoutStrategy:
    lookback: int = 20
    strategy_id: str = "close-breakout"
    version: str = "1"

    def __post_init__(self) -> None:
        if self.lookback < 1:
            raise ValueError("breakout lookback must be positive")

    def on_bar(
        self,
        bar: OHLCVBar,
        history: Sequence[OHLCVBar],
    ) -> Sequence[TargetPosition]:
        if len(history) <= self.lookback:
            return ()
        prior_high = max(item.high for item in history[-self.lookback - 1 : -1])
        weight = Decimal("1") if bar.close > prior_high else Decimal("0")
        return (TargetPosition(bar.symbol, weight, "close-breakout"),)
```

Registry entry:

```python
"breakout": StrategyDefinition(
    "breakout",
    "close-breakout",
    "breakout",
    "Hold when the close exceeds the prior trailing high.",
    (StrategyParameter("lookback", 20),),
    lambda _symbols, parameters: BreakoutStrategy(
        lookback=parameters["lookback"],
    ),
),
```

The registry rejects unknown parameters, booleans, non-integers, and values below the declared minimum before simulation.

## Test it

Keep the test small and deterministic:

```python
def test_breakout_waits_for_completed_history() -> None:
    strategy = BreakoutStrategy(lookback=2)
    first, second, breakout = bars()

    assert strategy.on_bar(first, (first,)) == ()
    assert strategy.on_bar(second, (first, second)) == ()
    assert strategy.on_bar(breakout, (first, second, breakout))[0].weight == Decimal("1")
```

Then run the shared checks:

```console
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
```

## Run it

```console
uv run trading-lab research list-strategies
uv run trading-lab research backtest \
  --dataset DATASET_ID \
  --strategy breakout \
  --parameter lookback=20
```

Do not add campaign IDs, qualification calls, paper intents, or broker code to a strategy. Promotion starts only after separate review of a zero-authority candidate export.
