"""Synthetic-only immutable specification runner for Program 002.

This module intentionally has no market-data loader or execution entry point.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .domain import OHLCVBar
from .fingerprints import canonical_json, fingerprint
from .multi_hour_sector_etf_engine import (
    Program002CostScenario,
    maximum_drawdown,
    replay_program_002_period,
)
from .multi_hour_sector_etf_features import build_selection_trace
from .multi_hour_sector_etf_plan import PROGRAM_ID, Program002Configuration, load_program_002_plan
from .multi_hour_sector_etf_synthetic import build_synthetic_program_002_fixture
from .program_002_credentials import reject_research_credentials
from .research_attempts import AttemptStateError, ResearchAttemptStore
from .research_executor import DEFAULT_RESEARCH_WORKERS, run_process_stage

RUN_SCHEMA = "multi-hour-sector-etf-research-001-synthetic-run-v1"
REPORT_SCHEMA = "multi-hour-sector-etf-research-001-synthetic-report-v1"
_ZERO_COST = "zero-cost-delay-1"
_NORMAL = "normal-delay-1"
_ROBUSTNESS = ("stress-a-delay-2", "stress-b-delay-3", "normal-delay-2", "normal-delay-3")
_FALSE_AUTHORITY = {
    "strategy_execution": False,
    "controlled_data_read": False,
    "research_qualification": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}


@dataclass(frozen=True)
class Program002Metrics:
    initial_cash: Decimal
    final_cash: Decimal
    benchmark_return: Decimal
    gross_market_profit: Decimal
    adverse_spread_and_regulatory_cost: Decimal
    entry_market_notional: Decimal
    positive_gross_round_trip_profit: Decimal
    active_sessions: int
    completed_round_trips: int
    maximum_drawdown: Decimal
    capacity_breach_count: int
    trace_mismatch_count: int
    accounting_identity_error: Decimal
    benchmark_trace_mismatch_count: int
    benchmark_accounting_identity_error: Decimal
    positive_symbol_profit: Mapping[str, Decimal]
    positive_bucket_profit: Mapping[str, Decimal]
    positive_block_profit: Mapping[str, Decimal]


@dataclass(frozen=True)
class DiscoveryBaseEvidence:
    configuration_id: str
    discovery_gates_passed: bool
    worst_normal_benchmark_excess_return: Decimal
    aggregate_normal_benchmark_excess_return: Decimal
    aggregate_normal_return: Decimal
    maximum_normal_drawdown: Decimal


def select_discovery_base(
    candidates: Sequence[DiscoveryBaseEvidence],
) -> DiscoveryBaseEvidence | None:
    """Frozen discovery-only lexicographic selection; no later metrics are accepted."""
    passing = tuple(item for item in candidates if item.discovery_gates_passed)
    if not passing:
        return None
    return min(
        passing,
        key=lambda item: (
            -item.worst_normal_benchmark_excess_return,
            -item.aggregate_normal_benchmark_excess_return,
            -item.aggregate_normal_return,
            item.maximum_normal_drawdown,
            item.configuration_id,
        ),
    )


def derive_exposed_specifications(
    repository: Path, source_commit: str
) -> tuple[dict[str, object], ...]:
    """Derive the complete 228-spec exposed graph without reading market data."""
    _require_source_commit(source_commit)
    result = tuple(
        specification
        for family_id in ("sector-relative-continuation-v1", "sector-relative-reversal-v1")
        for specification in derive_campaign_specifications(
            repository,
            source_commit,
            family_id,
            next(
                item.configuration_id
                for item in load_program_002_plan(repository).configurations.values()
                if item.family_id == family_id
            ),
        )
    )
    if len(result) != 228:
        raise AssertionError("Program 002 exposed specification ceiling differs")
    return result


def derive_campaign_specifications(
    repository: Path, source_commit: str, family_id: str, base_configuration_id: str | None = None
) -> tuple[dict[str, object], ...]:
    """Return one exact 114-spec family campaign once its base is fixed."""
    plan = load_program_002_plan(repository)
    _require_source_commit(source_commit)
    campaign = _campaign(plan.payload, family_id)
    configurations = tuple(
        item for item in plan.configurations.values() if item.family_id == family_id
    )
    if len(configurations) != 4:
        raise ValueError("unknown Program 002 family")
    if base_configuration_id is None:
        raise ValueError("Program 002 runnable campaign requires an immutable selected base")
    base = plan.configurations.get(base_configuration_id)
    if base is None or base.family_id != family_id:
        raise ValueError("Program 002 base configuration differs")
    chronology = _mapping(plan.payload["chronology"], "chronology")
    blocks = _mappings(chronology["discovery_blocks"], "discovery blocks")
    folds = _mappings(_mapping(chronology["walk_forward"], "walk forward")["folds"], "folds")
    specs: list[dict[str, object]] = []
    for configuration in configurations:
        for block in blocks:
            for scenario in (_NORMAL, _ZERO_COST):
                specs.append(
                    _specification(
                        plan,
                        source_commit,
                        campaign,
                        "discovery",
                        configuration,
                        block,
                        scenario,
                        None,
                    )
                )
    for configuration in (
        base,
        *(plan.configurations[value] for value in base.immediate_neighbors),
    ):
        for fold in folds[:-1]:
            for scenario in (_NORMAL, _ZERO_COST):
                specs.append(
                    _specification(
                        plan,
                        source_commit,
                        campaign,
                        "folds-1-8",
                        configuration,
                        fold,
                        scenario,
                        base.configuration_id,
                    )
                )
        for scenario in (_NORMAL, _ZERO_COST):
            specs.append(
                _specification(
                    plan,
                    source_commit,
                    campaign,
                    "final-fold-9",
                    configuration,
                    folds[-1],
                    scenario,
                    base.configuration_id,
                )
            )
    for fold in folds:
        for scenario in _ROBUSTNESS:
            specs.append(
                _specification(
                    plan,
                    source_commit,
                    campaign,
                    "robustness",
                    base,
                    fold,
                    scenario,
                    base.configuration_id,
                )
            )
    if len(specs) != 114:
        raise AssertionError("Program 002 campaign template ceiling differs")
    return tuple(specs)


def derive_controlled_templates(
    repository: Path, source_commit: str, configuration_id: str
) -> tuple[dict[str, object], ...]:
    """Pre-register four inert future templates; this grants neither read nor execution."""
    plan = load_program_002_plan(repository)
    _require_source_commit(source_commit)
    configuration = plan.configurations.get(configuration_id)
    if configuration is None:
        raise ValueError("unknown Program 002 configuration")
    return tuple(
        {
            "schema_version": RUN_SCHEMA,
            "program_id": PROGRAM_ID,
            "kind": "controlled-template",
            "block_id": block,
            "role": role,
            "configuration": _configuration(configuration),
            "selection_trace_identity": None,
            "source_commit": source_commit,
            "plan_sha256": plan.sha256,
            "plan_fingerprint": plan.plan_fingerprint,
            "authority": dict(_FALSE_AUTHORITY),
        }
        for block in ("controlled-a", "controlled-b")
        for role in ("candidate", "benchmark")
    )


def validate_program_specification_ceiling(
    exposed: Sequence[Mapping[str, object]], controlled: Sequence[Mapping[str, object]]
) -> None:
    """Reject duplicate IDs and any specification/attempt budget expansion."""
    all_specs = (*exposed, *controlled)
    ids = tuple(_run_id(specification) for specification in all_specs)
    if len(exposed) != 228 or len(controlled) != 4 or len(set(ids)) != len(ids):
        raise ValueError("Program 002 specification membership or ceiling differs")
    if len(all_specs) > 232 or len(all_specs) * 3 > 696:
        raise ValueError("Program 002 infrastructure attempt ceiling differs")


def metric_values(metrics: Program002Metrics) -> dict[str, Decimal | None]:
    """Frozen Decimal formulas; undefined ratios are represented by None and fail gates."""
    if metrics.initial_cash <= 0:
        raise ValueError("initial cash must be positive")
    return {
        "period_return": (metrics.final_cash - metrics.initial_cash) / metrics.initial_cash,
        "benchmark_excess_return": (metrics.final_cash - metrics.initial_cash)
        / metrics.initial_cash
        - metrics.benchmark_return,
        "gross_trade_edge_bps": _ratio(
            metrics.gross_market_profit * Decimal("10000"), metrics.entry_market_notional
        ),
        "round_trip_friction_bps": _ratio(
            metrics.adverse_spread_and_regulatory_cost * Decimal("10000"),
            metrics.entry_market_notional,
        ),
        "cost_to_gross_profitable_trade_profit": _ratio(
            metrics.adverse_spread_and_regulatory_cost, metrics.positive_gross_round_trip_profit
        ),
        "positive_profit_symbol_concentration": _concentration(metrics.positive_symbol_profit),
        "positive_profit_exposure_bucket_concentration": _concentration(
            metrics.positive_bucket_profit
        ),
        "positive_profit_block_concentration": _concentration(metrics.positive_block_profit),
    }


def aggregate_net_profit(metrics: Sequence[Program002Metrics]) -> Decimal:
    return sum((item.final_cash - item.initial_cash for item in metrics), Decimal("0"))


def aggregate_return(metrics: Sequence[Program002Metrics]) -> Decimal | None:
    value = Decimal("1")
    for item in metrics:
        if item.initial_cash <= 0:
            return None
        value *= item.final_cash / item.initial_cash
    return value - 1


def discovery_gates(
    metrics: Sequence[Program002Metrics], zero_cost: Sequence[Program002Metrics]
) -> bool:
    if len(metrics) != 3 or len(zero_cost) != 3:
        return False
    values = metric_values(_combine(metrics))
    edge, friction = values["gross_trade_edge_bps"], values["round_trip_friction_bps"]
    benchmark_excess = _benchmark_excess(metrics)
    return bool(
        _aggregate_return_is_positive(metrics)
        and _aggregate_return_is_positive(zero_cost)
        and benchmark_excess is not None
        and benchmark_excess > 0
        and sum(
            item.benchmark_return < (item.final_cash - item.initial_cash) / item.initial_cash
            for item in metrics
        )
        >= 2
        and sum(item.final_cash > item.initial_cash for item in metrics) >= 2
        and all(item.active_sessions >= 60 for item in metrics)
        and sum(item.completed_round_trips for item in metrics) >= 300
        and max(item.maximum_drawdown for item in metrics) <= Decimal("0.10")
        and edge is not None
        and friction is not None
        and edge >= max(Decimal("5"), Decimal("3") * friction)
        and values["cost_to_gross_profitable_trade_profit"] is not None
        and values["cost_to_gross_profitable_trade_profit"] <= Decimal("0.35")
        and values["positive_profit_symbol_concentration"] is not None
        and values["positive_profit_symbol_concentration"] <= Decimal("0.35")
        and values["positive_profit_exposure_bucket_concentration"] is not None
        and values["positive_profit_exposure_bucket_concentration"] <= Decimal("0.40")
        and values["positive_profit_block_concentration"] is not None
        and values["positive_profit_block_concentration"] <= Decimal("0.60")
        and _control_evidence(metrics)
        and _control_evidence(zero_cost)
    )


def fold_gates(
    metrics: Sequence[Program002Metrics], zero_cost: Sequence[Program002Metrics]
) -> bool:
    """Exact folds 1-8 gates; incomplete or undefined evidence fails closed."""
    if len(metrics) != 8 or len(zero_cost) != 8:
        return False
    combined = _combine(metrics)
    values = metric_values(combined)
    benchmark_excess = _aggregate_benchmark_excess(metrics)
    return bool(
        _aggregate_return_is_positive(metrics)
        and _aggregate_return_is_positive(zero_cost)
        and benchmark_excess is not None
        and benchmark_excess > 0
        and sum(_return(item) > 0 for item in metrics) >= 6
        and sum(_return(item) - item.benchmark_return > 0 for item in metrics) >= 5
        and min(_return(item) for item in metrics) >= Decimal("-0.01")
        and _quality_gates(combined, values, include_block_concentration=False)
        and _control_evidence(metrics)
        and _control_evidence(zero_cost)
    )


def final_fold_gates(metric: Program002Metrics, zero_cost: Program002Metrics) -> bool:
    """Exact independent final-exposed-fold gates."""
    benchmark_excess = _aggregate_benchmark_excess((metric,))
    return bool(
        _aggregate_return_is_positive((metric,))
        and _aggregate_return_is_positive((zero_cost,))
        and benchmark_excess is not None
        and benchmark_excess > 0
        and metric.active_sessions >= 15
        and metric.completed_round_trips >= 30
        and metric.maximum_drawdown <= Decimal("0.10")
        and _quality_gates(metric, metric_values(metric), include_block_concentration=False)
        and _control_evidence((metric, zero_cost))
    )


def all_nine_and_neighbor_gates(
    metrics: Sequence[Program002Metrics],
    zero_cost: Sequence[Program002Metrics],
    neighbor_net_profits: Sequence[Decimal | None],
) -> bool:
    """Nine-fold and exact-two-neighbor gates, including undefined retention failure."""
    if len(metrics) != 9 or len(zero_cost) != 9 or len(neighbor_net_profits) != 2:
        return False
    base_profit = aggregate_net_profit(metrics)
    if base_profit <= 0 or any(value is None or value <= 0 for value in neighbor_net_profits):
        return False
    combined = _combine(metrics)
    benchmark_excess = _aggregate_benchmark_excess(metrics)
    retention = (
        sum(
            (value / base_profit for value in neighbor_net_profits if value is not None),
            Decimal("0"),
        )
        / 2
    )
    return bool(
        _aggregate_return_is_positive(metrics)
        and _aggregate_return_is_positive(zero_cost)
        and benchmark_excess is not None
        and benchmark_excess > 0
        and sum(_return(item) > 0 for item in metrics) >= 7
        and sum(_return(item) - item.benchmark_return > 0 for item in metrics) >= 6
        and min(_return(item) for item in metrics) >= Decimal("-0.01")
        and retention >= Decimal("0.50")
        and _quality_gates(combined, metric_values(combined), include_block_concentration=False)
        and _control_evidence(metrics)
        and _control_evidence(zero_cost)
    )


def robustness_gates(
    normal: Sequence[Program002Metrics], variants: Mapping[str, Sequence[Program002Metrics]]
) -> bool:
    """All four frozen robustness variants must independently pass."""
    base = aggregate_net_profit(normal)
    if len(normal) != 9 or base <= 0 or set(variants) != set(_ROBUSTNESS):
        return False
    floors = {
        "stress-a-delay-2": Decimal("0.50"),
        "normal-delay-2": Decimal("0.50"),
        "stress-b-delay-3": Decimal("0.25"),
        "normal-delay-3": Decimal("0.25"),
    }
    return all(
        len(items) == 9
        and aggregate_net_profit(items) > 0
        and sum(_return(item) > 0 for item in items) >= 7
        and aggregate_net_profit(items) / base >= floors[name]
        and _quality_gates(
            _combine(items), metric_values(_combine(items)), include_block_concentration=False
        )
        and _control_evidence(items)
        for name, items in variants.items()
    )


def controlled_block_gates(metric: Program002Metrics) -> bool:
    """Controlled block gate shape; metrics remain synthetic inputs here."""
    return bool(
        _return(metric) > 0
        and _return(metric) - metric.benchmark_return > 0
        and metric.active_sessions >= 15
        and metric.completed_round_trips >= 30
        and metric.maximum_drawdown <= Decimal("0.10")
        and _quality_gates(metric, metric_values(metric), include_block_concentration=False)
    )


def paired_controlled_block_gates(
    candidate: Program002Metrics, benchmark: Program002Metrics
) -> bool:
    """Both paired controlled accounts must retain exact trace and accounting evidence."""
    return bool(
        controlled_block_gates(candidate)
        and benchmark.trace_mismatch_count == 0
        and benchmark.accounting_identity_error == 0
        and candidate.trace_mismatch_count == benchmark.trace_mismatch_count
    )


def campaign_2_permitted(campaign_1_outcome: str) -> bool:
    """Campaign 2 follows only a normal Campaign 1 scientific terminal outcome."""
    return campaign_1_outcome in {
        "completed-empty",
        "completed-one-serious-family-candidate",
    }


def _return(metric: Program002Metrics) -> Decimal:
    if metric.initial_cash <= 0:
        raise ValueError("initial cash must be positive")
    return (metric.final_cash - metric.initial_cash) / metric.initial_cash


def _aggregate_return_is_positive(metrics: Sequence[Program002Metrics]) -> bool:
    value = aggregate_return(metrics)
    return value is not None and value > 0


def _aggregate_benchmark_excess(metrics: Sequence[Program002Metrics]) -> Decimal | None:
    return _benchmark_excess(metrics)


def _control_evidence(metrics: Sequence[Program002Metrics]) -> bool:
    return all(
        item.capacity_breach_count == item.trace_mismatch_count == 0
        and item.accounting_identity_error == 0
        and item.benchmark_trace_mismatch_count == 0
        and item.benchmark_accounting_identity_error == 0
        for item in metrics
    )


def _quality_gates(
    metric: Program002Metrics,
    values: Mapping[str, Decimal | None],
    *,
    include_block_concentration: bool = True,
) -> bool:
    edge = values["gross_trade_edge_bps"]
    friction = values["round_trip_friction_bps"]
    return bool(
        edge is not None
        and friction is not None
        and edge >= max(Decimal("5"), Decimal("3") * friction)
        and values["cost_to_gross_profitable_trade_profit"] is not None
        and values["cost_to_gross_profitable_trade_profit"] <= Decimal("0.35")
        and values["positive_profit_symbol_concentration"] is not None
        and values["positive_profit_symbol_concentration"] <= Decimal("0.35")
        and values["positive_profit_exposure_bucket_concentration"] is not None
        and values["positive_profit_exposure_bucket_concentration"] <= Decimal("0.40")
        and (
            not include_block_concentration
            or (
                values["positive_profit_block_concentration"] is not None
                and values["positive_profit_block_concentration"] <= Decimal("0.60")
            )
        )
        and metric.capacity_breach_count == metric.trace_mismatch_count == 0
        and metric.accounting_identity_error == 0
    )


class SyntheticProgram002Runner:
    """Persist only synthetic specification evidence through the shared lease journal."""

    def __init__(
        self,
        repository: Path,
        runtime_root: Path,
        source_commit: str,
        *,
        workers: int = DEFAULT_RESEARCH_WORKERS,
        crash_after_claim: bool = False,
    ) -> None:
        reject_research_credentials()
        _require_source_commit(source_commit)
        if isinstance(workers, bool) or workers < 1:
            raise ValueError("worker count must be positive")
        self.repository = repository.resolve()
        self.runtime_root = runtime_root.resolve()
        self.source_commit = source_commit
        self.workers = workers
        self.crash_after_claim = crash_after_claim
        plan = load_program_002_plan(self.repository)
        self.store = ResearchAttemptStore(self.runtime_root)
        self.store.expire_stale(datetime.now(UTC))
        self.store.bind(
            {
                "program_id": PROGRAM_ID,
                "plan_sha256": plan.sha256,
                "plan_fingerprint": plan.plan_fingerprint,
                "synthetic_only": True,
                "authority": dict(_FALSE_AUTHORITY),
            }
        )

    def run(self, specifications: Sequence[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
        if len(specifications) > 232 or len(
            {_run_id(specification) for specification in specifications}
        ) != len(specifications):
            raise ValueError("Program 002 synthetic specification ceiling differs")
        for specification in specifications:
            _validate_synthetic_specification(specification, self.source_commit, self.repository)
            self._require_prior_stage(specification)
            self.store.reserve(_run_id(specification), specification)
        pending = tuple(
            spec for spec in specifications if self.store.get(_run_id(spec))["status"] == "pending"
        )
        if pending:
            run_process_stage(
                pending,
                worker_factory=_SyntheticWorkerFactory(
                    self.runtime_root,
                    self.source_commit,
                    self.repository,
                    self.crash_after_claim,
                ),
                workers=self.workers,
            )
        reports = tuple(_read_report(self.store, specification) for specification in specifications)
        for family_id in {
            _text(_mapping(specification.get("configuration"), "configuration"), "family_id")
            for specification in specifications
        }:
            for stage in {str(specification["stage"]) for specification in specifications}:
                if self._stage_complete(family_id, stage):
                    self._persist_stage_evidence(family_id, stage)
            if self._discovery_complete(family_id):
                self._persist_discovery_selection(family_id)
        return reports

    def _discovery_complete(self, family_id: str) -> bool:
        base = next(
            item.configuration_id
            for item in load_program_002_plan(self.repository).configurations.values()
            if item.family_id == family_id
        )
        try:
            return all(
                self.store.get(_run_id(item))["status"] == "completed"
                for item in derive_campaign_specifications(
                    self.repository, self.source_commit, family_id, base
                )
                if item["stage"] == "discovery"
            )
        except KeyError:
            return False

    def _require_prior_stage(self, specification: Mapping[str, object]) -> None:
        stage = _text(specification, "stage")
        if stage == "discovery":
            return
        configuration = _mapping(specification.get("configuration"), "configuration")
        family_id = _text(configuration, "family_id")
        base = _text(specification, "base_configuration_id")
        if self._selected_base(family_id) != base:
            raise AttemptStateError(
                "Program 002 downstream base differs from immutable discovery selection"
            )
        previous = {
            "folds-1-8": "discovery",
            "final-fold-9": "folds-1-8",
            "robustness": "final-fold-9",
        }.get(stage)
        if previous is None:
            raise ValueError("Program 002 synthetic stage differs")
        evidence = self._verified_stage_evidence(family_id, base, previous)
        results = _mapping(evidence.get("configuration_gate_results"), "stage gate results")
        if results.get(base) is not True:
            raise AttemptStateError("Program 002 prior stage canonical gate did not pass")

    def _stage_complete(self, family_id: str, stage: str) -> bool:
        base = self._stage_base(family_id, stage)
        try:
            return all(
                self.store.get(_run_id(item))["status"] == "completed"
                for item in derive_campaign_specifications(
                    self.repository, self.source_commit, family_id, base
                )
                if item["stage"] == stage
            )
        except KeyError:
            return False

    def _persist_stage_evidence(self, family_id: str, stage: str) -> None:
        base = self._stage_base(family_id, stage)
        evidence = _stage_evidence(
            self.store, self.repository, self.source_commit, family_id, stage, base
        )
        specification = _stage_evidence_specification(
            self.repository, self.source_commit, family_id, stage, base
        )
        run_id = _stage_evidence_run_id(specification)
        encoded = (canonical_json(evidence) + "\n").encode()
        try:
            row = self.store.get(run_id)
        except KeyError:
            self.store.reserve(run_id, specification)
            claim = self.store.claim(
                run_id, source_sha=self.source_commit, started_at=datetime.now(UTC)
            )
            self.store.publish(
                claim,
                Path("stage-evidence") / f"{family_id}-{stage}.json",
                encoded,
                report_fingerprint=str(evidence["stage_evidence_fingerprint"]),
                finished_at=datetime.now(UTC),
                exit_status=0,
            )
            return
        path = row.get("canonical_report_path")
        if (
            row["status"] != "completed"
            or not isinstance(path, Path)
            or path.read_bytes() != encoded
        ):
            raise ValueError("Program 002 immutable stage evidence differs")

    def _verified_stage_evidence(
        self, family_id: str, base: str, stage: str
    ) -> Mapping[str, object]:
        evidence_base = self._stage_base(family_id, stage)
        specification = _stage_evidence_specification(
            self.repository, self.source_commit, family_id, stage, evidence_base
        )
        row = self.store.get(_stage_evidence_run_id(specification))
        path = row.get("canonical_report_path")
        if row["status"] != "completed" or not isinstance(path, Path):
            raise AttemptStateError("Program 002 prior stage evidence is missing")
        value = _stage_evidence_from_bytes(path.read_bytes())
        expected = _stage_evidence(
            self.store, self.repository, self.source_commit, family_id, stage, evidence_base
        )
        if canonical_json(value) != canonical_json(expected):
            raise ValueError("Program 002 immutable stage evidence verification differs")
        return value

    def _stage_base(self, family_id: str, stage: str) -> str:
        if stage != "discovery":
            return self._selected_base(family_id)
        return next(
            item.configuration_id
            for item in load_program_002_plan(self.repository).configurations.values()
            if item.family_id == family_id
        )

    def _persist_discovery_selection(self, family_id: str) -> None:
        evidence = _discovery_selection_evidence(
            self.store, self.repository, self.source_commit, family_id
        )
        specification = _selection_specification(self.repository, self.source_commit, family_id)
        run_id = _selection_run_id(specification)
        try:
            row = self.store.get(run_id)
        except KeyError:
            self.store.reserve(run_id, specification)
            claim = self.store.claim(
                run_id, source_sha=self.source_commit, started_at=datetime.now(UTC)
            )
            encoded = (canonical_json(evidence) + "\n").encode()
            self.store.publish(
                claim,
                Path("selection-evidence") / f"{family_id}.json",
                encoded,
                report_fingerprint=str(evidence["selection_fingerprint"]),
                finished_at=datetime.now(UTC),
                exit_status=0,
            )
            return
        if row["status"] != "completed":
            raise AttemptStateError(
                "Program 002 discovery selection has an active or failed evidence run"
            )
        path = row.get("canonical_report_path")
        if (
            not isinstance(path, Path)
            or path.read_bytes() != (canonical_json(evidence) + "\n").encode()
        ):
            raise ValueError("Program 002 immutable discovery selection differs")

    def _selected_base(self, family_id: str) -> str:
        specification = _selection_specification(self.repository, self.source_commit, family_id)
        row = self.store.get(_selection_run_id(specification))
        path = row.get("canonical_report_path")
        if row["status"] != "completed" or not isinstance(path, Path):
            raise AttemptStateError("Program 002 immutable discovery selection is missing")
        value = _selection_evidence_from_bytes(path.read_bytes())
        expected = _discovery_selection_evidence(
            self.store, self.repository, self.source_commit, family_id
        )
        if canonical_json(value) != canonical_json(expected):
            raise ValueError("Program 002 immutable discovery selection verification differs")
        selected = value.get("selected_base_configuration_id")
        if not isinstance(selected, str):
            raise AttemptStateError("Program 002 discovery has no immutable selected base")
        return selected


@dataclass(frozen=True)
class _SyntheticWorkerFactory:
    root: Path
    source_commit: str
    repository: Path
    crash_after_claim: bool

    def __call__(self) -> _SyntheticWorker:
        return _SyntheticWorker(
            self.root, self.source_commit, self.repository, self.crash_after_claim
        )


class _SyntheticWorker:
    def __init__(
        self, root: Path, source_commit: str, repository: Path, crash_after_claim: bool
    ) -> None:
        reject_research_credentials()
        self.store = ResearchAttemptStore(root)
        self.source_commit = source_commit
        self.repository = repository
        self.crash_after_claim = crash_after_claim

    def __call__(self, specification: Mapping[str, object]) -> str:
        _validate_synthetic_specification(specification, self.source_commit, self.repository)
        run_id = _run_id(specification)
        claim = self.store.claim(
            run_id, source_sha=self.source_commit, started_at=datetime.now(UTC)
        )
        if self.crash_after_claim:
            os._exit(23)
        report = _synthetic_report(specification, self.repository)
        encoded = (canonical_json(report) + "\n").encode()
        self.store.publish(
            claim,
            Path("synthetic-reports") / f"{run_id}.json",
            encoded,
            report_fingerprint=str(report["report_fingerprint"]),
            finished_at=datetime.now(UTC),
            exit_status=0,
        )
        return run_id


def _specification(
    plan: Any,
    source_commit: str,
    campaign: Mapping[str, Any],
    stage: str,
    configuration: Program002Configuration,
    period: Mapping[str, Any],
    scenario: str,
    base: str | None,
) -> dict[str, object]:
    return {
        "schema_version": RUN_SCHEMA,
        "program_id": PROGRAM_ID,
        "kind": "exposed-synthetic-template",
        "campaign_id": _text(campaign, "campaign_id"),
        "stage": stage,
        "configuration": _configuration(configuration),
        "base_configuration_id": base,
        "period": dict(period),
        "scenario_id": scenario,
        "source_commit": source_commit,
        "plan_sha256": plan.sha256,
        "plan_fingerprint": plan.plan_fingerprint,
        "authority": dict(_FALSE_AUTHORITY),
    }


def _configuration(value: Program002Configuration) -> dict[str, object]:
    return {
        "configuration_id": value.configuration_id,
        "family_id": value.family_id,
        "strategy_id": value.strategy_id,
        "lookback_30m_bars": value.lookback_30m_bars,
        "hold_30m_bars": value.hold_30m_bars,
        "immediate_neighbors": list(value.immediate_neighbors),
    }


def _campaign(payload: Mapping[str, Any], family_id: str) -> Mapping[str, Any]:
    for key in ("campaign_1", "campaign_2"):
        value = _mapping(_mapping(payload["campaigns_and_budget"], "budget")[key], key)
        if value.get("family_id") == family_id:
            return value
    raise ValueError("unknown Program 002 family")


def _selection_specification(
    repository: Path, source_commit: str, family_id: str
) -> dict[str, object]:
    plan = load_program_002_plan(repository)
    return {
        "schema_version": "multi-hour-sector-etf-research-001-selection-evidence-v1",
        "program_id": PROGRAM_ID,
        "kind": "discovery-selection-evidence",
        "family_id": family_id,
        "source_commit": source_commit,
        "plan_sha256": plan.sha256,
        "plan_fingerprint": plan.plan_fingerprint,
        "authority": dict(_FALSE_AUTHORITY),
    }


def _selection_run_id(specification: Mapping[str, object]) -> str:
    return f"p002sel-{fingerprint(specification)[:24]}"


def _stage_evidence_specification(
    repository: Path, source_commit: str, family_id: str, stage: str, base_configuration_id: str
) -> dict[str, object]:
    plan = load_program_002_plan(repository)
    return {
        "schema_version": "multi-hour-sector-etf-research-001-stage-evidence-v1",
        "program_id": PROGRAM_ID,
        "kind": "synthetic-stage-evidence",
        "family_id": family_id,
        "stage": stage,
        "base_configuration_id": base_configuration_id,
        "source_commit": source_commit,
        "plan_sha256": plan.sha256,
        "plan_fingerprint": plan.plan_fingerprint,
        "authority": dict(_FALSE_AUTHORITY),
    }


def _stage_evidence_run_id(specification: Mapping[str, object]) -> str:
    return f"p002stage-{fingerprint(specification)[:24]}"


def _stage_evidence(
    store: ResearchAttemptStore,
    repository: Path,
    source_commit: str,
    family_id: str,
    stage: str,
    base: str,
) -> dict[str, object]:
    specifications = tuple(
        item
        for item in derive_campaign_specifications(repository, source_commit, family_id, base)
        if item["stage"] == stage
    )
    reports = tuple(_read_report(store, item) for item in specifications)
    by_configuration: dict[str, dict[str, list[Program002Metrics]]] = {}
    fingerprints: dict[str, dict[str, list[str]]] = {}
    for report in reports:
        specification = _mapping(report["specification"], "specification")
        configuration = _text(
            _mapping(specification["configuration"], "configuration"), "configuration_id"
        )
        scenario = _text(specification, "scenario_id")
        by_configuration.setdefault(configuration, {}).setdefault(scenario, []).append(
            _metrics_from_report(report)
        )
        fingerprints.setdefault(configuration, {}).setdefault(scenario, []).append(
            _text(report, "report_fingerprint")
        )
    results: dict[str, bool] = {}
    all_specifications = derive_campaign_specifications(repository, source_commit, family_id, base)
    for configuration, scenarios in by_configuration.items():
        normal = tuple(scenarios.get(_NORMAL, ()))
        zero = tuple(scenarios.get(_ZERO_COST, ()))
        if stage == "discovery":
            results[configuration] = discovery_gates(normal, zero)
        elif stage == "folds-1-8":
            results[configuration] = fold_gates(normal, zero)
        elif stage == "final-fold-9":
            if configuration != base:
                continue
            stage_metrics = _prior_and_current_metrics(
                store, all_specifications, ("folds-1-8", "final-fold-9")
            )
            base_configuration = load_program_002_plan(repository).configurations[base]
            declared = {base, *base_configuration.immediate_neighbors}
            if set(stage_metrics) != declared or not (
                len(normal) == len(zero) == 1 and final_fold_gates(normal[0], zero[0])
            ):
                results[configuration] = False
                continue
            neighbor_profits = tuple(
                aggregate_net_profit(stage_metrics[item].get(_NORMAL, ()))
                for item in base_configuration.immediate_neighbors
            )
            results[configuration] = all_nine_and_neighbor_gates(
                stage_metrics[base].get(_NORMAL, ()),
                stage_metrics[base].get(_ZERO_COST, ()),
                neighbor_profits,
            ) and all(
                (aggregate_return(stage_metrics[item].get(_NORMAL, ())) or Decimal("0")) > 0
                for item in base_configuration.immediate_neighbors
            )
        elif stage == "robustness":
            prior_metrics = _prior_and_current_metrics(
                store, all_specifications, ("folds-1-8", "final-fold-9")
            )
            results[configuration] = robustness_gates(
                prior_metrics[configuration].get(_NORMAL, ()),
                {name: tuple(value) for name, value in scenarios.items()},
            )
        else:
            raise ValueError("Program 002 synthetic stage differs")
    value: dict[str, object] = {
        "schema_version": "multi-hour-sector-etf-research-001-stage-evidence-v1",
        "program_id": PROGRAM_ID,
        "family_id": family_id,
        "stage": stage,
        "base_configuration_id": base,
        "source_commit": source_commit,
        "configuration_gate_results": results,
        "report_fingerprints": fingerprints,
        "gate_passed": bool(results) and all(results.values()),
        "authority": dict(_FALSE_AUTHORITY),
    }
    value["stage_evidence_fingerprint"] = fingerprint(value)
    return value


def _prior_and_current_metrics(
    store: ResearchAttemptStore,
    specifications: Sequence[Mapping[str, object]],
    stages: Sequence[str],
) -> dict[str, dict[str, tuple[Program002Metrics, ...]]]:
    output: dict[str, dict[str, list[Program002Metrics]]] = {}
    for specification in specifications:
        if specification["stage"] not in stages:
            continue
        report = _read_report(store, specification)
        report_specification = _mapping(report["specification"], "specification")
        configuration = _text(
            _mapping(report_specification["configuration"], "configuration"), "configuration_id"
        )
        scenario = _text(report_specification, "scenario_id")
        output.setdefault(configuration, {}).setdefault(scenario, []).append(
            _metrics_from_report(report)
        )
    return {
        configuration: {scenario: tuple(metrics) for scenario, metrics in scenarios.items()}
        for configuration, scenarios in output.items()
    }


def _stage_evidence_from_bytes(raw: bytes) -> Mapping[str, object]:
    import json

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("Program 002 stage evidence is invalid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("Program 002 stage evidence is not an object")
    stored = value.pop("stage_evidence_fingerprint", None)
    if not isinstance(stored, str) or fingerprint(value) != stored:
        raise ValueError("Program 002 stage evidence fingerprint differs")
    value["stage_evidence_fingerprint"] = stored
    return value


def _discovery_selection_evidence(
    store: ResearchAttemptStore, repository: Path, source_commit: str, family_id: str
) -> dict[str, object]:
    base = next(
        item.configuration_id
        for item in load_program_002_plan(repository).configurations.values()
        if item.family_id == family_id
    )
    discovery = tuple(
        item
        for item in derive_campaign_specifications(repository, source_commit, family_id, base)
        if item["stage"] == "discovery"
    )
    reports = tuple(_read_report(store, item) for item in discovery)
    candidates: list[DiscoveryBaseEvidence] = []
    for configuration_id in sorted(
        {
            _text(_mapping(item["configuration"], "configuration"), "configuration_id")
            for item in discovery
        }
    ):
        normal = tuple(
            report
            for report in reports
            if _text(_mapping(report["specification"], "specification"), "scenario_id") == _NORMAL
            and _text(
                _mapping(
                    _mapping(report["specification"], "specification")["configuration"],
                    "configuration",
                ),
                "configuration_id",
            )
            == configuration_id
        )
        zero_cost = tuple(
            report
            for report in reports
            if _text(_mapping(report["specification"], "specification"), "scenario_id")
            == _ZERO_COST
            and _text(
                _mapping(
                    _mapping(report["specification"], "specification")["configuration"],
                    "configuration",
                ),
                "configuration_id",
            )
            == configuration_id
        )
        if len(normal) != 3 or len(zero_cost) != 3:
            raise AttemptStateError("Program 002 discovery evidence is incomplete")
        normal_metrics = tuple(_metrics_from_report(report) for report in normal)
        zero_cost_metrics = tuple(_metrics_from_report(report) for report in zero_cost)
        aggregate_normal_return = aggregate_return(normal_metrics)
        aggregate_normal_excess = _benchmark_excess(normal_metrics)
        if aggregate_normal_return is None or aggregate_normal_excess is None:
            raise AttemptStateError("Program 002 discovery selection has undefined metrics")
        candidates.append(
            DiscoveryBaseEvidence(
                configuration_id,
                discovery_gates(normal_metrics, zero_cost_metrics),
                min(_return(metric) - metric.benchmark_return for metric in normal_metrics),
                aggregate_normal_excess,
                aggregate_normal_return,
                max(metric.maximum_drawdown for metric in normal_metrics),
            )
        )
    selected = select_discovery_base(candidates)
    value: dict[str, object] = {
        "schema_version": "multi-hour-sector-etf-research-001-selection-evidence-v1",
        "program_id": PROGRAM_ID,
        "family_id": family_id,
        "source_commit": source_commit,
        "selection_order": [
            "every discovery gate passed",
            "worst fixed-block Normal benchmark excess return descending",
            "aggregate Normal benchmark excess return descending",
            "aggregate Normal return descending",
            "maximum Normal drawdown ascending",
            "configuration_id ascending",
        ],
        "selector_inputs": candidates,
        "discovery_report_fingerprints": {
            _NORMAL: tuple(
                _text(report, "report_fingerprint")
                for report in reports
                if _text(_mapping(report["specification"], "specification"), "scenario_id")
                == _NORMAL
            ),
            _ZERO_COST: tuple(
                _text(report, "report_fingerprint")
                for report in reports
                if _text(_mapping(report["specification"], "specification"), "scenario_id")
                == _ZERO_COST
            ),
        },
        "selected_base_configuration_id": None if selected is None else selected.configuration_id,
        "authority": dict(_FALSE_AUTHORITY),
    }
    value["selection_fingerprint"] = fingerprint(value)
    return value


def _selection_evidence_from_bytes(raw: bytes) -> Mapping[str, object]:
    import json

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("Program 002 selection evidence is invalid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("Program 002 selection evidence is not an object")
    stored = value.pop("selection_fingerprint", None)
    if not isinstance(stored, str) or fingerprint(value) != stored:
        raise ValueError("Program 002 selection evidence fingerprint differs")
    value["selection_fingerprint"] = stored
    return value


def _synthetic_report(specification: Mapping[str, object], repository: Path) -> dict[str, object]:
    configuration_value = _mapping(specification.get("configuration"), "configuration")
    configuration_id = _text(configuration_value, "configuration_id")
    plan = load_program_002_plan(repository)
    configuration = plan.configurations.get(configuration_id)
    if configuration is None:
        raise ValueError("synthetic Program 002 configuration differs")
    fixture = build_synthetic_program_002_fixture()
    traces = (
        build_selection_trace(fixture.bars, fixture.normal_day, configuration),
        build_selection_trace(fixture.bars, fixture.early_close_day, configuration),
    )
    replay = replay_program_002_period(
        traces, fixture.bars, _synthetic_scenario(specification, fixture.bars), None
    )
    report: dict[str, object] = {
        "schema_version": REPORT_SCHEMA,
        "program_id": PROGRAM_ID,
        "run_id": _run_id(specification),
        "specification": dict(specification),
        "specification_fingerprint": fingerprint(specification),
        "result": "synthetic-fixture-contract-only-no-market-data",
        "market_data_read": False,
        "strategy_execution": False,
        "selection_traces": tuple(_trace_evidence(trace) for trace in traces),
        "candidate_ledger": tuple(session.candidate for session in replay.sessions),
        "benchmark_ledger": tuple(session.benchmark for session in replay.sessions),
        "metrics": {
            "candidate_return": replay.candidate_return,
            "benchmark_return": replay.benchmark_return,
            "benchmark_excess_return": replay.candidate_return - replay.benchmark_return,
            "candidate_maximum_drawdown": max(
                maximum_drawdown(session.candidate) for session in replay.sessions
            ),
            "benchmark_maximum_drawdown": max(
                maximum_drawdown(session.benchmark) for session in replay.sessions
            ),
            "accounting_identity_error": max(
                session.candidate.accounting_identity_error for session in replay.sessions
            ),
        },
        "gate_metrics": _synthetic_gate_metrics(replay, specification),
        "authority": dict(_FALSE_AUTHORITY),
    }
    report["report_fingerprint"] = fingerprint(report)
    return report


def _synthetic_gate_metrics(
    replay: object, specification: Mapping[str, object]
) -> Program002Metrics:
    from .multi_hour_sector_etf_engine import PeriodReplay

    if not isinstance(replay, PeriodReplay):
        raise TypeError("Program 002 synthetic replay differs")
    candidates = tuple(session.candidate for session in replay.sessions)
    benchmarks = tuple(session.benchmark for session in replay.sessions)
    symbols = tuple(
        sorted(
            {
                str(fill.symbol)
                for candidate in candidates
                for fill in candidate.fills
                if fill.side == "buy"
            }
        )
    )
    positive_profit = sum(
        (
            candidate.gross_market_profit
            for candidate in candidates
            if candidate.gross_market_profit > 0
        ),
        Decimal("0"),
    )
    by_symbol = {symbol: positive_profit / len(symbols) for symbol in symbols}
    active = tuple(candidate for candidate in candidates if candidate.fills)
    return Program002Metrics(
        replay.candidate_initial_cash,
        replay.candidate_final_cash,
        replay.benchmark_return,
        sum((candidate.gross_market_profit for candidate in candidates), Decimal("0")),
        sum(
            (candidate.adverse_spread_cost + candidate.regulatory_fees for candidate in candidates),
            Decimal("0"),
        ),
        sum(
            (
                fill.gross_notional
                for candidate in candidates
                for fill in candidate.fills
                if fill.side == "buy"
            ),
            Decimal("0"),
        ),
        positive_profit,
        len(active),
        sum(len(candidate.fills) // 2 for candidate in candidates),
        max(maximum_drawdown(candidate) for candidate in candidates),
        0,
        0,
        max(candidate.accounting_identity_error for candidate in candidates),
        0,
        max(benchmark.accounting_identity_error for benchmark in benchmarks),
        by_symbol,
        {"synthetic": positive_profit},
        {_period_identity(_mapping(specification["period"], "period")): positive_profit},
    )


def _period_identity(period: Mapping[str, Any]) -> str:
    for key in ("block_id", "fold_id"):
        value = period.get(key)
        if isinstance(value, str) and value:
            return value
    raise ValueError("Program 002 synthetic period identity differs")


def _metrics_from_report(report: Mapping[str, object]) -> Program002Metrics:
    value = _mapping(report.get("gate_metrics"), "canonical report gate metrics")
    try:
        return Program002Metrics(
            _decimal(value, "initial_cash"),
            _decimal(value, "final_cash"),
            _decimal(value, "benchmark_return"),
            _decimal(value, "gross_market_profit"),
            _decimal(value, "adverse_spread_and_regulatory_cost"),
            _decimal(value, "entry_market_notional"),
            _decimal(value, "positive_gross_round_trip_profit"),
            _integer(value, "active_sessions"),
            _integer(value, "completed_round_trips"),
            _decimal(value, "maximum_drawdown"),
            _integer(value, "capacity_breach_count"),
            _integer(value, "trace_mismatch_count"),
            _decimal(value, "accounting_identity_error"),
            _integer(value, "benchmark_trace_mismatch_count"),
            _decimal(value, "benchmark_accounting_identity_error"),
            _decimal_mapping(value, "positive_symbol_profit"),
            _decimal_mapping(value, "positive_bucket_profit"),
            _decimal_mapping(value, "positive_block_profit"),
        )
    except (ArithmeticError, TypeError, ValueError) as error:
        raise AttemptStateError("Program 002 canonical gate metrics are undefined") from error


def _decimal(value: Mapping[str, Any], key: str) -> Decimal:
    raw = value.get(key)
    if raw is None:
        raise ValueError(f"missing {key}")
    result = Decimal(str(raw))
    if not result.is_finite():
        raise ValueError(f"invalid {key}")
    return result


def _integer(value: Mapping[str, Any], key: str) -> int:
    raw = value.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ValueError(f"invalid {key}")
    return raw


def _decimal_mapping(value: Mapping[str, Any], key: str) -> dict[str, Decimal]:
    raw = _mapping(value.get(key), key)
    return {str(name): _decimal(raw, str(name)) for name in raw}


def _trace_evidence(trace: object) -> Mapping[str, object]:
    from .multi_hour_sector_etf_features import SelectionTrace

    if not isinstance(trace, SelectionTrace):
        raise TypeError("Program 002 synthetic trace differs")
    return {
        "configuration_id": trace.configuration_id,
        "strategy_id": trace.strategy_id,
        "family_id": trace.family_id,
        "session_day": trace.session_day.isoformat(),
        "decision_timestamp": trace.decision_timestamp,
        "latest_source_bar_open": trace.latest_source_bar_open,
        "lookback_30m_bars": trace.lookback_30m_bars,
        "hold_30m_bars": trace.hold_30m_bars,
        "ordered_features": trace.ordered_features,
        "selected_symbols": trace.selected_symbols,
        "inactive_reason": trace.inactive_reason,
    }


def _synthetic_scenario(
    specification: Mapping[str, object], bars: Sequence[OHLCVBar]
) -> Program002CostScenario:
    scenario_id = _text(specification, "scenario_id")
    if scenario_id in {_ZERO_COST, _NORMAL}:
        delay, spread = 1, Decimal("0")
    elif scenario_id == "stress-a-delay-2":
        delay, spread = 2, Decimal("1")
    elif scenario_id == "stress-b-delay-3":
        delay, spread = 3, Decimal("2")
    elif scenario_id == "normal-delay-2":
        delay, spread = 2, Decimal("0")
    elif scenario_id == "normal-delay-3":
        delay, spread = 3, Decimal("0")
    else:
        raise ValueError("synthetic Program 002 scenario differs")
    symbols = {bar.symbol for bar in bars}
    return Program002CostScenario(scenario_id, {symbol: spread for symbol in symbols}, delay, False)


def _read_report(
    store: ResearchAttemptStore, specification: Mapping[str, object]
) -> dict[str, object]:
    row = store.get(_run_id(specification))
    path = row.get("canonical_report_path")
    if row["status"] != "completed" or not isinstance(path, Path):
        raise AttemptStateError("synthetic Program 002 report is not complete")
    import json

    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or value.get("report_fingerprint") != fingerprint(
        {key: item for key, item in value.items() if key != "report_fingerprint"}
    ):
        raise ValueError("synthetic Program 002 report fingerprint differs")
    return value


def _run_id(specification: Mapping[str, object]) -> str:
    return f"p002r-{fingerprint(specification)[:24]}"


def _validate_synthetic_specification(
    specification: Mapping[str, object], source_commit: str, repository: Path
) -> None:
    if (
        specification.get("schema_version") != RUN_SCHEMA
        or specification.get("program_id") != PROGRAM_ID
        or specification.get("source_commit") != source_commit
    ):
        raise ValueError("Program 002 synthetic specification identity differs")
    if (
        specification.get("authority") != _FALSE_AUTHORITY
        or specification.get("kind") != "exposed-synthetic-template"
    ):
        raise ValueError("Program 002 synthetic runner has no execution authority")
    configuration = _mapping(specification.get("configuration"), "configuration")
    family_id = _text(configuration, "family_id")
    base = specification.get("base_configuration_id")
    if base is not None and not isinstance(base, str):
        raise ValueError("Program 002 synthetic base differs")
    if base is None and specification.get("stage") == "discovery":
        base = next(
            item.configuration_id
            for item in load_program_002_plan(repository).configurations.values()
            if item.family_id == family_id
        )
    canonical = derive_campaign_specifications(repository, source_commit, family_id, base)
    if canonical_json(specification) not in {canonical_json(value) for value in canonical}:
        raise ValueError("Program 002 synthetic specification is not canonical membership")


def _combine(items: Sequence[Program002Metrics]) -> Program002Metrics:
    return Program002Metrics(
        items[0].initial_cash,
        items[0].initial_cash + aggregate_net_profit(items),
        Decimal("0"),
        sum((item.gross_market_profit for item in items), Decimal("0")),
        sum((item.adverse_spread_and_regulatory_cost for item in items), Decimal("0")),
        sum((item.entry_market_notional for item in items), Decimal("0")),
        sum((item.positive_gross_round_trip_profit for item in items), Decimal("0")),
        sum(item.active_sessions for item in items),
        sum(item.completed_round_trips for item in items),
        max(item.maximum_drawdown for item in items),
        sum(item.capacity_breach_count for item in items),
        sum(item.trace_mismatch_count for item in items),
        max(item.accounting_identity_error for item in items),
        sum(item.benchmark_trace_mismatch_count for item in items),
        max(item.benchmark_accounting_identity_error for item in items),
        _merge_profit(items, "positive_symbol_profit"),
        _merge_profit(items, "positive_bucket_profit"),
        _merge_profit(items, "positive_block_profit"),
    )


def _merge_profit(items: Sequence[Program002Metrics], attribute: str) -> dict[str, Decimal]:
    output: dict[str, Decimal] = {}
    for item in items:
        for key, value in getattr(item, attribute).items():
            output[key] = output.get(key, Decimal("0")) + value
    return output


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    return numerator / denominator if denominator > 0 else None


def _concentration(values: Mapping[str, Decimal]) -> Decimal | None:
    positive = tuple(value for value in values.values() if value > 0)
    return max(positive) / sum(positive, Decimal("0")) if positive else None


def _benchmark_excess(metrics: Sequence[Program002Metrics]) -> Decimal | None:
    candidate = aggregate_return(metrics)
    if candidate is None:
        return None
    value = Decimal("1")
    for item in metrics:
        value *= Decimal("1") + item.benchmark_return
    return candidate - (value - 1)


def _require_source_commit(value: str) -> None:
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("Program 002 source commit must be a lowercase SHA-1")


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _mappings(value: object, label: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{label} must be object list")
    return tuple(value)


def _text(value: Mapping[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"missing {key}")
    return result
