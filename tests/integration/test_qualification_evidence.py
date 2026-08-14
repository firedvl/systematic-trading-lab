import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from systematic_trading_lab.cli import parser, run
from systematic_trading_lab.config import Settings
from systematic_trading_lab.domain import TradingMode
from systematic_trading_lab.experiments import (
    ExperimentRegistry,
    ExperimentSpec,
    ExperimentSplit,
    HoldoutAccessError,
)
from systematic_trading_lab.fingerprints import canonical_json, fingerprint
from systematic_trading_lab.qualification import load_qualification_proposal
from systematic_trading_lab.qualification_evidence import (
    CandidateEvidenceSpec,
    CombinedStressEvidenceSpec,
    QualificationEvidenceManifest,
    authorize_holdout_run,
    build_evidence_reports,
    evidence_manifest_fingerprint,
    load_evidence_manifest,
    write_evidence_reports,
)


def _spec(
    experiment_id: str,
    strategy_id: str,
    year: int,
    *,
    parent: str | None = None,
    parameters: dict[str, object] | None = None,
    cost_version: str = "conservative-bps-v1",
    execution_version: str = "next-bar-v1",
    code_commit: str = "abc123",
) -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id=experiment_id,
        campaign_id="campaign-evidence",
        strategy_id=strategy_id,
        strategy_version="1",
        strategy_family="trend" if strategy_id == "candidate-strategy" else "allocation",
        code_commit=code_commit,
        dataset_id="dataset-1",
        dataset_fingerprint="fingerprint-1",
        universe_id="liquid-etfs-v1",
        universe_fingerprint="universe-fingerprint-1",
        parameters=parameters or ({} if strategy_id == "fixed-weight" else {"window": 20}),
        cost_model_version=cost_version,
        execution_model_version=execution_version,
        split=ExperimentSplit.VALIDATION,
        start_timestamp=datetime(year, 1, 2, tzinfo=UTC),
        end_timestamp=datetime(year, 12, 29, tzinfo=UTC),
        random_seed=0,
        creation_reason="qualification evidence test",
        parent_candidate=parent,
    )


def _metrics(total_return: str, index: int, *, trade_count: int | None = None) -> dict[str, object]:
    return {
        "total_return": Decimal(total_return),
        "sharpe_ratio": Decimal(str(index)),
        "max_drawdown": Decimal(index) / Decimal("20"),
        "average_gross_exposure": Decimal("0.6"),
        "top_5_session_profit_share": Decimal("0.2"),
        "top_instrument_profit_share": Decimal("0.4"),
        "up_regime_sessions": 100 + index,
        "down_regime_sessions": 50 + index,
        "turnover": Decimal(str(10 + index)),
        "trade_count": trade_count if trade_count is not None else 100 + index,
    }


def _complete(
    registry: ExperimentRegistry, spec: ExperimentSpec, metrics: dict[str, object]
) -> None:
    report: dict[str, object] = {
        "schema_version": "backtest-report-v2",
        "results": {spec.experiment_id: metrics},
        "comparisons": {},
    }
    report["report_fingerprint"] = fingerprint(report)
    report_path = registry.path.parent / f"{spec.experiment_id}.json"
    report_path.write_text(canonical_json(report) + "\n", encoding="utf-8")
    registry.create_experiment(spec)
    registry.claim(spec.experiment_id)
    registry._complete_controlled(
        spec.experiment_id,
        metrics,
        [str(report_path)],
        [str(report["report_fingerprint"])],
    )


