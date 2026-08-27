from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

from systematic_trading_lab.domain import Symbol
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.multi_hour_sector_etf_engine import (
    Program002CostScenario,
    maximum_drawdown,
    replay_program_002_session,
)
from systematic_trading_lab.multi_hour_sector_etf_features import build_selection_trace
from systematic_trading_lab.multi_hour_sector_etf_plan import load_program_002_plan
from systematic_trading_lab.multi_hour_sector_etf_synthetic import (
    build_synthetic_program_002_fixture,
)

_REPOSITORY = Path(__file__).resolve().parents[2]
_PLAN_PATH = "config/research/program-004-marketparquet-successor-plan-v1.json"


def _load(path: str) -> dict[str, Any]:
    value = json.loads((_REPOSITORY / path).read_text())
    assert isinstance(value, dict)
    return value


def test_program_004_plan_binds_predecessor_and_grants_no_authority() -> None:
    plan = _load(_PLAN_PATH)
    unsigned = dict(plan)

    assert unsigned.pop("plan_fingerprint") == fingerprint(unsigned)
    assert plan["program_id"] == "multi-hour-sector-etf-research-003"
    assert plan["lineage"]["predecessor_strategy_outcomes_generated_or_observed"] == 0
    assert plan["lineage"]["predecessor_source_qualification_executed"] is False
    assert plan["lineage"]["economic_hypothesis_changed"] is False

    predecessor = plan["predecessor_contract"]
    predecessor_path = _REPOSITORY / predecessor["plan_path"]
    predecessor_plan = json.loads(predecessor_path.read_text())
    assert sha256(predecessor_path.read_bytes()).hexdigest() == predecessor["plan_sha256"]
    assert predecessor_plan["plan_fingerprint"] == predecessor["plan_fingerprint"]

    predecessor_review_path = _REPOSITORY / predecessor["review_path"]
    predecessor_review = json.loads(predecessor_review_path.read_text())
    assert sha256(predecessor_review_path.read_bytes()).hexdigest() == predecessor["review_sha256"]
    assert predecessor_review["review_fingerprint"] == predecessor["review_fingerprint"]

    hypothesis = plan["preserved_economic_contract"]
    assert hypothesis["configuration_count"] == 8
    assert hypothesis["lookback_minutes"] == [30, 60]
    assert hypothesis["hold_minutes"] == [120, 240]
    assert hypothesis["portfolio"]["fractional_equal_dollar_slots"] is True
    assert hypothesis["additional_search_allowed"] is False

    license_gate = plan["licensing_gate"]
    assert license_gate["verdict"] == "PASS-FOR-CONSTRAINED-INTERNAL-RESEARCH"
    assert all(license_gate["permitted"].values())
    assert all(license_gate["prohibited"].values())
    assert plan["purchase_design"]["keep_current_subscription_allowed"] is False
    assert plan["purchase_design"]["recurring_cost_required_usd_per_month"] == "0"

    source = plan["canonical_data_design"]
    assert source["selected_source"] == "MarketParquet etf_5min"
    assert source["selected_timeframe"] == "provider-native-5min"
    assert source["fallback"] is None
    assert source["generic_import_reuse_allowed"] is False
    assert plan["provenance_gate"]["official_sip_claimed"] is False
    assert plan["provenance_gate"]["nbbo_claimed_or_required"] is False

    qualification = plan["source_qualification"]
    assert qualification["status"] == "DESIGNED-NOT-AUTHORIZED"
    assert qualification["fixed_sessions"]["date_file_count"] == 15
    assert qualification["fixed_sessions"]["expected_regular_session_rows"] == 14_742
    assert len(qualification["known_mdy_coordinates"]) == 9
    budget = qualification["purchase_and_transport_budget"]
    assert budget["maximum_authenticated_presigned_url_responses"] == 15
    assert budget["maximum_presigned_file_responses"] == 15
    assert budget["maximum_http_responses"] == 30
    assert budget["maximum_credential_loads"] == 1

    missing = plan["inherited_missing_data_policy"]
    assert missing["changed_for_marketparquet"] is False
    assert missing["maximum_loss"]["overall_excluded_full_session_count_max"] == 7
    assert missing["maximum_loss"]["required_exposed_context_loss_max"] == 0

    costs = plan["inherited_cost_model"]
    assert {
        name: (values["total_bps_per_side"], values["delay_minutes"])
        for name, values in costs["scenarios"].items()
    } == {"normal": ("6", 5), "stress_a": ("12", 10), "stress_b": ("25", 15)}
    assert costs["fractional_shares"] is True
    assert costs["integer_share_rounding"] is False
    assert costs["per_share_or_fixed_dollar_fee"] is False

    controlled = plan["chronology_and_protected_boundaries"]
    assert (controlled["controlled_a"]["start"], controlled["controlled_a"]["end"]) == (
        "2027-04-16",
        "2027-10-15",
    )
    assert (controlled["controlled_b"]["start"], controlled["controlled_b"]["end"]) == (
        "2027-10-18",
        "2028-04-14",
    )
    assert not any(plan["authority"].values())
    assert not any(plan["protected_access"].values())


