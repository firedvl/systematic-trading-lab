"""Strict preregistration loader for Intraday Exposed 002."""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .calendar import expected_bar_timestamps, expected_sessions
from .domain import Timeframe
from .fingerprints import fingerprint
from .intraday_execution_cost_model import load_intraday_execution_cost_model

PLAN_ID = "intraday-exposed-002"
PLAN_SCHEMA = "intraday-exposed-002-research-plan-v1"
PLAN_RELATIVE_PATH = Path("config/research/intraday-exposed-002-plan-v1.json")
REVIEWED_PLAN_SHA256 = "8acb778eec43dd53b56c65712b5a076bdc6126de3504d68114aa714e2474b17f"
REVIEWED_PLAN_FINGERPRINT = "a255949e41c9776e82a04782c6183f5af1476a1dc97c36be4910e4d59424fb98"
PLAN_REVIEW_RELATIVE_PATH = Path(
    "config/research/intraday-exposed-002-plan-independent-review-v1.json"
)
REVIEWED_PLAN_REVIEW_SHA256 = "7a87b647aaf420a8613b793f26bc948c5572e6d66907f9aa9c330e9c543fafb0"
REVIEWED_PLAN_REVIEW_FINGERPRINT = (
    "2ecd5227c3ddc51de9725484de21c994a930dc6f83b7c866d886b68185efdcc4"
)
JUNE_DISPOSITION_RELATIVE_PATH = Path(
    "config/research/intraday-exposed-002-june-disposition-v2.json"
)
REVIEWED_JUNE_DISPOSITION_SHA256 = (
    "a3b623a6ab070a8f33cc5d032bf4ab944e9e2d971405c95f4b220e758c5250f0"
)
REVIEWED_JUNE_DISPOSITION_FINGERPRINT = (
    "7c8a2ea44a3f6679d5cc7ca72b0aee509073272723755c8fea99b09b85de477d"
)

_STARTING_MAIN = "71aa4da11875cffbff77693be83d116d11a5cb73"
_PLAN_STATUS = "frozen-before-may-only-data-acquisition-or-strategy-results"
_PRE_MAY_DATA_END = datetime.fromisoformat("2026-04-30T19:55:00+00:00")
_MAY_START = datetime.fromisoformat("2026-05-01T13:30:00+00:00")
_LATEST_PERMITTED_BAR = datetime.fromisoformat("2026-05-29T19:55:00+00:00")
_EXISTING_DATA_RANGES = (
    (
        datetime.fromisoformat("2025-07-01T13:30:00+00:00"),
        datetime.fromisoformat("2025-12-31T20:55:00+00:00"),
    ),
    (
        datetime.fromisoformat("2026-01-02T14:30:00+00:00"),
        datetime.fromisoformat("2026-02-27T20:55:00+00:00"),
    ),
    (
        datetime.fromisoformat("2026-03-02T14:30:00+00:00"),
        _PRE_MAY_DATA_END,
    ),
)
_DATA_BINDING_FIELDS = [
    "dataset_id",
    "fingerprint",
    "raw_fingerprint",
    "raw_sha256",
    "manifest_sha256",
    "bars_sha256",
    "requested_start",
    "requested_end",
    "actual_start",
    "actual_end",
    "session_count",
    "bar_count",
    "acquisition_main",
    "physically_bounded_before_june",
]
_AUTHORITY = {
    "research_qualification": False,
    "controlled_evaluation": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}
