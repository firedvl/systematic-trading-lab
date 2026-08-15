from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import systematic_trading_lab.rapid_004_runner as rapid_004_runner
from systematic_trading_lab.domain import OHLCVBar, Symbol
from systematic_trading_lab.fingerprints import canonical_json, fingerprint
from systematic_trading_lab.rapid_004 import RAPID_004_PROGRAM_ID
from systematic_trading_lab.rapid_004_runner import (
    Rapid004CampaignRunner,
    Rapid004Configuration,
    Rapid004Period,
    _FullUniverseStrategicAllocation,
    _passes_gates,
    _walk_forward_metrics,
    load_rapid_004_plan,
    rapid_004_plan_summary,
    rapid_004_status,
)
from systematic_trading_lab.rapid_004_strategies import build_rapid_004_portfolio_strategy
from systematic_trading_lab.strategies import StrategicAllocationPortfolioStrategy

REPOSITORY = Path(__file__).resolve().parents[2]
CODE_IDENTITY = {"commit": "a" * 40, "dirty": False}


def _full_range_specification(runner: Rapid004CampaignRunner) -> dict[str, object]:
    configuration = runner.plan.anchor("A")
    return runner._specification(
        run_type="rapid-004-full-range-discovery",
        strategy_id=configuration.strategy_id,
        family_id=configuration.family_id,
        parameters=configuration.parameters,
        period=runner.plan.full_period,
        scenario_id="normal",
        context={
            "parent_record": True,
            "stage": "full-range-discovery",
            "family_id": configuration.family_id,
            "source_stage": configuration.source_stage,
            "configuration_id": configuration.identity,
            "period_id": "full-range",
        },
    )


def _benchmark_specification(
    runner: Rapid004CampaignRunner,
    benchmark_id: str = "cash",
    period: Rapid004Period | None = None,
) -> dict[str, object]:
    definitions = runner.plan.payload["benchmarks"]["definitions"]
    assert isinstance(definitions, list)
    definition = next(item for item in definitions if item["id"] == benchmark_id)
    selected_period = period or runner.plan.full_period
    return runner._specification(
        run_type="rapid-004-benchmark",
        strategy_id=definition["strategy_id"],
        family_id=None,
        parameters=definition.get("parameters", {}),
        period=selected_period,
        scenario_id="normal",
        strategy_version=(
            "1"
            if benchmark_id == "strategic-allocation-21-historical-reference"
            else "rapid-004-mechanics-v1"
        ),
        context={
            "parent_record": True,
            "stage": "benchmark",
            "benchmark_id": benchmark_id,
            "period_id": selected_period.period_id,
        },
    )


def _complete_benchmarks(runner: Rapid004CampaignRunner) -> None:
    for benchmark_id in runner._benchmark_ids():
        for period in runner.plan.periods:
            row = runner._begin(_benchmark_specification(runner, benchmark_id, period))
            runner._finish(row, {"total_return": "0.1"}, {})


def _ordinary_run_specification() -> dict[str, object]:
    return {
        "schema_version": "rapid-research-run-v1",
        "run_type": "backtest",
        "dataset": {"id": "d" * 64, "fingerprint": "f" * 64, "timeframe": "1d"},
        "strategy": {
            "name": "moving-average",
            "id": "moving-average",
            "version": "1",
            "parameters": {"window": 20},
        },
        "start_timestamp": "2020-07-27T00:00:00Z",
        "end_timestamp": "2020-08-31T00:00:00Z",
        "initial_cash": "100000",
        "costs": {"version": "cost-v1", "slippage_bps": "1", "commission_bps": "5"},
        "execution": {"model": "next-bar-v1", "fill_delay_bars": 1},
        "code": CODE_IDENTITY,
    }


