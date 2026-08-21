from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from systematic_trading_lab.domain import OHLCVBar, Symbol
from systematic_trading_lab.intraday_execution_cost_model import (
    load_intraday_execution_cost_model,
)
from systematic_trading_lab.intraday_exposed_002_plan import load_intraday_exposed_002_plan
from systematic_trading_lab.intraday_exposed_002_strategies import (
    build_intraday_exposed_002_strategy,
)

_QQQ, _SPY = Symbol("QQQ"), Symbol("SPY")
_REPOSITORY = __import__("pathlib").Path(__file__).resolve().parents[2]
_COST_MODEL = load_intraday_execution_cost_model(_REPOSITORY)


def _bar(symbol: Symbol, timestamp: datetime, close: str) -> OHLCVBar:
    value = Decimal(close)
    return OHLCVBar(symbol, timestamp, value, value, value, value, 100)


def _history(
    qqq: tuple[str, ...], spy: tuple[str, ...], *, prior_days: int = 0
) -> dict[Symbol, tuple[OHLCVBar, ...]]:
    result: dict[Symbol, list[OHLCVBar]] = {_QQQ: [], _SPY: []}
    for day in range(prior_days):
        start = datetime(2026, 1, 2 + day, 14, 30, tzinfo=UTC)
        for symbol in result:
            result[symbol].extend(
                _bar(symbol, start + timedelta(minutes=5 * item), "100") for item in range(3)
            )
    start = datetime(2026, 1, 8, 14, 30, tzinfo=UTC)
    for symbol, values in ((_QQQ, qqq), (_SPY, spy)):
        result[symbol].extend(
            _bar(symbol, start + timedelta(minutes=5 * item), value)
            for item, value in enumerate(values)
        )
    return {symbol: tuple(items) for symbol, items in result.items()}


def _targets(
    strategy: object, history: dict[Symbol, tuple[OHLCVBar, ...]]
) -> dict[Symbol, Decimal]:
    result = strategy.on_session(  # type: ignore[attr-defined]
        (history[_QQQ][-1], history[_SPY][-1]), history
    )
    return {target.symbol: target.weight for target in result}


def test_builder_accepts_frozen_configuration_and_all_ten_families() -> None:
    plan = load_intraday_exposed_002_plan(_REPOSITORY)
    seen: set[str] = set()
    for configuration in plan.configurations:
        strategy = build_intraday_exposed_002_strategy(configuration, cost_model=_COST_MODEL)
        seen.add(strategy.family_id)
        assert strategy.strategy_id == configuration.candidate_id
        assert strategy.version == "intraday-exposed-002-mechanics-v1"
    assert len(seen) == 10


def test_rejects_parameter_drift_and_wrong_universe() -> None:
    with pytest.raises(ValueError, match="parameters differ"):
        build_intraday_exposed_002_strategy(
            "opening-range-breakout-v1",
            (_QQQ, _SPY),
            {"range_bars": 2},
            cost_model=_COST_MODEL,
        )
    with pytest.raises(ValueError, match="exactly QQQ and SPY"):
        build_intraday_exposed_002_strategy(
            "opening-range-breakout-v1",
            (_SPY,),
            {
                "range_bars": 2,
                "breakout_buffer_bps": "5",
                "minimum_edge_cost_multiple": "4",
                "reentry_allowed": False,
            },
            cost_model=_COST_MODEL,
        )


def test_opening_range_is_causal_and_never_resizes_or_reenters() -> None:
    strategy = build_intraday_exposed_002_strategy(
        "opening-range-breakout-v1",
        (_QQQ, _SPY),
        {
            "range_bars": 2,
            "breakout_buffer_bps": "5",
            "minimum_edge_cost_multiple": "4",
            "reentry_allowed": False,
        },
        cost_model=_COST_MODEL,
    )
    before = _history(("100", "101"), ("100", "101"))
    assert set(_targets(strategy, before).values()) == {Decimal("0")}
    entered = _history(("100", "101", "103", "104"), ("100", "101", "103", "104"))
    assert set(_targets(strategy, entered).values()) == {Decimal("0.5")}
    stopped = _history(("100", "101", "103", "99", "104"), ("100", "101", "103", "99", "104"))
    assert set(_targets(strategy, stopped).values()) == {Decimal("0")}


