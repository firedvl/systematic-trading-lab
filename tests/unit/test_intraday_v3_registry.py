from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

import systematic_trading_lab.intraday_v3_registry as registry_module
from systematic_trading_lab.datasets import _version_key
from systematic_trading_lab.domain import AdjustmentPolicy, Symbol, Timeframe, TimestampRange
from systematic_trading_lab.fingerprints import canonical_json, canonicalize, fingerprint
from systematic_trading_lab.intraday_source_provenance import write_intraday_execution_report
from systematic_trading_lab.intraday_v3_campaign import (
    IntradayV3CampaignPlan,
    load_intraday_v3_campaign_plan,
)
from systematic_trading_lab.intraday_v3_freshness import IntradayV3PublicationSeal
from systematic_trading_lab.intraday_v3_registry import (
    IntradayV3Registry,
    IntradayV3RegistryError,
)
from systematic_trading_lab.intraday_v3_source_provenance import IntradayV3SourceAssessment
from systematic_trading_lab.runtime_build import AttestationVerifierIdentity
from systematic_trading_lab.storage import StorageLayout

_INVENTORY = Path("config/research/intraday-known-exposures-v1.json")
_SELECTION = Path("config/research/intraday-v3-period-selection-v2.json")
_PLAN = Path("config/research/intraday-campaign-v3.json")
_BINDING = Path("config/research/intraday-v3-qualification-binding-v1.json")


def _plan() -> IntradayV3CampaignPlan:
    return load_intraday_v3_campaign_plan(_PLAN)


