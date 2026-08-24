from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from systematic_trading_lab.intraday_event_drift_001_plan import (
    load_intraday_event_drift_001_plan,
)
from systematic_trading_lab.intraday_event_prior_low_rejection_001_plan import (
    PLAN_FINGERPRINT,
    PLAN_SHA256,
    REVIEW_FINGERPRINT,
    REVIEW_SHA256,
    load_intraday_event_prior_low_rejection_001_plan,
)

_REPOSITORY = Path(__file__).resolve().parents[2]


def test_frozen_prior_low_rejection_plan_exposes_only_validated_base_inputs() -> None:
    plan = load_intraday_event_prior_low_rejection_001_plan(_REPOSITORY)
    base = load_intraday_event_drift_001_plan(_REPOSITORY)

    assert (plan.sha256, plan.plan_fingerprint) == (PLAN_SHA256, PLAN_FINGERPRINT)
    assert (plan.review_sha256, plan.review_fingerprint) == (REVIEW_SHA256, REVIEW_FINGERPRINT)
    assert plan.events == base.events
    assert plan.periods == base.periods
    assert [item.confirmation_bars for item in plan.configurations] == [1, 2, 3]
    assert sum(len(item.neighbor_ids) for item in plan.configurations) // 2 == 2
    assert all(
        key not in plan.payload
        for key in ("chronology", "data", "execution", "frozen_dependencies")
    )
    assert not any(plan.authority.values())


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("intraday-event-prior-low-rejection-001-plan-v1.json", "plan SHA-256 differs"),
        (
            "intraday-event-prior-low-rejection-001-plan-independent-review-v1.json",
            "review SHA-256 differs",
        ),
    ],
)
def test_prior_low_rejection_plan_rejects_changed_exact_bytes(
    tmp_path: Path, filename: str, expected: str
) -> None:
    shutil.copytree(_REPOSITORY / "config/research", tmp_path / "config/research")
    path = tmp_path / "config/research" / filename
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match=expected):
        load_intraday_event_prior_low_rejection_001_plan(tmp_path)
