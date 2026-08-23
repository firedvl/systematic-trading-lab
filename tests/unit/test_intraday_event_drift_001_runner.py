from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

import systematic_trading_lab.intraday_event_drift_001_runner as runner_module
from systematic_trading_lab.calendar import expected_bar_timestamps
from systematic_trading_lab.domain import OHLCVBar, Symbol, Timeframe
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.intraday_event_drift_001_launch_control import (
    REVIEWED_LAUNCH_CONTROL_FINGERPRINT,
    REVIEWED_LAUNCH_CONTROL_SHA256,
)
from systematic_trading_lab.intraday_event_drift_001_plan import (
    CALENDAR_FINGERPRINT,
    CALENDAR_RELATIVE_PATH,
    CALENDAR_SHA256,
    PLAN_FINGERPRINT,
    PLAN_RELATIVE_PATH,
    PLAN_SHA256,
    PROGRAM_ID,
    REVIEW_FINGERPRINT,
    REVIEW_RELATIVE_PATH,
    REVIEW_SHA256,
    SOURCE_EVIDENCE_FINGERPRINT,
    SOURCE_EVIDENCE_RELATIVE_PATH,
    SOURCE_EVIDENCE_SHA256,
    EventDriftEvent,
    EventDriftPeriod,
    load_intraday_event_drift_001_plan,
)
from systematic_trading_lab.intraday_event_drift_001_runner import (
    IntradayEventDrift001Runner,
    IntradayEventDrift001Store,
    _aggregate_reports,
    _dataset_bindings,
    _parallel_equivalence,
    _positive_fold,
    _run_id,
    _run_report,
    intraday_event_drift_001_plan_summary,
    intraday_event_drift_001_status,
)
from systematic_trading_lab.intraday_event_drift_001_strategies import (
    ScheduledBroadIndexPositiveDriftStrategy,
)
from systematic_trading_lab.intraday_execution_cost_model import (
    ExecutionCostScenario,
    RegulatoryFeeModel,
    load_intraday_execution_cost_model,
)
from systematic_trading_lab.intraday_exposed_002_engine import IntradayExposed002Engine
from systematic_trading_lab.intraday_exposed_002_runner import _gate_results, _scenarios
from systematic_trading_lab.public_cli import research_parser
from systematic_trading_lab.research_attempts import AttemptStateError

_REPOSITORY = Path(__file__).resolve().parents[2]
_QQQ, _SPY = Symbol("QQQ"), Symbol("SPY")


def _runner(*, workers: int) -> IntradayEventDrift001Runner:
    runner = IntradayEventDrift001Runner.__new__(IntradayEventDrift001Runner)
    runner.repository = _REPOSITORY
    runner.source_commit = "a" * 40
    runner.workers = workers
    runner.plan = load_intraday_event_drift_001_plan(_REPOSITORY)
    runner.cost_model = load_intraday_execution_cost_model(_REPOSITORY)
    runner.datasets = _dataset_bindings(runner.plan.payload)
    runner.scenarios = _scenarios(runner.cost_model)
    return runner


def _launch_repository(root: Path) -> Path:
    for relative in runner_module._LAUNCH_CONTROL_FILES:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((_REPOSITORY / relative).read_bytes())
    return root


