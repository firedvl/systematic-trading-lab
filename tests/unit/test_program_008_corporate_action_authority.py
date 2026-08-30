from __future__ import annotations

import hashlib
import inspect
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse
from urllib.request import Request
from uuid import UUID

import pytest
from pytest import CaptureFixture, MonkeyPatch

import systematic_trading_lab.intraday_fed_policy_absorption_001_cli as dispatcher
import systematic_trading_lab.program_007_alpaca as ledger_contract
import systematic_trading_lab.program_007_corporate_actions as predecessor
import systematic_trading_lab.program_008_corporate_action_authority as authority
import systematic_trading_lab.program_008_corporate_actions as metadata
from systematic_trading_lab.fingerprints import canonical_json, fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_LEDGER_PATH = _REPOSITORY / authority._LEDGER["path"]


def _credentials() -> dict[str, str]:
    return {
        authority.CREDENTIAL_NAMES[0]: "synthetic-key-material",
        authority.CREDENTIAL_NAMES[1]: "synthetic-secret-material",
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
        "isin": "",
        "new_rate": 2,
        "old_rate": 1,
        "process_date": "2025-12-05",
        "ex_date": "2025-12-05",
    }


def _body(*, next_page: str | None = None, controls: bool = True) -> bytes:
    events = (
        [
            _forward_split(symbol, index)
            for index, symbol in enumerate(sorted(metadata.POSITIVE_CONTROLS), 1)
        ]
        if controls
        else []
    )
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
    monkeypatch.setattr(ledger_contract, "load_action_ledger", lambda _path: _ledger())


def test_request_plan_is_exact_cusip_only_and_credential_free() -> None:
    plan = json.loads((_REPOSITORY / authority.REQUEST_PLAN_PATH).read_bytes())
    chain = authority.frozen_request_chain()

    assert plan == authority.expected_request_plan()
    assert chain.chain_id == "cusips"
    assert chain.identity_parameter == "cusips"
    assert len(chain.identities) == 13
    assert chain.parameters == (
        ("cusips", ",".join(chain.identities)),
        ("region", "us"),
        ("start", "1990-01-01"),
        ("end", "2026-08-29"),
        ("limit", "1000"),
        ("data_quality", "complete"),
        ("sort", "asc"),
    )
    assert "symbols=" not in chain.url()
    assert "types=" not in chain.url()
    assert urlparse(chain.url()).path == "/v1/corporate-actions"
    assert plan["transport_budget"] == {
        "minimum_http_requests": 1,
        "maximum_http_requests": 4,
        "minimum_http_responses": 1,
        "maximum_http_responses": 4,
        "maximum_pages": 4,
        "page_limit": 1000,
        "maximum_response_bytes": 1_048_576,
        "bounded_read_bytes": 1_048_577,
        "maximum_total_bytes": 4_194_304,
        "maximum_credential_loads": 1,
        "automatic_retries": 0,
    }
    assert all(value is False for value in plan["authority"].values())


def test_symbol_or_endpoint_mutation_is_rejected() -> None:
    chain = authority.frozen_request_chain()
    symbol_url = chain.url().replace("cusips=", "symbols=")
    bars_url = chain.url().replace("/v1/corporate-actions", "/v2/stocks/bars")

    for url in (symbol_url, bars_url, chain.url() + "&types=forward_split"):
        with pytest.raises(authority.Program008AuthorityError, match="endpoint or query differs"):
            authority._validate_http_request(Request(url, method="GET"))

    intent = predecessor.RequestIntent("symbols", chain.identity, 1, symbol_url, None)
    with pytest.raises(authority.Program008AuthorityError, match="request intent differs"):
        authority._validate_intent(intent)


def test_opaque_page_token_keeps_exact_fixed_query() -> None:
    chain = authority.frozen_request_chain()
    request = Request(chain.url("opaque+/="), method="GET")

    authority._validate_http_request(request)
    query = parse_qs(urlparse(request.full_url).query)
    assert query["cusips"] == [",".join(chain.identities)]
    assert query["page_token"] == ["opaque+/="]
    assert "symbols" not in query


