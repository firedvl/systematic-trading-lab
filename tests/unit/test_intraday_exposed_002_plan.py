from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from systematic_trading_lab.intraday_exposed_002_plan import (
    REVIEWED_DATA_BINDING_FINGERPRINT,
    REVIEWED_DATA_BINDING_REVIEW_FINGERPRINT,
    REVIEWED_DATA_BINDING_REVIEW_SHA256,
    REVIEWED_DATA_BINDING_SHA256,
    REVIEWED_JUNE_DISPOSITION_FINGERPRINT,
    REVIEWED_MAY_ACQUISITION_DISPOSITION_FINGERPRINT,
    REVIEWED_PLAN_AMENDMENT_FINGERPRINT,
    REVIEWED_PLAN_AMENDMENT_REVIEW_FINGERPRINT,
    REVIEWED_PLAN_AMENDMENT_REVIEW_SHA256,
    REVIEWED_PLAN_AMENDMENT_SHA256,
    REVIEWED_PLAN_FINGERPRINT,
    REVIEWED_PLAN_REVIEW_FINGERPRINT,
    REVIEWED_PLAN_REVIEW_SHA256,
    REVIEWED_PLAN_SHA256,
    load_intraday_exposed_002_plan,
)

_REPOSITORY = Path(__file__).resolve().parents[2]


