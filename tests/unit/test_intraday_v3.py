from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest

from systematic_trading_lab.backtesting import BacktestError, CostModel
from systematic_trading_lab.calendar import expected_bar_timestamps
from systematic_trading_lab.campaign_specs import parse_intraday_research_campaign_plan
from systematic_trading_lab.datasets import intraday_fixture_request, intraday_fixture_symbols
from systematic_trading_lab.domain import OHLCVBar, Symbol, Timeframe
from systematic_trading_lab.experiments import ExperimentSplit
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.intraday_qualification import (
    evaluate_intraday_qualification,
    load_intraday_qualification_policy,
)
from systematic_trading_lab.intraday_reporting import (
    IntradayMovingAverageTrendPortfolioStrategy,
)
from systematic_trading_lab.intraday_v3 import (
    V3_AUTHORITY_POLICY,
    V3_DIAGNOSTIC_POLICY,
    V3_EARLIEST_FILL_SEMANTICS,
    V3_EXECUTION_MODEL,
    V3_MA_STRATEGY_ID,
    V3_MOMENTUM_STRATEGY_ID,
    V3_OPENING_RANGE_STRATEGY_ID,
    V3_PERIODIC_REBALANCE_POLICY,
    V3_QUEUE_POLICY,
    V3_SESSION_POLICY,
    EventDrivenMovingAverageTrendStrategy,
    IntradayV3ExperimentSpec,
    StateTransitionBacktestEngine,
    ThirtyMinuteMomentumStrategy,
    ThirtyMinuteOpeningRangeBreakoutStrategy,
    build_v3_diagnostic_report,
    load_v3_campaign_draft,
    parse_v3_campaign_draft,
    run_v3_diagnostic,
    v3_strategy,
    validate_v3_period_selection,
    write_v3_diagnostic_report,
)
from systematic_trading_lab.providers import IntradayFixtureProvider
from systematic_trading_lab.strategies import TargetPosition

_NEW_YORK = ZoneInfo("America/New_York")
_SYMBOLS = (Symbol("QQQ"), Symbol("SPY"))
_FREE = CostModel("zero-test-cost-v1", Decimal("0"), Decimal("0"))


def _bars() -> tuple[OHLCVBar, ...]:
    records = IntradayFixtureProvider().fetch(
        intraday_fixture_symbols(), Timeframe.FIVE_MINUTES, intraday_fixture_request()
    )
    return tuple(OHLCVBar.from_record(record) for record in records)


def _normal_session_bars() -> tuple[OHLCVBar, ...]:
    return tuple(
        bar for bar in _bars() if bar.timestamp.astimezone(_NEW_YORK).date() == date(2025, 11, 26)
    )


class ScriptedStateStrategy:
    strategy_id = "scripted-v3-state"
    version = "1"

    def __init__(self, states: Sequence[Decimal]) -> None:
        self.states = tuple(states)

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        session = bars[0].timestamp.astimezone(_NEW_YORK).date()
        index = (
            sum(
                bar.timestamp.astimezone(_NEW_YORK).date() == session
                for bar in history[Symbol("SPY")]
            )
            - 1
        )
        state = self.states[index] if index < len(self.states) else self.states[-1]
        return (
            TargetPosition(Symbol("QQQ"), Decimal("0"), "scripted"),
            TargetPosition(Symbol("SPY"), state, "scripted"),
        )


class AlwaysLongStrategy:
    strategy_id = "always-long-v3-state"
    version = "1"

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        return tuple(TargetPosition(symbol, Decimal("0.5"), "always-long") for symbol in _SYMBOLS)


class ScriptedRotationStrategy:
    strategy_id = "scripted-v3-rotation"
    version = "1"

    def __init__(self, states: Sequence[tuple[Decimal, Decimal]]) -> None:
        self.states = tuple(states)

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        session = bars[0].timestamp.astimezone(_NEW_YORK).date()
        index = (
            sum(
                bar.timestamp.astimezone(_NEW_YORK).date() == session
                for bar in history[Symbol("SPY")]
            )
            - 1
        )
        weights = self.states[index] if index < len(self.states) else self.states[-1]
        return tuple(
            TargetPosition(symbol, weight, "scripted-rotation")
            for symbol, weight in zip(_SYMBOLS, weights, strict=True)
        )


