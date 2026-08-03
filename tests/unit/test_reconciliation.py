from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest

from systematic_trading_lab.reconciliation import (
    OpenOrderSnapshot,
    PortfolioSnapshot,
    PositionSnapshot,
    SnapshotSource,
    reconcile,
)

NOW = datetime(2026, 8, 3, 20, tzinfo=UTC)


def _snapshot(source: SnapshotSource, **changes: object) -> PortfolioSnapshot:
    value = PortfolioSnapshot(
        snapshot_id=f"{source}-1",
        source=source,
        account_id="paper-account",
        cash=Decimal("70000"),
        equity=Decimal("100000"),
        buying_power=Decimal("70000"),
        account_ready=True,
        positions=(PositionSnapshot("SPY", 300),),
        open_orders=(
            OpenOrderSnapshot(
                client_order_id="client-order-1",
                symbol="SPY",
                side="buy",
                quantity=2,
                filled_quantity=0,
                order_type="market",
                limit_price=None,
                status="new",
            ),
        ),
        account_observed_at=NOW - timedelta(seconds=5),
        positions_observed_at=NOW - timedelta(seconds=5),
        orders_observed_at=NOW - timedelta(seconds=5),
    )
    return replace(value, **cast(Any, changes))


def test_reconciliation_passes_only_for_complete_matching_fresh_state() -> None:
    result = reconcile(
        _snapshot(SnapshotSource.LOCAL_EXPECTED),
        _snapshot(SnapshotSource.ALPACA_PAPER),
        compared_at=NOW,
        maximum_age_seconds=30,
        unresolved_mutations=0,
    )

    assert result.clean
    assert result.reasons == ()
    assert result.result_fingerprint


def test_reconciliation_collects_every_material_discrepancy() -> None:
    expected = _snapshot(SnapshotSource.ALPACA_PAPER)
    observed = _snapshot(
        SnapshotSource.LOCAL_EXPECTED,
        account_id="other-account",
        cash=Decimal("69999"),
        equity=Decimal("99999"),
        buying_power=Decimal("69998"),
        positions=(PositionSnapshot("SPY", 299),),
        account_ready=False,
        open_orders=(),
        account_observed_at=NOW - timedelta(minutes=1),
        positions_observed_at=NOW + timedelta(seconds=1),
    )
    result = reconcile(
        expected,
        observed,
        compared_at=NOW,
        maximum_age_seconds=30,
        unresolved_mutations=1,
    )

    assert not result.clean
    assert set(result.reasons) == {
        "expected-source-invalid",
        "observed-source-invalid",
        "account-mismatch",
        "observed-state-stale-or-future",
        "cash-mismatch",
        "equity-mismatch",
        "buying-power-mismatch",
        "account-readiness-mismatch",
        "account-not-ready",
        "position-mismatch",
        "open-order-mismatch",
        "unresolved-broker-mutation",
    }


def test_snapshot_and_reconciliation_inputs_fail_closed() -> None:
    with pytest.raises(ValueError, match="source is unsupported"):
        _snapshot(cast(Any, "alpaca-paper"))
    with pytest.raises(ValueError, match="sorted with unique"):
        _snapshot(
            SnapshotSource.LOCAL_EXPECTED,
            positions=(PositionSnapshot("SPY", 1), PositionSnapshot("SPY", 2)),
        )
    with pytest.raises(ValueError, match="UTC-aware"):
        reconcile(
            _snapshot(SnapshotSource.LOCAL_EXPECTED),
            _snapshot(SnapshotSource.ALPACA_PAPER),
            compared_at=datetime(2026, 8, 3, 20),
            maximum_age_seconds=30,
            unresolved_mutations=0,
        )
