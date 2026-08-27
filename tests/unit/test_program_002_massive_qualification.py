from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

import pytest
from pytest import CaptureFixture, MonkeyPatch

import systematic_trading_lab.program_002_massive_qualification as massive
from systematic_trading_lab.config import non_broker_subprocess_environment
from systematic_trading_lab.program_002_acquisition import HttpPage
from systematic_trading_lab.program_002_credentials import reject_research_credentials
from systematic_trading_lab.storage import StorageLayout

_REPOSITORY = Path(__file__).resolve().parents[2]
_KEY = "synthetic-massive-key"


def _plan() -> massive.MassiveSourcePlan:
    return massive.load_massive_source_plan(_REPOSITORY)


def _chains() -> tuple[massive.MassiveRequestChain, ...]:
    return massive.build_massive_request_plan(_plan())


def _pass_gates() -> dict[str, Any]:
    return {
        "status": "PASS",
        "adjustment_semantics": {"verdict": "pass", "requested_adjusted_flag": False},
        "aggregate_eligibility_contract": {"verdict": "pass"},
        "licensing_and_retention": {"verdict": "pass"},
    }


def _adjustment_proof() -> dict[str, Any]:
    return {
        "source_sha256": "1" * 64,
        "adjusted_request": False,
        "split_price": True,
        "split_volume": True,
        "cash_dividends": True,
        "stock_dividends": True,
        "spin_offs": True,
        "historical_revisions": True,
        "point_in_time": True,
        "exact_program_002_match": True,
    }


def _trade_contract_payload() -> dict[str, Any]:
    return {
        "source_sha256": "2" * 64,
        "eligible_conditions": [0],
        "ineligible_conditions": [1],
        "eligible_corrections": [0],
        "ineligible_corrections": [1],
        "equal_timestamp_order": ["sip_timestamp", "sequence_number", "id"],
        "duplicate_policy": "reject-duplicate-exchange-trf-id",
        "cancellation_policy": "eligible-correction-codes-only",
        "late_report_policy": "condition-code-contract",
        "bucket_policy": "xnys-regular-session-five-minute-utc-bar-open",
        "equality_policy": "exact-decimal-ohlcv",
    }


def _authority() -> massive.QualificationAuthority:
    payload = {
        "attempt_id": "synthetic-massive-attempt-v1",
        "credential_identity_hash": hashlib.sha256(_KEY.encode()).hexdigest(),
        "adjustment_proof": _adjustment_proof(),
        "trade_audit_contract": _trade_contract_payload(),
    }
    return massive.QualificationAuthority(
        Path("authority.json"),
        "a" * 64,
        "b" * 64,
        payload,
        Path("review.json"),
        "c" * 64,
        "d" * 64,
        {},
    )


def _provider_body(
    chain: massive.MassiveRequestChain,
    records: list[dict[str, Any]],
    *,
    next_url: str | None = None,
    request_id: str = "synthetic-request",
) -> bytes:
    payload: dict[str, Any] = {
        "status": "OK",
        "request_id": request_id,
        "results": {"events": records} if chain.kind == "ticker-event" else records,
    }
    if chain.kind == "aggregate":
        payload.update({"ticker": chain.symbol, "adjusted": False})
    if next_url is not None:
        payload["next_url"] = next_url
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


def _raw_page(
    chain: massive.MassiveRequestChain,
    records: list[dict[str, Any]],
) -> massive.MassiveRawPage:
    body = _provider_body(chain, records)
    return massive.MassiveRawPage(
        chain.url,
        body,
        hashlib.sha256(body).hexdigest(),
        "synthetic-request",
    )


def _acquired(
    chain: massive.MassiveRequestChain,
    records: list[dict[str, Any]],
) -> massive.AcquiredMassiveChain:
    return massive.AcquiredMassiveChain(chain, (_raw_page(chain, records),), tuple(records))


def _aggregate_records(chain: massive.MassiveRequestChain) -> list[dict[str, Any]]:
    return [
        {"t": timestamp, "o": "100", "h": "100", "l": "100", "c": "100", "v": 1}
        for timestamp in chain.expected_timestamps
    ]