def _launch_review(repository: Path, *, findings: list[object] | None = None) -> dict[str, object]:
    source = "a" * 40
    digest = "b" * 64
    return {
        "schema_version": runner_module._LAUNCH_CONTROL_SCHEMA,
        "review_id": runner_module._LAUNCH_CONTROL_SCHEMA,
        "status": "passed",
        "verdict": "pass",
        "review_date": "2026-08-23",
        "review_method": "Independent exact implementation and equivalence review.",
        "reviewed_inputs": {
            "plan": {
                "path": PLAN_RELATIVE_PATH.as_posix(),
                "sha256": PLAN_SHA256,
                "fingerprint": PLAN_FINGERPRINT,
            },
            "calendar": {
                "path": CALENDAR_RELATIVE_PATH.as_posix(),
                "sha256": CALENDAR_SHA256,
                "fingerprint": CALENDAR_FINGERPRINT,
            },
            "source_evidence": {
                "path": SOURCE_EVIDENCE_RELATIVE_PATH.as_posix(),
                "sha256": SOURCE_EVIDENCE_SHA256,
                "fingerprint": SOURCE_EVIDENCE_FINGERPRINT,
            },
            "plan_review": {
                "path": REVIEW_RELATIVE_PATH.as_posix(),
                "sha256": REVIEW_SHA256,
                "fingerprint": REVIEW_FINGERPRINT,
            },
        },
        "implementation": {
            "source_commit": source,
            "files": [
                {
                    "path": relative,
                    "sha256": hashlib.sha256((repository / relative).read_bytes()).hexdigest(),
                }
                for relative in runner_module._LAUNCH_CONTROL_FILES
            ],
        },
        "quality_gates": {
            "source_commit": source,
            "results": [
                {"command": command, "status": "passed", "exit_code": 0, "summary": "passed"}
                for command in runner_module._LAUNCH_CONTROL_QUALITY_GATES
            ],
        },
        "equivalence": {
            "schema_version": "intraday-event-drift-001-parallel-equivalence-v1",
            "program_id": PROGRAM_ID,
            "verification_source_commit": source,
            "fixture_kind": "synthetic-non-protected-five-minute-bars",
            "protected_inputs_accessed": False,
            "worker_counts": [1, 4],
            "comparisons": list(runner_module._LAUNCH_CONTROL_EQUIVALENCE_COMPARISONS),
            "fixture_count": 3,
            "sequential_seconds": "4.0",
            "parallel_seconds": "1.5",
            "speedup": "2.666667",
            "fixtures": [
                {
                    "run_id": f"ied001r-{index}",
                    "candidate_id": "ied001-a01-b01" if index != 1 else "ied001-a02-b02",
                    "scenario_id": "normal" if index != 2 else "zero_cost_diagnostic",
                    "run_fingerprint": digest,
                    "decision_trace_fingerprint": digest,
                    "fill_trace_fingerprint": digest,
                    "round_trip_fingerprint": digest,
                    "report_sha256": digest,
                    "report_fingerprint": digest,
                    "specification_equal": True,
                    "metrics_equal": True,
                    "event_ledger_equal": True,
                    "canonical_report_equal": True,
                }
                for index in range(3)
            ],
            "equivalent": True,
        },
        "independent_review": {
            "source_commit": source,
            "status": "passed",
            "verdict": "pass",
            "findings": [] if findings is None else findings,
            "reviewer": "independent-control-review",
        },
        "scope_limit": "Synthetic fixtures only; protected and broker state excluded.",
        "authority": dict(runner_module._AUTHORITY),
    }