def _engine(delay: int = 1, costs: CostModel = _FREE) -> StateTransitionBacktestEngine:
    return StateTransitionBacktestEngine(Decimal("100000"), costs, delay)


def test_unchanged_target_state_and_price_drift_do_not_rebalance() -> None:
    result = _engine().run(_normal_session_bars(), AlwaysLongStrategy())

    assert len(result.decisions) == 78
    assert result.desired_state_change_count == 2
    assert result.executed_state_transition_count == 4
    assert len(result.trades) == 4
    assert sum(trade.quantity > 0 for trade in result.trades) == 2
    assert sum(trade.quantity < 0 for trade in result.trades) == 2
    assert result.periodic_rebalance_count == 0
    assert all(quantity == 0 for _, quantity in result.equity_curve[-1].positions)


def test_zero_to_half_to_zero_produces_one_entry_and_exit() -> None:
    states = (Decimal("0"), Decimal("0.5"), Decimal("0.5"), Decimal("0"))
    result = _engine().run(_normal_session_bars(), ScriptedStateStrategy(states))

    assert result.desired_state_change_count == 2
    assert result.executed_state_transition_count == 2
    assert [trade.quantity > 0 for trade in result.trades] == [True, False]
    assert [item.to_weight for item in result.transitions if item.status == "filled"] == [
        Decimal("0.5"),
        Decimal("0"),
    ]


def test_delay_preserves_decision_cadence_and_fifo_state_changes() -> None:
    states = (
        Decimal("0"),
        Decimal("0.5"),
        Decimal("0"),
        Decimal("0.5"),
        Decimal("0"),
    )
    results = {
        delay: _engine(delay).run(_normal_session_bars(), ScriptedStateStrategy(states))
        for delay in (1, 2, 3)
    }

    assert {len(result.decisions) for result in results.values()} == {78}
    assert {result.desired_state_change_count for result in results.values()} == {4}
    assert {result.executed_state_transition_count for result in results.values()} == {4}
    assert {
        tuple(decision.timestamp for decision in result.decisions) for result in results.values()
    } == {tuple(decision.timestamp for decision in results[1].decisions)}
    for delay, result in results.items():
        filled = tuple(item for item in result.transitions if item.source == "strategy")
        assert [item.status for item in filled] == ["filled"] * 4
        assert [item.to_weight for item in filled] == [
            Decimal("0.5"),
            Decimal("0"),
            Decimal("0.5"),
            Decimal("0"),
        ]
        assert all(
            item.eligible_fill_timestamp
            == result.decisions[1 + index].timestamp + Timeframe.FIVE_MINUTES.duration * (delay - 1)
            for index, item in enumerate(filled)
        )


def test_same_open_cross_symbol_transitions_preserve_global_fifo_order() -> None:
    bars = _normal_session_bars()
    result = _engine().run(
        bars,
        ScriptedRotationStrategy(
            (
                (Decimal("0"), Decimal("0.5")),
                (Decimal("0.5"), Decimal("0")),
            )
        ),
    )
    shared_fill = sorted({bar.timestamp for bar in bars})[2]
    rotation = tuple(
        item
        for item in result.transitions
        if item.eligible_fill_timestamp == shared_fill and item.status == "filled"
    )

    assert [(item.sequence, item.symbol, item.to_weight) for item in rotation] == [
        (2, Symbol("QQQ"), Decimal("0.5")),
        (3, Symbol("SPY"), Decimal("0")),
    ]


