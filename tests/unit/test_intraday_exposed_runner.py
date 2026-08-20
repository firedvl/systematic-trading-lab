from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from systematic_trading_lab.backtesting import CostModel
from systematic_trading_lab.calendar import expected_bar_timestamps
from systematic_trading_lab.domain import OHLCVBar, Symbol, Timeframe
from systematic_trading_lab.fingerprints import canonical_json, canonicalize, fingerprint
from systematic_trading_lab.intraday_exposed_runner import (
    PROGRAM_ID,
    REPORT_SCHEMA,
    REQUIRED_REPORTING_FIELDS,
    REVIEWED_PLAN_SHA256,
    Configuration,
    EvaluationPeriod,
    IntradayExposedRunner,
    IntradayExposedStateTransitionEngine,
    IntradayExposedStore,
    Scenario,
    _configuration_payload,
    _exclusive_file_lock,
    _required_reporting_metrics,
    _run_id,
    _source_commit,
    load_intraday_exposed_plan,
)
from systematic_trading_lab.intraday_exposed_strategies import build_intraday_exposed_strategy
from systematic_trading_lab.intraday_qualification import load_intraday_qualification_policy
from systematic_trading_lab.strategies import TargetPosition

_REPOSITORY = Path(__file__).resolve().parents[2]
_SPY, _QQQ = Symbol("SPY"), Symbol("QQQ")
_SYMBOLS = (_QQQ, _SPY)


def test_frozen_plan_sha_count_and_neighbors(tmp_path: Path) -> None:
    plan = load_intraday_exposed_plan(_REPOSITORY)
    assert plan.sha256 == REVIEWED_PLAN_SHA256
    assert len(plan.configurations) == 325
    assert [len(plan.family_configurations(family)) for family in "ABCDEFGHIJKLM"] == [
        48,
        32,
        28,
        43,
        32,
        16,
        18,
        16,
        16,
        28,
        12,
        18,
        18,
    ]
    configuration = next(
        item
        for item in plan.configurations
        if item.strategy_id == "absolute-momentum"
        and item.parameter_mapping == {"lookback": 6, "threshold_bps": 5}
    )
    neighbors = plan.neighbors(configuration)
    assert len(neighbors) == 4
    assert all(
        sum(
            left != right
            for left, right in zip(configuration.parameters, neighbor.parameters, strict=True)
        )
        == 1
        for neighbor in neighbors
    )

    target = tmp_path / "config" / "research"
    target.mkdir(parents=True)
    source = _REPOSITORY / "config" / "research" / "intraday-exposed-001-plan-v1.json"
    (target / source.name).write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="SHA-256 differs"):
        load_intraday_exposed_plan(tmp_path)


def test_same_policy_id_with_changed_content_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "repository" / "config" / "research"
    config.mkdir(parents=True)
    plan = _REPOSITORY / "config" / "research" / "intraday-exposed-001-plan-v1.json"
    policy = _REPOSITORY / "config" / "research" / "intraday-qualification-policy-v1.json"
    (config / plan.name).write_bytes(plan.read_bytes())
    payload = json.loads(policy.read_text(encoding="utf-8"))
    payload["purpose"] += " Changed content."
    (config / policy.name).write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(IntradayExposedRunner, "_verify_data", lambda _self: None)
    monkeypatch.setattr(
        "systematic_trading_lab.intraday_exposed_runner._source_commit",
        lambda _repository: "a" * 40,
    )

    with pytest.raises(ValueError, match="qualification policy differs"):
        IntradayExposedRunner(tmp_path / "repository", tmp_path / "data")


