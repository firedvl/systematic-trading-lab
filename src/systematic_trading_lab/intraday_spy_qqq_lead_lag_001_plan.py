"""Strict loader for the frozen Intraday SPY-QQQ Lead-Lag 001 plan."""

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
    STATE_RELATIVE_PATH as SOURCE_STATE_RELATIVE_PATH,
)
from .intraday_autonomous_research_program import (
    STATE_SHA256 as SOURCE_STATE_SHA256,
)
from .intraday_autonomous_research_program import (
    load_intraday_autonomous_research_program,
)

PROGRAM_ID = "intraday-spy-qqq-lead-lag-001"
PLAN_RELATIVE_PATH = Path("config/research/intraday-spy-qqq-lead-lag-001-plan-v1.json")
REVIEW_RELATIVE_PATH = Path(
    "config/research/intraday-spy-qqq-lead-lag-001-plan-independent-review-v1.json"
)
STATE_RELATIVE_PATH = Path(
    "docs/research-campaigns/intraday-autonomous-research-001-state-v2-revision-002.json"
)

PLAN_SHA256 = "1a02410da60f9dc90e2408e46e4dad88fe9ab9ec248ad8cb035f26734dc78b92"
PLAN_FINGERPRINT = "177fad36b3911b89a4938cdfe130a6eda81d22bd1d19e448ab7d11b46326a51a"
REVIEW_SHA256 = "71b60c8d4b900bb4ad1cb8c737fe26927b0365c7314aff5d64c688ffea6b6a07"
REVIEW_FINGERPRINT = "b0f14d7fe31f509300b1f5bedce4dcf6b94edba476efc8ed0b9f9fea351fe5d6"
STATE_SHA256 = "f74bc4ad3d0d30560ed0eb4718fc00739121849fb503e8045a01d8bc63907a0f"
STATE_FINGERPRINT = "a9be74e854942eaeea0cc65f67dca2c920a66d0e402e17452670543bb55b2058"

_AUTHORITY = {
    "strategy_results": False,
    "research_qualification": False,
    "controlled_evaluation": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}
