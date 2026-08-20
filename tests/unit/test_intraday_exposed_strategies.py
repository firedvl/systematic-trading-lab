from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from systematic_trading_lab.calendar import expected_bar_timestamps
from systematic_trading_lab.domain import OHLCVBar, Symbol, Timeframe
from systematic_trading_lab.intraday_exposed_strategies import build_intraday_exposed_strategy

_SPY, _QQQ = Symbol("SPY"), Symbol("QQQ")


def _history(
    count: int,
    *,
    spy: tuple[str, ...] = (),
    qqq: tuple[str, ...] = (),
    volume: int = 100,
    prior_close: str | None = None,
) -> dict[Symbol, tuple[OHLCVBar, ...]]:
    timestamps = expected_bar_timestamps(
        datetime(2026, 1, 5, tzinfo=UTC),
        datetime(2026, 1, 5, 21, tzinfo=UTC),
        Timeframe.FIVE_MINUTES,
    )[:count]

    def bars(symbol: Symbol, values: tuple[str, ...]) -> tuple[OHLCVBar, ...]:
        prices = values or tuple(str(100 + index) for index in range(count))
        return tuple(
            OHLCVBar(
                symbol,
                timestamp,
                Decimal(price),
                Decimal(price) + 1,
                Decimal(price) - 1,
                Decimal(price),
                volume,
            )
            for timestamp, price in zip(timestamps, prices, strict=True)
        )

    result = {_SPY: bars(_SPY, spy), _QQQ: bars(_QQQ, qqq)}
    if prior_close is not None:
        prior_time = datetime(2026, 1, 2, 20, 55, tzinfo=UTC)
        for symbol in result:
            prior = OHLCVBar(
                symbol,
                prior_time,
                Decimal(prior_close),
                Decimal(prior_close),
                Decimal(prior_close),
                Decimal(prior_close),
                volume,
            )
            result[symbol] = (prior, *result[symbol])
    return result


def _targets(
    strategy: object, history: dict[Symbol, tuple[OHLCVBar, ...]]
) -> dict[Symbol, Decimal]:
    result = strategy.on_session([history[_SPY][-1], history[_QQQ][-1]], history)  # type: ignore[attr-defined]
    return {item.symbol: item.weight for item in result}


def test_builder_rejects_parameter_drift_and_wrong_universe() -> None:
    with pytest.raises(ValueError, match="parameters differ"):
        build_intraday_exposed_strategy("absolute-momentum", (_SPY, _QQQ), {"lookback": 6})
    with pytest.raises(ValueError, match="parameters differ"):
        build_intraday_exposed_strategy(
            "absolute-momentum", (_SPY, _QQQ), {"lookback": True, "threshold_bps": 0}
        )
    with pytest.raises(ValueError, match="exactly SPY"):
        build_intraday_exposed_strategy(
            "absolute-momentum", (_SPY,), {"lookback": 6, "threshold_bps": 0}
        )


def test_rejects_partial_or_misaligned_slices() -> None:
    strategy = build_intraday_exposed_strategy(
        "absolute-momentum", (_SPY, _QQQ), {"lookback": 3, "threshold_bps": 0}
    )
    history = _history(4)
    history = {symbol: items[1:] for symbol, items in history.items()}
    with pytest.raises(ValueError, match="full completed"):
        _targets(strategy, history)
    complete = _history(5)
    complete[_QQQ] = complete[_QQQ][:-1]
    with pytest.raises(ValueError, match="aligned completed"):
        strategy.on_session([complete[_SPY][-1], _history(5)[_QQQ][-1]], complete)


def test_orb_only_enters_after_completed_opening_range_and_resets() -> None:
    strategy = build_intraday_exposed_strategy(
        "orb-time-exit", (_SPY, _QQQ), {"opening_bars": 2, "exit_bar": 24}
    )
    before = _history(2, spy=("100", "102"), qqq=("100", "102"))
    assert set(_targets(strategy, before).values()) == {Decimal("0")}
    after = _history(3, spy=("100", "102", "104"), qqq=("100", "102", "104"))
    assert set(_targets(strategy, after).values()) == {Decimal("0.5")}


def test_orb_and_channel_hold_until_their_declared_exit() -> None:
    orb = build_intraday_exposed_strategy(
        "orb-opposite-range-exit", (_SPY, _QQQ), {"opening_bars": 2}
    )
    held = _history(4, spy=("100", "102", "104", "102"), qqq=("100", "102", "104", "102"))
    exited = _history(4, spy=("100", "102", "104", "98"), qqq=("100", "102", "104", "98"))
    assert set(_targets(orb, held).values()) == {Decimal("0.5")}
    assert set(_targets(orb, exited).values()) == {Decimal("0")}

    channel = build_intraday_exposed_strategy(
        "completed-session-channel-breakout",
        (_SPY, _QQQ),
        {"entry_lookback": 3, "exit_lookback": 2},
    )
    held = _history(5, spy=("100", "100", "100", "105", "104"), qqq=("100",) * 3 + ("105", "104"))
    exited = _history(5, spy=("100", "100", "100", "105", "98"), qqq=("100",) * 3 + ("105", "98"))
    assert set(_targets(channel, held).values()) == {Decimal("0.5")}
    assert set(_targets(channel, exited).values()) == {Decimal("0")}


