"""Credential-safe one-use Alpaca SIP qualification for Program 006."""

from __future__ import annotations

import fcntl
import hashlib
import os
import subprocess
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.request import Request

from . import program_005_alpaca as frozen
from .config import non_broker_subprocess_environment
from .fingerprints import canonical_json, fingerprint

PROGRAM_ID = "multi-hour-sector-etf-research-005"
_PREDECESSOR_ID = "multi-hour-sector-etf-research-004"
_PRIVATE_ROOT = Path(".trading-lab/program-006-free-alpaca")
_CREDENTIAL_NAMES = (
    "PROGRAM_006_ALPACA_API_KEY_ID",
    "PROGRAM_006_ALPACA_API_SECRET_KEY",
)
_IMPLEMENTATION_REVIEW_PATH = Path(
    "config/research/program-006-credential-safe-qualification-implementation-"
    "independent-review-v1.json"
)
_PROPOSAL_PATH = Path("config/research/program-006-source-qualification-authority-proposal-v1.json")
_REVIEW_PATH = Path(
    "config/research/program-006-source-qualification-authority-proposal-independent-review-v1.json"
)
_PROGRAM_005_PROPOSAL = {
    "path": "config/research/program-005-source-qualification-authority-proposal-v2.json",
    "sha256": "c3ebe6c5ca36cba26468fe75af952b0f8019188660840b287e7503e945335b00",
    "fingerprint": "e74b8131cf82646b56b2609e2c9de077cebe25993a2dcec7bcac6bb4735b2e6b",
}
_PROGRAM_005_PROPOSAL_REVIEW = {
    "path": (
        "config/research/program-005-source-qualification-authority-proposal-"
        "independent-review-v2.json"
    ),
    "sha256": "ff17381bac27ec3e049650fdfd5471e6f13c3c925ec474b01ff259fa0e8f6c53",
    "fingerprint": "f72387b3960223945de3ec37d5e93ed61ec3da1c01e45a0f9f01d5bd7f682923",
}
_PROGRAM_005_FAILURE = {
    "path": "config/research/program-005-source-qualification-terminal-failure-v1.json",
    "sha256": "20ff82cf99ddd396c3b1dff73df2dfdc4a002278270d631f6de1ca1b8deed99f",
    "fingerprint": "51bd01b08b99746fb2379cd3afbb6a51609f0d9dffcb643f36e73e3a6cff4841",
}
_PROGRAM_005_FAILURE_REVIEW = {
    "path": (
        "config/research/program-005-source-qualification-terminal-failure-"
        "independent-review-v1.json"
    ),
    "sha256": "00400b86622bf0258f59a818260a8f4bfff847413061db1509b6b9dec75c0cd2",
    "fingerprint": "23fe61c933cece1a81a2cca5ecc6490dc6aa7d98f9a09946e8560e0ba38435f2",
}
_AUTHORITY_SOURCE_PATHS = (
    Path("pyproject.toml"),
    Path("scripts/check_secrets.py"),
    Path("src/systematic_trading_lab/__init__.py"),
    Path("src/systematic_trading_lab/calendar.py"),
    Path("src/systematic_trading_lab/cli.py"),
    Path("src/systematic_trading_lab/config.py"),
    Path("src/systematic_trading_lab/domain.py"),
    Path("src/systematic_trading_lab/fingerprints.py"),
    Path("src/systematic_trading_lab/program_005_alpaca.py"),
    Path("src/systematic_trading_lab/program_006_alpaca.py"),
    Path("uv.lock"),
)
_IMPLEMENTATION_REVIEW_ASSERTIONS = frozenset(
    {
        "credential_presence_reports_names_only",
        "credential_absence_prevents_activation",
        "credential_absence_under_lock_prevents_consumption",
        "client_construction_precedes_consumption",
        "first_transport_boundary_is_irreversible",
        "post_boundary_failure_consumes",
        "second_run_is_rejected",
        "external_authorization_root_is_required",
        "repository_and_bindings_are_revalidated_under_lock",
        "program_005_scientific_contract_is_unchanged",
        "program_005_terminal_lineage_is_immutable",
        "provider_and_strategy_execution_were_not_used_in_review",
    }
)
_IMPLEMENTATION_REVIEW_KEYS = frozenset(
    {
        "schema_version",
        "review_id",
        "program_id",
        "reviewed_at",
        "status",
        "verdict",
        "findings",
        "reviewed_implementation",
        "review_scope",
        "verified_assertions",
        "verification",
        "authority",
        "protected_access",
        "proof_gap",
        "review_fingerprint",
    }
)
_PROPOSAL_REVIEW_ASSERTIONS = frozenset(
    {
        "successor_is_legitimate_after_zero_provider_requests",
        "change_is_control_plane_repair_not_provider_shopping",
        "exact_twenty_two_session_sample_is_preserved",
        "credential_presence_reveals_no_secret_information",
        "missing_credentials_cannot_activate_or_consume_authority",
        "consumption_boundary_tracks_first_provider_transport_attempt",
        "multiple_provider_looks_are_not_permitted",
        "toctou_controls_are_preserved",
        "mutable_provenance_cannot_self_authorize",
        "program_005_terminal_records_are_immutable",
        "scientific_controls_are_unchanged",
        "controlled_and_protected_boundaries_are_untouched",
    }
)
_PROPOSAL_REVIEW_KEYS = frozenset(
    {
        "schema_version",
        "review_id",
        "program_id",
        "reviewed_at",
        "status",
        "verdict",
        "findings",
        "reviewed_proposal",
        "reviewed_implementation",
        "reviewed_implementation_review",
        "review_scope",
        "verified_assertions",
        "credential_presence_at_review",
        "verification",
        "authority",
        "protected_access",
        "proof_gap",
        "required_next_user_action",
        "review_fingerprint",
    }
)


