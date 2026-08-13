from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

import systematic_trading_lab.intraday_source_provenance as provenance
from systematic_trading_lab import cli
from systematic_trading_lab.backtesting import CostModel
from systematic_trading_lab.campaign_specs import (
    build_planned_intraday_experiments,
    load_intraday_research_campaign_plan,
)
from systematic_trading_lab.config import Settings
from systematic_trading_lab.datasets import DatasetService, intraday_fixture_request
from systematic_trading_lab.domain import OHLCVBar, Symbol, Timeframe, TradingMode
from systematic_trading_lab.experiment_runner import run_cataloged_intraday_experiment
from systematic_trading_lab.experiments import (
    ExperimentError,
    ExperimentRegistry,
    QualificationState,
    _planned_intraday_reservation,
)
from systematic_trading_lab.fingerprints import canonical_json, fingerprint
from systematic_trading_lab.intraday_campaigns import (
    INTRADAY_CAMPAIGN_V1_ID,
    INTRADAY_CAMPAIGN_V2_ID,
    INTRADAY_FOUNDATION_LOCK_SHA256,
    get_intraday_campaign_contract,
)
from systematic_trading_lab.intraday_qualification import _registered_report
from systematic_trading_lab.intraday_source_provenance import (
    IntradayExecutionBuildIdentity,
    IntradayExecutionSourceAssessment,
    IntradayExecutionSurfaceComparison,
    IntradayRuntimeEnvironmentIdentity,
)
from systematic_trading_lab.providers import IntradayFixtureProvider
from systematic_trading_lab.runtime_build import AttestationVerifierIdentity
from systematic_trading_lab.storage import StorageLayout

CAMPAIGN_ID = INTRADAY_CAMPAIGN_V2_ID
CAMPAIGN_CONTRACT = get_intraday_campaign_contract(CAMPAIGN_ID)
CAMPAIGN_SURFACE = provenance._load_reviewed_surface_manifest(CAMPAIGN_ID)
SOURCE_REVIEW_ID = "campaign-v2-source-review"


def _assessment(
    commit: str = "a" * 40, environment_marker: str = "1"
) -> IntradayExecutionSourceAssessment:
    components = CAMPAIGN_SURFACE.hashes
    surface = IntradayExecutionSurfaceComparison(
        foundation_commit=CAMPAIGN_CONTRACT.foundation_commit,
        surface_manifest_sha256=provenance._sha256(CAMPAIGN_SURFACE.raw),
        surface_manifest_fingerprint=fingerprint(CAMPAIGN_SURFACE.definition),
        reviewed_surface_fingerprint=fingerprint(components),
        observed_surface_fingerprint=fingerprint(components),
        reviewed_component_hashes=components,
        observed_component_hashes=components,
        mismatches=(),
        equivalent=True,
    )
    return IntradayExecutionSourceAssessment(
        campaign_id=CAMPAIGN_ID,
        plan_fingerprint=CAMPAIGN_CONTRACT.plan_fingerprint,
        build_identity=IntradayExecutionBuildIdentity(
            source_commit=commit,
            wheel_sha256="b" * 64,
            manifest_sha256="c" * 64,
            package_name="systematic-trading-lab",
            package_version="0.1.0",
            source_repository="firedvl/systematic-trading-lab",
            signer_workflow=".github/workflows/build-provenance.yml",
            attestation_verifier=AttestationVerifierIdentity(
                path="/usr/local/bin/gh", sha256="f" * 64
            ),
            distribution_record_sha256="d" * 64,
            source_files_fingerprint="e" * 64,
        ),
        environment_identity=IntradayRuntimeEnvironmentIdentity(
            uv_lock_sha256=INTRADAY_FOUNDATION_LOCK_SHA256,
            runtime_root="/runtime",
            pyvenv_config_sha256="0" * 64,
            python_executable="/runtime/bin/python",
            python_executable_chain=(("/runtime/bin/python", "file", environment_marker * 64),),
            python_executable_sha256=environment_marker * 64,
            base_prefix="/base-python",
            base_runtime_fingerprint="6" * 64,
            base_runtime_entry_count=1,
            site_packages_path="/runtime/lib/python3.12/site-packages",
            site_packages_fingerprint="7" * 64,
            site_packages_entry_count=1,
            sys_path=("/base-python/lib/python3.12",),
            python_implementation="CPython",
            python_version="3.12.13",
            python_cache_tag="cpython-312",
            python_flags="sys.flags()",
            platform="test-platform",
            meta_path=provenance._EXPECTED_META_PATH,
            path_hooks=provenance._DEFAULT_PATH_HOOKS,
            decimal_context=provenance._default_decimal_context(),
            timezone_source="tzdata:America/New_York",
            timezone_sha256="2" * 64,
            distributions=(
                (
                    "pyarrow",
                    "25.0.0",
                    "pyarrow-25.0.0-cp312-cp312-manylinux_x86_64.whl",
                    "3" * 64,
                    "4" * 64,
                    "5" * 64,
                ),
            ),
        ),
        surface_comparison=surface,
    )