@pytest.mark.parametrize("delay", (1, 2, 3))
def test_session_close_flattens_normal_and_early_close_under_all_delays(delay: int) -> None:
    bars = _bars()
    result = _engine(delay).run(bars, AlwaysLongStrategy())
    final_opens = {
        max(
            bar.timestamp
            for bar in bars
            if bar.symbol == symbol and bar.timestamp.astimezone(_NEW_YORK).date() == session
        )
        for symbol in _SYMBOLS
        for session in (date(2025, 11, 26), date(2025, 11, 28))
    }

    assert {trade.fill_timestamp for trade in result.trades if trade.quantity < 0} == final_opens
    assert all(trade.fill_timestamp in {bar.timestamp for bar in bars} for trade in result.trades)
    assert all(
        trade.decision_timestamp <= trade.fill_timestamp
        and trade.decision_timestamp.astimezone(_NEW_YORK).date()
        == trade.fill_timestamp.astimezone(_NEW_YORK).date()
        for trade in result.trades
    )
    final_by_session: dict[date, tuple[tuple[Symbol, Decimal], ...]] = {}
    for point in result.equity_curve:
        final_by_session[point.timestamp.astimezone(_NEW_YORK).date()] = point.positions
    assert all(
        all(quantity == 0 for _, quantity in positions) for positions in final_by_session.values()
    )


def test_session_close_override_records_canceled_and_rejected_late_states() -> None:
    bars = _normal_session_bars()
    states = tuple(Decimal("0") for _ in range(73)) + (
        Decimal("0.5"),
        Decimal("0.5"),
        Decimal("0"),
        Decimal("0.5"),
        Decimal("0.5"),
    )
    result = _engine(3).run(bars, ScriptedStateStrategy(states))

    assert any(item.status == "canceled" for item in result.transitions)
    assert any(item.status == "rejected" for item in result.transitions)
    assert all(
        item.reason == "session-close-override"
        for item in result.transitions
        if item.status == "canceled"
    )
    assert all(
        item.reason == "session-close-cutoff"
        for item in result.transitions
        if item.status == "rejected"
    )
    assert result.trades == ()


def test_future_bar_changes_do_not_change_prior_desired_state() -> None:
    bars = _normal_session_bars()
    changed = list(bars)
    future_timestamp = sorted({bar.timestamp for bar in bars})[30]
    for index, bar in enumerate(changed):
        if bar.symbol == Symbol("SPY") and bar.timestamp == future_timestamp:
            changed[index] = replace(
                bar,
                open=Decimal("900"),
                high=Decimal("902"),
                low=Decimal("899"),
                close=Decimal("901"),
            )
    original = _engine(2).run(bars, ThirtyMinuteMomentumStrategy(_SYMBOLS))
    modified = _engine(2).run(tuple(changed), ThirtyMinuteMomentumStrategy(_SYMBOLS))

    original_prior = tuple(
        decision for decision in original.decisions if decision.timestamp <= future_timestamp
    )
    modified_prior = tuple(
        decision for decision in modified.decisions if decision.timestamp <= future_timestamp
    )
    assert original_prior == modified_prior
    assert all(trade.decision_timestamp <= trade.fill_timestamp for trade in modified.trades)


def _synthetic_history(
    length: int, *, breakout: bool = False
) -> dict[Symbol, tuple[OHLCVBar, ...]]:
    start = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    result: dict[Symbol, tuple[OHLCVBar, ...]] = {}
    for symbol in _SYMBOLS:
        bars: list[OHLCVBar] = []
        for index in range(length):
            close = Decimal("110") if breakout and index == 6 else Decimal(100 + index)
            high = max(close, Decimal("101")) + Decimal("1")
            low = min(close, Decimal("100")) - Decimal("1")
            bars.append(
                OHLCVBar(
                    symbol,
                    start + Timeframe.FIVE_MINUTES.duration * index,
                    Decimal("100"),
                    high,
                    low,
                    close,
                    1000,
                )
            )
        result[symbol] = tuple(bars)
    return result


def _latest_slice(
    history: Mapping[Symbol, Sequence[OHLCVBar]],
) -> tuple[OHLCVBar, ...]:
    return tuple(history[symbol][-1] for symbol in _SYMBOLS)


