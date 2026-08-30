"""Exact one-use authority controls for Program 009 raw Alpaca SIP OHLCV."""

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
from datetime import UTC, date, datetime
from http.client import HTTPException
from pathlib import Path
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import Request, build_opener

from . import program_005_alpaca as transport_support
from . import program_006_alpaca as credential_contract
from . import program_007_alpaca as raw_contract
from .calendar import expected_bar_timestamps
from .config import non_broker_subprocess_environment
from .domain import Timeframe
from .fingerprints import canonical_json, fingerprint

PROGRAM_ID = "multi-hour-sector-etf-research-008"
PROGRAM_ORDINAL = 9
STARTING_MAIN = "6622f43c1cae3c0a6bf08899725654fc37eba4be"
FUTURE_AUTHORITY_ID = (
    "program-009-raw-alpaca-sip-ohlcv-structural-qualification-authority-2026-08-30-v1"
)
SOURCE_IMPLEMENTATION_ID = (
    "program-009-raw-alpaca-sip-ohlcv-structural-qualification-implementation-2026-08-30-v1"
)
READY_STATUS = "READY FOR USER AUTHORIZATION"
CONSUMPTION_BOUNDARY = "immediately before first provider transport invocation"
PRIVATE_ROOT = Path(".trading-lab/program-009-raw-alpaca-sip-ohlcv-v1")
CREDENTIAL_NAMES = credential_contract._CREDENTIAL_NAMES

SUCCESSOR_PROPOSAL_PATH = Path(
    "config/research/program-009-raw-alpaca-sip-ohlcv-structural-qualification-proposal-v1.json"
)
REQUEST_PLAN_PATH = Path(
    "config/research/program-009-raw-alpaca-sip-ohlcv-structural-request-plan-v1.json"
)
PROPOSAL_PATH = Path(
    "config/research/program-009-raw-alpaca-sip-ohlcv-structural-qualification-"
    "authority-proposal-v1.json"
)
REVIEW_PATH = Path(
    "config/research/program-009-raw-alpaca-sip-ohlcv-structural-qualification-"
    "authority-proposal-independent-review-v1.json"
)

_PROGRAM_007_TERMINAL = {
    "path": (
        "config/research/program-007-corporate-action-metadata-qualification-"
        "terminal-failure-v1.json"
    ),
    "sha256": "99bc4397909f364efac2f189351bff9ebaae9b886833fc7e0555b3fa5751119f",
    "fingerprint": "991bd9892ee32f4badc08350160a03c3514e0ae1a33dfa623406b534c73bd352",
}
_PROGRAM_008_TERMINAL = {
    "path": (
        "config/research/program-008-corporate-action-metadata-qualification-"
        "terminal-success-v1.json"
    ),
    "sha256": "23bf0e29b4f8b4b4655d7eeb470e4ceb1bc319717c854ec3d82790ef52c1762b",
    "fingerprint": "151091ac4d863d73561afc24dc0138e5326dd237183dfb7da178cb5584871fcd",
}
_PROGRAM_008_TERMINAL_REVIEW = {
    "path": (
        "config/research/program-008-corporate-action-metadata-qualification-"
        "terminal-success-independent-review-v1.json"
    ),
    "sha256": "65eda8a7e6bc6d262b382227db7ca82ecd42dc38caa97d637d6dd1b207a4e6c9",
    "fingerprint": "143f8e5023b96bc950f9ec86d37e966fca42ceefd1c07c691d6d3c2af7c66dad",
}
_RAW_PROPOSAL = {
    "path": "config/research/program-007-alpaca-raw-source-qualification-proposal-v1.json",
    "sha256": "5e92effb829e70d7bbf4636d88519c104565a10bd6f57235169419542cb05b34",
    "fingerprint": "d0ec31e7b6947ed6fe3e1118a6f5536daddae34ebbe9dffcc3b3f932dd9d41c0",
}
_RAW_IMPLEMENTATION = {
    "path": "config/research/program-007-raw-source-contract-implementation-v6.json",
    "sha256": "9903d4c243e94c34879cc5edd086747b4687b33224167db549782229f259b188",
    "fingerprint": "4e611bd85f4f59f045c1cf981ac77cc5359fce7205bedf698bd3f84050c57456",
}
_RAW_IMPLEMENTATION_REVIEW = {
    "path": (
        "config/research/program-007-raw-source-contract-implementation-independent-review-v1.json"
    ),
    "sha256": "e0cb67fed583490fbea484f7067a8ffcb93f663381a6cc51b80c0db3522d8238",
    "fingerprint": "7c6517671aa9a8e0fa9f13e3f1adf94343639c45b49a602b4efd8cc62b3b6841",
}
_LEDGER = {
    "path": "config/research/program-007-unit-changing-action-ledger-v3.json",
    "sha256": "e405529489921a0ec8883aa64e855e6600a99105387cbc9ed2766c82bc0826b1",
    "fingerprint": "37467ced2666cdb716706aa4310e48aa5b0938f168cafadf00f6dec72e336f4f",
}
_SUCCESSOR_PROPOSAL = {
    "path": SUCCESSOR_PROPOSAL_PATH.as_posix(),
    "sha256": "d67da94859eb7d574f9c84abd6c538d0831848d3ad32ae1e5cb390dd7930353b",
    "fingerprint": "64b3e380d1bdf7861afb65ff95882cb72ccf96a645bda382244731311548150f",
}