def _quote_records(
    chain: massive.MassiveRequestChain,
    eligible_count: int = 60,
) -> list[dict[str, Any]]:
    first = int(chain.params["timestamp.gte"]) + 5_000_000_000
    return [
        {
            "sip_timestamp": first + offset * 1_000_000_000 - 1,
            "participant_timestamp": first + offset * 1_000_000_000 - 2,
            "bid_price": "100" if offset < eligible_count else "0",
            "ask_price": "101",
            "bid_size": "10",
            "ask_size": "11",
            "bid_exchange": 11,
            "ask_exchange": 12,
        }
        for offset in range(60)
    ]


def _trade_records(chain: massive.MassiveRequestChain) -> list[dict[str, Any]]:
    assert chain.session_date is not None
    points = massive._session_bar_opens(date.fromisoformat(chain.session_date))
    return [
        {
            "sip_timestamp": massive._unix_ns(point) + 1,
            "price": "100",
            "size": 1,
            "conditions": [0],
            "correction": 0,
            "exchange": 11,
            "participant_timestamp": massive._unix_ns(point),
            "sequence_number": index,
            "id": f"trade-{index}",
        }
        for index, point in enumerate(points)
    ]


def test_frozen_request_plan_has_exact_scope_and_bounds() -> None:
    plan = _plan()
    chains = massive.build_massive_request_plan(plan)
    preflight = massive.credential_free_request_preflight(plan, chains)

    assert len(chains) == 630
    assert preflight["request_chain_counts"] == {
        "aggregate": 117,
        "dividend": 13,
        "quote": 468,
        "split": 13,
        "ticker-event": 13,
        "trade": 6,
    }
    assert preflight["request_plan_fingerprint"] == (
        "c82aa0a72f362ad6ab60161973a77e09e4831be34e1d1bc63cd4a5939636987b"
    )
    aggregate = next(chain for chain in chains if chain.kind == "aggregate")
    aggregate_query = parse_qs(urlparse(aggregate.url).query)
    assert aggregate.params["adjusted"] == "false"
    assert aggregate_query["sort"] == ["asc"]
    assert str(aggregate.expected_timestamps[0]) in aggregate.endpoint
    assert str(aggregate.expected_timestamps[-1]) in aggregate.endpoint
    assert len(aggregate.expected_timestamps) == 78
    early_close = next(
        chain
        for chain in chains
        if chain.kind == "aggregate" and chain.session_date == "2022-11-25"
    )
    assert len(early_close.expected_timestamps) == 42
    quote = next(chain for chain in chains if chain.kind == "quote")
    assert int(quote.params["timestamp.lt"]) - int(quote.params["timestamp.gte"]) == 65_000_000_000
    assert all("apiKey" not in parse_qs(urlparse(chain.url).query) for chain in chains)


