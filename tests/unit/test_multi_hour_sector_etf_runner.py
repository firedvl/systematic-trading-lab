from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from systematic_trading_lab.fingerprints import canonical_json, fingerprint
from systematic_trading_lab.multi_hour_sector_etf_runner import (
    DiscoveryBaseEvidence,
    Program002Metrics,
    SyntheticProgram002Runner,
    _run_id,
    aggregate_net_profit,
    aggregate_return,
    all_nine_and_neighbor_gates,
    campaign_2_permitted,
    controlled_block_gates,
    derive_campaign_specifications,
    derive_controlled_templates,
    derive_exposed_specifications,
    discovery_gates,
    final_fold_gates,
    fold_gates,
    metric_values,
    paired_controlled_block_gates,
    robustness_gates,
    select_discovery_base,
    validate_program_specification_ceiling,
)
from systematic_trading_lab.research_attempts import (
    AttemptStateError,
    PublicationConflictError,
    ResearchAttemptStore,
)
from systematic_trading_lab.research_executor import ResearchProcessError

_REPOSITORY = Path(__file__).resolve().parents[2]
_SOURCE = "c5fc2491cd978b0471cba9f2d2ca8190507f65f5"


def _metrics(
    *, profit: str = "100", benchmark: str = "0", denominator: str = "1000"
) -> Program002Metrics:
    return Program002Metrics(
        Decimal("1000"),
        Decimal("1000") + Decimal(profit),
        Decimal(benchmark),
        Decimal("50"),
        Decimal("10"),
        Decimal("1000"),
        Decimal(denominator),
        60,
        100,
        Decimal("0.05"),
        0,
        0,
        Decimal("0"),
        0,
        Decimal("0"),
        {"IWM": Decimal("25"), "MDY": Decimal("25"), "XLB": Decimal("25"), "XLE": Decimal("25")},
        {"broad": Decimal("34"), "sector": Decimal("33"), "sleeve": Decimal("33")},
        {"discovery": Decimal("50"), "later": Decimal("50")},
    )


def _publish_passing_report(
    runner: SyntheticProgram002Runner,
    specification: dict[str, object],
    *,
    metrics: Program002Metrics | None = None,
) -> None:
    report: dict[str, object] = {
        "specification": dict(specification),
        "gate_metrics": _metrics() if metrics is None else metrics,
        "authority": {
            "strategy_execution": False,
            "controlled_data_read": False,
            "research_qualification": False,
            "paper_execution": False,
            "broker_writes": False,
            "live_execution": False,
        },
    }
    report["report_fingerprint"] = fingerprint(
        {key: value for key, value in report.items() if key != "report_fingerprint"}
    )
    run_id = _run_id(specification)
    runner.store.reserve(run_id, specification)
    claim = runner.store.claim(run_id, source_sha=_SOURCE, started_at=datetime.now(UTC))
    runner.store.publish(
        claim,
        Path("synthetic-reports") / f"{run_id}.json",
        (canonical_json(report) + "\n").encode(),
        report_fingerprint=str(report["report_fingerprint"]),
        finished_at=datetime.now(UTC),
        exit_status=0,
    )


def test_exact_exposed_and_controlled_template_ceilings_and_false_authority() -> None:
    exposed = derive_exposed_specifications(_REPOSITORY, _SOURCE)
    controlled = derive_controlled_templates(_REPOSITORY, _SOURCE, "src-v1-l1-h4")

    assert len(exposed) == 228
    assert (
        len(
            derive_campaign_specifications(
                _REPOSITORY, _SOURCE, "sector-relative-continuation-v1", "src-v1-l1-h4"
            )
        )
        == 114
    )
    assert len(controlled) == 4
    assert {item["kind"] for item in controlled} == {"controlled-template"}
    assert all(
        isinstance(item["authority"], dict) and not any(item["authority"].values())
        for item in controlled
    )
    validate_program_specification_ceiling(exposed, controlled)
    with pytest.raises(ValueError, match="membership"):
        validate_program_specification_ceiling(exposed[:-1], controlled)


def test_metric_hand_calculation_and_undefined_denominators_fail_gates() -> None:
    metrics = _metrics()
    values = metric_values(metrics)

    assert values["period_return"] == Decimal("0.1")
    assert values["benchmark_excess_return"] == Decimal("0.1")
    assert values["gross_trade_edge_bps"] == Decimal("500")
    assert values["round_trip_friction_bps"] == Decimal("100")
    assert values["cost_to_gross_profitable_trade_profit"] == Decimal("0.01")
    assert aggregate_net_profit((metrics, _metrics(profit="20"))) == Decimal("120")
    assert aggregate_return((metrics, _metrics(profit="20"))) == Decimal("0.122")
    assert metric_values(_metrics(denominator="0"))["cost_to_gross_profitable_trade_profit"] is None
    assert not discovery_gates((_metrics(denominator="0"),) * 3, (_metrics(),) * 3)


