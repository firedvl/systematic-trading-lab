from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import systematic_trading_lab.intraday_spy_qqq_lead_lag_001_cli as cli_module
import systematic_trading_lab.intraday_spy_qqq_lead_lag_001_runner as runner_module
from systematic_trading_lab.config import Settings
from systematic_trading_lab.domain import TradingMode
from systematic_trading_lab.fingerprints import canonical_json, fingerprint
from systematic_trading_lab.intraday_autonomous_research_program import (
    PROGRAM_FINGERPRINT as AUTONOMOUS_PROGRAM_FINGERPRINT,
)
from systematic_trading_lab.intraday_autonomous_research_program import (
    PROGRAM_RELATIVE_PATH as AUTONOMOUS_PROGRAM_RELATIVE_PATH,
)
from systematic_trading_lab.intraday_autonomous_research_program import (
    PROGRAM_SHA256 as AUTONOMOUS_PROGRAM_SHA256,
)
from systematic_trading_lab.intraday_autonomous_research_program import (
    REVIEW_FINGERPRINT as AUTONOMOUS_REVIEW_FINGERPRINT,
)
from systematic_trading_lab.intraday_autonomous_research_program import (
    REVIEW_RELATIVE_PATH as AUTONOMOUS_REVIEW_RELATIVE_PATH,
)
from systematic_trading_lab.intraday_autonomous_research_program import (
    REVIEW_SHA256 as AUTONOMOUS_REVIEW_SHA256,
)
from systematic_trading_lab.intraday_spy_qqq_lead_lag_001_plan import (
    PLAN_FINGERPRINT,
    PLAN_RELATIVE_PATH,
    PLAN_SHA256,
    PROGRAM_ID,
    REVIEW_FINGERPRINT,
    REVIEW_RELATIVE_PATH,
    REVIEW_SHA256,
    STATE_FINGERPRINT,
    STATE_RELATIVE_PATH,
    STATE_SHA256,
    load_intraday_spy_qqq_lead_lag_001_plan,
)
from systematic_trading_lab.intraday_spy_qqq_lead_lag_001_runner import (
    IntradaySpyQqqLeadLag001Runner,
    IntradaySpyQqqLeadLag001Store,
    _EquivalenceWorker,
    _parallel_equivalence,
    _read_final_report,
    _validate_final_evidence,
    intraday_spy_qqq_lead_lag_001_plan_summary,
    intraday_spy_qqq_lead_lag_001_status,
)
from systematic_trading_lab.research_attempts import AttemptStateError

_REPOSITORY = Path(__file__).resolve().parents[2]
_SOURCE = "0" * 40


def test_plan_status_cli_and_unbound_launch_are_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner_module, "REVIEWED_LAUNCH_CONTROL_SHA256", None)
    monkeypatch.setattr(runner_module, "REVIEWED_LAUNCH_CONTROL_FINGERPRINT", None)

    plan = intraday_spy_qqq_lead_lag_001_plan_summary(_REPOSITORY)
    status = intraday_spy_qqq_lead_lag_001_status(tmp_path)
    arguments = cli_module.spy_qqq_lead_lag_parser().parse_args(("run", "--workers", "6"))

    assert plan["parent_configuration_count"] == 9
    assert plan["maximum_run_specifications"] == 90
    assert plan["maximum_attempts"] == 270
    assert plan["launchable"] is False
    assert status["database_exists"] is False
    assert arguments.workers == 6
    assert not (tmp_path / PROGRAM_ID).exists()
    with pytest.raises(ValueError, match="launch control is not hash-bound"):
        IntradaySpyQqqLeadLag001Runner(_REPOSITORY, tmp_path)
    assert not (tmp_path / PROGRAM_ID).exists()


