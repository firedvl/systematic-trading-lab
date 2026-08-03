import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit
from urllib.request import Request

import pytest

import systematic_trading_lab.alpaca_paper as alpaca_paper
from systematic_trading_lab.alpaca_paper import AlpacaPaperReader
from systematic_trading_lab.execution import ExecutionIntent, JournalIntegrityError
from systematic_trading_lab.experiments import HoldoutAccessError
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.reconciliation import (
    PortfolioSnapshot,
    PositionSnapshot,
    ReconciliationEvidence,
    ReconciliationStore,
    SnapshotSource,
)
from systematic_trading_lab.risk import (
    PaperAuthorization,
    RiskContext,
    RiskLimits,
    RiskStore,
)

NOW = datetime(2026, 8, 3, 20, tzinfo=UTC)


def _limits() -> RiskLimits:
    return RiskLimits(
        configuration_id="test-only-limits",
        account_id="paper-account",
        allowed_symbols=("SPY",),
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
        expires_at=NOW + timedelta(days=30),
    )


def _evidence(*, passed: bool = True) -> dict[str, object]:
    candidate = {
        "strategy_id": "candidate",
        "strategy_version": "1",
        "strategy_family": "trend",
        "code_commit": "reviewed-commit",
        "parameters": {"window": 20},
        "cost_model_version": "cost-v1",
        "execution_model_version": "next-bar-v1",
        "dataset_id": "dataset-1",
        "dataset_fingerprint": fingerprint({"dataset": 1}),
        "universe_id": "universe-1",
        "universe_fingerprint": fingerprint({"universe": 1}),
        "validation_start": "2025-01-01T00:00:00Z",
        "validation_end": "2025-12-31T00:00:00Z",
    }
    qualification: dict[str, object] = {
        "experiment_id": "candidate-1",
        "state": "qualified",
        "gates": [{"gate": "test", "approved": True, "passed": passed}],
    }
    qualification["report_fingerprint"] = fingerprint(qualification)
    report: dict[str, object] = {
        "schema_version": "qualification-evidence-v1",
        "manifest_id": "manifest-1",
        "manifest_fingerprint": fingerprint({"manifest": 1}),
        "proposal_id": "proposal-1",
        "proposal_fingerprint": fingerprint({"proposal": 1}),
        "campaign_id": "campaign-1",
        "candidate_id": "candidate-1",
        "strategy_id": "candidate",
        "candidate_specification": candidate,
        "source_experiment_ids": ["validation-1"],
        "metrics": {},
        "qualification": qualification,
    }
    report["evidence_fingerprint"] = fingerprint(report)
    return report


def _authorization(report: dict[str, object], limits: RiskLimits) -> PaperAuthorization:
    candidate = report["candidate_specification"]
    assert isinstance(candidate, dict)
    return PaperAuthorization(
        authorization_id="paper-auth-1",
        candidate_id="candidate-1",
        strategy_id="candidate",
        strategy_version="1",
        parameters_fingerprint=fingerprint(candidate["parameters"]),
        code_commit="reviewed-commit",
        dataset_id="dataset-1",
        dataset_fingerprint=str(candidate["dataset_fingerprint"]),
        universe_id="universe-1",
        universe_fingerprint=str(candidate["universe_fingerprint"]),
        qualification_evidence_fingerprint=str(report["evidence_fingerprint"]),
        account_id=limits.account_id,
        risk_configuration_fingerprint=limits.configuration_fingerprint,
        authorized_by="paper-reviewer",
        authorization_reason="test authorization",
        authorized_at=NOW,
        expires_at=NOW + timedelta(days=7),
    )


def _intent(report: dict[str, object]) -> ExecutionIntent:
    candidate = report["candidate_specification"]
    assert isinstance(candidate, dict)
    return ExecutionIntent(
        idempotency_key="candidate-1:SPY:2026-08-03",
        strategy_id="candidate",
        strategy_version="1",
        symbol="SPY",
        decision_timestamp=NOW - timedelta(minutes=2),
        target_weight=Decimal("0.25"),
        target_quantity=None,
        reason="daily target",
        source_data_fingerprint=str(candidate["dataset_fingerprint"]),
        configuration_fingerprint=fingerprint(candidate["parameters"]),
        reference_price=Decimal("100"),
        expires_at=NOW + timedelta(minutes=10),
    )