def test_frozen_intraday_exposed_002_plan_is_exact_sparse_and_pre_result() -> None:
    plan = load_intraday_exposed_002_plan(_REPOSITORY)

    assert plan.sha256 == REVIEWED_PLAN_SHA256
    assert plan.plan_fingerprint == REVIEWED_PLAN_FINGERPRINT
    assert plan.amendment_sha256 == REVIEWED_PLAN_AMENDMENT_SHA256
    assert plan.amendment_fingerprint == REVIEWED_PLAN_AMENDMENT_FINGERPRINT
    assert plan.data_binding_sha256 == REVIEWED_DATA_BINDING_SHA256
    assert plan.data_binding_fingerprint == REVIEWED_DATA_BINDING_FINGERPRINT
    review_path = (
        _REPOSITORY / "config/research/intraday-exposed-002-plan-independent-review-v1.json"
    )
    assert hashlib.sha256(review_path.read_bytes()).hexdigest() == REVIEWED_PLAN_REVIEW_SHA256
    assert json.loads(review_path.read_text())["review_fingerprint"] == (
        REVIEWED_PLAN_REVIEW_FINGERPRINT
    )
    amendment_review_path = (
        _REPOSITORY
        / "config/research/intraday-exposed-002-plan-amendment-independent-review-v2.json"
    )
    assert hashlib.sha256(amendment_review_path.read_bytes()).hexdigest() == (
        REVIEWED_PLAN_AMENDMENT_REVIEW_SHA256
    )
    assert json.loads(amendment_review_path.read_text())["review_fingerprint"] == (
        REVIEWED_PLAN_AMENDMENT_REVIEW_FINGERPRINT
    )
    binding_review_path = (
        _REPOSITORY / "config/research/intraday-exposed-002-data-binding-independent-review-v1.json"
    )
    assert hashlib.sha256(binding_review_path.read_bytes()).hexdigest() == (
        REVIEWED_DATA_BINDING_REVIEW_SHA256
    )
    assert json.loads(binding_review_path.read_text())["review_fingerprint"] == (
        REVIEWED_DATA_BINDING_REVIEW_FINGERPRINT
    )
    assert len(plan.configurations) == 60
    assert len({item.family_id for item in plan.configurations}) == 10
    assert plan.configurations[0].candidate_id == "ie002-f01-a01-b01"
    assert plan.configurations[-1].candidate_id == "ie002-f10-a03-b02"
    assert all(len(item.neighbor_ids) >= 2 for item in plan.configurations)
    assert all(item.candidate_id.startswith("ie002-") for item in plan.configurations)
    assert len(plan.periods) == 5
    assert plan.periods[-1].period_id == "final-exposed-2026-05"
    assert plan.periods[-1].evaluation_end.isoformat() == "2026-05-29T19:55:00+00:00"
    assert plan.payload["status"] == ("frozen-before-may-only-data-acquisition-or-strategy-results")
    data = plan.payload["data"]
    assert len(data["dataset_bindings"]) == 3
    assert data["dataset_bindings"][-1]["allowed_read_end"] == "2026-04-30T19:55:00Z"
    assert data["may_only_acquisition"] == {
        "status": "pending-until-plan-merges",
        "provider": "alpaca-historical-v2",
        "http_method": "GET",
        "feed": "iex",
        "fallback_allowed": False,
        "symbols": ["QQQ", "SPY"],
        "timeframe": "5m",
        "requested_start": "2026-05-01T13:30:00Z",
        "requested_end": "2026-05-29T19:55:00Z",
        "expected_session_count": 20,
        "expected_bar_count": 3120,
        "adjustment_policy": "provider-adjusted-all-v1",
        "universe_id": "liquid-etfs-intraday-5m-v1",
        "universe_fingerprint": (
            "6ac4a8269f8e352536f52ddc0a3000e0b39c5551c33c03959c20a640cfddeca9"
        ),
        "existing_artifact_derivation_allowed": False,
        "publication_rule": (
            "Publish a separate immutable dataset whose raw and Parquet records contain no "
            "market-data timestamp after the requested end and whose manifest requested and "
            "actual ranges end there."
        ),
        "forbidden_source": (
            "Do not derive the dataset from the existing May-June artifact because reading or "
            "filtering that file can scan June rows."
        ),
    }
    assert data["all_runtime_datasets_must_be_physically_bounded_before_june"] is True
    assert data["generic_filtered_read_of_artifact_containing_june"] is False
    amendment = plan.amendment
    assert amendment["status"] == (
        "frozen-after-transport-boundary-finding-before-data-binding-or-strategy-results"
    )
    assert amendment["acquisition_disposition"]["fingerprint"] == (
        REVIEWED_MAY_ACQUISITION_DISPOSITION_FINGERPRINT
    )
    replacement = amendment["replacement_data_contract"]
    assert replacement["raw_transport"]["actual_end"] == "2026-05-29T20:00:00Z"
    assert replacement["raw_transport"]["contains_june_market_timestamp"] is False
    assert replacement["normalized_parquet"]["actual_end"] == "2026-05-29T19:55:00Z"
    assert replacement["normalized_parquet"]["bar_count"] == 3120
    may_dataset = plan.data_binding["may_dataset"]
    assert may_dataset["dataset_id"] == (
        "4afa60f29ea266ec8b60be9d9600132f8cff4207e846443c65afd3bb5c497a19"
    )
    assert may_dataset["symbols"] == ["SPY", "QQQ"]
    assert may_dataset["raw_end"] == "2026-05-29T20:00:00Z"
    assert may_dataset["actual_end"] == "2026-05-29T19:55:00Z"
    assert may_dataset["raw_record_count"] == 3503
    assert may_dataset["bar_count"] == 3120
    assert may_dataset["contains_june_market_timestamp"] is False
    assert plan.payload["controlled_evaluation"] == {
        "range_status": "ineligible",
        "june_read": False,
        "substitute_range": False,
        "controlled_plan_creation": False,
        "empty_cohort_action": (
            "Close as immutable failed evidence with no controlled-qualified candidate."
        ),
        "nonempty_cohort_action": (
            "Stop after final freeze and report exposed-serious candidates only; do not claim "
            "controlled qualification."
        ),
    }
    assert plan.payload["frozen_dependencies"]["june_disposition"]["fingerprint"] == (
        REVIEWED_JUNE_DISPOSITION_FINGERPRINT
    )


def test_intraday_exposed_002_plan_rejects_changed_bytes(tmp_path: Path) -> None:
    destination = tmp_path / "config/research/intraday-exposed-002-plan-v1.json"
    destination.parent.mkdir(parents=True)
    destination.write_bytes((_REPOSITORY / destination.relative_to(tmp_path)).read_bytes() + b"\n")

    with pytest.raises(ValueError, match="plan SHA-256 differs"):
        load_intraday_exposed_002_plan(tmp_path)
