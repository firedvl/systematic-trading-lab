from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

import systematic_trading_lab.intraday_event_opening_breakout_001_cli as cli_module
import systematic_trading_lab.intraday_event_opening_breakout_001_runner as runner_module
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.intraday_event_drift_001_plan import (
    load_intraday_event_drift_001_plan,
)
from systematic_trading_lab.intraday_event_drift_001_runner import _dataset_bindings
from systematic_trading_lab.intraday_event_opening_breakout_001_cli import (
    event_opening_breakout_parser,
)
from systematic_trading_lab.intraday_event_opening_breakout_001_launch_control import (
    REVIEWED_LAUNCH_CONTROL_FINGERPRINT,
    REVIEWED_LAUNCH_CONTROL_SHA256,
)
from systematic_trading_lab.intraday_event_opening_breakout_001_plan import (
    PLAN_FINGERPRINT,
    PLAN_RELATIVE_PATH,
    PLAN_SHA256,
    PROGRAM_ID,
    REVIEW_FINGERPRINT,
    REVIEW_RELATIVE_PATH,
    REVIEW_SHA256,
    load_intraday_event_opening_breakout_001_plan,
)
from systematic_trading_lab.intraday_event_opening_breakout_001_runner import (
    IntradayEventOpeningBreakout001Runner,
    IntradayEventOpeningBreakout001Store,
    _aggregate_event_reports,
    _deduplicate_specifications,
    _parallel_equivalence,
    _require_non_broker_environment,
    _run_id,
    intraday_event_opening_breakout_001_plan_summary,
    intraday_event_opening_breakout_001_status,
)
from systematic_trading_lab.intraday_execution_cost_model import (
    load_intraday_execution_cost_model,
)
from systematic_trading_lab.intraday_exposed_002_runner import (
    IntradayExposed002Runner,
    _scenarios,
)

_REPOSITORY = Path(__file__).resolve().parents[2]
_SOURCE = "0" * 40
_IMPLEMENTATION_SOURCE = "017a7cbd91a151fbdc0ddf80f5f580f0c3f9eb34"


def _allow_unreviewed_test_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_module, "REVIEWED_LAUNCH_CONTROL_SHA256", "1" * 64)
    monkeypatch.setattr(runner_module, "REVIEWED_LAUNCH_CONTROL_FINGERPRINT", "2" * 64)
    monkeypatch.setattr(runner_module, "_source_commit", lambda _repository: _SOURCE)
    monkeypatch.setattr(
        runner_module,
        "_load_launch_control",
        lambda _repository, *, source_commit: {"source_commit": source_commit},
    )


def _runner() -> IntradayEventOpeningBreakout001Runner:
    runner = object.__new__(IntradayEventOpeningBreakout001Runner)
    runner.repository = _REPOSITORY
    runner.source_commit = _SOURCE
    runner.plan = load_intraday_event_opening_breakout_001_plan(_REPOSITORY)
    runner.base_plan = load_intraday_event_drift_001_plan(_REPOSITORY)
    runner.cost_model = load_intraday_execution_cost_model(_REPOSITORY)
    runner.datasets = _dataset_bindings(runner.base_plan.payload)
    runner.scenarios = _scenarios(runner.cost_model)
    return runner


def test_plan_status_cli_and_unbound_launch_are_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner_module, "REVIEWED_LAUNCH_CONTROL_SHA256", None)
    monkeypatch.setattr(runner_module, "REVIEWED_LAUNCH_CONTROL_FINGERPRINT", None)
    plan = intraday_event_opening_breakout_001_plan_summary(_REPOSITORY)
    status = intraday_event_opening_breakout_001_status(tmp_path)
    arguments = event_opening_breakout_parser().parse_args(("run", "--workers", "6"))

    assert plan["parent_configuration_count"] == 3
    assert plan["discovery_run_specification_count"] == 6
    assert plan["maximum_run_specifications"] == 46
    assert plan["maximum_attempts"] == 138
    assert plan["launchable"] is False
    assert plan["launch_control_bound"] is False
    assert status["database_exists"] is False
    assert arguments.workers == 6
    assert not any(cast(dict[str, bool], status["authority"]).values())
    assert not (tmp_path / PROGRAM_ID).exists()

    with pytest.raises(ValueError, match="launch control is not hash-bound"):
        IntradayEventOpeningBreakout001Runner(_REPOSITORY, tmp_path)
    assert not (tmp_path / PROGRAM_ID).exists()