def _context() -> RiskContext:
    observed = NOW - timedelta(seconds=5)
    return RiskContext(
        account_id="paper-account",
        evaluated_at=NOW,
        equity=Decimal("100000"),
        cash=Decimal("70000"),
        buying_power=Decimal("70000"),
        current_gross_exposure=Decimal("20000"),
        current_symbol_notional=Decimal("10000"),
        pending_buy_notional=Decimal("0"),
        pending_order_notional=Decimal("0"),
        open_order_count=0,
        pending_order_count=0,
        orders_last_minute=0,
        daily_pnl=Decimal("0"),
        strategy_drawdown=Decimal("0"),
        quote_price=Decimal("100.10"),
        account_observed_at=observed,
        positions_observed_at=observed,
        orders_observed_at=observed,
        quote_observed_at=observed,
        clock_observed_at=observed,
        regular_session_open=True,
        emergency_disabled=False,
    )


def _flat_snapshot(
    source: SnapshotSource, snapshot_id: str, **changes: object
) -> PortfolioSnapshot:
    value = PortfolioSnapshot(
        snapshot_id=snapshot_id,
        source=source,
        account_id="paper-account",
        cash=Decimal("70000"),
        equity=Decimal("70000"),
        buying_power=Decimal("70000"),
        account_ready=True,
        positions=(),
        open_orders=(),
        account_observed_at=NOW - timedelta(seconds=5),
        positions_observed_at=NOW - timedelta(seconds=5),
        orders_observed_at=NOW - timedelta(seconds=5),
    )
    return replace(value, **cast(Any, changes))


def _record_adapter_snapshot(
    store: ReconciliationStore,
    snapshot: PortfolioSnapshot,
    monkeypatch: pytest.MonkeyPatch,
    *,
    recorded_at: datetime = NOW,
) -> PortfolioSnapshot:
    responses: dict[str, object] = {
        "/v2/account": {
            "id": snapshot.account_id,
            "status": "ACTIVE" if snapshot.account_ready else "ACCOUNT_UPDATED",
            "cash": str(snapshot.cash),
            "equity": str(snapshot.equity),
            "buying_power": str(snapshot.buying_power),
            "account_blocked": not snapshot.account_ready,
            "trading_blocked": False,
            "trade_suspended_by_user": False,
        },
        "/v2/positions": [
            {"symbol": position.symbol, "qty": str(position.quantity)}
            for position in snapshot.positions
        ],
        "/v2/orders": [
            {
                "client_order_id": order.client_order_id,
                "symbol": order.symbol,
                "status": order.status,
                "side": order.side,
                "qty": str(order.quantity),
                "filled_qty": str(order.filled_quantity),
                "type": order.order_type,
                "limit_price": str(order.limit_price) if order.limit_price is not None else None,
                "time_in_force": "day",
                "extended_hours": False,
                "order_class": "simple",
                "notional": None,
                "legs": None,
            }
            for order in snapshot.open_orders
        ],
    }

    def transport(request: Request) -> bytes:
        return json.dumps(responses[urlsplit(request.full_url).path]).encode()

    monkeypatch.setattr(alpaca_paper, "_urlopen_bytes", transport)
    observations = iter(
        (
            snapshot.account_observed_at,
            snapshot.positions_observed_at,
            snapshot.orders_observed_at,
        )
    )
    symbols = frozenset(
        {position.symbol for position in snapshot.positions}
        | {order.symbol for order in snapshot.open_orders}
        | {"SPY"}
    )
    reader = AlpacaPaperReader(
        "test-key",
        "test-secret",
        account_id=snapshot.account_id,
        allowed_symbols=symbols,
        clock=lambda: next(observations),
    )
    return reader.record_portfolio(store, recorded_at=recorded_at)


def test_paper_authorization_is_exact_immutable_and_restart_safe(tmp_path: Path) -> None:
    path = tmp_path / "execution.sqlite3"
    limits = _limits()
    report = _evidence()
    authorization = _authorization(report, limits)

    store = RiskStore(path)
    assert store.authorize_paper(authorization, report, limits) == authorization
    assert store.authorize_paper(authorization, report, limits) == authorization
    assert RiskStore(path).get_paper_authorization("paper-auth-1") == authorization

    with (
        sqlite3.connect(path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="immutable"),
    ):
        connection.execute("UPDATE paper_authorizations SET authorization_json = '{}'")


