from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.request import Request

import pytest
from pytest import CaptureFixture, MonkeyPatch

import systematic_trading_lab.intraday_fed_policy_absorption_001_cli as dispatcher
import systematic_trading_lab.program_005_alpaca as frozen
import systematic_trading_lab.program_006_alpaca as program_006
from systematic_trading_lab.fingerprints import canonical_json, fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_CHAIN = frozen.build_request_plan(frozen.load_contract(_REPOSITORY), "qualification")[0]
_AUTHORITY = {
    "authority_id": "synthetic-program-006-authority",
    "authority_fingerprint": "a" * 64,
    "bindings": {},
    "implementation_binding": {
        "source_commit": "b" * 40,
        "implementation_root": "c" * 64,
    },
}
_PREFLIGHT = {
    "request_plan_fingerprint": "d" * 64,
    "maximum_http_responses_to_acquire": 60,
    "maximum_downloaded_bytes": 64 * 1024**2,
}


def _credentials() -> dict[str, str]:
    return {
        program_006._CREDENTIAL_NAMES[0]: "synthetic-key-material",
        program_006._CREDENTIAL_NAMES[1]: "synthetic-secret-material",
    }


def _stub_execution(
    monkeypatch: MonkeyPatch,
    *,
    load_authority: Callable[..., Mapping[str, Any]] | None = None,
) -> None:
    monkeypatch.setattr(frozen, "load_contract", lambda _: object())
    monkeypatch.setattr(frozen, "build_request_plan", lambda *_: (_CHAIN,))
    monkeypatch.setattr(program_006, "scientific_preflight", lambda _: _PREFLIGHT)
    monkeypatch.setattr(
        program_006,
        "load_active_authority",
        load_authority or (lambda *_: _AUTHORITY),
    )

    def acquire(
        chain: frozen.RequestChain,
        _chain_root: Path,
        client: frozen.AlpacaBarsClient,
        budget: frozen.AcquisitionBudget,
        *,
        source_commit: str,
    ) -> None:
        assert source_commit == "b" * 40
        budget.add(client.get(chain).body)

    monkeypatch.setattr(frozen, "acquire_chain", acquire)
    monkeypatch.setattr(frozen, "freeze_dataset", lambda *_args, **_kwargs: {"dataset_id": "x"})


def _private_root(repository: Path) -> Path:
    return repository / ".trading-lab/program-006-free-alpaca"


def _success_page(request: Request) -> frozen.HttpPage:
    return frozen.HttpPage(200, b"{}", request.full_url)


