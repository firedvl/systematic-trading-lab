from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime, time
from math import comb, floor
from pathlib import Path
from typing import Any, cast

from systematic_trading_lab.calendar import expected_bar_timestamps, expected_sessions
from systematic_trading_lab.domain import Timeframe
from systematic_trading_lab.fingerprints import fingerprint

_REPOSITORY = Path(__file__).resolve().parents[2]
_PROPOSAL_PATH = Path(
    "config/research/program-012-exposed-prefix-raw-alpaca-sip-acquisition-and-structural-admission-proposal-v1.json"
)


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_REPOSITORY / path).read_text(encoding="utf-8")))


def _assert_binding(binding: dict[str, str]) -> dict[str, Any]:
    path = Path(binding["path"])
    assert hashlib.sha256((_REPOSITORY / path).read_bytes()).hexdigest() == binding["sha256"]
    value = _load(path)
    if "fingerprint" in binding:
        assert binding["fingerprint"] in {
            item for key, item in value.items() if key.endswith("_fingerprint")
        }
    return value


def _hypergeometric_tail(population: int, successes: int, draws: int, threshold: int) -> float:
    denominator = comb(population, draws)
    return sum(
        comb(successes, selected) * comb(population - successes, draws - selected) / denominator
        for selected in range(threshold, min(successes, draws) + 1)
    )


def test_program_012_proposal_is_exact_protected_and_non_authorizing() -> None:
    proposal = _load(_PROPOSAL_PATH)
    stored_fingerprint = proposal.pop("proposal_fingerprint")
    assert stored_fingerprint == fingerprint(proposal)
    for binding in proposal["bindings"].values():
        _assert_binding(binding)

    chronology = proposal["chronology"]
    request = chronology["request_range"]
    start = datetime.combine(date.fromisoformat(request["start"]), time.min, tzinfo=UTC)
    end = datetime.combine(date.fromisoformat(request["end"]), time.max, tzinfo=UTC)
    sessions = expected_sessions(start, end)
    bars = expected_bar_timestamps(start, end, Timeframe.FIVE_MINUTES)
    bars_by_session = Counter(timestamp.date() for timestamp in bars)
    early_closes = tuple(
        session.isoformat() for session in sessions if bars_by_session[session] == 42
    )

    assert len(sessions) == request["session_count"] == 1_386
    assert Counter(bars_by_session.values()) == {78: 1_374, 42: 12}
    assert len(bars) * 13 == request["expected_coordinates"] == 1_399_788
    assert early_closes == tuple(chronology["early_close_sessions"])
    assert sum(block["sessions"] for block in chronology["structural_blocks"]) == 1_386
    assert sum(block["expected_coordinates"] for block in chronology["structural_blocks"]) == (
        1_399_788
    )

    protected = _load(Path(proposal["bindings"]["protected_chronology"]["path"]))
    request_start = date.fromisoformat(request["start"])
    request_end = date.fromisoformat(request["end"])
    assert all(
        request_end < date.fromisoformat(item["start"])
        or request_start > date.fromisoformat(item["end"])
        for item in protected["ranges"]
    )
    assert chronology["protected_overlap"]["request_session_count"] == 0
    assert chronology["protected_overlap"]["protected_sessions_enter_any_denominator"] is False

    budget = proposal["transport_budgets"]
    assert budget["nominal_complete_requests_and_responses"] == 1_374 * 2 + 12 == 2_760
    assert budget["maximum_requests_and_responses"] == 1_386 * 16 == 22_176
    assert budget["automatic_retries"] == budget["parallel_session_chains"] - 1 == 0

    source = proposal["source_contract"]
    assert (
        source["method"],
        source["endpoint"],
        source["feed"],
        source["timeframe"],
        source["adjustment"],
        source["sort"],
        source["limit"],
        source["asof"],
    ) == (
        "GET",
        "https://data.alpaca.markets/v2/stocks/bars",
        "sip",
        "5Min",
        "raw",
        "asc",
        1_000,
        "2026-07-31",
    )
    assert source["symbols"] == [
        "IWM",
        "MDY",
        "SPY",
        "XLB",
        "XLE",
        "XLF",
        "XLI",
        "XLK",
        "XLP",
        "XLRE",
        "XLU",
        "XLV",
        "XLY",
    ]
    assert source["provider_adjusted_view_allowed"] is False
    assert source["alternate_provider_allowed"] is False
    assert source["automatic_retries"] == 0

    pagination = proposal["pagination_contract"]
    assert pagination["terminal_condition"] == "next_page_token is null"
    assert pagination["raw_body_fsynced_before_parse_or_continuation"] is True
    assert pagination["maximum_pages_per_session"] == 16
    assert pagination["incomplete_chain_allows_dataset_admission"] is False
    restart = proposal["restart_contract"]
    assert restart["restart_safe_required"] is True
    assert restart["request_reissue_allowed"] is False
    assert restart["completed_session_reacquisition_allowed"] is False
    assert restart["intent_without_completed_page"] == (
        "AMBIGUOUS-SEND-TERMINAL-FAIL-CONSUMED-NO-RETRY"
    )
    assert restart["raw_body_without_response_receipt"] == (
        "AMBIGUOUS-PERSISTENCE-TERMINAL-FAIL-CONSUMED-NO-RETRY"
    )
    assert restart["changed_or_unverifiable_checkpoint"] == "FAIL-CONSUMED-NO-RETRY"
    assert restart["transport_retries"] == 0
    evidence = proposal["evidence_contract"]
    assert evidence["create_only_raw_pages"] is True
    assert evidence["create_only_request_intents"] is True
    assert evidence["create_only_response_receipts"] is True

    missingness = proposal["missingness_policy"]
    loss = missingness["global_loss_limit"]
    assert loss["overall_excluded_full_session_count_max"] == floor(1_354 * 7 / 1_499) == 6
    assert loss["unexpected_excluded_full_session_count_max"] == (
        6 - missingness["fixed_quarantine"]["session_count"]
    )
    clock = missingness["fixed_clock_concentration"]
    assert clock["uniform_coordinate_population"] == 1_354 * 78
    assert clock["exact_hypergeometric_tail_probability_at_rejection_count"] == format(
        _hypergeometric_tail(105_612, 1_354, 9, 3), ".12f"
    )
    bias = missingness["spy_mdy_morning_bias_diagnostic"]
    assert bias["tail_size_sessions"] == 339
    assert bias["exact_hypergeometric_tail_probabilities_at_rejection_count"] == {
        "5": format(_hypergeometric_tail(1_354, 339, 5, 5), ".12f"),
        "6": format(_hypergeometric_tail(1_354, 339, 6, 5), ".12f"),
    }

    canonical = proposal["canonical_data_contract"]
    admission = proposal["structural_admission_contract"]
    assert canonical["raw_prices_changed"] is False
    assert canonical["normalized_volume_materialized_during_program_012"] is False
    assert admission["program_002_admission"] is False
    assert admission["program_002_quote_windows_evaluated"] == 0
    assert admission["historical_final_exposed_fold_claim"] is False
    assert proposal["external_authorization_root"] is None
    assert all(value is False for value in proposal["authority"].values())
    implementation = proposal["implementation_boundary"]
    assert all(
        implementation[key] is False
        for key in (
            "runtime_present",
            "credential_reader_or_presence_check_added",
            "provider_transport_added",
            "private_store_added",
            "authority_activation_added",
            "dataset_admission_runtime_added",
        )
    )
    assert implementation["focused_tests_required"] is True
