"""Strict machine-readable plans for controlled research campaigns."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .calendar import expected_bar_timestamps, expected_sessions
from .config import non_broker_subprocess_environment
from .domain import Timeframe
from .experiments import ExperimentSpec, ExperimentSplit, IntradayExperimentSpec
from .fingerprints import canonical_json, fingerprint
from .intraday_campaigns import get_intraday_campaign_contract
from .intraday_qualification import REVIEWED_POLICY_FINGERPRINT
from .providers import ALPACA_HISTORICAL_PROVIDER_NAME

_ROOT_FIELDS = {
    "schema_version",
    "campaign_id",
    "name",
    "search_budget",
    "code_commit",
    "dataset_id",
    "dataset_fingerprint",
    "universe_id",
    "universe_fingerprint",
    "candidates",
}
_CANDIDATE_FIELDS = {
    "experiment_id",
    "role",
    "strategy_id",
    "strategy_version",
    "strategy_family",
    "parameters",
    "start_timestamp",
    "end_timestamp",
    "random_seed",
    "creation_reason",
    "parent_candidate",
}
_STRATEGIES: dict[str, tuple[str, frozenset[str]]] = {
    "cash": ("baseline", frozenset()),
    "buy-and-hold": ("baseline", frozenset()),
    "fixed-weight": ("allocation", frozenset()),
    "moving-average-trend": ("trend", frozenset({"window"})),
    "moving-average-mean-reversion": ("mean-reversion", frozenset({"window"})),
    "time-series-momentum": ("momentum", frozenset({"lookback"})),
    "volatility-targeted-exposure": ("volatility", frozenset({"volatility_window"})),
    "relative-strength-portfolio": (
        "portfolio-momentum",
        frozenset({"lookback", "rebalance_every", "selection_count"}),
    ),
    "risk-managed-momentum-portfolio": (
        "portfolio-momentum",
        frozenset({"lookback", "volatility_window", "rebalance_every"}),
    ),
    "volatility-balanced-portfolio": (
        "portfolio-allocation",
        frozenset({"volatility_window", "rebalance_every"}),
    ),
    "strategic-allocation-portfolio": (
        "portfolio-allocation",
        frozenset({"rebalance_every"}),
    ),
}
_PARAMETER_MINIMUMS = {
    "moving-average-trend": {"window": 2},
    "moving-average-mean-reversion": {"window": 2},
    "risk-managed-momentum-portfolio": {"volatility_window": 2},
    "volatility-balanced-portfolio": {"volatility_window": 2},
    "volatility-targeted-exposure": {"volatility_window": 2},
}

_INTRADAY_ROOT_FIELDS = {
    "schema_version",
    "campaign_id",
    "name",
    "status",
    "purpose",
    "base_code_commit",
    "search_budget",
    "provider",
    "feed",
    "adjustment",
    "timeframe",
    "symbols",
    "session_policy_version",
    "bar_timestamp_semantics_version",
    "session_return_policy_version",
    "benchmark_policy_version",
    "qualification_policy_id",
    "qualification_policy_fingerprint",
    "periods",
    "strategies",
    "cost_models",
    "execution_delays",
    "candidate_groups",
    "parameter_neighbors",
    "authorities",
    "change_control",
}
_INTRADAY_PERIOD_FIELDS = {
    "role",
    "split",
    "new_york_session_start",
    "new_york_session_end",
    "start_timestamp",
    "end_timestamp",
}
_INTRADAY_STRATEGY_FIELDS = {"strategy_id", "strategy_family", "parameters"}
_INTRADAY_COST_FIELDS = {"role", "version", "slippage_bps", "commission_bps"}
_INTRADAY_DELAY_FIELDS = {"role", "execution_delay_bars"}
_INTRADAY_GROUP_FIELDS = {"strategy_id", "period_role", "ordinal_start"}
_INTRADAY_AUTHORITIES = {
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}
_INTRADAY_STRATEGIES: tuple[tuple[str, str, Mapping[str, object]], ...] = (
    ("intraday-cash", "intraday-cash-baseline", {}),
    (
        "intraday-previous-bar-momentum",
        "intraday-directional-momentum",
        {"lookback": 1},
    ),
    ("intraday-moving-average-trend", "intraday-trend", {"window": 12}),
)
_INTRADAY_PERIOD_ROLES = ("training", "validation-a", "validation-b", "validation-c")
_INTRADAY_VARIANT_ROLES = (
    "base",
    "increased-cost",
    "harsher-cost",
    "plus-1-bar",
    "plus-2-bars",
)
REVIEWED_INTRADAY_CAMPAIGN_V1_FINGERPRINT = (
    "ce81be36d02cc15f421390bf3d3787714bb0b025797ccfb8de2c1d1236052c1a"
)
REVIEWED_INTRADAY_UNIVERSE_ID = "liquid-etfs-intraday-5m-v1"
REVIEWED_INTRADAY_UNIVERSE_FINGERPRINT = (
    "6ac4a8269f8e352536f52ddc0a3000e0b39c5551c33c03959c20a640cfddeca9"
)

RAPID_002_CAMPAIGN_ID = "rapid-002-rmm-40-40-10-controlled-v1"
RAPID_002_CANDIDATE_ID = "rr-a480ff073a90e448c8b2"
RAPID_002_CANDIDATE_FINGERPRINT = "1efe7aa4043fd6dcab7e34025e70b1a45c03a5d2ca6e15f520af3ef9a4742bf9"
RAPID_002_CANDIDATE_EXPORT_SHA256 = (
    "63a8c70b8e5d2cbb0142a5ccb0909a0ab739a543bf5b000930b32f6589c072ba"
)
RAPID_002_DATASET_ID = "508c606884112c92402707c30b56fc9d8c07cfc1c01c64f8538a6494888eeeca"
RAPID_002_DATASET_FINGERPRINT = "4fe62ab615ae713e23926da940256b9a728db39c2bc60c028df6d1136be49494"
RAPID_002_UNIVERSE_ID = "liquid-etfs-v1"
RAPID_002_UNIVERSE_FINGERPRINT = "cb0827988973c61362f2014c3f20fde53081217a32fa70f04a5a9e1a48b01985"
RAPID_002_EVIDENCE_MANIFEST_ID = "qualification-evidence-rapid-002-rmm-v1"
RAPID_002_EVIDENCE_MANIFEST_FINGERPRINT = (
    "b997afb53fdf05ef26be72934fb3318cb582ba503f4527fa9ca96f88f7b72693"
)
RAPID_002_PROPOSAL_ID = "qualification-gates-rapid-002-rmm-v1"
RAPID_002_PROPOSAL_FINGERPRINT = "fa168aa162de2d7e244d32bcc980d5e3c3c7baf127562b17c0aa40a8cc955fb0"
RAPID_002_BASE_COMMIT = "07fc39e542c468cd3592f41bf13a9e1cb08ea276"
RAPID_002_SOURCE_PRESERVATION_COMMIT = "3025987959057642639fed313424497217c45f44"
RAPID_002_CONTROL_BINDING_COMMIT = "94049895f39d1b19c36e0dd7f375145e63d5aa06"
RAPID_002_SOURCE_FINGERPRINT = "fc927594a1ac7efb5cf7dadd9667c5d00b17d2cb3c380841fb22f7e0fb336d16"
RAPID_002_STRATEGY_PATH = "src/systematic_trading_lab/strategies.py"
RAPID_002_STRATEGY_SHA256 = "4be05a18badf460f60016f9401206d5dcf3c89ea270835991f11aae3754085af"

_RAPID_002_AUTHORITY = {
    "independent_evaluation": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
    "automatic_promotion": False,
    "v3_access": False,
}
_RAPID_002_CANDIDATE_AUTHORITY = {
    "controlled_research_evidence": False,
    "qualification": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
    "automatic_promotion": False,
}
_RAPID_002_FOLDS = {
    2023: ("2023-01-03T00:00:00Z", "2023-12-29T00:00:00Z", 250),
    2024: ("2024-01-02T00:00:00Z", "2024-12-31T00:00:00Z", 252),
    2025: ("2025-01-02T00:00:00Z", "2025-12-31T00:00:00Z", 250),
}


@dataclass(frozen=True)
class TrainingCampaignPlan:
    campaign_id: str
    name: str
    search_budget: int
    code_commit: str
    dataset_id: str
    dataset_fingerprint: str
    universe_id: str
    universe_fingerprint: str
    candidates: tuple[ExperimentSpec, ...]
    payload: Mapping[str, object]
    plan_fingerprint: str


@dataclass(frozen=True)
class ControlledValidationReservation:
    ordinal: int
    role: str
    spec: ExperimentSpec
    initial_cash: Decimal
    slippage_bps: Decimal
    commission_bps: Decimal
    fill_delay_bars: int


@dataclass(frozen=True)
class ControlledValidationCampaignPlan:
    campaign_id: str
    name: str
    search_budget: int
    execution_source: Mapping[str, object]
    evidence_manifest_id: str
    evidence_manifest_fingerprint: str
    proposal_id: str
    proposal_fingerprint: str
    candidates: tuple[ControlledValidationReservation, ...]
    payload: Mapping[str, object]
    plan_fingerprint: str


@dataclass(frozen=True)
class IntradayPeriod:
    role: str
    split: ExperimentSplit
    new_york_session_start: date
    new_york_session_end: date
    start_timestamp: datetime
    end_timestamp: datetime


@dataclass(frozen=True)
class IntradayCandidateReservation:
    experiment_id: str
    candidate_ordinal: int
    strategy_id: str
    strategy_family: str
    parameters: Mapping[str, object]
    period_role: str
    split: ExperimentSplit
    start_timestamp: datetime
    end_timestamp: datetime
    variant_role: str
    parent_candidate: str | None
    cost_model_version: str
    slippage_bps: Decimal
    commission_bps: Decimal
    execution_delay_bars: int


@dataclass(frozen=True)
class IntradayResearchCampaignPlan:
    campaign_id: str
    name: str
    search_budget: int
    base_code_commit: str
    periods: tuple[IntradayPeriod, ...]
    candidates: tuple[IntradayCandidateReservation, ...]
    payload: Mapping[str, object]
    plan_fingerprint: str


def load_training_campaign_plan(path: Path) -> TrainingCampaignPlan:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return parse_training_campaign_plan(raw)


def parse_training_campaign_plan(raw: object) -> TrainingCampaignPlan:
    if not isinstance(raw, dict) or set(raw) != _ROOT_FIELDS:
        raise ValueError("training campaign plan fields differ")
    if raw["schema_version"] != "training-campaign-plan-v1":
        raise ValueError("training campaign plan schema differs")
    text = {
        field: _text(raw[field], field)
        for field in (
            "campaign_id",
            "name",
            "code_commit",
            "dataset_id",
            "dataset_fingerprint",
            "universe_id",
            "universe_fingerprint",
        )
    }
    budget = raw["search_budget"]
    candidates = raw["candidates"]
    if type(budget) is not int or budget < 1:
        raise ValueError("training campaign search budget must be positive")
    if not isinstance(candidates, list) or len(candidates) != budget:
        raise ValueError("training campaign candidates must fill the search budget")

    specs: list[ExperimentSpec] = []
    identifiers: set[str] = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict) or set(candidate) != _CANDIDATE_FIELDS:
            raise ValueError(f"training candidate {index} fields differ")
        experiment_id = _text(candidate["experiment_id"], "experiment ID")
        if experiment_id in identifiers:
            raise ValueError("training candidate IDs must be unique")
        parent = candidate["parent_candidate"]
        if parent is not None and (not isinstance(parent, str) or parent not in identifiers):
            raise ValueError("training candidate parent must be declared earlier")
        strategy_id = _text(candidate["strategy_id"], "strategy ID")
        contract = _STRATEGIES.get(strategy_id)
        if contract is None:
            raise ValueError(f"unsupported planned strategy: {strategy_id}")
        family, parameter_names = contract
        parameters = candidate["parameters"]
        minimums = _PARAMETER_MINIMUMS.get(strategy_id, {})
        if (
            not isinstance(parameters, dict)
            or set(parameters) != parameter_names
            or any(
                type(value) is not int or value < minimums.get(name, 1)
                for name, value in parameters.items()
            )
        ):
            raise ValueError(f"planned parameters differ for {strategy_id}")
        if candidate["strategy_family"] != family:
            raise ValueError(f"planned strategy family differs for {strategy_id}")
        if candidate["strategy_version"] != "1":
            raise ValueError("planned strategy version must be 1")
        _text(candidate["role"], "candidate role")
        random_seed = candidate["random_seed"]
        if type(random_seed) is not int or random_seed < 0:
            raise ValueError("planned random seed must be a non-negative integer")
        specs.append(
            ExperimentSpec(
                experiment_id=experiment_id,
                campaign_id=text["campaign_id"],
                strategy_id=strategy_id,
                strategy_version="1",
                strategy_family=family,
                code_commit=text["code_commit"],
                dataset_id=text["dataset_id"],
                dataset_fingerprint=text["dataset_fingerprint"],
                universe_id=text["universe_id"],
                universe_fingerprint=text["universe_fingerprint"],
                parameters=parameters,
                cost_model_version="conservative-bps-v1",
                execution_model_version="next-bar-v1",
                split=ExperimentSplit.TRAINING,
                start_timestamp=_utc(candidate["start_timestamp"]),
                end_timestamp=_utc(candidate["end_timestamp"]),
                random_seed=random_seed,
                creation_reason=_text(candidate["creation_reason"], "creation reason"),
                parent_candidate=parent,
            )
        )
        identifiers.add(experiment_id)

    return TrainingCampaignPlan(
        campaign_id=text["campaign_id"],
        name=text["name"],
        search_budget=budget,
        code_commit=text["code_commit"],
        dataset_id=text["dataset_id"],
        dataset_fingerprint=text["dataset_fingerprint"],
        universe_id=text["universe_id"],
        universe_fingerprint=text["universe_fingerprint"],
        candidates=tuple(specs),
        payload=raw,
        plan_fingerprint=fingerprint(raw),
    )


def parse_daily_campaign_plan(
    raw: object,
) -> TrainingCampaignPlan | ControlledValidationCampaignPlan:
    if (
        isinstance(raw, dict)
        and raw.get("schema_version") == "controlled-validation-campaign-plan-v1"
    ):
        return parse_controlled_validation_campaign_plan(raw)
    return parse_training_campaign_plan(raw)


def build_rapid_002_controlled_plan() -> ControlledValidationCampaignPlan:
    source = rapid_002_execution_source_identity()
    commit = source["execution_code_commit"]
    assert isinstance(commit, str)
    return parse_controlled_validation_campaign_plan(_rapid_002_plan_payload(commit))


def parse_controlled_validation_campaign_plan(
    raw: object,
) -> ControlledValidationCampaignPlan:
    if not isinstance(raw, dict):
        raise ValueError("controlled validation campaign plan must be an object")
    source = raw.get("execution_source")
    if not isinstance(source, dict):
        raise ValueError("controlled validation execution source is malformed")
    commit = _git_sha(source.get("execution_code_commit"), "controlled execution commit")
    expected = _rapid_002_plan_payload(commit)
    if raw != expected:
        raise ValueError("Rapid-002 controlled validation plan differs")
    for year, (start, end, count) in _RAPID_002_FOLDS.items():
        sessions = expected_sessions(_utc(start), _utc(end))
        if len(sessions) != count or sessions[0].year != year or sessions[-1].year != year:
            raise ValueError("Rapid-002 XNYS validation folds differ")

    reservations: list[ControlledValidationReservation] = []
    for candidate in _rapid_002_candidates():
        parameters = candidate["parameters"]
        ordinal = candidate["ordinal"]
        fill_delay_bars = candidate["fill_delay_bars"]
        assert isinstance(parameters, dict)
        assert type(ordinal) is int
        assert type(fill_delay_bars) is int
        spec = ExperimentSpec(
            experiment_id=str(candidate["experiment_id"]),
            campaign_id=RAPID_002_CAMPAIGN_ID,
            strategy_id=str(candidate["strategy_id"]),
            strategy_version="1",
            strategy_family=str(candidate["strategy_family"]),
            code_commit=commit,
            dataset_id=RAPID_002_DATASET_ID,
            dataset_fingerprint=RAPID_002_DATASET_FINGERPRINT,
            universe_id=RAPID_002_UNIVERSE_ID,
            universe_fingerprint=RAPID_002_UNIVERSE_FINGERPRINT,
            parameters=parameters,
            cost_model_version=str(candidate["cost_model_version"]),
            execution_model_version=str(candidate["execution_model_version"]),
            split=ExperimentSplit.VALIDATION,
            start_timestamp=_utc(candidate["start_timestamp"]),
            end_timestamp=_utc(candidate["end_timestamp"]),
            random_seed=0,
            creation_reason=str(candidate["creation_reason"]),
            parent_candidate=(
                None
                if candidate["parent_candidate"] is None
                else str(candidate["parent_candidate"])
            ),
        )
        reservations.append(
            ControlledValidationReservation(
                ordinal=ordinal,
                role=str(candidate["role"]),
                spec=spec,
                initial_cash=Decimal("100000"),
                slippage_bps=Decimal(str(candidate["slippage_bps"])),
                commission_bps=Decimal(str(candidate["commission_bps"])),
                fill_delay_bars=fill_delay_bars,
            )
        )
    return ControlledValidationCampaignPlan(
        campaign_id=RAPID_002_CAMPAIGN_ID,
        name="Rapid-002 risk-managed momentum controlled validation",
        search_budget=28,
        execution_source=source,
        evidence_manifest_id=RAPID_002_EVIDENCE_MANIFEST_ID,
        evidence_manifest_fingerprint=RAPID_002_EVIDENCE_MANIFEST_FINGERPRINT,
        proposal_id=RAPID_002_PROPOSAL_ID,
        proposal_fingerprint=RAPID_002_PROPOSAL_FINGERPRINT,
        candidates=tuple(reservations),
        payload=raw,
        plan_fingerprint=fingerprint(raw),
    )


def rapid_002_execution_source_identity(*, require_merged_main: bool = True) -> dict[str, object]:
    from .rapid_research import _code_identity

    identity = _code_identity()
    commit = _git_sha(identity.get("commit"), "controlled execution commit")
    if identity.get("dirty") is not False or identity.get("working_tree_fingerprint") is not None:
        raise ValueError("Rapid-002 controlled execution requires a clean source checkout")
    repository = Path(__file__).resolve().parents[2]
    if (repository / RAPID_002_STRATEGY_PATH).resolve() != Path(__file__).resolve().parent.joinpath(
        "strategies.py"
    ):
        raise ValueError("Rapid-002 controlled execution source is not the repository checkout")
    environment = non_broker_subprocess_environment()
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": "/nonexistent",
            "XDG_CONFIG_HOME": "/nonexistent",
        }
    )
    git = ("git", "--no-replace-objects", "-c", "core.fsmonitor=false")
    main_commits: set[str] | None = None
    try:
        checkout_status = subprocess.run(
            (*git, "status", "--porcelain=v1", "--untracked-files=all"),
            check=True,
            capture_output=True,
            cwd=repository,
            env=environment,
            timeout=5,
        ).stdout
        for ancestor in (
            RAPID_002_SOURCE_PRESERVATION_COMMIT,
            RAPID_002_CONTROL_BINDING_COMMIT,
        ):
            subprocess.run(
                (*git, "merge-base", "--is-ancestor", ancestor, commit),
                check=True,
                capture_output=True,
                cwd=repository,
                env=environment,
                timeout=5,
            )
        if require_merged_main:
            main_commits = {
                subprocess.run(
                    (*git, "rev-parse", "--verify", reference),
                    check=True,
                    capture_output=True,
                    cwd=repository,
                    env=environment,
                    text=True,
                    timeout=5,
                ).stdout.strip()
                for reference in ("refs/heads/main", "refs/remotes/origin/main")
            }
        source_diff = subprocess.run(
            (
                *git,
                "diff",
                "--binary",
                "--no-ext-diff",
                "--no-textconv",
                RAPID_002_BASE_COMMIT,
                RAPID_002_SOURCE_PRESERVATION_COMMIT,
                "--",
                "src/systematic_trading_lab",
                "pyproject.toml",
                "uv.lock",
            ),
            check=True,
            capture_output=True,
            cwd=repository,
            env=environment,
            timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("Rapid-002 controlled execution source ancestry is invalid") from error
    if checkout_status:
        raise ValueError("Rapid-002 controlled execution requires a clean checkout")
    if require_merged_main and main_commits != {commit}:
        raise ValueError("Rapid-002 controlled execution requires exact merged main")
    if hashlib.sha256(source_diff).hexdigest() != RAPID_002_SOURCE_FINGERPRINT:
        raise ValueError("Rapid-002 preserved source fingerprint differs")
    if (
        hashlib.sha256((repository / RAPID_002_STRATEGY_PATH).read_bytes()).hexdigest()
        != RAPID_002_STRATEGY_SHA256
    ):
        raise ValueError("Rapid-002 strategy source fingerprint differs")
    return _rapid_002_source_payload(commit)


def verify_rapid_002_candidate_export(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != RAPID_002_CANDIDATE_EXPORT_SHA256:
        raise ValueError("Rapid-002 candidate export SHA-256 differs")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or (canonical_json(payload) + "\n").encode() != raw:
        raise ValueError("Rapid-002 candidate export is not canonical JSON")
    candidate_fingerprint = payload.pop("candidate_fingerprint", None)
    if (
        candidate_fingerprint != RAPID_002_CANDIDATE_FINGERPRINT
        or fingerprint(payload) != RAPID_002_CANDIDATE_FINGERPRINT
        or payload.get("authority") != _RAPID_002_CANDIDATE_AUTHORITY
    ):
        raise ValueError("Rapid-002 candidate export identity differs")
    selected = payload.get("selected_run")
    if (
        not isinstance(selected, dict)
        or payload.get("selected_run_id") != RAPID_002_CANDIDATE_ID
        or selected.get("run_id") != RAPID_002_CANDIDATE_ID
    ):
        raise ValueError("Rapid-002 selected candidate differs")
    specification = selected.get("specification")
    if not isinstance(specification, dict):
        raise ValueError("Rapid-002 candidate specification is missing")
    expected = {
        "code": {
            "commit": RAPID_002_BASE_COMMIT,
            "dirty": True,
            "working_tree_fingerprint": RAPID_002_SOURCE_FINGERPRINT,
        },
        "dataset": {
            "id": RAPID_002_DATASET_ID,
            "fingerprint": RAPID_002_DATASET_FINGERPRINT,
            "source": "alpaca-historical-v2",
            "symbols": ["GLD", "IWM", "QQQ", "SPY", "TLT"],
            "timeframe": "1d",
        },
        "strategy": {
            "family": "portfolio-momentum",
            "id": "risk-managed-momentum-portfolio",
            "name": "risk-managed-momentum",
            "parameters": {"lookback": 40, "rebalance_every": 10, "volatility_window": 40},
            "version": "1",
        },
        "costs": {"commission_bps": "1", "slippage_bps": "5", "version": "conservative-bps-v1"},
        "execution": {"fill_delay_bars": 1, "model": "deterministic-next-bar-open-v1"},
        "initial_cash": "100000",
        "start_timestamp": "2025-01-02T00:00:00Z",
        "end_timestamp": "2025-12-31T00:00:00Z",
    }
    if any(specification.get(key) != value for key, value in expected.items()):
        raise ValueError("Rapid-002 candidate specification differs")
    ledger = payload.get("search_ledger")
    if not isinstance(ledger, list) or payload.get("search_ledger_fingerprint") != fingerprint(
        ledger
    ):
        raise ValueError("Rapid-002 candidate search ledger differs")
    return {
        "path": str(path.resolve()),
        "candidate_id": RAPID_002_CANDIDATE_ID,
        "candidate_fingerprint": RAPID_002_CANDIDATE_FINGERPRINT,
        "file_sha256": RAPID_002_CANDIDATE_EXPORT_SHA256,
        "authority": dict(_RAPID_002_CANDIDATE_AUTHORITY),
    }


def validate_rapid_002_dataset_manifest(manifest: Mapping[str, object]) -> None:
    identity = manifest.get("identity")
    expected = {
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
        "universe_id": RAPID_002_UNIVERSE_ID,
        "universe_fingerprint": RAPID_002_UNIVERSE_FINGERPRINT,
    }
    if identity != {
        "dataset_id": RAPID_002_DATASET_ID,
        "fingerprint": RAPID_002_DATASET_FINGERPRINT,
    } or any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("Rapid-002 controlled dataset manifest differs")


def validate_rapid_002_control_binding(
    plan: ControlledValidationCampaignPlan,
    manifest: object,
    proposal: object,
) -> None:
    from .qualification import QualificationProposal
    from .qualification_evidence import QualificationEvidenceManifest, evidence_manifest_fingerprint

    if (
        not isinstance(manifest, QualificationEvidenceManifest)
        or not isinstance(proposal, QualificationProposal)
        or manifest.manifest_id != plan.evidence_manifest_id
        or manifest.campaign_id != plan.campaign_id
        or evidence_manifest_fingerprint(manifest) != plan.evidence_manifest_fingerprint
        or proposal.proposal_id != plan.proposal_id
        or proposal.evidence_campaign_id != plan.campaign_id
        or fingerprint(proposal) != plan.proposal_fingerprint
    ):
        raise ValueError("Rapid-002 qualification binding differs")
    if len(manifest.candidates) != 1:
        raise ValueError("Rapid-002 qualification candidate count differs")
    candidate = manifest.candidates[0]
    evidence_ids = (
        candidate.base_validation_ids
        + candidate.benchmark_validation_ids
        + candidate.cost_sensitivity_ids
        + candidate.delay_sensitivity_ids
        + candidate.parameter_neighbor_ids
        + tuple(stress.experiment_id for stress in candidate.combined_stresses)
    )
    planned_ids = tuple(reservation.spec.experiment_id for reservation in plan.candidates)
    if len(evidence_ids) != 28 or set(evidence_ids) != set(planned_ids):
        raise ValueError("Rapid-002 qualification evidence IDs differ from the controlled plan")


def controlled_validation_reservation(
    plan: ControlledValidationCampaignPlan, experiment_id: str
) -> ControlledValidationReservation:
    reservation = next(
        (
            candidate
            for candidate in plan.candidates
            if candidate.spec.experiment_id == experiment_id
        ),
        None,
    )
    if reservation is None:
        raise ValueError(f"candidate is not reserved by the controlled plan: {experiment_id}")
    return reservation


def _rapid_002_plan_payload(execution_code_commit: str) -> dict[str, object]:
    _git_sha(execution_code_commit, "controlled execution commit")
    return {
        "schema_version": "controlled-validation-campaign-plan-v1",
        "campaign_id": RAPID_002_CAMPAIGN_ID,
        "name": "Rapid-002 risk-managed momentum controlled validation",
        "status": "preregistered",
        "search_budget": 28,
        "execution_source": _rapid_002_source_payload(execution_code_commit),
        "candidate_artifact": {
            "candidate_id": RAPID_002_CANDIDATE_ID,
            "candidate_fingerprint": RAPID_002_CANDIDATE_FINGERPRINT,
            "candidate_export_sha256": RAPID_002_CANDIDATE_EXPORT_SHA256,
            "authority": dict(_RAPID_002_CANDIDATE_AUTHORITY),
        },
        "dataset": {
            "dataset_id": RAPID_002_DATASET_ID,
            "dataset_fingerprint": RAPID_002_DATASET_FINGERPRINT,
            "provider": "alpaca-historical-v2",
            "adjustment_policy": "provider-adjusted-all-v1",
            "timeframe": "1d",
            "symbols": ["SPY", "QQQ", "IWM", "TLT", "GLD"],
            "universe_id": RAPID_002_UNIVERSE_ID,
            "universe_fingerprint": RAPID_002_UNIVERSE_FINGERPRINT,
        },
        "initial_cash": "100000",
        "random_seed": 0,
        "qualification": {
            "evidence_manifest_id": RAPID_002_EVIDENCE_MANIFEST_ID,
            "evidence_manifest_fingerprint": RAPID_002_EVIDENCE_MANIFEST_FINGERPRINT,
            "proposal_id": RAPID_002_PROPOSAL_ID,
            "proposal_fingerprint": RAPID_002_PROPOSAL_FINGERPRINT,
        },
        "candidates": _rapid_002_candidates(),
        "authorities": dict(_RAPID_002_AUTHORITY),
        "change_control": "no-retry-no-reselection-after-seal",
    }


def _rapid_002_source_payload(execution_code_commit: str) -> dict[str, object]:
    return {
        "execution_code_commit": execution_code_commit,
        "rapid_base_commit": RAPID_002_BASE_COMMIT,
        "source_preservation_commit": RAPID_002_SOURCE_PRESERVATION_COMMIT,
        "control_binding_commit": RAPID_002_CONTROL_BINDING_COMMIT,
        "rapid_source_fingerprint": RAPID_002_SOURCE_FINGERPRINT,
        "strategy_path": RAPID_002_STRATEGY_PATH,
        "strategy_sha256": RAPID_002_STRATEGY_SHA256,
    }


def _rapid_002_candidates() -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []

    def add(
        experiment_id: str,
        role: str,
        year: int,
        strategy_id: str,
        strategy_family: str,
        parameters: Mapping[str, int],
        cost_model_version: str = "conservative-bps-v1",
        slippage_bps: str = "5",
        commission_bps: str = "1",
        execution_model_version: str = "next-bar-v1",
        fill_delay_bars: int = 1,
        parent_candidate: str | None = None,
    ) -> None:
        start, end, _ = _RAPID_002_FOLDS[year]
        candidates.append(
            {
                "ordinal": len(candidates) + 1,
                "experiment_id": experiment_id,
                "role": role,
                "strategy_id": strategy_id,
                "strategy_version": "1",
                "strategy_family": strategy_family,
                "parameters": dict(parameters),
                "split": "validation",
                "start_timestamp": start,
                "end_timestamp": end,
                "cost_model_version": cost_model_version,
                "slippage_bps": slippage_bps,
                "commission_bps": commission_bps,
                "execution_model_version": execution_model_version,
                "fill_delay_bars": fill_delay_bars,
                "parent_candidate": parent_candidate,
                "creation_reason": f"frozen Rapid-002 {role} validation evidence",
            }
        )

    base = {"lookback": 40, "volatility_window": 40, "rebalance_every": 10}
    for year in _RAPID_002_FOLDS:
        add(
            f"r2-rmm-base-{year}",
            "base",
            year,
            "risk-managed-momentum-portfolio",
            "portfolio-momentum",
            base,
        )
    for year in _RAPID_002_FOLDS:
        add(f"r2-fixed-weight-{year}", "benchmark", year, "fixed-weight", "allocation", {})
    neighbors = (
        ("lookback30", {**base, "lookback": 30}),
        ("lookback50", {**base, "lookback": 50}),
        ("volatility30", {**base, "volatility_window": 30}),
        ("volatility50", {**base, "volatility_window": 50}),
        ("cadence5", {**base, "rebalance_every": 5}),
        ("cadence15", {**base, "rebalance_every": 15}),
    )
    for tag, parameters in neighbors:
        for year in _RAPID_002_FOLDS:
            add(
                f"r2-rmm-{tag}-{year}",
                f"neighbor-{tag}",
                year,
                "risk-managed-momentum-portfolio",
                "portfolio-momentum",
                parameters,
                parent_candidate=f"r2-rmm-base-{year}",
            )
    add(
        "r2-rmm-cost2x-2025",
        "isolated-cost",
        2025,
        "risk-managed-momentum-portfolio",
        "portfolio-momentum",
        base,
        "bps-10-2-v1",
        "10",
        "2",
        parent_candidate="r2-rmm-base-2025",
    )
    add(
        "r2-rmm-delay2-2025",
        "isolated-delay",
        2025,
        "risk-managed-momentum-portfolio",
        "portfolio-momentum",
        base,
        execution_model_version="delayed-2-bars-v1",
        fill_delay_bars=2,
        parent_candidate="r2-rmm-base-2025",
    )
    add(
        "r2-rmm-stress-a-2025",
        "stress-a",
        2025,
        "risk-managed-momentum-portfolio",
        "portfolio-momentum",
        base,
        "bps-10-2-v1",
        "10",
        "2",
        "delayed-2-bars-v1",
        2,
        "r2-rmm-base-2025",
    )
    add(
        "r2-rmm-stress-b-2025",
        "stress-b",
        2025,
        "risk-managed-momentum-portfolio",
        "portfolio-momentum",
        base,
        "bps-20-5-v1",
        "20",
        "5",
        "delayed-3-bars-v1",
        3,
        "r2-rmm-base-2025",
    )
    return candidates


def _git_sha(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a full lowercase Git SHA")
    return value


def load_intraday_research_campaign_plan(path: Path) -> IntradayResearchCampaignPlan:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return parse_intraday_research_campaign_plan(raw)


def parse_intraday_research_campaign_plan(raw: object) -> IntradayResearchCampaignPlan:
    """Validate one closed M5B campaign preregistration without loading market data."""

    if not isinstance(raw, dict) or set(raw) != _INTRADAY_ROOT_FIELDS:
        raise ValueError("intraday research campaign plan fields differ")
    if raw["schema_version"] != "intraday-research-campaign-plan-v1":
        raise ValueError("intraday research campaign plan schema differs")
    campaign_id = _text(raw["campaign_id"], "intraday campaign ID")
    contract = get_intraday_campaign_contract(campaign_id)
    name = _text(raw["name"], "intraday campaign name")
    base_code_commit = _text(raw["base_code_commit"], "intraday base code commit")
    if raw["status"] != "preregistered":
        raise ValueError("intraday campaign must be preregistered")
    purpose = _text(raw["purpose"], "intraday campaign purpose")
    if "not financial validation" not in purpose.lower():
        raise ValueError("intraday campaign purpose must reject financial validation")
    if (
        raw["provider"] != "alpaca"
        or raw["feed"] != "iex"
        or raw["adjustment"] != "all"
        or raw["timeframe"] != "5m"
        or raw["symbols"] != ["SPY", "QQQ"]
    ):
        raise ValueError("intraday campaign data contract differs")
    expected_versions = {
        "session_policy_version": "XNYS-regular-session-flat-v1",
        "bar_timestamp_semantics_version": "bar-open-utc-v1",
        "session_return_policy_version": "XNYS-session-close-equity-v1",
        "benchmark_policy_version": "cash-and-continuous-underlying-v1",
    }
    if any(raw[field] != value for field, value in expected_versions.items()):
        raise ValueError("intraday campaign replay contract differs")
    if (
        raw["qualification_policy_id"] != "intraday-qualification-policy-v1"
        or raw["qualification_policy_fingerprint"] != REVIEWED_POLICY_FINGERPRINT
    ):
        raise ValueError("intraday campaign qualification policy differs")
    if raw["parameter_neighbors"] != []:
        raise ValueError("intraday campaign does not authorize parameter neighbors")
    if raw["authorities"] != _INTRADAY_AUTHORITIES:
        raise ValueError("intraday campaign authority boundary differs")
    if raw["change_control"] != "new-version-required-after-first-observed-result":
        raise ValueError("intraday campaign change control differs")
    periods = _intraday_periods(raw["periods"])
    strategies = _intraday_strategies(raw["strategies"])
    costs = _intraday_costs(raw["cost_models"])
    delays = _intraday_delays(raw["execution_delays"])
    candidates = _intraday_candidates(
        campaign_id,
        raw["candidate_groups"],
        periods,
        strategies,
        costs,
        delays,
    )
    budget = raw["search_budget"]
    if type(budget) is not int or budget != len(candidates):
        raise ValueError("intraday campaign search budget must equal reserved candidates")
    plan_fingerprint = fingerprint(raw)
    if (
        plan_fingerprint != contract.plan_fingerprint
        or base_code_commit != contract.foundation_commit
    ):
        raise ValueError("intraday campaign differs from its reviewed preregistration")
    return IntradayResearchCampaignPlan(
        campaign_id=campaign_id,
        name=name,
        search_budget=budget,
        base_code_commit=base_code_commit,
        periods=periods,
        candidates=candidates,
        payload=raw,
        plan_fingerprint=plan_fingerprint,
    )


def build_planned_intraday_experiment(
    plan: IntradayResearchCampaignPlan,
    experiment_id: str,
    manifest: Mapping[str, object],
) -> IntradayExperimentSpec:
    """Bind one stored reservation to an exact validated Alpaca dataset manifest."""

    reservation = next(
        (candidate for candidate in plan.candidates if candidate.experiment_id == experiment_id),
        None,
    )
    if reservation is None:
        raise ValueError(f"intraday candidate is not reserved by the plan: {experiment_id}")
    period = next(period for period in plan.periods if period.role == reservation.period_role)
    dataset_id, dataset_fingerprint, universe_id, universe_fingerprint = (
        _planned_intraday_dataset_identity(period, manifest)
    )
    return IntradayExperimentSpec(
        experiment_id=reservation.experiment_id,
        campaign_id=plan.campaign_id,
        search_budget=plan.search_budget,
        candidate_ordinal=reservation.candidate_ordinal,
        strategy_id=reservation.strategy_id,
        strategy_version="1",
        strategy_family=reservation.strategy_family,
        code_commit=plan.base_code_commit,
        dataset_id=dataset_id,
        dataset_fingerprint=dataset_fingerprint,
        universe_id=universe_id,
        universe_fingerprint=universe_fingerprint,
        parameters=reservation.parameters,
        timeframe="5m",
        session_policy_version="XNYS-regular-session-flat-v1",
        bar_timestamp_semantics_version="bar-open-utc-v1",
        session_return_policy_version="XNYS-session-close-equity-v1",
        benchmark_policy_version="cash-and-continuous-underlying-v1",
        cost_model_version=reservation.cost_model_version,
        slippage_bps=reservation.slippage_bps,
        commission_bps=reservation.commission_bps,
        execution_model_version="deterministic-next-bar-open-v1",
        earliest_fill_semantics="completed-bar-next-bar-open-v1",
        execution_delay_bars=reservation.execution_delay_bars,
        split=reservation.split,
        start_timestamp=reservation.start_timestamp,
        end_timestamp=reservation.end_timestamp,
        random_seed=0,
        creation_reason=(
            f"preregistered {reservation.variant_role} evidence for "
            f"{reservation.strategy_id} {reservation.period_role}"
        ),
        parent_candidate=reservation.parent_candidate,
    )


def build_planned_intraday_experiments(
    plan: IntradayResearchCampaignPlan,
    manifests: Mapping[str, Mapping[str, object]],
) -> tuple[IntradayExperimentSpec, ...]:
    """Bind all reservations to one exact dataset per frozen period before any run."""

    expected_roles = {period.role for period in plan.periods}
    if set(manifests) != expected_roles:
        raise ValueError("intraday campaign dataset roles differ from the sealed periods")
    return tuple(
        build_planned_intraday_experiment(
            plan,
            candidate.experiment_id,
            manifests[candidate.period_role],
        )
        for candidate in plan.candidates
    )


def _planned_intraday_dataset_identity(
    period: IntradayPeriod,
    manifest: Mapping[str, object],
) -> tuple[str, str, str, str]:
    identity = manifest.get("identity")
    requested = manifest.get("requested_range")
    actual = manifest.get("actual_range")
    symbols = manifest.get("symbols")
    if (
        not isinstance(identity, Mapping)
        or not isinstance(requested, Mapping)
        or not isinstance(actual, Mapping)
        or not isinstance(symbols, list)
    ):
        raise ValueError("planned intraday dataset manifest is malformed")
    expected_range = {
        "start": period.start_timestamp.isoformat().replace("+00:00", "Z"),
        "end": period.end_timestamp.isoformat().replace("+00:00", "Z"),
    }
    if (
        manifest.get("provider") != ALPACA_HISTORICAL_PROVIDER_NAME
        or manifest.get("feed") != "iex"
        or manifest.get("timeframe") != "5m"
        or manifest.get("adjustment_policy") != "provider-adjusted-all-v1"
        or manifest.get("calendar_policy") != "XNYS-regular-session-bars-v1"
        or manifest.get("timestamp_policy") != "bar-open-utc-v1"
        or requested != expected_range
        or actual != expected_range
        or symbols != [{"value": "SPY"}, {"value": "QQQ"}]
        or manifest.get("universe_id") != REVIEWED_INTRADAY_UNIVERSE_ID
        or manifest.get("universe_fingerprint") != REVIEWED_INTRADAY_UNIVERSE_FINGERPRINT
    ):
        raise ValueError("dataset does not match the planned intraday period")
    dataset_id = _text(identity.get("dataset_id"), "planned intraday dataset ID")
    dataset_fingerprint = _text(identity.get("fingerprint"), "planned intraday dataset fingerprint")
    universe_id = _text(manifest.get("universe_id"), "planned intraday universe ID")
    universe_fingerprint = _text(
        manifest.get("universe_fingerprint"), "planned intraday universe fingerprint"
    )
    return dataset_id, dataset_fingerprint, universe_id, universe_fingerprint


def _intraday_periods(value: object) -> tuple[IntradayPeriod, ...]:
    if not isinstance(value, list) or len(value) != len(_INTRADAY_PERIOD_ROLES):
        raise ValueError("intraday campaign periods differ")
    periods: list[IntradayPeriod] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != _INTRADAY_PERIOD_FIELDS:
            raise ValueError(f"intraday period {index} fields differ")
        role = _text(item["role"], f"intraday period {index} role")
        if role != _INTRADAY_PERIOD_ROLES[index]:
            raise ValueError("intraday period role ordering differs")
        split = ExperimentSplit(_text(item["split"], f"intraday period {index} split"))
        expected_split = ExperimentSplit.TRAINING if index == 0 else ExperimentSplit.VALIDATION
        if split is not expected_split:
            raise ValueError("intraday period split ordering differs")
        session_start = _date(item["new_york_session_start"])
        session_end = _date(item["new_york_session_end"])
        start = _utc(item["start_timestamp"])
        end = _utc(item["end_timestamp"])
        if session_start > session_end or start > end:
            raise ValueError("intraday period range is reversed")
        expected_bars = expected_bar_timestamps(
            datetime.combine(session_start, time.min, UTC),
            datetime.combine(session_end, time.max, UTC),
            Timeframe.FIVE_MINUTES,
        )
        if not expected_bars or (start, end) != (expected_bars[0], expected_bars[-1]):
            raise ValueError("intraday period UTC bounds do not cover exact XNYS sessions")
        if periods and (
            periods[-1].new_york_session_end >= session_start or periods[-1].end_timestamp >= start
        ):
            raise ValueError("intraday campaign periods must be chronological and non-overlapping")
        periods.append(IntradayPeriod(role, split, session_start, session_end, start, end))
    return tuple(periods)


def _intraday_strategies(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) != len(_INTRADAY_STRATEGIES):
        raise ValueError("intraday campaign strategies differ")
    identifiers: list[str] = []
    for index, (item, expected) in enumerate(zip(value, _INTRADAY_STRATEGIES, strict=True)):
        if not isinstance(item, dict) or set(item) != _INTRADAY_STRATEGY_FIELDS:
            raise ValueError(f"intraday strategy {index} fields differ")
        strategy_id, family, parameters = expected
        if item != {
            "strategy_id": strategy_id,
            "strategy_family": family,
            "parameters": parameters,
        }:
            raise ValueError("intraday campaign fixed strategy contract differs")
        identifiers.append(strategy_id)
    return tuple(identifiers)


def _intraday_costs(value: object) -> dict[str, tuple[str, Decimal, Decimal]]:
    expected_roles = ("base", "increased-cost", "harsher-cost")
    if not isinstance(value, list) or len(value) != len(expected_roles):
        raise ValueError("intraday campaign cost models differ")
    costs: dict[str, tuple[str, Decimal, Decimal]] = {}
    totals: list[Decimal] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != _INTRADAY_COST_FIELDS:
            raise ValueError(f"intraday cost model {index} fields differ")
        role = _text(item["role"], f"intraday cost model {index} role")
        if role != expected_roles[index]:
            raise ValueError("intraday cost role ordering differs")
        model = _text(item["version"], f"intraday cost model {index} version")
        slippage = _decimal(item["slippage_bps"], f"intraday cost model {index} slippage")
        commission = _decimal(item["commission_bps"], f"intraday cost model {index} commission")
        if slippage < 0 or commission < 0:
            raise ValueError("intraday cost values must not be negative")
        costs[role] = (model, slippage, commission)
        totals.append(slippage + commission)
    if not totals[0] < totals[1] < totals[2]:
        raise ValueError("intraday cost stresses must increase in exact role order")
    return costs


def _intraday_delays(value: object) -> dict[str, int]:
    expected = {"baseline": 1, "plus-1-bar": 2, "plus-2-bars": 3}
    if not isinstance(value, list) or len(value) != len(expected):
        raise ValueError("intraday campaign execution delays differ")
    delays: dict[str, int] = {}
    for index, (item, (role, bars)) in enumerate(zip(value, expected.items(), strict=True)):
        if not isinstance(item, dict) or set(item) != _INTRADAY_DELAY_FIELDS:
            raise ValueError(f"intraday delay {index} fields differ")
        if item != {"role": role, "execution_delay_bars": bars}:
            raise ValueError("intraday delay role ordering differs")
        delays[role] = bars
    return delays


def _intraday_candidates(
    campaign_id: str,
    value: object,
    periods: tuple[IntradayPeriod, ...],
    strategies: tuple[str, ...],
    costs: Mapping[str, tuple[str, Decimal, Decimal]],
    delays: Mapping[str, int],
) -> tuple[IntradayCandidateReservation, ...]:
    expected_groups = [(strategy, period.role) for strategy in strategies for period in periods]
    if not isinstance(value, list) or len(value) != len(expected_groups):
        raise ValueError("intraday candidate groups differ")
    period_by_role = {period.role: period for period in periods}
    candidates: list[IntradayCandidateReservation] = []
    for group_index, (item, expected) in enumerate(zip(value, expected_groups, strict=True)):
        if not isinstance(item, dict) or set(item) != _INTRADAY_GROUP_FIELDS:
            raise ValueError(f"intraday candidate group {group_index} fields differ")
        ordinal_start = group_index * len(_INTRADAY_VARIANT_ROLES) + 1
        if item != {
            "strategy_id": expected[0],
            "period_role": expected[1],
            "ordinal_start": ordinal_start,
        }:
            raise ValueError("intraday candidate group ordering differs")
        strategy_slug = expected[0].removeprefix("intraday-")
        base_id = f"{campaign_id}-{strategy_slug}-{expected[1]}-base"
        period = period_by_role[expected[1]]
        for offset, variant in enumerate(_INTRADAY_VARIANT_ROLES):
            cost_role = variant if variant in costs else "base"
            delay_role = variant if variant in delays else "baseline"
            model, slippage, commission = costs[cost_role]
            experiment_id = (
                base_id
                if variant == "base"
                else f"{campaign_id}-{strategy_slug}-{expected[1]}-{variant}"
            )
            candidates.append(
                IntradayCandidateReservation(
                    experiment_id=experiment_id,
                    candidate_ordinal=ordinal_start + offset,
                    strategy_id=expected[0],
                    strategy_family=next(
                        family
                        for strategy, family, _ in _INTRADAY_STRATEGIES
                        if strategy == expected[0]
                    ),
                    parameters=next(
                        parameters
                        for strategy, _, parameters in _INTRADAY_STRATEGIES
                        if strategy == expected[0]
                    ),
                    period_role=expected[1],
                    split=period.split,
                    start_timestamp=period.start_timestamp,
                    end_timestamp=period.end_timestamp,
                    variant_role=variant,
                    parent_candidate=None if variant == "base" else base_id,
                    cost_model_version=model,
                    slippage_bps=slippage,
                    commission_bps=commission,
                    execution_delay_bars=delays[delay_role],
                )
            )
    return tuple(candidates)


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be non-empty text")
    return value


def _date(value: object) -> date:
    if not isinstance(value, str):
        raise ValueError("planned session date must be text")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("planned session date is invalid") from error


def _decimal(value: object, context: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be decimal text")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{context} is invalid") from error
    if not parsed.is_finite():
        raise ValueError(f"{context} is invalid")
    return parsed


def _utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("planned timestamp must be text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("planned timestamp is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("planned timestamp must be UTC")
    return parsed.astimezone(UTC)
