"""Strict, state-free parser for the sealed V3 intraday campaign plan."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .calendar import expected_bar_timestamps, expected_sessions
from .datasets import _manifest_static_identity_matches
from .domain import Timeframe
from .experiments import ExperimentSplit
from .fingerprints import fingerprint
from .intraday_v3 import (
    V3_AUTHORITY_POLICY,
    V3_CAMPAIGN_ID,
    V3_DIAGNOSTIC_POLICY,
    V3_EARLIEST_FILL_SEMANTICS,
    V3_EXECUTION_MODEL,
    V3_EXPERIMENT_SCHEMA,
    V3_PERIODIC_REBALANCE_POLICY,
    V3_QUEUE_POLICY,
    V3_REPORT_SCHEMA,
    V3_SESSION_POLICY,
    IntradayV3ExperimentSpec,
)
from .providers import ALPACA_HISTORICAL_PROVIDER_NAME

V3_CAMPAIGN_PLAN_SCHEMA = "intraday-research-campaign-plan-v2"
REVIEWED_V3_CAMPAIGN_PLAN_FINGERPRINT = (
    "5e81cf8f0db1143f293a0f93900f1e797718443a559c1caaaa2e986851d5241a"
)
REVIEWED_V3_INVENTORY_FINGERPRINT = (
    "0666996faabb50abce0b8959c49980e36a655ea290618bc1463342d2ab5122f9"
)
REVIEWED_V3_PERIOD_SELECTION_FINGERPRINT = (
    "c2718c3871bb95e22d4647e119f6bfb54cd51ec7b1b2cc472cfa1a7dfbcfc5d0"
)
REVIEWED_V3_QUALIFICATION_FINGERPRINT = (
    "11ce501cafc2ad0078d5750e185470dccbbf17a8b01b4ecfd95159c615b45cc3"
)
REVIEWED_V3_SOURCE_FOUNDATION_COMMIT = "d03be5eaa1e5d2d360424a6c0d06c1ce0bc6a723"
_UNIVERSE_ID = "liquid-etfs-intraday-5m-v1"
_UNIVERSE_FINGERPRINT = "6ac4a8269f8e352536f52ddc0a3000e0b39c5551c33c03959c20a640cfddeca9"
_ROLES = ("training", "validation-a", "validation-b", "validation-c")
_VARIANTS = ("base", "increased-cost", "harsher-cost", "plus-1-bar", "plus-2-bars")
_STRATEGIES = (
    ("intraday-event-driven-ma-trend", "intraday-trend", {"window": 12}),
    ("intraday-30-minute-momentum", "intraday-directional-momentum", {"lookback": 6}),
    (
        "intraday-30-minute-opening-range-breakout",
        "intraday-opening-range-breakout",
        {"opening_range_bars": 6},
    ),
)
_VARIANT_CONTRACTS = (
    ("base", "conservative-bps-v1", Decimal("5"), Decimal("1"), 1),
    ("increased-cost", "intraday-increased-cost-bps-v1", Decimal("10"), Decimal("2"), 1),
    ("harsher-cost", "intraday-harsher-cost-bps-v1", Decimal("20"), Decimal("5"), 1),
    ("plus-1-bar", "conservative-bps-v1", Decimal("5"), Decimal("1"), 2),
    ("plus-2-bars", "conservative-bps-v1", Decimal("5"), Decimal("1"), 3),
)
_AUTHORITIES = {
    "research_qualification": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}
_ROOT_FIELDS = {
    "schema_version",
    "campaign_id",
    "name",
    "status",
    "purpose",
    "source_foundation_commit",
    "search_budget",
    "data_contract",
    "execution_contract",
    "prospective_freshness",
    "trusted_time_policy",
    "qualification_binding",
    "periods",
    "strategies",
    "variants",
    "qualification_groups",
    "parameter_neighbors",
    "cash_sanity_test",
    "dataset_binding",
    "source_provenance",
    "change_control",
    "authorities",
    "plan_fingerprint",
}


@dataclass(frozen=True)
class IntradayV3CampaignPeriod:
    role: str
    split: ExperimentSplit
    new_york_session_start: date
    new_york_session_end: date
    start_timestamp: datetime
    end_timestamp: datetime
    session_count: int
    per_symbol_bar_opens: int


@dataclass(frozen=True)
class IntradayV3CandidateReservation:
    experiment_id: str
    candidate_ordinal: int
    strategy_id: str
    strategy_version: str
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
class IntradayV3CampaignPlan:
    campaign_id: str
    name: str
    search_budget: int
    source_foundation_commit: str
    periods: tuple[IntradayV3CampaignPeriod, ...]
    candidates: tuple[IntradayV3CandidateReservation, ...]
    payload: Mapping[str, object]
    plan_fingerprint: str


def load_intraday_v3_campaign_plan(path: Path) -> IntradayV3CampaignPlan:
    return parse_intraday_v3_campaign_plan(json.loads(path.read_text(encoding="utf-8")))


def parse_intraday_v3_campaign_plan(raw: object) -> IntradayV3CampaignPlan:
    """Validate the one preregistered V3 design without creating runtime state."""

    if not isinstance(raw, dict) or set(raw) != _ROOT_FIELDS:
        raise ValueError("V3 campaign plan fields differ")
    if raw["schema_version"] != V3_CAMPAIGN_PLAN_SCHEMA or raw["campaign_id"] != V3_CAMPAIGN_ID:
        raise ValueError("V3 campaign plan identity differs")
    if raw["status"] != "preregistered" or not _text(raw["name"], "V3 campaign name"):
        raise ValueError("V3 campaign plan preregistration differs")
    if "not financial validation" not in _text(raw["purpose"], "V3 campaign purpose").lower():
        raise ValueError("V3 campaign purpose must reject financial validation")
    if raw["source_foundation_commit"] != REVIEWED_V3_SOURCE_FOUNDATION_COMMIT:
        raise ValueError("V3 campaign source foundation differs")
    _contract(raw)
    periods = _periods(raw["periods"])
    _strategies(raw["strategies"])
    variants = _variants(raw["variants"])
    candidates = _reservations(raw["qualification_groups"], periods, variants)
    if raw["search_budget"] != 60 or len(candidates) != 60:
        raise ValueError("V3 campaign search budget differs")
    if raw["parameter_neighbors"] != [] or raw["authorities"] != _AUTHORITIES:
        raise ValueError("V3 campaign authority or neighbor boundary differs")
    if raw["plan_fingerprint"] != REVIEWED_V3_CAMPAIGN_PLAN_FINGERPRINT:
        raise ValueError("V3 campaign claimed fingerprint differs")
    unsigned = {key: value for key, value in raw.items() if key != "plan_fingerprint"}
    if fingerprint(unsigned) != raw["plan_fingerprint"]:
        raise ValueError("V3 campaign fingerprint differs")
    return IntradayV3CampaignPlan(
        V3_CAMPAIGN_ID,
        _text(raw["name"], "V3 campaign name"),
        60,
        REVIEWED_V3_SOURCE_FOUNDATION_COMMIT,
        periods,
        candidates,
        MappingProxyType(dict(raw)),
        raw["plan_fingerprint"],
    )


def build_intraday_v3_experiment(
    plan: IntradayV3CampaignPlan,
    source_commit: str,
    experiment_id: str,
    manifest: Mapping[str, object],
) -> IntradayV3ExperimentSpec:
    if not _commit_hash(source_commit):
        raise ValueError("V3 execution source commit differs")
    reservation = next(
        (item for item in plan.candidates if item.experiment_id == experiment_id), None
    )
    if reservation is None:
        raise ValueError("V3 candidate is not reserved by the campaign plan")
    period = next(item for item in plan.periods if item.role == reservation.period_role)
    dataset_id, dataset_fingerprint = _dataset_identity(period, manifest)
    return IntradayV3ExperimentSpec(
        experiment_id=reservation.experiment_id,
        campaign_id=plan.campaign_id,
        search_budget=plan.search_budget,
        candidate_ordinal=reservation.candidate_ordinal,
        strategy_id=reservation.strategy_id,
        strategy_version=reservation.strategy_version,
        strategy_family=reservation.strategy_family,
        code_commit=source_commit,
        source_foundation_commit=plan.source_foundation_commit,
        campaign_plan_fingerprint=plan.plan_fingerprint,
        qualification_binding_id="intraday-v3-qualification-binding-v1",
        qualification_binding_fingerprint=REVIEWED_V3_QUALIFICATION_FINGERPRINT,
        period_role=reservation.period_role,
        variant_role=reservation.variant_role,
        dataset_id=dataset_id,
        dataset_fingerprint=dataset_fingerprint,
        universe_id=_UNIVERSE_ID,
        universe_fingerprint=_UNIVERSE_FINGERPRINT,
        parameters=reservation.parameters,
        timeframe="5m",
        session_policy_version=V3_SESSION_POLICY,
        bar_timestamp_semantics_version="bar-open-utc-v1",
        session_return_policy_version="XNYS-session-close-equity-v1",
        benchmark_policy_version="cash-and-continuous-underlying-v1",
        cost_model_version=reservation.cost_model_version,
        slippage_bps=reservation.slippage_bps,
        commission_bps=reservation.commission_bps,
        execution_model_version=V3_EXECUTION_MODEL,
        earliest_fill_semantics=V3_EARLIEST_FILL_SEMANTICS,
        decision_queue_policy_version=V3_QUEUE_POLICY,
        execution_delay_bars=reservation.execution_delay_bars,
        periodic_rebalance_policy_version=V3_PERIODIC_REBALANCE_POLICY,
        diagnostic_policy_version=V3_DIAGNOSTIC_POLICY,
        authority_policy_version=V3_AUTHORITY_POLICY,
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


def build_intraday_v3_experiments(
    plan: IntradayV3CampaignPlan,
    source_commit: str,
    manifests: Mapping[str, Mapping[str, object]],
) -> tuple[IntradayV3ExperimentSpec, ...]:
    if set(manifests) != set(_ROLES):
        raise ValueError("V3 campaign dataset roles differ from the sealed periods")
    return tuple(
        build_intraday_v3_experiment(
            plan, source_commit, item.experiment_id, manifests[item.period_role]
        )
        for item in plan.candidates
    )


def parse_intraday_v3_experiment(value: object) -> IntradayV3ExperimentSpec:
    """Restore one stored canonical V3 spec and rerun every domain invariant."""

    if not isinstance(value, Mapping):
        raise ValueError("stored V3 experiment must be an object")
    expected = {field.name for field in fields(IntradayV3ExperimentSpec)}
    if set(value) != expected:
        raise ValueError("stored V3 experiment fields differ")
    payload: dict[str, Any] = dict(value)
    parameters = payload["parameters"]
    if not isinstance(parameters, Mapping):
        raise ValueError("stored V3 parameters differ")
    payload["parameters"] = dict(parameters)
    payload["slippage_bps"] = _decimal(payload["slippage_bps"])
    payload["commission_bps"] = _decimal(payload["commission_bps"])
    payload["split"] = ExperimentSplit(_text(payload["split"], "stored V3 split"))
    payload["start_timestamp"] = _timestamp(payload["start_timestamp"])
    payload["end_timestamp"] = _timestamp(payload["end_timestamp"])
    parent = payload["parent_candidate"]
    if parent is not None and (not isinstance(parent, str) or not parent):
        raise ValueError("stored V3 parent candidate differs")
    return IntradayV3ExperimentSpec(**payload)


def _contract(raw: Mapping[str, object]) -> None:
    if raw["data_contract"] != {
        "provider": "alpaca",
        "feed": "iex",
        "adjustment": "all",
        "timeframe": "5m",
        "symbols": ["SPY", "QQQ"],
        "universe_id": _UNIVERSE_ID,
        "universe_fingerprint": _UNIVERSE_FINGERPRINT,
    }:
        raise ValueError("V3 campaign data contract differs")
    if raw["execution_contract"] != {
        "experiment_schema": V3_EXPERIMENT_SCHEMA,
        "report_schema": V3_REPORT_SCHEMA,
        "execution_model": V3_EXECUTION_MODEL,
        "earliest_fill_semantics": V3_EARLIEST_FILL_SEMANTICS,
        "queue_policy": V3_QUEUE_POLICY,
        "session_policy": V3_SESSION_POLICY,
        "bar_timestamp_semantics": "bar-open-utc-v1",
        "session_return_policy": "XNYS-session-close-equity-v1",
        "benchmark_policy": "cash-and-continuous-underlying-v1",
        "periodic_rebalance_policy": V3_PERIODIC_REBALANCE_POLICY,
        "diagnostic_policy": V3_DIAGNOSTIC_POLICY,
        "authority_policy": V3_AUTHORITY_POLICY,
        "initial_cash": "100000",
        "random_seed": 0,
    }:
        raise ValueError("V3 campaign execution contract differs")
    if raw["prospective_freshness"] != {
        "inventory_fingerprint": REVIEWED_V3_INVENTORY_FINGERPRINT,
        "period_selection_fingerprint": REVIEWED_V3_PERIOD_SELECTION_FINGERPRINT,
        "universal_freshness_proven": False,
        "prospective_market_data_freshness": False,
        "prospective_market_data_freshness_eligible": True,
        "basis": "main-attested-design-before-first-market-bar-v1",
        "selection_date_is_authoritative": False,
        "trusted_cutoff_source": "verified-main-seal-tlog-timestamp",
    }:
        raise ValueError("V3 campaign inventory or period-selection binding differs")
    if raw["trusted_time_policy"] != {
        "seal_schema": "intraday-v3-preregistration-seal-v1",
        "source_ref": "refs/heads/main",
        "signer_workflow": ".github/workflows/build-provenance.yml",
        "first_validation_bar": "2026-10-01T13:30:00Z",
        "effective_selection_cutoff": "verified-sigstore-tlog-timestamp",
        "seal_required_before_runtime_campaign_creation": True,
    }:
        raise ValueError("V3 campaign trusted-time contract differs")
    if raw["qualification_binding"] != {
        "id": "intraday-v3-qualification-binding-v1",
        "fingerprint": REVIEWED_V3_QUALIFICATION_FINGERPRINT,
        "metric_source": "realistic.metrics",
    }:
        raise ValueError("V3 campaign qualification binding differs")
    if raw["cash_sanity_test"] != {
        "strategy_id": "intraday-cash",
        "budgeted": False,
        "authority": "software-sanity-only",
    } or raw["dataset_binding"] != {
        "required_roles": list(_ROLES),
        "all_roles_required_before_candidate_1": True,
        "atomic": True,
        "requires_normalized_and_raw_integrity": True,
        "creates_execution_source_binding": False,
        "creates_authority": False,
    }:
        raise ValueError("V3 campaign dataset binding differs")
    if raw["source_provenance"] != {
        "surface_scope": "whole-application-package-exact-bytes-v1",
        "source_commit_must_equal_attested_seal_commit": True,
        "main_attested_artifacts_required": True,
        "human_review_required": True,
        "immutable_campaign_review_required": True,
        "per_candidate_binding_required": True,
        "reverify_before_compute": True,
        "reverify_before_report_publication": True,
    } or raw["change_control"] != {
        "after_trusted_seal": "new-campaign-version-required",
        "after_first_observed_v3_result": "new-campaign-version-required",
        "future_data_acquisition_may_change_design": False,
    }:
        raise ValueError("V3 campaign provenance or change control differs")


def _periods(value: object) -> tuple[IntradayV3CampaignPeriod, ...]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("V3 campaign periods differ")
    periods: list[IntradayV3CampaignPeriod] = []
    for index, item in enumerate(value):
        if (
            not isinstance(item, dict)
            or set(item)
            != {
                "role",
                "split",
                "new_york_session_start",
                "new_york_session_end",
                "start_timestamp",
                "end_timestamp",
                "session_count",
                "per_symbol_bar_opens",
            }
            or item["role"] != _ROLES[index]
        ):
            raise ValueError("V3 campaign period fields or ordering differ")
        start_date, end_date = (
            _date(item["new_york_session_start"]),
            _date(item["new_york_session_end"]),
        )
        start, end = _timestamp(item["start_timestamp"]), _timestamp(item["end_timestamp"])
        split = ExperimentSplit.TRAINING if index == 0 else ExperimentSplit.VALIDATION
        if item["split"] != split.value or start_date > end_date or start > end:
            raise ValueError("V3 campaign period split or bounds differ")
        timestamps = expected_bar_timestamps(
            datetime.combine(start_date, time.min, UTC),
            datetime.combine(end_date, time.max, UTC),
            Timeframe.FIVE_MINUTES,
        )
        sessions = expected_sessions(
            datetime.combine(start_date, time.min, UTC), datetime.combine(end_date, time.max, UTC)
        )
        if (
            not timestamps
            or (start, end) != (timestamps[0], timestamps[-1])
            or item["session_count"] != len(sessions)
            or item["per_symbol_bar_opens"] != len(timestamps)
        ):
            raise ValueError("V3 campaign period calendar bounds or counts differ")
        if periods and (
            periods[-1].new_york_session_end >= start_date or periods[-1].end_timestamp >= start
        ):
            raise ValueError("V3 campaign periods must be chronological and non-overlapping")
        periods.append(
            IntradayV3CampaignPeriod(
                item["role"],
                split,
                start_date,
                end_date,
                start,
                end,
                len(sessions),
                len(timestamps),
            )
        )
    return tuple(periods)


def _strategies(value: object) -> None:
    expected = [
        {
            "strategy_id": identifier,
            "strategy_version": "1",
            "strategy_family": family,
            "parameters": parameters,
        }
        for identifier, family, parameters in _STRATEGIES
    ]
    if value != expected:
        raise ValueError("V3 campaign fixed strategy contract differs")


def _variants(value: object) -> tuple[tuple[str, str, Decimal, Decimal, int], ...]:
    if not isinstance(value, list) or len(value) != 5:
        raise ValueError("V3 campaign variants differ")
    parsed: list[tuple[str, str, Decimal, Decimal, int]] = []
    for item, expected in zip(value, _VARIANT_CONTRACTS, strict=True):
        if not isinstance(item, dict) or set(item) != {
            "role",
            "cost_model_version",
            "slippage_bps",
            "commission_bps",
            "execution_delay_bars",
        }:
            raise ValueError("V3 campaign variant fields differ")
        actual = (
            item["role"],
            item["cost_model_version"],
            _decimal(item["slippage_bps"]),
            _decimal(item["commission_bps"]),
            item["execution_delay_bars"],
        )
        if actual != expected:
            raise ValueError("V3 campaign fixed variant contract differs")
        parsed.append(expected)
    return tuple(parsed)


def _reservations(
    value: object,
    periods: tuple[IntradayV3CampaignPeriod, ...],
    variants: tuple[tuple[str, str, Decimal, Decimal, int], ...],
) -> tuple[IntradayV3CandidateReservation, ...]:
    if not isinstance(value, list) or len(value) != 12:
        raise ValueError("V3 campaign qualification groups differ")
    reservations: list[IntradayV3CandidateReservation] = []
    for group_index, item in enumerate(value):
        strategy_id, family, parameters = _STRATEGIES[group_index // 4]
        period = periods[group_index % 4]
        if (
            not isinstance(item, dict)
            or set(item) != {"strategy_id", "period_role", "roles"}
            or item["strategy_id"] != strategy_id
            or item["period_role"] != period.role
            or not isinstance(item["roles"], dict)
            or set(item["roles"]) != set(_VARIANTS)
        ):
            raise ValueError("V3 campaign qualification group ordering differs")
        base_id: str | None = None
        for variant_index, (role, cost, slippage, commission, delay) in enumerate(variants):
            expected_id = item["roles"][role]
            if not isinstance(expected_id, str) or not expected_id:
                raise ValueError("V3 campaign reservation ID differs")
            ordinal = group_index * 5 + variant_index + 1
            parent = None if variant_index == 0 else base_id
            reservations.append(
                IntradayV3CandidateReservation(
                    expected_id,
                    ordinal,
                    strategy_id,
                    "1",
                    family,
                    MappingProxyType(dict(parameters)),
                    period.role,
                    period.split,
                    period.start_timestamp,
                    period.end_timestamp,
                    role,
                    parent,
                    cost,
                    slippage,
                    commission,
                    delay,
                )
            )
            if variant_index == 0:
                base_id = expected_id
    expected_ids = tuple(
        f"intraday-research-v3-{slug}-{period.role}-{variant}"
        for strategy_id, _, _ in _STRATEGIES
        for slug in (strategy_id.removeprefix("intraday-"),)
        for period in periods
        for variant in _VARIANTS
    )
    if tuple(item.experiment_id for item in reservations) != expected_ids:
        raise ValueError("V3 campaign reservation IDs differ")
    return tuple(reservations)


def _dataset_identity(
    period: IntradayV3CampaignPeriod, manifest: Mapping[str, object]
) -> tuple[str, str]:
    required = {
        "identity",
        "provider",
        "symbols",
        "timeframe",
        "requested_range",
        "actual_range",
        "retrieval_timestamp",
        "raw_artifact_hashes",
        "normalization_version",
        "schema_version",
        "adjustment_policy",
        "calendar_policy",
        "timestamp_policy",
        "universe_id",
        "universe_fingerprint",
        "validation",
        "feed",
        "parent_dataset_id",
    }
    if (
        set(manifest) != required
        or not isinstance(manifest.get("identity"), Mapping)
        or not isinstance(manifest.get("validation"), Mapping)
    ):
        raise ValueError("V3 dataset manifest fields differ")
    expected_range = {"start": _z(period.start_timestamp), "end": _z(period.end_timestamp)}
    identity = manifest["identity"]
    validation = manifest["validation"]
    assert isinstance(identity, Mapping)
    assert isinstance(validation, Mapping)
    if (
        set(identity) != {"dataset_id", "fingerprint"}
        or set(validation)
        != {
            "errors",
            "missing_intervals",
            "duplicate_intervals",
            "conflicts",
            "quarantined_records",
        }
        or manifest.get("provider") != ALPACA_HISTORICAL_PROVIDER_NAME
        or manifest.get("feed") != "iex"
        or manifest.get("symbols") != [{"value": "SPY"}, {"value": "QQQ"}]
        or manifest.get("timeframe") != "5m"
        or manifest.get("requested_range") != expected_range
        or manifest.get("actual_range") != expected_range
        or manifest.get("normalization_version") != "ohlcv-normalization-v1"
        or manifest.get("schema_version") != "ohlcv-v1"
        or manifest.get("adjustment_policy") != "provider-adjusted-all-v1"
        or manifest.get("calendar_policy") != "XNYS-regular-session-bars-v1"
        or manifest.get("timestamp_policy") != "bar-open-utc-v1"
        or manifest.get("universe_id") != _UNIVERSE_ID
        or manifest.get("universe_fingerprint") != _UNIVERSE_FINGERPRINT
        or manifest.get("parent_dataset_id") is not None
        or validation
        != {
            "errors": [],
            "missing_intervals": [],
            "duplicate_intervals": [],
            "conflicts": [],
            "quarantined_records": 0,
        }
    ):
        raise ValueError(
            "V3 dataset manifest does not match the sealed period or integrity contract"
        )
    retrieval_timestamp = _timestamp(manifest["retrieval_timestamp"])
    raw_hashes = manifest["raw_artifact_hashes"]
    if not isinstance(raw_hashes, list) or len(raw_hashes) != 1 or not _hash(raw_hashes[0]):
        raise ValueError("V3 dataset raw integrity differs")
    dataset_id = _text(identity.get("dataset_id"), "V3 dataset ID")
    dataset_fingerprint = _text(identity.get("fingerprint"), "V3 dataset fingerprint")
    if (
        retrieval_timestamp <= period.end_timestamp
        or not _hash(dataset_id)
        or not _hash(dataset_fingerprint)
        or not _manifest_static_identity_matches(dict(manifest))
    ):
        raise ValueError("V3 dataset identity differs")
    return dataset_id, dataset_fingerprint


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be nonempty text")
    return value


def _date(value: object) -> date:
    try:
        return date.fromisoformat(_text(value, "V3 campaign date"))
    except ValueError as error:
        raise ValueError("V3 campaign date differs") from error


def _timestamp(value: object) -> datetime:
    try:
        result = datetime.fromisoformat(
            _text(value, "V3 campaign timestamp").replace("Z", "+00:00")
        )
    except ValueError as error:
        raise ValueError("V3 campaign timestamp differs") from error
    if result.tzinfo is None or result.utcoffset() != UTC.utcoffset(result):
        raise ValueError("V3 campaign timestamps must be UTC-aware")
    return result


def _decimal(value: object) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("V3 campaign costs must be decimal text")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("V3 campaign costs differ") from error
    if not result.is_finite():
        raise ValueError("V3 campaign costs differ")
    return result


def _hash(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _commit_hash(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def _z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
