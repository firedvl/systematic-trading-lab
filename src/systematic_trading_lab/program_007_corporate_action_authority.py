"""One-use authority controls for Program 007 corporate-action metadata."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from . import program_005_alpaca as frozen
from . import program_007_alpaca as program_007
from . import program_007_corporate_actions as metadata
from .config import non_broker_subprocess_environment
from .fingerprints import canonical_json, fingerprint

PROGRAM_ID = metadata.PROGRAM_ID
FUTURE_AUTHORITY_ID = "program-007-corporate-action-metadata-qualification-authority-2026-08-29-v1"
BLOCKED_STATUS = "BLOCKED-CREDENTIALS-NOT-VISIBLE-TO-RUNTIME"
READY_STATUS = "READY FOR USER AUTHORIZATION"
CONSUMPTION_BOUNDARY = "immediately before first provider transport invocation"

REQUEST_PLAN_PATH = Path(
    "config/research/program-007-corporate-action-metadata-request-plan-v1.json"
)
PROPOSAL_PATH = Path(
    "config/research/program-007-corporate-action-metadata-qualification-authority-proposal-v1.json"
)
REVIEW_PATH = Path(
    "config/research/program-007-corporate-action-metadata-qualification-authority-"
    "proposal-independent-review-v1.json"
)

_LEDGER = {
    "path": "config/research/program-007-unit-changing-action-ledger-v3.json",
    "sha256": "e405529489921a0ec8883aa64e855e6600a99105387cbc9ed2766c82bc0826b1",
    "fingerprint": "37467ced2666cdb716706aa4310e48aa5b0938f168cafadf00f6dec72e336f4f",
}
_PLAN = {
    "path": "config/research/program-007-corporate-action-metadata-source-plan-v3.json",
    "sha256": "b61758a35ca896890946dfbef1b315d0827b8821a32c2399a7440350d620e0c2",
    "fingerprint": "6ac30c18035161414cd410ba83715b74c55cb14322f421eda517ea4af375adef",
}
_IMPLEMENTATION = {
    "path": "config/research/program-007-corporate-action-metadata-source-implementation-v6.json",
    "sha256": "14ccfd69d54d9035cc36ccc7915c044c2596c06836e400da0016d5c74e9e84eb",
    "fingerprint": "0d87ce202517fdd1c41275c6d81f9d937189dbb81f33ac7735df3c428791a289",
}
_IMPLEMENTATION_REVIEW = {
    "path": (
        "config/research/program-007-corporate-action-metadata-source-independent-review-v2.json"
    ),
    "sha256": "2a1199e223d036723040420e4e75abb9cbdfc503a35a88277164f9660c20a80b",
    "fingerprint": "d3aac3e4774096311339814277ed575df6d1744ca032702c0e50c4e36222b2e5",
}
_AUTHORITY_SOURCE_PATHS = (
    REQUEST_PLAN_PATH,
    Path("scripts/check_secrets.py"),
    Path("src/systematic_trading_lab/cli.py"),
    Path("src/systematic_trading_lab/config.py"),
    Path("src/systematic_trading_lab/fingerprints.py"),
    Path("src/systematic_trading_lab/program_005_alpaca.py"),
    Path("src/systematic_trading_lab/program_007_corporate_actions.py"),
    Path("src/systematic_trading_lab/program_007_corporate_action_authority.py"),
    Path("tests/unit/test_intraday_source_provenance.py"),
    Path("tests/unit/test_program_007_corporate_action_authority.py"),
)
_ENABLED_AUTHORITY = {
    "provider_contact",
    "credential_access",
    "source_requests",
    "source_qualification",
}


class Program007AuthorityError(ValueError):
    """Fail-closed Program 007 authority error."""


def credential_presence(environ: Mapping[str, str] | None = None) -> Mapping[str, bool]:
    """Return names and presence only; never expose credential values."""
    values = os.environ if environ is None else environ
    return {name: bool(values.get(name, "").strip()) for name in metadata.CREDENTIAL_NAMES}


def credential_presence_preflight(
    environ: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    return tuple(name for name, present in credential_presence(environ).items() if not present)


def read_credentials(environ: Mapping[str, str] | None = None) -> tuple[str, str]:
    values = os.environ if environ is None else environ
    credentials = tuple(values.get(name, "").strip() for name in metadata.CREDENTIAL_NAMES)
    if any(not value or "\r" in value or "\n" in value for value in credentials):
        raise Program007AuthorityError("Program 007 metadata credentials are required")
    return credentials[0], credentials[1]


def expected_request_plan() -> Mapping[str, Any]:
    chains = metadata.frozen_request_chains()
    unsigned: dict[str, Any] = {
        "schema_version": "program-007-corporate-action-metadata-request-plan-v1",
        "request_plan_id": "program-007-corporate-action-metadata-request-plan-2026-08-29-v1",
        "program_id": PROGRAM_ID,
        "status": "FROZEN-CREDENTIAL-FREE-NOT-AUTHORIZED",
        "role": "CORROBORATION + DISCREPANCY DETECTION",
        "request": {
            "method": "GET",
            "endpoint": metadata.ENDPOINT,
            "redirects": False,
            "types": "OMITTED",
            "pagination_token": "opaque page_token appended after fixed parameters",
        },
        "chains": [
            {
                "chain_id": chain.chain_id,
                "identity_parameter": chain.identity_parameter,
                "identities": list(chain.identities),
                "fixed_parameters": [list(parameter) for parameter in chain.parameters],
                "chain_fingerprint": chain.identity,
                "maximum_pages": chain.maximum_pages,
            }
            for chain in chains
        ],
        "recognized_event_types": list(metadata.EVENT_TYPES),
        "process_date_semantics": {
            "requested_interval_inclusive": True,
            "returned_process_date_required_inside_interval": True,
            "start_end_literal_process_date_filter_claimed": False,
            "process_date_is_economic_date": False,
            "creation_lag": "UNBOUNDED-NO-PROVIDER-GUARANTEE",
        },
        "transport_budget": {
            "minimum_http_requests": 2,
            "maximum_http_requests": metadata.MAXIMUM_HTTP_REQUESTS,
            "minimum_http_responses": 2,
            "maximum_http_responses": metadata.MAXIMUM_HTTP_RESPONSES,
            "maximum_pages_per_chain": metadata.MAXIMUM_PAGES_PER_CHAIN,
            "page_limit": 1000,
            "maximum_response_bytes": metadata.MAXIMUM_RESPONSE_PAGE_BYTES,
            "bounded_read_bytes": metadata.MAXIMUM_RESPONSE_PAGE_BYTES + 1,
            "maximum_total_bytes": metadata.MAXIMUM_DOWNLOADED_BYTES,
            "maximum_credential_loads": 1,
            "automatic_retries": metadata.AUTOMATIC_TRANSPORT_RETRIES,
        },
        "credential_names": list(metadata.CREDENTIAL_NAMES),
        "authentication_header_names": ["APCA-API-KEY-ID", "APCA-API-SECRET-KEY"],
        "authority": _authority_flags(active=False),
    }
    return {**unsigned, "request_plan_fingerprint": fingerprint(unsigned)}


def validate_proposal_chain(repository: Path) -> Mapping[str, Any]:
    """Validate immutable proposal inputs without loading credentials."""
    repository = repository.resolve()
    ledger = _load_static_artifact(repository, _LEDGER, "ledger_fingerprint")
    program_007.validate_action_ledger(ledger)
    plan = _load_static_artifact(repository, _PLAN, "proposal_fingerprint")
    implementation = _load_static_artifact(
        repository, _IMPLEMENTATION, "implementation_fingerprint"
    )
    implementation_review = _load_static_artifact(
        repository, _IMPLEMENTATION_REVIEW, "review_fingerprint"
    )
    request_plan, request_plan_binding = _load_control_artifact(
        repository, REQUEST_PLAN_PATH, "request_plan_fingerprint", "request plan"
    )
    if request_plan != expected_request_plan():
        raise Program007AuthorityError("Program 007 request plan differs")
    proposal, proposal_binding = _load_control_artifact(
        repository, PROPOSAL_PATH, "proposal_fingerprint", "authority proposal"
    )
    review, review_binding = _load_control_artifact(
        repository, REVIEW_PATH, "review_fingerprint", "authority proposal review"
    )
    _validate_proposal(
        proposal,
        request_plan_binding,
        plan,
        implementation,
        implementation_review,
    )
    _validate_review(proposal, proposal_binding, review)
    return {
        "proposal": proposal,
        "review": review,
        "proposal_binding": proposal_binding,
        "review_binding": review_binding,
        "request_plan": request_plan,
        "request_plan_binding": request_plan_binding,
    }


def derive_authorization_root(
    repository: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Mapping[str, Any]:
    controls = validate_proposal_chain(repository)
    proposal = _mapping(controls["proposal"], "authority proposal")
    if proposal.get("status") != READY_STATUS:
        raise Program007AuthorityError(
            "Program 007 authority proposal is blocked; no authorization root exists"
        )
    _require_credentials_present(environ)
    lineage = _repository_preflight(repository.resolve(), proposal, controls)
    unsigned: dict[str, Any] = {
        "schema_version": "program-007-corporate-action-metadata-authority-v1",
        "status": "ACTIVE-ONE-USE",
        "authority_id": FUTURE_AUTHORITY_ID,
        "program_id": PROGRAM_ID,
        "request_plan_fingerprint": controls["request_plan"]["request_plan_fingerprint"],
        "consumption_boundary": CONSUMPTION_BOUNDARY,
        "authority": _authority_flags(active=True),
        "bindings": {
            "proposal": controls["proposal_binding"],
            "proposal_review": controls["review_binding"],
            "request_plan": controls["request_plan_binding"],
            "ledger": _LEDGER,
            "source_plan": _PLAN,
            "source_implementation": _IMPLEMENTATION,
            "source_implementation_review": _IMPLEMENTATION_REVIEW,
        },
        "implementation_binding": proposal["authority_implementation_binding"],
        "control_lineage": lineage,
    }
    return {**unsigned, "authority_fingerprint": fingerprint(unsigned)}


def activate_authority(
    repository: Path,
    authorization_root: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> Mapping[str, Any]:
    repository = repository.resolve()
    authority = derive_authorization_root(repository, environ=environ)
    if authority.get("authority_fingerprint") != authorization_root:
        raise Program007AuthorityError("Program 007 external authorization root differs")
    root_descriptor = metadata._open_private_root(repository)
    try:
        with _locked_root(root_descriptor):
            _reject_existing_state(root_descriptor, allow_active=False)
            authority = derive_authorization_root(repository, environ=environ)
            _require_credentials_present(environ)
            if authority.get("authority_fingerprint") != authorization_root:
                raise Program007AuthorityError("Program 007 external authorization root differs")
            metadata._append_persistent_evidence(
                root_descriptor,
                "active-authority.json",
                (canonical_json(authority) + "\n").encode(),
            )
    finally:
        os.close(root_descriptor)
    return authority


def load_active_authority(
    repository: Path,
    authorization_root: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> Mapping[str, Any]:
    expected = derive_authorization_root(repository, environ=environ)
    path = repository.resolve() / metadata.PRIVATE_ROOT / "active-authority.json"
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise Program007AuthorityError("Program 007 metadata authority is absent") from error
    authority = _json_object(raw, "active authority")
    if (
        authorization_root != expected.get("authority_fingerprint")
        or authority != expected
        or raw != (canonical_json(expected) + "\n").encode()
    ):
        raise Program007AuthorityError(
            "Program 007 metadata authority is not exact or externally authorized"
        )
    return authority


def execute_qualification(
    repository: Path,
    authorization_root: str,
    *,
    environ: Mapping[str, str] | None = None,
    transport: Callable[[Request], metadata.RawResponse] | None = None,
) -> metadata.MetadataQualificationResult:
    """Run one reviewed qualification; the committed blocked proposal cannot reach transport."""
    repository = repository.resolve()
    root_descriptor = metadata._open_private_root(repository)
    claim_written = False
    budget = metadata._Budget()
    try:
        with _locked_root(root_descriptor):
            _reject_existing_state(root_descriptor)
            authority = load_active_authority(repository, authorization_root, environ=environ)
            public_ledger = program_007.load_action_ledger(repository / _LEDGER["path"])
            _require_credentials_present(environ)
            key_id, secret_key = read_credentials(environ)
            selected_transport = transport
            if selected_transport is None:

                def selected_transport(request: Request) -> metadata.RawResponse:
                    metadata._validate_http_request(request)
                    try:
                        with build_opener(metadata._NoRedirect()).open(
                            request, timeout=30
                        ) as response:
                            return metadata.RawResponse(
                                int(response.status),
                                response.read(metadata.MAXIMUM_RESPONSE_PAGE_BYTES + 1),
                            )
                    except HTTPError as error:
                        try:
                            return metadata.RawResponse(
                                error.code,
                                error.read(metadata.MAXIMUM_RESPONSE_PAGE_BYTES + 1),
                            )
                        finally:
                            error.close()

            client = metadata._AlpacaMetadataClient(
                key_id,
                secret_key,
                selected_transport,
            )

            def writer(key: str, payload: bytes) -> None:
                metadata._append_persistent_evidence(root_descriptor, key, payload)

            def response_for(
                intent: metadata.RequestIntent,
                _intent_key: str,
            ) -> metadata.RawResponse:
                nonlocal claim_written
                if not claim_written:
                    writer(
                        "claim.json",
                        canonical_json(
                            {
                                "schema_version": (
                                    "program-007-private-corporate-action-metadata-claim-v1"
                                ),
                                "authority_id": authority["authority_id"],
                                "authority_fingerprint": authority["authority_fingerprint"],
                                "request_plan_fingerprint": authority["request_plan_fingerprint"],
                                "consumption_boundary": CONSUMPTION_BOUNDARY,
                                "scientific_use_consumed": True,
                            }
                        ).encode(),
                    )
                    claim_written = True
                return client.get(intent)

            try:
                chains = tuple(
                    metadata._execute_chain(chain, budget, response_for, writer)
                    for chain in metadata.frozen_request_chains()
                )
                result = metadata.MetadataQualificationResult(
                    chains, metadata._reconcile_chains(chains)
                )
                metadata.generate_successor_ledger_candidate(result, public_ledger)
            except Exception as error:
                if claim_written:
                    with suppress(OSError, ValueError):
                        writer(
                            "terminal-failure.json",
                            canonical_json(
                                {
                                    "schema_version": (
                                        "program-007-private-corporate-action-metadata-failure-v1"
                                    ),
                                    "status": "TERMINAL-FAIL-CONSUMED-NO-RETRY",
                                    "failure_class": type(error).__name__,
                                    "provider_transport_attempted": True,
                                    "scientific_use_consumed": True,
                                    "completed_responses": budget.responses,
                                    "completed_response_bytes": budget.response_bytes,
                                    "automatic_retries": 0,
                                    "paid_upgrade_allowed": False,
                                    "fallback_allowed": False,
                                    "credentials_stored": False,
                                }
                            ).encode(),
                        )
                raise
            writer(
                "qualification-receipt.json",
                canonical_json(
                    {
                        "schema_version": (
                            "program-007-private-corporate-action-metadata-receipt-v1"
                        ),
                        "status": "METADATA-QUALIFICATION-PASS",
                        "authority_id": authority["authority_id"],
                        "request_count": budget.requests,
                        "response_count": result.response_count,
                        "response_bytes": result.response_bytes,
                        "credential_loads": 1,
                        "automatic_retries": 0,
                        "dataset_admitted": False,
                        "strategy_calculations": 0,
                        "strategy_returns": 0,
                        "credentials_stored": False,
                        "observed_at": _utc_now(),
                    }
                ).encode(),
            )
            return result
    finally:
        os.close(root_descriptor)


class _LockedRoot:
    def __init__(self, root_descriptor: int) -> None:
        self._root_descriptor = root_descriptor
        self._handle: BinaryIO | None = None

    def __enter__(self) -> None:
        descriptor = os.open(
            "run.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
            dir_fd=self._root_descriptor,
        )
        self._handle = os.fdopen(descriptor, "a+b", buffering=0)
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)

    def __exit__(self, *_args: object) -> None:
        assert self._handle is not None
        self._handle.close()


def _locked_root(root_descriptor: int) -> _LockedRoot:
    return _LockedRoot(root_descriptor)


def _authority_flags(*, active: bool) -> Mapping[str, bool]:
    if set(metadata._AUTHORITY) != {
        "provider_contact",
        "subscription_purchase",
        "credential_access",
        "source_requests",
        "source_qualification",
        "market_data_acquisition",
        "real_dataset_admission",
        "strategy_implementation",
        "strategy_execution",
        "research_qualification",
        "controlled_evaluation",
        "protected_holdout",
        "paper_execution",
        "broker_writes",
        "live_execution",
    }:
        raise Program007AuthorityError("Program 007 authority field set differs")
    return {key: active and key in _ENABLED_AUTHORITY for key in metadata._AUTHORITY}


def _require_credentials_present(environ: Mapping[str, str] | None) -> None:
    missing = credential_presence_preflight(environ)
    if missing:
        raise Program007AuthorityError("Program 007 credentials missing: " + ", ".join(missing))


def _load_static_artifact(
    repository: Path,
    binding: Mapping[str, str],
    fingerprint_field: str,
) -> Mapping[str, Any]:
    path = repository / binding["path"]
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise Program007AuthorityError(f"Program 007 binding is absent: {path.name}") from error
    payload = _json_object(raw, path.name)
    if (
        hashlib.sha256(raw).hexdigest() != binding["sha256"]
        or payload.get(fingerprint_field) != binding["fingerprint"]
    ):
        raise Program007AuthorityError(f"Program 007 binding differs: {path.name}")
    return payload


def _load_control_artifact(
    repository: Path,
    relative: Path,
    fingerprint_field: str,
    label: str,
) -> tuple[Mapping[str, Any], Mapping[str, str]]:
    try:
        raw = (repository / relative).read_bytes()
    except OSError as error:
        raise Program007AuthorityError(f"Program 007 {label} is absent") from error
    payload = _json_object(raw, label)
    unsigned = dict(payload)
    stored = unsigned.pop(fingerprint_field, None)
    if not frozen._is_lower_hex(stored, 64) or stored != fingerprint(unsigned):
        raise Program007AuthorityError(f"Program 007 {label} differs")
    return payload, {
        "path": relative.as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "fingerprint": stored,
    }


def _validate_proposal(
    proposal: Mapping[str, Any],
    request_plan_binding: Mapping[str, str],
    plan: Mapping[str, Any],
    implementation: Mapping[str, Any],
    implementation_review: Mapping[str, Any],
) -> None:
    credentials = _mapping(proposal.get("credential_lifecycle"), "credential lifecycle")
    qualification = _mapping(proposal.get("qualification"), "qualification")
    activation = _mapping(proposal.get("activation_contract"), "activation contract")
    state = _mapping(proposal.get("state_at_proposal"), "proposal state")
    bindings = _mapping(proposal.get("bindings"), "proposal bindings")
    source_binding = _mapping(
        proposal.get("authority_implementation_binding"), "authority implementation binding"
    )
    source_files = _sequence(source_binding.get("source_files"), "authority source files")
    if (
        proposal.get("schema_version")
        != "program-007-corporate-action-metadata-qualification-authority-proposal-v1"
        or proposal.get("proposal_id")
        != "program-007-corporate-action-metadata-qualification-authority-proposal-2026-08-29-v1"
        or proposal.get("program_id") != PROGRAM_ID
        or proposal.get("status") != BLOCKED_STATUS
        or proposal.get("active_authority") is not False
        or proposal.get("source_role") != "CORROBORATION + DISCREPANCY DETECTION"
        or proposal.get("authority") != _authority_flags(active=False)
        or any(state.values())
        or bindings
        != {
            "ledger_v3": _LEDGER,
            "source_plan_v3": _PLAN,
            "source_implementation_v6": _IMPLEMENTATION,
            "source_implementation_review_v2": _IMPLEMENTATION_REVIEW,
            "request_plan_v1": request_plan_binding,
        }
        or plan.get("proposal_fingerprint") != _PLAN["fingerprint"]
        or implementation.get("implementation_fingerprint") != _IMPLEMENTATION["fingerprint"]
        or implementation_review.get("review_fingerprint") != _IMPLEMENTATION_REVIEW["fingerprint"]
        or credentials
        != {
            "environment_variables": list(metadata.CREDENTIAL_NAMES),
            "authentication_header_names": ["APCA-API-KEY-ID", "APCA-API-SECRET-KEY"],
            "presence_preflight": "MISSING",
            "missing_at_proposal": list(metadata.CREDENTIAL_NAMES),
            "values_exposed": False,
            "values_stored_hashed_or_logged": False,
            "presence_required_before_root": True,
            "presence_rechecked_under_lock": True,
            "maximum_successful_loads": 1,
            "missing_before_transport_consumes_use": False,
        }
        or qualification != _expected_qualification()
        or activation != _expected_activation_contract()
        or len(source_files) != len(_AUTHORITY_SOURCE_PATHS)
        or source_binding.get("implementation_root") != fingerprint(source_files)
        or not frozen._is_lower_hex(source_binding.get("source_commit"), 40)
        or [item.get("path") for item in source_files if isinstance(item, Mapping)]
        != [path.as_posix() for path in _AUTHORITY_SOURCE_PATHS]
    ):
        raise Program007AuthorityError("Program 007 authority proposal semantics differ")


def _validate_review(
    proposal: Mapping[str, Any],
    proposal_binding: Mapping[str, str],
    review: Mapping[str, Any],
) -> None:
    reviewed = _mapping(review.get("reviewed_proposal"), "reviewed proposal")
    challenges = _mapping(review.get("required_challenges"), "review challenges")
    expected_challenges = {
        "correct_ledger_v3": "PASS",
        "alpaca_only_corroboration_and_discrepancy": "PASS",
        "creation_lag_unbounded": "PASS",
        "missing_positive_controls_fail": "PASS",
        "unexpected_relevant_actions_fail": "PASS",
        "symbol_cusip_disagreement_fatal": "PASS",
        "transport_ceilings_exact": "PASS",
        "metadata_endpoint_only": "PASS",
        "credentials_checked_before_consumption": "PASS",
        "consumption_immediately_before_transport": "PASS",
        "credential_failure_can_burn_use": "NO",
        "ambiguous_transport_gets_free_retry": "NO",
        "mutable_artifacts_self_authorize": "NO",
        "ohlcv_authorized": "NO",
        "strategy_calculation_authorized": "NO",
        "broader_boundaries_preserved": "PASS",
    }
    if (
        review.get("schema_version")
        != (
            "program-007-corporate-action-metadata-qualification-authority-proposal-"
            "independent-review-v1"
        )
        or review.get("program_id") != PROGRAM_ID
        or review.get("status") != "PASS-BLOCKED-CREDENTIALS-NOT-VISIBLE-TO-RUNTIME"
        or review.get("verdict") != "PASS"
        or review.get("findings") != []
        or reviewed
        != {
            **proposal_binding,
            "proposal_id": proposal.get("proposal_id"),
            "proposal_artifact_commit": reviewed.get("proposal_artifact_commit"),
        }
        or not frozen._is_lower_hex(reviewed.get("proposal_artifact_commit"), 40)
        or challenges != expected_challenges
        or review.get("authority") != _authority_flags(active=False)
        or review.get("external_authorization_root_generated") is not False
    ):
        raise Program007AuthorityError("Program 007 authority proposal review differs")


def _expected_qualification() -> Mapping[str, Any]:
    return {
        "request_plan_path": REQUEST_PLAN_PATH.as_posix(),
        "endpoint_allowlist": [metadata.ENDPOINT],
        "provider_role": "CORROBORATION + DISCREPANCY DETECTION",
        "negative_event_completeness_proved": False,
        "positive_controls": sorted(metadata.POSITIVE_CONTROLS),
        "positive_control_rule": "exactly one 2-for-1 forward_split on 2025-12-05 each",
        "unexpected_relevant_action": "FAIL-PENDING-PUBLIC-LEDGER-RECONCILIATION",
        "symbol_cusip_disagreement": "FAIL",
        "recognized_event_types": list(metadata.EVENT_TYPES),
        "types_parameter": "OMITTED",
        "process_date": "retrieval/provider provenance only; returned value inside interval",
        "creation_lag": "UNBOUNDED-NO-PROVIDER-GUARANTEE",
        "raw_first_private_root": metadata.PRIVATE_ROOT.as_posix(),
        "transport_budget": expected_request_plan()["transport_budget"],
        "strategy_calculations": 0,
        "ohlcv_authority": False,
    }


def _expected_activation_contract() -> Mapping[str, Any]:
    return {
        "future_authority_id": FUTURE_AUTHORITY_ID,
        "external_authorization_root_required": True,
        "external_authorization_root_generated": False,
        "caller_supplied_root_required": True,
        "recomputed_alternate_root_self_authorizes": False,
        "under_lock_full_revalidation": True,
        "consumption_boundary": CONSUMPTION_BOUNDARY,
        "sent_or_ambiguous_transport_consumes_use": True,
        "automatic_retries": 0,
        "second_execution_allowed": False,
    }


def _repository_preflight(
    repository: Path,
    proposal: Mapping[str, Any],
    controls: Mapping[str, Any],
) -> Mapping[str, str]:
    source = _mapping(
        proposal.get("authority_implementation_binding"), "authority implementation binding"
    )
    source_commit = str(source.get("source_commit"))
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
                raise Program007AuthorityError("Program 007 control artifact history differs")
            return commits[0]

        request_plan_added = added(REQUEST_PLAN_PATH)
        proposal_added = added(PROPOSAL_PATH)
        review_added = added(REVIEW_PATH)
        lineage = (
            (source_commit, proposal_added),
            (proposal_added, review_added),
            (review_added, head),
        )
        changed = git(
            "diff",
            "--name-only",
            source_commit,
            head,
            "--",
            *(path.as_posix() for path in _AUTHORITY_SOURCE_PATHS),
        ).stdout
        proposal_bytes = git("show", f"{proposal_added}:{PROPOSAL_PATH.as_posix()}").stdout.encode()
        review_bytes = git("show", f"{review_added}:{REVIEW_PATH.as_posix()}").stdout.encode()
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        raise Program007AuthorityError("Program 007 repository identity is unavailable") from error
    reviewed = _mapping(
        _mapping(controls["review"], "authority proposal review").get("reviewed_proposal"),
        "reviewed proposal",
    )
    if (
        dirty
        or head != main
        or head != origin_main
        or request_plan_added != source_commit
        or len({source_commit, proposal_added, review_added}) != 3
        or any(
            git("merge-base", "--is-ancestor", earlier, later, check=False).returncode
            for earlier, later in lineage
        )
        or changed
        or reviewed.get("proposal_artifact_commit") != proposal_added
        or proposal_bytes != (repository / PROPOSAL_PATH).read_bytes()
        or review_bytes != (repository / REVIEW_PATH).read_bytes()
    ):
        raise Program007AuthorityError("Program 007 reviewed control lineage differs")
    source_files = _sequence(source.get("source_files"), "authority source files")
    for item, path in zip(source_files, _AUTHORITY_SOURCE_PATHS, strict=True):
        binding = _mapping(item, "authority source file")
        expected_sha = str(binding.get("sha256"))
        if (
            frozen._file_sha256(repository / path) != expected_sha
            or frozen._git_file_sha256(repository, source_commit, path) != expected_sha
        ):
            raise Program007AuthorityError("Program 007 reviewed implementation bytes differ")
    return {
        "authority_implementation_commit": source_commit,
        "request_plan_artifact_commit": request_plan_added,
        "proposal_artifact_commit": proposal_added,
        "proposal_review_artifact_commit": review_added,
        "synchronized_main_commit": head,
    }


def _reject_existing_state(root_descriptor: int, *, allow_active: bool = True) -> None:
    allowed = {"run.lock"}
    if allow_active:
        allowed.add("active-authority.json")
    if set(os.listdir(root_descriptor)) - allowed:
        raise Program007AuthorityError("Program 007 one-use authority state already exists")
    if not allow_active and "active-authority.json" in os.listdir(root_descriptor):
        raise Program007AuthorityError("Program 007 one-use authority state already exists")


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Program007AuthorityError(f"Program 007 {label} is invalid JSON") from error
    if type(value) is not dict:
        raise Program007AuthorityError(f"Program 007 {label} is not an object")
    return value


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Program007AuthorityError(f"Program 007 {label} is invalid")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise Program007AuthorityError(f"Program 007 {label} is invalid")
    return value


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