def test_credentials_absent_before_authorization_create_no_state(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(program_006, "derive_active_authority", lambda _: _AUTHORITY)
    with pytest.raises(program_006.Program006Error, match="credentials missing"):
        program_006.activate_authority(tmp_path, "a" * 64, environ={})
    assert not _private_root(tmp_path).exists()


def test_credentials_present_still_require_exact_external_root(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(program_006, "derive_active_authority", lambda _: _AUTHORITY)
    with pytest.raises(program_006.Program006Error, match="external authorization root differs"):
        program_006.activate_authority(tmp_path, "f" * 64, environ=_credentials())
    assert not _private_root(tmp_path).exists()
    authority = program_006.activate_authority(tmp_path, "a" * 64, environ=_credentials())
    assert authority == _AUTHORITY
    assert program_006._active_authority_path(tmp_path).exists()


def test_credentials_disappear_before_locked_revalidation_without_consumption(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    values = _credentials()
    calls = 0

    def load(*_arguments: Any) -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            values.clear()
        return _AUTHORITY

    _stub_execution(monkeypatch, load_authority=load)
    with pytest.raises(program_006.Program006Error, match="credentials missing"):
        program_006.execute_qualification(
            tmp_path,
            _private_root(tmp_path),
            "a" * 64,
            environ=values,
            transport=lambda _: (_ for _ in ()).throw(AssertionError("transported")),
        )
    scope = _private_root(tmp_path) / "qualification"
    assert not (scope / "claim.json").exists()
    assert not (scope / "terminal-qualification-failure.json").exists()


def test_git_or_binding_drift_under_lock_stops_before_credentials_and_claim(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    calls = 0

    def load(*_arguments: Any) -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise program_006.Program006Error("synthetic Git drift")
        return _AUTHORITY

    _stub_execution(monkeypatch, load_authority=load)
    with pytest.raises(program_006.Program006Error, match="Git drift"):
        program_006.execute_qualification(
            tmp_path,
            _private_root(tmp_path),
            "a" * 64,
            environ=_credentials(),
            transport=lambda _: (_ for _ in ()).throw(AssertionError("transported")),
        )
    assert not (_private_root(tmp_path) / "qualification/claim.json").exists()


def test_active_authority_rejects_root_mismatch(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(program_006, "derive_active_authority", lambda _: _AUTHORITY)
    path = program_006._active_authority_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(canonical_json(_AUTHORITY) + "\n", encoding="utf-8", newline="\n")
    with pytest.raises(program_006.Program006Error, match="not exact or externally authorized"):
        program_006.load_active_authority(tmp_path, "f" * 64, "d" * 64)


def test_valid_state_consumes_immediately_before_first_transport_and_rejects_rerun(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _stub_execution(monkeypatch)
    claim = _private_root(tmp_path) / "qualification/claim.json"
    transport_calls = 0

    def transport(request: Request) -> frozen.HttpPage:
        nonlocal transport_calls
        transport_calls += 1
        assert claim.exists()
        return _success_page(request)

    result = program_006.execute_qualification(
        tmp_path,
        _private_root(tmp_path),
        "a" * 64,
        environ=_credentials(),
        transport=transport,
        pace=lambda: None,
    )
    assert result == {"dataset_id": "x"}
    assert transport_calls == 1
    assert claim.exists()
    assert (_private_root(tmp_path) / "qualification/receipt.json").exists()

    credential_reads: list[bool] = []

    def unexpected_credential_read(*_arguments: Any) -> tuple[str, str]:
        credential_reads.append(True)
        return "key", "value"

    monkeypatch.setattr(
        program_006,
        "read_credentials",
        unexpected_credential_read,
    )
    with pytest.raises(program_006.Program006Error, match="state already exists"):
        program_006.execute_qualification(
            tmp_path,
            _private_root(tmp_path),
            "a" * 64,
            environ=_credentials(),
            transport=transport,
        )
    assert credential_reads == []
    assert transport_calls == 1


def test_provider_failure_after_boundary_is_consumed_without_secret_disclosure(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    _stub_execution(monkeypatch)
    values = _credentials()

    def transport(request: Request) -> frozen.HttpPage:
        return frozen.HttpPage(503, b'{"message":"redacted"}', request.full_url)

    with pytest.raises(frozen.Program005TransportError, match="HTTP 503"):
        program_006.execute_qualification(
            tmp_path,
            _private_root(tmp_path),
            "a" * 64,
            environ=values,
            transport=transport,
            pace=lambda: None,
        )
    scope = _private_root(tmp_path) / "qualification"
    assert (scope / "claim.json").exists()
    assert (scope / "terminal-transport-failure.json").exists()
    captured = capsys.readouterr()
    evidence = captured.out + captured.err
    evidence += "".join(
        path.read_text(encoding="utf-8") for path in scope.rglob("*.json") if path.is_file()
    )
    assert all(value not in evidence for value in values.values())


def test_credential_preflight_cli_prints_only_pass_or_missing_names(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    for name in program_006._CREDENTIAL_NAMES:
        monkeypatch.delenv(name, raising=False)
    assert dispatcher.main(("data", "acquire", "program-006", "credential-preflight")) == 1
    missing = capsys.readouterr()
    assert missing.err == ""
    assert missing.out.splitlines() == [
        f"MISSING: {name}" for name in program_006._CREDENTIAL_NAMES
    ]
    values = _credentials()
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    assert dispatcher.main(("data", "acquire", "program-006", "credential-preflight")) == 0
    passed = capsys.readouterr()
    assert passed.err == ""
    assert passed.out == "PASS\n"
    assert all(value not in missing.out + passed.out for value in values.values())


def test_exact_committed_chain_loads_and_self_rehashed_control_mutations_fail(
    tmp_path: Path,
) -> None:
    required = (
        program_006._IMPLEMENTATION_REVIEW_PATH,
        program_006._PROPOSAL_PATH,
        program_006._REVIEW_PATH,
    )
    if any(not (_REPOSITORY / path).exists() for path in required):
        pytest.skip("Program 006 reviewed control artifacts are added after implementation review")
    repository = tmp_path / "repository"
    subprocess.run(
        ("git", "clone", "--local", "--no-hardlinks", str(_REPOSITORY), str(repository)),
        check=True,
        capture_output=True,
        text=True,
    )
    head = subprocess.run(
        ("git", "-C", str(_REPOSITORY), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ("git", "-C", str(repository), "checkout", "-B", "main", head),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ("git", "-C", str(repository), "update-ref", "refs/remotes/origin/main", head),
        check=True,
    )
    authority = program_006.derive_active_authority(repository)
    assert authority["program_id"] == program_006.PROGRAM_ID
    assert authority["schema_version"] == "program-006-source-authority-v2"
    assert authority["control_lineage"]["synchronized_main_commit"] == head
    assert (
        authority["control_lineage"]["proposal_artifact_commit"]
        != authority["control_lineage"]["proposal_review_artifact_commit"]
    )

    proposal_path = repository / program_006._PROPOSAL_PATH
    original_proposal = proposal_path.read_bytes()
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    proposal.pop("proposal_fingerprint")
    proposal["purpose"] = "self-rehashed mutation"
    proposal["proposal_fingerprint"] = fingerprint(proposal)
    proposal_path.write_text(canonical_json(proposal) + "\n", encoding="utf-8", newline="\n")
    with pytest.raises(program_006.Program006Error):
        program_006.derive_active_authority(repository)

    proposal_path.write_bytes(original_proposal)
    review_path = repository / program_006._REVIEW_PATH
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review.pop("review_fingerprint")
    review["unexpected"] = True
    review["review_fingerprint"] = fingerprint(review)
    review_path.write_text(canonical_json(review) + "\n", encoding="utf-8", newline="\n")
    with pytest.raises(program_006.Program006Error):
        program_006.derive_active_authority(repository)


def test_program_005_terminal_artifacts_remain_byte_exact() -> None:
    for binding in (
        program_006._PROGRAM_005_FAILURE,
        program_006._PROGRAM_005_FAILURE_REVIEW,
    ):
        path = _REPOSITORY / binding["path"]
        digest = subprocess.run(
            ("shasum", "-a", "256", str(path)),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()[0]
        assert digest == binding["sha256"]
    assert not any(
        path.startswith(".trading-lab/")
        for path in subprocess.run(
            ("git", "ls-files"), check=True, capture_output=True, text=True
        ).stdout.splitlines()
    )


def test_private_program_006_artifacts_are_not_tracked() -> None:
    assert not any(
        "program-006-free-alpaca" in path
        for path in subprocess.run(
            ("git", "ls-files"), check=True, capture_output=True, text=True
        ).stdout.splitlines()
    )
