from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
from typing import Any

from systematic_trading_lab.calendar import expected_sessions
from systematic_trading_lab.domain import Symbol
from systematic_trading_lab.fingerprints import fingerprint
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


def _as_utc(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _fraction_drawdown(initial_cash: Fraction, equity_curve: tuple[Fraction, ...]) -> Fraction:
    peak = initial_cash
    drawdown = Fraction(0)
    for equity in equity_curve:
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak)
    return drawdown


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


def test_full_acquisition_count_includes_context_and_reuses_qualification_files() -> None:
    plan = _load(_PLAN_PATH)
    predecessor = _load(plan["predecessor_contract"]["plan_path"])
    acquisition = plan["full_acquisition_design"]
    date_range = acquisition["exact_date_range"]
    chronology = predecessor["chronology"]

    context = chronology["exposed_context_only"]
    context_sessions = expected_sessions(_as_utc(context["start"]), _as_utc(context["end"]))
    exposed_sessions = expected_sessions(
        _as_utc(chronology["discovery_blocks"][0]["start"]),
        _as_utc(plan["chronology_and_protected_boundaries"]["exposed_range_end"]),
    )
    acquisition_sessions = expected_sessions(
        _as_utc(date_range["start"]), _as_utc(date_range["end"])
    )

    assert acquisition_sessions == context_sessions + exposed_sessions
    assert len(context_sessions) == date_range["required_context_date_files"] == 20
    assert len(exposed_sessions) == date_range["exposed_evaluation_date_files"] == 1_511
    assert len(acquisition_sessions) == date_range["expected_xnys_date_files"] == 1_531

    fixed = plan["source_qualification"]["fixed_sessions"]
    qualification_sessions = {
        datetime.fromisoformat(value).date()
        for group in (
            "known_mdy_gap_sessions",
            "normal_controls",
            "early_close_control",
            "split_neighborhood",
            "distribution_neighborhood",
        )
        for value in fixed[group]
    }
    reused = len(qualification_sessions & set(acquisition_sessions))
    assert (
        reused == fixed["date_file_count"] == acquisition["qualification_date_files_reused"] == 15
    )
    assert (
        acquisition["maximum_additional_date_files"] == len(acquisition_sessions) - reused == 1_516
    )


def test_constant_split_representation_preserves_trace() -> None:
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