def test_geometric_aggregate_rejects_positive_sum_with_negative_compounding() -> None:
    normal = (_metrics(profit="1000"), _metrics(profit="1000"), _metrics(profit="-800"))

    assert aggregate_net_profit(normal) == Decimal("1200")
    assert aggregate_return(normal) == Decimal("-0.2")
    assert not discovery_gates(normal, normal)


def test_discovery_base_selection_uses_only_frozen_lexicographic_order() -> None:
    selected = select_discovery_base(
        (
            DiscoveryBaseEvidence(
                "src-v1-l2-h4", True, Decimal("1"), Decimal("1"), Decimal("1"), Decimal("0.1")
            ),
            DiscoveryBaseEvidence(
                "src-v1-l1-h4", True, Decimal("1"), Decimal("1"), Decimal("1"), Decimal("0.1")
            ),
            DiscoveryBaseEvidence(
                "src-v1-l1-h8", False, Decimal("9"), Decimal("9"), Decimal("9"), Decimal("0")
            ),
        )
    )
    assert selected is not None and selected.configuration_id == "src-v1-l1-h4"


def test_every_gate_phase_and_campaign_succession_fail_closed() -> None:
    metrics = (_metrics(),) * 9
    zero = (_metrics(),) * 9
    assert discovery_gates(metrics[:3], zero[:3])
    assert fold_gates(metrics[:8], zero[:8])
    assert final_fold_gates(metrics[-1], zero[-1])
    assert all_nine_and_neighbor_gates(metrics, zero, (Decimal("500"), Decimal("500")))
    variants = {
        "stress-a-delay-2": metrics,
        "stress-b-delay-3": metrics,
        "normal-delay-2": metrics,
        "normal-delay-3": metrics,
    }
    assert robustness_gates(metrics, variants)
    assert not robustness_gates(
        metrics,
        {
            name: tuple(replace(item, benchmark_trace_mismatch_count=1) for item in value)
            for name, value in variants.items()
        },
    )
    assert controlled_block_gates(metrics[0])
    assert paired_controlled_block_gates(metrics[0], metrics[0])
    assert not paired_controlled_block_gates(
        metrics[0],
        replace(metrics[0], trace_mismatch_count=1),
    )
    assert campaign_2_permitted("completed-empty")
    assert campaign_2_permitted("completed-one-serious-family-candidate")
    assert not campaign_2_permitted("contamination")
    assert not campaign_2_permitted("unresolved-deterministic-control-failure")


def test_family_successor_templates_remain_disjoint() -> None:
    continuation = derive_campaign_specifications(
        _REPOSITORY, _SOURCE, "sector-relative-continuation-v1", "src-v1-l1-h4"
    )
    reversal = derive_campaign_specifications(
        _REPOSITORY, _SOURCE, "sector-relative-reversal-v1", "srr-v1-l1-h4"
    )

    assert {item["campaign_id"] for item in continuation}.isdisjoint(
        {item["campaign_id"] for item in reversal}
    )


def test_synthetic_runner_is_byte_equivalent_for_one_and_four_workers(tmp_path: Path) -> None:
    specifications = derive_campaign_specifications(
        _REPOSITORY, _SOURCE, "sector-relative-continuation-v1", "src-v1-l1-h4"
    )[:4]
    one = SyntheticProgram002Runner(_REPOSITORY, tmp_path / "one", _SOURCE, workers=1).run(
        specifications
    )
    four = SyntheticProgram002Runner(_REPOSITORY, tmp_path / "four", _SOURCE, workers=4).run(
        specifications
    )

    assert [item["specification_fingerprint"] for item in one] == [
        item["specification_fingerprint"] for item in four
    ]
    assert [item["report_fingerprint"] for item in one] == [
        item["report_fingerprint"] for item in four
    ]
    assert one[0]["selection_traces"]
    assert one[0]["candidate_ledger"]
    assert one[0]["benchmark_ledger"]
    metrics_value = one[0]["metrics"]
    assert isinstance(metrics_value, dict)
    assert metrics_value["accounting_identity_error"] == "0"


def test_stale_lease_retries_at_most_three_times_and_restart_reconciles(tmp_path: Path) -> None:
    specification = derive_campaign_specifications(
        _REPOSITORY, _SOURCE, "sector-relative-continuation-v1", "src-v1-l1-h4"
    )[0]
    store = ResearchAttemptStore(tmp_path, lease_timeout=timedelta(seconds=1))
    store.reserve("run", specification)
    started = datetime(2026, 1, 1, tzinfo=UTC)
    for attempt in range(3):
        store.claim("run", source_sha=_SOURCE, started_at=started + timedelta(seconds=attempt * 2))
        store.expire_stale(started + timedelta(seconds=attempt * 2 + 1))
    assert store.get("run")["status"] == "failed"
    with pytest.raises(AttemptStateError):
        store.claim("run", source_sha=_SOURCE, started_at=started + timedelta(seconds=8))


