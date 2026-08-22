from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from systematic_trading_lab.intraday_exposed_005_plan import (
    REVIEWED_JUNE_DISPOSITION_FINGERPRINT,
    REVIEWED_JUNE_DISPOSITION_SHA256,
    REVIEWED_PLAN_FINGERPRINT,
    REVIEWED_PLAN_REVIEW_FINGERPRINT,
    REVIEWED_PLAN_REVIEW_SHA256,
    REVIEWED_PLAN_SHA256,
    load_intraday_exposed_005_plan,
)

_REPOSITORY = Path(__file__).resolve().parents[2]


def test_frozen_exposed_005_plan_rekeys_only_identity_and_scheduling() -> None:
    plan = load_intraday_exposed_005_plan(_REPOSITORY)
    source = plan.source_plan

    assert plan.sha256 == REVIEWED_PLAN_SHA256
    assert plan.plan_fingerprint == REVIEWED_PLAN_FINGERPRINT
    assert plan.june_disposition_sha256 == REVIEWED_JUNE_DISPOSITION_SHA256
    assert plan.june_disposition_fingerprint == REVIEWED_JUNE_DISPOSITION_FINGERPRINT
    review = _REPOSITORY / "config/research/intraday-exposed-005-plan-independent-review-v1.json"
    assert hashlib.sha256(review.read_bytes()).hexdigest() == REVIEWED_PLAN_REVIEW_SHA256
    assert json.loads(review.read_bytes())["review_fingerprint"] == REVIEWED_PLAN_REVIEW_FINGERPRINT
    assert len(plan.configurations) == len(source.configurations) == 60
    assert (
        plan.periods
        == source.periods
        == source.source_plan.periods
        == source.source_plan.source_plan.periods
    )
    assert sum(len(item.neighbor_ids) for item in plan.configurations) == 140

    for current, previous, exposed_003, original in zip(
        plan.configurations,
        source.configurations,
        source.source_plan.configurations,
        source.source_plan.source_plan.configurations,
        strict=True,
    ):
        assert current.candidate_id == previous.candidate_id.replace("ie004-", "ie005-", 1)
        assert current.source_exposed_004_candidate_id == previous.candidate_id
        assert current.source_exposed_003_candidate_id == exposed_003.candidate_id
        assert current.source_candidate_id == previous.source_candidate_id == original.candidate_id
        assert (
            current.family_id == previous.family_id == exposed_003.family_id == original.family_id
        )
        assert (
            current.family_ordinal
            == previous.family_ordinal
            == exposed_003.family_ordinal
            == original.family_ordinal
        )
        assert (
            current.parameters
            == previous.parameters
            == exposed_003.parameters
            == original.parameters
        )
        assert current.neighbor_ids == tuple(
            neighbor.replace("ie004-", "ie005-", 1) for neighbor in previous.neighbor_ids
        )

    source_design = plan.payload["source_design"]
    assert source_design["intraday_exposed_002_runtime_rows_imported"] is False
    assert source_design["intraday_exposed_003_runtime_rows_imported"] is False
    assert source_design["intraday_exposed_004_runtime_rows_imported"] is False
    assert source_design["result_dependent_design_change"] is False
    assert plan.payload["process_execution"] == {
        "start_method": "spawn",
        "default_worker_count": 4,
        "worker_count_configurable": True,
        "maximum_active_claims_per_worker": 1,
        "worker_state_lifetime": "one-stage",
        "worker_dataset_cache": "private-immutable-read-only",
        "cross_stage_parallelism": False,
        "completion_order_affects_selection": False,
        "abrupt_exit_reassignment": "lease-expiry-only",
        "coordinator_authority": [
            "campaign-lock",
            "stage-order",
            "reservation",
            "stage-barriers",
            "screening",
            "freeze",
            "final-report",
        ],
    }
    assert plan.payload["report_identity"] == {
        "program_binding_schema": "intraday-exposed-005-program-binding-v1",
        "runner_version": "intraday-exposed-005-runner-v1",
        "run_schema": "intraday-exposed-005-run-v1",
        "run_report_schema": "intraday-exposed-005-backtest-report-v1",
        "final_freeze_schema": "intraday-exposed-005-final-freeze-v1",
        "final_report_schema": "intraday-exposed-005-final-report-v1",
    }


def test_exposed_005_launch_and_protected_boundaries_are_fail_closed() -> None:
    plan = load_intraday_exposed_005_plan(_REPOSITORY)
    launch = plan.payload["launch_gates"]
    equivalence = launch["equivalence"]

    assert equivalence["worker_counts"] == [1, 4]
    assert equivalence["fixture_selection"] == "configuration-and-scenario-only-never-metrics"
    assert equivalence["source_database_mutation_allowed"] is False
    assert equivalence["dataset_input_mutation_allowed"] is False
    assert launch["partial_strategy_merit_inspection_allowed"] is False
    assert launch["required_control_artifact"]["pass_required_before_launch"] is True
    assert plan.payload["research_attempts"]["maximum_infrastructure_attempts"] == 3
    assert plan.payload["identity"]["attempt_id_format"].startswith("ie005a-")
    assert plan.june_disposition["program_effect"]["june_read_allowed"] is False
    assert not any(plan.payload["authority"].values())


def test_exposed_005_plan_rejects_changed_bytes(tmp_path: Path) -> None:
    relative = Path("config/research/intraday-exposed-005-plan-v1.json")
    destination = tmp_path / relative
    destination.parent.mkdir(parents=True)
    destination.write_bytes((_REPOSITORY / relative).read_bytes() + b"\n")

    with pytest.raises(ValueError, match="plan SHA-256 differs"):
        load_intraday_exposed_005_plan(tmp_path)
