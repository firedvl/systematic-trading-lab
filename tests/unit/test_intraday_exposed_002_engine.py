from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from systematic_trading_lab.backtesting import BacktestError
from systematic_trading_lab.calendar import expected_bar_timestamps
from systematic_trading_lab.domain import OHLCVBar, Symbol, Timeframe
from systematic_trading_lab.intraday_execution_cost_model import (
    ExecutionCostScenario,
    RegulatoryFeeModel,
)
from systematic_trading_lab.intraday_exposed_002_engine import IntradayExposed002Engine
from systematic_trading_lab.intraday_fed_policy_absorption_001_engine import (
    Exposed002Fill,
    IntradayFedPolicyAbsorption001Engine,
    _PendingTransition,
)
from systematic_trading_lab.strategies import TargetPosition

QQQ = Symbol("QQQ")
SPY = Symbol("SPY")
ZERO = Decimal("0")
HALF = Decimal("0.5")


@dataclass(frozen=True)
class _EnterAndHold:
    active: tuple[Symbol, ...] = (SPY,)
    strategy_id: str = "test-enter-and-hold"
    version: str = "1"

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        del bars, history
        return tuple(
            TargetPosition(symbol, HALF if symbol in self.active else ZERO, "test")
            for symbol in (QQQ, SPY)
        )


@dataclass(frozen=True)
class _Reenter:
    strategy_id: str = "test-reenter"
    version: str = "1"

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        session = bars[0].timestamp.date()
        index = sum(bar.timestamp.date() == session for bar in history[SPY]) - 1
        weight = HALF if index in {0, 1, 4, 5} or index > 5 else ZERO
        return (
            TargetPosition(QQQ, ZERO, "test"),
            TargetPosition(SPY, weight, "test"),
        )


