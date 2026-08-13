# mypy: disable-error-code="arg-type,attr-defined,index,no-untyped-call,no-untyped-def"

import json
from copy import deepcopy
from decimal import Decimal
from itertools import product
from pathlib import Path

import pytest

import systematic_trading_lab.intraday_v3_qualification as qualification
from systematic_trading_lab.datasets import intraday_fixture_request, intraday_fixture_symbols
from systematic_trading_lab.domain import OHLCVBar, Timeframe
from systematic_trading_lab.experiments import ExperimentSplit
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.intraday_qualification import load_intraday_qualification_policy
from systematic_trading_lab.intraday_v3 import (
    V3_AUTHORITY_POLICY,
    V3_DIAGNOSTIC_POLICY,
    V3_EARLIEST_FILL_SEMANTICS,
    V3_EXECUTION_MODEL,
    V3_MOMENTUM_STRATEGY_ID,
    V3_PERIODIC_REBALANCE_POLICY,
    V3_QUEUE_POLICY,
    V3_SESSION_POLICY,
    IntradayV3ExperimentSpec,
    build_v3_diagnostic_report,
    run_v3_diagnostic,
)
from systematic_trading_lab.intraday_v3_qualification import (
    evaluate_registered_v3_qualification,
    evaluate_v3_qualification,
    load_intraday_v3_qualification_binding,
)
from systematic_trading_lab.providers import IntradayFixtureProvider

_BINDING_PATH = Path("config/research/intraday-v3-qualification-binding-v1.json")
_POLICY_PATH = Path("config/research/intraday-qualification-policy-v1.json")
_PLAN_PATH = Path("config/research/intraday-campaign-v3.json")
_PLAN = json.loads(_PLAN_PATH.read_text(encoding="utf-8"))
_PLAN_FINGERPRINT = _PLAN["plan_fingerprint"]
_AUTHORITY = {
    "research_qualification": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}
_STRATEGIES = (
    ("intraday-event-driven-ma-trend", "intraday-trend", {"window": 12}),
    ("intraday-30-minute-momentum", "intraday-directional-momentum", {"lookback": 6}),
    (
        "intraday-30-minute-opening-range-breakout",
        "intraday-opening-range-breakout",
        {"opening_range_bars": 6},
    ),
)
_PERIODS = (
    (
        "validation-a",
        "validation",
        "2026-10-01T13:30:00+00:00",
        "2026-12-03T20:55:00+00:00",
    ),
    ("training", "training", "2025-07-01T13:30:00+00:00", "2026-06-30T19:55:00+00:00"),
    (
        "validation-b",
        "validation",
        "2026-12-04T14:30:00+00:00",
        "2027-02-09T20:55:00+00:00",
    ),
    (
        "validation-c",
        "validation",
        "2027-02-10T14:30:00+00:00",
        "2027-04-15T19:55:00+00:00",
    ),
)
_PERIOD_FINGERPRINTS = {
    "validation-a": "a" * 64,
    "training": "b" * 64,
    "validation-b": "c" * 64,
    "validation-c": "d" * 64,
}
_SEALED_BASE_ID = "intraday-research-v3-event-driven-ma-trend-validation-a-base"


def _binding_and_policy():
    binding = load_intraday_v3_qualification_binding(_BINDING_PATH)
    return binding, load_intraday_qualification_policy(_POLICY_PATH)


def _metrics() -> dict[str, str]:
    return {
        "total_return": "0.10",
        "cost_paid_total": "1.00",
        "completed_round_trip_count": "20",
        "sessions_in_range": "20",
        "sessions_traded": "5",
        "sessions_traded_percentage": "0.25",
        "max_drawdown": "0.20",
        "best_trade_positive_profit_concentration": "0.50",
        "best_session_positive_profit_concentration": "0.50",
        "best_5_trades_positive_profit_concentration": "0.50",
        "best_symbol_positive_profit_concentration": "0.75",
        "overnight_position_count": "0",
        "outside_session_fill_count": "0",
        "early_close_session_count": "1",
    }