def test_fixed_strategy_contracts_and_opening_range_causality() -> None:
    history = _synthetic_history(12)
    v2 = IntradayMovingAverageTrendPortfolioStrategy(_SYMBOLS).on_session(
        _latest_slice(history), history
    )
    v3 = EventDrivenMovingAverageTrendStrategy(_SYMBOLS).on_session(_latest_slice(history), history)
    assert [(target.symbol, target.weight) for target in v3] == [
        (target.symbol, target.weight) for target in v2
    ]

    momentum_history = _synthetic_history(7)
    momentum = ThirtyMinuteMomentumStrategy(_SYMBOLS).on_session(
        _latest_slice(momentum_history), momentum_history
    )
    assert {target.weight for target in momentum} == {Decimal("0.5")}

    opening = ThirtyMinuteOpeningRangeBreakoutStrategy(_SYMBOLS)
    for length in range(1, 7):
        incomplete = _synthetic_history(length, breakout=True)
        assert {
            target.weight for target in opening.on_session(_latest_slice(incomplete), incomplete)
        } == {Decimal("0")}
    complete = _synthetic_history(7, breakout=True)
    assert {target.weight for target in opening.on_session(_latest_slice(complete), complete)} == {
        Decimal("0.5")
    }


def test_v3_strategy_and_experiment_contracts_reject_parameter_drift() -> None:
    with pytest.raises(ValueError, match="parameters differ"):
        v3_strategy(V3_MOMENTUM_STRATEGY_ID, _SYMBOLS, {"lookback": True})
    with pytest.raises(ValueError, match="parameters differ"):
        v3_strategy(V3_OPENING_RANGE_STRATEGY_ID, _SYMBOLS, {"opening_range_bars": 5})
    with pytest.raises(ValueError, match="exactly SPY and QQQ"):
        v3_strategy(V3_MA_STRATEGY_ID, (Symbol("SPY"),), {"window": 12})
    with pytest.raises(BacktestError, match="binary"):
        _engine().run(
            _normal_session_bars(),
            ScriptedStateStrategy((Decimal("0.25"),)),
        )

    spec = _spec(_bars())
    with pytest.raises(ValueError, match="training and validation"):
        replace(spec, split=ExperimentSplit.HOLDOUT)
    with pytest.raises(ValueError, match="replay contract differs"):
        replace(spec, execution_model_version="deterministic-next-bar-open-v1")


def _spec(bars: Sequence[OHLCVBar]) -> IntradayV3ExperimentSpec:
    timestamps = sorted({bar.timestamp for bar in bars})
    return IntradayV3ExperimentSpec(
        experiment_id="v3-development-diagnostic",
        campaign_id="intraday-research-v3",
        search_budget=60,
        candidate_ordinal=1,
        strategy_id=V3_MOMENTUM_STRATEGY_ID,
        strategy_version="1",
        strategy_family="intraday-directional-momentum",
        code_commit="development-only-not-reviewed",
        source_foundation_commit="development-only-not-reviewed",
        campaign_plan_fingerprint="development-only-not-reviewed",
        qualification_binding_id="intraday-v3-qualification-binding-v1",
        qualification_binding_fingerprint="development-only-not-reviewed",
        period_role="training",
        variant_role="base",
        dataset_id="deterministic-intraday-fixture-v1",
        dataset_fingerprint=fingerprint(
            tuple(
                bar.to_record()
                for bar in sorted(bars, key=lambda item: (item.symbol.value, item.timestamp))
            )
        ),
        universe_id="liquid-etfs-intraday-5m-v1",
        universe_fingerprint="fixture-universe-fingerprint",
        parameters={"lookback": 6},
        timeframe="5m",
        session_policy_version=V3_SESSION_POLICY,
        bar_timestamp_semantics_version="bar-open-utc-v1",
        session_return_policy_version="XNYS-session-close-equity-v1",
        benchmark_policy_version="cash-and-continuous-underlying-v1",
        cost_model_version="conservative-bps-v1",
        slippage_bps=Decimal("5"),
        commission_bps=Decimal("1"),
        execution_model_version=V3_EXECUTION_MODEL,
        earliest_fill_semantics=V3_EARLIEST_FILL_SEMANTICS,
        decision_queue_policy_version=V3_QUEUE_POLICY,
        execution_delay_bars=2,
        periodic_rebalance_policy_version=V3_PERIODIC_REBALANCE_POLICY,
        diagnostic_policy_version=V3_DIAGNOSTIC_POLICY,
        authority_policy_version=V3_AUTHORITY_POLICY,
        split=ExperimentSplit.TRAINING,
        start_timestamp=timestamps[0],
        end_timestamp=timestamps[-1],
        random_seed=0,
        creation_reason="development-only deterministic diagnostic",
    )


