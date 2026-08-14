"""Append-only authorization handoff for an existing paper strategy portfolio."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from .execution import JournalIntegrityError
from .experiments import HoldoutAccessError
from .fingerprints import canonical_json, canonicalize, fingerprint
from .paper_planning import PresentStateActionPlan, plan_strategic_allocation
from .position_settlement import (
    _CONTINUATION_SETTLEMENT_MODE,
    _PLANNING_SETTLEMENT_MODE,
    PositionSettlementEvidence,
    _terminal_orders_at,
)
from .reconciliation import (
    PaperContinuationHandoff,
    PortfolioSnapshot,
    ReconciliationBaseline,
    ReconciliationEvidence,
    ReconciliationStore,
    SnapshotSource,
    StrategyEquityBaseline,
    _decode_continuation_handoff,
    _PaperSnapshotAttestationV2,
    reconcile,
)
from .risk import RiskLimits
from .risk_context import AttestedRiskContextStore
from .strategy_equity import (
    _CONTINUATION_CHECKPOINT_MODE,
    _PLANNING_CHECKPOINT_MODE,
    StrategyEquityCheckpoint,
)


class PaperContinuationStore(AttestedRiskContextStore):
    """Carry one settled strategy state into a new short-lived authorization."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)

    def complete_continuation(
        self,
        *,
        authorization_id: str,
        portfolio_snapshot_id: str,
        risk_input_evidence_id: str,
        limits: RiskLimits,
        operator: str,
        reason: str,
        completed_at: datetime,
    ) -> PaperContinuationHandoff:
        _utc(completed_at)
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_connection(connection)
                self._verify_reservations(connection)
                self._verify_releases(connection)
                self._verify_orders(connection)
                checkpoints = self._verify_checkpoints(connection)
                authorities = self._authorities(connection)
                snapshots, attestations, reconciliation_baselines, reconciliations = (
                    ReconciliationStore._verify_reconciliation(
                        cast(ReconciliationStore, self), connection
                    )
                )
                authorizations = self._verify_authorizations(connection)
                declarations = ReconciliationStore._verify_continuation_declarations(
                    cast(ReconciliationStore, self), connection, authorizations
                )
                existing = self._stored_handoff(connection, authorization_id)
                if existing is not None:
                    reconciliation_baseline = reconciliation_baselines.get(
                        existing.reconciliation_baseline_id
                    )
                    strategy_baseline = authorities[0].get(existing.strategy_equity_baseline_id)
                    if (
                        existing.current_snapshot_id != portfolio_snapshot_id
                        or existing.current_risk_input_evidence_id != risk_input_evidence_id
                        or existing.risk_configuration_fingerprint
                        != limits.configuration_fingerprint
                        or existing.completed_at != completed_at
                        or reconciliation_baseline is None
                        or reconciliation_baseline.operator != operator
                        or reconciliation_baseline.reason != reason
                        or strategy_baseline is None
                        or strategy_baseline.operator != operator
                        or strategy_baseline.reason != reason
                    ):
                        raise JournalIntegrityError(
                            "continuation authorization is bound to another handoff"
                        )
                    connection.commit()
                    return existing
                try:
                    declaration = declarations[authorization_id]
                    authorization = authorizations[authorization_id]
                    previous = authorizations[declaration.previous_authorization_id]
                    observed = snapshots[portfolio_snapshot_id]
                    attestation = attestations[portfolio_snapshot_id]
                    risk_input = authorities[2][risk_input_evidence_id]
                except KeyError as error:
                    raise HoldoutAccessError(
                        "continuation authority or present-state evidence is missing"
                    ) from error
                source_checkpoints = [
                    item
                    for item in checkpoints.values()
                    if item.authorization_id == declaration.previous_authorization_id
                ]
                if not source_checkpoints:
                    raise HoldoutAccessError("continuation source equity lineage is missing")
                source_checkpoint = source_checkpoints[-1]
                try:
                    source_settlement = authorities[1][source_checkpoint.settlement_proof_id]
                except KeyError as error:
                    raise HoldoutAccessError(
                        "continuation source settlement lineage is missing"
                    ) from error
                latest_advance = connection.execute(
                    "SELECT advance_fingerprint FROM expected_position_advances "
                    "WHERE baseline_id = ? ORDER BY journal_sequence DESC LIMIT 1",
                    (source_settlement.baseline_id,),
                ).fetchone()
                expected_latest_advance = (
                    (source_checkpoint.advance_fingerprint,)
                    if source_checkpoint.checkpoint_mode == "fill-replay-v1"
                    else None
                )
                nonterminal_order = connection.execute(
                    "SELECT 1 FROM orders WHERE state NOT IN ('filled', 'canceled', 'rejected') "
                    "LIMIT 1"
                ).fetchone()
                new_execution_artifact = connection.execute(
                    "SELECT 1 FROM capacity_reservations WHERE authorization_id = ? LIMIT 1",
                    (authorization_id,),
                ).fetchone()
                active_reservations = self._active_reservation_set(
                    connection,
                    account_id=authorization.account_id,
                    at=completed_at,
                )
                if (
                    not isinstance(attestation, _PaperSnapshotAttestationV2)
                    or authorization.account_id != limits.account_id
                    or authorization.risk_configuration_fingerprint
                    != limits.configuration_fingerprint
                    or previous.account_id != authorization.account_id
                    or previous.candidate_id != authorization.candidate_id
                    or previous.strategy_id != authorization.strategy_id
                    or previous.strategy_version != authorization.strategy_version
                    or previous.parameters_fingerprint != authorization.parameters_fingerprint
                    or previous.risk_configuration_fingerprint
                    != authorization.risk_configuration_fingerprint
                    or not authorization.authorized_at <= completed_at < authorization.expires_at
                    or not limits.effective_at <= completed_at < limits.expires_at
                    or observed.account_id != authorization.account_id
                    or observed.source is not SnapshotSource.ALPACA_PAPER
                    or not observed.account_ready
                    or observed.open_orders
                    or observed.positions != source_checkpoint.positions
                    or any(
                        observed_at < authorization.authorized_at
                        or observed_at > completed_at
                        or (completed_at - observed_at).total_seconds()
                        > limits.max_snapshot_age_seconds
                        for observed_at in (
                            observed.account_observed_at,
                            observed.positions_observed_at,
                            observed.orders_observed_at,
                        )
                    )
                    or risk_input.authorization_id != authorization_id
                    or risk_input.account_id != authorization.account_id
                    or risk_input.risk_configuration_fingerprint != limits.configuration_fingerprint
                    or risk_input.portfolio_snapshot_id != observed.snapshot_id
                    or risk_input.portfolio_snapshot_fingerprint != observed.snapshot_fingerprint
                    or risk_input.portfolio_attestation_fingerprint
                    != attestation.attestation_fingerprint
                    or risk_input.completed_at > completed_at
                    or any(
                        market_observed_at > completed_at
                        or (completed_at - market_observed_at).total_seconds()
                        > limits.max_snapshot_age_seconds
                        for market_observed_at in (
                            risk_input.clock.observed_at,
                            *(quote.observed_at for quote in risk_input.quotes),
                        )
                    )
                    or source_checkpoint.account_id != authorization.account_id
                    or source_checkpoint.strategy_id != authorization.strategy_id
                    or source_checkpoint.strategy_version != authorization.strategy_version
                    or source_checkpoint.risk_configuration_fingerprint
                    != limits.configuration_fingerprint
                    or source_checkpoint.allocated_capital != limits.strategy_capital_allocation
                    or source_checkpoint.marked_at > authorization.authorized_at
                    or source_settlement.authorization_id != declaration.previous_authorization_id
                    or source_settlement.account_id != authorization.account_id
                    or source_settlement.risk_configuration_fingerprint
                    != limits.configuration_fingerprint
                    or latest_advance != expected_latest_advance
                    or nonterminal_order is not None
                    or new_execution_artifact is not None
                    or active_reservations.reservation_count
                ):
                    raise HoldoutAccessError(
                        "continuation requires fresh matching settled state with no "
                        "unresolved mutation"
                    )
                emergency = self._verify_emergency(connection)
                if emergency.disabled:
                    raise HoldoutAccessError("continuation requires clear emergency state")
                if any(
                    item.authorization_id == authorization_id
                    for item in reconciliation_baselines.values()
                ) or any(
                    item.authorization_id == authorization_id for item in authorities[0].values()
                ):
                    raise HoldoutAccessError(
                        "continuation authorization already has baseline state"
                    )

                ids = {
                    name: fingerprint({"authorization_id": authorization_id, "kind": name})
                    for name in (
                        "expected-snapshot",
                        "reconciliation-baseline",
                        "strategy-equity-baseline",
                        "settlement-proof",
                    )
                }
                expected = replace(
                    observed,
                    snapshot_id=ids["expected-snapshot"],
                    source=SnapshotSource.LOCAL_EXPECTED,
                )
                comparison = reconcile(
                    expected,
                    observed,
                    compared_at=completed_at,
                    maximum_age_seconds=limits.max_snapshot_age_seconds,
                    unresolved_mutations=0,
                )
                if not comparison.clean:
                    raise HoldoutAccessError("continuation reconciliation is dirty")
                reconciliation_baseline = ReconciliationBaseline(
                    baseline_id=ids["reconciliation-baseline"],
                    authorization_id=authorization_id,
                    expected_snapshot_id=expected.snapshot_id,
                    observed_snapshot_id=observed.snapshot_id,
                    expected_fingerprint=expected.snapshot_fingerprint,
                    observed_fingerprint=observed.snapshot_fingerprint,
                    account_id=authorization.account_id,
                    risk_configuration_fingerprint=limits.configuration_fingerprint,
                    comparison_fingerprint=comparison.result_fingerprint,
                    maximum_age_seconds=limits.max_snapshot_age_seconds,
                    operator=operator,
                    reason=reason,
                    created_at=completed_at,
                )
                reconciliation_evidence_id = fingerprint(
                    {
                        "baseline_id": reconciliation_baseline.baseline_id,
                        "observed_snapshot_id": observed.snapshot_id,
                        "maximum_age_seconds": limits.max_snapshot_age_seconds,
                        "unresolved_mutations": 0,
                        "result": comparison,
                    }
                )
                reconciliation_evidence = ReconciliationEvidence(
                    evidence_id=reconciliation_evidence_id,
                    baseline_id=reconciliation_baseline.baseline_id,
                    observed_snapshot_id=observed.snapshot_id,
                    maximum_age_seconds=limits.max_snapshot_age_seconds,
                    unresolved_mutations=0,
                    result=comparison,
                )
                strategy_baseline = StrategyEquityBaseline(
                    baseline_id=ids["strategy-equity-baseline"],
                    authorization_id=authorization_id,
                    authorization_fingerprint=authorization.authorization_fingerprint,
                    reconciliation_baseline_id=reconciliation_baseline.baseline_id,
                    reconciliation_baseline_fingerprint=fingerprint(reconciliation_baseline),
                    account_id=authorization.account_id,
                    strategy_id=authorization.strategy_id,
                    strategy_version=authorization.strategy_version,
                    risk_configuration_fingerprint=limits.configuration_fingerprint,
                    allocated_capital=source_checkpoint.allocated_capital,
                    operator=operator,
                    reason=reason,
                    created_at=completed_at,
                )
                next_sequence = int(
                    connection.execute(
                        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM journal"
                    ).fetchone()[0]
                )
                settlement = PositionSettlementEvidence(
                    proof_id=ids["settlement-proof"],
                    baseline_id=reconciliation_baseline.baseline_id,
                    authorization_id=authorization_id,
                    account_id=authorization.account_id,
                    risk_configuration_fingerprint=limits.configuration_fingerprint,
                    advance_fingerprint=source_checkpoint.advance_fingerprint,
                    observed_snapshot_id=observed.snapshot_id,
                    observed_snapshot_fingerprint=observed.snapshot_fingerprint,
                    attestation_fingerprint=attestation.attestation_fingerprint,
                    terminal_orders=_terminal_orders_at(
                        connection,
                        account_id=authorization.account_id,
                        before_sequence=next_sequence,
                    ),
                    emergency_generation=emergency.generation,
                    settled_at=completed_at,
                    settlement_mode=_CONTINUATION_SETTLEMENT_MODE,
                    reconciliation_evidence_id=reconciliation_evidence.evidence_id,
                )
                checkpoint = self._derive_continuation_checkpoint(
                    connection,
                    baseline=strategy_baseline,
                    settlement=settlement,
                    risk_input=risk_input,
                    fill_cost_bps=limits.strategy_fill_cost_bps,
                    prior=None,
                    marked_at=completed_at,
                    before_sequence=None,
                )
                handoff = PaperContinuationHandoff(
                    authorization_id=authorization_id,
                    declaration_fingerprint=declaration.declaration_fingerprint,
                    previous_authorization_id=previous.authorization_id,
                    source_authorization_fingerprint=previous.authorization_fingerprint,
                    candidate_id=authorization.candidate_id,
                    strategy_id=authorization.strategy_id,
                    strategy_version=authorization.strategy_version,
                    account_id=authorization.account_id,
                    risk_configuration_fingerprint=limits.configuration_fingerprint,
                    source_reconciliation_baseline_id=source_settlement.baseline_id,
                    source_settlement_proof_id=source_settlement.proof_id,
                    source_settlement_proof_fingerprint=source_settlement.proof_fingerprint,
                    source_strategy_equity_checkpoint_id=source_checkpoint.checkpoint_id,
                    source_strategy_equity_checkpoint_fingerprint=(
                        source_checkpoint.checkpoint_fingerprint
                    ),
                    source_fill_event_ids=source_checkpoint.fill_event_ids,
                    current_snapshot_id=observed.snapshot_id,
                    current_snapshot_fingerprint=observed.snapshot_fingerprint,
                    current_attestation_fingerprint=attestation.attestation_fingerprint,
                    current_risk_input_evidence_id=risk_input.evidence_id,
                    reconciliation_baseline_id=reconciliation_baseline.baseline_id,
                    reconciliation_baseline_fingerprint=fingerprint(reconciliation_baseline),
                    reconciliation_evidence_id=reconciliation_evidence.evidence_id,
                    strategy_equity_baseline_id=strategy_baseline.baseline_id,
                    strategy_equity_baseline_fingerprint=strategy_baseline.baseline_fingerprint,
                    settlement_proof_id=settlement.proof_id,
                    settlement_proof_fingerprint=settlement.proof_fingerprint,
                    strategy_equity_checkpoint_id=checkpoint.checkpoint_id,
                    strategy_equity_checkpoint_fingerprint=checkpoint.checkpoint_fingerprint,
                    cash=observed.cash,
                    equity=observed.equity,
                    buying_power=observed.buying_power,
                    positions=observed.positions,
                    allocated_capital=checkpoint.allocated_capital,
                    gross_buy_notional=checkpoint.gross_buy_notional,
                    gross_sell_notional=checkpoint.gross_sell_notional,
                    fill_cost_reserve=checkpoint.fill_cost_reserve,
                    strategy_cash=checkpoint.strategy_cash,
                    strategy_equity=checkpoint.strategy_equity,
                    peak_equity=checkpoint.peak_equity,
                    strategy_drawdown=checkpoint.strategy_drawdown,
                    emergency_generation=emergency.generation,
                    completed_at=completed_at,
                )
                self._insert_handoff_evidence(
                    connection,
                    expected=expected,
                    reconciliation_baseline=reconciliation_baseline,
                    reconciliation_evidence=reconciliation_evidence,
                    strategy_baseline=strategy_baseline,
                    settlement=settlement,
                    checkpoint=checkpoint,
                    handoff=handoff,
                )
                connection.commit()
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise JournalIntegrityError("paper continuation evidence already exists") from error
            except Exception:
                connection.rollback()
                raise
        return handoff

    def record_planning_checkpoint(
        self,
        *,
        authorization_id: str,
        portfolio_snapshot_id: str,
        risk_input_evidence_id: str,
        limits: RiskLimits,
        marked_at: datetime,
    ) -> StrategyEquityCheckpoint:
        """Bind fresh GET-only state to an immutable continuation handoff."""
        _utc(marked_at)
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_connection(connection)
                self._verify_reservations(connection)
                self._verify_releases(connection)
                self._verify_orders(connection)
                checkpoints = self._verify_checkpoints(connection)
                authorities = self._authorities(connection)
                snapshots, attestations, _, reconciliations = (
                    ReconciliationStore._verify_reconciliation(
                        cast(ReconciliationStore, self), connection
                    )
                )
                authorizations = self._verify_authorizations(connection)
                handoff = self._stored_handoff(connection, authorization_id)
                if handoff is None:
                    raise HoldoutAccessError("paper planning requires a completed continuation")
                try:
                    authorization = authorizations[authorization_id]
                    observed = snapshots[portfolio_snapshot_id]
                    attestation = attestations[portfolio_snapshot_id]
                    risk_input = authorities[2][risk_input_evidence_id]
                    baseline = authorities[0][handoff.strategy_equity_baseline_id]
                    handoff_checkpoint = checkpoints[handoff.strategy_equity_checkpoint_id]
                    handoff_settlement = authorities[1][handoff.settlement_proof_id]
                    handoff_reconciliation = reconciliations[handoff.reconciliation_evidence_id]
                except KeyError as error:
                    raise JournalIntegrityError(
                        "paper planning authority or fresh evidence is missing"
                    ) from error
                matching = [
                    item
                    for item in checkpoints.values()
                    if item.authorization_id == authorization_id
                ]
                if not matching:
                    raise HoldoutAccessError("paper planning strategy equity is missing")
                prior = matching[-1]
                replay = next(
                    (
                        item
                        for item in matching
                        if item.risk_input_evidence_id == risk_input_evidence_id
                    ),
                    None,
                )
                if replay is not None:
                    replay_settlement = authorities[1].get(replay.settlement_proof_id)
                    if (
                        replay.checkpoint_mode != _PLANNING_CHECKPOINT_MODE
                        or replay.marked_at != marked_at
                        or replay.authorization_id != authorization_id
                        or replay.risk_configuration_fingerprint != limits.configuration_fingerprint
                        or replay_settlement is None
                        or replay_settlement.observed_snapshot_id != portfolio_snapshot_id
                        or risk_input.portfolio_snapshot_id != portfolio_snapshot_id
                    ):
                        raise JournalIntegrityError(
                            "risk input is bound to different paper planning evidence"
                        )
                    connection.commit()
                    return replay
                active_reservations = self._active_reservation_set(
                    connection,
                    account_id=authorization.account_id,
                    at=marked_at,
                )
                execution_artifact = connection.execute(
                    "SELECT 1 FROM capacity_reservations WHERE authorization_id = ? LIMIT 1",
                    (authorization_id,),
                ).fetchone()
                nonterminal_order = connection.execute(
                    "SELECT 1 FROM orders WHERE state NOT IN "
                    "('filled', 'canceled', 'rejected') LIMIT 1"
                ).fetchone()
                emergency = self._verify_emergency(connection)
                observation_times = (
                    observed.account_observed_at,
                    observed.positions_observed_at,
                    observed.orders_observed_at,
                    risk_input.clock.observed_at,
                    *(quote.observed_at for quote in risk_input.quotes),
                )
                if (
                    not isinstance(attestation, _PaperSnapshotAttestationV2)
                    or authorization.account_id != limits.account_id
                    or authorization.risk_configuration_fingerprint
                    != limits.configuration_fingerprint
                    or authorization.candidate_id != handoff.candidate_id
                    or authorization.strategy_id != handoff.strategy_id
                    or authorization.strategy_version != handoff.strategy_version
                    or authorization.account_id != handoff.account_id
                    or authorization.risk_configuration_fingerprint
                    != handoff.risk_configuration_fingerprint
                    or not authorization.authorized_at <= marked_at < authorization.expires_at
                    or not limits.effective_at <= marked_at < limits.expires_at
                    or portfolio_snapshot_id == handoff.current_snapshot_id
                    or risk_input_evidence_id == handoff.current_risk_input_evidence_id
                    or observed.source is not SnapshotSource.ALPACA_PAPER
                    or observed.account_id != authorization.account_id
                    or not observed.account_ready
                    or bool(observed.open_orders)
                    or observed.positions != handoff.positions
                    or observed.cash != handoff.cash
                    or not set(item.symbol for item in observed.positions).issubset(
                        limits.allowed_symbols
                    )
                    or risk_input.authorization_id != authorization_id
                    or risk_input.account_id != authorization.account_id
                    or risk_input.risk_configuration_fingerprint != limits.configuration_fingerprint
                    or risk_input.maximum_age_seconds != limits.max_snapshot_age_seconds
                    or risk_input.portfolio_snapshot_id != observed.snapshot_id
                    or risk_input.portfolio_snapshot_fingerprint != observed.snapshot_fingerprint
                    or risk_input.portfolio_attestation_fingerprint
                    != attestation.attestation_fingerprint
                    or set(item.symbol for item in risk_input.quotes) != set(limits.allowed_symbols)
                    or risk_input.completed_at > marked_at
                    or any(
                        observed_at <= handoff.completed_at
                        or observed_at > marked_at
                        or (marked_at - observed_at).total_seconds()
                        > limits.max_snapshot_age_seconds
                        for observed_at in observation_times
                    )
                    or handoff_checkpoint.checkpoint_fingerprint
                    != handoff.strategy_equity_checkpoint_fingerprint
                    or handoff_settlement.proof_fingerprint != handoff.settlement_proof_fingerprint
                    or handoff_reconciliation.observed_snapshot_id != handoff.current_snapshot_id
                    or not handoff_reconciliation.result.clean
                    or handoff_reconciliation.unresolved_mutations != 0
                    or prior.checkpoint_mode
                    not in {
                        _CONTINUATION_CHECKPOINT_MODE,
                        _PLANNING_CHECKPOINT_MODE,
                    }
                    or prior.strategy_equity_baseline_id != handoff.strategy_equity_baseline_id
                    or prior.authorization_id != authorization_id
                    or prior.account_id != authorization.account_id
                    or prior.strategy_id != authorization.strategy_id
                    or prior.strategy_version != authorization.strategy_version
                    or prior.risk_configuration_fingerprint != limits.configuration_fingerprint
                    or prior.positions != handoff.positions
                    or prior.advance_fingerprint != handoff_checkpoint.advance_fingerprint
                    or prior.fill_event_ids != handoff_checkpoint.fill_event_ids
                    or prior.allocated_capital != handoff.allocated_capital
                    or prior.gross_buy_notional != handoff.gross_buy_notional
                    or prior.gross_sell_notional != handoff.gross_sell_notional
                    or prior.fill_cost_reserve != handoff.fill_cost_reserve
                    or prior.strategy_cash != handoff.strategy_cash
                    or prior.peak_equity < handoff.peak_equity
                    or prior.marked_at >= marked_at
                    or emergency.disabled
                    or emergency.generation != handoff.emergency_generation
                    or active_reservations.reservation_count
                    or execution_artifact is not None
                    or nonterminal_order is not None
                ):
                    raise HoldoutAccessError(
                        "paper planning requires fresh unchanged continuation state with no "
                        "unresolved mutation"
                    )
                next_sequence = int(
                    connection.execute(
                        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM journal"
                    ).fetchone()[0]
                )
                terminal_orders = _terminal_orders_at(
                    connection,
                    account_id=authorization.account_id,
                    before_sequence=next_sequence,
                )
                if terminal_orders != handoff_settlement.terminal_orders:
                    raise HoldoutAccessError(
                        "paper planning terminal order lineage changed after handoff"
                    )
                settlement = PositionSettlementEvidence(
                    proof_id=fingerprint(
                        {
                            "kind": _PLANNING_SETTLEMENT_MODE,
                            "authorization_id": authorization_id,
                            "handoff_fingerprint": handoff.handoff_fingerprint,
                            "prior_checkpoint_fingerprint": prior.checkpoint_fingerprint,
                            "portfolio_snapshot_fingerprint": observed.snapshot_fingerprint,
                            "risk_input_evidence_id": risk_input.evidence_id,
                            "marked_at": marked_at,
                        }
                    ),
                    baseline_id=handoff.reconciliation_baseline_id,
                    authorization_id=authorization_id,
                    account_id=authorization.account_id,
                    risk_configuration_fingerprint=limits.configuration_fingerprint,
                    advance_fingerprint=prior.advance_fingerprint,
                    observed_snapshot_id=observed.snapshot_id,
                    observed_snapshot_fingerprint=observed.snapshot_fingerprint,
                    attestation_fingerprint=attestation.attestation_fingerprint,
                    terminal_orders=terminal_orders,
                    emergency_generation=emergency.generation,
                    settled_at=marked_at,
                    settlement_mode=_PLANNING_SETTLEMENT_MODE,
                    reconciliation_evidence_id=handoff.reconciliation_evidence_id,
                )
                checkpoint = self._derive_checkpoint(
                    connection,
                    baseline=baseline,
                    settlement=settlement,
                    risk_input=risk_input,
                    fill_cost_bps=limits.strategy_fill_cost_bps,
                    prior=prior,
                    marked_at=marked_at,
                    before_sequence=None,
                )
                self._insert_planning_checkpoint(
                    connection,
                    settlement=settlement,
                    checkpoint=checkpoint,
                )
                connection.commit()
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise JournalIntegrityError("paper planning evidence already exists") from error
            except Exception:
                connection.rollback()
                raise
        return checkpoint

    def plan_strategic_allocation(
        self,
        *,
        authorization_id: str,
        planning_checkpoint_id: str,
        limits: RiskLimits,
        planned_at: datetime,
    ) -> PresentStateActionPlan:
        """Read immutable continuation evidence and derive a broker-free plan."""
        _utc(planned_at)
        with self._connect() as connection:
            connection.execute("BEGIN")
            risk_context = self._derive(
                connection,
                authorization_id=authorization_id,
                symbol=limits.allowed_symbols[0],
                limits=limits,
                evaluated_at=planned_at,
                exclude_intent_id=None,
            )
            checkpoints = self._verify_checkpoints(connection)
            authorities = self._authorities(connection)
            snapshots, _, _, reconciliations = ReconciliationStore._verify_reconciliation(
                cast(ReconciliationStore, self), connection
            )
            authorizations = self._verify_authorizations(connection)
            declarations = ReconciliationStore._verify_continuation_declarations(
                cast(ReconciliationStore, self), connection, authorizations
            )
            handoff = self._stored_handoff(connection, authorization_id)
            if handoff is None:
                raise HoldoutAccessError("paper planning requires a completed continuation")
            matching = [
                item for item in checkpoints.values() if item.authorization_id == authorization_id
            ]
            if not matching:
                raise HoldoutAccessError("paper planning strategy equity is missing")
            try:
                checkpoint = checkpoints[planning_checkpoint_id]
                handoff_checkpoint = checkpoints[handoff.strategy_equity_checkpoint_id]
                settlement = authorities[1][checkpoint.settlement_proof_id]
                risk_input = authorities[2][checkpoint.risk_input_evidence_id]
                snapshot = snapshots[risk_input.portfolio_snapshot_id]
            except KeyError as error:
                raise JournalIntegrityError("paper planning present state is missing") from error
            if any(
                quote.observed_at > planned_at
                or (planned_at - quote.observed_at).total_seconds()
                > limits.max_snapshot_age_seconds
                for quote in risk_input.quotes
            ):
                raise JournalIntegrityError("paper planning market evidence is stale or mismatched")
            latest_reconciliation_row = connection.execute(
                "SELECT evidence_id FROM reconciliation_evidence "
                "WHERE json_extract(evidence_json, '$.baseline_id') = ? "
                "ORDER BY journal_sequence DESC LIMIT 1",
                (handoff.reconciliation_baseline_id,),
            ).fetchone()
            latest_reconciliation = (
                None
                if latest_reconciliation_row is None
                else reconciliations.get(str(latest_reconciliation_row[0]))
            )
            execution_artifact = connection.execute(
                "SELECT 1 FROM capacity_reservations WHERE authorization_id = ? LIMIT 1",
                (authorization_id,),
            ).fetchone()
            nonterminal_order = connection.execute(
                "SELECT 1 FROM orders WHERE state NOT IN ('filled', 'canceled', 'rejected') LIMIT 1"
            ).fetchone()
            if (
                matching[-1].checkpoint_id != planning_checkpoint_id
                or checkpoint.authorization_id != authorization_id
                or checkpoint.checkpoint_mode != _PLANNING_CHECKPOINT_MODE
                or settlement.settlement_mode != _PLANNING_SETTLEMENT_MODE
                or settlement.reconciliation_evidence_id != handoff.reconciliation_evidence_id
                or settlement.observed_snapshot_id != snapshot.snapshot_id
                or handoff_checkpoint.checkpoint_fingerprint
                != handoff.strategy_equity_checkpoint_fingerprint
                or latest_reconciliation is None
                or latest_reconciliation.evidence_id != handoff.reconciliation_evidence_id
                or not latest_reconciliation.result.clean
                or latest_reconciliation.unresolved_mutations != 0
                or latest_reconciliation.observed_snapshot_id != handoff.current_snapshot_id
                or risk_context.context.open_order_count != 0
                or risk_context.context.pending_order_count != 0
                or risk_context.context.emergency_disabled
                or execution_artifact is not None
                or nonterminal_order is not None
            ):
                raise HoldoutAccessError(
                    "paper planning requires unchanged clean continuation state"
                )
            authorization = authorizations[authorization_id]
            root_authorization_id = authorization_id
            visited: set[str] = set()
            while root_authorization_id in declarations:
                if root_authorization_id in visited:
                    raise JournalIntegrityError("paper planning continuation lineage is cyclic")
                visited.add(root_authorization_id)
                root_authorization_id = declarations[
                    root_authorization_id
                ].previous_authorization_id
            try:
                root_authorization = authorizations[root_authorization_id]
                root_checkpoint = next(
                    item
                    for item in checkpoints.values()
                    if item.authorization_id == root_authorization_id and item.fill_event_ids
                )
                root_risk_input = authorities[2][root_checkpoint.risk_input_evidence_id]
            except (KeyError, StopIteration) as error:
                raise HoldoutAccessError(
                    "paper planning root strategy session is missing"
                ) from error
            return plan_strategic_allocation(
                authorization=authorization,
                limits=limits,
                handoff=handoff,
                snapshot=snapshot,
                risk_input=risk_input,
                handoff_checkpoint=handoff_checkpoint,
                planning_settlement=settlement,
                planning_checkpoint=checkpoint,
                root_authorization=root_authorization,
                root_risk_input=root_risk_input,
                root_checkpoint=root_checkpoint,
            )

    def get_handoff(self, authorization_id: str) -> PaperContinuationHandoff:
        with self._connect() as connection:
            connection.execute("BEGIN")
            self._verify_checkpoints(connection)
            handoff = self._stored_handoff(connection, authorization_id)
        if handoff is None:
            raise KeyError(authorization_id)
        return handoff

    def _stored_handoff(
        self, connection: sqlite3.Connection, authorization_id: str
    ) -> PaperContinuationHandoff | None:
        row = connection.execute(
            "SELECT handoff_json FROM paper_continuation_handoffs WHERE authorization_id = ?",
            (authorization_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            return _decode_continuation_handoff(json.loads(str(row[0])))
        except (json.JSONDecodeError, ValueError) as error:
            raise JournalIntegrityError("stored paper continuation handoff is invalid") from error

    def _insert_handoff_evidence(
        self,
        connection: sqlite3.Connection,
        *,
        expected: PortfolioSnapshot,
        reconciliation_baseline: ReconciliationBaseline,
        reconciliation_evidence: ReconciliationEvidence,
        strategy_baseline: StrategyEquityBaseline,
        settlement: PositionSettlementEvidence,
        checkpoint: StrategyEquityCheckpoint,
        handoff: PaperContinuationHandoff,
    ) -> None:
        ReconciliationStore._record_snapshot(
            cast(ReconciliationStore, self), connection, expected, handoff.completed_at
        )
        sequence = self._append_event(
            connection,
            occurred_at=handoff.completed_at,
            event_type="reconciliation-baseline-created",
            entity_type="reconciliation-baseline",
            entity_id=reconciliation_baseline.baseline_id,
            payload=canonicalize(reconciliation_baseline),
        )
        connection.execute(
            "INSERT INTO reconciliation_baselines VALUES (?, ?, ?)",
            (
                reconciliation_baseline.baseline_id,
                canonical_json(reconciliation_baseline),
                sequence,
            ),
        )
        sequence = self._append_event(
            connection,
            occurred_at=handoff.completed_at,
            event_type="reconciliation-recorded",
            entity_type="reconciliation-evidence",
            entity_id=reconciliation_evidence.evidence_id,
            payload=canonicalize(reconciliation_evidence),
        )
        connection.execute(
            "INSERT INTO reconciliation_evidence VALUES (?, ?, ?)",
            (
                reconciliation_evidence.evidence_id,
                canonical_json(reconciliation_evidence),
                sequence,
            ),
        )
        sequence = self._append_event(
            connection,
            occurred_at=handoff.completed_at,
            event_type="strategy-equity-baseline-created",
            entity_type="strategy-equity-baseline",
            entity_id=strategy_baseline.baseline_id,
            payload=canonicalize(strategy_baseline),
        )
        connection.execute(
            "INSERT INTO strategy_equity_baselines VALUES (?, ?, ?, ?, ?, ?)",
            (
                strategy_baseline.baseline_id,
                strategy_baseline.authorization_id,
                strategy_baseline.reconciliation_baseline_id,
                strategy_baseline.baseline_fingerprint,
                canonical_json(strategy_baseline),
                sequence,
            ),
        )
        sequence = self._append_event(
            connection,
            occurred_at=handoff.completed_at,
            event_type="position-settlement-proved",
            entity_type="position-settlement",
            entity_id=settlement.proof_id,
            payload=canonicalize(settlement),
        )
        connection.execute(
            "INSERT INTO position_settlement_evidence VALUES (?, ?, ?, ?, ?, ?)",
            (
                settlement.proof_id,
                settlement.baseline_id,
                settlement.advance_fingerprint,
                settlement.observed_snapshot_id,
                canonical_json(settlement),
                sequence,
            ),
        )
        sequence = self._append_event(
            connection,
            occurred_at=handoff.completed_at,
            event_type="strategy-equity-checkpoint-recorded",
            entity_type="strategy-equity-checkpoint",
            entity_id=checkpoint.checkpoint_id,
            payload=canonicalize(checkpoint),
        )
        connection.execute(
            "INSERT INTO strategy_equity_checkpoints VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                checkpoint.checkpoint_id,
                checkpoint.strategy_equity_baseline_id,
                checkpoint.settlement_proof_id,
                checkpoint.risk_input_evidence_id,
                checkpoint.checkpoint_fingerprint,
                canonical_json(checkpoint),
                sequence,
            ),
        )
        sequence = self._append_event(
            connection,
            occurred_at=handoff.completed_at,
            event_type="paper-continuation-completed",
            entity_type="paper-continuation-handoff",
            entity_id=handoff.authorization_id,
            payload=canonicalize(handoff),
        )
        connection.execute(
            "INSERT INTO paper_continuation_handoffs VALUES (?, ?, ?, ?)",
            (
                handoff.authorization_id,
                handoff.handoff_fingerprint,
                canonical_json(handoff),
                sequence,
            ),
        )

    def _insert_planning_checkpoint(
        self,
        connection: sqlite3.Connection,
        *,
        settlement: PositionSettlementEvidence,
        checkpoint: StrategyEquityCheckpoint,
    ) -> None:
        sequence = self._append_event(
            connection,
            occurred_at=settlement.settled_at,
            event_type="position-settlement-proved",
            entity_type="position-settlement",
            entity_id=settlement.proof_id,
            payload=canonicalize(settlement),
        )
        connection.execute(
            "INSERT INTO position_settlement_evidence VALUES (?, ?, ?, ?, ?, ?)",
            (
                settlement.proof_id,
                settlement.baseline_id,
                settlement.advance_fingerprint,
                settlement.observed_snapshot_id,
                canonical_json(settlement),
                sequence,
            ),
        )
        sequence = self._append_event(
            connection,
            occurred_at=checkpoint.marked_at,
            event_type="strategy-equity-checkpoint-recorded",
            entity_type="strategy-equity-checkpoint",
            entity_id=checkpoint.checkpoint_id,
            payload=canonicalize(checkpoint),
        )
        connection.execute(
            "INSERT INTO strategy_equity_checkpoints VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                checkpoint.checkpoint_id,
                checkpoint.strategy_equity_baseline_id,
                checkpoint.settlement_proof_id,
                checkpoint.risk_input_evidence_id,
                checkpoint.checkpoint_fingerprint,
                canonical_json(checkpoint),
                sequence,
            ),
        )


def _utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("paper continuation time must be UTC-aware")
