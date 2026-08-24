"""Strict frozen-artifact loader for Intraday Event Opening Breakout 001."""

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

PROGRAM_ID = "intraday-event-opening-breakout-001"
PLAN_RELATIVE_PATH = Path("config/research/intraday-event-opening-breakout-001-plan-v1.json")
REVIEW_RELATIVE_PATH = Path(
    "config/research/intraday-event-opening-breakout-001-plan-independent-review-v1.json"
)
PLAN_SHA256 = "73ea48a3e2c250db93aca0c7ebef16b5480e118ab9577684089147bb318dfd27"
PLAN_FINGERPRINT = "3164757c9f91a1318d48607b24bdaa1c4f3e5439a9657d1b31b0cc32d8163b68"
REVIEW_SHA256 = "c3c581503fca8f78af0bafb30402ac78a2b6dce06f46b16c39a5e72efd26c550"
REVIEW_FINGERPRINT = "92f20b1648dba189130c0980e427e1364d0f7fecb8f52166ddc933ac165db540"
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
class EventOpeningBreakoutConfiguration:
    candidate_id: str
    breakout_buffer_bps: Decimal
    neighbor_ids: tuple[str, ...]


@dataclass(frozen=True)
class IntradayEventOpeningBreakout001Plan:
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
    configurations: tuple[EventOpeningBreakoutConfiguration, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "authority", MappingProxyType(dict(self.authority)))

    @property
    def eligible_events(self) -> tuple[EventDriftEvent, ...]:
        return tuple(event for event in self.events if event.eligible)

    @property
    def excluded_events(self) -> tuple[EventDriftEvent, ...]:
        return tuple(event for event in self.events if not event.eligible)


