"""Strict loader for the frozen Intraday Fed Policy Absorption 001 controls."""

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

PROGRAM_ID = "intraday-fed-policy-absorption-001"
PLAN_RELATIVE_PATH = Path("config/research/intraday-fed-policy-absorption-001-plan-v1.json")
CALENDAR_RELATIVE_PATH = Path("config/research/intraday-fed-policy-absorption-001-calendar-v1.json")
SOURCE_EVIDENCE_RELATIVE_PATH = Path(
    "config/research/intraday-fed-policy-absorption-001-source-evidence-v1.json"
)
REVIEW_RELATIVE_PATH = Path(
    "config/research/intraday-fed-policy-absorption-001-plan-calendar-independent-review-v1.json"
)
SOURCE_STATE_RELATIVE_PATH = Path(
    "docs/research-campaigns/intraday-autonomous-research-001-state-v2-revision-005.json"
)
STATE_RELATIVE_PATH = Path(
    "docs/research-campaigns/intraday-autonomous-research-001-state-v2-revision-006.json"
)
ATTESTATION_RELATIVE_PATH = Path(
    "docs/research-campaigns/intraday-fed-policy-absorption-001-pre-design-attestation-v2.json"
)
FAILURE_V1_RELATIVE_PATH = Path(
    "docs/research-campaigns/intraday-fed-policy-absorption-001-preplan-control-failure-v1.json"
)
FAILURE_V2_RELATIVE_PATH = Path(
    "docs/research-campaigns/intraday-fed-policy-absorption-001-preplan-control-failure-v2.json"
)
PLAN_SHA256 = "a3cd20e325f2e9eb6bc794df7a93db3763dab8e55d2fc1e02816a8480907c111"
PLAN_FINGERPRINT = "99d03036512b3a8b03f38774e05779982379b1e956906a2ee36f612b52f20140"
CALENDAR_SHA256 = "8bcfd05031b44e2c31861c43aa2b8130d609c82fca9aeec10804809c37a01c97"
CALENDAR_FINGERPRINT = "54c937bbb42703213efdf14dc4becb50bc0f757bb6f16388254550e12f0c93ba"
SOURCE_EVIDENCE_SHA256 = "1d72b74a04eadba87eb178fd7d67dc644c18d31b926f78e7a48f6f9c38f012c8"
SOURCE_EVIDENCE_FINGERPRINT = "ed4dc2c9f638a4ef04da7d292732ee653d0040a5c844a54f90efc588d3005a7b"
REVIEW_SHA256 = "7f6216324a135f9c910edc6257ef1b408ced8d6b33feb9e43d9cd524fee66014"
REVIEW_FINGERPRINT = "831e85f7e7228652f06d4b5bbe1b3822333d0e53e1ce2d97852ede1a24a262aa"
SOURCE_STATE_SHA256 = "cd68f08b0b95839d41672a5df024e8867759911830f28d0a3d255c61c2643883"
SOURCE_STATE_FINGERPRINT = "c6eaa1acc6af58af2d0f4a937c89ad95690ee8743ec998526b5f16ebdf7ea9af"
STATE_SHA256 = "7c414a92e22ca4ceead8d1cde5ad3429a8a62c5a5bd3ade7f88ce72c38f1b891"
STATE_FINGERPRINT = "4cc76196c71713fbf56a92cd2495a9a8cc137eb749da0ee0511a429144cc6b73"
ATTESTATION_SHA256 = "f95c19237ec9e4f6d854fe6f4fe5aa31ba289f962e1d302ef679f73667256b47"
ATTESTATION_FINGERPRINT = "174dae849dd5d20c0e2775d798b855d54e07030a140872a029b748741ea2467e"
FAILURE_V1_SHA256 = "364aa03c8b68beecb205ffe37f97fa0e68c1980dc4670ae010bdd65ac488ed4e"
FAILURE_V1_FINGERPRINT = "e2a8919220b5ef409e9a2eb6ddfe33a65809ebf62e953c0c7554e42b800ba56e"
FAILURE_V2_SHA256 = "9c3840f1992facb24b5acbbd406e33a9c984a75e47621da88bc7f5dfbab90a76"
FAILURE_V2_FINGERPRINT = "80ab56bf4b4158f92aef4b099c1f51c68f29f4f7fcf4b62f1cc3f84090bad640"

