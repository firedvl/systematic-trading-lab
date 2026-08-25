from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from systematic_trading_lab.domain import OHLCVBar, Symbol
from systematic_trading_lab.intraday_fed_policy_absorption_001_strategies import (
    FedPolicyAbsorptionStrategy,
)

_SPY, _QQQ = Symbol("SPY"), Symbol("QQQ")
_START = datetime(2026, 1, 8, 14, 30, tzinfo=UTC)


def _session(spy_terminal: str, qqq_terminal: str) -> dict[Symbol, tuple[OHLCVBar, ...]]:
    def bars(symbol: Symbol, terminal: str) -> tuple[OHLCVBar, ...]:
        return tuple(
            OHLCVBar(
                symbol,
                _START + timedelta(minutes=5 * index),
                Decimal("100"),
                max(Decimal("100"), Decimal(terminal)),
                Decimal("100"),
                Decimal(terminal) if index == 55 else Decimal("100"),
                1_000,
            )
            for index in range(56)
        )

    return {_SPY: bars(_SPY, spy_terminal), _QQQ: bars(_QQQ, qqq_terminal)}


def _strategy() -> FedPolicyAbsorptionStrategy:
    return FedPolicyAbsorptionStrategy(
        "fedabs-h02-f0008", 2, Decimal("8"), frozenset({date(2026, 1, 8)})
    )


def test_equality_activates_joint_half_weights() -> None:
    strategy = _strategy()
    session = _session("100.08", "100.08")
    signal = strategy.signal(session)

    assert signal.active
    assert signal.no_signal_reason is None
    assert signal.spy_reaction_bps == signal.qqq_reaction_bps == Decimal("8.0000")
    assert {
        target.symbol: target.weight
        for target in strategy.on_session((session[_SPY][-1], session[_QQQ][-1]), session)
    } == {_SPY: Decimal("0.5"), _QQQ: Decimal("0.5")}


def test_no_signal_reason_priority_is_exact() -> None:
    strategy = _strategy()

    assert strategy.signal(_session("100.07", "100.07")).no_signal_reason == "both-below-floor"
    assert strategy.signal(_session("100.07", "100.08")).no_signal_reason == "spy-below-floor"
    assert strategy.signal(_session("100.08", "100.07")).no_signal_reason == "qqq-below-floor"


def test_context_only_session_stays_flat_despite_joint_reaction() -> None:
    strategy = FedPolicyAbsorptionStrategy(
        "fedabs-h02-f0008", 2, Decimal("8"), frozenset({date(2026, 1, 7)})
    )
    session = _session("100.08", "100.08")

    targets = strategy.on_session((session[_SPY][-1], session[_QQQ][-1]), session)

    assert [(target.symbol, target.weight, target.reason) for target in targets] == [
        (_SPY, Decimal("0"), "fed-policy-absorption-flat"),
        (_QQQ, Decimal("0"), "fed-policy-absorption-flat"),
    ]


def test_event_session_activates_only_at_causal_terminal_bar() -> None:
    strategy = _strategy()
    session = _session("100.08", "100.08")
    before_terminal = {symbol: bars[:55] for symbol, bars in session.items()}

    before_targets = strategy.on_session(
        (before_terminal[_SPY][-1], before_terminal[_QQQ][-1]), before_terminal
    )
    terminal_targets = strategy.on_session((session[_SPY][-1], session[_QQQ][-1]), session)

    assert [target.weight for target in before_targets] == [Decimal("0"), Decimal("0")]
    assert [target.weight for target in terminal_targets] == [Decimal("0.5"), Decimal("0.5")]