def test_gap_uses_current_open_and_prior_session_final_close() -> None:
    strategy = build_intraday_exposed_strategy(
        "gap-continuation", (_SPY, _QQQ), {"gap_threshold_bps": 20, "entry_delay_bars": 1}
    )
    history = _history(2, spy=("103", "103"), qqq=("103", "103"), prior_close="100")
    assert set(_targets(strategy, history).values()) == {Decimal("0.5")}


def test_relative_strength_rotates_or_stays_in_cash() -> None:
    strategy = build_intraday_exposed_strategy(
        "single-horizon-relative-strength", (_SPY, _QQQ), {"lookback": 3, "threshold_bps": 0}
    )
    history = _history(4, spy=("100", "100", "100", "103"), qqq=("100", "100", "100", "101"))
    targets = _targets(strategy, history)
    assert targets[_SPY] == Decimal("1")
    assert targets[_QQQ] == Decimal("0")
    flat = _history(4, spy=("100", "100", "100", "99"), qqq=("100", "100", "100", "99"))
    assert set(_targets(strategy, flat).values()) == {Decimal("0")}

    rotation = _history(
        5,
        spy=("100", "100", "100", "104", "102"),
        qqq=("100", "100", "100", "101", "105"),
    )
    assert set(_targets(strategy, rotation).values()) == {Decimal("0")}
    settled = _history(
        6,
        spy=("100", "100", "100", "104", "102", "102"),
        qqq=("100", "100", "100", "101", "105", "106"),
    )
    assert _targets(strategy, settled)[_QQQ] == Decimal("1")


def test_vwap_is_causal_and_fails_closed_on_unusable_volume() -> None:
    strategy = build_intraday_exposed_strategy(
        "price-above-cumulative-vwap", (_SPY, _QQQ), {"threshold_bps": 0, "minimum_bars": 3}
    )
    history = _history(3, spy=("100", "100", "102"), qqq=("100", "100", "102"))
    assert set(_targets(strategy, history).values()) == {Decimal("0.5")}
    zero_volume = _history(3, spy=("100", "100", "102"), qqq=("100", "100", "102"), volume=0)
    assert set(_targets(strategy, zero_volume).values()) == {Decimal("0")}


def test_reversion_exit_parameters_change_the_frozen_state() -> None:
    history = _history(
        7,
        spy=("100", "100", "100", "100", "90", "91", "96"),
        qqq=("100", "100", "100", "100", "90", "91", "96"),
    )
    slow_exit = build_intraday_exposed_strategy(
        "moving-average-deviation-reversion",
        (_SPY, _QQQ),
        {"window": 6, "entry_z_hundredths": 75, "exit_z_hundredths": 0},
    )
    early_exit = build_intraday_exposed_strategy(
        "moving-average-deviation-reversion",
        (_SPY, _QQQ),
        {"window": 6, "entry_z_hundredths": 75, "exit_z_hundredths": 25},
    )
    assert set(_targets(slow_exit, history).values()) == {Decimal("0.5")}
    assert set(_targets(early_exit, history).values()) == {Decimal("0")}

    vwap_history = _history(
        4,
        spy=("100", "100", "99", "99.66"),
        qqq=("100", "100", "99", "99.66"),
    )
    vwap_slow = build_intraday_exposed_strategy(
        "cumulative-vwap-reversion",
        (_SPY, _QQQ),
        {"entry_threshold_bps": 10, "exit_threshold_bps": 0},
    )
    vwap_early = build_intraday_exposed_strategy(
        "cumulative-vwap-reversion",
        (_SPY, _QQQ),
        {"entry_threshold_bps": 10, "exit_threshold_bps": 5},
    )
    assert set(_targets(vwap_slow, vwap_history).values()) == {Decimal("0.5")}
    assert set(_targets(vwap_early, vwap_history).values()) == {Decimal("0")}


@pytest.mark.parametrize(
    ("strategy_id", "parameters", "bars"),
    [
        ("price-above-moving-average", {"window": 6}, 6),
        ("short-term-reversal", {"lookback": 1, "threshold_bps": 5}, 2),
        ("rolling-range-breakout", {"lookback": 3, "threshold_half_ranges": 1}, 3),
        (
            "momentum-volatility-filter",
            {"lookback": 6, "volatility_window": 12, "maximum_average_absolute_return_bps": 10},
            12,
        ),
        ("cross-asset-momentum-confirmation", {"lookback": 3, "threshold_bps": 0}, 4),
        ("completed-session-channel-breakout", {"entry_lookback": 3, "exit_lookback": 2}, 4),
        (
            "windowed-momentum",
            {"window_start_bar": 0, "window_end_bar": 11, "lookback": 3, "threshold_bps": 0},
            4,
        ),
        ("opening-range-plus-market-trend", {"opening_bars": 2, "trend_window": 12}, 12),
    ],
)
def test_contract_families_are_buildable(
    strategy_id: str, parameters: dict[str, int], bars: int
) -> None:
    strategy = build_intraday_exposed_strategy(strategy_id, (_SPY, _QQQ), parameters)
    targets = _targets(strategy, _history(bars))
    assert set(targets) == {_SPY, _QQQ}
    assert set(targets.values()) <= {Decimal("0"), Decimal("0.5"), Decimal("1")}
