from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from systematic_trading_lab.alpaca_paper import AlpacaPaperReader
from systematic_trading_lab.cli import parser, run
from systematic_trading_lab.config import ConfigurationError, Settings
from systematic_trading_lab.domain import TradingMode
from systematic_trading_lab.execution import ExecutionIntent, ExecutionStore, JournalIntegrityError
from systematic_trading_lab.paper_equivalence import (
    ActionPlan,
    ActionTarget,
    PaperEquivalenceStore,
)
from systematic_trading_lab.paper_observation import (
    PaperObservationStore,
    record_production_observation,
)
from systematic_trading_lab.paper_supervision import observation_supervisor_lock
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
        duration=timedelta(minutes=2),
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

    recovered_snapshot = _attest(
        path, _snapshot("observation-recovered", NOW + timedelta(seconds=118))
    )
    store.record_sample("paper-week-1", recovered_snapshot.snapshot_id)
    recovered_status = store.assess("paper-week-1", assessed_at=campaign.ends_at)
    assert recovered_status.healthy_now
    assert recovered_status.continuity_held
    assert recovered_status.failure_count == 1
    assert recovered_status.drift_count == 1
    assert recovered_status.campaign_reasons == ("historical-drift",)
    assert recovered_status.campaign_passed is False

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER paper_observations_no_update")
        connection.execute(
            "UPDATE paper_observations SET observation_json = '{}' WHERE observation_id = "
            "(SELECT observation_id FROM paper_observations LIMIT 1)"
        )
    with pytest.raises(JournalIntegrityError, match="stored paper observation"):
        PaperObservationStore(path)


