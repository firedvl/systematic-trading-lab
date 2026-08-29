from __future__ import annotations

import hashlib
import importlib.util
import json
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest

import systematic_trading_lab.program_007_alpaca as program_007
from systematic_trading_lab.calendar import expected_bar_timestamps
from systematic_trading_lab.domain import Timeframe
from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_LEDGER_PATH = _REPOSITORY / "config/research/program-007-unit-changing-action-ledger-v1.json"
_SCHEMA_PATH = (
    _REPOSITORY / "config/research/program-007-unit-changing-action-ledger-v1.schema.json"
)
_PROPOSAL_PATH = (
    _REPOSITORY / "config/research/program-007-alpaca-raw-source-qualification-proposal-v1.json"
)
_NOW = datetime(2026, 8, 28, 20, tzinfo=UTC)


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _ledger() -> dict[str, Any]:
    return _load(_LEDGER_PATH)


def _refingerprint(ledger: dict[str, Any]) -> None:
    unsigned = dict(ledger)
    unsigned.pop("ledger_fingerprint", None)
    ledger["ledger_fingerprint"] = fingerprint(unsigned)


def _bar(timestamp: datetime | str, **changes: object) -> dict[str, object]:
    value = (
        timestamp.isoformat().replace("+00:00", "Z")
        if isinstance(timestamp, datetime)
        else timestamp
    )
    row: dict[str, object] = {
        "t": value,
        "o": 100,
        "h": 101,
        "l": 99,
        "c": 100.5,
        "v": 10,
        "n": 2,
        "vw": 100.25,
    }
    row.update(changes)
    return row


def _body(rows: list[tuple[str, dict[str, object]]], token: str | None = None) -> bytes:
    bars: dict[str, list[dict[str, object]]] = defaultdict(list)
    for symbol, row in rows:
        bars[symbol].append(row)
    return json.dumps(
        {"bars": dict(bars), "next_page_token": token},
        separators=(",", ":"),
    ).encode()


def _chain(
    *,
    chain_id: str = "synthetic",
    start: datetime = datetime(2025, 11, 26, 14, 30, tzinfo=UTC),
    end: datetime = datetime(2025, 11, 26, 20, 55, tzinfo=UTC),
    symbols: tuple[str, ...] = ("SPY",),
    maximum_pages: int = 1,
) -> program_007.RequestChain:
    return program_007.RequestChain(chain_id, start, end, symbols, maximum_pages)


def _complete_rows(
    chain: program_007.RequestChain,
) -> list[tuple[str, dict[str, object]]]:
    timestamps = expected_bar_timestamps(chain.start, chain.end, Timeframe.FIVE_MINUTES)
    return [(symbol, _bar(timestamp)) for symbol in chain.symbols for timestamp in timestamps]


def _recursive_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_recursive_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_recursive_keys(item) for item in value), set())
    return set()


def _synthetic_action(
    effective: str,
    old_shares: int,
    new_shares: int,
    action_type: str,
    *,
    transformable: bool = True,
) -> dict[str, object]:
    return {
        "symbol": "XLB",
        "effective_session": effective,
        "old_shares": old_shares,
        "new_shares": new_shares,
        "action_type": action_type,
        "transformable": transformable,
    }


