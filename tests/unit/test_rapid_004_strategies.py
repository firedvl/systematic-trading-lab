from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from systematic_trading_lab.backtesting import BacktestEngine, CostModel
from systematic_trading_lab.domain import OHLCVBar, Symbol
from systematic_trading_lab.rapid_004_strategies import build_rapid_004_portfolio_strategy

_NAMES = ("AGG", "DBC", "EEM", "EFA", "GLD", "IEF", "LQD", "QQQ", "SHY", "SPY", "TIP", "TLT", "VNQ")
_SYMBOLS = tuple(Symbol(name) for name in _NAMES)
_BY_NAME = {symbol.value: symbol for symbol in _SYMBOLS}
_GROUPS = {
    "all": _SYMBOLS,
    "risk-breadth": tuple(_BY_NAME[name] for name in ("SPY", "QQQ", "EEM")),
    "defensive": tuple(_BY_NAME[name] for name in ("SHY", "IEF", "TLT", "GLD")),
    "static-core": tuple(_BY_NAME[name] for name in ("SPY", "EFA", "AGG", "GLD")),
    "tactical-representatives": tuple(
        _BY_NAME[name] for name in ("SPY", "EFA", "EEM", "TLT", "LQD", "TIP", "GLD", "DBC", "VNQ")
    ),
}
_SLEEVES = {
    "equity": tuple(_BY_NAME[name] for name in ("SPY", "QQQ", "EEM")),
    "international": (_BY_NAME["EFA"],),
    "income": tuple(_BY_NAME[name] for name in ("AGG", "SHY", "IEF", "TLT", "LQD", "TIP")),
    "real": tuple(_BY_NAME[name] for name in ("GLD", "DBC", "VNQ")),
}


def _history() -> dict[Symbol, tuple[OHLCVBar, ...]]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    result: dict[Symbol, tuple[OHLCVBar, ...]] = {}
    for number, symbol in enumerate(_SYMBOLS, start=1):
        closes = [
            Decimal("100") + Decimal(number * day + day * day) / Decimal("10") for day in range(8)
        ]
        result[symbol] = tuple(
            OHLCVBar(symbol, start + timedelta(days=day), close, close + 1, close - 1, close, 1)
            for day, close in enumerate(closes)
        )
    return result


def _profile(contract: str) -> dict[str, object]:
    return {
        "contract": contract,
        "group": "all",
        "risk_group": "risk-breadth",
        "fallback_group": "defensive",
        "breadth_group": "risk-breadth",
        "allocation_group": "static-core",
        "core_group": "static-core",
        "satellite": tuple(_BY_NAME[name] for name in ("EEM", "TLT", "LQD", "TIP", "DBC", "VNQ")),
        "weighting": "inverse-volatility" if "inverse-volatility" in contract else "equal",
        "cap": Decimal("0.8"),
        "risk_cap": Decimal("0.8"),
        "fallback_cap": Decimal("0.8"),
        "defensive_selection_count": 2,
    }


def _parameters(contract: str) -> dict[str, object]:
    params: dict[str, object] = {"rebalance_every": 1, "selection_count": 2, "lookback": 2}
    if "multi-horizon" in contract or contract == "dual-momentum-v1":
        params.update(short_lookback=1, long_lookback=2)
    if "trend" in contract or "breadth" in contract or contract == "signal-consensus-v1":
        params.update(window=2, trend_window=2, rank_lookback=2, breadth_threshold_percent=1)
    if "volatility" in contract or contract in {
        "normalized-mean-reversion-v1",
        "equity-bond-gold-regime-v1",
    }:
        params["volatility_window"] = 2
    if "breakout" in contract:
        params.update(entry_window=3, exit_window=2, volatility_window=2)
    if contract == "equity-bond-gold-regime-v1":
        params.update(trend_window=2, volatility_limit_percent=100)
    if contract == "normalized-mean-reversion-v1":
        params.update(trend_window=2, reversal_lookback=1, volatility_window=2)
    if contract == "core-satellite-v1":
        params.update(core_weight_percent=80, tactical_lookback=2)
    if contract == "signal-consensus-v1":
        params.update(momentum_lookback=2, trend_window=2, breadth_threshold_percent=1)
    if contract == "fixed-weight-configured-v1":
        return {"rebalance_every": 1}
    return params