_AUTHORITY_SOURCE_PATHS = (
    SUCCESSOR_PROPOSAL_PATH,
    REQUEST_PLAN_PATH,
    Path("scripts/check_secrets.py"),
    Path("src/systematic_trading_lab/calendar.py"),
    Path("src/systematic_trading_lab/cli.py"),
    Path("src/systematic_trading_lab/config.py"),
    Path("src/systematic_trading_lab/domain.py"),
    Path("src/systematic_trading_lab/fingerprints.py"),
    Path("src/systematic_trading_lab/program_005_alpaca.py"),
    Path("src/systematic_trading_lab/program_006_alpaca.py"),
    Path("src/systematic_trading_lab/program_007_alpaca.py"),
    Path("src/systematic_trading_lab/program_009_ohlcv_authority.py"),
    Path("tests/unit/test_intraday_source_provenance.py"),
    Path("tests/unit/test_program_009_ohlcv_authority.py"),
)
_AUTHORITY_FIELDS = (
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
_EVIDENCE_KEY = re.compile(r"[a-z0-9][a-z0-9.-]*")


class Program009AuthorityError(ValueError):
    """Fail-closed Program 009 authority error."""


class Program009PostClaimPersistenceError(Program009AuthorityError):
    """Terminal evidence could not be persisted after the one-use claim."""


def frozen_request_chains() -> tuple[raw_contract.RequestChain, ...]:
    chains = raw_contract._frozen_request_chains()
    if len(chains) != 6 or sum(chain.maximum_pages for chain in chains) != 11:
        raise Program009AuthorityError("Program 009 raw request shape differs")
    return chains


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
        raise Program009AuthorityError("Program 009 OHLCV credentials are required")
    return credentials[0], credentials[1]


def expected_successor_proposal() -> Mapping[str, Any]:
    unsigned: dict[str, Any] = {
        "schema_version": ("program-009-raw-alpaca-sip-ohlcv-structural-qualification-proposal-v1"),
        "proposal_id": (
            "program-009-raw-alpaca-sip-ohlcv-structural-qualification-proposal-2026-08-30-v1"
        ),
        "program_ordinal": PROGRAM_ORDINAL,
        "program_id": PROGRAM_ID,
        "status": "FROZEN-PROSPECTIVE-NOT-AUTHORIZED",
        "purpose": "Fresh raw Alpaca SIP five-minute OHLCV structural source qualification only.",
        "lineage": {
            "program_007_metadata": "TERMINAL-FAIL-CONSUMED-NO-RETRY",
            "program_008_metadata": "TERMINAL-PASS-CONSUMED-NO-REPLAY",
            "program_008_authority_reused": False,
            "program_008_metadata_pass_required": True,
        },
        "bindings": {
            "program_007_terminal_failure": _PROGRAM_007_TERMINAL,
            "program_008_terminal_success": _PROGRAM_008_TERMINAL,
            "program_008_terminal_success_review": _PROGRAM_008_TERMINAL_REVIEW,
            "program_007_raw_source_proposal": _RAW_PROPOSAL,
            "program_007_raw_source_implementation": _RAW_IMPLEMENTATION,
            "program_007_raw_source_implementation_review": _RAW_IMPLEMENTATION_REVIEW,
            "public_unit_changing_action_ledger": _LEDGER,
        },
        "source_contract": {
            "method": "GET",
            "endpoint": raw_contract.ENDPOINT,
            "feed": "sip",
            "timeframe": "5Min",
            "adjustment": "raw",
            "sort": "asc",
            "limit": 10000,
            "asof": "2026-07-31",
            "inclusive_bounds": True,
            "redirects": False,
            "provider_adjusted_view_allowed": False,
        },
        "freshness": {
            "programs_002_through_006_audit": "BOUND-BY-PROGRAM-007-RAW-PROPOSAL",
            "program_007_ohlcv_requests": 0,
            "program_008_ohlcv_requests": 0,
            "selected_session_overlap_with_prior_ohlcv": 0,
            "metadata_queries_count_as_ohlcv_exposure": False,
            "selected_session_count": 15,
            "expected_canonical_coordinates": 14742,
        },
        "scientific_contract": {
            "raw_first_private_retention": True,
            "raw_structural_validation_before_rth_projection": True,
            "extended_hours_retained_raw_only": True,
            "canonical_calendar": "XNYS",
            "canonical_completeness": "13/13 symbols on every required RTH bar-open coordinate",
            "early_close_session": "2025-11-28",
            "post_split_session": "2025-12-15",
            "forced_pagination_range": "2023-05-16 through 2023-05-30",
            "split_symbols": ["XLB", "XLE", "XLK", "XLU", "XLY"],
            "split_effective_session": "2025-12-05",
            "split_ratio": "2-for-1",
            "share_volume_rule": (
                "Multiply only split-spanning prior-session same-clock share counts by the "
                "exact new-to-old ratio."
            ),
            "historical_price_adjustment_allowed": False,
            "qualification_strategy_calculations": 0,
        },
        "later_missingness_policy": {
            "binding_path": ("config/research/program-005-free-alpaca-successor-plan-v1.json"),
            "whole_session_exclusion": True,
            "symbol_drop_rerank_fill_or_substitution_allowed": False,
            "qualification_sample_must_be_complete": True,
            "program_006_quarantine_sessions_reused_as_fresh_sample": False,
        },
        "protected_firewall": {
            "controlled_a": False,
            "controlled_b": False,
            "intraday_v3": False,
            "june": False,
            "daily_2018_2019": False,
            "strategic_allocation_21": False,
            "paper": False,
            "broker": False,
            "live": False,
        },
        "authority": _authority_flags(active=False),
    }
    return {**unsigned, "proposal_fingerprint": fingerprint(unsigned)}


def expected_request_plan() -> Mapping[str, Any]:
    chains = frozen_request_chains()
    chain_records: list[dict[str, Any]] = []
    all_coordinates: list[str] = []
    for chain in chains:
        timestamps = expected_bar_timestamps(chain.start, chain.end, Timeframe.FIVE_MINUTES)
        coordinates = [
            f"{symbol}@{timestamp.isoformat().replace('+00:00', 'Z')}"
            for timestamp in timestamps
            for symbol in chain.symbols
        ]
        all_coordinates.extend(coordinates)
        chain_records.append(
            {
                "range_id": chain.chain_id,
                "start": _iso_utc(chain.start),
                "end": _iso_utc(chain.end),
                "session_dates": [session.isoformat() for session in chain.session_dates],
                "symbols": list(chain.symbols),
                "fixed_parameters": [list(parameter) for parameter in chain.parameters],
                "chain_fingerprint": chain.identity,
                "maximum_pages": chain.maximum_pages,
                "expected_canonical_coordinate_count": len(coordinates),
                "expected_canonical_grid_fingerprint": fingerprint(coordinates),
            }
        )
    unsigned: dict[str, Any] = {
        "schema_version": ("program-009-raw-alpaca-sip-ohlcv-structural-request-plan-v1"),
        "request_plan_id": (
            "program-009-raw-alpaca-sip-ohlcv-structural-request-plan-2026-08-30-v1"
        ),
        "program_id": PROGRAM_ID,
        "status": "FROZEN-CREDENTIAL-FREE-NOT-AUTHORIZED",
        "bindings": {
            "successor_qualification_proposal": _SUCCESSOR_PROPOSAL,
            "program_008_terminal_success": _PROGRAM_008_TERMINAL,
            "program_008_terminal_success_review": _PROGRAM_008_TERMINAL_REVIEW,
            "public_unit_changing_action_ledger": _LEDGER,
        },
        "request": {
            "method": "GET",
            "endpoint": raw_contract.ENDPOINT,
            "feed": "sip",
            "timeframe": "5Min",
            "adjustment": "raw",
            "sort": "asc",
            "limit": 10000,
            "asof": "2026-07-31",
            "inclusive_bounds": True,
            "redirects": False,
            "pagination_token": "opaque page_token appended after fixed parameters",
        },
        "universe": list(raw_contract.SYMBOLS),
        "chains": chain_records,
        "expected_canonical_coordinate_count": len(all_coordinates),
        "expected_canonical_grid_fingerprint": fingerprint(all_coordinates),
        "transport_budget": {
            "logical_chain_count": 6,
            "minimum_http_requests": 7,
            "maximum_http_requests": raw_contract.MAXIMUM_HTTP_REQUESTS,
            "minimum_http_responses": 7,
            "maximum_http_responses": raw_contract.MAXIMUM_HTTP_RESPONSES,
            "maximum_response_page_bytes": raw_contract.MAXIMUM_RESPONSE_PAGE_BYTES,
            "bounded_read_bytes": raw_contract.MAXIMUM_RESPONSE_PAGE_BYTES + 1,
            "maximum_total_bytes": raw_contract.MAXIMUM_DOWNLOADED_BYTES,
            "maximum_requests_per_minute": raw_contract.MAXIMUM_REQUESTS_PER_MINUTE,
            "maximum_credential_loads": 1,
            "automatic_retries": raw_contract.AUTOMATIC_TRANSPORT_RETRIES,
            "minimum_forced_pagination_pages": 2,
        },
        "raw_first_storage": _expected_raw_first_storage(),
        "projection": {
            "calendar": "XNYS",
            "timestamp_semantics": "five-minute bar opens",
            "valid_extended_hours": "retain raw and exclude from canonical projection",
            "required_rth_completeness": "exact 13-symbol grid per selected session",
            "missing_required_coordinate": "whole-session exclusion and qualification FAIL",
        },
        "corporate_actions": {
            "ledger": _LEDGER,
            "provider_adjusted_view": False,
            "split_symbols": ["XLB", "XLE", "XLK", "XLU", "XLY"],
            "effective_session": "2025-12-05",
            "pre_action_control": "2025-11-28",
            "post_action_control": "2025-12-15",
            "share_volume_factor": "2",
            "factor_representation": "exact rational",
            "adjusted_historical_price_surface": False,
        },
        "credential_names": list(CREDENTIAL_NAMES),
        "authentication_header_names": ["APCA-API-KEY-ID", "APCA-API-SECRET-KEY"],
        "authority": _authority_flags(active=False),
    }
    return {**unsigned, "request_plan_fingerprint": fingerprint(unsigned)}


def validate_proposal_chain(repository: Path) -> Mapping[str, Any]:
    """Validate immutable proposal inputs without loading credential values."""
    repository = repository.resolve()
    program_007_terminal = _load_static_artifact(
        repository, _PROGRAM_007_TERMINAL, "failure_fingerprint"
    )
    program_008_terminal = _load_static_artifact(
        repository, _PROGRAM_008_TERMINAL, "success_fingerprint"
    )
    program_008_review = _load_static_artifact(
        repository, _PROGRAM_008_TERMINAL_REVIEW, "review_fingerprint"
    )
    raw_proposal = _load_static_artifact(repository, _RAW_PROPOSAL, "proposal_fingerprint")
    _load_static_artifact(repository, _RAW_IMPLEMENTATION, "implementation_fingerprint")
    _load_static_artifact(repository, _RAW_IMPLEMENTATION_REVIEW, "review_fingerprint")
    ledger = _load_static_artifact(repository, _LEDGER, "ledger_fingerprint")
    successor = _load_static_artifact(repository, _SUCCESSOR_PROPOSAL, "proposal_fingerprint")
    _validate_terminal_lineage(program_007_terminal, program_008_terminal, program_008_review)
    raw_contract.frozen_request_chains((repository / _RAW_PROPOSAL["path"]).read_bytes())
    raw_contract.require_action_ledger_admission(ledger)
    if successor != expected_successor_proposal():
        raise Program009AuthorityError("Program 009 successor proposal differs")
    request_plan, request_binding = _load_control_artifact(
        repository, REQUEST_PLAN_PATH, "request_plan_fingerprint", "request plan"
    )
    if request_plan != expected_request_plan():
        raise Program009AuthorityError("Program 009 request plan differs")
    proposal, proposal_binding = _load_control_artifact(
        repository, PROPOSAL_PATH, "proposal_fingerprint", "authority proposal"
    )
    review, review_binding = _load_control_artifact(
        repository, REVIEW_PATH, "review_fingerprint", "authority review"
    )
    _validate_authority_proposal(proposal, request_binding)
    _validate_authority_review(proposal, proposal_binding, review)
    return {
        "proposal": proposal,
        "review": review,
        "request_plan": request_plan,
        "request_plan_binding": request_binding,
        "proposal_binding": proposal_binding,
        "review_binding": review_binding,
        "successor_proposal": successor,
        "raw_proposal": raw_proposal,
    }


def derive_authorization_root(
    repository: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Mapping[str, Any]:
    repository = repository.resolve()
    _reject_terminal_state(repository)
    controls = validate_proposal_chain(repository)
    proposal = _mapping(controls["proposal"], "authority proposal")
    if proposal.get("status") != READY_STATUS:
        raise Program009AuthorityError(
            "Program 009 authority proposal is not ready; no authorization root exists"
        )
    _require_credentials_present(environ)
    lineage = _repository_preflight(repository, proposal, controls)
    unsigned: dict[str, Any] = {
        "schema_version": (
            "program-009-raw-alpaca-sip-ohlcv-structural-qualification-authority-v1"
        ),
        "status": "ACTIVE-ONE-USE",
        "authority_id": FUTURE_AUTHORITY_ID,
        "program_id": PROGRAM_ID,
        "request_plan_fingerprint": controls["request_plan"]["request_plan_fingerprint"],
        "consumption_boundary": CONSUMPTION_BOUNDARY,
        "authority": _authority_flags(active=True),
        "bindings": {
            "program_007_terminal_failure": _PROGRAM_007_TERMINAL,
            "program_008_terminal_success": _PROGRAM_008_TERMINAL,
            "program_008_terminal_success_review": _PROGRAM_008_TERMINAL_REVIEW,
            "program_007_raw_source_proposal": _RAW_PROPOSAL,
            "program_007_raw_source_implementation": _RAW_IMPLEMENTATION,
            "program_007_raw_source_implementation_review": _RAW_IMPLEMENTATION_REVIEW,
            "public_unit_changing_action_ledger": _LEDGER,
            "successor_qualification_proposal": _SUCCESSOR_PROPOSAL,
            "request_plan": controls["request_plan_binding"],
            "authority_proposal": controls["proposal_binding"],
            "authority_review": controls["review_binding"],
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
        raise Program009AuthorityError("Program 009 external authorization root differs")
    root_descriptor = _open_private_root(repository)
    try:
        with _LockedRoot(root_descriptor):
            _reject_existing_state(root_descriptor, allow_active=False)
            authority = derive_authorization_root(repository, environ=environ)
            _require_credentials_present(environ)
            if authority.get("authority_fingerprint") != authorization_root:
                raise Program009AuthorityError("Program 009 external authorization root differs")
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
        raise Program009AuthorityError("Program 009 OHLCV authority is absent") from error
    authority = _json_object(raw, "active authority")
    if (
        authorization_root != expected.get("authority_fingerprint")
        or authority != expected
        or raw != (canonical_json(expected) + "\n").encode()
    ):
        raise Program009AuthorityError(
            "Program 009 OHLCV authority is not exact or externally authorized"
        )
    return authority


def execute_qualification(
    repository: Path,
    authorization_root: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> raw_contract.QualificationResult:
    """Run one reviewed qualification after separate exact-root authorization."""
    repository = repository.resolve()
    _reject_terminal_state(repository)
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
    transport: MockBarsTransport,
) -> raw_contract.QualificationResult:
    if type(transport) is not MockBarsTransport:
        raise Program009AuthorityError("Program 009 test execution requires a finite mock")
    if environ is os.environ:
        raise Program009AuthorityError(
            "Program 009 test execution requires an explicit environment"
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
    mock_transport: MockBarsTransport | None,
) -> raw_contract.QualificationResult:
    repository = repository.resolve()
    _require_credentials_present(environ)
    load_active_authority(repository, authorization_root, environ=environ)
    root_descriptor = _open_private_root(repository)
    claim_written = False
    budget = _Budget()
    try:
        with _LockedRoot(root_descriptor):
            _reject_existing_state(root_descriptor)
            authority = load_active_authority(repository, authorization_root, environ=environ)
            ledger = raw_contract.load_action_ledger(repository / _LEDGER["path"])
            raw_contract.require_action_ledger_admission(ledger)
            _validate_split_controls(ledger)
            _require_credentials_present(environ)
            key_id, secret_key = read_credentials(environ)
            client = _AlpacaBarsClient(key_id, secret_key) if mock_transport is None else None

            def writer(key: str, payload: bytes) -> None:
                _append_persistent_evidence(root_descriptor, key, payload)

            def response_for(intent: raw_contract.RequestIntent) -> raw_contract.RawResponse:
                def consume() -> None:
                    nonlocal claim_written
                    if claim_written:
                        return
                    writer(
                        "claim.json",
                        canonical_json(
                            {
                                "schema_version": "program-009-private-ohlcv-claim-v1",
                                "authority_id": authority["authority_id"],
                                "authority_fingerprint": authority["authority_fingerprint"],
                                "request_plan_fingerprint": authority["request_plan_fingerprint"],
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

                if mock_transport is not None:
                    consume()
                    return mock_transport.get(intent)
                assert client is not None
                return client.get(intent, consume)

            try:
                result = _execute_all_chains(budget, response_for, writer)
                if mock_transport is not None:
                    mock_transport.require_exhausted()
            except Exception as error:
                if claim_written:
                    try:
                        writer(
                            "terminal-failure.json",
                            canonical_json(
                                {
                                    "schema_version": "program-009-private-ohlcv-failure-v1",
                                    "status": "FAIL-CONSUMED-NO-RETRY",
                                    "failure_class": type(error).__name__,
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
                                }
                            ).encode(),
                        )
                    except Exception as persistence_error:
                        raise Program009PostClaimPersistenceError(
                            "Program 009 terminal failure persistence failed after "
                            f"{type(error).__name__}; the claim fallback seals "
                            "FAIL-CONSUMED-NO-RETRY"
                        ) from persistence_error
                raise
            try:
                writer(
                    "qualification-receipt.json",
                    canonical_json(
                        {
                            "schema_version": "program-009-private-ohlcv-receipt-v1",
                            "status": "STRUCTURAL-QUALIFICATION-PASS",
                            "authority_id": authority["authority_id"],
                            "request_count": budget.requests,
                            "response_count": budget.responses,
                            "response_bytes": budget.response_bytes,
                            "raw_row_count": result.raw_row_count,
                            "canonical_row_count": result.canonical_row_count,
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
            except Exception as error:
                raise Program009PostClaimPersistenceError(
                    "Program 009 PASS receipt persistence failed; the claim fallback seals "
                    "FAIL-CONSUMED-NO-RETRY"
                ) from error
            return result
    finally:
        os.close(root_descriptor)


class MockBarsTransport:
    """Finite canned responses for lifecycle tests; no credentials cross this boundary."""

    __slots__ = ("_intents", "_responses")

    def __init__(self, responses: Sequence[raw_contract.RawResponse]) -> None:
        if (
            type(responses) not in {list, tuple}
            or not 1 <= len(responses) <= raw_contract.MAXIMUM_HTTP_RESPONSES
            or any(type(response) is not raw_contract.RawResponse for response in responses)
        ):
            raise Program009AuthorityError("Program 009 mock OHLCV responses are invalid")
        self._responses = tuple(responses)
        self._intents: list[raw_contract.RequestIntent] = []

    @property
    def intents(self) -> tuple[raw_contract.RequestIntent, ...]:
        return tuple(self._intents)

    def get(self, intent: raw_contract.RequestIntent) -> raw_contract.RawResponse:
        _validate_intent(intent)
        index = len(self._intents)
        self._intents.append(intent)
        if index >= len(self._responses):
            raise Program009AuthorityError("Program 009 mock OHLCV response is missing")
        return self._responses[index]

    def require_exhausted(self) -> None:
        if len(self._intents) != len(self._responses):
            raise Program009AuthorityError("Program 009 mock OHLCV responses remain unused")


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
            raise Program009AuthorityError("Program 009 OHLCV credentials are invalid")
        self._headers = {
            "Accept": "application/json",
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
        }
        self._opener = build_opener(transport_support._NoRedirect())
        self._pace = transport_support.RequestPacer() if pace is None else pace

    def get(
        self,
        intent: raw_contract.RequestIntent,
        before_transport: Callable[[], None],
    ) -> raw_contract.RawResponse:
        _validate_intent(intent)
        request = Request(intent.url, headers=self._headers, method="GET")
        _validate_http_request(request)
        self._pace()
        before_transport()
        try:
            with self._opener.open(request, timeout=30) as response:
                return raw_contract.RawResponse(
                    int(response.status),
                    response.read(raw_contract.MAXIMUM_RESPONSE_PAGE_BYTES + 1),
                )
        except HTTPError as error:
            try:
                return raw_contract.RawResponse(
                    error.code,
                    error.read(raw_contract.MAXIMUM_RESPONSE_PAGE_BYTES + 1),
                )
            finally:
                error.close()
        except (HTTPException, TimeoutError, ConnectionError, URLError, OSError) as error:
            raise Program009AuthorityError(
                "Program 009 OHLCV transport is ambiguous; zero-retry use is consumed"
            ) from error


class _Budget:
    def __init__(self) -> None:
        self.requests = 0
        self.responses = 0
        self.response_bytes = 0

    def reserve_request(self) -> None:
        if self.requests >= raw_contract.MAXIMUM_HTTP_REQUESTS:
            raise Program009AuthorityError("Program 009 OHLCV request ceiling exceeded")
        self.requests += 1

    def accept_response(self, body: bytes) -> None:
        if self.responses >= raw_contract.MAXIMUM_HTTP_RESPONSES:
            raise Program009AuthorityError("Program 009 OHLCV response ceiling exceeded")
        self.responses += 1
        self.response_bytes += len(body)
        if len(body) > raw_contract.MAXIMUM_RESPONSE_PAGE_BYTES:
            raise Program009AuthorityError("Program 009 OHLCV page exceeds 8 MiB")
        if self.response_bytes > raw_contract.MAXIMUM_DOWNLOADED_BYTES:
            raise Program009AuthorityError("Program 009 OHLCV byte ceiling exceeded")


def _execute_all_chains(
    budget: _Budget,
    response_for: Callable[[raw_contract.RequestIntent], raw_contract.RawResponse],
    writer: Callable[[str, bytes], None],
) -> raw_contract.QualificationResult:
    results = tuple(
        _execute_chain(chain, budget, response_for, writer) for chain in frozen_request_chains()
    )
    pagination = next(
        result
        for result in results
        if result.chain.chain_id == "pagination-2023-05-16-to-2023-05-30"
    )
    if budget.requests < 7 or budget.responses < 7 or len(pagination.pages) < 2:
        raise Program009AuthorityError("Program 009 forced pagination was not exercised")
    result = raw_contract.QualificationResult(results)
    if result.canonical_row_count != 14_742:
        raise Program009AuthorityError("Program 009 canonical coordinate count differs")
    return result


def _execute_chain(
    chain: raw_contract.RequestChain,
    budget: _Budget,
    response_for: Callable[[raw_contract.RequestIntent], raw_contract.RawResponse],
    writer: Callable[[str, bytes], None],
) -> raw_contract.ChainResult:
    rows: list[raw_contract.RawBar] = []
    pages: list[raw_contract.PageEvidence] = []
    seen_coordinates: set[tuple[str, datetime]] = set()
    seen_hashes: set[str] = set()
    seen_tokens: set[str] = set()
    incoming_token: str | None = None
    for page_index in range(1, chain.maximum_pages + 1):
        budget.reserve_request()
        intent = raw_contract.RequestIntent(
            chain.chain_id,
            chain.identity,
            page_index,
            chain.url(incoming_token),
            incoming_token,
        )
        _validate_intent(intent)
        prefix = f"{chain.chain_id}-{page_index:02d}"
        writer(f"{prefix}.intent.json", canonical_json(intent).encode())
        response = response_for(intent)
        retained = response.body[: raw_contract.MAXIMUM_RESPONSE_PAGE_BYTES + 1]
        writer(f"{prefix}.body", retained)
        response_sha256 = hashlib.sha256(retained).hexdigest()
        writer(
            f"{prefix}.receipt.json",
            canonical_json(
                {
                    "status": response.status,
                    "retained_response_bytes": len(retained),
                    "response_truncated": len(response.body) != len(retained),
                    "response_sha256": response_sha256,
                }
            ).encode(),
        )
        budget.accept_response(retained)
        _raise_for_status(response.status)
        if response_sha256 in seen_hashes:
            raise Program009AuthorityError("Program 009 OHLCV response page repeats")
        page_rows, outgoing_token = raw_contract.parse_raw_page(retained, chain)
        coordinates = {row.coordinate for row in page_rows}
        if seen_coordinates & coordinates:
            raise Program009AuthorityError("Program 009 OHLCV coordinate repeats across pages")
        if outgoing_token is not None:
            if outgoing_token in seen_tokens or outgoing_token == incoming_token:
                raise Program009AuthorityError("Program 009 OHLCV pagination token repeats")
            if not page_rows:
                raise Program009AuthorityError("Program 009 OHLCV nonterminal page is empty")
            if page_index == chain.maximum_pages:
                raise Program009AuthorityError("Program 009 OHLCV page ceiling exceeded")
        canonical = raw_contract.project_rth(page_rows, chain)
        page_identity = fingerprint(
            {
                "chain_identity": chain.identity,
                "page_index": page_index,
                "incoming_page_token": incoming_token,
                "outgoing_page_token": outgoing_token,
                "response_sha256": response_sha256,
            }
        )
        pages.append(
            raw_contract.PageEvidence(
                chain.chain_id,
                chain.identity,
                page_index,
                intent.url,
                incoming_token,
                outgoing_token,
                response_sha256,
                len(retained),
                page_identity,
                len(page_rows),
                len(canonical),
                len(page_rows) - len(canonical),
            )
        )
        seen_hashes.add(response_sha256)
        seen_coordinates.update(coordinates)
        rows.extend(page_rows)
        if outgoing_token is None:
            break
        seen_tokens.add(outgoing_token)
        incoming_token = outgoing_token
    else:
        raise Program009AuthorityError("Program 009 OHLCV chain did not terminate")

    raw_rows = tuple(sorted(rows))
    canonical_rows = raw_contract.project_rth(raw_rows, chain)
    expected = {
        (symbol, timestamp)
        for symbol in chain.symbols
        for timestamp in expected_bar_timestamps(chain.start, chain.end, Timeframe.FIVE_MINUTES)
    }
    if {row.coordinate for row in canonical_rows} != expected:
        raise Program009AuthorityError(
            "Program 009 canonical RTH completeness failed; the whole session is ineligible"
        )
    return raw_contract.ChainResult(chain, raw_rows, canonical_rows, tuple(pages))


def _raise_for_status(status: int) -> None:
    if status == 200:
        return
    if status == 401:
        raise Program009AuthorityError(
            "OHLCV-AUTHENTICATION-FAIL-CONSUMED-NO-RETRY: Alpaca returned HTTP 401"
        )
    if status == 403:
        raise Program009AuthorityError(
            "OHLCV-ACCESS-FAIL-CONSUMED-NO-RETRY-NO-PURCHASE: Alpaca returned HTTP 403"
        )
    if status == 429:
        raise Program009AuthorityError(
            "OHLCV-ACCESS-FAIL-CONSUMED-NO-RETRY: Alpaca returned HTTP 429"
        )
    if 300 <= status < 400:
        raise Program009AuthorityError("Program 009 OHLCV redirect attempt rejected")
    if 500 <= status < 600:
        raise Program009AuthorityError(
            f"OHLCV-ACCESS-FAIL-CONSUMED-NO-RETRY: Alpaca returned HTTP {status}"
        )
    raise Program009AuthorityError(f"Program 009 OHLCV returned unexpected HTTP {status}")


def _validate_intent(intent: raw_contract.RequestIntent) -> None:
    chains = {chain.chain_id: chain for chain in frozen_request_chains()}
    chain = chains.get(intent.chain_id) if type(intent) is raw_contract.RequestIntent else None
    if (
        chain is None
        or intent.chain_identity != chain.identity
        or type(intent.page_index) is not int
        or not 1 <= intent.page_index <= chain.maximum_pages
        or intent.url != chain.url(intent.incoming_page_token)
        or intent.method != "GET"
        or intent.redirects is not False
    ):
        raise Program009AuthorityError("Program 009 OHLCV request intent differs")


def _validate_http_request(request: Request) -> None:
    parsed = urlsplit(request.full_url)
    try:
        parameters = tuple(parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True))
    except ValueError as error:
        raise Program009AuthorityError("Program 009 OHLCV endpoint or query differs") from error
    matching = []
    for chain in frozen_request_chains():
        page_token = None
        if len(parameters) == len(chain.parameters) + 1 and parameters[-1][0] == "page_token":
            page_token = parameters[-1][1]
        query_is_exact = (
            parameters == chain.parameters
            if page_token is None
            else bool(page_token) and parameters[:-1] == chain.parameters
        )
        if query_is_exact and request.full_url == chain.url(page_token):
            matching.append(chain)
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
    ):
        raise Program009AuthorityError("Program 009 OHLCV endpoint or query differs")


def _authority_flags(*, active: bool) -> Mapping[str, bool]:
    if set(_AUTHORITY_FIELDS) != raw_contract._AUTHORITY_FIELDS:
        raise Program009AuthorityError("Program 009 authority field set differs")
    return {key: active and key in _ENABLED_AUTHORITY for key in _AUTHORITY_FIELDS}


def _expected_raw_first_storage() -> Mapping[str, Any]:
    return {
        "root": PRIVATE_ROOT.as_posix(),
        "separate_from_programs_006_007_008": True,
        "git_ignored": True,
        "absent_until_activation": True,
        "request_intent_before_transport": True,
        "claim_immediately_before_first_transport": True,
        "claim_defaults_to_terminal_failure_without_valid_pass_receipt": True,
        "bounded_body_before_parse": True,
        "sha256_receipt_before_parse": True,
        "create_only": True,
        "file_and_directory_fsync": True,
        "credentials_stored": False,
    }


def _expected_activation_contract() -> Mapping[str, Any]:
    return {
        "future_authority_id": FUTURE_AUTHORITY_ID,
        "external_authorization_root_required": True,
        "external_authorization_root_generated": False,
        "caller_supplied_root_required": True,
        "under_lock_full_revalidation": True,
        "consumption_boundary": CONSUMPTION_BOUNDARY,
        "sent_or_ambiguous_transport_consumes_use": True,
        "pre_transport_failure_consumes_use": False,
        "automatic_retries": 0,
        "second_execution_allowed": False,
    }


def _expected_qualification() -> Mapping[str, Any]:
    plan = expected_request_plan()
    return {
        "request_plan_path": REQUEST_PLAN_PATH.as_posix(),
        "request_plan_id": plan["request_plan_id"],
        "request_plan_fingerprint": plan["request_plan_fingerprint"],
        "endpoint_allowlist": [raw_contract.ENDPOINT],
        "universe": list(raw_contract.SYMBOLS),
        "range_ids": [chain.chain_id for chain in frozen_request_chains()],
        "logical_chain_count": 6,
        "expected_canonical_coordinates": 14_742,
        "transport_budget": plan["transport_budget"],
        "raw_only": True,
        "provider_adjusted_view": False,
        "raw_first_storage": True,
        "rth_projection_after_raw_validation": True,
        "valid_extended_hours_retained_raw_only": True,
        "early_close_calendar_derived": True,
        "forced_pagination_minimum_pages": 2,
        "public_ledger_fingerprint": _LEDGER["fingerprint"],
        "full_acquisition": False,
        "dataset_admission": False,
        "strategy_calculations": 0,
    }


def _expected_review_challenges() -> Mapping[str, str]:
    return {
        "program_008_metadata_terminal_pass": "PASS",
        "program_008_metadata_authority_replayable": "NO",
        "sample_previously_observed_as_ohlcv": "NO",
        "metadata_exposure_breaks_ohlcv_freshness": "NO",
        "non_raw_sip_view_possible": "NO",
        "provider_adjusted_bars_possible": "NO",
        "raw_parse_before_persistence": "NO",
        "extended_hours_forced_into_canonical": "NO",
        "completeness_before_rth_projection": "NO",
        "early_close_assumed_to_have_78_bars": "NO",
        "post_split_control_invalid": "NO",
        "five_split_events_unbound": "NO",
        "share_volume_normalization_broader_than_split_crossing": "NO",
        "adjusted_historical_price_surface_created": "NO",
        "pagination_range_cannot_require_pagination": "NO",
        "transport_budgets_unbounded": "NO",
        "retries_possible": "NO",
        "full_exposed_acquisition_possible": "NO",
        "real_dataset_admission_possible": "NO",
        "strategy_calculation_possible": "NO",
        "controlled_protected_paper_broker_or_live_possible": "NO",
        "changed_artifact_self_authorizes": "NO",
    }


def _validate_terminal_lineage(
    program_007: Mapping[str, Any],
    program_008: Mapping[str, Any],
    program_008_review: Mapping[str, Any],
) -> None:
    p7_authorization = _mapping(program_007.get("authorization"), "Program 007 authorization")
    p7_results = _mapping(program_007.get("structural_results"), "Program 007 results")
    p7_disposition = _mapping(program_007.get("disposition"), "Program 007 disposition")
    p7_protected = _mapping(program_007.get("protected_state"), "Program 007 protected state")
    p8_authorization = _mapping(program_008.get("authorization"), "Program 008 authorization")
    p8_results = _mapping(program_008.get("structural_results"), "Program 008 results")
    p8_disposition = _mapping(program_008.get("disposition"), "Program 008 disposition")
    p8_protected = _mapping(program_008.get("protected_state"), "Program 008 protected state")
    if (
        program_007.get("status") != "TERMINAL-FAIL-CONSUMED-NO-RETRY"
        or p7_authorization.get("one_use_consumed") is not True
        or p7_results.get("metadata_qualification") != "FAIL"
        or p7_disposition.get("retry_allowed") is not False
        or p7_disposition.get("replacement_authority_allowed") is not False
        or p7_protected.get("ohlcv_requests") != 0
        or program_008.get("status") != "TERMINAL-PASS-CONSUMED-NO-REPLAY"
        or p8_authorization.get("one_use_consumed") is not True
        or p8_results.get("metadata_qualification") != "PASS"
        or p8_disposition.get("metadata_authority_active") is not False
        or p8_disposition.get("metadata_replay_allowed") is not False
        or p8_disposition.get("replacement_metadata_authority_allowed") is not False
        or p8_protected.get("ohlcv_requests") != 0
        or program_008_review.get("verdict") != "PASS"
        or program_008_review.get("findings") != []
    ):
        raise Program009AuthorityError("Program 009 metadata prerequisite differs")


def _validate_split_controls(ledger: Mapping[str, Any]) -> None:
    for symbol in ("XLB", "XLE", "XLK", "XLU", "XLY"):
        factor = raw_contract.share_unit_factor(
            ledger, symbol, date(2025, 11, 28), date(2025, 12, 15)
        )
        if factor.numerator != 2 or factor.denominator != 1:
            raise Program009AuthorityError("Program 009 split-volume factor differs")


def _validate_authority_proposal(
    proposal: Mapping[str, Any], request_binding: Mapping[str, str]
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
        != ("program-009-raw-alpaca-sip-ohlcv-structural-qualification-authority-proposal-v1")
        or proposal.get("proposal_id")
        != (
            "program-009-raw-alpaca-sip-ohlcv-structural-qualification-"
            "authority-proposal-2026-08-30-v1"
        )
        or proposal.get("program_id") != PROGRAM_ID
        or proposal.get("status") != READY_STATUS
        or proposal.get("active_authority") is not False
        or proposal.get("future_authority_id") != FUTURE_AUTHORITY_ID
        or proposal.get("source_implementation_id") != SOURCE_IMPLEMENTATION_ID
        or proposal.get("authority") != _authority_flags(active=False)
        or any(state.values())
        or bindings
        != {
            "program_007_terminal_failure": _PROGRAM_007_TERMINAL,
            "program_008_terminal_success": _PROGRAM_008_TERMINAL,
            "program_008_terminal_success_review": _PROGRAM_008_TERMINAL_REVIEW,
            "program_007_raw_source_proposal": _RAW_PROPOSAL,
            "program_007_raw_source_implementation": _RAW_IMPLEMENTATION,
            "program_007_raw_source_implementation_review": _RAW_IMPLEMENTATION_REVIEW,
            "public_unit_changing_action_ledger": _LEDGER,
            "successor_qualification_proposal": _SUCCESSOR_PROPOSAL,
            "request_plan": request_binding,
        }
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
        or source.get("implementation_id") != SOURCE_IMPLEMENTATION_ID
        or source.get("base_commit") != STARTING_MAIN
        or not transport_support._is_lower_hex(source.get("source_commit"), 40)
        or not transport_support._is_lower_hex(source.get("source_tree"), 40)
        or source.get("implementation_root") != fingerprint(source_files)
        or [item.get("path") for item in source_files if isinstance(item, Mapping)]
        != [path.as_posix() for path in _AUTHORITY_SOURCE_PATHS]
    ):
        raise Program009AuthorityError("Program 009 authority proposal semantics differ")


def _validate_authority_review(
    proposal: Mapping[str, Any],
    proposal_binding: Mapping[str, str],
    review: Mapping[str, Any],
) -> None:
    reviewed = _mapping(review.get("reviewed_proposal"), "reviewed proposal")
    implementation = _mapping(review.get("reviewed_implementation"), "reviewed implementation")
    source = _mapping(
        proposal.get("authority_implementation_binding"), "authority implementation binding"
    )
    verification = _mapping(review.get("verification"), "review verification")
    if (
        review.get("schema_version")
        != (
            "program-009-raw-alpaca-sip-ohlcv-structural-qualification-"
            "authority-proposal-independent-review-v1"
        )
        or review.get("review_id")
        != (
            "program-009-raw-alpaca-sip-ohlcv-structural-qualification-"
            "authority-proposal-independent-review-2026-08-30-v1"
        )
        or review.get("program_id") != PROGRAM_ID
        or review.get("status") != "PASS-READY-FOR-EXACT-ONE-USE-OHLCV-STRUCTURAL-AUTHORIZATION"
        or review.get("verdict") != "PASS"
        or review.get("findings") != []
        or reviewed
        != {
            **proposal_binding,
            "proposal_id": proposal.get("proposal_id"),
            "proposal_artifact_commit": reviewed.get("proposal_artifact_commit"),
        }
        or not transport_support._is_lower_hex(reviewed.get("proposal_artifact_commit"), 40)
        or implementation
        != {
            "implementation_id": SOURCE_IMPLEMENTATION_ID,
            "source_commit": source.get("source_commit"),
            "source_tree": source.get("source_tree"),
            "implementation_root": source.get("implementation_root"),
        }
        or review.get("required_challenges") != _expected_review_challenges()
        or review.get("credential_presence_at_review")
        != [{"name": name, "present": True} for name in CREDENTIAL_NAMES]
        or review.get("authority") != _authority_flags(active=False)
        or review.get("external_authorization_root_generated") is not False
        or verification.get("credential_preflight") != "PASS"
        or verification.get("active_authority") is not False
        or verification.get("claim_created") is not False
        or verification.get("private_root_created") is not False
        or verification.get("credential_value_loads") != 0
        or verification.get("provider_requests") != 0
        or verification.get("provider_responses") != 0
        or verification.get("provider_bytes") != 0
        or verification.get("strategy_calculations") != 0
        or verification.get("strategy_returns") != 0
        or verification.get("controlled_protected_paper_broker_or_live_accessed") is not False
    ):
        raise Program009AuthorityError("Program 009 authority review semantics differ")


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
                raise Program009AuthorityError("Program 009 control artifact history differs")
            return commits[0]

        successor_added = added(SUCCESSOR_PROPOSAL_PATH)
        request_added = added(REQUEST_PLAN_PATH)
        proposal_added = added(PROPOSAL_PATH)
        review_added = added(REVIEW_PATH)
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
        raise Program009AuthorityError("Program 009 repository identity is unavailable") from error
    reviewed = _mapping(
        _mapping(controls["review"], "authority review").get("reviewed_proposal"),
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
        or source.get("base_commit") != STARTING_MAIN
        or source.get("source_tree") != source_tree
        or successor_added != source_commit
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
        raise Program009AuthorityError("Program 009 reviewed control lineage differs")
    source_files = _sequence(source.get("source_files"), "authority source files")
    for item, path in zip(source_files, _AUTHORITY_SOURCE_PATHS, strict=True):
        binding = _mapping(item, "authority source file")
        expected_sha = str(binding.get("sha256"))
        if (
            transport_support._file_sha256(repository / path) != expected_sha
            or transport_support._git_file_sha256(repository, source_commit, path) != expected_sha
        ):
            raise Program009AuthorityError("Program 009 reviewed implementation bytes differ")
    return {
        "starting_main": STARTING_MAIN,
        "authority_implementation_commit": source_commit,
        "successor_proposal_artifact_commit": successor_added,
        "request_plan_artifact_commit": request_added,
        "proposal_artifact_commit": proposal_added,
        "proposal_review_artifact_commit": review_added,
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
            raise Program009AuthorityError("Program 009 evidence lock is not private")
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)

    def __exit__(self, *_args: object) -> None:
        assert self._handle is not None
        self._handle.close()


def _open_private_root(repository: Path) -> int:
    if not isinstance(repository, Path):
        raise Program009AuthorityError("Program 009 repository root is invalid")
    repository = repository.resolve()
    if not repository.is_dir():
        raise Program009AuthorityError("Program 009 repository root is absent")
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
            raise Program009AuthorityError("Program 009 private evidence root is not private")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _append_persistent_evidence(root_descriptor: int, key: str, payload: bytes) -> None:
    if type(key) is not str or _EVIDENCE_KEY.fullmatch(key) is None or type(payload) is not bytes:
        raise Program009AuthorityError("Program 009 persistent evidence entry is invalid")
    try:
        descriptor = os.open(
            key,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=root_descriptor,
        )
    except FileExistsError:
        raise Program009AuthorityError(
            f"Program 009 persistent evidence already exists: {key}"
        ) from None
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.fsync(root_descriptor)


def _reject_existing_state(root_descriptor: int, *, allow_active: bool = True) -> None:
    allowed = {"run.lock"}
    if allow_active:
        allowed.add("active-authority.json")
    entries = set(os.listdir(root_descriptor))
    if entries - allowed or (not allow_active and "active-authority.json" in entries):
        raise Program009AuthorityError("Program 009 one-use authority state already exists")


def _require_credentials_present(environ: Mapping[str, str] | None) -> None:
    missing = credential_presence_preflight(environ)
    if missing:
        raise Program009AuthorityError("Program 009 credentials missing: " + ", ".join(missing))


def _load_static_artifact(
    repository: Path,
    binding: Mapping[str, str],
    fingerprint_field: str,
) -> Mapping[str, Any]:
    path = repository / binding["path"]
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise Program009AuthorityError(f"Program 009 binding is absent: {path.name}") from error
    payload = _json_object(raw, path.name)
    if (
        hashlib.sha256(raw).hexdigest() != binding["sha256"]
        or payload.get(fingerprint_field) != binding["fingerprint"]
    ):
        raise Program009AuthorityError(f"Program 009 binding differs: {path.name}")
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
        raise Program009AuthorityError(f"Program 009 {label} is absent") from error
    payload = _json_object(raw, label)
    unsigned = dict(payload)
    stored = unsigned.pop(fingerprint_field, None)
    if not transport_support._is_lower_hex(stored, 64) or stored != fingerprint(unsigned):
        raise Program009AuthorityError(f"Program 009 {label} differs")
    return payload, {
        "path": relative.as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "fingerprint": stored,
    }


def _reject_terminal_state(repository: Path) -> None:
    if (
        repository
        / "config/research/program-009-raw-alpaca-sip-ohlcv-structural-qualification-terminal.json"
    ).exists():
        raise Program009AuthorityError("Program 009 OHLCV authority is terminally revoked")


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Program009AuthorityError(f"Program 009 {label} is invalid JSON") from error
    if type(value) is not dict:
        raise Program009AuthorityError(f"Program 009 {label} is not an object")
    return value


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Program009AuthorityError(f"Program 009 {label} is invalid")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise Program009AuthorityError(f"Program 009 {label} is invalid")
    return value


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise Program009AuthorityError("Program 009 timestamp must be UTC")
    return value.isoformat().replace("+00:00", "Z")


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