_PROGRAM_AUTHORITY = {"strategy_execution": False, **dict(_AUTHORITY, strategy_results=False)}
_PROGRAM_AUTHORITY.pop("strategy_results")
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
    "state_sha256": SOURCE_STATE_SHA256,
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
_DEPENDENCY_FILES = (
    (_BASE_PLAN, "plan_fingerprint", "base plan"),
    (_BASE_REVIEW, "review_fingerprint", "base plan review"),
    (_COST_MODEL, "model_fingerprint", "execution cost model"),
    (_COST_REVIEW, "review_fingerprint", "execution cost review"),
    (_JUNE_DISPOSITION, "disposition_fingerprint", "June disposition"),
    (_AUTONOMOUS_REVIEW, "review_fingerprint", "autonomous program review"),
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


@dataclass(frozen=True)
class LeadLagPeriod:
    period_id: str
    context_start: datetime
    evaluation_start: datetime
    evaluation_end: datetime
    session_count: int


@dataclass(frozen=True)
class LeadLagConfiguration:
    candidate_id: str
    observation_horizon_bars: int
    minimum_spy_impulse_bps: Decimal
    neighbor_ids: tuple[str, ...]


@dataclass(frozen=True)
class IntradaySpyQqqLeadLag001Plan:
    path: Path
    sha256: str
    plan_fingerprint: str
    review_path: Path
    review_sha256: str
    review_fingerprint: str
    state_path: Path
    state_sha256: str
    state_fingerprint: str
    payload: Mapping[str, Any]
    review: Mapping[str, Any]
    state: Mapping[str, Any]
    authority: Mapping[str, bool]
    periods: tuple[LeadLagPeriod, ...]
    configurations: tuple[LeadLagConfiguration, ...]

    def __post_init__(self) -> None:
        for field in ("payload", "review", "state", "authority"):
            object.__setattr__(self, field, _freeze(getattr(self, field)))


def load_intraday_spy_qqq_lead_lag_001_plan(
    repository: Path,
) -> IntradaySpyQqqLeadLag001Plan:
    """Load only the exact reviewed Campaign 1 control artifacts."""
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
    state_path, state = _load_fingerprinted(
        repository,
        STATE_RELATIVE_PATH,
        STATE_SHA256,
        "state_fingerprint",
        STATE_FINGERPRINT,
        "state",
    )
    dependencies = _load_dependencies(repository)
    _verify_plan(payload, autonomous.payload, autonomous.state, dependencies)
    periods = _periods(payload)
    configurations = _configurations(payload)
    _verify_review(review)
    _verify_state(state)
    return IntradaySpyQqqLeadLag001Plan(
        path,
        PLAN_SHA256,
        PLAN_FINGERPRINT,
        review_path,
        REVIEW_SHA256,
        REVIEW_FINGERPRINT,
        state_path,
        STATE_SHA256,
        STATE_FINGERPRINT,
        payload,
        review,
        state,
        _AUTHORITY,
        periods,
        configurations,
    )


def _verify_plan(
    payload: Mapping[str, Any],
    autonomous: Mapping[str, Any],
    source_state: Mapping[str, Any],
    dependencies: Mapping[str, Mapping[str, Any]],
) -> None:
    autonomous_binding = _mapping(payload.get("autonomous_program"), "autonomous program")
    state_binding = _mapping(payload.get("program_state_source"), "program state source")
    inheritance = _mapping(payload.get("inheritance"), "inheritance")
    data = _mapping(payload.get("data"), "data")
    boundaries = _mapping(payload.get("protected_boundaries"), "protected boundaries")
    controlled = _mapping(payload.get("controlled_evaluation"), "controlled evaluation")
    base = dependencies["base_plan"]
    if (
        set(payload) != _PLAN_KEYS
        or payload.get("schema_version") != "intraday-spy-qqq-lead-lag-001-research-plan-v1"
        or payload.get("program_id") != PROGRAM_ID
        or payload.get("status") != "prospective-frozen-before-strategy-implementation-or-results"
        or payload.get("starting_main") != "4bb7615bcb508db114d11904d07dc202fe135e99"
        or payload.get("authority") != _AUTHORITY
        or autonomous_binding
        != {
            "path": AUTONOMOUS_PROGRAM_RELATIVE_PATH.as_posix(),
            "sha256": AUTONOMOUS_PROGRAM_SHA256,
            "fingerprint": AUTONOMOUS_PROGRAM_FINGERPRINT,
            "campaign_index": 1,
            "maximum_run_specifications": 90,
        }
        or state_binding.get("path") != SOURCE_STATE_RELATIVE_PATH.as_posix()
        or state_binding.get("sha256") != SOURCE_STATE_SHA256
        or state_binding.get("state_revision") != 1
        or source_state.get("state_revision") != 1
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
            "data read intersections",
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
        or any(value is not False for value in boundaries.values() if isinstance(value, bool))
    ):
        raise ValueError("SPY-QQQ Lead-Lag 001 plan binding differs")
    campaigns = _list_of_mappings(autonomous.get("campaigns"), "autonomous campaigns")
    if (
        campaigns[0].get("campaign_id") != PROGRAM_ID
        or campaigns[0].get("maximum_parent_candidates") != 9
        or campaigns[0].get("maximum_run_specifications") != 90
    ):
        raise ValueError("SPY-QQQ Lead-Lag 001 autonomous campaign differs")
    _verify_strategy_and_budget(payload)


def _verify_strategy_and_budget(payload: Mapping[str, Any]) -> None:
    contract = _mapping(payload.get("strategy_contract"), "strategy contract")
    fixed = _mapping(
        _mapping(contract.get("parameters"), "strategy parameters").get("fixed"),
        "fixed strategy parameters",
    )
    runtime = _mapping(payload.get("runtime"), "runtime")
    budget = _mapping(payload.get("search_budget"), "search budget")
    stage = _mapping(payload.get("stage_rules"), "stage rules")
    report = _mapping(payload.get("report_contract"), "report contract")
    if (
        contract.get("strategy_id") != "intraday-spy-qqq-fixed-leader-catchup-v1"
        or contract.get("feature_source_symbol") != "SPY"
        or contract.get("traded_symbol") != "QQQ"
        or contract.get("signal_only_symbol") != "SPY"
        or contract.get("ordinary_sessions_only") is not True
        or contract.get("long_only") is not True
        or contract.get("shorting") is not False
        or contract.get("leverage") is not False
        or contract.get("relative_rank_or_leader_selection") is not False
        or contract.get("event_filter") is not False
        or fixed
        != {
            "qqq_under_response_ratio_min": "0",
            "qqq_under_response_ratio_max": "0.5",
            "qqq_target_weight": "0.5",
            "spy_target_weight": "0",
            "hold_bars": 24,
            "maximum_entries_per_session": 1,
            "reentry_allowed": False,
            "resize_allowed": False,
        }
        or report.get("symbol_concentration_disposition")
        != (
            "not-applicable-by-design: SPY is signal-only and QQQ is the sole traded symbol; "
            "do not silently pass a multi-symbol concentration gate."
        )
        or stage.get("run_identity_fields") != ["candidate_id", "period_id", "scenario_id"]
        or runtime.get("namespace") != PROGRAM_ID
        or runtime.get("default_worker_count") != 4
        or runtime.get("maximum_infrastructure_attempts") != 3
        or budget.get("total_maximum_run_specifications") != 90
        or budget.get("maximum_total_attempts") != 270
        or sum(
            _mapping(budget.get(name), name).get("run_specifications", 0)
            for name in (
                "discovery_maximum",
                "walk_forward_maximum",
                "stress_and_delay_maximum",
                "immediate_neighbor_maximum",
            )
        )
        != 90
        or len(
            _list_of_mappings(
                _mapping(payload.get("discovery_screen"), "discovery screen").get("gates"),
                "discovery gates",
            )
        )
        != 11
        or len(
            _list_of_mappings(
                _mapping(payload.get("walk_forward_screen"), "walk-forward screen").get("gates"),
                "walk-forward gates",
            )
        )
        != 17
        or len(
            _list_of_mappings(
                _mapping(payload.get("serious_candidate_screen"), "serious screen").get(
                    "stress_gates"
                ),
                "stress gates",
            )
        )
        != 12
        or len(
            _list_of_mappings(
                _mapping(payload.get("serious_candidate_screen"), "serious screen").get(
                    "neighbor_gates"
                ),
                "neighbor gates",
            )
        )
        != 3
    ):
        raise ValueError("SPY-QQQ Lead-Lag 001 strategy or budget differs")


def _periods(payload: Mapping[str, Any]) -> tuple[LeadLagPeriod, ...]:
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
        raise ValueError("SPY-QQQ Lead-Lag 001 chronology differs")
    return tuple(
        LeadLagPeriod(
            period_id,
            _timestamp(context_start),
            _timestamp(evaluation_start),
            _timestamp(evaluation_end),
            session_count,
        )
        for period_id, context_start, evaluation_start, evaluation_end, session_count in _PERIODS
    )


def _configurations(payload: Mapping[str, Any]) -> tuple[LeadLagConfiguration, ...]:
    parameters = _mapping(
        _mapping(payload.get("strategy_contract"), "strategy contract").get("parameters"),
        "strategy parameters",
    )
    raw = _list_of_mappings(parameters.get("candidates"), "candidates")
    configurations = tuple(
        LeadLagConfiguration(
            _text(item, "candidate_id"),
            _integer(item, "observation_horizon_bars"),
            Decimal(_text(item, "minimum_spy_impulse_bps")),
            tuple(_list_of_strings(item.get("neighbor_ids"), "neighbor IDs")),
        )
        for item in raw
    )
    expected = [
        (f"isqlll001-a{row:02d}-b{column:02d}", horizon, Decimal(floor))
        for row, horizon in enumerate((6, 12, 18), 1)
        for column, floor in enumerate(("10", "20", "40"), 1)
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
                item.minimum_spy_impulse_bps,
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
        raise ValueError("SPY-QQQ Lead-Lag 001 candidate graph differs")
    return configurations


def _verify_review(review: Mapping[str, Any]) -> None:
    verification = _mapping(review.get("verification"), "review verification")
    if (
        review.get("schema_version") != "intraday-spy-qqq-lead-lag-001-plan-independent-review-v1"
        or review.get("review_id") != "intraday-spy-qqq-lead-lag-001-plan-independent-review-v1"
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
            "campaign_index": 1,
            "maximum_run_specifications": 90,
        }
        or review.get("reviewed_source_state")
        != {
            "path": SOURCE_STATE_RELATIVE_PATH.as_posix(),
            "sha256": SOURCE_STATE_SHA256,
            "state_revision": 1,
        }
        or review.get("reviewed_dependencies") != _FROZEN_DEPENDENCIES
        or verification.get("candidate_count") != 9
        or verification.get("undirected_neighbor_edge_count") != 12
        or verification.get("maximum_run_specifications") != 90
        or verification.get("maximum_infrastructure_attempts") != 270
        or verification.get("exact_byte_rereview") is not True
        or verification.get("all_authority_fields_false") is not True
    ):
        raise ValueError("SPY-QQQ Lead-Lag 001 independent review differs")


def _verify_state(state: Mapping[str, Any]) -> None:
    if (
        state.get("schema_version") != "intraday-autonomous-research-program-state-v2"
        or state.get("program_id") != AUTONOMOUS_PROGRAM_ID
        or state.get("state_revision") != 2
        or state.get("previous_state")
        != {
            "path": SOURCE_STATE_RELATIVE_PATH.as_posix(),
            "sha256": SOURCE_STATE_SHA256,
            "state_revision": 1,
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
        or state.get("phase") != "campaign-1-plan-reviewed-implementation-pending"
        or state.get("current_campaign_index") != 1
        or state.get("active_campaign_id") != PROGRAM_ID
        or state.get("run_specifications_consumed") != 0
        or state.get("run_specifications_remaining") != 270
        or state.get("authority") != _PROGRAM_AUTHORITY
    ):
        raise ValueError("SPY-QQQ Lead-Lag 001 program state differs")


def _load_dependencies(repository: Path) -> Mapping[str, Mapping[str, Any]]:
    values: dict[str, Mapping[str, Any]] = {}
    for (name, expected), (binding, key, label) in zip(
        _FROZEN_DEPENDENCIES.items(), _DEPENDENCY_FILES, strict=True
    ):
        _, value = _load_fingerprinted(
            repository,
            Path(_text(binding, "path")),
            _text(binding, "sha256"),
            key,
            _text(binding, "fingerprint"),
            label,
        )
        values[name] = value
        if expected != binding:
            raise ValueError("SPY-QQQ Lead-Lag 001 dependency order differs")
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
        raise ValueError(f"SPY-QQQ Lead-Lag 001 {label} SHA-256 differs")
    try:
        payload = _mapping(json.loads(raw, object_pairs_hook=_unique_object), label)
    except json.JSONDecodeError as error:
        raise ValueError(f"SPY-QQQ Lead-Lag 001 {label} is invalid JSON") from error
    unsigned = dict(payload)
    if (
        unsigned.pop(fingerprint_key, None) != expected_fingerprint
        or fingerprint(unsigned) != expected_fingerprint
    ):
        raise ValueError(f"SPY-QQQ Lead-Lag 001 {label} fingerprint differs")
    return path, payload


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"SPY-QQQ Lead-Lag 001 duplicate JSON key: {key}")
        value[key] = item
    return value


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo != UTC:
        raise ValueError("SPY-QQQ Lead-Lag 001 timestamp must be UTC")
    return parsed


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"SPY-QQQ Lead-Lag 001 {label} must be an object")
    return value


def _list_of_mappings(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list | tuple):
        raise ValueError(f"SPY-QQQ Lead-Lag 001 {label} must be a list")
    return [_mapping(item, label) for item in value]


def _list_of_strings(value: object, label: str) -> list[str]:
    if not isinstance(value, list | tuple) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"SPY-QQQ Lead-Lag 001 {label} must be a string list")
    return list(value)


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ValueError(f"SPY-QQQ Lead-Lag 001 {key} must be text")
    return item


def _integer(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"SPY-QQQ Lead-Lag 001 {key} must be an integer")
    return item
