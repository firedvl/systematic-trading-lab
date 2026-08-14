import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

import systematic_trading_lab.campaign_specs as campaign_specs
from systematic_trading_lab.calendar import expected_bar_timestamps
from systematic_trading_lab.campaign_specs import (
    RAPID_002_CAMPAIGN_ID,
    REVIEWED_INTRADAY_UNIVERSE_FINGERPRINT,
    REVIEWED_INTRADAY_UNIVERSE_ID,
    build_planned_intraday_experiment,
    build_planned_intraday_experiments,
    build_rapid_002_controlled_plan,
    load_intraday_research_campaign_plan,
    load_training_campaign_plan,
    parse_controlled_validation_campaign_plan,
    parse_intraday_research_campaign_plan,
    validate_rapid_002_control_binding,
    validate_rapid_002_dataset_manifest,
    verify_rapid_002_candidate_export,
)
from systematic_trading_lab.domain import Timeframe
from systematic_trading_lab.qualification import load_qualification_proposal
from systematic_trading_lab.qualification_evidence import load_evidence_manifest
from systematic_trading_lab.universe import load_intraday_universe

INTRADAY_V1_PLAN = Path("config/research/intraday-campaign-v1.json")
INTRADAY_V2_PLAN = Path("config/research/intraday-campaign-v2.json")


def plan_payload() -> dict[str, object]:
    return {
        "schema_version": "training-campaign-plan-v1",
        "campaign_id": "sealed-training",
        "name": "Sealed training",
        "search_budget": 2,
        "code_commit": "abc123",
        "dataset_id": "dataset-1",
        "dataset_fingerprint": "dataset-fingerprint-1",
        "universe_id": "liquid-etfs-v1",
        "universe_fingerprint": "universe-fingerprint-1",
        "candidates": [
            {
                "experiment_id": "benchmark",
                "role": "benchmark",
                "strategy_id": "fixed-weight",
                "strategy_version": "1",
                "strategy_family": "allocation",
                "parameters": {},
                "start_timestamp": "2020-01-01T00:00:00Z",
                "end_timestamp": "2020-12-31T00:00:00Z",
                "random_seed": 0,
                "creation_reason": "sealed benchmark",
                "parent_candidate": None,
            },
            {
                "experiment_id": "candidate",
                "role": "base",
                "strategy_id": "moving-average-trend",
                "strategy_version": "1",
                "strategy_family": "trend",
                "parameters": {"window": 20},
                "start_timestamp": "2020-01-01T00:00:00Z",
                "end_timestamp": "2020-12-31T00:00:00Z",
                "random_seed": 0,
                "creation_reason": "sealed candidate",
                "parent_candidate": "benchmark",
            },
        ],
    }


