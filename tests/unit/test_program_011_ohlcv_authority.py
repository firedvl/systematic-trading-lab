from __future__ import annotations

import hashlib
import inspect
import json
import os
import subprocess
import sys
from collections import defaultdict
from contextlib import nullcontext
from pathlib import Path
from typing import Any
from urllib.request import ProxyHandler, Request

import pytest
from pytest import CaptureFixture, MonkeyPatch

import systematic_trading_lab.intraday_fed_policy_absorption_001_cli as dispatcher
import systematic_trading_lab.program_006_alpaca as credential_contract
import systematic_trading_lab.program_007_alpaca as raw_contract
import systematic_trading_lab.program_011_ohlcv as program_011
import systematic_trading_lab.program_011_ohlcv_authority as authority
from systematic_trading_lab.config import non_broker_subprocess_environment
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.standing_research_authority import AUTHORITY_FIELDS

_REPOSITORY = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _allow_historical_runtime_tests(monkeypatch: MonkeyPatch) -> None:
    reject_terminal_state = authority._reject_terminal_state

    def reject(repository: Path) -> None:
        if repository.resolve() == _REPOSITORY.resolve():
            reject_terminal_state(repository)

    monkeypatch.setattr(authority, "_reject_terminal_state", reject)


def _credentials() -> dict[str, str]:
    return {
        authority.CREDENTIAL_NAMES[0]: "synthetic-key-material",
        authority.CREDENTIAL_NAMES[1]: "synthetic-secret-material",
    }


def _git(repository: Path, *arguments: str) -> str:
    environment = non_broker_subprocess_environment()
    environment.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    return subprocess.run(
        ("git", "-C", str(repository), *arguments),
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    ).stdout.strip()


def _git_environment() -> dict[str, str]:
    environment = non_broker_subprocess_environment()
    environment.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    return environment


def _git_policy_repository(repository: Path) -> tuple[str, str]:
    repository.mkdir(parents=True, exist_ok=True)
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "Program 011 Test")
    _git(repository, "config", "user.email", "program-011@example.invalid")
    _git(repository, "commit", "--allow-empty", "-m", "policy source")
    commit = _git(repository, "rev-parse", "HEAD")
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    alternate = _git(repository, "commit-tree", tree, "-p", commit, "-m", "alternate")
    _git(repository, "update-ref", "refs/remotes/origin/main", commit)
    return commit, alternate


def _make_symbolic_main_refs(repository: Path, commit: str) -> None:
    for reference, target in (
        ("refs/heads/main", "refs/heads/pinned"),
        ("refs/remotes/origin/main", "refs/remotes/origin/pinned"),
    ):
        _git(repository, "update-ref", target, commit)
        _git(repository, "symbolic-ref", reference, target)


def _active_authority() -> dict[str, object]:
    return {
        "authority_id": authority.CHILD_AUTHORITY_ID,
        "authority_fingerprint": "a" * 64,
        "child_identity_fingerprint": "b" * 64,
        "control_lineage": {"synchronized_main_commit": "c" * 40},
    }


def _bar(timestamp: str) -> dict[str, object]:
    return {
        "t": timestamp,
        "o": 100,
        "h": 101,
        "l": 99,
        "c": 100.5,
        "v": 10,
        "n": 2,
        "vw": 100.25,
    }


def _complete_rows(
    request: program_011.SessionRequest,
) -> list[tuple[str, dict[str, object]]]:
    return [
        (symbol, _bar(timestamp.isoformat().replace("+00:00", "Z")))
        for symbol in program_011.SYMBOLS
        for timestamp in request.grid
    ]


def _body(rows: list[tuple[str, dict[str, object]]], token: str | None = None) -> bytes:
    bars: dict[str, list[dict[str, object]]] = defaultdict(list)
    for symbol, row in rows:
        bars[symbol].append(row)
    return json.dumps(
        {"bars": dict(reversed(bars.items())), "next_page_token": token},
        separators=(",", ":"),
    ).encode()


def _responses(*, missing: tuple[str, str] | None = None) -> list[raw_contract.RawResponse]:
    responses: list[raw_contract.RawResponse] = []
    for request in program_011.qualification_requests():
        rows = _complete_rows(request)
        if missing is not None:
            rows = [item for item in rows if (item[0], str(item[1]["t"])) != missing]
        chunks = [rows[index : index + 1_000] for index in range(0, len(rows), 1_000)]
        for index, chunk in enumerate(chunks, 1):
            token = (
                f"opaque-{request.session.isoformat()}-{index + 1}" if index < len(chunks) else None
            )
            responses.append(raw_contract.RawResponse(200, _body(chunk, token)))
    return responses


