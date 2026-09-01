from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import subprocess
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pytest import CaptureFixture, MonkeyPatch

import systematic_trading_lab.cli as base_cli
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


@pytest.fixture(autouse=True)
def _reset_process_credential_latch(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(authority, "_PROCESS_CREDENTIAL_PID", None)


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
    (tmp_path / authority.PUBLIC_TERMINAL_PATH.parent).mkdir(parents=True, exist_ok=True)
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
    authority._append_atomic(
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


def _assert_public_terminal_has_no_private_commitments(
    public: dict[str, Any], root: Path
) -> dict[str, Any]:
    terminal_paths = [root / key for key in authority._TERMINAL_KEYS if (root / key).exists()]
    assert len(terminal_paths) == 1
    terminal_path = terminal_paths[0]
    terminal: dict[str, Any] = json.loads(terminal_path.read_bytes())
    assert public["private_evidence_hashes"] == {
        "response_manifest_sha256": terminal["response_manifest_sha256"],
        "canonical_raw_sha256": terminal["canonical_raw_sha256"],
    }
    serialized = json.dumps(public, sort_keys=True)
    private_commitments = {
        hashlib.sha256(terminal_path.read_bytes()).hexdigest(),
        terminal["terminal_fingerprint"],
    }
    for key in (
        "claim.json",
        "missing-coordinates.json",
        "structural-admission.json",
        "dataset-manifest.json",
    ):
        path = root / key
        if path.exists():
            private_commitments.add(hashlib.sha256(path.read_bytes()).hexdigest())
    private_dataset_identity = terminal.get("private_dataset_identity")
    if private_dataset_identity is not None:
        private_commitments.add(private_dataset_identity)
    assert all(value not in serialized for value in private_commitments)
    return terminal


def _configure_finite_execution(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    *,
    admission_passed: bool = True,
    retained_coordinate_count: int = 1,
) -> tuple[dict[str, Any], program_011.SessionRequest]:
    active = _active_authority()
    request = _request()
    proposal: dict[str, Any] = {
        "bindings": {
            "program_005_policy_precedent": {},
            "program_002_fixed_quarantine_incident": {},
            "program_007_public_unit_changing_action_ledger": authority._ACTION_LEDGER_MANIFEST,
        }
    }
    admission = {
        "schema_version": "program-012-private-structural-admission-report-v1",
        "program_id": authority.PROGRAM_ID,
        "status": (
            "ADMITTED-PROGRAM-012-RAW-STRUCTURAL-PREFIX"
            if admission_passed
            else "TERMINAL-FAIL-CONSUMED-NO-RETRY"
        ),
        "admission_passed": admission_passed,
        "failures": [] if admission_passed else ["global-count"],
        "fixed_quarantine_sessions": [],
        "unexpected_excluded_sessions": [],
        "missing_coordinate_count": len(request.expected_coordinates) - retained_coordinate_count,
        "excluded_full_session_count": 0,
        "program_002_admission": False,
        "program_002_quote_windows_evaluated": 0,
        "strategy_metrics_present": False,
    }
    admission["admission_fingerprint"] = fingerprint(admission)
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
    (tmp_path / authority.PUBLIC_TERMINAL_PATH.parent).mkdir(parents=True)
    authority.activate_authority(tmp_path, environ=_credentials())
    return active, request


def _recover_process(
    repository: str,
    active: dict[str, Any],
    start: Any,
    outputs: Any,
) -> None:
    request = _request()
    source_commit = active["control_lineage"]["runtime_source_commit"]
    descriptor = authority._open_private_root(Path(repository), create=False)
    transport = authority.MockBarsTransport(
        [raw_contract.RawResponse(200, _body(request, 1, None))]
    )
    try:
        start.wait()
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
            result = authority._execute_session(request, source)
            outputs.put(
                (
                    None,
                    len(result.pages),
                    tuple(intent.incoming_page_token for intent in transport.intents),
                )
            )
    except BaseException as error:
        outputs.put((type(error).__name__, 0, ()))
    finally:
        os.close(descriptor)


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


def test_cli_validates_public_controls_before_loading_dotenv(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    events: list[str] = []

    def validate_controls(_repository: Path) -> dict[str, Any]:
        events.append("controls")
        return _active_authority()

    monkeypatch.setattr(
        authority,
        "_derive_control_validated_authority",
        validate_controls,
    )
    monkeypatch.setattr(
        base_cli,
        "load_dotenv",
        lambda: pytest.fail("global dotenv loader ran for Program 012"),
    )
    for name, value in _credentials().items():
        monkeypatch.setenv(name, value)

    assert dispatcher.main(("data", "acquire", "program-012-ohlcv", "credential-preflight")) == 0

    assert capsys.readouterr().out == "PASS\n"
    assert events == ["controls"]


def test_git_preflight_allows_only_the_validated_generated_terminal_on_reentry(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Program 012 Test")
    _git(tmp_path, "config", "user.email", "program-012@example.invalid")
    (tmp_path / ".gitignore").write_text(".trading-lab/\n", encoding="utf-8")
    (tmp_path / "source.txt").write_text("reviewed\n", encoding="utf-8")
    _git(tmp_path, "add", ".gitignore", "source.txt")
    _git(tmp_path, "commit", "-m", "reviewed source")
    source_commit = _git(tmp_path, "rev-parse", "HEAD")
    source_tree = _git(tmp_path, "rev-parse", "HEAD^{tree}")
    for path in (authority.CHILD_AUTHORITY_PATH, authority.CHILD_REVIEW_PATH):
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("{}\n", encoding="utf-8")
        _git(tmp_path, "add", path.as_posix())
    _git(tmp_path, "commit", "-m", "review child authority")
    head = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", head)
    identity = {
        "child_authority_id": authority.CHILD_AUTHORITY_ID,
        "program_ordinal": authority.PROGRAM_ORDINAL,
        "program_id": authority.PROGRAM_ID,
        "operation_manifest": authority.OPERATION_MANIFEST,
        "runtime_entrypoint": "src/systematic_trading_lab/program_012_ohlcv_authority.py",
        "child_identity_fingerprint": "b" * 64,
        "authority": {key: True for key in authority._ENABLED_AUTHORITY},
        "runtime_binding": {
            "source_commit": source_commit,
            "source_tree": source_tree,
            "source_files": [
                {"path": path}
                for path in {
                    predecessor.PROTECTED_CHRONOLOGY_PATH.as_posix(),
                    *(path.as_posix() for path in predecessor.PROTECTED_CHRONOLOGY_SOURCE_PATHS),
                    *(
                        path.as_posix()
                        for path in predecessor.PROTECTED_CHRONOLOGY_REGISTRATION_PATHS
                    ),
                    str(authority.OPERATION_MANIFEST["path"]),
                }
            ],
        },
    }
    monkeypatch.setattr(authority, "derive_child_identity", lambda *_args: identity)
    monkeypatch.setattr(
        predecessor, "_validate_protected_registration_set", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(authority, "validate_operation_contract", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(predecessor, "_GitPolicySnapshot", lambda *_args: nullcontext())

    active = dict(authority._derive_control_validated_authority(tmp_path))
    descriptor = _root(tmp_path)
    try:
        authority._append(
            descriptor,
            "active-authority.json",
            (canonical_json(active) + "\n").encode(),
        )
        _write_claim(descriptor, active)
        authority._append_atomic(
            descriptor,
            "terminal-failure.json",
            authority._failure_payload(
                descriptor,
                authority.Program012AuthorityError("synthetic"),
                active,
                source_commit,
            ),
        )
        terminal_key, terminal = authority._load_terminal_record(descriptor, active, source_commit)
        authority._publish_public_terminal(tmp_path, descriptor, terminal_key, terminal)
    finally:
        os.close(descriptor)

    monkeypatch.setattr(
        authority,
        "read_credentials",
        lambda *_args: pytest.fail("terminal reentry accessed credentials"),
    )
    with pytest.raises(authority.Program012AuthorityError, match="terminally sealed"):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport([]),
        )

    extra = tmp_path / "unexpected.txt"
    extra.write_text("unexpected\n", encoding="utf-8")
    with pytest.raises(authority.Program012AuthorityError, match="synchronized-main lineage"):
        authority._derive_control_validated_authority(tmp_path)
    extra.unlink()

    (tmp_path / authority.PUBLIC_TERMINAL_PATH).write_text("{}\n", encoding="utf-8")
    with pytest.raises(
        authority.Program012AuthorityError, match="public terminal artifact differs"
    ):
        authority._derive_control_validated_authority(tmp_path)


def test_finite_run_activates_claims_persists_and_seals_once(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    active, request = _configure_finite_execution(tmp_path, monkeypatch)
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
    public_path = tmp_path / authority.PUBLIC_TERMINAL_PATH
    public_result = json.loads(public_path.read_bytes())
    assert public_result["result_kind"] == "ADMISSION-PASS"
    assert public_result["authority_fingerprint"] == active["authority_fingerprint"]
    assert public_result["source_commit"] == active["control_lineage"]["runtime_source_commit"]
    assert public_result["aggregate_gate_results"]["structural_admission_passed"] is True
    assert public_result["dataset_manifest"]["dataset_identity"] == execution.dataset_identity
    assert "admitted_session_index_fingerprint" not in public_result["dataset_manifest"]
    terminal = _assert_public_terminal_has_no_private_commitments(public_result, root)
    assert (
        terminal["private_dataset_identity"]
        == json.loads((root / "dataset-manifest.json").read_bytes())["dataset_identity"]
    )
    assert terminal["private_dataset_identity"] != execution.dataset_identity
    assert execution.dataset_identity == fingerprint(
        {
            "operation_manifest": authority.OPERATION_MANIFEST,
            "authority_fingerprint": active["authority_fingerprint"],
            "source_commit": active["control_lineage"]["runtime_source_commit"],
            "response_manifest_sha256": execution.response_manifest_sha256,
            "canonical_raw_sha256": execution.canonical_raw_sha256,
            "action_ledger": authority._ACTION_LEDGER_MANIFEST,
        }
    )
    serialized_result = json.dumps(public_result, sort_keys=True)
    assert all(value not in serialized_result for value in _credentials().values())
    assert "opaque-page" not in serialized_result
    assert "IWM@" not in serialized_result
    public = json.dumps(execution.public_summary(), sort_keys=True)
    assert "opaque-page" not in public
    assert "IWM@" not in public
    with pytest.raises(authority.Program012AuthorityError, match="terminally sealed"):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport([]),
        )


def test_failed_admission_publishes_one_redacted_terminal_result(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _, request = _configure_finite_execution(tmp_path, monkeypatch, admission_passed=False)
    execution = authority._execute_mock_acquisition(
        tmp_path,
        environ=_credentials(),
        transport=authority.MockBarsTransport(
            [raw_contract.RawResponse(200, _body(request, 0, None))]
        ),
    )

    public = json.loads((tmp_path / authority.PUBLIC_TERMINAL_PATH).read_bytes())
    serialized = json.dumps(public, sort_keys=True)
    assert execution.admission_passed is False
    assert public["result_kind"] == "ADMISSION-FAILURE"
    assert public["status"] == "TERMINAL-FAIL-CONSUMED-NO-RETRY"
    assert public["aggregate_gate_results"] == {
        "structural_admission_passed": False,
        "failure_count": 1,
    }
    assert "global-count" not in serialized
    assert public["dataset_manifest"] is None
    assert public["public_dataset_manifest_present"] is False
    _assert_public_terminal_has_no_private_commitments(public, tmp_path / authority.PRIVATE_ROOT)
    assert all(value not in serialized for value in _credentials().values())
    assert "opaque-page" not in serialized
    assert "IWM@" not in serialized


def test_keyboard_interrupt_seals_and_reentry_does_not_reload_credentials(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _, request = _configure_finite_execution(tmp_path, monkeypatch)
    credential_reads = 0
    original_read = authority.read_credentials

    def read_credentials(environ: dict[str, str]) -> tuple[str, str]:
        nonlocal credential_reads
        credential_reads += 1
        return original_read(environ)

    monkeypatch.setattr(authority, "read_credentials", read_credentials)

    with pytest.raises(KeyboardInterrupt):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport(
                [raw_contract.RawResponse(200, _body(request, 0, None))]
            ),
            after_page=lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
        )

    public = json.loads((tmp_path / authority.PUBLIC_TERMINAL_PATH).read_bytes())
    assert public["result_kind"] == "RUNTIME-FAILURE"
    assert public["failure_class"] == "KeyboardInterrupt"
    _assert_public_terminal_has_no_private_commitments(public, tmp_path / authority.PRIVATE_ROOT)
    assert credential_reads == 1
    with pytest.raises(authority.Program012AuthorityError, match="terminally sealed"):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport([]),
        )
    assert credential_reads == 1


def test_terminal_file_must_be_complete_and_bound_before_sealing(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    active, _ = _configure_finite_execution(tmp_path, monkeypatch)
    descriptor = authority._open_private_root(tmp_path, create=False)
    try:
        _write_claim(descriptor, active)
        authority._append(descriptor, "terminal-failure.json", b"{\n")
    finally:
        os.close(descriptor)

    with pytest.raises(authority.Program012AuthorityError, match="terminal evidence"):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport([]),
        )

    assert not (tmp_path / authority.PUBLIC_TERMINAL_PATH).exists()


def test_recovery_rejects_re_fingerprinted_private_fields_before_publication(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _, request = _configure_finite_execution(tmp_path, monkeypatch)
    original_publish = authority._publish_public_terminal

    def interrupt_publication(*_args: Any) -> None:
        raise OSError("synthetic publication interruption")

    monkeypatch.setattr(authority, "_publish_public_terminal", interrupt_publication)
    with pytest.raises(authority.Program012PostClaimPersistenceError):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport(
                [raw_contract.RawResponse(200, _body(request, 0, None))]
            ),
        )
    monkeypatch.setattr(authority, "_publish_public_terminal", original_publish)

    receipt_path = tmp_path / authority.PRIVATE_ROOT / "acquisition-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["public_dataset_manifest"]["private_marker"] = "PRIVATE-RAW-MARKER"
    receipt.pop("terminal_fingerprint")
    receipt["terminal_fingerprint"] = fingerprint(receipt)
    receipt_path.write_text(canonical_json(receipt) + "\n", encoding="utf-8")

    with pytest.raises(authority.Program012AuthorityError, match="schema differs"):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport([]),
        )

    assert not (tmp_path / authority.PUBLIC_TERMINAL_PATH).exists()


def test_recovery_rederives_public_dataset_identity_before_publication(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _, request = _configure_finite_execution(tmp_path, monkeypatch)
    original_publish = authority._publish_public_terminal
    monkeypatch.setattr(
        authority,
        "_publish_public_terminal",
        lambda *_args: (_ for _ in ()).throw(OSError("synthetic publication interruption")),
    )
    with pytest.raises(authority.Program012PostClaimPersistenceError):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport(
                [raw_contract.RawResponse(200, _body(request, 0, None))]
            ),
        )
    monkeypatch.setattr(authority, "_publish_public_terminal", original_publish)

    receipt_path = tmp_path / authority.PRIVATE_ROOT / "acquisition-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["dataset_identity"] = "f" * 64
    receipt["public_dataset_manifest"]["dataset_identity"] = "f" * 64
    receipt.pop("terminal_fingerprint")
    receipt["terminal_fingerprint"] = fingerprint(receipt)
    receipt_path.write_text(canonical_json(receipt) + "\n", encoding="utf-8")

    with pytest.raises(authority.Program012AuthorityError, match="acquisition receipt differs"):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport([]),
        )
    assert not (tmp_path / authority.PUBLIC_TERMINAL_PATH).exists()


def test_recovery_rederives_private_gate_results_before_publication(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _, request = _configure_finite_execution(tmp_path, monkeypatch, admission_passed=False)
    original_publish = authority._publish_public_terminal
    monkeypatch.setattr(
        authority,
        "_publish_public_terminal",
        lambda *_args: (_ for _ in ()).throw(OSError("synthetic publication interruption")),
    )
    with pytest.raises(authority.Program012PostClaimPersistenceError):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport(
                [raw_contract.RawResponse(200, _body(request, 0, None))]
            ),
        )
    monkeypatch.setattr(authority, "_publish_public_terminal", original_publish)

    receipt_path = tmp_path / authority.PRIVATE_ROOT / "acquisition-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["aggregate_gate_results"]["failure_classes"] = ["calendar-year:2025"]
    receipt.pop("terminal_fingerprint")
    receipt["terminal_fingerprint"] = fingerprint(receipt)
    receipt_path.write_text(canonical_json(receipt) + "\n", encoding="utf-8")

    with pytest.raises(authority.Program012AuthorityError, match="acquisition receipt differs"):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport([]),
        )
    assert not (tmp_path / authority.PUBLIC_TERMINAL_PATH).exists()


def test_recovery_rejects_re_fingerprinted_acquisition_credential_count(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _, request = _configure_finite_execution(tmp_path, monkeypatch, retained_coordinate_count=2)
    original_publish = authority._publish_public_terminal
    monkeypatch.setattr(
        authority,
        "_publish_public_terminal",
        lambda *_args: (_ for _ in ()).throw(OSError("synthetic publication interruption")),
    )
    with pytest.raises(authority.Program012PostClaimPersistenceError):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport(
                [
                    raw_contract.RawResponse(200, _body(request, 0, "opaque-page-2")),
                    raw_contract.RawResponse(200, _body(request, 1, None)),
                ]
            ),
        )
    monkeypatch.setattr(authority, "_publish_public_terminal", original_publish)

    receipt_path = tmp_path / authority.PRIVATE_ROOT / "acquisition-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["credential_loads"] = 2
    receipt.pop("terminal_fingerprint")
    receipt["terminal_fingerprint"] = fingerprint(receipt)
    receipt_path.write_text(canonical_json(receipt) + "\n", encoding="utf-8")

    with pytest.raises(authority.Program012AuthorityError, match="acquisition receipt differs"):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport([]),
        )
    assert not (tmp_path / authority.PUBLIC_TERMINAL_PATH).exists()


def test_recovery_rejects_re_fingerprinted_failure_credential_count(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _, request = _configure_finite_execution(tmp_path, monkeypatch)
    original_publish = authority._publish_public_terminal
    monkeypatch.setattr(
        authority,
        "_publish_public_terminal",
        lambda *_args: (_ for _ in ()).throw(OSError("synthetic publication interruption")),
    )
    with pytest.raises(authority.Program012PostClaimPersistenceError):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport(
                [raw_contract.RawResponse(200, _body(request, 0, None))]
            ),
            after_page=lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
        )
    monkeypatch.setattr(authority, "_publish_public_terminal", original_publish)

    failure_path = tmp_path / authority.PRIVATE_ROOT / "terminal-failure.json"
    failure = json.loads(failure_path.read_bytes())
    failure["credential_loads"] = 0
    failure.pop("terminal_fingerprint")
    failure["terminal_fingerprint"] = fingerprint(failure)
    failure_path.write_text(canonical_json(failure) + "\n", encoding="utf-8")

    with pytest.raises(authority.Program012AuthorityError, match="failure evidence differs"):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport([]),
        )
    assert not (tmp_path / authority.PUBLIC_TERMINAL_PATH).exists()


