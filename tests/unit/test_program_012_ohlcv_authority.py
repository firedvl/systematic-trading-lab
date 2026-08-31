from __future__ import annotations

import json
import os
import threading
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pytest import CaptureFixture, MonkeyPatch

import systematic_trading_lab.intraday_fed_policy_absorption_001_cli as dispatcher
import systematic_trading_lab.program_007_alpaca as raw_contract
import systematic_trading_lab.program_011_ohlcv as program_011
import systematic_trading_lab.program_011_ohlcv_authority as predecessor
import systematic_trading_lab.program_012_ohlcv as program_012
import systematic_trading_lab.program_012_ohlcv_authority as authority
from systematic_trading_lab.fingerprints import canonical_json, fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]


class _AbruptExit(BaseException):
    pass


def _credentials() -> dict[str, str]:
    return {
        authority.CREDENTIAL_NAMES[0]: "synthetic-key-material",
        authority.CREDENTIAL_NAMES[1]: "synthetic-secret-material",
    }


def _active_authority() -> dict[str, Any]:
    return {
        "authority_id": authority.CHILD_AUTHORITY_ID,
        "authority_fingerprint": "a" * 64,
        "child_identity_fingerprint": "b" * 64,
        "control_lineage": {
            "runtime_source_commit": "c" * 40,
            "synchronized_main_commit": "d" * 40,
        },
    }


def _request() -> program_011.SessionRequest:
    return program_012.acquisition_requests()[0]


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


def _root(tmp_path: Path) -> int:
    descriptor = authority._open_private_root(tmp_path, create=True)
    with predecessor._LockedRoot(descriptor):
        pass
    return descriptor