def test_action_ledger_schema_hash_fingerprint_and_symbol_coverage() -> None:
    schema = _load(_SCHEMA_PATH)
    ledger = _ledger()
    assert (
        hashlib.sha256(_SCHEMA_PATH.read_bytes()).hexdigest() == ledger["schema_binding"]["sha256"]
    )
    assert schema["additionalProperties"] is False

    def assert_strict_objects(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value.get("additionalProperties") is False
            for item in value.values():
                assert_strict_objects(item)
        elif isinstance(value, list):
            for item in value:
                assert_strict_objects(item)

    assert_strict_objects(schema)
    program_007.validate_action_ledger(ledger)
    assert ledger["ledger_fingerprint"] == (
        "eb61c7a117973977bd2f7947c965f5f0d3061beee43635bd39f893da738ea921"
    )
    assert [item["symbol"] for item in ledger["symbols"]] == list(program_007.SYMBOLS)
    assert {item["symbol"] for item in ledger["actions"]} == {
        "XLB",
        "XLE",
        "XLK",
        "XLU",
        "XLY",
    }
    assert {
        item["symbol"]
        for item in ledger["symbols"]
        if item["conclusion"] == "NO-APPLICABLE-ACTION-FOUND"
    } == {"IWM", "MDY", "SPY", "XLF", "XLI", "XLP", "XLRE", "XLV"}
    assert all(value is False for value in ledger["authority"].values())


def test_action_ledger_mutation_unknown_action_and_inconsistent_ratio_fail_closed() -> None:
    ledger = _ledger()
    ledger["symbols"][0]["continuity_notes"] += " mutation"
    with pytest.raises(program_007.Program007Error, match="fingerprint"):
        program_007.validate_action_ledger(ledger)

    ledger = _ledger()
    ledger["actions"][0]["action_type"] = "spin_off"
    _refingerprint(ledger)
    with pytest.raises(program_007.Program007Error, match="split ratio"):
        program_007.validate_action_ledger(ledger)

    ledger = _ledger()
    ledger["actions"][0]["new_shares"] = 1
    _refingerprint(ledger)
    with pytest.raises(program_007.Program007Error, match="split ratio"):
        program_007.validate_action_ledger(ledger)


def test_exact_volume_factors_cover_forward_reverse_and_sequential_actions() -> None:
    before = date(2025, 1, 2)
    middle = date(2025, 6, 2)
    after = date(2026, 1, 2)
    two_for_one = (_synthetic_action("2025-06-01", 1, 2, "forward_split"),)
    three_for_two = (_synthetic_action("2025-06-01", 2, 3, "forward_split"),)
    one_for_five = (_synthetic_action("2025-06-01", 5, 1, "reverse_split"),)
    sequential = (
        _synthetic_action("2025-02-01", 1, 2, "forward_split"),
        _synthetic_action("2025-05-01", 2, 3, "forward_split"),
        _synthetic_action("2025-09-01", 5, 1, "reverse_split"),
    )
    assert program_007.share_unit_factor_for_actions(two_for_one, "XLB", before, after) == 2
    assert program_007.share_unit_factor_for_actions(three_for_two, "XLB", before, after) == (
        Fraction(3, 2)
    )
    assert program_007.share_unit_factor_for_actions(one_for_five, "XLB", before, after) == (
        Fraction(1, 5)
    )
    assert program_007.share_unit_factor_for_actions(sequential, "XLB", before, after) == (
        Fraction(3, 5)
    )
    assert program_007.share_unit_factor_for_actions(sequential, "XLB", after, before) == (
        Fraction(5, 3)
    )
    assert program_007.share_unit_factor_for_actions(two_for_one, "XLB", middle, after) == 1


def test_ledger_normalization_uses_effective_session_boundary_and_exact_volume() -> None:
    ledger = _ledger()
    pre = date(2025, 11, 28)
    effective = date(2025, 12, 5)
    post = date(2025, 12, 15)
    assert program_007.share_unit_factor(ledger, "XLB", pre, post) == 2
    assert program_007.share_unit_factor(ledger, "XLB", effective, post) == 1
    assert program_007.share_unit_factor(ledger, "XLB", post, pre) == Fraction(1, 2)
    assert program_007.share_unit_factor(ledger, "SPY", pre, post) == 1
    assert program_007.normalize_share_volume(Decimal("10.5"), ledger, "XLB", pre, post) == 21


def test_ambiguous_and_inconsistent_synthetic_actions_fail_closed() -> None:
    with pytest.raises(program_007.Program007Error, match="not safely transformable"):
        program_007.share_unit_factor_for_actions(
            (_synthetic_action("2025-06-01", 1, 2, "spin_off"),),
            "XLB",
            date(2025, 1, 2),
            date(2026, 1, 2),
        )
    with pytest.raises(program_007.Program007Error, match="not safely transformable"):
        program_007.share_unit_factor_for_actions(
            (_synthetic_action("2025-06-01", 1, 2, "forward_split", transformable=False),),
            "XLB",
            date(2025, 1, 2),
            date(2026, 1, 2),
        )
    with pytest.raises(program_007.Program007Error, match="inconsistent"):
        program_007.share_unit_factor_for_actions(
            (_synthetic_action("2025-06-01", 2, 1, "forward_split"),),
            "XLB",
            date(2025, 1, 2),
            date(2026, 1, 2),
        )


def test_frozen_raw_contract_and_full_14742_coordinate_shape(tmp_path: Path) -> None:
    proposal = _load(_PROPOSAL_PATH)
    chains = program_007.frozen_request_chains(proposal)
    assert len(chains) == 6
    assert sum(chain.maximum_pages for chain in chains) == 11
    assert (
        sum(
            len(expected_bar_timestamps(chain.start, chain.end, Timeframe.FIVE_MINUTES))
            * len(chain.symbols)
            for chain in chains
        )
        == 14_742
    )
    chain_by_id = {chain.chain_id: chain for chain in chains}
    pages: dict[tuple[str, str | None], bytes] = {}
    for chain in chains:
        rows = _complete_rows(chain)
        if chain.chain_id == "pagination-2023-05-16-to-2023-05-30":
            extended = ("SPY", _bar("2023-05-16T20:00:00Z"))
            pages[(chain.chain_id, None)] = _body([*rows[:9_999], extended], "page-2")
            pages[(chain.chain_id, "page-2")] = _body(rows[9_999:])
        else:
            pages[(chain.chain_id, None)] = _body(rows)

    intents: list[program_007.RequestIntent] = []

    def source(intent: program_007.RequestIntent) -> program_007.RawResponse:
        assert (
            tmp_path
            / "chains"
            / intent.chain_identity
            / "requests"
            / f"{intent.page_index:05d}.json"
        ).is_file()
        intents.append(intent)
        return program_007.RawResponse(200, pages[(intent.chain_id, intent.incoming_page_token)])

    result = program_007.execute_qualification(chains, tmp_path, source, now=lambda: _NOW)
    assert result.response_count == len(intents) == 7
    assert result.canonical_row_count == 14_742
    assert result.raw_row_count == 14_743
    assert [len(item.canonical_rows) for item in result.chains] == [
        1_014,
        1_014,
        1_014,
        10_140,
        546,
        1_014,
    ]
    assert intents[0].method == "GET"
    assert intents[0].redirects is False
    for intent in intents:
        query = parse_qs(urlparse(intent.url).query)
        assert query["feed"] == ["sip"]
        assert query["timeframe"] == ["5Min"]
        assert query["adjustment"] == ["raw"]
        assert query["sort"] == ["asc"]
        assert query["limit"] == ["10000"]
        assert query["asof"] == ["2026-07-31"]
        assert query["start"] == [
            chain_by_id[intent.chain_id].start.isoformat().replace("+00:00", "Z")
        ]
        assert query["end"] == [chain_by_id[intent.chain_id].end.isoformat().replace("+00:00", "Z")]

    summary = result.public_summary(_ledger()["ledger_fingerprint"])
    forbidden = {
        "bars",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "request_url",
        "incoming_page_token",
        "outgoing_page_token",
        "raw_file",
        "retrieved_at_utc",
    }
    assert not forbidden & _recursive_keys(summary)
    assert summary["canonical_row_count"] == 14_742
    assert summary["extended_hours_row_count"] == 1
    assert summary["provider_requests_performed"] == 0
    assert (tmp_path / "private-manifest.json").is_file()


def test_valid_extended_hours_are_retained_and_restart_never_recontacts_source(
    tmp_path: Path,
) -> None:
    chain = _chain(
        start=datetime(2025, 11, 26, 12, tzinfo=UTC),
        end=datetime(2025, 11, 26, 22, tzinfo=UTC),
    )
    body = _body(
        [
            *(_complete_rows(chain)),
            ("SPY", _bar("2025-11-26T13:00:00Z")),
            ("SPY", _bar("2025-11-26T21:00:00Z")),
        ]
    )
    calls = 0

    def source(intent: program_007.RequestIntent) -> program_007.RawResponse:
        nonlocal calls
        calls += 1
        return program_007.RawResponse(200, body)

    result = program_007.execute_qualification((chain,), tmp_path, source, now=lambda: _NOW)
    assert calls == 1
    assert len(result.chains[0].raw_rows) == 80
    assert len(result.chains[0].canonical_rows) == 78
    assert result.chains[0].canonical_rows[0].timestamp == datetime(
        2025, 11, 26, 14, 30, tzinfo=UTC
    )
    assert result.chains[0].canonical_rows[-1].timestamp == datetime(
        2025, 11, 26, 20, 55, tzinfo=UTC
    )

    def forbidden_source(intent: program_007.RequestIntent) -> program_007.RawResponse:
        raise AssertionError(f"unexpected replay: {intent.url}")

    restarted = program_007.execute_qualification(
        (chain,), tmp_path, forbidden_source, now=lambda: _NOW
    )
    assert restarted == result
    raw_path = tmp_path / "chains" / chain.identity / "pages/00001/body.json"
    assert raw_path.read_bytes() == body


@pytest.mark.parametrize(
    "case",
    [
        "weekend",
        "holiday",
        "out-of-bounds",
        "misaligned",
        "duplicate",
        "malformed-timestamp",
        "foreign-symbol",
        "corrupt-json",
    ],
)
def test_invalid_raw_pages_fail_after_exact_bytes_are_retained(tmp_path: Path, case: str) -> None:
    chain = _chain()
    row = _bar("2025-11-26T14:30:00Z")
    rows = [("SPY", row)]
    if case == "weekend":
        chain = _chain(
            start=datetime(2025, 11, 28, tzinfo=UTC),
            end=datetime(2025, 12, 1, 23, 55, tzinfo=UTC),
        )
        rows = [("SPY", _bar("2025-11-29T15:00:00Z"))]
    elif case == "holiday":
        chain = _chain(
            start=datetime(2025, 7, 3, tzinfo=UTC),
            end=datetime(2025, 7, 7, 23, 55, tzinfo=UTC),
        )
        rows = [("SPY", _bar("2025-07-04T15:00:00Z"))]
    elif case == "out-of-bounds":
        rows = [("SPY", _bar("2025-11-26T14:25:00Z"))]
    elif case == "misaligned":
        rows = [("SPY", _bar("2025-11-26T14:31:00Z"))]
    elif case == "duplicate":
        rows = [("SPY", row), ("SPY", row)]
    elif case == "malformed-timestamp":
        rows = [("SPY", _bar("not-a-timestamp"))]
    elif case == "foreign-symbol":
        rows = [("QQQ", row)]
    body = b"{" if case == "corrupt-json" else _body(rows)

    with pytest.raises(program_007.Program007Error):
        program_007.execute_qualification(
            (chain,),
            tmp_path,
            lambda intent: program_007.RawResponse(200, body),
            now=lambda: _NOW,
        )
    page_root = tmp_path / "chains" / chain.identity / "pages/00001"
    assert (page_root / "body.json").read_bytes() == body
    validation = _load(page_root / "validation.json")
    assert validation["raw_structural_status"] == "FAIL"


def test_missing_canonical_row_excludes_the_whole_session(tmp_path: Path) -> None:
    chain = _chain()
    body = _body(_complete_rows(chain)[:-1])
    with pytest.raises(program_007.Program007Error, match="whole session is ineligible"):
        program_007.execute_qualification(
            (chain,),
            tmp_path,
            lambda intent: program_007.RawResponse(200, body),
            now=lambda: _NOW,
        )
    outcome = _load(tmp_path / "chains" / chain.identity / "validation.json")
    assert outcome["status"] == "FAIL"
    assert outcome["missing_coordinate_count"] == 1
    assert outcome["incomplete_sessions"] == ["2025-11-26"]


def test_forced_pagination_progression_and_token_cycle_rejection(tmp_path: Path) -> None:
    chain = _chain(maximum_pages=2)
    rows = _complete_rows(chain)
    successful_root = tmp_path / "success"
    responses = {
        None: _body(rows[:40], "page-2"),
        "page-2": _body(rows[40:]),
    }
    intents: list[program_007.RequestIntent] = []

    def source(intent: program_007.RequestIntent) -> program_007.RawResponse:
        intents.append(intent)
        return program_007.RawResponse(200, responses[intent.incoming_page_token])

    result = program_007.execute_qualification((chain,), successful_root, source, now=lambda: _NOW)
    assert len(result.chains[0].pages) == 2
    assert parse_qs(urlparse(intents[1].url).query)["page_token"] == ["page-2"]

    cycle_root = tmp_path / "cycle"
    cycle_responses = iter(
        (
            _body(rows[:1], "loop"),
            _body(rows[1:2], "loop"),
        )
    )
    with pytest.raises(program_007.Program007Error, match="token is repeated"):
        program_007.execute_qualification(
            (chain,),
            cycle_root,
            lambda intent: program_007.RawResponse(200, next(cycle_responses)),
            now=lambda: _NOW,
        )
    assert (cycle_root / "chains" / chain.identity / "pages/00002/body.json").is_file()


def test_page_response_and_total_byte_ceilings_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chain = _chain(maximum_pages=2)
    rows = _complete_rows(chain)
    oversized = _body(rows)
    monkeypatch.setattr(program_007, "MAXIMUM_RESPONSE_PAGE_BYTES", len(oversized) - 1)
    page_root = tmp_path / "page"
    with pytest.raises(program_007.Program007Error, match="8 MiB page ceiling"):
        program_007.execute_qualification(
            (chain,),
            page_root,
            lambda intent: program_007.RawResponse(200, oversized),
            now=lambda: _NOW,
        )
    assert not (page_root / "chains" / chain.identity / "pages/00001/body.json").exists()
    assert (page_root / "chains" / chain.identity / "requests/00001.json").is_file()

    monkeypatch.setattr(program_007, "MAXIMUM_RESPONSE_PAGE_BYTES", 8 * 1024 * 1024)
    first = _body(rows[:1], "page-2")
    second = _body(rows[1:])
    monkeypatch.setattr(program_007, "MAXIMUM_DOWNLOADED_BYTES", len(first) + len(second) - 1)
    total_root = tmp_path / "total"
    responses = iter((first, second))
    with pytest.raises(program_007.Program007Error, match="downloaded-byte ceiling"):
        program_007.execute_qualification(
            (chain,),
            total_root,
            lambda intent: program_007.RawResponse(200, next(responses)),
            now=lambda: _NOW,
        )
    assert (total_root / "chains" / chain.identity / "pages/00001/body.json").is_file()
    assert not (total_root / "chains" / chain.identity / "pages/00002/body.json").exists()


def test_page_and_response_count_ceilings_are_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chain = _chain(maximum_pages=1)
    rows = _complete_rows(chain)
    with pytest.raises(program_007.Program007Error, match="page ceiling"):
        program_007.execute_qualification(
            (chain,),
            tmp_path / "pages",
            lambda intent: program_007.RawResponse(200, _body(rows, "more")),
            now=lambda: _NOW,
        )

    chain = _chain(maximum_pages=2)
    monkeypatch.setattr(program_007, "MAXIMUM_HTTP_RESPONSES", 1)
    with pytest.raises(program_007.Program007Error, match="response ceiling"):
        program_007.execute_qualification(
            (chain,),
            tmp_path / "responses",
            lambda intent: program_007.RawResponse(200, _body(rows, "more")),
            now=lambda: _NOW,
        )


def test_ambiguous_send_is_never_retried(tmp_path: Path) -> None:
    chain = _chain()
    calls = 0

    def ambiguous(intent: program_007.RequestIntent) -> program_007.RawResponse:
        nonlocal calls
        calls += 1
        raise TimeoutError("synthetic ambiguous send")

    with pytest.raises(program_007.Program007Error, match="zero-retry"):
        program_007.execute_qualification((chain,), tmp_path, ambiguous, now=lambda: _NOW)
    assert calls == 1
    assert (tmp_path / "chains" / chain.identity / "requests/00001.json").is_file()
    assert not (tmp_path / "chains" / chain.identity / "pages/00001").exists()

    with pytest.raises(program_007.Program007Error, match="zero-retry"):
        program_007.execute_qualification((chain,), tmp_path, ambiguous, now=lambda: _NOW)
    assert calls == 1


def test_dst_early_close_holiday_adjacency_and_multi_day_bar_opens() -> None:
    dst_chain = _chain(
        start=datetime(2025, 3, 7, 13, tzinfo=UTC),
        end=datetime(2025, 3, 10, 22, tzinfo=UTC),
    )
    grid = expected_bar_timestamps(dst_chain.start, dst_chain.end, Timeframe.FIVE_MINUTES)
    assert grid[0] == datetime(2025, 3, 7, 14, 30, tzinfo=UTC)
    assert grid[78] == datetime(2025, 3, 10, 13, 30, tzinfo=UTC)
    assert dst_chain.session_dates == (date(2025, 3, 7), date(2025, 3, 10))

    holiday_chain = _chain(
        start=datetime(2025, 7, 3, 13, tzinfo=UTC),
        end=datetime(2025, 7, 7, 22, tzinfo=UTC),
    )
    holiday_grid = expected_bar_timestamps(
        holiday_chain.start, holiday_chain.end, Timeframe.FIVE_MINUTES
    )
    assert holiday_chain.session_dates == (date(2025, 7, 3), date(2025, 7, 7))
    assert len([point for point in holiday_grid if point.date() == date(2025, 7, 3)]) == 42
    assert not any(point.date() == date(2025, 7, 4) for point in holiday_grid)


def test_secret_guard_rejects_tracked_program_007_private_raw_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec = importlib.util.spec_from_file_location(
        "program_007_check_secrets", _REPOSITORY / "scripts/check_secrets.py"
    )
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    monkeypatch.chdir(tmp_path)
    private_path = Path("program-007-private/pages/00001/body.json")
    private_path.parent.mkdir(parents=True)
    private_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(guard, "tracked_files", lambda: [private_path])
    assert guard.main() == 1
    assert "private-market-data-path" in capsys.readouterr().err


def test_no_provider_client_credential_or_strategy_surface_exists() -> None:
    public_names = set(program_007.__dict__)
    assert (
        not {
            "AlpacaBarsClient",
            "read_credentials",
            "credential_preflight",
            "strategy",
            "backtest",
            "activate",
        }
        & public_names
    )
    assert program_007.AUTOMATIC_TRANSPORT_RETRIES == 0
    assert program_007.MAXIMUM_REQUESTS_PER_MINUTE == 120