def _report(role: str, ordinal: int, base_id: str = "v3-base") -> dict[str, object]:
    binding, _ = _binding_and_policy()
    variant = binding.required_variants[role]
    provenance = {
        "schema_version": binding.experiment_schema,
        "experiment_id": base_id if role == "base" else f"v3-{role}",
        "campaign_id": binding.campaign_id,
        "candidate_ordinal": ordinal,
        "search_budget": 60,
        "strategy_id": "intraday-event-driven-ma-trend",
        "strategy_version": "1",
        "strategy_family": "intraday-trend",
        "period_role": "validation-a",
        "split": "validation",
        "dataset_id": "dataset-v3-validation-a",
        "dataset_fingerprint": _PERIOD_FINGERPRINTS["validation-a"],
        "universe_id": "liquid-etfs-intraday-5m-v1",
        "universe_fingerprint": "e" * 64,
        "code_commit": "b" * 40,
        "source_foundation_commit": "d03be5eaa1e5d2d360424a6c0d06c1ce0bc6a723",
        "qualification_binding_id": binding.binding_id,
        "qualification_binding_fingerprint": binding.fingerprint,
        "campaign_plan_fingerprint": _PLAN_FINGERPRINT,
        "execution_model_version": binding.execution_contract["model"],
        "earliest_fill_semantics": binding.execution_contract["earliest_fill_semantics"],
        "decision_queue_policy_version": binding.execution_contract["queue_policy"],
        "session_policy_version": binding.execution_contract["session_policy"],
        "periodic_rebalance_policy_version": binding.execution_contract[
            "periodic_rebalance_policy"
        ],
        "diagnostic_policy_version": binding.execution_contract["diagnostic_policy"],
        "parameters": {"window": 12},
        "timeframe": "5m",
        "bar_timestamp_semantics_version": "bar-open-utc-v1",
        "session_return_policy_version": "XNYS-session-close-equity-v1",
        "benchmark_policy_version": "cash-and-continuous-underlying-v1",
        "authority_policy_version": "research-diagnostic-no-authority-v1",
        "start_timestamp": _PERIODS[0][2],
        "end_timestamp": _PERIODS[0][3],
        "random_seed": 0,
        "variant_role": role,
        "cost_model_version": variant["cost_model_version"],
        "slippage_bps": variant["slippage_bps"],
        "commission_bps": variant["commission_bps"],
        "execution_delay_bars": variant["execution_delay_bars"],
        "parent_candidate": None if role == "base" else base_id,
    }
    realistic = {
        "result_artifact_fingerprint": f"realistic-{role}",
        "cost_model_version": variant["cost_model_version"],
        "net_return": "0.10",
        "cost_paid_total": "1.00",
        "metrics": _metrics(),
    }
    zero = {
        "diagnostic_policy": binding.execution_contract["diagnostic_policy"],
        "result_artifact_fingerprint": f"zero-{role}",
        "cost_model_version": "zero-cost-counterfactual-v1",
        "return": "0.11",
        "cost_paid_total": "0",
        "semantic_trace_matches_realistic": True,
    }
    contract = {
        **{
            key: value
            for key, value in binding.execution_contract.items()
            if key != "diagnostic_policy"
        },
        "execution_delay_bars": variant["execution_delay_bars"],
        "initial_cash": "100000",
    }
    integrity = {
        "configuration_provenance_fingerprint": fingerprint(provenance),
        "input_bars_fingerprint": provenance["dataset_fingerprint"],
        "realistic_result_artifact_fingerprint": realistic["result_artifact_fingerprint"],
        "zero_cost_result_artifact_fingerprint": zero["result_artifact_fingerprint"],
        "semantic_trace_fingerprint": f"trace-{role}",
        "diagnostic_replay_fingerprint": f"replay-{role}",
        "execution_contract": contract,
    }
    raw: dict[str, object] = {
        "schema_version": "intraday-backtest-report-v2",
        "status": "completed-diagnostic-only",
        "provenance": provenance,
        "input_bar_count": 100,
        "strategy": {"id": provenance["strategy_id"], "version": provenance["strategy_version"]},
        "realistic": realistic,
        "zero_cost_counterfactual": zero,
        "execution_contract": contract,
        "configuration_provenance_fingerprint": integrity["configuration_provenance_fingerprint"],
        "input_bars_fingerprint": integrity["input_bars_fingerprint"],
        "diagnostic_replay_fingerprint": integrity["diagnostic_replay_fingerprint"],
        "semantic_trace_fingerprint": integrity["semantic_trace_fingerprint"],
        "decomposition_methodology": "paired replay",
        "qualification_metric_source": (
            "realistic-cost metrics only, and only after a separate reviewed V3 "
            "qualification contract"
        ),
        "evidence_integrity_fingerprint": fingerprint(integrity),
        "authority": _AUTHORITY,
    }
    return {**raw, "report_fingerprint": fingerprint(raw)}


