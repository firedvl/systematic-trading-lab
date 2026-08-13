from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

import systematic_trading_lab.intraday_v3_runner as runner
from systematic_trading_lab.experiments import ExperimentError, ExperimentSplit
from systematic_trading_lab.intraday_v3 import (
    V3_AUTHORITY_POLICY,
    V3_DIAGNOSTIC_POLICY,
    V3_EARLIEST_FILL_SEMANTICS,
    V3_EXECUTION_MODEL,
    V3_PERIODIC_REBALANCE_POLICY,
    V3_QUEUE_POLICY,
    V3_SESSION_POLICY,
    IntradayV3ExperimentSpec,
    V3DiagnosticReplay,
)
from systematic_trading_lab.intraday_v3_registry import IntradayV3Claim
from systematic_trading_lab.intraday_v3_runner import (
    IntradayV3SourceArtifacts,
    run_cataloged_intraday_v3_experiment,
)
from systematic_trading_lab.storage import StorageLayout


def _spec() -> IntradayV3ExperimentSpec:
    return IntradayV3ExperimentSpec(
        experiment_id="v3-candidate-1",
        campaign_id="intraday-research-v3",
        search_budget=60,
        candidate_ordinal=1,
        strategy_id="intraday-30-minute-momentum",
        strategy_version="1",
        strategy_family="intraday-directional-momentum",
        code_commit="a" * 40,
        source_foundation_commit="b" * 40,
        campaign_plan_fingerprint="c" * 64,
        qualification_binding_id="intraday-v3-qualification-binding-v1",
        qualification_binding_fingerprint="d" * 64,
        period_role="training",
        variant_role="base",
        dataset_id="e" * 64,
        dataset_fingerprint="f" * 64,
        universe_id="liquid-etfs-intraday-5m-v1",
        universe_fingerprint="1" * 64,
        parameters={"lookback": 6},
        timeframe="5m",
        session_policy_version=V3_SESSION_POLICY,
        bar_timestamp_semantics_version="bar-open-utc-v1",
        session_return_policy_version="XNYS-session-close-equity-v1",
        benchmark_policy_version="cash-and-continuous-underlying-v1",
        cost_model_version="conservative-bps-v1",
        slippage_bps=Decimal("5"),
        commission_bps=Decimal("1"),
        execution_model_version=V3_EXECUTION_MODEL,
        earliest_fill_semantics=V3_EARLIEST_FILL_SEMANTICS,
        decision_queue_policy_version=V3_QUEUE_POLICY,
        execution_delay_bars=1,
        periodic_rebalance_policy_version=V3_PERIODIC_REBALANCE_POLICY,
        diagnostic_policy_version=V3_DIAGNOSTIC_POLICY,
        authority_policy_version=V3_AUTHORITY_POLICY,
        split=ExperimentSplit.TRAINING,
        start_timestamp=datetime(2025, 7, 1, 13, 30, tzinfo=UTC),
        end_timestamp=datetime(2025, 7, 1, 19, 55, tzinfo=UTC),
        random_seed=0,
        creation_reason="sealed base candidate",
    )


def _artifacts(tmp_path: Path) -> IntradayV3SourceArtifacts:
    return IntradayV3SourceArtifacts(
        tmp_path / "wheel.whl",
        tmp_path / "build.json",
        tmp_path / "surface.json",
        tmp_path / "uv.lock",
        tmp_path / "wheelhouse",
    )


class _Registry:
    instances: list[_Registry] = []

    def __init__(self, path: Path) -> None:
        self.path = path
        self.status = "pending"
        self.assessments: list[object] = []
        self.completed: tuple[object, ...] | None = None
        self.failure: str | None = None
        self.heartbeats = 0
        self.__class__.instances.append(self)

    def bind_source_preassessment(self, assessment: object) -> object:
        self.assessments.append(assessment)
        return assessment

    def claim(self, experiment_id: str, assessment: object) -> IntradayV3Claim:
        assert experiment_id == "v3-candidate-1"
        self.status = "running"
        return IntradayV3Claim(_spec(), "a" * 64)

    def verify_current_source(
        self, experiment_id: str, claim_token: str, assessment: object
    ) -> None:
        assert experiment_id == "v3-candidate-1"
        assert claim_token == "a" * 64

    def heartbeat(self, experiment_id: str, claim_token: str) -> None:
        assert experiment_id == "v3-candidate-1"
        assert claim_token == "a" * 64
        self.heartbeats += 1

    def get(self, experiment_id: str) -> dict[str, object]:
        if experiment_id != "v3-candidate-1":
            raise KeyError(experiment_id)
        return {
            "status": self.status,
            "execution_source_provenance": {"review": {}, "binding": {}},
        }

    def publish_report(self, *values: object) -> None:
        self.status = "completed"
        self.completed = values

    def fail(self, experiment_id: str, claim_token: str, reason: str) -> bool:
        self.status = "failed"
        self.failure = reason
        return True


class _Datasets:
    instances: list[_Datasets] = []

    def __init__(self, layout: StorageLayout) -> None:
        self.valid = True
        self.loaded = False
        self.__class__.instances.append(self)

    def validate(self, dataset_id: str) -> dict[str, object]:
        assert dataset_id == _spec().dataset_id
        return {"valid": self.valid}

    def load_bars_range(
        self, dataset_id: str, requested: object, **identity: object
    ) -> tuple[str, ...]:
        self.loaded = True
        spec = _spec()
        assert dataset_id == spec.dataset_id
        assert identity == {
            "expected_fingerprint": spec.dataset_fingerprint,
            "expected_universe_id": spec.universe_id,
            "expected_universe_fingerprint": spec.universe_fingerprint,
        }
        return ("stored-bars",)


