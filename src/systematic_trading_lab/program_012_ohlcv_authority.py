"""Reviewed restart-safe runtime for Program 012 raw Alpaca SIP acquisition."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from http.client import HTTPException
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from . import program_005_alpaca as transport_support
from . import program_006_alpaca as credential_contract
from . import program_007_alpaca as raw_contract
from . import program_011_ohlcv as program_011
from . import program_011_ohlcv_authority as predecessor
from . import program_012_ohlcv as program_012
from .config import non_broker_subprocess_environment
from .fingerprints import canonical_json, fingerprint
from .standing_research_authority import derive_child_identity

PROGRAM_ID = program_012.PROGRAM_ID
PROGRAM_ORDINAL = program_012.PROGRAM_ORDINAL
CHILD_AUTHORITY_ID = (
    "program-012-exposed-prefix-raw-alpaca-sip-acquisition-and-"
    "structural-admission-child-2026-08-31-v1"
)
CONSUMPTION_BOUNDARY = "immediately before first provider transport invocation"
PRIVATE_ROOT = Path(".trading-lab/program-012-exposed-prefix-raw-alpaca-sip-v1")
PUBLIC_TERMINAL_PATH = Path(
    "config/research/program-012-exposed-prefix-raw-alpaca-sip-acquisition-and-"
    "structural-admission-terminal-result-v1.json"
)
CREDENTIAL_NAMES = credential_contract._CREDENTIAL_NAMES
CHILD_AUTHORITY_PATH = Path(
    "config/research/program-012-exposed-prefix-raw-alpaca-sip-acquisition-and-"
    "structural-admission-child-authority-v1.json"
)
CHILD_REVIEW_PATH = Path(
    "config/research/program-012-exposed-prefix-raw-alpaca-sip-acquisition-and-"
    "structural-admission-child-authority-independent-review-v1.json"
)
OPERATION_MANIFEST = {
    "path": (
        "config/research/program-012-exposed-prefix-raw-alpaca-sip-acquisition-and-"
        "structural-admission-proposal-v3.json"
    ),
    "sha256": "337a5b14ff15f9d40d0f88ed05822cf9e55293fe6c5219f56d63f1d65a67c19a",
    "fingerprint": "7f5817707001b03765ee5563fcb07f728ac066cc7352137b732f87312743c80b",
}
PROPOSAL_REVIEW = {
    "path": (
        "config/research/program-012-exposed-prefix-raw-alpaca-sip-acquisition-and-"
        "structural-admission-independent-review-v1.json"
    ),
    "sha256": "3a61db10f5cd074ea3d3d1b446eaa4acd6b8bbdebe8b4c2dc13328ed58cf30e7",
    "fingerprint": "98736a47227b309447c34a8731edb2b7bff8c5e64a9392329145eb444cd5eb4d",
}
_ACTION_LEDGER_MANIFEST = {
    "path": "config/research/program-007-unit-changing-action-ledger-v3.json",
    "sha256": "e405529489921a0ec8883aa64e855e6600a99105387cbc9ed2766c82bc0826b1",
    "fingerprint": "37467ced2666cdb716706aa4310e48aa5b0938f168cafadf00f6dec72e336f4f",
}
_ENABLED_AUTHORITY = {
    "provider_contact",
    "credential_access",
    "source_requests",
    "market_data_acquisition",
    "real_dataset_admission",
}
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_EVIDENCE_KEY = re.compile(r"[a-z0-9][a-z0-9.-]*")
_HEX_40 = re.compile(r"[0-9a-f]{40}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_PAGE_KEY = re.compile(
    r"session-(?P<session>[0-9]{4}-[0-9]{2}-[0-9]{2})-"
    r"(?P<page>[0-9]{2})\.(?P<kind>intent\.json|body|receipt\.json)"
)
_CREDENTIAL_KEY = re.compile(
    r"credential-load-(?P<sequence>[0-9]{6})\.(?P<kind>attempt|receipt)\.json"
)
_TERMINAL_KEYS = {"acquisition-receipt.json", "terminal-failure.json"}
_DERIVED_KEYS = {
    "canonical-raw.jsonl",
    "dataset-manifest.json",
    "missing-coordinates.json",
    "response-manifest.json",
    "structural-admission.json",
}
_PROCESS_CREDENTIAL_LOCK = threading.Lock()
_PROCESS_CREDENTIAL_PID: int | None = None
_FIXED_QUARANTINE_FAILURES = {
    f"fixed-quarantine:{name}"
    for name in (
        "membership",
        "block-counts",
        "block-retention",
        "block-balance",
        "protected-boundaries",
        "nonadjacency",
        "calendar",
        "clock",
    )
}
_ADMISSION_FAILURES = {
    *_FIXED_QUARANTINE_FAILURES,
    "quarantine-unexpected-coordinate",
    "global-count",
    "unexpected-count",
    "quarantine-block",
    "adjacent",
    "rolling-63",
    "quarantine-rolling-63",
    "same-symbol-rolling-252",
    "initial-context",
    "morning-population",
    "morning-diagnostic-unavailable",
    "unsupported-exclusion-count",
    "early-close",
    *{f"calendar-year:{year}" for year in range(2020, 2026)},
    *{
        f"fixed-block:{block}"
        for block in (
            "discovery-01",
            "discovery-02",
            "discovery-03",
            "wf-01",
            "wf-02",
            "wf-03",
            "wf-04",
            "wf-05",
            "wf-06",
            "wf-07",
            "wf-08",
        )
    },
    *{
        f"morning-bias:{symbol}:{metric}:{tail}"
        for symbol in ("SPY", "MDY")
        for metric, tail in (
            ("absolute-return", "high"),
            ("range", "high"),
            ("volume", "low"),
        )
    },
}
_ACQUISITION_RECEIPT_KEYS = {
    "schema_version",
    "program_id",
    "authority_id",
    "authority_fingerprint",
    "source_commit",
    "public_terminal_path",
    "status",
    "admission_passed",
    "session_count",
    "request_count",
    "response_count",
    "response_bytes",
    "raw_row_count",
    "expected_canonical_coordinate_count",
    "missing_coordinate_count",
    "excluded_full_session_count",
    "credential_loads",
    "aggregate_gate_results",
    "response_manifest_sha256",
    "canonical_raw_sha256",
    "private_missingness_sha256",
    "structural_admission_sha256",
    "private_dataset_manifest_sha256",
    "public_dataset_manifest",
    "dataset_identity",
    "private_dataset_identity",
    "automatic_retries",
    "credentials_stored",
    "exact_missing_coordinates_private",
    "exact_unexpected_exclusion_dates_private",
    "program_002_admission",
    "strategy_calculations",
    "strategy_returns",
    "observed_at",
    "terminal_fingerprint",
}
_TERMINAL_FAILURE_KEYS = {
    "schema_version",
    "program_id",
    "authority_id",
    "authority_fingerprint",
    "source_commit",
    "public_terminal_path",
    "status",
    "admission_passed",
    "failure_class",
    "failure_classification",
    "provider_transport_attempted",
    "scientific_use_consumed",
    "session_count",
    "request_count",
    "response_count",
    "response_bytes",
    "sessions_with_completed_responses",
    "raw_row_count",
    "expected_canonical_coordinate_count",
    "missing_coordinate_count",
    "excluded_full_session_count",
    "credential_loads",
    "aggregate_gate_results",
    "response_manifest_sha256",
    "canonical_raw_sha256",
    "private_missingness_sha256",
    "structural_admission_sha256",
    "private_dataset_manifest_sha256",
    "public_dataset_manifest",
    "dataset_identity",
    "unpaired_credential_attempts_count_as_load",
    "automatic_retries",
    "dataset_admitted",
    "strategy_calculations",
    "strategy_returns",
    "credentials_stored",
    "exact_missing_coordinates_private",
    "exact_unexpected_exclusion_dates_private",
    "program_002_admission",
    "observed_at",
    "terminal_fingerprint",
}
_ACQUISITION_GATE_KEYS = {
    "structural_admission_passed",
    "failure_count",
    "failure_classes",
}
_RUNTIME_FAILURE_GATE_KEYS = {
    "structural_admission_passed",
    "structural_admission_evaluated",
    "failure_count",
    "failure_classes",
}
_PUBLIC_DATASET_KEYS = {
    "schema_version",
    "program_id",
    "authority_id",
    "authority_fingerprint",
    "source_commit",
    "status",
    "dataset_identity",
    "canonical_raw_sha256",
    "raw_row_count",
    "expected_coordinate_count",
    "missing_coordinate_count",
    "excluded_full_session_count",
    "admitted_full_session_count",
    "exact_missingness_private",
    "exact_excluded_sessions_private",
    "program_002_admission",
    "strategy_metrics_present",
}
_PRIVATE_DATASET_KEYS = {
    "schema_version",
    "program_id",
    "authority_id",
    "authority_fingerprint",
    "source_commit",
    "status",
    "dataset_identity",
    "response_manifest_sha256",
    "canonical_raw_sha256",
    "private_missingness_sha256",
    "structural_admission_sha256",
    "raw_row_count",
    "expected_coordinate_count",
    "missing_coordinate_count",
    "excluded_full_session_count",
    "admitted_full_session_count",
    "admitted_session_index_fingerprint",
    "exact_missingness_private",
    "program_002_admission",
    "strategy_metrics_present",
}


class Program012AuthorityError(ValueError):
    """Fail-closed Program 012 runtime or authority error."""


class Program012PostClaimPersistenceError(Program012AuthorityError):
    """Terminal evidence could not be persisted after possible transport."""


class ChainIncompleteError(Program012AuthorityError):
    """A session retained a continuation token at the sixteen-page cap."""

    classification = "CHAIN-INCOMPLETE-RESOURCE-CAP"


class _TransportRequired(Exception):
    pass


@dataclass(frozen=True)
class AcquisitionExecution:
    status: str
    admission_passed: bool
    request_count: int
    response_count: int
    response_bytes: int
    raw_row_count: int
    expected_coordinate_count: int
    missing_coordinate_count: int
    excluded_full_session_count: int
    credential_loads: int
    response_manifest_sha256: str
    canonical_raw_sha256: str
    dataset_identity: str | None

    def public_summary(self) -> dict[str, object]:
        return {
            "program_id": PROGRAM_ID,
            "status": self.status,
            "admission_passed": self.admission_passed,
            "session_count": program_012.EXPECTED_SESSION_COUNT,
            "request_count": self.request_count,
            "response_count": self.response_count,
            "response_bytes": self.response_bytes,
            "raw_row_count": self.raw_row_count,
            "expected_canonical_coordinate_count": self.expected_coordinate_count,
            "missing_coordinate_count": self.missing_coordinate_count,
            "excluded_full_session_count": self.excluded_full_session_count,
            "credential_loads": self.credential_loads,
            "credentials_stored": False,
            "exact_missing_coordinates_private": True,
            "exact_unexpected_exclusion_dates_private": True,
            "response_manifest_sha256": self.response_manifest_sha256,
            "canonical_raw_sha256": self.canonical_raw_sha256,
            "dataset_identity": self.dataset_identity,
            "automatic_retries": 0,
            "program_002_admission": False,
            "strategy_calculations": 0,
            "strategy_returns": 0,
        }


def credential_presence_preflight(
    repository: Path, environ: Mapping[str, str] | None = None
) -> tuple[str, ...]:
    """Validate public controls before checking credential names."""
    _derive_control_validated_authority(repository)
    return credential_contract.credential_presence_preflight(environ)


def read_credentials(environ: Mapping[str, str] | None = None) -> tuple[str, str]:
    values = os.environ if environ is None else environ
    credentials = tuple(values.get(name, "").strip() for name in CREDENTIAL_NAMES)
    if any(not value or "\r" in value or "\n" in value for value in credentials):
        raise Program012AuthorityError("Program 012 OHLCV credentials are required")
    return credentials[0], credentials[1]


def validate_operation_contract(
    repository: Path, *, commit: str | None = None
) -> Mapping[str, Any]:
    """Revalidate the frozen source, chronology, budgets, and admission policy."""
    repository = _repository(repository)
    proposal = _load_bound(repository, OPERATION_MANIFEST, "proposal_fingerprint", commit=commit)
    review = _load_bound(repository, PROPOSAL_REVIEW, "review_fingerprint", commit=commit)
    bindings = _mapping(proposal.get("bindings"), "operation bindings")
    program_011_success = _load_bound(
        repository,
        _mapping(bindings.get("program_011_terminal_success"), "Program 011 success binding"),
        "success_fingerprint",
        commit=commit,
    )
    program_011_review = _load_bound(
        repository,
        _mapping(bindings.get("program_011_terminal_review"), "Program 011 review binding"),
        "review_fingerprint",
        commit=commit,
    )
    ledger = _load_bound(
        repository,
        _mapping(
            bindings.get("program_007_public_unit_changing_action_ledger"),
            "action ledger binding",
        ),
        "ledger_fingerprint",
        commit=commit,
    )
    program_005_plan = _load_bound(
        repository,
        _mapping(bindings.get("program_005_policy_precedent"), "Program 005 binding"),
        "plan_fingerprint",
        commit=commit,
    )
    incident = _load_bound(
        repository,
        _mapping(bindings.get("program_002_fixed_quarantine_incident"), "incident binding"),
        "incident_fingerprint",
        commit=commit,
    )
    incident_review = _load_bound(
        repository,
        _mapping(bindings.get("program_002_fixed_quarantine_review"), "incident review binding"),
        "review_fingerprint",
        commit=commit,
    )
    _load_bound(
        repository,
        _mapping(bindings.get("protected_chronology"), "protected chronology binding"),
        "inventory_fingerprint",
        commit=commit,
    )
    _load_bound(
        repository,
        _mapping(
            bindings.get("protected_chronology_registration"),
            "protected registration binding",
        ),
        "registration_fingerprint",
        commit=commit,
    )
    try:
        raw_contract.require_action_ledger_admission(ledger)
        predecessor._validate_split_controls(ledger)
        predecessor._validate_protected_registration_set(
            repository, commit or _git(repository, "rev-parse", "HEAD")
        )
        protected_ranges = predecessor._current_protected_ranges(repository, commit=commit)
    except (raw_contract.Program007Error, predecessor.Program011AuthorityError) as error:
        raise Program012AuthorityError(
            str(error).replace("Program 007", "Program 012").replace("Program 011", "Program 012")
        ) from None

    source = _mapping(proposal.get("source_contract"), "source contract")
    pagination = _mapping(proposal.get("pagination_contract"), "pagination contract")
    budgets = _mapping(proposal.get("transport_budgets"), "transport budgets")
    restart = _mapping(proposal.get("restart_contract"), "restart contract")
    chronology = _mapping(proposal.get("chronology"), "chronology")
    request_range = _mapping(chronology.get("request_range"), "request range")
    protected_overlap = _mapping(chronology.get("protected_overlap"), "protected overlap")
    admission = _mapping(proposal.get("structural_admission_contract"), "admission contract")
    authority = _mapping(proposal.get("authority"), "proposal authority")
    firewall = _mapping(proposal.get("protected_firewall"), "protected firewall")
    success_authorization = _mapping(
        program_011_success.get("authorization"), "Program 011 authorization"
    )
    success_disposition = _mapping(
        program_011_success.get("disposition"), "Program 011 disposition"
    )
    success_final = _mapping(
        program_011_success.get("effective_final_authority"), "Program 011 final authority"
    )
    review_final = _mapping(
        program_011_review.get("effective_final_authority"), "Program 011 review authority"
    )
    requests = program_012.acquisition_requests()
    inventory = program_012.derive_incident_inventory(incident, program_005_plan)
    if (
        proposal.get("program_ordinal") != PROGRAM_ORDINAL
        or proposal.get("program_id") != PROGRAM_ID
        or proposal.get("status") != program_012.STATUS
        or proposal.get("proposal_fingerprint") != OPERATION_MANIFEST["fingerprint"]
        or review.get("status")
        != "PASS-FINDING-FREE-PROSPECTIVE-DESIGN-AND-CREDENTIAL-BOUNDARY-REVIEW"
        or review.get("verdict") != "PASS"
        or review.get("findings") != []
        or bindings.get("program_007_public_unit_changing_action_ledger") != _ACTION_LEDGER_MANIFEST
        or source.get("method") != "GET"
        or source.get("endpoint") != program_011.ENDPOINT
        or source.get("feed") != "sip"
        or source.get("timeframe") != "5Min"
        or source.get("adjustment") != "raw"
        or source.get("sort") != "asc"
        or source.get("limit") != program_011.PAGE_ROW_LIMIT
        or source.get("asof") != "2026-07-31"
        or source.get("symbols") != list(program_012.SYMBOLS)
        or source.get("automatic_retries") != 0
        or pagination.get("terminal_condition") != "next_page_token is null"
        or pagination.get("maximum_pages_per_session") != program_012.MAXIMUM_PAGES_PER_SESSION
        or pagination.get("raw_body_fsynced_before_parse_or_continuation") is not True
        or budgets.get("session_chains") != program_012.EXPECTED_SESSION_COUNT
        or budgets.get("maximum_requests_and_responses")
        != program_012.MAXIMUM_REQUESTS_AND_RESPONSES
        or budgets.get("maximum_response_page_bytes") != program_012.MAXIMUM_RESPONSE_PAGE_BYTES
        or budgets.get("maximum_session_response_bytes")
        != program_012.MAXIMUM_SESSION_RESPONSE_BYTES
        or budgets.get("maximum_total_response_bytes") != program_012.MAXIMUM_TOTAL_RESPONSE_BYTES
        or budgets.get("working_disk_reservation_bytes")
        != program_012.WORKING_DISK_RESERVATION_BYTES
        or budgets.get("maximum_requests_per_minute") != program_012.MAXIMUM_REQUESTS_PER_MINUTE
        or budgets.get("request_timeout_seconds") != program_012.REQUEST_TIMEOUT_SECONDS
        or budgets.get("credential_loads_per_process_max") != 1
        or budgets.get("automatic_retries") != 0
        or budgets.get("parallel_session_chains") != 1
        or restart.get("exclusive_private_root_lock_required") is not True
        or restart.get("request_intent_create_only_and_atomic") is not True
        or restart.get("request_intent_fsynced_before_transport") is not True
        or restart.get("request_reissue_allowed") is not False
        or restart.get("credential_load_attempt_fsynced_before_access") is not True
        or restart.get("unpaired_credential_load_attempt_action")
        != "COUNT-AS-ONE-LOAD-CONSERVATIVELY"
        or request_range.get("start") != program_012.CONTEXT_START.isoformat()
        or request_range.get("end") != program_012.EXPOSED_END.isoformat()
        or request_range.get("session_count") != len(requests)
        or request_range.get("expected_coordinates")
        != sum(len(request.expected_coordinates) for request in requests)
        or protected_overlap.get("request_session_count") != 0
        or protected_overlap.get("request_coordinate_count") != 0
        or admission.get("complete_chain_required_for_every_session") is not True
        or admission.get("strategy_metrics_allowed", False) is True
        or len(inventory) != 9
        or any(authority.values())
        or firewall.get(
            "rederive_registered_ranges_from_synchronized_main_before_credential_presence"
        )
        is not True
        or firewall.get("revalidate_zero_request_overlap_before_private_state") is not True
        or firewall.get("revalidate_zero_request_overlap_before_every_transport") is not True
        or any(
            firewall.get(key) is not False
            for key in ("controlled_evaluation", "protected_holdout", "paper", "broker", "live")
        )
        or program_011_success.get("status") != "TERMINAL-PASS-CONSUMED-NO-REPLAY"
        or success_authorization.get("one_use_consumed") is not True
        or success_disposition.get("qualification_replay_allowed") is not False
        or any(success_final.values())
        or program_011_review.get("verdict") != "PASS"
        or program_011_review.get("findings") != []
        or any(review_final.values())
        or incident_review.get("verdict") != "pass"
        or incident_review.get("findings") != []
        or any(
            start <= request.session <= end
            for request in requests
            for start, end in protected_ranges
        )
    ):
        raise Program012AuthorityError("Program 012 operation contract differs")
    return proposal


def derive_active_authority(repository: Path) -> Mapping[str, Any]:
    """Derive the exact active record without reading credential state."""
    return _derive_control_validated_authority(repository)


def _derive_control_validated_authority(repository: Path) -> Mapping[str, Any]:
    repository = _repository(repository)
    identity = derive_child_identity(repository, CHILD_AUTHORITY_PATH, CHILD_REVIEW_PATH)
    authority = _mapping(identity.get("authority"), "child authority")
    runtime = _mapping(identity.get("runtime_binding"), "child runtime binding")
    source_paths = {
        str(_mapping(item, "child runtime source file").get("path"))
        for item in _sequence(runtime.get("source_files"), "child runtime source files")
    }
    required_paths = {
        predecessor.PROTECTED_CHRONOLOGY_PATH.as_posix(),
        *(path.as_posix() for path in predecessor.PROTECTED_CHRONOLOGY_SOURCE_PATHS),
        *(path.as_posix() for path in predecessor.PROTECTED_CHRONOLOGY_REGISTRATION_PATHS),
        str(OPERATION_MANIFEST["path"]),
    }
    if (
        identity.get("child_authority_id") != CHILD_AUTHORITY_ID
        or identity.get("program_ordinal") != PROGRAM_ORDINAL
        or identity.get("program_id") != PROGRAM_ID
        or identity.get("operation_manifest") != OPERATION_MANIFEST
        or identity.get("runtime_entrypoint")
        != "src/systematic_trading_lab/program_012_ohlcv_authority.py"
        or not required_paths <= source_paths
        or {key for key, value in authority.items() if value} != _ENABLED_AUTHORITY
    ):
        raise Program012AuthorityError("Program 012 reviewed child identity differs")
    lineage = _repository_preflight(repository, identity)
    commit = lineage["synchronized_main_commit"]
    try:
        predecessor._validate_protected_registration_set(repository, commit)
    except predecessor.Program011AuthorityError as error:
        raise Program012AuthorityError(str(error).replace("Program 011", "Program 012")) from None
    validate_operation_contract(repository, commit=commit)
    if _repository_preflight(repository, identity) != lineage:
        raise Program012AuthorityError("Program 012 repository changed during validation")
    unsigned: dict[str, Any] = {
        "schema_version": "program-012-raw-sip-acquisition-active-authority-v1",
        "status": "ACTIVE-ONE-USE-RECOVERABLE",
        "authority_id": CHILD_AUTHORITY_ID,
        "program_id": PROGRAM_ID,
        "activation_mode": "INTERNAL-STANDING-MANDATE-DERIVATION",
        "external_authorization_root_required": False,
        "child_identity_fingerprint": identity["child_identity_fingerprint"],
        "operation_manifest": OPERATION_MANIFEST,
        "consumption_boundary": CONSUMPTION_BOUNDARY,
        "authority": authority,
        "control_lineage": lineage,
    }
    active = {**unsigned, "authority_fingerprint": fingerprint(unsigned)}
    _validate_existing_public_terminal(repository, active, lineage["runtime_source_commit"])
    return active


def activate_authority(
    repository: Path, *, environ: Mapping[str, str] | None = None
) -> Mapping[str, Any]:
    repository = _repository(repository)
    authority = _derive_control_validated_authority(repository)
    _require_credentials_present(environ)
    commit = _authority_commit(authority)
    root_descriptor = _open_private_root(repository, create=True)
    try:
        with (
            predecessor._LockedRoot(root_descriptor),
            predecessor._GitPolicySnapshot(repository, commit),
        ):
            if set(os.listdir(root_descriptor)) != {"run.lock"}:
                raise Program012AuthorityError("Program 012 one-use authority state already exists")
            locked = _derive_control_validated_authority(repository)
            _require_credentials_present(environ)
            if locked != authority:
                raise Program012AuthorityError("Program 012 authority changed under policy lock")
            _append(
                root_descriptor,
                "active-authority.json",
                (canonical_json(locked) + "\n").encode(),
            )
    finally:
        os.close(root_descriptor)
    return authority


def load_active_authority(repository: Path) -> Mapping[str, Any]:
    repository = _repository(repository)
    expected = _derive_control_validated_authority(repository)
    root_descriptor = _open_private_root(repository, create=False)
    try:
        return _load_active(root_descriptor, expected)
    finally:
        os.close(root_descriptor)


def execute_acquisition(
    repository: Path, *, environ: Mapping[str, str] | None = None
) -> AcquisitionExecution:
    """Resume or consume the reviewed child and structurally admit the raw prefix."""
    return _execute_acquisition(
        repository,
        environ=environ,
        mock_transport=None,
        after_intent=None,
        after_credential_access=None,
        after_page=None,
    )


def _execute_mock_acquisition(
    repository: Path,
    *,
    environ: Mapping[str, str],
    transport: MockBarsTransport,
    after_intent: Callable[[], None] | None = None,
    after_credential_access: Callable[[], None] | None = None,
    after_page: Callable[[], None] | None = None,
) -> AcquisitionExecution:
    if type(transport) is not MockBarsTransport or environ is os.environ:
        raise Program012AuthorityError("Program 012 test execution requires finite inputs")
    return _execute_acquisition(
        repository,
        environ=environ,
        mock_transport=transport,
        after_intent=after_intent,
        after_credential_access=after_credential_access,
        after_page=after_page,
    )


def _execute_acquisition(
    repository: Path,
    *,
    environ: Mapping[str, str] | None,
    mock_transport: MockBarsTransport | None,
    after_intent: Callable[[], None] | None,
    after_credential_access: Callable[[], None] | None,
    after_page: Callable[[], None] | None,
) -> AcquisitionExecution:
    repository = _repository(repository)
    expected_authority = _derive_control_validated_authority(repository)
    commit = _authority_commit(expected_authority)
    source_commit = _source_commit(expected_authority)
    root_descriptor = _open_private_root(repository, create=False)
    budget: _Budget | None = None
    try:
        with (
            predecessor._LockedRoot(root_descriptor),
            predecessor._GitPolicySnapshot(repository, commit),
        ):
            try:
                if any(_exists(root_descriptor, key) for key in _TERMINAL_KEYS):
                    terminal_key, terminal = _load_terminal_record(
                        root_descriptor, expected_authority, source_commit
                    )
                    _publish_public_terminal(repository, root_descriptor, terminal_key, terminal)
                    raise Program012AuthorityError("Program 012 acquisition is terminally sealed")
                authority = _derive_control_validated_authority(repository)
                if authority != expected_authority:
                    raise Program012AuthorityError("Program 012 authority changed under lock")
                _load_active(root_descriptor, authority)
                proposal = validate_operation_contract(repository, commit=commit)
                budget = _Budget()
                _reconstruct_state(
                    root_descriptor,
                    authority=authority,
                    source_commit=source_commit,
                    budget=budget,
                )
                _require_working_disk_capacity(root_descriptor)
                loader = _CredentialLoader(
                    root_descriptor,
                    authority,
                    source_commit,
                    environ,
                    mock_transport,
                    after_credential_access,
                    budget.latest_response_at,
                )

                def consume() -> None:
                    if _derive_control_validated_authority(repository) != authority:
                        raise Program012AuthorityError(
                            "Program 012 authority changed at transport boundary"
                        )
                    try:
                        protected_ranges = predecessor._current_protected_ranges(
                            repository, commit=commit
                        )
                    except predecessor.Program011AuthorityError as error:
                        raise Program012AuthorityError(
                            str(error).replace("Program 011", "Program 012")
                        ) from None
                    if any(
                        start <= request.session <= end
                        for request in program_012.acquisition_requests()
                        for start, end in protected_ranges
                    ):
                        raise Program012AuthorityError(
                            "Program 012 request chronology overlaps protected data"
                        )
                    if _exists(root_descriptor, "claim.json"):
                        _validate_claim(root_descriptor, authority, source_commit)
                        return
                    _append_atomic(
                        root_descriptor,
                        "claim.json",
                        _claim_payload(authority, source_commit),
                    )

                temp_key, temp_descriptor = _new_temp(root_descriptor, "canonical-raw")
                missing: dict[date, set[str]] = {}
                morning: dict[date, dict[str, tuple[Any, Any, Any]]] = {}
                canonical_hash = hashlib.sha256()
                raw_row_count = 0
                completed = False
                try:
                    with os.fdopen(temp_descriptor, "wb") as canonical_file:
                        for request in program_012.acquisition_requests():
                            source = _PersistentSessionSource(
                                root_descriptor,
                                request,
                                authority,
                                source_commit,
                                budget,
                                loader,
                                consume,
                                after_intent,
                                after_page,
                            )
                            result = _execute_session(request, source)
                            coordinates = {
                                f"{symbol}@{_iso_utc(timestamp)}"
                                for symbol, timestamp in result.missingness.source_missing
                            }
                            if coordinates:
                                missing[request.session] = coordinates
                            program_012.collect_morning_metrics(result.rows, morning)
                            for row in result.rows:
                                line = (
                                    canonical_json(program_012.canonical_bar_record(row)) + "\n"
                                ).encode()
                                if canonical_file.write(line) != len(line):
                                    raise Program012AuthorityError(
                                        "Program 012 canonical raw write was incomplete"
                                    )
                                canonical_hash.update(line)
                                raw_row_count += 1
                        canonical_file.flush()
                        os.fsync(canonical_file.fileno())
                    completed = True
                finally:
                    if not completed:
                        with suppress(FileNotFoundError):
                            os.unlink(temp_key, dir_fd=root_descriptor)
                            os.fsync(root_descriptor)
                canonical_sha = canonical_hash.hexdigest()
                _publish_temp_or_validate(
                    root_descriptor,
                    temp_key,
                    "canonical-raw.jsonl",
                    canonical_sha,
                )
                if budget.requests != budget.responses:
                    raise Program012AuthorityError("Program 012 request and response counts differ")

                bindings = _mapping(proposal.get("bindings"), "operation bindings")
                program_005_plan = _load_bound(
                    repository,
                    _mapping(bindings.get("program_005_policy_precedent"), "Program 005 binding"),
                    "plan_fingerprint",
                    commit=commit,
                )
                incident = _load_bound(
                    repository,
                    _mapping(
                        bindings.get("program_002_fixed_quarantine_incident"),
                        "incident binding",
                    ),
                    "incident_fingerprint",
                    commit=commit,
                )
                admission = program_012.assess_structural_admission(
                    proposal, program_005_plan, incident, missing, morning
                )
                missing_payload = (
                    canonical_json(
                        {
                            "schema_version": "program-012-private-missing-coordinates-v1",
                            "program_id": PROGRAM_ID,
                            "sessions": {
                                session.isoformat(): sorted(coordinates)
                                for session, coordinates in sorted(missing.items())
                            },
                        }
                    )
                    + "\n"
                ).encode()
                _append_or_validate(root_descriptor, "missing-coordinates.json", missing_payload)
                admission_payload = (canonical_json(admission) + "\n").encode()
                _append_or_validate(root_descriptor, "structural-admission.json", admission_payload)
                response_manifest = {
                    "schema_version": "program-012-private-response-manifest-v1",
                    "program_id": PROGRAM_ID,
                    "request_count": budget.requests,
                    "response_count": budget.responses,
                    "response_bytes": budget.response_bytes,
                    "pages": budget.pages,
                    "credentials_stored": False,
                }
                response_payload = (canonical_json(response_manifest) + "\n").encode()
                _append_or_validate(root_descriptor, "response-manifest.json", response_payload)
                response_sha = hashlib.sha256(response_payload).hexdigest()
                excluded = {
                    date.fromisoformat(value)
                    for value in cast(Sequence[str], admission["fixed_quarantine_sessions"])
                }
                excluded.update(
                    date.fromisoformat(value)
                    for value in cast(Sequence[str], admission["unexpected_excluded_sessions"])
                )
                admitted_sessions = tuple(
                    request.session.isoformat()
                    for request in program_012.acquisition_requests()
                    if request.session in program_012.full_trade_sessions()
                    and request.session not in excluded
                )
                missingness_sha = hashlib.sha256(missing_payload).hexdigest()
                admission_sha = hashlib.sha256(admission_payload).hexdigest()
                admitted_session_fingerprint = fingerprint(admitted_sessions)
                dataset_identity, private_dataset_identity = _dataset_identities(
                    authority_fingerprint=str(authority["authority_fingerprint"]),
                    source_commit=source_commit,
                    response_manifest_sha256=response_sha,
                    canonical_raw_sha256=canonical_sha,
                    private_missingness_sha256=missingness_sha,
                    admitted_session_index_fingerprint=admitted_session_fingerprint,
                    admission=admission,
                )
                dataset_manifest = {
                    "schema_version": "program-012-raw-structural-prefix-dataset-manifest-v1",
                    "program_id": PROGRAM_ID,
                    "authority_id": authority["authority_id"],
                    "authority_fingerprint": authority["authority_fingerprint"],
                    "source_commit": source_commit,
                    "status": admission["status"],
                    "dataset_identity": private_dataset_identity,
                    "response_manifest_sha256": response_sha,
                    "canonical_raw_sha256": canonical_sha,
                    "private_missingness_sha256": missingness_sha,
                    "structural_admission_sha256": admission_sha,
                    "raw_row_count": raw_row_count,
                    "expected_coordinate_count": program_012.EXPECTED_COORDINATE_COUNT,
                    "missing_coordinate_count": admission["missing_coordinate_count"],
                    "excluded_full_session_count": admission["excluded_full_session_count"],
                    "admitted_full_session_count": len(admitted_sessions),
                    "admitted_session_index_fingerprint": admitted_session_fingerprint,
                    "exact_missingness_private": True,
                    "program_002_admission": False,
                    "strategy_metrics_present": False,
                }
                dataset_payload = (canonical_json(dataset_manifest) + "\n").encode()
                _append_or_validate(root_descriptor, "dataset-manifest.json", dataset_payload)
                public_dataset_manifest = {
                    "schema_version": (
                        "program-012-public-raw-structural-prefix-dataset-manifest-v1"
                    ),
                    "program_id": PROGRAM_ID,
                    "authority_id": authority["authority_id"],
                    "authority_fingerprint": authority["authority_fingerprint"],
                    "source_commit": source_commit,
                    "status": admission["status"],
                    "dataset_identity": dataset_identity,
                    "canonical_raw_sha256": canonical_sha,
                    "raw_row_count": raw_row_count,
                    "expected_coordinate_count": program_012.EXPECTED_COORDINATE_COUNT,
                    "missing_coordinate_count": admission["missing_coordinate_count"],
                    "excluded_full_session_count": admission["excluded_full_session_count"],
                    "admitted_full_session_count": len(admitted_sessions),
                    "exact_missingness_private": True,
                    "exact_excluded_sessions_private": True,
                    "program_002_admission": False,
                    "strategy_metrics_present": False,
                }
                credential_loads = _credential_load_count(root_descriptor)
                execution = AcquisitionExecution(
                    str(admission["status"]),
                    bool(admission["admission_passed"]),
                    budget.requests,
                    budget.responses,
                    budget.response_bytes,
                    raw_row_count,
                    program_012.EXPECTED_COORDINATE_COUNT,
                    int(admission["missing_coordinate_count"]),
                    int(admission["excluded_full_session_count"]),
                    credential_loads,
                    response_sha,
                    canonical_sha,
                    dataset_identity,
                )
                if mock_transport is not None:
                    mock_transport.require_exhausted()
                receipt = {
                    "schema_version": "program-012-private-acquisition-receipt-v2",
                    "authority_id": authority["authority_id"],
                    "authority_fingerprint": authority["authority_fingerprint"],
                    "source_commit": source_commit,
                    "public_terminal_path": PUBLIC_TERMINAL_PATH.as_posix(),
                    **execution.public_summary(),
                    "aggregate_gate_results": {
                        "structural_admission_passed": bool(admission["admission_passed"]),
                        "failure_count": len(cast(Sequence[object], admission["failures"])),
                        "failure_classes": admission["failures"],
                    },
                    "private_missingness_sha256": missingness_sha,
                    "structural_admission_sha256": admission_sha,
                    "private_dataset_manifest_sha256": hashlib.sha256(dataset_payload).hexdigest(),
                    "public_dataset_manifest": (
                        public_dataset_manifest if execution.admission_passed else None
                    ),
                    "private_dataset_identity": private_dataset_identity,
                    "observed_at": _utc_now(),
                }
                receipt["terminal_fingerprint"] = fingerprint(receipt)
                receipt_payload = (canonical_json(receipt) + "\n").encode()
                _append_atomic(root_descriptor, "acquisition-receipt.json", receipt_payload)
                terminal_key, terminal = _load_terminal_record(
                    root_descriptor, authority, source_commit
                )
                try:
                    _publish_public_terminal(repository, root_descriptor, terminal_key, terminal)
                except BaseException as persistence_error:
                    raise Program012PostClaimPersistenceError(
                        "Program 012 public terminal persistence failed after possible transport"
                    ) from persistence_error
                return execution
            except BaseException as error:
                if _has_consumed_state(root_descriptor) and not any(
                    _exists(root_descriptor, key) for key in _TERMINAL_KEYS
                ):
                    try:
                        _append_atomic(
                            root_descriptor,
                            "terminal-failure.json",
                            _failure_payload(
                                root_descriptor,
                                error,
                                budget,
                                expected_authority,
                                source_commit,
                            ),
                        )
                        terminal_key, terminal = _load_terminal_record(
                            root_descriptor, expected_authority, source_commit
                        )
                        _publish_public_terminal(
                            repository, root_descriptor, terminal_key, terminal
                        )
                    except BaseException as persistence_error:
                        raise Program012PostClaimPersistenceError(
                            "Program 012 terminal persistence failed after possible transport"
                        ) from persistence_error
                raise
    finally:
        os.close(root_descriptor)


class MockBarsTransport:
    """Finite canned responses for recovery lifecycle tests."""

    def __init__(self, responses: Sequence[raw_contract.RawResponse]) -> None:
        if type(responses) not in {list, tuple} or any(
            type(response) is not raw_contract.RawResponse for response in responses
        ):
            raise Program012AuthorityError("Program 012 mock responses are invalid")
        self._responses = tuple(responses)
        self._intents: list[program_011.PageIntent] = []

    @property
    def intents(self) -> tuple[program_011.PageIntent, ...]:
        return tuple(self._intents)

    def get(self, intent: program_011.PageIntent) -> raw_contract.RawResponse:
        index = len(self._intents)
        self._intents.append(intent)
        if index >= len(self._responses):
            raise Program012AuthorityError("Program 012 mock response is missing")
        return self._responses[index]

    def require_exhausted(self) -> None:
        if len(self._intents) != len(self._responses):
            raise Program012AuthorityError("Program 012 mock responses remain unused")


class _RecoveryPacer:
    def __init__(
        self,
        latest_response_at: datetime | None,
        *,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
        pace: Callable[[], None] | None = None,
    ) -> None:
        if latest_response_at is not None and (
            latest_response_at.tzinfo is None
            or latest_response_at.utcoffset() != UTC.utcoffset(latest_response_at)
        ):
            raise Program012AuthorityError("Program 012 recovery timestamp must be UTC")
        self._not_before = (
            None
            if latest_response_at is None
            else latest_response_at
            + timedelta(seconds=60 / program_012.MAXIMUM_REQUESTS_PER_MINUTE)
        )
        self._clock = clock
        self._sleep = sleep
        self._pace = (
            transport_support.RequestPacer(
                interval_seconds=60 / program_012.MAXIMUM_REQUESTS_PER_MINUTE
            )
            if pace is None
            else pace
        )

    def __call__(self) -> None:
        if self._not_before is not None:
            while True:
                now = datetime.now(UTC) if self._clock is None else self._clock()
                remaining = (self._not_before - now).total_seconds()
                if remaining <= 0:
                    break
                (time.sleep if self._sleep is None else self._sleep)(remaining)
            self._not_before = None
        self._pace()


class _AlpacaBarsClient:
    def __init__(
        self,
        key_id: str,
        secret_key: str,
        *,
        pace: Callable[[], None] | None = None,
    ) -> None:
        if any(not value or "\r" in value or "\n" in value for value in (key_id, secret_key)):
            raise Program012AuthorityError("Program 012 OHLCV credentials are invalid")
        self._headers = {
            "Accept": "application/json",
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
        }
        self._opener = build_opener(ProxyHandler({}), transport_support._NoRedirect())
        self._pace = transport_support.RequestPacer() if pace is None else pace

    def get(
        self,
        intent: program_011.PageIntent,
        before_transport: Callable[[], None],
    ) -> raw_contract.RawResponse:
        request = Request(intent.url, headers=self._headers, method="GET")
        _validate_http_request(request, intent)
        self._pace()
        before_transport()
        try:
            with self._opener.open(
                request, timeout=program_012.REQUEST_TIMEOUT_SECONDS
            ) as response:
                return raw_contract.RawResponse(
                    int(response.status),
                    response.read(program_012.MAXIMUM_RESPONSE_PAGE_BYTES + 1),
                )
        except HTTPError as error:
            try:
                return raw_contract.RawResponse(
                    error.code,
                    error.read(program_012.MAXIMUM_RESPONSE_PAGE_BYTES + 1),
                )
            finally:
                error.close()
        except (HTTPException, TimeoutError, ConnectionError, URLError, OSError) as error:
            raise Program012AuthorityError(
                "Program 012 OHLCV transport is ambiguous; zero-retry use is consumed"
            ) from error


class _CredentialLoader:
    def __init__(
        self,
        root_descriptor: int,
        authority: Mapping[str, Any],
        source_commit: str,
        environ: Mapping[str, str] | None,
        mock_transport: MockBarsTransport | None,
        after_access: Callable[[], None] | None,
        latest_response_at: datetime | None = None,
    ) -> None:
        self._root_descriptor = root_descriptor
        self._authority = authority
        self._source_commit = source_commit
        self._environ = environ
        self._mock_transport = mock_transport
        self._after_access = after_access
        self._latest_response_at = latest_response_at
        self._loaded = False
        self._client: _AlpacaBarsClient | None = None

    def get(
        self, intent: program_011.PageIntent, before_transport: Callable[[], None]
    ) -> raw_contract.RawResponse:
        if not self._loaded:
            sequence = _next_credential_sequence(self._root_descriptor)
            unsigned = {
                "schema_version": "program-012-private-credential-load-attempt-v1",
                "authority_fingerprint": self._authority["authority_fingerprint"],
                "source_commit": self._source_commit,
                "process_recovery_sequence": sequence,
            }
            attempt = {**unsigned, "attempt_identity": fingerprint(unsigned)}
            prefix = f"credential-load-{sequence:06d}"
            _reserve_process_credential_access(
                lambda: _append_atomic(
                    self._root_descriptor,
                    f"{prefix}.attempt.json",
                    (canonical_json(attempt) + "\n").encode(),
                )
            )
            try:
                key_id, secret_key = read_credentials(self._environ)
            except Exception:
                _append_atomic(
                    self._root_descriptor,
                    f"{prefix}.receipt.json",
                    (
                        canonical_json(
                            {
                                "schema_version": (
                                    "program-012-private-credential-load-receipt-v1"
                                ),
                                "attempt_identity": attempt["attempt_identity"],
                                "status": "FAILURE",
                            }
                        )
                        + "\n"
                    ).encode(),
                )
                raise
            if self._after_access is not None:
                self._after_access()
            _append_atomic(
                self._root_descriptor,
                f"{prefix}.receipt.json",
                (
                    canonical_json(
                        {
                            "schema_version": "program-012-private-credential-load-receipt-v1",
                            "attempt_identity": attempt["attempt_identity"],
                            "status": "SUCCESS",
                        }
                    )
                    + "\n"
                ).encode(),
            )
            if self._mock_transport is None:
                self._client = _AlpacaBarsClient(
                    key_id,
                    secret_key,
                    pace=_RecoveryPacer(self._latest_response_at),
                )
            self._loaded = True
        if self._mock_transport is not None:
            before_transport()
            return self._mock_transport.get(intent)
        assert self._client is not None
        return self._client.get(intent, before_transport)


class _Budget:
    def __init__(self) -> None:
        self.requests = 0
        self.responses = 0
        self.response_bytes = 0
        self.session_bytes: dict[date, int] = {}
        self.pages: list[dict[str, object]] = []
        self.latest_response_at: datetime | None = None

    def reserve_request(self) -> None:
        if self.requests >= program_012.MAXIMUM_REQUESTS_AND_RESPONSES:
            raise Program012AuthorityError("Program 012 request ceiling exceeded")
        self.requests += 1

    def accept_response(
        self,
        request: program_011.SessionRequest,
        intent: program_011.PageIntent,
        status: int,
        body: bytes,
        observed_at: datetime,
    ) -> None:
        if (
            type(observed_at) is not datetime
            or observed_at.tzinfo is None
            or observed_at.utcoffset() != UTC.utcoffset(observed_at)
        ):
            raise Program012AuthorityError("Program 012 response timestamp must be UTC")
        if self.responses >= program_012.MAXIMUM_REQUESTS_AND_RESPONSES:
            raise Program012AuthorityError("Program 012 response ceiling exceeded")
        self.responses += 1
        self.response_bytes += len(body)
        self.session_bytes[request.session] = self.session_bytes.get(request.session, 0) + len(body)
        if self.latest_response_at is None or observed_at > self.latest_response_at:
            self.latest_response_at = observed_at
        self.pages.append(
            {
                "session": request.session.isoformat(),
                "page_index": intent.page_index,
                "status": status,
                "response_bytes": len(body),
                "response_sha256": hashlib.sha256(body).hexdigest(),
                "incoming_page_token_present": intent.incoming_page_token is not None,
            }
        )
        if len(body) > program_012.MAXIMUM_RESPONSE_PAGE_BYTES:
            raise Program012AuthorityError("Program 012 response exceeds the 8 MiB page ceiling")
        if self.session_bytes[request.session] > program_012.MAXIMUM_SESSION_RESPONSE_BYTES:
            raise Program012AuthorityError("Program 012 session exceeds the 8 MiB byte ceiling")
        if self.response_bytes > program_012.MAXIMUM_TOTAL_RESPONSE_BYTES:
            raise Program012AuthorityError("Program 012 total response byte ceiling exceeded")


class _PersistentSessionSource:
    def __init__(
        self,
        root_descriptor: int,
        request: program_011.SessionRequest,
        authority: Mapping[str, Any],
        source_commit: str,
        budget: _Budget,
        loader: _CredentialLoader,
        consume: Callable[[], None],
        after_intent: Callable[[], None] | None,
        after_page: Callable[[], None] | None,
    ) -> None:
        self._root_descriptor = root_descriptor
        self._request = request
        self._authority = authority
        self._source_commit = source_commit
        self._budget = budget
        self._loader = loader
        self._consume = consume
        self._after_intent = after_intent
        self._after_page = after_page
        self._pending: program_011.RetainedPage | None = None

    def response(self, intent: program_011.PageIntent) -> raw_contract.RawResponse:
        if self._pending is not None:
            raise Program012AuthorityError("Program 012 persistent source state differs")
        _validate_page_intent(self._request, intent)
        prefix = _page_prefix(self._request, intent.page_index)
        present = tuple(
            _exists(self._root_descriptor, f"{prefix}.{suffix}")
            for suffix in ("intent.json", "body", "receipt.json")
        )
        if all(present):
            response, _ = _load_completed_page(
                self._root_descriptor,
                self._request,
                intent,
                self._authority,
                self._source_commit,
            )
            self._pending = program_011.RetainedPage(
                intent.page_index,
                len(response.body),
                hashlib.sha256(response.body).hexdigest(),
            )
            return response
        if any(present):
            raise Program012AuthorityError(
                "Program 012 ambiguous page checkpoint forbids request reissue"
            )
        self._budget.reserve_request()
        _append_atomic(
            self._root_descriptor,
            f"{prefix}.intent.json",
            _intent_payload(self._authority, self._source_commit, self._request, intent),
        )
        if self._after_intent is not None:
            self._after_intent()
        response = self._loader.get(intent, self._consume)
        body = response.body[: program_012.MAXIMUM_RESPONSE_PAGE_BYTES + 1]
        _append(self._root_descriptor, f"{prefix}.body", body)
        observed_at = _utc_now()
        receipt = _response_receipt(
            self._authority,
            self._source_commit,
            self._request,
            intent,
            raw_contract.RawResponse(response.status, body),
            observed_at,
        )
        _append(
            self._root_descriptor,
            f"{prefix}.receipt.json",
            (canonical_json(receipt) + "\n").encode(),
        )
        self._budget.accept_response(
            self._request,
            intent,
            response.status,
            body,
            _parse_observed_at(observed_at),
        )
        self._pending = program_011.RetainedPage(
            intent.page_index, len(body), hashlib.sha256(body).hexdigest()
        )
        if self._after_page is not None:
            self._after_page()
        return raw_contract.RawResponse(response.status, body)

    def retain(self, page_index: int, body: bytes) -> program_011.RetainedPage:
        pending = self._pending
        if (
            pending is None
            or pending.page_index != page_index
            or pending.byte_count != len(body)
            or pending.sha256 != hashlib.sha256(body).hexdigest()
        ):
            raise Program012AuthorityError("Program 012 retained response differs")
        self._pending = None
        return pending


class _ReplaySource:
    def __init__(
        self,
        root_descriptor: int,
        request: program_011.SessionRequest,
        authority: Mapping[str, Any],
        source_commit: str,
        budget: _Budget,
    ) -> None:
        self._root_descriptor = root_descriptor
        self._request = request
        self._authority = authority
        self._source_commit = source_commit
        self._budget = budget
        self._pending: program_011.RetainedPage | None = None

    def response(self, intent: program_011.PageIntent) -> raw_contract.RawResponse:
        prefix = _page_prefix(self._request, intent.page_index)
        present = tuple(
            _exists(self._root_descriptor, f"{prefix}.{suffix}")
            for suffix in ("intent.json", "body", "receipt.json")
        )
        if not any(present):
            raise _TransportRequired
        if not all(present):
            raise Program012AuthorityError(
                "Program 012 ambiguous page checkpoint forbids request reissue"
            )
        response, observed_at = _load_completed_page(
            self._root_descriptor,
            self._request,
            intent,
            self._authority,
            self._source_commit,
        )
        self._budget.reserve_request()
        self._budget.accept_response(
            self._request,
            intent,
            response.status,
            response.body,
            observed_at,
        )
        self._pending = program_011.RetainedPage(
            intent.page_index,
            len(response.body),
            hashlib.sha256(response.body).hexdigest(),
        )
        return response

    def retain(self, page_index: int, body: bytes) -> program_011.RetainedPage:
        pending = self._pending
        if pending is None or pending.page_index != page_index:
            raise Program012AuthorityError("Program 012 replayed response differs")
        self._pending = None
        return pending


def _execute_session(
    request: program_011.SessionRequest,
    source: _PersistentSessionSource | _ReplaySource,
) -> program_011.SessionResult:
    rows: list[raw_contract.RawBar] = []
    pages: list[program_011.PageEvidence] = []
    seen_coordinates: set[program_011.Coordinate] = set()
    seen_hashes: set[str] = set()
    seen_tokens: set[str] = set()
    incoming_token: str | None = None
    frontier: program_011.Coordinate | None = None
    response_bytes = 0
    for page_index in range(1, program_012.MAXIMUM_PAGES_PER_SESSION + 1):
        intent = program_011.PageIntent(
            request.identity, page_index, request.url(incoming_token), incoming_token
        )
        response = source.response(intent)
        response_bytes += len(response.body)
        if len(response.body) > program_012.MAXIMUM_RESPONSE_PAGE_BYTES:
            raise Program012AuthorityError("Program 012 response exceeds the 8 MiB page ceiling")
        if response_bytes > program_012.MAXIMUM_SESSION_RESPONSE_BYTES:
            raise Program012AuthorityError("Program 012 session exceeds the 8 MiB byte ceiling")
        retained = source.retain(page_index, response.body)
        _raise_for_status(response.status)
        page_rows, outgoing_token = request.parse_page(response.body)
        if len(page_rows) > program_011.PAGE_ROW_LIMIT:
            raise Program012AuthorityError("Program 012 response exceeds the 1,000-row limit")
        if retained.sha256 in seen_hashes:
            raise Program012AuthorityError("Program 012 response page is repeated")
        page_coordinates = {row.coordinate for row in page_rows}
        if page_coordinates & seen_coordinates:
            raise Program012AuthorityError("Program 012 coordinate repeats across pages")
        if page_rows and frontier is not None and page_rows[0].coordinate <= frontier:
            raise Program012AuthorityError("Program 012 page ordering does not progress")
        if outgoing_token is not None:
            if outgoing_token == incoming_token or outgoing_token in seen_tokens:
                raise Program012AuthorityError("Program 012 pagination token is repeated")
            if not page_rows:
                raise Program012AuthorityError("Program 012 nonterminal page makes zero progress")
        seen_hashes.add(retained.sha256)
        seen_coordinates.update(page_coordinates)
        rows.extend(page_rows)
        if page_rows:
            frontier = page_rows[-1].coordinate
        pages.append(
            program_011.PageEvidence(
                page_index,
                retained.byte_count,
                retained.sha256,
                len(page_rows),
                incoming_token is not None,
                outgoing_token is not None,
                page_rows[0].coordinate if page_rows else None,
                page_rows[-1].coordinate if page_rows else None,
            )
        )
        if outgoing_token is None:
            missingness = program_011.classify_missingness(
                request.expected_coordinates, seen_coordinates, terminal=True
            )
            return program_011.SessionResult(request, tuple(rows), tuple(pages), missingness)
        seen_tokens.add(outgoing_token)
        if page_index == program_012.MAXIMUM_PAGES_PER_SESSION:
            raise ChainIncompleteError("Program 012 chain is incomplete at the resource safety cap")
        incoming_token = outgoing_token
    raise AssertionError("unreachable Program 012 pagination state")


def _reconstruct_state(
    root_descriptor: int,
    *,
    authority: Mapping[str, Any],
    source_commit: str,
    budget: _Budget | None = None,
) -> _Budget:
    entries = set(os.listdir(root_descriptor))
    allowed = {
        "active-authority.json",
        "claim.json",
        "run.lock",
        *_DERIVED_KEYS,
        *_TERMINAL_KEYS,
    }
    page_entries: set[str] = set()
    for entry in entries - allowed:
        if _PAGE_KEY.fullmatch(entry):
            page_entries.add(entry)
        elif _CREDENTIAL_KEY.fullmatch(entry) or entry.startswith("tmp-"):
            continue
        else:
            raise Program012AuthorityError("Program 012 private checkpoint contains unknown state")
    credential_loads = _credential_load_count(
        root_descriptor,
        authority_fingerprint=str(authority["authority_fingerprint"]),
        source_commit=source_commit,
    )
    if page_entries:
        if credential_loads == 0:
            raise Program012AuthorityError("Program 012 page evidence lacks credential audit")
        if not _exists(root_descriptor, "claim.json"):
            raise Program012AuthorityError("Program 012 page evidence lacks a transport claim")
        _validate_claim(root_descriptor, authority, source_commit)
    elif _exists(root_descriptor, "claim.json"):
        raise Program012AuthorityError("Program 012 transport claim lacks page evidence")

    expected_sessions = {request.session for request in program_012.acquisition_requests()}
    for entry in page_entries:
        match = _PAGE_KEY.fullmatch(entry)
        assert match is not None
        try:
            session = date.fromisoformat(match.group("session"))
            page_index = int(match.group("page"))
        except ValueError as error:
            raise Program012AuthorityError("Program 012 page key is invalid") from error
        if session not in expected_sessions or not 1 <= page_index <= 16:
            raise Program012AuthorityError("Program 012 page key is outside the request plan")

    budget = _Budget() if budget is None else budget
    if (
        budget.requests
        or budget.responses
        or budget.response_bytes
        or budget.session_bytes
        or budget.pages
        or budget.latest_response_at is not None
    ):
        raise Program012AuthorityError("Program 012 recovery budget is not empty")
    frontier_found = False
    for request in program_012.acquisition_requests():
        session_entries = {
            entry for entry in page_entries if entry.startswith(f"session-{request.session}-")
        }
        if frontier_found:
            if session_entries:
                raise Program012AuthorityError("Program 012 checkpoint skips a request session")
            continue
        source = _ReplaySource(root_descriptor, request, authority, source_commit, budget)
        try:
            result = _execute_session(request, source)
        except _TransportRequired:
            completed_pages = sum(
                page["session"] == request.session.isoformat() for page in budget.pages
            )
            if session_entries != _expected_session_entries(request, completed_pages):
                raise Program012AuthorityError(
                    "Program 012 checkpoint skips a request page"
                ) from None
            frontier_found = True
        else:
            if session_entries != _expected_session_entries(request, len(result.pages)):
                raise Program012AuthorityError("Program 012 checkpoint continues after null token")
    return budget


def _load_completed_page(
    root_descriptor: int,
    request: program_011.SessionRequest,
    intent: program_011.PageIntent,
    authority: Mapping[str, Any],
    source_commit: str,
) -> tuple[raw_contract.RawResponse, datetime]:
    prefix = _page_prefix(request, intent.page_index)
    expected_intent = _intent_payload(authority, source_commit, request, intent)
    if _read(root_descriptor, f"{prefix}.intent.json") != expected_intent:
        raise Program012AuthorityError("Program 012 request intent checkpoint differs")
    body = _read(root_descriptor, f"{prefix}.body")
    receipt_raw = _read(root_descriptor, f"{prefix}.receipt.json")
    receipt = _json_object(receipt_raw, "response receipt")
    status = receipt.get("status")
    if type(status) is not int or not 100 <= status <= 599:
        raise Program012AuthorityError("Program 012 response status is invalid")
    response = raw_contract.RawResponse(status, body)
    observed_at = _parse_observed_at(receipt.get("observed_at"))
    expected_receipt = _response_receipt(
        authority,
        source_commit,
        request,
        intent,
        response,
        _format_observed_at(observed_at),
    )
    if (
        receipt != expected_receipt
        or receipt_raw != (canonical_json(expected_receipt) + "\n").encode()
    ):
        raise Program012AuthorityError("Program 012 response checkpoint differs")
    return response, observed_at


def _intent_payload(
    authority: Mapping[str, Any],
    source_commit: str,
    request: program_011.SessionRequest,
    intent: program_011.PageIntent,
) -> bytes:
    return (
        canonical_json(
            {
                "schema_version": "program-012-private-request-intent-v1",
                "authority_fingerprint": authority["authority_fingerprint"],
                "source_commit": source_commit,
                "session": request.session.isoformat(),
                "page_index": intent.page_index,
                "request_identity": intent.request_identity,
                "incoming_page_token": intent.incoming_page_token,
                "url": intent.url,
            }
        )
        + "\n"
    ).encode()


def _response_receipt(
    authority: Mapping[str, Any],
    source_commit: str,
    request: program_011.SessionRequest,
    intent: program_011.PageIntent,
    response: raw_contract.RawResponse,
    observed_at: str,
) -> dict[str, Any]:
    _parse_observed_at(observed_at)
    if type(response.status) is not int or not 100 <= response.status <= 599:
        raise Program012AuthorityError("Program 012 response status is invalid")
    body = response.body
    return {
        "schema_version": "program-012-private-response-receipt-v1",
        "authority_fingerprint": authority["authority_fingerprint"],
        "source_commit": source_commit,
        "session": request.session.isoformat(),
        "page_index": intent.page_index,
        "request_identity": intent.request_identity,
        "status": response.status,
        "retained_response_bytes": len(body),
        "response_sha256": hashlib.sha256(body).hexdigest(),
        "observed_at": observed_at,
    }


def _validate_page_intent(
    request: program_011.SessionRequest, intent: program_011.PageIntent
) -> None:
    if (
        type(request) is not program_011.SessionRequest
        or type(intent) is not program_011.PageIntent
        or intent.request_identity != request.identity
        or not 1 <= intent.page_index <= program_012.MAXIMUM_PAGES_PER_SESSION
        or intent.url != request.url(intent.incoming_page_token)
    ):
        raise Program012AuthorityError("Program 012 request intent differs")


def _validate_http_request(request: Request, intent: program_011.PageIntent) -> None:
    matching = [
        item
        for item in program_012.acquisition_requests()
        if item.identity == intent.request_identity
        and item.url(intent.incoming_page_token) == request.full_url
    ]
    parsed = urlsplit(request.full_url)
    try:
        parameters = tuple(parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True))
    except ValueError as error:
        raise Program012AuthorityError("Program 012 endpoint or query differs") from error
    expected: tuple[tuple[str, str], ...] = ()
    if len(matching) == 1:
        expected = matching[0].parameters
        if intent.incoming_page_token is not None:
            expected = (*expected, ("page_token", intent.incoming_page_token))
    if (
        request.get_method() != "GET"
        or parsed.scheme != "https"
        or parsed.hostname != "data.alpaca.markets"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/v2/stocks/bars"
        or parsed.fragment
        or len(matching) != 1
        or parameters != expected
    ):
        raise Program012AuthorityError("Program 012 endpoint or query differs")


def _raise_for_status(status: int) -> None:
    if status == 200:
        return
    if status == 401:
        raise Program012AuthorityError(
            "OHLCV-AUTHENTICATION-FAIL-CONSUMED-NO-RETRY: Alpaca returned HTTP 401"
        )
    if status == 403:
        raise Program012AuthorityError(
            "OHLCV-ACCESS-FAIL-CONSUMED-NO-RETRY-NO-PURCHASE: Alpaca returned HTTP 403"
        )
    if status == 429:
        raise Program012AuthorityError(
            "OHLCV-ACCESS-FAIL-CONSUMED-NO-RETRY: Alpaca returned HTTP 429"
        )
    if 300 <= status < 400:
        raise Program012AuthorityError("Program 012 OHLCV redirect attempt rejected")
    if 500 <= status < 600:
        raise Program012AuthorityError(
            f"OHLCV-ACCESS-FAIL-CONSUMED-NO-RETRY: Alpaca returned HTTP {status}"
        )
    raise Program012AuthorityError(f"Program 012 OHLCV returned unexpected HTTP {status}")


def _claim_payload(authority: Mapping[str, Any], source_commit: str) -> bytes:
    return (
        canonical_json(
            {
                "schema_version": "program-012-private-acquisition-claim-v1",
                "authority_id": authority["authority_id"],
                "authority_fingerprint": authority["authority_fingerprint"],
                "source_commit": source_commit,
                "operation_manifest": OPERATION_MANIFEST,
                "consumption_boundary": CONSUMPTION_BOUNDARY,
                "scientific_use_consumed": True,
                "terminal_fallback": {
                    "status": "FAIL-CONSUMED-NO-RETRY",
                    "request_reissue_allowed": False,
                },
            }
        )
        + "\n"
    ).encode()


def _validate_claim(root_descriptor: int, authority: Mapping[str, Any], source_commit: str) -> None:
    if _read(root_descriptor, "claim.json") != _claim_payload(authority, source_commit):
        raise Program012AuthorityError("Program 012 transport claim differs")


def _failure_payload(
    root_descriptor: int,
    error: BaseException,
    budget: _Budget | None,
    authority: Mapping[str, Any],
    source_commit: str,
) -> bytes:
    record: dict[str, Any] = {
        "schema_version": "program-012-private-acquisition-failure-v2",
        "program_id": PROGRAM_ID,
        "authority_id": authority["authority_id"],
        "authority_fingerprint": authority["authority_fingerprint"],
        "source_commit": source_commit,
        "public_terminal_path": PUBLIC_TERMINAL_PATH.as_posix(),
        "status": "FAIL-CONSUMED-NO-RETRY",
        "admission_passed": False,
        "failure_class": type(error).__name__,
        "failure_classification": getattr(error, "classification", type(error).__name__),
        "provider_transport_attempted": _exists(root_descriptor, "claim.json"),
        "scientific_use_consumed": True,
        "session_count": program_012.EXPECTED_SESSION_COUNT,
        "request_count": None if budget is None else budget.requests,
        "response_count": None if budget is None else budget.responses,
        "response_bytes": None if budget is None else budget.response_bytes,
        "sessions_with_completed_responses": (
            None if budget is None else len({str(page["session"]) for page in budget.pages})
        ),
        "raw_row_count": None,
        "expected_canonical_coordinate_count": program_012.EXPECTED_COORDINATE_COUNT,
        "missing_coordinate_count": None,
        "excluded_full_session_count": None,
        "credential_loads": _credential_load_count(root_descriptor),
        "aggregate_gate_results": {
            "structural_admission_passed": False,
            "structural_admission_evaluated": False,
            "failure_count": None,
            "failure_classes": [],
        },
        "response_manifest_sha256": _evidence_sha256_if_present(
            root_descriptor, "response-manifest.json"
        ),
        "canonical_raw_sha256": _evidence_sha256_if_present(root_descriptor, "canonical-raw.jsonl"),
        "private_missingness_sha256": _evidence_sha256_if_present(
            root_descriptor, "missing-coordinates.json"
        ),
        "structural_admission_sha256": _evidence_sha256_if_present(
            root_descriptor, "structural-admission.json"
        ),
        "private_dataset_manifest_sha256": _evidence_sha256_if_present(
            root_descriptor, "dataset-manifest.json"
        ),
        "public_dataset_manifest": None,
        "dataset_identity": None,
        "unpaired_credential_attempts_count_as_load": True,
        "automatic_retries": 0,
        "dataset_admitted": False,
        "strategy_calculations": 0,
        "strategy_returns": 0,
        "credentials_stored": False,
        "exact_missing_coordinates_private": True,
        "exact_unexpected_exclusion_dates_private": True,
        "program_002_admission": False,
        "observed_at": _utc_now(),
    }
    record["terminal_fingerprint"] = fingerprint(record)
    return (canonical_json(record) + "\n").encode()


def _evidence_sha256_if_present(root_descriptor: int, key: str) -> str | None:
    return (
        hashlib.sha256(_read(root_descriptor, key)).hexdigest()
        if _exists(root_descriptor, key)
        else None
    )


def _reserve_process_credential_access(write_attempt: Callable[[], None]) -> None:
    global _PROCESS_CREDENTIAL_PID
    process_id = os.getpid()
    with _PROCESS_CREDENTIAL_LOCK:
        if process_id == _PROCESS_CREDENTIAL_PID:
            raise Program012AuthorityError(
                "Program 012 credential access is already consumed in this process"
            )
        try:
            write_attempt()
        finally:
            # A failed or interrupted audit write must also close access in this PID.
            _PROCESS_CREDENTIAL_PID = process_id


def _exact_terminal_object(value: Any, expected_keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != expected_keys:
        raise Program012AuthorityError(f"Program 012 {label} schema differs")
    return cast(dict[str, Any], value)


def _terminal_count(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise Program012AuthorityError(f"Program 012 {label} differs")
    return value


def _terminal_sha256(value: Any, label: str) -> str:
    if type(value) is not str or _HEX_64.fullmatch(value) is None:
        raise Program012AuthorityError(f"Program 012 {label} differs")
    return value


def _dataset_identities(
    *,
    authority_fingerprint: str,
    source_commit: str,
    response_manifest_sha256: str,
    canonical_raw_sha256: str,
    private_missingness_sha256: str,
    admitted_session_index_fingerprint: str,
    admission: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    if admission.get("admission_passed") is not True:
        return None, None
    public_inputs = {
        "operation_manifest": OPERATION_MANIFEST,
        "authority_fingerprint": authority_fingerprint,
        "source_commit": source_commit,
        "response_manifest_sha256": response_manifest_sha256,
        "canonical_raw_sha256": canonical_raw_sha256,
        "action_ledger": _ACTION_LEDGER_MANIFEST,
    }
    return fingerprint(public_inputs), fingerprint(
        {
            **public_inputs,
            "private_missingness_sha256": private_missingness_sha256,
            "admitted_session_index_fingerprint": admitted_session_index_fingerprint,
            "admission_fingerprint": admission["admission_fingerprint"],
        }
    )


def _terminal_dates(value: Any, label: str) -> tuple[date, ...]:
    if type(value) is not list or any(type(item) is not str for item in value):
        raise Program012AuthorityError(f"Program 012 {label} differs")
    try:
        parsed = tuple(date.fromisoformat(item) for item in value)
    except ValueError as error:
        raise Program012AuthorityError(f"Program 012 {label} differs") from error
    if list(value) != sorted(set(value)):
        raise Program012AuthorityError(f"Program 012 {label} differs")
    return parsed


def _validated_structural_admission(root_descriptor: int) -> dict[str, Any]:
    raw = _read(root_descriptor, "structural-admission.json")
    admission = _json_object(raw, "structural admission")
    if raw != (canonical_json(admission) + "\n").encode():
        raise Program012AuthorityError("Program 012 structural admission is not canonical")
    unsigned = dict(admission)
    stored_fingerprint = unsigned.pop("admission_fingerprint", None)
    admission_passed = admission.get("admission_passed")
    failures = admission.get("failures")
    if (
        type(stored_fingerprint) is not str
        or _HEX_64.fullmatch(stored_fingerprint) is None
        or stored_fingerprint != fingerprint(unsigned)
        or type(admission_passed) is not bool
        or type(failures) is not list
        or any(type(item) is not str or item not in _ADMISSION_FAILURES for item in failures)
        or failures != sorted(set(failures))
        or (admission_passed and failures)
        or (not admission_passed and not failures)
        or admission.get("schema_version") != "program-012-private-structural-admission-report-v1"
        or admission.get("program_id") != PROGRAM_ID
        or admission.get("status")
        != (
            "ADMITTED-PROGRAM-012-RAW-STRUCTURAL-PREFIX"
            if admission_passed
            else "TERMINAL-FAIL-CONSUMED-NO-RETRY"
        )
        or admission.get("program_002_admission") is not False
        or admission.get("program_002_quote_windows_evaluated") != 0
        or admission.get("strategy_metrics_present") is not False
    ):
        raise Program012AuthorityError("Program 012 structural admission differs")
    fixed = _terminal_dates(admission.get("fixed_quarantine_sessions"), "fixed exclusions")
    unexpected = _terminal_dates(
        admission.get("unexpected_excluded_sessions"), "unexpected exclusions"
    )
    excluded = set(fixed) | set(unexpected)
    missing_count = _terminal_count(
        admission.get("missing_coordinate_count"), "admission missing count"
    )
    excluded_count = _terminal_count(
        admission.get("excluded_full_session_count"), "admission excluded count"
    )
    if (
        set(fixed) & set(unexpected)
        or excluded_count != len(excluded)
        or not excluded <= program_012.full_trade_sessions()
        or missing_count > program_012.EXPECTED_COORDINATE_COUNT
    ):
        raise Program012AuthorityError("Program 012 structural admission differs")
    return admission


def _validated_missingness_count(root_descriptor: int) -> int:
    raw = _read(root_descriptor, "missing-coordinates.json")
    value = _exact_terminal_object(
        _json_object(raw, "missing coordinates"),
        {"schema_version", "program_id", "sessions"},
        "missing coordinates",
    )
    if raw != (canonical_json(value) + "\n").encode():
        raise Program012AuthorityError("Program 012 missing coordinates are not canonical")
    sessions = value["sessions"]
    if (
        value["schema_version"] != "program-012-private-missing-coordinates-v1"
        or value["program_id"] != PROGRAM_ID
        or type(sessions) is not dict
    ):
        raise Program012AuthorityError("Program 012 missing coordinates differ")
    count = 0
    for session, coordinates in sessions.items():
        if type(session) is not str or type(coordinates) is not list:
            raise Program012AuthorityError("Program 012 missing coordinates differ")
        try:
            date.fromisoformat(session)
        except ValueError as error:
            raise Program012AuthorityError("Program 012 missing coordinates differ") from error
        if any(type(coordinate) is not str for coordinate in coordinates) or coordinates != sorted(
            set(coordinates)
        ):
            raise Program012AuthorityError("Program 012 missing coordinates differ")
        count += len(coordinates)
    return count


def _admitted_session_fingerprint(admission: Mapping[str, Any]) -> str:
    excluded = {
        *_terminal_dates(admission.get("fixed_quarantine_sessions"), "fixed exclusions"),
        *_terminal_dates(admission.get("unexpected_excluded_sessions"), "unexpected exclusions"),
    }
    return fingerprint(
        tuple(
            request.session.isoformat()
            for request in program_012.acquisition_requests()
            if request.session in program_012.full_trade_sessions()
            and request.session not in excluded
        )
    )


def _validate_terminal_evidence_hashes(
    root_descriptor: int, record: Mapping[str, Any], *, required: bool
) -> None:
    for field, key in (
        ("response_manifest_sha256", "response-manifest.json"),
        ("canonical_raw_sha256", "canonical-raw.jsonl"),
        ("private_missingness_sha256", "missing-coordinates.json"),
        ("structural_admission_sha256", "structural-admission.json"),
        ("private_dataset_manifest_sha256", "dataset-manifest.json"),
    ):
        actual = _evidence_sha256_if_present(root_descriptor, key)
        stored = record[field]
        if required and actual is None:
            raise Program012AuthorityError("Program 012 terminal evidence is incomplete")
        if stored != actual or (
            stored is not None and (type(stored) is not str or _HEX_64.fullmatch(stored) is None)
        ):
            raise Program012AuthorityError("Program 012 terminal evidence hash differs")


def _validated_acquisition_gates(value: Any, admission_passed: bool) -> dict[str, Any]:
    gates = _exact_terminal_object(value, _ACQUISITION_GATE_KEYS, "acquisition gate result")
    failures = gates["failure_classes"]
    if type(failures) is not list or any(
        type(item) is not str or item not in _ADMISSION_FAILURES for item in failures
    ):
        raise Program012AuthorityError("Program 012 acquisition gate result differs")
    if (
        failures != sorted(set(failures))
        or gates["structural_admission_passed"] is not admission_passed
        or type(gates["failure_count"]) is not int
        or gates["failure_count"] != len(failures)
        or (admission_passed and failures)
        or (not admission_passed and not failures)
    ):
        raise Program012AuthorityError("Program 012 acquisition gate result differs")
    return {
        "structural_admission_passed": admission_passed,
        "failure_count": len(failures),
        "failure_classes": list(failures),
    }


def _validated_runtime_failure_gates(value: Any) -> dict[str, Any]:
    gates = _exact_terminal_object(value, _RUNTIME_FAILURE_GATE_KEYS, "runtime failure gate result")
    if (
        gates["structural_admission_passed"] is not False
        or gates["structural_admission_evaluated"] is not False
        or gates["failure_count"] is not None
        or gates["failure_classes"] != []
        or type(gates["failure_classes"]) is not list
    ):
        raise Program012AuthorityError("Program 012 runtime failure gate result differs")
    return {
        "structural_admission_passed": False,
        "structural_admission_evaluated": False,
        "failure_count": None,
        "failure_classes": [],
    }


def _validated_public_dataset_manifest(record: Mapping[str, Any]) -> dict[str, Any] | None:
    if record["admission_passed"] is False:
        if record["public_dataset_manifest"] is not None:
            raise Program012AuthorityError("Program 012 public dataset manifest differs")
        return None
    dataset = _exact_terminal_object(
        record["public_dataset_manifest"], _PUBLIC_DATASET_KEYS, "public dataset manifest"
    )
    raw_row_count = _terminal_count(dataset["raw_row_count"], "public raw row count")
    expected_count = _terminal_count(
        dataset["expected_coordinate_count"], "public expected coordinate count"
    )
    missing_count = _terminal_count(dataset["missing_coordinate_count"], "public missing count")
    excluded_count = _terminal_count(
        dataset["excluded_full_session_count"], "public excluded session count"
    )
    admitted_count = _terminal_count(
        dataset["admitted_full_session_count"], "public admitted session count"
    )
    if (
        dataset["schema_version"] != "program-012-public-raw-structural-prefix-dataset-manifest-v1"
        or dataset["program_id"] != PROGRAM_ID
        or dataset["authority_id"] != record["authority_id"]
        or dataset["authority_fingerprint"] != record["authority_fingerprint"]
        or dataset["source_commit"] != record["source_commit"]
        or dataset["status"] != "ADMITTED-PROGRAM-012-RAW-STRUCTURAL-PREFIX"
        or dataset["dataset_identity"] != record["dataset_identity"]
        or dataset["canonical_raw_sha256"] != record["canonical_raw_sha256"]
        or raw_row_count != record["raw_row_count"]
        or expected_count != record["expected_canonical_coordinate_count"]
        or missing_count != record["missing_coordinate_count"]
        or excluded_count != record["excluded_full_session_count"]
        or admitted_count != len(program_012.full_trade_sessions()) - excluded_count
        or dataset["exact_missingness_private"] is not True
        or dataset["exact_excluded_sessions_private"] is not True
        or dataset["program_002_admission"] is not False
        or dataset["strategy_metrics_present"] is not False
    ):
        raise Program012AuthorityError("Program 012 public dataset manifest differs")
    return {
        "schema_version": dataset["schema_version"],
        "program_id": dataset["program_id"],
        "authority_id": dataset["authority_id"],
        "authority_fingerprint": dataset["authority_fingerprint"],
        "source_commit": dataset["source_commit"],
        "status": dataset["status"],
        "dataset_identity": dataset["dataset_identity"],
        "canonical_raw_sha256": dataset["canonical_raw_sha256"],
        "raw_row_count": dataset["raw_row_count"],
        "expected_coordinate_count": dataset["expected_coordinate_count"],
        "missing_coordinate_count": dataset["missing_coordinate_count"],
        "excluded_full_session_count": dataset["excluded_full_session_count"],
        "admitted_full_session_count": dataset["admitted_full_session_count"],
        "exact_missingness_private": True,
        "exact_excluded_sessions_private": True,
        "program_002_admission": False,
        "strategy_metrics_present": False,
    }


def _validate_private_dataset_manifest(
    root_descriptor: int,
    record: Mapping[str, Any],
    admission: Mapping[str, Any],
    private_dataset_identity: str | None,
    admitted_session_index_fingerprint: str,
) -> None:
    raw = _read(root_descriptor, "dataset-manifest.json")
    dataset = _exact_terminal_object(
        _json_object(raw, "private dataset manifest"),
        _PRIVATE_DATASET_KEYS,
        "private dataset manifest",
    )
    if raw != (canonical_json(dataset) + "\n").encode():
        raise Program012AuthorityError("Program 012 private dataset manifest is not canonical")
    excluded_count = _terminal_count(
        admission.get("excluded_full_session_count"), "admission excluded count"
    )
    if (
        dataset["schema_version"] != "program-012-raw-structural-prefix-dataset-manifest-v1"
        or dataset["program_id"] != PROGRAM_ID
        or dataset["authority_id"] != record["authority_id"]
        or dataset["authority_fingerprint"] != record["authority_fingerprint"]
        or dataset["source_commit"] != record["source_commit"]
        or dataset["status"] != admission["status"]
        or dataset["dataset_identity"] != private_dataset_identity
        or dataset["response_manifest_sha256"] != record["response_manifest_sha256"]
        or dataset["canonical_raw_sha256"] != record["canonical_raw_sha256"]
        or dataset["private_missingness_sha256"] != record["private_missingness_sha256"]
        or dataset["structural_admission_sha256"] != record["structural_admission_sha256"]
        or dataset["raw_row_count"] != record["raw_row_count"]
        or dataset["expected_coordinate_count"] != record["expected_canonical_coordinate_count"]
        or dataset["missing_coordinate_count"] != record["missing_coordinate_count"]
        or dataset["excluded_full_session_count"] != excluded_count
        or dataset["admitted_full_session_count"]
        != len(program_012.full_trade_sessions()) - excluded_count
        or dataset["admitted_session_index_fingerprint"] != admitted_session_index_fingerprint
        or dataset["exact_missingness_private"] is not True
        or dataset["program_002_admission"] is not False
        or dataset["strategy_metrics_present"] is not False
    ):
        raise Program012AuthorityError("Program 012 private dataset manifest differs")


def _validate_acquisition_receipt(root_descriptor: int, record: Mapping[str, Any]) -> None:
    if type(record["admission_passed"]) is not bool:
        raise Program012AuthorityError("Program 012 acquisition receipt differs")
    admission_passed = record["admission_passed"]
    session_count = _terminal_count(record["session_count"], "session count")
    request_count = _terminal_count(record["request_count"], "request count")
    response_count = _terminal_count(record["response_count"], "response count")
    response_bytes = _terminal_count(record["response_bytes"], "response byte count")
    raw_row_count = _terminal_count(record["raw_row_count"], "raw row count")
    expected_count = _terminal_count(
        record["expected_canonical_coordinate_count"], "expected coordinate count"
    )
    missing_count = _terminal_count(record["missing_coordinate_count"], "missing count")
    excluded_count = _terminal_count(
        record["excluded_full_session_count"], "excluded session count"
    )
    credential_loads = _terminal_count(record["credential_loads"], "credential load count")
    durable_credential_loads = _credential_load_count(
        root_descriptor,
        authority_fingerprint=record["authority_fingerprint"],
        source_commit=record["source_commit"],
    )
    dataset_identity = record["dataset_identity"]
    private_dataset_identity = record["private_dataset_identity"]
    if (
        record["schema_version"] != "program-012-private-acquisition-receipt-v2"
        or record["status"]
        != (
            "ADMITTED-PROGRAM-012-RAW-STRUCTURAL-PREFIX"
            if admission_passed
            else "TERMINAL-FAIL-CONSUMED-NO-RETRY"
        )
        or session_count != program_012.EXPECTED_SESSION_COUNT
        or not session_count <= request_count <= program_012.MAXIMUM_REQUESTS_AND_RESPONSES
        or response_count != request_count
        or response_bytes > program_012.MAXIMUM_TOTAL_RESPONSE_BYTES
        or expected_count != program_012.EXPECTED_COORDINATE_COUNT
        or raw_row_count + missing_count != expected_count
        or excluded_count > len(program_012.full_trade_sessions())
        or credential_loads != durable_credential_loads
        or not 1 <= credential_loads <= request_count
        or (
            admission_passed
            and (type(dataset_identity) is not str or _HEX_64.fullmatch(dataset_identity) is None)
        )
        or (
            admission_passed
            and (
                type(private_dataset_identity) is not str
                or _HEX_64.fullmatch(private_dataset_identity) is None
                or private_dataset_identity == dataset_identity
            )
        )
        or (
            not admission_passed
            and (dataset_identity is not None or private_dataset_identity is not None)
        )
        or type(record["automatic_retries"]) is not int
        or record["automatic_retries"] != 0
        or record["credentials_stored"] is not False
        or record["exact_missing_coordinates_private"] is not True
        or record["exact_unexpected_exclusion_dates_private"] is not True
        or record["program_002_admission"] is not False
        or type(record["strategy_calculations"]) is not int
        or record["strategy_calculations"] != 0
        or type(record["strategy_returns"]) is not int
        or record["strategy_returns"] != 0
    ):
        raise Program012AuthorityError("Program 012 acquisition receipt differs")
    _terminal_sha256(record["response_manifest_sha256"], "response manifest hash")
    _terminal_sha256(record["canonical_raw_sha256"], "canonical raw hash")
    _terminal_sha256(record["private_missingness_sha256"], "missingness hash")
    _terminal_sha256(record["structural_admission_sha256"], "admission hash")
    _terminal_sha256(record["private_dataset_manifest_sha256"], "dataset manifest hash")
    _validate_terminal_evidence_hashes(root_descriptor, record, required=True)
    admission = _validated_structural_admission(root_descriptor)
    failures = cast(list[str], admission["failures"])
    gates = _validated_acquisition_gates(record["aggregate_gate_results"], admission_passed)
    expected_gates = {
        "structural_admission_passed": admission_passed,
        "failure_count": len(failures),
        "failure_classes": failures,
    }
    admitted_session_index_fingerprint = _admitted_session_fingerprint(admission)
    expected_dataset_identity, expected_private_dataset_identity = _dataset_identities(
        authority_fingerprint=str(record["authority_fingerprint"]),
        source_commit=str(record["source_commit"]),
        response_manifest_sha256=str(record["response_manifest_sha256"]),
        canonical_raw_sha256=str(record["canonical_raw_sha256"]),
        private_missingness_sha256=str(record["private_missingness_sha256"]),
        admitted_session_index_fingerprint=admitted_session_index_fingerprint,
        admission=admission,
    )
    if (
        admission["admission_passed"] is not admission_passed
        or admission["status"] != record["status"]
        or admission["missing_coordinate_count"] != missing_count
        or admission["excluded_full_session_count"] != excluded_count
        or _validated_missingness_count(root_descriptor) != missing_count
        or gates != expected_gates
        or dataset_identity != expected_dataset_identity
        or private_dataset_identity != expected_private_dataset_identity
    ):
        raise Program012AuthorityError("Program 012 acquisition receipt differs")
    _validate_private_dataset_manifest(
        root_descriptor,
        record,
        admission,
        expected_private_dataset_identity,
        admitted_session_index_fingerprint,
    )
    _validated_public_dataset_manifest(record)
    _parse_observed_at(record["observed_at"])
    if not _exists(root_descriptor, "claim.json"):
        raise Program012AuthorityError("Program 012 acquisition receipt lacks a claim")


def _validate_terminal_failure(root_descriptor: int, record: Mapping[str, Any]) -> None:
    session_count = _terminal_count(record["session_count"], "failure session count")
    expected_count = _terminal_count(
        record["expected_canonical_coordinate_count"], "failure expected coordinate count"
    )
    counts = tuple(
        record[field]
        for field in (
            "request_count",
            "response_count",
            "response_bytes",
            "sessions_with_completed_responses",
        )
    )
    if any(value is None for value in counts):
        if any(value is not None for value in counts):
            raise Program012AuthorityError("Program 012 failure counts differ")
    else:
        request_count, response_count, response_bytes, completed_sessions = (
            _terminal_count(value, "failure count") for value in counts
        )
        if (
            request_count > program_012.MAXIMUM_REQUESTS_AND_RESPONSES
            or response_count > request_count
            or request_count - response_count > 1
            or response_bytes > program_012.MAXIMUM_TOTAL_RESPONSE_BYTES
            or completed_sessions > min(program_012.EXPECTED_SESSION_COUNT, response_count)
        ):
            raise Program012AuthorityError("Program 012 failure counts differ")
    failure_class = record["failure_class"]
    failure_classification = record["failure_classification"]
    expected_classification = (
        "CHAIN-INCOMPLETE-RESOURCE-CAP"
        if failure_class == "ChainIncompleteError"
        else failure_class
    )
    credential_loads = _terminal_count(record["credential_loads"], "credential load count")
    durable_credential_loads = _credential_load_count(
        root_descriptor,
        authority_fingerprint=record["authority_fingerprint"],
        source_commit=record["source_commit"],
    )
    if (
        record["schema_version"] != "program-012-private-acquisition-failure-v2"
        or record["status"] != "FAIL-CONSUMED-NO-RETRY"
        or record["admission_passed"] is not False
        or type(failure_class) is not str
        or not failure_class.isidentifier()
        or len(failure_class) > 128
        or failure_classification != expected_classification
        or record["provider_transport_attempted"] is not _exists(root_descriptor, "claim.json")
        or record["scientific_use_consumed"] is not True
        or session_count != program_012.EXPECTED_SESSION_COUNT
        or record["raw_row_count"] is not None
        or expected_count != program_012.EXPECTED_COORDINATE_COUNT
        or record["missing_coordinate_count"] is not None
        or record["excluded_full_session_count"] is not None
        or credential_loads != durable_credential_loads
        or credential_loads > program_012.MAXIMUM_REQUESTS_AND_RESPONSES
        or record["public_dataset_manifest"] is not None
        or record["dataset_identity"] is not None
        or record["unpaired_credential_attempts_count_as_load"] is not True
        or type(record["automatic_retries"]) is not int
        or record["automatic_retries"] != 0
        or record["dataset_admitted"] is not False
        or type(record["strategy_calculations"]) is not int
        or record["strategy_calculations"] != 0
        or type(record["strategy_returns"]) is not int
        or record["strategy_returns"] != 0
        or record["credentials_stored"] is not False
        or record["exact_missing_coordinates_private"] is not True
        or record["exact_unexpected_exclusion_dates_private"] is not True
        or record["program_002_admission"] is not False
    ):
        raise Program012AuthorityError("Program 012 failure evidence differs")
    _validated_runtime_failure_gates(record["aggregate_gate_results"])
    _validate_terminal_evidence_hashes(root_descriptor, record, required=False)
    _parse_observed_at(record["observed_at"])


def _load_terminal_record(
    root_descriptor: int,
    authority: Mapping[str, Any],
    source_commit: str,
) -> tuple[str, Mapping[str, Any]]:
    present = [key for key in sorted(_TERMINAL_KEYS) if _exists(root_descriptor, key)]
    if len(present) != 1:
        raise Program012AuthorityError("Program 012 terminal evidence set differs")
    key = present[0]
    raw = _read(root_descriptor, key)
    record = _json_object(raw, "terminal evidence")
    _exact_terminal_object(
        record,
        _ACQUISITION_RECEIPT_KEYS if key == "acquisition-receipt.json" else _TERMINAL_FAILURE_KEYS,
        "terminal evidence",
    )
    if raw != (canonical_json(record) + "\n").encode():
        raise Program012AuthorityError("Program 012 terminal evidence is not canonical")
    unsigned = dict(record)
    stored_fingerprint = unsigned.pop("terminal_fingerprint", None)
    if (
        type(stored_fingerprint) is not str
        or _HEX_64.fullmatch(stored_fingerprint) is None
        or stored_fingerprint != fingerprint(unsigned)
        or record.get("program_id") != PROGRAM_ID
        or record.get("authority_id") != authority.get("authority_id")
        or record.get("authority_fingerprint") != authority.get("authority_fingerprint")
        or _HEX_64.fullmatch(str(record.get("authority_fingerprint"))) is None
        or record.get("source_commit") != source_commit
        or _HEX_40.fullmatch(str(record.get("source_commit"))) is None
        or record.get("public_terminal_path") != PUBLIC_TERMINAL_PATH.as_posix()
        or record.get("credentials_stored") is not False
    ):
        raise Program012AuthorityError("Program 012 terminal evidence binding differs")
    if key == "acquisition-receipt.json":
        _validate_acquisition_receipt(root_descriptor, record)
    else:
        _validate_terminal_failure(root_descriptor, record)
    if _exists(root_descriptor, "claim.json"):
        _validate_claim(root_descriptor, authority, source_commit)
    return key, record


def _public_terminal_payload(
    root_descriptor: int,
    terminal_key: str,
    terminal: Mapping[str, Any],
) -> bytes:
    result_kind = (
        "RUNTIME-FAILURE"
        if terminal_key == "terminal-failure.json"
        else "ADMISSION-PASS"
        if terminal["admission_passed"] is True
        else "ADMISSION-FAILURE"
    )
    if terminal_key == "acquisition-receipt.json":
        admission = _validated_structural_admission(root_descriptor)
        private_gates = _validated_acquisition_gates(
            terminal["aggregate_gate_results"], terminal["admission_passed"] is True
        )
        failures = cast(list[str], admission["failures"])
        if private_gates != {
            "structural_admission_passed": admission["admission_passed"],
            "failure_count": len(failures),
            "failure_classes": failures,
        }:
            raise Program012AuthorityError("Program 012 acquisition gate result differs")
        aggregate_gate_results = {
            "structural_admission_passed": admission["admission_passed"],
            "failure_count": len(failures),
        }
        public_dataset = _validated_public_dataset_manifest(terminal)
        sessions_with_completed_responses = terminal["session_count"]
        failure_class = None
        failure_classification = None
    else:
        private_gates = _validated_runtime_failure_gates(terminal["aggregate_gate_results"])
        aggregate_gate_results = {
            "structural_admission_passed": private_gates["structural_admission_passed"],
            "structural_admission_evaluated": private_gates["structural_admission_evaluated"],
            "failure_count": private_gates["failure_count"],
        }
        public_dataset = None
        sessions_with_completed_responses = terminal["sessions_with_completed_responses"]
        failure_class = terminal["failure_class"]
        failure_classification = terminal["failure_classification"]
    public: dict[str, Any] = {
        "schema_version": "program-012-exposed-prefix-terminal-result-v1",
        "terminal_result_id": (
            "program-012-exposed-prefix-raw-alpaca-sip-acquisition-and-"
            "structural-admission-terminal-result-2026-08-31-v1"
        ),
        "program_ordinal": PROGRAM_ORDINAL,
        "program_id": PROGRAM_ID,
        "result_kind": result_kind,
        "status": terminal["status"],
        "authority_id": terminal["authority_id"],
        "authority_fingerprint": terminal["authority_fingerprint"],
        "source_commit": terminal["source_commit"],
        "admission_passed": terminal["admission_passed"],
        "session_count": terminal["session_count"],
        "sessions_with_completed_responses": sessions_with_completed_responses,
        "request_count": terminal["request_count"],
        "response_count": terminal["response_count"],
        "response_bytes": terminal["response_bytes"],
        "raw_row_count": terminal["raw_row_count"],
        "expected_canonical_coordinate_count": terminal["expected_canonical_coordinate_count"],
        "missing_coordinate_count": terminal["missing_coordinate_count"],
        "excluded_full_session_count": terminal["excluded_full_session_count"],
        "credential_loads": terminal["credential_loads"],
        "aggregate_gate_results": aggregate_gate_results,
        "failure_class": failure_class,
        "failure_classification": failure_classification,
        "private_evidence_hashes": {
            "response_manifest_sha256": terminal["response_manifest_sha256"],
            "canonical_raw_sha256": terminal["canonical_raw_sha256"],
        },
        "dataset_manifest": public_dataset,
        "public_dataset_manifest_present": public_dataset is not None,
        "credentials_stored": False,
        "provider_tokens_private": True,
        "exact_missing_coordinates_private": True,
        "exact_unexpected_exclusion_dates_private": True,
        "automatic_retries": 0,
        "program_002_admission": False,
        "strategy_calculations": 0,
        "strategy_returns": 0,
        "observed_at": terminal["observed_at"],
    }
    public["terminal_result_fingerprint"] = fingerprint(public)
    return (canonical_json(public) + "\n").encode()


def _publish_public_terminal(
    repository: Path,
    root_descriptor: int,
    terminal_key: str,
    terminal: Mapping[str, Any],
) -> None:
    _append_public_atomic(
        repository,
        root_descriptor,
        PUBLIC_TERMINAL_PATH,
        _public_terminal_payload(root_descriptor, terminal_key, terminal),
    )


def _credential_load_count(
    root_descriptor: int,
    *,
    authority_fingerprint: str | None = None,
    source_commit: str | None = None,
) -> int:
    entries = set(os.listdir(root_descriptor))
    attempts: dict[int, Mapping[str, Any]] = {}
    receipts: dict[int, Mapping[str, Any]] = {}
    for entry in entries:
        match = _CREDENTIAL_KEY.fullmatch(entry)
        if match is None:
            continue
        sequence = int(match.group("sequence"))
        raw = _read(root_descriptor, entry)
        value = _json_object(raw, "credential evidence")
        if raw != (canonical_json(value) + "\n").encode():
            raise Program012AuthorityError("Program 012 credential evidence is not canonical")
        target = attempts if match.group("kind") == "attempt" else receipts
        if sequence in target:
            raise Program012AuthorityError("Program 012 credential evidence is duplicated")
        target[sequence] = value
    if set(receipts) - set(attempts) or set(attempts) != set(range(1, len(attempts) + 1)):
        raise Program012AuthorityError("Program 012 credential evidence sequence differs")
    for sequence, attempt in attempts.items():
        unsigned = {
            "schema_version": "program-012-private-credential-load-attempt-v1",
            "authority_fingerprint": attempt.get("authority_fingerprint"),
            "source_commit": attempt.get("source_commit"),
            "process_recovery_sequence": sequence,
        }
        if attempt != {**unsigned, "attempt_identity": fingerprint(unsigned)}:
            raise Program012AuthorityError("Program 012 credential attempt differs")
        if (
            authority_fingerprint is not None
            and attempt.get("authority_fingerprint") != authority_fingerprint
        ) or (source_commit is not None and attempt.get("source_commit") != source_commit):
            raise Program012AuthorityError("Program 012 credential attempt binding differs")
        receipt = receipts.get(sequence)
        if receipt is not None and receipt != {
            "schema_version": "program-012-private-credential-load-receipt-v1",
            "attempt_identity": attempt["attempt_identity"],
            "status": receipt.get("status"),
        }:
            raise Program012AuthorityError("Program 012 credential receipt differs")
        if receipt is not None and receipt.get("status") not in {"SUCCESS", "FAILURE"}:
            raise Program012AuthorityError("Program 012 credential receipt status differs")
    return len(attempts)


def _next_credential_sequence(root_descriptor: int) -> int:
    return _credential_load_count(root_descriptor) + 1


def _require_working_disk_capacity(root_descriptor: int) -> None:
    filesystem = os.fstatvfs(root_descriptor)
    available = filesystem.f_bavail * filesystem.f_frsize
    if available < program_012.WORKING_DISK_RESERVATION_BYTES:
        raise Program012AuthorityError("Program 012 working disk reservation is unavailable")


def _append_public_atomic(
    repository: Path,
    root_descriptor: int,
    path: Path,
    payload: bytes,
) -> None:
    if path != PUBLIC_TERMINAL_PATH or type(payload) is not bytes:
        raise Program012AuthorityError("Program 012 public artifact path differs")
    public_descriptor = os.open(repository / path.parent, _DIRECTORY_FLAGS)
    try:
        try:
            existing_descriptor = os.open(
                path.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=public_descriptor,
            )
        except FileNotFoundError:
            existing_descriptor = None
        if existing_descriptor is not None:
            with os.fdopen(existing_descriptor, "rb") as handle:
                metadata = os.fstat(handle.fileno())
                existing = handle.read()
            if not stat.S_ISREG(metadata.st_mode) or existing != payload:
                raise Program012AuthorityError("Program 012 public terminal artifact differs")
            return
        temp_key, temp_descriptor = _new_temp(root_descriptor, "public-terminal")
        try:
            with os.fdopen(temp_descriptor, "wb") as handle:
                if handle.write(payload) != len(payload):
                    raise Program012AuthorityError(
                        "Program 012 public terminal write was incomplete"
                    )
                handle.flush()
                os.fchmod(handle.fileno(), 0o644)
                os.fsync(handle.fileno())
            try:
                os.link(
                    temp_key,
                    path.name,
                    src_dir_fd=root_descriptor,
                    dst_dir_fd=public_descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError:
                raise Program012AuthorityError(
                    "Program 012 public terminal artifact already exists"
                ) from None
            os.fsync(public_descriptor)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temp_key, dir_fd=root_descriptor)
                os.fsync(root_descriptor)
    finally:
        os.close(public_descriptor)


def _append(root_descriptor: int, key: str, payload: bytes) -> None:
    _validate_evidence_input(key, payload)
    try:
        descriptor = os.open(
            key,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=root_descriptor,
        )
    except FileExistsError:
        raise Program012AuthorityError(f"Program 012 evidence already exists: {key}") from None
    with os.fdopen(descriptor, "wb") as handle:
        if handle.write(payload) != len(payload):
            raise Program012AuthorityError("Program 012 evidence write was incomplete")
        handle.flush()
        os.fsync(handle.fileno())
    os.fsync(root_descriptor)


def _append_atomic(root_descriptor: int, key: str, payload: bytes) -> None:
    _validate_evidence_input(key, payload)
    temp_key, descriptor = _new_temp(root_descriptor, "intent")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            if handle.write(payload) != len(payload):
                raise Program012AuthorityError("Program 012 atomic evidence write was incomplete")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(
                temp_key,
                key,
                src_dir_fd=root_descriptor,
                dst_dir_fd=root_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError:
            raise Program012AuthorityError(f"Program 012 evidence already exists: {key}") from None
        os.fsync(root_descriptor)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temp_key, dir_fd=root_descriptor)
            os.fsync(root_descriptor)


def _append_or_validate(root_descriptor: int, key: str, payload: bytes) -> None:
    if _exists(root_descriptor, key):
        if _read(root_descriptor, key) != payload:
            raise Program012AuthorityError(f"Program 012 derived evidence differs: {key}")
        return
    _append(root_descriptor, key, payload)


def _new_temp(root_descriptor: int, label: str) -> tuple[str, int]:
    for _ in range(10):
        key = f"tmp-{label}-{secrets.token_hex(12)}"
        try:
            descriptor = os.open(
                key,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=root_descriptor,
            )
        except FileExistsError:
            continue
        return key, descriptor
    raise Program012AuthorityError("Program 012 temporary evidence name collision")


def _publish_temp_or_validate(
    root_descriptor: int, temp_key: str, final_key: str, expected_sha256: str
) -> None:
    if _exists(root_descriptor, final_key):
        if hashlib.sha256(_read(root_descriptor, final_key)).hexdigest() != expected_sha256:
            raise Program012AuthorityError("Program 012 canonical raw dataset differs")
    else:
        try:
            os.link(
                temp_key,
                final_key,
                src_dir_fd=root_descriptor,
                dst_dir_fd=root_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError:
            raise Program012AuthorityError("Program 012 canonical raw publish raced") from None
        os.fsync(root_descriptor)
    os.unlink(temp_key, dir_fd=root_descriptor)
    os.fsync(root_descriptor)


def _read(root_descriptor: int, key: str) -> bytes:
    if _EVIDENCE_KEY.fullmatch(key) is None:
        raise Program012AuthorityError("Program 012 evidence key is invalid")
    try:
        descriptor = os.open(
            key, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=root_descriptor
        )
    except OSError as error:
        raise Program012AuthorityError(f"Program 012 evidence is absent: {key}") from error
    with os.fdopen(descriptor, "rb") as handle:
        metadata = os.fstat(handle.fileno())
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise Program012AuthorityError("Program 012 evidence is not private")
        return handle.read()


def _exists(root_descriptor: int, key: str) -> bool:
    try:
        metadata = os.stat(key, dir_fd=root_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(metadata.st_mode):
        raise Program012AuthorityError("Program 012 evidence path is not a regular file")
    return True


def _open_private_root(repository: Path, *, create: bool) -> int:
    descriptor = os.open(_repository(repository), _DIRECTORY_FLAGS)
    try:
        for part in PRIVATE_ROOT.parts:
            if create:
                with suppress(FileExistsError):
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
            try:
                child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            except FileNotFoundError as error:
                raise Program012AuthorityError(
                    "Program 012 private evidence root is absent"
                ) from error
            os.close(descriptor)
            descriptor = child
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode) or stat.S_IMODE(opened.st_mode) & 0o077:
            raise Program012AuthorityError("Program 012 private evidence root is not private")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _load_active(root_descriptor: int, expected: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = _read(root_descriptor, "active-authority.json")
    value = _json_object(raw, "active authority")
    if value != expected or raw != (canonical_json(expected) + "\n").encode():
        raise Program012AuthorityError("Program 012 active authority differs")
    return value


def _validate_existing_public_terminal(
    repository: Path,
    authority: Mapping[str, Any],
    source_commit: str,
) -> None:
    path = repository / PUBLIC_TERMINAL_PATH
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return
    except OSError as error:
        raise Program012AuthorityError("Program 012 public terminal artifact is invalid") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 1_048_576:
            raise Program012AuthorityError("Program 012 public terminal artifact is invalid")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            actual = handle.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    root_descriptor = _open_private_root(repository, create=False)
    try:
        terminal_key, terminal = _load_terminal_record(root_descriptor, authority, source_commit)
        expected = _public_terminal_payload(root_descriptor, terminal_key, terminal)
    finally:
        os.close(root_descriptor)
    if actual != expected:
        raise Program012AuthorityError("Program 012 public terminal artifact differs")


def _repository_preflight(repository: Path, identity: Mapping[str, Any]) -> Mapping[str, str]:
    runtime = _mapping(identity.get("runtime_binding"), "runtime binding")
    source_commit = str(runtime.get("source_commit"))
    _sequence(runtime.get("source_files"), "runtime source files")
    expected_changes = {
        f"A\t{CHILD_AUTHORITY_PATH.as_posix()}",
        f"A\t{CHILD_REVIEW_PATH.as_posix()}",
    }
    environment = _git_environment()
    command = predecessor._git_command(repository)

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
        dirty = git("status", "--porcelain", "--untracked-files=all").stdout.splitlines()
        source_tree = git("rev-parse", f"{source_commit}^{{tree}}").stdout.strip()
        changed = git("diff", "--name-status", source_commit, head).stdout.splitlines()
        ancestor = git("merge-base", "--is-ancestor", source_commit, head, check=False)
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        raise Program012AuthorityError("Program 012 repository identity is unavailable") from error
    if (
        dirty not in ([], [f"?? {PUBLIC_TERMINAL_PATH.as_posix()}"])
        or head != main
        or head != origin_main
        or source_tree != runtime.get("source_tree")
        or ancestor.returncode != 0
        or set(changed) != expected_changes
    ):
        raise Program012AuthorityError("Program 012 reviewed synchronized-main lineage differs")
    return {
        "runtime_source_commit": source_commit,
        "runtime_source_tree": source_tree,
        "synchronized_main_commit": head,
    }


def _load_bound(
    repository: Path,
    binding: Mapping[str, Any],
    fingerprint_field: str,
    *,
    commit: str | None = None,
) -> Mapping[str, Any]:
    try:
        return predecessor._load_bound_artifact(
            repository, binding, fingerprint_field, commit=commit
        )
    except predecessor.Program011AuthorityError as error:
        raise Program012AuthorityError(str(error).replace("Program 011", "Program 012")) from None


def _authority_commit(authority: Mapping[str, Any]) -> str:
    value = str(
        _mapping(authority.get("control_lineage"), "control lineage").get(
            "synchronized_main_commit"
        )
    )
    if _HEX_40.fullmatch(value) is None:
        raise Program012AuthorityError("Program 012 authority policy commit differs")
    return value


def _source_commit(authority: Mapping[str, Any]) -> str:
    value = str(
        _mapping(authority.get("control_lineage"), "control lineage").get("runtime_source_commit")
    )
    if _HEX_40.fullmatch(value) is None:
        raise Program012AuthorityError("Program 012 runtime source commit differs")
    return value


def _require_credentials_present(environ: Mapping[str, str] | None) -> None:
    missing = credential_contract.credential_presence_preflight(environ)
    if missing:
        raise Program012AuthorityError("Program 012 credentials missing: " + ", ".join(missing))


def _page_prefix(request: program_011.SessionRequest, page_index: int) -> str:
    return f"session-{request.session.isoformat()}-{page_index:02d}"


def _expected_session_entries(request: program_011.SessionRequest, page_count: int) -> set[str]:
    return {
        f"{_page_prefix(request, page_index)}.{suffix}"
        for page_index in range(1, page_count + 1)
        for suffix in ("intent.json", "body", "receipt.json")
    }


def _has_consumed_state(root_descriptor: int) -> bool:
    return _exists(root_descriptor, "claim.json") or any(
        entry.endswith(".intent.json") for entry in os.listdir(root_descriptor)
    )


def _validate_evidence_input(key: str, payload: bytes) -> None:
    if type(key) is not str or _EVIDENCE_KEY.fullmatch(key) is None or type(payload) is not bytes:
        raise Program012AuthorityError("Program 012 evidence entry is invalid")


def _repository(repository: Path) -> Path:
    if not isinstance(repository, Path):
        raise Program012AuthorityError("Program 012 repository root is invalid")
    resolved = repository.resolve()
    if not resolved.is_dir():
        raise Program012AuthorityError("Program 012 repository root is absent")
    return resolved


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Program012AuthorityError(f"Program 012 {label} is invalid JSON") from error
    if type(value) is not dict:
        raise Program012AuthorityError(f"Program 012 {label} is not an object")
    return value


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Program012AuthorityError(f"Program 012 {label} is invalid")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise Program012AuthorityError(f"Program 012 {label} is invalid")
    return value


def _git(repository: Path, *arguments: str) -> str:
    try:
        return subprocess.run(
            (*predecessor._git_command(repository), *arguments),
            check=True,
            capture_output=True,
            text=True,
            env=_git_environment(),
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise Program012AuthorityError("Program 012 Git identity is unavailable") from error


def _git_environment() -> dict[str, str]:
    environment = non_broker_subprocess_environment()
    environment.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    return environment


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise Program012AuthorityError("Program 012 timestamp must be UTC")
    return value.isoformat().replace("+00:00", "Z")


def _format_observed_at(value: datetime) -> str:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise Program012AuthorityError("Program 012 response timestamp must be UTC")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_observed_at(value: Any) -> datetime:
    if type(value) is not str:
        raise Program012AuthorityError("Program 012 response timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise Program012AuthorityError("Program 012 response timestamp is invalid") from error
    if _format_observed_at(parsed) != value:
        raise Program012AuthorityError("Program 012 response timestamp is not canonical")
    return parsed


def _utc_now() -> str:
    return _format_observed_at(datetime.now(UTC))