def test_zero_cost_diagnostic_is_deterministic_distinct_and_non_authoritative(
    tmp_path: Path,
) -> None:
    bars = _bars()
    spec = _spec(bars)
    first = run_v3_diagnostic(spec, bars)
    second = run_v3_diagnostic(spec, bars)
    report = build_v3_diagnostic_report(spec, first, bars)
    typed_report = cast(dict[str, Any], report)

    assert first.artifact_fingerprint == second.artifact_fingerprint
    assert report == build_v3_diagnostic_report(spec, second, bars)
    assert typed_report["schema_version"] == "intraday-backtest-report-v2"
    assert (
        typed_report["realistic"]["net_return"]
        != typed_report["zero_cost_counterfactual"]["return"]
    )
    assert typed_report["realistic"]["cost_paid_total"] > 0
    assert typed_report["zero_cost_counterfactual"]["cost_paid_total"] == 0
    assert typed_report["zero_cost_counterfactual"]["semantic_trace_matches_realistic"] is True
    assert typed_report["realistic"]["metrics"]["transaction_cost_drag"] == (
        typed_report["zero_cost_counterfactual"]["return"] - typed_report["realistic"]["net_return"]
    )
    assert typed_report["realistic"]["metrics"]["periodic_rebalance_count"] == 0
    assert typed_report["realistic"]["metrics"]["overnight_position_count"] == 0
    assert typed_report["realistic"]["metrics"]["outside_session_fill_count"] == 0
    assert "metrics" not in typed_report["zero_cost_counterfactual"]
    assert "metrics" not in typed_report
    assert typed_report["evidence_integrity_fingerprint"]
    assert not any(typed_report["authority"].values())
    output = tmp_path / "v3-diagnostic.json"
    assert write_v3_diagnostic_report(output, spec, first, bars) == report
    with pytest.raises(FileExistsError):
        write_v3_diagnostic_report(output, spec, first, bars)
    policy = load_intraday_qualification_policy(
        Path("config/research/intraday-qualification-policy-v1.json")
    )
    with pytest.raises(ValueError, match="intraday-backtest-report-v1"):
        evaluate_intraday_qualification(policy, report, {}, {})


def test_v3_diagnostic_rejects_mismatched_input_and_forged_pair() -> None:
    bars = _bars()
    spec = _spec(bars)
    replay = run_v3_diagnostic(spec, bars)

    with pytest.raises(ValueError, match="experiment range"):
        run_v3_diagnostic(spec, _normal_session_bars())
    changed = list(bars)
    changed[0] = replace(changed[0], volume=changed[0].volume + 1)
    with pytest.raises(ValueError, match="dataset fingerprint"):
        run_v3_diagnostic(spec, changed)
    with pytest.raises(ValueError, match="initial cash differs"):
        run_v3_diagnostic(spec, bars, Decimal("1000"))

    mismatched_zero_cost = StateTransitionBacktestEngine(
        Decimal("100000"),
        CostModel("zero-cost-counterfactual-v1", Decimal("0"), Decimal("0")),
        1,
    ).run(bars, ThirtyMinuteMomentumStrategy(_SYMBOLS))
    forged = replace(replay, zero_cost=mismatched_zero_cost)
    with pytest.raises(ValueError, match="experiment provenance|semantic traces differ"):
        build_v3_diagnostic_report(spec, forged, bars)

    substituted_bars = list(bars)
    substituted_bars[20] = replace(substituted_bars[20], volume=substituted_bars[20].volume + 1)
    substituted_spec = replace(
        spec,
        dataset_fingerprint=fingerprint(
            tuple(
                bar.to_record()
                for bar in sorted(
                    substituted_bars, key=lambda item: (item.symbol.value, item.timestamp)
                )
            )
        ),
    )
    substituted_replay = run_v3_diagnostic(substituted_spec, substituted_bars)
    with pytest.raises(ValueError, match="artifact fingerprint differs"):
        build_v3_diagnostic_report(spec, substituted_replay, bars)

    mutable_parameters = {"lookback": 6}
    isolated_spec = replace(spec, parameters=mutable_parameters)
    mutable_parameters["lookback"] = 5
    assert isolated_spec.parameters["lookback"] == 6
    with pytest.raises(TypeError):
        cast(dict[str, object], isolated_spec.parameters)["lookback"] = 5


