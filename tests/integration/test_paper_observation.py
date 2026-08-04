from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from systematic_trading_lab.alpaca_paper import AlpacaPaperReader
from systematic_trading_lab.execution import JournalIntegrityError
from systematic_trading_lab.paper_observation import (
    PaperObservationStore,
    record_production_observation,
)
from systematic_trading_lab.reconciliation import (
    _ALPACA_READER_CAPABILITY,
    PortfolioSnapshot,
    PositionSnapshot,
    ReconciliationStore,
    SnapshotSource,
)

NOW = datetime(2026, 8, 4, 17, tzinfo=UTC)


def _snapshot(snapshot_id: str, at: datetime, quantity: int = 4) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        snapshot_id=snapshot_id,
        source=SnapshotSource.ALPACA_PAPER,
        account_id="paper-account",
        cash=Decimal("90000"),
        equity=Decimal("100000"),
        buying_power=Decimal("90000"),
        account_ready=True,
        positions=(PositionSnapshot("SPY", quantity),),
        open_orders=(),
        account_observed_at=at,
        positions_observed_at=at,
        orders_observed_at=at,
    )


def _attest(path: Path, snapshot: PortfolioSnapshot) -> PortfolioSnapshot:
    return ReconciliationStore(path)._record_adapter_snapshot(
        snapshot,
        adapter_version="alpaca-paper-reader-v2",
        paper_origin="https://paper-api.alpaca.markets",
        recorded_at=snapshot.orders_observed_at,
        _capability=_ALPACA_READER_CAPABILITY,
        previous_close_equity=Decimal("99900"),
    )


def test_paper_observation_records_continuity_failures_and_drift(tmp_path: Path) -> None:
    path = tmp_path / "execution.sqlite3"
    baseline = _attest(path, _snapshot("observation-baseline", NOW))
    store = PaperObservationStore(path)
    campaign = store.start(
        campaign_id="paper-week-1",
        baseline_snapshot_id=baseline.snapshot_id,
        maximum_gap_seconds=60,
        duration=timedelta(hours=1),
    )
    assert campaign.expected_positions == (PositionSnapshot("SPY", 4),)
    assert store.assess("paper-week-1", assessed_at=NOW + timedelta(seconds=30)).healthy_now
    assert store.assess("paper-week-1", assessed_at=NOW + timedelta(seconds=61)).reasons == (
        "observation-stale",
    )

    healthy_snapshot = _attest(path, _snapshot("observation-healthy", NOW + timedelta(seconds=50)))
    healthy = store.record_sample("paper-week-1", healthy_snapshot.snapshot_id)
    assert healthy.status == "healthy"
    assert store.record_sample("paper-week-1", healthy_snapshot.snapshot_id) == healthy

    injected_reader = AlpacaPaperReader(
        "test-key",
        "test-secret",
        account_id="paper-account",
        allowed_symbols=frozenset({"SPY"}),
        transport=lambda _request: b"{}",
    )
    failed = record_production_observation(
        store,
        injected_reader,
        campaign_id="paper-week-1",
        observed_at=NOW + timedelta(seconds=55),
    )
    assert failed.status == "read-failed"
    failed_status = store.assess("paper-week-1", assessed_at=NOW + timedelta(seconds=56))
    assert failed_status.reasons == ("paper-read-failed",)
    assert failed_status.failure_count == 1

    drift_snapshot = _attest(
        path, _snapshot("observation-drift", NOW + timedelta(seconds=58), quantity=5)
    )
    drift = store.record_sample("paper-week-1", drift_snapshot.snapshot_id)
    assert drift.status == "drift"
    assert drift.reasons == ("positions-drift",)
    status = store.assess("paper-week-1", assessed_at=NOW + timedelta(seconds=59))
    assert not status.healthy_now
    assert status.success_count == 2
    assert status.drift_count == 1
    assert status.failure_count == 1
    assert status.maximum_observed_gap_seconds == 50
    assert not status.campaign_complete
    assert "observation-stale" in store.assess("paper-week-1", assessed_at=campaign.ends_at).reasons

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER paper_observations_no_update")
        connection.execute(
            "UPDATE paper_observations SET observation_json = '{}' WHERE observation_id = "
            "(SELECT observation_id FROM paper_observations LIMIT 1)"
        )
    with pytest.raises(JournalIntegrityError, match="stored paper observation"):
        PaperObservationStore(path)