def _stub_active(tmp_path: Path, monkeypatch: MonkeyPatch) -> dict[str, object]:
    active = _active_authority()
    monkeypatch.setattr(authority, "derive_active_authority", lambda *_args, **_kwargs: active)
    monkeypatch.setattr(authority, "validate_operation_contract", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(authority, "_GitPolicySnapshot", lambda *_args: nullcontext())
    authority.activate_authority(tmp_path, environ=_credentials())
    return active


def test_operation_contract_revalidates_fresh_exposed_scope() -> None:
    proposal = authority.validate_operation_contract(_REPOSITORY)

    assert proposal["program_id"] == authority.PROGRAM_ID
    assert proposal["proposal_fingerprint"] == authority.OPERATION_MANIFEST["fingerprint"]


def test_terminal_success_revokes_before_credentials_or_private_state(
    monkeypatch: MonkeyPatch,
) -> None:
    credential_reads: list[bool] = []
    private_root_opens: list[bool] = []

    def credential_preflight(_environ: object) -> tuple[str, ...]:
        credential_reads.append(True)
        return ()

    monkeypatch.setattr(
        credential_contract,
        "credential_presence_preflight",
        credential_preflight,
    )
    monkeypatch.setattr(
        authority,
        "_open_private_root",
        lambda *_args, **_kwargs: private_root_opens.append(True),
    )

    for operation in (
        lambda: authority.credential_presence_preflight(_REPOSITORY, environ={}),
        lambda: authority.derive_active_authority(_REPOSITORY, environ={}),
        lambda: authority.activate_authority(_REPOSITORY, environ={}),
        lambda: authority.load_active_authority(_REPOSITORY, environ={}),
        lambda: authority.execute_qualification(_REPOSITORY, environ={}),
    ):
        with pytest.raises(authority.Program011AuthorityError, match="terminally revoked"):
            operation()

    assert credential_reads == []
    assert private_root_opens == []


def test_missing_terminal_success_rejects_before_credentials_or_private_state(
    monkeypatch: MonkeyPatch,
) -> None:
    credential_reads: list[bool] = []
    private_root_opens: list[bool] = []

    def credential_preflight(_environ: object) -> tuple[str, ...]:
        credential_reads.append(True)
        return ()

    monkeypatch.setattr(
        authority,
        "_TERMINAL_SUCCESS",
        {**authority._TERMINAL_SUCCESS, "path": "config/research/missing-terminal.json"},
    )
    monkeypatch.setattr(
        credential_contract,
        "credential_presence_preflight",
        credential_preflight,
    )
    monkeypatch.setattr(
        authority,
        "_open_private_root",
        lambda *_args, **_kwargs: private_root_opens.append(True),
    )

    for operation in (
        lambda: authority.credential_presence_preflight(_REPOSITORY, environ={}),
        lambda: authority.derive_active_authority(_REPOSITORY, environ={}),
        lambda: authority.activate_authority(_REPOSITORY, environ={}),
        lambda: authority.load_active_authority(_REPOSITORY, environ={}),
        lambda: authority.execute_qualification(_REPOSITORY, environ={}),
    ):
        with pytest.raises(authority.Program011AuthorityError, match="artifact is absent"):
            operation()

    assert credential_reads == []
    assert private_root_opens == []


def test_credential_preflight_cli_prints_only_pass_or_missing_names(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    control_checks: list[Path] = []

    def validate_controls(repository: Path) -> dict[str, object]:
        control_checks.append(repository)
        return _active_authority()

    monkeypatch.setattr(authority, "_derive_control_validated_authority", validate_controls)
    for name in authority.CREDENTIAL_NAMES:
        monkeypatch.delenv(name, raising=False)
    assert dispatcher.main(("data", "acquire", "program-011-ohlcv", "credential-preflight")) == 1
    missing = capsys.readouterr()
    assert missing.err == ""
    assert missing.out.splitlines() == [f"MISSING: {name}" for name in authority.CREDENTIAL_NAMES]

    values = _credentials()
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    assert dispatcher.main(("data", "acquire", "program-011-ohlcv", "credential-preflight")) == 0
    passed = capsys.readouterr()
    assert passed.err == ""
    assert passed.out == "PASS\n"
    assert all(value not in missing.out + passed.out for value in values.values())
    assert control_checks == [_REPOSITORY, _REPOSITORY]


def test_internal_child_derivation_enables_only_structural_qualification(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    child_authority = {key: key in authority._ENABLED_AUTHORITY for key in AUTHORITY_FIELDS}
    identity = {
        "child_authority_id": authority.CHILD_AUTHORITY_ID,
        "program_ordinal": authority.PROGRAM_ORDINAL,
        "program_id": authority.PROGRAM_ID,
        "operation_manifest": authority.OPERATION_MANIFEST,
        "runtime_entrypoint": ("src/systematic_trading_lab/program_011_ohlcv_authority.py"),
        "child_identity_fingerprint": "b" * 64,
        "authority": child_authority,
        "runtime_binding": {
            "source_files": [
                {"path": path.as_posix()}
                for path in (
                    authority.PROTECTED_CHRONOLOGY_PATH,
                    *authority.PROTECTED_CHRONOLOGY_SOURCE_PATHS,
                    *authority.PROTECTED_CHRONOLOGY_REGISTRATION_PATHS,
                )
            ]
        },
    }
    monkeypatch.setattr(authority, "derive_child_identity", lambda *_args: identity)
    monkeypatch.setattr(authority, "validate_operation_contract", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        authority,
        "_repository_preflight",
        lambda _repository, _identity: {"synchronized_main_commit": "c" * 40},
    )
    monkeypatch.setattr(authority, "_validate_protected_registration_set", lambda *_args: None)

    active = authority.derive_active_authority(tmp_path, environ=_credentials())

    assert active["external_authorization_root_required"] is False
    assert {key for key, value in active["authority"].items() if value} == {
        "provider_contact",
        "credential_access",
        "source_requests",
        "source_qualification",
    }
    assert active["authority"]["market_data_acquisition"] is False
    assert active["authority"]["real_dataset_admission"] is False
    assert active["authority"]["strategy_execution"] is False
    assert active["authority"]["controlled_evaluation"] is False
    assert active["authority"]["protected_holdout"] is False
    assert active["authority"]["paper_execution"] is False
    assert active["authority"]["broker_writes"] is False
    assert active["authority"]["live_execution"] is False


def test_controls_validate_before_missing_credentials_and_private_state(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    calls: list[str] = []
    private_root_opens: list[bool] = []

    def validate_controls(_repository: Path) -> dict[str, object]:
        calls.append("controls")
        return _active_authority()

    def credential_preflight(_environ: object) -> tuple[str, ...]:
        calls.append("credentials")
        return authority.CREDENTIAL_NAMES

    def open_private_root(*_args: object, **_kwargs: object) -> int:
        private_root_opens.append(True)
        return -1

    monkeypatch.setattr(
        authority,
        "_derive_control_validated_authority",
        validate_controls,
    )
    monkeypatch.setattr(
        credential_contract,
        "credential_presence_preflight",
        credential_preflight,
    )
    monkeypatch.setattr(authority, "_open_private_root", open_private_root)

    with pytest.raises(authority.Program011AuthorityError, match="credentials missing"):
        authority._execute_mock_qualification(
            tmp_path,
            environ={},
            transport=authority.MockBarsTransport([raw_contract.RawResponse(200, b"{}")]),
        )

    assert calls == ["controls", "credentials"]
    assert private_root_opens == []
    assert not (tmp_path / authority.PRIVATE_ROOT).exists()


@pytest.mark.parametrize(
    "control_failure",
    (
        "reviewed child identity differs",
        "child authority review is absent",
        "reviewed synchronized-main lineage differs",
        "fresh exposed chronology differs",
    ),
)
@pytest.mark.parametrize("entrypoint", ("execution", "credential-preflight"))
def test_invalid_controls_reject_before_credentials_or_private_state(
    control_failure: str,
    entrypoint: str,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []
    identity = {
        "child_authority_id": authority.CHILD_AUTHORITY_ID,
        "program_ordinal": authority.PROGRAM_ORDINAL,
        "program_id": authority.PROGRAM_ID,
        "operation_manifest": authority.OPERATION_MANIFEST,
        "runtime_entrypoint": "src/systematic_trading_lab/program_011_ohlcv_authority.py",
        "child_identity_fingerprint": "b" * 64,
        "authority": {key: key in authority._ENABLED_AUTHORITY for key in AUTHORITY_FIELDS},
        "runtime_binding": {
            "source_files": [
                {"path": path.as_posix()}
                for path in (
                    authority.PROTECTED_CHRONOLOGY_PATH,
                    *authority.PROTECTED_CHRONOLOGY_SOURCE_PATHS,
                    *authority.PROTECTED_CHRONOLOGY_REGISTRATION_PATHS,
                )
            ]
        },
    }

    def derive_identity(*_args: object) -> dict[str, object]:
        calls.append("controls")
        if control_failure == "child authority review is absent":
            raise authority.Program011AuthorityError(control_failure)
        if control_failure == "reviewed child identity differs":
            return {**identity, "child_authority_id": "invalid-child"}
        return identity

    def repository_preflight(*_args: object) -> dict[str, str]:
        if control_failure == "reviewed synchronized-main lineage differs":
            raise authority.Program011AuthorityError(control_failure)
        return {"synchronized_main_commit": "c" * 40}

    def validate_contract(*_args: object, **_kwargs: object) -> dict[str, object]:
        if control_failure == "fresh exposed chronology differs":
            raise authority.Program011AuthorityError(control_failure)
        return {}

    def credential_preflight(_environ: object) -> tuple[str, ...]:
        calls.append("credentials")
        return ()

    def open_private_root(*_args: object, **_kwargs: object) -> int:
        calls.append("private-state")
        return -1

    monkeypatch.setattr(authority, "derive_child_identity", derive_identity)
    monkeypatch.setattr(authority, "_repository_preflight", repository_preflight)
    monkeypatch.setattr(authority, "_validate_protected_registration_set", lambda *_args: None)
    monkeypatch.setattr(authority, "validate_operation_contract", validate_contract)
    monkeypatch.setattr(authority, "_reject_terminal_state", lambda _repository: None)
    monkeypatch.setattr(
        credential_contract,
        "credential_presence_preflight",
        credential_preflight,
    )
    monkeypatch.setattr(authority, "_open_private_root", open_private_root)

    if entrypoint == "execution":
        with pytest.raises(authority.Program011AuthorityError, match=control_failure):
            authority._execute_mock_qualification(
                tmp_path,
                environ=_credentials(),
                transport=authority.MockBarsTransport([raw_contract.RawResponse(200, b"{}")]),
            )
    else:
        assert (
            dispatcher.main(("data", "acquire", "program-011-ohlcv", "credential-preflight")) == 2
        )

    assert calls == ["controls"]
    assert not (tmp_path / authority.PRIVATE_ROOT).exists()


def test_activation_is_internal_and_does_not_consume_claim(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    active = _active_authority()
    monkeypatch.setattr(authority, "derive_active_authority", lambda *_args, **_kwargs: active)
    monkeypatch.setattr(authority, "_GitPolicySnapshot", lambda *_args: nullcontext())

    assert authority.activate_authority(tmp_path, environ=_credentials()) == active
    root = tmp_path / authority.PRIVATE_ROOT
    assert (root / "active-authority.json").exists()
    assert not (root / "claim.json").exists()
    assert tuple(inspect.signature(authority.activate_authority).parameters) == (
        "repository",
        "environ",
    )
    with pytest.raises(authority.Program011AuthorityError, match="state already exists"):
        authority.activate_authority(tmp_path, environ=_credentials())


def test_activation_ref_drift_rejects_before_active_record(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    active = _active_authority()
    monkeypatch.setattr(authority, "derive_active_authority", lambda *_args, **_kwargs: active)

    class RefDrift:
        def __enter__(self) -> None:
            raise authority.Program011AuthorityError("synthetic ref drift")

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(authority, "_GitPolicySnapshot", lambda *_args: RefDrift())

    with pytest.raises(authority.Program011AuthorityError, match="synthetic ref drift"):
        authority.activate_authority(tmp_path, environ=_credentials())

    assert not (tmp_path / authority.PRIVATE_ROOT / "active-authority.json").exists()


def test_git_policy_snapshot_blocks_main_and_origin_ref_updates(tmp_path: Path) -> None:
    commit, alternate = _git_policy_repository(tmp_path)
    environment = _git_environment()

    with authority._GitPolicySnapshot(tmp_path, commit):
        for reference in ("refs/heads/main", "refs/remotes/origin/main"):
            result = subprocess.run(
                ("git", "-C", str(tmp_path), "update-ref", reference, alternate, commit),
                check=False,
                capture_output=True,
                env=environment,
            )
            assert result.returncode != 0
            assert _git(tmp_path, "rev-parse", reference) == commit

    for reference in ("refs/heads/main", "refs/remotes/origin/main"):
        _git(tmp_path, "update-ref", reference, alternate, commit)
        assert _git(tmp_path, "rev-parse", reference) == alternate


def test_git_policy_snapshot_has_no_independent_lock_owner(tmp_path: Path) -> None:
    commit, alternate = _git_policy_repository(tmp_path)
    environment = _git_environment()
    snapshot = authority._GitPolicySnapshot(tmp_path, commit)
    snapshot.__enter__()
    try:
        helper = getattr(snapshot, "_process", None)
        if helper is not None:
            helper.terminate()
            helper.wait()
        for reference in ("refs/heads/main", "refs/remotes/origin/main"):
            result = subprocess.run(
                ("git", "-C", str(tmp_path), "update-ref", reference, alternate, commit),
                check=False,
                capture_output=True,
                env=environment,
            )
            assert result.returncode != 0
            assert _git(tmp_path, "rev-parse", reference) == commit
    finally:
        snapshot.__exit__(None)


def test_git_policy_snapshot_supports_packed_files_refs(tmp_path: Path) -> None:
    commit, alternate = _git_policy_repository(tmp_path)
    _git(tmp_path, "pack-refs", "--all", "--prune")

    with authority._GitPolicySnapshot(tmp_path, commit):
        for reference in ("refs/heads/main", "refs/remotes/origin/main"):
            result = subprocess.run(
                ("git", "-C", str(tmp_path), "update-ref", reference, alternate, commit),
                check=False,
                capture_output=True,
                env=_git_environment(),
            )
            assert result.returncode != 0
            assert _git(tmp_path, "rev-parse", reference) == commit


def test_symbolic_main_refs_reject_activation_and_execution(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    activation_repository = tmp_path / "activation"
    activation_commit, _ = _git_policy_repository(activation_repository)
    execution_repository = tmp_path / "execution"
    execution_commit, _ = _git_policy_repository(execution_repository)
    active = {
        activation_repository.resolve(): {
            **_active_authority(),
            "control_lineage": {"synchronized_main_commit": activation_commit},
        },
        execution_repository.resolve(): {
            **_active_authority(),
            "control_lineage": {"synchronized_main_commit": execution_commit},
        },
    }
    monkeypatch.setattr(
        authority,
        "derive_active_authority",
        lambda repository, **_kwargs: active[repository.resolve()],
    )
    monkeypatch.setattr(authority, "validate_operation_contract", lambda *_args, **_kwargs: {})

    _make_symbolic_main_refs(activation_repository, activation_commit)
    with pytest.raises(authority.Program011AuthorityError, match="snapshot lock failed"):
        authority.activate_authority(activation_repository, environ=_credentials())
    assert not (activation_repository / authority.PRIVATE_ROOT / "active-authority.json").exists()

    authority.activate_authority(execution_repository, environ=_credentials())
    _make_symbolic_main_refs(execution_repository, execution_commit)
    transport = authority.MockBarsTransport([raw_contract.RawResponse(200, b"{}")])
    with pytest.raises(authority.Program011AuthorityError, match="snapshot lock failed"):
        authority._execute_mock_qualification(
            execution_repository,
            environ=_credentials(),
            transport=transport,
        )
    root = execution_repository / authority.PRIVATE_ROOT
    assert not (root / "claim.json").exists()
    assert not (root / "terminal-failure.json").exists()
    assert transport.intents == ()


def test_git_policy_snapshot_recovers_owned_locks_after_abrupt_exit(tmp_path: Path) -> None:
    commit, alternate = _git_policy_repository(tmp_path)
    code = (
        "from pathlib import Path; import os,sys; "
        "from systematic_trading_lab.program_011_ohlcv_authority "
        "import _GitPolicySnapshot; "
        "_GitPolicySnapshot(Path(sys.argv[1]), sys.argv[2]).__enter__(); os._exit(0)"
    )
    subprocess.run(
        (sys.executable, "-c", code, str(tmp_path), commit),
        check=True,
        env=_git_environment(),
    )
    lock_paths = tuple(
        Path(
            f"{_git(tmp_path, 'rev-parse', '--path-format=absolute', '--git-path', reference)}.lock"
        )
        for reference in ("refs/heads/main", "refs/remotes/origin/main")
    )
    assert all(path.is_file() for path in lock_paths)

    with authority._GitPolicySnapshot(tmp_path, commit):
        for reference in ("refs/heads/main", "refs/remotes/origin/main"):
            result = subprocess.run(
                ("git", "-C", str(tmp_path), "update-ref", reference, alternate, commit),
                check=False,
                capture_output=True,
                env=_git_environment(),
            )
            assert result.returncode != 0
    assert not any(path.exists() for path in lock_paths)


def test_git_policy_snapshot_preserves_unowned_git_lock(tmp_path: Path) -> None:
    commit, _ = _git_policy_repository(tmp_path)
    reference_path = _git(
        tmp_path, "rev-parse", "--path-format=absolute", "--git-path", "refs/heads/main"
    )
    lock_path = Path(f"{reference_path}.lock")
    content = (commit + "\n").encode()
    lock_path.write_bytes(content)
    lock_path.chmod(0o600)

    with (
        pytest.raises(authority.Program011AuthorityError, match="snapshot lock failed"),
        authority._GitPolicySnapshot(tmp_path, commit),
    ):
        pass

    assert lock_path.read_bytes() == content


def test_fixed_get_endpoint_rejects_mutation() -> None:
    session = program_011.qualification_requests()[0]
    intent = program_011.PageIntent(session.identity, 1, session.url(), None)
    authority._validate_http_request(Request(intent.url, method="GET"), intent)

    for url in (
        intent.url.replace("/v2/stocks/bars", "/v1/corporate-actions"),
        intent.url.replace("adjustment=raw", "adjustment=split"),
        intent.url.replace("feed=sip", "feed=iex"),
        intent.url + "&symbols=QQQ",
    ):
        mutated = program_011.PageIntent(session.identity, 1, url, None)
        with pytest.raises(authority.Program011AuthorityError, match="endpoint or query differs"):
            authority._validate_http_request(Request(url, method="GET"), mutated)


def test_client_ignores_environment_proxies(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9876")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9876")
    proxy_settings: list[dict[str, str]] = []

    def configured_proxy_handler(proxies: dict[str, str]) -> object:
        proxy_settings.append(proxies)
        return ProxyHandler(proxies)

    monkeypatch.setattr(authority, "ProxyHandler", configured_proxy_handler)

    authority._AlpacaBarsClient("synthetic-key", "synthetic-secret", pace=lambda: None)

    assert proxy_settings == [{}]


def test_new_protected_session_rejects_before_credentials_or_private_state(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    proposal = authority.validate_operation_contract(_REPOSITORY)
    predecessor = authority._load_bound_artifact(
        _REPOSITORY, authority._PROGRAM_007_PROPOSAL, "proposal_fingerprint"
    )
    program_009_terminal = authority._load_bound_artifact(
        _REPOSITORY,
        proposal["bindings"]["program_009_terminal_failure"],
        "failure_fingerprint",
    )
    program_010_terminal = authority._load_bound_artifact(
        _REPOSITORY,
        proposal["bindings"]["program_010_terminal_failure"],
        "failure_fingerprint",
    )
    credential_checks: list[bool] = []
    private_root_opens: list[bool] = []

    monkeypatch.setattr(
        authority,
        "derive_child_identity",
        lambda *_args: {
            "child_authority_id": authority.CHILD_AUTHORITY_ID,
            "program_ordinal": authority.PROGRAM_ORDINAL,
            "program_id": authority.PROGRAM_ID,
            "operation_manifest": authority.OPERATION_MANIFEST,
            "runtime_entrypoint": "src/systematic_trading_lab/program_011_ohlcv_authority.py",
            "child_identity_fingerprint": "b" * 64,
            "authority": {key: key in authority._ENABLED_AUTHORITY for key in AUTHORITY_FIELDS},
            "runtime_binding": {
                "source_files": [
                    {"path": path.as_posix()}
                    for path in (
                        authority.PROTECTED_CHRONOLOGY_PATH,
                        *authority.PROTECTED_CHRONOLOGY_SOURCE_PATHS,
                        *authority.PROTECTED_CHRONOLOGY_REGISTRATION_PATHS,
                    )
                ]
            },
        },
    )
    monkeypatch.setattr(
        authority,
        "_current_protected_ranges",
        lambda _repository, **_kwargs: (
            (program_011.SELECTED_SESSIONS[0], program_011.SELECTED_SESSIONS[0]),
        ),
    )
    monkeypatch.setattr(
        authority,
        "_repository_preflight",
        lambda *_args: {"synchronized_main_commit": "c" * 40},
    )
    monkeypatch.setattr(authority, "_validate_protected_registration_set", lambda *_args: None)
    monkeypatch.setattr(
        authority,
        "_require_credentials_present",
        lambda _environ: credential_checks.append(True),
    )
    monkeypatch.setattr(
        authority,
        "_open_private_root",
        lambda *_args, **_kwargs: private_root_opens.append(True),
    )
    monkeypatch.setattr(
        authority,
        "validate_operation_contract",
        lambda _repository, **_kwargs: authority._validate_chronology(
            _REPOSITORY,
            proposal,
            predecessor,
            program_009_terminal,
            program_010_terminal,
        ),
    )

    with pytest.raises(
        authority.Program011AuthorityError, match="fresh exposed chronology differs"
    ):
        authority.activate_authority(tmp_path, environ=_credentials())

    assert credential_checks == []
    assert private_root_opens == []
    assert not (tmp_path / authority.PRIVATE_ROOT).exists()


def test_unreviewed_repository_artifact_rejects_before_credentials_or_private_state(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Program 011 Test")
    _git(tmp_path, "config", "user.email", "program-011@example.invalid")
    (tmp_path / "source.txt").write_text("reviewed\n", encoding="utf-8")
    _git(tmp_path, "add", "source.txt")
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
        "runtime_entrypoint": "src/systematic_trading_lab/program_011_ohlcv_authority.py",
        "child_identity_fingerprint": "b" * 64,
        "authority": {key: key in authority._ENABLED_AUTHORITY for key in AUTHORITY_FIELDS},
        "runtime_binding": {
            "source_commit": source_commit,
            "source_tree": source_tree,
            "source_files": [
                {"path": path.as_posix()}
                for path in (
                    authority.PROTECTED_CHRONOLOGY_PATH,
                    *authority.PROTECTED_CHRONOLOGY_SOURCE_PATHS,
                    *authority.PROTECTED_CHRONOLOGY_REGISTRATION_PATHS,
                )
            ],
        },
    }
    assert authority._repository_preflight(tmp_path, identity)["synchronized_main_commit"] == head

    extra = tmp_path / "config/research/future-sealed-range-v1.json"
    extra.write_text("{}\n", encoding="utf-8")
    _git(tmp_path, "add", extra.relative_to(tmp_path).as_posix())
    _git(tmp_path, "commit", "-m", "add unreviewed protected artifact")
    _git(
        tmp_path,
        "update-ref",
        "refs/remotes/origin/main",
        _git(tmp_path, "rev-parse", "HEAD"),
    )
    credential_checks: list[bool] = []
    private_root_opens: list[bool] = []
    monkeypatch.setattr(authority, "derive_child_identity", lambda *_args: identity)
    monkeypatch.setattr(authority, "validate_operation_contract", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(authority, "_validate_protected_registration_set", lambda *_args: None)
    monkeypatch.setattr(
        authority,
        "_require_credentials_present",
        lambda _environ: credential_checks.append(True),
    )
    monkeypatch.setattr(
        authority,
        "_open_private_root",
        lambda *_args, **_kwargs: private_root_opens.append(True),
    )

    with pytest.raises(
        authority.Program011AuthorityError, match="reviewed synchronized-main lineage differs"
    ):
        authority.activate_authority(tmp_path, environ=_credentials())

    assert credential_checks == []
    assert private_root_opens == []
    assert not (tmp_path / authority.PRIVATE_ROOT).exists()


def test_omitted_protected_registration_rejects_before_credentials_or_private_state(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Program 011 Test")
    _git(tmp_path, "config", "user.email", "program-011@example.invalid")
    for path in (
        authority.PROTECTED_CHRONOLOGY_PATH,
        *authority.PROTECTED_CHRONOLOGY_REGISTRATION_PATHS,
    ):
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((_REPOSITORY / path).read_bytes())
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "canonical protected registry")
    authority._validate_protected_registration_set(tmp_path, _git(tmp_path, "rev-parse", "HEAD"))

    extra_path = Path(
        "config/research/protected-chronology-registrations/future-sealed-range-v1.json"
    )
    unsigned = {
        "schema_version": authority._PROTECTED_REGISTRATION_SCHEMA,
        "registration_id": "future-sealed-range-2026-08-30-v1",
        "status": authority._PROTECTED_REGISTRATION_STATUS,
        "ranges": [
            {
                "id": "future-sealed-2021-05-25",
                "start": "2021-05-25",
                "end": "2021-05-25",
            }
        ],
    }
    (tmp_path / extra_path).write_text(
        json.dumps(
            {**unsigned, "registration_fingerprint": fingerprint(unsigned)},
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _git(tmp_path, "add", extra_path.as_posix())
    _git(tmp_path, "commit", "-m", "reviewed source with omitted registration")
    source_commit = _git(tmp_path, "rev-parse", "HEAD")
    source_tree = _git(tmp_path, "rev-parse", "HEAD^{tree}")
    for path in (authority.CHILD_AUTHORITY_PATH, authority.CHILD_REVIEW_PATH):
        destination = tmp_path / path
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
        "runtime_entrypoint": "src/systematic_trading_lab/program_011_ohlcv_authority.py",
        "child_identity_fingerprint": "b" * 64,
        "authority": {key: key in authority._ENABLED_AUTHORITY for key in AUTHORITY_FIELDS},
        "runtime_binding": {
            "source_commit": source_commit,
            "source_tree": source_tree,
            "source_files": [
                {"path": path.as_posix()}
                for path in (
                    authority.PROTECTED_CHRONOLOGY_PATH,
                    *authority.PROTECTED_CHRONOLOGY_SOURCE_PATHS,
                    *authority.PROTECTED_CHRONOLOGY_REGISTRATION_PATHS,
                )
            ],
        },
    }
    credential_checks: list[bool] = []
    private_root_opens: list[bool] = []
    monkeypatch.setattr(authority, "derive_child_identity", lambda *_args: identity)
    monkeypatch.setattr(authority, "validate_operation_contract", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        authority,
        "_require_credentials_present",
        lambda _environ: credential_checks.append(True),
    )
    monkeypatch.setattr(
        authority,
        "_open_private_root",
        lambda *_args, **_kwargs: private_root_opens.append(True),
    )

    with pytest.raises(authority.Program011AuthorityError, match="registration set differs"):
        authority.activate_authority(tmp_path, environ=_credentials())

    assert credential_checks == []
    assert private_root_opens == []
    assert not (tmp_path / authority.PRIVATE_ROOT).exists()


def test_execution_revalidates_authority_before_claim_or_transport(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    active = _stub_active(tmp_path, monkeypatch)
    calls = 0

    def derive(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls < 3:
            return active
        return {**active, "authority_fingerprint": "d" * 64}

    monkeypatch.setattr(authority, "derive_active_authority", derive)
    transport = authority.MockBarsTransport([raw_contract.RawResponse(200, b"{}")])

    with pytest.raises(authority.Program011AuthorityError, match="transport boundary"):
        authority._execute_mock_qualification(
            tmp_path,
            environ=_credentials(),
            transport=transport,
        )

    root = tmp_path / authority.PRIVATE_ROOT
    assert not (root / "claim.json").exists()
    assert not (root / "terminal-failure.json").exists()
    assert transport.intents == ()


def test_claim_raw_first_private_missingness_and_one_use(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _stub_active(tmp_path, monkeypatch)
    missing = ("MDY", "2021-04-28T13:30:00Z")
    transport = authority.MockBarsTransport(_responses(missing=missing))
    root = tmp_path / authority.PRIVATE_ROOT
    original_get = authority.MockBarsTransport.get
    original_parse = raw_contract.parse_raw_page
    original_read = authority.read_credentials
    credential_loads = 0

    def read(*args: Any, **kwargs: Any) -> tuple[str, str]:
        nonlocal credential_loads
        credential_loads += 1
        return original_read(*args, **kwargs)

    def get(
        self: authority.MockBarsTransport, intent: program_011.PageIntent
    ) -> raw_contract.RawResponse:
        session = next(
            request.session
            for request in program_011.qualification_requests()
            if request.identity == intent.request_identity
        )
        prefix = f"session-{session}-{intent.page_index:02d}"
        assert (root / "claim.json").exists()
        assert (root / f"{prefix}.intent.json").exists()
        assert not (root / f"{prefix}.body").exists()
        return original_get(self, intent)

    def parse(
        body: bytes,
        chain: raw_contract.RequestChain,
        *,
        preserve_received_order: bool = False,
    ) -> tuple[tuple[raw_contract.RawBar, ...], str | None]:
        intent = transport.intents[-1]
        session = next(
            request.session
            for request in program_011.qualification_requests()
            if request.identity == intent.request_identity
        )
        prefix = f"session-{session}-{intent.page_index:02d}"
        assert (root / f"{prefix}.body").read_bytes() == body
        receipt = json.loads((root / f"{prefix}.receipt.json").read_bytes())
        assert receipt["response_sha256"] == hashlib.sha256(body).hexdigest()
        return original_parse(body, chain, preserve_received_order=preserve_received_order)

    monkeypatch.setattr(authority, "read_credentials", read)
    monkeypatch.setattr(authority.MockBarsTransport, "get", get)
    monkeypatch.setattr(raw_contract, "parse_raw_page", parse)

    execution = authority._execute_mock_qualification(
        tmp_path, environ=_credentials(), transport=transport
    )

    assert execution.result.status == "PASS-WITH-SOURCE-MISSING"
    assert execution.request_count == execution.response_count == len(transport.intents) == 9
    assert credential_loads == 1
    private_missing = json.loads((root / "missing-coordinates.json").read_bytes())
    assert private_missing["sessions"][0]["source_missing_coordinates"] == [
        "MDY@2021-04-28T13:30:00Z"
    ]
    public = json.dumps(execution.public_summary(), sort_keys=True)
    assert "MDY@2021-04-28T13:30:00Z" not in public
    assert "opaque-" not in public
    assert execution.missing_inventory_sha256 not in public
    assert "missing_inventory_sha256" not in public
    assert '"open"' not in public
    assert '"close"' not in public
    assert '"volume"' not in public
    assert execution.public_summary()["source_missing_coordinate_count"] == 1
    assert (
        json.loads((root / "qualification-receipt.json").read_bytes())["dataset_admitted"] is False
    )

    with pytest.raises(authority.Program011AuthorityError, match="state already exists"):
        authority._execute_mock_qualification(tmp_path, environ=_credentials(), transport=transport)
    assert len(transport.intents) == 9


@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_post_claim_http_failure_is_terminal_and_retains_bytes(
    status: int, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _stub_active(tmp_path, monkeypatch)
    body = b'{"error":"bounded"}'

    with pytest.raises(authority.Program011AuthorityError, match=f"HTTP {status}"):
        authority._execute_mock_qualification(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport([raw_contract.RawResponse(status, body)]),
        )

    root = tmp_path / authority.PRIVATE_ROOT
    prefix = "session-2021-04-28-01"
    assert (root / f"{prefix}.body").read_bytes() == body
    assert (root / f"{prefix}.receipt.json").exists()
    assert (root / "claim.json").exists()
    assert json.loads((root / "terminal-failure.json").read_bytes())["status"] == (
        "FAIL-CONSUMED-NO-RETRY"
    )


def test_oversized_response_is_retained_before_failure(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _stub_active(tmp_path, monkeypatch)
    body = b"x" * (program_011.MAXIMUM_RESPONSE_PAGE_BYTES + 1)

    with pytest.raises(authority.Program011AuthorityError, match="8 MiB page ceiling"):
        authority._execute_mock_qualification(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport([raw_contract.RawResponse(200, body)]),
        )

    root = tmp_path / authority.PRIVATE_ROOT
    assert (root / "session-2021-04-28-01.body").read_bytes() == body
    assert (root / "terminal-failure.json").exists()


def test_post_claim_terminal_persistence_failure_uses_claim_fallback(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _stub_active(tmp_path, monkeypatch)
    original = authority._append_persistent_evidence

    def append(root_descriptor: int, key: str, payload: bytes) -> None:
        if key == "terminal-failure.json":
            raise OSError("simulated terminal persistence failure")
        original(root_descriptor, key, payload)

    monkeypatch.setattr(authority, "_append_persistent_evidence", append)

    with pytest.raises(
        authority.Program011PostClaimPersistenceError,
        match="claim fallback seals FAIL-CONSUMED-NO-RETRY",
    ):
        authority._execute_mock_qualification(
            tmp_path,
            environ=_credentials(),
            transport=authority.MockBarsTransport(
                [raw_contract.RawResponse(401, b'{"error":"bounded"}')]
            ),
        )

    claim = json.loads((tmp_path / authority.PRIVATE_ROOT / "claim.json").read_bytes())
    assert claim["terminal_fallback"]["status"] == "FAIL-CONSUMED-NO-RETRY"
    assert claim["terminal_fallback"]["retry_allowed"] is False
