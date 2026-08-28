from __future__ import annotations

import importlib.util
import json
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest
from pytest import CaptureFixture, MonkeyPatch

import systematic_trading_lab.intraday_fed_policy_absorption_001_cli as dispatcher
import systematic_trading_lab.program_005_alpaca as program_005
from systematic_trading_lab.calendar import expected_bar_timestamps, expected_sessions
from systematic_trading_lab.config import non_broker_subprocess_environment
from systematic_trading_lab.domain import Timeframe
from systematic_trading_lab.fingerprints import canonical_json, fingerprint
from systematic_trading_lab.program_002_credentials import reject_research_credentials

_REPOSITORY = Path(__file__).resolve().parents[2]
_SOURCE_COMMIT = "a" * 40


def _bundle() -> program_005.ContractBundle:
    return program_005.load_contract(_REPOSITORY)


def _chain(adjustment: str = "raw") -> program_005.RequestChain:
    suffix = "raw" if adjustment == "raw" else "split-spin-off"
    return program_005.RequestChain(
        f"synthetic-2020-07-27--{suffix}",
        "synthetic-2020-07-27",
        adjustment,
        datetime(2020, 7, 27, 13, 30, tzinfo=UTC),
        datetime(2020, 7, 27, 19, 55, tzinfo=UTC),
        tuple(_bundle().public_contract["symbols"]),
        (date(2020, 7, 27),),
        2,
    )


def _bar(
    timestamp: datetime,
    *,
    factor: Decimal = Decimal(1),
    volume_factor: Decimal = Decimal(1),
) -> dict[str, Any]:
    base = Decimal("100")
    return {
        "t": timestamp.isoformat().replace("+00:00", "Z"),
        "o": float(base * factor),
        "h": float((base + 2) * factor),
        "l": float((base - 1) * factor),
        "c": float((base + 1) * factor),
        "v": float(Decimal("1000") * volume_factor),
        "n": 10,
        "vw": float((base + Decimal("0.5")) * factor),
    }


def _body(
    chain: program_005.RequestChain,
    *,
    next_token: str | None = None,
    duplicate: bool = False,
    malformed_timestamp: bool = False,
    timestamp_parity: int | None = None,
) -> bytes:
    rows: dict[str, list[dict[str, Any]]] = {}
    split_symbols = {"XLB", "XLE", "XLK", "XLU", "XLY"}
    for symbol in chain.symbols:
        factor = (
            Decimal("0.5")
            if chain.adjustment == "split,spin-off" and symbol in split_symbols
            else Decimal(1)
        )
        volume_factor = Decimal(1) / factor
        timestamps = expected_bar_timestamps(chain.start, chain.end, Timeframe.FIVE_MINUTES)
        if timestamp_parity is not None:
            timestamps = timestamps[timestamp_parity::2]
        rows[symbol] = [
            _bar(timestamp, factor=factor, volume_factor=volume_factor) for timestamp in timestamps
        ]
    if duplicate:
        rows[chain.symbols[0]].append(dict(rows[chain.symbols[0]][0]))
    if malformed_timestamp:
        rows[chain.symbols[0]][0]["t"] = "2020-07-27T13:31:00Z"
    return json.dumps({"bars": rows, "next_page_token": next_token}).encode()


def _http(body: bytes, final_url: str | None = None, status: int = 200) -> program_005.HttpPage:
    return program_005.HttpPage(
        status,
        body,
        final_url or "https://data.alpaca.markets/v2/stocks/bars",
        {},
    )


def _store_complete_pair(root: Path) -> tuple[program_005.RequestChain, program_005.RequestChain]:
    raw = _chain("raw")
    analytical = _chain("split,spin-off")
    for chain in (raw, analytical):
        body = _body(chain)

        def transport(request: Request, response_body: bytes = body) -> program_005.HttpPage:
            return _http(response_body, request.full_url)

        client = program_005.AlpacaBarsClient(
            "synthetic-key",
            "synthetic-secret",
            transport=transport,
            pace=lambda: None,
        )
        program_005.acquire_chain(
            chain,
            program_005._chain_root(root, "qualification", chain),
            client,
            program_005.AcquisitionBudget(2, 10 * 1024**2),
            source_commit=_SOURCE_COMMIT,
            now=lambda: datetime(2026, 8, 28, tzinfo=UTC),
        )
    return raw, analytical


