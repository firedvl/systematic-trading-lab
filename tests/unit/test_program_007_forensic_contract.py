from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
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
_REVIEW_PATH = Path(
    "config/research/program-006-source-qualification-forensic-analysis-independent-review-v1.json"
)
_PROPOSAL_PATH = Path(
    "config/research/program-007-alpaca-raw-source-qualification-proposal-v1.json"
)


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_REPOSITORY / path).read_text(encoding="utf-8")))


def _assert_fingerprint(path: Path, field: str) -> dict[str, Any]:
    value = _load(path)
    expected = value.pop(field)
    assert expected == fingerprint(value)
    return {**value, field: expected}


def _load_bound_artifact(binding: dict[str, Any]) -> dict[str, Any]:
    path = Path(binding["path"])
    assert hashlib.sha256((_REPOSITORY / path).read_bytes()).hexdigest() == binding["sha256"]
    value = _load(path)
    if field := binding.get("fingerprint_field"):
        assert value[field] == binding["fingerprint"]
    return value


def _request_ranges(value: Any) -> set[tuple[str, str]]:
    ranges: set[tuple[str, str]] = set()
    if isinstance(value, dict):
        for start_key, end_key in (
            ("requested_start", "requested_end"),
            ("request_start", "request_end"),
        ):
            if isinstance(start := value.get(start_key), str) and isinstance(
                end := value.get(end_key), str
            ):
                ranges.add((start, end))
        if isinstance(request_url := value.get("request_url"), str):
            query = parse_qs(urlparse(request_url).query)
            if query.get("start") and query.get("end"):
                ranges.add((query["start"][0], query["end"][0]))
        for item in value.values():
            ranges.update(_request_ranges(item))
    elif isinstance(value, list):
        for item in value:
            ranges.update(_request_ranges(item))
    return ranges