def test_pagination_rejects_bad_next_urls_duplicate_pages_and_malformed_bodies() -> None:
    chain = next(item for item in _chains() if item.kind == "split")
    next_url = f"{chain.url}&cursor=one"
    pages = iter(
        (
            HttpPage(200, _provider_body(chain, [], next_url=next_url, request_id="one"), {}),
            HttpPage(200, _provider_body(chain, [], request_id="two"), {}),
        )
    )
    budget = massive.QualificationBudget()
    acquired = massive.acquire_massive_chain(
        chain, lambda _: next(pages), budget, pace=lambda: None
    )
    assert len(acquired.pages) == 2
    assert (budget.request_chains, budget.pages) == (1, 2)

    for bad_url in (
        "https://example.com/stocks/v1/splits?cursor=one",
        f"{chain.endpoint}?cursor=one&cursor=two",
        f"{chain.endpoint}?ticker=OTHER&cursor=one",
    ):

        def bad_transport(_: str, selected_url: str = bad_url) -> HttpPage:
            return HttpPage(200, _provider_body(chain, [], next_url=selected_url), {})

        with pytest.raises(massive.MassiveQualificationError, match="next_url"):
            massive.acquire_massive_chain(
                chain,
                bad_transport,
                massive.QualificationBudget(),
                pace=lambda: None,
            )

    repeated_pages = iter(
        (
            HttpPage(200, _provider_body(chain, [], next_url=next_url, request_id="one"), {}),
            HttpPage(200, _provider_body(chain, [], next_url=next_url, request_id="two"), {}),
        )
    )
    with pytest.raises(massive.MassiveQualificationError, match="repeated"):
        massive.acquire_massive_chain(
            chain,
            lambda _: next(repeated_pages),
            massive.QualificationBudget(),
            pace=lambda: None,
        )

    duplicate = _provider_body(chain, [], next_url=next_url)
    with pytest.raises(massive.MassiveQualificationError, match="duplicate") as duplicate_error:
        massive.acquire_massive_chain(
            chain,
            lambda _: HttpPage(200, duplicate, {}),
            massive.QualificationBudget(),
            pace=lambda: None,
        )
    assert len(duplicate_error.value.partial_pages) == 2  # type: ignore[attr-defined]

    with pytest.raises(massive.MassiveQualificationError, match="malformed") as malformed:
        massive.acquire_massive_chain(
            chain,
            lambda _: HttpPage(200, b"{", {}),
            massive.QualificationBudget(),
            pace=lambda: None,
        )
    assert malformed.value.partial_pages[0].body == b"{"  # type: ignore[attr-defined]


def test_global_chain_page_and_byte_budgets_are_hard() -> None:
    chain = _chains()[0]
    with pytest.raises(massive.MassiveQualificationError, match="chain ceiling"):
        massive.QualificationBudget(maximum_chains=0).begin(chain)

    page_budget = massive.QualificationBudget(maximum_pages=1)
    page_budget.add_page(b"one")
    with pytest.raises(massive.MassiveQualificationError, match="5000-page"):
        page_budget.add_page(b"two")

    byte_budget = massive.QualificationBudget(maximum_bytes=2)
    with pytest.raises(massive.MassiveQualificationError, match="5-GiB"):
        byte_budget.add_page(b"123")
    with pytest.raises(massive.MassiveQualificationError, match="bounded page"):
        massive.QualificationBudget().add_page_size(massive._MAX_PAGE_BYTES + 1)


def test_retry_classification_counts_every_http_response() -> None:
    chain = next(item for item in _chains() if item.kind == "split")
    accepted = _provider_body(chain, [])
    responses = iter((HttpPage(429, b"rate", {"Retry-After": "0"}), HttpPage(200, accepted, {})))
    waits: list[float] = []
    budget = massive.QualificationBudget()
    massive.acquire_massive_chain(
        chain,
        lambda _: next(responses),
        budget,
        pace=lambda: None,
        retry_wait=waits.append,
        wall_clock=lambda: 0.0,
    )
    assert budget.pages == 2
    assert budget.response_bytes == len(b"rate") + len(accepted)
    assert waits == [1.0]

    rejected_budget = massive.QualificationBudget()
    with pytest.raises(massive.MassiveQualificationError, match="nonretryable") as rejected:
        massive.acquire_massive_chain(
            chain,
            lambda _: HttpPage(401, b"denied", {}),
            rejected_budget,
            pace=lambda: None,
        )
    assert rejected_budget.pages == 1
    assert rejected.value.http_attempts[-1]["disposition"] == "rejected"  # type: ignore[attr-defined]


