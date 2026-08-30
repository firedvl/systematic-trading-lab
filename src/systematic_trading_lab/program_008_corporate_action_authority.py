"""Exact one-use authority controls for Program 008 corporate-action metadata."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import subprocess
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from http.client import HTTPException
from pathlib import Path
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import Request, build_opener

from . import program_005_alpaca as frozen
from . import program_007_alpaca as ledger_contract
from . import program_007_corporate_actions as predecessor
from . import program_008_corporate_actions as metadata
from .config import non_broker_subprocess_environment
from .fingerprints import canonical_json, fingerprint

PROGRAM_ID = metadata.PROGRAM_ID
STARTING_MAIN = "f8332e6fcab2bbf97dc18dc465aa716d94526526"
FUTURE_AUTHORITY_ID = "program-008-corporate-action-metadata-qualification-authority-2026-08-29-v1"
READY_STATUS = "READY FOR USER AUTHORIZATION"
CONSUMPTION_BOUNDARY = "immediately before first provider transport invocation"
PRIVATE_ROOT = Path(".trading-lab/program-008-corporate-action-metadata-v1")
CREDENTIAL_NAMES = predecessor.CREDENTIAL_NAMES

REQUEST_PLAN_PATH = Path(
    "config/research/program-008-corporate-action-metadata-request-plan-v1.json"
)
PROPOSAL_PATH = Path(
    "config/research/program-008-corporate-action-metadata-qualification-authority-proposal-v1.json"
)
REVIEW_PATH = Path(
    "config/research/program-008-corporate-action-metadata-qualification-authority-"
    "proposal-independent-review-v1.json"
)

_PROGRAM_007_TERMINAL = {
    "path": (
        "config/research/program-007-corporate-action-metadata-qualification-"
        "terminal-failure-v1.json"
    ),
    "sha256": "99bc4397909f364efac2f189351bff9ebaae9b886833fc7e0555b3fa5751119f",
    "fingerprint": "991bd9892ee32f4badc08350160a03c3514e0ae1a33dfa623406b534c73bd352",
}
_FORENSIC_ANALYSIS = {
    "path": (
        "config/research/program-007-corporate-action-metadata-offline-forensic-analysis-v1.json"
    ),
    "sha256": "1fdf65cf3d846dc67b3d29565f7e1283e95185fcc500f6a3b0d7670aa3b2ed8d",
    "fingerprint": "531148e65d1b45c8985b8ffe29bf7d4c150dd69888432a8188080322fd455c80",
}
_PROGRAM_008_PROPOSAL = {
    "path": "config/research/program-008-corporate-action-metadata-qualification-proposal-v1.json",
    "sha256": "19cc83e7531ac32c60ca2899cfb8a38e27cd21aed00b524b929fe068555fc7e5",
    "fingerprint": "3d2192495cae2fe9c8db67873819df727a9bb13eb5b9a911d51e89a8e4aa884f",
}
_FORENSIC_REVIEW = {
    "path": (
        "config/research/program-008-corporate-action-metadata-forensic-independent-review-v1.json"
    ),
    "sha256": "0ff5fe1f2c3db02c468ce3f87b553acbdd94b290189eb9f03c843e071c18475d",
    "fingerprint": "e987474a6af543a0e7097db67ee87475d0042b2ceae7b3c7e1b49d07e67b4064",
}
_LEDGER = {
    "path": "config/research/program-007-unit-changing-action-ledger-v3.json",
    "sha256": "e405529489921a0ec8883aa64e855e6600a99105387cbc9ed2766c82bc0826b1",
    "fingerprint": "37467ced2666cdb716706aa4310e48aa5b0938f168cafadf00f6dec72e336f4f",
}
_AUTHORITY_SOURCE_PATHS = (
    REQUEST_PLAN_PATH,
    Path("scripts/check_secrets.py"),
    Path("src/systematic_trading_lab/cli.py"),
    Path("src/systematic_trading_lab/config.py"),
    Path("src/systematic_trading_lab/fingerprints.py"),
    Path("src/systematic_trading_lab/program_005_alpaca.py"),
    Path("src/systematic_trading_lab/program_007_alpaca.py"),
    Path("src/systematic_trading_lab/program_007_corporate_actions.py"),
    Path("src/systematic_trading_lab/program_008_corporate_actions.py"),
    Path("src/systematic_trading_lab/program_008_corporate_action_authority.py"),
    Path("tests/unit/test_intraday_source_provenance.py"),
    Path("tests/unit/test_program_008_corporate_action_authority.py"),
)
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


class Program008AuthorityError(ValueError):
    """Fail-closed Program 008 authority error."""


def frozen_request_chain() -> predecessor.RequestChain:
    chain = predecessor.RequestChain("cusips", "cusips", predecessor.CUSIPS)
    if chain.identities != (
        "464287655",
        "78462F103",
        "78467Y107",
        "81369Y100",
        "81369Y209",
        "81369Y308",
        "81369Y407",
        "81369Y506",
        "81369Y605",
        "81369Y704",
        "81369Y803",
        "81369Y860",
        "81369Y886",
    ):
        raise Program008AuthorityError("Program 008 CUSIP chain differs")
    return chain


def credential_presence(environ: Mapping[str, str] | None = None) -> Mapping[str, bool]:
    """Return names and presence only; never expose credential values."""
    values = os.environ if environ is None else environ
    return {name: bool(values.get(name, "").strip()) for name in CREDENTIAL_NAMES}


def credential_presence_preflight(
    environ: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    return tuple(name for name, present in credential_presence(environ).items() if not present)


def read_credentials(environ: Mapping[str, str] | None = None) -> tuple[str, str]:
    values = os.environ if environ is None else environ
    credentials = tuple(values.get(name, "").strip() for name in CREDENTIAL_NAMES)
    if any(not value or "\r" in value or "\n" in value for value in credentials):
        raise Program008AuthorityError("Program 008 metadata credentials are required")
    return credentials[0], credentials[1]


def expected_request_plan() -> Mapping[str, Any]:
    chain = frozen_request_chain()
    unsigned: dict[str, Any] = {
        "schema_version": "program-008-corporate-action-metadata-request-plan-v1",
        "request_plan_id": "program-008-corporate-action-metadata-request-plan-2026-08-29-v1",
        "program_id": PROGRAM_ID,
        "status": "FROZEN-CREDENTIAL-FREE-NOT-AUTHORIZED",
        "source_role": "BOUNDED AS-OF CORROBORATION + DISCREPANCY DETECTION",
        "request": {
            "method": "GET",
            "endpoint": predecessor.ENDPOINT,
            "redirects": False,
            "types": "OMITTED",
            "pagination_token": "opaque page_token appended after fixed parameters",
        },
        "chain": {
            "chain_id": chain.chain_id,
            "identity_parameter": chain.identity_parameter,
            "identities": list(chain.identities),
            "fixed_parameters": [list(parameter) for parameter in chain.parameters],
            "chain_fingerprint": chain.identity,
            "maximum_pages": chain.maximum_pages,
            "symbol_parameter_allowed": False,
            "secondary_identity_query_allowed": False,
        },
        "transport_budget": {
            "minimum_http_requests": 1,
            "maximum_http_requests": metadata.MAXIMUM_REQUESTS,
            "minimum_http_responses": 1,
            "maximum_http_responses": metadata.MAXIMUM_RESPONSES,
            "maximum_pages": metadata.MAXIMUM_PAGES,
            "page_limit": 1000,
            "maximum_response_bytes": metadata.MAXIMUM_RESPONSE_PAGE_BYTES,
            "bounded_read_bytes": metadata.MAXIMUM_RESPONSE_PAGE_BYTES + 1,
            "maximum_total_bytes": metadata.MAXIMUM_RESPONSE_BYTES,
            "maximum_credential_loads": 1,
            "automatic_retries": metadata.AUTOMATIC_RETRIES,
        },
        "identity_semantics": {
            "empty_cusip": "ALLOW ONLY WITH ONE UNAMBIGUOUS PUBLIC-LEDGER IDENTITY",
            "matching_nonempty_cusip": "CORROBORATING",
            "conflicting_nonempty_cusip": "HARD FAIL",
            "empty_isin": "ALLOWED",
            "isin_canonical": False,
            "conflicting_nonempty_isin_for_same_event": "HARD FAIL",
        },
        "event_id_semantics": {
            "format": "canonical UUID",
            "identical_duplicate": "DEDUPLICATE AND COUNT",
            "conflicting_duplicate": "HARD FAIL",
            "canonical_core_consistent_across_pages": True,
            "cross_filter_stability_claimed": False,
        },
        "economic_date_semantics": {
            "ex_date": [
                "forward_split",
                "reverse_split",
                "cash_dividend",
                "stock_dividend",
                "spin_off",
                "rights_distribution",
                "capital_gains_distribution",
            ],
            "effective_date": [
                "unit_split",
                "cash_merger",
                "stock_merger",
                "stock_and_cash_merger",
                "reorganization",
            ],
            "feature_relevant_event_without_usable_date": "FAIL CLOSED",
            "inferred_transformation_date_allowed": False,
        },
        "positive_controls": {
            "symbols": sorted(metadata.POSITIVE_CONTROLS),
            "event_type": "forward_split",
            "economic_date": "2025-12-05",
            "ratio": "2-for-1",
            "required_count_per_symbol": 1,
        },
        "discrepancy_policy": "FAIL-PENDING-PUBLIC-LEDGER-RECONCILIATION",
        "process_date": {
            "requested_interval_inclusive": True,
            "returned_value_required_inside_interval": True,
            "equals_economic_date": False,
            "creation_lag": "UNBOUNDED-NO-PROVIDER-GUARANTEE",
        },
        "pagination": {
            "exact_page_sequence": True,
            "token_reuse_allowed": False,
            "token_cycle_allowed": False,
            "page_omission_allowed": False,
            "terminal_token": None,
        },
        "http_outcomes": {
            "200": "VALIDATE RETAINED METADATA",
            "401": "TERMINAL AUTHENTICATION FAIL; USE CONSUMED",
            "403": "TERMINAL ENTITLEMENT FAIL; USE CONSUMED; NO PURCHASE",
            "429": "TERMINAL FAIL; USE CONSUMED; NO RETRY",
            "5xx": "TERMINAL FAIL; USE CONSUMED; NO RETRY",
            "ambiguous_transport": "TERMINAL FAIL; USE CONSUMED; NO RETRY",
            "oversized_or_malformed": "RETAIN BOUNDED BYTES THEN TERMINAL FAIL",
        },
        "exposed_program_007_response_firewall": {
            "fresh_qualification_evidence": False,
            "read_during_program_008_qualification": False,
            "merged_into_program_008_receipts": False,
            "symbol_query_replay_allowed": False,
        },
        "raw_first_storage": {
            "private_root": PRIVATE_ROOT.as_posix(),
            "order": [
                "bounded response bytes",
                "create-only persistence",
                "fsync",
                "SHA-256 receipt",
                "parse and validate",
            ],
        },
        "credential_names": list(CREDENTIAL_NAMES),
        "authentication_header_names": ["APCA-API-KEY-ID", "APCA-API-SECRET-KEY"],
        "authority": _authority_flags(active=False),
    }
    return {**unsigned, "request_plan_fingerprint": fingerprint(unsigned)}


def validate_proposal_chain(repository: Path) -> Mapping[str, Any]:
    """Validate immutable authority inputs without loading credential values."""
    repository = repository.resolve()
    terminal = _load_static_artifact(repository, _PROGRAM_007_TERMINAL, "failure_fingerprint")
    _validate_program_007_terminal(terminal)
    analysis = _load_static_artifact(repository, _FORENSIC_ANALYSIS, "analysis_fingerprint")
    successor = _load_static_artifact(repository, _PROGRAM_008_PROPOSAL, "proposal_fingerprint")
    forensic_review = _load_static_artifact(repository, _FORENSIC_REVIEW, "review_fingerprint")
    ledger = _load_static_artifact(repository, _LEDGER, "ledger_fingerprint")
    ledger_contract.validate_action_ledger(ledger)
    request_plan, request_binding = _load_control_artifact(
        repository, REQUEST_PLAN_PATH, "request_plan_fingerprint", "request plan"
    )
    if request_plan != expected_request_plan():
        raise Program008AuthorityError("Program 008 request plan differs")
    proposal, proposal_binding = _load_control_artifact(
        repository, PROPOSAL_PATH, "proposal_fingerprint", "authority proposal"
    )
    review, review_binding = _load_control_artifact(
        repository, REVIEW_PATH, "review_fingerprint", "authority proposal review"
    )
    _validate_proposal(
        proposal,
        request_binding,
        analysis,
        successor,
        forensic_review,
    )
    _validate_review(proposal, proposal_binding, review)
    return {
        "proposal": proposal,
        "review": review,
        "proposal_binding": proposal_binding,
        "review_binding": review_binding,
        "request_plan": request_plan,
        "request_plan_binding": request_binding,
    }


def derive_authorization_root(
    repository: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Mapping[str, Any]:
    repository = repository.resolve()
    controls = validate_proposal_chain(repository)
    proposal = _mapping(controls["proposal"], "authority proposal")
    if proposal.get("status") != READY_STATUS:
        raise Program008AuthorityError(
            "Program 008 authority proposal is not ready; no authorization root exists"
        )
    _require_credentials_present(environ)
    lineage = _repository_preflight(repository, proposal, controls)
    unsigned: dict[str, Any] = {
        "schema_version": "program-008-corporate-action-metadata-authority-v1",
        "status": "ACTIVE-ONE-USE",
        "authority_id": FUTURE_AUTHORITY_ID,
        "program_id": PROGRAM_ID,
        "request_plan_fingerprint": controls["request_plan"]["request_plan_fingerprint"],
        "consumption_boundary": CONSUMPTION_BOUNDARY,
        "authority": _authority_flags(active=True),
        "bindings": {
            "program_007_terminal_failure": _PROGRAM_007_TERMINAL,
            "offline_forensic_analysis": _FORENSIC_ANALYSIS,
            "program_008_qualification_proposal": _PROGRAM_008_PROPOSAL,
            "program_008_forensic_review": _FORENSIC_REVIEW,
            "public_identity_ledger": _LEDGER,
            "request_plan": controls["request_plan_binding"],
            "authority_proposal": controls["proposal_binding"],
            "authority_proposal_review": controls["review_binding"],
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
        raise Program008AuthorityError("Program 008 external authorization root differs")
    root_descriptor = _open_private_root(repository)
    try:
        with _locked_root(root_descriptor):
            _reject_existing_state(root_descriptor, allow_active=False)
            authority = derive_authorization_root(repository, environ=environ)
            _require_credentials_present(environ)
            if authority.get("authority_fingerprint") != authorization_root:
                raise Program008AuthorityError("Program 008 external authorization root differs")
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
    authorization_root: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> Mapping[str, Any]:
    expected = derive_authorization_root(repository, environ=environ)
    path = repository.resolve() / PRIVATE_ROOT / "active-authority.json"
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise Program008AuthorityError("Program 008 metadata authority is absent") from error
    authority = _json_object(raw, "active authority")
    if (
        authorization_root != expected.get("authority_fingerprint")
        or authority != expected
        or raw != (canonical_json(expected) + "\n").encode()
    ):
        raise Program008AuthorityError(
            "Program 008 metadata authority is not exact or externally authorized"
        )
    return authority


def execute_qualification(
    repository: Path,
    authorization_root: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> metadata.ParsedChain:
    """Run one reviewed qualification after separate exact-root authorization."""
    return _execute_qualification(
        repository,
        authorization_root,
        environ=environ,
        mock_transport=None,
    )


def _execute_mock_qualification(
    repository: Path,
    authorization_root: str,
    *,
    environ: Mapping[str, str],
    transport: MockMetadataTransport,
) -> metadata.ParsedChain:
    if type(transport) is not MockMetadataTransport:
        raise Program008AuthorityError("Program 008 test execution requires a finite mock")
    if environ is os.environ:
        raise Program008AuthorityError(
            "Program 008 test execution requires an explicit environment"
        )
    return _execute_qualification(
        repository,
        authorization_root,
        environ=environ,
        mock_transport=transport,
    )


def _execute_qualification(
    repository: Path,
    authorization_root: str,
    *,
    environ: Mapping[str, str] | None,
    mock_transport: MockMetadataTransport | None,
) -> metadata.ParsedChain:
    repository = repository.resolve()
    root_descriptor = _open_private_root(repository)
    claim_written = False
    budget = _Budget()
    try:
        with _locked_root(root_descriptor):
            _reject_existing_state(root_descriptor)
            authority = load_active_authority(repository, authorization_root, environ=environ)
            public_ledger = ledger_contract.load_action_ledger(repository / _LEDGER["path"])
            ledger_contract.validate_action_ledger(public_ledger)
            _require_credentials_present(environ)
            key_id, secret_key = read_credentials(environ)
            client = _AlpacaMetadataClient(key_id, secret_key) if mock_transport is None else None

            def writer(key: str, payload: bytes) -> None:
                _append_persistent_evidence(root_descriptor, key, payload)

            def response_for(intent: predecessor.RequestIntent) -> predecessor.RawResponse:
                def consume() -> None:
                    nonlocal claim_written
                    if claim_written:
                        return
                    writer(
                        "claim.json",
                        canonical_json(
                            {
                                "schema_version": (
                                    "program-008-private-corporate-action-metadata-claim-v1"
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

                if mock_transport is not None:
                    consume()
                    return mock_transport.get(intent)
                assert client is not None
                return client.get(intent, consume)

            try:
                result = _execute_chain(budget, response_for, writer)
                if mock_transport is not None:
                    mock_transport.require_exhausted()
            except Exception as error:
                if claim_written:
                    with suppress(OSError, ValueError):
                        writer(
                            "terminal-failure.json",
                            canonical_json(
                                {
                                    "schema_version": (
                                        "program-008-private-corporate-action-metadata-failure-v1"
                                    ),
                                    "status": "TERMINAL-FAIL-CONSUMED-NO-RETRY",
                                    "failure_class": type(error).__name__,
                                    "provider_transport_attempted": True,
                                    "scientific_use_consumed": True,
                                    "completed_requests": budget.requests,
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
                            "program-008-private-corporate-action-metadata-receipt-v1"
                        ),
                        "status": "METADATA-QUALIFICATION-PASS",
                        "authority_id": authority["authority_id"],
                        "request_count": budget.requests,
                        "response_count": budget.responses,
                        "response_bytes": budget.response_bytes,
                        "event_count": len(result.events),
                        "credential_loads": 1,
                        "automatic_retries": 0,
                        "program_007_response_used": False,
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


class MockMetadataTransport:
    """Finite canned responses for lifecycle tests; no credentials cross this boundary."""

    __slots__ = ("_intents", "_responses")

    def __init__(self, responses: Sequence[predecessor.RawResponse]) -> None:
        if (
            type(responses) not in {list, tuple}
            or not 1 <= len(responses) <= metadata.MAXIMUM_RESPONSES
            or any(type(response) is not predecessor.RawResponse for response in responses)
        ):
            raise Program008AuthorityError("Program 008 mock metadata responses are invalid")
        self._responses = tuple(responses)
        self._intents: list[predecessor.RequestIntent] = []

    @property
    def intents(self) -> tuple[predecessor.RequestIntent, ...]:
        return tuple(self._intents)

    def get(self, intent: predecessor.RequestIntent) -> predecessor.RawResponse:
        _validate_intent(intent)
        index = len(self._intents)
        self._intents.append(intent)
        if index >= len(self._responses):
            raise Program008AuthorityError("Program 008 mock metadata response is missing")
        return self._responses[index]

    def require_exhausted(self) -> None:
        if len(self._intents) != len(self._responses):
            raise Program008AuthorityError("Program 008 mock metadata responses remain unused")


class _AlpacaMetadataClient:
    __slots__ = ("_headers", "_opener")

    def __init__(self, key_id: str, secret_key: str) -> None:
        if any(not value or "\r" in value or "\n" in value for value in (key_id, secret_key)):
            raise Program008AuthorityError("Program 008 metadata credentials are invalid")
        self._headers = {
            "Accept": "application/json",
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
        }
        self._opener = build_opener(predecessor._NoRedirect())

    def get(
        self,
        intent: predecessor.RequestIntent,
        before_transport: Callable[[], None],
    ) -> predecessor.RawResponse:
        _validate_intent(intent)
        request = Request(intent.url, headers=self._headers, method="GET")
        _validate_http_request(request)
        before_transport()
        try:
            with self._opener.open(request, timeout=30) as response:
                return predecessor.RawResponse(
                    int(response.status),
                    response.read(metadata.MAXIMUM_RESPONSE_PAGE_BYTES + 1),
                )
        except HTTPError as error:
            try:
                return predecessor.RawResponse(
                    error.code,
                    error.read(metadata.MAXIMUM_RESPONSE_PAGE_BYTES + 1),
                )
            finally:
                error.close()
        except (HTTPException, TimeoutError, ConnectionError, URLError, OSError) as error:
            raise Program008AuthorityError(
                "Program 008 metadata transport is ambiguous; zero-retry use is consumed"
            ) from error


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
            raise Program008AuthorityError("Program 008 evidence lock is not private")
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)

    def __exit__(self, *_args: object) -> None:
        assert self._handle is not None
        self._handle.close()


def _locked_root(root_descriptor: int) -> _LockedRoot:
    return _LockedRoot(root_descriptor)


class _Budget:
    def __init__(self) -> None:
        self.requests = 0
        self.responses = 0
        self.response_bytes = 0

    def reserve_request(self) -> None:
        if self.requests >= metadata.MAXIMUM_REQUESTS:
            raise Program008AuthorityError("Program 008 metadata request ceiling exceeded")
        self.requests += 1

    def accept_response(self, body: bytes) -> None:
        if self.responses >= metadata.MAXIMUM_RESPONSES:
            raise Program008AuthorityError("Program 008 metadata response ceiling exceeded")
        self.responses += 1
        self.response_bytes += len(body)
        if len(body) > metadata.MAXIMUM_RESPONSE_PAGE_BYTES:
            raise Program008AuthorityError("Program 008 metadata page exceeds 1 MiB")
        if self.response_bytes > metadata.MAXIMUM_RESPONSE_BYTES:
            raise Program008AuthorityError("Program 008 metadata byte ceiling exceeded")


def _execute_chain(
    budget: _Budget,
    response_for: Callable[[predecessor.RequestIntent], predecessor.RawResponse],
    writer: Callable[[str, bytes], None],
) -> metadata.ParsedChain:
    chain = frozen_request_chain()
    bodies: list[bytes] = []
    seen_tokens: set[str] = set()
    incoming_token: str | None = None
    for page_index in range(1, metadata.MAXIMUM_PAGES + 1):
        budget.reserve_request()
        intent = predecessor.RequestIntent(
            chain_id=chain.chain_id,
            chain_identity=chain.identity,
            page_index=page_index,
            url=chain.url(incoming_token),
            incoming_page_token=incoming_token,
        )
        _validate_intent(intent)
        prefix = f"cusips-{page_index:02d}"
        writer(f"{prefix}.intent.json", canonical_json(intent).encode())
        response = response_for(intent)
        retained = response.body[: metadata.MAXIMUM_RESPONSE_PAGE_BYTES + 1]
        writer(f"{prefix}.body", retained)
        writer(
            f"{prefix}.receipt.json",
            canonical_json(
                {
                    "status": response.status,
                    "response_bytes": len(response.body),
                    "retained_response_bytes": len(retained),
                    "response_truncated": len(retained) != len(response.body),
                    "response_sha256": hashlib.sha256(retained).hexdigest(),
                }
            ).encode(),
        )
        budget.accept_response(retained)
        _raise_for_status(response.status)
        page = metadata.parse_metadata_page(retained)
        bodies.append(retained)
        outgoing_token = page.next_page_token
        if outgoing_token is None:
            result = metadata.parse_metadata_chain(bodies)
            metadata.validate_unit_action_qualification(result.events)
            return result
        if outgoing_token in seen_tokens:
            raise Program008AuthorityError("Program 008 metadata pagination token repeats")
        seen_tokens.add(outgoing_token)
        incoming_token = outgoing_token
    raise Program008AuthorityError("Program 008 metadata pagination exceeds four pages")


def _raise_for_status(status: int) -> None:
    if status == 200:
        return
    if status == 401:
        raise Program008AuthorityError(
            "METADATA-AUTHENTICATION-FAIL-USE-CONSUMED-NO-RETRY: Alpaca returned HTTP 401"
        )
    if status == 403:
        raise Program008AuthorityError(
            "METADATA-ACCESS-FAIL-USE-CONSUMED-NO-RETRY-NO-PURCHASE: "
            "Alpaca entitlement returned HTTP 403"
        )
    if status == 429:
        raise Program008AuthorityError(
            "METADATA-ACCESS-FAIL-USE-CONSUMED-NO-RETRY: Alpaca returned HTTP 429"
        )
    if 300 <= status < 400:
        raise Program008AuthorityError("Program 008 metadata redirect attempt rejected")
    if 500 <= status < 600:
        raise Program008AuthorityError(
            f"METADATA-ACCESS-FAIL-USE-CONSUMED-NO-RETRY: Alpaca returned HTTP {status}"
        )
    raise Program008AuthorityError(f"Program 008 metadata returned unexpected HTTP {status}")


def _validate_intent(intent: predecessor.RequestIntent) -> None:
    chain = frozen_request_chain()
    if (
        type(intent) is not predecessor.RequestIntent
        or intent.chain_id != "cusips"
        or intent.chain_identity != chain.identity
        or type(intent.page_index) is not int
        or not 1 <= intent.page_index <= metadata.MAXIMUM_PAGES
        or intent.url != chain.url(intent.incoming_page_token)
        or intent.method != "GET"
        or intent.redirects is not False
    ):
        raise Program008AuthorityError("Program 008 metadata request intent differs")


def _validate_http_request(request: Request) -> None:
    parsed = urlsplit(request.full_url)
    chain = frozen_request_chain()
    try:
        parameters = tuple(parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True))
    except ValueError as error:
        raise Program008AuthorityError(
            "Program 008 metadata request endpoint or query differs"
        ) from error
    page_token = None
    if len(parameters) == len(chain.parameters) + 1 and parameters[-1][0] == "page_token":
        page_token = parameters[-1][1]
    query_is_exact = (
        parameters == chain.parameters
        if page_token is None
        else bool(page_token) and parameters[:-1] == chain.parameters
    )
    if (
        request.get_method() != "GET"
        or parsed.scheme != "https"
        or parsed.hostname != "data.alpaca.markets"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/v1/corporate-actions"
        or parsed.fragment
        or not query_is_exact
        or request.full_url != chain.url(page_token)
    ):
        raise Program008AuthorityError("Program 008 metadata request endpoint or query differs")


def _authority_flags(*, active: bool) -> Mapping[str, bool]:
    if set(predecessor._AUTHORITY) != {
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
        raise Program008AuthorityError("Program 008 authority field set differs")
    return {key: active and key in _ENABLED_AUTHORITY for key in predecessor._AUTHORITY}


def _require_credentials_present(environ: Mapping[str, str] | None) -> None:
    missing = credential_presence_preflight(environ)
    if missing:
        raise Program008AuthorityError("Program 008 credentials missing: " + ", ".join(missing))


def _open_private_root(repository: Path) -> int:
    if not isinstance(repository, Path):
        raise Program008AuthorityError("Program 008 repository root is invalid")
    repository = repository.resolve()
    if not repository.is_dir():
        raise Program008AuthorityError("Program 008 repository root is absent")
    descriptor = os.open(repository, _DIRECTORY_FLAGS)
    try:
        for part in PRIVATE_ROOT.parts:
            with suppress(FileExistsError):
                os.mkdir(part, mode=0o700, dir_fd=descriptor)
            child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode) or stat.S_IMODE(opened.st_mode) & 0o077:
            raise Program008AuthorityError("Program 008 private evidence root is not private")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _append_persistent_evidence(root_descriptor: int, key: str, payload: bytes) -> None:
    if (
        type(key) is not str
        or predecessor._EVIDENCE_KEY.fullmatch(key) is None
        or type(payload) is not bytes
    ):
        raise Program008AuthorityError("Program 008 persistent evidence entry is invalid")
    try:
        descriptor = os.open(
            key,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=root_descriptor,
        )
    except FileExistsError:
        raise Program008AuthorityError(
            f"Program 008 persistent evidence already exists: {key}"
        ) from None
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.fsync(root_descriptor)


def _load_static_artifact(
    repository: Path,
    binding: Mapping[str, str],
    fingerprint_field: str,
) -> Mapping[str, Any]:
    path = repository / binding["path"]
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise Program008AuthorityError(f"Program 008 binding is absent: {path.name}") from error
    payload = _json_object(raw, path.name)
    if (
        hashlib.sha256(raw).hexdigest() != binding["sha256"]
        or payload.get(fingerprint_field) != binding["fingerprint"]
    ):
        raise Program008AuthorityError(f"Program 008 binding differs: {path.name}")
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
        raise Program008AuthorityError(f"Program 008 {label} is absent") from error
    payload = _json_object(raw, label)
    unsigned = dict(payload)
    stored = unsigned.pop(fingerprint_field, None)
    if not frozen._is_lower_hex(stored, 64) or stored != fingerprint(unsigned):
        raise Program008AuthorityError(f"Program 008 {label} differs")
    return payload, {
        "path": relative.as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "fingerprint": stored,
    }


def _validate_program_007_terminal(failure: Mapping[str, Any]) -> None:
    authorization = _mapping(failure.get("authorization"), "Program 007 authorization")
    structural = _mapping(failure.get("structural_results"), "Program 007 results")
    disposition = _mapping(failure.get("disposition"), "Program 007 disposition")
    if (
        failure.get("program_id") != predecessor.PROGRAM_ID
        or failure.get("status") != "TERMINAL-FAIL-CONSUMED-NO-RETRY"
        or authorization.get("one_use_consumed") is not True
        or structural.get("metadata_qualification") != "FAIL"
        or disposition.get("retry_allowed") is not False
        or disposition.get("replacement_authority_allowed") is not False
    ):
        raise Program008AuthorityError("Program 007 terminal failure semantics differ")


def _validate_proposal(
    proposal: Mapping[str, Any],
    request_binding: Mapping[str, str],
    analysis: Mapping[str, Any],
    successor: Mapping[str, Any],
    forensic_review: Mapping[str, Any],
) -> None:
    bindings = _mapping(proposal.get("bindings"), "proposal bindings")
    source = _mapping(
        proposal.get("authority_implementation_binding"), "authority implementation binding"
    )
    source_files = _sequence(source.get("source_files"), "authority source files")
    credentials = _mapping(proposal.get("credential_lifecycle"), "credential lifecycle")
    state = _mapping(proposal.get("state_at_proposal"), "proposal state")
    if (
        proposal.get("schema_version")
        != "program-008-corporate-action-metadata-qualification-authority-proposal-v1"
        or proposal.get("proposal_id")
        != ("program-008-corporate-action-metadata-qualification-authority-proposal-2026-08-29-v1")
        or proposal.get("program_id") != PROGRAM_ID
        or proposal.get("status") != READY_STATUS
        or proposal.get("active_authority") is not False
        or proposal.get("future_authority_id") != FUTURE_AUTHORITY_ID
        or proposal.get("source_role") != "BOUNDED AS-OF CORROBORATION + DISCREPANCY DETECTION"
        or proposal.get("authority") != _authority_flags(active=False)
        or any(state.values())
        or bindings
        != {
            "program_007_terminal_failure": _PROGRAM_007_TERMINAL,
            "offline_forensic_analysis": _FORENSIC_ANALYSIS,
            "program_008_qualification_proposal": _PROGRAM_008_PROPOSAL,
            "program_008_forensic_review": _FORENSIC_REVIEW,
            "public_identity_ledger": _LEDGER,
            "request_plan": request_binding,
        }
        or analysis.get("analysis_fingerprint") != _FORENSIC_ANALYSIS["fingerprint"]
        or successor.get("proposal_fingerprint") != _PROGRAM_008_PROPOSAL["fingerprint"]
        or forensic_review.get("review_fingerprint") != _FORENSIC_REVIEW["fingerprint"]
        or credentials
        != {
            "environment_variables": list(CREDENTIAL_NAMES),
            "authentication_header_names": ["APCA-API-KEY-ID", "APCA-API-SECRET-KEY"],
            "presence_preflight": "PASS",
            "missing_at_proposal": [],
            "values_exposed": False,
            "values_stored_hashed_or_logged": False,
            "presence_required_before_root": True,
            "presence_rechecked_under_lock": True,
            "maximum_successful_loads": 1,
            "missing_before_transport_consumes_use": False,
        }
        or proposal.get("qualification") != _expected_qualification()
        or proposal.get("activation_contract") != _expected_activation_contract()
        or proposal.get("raw_first_storage") != _expected_raw_first_storage()
        or len(source_files) != len(_AUTHORITY_SOURCE_PATHS)
        or source.get("base_commit") != STARTING_MAIN
        or not frozen._is_lower_hex(source.get("source_commit"), 40)
        or not frozen._is_lower_hex(source.get("source_tree"), 40)
        or source.get("implementation_root") != fingerprint(source_files)
        or [item.get("path") for item in source_files if isinstance(item, Mapping)]
        != [path.as_posix() for path in _AUTHORITY_SOURCE_PATHS]
    ):
        raise Program008AuthorityError("Program 008 authority proposal semantics differ")


def _validate_review(
    proposal: Mapping[str, Any],
    proposal_binding: Mapping[str, str],
    review: Mapping[str, Any],
) -> None:
    reviewed = _mapping(review.get("reviewed_proposal"), "reviewed proposal")
    implementation = _mapping(review.get("reviewed_implementation"), "reviewed implementation")
    source = _mapping(
        proposal.get("authority_implementation_binding"), "authority implementation binding"
    )
    challenges = _mapping(review.get("required_challenges"), "review challenges")
    verification = _mapping(review.get("verification"), "review verification")
    if (
        review.get("schema_version")
        != (
            "program-008-corporate-action-metadata-qualification-authority-proposal-"
            "independent-review-v1"
        )
        or review.get("review_id")
        != (
            "program-008-corporate-action-metadata-qualification-authority-proposal-"
            "independent-review-2026-08-29-v1"
        )
        or review.get("program_id") != PROGRAM_ID
        or review.get("status") != "PASS-READY-FOR-EXACT-ONE-USE-AUTHORIZATION"
        or review.get("verdict") != "PASS"
        or review.get("findings") != []
        or reviewed
        != {
            **proposal_binding,
            "proposal_id": proposal.get("proposal_id"),
            "proposal_artifact_commit": reviewed.get("proposal_artifact_commit"),
        }
        or not frozen._is_lower_hex(reviewed.get("proposal_artifact_commit"), 40)
        or implementation
        != {
            "source_commit": source.get("source_commit"),
            "source_tree": source.get("source_tree"),
            "implementation_root": source.get("implementation_root"),
        }
        or challenges != _expected_review_challenges()
        or review.get("credential_presence_at_review")
        != [{"name": name, "present": True} for name in CREDENTIAL_NAMES]
        or review.get("authority") != _authority_flags(active=False)
        or review.get("external_authorization_root_generated") is not False
        or verification.get("credential_preflight") != "PASS"
        or verification.get("active_authority") is not False
        or verification.get("claim_created") is not False
        or verification.get("credential_value_loads") != 0
        or verification.get("provider_requests") != 0
        or verification.get("provider_responses") != 0
        or verification.get("provider_bytes") != 0
        or verification.get("ohlcv_requests") != 0
        or verification.get("strategy_calculations") != 0
        or verification.get("strategy_returns") != 0
        or verification.get("controlled_protected_paper_broker_or_live_accessed") is not False
    ):
        raise Program008AuthorityError("Program 008 authority proposal review differs")


def _expected_qualification() -> Mapping[str, Any]:
    return {
        "request_plan_path": REQUEST_PLAN_PATH.as_posix(),
        "endpoint_allowlist": [predecessor.ENDPOINT],
        "only_identity_parameter": "cusips",
        "exact_cusips": list(frozen_request_chain().identities),
        "symbol_filter_allowed": False,
        "secondary_query_allowed": False,
        "provider_role": "BOUNDED AS-OF CORROBORATION + DISCREPANCY DETECTION",
        "negative_event_completeness_proved": False,
        "positive_controls": sorted(metadata.POSITIVE_CONTROLS),
        "positive_control_rule": "exactly one 2-for-1 forward_split on 2025-12-05 each",
        "unexpected_relevant_action": "FAIL-PENDING-PUBLIC-LEDGER-RECONCILIATION",
        "empty_cusip": "ALLOW ONLY WITH ONE UNAMBIGUOUS PUBLIC-LEDGER IDENTITY",
        "matching_nonempty_cusip": "CORROBORATING",
        "conflicting_nonempty_cusip": "HARD FAIL",
        "empty_isin": "ALLOWED",
        "isin_canonical": False,
        "conflicting_nonempty_isin_for_same_event": "HARD FAIL",
        "event_id_semantics": expected_request_plan()["event_id_semantics"],
        "economic_date_semantics": expected_request_plan()["economic_date_semantics"],
        "program_007_response_used_for_pass_fail": False,
        "recognized_event_types": list(predecessor.EVENT_TYPES),
        "types_parameter": "OMITTED",
        "process_date": "retrieval/provider provenance only; returned value inside interval",
        "creation_lag": "UNBOUNDED-NO-PROVIDER-GUARANTEE",
        "raw_first_private_root": PRIVATE_ROOT.as_posix(),
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


def _expected_raw_first_storage() -> Mapping[str, Any]:
    return {
        "root": PRIVATE_ROOT.as_posix(),
        "separate_from_program_007": True,
        "git_ignored": True,
        "absent_until_activation": True,
        "request_intent_before_transport": True,
        "bounded_body_before_parse": True,
        "sha256_receipt_before_parse": True,
        "create_only": True,
        "file_and_directory_fsync": True,
        "credentials_stored": False,
    }


def _expected_review_challenges() -> Mapping[str, str]:
    return {
        "program_007_replayable": "NO",
        "program_008_cusip_chain_previously_executed": "NO",
        "symbol_chain_authorized": "NO",
        "corrected_cusip_semantics_justified": "PASS",
        "empty_isin_optional": "PASS",
        "conflicting_identity_can_fail": "PASS",
        "all_five_positive_controls_required": "PASS",
        "unexpected_ledger_contradiction_can_fail": "PASS",
        "program_007_response_counts_as_program_008_evidence": "NO",
        "budgets_exact": "PASS",
        "credentials_preflight_before_consumption": "PASS",
        "pre_transport_failure_consumes": "NO",
        "retries_possible": "NO",
        "non_corporate_actions_endpoint_authorized": "NO",
        "broader_authority_possible": "NO",
        "altered_artifacts_self_authorize": "NO",
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
                raise Program008AuthorityError("Program 008 control artifact history differs")
            return commits[0]

        request_added = added(REQUEST_PLAN_PATH)
        proposal_added = added(PROPOSAL_PATH)
        review_added = added(REVIEW_PATH)
        source_parent = git("rev-parse", f"{source_commit}^").stdout.strip()
        source_tree = git("rev-parse", f"{source_commit}^{{tree}}").stdout.strip()
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
        raise Program008AuthorityError("Program 008 repository identity is unavailable") from error
    reviewed = _mapping(
        _mapping(controls["review"], "authority proposal review").get("reviewed_proposal"),
        "reviewed proposal",
    )
    lineage = (
        (STARTING_MAIN, source_commit),
        (source_commit, proposal_added),
        (proposal_added, review_added),
        (review_added, head),
    )
    if (
        dirty
        or head != main
        or head != origin_main
        or source_parent != STARTING_MAIN
        or source.get("base_commit") != STARTING_MAIN
        or source.get("source_tree") != source_tree
        or request_added != source_commit
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
        raise Program008AuthorityError("Program 008 reviewed control lineage differs")
    source_files = _sequence(source.get("source_files"), "authority source files")
    for item, path in zip(source_files, _AUTHORITY_SOURCE_PATHS, strict=True):
        binding = _mapping(item, "authority source file")
        expected_sha = str(binding.get("sha256"))
        if (
            frozen._file_sha256(repository / path) != expected_sha
            or frozen._git_file_sha256(repository, source_commit, path) != expected_sha
        ):
            raise Program008AuthorityError("Program 008 reviewed implementation bytes differ")
    return {
        "starting_main": STARTING_MAIN,
        "authority_implementation_commit": source_commit,
        "request_plan_artifact_commit": request_added,
        "proposal_artifact_commit": proposal_added,
        "proposal_review_artifact_commit": review_added,
        "synchronized_main_commit": head,
    }


def _reject_existing_state(root_descriptor: int, *, allow_active: bool = True) -> None:
    allowed = {"run.lock"}
    if allow_active:
        allowed.add("active-authority.json")
    if set(os.listdir(root_descriptor)) - allowed:
        raise Program008AuthorityError("Program 008 one-use authority state already exists")
    if not allow_active and "active-authority.json" in os.listdir(root_descriptor):
        raise Program008AuthorityError("Program 008 one-use authority state already exists")


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Program008AuthorityError(f"Program 008 {label} is invalid JSON") from error
    if type(value) is not dict:
        raise Program008AuthorityError(f"Program 008 {label} is not an object")
    return value


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Program008AuthorityError(f"Program 008 {label} is invalid")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise Program008AuthorityError(f"Program 008 {label} is invalid")
    return value


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
