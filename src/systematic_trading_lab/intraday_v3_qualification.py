"""V3-only binding of unchanged intraday research qualification gates."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .experiments import ExperimentError, ExperimentRegistry
from .fingerprints import canonicalize, fingerprint
from .intraday_qualification import REVIEWED_POLICY_FINGERPRINT, IntradayQualificationPolicy

BINDING_SCHEMA = "intraday-v3-qualification-binding-v1"
REPORT_SCHEMA = "intraday-backtest-report-v2"
EVIDENCE_SCHEMA = "intraday-v3-qualification-evidence-v1"
_AUTHORITY = {
    "research_qualification": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}
_ROLES = ("base", "increased-cost", "harsher-cost", "plus-1-bar", "plus-2-bars")
_STRATEGIES = {
    "intraday-event-driven-ma-trend": ("intraday-trend", {"window": 12}),
    "intraday-30-minute-momentum": ("intraday-directional-momentum", {"lookback": 6}),
    "intraday-30-minute-opening-range-breakout": (
        "intraday-opening-range-breakout",
        {"opening_range_bars": 6},
    ),
}
_PERIODS = {
    "training": "training",
    "validation-a": "validation",
    "validation-b": "validation",
    "validation-c": "validation",
}
_METRICS = {
    "total_return",
    "cost_paid_total",
    "completed_round_trip_count",
    "sessions_in_range",
    "sessions_traded",
    "sessions_traded_percentage",
    "max_drawdown",
    "best_trade_positive_profit_concentration",
    "best_session_positive_profit_concentration",
    "best_5_trades_positive_profit_concentration",
    "best_symbol_positive_profit_concentration",
    "overnight_position_count",
    "outside_session_fill_count",
    "early_close_session_count",
}
_REQUIRED_INTEGRITY_FINGERPRINTS = (
    "configuration_provenance_fingerprint",
    "input_bars_fingerprint",
    "realistic_result_artifact_fingerprint",
    "zero_cost_result_artifact_fingerprint",
    "diagnostic_replay_fingerprint",
    "semantic_trace_fingerprint",
    "evidence_integrity_fingerprint",
    "report_fingerprint",
)


@dataclass(frozen=True)
class IntradayV3QualificationBinding:
    binding_id: str
    status: str
    purpose: str
    threshold_policy_id: str
    threshold_policy_fingerprint: str
    campaign_id: str
    experiment_schema: str
    report_schema: str
    evidence_schema: str
    metric_source: str
    zero_cost_is_diagnostic_only: bool
    required_variants: Mapping[str, Mapping[str, object]]
    execution_contract: Mapping[str, str]
    fixed_candidate_count: int
    required_report_integrity_fingerprints: tuple[str, ...]
    authorities: Mapping[str, bool]
    binding_fingerprint: str

    @property
    def fingerprint(self) -> str:
        return self.binding_fingerprint


def load_intraday_v3_qualification_binding(path: Path) -> IntradayV3QualificationBinding:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load V3 qualification binding: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("V3 qualification binding must be an object")
    expected = {
        "schema_version",
        "id",
        "status",
        "purpose",
        "threshold_policy_id",
        "threshold_policy_fingerprint",
        "campaign_id",
        "experiment_schema",
        "report_schema",
        "evidence_schema",
        "metric_source",
        "zero_cost_is_diagnostic_only",
        "required_variants",
        "execution_contract",
        "fixed_candidate_count",
        "required_report_integrity_fingerprints",
        "authorities",
        "binding_fingerprint",
    }
    if set(value) != expected:
        raise ValueError("V3 qualification binding fields differ")
    if (
        value["schema_version"] != BINDING_SCHEMA
        or value["id"] != BINDING_SCHEMA
        or value["status"] != "reviewed-research-binding"
    ):
        raise ValueError("unsupported V3 qualification binding")
    if (
        value["threshold_policy_id"] != "intraday-qualification-policy-v1"
        or value["threshold_policy_fingerprint"] != REVIEWED_POLICY_FINGERPRINT
    ):
        raise ValueError("V3 binding policy differs")
    if (
        value["campaign_id"] != "intraday-research-v3"
        or value["experiment_schema"] != "intraday-experiment-v2"
        or value["report_schema"] != REPORT_SCHEMA
        or value["evidence_schema"] != EVIDENCE_SCHEMA
        or value["metric_source"] != "realistic.metrics"
        or value["zero_cost_is_diagnostic_only"] is not True
        or value["fixed_candidate_count"] != 60
    ):
        raise ValueError("V3 binding identity differs")
    variants = value["required_variants"]
    if not isinstance(variants, dict) or tuple(variants) != _ROLES:
        raise ValueError("V3 variant roles differ")
    for role, variant in variants.items():
        if not isinstance(variant, dict) or set(variant) != {
            "cost_model_version",
            "slippage_bps",
            "commission_bps",
            "execution_delay_bars",
        }:
            raise ValueError(f"V3 variant {role} differs")
    if not isinstance(value["execution_contract"], dict) or set(value["execution_contract"]) != {
        "model",
        "earliest_fill_semantics",
        "queue_policy",
        "session_policy",
        "periodic_rebalance_policy",
        "diagnostic_policy",
    }:
        raise ValueError("V3 execution contract differs")
    if value["execution_contract"] != {
        "model": "state-transition-delayed-fifo-v1",
        "earliest_fill_semantics": "completed-bar-nth-later-open-v1",
        "queue_policy": "fifo-no-supersession-session-close-override-v1",
        "session_policy": "XNYS-regular-session-state-transition-flat-v2",
        "periodic_rebalance_policy": "none-v1",
        "diagnostic_policy": "paired-exact-zero-cost-counterfactual-v1",
    }:
        raise ValueError("V3 execution contract differs")
    integrity = value["required_report_integrity_fingerprints"]
    if not isinstance(integrity, list) or tuple(integrity) != _REQUIRED_INTEGRITY_FINGERPRINTS:
        raise ValueError("V3 report integrity fingerprints differ")
    if value["authorities"] != _AUTHORITY:
        raise ValueError("V3 authorities differ")
    unsigned = dict(value)
    claimed_fingerprint = unsigned.pop("binding_fingerprint")
    if not isinstance(claimed_fingerprint, str) or fingerprint(unsigned) != claimed_fingerprint:
        raise ValueError("V3 qualification binding fingerprint is invalid")
    return IntradayV3QualificationBinding(
        value["id"],
        value["status"],
        value["purpose"],
        value["threshold_policy_id"],
        value["threshold_policy_fingerprint"],
        value["campaign_id"],
        value["experiment_schema"],
        value["report_schema"],
        value["evidence_schema"],
        value["metric_source"],
        True,
        variants,
        value["execution_contract"],
        60,
        tuple(integrity),
        value["authorities"],
        claimed_fingerprint,
    )


def evaluate_v3_qualification(
    binding: IntradayV3QualificationBinding,
    policy: IntradayQualificationPolicy,
    base_report: Mapping[str, object],
    higher_cost_reports: Mapping[str, Mapping[str, object]],
    delay_reports: Mapping[str, Mapping[str, object]],
    campaign_records: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    if (
        policy.policy_id != binding.threshold_policy_id
        or policy.fingerprint != binding.threshold_policy_fingerprint
    ):
        raise ValueError("V3 qualification policy differs from binding")
    _exact_report_roles(higher_cost_reports, ("increased-cost", "harsher-cost"), "higher-cost")
    _exact_report_roles(delay_reports, ("plus-1-bar", "plus-2-bars"), "delay")
    reports = {
        "base": _report(base_report, binding, "base"),
        **{k: _report(v, binding, k) for k, v in higher_cost_reports.items()},
        **{k: _report(v, binding, k) for k, v in delay_reports.items()},
    }
    return _evaluate_normalized_v3_qualification(binding, policy, reports, campaign_records, False)


def _evaluate_normalized_v3_qualification(
    binding: IntradayV3QualificationBinding,
    policy: IntradayQualificationPolicy,
    reports: Mapping[str, Mapping[str, Any]],
    campaign_records: Sequence[Mapping[str, object]],
    registry_bound: bool,
) -> dict[str, object]:
    """Evaluate validated reports, including failed registry records without fake artifacts."""

    errors: dict[str, str] = {}
    base = reports["base"]
    source_provenance = [report["provenance"] for report in reports.values()]
    if len({item.get("experiment_id") for item in source_provenance}) != len(source_provenance):
        errors["search-accounting"] = "source-experiment-ids-are-not-unique"
    elif len({item.get("candidate_ordinal") for item in source_provenance}) != len(
        source_provenance
    ):
        errors["search-accounting"] = "source-candidate-ordinals-are-not-unique"
    for role in _ROLES:
        if role not in reports:
            errors[role] = "missing-required-variant"
            continue
        report = reports[role]
        provenance = report["provenance"]
        expected = binding.required_variants[role]
        if provenance.get("variant_role") != role:
            errors[role] = "variant-role-differs"
            continue
        if any(provenance.get(k) != v for k, v in expected.items()):
            errors[role] = "variant-contract-differs"
            continue
        if role == "base":
            if provenance.get("parent_candidate") is not None:
                errors[role] = "base-parent-must-be-null"
        else:
            if provenance.get("parent_candidate") != base["provenance"].get("experiment_id"):
                errors[role] = "variant-parent-does-not-match-base-experiment"
            stable = (
                "campaign_id",
                "search_budget",
                "strategy_id",
                "strategy_version",
                "strategy_family",
                "parameters",
                "period_role",
                "split",
                "start_timestamp",
                "end_timestamp",
                "timeframe",
                "dataset_id",
                "dataset_fingerprint",
                "universe_id",
                "universe_fingerprint",
                "code_commit",
                "source_foundation_commit",
                "qualification_binding_id",
                "qualification_binding_fingerprint",
                "campaign_plan_fingerprint",
                "execution_model_version",
                "earliest_fill_semantics",
                "decision_queue_policy_version",
                "session_policy_version",
                "bar_timestamp_semantics_version",
                "session_return_policy_version",
                "benchmark_policy_version",
                "periodic_rebalance_policy_version",
                "diagnostic_policy_version",
                "authority_policy_version",
                "random_seed",
            )
            if any(
                provenance.get(k) is None
                or base["provenance"].get(k) is None
                or provenance.get(k) != base["provenance"].get(k)
                for k in stable
            ):
                errors[role] = "variant-provenance-differs"
    if not _higher_cost(
        binding.required_variants["increased-cost"], binding.required_variants["harsher-cost"]
    ):
        errors["harsher-cost"] = "harsher-cost-is-not-higher-than-increased-cost"
    accounting = _accounting(
        campaign_records,
        binding,
        base["provenance"].get("campaign_plan_fingerprint"),
    )
    metrics = _gate_metrics(base, reports, errors, policy, registry_bound, accounting)
    gates = [_gate(policy_gate, metrics) for policy_gate in policy.gates]
    payload: dict[str, object] = {
        "schema_version": binding.evidence_schema,
        "binding": {"id": binding.binding_id, "fingerprint": binding.fingerprint},
        "policy": {"id": policy.policy_id, "fingerprint": policy.fingerprint},
        "state": "research-gates-passed"
        if all(g["passed"] for g in gates)
        else "research-gates-failed",
        "candidate_id": base["provenance"].get("experiment_id"),
        "base_report_fingerprint": base["fingerprint"],
        "metrics": canonicalize(metrics),
        "gates": gates,
        "sources": [_source(role, reports.get(role)) for role in _ROLES],
        "lineage_errors": dict(sorted(errors.items())),
        "search_accounting": accounting,
        "campaign_sources": accounting["records"],
        "evidence_binding": "controlled-registry" if registry_bound else "unbound-diagnostic",
        "authorities": dict(_AUTHORITY),
    }
    payload["report_fingerprint"] = fingerprint(payload)
    return payload


def evaluate_registered_v3_qualification(
    registry: ExperimentRegistry,
    binding: IntradayV3QualificationBinding,
    policy: IntradayQualificationPolicy,
    base_experiment_id: str,
    higher_cost_experiment_ids: Mapping[str, str],
    delay_experiment_ids: Mapping[str, str],
) -> dict[str, object]:
    if (
        policy.policy_id != binding.threshold_policy_id
        or policy.fingerprint != binding.threshold_policy_fingerprint
    ):
        raise ValueError("V3 qualification policy differs from binding")
    _exact_report_roles(
        higher_cost_experiment_ids, ("increased-cost", "harsher-cost"), "higher-cost"
    )
    _exact_report_roles(delay_experiment_ids, ("plus-1-bar", "plus-2-bars"), "delay")
    records = registry.list(binding.campaign_id)
    completed = _registered_campaign_evidence(registry, binding, records)
    selected = {
        "base": base_experiment_id,
        **higher_cost_experiment_ids,
        **delay_experiment_ids,
    }
    try:
        reports = {role: completed[experiment_id] for role, experiment_id in selected.items()}
    except KeyError as error:
        raise ValueError("registered V3 qualification source is not completed") from error
    return _evaluate_normalized_v3_qualification(binding, policy, reports, records, True)


def _exact_report_roles(
    reports: Mapping[str, object], expected: tuple[str, str], label: str
) -> None:
    if set(reports) != set(expected):
        raise ValueError(f"V3 {label} report roles differ")


def _report(
    value: Mapping[str, object], binding: IntradayV3QualificationBinding, label: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} report must be a mapping")
    r = dict(value)
    required = {
        "schema_version",
        "status",
        "provenance",
        "configuration_provenance_fingerprint",
        "input_bars_fingerprint",
        "input_bar_count",
        "strategy",
        "realistic",
        "zero_cost_counterfactual",
        "execution_contract",
        "decomposition_methodology",
        "diagnostic_replay_fingerprint",
        "semantic_trace_fingerprint",
        "authority",
        "qualification_metric_source",
        "evidence_integrity_fingerprint",
        "report_fingerprint",
    }
    allowed = required | {"execution_source_provenance"}
    if (
        (set(r) != required and set(r) != allowed)
        or r.get("schema_version") != REPORT_SCHEMA
        or r.get("status") != "completed-diagnostic-only"
    ):
        raise ValueError(f"{label} report schema or fields differ")
    unsigned = dict(r)
    claimed = unsigned.pop("report_fingerprint")
    if not isinstance(claimed, str) or fingerprint(unsigned) != claimed:
        raise ValueError(f"{label} report fingerprint is invalid")
    p = r["provenance"]
    if (
        not isinstance(p, Mapping)
        or p.get("schema_version") != binding.experiment_schema
        or p.get("campaign_id") != binding.campaign_id
    ):
        raise ValueError(f"{label} report provenance differs")
    if (
        r["configuration_provenance_fingerprint"] != fingerprint(p)
        or r["input_bars_fingerprint"] != p.get("dataset_fingerprint")
        or r["authority"] != _AUTHORITY
        or not isinstance(r["input_bar_count"], int)
        or isinstance(r["input_bar_count"], bool)
        or r["input_bar_count"] < 1
        or r["strategy"] != {"id": p.get("strategy_id"), "version": p.get("strategy_version")}
        or r["qualification_metric_source"]
        != (
            "realistic-cost metrics only, and only after a separate reviewed V3 "
            "qualification contract"
        )
    ):
        raise ValueError(f"{label} report provenance or authority differs")
    real = r["realistic"]
    zero = r["zero_cost_counterfactual"]
    if (
        not isinstance(real, Mapping)
        or set(real)
        != {
            "result_artifact_fingerprint",
            "cost_model_version",
            "net_return",
            "cost_paid_total",
            "metrics",
        }
        or not isinstance(real["metrics"], Mapping)
        or not set(real["metrics"]) >= _METRICS
        or not isinstance(real["result_artifact_fingerprint"], str)
        or real.get("cost_model_version") != p.get("cost_model_version")
        or _num(real, "net_return") != _num(real["metrics"], "total_return")
        or _num(real, "cost_paid_total") != _num(real["metrics"], "cost_paid_total")
    ):
        raise ValueError(f"{label} realistic evidence differs")
    if (
        not isinstance(zero, Mapping)
        or set(zero)
        != {
            "diagnostic_policy",
            "result_artifact_fingerprint",
            "cost_model_version",
            "return",
            "cost_paid_total",
            "semantic_trace_matches_realistic",
        }
        or zero.get("diagnostic_policy") != binding.execution_contract["diagnostic_policy"]
        or zero.get("cost_model_version") != "zero-cost-counterfactual-v1"
        or _num(zero, "cost_paid_total") != 0
        or zero.get("semantic_trace_matches_realistic") is not True
        or not isinstance(zero.get("result_artifact_fingerprint"), str)
    ):
        raise ValueError(f"{label} zero-cost diagnostic differs")
    if (
        not isinstance(r["execution_contract"], Mapping)
        or set(r["execution_contract"])
        != {
            "model",
            "earliest_fill_semantics",
            "queue_policy",
            "session_policy",
            "execution_delay_bars",
            "periodic_rebalance_policy",
            "initial_cash",
        }
        or any(
            r["execution_contract"].get(k) != v
            for k, v in binding.execution_contract.items()
            if k != "diagnostic_policy"
        )
        or r["execution_contract"].get("execution_delay_bars") != p.get("execution_delay_bars")
        or _num(r["execution_contract"], "initial_cash") != Decimal("100000")
    ):
        raise ValueError(f"{label} execution contract differs")
    integrity = {
        "configuration_provenance_fingerprint": r["configuration_provenance_fingerprint"],
        "input_bars_fingerprint": r["input_bars_fingerprint"],
        "realistic_result_artifact_fingerprint": real["result_artifact_fingerprint"],
        "zero_cost_result_artifact_fingerprint": zero.get("result_artifact_fingerprint"),
        "semantic_trace_fingerprint": r["semantic_trace_fingerprint"],
        "diagnostic_replay_fingerprint": r["diagnostic_replay_fingerprint"],
        "execution_contract": r["execution_contract"],
    }
    if r["evidence_integrity_fingerprint"] != fingerprint(integrity):
        raise ValueError(f"{label} evidence integrity fingerprint is invalid")
    return {
        "status": r["status"],
        "provenance": dict(p),
        "metrics": dict(real["metrics"]),
        "fingerprint": claimed,
    }


def _registered(
    registry: ExperimentRegistry,
    binding: IntradayV3QualificationBinding,
    experiment_id: str,
    campaign: object | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    record = registry.get(experiment_id)
    spec = record.get("spec_json")
    if (
        not isinstance(spec, Mapping)
        or spec.get("schema_version") != binding.experiment_schema
        or spec.get("campaign_id") != binding.campaign_id
        or campaign is not None
        and spec.get("campaign_id") != campaign
    ):
        raise ValueError("registered V3 evidence provenance differs")
    if record.get("status") != "completed":
        # A failed reservation is accounting evidence, not an execution report.  In
        # particular, never invent a V3 execution contract or diagnostic pair for it.
        return record, {
            "status": str(record.get("status")),
            "provenance": dict(spec),
            "metrics": {},
            "fingerprint": None,
        }
    if record.get("execution_provenance") != "controlled-run":
        raise ValueError("registered V3 evidence is not controlled-run")
    locations = record.get("artifact_locations_json")
    hashes = record.get("artifact_hashes_json")
    if (
        not isinstance(locations, list)
        or not isinstance(hashes, list)
        or len(locations) != 1
        or len(hashes) != 1
        or not isinstance(locations[0], str)
        or not isinstance(hashes[0], str)
    ):
        raise ValueError("registered V3 evidence must bind one report")
    try:
        raw = json.loads(Path(locations[0]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("registered V3 report cannot load") from error
    report = _report(raw, binding, experiment_id)
    if (
        report["fingerprint"] != hashes[0]
        or canonicalize(report["provenance"]) != canonicalize(spec)
        or canonicalize(report["metrics"]) != canonicalize(record.get("metrics_json"))
    ):
        raise ValueError("registered V3 report differs from record")
    evidence = raw.get("execution_source_provenance")
    if not isinstance(evidence, Mapping):
        raise ValueError("registered V3 report lacks execution source evidence")
    try:
        registry.verify_intraday_execution_source_evidence(experiment_id, evidence)
    except ExperimentError as error:
        raise ValueError("registered V3 execution source evidence differs") from error
    return record, report


def _registered_campaign_evidence(
    registry: ExperimentRegistry,
    binding: IntradayV3QualificationBinding,
    records: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    completed: dict[str, dict[str, object]] = {}
    seen: set[str] = set()
    for listed in records:
        experiment_id = listed.get("experiment_id")
        if not isinstance(experiment_id, str) or not experiment_id or experiment_id in seen:
            raise ValueError("registered V3 campaign experiment identity differs")
        seen.add(experiment_id)
        record, report = _registered(registry, binding, experiment_id, binding.campaign_id)
        if canonicalize(record) != canonicalize(listed):
            raise ValueError("registered V3 campaign record differs")
        if record.get("status") == "completed":
            completed[experiment_id] = report
        elif record.get("status") == "failed":
            failure = record.get("failure_info")
            if not isinstance(failure, str) or not failure.strip():
                raise ValueError("registered V3 failed candidate lacks a durable reason")
    return completed


def _gate_metrics(
    base: Mapping[str, Any],
    reports: Mapping[str, Mapping[str, Any]],
    errors: Mapping[str, str],
    policy: IntradayQualificationPolicy,
    bound: bool,
    accounting: Mapping[str, object],
) -> dict[str, Decimal | None]:
    m = base["metrics"]
    values = {
        "base_report_completed": Decimal(base["status"] == "completed-diagnostic-only"),
        "completed_round_trips": _num(m, "completed_round_trip_count"),
        "session_count": _num(m, "sessions_in_range"),
        "active_session_count": _num(m, "sessions_traded"),
        "active_session_percentage": _num(m, "sessions_traded_percentage"),
        "max_drawdown": _num(m, "max_drawdown"),
        "best_trade_profit_share": _num(m, "best_trade_positive_profit_concentration"),
        "best_session_profit_share": _num(m, "best_session_positive_profit_concentration"),
        "best_n_trades_profit_share": _num(m, "best_5_trades_positive_profit_concentration"),
        "symbol_profit_concentration": _num(m, "best_symbol_positive_profit_concentration"),
        "no_overnight_positions": _zero(m, "overnight_position_count"),
        "no_outside_session_trades": _zero(m, "outside_session_fill_count"),
        "early_close_coverage": _nonnegative(m, "early_close_session_count"),
        "configuration_identity": Decimal(not errors),
        "registry_evidence_bound": Decimal(bound),
        "search_budget_accounted": Decimal(bool(accounting["search_budget_accounted"])),
    }
    for kind, roles in (
        ("cost", ("increased-cost", "harsher-cost")),
        ("delay", ("plus-1-bar", "plus-2-bars")),
    ):
        complete = all(
            role in reports
            and reports[role]["status"] == "completed-diagnostic-only"
            and role not in errors
            for role in roles
        )
        returns = [
            _num(reports[r]["metrics"], "total_return") if r in reports else None for r in roles
        ]
        base_return = _num(m, "total_return")
        values[f"{kind}_stress_completed"] = Decimal(complete)
        values[f"{kind}_stress_return_retention"] = (
            min((x / base_return for x in returns if x is not None), default=None)
            if complete
            and base_return is not None
            and base_return > 0
            and all(x is not None for x in returns)
            else None
        )
    return values


def _accounting(
    records: Sequence[Mapping[str, object]],
    binding: IntradayV3QualificationBinding,
    expected_plan_fingerprint: object,
) -> dict[str, object]:
    summaries = []
    ordinals = []
    terminal = True
    schemas = True
    combinations: set[tuple[object, object, object]] = set()
    experiment_ids: set[str] = set()
    experiment_id_by_combination: dict[tuple[object, object, object], object] = {}
    parent_by_combination: dict[tuple[object, object, object], object] = {}
    period_identity: dict[object, tuple[object, ...]] = {}
    shared_identity: tuple[object, ...] | None = None
    plan_is_valid = _lower_hex(expected_plan_fingerprint, 64)
    for r in records:
        spec = r.get("spec_json")
        experiment_id = r.get("experiment_id")
        if isinstance(experiment_id, str) and experiment_id:
            experiment_ids.add(experiment_id)
        ordinal = spec.get("candidate_ordinal") if isinstance(spec, Mapping) else None
        if isinstance(ordinal, int) and not isinstance(ordinal, bool):
            ordinals.append(ordinal)
        strategy_id = spec.get("strategy_id") if isinstance(spec, Mapping) else None
        period_role = spec.get("period_role") if isinstance(spec, Mapping) else None
        variant_role = spec.get("variant_role") if isinstance(spec, Mapping) else None
        strategy = _STRATEGIES.get(strategy_id) if isinstance(strategy_id, str) else None
        split = _PERIODS.get(period_role) if isinstance(period_role, str) else None
        variant = (
            binding.required_variants.get(variant_role) if isinstance(variant_role, str) else None
        )
        schemas &= (
            isinstance(spec, Mapping)
            and spec.get("schema_version") == "intraday-experiment-v2"
            and spec.get("search_budget") == binding.fixed_candidate_count
            and spec.get("campaign_id") == binding.campaign_id
            and spec.get("qualification_binding_id") == binding.binding_id
            and spec.get("qualification_binding_fingerprint") == binding.fingerprint
            and plan_is_valid
            and spec.get("campaign_plan_fingerprint") == expected_plan_fingerprint
            and strategy is not None
            and spec.get("strategy_version") == "1"
            and spec.get("strategy_family") == (strategy or (None, None))[0]
            and spec.get("parameters") == (strategy or (None, None))[1]
            and split is not None
            and spec.get("split") == split
            and variant is not None
            and all(spec.get(key) == value for key, value in (variant or {}).items())
        )
        if isinstance(spec, Mapping):
            combination = (
                spec.get("strategy_id"),
                spec.get("period_role"),
                spec.get("variant_role"),
            )
            combinations.add(combination)
            experiment_id_by_combination[combination] = experiment_id
            parent_by_combination[combination] = spec.get("parent_candidate")
            observed_period = tuple(
                spec.get(key)
                for key in (
                    "start_timestamp",
                    "end_timestamp",
                    "dataset_id",
                    "dataset_fingerprint",
                    "universe_id",
                    "universe_fingerprint",
                    "timeframe",
                )
            )
            if period_role in period_identity and period_identity[period_role] != observed_period:
                schemas = False
            period_identity[period_role] = observed_period
            observed_shared = tuple(
                spec.get(key)
                for key in (
                    "code_commit",
                    "source_foundation_commit",
                    "campaign_plan_fingerprint",
                    "qualification_binding_id",
                    "qualification_binding_fingerprint",
                    "execution_model_version",
                    "earliest_fill_semantics",
                    "decision_queue_policy_version",
                    "session_policy_version",
                    "bar_timestamp_semantics_version",
                    "session_return_policy_version",
                    "benchmark_policy_version",
                    "periodic_rebalance_policy_version",
                    "diagnostic_policy_version",
                    "authority_policy_version",
                    "random_seed",
                )
            )
            if any(not isinstance(value, str) or not value for value in observed_period) or any(
                value is None for value in observed_shared
            ):
                schemas = False
            if shared_identity is not None and shared_identity != observed_shared:
                schemas = False
            shared_identity = observed_shared
        terminal &= r.get("status") in {"completed", "failed"}
        summaries.append(
            {
                "experiment_id": r.get("experiment_id"),
                "candidate_ordinal": ordinal,
                "status": r.get("status"),
                "failure_info": r.get("failure_info"),
            }
        )
    summaries.sort(
        key=lambda x: (
            x["candidate_ordinal"] if isinstance(x["candidate_ordinal"], int) else 0,
            str(x["experiment_id"]),
        )
    )
    expected_combinations = {
        (strategy, period, role)
        for strategy in _STRATEGIES
        for period in _PERIODS
        for role in _ROLES
    }
    parents_valid = combinations == expected_combinations and all(
        parent_by_combination.get((strategy, period, "base")) is None
        and all(
            parent_by_combination.get((strategy, period, role))
            == experiment_id_by_combination.get((strategy, period, "base"))
            for role in _ROLES[1:]
        )
        for strategy in _STRATEGIES
        for period in _PERIODS
    )
    periods_distinct = (
        schemas
        and len(period_identity) == len(_PERIODS)
        and len(set(period_identity.values())) == len(_PERIODS)
    )
    return {
        "fixed_search_budget": binding.fixed_candidate_count,
        "attempted_count": len(records),
        "completed_count": sum(r.get("status") == "completed" for r in records),
        "failed_count": sum(r.get("status") == "failed" for r in records),
        "pending_count": sum(r.get("status") == "pending" for r in records),
        "running_count": sum(r.get("status") == "running" for r in records),
        "search_budget_accounted": (
            schemas
            and terminal
            and len(records) == binding.fixed_candidate_count
            and sorted(ordinals) == list(range(1, binding.fixed_candidate_count + 1))
            and len(experiment_ids) == binding.fixed_candidate_count
            and combinations == expected_combinations
            and parents_valid
            and periods_distinct
        ),
        "records": summaries,
    }


def _lower_hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _gate(g: Any, metrics: Mapping[str, Decimal | None]) -> dict[str, object]:
    observed = metrics.get(g.metric)
    passed = observed is not None and (
        (g.comparison == ">=" and observed >= g.threshold)
        or (g.comparison == "<=" and observed <= g.threshold)
        or (g.comparison == "==" and observed == g.threshold)
    )
    return {
        "name": g.name,
        "metric": g.metric,
        "observed": observed,
        "comparison": g.comparison,
        "threshold": g.threshold,
        "passed": passed,
        "reason": "passed"
        if passed
        else "metric-missing-or-invalid"
        if observed is None
        else "threshold-not-met",
        "rationale": g.rationale,
    }


def _num(m: Mapping[str, object], key: str) -> Decimal | None:
    try:
        value = Decimal(str(m.get(key)))
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def _higher_cost(increased: Mapping[str, object], harsher: Mapping[str, object]) -> bool:
    increased_slippage = _num(increased, "slippage_bps")
    increased_commission = _num(increased, "commission_bps")
    harsher_slippage = _num(harsher, "slippage_bps")
    harsher_commission = _num(harsher, "commission_bps")
    if any(
        value is None
        for value in (
            increased_slippage,
            increased_commission,
            harsher_slippage,
            harsher_commission,
        )
    ):
        return False
    assert increased_slippage is not None
    assert increased_commission is not None
    assert harsher_slippage is not None
    assert harsher_commission is not None
    return harsher_slippage > increased_slippage and harsher_commission > increased_commission


def _zero(m: Mapping[str, object], key: str) -> Decimal | None:
    value = _num(m, key)
    return Decimal(value == 0) if value is not None else None


def _nonnegative(m: Mapping[str, object], key: str) -> Decimal | None:
    value = _num(m, key)
    return Decimal(value >= 0 and value == value.to_integral_value()) if value is not None else None


def _source(role: str, report: Mapping[str, Any] | None) -> dict[str, object]:
    return {
        "role": "base"
        if role == "base"
        else "higher-cost"
        if "cost" in role
        else "whole-bar-delay",
        "name": role,
        "status": "missing" if report is None else report["status"],
        "source_fingerprint": None if report is None else report["fingerprint"],
    }
