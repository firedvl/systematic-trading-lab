import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from systematic_trading_lab.experiments import (
    ExperimentError,
    ExperimentRegistry,
    ExperimentSpec,
    ExperimentSplit,
    HoldoutAccessError,
    QualificationState,
)
from systematic_trading_lab.fingerprints import fingerprint


def spec(experiment_id: str, split: ExperimentSplit = ExperimentSplit.TRAINING) -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id=experiment_id,
        campaign_id="campaign-1",
        strategy_id="moving-average-trend",
        strategy_version="1",
        strategy_family="trend",
        code_commit="abc123",
        dataset_id="dataset-1",
        dataset_fingerprint="fingerprint-1",
        universe_id="liquid-etfs-v1",
        universe_fingerprint="universe-fingerprint-1",
        parameters={"window": 20},
        cost_model_version="conservative-bps-v1",
        execution_model_version="next-bar-v1",
        split=split,
        start_timestamp=datetime(2020, 1, 1, tzinfo=UTC),
        end_timestamp=datetime(2021, 1, 1, tzinfo=UTC),
        random_seed=7,
        creation_reason="baseline campaign",
    )


def test_registry_tracks_lifecycle_budget_and_stale_recovery(tmp_path: Path) -> None:
    path = tmp_path / "experiments.sqlite3"
    registry = ExperimentRegistry(path)
    registry.create_campaign("campaign-1", "Foundation", 2)
    registry.create_experiment(spec("experiment-1"))
    registry.claim("experiment-1")
    registry.complete("experiment-1", {"total_return": Decimal("0.1")}, ["report.json"], ["hash"])
    completed = registry.get("experiment-1")
    assert completed["status"] == "completed"
    assert completed["metrics_json"] == {"total_return": "0.1"}
    with pytest.raises(ExperimentError, match="approved passing"):
        registry.record_qualification(
            "experiment-1",
            QualificationState.QUALIFIED,
            {
                "state": "qualified",
                "gates": [{"name": "return", "approved": False, "passed": True}],
            },
        )

    registry.create_experiment(spec("experiment-2"))
    registry.claim("experiment-2")
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE experiments SET heartbeat_at = ? WHERE experiment_id = ?",
            ("2000-01-01T00:00:00Z", "experiment-2"),
        )
    assert registry.recover_stale(timedelta(minutes=5)) == ["experiment-2"]
    assert registry.get("experiment-2")["failure_info"] == "stale-run-recovered"
    with pytest.raises(ExperimentError, match="budget"):
        registry.create_experiment(spec("experiment-3"))


def test_holdout_metrics_require_a_logged_event(tmp_path: Path) -> None:
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    registry.create_campaign("campaign-1", "Holdout", 1)
    with pytest.raises(HoldoutAccessError):
        registry.create_experiment(spec("holdout-1", ExperimentSplit.HOLDOUT))
    qualification: dict[str, object] = {
        "experiment_id": "candidate-1",
        "state": "qualified",
        "gates": [{"name": "return", "approved": True, "passed": True}],
    }
    qualification["report_fingerprint"] = fingerprint(qualification)
    report: dict[str, object] = {
        "schema_version": "qualification-evidence-v1",
        "manifest_id": "manifest-1",
        "manifest_fingerprint": "manifest-fingerprint-1",
        "proposal_id": "proposal-1",
        "proposal_fingerprint": "proposal-fingerprint-1",
        "campaign_id": "campaign-1",
        "candidate_id": "candidate-1",
        "strategy_id": "moving-average-trend",
        "candidate_specification": {
            "strategy_id": "moving-average-trend",
            "strategy_version": "1",
            "strategy_family": "trend",
            "parameters": {"window": 20},
            "cost_model_version": "conservative-bps-v1",
            "execution_model_version": "next-bar-v1",
            "dataset_id": "dataset-1",
            "dataset_fingerprint": "fingerprint-1",
            "universe_id": "liquid-etfs-v1",
            "universe_fingerprint": "universe-fingerprint-1",
            "validation_start": "2019-01-01T00:00:00Z",
            "validation_end": "2019-12-31T00:00:00Z",
        },
        "source_experiment_ids": ["validation-1"],
        "metrics": {"total_return": "0.1"},
        "qualification": qualification,
    }
    report["evidence_fingerprint"] = fingerprint(report)
    tampered = dict(report)
    tampered["metrics"] = {"total_return": "999"}
    with pytest.raises(HoldoutAccessError, match="fingerprint does not match"):
        registry._create_holdout_run_authorization(
            "authorization-tampered", tampered, "reviewer", "tampered evidence"
        )
    registry._create_holdout_run_authorization(
        "authorization-1", report, "reviewer", "one final holdout run"
    )
    holdout = replace(spec("holdout-1", ExperimentSplit.HOLDOUT), parent_candidate="candidate-1")
    registry.create_experiment(holdout, holdout_authorization_id="authorization-1")
    assert (
        registry.get_holdout_run_authorization("authorization-1")["consumed_by_experiment_id"]
        == "holdout-1"
    )
    with pytest.raises(HoldoutAccessError, match="unused stored authorization"):
        registry.create_experiment(
            replace(holdout, experiment_id="holdout-2"),
            holdout_authorization_id="authorization-1",
        )
    registry.claim("holdout-1")
    registry.complete("holdout-1", {"total_return": Decimal("0.2")})
    protected = registry.get("holdout-1")
    assert protected["metrics_json"] is None
    assert protected["holdout_metrics_protected"] is True
    registry.authorize_holdout("holdout-1", "event-1", "reviewer", "final qualification")
    with pytest.raises(HoldoutAccessError, match="access already exists"):
        registry.authorize_holdout("holdout-1", "event-2", "reviewer", "read again")
    revealed = registry.get("holdout-1", "event-1")
    assert revealed["metrics_json"] == {"total_return": "0.2"}
    with pytest.raises(HoldoutAccessError):
        registry.record_qualification("holdout-1", QualificationState.REJECTED, {}, "wrong-event")
    registry.record_qualification(
        "holdout-1",
        QualificationState.REJECTED,
        {"state": "rejected", "gates": [{"name": "drawdown", "approved": True, "passed": False}]},
        "event-1",
    )
    assert registry.get("holdout-1", "event-1")["qualification_state"] == "rejected"
