from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from systematic_trading_lab.intraday_exposure import (
    ExposureInventory,
    V3PeriodSelection,
    assess_validation_exposure,
    load_intraday_exposure_inventory,
    load_intraday_v3_period_selection,
    parse_intraday_exposure_inventory,
    parse_intraday_v3_period_selection,
)

_INVENTORY_PATH = Path("config/research/intraday-known-exposures-v1.json")
_SELECTION_PATH = Path("config/research/intraday-v3-period-selection-v2.json")


def _inventory() -> ExposureInventory:
    return load_intraday_exposure_inventory(_INVENTORY_PATH)


def _selection(inventory: ExposureInventory) -> V3PeriodSelection:
    return load_intraday_v3_period_selection(_SELECTION_PATH, inventory)


def test_real_market_v2_and_daily_acquisition_overlap_are_rejected() -> None:
    inventory = _inventory()

    v2 = assess_validation_exposure(inventory, date(2026, 6, 1), date(2026, 6, 12))
    daily = assess_validation_exposure(inventory, date(2026, 7, 1), date(2026, 7, 31))

    assert v2.status == "rejected"
    assert "intraday-v2-real-market-results" in v2.overlapping_entry_ids
    assert daily.status == "rejected"
    assert daily.overlapping_entry_ids == (
        "daily-alpaca-baselines-2020-07-27-through-2026-07-31",
        "strategic-allocation-protected-holdout-2026",
    )


def test_synthetic_fixture_and_date_reference_do_not_contaminate_future_period() -> None:
    inventory = _inventory()

    fixture = next(
        entry for entry in inventory.entries if entry.classification == "synthetic-fixture"
    )
    reference = next(
        entry for entry in inventory.entries if entry.classification == "date-only-reference"
    )

    assert not fixture.disqualifies_v3_validation
    assert not reference.disqualifies_v3_validation
    assessment = assess_validation_exposure(inventory, date(2026, 8, 12), date(2026, 8, 13))
    assert assessment.status == "unresolved"
    future = assess_validation_exposure(inventory, date(2026, 10, 1), date(2026, 12, 3))
    assert future.status == "unresolved"
    assert future.overlapping_entry_ids == ()


def test_unknown_external_state_stays_unresolved() -> None:
    inventory = _inventory()

    assessment = assess_validation_exposure(inventory, date(2027, 1, 1), date(2027, 1, 31))

    assert assessment.status == "unresolved"
    assert assessment.unresolved_entry_ids == (
        "unknown-dated-iex-quote-runtime-evidence",
        "unknown-local-and-external-state",
    )


def test_inventory_and_selection_fingerprints_are_deterministic_and_tampering_rejected() -> None:
    inventory_raw = json.loads(_INVENTORY_PATH.read_text(encoding="utf-8"))
    selection_raw = json.loads(_SELECTION_PATH.read_text(encoding="utf-8"))
    inventory = parse_intraday_exposure_inventory(inventory_raw)
    selection = parse_intraday_v3_period_selection(selection_raw, inventory)

    assert (
        inventory.inventory_fingerprint
        == parse_intraday_exposure_inventory(inventory_raw).inventory_fingerprint
    )
    assert (
        selection.selection_fingerprint
        == parse_intraday_v3_period_selection(selection_raw, inventory).selection_fingerprint
    )
    inventory_raw["inventory_fingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="fingerprint differs"):
        parse_intraday_exposure_inventory(inventory_raw)
    selection_raw["selection_fingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="fingerprint differs"):
        parse_intraday_v3_period_selection(selection_raw, inventory)


def test_selection_uses_exact_calendar_counts_and_future_validation() -> None:
    inventory = _inventory()
    selection = _selection(inventory)

    counts = [
        (period.session_count, period.per_symbol_bar_opens, period.two_symbol_bar_opens)
        for period in selection.periods
    ]
    assert counts == [
        (251, 19470, 38940),
        (45, 3474, 6948),
        (45, 3474, 6948),
        (45, 3510, 7020),
    ]
    assert selection.periods[0].exposed_training
    assert all(period.selection_rationale for period in selection.periods)
    assert not selection.periods[0].approved_for_v3_validation
    assert all(period.start > selection.selection_date for period in selection.periods[1:])
    assert not selection.selection_date_is_authoritative
    assert selection.trusted_cutoff_source == "verified-main-seal-tlog-timestamp"
    assert not any(period.approved_for_v3_validation for period in selection.periods[1:])
    assert all(period.prospective_freshness_eligible for period in selection.periods[1:])
    assert selection.status == "prospective-freshness-eligible-awaiting-pre-bar-main-attestation"
    assert not selection.universal_freshness_proven
    assert not selection.prospective_market_data_freshness
    assert selection.prospective_market_data_freshness_eligible


def test_training_exposure_requires_explicit_training_only_status() -> None:
    inventory = _inventory()
    raw = json.loads(_SELECTION_PATH.read_text(encoding="utf-8"))
    raw["periods"][0]["exposed_training"] = False

    with pytest.raises(ValueError, match="explicitly exposed"):
        parse_intraday_v3_period_selection(raw, inventory)


def test_unattested_selection_cannot_claim_validation_approval() -> None:
    inventory = _inventory()
    raw = json.loads(_SELECTION_PATH.read_text(encoding="utf-8"))
    raw["periods"][1]["approved_for_v3_validation"] = True

    with pytest.raises(ValueError, match="review status differs"):
        parse_intraday_v3_period_selection(raw, inventory)