def test_frozen_plan_materializes_every_declared_configuration_and_budget() -> None:
    plan = load_rapid_004_plan(REPOSITORY)
    summary = rapid_004_plan_summary(REPOSITORY)

    assert len(plan.configurations) == 542
    assert len({item.identity for item in plan.configurations}) == 542
    assert summary["discovery_configuration_count"] == 356
    assert summary["conditional_confirmation_configuration_count"] == 186
    assert summary["maximum_parent_records"] == 2452
    assert [item.period_id for item in plan.periods] == [
        "full-range",
        "block-1",
        "block-2",
        "block-3",
    ]
    symbols = tuple(
        sorted((Symbol(value) for value in plan.binding.symbols), key=lambda item: item.value)
    )
    for configuration in plan.configurations:
        build_rapid_004_portfolio_strategy(
            configuration.strategy_id,
            symbols,
            plan.groups,
            plan.sleeves,
            plan.profiles,
            configuration.parameters,
        )
    for (
        family_id,
        _discovery,
        _confirmation,
    ) in plan.binding.predeclaration.family_configuration_counts:
        assert plan.anchor(family_id) in plan.family_configurations(family_id)


def test_direct_neighbors_are_same_strategy_single_axis_and_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rapid_004_runner, "_code_identity", lambda _root: CODE_IDENTITY)
    runner = Rapid004CampaignRunner(REPOSITORY, tmp_path)

    for configuration in runner.plan.configurations:
        neighbors = runner._neighbors(configuration)
        assert 1 <= len(neighbors) <= 8
        for neighbor in neighbors:
            assert neighbor.family_id == configuration.family_id
            assert neighbor.strategy_id == configuration.strategy_id
            changed = tuple(
                name
                for name in configuration.parameters
                if configuration.parameters[name] != neighbor.parameters[name]
            )
            assert len(changed) == 1
            name = changed[0]
            declared = runner.plan.family(configuration.family_id)["neighbor_values"]
            assert isinstance(declared, dict)
            ordered = declared[name]
            assert isinstance(ordered, list)
            base_index = ordered.index(configuration.parameters[name])
            assert neighbor.parameters[name] in {
                ordered[index]
                for index in (base_index - 1, base_index + 1)
                if 0 <= index < len(ordered)
            }

    anchor = runner.plan.anchor("D")
    expected = {
        ("lookback", 84),
        ("lookback", 189),
        ("selection_count", 1),
        ("selection_count", 3),
        ("rebalance_every", 5),
    }
    assert {
        next(
            (name, neighbor.parameters[name])
            for name in anchor.parameters
            if anchor.parameters[name] != neighbor.parameters[name]
        )
        for neighbor in runner._neighbors(anchor)
    } == expected


def test_every_frozen_configuration_evaluates_a_warm_synthetic_session() -> None:
    plan = load_rapid_004_plan(REPOSITORY)
    symbols = tuple(
        sorted((Symbol(value) for value in plan.binding.symbols), key=lambda item: item.value)
    )
    start = datetime(2024, 1, 1, tzinfo=UTC)
    histories = {
        symbol: tuple(
            OHLCVBar(
                symbol,
                start + timedelta(days=day),
                (close := Decimal("100") + number + Decimal(day) / 10 + Decimal(day % 7) / 100),
                close + 1,
                close - 1,
                close,
                1,
            )
            for day in range(254)
        )
        for number, symbol in enumerate(symbols, start=1)
    }
    warmup_names = (
        "lookback",
        "short_lookback",
        "long_lookback",
        "window",
        "entry_window",
        "trend_window",
        "rank_lookback",
        "volatility_window",
        "reversal_lookback",
        "tactical_lookback",
        "momentum_lookback",
    )
    for configuration in plan.configurations:
        profile = plan.profiles[configuration.strategy_id]
        values = []
        for name in warmup_names:
            value = configuration.parameters.get(name, profile.get(name, 1))
            assert isinstance(value, int) and not isinstance(value, bool)
            values.append(value)
        warmup = max(values, default=1)
        count = warmup + 1
        history = {symbol: values[:count] for symbol, values in histories.items()}
        strategy = build_rapid_004_portfolio_strategy(
            configuration.strategy_id,
            symbols,
            plan.groups,
            plan.sleeves,
            plan.profiles,
            configuration.parameters,
        )
        targets = strategy.on_session(tuple(history[symbol][-1] for symbol in symbols), history)
        assert len(targets) == len(symbols)


