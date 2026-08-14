from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta, tzinfo
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

import systematic_trading_lab.cli as cli
import systematic_trading_lab.reconciliation as reconciliation
import systematic_trading_lab.risk as risk_module
from systematic_trading_lab.broker_events import BrokerEventStore, BrokerOrderEvent
from systematic_trading_lab.config import Settings
from systematic_trading_lab.domain import TradingMode
from systematic_trading_lab.execution import ExecutionIntent, JournalIntegrityError
from systematic_trading_lab.experiments import HoldoutAccessError
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.orders import OrderLifecycleStore, OrderState, build_order_delta
from systematic_trading_lab.paper_continuation import PaperContinuationStore
from systematic_trading_lab.paper_equivalence import PaperEquivalenceStore, load_action_plan
from systematic_trading_lab.paper_observation import PaperObservationStore
from systematic_trading_lab.paper_planning import plan_strategic_allocation, write_action_plans
from systematic_trading_lab.paper_submission import PaperSubmissionPreflightStore
from systematic_trading_lab.position_settlement import PositionSettlementStore
from systematic_trading_lab.reconciliation import (
    PaperContinuationHandoff,
    PortfolioSnapshot,
    PositionSnapshot,
    ReconciliationStore,
    SnapshotSource,
)
from systematic_trading_lab.recovery import _RecoveryVerifier
from systematic_trading_lab.risk import PaperAuthorization, RiskContext, RiskLimits, RiskStore
from systematic_trading_lab.risk_inputs import (
    _CAPABILITY,
    DATA_ORIGIN,
    PAPER_ORIGIN,
    LatestQuoteEvidence,
    MarketClockEvidence,
    RiskInputEvidence,
    RiskInputEvidenceStore,
)
from systematic_trading_lab.settled_capacity import SettledCapacityStore
from systematic_trading_lab.strategy_equity import StrategyEquityCheckpoint, StrategyEquityStore

_ROOT_SESSION_AT = datetime(2026, 8, 3, 14, 0, tzinfo=UTC)


def _frozen_datetime(at: datetime) -> type[datetime]:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, timezone: tzinfo | None = None) -> FrozenDateTime:
            return cls.fromtimestamp(at.timestamp(), timezone)

    return FrozenDateTime


@dataclass(frozen=True)
class _SourceState:
    path: Path
    limits: RiskLimits
    authorization: PaperAuthorization
    checkpoint: StrategyEquityCheckpoint
    risk_input: RiskInputEvidence
    settled_snapshot: PortfolioSnapshot
    now: datetime


@dataclass(frozen=True)
class _ContinuationState:
    source: _SourceState
    authorization: PaperAuthorization
    handoff: PaperContinuationHandoff
    snapshot: PortfolioSnapshot
    risk_input: RiskInputEvidence


def _limits(now: datetime) -> RiskLimits:
    return RiskLimits(
        configuration_id="paper-continuation-test",
        account_id="paper-account",
        allowed_symbols=("GLD", "IWM", "QQQ", "SPY"),
        max_order_notional=Decimal("4000"),
        max_position_notional=Decimal("4000"),
        max_gross_exposure=Decimal("10000"),
        strategy_capital_allocation=Decimal("10000"),
        strategy_fill_cost_bps=Decimal("10"),
        min_cash=Decimal("90000"),
        max_open_orders=1,
        max_orders_per_minute=4,
        max_daily_loss=Decimal("100"),
        max_strategy_drawdown=Decimal("0.01"),
        max_price_deviation_bps=Decimal("25"),
        max_snapshot_age_seconds=30,
        min_reconciliation_stability_seconds=5,
        reviewed_by="reviewer",
        review_reason="continuation test",
        effective_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=90),
    )


def _qualification_report() -> dict[str, object]:
    candidate = {
        "strategy_id": "strategic-allocation-portfolio",
        "strategy_version": "1",
        "strategy_family": "allocation",
        "code_commit": "a" * 40,
        "parameters": {"rebalance_every": 21},
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
        "experiment_id": "strategic-allocation-21",
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
        "candidate_id": "strategic-allocation-21",
        "strategy_id": "strategic-allocation-portfolio",
        "candidate_specification": candidate,
        "source_experiment_ids": ["experiment"],
        "metrics": {},
        "qualification": qualification,
    }
    report["evidence_fingerprint"] = fingerprint(report)
    return report


def _authorization(
    limits: RiskLimits, report: dict[str, object], *, now: datetime
) -> PaperAuthorization:
    return PaperAuthorization(
        authorization_id="initial-authorization",
        candidate_id="strategic-allocation-21",
        strategy_id="strategic-allocation-portfolio",
        strategy_version="1",
        parameters_fingerprint=fingerprint({"rebalance_every": 21}),
        code_commit="a" * 40,
        dataset_id="dataset",
        dataset_fingerprint="2" * 64,
        universe_id="universe",
        universe_fingerprint="3" * 64,
        qualification_evidence_fingerprint=str(report["evidence_fingerprint"]),
        account_id=limits.account_id,
        risk_configuration_fingerprint=limits.configuration_fingerprint,
        authorized_by="reviewer",
        authorization_reason="initial paper session",
        authorized_at=now,
        expires_at=now + timedelta(seconds=18),
    )


def _snapshot(
    snapshot_id: str,
    source: SnapshotSource,
    observed_at: datetime,
    *,
    positions: tuple[PositionSnapshot, ...] = (),
    cash: Decimal = Decimal("100000"),
    equity: Decimal = Decimal("100000"),
    buying_power: Decimal = Decimal("100000"),
) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        snapshot_id=snapshot_id,
        source=source,
        account_id="paper-account",
        cash=cash,
        equity=equity,
        buying_power=buying_power,
        account_ready=True,
        positions=positions,
        open_orders=(),
        account_observed_at=observed_at,
        positions_observed_at=observed_at,
        orders_observed_at=observed_at,
    )


