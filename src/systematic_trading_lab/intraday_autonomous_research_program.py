"""Strict loader for the frozen Intraday Autonomous Research 001 program."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .fingerprints import fingerprint

PROGRAM_ID = "intraday-autonomous-research-001"
PROGRAM_RELATIVE_PATH = Path("config/research/intraday-autonomous-research-001-program-v1.json")
REVIEW_RELATIVE_PATH = Path(
    "config/research/intraday-autonomous-research-001-program-independent-review-v1.json"
)
STATE_RELATIVE_PATH = Path("docs/research-campaigns/intraday-autonomous-research-001-state.json")

PROGRAM_SHA256 = "dda9b38a95970660ec2244e540de649586ed940e037eaa49a3b11c760480d1f9"
PROGRAM_FINGERPRINT = "734282e42b991889aa2dbce220b46807debe0114309e93cf4ca8d89bf0d0c14f"
REVIEW_SHA256 = "1731794543d13306f34462016d376966d47ae8354fa337144889c7bea5c738db"
REVIEW_FINGERPRINT = "50424b9e5c07a95351af93e560859293768e34959d01f816f0f63042302497c0"
STATE_SHA256 = "8ef652046442ce7adfcd474d8effe610738a2a00e29fc97ceae3d4110ae2981a"

_AUTHORITY = {
    "strategy_execution": False,
    "research_qualification": False,
    "controlled_evaluation": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}
_REVIEW_AUTHORITY = {"strategy_implementation": False, **_AUTHORITY}
_EVIDENCE_BINDINGS = dict(
    (
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
)
_DEPENDENCY_BINDINGS = {
    "config/research/intraday-event-drift-001-plan-v1.json": (
        "c0dade2573405ddcd38d88814c10a27c3caae11bfb925a21179f6741cc20233c",
        "73933d470feb52c1135746ab57db742019077b8b39e8e2545e9aba37c9a8d838",
    ),
    "config/research/intraday-execution-cost-model-001-v1.json": (
        "a9e6c2b86c6623d73e089de591c55eeec0711fa55f0933a4e3ea9a1c0c2392af",
        "94fc3ba4663b422fbb0dc0cce7e3d78a7ba81f22d71d5fa986ab6847b7925bb4",
    ),
}
_DATASET_IDS = (
    "0a307dd767283d8f268c10b372c416abc49ac555cb242bf612f0b485be518363",
    "074e66c2260f576d6c1765295db93b5e22fb4753dc8f9912ef6f5be7fa937479",
    "1b1b5b1179a84522d6827827a6143a547321ef8b49262cdfb4d6a81885f647ed",
    "4afa60f29ea266ec8b60be9d9600132f8cff4207e846443c65afd3bb5c497a19",
)
_CAMPAIGN_IDS = (
    "intraday-spy-qqq-lead-lag-001",
    "intraday-relative-volume-drift-001",
    "intraday-fed-policy-absorption-001",
)


@dataclass(frozen=True)
class IntradayAutonomousResearchProgram:
    """Verified read-only inputs available to Campaign 1 planning."""

    path: Path
    sha256: str
    program_fingerprint: str
    review_path: Path
    review_sha256: str
    review_fingerprint: str
    state_path: Path
    state_sha256: str
    payload: Mapping[str, Any]
    review: Mapping[str, Any]
    state: Mapping[str, Any]

    def __post_init__(self) -> None:
        for field in ("payload", "review", "state"):
            object.__setattr__(self, field, _freeze(getattr(self, field)))


def load_intraday_autonomous_research_program(
    repository: Path,
) -> IntradayAutonomousResearchProgram:
    """Load the exact reviewed program without reading market data or campaign results."""
    repository = repository.resolve()
    path, payload = _load_fingerprinted(
        repository,
        PROGRAM_RELATIVE_PATH,
        PROGRAM_SHA256,
        "program_fingerprint",
        PROGRAM_FINGERPRINT,
        "program",
    )
    review_path, review = _load_fingerprinted(
        repository,
        REVIEW_RELATIVE_PATH,
        REVIEW_SHA256,
        "review_fingerprint",
        REVIEW_FINGERPRINT,
        "review",
    )
    state_path, state = _load_json(repository, STATE_RELATIVE_PATH, STATE_SHA256, "state")
    _verify_program(repository, payload)
    _verify_review(review)
    _verify_state(state)
    return IntradayAutonomousResearchProgram(
        path,
        PROGRAM_SHA256,
        PROGRAM_FINGERPRINT,
        review_path,
        REVIEW_SHA256,
        REVIEW_FINGERPRINT,
        state_path,
        STATE_SHA256,
        payload,
        review,
        state,
    )


def _verify_program(repository: Path, payload: Mapping[str, Any]) -> None:
    bounds = _mapping(payload.get("program_bounds"), "program bounds")
    data = _mapping(payload.get("shared_data"), "shared data")
    execution = _mapping(payload.get("shared_execution"), "shared execution")
    envelope = _mapping(
        _mapping(payload.get("campaign_plan_requirements"), "campaign plan requirements").get(
            "stage_envelope"
        ),
        "stage envelope",
    )
    evidence = _list_of_mappings(
        _mapping(payload.get("research_basis"), "research basis").get("complete_exposed_evidence"),
        "evidence",
    )
    campaigns = _list_of_mappings(payload.get("campaigns"), "campaigns")
    if (
        payload.get("schema_version") != "intraday-autonomous-research-program-v1"
        or payload.get("program_id") != PROGRAM_ID
        or payload.get("status")
        != "prospective-frozen-before-any-successor-strategy-implementation-or-results"
        or payload.get("authority") != _AUTHORITY
        or [(item.get("path"), item.get("sha256")) for item in evidence]
        != list(_EVIDENCE_BINDINGS.items())
        or tuple(data.get("permitted_dataset_ids", ())) != _DATASET_IDS
        or data.get("price_volume_base_plan")
        != {
            "path": "config/research/intraday-event-drift-001-plan-v1.json",
            "sha256": _DEPENDENCY_BINDINGS["config/research/intraday-event-drift-001-plan-v1.json"][
                0
            ],
            "fingerprint": _DEPENDENCY_BINDINGS[
                "config/research/intraday-event-drift-001-plan-v1.json"
            ][1],
        }
        or execution.get("cost_model")
        != {
            "path": "config/research/intraday-execution-cost-model-001-v1.json",
            "sha256": _DEPENDENCY_BINDINGS[
                "config/research/intraday-execution-cost-model-001-v1.json"
            ][0],
            "fingerprint": _DEPENDENCY_BINDINGS[
                "config/research/intraday-execution-cost-model-001-v1.json"
            ][1],
        }
        or bounds.get("maximum_campaigns") != 3
        or bounds.get("maximum_total_run_specifications") != 270
        or bounds.get("maximum_run_specifications_per_campaign") != 90
        or bounds.get("maximum_infrastructure_attempts_per_run") != 3
        or [
            (
                item.get("index"),
                item.get("campaign_id"),
                item.get("maximum_parent_candidates"),
                item.get("maximum_run_specifications"),
            )
            for item in campaigns
        ]
        != [(index, campaign_id, 9, 90) for index, campaign_id in enumerate(_CAMPAIGN_IDS, 1)]
        or len(campaigns) != 3
        or envelope
        != {
            "parent_candidate_count": 9,
            "discovery_scenarios_per_parent": 2,
            "discovery_maximum": 18,
            "walk_forward_candidate_cap": 3,
            "walk_forward_period_count": 4,
            "walk_forward_scenarios_per_candidate_period": 2,
            "walk_forward_maximum": 24,
            "serious_candidate_cap": 1,
            "stress_scenario_count": 4,
            "stress_period_count": 4,
            "stress_and_delay_maximum": 16,
            "maximum_immediate_neighbors_per_serious_candidate": 4,
            "neighbor_period_count": 4,
            "neighbor_scenarios_per_period": 2,
            "immediate_neighbor_maximum": 32,
            "total_maximum": 90,
        }
    ):
        raise ValueError("Intraday Autonomous Research 001 program binding differs")
    for relative, expected_sha256 in _EVIDENCE_BINDINGS.items():
        _verify_raw_sha256(repository / relative, expected_sha256, "evidence")
    for relative, (expected_sha256, _) in _DEPENDENCY_BINDINGS.items():
        _verify_raw_sha256(repository / relative, expected_sha256, "dependency")


def _verify_review(review: Mapping[str, Any]) -> None:
    verification = _mapping(review.get("verification"), "review verification")
    if (
        review.get("schema_version") != "intraday-autonomous-research-program-independent-review-v1"
        or review.get("review_id")
        != "intraday-autonomous-research-001-program-independent-review-v1"
        or review.get("status") != "passed-before-successor-strategy-implementation-or-results"
        or review.get("verdict") != "pass"
        or review.get("findings") != []
        or review.get("authority") != _REVIEW_AUTHORITY
        or review.get("reviewed_program")
        != {
            "path": PROGRAM_RELATIVE_PATH.as_posix(),
            "sha256": PROGRAM_SHA256,
            "program_fingerprint": PROGRAM_FINGERPRINT,
            "program_id": PROGRAM_ID,
        }
        or review.get("reviewed_state")
        != {"path": STATE_RELATIVE_PATH.as_posix(), "sha256": STATE_SHA256}
        or verification.get("complete_exposed_evidence_binding_count") != 8
        or verification.get("dataset_binding_count") != 4
        or verification.get("campaign_count") != 3
        or verification.get("parent_cap_per_campaign") != 9
        or verification.get("spec_cap_per_campaign") != 90
        or verification.get("global_spec_cap") != 270
        or verification.get("stage_run_specifications")
        != {
            "discovery": 18,
            "walk_forward": 24,
            "stress_and_delay": 16,
            "immediate_neighbor": 32,
            "total": 90,
        }
        or verification.get("canonical_fingerprint_verified") is not True
        or verification.get("state_plan_binding_verified") is not True
        or verification.get("exact_byte_rereview") is not True
    ):
        raise ValueError("Intraday Autonomous Research 001 review binding differs")


def _verify_state(state: Mapping[str, Any]) -> None:
    if (
        state.get("schema_version") != "intraday-autonomous-research-program-state-v1"
        or state.get("program_id") != PROGRAM_ID
        or state.get("program_plan")
        != {
            "path": PROGRAM_RELATIVE_PATH.as_posix(),
            "sha256": PROGRAM_SHA256,
            "fingerprint": PROGRAM_FINGERPRINT,
        }
        or state.get("authority") != _AUTHORITY
    ):
        raise ValueError("Intraday Autonomous Research 001 state binding differs")


def _load_fingerprinted(
    repository: Path,
    relative: Path,
    expected_sha256: str,
    key: str,
    expected_fingerprint: str,
    label: str,
) -> tuple[Path, Mapping[str, Any]]:
    path, payload = _load_json(repository, relative, expected_sha256, label)
    unsigned = dict(payload)
    if (
        unsigned.pop(key, None) != expected_fingerprint
        or fingerprint(unsigned) != expected_fingerprint
    ):
        raise ValueError(f"Intraday Autonomous Research 001 {label} fingerprint differs")
    return path, payload


def _load_json(
    repository: Path, relative: Path, expected_sha256: str, label: str
) -> tuple[Path, Mapping[str, Any]]:
    path = repository / relative
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError(f"Intraday Autonomous Research 001 {label} SHA-256 differs")
    try:
        return path, _mapping(json.loads(raw), label)
    except json.JSONDecodeError as error:
        raise ValueError(f"Intraday Autonomous Research 001 {label} is invalid JSON") from error


def _verify_raw_sha256(path: Path, expected: str, label: str) -> None:
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f"Intraday Autonomous Research 001 {label} SHA-256 differs")


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"Intraday Autonomous Research 001 {label} must be an object")
    return value


def _list_of_mappings(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"Intraday Autonomous Research 001 {label} must be a list")
    return [_mapping(item, label) for item in value]
