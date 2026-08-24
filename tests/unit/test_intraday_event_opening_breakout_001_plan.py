from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from systematic_trading_lab.intraday_event_drift_001_plan import (
    load_intraday_event_drift_001_plan,
)
from systematic_trading_lab.intraday_event_opening_breakout_001_plan import (
    CALENDAR_FINGERPRINT,
    CALENDAR_SHA256,
    PLAN_FINGERPRINT,
    PLAN_SHA256,
    REVIEW_FINGERPRINT,
    REVIEW_SHA256,
    SOURCE_EVIDENCE_FINGERPRINT,
    SOURCE_EVIDENCE_SHA256,
    load_intraday_event_opening_breakout_001_plan,
)

_REPOSITORY = Path(__file__).resolve().parents[2]


def test_frozen_opening_breakout_plan_exposes_only_validated_base_inputs() -> None:
    plan = load_intraday_event_opening_breakout_001_plan(_REPOSITORY)
    base = load_intraday_event_drift_001_plan(_REPOSITORY)

    assert (plan.sha256, plan.plan_fingerprint) == (PLAN_SHA256, PLAN_FINGERPRINT)
    assert (plan.review_sha256, plan.review_fingerprint) == (REVIEW_SHA256, REVIEW_FINGERPRINT)
    assert (plan.calendar_sha256, plan.calendar_fingerprint) == (
        CALENDAR_SHA256,
        CALENDAR_FINGERPRINT,
    )
    assert (plan.source_evidence_sha256, plan.source_evidence_fingerprint) == (
        SOURCE_EVIDENCE_SHA256,
        SOURCE_EVIDENCE_FINGERPRINT,
    )
    assert plan.events == base.events
    assert plan.periods == base.periods
    assert len(plan.eligible_events) == 28
    assert [item.breakout_buffer_bps for item in plan.configurations] == [2, 4, 8]
    assert sum(len(item.neighbor_ids) for item in plan.configurations) // 2 == 2
    assert "chronology" not in plan.payload
    assert "data" not in plan.payload
    assert "execution" not in plan.payload
    assert "frozen_dependencies" not in plan.payload
    assert not any(plan.authority.values())


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("intraday-event-opening-breakout-001-plan-v1.json", "plan SHA-256 differs"),
        (
            "intraday-event-opening-breakout-001-plan-independent-review-v1.json",
            "review SHA-256 differs",
        ),
    ],
)
def test_opening_breakout_plan_rejects_changed_exact_bytes(
    tmp_path: Path, filename: str, expected: str
) -> None:
    shutil.copytree(_REPOSITORY / "config/research", tmp_path / "config/research")
    path = tmp_path / "config/research" / filename
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match=expected):
        load_intraday_event_opening_breakout_001_plan(tmp_path)