def test_dataset_binding_fails_before_any_run_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class WrongDatasetService:
        def __init__(self, _layout: object) -> None:
            pass

        def describe(self, _dataset_id: str) -> dict[str, object]:
            return {}

    monkeypatch.setattr(rapid_004_runner, "_code_identity", lambda _root: CODE_IDENTITY)
    monkeypatch.setattr(rapid_004_runner, "DatasetService", WrongDatasetService)
    runner = Rapid004CampaignRunner(REPOSITORY, tmp_path)

    with pytest.raises(ValueError, match="dataset identity"):
        runner.run()

    assert runner.store.list_runs() == []


def test_rapid_004_ignores_unrelated_runs_and_rejects_unbound_claimants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rapid_004_runner, "_code_identity", lambda _root: CODE_IDENTITY)
    runner = Rapid004CampaignRunner(REPOSITORY, tmp_path)
    ordinary = runner.store.begin_run(_ordinary_run_specification())

    resumed = Rapid004CampaignRunner(REPOSITORY, tmp_path)
    status = rapid_004_status(REPOSITORY, tmp_path)

    assert ordinary["status"] == "pending"
    assert resumed.runs == {}
    assert status["run_row_count"] == 0

    claimant = _ordinary_run_specification()
    claimant["exploratory_context"] = {"program_id": RAPID_004_PROGRAM_ID}
    claimant["run_type"] = "claimed-backtest"
    runner.store.begin_run(claimant)
    with pytest.raises(ValueError, match="unbound research run"):
        rapid_004_status(REPOSITORY, tmp_path)


def test_rapid_004_rejects_frozen_binding_with_removed_program_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rapid_004_runner, "_code_identity", lambda _root: CODE_IDENTITY)
    runner = Rapid004CampaignRunner(REPOSITORY, tmp_path)
    specification = _full_range_specification(runner)
    context = specification["exploratory_context"]
    assert isinstance(context, dict)
    del context["program_id"]
    runner.store.begin_run(specification)

    with pytest.raises(ValueError, match="stored run context differs"):
        Rapid004CampaignRunner(REPOSITORY, tmp_path)
    with pytest.raises(ValueError, match="stored run context differs"):
        rapid_004_status(REPOSITORY, tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    (("stage", "unknown"), ("scenario_id", "stress-z"), ("period_id", "sealed")),
)
def test_resume_rejects_unknown_stage_scenario_or_period(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    monkeypatch.setattr(rapid_004_runner, "_code_identity", lambda _root: CODE_IDENTITY)
    runner = Rapid004CampaignRunner(REPOSITORY, tmp_path)
    specification = _full_range_specification(runner)
    context = specification["exploratory_context"]
    assert isinstance(context, dict)
    context[field] = value
    runner.store.begin_run(specification)

    with pytest.raises(ValueError, match="stored"):
        Rapid004CampaignRunner(REPOSITORY, tmp_path)
    with pytest.raises(ValueError, match="stored"):
        rapid_004_status(REPOSITORY, tmp_path)


def test_resume_rejects_canonical_report_that_differs_from_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rapid_004_runner, "_code_identity", lambda _root: CODE_IDENTITY)
    runner = Rapid004CampaignRunner(REPOSITORY, tmp_path)
    row = runner._begin(_benchmark_specification(runner))
    completed = runner._finish(row, {"total_return": "0.1"}, {"test": True})
    assert len(Rapid004CampaignRunner(REPOSITORY, tmp_path).runs) == 1
    assert rapid_004_status(REPOSITORY, tmp_path)["completed_row_count"] == 1
    path = Path(str(completed["report_path"]))
    report = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(report, dict)
    report["metrics"] = {"total_return": "0.2"}
    unsigned = dict(report)
    unsigned.pop("report_fingerprint")
    report["report_fingerprint"] = fingerprint(unsigned)
    path.write_text(canonical_json(report) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="report differs from its row"):
        Rapid004CampaignRunner(REPOSITORY, tmp_path)
    with pytest.raises(ValueError, match="report differs from its row"):
        rapid_004_status(REPOSITORY, tmp_path)


