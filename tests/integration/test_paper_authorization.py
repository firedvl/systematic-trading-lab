import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from systematic_trading_lab.experiments import HoldoutAccessError
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.risk import (
    PaperAuthorization,
    RiskLimits,
    RiskStore,
)

NOW = datetime(2026, 8, 3, 20, tzinfo=UTC)


def _limits() -> RiskLimits:
    return RiskLimits(
        configuration_id="test-only-limits",
        account_id="paper-account",
        allowed_symbols=("SPY",),
        max_order_notional=Decimal("30000"),
        max_position_notional=Decimal("40000"),
        max_gross_exposure=Decimal("90000"),
        min_cash=Decimal("10000"),
        max_open_orders=3,
        max_orders_per_minute=4,
        max_daily_loss=Decimal("2000"),
        max_strategy_drawdown=Decimal("0.10"),
        max_price_deviation_bps=Decimal("50"),
        max_snapshot_age_seconds=30,
        reviewed_by="test-reviewer",
        review_reason="test fixture only",
        effective_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=30),
    )


def _evidence(*, passed: bool = True) -> dict[str, object]:
    candidate = {
        "strategy_id": "candidate",
        "strategy_version": "1",
        "strategy_family": "trend",
        "code_commit": "reviewed-commit",
        "parameters": {"window": 20},
        "cost_model_version": "cost-v1",
        "execution_model_version": "next-bar-v1",
        "dataset_id": "dataset-1",
        "dataset_fingerprint": fingerprint({"dataset": 1}),
        "universe_id": "universe-1",
        "universe_fingerprint": fingerprint({"universe": 1}),
        "validation_start": "2025-01-01T00:00:00Z",
        "validation_end": "2025-12-31T00:00:00Z",
    }
    qualification: dict[str, object] = {
        "experiment_id": "candidate-1",
        "state": "qualified",
        "gates": [{"gate": "test", "approved": True, "passed": passed}],
    }
    qualification["report_fingerprint"] = fingerprint(qualification)
    report: dict[str, object] = {
        "schema_version": "qualification-evidence-v1",
        "manifest_id": "manifest-1",
        "manifest_fingerprint": fingerprint({"manifest": 1}),
        "proposal_id": "proposal-1",
        "proposal_fingerprint": fingerprint({"proposal": 1}),
        "campaign_id": "campaign-1",
        "candidate_id": "candidate-1",
        "strategy_id": "candidate",
        "candidate_specification": candidate,
        "source_experiment_ids": ["validation-1"],
        "metrics": {},
        "qualification": qualification,
    }
    report["evidence_fingerprint"] = fingerprint(report)
    return report


def _authorization(report: dict[str, object], limits: RiskLimits) -> PaperAuthorization:
    candidate = report["candidate_specification"]
    assert isinstance(candidate, dict)
    return PaperAuthorization(
        authorization_id="paper-auth-1",
        candidate_id="candidate-1",
        strategy_id="candidate",
        strategy_version="1",
        parameters_fingerprint=fingerprint(candidate["parameters"]),
        code_commit="reviewed-commit",
        dataset_id="dataset-1",
        dataset_fingerprint=str(candidate["dataset_fingerprint"]),
        universe_id="universe-1",
        universe_fingerprint=str(candidate["universe_fingerprint"]),
        qualification_evidence_fingerprint=str(report["evidence_fingerprint"]),
        account_id=limits.account_id,
        risk_configuration_fingerprint=limits.configuration_fingerprint,
        authorized_by="paper-reviewer",
        authorization_reason="test authorization",
        authorized_at=NOW,
        expires_at=NOW + timedelta(days=7),
    )


def test_paper_authorization_is_exact_immutable_and_restart_safe(tmp_path: Path) -> None:
    path = tmp_path / "execution.sqlite3"
    limits = _limits()
    report = _evidence()
    authorization = _authorization(report, limits)

    store = RiskStore(path)
    assert store.authorize_paper(authorization, report, limits) == authorization
    assert store.authorize_paper(authorization, report, limits) == authorization
    assert RiskStore(path).get_paper_authorization("paper-auth-1") == authorization

    with (
        sqlite3.connect(path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="immutable"),
    ):
        connection.execute("UPDATE paper_authorizations SET authorization_json = '{}'")


def test_paper_authorization_rejects_failed_or_changed_evidence(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "execution.sqlite3")
    limits = _limits()
    report = _evidence()
    authorization = _authorization(report, limits)

    with pytest.raises(HoldoutAccessError, match="approved passing gates"):
        store.authorize_paper(authorization, _evidence(passed=False), limits)
    with pytest.raises(HoldoutAccessError, match="differs"):
        store.authorize_paper(replace(authorization, dataset_id="other-dataset"), report, limits)
    with pytest.raises(HoldoutAccessError, match="risk configuration period"):
        store.authorize_paper(
            replace(authorization, expires_at=limits.expires_at + timedelta(seconds=1)),
            report,
            limits,
        )