def _records(statuses: dict[int, str] | None = None) -> list[dict[str, object]]:
    binding, _ = _binding_and_policy()
    candidates = list(product(_STRATEGIES, _PERIODS, binding.required_variants))
    base_ids = {
        (strategy[0], period[0]): f"candidate-{ordinal}"
        for ordinal, (strategy, period, role) in enumerate(candidates, start=1)
        if role == "base"
    }
    records: list[dict[str, object]] = []
    for ordinal, (strategy, period, role) in enumerate(candidates, start=1):
        period_role = period[0]
        records.append(
            {
                "experiment_id": f"candidate-{ordinal}",
                "status": (statuses or {}).get(ordinal, "completed"),
                "failure_info": (
                    "controlled failure" if (statuses or {}).get(ordinal) == "failed" else None
                ),
                "spec_json": {
                    "schema_version": binding.experiment_schema,
                    "campaign_id": binding.campaign_id,
                    "search_budget": 60,
                    "candidate_ordinal": ordinal,
                    "qualification_binding_id": binding.binding_id,
                    "qualification_binding_fingerprint": binding.fingerprint,
                    "campaign_plan_fingerprint": _PLAN_FINGERPRINT,
                    "strategy_id": strategy[0],
                    "strategy_family": strategy[1],
                    "strategy_version": "1",
                    "parameters": strategy[2],
                    "period_role": period_role,
                    "split": period[1],
                    "start_timestamp": period[2],
                    "end_timestamp": period[3],
                    "dataset_id": f"dataset-v3-{period_role}",
                    "dataset_fingerprint": _PERIOD_FINGERPRINTS[period_role],
                    "universe_id": "liquid-etfs-intraday-5m-v1",
                    "universe_fingerprint": "e" * 64,
                    "timeframe": "5m",
                    "code_commit": "b" * 40,
                    "source_foundation_commit": "d03be5eaa1e5d2d360424a6c0d06c1ce0bc6a723",
                    "execution_model_version": binding.execution_contract["model"],
                    "earliest_fill_semantics": binding.execution_contract[
                        "earliest_fill_semantics"
                    ],
                    "decision_queue_policy_version": binding.execution_contract["queue_policy"],
                    "session_policy_version": binding.execution_contract["session_policy"],
                    "bar_timestamp_semantics_version": "bar-open-utc-v1",
                    "session_return_policy_version": "XNYS-session-close-equity-v1",
                    "benchmark_policy_version": "cash-and-continuous-underlying-v1",
                    "periodic_rebalance_policy_version": binding.execution_contract[
                        "periodic_rebalance_policy"
                    ],
                    "diagnostic_policy_version": binding.execution_contract["diagnostic_policy"],
                    "authority_policy_version": "research-diagnostic-no-authority-v1",
                    "random_seed": 0,
                    "variant_role": role,
                    "parent_candidate": (
                        None if role == "base" else base_ids[(strategy[0], period_role)]
                    ),
                    **binding.required_variants[role],
                },
            }
        )
    return records


def _evaluate(reports: dict[str, dict[str, object]], records=None) -> dict[str, object]:
    binding, policy = _binding_and_policy()
    return evaluate_v3_qualification(
        binding,
        policy,
        reports["base"],
        {key: reports[key] for key in ("increased-cost", "harsher-cost")},
        {key: reports[key] for key in ("plus-1-bar", "plus-2-bars")},
        _records() if records is None else records,
    )


def _reports() -> dict[str, dict[str, object]]:
    return {
        role: _report(role, index + 1)
        for index, role in enumerate(
            ("base", "increased-cost", "harsher-cost", "plus-1-bar", "plus-2-bars")
        )
    }


