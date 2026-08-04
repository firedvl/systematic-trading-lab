import json
import shutil
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.message import Message
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request

import pytest

import systematic_trading_lab.alpaca_paper as alpaca_paper
import systematic_trading_lab.reconciliation as reconciliation
import systematic_trading_lab.risk_inputs as risk_inputs
from systematic_trading_lab.alpaca_paper import AlpacaPaperReader
from systematic_trading_lab.broker_events import (
    BrokerEventStore,
    BrokerOrderEvent,
    OrderLookupNotFoundEvidence,
)
from systematic_trading_lab.execution import ExecutionIntent, JournalIntegrityError
from systematic_trading_lab.experiments import HoldoutAccessError
from systematic_trading_lab.fingerprints import canonical_json, canonicalize, fingerprint
from systematic_trading_lab.orders import OrderLifecycleStore, OrderState, build_order_delta
from systematic_trading_lab.position_settlement import PositionSettlementStore
from systematic_trading_lab.reconciliation import (
    PortfolioSnapshot,
    PositionSnapshot,
    ReconciliationEvidence,
    ReconciliationStore,
    SnapshotSource,
)
from systematic_trading_lab.recovery import SubmissionRecoveryStore
from systematic_trading_lab.risk import (
    PaperAuthorization,
    RiskContext,
    RiskLimits,
    RiskStore,
)
from systematic_trading_lab.risk_context import AttestedRiskContextStore
from systematic_trading_lab.risk_inputs import (
    AlpacaRiskInputError,
    AlpacaRiskInputReader,
    RiskInputEvidenceStore,
)
from systematic_trading_lab.strategy_equity import StrategyEquityStore

NOW = datetime(2026, 8, 3, 20, tzinfo=UTC)