def test_raw_chain_storage_is_create_only_reloadable_and_tamper_evident(tmp_path: Path) -> None:
    chain = next(item for item in _chains() if item.kind == "split")
    layout = StorageLayout(tmp_path)
    attempt_id = "synthetic-massive-attempt-v1"
    acquired = massive.acquire_massive_chain(
        chain,
        lambda _: HttpPage(200, _provider_body(chain, [], request_id="one"), {}),
        massive.QualificationBudget(),
        pace=lambda: None,
    )
    identity, created = massive.store_massive_chain(layout, attempt_id, acquired)
    assert created is True
    assert massive.load_massive_chain(layout, attempt_id, chain) == acquired
    assert massive.store_massive_chain(layout, attempt_id, acquired) == (identity, False)

    conflicting = massive.acquire_massive_chain(
        chain,
        lambda _: HttpPage(200, _provider_body(chain, [], request_id="two"), {}),
        massive.QualificationBudget(),
        pace=lambda: None,
    )
    with pytest.raises(massive.MassiveQualificationError, match="conflicts"):
        massive.store_massive_chain(layout, attempt_id, conflicting)

    raw_page = layout.dataset(identity) / "page-00001.json"
    raw_page.write_bytes(raw_page.read_bytes() + b" ")
    with pytest.raises(massive.MassiveQualificationError, match="page hash"):
        massive.load_massive_chain(layout, attempt_id, chain)


def test_aggregate_grid_is_exact_and_missing_rows_fail() -> None:
    chain = next(item for item in _chains() if item.kind == "aggregate")
    rows = _aggregate_records(chain)
    acquired = massive.acquire_massive_chain(
        chain,
        lambda _: HttpPage(200, _provider_body(chain, rows), {}),
        massive.QualificationBudget(),
        pace=lambda: None,
    )
    assert len(massive.validate_aggregate_chain(acquired)) == 78

    with pytest.raises(massive.MassiveQualificationError, match="incomplete"):
        massive.acquire_massive_chain(
            chain,
            lambda _: HttpPage(200, _provider_body(chain, rows[:-1]), {}),
            massive.QualificationBudget(),
            pace=lambda: None,
        )


def test_quote_sampling_enforces_the_57_of_60_gate() -> None:
    chain = next(item for item in _chains() if item.kind == "quote")
    assert (
        massive.eligible_quote_observation_count(_acquired(chain, _quote_records(chain, 57))) == 57
    )
    assert (
        massive.eligible_quote_observation_count(_acquired(chain, _quote_records(chain, 56))) == 56
    )


def test_raw_trade_audit_requires_exact_equality_and_never_returns_canonical_bars() -> None:
    chains = _chains()
    trade = next(item for item in chains if item.kind == "trade")
    aggregate = next(
        item
        for item in chains
        if item.kind == "aggregate"
        and item.symbol == trade.symbol
        and item.session_date == trade.session_date
    )
    provider = massive.validate_aggregate_chain(_acquired(aggregate, _aggregate_records(aggregate)))
    contract = massive.trade_audit_contract_from_authority(_authority())
    result = massive.audit_trade_chain(_acquired(trade, _trade_records(trade)), provider, contract)
    assert result["eligible_bucket_count"] == 78
    assert result["matches_provider_aggregates"] is True
    assert result["canonical_admission_allowed"] is False

    changed = [dict(item) for item in provider]
    changed[0]["close"] = Decimal("101")
    with pytest.raises(massive.MassiveQualificationError, match="differs"):
        massive.audit_trade_chain(_acquired(trade, _trade_records(trade)), changed, contract)

    with pytest.raises(massive.MassiveQualificationError, match="bucket set differs"):
        massive.audit_trade_chain(_acquired(trade, _trade_records(trade)[:-1]), provider, contract)


def test_adjustment_and_corporate_action_contracts_fail_closed() -> None:
    massive.require_exact_adjustment_proof(_adjustment_proof())
    incomplete = _adjustment_proof()
    incomplete["spin_offs"] = False
    with pytest.raises(massive.MassiveQualificationError, match="adjustment contract"):
        massive.require_exact_adjustment_proof(incomplete)

    split = next(item for item in _chains() if item.kind == "split")
    valid = {
        "ticker": split.symbol,
        "execution_date": "2021-01-04",
        "id": "split-1",
        "historical_adjustment_factor": "2",
        "adjustment_type": "forward_split",
        "split_from": 1,
        "split_to": 2,
    }
    assert massive.validate_corporate_action_chain(_acquired(split, [valid]))["record_count"] == 1
    invalid = {**valid, "ticker": "OTHER"}
    with pytest.raises(massive.MassiveQualificationError, match="ticker differs"):
        massive.validate_corporate_action_chain(_acquired(split, [invalid]))


