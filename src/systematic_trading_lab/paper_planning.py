"""Deterministic broker-free planning for the approved strategic allocation."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .calendar import expected_sessions
from .fingerprints import canonical_json, canonicalize, fingerprint
from .orders import whole_share_target
from .paper_equivalence import ActionPlan, ActionTarget
from .position_settlement import _PLANNING_SETTLEMENT_MODE, PositionSettlementEvidence
from .reconciliation import PaperContinuationHandoff, PortfolioSnapshot
from .risk import PaperAuthorization, RiskLimits
from .risk_inputs import RiskInputEvidence
from .strategies import STRATEGIC_ALLOCATION_WEIGHTS
from .strategy_equity import (
    _FILL_CHECKPOINT_MODE,
    _PLANNING_CHECKPOINT_MODE,
    StrategyEquityCheckpoint,
)

_CANDIDATE_ID = "strategic-allocation-21"
_STRATEGY_ID = "strategic-allocation-portfolio"
_STRATEGY_VERSION = "1"
_REBALANCE_EVERY = 21
_PARAMETERS = {"rebalance_every": _REBALANCE_EVERY}
_SIZING_MODEL = "whole-share-floor-at-ask-v1"
_XNYS_TIMEZONE = ZoneInfo("America/New_York")


@dataclass(frozen=True, order=True)
class ActionDelta:
    symbol: str
    current_quantity: int
    target_quantity: int
    delta: int

    def __post_init__(self) -> None:
        if (
            not self.symbol
            or self.symbol != self.symbol.upper()
            or isinstance(self.current_quantity, bool)
            or isinstance(self.target_quantity, bool)
            or isinstance(self.delta, bool)
            or self.current_quantity < 0
            or self.target_quantity < 0
            or self.delta != self.target_quantity - self.current_quantity
        ):
            raise ValueError("paper planning delta is invalid")


@dataclass(frozen=True)
class PresentStateActionPlan:
    authorization_id: str
    candidate_id: str
    strategy_id: str
    strategy_version: str
    account_id: str
    root_exchange_session: str
    current_exchange_session: str
    session_count: int
    rebalance_every: int
    rebalance_due: bool
    source_data_fingerprint: str
    source_state_fingerprint: str
    market_state_fingerprint: str
    configuration_fingerprint: str
    current_positions: tuple[ActionTarget, ...]
    targets: tuple[ActionTarget, ...]
    deltas: tuple[ActionDelta, ...]
    evidence_fingerprints: tuple[str, ...]
    replay: ActionPlan
    shadow: ActionPlan
    authority: tuple[tuple[str, bool], ...] = (
        ("intent", False),
        ("risk", False),
        ("activation", False),
        ("broker_write", False),
        ("live", False),
    )

    def __post_init__(self) -> None:
        try:
            root_session = date.fromisoformat(self.root_exchange_session)
            current_session = date.fromisoformat(self.current_exchange_session)
            derived_session_count = _session_count(root_session, current_session)
        except ValueError as error:
            raise ValueError("present-state action plan sessions are invalid") from error
        if (
            not self.authorization_id
            or self.candidate_id != _CANDIDATE_ID
            or self.strategy_id != _STRATEGY_ID
            or self.strategy_version != _STRATEGY_VERSION
            or not self.account_id
            or self.root_exchange_session != root_session.isoformat()
            or self.current_exchange_session != current_session.isoformat()
            or isinstance(self.session_count, bool)
            or self.session_count < 1
            or self.session_count != derived_session_count
            or self.rebalance_every != _REBALANCE_EVERY
            or self.rebalance_due
            != (self.session_count == 1 or (self.session_count - 1) % self.rebalance_every == 0)
            or self.current_positions != tuple(sorted(self.current_positions))
            or self.targets != tuple(sorted(self.targets))
            or self.deltas != tuple(sorted(self.deltas))
            or tuple(item.symbol for item in self.current_positions)
            != tuple(item.symbol for item in self.targets)
            or tuple(item.symbol for item in self.targets)
            != tuple(item.symbol for item in self.deltas)
            or any(
                delta.current_quantity != current.quantity
                or delta.target_quantity != target.quantity
                for current, target, delta in zip(
                    self.current_positions, self.targets, self.deltas, strict=True
                )
            )
            or self.evidence_fingerprints != tuple(sorted(set(self.evidence_fingerprints)))
            or self.replay.mode != "replay"
            or self.shadow.mode != "shadow"
            or self.replay.targets != self.targets
            or self.shadow.targets != self.targets
            or self.replay.source_data_fingerprint != self.source_data_fingerprint
            or self.shadow.source_data_fingerprint != self.source_data_fingerprint
            or self.replay.configuration_fingerprint != self.configuration_fingerprint
            or self.shadow.configuration_fingerprint != self.configuration_fingerprint
            or any(enabled for _, enabled in self.authority)
        ):
            raise ValueError("present-state action plan is inconsistent")
        for value in (
            self.source_data_fingerprint,
            self.source_state_fingerprint,
            self.market_state_fingerprint,
            self.configuration_fingerprint,
            *self.evidence_fingerprints,
        ):
            _sha256(value)

    @property
    def plan_fingerprint(self) -> str:
        return fingerprint(self)

    @property
    def trade_required(self) -> bool:
        return any(item.delta for item in self.deltas)


def plan_strategic_allocation(
    *,
    authorization: PaperAuthorization,
    limits: RiskLimits,
    handoff: PaperContinuationHandoff,
    snapshot: PortfolioSnapshot,
    risk_input: RiskInputEvidence,
    handoff_checkpoint: StrategyEquityCheckpoint,
    planning_settlement: PositionSettlementEvidence,
    planning_checkpoint: StrategyEquityCheckpoint,
    root_authorization: PaperAuthorization,
    root_risk_input: RiskInputEvidence,
    root_checkpoint: StrategyEquityCheckpoint,
) -> PresentStateActionPlan:
    """Derive targets and deltas from immutable present-state evidence only."""
    positive_weights = {
        symbol: weight for symbol, weight in STRATEGIC_ALLOCATION_WEIGHTS if weight > 0
    }
    if (
        authorization.candidate_id != _CANDIDATE_ID
        or authorization.strategy_id != _STRATEGY_ID
        or authorization.strategy_version != _STRATEGY_VERSION
        or authorization.parameters_fingerprint != fingerprint(_PARAMETERS)
        or authorization.account_id != limits.account_id
        or authorization.risk_configuration_fingerprint != limits.configuration_fingerprint
        or set(limits.allowed_symbols) != set(positive_weights)
        or handoff.authorization_id != authorization.authorization_id
        or handoff.account_id != authorization.account_id
        or handoff.strategy_equity_checkpoint_id != handoff_checkpoint.checkpoint_id
        or handoff.strategy_equity_checkpoint_fingerprint
        != handoff_checkpoint.checkpoint_fingerprint
        or handoff_checkpoint.authorization_id != authorization.authorization_id
        or handoff_checkpoint.risk_configuration_fingerprint != limits.configuration_fingerprint
        or planning_settlement.settlement_mode != _PLANNING_SETTLEMENT_MODE
        or planning_settlement.baseline_id != handoff.reconciliation_baseline_id
        or planning_settlement.authorization_id != authorization.authorization_id
        or planning_settlement.account_id != authorization.account_id
        or planning_settlement.risk_configuration_fingerprint != limits.configuration_fingerprint
        or planning_settlement.reconciliation_evidence_id != handoff.reconciliation_evidence_id
        or planning_settlement.observed_snapshot_id != snapshot.snapshot_id
        or planning_settlement.observed_snapshot_fingerprint != snapshot.snapshot_fingerprint
        or planning_settlement.attestation_fingerprint
        != risk_input.portfolio_attestation_fingerprint
        or planning_checkpoint.checkpoint_mode != _PLANNING_CHECKPOINT_MODE
        or planning_checkpoint.authorization_id != authorization.authorization_id
        or planning_checkpoint.risk_configuration_fingerprint != limits.configuration_fingerprint
        or planning_checkpoint.settlement_proof_id != planning_settlement.proof_id
        or planning_checkpoint.settlement_proof_fingerprint != planning_settlement.proof_fingerprint
        or planning_checkpoint.risk_input_evidence_id != risk_input.evidence_id
        or planning_checkpoint.prior_checkpoint_fingerprint is None
        or planning_checkpoint.positions != snapshot.positions
        or planning_checkpoint.advance_fingerprint != handoff_checkpoint.advance_fingerprint
        or planning_checkpoint.fill_event_ids != handoff_checkpoint.fill_event_ids
        or planning_checkpoint.allocated_capital != handoff_checkpoint.allocated_capital
        or planning_checkpoint.gross_buy_notional != handoff_checkpoint.gross_buy_notional
        or planning_checkpoint.gross_sell_notional != handoff_checkpoint.gross_sell_notional
        or planning_checkpoint.fill_cost_reserve != handoff_checkpoint.fill_cost_reserve
        or planning_checkpoint.strategy_cash != handoff_checkpoint.strategy_cash
        or planning_checkpoint.peak_equity < handoff_checkpoint.peak_equity
        or planning_checkpoint.marked_at != planning_settlement.settled_at
        or risk_input.authorization_id != authorization.authorization_id
        or risk_input.portfolio_snapshot_id != snapshot.snapshot_id
        or risk_input.risk_configuration_fingerprint != limits.configuration_fingerprint
        or any(
            getattr(root_authorization, name) != getattr(authorization, name)
            for name in (
                "candidate_id",
                "strategy_id",
                "strategy_version",
                "parameters_fingerprint",
                "code_commit",
                "dataset_id",
                "dataset_fingerprint",
                "universe_id",
                "universe_fingerprint",
                "qualification_evidence_fingerprint",
                "account_id",
                "risk_configuration_fingerprint",
            )
        )
        or root_checkpoint.authorization_id != root_authorization.authorization_id
        or root_checkpoint.account_id != root_authorization.account_id
        or root_checkpoint.strategy_id != root_authorization.strategy_id
        or root_checkpoint.strategy_version != root_authorization.strategy_version
        or root_checkpoint.risk_configuration_fingerprint
        != root_authorization.risk_configuration_fingerprint
        or root_checkpoint.checkpoint_mode != _FILL_CHECKPOINT_MODE
        or not root_checkpoint.fill_event_ids
        or not set(root_checkpoint.fill_event_ids).issubset(planning_checkpoint.fill_event_ids)
        or root_checkpoint.risk_input_evidence_id != root_risk_input.evidence_id
        or root_risk_input.authorization_id != root_authorization.authorization_id
        or root_risk_input.account_id != root_authorization.account_id
        or root_risk_input.risk_configuration_fingerprint
        != root_authorization.risk_configuration_fingerprint
    ):
        raise ValueError("strategic-allocation planning authority differs")
    current = {item.symbol: item.quantity for item in snapshot.positions}
    if not set(current).issubset(limits.allowed_symbols):
        raise ValueError("present positions differ from the approved strategy envelope")
    asks = {quote.symbol: quote.ask_price for quote in risk_input.quotes}
    if not set(limits.allowed_symbols).issubset(asks):
        raise ValueError("strategic-allocation planning quotes are incomplete")
    root_session = _xnys_session(root_risk_input)
    current_session = _xnys_session(risk_input)
    session_count = _session_count(root_session, current_session)
    market_state_fingerprint = fingerprint(
        {
            "account_id": authorization.account_id,
            "portfolio_snapshot_id": snapshot.snapshot_id,
            "portfolio_snapshot_fingerprint": snapshot.snapshot_fingerprint,
            "portfolio_attestation_fingerprint": risk_input.portfolio_attestation_fingerprint,
            "risk_input_evidence_id": risk_input.evidence_id,
            "market_clock": risk_input.clock,
            "exchange_session": current_session.isoformat(),
            "quotes": risk_input.quotes,
            "continuation_handoff_fingerprint": handoff.handoff_fingerprint,
            "handoff_strategy_equity_checkpoint_fingerprint": (
                handoff_checkpoint.checkpoint_fingerprint
            ),
            "planning_settlement_fingerprint": planning_settlement.proof_fingerprint,
            "planning_strategy_equity_checkpoint_fingerprint": (
                planning_checkpoint.checkpoint_fingerprint
            ),
        }
    )
    rebalance_due = session_count == 1 or (session_count - 1) % _REBALANCE_EVERY == 0
    desired = (
        {
            symbol: whole_share_target(
                target_weight=positive_weights[symbol],
                allocated_capital=limits.strategy_capital_allocation,
                ask_price=asks[symbol],
            )
            for symbol in limits.allowed_symbols
        }
        if rebalance_due
        else {symbol: current.get(symbol, 0) for symbol in limits.allowed_symbols}
    )
    current_positions = tuple(
        ActionTarget(symbol, current.get(symbol, 0)) for symbol in limits.allowed_symbols
    )
    targets = tuple(ActionTarget(symbol, desired[symbol]) for symbol in limits.allowed_symbols)
    deltas = tuple(
        ActionDelta(
            symbol=symbol,
            current_quantity=current.get(symbol, 0),
            target_quantity=desired[symbol],
            delta=desired[symbol] - current.get(symbol, 0),
        )
        for symbol in limits.allowed_symbols
    )
    planning_configuration_fingerprint = fingerprint(
        {
            "candidate_id": _CANDIDATE_ID,
            "strategy_id": _STRATEGY_ID,
            "strategy_version": _STRATEGY_VERSION,
            "parameters": _PARAMETERS,
            "weights": STRATEGIC_ALLOCATION_WEIGHTS,
            "sizing_model": _SIZING_MODEL,
            "risk_configuration_fingerprint": limits.configuration_fingerprint,
            "allocated_capital": limits.strategy_capital_allocation,
        }
    )
    configuration_fingerprint = authorization.parameters_fingerprint
    source_state_fingerprint = fingerprint(
        {
            "authorization_fingerprint": authorization.authorization_fingerprint,
            "dataset_fingerprint": authorization.dataset_fingerprint,
            "root_authorization_fingerprint": root_authorization.authorization_fingerprint,
            "root_strategy_equity_checkpoint_fingerprint": (root_checkpoint.checkpoint_fingerprint),
            "root_risk_input_evidence_id": root_risk_input.evidence_id,
            "root_exchange_session": root_session.isoformat(),
            "current_exchange_session": current_session.isoformat(),
            "market_state_fingerprint": market_state_fingerprint,
            "session_count": session_count,
            "portfolio_snapshot_fingerprint": snapshot.snapshot_fingerprint,
            "risk_input_evidence_id": risk_input.evidence_id,
            "continuation_handoff_fingerprint": handoff.handoff_fingerprint,
            "handoff_strategy_equity_checkpoint_fingerprint": (
                handoff_checkpoint.checkpoint_fingerprint
            ),
            "planning_settlement_fingerprint": planning_settlement.proof_fingerprint,
            "planning_strategy_equity_checkpoint_fingerprint": (
                planning_checkpoint.checkpoint_fingerprint
            ),
        }
    )
    evidence_fingerprints = tuple(
        sorted(
            {
                authorization.authorization_fingerprint,
                root_authorization.authorization_fingerprint,
                limits.configuration_fingerprint,
                handoff.handoff_fingerprint,
                snapshot.snapshot_fingerprint,
                risk_input.evidence_id,
                handoff_checkpoint.checkpoint_fingerprint,
                planning_settlement.proof_fingerprint,
                planning_checkpoint.checkpoint_fingerprint,
                root_checkpoint.checkpoint_fingerprint,
                root_risk_input.evidence_id,
                market_state_fingerprint,
                planning_configuration_fingerprint,
                source_state_fingerprint,
            }
        )
    )
    plans = {
        mode: ActionPlan(
            mode=mode,
            strategy_id=_STRATEGY_ID,
            strategy_version=_STRATEGY_VERSION,
            source_data_fingerprint=authorization.dataset_fingerprint,
            configuration_fingerprint=configuration_fingerprint,
            targets=targets,
            evidence_fingerprints=evidence_fingerprints,
        )
        for mode in ("replay", "shadow")
    }
    return PresentStateActionPlan(
        authorization_id=authorization.authorization_id,
        candidate_id=_CANDIDATE_ID,
        strategy_id=_STRATEGY_ID,
        strategy_version=_STRATEGY_VERSION,
        account_id=authorization.account_id,
        root_exchange_session=root_session.isoformat(),
        current_exchange_session=current_session.isoformat(),
        session_count=session_count,
        rebalance_every=_REBALANCE_EVERY,
        rebalance_due=rebalance_due,
        source_data_fingerprint=authorization.dataset_fingerprint,
        source_state_fingerprint=source_state_fingerprint,
        market_state_fingerprint=market_state_fingerprint,
        configuration_fingerprint=configuration_fingerprint,
        current_positions=current_positions,
        targets=targets,
        deltas=deltas,
        evidence_fingerprints=evidence_fingerprints,
        replay=plans["replay"],
        shadow=plans["shadow"],
    )


def _xnys_session(evidence: RiskInputEvidence) -> date:
    session = evidence.clock.provider_timestamp.astimezone(_XNYS_TIMEZONE).date()
    boundary = datetime(session.year, session.month, session.day, tzinfo=UTC)
    if (
        not evidence.clock.regular_session_open
        or not evidence.clock.is_market_day
        or expected_sessions(boundary, boundary, "XNYS") != (session,)
    ):
        raise ValueError("market clock does not establish an XNYS session")
    return session


def _session_count(root_session: date, current_session: date) -> int:
    if current_session < root_session:
        raise ValueError("current XNYS session predates the root strategy session")
    sessions = expected_sessions(
        datetime(root_session.year, root_session.month, root_session.day, tzinfo=UTC),
        datetime(current_session.year, current_session.month, current_session.day, tzinfo=UTC),
        "XNYS",
    )
    if not sessions or sessions[0] != root_session or sessions[-1] != current_session:
        raise ValueError("strategy session range is not bounded by XNYS sessions")
    return len(sessions)


def write_action_plans(
    plan: PresentStateActionPlan, *, replay_path: Path, shadow_path: Path
) -> tuple[Path, Path]:
    if replay_path.resolve() == shadow_path.resolve():
        raise ValueError("replay and shadow plan paths must differ")
    for path, action_plan in ((replay_path, plan.replay), (shadow_path, plan.shadow)):
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = canonicalize(action_plan)
        assert isinstance(payload, dict)
        payload.pop("mode")
        contents = (
            canonical_json({"schema_version": "paper-action-plan-v1", **payload}) + "\n"
        ).encode()
        _write_create_only(path, contents)
    return replay_path, shadow_path


def _write_create_only(path: Path, contents: bytes) -> None:
    if path.exists():
        if path.read_bytes() != contents:
            raise FileExistsError(f"action plan already exists with other bytes: {path}")
        return
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != contents:
                raise
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("paper planning fingerprint is invalid")