def test_cli_delegates_and_enforces_research_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    received: tuple[str, ...] | None = None

    def delegated(arguments: tuple[str, ...]) -> int:
        nonlocal received
        received = arguments
        return 17

    monkeypatch.setattr(cli_module, "prior_low_main", delegated)
    assert cli_module.main(("research", "list-strategies")) == 17
    assert received == ("research", "list-strategies")

    monkeypatch.setattr(cli_module, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        cli_module,
        "load_settings",
        lambda: Settings(TradingMode.RESEARCH, tmp_path),
    )
    monkeypatch.setattr(
        cli_module,
        "intraday_spy_qqq_lead_lag_001_plan_summary",
        lambda _repository: {"program_id": PROGRAM_ID},
    )
    assert cli_module.main(("research", PROGRAM_ID, "plan")) == 0
    assert json.loads(capsys.readouterr().out)["program_id"] == PROGRAM_ID

    monkeypatch.setattr(
        cli_module,
        "load_settings",
        lambda: SimpleNamespace(
            mode=TradingMode.RESEARCH,
            home=tmp_path,
            paper_write_request=object(),
        ),
    )
    assert cli_module.main(("research", PROGRAM_ID, "run")) != 0
    assert "paper-write opt-in" in capsys.readouterr().err

    monkeypatch.setattr(
        cli_module,
        "load_settings",
        lambda: Settings(TradingMode.RESEARCH, tmp_path),
    )

    def active(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AttemptStateError("run has an active attempt")

    monkeypatch.setattr(cli_module, "run_intraday_spy_qqq_lead_lag_001_campaign", active)
    assert cli_module.main(("research", PROGRAM_ID, "run")) != 0
    assert "active attempt" in capsys.readouterr().err


def test_accounting_failure_class_survives_generic_store(tmp_path: Path) -> None:
    store = IntradaySpyQqqLeadLag001Store(tmp_path)
    specification = {
        "source_commit": _SOURCE,
        "context": {
            "candidate_id": "isqlll001-a01-b01",
            "period_id": "p",
            "scenario_id": "normal",
        },
    }
    store.reserve((specification,))
    run_id = runner_module._run_id(specification)
    claim = store.claim(run_id, source_sha=_SOURCE)
    store.fail(claim, failure_class="accounting", reason="mismatch")

    row = store.get(run_id)
    assert row["failure_class"] == "accounting"
    assert row["failure_reason"] == "mismatch"


def test_discovery_tie_break_uses_cost_before_candidate_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = object.__new__(IntradaySpyQqqLeadLag001Runner)
    runner.plan = load_intraday_spy_qqq_lead_lag_001_plan(_REPOSITORY)
    monkeypatch.setattr(runner, "_execute", lambda _specifications: None)
    monkeypatch.setattr(
        runner,
        "_specification",
        lambda configuration, period, scenario: {
            "source_commit": _SOURCE,
            "context": {
                "candidate_id": configuration.candidate_id,
                "period_id": period.period_id,
                "scenario_id": scenario,
            },
        },
    )
    costs = {
        item.candidate_id: Decimal(index) / Decimal("100")
        for index, item in enumerate(reversed(runner.plan.configurations), start=1)
    }

    def reports(candidate_id: str, _period_id: str) -> tuple[dict[str, object], dict[str, object]]:
        normal: dict[str, object] = {
            "lead_signal_trace_fingerprint": "f" * 64,
            "metrics": {
                "total_return": Decimal("0.01"),
                "active_session_count": 12,
                "completed_round_trips": 12,
                "max_drawdown": Decimal("0.01"),
                "cost_to_gross_profit": costs[candidate_id],
                "average_gross_trade_edge_bps": Decimal("6"),
                "positive_profit_session_concentration": Decimal("0.4"),
                "positive_profit_signal_bucket_concentration": Decimal("0.5"),
                "signal_trace_mismatch_count": 0,
                "accounting_identity_error": Decimal("0"),
            },
        }
        zero: dict[str, object] = {
            "lead_signal_trace_fingerprint": "f" * 64,
            "metrics": {"total_return": Decimal("0.02")},
        }
        return normal, zero

    monkeypatch.setattr(runner, "_normal_zero", reports)
    result = runner._run_discovery()
    assert result["selected"] == (
        "isqlll001-a03-b03",
        "isqlll001-a03-b02",
        "isqlll001-a03-b01",
    )


def test_synthetic_session_contract_and_parallel_equivalence() -> None:
    worker = _EquivalenceWorker(_REPOSITORY)
    result = worker(
        {
            "source_commit": _SOURCE,
            "context": {
                "candidate_id": "isqlll001-a01-b01",
                "scenario_id": "normal-delay-3",
            },
        }
    )
    ledger = cast(list[dict[str, object]], result["session_ledger"])
    active = next(row for row in ledger if row["active"] is True)
    assert active["qqq_fill_count"] == 2
    assert active["spy_fill_count"] == 0
    assert active["completed_round_trips"] == 1
    assert active["entry_decision_timestamp"] == datetime(2026, 1, 8, 15, 0, tzinfo=UTC)
    assert active["entry_fill_timestamp"] == datetime(2026, 1, 8, 15, 10, tzinfo=UTC)
    assert active["exit_decision_timestamp"] == datetime(2026, 1, 8, 17, 0, tzinfo=UTC)
    assert active["exit_fill_timestamp"] == datetime(2026, 1, 8, 17, 10, tzinfo=UTC)

    equivalence = _parallel_equivalence(_REPOSITORY, source_commit=_SOURCE)
    assert equivalence["equivalent"] is True
    assert equivalence["worker_counts"] == [1, 4]
    assert equivalence["fixture_count"] == 4
    assert equivalence["protected_inputs_accessed"] is False
    for fixture in cast(list[dict[str, object]], equivalence["fixtures"]):
        assert fixture["specification_equal"] is True
        assert fixture["report_equal"] is True
        assert fixture["session_ledger_equal"] is True
        assert fixture["canonical_report_equal"] is True


def test_normal_zero_pair_rejects_decision_trace_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = object.__new__(IntradaySpyQqqLeadLag001Runner)
    reports = {
        "normal": {
            "run_id": "normal-run",
            "lead_signal_trace_fingerprint": "f" * 64,
            "execution_evidence": {"decision_trace_fingerprint": "a" * 64},
        },
        "zero_cost_diagnostic": {
            "run_id": "zero-run",
            "lead_signal_trace_fingerprint": "f" * 64,
            "execution_evidence": {"decision_trace_fingerprint": "b" * 64},
        },
    }
    monkeypatch.setattr(
        runner,
        "_report_for",
        lambda _candidate_id, _period_id, scenario_id: reports[scenario_id],
    )

    with pytest.raises(ValueError, match="paired decision trace differs") as error:
        runner._normal_zero("isqlll001-a01-b01", "discovery-2025-07-through-10")

    assert cast(Any, error.value).classification == "cross-scenario-decision-validation"
    assert cast(Any, error.value).run_ids == ("normal-run", "zero-run")


def test_deterministic_coordinator_error_becomes_terminal_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / runner_module.DATABASE_NAME
    database.write_bytes(b"database")
    runner = object.__new__(IntradaySpyQqqLeadLag001Runner)
    runner.runtime_root = tmp_path
    runner.source_commit = _SOURCE
    runner.workers = 4
    runner.plan = load_intraday_spy_qqq_lead_lag_001_plan(_REPOSITORY)
    runner.attempt_store = cast(
        Any,
        SimpleNamespace(
            path=database,
            list_runs=lambda: (),
            list_attempts=lambda _run_id: (),
            reconcile_reports=lambda: (),
            expire_stale=lambda: (),
        ),
    )
    monkeypatch.setattr(runner, "_load_final_report_if_present", lambda: None)
    monkeypatch.setattr(runner, "_require_no_failures", lambda: None)

    def reject() -> dict[str, object]:
        raise ValueError("deterministic coordinator mismatch")

    monkeypatch.setattr(runner, "_run_discovery", reject)
    result = runner.run()

    assert result["outcome"] == "terminally-interrupted"
    report = _read_final_report(tmp_path / "final-report.json", source_commit=_SOURCE)
    failure = cast(dict[str, object], report["coordinator_failure"])
    assert failure["classification"] == "coordinator-validation"
    assert "deterministic coordinator mismatch" in str(failure["cause"])


def test_final_report_and_freeze_reject_changed_bytes(tmp_path: Path) -> None:
    database = tmp_path / runner_module.DATABASE_NAME
    database.write_bytes(b"database")
    freeze: dict[str, object] = {
        "schema_version": runner_module.FINAL_FREEZE_SCHEMA,
        "program_id": PROGRAM_ID,
        "status": "frozen-after-complete-exposed-screening",
        "source_commit": _SOURCE,
        "runner_version": runner_module.RUNNER_VERSION,
        "engine_version": runner_module.ENGINE_VERSION,
        "strategy_version": runner_module.STRATEGY_VERSION,
        "plan": {
            "sha256": PLAN_SHA256,
            "fingerprint": PLAN_FINGERPRINT,
            "review_sha256": REVIEW_SHA256,
            "review_fingerprint": REVIEW_FINGERPRINT,
            "state_sha256": STATE_SHA256,
            "state_fingerprint": STATE_FINGERPRINT,
        },
        "launch_control": {
            "status": "passed",
            "verdict": "pass",
            "review_fingerprint": runner_module.REVIEWED_LAUNCH_CONTROL_FINGERPRINT,
        },
        "cost_model": {},
        "datasets": [],
        "screened_ledger": {
            "discovery": {},
            "walk_forward": {},
            "stress": {},
            "neighbors": {},
        },
        "cohort": [],
        "cohort_size": 0,
        "all_runtime_runs": [],
        "attempt_summary": {},
        "attempt_histories": [],
        "controlled_boundary": {
            "range_status": "none-eligible",
            "june_read": False,
            "substitute_range": False,
            "controlled_evaluation_performed": False,
        },
        "protected_access": runner_module._protected_access(),
        "authority": runner_module._AUTHORITY,
    }
    freeze["freeze_fingerprint"] = fingerprint(freeze)
    freeze_path = tmp_path / "final-freeze.json"
    freeze_path.write_text(canonical_json(freeze) + "\n")
    report: dict[str, object] = {
        "schema_version": runner_module.FINAL_REPORT_SCHEMA,
        "program_id": PROGRAM_ID,
        "outcome": "no-controlled-qualified-candidate",
        "terminal_message": "complete",
        "source_commit": _SOURCE,
        "plan_sha256": PLAN_SHA256,
        "plan_fingerprint": PLAN_FINGERPRINT,
        "launch_control": {
            "path": runner_module.LAUNCH_CONTROL_RELATIVE_PATH.as_posix(),
            "sha256": runner_module.REVIEWED_LAUNCH_CONTROL_SHA256,
            "fingerprint": runner_module.REVIEWED_LAUNCH_CONTROL_FINGERPRINT,
        },
        "complete_exposed_screening": True,
        "counts": {"cohort": 0},
        "cohort": [],
        "attempt_summary": {},
        "runtime_database": {
            "path": runner_module.DATABASE_NAME,
            "sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
        },
        "final_freeze": {
            "path": "final-freeze.json",
            "sha256": hashlib.sha256(freeze_path.read_bytes()).hexdigest(),
            "fingerprint": freeze["freeze_fingerprint"],
        },
        "controlled_evaluation": {
            "performed": False,
            "reason": "No eligible untouched controlled range exists.",
            "controlled_qualified_claim": False,
        },
        "protected_access": runner_module._protected_access(),
        "authority": runner_module._AUTHORITY,
    }
    report["report_fingerprint"] = fingerprint(report)
    report_path = tmp_path / "final-report.json"
    report_path.write_text(canonical_json(report) + "\n")

    loaded = _read_final_report(report_path, source_commit=_SOURCE)
    _validate_final_evidence(tmp_path, loaded)
    database.write_bytes(b"changed")
    with pytest.raises(ValueError, match="runtime database differs"):
        _validate_final_evidence(tmp_path, loaded)
    database.write_bytes(b"database")
    freeze_path.write_bytes(freeze_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="final freeze differs"):
        _validate_final_evidence(tmp_path, loaded)


def _launch_review(repository: Path, equivalence: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": runner_module._LAUNCH_CONTROL_SCHEMA,
        "review_id": runner_module._LAUNCH_CONTROL_SCHEMA,
        "status": "passed",
        "verdict": "pass",
        "review_date": "2026-08-24",
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
            "program_state": {
                "path": STATE_RELATIVE_PATH.as_posix(),
                "sha256": STATE_SHA256,
                "fingerprint": STATE_FINGERPRINT,
            },
            "autonomous_program": {
                "path": AUTONOMOUS_PROGRAM_RELATIVE_PATH.as_posix(),
                "sha256": AUTONOMOUS_PROGRAM_SHA256,
                "fingerprint": AUTONOMOUS_PROGRAM_FINGERPRINT,
            },
            "autonomous_program_review": {
                "path": AUTONOMOUS_REVIEW_RELATIVE_PATH.as_posix(),
                "sha256": AUTONOMOUS_REVIEW_SHA256,
                "fingerprint": AUTONOMOUS_REVIEW_FINGERPRINT,
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
            "execution_cost_model": {
                "path": "config/research/intraday-execution-cost-model-001-v1.json",
                "sha256": "a9e6c2b86c6623d73e089de591c55eeec0711fa55f0933a4e3ea9a1c0c2392af",
                "fingerprint": "94fc3ba4663b422fbb0dc0cce7e3d78a7ba81f22d71d5fa986ab6847b7925bb4",
            },
            "execution_cost_review": {
                "path": (
                    "config/research/intraday-execution-cost-model-001-independent-review-v1.json"
                ),
                "sha256": "fb197856b9229349e5de4bca742f328a8f1e5e53f9558dfd7324744e91a795aa",
                "fingerprint": "8ade5190bb64330af037f88bf0911ed3cdb04578ca7a6d6e27a5fa6d651349b2",
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


def test_launch_control_binds_exact_files_equivalence_and_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for relative in runner_module._LAUNCH_CONTROL_FILES:
        source = _REPOSITORY / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    review = _launch_review(tmp_path, _parallel_equivalence(_REPOSITORY, source_commit=_SOURCE))
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
    path.write_bytes(raw + b"\n")
    with pytest.raises(ValueError, match="SHA-256 differs"):
        runner_module._load_launch_control(tmp_path, source_commit=_SOURCE)