@pytest.mark.parametrize(
    "contract",
    (
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
    ),
)
def test_every_frozen_contract_expands_nonempty_targets_to_the_full_universe(contract: str) -> None:
    profile = _profile(contract)
    if contract == "fixed-weight-configured-v1":
        profile["group"] = "static-core"
    if contract == "signal-consensus-v1":
        profile["group"] = "tactical-representatives"
    strategy = build_rapid_004_portfolio_strategy(
        "case",
        _SYMBOLS,
        _GROUPS,
        _SLEEVES,
        {"case": profile},
        _parameters(contract),
        configured_weights={_BY_NAME["SPY"]: Decimal("0.4")}
        if contract == "fixed-weight-configured-v1"
        else None,
    )
    history = _history()
    targets = strategy.on_session(tuple(history[symbol][-1] for symbol in _SYMBOLS), history)
    assert len(targets) == len(_SYMBOLS)
    assert tuple(target.symbol for target in targets) == _SYMBOLS
    assert all(target.weight >= 0 for target in targets)
    assert sum((target.weight for target in targets), Decimal("0")) <= Decimal("1")


def test_ties_are_symbol_ascending_and_completed_close_is_required() -> None:
    profile = _profile("ranked-equal-v1")
    strategy = build_rapid_004_portfolio_strategy(
        "case",
        _SYMBOLS,
        _GROUPS,
        _SLEEVES,
        {"case": profile},
        {"lookback": 2, "selection_count": 1, "rebalance_every": 1},
    )
    history = _history()
    for symbol in _SYMBOLS:
        history[symbol] = history[symbol][:-1] + (
            history[symbol][-1].__class__(
                symbol,
                history[symbol][-1].timestamp,
                Decimal("110"),
                Decimal("111"),
                Decimal("109"),
                Decimal("110"),
                1,
            ),
        )
    targets = strategy.on_session(tuple(history[symbol][-1] for symbol in _SYMBOLS), history)
    assert next(target.symbol for target in targets if target.weight) == _SYMBOLS[0]
    bad = list(history[symbol][-1] for symbol in _SYMBOLS)
    bad[0] = OHLCVBar(
        _SYMBOLS[0],
        bad[0].timestamp,
        Decimal("111"),
        Decimal("112"),
        Decimal("110"),
        Decimal("111"),
        1,
    )
    with pytest.raises(ValueError, match="completed history"):
        strategy.on_session(bad, history)


def test_invalid_profile_group_and_weight_inputs_fail_closed() -> None:
    with pytest.raises(ValueError, match="unknown Rapid-004 strategy profile"):
        build_rapid_004_portfolio_strategy("missing", _SYMBOLS, _GROUPS, _SLEEVES, {}, {})
    with pytest.raises(ValueError, match="configured fixed weights are invalid"):
        build_rapid_004_portfolio_strategy(
            "case",
            _SYMBOLS,
            _GROUPS,
            _SLEEVES,
            {"case": {"contract": "fixed-weight-configured-v1", "group": "static-core"}},
            {"rebalance_every": 1},
            configured_weights={_BY_NAME["SPY"]: Decimal("1.1")},
        )


def test_cap_cash_residual_fallback_and_state_change() -> None:
    profile = _profile("ranked-inverse-volatility-v1")
    profile["cap"] = Decimal("0.4")
    inverse = build_rapid_004_portfolio_strategy(
        "case",
        _SYMBOLS,
        _GROUPS,
        _SLEEVES,
        {"case": profile},
        {"lookback": 2, "selection_count": 1, "volatility_window": 2, "rebalance_every": 1},
    )
    history = _history()
    targets = inverse.on_session(tuple(history[symbol][-1] for symbol in _SYMBOLS), history)
    assert sum((target.weight for target in targets), Decimal("0")) == Decimal("0.4")

    fallback_profile = _profile("dual-momentum-v1")
    fallback_profile["fallback"] = ("SHY",)
    fallback = build_rapid_004_portfolio_strategy(
        "case",
        _SYMBOLS,
        _GROUPS,
        _SLEEVES,
        {"case": fallback_profile},
        {"short_lookback": 1, "long_lookback": 2, "selection_count": 1, "rebalance_every": 1},
    )
    for symbol in _GROUPS["risk-breadth"]:
        bars = history[symbol]
        history[symbol] = bars[:-1] + (
            OHLCVBar(
                symbol,
                bars[-1].timestamp,
                Decimal("90"),
                Decimal("91"),
                Decimal("89"),
                Decimal("90"),
                1,
            ),
        )
    fallback_targets = fallback.on_session(
        tuple(history[symbol][-1] for symbol in _SYMBOLS), history
    )
    assert next(
        target.weight for target in fallback_targets if target.symbol == _BY_NAME["SHY"]
    ) == Decimal("1")

    state = build_rapid_004_portfolio_strategy(
        "case",
        _SYMBOLS,
        _GROUPS,
        _SLEEVES,
        {"case": {"contract": "independent-trend-v1", "group": "all"}},
        {"window": 2},
    )
    bars = tuple(history[symbol][-1] for symbol in _SYMBOLS)
    assert state.on_session(bars, history)
    assert not state.on_session(bars, history)


