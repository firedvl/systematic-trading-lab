from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast
from urllib.request import Request
from uuid import UUID

import pytest
from pytest import CaptureFixture, MonkeyPatch

import systematic_trading_lab.intraday_fed_policy_absorption_001_cli as dispatcher
import systematic_trading_lab.program_007_alpaca as program_007
import systematic_trading_lab.program_007_corporate_action_authority as authority
import systematic_trading_lab.program_007_corporate_actions as metadata
from systematic_trading_lab.fingerprints import canonical_json, fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_LEDGER_PATH = _REPOSITORY / authority._LEDGER["path"]


def _credentials() -> dict[str, str]:
    return {
        metadata.CREDENTIAL_NAMES[0]: "synthetic-key-material",
        metadata.CREDENTIAL_NAMES[1]: "synthetic-secret-material",
    }


def _active_authority() -> dict[str, Any]:
    return {
        "authority_id": authority.FUTURE_AUTHORITY_ID,
        "authority_fingerprint": "a" * 64,
        "request_plan_fingerprint": authority.expected_request_plan()["request_plan_fingerprint"],
    }


def _ledger() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_LEDGER_PATH.read_text(encoding="utf-8")))


def _forward_split(symbol: str, event_id: int) -> dict[str, Any]:
    return {
        "id": str(UUID(int=event_id)),
        "symbol": symbol,
        "cusip": metadata.IDENTITIES[symbol],
        "new_rate": 2,
        "old_rate": 1,
        "process_date": "2025-12-05",
        "ex_date": "2025-12-05",
    }


def _body(*, next_page: str | None = None) -> bytes:
    events = [
        _forward_split(symbol, index)
        for index, symbol in enumerate(sorted(metadata.POSITIVE_CONTROLS), 1)
    ]
    return json.dumps(
        {
            "corporate_actions": {"forward_splits": events},
            "next_page_token": next_page,
        },
        separators=(",", ":"),
    ).encode()


def _stub_authority(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        authority, "load_active_authority", lambda *_args, **_kwargs: _active_authority()
    )
    monkeypatch.setattr(program_007, "load_action_ledger", lambda _path: _ledger())


def test_request_plan_is_exact_credential_free_and_endpoint_isolated() -> None:
    plan = json.loads((_REPOSITORY / authority.REQUEST_PLAN_PATH).read_bytes())

    assert plan == authority.expected_request_plan()
    assert [chain["chain_id"] for chain in plan["chains"]] == ["symbols", "cusips"]
    assert plan["request"]["endpoint"] == metadata.ENDPOINT
    assert plan["request"]["types"] == "OMITTED"
    assert plan["transport_budget"] == {
        "minimum_http_requests": 2,
        "maximum_http_requests": 8,
        "minimum_http_responses": 2,
        "maximum_http_responses": 8,
        "maximum_pages_per_chain": 4,
        "page_limit": 1000,
        "maximum_response_bytes": 1_048_576,
        "bounded_read_bytes": 1_048_577,
        "maximum_total_bytes": 8_388_608,
        "maximum_credential_loads": 1,
        "automatic_retries": 0,
    }
    assert all(value is False for value in plan["authority"].values())


