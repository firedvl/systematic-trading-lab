from __future__ import annotations

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from systematic_trading_lab.intraday_event_repricing_001_plan import (
    CALENDAR_FINGERPRINT,
    CALENDAR_SHA256,
    PLAN_FINGERPRINT,
    PLAN_SHA256,
    REVIEW_FINGERPRINT,
    REVIEW_SHA256,
    SOURCE_EVIDENCE_FINGERPRINT,
    SOURCE_EVIDENCE_SHA256,
    load_intraday_event_repricing_001_plan,
)

_REPOSITORY = Path(__file__).resolve().parents[2]


def test_frozen_event_repricing_plan_exposes_only_validated_inputs() -> None:
    plan = load_intraday_event_repricing_001_plan(_REPOSITORY)

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
    assert len(plan.events) == 30
    assert len(plan.eligible_events) == 28
    assert [period.eligible_event_count for period in plan.periods] == [10, 4, 6, 5, 3]
    assert [
        (item.reaction_bars, item.minimum_relative_reaction_bps) for item in plan.configurations
    ] == [
        (reaction, Decimal(str(threshold))) for reaction in (3, 6, 12) for threshold in (5, 10, 20)
    ]
    assert sum(len(item.neighbor_ids) for item in plan.configurations) // 2 == 12
    assert not any(plan.authority.values())


def test_event_repricing_plan_rejects_changed_plan_bytes(tmp_path: Path) -> None:
    shutil.copytree(_REPOSITORY / "config/research", tmp_path / "config/research")
    path = tmp_path / "config/research/intraday-event-repricing-001-plan-v1.json"
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="plan SHA-256 differs"):
        load_intraday_event_repricing_001_plan(tmp_path)


def test_event_repricing_plan_rejects_inheritance_mutation_even_with_recomputed_fingerprint(
    tmp_path: Path,
) -> None:
    shutil.copytree(_REPOSITORY / "config/research", tmp_path / "config/research")
    path = tmp_path / "config/research/intraday-event-repricing-001-plan-v1.json"
    payload = json.loads(path.read_text())
    payload["inheritance"]["inherited_exact_sections"].pop()
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="plan SHA-256 differs"):
        load_intraday_event_repricing_001_plan(tmp_path)