def _sealed_group_reports() -> dict[str, dict[str, object]]:
    reports = _reports()
    identifiers = {
        "base": _SEALED_BASE_ID,
        "increased-cost": "intraday-research-v3-event-driven-ma-trend-validation-a-increased-cost",
        "harsher-cost": "intraday-research-v3-event-driven-ma-trend-validation-a-harsher-cost",
        "plus-1-bar": "intraday-research-v3-event-driven-ma-trend-validation-a-plus-1-bar",
        "plus-2-bars": "intraday-research-v3-event-driven-ma-trend-validation-a-plus-2-bars",
    }
    for role, report in reports.items():
        report["provenance"]["experiment_id"] = identifiers[role]
        report["provenance"]["parent_candidate"] = None if role == "base" else identifiers["base"]
        reports[role] = _rebind(report)
    return reports


def test_v3_qualification_binding_is_deterministic() -> None:
    first, _ = _binding_and_policy()
    assert first == load_intraday_v3_qualification_binding(_BINDING_PATH)
    assert first.threshold_policy_fingerprint == (
        "42481069d9d0295d40ff1ccc6c956632d852f58522040d01024d7798172fe127"
    )
    assert first.authorities == _AUTHORITY


def test_builder_report_reaches_v3_qualification_report_boundary() -> None:
    bars = tuple(
        OHLCVBar.from_record(record)
        for record in IntradayFixtureProvider().fetch(
            intraday_fixture_symbols(), Timeframe.FIVE_MINUTES, intraday_fixture_request()
        )
    )
    timestamps = sorted({bar.timestamp for bar in bars})
    spec = IntradayV3ExperimentSpec(
        experiment_id="v3-diagnostic",
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
                for bar in sorted(bars, key=lambda bar: (bar.symbol.value, bar.timestamp))
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
    binding, _ = _binding_and_policy()
    report = build_v3_diagnostic_report(spec, run_v3_diagnostic(spec, bars), bars)
    parsed = qualification._report(report, binding, "builder")
    assert parsed["status"] == "completed-diagnostic-only"
    assert parsed["metrics"] == report["realistic"]["metrics"]


def test_v3_uses_realistic_metrics_and_never_grants_authority() -> None:
    reports = _reports()
    reports["base"]["realistic"]["metrics"]["completed_round_trip_count"] = "0"
    reports["base"] = _resign(reports["base"])
    evidence = _evaluate(reports)
    gate = next(gate for gate in evidence["gates"] if gate["metric"] == "completed_round_trips")
    assert gate["passed"] is False
    assert evidence["authorities"] == _AUTHORITY
    assert evidence["state"] == "research-gates-failed"


def test_v3_rejects_zero_cost_gate_metric_injection() -> None:
    reports = _reports()
    reports["base"]["zero_cost_counterfactual"]["metrics"] = _metrics()
    reports["base"] = _resign(reports["base"])

    with pytest.raises(ValueError, match="zero-cost diagnostic differs"):
        _evaluate(reports)


@pytest.mark.parametrize(
    ("cost_roles", "delay_roles"),
    [
        (("increased-cost",), ("plus-1-bar", "plus-2-bars")),
        (("increased-cost", "harsher-cost", "caller-added"), ("plus-1-bar", "plus-2-bars")),
        (("increased-cost", "harsher-cost"), ("plus-1-bar",)),
        (("increased-cost", "harsher-cost"), ("plus-1-bar", "plus-2-bars", "caller-added")),
    ],
)
def test_v3_rejects_missing_or_extra_report_roles(
    cost_roles: tuple[str, ...], delay_roles: tuple[str, ...]
) -> None:
    reports = _reports()
    binding, policy = _binding_and_policy()
    costs = {role: reports.get(role, reports["base"]) for role in cost_roles}
    delays = {role: reports.get(role, reports["base"]) for role in delay_roles}
    with pytest.raises(ValueError, match="report roles differ"):
        evaluate_v3_qualification(binding, policy, reports["base"], costs, delays, _records())


@pytest.mark.parametrize(
    ("role", "field", "value", "error"),
    [
        ("increased-cost", "dataset_fingerprint", "forged", "variant-provenance-differs"),
        ("harsher-cost", "campaign_id", "other", "variant-provenance-differs"),
        (
            "plus-1-bar",
            "parent_candidate",
            "other-base",
            "variant-parent-does-not-match-base-experiment",
        ),
        ("plus-2-bars", "execution_delay_bars", 2, "variant-contract-differs"),
    ],
)
def test_v3_rejects_exact_stress_lineage_drift(
    role: str, field: str, value: object, error: str
) -> None:
    reports = _reports()
    reports[role]["provenance"][field] = value
    if field == "execution_delay_bars":
        reports[role]["execution_contract"]["execution_delay_bars"] = value
    reports[role] = _rebind(reports[role])
    if field in {"dataset_fingerprint", "campaign_id"}:
        with pytest.raises(ValueError, match="provenance"):
            _evaluate(reports)
        return
    evidence = _evaluate(reports)
    assert evidence["lineage_errors"][role] == error


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("parameters", {"window": 13}),
        ("start_timestamp", "2026-07-02T13:30:00+00:00"),
    ],
)
def test_v3_rejects_fixed_parameter_or_period_lineage_drift(field: str, value: object) -> None:
    reports = _reports()
    reports["increased-cost"]["provenance"][field] = value
    reports["increased-cost"] = _rebind(reports["increased-cost"])

    evidence = _evaluate(reports)

    assert evidence["lineage_errors"]["increased-cost"] == "variant-provenance-differs"