class Program006Error(ValueError):
    """Fail-closed Program 006 authority error."""


def credential_presence(
    environ: Mapping[str, str] | None = None,
) -> Mapping[str, bool]:
    """Return names and presence only; never expose credential values."""
    values = os.environ if environ is None else environ
    return {name: bool(values.get(name, "").strip()) for name in _CREDENTIAL_NAMES}


def credential_presence_preflight(
    environ: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    return tuple(name for name, present in credential_presence(environ).items() if not present)


def read_credentials(environ: Mapping[str, str] | None = None) -> tuple[str, str]:
    values = os.environ if environ is None else environ
    key_id, secret_key = (values.get(name, "").strip() for name in _CREDENTIAL_NAMES)
    if not key_id or not secret_key:
        raise Program006Error("Program 006 acquisition credentials are required")
    return key_id, secret_key


def scientific_preflight(repository: Path) -> Mapping[str, Any]:
    result = frozen.credential_free_preflight(repository, "qualification")
    expected = {
        "program_id": _PREDECESSOR_ID,
        "scope": "qualification",
        "method": "GET",
        "origin": "https://data.alpaca.markets",
        "path": "/v2/stocks/bars",
        "feed": "sip",
        "timeframe": "5Min",
        "adjustments": ["raw", "split,spin-off"],
        "asof": "2026-07-31",
        "requests_per_minute": 120,
        "logical_chain_count": 26,
        "reused_qualification_chain_count": 0,
        "request_chains_to_acquire": 26,
        "expected_http_responses_to_acquire": 28,
        "maximum_http_responses_to_acquire": 60,
        "maximum_downloaded_bytes": 64 * 1024**2,
        "maximum_credential_loads": 1,
        "automatic_transport_retries": 0,
        "credential_loaded": False,
        "provider_request_made": False,
        "strategy_calculation_allowed": False,
        "controlled_or_protected_access_allowed": False,
    }
    if any(result.get(key) != value for key, value in expected.items()):
        raise Program006Error("Program 006 scientific contract differs from Program 005")
    _validate_program_005_lineage(repository)
    return {**dict(result), "program_id": PROGRAM_ID}


def derive_active_authority(repository: Path) -> Mapping[str, Any]:
    repository = repository.resolve()
    preflight = scientific_preflight(repository)
    proposal, proposal_binding = frozen._load_control_artifact(
        repository, _PROPOSAL_PATH, "proposal_fingerprint", "Program 006 authority proposal"
    )
    review, review_binding = frozen._load_control_artifact(
        repository, _REVIEW_PATH, "review_fingerprint", "Program 006 authority review"
    )
    implementation_review, implementation_review_binding = frozen._load_control_artifact(
        repository,
        _IMPLEMENTATION_REVIEW_PATH,
        "review_fingerprint",
        "Program 006 implementation review",
    )
    implementation = _validate_proposal(
        repository,
        proposal,
        implementation_review,
        implementation_review_binding,
        preflight,
    )
    _validate_review(
        proposal,
        proposal_binding,
        review,
        implementation,
        implementation_review_binding,
    )
    _repository_preflight(
        repository,
        implementation,
        implementation_review,
        proposal_binding,
        review,
    )
    activation = frozen._mapping(proposal.get("activation_contract"), "activation contract")
    unsigned: dict[str, Any] = {
        "schema_version": "program-006-source-authority-v1",
        "status": "ACTIVE-ONE-USE",
        "authority_id": activation.get("future_authority_id"),
        "program_id": PROGRAM_ID,
        "scope": "qualification",
        "request_plan_fingerprint": preflight["request_plan_fingerprint"],
        "consumption_boundary": activation.get("consumption_boundary"),
        "authority": _authority_flags(active=True),
        "bindings": {
            "authority_proposal": proposal_binding,
            "independent_review": review_binding,
            "program_005_terminal_failure": _PROGRAM_005_FAILURE,
        },
        "implementation_binding": implementation,
    }
    return {**unsigned, "authority_fingerprint": fingerprint(unsigned)}


def activate_authority(
    repository: Path,
    authorization_root: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> Mapping[str, Any]:
    repository = repository.resolve()
    authority = derive_active_authority(repository)
    _require_credentials_present(environ)
    if authority.get("authority_fingerprint") != authorization_root:
        raise Program006Error("Program 006 external authorization root differs")
    path = _active_authority_path(repository)
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / "run.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        _reject_existing_state(repository)
        authority = derive_active_authority(repository)
        _require_credentials_present(environ)
        if authority.get("authority_fingerprint") != authorization_root:
            raise Program006Error("Program 006 external authorization root differs")
        frozen._write_fsynced(
            path,
            (canonical_json(authority) + "\n").encode(),
            exclusive=True,
        )
        frozen._fsync_directory(path.parent)
    return authority


def load_active_authority(
    repository: Path,
    authorization_root: str,
    request_plan_fingerprint: str,
) -> Mapping[str, Any]:
    repository = repository.resolve()
    expected = derive_active_authority(repository)
    path = _active_authority_path(repository)
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise Program006Error("Program 006 source authority is absent or unreadable") from error
    authority = frozen._load_json_object(raw, "Program 006 authority")
    if (
        authorization_root != expected.get("authority_fingerprint")
        or request_plan_fingerprint != expected.get("request_plan_fingerprint")
        or raw != (canonical_json(expected) + "\n").encode()
        or authority != expected
    ):
        raise Program006Error("Program 006 source authority is not exact or externally authorized")
    return authority


def execute_qualification(
    repository: Path,
    private_root: Path,
    authorization_root: str,
    *,
    environ: Mapping[str, str] | None = None,
    transport: Callable[[Request], frozen.HttpPage] = frozen._urlopen_page,
    pace: Callable[[], None] | None = None,
) -> Mapping[str, Any]:
    repository = repository.resolve()
    if private_root.resolve() != (repository / _PRIVATE_ROOT).resolve():
        raise Program006Error("Program 006 private root differs from the frozen repository root")
    bundle = frozen.load_contract(repository)
    chains = frozen.build_request_plan(bundle, "qualification")
    preflight = scientific_preflight(repository)
    authority = load_active_authority(
        repository,
        authorization_root,
        str(preflight["request_plan_fingerprint"]),
    )
    scope_root = private_root / "qualification"
    scope_root.mkdir(parents=True, exist_ok=True)
    with (scope_root / "run.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        _reject_existing_run_state(scope_root)
        authority = load_active_authority(
            repository,
            authorization_root,
            str(preflight["request_plan_fingerprint"]),
        )
        _require_credentials_present(environ)
        key_id, secret_key = read_credentials(environ)
        implementation = frozen._mapping(
            authority.get("implementation_binding"), "active implementation binding"
        )
        budget = frozen.AcquisitionBudget(
            int(preflight["maximum_http_responses_to_acquire"]),
            int(preflight["maximum_downloaded_bytes"]),
        )
        claim_path = scope_root / "claim.json"
        claim_written = False

        def consuming_transport(request: Request) -> frozen.HttpPage:
            nonlocal claim_written
            if not claim_written:
                frozen._publish_record(
                    claim_path,
                    {
                        "schema_version": "program-006-private-authority-claim-v1",
                        "scope": "qualification",
                        "authority_id": authority.get("authority_id"),
                        "authority_fingerprint": authority.get("authority_fingerprint"),
                        "source_commit": implementation.get("source_commit"),
                        "implementation_root": implementation.get("implementation_root"),
                        "authority_bindings": authority.get("bindings"),
                        "request_plan_fingerprint": preflight["request_plan_fingerprint"],
                        "consumption_boundary": (
                            "immediately before first provider transport invocation"
                        ),
                    },
                )
                claim_written = True
            return transport(request)

        client = frozen.AlpacaBarsClient(
            key_id,
            secret_key,
            transport=consuming_transport,
            pace=pace,
        )
        try:
            for chain in chains:
                frozen.acquire_chain(
                    chain,
                    frozen._chain_root(private_root, "qualification", chain),
                    client,
                    budget,
                    source_commit=str(implementation.get("source_commit")),
                )
            if not claim_written:
                raise Program006Error("Program 006 qualification made no provider attempt")
            public_manifest = frozen.freeze_dataset(
                bundle,
                "qualification",
                chains,
                private_root,
                source_commit=str(implementation.get("source_commit")),
                program_id=PROGRAM_ID,
                credential_names=_CREDENTIAL_NAMES,
            )
        except frozen.Program005TransportError as error:
            if claim_written:
                frozen._publish_record(
                    scope_root / "terminal-transport-failure.json",
                    {
                        "schema_version": "program-006-private-transport-failure-v1",
                        "scope": "qualification",
                        "status": error.status,
                        "provider_transport_attempted": True,
                        "scientific_use_consumed": True,
                        "automatic_retry_count": 0,
                        "completed_response_count": budget.responses,
                        "completed_response_bytes": budget.response_bytes,
                        "credentials_stored": False,
                    },
                )
            raise
        except Exception as error:
            if claim_written:
                failure = {
                    "schema_version": "program-006-private-qualification-failure-v1",
                    "scope": "qualification",
                    "failure_class": (
                        "structural" if isinstance(error, ValueError) else "internal"
                    ),
                    "provider_transport_attempted": True,
                    "scientific_use_consumed": True,
                    "completed_response_count": budget.responses,
                    "completed_response_bytes": budget.response_bytes,
                    "automatic_retry_count": 0,
                    "credentials_stored": False,
                    "strategy_calculation_performed": False,
                }
                with suppress(OSError):
                    frozen._publish_record(
                        scope_root / "terminal-qualification-failure.json", failure
                    )
            raise
        receipt = {
            "schema_version": "program-006-private-acquisition-receipt-v1",
            "scope": "qualification",
            "authority_id": authority.get("authority_id"),
            "authority_fingerprint": authority.get("authority_fingerprint"),
            "dataset_id": public_manifest.get("dataset_id"),
            "source_qualification": True,
            "full_market_data_acquisition": False,
            "real_dataset_admission": False,
            "http_response_count": budget.responses,
            "response_bytes": budget.response_bytes,
            "credential_loads": 1,
            "automatic_transport_retries": 0,
            "strategy_calculation_performed": False,
            "controlled_or_protected_accessed": False,
            "broker_write_performed": False,
        }
        frozen._publish_record(scope_root / "receipt.json", receipt)
        return public_manifest


def _validate_program_005_lineage(repository: Path) -> None:
    proposal = _load_static_artifact(repository, _PROGRAM_005_PROPOSAL, "proposal_fingerprint")
    _load_static_artifact(repository, _PROGRAM_005_PROPOSAL_REVIEW, "review_fingerprint")
    failure = _load_static_artifact(repository, _PROGRAM_005_FAILURE, "failure_fingerprint")
    failure_review = _load_static_artifact(
        repository, _PROGRAM_005_FAILURE_REVIEW, "review_fingerprint"
    )
    runtime = frozen._mapping(failure.get("runtime_outcome"), "Program 005 runtime outcome")
    structural = frozen._mapping(failure.get("structural_results"), "Program 005 results")
    protected = frozen._mapping(failure.get("protected_state"), "Program 005 protected state")
    if (
        proposal.get("program_id") != _PREDECESSOR_ID
        or failure.get("status") != "TERMINAL-FAIL-CONSUMED-NO-RETRY"
        or runtime.get("credential_load_count") != 0
        or runtime.get("provider_request_count") != 0
        or runtime.get("http_response_count") != 0
        or runtime.get("response_bytes") != 0
        or structural.get("known_mdy_coordinate_outcomes") != "NOT-OBSERVED"
        or structural.get("source_qualification") != "FAIL"
        or any(protected.values())
        or failure_review.get("verdict") != "PASS"
        or failure_review.get("findings") != []
    ):
        raise Program006Error("Program 005 terminal lineage differs")


def _load_static_artifact(
    repository: Path,
    binding: Mapping[str, str],
    fingerprint_field: str,
) -> Mapping[str, Any]:
    path = repository / binding["path"]
    raw = path.read_bytes()
    payload = frozen._load_json_object(raw, path.name)
    if (
        hashlib.sha256(raw).hexdigest() != binding["sha256"]
        or payload.get(fingerprint_field) != binding["fingerprint"]
    ):
        raise Program006Error(f"Program 006 static binding differs: {path.name}")
    return payload


def _validate_proposal(
    repository: Path,
    proposal: Mapping[str, Any],
    implementation_review: Mapping[str, Any],
    implementation_review_binding: Mapping[str, Any],
    preflight: Mapping[str, Any],
) -> Mapping[str, Any]:
    expected_keys = {
        "schema_version",
        "proposal_id",
        "program_id",
        "created_at",
        "status",
        "purpose",
        "scope",
        "active_authority",
        "program_005_lineage",
        "bindings",
        "implementation_binding",
        "qualification",
        "credential_lifecycle",
        "activation_contract",
        "private_data",
        "state_at_proposal",
        "authority",
        "proposal_fingerprint",
    }
    if (
        set(proposal) != expected_keys
        or proposal.get("schema_version")
        != "program-006-source-qualification-authority-proposal-v1"
        or proposal.get("proposal_id")
        != "program-006-source-qualification-authority-proposal-2026-08-28-v1"
        or proposal.get("program_id") != PROGRAM_ID
        or not isinstance(proposal.get("created_at"), str)
        or proposal.get("status") != "BLOCKED-CREDENTIALS-NOT-VISIBLE-TO-RUNTIME"
        or proposal.get("purpose")
        != "one-use free Alpaca Basic historical SIP structural source qualification only"
        or proposal.get("scope") != "qualification"
        or proposal.get("active_authority") is not False
        or proposal.get("authority") != _authority_flags(active=False)
        or any(frozen._mapping(proposal.get("state_at_proposal"), "proposal state").values())
    ):
        raise Program006Error("Program 006 authority proposal semantics differ")
    lineage = frozen._mapping(proposal.get("program_005_lineage"), "Program 005 lineage")
    if lineage != {
        "program_id": _PREDECESSOR_ID,
        "failure_class": "CONTROL-PLANE-CREDENTIAL-AVAILABILITY",
        "source_suitability": "UNOBSERVED",
        "provider_request_count": 0,
        "http_response_count": 0,
        "response_bytes": 0,
        "strategy_returns_generated_or_read": False,
        "terminal_failure_immutable": True,
        "authority_v2_consumed": True,
        "retry_or_v3_allowed": False,
    }:
        raise Program006Error("Program 006 predecessor lineage differs")
    bindings = frozen._mapping(proposal.get("bindings"), "proposal bindings")
    expected_bindings = {
        **_static_bindings(),
        "implementation_review": implementation_review_binding,
    }
    if bindings != expected_bindings:
        raise Program006Error("Program 006 authority proposal bindings differ")
    implementation = frozen._mapping(
        proposal.get("implementation_binding"), "implementation binding"
    )
    _validate_implementation_binding(implementation)
    _validate_implementation_review(implementation_review, implementation)
    predecessor = _load_static_artifact(repository, _PROGRAM_005_PROPOSAL, "proposal_fingerprint")
    predecessor_qualification = frozen._mapping(
        predecessor.get("qualification"), "Program 005 qualification"
    )
    expected_qualification = dict(predecessor_qualification)
    credential_boundary = dict(
        frozen._mapping(
            predecessor_qualification.get("credential_boundary"),
            "Program 005 credential boundary",
        )
    )
    credential_boundary["environment_variables"] = list(_CREDENTIAL_NAMES)
    expected_qualification["credential_boundary"] = credential_boundary
    if proposal.get("qualification") != expected_qualification:
        raise Program006Error("Program 006 scientific qualification differs from Program 005")
    qualification = frozen._mapping(proposal.get("qualification"), "qualification")
    if qualification.get("request_plan_fingerprint") != preflight.get("request_plan_fingerprint"):
        raise Program006Error("Program 006 request plan fingerprint differs")
    credential = frozen._mapping(proposal.get("credential_lifecycle"), "credential lifecycle")
    if credential != {
        "environment_variables": list(_CREDENTIAL_NAMES),
        "credential_file_supported": False,
        "presence_output": ["PASS", "MISSING: <NON-SECRET ENVIRONMENT VARIABLE NAME>"],
        "presence_checked_before_activation": True,
        "presence_rechecked_under_lock": True,
        "credential_values_reported_hashed_or_persisted": False,
        "authenticated_client_constructed_before_consumption": True,
    }:
        raise Program006Error("Program 006 credential lifecycle differs")
    activation = frozen._mapping(proposal.get("activation_contract"), "activation contract")
    if activation != {
        "future_authority_id": "program-006-source-qualification-authority-2026-08-28-v1",
        "authorization_root_is_external": True,
        "mutable_child_hashes_cannot_self_authorize": True,
        "clean_head_main_origin_required": True,
        "repository_and_bindings_revalidated_under_lock": True,
        "credential_presence_required_before_activation": True,
        "credential_presence_revalidated_under_lock": True,
        "consumption_boundary": "immediately before first provider transport invocation",
        "first_provider_transport_attempt_consumes": True,
        "ambiguous_transport_outcome_consumes": True,
        "provider_failure_after_boundary_consumes": True,
        "automatic_transport_retries": 0,
        "remaining_acquisition_or_strategy_authority": False,
    }:
        raise Program006Error("Program 006 activation contract differs")
    private_data = frozen._mapping(proposal.get("private_data"), "private-data contract")
    if private_data != {
        "root": _PRIVATE_ROOT.as_posix(),
        "git_ignored": True,
        "provider_observations_public": False,
        "reconstructable_observations_public": False,
        "credentials_stored_or_logged": False,
    }:
        raise Program006Error("Program 006 private-data contract differs")
    return implementation


def _validate_implementation_review(
    review: Mapping[str, Any], implementation: Mapping[str, Any]
) -> None:
    assertions = frozen._mapping(review.get("verified_assertions"), "review assertions")
    if (
        set(review) != _IMPLEMENTATION_REVIEW_KEYS
        or review.get("schema_version")
        != "program-006-credential-safe-qualification-implementation-independent-review-v1"
        or review.get("review_id")
        != "program-006-credential-safe-qualification-implementation-independent-review-"
        "2026-08-28-v1"
        or review.get("program_id") != PROGRAM_ID
        or review.get("status") != "PASS"
        or review.get("verdict") != "PASS"
        or review.get("findings") != []
        or review.get("reviewed_implementation") != implementation
        or set(assertions) != _IMPLEMENTATION_REVIEW_ASSERTIONS
        or any(value is not True for value in assertions.values())
        or review.get("authority") != _authority_flags(active=False)
        or any(frozen._mapping(review.get("protected_access"), "protected access").values())
    ):
        raise Program006Error("Program 006 implementation review differs")


def _validate_review(
    proposal: Mapping[str, Any],
    proposal_binding: Mapping[str, Any],
    review: Mapping[str, Any],
    implementation: Mapping[str, Any],
    implementation_review_binding: Mapping[str, Any],
) -> None:
    assertions = frozen._mapping(review.get("verified_assertions"), "review assertions")
    reviewed_proposal = frozen._mapping(review.get("reviewed_proposal"), "reviewed proposal")
    if (
        set(review) != _PROPOSAL_REVIEW_KEYS
        or review.get("schema_version")
        != "program-006-source-qualification-authority-proposal-independent-review-v1"
        or review.get("review_id")
        != "program-006-source-qualification-authority-proposal-independent-review-2026-08-28-v1"
        or review.get("program_id") != PROGRAM_ID
        or review.get("status") != "PASS-CONTROL-DESIGN-BLOCKED-CREDENTIALS"
        or review.get("verdict") != "PASS"
        or review.get("findings") != []
        or reviewed_proposal
        != {
            **dict(proposal_binding),
            "proposal_id": proposal.get("proposal_id"),
            "schema_version": proposal.get("schema_version"),
            "proposal_artifact_commit": reviewed_proposal.get("proposal_artifact_commit"),
        }
        or not frozen._is_lower_hex(reviewed_proposal.get("proposal_artifact_commit"), 40)
        or review.get("reviewed_implementation") != implementation
        or review.get("reviewed_implementation_review") != implementation_review_binding
        or set(assertions) != _PROPOSAL_REVIEW_ASSERTIONS
        or any(value is not True for value in assertions.values())
        or review.get("credential_presence_at_review")
        != [{"name": name, "present": False} for name in _CREDENTIAL_NAMES]
        or review.get("authority") != _authority_flags(active=False)
        or any(frozen._mapping(review.get("protected_access"), "protected access").values())
    ):
        raise Program006Error("Program 006 proposal review differs")


def _validate_implementation_binding(implementation: Mapping[str, Any]) -> None:
    source_files = implementation.get("source_files")
    if (
        set(implementation) != {"source_commit", "implementation_root", "source_files"}
        or not frozen._is_lower_hex(implementation.get("source_commit"), 40)
        or not isinstance(source_files, list)
        or len(source_files) != len(_AUTHORITY_SOURCE_PATHS)
        or implementation.get("implementation_root") != fingerprint(source_files)
    ):
        raise Program006Error("Program 006 implementation binding differs")
    for item, path in zip(source_files, _AUTHORITY_SOURCE_PATHS, strict=True):
        source = frozen._mapping(item, "implementation source")
        if (
            set(source) != {"path", "sha256"}
            or source.get("path") != path.as_posix()
            or not frozen._is_lower_hex(source.get("sha256"), 64)
        ):
            raise Program006Error("Program 006 implementation source manifest differs")


def _repository_preflight(
    repository: Path,
    implementation: Mapping[str, Any],
    implementation_review: Mapping[str, Any],
    proposal_binding: Mapping[str, Any],
    review: Mapping[str, Any],
) -> None:
    source_commit = str(implementation.get("source_commit"))
    environment = non_broker_subprocess_environment()
    environment.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    command = (
        "git",
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-C",
        str(repository),
    )

    def git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            (*command, *arguments),
            check=check,
            capture_output=True,
            text=True,
            env=environment,
        )

    try:
        head = git("rev-parse", "HEAD").stdout.strip()
        main = git("rev-parse", "refs/heads/main").stdout.strip()
        origin_main = git("rev-parse", "refs/remotes/origin/main").stdout.strip()
        dirty = git("status", "--porcelain", "--untracked-files=all").stdout

        def added(path: Path) -> str:
            commits = git(
                "log", "--diff-filter=A", "--format=%H", "--", path.as_posix()
            ).stdout.splitlines()
            if len(commits) != 1:
                raise Program006Error("Program 006 control artifact history differs")
            return commits[0]

        implementation_review_added = added(_IMPLEMENTATION_REVIEW_PATH)
        proposal_added = added(_PROPOSAL_PATH)
        review_added = added(_REVIEW_PATH)
        lineage = (
            (source_commit, implementation_review_added),
            (implementation_review_added, proposal_added),
            (proposal_added, review_added),
            (review_added, head),
        )
        if any(
            git("merge-base", "--is-ancestor", earlier, later, check=False).returncode
            for earlier, later in lineage
        ):
            raise Program006Error("Program 006 control artifact ancestry differs")
        changed = git(
            "diff",
            "--name-only",
            source_commit,
            head,
            "--",
            *(path.as_posix() for path in _AUTHORITY_SOURCE_PATHS),
        ).stdout
        committed = {
            path: git("show", f"{commit}:{path.as_posix()}").stdout.encode()
            for path, commit in (
                (_IMPLEMENTATION_REVIEW_PATH, implementation_review_added),
                (_PROPOSAL_PATH, proposal_added),
                (_REVIEW_PATH, review_added),
            )
        }
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        raise Program006Error("Program 006 repository identity is unavailable") from error
    reviewed_proposal = frozen._mapping(review.get("reviewed_proposal"), "reviewed proposal")
    reviewed_implementation = frozen._mapping(
        implementation_review.get("reviewed_implementation"), "reviewed implementation"
    )
    if (
        dirty
        or head != main
        or head != origin_main
        or changed
        or len({source_commit, implementation_review_added, proposal_added, review_added}) != 4
        or reviewed_implementation != implementation
        or reviewed_proposal.get("proposal_artifact_commit") != proposal_added
        or proposal_binding.get("sha256")
        != hashlib.sha256((repository / _PROPOSAL_PATH).read_bytes()).hexdigest()
        or any((repository / path).read_bytes() != contents for path, contents in committed.items())
    ):
        raise Program006Error("Program 006 reviewed implementation or control lineage differs")
    source_files = frozen._sequence(implementation.get("source_files"), "source files")
    for item, path in zip(source_files, _AUTHORITY_SOURCE_PATHS, strict=True):
        source = frozen._mapping(item, "implementation source")
        expected_sha256 = str(source.get("sha256"))
        if (
            frozen._file_sha256(repository / path) != expected_sha256
            or frozen._git_file_sha256(repository, source_commit, path) != expected_sha256
        ):
            raise Program006Error("Program 006 reviewed implementation bytes differ")


def _static_bindings() -> Mapping[str, Mapping[str, str]]:
    return {
        **{
            f"program_005_{name}": value
            for name, value in frozen._static_authority_bindings().items()
        },
        "program_005_authority_proposal_v2": _PROGRAM_005_PROPOSAL,
        "program_005_authority_proposal_review_v2": _PROGRAM_005_PROPOSAL_REVIEW,
        "program_005_terminal_failure": _PROGRAM_005_FAILURE,
        "program_005_terminal_failure_review": _PROGRAM_005_FAILURE_REVIEW,
    }


def _authority_flags(*, active: bool) -> Mapping[str, bool]:
    enabled = {"provider_contact", "credential_access", "source_requests", "source_qualification"}
    return {key: active and key in enabled for key in frozen._AUTHORITY_KEYS}


def _require_credentials_present(environ: Mapping[str, str] | None) -> None:
    missing = credential_presence_preflight(environ)
    if missing:
        raise Program006Error("Program 006 credentials missing: " + ", ".join(missing))


def _active_authority_path(repository: Path) -> Path:
    return repository / _PRIVATE_ROOT / "qualification" / "active-authority.json"


def _reject_existing_state(repository: Path) -> None:
    scope_root = repository / _PRIVATE_ROOT / "qualification"
    _reject_existing_run_state(scope_root, allow_active=False)
    if (repository / _PRIVATE_ROOT / "datasets").exists():
        raise Program006Error("Program 006 authority state already exists")


def _reject_existing_run_state(scope_root: Path, *, allow_active: bool = True) -> None:
    names = {
        "claim.json",
        "receipt.json",
        "terminal-transport-failure.json",
        "terminal-qualification-failure.json",
        "structural-failure.json",
        "chains",
    }
    if not allow_active:
        names.add("active-authority.json")
    if any((scope_root / name).exists() for name in names):
        raise Program006Error("Program 006 one-use authority state already exists")
