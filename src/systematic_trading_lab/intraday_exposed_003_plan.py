"""Strict frozen-plan loader for Intraday Exposed 003."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .fingerprints import fingerprint
from .intraday_exposed_002_plan import (
    REVIEWED_DATA_BINDING_FINGERPRINT,
    REVIEWED_DATA_BINDING_SHA256,
    REVIEWED_PLAN_AMENDMENT_FINGERPRINT,
    REVIEWED_PLAN_AMENDMENT_SHA256,
    Exposed002Period,
    IntradayExposed002Plan,
    load_intraday_exposed_002_plan,
)
from .intraday_exposed_002_plan import (
    REVIEWED_PLAN_FINGERPRINT as SOURCE_PLAN_FINGERPRINT,
)
from .intraday_exposed_002_plan import (
    REVIEWED_PLAN_SHA256 as SOURCE_PLAN_SHA256,
)
from .research_attempts import MAX_INFRASTRUCTURE_ATTEMPTS

PLAN_ID = "intraday-exposed-003-plan-v1"
PROGRAM_ID = "intraday-exposed-003"
PLAN_SCHEMA = "intraday-exposed-003-research-plan-v1"
PLAN_RELATIVE_PATH = Path("config/research/intraday-exposed-003-plan-v1.json")
REVIEWED_PLAN_SHA256 = "7d5edd0c52e80d42d322cfa2d3cf1d91ed10bc7c06cd5b418328ba8a3e649f22"
REVIEWED_PLAN_FINGERPRINT = "ac8b3c029599fd912464020e57bbe3cdbde907f63d46f5a7ef748cab2655bc2e"
PLAN_REVIEW_RELATIVE_PATH = Path(
    "config/research/intraday-exposed-003-plan-independent-review-v1.json"
)
REVIEWED_PLAN_REVIEW_SHA256 = "ad9a2bb278cd98d3e74e7248cd12f8549b6e6bbecf4cd03d41f3bb9a7ba4665f"
REVIEWED_PLAN_REVIEW_FINGERPRINT = (
    "b3e3cad3a8489b1079b83b8f8fdf11dc93e96151ee8311603b3fdfe38fb637ab"
)
JUNE_DISPOSITION_RELATIVE_PATH = Path(
    "config/research/intraday-exposed-003-june-disposition-v1.json"
)
REVIEWED_JUNE_DISPOSITION_SHA256 = (
    "af91ca3889327a402851e652592d842b43a31d04bba4aa2efe3305d855165efa"
)
REVIEWED_JUNE_DISPOSITION_FINGERPRINT = (
    "2c5b84269e255a78b41f591cbcfd79a684adb6159f6172733da4219e06ce5278"
)

_STARTING_MAIN = "9de63bfe3278091220ffbf88743daba7a24ddb1c"
_PLAN_STATUS = "frozen-before-exposed-003-implementation-or-strategy-results"
_KNOWN_EXPOSURES_PATH = Path("config/research/intraday-known-exposures-v1.json")
_KNOWN_EXPOSURES_SHA256 = "f11977e33a5ade47eeb0ad0923180eca733bc694ffef0e4e2f335936da4746aa"
_KNOWN_EXPOSURES_FINGERPRINT = "0666996faabb50abce0b8959c49980e36a655ea290618bc1463342d2ab5122f9"
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
class Exposed003Configuration:
    candidate_id: str
    source_candidate_id: str
    family_id: str
    family_ordinal: int
    parameters: Mapping[str, object]
    neighbor_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


@dataclass(frozen=True)
class IntradayExposed003Plan:
    path: Path
    sha256: str
    plan_fingerprint: str
    june_disposition_path: Path
    june_disposition_sha256: str
    june_disposition_fingerprint: str
    payload: Mapping[str, Any]
    june_disposition: Mapping[str, Any]
    source_plan: IntradayExposed002Plan
    configurations: tuple[Exposed003Configuration, ...]
    periods: tuple[Exposed002Period, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(
            self,
            "june_disposition",
            MappingProxyType(dict(self.june_disposition)),
        )


def load_intraday_exposed_003_plan(repository: Path) -> IntradayExposed003Plan:
    repository = repository.resolve()
    path, payload = _load_fingerprinted(
        repository,
        PLAN_RELATIVE_PATH,
        REVIEWED_PLAN_SHA256,
        "plan_fingerprint",
        REVIEWED_PLAN_FINGERPRINT,
        "Intraday Exposed 003 plan",
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
        raise ValueError("Intraday Exposed 003 plan identity differs")

    source_plan = load_intraday_exposed_002_plan(repository)
    _verify_source_design(payload, source_plan)
    _verify_implementation(repository, payload)
    _verify_runtime_boundary(payload)
    june_path, june_disposition = _load_fingerprinted(
        repository,
        JUNE_DISPOSITION_RELATIVE_PATH,
        REVIEWED_JUNE_DISPOSITION_SHA256,
        "disposition_fingerprint",
        REVIEWED_JUNE_DISPOSITION_FINGERPRINT,
        "Intraday Exposed 003 June disposition",
    )
    _verify_june_disposition(repository, payload, june_disposition)
    _verify_plan_review(repository)
    configurations = tuple(
        Exposed003Configuration(
            _rekey(item.candidate_id),
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
        or any(not item.candidate_id.startswith("ie003-") for item in configurations)
    ):
        raise ValueError("Intraday Exposed 003 candidate identities differ")
    return IntradayExposed003Plan(
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
        source_plan.periods,
    )


def _verify_source_design(payload: Mapping[str, Any], source_plan: IntradayExposed002Plan) -> None:
    source = _mapping(payload.get("source_design"), "source design")
    if (
        source.get("path") != "config/research/intraday-exposed-002-plan-v1.json"
        or source.get("program_id") != "intraday-exposed-002"
        or source.get("sha256") != SOURCE_PLAN_SHA256
        or source.get("fingerprint") != SOURCE_PLAN_FINGERPRINT
        or source.get("amendment_sha256") != REVIEWED_PLAN_AMENDMENT_SHA256
        or source.get("amendment_fingerprint") != REVIEWED_PLAN_AMENDMENT_FINGERPRINT
        or source.get("data_binding_sha256") != REVIEWED_DATA_BINDING_SHA256
        or source.get("data_binding_fingerprint") != REVIEWED_DATA_BINDING_FINGERPRINT
        or source.get("reuse_mode") != "exact-source-fields-with-campaign-identities-rekeyed-only"
        or source.get("exact_reuse_sections") != _EXACT_REUSE_SECTIONS
        or source.get("parent_configuration_count") != len(source_plan.configurations)
        or source.get("discovery_run_count") != len(source_plan.configurations) * 2
        or source.get("runtime_rows_imported") is not False
        or source.get("result_dependent_design_change") is not False
    ):
        raise ValueError("Intraday Exposed 003 source-design binding differs")


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
        raise ValueError("Intraday Exposed 003 implementation binding differs")


def _verify_runtime_boundary(payload: Mapping[str, Any]) -> None:
    cost = _mapping(payload.get("cost_model"), "cost model")
    data = _mapping(payload.get("data_reuse"), "data reuse")
    identity = _mapping(payload.get("identity"), "identity")
    attempts = _mapping(payload.get("research_attempts"), "research attempts")
    controlled = _mapping(payload.get("controlled_evaluation"), "controlled evaluation")
    protected = _mapping(payload.get("protected_boundaries"), "protected boundaries")
    if cost != {
        "path": "config/research/intraday-execution-cost-model-001-v1.json",
        "cost_model_id": "intraday-execution-cost-model-001-v1",
        "sha256": "a9e6c2b86c6623d73e089de591c55eeec0711fa55f0933a4e3ea9a1c0c2392af",
        "fingerprint": "94fc3ba4663b422fbb0dc0cce7e3d78a7ba81f22d71d5fa986ab6847b7925bb4",
        "recalibration_allowed": False,
    }:
        raise ValueError("Intraday Exposed 003 cost model differs")
    if (
        data.get("source_data_binding_path")
        != "config/research/intraday-exposed-002-data-binding-v1.json"
        or data.get("new_acquisition_allowed") is not False
        or data.get("june_data_access") is not False
        or data.get("latest_permitted_bar") != "2026-05-29T19:55:00Z"
        or data.get("full_integrity_reverification_required_before_runtime_state") is not True
        or identity.get("candidate_id_format")
        != "ie003-f{family_ordinal:02d}-a{first_axis_index:02d}-b{second_axis_index:02d}"
        or identity.get("reservation_id_format") != "ie003q-{run_fingerprint_prefix_24}"
        or identity.get("run_id_format") != "ie003r-{run_fingerprint_prefix_24}"
        or identity.get("runtime_root") != ".trading-lab/intraday-exposed-003"
        or identity.get("database") != "intraday-exposed-003.sqlite3"
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
        or controlled.get("range_status") != "ineligible"
        or controlled.get("june_read") is not False
        or controlled.get("substitute_range") is not False
        or controlled.get("controlled_plan_creation") is not False
        or protected.get("paper_or_broker_state_access") is not False
        or protected.get("strategic_allocation_21_access") is not False
    ):
        raise ValueError("Intraday Exposed 003 runtime boundary differs")


def _verify_june_disposition(
    repository: Path,
    payload: Mapping[str, Any],
    disposition: Mapping[str, Any],
) -> None:
    dependency = _mapping(payload.get("june_disposition"), "June disposition dependency")
    if dependency != {
        "path": JUNE_DISPOSITION_RELATIVE_PATH.as_posix(),
        "sha256": REVIEWED_JUNE_DISPOSITION_SHA256,
        "fingerprint": REVIEWED_JUNE_DISPOSITION_FINGERPRINT,
        "status": "ineligible-before-strategy-results",
    }:
        raise ValueError("Intraday Exposed 003 June dependency differs")
    if (
        disposition.get("schema_version") != "intraday-exposed-controlled-range-disposition-v1"
        or disposition.get("disposition_id") != "intraday-exposed-003-june-disposition-v1"
        or disposition.get("program_id") != PROGRAM_ID
        or disposition.get("status") != "ineligible-before-strategy-results"
        or disposition.get("starting_main") != _STARTING_MAIN
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
        raise ValueError("Intraday Exposed 003 June disposition differs")
    _verify_known_exposure(repository, disposition)


def _verify_known_exposure(repository: Path, disposition: Mapping[str, Any]) -> None:
    _path, inventory = _load_fingerprinted(
        repository,
        _KNOWN_EXPOSURES_PATH,
        _KNOWN_EXPOSURES_SHA256,
        "inventory_fingerprint",
        _KNOWN_EXPOSURES_FINGERPRINT,
        "intraday exposure inventory",
    )
    entries = inventory.get("entries")
    if not isinstance(entries, list):
        raise ValueError("intraday exposure inventory entries differ")
    conflicts = [
        _mapping(value, "intraday exposure")
        for value in entries
        if isinstance(value, dict) and value.get("id") == "intraday-v2-real-market-results"
    ]
    audit = _mapping(disposition.get("audit"), "June audit")
    if (
        len(conflicts) != 1
        or conflicts[0].get("start") != "2025-07-01"
        or conflicts[0].get("end") != "2026-06-30"
        or conflicts[0].get("class") != "real-market-result-observed"
        or audit.get("known_exposures_sha256") != _KNOWN_EXPOSURES_SHA256
        or audit.get("known_exposures_fingerprint") != _KNOWN_EXPOSURES_FINGERPRINT
        or audit.get("conflicting_entry_id") != "intraday-v2-real-market-results"
        or audit.get("active_controlled_registry_june_experiment_rows") != 0
        or audit.get("active_controlled_registry_unconsumed_holdout_authorizations") != 0
    ):
        raise ValueError("Intraday Exposed 003 June exposure evidence differs")


def _verify_plan_review(repository: Path) -> None:
    _path, review = _load_fingerprinted(
        repository,
        PLAN_REVIEW_RELATIVE_PATH,
        REVIEWED_PLAN_REVIEW_SHA256,
        "review_fingerprint",
        REVIEWED_PLAN_REVIEW_FINGERPRINT,
        "Intraday Exposed 003 plan review",
    )
    reviewed_plan = _mapping(review.get("reviewed_plan"), "reviewed plan")
    reviewed_june = _mapping(review.get("reviewed_june_disposition"), "reviewed June disposition")
    if (
        review.get("schema_version") != "intraday-exposed-003-plan-independent-review-v1"
        or review.get("review_id") != "intraday-exposed-003-plan-independent-review-v1"
        or review.get("status") != "passed-before-exposed-003-implementation-or-strategy-results"
        or review.get("verdict") != "pass"
        or review.get("findings") != []
        or reviewed_plan
        != {
            "program_id": PROGRAM_ID,
            "path": PLAN_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_PLAN_SHA256,
            "plan_fingerprint": REVIEWED_PLAN_FINGERPRINT,
        }
        or reviewed_june
        != {
            "path": JUNE_DISPOSITION_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_JUNE_DISPOSITION_SHA256,
            "disposition_fingerprint": REVIEWED_JUNE_DISPOSITION_FINGERPRINT,
            "status": "ineligible-before-strategy-results",
        }
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
        raise ValueError("Intraday Exposed 003 plan review differs")


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
    if not candidate_id.startswith("ie002-"):
        raise ValueError("Intraday Exposed 002 candidate identity differs")
    return f"ie003-{candidate_id.removeprefix('ie002-')}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object")
    return value