def _seal(plan: IntradayV3CampaignPlan, path: Path) -> IntradayV3PublicationSeal:
    raw = (
        json.dumps(
            {"source_commit": "a" * 40, "seal_fingerprint": "e" * 64},
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    path.write_text(raw, encoding="utf-8")
    first = next(period for period in plan.periods if period.role == "validation-a")
    prospective = plan.payload["prospective_freshness"]
    qualification = plan.payload["qualification_binding"]
    assert isinstance(prospective, Mapping) and isinstance(qualification, Mapping)
    return IntradayV3PublicationSeal(
        source_commit="a" * 40,
        inventory_fingerprint=str(prospective["inventory_fingerprint"]),
        selection_fingerprint=str(prospective["period_selection_fingerprint"]),
        plan_fingerprint=plan.plan_fingerprint,
        qualification_binding_fingerprint=str(qualification["fingerprint"]),
        first_validation_bar=first.start_timestamp,
        witnessed_at=first.start_timestamp - timedelta(seconds=1),
        seal_fingerprint="e" * 64,
        seal_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        verifier=AttestationVerifierIdentity(path="/verified/gh", sha256="1" * 64),
    )


def _materialize(
    registry: IntradayV3Registry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[IntradayV3CampaignPlan, IntradayV3PublicationSeal, Path]:
    plan = _plan()
    path = tmp_path / "intraday-v3-preregistration-seal.json"
    seal = _seal(plan, path)
    monkeypatch.setattr(registry_module, "verify_intraday_v3_publication_seal", lambda *args: seal)
    registry.materialize(path, _INVENTORY, _SELECTION, _PLAN, _BINDING)
    return plan, seal, path


def _manifests(plan: IntradayV3CampaignPlan) -> dict[str, dict[str, object]]:
    manifests: dict[str, dict[str, object]] = {}
    for index, period in enumerate(plan.periods):
        data_fingerprint = f"{index + 4:x}" * 64
        raw_fingerprint = "9" * 64
        dataset_id = fingerprint(
            _version_key(
                "alpaca-historical-v2",
                (Symbol("SPY"), Symbol("QQQ")),
                Timeframe.FIVE_MINUTES,
                TimestampRange(period.start_timestamp, period.end_timestamp),
                AdjustmentPolicy.PROVIDER_ADJUSTED_ALL,
                "ohlcv-normalization-v1",
                "ohlcv-v1",
                "XNYS-regular-session-bars-v1",
                "bar-open-utc-v1",
                "liquid-etfs-intraday-5m-v1",
                "6ac4a8269f8e352536f52ddc0a3000e0b39c5551c33c03959c20a640cfddeca9",
                "iex",
                data_fingerprint,
                raw_fingerprint,
            )
        )
        manifests[period.role] = {
            "identity": {"dataset_id": dataset_id, "fingerprint": data_fingerprint},
            "provider": "alpaca-historical-v2",
            "symbols": [{"value": "SPY"}, {"value": "QQQ"}],
            "timeframe": "5m",
            "requested_range": {
                "start": period.start_timestamp.isoformat().replace("+00:00", "Z"),
                "end": period.end_timestamp.isoformat().replace("+00:00", "Z"),
            },
            "actual_range": {
                "start": period.start_timestamp.isoformat().replace("+00:00", "Z"),
                "end": period.end_timestamp.isoformat().replace("+00:00", "Z"),
            },
            "retrieval_timestamp": datetime(2027, 4, 16, tzinfo=UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "raw_artifact_hashes": [raw_fingerprint],
            "normalization_version": "ohlcv-normalization-v1",
            "schema_version": "ohlcv-v1",
            "adjustment_policy": "provider-adjusted-all-v1",
            "calendar_policy": "XNYS-regular-session-bars-v1",
            "timestamp_policy": "bar-open-utc-v1",
            "universe_id": "liquid-etfs-intraday-5m-v1",
            "universe_fingerprint": (
                "6ac4a8269f8e352536f52ddc0a3000e0b39c5551c33c03959c20a640cfddeca9"
            ),
            "validation": {
                "errors": [],
                "missing_intervals": [],
                "duplicate_intervals": [],
                "conflicts": [],
                "quarantined_records": 0,
            },
            "feed": "iex",
            "parent_dataset_id": None,
        }
    return manifests


class _Datasets:
    manifests: dict[str, dict[str, object]] = {}
    invalid: set[str] = set()
    validated: list[str] = []

    def __init__(self, layout: StorageLayout) -> None:
        self.layout = layout

    def describe(self, dataset_id: str) -> dict[str, object]:
        return self.manifests[dataset_id]

    def validate(self, dataset_id: str) -> dict[str, object]:
        self.validated.append(dataset_id)
        identity = self.manifests[dataset_id]["identity"]
        assert isinstance(identity, dict)
        return {
            "valid": dataset_id not in self.invalid,
            "dataset_id": dataset_id,
            "fingerprint": identity["fingerprint"],
        }


def _dataset_ids(manifests: Mapping[str, Mapping[str, object]]) -> dict[str, str]:
    result = {}
    for role, manifest in manifests.items():
        identity = manifest["identity"]
        assert isinstance(identity, Mapping)
        result[role] = str(identity["dataset_id"])
    return result


def _bind_catalog_datasets(
    registry: IntradayV3Registry,
    layout: StorageLayout,
    plan: IntradayV3CampaignPlan,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifests = _manifests(plan)
    dataset_ids = _dataset_ids(manifests)
    _Datasets.manifests = {dataset_ids[role]: manifest for role, manifest in manifests.items()}
    _Datasets.invalid = set()
    _Datasets.validated = []
    monkeypatch.setattr(registry_module, "DatasetService", _Datasets)
    registry.bind_datasets(layout, dataset_ids)
    assert set(_Datasets.validated) == set(dataset_ids.values())


@dataclass(frozen=True)
class _Identity:
    source_commit: str = "a" * 40

    @property
    def identity_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class _Preassessment:
    build_identity: _Identity
    environment_identity: _Identity
    surface_identity: _Identity


@dataclass(frozen=True)
class _Assessment:
    campaign_id: str
    plan_fingerprint: str
    publication_fingerprint: str
    preassessment: _Preassessment

    @property
    def build_identity(self) -> _Identity:
        return self.preassessment.build_identity

    @property
    def assessment_fingerprint(self) -> str:
        return fingerprint(self)


def _assessment(
    plan: IntradayV3CampaignPlan,
    publication: IntradayV3PublicationSeal,
    seal_path: Path,
) -> IntradayV3SourceAssessment:
    identity = _Identity()
    publication_fingerprint = fingerprint(
        {
            "artifact_json": seal_path.read_text(encoding="utf-8"),
            "verification": canonicalize(publication),
        }
    )
    value = _Assessment(
        plan.campaign_id,
        plan.plan_fingerprint,
        publication_fingerprint,
        _Preassessment(identity, identity, identity),
    )
    return cast(IntradayV3SourceAssessment, value)


def _record_source_review(
    registry: IntradayV3Registry,
    plan: IntradayV3CampaignPlan,
    publication: IntradayV3PublicationSeal,
    seal_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> IntradayV3SourceAssessment:
    assessment = _assessment(plan, publication, seal_path)
    preassessment = cast(_Assessment, assessment).preassessment
    monkeypatch.setattr(registry_module, "IntradayV3SourcePreassessment", _Preassessment)
    monkeypatch.setattr(
        registry_module,
        "assess_intraday_v3_source_preassessment",
        lambda *args: preassessment,
    )
    monkeypatch.setattr(
        registry_module,
        "bind_intraday_v3_source_assessment",
        lambda preassessment, *, plan_fingerprint, publication_fingerprint: _Assessment(
            plan.campaign_id,
            str(plan_fingerprint),
            str(publication_fingerprint),
            preassessment,
        ),
    )
    registry.record_source_review(
        "review-1",
        Path("wheel.whl"),
        Path("runtime-build-manifest.json"),
        Path("intraday-v3-whole-package-surface.json"),
        Path("uv.lock"),
        Path("wheelhouse"),
        assessment.assessment_fingerprint,
        "reviewer",
        "reviewed",
    )
    return assessment


def _bound_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[
    IntradayV3Registry,
    IntradayV3CampaignPlan,
    IntradayV3PublicationSeal,
    Path,
]:
    layout = StorageLayout(tmp_path)
    registry = IntradayV3Registry(layout.experiments)
    plan, publication, seal_path = _materialize(registry, tmp_path, monkeypatch)
    _bind_catalog_datasets(registry, layout, plan, monkeypatch)
    return registry, plan, publication, seal_path


def test_plan_file_alone_creates_no_v3_state(tmp_path: Path) -> None:
    assert (
        IntradayV3Registry(StorageLayout(tmp_path).experiments).list("intraday-research-v3") == []
    )


def test_materializes_only_through_verifier_and_pre_result_get_is_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = IntradayV3Registry(StorageLayout(tmp_path).experiments)
    plan, _, _ = _materialize(registry, tmp_path, monkeypatch)

    assert len(registry.list(plan.campaign_id)) == 60
    record = registry.get(plan.candidates[0].experiment_id)
    assert record["status"] == "pending"
    assert record["metrics_json"] is None


def test_directly_constructed_seal_cannot_materialize(
    tmp_path: Path,
) -> None:
    plan = _plan()
    path = tmp_path / "forged.json"
    forged = _seal(plan, path)
    registry = IntradayV3Registry(StorageLayout(tmp_path).experiments)

    with pytest.raises((AttributeError, TypeError)):
        registry.materialize(cast(Path, forged), _INVENTORY, _SELECTION, _PLAN, _BINDING)
    assert registry.list(plan.campaign_id) == []


def test_catalog_validation_failure_rolls_back_all_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = StorageLayout(tmp_path)
    registry = IntradayV3Registry(layout.experiments)
    plan, _, _ = _materialize(registry, tmp_path, monkeypatch)
    manifests = _manifests(plan)
    dataset_ids = _dataset_ids(manifests)
    _Datasets.manifests = {dataset_ids[role]: manifest for role, manifest in manifests.items()}
    _Datasets.invalid = {dataset_ids["validation-c"]}
    _Datasets.validated = []
    monkeypatch.setattr(registry_module, "DatasetService", _Datasets)

    with pytest.raises(IntradayV3RegistryError, match="failed validation"):
        registry.bind_datasets(layout, dataset_ids)
    assert len(_Datasets.validated) == 4
    assert registry.get(plan.candidates[0].experiment_id)["spec_json"] == {
        "candidate_ordinal": 1,
        "commission_bps": "1",
        "execution_delay_bars": 1,
        "experiment_id": plan.candidates[0].experiment_id,
        "parameters": {"window": 12},
        "parent_candidate": None,
        "period_role": "training",
        "slippage_bps": "5",
        "split": "training",
        "start_timestamp": "2025-07-01T13:30:00Z",
        "end_timestamp": "2026-06-30T19:55:00Z",
        "strategy_family": "intraday-trend",
        "strategy_id": "intraday-event-driven-ma-trend",
        "strategy_version": "1",
        "variant_role": "base",
        "cost_model_version": "conservative-bps-v1",
    }


def test_missing_catalog_datasets_cannot_bind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = StorageLayout(tmp_path)
    registry = IntradayV3Registry(layout.experiments)
    plan, _, _ = _materialize(registry, tmp_path, monkeypatch)
    dataset_ids = {period.role: f"{index + 1:x}" * 64 for index, period in enumerate(plan.periods)}

    with pytest.raises(IntradayV3RegistryError, match="catalog datasets"):
        registry.bind_datasets(layout, dataset_ids)
    assert registry.get(plan.candidates[0].experiment_id)["status"] == "pending"


def test_claim_exposes_review_and_binding_and_failed_candidate_cannot_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(registry_module, "IntradayV3SourceAssessment", _Assessment)
    registry, plan, publication, seal_path = _bound_registry(tmp_path, monkeypatch)
    assessment = _record_source_review(registry, plan, publication, seal_path, monkeypatch)
    experiment_id = plan.candidates[0].experiment_id

    claim = registry.claim(experiment_id, assessment)
    evidence = registry.get(experiment_id)["execution_source_provenance"]
    assert isinstance(evidence, dict) and set(evidence) == {"review", "binding"}
    assert registry.fail(experiment_id, claim.token, "controlled failure")
    with pytest.raises(IntradayV3RegistryError, match="retries"):
        registry.claim(experiment_id, assessment)


def test_heartbeat_and_stale_recovery_leave_terminal_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(registry_module, "IntradayV3SourceAssessment", _Assessment)
    registry, plan, publication, seal_path = _bound_registry(tmp_path, monkeypatch)
    assessment = _record_source_review(registry, plan, publication, seal_path, monkeypatch)
    experiment_id = plan.candidates[0].experiment_id
    claim = registry.claim(experiment_id, assessment)

    registry.heartbeat(experiment_id, claim.token)
    assert registry.get(experiment_id)["heartbeat_at"] is not None
    with registry._connect() as connection:
        connection.execute(
            "UPDATE intraday_v3_lifecycle SET heartbeat_at = ? WHERE experiment_id = ?",
            ("2000-01-01T00:00:00Z", experiment_id),
        )

    assert registry.recover_stale(timedelta(minutes=1)) == [experiment_id]
    record = registry.get(experiment_id)
    assert record["status"] == "failed"
    assert record["failure_info"] == "stale-run-recovered"
    assert record["heartbeat_at"] is None
    assert record["finished_at"] is not None

    report_path = tmp_path / "reports" / f"{claim.spec.configuration_fingerprint}.json"
    report = _report(experiment_id)
    with pytest.raises(IntradayV3RegistryError, match="lease"):
        registry.publish_report(experiment_id, claim.token, report_path, report)
    assert not report_path.exists()


def _report(experiment_id: str) -> dict[str, object]:
    unsigned: dict[str, object] = {
        "provenance": {"experiment_id": experiment_id},
        "realistic": {"metrics": {"total_return": "0.1"}},
        "execution_source_provenance": {"review": {}, "binding": {}},
    }
    return {**unsigned, "report_fingerprint": fingerprint(unsigned)}


def test_claim_token_owns_report_publication_and_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(registry_module, "IntradayV3SourceAssessment", _Assessment)
    registry, plan, publication, seal_path = _bound_registry(tmp_path, monkeypatch)
    assessment = _record_source_review(registry, plan, publication, seal_path, monkeypatch)
    experiment_id = plan.candidates[0].experiment_id
    claim = registry.claim(experiment_id, assessment)
    report_path = tmp_path / "reports" / f"{claim.spec.configuration_fingerprint}.json"
    report = _report(experiment_id)

    registry.publish_report(experiment_id, claim.token, report_path, report)

    record = registry.get(experiment_id)
    assert report_path.is_file()
    assert record["status"] == "completed"
    assert record["artifact_locations_json"] == [str(report_path)]
    assert record["artifact_hashes_json"] == [report["report_fingerprint"]]
    assert not registry.fail(experiment_id, claim.token, "late failure")


@pytest.mark.parametrize("after_write", (False, True))
def test_crash_during_journaled_publication_is_recovered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after_write: bool
) -> None:
    monkeypatch.setattr(registry_module, "IntradayV3SourceAssessment", _Assessment)
    registry, plan, publication, seal_path = _bound_registry(tmp_path, monkeypatch)
    assessment = _record_source_review(registry, plan, publication, seal_path, monkeypatch)
    experiment_id = plan.candidates[0].experiment_id
    claim = registry.claim(experiment_id, assessment)
    report_path = tmp_path / "reports" / f"{claim.spec.configuration_fingerprint}.json"
    writer = write_intraday_execution_report

    def interrupted(path: Path, report: Mapping[str, object]) -> None:
        if after_write:
            writer(path, report)
        raise SystemExit("simulated process termination")

    monkeypatch.setattr(registry_module, "write_intraday_execution_report", interrupted)

    with pytest.raises(SystemExit, match="process termination"):
        registry.publish_report(experiment_id, claim.token, report_path, _report(experiment_id))

    assert report_path.exists() is after_write
    assert registry.get(experiment_id)["status"] == "running"
    assert not registry.fail(experiment_id, claim.token, "late failure")
    monkeypatch.setattr(registry_module, "write_intraday_execution_report", writer)
    with registry._connect() as connection:
        connection.execute(
            "UPDATE intraday_v3_lifecycle SET heartbeat_at = ? WHERE experiment_id = ?",
            ("2000-01-01T00:00:00Z", experiment_id),
        )

    assert registry.recover_stale(timedelta(minutes=1)) == [experiment_id]
    assert registry.get(experiment_id)["status"] == "completed"
    assert report_path.read_text(encoding="utf-8") == canonical_json(_report(experiment_id)) + "\n"


def test_completed_publication_reconciles_a_missing_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(registry_module, "IntradayV3SourceAssessment", _Assessment)
    registry, plan, publication, seal_path = _bound_registry(tmp_path, monkeypatch)
    assessment = _record_source_review(registry, plan, publication, seal_path, monkeypatch)
    experiment_id = plan.candidates[0].experiment_id
    claim = registry.claim(experiment_id, assessment)
    report_path = tmp_path / "reports" / f"{claim.spec.configuration_fingerprint}.json"
    registry.publish_report(experiment_id, claim.token, report_path, _report(experiment_id))
    report_path.unlink()

    assert registry.recover_stale(timedelta(minutes=1)) == [experiment_id]
    assert registry.get(experiment_id)["status"] == "completed"
    assert report_path.is_file()


def test_completed_publication_substitution_records_immutable_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(registry_module, "IntradayV3SourceAssessment", _Assessment)
    registry, plan, publication, seal_path = _bound_registry(tmp_path, monkeypatch)
    assessment = _record_source_review(registry, plan, publication, seal_path, monkeypatch)
    experiment_id = plan.candidates[0].experiment_id
    claim = registry.claim(experiment_id, assessment)
    report_path = tmp_path / "reports" / f"{claim.spec.configuration_fingerprint}.json"
    registry.publish_report(experiment_id, claim.token, report_path, _report(experiment_id))
    before = registry.get(experiment_id)
    report_path.write_text("substituted", encoding="utf-8")

    with pytest.raises(IntradayV3RegistryError, match="durable publication journal"):
        registry.recover_stale(timedelta(minutes=1))

    after = registry.get(experiment_id)
    conflict = after["publication_integrity_conflict"]
    assert isinstance(conflict, dict)
    assert conflict["experiment_id"] == experiment_id
    assert conflict["reason"] == "V3 report path contains different evidence"
    assert conflict["observed_kind"] == "regular-file"
    assert conflict["observed_sha256"] == hashlib.sha256(b"substituted").hexdigest()
    assert conflict["observed_size"] == len(b"substituted")
    assert after["status"] == "completed"
    assert after["artifact_hashes_json"] == before["artifact_hashes_json"]
    with registry._connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE intraday_v3_publication_conflicts SET conflict_json = '{}' "
            "WHERE experiment_id = ?",
            (experiment_id,),
        )


def test_conflicting_report_path_records_terminal_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(registry_module, "IntradayV3SourceAssessment", _Assessment)
    registry, plan, publication, seal_path = _bound_registry(tmp_path, monkeypatch)
    assessment = _record_source_review(registry, plan, publication, seal_path, monkeypatch)
    experiment_id = plan.candidates[0].experiment_id
    claim = registry.claim(experiment_id, assessment)
    report_path = tmp_path / "reports" / f"{claim.spec.configuration_fingerprint}.json"
    report_path.parent.mkdir()
    report_path.write_text("different evidence", encoding="utf-8")

    with pytest.raises(IntradayV3RegistryError, match="path conflicts"):
        registry.publish_report(experiment_id, claim.token, report_path, _report(experiment_id))

    record = registry.get(experiment_id)
    assert record["status"] == "failed"
    assert record["failure_info"] == "report-publication-conflict"
    with registry._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM intraday_v3_publications WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchone() == (1,)


def test_stale_recovery_takes_publication_ownership_from_a_paused_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(registry_module, "IntradayV3SourceAssessment", _Assessment)
    registry, plan, publication, seal_path = _bound_registry(tmp_path, monkeypatch)
    assessment = _record_source_review(registry, plan, publication, seal_path, monkeypatch)
    experiment_id = plan.candidates[0].experiment_id
    claim = registry.claim(experiment_id, assessment)
    with registry._connect() as connection:
        connection.execute(
            "UPDATE intraday_v3_lifecycle SET heartbeat_at = ? WHERE experiment_id = ?",
            ("2000-01-01T00:00:00Z", experiment_id),
        )

    writer_entered = threading.Event()
    release_writer = threading.Event()
    recovery_started = threading.Event()
    publication_errors: list[BaseException] = []
    recovered: list[str] = []
    report_path = tmp_path / "reports" / f"{claim.spec.configuration_fingerprint}.json"
    writer = write_intraday_execution_report

    def blocking_writer(path: Path, report: Mapping[str, object]) -> None:
        writer_entered.set()
        assert release_writer.wait(timeout=5)
        writer(path, report)

    monkeypatch.setattr(registry_module, "write_intraday_execution_report", blocking_writer)

    def publish() -> None:
        try:
            registry.publish_report(experiment_id, claim.token, report_path, _report(experiment_id))
        except BaseException as error:
            publication_errors.append(error)

    def recover() -> None:
        recovery_started.set()
        recovered.extend(registry.recover_stale(timedelta(minutes=1)))

    publication_thread = threading.Thread(target=publish)
    publication_thread.start()
    assert writer_entered.wait(timeout=5)
    recovery = threading.Thread(target=recover)
    recovery.start()
    assert recovery_started.wait(timeout=5)
    release_writer.set()
    publication_thread.join(timeout=5)
    recovery.join(timeout=5)

    assert not publication_thread.is_alive() and not recovery.is_alive()
    assert publication_errors == []
    assert recovered == [experiment_id]
    assert report_path.is_file()
    assert registry.get(experiment_id)["status"] == "completed"
