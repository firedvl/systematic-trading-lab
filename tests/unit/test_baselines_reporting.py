from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from systematic_trading_lab.domain import OHLCVBar, Symbol
from systematic_trading_lab.reporting import (
    benchmark_suite,
    build_report,
    report_json,
    strategy_result,
    write_report,
)
from systematic_trading_lab.strategies import (
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


def test_baselines_emit_targets_only_when_their_data_is_ready() -> None:
    symbol = Symbol("SPY")
    bars = tuple(
        OHLCVBar(
            symbol,
            datetime(2025, 1, 6, tzinfo=UTC) + timedelta(days=index),
            Decimal(str(price)),
            Decimal(str(price + 2)),
            Decimal(str(price - 2)),
            Decimal(str(price + 1)),
            100,
        )
        for index, price in enumerate((100, 101, 102, 103))
    )
    fixed = FixedWeightStrategy((symbol,), rebalance_every=2)
    assert fixed.on_bar(bars[0], (bars[0],))[0].weight == Decimal("1")
    assert fixed.on_bar(bars[1], bars[:2]) == ()
    assert fixed.on_bar(bars[2], bars[:3])[0].reason == "periodic-rebalance"
    assert MovingAverageTrendStrategy(window=3).on_bar(bars[1], bars[:2]) == ()
    assert MovingAverageTrendStrategy(window=3).on_bar(bars[2], bars[:3])[0].weight == Decimal("1")
    assert MeanReversionStrategy(window=3).on_bar(bars[1], bars[:2]) == ()
    assert TimeSeriesMomentumStrategy(lookback=2).on_bar(bars[1], bars[:2]) == ()
    assert TimeSeriesMomentumStrategy(lookback=2).on_bar(bars[2], bars)[0].weight == Decimal("1")
    assert VolatilityTargetedExposureStrategy(volatility_window=2).on_bar(bars[1], bars[:2]) == ()


def test_mean_reversion_and_volatility_targeted_baselines_are_bounded() -> None:
    symbol = Symbol("SPY")
    start = datetime(2025, 1, 6, tzinfo=UTC)

    def history(closes: tuple[str, ...]) -> tuple[OHLCVBar, ...]:
        return tuple(
            OHLCVBar(
                symbol,
                start + timedelta(days=index),
                Decimal(close),
                Decimal(close),
                Decimal(close),
                Decimal(close),
                100,
            )
            for index, close in enumerate(closes)
        )

    falling = history(("100", "90"))
    rising = history(("90", "100"))
    mean_reversion = MeanReversionStrategy(window=2)
    assert mean_reversion.on_bar(falling[-1], falling)[0].weight == Decimal("1")
    assert mean_reversion.on_bar(rising[-1], rising)[0].weight == Decimal("0")

    low_volatility = history(("100", "101", "100.5"))
    high_volatility = history(("100", "110", "90"))
    volatility_targeted = VolatilityTargetedExposureStrategy(volatility_window=2)
    low_weight = volatility_targeted.on_bar(low_volatility[-1], low_volatility)[0].weight
    high_weight = volatility_targeted.on_bar(high_volatility[-1], high_volatility)[0].weight
    assert Decimal("0") < high_weight < low_weight <= Decimal("1")

    with pytest.raises(ValueError, match="positive volatility"):
        constant_returns = history(("100", "110", "121"))
        volatility_targeted.on_bar(constant_returns[-1], constant_returns)


def test_new_baseline_reports_are_deterministic_and_unlevered() -> None:
    start = datetime(2025, 1, 6, tzinfo=UTC)
    bars = tuple(
        OHLCVBar(
            Symbol(symbol),
            start + timedelta(days=index),
            Decimal(str(price)),
            Decimal(str(price)),
            Decimal(str(price)),
            Decimal(str(price)),
            100,
        )
        for symbol, prices in (("QQQ", (100, 103, 101, 104)), ("SPY", (100, 101, 100, 102)))
        for index, price in enumerate(prices)
    )

    for name, parameters in (
        ("mean-reversion", {"window": 2}),
        ("volatility-targeted", {"volatility_window": 2}),
    ):
        first = strategy_result(name, bars, Decimal("1000"), parameters=parameters)
        second = strategy_result(name, bars, Decimal("1000"), parameters=parameters)
        assert first.artifact_fingerprint == second.artifact_fingerprint
        assert first.metrics.max_gross_exposure <= Decimal("1")


def test_benchmark_report_is_deterministic_and_immutable(tmp_path: Path) -> None:
    symbol = Symbol("SPY")
    bars = tuple(
        OHLCVBar(
            symbol,
            datetime(2025, 1, 6, tzinfo=UTC) + timedelta(days=index),
            Decimal("100"),
            Decimal("105"),
            Decimal("95"),
            Decimal(str(100 + index)),
            100,
        )
        for index in range(3)
    )
    results = benchmark_suite(bars, Decimal("1000"))
    assert {
        "cash",
        "buy-and-hold:SPY",
        "fixed-weight",
        "moving-average",
        "mean-reversion",
        "momentum",
        "volatility-targeted",
    } == results.keys()
    report = build_report(results)
    comparisons = report["comparisons"]
    assert isinstance(comparisons, dict)
    assert comparisons["cash"] == {"excess_return_vs_cash": Decimal("0")}
    assert report_json(results) == report_json(results)
    output = tmp_path / "report.json"
    write_report(output, results)
    with pytest.raises(FileExistsError):
        write_report(output, results)


def test_trend_baselines_split_exposure_across_the_dataset_symbols() -> None:
    start = datetime(2025, 1, 6, tzinfo=UTC)
    bars = tuple(
        OHLCVBar(
            Symbol(symbol),
            start + timedelta(days=index),
            Decimal(str(100 + index)),
            Decimal(str(102 + index)),
            Decimal(str(99 + index)),
            Decimal(str(101 + index)),
            100,
        )
        for symbol in ("QQQ", "SPY")
        for index in range(3)
    )

    for strategy, parameters in (
        ("moving-average", {"window": 2}),
        ("momentum", {"lookback": 1}),
    ):
        result = strategy_result(strategy, bars, Decimal("1000"), parameters=parameters)
        active_weights = {
            target.weight
            for decision in result.decisions
            for target in decision.targets
            if target.weight > 0
        }
        assert active_weights == {Decimal("0.5")}


def test_relative_strength_uses_positive_ranked_assets_on_rebalance_sessions() -> None:
    symbols = tuple(Symbol(value) for value in ("QQQ", "SPY", "TLT"))
    start = datetime(2025, 1, 6, tzinfo=UTC)
    closes = {
        Symbol("QQQ"): (Decimal("100"), Decimal("110"), Decimal("120"), Decimal("121")),
        Symbol("SPY"): (Decimal("100"), Decimal("105"), Decimal("110"), Decimal("111")),
        Symbol("TLT"): (Decimal("100"), Decimal("95"), Decimal("90"), Decimal("89")),
    }
    history = {
        symbol: tuple(
            OHLCVBar(
                symbol,
                start + timedelta(days=index),
                close,
                close,
                close,
                close,
                100,
            )
            for index, close in enumerate(values)
        )
        for symbol, values in closes.items()
    }
    strategy = RelativeStrengthPortfolioStrategy(
        symbols, lookback=2, rebalance_every=2, selection_count=2
    )

    assert (
        strategy.on_session(
            tuple(values[1] for values in history.values()),
            {symbol: values[:2] for symbol, values in history.items()},
        )
        == ()
    )
    targets = strategy.on_session(
        tuple(values[2] for values in history.values()),
        {symbol: values[:3] for symbol, values in history.items()},
    )
    assert {target.symbol: target.weight for target in targets} == {
        Symbol("QQQ"): Decimal("0.5"),
        Symbol("SPY"): Decimal("0.5"),
        Symbol("TLT"): Decimal("0"),
    }
    assert strategy.on_session(tuple(values[3] for values in history.values()), history) == ()


def test_relative_strength_reporting_uses_session_portfolio_engine() -> None:
    start = datetime(2025, 1, 6, tzinfo=UTC)
    source = tuple(
        OHLCVBar(
            Symbol(symbol),
            start + timedelta(days=day),
            Decimal(str(100 + day)),
            Decimal(str(104 + day)),
            Decimal(str(99 + day)),
            Decimal(str(101 + day + (2 if symbol == "QQQ" else 0))),
            100,
        )
        for day in range(5)
        for symbol in ("GLD", "IWM", "QQQ", "SPY", "TLT")
    )

    result = strategy_result(
        "relative-strength",
        source,
        Decimal("1000"),
        parameters={"lookback": 2, "rebalance_every": 1, "selection_count": 1},
    )

    assert result.strategy_id == "relative-strength-portfolio"
    assert len(result.decisions) == 5
    assert result.metrics.trade_count > 0

    risk_managed = strategy_result(
        "risk-managed-momentum",
        source,
        Decimal("1000"),
        parameters={"lookback": 2, "volatility_window": 2, "rebalance_every": 1},
    )
    assert risk_managed.strategy_id == "risk-managed-momentum-portfolio"
    assert risk_managed.metrics.trade_count > 0

    volatility_balanced = strategy_result(
        "volatility-balanced",
        source,
        Decimal("1000"),
        parameters={"volatility_window": 2, "rebalance_every": 1},
    )
    assert volatility_balanced.strategy_id == "volatility-balanced-portfolio"
    assert volatility_balanced.metrics.trade_count > 0


def test_risk_managed_momentum_caps_inverse_volatility_weights() -> None:
    symbols = tuple(Symbol(value) for value in ("QQQ", "SPY", "TLT"))
    start = datetime(2025, 1, 6, tzinfo=UTC)
    closes = {
        Symbol("QQQ"): (Decimal("100"), Decimal("105"), Decimal("115")),
        Symbol("SPY"): (Decimal("100"), Decimal("102"), Decimal("104")),
        Symbol("TLT"): (Decimal("100"), Decimal("99"), Decimal("98")),
    }
    history = {
        symbol: tuple(
            OHLCVBar(
                symbol,
                start + timedelta(days=index),
                close,
                close,
                close,
                close,
                100,
            )
            for index, close in enumerate(values)
        )
        for symbol, values in closes.items()
    }
    strategy = RiskManagedMomentumPortfolioStrategy(
        symbols, lookback=2, volatility_window=2, rebalance_every=1
    )

    assert (
        strategy.on_session(
            tuple(values[1] for values in history.values()),
            {symbol: values[:2] for symbol, values in history.items()},
        )
        == ()
    )
    targets = strategy.on_session(tuple(values[-1] for values in history.values()), history)
    weights = {target.symbol: target.weight for target in targets}
    assert weights[Symbol("SPY")] == Decimal("0.4")
    assert weights[Symbol("QQQ")] == Decimal("0.4")
    assert weights[Symbol("TLT")] == Decimal("0")
    assert sum(weights.values(), Decimal("0")) == Decimal("0.8")


def test_risk_managed_momentum_rejects_zero_volatility() -> None:
    symbol = Symbol("SPY")
    start = datetime(2025, 1, 6, tzinfo=UTC)
    history = tuple(
        OHLCVBar(symbol, start + timedelta(days=index), close, close, close, close, 100)
        for index, close in enumerate(map(Decimal, ("100", "110", "121")))
    )
    strategy = RiskManagedMomentumPortfolioStrategy(
        (symbol,), lookback=2, volatility_window=2, rebalance_every=1
    )

    with pytest.raises(ValueError, match="positive volatility"):
        strategy.on_session((history[-1],), {symbol: history})


def test_volatility_balanced_caps_and_fully_allocates() -> None:
    symbols = tuple(Symbol(value) for value in ("GLD", "IWM", "QQQ", "SPY", "TLT"))
    start = datetime(2025, 1, 6, tzinfo=UTC)
    closes = (
        ("100", "101", "103"),
        ("100", "102", "105"),
        ("100", "105", "106"),
        ("100", "101", "104"),
        ("100", "104", "110"),
    )
    history = {
        symbol: tuple(
            OHLCVBar(symbol, start + timedelta(days=index), close, close, close, close, 100)
            for index, close in enumerate(map(Decimal, values))
        )
        for symbol, values in zip(symbols, closes, strict=True)
    }
    strategy = VolatilityBalancedPortfolioStrategy(symbols, volatility_window=2, rebalance_every=1)

    assert (
        strategy.on_session(
            tuple(values[1] for values in history.values()),
            {symbol: values[:2] for symbol, values in history.items()},
        )
        == ()
    )
    targets = strategy.on_session(tuple(values[-1] for values in history.values()), history)
    weights = {target.symbol: target.weight for target in targets}
    assert max(weights.values()) == Decimal("0.3")
    assert min(weights.values()) > Decimal("0")
    assert sum(weights.values(), Decimal("0")) == Decimal("1")
    assert {target.reason for target in targets} == {"capped-inverse-volatility"}


@pytest.mark.parametrize(
    ("lookback", "rebalance_every", "selection_count"),
    (
        (0, 1, 2),
        (2, 0, 2),
        (2, 1, 4),
    ),
)
def test_relative_strength_rejects_invalid_parameters(
    lookback: int, rebalance_every: int, selection_count: int
) -> None:
    with pytest.raises(ValueError):
        RelativeStrengthPortfolioStrategy(
            (Symbol("QQQ"), Symbol("SPY"), Symbol("TLT")),
            lookback=lookback,
            rebalance_every=rebalance_every,
            selection_count=selection_count,
        )


@pytest.mark.parametrize(
    ("lookback", "volatility_window", "rebalance_every"),
    ((0, 2, 1), (2, 1, 1), (2, 2, 0)),
)
def test_risk_managed_momentum_rejects_invalid_parameters(
    lookback: int, volatility_window: int, rebalance_every: int
) -> None:
    with pytest.raises(ValueError):
        RiskManagedMomentumPortfolioStrategy(
            (Symbol("QQQ"), Symbol("SPY")),
            lookback=lookback,
            volatility_window=volatility_window,
            rebalance_every=rebalance_every,
        )


@pytest.mark.parametrize(
    ("volatility_window", "rebalance_every"),
    ((1, 1), (2, 0)),
)
def test_volatility_balanced_rejects_invalid_parameters(
    volatility_window: int, rebalance_every: int
) -> None:
    with pytest.raises(ValueError):
        VolatilityBalancedPortfolioStrategy(
            tuple(Symbol(value) for value in ("GLD", "IWM", "QQQ", "SPY")),
            volatility_window=volatility_window,
            rebalance_every=rebalance_every,
        )


def test_volatility_balanced_rejects_underdiversified_universe() -> None:
    with pytest.raises(ValueError, match="at least four unique symbols"):
        VolatilityBalancedPortfolioStrategy(tuple(Symbol(value) for value in ("QQQ", "SPY", "TLT")))


def test_strategic_allocation_uses_fixed_diversified_weights() -> None:
    symbols = tuple(Symbol(value) for value in ("GLD", "IWM", "QQQ", "SPY", "TLT"))
    start = datetime(2025, 1, 6, tzinfo=UTC)
    history = {
        symbol: (
            OHLCVBar(
                symbol,
                start,
                Decimal("100"),
                Decimal("100"),
                Decimal("100"),
                Decimal("100"),
                100,
            ),
        )
        for symbol in symbols
    }
    strategy = StrategicAllocationPortfolioStrategy(symbols, rebalance_every=21)

    targets = strategy.on_session(tuple(values[0] for values in history.values()), history)

    assert {target.symbol.value: target.weight for target in targets} == {
        "GLD": Decimal("0.15"),
        "IWM": Decimal("0.25"),
        "QQQ": Decimal("0.25"),
        "SPY": Decimal("0.35"),
        "TLT": Decimal("0"),
    }
    result = strategy_result(
        "strategic-allocation",
        tuple(values[0] for values in history.values()),
        Decimal("1000"),
        parameters={"rebalance_every": 21},
    )
    assert result.strategy_id == "strategic-allocation-portfolio"
    with pytest.raises(ValueError, match="fixed ETF universe"):
        StrategicAllocationPortfolioStrategy(symbols[:-1])
