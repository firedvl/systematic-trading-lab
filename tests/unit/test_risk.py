import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from systematic_trading_lab.execution import ExecutionIntent, JournalIntegrityError
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.risk import RiskContext, RiskLimits, RiskStore, evaluate_risk

NOW = datetime(2026, 8, 3, 20, tzinfo=UTC)


def _intent(**changes: object) -> ExecutionIntent:
    value = ExecutionIntent(
        idempotency_key="candidate:SPY:2026-08-03",
        strategy_id="candidate",
        strategy_version="1",
        symbol="SPY",
        decision_timestamp=NOW - timedelta(minutes=1),
        target_weight=Decimal("0.25"),
        target_quantity=None,
        reason="daily target",
        source_data_fingerprint=fingerprint({"data": 1}),
        configuration_fingerprint=fingerprint({"strategy": 1}),
        reference_price=Decimal("100"),
        expires_at=NOW + timedelta(minutes=10),
    )
    return replace(value, **cast(Any, changes))


def _limits(**changes: object) -> RiskLimits:
    value = RiskLimits(
        configuration_id="test-only-limits",
        account_id="paper-account",
        allowed_symbols=("QQQ", "SPY"),
        max_order_notional=Decimal("30000"),
        max_position_notional=Decimal("40000"),
        max_gross_exposure=Decimal("90000"),
        min_cash=Decimal("10000"),
        max_open_orders=3,
        max_orders_per_minute=4,
        max_daily_loss=Decimal("2000"),
        max_strategy_drawdown=Decimal("0.10"),
        max_price_deviation_bps=Decimal("50"),
        max_snapshot_age_seconds=30,
        min_reconciliation_stability_seconds=5,
        reviewed_by="test-reviewer",
        review_reason="test fixture only",
        effective_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=1),
    )
    return replace(value, **cast(Any, changes))


def _context(**changes: object) -> RiskContext:
    observed = NOW - timedelta(seconds=5)
    value = RiskContext(
        account_id="paper-account",
        evaluated_at=NOW,
        equity=Decimal("100000"),
        cash=Decimal("70000"),
        buying_power=Decimal("70000"),
        current_gross_exposure=Decimal("20000"),
        current_symbol_notional=Decimal("10000"),
        current_symbol_quantity=100,
        pending_buy_notional=Decimal("0"),
        pending_order_notional=Decimal("0"),
        active_reservation_set_fingerprint=fingerprint({"reservations": []}),
        open_order_count=0,
        pending_order_count=0,
        orders_last_minute=0,
        daily_pnl=Decimal("0"),
        strategy_drawdown=Decimal("0"),
        quote_bid_price=Decimal("99.99"),
        quote_ask_price=Decimal("100"),
        account_observed_at=observed,
        positions_observed_at=observed,
        orders_observed_at=observed,
        quote_observed_at=observed,
        clock_observed_at=observed,
        regular_session_open=True,
        emergency_disabled=False,
    )
    return replace(value, **cast(Any, changes))


def test_risk_approves_only_when_every_gate_passes() -> None:
    decision = evaluate_risk(_intent(), _limits(), _context())

    assert decision.approved
    assert decision.reasons == ()
    assert decision.order_notional == Decimal("15000")
    assert decision.cash_reservation == Decimal("15000")
    assert decision.configuration_fingerprint == _limits().configuration_fingerprint


def test_risk_collects_fail_closed_reasons() -> None:
    context = _context(
        emergency_disabled=True,
        account_id="other",
        quote_observed_at=NOW - timedelta(minutes=2),
        regular_session_open=False,
        daily_pnl=Decimal("-2000"),
        strategy_drawdown=Decimal("0.10"),
        quote_bid_price=Decimal("102"),
        quote_ask_price=Decimal("102"),
        current_symbol_notional=Decimal("10200"),
        current_gross_exposure=Decimal("20200"),
        pending_buy_notional=Decimal("60000"),
        pending_order_count=3,
        orders_last_minute=4,
    )
    decision = evaluate_risk(_intent(symbol="IWM"), _limits(), context)

    assert not decision.approved
    assert set(decision.reasons) >= {
        "emergency-disabled",
        "account-mismatch",
        "symbol-not-allowed",
        "snapshot-stale-or-future",
        "regular-session-closed",
        "daily-loss-limit",
        "strategy-drawdown-limit",
        "price-deviation-limit",
        "buying-power-limit",
        "minimum-cash-limit",
        "open-order-limit",
        "order-rate-limit",
    }


def test_risk_uses_ask_for_buys_and_bid_for_sells() -> None:
    context = _context(quote_bid_price=Decimal("98"), quote_ask_price=Decimal("100"))
    buy = evaluate_risk(_intent(target_weight=None, target_quantity=150), _limits(), context)
    sell = evaluate_risk(_intent(target_weight=None, target_quantity=50), _limits(), context)
    weight_buy = evaluate_risk(_intent(target_weight=Decimal("0.15")), _limits(), context)
    weight_sell = evaluate_risk(_intent(target_weight=Decimal("0.05")), _limits(), context)

    assert buy.approved
    assert buy.order_notional == Decimal("5000")
    assert not sell.approved
    assert "price-deviation-limit" in sell.reasons
    assert sell.order_notional == Decimal("4900")
    assert weight_buy.approved
    assert not weight_sell.approved
    assert "price-deviation-limit" in weight_sell.reasons


def test_limits_reject_implicit_or_invalid_values() -> None:
    with pytest.raises(ValueError, match="sorted unique"):
        _limits(allowed_symbols=("SPY", "QQQ"))
    with pytest.raises(ValueError, match="finite and positive"):
        _limits(max_daily_loss=Decimal("0"))
    with pytest.raises(ValueError, match="expiry"):
        _limits(expires_at=NOW - timedelta(days=2))
    with pytest.raises(ValueError, match="stability interval"):
        _limits(min_reconciliation_stability_seconds=0)
    with pytest.raises(ValueError, match="cannot exceed"):
        _context(quote_bid_price=Decimal("101"), quote_ask_price=Decimal("100"))
    with pytest.raises(ValueError, match="must use the ask"):
        _context(current_symbol_quantity=99)


def test_emergency_disable_is_default_persistent_and_journal_bound(tmp_path: Path) -> None:
    path = tmp_path / "execution.sqlite3"
    first = RiskStore(path).get_emergency()
    second = RiskStore(path).get_emergency()

    assert first == second
    assert first.disabled
    assert first.reason == "paper execution is not enabled"

    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE emergency_state SET reason = 'tampered'")
    with pytest.raises(JournalIntegrityError, match="emergency state"):
        RiskStore(path)

    missing_path = tmp_path / "missing-emergency.sqlite3"
    RiskStore(missing_path)
    with sqlite3.connect(missing_path) as connection:
        connection.execute("DROP TABLE emergency_state")
    with pytest.raises(JournalIntegrityError, match="emergency state is missing"):
        RiskStore(missing_path)
