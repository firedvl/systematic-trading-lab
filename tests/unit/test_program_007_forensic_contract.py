from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

import pytest

import systematic_trading_lab.program_005_alpaca as program_005
from systematic_trading_lab.calendar import expected_bar_timestamps, expected_sessions
from systematic_trading_lab.domain import Symbol, Timeframe, TimestampRange
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.providers import AlpacaHistoricalProvider, ProviderRecords

_REPOSITORY = Path(__file__).resolve().parents[2]
_ANALYSIS_PATH = Path("config/research/program-006-source-qualification-forensic-analysis-v1.json")
_PROPOSAL_PATH = Path(
    "config/research/program-007-alpaca-raw-source-qualification-proposal-v1.json"
)


def _load(path: Path) -> dict[str, object]:
    return json.loads((_REPOSITORY / path).read_text(encoding="utf-8"))


def _assert_fingerprint(path: Path, field: str) -> dict[str, object]:
    value = _load(path)
    expected = value.pop(field)
    assert expected == fingerprint(value)
    return {**value, field: expected}


def _bar(timestamp: datetime | str) -> dict[str, object]:
    value = (
        timestamp if isinstance(timestamp, str) else timestamp.isoformat().replace("+00:00", "Z")
    )
    return {"t": value, "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 10}


def test_public_forensic_artifacts_are_bound_and_non_authorizing() -> None:
    analysis = _assert_fingerprint(_ANALYSIS_PATH, "analysis_fingerprint")
    proposal = _assert_fingerprint(_PROPOSAL_PATH, "proposal_fingerprint")

    failure_path = Path(
        str(
            analysis["terminal_state_confirmation"]["program_006_failure_artifact"]["path"]  # type: ignore[index]
        )
    )
    failure = _assert_fingerprint(failure_path, "failure_fingerprint")
    failure_binding = analysis["terminal_state_confirmation"][  # type: ignore[index]
        "program_006_failure_artifact"
    ]
    assert (
        hashlib.sha256((_REPOSITORY / failure_path).read_bytes()).hexdigest()
        == failure_binding[  # type: ignore[index]
            "sha256"
        ]
    )
    assert failure["status"] == "TERMINAL-FAIL-CONSUMED-NO-RETRY"
    assert analysis["failure_a"]["classification"] == "INDETERMINATE"  # type: ignore[index]
    assert analysis["failure_b"]["classification"] == (  # type: ignore[index]
        "QUALIFICATION-SPECIFICATION-DEFECT"
    )
    assert all(value is False for value in analysis["effective_authority"].values())  # type: ignore[union-attr]
    assert all(value is False for value in proposal["authority"].values())  # type: ignore[union-attr]
    assert proposal["status"] == "PROPOSED-NOT-AUTHORIZED"


def test_program_007_sample_is_fresh_and_deterministic() -> None:
    proposal = _load(_PROPOSAL_PATH)
    audit = proposal["prior_provider_observation_audit"]
    selection = proposal["fresh_sample_selection"]
    start = datetime(2020, 6, 26, tzinfo=UTC)
    end = datetime(2026, 7, 31, 23, 59, tzinfo=UTC)
    sessions = expected_sessions(start, end)
    grid_counts = Counter(
        point.date() for point in expected_bar_timestamps(start, end, Timeframe.FIVE_MINUTES)
    )
    program_002 = set(expected_sessions(start, datetime(2021, 2, 26, 23, 59, tzinfo=UTC)))
    program_006 = {
        datetime.fromisoformat(value).date() for value in audit["program_006_observed_sessions"]
    }
    observed = program_002 | program_006
    eligible = tuple(session for session in sessions if session not in observed)

    assert len(sessions) == audit["eligible_exposed_chronology"]["xnys_session_count"]
    assert (
        fingerprint([str(value) for value in sessions])
        == audit["eligible_exposed_chronology"]["session_list_fingerprint"]
    )
    assert (
        len(program_002)
        == audit["program_002_observed_market_data"]["xnys_session_range"]["distinct_session_count"]
    )
    assert (
        fingerprint([str(value) for value in sorted(program_002)])
        == audit["program_002_observed_market_data"]["xnys_session_range"][
            "session_list_fingerprint"
        ]
    )
    assert len(observed) == audit["previously_observed_session_union_count"]
    assert (
        fingerprint([str(value) for value in sorted(observed)])
        == audit["previously_observed_session_union_fingerprint"]
    )
    assert len(eligible) == audit["eligible_unobserved_session_count"]
    assert (
        fingerprint([str(value) for value in eligible])
        == audit["eligible_unobserved_session_fingerprint"]
    )

    seed = selection["seed"]
    split_effective = datetime(2025, 12, 5).date()
    semantic_controls = {
        max(value for value in eligible if value < split_effective),
        min(value for value in eligible if value > split_effective),
    }
    remaining = set(eligible) - semantic_controls
    full_sessions = {value for value, count in grid_counts.items() if count == 78}
    pagination_candidates = []
    for offset in range(len(sessions) - 9):
        window = sessions[offset : offset + 10]
        if all(value in remaining and value in full_sessions for value in window):
            digest = hashlib.sha256(
                f"{seed}|pagination|{window[0]}|{window[-1]}".encode()
            ).hexdigest()
            pagination_candidates.append((digest, window))
    pagination_digest, pagination = min(pagination_candidates)
    normal_candidates = sorted(
        (
            hashlib.sha256(f"{seed}|normal|{value}".encode()).hexdigest(),
            value,
        )
        for value in remaining - set(pagination)
        if value in full_sessions
    )
    normals = {value for _, value in normal_candidates[:3]}
    selected = tuple(sorted(semantic_controls | set(pagination) | normals))

    assert len(pagination_candidates) == selection["pagination_candidate_count"]
    assert pagination_digest == selection["selected_pagination_digest"]
    assert {str(value) for value in normals} == set(selection["categories"]["normal_controls"])
    assert [str(value) for value in selected] == sorted(
        value
        for values in selection["categories"].values()
        if isinstance(values, list)
        for value in values
    )
    assert not set(selected) & observed
    assert (
        fingerprint([str(value) for value in selected]) == selection["selected_session_fingerprint"]
    )
    assert (
        sum(grid_counts[value] * 13 for value in selected)
        == selection["expected_regular_session_rows"]
    )


def test_rth_projection_tolerates_extended_hours_across_symbol_pagination() -> None:
    requested = TimestampRange(
        datetime(2025, 11, 26, 14, 30, tzinfo=UTC),
        datetime(2025, 11, 28, 17, 55, tzinfo=UTC),
    )
    expected = expected_bar_timestamps(requested.start, requested.end, Timeframe.FIVE_MINUTES)
    extended = ("2025-11-26T21:00:00Z", "2025-11-28T13:00:00Z")

    old_chain = program_005.RequestChain(
        "synthetic-pagination--raw",
        "synthetic-pagination",
        "raw",
        requested.start,
        requested.end,
        ("SPY",),
        tuple(dict.fromkeys(point.date() for point in expected)),
        2,
    )
    old_body = json.dumps(
        {
            "bars": {"SPY": [_bar(expected[0]), _bar(extended[0])]},
            "next_page_token": None,
        }
    ).encode()
    with pytest.raises(program_005.Program005Error, match="outside the exact XNYS grid"):
        program_005.parse_bars_page(old_body, old_chain)

    requests: list[Request] = []
    payloads = iter(
        (
            {
                "bars": {"SPY": [*map(_bar, expected), _bar(extended[0])]},
                "next_page_token": "page-2",
            },
            {
                "bars": {"QQQ": [_bar(extended[1]), *map(_bar, expected)]},
                "next_page_token": None,
            },
        )
    )

    def transport(request: Request) -> bytes:
        requests.append(request)
        return json.dumps(next(payloads)).encode()

    records = AlpacaHistoricalProvider(
        "synthetic-key", "synthetic-secret", transport=transport
    ).fetch((Symbol("SPY"), Symbol("QQQ")), Timeframe.FIVE_MINUTES, requested)

    assert isinstance(records, ProviderRecords)
    assert len(records) == len(expected) * 2
    assert len(records.raw_records) == len(records) + len(extended)
    assert not set(extended) & {str(record["timestamp"]) for record in records}
    assert set(extended) <= {str(record["timestamp"]) for record in records.raw_records}
    assert parse_qs(urlparse(str(requests[1].full_url)).query)["page_token"] == ["page-2"]


def test_split_share_units_replace_the_old_combined_factor_assumption() -> None:
    timestamp = datetime(2024, 6, 10, 13, 30, tzinfo=UTC)
    raw = program_005.CanonicalBar(
        timestamp,
        "XLB",
        Decimal("100"),
        Decimal("102"),
        Decimal("99"),
        Decimal("101"),
        Decimal("1000"),
    )
    rounded_adjusted = program_005.CanonicalBar(
        timestamp,
        "XLB",
        Decimal("50.01"),
        Decimal("51"),
        Decimal("49.5"),
        Decimal("50.5"),
        Decimal("2000"),
    )
    ledger = _load(Path("config/research/program-005-corporate-action-ledger-v1.json"))

    with pytest.raises(program_005.Program005Error, match="price factor is not constant"):
        program_005.validate_action_pair((raw,), (rounded_adjusted,), ledger)

    split_ratio = Decimal("2")
    assert rounded_adjusted.volume == raw.volume * split_ratio
    assert Decimal("102") / Decimal("100") - 1 == Decimal("51") / Decimal("50") - 1
    assert Decimal("100") * Decimal("1000") == Decimal("50") * Decimal("2000")
    assert raw.volume * split_ratio == rounded_adjusted.volume
    proposal = _load(_PROPOSAL_PATH)
    normalization = proposal["corporate_action_contract"]["normalization"]
    assert normalization["canonical_prices"].startswith("retain raw provider prices")
    assert normalization["spin_off_volume_adjustment"] is False