def test_runner_worker_death_restarts_after_expiry_and_conflict_is_terminal(tmp_path: Path) -> None:
    specification = derive_campaign_specifications(
        _REPOSITORY, _SOURCE, "sector-relative-continuation-v1", "src-v1-l1-h4"
    )[0]
    crashed = SyntheticProgram002Runner(
        _REPOSITORY, tmp_path / "crashed", _SOURCE, workers=1, crash_after_claim=True
    )
    with pytest.raises(ResearchProcessError, match="WorkerProcessExit"):
        crashed.run((specification,))
    crashed.store.expire_stale(datetime.now(UTC) + timedelta(minutes=6))
    restarted = SyntheticProgram002Runner(_REPOSITORY, tmp_path / "crashed", _SOURCE, workers=1)
    assert (
        restarted.run((specification,))[0]["result"]
        == "synthetic-fixture-contract-only-no-market-data"
    )

    conflict = SyntheticProgram002Runner(_REPOSITORY, tmp_path / "conflict", _SOURCE, workers=1)
    run_id = "p002r-" + fingerprint(specification)[:24]
    destination = tmp_path / "conflict" / "synthetic-reports" / f"{run_id}.json"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"conflict")
    with pytest.raises(ResearchProcessError, match="canonical report path differs"):
        conflict.run((specification,))


def test_discovery_selection_is_immutable_and_rejects_downstream_without_a_gate_pass(
    tmp_path: Path,
) -> None:
    selected_base = "src-v1-l1-h4"
    all_specs = derive_campaign_specifications(
        _REPOSITORY, _SOURCE, "sector-relative-continuation-v1", selected_base
    )
    discovery = tuple(item for item in all_specs if item["stage"] == "discovery")
    runner = SyntheticProgram002Runner(_REPOSITORY, tmp_path, _SOURCE, workers=4)
    runner.run(discovery)
    downstream = next(item for item in all_specs if item["stage"] == "folds-1-8")
    with pytest.raises(AttemptStateError, match="no immutable selected base"):
        runner.run((downstream,))

    selection = next((tmp_path / "selection-evidence").glob("*.json")).read_text()
    assert "zero-cost-delay-1" in selection
    assert 'selected_base_configuration_id":null' in selection
    stage = next((tmp_path / "stage-evidence").glob("*discovery.json")).read_text()
    assert '"gate_passed":false' in stage

    other = derive_campaign_specifications(
        _REPOSITORY, _SOURCE, "sector-relative-continuation-v1", "src-v1-l2-h4"
    )
    with pytest.raises(AttemptStateError, match="no immutable selected base"):
        runner.run((next(item for item in other if item["stage"] == "folds-1-8"),))

    evidence = next((tmp_path / "selection-evidence").glob("*.json"))
    evidence.write_bytes(b"tampered")
    with pytest.raises(PublicationConflictError, match="canonical report path differs"):
        SyntheticProgram002Runner(_REPOSITORY, tmp_path, _SOURCE, workers=1)


def test_selected_nonfirst_base_and_its_neighbors_reach_robustness_from_canonical_evidence(
    tmp_path: Path,
) -> None:
    base = "src-v1-l2-h4"
    specifications = derive_campaign_specifications(
        _REPOSITORY, _SOURCE, "sector-relative-continuation-v1", base
    )
    runner = SyntheticProgram002Runner(_REPOSITORY, tmp_path, _SOURCE, workers=1)
    for specification in specifications:
        configuration = specification["configuration"]
        assert isinstance(configuration, dict)
        stronger_discovery = (
            specification["stage"] == "discovery" and configuration["configuration_id"] == base
        )
        _publish_passing_report(
            runner,
            specification,
            metrics=_metrics(profit="200") if stronger_discovery else None,
        )

    discovery = tuple(item for item in specifications if item["stage"] == "discovery")
    folds = tuple(item for item in specifications if item["stage"] == "folds-1-8")
    final = tuple(item for item in specifications if item["stage"] == "final-fold-9")
    robustness = tuple(item for item in specifications if item["stage"] == "robustness")

    runner.run(discovery)
    runner.run(folds)
    runner.run(final)
    reports = runner.run(robustness)
    assert len(reports) == len(robustness)
    assert all(
        report["specification"] == specification
        for report, specification in zip(reports, robustness, strict=True)
    )

    stage = next((tmp_path / "stage-evidence").glob("*robustness.json")).read_text()
    assert '"gate_passed":true' in stage
    assert f'"base_configuration_id":"{base}"' in stage