def test_v3_requires_exact_60_candidate_accounting_including_failures() -> None:
    evidence = _evaluate(_reports(), _records({60: "failed"}))
    accounting = evidence["search_accounting"]
    assert accounting["attempted_count"] == 60
    assert accounting["failed_count"] == 1
    assert accounting["search_budget_accounted"] is True
    assert accounting["records"][-1]["status"] == "failed"
    incomplete = _evaluate(_reports(), _records()[:-1])["search_accounting"]
    assert incomplete["search_budget_accounted"] is False


def test_v3_rejects_hidden_parameter_neighbor_and_duplicate_matrix_combination() -> None:
    records = _records()
    records[59]["spec_json"]["parameters"] = {"window": 13}
    assert _evaluate(_reports(), records)["search_accounting"]["search_budget_accounted"] is False

    records = _records()
    records[59]["spec_json"]["strategy_id"] = records[0]["spec_json"]["strategy_id"]
    records[59]["spec_json"]["parameters"] = records[0]["spec_json"]["parameters"]
    records[59]["spec_json"]["period_role"] = records[0]["spec_json"]["period_role"]
    records[59]["spec_json"]["split"] = records[0]["spec_json"]["split"]
    records[59]["spec_json"]["variant_role"] = records[0]["spec_json"]["variant_role"]
    records[59]["spec_json"].update(_binding_and_policy()[0].required_variants["base"])
    assert _evaluate(_reports(), records)["search_accounting"]["search_budget_accounted"] is False


def test_v3_rejects_campaign_plan_parent_period_and_candidate_identity_drift() -> None:
    records = _records()
    records[1]["spec_json"]["campaign_plan_fingerprint"] = "f" * 64
    assert _evaluate(_reports(), records)["search_accounting"]["search_budget_accounted"] is False

    records = _records()
    records[1]["spec_json"]["parent_candidate"] = "wrong-base"
    assert _evaluate(_reports(), records)["search_accounting"]["search_budget_accounted"] is False

    records = _records()
    records[1]["spec_json"]["dataset_fingerprint"] = "f" * 64
    assert _evaluate(_reports(), records)["search_accounting"]["search_budget_accounted"] is False

    records = _records()
    records[1]["experiment_id"] = records[0]["experiment_id"]
    assert _evaluate(_reports(), records)["search_accounting"]["search_budget_accounted"] is False


def test_v3_rejects_duplicate_source_candidate_identity() -> None:
    reports = _reports()
    reports["plus-2-bars"]["provenance"]["candidate_ordinal"] = 4
    reports["plus-2-bars"] = _rebind(reports["plus-2-bars"])

    evidence = _evaluate(reports)

    assert evidence["lineage_errors"]["search-accounting"] == (
        "source-candidate-ordinals-are-not-unique"
    )


def test_v3_rejects_v1_report_and_forged_integrity() -> None:
    reports = _reports()
    reports["base"]["schema_version"] = "intraday-backtest-report-v1"
    with pytest.raises(ValueError, match="schema"):
        _evaluate(reports)

    reports = _reports()
    reports["base"]["semantic_trace_fingerprint"] = "forged-trace"
    reports["base"] = _resign(reports["base"])
    with pytest.raises(ValueError, match="integrity"):
        _evaluate(reports)


