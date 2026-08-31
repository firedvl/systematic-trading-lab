from __future__ import annotations

import hashlib
import importlib.util
import json
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from systematic_trading_lab import program_007_alpaca as raw_contract
from systematic_trading_lab import program_011_ohlcv as program_011
from systematic_trading_lab.calendar import expected_bar_timestamps, expected_sessions
from systematic_trading_lab.domain import Timeframe
from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]


def _load(path: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_REPOSITORY / path).read_text(encoding="utf-8")))


def _request(value: str = "2025-11-28") -> program_011.SessionRequest:
    return program_011.SessionRequest(date.fromisoformat(value))


def _bar(timestamp: datetime) -> dict[str, object]:
    return {
        "t": timestamp.isoformat().replace("+00:00", "Z"),
        "o": 100,
        "h": 101,
        "l": 99,
        "c": 100.5,
        "v": 10,
    }


def _complete_rows(
    request: program_011.SessionRequest,
) -> list[tuple[str, dict[str, object]]]:
    return [
        (symbol, _bar(timestamp)) for symbol in program_011.SYMBOLS for timestamp in request.grid
    ]


def _body(
    rows: list[tuple[str, dict[str, object]]],
    token: str | None = None,
    *,
    reverse_symbols: bool = False,
) -> bytes:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for symbol, row in rows:
        grouped[symbol].append(row)
    symbols = reversed(grouped) if reverse_symbols else grouped
    bars = {symbol: grouped[symbol] for symbol in symbols}
    return json.dumps({"bars": bars, "next_page_token": token}, separators=(",", ":")).encode()


def _source(*bodies: bytes) -> program_011.SyntheticSessionSource:
    return program_011.SyntheticSessionSource(
        tuple(raw_contract.RawResponse(200, body) for body in bodies)
    )


def test_unordered_symbol_members_pass_after_per_symbol_validation_and_sort() -> None:
    request = _request()
    rows = _complete_rows(request)
    body = _body(rows, reverse_symbols=True)
    source = _source(body)

    result = program_011.execute_synthetic_session(request, source)

    assert result.status == "PASS"
    assert result.rows == tuple(sorted(result.rows))
    assert result.pages[0].first_coordinate == request.expected_coordinates[0]
    assert result.pages[0].last_coordinate == request.expected_coordinates[-1]
    assert source.retained_pages[0].sha256 == hashlib.sha256(body).hexdigest()


def test_timestamp_disorder_within_one_symbol_fails_after_raw_retention() -> None:
    request = _request()
    rows = [("SPY", _bar(request.grid[1])), ("SPY", _bar(request.grid[0]))]
    body = _body(rows)
    source = _source(body)

    with pytest.raises(program_011.Program011Error, match="within a symbol array"):
        program_011.execute_synthetic_session(request, source)

    assert source.retained_pages[0].sha256 == hashlib.sha256(body).hexdigest()
    assert source.closed is True


def test_duplicate_coordinate_within_page_fails_after_raw_retention() -> None:
    request = _request()
    row = ("SPY", _bar(request.grid[0]))
    body = _body([row, row])
    source = _source(body)

    with pytest.raises(program_011.Program011Error, match="duplicate coordinate"):
        program_011.execute_synthetic_session(request, source)

    assert source.retained_pages[0].sha256 == hashlib.sha256(body).hexdigest()


def test_duplicate_coordinate_across_pages_fails() -> None:
    request = _request()
    row = ("SPY", _bar(request.grid[0]))
    source = _source(_body([row], "page-2"), _body([row]))

    with pytest.raises(program_011.Program011Error, match="repeats across pages"):
        program_011.execute_synthetic_session(request, source)


def test_cross_page_order_regression_still_fails() -> None:
    request = _request()
    later = ("SPY", _bar(request.grid[1]))
    earlier = ("SPY", _bar(request.grid[0]))
    source = _source(_body([later], "page-2"), _body([earlier]))

    with pytest.raises(program_011.Program011Error, match="ordering does not progress"):
        program_011.execute_synthetic_session(request, source)


def test_program_identity_and_frozen_sample_are_successor_specific() -> None:
    requests = program_011.qualification_requests()

    assert program_011.PROGRAM_ID == "multi-hour-sector-etf-research-010"
    assert program_011.PROGRAM_ORDINAL == 11
    assert [request.session.isoformat() for request in requests] == [
        "2021-04-28",
        "2025-01-06",
        "2025-02-27",
        "2025-11-28",
        "2025-12-15",
    ]
    assert sum(len(request.expected_coordinates) for request in requests) == 4_602
    assert "2021-05-25" not in {request.session.isoformat() for request in requests}


