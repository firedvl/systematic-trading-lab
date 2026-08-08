"""Research-only, gate-based qualification evidence for intraday replay reports.

This module deliberately has no holdout, paper, broker, or daily-qualification authority.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from .experiments import ExperimentRegistry
from .fingerprints import canonical_json, canonicalize, fingerprint

POLICY_SCHEMA = "intraday-qualification-policy-v1"
REPORT_SCHEMA = "intraday-backtest-report-v1"
EVIDENCE_SCHEMA = "intraday-qualification-evidence-v1"
REVIEWED_POLICY_FINGERPRINT = "42481069d9d0295d40ff1ccc6c956632d852f58522040d01024d7798172fe127"
_STATUS_VALUES = frozenset({"pending", "running", "completed", "failed", "rejected"})
_REQUIRED_COST_STRESS_NAMES = ("increased-cost", "harsher-cost")
_REQUIRED_DELAY_STRESS_NAMES = ("plus-1-bar", "plus-2-bars")
_DELAY_STRESS_OFFSETS = {"plus-1-bar": 1, "plus-2-bars": 2}
_PROVENANCE_FIELDS = {
    "experiment_id",
    "campaign_id",
    "search_budget",
    "candidate_ordinal",
    "strategy_id",
    "strategy_version",
    "strategy_family",
    "code_commit",
    "dataset_id",
    "dataset_fingerprint",
    "universe_id",
    "universe_fingerprint",
    "parameters",
    "timeframe",
    "session_policy_version",
    "bar_timestamp_semantics_version",
    "session_return_policy_version",
    "benchmark_policy_version",
    "cost_model_version",
    "slippage_bps",
    "commission_bps",
    "execution_model_version",
    "earliest_fill_semantics",
    "execution_delay_bars",
    "split",
    "start_timestamp",
    "end_timestamp",
    "random_seed",
    "creation_reason",
    "parent_candidate",
    "schema_version",
}
_STABLE_LINEAGE_FIELDS = _PROVENANCE_FIELDS - {
    "experiment_id",
    "candidate_ordinal",
    "parameters",
    "cost_model_version",
    "slippage_bps",
    "commission_bps",
    "execution_model_version",
    "earliest_fill_semantics",
    "execution_delay_bars",
    "creation_reason",
    "parent_candidate",
}


@dataclass(frozen=True)
class IntradayGateSpec:
    name: str
    metric: str
    comparison: str
    threshold: Decimal
    rationale: str


@dataclass(frozen=True)
class IntradayQualificationPolicy:
    policy_id: str
    status: str
    purpose: str
    required_cost_stress_names: tuple[str, ...]
    required_delay_stress_names: tuple[str, ...]
    gates: tuple[IntradayGateSpec, ...]
    fingerprint: str


def load_intraday_qualification_policy(path: Path) -> IntradayQualificationPolicy:
    """Load the exact reviewed research policy; malformed policy fails closed."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load intraday qualification policy: {error}") from error
    root = _object(payload, "policy")
    _exact_fields(
        root,
        {
            "schema_version",
            "id",
            "status",
            "purpose",
            "required_cost_stress_names",
            "required_delay_stress_names",
            "gates",
        },
        "policy",
    )
    if _text(root["schema_version"], "policy schema version") != POLICY_SCHEMA:
        raise ValueError("unsupported intraday qualification policy schema")
    policy_id = _text(root["id"], "policy id")
    if policy_id != POLICY_SCHEMA:
        raise ValueError("intraday qualification policy ID must equal its schema version")
    if _text(root["status"], "policy status") != "reviewed-research-parameters":
        raise ValueError("intraday qualification policy must be reviewed research parameters")
    purpose = _text(root["purpose"], "policy purpose")
    if "not financial validation" not in purpose.lower():
        raise ValueError("policy purpose must state that it is not financial validation")
    cost_names = _names(root["required_cost_stress_names"], "required cost stress names")
    delay_names = _names(root["required_delay_stress_names"], "required delay stress names")
    if cost_names != _REQUIRED_COST_STRESS_NAMES:
        raise ValueError("intraday qualification policy cost stress roles differ")
    if delay_names != _REQUIRED_DELAY_STRESS_NAMES:
        raise ValueError("intraday qualification policy delay stress roles differ")
    gates_value = root["gates"]
    if not isinstance(gates_value, list) or not gates_value:
        raise ValueError("policy gates must be a nonempty list")
    gates = tuple(_gate(value, index) for index, value in enumerate(gates_value))
    if len({gate.name for gate in gates}) != len(gates) or len(
        {gate.metric for gate in gates}
    ) != len(gates):
        raise ValueError("policy gate names and metrics must be unique")
    return IntradayQualificationPolicy(
        policy_id,
        "reviewed-research-parameters",
        purpose,
        cost_names,
        delay_names,
        gates,
        fingerprint(root),
    )