def test_paper_authorization_rejects_failed_or_changed_evidence(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "execution.sqlite3")
    limits = _limits()
    report = _evidence()
    authorization = _authorization(report, limits)

    with pytest.raises(HoldoutAccessError, match="approved passing gates"):
        store.authorize_paper(authorization, _evidence(passed=False), limits)
    with pytest.raises(HoldoutAccessError, match="differs"):
        store.authorize_paper(replace(authorization, dataset_id="other-dataset"), report, limits)
    with pytest.raises(HoldoutAccessError, match="risk configuration period"):
        store.authorize_paper(
            replace(authorization, expires_at=limits.expires_at + timedelta(seconds=1)),
            report,
            limits,
        )


def test_durable_risk_decision_uses_persistent_emergency_state(tmp_path: Path) -> None:
    path = tmp_path / "execution.sqlite3"
    limits = _limits()
    report = _evidence()
    authorization = _authorization(report, limits)
    intent = _intent(report)
    store = RiskStore(path)
    store.record_intent(intent, received_at=NOW - timedelta(minutes=1))
    store.authorize_paper(authorization, report, limits)

    receipt = store.record_risk_decision(
        intent.idempotency_key, authorization.authorization_id, limits, _context()
    )
    replay = RiskStore(path).record_risk_decision(
        intent.idempotency_key, authorization.authorization_id, limits, _context()
    )

    assert replay == receipt
    assert not receipt.approved
    assert receipt.reasons == ("emergency-disabled",)


def test_reconciliation_store_persists_flat_baseline_and_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "execution.sqlite3"
    limits = _limits()
    report = _evidence()
    authorization = _authorization(report, limits)
    store = ReconciliationStore(path)
    store.authorize_paper(authorization, report, limits)
    expected = _flat_snapshot(SnapshotSource.LOCAL_EXPECTED, "expected-1")
    caller_observed = _flat_snapshot(SnapshotSource.ALPACA_PAPER, "caller-observed")
    store.record_snapshot(expected, recorded_at=NOW)
    store.record_snapshot(caller_observed, recorded_at=NOW)
    with pytest.raises(HoldoutAccessError, match="matching fresh flat state"):
        store.create_flat_baseline(
            baseline_id="baseline-1",
            authorization_id=authorization.authorization_id,
            expected_snapshot_id=expected.snapshot_id,
            observed_snapshot_id=caller_observed.snapshot_id,
            limits=limits,
            operator="test-operator",
            reason="flat test baseline",
            created_at=NOW,
        )
    with pytest.raises(PermissionError, match="production Alpaca reader"):
        store._record_adapter_snapshot(
            caller_observed,
            adapter_version="alpaca-paper-reader-v1",
            paper_origin="https://paper-api.alpaca.markets",
            recorded_at=NOW,
            _capability=object(),
        )
    observed = _record_adapter_snapshot(store, caller_observed, monkeypatch)
    baseline = store.create_flat_baseline(
        baseline_id="baseline-1",
        authorization_id=authorization.authorization_id,
        expected_snapshot_id=expected.snapshot_id,
        observed_snapshot_id=observed.snapshot_id,
        limits=limits,
        operator="test-operator",
        reason="flat test baseline",
        created_at=NOW,
    )

    clean = store.record_reconciliation(
        baseline_id=baseline.baseline_id,
        observed_snapshot_id=observed.snapshot_id,
        compared_at=NOW,
        unresolved_mutations=0,
    )
    raw_snapshot = _flat_snapshot(SnapshotSource.ALPACA_PAPER, "observed-raw")
    store.record_snapshot(raw_snapshot, recorded_at=NOW)
    with pytest.raises(ValueError, match="durable evidence"):
        store.record_reconciliation(
            baseline_id=baseline.baseline_id,
            observed_snapshot_id=raw_snapshot.snapshot_id,
            compared_at=NOW,
            unresolved_mutations=0,
        )
    dirty_snapshot = _flat_snapshot(
        SnapshotSource.ALPACA_PAPER, "observed-2", cash=Decimal("69999")
    )
    dirty_snapshot = _record_adapter_snapshot(store, dirty_snapshot, monkeypatch)
    dirty = store.record_reconciliation(
        baseline_id=baseline.baseline_id,
        observed_snapshot_id=dirty_snapshot.snapshot_id,
        compared_at=NOW,
        unresolved_mutations=1,
    )

    assert clean.result.clean
    assert not dirty.result.clean
    assert dirty.result.reasons == ("cash-mismatch", "unresolved-broker-mutation")
    ReconciliationStore(path)


