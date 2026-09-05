from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import multiprocessing
import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pytest import CaptureFixture, MonkeyPatch

import systematic_trading_lab.cli as base_cli
import systematic_trading_lab.intraday_fed_policy_absorption_001_cli as dispatcher
import systematic_trading_lab.program_006_alpaca as credential_contract
import systematic_trading_lab.program_007_alpaca as raw_contract
import systematic_trading_lab.program_011_ohlcv as program_011
import systematic_trading_lab.program_011_ohlcv_authority as git_controls
import systematic_trading_lab.program_012_ohlcv as science
import systematic_trading_lab.program_012_ohlcv_authority as predecessor
import systematic_trading_lab.program_013_ohlcv_authority as program_013
import systematic_trading_lab.program_014_ohlcv_authority as authority
import systematic_trading_lab.standing_research_authority as standing
from systematic_trading_lab.fingerprints import canonical_json, fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]


class _AbruptExit(BaseException):
    pass


@pytest.fixture(autouse=True)
def _reset_process_credential_latch(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(authority, "_PROCESS_CREDENTIAL_PID", None)


@pytest.fixture(autouse=True)
def _allow_historical_runtime_tests(monkeypatch: MonkeyPatch) -> None:
    reject_terminal_state = authority._reject_terminal_state

    def reject(repository: Path) -> None:
        terminal = repository / authority.PUBLIC_TERMINAL_PATH
        if repository.resolve() == _REPOSITORY.resolve() or os.path.lexists(terminal):
            reject_terminal_state(repository)

    monkeypatch.setattr(authority, "_reject_terminal_state", reject)


def _credentials() -> dict[str, str]:
    return {
        authority.CREDENTIAL_NAMES[0]: "synthetic-key-material",
        authority.CREDENTIAL_NAMES[1]: "synthetic-secret-material",
    }


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", "-C", str(repository), *arguments),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _active_authority() -> dict[str, Any]:
    return {
        "schema_version": "program-014-raw-sip-recovery-active-authority-v1",
        "status": "ACTIVE-ONE-USE-RECOVERABLE",
        "authority_id": authority.CHILD_AUTHORITY_ID,
        "program_id": authority.PROGRAM_ID,
        "activation_mode": "INTERNAL-STANDING-MANDATE-DERIVATION",
        "external_authorization_root_required": False,
        "child_identity_fingerprint": "b" * 64,
        "operation_manifest": authority.OPERATION_MANIFEST,
        "consumption_boundary": authority.CONSUMPTION_BOUNDARY,
        "authority": {name: True for name in authority._ENABLED_AUTHORITY},
        "runtime_binding": {
            "source_commit": "c" * 40,
            "source_tree": "d" * 40,
            "implementation_root": "e" * 64,
        },
        "control_lineage": {
            "runtime_source_commit": "c" * 40,
            "runtime_source_tree": "d" * 40,
            "runtime_implementation_root": "e" * 64,
            "synchronized_main_commit": "f" * 40,
        },
        "authority_fingerprint": "a" * 64,
    }


def _request(index: int = 0) -> program_011.SessionRequest:
    return science.acquisition_requests()[index]


def _body(
    request: program_011.SessionRequest,
    coordinate_index: int,
    token: str | None,
) -> bytes:
    timestamp = request.grid[coordinate_index].isoformat().replace("+00:00", "Z")
    return json.dumps(
        {
            "bars": {
                "IWM": [
                    {
                        "t": timestamp,
                        "o": 100,
                        "h": 101,
                        "l": 99,
                        "c": 100.5,
                        "v": 10,
                        "n": 2,
                        "vw": 100.25,
                    }
                ]
            },
            "next_page_token": token,
        },
        separators=(",", ":"),
    ).encode()


def _predecessor_state(
    request: program_011.SessionRequest | None = None,
    *,
    completed_responses: int = 0,
) -> authority._PredecessorState:
    request = _request() if request is None else request
    program_012_manifest = {
        "completed_sessions": [],
        "completed_request_count": 0,
        "completed_response_count": 0,
        "completed_response_bytes": 0,
        "frontier": {
            "session": request.session.isoformat(),
            "page_index": 1,
            "request_identity": request.identity,
            "incoming_page_token": None,
            "url": request.url(),
            "intent_sha256": "0" * 64,
            "body_present": False,
            "receipt_present": False,
            "later_evidence_present": False,
        },
    }
    program_012_payload = (canonical_json(program_012_manifest) + "\n").encode()
    program_012_state = program_013._PredecessorState(
        manifest=program_012_manifest,
        payload=program_012_payload,
        sha256=hashlib.sha256(program_012_payload).hexdigest(),
        active_authority={"authority_fingerprint": "1" * 64},
        source_commit="2" * 40,
        frontier_request_index=0,
        latest_response_at=None,
    )
    manifest: dict[str, Any] = {
        "schema_version": "program-014-private-predecessor-import-manifest-v1",
        "program_id": authority.PROGRAM_ID,
        "completed_sessions": [],
        "completed_request_count": completed_responses,
        "completed_response_count": completed_responses,
        "completed_response_bytes": 0,
        "consumed_intent_without_response_count": 2,
        "frontier": {
            "session": request.session.isoformat(),
            "page_index": 1,
            "request_identity": request.identity,
            "incoming_page_token": None,
            "url": request.url(),
            "intent_sha256": "1" * 64,
            "body_present": False,
            "receipt_present": False,
            "later_evidence_present": False,
        },
        "no_later_evidence": True,
    }
    payload = (canonical_json(manifest) + "\n").encode()
    return authority._PredecessorState(
        manifest=manifest,
        payload=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        active_authority={"authority_fingerprint": "2" * 64},
        source_commit="3" * 40,
        frontier_request_index=0,
        latest_response_at=None,
        program_012_state=program_012_state,
    )


def _make_private_roots(repository: Path) -> None:
    for root in (
        authority.PRIVATE_ROOT,
        authority.PROGRAM_013_PRIVATE_ROOT,
        authority.PROGRAM_012_PRIVATE_ROOT,
    ):
        path = repository / root
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        path.chmod(0o700)
    for root in (authority.PROGRAM_013_PRIVATE_ROOT, authority.PROGRAM_012_PRIVATE_ROOT):
        predecessor_lock = repository / root / "run.lock"
        predecessor_lock.touch(mode=0o600, exist_ok=True)
        predecessor_lock.chmod(0o600)


def _open_program_014_root(repository: Path) -> int:
    (repository / authority.PUBLIC_TERMINAL_PATH.parent).mkdir(parents=True, exist_ok=True)
    _make_private_roots(repository)
    descriptor = authority._open_root(repository, authority.PRIVATE_ROOT, create=True)
    with git_controls._LockedRoot(descriptor):
        pass
    return descriptor


def _write_base_state(
    descriptor: int,
    active: dict[str, Any],
    state: authority._PredecessorState,
) -> None:
    predecessor._append_or_validate(descriptor, "predecessor-import-manifest.json", state.payload)
    predecessor._append_or_validate(
        descriptor,
        authority._LAUNCHER_KEY,
        authority._launcher_payload(active, state),
    )
    predecessor._append_or_validate(
        descriptor, "active-authority.json", (canonical_json(active) + "\n").encode()
    )


def _write_claim(
    descriptor: int,
    active: dict[str, Any],
    state: authority._PredecessorState,
) -> None:
    predecessor._append_or_validate(
        descriptor, "claim.json", authority._claim_payload(active, state)
    )


def _write_credential_audit(
    descriptor: int,
    active: dict[str, Any],
    state: authority._PredecessorState,
    sequence: int,
    *,
    status: str | None = "SUCCESS",
) -> None:
    attempt = authority._credential_attempt(active, state.sha256, sequence)
    prefix = f"credential-load-{sequence:06d}"
    predecessor._append(
        descriptor,
        f"{prefix}.attempt.json",
        (canonical_json(attempt) + "\n").encode(),
    )
    if status is not None:
        predecessor._append(
            descriptor,
            f"{prefix}.receipt.json",
            authority._credential_receipt_payload(str(attempt["attempt_identity"]), status),
        )


def _write_page(
    descriptor: int,
    active: dict[str, Any],
    state: authority._PredecessorState,
    request: program_011.SessionRequest,
    page_index: int,
    incoming_token: str | None,
    body: bytes,
) -> None:
    intent = program_011.PageIntent(
        request.identity,
        page_index,
        request.url(incoming_token),
        incoming_token,
    )
    prefix = predecessor._page_prefix(request, page_index)
    predecessor._append(
        descriptor,
        f"{prefix}.intent.json",
        authority._intent_payload(active, state, request, intent),
    )
    predecessor._append(descriptor, f"{prefix}.body", body)
    receipt = authority._response_receipt(
        active,
        state,
        request,
        intent,
        raw_contract.RawResponse(200, body),
        predecessor._utc_now(),
    )
    predecessor._append(
        descriptor,
        f"{prefix}.receipt.json",
        (canonical_json(receipt) + "\n").encode(),
    )


def _public_terminal() -> dict[str, Any]:
    return authority._public_terminal_value(
        {
            "result_kind": "RUNTIME-FAILURE",
            "status": "FAIL-CONSUMED-NO-RETRY",
            "authority_id": authority.CHILD_AUTHORITY_ID,
            "authority_fingerprint": "a" * 64,
            "source_commit": "b" * 40,
            "admission_passed": False,
            "public_dataset_lineage_manifest": None,
            "observed_at": "2026-09-03T12:00:00.000000Z",
        }
    )


def _child_identity(*, extra_capability: str | None = None) -> dict[str, Any]:
    required_paths = {
        git_controls.PROTECTED_CHRONOLOGY_PATH.as_posix(),
        *(path.as_posix() for path in git_controls.PROTECTED_CHRONOLOGY_SOURCE_PATHS),
        *(path.as_posix() for path in git_controls.PROTECTED_CHRONOLOGY_REGISTRATION_PATHS),
        str(authority.OPERATION_MANIFEST["path"]),
        str(authority.PROPOSAL_REVIEW["path"]),
        predecessor.PUBLIC_TERMINAL_PATH.as_posix(),
        program_013.PUBLIC_TERMINAL_PATH.as_posix(),
        "src/systematic_trading_lab/program_012_ohlcv_authority.py",
        "src/systematic_trading_lab/program_013_ohlcv_authority.py",
        "src/systematic_trading_lab/program_014_ohlcv_authority.py",
    }
    enabled = {name: True for name in authority._ENABLED_AUTHORITY}
    if extra_capability is not None:
        enabled[extra_capability] = True
    return {
        "child_authority_id": authority.CHILD_AUTHORITY_ID,
        "program_ordinal": authority.PROGRAM_ORDINAL,
        "program_id": authority.PROGRAM_ID,
        "operation_manifest": authority.OPERATION_MANIFEST,
        "runtime_entrypoint": "src/systematic_trading_lab/program_014_ohlcv_authority.py",
        "child_identity_fingerprint": "1" * 64,
        "authority": enabled,
        "runtime_binding": {
            "source_commit": "2" * 40,
            "source_tree": "3" * 40,
            "implementation_root": "4" * 64,
            "source_files": [{"path": path} for path in sorted(required_paths)],
        },
    }


def _configure_control_derivation(
    monkeypatch: MonkeyPatch,
    identity: dict[str, Any],
) -> None:
    monkeypatch.setattr(standing, "derive_child_identity", lambda *_args: identity)
    monkeypatch.setattr(
        authority,
        "_repository_preflight",
        lambda *_args: {
            "runtime_source_commit": "2" * 40,
            "runtime_source_tree": "3" * 40,
            "runtime_implementation_root": "4" * 64,
            "synchronized_main_commit": "5" * 40,
        },
    )
    monkeypatch.setattr(git_controls, "_validate_protected_registration_set", lambda *_args: None)
    monkeypatch.setattr(authority, "validate_operation_contract", lambda *_args, **_kwargs: {})


def _configure_finite_execution(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    *,
    admission_passed: bool = True,
    completed_responses: int = 0,
    activated: bool = False,
) -> tuple[dict[str, Any], program_011.SessionRequest, authority._PredecessorState]:
    active = _active_authority()
    request = _request()
    state = _predecessor_state(request, completed_responses=completed_responses)
    admission: dict[str, Any] = {
        "schema_version": "program-012-private-structural-admission-report-v1",
        "program_id": science.PROGRAM_ID,
        "status": (
            "ADMITTED-PROGRAM-012-RAW-STRUCTURAL-PREFIX"
            if admission_passed
            else "TERMINAL-FAIL-CONSUMED-NO-RETRY"
        ),
        "admission_passed": admission_passed,
        "failures": [] if admission_passed else ["global-count"],
        "fixed_quarantine_sessions": [],
        "unexpected_excluded_sessions": [],
        "missing_coordinate_count": len(request.expected_coordinates) - 1,
        "excluded_full_session_count": 0,
        "program_002_admission": False,
        "program_002_quote_windows_evaluated": 0,
        "strategy_metrics_present": False,
    }
    admission["admission_fingerprint"] = fingerprint(admission)
    proposal_012: dict[str, Any] = {
        "bindings": {
            "program_005_policy_precedent": {},
            "program_002_fixed_quarantine_incident": {},
        }
    }
    proposal_014 = {
        "predecessor": {
            "program_013_terminal_result": {
                "path": program_013.PUBLIC_TERMINAL_PATH.as_posix(),
                "sha256": "7" * 64,
            }
        }
    }
    proposal_013 = {
        "predecessor": {
            "program_012_scientific_contract": {},
            "program_012_terminal_result": {
                "path": predecessor.PUBLIC_TERMINAL_PATH.as_posix(),
                "sha256": "6" * 64,
            },
        }
    }
    monkeypatch.setattr(authority, "_derive_control_validated_authority", lambda _repo: active)
    monkeypatch.setattr(authority, "_derive_predecessor_state", lambda *_args: state)
    monkeypatch.setattr(
        authority,
        "validate_operation_contract",
        lambda *_args, **_kwargs: proposal_014,
    )
    monkeypatch.setattr(
        program_013,
        "validate_operation_contract",
        lambda *_args, **_kwargs: proposal_013,
    )
    monkeypatch.setattr(authority, "_load_bound", lambda *_args, **_kwargs: proposal_012)
    monkeypatch.setattr(authority, "_require_zero_protected_overlap", lambda *_args: None)
    monkeypatch.setattr(authority, "_require_working_disk_capacity", lambda _fd: None)
    monkeypatch.setattr(git_controls, "_GitPolicySnapshot", lambda *_args: nullcontext())
    monkeypatch.setattr(science, "acquisition_requests", lambda: (request,))
    monkeypatch.setattr(science, "full_trade_sessions", lambda: frozenset({request.session}))
    monkeypatch.setattr(science, "EXPECTED_COORDINATE_COUNT", len(request.expected_coordinates))
    monkeypatch.setattr(science, "assess_structural_admission", lambda *_args, **_kwargs: admission)
    (tmp_path / authority.PUBLIC_TERMINAL_PATH.parent).mkdir(parents=True, exist_ok=True)
    _make_private_roots(tmp_path)
    if activated:
        descriptor = authority._open_root(tmp_path, authority.PRIVATE_ROOT, create=False)
        try:
            with git_controls._LockedRoot(descriptor):
                authority._activate_locked_authority(descriptor, active, state, _credentials())
        finally:
            os.close(descriptor)
    return active, request, state


def _write_program_013_page(
    descriptor: int,
    active: dict[str, Any],
    state: program_013._PredecessorState,
    request: program_011.SessionRequest,
    *,
    complete: bool,
    include_frontier_body: bool = False,
    next_token: str | None = None,
) -> None:
    intent = program_011.PageIntent(request.identity, 1, request.url(), None)
    prefix = predecessor._page_prefix(request, 1)
    predecessor._append(
        descriptor,
        f"{prefix}.intent.json",
        program_013._intent_payload(active, state, request, intent),
    )
    if not complete and not include_frontier_body:
        return
    body = _body(request, 0, next_token)
    predecessor._append(descriptor, f"{prefix}.body", body)
    if not complete:
        return
    receipt = program_013._response_receipt(
        active,
        state,
        request,
        intent,
        raw_contract.RawResponse(200, body),
        predecessor._utc_now(),
    )
    predecessor._append(
        descriptor,
        f"{prefix}.receipt.json",
        (canonical_json(receipt) + "\n").encode(),
    )


def _derive_synthetic_predecessor(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    *,
    mutation: str | None = None,
) -> authority._PredecessorState:
    requests = tuple(science.acquisition_requests()[:3])
    source_commit = "9" * 40
    p12_state = _predecessor_state(requests[0]).program_012_state
    historical_identity = {
        "child_identity_fingerprint": "8" * 64,
        "authority": {name: True for name in authority._ENABLED_AUTHORITY},
    }
    control_lineage = {
        "runtime_source_commit": source_commit,
        "runtime_source_tree": "7" * 40,
        "runtime_implementation_root": "6" * 64,
        "synchronized_main_commit": "5" * 40,
    }
    unsigned_active = {
        "schema_version": "program-013-raw-sip-recovery-active-authority-v1",
        "status": "ACTIVE-ONE-USE-RECOVERABLE",
        "authority_id": program_013.CHILD_AUTHORITY_ID,
        "program_id": program_013.PROGRAM_ID,
        "activation_mode": "INTERNAL-STANDING-MANDATE-DERIVATION",
        "external_authorization_root_required": False,
        "child_identity_fingerprint": historical_identity["child_identity_fingerprint"],
        "operation_manifest": program_013.OPERATION_MANIFEST,
        "consumption_boundary": program_013.CONSUMPTION_BOUNDARY,
        "authority": historical_identity["authority"],
        "runtime_binding": {
            "source_commit": source_commit,
            "source_tree": control_lineage["runtime_source_tree"],
            "implementation_root": control_lineage["runtime_implementation_root"],
        },
        "control_lineage": control_lineage,
    }
    active_013 = {
        **unsigned_active,
        "authority_fingerprint": fingerprint(unsigned_active),
    }
    for root in (authority.PROGRAM_013_PRIVATE_ROOT, authority.PROGRAM_012_PRIVATE_ROOT):
        path = tmp_path / root
        path.mkdir(parents=True, mode=0o700)
        path.chmod(0o700)
    root = tmp_path / authority.PROGRAM_013_PRIVATE_ROOT
    descriptor = authority._open_root(tmp_path, authority.PROGRAM_013_PRIVATE_ROOT, create=False)
    predecessor._append(
        descriptor, "active-authority.json", (canonical_json(active_013) + "\n").encode()
    )
    predecessor._append(descriptor, "predecessor-import-manifest.json", p12_state.payload)
    if mutation == "partial-predecessor":
        _write_program_013_page(descriptor, active_013, p12_state, requests[0], complete=False)
    else:
        _write_program_013_page(descriptor, active_013, p12_state, requests[0], complete=True)
        if mutation == "page-2-frontier":
            next_page = "next"
            _write_program_013_page(
                descriptor,
                active_013,
                p12_state,
                requests[1],
                complete=True,
                next_token=next_page,
            )
            intent = program_011.PageIntent(
                requests[1].identity,
                2,
                requests[1].url("next"),
                "next",
            )
            prefix = predecessor._page_prefix(requests[1], 2)
            predecessor._append(
                descriptor,
                f"{prefix}.intent.json",
                program_013._intent_payload(active_013, p12_state, requests[1], intent),
            )
        else:
            _write_program_013_page(
                descriptor,
                active_013,
                p12_state,
                requests[1],
                complete=False,
                include_frontier_body=mutation == "frontier-body",
            )
    if mutation == "changed-checkpoint":
        prefix = predecessor._page_prefix(requests[0], 1)
        receipt_path = root / f"{prefix}.receipt.json"
        receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
    if mutation == "later-evidence":
        _write_program_013_page(descriptor, active_013, p12_state, requests[2], complete=False)
    monkeypatch.setattr(science, "acquisition_requests", lambda: requests)
    monkeypatch.setattr(
        authority,
        "validate_operation_contract",
        lambda *_args, **_kwargs: {
            "predecessor": {"program_013_terminal_result": {"path": "terminal", "sha256": "x"}}
        },
    )
    monkeypatch.setattr(
        authority,
        "_load_bound",
        lambda *_args, **_kwargs: {
            "authority_fingerprint": active_013["authority_fingerprint"],
            "source_commit": source_commit,
        },
    )
    monkeypatch.setattr(
        authority,
        "_historical_program_013_identity",
        lambda *_args: historical_identity,
    )
    monkeypatch.setattr(program_013, "validate_operation_contract", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(program_013, "_derive_predecessor_state", lambda *_args: p12_state)
    body = _body(requests[0], 0, None)
    private_terminal = {
        "result_kind": "RUNTIME-FAILURE",
        "status": "FAIL-CONSUMED-NO-RETRY",
        "admission_passed": False,
        "structural_admission_evaluated": False,
        "strategy_calculations": 0,
        "strategy_returns": 0,
        "cumulative_request_intents": 3,
        "cumulative_responses": 1,
        "cumulative_response_bytes": len(body),
        "terminal_fingerprint": "4" * 64,
    }
    monkeypatch.setattr(
        program_013,
        "_load_terminal_record",
        lambda *_args: private_terminal,
    )
    monkeypatch.setattr(program_013, "_public_terminal_payload", lambda *_args: b"public\n")
    monkeypatch.setattr(authority, "_git", lambda *_args: b"public\n")
    p12_descriptor = authority._open_root(
        tmp_path, authority.PROGRAM_012_PRIVATE_ROOT, create=False
    )
    try:
        return authority._derive_predecessor_state(
            tmp_path, descriptor, p12_descriptor, _active_authority()
        )
    finally:
        os.close(p12_descriptor)
        os.close(descriptor)


def test_operation_contract_revalidates_program_014_v5() -> None:
    proposal = authority.validate_operation_contract(_REPOSITORY)

    assert proposal["program_id"] == authority.PROGRAM_ID
    assert proposal["proposal_fingerprint"] == authority.OPERATION_MANIFEST["fingerprint"]


def test_exact_predecessor_prefix_and_frontier_are_rederived(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    state = _derive_synthetic_predecessor(tmp_path, monkeypatch)

    assert state.frontier_request_index == 1
    assert state.manifest["completed_request_count"] == 1
    assert state.manifest["completed_response_count"] == 1
    assert len(state.manifest["program_013_completed_sessions"]) == 1
    assert state.manifest["frontier"]["body_present"] is False
    assert state.manifest["frontier"]["receipt_present"] is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("partial-predecessor", "frontier is absent"),
        ("changed-checkpoint", "reviewed intent-only frontier"),
        ("frontier-body", "frontier checkpoint differs"),
        ("later-evidence", "continues after frontier"),
        ("page-2-frontier", "not first-page intent-only"),
    ),
)
def test_invalid_predecessor_shapes_fail_before_reuse(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    with pytest.raises(authority.Program014AuthorityError, match=message):
        _derive_synthetic_predecessor(tmp_path, monkeypatch, mutation=mutation)


def test_control_lock_order_uses_only_the_fixed_roots(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    events: list[str] = []
    opened: list[tuple[Path, bool]] = []
    held = {"program-014": False, "program-013": False, "program-012": False, "git": False}

    def open_root(_repository: Path, root: Path, *, create: bool) -> int:
        opened.append((root, create))
        path = tmp_path / f"fd-{len(opened)}"
        path.mkdir()
        return os.open(path, os.O_RDONLY)

    @contextmanager
    def locked(_descriptor: int) -> Iterator[None]:
        events.append("program-014-enter")
        held["program-014"] = True
        try:
            yield
        finally:
            held["program-014"] = False
            events.append("program-014-exit")

    @contextmanager
    def read_locked(_descriptor: int, program: str) -> Iterator[None]:
        key = program.lower().replace(" ", "-")
        events.append(f"{key}-enter")
        held[key] = True
        try:
            yield
        finally:
            held[key] = False
            events.append(f"{key}-exit")

    @contextmanager
    def git_locked(_repository: Path, _commit: str) -> Iterator[None]:
        events.append("git-enter")
        held["git"] = True
        try:
            yield
        finally:
            held["git"] = False
            events.append("git-exit")

    monkeypatch.setattr(authority, "_open_root", open_root)
    monkeypatch.setattr(git_controls, "_LockedRoot", locked)
    monkeypatch.setattr(authority, "_ReadLockedRoot", read_locked)
    monkeypatch.setattr(git_controls, "_GitPolicySnapshot", git_locked)
    private_terminal = {
        "result_kind": "RUNTIME-FAILURE",
        "status": "FAIL-CONSUMED-NO-RETRY",
        "authority_id": authority.CHILD_AUTHORITY_ID,
        "authority_fingerprint": "a" * 64,
        "source_commit": "b" * 40,
        "admission_passed": False,
        "public_dataset_lineage_manifest": None,
        "observed_at": "2026-09-03T12:00:00.000000Z",
    }
    monkeypatch.setattr(authority, "_revalidate_closeout_boundary", lambda *_args: None)
    monkeypatch.setattr(
        authority,
        "_load_terminal_record",
        lambda *_args: private_terminal,
    )

    def publish(_repository: Path, _descriptor: int, _payload: bytes) -> None:
        assert all(held.values())
        events.append("publish")

    monkeypatch.setattr(authority, "_append_public_atomic", publish)

    with authority._locked_controls(tmp_path, _active_authority(), create_program_014=True) as (
        program_014_root,
        program_013_root,
        program_012_root,
    ):
        authority._publish_public_terminal(
            tmp_path,
            program_014_root,
            program_013_root,
            program_012_root,
            _active_authority(),
            _predecessor_state(),
            private_terminal,
        )
        events.append("body")

    assert opened == [
        (authority.PRIVATE_ROOT, True),
        (authority.PROGRAM_013_PRIVATE_ROOT, False),
        (authority.PROGRAM_012_PRIVATE_ROOT, False),
    ]
    assert events == [
        "program-014-enter",
        "program-013-enter",
        "program-012-enter",
        "git-enter",
        "publish",
        "body",
        "git-exit",
        "program-012-exit",
        "program-013-exit",
        "program-014-exit",
    ]
    assert "private_root" not in inspect.signature(authority.execute_acquisition).parameters
    assert "lock_path" not in inspect.signature(authority.execute_acquisition).parameters


def test_overbroad_child_fails_before_credentials_or_private_roots(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    identity = _child_identity(extra_capability="source_qualification")
    _configure_control_derivation(monkeypatch, identity)
    opened: list[bool] = []
    checked_credentials: list[bool] = []
    monkeypatch.setattr(authority, "_open_root", lambda *_args, **_kwargs: opened.append(True))
    monkeypatch.setattr(
        credential_contract,
        "credential_presence_preflight",
        lambda *_args: checked_credentials.append(True),
    )

    with pytest.raises(authority.Program014AuthorityError, match="reviewed child identity"):
        authority.credential_presence_preflight(tmp_path, environ={})

    assert opened == []
    assert checked_credentials == []


def test_protected_overlap_fails_before_every_private_root_entrypoint(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _configure_control_derivation(monkeypatch, _child_identity())
    opened: list[bool] = []
    credentials: list[bool] = []
    monkeypatch.setattr(
        authority,
        "_require_zero_protected_overlap",
        lambda *_args: (_ for _ in ()).throw(
            authority.Program014AuthorityError(
                "Program 014 request chronology overlaps protected data"
            )
        ),
    )
    monkeypatch.setattr(authority, "_open_root", lambda *_args, **_kwargs: opened.append(True))
    monkeypatch.setattr(
        credential_contract,
        "credential_presence_preflight",
        lambda *_args: credentials.append(True),
    )

    for operation in (
        lambda: authority.credential_presence_preflight(tmp_path, environ={}),
        lambda: authority.derive_active_authority(tmp_path),
        lambda: authority.execute_acquisition(tmp_path, environ={}),
    ):
        with pytest.raises(authority.Program014AuthorityError, match="overlaps protected"):
            operation()

    assert opened == []
    assert credentials == []


def test_runtime_source_precedes_exact_child_and_review_topology(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Program 014 Test")
    _git(tmp_path, "config", "user.email", "program-014@example.invalid")
    (tmp_path / ".gitignore").write_text(".trading-lab/\n", encoding="utf-8")
    (tmp_path / "runtime.py").write_text("RUNTIME = True\n", encoding="utf-8")
    _git(tmp_path, "add", ".gitignore", "runtime.py")
    _git(tmp_path, "commit", "-m", "runtime")
    source_commit = _git(tmp_path, "rev-parse", "HEAD")
    source_tree = _git(tmp_path, "rev-parse", "HEAD^{tree}")
    for path in (authority.CHILD_AUTHORITY_PATH, authority.CHILD_REVIEW_PATH):
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("{}\n", encoding="utf-8")
        _git(tmp_path, "add", path.as_posix())
    _git(tmp_path, "commit", "-m", "child and review")
    head = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", head)
    identity = {
        "runtime_binding": {
            "source_commit": source_commit,
            "source_tree": source_tree,
            "implementation_root": "a" * 64,
        }
    }

    lineage = authority._repository_preflight(tmp_path, identity)

    assert source_commit != head
    assert lineage["runtime_source_commit"] == source_commit
    assert lineage["synchronized_main_commit"] == head
    stale = {
        "runtime_binding": {
            "source_commit": head,
            "source_tree": _git(tmp_path, "rev-parse", "HEAD^{tree}"),
            "implementation_root": "a" * 64,
        }
    }
    with pytest.raises(authority.Program014AuthorityError, match="synchronized-main lineage"):
        authority._repository_preflight(tmp_path, stale)
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", source_commit)
    with pytest.raises(authority.Program014AuthorityError, match="synchronized-main lineage"):
        authority._repository_preflight(tmp_path, identity)


def test_transport_and_closeout_revalidate_authority_predecessor_and_firewall(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    active = _active_authority()
    state = _predecessor_state()
    monkeypatch.setattr(authority, "_require_working_disk_capacity", lambda _fd: None)
    monkeypatch.setattr(authority, "_require_zero_protected_overlap", lambda *_args: None)
    monkeypatch.setattr(authority, "_derive_control_validated_authority", lambda _repo: active)
    monkeypatch.setattr(authority, "_derive_predecessor_state", lambda *_args: state)

    authority._revalidate_transport_boundary(tmp_path, 1, 2, 3, active, state)
    authority._revalidate_closeout_boundary(tmp_path, 2, 3, active, state)

    changed = dict(active)
    changed["authority_fingerprint"] = "0" * 64
    monkeypatch.setattr(authority, "_derive_control_validated_authority", lambda _repo: changed)
    with pytest.raises(authority.Program014AuthorityError, match="authority changed"):
        authority._revalidate_transport_boundary(tmp_path, 1, 2, 3, active, state)
    with pytest.raises(authority.Program014AuthorityError, match="authority changed"):
        authority._revalidate_closeout_boundary(tmp_path, 2, 3, active, state)

    monkeypatch.setattr(authority, "_derive_control_validated_authority", lambda _repo: active)
    changed_state = _predecessor_state(_request(1))
    monkeypatch.setattr(authority, "_derive_predecessor_state", lambda *_args: changed_state)
    with pytest.raises(authority.Program014AuthorityError, match="evidence changed"):
        authority._revalidate_transport_boundary(tmp_path, 1, 2, 3, active, state)
    with pytest.raises(authority.Program014AuthorityError, match="evidence changed"):
        authority._revalidate_closeout_boundary(tmp_path, 2, 3, active, state)


def test_closeout_rejection_precedes_private_success_terminal(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _, request, _ = _configure_finite_execution(tmp_path, monkeypatch)
    monkeypatch.setattr(
        authority,
        "_revalidate_closeout_boundary",
        lambda *_args: (_ for _ in ()).throw(
            authority.Program014AuthorityError("Program 014 closeout rejected")
        ),
    )

    with pytest.raises(authority.Program014PostClaimPersistenceError):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport(
                [raw_contract.RawResponse(200, _body(request, 0, None))]
            ),
        )

    assert not (tmp_path / authority.PRIVATE_ROOT / authority._TERMINAL_KEY).exists()


def test_crash_after_durable_activation_seals_before_unlock(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _, request, _ = _configure_finite_execution(
        tmp_path,
        monkeypatch,
        activated=False,
    )
    transport = authority.MockBarsTransport(
        [raw_contract.RawResponse(200, _body(request, 0, None))]
    )

    with pytest.raises(KeyboardInterrupt):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=transport,
            after_activation=lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
        )

    private = json.loads((tmp_path / authority.PRIVATE_ROOT / authority._TERMINAL_KEY).read_bytes())
    assert private["result_kind"] == "RUNTIME-FAILURE"
    assert private["provider_transport_attempted"] is False
    assert private["program_014_credential_loads"] == 0
    assert private["cumulative_request_intents"] == 2
    assert private["cumulative_responses"] == 0
    assert transport.intents == ()


def test_crash_after_intent_seals_without_credentials_or_transport(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _, _, _ = _configure_finite_execution(tmp_path, monkeypatch)
    transport = authority.MockBarsTransport(
        [raw_contract.RawResponse(200, _body(_request(), 0, None))]
    )

    with pytest.raises(KeyboardInterrupt):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=transport,
            after_intent=lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
        )

    public = json.loads((tmp_path / authority.PUBLIC_TERMINAL_PATH).read_bytes())
    private = json.loads((tmp_path / authority.PRIVATE_ROOT / authority._TERMINAL_KEY).read_bytes())
    assert public["result_kind"] == "RUNTIME-FAILURE"
    assert private["provider_transport_attempted"] is False
    assert private["program_014_credential_loads"] == 0
    assert private["cumulative_request_intents"] == 3
    assert private["cumulative_responses"] == 0
    assert transport.intents == ()
    monkeypatch.setattr(
        authority,
        "read_credentials",
        lambda *_args: pytest.fail("terminal recovery accessed credentials"),
    )
    with pytest.raises(authority.Program014AuthorityError, match="terminally sealed"):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport([]),
        )


def test_crash_after_body_seals_without_a_second_transport(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _, request, _ = _configure_finite_execution(tmp_path, monkeypatch)
    transport = authority.MockBarsTransport(
        [raw_contract.RawResponse(200, _body(request, 0, None))]
    )

    with pytest.raises(KeyboardInterrupt):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=transport,
            after_body=lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
        )

    private = json.loads((tmp_path / authority.PRIVATE_ROOT / authority._TERMINAL_KEY).read_bytes())
    assert private["provider_transport_attempted"] is True
    assert private["program_014_credential_loads"] == 1
    assert private["cumulative_request_intents"] == 3
    assert private["cumulative_responses"] == 0
    assert len(transport.intents) == 1
    monkeypatch.setattr(
        authority,
        "read_credentials",
        lambda *_args: pytest.fail("terminal recovery accessed credentials"),
    )
    with pytest.raises(authority.Program014AuthorityError, match="terminally sealed"):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport([]),
        )


def test_completed_page_replays_locally_and_resumes_only_the_continuation(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    active = _active_authority()
    request = _request()
    state = _predecessor_state(request)
    descriptor = _open_program_014_root(tmp_path)
    _write_base_state(descriptor, active, state)
    first_transport = authority.MockBarsTransport(
        [raw_contract.RawResponse(200, _body(request, 0, "opaque-page-2"))]
    )
    first_budget = authority._Budget(state)
    first_loader = authority._CredentialLoader(
        descriptor,
        active,
        state,
        _credentials(),
        first_transport,
        None,
        None,
    )

    def consume() -> None:
        _write_claim(descriptor, active, state)

    first_source = authority._PersistentSessionSource(
        descriptor,
        request,
        active,
        state,
        first_budget,
        first_loader,
        consume,
        None,
        None,
        lambda: (_ for _ in ()).throw(_AbruptExit()),
    )
    with pytest.raises(_AbruptExit):
        authority._execute_session(request, first_source)
    assert len(first_transport.intents) == 1
    monkeypatch.setattr(authority, "_PROCESS_CREDENTIAL_PID", None)

    recovered_budget = authority._reconstruct_state(descriptor, state, authority=active)
    second_transport = authority.MockBarsTransport(
        [raw_contract.RawResponse(200, _body(request, 1, None))]
    )
    second_loader = authority._CredentialLoader(
        descriptor,
        active,
        state,
        _credentials(),
        second_transport,
        None,
        recovered_budget.latest_response_at,
    )
    second_source = authority._PersistentSessionSource(
        descriptor,
        request,
        active,
        state,
        recovered_budget,
        second_loader,
        consume,
        None,
        None,
        None,
    )

    result = authority._execute_session(request, second_source)

    assert len(result.pages) == 2
    assert len(second_transport.intents) == 1
    assert second_transport.intents[0].page_index == 2
    assert second_transport.intents[0].incoming_page_token == "opaque-page-2"
    assert authority._credential_load_counts(descriptor, active, state) == (2, 2)
    os.close(descriptor)


def _concurrent_recovery_worker(
    repository: str,
    active: dict[str, Any],
    state: authority._PredecessorState,
    start: Any,
    outputs: Any,
) -> None:
    request = science.acquisition_requests()[0]
    science.acquisition_requests.cache_clear()

    def acquisition_requests() -> tuple[program_011.SessionRequest, ...]:
        return (request,)

    def git_policy_snapshot(*_args: Any) -> Any:
        return nullcontext()

    science_module: Any = science
    git_controls_module: Any = git_controls
    science_module.acquisition_requests = acquisition_requests
    git_controls_module._GitPolicySnapshot = git_policy_snapshot
    transport = authority.MockBarsTransport(
        [raw_contract.RawResponse(200, _body(request, 0, None))]
    )
    try:
        start.wait()
        with authority._locked_controls(Path(repository), active, create_program_014=False) as (
            descriptor,
            _program_013_descriptor,
            _program_012_descriptor,
        ):
            budget = authority._reconstruct_state(descriptor, state, authority=active)
            loader = authority._CredentialLoader(
                descriptor,
                active,
                state,
                _credentials(),
                transport,
                None,
                budget.latest_response_at,
            )

            def consume() -> None:
                if predecessor._exists(descriptor, "claim.json"):
                    authority._validate_claim(descriptor, active, state)
                else:
                    _write_claim(descriptor, active, state)

            source = authority._PersistentSessionSource(
                descriptor,
                request,
                active,
                state,
                budget,
                loader,
                consume,
                None,
                None,
                None,
            )
            result = authority._execute_session(request, source)
            outputs.put((None, len(result.pages), len(transport.intents)))
    except BaseException as error:
        outputs.put((type(error).__name__, 0, len(transport.intents)))


def test_two_processes_serialize_one_credential_and_frontier_transport(
    tmp_path: Path,
) -> None:
    active = _active_authority()
    request = _request()
    state = _predecessor_state(request)
    descriptor = _open_program_014_root(tmp_path)
    _write_base_state(descriptor, active, state)
    os.close(descriptor)
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    outputs = context.Queue()
    processes = [
        context.Process(
            target=_concurrent_recovery_worker,
            args=(str(tmp_path), active, state, start, outputs),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=15)

    results = [outputs.get(timeout=2) for _ in processes]
    assert not any(process.is_alive() for process in processes)
    assert [process.exitcode for process in processes] == [0, 0]
    # Program 014 is explicitly single-process: a launcher checkpoint created
    # by one process must reject every separately launched process before
    # credential access or provider transport.
    assert all(
        error in {"Program014AuthorityError", "_IncompletePageCheckpoint"} and pages == 0
        for error, pages, _ in results
    ), results
    assert sum(transports for _, _, transports in results) == 0
    descriptor = authority._open_root(tmp_path, authority.PRIVATE_ROOT, create=False)
    try:
        assert authority._credential_load_counts(descriptor, active, state) == (0, 0)
    finally:
        os.close(descriptor)
        outputs.close()
        outputs.join_thread()


@pytest.mark.parametrize("mutation", ("pid", "nonce", "automatic_restart"))
def test_launcher_rejects_relaunch_or_restart_policy_change(tmp_path: Path, mutation: str) -> None:
    active = _active_authority()
    state = _predecessor_state()
    descriptor = _open_program_014_root(tmp_path)
    _write_base_state(descriptor, active, state)
    launcher_path = tmp_path / authority.PRIVATE_ROOT / authority._LAUNCHER_KEY
    launcher = json.loads(launcher_path.read_bytes())
    if mutation == "pid":
        launcher["process_pid"] += 1
    elif mutation == "nonce":
        launcher["process_nonce"] = "0" * 64
    else:
        launcher["automatic_restart"] = True
    unsigned = dict(launcher)
    unsigned.pop("launcher_fingerprint")
    launcher["launcher_fingerprint"] = fingerprint(unsigned)
    launcher_path.write_bytes((canonical_json(launcher) + "\n").encode())

    with pytest.raises(authority.Program014AuthorityError, match="launcher changed"):
        authority._validate_launcher(descriptor, active, state)
    os.close(descriptor)


def test_restarted_process_cannot_publish_success_from_completed_pages(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    active, request, state = _configure_finite_execution(tmp_path, monkeypatch, activated=True)
    descriptor = authority._open_root(tmp_path, authority.PRIVATE_ROOT, create=False)
    _write_claim(descriptor, active, state)
    _write_credential_audit(descriptor, active, state, 1)
    _write_page(descriptor, active, state, request, 1, None, _body(request, 0, None))
    os.close(descriptor)
    monkeypatch.setattr(authority, "_PROCESS_LAUNCH_NONCE", "0" * 64)
    monkeypatch.setattr(
        authority,
        "read_credentials",
        lambda *_args: pytest.fail("restarted process accessed credentials"),
    )
    transport = authority.MockBarsTransport([])

    with pytest.raises(authority.Program014AuthorityError, match="terminally sealed"):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=transport,
        )

    private = json.loads((tmp_path / authority.PRIVATE_ROOT / authority._TERMINAL_KEY).read_bytes())
    assert private["result_kind"] == "RUNTIME-FAILURE"
    assert private["provider_transport_attempted"] is True
    assert private["program_014_credential_loads"] == 1
    assert private["cumulative_request_intents"] == 3
    assert private["cumulative_responses"] == 1
    assert transport.intents == ()


@pytest.mark.parametrize("field", ("strategy_calculations", "strategy_returns"))
def test_private_terminal_rejects_boolean_strategy_zero(
    tmp_path: Path, monkeypatch: MonkeyPatch, field: str
) -> None:
    _, request, state = _configure_finite_execution(tmp_path, monkeypatch)
    authority._execute_mock_acquisition(
        tmp_path,
        environ=_credentials(),
        transport=authority.MockBarsTransport(
            [raw_contract.RawResponse(200, _body(request, 0, None))]
        ),
    )
    terminal_path = tmp_path / authority.PRIVATE_ROOT / authority._TERMINAL_KEY
    terminal = json.loads(terminal_path.read_bytes())
    terminal[field] = False
    unsigned = dict(terminal)
    unsigned.pop("terminal_fingerprint")
    terminal["terminal_fingerprint"] = fingerprint(unsigned)
    terminal_path.write_bytes((canonical_json(terminal) + "\n").encode())
    descriptor = authority._open_root(tmp_path, authority.PRIVATE_ROOT, create=False)
    program_013_descriptor = authority._open_root(
        tmp_path, authority.PROGRAM_013_PRIVATE_ROOT, create=False
    )
    program_012_descriptor = authority._open_root(
        tmp_path, authority.PROGRAM_012_PRIVATE_ROOT, create=False
    )
    try:
        with pytest.raises(authority.Program014AuthorityError, match="private terminal binding"):
            authority._load_terminal_record(
                tmp_path,
                descriptor,
                program_013_descriptor,
                program_012_descriptor,
                _active_authority(),
                state,
            )
    finally:
        os.close(descriptor)
        os.close(program_013_descriptor)
        os.close(program_012_descriptor)


@pytest.mark.parametrize(
    "mutation",
    ("gap", "receipt-without-attempt", "changed-binding", "changed-status"),
)
def test_credential_sequences_reject_invalid_evidence(tmp_path: Path, mutation: str) -> None:
    active = _active_authority()
    state = _predecessor_state()
    descriptor = _open_program_014_root(tmp_path)
    if mutation == "gap":
        _write_credential_audit(descriptor, active, state, 2)
    elif mutation == "receipt-without-attempt":
        predecessor._append(
            descriptor,
            "credential-load-000001.receipt.json",
            authority._credential_receipt_payload("1" * 64, "SUCCESS"),
        )
    elif mutation == "changed-binding":
        changed = dict(active)
        changed["authority_fingerprint"] = "0" * 64
        _write_credential_audit(descriptor, changed, state, 1)
    else:
        attempt = authority._credential_attempt(active, state.sha256, 1)
        predecessor._append(
            descriptor,
            "credential-load-000001.attempt.json",
            (canonical_json(attempt) + "\n").encode(),
        )
        receipt = {
            "schema_version": "program-014-private-credential-load-receipt-v1",
            "attempt_identity": attempt["attempt_identity"],
            "status": "UNKNOWN",
        }
        predecessor._append(
            descriptor,
            "credential-load-000001.receipt.json",
            (canonical_json(receipt) + "\n").encode(),
        )

    with pytest.raises(authority.Program014AuthorityError, match="credential"):
        authority._credential_load_counts(descriptor, active, state)
    os.close(descriptor)


def test_duplicate_credential_checkpoint_is_create_only(tmp_path: Path) -> None:
    active = _active_authority()
    state = _predecessor_state()
    descriptor = _open_program_014_root(tmp_path)
    _write_credential_audit(descriptor, active, state, 1, status=None)

    with pytest.raises(predecessor.Program012AuthorityError, match="already exists"):
        _write_credential_audit(descriptor, active, state, 1, status=None)
    os.close(descriptor)


def test_unpaired_attempt_counts_one_load_and_latch_blocks_second_access(
    tmp_path: Path,
) -> None:
    active = _active_authority()
    request = _request()
    state = _predecessor_state(request)
    descriptor = _open_program_014_root(tmp_path)
    _write_base_state(descriptor, active, state)
    first = authority._CredentialLoader(
        descriptor,
        active,
        state,
        _credentials(),
        authority.MockBarsTransport([]),
        lambda: (_ for _ in ()).throw(_AbruptExit()),
        None,
    )
    intent = program_011.PageIntent(request.identity, 1, request.url(), None)
    with pytest.raises(_AbruptExit):
        first.get(intent, lambda: None)
    assert authority._credential_load_counts(descriptor, active, state) == (1, 0)

    second = authority._CredentialLoader(
        descriptor,
        active,
        state,
        _credentials(),
        authority.MockBarsTransport([]),
        None,
        None,
    )
    with pytest.raises(authority.Program014AuthorityError, match="already consumed"):
        second.get(intent, lambda: None)
    assert authority._credential_load_counts(descriptor, active, state) == (1, 0)
    os.close(descriptor)


def test_success_receipt_precedes_transport_and_latch_blocks_second_access(
    tmp_path: Path,
) -> None:
    active = _active_authority()
    request = _request()
    state = _predecessor_state(request)
    descriptor = _open_program_014_root(tmp_path)
    _write_base_state(descriptor, active, state)
    intent = program_011.PageIntent(request.identity, 1, request.url(), None)
    observed: list[bool] = []
    transport = authority.MockBarsTransport([raw_contract.RawResponse(200, b"{}")])
    first = authority._CredentialLoader(
        descriptor,
        active,
        state,
        _credentials(),
        transport,
        None,
        None,
    )

    def before_transport() -> None:
        assert predecessor._exists(descriptor, "credential-load-000001.receipt.json")
        observed.append(True)

    first.get(intent, before_transport)
    second = authority._CredentialLoader(
        descriptor,
        active,
        state,
        _credentials(),
        authority.MockBarsTransport([]),
        None,
        None,
    )
    with pytest.raises(authority.Program014AuthorityError, match="already consumed"):
        second.get(intent, lambda: None)
    assert observed == [True]
    assert authority._credential_load_counts(descriptor, active, state) == (1, 1)
    os.close(descriptor)


def test_combined_budget_counts_predecessor_frontier_and_program_014_pages() -> None:
    state = _predecessor_state(completed_responses=22_174)
    budget = authority._Budget(state)

    assert (budget.requests, budget.responses) == (22_176, 22_174)
    with pytest.raises(authority.CombinedRequestBudgetExhausted):
        budget.reserve_request()
    intent = program_011.PageIntent(_request().identity, 1, _request().url(), None)
    with pytest.raises(authority.CombinedRequestBudgetExhausted):
        budget.accept_response(_request(), intent, 200, b"{}", datetime(2026, 9, 4, tzinfo=UTC))


def test_exhausted_inherited_envelope_seals_without_credentials_or_transport(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _, request, _ = _configure_finite_execution(
        tmp_path,
        monkeypatch,
        completed_responses=science.MAXIMUM_REQUESTS_AND_RESPONSES - 2,
    )
    credential_reads: list[bool] = []
    monkeypatch.setattr(
        authority,
        "read_credentials",
        lambda *_args: credential_reads.append(True),
    )
    transport = authority.MockBarsTransport(
        [raw_contract.RawResponse(200, _body(request, 0, None))]
    )

    with pytest.raises(authority.Program014AuthorityError, match="sealed failure"):
        authority._execute_mock_acquisition(tmp_path, environ=_credentials(), transport=transport)

    private = json.loads((tmp_path / authority.PRIVATE_ROOT / authority._TERMINAL_KEY).read_bytes())
    assert private["failure_class"] == "CombinedRequestBudgetExhausted"
    assert private["failure_classification"] == (
        "FAIL-CONSUMED-NO-RETRY-COMBINED-REQUEST-BUDGET-EXHAUSTED"
    )
    assert private["cumulative_request_intents"] == 22_176
    assert private["cumulative_responses"] == 22_174
    assert private["provider_transport_attempted"] is False
    assert credential_reads == []
    assert transport.intents == ()


def test_atomic_predecessor_manifest_recovers_after_interruption_before_link(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    descriptor = _open_program_014_root(tmp_path)
    state = _predecessor_state()
    original_link = os.link
    monkeypatch.setattr(
        os,
        "link",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(_AbruptExit()),
    )

    with pytest.raises(_AbruptExit):
        authority._append_atomic_or_validate(
            descriptor, "predecessor-import-manifest.json", state.payload
        )

    assert not predecessor._exists(descriptor, "predecessor-import-manifest.json")
    monkeypatch.setattr(os, "link", original_link)
    authority._append_atomic_or_validate(
        descriptor, "predecessor-import-manifest.json", state.payload
    )
    assert predecessor._read(descriptor, "predecessor-import-manifest.json") == state.payload
    os.close(descriptor)


@pytest.mark.parametrize("operation", ("preflight", "run"))
def test_lifecycle_entrypoints_seal_ambiguous_consumed_state_before_credentials(
    tmp_path: Path, monkeypatch: MonkeyPatch, operation: str
) -> None:
    active, request, state = _configure_finite_execution(tmp_path, monkeypatch, activated=True)
    descriptor = authority._open_root(tmp_path, authority.PRIVATE_ROOT, create=False)
    intent = program_011.PageIntent(request.identity, 1, request.url(), None)
    prefix = predecessor._page_prefix(request, 1)
    predecessor._append_atomic(
        descriptor,
        f"{prefix}.intent.json",
        authority._intent_payload(active, state, request, intent),
    )
    os.close(descriptor)
    monkeypatch.setattr(
        credential_contract,
        "credential_presence_preflight",
        lambda *_args: pytest.fail("consumed-state recovery accessed credentials"),
    )

    with pytest.raises(authority.Program014AuthorityError, match="terminally sealed"):
        if operation == "preflight":
            authority.credential_presence_preflight(tmp_path, environ={})
        else:
            authority.execute_acquisition(tmp_path, environ={})

    private = json.loads((tmp_path / authority.PRIVATE_ROOT / authority._TERMINAL_KEY).read_bytes())
    assert private["result_kind"] == "RUNTIME-FAILURE"
    assert private["provider_transport_attempted"] is False
    assert private["program_014_credential_loads"] == 0
    assert (tmp_path / authority.PUBLIC_TERMINAL_PATH).exists()


@pytest.mark.parametrize("artifact", ("credential", "body", "receipt", "body-receipt", "derived"))
def test_every_surviving_operational_artifact_seals_before_credentials_or_transport(
    tmp_path: Path, monkeypatch: MonkeyPatch, artifact: str
) -> None:
    active, request, state = _configure_finite_execution(tmp_path, monkeypatch, activated=True)
    descriptor = authority._open_root(tmp_path, authority.PRIVATE_ROOT, create=False)
    prefix = predecessor._page_prefix(request, 1)
    if artifact == "credential":
        _write_credential_audit(descriptor, active, state, 1)
    elif artifact == "body":
        predecessor._append(descriptor, f"{prefix}.body", b"{}")
    elif artifact == "receipt":
        predecessor._append(descriptor, f"{prefix}.receipt.json", b"{}\n")
    elif artifact == "body-receipt":
        predecessor._append(descriptor, f"{prefix}.body", b"{}")
        predecessor._append(descriptor, f"{prefix}.receipt.json", b"{}\n")
    else:
        predecessor._append(descriptor, "combined-missing-coordinates.json", b"{}\n")
    os.close(descriptor)
    credential_reads: list[bool] = []
    monkeypatch.setattr(
        authority,
        "read_credentials",
        lambda *_args: credential_reads.append(True),
    )
    transport = authority.MockBarsTransport(
        [raw_contract.RawResponse(200, _body(request, 0, None))]
    )

    with pytest.raises(authority.Program014AuthorityError, match="terminally sealed"):
        authority._execute_mock_acquisition(tmp_path, environ=_credentials(), transport=transport)

    private = json.loads((tmp_path / authority.PRIVATE_ROOT / authority._TERMINAL_KEY).read_bytes())
    assert private["result_kind"] == "RUNTIME-FAILURE"
    assert private["provider_transport_attempted"] is False
    assert private["program_014_credential_loads"] == (1 if artifact == "credential" else 0)
    assert private["cumulative_request_intents"] <= science.MAXIMUM_REQUESTS_AND_RESPONSES
    assert private["cumulative_responses"] <= science.MAXIMUM_REQUESTS_AND_RESPONSES - 2
    assert private["cumulative_responses"] < private["cumulative_request_intents"]
    assert credential_reads == []
    assert transport.intents == ()


def test_receipt_only_corruption_cannot_exceed_the_combined_envelope(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _, request, _ = _configure_finite_execution(
        tmp_path,
        monkeypatch,
        completed_responses=science.MAXIMUM_REQUESTS_AND_RESPONSES - 2,
        activated=True,
    )
    descriptor = authority._open_root(tmp_path, authority.PRIVATE_ROOT, create=False)
    prefix = predecessor._page_prefix(request, 1)
    predecessor._append(descriptor, f"{prefix}.receipt.json", b"{}\n")
    os.close(descriptor)
    monkeypatch.setattr(
        authority,
        "read_credentials",
        lambda *_args: pytest.fail("receipt-only recovery accessed credentials"),
    )
    transport = authority.MockBarsTransport(
        [raw_contract.RawResponse(200, _body(request, 0, None))]
    )

    with pytest.raises(authority.Program014AuthorityError, match="terminally sealed"):
        authority._execute_mock_acquisition(tmp_path, environ=_credentials(), transport=transport)

    private = json.loads((tmp_path / authority.PRIVATE_ROOT / authority._TERMINAL_KEY).read_bytes())
    assert private["cumulative_request_intents"] == science.MAXIMUM_REQUESTS_AND_RESPONSES
    assert private["cumulative_responses"] == science.MAXIMUM_REQUESTS_AND_RESPONSES - 2
    assert private["provider_transport_attempted"] is False
    assert transport.intents == ()


def test_corrupt_complete_page_cannot_exceed_the_effective_response_ceiling(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    active, request, state = _configure_finite_execution(
        tmp_path,
        monkeypatch,
        completed_responses=science.MAXIMUM_REQUESTS_AND_RESPONSES - 2,
        activated=True,
    )
    descriptor = authority._open_root(tmp_path, authority.PRIVATE_ROOT, create=False)
    _write_claim(descriptor, active, state)
    body = _body(request, 0, None)
    _write_page(descriptor, active, state, request, 1, None, body)
    os.close(descriptor)
    prefix = predecessor._page_prefix(request, 1)
    (tmp_path / authority.PRIVATE_ROOT / f"{prefix}.receipt.json").write_bytes(b"{}\n")
    monkeypatch.setattr(
        credential_contract,
        "credential_presence_preflight",
        lambda *_args: pytest.fail("corrupt-state recovery accessed credentials"),
    )

    with pytest.raises(authority.Program014AuthorityError, match="terminally sealed"):
        authority.credential_presence_preflight(tmp_path, environ={})

    private = json.loads((tmp_path / authority.PRIVATE_ROOT / authority._TERMINAL_KEY).read_bytes())
    assert private["cumulative_request_intents"] == 22_176
    assert private["cumulative_responses"] == 22_174
    assert private["cumulative_response_bytes"] == len(body)


@pytest.mark.parametrize("changed_suffix", ("intent.json", "body", "receipt.json"))
def test_changed_consumed_page_checkpoint_seals_terminal_failure(
    tmp_path: Path, monkeypatch: MonkeyPatch, changed_suffix: str
) -> None:
    active, request, state = _configure_finite_execution(tmp_path, monkeypatch, activated=True)
    descriptor = authority._open_root(tmp_path, authority.PRIVATE_ROOT, create=False)
    _write_claim(descriptor, active, state)
    _write_credential_audit(descriptor, active, state, 1)
    body = _body(request, 0, None)
    _write_page(descriptor, active, state, request, 1, None, body)
    prefix = predecessor._page_prefix(request, 1)
    os.close(descriptor)
    (tmp_path / authority.PRIVATE_ROOT / f"{prefix}.{changed_suffix}").write_bytes(b"changed")
    monkeypatch.setattr(
        credential_contract,
        "credential_presence_preflight",
        lambda *_args: pytest.fail("changed-state recovery accessed credentials"),
    )

    with pytest.raises(authority.Program014AuthorityError, match="terminally sealed"):
        authority.credential_presence_preflight(tmp_path, environ={})

    private = json.loads((tmp_path / authority.PRIVATE_ROOT / authority._TERMINAL_KEY).read_bytes())
    assert private["result_kind"] == "RUNTIME-FAILURE"
    assert private["status"] == "FAIL-CONSUMED-NO-RETRY"
    assert private["cumulative_request_intents"] == 3
    assert private["cumulative_responses"] == 1
    assert private["cumulative_response_bytes"] == (len(body) if changed_suffix != "body" else 7)
    assert (tmp_path / authority.PUBLIC_TERMINAL_PATH).exists()


def test_preflight_seals_completed_page_from_an_interrupted_launcher(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    active, request, state = _configure_finite_execution(tmp_path, monkeypatch, activated=True)
    descriptor = authority._open_root(tmp_path, authority.PRIVATE_ROOT, create=False)
    _write_claim(descriptor, active, state)
    _write_credential_audit(descriptor, active, state, 1)
    _write_page(descriptor, active, state, request, 1, None, _body(request, 0, None))
    os.close(descriptor)

    with pytest.raises(authority.Program014AuthorityError, match="terminally sealed"):
        authority.credential_presence_preflight(tmp_path, environ=_credentials())
    terminal = json.loads(
        (tmp_path / authority.PRIVATE_ROOT / authority._TERMINAL_KEY).read_bytes()
    )
    assert terminal["result_kind"] == "RUNTIME-FAILURE"


def test_working_space_check_uses_available_bytes_not_existing_evidence(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    descriptor = _open_program_014_root(tmp_path)

    class _Filesystem:
        f_bavail = science.WORKING_DISK_RESERVATION_BYTES // 4096
        f_frsize = 4096

    monkeypatch.setattr(os, "fstatvfs", lambda _fd: _Filesystem())
    authority._require_working_disk_capacity(descriptor)
    _Filesystem.f_bavail -= 1
    with pytest.raises(authority.Program014AuthorityError, match="8 GiB"):
        authority._require_working_disk_capacity(descriptor)
    os.close(descriptor)


def test_existing_canonical_evidence_is_hashed_without_whole_file_read(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    descriptor = _open_program_014_root(tmp_path)
    payload = b"x" * (1024 * 1024 + 17)
    expected_sha256 = hashlib.sha256(payload).hexdigest()
    predecessor._append(descriptor, "combined-canonical-raw.jsonl", payload)
    temp_key, temp_descriptor = predecessor._new_temp(descriptor, "combined-canonical-raw")
    with os.fdopen(temp_descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    monkeypatch.setattr(
        predecessor,
        "_read",
        lambda *_args: pytest.fail("streaming hash called the whole-file reader"),
    )

    assert (
        authority._evidence_sha256_if_present(descriptor, "combined-canonical-raw.jsonl")
        == expected_sha256
    )
    authority._publish_temp_or_validate(
        descriptor,
        temp_key,
        "combined-canonical-raw.jsonl",
        expected_sha256,
    )

    assert not (tmp_path / authority.PRIVATE_ROOT / temp_key).exists()
    os.close(descriptor)


def test_admission_failure_keeps_private_identity_and_no_public_lineage(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    active, request, state = _configure_finite_execution(
        tmp_path, monkeypatch, admission_passed=False
    )
    transport = authority.MockBarsTransport(
        [raw_contract.RawResponse(200, _body(request, 0, None))]
    )

    result = authority._execute_mock_acquisition(
        tmp_path, environ=_credentials(), transport=transport
    )

    private = json.loads((tmp_path / authority.PRIVATE_ROOT / authority._TERMINAL_KEY).read_bytes())
    assert private["result_kind"] == "ADMISSION-FAILURE"
    assert private["status"] == "TERMINAL-FAIL-CONSUMED-NO-RETRY"
    assert isinstance(private["private_dataset_identity"], str)
    assert len(private["private_dataset_identity"]) == 64
    assert private["dataset_lineage_identity"] is None
    assert private["public_dataset_lineage_manifest"] is None
    assert result.public_summary()["dataset_lineage_manifest"] is None
    assert active["authority_id"] == authority.CHILD_AUTHORITY_ID
    assert state.frontier_request_index == 0


@pytest.mark.parametrize(
    "mutation",
    (
        "missing-top-level",
        "unknown-top-level",
        "changed-top-level",
        "missing-nested",
        "unknown-nested",
        "changed-nested",
    ),
)
def test_invalid_public_terminal_fields_fail_before_credentials_or_private_roots(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    mutation: str,
) -> None:
    public = _public_terminal()
    if mutation == "missing-top-level":
        public.pop("status")
    elif mutation == "unknown-top-level":
        public["unexpected"] = False
    elif mutation == "changed-top-level":
        public["program_id"] = "changed"
    elif mutation == "missing-nested":
        public["privacy_assertions"].pop("credentials_stored")
    elif mutation == "unknown-nested":
        public["scientific_assertions"]["unexpected"] = False
    else:
        public["disabled_authority"]["broker_writes"] = True
    path = tmp_path / authority.PUBLIC_TERMINAL_PATH
    path.parent.mkdir(parents=True)
    path.write_bytes((canonical_json(public) + "\n").encode())
    opened: list[bool] = []
    credential_checks: list[bool] = []
    monkeypatch.setattr(
        authority,
        "_open_root",
        lambda *_args, **_kwargs: opened.append(True),
    )
    monkeypatch.setattr(
        credential_contract,
        "credential_presence_preflight",
        lambda *_args: credential_checks.append(True),
    )

    with pytest.raises(authority.Program014AuthorityError):
        authority.credential_presence_preflight(tmp_path, environ={})

    assert opened == []
    assert credential_checks == []


def test_every_lifecycle_entrypoint_rejects_an_exact_public_terminal_first(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    terminal_path = tmp_path / "terminal.json"
    payload = (canonical_json(_public_terminal()) + "\n").encode()
    terminal_path.write_bytes(payload)
    monkeypatch.setattr(authority, "PUBLIC_TERMINAL_PATH", terminal_path)
    monkeypatch.setattr(authority, "_PUBLIC_TERMINAL_SHA256", hashlib.sha256(payload).hexdigest())
    opened: list[bool] = []
    credential_checks: list[bool] = []
    monkeypatch.setattr(
        authority,
        "_open_root",
        lambda *_args, **_kwargs: opened.append(True),
    )
    monkeypatch.setattr(
        credential_contract,
        "credential_presence_preflight",
        lambda *_args: credential_checks.append(True),
    )

    for operation in (
        lambda: authority.credential_presence_preflight(_REPOSITORY, environ={}),
        lambda: authority.derive_active_authority(_REPOSITORY),
        lambda: authority.execute_acquisition(_REPOSITORY, environ={}),
    ):
        with pytest.raises(authority.Program014AuthorityError, match="terminally revoked"):
            operation()

    assert opened == []
    assert credential_checks == []


def test_valid_shaped_terminal_without_immutable_binding_rejects_before_credentials(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    terminal = _public_terminal()
    terminal["observed_at"] = "2026-09-04T22:34:41.313170Z"
    path = tmp_path / "terminal.json"
    path.write_bytes((canonical_json(terminal) + "\n").encode())
    credential_checks: list[bool] = []
    monkeypatch.setattr(authority, "PUBLIC_TERMINAL_PATH", path)
    monkeypatch.setattr(authority, "_PUBLIC_TERMINAL_SHA256", None)
    monkeypatch.setattr(
        credential_contract,
        "credential_presence_preflight",
        lambda *_args: credential_checks.append(True),
    )

    with pytest.raises(authority.Program014AuthorityError, match="lacks immutable binding"):
        authority.credential_presence_preflight(_REPOSITORY, environ={})

    assert credential_checks == []


def test_missing_terminal_rejects_before_credentials_or_private_roots(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    opened: list[bool] = []
    credential_checks: list[bool] = []
    monkeypatch.setattr(authority, "PUBLIC_TERMINAL_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(authority, "_PUBLIC_TERMINAL_SHA256", "a" * 64)
    monkeypatch.setattr(
        authority,
        "_open_root",
        lambda *_args, **_kwargs: opened.append(True),
    )
    monkeypatch.setattr(
        credential_contract,
        "credential_presence_preflight",
        lambda *_args: credential_checks.append(True),
    )

    for operation in (
        lambda: authority.credential_presence_preflight(_REPOSITORY, environ={}),
        lambda: authority.derive_active_authority(_REPOSITORY),
        lambda: authority.execute_acquisition(_REPOSITORY, environ={}),
    ):
        with pytest.raises(authority.Program014AuthorityError, match="artifact is absent"):
            operation()

    assert opened == []
    assert credential_checks == []


def test_changed_terminal_observation_time_rejects_before_credentials(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    terminal = _public_terminal()
    expected_payload = (canonical_json(terminal) + "\n").encode()
    terminal["observed_at"] = "2026-09-04T22:34:41.313170Z"
    path = tmp_path / "terminal.json"
    path.write_bytes((canonical_json(terminal) + "\n").encode())
    credential_checks: list[bool] = []
    monkeypatch.setattr(authority, "PUBLIC_TERMINAL_PATH", path)
    monkeypatch.setattr(
        authority, "_PUBLIC_TERMINAL_SHA256", hashlib.sha256(expected_payload).hexdigest()
    )
    monkeypatch.setattr(
        credential_contract,
        "credential_presence_preflight",
        lambda *_args: credential_checks.append(True),
    )

    with pytest.raises(authority.Program014AuthorityError, match="semantics differ"):
        authority.credential_presence_preflight(_REPOSITORY, environ={})

    assert credential_checks == []


def test_valid_private_terminal_recovers_without_credentials_or_transport(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _, request, _ = _configure_finite_execution(tmp_path, monkeypatch)
    original_append_public = authority._append_public_atomic
    monkeypatch.setattr(
        authority,
        "_append_public_atomic",
        lambda *_args: (_ for _ in ()).throw(_AbruptExit()),
    )

    with pytest.raises(authority.Program014PostClaimPersistenceError):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport(
                [raw_contract.RawResponse(200, _body(request, 0, None))]
            ),
        )

    public_path = tmp_path / authority.PUBLIC_TERMINAL_PATH
    private_path = tmp_path / authority.PRIVATE_ROOT / authority._TERMINAL_KEY
    assert private_path.exists()
    assert not public_path.exists()
    monkeypatch.setattr(authority, "_append_public_atomic", original_append_public)
    monkeypatch.setattr(
        authority,
        "read_credentials",
        lambda *_args: pytest.fail("private terminal recovery accessed credentials"),
    )
    transport = authority.MockBarsTransport([])

    with pytest.raises(authority.Program014AuthorityError, match="terminally sealed"):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=transport,
        )

    private = json.loads(private_path.read_bytes())
    assert public_path.read_bytes() == authority._public_terminal_payload(private)
    assert transport.intents == ()


def test_atomic_publication_recovers_after_interruption_before_link(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    descriptor = _open_program_014_root(tmp_path)
    payload = (canonical_json(_public_terminal()) + "\n").encode()
    original_link = os.link
    monkeypatch.setattr(
        os,
        "link",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(_AbruptExit()),
    )

    with pytest.raises(_AbruptExit):
        authority._append_public_atomic(tmp_path, descriptor, payload)

    public_path = tmp_path / authority.PUBLIC_TERMINAL_PATH
    assert not public_path.exists()
    monkeypatch.setattr(os, "link", original_link)
    authority._append_public_atomic(tmp_path, descriptor, payload)
    assert public_path.read_bytes() == payload
    os.close(descriptor)


def test_atomic_publication_recovers_after_link_before_parent_fsync(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    descriptor = _open_program_014_root(tmp_path)
    payload = (canonical_json(_public_terminal()) + "\n").encode()
    original_fsync = os.fsync
    fsync_calls = 0

    def interrupt_parent_fsync(file_descriptor: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 2:
            raise _AbruptExit()
        original_fsync(file_descriptor)

    monkeypatch.setattr(os, "fsync", interrupt_parent_fsync)
    with pytest.raises(_AbruptExit):
        authority._append_public_atomic(tmp_path, descriptor, payload)

    public_path = tmp_path / authority.PUBLIC_TERMINAL_PATH
    assert public_path.read_bytes() == payload
    monkeypatch.setattr(os, "fsync", original_fsync)
    authority._append_public_atomic(tmp_path, descriptor, payload)
    assert public_path.read_bytes() == payload
    os.close(descriptor)


def test_atomic_publication_never_overwrites_different_public_bytes(
    tmp_path: Path,
) -> None:
    descriptor = _open_program_014_root(tmp_path)
    public_path = tmp_path / authority.PUBLIC_TERMINAL_PATH
    public_path.write_bytes(b"{}\n")
    payload = (canonical_json(_public_terminal()) + "\n").encode()

    with pytest.raises(authority.Program014AuthorityError, match="artifact differs"):
        authority._append_public_atomic(tmp_path, descriptor, payload)

    assert public_path.read_bytes() == b"{}\n"
    os.close(descriptor)


def test_repository_terminal_bytes_exactly_equal_cli_output(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    _, request, _ = _configure_finite_execution(tmp_path, monkeypatch)
    execution = authority._execute_mock_acquisition(
        tmp_path,
        environ=_credentials(),
        transport=authority.MockBarsTransport(
            [raw_contract.RawResponse(200, _body(request, 0, None))]
        ),
    )
    terminal_bytes = (tmp_path / authority.PUBLIC_TERMINAL_PATH).read_bytes()
    assert execution.public_payload() == terminal_bytes
    calls: list[tuple[str, int]] = []

    def execute(*_args: Any, **_kwargs: Any) -> authority.AcquisitionExecution:
        calls.append(("execute", os.getpid()))
        return execution

    monkeypatch.setattr(authority, "execute_acquisition", execute)
    monkeypatch.setattr(
        base_cli,
        "load_dotenv",
        lambda: pytest.fail("Program 014 CLI loaded dotenv"),
    )
    monkeypatch.setenv("TRADING_LAB_MODE", "research")

    assert dispatcher.main(("data", "acquire", "program-014-ohlcv", "run")) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.encode() == terminal_bytes
    assert calls == [("execute", os.getpid())]


def test_secret_guard_allows_reserved_program_014_control_artifacts_only(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    spec = importlib.util.spec_from_file_location(
        "program_014_check_secrets", _REPOSITORY / "scripts/check_secrets.py"
    )
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    monkeypatch.chdir(tmp_path)
    public = authority.PUBLIC_TERMINAL_PATH
    terminal_review = Path(
        "config/research/program-014-exposed-prefix-raw-alpaca-sip-recovery-and-structural-admission-terminal-result-independent-review-v1.json"
    )
    reserved = (
        public,
        terminal_review,
        authority.CHILD_AUTHORITY_PATH,
        authority.CHILD_REVIEW_PATH,
    )
    observation = Path("config/research/program-014-market-observations.json")
    private = Path(".trading-lab/program-014-private-terminal.json")
    for path in (*reserved, observation, private):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(guard, "tracked_files", lambda: [*reserved, observation, private])

    assert guard.main() == 1
    errors = capsys.readouterr().err
    for path in reserved:
        assert path.as_posix() in guard.PUBLIC_PROGRAM_JSON
        assert path.as_posix() not in errors
    assert f"{observation}:private-market-data-path" in errors
    assert f"{private}:private-market-data-path" in errors