def write_plan(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_training_campaign_plan_is_strict_and_deterministic(tmp_path: Path) -> None:
    path = write_plan(tmp_path / "plan.json", plan_payload())
    first = load_training_campaign_plan(path)
    second = load_training_campaign_plan(path)

    assert first.plan_fingerprint == second.plan_fingerprint
    assert len(first.candidates) == first.search_budget == 2
    assert first.candidates[1].parameters == {"window": 20}


@pytest.mark.parametrize("defect", ("unknown-field", "budget", "parent", "parameters"))
def test_training_campaign_plan_rejects_unsealed_variation(tmp_path: Path, defect: str) -> None:
    payload = copy.deepcopy(plan_payload())
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    second = candidates[1]
    assert isinstance(second, dict)
    if defect == "unknown-field":
        payload["unexpected"] = True
    elif defect == "budget":
        payload["search_budget"] = 3
    elif defect == "parent":
        second["parent_candidate"] = "undeclared"
    else:
        second["parameters"] = {}

    with pytest.raises(ValueError):
        load_training_campaign_plan(write_plan(tmp_path / f"{defect}.json", payload))


@pytest.mark.parametrize(
    ("strategy_id", "family", "parameter"),
    (
        ("moving-average-mean-reversion", "mean-reversion", "window"),
        ("volatility-targeted-exposure", "volatility", "volatility_window"),
    ),
)
def test_training_plan_rejects_invalid_new_baseline_windows(
    tmp_path: Path, strategy_id: str, family: str, parameter: str
) -> None:
    payload = plan_payload()
    candidates = payload["candidates"]
    assert isinstance(candidates, list) and isinstance(candidates[1], dict)
    candidates[1].update(
        strategy_id=strategy_id,
        strategy_family=family,
        parameters={parameter: 1},
    )

    with pytest.raises(ValueError, match="planned parameters differ"):
        load_training_campaign_plan(write_plan(tmp_path / "invalid-window.json", payload))


def test_training_plan_accepts_strategic_allocation(tmp_path: Path) -> None:
    payload = plan_payload()
    candidates = payload["candidates"]
    assert isinstance(candidates, list) and isinstance(candidates[1], dict)
    candidates[1].update(
        strategy_id="strategic-allocation-portfolio",
        strategy_family="portfolio-allocation",
        parameters={"rebalance_every": 21},
    )

    plan = load_training_campaign_plan(write_plan(tmp_path / "allocation.json", payload))

    assert plan.candidates[1].parameters == {"rebalance_every": 21}


def _rapid_002_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> campaign_specs.ControlledValidationCampaignPlan:
    source = campaign_specs._rapid_002_source_payload("f" * 40)
    monkeypatch.setattr(campaign_specs, "rapid_002_execution_source_identity", lambda: source)
    return build_rapid_002_controlled_plan()


def test_rapid_002_plan_freezes_exact_28_record_execution_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _rapid_002_plan(monkeypatch)
    reservations = {item.spec.experiment_id: item for item in plan.candidates}
    expected_ids = {
        *(f"r2-rmm-base-{year}" for year in (2023, 2024, 2025)),
        *(f"r2-fixed-weight-{year}" for year in (2023, 2024, 2025)),
        *(
            f"r2-rmm-{tag}-{year}"
            for tag in (
                "lookback30",
                "lookback50",
                "volatility30",
                "volatility50",
                "cadence5",
                "cadence15",
            )
            for year in (2023, 2024, 2025)
        ),
        "r2-rmm-cost2x-2025",
        "r2-rmm-delay2-2025",
        "r2-rmm-stress-a-2025",
        "r2-rmm-stress-b-2025",
    }

    assert plan.campaign_id == RAPID_002_CAMPAIGN_ID
    assert len(plan.candidates) == plan.search_budget == 28
    assert {item.ordinal for item in plan.candidates} == set(range(1, 29))
    assert set(reservations) == expected_ids
    assert all(item.spec.split.value == "validation" for item in plan.candidates)
    assert all(item.spec.code_commit == "f" * 40 for item in plan.candidates)
    assert all(
        (item.initial_cash, item.spec.random_seed) == (Decimal("100000"), 0)
        for item in plan.candidates
    )

    normal_ids = expected_ids - {
        "r2-rmm-cost2x-2025",
        "r2-rmm-delay2-2025",
        "r2-rmm-stress-a-2025",
        "r2-rmm-stress-b-2025",
    }
    assert {
        (
            reservations[item].slippage_bps,
            reservations[item].commission_bps,
            reservations[item].fill_delay_bars,
        )
        for item in normal_ids
    } == {(Decimal("5"), Decimal("1"), 1)}
    assert (
        reservations["r2-rmm-cost2x-2025"].slippage_bps,
        reservations["r2-rmm-cost2x-2025"].commission_bps,
        reservations["r2-rmm-cost2x-2025"].fill_delay_bars,
    ) == (Decimal("10"), Decimal("2"), 1)
    assert (
        reservations["r2-rmm-delay2-2025"].slippage_bps,
        reservations["r2-rmm-delay2-2025"].commission_bps,
        reservations["r2-rmm-delay2-2025"].fill_delay_bars,
    ) == (Decimal("5"), Decimal("1"), 2)
    assert (
        reservations["r2-rmm-stress-a-2025"].slippage_bps,
        reservations["r2-rmm-stress-a-2025"].commission_bps,
        reservations["r2-rmm-stress-a-2025"].fill_delay_bars,
    ) == (Decimal("10"), Decimal("2"), 2)
    assert (
        reservations["r2-rmm-stress-b-2025"].slippage_bps,
        reservations["r2-rmm-stress-b-2025"].commission_bps,
        reservations["r2-rmm-stress-b-2025"].fill_delay_bars,
    ) == (Decimal("20"), Decimal("5"), 3)

    validate_rapid_002_control_binding(
        plan,
        load_evidence_manifest(
            Path("config/research/qualification-evidence-rapid-002-rmm-v1.json")
        ),
        load_qualification_proposal(
            Path("config/research/qualification-proposal-rapid-002-rmm-v1.json")
        ),
    )


@pytest.mark.parametrize(
    "defect",
    (
        "parameter",
        "cost",
        "delay",
        "manifest",
        "proposal",
        "source",
        "dataset",
        "authority",
        "candidate-count",
    ),
)
def test_rapid_002_plan_rejects_any_frozen_control_mutation(
    monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    payload = copy.deepcopy(_rapid_002_plan(monkeypatch).payload)
    candidates = payload["candidates"]
    qualification = payload["qualification"]
    source = payload["execution_source"]
    dataset = payload["dataset"]
    authorities = payload["authorities"]
    assert isinstance(candidates, list) and isinstance(candidates[0], dict)
    assert isinstance(qualification, dict)
    assert isinstance(source, dict)
    assert isinstance(dataset, dict)
    assert isinstance(authorities, dict)
    if defect == "parameter":
        parameters = candidates[0]["parameters"]
        assert isinstance(parameters, dict)
        parameters["lookback"] = 41
    elif defect == "cost":
        candidates[0]["slippage_bps"] = "6"
    elif defect == "delay":
        candidates[0]["fill_delay_bars"] = 2
    elif defect == "manifest":
        qualification["evidence_manifest_fingerprint"] = "0" * 64
    elif defect == "proposal":
        qualification["proposal_fingerprint"] = "0" * 64
    elif defect == "source":
        source["strategy_sha256"] = "0" * 64
    elif defect == "dataset":
        dataset["symbols"] = ["SPY"]
    elif defect == "authority":
        authorities["paper_execution"] = True
    else:
        candidates.pop()

    with pytest.raises(ValueError, match="plan differs"):
        parse_controlled_validation_campaign_plan(payload)


def test_rapid_002_dataset_and_candidate_artifacts_fail_closed(tmp_path: Path) -> None:
    manifest: dict[str, object] = {
        "identity": {
            "dataset_id": campaign_specs.RAPID_002_DATASET_ID,
            "fingerprint": campaign_specs.RAPID_002_DATASET_FINGERPRINT,
        },
        "provider": "alpaca-historical-v2",
        "symbols": [{"value": symbol} for symbol in ("SPY", "QQQ", "IWM", "TLT", "GLD")],
        "timeframe": "1d",
        "requested_range": {
            "start": "2020-07-27T00:00:00Z",
            "end": "2026-07-31T00:00:00Z",
        },
        "actual_range": {
            "start": "2020-07-27T00:00:00Z",
            "end": "2026-07-31T00:00:00Z",
        },
        "adjustment_policy": "provider-adjusted-all-v1",
        "calendar_policy": "XNYS-v1",
        "universe_id": campaign_specs.RAPID_002_UNIVERSE_ID,
        "universe_fingerprint": campaign_specs.RAPID_002_UNIVERSE_FINGERPRINT,
    }
    validate_rapid_002_dataset_manifest(manifest)
    changed = copy.deepcopy(manifest)
    changed["adjustment_policy"] = "unknown"
    with pytest.raises(ValueError, match="dataset manifest differs"):
        validate_rapid_002_dataset_manifest(changed)

    invalid_export = tmp_path / "candidate.json"
    invalid_export.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 differs"):
        verify_rapid_002_candidate_export(invalid_export)


def test_intraday_campaign_v1_reserves_the_complete_fixed_matrix() -> None:
    first = load_intraday_research_campaign_plan(INTRADAY_V1_PLAN)
    second = load_intraday_research_campaign_plan(INTRADAY_V1_PLAN)

    assert first.plan_fingerprint == second.plan_fingerprint
    assert (
        first.plan_fingerprint == "ce81be36d02cc15f421390bf3d3787714bb0b025797ccfb8de2c1d1236052c1a"
    )
    assert first.base_code_commit == "b1774f547da2976348430b820faf2ebdacdf46af"
    universe = load_intraday_universe(Timeframe.FIVE_MINUTES)
    assert universe.universe_id == REVIEWED_INTRADAY_UNIVERSE_ID
    assert universe.universe_fingerprint == REVIEWED_INTRADAY_UNIVERSE_FINGERPRINT
    assert len(first.candidates) == first.search_budget == 60
    assert [candidate.candidate_ordinal for candidate in first.candidates] == list(range(1, 61))
    assert [period.role for period in first.periods] == [
        "training",
        "validation-a",
        "validation-b",
        "validation-c",
    ]
    assert sum(candidate.variant_role == "base" for candidate in first.candidates) == 12
    assert sum(candidate.variant_role.endswith("cost") for candidate in first.candidates) == 24
    assert sum(candidate.variant_role.startswith("plus-") for candidate in first.candidates) == 24
    for offset in range(0, first.search_budget, 5):
        group = first.candidates[offset : offset + 5]
        assert [candidate.variant_role for candidate in group] == [
            "base",
            "increased-cost",
            "harsher-cost",
            "plus-1-bar",
            "plus-2-bars",
        ]
        assert group[0].parent_candidate is None
        assert all(candidate.parent_candidate == group[0].experiment_id for candidate in group[1:])
        assert [candidate.execution_delay_bars for candidate in group] == [1, 1, 1, 2, 3]


def test_intraday_campaign_v2_carries_forward_the_fixed_design_under_a_new_identity() -> None:
    v1 = load_intraday_research_campaign_plan(INTRADAY_V1_PLAN)
    v2 = load_intraday_research_campaign_plan(INTRADAY_V2_PLAN)

    assert v2.campaign_id == "intraday-research-v2"
    assert v2.plan_fingerprint == (
        "52db8a27fa4ff86865ab69b6bd7456899329ef3b861a582e59ab32904c03c122"
    )
    assert v2.base_code_commit == "f3d7ee7d86c3a02b52c09270a6399aa1bf5f78b7"
    assert len(v2.candidates) == v2.search_budget == 60
    assert [
        len(
            expected_bar_timestamps(
                period.start_timestamp,
                period.end_timestamp,
                Timeframe.FIVE_MINUTES,
            )
        )
        for period in v2.periods
    ] == [9876, 3042, 3354, 3198]
    assert [
        (
            candidate.candidate_ordinal,
            candidate.strategy_id,
            candidate.strategy_family,
            candidate.parameters,
            candidate.period_role,
            candidate.split,
            candidate.start_timestamp,
            candidate.end_timestamp,
            candidate.variant_role,
            candidate.cost_model_version,
            candidate.slippage_bps,
            candidate.commission_bps,
            candidate.execution_delay_bars,
        )
        for candidate in v2.candidates
    ] == [
        (
            candidate.candidate_ordinal,
            candidate.strategy_id,
            candidate.strategy_family,
            candidate.parameters,
            candidate.period_role,
            candidate.split,
            candidate.start_timestamp,
            candidate.end_timestamp,
            candidate.variant_role,
            candidate.cost_model_version,
            candidate.slippage_bps,
            candidate.commission_bps,
            candidate.execution_delay_bars,
        )
        for candidate in v1.candidates
    ]


def test_intraday_campaign_v1_binds_only_the_exact_planned_dataset() -> None:
    plan = load_intraday_research_campaign_plan(INTRADAY_V1_PLAN)
    manifest: dict[str, object] = {
        "identity": {"dataset_id": "dataset-1", "fingerprint": "dataset-fingerprint-1"},
        "provider": "alpaca-historical-v2",
        "feed": "iex",
        "timeframe": "5m",
        "adjustment_policy": "provider-adjusted-all-v1",
        "calendar_policy": "XNYS-regular-session-bars-v1",
        "timestamp_policy": "bar-open-utc-v1",
        "requested_range": {
            "start": "2025-07-01T13:30:00Z",
            "end": "2025-12-31T20:55:00Z",
        },
        "actual_range": {
            "start": "2025-07-01T13:30:00Z",
            "end": "2025-12-31T20:55:00Z",
        },
        "symbols": [{"value": "SPY"}, {"value": "QQQ"}],
        "universe_id": "liquid-etfs-intraday-5m-v1",
        "universe_fingerprint": "6ac4a8269f8e352536f52ddc0a3000e0b39c5551c33c03959c20a640cfddeca9",
    }

    spec = build_planned_intraday_experiment(
        plan,
        "intraday-research-v1-cash-training-base",
        manifest,
    )

    assert spec.candidate_ordinal == 1
    assert spec.strategy_id == "intraday-cash"
    assert spec.dataset_id == "dataset-1"
    assert spec.start_timestamp == plan.periods[0].start_timestamp
    assert spec.parent_candidate is None

    changed = copy.deepcopy(manifest)
    actual_range = changed["actual_range"]
    assert isinstance(actual_range, dict)
    actual_range["start"] = "2025-07-02T13:30:00Z"
    with pytest.raises(ValueError, match="does not match the planned intraday period"):
        build_planned_intraday_experiment(
            plan,
            "intraday-research-v1-cash-training-base",
            changed,
        )

    changed_feed = copy.deepcopy(manifest)
    changed_feed["feed"] = "sip"
    with pytest.raises(ValueError, match="does not match the planned intraday period"):
        build_planned_intraday_experiment(
            plan,
            "intraday-research-v1-cash-training-base",
            changed_feed,
        )


def test_intraday_campaign_requires_one_dataset_per_period() -> None:
    plan = load_intraday_research_campaign_plan(INTRADAY_V2_PLAN)
    manifests: dict[str, dict[str, object]] = {}
    for index, period in enumerate(plan.periods):
        start = period.start_timestamp.isoformat().replace("+00:00", "Z")
        end = period.end_timestamp.isoformat().replace("+00:00", "Z")
        manifests[period.role] = {
            "identity": {
                "dataset_id": f"dataset-{index}",
                "fingerprint": f"fingerprint-{index}",
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
            "universe_id": REVIEWED_INTRADAY_UNIVERSE_ID,
            "universe_fingerprint": REVIEWED_INTRADAY_UNIVERSE_FINGERPRINT,
        }

    specs = build_planned_intraday_experiments(plan, manifests)
    assert len(specs) == 60
    assert {spec.dataset_id for spec in specs} == {
        f"dataset-{index}" for index in range(len(plan.periods))
    }
    missing = dict(manifests)
    missing.pop("validation-c")
    with pytest.raises(ValueError, match="dataset roles differ"):
        build_planned_intraday_experiments(plan, missing)


@pytest.mark.parametrize(
    ("defect", "message"),
    (
        ("strategy", "fixed strategy contract differs"),
        ("period", "UTC bounds do not cover exact XNYS sessions"),
        ("cost", "cost stresses must increase"),
        ("ordered-cost-change", "differs from its reviewed preregistration"),
        ("group", "candidate group ordering differs"),
        ("neighbors", "does not authorize parameter neighbors"),
        ("holdout", "authority boundary differs"),
        ("policy", "qualification policy differs"),
    ),
)
@pytest.mark.parametrize("plan_path", (INTRADAY_V1_PLAN, INTRADAY_V2_PLAN))
def test_intraday_campaigns_reject_post_registration_variation(
    plan_path: Path, defect: str, message: str
) -> None:
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    if defect == "strategy":
        payload["strategies"][1]["parameters"]["lookback"] = 2
    elif defect == "period":
        payload["periods"][1]["start_timestamp"] = "2026-01-05T14:30:00Z"
    elif defect == "cost":
        payload["cost_models"][2]["slippage_bps"] = "5"
    elif defect == "ordered-cost-change":
        payload["cost_models"][2]["slippage_bps"] = "21"
    elif defect == "group":
        payload["candidate_groups"][1]["ordinal_start"] = 7
    elif defect == "neighbors":
        payload["parameter_neighbors"] = [{"window": 11}]
    elif defect == "holdout":
        payload["authorities"]["protected_holdout"] = True
    else:
        payload["qualification_policy_fingerprint"] = "changed"

    with pytest.raises(ValueError, match=message):
        parse_intraday_research_campaign_plan(payload)
