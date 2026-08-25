"""Strict loader for the frozen Program 002 research contract."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .domain import Symbol
from .fingerprints import fingerprint

PROGRAM_ID = "multi-hour-sector-etf-research-001"
PLAN_RELATIVE_PATH = Path(
    "config/research/cross-sectional-sector-etf-program-002-plan-proposal-v1.json"
)
ACQUISITION_PLAN_RELATIVE_PATH = Path(
    "config/research/cross-sectional-sector-etf-program-002-data-acquisition-plan-proposal-v1.json"
)
UNIVERSE_RELATIVE_PATH = Path("config/research/multi-hour-sector-etfs-v1.json")
AUTHORITY_RELATIVE_PATH = Path(
    "config/research/program-002-implementation-acquisition-authority-v1.json"
)
IMPLEMENTATION_PLAN_RELATIVE_PATH = Path(
    "docs/research-campaigns/multi-hour-sector-etf-research-001-implementation-plan.md"
)
PLANNING_REVIEW_RELATIVE_PATH = Path(
    "config/research/cross-sectional-sector-etf-program-002-plan-independent-review-v1.json"
)
REVIEWED_AUTHORITY_SHA256 = "c1fb084b0ac36f7270b56066e499258f18c38adb393b7b597b3d4e1a593e6ca3"
REVIEWED_AUTHORIZATION_PACKET_SHA256 = (
    "8314190d0525e1ff4bd479bc9c1f455f7b40c9e295bc0ccdc8c5d7fcd4a97785"
)
REVIEWED_PLAN_SHA256 = "2872d4d3301df0a85e1a5a2eba6e3ee533ee5573971121e99840041e7c8d2173"
REVIEWED_PLAN_FINGERPRINT = "701dc67ea2da1e45d235f4247724b2bc8eb62853561c2400c17a668342c6b81e"
REVIEWED_ACQUISITION_PLAN_SHA256 = (
    "26c768f422e63e9f00e6adc88be2d57f5c6447972a9de1fa4873ab2826556aae"
)
REVIEWED_UNIVERSE_SHA256 = "8f07f73fd93f9432501d579e43616e1d9a09d6db77c347a6bed4151f2210c312"
REVIEWED_UNIVERSE_FINGERPRINT = "ef23e533aa7a91262200bd7a77a65f9b6d8b4d473573850c33ef014701177790"
REVIEWED_IMPLEMENTATION_PLAN_SHA256 = (
    "aebfea81a2c8a4110d369dbd23d12e0ff79a661fc8f6187df0f27939abdfede5"
)
REVIEWED_PLANNING_REVIEW_SHA256 = "b5023c90a7d748a7c8ac42609bad6d1c394150bc914c51b8b65c73e3d80c17e6"
REVIEWED_PLANNING_REVIEW_FINGERPRINT = (
    "55e30955789981a4eca129856322207ceb05fa9aebccb1101d892dd92f7a5d33"
)

_AUTHORITY_KEYS = frozenset(
    {
        "market_data_acquisition",
        "strategy_implementation",
        "strategy_execution",
        "research_qualification",
        "controlled_evaluation",
        "protected_holdout",
        "paper_execution",
        "broker_writes",
        "live_execution",
    }
)
_RANKING_SYMBOLS = tuple(
    Symbol(value)
    for value in (
        "IWM",
        "MDY",
        "XLB",
        "XLE",
        "XLF",
        "XLI",
        "XLK",
        "XLP",
        "XLRE",
        "XLU",
        "XLV",
        "XLY",
    )
)
_SPY = Symbol("SPY")
_NUMERIC_POLICY = (
    "Use Decimal price and return arithmetic and exact integer volumes. "
    "No floating-point ranking key is permitted."
)


@dataclass(frozen=True)
class Program002Configuration:
    configuration_id: str
    family_id: str
    strategy_id: str
    lookback_30m_bars: int
    hold_30m_bars: int
    immediate_neighbors: tuple[str, str]


@dataclass(frozen=True)
class Program002Authority:
    path: Path
    sha256: str
    authority_id: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class Program002Plan:
    path: Path
    sha256: str
    plan_fingerprint: str
    universe_path: Path
    universe_sha256: str
    universe_fingerprint: str
    ranking_symbols: tuple[Symbol, ...]
    context_symbol: Symbol
    configurations: Mapping[str, Program002Configuration]
    payload: Mapping[str, Any]
    universe_payload: Mapping[str, Any]
    authority: Program002Authority

    def __post_init__(self) -> None:
        object.__setattr__(self, "configurations", MappingProxyType(dict(self.configurations)))
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "universe_payload", MappingProxyType(dict(self.universe_payload)))


@dataclass(frozen=True)
class Program002AcquisitionPlan:
    path: Path
    sha256: str
    payload: Mapping[str, Any]
    authority: Program002Authority

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


def load_program_002_authority(repository: Path) -> Program002Authority:
    repository = repository.resolve()
    path = repository / AUTHORITY_RELATIVE_PATH
    raw = path.read_bytes()
    _require_sha256(raw, REVIEWED_AUTHORITY_SHA256, "Program 002 authority")
    payload = _load_unique_json(raw, "Program 002 authority")
    _verify_authority(repository, payload)
    return Program002Authority(
        path,
        REVIEWED_AUTHORITY_SHA256,
        "program-002-implementation-acquisition-2026-08-25-v1",
        payload,
    )


def load_program_002_plan(repository: Path) -> Program002Plan:
    repository = repository.resolve()
    authority = load_program_002_authority(repository)
    path = repository / PLAN_RELATIVE_PATH
    universe_path = repository / UNIVERSE_RELATIVE_PATH
    raw = path.read_bytes()
    universe_raw = universe_path.read_bytes()
    _require_sha256(raw, REVIEWED_PLAN_SHA256, "Program 002 plan")
    _require_sha256(universe_raw, REVIEWED_UNIVERSE_SHA256, "Program 002 universe")
    payload = _load_unique_json(raw, "Program 002 plan")
    universe = _load_unique_json(universe_raw, "Program 002 universe")
    _verify_plan_identity(payload)
    _verify_universe(payload, universe)
    configurations = _configurations(payload)
    _verify_contracts(payload, configurations)
    return Program002Plan(
        path,
        REVIEWED_PLAN_SHA256,
        REVIEWED_PLAN_FINGERPRINT,
        universe_path,
        REVIEWED_UNIVERSE_SHA256,
        REVIEWED_UNIVERSE_FINGERPRINT,
        _RANKING_SYMBOLS,
        _SPY,
        configurations,
        payload,
        universe,
        authority,
    )


def load_program_002_acquisition_plan(repository: Path) -> Program002AcquisitionPlan:
    repository = repository.resolve()
    authority = load_program_002_authority(repository)
    path = repository / ACQUISITION_PLAN_RELATIVE_PATH
    raw = path.read_bytes()
    _require_sha256(raw, REVIEWED_ACQUISITION_PLAN_SHA256, "Program 002 acquisition plan")
    payload = _load_unique_json(raw, "Program 002 acquisition plan")
    if (
        payload.get("schema_version")
        != "cross-sectional-sector-etf-program-002-data-acquisition-plan-proposal-v1"
        or payload.get("program_id") != PROGRAM_ID
        or payload.get("status") != "PROPOSED-NOT-AUTHORIZED-FOR-ACQUISITION"
    ):
        raise ValueError("Program 002 acquisition plan identity differs")
    _require_false_authority(payload.get("authority"), "acquisition plan")
    program = _mapping(payload.get("program_plan"), "acquisition program binding")
    universe = _mapping(payload.get("universe"), "acquisition universe binding")
    if program != {
        "path": PLAN_RELATIVE_PATH.as_posix(),
        "status_required": "PROPOSED-NOT-AUTHORIZED",
        "sha256": REVIEWED_PLAN_SHA256,
        "plan_fingerprint": REVIEWED_PLAN_FINGERPRINT,
    }:
        raise ValueError("Program 002 acquisition plan program binding differs")
    if (
        universe.get("path") != UNIVERSE_RELATIVE_PATH.as_posix()
        or universe.get("sha256") != REVIEWED_UNIVERSE_SHA256
        or universe.get("universe_fingerprint") != REVIEWED_UNIVERSE_FINGERPRINT
    ):
        raise ValueError("Program 002 acquisition plan universe binding differs")
    if any(_mapping(payload.get("launch_control"), "acquisition launch control").values()):
        raise ValueError("Program 002 acquisition proposal unexpectedly grants launch authority")
    return Program002AcquisitionPlan(path, REVIEWED_ACQUISITION_PLAN_SHA256, payload, authority)


def _verify_authority(repository: Path, payload: Mapping[str, Any]) -> None:
    if (
        payload.get("schema_version") != "program-002-implementation-acquisition-authority-v1"
        or payload.get("authority_id") != "program-002-implementation-acquisition-2026-08-25-v1"
        or payload.get("program_id") != PROGRAM_ID
        or payload.get("status") != "active-until-complete-or-terminal-blocker"
        or payload.get("issued_date") != "2026-08-25"
        or payload.get("source")
        != {
            "kind": "user-supplied-authorization-packet",
            "sha256": REVIEWED_AUTHORIZATION_PACKET_SHA256,
        }
    ):
        raise ValueError("Program 002 authority identity differs")
    expected_bindings = {
        "program_plan": {
            "path": PLAN_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_PLAN_SHA256,
            "fingerprint": REVIEWED_PLAN_FINGERPRINT,
        },
        "acquisition_plan": {
            "path": ACQUISITION_PLAN_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_ACQUISITION_PLAN_SHA256,
        },
        "universe": {
            "path": UNIVERSE_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_UNIVERSE_SHA256,
            "fingerprint": REVIEWED_UNIVERSE_FINGERPRINT,
        },
        "implementation_plan": {
            "path": IMPLEMENTATION_PLAN_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_IMPLEMENTATION_PLAN_SHA256,
        },
        "planning_review": {
            "path": PLANNING_REVIEW_RELATIVE_PATH.as_posix(),
            "sha256": REVIEWED_PLANNING_REVIEW_SHA256,
            "fingerprint": REVIEWED_PLANNING_REVIEW_FINGERPRINT,
        },
    }
    if payload.get("bindings") != expected_bindings:
        raise ValueError("Program 002 authority bindings differ")
    for binding in expected_bindings.values():
        artifact = repository / str(binding["path"])
        _require_sha256(artifact.read_bytes(), str(binding["sha256"]), artifact.as_posix())
    authority_symbols = (*_RANKING_SYMBOLS[:2], _SPY, *_RANKING_SYMBOLS[2:])
    expected_symbols = [symbol.value for symbol in authority_symbols]
    if payload.get("authorized") != {
        "strategy_implementation": True,
        "synthetic_and_mock_validation": True,
        "exposed_market_data_acquisition": True,
        "exposed_quote_calibration_acquisition": True,
        "prospective_cost_model_derivation": True,
        "authorized_dataset_roles": [
            "exposed-context-only",
            "exposed-block-1",
            "exposed-block-2",
            "exposed-block-3",
        ],
        "quote_sessions": 73,
        "quote_fill_clocks": 9,
        "symbols": expected_symbols,
    }:
        raise ValueError("Program 002 authorized scope differs")
    prohibited = _mapping(payload.get("prohibited"), "Program 002 prohibited scope")
    if set(prohibited) != {
        "strategy_execution_on_acquired_data",
        "strategy_result_generation_or_read",
        "discovery",
        "walk_forward",
        "robustness",
        "controlled_dataset_acquisition_or_access",
        "qualification",
        "protected_holdout",
        "paper_execution",
        "broker_writes",
        "live_execution",
        "strategic_allocation_21_access",
    } or any(value is not True for value in prohibited.values()):
        raise ValueError("Program 002 prohibited scope differs")
    expected_authority = {key: False for key in _AUTHORITY_KEYS}
    expected_authority.update({"market_data_acquisition": True, "strategy_implementation": True})
    if payload.get("authority") != expected_authority:
        raise ValueError("Program 002 authority flags differ")


def _verify_plan_identity(payload: Mapping[str, Any]) -> None:
    if (
        payload.get("schema_version") != "cross-sectional-sector-etf-program-002-plan-proposal-v1"
        or payload.get("program_id") != PROGRAM_ID
        or payload.get("status") != "PROPOSED-NOT-AUTHORIZED"
    ):
        raise ValueError("Program 002 plan identity differs")
    unsigned = dict(payload)
    if unsigned.pop("plan_fingerprint", None) != REVIEWED_PLAN_FINGERPRINT:
        raise ValueError("Program 002 plan fingerprint binding differs")
    if fingerprint(unsigned) != REVIEWED_PLAN_FINGERPRINT:
        raise ValueError("Program 002 plan fingerprint differs")
    _require_false_authority(payload.get("authority"), "plan")
    launch = _mapping(payload.get("launch_control"), "plan launch control")
    if set(launch.values()) != {False}:
        raise ValueError("Program 002 plan unexpectedly grants launch authority")


def _verify_universe(payload: Mapping[str, Any], universe: Mapping[str, Any]) -> None:
    binding = _mapping(payload.get("universe"), "plan universe binding")
    if (
        binding.get("path") != UNIVERSE_RELATIVE_PATH.as_posix()
        or binding.get("sha256") != REVIEWED_UNIVERSE_SHA256
        or binding.get("universe_fingerprint") != REVIEWED_UNIVERSE_FINGERPRINT
        or binding.get("ranking_symbols") != [symbol.value for symbol in _RANKING_SYMBOLS]
        or binding.get("context_and_benchmark_symbol") != _SPY.value
        or binding.get("membership_change_allowed") is not False
    ):
        raise ValueError("Program 002 universe binding differs")
    if (
        universe.get("id") != "multi-hour-sector-etfs-v1"
        or universe.get("timeframe") != "5m"
        or universe.get("traded_symbols") != [symbol.value for symbol in _RANKING_SYMBOLS]
        or universe.get("ranking_symbols") != [symbol.value for symbol in _RANKING_SYMBOLS]
        or universe.get("context_and_benchmark_symbols") != [_SPY.value]
        or fingerprint(universe) != REVIEWED_UNIVERSE_FINGERPRINT
    ):
        raise ValueError("Program 002 universe contract differs")
    _require_false_authority(universe.get("authority"), "universe")


def _configurations(payload: Mapping[str, Any]) -> dict[str, Program002Configuration]:
    grid = _mapping(payload.get("configuration_grid"), "configuration grid")
    strategy_by_family = {
        _text(item, "family_id"): _text(item, "strategy_id")
        for item in _list_of_mappings(payload.get("economic_contracts"), "economic contracts")
    }
    result: dict[str, Program002Configuration] = {}
    for item in _list_of_mappings(grid.get("configurations"), "configurations"):
        configuration_id = _text(item, "configuration_id")
        family_id = _text(item, "family_id")
        neighbors = item.get("immediate_neighbors")
        if (
            configuration_id in result
            or family_id not in strategy_by_family
            or not isinstance(neighbors, list)
            or len(neighbors) != 2
            or not all(isinstance(value, str) and value for value in neighbors)
        ):
            raise ValueError("Program 002 configuration identity differs")
        lookback = item.get("lookback_30m_bars")
        hold = item.get("hold_30m_bars")
        if (
            type(lookback) is not int
            or lookback not in {1, 2}
            or type(hold) is not int
            or hold not in {4, 8}
        ):
            raise ValueError("Program 002 configuration axes differ")
        result[configuration_id] = Program002Configuration(
            configuration_id,
            family_id,
            strategy_by_family[family_id],
            lookback,
            hold,
            (neighbors[0], neighbors[1]),
        )
    if grid.get("configuration_count") != 8 or len(result) != 8:
        raise ValueError("Program 002 configuration count differs")
    return result


def _verify_contracts(
    payload: Mapping[str, Any], configurations: Mapping[str, Program002Configuration]
) -> None:
    expected_families = {
        "sector-relative-continuation-v1": (
            "multi-hour-sector-relative-continuation-v1",
            "residual_return > 0 and same_clock_relative_volume >= 1.2",
            "residual_return descending, then symbol ascending",
        ),
        "sector-relative-reversal-v1": (
            "multi-hour-sector-relative-reversal-v1",
            "residual_return <= -0.001 and same_clock_relative_volume >= 1.5",
            "residual_return ascending, then symbol ascending",
        ),
    }
    families = {
        _text(item, "family_id"): (
            _text(item, "strategy_id"),
            _text(item, "activation"),
            _text(item, "ranking"),
        )
        for item in _list_of_mappings(payload.get("economic_contracts"), "economic contracts")
    }
    if families != expected_families:
        raise ValueError("Program 002 economic contracts differ")
    for configuration in configurations.values():
        for neighbor_id in configuration.immediate_neighbors:
            neighbor = configurations.get(neighbor_id)
            if neighbor is None or neighbor.family_id != configuration.family_id:
                raise ValueError("Program 002 neighbor graph differs")
            changed = sum(
                left != right
                for left, right in (
                    (configuration.lookback_30m_bars, neighbor.lookback_30m_bars),
                    (configuration.hold_30m_bars, neighbor.hold_30m_bars),
                )
            )
            if changed != 1 or configuration.configuration_id not in neighbor.immediate_neighbors:
                raise ValueError("Program 002 neighbor graph differs")
    budget = _mapping(payload.get("campaigns_and_budget"), "campaign budget")
    if (
        _mapping(budget.get("campaign_1"), "campaign 1").get("maximum_specs") != 114
        or _mapping(budget.get("campaign_2"), "campaign 2").get("maximum_specs") != 114
        or budget.get("controlled_specs") != 4
        or budget.get("maximum_run_specifications") != 232
        or budget.get("maximum_attempts_per_specification") != 3
        or budget.get("maximum_infrastructure_attempts") != 696
    ):
        raise ValueError("Program 002 budget differs")
    feature = _mapping(payload.get("feature_contract"), "feature contract")
    decision = _mapping(feature.get("decision"), "decision contract")
    execution = _mapping(payload.get("execution_contract"), "execution contract")
    portfolio = _mapping(payload.get("portfolio_contract"), "portfolio contract")
    if (
        decision.get("clock") != "11:30:00 America/New_York"
        or decision.get("latest_source_bar_open") != "11:25:00 America/New_York"
        or feature.get("numeric_policy") != _NUMERIC_POLICY
        or portfolio.get("construction") != "long-flat"
        or portfolio.get("maximum_positions") != 3
        or portfolio.get("shorting") is not False
        or portfolio.get("leverage") is not False
        or portfolio.get("reentry") is not False
        or portfolio.get("resize") is not False
        or execution.get("entry_fill_clocks")
        != {"delay_1": "11:35", "delay_2": "11:40", "delay_3": "11:45"}
    ):
        raise ValueError("Program 002 causal portfolio contract differs")


def _require_false_authority(value: object, label: str) -> None:
    authority = _mapping(value, f"{label} authority")
    if set(authority) != _AUTHORITY_KEYS or any(item is not False for item in authority.values()):
        raise ValueError(f"Program 002 {label} authority differs")


def _load_unique_json(raw: bytes, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is invalid JSON") from error
    return _mapping(value, label)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _require_sha256(raw: bytes, expected: str, label: str) -> None:
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f"{label} SHA-256 differs")


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object")
    return value


def _list_of_mappings(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must be a list of objects")
    return value


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} must be text")
    return item