def test_credential_preflight_cli_prints_only_pass_or_missing_names(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    for name in metadata.CREDENTIAL_NAMES:
        monkeypatch.delenv(name, raising=False)
    assert dispatcher.main(("data", "acquire", "program-007-metadata", "credential-preflight")) == 1
    missing = capsys.readouterr()
    assert missing.err == ""
    assert missing.out.splitlines() == [f"MISSING: {name}" for name in metadata.CREDENTIAL_NAMES]

    values = _credentials()
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    assert dispatcher.main(("data", "acquire", "program-007-metadata", "credential-preflight")) == 0
    passed = capsys.readouterr()
    assert passed.err == ""
    assert passed.out == "PASS\n"
    assert all(value not in missing.out + passed.out for value in values.values())


def test_only_four_metadata_flags_can_activate() -> None:
    active = authority._authority_flags(active=True)

    assert {key for key, value in active.items() if value} == {
        "provider_contact",
        "credential_access",
        "source_requests",
        "source_qualification",
    }
    assert active["market_data_acquisition"] is False
    assert active["strategy_execution"] is False
    assert active["protected_holdout"] is False
    assert active["paper_execution"] is False
    assert active["broker_writes"] is False
    assert active["live_execution"] is False


def test_credential_disappearance_under_lock_stops_before_claim(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    values = _credentials()

    def load(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        values.clear()
        return _active_authority()

    monkeypatch.setattr(authority, "load_active_authority", load)
    monkeypatch.setattr(program_007, "load_action_ledger", lambda _path: _ledger())

    with pytest.raises(authority.Program007AuthorityError, match="credentials missing"):
        authority.execute_qualification(
            tmp_path,
            "a" * 64,
            environ=values,
            transport=lambda _request: (_ for _ in ()).throw(AssertionError("transported")),
        )

    private_root = tmp_path / metadata.PRIVATE_ROOT
    assert not (private_root / "claim.json").exists()
    assert not (private_root / "terminal-failure.json").exists()


def test_claim_exists_immediately_before_first_transport_and_rerun_is_rejected(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _stub_authority(monkeypatch)
    private_root = tmp_path / metadata.PRIVATE_ROOT
    responses = iter((metadata.RawResponse(200, _body()), metadata.RawResponse(200, _body())))
    calls = 0

    def transport(_request: Request) -> metadata.RawResponse:
        nonlocal calls
        calls += 1
        assert (private_root / "claim.json").exists()
        assert _request.full_url.startswith(metadata.ENDPOINT + "?")
        return next(responses)

    result = authority.execute_qualification(
        tmp_path,
        "a" * 64,
        environ=_credentials(),
        transport=transport,
    )

    assert result.response_count == 2
    assert calls == 2
    assert (private_root / "qualification-receipt.json").exists()
    with pytest.raises(authority.Program007AuthorityError, match="state already exists"):
        authority.execute_qualification(
            tmp_path,
            "a" * 64,
            environ=_credentials(),
            transport=transport,
        )
    assert calls == 2


@pytest.mark.parametrize(
    ("responses", "message"),
    [
        ([metadata.RawResponse(403, b'{"error":"denied"}')], "METADATA-ACCESS-FAIL"),
        (
            [
                metadata.RawResponse(
                    200,
                    b'{"corporate_actions":{},"next_page_token":"same"}',
                )
            ]
            * 2,
            "pagination token repeats",
        ),
        (
            [metadata.RawResponse(200, b"x" * (metadata.MAXIMUM_RESPONSE_PAGE_BYTES + 1))],
            "exceeds 1 MiB",
        ),
    ],
)
def test_post_claim_failures_are_terminal_and_never_leak_secrets(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    responses: list[metadata.RawResponse],
    message: str,
) -> None:
    _stub_authority(monkeypatch)
    values = _credentials()
    pending = iter(responses)

    with pytest.raises(metadata.Program007MetadataError, match=message):
        authority.execute_qualification(
            tmp_path,
            "a" * 64,
            environ=values,
            transport=lambda _request: next(pending),
        )

    private_root = tmp_path / metadata.PRIVATE_ROOT
    assert (private_root / "claim.json").exists()
    failure = json.loads((private_root / "terminal-failure.json").read_bytes())
    assert failure["status"] == "TERMINAL-FAIL-CONSUMED-NO-RETRY"
    captured = capsys.readouterr()
    evidence = captured.out + captured.err
    evidence += "".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in private_root.iterdir()
        if path.is_file()
    )
    assert all(value not in evidence for value in values.values())


def test_no_standalone_provider_transport_exists() -> None:
    assert not hasattr(authority, "_authorized_urlopen_response")


def test_blocked_v1_is_preserved_without_authority_or_claim() -> None:
    blocked_proposal = _REPOSITORY / authority._BLOCKED_PROPOSAL["path"]
    blocked_review = _REPOSITORY / authority._BLOCKED_REVIEW["path"]

    assert (
        authority._load_static_artifact(
            _REPOSITORY, authority._BLOCKED_PROPOSAL, "proposal_fingerprint"
        )["status"]
        == "BLOCKED-CREDENTIALS-NOT-VISIBLE-TO-RUNTIME"
    )
    assert (
        authority._load_static_artifact(
            _REPOSITORY, authority._BLOCKED_REVIEW, "review_fingerprint"
        )["status"]
        == "PASS-BLOCKED-CREDENTIALS-NOT-VISIBLE-TO-RUNTIME"
    )
    assert blocked_proposal.is_file()
    assert blocked_review.is_file()
    private_root = _REPOSITORY / metadata.PRIVATE_ROOT
    assert not (private_root / "active-authority.json").exists()
    assert not (private_root / "claim.json").exists()


def test_ready_proposal_creates_no_authority_or_claim() -> None:
    if (
        not (_REPOSITORY / authority.PROPOSAL_PATH).exists()
        or not (_REPOSITORY / authority.REVIEW_PATH).exists()
    ):
        pytest.skip("ready proposal and review are committed after implementation")

    controls = authority.validate_proposal_chain(_REPOSITORY)
    assert controls["proposal"]["status"] == authority.READY_STATUS
    assert controls["proposal"]["credential_lifecycle"]["presence_preflight"] == "PASS"
    assert controls["proposal"]["authority"] == authority._authority_flags(active=False)
    private_root = _REPOSITORY / metadata.PRIVATE_ROOT
    assert not (private_root / "active-authority.json").exists()
    assert not (private_root / "claim.json").exists()
    assert not private_root.exists()


def _copy_controls(destination: Path) -> None:
    paths = (
        Path(authority._LEDGER["path"]),
        Path(authority._PLAN["path"]),
        Path(authority._IMPLEMENTATION["path"]),
        Path(authority._IMPLEMENTATION_REVIEW["path"]),
        Path(authority._BLOCKED_PROPOSAL["path"]),
        Path(authority._BLOCKED_REVIEW["path"]),
        authority.REQUEST_PLAN_PATH,
        authority.PROPOSAL_PATH,
        authority.REVIEW_PATH,
    )
    for relative in paths:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_REPOSITORY / relative, target)


@pytest.mark.parametrize(
    "relative",
    [
        Path(authority._LEDGER["path"]),
        Path(authority._PLAN["path"]),
        Path(authority._IMPLEMENTATION["path"]),
        Path(authority._IMPLEMENTATION_REVIEW["path"]),
        Path(authority._BLOCKED_PROPOSAL["path"]),
        Path(authority._BLOCKED_REVIEW["path"]),
    ],
)
def test_bound_source_artifact_mutation_fails(relative: Path, tmp_path: Path) -> None:
    if not (_REPOSITORY / authority.REVIEW_PATH).exists():
        pytest.skip("proposal review is committed after implementation")
    _copy_controls(tmp_path)
    path = tmp_path / relative
    path.write_bytes(path.read_bytes() + b" \n")

    with pytest.raises(authority.Program007AuthorityError, match="binding differs"):
        authority.validate_proposal_chain(tmp_path)


def test_self_rehashed_request_plan_mutation_fails(tmp_path: Path) -> None:
    if not (_REPOSITORY / authority.REVIEW_PATH).exists():
        pytest.skip("proposal review is committed after implementation")
    _copy_controls(tmp_path)
    path = tmp_path / authority.REQUEST_PLAN_PATH
    plan = json.loads(path.read_bytes())
    plan.pop("request_plan_fingerprint")
    plan["request"]["types"] = "forward_split"
    plan["request_plan_fingerprint"] = fingerprint(plan)
    path.write_text(canonical_json(plan) + "\n", encoding="utf-8", newline="\n")

    with pytest.raises(authority.Program007AuthorityError, match="request plan differs"):
        authority.validate_proposal_chain(tmp_path)


def test_git_mutation_fails_reviewed_lineage(tmp_path: Path) -> None:
    if not (_REPOSITORY / authority.REVIEW_PATH).exists():
        pytest.skip("proposal review is committed after implementation")
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
    for ref in ("refs/heads/main", "refs/remotes/origin/main"):
        subprocess.run(
            ("git", "-C", str(repository), "update-ref", ref, head),
            check=True,
        )
    subprocess.run(
        ("git", "-C", str(repository), "checkout", "--detach", head),
        check=True,
        capture_output=True,
        text=True,
    )
    controls = authority.validate_proposal_chain(repository)
    proposal = cast(dict[str, Any], controls["proposal"])
    lineage = authority._repository_preflight(repository, proposal, controls)
    assert lineage["synchronized_main_commit"] == head
    active = authority.derive_authorization_root(repository, environ=_credentials())
    assert {key for key, value in active["authority"].items() if value} == {
        "provider_contact",
        "credential_access",
        "source_requests",
        "source_qualification",
    }

    source = repository / "src/systematic_trading_lab/program_007_corporate_action_authority.py"
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(authority.Program007AuthorityError, match="control lineage differs"):
        authority._repository_preflight(repository, proposal, controls)