def test_completed_campaign_assessment_enforces_historical_gap(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    passing_path = tmp_path / "passing" / "execution.sqlite3"
    baseline = _attest(passing_path, _snapshot("passing-baseline", NOW))
    passing_store = PaperObservationStore(passing_path)
    passing_store.start(
        campaign_id="passing-week",
        baseline_snapshot_id=baseline.snapshot_id,
        maximum_gap_seconds=900,
        duration=timedelta(minutes=30),
    )
    passing_store.record_failure("passing-week", observed_at=NOW + timedelta(minutes=10))
    for name, seconds in (("passing-recovered", 900), ("passing-final", 1800)):
        snapshot = _attest(passing_path, _snapshot(name, NOW + timedelta(seconds=seconds)))
        passing_store.record_sample("passing-week", snapshot.snapshot_id)

    passing = passing_store.assess("passing-week", assessed_at=NOW + timedelta(minutes=30))
    assert passing.healthy_now
    assert passing.campaign_complete
    assert passing.continuity_held
    assert passing.campaign_passed is True
    assert passing.campaign_reasons == ()
    assert passing.failure_count == 1
    assert passing.maximum_gap_seconds == 900
    assert passing.maximum_observed_gap_seconds == 900

    failing_path = tmp_path / "execution.sqlite3"
    baseline = _attest(failing_path, _snapshot("failing-baseline", NOW))
    failing_store = PaperObservationStore(failing_path)
    failing_store.start(
        campaign_id="failing-week",
        baseline_snapshot_id=baseline.snapshot_id,
        maximum_gap_seconds=900,
        duration=timedelta(minutes=30),
    )
    for name, seconds in (("failing-gap", 1030), ("failing-final", 1800)):
        snapshot = _attest(failing_path, _snapshot(name, NOW + timedelta(seconds=seconds)))
        failing_store.record_sample("failing-week", snapshot.snapshot_id)

    with sqlite3.connect(failing_path) as connection:
        evidence_before = connection.execute(
            "SELECT observation_json FROM paper_observations ORDER BY observation_id"
        ).fetchall()
        journal_count_before = connection.execute("SELECT COUNT(*) FROM journal").fetchone()[0]

    failing = failing_store.assess("failing-week", assessed_at=NOW + timedelta(minutes=30))
    assert failing.healthy_now
    assert failing.campaign_complete
    assert not failing.continuity_held
    assert failing.campaign_passed is False
    assert failing.reasons == ()
    assert failing.campaign_reasons == ("maximum-observation-gap-exceeded",)
    assert failing.maximum_gap_seconds == 900
    assert failing.maximum_observed_gap_seconds == 1030

    result = run(
        parser().parse_args(["paper", "assess-observation", "failing-week"]),
        Settings(TradingMode.OFFLINE, tmp_path),
    )
    output = capsys.readouterr().out
    assert result == 1
    assert '"healthy_now": true' in output
    assert '"continuity_held": false' in output
    assert '"campaign_passed": false' in output
    assert '"maximum_gap_seconds": 900' in output

    with sqlite3.connect(failing_path) as connection:
        assert (
            connection.execute(
                "SELECT observation_json FROM paper_observations ORDER BY observation_id"
            ).fetchall()
            == evidence_before
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM journal").fetchone()[0] == journal_count_before
        )


def test_fractional_gap_reports_failed_continuity_conservatively(tmp_path: Path) -> None:
    path = tmp_path / "execution.sqlite3"
    baseline = _attest(path, _snapshot("fractional-baseline", NOW))
    store = PaperObservationStore(path)
    store.start(
        campaign_id="fractional-gap",
        baseline_snapshot_id=baseline.snapshot_id,
        maximum_gap_seconds=900,
        duration=timedelta(minutes=20),
    )
    snapshot = _attest(path, _snapshot("fractional-gap", NOW + timedelta(seconds=900.001)))
    store.record_sample("fractional-gap", snapshot.snapshot_id)

    status = store.assess("fractional-gap", assessed_at=NOW + timedelta(seconds=900.001))

    assert not status.continuity_held
    assert status.maximum_observed_gap_seconds == 901
    assert status.maximum_observed_gap_seconds > status.maximum_gap_seconds


def test_one_shot_observation_writer_respects_supervisor_lock(tmp_path: Path) -> None:
    with (
        observation_supervisor_lock(tmp_path),
        pytest.raises(ConfigurationError, match="another paper observation supervisor"),
    ):
        run(
            parser().parse_args(["paper", "record-observation", "paper-week-1"]),
            Settings(TradingMode.PAPER, tmp_path),
        )


def test_paper_equivalence_binds_intents_and_retains_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "execution.sqlite3"
    baseline = _attest(path, _snapshot("equivalence-baseline", NOW))
    PaperObservationStore(path).start(
        campaign_id="paper-week-1",
        baseline_snapshot_id=baseline.snapshot_id,
        maximum_gap_seconds=60,
        duration=timedelta(hours=1),
    )
    intent = ExecutionIntent(
        idempotency_key="paper-spy",
        strategy_id="strategic-allocation-portfolio",
        strategy_version="1",
        symbol="SPY",
        decision_timestamp=NOW,
        target_weight=None,
        target_quantity=4,
        reason="paper equivalence test",
        source_data_fingerprint="a" * 64,
        configuration_fingerprint="b" * 64,
        reference_price=Decimal("700"),
        expires_at=NOW + timedelta(minutes=5),
    )
    ExecutionStore(path).record_intent(intent, received_at=NOW)
    targets = (ActionTarget("SPY", 4),)
    replay = ActionPlan(
        "replay",
        intent.strategy_id,
        intent.strategy_version,
        intent.source_data_fingerprint,
        intent.configuration_fingerprint,
        targets,
        ("c" * 64,),
    )
    shadow = ActionPlan(
        "shadow",
        intent.strategy_id,
        intent.strategy_version,
        intent.source_data_fingerprint,
        intent.configuration_fingerprint,
        targets,
        ("d" * 64,),
    )
    store = PaperEquivalenceStore(path)
    record = store.record(
        comparison_id="initial-entry",
        campaign_id="paper-week-1",
        replay=replay,
        shadow=shadow,
        paper_intent_keys=(intent.idempotency_key,),
        recorded_at=NOW + timedelta(seconds=1),
    )
    assert record.equivalent
    assert store.get("initial-entry") == record
    assert (
        store.record(
            comparison_id="initial-entry",
            campaign_id="paper-week-1",
            replay=replay,
            shadow=shadow,
            paper_intent_keys=(intent.idempotency_key,),
            recorded_at=NOW + timedelta(seconds=2),
        )
        == record
    )

    mismatch = store.record(
        comparison_id="changed-shadow",
        campaign_id="paper-week-1",
        replay=replay,
        shadow=ActionPlan(
            "shadow",
            intent.strategy_id,
            intent.strategy_version,
            intent.source_data_fingerprint,
            intent.configuration_fingerprint,
            (ActionTarget("SPY", 5),),
            ("e" * 64,),
        ),
        paper_intent_keys=(intent.idempotency_key,),
        recorded_at=NOW + timedelta(seconds=2),
    )
    assert not mismatch.equivalent
    assert mismatch.reasons == ("target-mismatch",)

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER paper_equivalence_records_no_update")
        connection.execute(
            "UPDATE paper_equivalence_records SET record_json = '{}' "
            "WHERE comparison_id = 'initial-entry'"
        )
    with pytest.raises(JournalIntegrityError, match="stored paper equivalence"):
        PaperEquivalenceStore(path)