_AUTONOMOUS_PROGRAM = {
    "path": "config/research/intraday-autonomous-research-001-program-v1.json",
    "sha256": "dda9b38a95970660ec2244e540de649586ed940e037eaa49a3b11c760480d1f9",
    "fingerprint": "734282e42b991889aa2dbce220b46807debe0114309e93cf4ca8d89bf0d0c14f",
}
_AUTONOMOUS_REVIEW = {
    "path": "config/research/intraday-autonomous-research-001-program-independent-review-v1.json",
    "sha256": "1731794543d13306f34462016d376966d47ae8354fa337144889c7bea5c738db",
    "fingerprint": "50424b9e5c07a95351af93e560859293768e34959d01f816f0f63042302497c0",
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
}
_JUNE_DISPOSITION = {
    "path": "config/research/intraday-exposed-005-june-disposition-v1.json",
    "sha256": "af6aea5e8d7bd8360aa6af4ddc31e1e67a1be48476f6c8ab13197fe12515b3c0",
    "fingerprint": "6dad6480dc3b0379017d582bb2f29fc562f41379bb3065855c55eadf51f025dd",
}
_ATTESTATION = {
    "path": ATTESTATION_RELATIVE_PATH.as_posix(),
    "sha256": ATTESTATION_SHA256,
    "fingerprint": ATTESTATION_FINGERPRINT,
}
_FAILURE_V1 = {
    "path": FAILURE_V1_RELATIVE_PATH.as_posix(),
    "sha256": FAILURE_V1_SHA256,
    "fingerprint": FAILURE_V1_FINGERPRINT,
}
_FAILURE_V2 = {
    "path": FAILURE_V2_RELATIVE_PATH.as_posix(),
    "sha256": FAILURE_V2_SHA256,
    "fingerprint": FAILURE_V2_FINGERPRINT,
}

_AUTHORITY = {
    "strategy_implementation": False,
    "strategy_execution": False,
    "strategy_results": False,
    "market_data_read": False,
    "research_qualification": False,
    "controlled_evaluation": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}
_PERIOD_COUNTS = (6, 3, 2, 3, 1)
_ATTESTATION_STATUS = (
    "prospective-source-bound-before-third-replacement-design-implementation-"
    "reservation-market-data-read-or-results"
)
_FAILURE_V1_STATUS = (
    "terminal-rejected-draft-before-implementation-reservation-market-data-read-or-results"
)
_FAILURE_V2_STATUS = (
    "terminal-second-rejected-plan-before-commit-implementation-reservation-"
    "market-data-read-or-results"
)


@dataclass(frozen=True)
class FedPolicyAbsorptionEvent:
    event_id: str
    publication_class: str
    scheduled_utc: datetime
    scheduled_local: datetime
    session: str
    period_id: str

    @property
    def xnys_session(self) -> str:
        return self.session

    @property
    def pre_publication_bar_index(self) -> int:
        return 53

    @property
    def publication_bar_index(self) -> int:
        return 54

    @property
    def final_bar_index(self) -> int:
        return 77


FedPolicyEvent = FedPolicyAbsorptionEvent


@dataclass(frozen=True)
class FedPolicyAbsorptionPeriod:
    period_id: str
    context_start: datetime
    evaluation_start: datetime
    evaluation_end: datetime
    session_count: int
    eligible_event_count: int


@dataclass(frozen=True)
class FedPolicyAbsorptionConfiguration:
    candidate_id: str
    observation_horizon_bars: int
    minimum_joint_reaction_bps: Decimal
    neighbor_ids: tuple[str, ...]


