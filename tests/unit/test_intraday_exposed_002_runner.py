from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

import systematic_trading_lab.intraday_exposed_002_runner as runner_module
from systematic_trading_lab.intraday_exposed_002_engine import Exposed002ReplayResult
from systematic_trading_lab.intraday_exposed_002_runner import (
    IntradayExposed002Store,
    _aggregate_reports,
    _gate_results,
    _run_id,
    _run_report,
    _select_with_caps,
    _source_commit,
    _write_create_only,
    intraday_exposed_002_plan_summary,
    intraday_exposed_002_status,
)

_REPOSITORY = Path(__file__).resolve().parents[2]


def _specification(candidate_id: str = "ie002-f01-a01-b01") -> dict[str, object]:
    return {
        "schema_version": "intraday-exposed-002-run-v1",
        "context": {
            "stage": "discovery",
            "base_candidate_id": None,
            "candidate_id": candidate_id,
            "family_id": "gap-down-failed-continuation-fade-v1",
            "period_id": "discovery-2025-07-through-10",
            "scenario_id": "normal",
        },
    }


def _report(
    *,
    total_return: str,
    net: str,
    gross: str,
    friction: str,
    profitable: str = "10",
    completed: int = 2,
    sessions: int = 2,
    spy_net: str = "1",
    qqq_net: str = "1",
) -> dict[str, object]:
    return {
        "metrics": {
            "total_return": total_return,
            "max_drawdown": "0.01",
            "completed_round_trips": completed,
            "session_count": sessions,
            "gross_profit_loss": gross,
            "gross_profitable_trade_profit": profitable,
            "execution_friction": friction,
            "net_profit_loss": net,
            "gross_trade_edge_bps_sum": "8",
            "holding_bars_sum": "6",
        },
        "details": {"symbol_net_profit_loss": {"SPY": spy_net, "QQQ": qqq_net}},
    }


def _selection_key(item: Mapping[str, object]) -> tuple[Decimal]:
    metrics = item["metrics"]
    assert isinstance(metrics, dict)
    value = metrics["return"]
    assert isinstance(value, Decimal)
    return (-value,)


def test_store_reserves_claims_completes_and_never_retries_failed(tmp_path: Path) -> None:
    store = IntradayExposed002Store(tmp_path)
    store.bind({"program_id": "intraday-exposed-002", "source_commit": "a" * 40})
    specification = _specification()
    run_id = _run_id(specification)

    store.reserve((specification,))
    store.reserve((specification,))
    assert store.claim(run_id) is True
    store.complete(run_id, "run-reports/a.json", "b" * 64, "c" * 64)
    assert store.claim(run_id) is False
    assert store.get(run_id)["status"] == "completed"

    failed_specification = _specification("ie002-f01-a01-b02")
    failed_run_id = _run_id(failed_specification)
    store.reserve((failed_specification,))
    assert store.claim(failed_run_id) is True
    store.fail(failed_run_id, RuntimeError("boom"))
    with pytest.raises(ValueError, match="terminal"):
        store.claim(failed_run_id)


def test_store_recovers_running_as_terminal_failure(tmp_path: Path) -> None:
    store = IntradayExposed002Store(tmp_path)
    specification = _specification()
    run_id = _run_id(specification)
    store.reserve((specification,))
    assert store.claim(run_id) is True

    assert store.recover_running() == (run_id,)
    assert store.get(run_id)["status"] == "failed"
    with pytest.raises(ValueError, match="terminal"):
        store.claim(run_id)


def test_gate_results_fail_closed_and_selection_respects_caps() -> None:
    gates = (
        {"metric": "return", "comparison": ">", "threshold": "0"},
        {"metric": "cost", "comparison": "<=", "threshold": "0.35"},
    )
    assert [item["passed"] for item in _gate_results(gates, {"return": Decimal("1")})] == [
        True,
        False,
    ]
    ledger: list[dict[str, object]] = []
    for index, (family, value) in enumerate((("a", "3"), ("a", "2"), ("b", "1")), 1):
        ledger.append(
            {
                "candidate": {
                    "candidate_id": f"ie002-f0{index}-a01-b01",
                    "family_id": family,
                },
                "metrics": {"return": Decimal(value)},
                "eligible": True,
            }
        )
    selected = _select_with_caps(
        ledger,
        global_cap=2,
        per_family_cap=1,
        key=_selection_key,
    )
    assert selected == ("ie002-f01-a01-b01", "ie002-f03-a01-b01")


def test_aggregate_metrics_recompute_accounting_and_symbol_concentration() -> None:
    aggregate = _aggregate_reports(
        (
            _report(total_return="0.01", net="8", gross="10", friction="2"),
            _report(
                total_return="-0.005",
                net="3",
                gross="4",
                friction="1",
                spy_net="2",
                qqq_net="1",
            ),
        )
    )

    assert aggregate["total_return"] == Decimal("0.005")
    assert aggregate["net_profit_loss"] == Decimal("11")
    assert aggregate["accounting_identity_error"] == Decimal("0E-12")
    assert aggregate["completed_round_trips"] == 4
    assert aggregate["positive_profit_symbol_concentration"] == Decimal("0.6")


