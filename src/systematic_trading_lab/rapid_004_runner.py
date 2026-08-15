"""Dedicated, fail-closed execution for the frozen Rapid-004 campaign."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence, Set
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from itertools import product
from pathlib import Path
from typing import Any

from .backtesting import BacktestEngine, BacktestResult, CostModel, PortfolioStrategy
from .config import non_broker_subprocess_environment
from .datasets import DatasetService
from .domain import OHLCVBar, Symbol, TimestampRange
from .fingerprints import canonical_json, canonicalize, fingerprint
from .rapid_004 import (
    RAPID_004_PROGRAM_ID,
    Rapid004Binding,
    load_rapid_004_binding,
    load_rapid_004_predeclaration_payload,
)
from .rapid_research import research_metrics
from .rapid_store import RapidResearchStore, rapid_authority
from .rapid_strategies import StartBoundPortfolioStrategy
from .storage import StorageLayout
from .strategies import StrategicAllocationPortfolioStrategy, TargetPosition

RUNNER_VERSION = "rapid-004-runner-v1"
EXPOSED_REPORT_NAME = "rapid-004-exposed-report-v1.json"
COHORT_FREEZE_NAME = "rapid-004-cohort-freeze-v1.json"


@dataclass(frozen=True)
class Rapid004Configuration:
    family_id: str
    family_name: str
    source_stage: str
    strategy_id: str
    parameter_items: tuple[tuple[str, int], ...]

    @property
    def parameters(self) -> dict[str, int]:
        return dict(self.parameter_items)

    @property
    def identity(self) -> str:
        return fingerprint(
            {
                "family_id": self.family_id,
                "strategy_id": self.strategy_id,
                "parameters": self.parameters,
            }
        )


@dataclass(frozen=True)
class Rapid004Period:
    period_id: str
    start: str
    end: str

    @property
    def timestamp_range(self) -> TimestampRange:
        return TimestampRange(_date(self.start), _date(self.end))


@dataclass(frozen=True)
class Rapid004Plan:
    binding: Rapid004Binding
    payload: Mapping[str, Any]
    configurations: tuple[Rapid004Configuration, ...]
    periods: tuple[Rapid004Period, ...]

    @property
    def full_period(self) -> Rapid004Period:
        return self.periods[0]

    @property
    def block_periods(self) -> tuple[Rapid004Period, ...]:
        return self.periods[1:]

    @property
    def groups(self) -> dict[str, tuple[str, ...]]:
        return dict(self.binding.predeclaration.groups)

    @property
    def sleeves(self) -> dict[str, tuple[str, ...]]:
        return dict(self.binding.predeclaration.sleeves)

    @property
    def profiles(self) -> Mapping[str, Mapping[str, object]]:
        mechanics = _mapping(self.payload["mechanics"], "mechanics")
        values = _mapping(mechanics["strategy_profiles"], "strategy profiles")
        return {name: _mapping(value, f"strategy profile {name}") for name, value in values.items()}

    @property
    def families(self) -> tuple[Mapping[str, object], ...]:
        value = self.payload["families"]
        if not isinstance(value, list):
            raise ValueError("Rapid-004 families differ")
        return tuple(_mapping(item, "family") for item in value)

    def family_configurations(
        self, family_id: str, source_stage: str | None = None
    ) -> tuple[Rapid004Configuration, ...]:
        return tuple(
            item
            for item in self.configurations
            if item.family_id == family_id
            and (source_stage is None or item.source_stage == source_stage)
        )

    def family(self, family_id: str) -> Mapping[str, object]:
        try:
            return next(item for item in self.families if item["id"] == family_id)
        except StopIteration as error:
            raise ValueError(f"unknown Rapid-004 family: {family_id}") from error

    def anchor(self, family_id: str) -> Rapid004Configuration:
        anchor = _mapping(self.family(family_id)["anchor"], "family anchor")
        strategy_id = _text(anchor["strategy_id"], "anchor strategy ID")
        parameters = _integer_mapping(anchor["parameters"], "anchor parameters")
        matches = tuple(
            item
            for item in self.family_configurations(family_id)
            if item.strategy_id == strategy_id and item.parameters == parameters
        )
        if len(matches) != 1:
            raise ValueError(f"Rapid-004 family {family_id} anchor differs from its grids")
        return matches[0]

    def cohort_diversity_group(self, family_id: str) -> str:
        return _text(
            self.family(family_id)["cohort_diversity_group"],
            "cohort diversity group",
        )


def load_rapid_004_plan(repository: Path | None = None) -> Rapid004Plan:
    root = (repository or Path(__file__).resolve().parents[2]).resolve()
    binding = load_rapid_004_binding(root)
    payload = load_rapid_004_predeclaration_payload(root)
    configurations = _configurations(payload)
    counts = binding.predeclaration.family_configuration_counts
    observed = tuple(
        (
            family_id,
            sum(
                item.family_id == family_id and item.source_stage == "discovery"
                for item in configurations
            ),
            sum(
                item.family_id == family_id and item.source_stage == "confirmation"
                for item in configurations
            ),
        )
        for family_id, _discovery, _confirmation in counts
    )
    if observed != counts or len({item.identity for item in configurations}) != len(configurations):
        raise ValueError("Rapid-004 materialized family grids differ from the freeze")

    chronology = _mapping(payload["chronology"], "chronology")
    full = _mapping(chronology["full_range"], "full range")
    blocks = chronology["fixed_blocks"]
    if not isinstance(blocks, list):
        raise ValueError("Rapid-004 fixed blocks differ")
    periods = (
        Rapid004Period("full-range", _text(full["start"], "start"), _text(full["end"], "end")),
        *(
            Rapid004Period(
                _text(_mapping(block, "fixed block")["id"], "block ID"),
                _text(_mapping(block, "fixed block")["start"], "block start"),
                _text(_mapping(block, "fixed block")["end"], "block end"),
            )
            for block in blocks
        ),
    )
    if (
        len(periods) != 4
        or periods[0].start != binding.start
        or periods[0].end != binding.end
        or sum(discovery + confirmation for _family, discovery, confirmation in counts) != 542
    ):
        raise ValueError("Rapid-004 chronology or grid budget differs")

    plan = Rapid004Plan(binding, payload, configurations, periods)
    for family_id, _discovery, _confirmation in counts:
        plan.anchor(family_id)
    _validate_theoretical_budget(plan)
    return plan


def rapid_004_status(repository: Path, data_root: Path) -> dict[str, object]:
    plan = load_rapid_004_plan(repository)
    store = RapidResearchStore(data_root)
    runs = _campaign_runs(store, plan.binding)
    if runs:
        first_specification = _mapping(runs[0]["specification"], "stored specification")
        stored_code = _validated_code_identity(
            _mapping(first_specification["code"], "stored code identity")
        )
        runner = Rapid004CampaignRunner(
            repository,
            data_root,
            _stored_code_identity=stored_code,
        )
        runs = list(runner.runs.values())
    cohort = data_root / COHORT_FREEZE_NAME
    exposed = data_root / EXPOSED_REPORT_NAME
    return {
        "program_id": RAPID_004_PROGRAM_ID,
        "runner_version": RUNNER_VERSION,
        "predeclaration_sha256": plan.binding.predeclaration.sha256,
        "parent_record_count": sum(_is_parent_record(run) for run in runs),
        "run_row_count": len(runs),
        "completed_row_count": sum(run["status"] == "completed" for run in runs),
        "failed_row_count": sum(run["status"] == "failed" for run in runs),
        "exposed_report_path": str(exposed) if exposed.exists() else None,
        "cohort_freeze_path": str(cohort) if cohort.exists() else None,
        "authority": rapid_authority(),
    }


def rapid_004_plan_summary(repository: Path | None = None) -> dict[str, object]:
    plan = load_rapid_004_plan(repository)
    counts = plan.binding.predeclaration.family_configuration_counts
    return {
        "program_id": RAPID_004_PROGRAM_ID,
        "runner_version": RUNNER_VERSION,
        "predeclaration_sha256": plan.binding.predeclaration.sha256,
        "family_counts": [
            {"family_id": family, "discovery": discovery, "confirmation": confirmation}
            for family, discovery, confirmation in counts
        ],
        "discovery_configuration_count": sum(item[1] for item in counts),
        "conditional_confirmation_configuration_count": sum(item[2] for item in counts),
        "maximum_parent_records": plan.binding.predeclaration.maximum_parent_records,
        "parent_configuration_ceiling": 3000,
        "periods": [
            {"period_id": item.period_id, "start": item.start, "end": item.end}
            for item in plan.periods
        ],
        "authority": rapid_authority(),
    }


def _configurations(payload: Mapping[str, Any]) -> tuple[Rapid004Configuration, ...]:
    families = payload.get("families")
    if not isinstance(families, list):
        raise ValueError("Rapid-004 families differ")
    result: list[Rapid004Configuration] = []
    for family_value in families:
        family = _mapping(family_value, "family")
        family_id = _text(family["id"], "family ID")
        family_name = _text(family["name"], "family name")
        for source_stage in ("discovery", "confirmation"):
            stage = _mapping(family[source_stage], f"family {source_stage}")
            strategy_ids = _strings(stage["strategy_ids"], "strategy IDs")
            grid = _mapping(stage.get("parameters", {}), "parameter grid")
            names = tuple(grid)
            values = tuple(_integers(grid[name], f"parameter {name}") for name in names)
            parameter_sets_value = stage.get("parameter_sets", [{}])
            if not isinstance(parameter_sets_value, list) or not parameter_sets_value:
                raise ValueError("Rapid-004 parameter sets differ")
            parameter_sets = tuple(
                _integer_mapping(item, "parameter set") for item in parameter_sets_value
            )
            fixed = _integer_mapping(stage.get("fixed_parameters", {}), "fixed parameters")
            for strategy_id in strategy_ids:
                for parameter_set in parameter_sets:
                    for selection in product(*values):
                        selected = dict(zip(names, selection, strict=True))
                        if set(parameter_set) & set(selected) or (
                            set(fixed) & (set(parameter_set) | set(selected))
                        ):
                            raise ValueError("Rapid-004 parameter declarations overlap")
                        parameters = {**parameter_set, **selected, **fixed}
                        result.append(
                            Rapid004Configuration(
                                family_id,
                                family_name,
                                source_stage,
                                strategy_id,
                                tuple(sorted(parameters.items())),
                            )
                        )
    return tuple(result)


def _validate_theoretical_budget(plan: Rapid004Plan) -> None:
    search = _mapping(plan.payload["search"], "search")
    budget = _mapping(search["parent_budget"], "parent budget")
    expected = {
        "benchmark_full_range_and_fixed_blocks": 5 * len(plan.periods),
        "all_discovery_and_confirmation_full_range": len(plan.configurations),
        "maximum_fixed_block_parents": len(plan.families) * 5 * len(plan.block_periods),
        "maximum_neighbor_fixed_block_parents": len(plan.families)
        * 3
        * 8
        * len(plan.block_periods),
        "maximum_walk_forward_parents": len(plan.families) * 3,
    }
    if any(_integer(budget[name], name) != value for name, value in expected.items()):
        raise ValueError("Rapid-004 theoretical parent budget differs")
    if sum(expected.values()) != plan.binding.predeclaration.maximum_parent_records:
        raise ValueError("Rapid-004 theoretical parent budget total differs")


def _campaign_runs(store: RapidResearchStore, binding: Rapid004Binding) -> list[dict[str, object]]:
    expected = binding.specification()
    result: list[dict[str, object]] = []
    for run in store.list_runs():
        specification = _mapping(run["specification"], "stored run specification")
        context_value = specification.get("exploratory_context")
        campaign = specification.get("campaign")
        claims_context = isinstance(context_value, Mapping) and (
            context_value.get("program_id") == RAPID_004_PROGRAM_ID
        )
        claims_campaign = isinstance(campaign, Mapping) and campaign == expected
        if not claims_context and not claims_campaign:
            continue
        if not claims_context:
            raise ValueError("Rapid-004 stored run context differs")
        if campaign is None:
            raise ValueError("Rapid-004 store contains an unbound research run")
        if _mapping(campaign, "stored campaign") != expected:
            raise ValueError("Rapid-004 stored campaign binding differs")
        result.append(run)
    return result


def _is_parent_record(run: Mapping[str, object]) -> bool:
    specification = _mapping(run["specification"], "run specification")
    context = _mapping(specification.get("exploratory_context"), "run context")
    return context.get("parent_record") is True


def _date(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError as error:
        raise ValueError(f"Rapid-004 date is invalid: {value}") from error


def _timestamp(value: object, label: str) -> datetime:
    text = _text(value, label)
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Rapid-004 {label} is invalid") from error
    if result.utcoffset() != UTC.utcoffset(result):
        raise ValueError(f"Rapid-004 {label} must use UTC")
    return result.astimezone(UTC)


def _run_id(specification: Mapping[str, object]) -> str:
    return f"rr-{fingerprint(specification)[:20]}"


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Rapid-004 {label} must be an object")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Rapid-004 {label} must be text")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Rapid-004 {label} must be a non-negative integer")
    return value


def _integers(value: object, label: str) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"Rapid-004 {label} must be a nonempty integer list")
    result = tuple(_integer(item, label) for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"Rapid-004 {label} must be unique")
    return result


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"Rapid-004 {label} must be a nonempty string list")
    result = tuple(_text(item, label) for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"Rapid-004 {label} must be unique")
    return result


def _integer_mapping(value: object, label: str) -> dict[str, int]:
    mapping = _mapping(value, label)
    if any(not isinstance(name, str) or not name for name in mapping):
        raise ValueError(f"Rapid-004 {label} names differ")
    return {name: _integer(item, f"{label} {name}") for name, item in mapping.items()}


@dataclass
class _FullUniverseFixedWeights:
    symbols: tuple[Symbol, ...]
    weights: Mapping[Symbol, Decimal]
    strategy_id: str
    rebalance_every: int | None
    version: str = "rapid-004-mechanics-v1"

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        expected = set(self.symbols)
        if {bar.symbol for bar in bars} != expected or set(history) != expected:
            raise ValueError("Rapid-004 fixed-weight session universe differs")
        lengths = {len(history[symbol]) for symbol in self.symbols}
        if len(lengths) != 1:
            raise ValueError("Rapid-004 fixed-weight history lengths differ")
        session_count = next(iter(lengths))
        if session_count != 1 and (
            self.rebalance_every is None or (session_count - 1) % self.rebalance_every
        ):
            return ()
        return tuple(
            TargetPosition(
                symbol,
                self.weights.get(symbol, Decimal("0")),
                "rapid-004-fixed-weight",
            )
            for symbol in sorted(self.symbols, key=lambda item: item.value)
        )


@dataclass(frozen=True)
class _FullUniverseStrategicAllocation:
    symbols: tuple[Symbol, ...]
    rebalance_every: int
    strategy_id: str = "strategic-allocation-portfolio"
    version: str = "1"

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        expected = set(self.symbols)
        if {bar.symbol for bar in bars} != expected or set(history) != expected:
            raise ValueError("Rapid-004 strategic-allocation session universe differs")
        historical_symbols = tuple(
            symbol for symbol in self.symbols if symbol.value in {"GLD", "IWM", "QQQ", "SPY", "TLT"}
        )
        inner = StrategicAllocationPortfolioStrategy(
            historical_symbols, rebalance_every=self.rebalance_every
        )
        targets = inner.on_session(
            tuple(bar for bar in bars if bar.symbol in historical_symbols),
            {symbol: history[symbol] for symbol in historical_symbols},
        )
        if not targets:
            return ()
        weights = {target.symbol: target.weight for target in targets}
        return tuple(
            TargetPosition(
                symbol,
                weights.get(symbol, Decimal("0")),
                "strategic-allocation",
            )
            for symbol in self.symbols
        )


class Rapid004CampaignRunner:
    def __init__(
        self,
        repository: Path,
        data_root: Path,
        *,
        progress: Callable[[str], None] | None = None,
        _stored_code_identity: Mapping[str, object] | None = None,
    ) -> None:
        self.repository = repository.resolve()
        self.data_root = data_root.resolve()
        self.plan = load_rapid_004_plan(self.repository)
        self.store = RapidResearchStore(self.data_root)
        self.progress = progress or (lambda _message: None)
        self.code = (
            _code_identity(self.repository)
            if _stored_code_identity is None
            else _validated_code_identity(_stored_code_identity)
        )
        self._configurations_by_identity = {
            item.identity: item for item in self.plan.configurations
        }
        self._neighbor_configurations_by_identity: dict[str, Rapid004Configuration] | None = None
        self.runs = {
            _text(run["run_id"], "run ID"): run
            for run in _campaign_runs(self.store, self.plan.binding)
        }
        self.bars: tuple[OHLCVBar, ...] = ()
        self.period_bars: dict[str, tuple[OHLCVBar, ...]] = {}
        self._validate_stored_runs()

    def run(self) -> dict[str, object]:
        self._load_bars()
        self._run_benchmarks()
        full_rows = self._run_full_range_search()
        selected = self._run_fixed_blocks(full_rows)
        serious = self._select_and_evaluate_serious(selected)
        screened = self._screen_serious(serious)
        cohort = self._freeze_cohort(screened)
        report = self._write_exposed_report(full_rows, selected, serious, screened, cohort)
        return {
            "program_id": RAPID_004_PROGRAM_ID,
            "runner_version": RUNNER_VERSION,
            "parent_record_count": self._parent_count(),
            "run_row_count": len(self.runs),
            "screened_candidate_count": len(screened),
            "passing_candidate_count": sum(item["passed"] is True for item in screened),
            "cohort_size": len(cohort),
            "cohort": cohort,
            "exposed_report": report,
            "authority": rapid_authority(),
        }

    def _validate_stored_runs(self, *, exact_folds: bool = False) -> None:
        maximum = self.plan.binding.predeclaration.maximum_parent_records
        if self._parent_count() > maximum or maximum > 3000:
            raise ValueError("Rapid-004 cumulative parent budget exceeded")
        for run in self.runs.values():
            specification = _mapping(run["specification"], "stored specification")
            expected = self._require_allowed_specification(specification, exact_folds=exact_folds)
            self._validate_stored_record(run, expected)
        for run in self.runs.values():
            self._require_parent_link(_mapping(run["specification"], "stored specification"))
        self._validate_stage_advancement()

    def _require_parent_link(self, specification: Mapping[str, object]) -> None:
        parent_value = specification.get("parent_run_id")
        if parent_value is None:
            return
        parent = self.runs.get(_text(parent_value, "parent run ID"))
        if parent is None:
            raise ValueError("Rapid-004 child run has no stored parent")
        context = _mapping(specification["exploratory_context"], "child context")
        allowed_statuses = (
            {"pending", "completed"}
            if context.get("stage") == "walk-forward-fold"
            else {"completed"}
        )
        if parent.get("status") not in allowed_statuses:
            raise ValueError("Rapid-004 child run parent status differs")

    def _validate_stage_advancement(self, candidate: Mapping[str, object] | None = None) -> None:
        entries = [
            (
                _mapping(run["specification"], "stored specification"),
                _text(run["status"], "stored status"),
            )
            for run in self.runs.values()
        ]
        if candidate is not None and _run_id(candidate) not in self.runs:
            entries.append((candidate, "pending"))

        def stage_rows(name: str) -> list[tuple[Mapping[str, object], str]]:
            return [
                (specification, status)
                for specification, status in entries
                if _mapping(specification["exploratory_context"], "stored context").get("stage")
                == name
            ]

        def context(specification: Mapping[str, object]) -> Mapping[str, object]:
            return _mapping(specification["exploratory_context"], "stored context")

        def require_completed(
            rows: Sequence[tuple[Mapping[str, object], str]],
            expected: Set[object],
            key: Callable[[Mapping[str, object]], object],
            label: str,
        ) -> None:
            observed = {key(specification): status for specification, status in rows}
            if set(observed) != expected or any(
                status != "completed" for status in observed.values()
            ):
                raise ValueError(f"Rapid-004 {label} prerequisites are incomplete")

        benchmark_rows = stage_rows("benchmark")
        candidate_stages = {
            "full-range-discovery",
            "full-range-confirmation",
            "fixed-block",
            "walk-forward",
            "walk-forward-fold",
            "parameter-neighbor",
            "isolated-sensitivity",
            "combined-stress",
        }
        if any(stage_rows(stage) for stage in candidate_stages):
            require_completed(
                benchmark_rows,
                {
                    (benchmark_id, period.period_id)
                    for benchmark_id in self._benchmark_ids()
                    for period in self.plan.periods
                },
                lambda specification: (
                    context(specification).get("benchmark_id"),
                    context(specification).get("period_id"),
                ),
                "benchmark",
            )

        discovery_rows = stage_rows("full-range-discovery")
        confirmation_rows = stage_rows("full-range-confirmation")
        post_discovery_stages = candidate_stages - {"full-range-discovery"}
        expected_discovery = {
            item.identity for item in self.plan.configurations if item.source_stage == "discovery"
        }
        if confirmation_rows or any(stage_rows(stage) for stage in post_discovery_stages):
            require_completed(
                discovery_rows,
                expected_discovery,
                lambda specification: context(specification).get("configuration_id"),
                "discovery",
            )
            early_gates = _mapping(
                _mapping(self.plan.payload["search"], "search")["full_range_early_gate"],
                "early gate",
            )["gates"]
            if not isinstance(early_gates, list):
                raise ValueError("Rapid-004 early gates differ")
            discovery_by_identity = {
                _text(context(specification)["configuration_id"], "configuration ID"): self.runs[
                    _run_id(specification)
                ]
                for specification, _status in discovery_rows
            }
            activated = {
                family_id
                for family_id, _discovery, _confirmation in (
                    self.plan.binding.predeclaration.family_configuration_counts
                )
                if any(
                    _passes_gates(
                        _metrics(discovery_by_identity[configuration.identity]),
                        early_gates,
                    )
                    for configuration in self.plan.family_configurations(family_id, "discovery")
                )
            }
            allowed_confirmation = {
                item.identity
                for item in self.plan.configurations
                if item.source_stage == "confirmation" and item.family_id in activated
            }
            if any(
                context(specification).get("configuration_id") not in allowed_confirmation
                for specification, _status in confirmation_rows
            ):
                raise ValueError("Rapid-004 confirmation was not activated")
        else:
            allowed_confirmation = set()

        post_confirmation_stages = post_discovery_stages - {"full-range-confirmation"}
        if any(stage_rows(stage) for stage in post_confirmation_stages):
            require_completed(
                confirmation_rows,
                allowed_confirmation,
                lambda specification: context(specification).get("configuration_id"),
                "confirmation",
            )
            full_by_identity = {
                _text(context(specification)["configuration_id"], "configuration ID"): self.runs[
                    _run_id(specification)
                ]
                for specification, _status in (*discovery_rows, *confirmation_rows)
            }
            full_rows = {
                family_id: [
                    (configuration, full_by_identity[configuration.identity])
                    for configuration in self.plan.family_configurations(family_id)
                    if configuration.identity in full_by_identity
                ]
                for family_id, _discovery, _confirmation in (
                    self.plan.binding.predeclaration.family_configuration_counts
                )
            }
            selected = self._select_fixed_block_configurations(full_rows)
            allowed_fixed = {
                (configuration.identity, period.period_id)
                for configurations in selected.values()
                for configuration in configurations
                for period in self.plan.block_periods
            }
            fixed_rows = stage_rows("fixed-block")
            if any(
                (
                    context(specification).get("configuration_id"),
                    context(specification).get("period_id"),
                )
                not in allowed_fixed
                for specification, _status in fixed_rows
            ):
                raise ValueError("Rapid-004 fixed-block identity was not selected")
        else:
            selected = {}
            allowed_fixed = set()
            fixed_rows = stage_rows("fixed-block")

        robustness_stages = {
            "walk-forward",
            "walk-forward-fold",
            "parameter-neighbor",
            "isolated-sensitivity",
            "combined-stress",
        }
        if any(stage_rows(stage) for stage in robustness_stages):
            require_completed(
                fixed_rows,
                allowed_fixed,
                lambda specification: (
                    context(specification).get("configuration_id"),
                    context(specification).get("period_id"),
                ),
                "fixed-block",
            )
            serious = self._select_serious_configurations(selected)
            serious_configurations = tuple(
                configuration
                for configurations in serious.values()
                for configuration in configurations
            )
            serious_ids = {configuration.identity for configuration in serious_configurations}
            neighbor_configurations = {
                neighbor.identity: neighbor
                for configuration in serious_configurations
                for neighbor in self._neighbors(configuration)
            }
            for stage in ("walk-forward", "walk-forward-fold"):
                if any(
                    context(specification).get("configuration_id") not in serious_ids
                    for specification, _status in stage_rows(stage)
                ):
                    raise ValueError("Rapid-004 walk-forward identity was not serious")
            neighbor_rows = stage_rows("parameter-neighbor")
            if any(
                context(specification).get("configuration_id") not in neighbor_configurations
                for specification, _status in neighbor_rows
            ):
                raise ValueError("Rapid-004 parameter neighbor was not incident")
        else:
            serious_configurations = ()
            serious_ids = set()
            neighbor_configurations = {}
            neighbor_rows = stage_rows("parameter-neighbor")

        isolated_rows = stage_rows("isolated-sensitivity")
        stress_rows = stage_rows("combined-stress")
        if isolated_rows or stress_rows:
            require_completed(
                stage_rows("walk-forward"),
                set(serious_ids),
                lambda specification: context(specification).get("configuration_id"),
                "walk-forward parent",
            )
            required_folds = _integer(
                _mapping(self.plan.payload["walk_forward_screen"], "walk-forward screen")[
                    "required_fold_count"
                ],
                "required fold count",
            )
            require_completed(
                stage_rows("walk-forward-fold"),
                {
                    (configuration.identity, f"walk-forward-{ordinal}")
                    for configuration in serious_configurations
                    for ordinal in range(1, required_folds + 1)
                },
                lambda specification: (
                    context(specification).get("configuration_id"),
                    context(specification).get("period_id"),
                ),
                "walk-forward fold",
            )
            require_completed(
                neighbor_rows,
                {
                    (neighbor.identity, period.period_id)
                    for neighbor in neighbor_configurations.values()
                    for period in self.plan.block_periods
                },
                lambda specification: (
                    context(specification).get("configuration_id"),
                    context(specification).get("period_id"),
                ),
                "parameter-neighbor",
            )
            if any(
                context(specification).get("configuration_id") not in serious_ids
                for specification, _status in isolated_rows
            ):
                raise ValueError("Rapid-004 isolated identity was not serious")

        if stress_rows:
            require_completed(
                isolated_rows,
                {
                    (configuration.identity, period.period_id, scenario_id)
                    for configuration in serious_configurations
                    for period in self.plan.block_periods
                    for scenario_id in ("isolated-cost-2x", "isolated-delay-2")
                },
                lambda specification: (
                    context(specification).get("configuration_id"),
                    context(specification).get("period_id"),
                    context(specification).get("scenario_id"),
                ),
                "isolated-sensitivity",
            )
            if any(
                context(specification).get("configuration_id") not in serious_ids
                for specification, _status in stress_rows
            ):
                raise ValueError("Rapid-004 stress identity was not serious")

    def _require_allowed_specification(
        self, specification: Mapping[str, object], *, exact_folds: bool
    ) -> dict[str, object]:
        expected = canonicalize(
            self._expected_stored_specification(specification, exact_folds=exact_folds)
        )
        if not isinstance(expected, dict) or canonicalize(specification) != expected:
            raise ValueError("Rapid-004 stored run specification differs")
        return expected

    def _configuration_for_context(
        self, context: Mapping[str, object], *, allow_neighbor: bool
    ) -> Rapid004Configuration:
        identity = _text(context.get("configuration_id"), "configuration ID")
        if allow_neighbor:
            if self._neighbor_configurations_by_identity is None:
                neighbors: dict[str, Rapid004Configuration] = {}
                for base in self.plan.configurations:
                    for neighbor in self._neighbors(base):
                        previous = neighbors.setdefault(neighbor.identity, neighbor)
                        if previous != neighbor:
                            raise ValueError("Rapid-004 neighbor identity is ambiguous")
                self._neighbor_configurations_by_identity = neighbors
            configuration = self._neighbor_configurations_by_identity.get(identity)
        else:
            configuration = self._configurations_by_identity.get(identity)
        if configuration is None:
            raise ValueError("Rapid-004 stored configuration is not frozen")
        if (
            context.get("family_id") != configuration.family_id
            or context.get("source_stage") != configuration.source_stage
        ):
            raise ValueError("Rapid-004 stored configuration context differs")
        return configuration

    def _period(self, period_id: object, *, blocks_only: bool = False) -> Rapid004Period:
        identifier = _text(period_id, "period ID")
        periods = self.plan.block_periods if blocks_only else self.plan.periods
        try:
            return next(period for period in periods if period.period_id == identifier)
        except StopIteration as error:
            raise ValueError("Rapid-004 stored period is not frozen") from error

    def _expected_stored_specification(
        self,
        specification: Mapping[str, object],
        *,
        exact_folds: bool,
    ) -> dict[str, object]:
        context = _mapping(specification.get("exploratory_context"), "stored context")
        stage = _text(context.get("stage"), "stored stage")
        scenario_id = _text(context.get("scenario_id"), "stored scenario")

        if stage == "benchmark":
            if scenario_id != "normal" or context.get("parent_record") is not True:
                raise ValueError("Rapid-004 stored benchmark context differs")
            benchmark_id = _text(context.get("benchmark_id"), "benchmark ID")
            definitions = _mapping(self.plan.payload["benchmarks"], "benchmarks")["definitions"]
            if not isinstance(definitions, list):
                raise ValueError("Rapid-004 benchmarks differ")
            try:
                definition = next(
                    _mapping(item, "benchmark")
                    for item in definitions
                    if _mapping(item, "benchmark").get("id") == benchmark_id
                )
            except StopIteration as error:
                raise ValueError("Rapid-004 stored benchmark is not frozen") from error
            period = self._period(context.get("period_id"))
            return self._specification(
                run_type="rapid-004-benchmark",
                strategy_id=_text(definition["strategy_id"], "benchmark strategy ID"),
                family_id=None,
                parameters=_integer_mapping(
                    definition.get("parameters", {}), "benchmark parameters"
                ),
                period=period,
                scenario_id="normal",
                strategy_version=(
                    "1"
                    if benchmark_id == "strategic-allocation-21-historical-reference"
                    else "rapid-004-mechanics-v1"
                ),
                context={
                    "parent_record": True,
                    "stage": "benchmark",
                    "benchmark_id": benchmark_id,
                    "period_id": period.period_id,
                },
            )

        allow_neighbor = stage == "parameter-neighbor"
        configuration = self._configuration_for_context(context, allow_neighbor=allow_neighbor)
        common_context = {
            "family_id": configuration.family_id,
            "source_stage": configuration.source_stage,
            "configuration_id": configuration.identity,
        }
        parent_run_id: str | None = None
        fold: Mapping[str, object] | None = None

        if stage in {"full-range-discovery", "full-range-confirmation"}:
            required_source = stage.removeprefix("full-range-")
            if (
                configuration.source_stage != required_source
                or scenario_id != "normal"
                or context.get("parent_record") is not True
                or context.get("period_id") != "full-range"
            ):
                raise ValueError("Rapid-004 stored full-range context differs")
            period = self.plan.full_period
        elif stage == "fixed-block":
            if scenario_id != "normal" or context.get("parent_record") is not True:
                raise ValueError("Rapid-004 stored fixed-block context differs")
            period = self._period(context.get("period_id"), blocks_only=True)
        elif stage == "parameter-neighbor":
            if scenario_id != "normal" or context.get("parent_record") is not True:
                raise ValueError("Rapid-004 stored neighbor context differs")
            period = self._period(context.get("period_id"), blocks_only=True)
        elif stage == "walk-forward":
            if (
                scenario_id != "normal"
                or context.get("parent_record") is not True
                or context.get("period_id") != "full-range"
            ):
                raise ValueError("Rapid-004 stored walk-forward context differs")
            period = self.plan.full_period
        elif stage == "walk-forward-fold":
            if scenario_id != "normal" or context.get("parent_record") is not False:
                raise ValueError("Rapid-004 stored walk-forward fold context differs")
            period, fold = self._stored_walk_forward_fold(specification, context, exact=exact_folds)
            parent_specification = self._specification(
                run_type="rapid-004-walk-forward",
                strategy_id=configuration.strategy_id,
                family_id=configuration.family_id,
                parameters=configuration.parameters,
                period=self.plan.full_period,
                scenario_id="normal",
                context={
                    "parent_record": True,
                    "stage": "walk-forward",
                    **common_context,
                    "period_id": "full-range",
                },
            )
            parent_run_id = _run_id(parent_specification)
        elif stage == "isolated-sensitivity":
            if (
                scenario_id not in {"isolated-cost-2x", "isolated-delay-2"}
                or context.get("parent_record") is not False
            ):
                raise ValueError("Rapid-004 stored isolated-sensitivity context differs")
            period = self._period(context.get("period_id"), blocks_only=True)
            parent_specification = self._specification(
                run_type="rapid-004-fixed-block",
                strategy_id=configuration.strategy_id,
                family_id=configuration.family_id,
                parameters=configuration.parameters,
                period=period,
                scenario_id="normal",
                context={
                    "parent_record": True,
                    "stage": "fixed-block",
                    **common_context,
                    "period_id": period.period_id,
                },
            )
            parent_run_id = _run_id(parent_specification)
        elif stage == "combined-stress":
            if (
                scenario_id not in {"stress-a", "stress-b"}
                or context.get("parent_record") is not False
                or context.get("period_id") != "full-range"
            ):
                raise ValueError("Rapid-004 stored combined-stress context differs")
            period = self.plan.full_period
            parent_stage = f"full-range-{configuration.source_stage}"
            parent_specification = self._specification(
                run_type=f"rapid-004-{parent_stage}",
                strategy_id=configuration.strategy_id,
                family_id=configuration.family_id,
                parameters=configuration.parameters,
                period=period,
                scenario_id="normal",
                context={
                    "parent_record": True,
                    "stage": parent_stage,
                    **common_context,
                    "period_id": "full-range",
                },
            )
            parent_run_id = _run_id(parent_specification)
        else:
            raise ValueError("Rapid-004 stored stage is not frozen")

        expected_parent = stage not in {
            "walk-forward-fold",
            "isolated-sensitivity",
            "combined-stress",
        }
        return self._specification(
            run_type=f"rapid-004-{stage}",
            strategy_id=configuration.strategy_id,
            family_id=configuration.family_id,
            parameters=configuration.parameters,
            period=period,
            scenario_id=scenario_id,
            context={
                "parent_record": expected_parent,
                "stage": stage,
                **common_context,
                "period_id": period.period_id,
            },
            parent_run_id=parent_run_id,
            fold=fold,
        )

    def _stored_walk_forward_fold(
        self,
        specification: Mapping[str, object],
        context: Mapping[str, object],
        *,
        exact: bool,
    ) -> tuple[Rapid004Period, Mapping[str, object]]:
        stored = _mapping(specification.get("fold"), "stored fold")
        required_keys = {
            "ordinal",
            "training_start",
            "training_end",
            "test_start",
            "test_end",
            "training_sessions",
            "test_sessions",
        }
        if set(stored) != required_keys:
            raise ValueError("Rapid-004 stored fold fields differ")
        ordinal = _integer(stored["ordinal"], "fold ordinal")
        required = _integer(
            _mapping(self.plan.payload["walk_forward_screen"], "walk-forward screen")[
                "required_fold_count"
            ],
            "required fold count",
        )
        chronology = _mapping(self.plan.payload["chronology"], "chronology")
        walk = _mapping(chronology["walk_forward"], "walk-forward")
        if (
            not 1 <= ordinal <= required
            or context.get("period_id") != f"walk-forward-{ordinal}"
            or stored["training_sessions"] != walk["training_sessions"]
            or stored["test_sessions"] != walk["test_sessions"]
        ):
            raise ValueError("Rapid-004 stored fold identity differs")
        if exact:
            windows = self._walk_forward_windows()
            if len(windows) != required:
                raise ValueError("Rapid-004 walk-forward fold count differs")
            period, expected = windows[ordinal - 1]
            if stored != expected:
                raise ValueError("Rapid-004 stored fold chronology differs")
            return period, expected
        timestamps = tuple(
            _timestamp(stored[name], f"fold {name}")
            for name in ("training_start", "training_end", "test_start", "test_end")
        )
        if not (
            self.plan.full_period.timestamp_range.start
            <= timestamps[0]
            <= timestamps[1]
            < timestamps[2]
            <= timestamps[3]
            <= self.plan.full_period.timestamp_range.end
        ):
            raise ValueError("Rapid-004 stored fold is outside the exposed range")
        period = Rapid004Period(
            f"walk-forward-{ordinal}",
            timestamps[0].date().isoformat(),
            timestamps[3].date().isoformat(),
        )
        return period, stored

    def _validate_stored_record(
        self, run: Mapping[str, object], specification: Mapping[str, object]
    ) -> None:
        run_id = _run_id(specification)
        dataset = _mapping(specification["dataset"], "stored dataset")
        strategy = _mapping(specification["strategy"], "stored strategy")
        costs = _mapping(specification["costs"], "stored costs")
        execution = _mapping(specification["execution"], "stored execution")
        code = _mapping(specification["code"], "stored code identity")
        expected = {
            "run_id": run_id,
            "configuration_fingerprint": fingerprint(specification),
            "run_type": specification["run_type"],
            "group_id": specification.get("group_id"),
            "parent_run_id": specification.get("parent_run_id"),
            "dataset_id": dataset["id"],
            "dataset_fingerprint": dataset["fingerprint"],
            "strategy_name": strategy["name"],
            "strategy_id": strategy["id"],
            "strategy_version": strategy["version"],
            "parameters": strategy["parameters"],
            "timeframe": dataset["timeframe"],
            "start_timestamp": specification["start_timestamp"],
            "end_timestamp": specification["end_timestamp"],
            "cost_model_version": costs["version"],
            "slippage_bps": costs["slippage_bps"],
            "commission_bps": costs["commission_bps"],
            "fill_delay_bars": execution["fill_delay_bars"],
            "code_commit": code.get("commit"),
            "code_dirty": code.get("dirty"),
        }
        if any(run.get(name) != value for name, value in expected.items()):
            raise ValueError("Rapid-004 stored row differs from its specification")
        status = _text(run.get("status"), "stored status")
        _timestamp(run.get("created_at"), "stored creation time")
        path = self.store.reports / f"{run_id}.json"
        if status == "pending":
            if any(
                run.get(name) is not None
                for name in ("metrics", "report_path", "error", "completed_at")
            ):
                raise ValueError("Rapid-004 pending row contains completed evidence")
            if path.exists():
                self._validate_stored_report(path, run, specification, pending=True)
            return
        if status not in {"completed", "failed"}:
            raise ValueError("Rapid-004 stored status differs")
        if run.get("report_path") != str(path) or not path.is_file():
            raise ValueError("Rapid-004 stored report path differs")
        _timestamp(run.get("completed_at"), "stored completion time")
        if status == "completed":
            _mapping(run.get("metrics"), "stored metrics")
            if run.get("error") is not None:
                raise ValueError("Rapid-004 completed row contains an error")
        elif run.get("metrics") is not None or not isinstance(run.get("error"), str):
            raise ValueError("Rapid-004 failed row evidence differs")
        self._validate_stored_report(path, run, specification, pending=False)

    def _validate_stored_report(
        self,
        path: Path,
        run: Mapping[str, object],
        specification: Mapping[str, object],
        *,
        pending: bool,
    ) -> None:
        try:
            contents = path.read_bytes()
            report_value = json.loads(contents)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Rapid-004 stored report bytes are invalid") from error
        report = _mapping(report_value, "stored report")
        required = {
            "schema_version",
            "evidence_class",
            "run_id",
            "status",
            "created_at",
            "completed_at",
            "specification",
            "metrics",
            "details",
            "error",
            "authority",
            "report_fingerprint",
        }
        if set(report) != required or contents != (canonical_json(report) + "\n").encode():
            raise ValueError("Rapid-004 stored report bytes differ")
        unsigned = dict(report)
        report_fingerprint = unsigned.pop("report_fingerprint")
        if (
            report_fingerprint != fingerprint(unsigned)
            or report.get("schema_version") != "rapid-research-report-v1"
            or report.get("evidence_class") != "exploratory-uncontrolled"
            or report.get("run_id") != run.get("run_id")
            or report.get("created_at") != run.get("created_at")
            or report.get("specification") != specification
            or report.get("authority") != rapid_authority()
        ):
            raise ValueError("Rapid-004 stored report identity differs")
        _mapping(report.get("details"), "stored report details")
        if pending:
            if report.get("status") not in {"completed", "failed"}:
                raise ValueError("Rapid-004 pending report status differs")
            return
        if any(
            report.get(name) != run.get(name)
            for name in ("status", "completed_at", "metrics", "error")
        ):
            raise ValueError("Rapid-004 stored report differs from its row")

    def _load_bars(self) -> None:
        binding = self.plan.binding
        service = DatasetService(StorageLayout(self.data_root))
        manifest = service.describe(binding.dataset_id)
        binding.require_manifest(manifest)
        validation = service.validate(binding.dataset_id)
        if validation.get("valid") is not True:
            raise ValueError("Rapid-004 frozen dataset failed full validation")
        bars = service.load_bars_range(
            binding.dataset_id,
            self.plan.full_period.timestamp_range,
            expected_fingerprint=binding.dataset_fingerprint,
            expected_universe_id=binding.universe_id,
            expected_universe_fingerprint=binding.universe_fingerprint,
            verify_full_dataset=True,
        )
        if {bar.symbol.value for bar in bars} != set(binding.symbols):
            raise ValueError("Rapid-004 loaded symbol set differs")
        self.bars = bars
        self.period_bars = {
            period.period_id: tuple(
                bar
                for bar in bars
                if period.timestamp_range.start <= bar.timestamp <= period.timestamp_range.end
            )
            for period in self.plan.periods
        }
        for period in self.plan.periods:
            selected = self.period_bars[period.period_id]
            if not selected or {bar.symbol.value for bar in selected} != set(binding.symbols):
                raise ValueError(f"Rapid-004 {period.period_id} bars differ")
        self._validate_stored_runs(exact_folds=True)
        self.progress(f"validated frozen dataset {binding.dataset_id}: {len(self.bars)} bars")

    def _parent_count(self) -> int:
        return sum(_is_parent_record(run) for run in self.runs.values())

    def _scenario(self, name: str) -> Mapping[str, object]:
        execution = _mapping(self.plan.payload["execution"], "execution")
        key = {
            "normal": "normal",
            "isolated-cost-2x": "isolated_cost_2x",
            "isolated-delay-2": "isolated_delay_2",
            "stress-a": "stress_a",
            "stress-b": "stress_b",
        }.get(name)
        if key is None:
            raise ValueError(f"unknown Rapid-004 scenario: {name}")
        scenario = dict(_mapping(execution[key], f"scenario {name}"))
        if name == "normal":
            scenario["id"] = "normal"
        elif scenario.get("id") != name:
            raise ValueError("Rapid-004 scenario identity differs")
        return scenario

    def _specification(
        self,
        *,
        run_type: str,
        strategy_id: str,
        family_id: str | None,
        parameters: Mapping[str, int],
        period: Rapid004Period,
        scenario_id: str,
        context: Mapping[str, object],
        strategy_version: str = "rapid-004-mechanics-v1",
        parent_run_id: str | None = None,
        fold: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        scenario = self._scenario(scenario_id)
        execution_plan = _mapping(self.plan.payload["execution"], "execution")
        specification: dict[str, object] = {
            "schema_version": "rapid-research-run-v1",
            "run_type": run_type,
            "dataset": {
                "id": self.plan.binding.dataset_id,
                "fingerprint": self.plan.binding.dataset_fingerprint,
                "source": "cataloged-frozen-rapid-004",
                "timeframe": "1d",
                "symbols": self.plan.binding.symbols,
            },
            "strategy": {
                "name": strategy_id,
                "id": strategy_id,
                "version": strategy_version,
                "family": family_id or "benchmark",
                "parameters": dict(parameters),
            },
            "start_timestamp": f"{period.start}T00:00:00Z",
            "end_timestamp": f"{period.end}T00:00:00Z",
            "initial_cash": Decimal(str(execution_plan["initial_cash"])),
            "costs": {
                "version": _text(execution_plan["cost_model_version"], "cost model version"),
                "slippage_bps": Decimal(str(scenario["slippage_bps"])),
                "commission_bps": Decimal(str(scenario["commission_bps"])),
            },
            "execution": {
                "model": _text(
                    execution_plan["execution_model_version"], "execution model version"
                ),
                "fill_delay_bars": _integer(scenario["fill_delay_bars"], "fill delay"),
            },
            "code": self.code,
            "campaign": self.plan.binding.specification(),
            "exploratory_context": {
                "program_id": RAPID_004_PROGRAM_ID,
                "runner_version": RUNNER_VERSION,
                "scenario_id": scenario_id,
                **context,
            },
        }
        if parent_run_id is not None:
            specification["parent_run_id"] = parent_run_id
        if fold is not None:
            specification["fold"] = dict(fold)
        return specification

    def _begin(self, specification: Mapping[str, object]) -> dict[str, object]:
        expected = self._require_allowed_specification(specification, exact_folds=bool(self.bars))
        self._require_parent_link(expected)
        self._validate_stage_advancement(expected)
        run_id = _run_id(expected)
        known = self.runs.get(run_id)
        context = _mapping(expected["exploratory_context"], "run context")
        if known is None and context.get("parent_record") is True:
            next_count = self._parent_count() + 1
            if next_count > self.plan.binding.predeclaration.maximum_parent_records:
                raise ValueError("Rapid-004 cumulative parent budget exceeded")
            if next_count > 3000:
                raise ValueError("Rapid-004 parent configuration ceiling exceeded")
        record = self.store.begin_run(specification)
        if record["specification"] != expected:
            raise ValueError("Rapid-004 stored run specification differs")
        self._validate_stored_record(record, expected)
        self.runs[_text(record["run_id"], "run ID")] = record
        return record

    def _finish(
        self,
        record: Mapping[str, object],
        metrics: Mapping[str, object] | None,
        details: Mapping[str, object],
        *,
        error: str | None = None,
    ) -> dict[str, object]:
        completed = self.store.finish_run(
            _text(record["run_id"], "run ID"), metrics, details, error=error
        )
        specification = _mapping(completed["specification"], "completed specification")
        expected = self._require_allowed_specification(specification, exact_folds=bool(self.bars))
        self._validate_stored_record(completed, expected)
        self.runs[_text(completed["run_id"], "run ID")] = completed
        return completed

    def _execute(
        self,
        specification: Mapping[str, object],
        bars: Sequence[OHLCVBar],
        strategy: PortfolioStrategy,
        *,
        evaluation_start: datetime,
        evaluation_end: datetime,
        benchmark_period_id: str | None,
        queue_portfolio_targets: bool = False,
    ) -> dict[str, object]:
        stored_strategy = _mapping(specification["strategy"], "run strategy")
        if (
            stored_strategy.get("id") != strategy.strategy_id
            or stored_strategy.get("version") != strategy.version
        ):
            raise ValueError("Rapid-004 executable strategy identity differs")
        record = self._begin(specification)
        if record["status"] == "completed":
            return record
        if record["status"] == "failed":
            raise ValueError(f"Rapid-004 run already failed: {record['run_id']}")
        costs = _mapping(specification["costs"], "run costs")
        execution = _mapping(specification["execution"], "run execution")
        try:
            result = BacktestEngine(
                Decimal(str(specification["initial_cash"])),
                CostModel(
                    _text(costs["version"], "cost model version"),
                    Decimal(str(costs["slippage_bps"])),
                    Decimal(str(costs["commission_bps"])),
                ),
                _integer(execution["fill_delay_bars"], "fill delay"),
                queue_portfolio_targets=queue_portfolio_targets,
            ).run_portfolio(bars, strategy)
            context = _mapping(specification["exploratory_context"], "context")
            metrics, instrument_profits, sleeve_profits = self._result_metrics(
                result,
                bars=bars,
                evaluation_start=evaluation_start,
                evaluation_end=evaluation_end,
                benchmark_period_id=benchmark_period_id,
                scenario_id=_text(context["scenario_id"], "scenario ID"),
            )
            return self._finish(
                record,
                metrics,
                {
                    "input_bar_count": len(bars),
                    "symbols": self.plan.binding.symbols,
                    "backtest_artifact_fingerprint": result.artifact_fingerprint,
                    "positive_instrument_profit": instrument_profits,
                    "positive_sleeve_profit": sleeve_profits,
                },
            )
        except Exception as error:
            self._finish(
                record,
                None,
                {"input_bar_count": len(bars), "symbols": self.plan.binding.symbols},
                error=f"{type(error).__name__}: {error}",
            )
            raise

    def _result_metrics(
        self,
        result: BacktestResult,
        *,
        bars: Sequence[OHLCVBar],
        evaluation_start: datetime,
        evaluation_end: datetime,
        benchmark_period_id: str | None,
        scenario_id: str,
    ) -> tuple[dict[str, object], dict[str, Decimal], dict[str, Decimal]]:
        metrics = research_metrics(
            result, evaluation_start=evaluation_start, evaluation_end=evaluation_end
        )
        instrument_profits = _positive_instrument_profits(result, bars)
        sleeve_profits = {
            sleeve: sum(
                (instrument_profits.get(symbol, Decimal("0")) for symbol in symbols),
                Decimal("0"),
            )
            for sleeve, symbols in self.plan.sleeves.items()
        }
        positive_sleeves = tuple(value for value in sleeve_profits.values() if value > 0)
        total_sleeve_profit = sum(positive_sleeves, Decimal("0"))
        metrics.update(
            {
                "max_sleeve_profit_share": (
                    max(positive_sleeves) / total_sleeve_profit if total_sleeve_profit else None
                ),
                "up_regime_return": result.metrics.up_regime_return,
                "down_regime_return": result.metrics.down_regime_return,
                "up_regime_sessions": result.metrics.up_regime_sessions,
                "down_regime_sessions": result.metrics.down_regime_sessions,
            }
        )
        if benchmark_period_id is not None and scenario_id == "normal":
            benchmark_returns = {
                benchmark_id: _metric(
                    self._find_benchmark(benchmark_id, benchmark_period_id), "total_return"
                )
                for benchmark_id in self._benchmark_ids()
            }
            candidate_return = _decimal_metric(metrics, "total_return")
            relative = {
                benchmark_id: candidate_return - value
                for benchmark_id, value in benchmark_returns.items()
            }
            metrics["benchmark_relative_return"] = relative
            metrics["gate_benchmark_excess_return"] = relative[self._gate_benchmark_id()]
        return metrics, instrument_profits, sleeve_profits

    def _find(self, **context_fields: object) -> dict[str, object]:
        matches = []
        for run in self.runs.values():
            specification = _mapping(run["specification"], "run specification")
            context = _mapping(specification["exploratory_context"], "run context")
            if all(context.get(name) == value for name, value in context_fields.items()):
                matches.append(run)
        if len(matches) != 1:
            raise ValueError(f"Rapid-004 evidence row count differs for {context_fields}")
        if matches[0]["status"] != "completed":
            raise ValueError("Rapid-004 required evidence row is incomplete")
        return matches[0]

    def _benchmark_ids(self) -> tuple[str, ...]:
        benchmarks = _mapping(self.plan.payload["benchmarks"], "benchmarks")["definitions"]
        if not isinstance(benchmarks, list):
            raise ValueError("Rapid-004 benchmarks differ")
        return tuple(
            _text(_mapping(item, "benchmark")["id"], "benchmark ID") for item in benchmarks
        )

    def _gate_benchmark_id(self) -> str:
        return _text(
            _mapping(self.plan.payload["benchmarks"], "benchmarks")["gate_benchmark_id"],
            "gate benchmark ID",
        )

    def _find_benchmark(self, benchmark_id: str, period_id: str) -> dict[str, object]:
        return self._find(
            stage="benchmark",
            benchmark_id=benchmark_id,
            period_id=period_id,
            scenario_id="normal",
        )

    def _symbols(self) -> tuple[Symbol, ...]:
        return tuple(
            sorted((Symbol(value) for value in self.plan.binding.symbols), key=lambda x: x.value)
        )

    def _configuration_strategy(
        self,
        configuration: Rapid004Configuration,
        *,
        evaluation_start: datetime | None = None,
    ) -> PortfolioStrategy:
        from .rapid_004_strategies import build_rapid_004_portfolio_strategy

        return build_rapid_004_portfolio_strategy(
            configuration.strategy_id,
            self._symbols(),
            self.plan.groups,
            self.plan.sleeves,
            self.plan.profiles,
            configuration.parameters,
            evaluation_start=evaluation_start,
        )

    def _run_benchmarks(self) -> None:
        definitions = _mapping(self.plan.payload["benchmarks"], "benchmarks")["definitions"]
        if not isinstance(definitions, list):
            raise ValueError("Rapid-004 benchmark definitions differ")
        symbols = self._symbols()
        for definition_value in definitions:
            definition = _mapping(definition_value, "benchmark")
            benchmark_id = _text(definition["id"], "benchmark ID")
            strategy_id = _text(definition["strategy_id"], "benchmark strategy ID")
            parameters = _integer_mapping(definition.get("parameters", {}), "benchmark parameters")
            raw_weights = _mapping(definition.get("weights", {}), "benchmark weights")
            configured_weights: dict[Symbol | str, Decimal | str] = {
                str(symbol): str(weight) for symbol, weight in raw_weights.items()
            }
            for period in self.plan.periods:
                if benchmark_id == "cash":
                    strategy: PortfolioStrategy = _FullUniverseFixedWeights(
                        symbols, {}, "cash", None
                    )
                elif benchmark_id in {"spy-buy-and-hold", "qqq-buy-and-hold"}:
                    held = Symbol("SPY" if benchmark_id.startswith("spy") else "QQQ")
                    strategy = _FullUniverseFixedWeights(
                        symbols, {held: Decimal("1")}, strategy_id, None
                    )
                elif benchmark_id == "strategic-allocation-21-historical-reference":
                    strategy = _FullUniverseStrategicAllocation(
                        symbols, parameters["rebalance_every"]
                    )
                else:
                    from .rapid_004_strategies import build_rapid_004_portfolio_strategy

                    strategy = build_rapid_004_portfolio_strategy(
                        strategy_id,
                        symbols,
                        self.plan.groups,
                        self.plan.sleeves,
                        self.plan.profiles,
                        parameters,
                        configured_weights=configured_weights,
                    )
                specification = self._specification(
                    run_type="rapid-004-benchmark",
                    strategy_id=strategy_id,
                    family_id=None,
                    parameters=parameters,
                    period=period,
                    scenario_id="normal",
                    strategy_version=strategy.version,
                    context={
                        "parent_record": True,
                        "stage": "benchmark",
                        "benchmark_id": benchmark_id,
                        "period_id": period.period_id,
                    },
                )
                self._execute(
                    specification,
                    self.period_bars[period.period_id],
                    strategy,
                    evaluation_start=period.timestamp_range.start,
                    evaluation_end=period.timestamp_range.end,
                    benchmark_period_id=None,
                )
        self.progress("completed 20 predeclared benchmark parent records")

    def _run_configuration(
        self,
        configuration: Rapid004Configuration,
        period: Rapid004Period,
        *,
        stage: str,
        scenario_id: str = "normal",
        parent_record: bool,
        parent_run_id: str | None = None,
        bars: Sequence[OHLCVBar] | None = None,
        evaluation_start: datetime | None = None,
        evaluation_end: datetime | None = None,
        fold: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        specification = self._specification(
            run_type=f"rapid-004-{stage}",
            strategy_id=configuration.strategy_id,
            family_id=configuration.family_id,
            parameters=configuration.parameters,
            period=period,
            scenario_id=scenario_id,
            context={
                "parent_record": parent_record,
                "stage": stage,
                "family_id": configuration.family_id,
                "source_stage": configuration.source_stage,
                "configuration_id": configuration.identity,
                "period_id": period.period_id,
            },
            parent_run_id=parent_run_id,
            fold=fold,
        )
        selected_bars = bars or self.period_bars[period.period_id]
        profile = self.plan.profiles[configuration.strategy_id]
        contract = _text(profile["contract"], "strategy contract")
        stateful = contract.startswith(("independent-trend", "channel-breakout"))
        strategy: PortfolioStrategy = self._configuration_strategy(
            configuration,
            evaluation_start=evaluation_start if stateful else None,
        )
        if evaluation_start is not None and not stateful:
            strategy = StartBoundPortfolioStrategy(strategy, evaluation_start)
        return self._execute(
            specification,
            selected_bars,
            strategy,
            evaluation_start=evaluation_start or period.timestamp_range.start,
            evaluation_end=evaluation_end or period.timestamp_range.end,
            benchmark_period_id=(
                period.period_id if scenario_id == "normal" and fold is None else None
            ),
            queue_portfolio_targets=stateful,
        )

    def _run_full_range_search(
        self,
    ) -> dict[str, list[tuple[Rapid004Configuration, dict[str, object]]]]:
        result: dict[str, list[tuple[Rapid004Configuration, dict[str, object]]]] = {
            family: []
            for family, _discovery, _confirmation in (
                self.plan.binding.predeclaration.family_configuration_counts
            )
        }
        gates = _mapping(
            _mapping(self.plan.payload["search"], "search")["full_range_early_gate"],
            "early gate",
        )["gates"]
        if not isinstance(gates, list):
            raise ValueError("Rapid-004 early gates differ")
        for (
            family,
            _discovery,
            _confirmation,
        ) in self.plan.binding.predeclaration.family_configuration_counts:
            for configuration in self.plan.family_configurations(family, "discovery"):
                result[family].append(
                    (
                        configuration,
                        self._run_configuration(
                            configuration,
                            self.plan.full_period,
                            stage="full-range-discovery",
                            parent_record=True,
                        ),
                    )
                )
        self.progress("completed every frozen full-range discovery configuration")
        for (
            family,
            _discovery,
            _confirmation,
        ) in self.plan.binding.predeclaration.family_configuration_counts:
            if any(_passes_gates(_metrics(row), gates) for _configuration, row in result[family]):
                for configuration in self.plan.family_configurations(family, "confirmation"):
                    result[family].append(
                        (
                            configuration,
                            self._run_configuration(
                                configuration,
                                self.plan.full_period,
                                stage="full-range-confirmation",
                                parent_record=True,
                            ),
                        )
                    )
            self.progress(
                f"family {family}: {len(result[family])} full-range parent configurations complete"
            )
        return result

    def _select_fixed_block_configurations(
        self,
        full_rows: Mapping[str, Sequence[tuple[Rapid004Configuration, dict[str, object]]]],
    ) -> dict[str, tuple[Rapid004Configuration, ...]]:
        gate = self._find_benchmark(self._gate_benchmark_id(), "full-range")
        early_gates = _mapping(
            _mapping(self.plan.payload["search"], "search")["full_range_early_gate"],
            "early gate",
        )["gates"]
        if not isinstance(early_gates, list):
            raise ValueError("Rapid-004 early gates differ")
        selected: dict[str, tuple[Rapid004Configuration, ...]] = {}
        for family_id, rows in full_rows.items():
            anchor = self.plan.anchor(family_id)
            eligible = [
                (configuration, row)
                for configuration, row in rows
                if configuration.identity != anchor.identity
                and _passes_gates(_metrics(row), early_gates)
                and (
                    _metric(row, "total_return") > _metric(gate, "total_return")
                    or _benchmark_risk_exception(_metrics(row), _metrics(gate))
                )
            ]
            eligible.sort(key=lambda item: _fixed_selection_key(item, gate))
            selected[family_id] = (anchor, *(item[0] for item in eligible[:4]))
        return selected

    def _run_fixed_blocks(
        self,
        full_rows: Mapping[str, Sequence[tuple[Rapid004Configuration, dict[str, object]]]],
    ) -> dict[str, tuple[Rapid004Configuration, ...]]:
        selected = self._select_fixed_block_configurations(full_rows)
        for family_id, configurations in selected.items():
            for configuration in configurations:
                for period in self.plan.block_periods:
                    self._run_configuration(
                        configuration,
                        period,
                        stage="fixed-block",
                        parent_record=True,
                    )
            self.progress(
                f"family {family_id}: {len(configurations)} identities completed fixed blocks"
            )
        return selected

    def _block_rows(
        self, configuration: Rapid004Configuration, stage: str = "fixed-block"
    ) -> tuple[dict[str, object], ...]:
        return tuple(
            self._find(
                stage=stage,
                family_id=configuration.family_id,
                configuration_id=configuration.identity,
                period_id=period.period_id,
                scenario_id="normal",
            )
            for period in self.plan.block_periods
        )

    def _fixed_block_metrics(self, configuration: Rapid004Configuration) -> dict[str, object]:
        rows = self._block_rows(configuration)
        metrics = tuple(_metrics(row) for row in rows)
        benchmark = tuple(
            _metrics(self._find_benchmark(self._gate_benchmark_id(), period.period_id))
            for period in self.plan.block_periods
        )
        returns = tuple(_decimal_metric(item, "total_return") for item in metrics)
        sharpe = tuple(_optional_decimal_metric(item, "sharpe_ratio") for item in metrics)
        top_five = tuple(
            _optional_decimal_metric(item, "top_5_session_profit_share") for item in metrics
        )
        instruments = tuple(
            _optional_decimal_metric(item, "top_instrument_profit_share") for item in metrics
        )
        sleeves = tuple(
            _optional_decimal_metric(item, "max_sleeve_profit_share") for item in metrics
        )
        excess = tuple(
            value - _decimal_metric(reference, "total_return")
            for value, reference in zip(returns, benchmark, strict=True)
        )
        wins = sum(value > 0 for value in excess)
        return {
            "validation_fold_count": len(rows),
            "positive_validation_fold_rate": Decimal(sum(value > 0 for value in returns))
            / Decimal(len(returns)),
            "gate_benchmark_win_count": wins,
            "gate_benchmark_win_rate": Decimal(wins) / Decimal(len(rows)),
            "fixed_block_returns": returns,
            "worst_fixed_block_excess_return": min(excess),
            "fixed_block_excess_returns": excess,
            "worst_validation_return": min(returns),
            "worst_validation_sharpe": _min_optional(sharpe),
            "max_validation_drawdown": max(
                _decimal_metric(item, "max_drawdown") for item in metrics
            ),
            "max_average_gross_exposure": max(
                _decimal_metric(item, "average_gross_exposure") for item in metrics
            ),
            "max_top_5_session_profit_share": _max_optional(top_five),
            "max_top_instrument_profit_share": _max_optional(instruments),
            "max_sleeve_profit_share": _max_optional(sleeves),
            "min_up_regime_sessions": min(
                _int_metric(item, "up_regime_sessions") for item in metrics
            ),
            "min_down_regime_sessions": min(
                _int_metric(item, "down_regime_sessions") for item in metrics
            ),
            "max_turnover": max(_decimal_metric(item, "turnover") for item in metrics),
            "total_validation_trade_count": sum(
                _int_metric(item, "trade_count") for item in metrics
            ),
            "block_run_ids": tuple(_text(row["run_id"], "run ID") for row in rows),
        }

    def _visible_base_passes(self, metrics: Mapping[str, object]) -> bool:
        screen = _mapping(self.plan.payload["exposed_screen"], "screen")
        visible = _mapping(screen["visible_base"], "visible screen")
        gates = visible["gates"]
        if not isinstance(gates, list):
            raise ValueError("Rapid-004 visible gates differ")
        return _passes_gates(metrics, gates)

    def _select_serious_configurations(
        self, selected: Mapping[str, Sequence[Rapid004Configuration]]
    ) -> dict[str, tuple[Rapid004Configuration, ...]]:
        serious: dict[str, tuple[Rapid004Configuration, ...]] = {}
        for family_id, configurations in selected.items():
            eligible = [
                (configuration, self._fixed_block_metrics(configuration))
                for configuration in configurations
            ]
            eligible = [item for item in eligible if self._visible_base_passes(item[1])]
            eligible.sort(key=_serious_selection_key)
            serious[family_id] = tuple(item[0] for item in eligible[:3])
        return serious

    def _select_and_evaluate_serious(
        self, selected: Mapping[str, Sequence[Rapid004Configuration]]
    ) -> dict[str, tuple[Rapid004Configuration, ...]]:
        serious = self._select_serious_configurations(selected)
        for family_id, chosen in serious.items():
            for configuration in chosen:
                self._run_walk_forward(configuration)
                self._run_neighbors(configuration)
            self.progress(f"family {family_id}: {len(chosen)} serious identities")
        for configurations in serious.values():
            for configuration in configurations:
                self._run_isolated_sensitivities(configuration)
        for configurations in serious.values():
            for configuration in configurations:
                self._run_combined_stress(configuration)
        return serious

    def _walk_forward_windows(
        self,
    ) -> tuple[tuple[Rapid004Period, dict[str, object]], ...]:
        if not self.bars:
            raise ValueError("Rapid-004 bars are not loaded")
        chronology = _mapping(self.plan.payload["chronology"], "chronology")
        walk = _mapping(chronology["walk_forward"], "walk-forward")
        training = _integer(walk["training_sessions"], "training sessions")
        testing = _integer(walk["test_sessions"], "test sessions")
        step = _integer(walk["step_sessions"], "step sessions")
        sessions = tuple(sorted({bar.timestamp for bar in self.bars}))
        folds: list[tuple[int, int, int]] = []
        start = 0
        while start + training + testing <= len(sessions):
            folds.append((start, start + training, start + training + testing - 1))
            start += step
        required = _integer(
            _mapping(self.plan.payload["walk_forward_screen"], "walk-forward screen")[
                "required_fold_count"
            ],
            "required fold count",
        )
        if len(folds) != required:
            raise ValueError("Rapid-004 walk-forward fold count differs")
        result = []
        for ordinal, (training_start, test_start, test_end) in enumerate(folds, start=1):
            result.append(
                (
                    Rapid004Period(
                        f"walk-forward-{ordinal}",
                        sessions[training_start].date().isoformat(),
                        sessions[test_end].date().isoformat(),
                    ),
                    {
                        "ordinal": ordinal,
                        "training_start": sessions[training_start].isoformat(),
                        "training_end": sessions[test_start - 1].isoformat(),
                        "test_start": sessions[test_start].isoformat(),
                        "test_end": sessions[test_end].isoformat(),
                        "training_sessions": training,
                        "test_sessions": testing,
                    },
                )
            )
        return tuple(result)

    def _run_walk_forward(self, configuration: Rapid004Configuration) -> dict[str, object]:
        windows = self._walk_forward_windows()
        required = len(windows)
        specification = self._specification(
            run_type="rapid-004-walk-forward",
            strategy_id=configuration.strategy_id,
            family_id=configuration.family_id,
            parameters=configuration.parameters,
            period=self.plan.full_period,
            scenario_id="normal",
            context={
                "parent_record": True,
                "stage": "walk-forward",
                "family_id": configuration.family_id,
                "source_stage": configuration.source_stage,
                "configuration_id": configuration.identity,
                "period_id": "full-range",
            },
        )
        parent = self._begin(specification)
        if parent["status"] == "completed":
            return parent
        if parent["status"] == "failed":
            raise ValueError(f"Rapid-004 walk-forward already failed: {parent['run_id']}")
        rows: list[dict[str, object]] = []
        for period, fold in windows:
            training_start = _timestamp(fold["training_start"], "training start")
            test_start = _timestamp(fold["test_start"], "test start")
            test_end = _timestamp(fold["test_end"], "test end")
            selected_bars = tuple(
                bar for bar in self.bars if training_start <= bar.timestamp <= test_end
            )
            rows.append(
                self._run_configuration(
                    configuration,
                    period,
                    stage="walk-forward-fold",
                    parent_record=False,
                    parent_run_id=_text(parent["run_id"], "parent run ID"),
                    bars=selected_bars,
                    evaluation_start=test_start,
                    evaluation_end=test_end,
                    fold=fold,
                )
            )
        metrics = _walk_forward_metrics(rows)
        return self._finish(
            parent,
            metrics,
            {
                "fold_run_ids": tuple(_text(row["run_id"], "fold run ID") for row in rows),
                "folds": required,
            },
        )

    def _neighbors(self, configuration: Rapid004Configuration) -> tuple[Rapid004Configuration, ...]:
        peers = tuple(
            item
            for item in self.plan.family_configurations(configuration.family_id)
            if item.strategy_id == configuration.strategy_id
        )
        family = self.plan.family(configuration.family_id)
        declared = _mapping(family["neighbor_values"], "family neighbor values")
        values = {
            name: _integers(raw_values, f"neighbor axis {name}")
            for name, raw_values in declared.items()
            if name in configuration.parameters
        }
        result: dict[str, Rapid004Configuration] = {}
        for name, ordered in values.items():
            try:
                index = ordered.index(configuration.parameters[name])
            except ValueError as error:
                raise ValueError("Rapid-004 configuration is outside its neighbor axis") from error
            for neighbor_index in (index - 1, index + 1):
                if not 0 <= neighbor_index < len(ordered):
                    continue
                parameters = configuration.parameters
                parameters[name] = ordered[neighbor_index]
                match = tuple(item for item in peers if item.parameters == parameters)
                if len(match) > 1:
                    raise ValueError("Rapid-004 neighbor identity is ambiguous")
                neighbor = (
                    match[0]
                    if match
                    else Rapid004Configuration(
                        configuration.family_id,
                        configuration.family_name,
                        "neighbor",
                        configuration.strategy_id,
                        tuple(sorted(parameters.items())),
                    )
                )
                try:
                    self._configuration_strategy(neighbor)
                except ValueError:
                    continue
                result[neighbor.identity] = neighbor
        if len(result) > 8:
            raise ValueError("Rapid-004 direct-neighbor cap exceeded")
        return tuple(result[name] for name in sorted(result))

    def _run_neighbors(self, configuration: Rapid004Configuration) -> None:
        neighbors = self._neighbors(configuration)
        if not neighbors:
            raise ValueError("Rapid-004 serious identity has no direct parameter neighbor")
        for neighbor in neighbors:
            for period in self.plan.block_periods:
                self._run_configuration(
                    neighbor,
                    period,
                    stage="parameter-neighbor",
                    parent_record=True,
                )

    def _run_isolated_sensitivities(self, configuration: Rapid004Configuration) -> None:
        for scenario_id in ("isolated-cost-2x", "isolated-delay-2"):
            for period in self.plan.block_periods:
                base = self._find(
                    stage="fixed-block",
                    family_id=configuration.family_id,
                    configuration_id=configuration.identity,
                    period_id=period.period_id,
                    scenario_id="normal",
                )
                self._run_configuration(
                    configuration,
                    period,
                    stage="isolated-sensitivity",
                    scenario_id=scenario_id,
                    parent_record=False,
                    parent_run_id=_text(base["run_id"], "base run ID"),
                )

    def _run_combined_stress(self, configuration: Rapid004Configuration) -> None:
        full = self._find(
            stage=f"full-range-{configuration.source_stage}",
            family_id=configuration.family_id,
            configuration_id=configuration.identity,
            period_id="full-range",
            scenario_id="normal",
        )
        for scenario_id in ("stress-a", "stress-b"):
            self._run_configuration(
                configuration,
                self.plan.full_period,
                stage="combined-stress",
                scenario_id=scenario_id,
                parent_record=False,
                parent_run_id=_text(full["run_id"], "base run ID"),
            )

    def _screen_serious(
        self, serious: Mapping[str, Sequence[Rapid004Configuration]]
    ) -> list[dict[str, object]]:
        exposed = _mapping(self.plan.payload["exposed_screen"], "exposed screen")
        visible_gates = _mapping(exposed["visible_base"], "visible screen")["gates"]
        walk_gates = _mapping(self.plan.payload["walk_forward_screen"], "walk-forward screen")[
            "gates"
        ]
        if not isinstance(visible_gates, list) or not isinstance(walk_gates, list):
            raise ValueError("Rapid-004 screen gates differ")
        screened: list[dict[str, object]] = []
        for configurations in serious.values():
            for configuration in configurations:
                fixed = self._fixed_block_metrics(configuration)
                neighbors = self._neighbors(configuration)
                walk = self._find(
                    stage="walk-forward",
                    family_id=configuration.family_id,
                    configuration_id=configuration.identity,
                    period_id="full-range",
                    scenario_id="normal",
                )
                walk_metrics = _metrics(walk)
                neighbor_retentions = self._neighbor_retentions(configuration)
                isolated = {
                    scenario_id: self._isolated_retentions(configuration, scenario_id)
                    for scenario_id in ("isolated-cost-2x", "isolated-delay-2")
                }
                stress = {
                    scenario_id: self._stress_metrics(configuration, scenario_id)
                    for scenario_id in ("stress-a", "stress-b")
                }
                failed = [
                    *(f"visible:{name}" for name in _failed_gates(fixed, visible_gates)),
                    *(f"walk-forward:{name}" for name in _failed_gates(walk_metrics, walk_gates)),
                ]
                if not neighbor_retentions or min(neighbor_retentions) < Decimal("0.50"):
                    failed.append("parameter-neighbors:minimum-return-retention")
                for scenario_id, values in isolated.items():
                    if not values or min(values) < Decimal("0.80"):
                        failed.append(f"{scenario_id}:minimum-return-retention")
                for scenario_id, stress_values in stress.items():
                    if stress_values["total_return"] <= 0:
                        failed.append(f"{scenario_id}:positive-return")
                    if stress_values["return_retention"] < Decimal("0.80"):
                        failed.append(f"{scenario_id}:minimum-return-retention")
                screened.append(
                    {
                        "family_id": configuration.family_id,
                        "family_name": configuration.family_name,
                        "cohort_diversity_group": self.plan.cohort_diversity_group(
                            configuration.family_id
                        ),
                        "source_stage": configuration.source_stage,
                        "strategy_id": configuration.strategy_id,
                        "parameters": configuration.parameters,
                        "configuration_fingerprint": configuration.identity,
                        "fixed_block_metrics": fixed,
                        "walk_forward_metrics": walk_metrics,
                        "minimum_parameter_neighbor_return_retention": min(neighbor_retentions),
                        "parameter_neighbor_retentions": neighbor_retentions,
                        "parameter_neighbors": tuple(
                            {
                                "strategy_id": neighbor.strategy_id,
                                "parameters": neighbor.parameters,
                                "configuration_fingerprint": neighbor.identity,
                            }
                            for neighbor in neighbors
                        ),
                        "minimum_cost_2x_return_retention": min(isolated["isolated-cost-2x"]),
                        "minimum_delay_2_return_retention": min(isolated["isolated-delay-2"]),
                        "isolated_retentions": isolated,
                        "combined_stress": stress,
                        "failed_gates": tuple(failed),
                        "passed": not failed,
                        "evidence": self._candidate_evidence(configuration),
                    }
                )
        screened.sort(key=lambda item: str(item["configuration_fingerprint"]))
        return screened

    def _neighbor_retentions(self, configuration: Rapid004Configuration) -> tuple[Decimal, ...]:
        result: list[Decimal] = []
        for neighbor in self._neighbors(configuration):
            for period in self.plan.block_periods:
                base = self._find(
                    stage="fixed-block",
                    family_id=configuration.family_id,
                    configuration_id=configuration.identity,
                    period_id=period.period_id,
                    scenario_id="normal",
                )
                row = self._find(
                    stage="parameter-neighbor",
                    family_id=neighbor.family_id,
                    configuration_id=neighbor.identity,
                    period_id=period.period_id,
                    scenario_id="normal",
                )
                result.append(_return_retention(row, base))
        return tuple(result)

    def _isolated_retentions(
        self, configuration: Rapid004Configuration, scenario_id: str
    ) -> tuple[Decimal, ...]:
        result = []
        for period in self.plan.block_periods:
            base = self._find(
                stage="fixed-block",
                family_id=configuration.family_id,
                configuration_id=configuration.identity,
                period_id=period.period_id,
                scenario_id="normal",
            )
            row = self._find(
                stage="isolated-sensitivity",
                family_id=configuration.family_id,
                configuration_id=configuration.identity,
                period_id=period.period_id,
                scenario_id=scenario_id,
            )
            result.append(_return_retention(row, base))
        return tuple(result)

    def _stress_metrics(
        self, configuration: Rapid004Configuration, scenario_id: str
    ) -> dict[str, Decimal]:
        base = self._find(
            stage=f"full-range-{configuration.source_stage}",
            family_id=configuration.family_id,
            configuration_id=configuration.identity,
            period_id="full-range",
            scenario_id="normal",
        )
        row = self._find(
            stage="combined-stress",
            family_id=configuration.family_id,
            configuration_id=configuration.identity,
            period_id="full-range",
            scenario_id=scenario_id,
        )
        return {
            "total_return": _metric(row, "total_return"),
            "return_retention": _return_retention(row, base),
        }

    def _candidate_evidence(self, configuration: Rapid004Configuration) -> dict[str, object]:
        matching: list[tuple[str, str]] = []
        neighbor_ids = {neighbor.identity for neighbor in self._neighbors(configuration)}
        neighbor_matching: list[tuple[str, str, str]] = []
        benchmark_matching: list[tuple[str, str]] = []
        for run in self.runs.values():
            specification = _mapping(run["specification"], "run specification")
            context = _mapping(specification["exploratory_context"], "run context")
            if (
                context.get("family_id") == configuration.family_id
                and context.get("configuration_id") == configuration.identity
            ):
                matching.append(
                    (
                        _text(context["stage"], "stage"),
                        _text(run["run_id"], "run ID"),
                    )
                )
            configuration_id = context.get("configuration_id")
            if (
                context.get("stage") == "parameter-neighbor"
                and isinstance(configuration_id, str)
                and configuration_id in neighbor_ids
            ):
                neighbor_matching.append(
                    (
                        configuration_id,
                        _text(context["period_id"], "period ID"),
                        _text(run["run_id"], "run ID"),
                    )
                )
            if (
                context.get("stage") == "benchmark"
                and context.get("benchmark_id") == self._gate_benchmark_id()
            ):
                benchmark_matching.append(
                    (
                        _text(context["period_id"], "period ID"),
                        _text(run["run_id"], "run ID"),
                    )
                )
        return {
            "candidate_run_ids_by_stage": {
                stage: tuple(
                    sorted(run_id for item_stage, run_id in matching if item_stage == stage)
                )
                for stage in sorted({item[0] for item in matching})
            },
            "parameter_neighbor_run_ids": {
                neighbor_id: {
                    period_id: run_id
                    for item_neighbor_id, period_id, run_id in neighbor_matching
                    if item_neighbor_id == neighbor_id
                }
                for neighbor_id in sorted(neighbor_ids)
            },
            "gate_benchmark_run_ids": dict(sorted(benchmark_matching)),
            "evidence_run_count": len(matching) + len(neighbor_matching) + len(benchmark_matching),
        }

    def _controlled_plan(self, screened: Mapping[str, object]) -> dict[str, object]:
        configuration_id = _text(screened["configuration_fingerprint"], "configuration fingerprint")
        configuration = next(
            (item for item in self.plan.configurations if item.identity == configuration_id),
            None,
        )
        if configuration is None:
            raise ValueError("Rapid-004 cohort configuration is not frozen")
        neighbors = self._neighbors(configuration)
        benchmark_id = self._gate_benchmark_id()
        benchmark = next(
            (
                _mapping(item, "benchmark")
                for item in _mapping(self.plan.payload["benchmarks"], "benchmarks")["definitions"]
                if _mapping(item, "benchmark").get("id") == benchmark_id
            ),
            None,
        )
        if benchmark is None:
            raise ValueError("Rapid-004 gate benchmark is missing")

        def record(
            role: str,
            strategy_id: str,
            parameters: Mapping[str, int],
            period: Rapid004Period,
            scenario_id: str,
            **context: object,
        ) -> dict[str, object]:
            value: dict[str, object] = {
                "role": role,
                "strategy_id": strategy_id,
                "parameters": dict(parameters),
                "period": {
                    "id": period.period_id,
                    "start": period.start,
                    "end": period.end,
                },
                "scenario": dict(self._scenario(scenario_id)),
                **context,
            }
            value["record_fingerprint"] = fingerprint(value)
            return value

        records: list[dict[str, object]] = []
        benchmark_parameters = _integer_mapping(
            benchmark.get("parameters", {}), "benchmark parameters"
        )
        for period in self.plan.block_periods:
            records.extend(
                (
                    record(
                        "candidate-base",
                        configuration.strategy_id,
                        configuration.parameters,
                        period,
                        "normal",
                        configuration_fingerprint=configuration.identity,
                    ),
                    record(
                        "gate-benchmark",
                        _text(benchmark["strategy_id"], "benchmark strategy ID"),
                        benchmark_parameters,
                        period,
                        "normal",
                        benchmark_id=benchmark_id,
                        weights=_mapping(benchmark.get("weights", {}), "benchmark weights"),
                    ),
                    record(
                        "isolated-cost",
                        configuration.strategy_id,
                        configuration.parameters,
                        period,
                        "isolated-cost-2x",
                        configuration_fingerprint=configuration.identity,
                    ),
                    record(
                        "isolated-delay",
                        configuration.strategy_id,
                        configuration.parameters,
                        period,
                        "isolated-delay-2",
                        configuration_fingerprint=configuration.identity,
                    ),
                )
            )
            records.extend(
                record(
                    "parameter-neighbor",
                    neighbor.strategy_id,
                    neighbor.parameters,
                    period,
                    "normal",
                    base_configuration_fingerprint=configuration.identity,
                    configuration_fingerprint=neighbor.identity,
                )
                for neighbor in neighbors
            )
        records.extend(
            record(
                "combined-stress",
                configuration.strategy_id,
                configuration.parameters,
                self.plan.full_period,
                scenario_id,
                configuration_fingerprint=configuration.identity,
            )
            for scenario_id in ("stress-a", "stress-b")
        )
        policy = _mapping(
            _mapping(self.plan.payload["cohort"], "cohort")["controlled_plan"],
            "controlled plan",
        )
        if len(records) > _integer(policy["maximum_records"], "controlled record maximum"):
            raise ValueError("Rapid-004 controlled record maximum exceeded")
        payload: dict[str, object] = {
            "schema_version": "rapid-004-controlled-candidate-plan-v1",
            "program_id": RAPID_004_PROGRAM_ID,
            "source_commit": self.code["commit"],
            "campaign": self.plan.binding.specification(),
            "candidate": {
                "family_id": configuration.family_id,
                "cohort_diversity_group": self.plan.cohort_diversity_group(configuration.family_id),
                "strategy_id": configuration.strategy_id,
                "strategy_version": "rapid-004-mechanics-v1",
                "strategy_profile": self.plan.profiles[configuration.strategy_id],
                "parameters": configuration.parameters,
                "configuration_fingerprint": configuration.identity,
                "neighbors": tuple(
                    {
                        "strategy_id": neighbor.strategy_id,
                        "parameters": neighbor.parameters,
                        "configuration_fingerprint": neighbor.identity,
                    }
                    for neighbor in neighbors
                ),
            },
            "initial_cash": _mapping(self.plan.payload["execution"], "execution")["initial_cash"],
            "records": records,
            "record_count": len(records),
            "policy": policy,
            "authority": rapid_authority(),
        }
        payload["controlled_plan_fingerprint"] = fingerprint(payload)
        return payload

    def _freeze_cohort(self, screened: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
        passing = [dict(item) for item in screened if item["passed"] is True]
        by_group: dict[str, list[dict[str, object]]] = defaultdict(list)
        for item in passing:
            by_group[_text(item["cohort_diversity_group"], "cohort group")].append(item)
        for rows in by_group.values():
            rows.sort(key=_cohort_selection_key)
        cohort: list[dict[str, object]] = []
        maximum = _integer(
            _mapping(self.plan.payload["cohort"], "cohort")["maximum_candidates"],
            "maximum cohort candidates",
        )
        while len(cohort) < maximum and any(by_group.values()):
            round_rows = [rows[0] for rows in by_group.values() if rows]
            round_rows.sort(key=_cohort_selection_key)
            for row in round_rows:
                if len(cohort) == maximum:
                    break
                cohort.append(row)
                by_group[_text(row["cohort_diversity_group"], "cohort group")].pop(0)
        controlled_plans = [self._controlled_plan(item) for item in cohort]
        payload = {
            "schema_version": "rapid-004-cohort-freeze-v1",
            "status": "frozen-before-any-controlled-result",
            "program_id": RAPID_004_PROGRAM_ID,
            "runner_version": RUNNER_VERSION,
            "source_commit": self.code["commit"],
            "campaign": self.plan.binding.specification(),
            "screened_candidate_count": len(screened),
            "passing_candidate_count": len(passing),
            "screened_candidates_fingerprint": fingerprint(screened),
            "cohort": cohort,
            "cohort_fingerprint": fingerprint(cohort),
            "controlled_plans": controlled_plans,
            "controlled_plans_fingerprint": fingerprint(controlled_plans),
            "authority": rapid_authority(),
        }
        path = self.data_root / COHORT_FREEZE_NAME
        _write_create_only_json(path, payload)
        self.progress(f"froze complete cohort with {len(cohort)} candidate(s)")
        return cohort

    def _write_exposed_report(
        self,
        full_rows: Mapping[str, Sequence[tuple[Rapid004Configuration, dict[str, object]]]],
        selected: Mapping[str, Sequence[Rapid004Configuration]],
        serious: Mapping[str, Sequence[Rapid004Configuration]],
        screened: Sequence[Mapping[str, object]],
        cohort: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        families = []
        for (
            family_id,
            discovery_count,
            confirmation_count,
        ) in self.plan.binding.predeclaration.family_configuration_counts:
            rows = full_rows[family_id]
            strongest_configuration, strongest_row = min(rows, key=_strongest_full_range_key)
            confirmation_rows = sum(
                configuration.source_stage == "confirmation" for configuration, _row in rows
            )
            family_screened = [item for item in screened if item["family_id"] == family_id]
            families.append(
                {
                    "family_id": family_id,
                    "family_name": strongest_configuration.family_name,
                    "status": "TESTED",
                    "discovery_configuration_count": discovery_count,
                    "confirmation_configuration_count": confirmation_rows,
                    "maximum_conditional_confirmation_configuration_count": confirmation_count,
                    "confirmation_disposition": (
                        "TESTED" if confirmation_rows else "EXPLICITLY_REJECTED / INFEASIBLE"
                    ),
                    "full_range_parent_count": len(rows),
                    "fixed_block_identity_count": len(selected[family_id]),
                    "serious_identity_count": len(serious[family_id]),
                    "uniform_screen_pass_count": sum(
                        item["passed"] is True for item in family_screened
                    ),
                    "strongest_configuration": {
                        "strategy_id": strongest_configuration.strategy_id,
                        "parameters": strongest_configuration.parameters,
                        "configuration_fingerprint": strongest_configuration.identity,
                        "run_id": strongest_row["run_id"],
                        "metrics": strongest_row["metrics"],
                    },
                }
            )
        contexts = [
            _mapping(
                _mapping(run["specification"], "run specification")["exploratory_context"],
                "run context",
            )
            for run in self.runs.values()
        ]
        cohort_path = self.data_root / COHORT_FREEZE_NAME
        payload: dict[str, object] = {
            "schema_version": "rapid-004-exposed-report-v1",
            "evidence_class": "exploratory-uncontrolled",
            "program_id": RAPID_004_PROGRAM_ID,
            "runner_version": RUNNER_VERSION,
            "source_commit": self.code["commit"],
            "campaign": self.plan.binding.specification(),
            "data": {
                "symbols": self.plan.binding.symbols,
                "bar_count": len(self.bars),
                "session_count": len({bar.timestamp for bar in self.bars}),
                "start": self.plan.binding.start,
                "end": self.plan.binding.end,
                "validation": (
                    "full immutable catalog, Parquet, raw JSONL, identity, and range valid"
                ),
            },
            "benchmarks": _mapping(self.plan.payload["benchmarks"], "benchmarks"),
            "families": families,
            "counts": {
                "parent_configurations": self._parent_count(),
                "walk_forward_folds": sum(
                    context.get("stage") == "walk-forward-fold" for context in contexts
                ),
                "isolated_sensitivity_runs": sum(
                    context.get("stage") == "isolated-sensitivity" for context in contexts
                ),
                "combined_stress_runs": sum(
                    context.get("stage") == "combined-stress" for context in contexts
                ),
                "total_rapid_rows": len(self.runs),
            },
            "uniform_screen": list(screened),
            "uniform_screen_fingerprint": fingerprint(screened),
            "cohort": list(cohort),
            "cohort_fingerprint": fingerprint(cohort),
            "cohort_freeze_path": str(cohort_path),
            "cohort_freeze_sha256": _sha256(cohort_path),
            "protected_state": _mapping(self.plan.payload["protected_state"], "protected state"),
            "authority": rapid_authority(),
        }
        payload["report_fingerprint"] = fingerprint(payload)
        path = self.data_root / EXPOSED_REPORT_NAME
        _write_create_only_json(path, payload)
        self.progress(f"wrote exposed report {path}")
        return {
            "path": str(path),
            "sha256": _sha256(path),
            "report_fingerprint": payload["report_fingerprint"],
        }


def run_rapid_004_campaign(
    repository: Path,
    data_root: Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    return Rapid004CampaignRunner(repository, data_root, progress=progress).run()


def _code_identity(repository: Path) -> dict[str, object]:
    command = ("git", "--no-replace-objects", "-c", "core.fsmonitor=false", "-C", str(repository))
    environment = non_broker_subprocess_environment()
    environment.update({"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"})
    try:
        commit = subprocess.run(
            (*command, "rev-parse", "HEAD"),
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout.strip()
        dirty = subprocess.run(
            (*command, "status", "--porcelain", "--untracked-files=all"),
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError("Rapid-004 source identity is unavailable") from error
    if dirty:
        raise ValueError("Rapid-004 requires a clean reviewed source commit")
    return _validated_code_identity({"commit": commit, "dirty": False})


def _validated_code_identity(value: Mapping[str, object]) -> dict[str, object]:
    if set(value) != {"commit", "dirty"}:
        raise ValueError("Rapid-004 source identity fields differ")
    commit = _text(value["commit"], "source commit")
    if (
        len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
        or value["dirty"] is not False
    ):
        raise ValueError("Rapid-004 source identity is invalid")
    return {"commit": commit, "dirty": False}


def _positive_instrument_profits(
    result: BacktestResult, bars: Sequence[OHLCVBar]
) -> dict[str, Decimal]:
    positions = dict(result.equity_curve[-1].positions) if result.equity_curve else {}
    marks: dict[Symbol, Decimal] = {}
    for bar in bars:
        marks[bar.symbol] = bar.close
    profits: dict[str, Decimal] = {}
    symbols = set(positions) | {trade.symbol for trade in result.trades}
    for symbol in symbols:
        net_investment = sum(
            (
                trade.quantity * trade.fill_price + trade.commission
                for trade in result.trades
                if trade.symbol == symbol
            ),
            Decimal("0"),
        )
        profit = positions.get(symbol, Decimal("0")) * marks[symbol] - net_investment
        if profit > 0:
            profits[symbol.value] = profit
    return dict(sorted(profits.items()))


def _metrics(run: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping(run.get("metrics"), "run metrics")


def _metric(run: Mapping[str, object], name: str) -> Decimal:
    return _decimal_metric(_metrics(run), name)


def _decimal_metric(metrics: Mapping[str, object], name: str) -> Decimal:
    value = metrics.get(name)
    if value is None or isinstance(value, bool):
        raise ValueError(f"Rapid-004 metric is missing: {name}")
    try:
        result = Decimal(str(value))
    except Exception as error:
        raise ValueError(f"Rapid-004 metric is invalid: {name}") from error
    if not result.is_finite():
        raise ValueError(f"Rapid-004 metric is invalid: {name}")
    return result


def _optional_decimal_metric(metrics: Mapping[str, object], name: str) -> Decimal | None:
    return None if metrics.get(name) is None else _decimal_metric(metrics, name)


def _int_metric(metrics: Mapping[str, object], name: str) -> int:
    value = metrics.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Rapid-004 integer metric is invalid: {name}")
    return value


def _passes_gates(metrics: Mapping[str, object], gates: Sequence[object]) -> bool:
    return not _failed_gates(metrics, gates)


def _failed_gates(metrics: Mapping[str, object], gates: Sequence[object]) -> tuple[str, ...]:
    failed = []
    for gate_value in gates:
        gate = _mapping(gate_value, "gate")
        name = _text(gate["metric"], "gate metric")
        comparison = _text(gate["comparison"], "gate comparison")
        try:
            value = _decimal_metric(metrics, name)
            threshold = Decimal(str(gate["threshold"]))
        except (ArithmeticError, ValueError):
            failed.append(name)
            continue
        passed = {
            ">": value > threshold,
            ">=": value >= threshold,
            "<=": value <= threshold,
            "==": value == threshold,
        }.get(comparison)
        if passed is not True:
            failed.append(name)
    return tuple(failed)


def _benchmark_risk_exception(
    candidate: Mapping[str, object], benchmark: Mapping[str, object]
) -> bool:
    try:
        candidate_return = _decimal_metric(candidate, "total_return")
        candidate_sharpe = _decimal_metric(candidate, "sharpe_ratio")
        candidate_drawdown = _decimal_metric(candidate, "max_drawdown")
        candidate_annualized = _decimal_metric(candidate, "annualized_return")
        benchmark_sharpe = _decimal_metric(benchmark, "sharpe_ratio")
        benchmark_drawdown = _decimal_metric(benchmark, "max_drawdown")
        benchmark_annualized = _decimal_metric(benchmark, "annualized_return")
    except ValueError:
        return False
    return (
        candidate_return > 0
        and benchmark_drawdown != 0
        and candidate_sharpe >= benchmark_sharpe
        and candidate_drawdown <= Decimal("0.75") * benchmark_drawdown
        and (
            benchmark_annualized <= 0
            or candidate_annualized >= Decimal("0.80") * benchmark_annualized
        )
    )


def _fixed_selection_key(
    item: tuple[Rapid004Configuration, Mapping[str, object]],
    gate: Mapping[str, object],
) -> tuple[object, ...]:
    configuration, row = item
    metrics = _metrics(row)
    beats = _decimal_metric(metrics, "total_return") > _metric(gate, "total_return")
    sharpe = _optional_decimal_metric(metrics, "sharpe_ratio")
    return (
        0 if beats else 1,
        -_decimal_metric(metrics, "total_return"),
        -(sharpe if sharpe is not None else Decimal("-999")),
        _decimal_metric(metrics, "max_drawdown"),
        configuration.identity,
    )


def _serious_selection_key(
    item: tuple[Rapid004Configuration, Mapping[str, object]],
) -> tuple[object, ...]:
    configuration, metrics = item
    sharpe = _optional_decimal_metric(metrics, "worst_validation_sharpe")
    return (
        -_decimal_metric(metrics, "gate_benchmark_win_count"),
        -_decimal_metric(metrics, "worst_fixed_block_excess_return"),
        -(sharpe if sharpe is not None else Decimal("-999")),
        _decimal_metric(metrics, "max_validation_drawdown"),
        configuration.identity,
    )


def _cohort_selection_key(item: Mapping[str, object]) -> tuple[object, ...]:
    metrics = _mapping(item["fixed_block_metrics"], "fixed-block metrics")
    sharpe = _optional_decimal_metric(metrics, "worst_validation_sharpe")
    return (
        -_decimal_metric(metrics, "worst_fixed_block_excess_return"),
        -(sharpe if sharpe is not None else Decimal("-999")),
        _decimal_metric(metrics, "max_validation_drawdown"),
        _decimal_metric(metrics, "max_turnover"),
        _text(item["configuration_fingerprint"], "configuration fingerprint"),
    )


def _strongest_full_range_key(
    item: tuple[Rapid004Configuration, Mapping[str, object]],
) -> tuple[object, ...]:
    configuration, row = item
    metrics = _metrics(row)
    sharpe = _optional_decimal_metric(metrics, "sharpe_ratio")
    return (
        -_decimal_metric(metrics, "total_return"),
        -(sharpe if sharpe is not None else Decimal("-999")),
        _decimal_metric(metrics, "max_drawdown"),
        configuration.identity,
    )


def _min_optional(values: Sequence[Decimal | None]) -> Decimal | None:
    return (
        None
        if not values or any(value is None for value in values)
        else min(value for value in values if value is not None)
    )


def _max_optional(values: Sequence[Decimal | None]) -> Decimal | None:
    return (
        None
        if not values or any(value is None for value in values)
        else max(value for value in values if value is not None)
    )


def _walk_forward_metrics(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    completed = tuple(row for row in rows if row["status"] == "completed")
    returns = tuple(_metric(row, "total_return") for row in completed)
    combined = Decimal("1")
    for value in returns:
        combined *= Decimal("1") + value
    mean = sum(returns, Decimal("0")) / Decimal(len(returns)) if returns else None
    dispersion = (
        (
            sum(((value - mean) ** 2 for value in returns), Decimal("0"))
            / Decimal(len(returns) - 1)
        ).sqrt()
        if mean is not None and len(returns) > 1
        else Decimal("0")
        if returns
        else None
    )
    profitable = sum(value > 0 for value in returns)
    return {
        "fold_count": len(rows),
        "completed_fold_count": len(completed),
        "failed_fold_count": len(rows) - len(completed),
        "overall_out_of_sample_return": combined - Decimal("1") if returns else None,
        "mean_fold_return": mean,
        "fold_return_dispersion": dispersion,
        "fold_returns": returns,
        "profitable_fold_count": profitable,
        "profitable_fold_rate": Decimal(profitable) / Decimal(len(returns)) if returns else None,
        "best_fold_return": max(returns) if returns else None,
        "worst_fold_return": min(returns) if returns else None,
        "total_trade_count": sum(_int_metric(_metrics(row), "trade_count") for row in completed),
        "total_cost_paid": sum((_metric(row, "cost_paid") for row in completed), Decimal("0")),
        "score": None,
        "net_of_costs": True,
    }


def _return_retention(scenario: Mapping[str, object], base: Mapping[str, object]) -> Decimal:
    denominator = _metric(base, "total_return")
    return _metric(scenario, "total_return") / denominator if denominator > 0 else Decimal("-1")


def _write_create_only_json(path: Path, payload: Mapping[str, object]) -> None:
    contents = (canonical_json(payload) + "\n").encode()
    if path.exists():
        if path.read_bytes() != contents:
            raise FileExistsError(f"Rapid-004 artifact already exists with other bytes: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(name)
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


def _sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()