def test_resume_rejects_orphan_child_and_accepts_pending_walk_forward_parent_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rapid_004_runner, "_code_identity", lambda _root: CODE_IDENTITY)
    runner = Rapid004CampaignRunner(REPOSITORY, tmp_path)
    configuration = runner.plan.anchor("A")
    common = {
        "family_id": configuration.family_id,
        "source_stage": configuration.source_stage,
        "configuration_id": configuration.identity,
    }
    parent_specification = runner._specification(
        run_type="rapid-004-walk-forward",
        strategy_id=configuration.strategy_id,
        family_id=configuration.family_id,
        parameters=configuration.parameters,
        period=runner.plan.full_period,
        scenario_id="normal",
        context={
            "parent_record": True,
            "stage": "walk-forward",
            **common,
            "period_id": "full-range",
        },
    )
    parent_run_id = f"rr-{fingerprint(parent_specification)[:20]}"
    fold = {
        "ordinal": 1,
        "training_start": "2020-07-27T00:00:00+00:00",
        "training_end": "2021-07-26T00:00:00+00:00",
        "test_start": "2021-07-27T00:00:00+00:00",
        "test_end": "2022-01-25T00:00:00+00:00",
        "training_sessions": 252,
        "test_sessions": 126,
    }
    child_specification = runner._specification(
        run_type="rapid-004-walk-forward-fold",
        strategy_id=configuration.strategy_id,
        family_id=configuration.family_id,
        parameters=configuration.parameters,
        period=Rapid004Period("walk-forward-1", "2020-07-27", "2022-01-25"),
        scenario_id="normal",
        context={
            "parent_record": False,
            "stage": "walk-forward-fold",
            **common,
            "period_id": "walk-forward-1",
        },
        parent_run_id=parent_run_id,
        fold=fold,
    )
    child = runner.store.begin_run(child_specification)
    runner.store.finish_run(str(child["run_id"]), {"total_return": "0.1"}, {})

    with pytest.raises(ValueError, match="no stored parent"):
        Rapid004CampaignRunner(REPOSITORY, tmp_path)

    parent = runner.store.begin_run(parent_specification)
    runner.runs[parent_run_id] = parent
    runner._require_parent_link(child_specification)
    assert parent["run_id"] == parent_run_id


def test_confirmation_rejects_before_discovery_on_begin_and_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rapid_004_runner, "_code_identity", lambda _root: CODE_IDENTITY)
    runner = Rapid004CampaignRunner(REPOSITORY, tmp_path)
    _complete_benchmarks(runner)
    configuration = next(
        item for item in runner.plan.configurations if item.source_stage == "confirmation"
    )
    specification = runner._specification(
        run_type="rapid-004-full-range-confirmation",
        strategy_id=configuration.strategy_id,
        family_id=configuration.family_id,
        parameters=configuration.parameters,
        period=runner.plan.full_period,
        scenario_id="normal",
        context={
            "parent_record": True,
            "stage": "full-range-confirmation",
            "family_id": configuration.family_id,
            "source_stage": configuration.source_stage,
            "configuration_id": configuration.identity,
            "period_id": "full-range",
        },
    )

    with pytest.raises(ValueError, match="discovery prerequisites are incomplete"):
        runner._begin(specification)

    runner.store.begin_run(specification)
    with pytest.raises(ValueError, match="discovery prerequisites are incomplete"):
        Rapid004CampaignRunner(REPOSITORY, tmp_path)