def _attest(store: ReconciliationStore, snapshot: PortfolioSnapshot) -> PortfolioSnapshot:
    return store._record_adapter_snapshot(
        snapshot,
        adapter_version="alpaca-paper-reader-v2",
        paper_origin=PAPER_ORIGIN,
        recorded_at=snapshot.orders_observed_at,
        previous_close_equity=Decimal("100000"),
        _capability=reconciliation._ALPACA_READER_CAPABILITY,
    )


def _risk_input(
    path: Path,
    *,
    snapshot: PortfolioSnapshot,
    authorization_id: str,
    attestation_fingerprint: str,
    limits: RiskLimits,
    observed_at: datetime,
    spy_ask: str = "100",
) -> RiskInputEvidence:
    prices = {
        "GLD": ("199", "200"),
        "IWM": ("99", "100"),
        "QQQ": ("499", "500"),
        "SPY": ("50", spy_ask),
    }
    quotes = tuple(
        LatestQuoteEvidence(
            symbol,
            Decimal(bid),
            Decimal(ask),
            10,
            10,
            observed_at,
            observed_at,
        )
        for symbol, (bid, ask) in prices.items()
    )
    clock = MarketClockEvidence(
        "NYSE",
        "core",
        True,
        observed_at,
        observed_at + timedelta(days=1),
        observed_at + timedelta(hours=1),
        observed_at,
    )
    evidence = RiskInputEvidence(
        portfolio_snapshot_id=snapshot.snapshot_id,
        portfolio_snapshot_fingerprint=snapshot.snapshot_fingerprint,
        portfolio_attestation_fingerprint=attestation_fingerprint,
        authorization_id=authorization_id,
        account_id=limits.account_id,
        risk_configuration_fingerprint=limits.configuration_fingerprint,
        maximum_age_seconds=limits.max_snapshot_age_seconds,
        quotes=quotes,
        clock=clock,
        data_origin=DATA_ORIGIN,
        paper_origin=PAPER_ORIGIN,
        quote_path="/v2/stocks/quotes/latest",
        clock_path="/v3/clock",
        feed="iex",
        adapter_version="alpaca-risk-input-reader-v1",
        completed_at=observed_at,
    )
    return RiskInputEvidenceStore(path)._record(
        evidence, recorded_at=observed_at, capability=_CAPABILITY
    )


def _source_state(tmp_path: Path, *, now: datetime = _ROOT_SESSION_AT) -> _SourceState:
    path = tmp_path / "execution.sqlite3"
    with patch.object(risk_module, "datetime", _frozen_datetime(now - timedelta(seconds=1))):
        store = ReconciliationStore(path)
    limits = _limits(now)
    report = _qualification_report()
    authorization = _authorization(limits, report, now=now)
    store.authorize_paper(authorization, report, limits)
    expected = _snapshot("initial-expected", SnapshotSource.LOCAL_EXPECTED, now)
    observed = _attest(store, _snapshot("initial-observed", SnapshotSource.ALPACA_PAPER, now))
    store.record_snapshot(expected, recorded_at=now)
    baseline = store.create_flat_baseline(
        baseline_id="initial-baseline",
        authorization_id=authorization.authorization_id,
        expected_snapshot_id=expected.snapshot_id,
        observed_snapshot_id=observed.snapshot_id,
        limits=limits,
        operator="operator",
        reason="initial flat state",
        created_at=now,
    )
    strategy_baseline = store.create_strategy_equity_baseline(
        baseline_id="initial-strategy-equity",
        reconciliation_baseline_id=baseline.baseline_id,
        limits=limits,
        operator="operator",
        reason="initial strategy allocation",
        created_at=now,
    )
    for seconds in (0, 5, 10):
        sample_at = now + timedelta(seconds=seconds)
        sample = (
            observed
            if not seconds
            else _attest(
                store,
                _snapshot(f"initial-stable-{seconds}", SnapshotSource.ALPACA_PAPER, sample_at),
            )
        )
        store.record_reconciliation(
            baseline_id=baseline.baseline_id,
            observed_snapshot_id=sample.snapshot_id,
            compared_at=sample_at,
            unresolved_mutations=0,
        )
    store.clear_emergency(
        clear_id="initial-clear",
        baseline_id=baseline.baseline_id,
        limits=limits,
        operator="operator",
        reason="stable clean initial state",
        cleared_at=now + timedelta(seconds=10),
    )
    intent = ExecutionIntent(
        idempotency_key="initial:SPY",
        strategy_id=authorization.strategy_id,
        strategy_version=authorization.strategy_version,
        symbol="SPY",
        decision_timestamp=now + timedelta(seconds=10),
        target_weight=None,
        target_quantity=4,
        reason="initial target",
        source_data_fingerprint=authorization.dataset_fingerprint,
        configuration_fingerprint=authorization.parameters_fingerprint,
        reference_price=Decimal("100"),
        expires_at=now + timedelta(seconds=18),
    )
    store.record_intent(intent, received_at=now + timedelta(seconds=10))
    context_at = now + timedelta(seconds=11)
    context = RiskContext(
        account_id=limits.account_id,
        evaluated_at=context_at,
        equity=Decimal("100000"),
        cash=Decimal("100000"),
        buying_power=Decimal("100000"),
        current_gross_exposure=Decimal(0),
        current_symbol_notional=Decimal(0),
        current_symbol_quantity=0,
        pending_buy_notional=Decimal(0),
        pending_order_notional=Decimal(0),
        active_reservation_set_fingerprint=fingerprint({"reservations": []}),
        open_order_count=0,
        pending_order_count=0,
        orders_last_minute=0,
        daily_pnl=Decimal(0),
        strategy_drawdown=Decimal(0),
        quote_bid_price=Decimal("99"),
        quote_ask_price=Decimal("100"),
        account_observed_at=now + timedelta(seconds=10),
        positions_observed_at=now + timedelta(seconds=10),
        orders_observed_at=now + timedelta(seconds=10),
        quote_observed_at=now + timedelta(seconds=10),
        clock_observed_at=now + timedelta(seconds=10),
        regular_session_open=True,
        emergency_disabled=False,
    )
    receipt = store._record_risk_decision_with_context(
        intent.idempotency_key, authorization.authorization_id, limits, context
    )
    assert receipt.approved
    delta = build_order_delta(intent, target_quantity=4, current_quantity=0, created_at=context_at)
    assert delta is not None
    orders = OrderLifecycleStore(path)
    reservation_id = fingerprint({"decision_id": receipt.decision_id})
    orders.stage(delta, reservation_id=reservation_id, staged_at=context_at)
    orders.claim_submitter(
        delta.client_order_id,
        submitter_id="test-writer",
        claimed_at=now + timedelta(seconds=12),
    )
    filled_at = now + timedelta(seconds=13)
    BrokerEventStore(path).record(
        BrokerOrderEvent(
            event_id="initial-fill",
            broker_order_id="paper-order",
            client_order_id=delta.client_order_id,
            state=OrderState.FILLED,
            cumulative_filled_quantity=4,
            cumulative_average_fill_price=Decimal("100"),
            provider_timestamp=filled_at,
            observed_at=filled_at,
        ),
        baseline_id=baseline.baseline_id,
    )
    settled_at = now + timedelta(seconds=14)
    settled_snapshot = _attest(
        store,
        _snapshot(
            "initial-settled",
            SnapshotSource.ALPACA_PAPER,
            settled_at,
            positions=(PositionSnapshot("SPY", 4),),
            cash=Decimal("99600"),
            buying_power=Decimal("99600"),
        ),
    )
    settlement = PositionSettlementStore(path).record_settlement(
        proof_id="initial-settlement",
        baseline_id=baseline.baseline_id,
        observed_snapshot_id=settled_snapshot.snapshot_id,
        settled_at=settled_at,
    )
    risk_input = _risk_input(
        path,
        snapshot=settled_snapshot,
        authorization_id=authorization.authorization_id,
        attestation_fingerprint=settlement.attestation_fingerprint,
        limits=limits,
        observed_at=now + timedelta(seconds=15),
    )
    checkpoint = StrategyEquityStore(path).record_checkpoint(
        strategy_equity_baseline_id=strategy_baseline.baseline_id,
        settlement_proof_id=settlement.proof_id,
        risk_input_evidence_id=risk_input.evidence_id,
        limits=limits,
        marked_at=now + timedelta(seconds=15),
    )
    SettledCapacityStore(path).release(
        authorization_id=authorization.authorization_id,
        settlement_proof_id=settlement.proof_id,
        symbol="SPY",
        limits=limits,
        released_at=now + timedelta(seconds=16),
    )
    return _SourceState(path, limits, authorization, checkpoint, risk_input, settled_snapshot, now)