def test_contract_and_request_plans_are_exact_and_deterministic() -> None:
    qualification = program_005.credential_free_preflight(_REPOSITORY, "qualification")
    full = program_005.credential_free_preflight(_REPOSITORY, "full")
    chains = program_005.build_request_plan(_bundle(), "qualification")
    first = chains[0]
    parsed = urlsplit(first.url())
    parameters = parse_qs(parsed.query)

    assert qualification["logical_chain_count"] == 26
    assert qualification["expected_http_responses_to_acquire"] == 28
    assert qualification["maximum_http_responses_to_acquire"] == 60
    assert qualification["maximum_downloaded_bytes"] == 64 * 1024**2
    assert full["logical_chain_count"] == 3044
    assert full["reused_qualification_chain_count"] == 26
    assert full["request_chains_to_acquire"] == 3018
    assert full["expected_http_responses_to_acquire"] == 3018
    assert full["maximum_http_responses_to_acquire"] == 12072
    assert (parsed.scheme, parsed.netloc, parsed.path) == (
        "https",
        "data.alpaca.markets",
        "/v2/stocks/bars",
    )
    assert parameters == {
        "symbols": ["IWM,MDY,SPY,XLB,XLE,XLF,XLI,XLK,XLP,XLRE,XLU,XLV,XLY"],
        "start": ["2020-07-27T13:30:00Z"],
        "end": ["2020-07-27T19:55:00Z"],
        "feed": ["sip"],
        "timeframe": ["5Min"],
        "adjustment": ["raw"],
        "sort": ["asc"],
        "limit": ["10000"],
        "asof": ["2026-07-31"],
    }
    assert qualification == program_005.credential_free_preflight(_REPOSITORY, "qualification")


def test_transport_is_get_only_single_attempt_redirect_free_and_classified() -> None:
    chain = _chain()
    seen: list[Request] = []

    def success(request: Request) -> program_005.HttpPage:
        seen.append(request)
        return _http(_body(chain), request.full_url)

    client = program_005.AlpacaBarsClient(
        "synthetic-key", "synthetic-secret", transport=success, pace=lambda: None
    )
    client.get(chain)
    assert len(seen) == 1
    assert seen[0].method == "GET"
    assert seen[0].get_header("Apca-api-key-id") == "synthetic-key"
    assert seen[0].get_header("Apca-api-secret-key") == "synthetic-secret"
    assert "synthetic" not in seen[0].full_url

    for status, retryable in ((429, True), (401, False)):

        def failed_transport(
            request: Request, response_status: int = status
        ) -> program_005.HttpPage:
            return _http(b'{"message":"redacted"}', request.full_url, response_status)

        failed = program_005.AlpacaBarsClient(
            "key",
            "secret",
            transport=failed_transport,
            pace=lambda: None,
        )
        with pytest.raises(program_005.Program005TransportError) as caught:
            failed.get(chain)
        assert caught.value.status == status
        assert caught.value.retryable is retryable

    disconnected = program_005.AlpacaBarsClient(
        "key",
        "secret",
        transport=lambda _: (_ for _ in ()).throw(ConnectionError("private detail")),
        pace=lambda: None,
    )
    with pytest.raises(program_005.Program005TransportError, match="disconnected") as caught:
        disconnected.get(chain)
    assert caught.value.retryable is True
    assert "private detail" not in str(caught.value)

    redirected = program_005.AlpacaBarsClient(
        "key",
        "secret",
        transport=lambda _: _http(_body(chain), "https://example.com/v2/stocks/bars"),
        pace=lambda: None,
    )
    with pytest.raises(program_005.Program005TransportError, match="redirected"):
        redirected.get(chain)
    with pytest.raises(program_005.Program005Error, match="outside"):
        program_005._validate_request_url("https://paper-api.alpaca.markets/v2/orders", chain)