@dataclass(frozen=True)
class IntradayFedPolicyAbsorption001Plan:
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
    source_state_path: Path
    source_state_sha256: str
    source_state_fingerprint: str
    state_path: Path
    state_sha256: str
    state_fingerprint: str
    payload: Mapping[str, Any]
    source_state: Mapping[str, Any]
    state: Mapping[str, Any]
    authority: Mapping[str, bool]
    events: tuple[FedPolicyAbsorptionEvent, ...]
    periods: tuple[FedPolicyAbsorptionPeriod, ...]
    configurations: tuple[FedPolicyAbsorptionConfiguration, ...]

    def __post_init__(self) -> None:
        for field in ("payload", "source_state", "state"):
            object.__setattr__(self, field, _freeze(getattr(self, field)))
        object.__setattr__(self, "authority", MappingProxyType(dict(self.authority)))


def load_intraday_fed_policy_absorption_001_plan(
    repository: Path,
) -> IntradayFedPolicyAbsorption001Plan:
    """Load the exact Campaign 3 plan, calendar, evidence, and finding-free review."""
    repository = repository.resolve()
    path, payload = _load(
        repository, PLAN_RELATIVE_PATH, PLAN_SHA256, "plan_fingerprint", PLAN_FINGERPRINT
    )
    calendar_path, calendar = _load(
        repository,
        CALENDAR_RELATIVE_PATH,
        CALENDAR_SHA256,
        "calendar_fingerprint",
        CALENDAR_FINGERPRINT,
    )
    evidence_path, evidence = _load(
        repository,
        SOURCE_EVIDENCE_RELATIVE_PATH,
        SOURCE_EVIDENCE_SHA256,
        "evidence_fingerprint",
        SOURCE_EVIDENCE_FINGERPRINT,
    )
    review_path, review = _load(
        repository, REVIEW_RELATIVE_PATH, REVIEW_SHA256, "review_fingerprint", REVIEW_FINGERPRINT
    )
    source_state_path, source_state = _load(
        repository,
        SOURCE_STATE_RELATIVE_PATH,
        SOURCE_STATE_SHA256,
        "state_fingerprint",
        SOURCE_STATE_FINGERPRINT,
    )
    state_path, state = _load(
        repository, STATE_RELATIVE_PATH, STATE_SHA256, "state_fingerprint", STATE_FINGERPRINT
    )
    bound = _load_bound_artifacts(repository)
    events = _events(calendar, evidence)
    periods = _periods(payload, events)
    configurations = _configurations(payload)
    _verify_plan(payload, events, periods, configurations, bound)
    _verify_review(review)
    _verify_states(source_state, state)
    return IntradayFedPolicyAbsorption001Plan(
        path,
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
        source_state_path,
        SOURCE_STATE_SHA256,
        SOURCE_STATE_FINGERPRINT,
        state_path,
        STATE_SHA256,
        STATE_FINGERPRINT,
        payload,
        source_state,
        state,
        _AUTHORITY,
        events,
        periods,
        configurations,
    )


def _load(
    repository: Path, relative: Path, sha256: str, fingerprint_key: str, expected_fingerprint: str
) -> tuple[Path, Mapping[str, Any]]:
    path = repository / relative
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError(f"Fed Policy Absorption 001 {relative.name} SHA-256 differs")
    payload = json.loads(raw, object_pairs_hook=_no_duplicate_keys)
    if not isinstance(payload, dict) or payload.get(fingerprint_key) != expected_fingerprint:
        raise ValueError(f"Fed Policy Absorption 001 {relative.name} fingerprint field differs")
    preimage = dict(payload)
    preimage.pop(fingerprint_key)
    if fingerprint(preimage) != expected_fingerprint:
        raise ValueError(f"Fed Policy Absorption 001 {relative.name} canonical fingerprint differs")
    return path, payload