def test_v3_draft_is_fixed_non_sealable_and_fingerprinted() -> None:
    path = Path("config/research/intraday-campaign-v3-draft.json")
    draft = load_v3_campaign_draft(path)
    repeated = load_v3_campaign_draft(path)
    payload = cast(dict[str, Any], draft.payload)

    assert draft.candidate_count == 60
    assert draft.draft_fingerprint == repeated.draft_fingerprint
    assert payload["status"] == "draft-unpreregistered"
    assert payload["periods"][0]["selection_status"] == "unselected"
    assert payload["source_provenance"]["required_new_modules"] == (
        "systematic_trading_lab/intraday_v3.py",
    )
    assert not any(payload["authorities"].values())
    with pytest.raises(ValueError, match="fields differ"):
        parse_intraday_research_campaign_plan(json.loads(path.read_text(encoding="utf-8")))

    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["authorities"]["paper_execution"] = True
    with pytest.raises(ValueError, match="authority boundary"):
        parse_v3_campaign_draft(changed)

    source = json.loads(path.read_text(encoding="utf-8"))
    isolated = parse_v3_campaign_draft(source)
    source["authorities"]["paper_execution"] = True
    authorities = cast(Mapping[str, object], isolated.payload["authorities"])
    assert authorities["paper_execution"] is False
    with pytest.raises(TypeError):
        cast(dict[str, object], isolated.payload["authorities"])["paper_execution"] = True


def _selected_period(role: str, split: str, start: date, end: date) -> dict[str, object]:
    timestamps = expected_bar_timestamps(
        datetime.combine(start, datetime.min.time(), UTC),
        datetime.combine(end, datetime.max.time(), UTC),
        Timeframe.FIVE_MINUTES,
    )
    return {
        "role": role,
        "split": split,
        "new_york_session_start": start.isoformat(),
        "new_york_session_end": end.isoformat(),
        "start_timestamp": timestamps[0].isoformat().replace("+00:00", "Z"),
        "end_timestamp": timestamps[-1].isoformat().replace("+00:00", "Z"),
    }


def test_period_selection_rejects_known_exposure_and_never_certifies_freshness() -> None:
    draft = load_v3_campaign_draft(Path("config/research/intraday-campaign-v3-draft.json"))
    selection = [
        _selected_period("training", "training", date(2026, 5, 1), date(2026, 5, 29)),
        _selected_period("validation-a", "validation", date(2026, 7, 1), date(2026, 7, 10)),
        _selected_period("validation-b", "validation", date(2026, 7, 13), date(2026, 7, 24)),
        _selected_period("validation-c", "validation", date(2026, 7, 27), date(2026, 8, 7)),
    ]
    result = validate_v3_period_selection(draft, selection)
    repeated = validate_v3_period_selection(draft, selection)

    assert result.selection_fingerprint == repeated.selection_fingerprint
    assert result.status == "candidate-selection-requires-independent-review"
    exposed = list(selection)
    exposed[1] = _selected_period("validation-a", "validation", date(2026, 6, 1), date(2026, 6, 12))
    with pytest.raises(ValueError, match="overlaps known exposed evidence"):
        validate_v3_period_selection(draft, exposed)