def _mismatched_assessment() -> IntradayExecutionSourceAssessment:
    assessment = _assessment()
    observed = list(CAMPAIGN_SURFACE.hashes)
    component, _ = observed[0]
    observed[0] = (component, "0" * 64)
    surface = IntradayExecutionSurfaceComparison(
        foundation_commit=CAMPAIGN_CONTRACT.foundation_commit,
        surface_manifest_sha256=provenance._sha256(CAMPAIGN_SURFACE.raw),
        surface_manifest_fingerprint=fingerprint(CAMPAIGN_SURFACE.definition),
        reviewed_surface_fingerprint=fingerprint(CAMPAIGN_SURFACE.hashes),
        observed_surface_fingerprint=fingerprint(tuple(observed)),
        reviewed_component_hashes=CAMPAIGN_SURFACE.hashes,
        observed_component_hashes=tuple(observed),
        mismatches=(component,),
        equivalent=False,
    )
    return replace(assessment, surface_comparison=surface)


def _manifests() -> dict[str, dict[str, object]]:
    plan = load_intraday_research_campaign_plan(Path("config/research/intraday-campaign-v2.json"))
    result: dict[str, dict[str, object]] = {}
    for period in plan.periods:
        start = period.start_timestamp.isoformat().replace("+00:00", "Z")
        end = period.end_timestamp.isoformat().replace("+00:00", "Z")
        result[period.role] = {
            "identity": {
                "dataset_id": f"planned-{period.role}",
                "fingerprint": f"fingerprint-{period.role}",
            },
            "provider": "alpaca-historical-v2",
            "feed": "iex",
            "timeframe": "5m",
            "adjustment_policy": "provider-adjusted-all-v1",
            "calendar_policy": "XNYS-regular-session-bars-v1",
            "timestamp_policy": "bar-open-utc-v1",
            "requested_range": {"start": start, "end": end},
            "actual_range": {"start": start, "end": end},
            "symbols": [{"value": "SPY"}, {"value": "QQQ"}],
            "universe_id": "liquid-etfs-intraday-5m-v1",
            "universe_fingerprint": (
                "6ac4a8269f8e352536f52ddc0a3000e0b39c5551c33c03959c20a640cfddeca9"
            ),
        }
    return result


def _registry(tmp_path: Path, *, bind: bool = True) -> ExperimentRegistry:
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    plan = load_intraday_research_campaign_plan(Path("config/research/intraday-campaign-v2.json"))
    registry.create_planned_intraday_campaign(plan.payload)
    if bind:
        registry.bind_planned_intraday_experiments(
            build_planned_intraday_experiments(plan, _manifests())
        )
    return registry