def _load_bound_artifacts(repository: Path) -> Mapping[str, Mapping[str, Any]]:
    specifications = {
        "autonomous_program": (_AUTONOMOUS_PROGRAM, "program_fingerprint"),
        "autonomous_review": (_AUTONOMOUS_REVIEW, "review_fingerprint"),
        "base_plan": (_BASE_PLAN, "plan_fingerprint"),
        "base_review": (_BASE_REVIEW, "review_fingerprint"),
        "cost_model": (_COST_MODEL, "model_fingerprint"),
        "cost_review": (_COST_REVIEW, "review_fingerprint"),
        "june_disposition": (_JUNE_DISPOSITION, "disposition_fingerprint"),
        "attestation": (_ATTESTATION, "attestation_fingerprint"),
        "failure_v1": (_FAILURE_V1, "failure_fingerprint"),
        "failure_v2": (_FAILURE_V2, "failure_fingerprint"),
    }
    values: dict[str, Mapping[str, Any]] = {}
    for name, (binding, fingerprint_key) in specifications.items():
        _, values[name] = _load(
            repository,
            Path(binding["path"]),
            binding["sha256"],
            fingerprint_key,
            binding["fingerprint"],
        )
    return MappingProxyType(values)


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _events(
    calendar: Mapping[str, Any], evidence: Mapping[str, Any]
) -> tuple[FedPolicyAbsorptionEvent, ...]:
    rows = calendar.get("events")
    evidence_rows = evidence.get("event_evidence")
    if (
        not isinstance(rows, list)
        or not isinstance(evidence_rows, list)
        or len(rows) != 15
        or len(evidence_rows) != 15
    ):
        raise ValueError("Fed Policy Absorption 001 calendar sample differs")
    evidence_identity = {
        (row.get("event_id"), row.get("publication_class"), row.get("scheduled_utc"))
        for row in evidence_rows
        if isinstance(row, dict)
    }
    events: list[FedPolicyAbsorptionEvent] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Fed Policy Absorption 001 calendar event differs")
        identity = (row.get("event_id"), row.get("publication_class"), row.get("scheduled_utc"))
        if (
            identity not in evidence_identity
            or row.get("disposition") != "eligible-full-xnys-session"
            or row.get("session_bar_count") != 78
            or (
                row.get("pre_publication_bar_index"),
                row.get("publication_bar_index"),
                row.get("final_bar_index"),
            )
            != (53, 54, 77)
        ):
            raise ValueError("Fed Policy Absorption 001 calendar binding differs")
        local = _timestamp(row.get("scheduled_local"))
        if local.hour != 14 or local.minute != 0:
            raise ValueError("Fed Policy Absorption 001 event clock differs")
        events.append(
            FedPolicyAbsorptionEvent(
                str(row["event_id"]),
                str(row["publication_class"]),
                _timestamp(row.get("scheduled_utc")),
                local,
                str(row["xnys_session"]),
                str(row["period_id"]),
            )
        )
    if (
        len({item.event_id for item in events}) != 15
        or len({item.session for item in events}) != 15
        or {item.publication_class for item in events}
        != {"fomc-meeting-minutes", "fomc-policy-statement"}
        or sum(item.publication_class == "fomc-meeting-minutes" for item in events) != 8
        or sum(item.publication_class == "fomc-policy-statement" for item in events) != 7
        or tuple(events)
        != tuple(sorted(events, key=lambda item: (item.scheduled_utc, item.event_id)))
    ):
        raise ValueError("Fed Policy Absorption 001 calendar identities differ")
    return tuple(events)