@pytest.mark.parametrize("fill_delay", (1, 2, 3))
@pytest.mark.parametrize(
    ("contract", "closes", "parameters", "entry_index", "exit_index"),
    (
        (
            "independent-trend-v1",
            tuple(Decimal(value) for value in ("100", "110", "90", "90", "90", "90", "90", "90")),
            {"window": 2},
            1,
            2,
        ),
        (
            "channel-breakout-v1",
            tuple(Decimal(value) for value in ("100", "101", "110", "90", "90", "90", "90", "90")),
            {"entry_window": 2, "exit_window": 1},
            2,
            3,
        ),
    ),
)
def test_state_changes_fill_at_the_exact_declared_delay(
    fill_delay: int,
    contract: str,
    closes: tuple[Decimal, ...],
    parameters: dict[str, int],
    entry_index: int,
    exit_index: int,
) -> None:
    history = _history()
    spy = _BY_NAME["SPY"]
    history[spy] = tuple(
        OHLCVBar(spy, bar.timestamp, close, close + 1, close - 1, close, 1)
        for bar, close in zip(history[spy], closes, strict=True)
    )
    strategy = build_rapid_004_portfolio_strategy(
        "case",
        _SYMBOLS,
        _GROUPS | {"spy": (spy,)},
        _SLEEVES,
        {"case": {"contract": contract, "group": "spy"}},
        parameters,
    )
    result = BacktestEngine(
        Decimal("1000"),
        CostModel(slippage_bps=Decimal("0"), commission_bps=Decimal("0")),
        fill_delay,
        queue_portfolio_targets=True,
    ).run_portfolio(tuple(bar for bars in history.values() for bar in bars), strategy)
    assert len(result.trades) == 2
    assert result.trades[0].decision_timestamp == history[spy][entry_index].timestamp
    assert result.trades[0].fill_timestamp == history[spy][entry_index + fill_delay].timestamp
    assert result.trades[1].decision_timestamp == history[spy][exit_index].timestamp
    assert result.trades[1].fill_timestamp == history[spy][exit_index + fill_delay].timestamp
    assert dict(result.equity_curve[-1].positions).get(spy, Decimal("0")) == Decimal("0")
    assert not any(event.reason == "pending-order-exists" for event in result.orders)


def test_breakout_walk_forward_replays_training_state_before_first_test_target() -> None:
    history = _history()
    spy = _BY_NAME["SPY"]
    closes = tuple(Decimal(value) for value in ("100", "101", "110", "112", "113", "114"))
    history[spy] = tuple(
        OHLCVBar(spy, bar.timestamp, close, close + 1, close - 1, close, 1)
        for bar, close in zip(history[spy], closes, strict=False)
    )
    evaluation_start = history[spy][4].timestamp
    strategy = build_rapid_004_portfolio_strategy(
        "case",
        _SYMBOLS,
        _GROUPS | {"spy": (spy,)},
        _SLEEVES,
        {"case": {"contract": "channel-breakout-v1", "group": "spy"}},
        {"entry_window": 2, "exit_window": 1},
        evaluation_start=evaluation_start,
    )
    emitted = []
    for index in range(5):
        sliced = {symbol: bars[: index + 1] for symbol, bars in history.items()}
        targets = strategy.on_session(tuple(sliced[symbol][-1] for symbol in _SYMBOLS), sliced)
        emitted.append(targets)

    assert not any(emitted[:4])
    assert next(target.weight for target in emitted[4] if target.symbol == spy) == Decimal("1")


def test_inverse_volatility_keeps_infeasible_or_not_warm_positions_in_cash() -> None:
    constant = _history()
    for symbol, bars in constant.items():
        constant[symbol] = tuple(
            OHLCVBar(
                symbol,
                bar.timestamp,
                Decimal("100"),
                Decimal("101"),
                Decimal("99"),
                Decimal("100"),
                1,
            )
            for bar in bars
        )
    allocation = build_rapid_004_portfolio_strategy(
        "case",
        _SYMBOLS,
        _GROUPS,
        _SLEEVES,
        {"case": {"contract": "inverse-volatility-allocation-v1", "group": "all", "cap": "0.4"}},
        {"volatility_window": 2, "rebalance_every": 1},
    )
    targets = allocation.on_session(tuple(constant[symbol][-1] for symbol in _SYMBOLS), constant)
    assert all(target.weight == 0 for target in targets)

    short_history = {symbol: bars[:3] for symbol, bars in _history().items()}
    trend = build_rapid_004_portfolio_strategy(
        "case",
        _SYMBOLS,
        _GROUPS,
        _SLEEVES,
        {
            "case": {
                "contract": "independent-trend-inverse-volatility-v1",
                "group": "all",
                "cap": "0.4",
                "volatility_window": 5,
            }
        },
        {"window": 2},
    )
    assert not trend.on_session(
        tuple(short_history[symbol][-1] for symbol in _SYMBOLS), short_history
    )