def test_full_synthetic_sample_executes_once_and_publishes_only_structural_evidence(
    tmp_path: Path,
) -> None:
    plan = _plan()
    chains = massive.build_massive_request_plan(plan)
    by_url = {chain.url: chain for chain in chains}
    seen: list[str] = []

    def transport(request: Request) -> HttpPage:
        assert request.get_header("Authorization") == f"Bearer {_KEY}"
        assert _KEY not in request.full_url
        chain = by_url[request.full_url]
        if chain.kind == "aggregate":
            records = _aggregate_records(chain)
        elif chain.kind == "trade":
            records = _trade_records(chain)
        elif chain.kind == "quote":
            records = _quote_records(chain)
        else:
            records = []
        seen.append(request.full_url)
        return HttpPage(200, _provider_body(chain, records), {})

    layout = StorageLayout(tmp_path)
    receipt = massive.execute_massive_source_qualification(
        plan,
        _pass_gates(),
        _authority(),
        layout,
        environ={"PROGRAM_002_MASSIVE_API_KEY": _KEY},
        request_transport=transport,
        pace=lambda: None,
    )
    assert len(seen) == 630
    assert len(tuple(layout.datasets.iterdir())) == 630
    assert receipt["source_qualification"] == "PASS"
    assert receipt["request_chains"] == 630
    assert receipt["http_pages"] == 630
    assert receipt["credential_loads"] == 1
    assert receipt["authority_consumed"] is True
    assert receipt["one_use_attempt_terminal"] is True
    assert receipt["aggregate_rows"] == 8_658
    assert receipt["quote_grid_observations"] == 28_080
    assert receipt["eligible_quote_observations"] == 28_080
    assert len(receipt["raw_trade_audits"]) == 6
    assert len(receipt["corporate_action_chains"]) == 39
    assert all(receipt["known_mdy_coordinates"].values())
    assert receipt["zero_strategy_returns_generated"] is True
    assert receipt["controlled_or_protected_state_touched"] is False
    assert not any(receipt["authority"].values())
    report = layout.reports / "program-002" / "massive-qualification"
    assert (report / "receipt.json").exists()
    assert (report / "outcome.json").exists()

    with pytest.raises(massive.MassiveQualificationError, match="terminal"):
        massive.execute_massive_source_qualification(
            plan,
            _pass_gates(),
            _authority(),
            layout,
            environ={"PROGRAM_002_MASSIVE_API_KEY": _KEY},
            request_transport=lambda _: (_ for _ in ()).throw(AssertionError("retried")),
            pace=lambda: None,
        )


def test_failed_transport_is_quarantined_sealed_and_never_retried(tmp_path: Path) -> None:
    layout = StorageLayout(tmp_path)
    calls = 0

    def malformed(_: Request) -> HttpPage:
        nonlocal calls
        calls += 1
        return HttpPage(200, b"{", {})

    with pytest.raises(massive.MassiveQualificationError, match="malformed"):
        massive.execute_massive_source_qualification(
            _plan(),
            _pass_gates(),
            _authority(),
            layout,
            environ={"PROGRAM_002_MASSIVE_API_KEY": _KEY},
            request_transport=malformed,
            pace=lambda: None,
        )
    assert calls == 1
    report = layout.reports / "program-002" / "massive-qualification"
    receipt = massive._load_exact_record(report / "receipt.json", "synthetic receipt")
    assert receipt["source_qualification"] == "FAIL"
    assert receipt["authority_consumed"] is True
    assert receipt["http_pages"] == 1
    assert receipt["zero_strategy_returns_generated"] is True
    assert next(layout.quarantine.glob("*.json"))

    with pytest.raises(massive.MassiveQualificationError, match="terminal"):
        massive.execute_massive_source_qualification(
            _plan(),
            _pass_gates(),
            _authority(),
            layout,
            environ={"PROGRAM_002_MASSIVE_API_KEY": _KEY},
            request_transport=malformed,
            pace=lambda: None,
        )
    assert calls == 1