class _Registry:
    def __init__(self, records):
        self.records = records
        self.plan = deepcopy(_PLAN)

    def get(self, experiment_id: str):
        return next(record for record in self.records if record["experiment_id"] == experiment_id)

    def list(self, campaign_id: str):
        return self.records

    def get_campaign_plan(self, campaign_id: str):
        assert campaign_id == "intraday-research-v3"
        return self.plan

    def verify_intraday_execution_source_evidence(self, experiment_id: str, evidence: object):
        return None


def _bind_registered_reports(
    tmp_path: Path,
    records: list[dict[str, object]],
    reports: dict[str, dict[str, object]],
    *,
    source_bound: bool,
) -> None:
    for index, (role, report) in enumerate(reports.items()):
        if source_bound:
            report["execution_source_provenance"] = {"review": {}, "binding": {}}
            reports[role] = _resign(report)
        path = tmp_path / f"{role}.json"
        path.write_text(json.dumps(reports[role]), encoding="utf-8")
        record = records[index]
        record["experiment_id"] = reports[role]["provenance"]["experiment_id"]
        record["spec_json"] = reports[role]["provenance"]
        record["artifact_locations_json"] = [str(path)]
        record["artifact_hashes_json"] = [reports[role]["report_fingerprint"]]
        record["metrics_json"] = reports[role]["realistic"]["metrics"]
        record["execution_provenance"] = "controlled-run"


def test_registered_v3_rejects_missing_source_binding_and_keeps_failed_visible(
    tmp_path: Path,
) -> None:
    reports = _reports()
    records = _records({ordinal: "failed" for ordinal in range(6, 61)})
    _bind_registered_reports(tmp_path, records, reports, source_bound=False)

    binding, policy = _binding_and_policy()
    with pytest.raises(ValueError, match="lacks execution source evidence"):
        evaluate_registered_v3_qualification(
            _Registry(records),
            binding,
            policy,
            _SEALED_BASE_ID,
        )


def test_registered_v3_passing_gates_keep_all_authorities_false(tmp_path: Path) -> None:
    reports = _sealed_group_reports()
    records = _records({ordinal: "failed" for ordinal in range(6, 61)})
    _bind_registered_reports(tmp_path, records, reports, source_bound=True)

    binding, policy = _binding_and_policy()
    evidence = evaluate_registered_v3_qualification(
        _Registry(records),
        binding,
        policy,
        _SEALED_BASE_ID,
    )
    assert evidence["state"] == "research-gates-passed"
    assert evidence["evidence_binding"] == "controlled-registry"
    assert evidence["authorities"] == _AUTHORITY
    assert len(evidence["campaign_sources"]) == 60
    assert evidence["campaign_evidence_fingerprint"] == fingerprint(evidence["campaign_sources"])
    assert all(
        "report_fingerprint" in source
        if source["status"] == "completed"
        else "record_identity_fingerprint" in source
        for source in evidence["campaign_sources"]
    )


def test_registered_v3_rejects_publication_integrity_conflict(tmp_path: Path) -> None:
    reports = _sealed_group_reports()
    records = _records({ordinal: "failed" for ordinal in range(6, 61)})
    _bind_registered_reports(tmp_path, records, reports, source_bound=True)
    records[0]["publication_integrity_conflict"] = {
        "schema_version": "intraday-v3-publication-integrity-conflict-v1"
    }
    binding, policy = _binding_and_policy()

    with pytest.raises(ValueError, match="publication integrity conflict"):
        evaluate_registered_v3_qualification(_Registry(records), binding, policy, _SEALED_BASE_ID)