def _periods(
    payload: Mapping[str, Any], events: tuple[FedPolicyAbsorptionEvent, ...]
) -> tuple[FedPolicyAbsorptionPeriod, ...]:
    chronology = payload.get("chronology")
    if not isinstance(chronology, dict) or not isinstance(chronology.get("periods"), list):
        raise ValueError("Fed Policy Absorption 001 chronology differs")
    periods = tuple(
        FedPolicyAbsorptionPeriod(
            str(row["period_id"]),
            _timestamp(row.get("context_start")),
            _timestamp(row.get("evaluation_start")),
            _timestamp(row.get("evaluation_end")),
            int(row["session_count"]),
            int(row["eligible_event_count"]),
        )
        for row in chronology["periods"]
        if isinstance(row, dict)
    )
    if (
        len(periods) != 5
        or tuple(item.period_id for item in periods) != tuple(chronology.get("period_order", ()))
        or tuple(item.eligible_event_count for item in periods) != _PERIOD_COUNTS
        or tuple(sum(event.period_id == item.period_id for event in events) for item in periods)
        != _PERIOD_COUNTS
    ):
        raise ValueError("Fed Policy Absorption 001 period counts differ")
    return periods


def _configurations(payload: Mapping[str, Any]) -> tuple[FedPolicyAbsorptionConfiguration, ...]:
    strategy = payload.get("strategy_contract")
    parameters = strategy.get("parameters") if isinstance(strategy, dict) else None
    rows = parameters.get("candidates") if isinstance(parameters, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Fed Policy Absorption 001 candidate grid differs")
    configurations = tuple(
        FedPolicyAbsorptionConfiguration(
            str(row["candidate_id"]),
            int(row["observation_horizon_bars"]),
            Decimal(str(row["minimum_joint_reaction_bps"])),
            _neighbors(
                int(row["observation_horizon_bars"]),
                Decimal(str(row["minimum_joint_reaction_bps"])),
            ),
        )
        for row in rows
        if isinstance(row, dict)
    )
    expected = tuple(
        (f"fedabs-h{h:02d}-f{f:04d}", h, Decimal(f)) for h in (2, 4, 6) for f in (8, 16, 24)
    )
    if (
        tuple(
            (item.candidate_id, item.observation_horizon_bars, item.minimum_joint_reaction_bps)
            for item in configurations
        )
        != expected
    ):
        raise ValueError("Fed Policy Absorption 001 candidate order differs")
    return configurations


def _neighbors(horizon: int, floor: Decimal) -> tuple[str, ...]:
    if horizon not in range(1, 8) or floor not in {
        Decimal(item) for item in ("4", "8", "12", "16", "20", "24", "28")
    }:
        raise ValueError("Fed Policy Absorption 001 neighbor node differs")
    return (
        f"fedabs-h{horizon - 1:02d}-f{int(floor):04d}",
        f"fedabs-h{horizon + 1:02d}-f{int(floor):04d}",
        f"fedabs-h{horizon:02d}-f{int(floor - 4):04d}",
        f"fedabs-h{horizon:02d}-f{int(floor + 4):04d}",
    )


def _verify_plan(
    payload: Mapping[str, Any],
    events: tuple[FedPolicyAbsorptionEvent, ...],
    periods: tuple[FedPolicyAbsorptionPeriod, ...],
    configurations: tuple[FedPolicyAbsorptionConfiguration, ...],
    bound: Mapping[str, Mapping[str, Any]],
) -> None:
    strategy = payload.get("strategy_contract")
    arithmetic = payload.get("arithmetic")
    execution = payload.get("execution")
    budget = payload.get("search_budget")
    autonomous = payload.get("autonomous_program")
    source_state = payload.get("program_state_source")
    design = payload.get("design_provenance")
    inheritance = payload.get("inheritance")
    dependencies = payload.get("frozen_dependencies")
    if (
        payload.get("program_id") != PROGRAM_ID
        or payload.get("authority") != _AUTHORITY
        or autonomous
        != {
            "program_id": "intraday-autonomous-research-001",
            "campaign_index": 3,
            "maximum_run_specifications": 90,
            **_AUTONOMOUS_PROGRAM,
        }
        or not isinstance(source_state, dict)
        or source_state.get("path") != SOURCE_STATE_RELATIVE_PATH.as_posix()
        or source_state.get("sha256") != SOURCE_STATE_SHA256
        or source_state.get("fingerprint") != SOURCE_STATE_FINGERPRINT
        or source_state.get("state_revision") != 5
        or not isinstance(design, dict)
        or design.get("attestation") != _ATTESTATION
        or design.get("preserved_failures") != [_FAILURE_V1, _FAILURE_V2]
        or design.get("rejected_design_reuse") is not False
        or not isinstance(inheritance, dict)
        or inheritance.get("base_plan") != _BASE_PLAN
        or inheritance.get("base_plan_review") != _BASE_REVIEW
        or not isinstance(dependencies, dict)
        or dependencies.get("autonomous_program_review")
        != {**_AUTONOMOUS_REVIEW, "verdict": "pass"}
        or dependencies.get("execution_cost_model") != _COST_MODEL
        or dependencies.get("execution_cost_review") != {**_COST_REVIEW, "verdict": "pass"}
        or dependencies.get("june_disposition")
        != {**_JUNE_DISPOSITION, "range_status": "ineligible"}
        or not isinstance(strategy, dict)
        or strategy.get("strategy_id") != "intraday-fed-policy-absorption-v1"
        or strategy.get("reference_bar_index") != 53
        or strategy.get("publication_bar_index") != 54
        or strategy.get("no_signal_reason_priority")
        != ["both-below-floor", "spy-below-floor", "qqq-below-floor"]
        or not isinstance(arithmetic, dict)
        or arithmetic.get("decimal_context_precision") != 50
        or arithmetic.get("decimal_rounding") != "ROUND_HALF_EVEN"
        or not isinstance(execution, dict)
        or execution.get("exit_decision_index") != 74
        or execution.get("entry_fill_index_formula") != "53 + horizon + delay"
        or execution.get("exit_fill_indices") != {"delay-1": 75, "delay-2": 76, "delay-3": 77}
        or not isinstance(budget, dict)
        or budget.get("total_maximum_run_specifications") != 90
        or budget.get("maximum_total_attempts") != 270
        or len(events) != 15
        or len(periods) != 5
        or len(configurations) != 9
    ):
        raise ValueError("Fed Policy Absorption 001 frozen plan differs")
    campaigns = bound["autonomous_program"].get("campaigns")
    if (
        not isinstance(campaigns, list)
        or len(campaigns) != 3
        or campaigns[2].get("campaign_id") != PROGRAM_ID
        or campaigns[2].get("maximum_parent_candidates") != 9
        or campaigns[2].get("maximum_run_specifications") != 90
        or bound["autonomous_review"].get("verdict") != "pass"
        or bound["base_review"].get("verdict") != "pass"
        or bound["cost_review"].get("verdict") != "pass"
        or bound["june_disposition"].get("status") != "ineligible-before-strategy-results"
        or bound["attestation"].get("status") != _ATTESTATION_STATUS
        or bound["failure_v1"].get("status") != _FAILURE_V1_STATUS
        or bound["failure_v2"].get("status") != _FAILURE_V2_STATUS
    ):
        raise ValueError("Fed Policy Absorption 001 dependency binding differs")


def _verify_review(review: Mapping[str, Any]) -> None:
    reviewed = review.get("reviewed_inputs")
    expected = {
        "plan": {
            "path": PLAN_RELATIVE_PATH.as_posix(),
            "sha256": PLAN_SHA256,
            "fingerprint": PLAN_FINGERPRINT,
        },
        "attestation": _ATTESTATION,
        "autonomous_program": _AUTONOMOUS_PROGRAM,
        "autonomous_program_review": _AUTONOMOUS_REVIEW,
        "source_state": {
            "path": SOURCE_STATE_RELATIVE_PATH.as_posix(),
            "sha256": SOURCE_STATE_SHA256,
            "fingerprint": SOURCE_STATE_FINGERPRINT,
        },
        "calendar": {
            "path": CALENDAR_RELATIVE_PATH.as_posix(),
            "sha256": CALENDAR_SHA256,
            "fingerprint": CALENDAR_FINGERPRINT,
        },
        "source_evidence": {
            "path": SOURCE_EVIDENCE_RELATIVE_PATH.as_posix(),
            "sha256": SOURCE_EVIDENCE_SHA256,
            "fingerprint": SOURCE_EVIDENCE_FINGERPRINT,
        },
        "execution_cost_model": _COST_MODEL,
        "execution_cost_review": _COST_REVIEW,
        "preplan_failure_v1": _FAILURE_V1,
        "preplan_failure_v2": _FAILURE_V2,
    }
    verification = review.get("verification")
    if (
        review.get("schema_version")
        != "intraday-fed-policy-absorption-001-plan-calendar-independent-review-v1"
        or review.get("review_id")
        != "intraday-fed-policy-absorption-001-plan-calendar-independent-review-v1"
        or review.get("status")
        != "finding-free-before-implementation-reservation-market-data-read-or-results"
        or review.get("verdict") != "pass"
        or review.get("findings") != []
        or reviewed != expected
        or not isinstance(verification, dict)
        or verification.get("calendar_events") != 15
        or verification.get("unique_event_ids") != 15
        or verification.get("unique_sessions") != 15
        or verification.get("parents") != 9
        or verification.get("scenarios") != 6
        or verification.get("neighbors_per_parent") != 4
        or verification.get("run_specifications") != 90
        or verification.get("maximum_attempts") != 270
    ):
        raise ValueError("Fed Policy Absorption 001 independent review differs")


def _verify_states(source: Mapping[str, Any], state: Mapping[str, Any]) -> None:
    program_authority = {
        "strategy_execution": False,
        "research_qualification": False,
        "controlled_evaluation": False,
        "protected_holdout": False,
        "paper_execution": False,
        "broker_writes": False,
        "live_execution": False,
    }
    previous = {
        "path": SOURCE_STATE_RELATIVE_PATH.as_posix(),
        "sha256": SOURCE_STATE_SHA256,
        "fingerprint": SOURCE_STATE_FINGERPRINT,
        "state_revision": 5,
    }
    if (
        source.get("schema_version") != "intraday-autonomous-research-program-state-v2"
        or source.get("program_id") != "intraday-autonomous-research-001"
        or source.get("state_revision") != 5
        or source.get("phase") != "campaign-2-terminal-reviewed-campaign-3-planning-authorized"
        or source.get("run_specifications_consumed") != 36
        or source.get("remaining_permitted_campaign_capacity") != 90
        or source.get("authority") != program_authority
        or state.get("schema_version") != "intraday-autonomous-research-program-state-v2"
        or state.get("program_id") != "intraday-autonomous-research-001"
        or state.get("state_revision") != 6
        or state.get("previous_state") != previous
        or state.get("phase") != "campaign-3-plan-reviewed-implementation-pending"
        or state.get("active_campaign_id") != PROGRAM_ID
        or state.get("current_campaign_index") != 3
        or state.get("run_specifications_consumed") != 36
        or state.get("remaining_permitted_campaign_capacity") != 90
        or state.get("remaining_prospectively_permitted_campaigns") != [PROGRAM_ID]
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
        or state.get("campaign_planning_controls")
        != {
            "calendar": {
                "path": CALENDAR_RELATIVE_PATH.as_posix(),
                "sha256": CALENDAR_SHA256,
                "fingerprint": CALENDAR_FINGERPRINT,
            },
            "source_evidence": {
                "path": SOURCE_EVIDENCE_RELATIVE_PATH.as_posix(),
                "sha256": SOURCE_EVIDENCE_SHA256,
                "fingerprint": SOURCE_EVIDENCE_FINGERPRINT,
            },
            "pre_design_attestation": _ATTESTATION,
            "preserved_preplan_failures": [_FAILURE_V1, _FAILURE_V2],
        }
        or state.get("authority") != program_authority
    ):
        raise ValueError("Fed Policy Absorption 001 program state differs")


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Fed Policy Absorption 001 timestamp differs")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Fed Policy Absorption 001 timestamp must be aware")
    return parsed.astimezone(UTC) if value.endswith("Z") else parsed


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value