def test_page_parser_rejects_duplicate_malformed_and_foreign_records() -> None:
    chain = _chain()
    bars, token = program_005.parse_bars_page(_body(chain), chain)
    assert len(bars) == 13 * 78
    assert token is None
    assert bars[0].trade_count == 10
    assert bars[0].vwap == Decimal("100.5")

    with pytest.raises(program_005.Program005Error, match="duplicate coordinate"):
        program_005.parse_bars_page(_body(chain, duplicate=True), chain)
    with pytest.raises(program_005.Program005Error, match="five-minute"):
        program_005.parse_bars_page(_body(chain, malformed_timestamp=True), chain)
    payload = json.loads(_body(chain))
    payload["bars"]["QQQ"] = payload["bars"].pop("IWM")
    with pytest.raises(program_005.Program005Error, match="foreign symbol"):
        program_005.parse_bars_page(json.dumps(payload).encode(), chain)
    payload = json.loads(_body(chain))
    payload.pop("next_page_token")
    with pytest.raises(program_005.Program005Error, match="omits next_page_token"):
        program_005.parse_bars_page(json.dumps(payload).encode(), chain)


def test_restart_uses_stored_page_and_rejects_repeated_token(tmp_path: Path) -> None:
    chain = _chain()
    calls: list[str | None] = []

    def interrupted(request: Request) -> program_005.HttpPage:
        token = parse_qs(urlsplit(request.full_url).query).get("page_token", [None])[0]
        calls.append(token)
        if token is None:
            page_marker = "page-two"
            return _http(_body(chain, next_token=page_marker, timestamp_parity=0), request.full_url)
        raise ConnectionError("synthetic disconnect")

    budget = program_005.AcquisitionBudget(2, 20 * 1024**2)
    client = program_005.AlpacaBarsClient("key", "secret", transport=interrupted, pace=lambda: None)
    with pytest.raises(program_005.Program005TransportError):
        program_005.acquire_chain(
            chain, tmp_path / "chain", client, budget, source_commit=_SOURCE_COMMIT
        )
    assert calls == [None, "page-two"]
    assert (tmp_path / "chain" / "pages" / "00001" / "body.json").exists()

    resumed_calls: list[str | None] = []

    def resumed(request: Request) -> program_005.HttpPage:
        token = parse_qs(urlsplit(request.full_url).query).get("page_token", [None])[0]
        resumed_calls.append(token)
        return _http(_body(chain, timestamp_parity=1), request.full_url)

    rows = program_005.acquire_chain(
        chain,
        tmp_path / "chain",
        program_005.AlpacaBarsClient("key", "secret", transport=resumed, pace=lambda: None),
        program_005.AcquisitionBudget(2, 20 * 1024**2),
        source_commit=_SOURCE_COMMIT,
    )
    assert resumed_calls == ["page-two"]
    assert len(rows) == 13 * 78

    repeated = _chain()
    repeated_marker = "same"
    with pytest.raises(program_005.Program005Error, match="repeated"):
        program_005.acquire_chain(
            repeated,
            tmp_path / "repeated",
            program_005.AlpacaBarsClient(
                "key",
                "secret",
                transport=lambda request: _http(
                    _body(repeated, next_token=repeated_marker), request.full_url
                ),
                pace=lambda: None,
            ),
            program_005.AcquisitionBudget(2, 20 * 1024**2),
            source_commit=_SOURCE_COMMIT,
        )


