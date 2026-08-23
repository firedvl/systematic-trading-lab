"""Strict frozen-artifact loader for Intraday Event Drift 001."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .fingerprints import fingerprint

PROGRAM_ID = "intraday-event-drift-001"
PLAN_RELATIVE_PATH = Path("config/research/intraday-event-drift-001-plan-v1.json")
CALENDAR_RELATIVE_PATH = Path("config/research/intraday-event-calendar-001-v1.json")
SOURCE_EVIDENCE_RELATIVE_PATH = Path(
    "config/research/intraday-event-calendar-001-source-evidence-v1.json"
)
REVIEW_RELATIVE_PATH = Path(
    "config/research/intraday-event-drift-001-plan-independent-review-v1.json"
)
PLAN_SHA256 = "c0dade2573405ddcd38d88814c10a27c3caae11bfb925a21179f6741cc20233c"
PLAN_FINGERPRINT = "73933d470feb52c1135746ab57db742019077b8b39e8e2545e9aba37c9a8d838"
CALENDAR_SHA256 = "fa413a30234c6b82394fcdbf99df94aa31ae38e2df12d58296bcbc03162a34ee"
CALENDAR_FINGERPRINT = "9992ee0a430abc0b59f49f6dd9e5178ff22d13a9dec5ad5de1d8578896ed2a78"
SOURCE_EVIDENCE_SHA256 = "c5f1ab34c92b10ac9c75d86a3c33c9f2a445eed022a48697edaa7dfd9eabee0a"
SOURCE_EVIDENCE_FINGERPRINT = "6616ed631b3d7e8e727b8cde85bf26e4c2cb5800812db745c327a71bf62192fd"
REVIEW_SHA256 = "25e92a85cee47aa261b4a85dce57666effbfbe329c203d3ac78df7b5bba9df96"
REVIEW_FINGERPRINT = "0a464aca264ad4a8583d12fc4912898461ecf9e6121a1119322229e12bfb4077"

_OTHER_FROZEN_DEPENDENCIES = (
    (
        Path("config/research/intraday-execution-cost-model-001-v1.json"),
        "a9e6c2b86c6623d73e089de591c55eeec0711fa55f0933a4e3ea9a1c0c2392af",
        "model_fingerprint",
        "94fc3ba4663b422fbb0dc0cce7e3d78a7ba81f22d71d5fa986ab6847b7925bb4",
        "execution cost model",
    ),
    (
        Path("config/research/intraday-execution-cost-model-001-independent-review-v1.json"),
        "fb197856b9229349e5de4bca742f328a8f1e5e53f9558dfd7324744e91a795aa",
        "review_fingerprint",
        "8ade5190bb64330af037f88bf0911ed3cdb04578ca7a6d6e27a5fa6d651349b2",
        "execution cost review",
    ),
    (
        Path("config/research/intraday-exposed-002-data-binding-v1.json"),
        "3d6a5dde3b05369ceeb1e3be5b1f47e73a541c74eed184e1850945ee56890769",
        "binding_fingerprint",
        "b6849987e7673c4073272ec891e7f7118b91eba6926aa4c16f262162f529ea9d",
        "source data binding",
    ),
    (
        Path("config/research/intraday-exposed-005-june-disposition-v1.json"),
        "af6aea5e8d7bd8360aa6af4ddc31e1e67a1be48476f6c8ab13197fe12515b3c0",
        "disposition_fingerprint",
        "6dad6480dc3b0379017d582bb2f29fc562f41379bb3065855c55eadf51f025dd",
        "June disposition",
    ),
)

_PLAN_AUTHORITY = {
    "strategy_results": False,
    "research_qualification": False,
    "controlled_evaluation": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}
_CALENDAR_AUTHORITY = {"market_data_acquisition": False, **_PLAN_AUTHORITY}
_REVIEW_AUTHORITY = {
    "strategy_execution": False,
    "controlled_evaluation": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}
_EXPECTED_EXCLUSIONS = {
    "bls-empsit-2026-02-11": "excluded-source-causality-unproven",
    "bls-empsit-2026-04-03": "excluded-xnys-closed",
}
_EXPECTED_PERIOD_COUNTS = (10, 4, 6, 5, 3)


@dataclass(frozen=True)
class EventDriftEvent:
    event_id: str
    release_name: str
    scheduled_utc: str
    xnys_session: str | None
    session_open_utc: str | None
    session_close_utc: str | None
    disposition: str

    @property
    def eligible(self) -> bool:
        return self.disposition in {"eligible", "eligible-early-close"}


@dataclass(frozen=True)
class EventDriftPeriod:
    period_id: str
    context_start: datetime
    evaluation_start: datetime
    evaluation_end: datetime
    session_count: int
    eligible_event_count: int


@dataclass(frozen=True)
class EventDriftConfiguration:
    candidate_id: str
    reaction_bars: int
    minimum_reaction_bps: Decimal
    neighbor_ids: tuple[str, ...]


@dataclass(frozen=True)
class IntradayEventDrift001Plan:
    path: Path
    sha256: str
    plan_fingerprint: str
    calendar_path: Path
    calendar_sha256: str
    calendar_fingerprint: str
    source_evidence_path: Path
    source_evidence_sha256: str
    source_evidence_fingerprint: str
    review_path: Path
    review_sha256: str
    review_fingerprint: str
    payload: Mapping[str, Any]
    authority: Mapping[str, bool]
    events: tuple[EventDriftEvent, ...]
    periods: tuple[EventDriftPeriod, ...]
    configurations: tuple[EventDriftConfiguration, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "authority", MappingProxyType(dict(self.authority)))

    @property
    def eligible_events(self) -> tuple[EventDriftEvent, ...]:
        return tuple(event for event in self.events if event.eligible)

    @property
    def excluded_events(self) -> tuple[EventDriftEvent, ...]:
        return tuple(event for event in self.events if not event.eligible)


def load_intraday_event_drift_001_plan(repository: Path) -> IntradayEventDrift001Plan:
    """Load the exact independently reviewed prospective Event Drift 001 inputs."""
    repository = repository.resolve()
    plan_path, plan = _load_fingerprinted(
        repository, PLAN_RELATIVE_PATH, PLAN_SHA256, "plan_fingerprint", PLAN_FINGERPRINT, "plan"
    )
    calendar_path, calendar = _load_fingerprinted(
        repository,
        CALENDAR_RELATIVE_PATH,
        CALENDAR_SHA256,
        "calendar_fingerprint",
        CALENDAR_FINGERPRINT,
        "calendar",
    )
    evidence_path, evidence = _load_fingerprinted(
        repository,
        SOURCE_EVIDENCE_RELATIVE_PATH,
        SOURCE_EVIDENCE_SHA256,
        "evidence_fingerprint",
        SOURCE_EVIDENCE_FINGERPRINT,
        "source evidence",
    )
    review_path, review = _load_fingerprinted(
        repository,
        REVIEW_RELATIVE_PATH,
        REVIEW_SHA256,
        "review_fingerprint",
        REVIEW_FINGERPRINT,
        "review",
    )
    _verify_plan(plan)
    _verify_frozen_dependency_artifacts(repository, plan)
    events = _verify_calendar_and_evidence(plan, calendar, evidence)
    periods = _periods(plan)
    _verify_period_event_attribution(events, periods)
    configurations = _configurations(plan)
    _verify_review(review)
    return IntradayEventDrift001Plan(
        plan_path,
        PLAN_SHA256,
        PLAN_FINGERPRINT,
        calendar_path,
        CALENDAR_SHA256,
        CALENDAR_FINGERPRINT,
        evidence_path,
        SOURCE_EVIDENCE_SHA256,
        SOURCE_EVIDENCE_FINGERPRINT,
        review_path,
        REVIEW_SHA256,
        REVIEW_FINGERPRINT,
        plan,
        _PLAN_AUTHORITY,
        events,
        periods,
        configurations,
    )


def _verify_plan(plan: Mapping[str, Any]) -> None:
    dependencies = _mapping(plan.get("frozen_dependencies"), "plan frozen dependencies")
    if (
        plan.get("schema_version") != "intraday-event-drift-001-research-plan-v1"
        or plan.get("program_id") != PROGRAM_ID
        or plan.get("status") != "prospective-frozen-before-strategy-implementation-or-results"
        or plan.get("starting_main") != "2e150e2bd89ad680d69ab4b9a2f32c82eec60814"
        or plan.get("authority") != _PLAN_AUTHORITY
        or dependencies.get("event_calendar")
        != {
            "path": CALENDAR_RELATIVE_PATH.as_posix(),
            "calendar_id": "intraday-event-calendar-001-v1",
            "sha256": CALENDAR_SHA256,
            "fingerprint": CALENDAR_FINGERPRINT,
            "eligible_event_count": 28,
            "excluded_event_count": 2,
            "independent_causality_review_required": True,
        }
        or dependencies.get("event_source_evidence")
        != {
            "path": SOURCE_EVIDENCE_RELATIVE_PATH.as_posix(),
            "evidence_id": "intraday-event-calendar-001-source-evidence-v1",
            "sha256": SOURCE_EVIDENCE_SHA256,
            "fingerprint": SOURCE_EVIDENCE_FINGERPRINT,
            "event_count": 30,
            "release_content_or_market_results_used": False,
        }
        or _mapping(plan.get("protected_boundaries"), "protected boundaries").get(
            "maximum_market_timestamp"
        )
        != "2026-05-29T19:55:00Z"
        or any(
            _mapping(plan.get("protected_boundaries"), "protected boundaries").get(key) is not False
            for key in (
                "june_market_data_or_results",
                "intraday_v3_data_or_results",
                "daily_2018_2019_data_or_results",
                "paper_or_broker_state",
                "strategic_allocation_21",
                "live_execution",
                "partial_result_adaptation",
            )
        )
        or _mapping(plan.get("runtime"), "runtime").get("default_worker_count") != 4
        or _mapping(plan.get("runtime"), "runtime").get("maximum_infrastructure_attempts") != 3
        or _mapping(plan.get("controlled_evaluation"), "controlled evaluation").get("range_status")
        != "none-eligible"
    ):
        raise ValueError("Event Drift 001 plan binding differs")


def _verify_calendar_and_evidence(
    plan: Mapping[str, Any], calendar: Mapping[str, Any], evidence: Mapping[str, Any]
) -> tuple[EventDriftEvent, ...]:
    if (
        calendar.get("schema_version") != "scheduled-event-calendar-v1"
        or calendar.get("calendar_id") != "intraday-event-calendar-001-v1"
        or calendar.get("status") != "prospective-frozen-before-strategy-implementation-or-results"
        or calendar.get("authority") != _CALENDAR_AUTHORITY
        or evidence.get("schema_version") != "scheduled-event-source-evidence-v1"
        or evidence.get("evidence_id") != "intraday-event-calendar-001-source-evidence-v1"
        or evidence.get("status")
        != "prospective-source-evidence-before-strategy-implementation-or-results"
        or evidence.get("authority") != _CALENDAR_AUTHORITY
    ):
        raise ValueError("Event Drift 001 calendar or source evidence identity differs")
    calendar_events = _list_of_mappings(calendar.get("events"), "calendar events")
    evidence_events = _list_of_mappings(evidence.get("event_evidence"), "source evidence events")
    if len(calendar_events) != 30 or len(evidence_events) != 30:
        raise ValueError("Event Drift 001 source event count differs")
    evidence_by_id = {item.get("event_id"): item for item in evidence_events}
    if len(evidence_by_id) != 30 or set(evidence_by_id) != {
        item.get("event_id") for item in calendar_events
    }:
        raise ValueError("Event Drift 001 calendar/evidence identities differ")
    events = tuple(_event(item) for item in calendar_events)
    eligible = tuple(event for event in events if event.eligible)
    if (
        len(eligible) != 28
        or len({event.xnys_session for event in eligible}) != 28
        or any(event.xnys_session is None for event in eligible)
        or {event.event_id: event.disposition for event in events if not event.eligible}
        != _EXPECTED_EXCLUSIONS
        or _mapping(calendar.get("counts"), "calendar counts").get("eligible_events") != 28
        or _mapping(calendar.get("counts"), "calendar counts").get("excluded_events") != 2
    ):
        raise ValueError("Event Drift 001 calendar eligibility differs")
    for event in events:
        proof = evidence_by_id[event.event_id]
        if proof.get("scheduled_utc") != event.scheduled_utc:
            raise ValueError("Event Drift 001 event schedule evidence differs")
        if event.eligible and (
            proof.get("proof_type") != "archived-official-schedule-before-market-open"
            or proof.get("source_capture_before_boundary") is not True
            or proof.get("xnys_open_utc") != event.session_open_utc
        ):
            raise ValueError("Event Drift 001 eligible event causality differs")
    return events


def _verify_frozen_dependency_artifacts(repository: Path, plan: Mapping[str, Any]) -> None:
    dependencies = _mapping(plan.get("frozen_dependencies"), "plan frozen dependencies")
    expected_dependency_names = (
        "execution_cost_model",
        "execution_cost_review",
        "source_data_binding",
        "june_disposition",
    )
    for dependency_name, expected in zip(
        expected_dependency_names, _OTHER_FROZEN_DEPENDENCIES, strict=True
    ):
        path, sha256, fingerprint_key, expected_fingerprint, label = expected
        dependency = _mapping(dependencies.get(dependency_name), dependency_name)
        if (
            dependency.get("path") != path.as_posix()
            or dependency.get("sha256") != sha256
            or dependency.get("fingerprint") != expected_fingerprint
        ):
            raise ValueError(f"Event Drift 001 {label} dependency differs")
        _load_fingerprinted(repository, path, sha256, fingerprint_key, expected_fingerprint, label)


def _periods(plan: Mapping[str, Any]) -> tuple[EventDriftPeriod, ...]:
    chronology = _mapping(plan.get("chronology"), "chronology")
    raw_periods = [_mapping(chronology.get("discovery"), "discovery chronology")]
    raw_periods.extend(_list_of_mappings(chronology.get("walk_forward"), "walk-forward chronology"))
    periods = tuple(
        EventDriftPeriod(
            item["period_id"],
            _timestamp(item.get("context_start"), "period context start"),
            _timestamp(item.get("evaluation_start"), "period evaluation start"),
            _timestamp(item.get("evaluation_end"), "period evaluation end"),
            item["session_count"],
            item["eligible_event_count"],
        )
        for item in raw_periods
    )
    if (
        len(periods) != 5
        or tuple(item.eligible_event_count for item in periods) != _EXPECTED_PERIOD_COUNTS
    ):
        raise ValueError("Event Drift 001 chronology differs")
    return periods


def _verify_period_event_attribution(
    events: tuple[EventDriftEvent, ...], periods: tuple[EventDriftPeriod, ...]
) -> None:
    observed = tuple(
        sum(
            event.eligible
            and event.session_open_utc is not None
            and period.evaluation_start
            <= _timestamp(event.session_open_utc, "event session open")
            <= period.evaluation_end
            for event in events
        )
        for period in periods
    )
    if observed != _EXPECTED_PERIOD_COUNTS or observed != tuple(
        period.eligible_event_count for period in periods
    ):
        raise ValueError("Event Drift 001 period event attribution differs")


def _configurations(plan: Mapping[str, Any]) -> tuple[EventDriftConfiguration, ...]:
    parameters = _mapping(
        _mapping(plan.get("strategy_contract"), "strategy contract").get("parameters"), "parameters"
    )
    raw = _list_of_mappings(parameters.get("candidates"), "candidates")
    expected = [
        (f"ied001-a{row:02d}-b{column:02d}", reaction, Decimal(minimum))
        for row, reaction in enumerate((3, 6, 12), 1)
        for column, minimum in enumerate(("10", "20", "40"), 1)
    ]
    configurations = tuple(
        EventDriftConfiguration(
            item["candidate_id"],
            item["reaction_bars"],
            Decimal(item["minimum_reaction_bps"]),
            tuple(item["neighbor_ids"]),
        )
        for item in raw
    )
    if (
        len(configurations) != 9
        or [
            (item.candidate_id, item.reaction_bars, item.minimum_reaction_bps)
            for item in configurations
        ]
        != expected
        or any(item.neighbor_ids != tuple(sorted(item.neighbor_ids)) for item in configurations)
    ):
        raise ValueError("Event Drift 001 candidate grid differs")
    by_id = {item.candidate_id: item for item in configurations}
    edges = {
        (item.candidate_id, neighbor) for item in configurations for neighbor in item.neighbor_ids
    }
    if (
        len(by_id) != 9
        or any(
            neighbor not in by_id or item.candidate_id not in by_id[neighbor].neighbor_ids
            for item in configurations
            for neighbor in item.neighbor_ids
        )
        or len(edges) != 24
        or any((right, left) not in edges for left, right in edges)
    ):
        raise ValueError("Event Drift 001 neighbor graph differs")
    return configurations


def _verify_review(review: Mapping[str, Any]) -> None:
    if (
        review.get("schema_version") != "intraday-event-drift-001-plan-independent-review-v1"
        or review.get("review_id") != "intraday-event-drift-001-plan-independent-review-v1"
        or review.get("status") != "passed-before-implementation-or-strategy-results"
        or review.get("verdict") != "pass"
        or review.get("findings") != []
        or review.get("authority") != _REVIEW_AUTHORITY
        or _mapping(review.get("reviewed_plan"), "reviewed plan")
        != {
            "path": PLAN_RELATIVE_PATH.as_posix(),
            "program_id": PROGRAM_ID,
            "sha256": PLAN_SHA256,
            "plan_fingerprint": PLAN_FINGERPRINT,
        }
        or _mapping(review.get("verification"), "review verification").get("source_event_count")
        != 30
        or _mapping(review.get("verification"), "review verification").get("eligible_event_count")
        != 28
        or _mapping(review.get("verification"), "review verification").get(
            "undirected_neighbor_edge_count"
        )
        != 12
    ):
        raise ValueError("Event Drift 001 independent review differs")


def _event(item: Mapping[str, Any]) -> EventDriftEvent:
    required = (
        "event_id",
        "release_name",
        "scheduled_utc",
        "xnys_session",
        "session_open_utc",
        "session_close_utc",
        "disposition",
    )
    if any(key not in item for key in required):
        raise ValueError("Event Drift 001 calendar event schema differs")
    return EventDriftEvent(*(item[key] for key in required))


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
        raise ValueError(f"Event Drift 001 {label} SHA-256 differs")
    try:
        payload = _mapping(json.loads(raw), label)
    except json.JSONDecodeError as error:
        raise ValueError(f"Event Drift 001 {label} is invalid JSON") from error
    unsigned = dict(payload)
    if (
        unsigned.pop(fingerprint_key, None) != expected_fingerprint
        or fingerprint(unsigned) != expected_fingerprint
    ):
        raise ValueError(f"Event Drift 001 {label} fingerprint differs")
    return path, payload


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"Event Drift 001 {label} must be an object")
    return value


def _list_of_mappings(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"Event Drift 001 {label} must be a list")
    return [_mapping(item, label) for item in value]


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"Event Drift 001 {label} must be a UTC timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    offset = result.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError(f"Event Drift 001 {label} must be a UTC timestamp")
    return result