def test_recovery_rejects_re_fingerprinted_failure_page_counts(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _, request = _configure_finite_execution(tmp_path, monkeypatch)
    body = _body(request, 0, None)
    original_publish = authority._publish_public_terminal
    monkeypatch.setattr(
        authority,
        "_publish_public_terminal",
        lambda *_args: (_ for _ in ()).throw(OSError("synthetic publication interruption")),
    )
    with pytest.raises(authority.Program012PostClaimPersistenceError):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport([raw_contract.RawResponse(200, body)]),
            after_page=lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
        )
    monkeypatch.setattr(authority, "_publish_public_terminal", original_publish)

    failure_path = tmp_path / authority.PRIVATE_ROOT / "terminal-failure.json"
    failure = json.loads(failure_path.read_bytes())
    assert (
        failure["request_count"],
        failure["response_count"],
        failure["response_bytes"],
        failure["sessions_with_completed_responses"],
    ) == (1, 1, len(body), 1)
    for field in (
        "request_count",
        "response_count",
        "response_bytes",
        "sessions_with_completed_responses",
    ):
        failure[field] = 0
    failure.pop("terminal_fingerprint")
    failure["terminal_fingerprint"] = fingerprint(failure)
    failure_path.write_text(canonical_json(failure) + "\n", encoding="utf-8")

    with pytest.raises(authority.Program012AuthorityError, match="failure counts differ"):
        authority._execute_mock_acquisition(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport([]),
        )
    assert not (tmp_path / authority.PUBLIC_TERMINAL_PATH).exists()


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
    _write_claim(root_descriptor, active)
    _write_credential_audit(root_descriptor, active, 1)
    _write_page(
        root_descriptor,
        active,
        request,
        1,
        None,
        _body(request, 0, "opaque-page-2"),
    )
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
            root_descriptor,
            authority.Program012AuthorityError("synthetic"),
            active,
            active["control_lineage"]["runtime_source_commit"],
        )
    )
    assert failure["credential_loads"] == 1
    assert transport.intents == ()
    os.close(root_descriptor)