def test_parent_budget_rejects_before_creating_a_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rapid_004_runner, "_code_identity", lambda _root: CODE_IDENTITY)
    runner = Rapid004CampaignRunner(REPOSITORY, tmp_path)
    monkeypatch.setattr(
        runner,
        "_parent_count",
        lambda: runner.plan.binding.predeclaration.maximum_parent_records,
    )

    with pytest.raises(ValueError, match="parent budget exceeded"):
        runner._begin(_benchmark_specification(runner))

    assert runner.store.list_runs() == []


def test_create_only_artifact_race_never_overwrites_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "artifact.json"
    winner = b"winner\n"

    def racing_link(_source: Path, destination: Path) -> None:
        destination.write_bytes(winner)
        raise FileExistsError

    monkeypatch.setattr(os, "link", racing_link)

    with pytest.raises(FileExistsError):
        rapid_004_runner._write_create_only_json(path, {"candidate": "loser"})

    assert path.read_bytes() == winner


def test_frozen_stage_passes_do_not_interleave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rapid_004_runner, "_code_identity", lambda _root: CODE_IDENTITY)
    runner = Rapid004CampaignRunner(REPOSITORY, tmp_path)
    calls: list[str] = []
    passing_metrics = {
        "total_return": "0.1",
        "sharpe_ratio": "1",
        "max_drawdown": "0.1",
        "average_gross_exposure": "1",
        "top_instrument_profit_share": "0.5",
        "turnover": "1",
        "trade_count": 100,
    }

    def run_configuration(
        _configuration: Rapid004Configuration,
        _period: object,
        *,
        stage: str,
        **_kwargs: object,
    ) -> dict[str, object]:
        calls.append(stage)
        return {"metrics": passing_metrics}

    monkeypatch.setattr(runner, "_run_configuration", run_configuration)
    runner._run_full_range_search()
    assert calls[:356] == ["full-range-discovery"] * 356
    assert calls[356:] == ["full-range-confirmation"] * 186

    calls.clear()
    monkeypatch.setattr(runner, "_fixed_block_metrics", lambda _configuration: {})
    monkeypatch.setattr(runner, "_visible_base_passes", lambda _metrics: True)
    monkeypatch.setattr(rapid_004_runner, "_serious_selection_key", lambda _item: ())
    monkeypatch.setattr(
        runner,
        "_run_walk_forward",
        lambda configuration: calls.append(f"walk:{configuration.family_id}"),
    )
    monkeypatch.setattr(
        runner,
        "_run_neighbors",
        lambda configuration: calls.append(f"neighbors:{configuration.family_id}"),
    )
    monkeypatch.setattr(
        runner,
        "_run_isolated_sensitivities",
        lambda configuration: calls.append(f"isolated:{configuration.family_id}"),
    )
    monkeypatch.setattr(
        runner,
        "_run_combined_stress",
        lambda configuration: calls.append(f"stress:{configuration.family_id}"),
    )
    runner._select_and_evaluate_serious(
        {"A": (runner.plan.anchor("A"),), "B": (runner.plan.anchor("B"),)}
    )
    assert calls == [
        "walk:A",
        "neighbors:A",
        "walk:B",
        "neighbors:B",
        "isolated:A",
        "isolated:B",
        "stress:A",
        "stress:B",
    ]


def test_cohort_uses_declared_diversity_group_and_freezes_exact_plans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rapid_004_runner, "_code_identity", lambda _root: CODE_IDENTITY)
    runner = Rapid004CampaignRunner(REPOSITORY, tmp_path)
    metric = {
        "worst_fixed_block_excess_return": "1",
        "worst_validation_sharpe": "1",
        "max_validation_drawdown": "0.1",
        "max_turnover": "1",
    }
    screened = [
        {
            "passed": True,
            "family_id": family,
            "cohort_diversity_group": group,
            "configuration_fingerprint": identity,
            "fixed_block_metrics": metric,
        }
        for family, group, identity in (
            ("A", "shared", "1"),
            ("B", "shared", "2"),
            ("C", "other", "3"),
        )
    ]
    monkeypatch.setattr(
        runner,
        "_controlled_plan",
        lambda item: {"configuration_fingerprint": item["configuration_fingerprint"]},
    )

    cohort = runner._freeze_cohort(screened)

    assert [item["configuration_fingerprint"] for item in cohort] == ["1", "3", "2"]
    payload = json.loads(
        (tmp_path / rapid_004_runner.COHORT_FREEZE_NAME).read_text(encoding="utf-8")
    )
    assert [item["configuration_fingerprint"] for item in payload["controlled_plans"]] == [
        "1",
        "3",
        "2",
    ]