def evaluate_intraday_qualification(
    policy: IntradayQualificationPolicy,
    base_report: Mapping[str, object],
    higher_cost_reports: Mapping[str, Mapping[str, object]],
    whole_bar_delay_reports: Mapping[str, Mapping[str, object]],
    parameter_neighbor_reports: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Evaluate unbound diagnostic inputs without claiming controlled evidence."""

    return _evaluate_intraday_qualification(
        policy,
        base_report,
        higher_cost_reports,
        whole_bar_delay_reports,
        parameter_neighbor_reports,
        (),
        False,
    )


def _evaluate_intraday_qualification(
    policy: IntradayQualificationPolicy,
    base_report: Mapping[str, object],
    higher_cost_reports: Mapping[str, Mapping[str, object]],
    whole_bar_delay_reports: Mapping[str, Mapping[str, object]],
    parameter_neighbor_reports: Mapping[str, Mapping[str, object]] | None,
    campaign_records: Sequence[Mapping[str, object]],
    registry_bound: bool,
) -> dict[str, object]:
    """Build deterministic research evidence from frozen intraday reports.

    Missing, failed, rejected, and lineage-invalid stress reports remain in the output and fail
    their relevant gates.  This function never ranks candidates or grants any authority.
    """
    base = _report(base_report, "base")
    costs = _named_reports(higher_cost_reports, "higher-cost")
    delays = _named_reports(whole_bar_delay_reports, "whole-bar-delay")
    neighbors = _named_reports(parameter_neighbor_reports or {}, "parameter-neighbor")
    sources = [base, *costs.values(), *delays.values(), *neighbors.values()]

    lineage_errors: dict[str, str] = {}
    source_provenance = [cast(Mapping[str, object], report["provenance"]) for report in sources]
    if len({item["experiment_id"] for item in source_provenance}) != len(source_provenance):
        lineage_errors["search-accounting"] = "source-experiment-ids-are-not-unique"
    elif len({item["candidate_ordinal"] for item in source_provenance}) != len(source_provenance):
        lineage_errors["search-accounting"] = "source-candidate-ordinals-are-not-unique"
    for name, report in costs.items():
        error = _variant_lineage(
            base, report, {"cost_model_version", "slippage_bps", "commission_bps"}
        )
        if error:
            lineage_errors[f"higher-cost:{name}"] = error
    for name, report in delays.items():
        error = _variant_lineage(
            base,
            report,
            {"execution_model_version", "earliest_fill_semantics", "execution_delay_bars"},
            expected_delay_offset=_DELAY_STRESS_OFFSETS.get(name),
        )
        if error:
            lineage_errors[f"whole-bar-delay:{name}"] = error
    for name, report in neighbors.items():
        error = _variant_lineage(base, report, {"parameters"})
        if error:
            lineage_errors[f"parameter-neighbor:{name}"] = error
    if all(name in costs for name in _REQUIRED_COST_STRESS_NAMES) and not any(
        f"higher-cost:{name}" in lineage_errors for name in _REQUIRED_COST_STRESS_NAMES
    ):
        increased = cast(Mapping[str, object], costs["increased-cost"]["provenance"])
        harsher = cast(Mapping[str, object], costs["harsher-cost"]["provenance"])
        if not _higher_cost(increased, harsher):
            lineage_errors["higher-cost:harsher-cost"] = (
                "harsher-cost-variant-is-not-higher-than-increased-cost"
            )

    metrics = _metrics(base, costs, delays, policy, lineage_errors)
    metrics["configuration_identity"] = Decimal(not lineage_errors)
    campaign_evidence = _campaign_evidence(campaign_records)
    metrics["registry_evidence_bound"] = Decimal(registry_bound)
    metrics["search_budget_accounted"] = Decimal(
        bool(campaign_evidence.get("search_budget_accounted"))
    )
    gate_results = [_gate_result(gate, metrics) for gate in policy.gates]
    evidence_sources = [_source(base)]
    evidence_sources.extend(
        _source(report, name, "higher-cost") for name, report in sorted(costs.items())
    )
    evidence_sources.extend(
        _missing_source(name, "higher-cost")
        for name in policy.required_cost_stress_names
        if name not in costs
    )
    evidence_sources.extend(
        _source(report, name, "whole-bar-delay") for name, report in sorted(delays.items())
    )
    evidence_sources.extend(
        _missing_source(name, "whole-bar-delay")
        for name in policy.required_delay_stress_names
        if name not in delays
    )
    evidence_sources.extend(
        _source(report, name, "parameter-neighbor") for name, report in sorted(neighbors.items())
    )
    payload: dict[str, object] = {
        "schema_version": EVIDENCE_SCHEMA,
        "policy": {
            "id": policy.policy_id,
            "status": policy.status,
            "fingerprint": policy.fingerprint,
            "purpose": policy.purpose,
        },
        "state": "research-gates-passed"
        if all(result["passed"] for result in gate_results)
        else "research-gates-failed",
        "candidate_id": cast(Mapping[str, object], base["provenance"])["experiment_id"],
        "base_report_fingerprint": base["fingerprint"],
        "metrics": canonicalize(metrics),
        "gates": gate_results,
        "sources": evidence_sources,
        "lineage_errors": dict(sorted(lineage_errors.items())),
        "search_accounting": campaign_evidence,
        "campaign_sources": campaign_evidence.get("records", []),
        "evidence_binding": "controlled-registry" if registry_bound else "unbound-diagnostic",
    }
    payload["report_fingerprint"] = fingerprint(payload)
    return payload


def evaluate_registered_intraday_qualification(
    registry: ExperimentRegistry,
    policy: IntradayQualificationPolicy,
    base_experiment_id: str,
    higher_cost_experiment_ids: Mapping[str, str],
    whole_bar_delay_experiment_ids: Mapping[str, str],
    parameter_neighbor_experiment_ids: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Bind every report and campaign status to immutable controlled-run registry evidence."""

    if policy.fingerprint != REVIEWED_POLICY_FINGERPRINT:
        raise ValueError("intraday assessment policy differs from the committed reviewed policy")
    base_record, base_report = _registered_report(registry, base_experiment_id)
    base_spec = cast(Mapping[str, object], base_record["spec_json"])
    campaign_id = _text(base_spec.get("campaign_id"), "base campaign ID")
    costs = {
        name: _registered_report(registry, experiment_id, campaign_id)[1]
        for name, experiment_id in higher_cost_experiment_ids.items()
    }
    delays = {
        name: _registered_report(registry, experiment_id, campaign_id)[1]
        for name, experiment_id in whole_bar_delay_experiment_ids.items()
    }
    neighbors = {
        name: _registered_report(registry, experiment_id, campaign_id)[1]
        for name, experiment_id in (parameter_neighbor_experiment_ids or {}).items()
    }
    campaign_records = registry.list(campaign_id)
    return _evaluate_intraday_qualification(
        policy,
        base_report,
        costs,
        delays,
        neighbors,
        campaign_records,
        True,
    )


def load_intraday_report(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load intraday report: {error}") from error
    return _object(value, "intraday report")


def write_intraday_qualification_evidence(directory: Path, evidence: Mapping[str, object]) -> Path:
    """Write one immutable, content-addressed research-only evidence artifact."""

    claimed = evidence.get("report_fingerprint")
    unsigned = dict(evidence)
    unsigned.pop("report_fingerprint", None)
    if not isinstance(claimed, str) or fingerprint(unsigned) != claimed:
        raise ValueError("intraday qualification evidence fingerprint is invalid")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{claimed}.json"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{claimed[:12]}-", dir=directory)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(canonical_json(evidence) + "\n", encoding="utf-8", newline="\n")
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.read_text(encoding="utf-8") != temporary.read_text(encoding="utf-8"):
                raise ValueError("existing intraday qualification evidence differs") from None
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _report(value: Mapping[str, object], label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} report must be a mapping")
    report = dict(value)
    if report.get("schema_version") != REPORT_SCHEMA:
        raise ValueError(f"{label} report must use {REPORT_SCHEMA}")
    required_report_fields = {
        "schema_version",
        "status",
        "provenance",
        "metrics",
        "report_fingerprint",
    }
    if not required_report_fields <= report.keys():
        raise ValueError(f"{label} report is missing qualification fields")
    status = _text(report["status"], f"{label} status")
    if status not in _STATUS_VALUES:
        raise ValueError(f"{label} status is unsupported")
    provenance = _object(report["provenance"], f"{label} provenance")
    if set(provenance) != _PROVENANCE_FIELDS:
        raise ValueError(f"{label} provenance fields differ")
    text_fields = _PROVENANCE_FIELDS - {
        "candidate_ordinal",
        "search_budget",
        "parameters",
        "execution_delay_bars",
        "random_seed",
        "parent_candidate",
    }
    for field in text_fields:
        _text(provenance[field], f"{label} provenance {field}")
    if (
        not isinstance(provenance["parameters"], Mapping)
        or not isinstance(provenance["search_budget"], int)
        or provenance["search_budget"] < 1
        or not isinstance(provenance["candidate_ordinal"], int)
        or not 1 <= provenance["candidate_ordinal"] <= provenance["search_budget"]
        or not isinstance(provenance["execution_delay_bars"], int)
        or provenance["execution_delay_bars"] < 1
        or (
            provenance["random_seed"] is not None
            and (
                isinstance(provenance["random_seed"], bool)
                or not isinstance(provenance["random_seed"], int)
            )
        )
        or not isinstance(provenance["parent_candidate"], str | None)
    ):
        raise ValueError(f"{label} provenance is invalid")
    metrics = _object(report["metrics"], f"{label} metrics")
    unsigned = dict(report)
    claimed = unsigned.pop("report_fingerprint")
    if not isinstance(claimed, str) or fingerprint(unsigned) != claimed:
        raise ValueError(f"{label} report fingerprint is invalid")
    return {
        "label": label,
        "status": status,
        "provenance": provenance,
        "metrics": metrics,
        "fingerprint": claimed,
    }


def _named_reports(
    value: Mapping[str, Mapping[str, object]], kind: str
) -> dict[str, dict[str, object]]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{kind} reports must be a mapping")
    result: dict[str, dict[str, object]] = {}
    for name, report in value.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{kind} report names must be nonempty strings")
        result[name] = _report(report, f"{kind}:{name}")
    return result


def _variant_lineage(
    base: Mapping[str, object],
    variant: Mapping[str, object],
    allowed: set[str],
    *,
    expected_delay_offset: int | None = None,
) -> str | None:
    base_provenance = cast(Mapping[str, object], base["provenance"])
    variant_provenance = cast(Mapping[str, object], variant["provenance"])
    if any(base_provenance[key] != variant_provenance[key] for key in _STABLE_LINEAGE_FIELDS):
        return "variant-provenance-differs-outside-allowed-fields"
    if variant_provenance["parent_candidate"] != base_provenance["experiment_id"]:
        return "variant-parent-does-not-match-base-experiment"
    metadata_fields = {"experiment_id", "candidate_ordinal", "creation_reason", "parent_candidate"}
    changed_assumptions = {
        key
        for key in _PROVENANCE_FIELDS - metadata_fields
        if base_provenance[key] != variant_provenance[key]
    }
    if not changed_assumptions or not changed_assumptions <= allowed:
        return "variant-changes-fields-outside-its-role"
    differences = changed_assumptions
    if allowed == {"cost_model_version", "slippage_bps", "commission_bps"} and (
        "cost_model_version" not in differences
        or not _higher_cost(base_provenance, variant_provenance)
    ):
        return "cost-variant-is-not-explicitly-higher-cost"
    if allowed == {
        "execution_model_version",
        "earliest_fill_semantics",
        "execution_delay_bars",
    }:
        if expected_delay_offset is None:
            return "delay-stress-role-is-unsupported"
        expected_delay = cast(int, base_provenance["execution_delay_bars"]) + expected_delay_offset
        if (
            "execution_delay_bars" not in differences
            or variant_provenance["execution_delay_bars"] != expected_delay
        ):
            return "delay-variant-does-not-match-required-whole-bar-offset"
    return None


def _higher_cost(base: Mapping[str, object], variant: Mapping[str, object]) -> bool:
    try:
        base_cost = Decimal(str(base["slippage_bps"])) + Decimal(str(base["commission_bps"]))
        variant_cost = Decimal(str(variant["slippage_bps"])) + Decimal(
            str(variant["commission_bps"])
        )
    except (InvalidOperation, ValueError):
        return False
    return base_cost.is_finite() and variant_cost.is_finite() and variant_cost > base_cost


def _metrics(
    base: Mapping[str, object],
    costs: Mapping[str, Mapping[str, object]],
    delays: Mapping[str, Mapping[str, object]],
    policy: IntradayQualificationPolicy,
    lineage_errors: Mapping[str, str],
) -> dict[str, Decimal | None]:
    base_metrics = cast(Mapping[str, object], base["metrics"])
    values: dict[str, Decimal | None] = {
        "base_report_completed": Decimal(base["status"] == "completed"),
        "completed_round_trips": _number(base_metrics, "completed_round_trip_count"),
        "session_count": _number(base_metrics, "sessions_in_range"),
        "active_session_count": _number(base_metrics, "sessions_traded"),
        "active_session_percentage": _number(base_metrics, "sessions_traded_percentage"),
        "max_drawdown": _number(base_metrics, "max_drawdown"),
        "best_trade_profit_share": _number(
            base_metrics, "best_trade_positive_profit_concentration"
        ),
        "best_session_profit_share": _number(
            base_metrics, "best_session_positive_profit_concentration"
        ),
        "best_n_trades_profit_share": _number(
            base_metrics, "best_5_trades_positive_profit_concentration"
        ),
        "symbol_profit_concentration": _number(
            base_metrics, "best_symbol_positive_profit_concentration"
        ),
        "no_overnight_positions": _zero_count(base_metrics, "overnight_position_count"),
        "no_outside_session_trades": _zero_count(base_metrics, "outside_session_fill_count"),
        "early_close_coverage": _positive_count(base_metrics, "early_close_session_count"),
    }
    values.update(
        _stress_metrics(
            base_metrics, costs, policy.required_cost_stress_names, "cost", lineage_errors
        )
    )
    values.update(
        _stress_metrics(
            base_metrics, delays, policy.required_delay_stress_names, "delay", lineage_errors
        )
    )
    return values


def _stress_metrics(
    base_metrics: Mapping[str, object],
    reports: Mapping[str, Mapping[str, object]],
    required_names: Sequence[str],
    kind: str,
    lineage_errors: Mapping[str, str],
) -> dict[str, Decimal | None]:
    required = [reports.get(name) for name in required_names]
    completed = all(
        report is not None
        and report["status"] == "completed"
        and f"{('higher-cost' if kind == 'cost' else 'whole-bar-delay')}:{name}"
        not in lineage_errors
        for name, report in zip(required_names, required, strict=True)
    )
    base_return = _number(base_metrics, "total_return")
    returns = [
        _number(cast(Mapping[str, object], report["metrics"]), "total_return")
        if report is not None
        else None
        for report in required
    ]
    retention: Decimal | None = None
    if (
        completed
        and base_return is not None
        and base_return > 0
        and all(value is not None for value in returns)
    ):
        retention = min(cast(Decimal, value) / base_return for value in returns)
    return {
        f"{kind}_stress_completed": Decimal(completed),
        f"{kind}_stress_return_retention": retention,
    }


def _gate_result(
    gate: IntradayGateSpec, metrics: Mapping[str, Decimal | None]
) -> dict[str, object]:
    observed = metrics.get(gate.metric)
    if observed is None:
        passed, reason = False, "metric-missing-or-invalid"
    elif gate.comparison == ">=":
        passed, reason = (
            observed >= gate.threshold,
            "passed" if observed >= gate.threshold else "below-threshold",
        )
    elif gate.comparison == "<=":
        passed, reason = (
            observed <= gate.threshold,
            "passed" if observed <= gate.threshold else "above-threshold",
        )
    else:
        passed, reason = (
            observed == gate.threshold,
            "passed" if observed == gate.threshold else "not-equal",
        )
    return {
        "name": gate.name,
        "metric": gate.metric,
        "observed": observed,
        "comparison": gate.comparison,
        "threshold": gate.threshold,
        "passed": passed,
        "reason": reason,
        "rationale": gate.rationale,
    }


def _source(
    report: Mapping[str, object], name: str = "base", role: str = "base"
) -> dict[str, object]:
    return {
        "role": role,
        "name": name,
        "status": report["status"],
        "source_fingerprint": report["fingerprint"],
    }


def _missing_source(name: str, role: str) -> dict[str, object]:
    return {"role": role, "name": name, "status": "missing", "source_fingerprint": None}


def _registered_report(
    registry: ExperimentRegistry,
    experiment_id: str,
    expected_campaign_id: str | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    record = registry.get(experiment_id)
    spec = record.get("spec_json")
    if not isinstance(spec, Mapping) or spec.get("schema_version") != "intraday-experiment-v1":
        raise ValueError(f"registered experiment is not an M5B candidate: {experiment_id}")
    if expected_campaign_id is not None and spec.get("campaign_id") != expected_campaign_id:
        raise ValueError("registered intraday evidence crosses campaigns")
    status = record.get("status")
    if status != "completed":
        if status not in _STATUS_VALUES:
            raise ValueError(f"registered intraday evidence status is invalid: {experiment_id}")
        unsigned_failure: dict[str, object] = {
            "schema_version": REPORT_SCHEMA,
            "status": status,
            "provenance": canonicalize(spec),
            "metrics": canonicalize(record.get("metrics_json") or {}),
            "registry_failure_info": record.get("failure_info"),
        }
        failed_report = {**unsigned_failure, "report_fingerprint": fingerprint(unsigned_failure)}
        return record, failed_report
    if record.get("execution_provenance") != "controlled-run":
        raise ValueError(f"intraday evidence is not a completed controlled run: {experiment_id}")
    locations = record.get("artifact_locations_json")
    hashes = record.get("artifact_hashes_json")
    if (
        not isinstance(locations, list)
        or len(locations) != 1
        or not isinstance(locations[0], str)
        or not isinstance(hashes, list)
        or len(hashes) != 1
        or not isinstance(hashes[0], str)
    ):
        raise ValueError("registered intraday evidence must bind exactly one report artifact")
    report = load_intraday_report(Path(locations[0]))
    validated = _report(report, experiment_id)
    if validated["fingerprint"] != hashes[0]:
        raise ValueError("registered intraday report fingerprint differs")
    provenance = cast(Mapping[str, object], validated["provenance"])
    if provenance.get("experiment_id") != experiment_id or canonicalize(provenance) != canonicalize(
        spec
    ):
        raise ValueError("registered intraday report provenance differs")
    if canonicalize(validated["metrics"]) != canonicalize(record.get("metrics_json")):
        raise ValueError("registered intraday report metrics differ")
    return record, report


def _campaign_evidence(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    summaries: list[dict[str, object]] = []
    budgets: set[int] = set()
    ordinals: list[int] = []
    intraday_only = bool(records)
    for record in records:
        spec = record.get("spec_json")
        if not isinstance(spec, Mapping) or spec.get("schema_version") not in {
            "intraday-candidate-reservation-v1",
            "intraday-experiment-v1",
        }:
            intraday_only = False
            ordinal = None
        else:
            ordinal = spec.get("candidate_ordinal")
            budget = spec.get("search_budget")
            if isinstance(ordinal, int) and not isinstance(ordinal, bool):
                ordinals.append(ordinal)
            else:
                intraday_only = False
            if isinstance(budget, int) and not isinstance(budget, bool):
                budgets.add(budget)
            else:
                intraday_only = False
        summaries.append(
            {
                "experiment_id": record.get("experiment_id"),
                "candidate_ordinal": ordinal,
                "status": record.get("status"),
                "failure_info": record.get("failure_info"),
                "qualification_state": record.get("qualification_state"),
                "execution_provenance": record.get("execution_provenance"),
                "artifact_fingerprints": record.get("artifact_hashes_json") or [],
            }
        )
    fixed_budget = next(iter(budgets)) if len(budgets) == 1 else None
    accounted = bool(
        intraday_only
        and fixed_budget is not None
        and len(records) == fixed_budget
        and sorted(ordinals) == list(range(1, fixed_budget + 1))
    )
    statuses = [str(record.get("status")) for record in records]
    summaries.sort(
        key=lambda item: (
            item["candidate_ordinal"] if isinstance(item["candidate_ordinal"], int) else 0,
            str(item["experiment_id"]),
        )
    )
    return {
        "fixed_search_budget": fixed_budget,
        "attempted_count": len(records),
        "completed_count": statuses.count("completed"),
        "failed_count": statuses.count("failed"),
        "rejected_count": statuses.count("rejected"),
        "pending_count": statuses.count("pending"),
        "running_count": statuses.count("running"),
        "search_budget_accounted": accounted,
        "records": summaries,
    }


def _gate(value: object, index: int) -> IntradayGateSpec:
    item = _object(value, f"gate {index}")
    _exact_fields(item, {"name", "metric", "comparison", "threshold", "rationale"}, f"gate {index}")
    try:
        threshold = Decimal(_text(item["threshold"], f"gate {index} threshold"))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"gate {index} threshold is invalid") from error
    if not threshold.is_finite() or _text(item["comparison"], f"gate {index} comparison") not in {
        ">=",
        "<=",
        "==",
    }:
        raise ValueError(f"gate {index} is invalid")
    return IntradayGateSpec(
        _text(item["name"], f"gate {index} name"),
        _text(item["metric"], f"gate {index} metric"),
        _text(item["comparison"], f"gate {index} comparison"),
        threshold,
        _text(item["rationale"], f"gate {index} rationale"),
    )


def _names(value: object, context: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError(f"{context} must be a nonempty unique string list")
    return tuple(value)


def _number(metrics: Mapping[str, object], name: str) -> Decimal | None:
    try:
        value = Decimal(str(metrics.get(name)))
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def _zero_count(metrics: Mapping[str, object], name: str) -> Decimal | None:
    value = _number(metrics, name)
    return Decimal(value == 0) if value is not None else None


def _positive_count(metrics: Mapping[str, object], name: str) -> Decimal | None:
    value = _number(metrics, name)
    return Decimal(value > 0) if value is not None else None


def _object(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be an object with string keys")
    return cast(dict[str, object], value)


def _exact_fields(value: Mapping[str, object], expected: set[str], context: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{context} fields differ")


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a nonempty string")
    return value