def test_process_latch_blocks_a_second_credential_access(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    active = _active_authority()
    request = _request()
    descriptor = _root(tmp_path)
    credential_reads = 0
    original_read = authority.read_credentials

    def read_credentials(environ: dict[str, str]) -> tuple[str, str]:
        nonlocal credential_reads
        credential_reads += 1
        return original_read(environ)

    monkeypatch.setattr(authority, "read_credentials", read_credentials)
    intent = program_011.PageIntent(request.identity, 1, request.url(), None)
    first = authority._CredentialLoader(
        descriptor,
        active,
        active["control_lineage"]["runtime_source_commit"],
        _credentials(),
        authority.MockBarsTransport([raw_contract.RawResponse(200, b"{}")]),
        None,
    )
    second = authority._CredentialLoader(
        descriptor,
        active,
        active["control_lineage"]["runtime_source_commit"],
        _credentials(),
        authority.MockBarsTransport([]),
        None,
    )

    first.get(intent, lambda: None)
    with pytest.raises(authority.Program012AuthorityError, match="already consumed"):
        second.get(intent, lambda: None)

    assert credential_reads == 1
    assert authority._credential_load_count(descriptor) == 1
    os.close(descriptor)


def test_two_concurrent_recovery_processes_send_one_continuation(
    tmp_path: Path,
) -> None:
    active = _active_authority()
    request = _request()
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

    context = multiprocessing.get_context("spawn")
    start = context.Event()
    outputs = context.Queue()
    processes = [
        context.Process(
            target=_recover_process,
            args=(str(tmp_path), active, start, outputs),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=10)

    results = [outputs.get(timeout=2) for _ in processes]
    assert not any(process.is_alive() for process in processes)
    assert [process.exitcode for process in processes] == [0, 0]
    assert all(error is None and page_count == 2 for error, page_count, _ in results)
    assert sorted(token for _, _, tokens in results for token in tokens) == ["opaque-page-2"]
    descriptor = authority._open_private_root(tmp_path, create=False)
    try:
        assert authority._credential_load_count(descriptor) == 2
    finally:
        os.close(descriptor)
        outputs.close()
        outputs.join_thread()


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