def test_fresh_sample_rederives_from_programs_002_through_010_and_protected_ranges() -> None:
    audit = _load("config/research/program-007-alpaca-raw-source-qualification-proposal-v1.json")[
        "prior_provider_observation_audit"
    ]
    program_009 = _load(
        "config/research/program-009-raw-alpaca-sip-ohlcv-structural-qualification-"
        "terminal-failure-v1.json"
    )
    program_010 = _load(
        "config/research/program-010-raw-alpaca-sip-ohlcv-structural-qualification-"
        "terminal-failure-v1.json"
    )
    protected_inventory = _load("config/research/standing-protected-chronology-v1.json")

    start = datetime(2020, 6, 26, tzinfo=UTC)
    end = datetime(2026, 7, 31, 23, 59, tzinfo=UTC)
    sessions = expected_sessions(start, end)
    grid_counts = Counter(
        timestamp.date()
        for timestamp in expected_bar_timestamps(start, end, Timeframe.FIVE_MINUTES)
    )
    observed = set(expected_sessions(start, datetime(2021, 2, 26, 23, 59, tzinfo=UTC)))
    observed.update(date.fromisoformat(value) for value in audit["program_006_observed_sessions"])
    assert all(
        program_009["runtime_outcome"]["pages_per_chain"][chain] > 0
        for chain in tuple(program_009["runtime_outcome"]["pages_per_chain"])[0:4]
    )
    observed.update(
        date.fromisoformat(value)
        for value in program_009["qualification_contract"]["sessions"][:-2]
    )
    observed.add(date.fromisoformat(program_010["operation_contract"]["session"]))

    protected = {
        session
        for session in sessions
        if any(
            date.fromisoformat(item["start"]) <= session <= date.fromisoformat(item["end"])
            for item in protected_inventory["ranges"]
        )
    }
    eligible = tuple(session for session in sessions if session not in observed | protected)
    controls = {date(2025, 11, 28), date(2025, 12, 15)}
    seed = "program-011-raw-sip-qualification-sample-v1"
    candidates = sorted(
        (
            hashlib.sha256(f"{seed}|normal|{session}".encode()).hexdigest(),
            session,
        )
        for session in eligible
        if grid_counts[session] == 78 and session not in controls
    )
    selected = tuple(sorted(controls | {session for _, session in candidates[:3]}))

    assert len(observed) == 199
    assert fingerprint([str(value) for value in sorted(observed)]) == (
        "3fb677dadeefb21dcab5a49d0d53030e064c9ac1a60becd1c5322b0b172729c8"
    )
    assert len(protected) == 145
    assert len(eligible) == 1_188
    assert fingerprint([str(value) for value in eligible]) == (
        "9274779e7ce6d72349dea14a5f61849b374cde796036041075c8b6e3d5691bba"
    )
    assert [(str(session), digest) for digest, session in candidates[:3]] == [
        (
            "2025-02-27",
            "0006baf02b85db42f6d9ff9bf4bfb47b711b7cf7919240d2362dcfd78b28779b",
        ),
        (
            "2025-01-06",
            "004fb0db61642084a95453bb3a83b840f246a243ba69ad48ae4d7b06bfc59b16",
        ),
        (
            "2021-04-28",
            "00935b721ccf00d7ba5a8fc1e06def600c7d712f0f420728b79b7201c8c38b68",
        ),
    ]
    assert selected == program_011.SELECTED_SESSIONS
    assert fingerprint([str(value) for value in selected]) == (
        "549a83f7af681088012d2867dfa63aebe6878f817fc13e692e3fe948e9ca62bc"
    )
    assert not set(selected) & observed
    assert not set(selected) & protected
    assert sum(grid_counts[value] * len(program_011.SYMBOLS) for value in selected) == 4_602


def test_secret_guard_allows_only_reserved_public_program_011_json_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec = importlib.util.spec_from_file_location(
        "program_011_check_secrets", _REPOSITORY / "scripts/check_secrets.py"
    )
    assert spec is not None and spec.loader is not None
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    public_program_artifacts = {
        path.relative_to(_REPOSITORY).as_posix()
        for path in (_REPOSITORY / "config/research").glob("program-011*.json")
    }

    assert public_program_artifacts <= guard.PUBLIC_PROGRAM_JSON

    private_path = tmp_path / "program-011-private-market-page.json"
    private_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(guard, "tracked_files", lambda: [private_path])

    assert guard.main() == 1
    assert "private-market-data-path" in capsys.readouterr().err
