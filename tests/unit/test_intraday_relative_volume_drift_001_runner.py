from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

import systematic_trading_lab.intraday_relative_volume_drift_001_runner as runner_module
from systematic_trading_lab.intraday_relative_volume_drift_001_launch_control import (
    REVIEWED_LAUNCH_CONTROL_FINGERPRINT,
    REVIEWED_LAUNCH_CONTROL_SHA256,
)
from systematic_trading_lab.intraday_relative_volume_drift_001_plan import (
    PROGRAM_ID,
    load_intraday_relative_volume_drift_001_plan,
)
from systematic_trading_lab.intraday_relative_volume_drift_001_runner import (
    IntradayRelativeVolumeDrift001Runner,
    IntradayRelativeVolumeDrift001Store,
    _deduplicate_specifications,
    _EquivalenceWorker,
    _load_launch_control,
    _parallel_equivalence,
    _recompute_terminal_screening,
    _require_non_broker_environment,
    decode_canonical_metric,
    intraday_relative_volume_drift_001_plan_summary,
    intraday_relative_volume_drift_001_status,
    validate_accounting,
    validate_paired_traces,
    validate_screen,
    validate_terminal_screening,
)

_REPOSITORY = Path(__file__).resolve().parents[2]
_SOURCE = "0" * 40
_IMPLEMENTATION_SOURCE = "b9efc2c7a4a022177d72935821c3cb0e7b46c598"


def _specification(candidate: str, period: str, scenario: str) -> dict[str, object]:
    return {
        "source_commit": _SOURCE,
        "context": {
            "candidate_id": candidate,
            "period_id": period,
            "scenario_id": scenario,
        },
    }


def _discovery_report(
    candidate: str,
    period: str,
    scenario: str,
    *,
    total_return: object = "-0.01",
) -> dict[str, object]:
    metrics: dict[str, object] = {
        "total_return": total_return,
        "active_session_count": 0,
        "completed_round_trips": 0,
        "max_drawdown": "0",
        "cost_to_gross_profit": None,
        "average_gross_trade_edge_bps": None,
        "positive_profit_symbol_concentration": None,
        "positive_profit_session_concentration": None,
        "positive_profit_participation_bucket_concentration": None,
        "accounting_identity_error": "0",
        "signal_trace_mismatch_count": 0,
    }
    return {
        "specification": _specification(candidate, period, scenario),
        "signal_trace_fingerprint": "a" * 64,
        "execution_evidence": {"decision_trace_fingerprint": "b" * 64},
        "metrics": metrics,
    }


def test_plan_status_and_unbound_launch_are_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner_module, "REVIEWED_LAUNCH_CONTROL_SHA256", None)
    monkeypatch.setattr(runner_module, "REVIEWED_LAUNCH_CONTROL_FINGERPRINT", None)

    plan = intraday_relative_volume_drift_001_plan_summary(_REPOSITORY)
    status = intraday_relative_volume_drift_001_status(tmp_path)
    assert plan["parent_configuration_count"] == 9
    assert plan["maximum_run_specifications"] == 90
    assert plan["maximum_attempts"] == 270
    assert plan["launchable"] is False
    assert status["database_exists"] is False
    assert not (tmp_path / PROGRAM_ID).exists()
    with pytest.raises(ValueError, match="not hash-bound"):
        IntradayRelativeVolumeDrift001Runner(_REPOSITORY, tmp_path)
    assert not (tmp_path / PROGRAM_ID).exists()


def test_historical_launch_control_stays_bound_and_rejects_new_cli_source() -> None:
    assert REVIEWED_LAUNCH_CONTROL_SHA256 == (
        "51159d51aff6b11b9fee9c5c5bacfa3ac3ceaa93c17259b493aeb794d0b5e655"
    )
    assert REVIEWED_LAUNCH_CONTROL_FINGERPRINT == (
        "3b6c46f924ab94557f5235bf26650c1b8bf6f836b0f55bb590e63c1bba86717f"
    )
    with pytest.raises(ValueError, match="implementation file differs"):
        _load_launch_control(_REPOSITORY, source_commit=_IMPLEMENTATION_SOURCE)


def test_broker_credentials_are_rejected_before_campaign_state() -> None:
    with pytest.raises(ValueError, match="broker credentials"):
        _require_non_broker_environment({"APCA_API_KEY_ID": "forbidden"})
    with pytest.raises(ValueError, match="paper-write"):
        _require_non_broker_environment({"TRADING_LAB_PAPER_WRITE": "1"})
    _require_non_broker_environment({"UNRELATED": "safe"})