def test_closed_campaign_launch_control_rejects_successor_source() -> None:
    path = _REPOSITORY / runner_module.LAUNCH_CONTROL_RELATIVE_PATH
    raw = path.read_bytes()
    review = cast(dict[str, Any], json.loads(raw))
    stored = cast(str, review.pop("review_fingerprint"))

    assert hashlib.sha256(raw).hexdigest() == REVIEWED_LAUNCH_CONTROL_SHA256
    assert stored == REVIEWED_LAUNCH_CONTROL_FINGERPRINT
    assert fingerprint(review) == stored
    with pytest.raises(ValueError, match="implementation file differs"):
        runner_module._load_launch_control(
            _REPOSITORY,
            source_commit=_IMPLEMENTATION_SOURCE,
        )


@pytest.mark.parametrize(
    "reason",
    (
        "launch control review is missing",
        "launch control SHA-256 differs",
        "launch source lineage differs",
    ),
)
def test_plan_summary_requires_valid_launch_control(
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    monkeypatch.setattr(runner_module, "REVIEWED_LAUNCH_CONTROL_SHA256", "0" * 64)
    monkeypatch.setattr(runner_module, "REVIEWED_LAUNCH_CONTROL_FINGERPRINT", "1" * 64)
    monkeypatch.setattr(runner_module, "_source_commit", lambda _repository: _SOURCE)

    def reject(_repository: Path, *, source_commit: str) -> None:
        assert source_commit == _SOURCE
        raise ValueError(reason)

    monkeypatch.setattr(runner_module, "_load_launch_control", reject)
    pending = intraday_event_opening_breakout_001_plan_summary(_REPOSITORY)
    assert pending["status"] == "implementation-awaiting-review"
    assert pending["launchable"] is False
    assert pending["launch_control_bound"] is False

    monkeypatch.setattr(
        runner_module,
        "_load_launch_control",
        lambda _repository, *, source_commit: {"source_commit": source_commit},
    )
    ready = intraday_event_opening_breakout_001_plan_summary(_REPOSITORY)
    assert ready["status"] == "launch-reviewed-ready"
    assert ready["launchable"] is True
    assert ready["launch_control_bound"] is True


def test_cli_delegates_every_other_command_to_the_existing_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: tuple[str, ...] | None = None

    def delegated(arguments: tuple[str, ...]) -> int:
        nonlocal received
        received = arguments
        return 17

    monkeypatch.setattr(cli_module, "repricing_main", delegated)

    assert cli_module.main(("research", "list-strategies")) == 17
    assert received == ("research", "list-strategies")
    assert (
        'trading-lab = "systematic_trading_lab.intraday_fed_policy_absorption_001_cli:main"'
        in (_REPOSITORY / "pyproject.toml").read_text()
    )


def test_coordinator_and_worker_use_the_explicit_inherited_data_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_unreviewed_test_source(monkeypatch)
    observed: list[Mapping[str, Any]] = []

    def verify(_target: object, payload: Mapping[str, Any] | None = None) -> None:
        assert payload is not None
        observed.append(payload)

    monkeypatch.setattr(IntradayExposed002Runner, "_verify_datasets", verify)
    service = cast(Any, object())
    coordinator = IntradayEventOpeningBreakout001Runner(
        _REPOSITORY,
        tmp_path / "coordinator",
        data_service=service,
    )
    assert "data" not in coordinator.plan.payload
    assert observed[-1] == coordinator.base_plan.payload

    monkeypatch.setattr(runner_module, "_read_only_dataset_services", lambda *_args: {})
    worker = runner_module._WorkerFactory(
        _REPOSITORY,
        tmp_path / "worker-data",
        tmp_path / "worker-runtime",
        _SOURCE,
    )()
    assert "data" not in worker.plan.payload
    assert observed[-1] == worker.base_plan.payload


def test_broker_environment_fails_before_source_plan_or_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_checked = False

    def unexpected_source(_repository: Path) -> str:
        nonlocal source_checked
        source_checked = True
        return _SOURCE

    monkeypatch.setattr(runner_module, "_source_commit", unexpected_source)
    monkeypatch.setenv("APCA_API_SECRET_KEY", "must-not-reach-research")
    with pytest.raises(ValueError, match="APCA_API_SECRET_KEY") as error:
        IntradayEventOpeningBreakout001Runner(_REPOSITORY, tmp_path)
    assert "must-not-reach-research" not in str(error.value)
    assert source_checked is False
    assert not (tmp_path / PROGRAM_ID).exists()

    with pytest.raises(ValueError, match="paper-write opt-in"):
        _require_non_broker_environment({"TRADING_LAB_PAPER_ACTIVATION_ID": "value"})


def test_worker_repeats_the_non_broker_guard_before_plan_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_loaded = False

    def unexpected_plan(*_args: object) -> object:
        nonlocal plan_loaded
        plan_loaded = True
        raise AssertionError("plan loaded")

    monkeypatch.setattr(
        runner_module,
        "load_intraday_event_opening_breakout_001_plan",
        unexpected_plan,
    )
    monkeypatch.setenv("TRADING_LAB_PAPER_CODE_COMMIT", "must-not-reach-worker")
    with pytest.raises(ValueError, match="TRADING_LAB_PAPER_CODE_COMMIT"):
        runner_module._WorkerFactory(_REPOSITORY, tmp_path, tmp_path / "runtime", _SOURCE)()
    with pytest.raises(ValueError, match="TRADING_LAB_PAPER_CODE_COMMIT"):
        runner_module._EquivalenceWorkerFactory(_REPOSITORY)()
    assert plan_loaded is False
    assert not (tmp_path / "runtime").exists()


def test_run_identity_budget_is_exact_and_reuses_neighbor_evidence(tmp_path: Path) -> None:
    runner = _runner()
    periods = runner.plan.periods[1:]
    discovery = tuple(
        runner._specification(configuration, runner.plan.periods[0], scenario)
        for configuration in runner.plan.configurations
        for scenario in ("normal", "zero_cost_diagnostic")
    )
    walk = tuple(
        runner._specification(runner._configuration(candidate), period, scenario)
        for candidate in ("ieb001-a01", "ieb001-a02")
        for period in periods
        for scenario in ("normal", "zero_cost_diagnostic")
    )
    stress = tuple(
        runner._specification(runner._configuration("ieb001-a02"), period, scenario)
        for period in periods
        for scenario in ("stress_a", "stress_b", "normal-delay-2", "normal-delay-3")
    )
    neighbors = tuple(
        runner._specification(runner._configuration(candidate), period, scenario)
        for candidate in ("ieb001-a01", "ieb001-a03")
        for period in periods
        for scenario in ("normal", "zero_cost_diagnostic")
    )
    specifications = _deduplicate_specifications(discovery + walk + stress + neighbors)

    assert (len(discovery), len(walk), len(stress), len(neighbors)) == (6, 16, 16, 16)
    assert len(specifications) == 46
    assert (
        sum(
            _run_id(value) not in {_run_id(item) for item in discovery + walk + stress}
            for value in _deduplicate_specifications(neighbors)
        )
        == 8
    )
    sample = discovery[0]
    changed_metadata = dict(sample, source_commit="f" * 40)
    assert _run_id(sample) == _run_id(changed_metadata)
    with pytest.raises(ValueError, match="canonical run identity collides"):
        _deduplicate_specifications((sample, changed_metadata))
    with pytest.raises(ValueError, match="canonical run context differs"):
        _run_id(
            dict(
                sample,
                context={**cast(dict[str, object], sample["context"]), "stage": "neighbor"},
            )
        )

    store = IntradayEventOpeningBreakout001Store(tmp_path)
    store.reserve(specifications)
    assert len(store.list_runs()) == 46
    extra = deepcopy(specifications[0])
    cast(dict[str, object], extra["context"])["candidate_id"] = "ieb001-extra"
    with pytest.raises(ValueError, match="budget exceeds 46"):
        store.reserve((extra,))


def _equivalence_result(candidate_id: str, scenario_id: str) -> Mapping[str, object]:
    worker = runner_module._EquivalenceWorker(_REPOSITORY)
    return worker(
        {
            "source_commit": _SOURCE,
            "context": {"candidate_id": candidate_id, "scenario_id": scenario_id},
        }
    )


def test_event_report_retains_signal_and_enforces_active_inactive_contract() -> None:
    normal = _equivalence_result("ieb001-a01", "normal")
    delayed = _equivalence_result("ieb001-a01", "normal-delay-3")
    metrics = cast(Mapping[str, object], normal["metrics"])
    ledger = cast(list[dict[str, object]], normal["event_ledger"])

    assert metrics["eligible_event_count"] == 2
    assert metrics["active_event_count"] == 1
    assert metrics["completed_round_trips"] == 1
    assert metrics["signal_trace_mismatch_count"] == 0
    assert normal["signal_trace_fingerprint"] == delayed["signal_trace_fingerprint"]
    active = next(row for row in ledger if row["active"] is True)
    inactive = next(row for row in ledger if row["active"] is False)
    assert active["breakout_bar_index"] == 6
    assert active["breakout_decision_timestamp"] == active["entry_fill_timestamp"]
    assert active["exit_decision_timestamp"] == active["exit_fill_timestamp"]
    assert inactive["opening_range_high"] == Decimal("100")
    assert inactive["breakout_threshold"] == Decimal("100.02")
    assert all(
        inactive[key] is None
        for key in (
            "breakout_bar_index",
            "breakout_decision_timestamp",
            "entry_fill_timestamp",
            "exit_decision_timestamp",
            "exit_fill_timestamp",
        )
    )
    assert inactive["net_profit_loss"] == 0

    signal = cast(list[dict[str, object]], normal["signal_trace"])
    assert set(signal[0]) == {
        "event_id",
        "breakout_buffer_bps",
        "opening_range_high",
        "breakout_threshold",
        "active",
        "breakout_bar_index",
        "breakout_decision_timestamp",
        "exit_decision_timestamp",
    }


def test_event_aggregation_recomputes_ledger_concentrations() -> None:
    result = _equivalence_result("ieb001-a01", "normal")
    metrics = cast(dict[str, object], deepcopy(result["metrics"]))
    ledger = cast(list[dict[str, object]], deepcopy(result["event_ledger"]))
    details = {
        "event_ledger": ledger,
        "signal_trace_fingerprint": result["signal_trace_fingerprint"],
        "symbol_net_profit_loss": {"QQQ": Decimal("0"), "SPY": metrics["net_profit_loss"]},
    }
    first: Mapping[str, Any] = {"metrics": metrics, "details": details}
    second = deepcopy(first)
    for row in cast(list[dict[str, object]], second["details"]["event_ledger"]):
        row["event_id"] = f"second-{row['event_id']}"

    aggregate = _aggregate_event_reports((first, second))

    assert aggregate["eligible_event_count"] == 4
    assert aggregate["active_event_count"] == 2
    assert (
        abs(
            cast(Decimal, aggregate["event_net_profit_loss"])
            - 2 * cast(Decimal, metrics["net_profit_loss"])
        ).quantize(Decimal("0.000000000001"))
        == 0
    )
    assert aggregate["positive_profit_event_concentration"] == Decimal("0.5")
    assert aggregate["signal_trace_mismatch_count"] == 0
    assert aggregate["accounting_identity_error"] == 0


def test_synthetic_one_worker_and_four_worker_reports_are_byte_identical() -> None:
    result = _parallel_equivalence(_REPOSITORY, source_commit=_SOURCE)

    assert result["equivalent"] is True
    assert result["worker_counts"] == [1, 4]
    assert result["fixture_count"] == 4
    assert result["protected_inputs_accessed"] is False
    for fixture in cast(list[dict[str, object]], result["fixtures"]):
        assert fixture["specification_equal"] is True
        assert fixture["report_equal"] is True
        assert fixture["event_ledger_equal"] is True
        assert fixture["canonical_report_equal"] is True


def _launch_review(repository: Path, equivalence: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": runner_module._LAUNCH_CONTROL_SCHEMA,
        "review_id": runner_module._LAUNCH_CONTROL_SCHEMA,
        "status": "passed",
        "verdict": "pass",
        "review_date": "2026-08-23",
        "review_method": "Independent synthetic and source review.",
        "reviewed_inputs": {
            "plan": {
                "path": PLAN_RELATIVE_PATH.as_posix(),
                "sha256": PLAN_SHA256,
                "fingerprint": PLAN_FINGERPRINT,
            },
            "plan_review": {
                "path": REVIEW_RELATIVE_PATH.as_posix(),
                "sha256": REVIEW_SHA256,
                "fingerprint": REVIEW_FINGERPRINT,
            },
            "base_plan": {
                "path": "config/research/intraday-event-drift-001-plan-v1.json",
                "sha256": "c0dade2573405ddcd38d88814c10a27c3caae11bfb925a21179f6741cc20233c",
                "fingerprint": "73933d470feb52c1135746ab57db742019077b8b39e8e2545e9aba37c9a8d838",
            },
            "base_plan_review": {
                "path": "config/research/intraday-event-drift-001-plan-independent-review-v1.json",
                "sha256": "25e92a85cee47aa261b4a85dce57666effbfbe329c203d3ac78df7b5bba9df96",
                "fingerprint": "0a464aca264ad4a8583d12fc4912898461ecf9e6121a1119322229e12bfb4077",
            },
            "calendar": {
                "path": "config/research/intraday-event-calendar-001-v1.json",
                "sha256": "fa413a30234c6b82394fcdbf99df94aa31ae38e2df12d58296bcbc03162a34ee",
                "fingerprint": "9992ee0a430abc0b59f49f6dd9e5178ff22d13a9dec5ad5de1d8578896ed2a78",
            },
            "source_evidence": {
                "path": "config/research/intraday-event-calendar-001-source-evidence-v1.json",
                "sha256": "c5f1ab34c92b10ac9c75d86a3c33c9f2a445eed022a48697edaa7dfd9eabee0a",
                "fingerprint": "6616ed631b3d7e8e727b8cde85bf26e4c2cb5800812db745c327a71bf62192fd",
            },
        },
        "implementation": {
            "source_commit": _SOURCE,
            "files": [
                {
                    "path": path,
                    "sha256": hashlib.sha256((repository / path).read_bytes()).hexdigest(),
                }
                for path in runner_module._LAUNCH_CONTROL_FILES
            ],
        },
        "quality_gates": {
            "source_commit": _SOURCE,
            "results": [
                {"command": command, "status": "passed", "exit_code": 0, "summary": "passed"}
                for command in runner_module._LAUNCH_CONTROL_QUALITY_GATES
            ],
        },
        "equivalence": equivalence,
        "independent_review": {
            "source_commit": _SOURCE,
            "status": "passed",
            "verdict": "pass",
            "findings": [],
            "reviewer": "independent-launch-reviewer",
        },
        "scope_limit": "Synthetic fixtures only; protected and broker state excluded.",
        "authority": dict(runner_module._AUTHORITY),
    }


def test_launch_control_binds_exact_files_equivalence_and_clean_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for relative in runner_module._LAUNCH_CONTROL_FILES:
        source = _REPOSITORY / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    equivalence = _parallel_equivalence(_REPOSITORY, source_commit=_SOURCE)
    review = _launch_review(tmp_path, equivalence)
    review["review_fingerprint"] = fingerprint(review)
    raw = (json.dumps(review, indent=2) + "\n").encode()
    path = tmp_path / runner_module.LAUNCH_CONTROL_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    monkeypatch.setattr(
        runner_module, "REVIEWED_LAUNCH_CONTROL_SHA256", hashlib.sha256(raw).hexdigest()
    )
    monkeypatch.setattr(
        runner_module,
        "REVIEWED_LAUNCH_CONTROL_FINGERPRINT",
        review["review_fingerprint"],
    )

    loaded = runner_module._load_launch_control(tmp_path, source_commit=_SOURCE)
    assert loaded["verdict"] == "pass"

    cast(dict[str, Any], review["independent_review"])["findings"] = ["finding"]
    review.pop("review_fingerprint")
    review["review_fingerprint"] = fingerprint(review)
    raw = (json.dumps(review, indent=2) + "\n").encode()
    path.write_bytes(raw)
    monkeypatch.setattr(
        runner_module, "REVIEWED_LAUNCH_CONTROL_SHA256", hashlib.sha256(raw).hexdigest()
    )
    monkeypatch.setattr(
        runner_module,
        "REVIEWED_LAUNCH_CONTROL_FINGERPRINT",
        review["review_fingerprint"],
    )
    with pytest.raises(ValueError, match="independent review differs"):
        runner_module._load_launch_control(tmp_path, source_commit=_SOURCE)