def load_intraday_event_opening_breakout_001_plan(
    repository: Path,
) -> IntradayEventOpeningBreakout001Plan:
    """Load only the exact reviewed plan and explicit Event Drift base inputs."""
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
    return IntradayEventOpeningBreakout001Plan(
        path,
        PLAN_SHA256,
        PLAN_FINGERPRINT,
        review_path,
        REVIEW_SHA256,
        REVIEW_FINGERPRINT,
        CALENDAR_SHA256,
        CALENDAR_FINGERPRINT,
        SOURCE_EVIDENCE_SHA256,
        SOURCE_EVIDENCE_FINGERPRINT,
        payload,
        _AUTHORITY,
        base.events,
        base.periods,
        configurations,
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
    boundaries = _mapping(payload.get("protected_boundaries"), "protected boundaries")
    if (
        payload.get("schema_version") != "intraday-event-opening-breakout-001-research-plan-v1"
        or payload.get("program_id") != PROGRAM_ID
        or payload.get("status") != "prospective-frozen-before-strategy-implementation-or-results"
        or payload.get("starting_main") != "b268b5d8e8eb1abb7334458b2abf554b7f0809f2"
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
        or any(key in payload for key in ("chronology", "data", "execution", "frozen_dependencies"))
        or _mapping(payload.get("controlled_evaluation"), "controlled evaluation")
        != _mapping(base.get("controlled_evaluation"), "base controlled evaluation")
        or boundaries != _mapping(base.get("protected_boundaries"), "base protected boundaries")
        or any(value is not False for value in boundaries.values() if isinstance(value, bool))
    ):
        raise ValueError("Event Opening Breakout 001 plan inheritance or authority differs")
    contract = _mapping(payload.get("strategy_contract"), "strategy contract")
    parameters = _mapping(contract.get("parameters"), "strategy parameters")
    fixed = _mapping(parameters.get("fixed"), "fixed strategy parameters")
    runtime = _mapping(payload.get("runtime"), "runtime")
    budget = _mapping(payload.get("search_budget"), "search budget")
    if (
        contract.get("strategy_id") != "scheduled-event-spy-opening-breakout-v1"
        or contract.get("event_sessions_only") is not True
        or contract.get("long_only") is not True
        or contract.get("shorting") is not False
        or contract.get("leverage") is not False
        or contract.get("reentry_allowed") is not False
        or contract.get("maximum_entries_per_event_session") != 1
        or contract.get("opening_range")
        != (
            "After bars 0 through 5 fully complete at 10:00 ET, set opening_range_high to the "
            "maximum SPY high across those six bars. The range never changes later in the session."
        )
        or contract.get("monitoring_rule")
        != (
            "Inspect SPY closes only after completed bars 6 through 11, from 10:05 through 10:30 "
            "ET. Activate at the first close greater than or equal to the frozen breakout "
            "threshold. A high-only breach, an earlier opening-range value, or a later close "
            "does not activate."
        )
        or contract.get("exit_rule")
        != (
            "Target SPY flat after completed bar index 29. Scenario delay d fills at bar index "
            "29+d, at 12:00, 12:05, or 12:10 ET. QQQ remains flat for the full run."
        )
        or fixed
        != {
            "active_symbol": "SPY",
            "active_symbol_weight": "0.5",
            "qqq_target_weight": "0",
            "opening_range_bars": 6,
            "monitor_start_bar_index": 6,
            "monitor_end_bar_index": 11,
            "exit_bar_index": 29,
            "close_confirmation": True,
            "reentry_allowed": False,
        }
        or runtime.get("default_worker_count") != 4
        or runtime.get("maximum_infrastructure_attempts") != 3
        or budget.get("total_maximum_run_specifications") != 46
        or budget.get("maximum_total_attempts") != 138
        or sum(
            _mapping(budget.get(name), name).get("run_specifications", 0)
            for name in (
                "discovery_maximum",
                "walk_forward_maximum",
                "stress_and_delay_maximum",
                "immediate_neighbor_maximum",
            )
        )
        != 46
    ):
        raise ValueError("Event Opening Breakout 001 strategy or budget differs")


def _configurations(payload: Mapping[str, Any]) -> tuple[EventOpeningBreakoutConfiguration, ...]:
    parameters = _mapping(
        _mapping(payload.get("strategy_contract"), "strategy contract").get("parameters"),
        "strategy parameters",
    )
    raw = _list_of_mappings(parameters.get("candidates"), "candidates")
    configurations = tuple(
        EventOpeningBreakoutConfiguration(
            item["candidate_id"], Decimal(item["breakout_buffer_bps"]), tuple(item["neighbor_ids"])
        )
        for item in raw
    )
    expected = [
        (f"ieb001-a{index:02d}", Decimal(buffer)) for index, buffer in enumerate(("2", "4", "8"), 1)
    ]
    by_id = {item.candidate_id: item for item in configurations}
    edges = {
        (item.candidate_id, neighbor) for item in configurations for neighbor in item.neighbor_ids
    }
    if (
        parameters.get("candidate_count") != 3
        or len(configurations) != 3
        or [(item.candidate_id, item.breakout_buffer_bps) for item in configurations] != expected
        or len(by_id) != 3
        or any(item.neighbor_ids != tuple(sorted(item.neighbor_ids)) for item in configurations)
        or any(
            neighbor not in by_id or item.candidate_id not in by_id[neighbor].neighbor_ids
            for item in configurations
            for neighbor in item.neighbor_ids
        )
        or len(edges) != 4
        or len({tuple(sorted(edge)) for edge in edges}) != 2
    ):
        raise ValueError("Event Opening Breakout 001 candidate graph differs")
    return configurations


def _verify_review(review: Mapping[str, Any]) -> None:
    reviewed_plan = _mapping(review.get("reviewed_plan"), "reviewed plan")
    verification = _mapping(review.get("verification"), "review verification")
    if (
        review.get("schema_version")
        != "intraday-event-opening-breakout-001-plan-independent-review-v1"
        or review.get("review_id")
        != "intraday-event-opening-breakout-001-plan-independent-review-v1"
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
        or verification.get("candidate_count") != 3
        or verification.get("undirected_neighbor_edge_count") != 2
        or verification.get("discovery_gate_count") != 11
        or verification.get("walk_forward_gate_count") != 16
        or verification.get("stress_scenario_count") != 4
        or verification.get("stress_gate_count") != 12
        or verification.get("neighbor_gate_count") != 2
        or verification.get("maximum_run_specifications") != 46
        or verification.get("maximum_infrastructure_attempts") != 138
        or verification.get("exact_byte_rereview") is not True
    ):
        raise ValueError("Event Opening Breakout 001 independent review differs")


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
        raise ValueError(f"Event Opening Breakout 001 {label} SHA-256 differs")
    try:
        payload = _mapping(json.loads(raw), label)
    except json.JSONDecodeError as error:
        raise ValueError(f"Event Opening Breakout 001 {label} is invalid JSON") from error
    unsigned = dict(payload)
    if (
        unsigned.pop(fingerprint_key, None) != expected_fingerprint
        or fingerprint(unsigned) != expected_fingerprint
    ):
        raise ValueError(f"Event Opening Breakout 001 {label} fingerprint differs")
    return path, payload


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"Event Opening Breakout 001 {label} must be an object")
    return value


def _list_of_mappings(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"Event Opening Breakout 001 {label} must be a list")
    return [_mapping(item, label) for item in value]
