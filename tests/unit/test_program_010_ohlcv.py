from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from systematic_trading_lab import program_007_alpaca as raw_contract
from systematic_trading_lab import program_010_ohlcv as program_010
from systematic_trading_lab.calendar import expected_bar_timestamps
from systematic_trading_lab.domain import Timeframe

_REPOSITORY = Path(__file__).resolve().parents[2]
_PRIVATE_009 = _REPOSITORY / ".trading-lab/program-009-raw-alpaca-sip-ohlcv-v1"


def _request(value: str) -> program_010.SessionRequest:
    return program_010.SessionRequest(date.fromisoformat(value))


def _bar(timestamp: datetime | str) -> dict[str, object]:
    value = (
        timestamp.isoformat().replace("+00:00", "Z")
        if isinstance(timestamp, datetime)
        else timestamp
    )
    return {"t": value, "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 10}


def _complete_rows(request: program_010.SessionRequest) -> list[tuple[str, dict[str, object]]]:
    return [
        (symbol, _bar(timestamp)) for symbol in program_010.SYMBOLS for timestamp in request.grid
    ]


def _body(rows: list[tuple[str, dict[str, object]]], token: str | None = None) -> bytes:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for symbol, row in rows:
        grouped[symbol].append(row)
    return json.dumps(
        {"bars": dict(grouped), "next_page_token": token},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _responses(
    pages: list[tuple[list[tuple[str, dict[str, object]]], str | None]],
) -> tuple[raw_contract.RawResponse, ...]:
    return tuple(raw_contract.RawResponse(200, _body(rows, token)) for rows, token in pages)


def _run(
    request: program_010.SessionRequest,
    pages: list[tuple[list[tuple[str, dict[str, object]]], str | None]],
) -> tuple[program_010.SessionResult, program_010.SyntheticSessionSource]:
    source = program_010.SyntheticSessionSource(_responses(pages))
    return program_010.execute_synthetic_session(request, source), source


def _recursive_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _recursive_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _recursive_keys(item)}
    return set()


def test_session_contract_uses_exact_rth_bounds_and_limit_1000() -> None:
    normal = _request("2024-01-11")
    early = _request("2025-11-28")
    query = parse_qs(urlparse(normal.url()).query)

    assert len(normal.grid) == 78
    assert len(normal.expected_coordinates) == 1_014
    assert len(early.grid) == 42
    assert len(early.expected_coordinates) == 546
    assert query == {
        "symbols": [",".join(program_010.SYMBOLS)],
        "start": [normal.start.isoformat().replace("+00:00", "Z")],
        "end": [normal.end.isoformat().replace("+00:00", "Z")],
        "feed": ["sip"],
        "timeframe": ["5Min"],
        "adjustment": ["raw"],
        "sort": ["asc"],
        "limit": ["1000"],
        "asof": ["2026-07-31"],
    }


def test_complete_normal_session_naturally_paginates() -> None:
    request = _request("2024-01-11")
    rows = _complete_rows(request)
    result, source = _run(request, [(rows[:1000], "page-2"), (rows[1000:], None)])

    assert result.status == "PASS"
    assert len(result.pages) == len(source.intents) == len(source.retained_pages) == 2
    assert len(result.rows) == 1_014
    assert result.missingness == program_010.Missingness((), ())
    assert parse_qs(urlparse(source.intents[1].url).query)["page_token"] == ["page-2"]


def test_underfilled_first_page_and_three_page_completion_are_valid() -> None:
    request = _request("2024-01-11")
    rows = _complete_rows(request)
    tokens = ("opaque+/=one", "opaque+/=two")
    result, source = _run(
        request,
        [(rows[:400], tokens[0]), (rows[400:800], tokens[1]), (rows[800:], None)],
    )

    assert result.status == "PASS"
    assert [page.raw_row_count for page in result.pages] == [400, 400, 214]
    assert {intent.request_identity for intent in source.intents} == {request.identity}
    assert parse_qs(urlparse(source.intents[1].url).query)["page_token"] == [tokens[0]]
    assert parse_qs(urlparse(source.intents[2].url).query)["page_token"] == [tokens[1]]


@pytest.mark.parametrize(
    "pages",
    [
        ((0, "token-a"), (1, "token-a")),
        ((0, "token-a"), (1, "token-b"), (2, "token-a")),
    ],
)
def test_token_reuse_and_cycles_fail(pages: tuple[tuple[int, str], ...]) -> None:
    request = _request("2024-01-11")
    rows = _complete_rows(request)
    source = program_010.SyntheticSessionSource(
        _responses([([rows[index]], token) for index, token in pages])
    )

    with pytest.raises(program_010.Program010Error, match="token is repeated"):
        program_010.execute_synthetic_session(request, source)


def test_nonterminal_zero_progress_page_fails_after_raw_retention() -> None:
    request = _request("2024-01-11")
    body = _body([], "still-more")
    source = program_010.SyntheticSessionSource((raw_contract.RawResponse(200, body),))

    with pytest.raises(program_010.Program010Error, match="zero progress"):
        program_010.execute_synthetic_session(request, source)

    assert source.retained_pages[0].sha256 == hashlib.sha256(body).hexdigest()


def test_duplicate_coordinate_across_pages_fails() -> None:
    request = _request("2024-01-11")
    row = _complete_rows(request)[0]
    source = program_010.SyntheticSessionSource(_responses([([row], "page-2"), ([row], None)]))

    with pytest.raises(program_010.Program010Error, match="repeats across pages"):
        program_010.execute_synthetic_session(request, source)


def test_missing_one_mdy_coordinate_is_source_quality_not_transport_failure() -> None:
    request = _request("2024-01-11")
    missing = ("MDY", request.grid[32])
    rows = [
        item
        for item in _complete_rows(request)
        if not (
            item[0] == missing[0] and item[1]["t"] == missing[1].isoformat().replace("+00:00", "Z")
        )
    ]
    result, _ = _run(request, [(rows[:1000], "page-2"), (rows[1000:], None)])

    assert result.status == "PASS-WITH-SOURCE-MISSING"
    assert result.missingness.source_missing == (missing,)
    assert result.missingness.unobserved == ()


def test_entire_symbol_absence_is_catastrophic() -> None:
    request = _request("2024-01-11")
    rows = [item for item in _complete_rows(request) if item[0] != "MDY"]
    source = program_010.SyntheticSessionSource(_responses([(rows, None)]))

    with pytest.raises(program_010.CatastrophicCoverageError) as failure:
        program_010.execute_synthetic_session(request, source)

    assert failure.value.missing_symbols == ("MDY",)


def test_early_close_is_one_546_coordinate_page() -> None:
    request = _request("2025-11-28")
    result, _ = _run(request, [(_complete_rows(request), None)])

    assert result.status == "PASS"
    assert len(result.rows) == 546
    assert len(result.pages) == 1


def test_post_split_session_and_exact_share_volume_transform() -> None:
    request = _request("2025-12-15")
    rows = _complete_rows(request)
    result, _ = _run(request, [(rows[:1000], "page-2"), (rows[1000:], None)])
    ledger = raw_contract.load_action_ledger(
        _REPOSITORY / "config/research/program-007-unit-changing-action-ledger-v3.json"
    )

    assert result.status == "PASS"
    assert (
        raw_contract.normalize_share_volume(
            Decimal("10.5"), ledger, "XLB", date(2025, 11, 28), date(2025, 12, 15)
        )
        == 21
    )


@pytest.mark.parametrize("case", ["out-of-bounds", "malformed"])
def test_invalid_raw_page_fails_after_retention(case: str) -> None:
    request = _request("2024-01-11")
    row = _bar(request.start - timedelta(minutes=5))
    if case == "malformed":
        row.pop("v")
    body = _body([("SPY", row)])
    source = program_010.SyntheticSessionSource((raw_contract.RawResponse(200, body),))

    with pytest.raises(program_010.Program010Error):
        program_010.execute_synthetic_session(request, source)

    assert source.retained_pages[0].sha256 == hashlib.sha256(body).hexdigest()


def test_page_over_1000_rows_fails() -> None:
    request = _request("2024-01-11")
    body = _body(_complete_rows(request)[:1001], "more")
    source = program_010.SyntheticSessionSource((raw_contract.RawResponse(200, body),))

    with pytest.raises(program_010.Program010Error, match="1,000-row"):
        program_010.execute_synthetic_session(request, source)


def test_resource_cap_reports_unobserved_not_source_missing() -> None:
    request = _request("2024-01-11")
    rows = _complete_rows(request)
    source = program_010.SyntheticSessionSource(
        _responses([([rows[index]], f"token-{index}") for index in range(16)])
    )

    with pytest.raises(program_010.ChainIncompleteError) as failure:
        program_010.execute_synthetic_session(request, source)

    assert failure.value.page_count == 16
    assert failure.value.observed_count == 16
    assert failure.value.missingness.source_missing == ()
    assert len(failure.value.missingness.unobserved) == 998


def test_six_valid_nonterminal_pages_are_chain_incomplete_not_source_missing() -> None:
    request = _request("2024-01-11")
    observed = request.expected_coordinates[:6]
    missingness = program_010.classify_missingness(
        request.expected_coordinates, observed, terminal=False, frontier=observed[-1]
    )

    assert missingness.source_missing == ()
    assert len(missingness.unobserved) == 1_008


def test_full_synthetic_qualification_has_five_sessions_and_no_public_ohlcv() -> None:
    responses: list[raw_contract.RawResponse] = []
    for request in program_010.qualification_requests():
        rows = _complete_rows(request)
        if len(rows) > 1000:
            responses.extend(_responses([(rows[:1000], "page-2"), (rows[1000:], None)]))
        else:
            responses.extend(_responses([(rows, None)]))
    source = program_010.SyntheticSessionSource(responses)
    result = program_010.execute_synthetic_qualification(source)
    summary = result.public_summary()

    assert result.status == "PASS"
    assert len(result.sessions) == 5
    assert len(source.intents) == 9
    assert summary["expected_canonical_coordinate_count"] == 4_602
    assert not {"bars", "open", "high", "low", "close", "volume"} & _recursive_keys(summary)


@pytest.mark.skipif(not _PRIVATE_009.exists(), reason="private Program 009 evidence unavailable")
def test_private_program_009_pages_classify_mdy_and_xly_without_values() -> None:
    chains = raw_contract._frozen_request_chains()
    pagination = next(chain for chain in chains if chain.chain_id.startswith("pagination-"))
    observed: set[program_010.Coordinate] = set()
    raw_rows: list[raw_contract.RawBar] = []
    page_counts: list[tuple[int, int]] = []
    for index in range(1, 7):
        body = (_PRIVATE_009 / f"{pagination.chain_id}-{index:02d}.body").read_bytes()
        rows, token = raw_contract.parse_raw_page(body, pagination)
        canonical = raw_contract.project_rth(rows, pagination)
        assert token is not None
        raw_rows.extend(rows)
        observed.update(row.coordinate for row in canonical)
        page_counts.append((len(rows), len(canonical)))

    expected = tuple(
        (symbol, timestamp)
        for symbol in pagination.symbols
        for timestamp in expected_bar_timestamps(
            pagination.start, pagination.end, Timeframe.FIVE_MINUTES
        )
    )
    missingness = program_010.classify_missingness(
        expected, observed, terminal=False, frontier=max(row.coordinate for row in raw_rows)
    )

    assert page_counts == [
        (2428, 1547),
        (2235, 1210),
        (2557, 1612),
        (2443, 1777),
        (2311, 1866),
        (2265, 1883),
    ]
    assert missingness.source_missing == (("MDY", datetime(2023, 5, 19, 17, 10, tzinfo=UTC)),)
    assert len(missingness.unobserved) == 244
    assert {symbol for symbol, _ in missingness.unobserved} == {"XLY"}

    for chain in chains[:3]:
        body = (_PRIVATE_009 / f"{chain.chain_id}-01.body").read_bytes()
        rows, token = raw_contract.parse_raw_page(body, chain)
        assert token is None
        assert len(raw_contract.project_rth(rows, chain)) == 1_014