def _patch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[object]:
    _Registry.instances.clear()
    _Datasets.instances.clear()
    checks: list[object] = []
    monkeypatch.setattr(runner, "IntradayV3Registry", _Registry)
    monkeypatch.setattr(runner, "DatasetService", _Datasets)

    def assess(*args: object) -> object:
        checks.append("source")
        return {"assessment": len(checks)}

    monkeypatch.setattr(runner, "assess_intraday_v3_source_preassessment", assess)
    replay = cast(V3DiagnosticReplay, object())
    monkeypatch.setattr(runner, "run_v3_diagnostic", lambda spec, bars: replay)
    monkeypatch.setattr(
        runner,
        "build_v3_diagnostic_report",
        lambda spec, value, bars: {
            "report_fingerprint": "old",
            "realistic": {"metrics": {"total_return": "0.1"}},
        },
    )
    monkeypatch.setattr(
        runner,
        "bind_intraday_execution_source",
        lambda report, evidence: {**report, "report_fingerprint": "final"},
    )
    checks.append(replay)
    return checks


def test_runner_has_no_research_override_route_and_uses_stored_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checks = _patch(monkeypatch, tmp_path)

    result = run_cataloged_intraday_v3_experiment(
        "v3-candidate-1", StorageLayout(tmp_path), _artifacts(tmp_path)
    )

    assert list(inspect.signature(run_cataloged_intraday_v3_experiment).parameters) == [
        "experiment_id",
        "layout",
        "source_artifacts",
    ]
    assert result is checks[0]
    assert checks.count("source") == 2
    assert _Datasets.instances[0].loaded
    assert _Registry.instances[0].heartbeats == 3
    completed = _Registry.instances[0].completed
    assert completed is not None
    assert completed[1:] == (
        "a" * 64,
        tmp_path / "reports" / f"{_spec().configuration_fingerprint}.json",
        {
            "report_fingerprint": "final",
            "realistic": {"metrics": {"total_return": "0.1"}},
        },
    )


def test_source_drift_before_publication_durably_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(monkeypatch, tmp_path)

    def drift(self: _Registry, experiment_id: str, claim_token: str, assessment: object) -> None:
        raise ValueError("source drift")

    monkeypatch.setattr(_Registry, "verify_current_source", drift)
    with pytest.raises(ValueError, match="source drift"):
        run_cataloged_intraday_v3_experiment(
            "v3-candidate-1", StorageLayout(tmp_path), _artifacts(tmp_path)
        )
    assert _Registry.instances[0].status == "failed"
    assert _Registry.instances[0].failure == "controlled-run-error:ValueError"


def test_full_dataset_validation_precedes_range_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(monkeypatch, tmp_path)
    original = _Datasets.validate

    def invalid(self: _Datasets, dataset_id: str) -> dict[str, object]:
        original(self, dataset_id)
        return {"valid": False}

    monkeypatch.setattr(_Datasets, "validate", invalid)
    with pytest.raises(ValueError, match="integrity"):
        run_cataloged_intraday_v3_experiment(
            "v3-candidate-1", StorageLayout(tmp_path), _artifacts(tmp_path)
        )
    assert not _Datasets.instances[0].loaded
    assert _Registry.instances[0].status == "failed"


def test_unknown_candidate_source_failure_creates_no_lifecycle_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(monkeypatch, tmp_path)
    monkeypatch.setattr(
        runner,
        "assess_intraday_v3_source_preassessment",
        lambda *args: (_ for _ in ()).throw(ValueError("missing attestation")),
    )
    with pytest.raises(ValueError, match="missing attestation"):
        run_cataloged_intraday_v3_experiment(
            "unknown", StorageLayout(tmp_path), _artifacts(tmp_path)
        )
    assert _Registry.instances[0].failure is None


def test_preclaim_source_failure_leaves_known_reservation_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(monkeypatch, tmp_path)
    monkeypatch.setattr(
        runner,
        "assess_intraday_v3_source_preassessment",
        lambda *args: (_ for _ in ()).throw(ValueError("missing attestation")),
    )

    with pytest.raises(ValueError, match="missing attestation"):
        run_cataloged_intraday_v3_experiment(
            "v3-candidate-1", StorageLayout(tmp_path), _artifacts(tmp_path)
        )
    assert _Registry.instances[0].status == "pending"
    assert _Registry.instances[0].failure is None


def test_duplicate_invocation_cannot_fail_another_runners_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(monkeypatch, tmp_path)

    def duplicate(self: _Registry, experiment_id: str, assessment: object) -> IntradayV3Claim:
        self.status = "running"
        raise ExperimentError("candidate already claimed")

    monkeypatch.setattr(_Registry, "claim", duplicate)
    with pytest.raises(ExperimentError, match="already claimed"):
        run_cataloged_intraday_v3_experiment(
            "v3-candidate-1", StorageLayout(tmp_path), _artifacts(tmp_path)
        )
    assert _Registry.instances[0].status == "running"
    assert _Registry.instances[0].failure is None
