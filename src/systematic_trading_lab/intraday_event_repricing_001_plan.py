"""Strict frozen-artifact loader for Intraday Event Repricing 001."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .fingerprints import fingerprint
from .intraday_event_drift_001_plan import (
    CALENDAR_FINGERPRINT as _CALENDAR_FINGERPRINT,
)
from .intraday_event_drift_001_plan import (
    CALENDAR_SHA256 as _CALENDAR_SHA256,
)
from .intraday_event_drift_001_plan import (
    SOURCE_EVIDENCE_FINGERPRINT as _SOURCE_EVIDENCE_FINGERPRINT,
)
from .intraday_event_drift_001_plan import (
    SOURCE_EVIDENCE_SHA256 as _SOURCE_EVIDENCE_SHA256,
)
from .intraday_event_drift_001_plan import (
    EventDriftEvent,
    EventDriftPeriod,
    load_intraday_event_drift_001_plan,
)

PROGRAM_ID = "intraday-event-repricing-001"
PLAN_RELATIVE_PATH = Path("config/research/intraday-event-repricing-001-plan-v1.json")
REVIEW_RELATIVE_PATH = Path(
    "config/research/intraday-event-repricing-001-plan-independent-review-v1.json"
)
PLAN_SHA256 = "f24cae1372f346be02c0079b931c77d5efb5105a06cf26631b783010851bd8b8"
PLAN_FINGERPRINT = "2f98e0cc4565435c9974f65791fd830f7fb9509730f31872f97d77484c00c489"
REVIEW_SHA256 = "0c17f683d21e0e365a730f6e267029d5be64eb62691e1a3bbacf6ead678048ca"
REVIEW_FINGERPRINT = "2351e230df1f6618247bbd91bed19ac6444baf09b8573ced2af9c6f937513ab5"
CALENDAR_SHA256 = _CALENDAR_SHA256
CALENDAR_FINGERPRINT = _CALENDAR_FINGERPRINT
SOURCE_EVIDENCE_SHA256 = _SOURCE_EVIDENCE_SHA256
SOURCE_EVIDENCE_FINGERPRINT = _SOURCE_EVIDENCE_FINGERPRINT

_AUTHORITY = {
    "strategy_results": False,
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


@dataclass(frozen=True)
class EventRepricingConfiguration:
    candidate_id: str
    reaction_bars: int
    minimum_relative_reaction_bps: Decimal
    neighbor_ids: tuple[str, ...]


@dataclass(frozen=True)
class IntradayEventRepricing001Plan:
    path: Path
    sha256: str
    plan_fingerprint: str
    review_path: Path
    review_sha256: str
    review_fingerprint: str
    calendar_sha256: str
    calendar_fingerprint: str
    source_evidence_sha256: str
    source_evidence_fingerprint: str
    payload: Mapping[str, Any]
    authority: Mapping[str, bool]
    events: tuple[EventDriftEvent, ...]
    periods: tuple[EventDriftPeriod, ...]
    configurations: tuple[EventRepricingConfiguration, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "authority", MappingProxyType(dict(self.authority)))

    @property
    def eligible_events(self) -> tuple[EventDriftEvent, ...]:
        return tuple(event for event in self.events if event.eligible)

    @property
    def excluded_events(self) -> tuple[EventDriftEvent, ...]:
        return tuple(event for event in self.events if not event.eligible)


def load_intraday_event_repricing_001_plan(repository: Path) -> IntradayEventRepricing001Plan:
    """Load only the exact reviewed successor plan and inherited Event Drift inputs."""
    repository = repository.resolve()
    base = load_intraday_event_drift_001_plan(repository)
    path, payload = _load_fingerprinted(
        repository, PLAN_RELATIVE_PATH, PLAN_SHA256, "plan_fingerprint", PLAN_FINGERPRINT, "plan"
    )
    review_path, review = _load_fingerprinted(
        repository,
        REVIEW_RELATIVE_PATH,
        REVIEW_SHA256,
        "review_fingerprint",
        REVIEW_FINGERPRINT,
        "review",
    )
    _verify_plan(payload, base.payload)
    configurations = _configurations(payload)
    _verify_review(review)
    return IntradayEventRepricing001Plan(
        path=path,
        sha256=PLAN_SHA256,
        plan_fingerprint=PLAN_FINGERPRINT,
        review_path=review_path,
        review_sha256=REVIEW_SHA256,
        review_fingerprint=REVIEW_FINGERPRINT,
        calendar_sha256=CALENDAR_SHA256,
        calendar_fingerprint=CALENDAR_FINGERPRINT,
        source_evidence_sha256=SOURCE_EVIDENCE_SHA256,
        source_evidence_fingerprint=SOURCE_EVIDENCE_FINGERPRINT,
        payload=payload,
        authority=_AUTHORITY,
        events=base.events,
        periods=base.periods,
        configurations=configurations,
    )


def _verify_plan(payload: Mapping[str, Any], base: Mapping[str, Any]) -> None:
    inheritance = _mapping(payload.get("inheritance"), "inheritance")
    expected_base = {
        "path": "config/research/intraday-event-drift-001-plan-v1.json",
        "sha256": "c0dade2573405ddcd38d88814c10a27c3caae11bfb925a21179f6741cc20233c",
        "fingerprint": "73933d470feb52c1135746ab57db742019077b8b39e8e2545e9aba37c9a8d838",
    }
    expected_review = {
        "path": "config/research/intraday-event-drift-001-plan-independent-review-v1.json",
        "sha256": "25e92a85cee47aa261b4a85dce57666effbfbe329c203d3ac78df7b5bba9df96",
        "fingerprint": "0a464aca264ad4a8583d12fc4912898461ecf9e6121a1119322229e12bfb4077",
    }
    if (
        payload.get("schema_version") != "intraday-event-repricing-001-research-plan-v1"
        or payload.get("program_id") != PROGRAM_ID
        or payload.get("status") != "prospective-frozen-before-strategy-implementation-or-results"
        or payload.get("starting_main") != "1113ede80481edc538c9fd2ef93307555f1dbd34"
        or payload.get("authority") != _AUTHORITY
        or inheritance.get("base_plan") != expected_base
        or inheritance.get("base_plan_review") != expected_review
        or inheritance.get("inherited_exact_sections")
        != [
            "chronology",
            "data",
            "execution",
            "frozen_dependencies",
            "controlled_evaluation",
            "protected_boundaries",
        ]
        or any(
            section in payload
            for section in ("chronology", "data", "execution", "frozen_dependencies")
        )
        or _mapping(payload.get("controlled_evaluation"), "controlled evaluation")
        != _mapping(base.get("controlled_evaluation"), "base controlled evaluation")
        or _mapping(payload.get("protected_boundaries"), "protected boundaries")
        != _mapping(base.get("protected_boundaries"), "base protected boundaries")
        or any(
            value is not False
            for value in _mapping(
                payload.get("protected_boundaries"), "protected boundaries"
            ).values()
            if isinstance(value, bool)
        )
    ):
        raise ValueError("Event Repricing 001 plan inheritance or authority differs")
    contract = _mapping(payload.get("strategy_contract"), "strategy contract")
    parameters = _mapping(contract.get("parameters"), "strategy parameters")
    fixed = _mapping(parameters.get("fixed"), "fixed strategy parameters")
    runtime = _mapping(payload.get("runtime"), "runtime")
    budget = _mapping(payload.get("search_budget"), "search budget")
    if (
        contract.get("strategy_id") != "scheduled-event-relative-leader-continuation-v1"
        or contract.get("event_sessions_only") is not True
        or contract.get("long_only") is not True
        or contract.get("shorting") is not False
        or contract.get("leverage") is not False
        or contract.get("reentry_allowed") is not False
        or contract.get("reaction_measurement")
        != (
            "After reaction_bars=N bars fully complete, compute 10,000 * ((QQQ bar[N-1].close "
            "/ QQQ bar[0].open) - (SPY bar[N-1].close / SPY bar[0].open))."
        )
        or contract.get("activation_rule")
        != (
            "Activate once when the absolute signed reaction is at least "
            "minimum_relative_reaction_bps. An exact zero or sub-threshold reaction remains flat."
        )
        or contract.get("leader_action")
        != "The strategy replay targets only the leader at weight 0.5 and the laggard at zero."
        or contract.get("arm_ids") != ["leader", "laggard-control"]
        or contract.get("exit_rule")
        != (
            "For reaction_bars=N, target the active symbol flat after completed regular-session "
            "bar index N+23. Scenario delay d fills at index N+23+d, exactly 24 five-minute "
            "intervals "
            "after the entry fill at index N-1+d."
        )
        or fixed
        != {
            "active_symbol_weight": "0.5",
            "holding_bars": 24,
            "reentry_allowed": False,
            "leader_and_laggard_control_are_separate_run_specifications": True,
        }
        or runtime.get("default_worker_count") != 4
        or runtime.get("maximum_infrastructure_attempts") != 3
        or budget.get("total_maximum_run_specifications") != 244
        or budget.get("maximum_total_attempts") != 732
        or sum(
            _mapping(budget.get(name), name).get("run_specifications", 0)
            for name in (
                "discovery_maximum",
                "walk_forward_maximum",
                "stress_and_delay_maximum",
                "immediate_neighbor_maximum",
            )
        )
        != 244
    ):
        raise ValueError("Event Repricing 001 strategy or budget differs")


def _configurations(payload: Mapping[str, Any]) -> tuple[EventRepricingConfiguration, ...]:
    contract = _mapping(payload.get("strategy_contract"), "strategy contract")
    parameters = _mapping(contract.get("parameters"), "strategy parameters")
    raw = _list_of_mappings(parameters.get("candidates"), "candidates")
    expected = [
        (f"ier001-a{row:02d}-b{column:02d}", reaction, Decimal(threshold))
        for row, reaction in enumerate((3, 6, 12), 1)
        for column, threshold in enumerate(("5", "10", "20"), 1)
    ]
    configurations = tuple(
        EventRepricingConfiguration(
            item["candidate_id"],
            item["reaction_bars"],
            Decimal(item["minimum_relative_reaction_bps"]),
            tuple(item["neighbor_ids"]),
        )
        for item in raw
    )
    by_id = {item.candidate_id: item for item in configurations}
    edges = {
        (item.candidate_id, neighbor) for item in configurations for neighbor in item.neighbor_ids
    }
    if (
        len(configurations) != 9
        or [
            (item.candidate_id, item.reaction_bars, item.minimum_relative_reaction_bps)
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
        or len(edges) != 24
        or len({tuple(sorted(edge)) for edge in edges}) != 12
    ):
        raise ValueError("Event Repricing 001 candidate graph differs")
    return configurations


def _verify_review(review: Mapping[str, Any]) -> None:
    reviewed_plan = _mapping(review.get("reviewed_plan"), "reviewed plan")
    verification = _mapping(review.get("verification"), "review verification")
    if (
        review.get("schema_version") != "intraday-event-repricing-001-plan-independent-review-v1"
        or review.get("review_id") != "intraday-event-repricing-001-plan-independent-review-v1"
        or review.get("status") != "passed-before-strategy-implementation-or-results"
        or review.get("verdict") != "pass"
        or review.get("findings") != []
        or review.get("authority") != _REVIEW_AUTHORITY
        or reviewed_plan
        != {
            "program_id": PROGRAM_ID,
            "path": PLAN_RELATIVE_PATH.as_posix(),
            "sha256": PLAN_SHA256,
            "plan_fingerprint": PLAN_FINGERPRINT,
        }
        or verification.get("candidate_count") != 9
        or verification.get("undirected_neighbor_edge_count") != 12
        or verification.get("maximum_run_specifications") != 244
        or verification.get("maximum_infrastructure_attempts") != 732
    ):
        raise ValueError("Event Repricing 001 independent review differs")


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
        raise ValueError(f"Event Repricing 001 {label} SHA-256 differs")
    try:
        payload = _mapping(json.loads(raw), label)
    except json.JSONDecodeError as error:
        raise ValueError(f"Event Repricing 001 {label} is invalid JSON") from error
    unsigned = dict(payload)
    if (
        unsigned.pop(fingerprint_key, None) != expected_fingerprint
        or fingerprint(unsigned) != expected_fingerprint
    ):
        raise ValueError(f"Event Repricing 001 {label} fingerprint differs")
    return path, payload


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"Event Repricing 001 {label} must be an object")
    return value


def _list_of_mappings(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"Event Repricing 001 {label} must be a list")
    return [_mapping(item, label) for item in value]