_FAMILY_IDS = (
    "gap-down-failed-continuation-fade-v1",
    "gap-up-confirmed-continuation-v1",
    "opening-range-breakout-v1",
    "volatility-compression-breakout-v1",
    "trend-pullback-recovery-v1",
    "prior-session-level-event-v1",
    "morning-afternoon-continuation-v1",
    "cross-asset-confirmed-breakout-v1",
    "volatility-filtered-breakout-v1",
    "minimum-edge-hysteresis-one-trade-v1",
)
_DISCOVERY_METRICS = {
    "normal.total_return",
    "zero_cost_diagnostic.total_return",
    "normal.completed_round_trips",
    "normal.average_round_trips_per_session",
    "normal.max_drawdown",
    "normal.cost_to_gross_profit",
    "normal.average_gross_trade_edge_bps",
    "normal.average_holding_bars",
    "normal.positive_profit_symbol_concentration",
    "normal.accounting_identity_error",
}
_WALK_FORWARD_METRICS = {
    "aggregate.normal.total_return",
    "positive_normal_fold_count",
    "final_exposed_may.normal.total_return",
    "worst_normal_fold_return",
    "worst_normal_fold_drawdown",
    "aggregate.normal.completed_round_trips",
    "aggregate.normal.average_round_trips_per_session",
    "aggregate.normal.cost_to_gross_profit",
    "aggregate.normal.average_gross_trade_edge_bps",
    "aggregate.normal.average_holding_bars",
    "aggregate.normal.positive_profit_symbol_concentration",
    "aggregate.normal.accounting_identity_error",
}
_STRESS_METRICS = {
    f"{scenario}.{metric}"
    for scenario in ("stress_a", "stress_b", "normal-delay-2", "normal-delay-3")
    for metric in ("aggregate_total_return", "positive_fold_count", "normal_profit_retention")
}


@dataclass(frozen=True)
class Exposed002Configuration:
    candidate_id: str
    family_id: str
    family_ordinal: int
    parameters: Mapping[str, object]
    neighbor_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


@dataclass(frozen=True)
class Exposed002Period:
    period_id: str
    context_start: datetime
    evaluation_start: datetime
    evaluation_end: datetime
    session_count: int