def _completed_continuation(
    tmp_path: Path,
    *,
    root_at: datetime = _ROOT_SESSION_AT,
    continuation_at: datetime | None = None,
    current_spy_ask: str = "100",
) -> _ContinuationState:
    source = _source_state(tmp_path, now=root_at)
    authorized_at = continuation_at or source.now + timedelta(seconds=20)
    authorization, _ = ReconciliationStore(source.path).authorize_continuation(
        authorization_id="continuation-authorization",
        previous_authorization_id=source.authorization.authorization_id,
        limits=source.limits,
        authorized_by="reviewer",
        reason="second paper session",
        authorized_at=authorized_at,
        expires_at=authorized_at + timedelta(hours=1),
    )
    snapshot_at = authorized_at + timedelta(seconds=1)
    snapshot = _attest(
        ReconciliationStore(source.path),
        _snapshot(
            "continuation-current",
            SnapshotSource.ALPACA_PAPER,
            snapshot_at,
            positions=source.checkpoint.positions,
            cash=Decimal("99600"),
            buying_power=Decimal("99600"),
        ),
    )
    risk_input = _risk_input(
        source.path,
        snapshot=snapshot,
        authorization_id=authorization.authorization_id,
        attestation_fingerprint=_attestation_fingerprint(source.path, snapshot.snapshot_id),
        limits=source.limits,
        observed_at=snapshot_at,
        spy_ask=current_spy_ask,
    )
    handoff = PaperContinuationStore(source.path).complete_continuation(
        authorization_id=authorization.authorization_id,
        portfolio_snapshot_id=snapshot.snapshot_id,
        risk_input_evidence_id=risk_input.evidence_id,
        limits=source.limits,
        operator="operator",
        reason="clean continuation handoff",
        completed_at=authorized_at + timedelta(seconds=2),
    )
    return _ContinuationState(source, authorization, handoff, snapshot, risk_input)


def _attestation_fingerprint(path: Path, snapshot_id: str) -> str:
    store = ReconciliationStore(path)
    with store._connect() as connection:
        _, attestations, _, _ = store._verify_reconciliation(connection)
    return str(attestations[snapshot_id].attestation_fingerprint)