@pytest.mark.parametrize(
    "value",
    ("1.25", "0", "-2", "4", 3, Decimal("4.0")),
)
def test_canonical_metric_decoder_accepts_frozen_forms(value: object) -> None:
    assert decode_canonical_metric(value) is not None


@pytest.mark.parametrize(
    "value",
    (
        True,
        False,
        1.2,
        " 1",
        "1 ",
        "1e2",
        "01",
        "+1",
        "4.0",
        "0.0",
        "-0",
        "NaN",
        "Infinity",
        "",
        None,
    ),
)
def test_canonical_metric_decoder_rejects_malformed_or_semantic_null(
    value: object,
) -> None:
    with pytest.raises(ValueError):
        decode_canonical_metric(value)


def test_every_stage_gate_uses_strict_reload_and_null_fails() -> None:
    plan = load_intraday_relative_volume_drift_001_plan(_REPOSITORY)
    stage_gates = (
        plan.payload["discovery_screen"]["gates"],
        plan.payload["walk_forward_screen"]["gates"],
        plan.payload["serious_candidate_screen"]["stress_gates"],
        plan.payload["serious_candidate_screen"]["neighbor_gates"],
    )
    for gates in stage_gates:
        gate = gates[0]
        metric = str(gate["metric"])
        with pytest.raises(ValueError):
            validate_screen({metric: 1.5}, (gate,))
        with pytest.raises(ValueError):
            validate_screen({metric: "1e2"}, (gate,))
        assert validate_screen({metric: None}, (gate,)) == (False, (metric,))

    assert validate_screen(
        {"metric": "0.7"},
        ({"metric": "metric", "comparison": "<=", "threshold": "0.70"},),
    ) == (True, ())


def test_accounting_and_paired_trace_validation_fail_closed() -> None:
    validate_accounting(
        {"gross_profit_loss": "10", "execution_friction": "1", "net_profit_loss": "9"}
    )
    with pytest.raises(ValueError, match="accounting"):
        validate_accounting(
            {"gross_profit_loss": "10", "execution_friction": "1", "net_profit_loss": "8"}
        )
    validate_paired_traces(
        {"signal_trace_fingerprint": "a", "decision_trace_fingerprint": "b"},
        {"signal_trace_fingerprint": "a", "decision_trace_fingerprint": "b"},
    )
    with pytest.raises(ValueError, match="mismatch"):
        validate_paired_traces(
            {"signal_trace_fingerprint": "a", "decision_trace_fingerprint": "b"},
            {"signal_trace_fingerprint": "a", "decision_trace_fingerprint": "c"},
        )


def test_store_enforces_90_specification_budget_and_identity_dedup(
    tmp_path: Path,
) -> None:
    store = IntradayRelativeVolumeDrift001Store(tmp_path)
    too_many = tuple(
        _specification(f"candidate-{index}", "period", "normal") for index in range(91)
    )
    with pytest.raises(ValueError, match="exceeds 90"):
        store.reserve(too_many)

    first = _specification("candidate", "period", "normal")
    changed = copy.deepcopy(first)
    changed["source_commit"] = "1" * 40
    with pytest.raises(ValueError, match="collides"):
        _deduplicate_specifications((first, changed))


def test_discovery_executes_all_18_before_reading_merit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = object.__new__(IntradayRelativeVolumeDrift001Runner)
    runner.plan = load_intraday_relative_volume_drift_001_plan(_REPOSITORY)
    completed = False

    def execute(specifications: tuple[dict[str, object], ...]) -> None:
        nonlocal completed
        assert len(specifications) == 18
        completed = True

    monkeypatch.setattr(runner, "_execute", execute)
    monkeypatch.setattr(
        runner,
        "_specification",
        lambda configuration, period, scenario: _specification(
            configuration.candidate_id, period.period_id, scenario
        ),
    )

    def normal_zero(candidate: str, period: str) -> tuple[dict[str, object], dict[str, object]]:
        assert completed
        normal = _discovery_report(candidate, period, "normal", total_return="0.01")
        cast(dict[str, object], normal["metrics"]).update(
            {
                "active_session_count": 12,
                "completed_round_trips": 24,
                "max_drawdown": "0.01",
                "cost_to_gross_profit": "0.1",
                "average_gross_trade_edge_bps": "6",
                "positive_profit_symbol_concentration": "0.5",
                "positive_profit_session_concentration": "0.4",
                "positive_profit_participation_bucket_concentration": "0.5",
            }
        )
        zero = _discovery_report(candidate, period, "zero_cost_diagnostic", total_return="0.02")
        return normal, zero

    monkeypatch.setattr(runner, "_normal_zero", normal_zero)
    result = runner._run_discovery()
    assert len(cast(list[object], result["ledger"])) == 9
    assert len(cast(tuple[str, ...], result["selected"])) == 3