def _artifacts(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    return (
        tmp_path / "build.whl",
        tmp_path / "manifest.json",
        tmp_path / "uv.lock",
        tmp_path / "dependency-wheelhouse",
    )


def _record_review(
    registry: ExperimentRegistry,
    tmp_path: Path,
    assessment: IntradayExecutionSourceAssessment,
) -> dict[str, object]:
    wheel, manifest, lockfile, wheelhouse = _artifacts(tmp_path)
    return registry.record_intraday_execution_source_review(
        SOURCE_REVIEW_ID,
        wheel,
        manifest,
        lockfile,
        wheelhouse,
        assessment.assessment_fingerprint,
        "independent-reviewer",
        "reviewed attested Campaign V2 execution build",
        campaign_id=CAMPAIGN_ID,
    )


def test_source_review_requires_explicit_fingerprint_and_is_immutable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path, bind=False)
    assessment = _assessment()
    monkeypatch.setattr(
        provenance, "assess_intraday_execution_source", lambda *args, **kwargs: assessment
    )
    wheel, manifest, lockfile, wheelhouse = _artifacts(tmp_path)

    with pytest.raises(ExperimentError, match="explicitly reviewed assessment"):
        registry.record_intraday_execution_source_review(
            SOURCE_REVIEW_ID,
            wheel,
            manifest,
            lockfile,
            wheelhouse,
            "f" * 64,
            "independent-reviewer",
            "reviewed build",
            campaign_id=CAMPAIGN_ID,
        )
    with pytest.raises(ExperimentError, match="review not found"):
        registry.get_intraday_execution_source_review(SOURCE_REVIEW_ID)

    review = _record_review(registry, tmp_path, assessment)
    assert review["foundation_commit"] == CAMPAIGN_CONTRACT.foundation_commit
    assert review["execution_commit"] == "a" * 40
    assert _record_review(registry, tmp_path, assessment) == review
    with pytest.raises(ExperimentError, match="already has a different"):
        registry.record_intraday_execution_source_review(
            "replacement-review",
            wheel,
            manifest,
            lockfile,
            wheelhouse,
            assessment.assessment_fingerprint,
            "independent-reviewer",
            "reviewed build",
            campaign_id=CAMPAIGN_ID,
        )
    with sqlite3.connect(registry.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE intraday_execution_source_reviews SET review_id = 'changed'")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM intraday_execution_source_reviews")