def test_continuation_preserves_lineage_and_plans_deterministically(tmp_path: Path) -> None:
    state = _completed_continuation(tmp_path)
    store = PaperContinuationStore(state.source.path)
    plan_at = state.handoff.completed_at
    first = store.plan_strategic_allocation(
        authorization_id=state.authorization.authorization_id,
        limits=state.source.limits,
        planned_at=plan_at,
    )
    second = store.plan_strategic_allocation(
        authorization_id=state.authorization.authorization_id,
        limits=state.source.limits,
        planned_at=plan_at,
    )

    assert first == second
    assert first.plan_fingerprint == fingerprint(first)
    assert tuple((item.symbol, item.quantity) for item in first.targets) == (
        ("GLD", 7),
        ("IWM", 25),
        ("QQQ", 5),
        ("SPY", 35),
    )
    assert tuple((item.symbol, item.delta) for item in first.deltas) == (
        ("GLD", 7),
        ("IWM", 25),
        ("QQQ", 5),
        ("SPY", 31),
    )
    assert first.session_count == 1
    assert first.root_exchange_session == first.current_exchange_session
    assert first.market_state_fingerprint in first.evidence_fingerprints
    assert not any(dict(first.authority).values())
    assert not hasattr(first, "submit")

    handoff = state.handoff
    source_checkpoint = state.source.checkpoint
    assert handoff.positions == source_checkpoint.positions == (PositionSnapshot("SPY", 4),)
    assert handoff.gross_buy_notional == source_checkpoint.gross_buy_notional
    assert handoff.fill_cost_reserve == source_checkpoint.fill_cost_reserve
    assert handoff.strategy_cash == source_checkpoint.strategy_cash
    assert handoff.peak_equity == source_checkpoint.peak_equity
    assert handoff.strategy_drawdown == source_checkpoint.strategy_drawdown
    assert handoff.strategy_drawdown >= state.source.limits.max_strategy_drawdown
    assert (
        PaperContinuationStore(state.source.path).get_handoff(handoff.authorization_id) == handoff
    )

    replay_path = tmp_path / "replay.json"
    shadow_path = tmp_path / "shadow.json"
    write_action_plans(first, replay_path=replay_path, shadow_path=shadow_path)
    write_action_plans(first, replay_path=replay_path, shadow_path=shadow_path)
    replay = load_action_plan(replay_path, mode="replay")
    shadow = load_action_plan(shadow_path, mode="shadow")
    assert replay.targets == shadow.targets == first.targets
    assert replay.source_data_fingerprint == shadow.source_data_fingerprint
    assert replay.configuration_fingerprint == shadow.configuration_fingerprint

    observation = PaperObservationStore(state.source.path).start(
        campaign_id="continuation-equivalence",
        baseline_snapshot_id=state.snapshot.snapshot_id,
        maximum_gap_seconds=60,
        duration=timedelta(hours=1),
    )
    intent_keys = []
    for target in first.targets:
        key = f"continuation:{target.symbol}"
        RiskStore(state.source.path).record_intent(
            ExecutionIntent(
                idempotency_key=key,
                strategy_id=first.strategy_id,
                strategy_version=first.strategy_version,
                symbol=target.symbol,
                decision_timestamp=plan_at,
                target_weight=None,
                target_quantity=target.quantity,
                reason="continuation target",
                source_data_fingerprint=first.source_data_fingerprint,
                configuration_fingerprint=first.configuration_fingerprint,
                reference_price=next(
                    quote.ask_price
                    for quote in state.risk_input.quotes
                    if quote.symbol == target.symbol
                ),
                expires_at=plan_at + timedelta(minutes=5),
            ),
            received_at=plan_at,
        )
        intent_keys.append(key)
    equivalence = PaperEquivalenceStore(state.source.path).record(
        comparison_id="continuation-comparison",
        campaign_id=observation.campaign_id,
        replay=replay,
        shadow=shadow,
        paper_intent_keys=tuple(intent_keys),
        recorded_at=plan_at,
    )
    assert equivalence.equivalent

    denied = ExecutionIntent(
        idempotency_key="continuation:risk-check",
        strategy_id=first.strategy_id,
        strategy_version=first.strategy_version,
        symbol="SPY",
        decision_timestamp=plan_at,
        target_weight=None,
        target_quantity=36,
        reason="prove drawdown lineage",
        source_data_fingerprint=first.source_data_fingerprint,
        configuration_fingerprint=first.configuration_fingerprint,
        reference_price=Decimal("100"),
        expires_at=plan_at + timedelta(minutes=5),
    )
    RiskStore(state.source.path).record_intent(denied, received_at=plan_at)
    receipt = PaperContinuationStore(state.source.path).record_attested_risk_decision(
        intent_id=denied.idempotency_key,
        authorization_id=state.authorization.authorization_id,
        limits=state.source.limits,
        evaluated_at=plan_at,
    )
    assert not receipt.approved
    assert "strategy-drawdown-limit" in receipt.reasons

    with (
        sqlite3.connect(state.source.path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="immutable"),
    ):
        connection.execute(
            "UPDATE paper_authorizations SET authorization_json = '{}' WHERE authorization_id = ?",
            (state.source.authorization.authorization_id,),
        )


@pytest.mark.parametrize(
    ("option", "value"),
    (
        pytest.param("--session-count", "22", id="session-count"),
        pytest.param("--market-state-fingerprint", "1" * 64, id="market-state-fingerprint"),
    ),
)
def test_paper_plan_cli_rejects_manual_planning_provenance(
    tmp_path: Path, option: str, value: str
) -> None:
    command = [
        "paper",
        "plan",
        "--authorization",
        "continuation-authorization",
        "--replay-plan",
        str(tmp_path / "replay.json"),
        "--shadow-plan",
        str(tmp_path / "shadow.json"),
    ]

    with pytest.raises(SystemExit):
        cli.parser().parse_args([*command, option, value])


