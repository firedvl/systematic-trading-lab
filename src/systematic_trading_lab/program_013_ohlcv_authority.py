"""Restart-safe Program 013 recovery of the Program 012 exposed prefix."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, BinaryIO, cast

from . import program_006_alpaca as credential_contract
from . import program_007_alpaca as raw_contract
from . import program_011_ohlcv as program_011
from . import program_011_ohlcv_authority as git_controls
from . import program_012_ohlcv as science
from . import program_012_ohlcv_authority as predecessor
from .config import non_broker_subprocess_environment
from .fingerprints import canonical_json, fingerprint
from .standing_research_authority import derive_child_identity

PROGRAM_ID = "multi-hour-sector-etf-research-012"
PROGRAM_ORDINAL = 13
CHILD_AUTHORITY_ID = (
    "program-013-exposed-prefix-raw-alpaca-sip-recovery-and-"
    "structural-admission-child-2026-09-03-v1"
)
CONSUMPTION_BOUNDARY = "immediately before first provider transport invocation"
PRIVATE_ROOT = Path(".trading-lab/program-013-exposed-prefix-raw-alpaca-sip-v1")
PREDECESSOR_PRIVATE_ROOT = predecessor.PRIVATE_ROOT
PUBLIC_TERMINAL_PATH = Path(
    "config/research/program-013-exposed-prefix-raw-alpaca-sip-recovery-and-"
    "structural-admission-terminal-result-v1.json"
)
CHILD_AUTHORITY_PATH = Path(
    "config/research/program-013-exposed-prefix-raw-alpaca-sip-recovery-and-"
    "structural-admission-child-authority-v1.json"
)
CHILD_REVIEW_PATH = Path(
    "config/research/program-013-exposed-prefix-raw-alpaca-sip-recovery-and-"
    "structural-admission-child-authority-independent-review-v1.json"
)
OPERATION_MANIFEST = {
    "path": (
        "config/research/program-013-exposed-prefix-raw-alpaca-sip-recovery-and-"
        "structural-admission-proposal-v5.json"
    ),
    "sha256": "bcfae8da387daf0012afc3fd2636e2d81fa1a5f7e11a0f82a826bd021484f269",
    "fingerprint": "8beea434b1dd2e129eaa32154a9cdfeb515611d5a96a1e4826fb0dfcaddd61bf",
}
PROPOSAL_REVIEW = {
    "path": (
        "config/research/program-013-exposed-prefix-raw-alpaca-sip-recovery-and-"
        "structural-admission-independent-review-v5.json"
    ),
    "sha256": "45171e25fed0042be425457b4288efc1d698fbcf3f2a643703454ad592c0c780",
    "fingerprint": "d2cd4ff809e616dab50538ec4cdbf9c6f38d29e719b6b58cdad86c7dd13ff1af",
}
CREDENTIAL_NAMES = credential_contract._CREDENTIAL_NAMES
MockBarsTransport = predecessor.MockBarsTransport
_ACTION_LEDGER_MANIFEST = predecessor._ACTION_LEDGER_MANIFEST

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
_HEX_40 = re.compile(r"[0-9a-f]{40}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_EVIDENCE_KEY = re.compile(r"[a-z0-9][a-z0-9.-]*")
_PAGE_KEY = re.compile(
    r"session-(?P<session>[0-9]{4}-[0-9]{2}-[0-9]{2})-"
    r"(?P<page>[0-9]{2})\.(?P<kind>intent\.json|body|receipt\.json)"
)
_CREDENTIAL_KEY = re.compile(
    r"credential-load-(?P<sequence>[0-9]{6})\.(?P<kind>attempt|receipt)\.json"
)
_DERIVED_KEYS = {
    "combined-canonical-raw.jsonl",
    "combined-dataset-manifest.json",
    "combined-missing-coordinates.json",
    "combined-structural-admission.json",
    "program-013-response-manifest.json",
}
_TERMINAL_KEY = "terminal.json"
_PUBLIC_TERMINAL_RESULT_ID = (
    "program-013-exposed-prefix-raw-alpaca-sip-recovery-and-"
    "structural-admission-terminal-result-2026-09-03-v1"
)
_PUBLIC_TERMINAL_SHA256 = "7e4d148b7a20122cdb5fde21f6f8d70493cfd5772a527aa42a3c127c067f56ee"
_PRIVATE_TERMINAL_KEYS = {
    "schema_version",
    "program_id",
    "authority_id",
    "authority_fingerprint",
    "source_commit",
    "source_tree",
    "runtime_implementation_root",
    "operation_manifest",
    "predecessor_import_manifest_sha256",
    "public_terminal_path",
    "result_kind",
    "status",
    "provider_transport_attempted",
    "scientific_use_consumed",
    "failure_class",
    "failure_classification",
    "program_013_credential_loads",
    "cumulative_request_intents",
    "cumulative_responses",
    "cumulative_response_bytes",
    "structural_admission_evaluated",
    "admission_passed",
    "private_evidence",
    "public_dataset_lineage_manifest",
    "dataset_lineage_identity",
    "private_dataset_identity",
    "automatic_retries",
    "credentials_stored",
    "program_002_admission",
    "strategy_calculations",
    "strategy_returns",
    "observed_at",
    "terminal_fingerprint",
}
_PRIVATE_EVIDENCE_KEYS = {
    "program_013_response_manifest_sha256",
    "combined_canonical_raw_sha256",
    "combined_missingness_sha256",
    "combined_structural_admission_sha256",
    "combined_dataset_manifest_sha256",
    "raw_row_count",
    "missing_coordinate_count",
    "excluded_full_session_count",
}
_RUNTIME_BINDING_KEYS = {"source_commit", "source_tree", "implementation_root"}
_CLAIM_KEYS = {
    "schema_version",
    "program_id",
    "authority_id",
    "authority_fingerprint",
    "operation_manifest",
    "runtime_binding",
    "predecessor_import_manifest_sha256",
    "consumption_boundary",
    "scientific_use_consumed",
    "terminal_fallback",
    "claim_fingerprint",
}
_INTENT_KEYS = {
    "schema_version",
    "program_id",
    "authority_fingerprint",
    "operation_manifest",
    "runtime_binding",
    "predecessor_import_manifest_sha256",
    "expected_claim_fingerprint",
    "method",
    "session",
    "page_index",
    "request_identity",
    "incoming_page_token",
    "url",
    "intent_fingerprint",
}
_RECEIPT_KEYS = {
    "schema_version",
    "program_id",
    "authority_fingerprint",
    "operation_manifest",
    "runtime_binding",
    "predecessor_import_manifest_sha256",
    "claim_fingerprint",
    "intent_fingerprint",
    "intent_sha256",
    "session",
    "page_index",
    "request_identity",
    "status",
    "retained_response_bytes",
    "response_sha256",
    "observed_at",
    "receipt_fingerprint",
}
_CREDENTIAL_ATTEMPT_KEYS = {
    "schema_version",
    "authority_fingerprint",
    "runtime_binding",
    "predecessor_import_manifest_sha256",
    "process_recovery_sequence",
    "attempt_identity",
}
_CREDENTIAL_RECEIPT_KEYS = {"schema_version", "attempt_identity", "status"}
_RESPONSE_MANIFEST_KEYS = {
    "schema_version",
    "program_id",
    "authority_id",
    "authority_fingerprint",
    "runtime_binding",
    "predecessor_import_manifest_sha256",
    "request_count",
    "response_count",
    "response_bytes",
    "pages",
    "credentials_stored",
}
_COMBINED_MISSINGNESS_KEYS = {
    "schema_version",
    "program_id",
    "predecessor_import_manifest_sha256",
    "sessions",
}
_COMBINED_DATASET_KEYS = {
    "schema_version",
    "program_id",
    "authority_id",
    "authority_fingerprint",
    "source_commit",
    "predecessor_import_manifest_sha256",
    "status",
    "private_dataset_identity",
    "program_013_response_manifest_sha256",
    "combined_canonical_raw_sha256",
    "combined_missingness_sha256",
    "combined_structural_admission_sha256",
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
_PUBLIC_TERMINAL_KEYS = {
    "schema_version",
    "terminal_result_id",
    "program_ordinal",
    "program_id",
    "result_kind",
    "status",
    "authority_id",
    "authority_fingerprint",
    "source_commit",
    "admission_passed",
    "dataset_lineage_manifest",
    "privacy_assertions",
    "scientific_assertions",
    "disabled_authority",
    "observed_at",
}
_PUBLIC_LINEAGE_KEYS = {
    "schema_version",
    "program_id",
    "authority_id",
    "authority_fingerprint",
    "source_commit",
    "status",
    "dataset_lineage_identity",
}
_PRIVACY_ASSERTIONS = {
    "credentials_stored": False,
    "provider_tokens_private": True,
    "market_data_private": True,
    "dynamic_acquisition_counts_private": True,
    "data_derived_hashes_and_identities_private": True,
    "detailed_gate_and_failure_evidence_private": True,
    "private_dataset_content_identity_private": True,
    "exact_missing_coordinates_private": True,
    "exact_unexpected_exclusion_dates_private": True,
}
_SCIENTIFIC_ASSERTIONS = {
    "program_002_admission": False,
    "strategy_calculations_present": False,
    "strategy_returns_present": False,
}
_DISABLED_AUTHORITY = {
    "subscription_purchase": False,
    "strategy_implementation": False,
    "strategy_execution": False,
    "research_qualification": False,
    "controlled_evaluation": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}
_PROCESS_CREDENTIAL_LOCK = threading.Lock()
_PROCESS_CREDENTIAL_PID: int | None = None


class Program013AuthorityError(ValueError):
    """Fail-closed Program 013 runtime or authority error."""


class Program013PostClaimPersistenceError(Program013AuthorityError):
    """Terminal evidence could not be persisted after possible transport."""


class CombinedRequestBudgetExhausted(Program013AuthorityError):
    """The inherited cumulative intent ceiling cannot admit another page."""

    classification = "FAIL-CONSUMED-NO-RETRY-COMBINED-REQUEST-BUDGET-EXHAUSTED"


class _TransportRequired(Exception):
    pass


class _IncompletePageCheckpoint(Program013AuthorityError):
    pass


@dataclass(frozen=True)
class AcquisitionExecution:
    public_terminal: Mapping[str, object]

    def public_summary(self) -> dict[str, object]:
        return dict(self.public_terminal)

    def public_payload(self) -> bytes:
        return (canonical_json(self.public_terminal) + "\n").encode()


@dataclass(frozen=True)
class _PredecessorState:
    manifest: Mapping[str, Any]
    payload: bytes
    sha256: str
    active_authority: Mapping[str, Any]
    source_commit: str
    frontier_request_index: int
    latest_response_at: datetime | None


@dataclass(frozen=True)
class _CombinedProjection:
    canonical_sha256: str
    raw_row_count: int
    missing: Mapping[date, set[str]]
    morning: Mapping[date, Mapping[str, tuple[Any, Any, Any]]]
    program_013_response_manifest: Mapping[str, Any]
    budget: _Budget


class _Budget:
    def __init__(self, predecessor_state: _PredecessorState) -> None:
        completed_requests = _count(
            predecessor_state.manifest.get("completed_request_count"),
            "predecessor completed request count",
        )
        completed_responses = _count(
            predecessor_state.manifest.get("completed_response_count"),
            "predecessor completed response count",
        )
        completed_bytes = _count(
            predecessor_state.manifest.get("completed_response_bytes"),
            "predecessor completed response byte count",
        )
        if completed_requests != completed_responses:
            raise Program013AuthorityError("Program 013 predecessor budget differs")
        self.inherited_requests = completed_requests + 1
        self.inherited_responses = completed_responses
        self.inherited_response_bytes = completed_bytes
        self.requests = self.inherited_requests
        self.responses = self.inherited_responses
        self.response_bytes = self.inherited_response_bytes
        self.session_bytes: dict[date, int] = {}
        self.pages: list[dict[str, object]] = []
        self.latest_response_at = predecessor_state.latest_response_at
        if (
            self.requests > science.MAXIMUM_REQUESTS_AND_RESPONSES
            or self.responses > science.MAXIMUM_REQUESTS_AND_RESPONSES - 1
            or self.response_bytes > science.MAXIMUM_TOTAL_RESPONSE_BYTES
        ):
            raise Program013AuthorityError("Program 013 inherited budget exceeds its ceiling")

    @property
    def new_requests(self) -> int:
        return self.requests - self.inherited_requests

    @property
    def new_responses(self) -> int:
        return self.responses - self.inherited_responses

    @property
    def new_response_bytes(self) -> int:
        return self.response_bytes - self.inherited_response_bytes

    def reserve_request(self) -> None:
        if self.requests >= science.MAXIMUM_REQUESTS_AND_RESPONSES:
            raise CombinedRequestBudgetExhausted(
                "Program 013 combined request ceiling is exhausted"
            )
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
            raise Program013AuthorityError("Program 013 response timestamp must be UTC")
        if self.responses >= science.MAXIMUM_REQUESTS_AND_RESPONSES - 1:
            raise CombinedRequestBudgetExhausted(
                "Program 013 combined response ceiling is exhausted"
            )
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
        if len(body) > science.MAXIMUM_RESPONSE_PAGE_BYTES:
            raise Program013AuthorityError("Program 013 response exceeds the 8 MiB page ceiling")
        if self.session_bytes[request.session] > science.MAXIMUM_SESSION_RESPONSE_BYTES:
            raise Program013AuthorityError("Program 013 session exceeds the 8 MiB byte ceiling")
        if self.response_bytes > science.MAXIMUM_TOTAL_RESPONSE_BYTES:
            raise Program013AuthorityError("Program 013 total response byte ceiling exceeded")


class _ReadLockedRoot:
    def __init__(self, root_descriptor: int) -> None:
        self._root_descriptor = root_descriptor
        self._handle: BinaryIO | None = None

    def __enter__(self) -> None:
        try:
            descriptor = os.open(
                "run.lock",
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=self._root_descriptor,
            )
        except FileNotFoundError as error:
            raise Program013AuthorityError("Program 012 read-only lock is absent") from error
        self._handle = os.fdopen(descriptor, "rb", buffering=0)
        metadata = os.fstat(self._handle.fileno())
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
            self._handle.close()
            raise Program013AuthorityError("Program 012 read-only lock is invalid")
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_SH)

    def __exit__(self, *_args: object) -> None:
        assert self._handle is not None
        self._handle.close()


def credential_presence_preflight(
    repository: Path, environ: Mapping[str, str] | None = None
) -> tuple[str, ...]:
    """Validate the successor and predecessor before checking credential names."""
    repository = _repository(repository)
    authority = _derive_control_validated_authority(repository)
    with _locked_controls(repository, authority, create_program_013=True) as (
        program_013_root,
        predecessor_root,
    ):
        locked = _derive_control_validated_authority(repository)
        if locked != authority:
            raise Program013AuthorityError("Program 013 authority changed under policy lock")
        predecessor_state = _derive_predecessor_state(repository, predecessor_root, authority)
        _recover_private_terminal_if_present(
            repository,
            program_013_root,
            predecessor_root,
            authority,
            predecessor_state,
        )
        return credential_contract.credential_presence_preflight(environ)


def read_credentials(environ: Mapping[str, str] | None = None) -> tuple[str, str]:
    values = os.environ if environ is None else environ
    credentials = tuple(values.get(name, "").strip() for name in CREDENTIAL_NAMES)
    if any(not value or "\r" in value or "\n" in value for value in credentials):
        raise Program013AuthorityError("Program 013 OHLCV credentials are required")
    return credentials[0], credentials[1]


def validate_operation_contract(
    repository: Path, *, commit: str | None = None
) -> Mapping[str, Any]:
    """Validate the exact reviewed recovery contract and inherited science."""
    repository = _repository(repository)
    proposal = _load_bound(repository, OPERATION_MANIFEST, "proposal_fingerprint", commit=commit)
    review = _load_bound(repository, PROPOSAL_REVIEW, "review_fingerprint", commit=commit)
    try:
        predecessor.validate_operation_contract(repository, commit=commit)
    except predecessor.Program012AuthorityError as error:
        raise Program013AuthorityError(str(error).replace("Program 012", "Program 013")) from None
    source = _mapping(proposal.get("source_contract"), "source contract")
    chronology = _mapping(proposal.get("chronology"), "chronology")
    recovery = _mapping(proposal.get("recovery_contract"), "recovery contract")
    restart = _mapping(proposal.get("restart_contract"), "restart contract")
    topology = _mapping(proposal.get("runtime_and_child_topology_contract"), "runtime topology")
    budgets = _mapping(
        proposal.get("cumulative_transport_and_working_space_budgets"), "cumulative budgets"
    )
    terminal = _mapping(proposal.get("public_terminal_contract"), "public terminal contract")
    child = _mapping(proposal.get("future_child_authority"), "future child authority")
    authority = _mapping(proposal.get("authority"), "proposal authority")
    firewall = _mapping(proposal.get("protected_firewall"), "protected firewall")
    if (
        proposal.get("program_ordinal") != PROGRAM_ORDINAL
        or proposal.get("program_id") != PROGRAM_ID
        or proposal.get("status") != "PROPOSED-PROSPECTIVE-NOT-AUTHORIZED"
        or proposal.get("proposal_fingerprint") != OPERATION_MANIFEST["fingerprint"]
        or review.get("status") != "PASS-FINDING-FREE-PROSPECTIVE-DESIGN-AND-SECURITY-REVIEW"
        or review.get("verdict") != "PASS"
        or review.get("findings") != []
        or review.get("reviewed_source_commit") != "93aeaaa73d700897a5629ecf0fa6c110ce80449f"
        or review.get("reviewed_proposal") != OPERATION_MANIFEST
        or source.get("method") != "GET"
        or source.get("endpoint") != program_011.ENDPOINT
        or source.get("feed") != "sip"
        or source.get("timeframe") != "5Min"
        or source.get("adjustment") != "raw"
        or source.get("sort") != "asc"
        or source.get("limit") != program_011.PAGE_ROW_LIMIT
        or source.get("automatic_retries") != 0
        or source.get("symbols") != list(science.SYMBOLS)
        or chronology.get("context_start") != science.CONTEXT_START.isoformat()
        or chronology.get("exposed_end") != science.EXPOSED_END.isoformat()
        or chronology.get("session_count") != science.EXPECTED_SESSION_COUNT
        or chronology.get("expected_coordinate_count") != science.EXPECTED_COORDINATE_COUNT
        or recovery.get("program_012_private_root") != PREDECESSOR_PRIVATE_ROOT.as_posix()
        or recovery.get("program_013_private_root") != PRIVATE_ROOT.as_posix()
        or recovery.get("frontier_page_index") != 1
        or recovery.get("first_program_013_intent_must_equal_rederived_frontier_identity")
        is not True
        or restart.get("program_013_lock_path") != f"{PRIVATE_ROOT.as_posix()}/run.lock"
        or restart.get("program_012_lock_path") != f"{PREDECESSOR_PRIVATE_ROOT.as_posix()}/run.lock"
        or restart.get("control_acquisition_order")
        != [
            "Program 013 exclusive lock",
            "Program 012 read-only shared lock",
            "Git policy snapshot bound to the exact post-child-and-review synchronized main commit",
        ]
        or topology.get("only_allowed_paths_between_runtime_source_and_synchronized_main")
        != [CHILD_AUTHORITY_PATH.as_posix(), CHILD_REVIEW_PATH.as_posix()]
        or topology.get("git_policy_snapshot_binds_synchronized_main_not_runtime_source")
        is not True
        or budgets.get("maximum_combined_request_intents") != science.MAXIMUM_REQUESTS_AND_RESPONSES
        or budgets.get("maximum_effective_combined_responses")
        != science.MAXIMUM_REQUESTS_AND_RESPONSES - 1
        or budgets.get("maximum_combined_response_bytes") != science.MAXIMUM_TOTAL_RESPONSE_BYTES
        or budgets.get("working_disk_reservation_bytes") != science.WORKING_DISK_RESERVATION_BYTES
        or budgets.get("maximum_requests_per_minute") != science.MAXIMUM_REQUESTS_PER_MINUTE
        or budgets.get("automatic_retries") != 0
        or terminal.get("path") != PUBLIC_TERMINAL_PATH.as_posix()
        or terminal.get("schema_version") != "program-013-exposed-prefix-terminal-result-v1"
        or _typed_string_set(
            child.get("maximum_enabled_capabilities"), "maximum enabled capabilities"
        )
        != _ENABLED_AUTHORITY
        or child.get("source_qualification_allowed") is not False
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
    ):
        raise Program013AuthorityError("Program 013 operation contract differs")
    return proposal


def derive_active_authority(repository: Path) -> Mapping[str, Any]:
    """Derive the reviewed child without reading either private evidence root."""
    return _derive_control_validated_authority(repository)


def _derive_control_validated_authority(repository: Path) -> Mapping[str, Any]:
    repository = _repository(repository)
    _reject_terminal_state(repository)
    try:
        identity = derive_child_identity(repository, CHILD_AUTHORITY_PATH, CHILD_REVIEW_PATH)
    except ValueError as error:
        raise Program013AuthorityError(str(error)) from None
    authority = _mapping(identity.get("authority"), "child authority")
    runtime = _mapping(identity.get("runtime_binding"), "child runtime binding")
    source_paths = {
        str(_mapping(item, "child runtime source file").get("path"))
        for item in _sequence(runtime.get("source_files"), "child runtime source files")
    }
    required_paths = {
        git_controls.PROTECTED_CHRONOLOGY_PATH.as_posix(),
        *(path.as_posix() for path in git_controls.PROTECTED_CHRONOLOGY_SOURCE_PATHS),
        *(path.as_posix() for path in git_controls.PROTECTED_CHRONOLOGY_REGISTRATION_PATHS),
        str(OPERATION_MANIFEST["path"]),
        str(PROPOSAL_REVIEW["path"]),
        predecessor.PUBLIC_TERMINAL_PATH.as_posix(),
        "src/systematic_trading_lab/program_013_ohlcv_authority.py",
    }
    if (
        identity.get("child_authority_id") != CHILD_AUTHORITY_ID
        or identity.get("program_ordinal") != PROGRAM_ORDINAL
        or identity.get("program_id") != PROGRAM_ID
        or identity.get("operation_manifest") != OPERATION_MANIFEST
        or identity.get("runtime_entrypoint")
        != "src/systematic_trading_lab/program_013_ohlcv_authority.py"
        or not required_paths <= source_paths
        or {key for key, value in authority.items() if value} != _ENABLED_AUTHORITY
    ):
        raise Program013AuthorityError("Program 013 reviewed child identity differs")
    lineage = _repository_preflight(repository, identity)
    commit = lineage["synchronized_main_commit"]
    try:
        git_controls._validate_protected_registration_set(repository, commit)
    except git_controls.Program011AuthorityError as error:
        raise Program013AuthorityError(str(error).replace("Program 011", "Program 013")) from None
    validate_operation_contract(repository, commit=commit)
    _require_zero_protected_overlap(repository, commit)
    if _repository_preflight(repository, identity) != lineage:
        raise Program013AuthorityError("Program 013 repository changed during validation")
    unsigned: dict[str, Any] = {
        "schema_version": "program-013-raw-sip-recovery-active-authority-v1",
        "status": "ACTIVE-ONE-USE-RECOVERABLE",
        "authority_id": CHILD_AUTHORITY_ID,
        "program_id": PROGRAM_ID,
        "activation_mode": "INTERNAL-STANDING-MANDATE-DERIVATION",
        "external_authorization_root_required": False,
        "child_identity_fingerprint": identity["child_identity_fingerprint"],
        "operation_manifest": OPERATION_MANIFEST,
        "consumption_boundary": CONSUMPTION_BOUNDARY,
        "authority": authority,
        "runtime_binding": {
            "source_commit": runtime["source_commit"],
            "source_tree": runtime["source_tree"],
            "implementation_root": runtime["implementation_root"],
        },
        "control_lineage": lineage,
    }
    return {**unsigned, "authority_fingerprint": fingerprint(unsigned)}


@contextmanager
def _locked_controls(
    repository: Path,
    authority: Mapping[str, Any],
    *,
    create_program_013: bool,
) -> Iterator[tuple[int, int]]:
    program_013_root = _open_root(repository, PRIVATE_ROOT, create=create_program_013)
    try:
        with git_controls._LockedRoot(program_013_root):
            program_012_root = _open_root(repository, PREDECESSOR_PRIVATE_ROOT, create=False)
            try:
                with (
                    _ReadLockedRoot(program_012_root),
                    git_controls._GitPolicySnapshot(repository, _authority_commit(authority)),
                ):
                    yield program_013_root, program_012_root
            finally:
                os.close(program_012_root)
    except git_controls.Program011AuthorityError as error:
        raise Program013AuthorityError(str(error).replace("Program 011", "Program 013")) from None
    finally:
        os.close(program_013_root)


def activate_authority(
    repository: Path, *, environ: Mapping[str, str] | None = None
) -> Mapping[str, Any]:
    repository = _repository(repository)
    authority = _derive_control_validated_authority(repository)
    with _locked_controls(repository, authority, create_program_013=True) as (
        program_013_root,
        program_012_root,
    ):
        locked = _derive_control_validated_authority(repository)
        if locked != authority:
            raise Program013AuthorityError("Program 013 authority changed under policy lock")
        predecessor_state = _derive_predecessor_state(repository, program_012_root, authority)
        _recover_private_terminal_if_present(
            repository,
            program_013_root,
            program_012_root,
            authority,
            predecessor_state,
        )
        _require_credentials_present(environ)
        entries = set(os.listdir(program_013_root))
        if entries not in (
            {"run.lock"},
            {"run.lock", "predecessor-import-manifest.json"},
        ):
            raise Program013AuthorityError("Program 013 one-use authority state already exists")
        _append_atomic_or_validate(
            program_013_root,
            "predecessor-import-manifest.json",
            predecessor_state.payload,
        )
        predecessor._append_atomic(
            program_013_root,
            "active-authority.json",
            (canonical_json(authority) + "\n").encode(),
        )
    return authority


def load_active_authority(repository: Path) -> Mapping[str, Any]:
    repository = _repository(repository)
    expected = _derive_control_validated_authority(repository)
    with _locked_controls(repository, expected, create_program_013=False) as (
        program_013_root,
        program_012_root,
    ):
        predecessor_state = _derive_predecessor_state(repository, program_012_root, expected)
        _validate_predecessor_manifest(program_013_root, predecessor_state)
        _recover_private_terminal_if_present(
            repository,
            program_013_root,
            program_012_root,
            expected,
            predecessor_state,
        )
        return _load_active(program_013_root, expected)


def execute_acquisition(
    repository: Path, *, environ: Mapping[str, str] | None = None
) -> AcquisitionExecution:
    """Resume or consume the reviewed recovery child and admit the combined prefix."""
    return _execute_acquisition(
        repository,
        environ=environ,
        mock_transport=None,
        after_intent=None,
        after_credential_access=None,
        after_body=None,
        after_page=None,
    )


def _execute_mock_acquisition(
    repository: Path,
    *,
    environ: Mapping[str, str],
    transport: MockBarsTransport,
    after_intent: Callable[[], None] | None = None,
    after_credential_access: Callable[[], None] | None = None,
    after_body: Callable[[], None] | None = None,
    after_page: Callable[[], None] | None = None,
) -> AcquisitionExecution:
    if type(transport) is not MockBarsTransport or environ is os.environ:
        raise Program013AuthorityError("Program 013 test execution requires finite inputs")
    return _execute_acquisition(
        repository,
        environ=environ,
        mock_transport=transport,
        after_intent=after_intent,
        after_credential_access=after_credential_access,
        after_body=after_body,
        after_page=after_page,
    )


def _execute_acquisition(
    repository: Path,
    *,
    environ: Mapping[str, str] | None,
    mock_transport: MockBarsTransport | None,
    after_intent: Callable[[], None] | None,
    after_credential_access: Callable[[], None] | None,
    after_body: Callable[[], None] | None,
    after_page: Callable[[], None] | None,
) -> AcquisitionExecution:
    repository = _repository(repository)
    expected_authority = _derive_control_validated_authority(repository)
    with _locked_controls(repository, expected_authority, create_program_013=False) as (
        program_013_root,
        program_012_root,
    ):
        predecessor_state = _derive_predecessor_state(
            repository, program_012_root, expected_authority
        )
        _validate_predecessor_manifest(program_013_root, predecessor_state)
        _recover_private_terminal_if_present(
            repository,
            program_013_root,
            program_012_root,
            expected_authority,
            predecessor_state,
        )
        try:
            authority = _derive_control_validated_authority(repository)
            if authority != expected_authority:
                raise Program013AuthorityError("Program 013 authority changed under lock")
            _load_active(program_013_root, authority)
            budget = _reconstruct_state(
                program_013_root,
                predecessor_state,
                authority=authority,
            )
            _require_working_disk_capacity(program_013_root)
            loader = _CredentialLoader(
                program_013_root,
                authority,
                predecessor_state,
                environ,
                mock_transport,
                after_credential_access,
                budget.latest_response_at,
            )

            def consume() -> None:
                _revalidate_transport_boundary(
                    repository,
                    program_013_root,
                    program_012_root,
                    authority,
                    predecessor_state,
                )
                if predecessor._exists(program_013_root, "claim.json"):
                    _validate_claim(program_013_root, authority, predecessor_state)
                    return
                predecessor._append_atomic(
                    program_013_root,
                    "claim.json",
                    _claim_payload(authority, predecessor_state),
                )

            temp_key, temp_descriptor = predecessor._new_temp(
                program_013_root, "combined-canonical-raw"
            )
            completed = False
            try:
                with os.fdopen(temp_descriptor, "wb") as canonical_file:
                    projection = _combined_projection(
                        program_013_root,
                        program_012_root,
                        predecessor_state,
                        authority,
                        budget,
                        canonical_file=canonical_file,
                        loader=loader,
                        consume=consume,
                        after_intent=after_intent,
                        after_body=after_body,
                        after_page=after_page,
                    )
                    canonical_file.flush()
                    os.fsync(canonical_file.fileno())
                completed = True
            finally:
                if not completed:
                    with suppress(FileNotFoundError):
                        os.unlink(temp_key, dir_fd=program_013_root)
                        os.fsync(program_013_root)
            _publish_temp_or_validate(
                program_013_root,
                temp_key,
                "combined-canonical-raw.jsonl",
                projection.canonical_sha256,
            )
            if budget.new_requests != budget.new_responses:
                raise Program013AuthorityError("Program 013 new request and response counts differ")
            evidence = _derived_admission_evidence(
                repository, authority, predecessor_state, projection
            )
            for key, payload in cast(Mapping[str, bytes], evidence["payloads"]).items():
                predecessor._append_or_validate(program_013_root, key, payload)
            if mock_transport is not None:
                mock_transport.require_exhausted()
            terminal_payload = _admission_terminal_payload(
                program_013_root,
                authority,
                predecessor_state,
                projection,
                evidence,
                predecessor._utc_now(),
            )
            _revalidate_closeout_boundary(
                repository,
                program_012_root,
                authority,
                predecessor_state,
            )
            predecessor._append_atomic(program_013_root, _TERMINAL_KEY, terminal_payload)
            terminal = _load_terminal_record(
                repository,
                program_013_root,
                program_012_root,
                authority,
                predecessor_state,
            )
            try:
                public_terminal = _publish_public_terminal(
                    repository,
                    program_013_root,
                    program_012_root,
                    authority,
                    predecessor_state,
                    terminal,
                )
            except BaseException as persistence_error:
                raise Program013PostClaimPersistenceError(
                    "Program 013 public terminal persistence failed after possible transport"
                ) from persistence_error
            return AcquisitionExecution(public_terminal)
        except BaseException as error:
            published_failure = False
            if (
                isinstance(error, CombinedRequestBudgetExhausted)
                or _has_consumed_state(program_013_root)
            ) and not predecessor._exists(program_013_root, _TERMINAL_KEY):
                try:
                    _seal_runtime_failure(
                        repository,
                        program_013_root,
                        program_012_root,
                        expected_authority,
                        predecessor_state,
                        error,
                    )
                    published_failure = True
                except BaseException as persistence_error:
                    raise Program013PostClaimPersistenceError(
                        "Program 013 terminal persistence failed after possible transport"
                    ) from persistence_error
            if published_failure and isinstance(error, Exception):
                raise Program013AuthorityError(
                    "Program 013 acquisition ended with a sealed failure"
                ) from None
            raise


class _CredentialLoader:
    def __init__(
        self,
        root_descriptor: int,
        authority: Mapping[str, Any],
        predecessor_state: _PredecessorState,
        environ: Mapping[str, str] | None,
        mock_transport: MockBarsTransport | None,
        after_access: Callable[[], None] | None,
        latest_response_at: datetime | None,
    ) -> None:
        self._root_descriptor = root_descriptor
        self._authority = authority
        self._predecessor_state = predecessor_state
        self._environ = environ
        self._mock_transport = mock_transport
        self._after_access = after_access
        self._latest_response_at = latest_response_at
        self._loaded = False
        self._client: predecessor._AlpacaBarsClient | None = None

    def get(
        self, intent: program_011.PageIntent, before_transport: Callable[[], None]
    ) -> raw_contract.RawResponse:
        if not self._loaded:
            sequence = _next_credential_sequence(
                self._root_descriptor, self._authority, self._predecessor_state
            )
            attempt = _credential_attempt(self._authority, self._predecessor_state.sha256, sequence)
            prefix = f"credential-load-{sequence:06d}"
            _reserve_process_credential_access(
                lambda: predecessor._append_atomic(
                    self._root_descriptor,
                    f"{prefix}.attempt.json",
                    (canonical_json(attempt) + "\n").encode(),
                )
            )
            try:
                key_id, secret_key = read_credentials(self._environ)
            except Exception:
                predecessor._append_atomic(
                    self._root_descriptor,
                    f"{prefix}.receipt.json",
                    _credential_receipt_payload(str(attempt["attempt_identity"]), "FAILURE"),
                )
                raise
            if self._after_access is not None:
                self._after_access()
            predecessor._append_atomic(
                self._root_descriptor,
                f"{prefix}.receipt.json",
                _credential_receipt_payload(str(attempt["attempt_identity"]), "SUCCESS"),
            )
            if self._mock_transport is None:
                self._client = predecessor._AlpacaBarsClient(
                    key_id,
                    secret_key,
                    pace=predecessor._RecoveryPacer(self._latest_response_at),
                )
            self._loaded = True
        if self._mock_transport is not None:
            before_transport()
            return self._mock_transport.get(intent)
        assert self._client is not None
        return self._client.get(intent, before_transport)


class _PersistentSessionSource:
    def __init__(
        self,
        root_descriptor: int,
        request: program_011.SessionRequest,
        authority: Mapping[str, Any],
        predecessor_state: _PredecessorState,
        budget: _Budget,
        loader: _CredentialLoader,
        consume: Callable[[], None],
        after_intent: Callable[[], None] | None,
        after_body: Callable[[], None] | None,
        after_page: Callable[[], None] | None,
    ) -> None:
        self._root_descriptor = root_descriptor
        self._request = request
        self._authority = authority
        self._predecessor_state = predecessor_state
        self._budget = budget
        self._loader = loader
        self._consume = consume
        self._after_intent = after_intent
        self._after_body = after_body
        self._after_page = after_page
        self._pending: program_011.RetainedPage | None = None

    def response(self, intent: program_011.PageIntent) -> raw_contract.RawResponse:
        if self._pending is not None:
            raise Program013AuthorityError("Program 013 persistent source state differs")
        _validate_page_intent(self._request, intent, self._predecessor_state)
        prefix = predecessor._page_prefix(self._request, intent.page_index)
        present = tuple(
            predecessor._exists(self._root_descriptor, f"{prefix}.{suffix}")
            for suffix in ("intent.json", "body", "receipt.json")
        )
        if all(present):
            response, _ = _load_completed_page(
                self._root_descriptor,
                self._request,
                intent,
                self._authority,
                self._predecessor_state,
            )
            self._pending = program_011.RetainedPage(
                intent.page_index,
                len(response.body),
                hashlib.sha256(response.body).hexdigest(),
            )
            return response
        if any(present):
            if present[0]:
                expected = _intent_payload(
                    self._authority, self._predecessor_state, self._request, intent
                )
                if predecessor._read(self._root_descriptor, f"{prefix}.intent.json") != expected:
                    raise Program013AuthorityError(
                        "Program 013 partial request intent checkpoint differs"
                    )
            raise Program013AuthorityError(
                "Program 013 ambiguous page checkpoint forbids request reissue"
            )
        self._budget.reserve_request()
        predecessor._append_atomic(
            self._root_descriptor,
            f"{prefix}.intent.json",
            _intent_payload(self._authority, self._predecessor_state, self._request, intent),
        )
        if self._after_intent is not None:
            self._after_intent()
        response = self._loader.get(intent, self._consume)
        body = response.body[: science.MAXIMUM_RESPONSE_PAGE_BYTES + 1]
        predecessor._append(self._root_descriptor, f"{prefix}.body", body)
        if self._after_body is not None:
            self._after_body()
        observed_at = predecessor._utc_now()
        receipt = _response_receipt(
            self._authority,
            self._predecessor_state,
            self._request,
            intent,
            raw_contract.RawResponse(response.status, body),
            observed_at,
        )
        predecessor._append(
            self._root_descriptor,
            f"{prefix}.receipt.json",
            (canonical_json(receipt) + "\n").encode(),
        )
        self._budget.accept_response(
            self._request,
            intent,
            response.status,
            body,
            predecessor._parse_observed_at(observed_at),
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
            raise Program013AuthorityError("Program 013 retained response differs")
        self._pending = None
        return pending


class _ReplaySource:
    def __init__(
        self,
        root_descriptor: int,
        request: program_011.SessionRequest,
        authority: Mapping[str, Any],
        predecessor_state: _PredecessorState,
        budget: _Budget,
    ) -> None:
        self._root_descriptor = root_descriptor
        self._request = request
        self._authority = authority
        self._predecessor_state = predecessor_state
        self._budget = budget
        self._pending: program_011.RetainedPage | None = None

    def response(self, intent: program_011.PageIntent) -> raw_contract.RawResponse:
        _validate_page_intent(self._request, intent, self._predecessor_state)
        prefix = predecessor._page_prefix(self._request, intent.page_index)
        present = tuple(
            predecessor._exists(self._root_descriptor, f"{prefix}.{suffix}")
            for suffix in ("intent.json", "body", "receipt.json")
        )
        if not any(present):
            raise _TransportRequired
        expected_intent = _intent_payload(
            self._authority, self._predecessor_state, self._request, intent
        )
        if not all(present):
            if (
                present not in {(True, False, False), (True, True, False)}
                or predecessor._read(self._root_descriptor, f"{prefix}.intent.json")
                != expected_intent
            ):
                raise Program013AuthorityError("Program 013 partial page checkpoint differs")
            self._budget.reserve_request()
            raise _IncompletePageCheckpoint(
                "Program 013 ambiguous page checkpoint forbids request reissue"
            )
        response, observed_at = _load_completed_page(
            self._root_descriptor,
            self._request,
            intent,
            self._authority,
            self._predecessor_state,
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
            raise Program013AuthorityError("Program 013 replayed response differs")
        self._pending = None
        return pending


class _ExistingSessionSource:
    def __init__(
        self,
        root_descriptor: int,
        request: program_011.SessionRequest,
        authority: Mapping[str, Any],
        predecessor_state: _PredecessorState,
    ) -> None:
        self._root_descriptor = root_descriptor
        self._request = request
        self._authority = authority
        self._predecessor_state = predecessor_state
        self._pending: program_011.RetainedPage | None = None

    def response(self, intent: program_011.PageIntent) -> raw_contract.RawResponse:
        _validate_page_intent(self._request, intent, self._predecessor_state)
        prefix = predecessor._page_prefix(self._request, intent.page_index)
        if not all(
            predecessor._exists(self._root_descriptor, f"{prefix}.{suffix}")
            for suffix in ("intent.json", "body", "receipt.json")
        ):
            raise _TransportRequired
        response, _ = _load_completed_page(
            self._root_descriptor,
            self._request,
            intent,
            self._authority,
            self._predecessor_state,
        )
        self._pending = program_011.RetainedPage(
            intent.page_index,
            len(response.body),
            hashlib.sha256(response.body).hexdigest(),
        )
        return response

    def retain(self, page_index: int, body: bytes) -> program_011.RetainedPage:
        pending = self._pending
        if (
            pending is None
            or pending.page_index != page_index
            or pending.byte_count != len(body)
            or pending.sha256 != hashlib.sha256(body).hexdigest()
        ):
            raise Program013AuthorityError("Program 013 existing response differs")
        self._pending = None
        return pending


def _combined_projection(
    program_013_root: int,
    program_012_root: int,
    predecessor_state: _PredecessorState,
    authority: Mapping[str, Any],
    budget: _Budget,
    *,
    canonical_file: BinaryIO | None,
    loader: _CredentialLoader | None,
    consume: Callable[[], None] | None = None,
    after_intent: Callable[[], None] | None = None,
    after_body: Callable[[], None] | None = None,
    after_page: Callable[[], None] | None = None,
) -> _CombinedProjection:
    prefix_budget = predecessor._Budget()
    missing: dict[date, set[str]] = {}
    morning: dict[date, dict[str, tuple[Any, Any, Any]]] = {}
    canonical_hash = hashlib.sha256()
    raw_row_count = 0
    for request_index, request in enumerate(science.acquisition_requests()):
        if request_index < predecessor_state.frontier_request_index:
            source: Any = predecessor._ReplaySource(
                program_012_root,
                request,
                predecessor_state.active_authority,
                predecessor_state.source_commit,
                prefix_budget,
            )
        elif loader is None:
            source = _ExistingSessionSource(program_013_root, request, authority, predecessor_state)
        else:
            assert consume is not None
            source = _PersistentSessionSource(
                program_013_root,
                request,
                authority,
                predecessor_state,
                budget,
                loader,
                consume,
                after_intent,
                after_body,
                after_page,
            )
        result = _execute_session(request, source)
        coordinates = {
            f"{symbol}@{predecessor._iso_utc(timestamp)}"
            for symbol, timestamp in result.missingness.source_missing
        }
        if coordinates:
            missing[request.session] = coordinates
        science.collect_morning_metrics(result.rows, morning)
        for row in result.rows:
            line = (canonical_json(science.canonical_bar_record(row)) + "\n").encode()
            if canonical_file is not None and canonical_file.write(line) != len(line):
                raise Program013AuthorityError("Program 013 canonical raw write was incomplete")
            canonical_hash.update(line)
            raw_row_count += 1
    if (
        prefix_budget.requests
        != _count(
            predecessor_state.manifest.get("completed_request_count"),
            "predecessor completed request count",
        )
        or prefix_budget.responses
        != _count(
            predecessor_state.manifest.get("completed_response_count"),
            "predecessor completed response count",
        )
        or prefix_budget.response_bytes
        != _count(
            predecessor_state.manifest.get("completed_response_bytes"),
            "predecessor completed response byte count",
        )
    ):
        raise Program013AuthorityError("Program 013 predecessor replay budget differs")
    response_manifest = {
        "schema_version": "program-013-private-response-manifest-v1",
        "program_id": PROGRAM_ID,
        "authority_id": authority["authority_id"],
        "authority_fingerprint": authority["authority_fingerprint"],
        "runtime_binding": dict(_runtime_binding(authority)),
        "predecessor_import_manifest_sha256": predecessor_state.sha256,
        "request_count": budget.new_requests,
        "response_count": budget.new_responses,
        "response_bytes": budget.new_response_bytes,
        "pages": budget.pages,
        "credentials_stored": False,
    }
    return _CombinedProjection(
        canonical_sha256=canonical_hash.hexdigest(),
        raw_row_count=raw_row_count,
        missing=missing,
        morning=morning,
        program_013_response_manifest=response_manifest,
        budget=budget,
    )


def _execute_session(
    request: program_011.SessionRequest,
    source: _PersistentSessionSource | _ReplaySource | _ExistingSessionSource | Any,
) -> program_011.SessionResult:
    try:
        return predecessor._execute_session(request, cast(Any, source))
    except predecessor.ChainIncompleteError as error:
        replacement = Program013AuthorityError(str(error).replace("Program 012", "Program 013"))
        replacement.classification = error.classification  # type: ignore[attr-defined]
        raise replacement from error
    except predecessor.Program012AuthorityError as error:
        raise Program013AuthorityError(str(error).replace("Program 012", "Program 013")) from error


def _reconstruct_state(
    root_descriptor: int,
    predecessor_state: _PredecessorState,
    *,
    authority: Mapping[str, Any],
    allow_terminal_failure: bool = False,
    require_complete: bool = False,
) -> _Budget:
    entries = set(os.listdir(root_descriptor))
    if entries & _DERIVED_KEYS and _TERMINAL_KEY not in entries:
        raise Program013AuthorityError("Program 013 derived evidence lacks a terminal")
    allowed = {
        "active-authority.json",
        "claim.json",
        "predecessor-import-manifest.json",
        "run.lock",
        *_DERIVED_KEYS,
        _TERMINAL_KEY,
    }
    page_entries: set[str] = set()
    for entry in entries - allowed:
        if _PAGE_KEY.fullmatch(entry):
            page_entries.add(entry)
        elif _CREDENTIAL_KEY.fullmatch(entry) or entry.startswith("tmp-"):
            continue
        else:
            raise Program013AuthorityError("Program 013 private checkpoint contains unknown state")
    credential_loads, successful_loads = _credential_load_counts(
        root_descriptor, authority, predecessor_state
    )
    claim_exists = predecessor._exists(root_descriptor, "claim.json")
    body_or_receipt = any(
        entry.endswith(".body") or entry.endswith(".receipt.json") for entry in page_entries
    )
    if page_entries:
        if claim_exists:
            if successful_loads == 0:
                raise Program013AuthorityError(
                    "Program 013 page evidence lacks a successful credential audit"
                )
            _validate_claim(root_descriptor, authority, predecessor_state)
        elif body_or_receipt or (
            not allow_terminal_failure
            and any(not entry.endswith(".intent.json") for entry in page_entries)
        ):
            raise Program013AuthorityError("Program 013 provider evidence lacks a transport claim")
    elif claim_exists:
        raise Program013AuthorityError("Program 013 transport claim lacks page evidence")
    if credential_loads and not page_entries:
        raise Program013AuthorityError("Program 013 credential audit lacks request evidence")

    requests = science.acquisition_requests()
    expected_sessions = {
        request.session for request in requests[predecessor_state.frontier_request_index :]
    }
    for entry in page_entries:
        match = _PAGE_KEY.fullmatch(entry)
        assert match is not None
        try:
            session = date.fromisoformat(match.group("session"))
            page_index = int(match.group("page"))
        except ValueError as error:
            raise Program013AuthorityError("Program 013 page key is invalid") from error
        if session not in expected_sessions or not 1 <= page_index <= 16:
            raise Program013AuthorityError("Program 013 page key is outside the recovery plan")

    budget = _Budget(predecessor_state)
    frontier_found = False
    for request in requests[predecessor_state.frontier_request_index :]:
        session_entries = {
            entry for entry in page_entries if entry.startswith(f"session-{request.session}-")
        }
        if frontier_found:
            if session_entries:
                raise Program013AuthorityError("Program 013 checkpoint skips a request session")
            continue
        source = _ReplaySource(root_descriptor, request, authority, predecessor_state, budget)
        try:
            result = _execute_session(request, source)
        except _IncompletePageCheckpoint:
            if not allow_terminal_failure:
                raise
            completed_pages = sum(
                page["session"] == request.session.isoformat() for page in budget.pages
            )
            expected = predecessor._expected_session_entries(request, completed_pages)
            partial = predecessor._page_prefix(request, completed_pages + 1)
            if frozenset(session_entries) not in {
                frozenset({*expected, f"{partial}.intent.json"}),
                frozenset({*expected, f"{partial}.intent.json", f"{partial}.body"}),
            }:
                raise Program013AuthorityError(
                    "Program 013 terminal checkpoint is not a reachable prefix"
                ) from None
            frontier_found = True
        except _TransportRequired:
            completed_pages = sum(
                page["session"] == request.session.isoformat() for page in budget.pages
            )
            if session_entries != predecessor._expected_session_entries(request, completed_pages):
                raise Program013AuthorityError(
                    "Program 013 checkpoint skips a request page"
                ) from None
            if require_complete:
                raise Program013AuthorityError(
                    "Program 013 acquisition evidence is incomplete"
                ) from None
            frontier_found = True
        except (Program013AuthorityError, program_011.Program011Error):
            if not allow_terminal_failure:
                raise
            completed_pages = sum(
                page["session"] == request.session.isoformat() for page in budget.pages
            )
            if session_entries != predecessor._expected_session_entries(request, completed_pages):
                raise Program013AuthorityError(
                    "Program 013 terminal checkpoint is not a reachable prefix"
                ) from None
            frontier_found = True
        else:
            if session_entries != predecessor._expected_session_entries(request, len(result.pages)):
                raise Program013AuthorityError(
                    "Program 013 checkpoint continues after a terminal page"
                )
    if require_complete and frontier_found:
        raise Program013AuthorityError("Program 013 acquisition evidence is incomplete")
    return budget


def _runtime_failure_counts(
    root_descriptor: int,
    predecessor_state: _PredecessorState,
    authority: Mapping[str, Any],
) -> tuple[int, int, int]:
    try:
        budget = _reconstruct_state(
            root_descriptor,
            predecessor_state,
            authority=authority,
            allow_terminal_failure=True,
        )
        return budget.requests, budget.responses, budget.response_bytes
    except (Program013AuthorityError, program_011.Program011Error):
        budget = _Budget(predecessor_state)
        page_kinds: dict[tuple[str, str], set[str]] = {}
        body_sizes: dict[tuple[str, str], int] = {}
        for entry in os.listdir(root_descriptor):
            match = _PAGE_KEY.fullmatch(entry)
            if match is None:
                continue
            key = match.group("session"), match.group("page")
            kind = match.group("kind")
            page_kinds.setdefault(key, set()).add(kind)
            if kind == "body":
                metadata = os.stat(entry, dir_fd=root_descriptor, follow_symlinks=False)
                body_sizes[key] = metadata.st_size if stat.S_ISREG(metadata.st_mode) else 0
        budget.requests = min(
            science.MAXIMUM_REQUESTS_AND_RESPONSES,
            budget.requests + len(page_kinds),
        )
        receipted = {
            key
            for key, kinds in page_kinds.items()
            if kinds == {"intent.json", "body", "receipt.json"}
        }
        if not predecessor._exists(root_descriptor, "claim.json"):
            receipted.clear()
        budget.responses = min(
            science.MAXIMUM_REQUESTS_AND_RESPONSES - 1,
            budget.requests - 1,
            budget.responses + len(receipted),
        )
        budget.response_bytes = min(
            science.MAXIMUM_TOTAL_RESPONSE_BYTES,
            budget.response_bytes + sum(body_sizes.get(key, 0) for key in receipted),
        )
        return budget.requests, budget.responses, budget.response_bytes


def _runtime_failure_credential_load_count(
    root_descriptor: int,
    authority: Mapping[str, Any],
    predecessor_state: _PredecessorState,
) -> int:
    try:
        return _credential_load_counts(root_descriptor, authority, predecessor_state)[0]
    except Program013AuthorityError:
        return len(
            {
                int(match.group("sequence"))
                for entry in os.listdir(root_descriptor)
                if (match := _CREDENTIAL_KEY.fullmatch(entry)) is not None
                and match.group("kind") == "attempt"
            }
        )


def _claim_value(
    authority: Mapping[str, Any], predecessor_state: _PredecessorState
) -> dict[str, Any]:
    unsigned: dict[str, Any] = {
        "schema_version": "program-013-private-acquisition-claim-v1",
        "program_id": PROGRAM_ID,
        "authority_id": authority["authority_id"],
        "authority_fingerprint": authority["authority_fingerprint"],
        "operation_manifest": OPERATION_MANIFEST,
        "runtime_binding": dict(_runtime_binding(authority)),
        "predecessor_import_manifest_sha256": predecessor_state.sha256,
        "consumption_boundary": CONSUMPTION_BOUNDARY,
        "scientific_use_consumed": True,
        "terminal_fallback": {
            "status": "FAIL-CONSUMED-NO-RETRY",
            "request_reissue_allowed": False,
        },
    }
    return {**unsigned, "claim_fingerprint": fingerprint(unsigned)}


def _claim_payload(authority: Mapping[str, Any], predecessor_state: _PredecessorState) -> bytes:
    return (canonical_json(_claim_value(authority, predecessor_state)) + "\n").encode()


def _validate_claim(
    root_descriptor: int,
    authority: Mapping[str, Any],
    predecessor_state: _PredecessorState,
) -> None:
    if predecessor._read(root_descriptor, "claim.json") != _claim_payload(
        authority, predecessor_state
    ):
        raise Program013AuthorityError("Program 013 transport claim differs")


def _intent_value(
    authority: Mapping[str, Any],
    predecessor_state: _PredecessorState,
    request: program_011.SessionRequest,
    intent: program_011.PageIntent,
) -> dict[str, Any]:
    claim = _claim_value(authority, predecessor_state)
    unsigned: dict[str, Any] = {
        "schema_version": "program-013-private-request-intent-v1",
        "program_id": PROGRAM_ID,
        "authority_fingerprint": authority["authority_fingerprint"],
        "operation_manifest": OPERATION_MANIFEST,
        "runtime_binding": dict(_runtime_binding(authority)),
        "predecessor_import_manifest_sha256": predecessor_state.sha256,
        "expected_claim_fingerprint": claim["claim_fingerprint"],
        "method": "GET",
        "session": request.session.isoformat(),
        "page_index": intent.page_index,
        "request_identity": intent.request_identity,
        "incoming_page_token": intent.incoming_page_token,
        "url": intent.url,
    }
    return {**unsigned, "intent_fingerprint": fingerprint(unsigned)}


def _intent_payload(
    authority: Mapping[str, Any],
    predecessor_state: _PredecessorState,
    request: program_011.SessionRequest,
    intent: program_011.PageIntent,
) -> bytes:
    return (
        canonical_json(_intent_value(authority, predecessor_state, request, intent)) + "\n"
    ).encode()


def _response_receipt(
    authority: Mapping[str, Any],
    predecessor_state: _PredecessorState,
    request: program_011.SessionRequest,
    intent: program_011.PageIntent,
    response: raw_contract.RawResponse,
    observed_at: str,
) -> dict[str, Any]:
    predecessor._parse_observed_at(observed_at)
    if type(response.status) is not int or not 100 <= response.status <= 599:
        raise Program013AuthorityError("Program 013 response status is invalid")
    intent_payload = _intent_payload(authority, predecessor_state, request, intent)
    intent_value = _json_object(intent_payload, "request intent")
    claim = _claim_value(authority, predecessor_state)
    unsigned: dict[str, Any] = {
        "schema_version": "program-013-private-response-receipt-v1",
        "program_id": PROGRAM_ID,
        "authority_fingerprint": authority["authority_fingerprint"],
        "operation_manifest": OPERATION_MANIFEST,
        "runtime_binding": dict(_runtime_binding(authority)),
        "predecessor_import_manifest_sha256": predecessor_state.sha256,
        "claim_fingerprint": claim["claim_fingerprint"],
        "intent_fingerprint": intent_value["intent_fingerprint"],
        "intent_sha256": hashlib.sha256(intent_payload).hexdigest(),
        "session": request.session.isoformat(),
        "page_index": intent.page_index,
        "request_identity": intent.request_identity,
        "status": response.status,
        "retained_response_bytes": len(response.body),
        "response_sha256": hashlib.sha256(response.body).hexdigest(),
        "observed_at": observed_at,
    }
    return {**unsigned, "receipt_fingerprint": fingerprint(unsigned)}


def _load_completed_page(
    root_descriptor: int,
    request: program_011.SessionRequest,
    intent: program_011.PageIntent,
    authority: Mapping[str, Any],
    predecessor_state: _PredecessorState,
) -> tuple[raw_contract.RawResponse, datetime]:
    prefix = predecessor._page_prefix(request, intent.page_index)
    expected_intent = _intent_payload(authority, predecessor_state, request, intent)
    if predecessor._read(root_descriptor, f"{prefix}.intent.json") != expected_intent:
        raise Program013AuthorityError("Program 013 request intent checkpoint differs")
    body = predecessor._read(root_descriptor, f"{prefix}.body")
    receipt_raw = predecessor._read(root_descriptor, f"{prefix}.receipt.json")
    receipt = _json_object(receipt_raw, "response receipt")
    status = receipt.get("status")
    if type(status) is not int or not 100 <= status <= 599:
        raise Program013AuthorityError("Program 013 response status is invalid")
    observed_at = predecessor._parse_observed_at(receipt.get("observed_at"))
    expected_receipt = _response_receipt(
        authority,
        predecessor_state,
        request,
        intent,
        raw_contract.RawResponse(status, body),
        predecessor._format_observed_at(observed_at),
    )
    if (
        set(receipt) != _RECEIPT_KEYS
        or receipt != expected_receipt
        or receipt_raw != (canonical_json(expected_receipt) + "\n").encode()
    ):
        raise Program013AuthorityError("Program 013 response checkpoint differs")
    return raw_contract.RawResponse(status, body), observed_at


def _validate_page_intent(
    request: program_011.SessionRequest,
    intent: program_011.PageIntent,
    predecessor_state: _PredecessorState,
) -> None:
    if (
        type(request) is not program_011.SessionRequest
        or type(intent) is not program_011.PageIntent
        or intent.request_identity != request.identity
        or not 1 <= intent.page_index <= science.MAXIMUM_PAGES_PER_SESSION
        or intent.url != request.url(intent.incoming_page_token)
    ):
        raise Program013AuthorityError("Program 013 request intent differs")
    frontier = _mapping(predecessor_state.manifest.get("frontier"), "predecessor frontier")
    frontier_request = science.acquisition_requests()[predecessor_state.frontier_request_index]
    if (
        request == frontier_request
        and intent.page_index == 1
        and (
            intent.incoming_page_token is not None
            or intent.url != frontier.get("url")
            or intent.request_identity != frontier.get("request_identity")
            or request.session.isoformat() != frontier.get("session")
            or frontier.get("page_index") != 1
        )
    ):
        raise Program013AuthorityError("Program 013 first intent differs from the frontier")


def _credential_attempt(
    authority: Mapping[str, Any], predecessor_manifest_sha256: str, sequence: int
) -> dict[str, Any]:
    if type(sequence) is not int or sequence < 1:
        raise Program013AuthorityError("Program 013 credential sequence differs")
    unsigned: dict[str, Any] = {
        "schema_version": "program-013-private-credential-load-attempt-v1",
        "authority_fingerprint": authority["authority_fingerprint"],
        "runtime_binding": dict(_runtime_binding(authority)),
        "predecessor_import_manifest_sha256": predecessor_manifest_sha256,
        "process_recovery_sequence": sequence,
    }
    return {**unsigned, "attempt_identity": fingerprint(unsigned)}


def _credential_receipt_payload(attempt_identity: str, status: str) -> bytes:
    if _HEX_64.fullmatch(attempt_identity) is None or status not in {"SUCCESS", "FAILURE"}:
        raise Program013AuthorityError("Program 013 credential receipt differs")
    value = {
        "schema_version": "program-013-private-credential-load-receipt-v1",
        "attempt_identity": attempt_identity,
        "status": status,
    }
    return (canonical_json(value) + "\n").encode()


def _credential_load_counts(
    root_descriptor: int,
    authority: Mapping[str, Any],
    predecessor_state: _PredecessorState,
) -> tuple[int, int]:
    attempts: dict[int, dict[str, Any]] = {}
    receipts: dict[int, dict[str, Any]] = {}
    for entry in os.listdir(root_descriptor):
        match = _CREDENTIAL_KEY.fullmatch(entry)
        if match is None:
            continue
        sequence = int(match.group("sequence"))
        raw = predecessor._read(root_descriptor, entry)
        value = _json_object(raw, "credential audit")
        if raw != (canonical_json(value) + "\n").encode():
            raise Program013AuthorityError("Program 013 credential audit is not canonical")
        target = attempts if match.group("kind") == "attempt" else receipts
        if sequence in target:
            raise Program013AuthorityError("Program 013 credential sequence is duplicated")
        target[sequence] = value
    sequences = sorted(attempts)
    if sequences != list(range(1, len(sequences) + 1)) or not set(receipts) <= set(attempts):
        raise Program013AuthorityError("Program 013 credential sequence is not contiguous")
    expected_runtime = dict(_runtime_binding(authority))
    successful = 0
    for sequence in sequences:
        attempt = attempts[sequence]
        expected_attempt = _credential_attempt(authority, predecessor_state.sha256, sequence)
        if set(attempt) != _CREDENTIAL_ATTEMPT_KEYS or attempt != expected_attempt:
            raise Program013AuthorityError("Program 013 credential attempt binding differs")
        receipt = receipts.get(sequence)
        if receipt is None:
            if sequence != sequences[-1]:
                raise Program013AuthorityError("Program 013 credential receipt sequence has a gap")
            continue
        if (
            set(receipt) != _CREDENTIAL_RECEIPT_KEYS
            or receipt.get("schema_version") != "program-013-private-credential-load-receipt-v1"
            or receipt.get("attempt_identity") != attempt["attempt_identity"]
            or receipt.get("status") not in {"SUCCESS", "FAILURE"}
            or attempt.get("runtime_binding") != expected_runtime
        ):
            raise Program013AuthorityError("Program 013 credential receipt binding differs")
        if receipt["status"] == "SUCCESS":
            successful += 1
        elif sequence != sequences[-1]:
            raise Program013AuthorityError("Program 013 failed credential load is not terminal")
    return len(attempts), successful


def _next_credential_sequence(
    root_descriptor: int,
    authority: Mapping[str, Any],
    predecessor_state: _PredecessorState,
) -> int:
    attempts, _ = _credential_load_counts(root_descriptor, authority, predecessor_state)
    return attempts + 1


def _reserve_process_credential_access(write_attempt: Callable[[], None]) -> None:
    global _PROCESS_CREDENTIAL_PID
    process_id = os.getpid()
    with _PROCESS_CREDENTIAL_LOCK:
        if process_id == _PROCESS_CREDENTIAL_PID:
            raise Program013AuthorityError(
                "Program 013 credential access is already consumed in this process"
            )
        try:
            write_attempt()
        finally:
            _PROCESS_CREDENTIAL_PID = process_id


def _revalidate_transport_boundary(
    repository: Path,
    program_013_root: int,
    program_012_root: int,
    authority: Mapping[str, Any],
    predecessor_state: _PredecessorState,
) -> None:
    if _derive_control_validated_authority(repository) != authority:
        raise Program013AuthorityError("Program 013 authority changed at transport boundary")
    current_predecessor = _derive_predecessor_state(repository, program_012_root, authority)
    if current_predecessor.payload != predecessor_state.payload:
        raise Program013AuthorityError("Program 012 evidence changed at transport boundary")
    _require_working_disk_capacity(program_013_root)
    _require_zero_protected_overlap(repository, _authority_commit(authority))


def _revalidate_closeout_boundary(
    repository: Path,
    program_012_root: int,
    authority: Mapping[str, Any],
    predecessor_state: _PredecessorState,
) -> None:
    if _derive_control_validated_authority(repository) != authority:
        raise Program013AuthorityError("Program 013 authority changed at closeout")
    current_predecessor = _derive_predecessor_state(repository, program_012_root, authority)
    if current_predecessor.payload != predecessor_state.payload:
        raise Program013AuthorityError("Program 012 evidence changed at closeout")
    _require_zero_protected_overlap(repository, _authority_commit(authority))


def _require_zero_protected_overlap(repository: Path, commit: str) -> None:
    try:
        protected_ranges = git_controls._current_protected_ranges(repository, commit=commit)
    except git_controls.Program011AuthorityError as error:
        raise Program013AuthorityError(str(error).replace("Program 011", "Program 013")) from None
    if any(
        start <= request.session <= end
        for request in science.acquisition_requests()
        for start, end in protected_ranges
    ):
        raise Program013AuthorityError("Program 013 request chronology overlaps protected data")


def _require_working_disk_capacity(root_descriptor: int) -> None:
    filesystem = os.fstatvfs(root_descriptor)
    if filesystem.f_bavail * filesystem.f_frsize < science.WORKING_DISK_RESERVATION_BYTES:
        raise Program013AuthorityError("Program 013 requires 8 GiB of available working space")


def _runtime_binding(authority: Mapping[str, Any]) -> Mapping[str, Any]:
    runtime = _mapping(authority.get("runtime_binding"), "runtime binding")
    if (
        set(runtime) != _RUNTIME_BINDING_KEYS
        or _HEX_40.fullmatch(str(runtime.get("source_commit"))) is None
        or _HEX_40.fullmatch(str(runtime.get("source_tree"))) is None
        or _HEX_64.fullmatch(str(runtime.get("implementation_root"))) is None
    ):
        raise Program013AuthorityError("Program 013 runtime binding differs")
    return runtime


def _count(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise Program013AuthorityError(f"Program 013 {label} differs")
    return value


def _typed_string_set(value: Any, label: str) -> set[str]:
    items = _sequence(value, label)
    if any(type(item) is not str or not item for item in items) or len(set(items)) != len(items):
        raise Program013AuthorityError(f"Program 013 {label} differs")
    return set(cast(Sequence[str], items))


def _derived_admission_evidence(
    repository: Path,
    authority: Mapping[str, Any],
    predecessor_state: _PredecessorState,
    projection: _CombinedProjection,
) -> dict[str, Any]:
    proposal_012 = _load_bound(
        repository,
        _mapping(
            _mapping(
                validate_operation_contract(repository, commit=_authority_commit(authority)).get(
                    "predecessor"
                ),
                "predecessor bindings",
            ).get("program_012_scientific_contract"),
            "Program 012 science binding",
        ),
        "proposal_fingerprint",
        commit=_authority_commit(authority),
    )
    bindings = _mapping(proposal_012.get("bindings"), "Program 012 bindings")
    program_005_plan = _load_bound(
        repository,
        _mapping(bindings.get("program_005_policy_precedent"), "Program 005 binding"),
        "plan_fingerprint",
        commit=_authority_commit(authority),
    )
    incident = _load_bound(
        repository,
        _mapping(bindings.get("program_002_fixed_quarantine_incident"), "incident binding"),
        "incident_fingerprint",
        commit=_authority_commit(authority),
    )
    admission = dict(
        science.assess_structural_admission(
            proposal_012,
            program_005_plan,
            incident,
            projection.missing,
            projection.morning,
        )
    )
    admission["schema_version"] = "program-013-private-structural-admission-report-v1"
    admission["program_id"] = PROGRAM_ID
    admission["status"] = (
        "ADMITTED-PROGRAM-013-RAW-STRUCTURAL-PREFIX"
        if admission["admission_passed"]
        else "TERMINAL-FAIL-CONSUMED-NO-RETRY"
    )
    unsigned_admission = dict(admission)
    unsigned_admission.pop("admission_fingerprint", None)
    admission["admission_fingerprint"] = fingerprint(unsigned_admission)

    missing_value = {
        "schema_version": "program-013-private-combined-missing-coordinates-v1",
        "program_id": PROGRAM_ID,
        "predecessor_import_manifest_sha256": predecessor_state.sha256,
        "sessions": {
            session.isoformat(): sorted(coordinates)
            for session, coordinates in sorted(projection.missing.items())
        },
    }
    response_payload = (canonical_json(projection.program_013_response_manifest) + "\n").encode()
    missing_payload = (canonical_json(missing_value) + "\n").encode()
    admission_payload = (canonical_json(admission) + "\n").encode()
    response_sha = hashlib.sha256(response_payload).hexdigest()
    missing_sha = hashlib.sha256(missing_payload).hexdigest()
    admission_sha = hashlib.sha256(admission_payload).hexdigest()
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
        for request in science.acquisition_requests()
        if request.session in science.full_trade_sessions() and request.session not in excluded
    )
    admitted_session_fingerprint = fingerprint(admitted_sessions)
    private_dataset_identity = fingerprint(
        {
            "operation_manifest": OPERATION_MANIFEST,
            "authority_fingerprint": authority["authority_fingerprint"],
            "source_commit": _source_commit(authority),
            "predecessor_import_manifest_sha256": predecessor_state.sha256,
            "program_013_response_manifest_sha256": response_sha,
            "combined_canonical_raw_sha256": projection.canonical_sha256,
            "combined_missingness_sha256": missing_sha,
            "combined_structural_admission_sha256": admission_sha,
            "combined_structural_admission_fingerprint": admission["admission_fingerprint"],
            "admitted_session_index_fingerprint": admitted_session_fingerprint,
            "action_ledger": _ACTION_LEDGER_MANIFEST,
        }
    )
    public_lineage = (
        {
            "schema_version": ("program-013-public-raw-structural-prefix-lineage-manifest-v1"),
            "program_id": PROGRAM_ID,
            "authority_id": authority["authority_id"],
            "authority_fingerprint": authority["authority_fingerprint"],
            "source_commit": _source_commit(authority),
            "status": "ADMITTED-PROGRAM-013-RAW-STRUCTURAL-PREFIX",
            "dataset_lineage_identity": fingerprint(
                {
                    "operation_manifest": OPERATION_MANIFEST,
                    "authority_fingerprint": authority["authority_fingerprint"],
                    "source_commit": _source_commit(authority),
                    "program_012_public_terminal": _mapping(
                        _mapping(
                            validate_operation_contract(
                                repository, commit=_authority_commit(authority)
                            ).get("predecessor"),
                            "predecessor bindings",
                        ).get("program_012_terminal_result"),
                        "Program 012 terminal binding",
                    ),
                    "action_ledger": _ACTION_LEDGER_MANIFEST,
                    "status": "ADMITTED-PROGRAM-013-RAW-STRUCTURAL-PREFIX",
                }
            ),
        }
        if admission["admission_passed"]
        else None
    )
    if public_lineage is not None and (
        public_lineage["dataset_lineage_identity"] == private_dataset_identity
    ):
        raise Program013AuthorityError("Program 013 public and private identities collide")
    dataset_manifest = {
        "schema_version": "program-013-private-combined-dataset-manifest-v1",
        "program_id": PROGRAM_ID,
        "authority_id": authority["authority_id"],
        "authority_fingerprint": authority["authority_fingerprint"],
        "source_commit": _source_commit(authority),
        "predecessor_import_manifest_sha256": predecessor_state.sha256,
        "status": admission["status"],
        "private_dataset_identity": private_dataset_identity,
        "program_013_response_manifest_sha256": response_sha,
        "combined_canonical_raw_sha256": projection.canonical_sha256,
        "combined_missingness_sha256": missing_sha,
        "combined_structural_admission_sha256": admission_sha,
        "raw_row_count": projection.raw_row_count,
        "expected_coordinate_count": science.EXPECTED_COORDINATE_COUNT,
        "missing_coordinate_count": admission["missing_coordinate_count"],
        "excluded_full_session_count": admission["excluded_full_session_count"],
        "admitted_full_session_count": len(admitted_sessions),
        "admitted_session_index_fingerprint": admitted_session_fingerprint,
        "exact_missingness_private": True,
        "program_002_admission": False,
        "strategy_metrics_present": False,
    }
    dataset_payload = (canonical_json(dataset_manifest) + "\n").encode()
    return {
        "admission": admission,
        "private_dataset_identity": private_dataset_identity,
        "public_lineage": public_lineage,
        "payloads": {
            "program-013-response-manifest.json": response_payload,
            "combined-missing-coordinates.json": missing_payload,
            "combined-structural-admission.json": admission_payload,
            "combined-dataset-manifest.json": dataset_payload,
        },
        "hashes": {
            "program_013_response_manifest_sha256": response_sha,
            "combined_canonical_raw_sha256": projection.canonical_sha256,
            "combined_missingness_sha256": missing_sha,
            "combined_structural_admission_sha256": admission_sha,
            "combined_dataset_manifest_sha256": hashlib.sha256(dataset_payload).hexdigest(),
        },
    }


def _admission_terminal_payload(
    root_descriptor: int,
    authority: Mapping[str, Any],
    predecessor_state: _PredecessorState,
    projection: _CombinedProjection,
    evidence: Mapping[str, Any],
    observed_at: str,
) -> bytes:
    admission = _mapping(evidence.get("admission"), "structural admission")
    hashes = _mapping(evidence.get("hashes"), "derived evidence hashes")
    admission_passed = admission.get("admission_passed") is True
    public_lineage = evidence.get("public_lineage")
    private_identity = str(evidence.get("private_dataset_identity"))
    if _HEX_64.fullmatch(private_identity) is None:
        raise Program013AuthorityError("Program 013 private dataset identity differs")
    lineage_identity = (
        str(_mapping(public_lineage, "public lineage").get("dataset_lineage_identity"))
        if admission_passed
        else None
    )
    record: dict[str, Any] = {
        "schema_version": "program-013-private-terminal-v1",
        "program_id": PROGRAM_ID,
        "authority_id": authority["authority_id"],
        "authority_fingerprint": authority["authority_fingerprint"],
        "source_commit": _source_commit(authority),
        "source_tree": _runtime_binding(authority)["source_tree"],
        "runtime_implementation_root": _runtime_binding(authority)["implementation_root"],
        "operation_manifest": OPERATION_MANIFEST,
        "predecessor_import_manifest_sha256": predecessor_state.sha256,
        "public_terminal_path": PUBLIC_TERMINAL_PATH.as_posix(),
        "result_kind": "ADMISSION-PASS" if admission_passed else "ADMISSION-FAILURE",
        "status": admission["status"],
        "provider_transport_attempted": True,
        "scientific_use_consumed": True,
        "failure_class": None,
        "failure_classification": None,
        "program_013_credential_loads": _credential_load_counts(
            root_descriptor, authority, predecessor_state
        )[0],
        "cumulative_request_intents": projection.budget.requests,
        "cumulative_responses": projection.budget.responses,
        "cumulative_response_bytes": projection.budget.response_bytes,
        "structural_admission_evaluated": True,
        "admission_passed": admission_passed,
        "private_evidence": {
            **hashes,
            "raw_row_count": projection.raw_row_count,
            "missing_coordinate_count": admission["missing_coordinate_count"],
            "excluded_full_session_count": admission["excluded_full_session_count"],
        },
        "public_dataset_lineage_manifest": public_lineage,
        "dataset_lineage_identity": lineage_identity,
        "private_dataset_identity": private_identity,
        "automatic_retries": 0,
        "credentials_stored": False,
        "program_002_admission": False,
        "strategy_calculations": 0,
        "strategy_returns": 0,
        "observed_at": observed_at,
    }
    record["terminal_fingerprint"] = fingerprint(record)
    return (canonical_json(record) + "\n").encode()


def _runtime_failure_payload(
    root_descriptor: int,
    predecessor_state: _PredecessorState,
    error: BaseException,
    authority: Mapping[str, Any],
) -> bytes:
    requests, responses, response_bytes = _runtime_failure_counts(
        root_descriptor, predecessor_state, authority
    )
    private_evidence = {
        "program_013_response_manifest_sha256": _evidence_sha256_if_present(
            root_descriptor, "program-013-response-manifest.json"
        ),
        "combined_canonical_raw_sha256": _evidence_sha256_if_present(
            root_descriptor, "combined-canonical-raw.jsonl"
        ),
        "combined_missingness_sha256": _evidence_sha256_if_present(
            root_descriptor, "combined-missing-coordinates.json"
        ),
        "combined_structural_admission_sha256": _evidence_sha256_if_present(
            root_descriptor, "combined-structural-admission.json"
        ),
        "combined_dataset_manifest_sha256": _evidence_sha256_if_present(
            root_descriptor, "combined-dataset-manifest.json"
        ),
        "raw_row_count": None,
        "missing_coordinate_count": None,
        "excluded_full_session_count": None,
    }
    record: dict[str, Any] = {
        "schema_version": "program-013-private-terminal-v1",
        "program_id": PROGRAM_ID,
        "authority_id": authority["authority_id"],
        "authority_fingerprint": authority["authority_fingerprint"],
        "source_commit": _source_commit(authority),
        "source_tree": _runtime_binding(authority)["source_tree"],
        "runtime_implementation_root": _runtime_binding(authority)["implementation_root"],
        "operation_manifest": OPERATION_MANIFEST,
        "predecessor_import_manifest_sha256": predecessor_state.sha256,
        "public_terminal_path": PUBLIC_TERMINAL_PATH.as_posix(),
        "result_kind": "RUNTIME-FAILURE",
        "status": "FAIL-CONSUMED-NO-RETRY",
        "provider_transport_attempted": predecessor._exists(root_descriptor, "claim.json"),
        "scientific_use_consumed": True,
        "failure_class": type(error).__name__,
        "failure_classification": getattr(error, "classification", type(error).__name__),
        "program_013_credential_loads": _runtime_failure_credential_load_count(
            root_descriptor, authority, predecessor_state
        ),
        "cumulative_request_intents": requests,
        "cumulative_responses": responses,
        "cumulative_response_bytes": response_bytes,
        "structural_admission_evaluated": False,
        "admission_passed": False,
        "private_evidence": private_evidence,
        "public_dataset_lineage_manifest": None,
        "dataset_lineage_identity": None,
        "private_dataset_identity": None,
        "automatic_retries": 0,
        "credentials_stored": False,
        "program_002_admission": False,
        "strategy_calculations": 0,
        "strategy_returns": 0,
        "observed_at": predecessor._utc_now(),
    }
    record["terminal_fingerprint"] = fingerprint(record)
    return (canonical_json(record) + "\n").encode()


def _load_terminal_record(
    repository: Path,
    root_descriptor: int,
    predecessor_root: int,
    authority: Mapping[str, Any],
    predecessor_state: _PredecessorState,
) -> dict[str, Any]:
    raw = predecessor._read(root_descriptor, _TERMINAL_KEY)
    record = _json_object(raw, "private terminal")
    unsigned = dict(record)
    stored_fingerprint = unsigned.pop("terminal_fingerprint", None)
    if (
        set(record) != _PRIVATE_TERMINAL_KEYS
        or raw != (canonical_json(record) + "\n").encode()
        or stored_fingerprint != fingerprint(unsigned)
        or record.get("schema_version") != "program-013-private-terminal-v1"
        or record.get("program_id") != PROGRAM_ID
        or record.get("authority_id") != authority["authority_id"]
        or record.get("authority_fingerprint") != authority["authority_fingerprint"]
        or record.get("source_commit") != _source_commit(authority)
        or record.get("source_tree") != _runtime_binding(authority)["source_tree"]
        or record.get("runtime_implementation_root")
        != _runtime_binding(authority)["implementation_root"]
        or record.get("operation_manifest") != OPERATION_MANIFEST
        or record.get("predecessor_import_manifest_sha256") != predecessor_state.sha256
        or record.get("public_terminal_path") != PUBLIC_TERMINAL_PATH.as_posix()
        or type(record.get("provider_transport_attempted")) is not bool
        or record.get("scientific_use_consumed") is not True
        or record.get("automatic_retries") != 0
        or record.get("credentials_stored") is not False
        or record.get("program_002_admission") is not False
        or record.get("strategy_calculations") != 0
        or record.get("strategy_returns") != 0
    ):
        raise Program013AuthorityError("Program 013 private terminal binding differs")
    predecessor._parse_observed_at(record.get("observed_at"))
    current_predecessor = _derive_predecessor_state(repository, predecessor_root, authority)
    if current_predecessor.payload != predecessor_state.payload:
        raise Program013AuthorityError("Program 012 evidence changed before terminal validation")
    result_kind = record.get("result_kind")
    durable_credentials = (
        _runtime_failure_credential_load_count(root_descriptor, authority, predecessor_state)
        if result_kind == "RUNTIME-FAILURE"
        else _credential_load_counts(root_descriptor, authority, predecessor_state)[0]
    )
    if _count(
        record.get("program_013_credential_loads"), "terminal credential count"
    ) != durable_credentials or record.get(
        "provider_transport_attempted"
    ) is not predecessor._exists(root_descriptor, "claim.json"):
        raise Program013AuthorityError("Program 013 terminal credential count differs")
    private_evidence = _exact_object(
        record.get("private_evidence"), _PRIVATE_EVIDENCE_KEYS, "private terminal evidence"
    )
    if result_kind == "RUNTIME-FAILURE":
        counts = _runtime_failure_counts(root_descriptor, predecessor_state, authority)
        if (
            record.get("status") != "FAIL-CONSUMED-NO-RETRY"
            or record.get("structural_admission_evaluated") is not False
            or record.get("admission_passed") is not False
            or record.get("public_dataset_lineage_manifest") is not None
            or record.get("dataset_lineage_identity") is not None
            or record.get("private_dataset_identity") is not None
            or type(record.get("failure_class")) is not str
            or not record["failure_class"]
            or type(record.get("failure_classification")) is not str
            or not record["failure_classification"]
            or private_evidence["raw_row_count"] is not None
            or private_evidence["missing_coordinate_count"] is not None
            or private_evidence["excluded_full_session_count"] is not None
        ):
            raise Program013AuthorityError("Program 013 runtime terminal semantics differ")
        _validate_runtime_failure_counts(record, counts)
        for field, key in (
            ("program_013_response_manifest_sha256", "program-013-response-manifest.json"),
            ("combined_canonical_raw_sha256", "combined-canonical-raw.jsonl"),
            ("combined_missingness_sha256", "combined-missing-coordinates.json"),
            ("combined_structural_admission_sha256", "combined-structural-admission.json"),
            ("combined_dataset_manifest_sha256", "combined-dataset-manifest.json"),
        ):
            if private_evidence[field] != _evidence_sha256_if_present(root_descriptor, key):
                raise Program013AuthorityError("Program 013 runtime evidence hash differs")
    elif result_kind in {"ADMISSION-FAILURE", "ADMISSION-PASS"}:
        _require_working_disk_capacity(root_descriptor)
        budget = _reconstruct_state(
            root_descriptor,
            predecessor_state,
            authority=authority,
            require_complete=True,
        )
        projection = _combined_projection(
            root_descriptor,
            predecessor_root,
            predecessor_state,
            authority,
            budget,
            canonical_file=None,
            loader=None,
        )
        evidence = _derived_admission_evidence(repository, authority, predecessor_state, projection)
        payloads = cast(Mapping[str, bytes], evidence["payloads"])
        for key, expected in payloads.items():
            if predecessor._read(root_descriptor, key) != expected:
                raise Program013AuthorityError("Program 013 derived evidence differs")
        if (
            _evidence_sha256(root_descriptor, "combined-canonical-raw.jsonl")
            != projection.canonical_sha256
        ):
            raise Program013AuthorityError("Program 013 combined canonical evidence differs")
        admission = _mapping(evidence.get("admission"), "structural admission")
        admission_passed = admission.get("admission_passed") is True
        expected_kind = "ADMISSION-PASS" if admission_passed else "ADMISSION-FAILURE"
        expected_lineage = evidence.get("public_lineage")
        expected_lineage_identity = (
            _mapping(expected_lineage, "public lineage").get("dataset_lineage_identity")
            if admission_passed
            else None
        )
        hashes = _mapping(evidence.get("hashes"), "derived hashes")
        if (
            result_kind != expected_kind
            or record.get("status") != admission.get("status")
            or record.get("structural_admission_evaluated") is not True
            or record.get("admission_passed") is not admission_passed
            or record.get("failure_class") is not None
            or record.get("failure_classification") is not None
            or record.get("public_dataset_lineage_manifest") != expected_lineage
            or record.get("dataset_lineage_identity") != expected_lineage_identity
            or record.get("private_dataset_identity") != evidence.get("private_dataset_identity")
            or record.get("provider_transport_attempted") is not True
            or private_evidence
            != {
                **hashes,
                "raw_row_count": projection.raw_row_count,
                "missing_coordinate_count": admission["missing_coordinate_count"],
                "excluded_full_session_count": admission["excluded_full_session_count"],
            }
        ):
            raise Program013AuthorityError("Program 013 admission terminal semantics differ")
        _validate_budget_counts(record, budget)
    else:
        raise Program013AuthorityError("Program 013 private terminal result kind differs")
    return record


def _validate_budget_counts(record: Mapping[str, Any], budget: _Budget) -> None:
    if (
        _count(record.get("cumulative_request_intents"), "cumulative request count")
        != budget.requests
        or _count(record.get("cumulative_responses"), "cumulative response count")
        != budget.responses
        or _count(record.get("cumulative_response_bytes"), "cumulative response bytes")
        != budget.response_bytes
    ):
        raise Program013AuthorityError("Program 013 terminal budget differs")


def _validate_runtime_failure_counts(
    record: Mapping[str, Any], counts: tuple[int, int, int]
) -> None:
    if (
        tuple(
            _count(record.get(field), "runtime failure count")
            for field in (
                "cumulative_request_intents",
                "cumulative_responses",
                "cumulative_response_bytes",
            )
        )
        != counts
    ):
        raise Program013AuthorityError("Program 013 terminal budget differs")


def _public_terminal_value(record: Mapping[str, Any]) -> dict[str, Any]:
    lineage = record["public_dataset_lineage_manifest"]
    if lineage is not None:
        _validate_public_lineage(lineage, record)
    value = {
        "schema_version": "program-013-exposed-prefix-terminal-result-v1",
        "terminal_result_id": _PUBLIC_TERMINAL_RESULT_ID,
        "program_ordinal": PROGRAM_ORDINAL,
        "program_id": PROGRAM_ID,
        "result_kind": record["result_kind"],
        "status": record["status"],
        "authority_id": record["authority_id"],
        "authority_fingerprint": record["authority_fingerprint"],
        "source_commit": record["source_commit"],
        "admission_passed": record["admission_passed"],
        "dataset_lineage_manifest": lineage,
        "privacy_assertions": dict(_PRIVACY_ASSERTIONS),
        "scientific_assertions": dict(_SCIENTIFIC_ASSERTIONS),
        "disabled_authority": dict(_DISABLED_AUTHORITY),
        "observed_at": record["observed_at"],
    }
    _validate_public_terminal_shape(value)
    return value


def _public_terminal_payload(record: Mapping[str, Any]) -> bytes:
    return (canonical_json(_public_terminal_value(record)) + "\n").encode()


def _publish_public_terminal(
    repository: Path,
    root_descriptor: int,
    predecessor_root: int,
    authority: Mapping[str, Any],
    predecessor_state: _PredecessorState,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    _revalidate_closeout_boundary(repository, predecessor_root, authority, predecessor_state)
    validated = _load_terminal_record(
        repository, root_descriptor, predecessor_root, authority, predecessor_state
    )
    if validated != record:
        raise Program013AuthorityError("Program 013 terminal changed before publication")
    payload = _public_terminal_payload(validated)
    _append_public_atomic(repository, root_descriptor, payload)
    return _json_object(payload, "public terminal")


def _append_public_atomic(repository: Path, root_descriptor: int, payload: bytes) -> None:
    public_descriptor = os.open(repository / PUBLIC_TERMINAL_PATH.parent, _DIRECTORY_FLAGS)
    try:
        try:
            existing_descriptor = os.open(
                PUBLIC_TERMINAL_PATH.name,
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
                raise Program013AuthorityError("Program 013 public terminal artifact differs")
            os.fsync(public_descriptor)
            return
        temp_key, temp_descriptor = predecessor._new_temp(root_descriptor, "public-terminal")
        try:
            with os.fdopen(temp_descriptor, "wb") as handle:
                if handle.write(payload) != len(payload):
                    raise Program013AuthorityError(
                        "Program 013 public terminal write was incomplete"
                    )
                handle.flush()
                os.fchmod(handle.fileno(), 0o644)
                os.fsync(handle.fileno())
            try:
                os.link(
                    temp_key,
                    PUBLIC_TERMINAL_PATH.name,
                    src_dir_fd=root_descriptor,
                    dst_dir_fd=public_descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError:
                raise Program013AuthorityError(
                    "Program 013 public terminal artifact already exists"
                ) from None
            os.fsync(public_descriptor)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temp_key, dir_fd=root_descriptor)
                os.fsync(root_descriptor)
    finally:
        os.close(public_descriptor)


def _recover_private_terminal_if_present(
    repository: Path,
    root_descriptor: int,
    predecessor_root: int,
    authority: Mapping[str, Any],
    predecessor_state: _PredecessorState,
) -> None:
    if predecessor._exists(root_descriptor, _TERMINAL_KEY):
        _validate_predecessor_manifest(root_descriptor, predecessor_state)
        _load_active(root_descriptor, authority)
        terminal = _load_terminal_record(
            repository, root_descriptor, predecessor_root, authority, predecessor_state
        )
        _publish_public_terminal(
            repository,
            root_descriptor,
            predecessor_root,
            authority,
            predecessor_state,
            terminal,
        )
        raise Program013AuthorityError("Program 013 acquisition is terminally sealed")
    if not _has_consumed_state(root_descriptor):
        return
    _validate_predecessor_manifest(root_descriptor, predecessor_state)
    _load_active(root_descriptor, authority)
    try:
        _reconstruct_state(root_descriptor, predecessor_state, authority=authority)
    except Exception as error:
        try:
            _seal_runtime_failure(
                repository,
                root_descriptor,
                predecessor_root,
                authority,
                predecessor_state,
                error,
            )
        except BaseException as persistence_error:
            raise Program013PostClaimPersistenceError(
                "Program 013 terminal persistence failed after possible transport"
            ) from persistence_error
        raise Program013AuthorityError("Program 013 acquisition is terminally sealed") from None


def _seal_runtime_failure(
    repository: Path,
    root_descriptor: int,
    predecessor_root: int,
    authority: Mapping[str, Any],
    predecessor_state: _PredecessorState,
    error: BaseException,
) -> None:
    _revalidate_closeout_boundary(repository, predecessor_root, authority, predecessor_state)
    predecessor._append_atomic(
        root_descriptor,
        _TERMINAL_KEY,
        _runtime_failure_payload(root_descriptor, predecessor_state, error, authority),
    )
    terminal = _load_terminal_record(
        repository, root_descriptor, predecessor_root, authority, predecessor_state
    )
    _publish_public_terminal(
        repository,
        root_descriptor,
        predecessor_root,
        authority,
        predecessor_state,
        terminal,
    )


def _reject_terminal_state(repository: Path) -> None:
    path = repository / PUBLIC_TERMINAL_PATH
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError as error:
        raise Program013AuthorityError("Program 013 terminal result artifact is absent") from error
    except OSError as error:
        raise Program013AuthorityError("Program 013 terminal result artifact is invalid") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 1_048_576:
            raise Program013AuthorityError("Program 013 terminal result artifact is invalid")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            raw = handle.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    value = _json_object(raw, "public terminal")
    if raw != (canonical_json(value) + "\n").encode():
        raise Program013AuthorityError("Program 013 public terminal is not canonical")
    _validate_public_terminal_shape(value)
    if hashlib.sha256(raw).hexdigest() != _PUBLIC_TERMINAL_SHA256:
        raise Program013AuthorityError("Program 013 terminal result semantics differ")
    raise Program013AuthorityError("Program 013 authority is terminally revoked")


def _validate_public_terminal_shape(value: Mapping[str, Any]) -> None:
    if (
        set(value) != _PUBLIC_TERMINAL_KEYS
        or value.get("schema_version") != "program-013-exposed-prefix-terminal-result-v1"
        or value.get("terminal_result_id") != _PUBLIC_TERMINAL_RESULT_ID
        or value.get("program_ordinal") != PROGRAM_ORDINAL
        or value.get("program_id") != PROGRAM_ID
        or value.get("authority_id") != CHILD_AUTHORITY_ID
        or _HEX_64.fullmatch(str(value.get("authority_fingerprint"))) is None
        or _HEX_40.fullmatch(str(value.get("source_commit"))) is None
        or value.get("privacy_assertions") != _PRIVACY_ASSERTIONS
        or value.get("scientific_assertions") != _SCIENTIFIC_ASSERTIONS
        or value.get("disabled_authority") != _DISABLED_AUTHORITY
        or type(value.get("admission_passed")) is not bool
    ):
        raise Program013AuthorityError("Program 013 public terminal schema differs")
    predecessor._parse_observed_at(value.get("observed_at"))
    result_kind = value.get("result_kind")
    if result_kind == "RUNTIME-FAILURE":
        expected_status = "FAIL-CONSUMED-NO-RETRY"
        expected_admission = False
    elif result_kind == "ADMISSION-FAILURE":
        expected_status = "TERMINAL-FAIL-CONSUMED-NO-RETRY"
        expected_admission = False
    elif result_kind == "ADMISSION-PASS":
        expected_status = "ADMITTED-PROGRAM-013-RAW-STRUCTURAL-PREFIX"
        expected_admission = True
    else:
        raise Program013AuthorityError("Program 013 public terminal result kind differs")
    if (
        value.get("status") != expected_status
        or value.get("admission_passed") is not expected_admission
    ):
        raise Program013AuthorityError("Program 013 public terminal branch differs")
    lineage = value.get("dataset_lineage_manifest")
    if expected_admission:
        _validate_public_lineage(lineage, value)
    elif lineage is not None:
        raise Program013AuthorityError("Program 013 failure terminal publishes lineage")


def _validate_public_lineage(value: Any, terminal: Mapping[str, Any]) -> dict[str, Any]:
    lineage = _exact_object(value, _PUBLIC_LINEAGE_KEYS, "public dataset lineage")
    if (
        lineage.get("schema_version")
        != "program-013-public-raw-structural-prefix-lineage-manifest-v1"
        or lineage.get("program_id") != PROGRAM_ID
        or lineage.get("authority_id") != terminal.get("authority_id")
        or lineage.get("authority_fingerprint") != terminal.get("authority_fingerprint")
        or lineage.get("source_commit") != terminal.get("source_commit")
        or lineage.get("status") != "ADMITTED-PROGRAM-013-RAW-STRUCTURAL-PREFIX"
        or _HEX_64.fullmatch(str(lineage.get("dataset_lineage_identity"))) is None
    ):
        raise Program013AuthorityError("Program 013 public dataset lineage differs")
    return lineage


def _exact_object(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise Program013AuthorityError(f"Program 013 {label} schema differs")
    return cast(dict[str, Any], value)


def _evidence_sha256_if_present(root_descriptor: int, key: str) -> str | None:
    return (
        _evidence_sha256(root_descriptor, key)
        if predecessor._exists(root_descriptor, key)
        else None
    )


def _evidence_sha256(root_descriptor: int, key: str) -> str:
    if _EVIDENCE_KEY.fullmatch(key) is None:
        raise Program013AuthorityError("Program 013 evidence key is invalid")
    try:
        descriptor = os.open(
            key,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_descriptor,
        )
    except OSError as error:
        raise Program013AuthorityError(f"Program 013 evidence is absent: {key}") from error
    with os.fdopen(descriptor, "rb") as handle:
        metadata = os.fstat(handle.fileno())
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise Program013AuthorityError("Program 013 evidence is not private")
        digest = hashlib.sha256()
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
        return digest.hexdigest()


def _publish_temp_or_validate(
    root_descriptor: int, temp_key: str, final_key: str, expected_sha256: str
) -> None:
    if predecessor._exists(root_descriptor, final_key):
        if _evidence_sha256(root_descriptor, final_key) != expected_sha256:
            raise Program013AuthorityError("Program 013 canonical raw dataset differs")
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
            raise Program013AuthorityError("Program 013 canonical raw publish raced") from None
        os.fsync(root_descriptor)
    os.unlink(temp_key, dir_fd=root_descriptor)
    os.fsync(root_descriptor)


def _has_consumed_state(root_descriptor: int) -> bool:
    for entry in os.listdir(root_descriptor):
        if (
            entry == "claim.json"
            or entry in _DERIVED_KEYS
            or _PAGE_KEY.fullmatch(entry)
            or _CREDENTIAL_KEY.fullmatch(entry)
        ):
            return True
    return False


def _derive_predecessor_state(
    repository: Path,
    root_descriptor: int,
    authority: Mapping[str, Any],
) -> _PredecessorState:
    proposal = validate_operation_contract(repository, commit=_authority_commit(authority))
    terminal_binding = _mapping(
        _mapping(proposal.get("predecessor"), "predecessor bindings").get(
            "program_012_terminal_result"
        ),
        "Program 012 public terminal binding",
    )
    public_terminal = _load_bound(
        repository,
        terminal_binding,
        "terminal_fingerprint",
        commit=_authority_commit(authority),
        fingerprint_optional=True,
    )
    active_raw = predecessor._read(root_descriptor, "active-authority.json")
    active = _json_object(active_raw, "Program 012 active authority")
    if active_raw != (canonical_json(active) + "\n").encode():
        raise Program013AuthorityError("Program 012 active authority is not canonical")
    unsigned_active = dict(active)
    active_fingerprint = unsigned_active.pop("authority_fingerprint", None)
    control_lineage = _mapping(active.get("control_lineage"), "Program 012 control lineage")
    source_commit = str(control_lineage.get("runtime_source_commit"))
    if (
        active.get("schema_version") != "program-012-raw-sip-acquisition-active-authority-v1"
        or active.get("status") != "ACTIVE-ONE-USE-RECOVERABLE"
        or active.get("authority_id") != predecessor.CHILD_AUTHORITY_ID
        or active.get("program_id") != predecessor.PROGRAM_ID
        or active.get("operation_manifest") != predecessor.OPERATION_MANIFEST
        or active_fingerprint != fingerprint(unsigned_active)
        or public_terminal.get("authority_fingerprint") != active_fingerprint
        or public_terminal.get("source_commit") != source_commit
        or _HEX_40.fullmatch(source_commit) is None
    ):
        raise Program013AuthorityError("Program 012 active authority binding differs")
    try:
        terminal_key, private_terminal = predecessor._load_terminal_record(
            root_descriptor, active, source_commit
        )
    except predecessor.Program012AuthorityError as error:
        raise Program013AuthorityError(str(error)) from None
    if (
        terminal_key != "terminal-failure.json"
        or private_terminal.get("status") != "FAIL-CONSUMED-NO-RETRY"
        or private_terminal.get("admission_passed") is not False
    ):
        raise Program013AuthorityError("Program 012 terminal disposition differs")

    requests = science.acquisition_requests()
    page_entries = {
        entry for entry in os.listdir(root_descriptor) if predecessor._PAGE_KEY.fullmatch(entry)
    }
    budget = predecessor._Budget()
    completed_sessions: list[dict[str, Any]] = []
    frontier: dict[str, Any] | None = None
    frontier_request_index = -1
    for request_index, request in enumerate(requests):
        session_entries = {
            entry for entry in page_entries if entry.startswith(f"session-{request.session}-")
        }
        if frontier is not None:
            if session_entries:
                raise Program013AuthorityError("Program 012 evidence continues after frontier")
            continue
        source = predecessor._ReplaySource(root_descriptor, request, active, source_commit, budget)
        before_requests = budget.requests
        before_responses = budget.responses
        before_bytes = budget.response_bytes
        try:
            result = predecessor._execute_session(request, source)
        except predecessor._IncompletePageCheckpoint:
            intent = program_011.PageIntent(request.identity, 1, request.url(), None)
            prefix = predecessor._page_prefix(request, 1)
            if session_entries != {f"{prefix}.intent.json"}:
                raise Program013AuthorityError("Program 012 frontier checkpoint differs") from None
            frontier = {
                "session": request.session.isoformat(),
                "page_index": 1,
                "request_identity": request.identity,
                "incoming_page_token": None,
                "url": intent.url,
                "intent_sha256": hashlib.sha256(
                    predecessor._read(root_descriptor, f"{prefix}.intent.json")
                ).hexdigest(),
                "body_present": False,
                "receipt_present": False,
                "later_evidence_present": False,
            }
            frontier_request_index = request_index
        except (predecessor._TransportRequired, predecessor.Program012AuthorityError) as error:
            raise Program013AuthorityError(
                "Program 012 evidence is not the reviewed first-page intent-only frontier"
            ) from error
        except program_011.Program011Error as error:
            raise Program013AuthorityError(
                "Program 012 completed prefix does not reparse"
            ) from error
        else:
            expected_entries = predecessor._expected_session_entries(request, len(result.pages))
            if session_entries != expected_entries:
                raise Program013AuthorityError("Program 012 completed session evidence differs")
            pages = []
            for page in result.pages:
                prefix = predecessor._page_prefix(request, page.page_index)
                pages.append(
                    {
                        "page_index": page.page_index,
                        "intent_sha256": hashlib.sha256(
                            predecessor._read(root_descriptor, f"{prefix}.intent.json")
                        ).hexdigest(),
                        "body_sha256": hashlib.sha256(
                            predecessor._read(root_descriptor, f"{prefix}.body")
                        ).hexdigest(),
                        "receipt_sha256": hashlib.sha256(
                            predecessor._read(root_descriptor, f"{prefix}.receipt.json")
                        ).hexdigest(),
                        "response_bytes": page.response_bytes,
                    }
                )
            completed_sessions.append(
                {
                    "session": request.session.isoformat(),
                    "request_identity": request.identity,
                    "page_count": budget.responses - before_responses,
                    "response_bytes": budget.response_bytes - before_bytes,
                    "pages": pages,
                }
            )
            if budget.requests - before_requests != len(result.pages):
                raise Program013AuthorityError("Program 012 completed request count differs")
    if frontier is None or frontier_request_index < 0 or not completed_sessions:
        raise Program013AuthorityError("Program 012 reviewed recovery frontier is absent")
    runtime = _mapping(authority.get("runtime_binding"), "runtime binding")
    unsigned_manifest: dict[str, Any] = {
        "schema_version": "program-013-private-predecessor-import-manifest-v1",
        "program_id": PROGRAM_ID,
        "operation_manifest": OPERATION_MANIFEST,
        "child_authority_id": authority["authority_id"],
        "child_authority_fingerprint": authority["authority_fingerprint"],
        "runtime_binding": dict(runtime),
        "program_012_public_terminal": dict(terminal_binding),
        "program_012_active_authority_fingerprint": active_fingerprint,
        "program_012_source_commit": source_commit,
        "program_012_private_terminal_fingerprint": private_terminal["terminal_fingerprint"],
        "completed_sessions": completed_sessions,
        "completed_request_count": budget.responses,
        "completed_response_count": budget.responses,
        "completed_response_bytes": budget.response_bytes,
        "frontier": frontier,
        "no_later_evidence": True,
    }
    manifest = {**unsigned_manifest, "manifest_fingerprint": fingerprint(unsigned_manifest)}
    payload = (canonical_json(manifest) + "\n").encode()
    return _PredecessorState(
        manifest=manifest,
        payload=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        active_authority=active,
        source_commit=source_commit,
        frontier_request_index=frontier_request_index,
        latest_response_at=budget.latest_response_at,
    )


def _validate_predecessor_manifest(root_descriptor: int, expected: _PredecessorState) -> None:
    if predecessor._read(root_descriptor, "predecessor-import-manifest.json") != expected.payload:
        raise Program013AuthorityError("Program 013 predecessor import manifest differs")


def _append_atomic_or_validate(root_descriptor: int, key: str, payload: bytes) -> None:
    if predecessor._exists(root_descriptor, key):
        if predecessor._read(root_descriptor, key) != payload:
            raise Program013AuthorityError(f"Program 013 derived evidence differs: {key}")
        return
    try:
        predecessor._append_atomic(root_descriptor, key, payload)
    except predecessor.Program012AuthorityError as error:
        raise Program013AuthorityError(str(error).replace("Program 012", "Program 013")) from None


def _load_active(root_descriptor: int, expected: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = predecessor._read(root_descriptor, "active-authority.json")
    value = _json_object(raw, "active authority")
    if value != expected or raw != (canonical_json(expected) + "\n").encode():
        raise Program013AuthorityError("Program 013 active authority differs")
    return value


def _repository_preflight(repository: Path, identity: Mapping[str, Any]) -> dict[str, str]:
    runtime = _mapping(identity.get("runtime_binding"), "runtime binding")
    source_commit = str(runtime.get("source_commit"))
    expected_changes = {
        f"A\t{CHILD_AUTHORITY_PATH.as_posix()}",
        f"A\t{CHILD_REVIEW_PATH.as_posix()}",
    }
    environment = _git_environment()
    command = git_controls._git_command(repository)

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
        raise Program013AuthorityError("Program 013 repository identity is unavailable") from error
    if (
        dirty not in ([], [f"?? {PUBLIC_TERMINAL_PATH.as_posix()}"])
        or head != main
        or head != origin_main
        or source_tree != runtime.get("source_tree")
        or ancestor.returncode != 0
        or set(changed) != expected_changes
    ):
        raise Program013AuthorityError("Program 013 reviewed synchronized-main lineage differs")
    return {
        "runtime_source_commit": source_commit,
        "runtime_source_tree": source_tree,
        "runtime_implementation_root": str(runtime["implementation_root"]),
        "synchronized_main_commit": head,
    }


def _authority_commit(authority: Mapping[str, Any]) -> str:
    value = str(
        _mapping(authority.get("control_lineage"), "control lineage").get(
            "synchronized_main_commit"
        )
    )
    if _HEX_40.fullmatch(value) is None:
        raise Program013AuthorityError("Program 013 authority policy commit differs")
    return value


def _source_commit(authority: Mapping[str, Any]) -> str:
    value = str(_mapping(authority.get("runtime_binding"), "runtime binding").get("source_commit"))
    if _HEX_40.fullmatch(value) is None:
        raise Program013AuthorityError("Program 013 runtime source commit differs")
    return value


def _require_credentials_present(environ: Mapping[str, str] | None) -> None:
    missing = credential_contract.credential_presence_preflight(environ)
    if missing:
        raise Program013AuthorityError("Program 013 credentials missing: " + ", ".join(missing))


def _load_bound(
    repository: Path,
    binding: Mapping[str, Any],
    fingerprint_field: str,
    *,
    commit: str | None = None,
    fingerprint_optional: bool = False,
) -> Mapping[str, Any]:
    try:
        value = git_controls._load_bound_artifact(
            repository,
            binding,
            fingerprint_field,
            commit=commit,
        )
    except git_controls.Program011AuthorityError as error:
        if not fingerprint_optional:
            raise Program013AuthorityError(
                str(error).replace("Program 011", "Program 013")
            ) from None
        path = Path(str(binding.get("path")))
        raw = _git(repository, "show", f"{commit or 'HEAD'}:{path.as_posix()}")
        if hashlib.sha256(raw).hexdigest() != binding.get("sha256"):
            raise Program013AuthorityError("Program 013 bound artifact differs") from None
        value = _json_object(raw, "bound artifact")
    return value


def _open_root(repository: Path, root: Path, *, create: bool) -> int:
    descriptor = os.open(_repository(repository), _DIRECTORY_FLAGS)
    try:
        for part in root.parts:
            if create:
                with suppress(FileExistsError):
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
            try:
                child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            except FileNotFoundError as error:
                raise Program013AuthorityError(
                    "Program 013 private evidence root is absent"
                ) from error
            os.close(descriptor)
            descriptor = child
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise Program013AuthorityError("Program 013 private evidence root is not private")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _repository(repository: Path) -> Path:
    if not isinstance(repository, Path):
        raise Program013AuthorityError("Program 013 repository root is invalid")
    resolved = repository.resolve()
    if not resolved.is_dir():
        raise Program013AuthorityError("Program 013 repository root is absent")
    return resolved


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Program013AuthorityError(f"Program 013 {label} is invalid")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise Program013AuthorityError(f"Program 013 {label} is invalid")
    return value


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Program013AuthorityError(f"Program 013 {label} is invalid JSON") from error
    if type(value) is not dict:
        raise Program013AuthorityError(f"Program 013 {label} is not an object")
    return value


def _git(repository: Path, *arguments: str) -> bytes:
    try:
        return subprocess.run(
            (*git_controls._git_command(repository), *arguments),
            check=True,
            capture_output=True,
            env=_git_environment(),
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise Program013AuthorityError("Program 013 Git identity is unavailable") from error


def _git_environment() -> dict[str, str]:
    environment = non_broker_subprocess_environment()
    environment.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    return environment