def test_action_ledger_enforces_split_reciprocal_volume_dividend_and_spin_off() -> None:
    bundle = _bundle()
    raw_chain = _chain("raw")
    analytical_chain = _chain("split,spin-off")
    raw, _ = program_005.parse_bars_page(_body(raw_chain), raw_chain)
    analytical, _ = program_005.parse_bars_page(_body(analytical_chain), analytical_chain)
    observations = program_005.validate_action_pair(raw, analytical, bundle.action_ledger)
    assert {item["analytical_price_factor"] for item in observations} == {"0.5", "1"}
    with pytest.raises(program_005.Program005Error, match="coordinate sets differ"):
        program_005.validate_action_pair(raw, analytical[:-1], bundle.action_ledger)

    iwm_raw = next(bar for bar in raw if bar.symbol == "IWM")
    assert (
        program_005.validate_action_pair([iwm_raw], [iwm_raw], bundle.action_ledger)[0][
            "analytical_price_factor"
        ]
        == "1"
    )
    non_unit = program_005.CanonicalBar(
        iwm_raw.timestamp,
        iwm_raw.symbol,
        iwm_raw.open / 2,
        iwm_raw.high / 2,
        iwm_raw.low / 2,
        iwm_raw.close / 2,
        iwm_raw.volume * 2,
    )
    with pytest.raises(program_005.Program005Error, match="absent from the frozen ledger"):
        program_005.validate_action_pair([iwm_raw], [non_unit], bundle.action_ledger)
    broken_volume = program_005.CanonicalBar(
        iwm_raw.timestamp,
        iwm_raw.symbol,
        iwm_raw.open,
        iwm_raw.high,
        iwm_raw.low,
        iwm_raw.close,
        iwm_raw.volume * 2,
    )
    with pytest.raises(program_005.Program005Error, match="not reciprocal"):
        program_005.validate_action_pair([iwm_raw], [broken_volume], bundle.action_ledger)