def _write_credential_audit(
    root_descriptor: int,
    active: dict[str, Any],
    sequence: int,
    *,
    receipt: bool = True,
) -> None:
    unsigned = {
        "schema_version": "program-012-private-credential-load-attempt-v1",
        "authority_fingerprint": active["authority_fingerprint"],
        "source_commit": active["control_lineage"]["runtime_source_commit"],
        "process_recovery_sequence": sequence,
    }
    attempt = {**unsigned, "attempt_identity": fingerprint(unsigned)}
    prefix = f"credential-load-{sequence:06d}"
    authority._append(
        root_descriptor,
        f"{prefix}.attempt.json",
        (canonical_json(attempt) + "\n").encode(),
    )
    if receipt:
        authority._append(
            root_descriptor,
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


def _write_claim(root_descriptor: int, active: dict[str, Any]) -> None:
    authority._append(
        root_descriptor,
        "claim.json",
        authority._claim_payload(active, active["control_lineage"]["runtime_source_commit"]),
    )


def _write_page(
    root_descriptor: int,
    active: dict[str, Any],
    request: program_011.SessionRequest,
    page_index: int,
    incoming_token: str | None,
    body: bytes,
) -> None:
    source_commit = active["control_lineage"]["runtime_source_commit"]
    intent = program_011.PageIntent(
        request.identity,
        page_index,
        request.url(incoming_token),
        incoming_token,
    )
    prefix = authority._page_prefix(request, page_index)
    authority._append_atomic(
        root_descriptor,
        f"{prefix}.intent.json",
        authority._intent_payload(active, source_commit, request, intent),
    )
    authority._append(root_descriptor, f"{prefix}.body", body)
    receipt = authority._response_receipt(
        active,
        source_commit,
        request,
        intent,
        raw_contract.RawResponse(200, body),
        authority._utc_now(),
    )
    authority._append(
        root_descriptor,
        f"{prefix}.receipt.json",
        (canonical_json(receipt) + "\n").encode(),
    )


def test_operation_contract_revalidates_the_exposed_prefix() -> None:
    proposal = authority.validate_operation_contract(_REPOSITORY)

    assert proposal["program_id"] == authority.PROGRAM_ID
    assert proposal["proposal_fingerprint"] == authority.OPERATION_MANIFEST["fingerprint"]


def test_credential_preflight_cli_prints_only_pass_or_missing_names(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    control_checks: list[Path] = []

    def validate_controls(repository: Path) -> dict[str, Any]:
        control_checks.append(repository)
        return _active_authority()

    monkeypatch.setattr(authority, "_derive_control_validated_authority", validate_controls)
    for name in authority.CREDENTIAL_NAMES:
        monkeypatch.delenv(name, raising=False)
    assert dispatcher.main(("data", "acquire", "program-012-ohlcv", "credential-preflight")) == 1
    missing = capsys.readouterr()
    assert missing.err == ""
    assert missing.out.splitlines() == [f"MISSING: {name}" for name in authority.CREDENTIAL_NAMES]

    values = _credentials()
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    assert dispatcher.main(("data", "acquire", "program-012-ohlcv", "credential-preflight")) == 0
    passed = capsys.readouterr()
    assert passed.err == ""
    assert passed.out == "PASS\n"
    assert all(value not in missing.out + passed.out for value in values.values())
    assert control_checks == [_REPOSITORY, _REPOSITORY]


def test_finite_run_activates_claims_persists_and_seals_once(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    active = _active_authority()
    request = _request()
    proposal: dict[str, Any] = {
        "bindings": {
            "program_005_policy_precedent": {},
            "program_002_fixed_quarantine_incident": {},
            "program_007_public_unit_changing_action_ledger": {},
        }
    }
    admission = {
        "status": "ADMITTED-PROGRAM-012-RAW-STRUCTURAL-PREFIX",
        "admission_passed": True,
        "fixed_quarantine_sessions": [],
        "unexpected_excluded_sessions": [],
        "missing_coordinate_count": len(request.expected_coordinates) - 1,
        "excluded_full_session_count": 0,
        "admission_fingerprint": "e" * 64,
    }
    monkeypatch.setattr(
        authority, "_derive_control_validated_authority", lambda _repository: active
    )
    monkeypatch.setattr(predecessor, "_GitPolicySnapshot", lambda *_args: nullcontext())
    monkeypatch.setattr(predecessor, "_current_protected_ranges", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        authority, "validate_operation_contract", lambda *_args, **_kwargs: proposal
    )
    monkeypatch.setattr(authority, "_load_bound", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(authority, "_require_working_disk_capacity", lambda _descriptor: None)
    monkeypatch.setattr(program_012, "acquisition_requests", lambda: (request,))
    monkeypatch.setattr(program_012, "full_trade_sessions", lambda: frozenset({request.session}))
    monkeypatch.setattr(program_012, "EXPECTED_SESSION_COUNT", 1)
    monkeypatch.setattr(program_012, "EXPECTED_COORDINATE_COUNT", len(request.expected_coordinates))
    monkeypatch.setattr(
        program_012, "assess_structural_admission", lambda *_args, **_kwargs: admission
    )

    authority.activate_authority(tmp_path, environ=_credentials())
    transport = authority.MockBarsTransport(
        [raw_contract.RawResponse(200, _body(request, 0, None))]
    )
    root = tmp_path / authority.PRIVATE_ROOT
    original_require_exhausted = transport.require_exhausted

    def require_exhausted() -> None:
        assert not (root / "acquisition-receipt.json").exists()
        original_require_exhausted()

    monkeypatch.setattr(transport, "require_exhausted", require_exhausted)
    execution = authority._execute_mock_acquisition(
        tmp_path, environ=_credentials(), transport=transport
    )

    assert execution.admission_passed is True
    assert execution.request_count == execution.response_count == 1
    assert execution.credential_loads == 1
    assert (root / "claim.json").exists()
    assert (root / "canonical-raw.jsonl").exists()
    assert (root / "dataset-manifest.json").exists()
    assert (root / "acquisition-receipt.json").exists()
    public = json.dumps(execution.public_summary(), sort_keys=True)
    assert "opaque-page" not in public
    assert "IWM@" not in public
    with pytest.raises(authority.Program012AuthorityError, match="terminally sealed"):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport([]),
        )


def test_crash_after_fsynced_intent_forbids_a_second_transport_call(
    tmp_path: Path,
) -> None:
    root_descriptor = _root(tmp_path)
    active = _active_authority()
    request = _request()
    transport = authority.MockBarsTransport(
        [raw_contract.RawResponse(200, _body(request, 0, None))]
    )
    loader = authority._CredentialLoader(
        root_descriptor,
        active,
        active["control_lineage"]["runtime_source_commit"],
        _credentials(),
        transport,
        None,
    )

    def crash_after_intent() -> None:
        _write_credential_audit(root_descriptor, active, 1)
        _write_claim(root_descriptor, active)
        raise _AbruptExit

    source = authority._PersistentSessionSource(
        root_descriptor,
        request,
        active,
        active["control_lineage"]["runtime_source_commit"],
        authority._Budget(),
        loader,
        lambda: _write_claim(root_descriptor, active),
        crash_after_intent,
        None,
    )

    with pytest.raises(_AbruptExit):
        authority._execute_session(request, source)

    prefix = authority._page_prefix(request, 1)
    assert authority._exists(root_descriptor, f"{prefix}.intent.json")
    assert not authority._exists(root_descriptor, f"{prefix}.body")
    assert not authority._exists(root_descriptor, f"{prefix}.receipt.json")
    assert transport.intents == ()
    with pytest.raises(authority.Program012AuthorityError, match="forbids request reissue"):
        authority._reconstruct_state(
            root_descriptor,
            authority=active,
            source_commit=active["control_lineage"]["runtime_source_commit"],
        )
    assert transport.intents == ()
    os.close(root_descriptor)


def test_completed_nonterminal_page_recovers_one_continuation_and_one_load(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    active = _active_authority()
    request = _request()
    source_commit = active["control_lineage"]["runtime_source_commit"]
    root_descriptor = _root(tmp_path)
    first_transport = authority.MockBarsTransport(
        [raw_contract.RawResponse(200, _body(request, 0, "opaque-page-2"))]
    )
    first_loader = authority._CredentialLoader(
        root_descriptor,
        active,
        source_commit,
        _credentials(),
        first_transport,
        None,
    )
    first_source = authority._PersistentSessionSource(
        root_descriptor,
        request,
        active,
        source_commit,
        authority._Budget(),
        first_loader,
        lambda: _write_claim(root_descriptor, active),
        None,
        lambda: (_ for _ in ()).throw(_AbruptExit()),
    )

    with pytest.raises(_AbruptExit):
        authority._execute_session(request, first_source)
    assert len(first_transport.intents) == 1
    os.close(root_descriptor)

    root_descriptor = authority._open_private_root(tmp_path, create=False)
    budget = authority._reconstruct_state(
        root_descriptor, authority=active, source_commit=source_commit
    )
    assert (budget.requests, budget.responses) == (1, 1)
    credential_reads = 0
    original_read = authority.read_credentials

    def read_credentials(environ: dict[str, str]) -> tuple[str, str]:
        nonlocal credential_reads
        credential_reads += 1
        return original_read(environ)

    monkeypatch.setattr(authority, "read_credentials", read_credentials)
    recovery_transport = authority.MockBarsTransport(
        [raw_contract.RawResponse(200, _body(request, 1, None))]
    )
    recovery_loader = authority._CredentialLoader(
        root_descriptor,
        active,
        source_commit,
        _credentials(),
        recovery_transport,
        None,
    )
    recovery_source = authority._PersistentSessionSource(
        root_descriptor,
        request,
        active,
        source_commit,
        budget,
        recovery_loader,
        lambda: authority._validate_claim(root_descriptor, active, source_commit),
        None,
        None,
    )

    result = authority._execute_session(request, recovery_source)

    assert len(result.pages) == 2
    assert credential_reads == 1
    assert len(recovery_transport.intents) == 1
    assert recovery_transport.intents[0].incoming_page_token == "opaque-page-2"
    assert authority._credential_load_count(root_descriptor) == 2
    os.close(root_descriptor)


def test_malformed_response_is_receipted_and_counted_before_parsing(
    tmp_path: Path,
) -> None:
    active = _active_authority()
    request = _request()
    source_commit = active["control_lineage"]["runtime_source_commit"]
    root_descriptor = _root(tmp_path)
    budget = authority._Budget()
    transport = authority.MockBarsTransport([raw_contract.RawResponse(200, b"{")])
    loader = authority._CredentialLoader(
        root_descriptor,
        active,
        source_commit,
        _credentials(),
        transport,
        None,
    )
    source = authority._PersistentSessionSource(
        root_descriptor,
        request,
        active,
        source_commit,
        budget,
        loader,
        lambda: _write_claim(root_descriptor, active),
        None,
        None,
    )

    with pytest.raises(program_011.Program011Error, match="not valid JSON"):
        authority._execute_session(request, source)

    prefix = authority._page_prefix(request, 1)
    receipt = json.loads(authority._read(root_descriptor, f"{prefix}.receipt.json"))
    assert set(receipt) == {
        "schema_version",
        "authority_fingerprint",
        "source_commit",
        "session",
        "page_index",
        "request_identity",
        "status",
        "retained_response_bytes",
        "response_sha256",
        "observed_at",
    }
    assert (budget.requests, budget.responses, budget.response_bytes) == (1, 1, 1)
    recovered = authority._Budget()
    with pytest.raises(program_011.Program011Error, match="not valid JSON"):
        authority._reconstruct_state(
            root_descriptor,
            authority=active,
            source_commit=source_commit,
            budget=recovered,
        )
    assert (recovered.requests, recovered.responses, recovered.response_bytes) == (1, 1, 1)
    assert recovered.latest_response_at == authority._parse_observed_at(receipt["observed_at"])
    os.close(root_descriptor)


def test_recovery_pacer_waits_from_latest_durable_response() -> None:
    latest = datetime(2026, 8, 31, 12, tzinfo=UTC)
    current = [latest + timedelta(seconds=0.2)]
    sleeps: list[float] = []
    paced: list[None] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        current[0] += timedelta(seconds=seconds)

    pacer = authority._RecoveryPacer(
        latest,
        clock=lambda: current[0],
        sleep=sleep,
        pace=lambda: paced.append(None),
    )

    pacer()
    pacer()

    assert sleeps == pytest.approx([0.3])
    assert paced == [None, None]


def test_unpaired_credential_attempt_counts_as_one_load(
    tmp_path: Path,
) -> None:
    active = _active_authority()
    request = _request()
    root_descriptor = _root(tmp_path)
    transport = authority.MockBarsTransport([])
    loader = authority._CredentialLoader(
        root_descriptor,
        active,
        active["control_lineage"]["runtime_source_commit"],
        _credentials(),
        transport,
        lambda: (_ for _ in ()).throw(_AbruptExit()),
    )
    intent = program_011.PageIntent(request.identity, 1, request.url(), None)

    with pytest.raises(_AbruptExit):
        loader.get(intent, lambda: None)

    assert authority._credential_load_count(root_descriptor) == 1
    assert not authority._exists(root_descriptor, "credential-load-000001.receipt.json")
    failure = json.loads(
        authority._failure_payload(
            root_descriptor, authority.Program012AuthorityError("synthetic"), None
        )
    )
    assert failure["credential_loads"] == 1
    assert transport.intents == ()
    os.close(root_descriptor)


def test_two_concurrent_recovery_owners_send_one_continuation(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    active = _active_authority()
    request = _request()
    source_commit = active["control_lineage"]["runtime_source_commit"]
    setup_descriptor = _root(tmp_path)
    _write_claim(setup_descriptor, active)
    _write_credential_audit(setup_descriptor, active, 1)
    _write_page(
        setup_descriptor,
        active,
        request,
        1,
        None,
        _body(request, 0, "opaque-page-2"),
    )
    os.close(setup_descriptor)

    credential_reads = 0
    read_lock = threading.Lock()

    def read_credentials(_environ: dict[str, str]) -> tuple[str, str]:
        nonlocal credential_reads
        with read_lock:
            credential_reads += 1
        return "synthetic-key-material", "synthetic-secret-material"

    monkeypatch.setattr(authority, "read_credentials", read_credentials)
    transport = authority.MockBarsTransport(
        [raw_contract.RawResponse(200, _body(request, 1, None))]
    )
    barrier = threading.Barrier(3)
    errors: list[BaseException] = []
    results: list[program_011.SessionResult] = []

    def recover() -> None:
        descriptor = authority._open_private_root(tmp_path, create=False)
        try:
            barrier.wait()
            with predecessor._LockedRoot(descriptor):
                budget = authority._reconstruct_state(
                    descriptor, authority=active, source_commit=source_commit
                )
                loader = authority._CredentialLoader(
                    descriptor,
                    active,
                    source_commit,
                    _credentials(),
                    transport,
                    None,
                )
                source = authority._PersistentSessionSource(
                    descriptor,
                    request,
                    active,
                    source_commit,
                    budget,
                    loader,
                    lambda: authority._validate_claim(descriptor, active, source_commit),
                    None,
                    None,
                )
                results.append(authority._execute_session(request, source))
        except BaseException as error:
            errors.append(error)
        finally:
            os.close(descriptor)

    threads = [threading.Thread(target=recover) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert len(results) == 2
    assert credential_reads == 1
    assert len(transport.intents) == 1
    assert transport.intents[0].incoming_page_token == "opaque-page-2"
    descriptor = authority._open_private_root(tmp_path, create=False)
    try:
        assert authority._credential_load_count(descriptor) == 2
    finally:
        os.close(descriptor)


def test_recovery_reconstructs_cumulative_request_response_and_byte_budgets(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    active = _active_authority()
    request = _request()
    source_commit = active["control_lineage"]["runtime_source_commit"]
    root_descriptor = _root(tmp_path)
    _write_claim(root_descriptor, active)
    _write_credential_audit(root_descriptor, active, 1)
    first = _body(request, 0, "opaque-page-2")
    second = _body(request, 1, None)
    _write_page(root_descriptor, active, request, 1, None, first)
    _write_page(root_descriptor, active, request, 2, "opaque-page-2", second)

    budget = authority._reconstruct_state(
        root_descriptor, authority=active, source_commit=source_commit
    )

    assert budget.requests == budget.responses == 2
    assert budget.response_bytes == len(first) + len(second)
    assert budget.session_bytes[request.session] == len(first) + len(second)
    monkeypatch.setattr(program_012, "MAXIMUM_REQUESTS_AND_RESPONSES", 2)
    with pytest.raises(authority.Program012AuthorityError, match="request ceiling"):
        budget.reserve_request()
    monkeypatch.setattr(program_012, "MAXIMUM_REQUESTS_AND_RESPONSES", 3)
    monkeypatch.setattr(program_012, "MAXIMUM_TOTAL_RESPONSE_BYTES", len(first) + len(second))
    budget.reserve_request()
    third = program_011.PageIntent(request.identity, 3, request.url("unused"), "unused")
    with pytest.raises(authority.Program012AuthorityError, match="total response byte ceiling"):
        budget.accept_response(request, third, 200, b"x", datetime.now(UTC))
    os.close(root_descriptor)