def _limits() -> RiskLimits:
    return RiskLimits(
        configuration_id="test-only-limits",
        account_id="paper-account",
        allowed_symbols=("SPY",),
        max_order_notional=Decimal("30000"),
        max_position_notional=Decimal("40000"),
        max_gross_exposure=Decimal("90000"),
        strategy_capital_allocation=Decimal("50000"),
        strategy_fill_cost_bps=Decimal("10"),
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
    previous_close_equity: Decimal | None = None,
) -> PortfolioSnapshot:
    responses: dict[str, object] = {
        "/v2/account": {
            "id": snapshot.account_id,
            "status": "ACTIVE" if snapshot.account_ready else "ACCOUNT_UPDATED",
            "cash": str(snapshot.cash),
            "equity": str(snapshot.equity),
            "last_equity": str(previous_close_equity or snapshot.equity),
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


def test_strategy_equity_baseline_binds_allocation_and_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "execution.sqlite3"
    RiskStore(path)
    store = ReconciliationStore(path)
    limits = _limits()
    report = _evidence()
    authorization = _authorization(report, limits)
    store.authorize_paper(authorization, report, limits)
    expected = _flat_snapshot(SnapshotSource.LOCAL_EXPECTED, "equity-expected")
    observed = _record_adapter_snapshot(
        store,
        _flat_snapshot(SnapshotSource.ALPACA_PAPER, "equity-observed"),
        monkeypatch,
    )
    store.record_snapshot(expected, recorded_at=NOW)
    reconciliation_baseline = store.create_flat_baseline(
        baseline_id="equity-reconciliation-baseline",
        authorization_id=authorization.authorization_id,
        expected_snapshot_id=expected.snapshot_id,
        observed_snapshot_id=observed.snapshot_id,
        limits=limits,
        operator="test-operator",
        reason="strategy equity test",
        created_at=NOW,
    )

    with pytest.raises(HoldoutAccessError, match="strategy equity baseline is missing"):
        ReconciliationStore(path).get_strategy_equity_baseline(authorization.authorization_id)

    baseline = store.create_strategy_equity_baseline(
        baseline_id="strategy-equity-baseline-1",
        reconciliation_baseline_id=reconciliation_baseline.baseline_id,
        limits=limits,
        operator="test-operator",
        reason="test-only capital allocation",
        created_at=NOW,
    )

    assert baseline.allocated_capital == Decimal("50000")
    assert baseline.authorization_id == authorization.authorization_id
    assert baseline.authorization_fingerprint == authorization.authorization_fingerprint
    assert baseline.reconciliation_baseline_fingerprint == fingerprint(reconciliation_baseline)
    assert baseline.strategy_id == authorization.strategy_id
    assert baseline.strategy_version == authorization.strategy_version
    assert baseline.risk_configuration_fingerprint == limits.configuration_fingerprint
    assert store.get_strategy_equity_baseline(authorization.authorization_id) == baseline
    assert (
        store.create_strategy_equity_baseline(
            baseline_id=baseline.baseline_id,
            reconciliation_baseline_id=reconciliation_baseline.baseline_id,
            limits=limits,
            operator="test-operator",
            reason="test-only capital allocation",
            created_at=NOW,
        )
        == baseline
    )
    with pytest.raises(HoldoutAccessError, match="matching active authority"):
        store.create_strategy_equity_baseline(
            baseline_id="changed-allocation",
            reconciliation_baseline_id=reconciliation_baseline.baseline_id,
            limits=replace(limits, strategy_capital_allocation=Decimal("50001")),
            operator="test-operator",
            reason="must reject changed allocation",
            created_at=NOW,
        )

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER strategy_equity_baselines_no_update")
        connection.execute("UPDATE strategy_equity_baselines SET baseline_json = '{}'")
    with pytest.raises(JournalIntegrityError, match="strategy equity baseline"):
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
    snapshot = _record_adapter_snapshot(
        store, snapshot, monkeypatch, previous_close_equity=Decimal("71000")
    )
    daily_pnl = ReconciliationStore(path).account_daily_pnl(snapshot.snapshot_id)
    assert daily_pnl.equity == Decimal("70000")
    assert daily_pnl.previous_close_equity == Decimal("71000")
    assert daily_pnl.daily_pnl == Decimal("-1000")

    legacy = ReconciliationStore(tmp_path / "legacy-execution.sqlite3")
    legacy_snapshot = _flat_snapshot(SnapshotSource.ALPACA_PAPER, "legacy-observed")
    legacy._record_adapter_snapshot(
        legacy_snapshot,
        adapter_version="alpaca-paper-reader-v1",
        paper_origin="https://paper-api.alpaca.markets",
        recorded_at=NOW,
        _capability=reconciliation._ALPACA_READER_CAPABILITY,
    )
    ReconciliationStore(legacy.path)
    with pytest.raises(ValueError, match="lacks prior-close"):
        legacy.account_daily_pnl(legacy_snapshot.snapshot_id)

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER paper_snapshot_attestations_no_update")
        connection.execute("UPDATE paper_snapshot_attestations SET attestation_json = '{}'")

    with pytest.raises(JournalIntegrityError, match="attestation"):
        ReconciliationStore(path)


def test_emergency_clear_readiness_requires_latest_three_stable_clean_samples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing_path = tmp_path / "missing-execution.sqlite3"
    with pytest.raises(JournalIntegrityError, match="database is missing"):
        SubmissionRecoveryStore(missing_path)
    assert not missing_path.exists()
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
    strategy_equity_baseline = store.create_strategy_equity_baseline(
        baseline_id="stable-strategy-equity-baseline",
        reconciliation_baseline_id=baseline.baseline_id,
        limits=limits,
        operator="test-operator",
        reason="test-only strategy allocation",
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
        pending_buy_notional=Decimal("60000"),
        pending_order_notional=Decimal("60000"),
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
    with sqlite3.connect(store.path) as connection:
        decision_json = connection.execute(
            "SELECT decision_json FROM risk_decisions WHERE decision_id = ?",
            (reserved.decision_id,),
        ).fetchone()
    assert decision_json is not None
    assert json.loads(decision_json[0])["context_fingerprint"] != risk_context.context_fingerprint
    temporal_path = tmp_path / "temporal-reservations.sqlite3"
    shutil.copy2(store.path, temporal_path)
    temporal = RiskStore(temporal_path)
    temporal_reservation_id = fingerprint({"decision_id": reserved.decision_id})
    with temporal._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        temporal._verify_connection(connection)
        temporal._verify_emergency(connection)
        temporal._verify_authorizations(connection)
        temporal._verify_decisions(connection)
        temporal._verify_reservations(connection)
        temporal._verify_releases(connection)
        assert (
            temporal._active_reservation_set(
                connection,
                account_id=limits.account_id,
                at=NOW + timedelta(seconds=17),
            ).reservation_count
            == 0
        )
        assert (
            temporal._active_reservation_set(
                connection,
                account_id=limits.account_id,
                at=NOW + timedelta(seconds=18),
            ).reservation_count
            == 1
        )
        temporal._release_capacity(
            connection,
            reservation_id=temporal_reservation_id,
            reason="temporal-test",
            released_at=NOW + timedelta(seconds=20),
        )
        assert (
            temporal._active_reservation_set(
                connection,
                account_id=limits.account_id,
                at=NOW + timedelta(seconds=19),
            ).reservation_count
            == 1
        )
        assert (
            temporal._active_reservation_set(
                connection,
                account_id=limits.account_id,
                at=NOW + timedelta(seconds=20),
            ).reservation_count
            == 0
        )
        connection.commit()
    assert (
        RiskStore(store.path).record_risk_decision(
            intent.idempotency_key, authorization.authorization_id, limits, risk_context
        )
        == reserved
    )
    delta = build_order_delta(
        intent,
        target_quantity=10,
        current_quantity=0,
        created_at=NOW + timedelta(seconds=18),
    )
    assert delta is not None
    orders = OrderLifecycleStore(store.path)
    reservation_id = fingerprint({"decision_id": reserved.decision_id})
    with pytest.raises(JournalIntegrityError, match="reservation is missing"):
        orders.stage(delta, reservation_id="missing", staged_at=NOW + timedelta(seconds=18))
    staged = orders.stage(
        delta, reservation_id=reservation_id, staged_at=NOW + timedelta(seconds=18)
    )
    assert staged.state == OrderState.STAGED
    with pytest.raises(JournalIntegrityError, match="invalid order transition"):
        orders.transition(
            delta.client_order_id,
            OrderState.SUBMITTING,
            changed_at=NOW + timedelta(seconds=19),
        )
    claimed = orders.claim_submitter(
        delta.client_order_id,
        submitter_id="worker-1",
        claimed_at=NOW + timedelta(seconds=19),
    )
    assert claimed.state == OrderState.SUBMITTING
    assert (
        orders.claim_submitter(
            delta.client_order_id,
            submitter_id="worker-1",
            claimed_at=NOW + timedelta(seconds=19),
        )
        == claimed
    )
    with pytest.raises(JournalIntegrityError, match="different submitter"):
        orders.claim_submitter(
            delta.client_order_id,
            submitter_id="worker-2",
            claimed_at=NOW + timedelta(seconds=19),
        )
    broker_events = BrokerEventStore(store.path)

    def missing_order(request: Request) -> bytes:
        if urlsplit(request.full_url).path == "/v2/account":
            return json.dumps({"id": limits.account_id}).encode()
        raise HTTPError(request.full_url, 404, "secret raw error", Message(), None)

    monkeypatch.setattr(alpaca_paper, "_urlopen_bytes", missing_order)
    reader = AlpacaPaperReader(
        "test-key",
        "test-secret",
        account_id=limits.account_id,
        allowed_symbols=frozenset(limits.allowed_symbols),
        clock=lambda: NOW + timedelta(seconds=20),
    )
    with pytest.raises(JournalIntegrityError, match="submission-unknown"):
        reader.record_order_lookup(broker_events, client_order_id=delta.client_order_id)
    unknown = orders.transition(
        delta.client_order_id,
        OrderState.SUBMISSION_UNKNOWN,
        changed_at=NOW + timedelta(seconds=19, milliseconds=500),
    )
    missing = reader.record_order_lookup(broker_events, client_order_id=delta.client_order_id)
    assert isinstance(missing, OrderLookupNotFoundEvidence)
    assert missing == reader.record_order_lookup(
        broker_events, client_order_id=delta.client_order_id
    )
    assert missing.client_order_id == delta.client_order_id
    assert missing.account_id == limits.account_id
    assert broker_events.submission_unknown_orders() == (unknown,)
    assert not broker_events.get_emergency().disabled
    with sqlite3.connect(store.path) as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM capacity_releases WHERE reservation_id = ?", (reservation_id,)
            ).fetchone()
            is None
        )
    recovery_at = NOW + timedelta(seconds=21)
    recovery_snapshot = _record_adapter_snapshot(
        store,
        _flat_snapshot(
            SnapshotSource.ALPACA_PAPER,
            "recovery-observed",
            account_observed_at=recovery_at,
            positions_observed_at=recovery_at,
            orders_observed_at=recovery_at,
        ),
        monkeypatch,
        recorded_at=recovery_at,
    )
    recovery_baseline = store.create_flat_baseline(
        baseline_id="recovery-baseline",
        authorization_id=authorization.authorization_id,
        expected_snapshot_id=expected.snapshot_id,
        observed_snapshot_id=recovery_snapshot.snapshot_id,
        limits=limits,
        operator="test-operator",
        reason="unknown order recovery test",
        created_at=recovery_at,
    )
    recovery_evidence = store.record_reconciliation(
        baseline_id=recovery_baseline.baseline_id,
        observed_snapshot_id=recovery_snapshot.snapshot_id,
        compared_at=recovery_at,
        unresolved_mutations=0,
    )
    recovery = SubmissionRecoveryStore(store.path)
    journal_head = orders.verify_journal()
    proof = recovery.assess(
        order_id=delta.client_order_id,
        lookup_evidence_id=missing.evidence_id,
        reconciliation_evidence_id=recovery_evidence.evidence_id,
        limits=limits,
        assessed_at=recovery_at,
    )
    assert proof.ready_for_review
    assert proof.proof_fingerprint
    assert orders.verify_journal() == journal_head
    assert not any(
        hasattr(recovery, name) for name in ("stage", "claim_submitter", "transition", "record")
    )
    emergency = store.get_emergency()
    disabled_at = recovery_at + timedelta(milliseconds=250)
    changed_at = recovery_at + timedelta(milliseconds=500)
    with store._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        disabled_sequence = store._append_event(
            connection,
            occurred_at=disabled_at,
            event_type="emergency-disabled",
            entity_type="emergency-state",
            entity_id="global",
            payload={
                "cause_fingerprint": fingerprint({"test": "post-lookup-disable"}),
                "disabled": True,
                "generation": emergency.generation + 1,
                "reason": "post-lookup test disable",
                "operator": "system",
            },
        )
        connection.execute(
            "UPDATE emergency_state SET disabled = 1, generation = ?, reason = ?, operator = ?, "
            "changed_at = ?, journal_sequence = ? WHERE singleton = 1",
            (
                emergency.generation + 1,
                "post-lookup test disable",
                "system",
                disabled_at.isoformat().replace("+00:00", "Z"),
                disabled_sequence,
            ),
        )
        cleared_sequence = store._append_event(
            connection,
            occurred_at=changed_at,
            event_type="emergency-cleared",
            entity_type="emergency-state",
            entity_id="global",
            payload={
                "cause_fingerprint": fingerprint({"test": "post-lookup-clear"}),
                "disabled": False,
                "generation": emergency.generation + 2,
                "reason": "post-lookup test clear",
                "operator": "test-operator",
            },
        )
        connection.execute(
            "UPDATE emergency_state SET disabled = 0, generation = ?, reason = ?, operator = ?, "
            "changed_at = ?, journal_sequence = ? WHERE singleton = 1",
            (
                emergency.generation + 2,
                "post-lookup test clear",
                "test-operator",
                changed_at.isoformat().replace("+00:00", "Z"),
                cleared_sequence,
            ),
        )
        connection.commit()
    assert (
        "emergency-state-changed-after-lookup"
        in recovery.assess(
            order_id=delta.client_order_id,
            lookup_evidence_id=missing.evidence_id,
            reconciliation_evidence_id=recovery_evidence.evidence_id,
            limits=limits,
            assessed_at=changed_at,
        ).reasons
    )
    journal_head = orders.verify_journal()
    assert broker_events.submission_unknown_orders() == (unknown,)
    assert orders.verify_journal() == journal_head
    acknowledged = BrokerOrderEvent(
        event_id="broker-event-1",
        broker_order_id="broker-order-1",
        client_order_id=delta.client_order_id,
        state=OrderState.ACKNOWLEDGED,
        cumulative_filled_quantity=0,
        cumulative_average_fill_price=None,
        provider_timestamp=NOW + timedelta(seconds=19),
        observed_at=NOW + timedelta(seconds=20),
    )
    legacy_payload = canonicalize(acknowledged)
    assert isinstance(legacy_payload, dict)
    legacy_payload.pop("cumulative_average_fill_price")
    with broker_events._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        event_sequence = broker_events._append_event(
            connection,
            occurred_at=acknowledged.observed_at,
            event_type="broker-event-recorded",
            entity_type="broker-event",
            entity_id=acknowledged.event_id,
            payload=legacy_payload,
        )
        connection.execute(
            "INSERT INTO broker_events VALUES (?, ?, ?, ?, ?)",
            (
                acknowledged.event_id,
                fingerprint(legacy_payload),
                acknowledged.client_order_id,
                canonical_json(legacy_payload),
                event_sequence,
            ),
        )
        transition = {
            "order_id": acknowledged.client_order_id,
            "from_state": OrderState.SUBMISSION_UNKNOWN,
            "to_state": OrderState.ACKNOWLEDGED,
            "changed_at": acknowledged.observed_at,
            "broker_event_id": acknowledged.event_id,
        }
        order_sequence = broker_events._append_event(
            connection,
            occurred_at=acknowledged.observed_at,
            event_type="order-transitioned",
            entity_type="order",
            entity_id=acknowledged.client_order_id,
            payload=canonicalize(transition),
        )
        connection.execute(
            "UPDATE orders SET state = ?, changed_at = ?, journal_sequence = ? WHERE order_id = ?",
            (
                OrderState.ACKNOWLEDGED,
                acknowledged.observed_at.isoformat().replace("+00:00", "Z"),
                order_sequence,
                acknowledged.client_order_id,
            ),
        )
        connection.commit()
    assert BrokerEventStore(store.path).record(acknowledged) == acknowledged
    assert not recovery.assess(
        order_id=delta.client_order_id,
        lookup_evidence_id=missing.evidence_id,
        reconciliation_evidence_id=recovery_evidence.evidence_id,
        limits=limits,
        assessed_at=recovery_at,
    ).ready_for_review
    assert broker_events.submission_unknown_orders() == ()
    partial = BrokerOrderEvent(
        event_id="broker-event-2",
        broker_order_id="broker-order-1",
        client_order_id=delta.client_order_id,
        state=OrderState.PARTIALLY_FILLED,
        cumulative_filled_quantity=3,
        cumulative_average_fill_price=Decimal("100.25"),
        provider_timestamp=NOW + timedelta(seconds=22),
        observed_at=NOW + timedelta(seconds=23),
    )
    evidence_only_path = tmp_path / "evidence-only.sqlite3"
    shutil.copy2(store.path, evidence_only_path)
    evidence_only = BrokerEventStore(evidence_only_path)
    evidence_only.record(partial)
    with pytest.raises(JournalIntegrityError, match="lineage is incomplete"):
        evidence_only.expected_positions(baseline.baseline_id)
    journal_before_fill = broker_events.verify_journal()
    assert broker_events.record(partial, baseline_id=baseline.baseline_id) == partial
    assert broker_events.expected_positions(baseline.baseline_id) == (PositionSnapshot("SPY", 3),)
    journal_after_fill = broker_events.verify_journal()
    assert journal_after_fill.event_count == journal_before_fill.event_count + 3
    assert broker_events.record(partial, baseline_id=baseline.baseline_id) == partial
    assert broker_events.verify_journal() == journal_after_fill
    canceled = BrokerOrderEvent(
        event_id="broker-event-3",
        broker_order_id="broker-order-1",
        client_order_id=delta.client_order_id,
        state=OrderState.CANCELED,
        cumulative_filled_quantity=3,
        cumulative_average_fill_price=Decimal("100.25"),
        provider_timestamp=NOW + timedelta(seconds=24),
        observed_at=NOW + timedelta(seconds=25),
    )
    broker_events.record(canceled, baseline_id=baseline.baseline_id)
    canceled_head = broker_events.verify_journal()
    assert broker_events.record(canceled, baseline_id=baseline.baseline_id) == canceled
    assert broker_events.verify_journal() == canceled_head
    with sqlite3.connect(store.path) as connection:
        assert (
            connection.execute(
                "SELECT reason FROM capacity_releases WHERE reservation_id = ?",
                (reservation_id,),
            ).fetchone()
            is None
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM expected_position_advances WHERE baseline_id = ?",
            (baseline.baseline_id,),
        ).fetchone() == (1,)
    assert BrokerEventStore(store.path).expected_positions(baseline.baseline_id) == (
        PositionSnapshot("SPY", 3),
    )
    legacy_release_path = tmp_path / "legacy-partial-release.sqlite3"
    shutil.copy2(store.path, legacy_release_path)
    legacy_release = BrokerEventStore(legacy_release_path)
    with legacy_release._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        legacy_release._release_capacity(
            connection,
            reservation_id=reservation_id,
            reason="order-canceled",
            released_at=canceled.observed_at,
        )
        connection.commit()
    with pytest.raises(JournalIntegrityError, match="capacity release"):
        RiskStore(legacy_release_path)
    settlement_at = NOW + timedelta(seconds=26)
    settled_snapshot = _record_adapter_snapshot(
        store,
        replace(
            _flat_snapshot(
                SnapshotSource.ALPACA_PAPER,
                "settled-observed",
                account_observed_at=settlement_at,
                positions_observed_at=settlement_at,
                orders_observed_at=settlement_at,
            ),
            cash=Decimal("69000"),
            equity=Decimal("71000"),
            buying_power=Decimal("68000"),
            positions=(PositionSnapshot("SPY", 3),),
        ),
        monkeypatch,
        recorded_at=settlement_at,
    )
    risk_observations = iter(
        (settlement_at + timedelta(seconds=1), settlement_at + timedelta(seconds=2))
    )

    def risk_transport(request: Request) -> bytes:
        path = urlsplit(request.full_url).path
        if path == "/v2/stocks/quotes/latest":
            return json.dumps(
                {
                    "quotes": {
                        "SPY": {
                            "bp": 100,
                            "ap": 100.1,
                            "bs": 10,
                            "as": 12,
                            "t": settlement_at.isoformat(),
                        }
                    }
                }
            ).encode()
        if path == "/v3/clock":
            return json.dumps(
                {
                    "clocks": [
                        {
                            "market": {"acronym": "NYSE"},
                            "timestamp": settlement_at.isoformat(),
                            "is_market_day": True,
                            "next_market_open": (settlement_at + timedelta(days=1)).isoformat(),
                            "next_market_close": (settlement_at + timedelta(hours=1)).isoformat(),
                            "phase": "core",
                        }
                    ]
                }
            ).encode()
        raise AssertionError(path)

    monkeypatch.setattr(risk_inputs, "_urlopen_bytes", risk_transport)
    risk_input_store = RiskInputEvidenceStore(store.path)
    risk_reader = AlpacaRiskInputReader(
        "test-key",
        "test-secret",
        limits=limits,
        clock=lambda: next(risk_observations),
    )
    risk_input = risk_reader.record(
        risk_input_store,
        portfolio_snapshot_id=settled_snapshot.snapshot_id,
        authorization_id=authorization.authorization_id,
        recorded_at=settlement_at + timedelta(seconds=2),
    )
    assert risk_input.quotes[0].symbol == "SPY"
    assert risk_input.quotes[0].ask_price == Decimal("100.1")
    assert risk_input.clock.regular_session_open
    assert risk_input.authorization_id == authorization.authorization_id
    assert risk_input.maximum_age_seconds == limits.max_snapshot_age_seconds
    assert RiskInputEvidenceStore(store.path).verify_journal()
    injected_risk_reader = AlpacaRiskInputReader(
        "test-key",
        "test-secret",
        limits=limits,
        transport=risk_transport,
    )
    with pytest.raises(AlpacaRiskInputError, match="cannot produce durable"):
        injected_risk_reader.record(
            risk_input_store,
            portfolio_snapshot_id=settled_snapshot.snapshot_id,
            authorization_id=authorization.authorization_id,
            recorded_at=settlement_at + timedelta(seconds=2),
        )
    settlement_store = PositionSettlementStore(store.path)
    settlement = settlement_store.record_settlement(
        proof_id="position-settlement-1",
        baseline_id=baseline.baseline_id,
        observed_snapshot_id=settled_snapshot.snapshot_id,
        settled_at=settlement_at,
    )
    settlement_head = settlement_store.verify_journal()
    assert settlement.advance_fingerprint
    assert settlement.observed_snapshot_fingerprint == settled_snapshot.snapshot_fingerprint
    assessment_head = settlement_store.verify_journal()
    assessment = settlement_store.assess_capacity(settlement.proof_id, assessed_at=settlement_at)
    assert not assessment.ready
    assert assessment.reasons == ("context-provenance-missing",)
    assert assessment.reservation_ids == (reservation_id,)
    assert assessment.observed_cash == Decimal("69000")
    assert assessment.observed_equity == Decimal("71000")
    assert assessment.observed_buying_power == Decimal("68000")
    assert settlement_store.verify_journal() == assessment_head
    stale_assessment = settlement_store.assess_capacity(
        settlement.proof_id, assessed_at=settlement_at + timedelta(seconds=31)
    )
    assert stale_assessment.reasons == (
        "context-provenance-missing",
        "settlement-snapshot-stale-or-future",
    )
    assert settlement_store.verify_journal() == assessment_head
    assert (
        settlement_store.record_settlement(
            proof_id="position-settlement-1",
            baseline_id=baseline.baseline_id,
            observed_snapshot_id=settled_snapshot.snapshot_id,
            settled_at=settlement_at,
        )
        == settlement
    )
    assert PositionSettlementStore(store.path).verify_journal() == settlement_head
    equity_store = StrategyEquityStore(store.path)
    checkpoint = equity_store.record_checkpoint(
        strategy_equity_baseline_id=strategy_equity_baseline.baseline_id,
        settlement_proof_id=settlement.proof_id,
        risk_input_evidence_id=risk_input.evidence_id,
        limits=limits,
        marked_at=settlement_at + timedelta(seconds=2),
    )
    assert checkpoint.fill_event_ids == (partial.event_id,)
    assert checkpoint.gross_buy_notional == Decimal("300.75")
    assert checkpoint.gross_sell_notional == Decimal("0")
    assert checkpoint.fill_cost_reserve == Decimal("0.30075")
    assert checkpoint.strategy_cash == Decimal("49698.94925")
    assert checkpoint.position_market_value == Decimal("300")
    assert checkpoint.strategy_equity == Decimal("49998.94925")
    assert checkpoint.peak_equity == Decimal("50000")
    assert checkpoint.strategy_drawdown == Decimal("0.000021015")
    assert equity_store.latest_checkpoint(authorization.authorization_id) == checkpoint
    assert (
        equity_store.record_checkpoint(
            strategy_equity_baseline_id=strategy_equity_baseline.baseline_id,
            settlement_proof_id=settlement.proof_id,
            risk_input_evidence_id=risk_input.evidence_id,
            limits=limits,
            marked_at=settlement_at + timedelta(seconds=2),
        )
        == checkpoint
    )
    context_head = equity_store.verify_journal()
    attested_context = AttestedRiskContextStore(store.path).derive(
        authorization_id=authorization.authorization_id,
        symbol="SPY",
        limits=limits,
        evaluated_at=settlement_at + timedelta(seconds=2),
    )
    context = attested_context.context
    assert context.equity == Decimal("71000")
    assert context.cash == Decimal("69000")
    assert context.buying_power == Decimal("68000")
    assert context.current_gross_exposure == Decimal("300.3")
    assert context.current_symbol_notional == Decimal("300.3")
    assert context.current_symbol_quantity == 3
    assert context.pending_buy_notional == Decimal("15000")
    assert context.pending_order_notional == Decimal("15000")
    assert context.pending_order_count == 1
    assert context.orders_last_minute == 1
    assert context.daily_pnl == Decimal("0")
    assert context.strategy_drawdown == checkpoint.strategy_drawdown
    assert context.quote_bid_price == Decimal("100")
    assert context.quote_ask_price == Decimal("100.1")
    assert context.regular_session_open
    assert not context.emergency_disabled
    assert attested_context.strategy_equity_checkpoint_fingerprint == (
        checkpoint.checkpoint_fingerprint
    )
    assert attested_context.proof_fingerprint
    assert equity_store.verify_journal() == context_head
    with pytest.raises(JournalIntegrityError, match="stale or mismatched"):
        AttestedRiskContextStore(store.path).derive(
            authorization_id=authorization.authorization_id,
            symbol="SPY",
            limits=limits,
            evaluated_at=settlement_at + timedelta(seconds=33),
        )
    with pytest.raises(JournalIntegrityError, match="valuation is incomplete"):
        AttestedRiskContextStore(store.path).derive(
            authorization_id=authorization.authorization_id,
            symbol="QQQ",
            limits=limits,
            evaluated_at=settlement_at + timedelta(seconds=2),
        )
    tampered_path = tmp_path / "tampered-strategy-equity.sqlite3"
    shutil.copy2(store.path, tampered_path)
    with sqlite3.connect(tampered_path) as connection:
        connection.execute("DROP TRIGGER strategy_equity_checkpoints_no_update")
        connection.execute("UPDATE strategy_equity_checkpoints SET checkpoint_json = '{}'")
    with pytest.raises(JournalIntegrityError, match="strategy equity checkpoint"):
        StrategyEquityStore(tampered_path)
    unattested_snapshot = replace(settled_snapshot, snapshot_id="unattested-settlement")
    store.record_snapshot(unattested_snapshot, recorded_at=settlement_at)
    with pytest.raises(JournalIntegrityError, match="authority is missing"):
        settlement_store.record_settlement(
            proof_id="unattested-proof",
            baseline_id=baseline.baseline_id,
            observed_snapshot_id=unattested_snapshot.snapshot_id,
            settled_at=settlement_at,
        )
    mismatch_at = settlement_at + timedelta(seconds=1)
    mismatched_snapshot = _record_adapter_snapshot(
        store,
        _flat_snapshot(
            SnapshotSource.ALPACA_PAPER,
            "mismatched-settlement",
            account_observed_at=mismatch_at,
            positions_observed_at=mismatch_at,
            orders_observed_at=mismatch_at,
        ),
        monkeypatch,
        recorded_at=mismatch_at,
    )
    with pytest.raises(JournalIntegrityError, match="not complete and current"):
        settlement_store.record_settlement(
            proof_id="mismatched-proof",
            baseline_id=baseline.baseline_id,
            observed_snapshot_id=mismatched_snapshot.snapshot_id,
            settled_at=mismatch_at,
        )
    with sqlite3.connect(store.path) as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM capacity_releases WHERE reservation_id = ?",
                (reservation_id,),
            ).fetchone()
            is None
        )
    OrderLifecycleStore(store.path)
    assert (
        store.clear_emergency(
            clear_id="clear-stable-1",
            baseline_id=baseline.baseline_id,
            limits=limits,
            operator="test-operator",
            reason="stable proof reviewed",
            cleared_at=NOW + timedelta(seconds=18),
        )
        == store.get_emergency()
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
    with pytest.raises(JournalIntegrityError, match="different content"):
        broker_events.record(
            replace(
                acknowledged,
                state=OrderState.FILLED,
                cumulative_filled_quantity=10,
                cumulative_average_fill_price=Decimal("100.25"),
            )
        )
    assert store.get_emergency().disabled

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
    forged = replace(missing, observed_at=NOW + timedelta(seconds=24))
    with broker_events._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        sequence = broker_events._append_event(
            connection,
            occurred_at=forged.observed_at,
            event_type="order-lookup-not-found",
            entity_type="order-lookup",
            entity_id=forged.evidence_id,
            payload=canonicalize(forged),
        )
        connection.execute(
            "INSERT INTO order_lookup_not_found VALUES (?, ?, ?, ?)",
            (forged.evidence_id, forged.client_order_id, canonical_json(forged), sequence),
        )
        connection.commit()
    with pytest.raises(JournalIntegrityError, match="negative order lookup"):
        BrokerEventStore(store.path)
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE orders SET state = 'filled'")
    with pytest.raises(JournalIntegrityError, match="latest journal event"):
        OrderLifecycleStore(store.path)
