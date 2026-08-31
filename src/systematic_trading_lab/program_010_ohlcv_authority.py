"""Reviewed one-use runtime for Program 010 raw Alpaca SIP OHLCV."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime
from http.client import HTTPException
from pathlib import Path
from typing import Any, BinaryIO, cast
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from . import program_005_alpaca as transport_support
from . import program_006_alpaca as credential_contract
from . import program_007_alpaca as raw_contract
from . import program_010_ohlcv as program_010
from .config import non_broker_subprocess_environment
from .fingerprints import canonical_json, fingerprint
from .standing_research_authority import derive_child_identity

PROGRAM_ID = program_010.PROGRAM_ID
PROGRAM_ORDINAL = program_010.PROGRAM_ORDINAL
CHILD_AUTHORITY_ID = "program-010-raw-alpaca-sip-ohlcv-structural-qualification-child-2026-08-30-v1"
CONSUMPTION_BOUNDARY = "immediately before first provider transport invocation"
PRIVATE_ROOT = Path(".trading-lab/program-010-raw-alpaca-sip-ohlcv-v1")
CREDENTIAL_NAMES = credential_contract._CREDENTIAL_NAMES
PROTECTED_CHRONOLOGY_PATH = Path("config/research/standing-protected-chronology-v1.json")
PROTECTED_CHRONOLOGY_SOURCE_PATHS = (
    Path("config/research/program-005-free-alpaca-successor-plan-v1.json"),
    Path("config/research/rapid-004-seed-universe-v1.json"),
    Path("config/research/intraday-known-exposures-v1.json"),
    Path("config/research/intraday-exposed-002-june-reservation-v1.json"),
    Path("config/research/intraday-v3-period-selection-v2.json"),
)

CHILD_AUTHORITY_PATH = Path(
    "config/research/program-010-raw-alpaca-sip-ohlcv-structural-qualification-"
    "child-authority-v1.json"
)
CHILD_REVIEW_PATH = Path(
    "config/research/program-010-raw-alpaca-sip-ohlcv-structural-qualification-"
    "child-authority-independent-review-v1.json"
)
OPERATION_MANIFEST = {
    "path": (
        "config/research/program-010-raw-alpaca-sip-ohlcv-structural-qualification-proposal-v5.json"
    ),
    "sha256": "449327a5843902f4a93603ff0f3fd7f01665baf33561ba3d019fde4612acc1f5",
    "fingerprint": "fe24131e1dcd504615a314221d3aec664a0f2c3810127ba69fbceb50f81727a7",
}
_PROGRAM_007_PROPOSAL = {
    "path": "config/research/program-007-alpaca-raw-source-qualification-proposal-v1.json",
    "sha256": "5e92effb829e70d7bbf4636d88519c104565a10bd6f57235169419542cb05b34",
    "fingerprint": "d0ec31e7b6947ed6fe3e1118a6f5536daddae34ebbe9dffcc3b3f932dd9d41c0",
}
_ENABLED_AUTHORITY = {
    "provider_contact",
    "credential_access",
    "source_requests",
    "source_qualification",
}
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_EVIDENCE_KEY = re.compile(r"[a-z0-9][a-z0-9.-]*")


class Program010AuthorityError(ValueError):
    """Fail-closed Program 010 runtime or authority error."""


class Program010PostClaimPersistenceError(Program010AuthorityError):
    """Terminal evidence could not be persisted after the one-use claim."""


@dataclass(frozen=True)
class QualificationExecution:
    result: program_010.QualificationResult
    request_count: int
    response_count: int
    response_bytes: int
    response_manifest_sha256: str
    missing_inventory_sha256: str

    def public_summary(self) -> dict[str, object]:
        sessions = [
            {
                "session": item.request.session.isoformat(),
                "status": item.status,
                "page_count": len(item.pages),
                "raw_row_count": len(item.rows),
                "expected_canonical_coordinate_count": len(item.request.expected_coordinates),
                "source_missing_coordinate_count": len(item.missingness.source_missing),
                "unobserved_coordinate_count": len(item.missingness.unobserved),
            }
            for item in self.result.sessions
        ]
        return {
            "program_id": PROGRAM_ID,
            "status": self.result.status,
            "session_count": len(self.result.sessions),
            "request_count": self.request_count,
            "response_count": self.response_count,
            "response_bytes": self.response_bytes,
            "raw_row_count": sum(len(item.rows) for item in self.result.sessions),
            "expected_canonical_coordinate_count": sum(
                len(item.request.expected_coordinates) for item in self.result.sessions
            ),
            "source_missing_coordinate_count": sum(
                len(item.missingness.source_missing) for item in self.result.sessions
            ),
            "unobserved_coordinate_count": sum(
                len(item.missingness.unobserved) for item in self.result.sessions
            ),
            "exact_missing_coordinates_private": True,
            "response_manifest_sha256": self.response_manifest_sha256,
            "automatic_retries": 0,
            "dataset_admitted": False,
            "strategy_calculations": 0,
            "strategy_returns": 0,
            "sessions": sessions,
        }


def credential_presence(environ: Mapping[str, str] | None = None) -> Mapping[str, bool]:
    """Return names and presence only; never expose credential values."""
    return credential_contract.credential_presence(environ)


def credential_presence_preflight(
    environ: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    return credential_contract.credential_presence_preflight(environ)


def read_credentials(environ: Mapping[str, str] | None = None) -> tuple[str, str]:
    values = os.environ if environ is None else environ
    credentials = tuple(values.get(name, "").strip() for name in CREDENTIAL_NAMES)
    if any(not value or "\r" in value or "\n" in value for value in credentials):
        raise Program010AuthorityError("Program 010 OHLCV credentials are required")
    return credentials[0], credentials[1]


def validate_operation_contract(repository: Path) -> Mapping[str, Any]:
    """Revalidate the frozen qualification and its exact exposed chronology."""
    repository = _repository(repository)
    proposal = _load_bound_artifact(repository, OPERATION_MANIFEST, "proposal_fingerprint")
    predecessor = _load_bound_artifact(repository, _PROGRAM_007_PROPOSAL, "proposal_fingerprint")
    bindings = _mapping(proposal.get("bindings"), "operation bindings")
    terminal = _load_bound_artifact(
        repository,
        _mapping(bindings.get("program_009_terminal_failure"), "Program 009 terminal binding"),
        "failure_fingerprint",
    )
    metadata = _load_bound_artifact(
        repository,
        _mapping(bindings.get("program_008_terminal_success"), "Program 008 terminal binding"),
        "success_fingerprint",
    )
    ledger = _load_bound_artifact(
        repository,
        _mapping(bindings.get("public_unit_changing_action_ledger"), "action ledger binding"),
        "ledger_fingerprint",
    )
    raw_contract.require_action_ledger_admission(ledger)
    _validate_split_controls(ledger)
    _validate_chronology(repository, proposal, predecessor, terminal)

    source = _mapping(proposal.get("source_contract"), "source contract")
    pagination = _mapping(proposal.get("pagination_contract"), "pagination contract")
    qualification = _mapping(proposal.get("qualification_contract"), "qualification contract")
    budgets = _mapping(proposal.get("budgets"), "qualification budgets")
    authority = _mapping(proposal.get("authority"), "proposal authority")
    protected = _mapping(proposal.get("protected_firewall"), "protected firewall")
    metadata_results = _mapping(metadata.get("structural_results"), "Program 008 results")
    metadata_disposition = _mapping(metadata.get("disposition"), "Program 008 disposition")
    expected_coordinates = sum(
        len(request.expected_coordinates) for request in program_010.qualification_requests()
    )
    if (
        proposal.get("program_ordinal") != PROGRAM_ORDINAL
        or proposal.get("program_id") != PROGRAM_ID
        or proposal.get("status") != program_010.STATUS
        or proposal.get("proposal_fingerprint") != OPERATION_MANIFEST["fingerprint"]
        or source.get("method") != "GET"
        or source.get("endpoint") != program_010.ENDPOINT
        or source.get("feed") != "sip"
        or source.get("timeframe") != "5Min"
        or source.get("adjustment") != "raw"
        or source.get("sort") != "asc"
        or source.get("limit") != program_010.PAGE_ROW_LIMIT
        or source.get("asof") != "2026-07-31"
        or source.get("automatic_retries") != 0
        or pagination.get("terminal_condition") != "next_page_token is null"
        or pagination.get("maximum_pages_per_session") != program_010.MAXIMUM_PAGES_PER_SESSION
        or pagination.get("raw_body_fsynced_before_parse_or_continuation") is not True
        or qualification.get("imputation_allowed") is not False
        or qualification.get("normal_session_minimum_coordinates_per_symbol") != 40
        or qualification.get("early_close_minimum_coordinates_per_symbol") != 22
        or budgets.get("qualification_maximum_requests_and_responses")
        != program_010.MAXIMUM_QUALIFICATION_REQUESTS
        or budgets.get("maximum_response_page_bytes") != program_010.MAXIMUM_RESPONSE_PAGE_BYTES
        or budgets.get("maximum_session_response_bytes")
        != program_010.MAXIMUM_SESSION_RESPONSE_BYTES
        or budgets.get("maximum_qualification_response_bytes")
        != program_010.MAXIMUM_QUALIFICATION_RESPONSE_BYTES
        or budgets.get("automatic_retries") != 0
        or expected_coordinates != 4_602
        or any(authority.values())
        or any(protected.values())
        or metadata.get("status") != "TERMINAL-PASS-CONSUMED-NO-REPLAY"
        or metadata_results.get("metadata_qualification") != "PASS"
        or metadata_disposition.get("metadata_replay_allowed") is not False
    ):
        raise Program010AuthorityError("Program 010 operation contract differs")
    return proposal


def derive_active_authority(
    repository: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Mapping[str, Any]:
    """Derive the concrete active record from the reviewed standing child."""
    repository = _repository(repository)
    identity = derive_child_identity(repository, CHILD_AUTHORITY_PATH, CHILD_REVIEW_PATH)
    validate_operation_contract(repository)
    lineage = _repository_preflight(repository, identity)
    authority = _mapping(identity.get("authority"), "child authority")
    runtime = _mapping(identity.get("runtime_binding"), "child runtime binding")
    source_paths = {
        str(_mapping(item, "child runtime source file").get("path"))
        for item in _sequence(runtime.get("source_files"), "child runtime source files")
    }
    required_protected_paths = {
        PROTECTED_CHRONOLOGY_PATH.as_posix(),
        *(path.as_posix() for path in PROTECTED_CHRONOLOGY_SOURCE_PATHS),
    }
    if (
        identity.get("child_authority_id") != CHILD_AUTHORITY_ID
        or identity.get("program_ordinal") != PROGRAM_ORDINAL
        or identity.get("program_id") != PROGRAM_ID
        or identity.get("operation_manifest") != OPERATION_MANIFEST
        or identity.get("runtime_entrypoint")
        != "src/systematic_trading_lab/program_010_ohlcv_authority.py"
        or not required_protected_paths <= source_paths
        or {key for key, value in authority.items() if value} != _ENABLED_AUTHORITY
    ):
        raise Program010AuthorityError("Program 010 reviewed child identity differs")
    _require_credentials_present(environ)
    unsigned: dict[str, Any] = {
        "schema_version": "program-010-raw-sip-qualification-active-authority-v1",
        "status": "ACTIVE-ONE-USE",
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
    return {**unsigned, "authority_fingerprint": fingerprint(unsigned)}


def activate_authority(
    repository: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Mapping[str, Any]:
    repository = _repository(repository)
    authority = derive_active_authority(repository, environ=environ)
    root_descriptor = _open_private_root(repository, create=True)
    try:
        with _LockedRoot(root_descriptor):
            _reject_existing_state(root_descriptor, allow_active=False)
            authority = derive_active_authority(repository, environ=environ)
            _require_credentials_present(environ)
            _append_persistent_evidence(
                root_descriptor,
                "active-authority.json",
                (canonical_json(authority) + "\n").encode(),
            )
    finally:
        os.close(root_descriptor)
    return authority


def load_active_authority(
    repository: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Mapping[str, Any]:
    repository = _repository(repository)
    expected = derive_active_authority(repository, environ=environ)
    root_descriptor = _open_private_root(repository, create=False)
    try:
        return _load_active_from_descriptor(root_descriptor, expected)
    finally:
        os.close(root_descriptor)


def execute_qualification(
    repository: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> QualificationExecution:
    """Consume the reviewed child once and run the real fixed transport."""
    return _execute_qualification(repository, environ=environ, mock_transport=None)


def _execute_mock_qualification(
    repository: Path,
    *,
    environ: Mapping[str, str],
    transport: MockBarsTransport,
) -> QualificationExecution:
    if type(transport) is not MockBarsTransport or environ is os.environ:
        raise Program010AuthorityError("Program 010 test execution requires explicit finite inputs")
    return _execute_qualification(repository, environ=environ, mock_transport=transport)


def _execute_qualification(
    repository: Path,
    *,
    environ: Mapping[str, str] | None,
    mock_transport: MockBarsTransport | None,
) -> QualificationExecution:
    repository = _repository(repository)
    _require_credentials_present(environ)
    expected_authority = derive_active_authority(repository, environ=environ)
    root_descriptor = _open_private_root(repository, create=False)
    claim_written = False
    budget = _Budget()
    try:
        with _LockedRoot(root_descriptor):
            _reject_existing_state(root_descriptor)
            authority = derive_active_authority(repository, environ=environ)
            if authority != expected_authority:
                raise Program010AuthorityError("Program 010 authority changed under lock")
            _load_active_from_descriptor(root_descriptor, authority)
            validate_operation_contract(repository)
            _require_credentials_present(environ)
            key_id, secret_key = read_credentials(environ)
            client = _AlpacaBarsClient(key_id, secret_key) if mock_transport is None else None

            def writer(key: str, payload: bytes) -> None:
                _append_persistent_evidence(root_descriptor, key, payload)

            def consume() -> None:
                nonlocal claim_written
                if claim_written:
                    return
                writer(
                    "claim.json",
                    canonical_json(
                        {
                            "schema_version": "program-010-private-ohlcv-claim-v1",
                            "authority_id": authority["authority_id"],
                            "authority_fingerprint": authority["authority_fingerprint"],
                            "child_identity_fingerprint": authority["child_identity_fingerprint"],
                            "operation_manifest": OPERATION_MANIFEST,
                            "consumption_boundary": CONSUMPTION_BOUNDARY,
                            "scientific_use_consumed": True,
                            "terminal_fallback": {
                                "applies_without_valid_pass_receipt": True,
                                "status": "FAIL-CONSUMED-NO-RETRY",
                                "provider_transport_outcome": "AMBIGUOUS",
                                "retry_allowed": False,
                            },
                        }
                    ).encode(),
                )
                claim_written = True

            def response_for(intent: program_010.PageIntent) -> raw_contract.RawResponse:
                if mock_transport is not None:
                    consume()
                    return mock_transport.get(intent)
                assert client is not None
                return client.get(intent, consume)

            try:
                session_results: list[program_010.SessionResult] = []
                for request in program_010.qualification_requests():
                    source = _PersistentSessionSource(request, budget, response_for, writer)
                    try:
                        session_results.append(
                            program_010._execute_synthetic_session(
                                request, cast(program_010.SyntheticSessionSource, source)
                            )
                        )
                    finally:
                        source.close()
                result = program_010.QualificationResult(tuple(session_results))
                if mock_transport is not None:
                    mock_transport.require_exhausted()
                if (
                    budget.requests != budget.responses
                    or budget.requests > program_010.MAXIMUM_QUALIFICATION_REQUESTS
                    or sum(len(item.request.expected_coordinates) for item in result.sessions)
                    != 4_602
                    or any(item.missingness.unobserved for item in result.sessions)
                ):
                    raise Program010AuthorityError("Program 010 qualification result differs")

                missing_payload = (
                    canonical_json(
                        {
                            "schema_version": "program-010-private-missing-coordinates-v1",
                            "program_id": PROGRAM_ID,
                            "sessions": [
                                {
                                    "session": item.request.session.isoformat(),
                                    "source_missing_coordinates": [
                                        f"{symbol}@{_iso_utc(timestamp)}"
                                        for symbol, timestamp in item.missingness.source_missing
                                    ],
                                    "unobserved_coordinates": [
                                        f"{symbol}@{_iso_utc(timestamp)}"
                                        for symbol, timestamp in item.missingness.unobserved
                                    ],
                                }
                                for item in result.sessions
                            ],
                        }
                    )
                    + "\n"
                ).encode()
                writer("missing-coordinates.json", missing_payload)
                missing_sha = hashlib.sha256(missing_payload).hexdigest()
                manifest_payload = (
                    canonical_json(
                        {
                            "schema_version": "program-010-private-response-manifest-v1",
                            "program_id": PROGRAM_ID,
                            "request_count": budget.requests,
                            "response_count": budget.responses,
                            "response_bytes": budget.response_bytes,
                            "pages": budget.pages,
                            "credentials_stored": False,
                        }
                    )
                    + "\n"
                ).encode()
                writer("response-manifest.json", manifest_payload)
                manifest_sha = hashlib.sha256(manifest_payload).hexdigest()
                execution = QualificationExecution(
                    result,
                    budget.requests,
                    budget.responses,
                    budget.response_bytes,
                    manifest_sha,
                    missing_sha,
                )
                receipt_payload = (
                    canonical_json(
                        {
                            "schema_version": "program-010-private-ohlcv-receipt-v1",
                            "status": "STRUCTURAL-QUALIFICATION-PASS",
                            "authority_id": authority["authority_id"],
                            **execution.public_summary(),
                            "missing_inventory_sha256": missing_sha,
                            "credential_loads": 1,
                            "credentials_stored": False,
                            "observed_at": _utc_now(),
                        }
                    )
                    + "\n"
                ).encode()
                writer("qualification-receipt.json", receipt_payload)
                return execution
            except Exception as error:
                if claim_written:
                    try:
                        writer(
                            "terminal-failure.json",
                            (
                                canonical_json(
                                    {
                                        "schema_version": "program-010-private-ohlcv-failure-v1",
                                        "status": "FAIL-CONSUMED-NO-RETRY",
                                        "failure_class": type(error).__name__,
                                        "failure_classification": getattr(
                                            error, "classification", type(error).__name__
                                        ),
                                        "provider_transport_attempted": True,
                                        "scientific_use_consumed": True,
                                        "completed_requests": budget.requests,
                                        "completed_responses": budget.responses,
                                        "completed_response_bytes": budget.response_bytes,
                                        "automatic_retries": 0,
                                        "dataset_admitted": False,
                                        "strategy_calculations": 0,
                                        "strategy_returns": 0,
                                        "credentials_stored": False,
                                        "observed_at": _utc_now(),
                                    }
                                )
                                + "\n"
                            ).encode(),
                        )
                    except Exception as persistence_error:
                        raise Program010PostClaimPersistenceError(
                            "Program 010 terminal persistence failed after "
                            f"{type(error).__name__}; the claim fallback seals "
                            "FAIL-CONSUMED-NO-RETRY"
                        ) from persistence_error
                raise
    finally:
        os.close(root_descriptor)


class MockBarsTransport:
    """Finite canned responses for lifecycle tests."""

    __slots__ = ("_intents", "_responses")

    def __init__(self, responses: Sequence[raw_contract.RawResponse]) -> None:
        if (
            type(responses) not in {list, tuple}
            or not 1 <= len(responses) <= program_010.MAXIMUM_QUALIFICATION_REQUESTS
            or any(type(response) is not raw_contract.RawResponse for response in responses)
        ):
            raise Program010AuthorityError("Program 010 mock responses are invalid")
        self._responses = tuple(responses)
        self._intents: list[program_010.PageIntent] = []

    @property
    def intents(self) -> tuple[program_010.PageIntent, ...]:
        return tuple(self._intents)

    def get(self, intent: program_010.PageIntent) -> raw_contract.RawResponse:
        if type(intent) is not program_010.PageIntent:
            raise Program010AuthorityError("Program 010 mock intent is invalid")
        index = len(self._intents)
        self._intents.append(intent)
        if index >= len(self._responses):
            raise Program010AuthorityError("Program 010 mock response is missing")
        return self._responses[index]

    def require_exhausted(self) -> None:
        if len(self._intents) != len(self._responses):
            raise Program010AuthorityError("Program 010 mock responses remain unused")


class _AlpacaBarsClient:
    __slots__ = ("_headers", "_opener", "_pace")

    def __init__(
        self,
        key_id: str,
        secret_key: str,
        *,
        pace: Callable[[], None] | None = None,
    ) -> None:
        if any(not value or "\r" in value or "\n" in value for value in (key_id, secret_key)):
            raise Program010AuthorityError("Program 010 OHLCV credentials are invalid")
        self._headers = {
            "Accept": "application/json",
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
        }
        self._opener = build_opener(ProxyHandler({}), transport_support._NoRedirect())
        self._pace = transport_support.RequestPacer() if pace is None else pace

    def get(
        self,
        intent: program_010.PageIntent,
        before_transport: Callable[[], None],
    ) -> raw_contract.RawResponse:
        request = Request(intent.url, headers=self._headers, method="GET")
        _validate_http_request(request, intent)
        self._pace()
        before_transport()
        try:
            with self._opener.open(request, timeout=30) as response:
                return raw_contract.RawResponse(
                    int(response.status),
                    response.read(program_010.MAXIMUM_RESPONSE_PAGE_BYTES + 1),
                )
        except HTTPError as error:
            try:
                return raw_contract.RawResponse(
                    error.code,
                    error.read(program_010.MAXIMUM_RESPONSE_PAGE_BYTES + 1),
                )
            finally:
                error.close()
        except (HTTPException, TimeoutError, ConnectionError, URLError, OSError) as error:
            raise Program010AuthorityError(
                "Program 010 OHLCV transport is ambiguous; zero-retry use is consumed"
            ) from error


class _Budget:
    def __init__(self) -> None:
        self.requests = 0
        self.responses = 0
        self.response_bytes = 0
        self.pages: list[dict[str, object]] = []

    def reserve_request(self) -> None:
        if self.requests >= program_010.MAXIMUM_QUALIFICATION_REQUESTS:
            raise Program010AuthorityError("Program 010 request ceiling exceeded")
        self.requests += 1

    def accept_response(
        self,
        request: program_010.SessionRequest,
        intent: program_010.PageIntent,
        response: raw_contract.RawResponse,
        body: bytes,
    ) -> None:
        if self.responses >= program_010.MAXIMUM_QUALIFICATION_REQUESTS:
            raise Program010AuthorityError("Program 010 response ceiling exceeded")
        self.responses += 1
        self.response_bytes += len(body)
        self.pages.append(
            {
                "session": request.session.isoformat(),
                "page_index": intent.page_index,
                "status": response.status,
                "response_bytes": len(body),
                "response_sha256": hashlib.sha256(body).hexdigest(),
                "incoming_page_token_present": intent.incoming_page_token is not None,
            }
        )
        if len(body) > program_010.MAXIMUM_RESPONSE_PAGE_BYTES:
            raise Program010AuthorityError("Program 010 response exceeds the 8 MiB page ceiling")
        if self.response_bytes > program_010.MAXIMUM_QUALIFICATION_RESPONSE_BYTES:
            raise Program010AuthorityError("Program 010 qualification byte ceiling exceeded")


class _PersistentSessionSource:
    __slots__ = (
        "_budget",
        "_closed",
        "_pending",
        "_request",
        "_response_for",
        "_writer",
    )

    def __init__(
        self,
        request: program_010.SessionRequest,
        budget: _Budget,
        response_for: Callable[[program_010.PageIntent], raw_contract.RawResponse],
        writer: Callable[[str, bytes], None],
    ) -> None:
        self._request = request
        self._budget = budget
        self._response_for = response_for
        self._writer = writer
        self._pending: program_010.RetainedPage | None = None
        self._closed = False

    def response(self, intent: program_010.PageIntent) -> raw_contract.RawResponse:
        if self._closed or self._pending is not None:
            raise Program010AuthorityError("Program 010 persistent source state differs")
        _validate_page_intent(self._request, intent)
        self._budget.reserve_request()
        prefix = f"session-{self._request.session.isoformat()}-{intent.page_index:02d}"
        self._writer(f"{prefix}.intent.json", (canonical_json(intent) + "\n").encode())
        response = self._response_for(intent)
        body = response.body[: program_010.MAXIMUM_RESPONSE_PAGE_BYTES + 1]
        self._writer(f"{prefix}.body", body)
        response_sha256 = hashlib.sha256(body).hexdigest()
        self._writer(
            f"{prefix}.receipt.json",
            (
                canonical_json(
                    {
                        "status": response.status,
                        "retained_response_bytes": len(body),
                        "response_truncated": len(response.body) != len(body),
                        "response_sha256": response_sha256,
                    }
                )
                + "\n"
            ).encode(),
        )
        retained = program_010.RetainedPage(intent.page_index, len(body), response_sha256)
        self._pending = retained
        bounded = raw_contract.RawResponse(response.status, body)
        self._budget.accept_response(self._request, intent, bounded, body)
        _raise_for_status(response.status)
        return bounded

    def retain(self, page_index: int, body: bytes) -> program_010.RetainedPage:
        pending = self._pending
        if (
            self._closed
            or pending is None
            or pending.page_index != page_index
            or pending.byte_count != len(body)
            or pending.sha256 != hashlib.sha256(body).hexdigest()
        ):
            raise Program010AuthorityError("Program 010 retained response differs")
        self._pending = None
        return pending

    def close(self) -> None:
        self._closed = True


def _validate_page_intent(
    request: program_010.SessionRequest, intent: program_010.PageIntent
) -> None:
    if (
        type(request) is not program_010.SessionRequest
        or type(intent) is not program_010.PageIntent
        or intent.request_identity != request.identity
        or type(intent.page_index) is not int
        or not 1 <= intent.page_index <= program_010.MAXIMUM_PAGES_PER_SESSION
        or intent.url != request.url(intent.incoming_page_token)
    ):
        raise Program010AuthorityError("Program 010 request intent differs")


def _validate_http_request(request: Request, intent: program_010.PageIntent) -> None:
    matching = [
        item
        for item in program_010.qualification_requests()
        if item.identity == intent.request_identity
        and item.url(intent.incoming_page_token) == request.full_url
    ]
    parsed = urlsplit(request.full_url)
    try:
        parameters = tuple(parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True))
    except ValueError as error:
        raise Program010AuthorityError("Program 010 endpoint or query differs") from error
    expected_parameters: tuple[tuple[str, str], ...] = ()
    if len(matching) == 1:
        expected_parameters = matching[0].parameters
        if intent.incoming_page_token is not None:
            expected_parameters = (*expected_parameters, ("page_token", intent.incoming_page_token))
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
        or parameters != expected_parameters
    ):
        raise Program010AuthorityError("Program 010 endpoint or query differs")


def _raise_for_status(status: int) -> None:
    if status == 200:
        return
    if status == 401:
        raise Program010AuthorityError(
            "OHLCV-AUTHENTICATION-FAIL-CONSUMED-NO-RETRY: Alpaca returned HTTP 401"
        )
    if status == 403:
        raise Program010AuthorityError(
            "OHLCV-ACCESS-FAIL-CONSUMED-NO-RETRY-NO-PURCHASE: Alpaca returned HTTP 403"
        )
    if status == 429:
        raise Program010AuthorityError(
            "OHLCV-ACCESS-FAIL-CONSUMED-NO-RETRY: Alpaca returned HTTP 429"
        )
    if 300 <= status < 400:
        raise Program010AuthorityError("Program 010 OHLCV redirect attempt rejected")
    if 500 <= status < 600:
        raise Program010AuthorityError(
            f"OHLCV-ACCESS-FAIL-CONSUMED-NO-RETRY: Alpaca returned HTTP {status}"
        )
    raise Program010AuthorityError(f"Program 010 OHLCV returned unexpected HTTP {status}")


def _validate_chronology(
    repository: Path,
    proposal: Mapping[str, Any],
    predecessor: Mapping[str, Any],
    terminal: Mapping[str, Any],
) -> None:
    sample = _mapping(proposal.get("fresh_sample"), "fresh sample")
    records = _sequence(sample.get("sessions"), "fresh sample sessions")
    selected = tuple(
        date.fromisoformat(str(_mapping(item, "session").get("date"))) for item in records
    )
    audit = _mapping(predecessor.get("prior_provider_observation_audit"), "observation audit")
    program_002 = _mapping(audit.get("program_002_observed_market_data"), "Program 002 audit")
    program_002_range = _mapping(program_002.get("xnys_session_range"), "Program 002 range")
    observed = {
        date.fromisoformat(value)
        for value in _sequence(
            audit.get("program_006_observed_sessions"), "Program 006 observed sessions"
        )
    }
    p2_start = date.fromisoformat(str(program_002_range.get("start_session")))
    p2_end = date.fromisoformat(str(program_002_range.get("end_session")))
    terminal_contract = _mapping(terminal.get("qualification_contract"), "Program 009 contract")
    terminal_sessions = tuple(
        date.fromisoformat(str(value))
        for value in _sequence(terminal_contract.get("sessions"), "Program 009 sessions")
    )
    runtime = _mapping(terminal.get("runtime_outcome"), "Program 009 runtime")
    pages = _mapping(runtime.get("pages_per_chain"), "Program 009 pages")
    if (
        len(terminal_sessions) != 15
        or terminal_sessions[-2:] != (date(2025, 11, 28), date(2025, 12, 15))
        or pages.get("split-pre-early-close-2025-11-28") != 0
        or pages.get("split-post-2025-12-15") != 0
    ):
        raise Program010AuthorityError("Program 009 observed chronology differs")
    observed.update(terminal_sessions[:-2])
    exclusions = _mapping(
        audit.get("protected_or_controlled_exclusion_inventory"), "protected inventory"
    )
    ranges = tuple(
        (
            date.fromisoformat(str(_mapping(item, "protected range").get("start"))),
            date.fromisoformat(str(_mapping(item, "protected range").get("end"))),
        )
        for item in _sequence(exclusions.get("ranges"), "protected ranges")
    )
    current_ranges = _current_protected_ranges(repository)
    eligible = _mapping(audit.get("eligible_exposed_chronology"), "eligible chronology")
    eligible_start = date.fromisoformat(str(eligible.get("start_session")))
    eligible_end = date.fromisoformat(str(eligible.get("end_session")))
    if (
        selected != program_010.SELECTED_SESSIONS
        or sample.get("selected_session_overlap_with_prior_ohlcv") != 0
        or sample.get("expected_canonical_coordinates") != 4_602
        or any(p2_start <= session <= p2_end or session in observed for session in selected)
        or any(
            start <= session <= end
            for session in selected
            for start, end in (*ranges, *current_ranges)
        )
        or any(not eligible_start <= session <= eligible_end for session in selected)
    ):
        raise Program010AuthorityError("Program 010 fresh exposed chronology differs")


def _current_protected_ranges(repository: Path) -> tuple[tuple[date, date], ...]:
    try:
        raw = (repository / PROTECTED_CHRONOLOGY_PATH).read_bytes()
    except OSError as error:
        raise Program010AuthorityError("Program 010 protected chronology is absent") from error
    inventory = _json_object(raw, "protected chronology")
    unsigned = dict(inventory)
    stored_fingerprint = unsigned.pop("inventory_fingerprint", None)
    sources = _mapping(inventory.get("source_artifacts"), "protected chronology sources")
    expected_paths = {
        "controlled_ranges": PROTECTED_CHRONOLOGY_SOURCE_PATHS[0],
        "daily_independent_range": PROTECTED_CHRONOLOGY_SOURCE_PATHS[1],
        "strategic_allocation_range": PROTECTED_CHRONOLOGY_SOURCE_PATHS[2],
        "june_reservation": PROTECTED_CHRONOLOGY_SOURCE_PATHS[3],
        "intraday_v3_selection": PROTECTED_CHRONOLOGY_SOURCE_PATHS[4],
    }
    if (
        inventory.get("schema_version") != "standing-protected-chronology-v1"
        or inventory.get("inventory_id") != "standing-protected-chronology-2026-08-30-v1"
        or inventory.get("status") != "ACTIVE-CANONICAL-PROTECTED-CHRONOLOGY"
        or stored_fingerprint != fingerprint(unsigned)
        or set(sources) != set(expected_paths)
        or any(
            _mapping(sources.get(name), f"protected chronology {name} source").get("path")
            != path.as_posix()
            for name, path in expected_paths.items()
        )
    ):
        raise Program010AuthorityError("Program 010 protected chronology control differs")

    artifacts = {
        name: _load_sha256_artifact(
            repository,
            _mapping(sources.get(name), f"protected chronology {name} source"),
        )
        for name in expected_paths
    }
    controlled = _mapping(
        artifacts["controlled_ranges"].get("chronology_and_protected_boundaries"),
        "controlled ranges",
    )
    sealed = _mapping(
        artifacts["daily_independent_range"].get("sealed_boundaries"), "sealed ranges"
    )
    daily = _mapping(sealed.get("independent_daily_range"), "daily independent range")
    strategic_entries = [
        _mapping(item, "known exposure")
        for item in _sequence(
            artifacts["strategic_allocation_range"].get("entries"), "known exposures"
        )
        if isinstance(item, Mapping)
        and item.get("id") == "strategic-allocation-protected-holdout-2026"
    ]
    june = _mapping(artifacts["june_reservation"].get("range"), "June reservation")
    v3_periods = [
        _mapping(item, "V3 period")
        for item in _sequence(artifacts["intraday_v3_selection"].get("periods"), "V3 periods")
        if isinstance(item, Mapping) and item.get("role") != "training"
    ]
    if len(strategic_entries) != 1 or [item.get("role") for item in v3_periods] != [
        "validation-a",
        "validation-b",
        "validation-c",
    ]:
        raise Program010AuthorityError("Program 010 protected chronology sources differ")

    derived = (
        ("daily-independent-2018-2019", daily.get("start"), daily.get("end")),
        (
            "strategic-allocation-protected-holdout-2026",
            strategic_entries[0].get("start"),
            strategic_entries[0].get("end"),
        ),
        (
            "june-2026-reservation",
            str(june.get("evaluation_start"))[:10],
            str(june.get("evaluation_end"))[:10],
        ),
        (
            "intraday-v3-validation",
            v3_periods[0].get("start"),
            v3_periods[-1].get("end"),
        ),
        ("controlled-a", *_range_boundaries(controlled, "controlled_a")),
        ("controlled-b", *_range_boundaries(controlled, "controlled_b")),
    )
    declared = tuple(
        (item.get("id"), item.get("start"), item.get("end"))
        for item in (
            _mapping(value, "protected chronology range")
            for value in _sequence(inventory.get("ranges"), "protected chronology ranges")
        )
    )
    if declared != derived:
        raise Program010AuthorityError("Program 010 protected chronology inventory is stale")
    try:
        protected_ranges = tuple(
            (date.fromisoformat(str(start)), date.fromisoformat(str(end)))
            for _, start, end in derived
        )
    except ValueError as error:
        raise Program010AuthorityError(
            "Program 010 protected chronology dates are invalid"
        ) from error
    if any(start > end for start, end in protected_ranges):
        raise Program010AuthorityError("Program 010 protected chronology range is inverted")
    return protected_ranges


def _range_boundaries(value: Mapping[str, Any], key: str) -> tuple[Any, Any]:
    item = _mapping(value.get(key), f"{key} range")
    return item.get("start"), item.get("end")


def _validate_split_controls(ledger: Mapping[str, Any]) -> None:
    for symbol in ("XLB", "XLE", "XLK", "XLU", "XLY"):
        factor = raw_contract.share_unit_factor(
            ledger, symbol, date(2025, 11, 28), date(2025, 12, 15)
        )
        if factor.numerator != 2 or factor.denominator != 1:
            raise Program010AuthorityError("Program 010 split-volume factor differs")


def _repository_preflight(repository: Path, identity: Mapping[str, Any]) -> Mapping[str, str]:
    runtime = _mapping(identity.get("runtime_binding"), "runtime binding")
    source_commit = str(runtime.get("source_commit"))
    source_files = _sequence(runtime.get("source_files"), "runtime source files")
    paths = [str(_mapping(item, "runtime source file").get("path")) for item in source_files]
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
        source_tree = git("rev-parse", f"{source_commit}^{{tree}}").stdout.strip()
        changed = git("diff", "--name-only", source_commit, head, "--", *paths).stdout
        ancestor = git("merge-base", "--is-ancestor", source_commit, head, check=False)
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        raise Program010AuthorityError("Program 010 repository identity is unavailable") from error
    if (
        dirty
        or head != main
        or head != origin_main
        or source_tree != runtime.get("source_tree")
        or ancestor.returncode != 0
        or changed
    ):
        raise Program010AuthorityError("Program 010 reviewed synchronized-main lineage differs")
    return {
        "runtime_source_commit": source_commit,
        "runtime_source_tree": source_tree,
        "synchronized_main_commit": head,
    }


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
        if stat.S_IMODE(os.fstat(self._handle.fileno()).st_mode) & 0o077:
            self._handle.close()
            raise Program010AuthorityError("Program 010 evidence lock is not private")
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)

    def __exit__(self, *_args: object) -> None:
        assert self._handle is not None
        self._handle.close()


def _open_private_root(repository: Path, *, create: bool) -> int:
    repository = _repository(repository)
    descriptor = os.open(repository, _DIRECTORY_FLAGS)
    try:
        for part in PRIVATE_ROOT.parts:
            if create:
                with suppress(FileExistsError):
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
            try:
                child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            except FileNotFoundError as error:
                raise Program010AuthorityError(
                    "Program 010 private evidence root is absent"
                ) from error
            os.close(descriptor)
            descriptor = child
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode) or stat.S_IMODE(opened.st_mode) & 0o077:
            raise Program010AuthorityError("Program 010 private evidence root is not private")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _append_persistent_evidence(root_descriptor: int, key: str, payload: bytes) -> None:
    if type(key) is not str or _EVIDENCE_KEY.fullmatch(key) is None or type(payload) is not bytes:
        raise Program010AuthorityError("Program 010 persistent evidence entry is invalid")
    try:
        descriptor = os.open(
            key,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=root_descriptor,
        )
    except FileExistsError:
        raise Program010AuthorityError(
            f"Program 010 persistent evidence already exists: {key}"
        ) from None
    with os.fdopen(descriptor, "wb") as handle:
        if handle.write(payload) != len(payload):
            raise Program010AuthorityError("Program 010 persistent evidence write was incomplete")
        handle.flush()
        os.fsync(handle.fileno())
    os.fsync(root_descriptor)


def _read_persistent_evidence(root_descriptor: int, key: str) -> bytes:
    if _EVIDENCE_KEY.fullmatch(key) is None:
        raise Program010AuthorityError("Program 010 persistent evidence entry is invalid")
    try:
        descriptor = os.open(key, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_descriptor)
    except OSError as error:
        raise Program010AuthorityError("Program 010 active authority is absent") from error
    with os.fdopen(descriptor, "rb") as handle:
        metadata = os.fstat(handle.fileno())
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise Program010AuthorityError("Program 010 active authority is not private")
        return handle.read()


def _load_active_from_descriptor(
    root_descriptor: int, expected: Mapping[str, Any]
) -> Mapping[str, Any]:
    raw = _read_persistent_evidence(root_descriptor, "active-authority.json")
    authority = _json_object(raw, "active authority")
    if authority != expected or raw != (canonical_json(expected) + "\n").encode():
        raise Program010AuthorityError("Program 010 active authority differs")
    return authority


def _reject_existing_state(root_descriptor: int, *, allow_active: bool = True) -> None:
    allowed = {"run.lock"}
    if allow_active:
        allowed.add("active-authority.json")
    entries = set(os.listdir(root_descriptor))
    if entries - allowed or (not allow_active and "active-authority.json" in entries):
        raise Program010AuthorityError("Program 010 one-use authority state already exists")


def _require_credentials_present(environ: Mapping[str, str] | None) -> None:
    missing = credential_presence_preflight(environ)
    if missing:
        raise Program010AuthorityError("Program 010 credentials missing: " + ", ".join(missing))


def _load_bound_artifact(
    repository: Path,
    binding: Mapping[str, Any],
    fingerprint_field: str,
) -> Mapping[str, Any]:
    path_value = binding.get("path")
    if not isinstance(path_value, str):
        raise Program010AuthorityError("Program 010 artifact binding path is invalid")
    path = Path(path_value)
    if path.is_absolute() or ".." in path.parts:
        raise Program010AuthorityError("Program 010 artifact binding path is invalid")
    try:
        raw = (repository / path).read_bytes()
    except OSError as error:
        raise Program010AuthorityError(f"Program 010 binding is absent: {path.name}") from error
    payload = _json_object(raw, path.name)
    if hashlib.sha256(raw).hexdigest() != binding.get("sha256") or payload.get(
        fingerprint_field
    ) != binding.get("fingerprint"):
        raise Program010AuthorityError(f"Program 010 binding differs: {path.name}")
    return payload


def _load_sha256_artifact(
    repository: Path,
    binding: Mapping[str, Any],
) -> Mapping[str, Any]:
    path_value = binding.get("path")
    if not isinstance(path_value, str):
        raise Program010AuthorityError("Program 010 protected source path is invalid")
    path = Path(path_value)
    if path.is_absolute() or ".." in path.parts:
        raise Program010AuthorityError("Program 010 protected source path is invalid")
    try:
        raw = (repository / path).read_bytes()
    except OSError as error:
        raise Program010AuthorityError(
            f"Program 010 protected source is absent: {path.name}"
        ) from error
    if hashlib.sha256(raw).hexdigest() != binding.get("sha256"):
        raise Program010AuthorityError(f"Program 010 protected source differs: {path.name}")
    return _json_object(raw, path.name)


def _repository(repository: Path) -> Path:
    if not isinstance(repository, Path):
        raise Program010AuthorityError("Program 010 repository root is invalid")
    resolved = repository.resolve()
    if not resolved.is_dir():
        raise Program010AuthorityError("Program 010 repository root is absent")
    return resolved


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Program010AuthorityError(f"Program 010 {label} is invalid JSON") from error
    if type(value) is not dict:
        raise Program010AuthorityError(f"Program 010 {label} is not an object")
    return value


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Program010AuthorityError(f"Program 010 {label} is invalid")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise Program010AuthorityError(f"Program 010 {label} is invalid")
    return value


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise Program010AuthorityError("Program 010 timestamp must be UTC")
    return value.isoformat().replace("+00:00", "Z")


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