def test_fractional_split_representation_preserves_exact_cost_replay() -> None:
    fixture = build_synthetic_program_002_fixture()
    configuration = load_program_002_plan(_REPOSITORY).configurations["src-v1-l1-h4"]
    trace = build_selection_trace(fixture.bars, fixture.normal_day, configuration)
    symbols = trace.selected_symbols
    factors = dict(zip(symbols, (Fraction(3, 2), Fraction(2), Fraction(5, 2)), strict=True))
    bars = {(bar.symbol, bar.timestamp): bar for bar in fixture.bars}
    initial_cash = Fraction(100_000)
    slot_weight = Fraction(Decimal("0.3333333333333333333333333333"))

    for bps, delay_bars in ((6, 1), (12, 2), (25, 3)):
        rate = Fraction(bps, 10_000)
        entry = trace.decision_timestamp + timedelta(minutes=5 * delay_bars)
        exit_at = entry + timedelta(minutes=30 * trace.hold_30m_bars)
        raw_entry = {symbol: Fraction(bars[symbol, entry].open) for symbol in symbols}
        raw_exit = {symbol: Fraction(bars[symbol, exit_at].open) for symbol in symbols}
        adjusted_entry = {symbol: raw_entry[symbol] / factors[symbol] for symbol in symbols}
        adjusted_exit = {symbol: raw_exit[symbol] / factors[symbol] for symbol in symbols}
        raw_buy = {symbol: raw_entry[symbol] * (1 + rate) for symbol in symbols}
        raw_sell = {symbol: raw_exit[symbol] * (1 - rate) for symbol in symbols}
        adjusted_buy = {symbol: adjusted_entry[symbol] * (1 + rate) for symbol in symbols}
        adjusted_sell = {symbol: adjusted_exit[symbol] * (1 - rate) for symbol in symbols}
        raw_quantity = {symbol: slot_weight * initial_cash / raw_buy[symbol] for symbol in symbols}
        adjusted_quantity = {
            symbol: slot_weight * initial_cash / adjusted_buy[symbol] for symbol in symbols
        }

        raw_buy_notional = {symbol: raw_quantity[symbol] * raw_buy[symbol] for symbol in symbols}
        raw_sell_notional = {symbol: raw_quantity[symbol] * raw_sell[symbol] for symbol in symbols}
        adjusted_buy_notional = {
            symbol: adjusted_quantity[symbol] * adjusted_buy[symbol] for symbol in symbols
        }
        adjusted_sell_notional = {
            symbol: adjusted_quantity[symbol] * adjusted_sell[symbol] for symbol in symbols
        }
        for symbol in symbols:
            assert adjusted_buy[symbol] == raw_buy[symbol] / factors[symbol]
            assert adjusted_sell[symbol] == raw_sell[symbol] / factors[symbol]
            assert adjusted_quantity[symbol] == raw_quantity[symbol] * factors[symbol]
            assert adjusted_buy_notional[symbol] == raw_buy_notional[symbol]
            assert adjusted_sell_notional[symbol] == raw_sell_notional[symbol]

        raw_gross = sum(
            (raw_quantity[symbol] * (raw_exit[symbol] - raw_entry[symbol]) for symbol in symbols),
            Fraction(0),
        )
        adjusted_gross = sum(
            (
                adjusted_quantity[symbol] * (adjusted_exit[symbol] - adjusted_entry[symbol])
                for symbol in symbols
            ),
            Fraction(0),
        )
        raw_cost = sum(
            (
                raw_quantity[symbol]
                * (raw_buy[symbol] - raw_entry[symbol] + raw_exit[symbol] - raw_sell[symbol])
                for symbol in symbols
            ),
            Fraction(0),
        )
        adjusted_cost = sum(
            (
                adjusted_quantity[symbol]
                * (
                    adjusted_buy[symbol]
                    - adjusted_entry[symbol]
                    + adjusted_exit[symbol]
                    - adjusted_sell[symbol]
                )
                for symbol in symbols
            ),
            Fraction(0),
        )
        raw_final = initial_cash - sum(raw_buy_notional.values()) + sum(raw_sell_notional.values())
        adjusted_final = (
            initial_cash
            - sum(adjusted_buy_notional.values())
            + sum(adjusted_sell_notional.values())
        )
        raw_net = raw_final - initial_cash
        adjusted_net = adjusted_final - initial_cash

        assert raw_gross == adjusted_gross
        assert raw_cost == adjusted_cost > 0
        assert raw_net == adjusted_net == raw_gross - raw_cost
        assert raw_final - (initial_cash + raw_gross - raw_cost) == 0
        assert adjusted_final - (initial_cash + adjusted_gross - adjusted_cost) == 0

        timestamps = tuple(
            timestamp
            for timestamp in sorted(
                bar.timestamp for bar in fixture.bars if bar.symbol == symbols[0]
            )
            if entry <= timestamp <= exit_at
        )
        raw_entry_cash = initial_cash - sum(raw_buy_notional.values())
        adjusted_entry_cash = initial_cash - sum(adjusted_buy_notional.values())
        raw_curve = (
            raw_entry_cash + sum(raw_quantity[symbol] * raw_entry[symbol] for symbol in symbols),
            *(
                raw_entry_cash
                + sum(
                    raw_quantity[symbol] * Fraction(bars[symbol, timestamp].close)
                    for symbol in symbols
                )
                for timestamp in timestamps[:-1]
            ),
            raw_final,
        )
        adjusted_curve = (
            adjusted_entry_cash
            + sum(adjusted_quantity[symbol] * adjusted_entry[symbol] for symbol in symbols),
            *(
                adjusted_entry_cash
                + sum(
                    adjusted_quantity[symbol]
                    * Fraction(bars[symbol, timestamp].close)
                    / factors[symbol]
                    for symbol in symbols
                )
                for timestamp in timestamps[:-1]
            ),
            adjusted_final,
        )
        assert adjusted_curve == raw_curve
        assert _fraction_drawdown(initial_cash, adjusted_curve) == _fraction_drawdown(
            initial_cash, raw_curve
        )


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