def test_gap_confirmation_counts_completed_bars() -> None:
    strategy = build_intraday_exposed_002_strategy(
        "gap-down-failed-continuation-fade-v1",
        (_QQQ, _SPY),
        {
            "minimum_gap_bps": "20",
            "confirmation_bars": 3,
            "minimum_retrace_fraction": "0.5",
            "exit_bar_index": 66,
            "gap_side": "down-only",
        },
        cost_model=_COST_MODEL,
    )

    two_bars = _history(("99", "100"), ("99", "100"), prior_days=1)
    three_bars = _history(("99", "99.5", "100"), ("99", "99.5", "100"), prior_days=1)

    assert set(_targets(strategy, two_bars).values()) == {Decimal("0")}
    assert set(_targets(strategy, three_bars).values()) == {Decimal("0.5")}


def test_cross_asset_family_requires_same_completed_slice_and_agreement() -> None:
    strategy = build_intraday_exposed_002_strategy(
        "cross-asset-confirmed-breakout-v1",
        (_QQQ, _SPY),
        {
            "confirmation_window_bars": 1,
            "minimum_joint_breakout_bps": "5",
            "opening_range_bars": 6,
            "require_spy_qqq_agreement": True,
            "reentry_allowed": False,
        },
        cost_model=_COST_MODEL,
    )
    no_agreement = _history(("100",) * 6 + ("102",), ("100",) * 7)
    assert set(_targets(strategy, no_agreement).values()) == {Decimal("0")}
    agreement = _history(("100",) * 6 + ("102",), ("100",) * 6 + ("102",))
    assert set(_targets(strategy, agreement).values()) == {Decimal("0.5")}
    broken = dict(agreement)
    broken[_SPY] = broken[_SPY][:-1]
    with pytest.raises(ValueError, match="aligned completed"):
        _targets(strategy, broken)


def test_cross_asset_confirmation_window_and_frozen_cost_estimate_are_effective() -> None:
    strategy = build_intraday_exposed_002_strategy(
        "cross-asset-confirmed-breakout-v1",
        (_QQQ, _SPY),
        {
            "confirmation_window_bars": 2,
            "minimum_joint_breakout_bps": "5",
            "opening_range_bars": 6,
            "require_spy_qqq_agreement": True,
            "reentry_allowed": False,
        },
        cost_model=_COST_MODEL,
    )
    one_bar = _history(("100",) * 7 + ("102",), ("100",) * 7 + ("102",))
    assert set(_targets(strategy, one_bar).values()) == {Decimal("0")}
    two_bars = _history(("100",) * 6 + ("102", "103"), ("100",) * 6 + ("102", "103"))
    assert set(_targets(strategy, two_bars).values()) == {Decimal("0.5")}

    bar = two_bars[_SPY][-1]
    assert strategy._round_trip_cost_bps(_QQQ, bar) > strategy._round_trip_cost_bps(_SPY, bar)
    assert strategy._round_trip_cost_bps(_SPY, bar) > Decimal("0.18")


def test_minimum_edge_agreement_uses_each_symbols_cost_threshold() -> None:
    strategy = build_intraday_exposed_002_strategy(
        "minimum-edge-hysteresis-one-trade-v1",
        (_QQQ, _SPY),
        {
            "entry_edge_cost_multiple": "4",
            "hysteresis_cost_multiple": "1",
            "observation_bars": 6,
            "require_spy_qqq_agreement": True,
            "maximum_entries_per_symbol_session": 1,
        },
        cost_model=_COST_MODEL,
    )
    history = _history(("100",) * 6 + ("100.02",), ("100",) * 6 + ("100.02",))

    assert strategy._round_trip_cost_bps(_SPY, history[_SPY][-1]) * 4 < Decimal("2")
    assert strategy._round_trip_cost_bps(_QQQ, history[_QQQ][-1]) * 4 > Decimal("2")
    assert set(_targets(strategy, history).values()) == {Decimal("0")}


def test_trend_pullback_requires_pullback_after_established_peak() -> None:
    strategy = build_intraday_exposed_002_strategy(
        "trend-pullback-recovery-v1",
        (_QQQ, _SPY),
        {
            "trend_bars": 6,
            "minimum_trend_bps": "20",
            "pullback_fraction": "0.3333333333333333333333333333",
            "recovery_buffer_bps": "5",
            "reentry_allowed": False,
        },
        cost_model=_COST_MODEL,
    )
    low_before_peak = _history(
        ("100", "99", "100", "101", "102", "103", "104", "105"),
        ("100", "99", "100", "101", "102", "103", "104", "105"),
    )
    pullback_after_peak = _history(
        ("100", "101", "102", "103", "104", "103", "102", "104"),
        ("100", "101", "102", "103", "104", "103", "102", "104"),
    )

    assert set(_targets(strategy, low_before_peak).values()) == {Decimal("0")}
    assert set(_targets(strategy, pullback_after_peak).values()) == {Decimal("0.5")}