def _seed_registry(
    path: Path,
    *,
    corrupt_cost: bool = False,
    include_stresses: bool = False,
    stress_b_return: str = "0.24",
    stress_a_execution_version: str = "delayed-2-bars-v1",
    stress_code_commit: str = "abc123",
) -> ExperimentRegistry:
    registry = ExperimentRegistry(path)
    registry.create_campaign("campaign-evidence", "Evidence", 16)
    base_returns = ("0.1", "0.2", "0.3")
    benchmark_returns = ("0.05", "0.25", "0.1")
    base_trade_counts = (20, 30, 50)
    for index, year in enumerate((2023, 2024, 2025), start=1):
        _complete(
            registry,
            _spec(f"base-{index}", "candidate-strategy", year),
            _metrics(
                base_returns[index - 1],
                index,
                trade_count=base_trade_counts[index - 1],
            ),
        )
        _complete(
            registry,
            _spec(f"benchmark-{index}", "fixed-weight", year),
            _metrics(benchmark_returns[index - 1], index),
        )
    _complete(
        registry,
        _spec(
            "cost",
            "candidate-strategy",
            2025,
            parent="base-3",
            parameters={"window": 25} if corrupt_cost else None,
            cost_version="cost-2x-v1",
        ),
        _metrics("0.24", 3),
    )
    _complete(
        registry,
        _spec(
            "delay",
            "candidate-strategy",
            2025,
            parent="base-3",
            execution_version="delayed-2-bars-v1",
        ),
        _metrics("0.27", 3),
    )
    if include_stresses:
        _complete(
            registry,
            _spec(
                "stress-a",
                "candidate-strategy",
                2025,
                parent="base-3",
                cost_version="bps-10-2-v1",
                execution_version=stress_a_execution_version,
                code_commit=stress_code_commit,
            ),
            _metrics("0.25", 3),
        )
        _complete(
            registry,
            _spec(
                "stress-b",
                "candidate-strategy",
                2025,
                parent="base-3",
                cost_version="bps-20-5-v1",
                execution_version="delayed-3-bars-v1",
            ),
            _metrics(stress_b_return, 3),
        )
    for index, year in enumerate((2023, 2024, 2025), start=1):
        base_return = Decimal(base_returns[index - 1])
        for window, retention in ((15, Decimal("0.5")), (25, Decimal("0.75"))):
            _complete(
                registry,
                _spec(
                    f"neighbor-{index}-{window}",
                    "candidate-strategy",
                    year,
                    parent=f"base-{index}",
                    parameters={"window": window},
                ),
                _metrics(str(base_return * retention), index),
            )
    return registry


def _manifest(*, include_stresses: bool = False) -> QualificationEvidenceManifest:
    return QualificationEvidenceManifest(
        "evidence-test",
        "campaign-evidence",
        "fixed-weight",
        (
            CandidateEvidenceSpec(
                "candidate-20",
                "candidate-strategy",
                {"window": 20},
                "conservative-bps-v1",
                "next-bar-v1",
                "cost-2x-v1",
                "delayed-2-bars-v1",
                ({"window": 15}, {"window": 25}),
                ("base-1", "base-2", "base-3"),
                ("benchmark-1", "benchmark-2", "benchmark-3"),
                ("cost",),
                ("delay",),
                (
                    "neighbor-1-15",
                    "neighbor-1-25",
                    "neighbor-2-15",
                    "neighbor-2-25",
                    "neighbor-3-15",
                    "neighbor-3-25",
                ),
                (
                    CombinedStressEvidenceSpec(
                        "stress-a",
                        "stress-a",
                        "base-3",
                        "bps-10-2-v1",
                        "delayed-2-bars-v1",
                    ),
                    CombinedStressEvidenceSpec(
                        "stress-b",
                        "stress-b",
                        "base-3",
                        "bps-20-5-v1",
                        "delayed-3-bars-v1",
                    ),
                )
                if include_stresses
                else (),
            ),
        ),
    )


