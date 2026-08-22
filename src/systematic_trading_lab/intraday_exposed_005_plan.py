"""Strict frozen-plan loader for Intraday Exposed 005."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .fingerprints import fingerprint
from .intraday_exposed_004_plan import (
    PROGRAM_ID as SOURCE_PROGRAM_ID,
)
from .intraday_exposed_004_plan import (
    REVIEWED_PLAN_FINGERPRINT as SOURCE_PLAN_FINGERPRINT,
)
from .intraday_exposed_004_plan import (
    REVIEWED_PLAN_SHA256 as SOURCE_PLAN_SHA256,
)
from .intraday_exposed_004_plan import (
    IntradayExposed004Plan,
    load_intraday_exposed_004_plan,
)
from .research_attempts import MAX_INFRASTRUCTURE_ATTEMPTS

PLAN_ID = "intraday-exposed-005-plan-v1"
PROGRAM_ID = "intraday-exposed-005"
PLAN_SCHEMA = "intraday-exposed-005-research-plan-v1"
PLAN_RELATIVE_PATH = Path("config/research/intraday-exposed-005-plan-v1.json")
REVIEWED_PLAN_SHA256 = "622d3ad769b12dad857bfe8ee60be4fa1a75b3f3d68becb9b750b323102fd811"
REVIEWED_PLAN_FINGERPRINT = "8d30af60d84f1baaa2365096b898960bef759fbafc5215eba68bb81061819ba3"
PLAN_REVIEW_RELATIVE_PATH = Path(
    "config/research/intraday-exposed-005-plan-independent-review-v1.json"
)
REVIEWED_PLAN_REVIEW_SHA256 = "e1ef2d6bb5651281aa6d757d9af12260fc51ce0114a8ca54e49626946507f838"
REVIEWED_PLAN_REVIEW_FINGERPRINT = (
    "cdd8d0e3714a3bafead13869d5785c6f2a83b2e3fb33e3ab06e3829ff26457c3"
)
JUNE_DISPOSITION_RELATIVE_PATH = Path(
    "config/research/intraday-exposed-005-june-disposition-v1.json"
)
REVIEWED_JUNE_DISPOSITION_SHA256 = (
    "af6aea5e8d7bd8360aa6af4ddc31e1e67a1be48476f6c8ab13197fe12515b3c0"
)
REVIEWED_JUNE_DISPOSITION_FINGERPRINT = (
    "6dad6480dc3b0379017d582bb2f29fc562f41379bb3065855c55eadf51f025dd"
)

_STARTING_MAIN = "8856a689a4767041dbfadab00f8da6907beef15d"
_PLAN_STATUS = "frozen-before-exposed-005-implementation-or-strategy-results"
LAUNCH_FAILURE_RELATIVE_PATH = Path("config/research/intraday-exposed-004-launch-failure-v1.json")
REVIEWED_LAUNCH_FAILURE_SHA256 = "e7e38498c888107b42375cd1323afd2d97068747718bf239f1605bf6c9d09a16"
REVIEWED_LAUNCH_FAILURE_FINGERPRINT = (
    "4c5a9a35297f6443dc354da5f08d085bc0c845379cc629a6c26f6f698865ed4a"
)
_LAUNCH_FAILURE = {
    "path": LAUNCH_FAILURE_RELATIVE_PATH.as_posix(),
    "sha256": REVIEWED_LAUNCH_FAILURE_SHA256,
    "fingerprint": REVIEWED_LAUNCH_FAILURE_FINGERPRINT,
    "classification": "aborted-before-attempt-task-transport-failure",
}
_STRATEGY_PATH = Path("src/systematic_trading_lab/intraday_exposed_002_strategies.py")
_STRATEGY_SHA256 = "4c6cbc193b78d32a072ef5f71c1c179714c88d182887a97a2c5e031b54fc2ad4"
_ENGINE_PATH = Path("src/systematic_trading_lab/intraday_exposed_002_engine.py")
_ENGINE_SHA256 = "bf62f6661b0beb2ac57b83668412b90a17255fd176fa559966ec0f5a64032c66"
_EXACT_REUSE_SECTIONS = [
    "frozen_dependencies.execution_cost_model",
    "data",
    "chronology",
    "execution",
    "configuration_contract.expansion",
    "configuration_contract.neighbor_rule",
    "configuration_contract.parent_configuration_count",
    "configuration_contract.maximum_parent_configurations",
    "configuration_contract.maximum_free_parameters_per_family",
    "configuration_contract.families",
    "paired_cost_analysis",
    "discovery_screen",
    "walk_forward_screen",
    "serious_candidate_screen",
    "final_cohort",
]
_AUTHORITY = {
    "research_qualification": False,
    "controlled_evaluation": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}


@dataclass(frozen=True)
class Exposed005Configuration:
    candidate_id: str
    source_candidate_id: str
    source_exposed_003_candidate_id: str
    source_exposed_004_candidate_id: str
    family_id: str
    family_ordinal: int
    parameters: Mapping[str, object]
    neighbor_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


@dataclass(frozen=True)
class IntradayExposed005Plan:
    path: Path
    sha256: str
    plan_fingerprint: str
    june_disposition_path: Path
    june_disposition_sha256: str
    june_disposition_fingerprint: str
    payload: Mapping[str, Any]
    june_disposition: Mapping[str, Any]
    source_plan: IntradayExposed004Plan
    configurations: tuple[Exposed005Configuration, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(
            self,
            "june_disposition",
            MappingProxyType(dict(self.june_disposition)),
        )

    @property
    def periods(self) -> tuple[Any, ...]:
        return self.source_plan.periods


def load_intraday_exposed_005_plan(repository: Path) -> IntradayExposed005Plan:
    repository = repository.resolve()
    path, payload = _load_fingerprinted(
        repository,
        PLAN_RELATIVE_PATH,
        REVIEWED_PLAN_SHA256,
        "plan_fingerprint",
        REVIEWED_PLAN_FINGERPRINT,
        "Intraday Exposed 005 plan",
    )
    if (
        payload.get("schema_version") != PLAN_SCHEMA
        or payload.get("plan_id") != PLAN_ID
        or payload.get("program_id") != PROGRAM_ID
        or payload.get("campaign_id") != PROGRAM_ID
        or payload.get("status") != _PLAN_STATUS
        or payload.get("starting_main") != _STARTING_MAIN
        or payload.get("authority") != _AUTHORITY
    ):
        raise ValueError("Intraday Exposed 005 plan identity differs")

    source_plan = load_intraday_exposed_004_plan(repository)
    _verify_source_design(payload, source_plan)
    _verify_launch_failure(repository)
    _verify_implementation(repository, payload)
    _verify_runtime_boundary(payload)
    june_path, june_disposition = _load_fingerprinted(
        repository,
        JUNE_DISPOSITION_RELATIVE_PATH,
        REVIEWED_JUNE_DISPOSITION_SHA256,
        "disposition_fingerprint",
        REVIEWED_JUNE_DISPOSITION_FINGERPRINT,
        "Intraday Exposed 005 June disposition",
    )
    _verify_june_disposition(payload, june_disposition)
    _verify_plan_review(repository)
    configurations = tuple(
        Exposed005Configuration(
            _rekey(item.candidate_id),
            item.source_candidate_id,
            item.source_exposed_003_candidate_id,
            item.candidate_id,
            item.family_id,
            item.family_ordinal,
            item.parameters,
            tuple(_rekey(neighbor_id) for neighbor_id in item.neighbor_ids),
        )
        for item in source_plan.configurations
    )
    if (
        len(configurations) != 60
        or len({item.candidate_id for item in configurations}) != 60
        or any(not item.candidate_id.startswith("ie005-") for item in configurations)
    ):
        raise ValueError("Intraday Exposed 005 candidate identities differ")
    return IntradayExposed005Plan(
        path,
        REVIEWED_PLAN_SHA256,
        REVIEWED_PLAN_FINGERPRINT,
        june_path,
        REVIEWED_JUNE_DISPOSITION_SHA256,
        REVIEWED_JUNE_DISPOSITION_FINGERPRINT,
        payload,
        june_disposition,
        source_plan,
        configurations,
    )


def _verify_source_design(payload: Mapping[str, Any], source_plan: IntradayExposed004Plan) -> None:
    source = _mapping(payload.get("source_design"), "source design")
    exposed_003 = source_plan.source_plan
    underlying = exposed_003.source_plan
    if (
        source.get("path") != "config/research/intraday-exposed-004-plan-v1.json"
        or source.get("program_id") != SOURCE_PROGRAM_ID
        or source.get("sha256") != SOURCE_PLAN_SHA256
        or source.get("fingerprint") != SOURCE_PLAN_FINGERPRINT
        or source.get("source_exposed_003_path")
        != "config/research/intraday-exposed-003-plan-v1.json"
        or source.get("source_exposed_003_program_id") != exposed_003.payload["program_id"]
        or source.get("source_exposed_003_sha256") != exposed_003.sha256
        or source.get("source_exposed_003_fingerprint") != exposed_003.plan_fingerprint
        or source.get("underlying_source_path")
        != "config/research/intraday-exposed-002-plan-v1.json"
        or source.get("underlying_source_sha256") != underlying.sha256
        or source.get("underlying_source_fingerprint") != underlying.plan_fingerprint
        or source.get("underlying_amendment_sha256") != underlying.amendment_sha256
        or source.get("underlying_amendment_fingerprint") != underlying.amendment_fingerprint
        or source.get("underlying_data_binding_sha256") != underlying.data_binding_sha256
        or source.get("underlying_data_binding_fingerprint") != underlying.data_binding_fingerprint
        or source.get("reuse_mode")
        != "exact-frozen-004-plan-via-transitive-loader-with-identity-rekey-only"
        or source.get("exact_reuse_sections") != _EXACT_REUSE_SECTIONS
        or source.get("parent_configuration_count") != len(source_plan.configurations)
        or source.get("discovery_run_count") != len(source_plan.configurations) * 2
        or source.get("intraday_exposed_002_runtime_rows_imported") is not False
        or source.get("intraday_exposed_003_runtime_rows_imported") is not False
        or source.get("intraday_exposed_004_runtime_rows_imported") is not False
        or source.get("result_dependent_design_change") is not False
        or source.get("launch_failure") != _LAUNCH_FAILURE
    ):
        raise ValueError("Intraday Exposed 005 source-design binding differs")


def _verify_implementation(repository: Path, payload: Mapping[str, Any]) -> None:
    binding = _mapping(payload.get("implementation_binding"), "implementation binding")
    if (
        binding.get("strategy_path") != _STRATEGY_PATH.as_posix()
        or binding.get("strategy_sha256") != _STRATEGY_SHA256
        or binding.get("strategy_version") != "intraday-exposed-002-mechanics-v1"
        or binding.get("engine_path") != _ENGINE_PATH.as_posix()
        or binding.get("engine_sha256") != _ENGINE_SHA256
        or binding.get("engine_version") != "intraday-exposed-002-engine-v1"
        or _sha256(repository / _STRATEGY_PATH) != _STRATEGY_SHA256
        or _sha256(repository / _ENGINE_PATH) != _ENGINE_SHA256
    ):
        raise ValueError("Intraday Exposed 005 implementation binding differs")


def _verify_launch_failure(repository: Path) -> None:
    _path, failure = _load_fingerprinted(
        repository,
        LAUNCH_FAILURE_RELATIVE_PATH,
        REVIEWED_LAUNCH_FAILURE_SHA256,
        "failure_fingerprint",
        REVIEWED_LAUNCH_FAILURE_FINGERPRINT,
        "Intraday Exposed 004 launch failure",
    )
    if (
        failure.get("schema_version") != "intraday-exposed-004-launch-failure-v1"
        or failure.get("program_id") != SOURCE_PROGRAM_ID
        or failure.get("classification") != _LAUNCH_FAILURE["classification"]
        or failure.get("authority") != _AUTHORITY
        or _mapping(failure.get("runtime"), "launch failure runtime").get("attempt_count") != 0
        or _mapping(failure.get("runtime"), "launch failure runtime").get(
            "strategy_execution_started"
        )
        is not False
    ):
        raise ValueError("Intraday Exposed 004 launch failure binding differs")


def _verify_runtime_boundary(payload: Mapping[str, Any]) -> None:
    cost = _mapping(payload.get("cost_model"), "cost model")
    data = _mapping(payload.get("data_reuse"), "data reuse")
    identity = _mapping(payload.get("identity"), "identity")
    report_identity = _mapping(payload.get("report_identity"), "report identity")
    attempts = _mapping(payload.get("research_attempts"), "research attempts")
    process = _mapping(payload.get("process_execution"), "process execution")
    launch = _mapping(payload.get("launch_gates"), "launch gates")
    controlled = _mapping(payload.get("controlled_evaluation"), "controlled evaluation")
    protected = _mapping(payload.get("protected_boundaries"), "protected boundaries")
    if cost != {
        "path": "config/research/intraday-execution-cost-model-001-v1.json",
        "cost_model_id": "intraday-execution-cost-model-001-v1",
        "sha256": "a9e6c2b86c6623d73e089de591c55eeec0711fa55f0933a4e3ea9a1c0c2392af",
        "fingerprint": "94fc3ba4663b422fbb0dc0cce7e3d78a7ba81f22d71d5fa986ab6847b7925bb4",
        "recalibration_allowed": False,
    }:
        raise ValueError("Intraday Exposed 005 cost model differs")
    if (
        data.get("source_data_binding_path")
        != "config/research/intraday-exposed-002-data-binding-v1.json"
        or data.get("new_acquisition_allowed") is not False
        or data.get("june_data_access") is not False
        or data.get("latest_permitted_bar") != "2026-05-29T19:55:00Z"
        or data.get("full_integrity_reverification_required_before_runtime_state") is not True
        or data.get("worker_catalog_access") != "read-only"
        or identity.get("candidate_id_format")
        != "ie005-f{family_ordinal:02d}-a{first_axis_index:02d}-b{second_axis_index:02d}"
        or identity.get("reservation_id_format") != "ie005q-{run_fingerprint_prefix_24}"
        or identity.get("run_id_format") != "ie005r-{run_fingerprint_prefix_24}"
        or identity.get("attempt_id_format") != "ie005a-{attempt_fingerprint_prefix_24}"
        or identity.get("runtime_root") != ".trading-lab/intraday-exposed-005"
        or identity.get("database") != "intraday-exposed-005.sqlite3"
        or report_identity
        != {
            "program_binding_schema": "intraday-exposed-005-program-binding-v1",
            "runner_version": "intraday-exposed-005-runner-v1",
            "run_schema": "intraday-exposed-005-run-v1",
            "run_report_schema": "intraday-exposed-005-backtest-report-v1",
            "final_freeze_schema": "intraday-exposed-005-final-freeze-v1",
            "final_report_schema": "intraday-exposed-005-final-report-v1",
        }
        or attempts.get("schema") != "research-attempts-v1"
        or attempts.get("maximum_infrastructure_attempts") != MAX_INFRASTRUCTURE_ATTEMPTS
        or attempts.get("lease_timeout_seconds") != 300
        or attempts.get("heartbeat_interval_seconds") != 60
        or attempts.get("retry_condition") != "expired-no-result-infrastructure-lease-only"
        or any(
            attempts.get(key) is not False
            for key in (
                "completed_result_retry_allowed",
                "candidate_exception_retry_allowed",
                "data_integrity_retry_allowed",
                "publication_conflict_retry_allowed",
                "failed_qualification_gate_retry_allowed",
            )
        )
        or process.get("start_method") != "spawn"
        or process.get("default_worker_count") != 4
        or process.get("worker_count_configurable") is not True
        or process.get("maximum_active_claims_per_worker") != 1
        or process.get("worker_state_lifetime") != "one-stage"
        or process.get("worker_dataset_cache") != "private-immutable-read-only"
        or process.get("cross_stage_parallelism") is not False
        or process.get("completion_order_affects_selection") is not False
        or process.get("abrupt_exit_reassignment") != "lease-expiry-only"
        or _mapping(launch.get("required_control_artifact"), "required control artifact").get(
            "pass_required_before_launch"
        )
        is not True
        or _mapping(launch.get("equivalence"), "equivalence gate").get("worker_counts") != [1, 4]
        or _mapping(launch.get("equivalence"), "equivalence gate").get(
            "source_database_mutation_allowed"
        )
        is not False
        or _mapping(launch.get("equivalence"), "equivalence gate").get(
            "dataset_input_mutation_allowed"
        )
        is not False
        or not isinstance(launch.get("intraday_exposed_003_valid_completed_terminal_action"), str)
        or not isinstance(
            launch.get("intraday_exposed_003_incomplete_or_invalid_terminal_action"), str
        )
        or not isinstance(
            launch.get("intraday_exposed_003_active_materially_incomplete_action"), str
        )
        or launch.get("partial_strategy_merit_inspection_allowed") is not False
        or controlled.get("range_status") != "ineligible"
        or controlled.get("june_read") is not False
        or controlled.get("substitute_range") is not False
        or controlled.get("controlled_plan_creation") is not False
        or protected.get("paper_or_broker_state_access") is not False
        or protected.get("strategic_allocation_21_access") is not False
    ):
        raise ValueError("Intraday Exposed 005 runtime boundary differs")


def _verify_june_disposition(payload: Mapping[str, Any], disposition: Mapping[str, Any]) -> None:
    dependency = _mapping(payload.get("june_disposition"), "June disposition dependency")
    audit = _mapping(disposition.get("audit"), "June disposition audit")
    effect = _mapping(disposition.get("program_effect"), "June disposition effect")
    if dependency != {
        "path": JUNE_DISPOSITION_RELATIVE_PATH.as_posix(),
        "sha256": REVIEWED_JUNE_DISPOSITION_SHA256,
        "fingerprint": REVIEWED_JUNE_DISPOSITION_FINGERPRINT,
        "status": "ineligible-before-strategy-results",
    }:
        raise ValueError("Intraday Exposed 005 June dependency differs")
    if (
        disposition.get("schema_version") != "intraday-exposed-controlled-range-disposition-v1"
        or disposition.get("disposition_id") != "intraday-exposed-005-june-disposition-v1"
        or disposition.get("program_id") != PROGRAM_ID
        or disposition.get("status") != "ineligible-before-strategy-results"
        or disposition.get("starting_main") != _STARTING_MAIN
        or audit.get("known_exposures_sha256")
        != "f11977e33a5ade47eeb0ad0923180eca733bc694ffef0e4e2f335936da4746aa"
        or audit.get("known_exposures_fingerprint")
        != "0666996faabb50abce0b8959c49980e36a655ea290618bc1463342d2ab5122f9"
        or audit.get("prior_disposition_sha256")
        != "af91ca3889327a402851e652592d842b43a31d04bba4aa2efe3305d855165efa"
        or audit.get("prior_disposition_fingerprint")
        != "2c5b84269e255a78b41f591cbcfd79a684adb6159f6172733da4219e06ce5278"
        or audit.get("conflicting_entry_id") != "intraday-v2-real-market-results"
        or audit.get("conflicting_entry_class") != "real-market-result-observed"
        or effect.get("june_read_allowed") is not False
        or effect.get("controlled_evaluation_allowed") is not False
        or effect.get("substitute_range_allowed") is not False
        or disposition.get("authority")
        != {
            "read_june": False,
            "controlled_evaluation": False,
            "protected_holdout": False,
            "paper_execution": False,
            "broker_writes": False,
            "live_execution": False,
        }
    ):
        raise ValueError("Intraday Exposed 005 June disposition differs")


def _verify_plan_review(repository: Path) -> None:
    _path, review = _load_fingerprinted(
        repository,
        PLAN_REVIEW_RELATIVE_PATH,
        REVIEWED_PLAN_REVIEW_SHA256,
        "review_fingerprint",
        REVIEWED_PLAN_REVIEW_FINGERPRINT,
        "Intraday Exposed 005 plan review",
    )
    reviewed_plan = _mapping(review.get("reviewed_plan"), "reviewed plan")
    reviewed_failure = _mapping(review.get("reviewed_004_launch_failure"), "reviewed failure")
    reviewed_june = _mapping(review.get("reviewed_june_disposition"), "reviewed June disposition")
    verification = _mapping(review.get("verification"), "review verification")
    if (
        review.get("schema_version") != "intraday-exposed-005-plan-independent-review-v1"
        or review.get("review_id") != "intraday-exposed-005-plan-independent-review-v1"
        or review.get("status") != "passed-before-exposed-005-implementation-or-strategy-results"
        or review.get("verdict") != "pass"
        or review.get("findings") != []
        or reviewed_plan
        != {
            "program_id": PROGRAM_ID,
            "path": PLAN_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_PLAN_SHA256,
            "plan_fingerprint": REVIEWED_PLAN_FINGERPRINT,
        }
        or reviewed_failure
        != {
            "path": _LAUNCH_FAILURE["path"],
            "sha256": _LAUNCH_FAILURE["sha256"],
            "failure_fingerprint": _LAUNCH_FAILURE["fingerprint"],
            "classification": _LAUNCH_FAILURE["classification"],
        }
        or reviewed_june
        != {
            "path": JUNE_DISPOSITION_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_JUNE_DISPOSITION_SHA256,
            "disposition_fingerprint": REVIEWED_JUNE_DISPOSITION_FINGERPRINT,
            "status": "ineligible-before-strategy-results",
        }
        or verification.get("configuration_count") != 60
        or verification.get("family_count") != 10
        or verification.get("neighbor_edge_count") != 140
        or verification.get("period_count") != 5
        or verification.get("discovery_run_count") != 120
        or review.get("authority")
        != {
            "strategy_execution": False,
            "controlled_evaluation": False,
            "protected_holdout": False,
            "paper_execution": False,
            "broker_writes": False,
            "live_execution": False,
        }
    ):
        raise ValueError("Intraday Exposed 005 plan review differs")


def _load_fingerprinted(
    repository: Path,
    relative_path: Path,
    expected_sha256: str,
    fingerprint_key: str,
    expected_fingerprint: str,
    label: str,
) -> tuple[Path, Mapping[str, Any]]:
    path = repository / relative_path
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError(f"{label} SHA-256 differs")
    try:
        payload = _mapping(json.loads(raw), label)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} is invalid JSON") from error
    unsigned = dict(payload)
    stored_fingerprint = unsigned.pop(fingerprint_key, None)
    if stored_fingerprint != expected_fingerprint or fingerprint(unsigned) != expected_fingerprint:
        raise ValueError(f"{label} fingerprint differs")
    return path, payload


def _rekey(candidate_id: str) -> str:
    if not candidate_id.startswith("ie004-"):
        raise ValueError("Intraday Exposed 004 candidate identity differs")
    return f"ie005-{candidate_id.removeprefix('ie004-')}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object")
    return value
