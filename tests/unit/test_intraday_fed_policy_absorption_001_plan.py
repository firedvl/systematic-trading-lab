from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from systematic_trading_lab.intraday_fed_policy_absorption_001_plan import (
    SOURCE_STATE_FINGERPRINT,
    SOURCE_STATE_SHA256,
    STATE_FINGERPRINT,
    STATE_SHA256,
    load_intraday_fed_policy_absorption_001_plan,
)

_REPOSITORY = Path(__file__).resolve().parents[2]


def test_loads_exact_frozen_calendar_and_candidate_lattice() -> None:
    plan = load_intraday_fed_policy_absorption_001_plan(_REPOSITORY)

    assert len(plan.events) == 15
    assert [period.eligible_event_count for period in plan.periods] == [6, 3, 2, 3, 1]
    assert sum(event.publication_class == "fomc-meeting-minutes" for event in plan.events) == 8
    assert sum(event.publication_class == "fomc-policy-statement" for event in plan.events) == 7
    assert plan.configurations[0].candidate_id == "fedabs-h02-f0008"
    assert plan.configurations[-1].neighbor_ids == (
        "fedabs-h05-f0024",
        "fedabs-h07-f0024",
        "fedabs-h06-f0020",
        "fedabs-h06-f0028",
    )
    assert (plan.source_state_sha256, plan.source_state_fingerprint) == (
        SOURCE_STATE_SHA256,
        SOURCE_STATE_FINGERPRINT,
    )
    assert (plan.state_sha256, plan.state_fingerprint) == (STATE_SHA256, STATE_FINGERPRINT)
    assert plan.state["phase"] == "campaign-3-plan-reviewed-implementation-pending"
    assert not any(plan.authority.values())


def test_rejects_changed_bound_control_before_loading() -> None:
    plan = load_intraday_fed_policy_absorption_001_plan(_REPOSITORY)

    with pytest.raises(TypeError):
        plan.state["authority"]["broker_writes"] = True


def test_rejects_changed_successor_state_bytes(tmp_path: Path) -> None:
    shutil.copytree(_REPOSITORY / "config", tmp_path / "config")
    shutil.copytree(_REPOSITORY / "docs/research-campaigns", tmp_path / "docs/research-campaigns")
    path = (
        tmp_path
        / "docs/research-campaigns/intraday-autonomous-research-001-state-v2-revision-006.json"
    )
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="SHA-256 differs"):
        load_intraday_fed_policy_absorption_001_plan(tmp_path)