def test_controlled_dates_are_rejected_before_transport() -> None:
    plan = _plan()
    chains = list(massive.build_massive_request_plan(plan))
    chains[0] = replace(chains[0], session_date="2027-04-16")
    with pytest.raises(massive.MassiveQualificationError, match="frozen scope"):
        massive.credential_free_request_preflight(plan, chains)


def test_reviewed_implementation_must_be_clean_synchronized_main(tmp_path: Path) -> None:
    environment = non_broker_subprocess_environment()
    environment.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})

    def git(*arguments: str) -> str:
        return subprocess.run(
            ("git", "-C", str(tmp_path), *arguments),
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.name", "Massive Qualification Test")
    git("config", "user.email", "massive-qualification@example.invalid")
    files: list[dict[str, str]] = []
    for relative in massive._IMPLEMENTATION_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{relative}\n", encoding="utf-8")
        files.append({"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    git("add", ".")
    git("commit", "-m", "reviewed implementation")
    source_commit = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/main", source_commit)
    implementation = {"source_commit": source_commit, "files": files}

    massive._validate_implementation_identity(tmp_path, implementation)
    massive._repository_qualification_preflight(tmp_path, implementation)
    (tmp_path / massive._IMPLEMENTATION_PATHS[0]).write_text("changed\n", encoding="utf-8")
    with pytest.raises(massive.MassiveQualificationError, match="clean synchronized main"):
        massive._repository_qualification_preflight(tmp_path, implementation)


def test_one_use_consumption_is_idempotent_and_terminal(tmp_path: Path) -> None:
    layout = StorageLayout(tmp_path)
    authority = _authority()
    first, second = _chains()[:2]
    with massive.OneUseAttempt(layout, authority) as attempt:
        attempt.consume(first)
        attempt.consume(second)
        assert attempt.consumed is True
        attempt.finish("failed-no-retry", {"reason": "synthetic"})
    with (
        pytest.raises(massive.MassiveQualificationError, match="terminal"),
        massive.OneUseAttempt(layout, authority),
    ):
        pass


def test_gate_failure_precedes_authority_and_environment_access(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        massive,
        "load_qualification_authority",
        lambda *_: (_ for _ in ()).throw(AssertionError("authority accessed")),
    )
    monkeypatch.setattr(
        massive,
        "execute_massive_source_qualification",
        lambda *_: (_ for _ in ()).throw(AssertionError("environment accessed")),
    )
    status = massive.main(
        (
            "qualify-massive",
            "--repository",
            str(_REPOSITORY),
            "--data-home",
            str(tmp_path),
        )
    )
    assert status == os.EX_USAGE
    assert "gates have not passed" in capsys.readouterr().err
    assert not any(tmp_path.iterdir())


def test_client_uses_an_authorization_header_and_never_puts_the_key_in_the_url() -> None:
    chain = next(item for item in _chains() if item.kind == "split")
    seen: list[Request] = []

    def transport(request: Request) -> HttpPage:
        seen.append(request)
        return HttpPage(200, _provider_body(chain, []), {})

    client = massive.MassiveHttpClient(_KEY, (chain,), transport)
    client.get(chain, chain.url)
    assert len(seen) == 1
    assert seen[0].get_header("Authorization") == f"Bearer {_KEY}"
    assert _KEY not in seen[0].full_url


def test_subprocess_and_research_boundaries_strip_massive_credentials() -> None:
    assert non_broker_subprocess_environment(
        {"PATH": "/bin", "PROGRAM_002_MASSIVE_API_KEY": "secret"}
    ) == {"PATH": "/bin"}
    with pytest.raises(ValueError, match="forbids credentials"):
        reject_research_credentials({"PROGRAM_002_MASSIVE_API_KEY": "secret"})