def _write_launch_review(
    repository: Path,
    value: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsigned = deepcopy(value)
    unsigned.pop("review_fingerprint", None)
    value["review_fingerprint"] = fingerprint(unsigned)
    raw = (json.dumps(value, indent=2) + "\n").encode()
    path = repository / runner_module.LAUNCH_CONTROL_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    monkeypatch.setattr(
        runner_module, "REVIEWED_LAUNCH_CONTROL_SHA256", hashlib.sha256(raw).hexdigest()
    )
    monkeypatch.setattr(
        runner_module,
        "REVIEWED_LAUNCH_CONTROL_FINGERPRINT",
        value["review_fingerprint"],
    )


def test_plan_status_and_cli_are_read_only_after_launch_control_is_bound(
    tmp_path: Path,
) -> None:
    plan = intraday_event_drift_001_plan_summary(_REPOSITORY)
    status = intraday_event_drift_001_status(tmp_path)
    arguments = research_parser().parse_args(("intraday-event-drift-001", "run", "--workers", "6"))

    assert plan["parent_configuration_count"] == 9
    assert plan["discovery_run_count"] == 18
    assert plan["eligible_event_count"] == 28
    assert plan["default_workers"] == 4
    assert plan["status"] == "launch-control-bound"
    assert plan["launch_control_bound"] is True
    assert status["database_exists"] is False
    assert arguments.workers == 6
    assert not any(cast(Mapping[str, bool], status["authority"]).values())
    assert not (tmp_path / PROGRAM_ID).exists()
    assert REVIEWED_LAUNCH_CONTROL_SHA256 == (
        "d436c4eb29aa2148faa98c5b0143dfaf5df0296d9be23671d98d2cee4b3e4f80"
    )
    assert (
        REVIEWED_LAUNCH_CONTROL_FINGERPRINT
        == "fe807901b40109c192a93c73e9affa694ef861fb48f5aca8ac2b0570997ae845"
    )
    loaded = runner_module._load_launch_control(
        _REPOSITORY,
        source_commit="735b990c6c857d06f8db900f367f10a0c10e5dbf",
    )
    assert loaded["review_fingerprint"] == REVIEWED_LAUNCH_CONTROL_FINGERPRINT


def test_launch_control_requires_exact_finding_free_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _launch_repository(tmp_path / "repository")
    review = _launch_review(repository)
    _write_launch_review(repository, review, monkeypatch)

    loaded = runner_module._load_launch_control(repository, source_commit="a" * 40)

    assert loaded["verdict"] == "pass"
    assert cast(Mapping[str, object], loaded["equivalence"])["equivalent"] is True

    finding_review = _launch_review(repository, findings=[{"severity": "P1"}])
    _write_launch_review(repository, finding_review, monkeypatch)
    with pytest.raises(ValueError, match="independent review differs"):
        runner_module._load_launch_control(repository, source_commit="a" * 40)


def test_run_specification_has_exact_dataset_inputs_and_excludes_worker_count() -> None:
    one = _runner(workers=1)
    four = _runner(workers=4)
    period = one.plan.periods[2]
    specification = one._specification("walk-forward", one.plan.configurations[0], period, "normal")
    parallel = four._specification("walk-forward", four.plan.configurations[0], period, "normal")
    inputs = cast(list[Mapping[str, object]], specification["dataset_inputs"])

    assert specification == parallel
    assert _run_id(specification) == _run_id(parallel)
    assert len(inputs) == 2
    assert all(
        set(item)
        == {
            "dataset_id",
            "fingerprint",
            "raw_fingerprint",
            "read_start",
            "read_end",
            "evaluation_read_start",
            "evaluation_read_end",
        }
        for item in inputs
    )
    assert inputs[0]["evaluation_read_start"] is None
    assert inputs[0]["evaluation_read_end"] is None
    assert inputs[1]["evaluation_read_start"] == "2026-01-02T14:30:00Z"
    assert inputs[1]["evaluation_read_end"] == "2026-02-27T20:55:00Z"


def test_discovery_barrier_screens_all_pairs_then_applies_frozen_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner(workers=4)
    executed = False

    def execute(specifications: tuple[Mapping[str, object], ...]) -> None:
        nonlocal executed
        assert len(specifications) == 18
        assert all(
            cast(Mapping[str, object], specification["context"])["stage"] == "discovery"
            for specification in specifications
        )
        executed = True

    def paired(
        stage: str,
        candidate_id: str,
        period_id: str,
        *,
        base_candidate_id: str | None = None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        del period_id, base_candidate_id
        assert stage == "discovery"
        assert executed
        rank = next(
            index
            for index, configuration in enumerate(runner.plan.configurations, 1)
            if configuration.candidate_id == candidate_id
        )
        metrics = {
            "total_return": Decimal(rank) / Decimal("100"),
            "active_event_count": 4,
            "completed_round_trips": 8,
            "max_drawdown": Decimal("0"),
            "cost_to_gross_profit": Decimal("0.10"),
            "average_gross_trade_edge_bps": Decimal("10"),
            "positive_profit_symbol_concentration": Decimal("0.50"),
            "positive_profit_event_concentration": Decimal("0.40"),
            "positive_profit_release_class_concentration": Decimal("0.50"),
            "accounting_identity_error": Decimal("0"),
        }
        normal: dict[str, object] = {
            "run_id": f"normal-{candidate_id}",
            "metrics": metrics,
        }
        zero: dict[str, object] = {
            "run_id": f"zero-{candidate_id}",
            "metrics": {**metrics, "total_return": Decimal(rank) / Decimal("90")},
        }
        return normal, zero

    monkeypatch.setattr(runner, "_execute", execute)
    monkeypatch.setattr(runner, "_paired_reports", paired)

    screen = runner._run_discovery()

    assert screen["paired_run_count"] == 18
    assert screen["eligible_count"] == 9
    assert screen["selected_candidate_ids"] == (
        "ied001-a03-b03",
        "ied001-a03-b02",
        "ied001-a03-b01",
        "ied001-a02-b03",
    )


def test_walk_forward_barrier_uses_event_folds_and_frozen_serious_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner(workers=4)
    selected = tuple(configuration.candidate_id for configuration in runner.plan.configurations[:4])
    discovery = {"selected_candidate_ids": selected}
    executed = False

    def execute(specifications: tuple[Mapping[str, object], ...]) -> None:
        nonlocal executed
        assert len(specifications) == 32
        executed = True

    def report(candidate_id: str, period_id: str, scenario: str) -> dict[str, object]:
        candidate_rank = selected.index(candidate_id) + 1
        period_rank = next(
            index
            for index, period in enumerate(runner.plan.periods[1:], 1)
            if period.period_id == period_id
        )
        profit = Decimal(candidate_rank * 100 + period_rank)
        gross = profit + Decimal("1")
        releases = (
            "Consumer Price Index",
            "Employment Situation",
            "Producer Price Index",
        )
        ledger = [
            {
                "event_id": f"{candidate_id}-{period_id}-{index}",
                "release_name": release,
                "scheduled_utc": f"2026-0{period_rank}-0{index}T13:30:00Z",
                "xnys_session": f"2026-0{period_rank}-0{index}",
                "active": True,
                "entry_decision_timestamp": None,
                "entry_fill_timestamp": None,
                "exit_decision_timestamp": None,
                "exit_fill_timestamp": None,
                "gross_profit_loss": gross / 3,
                "adverse_slippage": Decimal("1") / 3,
                "regulatory_fees": Decimal("0"),
                "net_profit_loss": profit / 3,
            }
            for index, release in enumerate(releases, 1)
        ]
        return {
            "run_id": f"{scenario}-{candidate_id}-{period_id}",
            "metrics": {
                "completed_round_trips": 6,
                "session_count": 20,
                "gross_profit_loss": gross,
                "gross_profitable_trade_profit": gross,
                "execution_friction": Decimal("1"),
                "net_profit_loss": profit,
                "gross_trade_edge_bps_sum": Decimal("60"),
                "holding_bars_sum": Decimal("360"),
                "total_return": profit / Decimal("100000"),
                "max_drawdown": Decimal("0"),
                "active_event_count": 3,
            },
            "details": {
                "symbol_net_profit_loss": {"QQQ": profit / 2, "SPY": profit / 2},
                "event_ledger": ledger,
            },
        }

    def paired(
        stage: str,
        candidate_id: str,
        period_id: str,
        *,
        base_candidate_id: str | None = None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        del base_candidate_id
        assert stage == "walk-forward"
        assert executed
        return report(candidate_id, period_id, "normal"), report(candidate_id, period_id, "zero")

    monkeypatch.setattr(runner, "_execute", execute)
    monkeypatch.setattr(runner, "_paired_reports", paired)

    screen = runner._run_walk_forward(discovery)

    assert screen["paired_run_count"] == 32
    assert screen["eligible_count"] == 4
    assert screen["selected_candidate_ids"] == (selected[3], selected[2])


def test_serious_barrier_runs_all_stress_and_neighbors_before_simultaneous_freeze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner(workers=4)
    center = "ied001-a02-b02"
    corner = "ied001-a01-b01"
    selected = (center, corner)
    walk_forward = {
        "selected_candidate_ids": selected,
        "ledger": [
            {
                "candidate": {"candidate_id": candidate_id},
                "normal_aggregate": {"net_profit_loss": Decimal("400")},
            }
            for candidate_id in selected
        ],
    }
    executed = False

    def execute(specifications: tuple[Mapping[str, object], ...]) -> None:
        nonlocal executed
        assert len(specifications) == 80
        assert (
            sum(
                cast(Mapping[str, object], specification["context"])["stage"] == "stress"
                for specification in specifications
            )
            == 32
        )
        executed = True

    def report(
        candidate_id: str,
        period_id: str,
        scenario_id: str,
        profit: Decimal,
        *,
        base_candidate_id: str | None = None,
    ) -> dict[str, object]:
        event_id = f"{base_candidate_id}-{candidate_id}-{period_id}-{scenario_id}"
        return {
            "run_id": event_id,
            "metrics": {
                "completed_round_trips": 2,
                "session_count": 1,
                "gross_profit_loss": profit,
                "gross_profitable_trade_profit": max(profit, Decimal("0")),
                "execution_friction": Decimal("0"),
                "net_profit_loss": profit,
                "gross_trade_edge_bps_sum": Decimal("10"),
                "holding_bars_sum": Decimal("20"),
                "total_return": profit / Decimal("100000"),
                "max_drawdown": Decimal("0"),
            },
            "details": {
                "symbol_net_profit_loss": {"QQQ": profit / 2, "SPY": profit / 2},
                "event_ledger": [
                    {
                        "event_id": event_id,
                        "release_name": "Consumer Price Index",
                        "scheduled_utc": "2026-01-08T13:30:00Z",
                        "xnys_session": "2026-01-08",
                        "active": True,
                        "entry_decision_timestamp": None,
                        "entry_fill_timestamp": None,
                        "exit_decision_timestamp": None,
                        "exit_fill_timestamp": None,
                        "gross_profit_loss": profit,
                        "adverse_slippage": Decimal("0"),
                        "regulatory_fees": Decimal("0"),
                        "net_profit_loss": profit,
                    }
                ],
            },
        }

    def report_for(
        stage: str,
        candidate_id: str,
        period_id: str,
        scenario_id: str,
        *,
        base_candidate_id: str | None = None,
    ) -> dict[str, object]:
        assert stage == "stress"
        assert base_candidate_id is None
        assert executed
        return report(candidate_id, period_id, scenario_id, Decimal("100"))

    def paired(
        stage: str,
        candidate_id: str,
        period_id: str,
        *,
        base_candidate_id: str | None = None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        assert stage == "neighbor"
        assert base_candidate_id is not None
        assert executed
        neighbors = runner._configuration(base_candidate_id).neighbor_ids
        index = neighbors.index(candidate_id)
        positive_count = 3 if base_candidate_id == center else 1
        profit = Decimal("300") if index < positive_count else Decimal("-10")
        return (
            report(candidate_id, period_id, "normal", profit, base_candidate_id=base_candidate_id),
            report(candidate_id, period_id, "zero", profit, base_candidate_id=base_candidate_id),
        )

    monkeypatch.setattr(runner, "_execute", execute)
    monkeypatch.setattr(runner, "_report_for", report_for)
    monkeypatch.setattr(runner, "_paired_reports", paired)

    serious = runner._run_serious(walk_forward)
    cohort = runner._select_cohort(serious)

    assert serious["stress_run_count"] == 32
    assert serious["neighbor_run_count"] == 48
    assert serious["eligible_count"] == 1
    assert cohort == (center,)


def _synthetic_bars() -> tuple[OHLCVBar, ...]:
    start = datetime(2026, 1, 7, 14, 30, tzinfo=UTC)
    end = datetime(2026, 1, 9, 20, 55, tzinfo=UTC)
    session_index: dict[date, int] = {}
    bars: list[OHLCVBar] = []
    for timestamp in expected_bar_timestamps(start, end, Timeframe.FIVE_MINUTES):
        day = timestamp.date()
        index = session_index.get(day, 0)
        session_index[day] = index + 1
        if day == date(2026, 1, 7):
            opening = closing = Decimal("100")
        elif day == date(2026, 1, 8):
            opening = Decimal("100.2") if index == 0 else Decimal("100.5")
            closing = (
                Decimal("100.3") + Decimal(index) / Decimal("10") if index < 3 else Decimal("101")
            )
        else:
            opening = closing = Decimal("100.9")
        for symbol in (_QQQ, _SPY):
            bars.append(
                OHLCVBar(
                    symbol,
                    timestamp,
                    opening,
                    max(opening, closing),
                    min(opening, closing),
                    closing,
                    1_000,
                )
            )
    return tuple(bars)


def _fees() -> RegulatoryFeeModel:
    return RegulatoryFeeModel(
        "alpaca-us-equity-regulatory-fees-2026-07-20-v1",
        "America/New_York",
        Decimal("0.0000206"),
        Decimal("0.000195"),
        Decimal("9.79"),
        Decimal("0.000003"),
    )


def test_report_attributes_active_and_inactive_events_and_reconciles_accounting() -> None:
    period = EventDriftPeriod(
        "test-period",
        datetime(2026, 1, 7, 14, 30, tzinfo=UTC),
        datetime(2026, 1, 8, 14, 30, tzinfo=UTC),
        datetime(2026, 1, 9, 20, 55, tzinfo=UTC),
        2,
        2,
    )
    events = (
        EventDriftEvent(
            "event-active",
            "Consumer Price Index",
            "2026-01-08T13:30:00Z",
            "2026-01-08",
            "2026-01-08T14:30:00Z",
            "2026-01-08T21:00:00Z",
            "eligible",
        ),
        EventDriftEvent(
            "event-inactive",
            "Producer Price Index",
            "2026-01-09T13:30:00Z",
            "2026-01-09",
            "2026-01-09T14:30:00Z",
            "2026-01-09T21:00:00Z",
            "eligible",
        ),
    )
    strategy = ScheduledBroadIndexPositiveDriftStrategy(
        "ied001-a01-b01",
        3,
        Decimal("10"),
        frozenset({date(2026, 1, 8), date(2026, 1, 9)}),
        period.evaluation_start,
    )
    fees = _fees()
    scenario = ExecutionCostScenario(
        "normal",
        None,
        {_QQQ: Decimal("1"), _SPY: Decimal("1")},
        1,
        fees.model_id,
    )
    result = IntradayExposed002Engine(Decimal("100000"), scenario, fees).run(
        _synthetic_bars(), strategy
    )
    specification = {
        "schema_version": "test-run-v1",
        "context": {"candidate_id": strategy.candidate_id, "period_id": period.period_id},
    }

    report = _run_report(specification, result, period, events, _synthetic_bars())
    metrics = cast(Mapping[str, object], report["metrics"])
    details = cast(Mapping[str, object], report["details"])
    ledger = cast(list[Mapping[str, object]], details["event_ledger"])

    assert metrics["eligible_event_count"] == 2
    assert metrics["active_event_count"] == 1
    assert metrics["event_activation_fraction"] == Decimal("0.5")
    assert [row["event_id"] for row in ledger] == ["event-active", "event-inactive"]
    assert ledger[0]["entry_decision_timestamp"] == datetime(2026, 1, 8, 14, 45, tzinfo=UTC)
    assert ledger[0]["entry_fill_timestamp"] == datetime(2026, 1, 8, 14, 45, tzinfo=UTC)
    assert ledger[0]["exit_decision_timestamp"] == datetime(2026, 1, 8, 19, 35, tzinfo=UTC)
    assert ledger[0]["exit_fill_timestamp"] == datetime(2026, 1, 8, 19, 35, tzinfo=UTC)
    assert ledger[1]["active"] is False
    assert ledger[1]["entry_fill_timestamp"] is None
    assert ledger[1]["net_profit_loss"] == 0
    assert sum((cast(Decimal, row["net_profit_loss"]) for row in ledger), Decimal("0")) == cast(
        Decimal, metrics["event_net_profit_loss"]
    )
    assert metrics["event_net_profit_loss"] == metrics["net_profit_loss"]
    benchmarks = cast(Mapping[str, Decimal], metrics["benchmark_references"])
    continuous_return = Decimal("100.9") / Decimal("100.2") - Decimal("1")
    assert benchmarks == {
        "cash": Decimal("0"),
        "spy_continuous": continuous_return,
        "qqq_continuous": continuous_return,
        "fixed_50_50_continuous": continuous_return,
    }


def _aggregate_fixture(
    event_id: str,
    release_name: str,
    net: str,
    *,
    active: bool,
) -> dict[str, object]:
    profit = Decimal(net)
    completed = 2 if active else 0
    return {
        "metrics": {
            "completed_round_trips": completed,
            "session_count": 1,
            "gross_profit_loss": profit,
            "gross_profitable_trade_profit": max(profit, Decimal("0")),
            "execution_friction": Decimal("0"),
            "net_profit_loss": profit,
            "gross_trade_edge_bps_sum": Decimal("10") if active else Decimal("0"),
            "holding_bars_sum": Decimal("20") if active else Decimal("0"),
            "total_return": profit / Decimal("100000"),
            "max_drawdown": Decimal("0"),
        },
        "details": {
            "symbol_net_profit_loss": {"QQQ": profit / 2, "SPY": profit / 2},
            "event_ledger": [
                {
                    "event_id": event_id,
                    "release_name": release_name,
                    "scheduled_utc": f"2026-01-0{1 if event_id == 'one' else 2}T13:30:00Z",
                    "xnys_session": f"2026-01-0{1 if event_id == 'one' else 2}",
                    "active": active,
                    "entry_decision_timestamp": None,
                    "entry_fill_timestamp": None,
                    "exit_decision_timestamp": None,
                    "exit_fill_timestamp": None,
                    "gross_profit_loss": profit,
                    "adverse_slippage": Decimal("0"),
                    "regulatory_fees": Decimal("0"),
                    "net_profit_loss": profit,
                }
            ],
        },
    }


def test_aggregate_recomputes_event_and_release_concentration() -> None:
    aggregate = _aggregate_reports(
        (
            _aggregate_fixture("one", "Consumer Price Index", "10", active=True),
            _aggregate_fixture("two", "Producer Price Index", "5", active=True),
        )
    )

    assert aggregate["eligible_event_count"] == 2
    assert aggregate["active_event_count"] == 2
    assert aggregate["event_net_profit_loss"] == Decimal("15")
    assert aggregate["positive_profit_event_concentration"] == Decimal("10") / Decimal("15")
    assert aggregate["positive_profit_release_class_concentration"] == Decimal("10") / Decimal("15")
    assert [
        row["event_id"] for row in cast(list[Mapping[str, object]], aggregate["event_ledger"])
    ] == [
        "one",
        "two",
    ]


def test_positive_fold_and_neighbor_fraction_use_exact_frozen_definitions() -> None:
    assert _positive_fold(
        {"metrics": {"net_profit_loss": Decimal("1"), "total_return": Decimal("0.01")}}
    )
    assert not _positive_fold(
        {"metrics": {"net_profit_loss": Decimal("1"), "total_return": Decimal("0")}}
    )
    assert not _positive_fold(
        {"metrics": {"net_profit_loss": Decimal("0"), "total_return": Decimal("0.01")}}
    )
    result = _gate_results(
        (
            {
                "metric": "positive_neighbor_fraction",
                "comparison": ">=",
                "threshold": "0.75",
            },
        ),
        {"positive_neighbor_fraction": Decimal(2) / Decimal(3)},
    )
    assert result[0]["passed"] is False


def test_synthetic_one_worker_and_four_worker_outputs_are_byte_identical() -> None:
    result = _parallel_equivalence(_REPOSITORY, source_commit="a" * 40)
    fixtures = cast(list[Mapping[str, object]], result["fixtures"])

    assert result["worker_counts"] == [1, 4]
    assert result["fixture_count"] == 4
    assert result["protected_inputs_accessed"] is False
    assert result["equivalent"] is True
    assert all(
        fixture["specification_equal"] is True
        and fixture["metrics_equal"] is True
        and fixture["event_ledger_equal"] is True
        and fixture["canonical_report_equal"] is True
        for fixture in fixtures
    )


def test_campaign_store_retries_only_expired_leases_and_stops_after_three(
    tmp_path: Path,
) -> None:
    store = IntradayEventDrift001Store(tmp_path / PROGRAM_ID)
    runner = _runner(workers=4)
    specification = runner._specification(
        "discovery",
        runner.plan.configurations[0],
        runner.plan.periods[0],
        "normal",
    )
    run_id = _run_id(specification)
    store.bind({"program_id": PROGRAM_ID, "source_commit": "a" * 40})
    store.reserve((specification,))
    started = datetime(2026, 8, 23, 12, tzinfo=UTC)

    for attempt_number in range(1, 4):
        claim = store.attempts.claim(run_id, source_sha="a" * 40, started_at=started)
        assert claim.attempt_number == attempt_number
        assert str(claim.attempt_id).startswith("ied001a-")
        assert store.attempts.expire_stale(started + timedelta(seconds=300)) == (run_id,)
        started += timedelta(seconds=301)

    row = store.get(run_id)
    assert row["status"] == "failed"
    assert row["failure_class"] == "infrastructure"
    assert row["failure_reason"] == "attempt-limit-exhausted:lease-expired"


def test_campaign_store_records_calendar_integrity_as_terminal(tmp_path: Path) -> None:
    store = IntradayEventDrift001Store(tmp_path / PROGRAM_ID)
    runner = _runner(workers=4)
    specification = runner._specification(
        "discovery",
        runner.plan.configurations[0],
        runner.plan.periods[0],
        "normal",
    )
    run_id = _run_id(specification)
    store.bind({"program_id": PROGRAM_ID, "source_commit": "a" * 40})
    store.reserve((specification,))
    claim = store.attempts.claim(
        run_id,
        source_sha="a" * 40,
        started_at=datetime(2026, 8, 23, 12, tzinfo=UTC),
    )

    store.fail(claim, failure_class="calendar", reason="duplicate eligible event session")

    row = store.get(run_id)
    stored = store.attempts.get(run_id)
    assert row["status"] == "failed"
    assert row["failure_class"] == "calendar"
    assert row["failure_reason"] == "duplicate eligible event session"
    assert stored["failure_class"] == "data"
    assert str(stored["failure_reason"]).startswith("calendar-integrity: ")
    assert store.expire_stale() == ()
    with pytest.raises(AttemptStateError, match="terminal"):
        store.claim(run_id, source_sha="a" * 40)