def test_credential_preflight_cli_prints_only_pass_or_missing_names(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    for name in authority.CREDENTIAL_NAMES:
        monkeypatch.delenv(name, raising=False)
    assert dispatcher.main(("data", "acquire", "program-008-metadata", "credential-preflight")) == 1
    missing = capsys.readouterr()
    assert missing.err == ""
    assert missing.out.splitlines() == [f"MISSING: {name}" for name in authority.CREDENTIAL_NAMES]

    values = _credentials()
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    assert dispatcher.main(("data", "acquire", "program-008-metadata", "credential-preflight")) == 0
    passed = capsys.readouterr()
    assert passed.err == ""
    assert passed.out == "PASS\n"
    assert all(value not in missing.out + passed.out for value in values.values())


def test_missing_credentials_create_no_root_or_claim(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        authority,
        "validate_proposal_chain",
        lambda _repository: {
            "proposal": {"status": authority.READY_STATUS},
            "request_plan": {"request_plan_fingerprint": "b" * 64},
        },
    )
    monkeypatch.setattr(authority, "_repository_preflight", lambda *_args: {})

    with pytest.raises(authority.Program008AuthorityError, match="credentials missing"):
        authority.derive_authorization_root(tmp_path, environ={})

    assert not (tmp_path / authority.PRIVATE_ROOT).exists()


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


def test_production_executor_owns_fixed_transport(monkeypatch: MonkeyPatch) -> None:
    opens = 0

    class Opener:
        def open(self, *_args: Any, **_kwargs: Any) -> None:
            nonlocal opens
            opens += 1

    def build(handler: Any) -> Opener:
        assert isinstance(handler, predecessor._NoRedirect)
        return Opener()

    monkeypatch.setattr(authority, "build_opener", build)
    authority._AlpacaMetadataClient("key", "secret")

    assert tuple(inspect.signature(authority.execute_qualification).parameters) == (
        "repository",
        "authorization_root",
        "environ",
    )
    assert opens == 0


def test_mock_transport_must_be_exact_finite_type(tmp_path: Path) -> None:
    with pytest.raises(authority.Program008AuthorityError, match="requires a finite mock"):
        authority._execute_mock_qualification(
            tmp_path,
            "a" * 64,
            environ=_credentials(),
            transport=cast(Any, lambda _request: predecessor.RawResponse(200, _body())),
        )

    assert not (tmp_path / authority.PRIVATE_ROOT).exists()


def test_activation_persists_authority_without_consuming_claim(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    active = _active_authority()
    monkeypatch.setattr(authority, "derive_authorization_root", lambda *_args, **_kwargs: active)

    assert authority.activate_authority(tmp_path, "a" * 64, environ=_credentials()) == active
    private_root = tmp_path / authority.PRIVATE_ROOT
    assert (private_root / "active-authority.json").exists()
    assert not (private_root / "claim.json").exists()
    with pytest.raises(authority.Program008AuthorityError, match="state already exists"):
        authority.activate_authority(tmp_path, "a" * 64, environ=_credentials())


def test_credential_disappearance_under_lock_stops_before_claim(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    values = _credentials()

    def load(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        values.clear()
        return _active_authority()

    monkeypatch.setattr(authority, "load_active_authority", load)
    monkeypatch.setattr(ledger_contract, "load_action_ledger", lambda _path: _ledger())

    transport = authority.MockMetadataTransport([predecessor.RawResponse(200, _body())])
    with pytest.raises(authority.Program008AuthorityError, match="credentials missing"):
        authority._execute_mock_qualification(
            tmp_path,
            "a" * 64,
            environ=values,
            transport=transport,
        )

    private_root = tmp_path / authority.PRIVATE_ROOT
    assert not transport.intents
    assert not (private_root / "claim.json").exists()
    assert not (private_root / "terminal-failure.json").exists()


def test_claim_raw_first_and_fresh_response_firewall(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _stub_authority(monkeypatch)
    private_root = tmp_path / authority.PRIVATE_ROOT
    calls = 0
    credential_loads = 0
    original_read_credentials = authority.read_credentials
    original_parse = metadata.parse_metadata_page

    def read_credentials(*args: Any, **kwargs: Any) -> tuple[str, str]:
        nonlocal credential_loads
        credential_loads += 1
        return original_read_credentials(*args, **kwargs)

    transport = authority.MockMetadataTransport([predecessor.RawResponse(200, _body())])
    original_get = authority.MockMetadataTransport.get

    def get(
        self: authority.MockMetadataTransport,
        intent: predecessor.RequestIntent,
    ) -> predecessor.RawResponse:
        nonlocal calls
        calls += 1
        assert (private_root / "claim.json").exists()
        assert (private_root / "cusips-01.intent.json").exists()
        assert not (private_root / "cusips-01.body").exists()
        assert intent.url == authority.frozen_request_chain().url()
        assert "symbols=" not in intent.url
        return original_get(self, intent)

    def parse(body: bytes) -> metadata.ParsedPage:
        assert (private_root / "cusips-01.body").read_bytes() == body
        receipt = json.loads((private_root / "cusips-01.receipt.json").read_bytes())
        assert receipt["response_sha256"] == hashlib.sha256(body).hexdigest()
        return original_parse(body)

    monkeypatch.setattr(authority, "read_credentials", read_credentials)
    monkeypatch.setattr(authority.MockMetadataTransport, "get", get)
    monkeypatch.setattr(metadata, "parse_metadata_page", parse)
    monkeypatch.setattr(
        metadata,
        "reconcile_with_exposed_symbol_response",
        lambda *_args: (_ for _ in ()).throw(AssertionError("read exposed response")),
    )

    result = authority._execute_mock_qualification(
        tmp_path,
        "a" * 64,
        environ=_credentials(),
        transport=transport,
    )

    assert result.page_count == 1
    assert len(result.events) == 5
    assert calls == 1
    assert len(transport.intents) == 1
    assert credential_loads == 1
    receipt = json.loads((private_root / "qualification-receipt.json").read_bytes())
    assert receipt["program_007_response_used"] is False
    with pytest.raises(authority.Program008AuthorityError, match="state already exists"):
        authority._execute_mock_qualification(
            tmp_path,
            "a" * 64,
            environ=_credentials(),
            transport=transport,
        )
    assert calls == 1


@pytest.mark.parametrize(
    ("responses", "message"),
    [
        ([predecessor.RawResponse(403, b'{"error":"denied"}')], "HTTP 403"),
        ([predecessor.RawResponse(429, b'{"error":"limited"}')], "HTTP 429"),
        ([predecessor.RawResponse(503, b'{"error":"unavailable"}')], "HTTP 503"),
        (
            [predecessor.RawResponse(200, b"x" * (metadata.MAXIMUM_RESPONSE_PAGE_BYTES + 1))],
            "exceeds 1 MiB",
        ),
        ([predecessor.RawResponse(200, b"{")], "not valid JSON"),
        (
            [
                predecessor.RawResponse(200, _body(next_page="same", controls=False)),
                predecessor.RawResponse(200, _body(next_page="same", controls=False)),
            ],
            "pagination token repeats",
        ),
    ],
)
def test_post_claim_failures_are_terminal_and_never_leak_secrets(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    responses: list[predecessor.RawResponse],
    message: str,
) -> None:
    _stub_authority(monkeypatch)
    values = _credentials()
    transport = authority.MockMetadataTransport(responses)

    with pytest.raises(
        (authority.Program008AuthorityError, metadata.Program008MetadataError), match=message
    ):
        authority._execute_mock_qualification(
            tmp_path,
            "a" * 64,
            environ=values,
            transport=transport,
        )

    private_root = tmp_path / authority.PRIVATE_ROOT
    assert (private_root / "claim.json").exists()
    assert (private_root / "terminal-failure.json").exists()
    assert (private_root / "cusips-01.body").read_bytes() == responses[0].body[
        : metadata.MAXIMUM_RESPONSE_PAGE_BYTES + 1
    ]
    captured = capsys.readouterr()
    evidence = captured.out + captured.err
    evidence += "".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in private_root.iterdir()
        if path.is_file()
    )
    assert all(value not in evidence for value in values.values())


def test_four_nonterminal_pages_fail_consumed_without_a_fifth_request(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _stub_authority(monkeypatch)
    transport = authority.MockMetadataTransport(
        [
            predecessor.RawResponse(
                200,
                _body(next_page=f"page-{index}", controls=False),
            )
            for index in range(1, 5)
        ]
    )

    with pytest.raises(authority.Program008AuthorityError, match="exceeds four pages"):
        authority._execute_mock_qualification(
            tmp_path,
            "a" * 64,
            environ=_credentials(),
            transport=transport,
        )

    assert len(transport.intents) == 4
    assert (tmp_path / authority.PRIVATE_ROOT / "terminal-failure.json").exists()


def test_program_007_terminal_and_program_008_static_bindings_are_exact() -> None:
    terminal = authority._load_static_artifact(
        _REPOSITORY, authority._PROGRAM_007_TERMINAL, "failure_fingerprint"
    )
    authority._validate_program_007_terminal(terminal)
    assert terminal["status"] == "TERMINAL-FAIL-CONSUMED-NO-RETRY"

    for binding, field in (
        (authority._FORENSIC_ANALYSIS, "analysis_fingerprint"),
        (authority._PROGRAM_008_PROPOSAL, "proposal_fingerprint"),
        (authority._FORENSIC_REVIEW, "review_fingerprint"),
        (authority._LEDGER, "ledger_fingerprint"),
    ):
        authority._load_static_artifact(_REPOSITORY, binding, field)


def test_authority_proposal_and_review_validate_when_committed() -> None:
    controls = authority.validate_proposal_chain(_REPOSITORY)
    assert controls["proposal"]["status"] == authority.READY_STATUS
    assert controls["review"]["verdict"] == "PASS"
    assert controls["proposal"]["authority"] == authority._authority_flags(active=False)


def test_terminal_success_revokes_before_credentials_or_private_state(
    monkeypatch: MonkeyPatch,
) -> None:
    credential_reads: list[bool] = []
    private_root_opens: list[bool] = []
    monkeypatch.setattr(
        authority,
        "_require_credentials_present",
        lambda _environ: credential_reads.append(True),
    )
    monkeypatch.setattr(
        authority,
        "_open_private_root",
        lambda _repository: private_root_opens.append(True),
    )

    for operation in (
        lambda: authority.derive_authorization_root(_REPOSITORY, environ={}),
        lambda: authority.activate_authority(_REPOSITORY, "a" * 64, environ={}),
        lambda: authority.execute_qualification(_REPOSITORY, "a" * 64, environ={}),
    ):
        with pytest.raises(authority.Program008AuthorityError, match="terminally revoked"):
            operation()

    assert credential_reads == []
    assert private_root_opens == []


def _copy_controls(destination: Path) -> None:
    paths = (
        Path(authority._PROGRAM_007_TERMINAL["path"]),
        Path(authority._FORENSIC_ANALYSIS["path"]),
        Path(authority._PROGRAM_008_PROPOSAL["path"]),
        Path(authority._FORENSIC_REVIEW["path"]),
        Path(authority._LEDGER["path"]),
        authority.REQUEST_PLAN_PATH,
        authority.PROPOSAL_PATH,
        authority.REVIEW_PATH,
    )
    for relative in paths:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_REPOSITORY / relative, target)


@pytest.mark.parametrize(
    ("binding", "field"),
    [
        (authority._PROGRAM_007_TERMINAL, "failure_fingerprint"),
        (authority._FORENSIC_ANALYSIS, "analysis_fingerprint"),
        (authority._PROGRAM_008_PROPOSAL, "proposal_fingerprint"),
        (authority._FORENSIC_REVIEW, "review_fingerprint"),
        (authority._LEDGER, "ledger_fingerprint"),
    ],
)
def test_bound_artifact_mutation_fails(
    binding: dict[str, str],
    field: str,
    tmp_path: Path,
) -> None:
    _copy_controls(tmp_path)
    path = tmp_path / binding["path"]
    path.write_bytes(path.read_bytes() + b" \n")

    with pytest.raises(authority.Program008AuthorityError, match="binding differs"):
        authority._load_static_artifact(tmp_path, binding, field)


def test_self_rehashed_request_plan_mutation_fails(tmp_path: Path) -> None:
    _copy_controls(tmp_path)
    path = tmp_path / authority.REQUEST_PLAN_PATH
    plan = json.loads(path.read_bytes())
    plan.pop("request_plan_fingerprint")
    plan["chain"]["identity_parameter"] = "symbols"
    plan["request_plan_fingerprint"] = fingerprint(plan)
    path.write_text(canonical_json(plan) + "\n", encoding="utf-8", newline="\n")

    with pytest.raises(authority.Program008AuthorityError, match="request plan differs"):
        authority.validate_proposal_chain(tmp_path)


def test_self_rehashed_proposal_or_review_mutation_fails(tmp_path: Path) -> None:
    for relative, field, section, key, expected in (
        (
            authority.PROPOSAL_PATH,
            "proposal_fingerprint",
            "qualification",
            "symbol_filter_allowed",
            "authority proposal semantics differ",
        ),
        (
            authority.REVIEW_PATH,
            "review_fingerprint",
            "required_challenges",
            "symbol_chain_authorized",
            "authority proposal review differs",
        ),
    ):
        destination = tmp_path / relative.stem
        _copy_controls(destination)
        path = destination / relative
        payload = json.loads(path.read_bytes())
        payload.pop(field)
        payload[section][key] = "PASS"
        payload[field] = fingerprint(payload)
        path.write_text(canonical_json(payload) + "\n", encoding="utf-8", newline="\n")

        with pytest.raises(authority.Program008AuthorityError, match=expected):
            authority.validate_proposal_chain(destination)


def test_git_mutation_fails_reviewed_lineage(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    subprocess.run(
        ("git", "clone", "--local", "--no-hardlinks", str(_REPOSITORY), str(repository)),
        check=True,
        capture_output=True,
        text=True,
    )
    terminal = json.loads((_REPOSITORY / authority._TERMINAL_SUCCESS["path"]).read_bytes())
    head = str(terminal["execution_main"])
    subprocess.run(
        ("git", "-C", str(repository), "checkout", "-B", "main", head),
        check=True,
        capture_output=True,
        text=True,
    )
    for ref in ("refs/heads/main", "refs/remotes/origin/main"):
        subprocess.run(
            ("git", "-C", str(repository), "update-ref", ref, head),
            check=True,
        )
    controls = authority.validate_proposal_chain(repository)
    proposal = cast(dict[str, Any], controls["proposal"])
    lineage = authority._repository_preflight(repository, proposal, controls)
    assert lineage["synchronized_main_commit"] == head

    source = repository / "src/systematic_trading_lab/program_008_corporate_action_authority.py"
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(authority.Program008AuthorityError, match="control lineage differs"):
        authority._repository_preflight(repository, proposal, controls)