def test_terminal_recomputation_rejects_missing_malformed_and_changed_ledgers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = load_intraday_relative_volume_drift_001_plan(_REPOSITORY)
    period = plan.periods[0].period_id
    reports = [
        _discovery_report(configuration.candidate_id, period, scenario)
        for configuration in plan.configurations
        for scenario in ("normal", "zero_cost_diagnostic")
    ]
    monkeypatch.setattr(runner_module, "_validate_run_report_semantics", lambda _report: None)

    screened, cohort = _recompute_terminal_screening(plan, reports)
    assert cohort == ()
    validate_terminal_screening(plan, reports, screened, cohort)

    changed = copy.deepcopy(screened)
    cast(dict[str, object], changed["discovery"])["selected"] = ["irvd001-a01-b01"]
    with pytest.raises(ValueError, match="terminal screening"):
        validate_terminal_screening(plan, reports, changed, cohort)
    with pytest.raises(ValueError, match="missing"):
        _recompute_terminal_screening(plan, reports[:-1])
    malformed = copy.deepcopy(reports)
    cast(dict[str, object], malformed[0]["metrics"])["total_return"] = 0.5
    with pytest.raises(ValueError, match="bool or float"):
        _recompute_terminal_screening(plan, malformed)


def test_synthetic_engine_has_joint_four_fill_two_trip_fixed_hold() -> None:
    worker = _EquivalenceWorker(_REPOSITORY)
    result = worker(
        {
            "source_commit": _SOURCE,
            "context": {
                "candidate_id": "irvd001-a01-b01",
                "scenario_id": "normal",
            },
        }
    )
    ledger = cast(list[dict[str, Any]], result["session_ledger"])
    active = next(row for row in ledger if row["disposition"] == "active")
    assert active["fill_counts"] == {"QQQ": 2, "SPY": 2}
    assert active["round_trip_counts"] == {"QQQ": 1, "SPY": 1}
    assert active["completed_round_trips"] == 2
    assert (
        active["exit_fill_timestamp"] - active["entry_fill_timestamp"]
    ).total_seconds() == 24 * 5 * 60


def test_synthetic_report_metrics_are_recomputed_from_session_evidence() -> None:
    worker = _EquivalenceWorker(_REPOSITORY)
    result = worker(
        {
            "source_commit": _SOURCE,
            "context": {
                "candidate_id": "irvd001-a01-b01",
                "scenario_id": "normal",
            },
        }
    )
    report = cast(dict[str, Any], json.loads(cast(bytes, result["report_bytes"])))
    runner_module._validate_run_report_semantics(report)

    mutations: tuple[tuple[tuple[str | int, ...], object], ...] = (
        (("metrics", "gross_profit_loss"), "0"),
        (("metrics", "gross_profitable_trade_profit"), "0"),
        (("metrics", "gross_trade_edge_bps_sum"), "0"),
        (("metrics", "average_gross_trade_edge_bps"), "0"),
        (("metrics", "average_holding_bars"), "0"),
        (("metrics", "total_return"), "0"),
        (("metrics", "max_drawdown"), "0.1"),
        (("metrics", "cost_to_gross_profit"), "0"),
        (("metrics", "positive_profit_symbol_concentration"), "0"),
        (("metrics", "positive_profit_session_concentration"), "0"),
        (("metrics", "positive_profit_period_concentration"), "0"),
        (("metrics", "positive_profit_participation_bucket_concentration"), "0"),
        (
            (
                "metrics",
                "participation_bucket_net_profit_loss",
                "participation-q-1-5-plus",
            ),
            "0",
        ),
        (("details", "symbol_net_profit_loss", "QQQ"), "0"),
        (("details", "session_ledger", 0, "gross_trade_edge_bps_sum"), "0"),
        (("details", "session_ledger", 0, "holding_bars_sum"), "0"),
        (("details", "session_ledger", 0, "ending_equity"), "100000"),
    )
    for path, replacement in mutations:
        changed = copy.deepcopy(report)
        target: Any = changed
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = replacement
        with pytest.raises(ValueError):
            runner_module._validate_run_report_semantics(changed)


def test_synthetic_one_worker_four_worker_reports_are_byte_identical() -> None:
    result = _parallel_equivalence(_REPOSITORY, source_commit=_SOURCE)
    assert result["worker_counts"] == [1, 4]
    assert result["equivalent"] is True
    assert result["protected_inputs_accessed"] is False
    fixtures = cast(list[dict[str, object]], result["fixtures"])
    assert len(fixtures) == 4
    assert all(fixture["canonical_report_equal"] is True for fixture in fixtures)