def test_source_commit_requires_head_main_and_origin_main(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()

    def git(*arguments: str) -> str:
        return subprocess.run(
            ("git", "-C", str(repository), *arguments),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.name", "Intraday Test")
    git("config", "user.email", "intraday@example.invalid")
    (repository / "source.txt").write_text("main\n", encoding="utf-8")
    git("add", "source.txt")
    git("commit", "-m", "main")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    assert _source_commit(repository) == git("rev-parse", "HEAD")

    git("switch", "-c", "feature")
    (repository / "source.txt").write_text("feature\n", encoding="utf-8")
    git("commit", "-am", "feature")
    with pytest.raises(ValueError, match="HEAD, main, and origin/main"):
        _source_commit(repository)


def test_campaign_lock_rejects_a_second_runner(tmp_path: Path) -> None:
    lock = tmp_path / "campaign.lock"
    with (
        _exclusive_file_lock(lock),
        pytest.raises(ValueError, match="already running"),
        _exclusive_file_lock(lock),
    ):
        pytest.fail("second campaign acquired the lock")


def _specification(name: str, *, stage: str = "test") -> dict[str, object]:
    return {
        "schema_version": "test-v1",
        "name": name,
        "context": {
            "stage": stage,
            "family_id": "A",
            "configuration_id": f"configuration-{name}",
            "period_id": "period-1",
            "scenario_id": "normal",
        },
    }


def test_isolated_store_lifecycle(tmp_path: Path) -> None:
    store = IntradayExposedStore(tmp_path)
    store.bind({"schema_version": "binding-v1", "value": 1})
    exploratory = _specification("exploratory")
    run_id = _run_id(exploratory)
    assert store.begin(exploratory)["status"] == "running"
    completed = store.complete(run_id, {"total_return": "0.1"}, {"trace": "ok"})
    assert completed["status"] == "completed"
    assert store.begin(exploratory)["record_fingerprint"] == completed["record_fingerprint"]

    controlled = (_specification("controlled-1", stage="controlled"),)
    plan_fingerprint = "f" * 64
    store.reserve_controlled(plan_fingerprint, controlled)
    controlled_run_id = _run_id(controlled[0])
    assert store.get(controlled_run_id)["status"] == "pending"  # type: ignore[index]
    store.claim_controlled(controlled_run_id)
    report = tmp_path / "report.json"
    report.write_text("{}\n", encoding="utf-8")
    report_sha = hashlib.sha256(report.read_bytes()).hexdigest()
    record = store.complete_controlled(
        controlled_run_id,
        {"total_return": "0.2"},
        {"trace": "controlled"},
        report,
        report_sha,
    )
    assert record["status"] == "completed"
    row = store.controlled_rows()[0]
    assert row["status"] == "completed"
    assert row["report_sha256"] == report_sha

    failed = _specification("controlled-2", stage="controlled")
    second_store = IntradayExposedStore(tmp_path / "failure")
    second_store.reserve_controlled(plan_fingerprint, (failed,))
    failed_run_id = _run_id(failed)
    second_store.claim_controlled(failed_run_id)
    second_store.fail_controlled(failed_run_id, RuntimeError("expected"))
    assert second_store.get(failed_run_id)["status"] == "failed"  # type: ignore[index]
    assert second_store.controlled_rows()[0]["status"] == "failed"


def _bars(session: date) -> tuple[OHLCVBar, ...]:
    timestamps = expected_bar_timestamps(
        datetime.combine(session, datetime.min.time(), UTC),
        datetime.combine(session, datetime.max.time(), UTC),
        Timeframe.FIVE_MINUTES,
    )
    return tuple(
        OHLCVBar(
            symbol,
            timestamp,
            Decimal("100"),
            Decimal("101"),
            Decimal("99"),
            Decimal("100"),
            1000,
        )
        for timestamp in timestamps
        for symbol in _SYMBOLS
    )


def _rotation_bars() -> tuple[OHLCVBar, ...]:
    bars = _bars(date(2026, 1, 5))
    spy = ("100", "100", "100", "104", "102", "102", "102")
    qqq = ("100", "100", "100", "101", "105", "106", "107")
    result = []
    indexes = {_SPY: 0, _QQQ: 0}
    for bar in bars:
        values = spy if bar.symbol == _SPY else qqq
        index = indexes[bar.symbol]
        price = Decimal(values[index] if index < len(values) else values[-1])
        indexes[bar.symbol] += 1
        result.append(
            OHLCVBar(
                bar.symbol,
                bar.timestamp,
                price,
                price + 1,
                price - 1,
                price,
                bar.volume,
            )
        )
    return tuple(result)


@dataclass(frozen=True)
class _ScheduledStrategy:
    late_index: int | None = None
    always_long: bool = False
    strategy_id: str = "scheduled-test"
    version: str = "1"

    def on_session(
        self,
        bars: Sequence[OHLCVBar],
        history: Mapping[Symbol, Sequence[OHLCVBar]],
    ) -> Sequence[TargetPosition]:
        index = len(history[_SPY]) - 1
        if self.always_long:
            weights = {_SPY: Decimal("0.5"), _QQQ: Decimal("0.5")}
        elif self.late_index is not None:
            weight = Decimal("0.5") if index >= self.late_index else Decimal("0")
            weights = {_SPY: weight, _QQQ: weight}
        else:
            weights = {
                _SPY: Decimal("0.5") if 1 <= index < 3 else Decimal("0"),
                _QQQ: Decimal("0.5") if 2 <= index < 4 else Decimal("0"),
            }
        return tuple(TargetPosition(symbol, weights[symbol], "scheduled") for symbol in _SYMBOLS)


def _engine(delay: int) -> IntradayExposedStateTransitionEngine:
    return IntradayExposedStateTransitionEngine(
        Decimal("100000"), CostModel("test", Decimal("0"), Decimal("0")), delay
    )


def test_multi_symbol_fifo_delays_preserve_cadence_and_signal_timestamps() -> None:
    bars = _bars(date(2026, 1, 5))
    results = [_engine(delay).run(bars, _ScheduledStrategy()) for delay in (1, 2, 3)]
    decision_signatures = [
        tuple((item.timestamp, item.changed_symbols) for item in result.decisions)
        for result in results
    ]
    assert decision_signatures[0] == decision_signatures[1] == decision_signatures[2]
    assert len(results[0].decisions) == 78
    assert sum(bool(changed) for _, changed in decision_signatures[0]) == 4
    assert [len(result.trades) for result in results] == [4, 4, 4]

    signal_timestamps = [
        tuple(item.decision_timestamp for item in result.transitions if item.source == "strategy")
        for result in results
    ]
    assert signal_timestamps[0] == signal_timestamps[1] == signal_timestamps[2]
    latency_seconds = [
        {
            int((item.eligible_fill_timestamp - item.decision_timestamp).total_seconds())
            for item in result.transitions
            if item.source == "strategy" and item.eligible_fill_timestamp is not None
        }
        for result in results
    ]
    assert latency_seconds == [{0}, {300}, {600}]


@pytest.mark.parametrize("delay", [1, 2, 3])
def test_full_weight_rotation_flattens_before_replacement_buy(delay: int) -> None:
    strategy = build_intraday_exposed_strategy(
        "single-horizon-relative-strength",
        _SYMBOLS,
        {"lookback": 3, "threshold_bps": 0},
    )
    result = IntradayExposedStateTransitionEngine(
        Decimal("100000"), CostModel("normal", Decimal("5"), Decimal("1")), delay
    ).run(_rotation_bars(), strategy)
    target_states = [
        {target.symbol: target.weight for target in decision.desired_targets}
        for decision in result.decisions
    ]
    flat_index = next(
        index
        for index, state in enumerate(target_states)
        if index > 3 and set(state.values()) == {Decimal("0")}
    )
    qqq_index = next(
        index
        for index, state in enumerate(target_states)
        if index > flat_index and state[_QQQ] == Decimal("1")
    )
    assert flat_index < qqq_index
    assert all(point.cash >= 0 for point in result.equity_curve)
    assert all(quantity == 0 for _, quantity in result.equity_curve[-1].positions)


@pytest.mark.parametrize("session", [date(2026, 1, 5), date(2025, 7, 3)])
@pytest.mark.parametrize("delay", [1, 2, 3])
def test_normal_and_early_close_flatten_and_reject_late_signals(session: date, delay: int) -> None:
    bars = _bars(session)
    result = _engine(delay).run(bars, _ScheduledStrategy(always_long=True))
    assert all(quantity == 0 for _, quantity in result.equity_curve[-1].positions)
    assert result.trades[-1].fill_timestamp == max(bar.timestamp for bar in bars)
    assert sum(item.source == "mandatory-session-flatten" for item in result.transitions) == 2

    bar_count = len({bar.timestamp for bar in bars})
    cutoff = bar_count - delay - 1
    late = _engine(delay).run(bars, _ScheduledStrategy(late_index=cutoff))
    assert not late.trades
    assert (
        sum(
            item.status == "rejected" and item.reason == "session-close-cutoff"
            for item in late.transitions
        )
        == 2
    )
    assert all(quantity == 0 for _, quantity in late.equity_curve[-1].positions)


def _runner_without_data(tmp_path: Path) -> IntradayExposedRunner:
    runner = object.__new__(IntradayExposedRunner)
    runner.repository = _REPOSITORY
    runner.runtime_root = tmp_path
    runner.plan = load_intraday_exposed_plan(_REPOSITORY)
    runner.policy = load_intraday_qualification_policy(
        _REPOSITORY / "config" / "research" / "intraday-qualification-policy-v1.json"
    )
    runner.source_commit = "a" * 40
    runner.implementation_pr = 142
    runner.progress = lambda _message: None
    runner.store = IntradayExposedStore(tmp_path)
    return runner


def test_recovery_marks_exploratory_claim_failed_without_rerunning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner_without_data(tmp_path)
    configuration = runner.plan.configurations[0]
    specification = runner._specification(
        configuration,
        runner.plan.discovery,
        runner.plan.scenarios["normal"],
        stage="discovery",
    )
    run_id = _run_id(specification)
    runner.store.begin(specification)
    runner._recover_interrupted_runs()
    monkeypatch.setattr(
        runner,
        "_bars",
        lambda _period: pytest.fail("recovered execution was rerun"),
    )

    record = runner._execute(
        configuration,
        runner.plan.discovery,
        runner.plan.scenarios["normal"],
        stage="discovery",
    )
    assert record["status"] == "failed"
    assert "was not rerun" in str(record["error"])
    assert runner._passes_discovery({"normal": record, "zero-cost": record}) is False
    assert runner.store.get(run_id) == record
    with pytest.raises(RuntimeError, match="incomplete after discovery"):
        runner._require_no_failed_runs("discovery")


@pytest.mark.parametrize("publish_report", [False, True])
def test_recovery_closes_controlled_claim_without_rerunning(
    tmp_path: Path, publish_report: bool
) -> None:
    runner = _runner_without_data(tmp_path)
    configuration = runner.plan.configurations[0]
    specification = runner._specification(
        configuration,
        runner.plan.controlled_period,
        runner.plan.scenarios["normal"],
        stage="controlled",
        controlled_role="base",
    )
    run_id = _run_id(specification)
    runner.store.reserve_controlled("f" * 64, (specification,))
    runner.store.claim_controlled(run_id)
    destination = tmp_path / "controlled-reports" / f"{run_id}.json"
    if publish_report:
        report: dict[str, object] = {
            "schema_version": REPORT_SCHEMA,
            "program_id": PROGRAM_ID,
            "status": "completed",
            "provenance": canonicalize(specification),
            "metrics": {"total_return": Decimal("0.01")},
            "execution_evidence": {"decision_trace_fingerprint": "trace"},
        }
        report["report_fingerprint"] = fingerprint(report)
        destination.parent.mkdir(parents=True)
        destination.write_text(canonical_json(report) + "\n", encoding="utf-8")

    runner._recover_interrupted_runs()
    row = runner.store.controlled_rows()[0]
    assert row["status"] == ("completed" if publish_report else "failed")
    record = runner.store.get(run_id)
    assert record is not None
    assert record["status"] == row["status"]
    if publish_report:
        assert row["report_sha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()
    else:
        assert "was not rerun" in str(record["error"])


def test_required_reporting_has_every_frozen_field_with_explicit_nulls() -> None:
    unavailable = _required_reporting_metrics(Decimal("100000"), None, None)
    assert tuple(unavailable) == REQUIRED_REPORTING_FIELDS
    assert set(unavailable.values()) == {None}

    normal = {
        "status": "completed",
        "metrics": {
            "total_return": "0.01",
            "sharpe_ratio": "1.2",
            "max_drawdown": "0.03",
            "turnover": "2",
            "fill_count": 4,
            "completed_round_trip_count": 2,
            "hit_rate": "0.5",
            "average_trade": "10",
            "cost_paid_total": "25",
            "average_holding_duration_seconds": "900",
            "exposure_bar_percentage": "0.4",
            "average_long_state_seconds": "600",
            "average_flat_state_seconds": "1200",
        },
        "details": {
            "time_of_day_profit": {"open": "10"},
            "symbol_profit": {"SPY": "10", "QQQ": "5"},
        },
    }
    zero = {
        "status": "completed",
        "metrics": {"total_return": "0.02"},
        "details": {},
    }
    screen = {
        "fold_returns": {"wf-1": "0.01"},
        "worst_fold_return": "0.01",
        "fold_return_dispersion": "0.002",
        "stress_retentions": {"stress-a": "0.8", "stress-b": "0.5"},
        "neighbor_retentions": {"neighbor-1": "0.7"},
    }
    available = _required_reporting_metrics(Decimal("100000"), normal, zero, screen)
    assert available["cost_to_zero_cost_profit_ratio"] == Decimal("0.0125")
    assert available["average_holding_duration"] == Decimal("900")
    assert available["chronological_block_performance"] == {"wf-1": "0.01"}


def test_controlled_execution_requires_both_freeze_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner_without_data(tmp_path)
    configuration = next(
        item
        for item in runner.plan.configurations
        if item.strategy_id == "absolute-momentum"
        and item.parameter_mapping == {"lookback": 6, "threshold_bps": 5}
    )
    screen = {"configuration": _configuration_payload(configuration), "passed": True}
    freeze = runner._freeze_cohort((configuration,), (screen,))
    assert (tmp_path / "cohort-freeze.json").is_file()
    assert (tmp_path / "controlled-plan.json").is_file()
    assert not runner.store.controlled_rows()
    calls = 0

    def fail_after_freeze(
        run_configuration: Configuration,
        period: EvaluationPeriod,
        scenario: Scenario,
        **kwargs: object,
    ) -> dict[str, object]:
        nonlocal calls
        assert (tmp_path / "cohort-freeze.json").is_file()
        assert (tmp_path / "controlled-plan.json").is_file()
        parent_run_id = kwargs.get("parent_run_id")
        neighbor_of = kwargs.get("neighbor_of")
        controlled_role = kwargs.get("controlled_role")
        assert isinstance(parent_run_id, str | None)
        assert isinstance(neighbor_of, str | None)
        assert isinstance(controlled_role, str | None)
        specification = runner._specification(
            run_configuration,
            period,
            scenario,
            stage=str(kwargs["stage"]),
            parent_run_id=parent_run_id,
            neighbor_of=neighbor_of,
            controlled_role=controlled_role,
        )
        run_id = _run_id(specification)
        runner.store.claim_controlled(run_id)
        runner.store.fail_controlled(run_id, RuntimeError("synthetic stop"))
        calls += 1
        raise RuntimeError("synthetic stop")

    monkeypatch.setattr(runner, "_execute", fail_after_freeze)
    results = runner._run_controlled((configuration,), freeze)
    assert calls == len(runner.store.controlled_rows())
    assert results[0]["passed"] is False
    assert {row["status"] for row in runner.store.controlled_rows()} == {"failed"}


def test_empty_cohort_freezes_without_controlled_plan(tmp_path: Path) -> None:
    runner = _runner_without_data(tmp_path)
    freeze = runner._freeze_cohort((), ())
    assert (tmp_path / "cohort-freeze.json").is_file()
    assert not (tmp_path / "controlled-plan.json").exists()
    assert freeze["controlled_plan"] is None
    assert not runner.store.controlled_rows()