def test_registry_evidence_aggregates_and_qualifies_approved_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = _seed_registry(tmp_path / "experiments.sqlite3")
    proposal = replace(
        load_qualification_proposal(Path("config/research/qualification-proposal.json")),
        evidence_campaign_id="campaign-evidence",
    )

    reports = build_evidence_reports(registry, _manifest(), proposal)
    metrics = reports[0]["metrics"]
    qualification = reports[0]["qualification"]

    assert isinstance(metrics, dict)
    assert metrics["benchmark_win_rate"] == Decimal("2") / Decimal("3")
    assert metrics["min_cost2x_return_retention"] == Decimal("0.8")
    assert metrics["min_delay2_return_retention"] == Decimal("0.9")
    assert metrics["min_parameter_neighbor_return_retention"] == Decimal("0.5")
    assert metrics["total_validation_trade_count"] == 100
    assert metrics["campaign_candidate_count"] == 14
    assert isinstance(qualification, dict)
    assert qualification["state"] == "qualified"
    assert all(gate["passed"] for gate in qualification["gates"])
    path = write_evidence_reports(tmp_path / "reports", reports)
    assert path == write_evidence_reports(tmp_path / "reports", reports)

    manifest_path = tmp_path / "evidence.json"
    manifest_path.write_text(
        json.dumps(
            {
                "id": "evidence-test",
                "campaign_id": "campaign-evidence",
                "benchmark_strategy_id": "fixed-weight",
                "candidates": [
                    {
                        "id": "candidate-20",
                        "strategy_id": "candidate-strategy",
                        "base_parameters": {"window": 20},
                        "base_cost_model_version": "conservative-bps-v1",
                        "base_execution_model_version": "next-bar-v1",
                        "cost_sensitivity_model_version": "cost-2x-v1",
                        "delay_sensitivity_model_version": "delayed-2-bars-v1",
                        "parameter_neighbor_values": [{"window": 15}, {"window": 25}],
                        "base_validation_ids": ["base-1", "base-2", "base-3"],
                        "benchmark_validation_ids": [
                            "benchmark-1",
                            "benchmark-2",
                            "benchmark-3",
                        ],
                        "cost_sensitivity_ids": ["cost"],
                        "delay_sensitivity_ids": ["delay"],
                        "parameter_neighbor_ids": [
                            "neighbor-1-15",
                            "neighbor-1-25",
                            "neighbor-2-15",
                            "neighbor-2-25",
                            "neighbor-3-15",
                            "neighbor-3-25",
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    proposal_payload = json.loads(
        Path("config/research/qualification-proposal.json").read_text(encoding="utf-8")
    )
    proposal_payload["evidence_campaign_id"] = "campaign-evidence"
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal_payload), encoding="utf-8")
    arguments = parser().parse_args(
        [
            "experiment",
            "evaluate-qualification",
            "--evidence-manifest",
            str(manifest_path),
            "--proposal",
            str(proposal_path),
        ]
    )

    assert run(arguments, Settings(TradingMode.OFFLINE, tmp_path)) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["candidate_ids"] == ["candidate-20"]
    assert Path(output["report"]) == path

    authorize_arguments = parser().parse_args(
        [
            "experiment",
            "authorize-holdout",
            "authorization-approved",
            "--candidate",
            "candidate-20",
            "--evidence-manifest",
            str(manifest_path),
            "--proposal",
            str(proposal_path),
            "--reviewer",
            "reviewer",
            "--reason",
            "final holdout",
        ]
    )
    assert run(authorize_arguments, Settings(TradingMode.OFFLINE, tmp_path)) == 0
    assert (
        registry.get_holdout_run_authorization("authorization-approved")["candidate_id"]
        == "candidate-20"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("execution_provenance", "legacy-manual"),
        ("artifact_locations_json", "[]"),
        ("artifact_hashes_json", "[]"),
    ),
)
def test_qualification_rejects_uncontrolled_or_unbound_evidence(
    tmp_path: Path, field: str, value: str
) -> None:
    path = tmp_path / "experiments.sqlite3"
    registry = _seed_registry(path)
    with registry._connect() as connection:
        connection.execute(
            f"UPDATE experiments SET {field} = ? WHERE experiment_id = 'base-1'", (value,)
        )
    proposal = replace(
        load_qualification_proposal(Path("config/research/qualification-proposal.json")),
        evidence_campaign_id="campaign-evidence",
    )

    with pytest.raises(ValueError, match="invalid qualification evidence experiment: base-1"):
        build_evidence_reports(registry, _manifest(), proposal)


@pytest.mark.parametrize("replacement", (None, "{}"))
def test_qualification_rejects_missing_or_tampered_report(
    tmp_path: Path, replacement: str | None
) -> None:
    registry = _seed_registry(tmp_path / "experiments.sqlite3")
    locations = registry.get("base-1")["artifact_locations_json"]
    assert isinstance(locations, list) and isinstance(locations[0], str)
    report_path = Path(locations[0])
    if replacement is None:
        report_path.unlink()
    else:
        report_path.write_text(replacement, encoding="utf-8")
    proposal = replace(
        load_qualification_proposal(Path("config/research/qualification-proposal.json")),
        evidence_campaign_id="campaign-evidence",
    )

    with pytest.raises(ValueError, match="invalid qualification evidence report: base-1"):
        build_evidence_reports(registry, _manifest(), proposal)


def test_approved_evidence_creates_one_exact_holdout_authorization(tmp_path: Path) -> None:
    registry = _seed_registry(tmp_path / "experiments.sqlite3")
    proposal = replace(
        load_qualification_proposal(Path("config/research/qualification-proposal.json")),
        evidence_campaign_id="campaign-evidence",
    )
    authorization = authorize_holdout_run(
        registry,
        _manifest(),
        proposal,
        "candidate-20",
        "authorization-1",
        "reviewer",
        "one final holdout",
    )

    assert authorization["candidate_id"] == "candidate-20"
    assert authorization["consumed_by_experiment_id"] is None
    with pytest.raises(HoldoutAccessError, match="already exists"):
        authorize_holdout_run(
            registry,
            _manifest(),
            proposal,
            "candidate-20",
            "authorization-2",
            "reviewer",
            "try to authorize twice",
        )
    holdout = replace(
        _spec("holdout", "candidate-strategy", 2026),
        split=ExperimentSplit.HOLDOUT,
        parent_candidate="candidate-20",
    )
    with pytest.raises(HoldoutAccessError, match="unused stored authorization"):
        registry.create_experiment(holdout)
    with pytest.raises(HoldoutAccessError, match="begin after"):
        registry.create_experiment(
            replace(
                holdout,
                start_timestamp=datetime(2025, 1, 2, tzinfo=UTC),
                end_timestamp=datetime(2025, 12, 29, tzinfo=UTC),
            ),
            holdout_authorization_id="authorization-1",
        )
    with pytest.raises(HoldoutAccessError, match="specification differs"):
        registry.create_experiment(
            replace(holdout, parameters={"window": 25}),
            holdout_authorization_id="authorization-1",
        )
    assert (
        registry.get_holdout_run_authorization("authorization-1")["consumed_by_experiment_id"]
        is None
    )

    registry.create_experiment(holdout, holdout_authorization_id="authorization-1")

    assert (
        registry.get_holdout_run_authorization("authorization-1")["consumed_by_experiment_id"]
        == "holdout"
    )
    with pytest.raises(HoldoutAccessError, match="unused stored authorization"):
        registry.create_experiment(
            replace(holdout, experiment_id="holdout-again"),
            holdout_authorization_id="authorization-1",
        )
    with pytest.raises(HoldoutAccessError, match="already exists"):
        authorize_holdout_run(
            registry,
            _manifest(),
            proposal,
            "candidate-20",
            "authorization-after-consumption",
            "reviewer",
            "try to reopen the same qualification",
        )


def test_approved_evidence_cannot_authorize_a_failing_candidate(tmp_path: Path) -> None:
    registry = _seed_registry(tmp_path / "experiments.sqlite3")
    proposal = replace(
        load_qualification_proposal(Path("config/research/qualification-proposal.json")),
        evidence_campaign_id="campaign-evidence",
    )
    failing = replace(
        proposal,
        gates=(
            replace(
                proposal.gates[0],
                spec=replace(proposal.gates[0].spec, threshold=Decimal("4")),
            ),
            *proposal.gates[1:],
        ),
    )

    with pytest.raises(HoldoutAccessError, match="approved passing"):
        authorize_holdout_run(
            registry,
            _manifest(),
            failing,
            "candidate-20",
            "authorization-failing",
            "reviewer",
            "must not authorize failed evidence",
        )
    with pytest.raises(KeyError, match="authorization not found"):
        registry.get_holdout_run_authorization("authorization-failing")


def test_registry_evidence_rejects_mislabeled_variant(tmp_path: Path) -> None:
    registry = _seed_registry(tmp_path / "experiments.sqlite3", corrupt_cost=True)
    proposal = replace(
        load_qualification_proposal(Path("config/research/qualification-proposal.json")),
        evidence_campaign_id="campaign-evidence",
    )

    with pytest.raises(ValueError, match="invalid cost variant"):
        build_evidence_reports(registry, _manifest(), proposal)


def test_combined_stresses_bind_both_models_and_qualify(tmp_path: Path) -> None:
    registry = _seed_registry(tmp_path / "experiments.sqlite3", include_stresses=True)
    proposal = replace(
        load_qualification_proposal(
            Path("config/research/qualification-proposal-rapid-002-rmm-v1.json")
        ),
        evidence_campaign_id="campaign-evidence",
    )

    report = build_evidence_reports(registry, _manifest(include_stresses=True), proposal)[0]
    metrics = report["metrics"]
    qualification = report["qualification"]

    assert isinstance(metrics, dict)
    assert metrics["stress_a_return"] == Decimal("0.25")
    assert metrics["stress_a_return_retention"] == Decimal("0.25") / Decimal("0.3")
    assert metrics["stress_b_return"] == Decimal("0.24")
    assert metrics["stress_b_return_retention"] == Decimal("0.8")
    assert metrics["campaign_candidate_count"] == 16
    assert isinstance(qualification, dict)
    assert qualification["state"] == "qualified"
    assert all(gate["passed"] for gate in qualification["gates"])


def test_combined_stress_zero_return_fails_strict_gate(tmp_path: Path) -> None:
    registry = _seed_registry(
        tmp_path / "experiments.sqlite3",
        include_stresses=True,
        stress_b_return="0",
    )
    proposal = replace(
        load_qualification_proposal(
            Path("config/research/qualification-proposal-rapid-002-rmm-v1.json")
        ),
        evidence_campaign_id="campaign-evidence",
    )

    qualification = build_evidence_reports(registry, _manifest(include_stresses=True), proposal)[0][
        "qualification"
    ]

    assert isinstance(qualification, dict)
    assert qualification["state"] == "rejected"
    stress_b_return = next(
        gate for gate in qualification["gates"] if gate["metric"] == "stress_b_return"
    )
    assert stress_b_return["passed"] is False
    assert stress_b_return["reason"] == "not-above-threshold"


@pytest.mark.parametrize(
    ("stress_a_execution_version", "stress_code_commit"),
    (
        ("next-bar-v1", "abc123"),
        ("delayed-2-bars-v1", "different-source"),
    ),
)
def test_combined_stress_rejects_one_axis_or_source_mismatch(
    tmp_path: Path,
    stress_a_execution_version: str,
    stress_code_commit: str,
) -> None:
    registry = _seed_registry(
        tmp_path / "experiments.sqlite3",
        include_stresses=True,
        stress_a_execution_version=stress_a_execution_version,
        stress_code_commit=stress_code_commit,
    )
    proposal = replace(
        load_qualification_proposal(
            Path("config/research/qualification-proposal-rapid-002-rmm-v1.json")
        ),
        evidence_campaign_id="campaign-evidence",
    )

    with pytest.raises(ValueError, match="combined stress"):
        build_evidence_reports(registry, _manifest(include_stresses=True), proposal)


def test_committed_evidence_manifest_is_strict() -> None:
    manifest = load_evidence_manifest(Path("config/research/qualification-evidence-v3.json"))

    assert manifest.campaign_id == "alpaca-qualification-evidence-20260802-v3"
    assert [candidate.candidate_id for candidate in manifest.candidates] == [
        "moving-average-20",
        "momentum-20",
    ]


def test_rapid_002_manifest_freezes_exact_28_record_ledger() -> None:
    manifest = load_evidence_manifest(
        Path("config/research/qualification-evidence-rapid-002-rmm-v1.json")
    )
    proposal = load_qualification_proposal(
        Path("config/research/qualification-proposal-rapid-002-rmm-v1.json")
    )
    approved_daily = load_qualification_proposal(
        Path("config/research/qualification-proposal-strategic-allocation-v1.json")
    )
    candidate = manifest.candidates[0]
    ids = (
        candidate.base_validation_ids
        + candidate.benchmark_validation_ids
        + candidate.cost_sensitivity_ids
        + candidate.delay_sensitivity_ids
        + candidate.parameter_neighbor_ids
        + tuple(stress.experiment_id for stress in candidate.combined_stresses)
    )

    assert manifest.campaign_id == "rapid-002-rmm-40-40-10-controlled-v1"
    assert candidate.candidate_id == "rr-a480ff073a90e448c8b2"
    assert candidate.base_parameters == {
        "lookback": 40,
        "rebalance_every": 10,
        "volatility_window": 40,
    }
    assert len(ids) == len(set(ids)) == 28
    assert tuple(stress.role for stress in candidate.combined_stresses) == (
        "stress-a",
        "stress-b",
    )
    assert evidence_manifest_fingerprint(manifest) == (
        "b997afb53fdf05ef26be72934fb3318cb582ba503f4527fa9ca96f88f7b72693"
    )
    assert proposal.gates[:17] == approved_daily.gates
    assert tuple(gate.spec.metric for gate in proposal.gates[17:]) == (
        "stress_a_return",
        "stress_a_return_retention",
        "stress_b_return",
        "stress_b_return_retention",
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    (
        (
            "config/research/qualification-evidence-strategic-allocation-v1.json",
            "1feddfba3b889d8fc15c83ee241b776dd69afe607ecf2d05a1b92154071822b5",
        ),
        (
            "config/research/qualification-evidence-v3.json",
            "e34075c041054b54ddf1141b39c5827fb492ec3fd3a836f18c5d95e59982a73d",
        ),
    ),
)
def test_existing_manifest_fingerprints_remain_stable(path: str, expected: str) -> None:
    assert evidence_manifest_fingerprint(load_evidence_manifest(Path(path))) == expected
