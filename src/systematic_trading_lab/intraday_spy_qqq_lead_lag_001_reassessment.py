"""Read-only reassessment of the immutable Campaign 1 discovery evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

from .fingerprints import canonical_json, canonicalize, fingerprint
from .intraday_spy_qqq_lead_lag_001_plan import (
    PLAN_FINGERPRINT,
    PLAN_RELATIVE_PATH,
    PLAN_SHA256,
    PROGRAM_ID,
    STATE_FINGERPRINT,
    STATE_RELATIVE_PATH,
    STATE_SHA256,
    load_intraday_spy_qqq_lead_lag_001_plan,
)

ASSESSMENT_SCHEMA = "intraday-spy-qqq-lead-lag-001-post-campaign-reassessment-v1"
ASSESSMENT_RELATIVE_PATH = Path(
    "docs/research-campaigns/intraday-spy-qqq-lead-lag-001-post-campaign-reassessment-v1.json"
)
LAUNCH_CONTROL_RELATIVE_PATH = Path(
    "config/research/intraday-spy-qqq-lead-lag-001-launch-control-review-v1.json"
)
DATABASE_NAME = "intraday-spy-qqq-lead-lag-001.sqlite3"
FINAL_REPORT_NAME = "final-report.json"
FINAL_FREEZE_NAME = "final-freeze.json"
DISCOVERY_PERIOD_ID = "discovery-2025-07-through-10"
RUNTIME_SOURCE_COMMIT = "a8093f24fba142c2817311bbd3c30656b981b15c"
LAUNCH_CONTROL_SHA256 = "26d1ef10abb3b2ef063dec1bc5931b0c667c2698bc983c7c9e3a3e58ca01e863"
LAUNCH_CONTROL_FINGERPRINT = "b69466bfe3ed67d8e539a6e772341f2fbb7a7bddcdefa4bcee04e336c73c446e"
RUNTIME_DATABASE_SHA256 = "fca67d95832a6fad87f29ef68ce56238a0f9d8d2e02e8d331aece63e4e9e8908"
FINAL_REPORT_SHA256 = "d44f9390db7f8882f7375afbfd40607ce51d89d6a7537431e01c9cfd9b6b6608"
FINAL_REPORT_FINGERPRINT = "0c05593ab04da12774c066b361c2f44de4db0a103d4c3f78bb3edd0763e82dc0"
FINAL_FREEZE_SHA256 = "62c2301cde8e72d80f39159b3d38da156e92801afdd70e554356b806cac37d2c"
FINAL_FREEZE_FINGERPRINT = "d958ff60712fc60acb04942327fd3930331aa0ce482119a726d19a44cdcf98cf"
_ACCOUNTING_PRECISION = Decimal("0.000000000001")
_AUTHORITY = {
    "research_qualification": False,
    "controlled_evaluation": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}
_PROTECTED_ACCESS = {
    "june_market_data_or_results": False,
    "intraday_v3_data_or_results": False,
    "daily_2018_2019_data_or_results": False,
    "paper_broker_or_live_state": False,
    "strategic_allocation_21": False,
}
_ASSESSOR_FILES = (
    "src/systematic_trading_lab/intraday_spy_qqq_lead_lag_001_reassessment.py",
    "tests/unit/test_intraday_spy_qqq_lead_lag_001_reassessment.py",
)


@dataclass(frozen=True)
class ReassessmentEvidence:
    database_sha256: str = RUNTIME_DATABASE_SHA256
    final_report_sha256: str = FINAL_REPORT_SHA256
    final_report_fingerprint: str = FINAL_REPORT_FINGERPRINT
    final_freeze_sha256: str = FINAL_FREEZE_SHA256
    final_freeze_fingerprint: str = FINAL_FREEZE_FINGERPRINT
    runtime_source_commit: str = RUNTIME_SOURCE_COMMIT


_DEFAULT_EVIDENCE = ReassessmentEvidence()


def assess_intraday_spy_qqq_lead_lag_001(
    repository: Path,
    data_home: Path,
    *,
    evidence: ReassessmentEvidence = _DEFAULT_EVIDENCE,
) -> dict[str, object]:
    """Recompute discovery screening without reading market data or mutating runtime evidence."""
    repository = repository.resolve()
    runtime = data_home.resolve() / PROGRAM_ID
    database = runtime / DATABASE_NAME
    final_report_path = runtime / FINAL_REPORT_NAME
    final_freeze_path = runtime / FINAL_FREEZE_NAME
    for suffix in ("-journal", "-shm", "-wal"):
        if Path(f"{database}{suffix}").exists():
            raise ValueError(f"Campaign 1 reassessment rejects SQLite sidecar: {suffix}")

    source_hashes = {
        path: _sha256(repository / path)
        for path in _ASSESSOR_FILES
        if (repository / path).is_file()
    }
    if set(source_hashes) != set(_ASSESSOR_FILES):
        raise ValueError("Campaign 1 reassessment source surface is incomplete")

    input_hashes = _input_hashes(repository, database, final_report_path, final_freeze_path)
    expected_hashes = {
        "runtime_database": evidence.database_sha256,
        "final_report": evidence.final_report_sha256,
        "final_freeze": evidence.final_freeze_sha256,
        "plan": PLAN_SHA256,
        "launch_control": LAUNCH_CONTROL_SHA256,
        "previous_state": STATE_SHA256,
    }
    if input_hashes != expected_hashes:
        raise ValueError("Campaign 1 reassessment input hash differs")

    plan = load_intraday_spy_qqq_lead_lag_001_plan(repository)
    gates = _discovery_gates(plan.payload)
    final_report = _fingerprinted_json(
        final_report_path,
        "report_fingerprint",
        evidence.final_report_fingerprint,
        "final report",
    )
    final_freeze = _fingerprinted_json(
        final_freeze_path,
        "freeze_fingerprint",
        evidence.final_freeze_fingerprint,
        "final freeze",
    )
    launch_control = _fingerprinted_json(
        repository / LAUNCH_CONTROL_RELATIVE_PATH,
        "review_fingerprint",
        LAUNCH_CONTROL_FINGERPRINT,
        "launch control",
    )
    previous_state = _fingerprinted_json(
        repository / STATE_RELATIVE_PATH,
        "state_fingerprint",
        STATE_FINGERPRINT,
        "previous state",
    )
    _validate_boundaries(
        final_report,
        final_freeze,
        launch_control,
        previous_state,
        evidence,
    )

    reports, runtime_accounting = _load_runtime_reports(
        database,
        runtime,
        final_freeze,
        plan.configurations,
        evidence.runtime_source_commit,
    )
    recomputed = _recompute_discovery(reports, plan.configurations, gates)
    _validate_original_screening_defect(final_freeze, recomputed)
    _validate_empty_downstream(final_report, final_freeze, recomputed)

    after_hashes = _input_hashes(repository, database, final_report_path, final_freeze_path)
    if after_hashes != input_hashes:
        raise ValueError("Campaign 1 reassessment input changed during assessment")

    payload: dict[str, object] = {
        "schema_version": ASSESSMENT_SCHEMA,
        "assessment_id": ASSESSMENT_SCHEMA,
        "status": "passed-invariant-empty-disposition-after-semantic-defect",
        "assessment_date": "2026-08-24",
        "program_id": PROGRAM_ID,
        "method": (
            "Read-only exact-byte validation and gate recomputation from the 18 immutable "
            "canonical discovery reports; no strategy rerun or market-data read."
        ),
        "assessor_source": [
            {"path": path, "sha256": source_hashes[path]} for path in _ASSESSOR_FILES
        ],
        "historical_evidence": {
            "runtime_source_commit": evidence.runtime_source_commit,
            "runtime_database": {
                "path": DATABASE_NAME,
                "sha256": evidence.database_sha256,
            },
            "final_report": {
                "path": FINAL_REPORT_NAME,
                "sha256": evidence.final_report_sha256,
                "fingerprint": evidence.final_report_fingerprint,
            },
            "final_freeze": {
                "path": FINAL_FREEZE_NAME,
                "sha256": evidence.final_freeze_sha256,
                "fingerprint": evidence.final_freeze_fingerprint,
            },
            "plan": {
                "path": PLAN_RELATIVE_PATH.as_posix(),
                "sha256": PLAN_SHA256,
                "fingerprint": PLAN_FINGERPRINT,
            },
            "launch_control": {
                "path": LAUNCH_CONTROL_RELATIVE_PATH.as_posix(),
                "sha256": LAUNCH_CONTROL_SHA256,
                "fingerprint": LAUNCH_CONTROL_FINGERPRINT,
            },
            "previous_state": {
                "path": STATE_RELATIVE_PATH.as_posix(),
                "sha256": STATE_SHA256,
                "fingerprint": STATE_FINGERPRINT,
                "state_revision": 2,
            },
        },
        "defect": {
            "classification": "post-observation-screening-semantic-defect",
            "cause": (
                "Canonical Decimal metrics reloaded as JSON strings, but historical "
                "_pair_values retained only Decimal, int, or null values."
            ),
            "historical_artifact_disposition": (
                "byte-valid immutable evidence with a semantically incomplete screening ledger"
            ),
            "historical_bytes_rewritten": False,
            "campaign_rerun": False,
        },
        "runtime_accounting": runtime_accounting,
        "recomputed_discovery": recomputed,
        "disposition": {
            "original_cohort_size": 0,
            "recomputed_cohort_size": 0,
            "empty_disposition_invariant": True,
            "maximum_normal_active_sessions": max(
                cast(int, row["normal_active_sessions"])
                for row in cast(list[dict[str, object]], recomputed["ledger"])
            ),
            "minimum_required_normal_active_sessions": 12,
            "later_stage_work_warranted": False,
            "run_specifications_consumed": 18,
            "global_numerical_headroom": 252,
            "remaining_permitted_campaign_capacity": 180,
            "campaign_1_unused_specifications_transferable": False,
        },
        "scope_limit": (
            "Campaign 1 runtime reports and control metadata only. No market bars, June, V3, "
            "daily 2018-2019, protected results, PAPER, broker, live, credential, or "
            "strategic-allocation-21 state was read."
        ),
        "protected_access": dict(_PROTECTED_ACCESS),
        "authority": dict(_AUTHORITY),
    }
    payload["assessment_fingerprint"] = fingerprint(payload)
    return payload


def publish_intraday_spy_qqq_lead_lag_001_reassessment(
    repository: Path,
    data_home: Path,
) -> Path:
    """Create the immutable reassessment artifact or verify identical existing bytes."""
    repository = repository.resolve()
    payload = assess_intraday_spy_qqq_lead_lag_001(repository, data_home)
    path = repository / ASSESSMENT_RELATIVE_PATH
    raw = (canonical_json(payload) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise ValueError("Campaign 1 reassessment artifact already differs") from None
    return path


def _input_hashes(
    repository: Path,
    database: Path,
    final_report: Path,
    final_freeze: Path,
) -> dict[str, str]:
    return {
        "runtime_database": _sha256(database),
        "final_report": _sha256(final_report),
        "final_freeze": _sha256(final_freeze),
        "plan": _sha256(repository / PLAN_RELATIVE_PATH),
        "launch_control": _sha256(repository / LAUNCH_CONTROL_RELATIVE_PATH),
        "previous_state": _sha256(repository / STATE_RELATIVE_PATH),
    }


def _load_runtime_reports(
    database: Path,
    runtime: Path,
    final_freeze: Mapping[str, Any],
    configurations: Sequence[Any],
    source_commit: str,
) -> tuple[dict[tuple[str, str], Mapping[str, Any]], dict[str, object]]:
    connection = sqlite3.connect(
        f"{database.resolve().as_uri()}?mode=ro&immutable=1",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    try:
        if [row[0] for row in connection.execute("PRAGMA quick_check").fetchall()] != ["ok"]:
            raise ValueError("Campaign 1 reassessment SQLite quick check failed")
        bindings = connection.execute(
            "SELECT program_id, binding_json, binding_fingerprint FROM research_program_binding"
        ).fetchall()
        runs = connection.execute("SELECT * FROM research_runs ORDER BY run_id").fetchall()
        attempts = connection.execute(
            "SELECT attempt_id, run_id, attempt_number, source_sha, run_fingerprint "
            "FROM research_attempts ORDER BY run_id"
        ).fetchall()
        events = connection.execute(
            "SELECT a.run_id, e.kind FROM research_attempts AS a "
            "JOIN research_attempt_events AS e ON e.attempt_id = a.attempt_id "
            "ORDER BY a.run_id, e.event_id"
        ).fetchall()
    finally:
        connection.close()

    if len(bindings) != 1 or bindings[0]["program_id"] != PROGRAM_ID:
        raise ValueError("Campaign 1 reassessment program binding differs")
    binding = _json_mapping(str(bindings[0]["binding_json"]).encode(), "program binding")
    if (
        fingerprint(binding) != bindings[0]["binding_fingerprint"]
        or binding.get("source_commit") != source_commit
        or binding.get("program_id") != PROGRAM_ID
        or binding.get("authority") != _AUTHORITY
    ):
        raise ValueError("Campaign 1 reassessment program binding identity differs")

    expected_candidates = {str(item.candidate_id) for item in configurations}
    expected_contexts = {
        (candidate, scenario)
        for candidate in expected_candidates
        for scenario in ("normal", "zero_cost_diagnostic")
    }
    if len(runs) != 18 or len(attempts) != 18 or len(events) != 36:
        raise ValueError("Campaign 1 reassessment runtime counts differ")
    attempts_by_run = {str(row["run_id"]): row for row in attempts}
    event_kinds: dict[str, list[str]] = {}
    for row in events:
        event_kinds.setdefault(str(row["run_id"]), []).append(str(row["kind"]))

    frozen_runs_raw = final_freeze.get("all_runtime_runs")
    if not isinstance(frozen_runs_raw, list) or len(frozen_runs_raw) != 18:
        raise ValueError("Campaign 1 reassessment frozen run ledger differs")
    frozen_runs = {
        _text(_mapping(item, "frozen run"), "run_id"): _mapping(item, "frozen run")
        for item in frozen_runs_raw
    }
    reports: dict[tuple[str, str], Mapping[str, Any]] = {}
    filesystem_paths: set[Path] = set()
    for row in runs:
        run_id = str(row["run_id"])
        attempt = attempts_by_run.get(run_id)
        if (
            row["status"] != "completed"
            or row["active_attempt_id"] is not None
            or row["attempt_count"] != 1
            or row["failure_class"] is not None
            or row["failure_reason"] is not None
            or attempt is None
            or attempt["attempt_number"] != 1
            or attempt["source_sha"] != source_commit
            or attempt["run_fingerprint"] != row["run_fingerprint"]
            or event_kinds.get(run_id) != ["started", "completed"]
        ):
            raise ValueError(f"Campaign 1 reassessment run lifecycle differs: {run_id}")
        relative = Path(str(row["canonical_report_relative_path"]))
        if relative != Path("run-reports") / f"{run_id}.json":
            raise ValueError(f"Campaign 1 reassessment report path differs: {run_id}")
        path = runtime / relative
        filesystem_paths.add(path.resolve())
        raw = path.read_bytes()
        stored_bytes = bytes(row["canonical_report_bytes"])
        report_sha256 = hashlib.sha256(raw).hexdigest()
        frozen = frozen_runs.get(run_id)
        if (
            raw != stored_bytes
            or report_sha256 != row["canonical_report_sha256"]
            or frozen is None
            or frozen.get("status") != "completed"
            or frozen.get("attempt_count") != 1
            or frozen.get("report_path") != relative.as_posix()
            or frozen.get("report_sha256") != report_sha256
            or frozen.get("report_fingerprint") != row["canonical_report_fingerprint"]
        ):
            raise ValueError(f"Campaign 1 reassessment canonical report differs: {run_id}")
        report = _json_mapping(raw, "canonical report")
        unsigned = dict(report)
        report_fingerprint = unsigned.pop("report_fingerprint", None)
        specification = _mapping(report.get("specification"), "report specification")
        context = _mapping(specification.get("context"), "report context")
        candidate = _text(context, "candidate_id")
        period = _text(context, "period_id")
        scenario = _text(context, "scenario_id")
        key = (candidate, scenario)
        if (
            report.get("run_id") != run_id
            or report.get("program_id") != PROGRAM_ID
            or report.get("source_commit") != source_commit
            or report.get("plan_sha256") != PLAN_SHA256
            or report.get("plan_fingerprint") != PLAN_FINGERPRINT
            or report.get("authority") != _AUTHORITY
            or specification.get("source_commit") != source_commit
            or specification.get("authority") != _AUTHORITY
            or period != DISCOVERY_PERIOD_ID
            or key not in expected_contexts
            or key in reports
            or fingerprint(specification) != report.get("specification_fingerprint")
            or fingerprint(specification) != row["run_fingerprint"]
            or fingerprint(unsigned) != report_fingerprint
            or report_fingerprint != row["canonical_report_fingerprint"]
        ):
            raise ValueError(f"Campaign 1 reassessment report identity differs: {run_id}")
        reports[key] = report

    actual_files = {
        path.resolve() for path in (runtime / "run-reports").glob("*.json") if path.is_file()
    }
    if set(reports) != expected_contexts or actual_files != filesystem_paths:
        raise ValueError("Campaign 1 reassessment report catalog differs")
    return reports, {
        "sqlite_quick_check": "ok",
        "completed_run_count": 18,
        "attempt_count": 18,
        "maximum_attempts_for_one_run": 1,
        "retry_count": 0,
        "failed_run_count": 0,
        "pending_run_count": 0,
        "running_run_count": 0,
        "active_claim_count": 0,
        "canonical_report_count": 18,
        "later_stage_run_count": 0,
    }


def _recompute_discovery(
    reports: Mapping[tuple[str, str], Mapping[str, Any]],
    configurations: Sequence[Any],
    gates: Sequence[Mapping[str, Any]],
) -> dict[str, object]:
    ledger: list[dict[str, object]] = []
    for configuration in configurations:
        candidate = str(configuration.candidate_id)
        normal = reports[(candidate, "normal")]
        zero = reports[(candidate, "zero_cost_diagnostic")]
        if normal.get("lead_signal_trace_fingerprint") != zero.get("lead_signal_trace_fingerprint"):
            raise ValueError(f"Campaign 1 reassessment paired signal trace differs: {candidate}")
        normal_execution = _mapping(normal.get("execution_evidence"), "normal execution evidence")
        zero_execution = _mapping(zero.get("execution_evidence"), "zero execution evidence")
        if normal_execution.get("decision_trace_fingerprint") != zero_execution.get(
            "decision_trace_fingerprint"
        ):
            raise ValueError(f"Campaign 1 reassessment paired decision trace differs: {candidate}")

        normal_metrics = _mapping(normal.get("metrics"), "normal metrics")
        zero_metrics = _mapping(zero.get("metrics"), "zero metrics")
        active, round_trips = _derived_activity(normal)
        if (
            _integer(normal_metrics.get("active_session_count"), "active_session_count") != active
            or _integer(normal_metrics.get("completed_round_trips"), "completed_round_trips")
            != round_trips
        ):
            raise ValueError(f"Campaign 1 reassessment activity accounting differs: {candidate}")
        _validate_accounting(normal)
        _validate_accounting(zero)

        values: dict[str, Decimal | int | None] = {
            "normal.signal_trace_mismatch_count": 0,
        }
        for gate in gates:
            metric = _text(gate, "metric")
            if metric in values:
                continue
            prefix, name = metric.split(".", 1)
            source = normal_metrics if prefix == "normal" else zero_metrics
            if name not in source:
                raise ValueError(f"Campaign 1 reassessment required metric is missing: {metric}")
            values[metric] = _metric(source[name], metric)
        gate_results = [_gate_result(gate, values) for gate in gates]
        eligible = all(cast(bool, gate["passed"]) for gate in gate_results)
        ledger.append(
            {
                "candidate_id": candidate,
                "normal_active_sessions": active,
                "normal_completed_round_trips": round_trips,
                "activity_gate_failed": active < 12,
                "metrics": values,
                "gates": gate_results,
                "eligible": eligible,
            }
        )
    selected = [cast(str, row["candidate_id"]) for row in ledger if row["eligible"]]
    if selected or not all(cast(bool, row["activity_gate_failed"]) for row in ledger):
        raise ValueError("Campaign 1 reassessment empty-disposition proof differs")
    return {
        "parent_count": 9,
        "normal_zero_report_count": 18,
        "gate_count_per_parent": len(gates),
        "all_parents_screened_simultaneously": True,
        "ledger": ledger,
        "selected": selected,
    }


def _derived_activity(report: Mapping[str, Any]) -> tuple[int, int]:
    details = _mapping(report.get("details"), "report details")
    raw = details.get("session_ledger")
    if not isinstance(raw, list) or len(raw) != 87:
        raise ValueError("Campaign 1 reassessment session ledger differs")
    sessions: set[str] = set()
    active = 0
    round_trips = 0
    for item in raw:
        row = _mapping(item, "session row")
        session = _text(row, "session")
        if session in sessions:
            raise ValueError("Campaign 1 reassessment session repeats")
        sessions.add(session)
        disposition_active = _text(row, "disposition") == "active"
        if row.get("active") is not disposition_active:
            raise ValueError("Campaign 1 reassessment session activity differs")
        active += disposition_active
        round_trips += _integer(row.get("completed_round_trips"), "session round trips")
    return active, round_trips


def _validate_accounting(report: Mapping[str, Any]) -> None:
    metrics = _mapping(report.get("metrics"), "report metrics")
    gross = _required_metric(metrics.get("gross_profit_loss"), "gross_profit_loss")
    friction = _required_metric(metrics.get("execution_friction"), "execution_friction")
    net = _required_metric(metrics.get("net_profit_loss"), "net_profit_loss")
    identity = _required_metric(
        metrics.get("accounting_identity_error"), "accounting_identity_error"
    )
    if abs(gross - friction - net).quantize(_ACCOUNTING_PRECISION) != identity or identity != 0:
        raise ValueError("Campaign 1 reassessment report accounting differs")


def _gate_result(
    gate: Mapping[str, Any],
    values: Mapping[str, Decimal | int | None],
) -> dict[str, object]:
    metric = _text(gate, "metric")
    comparison = _text(gate, "comparison")
    threshold = _decimal_value(
        gate.get("threshold"), f"{metric} threshold", require_canonical=False
    )
    observed = values[metric]
    numeric = None if observed is None else Decimal(observed)
    if comparison not in {">", ">=", "<=", "="}:
        raise ValueError(f"Campaign 1 reassessment comparison differs: {comparison}")
    passed = (
        numeric is not None
        and {
            ">": numeric > threshold if numeric is not None else False,
            ">=": numeric >= threshold if numeric is not None else False,
            "<=": numeric <= threshold if numeric is not None else False,
            "=": numeric == threshold if numeric is not None else False,
        }[comparison]
    )
    return {
        "metric": metric,
        "comparison": comparison,
        "threshold": threshold,
        "observed": numeric,
        "passed": passed,
    }


def _metric(value: object, name: str) -> Decimal | int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"Campaign 1 reassessment metric type differs: {name}")
    if isinstance(value, int):
        return value
    return _required_metric(value, name)


def _required_metric(value: object, name: str) -> Decimal:
    return _decimal_value(value, name, require_canonical=True)


def _decimal_value(value: object, name: str, *, require_canonical: bool) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str | int | Decimal):
        raise ValueError(f"Campaign 1 reassessment metric type differs: {name}")
    if isinstance(value, str) and value != value.strip():
        raise ValueError(f"Campaign 1 reassessment metric text differs: {name}")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"Campaign 1 reassessment metric is invalid: {name}") from error
    if not parsed.is_finite():
        raise ValueError(f"Campaign 1 reassessment metric is not finite: {name}")
    if require_canonical and isinstance(value, str) and canonicalize(parsed) != value:
        raise ValueError(f"Campaign 1 reassessment metric is not canonical: {name}")
    return parsed


def _validate_original_screening_defect(
    final_freeze: Mapping[str, Any],
    recomputed: Mapping[str, object],
) -> None:
    screened = _mapping(final_freeze.get("screened_ledger"), "screened ledger")
    discovery = _mapping(screened.get("discovery"), "discovery ledger")
    original = discovery.get("ledger")
    corrected = cast(list[dict[str, object]], recomputed["ledger"])
    if not isinstance(original, list) or len(original) != 9 or discovery.get("selected") != []:
        raise ValueError("Campaign 1 reassessment original discovery ledger differs")
    corrected_by_id = {cast(str, row["candidate_id"]): row for row in corrected}
    omitted = {
        "normal.total_return",
        "zero_cost_diagnostic.total_return",
        "normal.max_drawdown",
        "normal.accounting_identity_error",
    }
    for item in original:
        row = _mapping(item, "original discovery row")
        candidate = _text(_mapping(row.get("candidate"), "candidate"), "candidate_id")
        gates = row.get("gates")
        if candidate not in corrected_by_id or not isinstance(gates, list):
            raise ValueError("Campaign 1 reassessment original candidate differs")
        observed = {
            _text(_mapping(gate, "original gate"), "metric"): _mapping(gate, "original gate").get(
                "observed"
            )
            for gate in gates
        }
        if any(observed.get(metric) is not None for metric in omitted):
            raise ValueError("Campaign 1 reassessment historical defect signature differs")
        corrected_row = corrected_by_id[candidate]
        metrics = _mapping(row.get("metrics"), "original metrics")
        if (
            metrics.get("normal.active_session_count") != corrected_row["normal_active_sessions"]
            or metrics.get("normal.completed_round_trips")
            != corrected_row["normal_completed_round_trips"]
            or row.get("eligible") is not False
        ):
            raise ValueError("Campaign 1 reassessment original activity differs")


def _validate_empty_downstream(
    final_report: Mapping[str, Any],
    final_freeze: Mapping[str, Any],
    recomputed: Mapping[str, object],
) -> None:
    counts = _mapping(final_report.get("counts"), "final counts")
    screened = _mapping(final_freeze.get("screened_ledger"), "screened ledger")
    walk = _mapping(screened.get("walk_forward"), "walk-forward ledger")
    stress = _mapping(screened.get("stress"), "stress ledger")
    neighbors = _mapping(screened.get("neighbors"), "neighbor ledger")
    if (
        recomputed.get("selected") != []
        or final_report.get("outcome") != "no-controlled-qualified-candidate"
        or final_report.get("cohort") != []
        or final_freeze.get("cohort") != []
        or counts.get("total_run_specifications") != 18
        or counts.get("walk_forward_run_specifications") != 0
        or counts.get("stress_run_specifications") != 0
        or counts.get("neighbor_new_run_specifications") != 0
        or walk != {"ledger": [], "selected": []}
        or stress != {"ledger": [], "selected": []}
        or neighbors.get("ledger") != []
        or neighbors.get("selected") != []
        or neighbors.get("requested_run_specification_count") != 0
        or neighbors.get("new_run_specification_count") != 0
    ):
        raise ValueError("Campaign 1 reassessment downstream disposition differs")


def _validate_boundaries(
    final_report: Mapping[str, Any],
    final_freeze: Mapping[str, Any],
    launch_control: Mapping[str, Any],
    previous_state: Mapping[str, Any],
    evidence: ReassessmentEvidence,
) -> None:
    report_freeze = _mapping(final_report.get("final_freeze"), "final report freeze")
    report_database = _mapping(final_report.get("runtime_database"), "runtime database")
    freeze_plan = _mapping(final_freeze.get("plan"), "freeze plan")
    if (
        final_report.get("source_commit") != evidence.runtime_source_commit
        or final_report.get("plan_sha256") != PLAN_SHA256
        or final_report.get("plan_fingerprint") != PLAN_FINGERPRINT
        or final_report.get("protected_access") != _PROTECTED_ACCESS
        or final_report.get("authority") != _AUTHORITY
        or report_database != {"path": DATABASE_NAME, "sha256": evidence.database_sha256}
        or report_freeze.get("path") != FINAL_FREEZE_NAME
        or report_freeze.get("sha256") != evidence.final_freeze_sha256
        or report_freeze.get("fingerprint") != evidence.final_freeze_fingerprint
        or final_freeze.get("source_commit") != evidence.runtime_source_commit
        or freeze_plan.get("sha256") != PLAN_SHA256
        or freeze_plan.get("fingerprint") != PLAN_FINGERPRINT
        or freeze_plan.get("state_sha256") != STATE_SHA256
        or freeze_plan.get("state_fingerprint") != STATE_FINGERPRINT
        or final_freeze.get("protected_access") != _PROTECTED_ACCESS
        or final_freeze.get("authority") != _AUTHORITY
        or launch_control.get("status") != "passed"
        or launch_control.get("verdict") != "pass"
        or launch_control.get("authority") != _AUTHORITY
        or previous_state.get("state_revision") != 2
        or previous_state.get("authority") != {"strategy_execution": False, **_AUTHORITY}
    ):
        raise ValueError("Campaign 1 reassessment control boundary differs")


def _discovery_gates(plan: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    screen = _mapping(plan.get("discovery_screen"), "discovery screen")
    raw = screen.get("gates")
    if (
        screen.get("undefined_metric_action") != "fail"
        or not isinstance(raw, Sequence)
        or isinstance(raw, str | bytes)
    ):
        raise ValueError("Campaign 1 reassessment discovery screen differs")
    gates = tuple(_mapping(item, "discovery gate") for item in raw)
    if len(gates) != 11:
        raise ValueError("Campaign 1 reassessment discovery gate count differs")
    return gates


def _fingerprinted_json(
    path: Path,
    fingerprint_field: str,
    expected_fingerprint: str,
    label: str,
) -> Mapping[str, Any]:
    value = _json_mapping(path.read_bytes(), label)
    unsigned = dict(value)
    stored = unsigned.pop(fingerprint_field, None)
    if stored != expected_fingerprint or fingerprint(unsigned) != stored:
        raise ValueError(f"Campaign 1 reassessment {label} fingerprint differs")
    return value


def _json_mapping(raw: bytes, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Campaign 1 reassessment {label} is invalid JSON") from error
    return _mapping(value, label)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Campaign 1 reassessment JSON key repeats: {key}")
        result[key] = value
    return result


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Campaign 1 reassessment {label} must be an object")
    return cast(Mapping[str, Any], value)


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"Campaign 1 reassessment {key} must be text")
    return item


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Campaign 1 reassessment {name} must be an integer")
    return value


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"Campaign 1 reassessment file is missing: {path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()
