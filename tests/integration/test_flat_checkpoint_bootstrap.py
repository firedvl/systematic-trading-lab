"""Flat-baseline settlement bootstrap leaves execution lineage empty."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import systematic_trading_lab.reconciliation as reconciliation
from systematic_trading_lab.execution import ExecutionIntent, JournalIntegrityError
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.position_settlement import (
    PositionSettlementStore,
    _decode_evidence,
)
from systematic_trading_lab.reconciliation import (
    PortfolioSnapshot,
    ReconciliationStore,
    SnapshotSource,
)
from systematic_trading_lab.risk import PaperAuthorization, RiskLimits
from systematic_trading_lab.risk_context import AttestedRiskContextStore
from systematic_trading_lab.risk_inputs import (
    _CAPABILITY,
    DATA_ORIGIN,
    PAPER_ORIGIN,
    LatestQuoteEvidence,
    MarketClockEvidence,
    RiskInputEvidence,
    RiskInputEvidenceStore,
)
from systematic_trading_lab.strategy_equity import StrategyEquityStore

NOW = datetime(2026, 8, 4, 12, tzinfo=UTC)


def _limits() -> RiskLimits:
    return RiskLimits(
        configuration_id="flat-bootstrap-test",
        account_id="paper-account",
        allowed_symbols=("SPY",),
        max_order_notional=Decimal("4000"),
        max_position_notional=Decimal("4000"),
        max_gross_exposure=Decimal("10000"),
        strategy_capital_allocation=Decimal("10000"),
        strategy_fill_cost_bps=Decimal("10"),
        min_cash=Decimal("90000"),
        max_open_orders=1,
        max_orders_per_minute=1,
        max_daily_loss=Decimal("100"),
        max_strategy_drawdown=Decimal("0.10"),
        max_price_deviation_bps=Decimal("25"),
        max_snapshot_age_seconds=30,
        min_reconciliation_stability_seconds=5,
        reviewed_by="reviewer",
        review_reason="test",
        effective_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=1),
    )


def _report() -> dict[str, object]:
    candidate = {
        "strategy_id": "strategy",
        "strategy_version": "1",
        "strategy_family": "trend",
        "code_commit": "a" * 40,
        "parameters": {"window": 20},
        "cost_model_version": "cost-v1",
        "execution_model_version": "next-bar-v1",
        "dataset_id": "dataset",
        "dataset_fingerprint": "2" * 64,
        "universe_id": "universe",
        "universe_fingerprint": "3" * 64,
        "validation_start": "2025-01-01T00:00:00Z",
        "validation_end": "2025-12-31T00:00:00Z",
    }
    qualification: dict[str, object] = {
        "experiment_id": "candidate",
        "state": "qualified",
        "gates": [{"gate": "test", "approved": True, "passed": True}],
    }
    qualification["report_fingerprint"] = fingerprint(qualification)
    report: dict[str, object] = {
        "schema_version": "qualification-evidence-v1",
        "manifest_id": "manifest",
        "manifest_fingerprint": "5" * 64,
        "proposal_id": "proposal",
        "proposal_fingerprint": "6" * 64,
        "campaign_id": "campaign",
        "candidate_id": "candidate",
        "strategy_id": "strategy",
        "candidate_specification": candidate,
        "source_experiment_ids": ["experiment"],
        "metrics": {},
        "qualification": qualification,
    }
    report["evidence_fingerprint"] = fingerprint(report)
    return report


def _authorization(limits: RiskLimits, report: dict[str, object]) -> PaperAuthorization:
    return PaperAuthorization(
        authorization_id="flat-auth",
        candidate_id="candidate",
        strategy_id="strategy",
        strategy_version="1",
        parameters_fingerprint=fingerprint({"window": 20}),
        code_commit="a" * 40,
        dataset_id="dataset",
        dataset_fingerprint="2" * 64,
        universe_id="universe",
        universe_fingerprint="3" * 64,
        qualification_evidence_fingerprint=str(report["evidence_fingerprint"]),
        account_id=limits.account_id,
        risk_configuration_fingerprint=limits.configuration_fingerprint,
        authorized_by="reviewer",
        authorization_reason="test",
        authorized_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )


def _snapshot(snapshot_id: str, observed_at: datetime, source: SnapshotSource) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        snapshot_id=snapshot_id,
        source=source,
        account_id="paper-account",
        cash=Decimal("100000"),
        equity=Decimal("100000"),
        buying_power=Decimal("100000"),
        account_ready=True,
        positions=(),
        open_orders=(),
        account_observed_at=observed_at,
        positions_observed_at=observed_at,
        orders_observed_at=observed_at,
    )


def _attest(store: ReconciliationStore, snapshot: PortfolioSnapshot) -> PortfolioSnapshot:
    return store._record_adapter_snapshot(
        snapshot,
        adapter_version="alpaca-paper-reader-v2",
        paper_origin="https://paper-api.alpaca.markets",
        recorded_at=snapshot.account_observed_at,
        previous_close_equity=snapshot.equity,
        _capability=reconciliation._ALPACA_READER_CAPABILITY,
    )


def _flat_ready_store(tmp_path: Path) -> tuple[Any, ...]:
    limits = _limits()
    report = _report()
    authorization = _authorization(limits, report)
    store = ReconciliationStore(tmp_path / "flat.sqlite3")
    store.authorize_paper(authorization, report, limits)
    expected = _snapshot("expected", NOW, SnapshotSource.LOCAL_EXPECTED)
    store.record_snapshot(expected, recorded_at=NOW)
    first = _attest(store, _snapshot("first", NOW, SnapshotSource.ALPACA_PAPER))
    baseline = store.create_flat_baseline(
        baseline_id="flat-baseline",
        authorization_id=authorization.authorization_id,
        expected_snapshot_id=expected.snapshot_id,
        observed_snapshot_id=first.snapshot_id,
        limits=limits,
        operator="operator",
        reason="flat bootstrap",
        created_at=NOW,
    )
    RiskInputEvidenceStore(store.path)
    strategy_baseline = store.create_strategy_equity_baseline(
        baseline_id="flat-strategy-equity",
        reconciliation_baseline_id=baseline.baseline_id,
        limits=limits,
        operator="operator",
        reason="flat bootstrap",
        created_at=NOW,
    )
    for second in (6, 12, 18):
        observed_at = NOW + timedelta(seconds=second)
        observed = _attest(
            store, _snapshot(f"stable-{second}", observed_at, SnapshotSource.ALPACA_PAPER)
        )
        store.record_reconciliation(
            baseline_id=baseline.baseline_id,
            observed_snapshot_id=observed.snapshot_id,
            compared_at=observed_at,
            unresolved_mutations=0,
        )
    store.clear_emergency(
        clear_id="clear-flat",
        baseline_id=baseline.baseline_id,
        limits=limits,
        operator="operator",
        reason="clean samples",
        cleared_at=NOW + timedelta(seconds=18),
    )
    observed_at = NOW + timedelta(seconds=20)
    observed = _attest(store, _snapshot("post-clear", observed_at, SnapshotSource.ALPACA_PAPER))
    evidence = store.record_reconciliation(
        baseline_id=baseline.baseline_id,
        observed_snapshot_id=observed.snapshot_id,
        compared_at=observed_at,
        unresolved_mutations=0,
    )
    return store, limits, baseline, strategy_baseline, observed, evidence, observed_at


def test_flat_settlement_has_no_fabricated_execution_lineage(tmp_path: Path) -> None:
    store, limits, baseline, _, observed, reconciliation_evidence, settled_at = _flat_ready_store(
        tmp_path
    )
    settlement_store = PositionSettlementStore(store.path)
    proof = settlement_store.record_flat_baseline_settlement(
        proof_id="flat-proof",
        baseline_id=baseline.baseline_id,
        observed_snapshot_id=observed.snapshot_id,
        reconciliation_evidence_id=reconciliation_evidence.evidence_id,
        limits=limits,
        settled_at=settled_at,
    )

    assert proof.settlement_mode == "flat-baseline-v1"
    assert proof.advance_fingerprint == ""
    assert proof.terminal_orders == ()
    assert (
        settlement_store.record_flat_baseline_settlement(
            proof_id="flat-proof",
            baseline_id=baseline.baseline_id,
            observed_snapshot_id=observed.snapshot_id,
            reconciliation_evidence_id=reconciliation_evidence.evidence_id,
            limits=limits,
            settled_at=settled_at,
        )
        == proof
    )
    with settlement_store._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM expected_position_advances").fetchone() == (
            0,
        )
        assert connection.execute("SELECT COUNT(*) FROM broker_events").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM capacity_reservations").fetchone() == (0,)


def test_flat_settlement_rejects_preclear_or_tampered_lineage(tmp_path: Path) -> None:
    store, limits, baseline, _, observed, reconciliation_evidence, settled_at = _flat_ready_store(
        tmp_path
    )
    settlement_store = PositionSettlementStore(store.path)
    with pytest.raises(JournalIntegrityError, match="not complete and current"):
        settlement_store.record_flat_baseline_settlement(
            proof_id="too-early",
            baseline_id=baseline.baseline_id,
            observed_snapshot_id=observed.snapshot_id,
            reconciliation_evidence_id=reconciliation_evidence.evidence_id,
            limits=limits,
            settled_at=NOW + timedelta(seconds=18),
        )
    proof = settlement_store.record_flat_baseline_settlement(
        proof_id="flat-proof",
        baseline_id=baseline.baseline_id,
        observed_snapshot_id=observed.snapshot_id,
        reconciliation_evidence_id=reconciliation_evidence.evidence_id,
        limits=limits,
        settled_at=settled_at,
    )
    with settlement_store._connect() as connection:
        connection.execute("DROP TRIGGER position_settlement_evidence_no_update")
        connection.execute(
            "UPDATE position_settlement_evidence SET evidence_json = ? WHERE proof_id = ?",
            ("{}", proof.proof_id),
        )
        connection.commit()
    with pytest.raises(JournalIntegrityError, match="stored position settlement"):
        PositionSettlementStore(store.path)


def test_flat_checkpoint_can_supply_the_first_attested_risk_context(tmp_path: Path) -> None:
    store, limits, baseline, strategy_baseline, observed, reconciliation_evidence, now = (
        _flat_ready_store(tmp_path)
    )
    settlement = PositionSettlementStore(store.path).record_flat_baseline_settlement(
        proof_id="flat-proof",
        baseline_id=baseline.baseline_id,
        observed_snapshot_id=observed.snapshot_id,
        reconciliation_evidence_id=reconciliation_evidence.evidence_id,
        limits=limits,
        settled_at=now,
    )
    quote = LatestQuoteEvidence("SPY", Decimal("100"), Decimal("100.1"), 1, 1, now, now)
    clock = MarketClockEvidence(
        "NYSE",
        "core",
        True,
        now,
        now + timedelta(days=1),
        now + timedelta(hours=1),
        now,
    )
    risk_input = RiskInputEvidence(
        portfolio_snapshot_id=observed.snapshot_id,
        portfolio_snapshot_fingerprint=observed.snapshot_fingerprint,
        portfolio_attestation_fingerprint=settlement.attestation_fingerprint,
        authorization_id=baseline.authorization_id,
        account_id=limits.account_id,
        risk_configuration_fingerprint=limits.configuration_fingerprint,
        maximum_age_seconds=limits.max_snapshot_age_seconds,
        quotes=(quote,),
        clock=clock,
        data_origin=DATA_ORIGIN,
        paper_origin=PAPER_ORIGIN,
        quote_path="/v2/stocks/quotes/latest",
        clock_path="/v3/clock",
        feed="iex",
        adapter_version="alpaca-risk-input-reader-v1",
        completed_at=now,
    )
    RiskInputEvidenceStore(store.path)._record(risk_input, recorded_at=now, capability=_CAPABILITY)
    checkpoint = StrategyEquityStore(store.path).record_flat_baseline_checkpoint(
        strategy_equity_baseline_id=strategy_baseline.baseline_id,
        settlement_proof_id=settlement.proof_id,
        risk_input_evidence_id=risk_input.evidence_id,
        limits=limits,
        marked_at=now,
    )
    refresh_time = now + timedelta(seconds=1)
    refreshed_risk_input = replace(
        risk_input,
        quotes=(replace(quote, provider_timestamp=refresh_time, observed_at=refresh_time),),
        clock=replace(clock, provider_timestamp=refresh_time, observed_at=refresh_time),
        completed_at=refresh_time,
    )
    RiskInputEvidenceStore(store.path)._record(
        refreshed_risk_input,
        recorded_at=refresh_time,
        capability=_CAPABILITY,
    )
    refreshed = StrategyEquityStore(store.path).record_flat_baseline_checkpoint(
        strategy_equity_baseline_id=strategy_baseline.baseline_id,
        settlement_proof_id=settlement.proof_id,
        risk_input_evidence_id=refreshed_risk_input.evidence_id,
        limits=limits,
        marked_at=refresh_time,
    )
    context = AttestedRiskContextStore(store.path).derive(
        authorization_id=baseline.authorization_id,
        symbol="SPY",
        limits=limits,
        evaluated_at=refresh_time,
    )

    assert checkpoint.checkpoint_mode == "flat-baseline-v1"
    assert checkpoint.fill_event_ids == ()
    assert checkpoint.strategy_equity == limits.strategy_capital_allocation
    assert refreshed.prior_checkpoint_fingerprint == checkpoint.checkpoint_fingerprint
    assert refreshed.checkpoint_mode == "flat-baseline-v1"
    assert context.strategy_equity_checkpoint_fingerprint == refreshed.checkpoint_fingerprint
    assert context.context.current_gross_exposure == 0
    assert not context.context.emergency_disabled

    intent = ExecutionIntent(
        idempotency_key="flat-bootstrap:SPY",
        strategy_id="strategy",
        strategy_version="1",
        symbol="SPY",
        decision_timestamp=refresh_time,
        target_weight=None,
        target_quantity=1,
        reason="verify post-reservation settlement history",
        source_data_fingerprint="2" * 64,
        configuration_fingerprint=fingerprint({"window": 20}),
        reference_price=Decimal("100.1"),
        expires_at=refresh_time + timedelta(minutes=10),
    )
    store.record_intent(intent, received_at=refresh_time)
    assert (
        AttestedRiskContextStore(store.path)
        .record_attested_risk_decision(
            intent_id=intent.idempotency_key,
            authorization_id=baseline.authorization_id,
            limits=limits,
            evaluated_at=refresh_time,
        )
        .approved
    )
    assert (
        AttestedRiskContextStore(store.path)
        .derive(
            authorization_id=baseline.authorization_id,
            symbol="SPY",
            limits=limits,
            evaluated_at=refresh_time,
        )
        .context.pending_order_count
        == 1
    )


def test_legacy_fill_settlement_decodes_without_the_new_fields() -> None:
    value = {
        "proof_id": "legacy",
        "baseline_id": "baseline",
        "authorization_id": "authorization",
        "account_id": "account",
        "risk_configuration_fingerprint": "a" * 64,
        "advance_fingerprint": "b" * 64,
        "observed_snapshot_id": "snapshot",
        "observed_snapshot_fingerprint": "c" * 64,
        "attestation_fingerprint": "d" * 64,
        "terminal_orders": [],
        "emergency_generation": 1,
        "settled_at": "2026-08-04T12:00:00Z",
    }
    decoded = _decode_evidence(value)
    assert decoded.settlement_mode == "fill-settlement-v1"
    assert decoded.reconciliation_evidence_id is None


def test_flat_settlement_wraps_corrupt_reconciliation_as_integrity_error(
    tmp_path: Path,
) -> None:
    store, limits, baseline, _, observed, reconciliation_evidence, settled_at = _flat_ready_store(
        tmp_path
    )
    PositionSettlementStore(store.path).record_flat_baseline_settlement(
        proof_id="flat-proof",
        baseline_id=baseline.baseline_id,
        observed_snapshot_id=observed.snapshot_id,
        reconciliation_evidence_id=reconciliation_evidence.evidence_id,
        limits=limits,
        settled_at=settled_at,
    )
    with store._connect() as connection:
        connection.execute("DROP TRIGGER reconciliation_evidence_no_update")
        connection.execute(
            "UPDATE reconciliation_evidence SET evidence_json = '{}' WHERE evidence_id = ?",
            (reconciliation_evidence.evidence_id,),
        )
        connection.commit()

    with pytest.raises(JournalIntegrityError, match="stored position settlement"):
        PositionSettlementStore(store.path)