def test_reconciliation_store_rejects_nonflat_or_changed_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "execution.sqlite3"
    limits = _limits()
    report = _evidence()
    authorization = _authorization(report, limits)
    store = ReconciliationStore(path)
    store.authorize_paper(authorization, report, limits)
    expected = _flat_snapshot(
        SnapshotSource.LOCAL_EXPECTED,
        "expected-positioned",
        positions=(PositionSnapshot("SPY", 1),),
        equity=Decimal("70100"),
    )
    observed = _flat_snapshot(
        SnapshotSource.ALPACA_PAPER,
        "observed-positioned",
        positions=(PositionSnapshot("SPY", 1),),
        equity=Decimal("70100"),
    )
    store.record_snapshot(expected, recorded_at=NOW)
    observed = _record_adapter_snapshot(store, observed, monkeypatch)

    with pytest.raises(HoldoutAccessError, match="flat state"):
        store.create_flat_baseline(
            baseline_id="unsafe-baseline",
            authorization_id=authorization.authorization_id,
            expected_snapshot_id=expected.snapshot_id,
            observed_snapshot_id=observed.snapshot_id,
            limits=limits,
            operator="test-operator",
            reason="must reject positions",
            created_at=NOW,
        )
    with pytest.raises(JournalIntegrityError, match="different normalized state"):
        store.record_snapshot(replace(expected, cash=Decimal("1")), recorded_at=NOW)


def test_paper_snapshot_attestation_is_immutable_and_journal_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "execution.sqlite3"
    snapshot = _flat_snapshot(SnapshotSource.ALPACA_PAPER, "observed-attested")
    store = ReconciliationStore(path)
    snapshot = _record_adapter_snapshot(store, snapshot, monkeypatch)

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER paper_snapshot_attestations_no_update")
        connection.execute("UPDATE paper_snapshot_attestations SET attestation_json = '{}'")

    with pytest.raises(JournalIntegrityError, match="attestation"):
        ReconciliationStore(path)