@dataclass(frozen=True)
class IntradayExposed002Plan:
    path: Path
    sha256: str
    plan_fingerprint: str
    payload: Mapping[str, Any]
    configurations: tuple[Exposed002Configuration, ...]
    periods: tuple[Exposed002Period, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


def load_intraday_exposed_002_plan(repository: Path) -> IntradayExposed002Plan:
    repository = repository.resolve()
    path = repository / PLAN_RELATIVE_PATH
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    if sha256 != REVIEWED_PLAN_SHA256:
        raise ValueError("Intraday Exposed 002 plan SHA-256 differs")
    try:
        payload = _mapping(json.loads(raw), "Intraday Exposed 002 plan")
    except json.JSONDecodeError as error:
        raise ValueError("Intraday Exposed 002 plan is invalid JSON") from error
    stored_fingerprint = _text(payload, "plan_fingerprint")
    unsigned = dict(payload)
    del unsigned["plan_fingerprint"]
    if (
        fingerprint(unsigned) != stored_fingerprint
        or stored_fingerprint != REVIEWED_PLAN_FINGERPRINT
    ):
        raise ValueError("Intraday Exposed 002 plan fingerprint differs")
    if (
        payload.get("schema_version") != PLAN_SCHEMA
        or payload.get("program_id") != PLAN_ID
        or payload.get("status") != _PLAN_STATUS
        or payload.get("starting_main") != _STARTING_MAIN
        or payload.get("authority") != _AUTHORITY
    ):
        raise ValueError("Intraday Exposed 002 plan identity differs")

    _verify_dependencies(repository, payload)
    _verify_plan_review(repository, sha256, stored_fingerprint)
    periods = _periods(payload)
    configurations = _configurations(payload)
    _verify_data_boundary(payload, periods)
    _verify_screens(payload)
    _verify_controlled_boundary(payload)
    return IntradayExposed002Plan(
        path,
        sha256,
        stored_fingerprint,
        payload,
        configurations,
        periods,
    )


def _verify_dependencies(repository: Path, payload: Mapping[str, Any]) -> None:
    dependencies = _mapping(payload.get("frozen_dependencies"), "frozen dependencies")
    cost = _mapping(dependencies.get("execution_cost_model"), "execution cost model")
    model = load_intraday_execution_cost_model(repository)
    if (
        cost.get("path") != model.path.relative_to(repository).as_posix()
        or cost.get("cost_model_id") != model.payload.get("cost_model_id")
        or cost.get("sha256") != model.sha256
        or cost.get("fingerprint") != model.model_fingerprint
    ):
        raise ValueError("Intraday Exposed 002 cost-model dependency differs")

    review = _mapping(dependencies.get("execution_cost_review"), "execution cost review")
    _verify_artifact(
        repository,
        review,
        "review_fingerprint",
        "8ade5190bb64330af037f88bf0911ed3cdb04578ca7a6d6e27a5fa6d651349b2",
    )
    if review.get("verdict") != "pass":
        raise ValueError("Intraday Exposed 002 cost review did not pass")

    disposition = _mapping(dependencies.get("june_disposition"), "June disposition")
    value = _verify_artifact(
        repository,
        disposition,
        "disposition_fingerprint",
        REVIEWED_JUNE_DISPOSITION_FINGERPRINT,
    )
    if (
        disposition.get("path") != JUNE_DISPOSITION_RELATIVE_PATH.as_posix()
        or disposition.get("sha256") != REVIEWED_JUNE_DISPOSITION_SHA256
        or disposition.get("status") != "ineligible-before-strategy-results"
        or value.get("status") != disposition.get("status")
        or _mapping(value.get("program_effect"), "June program effect").get("june_read_allowed")
        is not False
    ):
        raise ValueError("Intraday Exposed 002 June disposition differs")


def _verify_plan_review(repository: Path, plan_sha256: str, plan_fingerprint: str) -> None:
    path = repository / PLAN_REVIEW_RELATIVE_PATH
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != REVIEWED_PLAN_REVIEW_SHA256:
        raise ValueError("Intraday Exposed 002 plan-review SHA-256 differs")
    value = _mapping(json.loads(raw), "Intraday Exposed 002 plan review")
    stored_fingerprint = _text(value, "review_fingerprint")
    unsigned = dict(value)
    del unsigned["review_fingerprint"]
    reviewed_plan = _mapping(value.get("reviewed_plan"), "reviewed plan")
    if (
        fingerprint(unsigned) != stored_fingerprint
        or stored_fingerprint != REVIEWED_PLAN_REVIEW_FINGERPRINT
        or value.get("schema_version") != "intraday-exposed-002-plan-independent-review-v1"
        or value.get("status") != "passed-before-may-only-data-acquisition-or-strategy-results"
        or value.get("verdict") != "pass"
        or value.get("findings") != []
        or reviewed_plan.get("program_id") != PLAN_ID
        or reviewed_plan.get("path") != PLAN_RELATIVE_PATH.as_posix()
        or reviewed_plan.get("sha256") != plan_sha256
        or reviewed_plan.get("plan_fingerprint") != plan_fingerprint
    ):
        raise ValueError("Intraday Exposed 002 plan review differs")


def _verify_artifact(
    repository: Path,
    binding: Mapping[str, Any],
    fingerprint_key: str,
    expected_fingerprint: str,
) -> Mapping[str, Any]:
    path = repository / _text(binding, "path")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _text(binding, "sha256"):
        raise ValueError("Intraday Exposed 002 dependency SHA-256 differs")
    value = _mapping(json.loads(raw), "Intraday Exposed 002 dependency")
    stored_fingerprint = _text(value, fingerprint_key)
    unsigned = dict(value)
    del unsigned[fingerprint_key]
    if (
        stored_fingerprint != expected_fingerprint
        or binding.get("fingerprint") != stored_fingerprint
        or fingerprint(unsigned) != stored_fingerprint
    ):
        raise ValueError("Intraday Exposed 002 dependency fingerprint differs")
    return value


def _periods(payload: Mapping[str, Any]) -> tuple[Exposed002Period, ...]:
    chronology = _mapping(payload.get("chronology"), "chronology")
    values = [_mapping(chronology.get("discovery"), "discovery")]
    walk_forward = chronology.get("walk_forward")
    if not isinstance(walk_forward, list) or len(walk_forward) != 4:
        raise ValueError("Intraday Exposed 002 walk-forward periods differ")
    values.extend(_mapping(value, "walk-forward period") for value in walk_forward)
    periods = tuple(_period(value) for value in values)
    if len({period.period_id for period in periods}) != len(periods) or any(
        left.evaluation_end >= right.evaluation_start for left, right in itertools.pairwise(periods)
    ):
        raise ValueError("Intraday Exposed 002 periods overlap or differ")
    return periods


def _period(value: Mapping[str, Any]) -> Exposed002Period:
    period = Exposed002Period(
        _text(value, "period_id"),
        _timestamp(value.get("context_start"), "context start"),
        _timestamp(value.get("evaluation_start"), "evaluation start"),
        _timestamp(value.get("evaluation_end"), "evaluation end"),
        _positive_int(value.get("session_count"), "session count"),
    )
    if (
        period.context_start > period.evaluation_start
        or period.evaluation_end > _LATEST_PERMITTED_BAR
    ):
        raise ValueError("Intraday Exposed 002 period exceeds its permitted range")
    bars = expected_bar_timestamps(
        period.evaluation_start,
        period.evaluation_end,
        Timeframe.FIVE_MINUTES,
    )
    sessions = expected_sessions(period.evaluation_start, period.evaluation_end)
    if (
        not bars
        or bars[0] != period.evaluation_start
        or bars[-1] != period.evaluation_end
        or len(sessions) != period.session_count
    ):
        raise ValueError("Intraday Exposed 002 period calendar differs")
    return period


def _configurations(payload: Mapping[str, Any]) -> tuple[Exposed002Configuration, ...]:
    contract = _mapping(payload.get("configuration_contract"), "configuration contract")
    families = contract.get("families")
    if not isinstance(families, list) or len(families) != len(_FAMILY_IDS):
        raise ValueError("Intraday Exposed 002 families differ")
    result: list[Exposed002Configuration] = []
    for expected_ordinal, (expected_id, raw_family) in enumerate(
        zip(_FAMILY_IDS, families, strict=True), 1
    ):
        family = _mapping(raw_family, "strategy family")
        ordinal = _positive_int(family.get("family_ordinal"), "family ordinal")
        family_id = _text(family, "family_id")
        axes = family.get("axes")
        fixed = _mapping(family.get("fixed_parameters"), "fixed parameters")
        if ordinal != expected_ordinal or family_id != expected_id:
            raise ValueError("Intraday Exposed 002 family identity differs")
        if not isinstance(axes, list) or len(axes) != 2:
            raise ValueError("Intraday Exposed 002 family axes differ")
        parsed_axes = tuple(_axis(value) for value in axes)
        if len({name for name, _values in parsed_axes}) != 2 or set(fixed) & {
            name for name, _values in parsed_axes
        }:
            raise ValueError("Intraday Exposed 002 family parameters collide")
        axis_values = tuple(values for _name, values in parsed_axes)
        if len(axis_values[0]) * len(axis_values[1]) != 6:
            raise ValueError("Intraday Exposed 002 family must contain six parents")
        for first_index, second_index in itertools.product(
            range(len(axis_values[0])), range(len(axis_values[1]))
        ):
            candidate_id = _candidate_id(ordinal, first_index, second_index)
            parameters: dict[str, object] = dict(fixed)
            parameters[parsed_axes[0][0]] = axis_values[0][first_index]
            parameters[parsed_axes[1][0]] = axis_values[1][second_index]
            neighbors: list[str] = []
            for axis_index, current in enumerate((first_index, second_index)):
                for neighbor in (current - 1, current + 1):
                    if 0 <= neighbor < len(axis_values[axis_index]):
                        indices = [first_index, second_index]
                        indices[axis_index] = neighbor
                        neighbors.append(_candidate_id(ordinal, indices[0], indices[1]))
            if len(neighbors) < 2:
                raise ValueError("Intraday Exposed 002 parameter neighborhood is incomplete")
            result.append(
                Exposed002Configuration(
                    candidate_id,
                    family_id,
                    ordinal,
                    parameters,
                    tuple(sorted(neighbors)),
                )
            )
    configurations = tuple(result)
    if (
        len(configurations) != 60
        or len({item.candidate_id for item in configurations}) != 60
        or contract.get("parent_configuration_count") != 60
        or _positive_int(
            contract.get("maximum_parent_configurations"), "maximum parent configurations"
        )
        != 800
        or contract.get("maximum_free_parameters_per_family") != 2
    ):
        raise ValueError("Intraday Exposed 002 parent budget differs")
    return configurations


def _axis(value: object) -> tuple[str, tuple[object, ...]]:
    axis = _mapping(value, "parameter axis")
    name = _text(axis, "name")
    values = axis.get("values")
    if not isinstance(values, list) or len(values) not in {2, 3}:
        raise ValueError("Intraday Exposed 002 parameter axis differs")
    if any(isinstance(item, bool) or not isinstance(item, str | int) for item in values):
        raise ValueError("Intraday Exposed 002 parameter value differs")
    if len({json.dumps(item, sort_keys=True) for item in values}) != len(values):
        raise ValueError("Intraday Exposed 002 parameter values repeat")
    return name, tuple(values)


def _candidate_id(ordinal: int, first_index: int, second_index: int) -> str:
    return f"ie002-f{ordinal:02d}-a{first_index + 1:02d}-b{second_index + 1:02d}"


def _verify_data_boundary(
    payload: Mapping[str, Any], periods: tuple[Exposed002Period, ...]
) -> None:
    data = _mapping(payload.get("data"), "data")
    bindings = data.get("dataset_bindings")
    if not isinstance(bindings, list) or len(bindings) != 3:
        raise ValueError("Intraday Exposed 002 dataset bindings differ")
    allowed_ranges = tuple(
        (
            _timestamp(
                _mapping(binding, "dataset binding").get("allowed_read_start"),
                "allowed start",
            ),
            _timestamp(
                _mapping(binding, "dataset binding").get("allowed_read_end"),
                "allowed end",
            ),
        )
        for binding in bindings
    )
    may = _mapping(data.get("may_only_acquisition"), "May-only acquisition")
    may_start = _timestamp(may.get("requested_start"), "May requested start")
    may_end = _timestamp(may.get("requested_end"), "May requested end")
    expected_may_bars = expected_bar_timestamps(may_start, may_end, Timeframe.FIVE_MINUTES)
    expected_may_sessions = expected_sessions(may_start, may_end)
    required_binding = _mapping(data.get("required_data_binding"), "required data binding")
    if (
        data.get("symbols") != ["QQQ", "SPY"]
        or data.get("timeframe") != "5m"
        or data.get("provider") != "alpaca-historical-v2"
        or data.get("feed") != "iex"
        or allowed_ranges != _EXISTING_DATA_RANGES
        or max(end for _start, end in allowed_ranges) != _PRE_MAY_DATA_END
        or any(period.evaluation_end > _PRE_MAY_DATA_END for period in periods[:-1])
        or periods[-1].evaluation_start != _MAY_START
        or periods[-1].evaluation_end != _LATEST_PERMITTED_BAR
        or may.get("status") != "pending-until-plan-merges"
        or may.get("provider") != "alpaca-historical-v2"
        or may.get("http_method") != "GET"
        or may.get("feed") != "iex"
        or may.get("fallback_allowed") is not False
        or may.get("symbols") != ["QQQ", "SPY"]
        or may.get("timeframe") != "5m"
        or may_start != _MAY_START
        or may_end != _LATEST_PERMITTED_BAR
        or may.get("expected_session_count") != len(expected_may_sessions)
        or may.get("expected_bar_count") != len(expected_may_bars) * 2
        or may.get("adjustment_policy") != "provider-adjusted-all-v1"
        or may.get("universe_id") != "liquid-etfs-intraday-5m-v1"
        or may.get("universe_fingerprint")
        != "6ac4a8269f8e352536f52ddc0a3000e0b39c5551c33c03959c20a640cfddeca9"
        or may.get("existing_artifact_derivation_allowed") is not False
        or required_binding.get("path")
        != "config/research/intraday-exposed-002-data-binding-v1.json"
        or required_binding.get("status")
        != "must-be-frozen-and-independently-reviewed-before-strategy-results"
        or required_binding.get("required_fields") != _DATA_BINDING_FIELDS
        or data.get("all_runtime_datasets_must_be_physically_bounded_before_june") is not True
        or data.get("generic_filtered_read_of_artifact_containing_june") is not False
        or data.get("full_dataset_validation_during_campaign") is not True
        or data.get("acquire_one_minute_data") is not False
        or _timestamp(data.get("latest_permitted_bar"), "latest permitted bar")
        != _LATEST_PERMITTED_BAR
    ):
        raise ValueError("Intraday Exposed 002 data boundary differs")


def _verify_screens(payload: Mapping[str, Any]) -> None:
    if _gate_metrics(payload, "discovery_screen", "gates") != _DISCOVERY_METRICS:
        raise ValueError("Intraday Exposed 002 discovery gates differ")
    if _gate_metrics(payload, "walk_forward_screen", "gates") != _WALK_FORWARD_METRICS:
        raise ValueError("Intraday Exposed 002 walk-forward gates differ")
    serious = _mapping(payload.get("serious_candidate_screen"), "serious screen")
    if _gate_metrics(serious, None, "stress_gates") != _STRESS_METRICS:
        raise ValueError("Intraday Exposed 002 stress gates differ")
    if _gate_metrics(serious, None, "neighbor_gates") != {
        "positive_neighbor_fraction",
        "median_neighbor_normal_profit_retention",
    }:
        raise ValueError("Intraday Exposed 002 neighbor gates differ")
    discovery = _mapping(payload.get("discovery_screen"), "discovery screen")
    walk_forward = _mapping(payload.get("walk_forward_screen"), "walk-forward screen")
    cohort = _mapping(payload.get("final_cohort"), "final cohort")
    if (
        discovery.get("run_all_parents_before_screening") is not True
        or discovery.get("walk_forward_cap") != 30
        or walk_forward.get("serious_candidate_cap") != 15
        or cohort.get("maximum_size") != 5
        or cohort.get("maximum_per_family") != 1
    ):
        raise ValueError("Intraday Exposed 002 selection caps differ")


def _gate_metrics(payload: Mapping[str, Any], section: str | None, key: str) -> set[str]:
    values = _mapping(payload.get(section), section) if section is not None else payload
    gates = values.get(key)
    if not isinstance(gates, list):
        raise ValueError("Intraday Exposed 002 gates must be a list")
    metrics: list[str] = []
    for value in gates:
        gate = _mapping(value, "gate")
        metric = _text(gate, "metric")
        if (
            gate.get("comparison") not in {">", ">=", "<=", "="}
            or isinstance(gate.get("threshold"), bool)
            or not isinstance(gate.get("threshold"), str | int)
        ):
            raise ValueError("Intraday Exposed 002 gate differs")
        metrics.append(metric)
    if len(metrics) != len(set(metrics)):
        raise ValueError("Intraday Exposed 002 gate metrics repeat")
    return set(metrics)


def _verify_controlled_boundary(payload: Mapping[str, Any]) -> None:
    controlled = _mapping(payload.get("controlled_evaluation"), "controlled evaluation")
    if (
        controlled.get("range_status") != "ineligible"
        or controlled.get("june_read") is not False
        or controlled.get("substitute_range") is not False
        or controlled.get("controlled_plan_creation") is not False
    ):
        raise ValueError("Intraday Exposed 002 controlled boundary differs")


def _mapping(value: object, label: str | None) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label or 'value'} must be an object")
    return value


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} must be text")
    return item


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} must be a UTC timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    offset = result.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError(f"{label} must be a UTC timestamp")
    return result
