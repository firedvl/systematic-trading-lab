from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from systematic_trading_lab.intraday_exposed_003_plan import (
    REVIEWED_JUNE_DISPOSITION_FINGERPRINT,
    REVIEWED_JUNE_DISPOSITION_SHA256,
    REVIEWED_PLAN_FINGERPRINT,
    REVIEWED_PLAN_REVIEW_FINGERPRINT,
    REVIEWED_PLAN_REVIEW_SHA256,
    REVIEWED_PLAN_SHA256,
    load_intraday_exposed_003_plan,
)

_REPOSITORY = Path(__file__).resolve().parents[2]


def test_frozen_exposed_003_plan_rekeys_only_exact_exposed_002_design() -> None:
    plan = load_intraday_exposed_003_plan(_REPOSITORY)

    assert plan.sha256 == REVIEWED_PLAN_SHA256
    assert plan.plan_fingerprint == REVIEWED_PLAN_FINGERPRINT
    assert plan.june_disposition_sha256 == REVIEWED_JUNE_DISPOSITION_SHA256
    assert plan.june_disposition_fingerprint == REVIEWED_JUNE_DISPOSITION_FINGERPRINT
    review_path = (
        _REPOSITORY / "config/research/intraday-exposed-003-plan-independent-review-v1.json"
    )
    assert hashlib.sha256(review_path.read_bytes()).hexdigest() == REVIEWED_PLAN_REVIEW_SHA256
    assert json.loads(review_path.read_text())["review_fingerprint"] == (
        REVIEWED_PLAN_REVIEW_FINGERPRINT
    )
    assert len(plan.configurations) == 60
    assert plan.configurations[0].candidate_id == "ie003-f01-a01-b01"
    assert plan.configurations[-1].candidate_id == "ie003-f10-a03-b02"
    assert plan.periods == plan.source_plan.periods

    for current, source in zip(plan.configurations, plan.source_plan.configurations, strict=True):
        assert current.candidate_id == source.candidate_id.replace("ie002-", "ie003-", 1)
        assert current.source_candidate_id == source.candidate_id
        assert current.family_id == source.family_id
        assert current.family_ordinal == source.family_ordinal
        assert current.parameters == source.parameters
        assert current.neighbor_ids == tuple(
            neighbor.replace("ie002-", "ie003-", 1) for neighbor in source.neighbor_ids
        )

    source = plan.payload["source_design"]
    assert source["parent_configuration_count"] == 60
    assert source["discovery_run_count"] == 120
    assert source["runtime_rows_imported"] is False
    assert source["result_dependent_design_change"] is False
    assert plan.payload["cost_model"] == {
        "path": "config/research/intraday-execution-cost-model-001-v1.json",
        "cost_model_id": "intraday-execution-cost-model-001-v1",
        "sha256": "a9e6c2b86c6623d73e089de591c55eeec0711fa55f0933a4e3ea9a1c0c2392af",
        "fingerprint": "94fc3ba4663b422fbb0dc0cce7e3d78a7ba81f22d71d5fa986ab6847b7925bb4",
        "recalibration_allowed": False,
    }
    assert plan.payload["research_attempts"]["maximum_infrastructure_attempts"] == 3
    assert plan.payload["identity"]["database"] == "intraday-exposed-003.sqlite3"


def test_exposed_003_june_is_metadata_ineligible_before_results() -> None:
    plan = load_intraday_exposed_003_plan(_REPOSITORY)
    disposition = plan.june_disposition

    assert disposition["status"] == "ineligible-before-strategy-results"
    assert disposition["audit"]["conflicting_entry_id"] == ("intraday-v2-real-market-results")
    assert disposition["audit"]["conflicting_entry_class"] == ("real-market-result-observed")
    assert disposition["audit"]["active_controlled_registry_june_experiment_rows"] == 0
    assert disposition["audit"]["active_controlled_registry_unconsumed_holdout_authorizations"] == 0
    assert disposition["program_effect"]["june_read_allowed"] is False
    assert disposition["program_effect"]["controlled_evaluation_allowed"] is False
    assert disposition["program_effect"]["substitute_range_allowed"] is False
    assert all(value is False for value in plan.payload["authority"].values())


def test_exposed_003_plan_rejects_changed_bytes(tmp_path: Path) -> None:
    destination = tmp_path / "config/research/intraday-exposed-003-plan-v1.json"
    destination.parent.mkdir(parents=True)
    destination.write_bytes((_REPOSITORY / destination.relative_to(tmp_path)).read_bytes() + b"\n")

    with pytest.raises(ValueError, match="plan SHA-256 differs"):
        load_intraday_exposed_003_plan(tmp_path)


def test_exposed_003_plan_rejects_changed_source_plan(tmp_path: Path) -> None:
    plan_path = Path("config/research/intraday-exposed-003-plan-v1.json")
    source_path = Path("config/research/intraday-exposed-002-plan-v1.json")
    (tmp_path / plan_path).parent.mkdir(parents=True)
    (tmp_path / plan_path).write_bytes((_REPOSITORY / plan_path).read_bytes())
    (tmp_path / source_path).write_bytes((_REPOSITORY / source_path).read_bytes() + b"\n")

    with pytest.raises(ValueError, match="Exposed 002 plan SHA-256 differs"):
        load_intraday_exposed_003_plan(tmp_path)
