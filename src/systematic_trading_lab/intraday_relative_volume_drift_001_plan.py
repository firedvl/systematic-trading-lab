"""Strict loader for the frozen Intraday Relative-Volume Drift 001 plan."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .fingerprints import fingerprint
from .intraday_autonomous_research_program import (
    PROGRAM_FINGERPRINT as AUTONOMOUS_PROGRAM_FINGERPRINT,
)
from .intraday_autonomous_research_program import (
    PROGRAM_ID as AUTONOMOUS_PROGRAM_ID,
)
from .intraday_autonomous_research_program import (
    PROGRAM_RELATIVE_PATH as AUTONOMOUS_PROGRAM_RELATIVE_PATH,
)
from .intraday_autonomous_research_program import (
    PROGRAM_SHA256 as AUTONOMOUS_PROGRAM_SHA256,
)
from .intraday_autonomous_research_program import (
    REVIEW_FINGERPRINT as AUTONOMOUS_REVIEW_FINGERPRINT,
)
from .intraday_autonomous_research_program import (
    REVIEW_RELATIVE_PATH as AUTONOMOUS_REVIEW_RELATIVE_PATH,
)
from .intraday_autonomous_research_program import (
    REVIEW_SHA256 as AUTONOMOUS_REVIEW_SHA256,
)
from .intraday_autonomous_research_program import (
    STATE_SHA256 as AUTONOMOUS_SOURCE_STATE_SHA256,
)
from .intraday_autonomous_research_program import (
    load_intraday_autonomous_research_program,
)

PROGRAM_ID = "intraday-relative-volume-drift-001"
PLAN_RELATIVE_PATH = Path("config/research/intraday-relative-volume-drift-001-plan-v1.json")
REVIEW_RELATIVE_PATH = Path(
    "config/research/intraday-relative-volume-drift-001-plan-independent-review-v1.json"
)
SOURCE_STATE_RELATIVE_PATH = Path(
    "docs/research-campaigns/intraday-autonomous-research-001-state-v2-revision-003.json"
)
STATE_RELATIVE_PATH = Path(
    "docs/research-campaigns/intraday-autonomous-research-001-state-v2-revision-004.json"
)

PLAN_SHA256 = "bc3731b5976fbf7ddb39d275a373ddec7a0678daefbbd1e745a0b0504833b518"
PLAN_FINGERPRINT = "699a41c4cf6dd38826361b9b7ad35cfb2869a5e59e73f0983bf27fbf9a63e111"
PLAN_SEMANTIC_FINGERPRINT = "35657d960c6d3c0245ca29a04a85e5c3d0144b852fc3c9d9160583f70618de19"
REVIEW_SHA256 = "c934369f1cdebeb99613a0ea0e5396c30ff5771c7ee2d92b380d4ca92b5a5611"
REVIEW_FINGERPRINT = "0fb04bfd40cd028355dd8bf4594093cb5bb0707945eeebf867cccab51d994946"
SOURCE_STATE_SHA256 = "7d35eeaf7f079033d1ce2f396088754ce5de22f829c88e3a884757672feef6a2"
SOURCE_STATE_FINGERPRINT = "7f35e0876c2398589b37b7a34d924e3a7a2d588f86f16102c5f2f4080b20d81e"
STATE_SHA256 = "6aa4f195b408e037dd11333f79d9f1b829ea01c12ac233b5b781866eb9ff1551"
STATE_FINGERPRINT = "69d8e113bea81e9bde27b34c3cf7909eea2cafed743a7238823e5a627ae3ff0b"

_STARTING_MAIN = "6fedd1acfce45758c75d93b6425873c74b4be5cb"
_AUTHORITY = {
    "strategy_results": False,
    "research_qualification": False,
    "controlled_evaluation": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}
_PROGRAM_AUTHORITY = {
    "strategy_execution": False,
    "research_qualification": False,
    "controlled_evaluation": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}
_REVIEW_AUTHORITY = {
    "strategy_execution": False,
    "controlled_evaluation": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}
_BASE_PLAN = {
    "path": "config/research/intraday-event-drift-001-plan-v1.json",
    "sha256": "c0dade2573405ddcd38d88814c10a27c3caae11bfb925a21179f6741cc20233c",
    "fingerprint": "73933d470feb52c1135746ab57db742019077b8b39e8e2545e9aba37c9a8d838",
}
_BASE_REVIEW = {
    "path": "config/research/intraday-event-drift-001-plan-independent-review-v1.json",
    "sha256": "25e92a85cee47aa261b4a85dce57666effbfbe329c203d3ac78df7b5bba9df96",
    "fingerprint": "0a464aca264ad4a8583d12fc4912898461ecf9e6121a1119322229e12bfb4077",
}
_COST_MODEL = {
    "path": "config/research/intraday-execution-cost-model-001-v1.json",
    "sha256": "a9e6c2b86c6623d73e089de591c55eeec0711fa55f0933a4e3ea9a1c0c2392af",
    "fingerprint": "94fc3ba4663b422fbb0dc0cce7e3d78a7ba81f22d71d5fa986ab6847b7925bb4",
}
_COST_REVIEW = {
    "path": "config/research/intraday-execution-cost-model-001-independent-review-v1.json",
    "sha256": "fb197856b9229349e5de4bca742f328a8f1e5e53f9558dfd7324744e91a795aa",
    "fingerprint": "8ade5190bb64330af037f88bf0911ed3cdb04578ca7a6d6e27a5fa6d651349b2",
    "verdict": "pass",
}
_JUNE_DISPOSITION = {
    "path": "config/research/intraday-exposed-005-june-disposition-v1.json",
    "sha256": "af6aea5e8d7bd8360aa6af4ddc31e1e67a1be48476f6c8ab13197fe12515b3c0",
    "fingerprint": "6dad6480dc3b0379017d582bb2f29fc562f41379bb3065855c55eadf51f025dd",
    "range_status": "ineligible",
}
_AUTONOMOUS_REVIEW = {
    "path": AUTONOMOUS_REVIEW_RELATIVE_PATH.as_posix(),
    "sha256": AUTONOMOUS_REVIEW_SHA256,
    "fingerprint": AUTONOMOUS_REVIEW_FINGERPRINT,
    "state_sha256": AUTONOMOUS_SOURCE_STATE_SHA256,
    "verdict": "pass",
}
_FROZEN_DEPENDENCIES = {
    "base_plan": _BASE_PLAN,
    "base_plan_review": _BASE_REVIEW,
    "execution_cost_model": _COST_MODEL,
    "execution_cost_review": _COST_REVIEW,
    "june_disposition": _JUNE_DISPOSITION,
    "autonomous_program_review": _AUTONOMOUS_REVIEW,
}
_DEPENDENCY_FILES = {
    "base_plan": (_BASE_PLAN, "plan_fingerprint", "base plan"),
    "base_plan_review": (_BASE_REVIEW, "review_fingerprint", "base plan review"),
    "execution_cost_model": (_COST_MODEL, "model_fingerprint", "execution cost model"),
    "execution_cost_review": (
        _COST_REVIEW,
        "review_fingerprint",
        "execution cost review",
    ),
    "june_disposition": (
        _JUNE_DISPOSITION,
        "disposition_fingerprint",
        "June disposition",
    ),
    "autonomous_program_review": (
        _AUTONOMOUS_REVIEW,
        "review_fingerprint",
        "autonomous program review",
    ),
}
_EVIDENCE_BINDINGS = (
    (
        "docs/research-campaigns/intraday-campaign-v2-postmortem.md",
        "7fe9fbc83a7a92954002bac5c3090fda6efc9c03a801bdd1fbff19e09f873f5c",
    ),
    (
        "docs/research-campaigns/intraday-exposed-001-final-report.md",
        "1ea6edb42b4d560dcdaee835172bd5614195f2a48dbf4bd61a9ab299689612ea",
    ),
    (
        "docs/research-campaigns/intraday-exposed-002-terminal-report.md",
        "e010a4fda5f40f778557a8164690248cbc158a806e0c30aac7f4ffd728d3926d",
    ),
    (
        "docs/research-campaigns/intraday-exposed-005-final-report.md",
        "c386eac54fec83f585b534edf9dbd386551053764330d58ccd64fa69ab3113de",
    ),
    (
        "docs/research-campaigns/intraday-event-drift-001-final-report.md",
        "357f3be173ae0038eb72c882a076d1795689a96ddcfa4b8545cd52f32eed6b11",
    ),
    (
        "docs/research-campaigns/intraday-event-repricing-001-final-report.md",
        "f97f2211885dba005ad92a1243ec7dc2fb0dad29eba92b4959446dbb3974476b",
    ),
    (
        "docs/research-campaigns/intraday-event-opening-breakout-001-final-report.md",
        "5b3168acdc31376636577c17e2a29afc51fe562e374278af427dfc3f1719bc89",
    ),
    (
        "docs/research-campaigns/intraday-event-prior-low-rejection-001-program.md",
        "40fb4548988d16e7bf78a338f902fc952e2817672f610989bc390490d5d91d71",
    ),
)
_DATASET_IDS = (
    "0a307dd767283d8f268c10b372c416abc49ac555cb242bf612f0b485be518363",
    "074e66c2260f576d6c1765295db93b5e22fb4753dc8f9912ef6f5be7fa937479",
    "1b1b5b1179a84522d6827827a6143a547321ef8b49262cdfb4d6a81885f647ed",
    "4afa60f29ea266ec8b60be9d9600132f8cff4207e846443c65afd3bb5c497a19",
)
_PERIODS = (
    (
        "discovery-2025-07-through-10",
        "2025-07-01T13:30:00Z",
        "2025-07-01T13:30:00Z",
        "2025-10-31T19:55:00Z",
        87,
    ),
    (
        "walk-forward-2025-11-through-12",
        "2025-10-20T13:30:00Z",
        "2025-11-03T14:30:00Z",
        "2025-12-31T20:55:00Z",
        41,
    ),
    (
        "walk-forward-2026-01-through-02",
        "2025-12-17T14:30:00Z",
        "2026-01-02T14:30:00Z",
        "2026-02-27T20:55:00Z",
        39,
    ),
    (
        "walk-forward-2026-03-through-04",
        "2026-02-13T14:30:00Z",
        "2026-03-02T14:30:00Z",
        "2026-04-30T19:55:00Z",
        43,
    ),
    (
        "final-exposed-2026-05",
        "2026-04-17T13:30:00Z",
        "2026-05-01T13:30:00Z",
        "2026-05-29T19:55:00Z",
        20,
    ),
)
_PLAN_KEYS = {
    "schema_version",
    "program_id",
    "autonomous_program",
    "program_state_source",
    "status",
    "starting_main",
    "purpose",
    "research_basis",
    "inheritance",
    "data",
    "chronology",
    "frozen_dependencies",
    "strategy_contract",
    "execution",
    "report_contract",
    "discovery_screen",
    "walk_forward_screen",
    "serious_candidate_screen",
    "stage_rules",
    "search_budget",
    "runtime",
    "controlled_evaluation",
    "protected_boundaries",
    "authority",
    "plan_fingerprint",
}
_PLAN_SEMANTIC_SECTIONS = (
    "research_basis",
    "inheritance",
    "data",
    "chronology",
    "strategy_contract",
    "execution",
    "report_contract",
    "discovery_screen",
    "walk_forward_screen",
    "serious_candidate_screen",
    "stage_rules",
    "search_budget",
    "runtime",
    "controlled_evaluation",
    "protected_boundaries",
    "authority",
)


@dataclass(frozen=True)
class RelativeVolumePeriod:
    period_id: str
    context_start: datetime
    evaluation_start: datetime
    evaluation_end: datetime
    session_count: int


@dataclass(frozen=True)
class RelativeVolumeConfiguration:
    candidate_id: str
    observation_horizon_bars: int
    minimum_joint_relative_volume: Decimal
    neighbor_ids: tuple[str, ...]


@dataclass(frozen=True)
class IntradayRelativeVolumeDrift001Plan:
    path: Path
    sha256: str
    plan_fingerprint: str
    review_path: Path
    review_sha256: str
    review_fingerprint: str
    source_state_path: Path
    source_state_sha256: str
    source_state_fingerprint: str
    state_path: Path
    state_sha256: str
    state_fingerprint: str
    payload: Mapping[str, Any]
    review: Mapping[str, Any]
    source_state: Mapping[str, Any]
    state: Mapping[str, Any]
    authority: Mapping[str, bool]
    periods: tuple[RelativeVolumePeriod, ...]
    configurations: tuple[RelativeVolumeConfiguration, ...]

    def __post_init__(self) -> None:
        for field in ("payload", "review", "source_state", "state", "authority"):
            object.__setattr__(self, field, _freeze(getattr(self, field)))


def load_intraday_relative_volume_drift_001_plan(
    repository: Path,
) -> IntradayRelativeVolumeDrift001Plan:
    """Load only the exact reviewed Campaign 2 control artifacts."""
    repository = repository.resolve()
    autonomous = load_intraday_autonomous_research_program(repository)
    path, payload = _load_fingerprinted(
        repository,
        PLAN_RELATIVE_PATH,
        PLAN_SHA256,
        "plan_fingerprint",
        PLAN_FINGERPRINT,
        "plan",
    )
    review_path, review = _load_fingerprinted(
        repository,
        REVIEW_RELATIVE_PATH,
        REVIEW_SHA256,
        "review_fingerprint",
        REVIEW_FINGERPRINT,
        "review",
    )
    source_state_path, source_state = _load_fingerprinted(
        repository,
        SOURCE_STATE_RELATIVE_PATH,
        SOURCE_STATE_SHA256,
        "state_fingerprint",
        SOURCE_STATE_FINGERPRINT,
        "source state",
    )
    state_path, state = _load_fingerprinted(
        repository,
        STATE_RELATIVE_PATH,
        STATE_SHA256,
        "state_fingerprint",
        STATE_FINGERPRINT,
        "state",
    )
    dependencies = _load_dependencies(repository)
    _verify_plan(repository, payload, autonomous.payload, source_state, dependencies)
    periods = _periods(payload)
    configurations = _configurations(payload)
    _verify_review(review)
    _verify_source_state(source_state)
    _verify_state(state, source_state)
    return IntradayRelativeVolumeDrift001Plan(
        path,
        PLAN_SHA256,
        PLAN_FINGERPRINT,
        review_path,
        REVIEW_SHA256,
        REVIEW_FINGERPRINT,
        source_state_path,
        SOURCE_STATE_SHA256,
        SOURCE_STATE_FINGERPRINT,
        state_path,
        STATE_SHA256,
        STATE_FINGERPRINT,
        payload,
        review,
        source_state,
        state,
        _AUTHORITY,
        periods,
        configurations,
    )


def _verify_plan(
    repository: Path,
    payload: Mapping[str, Any],
    autonomous: Mapping[str, Any],
    source_state: Mapping[str, Any],
    dependencies: Mapping[str, Mapping[str, Any]],
) -> None:
    if (
        fingerprint({name: payload.get(name) for name in _PLAN_SEMANTIC_SECTIONS})
        != PLAN_SEMANTIC_FINGERPRINT
    ):
        raise ValueError("Relative-Volume Drift 001 plan semantic fingerprint differs")
    autonomous_binding = _mapping(payload.get("autonomous_program"), "autonomous program")
    state_binding = _mapping(payload.get("program_state_source"), "program state source")
    inheritance = _mapping(payload.get("inheritance"), "inheritance")
    data = _mapping(payload.get("data"), "data")
    boundaries = _mapping(payload.get("protected_boundaries"), "protected boundaries")
    controlled = _mapping(payload.get("controlled_evaluation"), "controlled evaluation")
    base = dependencies["base_plan"]
    expected_state_binding = {
        "path": SOURCE_STATE_RELATIVE_PATH.as_posix(),
        "sha256": SOURCE_STATE_SHA256,
        "fingerprint": SOURCE_STATE_FINGERPRINT,
        "state_revision": 3,
        "successor_state_rule": (
            "Never mutate revision 3. After this exact plan passes independent review, publish "
            "immutable revision 4 binding revision 3, this plan, and its review before "
            "implementation."
        ),
    }
    if (
        set(payload) != _PLAN_KEYS
        or payload.get("schema_version") != "intraday-relative-volume-drift-001-research-plan-v1"
        or payload.get("program_id") != PROGRAM_ID
        or payload.get("status") != "prospective-frozen-before-strategy-implementation-or-results"
        or payload.get("starting_main") != _STARTING_MAIN
        or payload.get("authority") != _AUTHORITY
        or autonomous_binding
        != {
            "path": AUTONOMOUS_PROGRAM_RELATIVE_PATH.as_posix(),
            "sha256": AUTONOMOUS_PROGRAM_SHA256,
            "fingerprint": AUTONOMOUS_PROGRAM_FINGERPRINT,
            "campaign_index": 2,
            "maximum_run_specifications": 90,
        }
        or state_binding != expected_state_binding
        or source_state.get("state_revision") != 3
        or inheritance.get("base_plan") != _BASE_PLAN
        or inheritance.get("base_plan_review") != _BASE_REVIEW
        or inheritance.get("bound_base_artifacts")
        != [
            "data identity and read eligibility",
            "execution cost model and session safeguards",
            "protected-data and controlled-evaluation disposition",
        ]
        or inheritance.get("campaign_owned_sections")
        != [
            "chronology",
            "same-clock prior-session feature",
            "strategy contract",
            "screens and stage rules",
            "runtime and reporting",
        ]
        or payload.get("frozen_dependencies") != _FROZEN_DEPENDENCIES
        or data != base.get("data")
        or payload.get("execution") != base.get("execution")
        or boundaries != base.get("protected_boundaries")
        or tuple(
            item.get("dataset_id")
            for item in _list_of_mappings(data.get("dataset_bindings"), "dataset bindings")
        )
        != _DATASET_IDS
        or data.get("new_market_data_acquisition") is not False
        or data.get("maximum_read_end") != "2026-05-29T19:55:00Z"
        or controlled.get("range_status") != "none-eligible"
        or controlled.get("june_read") is not False
        or any(value is not False for value in boundaries.values() if isinstance(value, bool))
    ):
        raise ValueError("Relative-Volume Drift 001 plan binding differs")
    campaigns = _list_of_mappings(autonomous.get("campaigns"), "autonomous campaigns")
    if (
        campaigns[1].get("campaign_id") != PROGRAM_ID
        or campaigns[1].get("maximum_parent_candidates") != 9
        or campaigns[1].get("maximum_run_specifications") != 90
    ):
        raise ValueError("Relative-Volume Drift 001 autonomous campaign differs")
    evidence = _list_of_mappings(
        _mapping(payload.get("research_basis"), "research basis").get("complete_exposed_evidence"),
        "complete exposed evidence",
    )
    if tuple((item.get("path"), item.get("sha256")) for item in evidence) != (_EVIDENCE_BINDINGS):
        raise ValueError("Relative-Volume Drift 001 exposed evidence differs")
    for relative, expected_sha256 in _EVIDENCE_BINDINGS:
        _verify_raw_sha256(repository / relative, expected_sha256, "exposed evidence")
    _verify_strategy_and_budget(payload)


def _verify_strategy_and_budget(payload: Mapping[str, Any]) -> None:
    contract = _mapping(payload.get("strategy_contract"), "strategy contract")
    parameters = _mapping(contract.get("parameters"), "strategy parameters")
    fixed = _mapping(parameters.get("fixed"), "fixed strategy parameters")
    runtime = _mapping(payload.get("runtime"), "runtime")
    budget = _mapping(payload.get("search_budget"), "search budget")
    stage = _mapping(payload.get("stage_rules"), "stage rules")
    report = _mapping(payload.get("report_contract"), "report contract")
    serious = _mapping(payload.get("serious_candidate_screen"), "serious screen")
    prohibited_flags = (
        "cumulative_vwap_rule",
        "current_bar_recent_bar_volume_comparison",
        "event_filter",
        "opening_range_breakout",
        "relative_rank_or_leader_selection",
        "shorting",
        "trend_pullback_rule",
    )
    stage_total = sum(
        _mapping(budget.get(name), name).get("run_specifications", 0)
        for name in (
            "discovery_maximum",
            "walk_forward_maximum",
            "stress_and_delay_maximum",
            "immediate_neighbor_maximum",
        )
    )
    if (
        contract.get("strategy_id") != "intraday-joint-relative-volume-drift-v1"
        or contract.get("feature_symbols") != ["QQQ", "SPY"]
        or contract.get("traded_symbols") != ["QQQ", "SPY"]
        or contract.get("ordinary_sessions_only") is not True
        or contract.get("long_only") is not True
        or contract.get("leverage") is not False
        or any(contract.get(name) is not False for name in prohibited_flags)
        or contract.get("hold_bars") != 24
        or contract.get("disposition_priority")
        != [
            "lookback-ineligible",
            "hold-capacity-ineligible",
            "inactive-joint-return",
            "inactive-joint-relative-volume",
            "active",
        ]
        or fixed
        != {
            "hold_bars": 24,
            "maximum_entries_per_symbol_per_session": 1,
            "minimum_qqq_return_bps": "15",
            "minimum_spy_return_bps": "15",
            "prior_complete_session_lookback": 10,
            "qqq_target_weight": "0.5",
            "reentry_allowed": False,
            "resize_allowed": False,
            "same_clock_estimator": ("median-of-ten-prior-complete-session-cumulative-prefixes-v1"),
            "spy_target_weight": "0.5",
        }
        or parameters.get("axes")
        != [
            {"name": "observation_horizon_bars", "values": [8, 16, 24]},
            {"name": "minimum_joint_relative_volume", "values": ["1.2", "1.5", "2"]},
        ]
        or contract.get("participation_buckets")
        != [
            {
                "bucket_id": "participation-q-1-to-1-2",
                "lower_inclusive": "1",
                "upper_exclusive": "1.2",
            },
            {
                "bucket_id": "participation-q-1-2-to-1-5",
                "lower_inclusive": "1.2",
                "upper_exclusive": "1.5",
            },
            {
                "bucket_id": "participation-q-1-5-plus",
                "lower_inclusive": "1.5",
            },
        ]
        or not isinstance(report.get("canonical_metric_decode_rule"), str)
        or not isinstance(report.get("terminal_semantic_validation_rule"), str)
        or stage.get("run_identity_fields") != ["candidate_id", "period_id", "scenario_id"]
        or stage.get("no_partial_result_adaptation") is not True
        or runtime.get("namespace") != PROGRAM_ID
        or runtime.get("default_worker_count") != 4
        or runtime.get("maximum_infrastructure_attempts") != 3
        or "canonical metric decode failure" not in runtime.get("terminal_failures", ())
        or "screening semantic mismatch" not in runtime.get("terminal_failures", ())
        or budget.get("total_maximum_run_specifications") != 90
        or budget.get("maximum_total_attempts") != 270
        or budget.get("program_run_specifications_consumed_before_campaign") != 18
        or budget.get("campaign_1_unused_specifications_transferable") is not False
        or stage_total != 90
        or len(
            _list_of_mappings(
                _mapping(payload.get("discovery_screen"), "discovery screen").get("gates"),
                "discovery gates",
            )
        )
        != 12
        or len(
            _list_of_mappings(
                _mapping(payload.get("walk_forward_screen"), "walk-forward screen").get("gates"),
                "walk-forward gates",
            )
        )
        != 18
        or len(_list_of_mappings(serious.get("stress_gates"), "stress gates")) != 12
        or len(_list_of_mappings(serious.get("neighbor_gates"), "neighbor gates")) != 3
    ):
        raise ValueError("Relative-Volume Drift 001 strategy or budget differs")


def _periods(payload: Mapping[str, Any]) -> tuple[RelativeVolumePeriod, ...]:
    chronology = _mapping(payload.get("chronology"), "chronology")
    raw = _list_of_mappings(chronology.get("periods"), "periods")
    observed = tuple(
        (
            item.get("period_id"),
            item.get("context_start"),
            item.get("evaluation_start"),
            item.get("evaluation_end"),
            item.get("session_count"),
        )
        for item in raw
    )
    if (
        observed != _PERIODS
        or chronology.get("period_order") != [item[0] for item in _PERIODS]
        or chronology.get("maximum_market_timestamp") != "2026-05-29T19:55:00Z"
    ):
        raise ValueError("Relative-Volume Drift 001 chronology differs")
    return tuple(
        RelativeVolumePeriod(
            period_id,
            _timestamp(context_start),
            _timestamp(evaluation_start),
            _timestamp(evaluation_end),
            session_count,
        )
        for period_id, context_start, evaluation_start, evaluation_end, session_count in _PERIODS
    )


def _configurations(
    payload: Mapping[str, Any],
) -> tuple[RelativeVolumeConfiguration, ...]:
    parameters = _mapping(
        _mapping(payload.get("strategy_contract"), "strategy contract").get("parameters"),
        "strategy parameters",
    )
    raw = _list_of_mappings(parameters.get("candidates"), "candidates")
    configurations = tuple(
        RelativeVolumeConfiguration(
            _text(item, "candidate_id"),
            _integer(item, "observation_horizon_bars"),
            Decimal(_text(item, "minimum_joint_relative_volume")),
            tuple(_list_of_strings(item.get("neighbor_ids"), "neighbor IDs")),
        )
        for item in raw
    )
    expected = [
        (f"irvd001-a{row:02d}-b{column:02d}", horizon, Decimal(floor))
        for row, horizon in enumerate((8, 16, 24), 1)
        for column, floor in enumerate(("1.2", "1.5", "2"), 1)
    ]
    by_id = {item.candidate_id: item for item in configurations}
    directed = {
        (item.candidate_id, neighbor) for item in configurations for neighbor in item.neighbor_ids
    }
    if (
        parameters.get("candidate_count") != 9
        or [
            (
                item.candidate_id,
                item.observation_horizon_bars,
                item.minimum_joint_relative_volume,
            )
            for item in configurations
        ]
        != expected
        or len(by_id) != 9
        or any(item.neighbor_ids != tuple(sorted(item.neighbor_ids)) for item in configurations)
        or any(
            neighbor not in by_id or item.candidate_id not in by_id[neighbor].neighbor_ids
            for item in configurations
            for neighbor in item.neighbor_ids
        )
        or len(directed) != 24
        or len({tuple(sorted(edge)) for edge in directed}) != 12
    ):
        raise ValueError("Relative-Volume Drift 001 candidate graph differs")
    return configurations


def _verify_review(review: Mapping[str, Any]) -> None:
    verification = _mapping(review.get("verification"), "review verification")
    if (
        review.get("schema_version")
        != "intraday-relative-volume-drift-001-plan-independent-review-v1"
        or review.get("review_id")
        != "intraday-relative-volume-drift-001-plan-independent-review-v1"
        or review.get("status") != "passed-before-strategy-implementation-or-results"
        or review.get("verdict") != "pass"
        or review.get("findings") != []
        or review.get("authority") != _REVIEW_AUTHORITY
        or review.get("reviewed_plan")
        != {
            "program_id": PROGRAM_ID,
            "path": PLAN_RELATIVE_PATH.as_posix(),
            "sha256": PLAN_SHA256,
            "plan_fingerprint": PLAN_FINGERPRINT,
        }
        or review.get("reviewed_program")
        != {
            "program_id": AUTONOMOUS_PROGRAM_ID,
            "path": AUTONOMOUS_PROGRAM_RELATIVE_PATH.as_posix(),
            "sha256": AUTONOMOUS_PROGRAM_SHA256,
            "program_fingerprint": AUTONOMOUS_PROGRAM_FINGERPRINT,
            "campaign_index": 2,
            "maximum_run_specifications": 90,
        }
        or review.get("reviewed_source_state")
        != {
            "path": SOURCE_STATE_RELATIVE_PATH.as_posix(),
            "sha256": SOURCE_STATE_SHA256,
            "fingerprint": SOURCE_STATE_FINGERPRINT,
            "state_revision": 3,
        }
        or review.get("reviewed_dependencies") != _FROZEN_DEPENDENCIES
        or verification.get("candidate_count") != 9
        or verification.get("undirected_neighbor_edge_count") != 12
        or verification.get("maximum_run_specifications") != 90
        or verification.get("maximum_infrastructure_attempts") != 270
        or verification.get("canonical_decimal_decode_required") is not True
        or verification.get("terminal_semantic_validation_required") is not True
        or verification.get("exact_byte_rereview") is not True
        or verification.get("all_authority_fields_false") is not True
    ):
        raise ValueError("Relative-Volume Drift 001 independent review differs")


def _verify_source_state(state: Mapping[str, Any]) -> None:
    if (
        state.get("schema_version") != "intraday-autonomous-research-program-state-v2"
        or state.get("program_id") != AUTONOMOUS_PROGRAM_ID
        or state.get("state_revision") != 3
        or state.get("phase") != "campaign-1-terminal-empty-campaign-2-plan-pending"
        or state.get("current_campaign_index") != 2
        or state.get("next_campaign_id") != PROGRAM_ID
        or state.get("run_specifications_consumed") != 18
        or state.get("run_specifications_remaining") != 252
        or state.get("remaining_permitted_campaign_capacity") != 180
        or state.get("campaign_1_unused_specifications_transferable") is not False
        or state.get("authority") != _PROGRAM_AUTHORITY
    ):
        raise ValueError("Relative-Volume Drift 001 source program state differs")


def _verify_state(state: Mapping[str, Any], source_state: Mapping[str, Any]) -> None:
    if (
        state.get("schema_version") != "intraday-autonomous-research-program-state-v2"
        or state.get("program_id") != AUTONOMOUS_PROGRAM_ID
        or state.get("state_revision") != 4
        or state.get("previous_state")
        != {
            "path": SOURCE_STATE_RELATIVE_PATH.as_posix(),
            "sha256": SOURCE_STATE_SHA256,
            "fingerprint": SOURCE_STATE_FINGERPRINT,
            "state_revision": 3,
        }
        or state.get("campaign_plan")
        != {
            "campaign_id": PROGRAM_ID,
            "path": PLAN_RELATIVE_PATH.as_posix(),
            "sha256": PLAN_SHA256,
            "fingerprint": PLAN_FINGERPRINT,
        }
        or state.get("campaign_plan_review")
        != {
            "path": REVIEW_RELATIVE_PATH.as_posix(),
            "sha256": REVIEW_SHA256,
            "fingerprint": REVIEW_FINGERPRINT,
            "verdict": "pass",
        }
        or state.get("campaign_terminal_evidence") != source_state.get("campaign_terminal_evidence")
        or state.get("completed_campaigns") != source_state.get("completed_campaigns")
        or state.get("state_transition_contract") != source_state.get("state_transition_contract")
        or state.get("stop_conditions") != source_state.get("stop_conditions")
        or state.get("phase") != "campaign-2-plan-reviewed-implementation-pending"
        or state.get("current_campaign_index") != 2
        or state.get("active_campaign_id") != PROGRAM_ID
        or state.get("campaign_dispositions")
        != {
            "intraday-spy-qqq-lead-lag-001": ("terminal-empty-after-reviewed-reassessment"),
            PROGRAM_ID: "plan-reviewed-implementation-pending",
            "intraday-fed-policy-absorption-001": "not-started",
        }
        or state.get("run_specifications_consumed") != 18
        or state.get("run_specifications_remaining") != 252
        or state.get("global_numerical_headroom") != 252
        or state.get("remaining_permitted_campaign_capacity") != 180
        or state.get("campaign_1_unused_specifications_transferable") is not False
        or state.get("authority") != _PROGRAM_AUTHORITY
    ):
        raise ValueError("Relative-Volume Drift 001 program state differs")


def _load_dependencies(repository: Path) -> Mapping[str, Mapping[str, Any]]:
    values: dict[str, Mapping[str, Any]] = {}
    for name, (binding, key, label) in _DEPENDENCY_FILES.items():
        _, value = _load_fingerprinted(
            repository,
            Path(_text(binding, "path")),
            _text(binding, "sha256"),
            key,
            _text(binding, "fingerprint"),
            label,
        )
        values[name] = value
        if _FROZEN_DEPENDENCIES[name] != binding:
            raise ValueError("Relative-Volume Drift 001 dependency binding differs")
    return MappingProxyType(values)


def _load_fingerprinted(
    repository: Path,
    relative: Path,
    expected_sha256: str,
    fingerprint_key: str,
    expected_fingerprint: str,
    label: str,
) -> tuple[Path, Mapping[str, Any]]:
    path = repository / relative
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError(f"Relative-Volume Drift 001 {label} SHA-256 differs")
    try:
        payload = _mapping(json.loads(raw, object_pairs_hook=_unique_object), label)
    except json.JSONDecodeError as error:
        raise ValueError(f"Relative-Volume Drift 001 {label} is invalid JSON") from error
    unsigned = dict(payload)
    if (
        unsigned.pop(fingerprint_key, None) != expected_fingerprint
        or fingerprint(unsigned) != expected_fingerprint
    ):
        raise ValueError(f"Relative-Volume Drift 001 {label} fingerprint differs")
    return path, payload


def _verify_raw_sha256(path: Path, expected_sha256: str, label: str) -> None:
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError(f"Relative-Volume Drift 001 {label} SHA-256 differs")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Relative-Volume Drift 001 duplicate JSON key: {key}")
        value[key] = item
    return value


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo != UTC:
        raise ValueError("Relative-Volume Drift 001 timestamp must be UTC")
    return parsed


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"Relative-Volume Drift 001 {label} must be an object")
    return value


def _list_of_mappings(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list | tuple):
        raise ValueError(f"Relative-Volume Drift 001 {label} must be a list")
    return [_mapping(item, label) for item in value]


def _list_of_strings(value: object, label: str) -> list[str]:
    if not isinstance(value, list | tuple) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"Relative-Volume Drift 001 {label} must be a string list")
    return list(value)


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ValueError(f"Relative-Volume Drift 001 {key} must be text")
    return item


def _integer(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"Relative-Volume Drift 001 {key} must be an integer")
    return item