def test_run_report_formula_uses_gross_minus_friction_equals_net() -> None:
    from systematic_trading_lab.backtesting import EquityPoint
    from systematic_trading_lab.domain import Symbol
    from systematic_trading_lab.intraday_execution_cost_model import DailyRegulatoryCharges
    from systematic_trading_lab.intraday_exposed_002_engine import (
        Exposed002DailyFees,
        Exposed002Fill,
        Exposed002RoundTrip,
    )
    from systematic_trading_lab.intraday_exposed_002_plan import Exposed002Period

    qqq = Symbol("QQQ")
    spy = Symbol("SPY")
    start = datetime(2026, 5, 1, 13, 30, tzinfo=UTC)
    end = datetime(2026, 5, 1, 19, 55, tzinfo=UTC)
    entry = datetime(2026, 5, 1, 13, 35, tzinfo=UTC)
    exit_time = datetime(2026, 5, 1, 19, 55, tzinfo=UTC)
    round_trip = Exposed002RoundTrip(
        "2026-05-01:SPY:1",
        spy,
        entry,
        exit_time,
        Decimal("10"),
        Decimal("100"),
        Decimal("101"),
        Decimal("100.1"),
        Decimal("100.9"),
    )
    fills = (
        Exposed002Fill(
            1,
            round_trip.trade_id,
            spy,
            start,
            entry,
            Decimal("10"),
            Decimal("100"),
            Decimal("100.1"),
            Decimal("1001"),
            Decimal("1"),
        ),
        Exposed002Fill(
            2,
            round_trip.trade_id,
            spy,
            end,
            exit_time,
            Decimal("-10"),
            Decimal("101"),
            Decimal("100.9"),
            Decimal("1009"),
            Decimal("1"),
        ),
    )
    fees = Exposed002DailyFees(
        "2026-05-01",
        DailyRegulatoryCharges(Decimal("0.5"), Decimal("0.3"), Decimal("0.2")),
        ((qqq, Decimal("0")), (spy, Decimal("1"))),
        "f" * 64,
    )
    result = Exposed002ReplayResult(
        "test",
        "1",
        "normal",
        Decimal("100000"),
        (),
        (),
        fills,
        (round_trip,),
        (fees,),
        (
            EquityPoint(
                end,
                Decimal("100007"),
                Decimal("100007"),
                ((qqq, Decimal("0")), (spy, Decimal("0"))),
            ),
        ),
        "e" * 64,
    )
    period = Exposed002Period("test", start, start, end, 1)

    report = _run_report(_specification(), result, period)
    metrics = report["metrics"]
    assert isinstance(metrics, dict)
    assert metrics["gross_profit_loss"] == Decimal("10")
    assert metrics["execution_friction"] == Decimal("3")
    assert metrics["net_profit_loss"] == Decimal("7")
    assert metrics["accounting_identity_error"] == Decimal("0E-12")


def test_plan_and_status_surface_grant_no_authority(tmp_path: Path) -> None:
    plan = intraday_exposed_002_plan_summary(_REPOSITORY)
    status = intraday_exposed_002_status(tmp_path)

    assert plan["parent_configuration_count"] == 60
    assert plan["june_status"] == "ineligible-no-read-no-substitute"
    plan_authority = plan["authority"]
    assert isinstance(plan_authority, Mapping)
    assert not any(plan_authority.values())
    assert status["database_exists"] is False
    status_authority = status["authority"]
    assert isinstance(status_authority, Mapping)
    assert not any(status_authority.values())


def test_create_only_rejects_changed_final_artifact(tmp_path: Path) -> None:
    destination = tmp_path / "final-freeze.json"
    _write_create_only(destination, {"a": 1})
    _write_create_only(destination, {"a": 1})

    with pytest.raises(FileExistsError, match="artifact differs"):
        _write_create_only(destination, {"a": 2})


def test_source_gate_rejects_dirty_or_unmerged_repository(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(("git", "init", "-b", "main"), cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(("git", "config", "user.email", "test@example.com"), cwd=tmp_path, check=True)
    subprocess.run(("git", "config", "user.name", "Test"), cwd=tmp_path, check=True)
    (tmp_path / "a").write_text("a")
    subprocess.run(("git", "add", "a"), cwd=tmp_path, check=True)
    subprocess.run(("git", "commit", "-m", "a"), cwd=tmp_path, check=True, capture_output=True)

    with pytest.raises(ValueError, match="source identity is unavailable"):
        _source_commit(tmp_path)


def test_runner_enforces_source_gate_before_data_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    accessed = False

    class _DataService:
        def describe(self, dataset_id: str) -> dict[str, object]:
            nonlocal accessed
            accessed = True
            raise AssertionError(dataset_id)

    def reject_source(_repository: Path) -> str:
        raise ValueError("source gate")

    monkeypatch.setattr(runner_module, "_source_commit", reject_source)

    with pytest.raises(ValueError, match="source gate"):
        runner_module.IntradayExposed002Runner(
            _REPOSITORY,
            tmp_path,
            data_service=_DataService(),  # type: ignore[arg-type]
        )
    assert accessed is False


def test_store_database_name_and_no_controlled_table(tmp_path: Path) -> None:
    store = IntradayExposed002Store(tmp_path)
    assert store.path.name == "intraday-exposed-002.sqlite3"
    with sqlite3.connect(store.path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert tables == {"program_binding", "runs"}
    assert not any("controlled" in value for value in tables)
