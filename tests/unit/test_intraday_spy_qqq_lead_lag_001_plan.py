from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from systematic_trading_lab.intraday_spy_qqq_lead_lag_001_plan import (
    PLAN_FINGERPRINT,
    PLAN_SHA256,
    REVIEW_FINGERPRINT,
    REVIEW_SHA256,
    STATE_FINGERPRINT,
    STATE_SHA256,
    load_intraday_spy_qqq_lead_lag_001_plan,
)

_REPOSITORY = Path(__file__).resolve().parents[2]


def _frozen_repository(destination: Path) -> None:
    shutil.copytree(_REPOSITORY / "config", destination / "config")
    shutil.copytree(
        _REPOSITORY / "docs/research-campaigns",
        destination / "docs/research-campaigns",
    )


def test_loads_exact_reviewed_campaign_one_plan_and_state_revision() -> None:
    plan = load_intraday_spy_qqq_lead_lag_001_plan(_REPOSITORY)

    assert (plan.sha256, plan.plan_fingerprint) == (PLAN_SHA256, PLAN_FINGERPRINT)
    assert (plan.review_sha256, plan.review_fingerprint) == (
        REVIEW_SHA256,
        REVIEW_FINGERPRINT,
    )
    assert (plan.state_sha256, plan.state_fingerprint) == (
        STATE_SHA256,
        STATE_FINGERPRINT,
    )
    assert [item.session_count for item in plan.periods] == [87, 41, 39, 43, 20]
    assert [item.observation_horizon_bars for item in plan.configurations] == [
        6,
        6,
        6,
        12,
        12,
        12,
        18,
        18,
        18,
    ]
    assert sum(len(item.neighbor_ids) for item in plan.configurations) // 2 == 12
    assert plan.state["phase"] == "campaign-1-plan-reviewed-implementation-pending"
    assert not any(plan.authority.values())


def test_loaded_campaign_one_controls_are_deeply_immutable() -> None:
    plan = load_intraday_spy_qqq_lead_lag_001_plan(_REPOSITORY)

    with pytest.raises(TypeError):
        plan.payload["authority"]["broker_writes"] = True
    with pytest.raises(TypeError):
        plan.review["verification"]["candidate_count"] = 10
    with pytest.raises(TypeError):
        plan.state["campaign_dispositions"][plan.payload["program_id"]] = "complete"


@pytest.mark.parametrize(
    ("relative", "message"),
    [
        (
            "config/research/intraday-spy-qqq-lead-lag-001-plan-v1.json",
            "plan SHA-256 differs",
        ),
        (
            "config/research/intraday-spy-qqq-lead-lag-001-plan-independent-review-v1.json",
            "review SHA-256 differs",
        ),
        (
            "docs/research-campaigns/intraday-autonomous-research-001-state-v2-revision-002.json",
            "state SHA-256 differs",
        ),
    ],
)
def test_rejects_changed_campaign_one_control_bytes(
    tmp_path: Path, relative: str, message: str
) -> None:
    _frozen_repository(tmp_path)
    path = tmp_path / relative
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match=message):
        load_intraday_spy_qqq_lead_lag_001_plan(tmp_path)


@pytest.mark.parametrize(
    "relative",
    [
        "config/research/intraday-event-drift-001-plan-v1.json",
        "config/research/intraday-execution-cost-model-001-independent-review-v1.json",
        "config/research/intraday-exposed-005-june-disposition-v1.json",
    ],
)
def test_rejects_changed_campaign_one_dependency(tmp_path: Path, relative: str) -> None:
    _frozen_repository(tmp_path)
    path = tmp_path / relative
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="SHA-256 differs"):
        load_intraday_spy_qqq_lead_lag_001_plan(tmp_path)


def test_plan_hash_and_parse_use_one_byte_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _frozen_repository(tmp_path)
    plan_path = (tmp_path / "config/research/intraday-spy-qqq-lead-lag-001-plan-v1.json").resolve()
    valid = plan_path.read_bytes()
    altered = valid.replace(b'"broker_writes": false', b'"broker_writes": true')
    original_read_bytes = Path.read_bytes
    calls = 0

    def read_bytes(path: Path) -> bytes:
        nonlocal calls
        if path.resolve() == plan_path:
            calls += 1
            return valid if calls == 1 else altered
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    plan = load_intraday_spy_qqq_lead_lag_001_plan(tmp_path)

    assert calls == 1
    assert plan.payload["authority"]["broker_writes"] is False


def test_rejects_duplicate_json_keys_before_semantic_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _frozen_repository(tmp_path)
    path = tmp_path / "config/research/intraday-spy-qqq-lead-lag-001-plan-v1.json"
    raw = path.read_bytes().replace(b"{", b'{"program_id":"duplicate",', 1)
    path.write_bytes(raw)
    monkeypatch.setattr(
        "systematic_trading_lab.intraday_spy_qqq_lead_lag_001_plan.PLAN_SHA256",
        hashlib.sha256(raw).hexdigest(),
    )

    with pytest.raises(ValueError, match="duplicate JSON key: program_id"):
        load_intraday_spy_qqq_lead_lag_001_plan(tmp_path)
