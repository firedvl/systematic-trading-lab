from __future__ import annotations

import hashlib
import inspect
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, cast
from urllib.request import Request

import pytest
from pytest import CaptureFixture, MonkeyPatch

import systematic_trading_lab.intraday_fed_policy_absorption_001_cli as dispatcher
import systematic_trading_lab.program_007_alpaca as raw_contract
import systematic_trading_lab.program_009_ohlcv_authority as authority
from systematic_trading_lab.calendar import expected_bar_timestamps
from systematic_trading_lab.domain import Timeframe

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
    chain: raw_contract.RequestChain,
) -> list[tuple[str, dict[str, object]]]:
    timestamps = expected_bar_timestamps(chain.start, chain.end, Timeframe.FIVE_MINUTES)
    return [
        (symbol, _bar(timestamp.isoformat().replace("+00:00", "Z")))
        for symbol in chain.symbols
        for timestamp in timestamps
    ]


def _body(rows: list[tuple[str, dict[str, object]]], token: str | None = None) -> bytes:
    bars: dict[str, list[dict[str, object]]] = defaultdict(list)
    for symbol, row in rows:
        bars[symbol].append(row)
    return json.dumps(
        {"bars": dict(bars), "next_page_token": token}, separators=(",", ":")
    ).encode()


def _responses() -> list[raw_contract.RawResponse]:
    responses: list[raw_contract.RawResponse] = []
    for chain in authority.frozen_request_chains():
        rows = _complete_rows(chain)
        if chain.chain_id == "pagination-2023-05-16-to-2023-05-30":
            extended = ("SPY", _bar("2023-05-16T20:00:00Z"))
            responses.append(raw_contract.RawResponse(200, _body([*rows[:9_999], extended], "p2")))
            responses.append(raw_contract.RawResponse(200, _body(rows[9_999:])))
        else:
            responses.append(raw_contract.RawResponse(200, _body(rows)))
    return responses


def _stub_execution(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        authority, "load_active_authority", lambda *_args, **_kwargs: _active_authority()
    )
    monkeypatch.setattr(raw_contract, "load_action_ledger", lambda _path: _ledger())


def test_successor_and_request_plan_are_exact_credential_free_raw_sip() -> None:
    successor = json.loads((_REPOSITORY / authority.SUCCESSOR_PROPOSAL_PATH).read_bytes())
    plan = json.loads((_REPOSITORY / authority.REQUEST_PLAN_PATH).read_bytes())

    assert successor == authority.expected_successor_proposal()
    assert plan == authority.expected_request_plan()
    assert plan["request"] == {
        "method": "GET",
        "endpoint": "https://data.alpaca.markets/v2/stocks/bars",
        "feed": "sip",
        "timeframe": "5Min",
        "adjustment": "raw",
        "sort": "asc",
        "limit": 10_000,
        "asof": "2026-07-31",
        "inclusive_bounds": True,
        "redirects": False,
        "pagination_token": "opaque page_token appended after fixed parameters",
    }
    assert plan["expected_canonical_coordinate_count"] == 14_742
    assert len(plan["chains"]) == 6
    assert plan["transport_budget"] == {
        "logical_chain_count": 6,
        "minimum_http_requests": 7,
        "maximum_http_requests": 11,
        "minimum_http_responses": 7,
        "maximum_http_responses": 11,
        "maximum_response_page_bytes": 8_388_608,
        "bounded_read_bytes": 8_388_609,
        "maximum_total_bytes": 16_777_216,
        "maximum_requests_per_minute": 120,
        "maximum_credential_loads": 1,
        "automatic_retries": 0,
        "minimum_forced_pagination_pages": 2,
    }
    assert all(value is False for value in plan["authority"].values())