def test_controlled_plan_freezes_every_incident_neighbor_and_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rapid_004_runner, "_code_identity", lambda _root: CODE_IDENTITY)
    runner = Rapid004CampaignRunner(REPOSITORY, tmp_path)
    configuration = runner.plan.anchor("D")

    plan = runner._controlled_plan({"configuration_fingerprint": configuration.identity})
    candidate = plan["candidate"]
    assert isinstance(candidate, dict)
    neighbors = runner._neighbors(configuration)
    assert {item["configuration_fingerprint"] for item in candidate["neighbors"]} == {
        item.identity for item in neighbors
    }
    assert plan["record_count"] == 14 + 3 * len(neighbors)
    unsigned = dict(plan)
    plan_fingerprint = unsigned.pop("controlled_plan_fingerprint")
    assert plan_fingerprint == fingerprint(unsigned)


def test_historical_benchmark_wraps_the_unchanged_strategy() -> None:
    plan = load_rapid_004_plan(REPOSITORY)
    symbols = tuple(
        sorted((Symbol(value) for value in plan.binding.symbols), key=lambda item: item.value)
    )
    timestamp = datetime(2024, 1, 2, tzinfo=UTC)
    history = {
        symbol: (
            OHLCVBar(
                symbol,
                timestamp,
                Decimal("100"),
                Decimal("101"),
                Decimal("99"),
                Decimal("100"),
                1,
            ),
        )
        for symbol in symbols
    }
    historical_symbols = tuple(
        symbol for symbol in symbols if symbol.value in {"GLD", "IWM", "QQQ", "SPY", "TLT"}
    )
    inner = StrategicAllocationPortfolioStrategy(historical_symbols, rebalance_every=21)
    expected = {
        target.symbol: target.weight
        for target in inner.on_session(
            tuple(history[symbol][-1] for symbol in historical_symbols),
            {symbol: history[symbol] for symbol in historical_symbols},
        )
    }
    adapter = _FullUniverseStrategicAllocation(symbols, 21)

    targets = adapter.on_session(tuple(history[symbol][-1] for symbol in symbols), history)

    assert len(targets) == len(symbols)
    assert {target.symbol: target.weight for target in targets if target.weight} == {
        symbol: weight for symbol, weight in expected.items() if weight
    }


def test_gate_evaluation_fails_closed_for_missing_and_null_metrics() -> None:
    gates = [
        {"metric": "return", "comparison": ">", "threshold": "0"},
        {"metric": "drawdown", "comparison": "<=", "threshold": "0.2"},
    ]

    assert _passes_gates({"return": "0.1", "drawdown": "0.2"}, gates)
    assert not _passes_gates({"return": "0.1", "drawdown": None}, gates)
    assert not _passes_gates({"return": "0.1"}, gates)


def test_walk_forward_metrics_report_frozen_fields() -> None:
    rows = [
        {
            "status": "completed",
            "metrics": {"total_return": value, "trade_count": 2, "cost_paid": "1"},
        }
        for value in ("0.10", "-0.05", "0.02")
    ]

    metrics = _walk_forward_metrics(rows)

    assert metrics["fold_count"] == 3
    assert metrics["completed_fold_count"] == 3
    assert metrics["profitable_fold_count"] == 2
    assert metrics["profitable_fold_rate"] == Decimal(2) / Decimal(3)
    assert metrics["fold_returns"] == (Decimal("0.10"), Decimal("-0.05"), Decimal("0.02"))
    assert metrics["worst_fold_return"] == Decimal("-0.05")