def test_paper_plan_cli_outputs_derived_planning_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = _completed_continuation(
        tmp_path,
        continuation_at=datetime(2026, 8, 4, 14, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(cli, "load_risk_limits", lambda _: state.source.limits)
    monkeypatch.setattr(cli, "datetime", _frozen_datetime(state.handoff.completed_at))
    arguments = cli.parser().parse_args(
        [
            "paper",
            "plan",
            "--authorization",
            state.authorization.authorization_id,
            "--replay-plan",
            str(tmp_path / "replay.json"),
            "--shadow-plan",
            str(tmp_path / "shadow.json"),
        ]
    )

    assert not hasattr(arguments, "session_count")
    assert not hasattr(arguments, "market_state_fingerprint")
    assert cli.run(arguments, Settings(TradingMode.OFFLINE, tmp_path)) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["root_exchange_session"] == "2026-08-03"
    assert output["current_exchange_session"] == "2026-08-04"
    assert output["session_count"] == 2
    assert output["rebalance_due"] is False
    assert len(output["market_state_fingerprint"]) == 64
    assert output["authority"] == {
        "activation": False,
        "broker_write": False,
        "intent": False,
        "live": False,
        "risk": False,
    }


@pytest.mark.parametrize(
    ("root_at", "continuation_at"),
    (
        pytest.param(
            datetime(2026, 8, 7, 14, 0, tzinfo=UTC),
            datetime(2026, 8, 10, 14, 0, tzinfo=UTC),
            id="weekend",
        ),
        pytest.param(
            datetime(2026, 7, 2, 14, 0, tzinfo=UTC),
            datetime(2026, 7, 6, 14, 0, tzinfo=UTC),
            id="xnys-holiday",
        ),
    ),
)
def test_planner_counts_only_xnys_sessions(
    tmp_path: Path, root_at: datetime, continuation_at: datetime
) -> None:
    state = _completed_continuation(tmp_path, root_at=root_at, continuation_at=continuation_at)
    plan = PaperContinuationStore(state.source.path).plan_strategic_allocation(
        authorization_id=state.authorization.authorization_id,
        limits=state.source.limits,
        planned_at=state.handoff.completed_at,
    )

    assert plan.root_exchange_session == root_at.date().isoformat()
    assert plan.current_exchange_session == continuation_at.date().isoformat()
    assert plan.session_count == 2
    assert not plan.rebalance_due
    assert plan.targets == plan.current_positions


def test_market_state_fingerprint_is_canonical_and_evidence_sensitive(
    tmp_path: Path,
) -> None:
    first_home = tmp_path / "first"
    changed_home = tmp_path / "changed"
    first_home.mkdir()
    changed_home.mkdir()
    first = _completed_continuation(first_home)
    changed = _completed_continuation(changed_home, current_spy_ask="101")
    first_store = PaperContinuationStore(first.source.path)
    first_plan = first_store.plan_strategic_allocation(
        authorization_id=first.authorization.authorization_id,
        limits=first.source.limits,
        planned_at=first.handoff.completed_at,
    )
    repeated = first_store.plan_strategic_allocation(
        authorization_id=first.authorization.authorization_id,
        limits=first.source.limits,
        planned_at=first.handoff.completed_at,
    )
    changed_plan = PaperContinuationStore(changed.source.path).plan_strategic_allocation(
        authorization_id=changed.authorization.authorization_id,
        limits=changed.source.limits,
        planned_at=changed.handoff.completed_at,
    )
    checkpoint = StrategyEquityStore(first.source.path).latest_checkpoint(
        first.authorization.authorization_id
    )

    assert first_plan.market_state_fingerprint == fingerprint(
        {
            "account_id": first.authorization.account_id,
            "portfolio_snapshot_id": first.snapshot.snapshot_id,
            "portfolio_snapshot_fingerprint": first.snapshot.snapshot_fingerprint,
            "portfolio_attestation_fingerprint": (
                first.risk_input.portfolio_attestation_fingerprint
            ),
            "risk_input_evidence_id": first.risk_input.evidence_id,
            "market_clock": first.risk_input.clock,
            "exchange_session": first_plan.current_exchange_session,
            "quotes": first.risk_input.quotes,
            "continuation_handoff_fingerprint": first.handoff.handoff_fingerprint,
            "strategy_equity_checkpoint_fingerprint": checkpoint.checkpoint_fingerprint,
        }
    )
    assert repeated == first_plan
    assert repeated.plan_fingerprint == first_plan.plan_fingerprint
    assert changed_plan.market_state_fingerprint != first_plan.market_state_fingerprint
    assert changed_plan.plan_fingerprint != first_plan.plan_fingerprint


@pytest.mark.parametrize("mutation", ("missing", "malformed", "stale"))
def test_planner_rejects_unverifiable_market_clock(tmp_path: Path, mutation: str) -> None:
    state = _completed_continuation(tmp_path)
    with sqlite3.connect(state.source.path) as connection:
        connection.execute("DROP TRIGGER risk_input_evidence_no_update")
        if mutation == "missing":
            connection.execute(
                "UPDATE risk_input_evidence SET evidence_json = "
                "json_remove(evidence_json, '$.clock') WHERE evidence_id = ?",
                (state.risk_input.evidence_id,),
            )
        elif mutation == "malformed":
            connection.execute(
                "UPDATE risk_input_evidence SET evidence_json = "
                "json_set(evidence_json, '$.clock.provider_timestamp', 'invalid') "
                "WHERE evidence_id = ?",
                (state.risk_input.evidence_id,),
            )
        else:
            stale = state.risk_input.clock.observed_at - timedelta(
                seconds=state.risk_input.maximum_age_seconds + 1
            )
            connection.execute(
                "UPDATE risk_input_evidence SET evidence_json = "
                "json_set(evidence_json, '$.clock.provider_timestamp', ?) "
                "WHERE evidence_id = ?",
                (stale.isoformat().replace("+00:00", "Z"), state.risk_input.evidence_id),
            )

    with pytest.raises(JournalIntegrityError):
        PaperContinuationStore(state.source.path)


def test_root_session_lineage_tampering_fails_journal_verification(tmp_path: Path) -> None:
    state = _completed_continuation(tmp_path)
    with sqlite3.connect(state.source.path) as connection:
        connection.execute("DROP TRIGGER paper_continuation_declarations_no_update")
        connection.execute(
            "UPDATE paper_continuation_declarations SET previous_authorization_id = ? "
            "WHERE authorization_id = ?",
            ("missing-root", state.authorization.authorization_id),
        )

    with pytest.raises(JournalIntegrityError):
        store = PaperContinuationStore(state.source.path)
        store.plan_strategic_allocation(
            authorization_id=state.authorization.authorization_id,
            limits=state.source.limits,
            planned_at=state.handoff.completed_at,
        )


@pytest.mark.parametrize("mismatch", ["account", "configuration", "strategy"])
def test_planner_rejects_authority_mismatch(tmp_path: Path, mismatch: str) -> None:
    state = _completed_continuation(tmp_path)
    limits = state.source.limits
    authorization = state.authorization
    if mismatch == "account":
        limits = replace(limits, account_id="other-account")
    elif mismatch == "configuration":
        limits = replace(limits, review_reason="changed limits")
    else:
        authorization = replace(authorization, strategy_id="other-strategy")

    checkpoint = StrategyEquityStore(state.source.path).latest_checkpoint(
        state.authorization.authorization_id
    )
    with pytest.raises(ValueError, match="authority differs"):
        plan_strategic_allocation(
            authorization=authorization,
            limits=limits,
            handoff=state.handoff,
            snapshot=state.snapshot,
            risk_input=state.risk_input,
            checkpoint=checkpoint,
            root_authorization=state.source.authorization,
            root_risk_input=state.source.risk_input,
            root_checkpoint=state.source.checkpoint,
        )


def test_continuation_authorization_expires_and_cannot_bootstrap_flat(tmp_path: Path) -> None:
    source = _source_state(tmp_path)
    authorized_at = source.now + timedelta(seconds=20)
    store = ReconciliationStore(source.path)
    with pytest.raises(HoldoutAccessError, match="24-hour"):
        store.authorize_continuation(
            authorization_id="too-long",
            previous_authorization_id=source.authorization.authorization_id,
            limits=source.limits,
            authorized_by="reviewer",
            reason="invalid long authorization",
            authorized_at=authorized_at,
            expires_at=authorized_at + timedelta(hours=25),
        )
    with pytest.raises(HoldoutAccessError, match="settled lineage"):
        store.authorize_continuation(
            authorization_id="overlapping",
            previous_authorization_id=source.authorization.authorization_id,
            limits=source.limits,
            authorized_by="reviewer",
            reason="invalid overlapping authorization",
            authorized_at=source.authorization.expires_at - timedelta(seconds=1),
            expires_at=authorized_at + timedelta(hours=1),
        )
    authorization, _ = store.authorize_continuation(
        authorization_id="continuation-authorization",
        previous_authorization_id=source.authorization.authorization_id,
        limits=source.limits,
        authorized_by="reviewer",
        reason="second paper session",
        authorized_at=authorized_at,
        expires_at=authorized_at + timedelta(hours=1),
    )
    with pytest.raises(HoldoutAccessError, match="matching fresh flat state"):
        store.create_flat_baseline(
            baseline_id="invalid-flat-reset",
            authorization_id=authorization.authorization_id,
            expected_snapshot_id="initial-expected",
            observed_snapshot_id="initial-observed",
            limits=source.limits,
            operator="operator",
            reason="invalid continuation reset",
            created_at=authorized_at,
        )
    expires_snapshot_at = authorization.expires_at - timedelta(seconds=1)
    expires_snapshot = _attest(
        store,
        _snapshot(
            "expires-current",
            SnapshotSource.ALPACA_PAPER,
            expires_snapshot_at,
            positions=source.checkpoint.positions,
            cash=Decimal("99600"),
            buying_power=Decimal("99600"),
        ),
    )
    expires_risk_input = _risk_input(
        source.path,
        snapshot=expires_snapshot,
        authorization_id=authorization.authorization_id,
        attestation_fingerprint=_attestation_fingerprint(source.path, expires_snapshot.snapshot_id),
        limits=source.limits,
        observed_at=expires_snapshot_at,
    )
    with pytest.raises(HoldoutAccessError, match="fresh matching settled state"):
        PaperContinuationStore(source.path).complete_continuation(
            authorization_id=authorization.authorization_id,
            portfolio_snapshot_id=expires_snapshot.snapshot_id,
            risk_input_evidence_id=expires_risk_input.evidence_id,
            limits=source.limits,
            operator="operator",
            reason="expired continuation",
            completed_at=authorization.expires_at,
        )


def test_continuation_rejects_stale_or_unresolved_present_state(tmp_path: Path) -> None:
    source = _source_state(tmp_path)
    authorized_at = source.now + timedelta(seconds=20)
    authorization, _ = ReconciliationStore(source.path).authorize_continuation(
        authorization_id="continuation-authorization",
        previous_authorization_id=source.authorization.authorization_id,
        limits=source.limits,
        authorized_by="reviewer",
        reason="second paper session",
        authorized_at=authorized_at,
        expires_at=authorized_at + timedelta(hours=1),
    )
    snapshot_at = authorized_at + timedelta(seconds=1)
    snapshot = _attest(
        ReconciliationStore(source.path),
        _snapshot(
            "continuation-current",
            SnapshotSource.ALPACA_PAPER,
            snapshot_at,
            positions=source.checkpoint.positions,
            cash=Decimal("99600"),
            buying_power=Decimal("99600"),
        ),
    )
    risk_input = _risk_input(
        source.path,
        snapshot=snapshot,
        authorization_id=authorization.authorization_id,
        attestation_fingerprint=_attestation_fingerprint(source.path, snapshot.snapshot_id),
        limits=source.limits,
        observed_at=snapshot_at,
    )
    with pytest.raises(HoldoutAccessError, match="fresh matching settled state"):
        PaperContinuationStore(source.path).complete_continuation(
            authorization_id=authorization.authorization_id,
            portfolio_snapshot_id=snapshot.snapshot_id,
            risk_input_evidence_id=risk_input.evidence_id,
            limits=source.limits,
            operator="operator",
            reason="stale state",
            completed_at=snapshot_at
            + timedelta(seconds=source.limits.max_snapshot_age_seconds + 1),
        )

    bypass_intent = ExecutionIntent(
        idempotency_key="continuation:bypass",
        strategy_id=authorization.strategy_id,
        strategy_version=authorization.strategy_version,
        symbol="SPY",
        decision_timestamp=snapshot_at,
        target_weight=None,
        target_quantity=5,
        reason="unresolved continuation mutation",
        source_data_fingerprint=authorization.dataset_fingerprint,
        configuration_fingerprint=authorization.parameters_fingerprint,
        reference_price=Decimal("100"),
        expires_at=snapshot_at + timedelta(minutes=5),
    )
    risk_store = RiskStore(source.path)
    risk_store.record_intent(bypass_intent, received_at=snapshot_at)
    context = RiskContext(
        account_id=source.limits.account_id,
        evaluated_at=snapshot_at,
        equity=Decimal("100000"),
        cash=Decimal("99600"),
        buying_power=Decimal("99600"),
        current_gross_exposure=Decimal("400"),
        current_symbol_notional=Decimal("400"),
        current_symbol_quantity=4,
        pending_buy_notional=Decimal(0),
        pending_order_notional=Decimal(0),
        active_reservation_set_fingerprint=fingerprint({"reservations": []}),
        open_order_count=0,
        pending_order_count=0,
        orders_last_minute=0,
        daily_pnl=Decimal(0),
        strategy_drawdown=Decimal(0),
        quote_bid_price=Decimal("99"),
        quote_ask_price=Decimal("100"),
        account_observed_at=snapshot_at,
        positions_observed_at=snapshot_at,
        orders_observed_at=snapshot_at,
        quote_observed_at=snapshot_at,
        clock_observed_at=snapshot_at,
        regular_session_open=True,
        emergency_disabled=False,
    )
    assert risk_store._record_risk_decision_with_context(
        bypass_intent.idempotency_key, authorization.authorization_id, source.limits, context
    ).approved
    with pytest.raises(HoldoutAccessError, match="unresolved mutation"):
        PaperContinuationStore(source.path).complete_continuation(
            authorization_id=authorization.authorization_id,
            portfolio_snapshot_id=snapshot.snapshot_id,
            risk_input_evidence_id=risk_input.evidence_id,
            limits=source.limits,
            operator="operator",
            reason="unresolved state",
            completed_at=snapshot_at + timedelta(seconds=1),
        )


def test_continuation_rejects_dirty_reconciliation_and_emergency_state(tmp_path: Path) -> None:
    source = _source_state(tmp_path)
    authorized_at = source.now + timedelta(seconds=20)
    authorization, _ = ReconciliationStore(source.path).authorize_continuation(
        authorization_id="continuation-authorization",
        previous_authorization_id=source.authorization.authorization_id,
        limits=source.limits,
        authorized_by="reviewer",
        reason="second paper session",
        authorized_at=authorized_at,
        expires_at=authorized_at + timedelta(hours=1),
    )
    dirty_at = authorized_at + timedelta(seconds=1)
    dirty = _attest(
        ReconciliationStore(source.path),
        _snapshot(
            "dirty-current",
            SnapshotSource.ALPACA_PAPER,
            dirty_at,
            positions=source.checkpoint.positions,
            cash=Decimal("99600"),
            buying_power=Decimal("99600"),
        ),
    )
    ReconciliationStore(source.path).record_reconciliation(
        baseline_id="initial-baseline",
        observed_snapshot_id=dirty.snapshot_id,
        compared_at=dirty_at,
        unresolved_mutations=1,
    )
    risk_input = _risk_input(
        source.path,
        snapshot=dirty,
        authorization_id=authorization.authorization_id,
        attestation_fingerprint=_attestation_fingerprint(source.path, dirty.snapshot_id),
        limits=source.limits,
        observed_at=dirty_at,
    )
    with pytest.raises(HoldoutAccessError, match="clear emergency state"):
        PaperContinuationStore(source.path).complete_continuation(
            authorization_id=authorization.authorization_id,
            portfolio_snapshot_id=dirty.snapshot_id,
            risk_input_evidence_id=risk_input.evidence_id,
            limits=source.limits,
            operator="operator",
            reason="dirty state",
            completed_at=dirty_at + timedelta(seconds=1),
        )


def test_malformed_handoff_checkpoint_fails_as_journal_integrity_error(tmp_path: Path) -> None:
    state = _completed_continuation(tmp_path)
    with sqlite3.connect(state.source.path) as connection:
        connection.execute("DROP TRIGGER strategy_equity_checkpoints_no_update")
        row = connection.execute(
            "SELECT checkpoint_json FROM strategy_equity_checkpoints WHERE checkpoint_id = ?",
            (state.handoff.strategy_equity_checkpoint_id,),
        ).fetchone()
        assert row is not None
        connection.execute(
            "UPDATE strategy_equity_checkpoints SET checkpoint_json = "
            "json_set(checkpoint_json, '$.peak_equity', 'not-a-decimal') "
            "WHERE checkpoint_id = ?",
            (state.handoff.strategy_equity_checkpoint_id,),
        )
    with pytest.raises(JournalIntegrityError):
        ReconciliationStore(state.source.path)


def test_continuation_chain_has_one_successor_and_preserves_lineage(tmp_path: Path) -> None:
    state = _completed_continuation(
        tmp_path,
        continuation_at=datetime(2026, 8, 4, 14, 0, tzinfo=UTC),
    )
    first_plan = PaperContinuationStore(state.source.path).plan_strategic_allocation(
        authorization_id=state.authorization.authorization_id,
        limits=state.source.limits,
        planned_at=state.handoff.completed_at,
    )
    store = ReconciliationStore(state.source.path)
    second_authorized_at = datetime(2026, 9, 1, 14, 0, tzinfo=UTC)

    with pytest.raises(HoldoutAccessError, match="already has a continuation successor"):
        store.authorize_continuation(
            authorization_id="forked-continuation",
            previous_authorization_id=state.source.authorization.authorization_id,
            limits=state.source.limits,
            authorized_by="reviewer",
            reason="invalid fork",
            authorized_at=second_authorized_at,
            expires_at=second_authorized_at + timedelta(hours=1),
        )

    authorization, _ = store.authorize_continuation(
        authorization_id="continuation-authorization-2",
        previous_authorization_id=state.authorization.authorization_id,
        limits=state.source.limits,
        authorized_by="reviewer",
        reason="third paper session",
        authorized_at=second_authorized_at,
        expires_at=second_authorized_at + timedelta(hours=1),
    )
    snapshot_at = second_authorized_at + timedelta(seconds=1)
    snapshot = _attest(
        store,
        _snapshot(
            "continuation-current-2",
            SnapshotSource.ALPACA_PAPER,
            snapshot_at,
            positions=state.handoff.positions,
            cash=state.handoff.cash,
            equity=state.handoff.equity,
            buying_power=state.handoff.buying_power,
        ),
    )
    risk_input = _risk_input(
        state.source.path,
        snapshot=snapshot,
        authorization_id=authorization.authorization_id,
        attestation_fingerprint=_attestation_fingerprint(state.source.path, snapshot.snapshot_id),
        limits=state.source.limits,
        observed_at=snapshot_at,
    )
    handoff = PaperContinuationStore(state.source.path).complete_continuation(
        authorization_id=authorization.authorization_id,
        portfolio_snapshot_id=snapshot.snapshot_id,
        risk_input_evidence_id=risk_input.evidence_id,
        limits=state.source.limits,
        operator="operator",
        reason="clean chained continuation handoff",
        completed_at=snapshot_at + timedelta(seconds=1),
    )
    second_plan = PaperContinuationStore(state.source.path).plan_strategic_allocation(
        authorization_id=authorization.authorization_id,
        limits=state.source.limits,
        planned_at=handoff.completed_at,
    )

    assert first_plan.root_exchange_session == "2026-08-03"
    assert first_plan.current_exchange_session == "2026-08-04"
    assert first_plan.session_count == 2
    assert not first_plan.rebalance_due
    assert first_plan.targets == first_plan.current_positions
    assert not first_plan.trade_required
    assert second_plan.root_exchange_session == "2026-08-03"
    assert second_plan.current_exchange_session == "2026-09-01"
    assert second_plan.session_count == 22
    assert second_plan.rebalance_due
    assert handoff.previous_authorization_id == state.authorization.authorization_id
    assert handoff.source_fill_event_ids == state.handoff.source_fill_event_ids
    assert handoff.positions == state.handoff.positions
    assert handoff.gross_buy_notional == state.handoff.gross_buy_notional
    assert handoff.fill_cost_reserve == state.handoff.fill_cost_reserve
    assert handoff.strategy_cash == state.handoff.strategy_cash
    assert handoff.peak_equity == state.handoff.peak_equity
    assert handoff.strategy_drawdown == state.handoff.strategy_drawdown


def test_completed_handoff_rejects_conflicting_replay_inputs(tmp_path: Path) -> None:
    state = _completed_continuation(tmp_path)
    store = PaperContinuationStore(state.source.path)

    def replay(
        *,
        limits: RiskLimits = state.source.limits,
        operator: str = "operator",
        reason: str = "clean continuation handoff",
    ) -> PaperContinuationHandoff:
        return store.complete_continuation(
            authorization_id=state.authorization.authorization_id,
            portfolio_snapshot_id=state.snapshot.snapshot_id,
            risk_input_evidence_id=state.risk_input.evidence_id,
            limits=limits,
            operator=operator,
            reason=reason,
            completed_at=state.handoff.completed_at,
        )

    assert replay() == state.handoff
    with pytest.raises(JournalIntegrityError, match="another handoff"):
        replay(operator="other-operator")
    with pytest.raises(JournalIntegrityError, match="another handoff"):
        replay(reason="other reason")
    with pytest.raises(JournalIntegrityError, match="another handoff"):
        replay(limits=replace(state.source.limits, review_reason="changed"))


def test_cli_handoff_replay_validates_metadata_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    state = _completed_continuation(tmp_path)
    monkeypatch.setattr(cli, "load_risk_limits", lambda _: state.source.limits)
    monkeypatch.setattr(
        cli,
        "_paper_observation_reader",
        lambda *_: pytest.fail("completed handoff replay must not read the broker"),
    )

    def arguments(operator: str) -> argparse.Namespace:
        return cli.parser().parse_args(
            [
                "paper",
                "complete-continuation",
                state.authorization.authorization_id,
                "--operator",
                operator,
                "--reason",
                "clean continuation handoff",
            ]
        )

    assert cli.run(arguments("operator"), Settings(TradingMode.OFFLINE, tmp_path)) == 0
    assert '"broker_writes_allowed": false' in capsys.readouterr().out
    with pytest.raises(JournalIntegrityError, match="another handoff"):
        cli.run(arguments("other-operator"), Settings(TradingMode.OFFLINE, tmp_path))


def test_handoff_source_baseline_binding_is_verified(tmp_path: Path) -> None:
    state = _completed_continuation(tmp_path)
    with sqlite3.connect(state.source.path) as connection:
        connection.execute("DROP TRIGGER paper_continuation_handoffs_no_update")
        connection.execute(
            "UPDATE paper_continuation_handoffs SET handoff_json = "
            "json_set(handoff_json, '$.source_reconciliation_baseline_id', ?) "
            "WHERE authorization_id = ?",
            (state.handoff.reconciliation_baseline_id, state.handoff.authorization_id),
        )
    with pytest.raises(JournalIntegrityError):
        ReconciliationStore(state.source.path)


def test_pre_continuation_database_remains_readable(tmp_path: Path) -> None:
    source = _source_state(tmp_path)
    with sqlite3.connect(source.path) as connection:
        connection.execute("DROP TABLE paper_continuation_handoffs")
        connection.execute("DROP TABLE paper_continuation_declarations")

    assert (
        StrategyEquityStore(source.path).latest_checkpoint(source.authorization.authorization_id)
        == source.checkpoint
    )
    PaperSubmissionPreflightStore(source.path)
    verifier = _RecoveryVerifier(source.path)
    with verifier._connect() as connection:
        verifier._verify_all(connection)


def test_partial_continuation_schema_fails_closed(tmp_path: Path) -> None:
    source = _source_state(tmp_path)
    with sqlite3.connect(source.path) as connection:
        connection.execute("DROP TABLE paper_continuation_handoffs")

    with pytest.raises(JournalIntegrityError, match="schema and journal differ"):
        StrategyEquityStore(source.path)
