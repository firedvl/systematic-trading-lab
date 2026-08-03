"""Strict machine-readable plans for sealed training campaigns."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .experiments import ExperimentSpec, ExperimentSplit
from .fingerprints import fingerprint

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
}
_PARAMETER_MINIMUMS = {
    "moving-average-trend": {"window": 2},
    "moving-average-mean-reversion": {"window": 2},
    "risk-managed-momentum-portfolio": {"volatility_window": 2},
    "volatility-balanced-portfolio": {"volatility_window": 2},
    "volatility-targeted-exposure": {"volatility_window": 2},
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


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be non-empty text")
    return value


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