def test_emergency_clear_readiness_requires_latest_three_stable_clean_samples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ReconciliationStore(tmp_path / "execution.sqlite3")
    limits = _limits()
    report = _evidence()
    authorization = _authorization(report, limits)
    store.authorize_paper(authorization, report, limits)
    expected = _flat_snapshot(SnapshotSource.LOCAL_EXPECTED, "stable-expected")
    first_observed = _record_adapter_snapshot(
        store,
        _flat_snapshot(
            SnapshotSource.ALPACA_PAPER,
            "stable-observed-0",
            account_observed_at=NOW,
            positions_observed_at=NOW,
            orders_observed_at=NOW,
        ),
        monkeypatch,
    )
    store.record_snapshot(expected, recorded_at=NOW)
    baseline = store.create_flat_baseline(
        baseline_id="stable-baseline",
        authorization_id=authorization.authorization_id,
        expected_snapshot_id=expected.snapshot_id,
        observed_snapshot_id=first_observed.snapshot_id,
        limits=limits,
        operator="test-operator",
        reason="stable readiness test",
        created_at=NOW,
    )
    samples: list[ReconciliationEvidence] = [
        store.record_reconciliation(
            baseline_id=baseline.baseline_id,
            observed_snapshot_id=first_observed.snapshot_id,
            compared_at=NOW,
            unresolved_mutations=0,
        )
    ]
    assert store.assess_emergency_clear_readiness(
        baseline_id=baseline.baseline_id, limits=limits, assessed_at=NOW
    ).reasons == ("insufficient-clean-samples",)

    for seconds in (4, 8, 13, 18):
        observed_at = NOW + timedelta(seconds=seconds)
        observed = _flat_snapshot(
            SnapshotSource.ALPACA_PAPER,
            f"stable-observed-{seconds}",
            account_observed_at=observed_at,
            positions_observed_at=observed_at,
            orders_observed_at=observed_at,
        )
        observed = _record_adapter_snapshot(store, observed, monkeypatch, recorded_at=observed_at)
        samples.append(
            store.record_reconciliation(
                baseline_id=baseline.baseline_id,
                observed_snapshot_id=observed.snapshot_id,
                compared_at=observed_at,
                unresolved_mutations=0,
            )
        )
        if seconds == 8:
            assert (
                "samples-not-stable"
                in store.assess_emergency_clear_readiness(
                    baseline_id=baseline.baseline_id,
                    limits=limits,
                    assessed_at=observed_at,
                ).reasons
            )

    readiness = store.assess_emergency_clear_readiness(
        baseline_id=baseline.baseline_id,
        limits=limits,
        assessed_at=NOW + timedelta(seconds=18),
    )
    assert readiness.ready
    assert readiness.evidence_ids == tuple(item.evidence_id for item in samples[-3:])
    assert readiness.proof_fingerprint
    cleared = store.clear_emergency(
        clear_id="clear-stable-1",
        baseline_id=baseline.baseline_id,
        limits=limits,
        operator="test-operator",
        reason="stable proof reviewed",
        cleared_at=NOW + timedelta(seconds=18),
    )
    assert not cleared.disabled
    assert cleared.generation == 2
    intent = replace(
        _intent(report),
        decision_timestamp=NOW + timedelta(seconds=16),
        expires_at=NOW + timedelta(minutes=20),
    )
    store.record_intent(intent, received_at=NOW + timedelta(seconds=17))
    risk_context = replace(
        _context(),
        evaluated_at=NOW + timedelta(seconds=18),
        account_observed_at=NOW + timedelta(seconds=13),
        positions_observed_at=NOW + timedelta(seconds=13),
        orders_observed_at=NOW + timedelta(seconds=13),
        quote_observed_at=NOW + timedelta(seconds=13),
        clock_observed_at=NOW + timedelta(seconds=13),
    )
    reserved = store.record_risk_decision(
        intent.idempotency_key, authorization.authorization_id, limits, risk_context
    )
    assert reserved.approved
    assert (
        RiskStore(store.path).record_risk_decision(
            intent.idempotency_key, authorization.authorization_id, limits, risk_context
        )
        == reserved
    )
    assert (
        store.clear_emergency(
            clear_id="clear-stable-1",
            baseline_id=baseline.baseline_id,
            limits=limits,
            operator="test-operator",
            reason="stable proof reviewed",
            cleared_at=NOW + timedelta(seconds=18),
        )
        == cleared
    )
    with pytest.raises(JournalIntegrityError, match="different content"):
        store.clear_emergency(
            clear_id="clear-stable-1",
            baseline_id=baseline.baseline_id,
            limits=limits,
            operator="other-operator",
            reason="changed",
            cleared_at=NOW + timedelta(seconds=18),
        )
    stale = store.assess_emergency_clear_readiness(
        baseline_id=baseline.baseline_id,
        limits=limits,
        assessed_at=NOW + timedelta(seconds=49),
    )
    assert stale.reasons == ("emergency-already-clear", "latest-sample-stale-or-future")
    mismatched = store.assess_emergency_clear_readiness(
        baseline_id=baseline.baseline_id,
        limits=replace(limits, min_reconciliation_stability_seconds=6),
        assessed_at=NOW + timedelta(seconds=18),
    )
    assert "authority-or-limits-mismatch" in mismatched.reasons

    dirty_at = NOW + timedelta(seconds=23)
    dirty = _flat_snapshot(
        SnapshotSource.ALPACA_PAPER,
        "stable-observed-dirty",
        cash=Decimal("69999"),
        account_observed_at=dirty_at,
        positions_observed_at=dirty_at,
        orders_observed_at=dirty_at,
    )
    dirty = _record_adapter_snapshot(store, dirty, monkeypatch, recorded_at=dirty_at)
    store.record_reconciliation(
        baseline_id=baseline.baseline_id,
        observed_snapshot_id=dirty.snapshot_id,
        compared_at=dirty_at,
        unresolved_mutations=1,
    )
    assert store.get_emergency().disabled
    reset = store.assess_emergency_clear_readiness(
        baseline_id=baseline.baseline_id, limits=limits, assessed_at=dirty_at
    )
    assert not reset.ready
    assert reset.reasons == ("latest-samples-not-clean",)
    assert ReconciliationStore(store.path).get_emergency().disabled