def test_campaign_v1_evidence_remains_readable_immutable_and_closed(tmp_path: Path) -> None:
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    v1 = get_intraday_campaign_contract(INTRADAY_CAMPAIGN_V1_ID)
    v1_plan = load_intraday_research_campaign_plan(
        Path("config/research/intraday-campaign-v1.json")
    )
    unsigned: dict[str, object] = {
        "schema_version": "intraday-execution-source-review-v1",
        "review_id": "historical-v1-review",
        "campaign_id": INTRADAY_CAMPAIGN_V1_ID,
        "plan_fingerprint": v1.plan_fingerprint,
        "foundation_commit": v1.foundation_commit,
        "execution_commit": "a" * 40,
        "assessment": {"historical": True},
        "assessment_fingerprint": "b" * 64,
        "build_identity_fingerprint": "c" * 64,
        "environment_identity_fingerprint": "d" * 64,
        "surface_comparison_fingerprint": "e" * 64,
        "reviewer": "historical-reviewer",
        "reason": "recorded before the acquisition defect",
        "reviewed_at": "2026-08-13T00:00:00Z",
    }
    review = {**unsigned, "review_fingerprint": fingerprint(unsigned)}
    with sqlite3.connect(registry.path) as connection:
        connection.execute(
            "INSERT INTO campaigns VALUES (?, ?, ?, ?, ?)",
            (
                v1_plan.campaign_id,
                v1_plan.name,
                "2026-08-12T00:00:00Z",
                "sealed",
                v1_plan.search_budget,
            ),
        )
        connection.execute(
            "INSERT INTO campaign_plans VALUES (?, ?, ?, ?)",
            (
                v1_plan.campaign_id,
                canonical_json(v1_plan.payload),
                v1_plan.plan_fingerprint,
                "2026-08-12T00:00:00Z",
            ),
        )
        for index, reservation in enumerate(v1_plan.candidates):
            status = "running" if index == 1 else "pending"
            connection.execute(
                """
                INSERT INTO experiments
                (experiment_id, campaign_id, spec_json, split, status, qualification_state,
                 created_at, heartbeat_at, campaign_plan_fingerprint)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reservation.experiment_id,
                    v1_plan.campaign_id,
                    canonical_json(_planned_intraday_reservation(v1_plan, reservation)),
                    reservation.split.value,
                    status,
                    "not-evaluated",
                    "2026-08-12T00:00:00Z",
                    "2026-08-12T00:00:00+00:00" if status == "running" else None,
                    v1_plan.plan_fingerprint,
                ),
            )
        connection.execute(
            "INSERT INTO intraday_execution_source_reviews VALUES (?, ?, ?, ?)",
            (
                review["review_id"],
                review["campaign_id"],
                canonical_json(review),
                review["review_fingerprint"],
            ),
        )

    def v1_state() -> tuple[list[tuple[object, ...]], ...]:
        with sqlite3.connect(registry.path) as connection:
            return tuple(
                connection.execute(
                    f"SELECT * FROM {table} ORDER BY 1"  # noqa: S608 - fixed test table names
                ).fetchall()
                for table in (
                    "campaigns",
                    "campaign_plans",
                    "experiments",
                    "intraday_execution_source_reviews",
                )
            )

    before = v1_state()
    pending_id = v1_plan.candidates[0].experiment_id
    running_id = v1_plan.candidates[1].experiment_id
    assert registry.get_intraday_execution_source_review("historical-v1-review") == review
    assert registry.get_campaign(v1_plan.campaign_id)["status"] == "sealed"
    assert (
        registry.get_campaign_plan(v1_plan.campaign_id)["plan_fingerprint"] == v1.plan_fingerprint
    )
    with pytest.raises(ExperimentError, match="aborted and remains read-only"):
        registry.create_planned_intraday_campaign(v1_plan.payload)
    with pytest.raises(ExperimentError, match="aborted and remains read-only"):
        registry.record_intraday_execution_source_review(
            "replacement-v1-review",
            *_artifacts(tmp_path),
            "f" * 64,
            "reviewer",
            "replacement",
            campaign_id=INTRADAY_CAMPAIGN_V1_ID,
        )
    with pytest.raises(ExperimentError, match="cannot be failed"):
        registry.fail(pending_id, "must remain historical evidence")
    with pytest.raises(ExperimentError, match="running experiment not found"):
        registry.heartbeat(running_id)
    assert registry.recover_stale(timedelta(minutes=5)) == []
    with pytest.raises(ExperimentError, match="only completed experiments"):
        registry.record_qualification(
            pending_id,
            QualificationState.REJECTED,
            {"state": "rejected", "gates": [{"approved": True, "passed": False}]},
        )
    bound_specs = build_planned_intraday_experiments(v1_plan, _manifests())
    with pytest.raises(ExperimentError, match="aborted and remains read-only"):
        registry.bind_planned_intraday_experiments(bound_specs)
    with pytest.raises(ExperimentError, match="aborted and remains read-only"):
        run_cataloged_intraday_experiment(
            registry,
            DatasetService(StorageLayout(tmp_path)),
            bound_specs[0],
            StorageLayout(tmp_path).reports,
            pre_registered=True,
        )
    with sqlite3.connect(registry.path) as connection:
        for statement in (
            "UPDATE campaigns SET status = 'changed' WHERE campaign_id = 'intraday-research-v1'",
            "DELETE FROM campaigns WHERE campaign_id = 'intraday-research-v1'",
            "UPDATE campaign_plans SET sealed_at = 'changed' "
            "WHERE campaign_id = 'intraday-research-v1'",
            "DELETE FROM campaign_plans WHERE campaign_id = 'intraday-research-v1'",
            "UPDATE experiments SET status = 'failed' WHERE campaign_id = 'intraday-research-v1'",
            "DELETE FROM experiments WHERE campaign_id = 'intraday-research-v1'",
            "DELETE FROM intraday_execution_source_reviews",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                connection.execute(statement)
    assert v1_state() == before


def test_surface_mismatch_requires_a_new_campaign_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path, bind=False)
    assessment = _mismatched_assessment()
    monkeypatch.setattr(
        provenance, "assess_intraday_execution_source", lambda *args, **kwargs: assessment
    )

    with pytest.raises(ExperimentError, match="new intraday campaign version"):
        _record_review(registry, tmp_path, assessment)

    assert {record["status"] for record in registry.list(CAMPAIGN_ID)} == {"pending"}


def test_cli_assesses_and_records_only_the_explicit_attested_build(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment = _assessment()
    monkeypatch.setattr(
        provenance, "assess_intraday_execution_source", lambda *args, **kwargs: assessment
    )
    monkeypatch.setattr(cli, "assess_intraday_execution_source", lambda *args, **kwargs: assessment)
    settings = Settings(TradingMode.OFFLINE, tmp_path)
    assert (
        cli.run(
            cli.parser().parse_args(
                [
                    "experiment",
                    "plan-intraday",
                    "--spec",
                    "config/research/intraday-campaign-v2.json",
                ]
            ),
            settings,
        )
        == 0
    )
    capsys.readouterr()
    wheel, manifest, lockfile, wheelhouse = _artifacts(tmp_path)
    common = [
        "--campaign",
        CAMPAIGN_ID,
        "--wheel",
        str(wheel),
        "--build-manifest",
        str(manifest),
        "--lockfile",
        str(lockfile),
        "--dependency-wheelhouse",
        str(wheelhouse),
    ]
    assert (
        cli.run(
            cli.parser().parse_args(["experiment", "assess-intraday-source", *common]),
            settings,
        )
        == 0
    )
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["assessment_fingerprint"] == assessment.assessment_fingerprint
    assert not inspected["broker_write_authority"]
    assert (
        cli.run(
            cli.parser().parse_args(
                [
                    "experiment",
                    "record-intraday-source",
                    SOURCE_REVIEW_ID,
                    *common,
                    "--assessment-fingerprint",
                    assessment.assessment_fingerprint,
                    "--reviewer",
                    "independent-reviewer",
                    "--reason",
                    "reviewed attested Campaign V2 execution build",
                ]
            ),
            settings,
        )
        == 0
    )
    recorded = json.loads(capsys.readouterr().out)
    assert recorded["review"]["execution_commit"] == "a" * 40
    assert not recorded["protected_holdout_authority"]
    registry = ExperimentRegistry(StorageLayout(tmp_path).experiments)
    assert {record["status"] for record in registry.list(CAMPAIGN_ID)} == {"pending"}


def test_campaign_v2_rejects_caller_controlled_computation_inputs(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    datasets = DatasetService(StorageLayout(tmp_path))
    spec = registry.get_planned_intraday_spec("intraday-research-v2-cash-training-base")

    with pytest.raises(ExperimentError, match="initial cash differs"):
        run_cataloged_intraday_experiment(
            registry,
            datasets,
            spec,
            StorageLayout(tmp_path).reports,
            initial_cash=Decimal("1"),
            pre_registered=True,
        )

    class SubstituteCash(Decimal):
        def __new__(cls) -> SubstituteCash:
            return super().__new__(cls, "1")

        def __ne__(self, other: object) -> bool:
            return False

    with pytest.raises(ExperimentError, match="initial cash differs"):
        run_cataloged_intraday_experiment(
            registry,
            datasets,
            spec,
            StorageLayout(tmp_path).reports,
            initial_cash=SubstituteCash(),
            pre_registered=True,
        )

    class SubstituteCost(CostModel):
        def commission(self, notional: Decimal) -> Decimal:
            return Decimal("0")

    with pytest.raises(ExperimentError, match="costs come from"):
        run_cataloged_intraday_experiment(
            registry,
            datasets,
            spec,
            StorageLayout(tmp_path).reports,
            cost_model=SubstituteCost(
                spec.cost_model_version,
                spec.slippage_bps,
                spec.commission_bps,
            ),
            pre_registered=True,
        )

    class InjectedDatasetService(DatasetService):
        pass

    with pytest.raises(ExperimentError, match="concrete storage services"):
        run_cataloged_intraday_experiment(
            registry,
            InjectedDatasetService(StorageLayout(tmp_path)),
            spec,
            StorageLayout(tmp_path).reports,
            pre_registered=True,
        )

    assert registry.get(spec.experiment_id)["status"] == "pending"


def test_fresh_source_mismatch_fails_before_atomic_binding_and_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path)
    reviewed = _assessment()
    monkeypatch.setattr(
        provenance, "assess_intraday_execution_source", lambda *args, **kwargs: reviewed
    )
    _record_review(registry, tmp_path, reviewed)
    observed = replace(
        reviewed, environment_identity=_assessment(environment_marker="4").environment_identity
    )
    monkeypatch.setattr(
        provenance, "assess_intraday_execution_source", lambda *args, **kwargs: observed
    )
    experiment_id = "intraday-research-v2-cash-training-base"
    spec = registry.get_planned_intraday_spec(experiment_id)

    with pytest.raises(ExperimentError, match="differs from its recorded"):
        registry._claim_planned_intraday(spec, SOURCE_REVIEW_ID, *_artifacts(tmp_path))

    assert registry.get(experiment_id)["status"] == "pending"
    with pytest.raises(ExperimentError, match="binding not found"):
        registry.get_intraday_execution_source_binding(experiment_id)


def test_source_binding_and_claim_commit_or_rollback_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path)
    assessment = _assessment()
    monkeypatch.setattr(
        provenance, "assess_intraday_execution_source", lambda *args, **kwargs: assessment
    )
    _record_review(registry, tmp_path, assessment)
    experiment_id = "intraday-research-v2-cash-training-base"
    spec = registry.get_planned_intraday_spec(experiment_id)
    binding = registry._claim_planned_intraday(spec, SOURCE_REVIEW_ID, *_artifacts(tmp_path))

    assert binding is not None
    assert binding["execution_commit"] == "a" * 40
    assert registry.get(experiment_id)["status"] == "running"
    assert registry.get_intraday_execution_source_binding(experiment_id) == binding
    with (
        sqlite3.connect(registry.path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="immutable"),
    ):
        connection.execute("DELETE FROM intraday_experiment_execution_sources")

    changed = _assessment(environment_marker="4")
    monkeypatch.setattr(
        provenance, "assess_intraday_execution_source", lambda *args, **kwargs: changed
    )
    with pytest.raises(ExperimentError, match="new campaign version"):
        registry.verify_intraday_execution_source_review(SOURCE_REVIEW_ID, *_artifacts(tmp_path))
    monkeypatch.setattr(
        provenance, "assess_intraday_execution_source", lambda *args, **kwargs: assessment
    )

    rollback_id = "intraday-research-v2-cash-training-increased-cost"
    rollback_spec = registry.get_planned_intraday_spec(rollback_id)
    with sqlite3.connect(registry.path) as connection:
        connection.execute(
            f"""
            CREATE TRIGGER reject_source_bound_claim
            BEFORE UPDATE OF status ON experiments
            WHEN NEW.experiment_id = '{rollback_id}' AND NEW.status = 'running'
            BEGIN SELECT RAISE(ABORT, 'forced source-bound claim failure'); END
            """
        )
    with pytest.raises(ExperimentError, match="could not be bound"):
        registry._claim_planned_intraday(rollback_spec, SOURCE_REVIEW_ID, *_artifacts(tmp_path))
    assert registry.get(rollback_id)["status"] == "pending"
    with pytest.raises(ExperimentError, match="binding not found"):
        registry.get_intraday_execution_source_binding(rollback_id)


def test_matching_build_runs_and_report_binds_foundation_and_actual_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path)
    assessment = _assessment()
    calls: list[str] = []

    def assess(*args: object, **kwargs: object) -> IntradayExecutionSourceAssessment:
        calls.append("assess")
        return assessment

    monkeypatch.setattr(provenance, "assess_intraday_execution_source", assess)
    _record_review(registry, tmp_path, assessment)
    calls.clear()
    dataset_service = DatasetService(StorageLayout(tmp_path))
    spec = registry.get_planned_intraday_spec("intraday-research-v2-cash-training-base")
    manifest = _manifests()["training"]
    fixture_records = IntradayFixtureProvider().fetch(
        (Symbol("SPY"), Symbol("QQQ")),
        Timeframe.FIVE_MINUTES,
        intraday_fixture_request(),
    )
    bars = tuple(OHLCVBar.from_record(record) for record in fixture_records)

    def validate(dataset_id: str) -> dict[str, object]:
        calls.append("validate")
        return {"valid": True}

    monkeypatch.setattr(dataset_service, "validate", validate)
    monkeypatch.setattr(dataset_service, "describe", lambda dataset_id: manifest)
    monkeypatch.setattr(dataset_service, "load_bars_range", lambda *args, **kwargs: bars)

    result = run_cataloged_intraday_experiment(
        registry,
        dataset_service,
        spec,
        StorageLayout(tmp_path).reports,
        pre_registered=True,
        execution_source_review_id=SOURCE_REVIEW_ID,
        execution_source_wheel=_artifacts(tmp_path)[0],
        execution_source_manifest=_artifacts(tmp_path)[1],
        execution_source_lockfile=_artifacts(tmp_path)[2],
        execution_source_dependency_wheelhouse=_artifacts(tmp_path)[3],
    )

    assert calls == ["assess", "validate", "assess"]
    assert result.strategy_id == "intraday-cash"
    record = registry.get(spec.experiment_id)
    assert record["status"] == "completed"
    report_path = Path(cast(list[str], record["artifact_locations_json"])[0])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["provenance"]["code_commit"] == CAMPAIGN_CONTRACT.foundation_commit
    source = report["execution_source_provenance"]
    assert source["review"]["execution_commit"] == "a" * 40
    assert source["binding"]["execution_commit"] == "a" * 40
    _registered_report(registry, spec.experiment_id)

    source["binding"]["execution_commit"] = "b" * 40
    unsigned = dict(report)
    unsigned.pop("report_fingerprint")
    report["report_fingerprint"] = fingerprint(unsigned)
    report_path.write_text(canonical_json(report) + "\n", encoding="utf-8")
    with sqlite3.connect(registry.path) as connection:
        connection.execute(
            "UPDATE experiments SET artifact_hashes_json = ? WHERE experiment_id = ?",
            (canonical_json([report["report_fingerprint"]]), spec.experiment_id),
        )
    with pytest.raises(ValueError, match="execution source provenance differs"):
        _registered_report(registry, spec.experiment_id)

    report.pop("execution_source_provenance")
    unsigned = dict(report)
    unsigned.pop("report_fingerprint")
    report["report_fingerprint"] = fingerprint(unsigned)
    report_path.write_text(canonical_json(report) + "\n", encoding="utf-8")
    with sqlite3.connect(registry.path) as connection:
        connection.execute(
            "UPDATE experiments SET artifact_hashes_json = ? WHERE experiment_id = ?",
            (canonical_json([report["report_fingerprint"]]), spec.experiment_id),
        )
    with pytest.raises(ValueError, match="lacks execution source provenance"):
        _registered_report(registry, spec.experiment_id)


def test_post_claim_failure_retains_source_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path)
    assessment = _assessment()
    monkeypatch.setattr(
        provenance, "assess_intraday_execution_source", lambda *args, **kwargs: assessment
    )
    _record_review(registry, tmp_path, assessment)
    datasets = DatasetService(StorageLayout(tmp_path))
    spec = registry.get_planned_intraday_spec("intraday-research-v2-cash-training-base")
    monkeypatch.setattr(
        datasets,
        "validate",
        lambda dataset_id: (_ for _ in ()).throw(ValueError("downstream failure")),
    )

    with pytest.raises(ValueError, match="downstream failure"):
        run_cataloged_intraday_experiment(
            registry,
            datasets,
            spec,
            StorageLayout(tmp_path).reports,
            pre_registered=True,
            execution_source_review_id=SOURCE_REVIEW_ID,
            execution_source_wheel=_artifacts(tmp_path)[0],
            execution_source_manifest=_artifacts(tmp_path)[1],
            execution_source_lockfile=_artifacts(tmp_path)[2],
            execution_source_dependency_wheelhouse=_artifacts(tmp_path)[3],
        )

    assert registry.get(spec.experiment_id)["status"] == "failed"
    assert (
        registry.get_intraday_execution_source_binding(spec.experiment_id)["execution_commit"]
        == "a" * 40
    )