def test_registered_v3_derives_exact_sealed_group_and_binds_mutations(tmp_path: Path) -> None:
    reports = _sealed_group_reports()
    records = _records({ordinal: "failed" for ordinal in range(6, 61)})
    _bind_registered_reports(tmp_path, records, reports, source_bound=True)
    binding, policy = _binding_and_policy()
    registry = _Registry(records)
    evidence = evaluate_registered_v3_qualification(registry, binding, policy, _SEALED_BASE_ID)

    with pytest.raises(ValueError, match="qualification group differs"):
        evaluate_registered_v3_qualification(registry, binding, policy, "candidate-substitution")

    path = Path(records[0]["artifact_locations_json"][0])
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["realistic"]["metrics"]["total_return"] = "0.99"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="fingerprint"):
        evaluate_registered_v3_qualification(registry, binding, policy, _SEALED_BASE_ID)

    reports = _sealed_group_reports()
    records = _records({ordinal: "failed" for ordinal in range(6, 61)})
    _bind_registered_reports(tmp_path, records, reports, source_bound=True)
    changed = evaluate_registered_v3_qualification(
        _Registry(records), binding, policy, _SEALED_BASE_ID
    )
    records[5]["failure_info"] = "different durable reason"
    changed_reason = evaluate_registered_v3_qualification(
        _Registry(records), binding, policy, _SEALED_BASE_ID
    )
    assert (
        evidence["campaign_evidence_fingerprint"] != changed_reason["campaign_evidence_fingerprint"]
    )
    assert (
        changed["campaign_evidence_fingerprint"] != changed_reason["campaign_evidence_fingerprint"]
    )


def test_registered_v3_rejects_stored_plan_role_substitution(tmp_path: Path) -> None:
    reports = _sealed_group_reports()
    records = _records({ordinal: "failed" for ordinal in range(6, 61)})
    _bind_registered_reports(tmp_path, records, reports, source_bound=True)
    binding, policy = _binding_and_policy()
    registry = _Registry(records)
    registry.plan["qualification_groups"][1]["roles"]["increased-cost"] = "substituted"

    with pytest.raises(ValueError):
        evaluate_registered_v3_qualification(registry, binding, policy, _SEALED_BASE_ID)


def test_registered_v3_rejects_unselected_completed_candidate_without_evidence(
    tmp_path: Path,
) -> None:
    reports = _sealed_group_reports()
    records = _records({ordinal: "failed" for ordinal in range(7, 61)})
    _bind_registered_reports(tmp_path, records, reports, source_bound=True)
    records[5]["execution_provenance"] = "controlled-run"
    binding, policy = _binding_and_policy()

    with pytest.raises(ValueError, match="must bind one report"):
        evaluate_registered_v3_qualification(
            _Registry(records),
            binding,
            policy,
            _SEALED_BASE_ID,
        )


def test_registered_v3_rejects_failed_candidate_without_durable_reason(tmp_path: Path) -> None:
    reports = _sealed_group_reports()
    records = _records({ordinal: "failed" for ordinal in range(6, 61)})
    records[5]["failure_info"] = None
    _bind_registered_reports(tmp_path, records, reports, source_bound=True)
    binding, policy = _binding_and_policy()

    with pytest.raises(ValueError, match="lacks a durable reason"):
        evaluate_registered_v3_qualification(
            _Registry(records),
            binding,
            policy,
            _SEALED_BASE_ID,
        )


def _resign(report: dict[str, object]) -> dict[str, object]:
    result = deepcopy(report)
    result.pop("report_fingerprint")
    result["report_fingerprint"] = fingerprint(result)
    return result


def _rebind(report: dict[str, object]) -> dict[str, object]:
    """Rebuild report-level hashes to isolate lineage checks from tamper checks."""
    result = deepcopy(report)
    provenance = result["provenance"]
    realistic = result["realistic"]
    zero = result["zero_cost_counterfactual"]
    contract = result["execution_contract"]
    result["configuration_provenance_fingerprint"] = fingerprint(provenance)
    integrity = {
        "configuration_provenance_fingerprint": result["configuration_provenance_fingerprint"],
        "input_bars_fingerprint": result["input_bars_fingerprint"],
        "realistic_result_artifact_fingerprint": realistic["result_artifact_fingerprint"],
        "zero_cost_result_artifact_fingerprint": zero["result_artifact_fingerprint"],
        "semantic_trace_fingerprint": result["semantic_trace_fingerprint"],
        "diagnostic_replay_fingerprint": result["diagnostic_replay_fingerprint"],
        "execution_contract": contract,
    }
    result["evidence_integrity_fingerprint"] = fingerprint(integrity)
    return _resign(result)
