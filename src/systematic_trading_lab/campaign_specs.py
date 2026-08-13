"""Strict machine-readable plans for controlled research campaigns."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .calendar import expected_bar_timestamps
from .domain import Timeframe
from .experiments import ExperimentSpec, ExperimentSplit, IntradayExperimentSpec
from .fingerprints import fingerprint
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


def load_intraday_research_campaign_plan(path: Path) -> IntradayResearchCampaignPlan:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return parse_intraday_research_campaign_plan(raw)


def parse_intraday_research_campaign_plan(raw: object) -> IntradayResearchCampaignPlan:
    """Validate the frozen M5B campaign-v1 preregistration without loading market data."""

    if not isinstance(raw, dict) or set(raw) != _INTRADAY_ROOT_FIELDS:
        raise ValueError("intraday research campaign plan fields differ")
    if raw["schema_version"] != "intraday-research-campaign-plan-v1":
        raise ValueError("intraday research campaign plan schema differs")
    campaign_id = _text(raw["campaign_id"], "intraday campaign ID")
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
        raise ValueError("intraday campaign v1 does not authorize parameter neighbors")
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
    if plan_fingerprint != REVIEWED_INTRADAY_CAMPAIGN_V1_FINGERPRINT:
        raise ValueError("intraday campaign differs from the reviewed v1 preregistration")
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