def test_missingness_quarantine_capacity_concentration_and_context_gates() -> None:
    plan = _bundle().plan
    policy = plan["missing_data_policy"]
    chronology = plan["chronology_and_protected_boundaries"]
    sessions = expected_sessions(
        datetime.fromisoformat(chronology["context_start"] + "T00:00:00+00:00"),
        datetime.fromisoformat(chronology["exposed_end"] + "T23:59:59+00:00"),
    )
    full = {
        session
        for session in sessions
        if session >= date.fromisoformat(chronology["discovery_start"])
        and len(
            expected_bar_timestamps(
                datetime.combine(session, datetime.min.time(), UTC),
                datetime.combine(session, datetime.max.time(), UTC),
                Timeframe.FIVE_MINUTES,
            )
        )
        == 78
    }
    quarantine = {
        date.fromisoformat(value) for value in policy["pre_exposed_design_quarantine"]["sessions"]
    }
    ordered = sorted(full)
    metrics: dict[date, dict[str, tuple[Decimal, Decimal, Decimal]]] = {}
    for index, session in enumerate(ordered):
        value = Decimal(index + 1)
        if session in quarantine:
            value = Decimal(len(ordered) // 2)
        metrics[session] = {
            "SPY": (value, value, value),
            "MDY": (value, value, value),
        }
    known: dict[date, set[str]] = {session: set() for session in quarantine}
    for coordinate in plan["source_qualification"]["known_mdy_coordinates"]:
        known[date.fromisoformat(coordinate.split("@", 1)[1][:10])].add(coordinate)
    unexpected = {
        date(2022, 3, 1): {"SPY@2022-03-01T15:00:00Z"},
        date(2024, 3, 1): {"XLE@2024-03-01T15:00:00Z"},
    }
    report = program_005.assess_missingness(plan, {**known, **unexpected}, metrics)
    assert report["expected_full_trade_eligible_sessions"] == 1499
    assert report["excluded_full_session_count"] == 7
    assert report["retained_full_trade_eligible_sessions"] == 1492
    assert report["admission_passed"] is True

    over_limit = program_005.assess_missingness(
        plan,
        {
            **known,
            **unexpected,
            date(2025, 3, 3): {"XLK@2025-03-03T15:00:00Z"},
        },
        metrics,
    )
    assert {"global-count", "unexpected-count"} <= set(over_limit["failures"])
    context_loss = program_005.assess_missingness(
        plan,
        {date(2020, 7, 1): {"SPY@2020-07-01T15:00:00Z"}},
        metrics,
    )
    assert "initial-context" in context_loss["failures"]

    inconsistent = json.loads(canonical_json(plan))
    fixed_contract = inconsistent["missing_data_policy"]["concentration_limits"][
        "pre_exposed_design_quarantine_concentration_contract"
    ]
    fixed_contract["minimum_retained_full_sessions_per_discovery_block"] = 10_000
    fixed_contract["post_quarantine_maximum_discovery_block_session_count_difference"] = 0
    fixed_contract["calendar_concentration_contract"][
        "minimum_retained_full_sessions_per_affected_month"
    ] = 10_000
    fixed_contract["calendar_concentration_contract"][
        "minimum_retained_full_sessions_per_affected_complete_calendar_year"
    ] = 10_000
    fixed_contract["clock_concentration_contract"]["rejection_count_at_one_clock"] = 1
    fixed_contract["clock_concentration_contract"][
        "maximum_fixed_sessions_missing_at_any_exact_strategy_clock"
    ] = 0
    inconsistent_report = program_005.assess_missingness(inconsistent, known, metrics)
    assert {
        "fixed-quarantine:block-retention",
        "fixed-quarantine:block-balance",
        "fixed-quarantine:calendar",
        "fixed-quarantine:clock",
    } <= set(inconsistent_report["failures"])
    assert inconsistent_report["admission_passed"] is False


def test_private_freeze_is_streamed_create_only_and_deterministic(tmp_path: Path) -> None:
    bundle = _bundle()
    manifests: list[dict[str, Any]] = []
    for name in ("first", "second"):
        root = tmp_path / name
        chains = _store_complete_pair(root)
        manifest = dict(
            program_005.freeze_dataset(
                bundle,
                "qualification",
                chains,
                root,
                source_commit=_SOURCE_COMMIT,
            )
        )
        manifests.append(manifest)
        dataset = root / "datasets" / str(manifest["dataset_id"])
        assert (dataset / "canonical-raw.jsonl").stat().st_size > 0
        assert (dataset / "canonical-analytical.jsonl").stat().st_size > 0
        assert manifest["authority"] == {
            "strategy_execution": False,
            "controlled_evaluation": False,
            "protected_holdout": False,
            "paper_execution": False,
            "broker_writes": False,
            "live_execution": False,
        }
        assert not {
            "raw_page_filenames",
            "raw_response_bytes",
            "request_page_metadata",
            "retrieval_timestamps",
            "private_storage_locations",
        } & program_005._recursive_keys(manifest)
    assert manifests[0] == manifests[1]
    with pytest.raises(program_005.Program005Error, match="already exists"):
        program_005.freeze_dataset(
            bundle,
            "qualification",
            _store_complete_pair(tmp_path / "first"),
            tmp_path / "first",
            source_commit=_SOURCE_COMMIT,
        )


def test_authority_precedes_credentials_and_research_credentials_fail_closed(
    tmp_path: Path,
) -> None:
    assert non_broker_subprocess_environment(
        {
            "PATH": "/bin",
            "PROGRAM_005_ALPACA_API_KEY_ID": "synthetic-key",
            "PROGRAM_005_ALPACA_API_SECRET_KEY": "synthetic-secret",
        }
    ) == {"PATH": "/bin"}
    with pytest.raises(ValueError, match="forbids credentials"):
        reject_research_credentials({"PROGRAM_005_ALPACA_API_KEY_ID": "synthetic-key"})
    with pytest.raises(program_005.Program005Error, match="authority"):
        program_005.execute_acquisition(
            _REPOSITORY,
            tmp_path / "private",
            "qualification",
            tmp_path / "absent-authority.json",
            environ={
                "PROGRAM_005_ALPACA_API_KEY_ID": "synthetic-key",
                "PROGRAM_005_ALPACA_API_SECRET_KEY": "synthetic-secret",
            },
            transport=lambda _: (_ for _ in ()).throw(AssertionError("transported")),
        )
    assert not (tmp_path / "private").exists()


def test_terminal_failure_and_unreviewed_full_scope_stop_before_credentials(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    private_root = tmp_path / ".trading-lab/program-005-free-alpaca"
    terminal = private_root / "qualification/terminal-transport-failure.json"
    terminal.parent.mkdir(parents=True)
    terminal.write_text("{}\n", encoding="utf-8")
    credential_reads: list[bool] = []

    def record_credentials(
        _environ: Mapping[str, str] | None = None,
    ) -> tuple[str, str]:
        credential_reads.append(True)
        return "key", "secret"

    monkeypatch.setattr(program_005, "load_contract", lambda _: object())
    monkeypatch.setattr(program_005, "build_request_plan", lambda *_: ())
    monkeypatch.setattr(
        program_005,
        "credential_free_preflight",
        lambda *_: {"request_plan_fingerprint": "synthetic-plan"},
    )
    monkeypatch.setattr(program_005, "load_active_authority", lambda *_: {})
    monkeypatch.setattr(program_005, "read_credentials", record_credentials)

    with pytest.raises(program_005.Program005Error, match="terminal transport failure"):
        program_005.execute_acquisition(
            tmp_path,
            private_root,
            "qualification",
            tmp_path / "authority.json",
        )
    with pytest.raises(program_005.Program005Error, match="qualification bytes"):
        program_005.execute_acquisition(
            tmp_path,
            private_root,
            "full",
            tmp_path / "authority.json",
        )
    assert credential_reads == []


def test_qualification_claim_and_failure_block_all_reentry_before_credentials(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    credential_reads: list[bool] = []

    def record_credentials(
        _environ: Mapping[str, str] | None = None,
    ) -> tuple[str, str]:
        credential_reads.append(True)
        return "key", "secret"

    monkeypatch.setattr(program_005, "load_contract", lambda _: object())
    monkeypatch.setattr(program_005, "build_request_plan", lambda *_: ())
    monkeypatch.setattr(
        program_005,
        "credential_free_preflight",
        lambda *_: {
            "request_plan_fingerprint": "synthetic-plan",
            "maximum_http_responses_to_acquire": 1,
            "maximum_downloaded_bytes": 1024,
        },
    )
    monkeypatch.setattr(program_005, "load_active_authority", lambda *_: {})
    monkeypatch.setattr(program_005, "read_credentials", record_credentials)
    monkeypatch.setattr(
        program_005,
        "freeze_dataset",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            program_005.Program005Error("synthetic parse failure")
        ),
    )

    private_root = tmp_path / ".trading-lab/program-005-free-alpaca"
    with pytest.raises(program_005.Program005Error, match="synthetic parse failure"):
        program_005.execute_acquisition(
            tmp_path,
            private_root,
            "qualification",
            tmp_path / "authority.json",
        )
    assert (private_root / "qualification/claim.json").exists()
    assert (private_root / "qualification/terminal-qualification-failure.json").exists()

    with pytest.raises(program_005.Program005Error, match="terminal qualification failure"):
        program_005.execute_acquisition(
            tmp_path,
            private_root,
            "qualification",
            tmp_path / "authority.json",
        )
    assert credential_reads == [True]

    interrupted_repository = tmp_path / "interrupted"
    interrupted_root = interrupted_repository / ".trading-lab/program-005-free-alpaca"
    claim = interrupted_root / "qualification/claim.json"
    claim.parent.mkdir(parents=True)
    claim.write_text("{}\n", encoding="utf-8")
    with pytest.raises(program_005.Program005Error, match="already claimed"):
        program_005.execute_acquisition(
            interrupted_repository,
            interrupted_root,
            "qualification",
            interrupted_repository / "authority.json",
        )
    assert credential_reads == [True]


def test_authority_requires_exact_repository_source_inventory(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    preflight = program_005.credential_free_preflight(_REPOSITORY, "qualification")
    source_commit = subprocess_run(("git", "rev-parse", "HEAD"))[0]
    bindings = {
        "program_plan": {
            "path": program_005._PLAN_PATH.as_posix(),
            "sha256": program_005._PLAN_SHA256,
            "fingerprint": program_005._PLAN_FINGERPRINT,
        },
        "retention_policy": {
            "path": program_005._RETENTION_PATH.as_posix(),
            "sha256": program_005._RETENTION_SHA256,
            "fingerprint": program_005._RETENTION_FINGERPRINT,
        },
        "public_dataset_contract": {
            "path": program_005._PUBLIC_CONTRACT_PATH.as_posix(),
            "sha256": program_005._PUBLIC_CONTRACT_SHA256,
            "fingerprint": program_005._PUBLIC_CONTRACT_FINGERPRINT,
        },
        "corporate_action_ledger": {
            "path": program_005._ACTION_LEDGER_PATH.as_posix(),
            "sha256": program_005._ACTION_LEDGER_SHA256,
            "fingerprint": program_005._ACTION_LEDGER_FINGERPRINT,
        },
    }
    authority: dict[str, Any] = {
        "schema_version": "program-005-source-authority-v1",
        "status": "ACTIVE-ONE-USE",
        "authority_id": "synthetic-program-005-qualification",
        "program_id": "multi-hour-sector-etf-research-004",
        "scope": "qualification",
        "request_plan_fingerprint": preflight["request_plan_fingerprint"],
        "authority": {
            "provider_contact": True,
            "credential_access": True,
            "source_requests": True,
            "source_qualification": True,
            "market_data_acquisition": False,
            "real_dataset_admission": False,
            **{name: False for name in program_005._AUTHORITY_FALSE_KEYS},
        },
        "bindings": bindings,
        "source_commit": source_commit,
        "source_files": [
            {
                "path": path.as_posix(),
                "sha256": program_005._file_sha256(_REPOSITORY / path),
            }
            for path in program_005._AUTHORITY_SOURCE_PATHS
        ],
    }
    monkeypatch.setattr(
        program_005,
        "_git_file_sha256",
        lambda repository, _commit, path: program_005._file_sha256(repository / path),
    )

    def write_authority(payload: Mapping[str, Any]) -> Path:
        unsigned = dict(payload)
        unsigned["authority_fingerprint"] = fingerprint(unsigned)
        path = tmp_path / "authority.json"
        path.write_text(json.dumps(unsigned), encoding="utf-8")
        return path

    path = write_authority(authority)
    assert (
        program_005.load_active_authority(
            _REPOSITORY,
            path,
            "qualification",
            str(preflight["request_plan_fingerprint"]),
        )["authority_id"]
        == "synthetic-program-005-qualification"
    )

    missing = deepcopy(authority)
    missing["source_files"] = missing["source_files"][:-1]
    with pytest.raises(program_005.Program005Error, match="source files are absent"):
        program_005.load_active_authority(
            _REPOSITORY,
            write_authority(missing),
            "qualification",
            str(preflight["request_plan_fingerprint"]),
        )

    escaped = deepcopy(authority)
    escaped["source_files"][0]["path"] = "../../../../../etc/hosts"
    with pytest.raises(program_005.Program005Error, match="source binding differs"):
        program_005.load_active_authority(
            _REPOSITORY,
            write_authority(escaped),
            "qualification",
            str(preflight["request_plan_fingerprint"]),
        )


def test_cli_preflight_and_repository_safety_guard(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    runtime = tmp_path / "runtime"
    monkeypatch.setenv("TRADING_LAB_HOME", str(runtime))
    assert (
        dispatcher.main(("data", "acquire", "program-005", "preflight", "--scope", "qualification"))
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["credential_loaded"] is False
    assert output["provider_request_made"] is False
    assert output["request_chains_to_acquire"] == 26
    assert not runtime.exists()

    spec = importlib.util.spec_from_file_location(
        "check_secrets", _REPOSITORY / "scripts" / "check_secrets.py"
    )
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    monkeypatch.chdir(tmp_path)
    private_path = Path("program-005-private-bars.csv")
    private_path.write_text("timestamp,symbol,open,high,low,close,volume\n", encoding="utf-8")
    raw_path = Path("leaks/body.json")
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text(
        json.dumps(
            {
                "bars": {
                    "MDY": [
                        {
                            "t": "2021-02-03T16:40:00Z",
                            "o": 1,
                            "h": 2,
                            "l": 1,
                            "c": 2,
                            "v": 100,
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    config_data = Path("config/research/program-005-bars.jsonl")
    config_data.parent.mkdir(parents=True)
    config_data.write_text(
        json.dumps(
            {
                "timestamp": "2021-02-03T16:40:00Z",
                "symbol": "MDY",
                "open": 1,
                "high": 2,
                "low": 1,
                "close": 2,
                "volume": 100,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    escaped_csv = Path("notes/snapshot.csv")
    escaped_csv.parent.mkdir(parents=True)
    escaped_csv.write_text(
        "timestamp,symbol,open,high,low,close,volume\n2021-02-03T16:40:00Z,MDY,1,2,1,2,100\n",
        encoding="utf-8",
    )
    escaped_parquet = Path("notes/snapshot.parquet")
    escaped_parquet.write_bytes(b"synthetic-binary-placeholder")
    secret_path = Path("credential.env")
    secret_path.write_text("PROGRAM_005_ALPACA_API_SECRET_KEY=synthetic-value\n", encoding="utf-8")
    export_path = Path("credential.sh")
    export_path.write_text(
        "export PROGRAM_005_ALPACA_API_SECRET_KEY=synthetic-value\n", encoding="utf-8"
    )
    json_secret_path = Path("credential.json")
    json_secret_path.write_text(
        '{"PROGRAM_005_ALPACA_API_SECRET_KEY": "synthetic-value"}\n', encoding="utf-8"
    )
    public_path = Path("config/research/program-005-private-data-retention-policy-v1.json")
    public_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        guard,
        "tracked_files",
        lambda: [
            private_path,
            raw_path,
            config_data,
            escaped_csv,
            escaped_parquet,
            secret_path,
            export_path,
            json_secret_path,
            public_path,
        ],
    )
    assert guard.main() == 1
    errors = capsys.readouterr().err
    assert "private-market-data-path" in errors
    assert "leaks/body.json:private-market-data-content" in errors
    assert "config/research/program-005-bars.jsonl:private-market-data-path" in errors
    assert "notes/snapshot.csv:private-market-data-content" in errors
    assert "notes/snapshot.parquet:private-market-data-path" in errors
    assert "credential.env:1" in errors
    assert "credential.sh:1" in errors
    assert "credential.json:1" in errors
    assert str(public_path) not in errors


def test_repository_contains_no_program_005_observations_or_private_artifacts() -> None:
    tracked = subprocess_run(("git", "ls-files"))
    assert not any(path.startswith(".trading-lab/") for path in tracked)
    assert not any(
        "program-005" in path.lower()
        and Path(path).suffix.lower()
        in {".arrow", ".csv", ".db", ".feather", ".jsonl", ".parquet", ".sqlite", ".sqlite3"}
        for path in tracked
    )
    for path in (
        _REPOSITORY / "config/research/program-005-private-data-retention-policy-v1.json",
        _REPOSITORY / "config/research/program-005-public-dataset-contract-v1.json",
        _REPOSITORY / "config/research/program-005-corporate-action-ledger-v1.json",
    ):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload.get("observation_count", payload.get("provider_observation_count", 0)) == 0


def subprocess_run(command: tuple[str, ...]) -> tuple[str, ...]:
    import subprocess

    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return tuple(result.stdout.splitlines())