@dataclass(frozen=True)
class _ExitBeforeCutoff:
    strategy_id: str = "test-exit-before-cutoff"
    version: str = "1"

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        del history
        elapsed = bars[0].timestamp - datetime(2026, 5, 1, 13, 30, tzinfo=UTC)
        index = int(elapsed.total_seconds() // 300)
        return (
            TargetPosition(QQQ, ZERO, "test"),
            TargetPosition(SPY, HALF if index < 72 else ZERO, "test"),
        )


@dataclass(frozen=True)
class _EnterBeforeCutoff:
    strategy_id: str = "test-enter-before-cutoff"
    version: str = "1"

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        del history
        elapsed = bars[0].timestamp - datetime(2026, 5, 1, 13, 30, tzinfo=UTC)
        index = int(elapsed.total_seconds() // 300)
        return (
            TargetPosition(QQQ, ZERO, "test"),
            TargetPosition(SPY, HALF if index >= 72 else ZERO, "test"),
        )


def _fees() -> RegulatoryFeeModel:
    return RegulatoryFeeModel(
        "alpaca-us-equity-regulatory-fees-2026-07-20-v1",
        "America/New_York",
        Decimal("0.0000206"),
        Decimal("0.000195"),
        Decimal("9.79"),
        Decimal("0.000003"),
    )


def _scenario(
    name: str = "normal",
    *,
    qqq_bps: str = "1",
    spy_bps: str = "2",
    delay: int = 1,
    charge_fees: bool = True,
) -> ExecutionCostScenario:
    return ExecutionCostScenario(
        name,
        None,
        {QQQ: Decimal(qqq_bps), SPY: Decimal(spy_bps)},
        delay,
        _fees().model_id if charge_fees else None,
    )


def _bars(start: datetime, end: datetime, price: str = "100") -> tuple[OHLCVBar, ...]:
    value = Decimal(price)
    return tuple(
        OHLCVBar(symbol, timestamp, value, value, value, value, 1_000)
        for timestamp in expected_bar_timestamps(start, end, Timeframe.FIVE_MINUTES)
        for symbol in (QQQ, SPY)
    )


def test_replay_uses_symbol_costs_flattens_and_deducts_daily_fees() -> None:
    bars = _bars(
        datetime(2026, 5, 1, 13, 30, tzinfo=UTC),
        datetime(2026, 5, 1, 19, 55, tzinfo=UTC),
    )

    result = IntradayExposed002Engine(Decimal("100000"), _scenario(), _fees()).run(
        bars, _EnterAndHold((QQQ, SPY))
    )

    assert len(result.round_trips) == 2
    buys = {fill.symbol: fill for fill in result.fills if fill.quantity > 0}
    sells = {fill.symbol: fill for fill in result.fills if fill.quantity < 0}
    assert buys[QQQ].fill_price == Decimal("100.01")
    assert buys[SPY].fill_price == Decimal("100.02")
    assert sells[QQQ].fill_price == Decimal("99.99")
    assert sells[SPY].fill_price == Decimal("99.98")
    daily = result.fee_ledger[0]
    assert daily.charges.sec > 0
    assert daily.charges.taf > 0
    assert daily.charges.cat > 0
    assert sum((value for _symbol, value in daily.by_symbol), ZERO) == daily.charges.total
    assert result.equity_curve[-1].positions == ((QQQ, ZERO), (SPY, ZERO))
    gross = sum((trade.gross_profit for trade in result.round_trips), ZERO)
    friction = sum((fill.adverse_slippage for fill in result.fills), ZERO) + sum(
        (item.charges.total for item in result.fee_ledger), ZERO
    )
    precision = Decimal("0.000000000001")
    assert (result.equity_curve[-1].equity - result.initial_cash).quantize(precision) == (
        gross - friction
    ).quantize(precision)


def test_exact_joint_entries_use_shared_half_equity_notional_and_flatten() -> None:
    bars = _bars(
        datetime(2026, 5, 1, 13, 30, tzinfo=UTC),
        datetime(2026, 5, 1, 19, 55, tzinfo=UTC),
        "3",
    )
    initial_cash = Decimal("100001")
    result = IntradayFedPolicyAbsorption001Engine(
        initial_cash,
        _scenario(qqq_bps="0", spy_bps="0", charge_fees=False),
        _fees(),
    ).run(bars, _EnterAndHold((QQQ, SPY)))

    entries = [fill for fill in result.fills if fill.quantity > ZERO]
    assert len(entries) == 2
    assert all(fill.quantity * fill.fill_price != initial_cash * HALF for fill in entries)
    assert {fill.symbol for fill in entries} == {QQQ, SPY}
    assert all(fill.gross_notional == initial_cash * HALF for fill in entries)
    assert sum((fill.gross_notional for fill in entries), ZERO) == initial_cash
    assert len(result.round_trips) == 2
    assert all(trade.net_before_regulatory_fees == ZERO for trade in result.round_trips)
    assert result.equity_curve[-1].positions == ((SPY, ZERO), (QQQ, ZERO))
    assert result.equity_curve[-1].equity == initial_cash
    assert result.fee_ledger[0].charges.total == ZERO


def test_exact_joint_second_leg_failure_does_not_commit_batch_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars = _bars(
        datetime(2026, 5, 1, 13, 30, tzinfo=UTC),
        datetime(2026, 5, 1, 19, 55, tzinfo=UTC),
    )
    engine = IntradayFedPolicyAbsorption001Engine(
        Decimal("100000"),
        _scenario(charge_fees=False),
        _fees(),
    )
    before = dict(engine.__dict__)
    original_fill = IntradayFedPolicyAbsorption001Engine._fill
    observed: dict[str, object] = {}

    def fail_on_qqq(
        self: IntradayFedPolicyAbsorption001Engine,
        item: _PendingTransition,
        market_price: Decimal,
        cash: Decimal,
        positions: dict[Symbol, Decimal],
        marks: Mapping[Symbol, Decimal],
        entries: dict[Symbol, int],
        open_fills: Mapping[Symbol, Exposed002Fill],
        *,
        entry_equity: Decimal | None = None,
    ) -> tuple[Decimal, Exposed002Fill]:
        if item.symbol == QQQ:
            observed["cash"] = cash
            observed["positions"] = dict(positions)
            observed["entries"] = dict(entries)
            observed["open_fills"] = dict(open_fills)
            raise BacktestError("forced second-leg failure")
        return original_fill(
            self,
            item,
            market_price,
            cash,
            positions,
            marks,
            entries,
            open_fills,
            entry_equity=entry_equity,
        )

    monkeypatch.setattr(IntradayFedPolicyAbsorption001Engine, "_fill", fail_on_qqq)

    with pytest.raises(BacktestError, match="forced second-leg failure"):
        engine.run(bars, _EnterAndHold((QQQ, SPY)))

    # The first fill mutated only the batch's working copies.  The engine stores
    # no replay state, and no replay artifact was returned to expose partial fills.
    assert engine.__dict__ == before
    assert observed["cash"] == Decimal("50000")
    assert observed["positions"] == {
        SPY: Decimal("50000") / Decimal("100.02"),
        QQQ: ZERO,
    }
    assert observed["entries"] == {SPY: 1, QQQ: 0}
    assert observed["open_fills"]


def test_daily_fees_reduce_next_session_position_size_before_carry() -> None:
    bars = _bars(
        datetime(2026, 5, 1, 13, 30, tzinfo=UTC),
        datetime(2026, 5, 4, 19, 55, tzinfo=UTC),
    )
    scenario = _scenario(qqq_bps="0", spy_bps="0")

    result = IntradayExposed002Engine(Decimal("100000"), scenario, _fees()).run(
        bars, _EnterAndHold()
    )

    entries = [fill for fill in result.fills if fill.quantity > 0]
    assert len(entries) == 2
    assert entries[1].quantity < entries[0].quantity
    assert result.fee_ledger[0].charges.total > 0


def test_zero_cost_keeps_decision_and_delay_trace_without_monetary_costs() -> None:
    bars = _bars(
        datetime(2026, 5, 1, 13, 30, tzinfo=UTC),
        datetime(2026, 5, 1, 19, 55, tzinfo=UTC),
    )
    normal = IntradayExposed002Engine(Decimal("100000"), _scenario(), _fees()).run(
        bars, _EnterAndHold()
    )
    zero_scenario = _scenario(
        "zero_cost_diagnostic",
        qqq_bps="0",
        spy_bps="0",
        charge_fees=False,
    )

    zero = IntradayExposed002Engine(Decimal("100000"), zero_scenario, _fees()).run(
        bars, _EnterAndHold()
    )

    assert [item.desired_targets for item in normal.decisions] == [
        item.desired_targets for item in zero.decisions
    ]
    assert [fill.fill_timestamp for fill in normal.fills] == [
        fill.fill_timestamp for fill in zero.fills
    ]
    assert all(fill.adverse_slippage == 0 for fill in zero.fills)
    assert all(item.charges.total == 0 for item in zero.fee_ledger)


def test_delay_and_one_entry_per_symbol_are_enforced() -> None:
    bars = _bars(
        datetime(2026, 5, 1, 13, 30, tzinfo=UTC),
        datetime(2026, 5, 1, 19, 55, tzinfo=UTC),
    )
    delayed = IntradayExposed002Engine(Decimal("100000"), _scenario(delay=3), _fees()).run(
        bars, _EnterAndHold()
    )
    spy_entry = next(fill for fill in delayed.fills if fill.symbol == SPY and fill.quantity > 0)
    assert spy_entry.fill_timestamp == datetime(2026, 5, 1, 13, 45, tzinfo=UTC)

    with pytest.raises(BacktestError, match="one entry"):
        IntradayExposed002Engine(Decimal("100000"), _scenario(charge_fees=False), _fees()).run(
            bars, _Reenter()
        )


def test_exit_due_before_close_keeps_fifo_fill_instead_of_close_repricing() -> None:
    bars = _bars(
        datetime(2026, 5, 1, 13, 30, tzinfo=UTC),
        datetime(2026, 5, 1, 19, 55, tzinfo=UTC),
    )

    result = IntradayExposed002Engine(Decimal("100000"), _scenario(delay=3), _fees()).run(
        bars, _ExitBeforeCutoff()
    )

    exit_fill = next(fill for fill in result.fills if fill.quantity < 0)
    assert exit_fill.fill_timestamp == datetime(2026, 5, 1, 19, 45, tzinfo=UTC)
    assert not any(
        transition.status == "canceled" and transition.to_weight == ZERO
        for transition in result.transitions
    )


def test_entry_due_before_close_fills_then_flattens_at_close() -> None:
    bars = _bars(
        datetime(2026, 5, 1, 13, 30, tzinfo=UTC),
        datetime(2026, 5, 1, 19, 55, tzinfo=UTC),
    )

    result = IntradayExposed002Engine(Decimal("100000"), _scenario(delay=3), _fees()).run(
        bars, _EnterBeforeCutoff()
    )

    spy_fills = [fill for fill in result.fills if fill.symbol == SPY]
    assert [fill.fill_timestamp for fill in spy_fills] == [
        datetime(2026, 5, 1, 19, 45, tzinfo=UTC),
        datetime(2026, 5, 1, 19, 55, tzinfo=UTC),
    ]
    assert not any(transition.status == "canceled" for transition in result.transitions)


def test_replay_rejects_incomplete_symbol_slices() -> None:
    bars = _bars(
        datetime(2026, 5, 1, 13, 30, tzinfo=UTC),
        datetime(2026, 5, 1, 19, 55, tzinfo=UTC),
    )

    with pytest.raises(BacktestError, match="complete QQQ/SPY"):
        IntradayExposed002Engine(Decimal("100000"), _scenario(), _fees()).run(
            bars[1:], _EnterAndHold()
        )