def test_constant_split_representation_preserves_trace_notional_profit_and_drawdown() -> None:
    fixture = build_synthetic_program_002_fixture()
    configuration = load_program_002_plan(_REPOSITORY).configurations["src-v1-l1-h4"]
    factors = {
        symbol: Decimal(2 if index % 2 else 4)
        for index, symbol in enumerate(sorted({bar.symbol for bar in fixture.bars}))
    }
    adjusted = tuple(
        replace(
            bar,
            open=bar.open / factors[bar.symbol],
            high=bar.high / factors[bar.symbol],
            low=bar.low / factors[bar.symbol],
            close=bar.close / factors[bar.symbol],
            volume=bar.volume * int(factors[bar.symbol]),
        )
        for bar in fixture.bars
    )

    raw_trace = build_selection_trace(fixture.bars, fixture.normal_day, configuration)
    adjusted_trace = build_selection_trace(adjusted, fixture.normal_day, configuration)
    assert adjusted_trace.selected_symbols == raw_trace.selected_symbols
    raw_features = {feature.symbol: feature for feature in raw_trace.ordered_features}
    adjusted_features = {feature.symbol: feature for feature in adjusted_trace.ordered_features}
    for symbol, raw in raw_features.items():
        changed = adjusted_features[symbol]
        assert changed.lookback_return == raw.lookback_return
        assert changed.spy_return == raw.spy_return
        assert changed.residual_return == raw.residual_return
        assert changed.same_clock_relative_volume == raw.same_clock_relative_volume
        assert changed.prior_median_dollar_volume == raw.prior_median_dollar_volume

    scenario = Program002CostScenario(
        "program-004-synthetic-zero-cost",
        {symbol: Decimal("0") for symbol in factors},
        1,
        False,
    )
    raw_replay = replay_program_002_session(raw_trace, fixture.bars, scenario, None)
    adjusted_replay = replay_program_002_session(adjusted_trace, adjusted, scenario, None)

    assert adjusted_replay.candidate.final_cash == raw_replay.candidate.final_cash
    assert abs(
        adjusted_replay.candidate.gross_market_profit - raw_replay.candidate.gross_market_profit
    ) <= Decimal("1e-24")
    assert adjusted_replay.candidate.adverse_spread_cost == raw_replay.candidate.adverse_spread_cost
    assert adjusted_replay.candidate.net_profit == raw_replay.candidate.net_profit
    assert tuple(value for _, value in adjusted_replay.candidate.equity_curve) == tuple(
        value for _, value in raw_replay.candidate.equity_curve
    )
    assert maximum_drawdown(adjusted_replay.candidate) == maximum_drawdown(raw_replay.candidate)
    for raw_fill, adjusted_fill in zip(
        raw_replay.candidate.fills, adjusted_replay.candidate.fills, strict=True
    ):
        factor = factors[raw_fill.symbol]
        assert abs(adjusted_fill.quantity - raw_fill.quantity * factor) <= Decimal("1e-24")
        assert adjusted_fill.market_open == raw_fill.market_open / factor
        assert abs(adjusted_fill.gross_notional - raw_fill.gross_notional) <= Decimal("1e-22")
        adjusted_cost = adjusted_fill.gross_notional * Decimal("6") / Decimal("10000")
        raw_cost = raw_fill.gross_notional * Decimal("6") / Decimal("10000")
        assert abs(adjusted_cost - raw_cost) <= Decimal("1e-22")


def test_split_spanning_volume_window_matches_one_common_share_unit() -> None:
    fixture = build_synthetic_program_002_fixture()
    configuration = load_program_002_plan(_REPOSITORY).configurations["src-v1-l1-h4"]
    prior_days = set(fixture.prior_days)
    contemporaneous = tuple(
        replace(
            bar,
            open=bar.open * 2,
            high=bar.high * 2,
            low=bar.low * 2,
            close=bar.close * 2,
            volume=bar.volume // 2,
        )
        if bar.timestamp.date() in prior_days
        else bar
        for bar in fixture.bars
    )
    normalized = tuple(
        replace(
            bar,
            open=bar.open / 2,
            high=bar.high / 2,
            low=bar.low / 2,
            close=bar.close / 2,
            volume=bar.volume * 2,
        )
        if bar.timestamp.date() in prior_days
        else bar
        for bar in contemporaneous
    )

    raw_trace = build_selection_trace(contemporaneous, fixture.normal_day, configuration)
    normalized_trace = build_selection_trace(normalized, fixture.normal_day, configuration)
    baseline_trace = build_selection_trace(fixture.bars, fixture.normal_day, configuration)
    raw_iwm = next(
        feature for feature in raw_trace.ordered_features if feature.symbol == Symbol("IWM")
    )
    normalized_iwm = next(
        feature for feature in normalized_trace.ordered_features if feature.symbol == Symbol("IWM")
    )
    baseline_iwm = next(
        feature for feature in baseline_trace.ordered_features if feature.symbol == Symbol("IWM")
    )

    assert raw_iwm.same_clock_relative_volume == Decimal("2.4")
    assert normalized_iwm.same_clock_relative_volume == Decimal("1.2")
    assert normalized_iwm == baseline_iwm

    before_split = Decimal(120) / Decimal(100)
    before_split_adjusted = Decimal(240) / Decimal(200)
    spanning_split = Decimal(220) / Decimal(200)
    same_economic_volume_in_old_units = Decimal(110) / Decimal(100)
    after_split = Decimal(220) / Decimal(200)
    assert before_split_adjusted == before_split == Decimal("1.2")
    assert spanning_split == same_economic_volume_in_old_units == Decimal("1.1")
    assert after_split == Decimal("1.1")
