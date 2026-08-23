from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from systematic_trading_lab.intraday_event_drift_001_plan import (
    CALENDAR_FINGERPRINT,
    CALENDAR_SHA256,
    PLAN_FINGERPRINT,
    PLAN_SHA256,
    REVIEW_FINGERPRINT,
    REVIEW_SHA256,
    SOURCE_EVIDENCE_FINGERPRINT,
    SOURCE_EVIDENCE_SHA256,
    load_intraday_event_drift_001_plan,
)

_REPOSITORY = Path(__file__).resolve().parents[2]


def test_frozen_event_drift_plan_exposes_only_validated_inputs() -> None:
    plan = load_intraday_event_drift_001_plan(_REPOSITORY)

    assert (plan.sha256, plan.plan_fingerprint) == (PLAN_SHA256, PLAN_FINGERPRINT)
    assert (plan.calendar_sha256, plan.calendar_fingerprint) == (
        CALENDAR_SHA256,
        CALENDAR_FINGERPRINT,
    )
    assert (plan.source_evidence_sha256, plan.source_evidence_fingerprint) == (
        SOURCE_EVIDENCE_SHA256,
        SOURCE_EVIDENCE_FINGERPRINT,
    )
    assert (plan.review_sha256, plan.review_fingerprint) == (REVIEW_SHA256, REVIEW_FINGERPRINT)
    assert len(plan.events) == 30
    assert len(plan.eligible_events) == 28
    assert {event.event_id: event.disposition for event in plan.excluded_events} == {
        "bls-empsit-2026-02-11": "excluded-source-causality-unproven",
        "bls-empsit-2026-04-03": "excluded-xnys-closed",
    }
    assert len({event.xnys_session for event in plan.eligible_events}) == 28
    assert [period.eligible_event_count for period in plan.periods] == [10, 4, 6, 5, 3]
    assert plan.periods[0].evaluation_start == datetime(2025, 7, 1, 13, 30, tzinfo=UTC)
    assert plan.periods[-1].evaluation_end == datetime(2026, 5, 29, 19, 55, tzinfo=UTC)
    assert [candidate.candidate_id for candidate in plan.configurations] == [
        f"ied001-a{reaction:02d}-b{minimum:02d}"
        for reaction in range(1, 4)
        for minimum in range(1, 4)
    ]
    assert sum(len(candidate.neighbor_ids) for candidate in plan.configurations) // 2 == 12
    assert not any(plan.authority.values())


def test_event_drift_plan_rejects_changed_calendar_bytes(tmp_path: Path) -> None:
    relative = Path("config/research/intraday-event-calendar-001-v1.json")
    for source_relative in (
        Path("config/research/intraday-event-drift-001-plan-v1.json"),
        Path("config/research/intraday-event-calendar-001-source-evidence-v1.json"),
        Path("config/research/intraday-event-drift-001-plan-independent-review-v1.json"),
    ):
        target = tmp_path / source_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_REPOSITORY / source_relative, target)
    destination = tmp_path / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes((_REPOSITORY / relative).read_bytes() + b"\n")

    with pytest.raises(ValueError, match="calendar SHA-256 differs"):
        load_intraday_event_drift_001_plan(tmp_path)