def _bar(timestamp: datetime | str) -> dict[str, object]:
    value = (
        timestamp if isinstance(timestamp, str) else timestamp.isoformat().replace("+00:00", "Z")
    )
    return {"t": value, "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 10}


def test_public_forensic_artifacts_are_bound_and_non_authorizing() -> None:
    analysis = _assert_fingerprint(_ANALYSIS_PATH, "analysis_fingerprint")
    proposal = _assert_fingerprint(_PROPOSAL_PATH, "proposal_fingerprint")

    failure_path = Path(
        str(analysis["terminal_state_confirmation"]["program_006_failure_artifact"]["path"])
    )
    failure = _assert_fingerprint(failure_path, "failure_fingerprint")
    failure_binding = analysis["terminal_state_confirmation"]["program_006_failure_artifact"]
    assert (
        hashlib.sha256((_REPOSITORY / failure_path).read_bytes()).hexdigest()
        == failure_binding["sha256"]
    )
    assert failure["status"] == "TERMINAL-FAIL-CONSUMED-NO-RETRY"
    assert analysis["failure_a"]["classification"] == "INDETERMINATE"
    assert analysis["failure_b"]["classification"] == ("QUALIFICATION-SPECIFICATION-DEFECT")
    assert all(value is False for value in analysis["effective_authority"].values())
    assert all(value is False for value in proposal["authority"].values())
    assert proposal["status"] == "PROPOSED-NOT-AUTHORIZED"


def test_independent_review_binds_artifacts_and_passes_every_challenge() -> None:
    review = _assert_fingerprint(_REVIEW_PATH, "review_fingerprint")
    bindings = review["reviewed_artifacts"]
    assert set(bindings) == {
        "program_006_terminal_failure",
        "program_006_terminal_failure_review",
        "forensic_analysis",
        "program_007_proposal",
    }
    artifacts = {name: _load_bound_artifact(binding) for name, binding in bindings.items()}

    assert artifacts["program_006_terminal_failure"]["status"] == (
        "TERMINAL-FAIL-CONSUMED-NO-RETRY"
    )
    assert artifacts["forensic_analysis"]["failure_a"]["classification"] == "INDETERMINATE"
    assert artifacts["forensic_analysis"]["failure_b"]["classification"] == (
        "QUALIFICATION-SPECIFICATION-DEFECT"
    )
    assert artifacts["program_007_proposal"]["status"] == "PROPOSED-NOT-AUTHORIZED"
    assert all(value is False for value in artifacts["program_007_proposal"]["authority"].values())

    challenges = review["challenge_results"]
    assert [item["challenge"] for item in challenges] == list(range(1, 12))
    assert all(item["result"] == "PASS" for item in challenges)
    assert review["verification"]["required_challenge_count"] == 11
    assert review["verification"]["required_challenges_passed"] == 11
    assert review["findings"] == []
    assert review["status"] == review["verdict"] == "PASS-FINDING-FREE"
    assert all(value is False for value in review["authority"].values())
    assert review["private_data_firewall"] == {
        "private_pages_read_by_reviewer": False,
        "private_market_observations_in_this_artifact": False,
        "reconstructable_private_values_in_this_artifact": False,
        "private_program_roots_git_ignored": True,
        "tracked_private_file_count": 0,
        "strategy_outputs_generated_or_read": 0,
    }


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
    program_002_evidence = [
        _load_bound_artifact(binding)
        for binding in audit["program_002_observed_market_data"]["evidence_bindings"]
    ]
    program_002_ranges = {
        request_range
        for artifact in program_002_evidence
        for request_range in _request_ranges(artifact)
    }
    assert program_002_ranges
    program_002 = {
        session
        for range_start, range_end in program_002_ranges
        for session in expected_sessions(
            datetime.fromisoformat(range_start), datetime.fromisoformat(range_end)
        )
    }
    outcome_evidence = {
        name: _load_bound_artifact(binding)
        for name, binding in audit["program_outcome_evidence_bindings"].items()
    }
    assert outcome_evidence["program_003"]["authority"]["source_requests"] is False
    assert outcome_evidence["program_004"]["authority"]["source_requests"] is False
    for name in ("program_005", "program_006"):
        assert (
            outcome_evidence[name]["runtime_outcome"]["provider_request_count"]
            == audit["program_outcome_evidence_bindings"][name]["provider_request_count"]
        )
    program_006 = {
        datetime.fromisoformat(value).date()
        for value in outcome_evidence["program_006"]["qualification_contract"]["sessions"]
    }
    assert sorted(map(str, program_006)) == audit["program_006_observed_sessions"]
    observed = program_002 | program_006

    protected_inventory = audit["protected_or_controlled_exclusion_inventory"]
    protected_evidence = {
        name: _load_bound_artifact(binding)
        for name, binding in protected_inventory["evidence_bindings"].items()
    }
    strategic_range = next(
        entry
        for entry in protected_evidence["strategic_allocation_range"]["entries"]
        if entry["id"]
        == protected_inventory["evidence_bindings"]["strategic_allocation_range"]["source_entry_id"]
    )
    v3_validation = [
        period
        for period in protected_evidence["intraday_v3_selection"]["periods"]
        if period["role"] != "training"
    ]
    protected_ranges = {
        item["id"]: (
            datetime.fromisoformat(item["start"]).date(),
            datetime.fromisoformat(item["end"]).date(),
        )
        for item in protected_inventory["ranges"]
    }
    predecessor_chronology = protected_evidence["program_005_plan"][
        "chronology_and_protected_boundaries"
    ]
    assert protected_ranges == {
        "daily-independent-2018-2019": (
            datetime.fromisoformat(
                protected_evidence["daily_independent_range"]["sealed_boundaries"][
                    "independent_daily_range"
                ]["start"]
            ).date(),
            datetime.fromisoformat(
                protected_evidence["daily_independent_range"]["sealed_boundaries"][
                    "independent_daily_range"
                ]["end"]
            ).date(),
        ),
        "strategic-allocation-protected-holdout-2026": (
            datetime.fromisoformat(strategic_range["start"]).date(),
            datetime.fromisoformat(strategic_range["end"]).date(),
        ),
        "june-2026-reservation": (
            datetime.fromisoformat(
                protected_evidence["june_reservation"]["range"]["evaluation_start"]
            ).date(),
            datetime.fromisoformat(
                protected_evidence["june_reservation"]["range"]["evaluation_end"]
            ).date(),
        ),
        "intraday-v3-validation": (
            min(datetime.fromisoformat(period["start"]).date() for period in v3_validation),
            max(datetime.fromisoformat(period["end"]).date() for period in v3_validation),
        ),
        "controlled-a": (
            datetime.fromisoformat(predecessor_chronology["controlled_a"]["start"]).date(),
            datetime.fromisoformat(predecessor_chronology["controlled_a"]["end"]).date(),
        ),
        "controlled-b": (
            datetime.fromisoformat(predecessor_chronology["controlled_b"]["start"]).date(),
            datetime.fromisoformat(predecessor_chronology["controlled_b"]["end"]).date(),
        ),
    }
    protected = {
        session
        for session in sessions
        if any(
            range_start <= session <= range_end
            for range_start, range_end in protected_ranges.values()
        )
    }
    eligible_unobserved = tuple(session for session in sessions if session not in observed)
    excluded = observed | protected
    eligible = tuple(session for session in sessions if session not in excluded)

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
    assert len(eligible_unobserved) == audit["eligible_unobserved_session_count"]
    assert (
        fingerprint([str(value) for value in eligible_unobserved])
        == audit["eligible_unobserved_session_fingerprint"]
    )
    assert len(protected) == protected_inventory["in_eligible_chronology_session_count"]
    assert (
        fingerprint([str(value) for value in sorted(protected)])
        == protected_inventory["in_eligible_chronology_session_fingerprint"]
    )
    assert len(observed & protected) == protected_inventory["overlap_with_observed_session_count"]
    assert (
        fingerprint([str(value) for value in sorted(observed & protected)])
        == protected_inventory["overlap_with_observed_session_fingerprint"]
    )
    assert len(excluded) == audit["observed_or_protected_exclusion_union_count"]
    assert (
        fingerprint([str(value) for value in sorted(excluded)])
        == audit["observed_or_protected_exclusion_union_fingerprint"]
    )
    assert len(eligible) == audit["eligible_unobserved_unprotected_session_count"]
    assert (
        fingerprint([str(value) for value in eligible])
        == audit["eligible_unobserved_unprotected_session_fingerprint"]
    )

    missing_binding = proposal["preserved_economic_contract"]["missing_session_policy_binding"]
    predecessor_policy = _load_bound_artifact(missing_binding)[missing_binding["source_field"]]
    retained = missing_binding["retained_rules"]
    assert retained["minimum_cross_section"] == predecessor_policy["minimum_cross_section"]
    assert retained["incomplete_session_action"] == predecessor_policy["incomplete_session_action"]
    assert (
        retained["pre_exposed_design_quarantine_sessions"]
        == predecessor_policy["pre_exposed_design_quarantine"]["sessions"]
    )
    assert (
        retained["overall_excluded_full_session_count_max"]
        == predecessor_policy["global_loss_limit"]["overall_excluded_full_session_count_max"]
    )
    assert (
        retained["unexpected_excluded_full_session_count_max"]
        == predecessor_policy["global_loss_limit"]["unexpected_excluded_full_session_count_max"]
    )
    assert missing_binding["superseded_rules"] == []

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
    assert not set(selected) & protected
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