def test_credential_preflight_cli_prints_only_pass_or_missing_names(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    for name in authority.CREDENTIAL_NAMES:
        monkeypatch.delenv(name, raising=False)
    assert dispatcher.main(("data", "acquire", "program-009-ohlcv", "credential-preflight")) == 1
    missing = capsys.readouterr()
    assert missing.err == ""
    assert missing.out.splitlines() == [f"MISSING: {name}" for name in authority.CREDENTIAL_NAMES]

    values = _credentials()
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    assert dispatcher.main(("data", "acquire", "program-009-ohlcv", "credential-preflight")) == 0
    passed = capsys.readouterr()
    assert passed.err == ""
    assert passed.out == "PASS\n"
    assert all(value not in missing.out + passed.out for value in values.values())


def test_missing_credentials_create_no_root_or_claim(
    tmp_path: Path, monkeypatch: MonkeyPatch
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

    with pytest.raises(authority.Program009AuthorityError, match="credentials missing"):
        authority.derive_authorization_root(tmp_path, environ={})

    assert not (tmp_path / authority.PRIVATE_ROOT).exists()


@pytest.mark.parametrize("failure", ["authority", "credentials"])
def test_run_preflight_failure_creates_no_private_root(
    failure: str, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    if failure == "authority":

        def load_active_authority(*_args: Any, **_kwargs: Any) -> None:
            raise authority.Program009AuthorityError("Program 009 OHLCV authority is absent")

        monkeypatch.setattr(authority, "load_active_authority", load_active_authority)
        environ = _credentials()
        message = "authority is absent"
    else:
        monkeypatch.setattr(
            authority, "load_active_authority", lambda *_args, **_kwargs: _active_authority()
        )
        environ = {}
        message = "credentials missing"
    transport = authority.MockBarsTransport([raw_contract.RawResponse(200, b"{}")])

    with pytest.raises(authority.Program009AuthorityError, match=message):
        authority._execute_mock_qualification(
            tmp_path, "a" * 64, environ=environ, transport=transport
        )

    assert not transport.intents
    assert not (tmp_path / authority.PRIVATE_ROOT).exists()


def test_only_structural_qualification_flags_can_activate() -> None:
    active = authority._authority_flags(active=True)

    assert {key for key, value in active.items() if value} == {
        "provider_contact",
        "credential_access",
        "source_requests",
        "source_qualification",
    }
    assert active["market_data_acquisition"] is False
    assert active["real_dataset_admission"] is False
    assert active["strategy_execution"] is False
    assert active["protected_holdout"] is False
    assert active["paper_execution"] is False
    assert active["broker_writes"] is False
    assert active["live_execution"] is False


def test_endpoint_or_adjustment_mutation_is_rejected() -> None:
    chain = authority.frozen_request_chains()[0]
    valid = Request(chain.url(), method="GET")
    authority._validate_http_request(valid)

    for url in (
        chain.url().replace("/v2/stocks/bars", "/v1/corporate-actions"),
        chain.url().replace("adjustment=raw", "adjustment=split"),
        chain.url().replace("feed=sip", "feed=iex"),
        chain.url() + "&symbols=QQQ",
    ):
        with pytest.raises(authority.Program009AuthorityError, match="endpoint or query differs"):
            authority._validate_http_request(Request(url, method="GET"))


def test_production_executor_owns_fixed_transport(monkeypatch: MonkeyPatch) -> None:
    opens = 0

    class Opener:
        def open(self, *_args: Any, **_kwargs: Any) -> None:
            nonlocal opens
            opens += 1

    monkeypatch.setattr(authority, "build_opener", lambda _handler: Opener())
    authority._AlpacaBarsClient("key", "secret", pace=lambda: None)

    assert tuple(inspect.signature(authority.execute_qualification).parameters) == (
        "repository",
        "authorization_root",
        "environ",
    )
    assert opens == 0


def test_activation_persists_authority_without_consuming_claim(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    active = _active_authority()
    monkeypatch.setattr(authority, "derive_authorization_root", lambda *_args, **_kwargs: active)

    assert authority.activate_authority(tmp_path, "a" * 64, environ=_credentials()) == active
    private_root = tmp_path / authority.PRIVATE_ROOT
    assert (private_root / "active-authority.json").exists()
    assert not (private_root / "claim.json").exists()
    with pytest.raises(authority.Program009AuthorityError, match="state already exists"):
        authority.activate_authority(tmp_path, "a" * 64, environ=_credentials())


def test_credential_disappearance_under_lock_stops_before_claim(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    values = _credentials()

    def load(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        values.clear()
        return _active_authority()

    monkeypatch.setattr(authority, "load_active_authority", load)
    monkeypatch.setattr(raw_contract, "load_action_ledger", lambda _path: _ledger())
    transport = authority.MockBarsTransport([raw_contract.RawResponse(200, b"{}")])

    with pytest.raises(authority.Program009AuthorityError, match="credentials missing"):
        authority._execute_mock_qualification(
            tmp_path, "a" * 64, environ=values, transport=transport
        )

    private_root = tmp_path / authority.PRIVATE_ROOT
    assert not transport.intents
    assert not (private_root / "claim.json").exists()
    assert not (private_root / "terminal-failure.json").exists()


def test_claim_raw_first_projection_pagination_and_one_use(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _stub_execution(monkeypatch)
    private_root = tmp_path / authority.PRIVATE_ROOT
    transport = authority.MockBarsTransport(_responses())
    original_get = authority.MockBarsTransport.get
    original_parse = raw_contract.parse_raw_page
    credential_loads = 0
    original_read = authority.read_credentials

    def read(*args: Any, **kwargs: Any) -> tuple[str, str]:
        nonlocal credential_loads
        credential_loads += 1
        return original_read(*args, **kwargs)

    def get(
        self: authority.MockBarsTransport, intent: raw_contract.RequestIntent
    ) -> raw_contract.RawResponse:
        prefix = f"{intent.chain_id}-{intent.page_index:02d}"
        assert (private_root / "claim.json").exists()
        assert json.loads((private_root / "claim.json").read_bytes())["terminal_fallback"] == {
            "applies_without_valid_pass_receipt": True,
            "provider_transport_outcome": "AMBIGUOUS",
            "retry_allowed": False,
            "status": "FAIL-CONSUMED-NO-RETRY",
        }
        assert (private_root / f"{prefix}.intent.json").exists()
        assert not (private_root / f"{prefix}.body").exists()
        return original_get(self, intent)

    def parse(
        body: bytes, chain: raw_contract.RequestChain
    ) -> tuple[tuple[raw_contract.RawBar, ...], str | None]:
        index = len([intent for intent in transport.intents if intent.chain_id == chain.chain_id])
        prefix = f"{chain.chain_id}-{index:02d}"
        assert (private_root / f"{prefix}.body").read_bytes() == body
        receipt = json.loads((private_root / f"{prefix}.receipt.json").read_bytes())
        assert receipt["response_sha256"] == hashlib.sha256(body).hexdigest()
        return original_parse(body, chain)

    monkeypatch.setattr(authority, "read_credentials", read)
    monkeypatch.setattr(authority.MockBarsTransport, "get", get)
    monkeypatch.setattr(raw_contract, "parse_raw_page", parse)

    result = authority._execute_mock_qualification(
        tmp_path, "a" * 64, environ=_credentials(), transport=transport
    )

    assert result.response_count == len(transport.intents) == 7
    assert result.raw_row_count == 14_743
    assert result.canonical_row_count == 14_742
    assert credential_loads == 1
    pagination = next(
        chain
        for chain in result.chains
        if chain.chain.chain_id == "pagination-2023-05-16-to-2023-05-30"
    )
    assert len(pagination.pages) == 2
    assert len(pagination.raw_rows) == 10_141
    assert len(pagination.canonical_rows) == 10_140
    receipt = json.loads((private_root / "qualification-receipt.json").read_bytes())
    assert receipt["dataset_admitted"] is False
    assert receipt["strategy_calculations"] == 0
    assert receipt["strategy_returns"] == 0

    with pytest.raises(authority.Program009AuthorityError, match="state already exists"):
        authority._execute_mock_qualification(
            tmp_path, "a" * 64, environ=_credentials(), transport=transport
        )
    assert len(transport.intents) == 7


@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_post_claim_http_failure_is_terminal_and_retains_bytes(
    status: int, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _stub_execution(monkeypatch)
    body = b'{"error":"bounded"}'
    transport = authority.MockBarsTransport([raw_contract.RawResponse(status, body)])

    with pytest.raises(authority.Program009AuthorityError, match=f"HTTP {status}"):
        authority._execute_mock_qualification(
            tmp_path, "a" * 64, environ=_credentials(), transport=transport
        )

    private_root = tmp_path / authority.PRIVATE_ROOT
    prefix = "normal-2021-07-08-01"
    assert (private_root / f"{prefix}.body").read_bytes() == body
    assert (private_root / f"{prefix}.receipt.json").exists()
    assert (private_root / "claim.json").exists()
    assert json.loads((private_root / "terminal-failure.json").read_bytes())["status"] == (
        "FAIL-CONSUMED-NO-RETRY"
    )


@pytest.mark.parametrize("failed_key", ["terminal-failure.json", "qualification-receipt.json"])
def test_post_claim_terminal_persistence_failure_uses_claim_fallback(
    failed_key: str,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _stub_execution(monkeypatch)
    original_append = authority._append_persistent_evidence
    responses = (
        [raw_contract.RawResponse(401, b'{"error":"bounded"}')]
        if failed_key == "terminal-failure.json"
        else _responses()
    )

    def append(root_descriptor: int, key: str, payload: bytes) -> None:
        if key == failed_key:
            raise OSError("simulated terminal persistence failure")
        original_append(root_descriptor, key, payload)

    monkeypatch.setattr(authority, "_append_persistent_evidence", append)

    with pytest.raises(
        authority.Program009PostClaimPersistenceError,
        match="claim fallback seals FAIL-CONSUMED-NO-RETRY",
    ):
        authority._execute_mock_qualification(
            tmp_path,
            "a" * 64,
            environ=_credentials(),
            transport=authority.MockBarsTransport(responses),
        )

    claim = json.loads((tmp_path / authority.PRIVATE_ROOT / "claim.json").read_bytes())
    assert claim["terminal_fallback"]["status"] == "FAIL-CONSUMED-NO-RETRY"
    assert claim["terminal_fallback"]["retry_allowed"] is False


def test_authority_proposal_and_review_validate_when_committed() -> None:
    controls = authority.validate_proposal_chain(_REPOSITORY)

    assert controls["proposal"]["status"] == authority.READY_STATUS
    assert controls["review"]["verdict"] == "PASS"
    assert controls["review"]["findings"] == []


def test_terminal_failure_revokes_before_credentials_or_private_state(
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
        with pytest.raises(authority.Program009AuthorityError, match="terminally revoked"):
            operation()

    assert credential_reads == []
    assert private_root_opens == []
