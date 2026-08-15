"""Exact dataset binding for the frozen Rapid-004 campaign."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .datasets import DatasetService
from .fingerprints import fingerprint
from .rapid_store import RapidResearchStore
from .storage import StorageLayout
from .universe import load_research_universe

RAPID_004_PROGRAM_ID = "rapid-004-expanded-universe"
_FREEZE_PATH = Path("config/research/rapid-004-universe-freeze-v1.json")
_UNIVERSE_PATH = Path("config/research/rapid-004-final-universe-v1.json")
_PREDECLARATION_PATH = Path("config/research/rapid-004-predeclaration-v1.json")
_FREEZE_SHA256 = "e99cd6e7cd8f4dc11cd80bbe9affadc2e4136945250f44b2eec6d4d83de8efba"
_PREDECLARATION_SHA256 = "28f97126d49a9f0f092f2c8159d5b7c48a14a4e5b7ba850c2e58dfd9b6c64996"
_RESEARCH_PLAN_KEYS = (
    "execution",
    "chronology",
    "search",
    "mechanics",
    "families",
    "walk_forward_screen",
    "cohort",
)


@dataclass(frozen=True)
class Rapid004Predeclaration:
    sha256: str
    role_map_sha256: str
    benchmark_suite_sha256: str
    research_plan_sha256: str
    exposed_screen_sha256: str
    groups: tuple[tuple[str, tuple[str, ...]], ...]
    sleeves: tuple[tuple[str, tuple[str, ...]], ...]
    family_configuration_counts: tuple[tuple[str, int, int], ...]
    maximum_parent_records: int

    def group(self, name: str) -> tuple[str, ...]:
        try:
            return dict(self.groups)[name]
        except KeyError as error:
            raise ValueError(f"unknown Rapid-004 role group: {name}") from error


@dataclass(frozen=True)
class Rapid004Binding:
    freeze_sha256: str
    universe_specification_sha256: str
    universe_id: str
    universe_fingerprint: str
    dataset_id: str
    dataset_fingerprint: str
    provider: str
    feed: str | None
    adjustment_policy: str
    start: str
    end: str
    raw_record_fingerprint: str
    symbols: tuple[str, ...]
    predeclaration: Rapid004Predeclaration

    def require_dataset_id(self, dataset_id: str) -> None:
        if dataset_id != self.dataset_id:
            raise ValueError("Rapid-004 requires its exact frozen dataset ID")

    def require_manifest(self, manifest: Mapping[str, Any]) -> None:
        identity = _mapping(manifest.get("identity"), "dataset identity")
        symbols = manifest.get("symbols")
        if not isinstance(symbols, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("value"), str) for item in symbols
        ):
            raise ValueError("Rapid-004 dataset symbols are invalid")
        expected = {
            "dataset ID": self.dataset_id,
            "dataset fingerprint": self.dataset_fingerprint,
            "universe ID": self.universe_id,
            "universe fingerprint": self.universe_fingerprint,
            "provider": self.provider,
            "feed": self.feed,
            "adjustment policy": self.adjustment_policy,
            "timeframe": "1d",
            "requested start": f"{self.start}T00:00:00Z",
            "requested end": f"{self.end}T00:00:00Z",
            "actual start": f"{self.start}T00:00:00Z",
            "actual end": f"{self.end}T00:00:00Z",
            "raw record fingerprint": self.raw_record_fingerprint,
            "symbols": self.symbols,
            "validation": {
                "errors": [],
                "missing_intervals": [],
                "duplicate_intervals": [],
                "conflicts": [],
                "quarantined_records": 0,
            },
        }
        requested = _mapping(manifest.get("requested_range"), "requested range")
        actual = _mapping(manifest.get("actual_range"), "actual range")
        raw_hashes = manifest.get("raw_artifact_hashes")
        observed = {
            "dataset ID": identity.get("dataset_id"),
            "dataset fingerprint": identity.get("fingerprint"),
            "universe ID": manifest.get("universe_id"),
            "universe fingerprint": manifest.get("universe_fingerprint"),
            "provider": manifest.get("provider"),
            "feed": manifest.get("feed"),
            "adjustment policy": manifest.get("adjustment_policy"),
            "timeframe": manifest.get("timeframe"),
            "requested start": requested.get("start"),
            "requested end": requested.get("end"),
            "actual start": actual.get("start"),
            "actual end": actual.get("end"),
            "raw record fingerprint": (
                raw_hashes[0] if isinstance(raw_hashes, list) and len(raw_hashes) == 1 else None
            ),
            "symbols": tuple(item["value"] for item in symbols),
            "validation": manifest.get("validation"),
        }
        for label, value in expected.items():
            if observed[label] != value:
                raise ValueError(f"Rapid-004 dataset {label} differs from its freeze")

    def specification(self) -> dict[str, object]:
        return {
            "id": RAPID_004_PROGRAM_ID,
            "freeze_sha256": self.freeze_sha256,
            "universe_specification_sha256": self.universe_specification_sha256,
            "universe_id": self.universe_id,
            "universe_fingerprint": self.universe_fingerprint,
            "dataset_id": self.dataset_id,
            "dataset_fingerprint": self.dataset_fingerprint,
            "predeclaration_sha256": self.predeclaration.sha256,
            "role_map_sha256": self.predeclaration.role_map_sha256,
            "benchmark_suite_sha256": self.predeclaration.benchmark_suite_sha256,
            "research_plan_sha256": self.predeclaration.research_plan_sha256,
            "exposed_screen_sha256": self.predeclaration.exposed_screen_sha256,
        }


def load_rapid_004_binding(repository: Path | None = None) -> Rapid004Binding:
    root = repository or Path(__file__).resolve().parents[2]
    freeze_path = root / _FREEZE_PATH
    if _sha256(freeze_path) != _FREEZE_SHA256:
        raise ValueError("Rapid-004 universe freeze SHA-256 differs")
    try:
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Rapid-004 universe freeze is unreadable") from error
    if (
        freeze.get("schema_version") != "rapid-004-universe-freeze-v1"
        or freeze.get("program_id") != RAPID_004_PROGRAM_ID
        or freeze.get("status") != "frozen-before-strategy-performance-research"
    ):
        raise ValueError("Rapid-004 universe freeze identity differs")
    universe_record = _mapping(freeze.get("universe_specification"), "universe specification")
    dataset = _mapping(freeze.get("immutable_dataset"), "immutable dataset")
    if universe_record.get("path") != _UNIVERSE_PATH.as_posix():
        raise ValueError("Rapid-004 universe specification path differs")
    universe_path = root / _UNIVERSE_PATH
    universe_sha256 = _text(universe_record.get("sha256"), "universe specification SHA-256")
    if _sha256(universe_path) != universe_sha256:
        raise ValueError("Rapid-004 universe specification SHA-256 differs")
    universe = load_research_universe(universe_path)
    symbols = _strings(universe_record.get("symbols"), "frozen symbols")
    if (
        universe.universe_id != universe_record.get("universe_id")
        or universe.universe_fingerprint != universe_record.get("universe_fingerprint")
        or tuple(membership.symbol.value for membership in universe.memberships) != symbols
    ):
        raise ValueError("Rapid-004 universe specification differs from its freeze")
    dataset_id = _text(dataset.get("dataset_id"), "dataset ID")
    dataset_fingerprint = _text(dataset.get("dataset_fingerprint"), "dataset fingerprint")
    predeclaration = _load_predeclaration(
        root,
        symbols=symbols,
        universe_sha256=universe_sha256,
        universe_id=universe.universe_id,
        universe_fingerprint=universe.universe_fingerprint,
        dataset_id=dataset_id,
        dataset_fingerprint=dataset_fingerprint,
    )
    return Rapid004Binding(
        freeze_sha256=_FREEZE_SHA256,
        universe_specification_sha256=universe_sha256,
        universe_id=universe.universe_id,
        universe_fingerprint=universe.universe_fingerprint,
        dataset_id=dataset_id,
        dataset_fingerprint=dataset_fingerprint,
        provider=_text(dataset.get("provider"), "provider"),
        feed=_optional_text(dataset.get("feed"), "feed"),
        adjustment_policy=_text(dataset.get("adjustment_policy"), "adjustment policy"),
        start=_text(dataset.get("requested_start"), "requested start"),
        end=_text(dataset.get("requested_end"), "requested end"),
        raw_record_fingerprint=_text(
            dataset.get("raw_record_fingerprint"), "raw record fingerprint"
        ),
        symbols=symbols,
        predeclaration=predeclaration,
    )


def load_rapid_004_predeclaration(
    repository: Path | None = None,
) -> Rapid004Predeclaration:
    return load_rapid_004_binding(repository).predeclaration


def load_rapid_004_predeclaration_payload(
    repository: Path | None = None,
) -> dict[str, Any]:
    """Return a fresh copy only after every frozen binding and semantic check passes."""
    root = repository or Path(__file__).resolve().parents[2]
    load_rapid_004_binding(root)
    try:
        payload = json.loads((root / _PREDECLARATION_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Rapid-004 predeclaration is unreadable") from error
    if not isinstance(payload, dict):
        raise ValueError("Rapid-004 predeclaration must be an object")
    return payload


def bind_rapid_004_dataset(
    root: Path, store: RapidResearchStore, dataset_id: str
) -> dict[str, object]:
    binding = load_rapid_004_binding()
    binding.require_dataset_id(dataset_id)
    if store.get_dataset(dataset_id) is not None:
        raise ValueError("Rapid-004 requires its cataloged frozen dataset")
    manifest = DatasetService(StorageLayout(root)).describe(dataset_id)
    binding.require_manifest(manifest)
    return binding.specification()


def _sha256(path: Path) -> str:
    try:
        with path.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest()
    except OSError as error:
        raise ValueError(f"Rapid-004 artifact is unreadable: {path}") from error


def _load_predeclaration(
    root: Path,
    *,
    symbols: tuple[str, ...],
    universe_sha256: str,
    universe_id: str,
    universe_fingerprint: str,
    dataset_id: str,
    dataset_fingerprint: str,
) -> Rapid004Predeclaration:
    path = root / _PREDECLARATION_PATH
    if _sha256(path) != _PREDECLARATION_SHA256:
        raise ValueError("Rapid-004 predeclaration SHA-256 differs")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Rapid-004 predeclaration is unreadable") from error
    if not isinstance(payload, dict):
        raise ValueError("Rapid-004 predeclaration must be an object")
    if (
        payload.get("schema_version") != "rapid-004-predeclaration-v1"
        or payload.get("program_id") != RAPID_004_PROGRAM_ID
        or payload.get("status") != "frozen-before-strategy-performance-research"
    ):
        raise ValueError("Rapid-004 predeclaration identity differs")
    source = _mapping(payload.get("source"), "predeclaration source")
    expected_source = {
        "universe_freeze_path": _FREEZE_PATH.as_posix(),
        "universe_freeze_sha256": _FREEZE_SHA256,
        "universe_specification_path": _UNIVERSE_PATH.as_posix(),
        "universe_specification_sha256": universe_sha256,
        "universe_id": universe_id,
        "universe_fingerprint": universe_fingerprint,
        "dataset_id": dataset_id,
        "dataset_fingerprint": dataset_fingerprint,
        "allowed_start": "2020-07-27",
        "allowed_end": "2026-07-31",
    }
    if any(source.get(name) != value for name, value in expected_source.items()):
        raise ValueError("Rapid-004 predeclaration source binding differs")

    role_map = _mapping(payload.get("role_map"), "role map")
    categories = _partition(role_map.get("categories"), symbols, "categories")
    sleeves = _partition(role_map.get("sleeves"), symbols, "sleeves")
    groups = _groups(role_map.get("groups"), symbols)
    if dict(groups).get("all") != symbols:
        raise ValueError("Rapid-004 all role group differs from the frozen universe")
    if not categories or not sleeves:
        raise ValueError("Rapid-004 role partitions must be nonempty")

    benchmarks = _mapping(payload.get("benchmarks"), "benchmarks")
    _validate_benchmarks(benchmarks)
    families_value = payload.get("families")
    if not isinstance(families_value, list):
        raise ValueError("Rapid-004 families must be a list")
    mechanics = _mapping(payload.get("mechanics"), "strategy mechanics")
    _validate_mechanics(mechanics, families_value, groups, symbols)
    family_counts = _family_counts(families_value)
    search = _mapping(payload.get("search"), "search plan")
    budget = _mapping(search.get("parent_budget"), "parent budget")
    maximum_parent_records = _integer(
        budget.get("maximum_parent_records"), "maximum parent records"
    )
    components = (
        "benchmark_full_range_and_fixed_blocks",
        "all_discovery_and_confirmation_full_range",
        "maximum_fixed_block_parents",
        "maximum_neighbor_fixed_block_parents",
        "maximum_walk_forward_parents",
    )
    if sum(_integer(budget.get(name), name) for name in components) != maximum_parent_records:
        raise ValueError("Rapid-004 parent budget components differ from their total")
    ceiling = _integer(search.get("parent_configuration_ceiling"), "parent ceiling")
    if maximum_parent_records > ceiling or ceiling != 3000:
        raise ValueError("Rapid-004 parent budget exceeds its fixed ceiling")
    if (
        sum(item[1] for item in family_counts) != 356
        or sum(item[2] for item in family_counts) != 186
    ):
        raise ValueError("Rapid-004 family grid totals differ")

    exposed_screen = _mapping(payload.get("exposed_screen"), "exposed screen")
    _validate_screen(exposed_screen)
    _validate_walk_forward_screen(
        _mapping(payload.get("walk_forward_screen"), "walk-forward screen")
    )
    research_plan = {name: payload[name] for name in _RESEARCH_PLAN_KEYS}
    return Rapid004Predeclaration(
        sha256=_PREDECLARATION_SHA256,
        role_map_sha256=fingerprint(role_map),
        benchmark_suite_sha256=fingerprint(benchmarks),
        research_plan_sha256=fingerprint(research_plan),
        exposed_screen_sha256=fingerprint(exposed_screen),
        groups=groups,
        sleeves=sleeves,
        family_configuration_counts=family_counts,
        maximum_parent_records=maximum_parent_records,
    )


def _partition(
    value: object, symbols: tuple[str, ...], label: str
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    mapping = _mapping(value, label)
    rows = tuple((name, _strings(members, f"{label} {name}")) for name, members in mapping.items())
    flattened = tuple(symbol for _name, members in rows for symbol in members)
    if len(flattened) != len(set(flattened)) or set(flattened) != set(symbols):
        raise ValueError(f"Rapid-004 {label} must exactly partition the frozen universe")
    return rows


def _groups(value: object, symbols: tuple[str, ...]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    mapping = _mapping(value, "role groups")
    rows = tuple(
        (name, _strings(members, f"role group {name}")) for name, members in mapping.items()
    )
    if any(not set(members) <= set(symbols) for _name, members in rows):
        raise ValueError("Rapid-004 role group contains an unknown symbol")
    return rows


def _validate_benchmarks(benchmarks: Mapping[str, Any]) -> None:
    definitions = benchmarks.get("definitions")
    if not isinstance(definitions, list) or len(definitions) != 5:
        raise ValueError("Rapid-004 benchmark definitions are invalid")
    rows = tuple(_mapping(item, "benchmark definition") for item in definitions)
    if [item.get("id") for item in rows] != [
        "cash",
        "spy-buy-and-hold",
        "qqq-buy-and-hold",
        "rapid-004-static-multi-asset-60-30-10-v1",
        "strategic-allocation-21-historical-reference",
    ]:
        raise ValueError("Rapid-004 benchmark definitions differ")
    gate = rows[3]
    weights = _mapping(gate.get("weights"), "gate benchmark weights")
    try:
        total = sum((Decimal(str(value)) for value in weights.values()), Decimal("0"))
    except Exception as error:
        raise ValueError("Rapid-004 gate benchmark weights are invalid") from error
    if set(weights) != {"SPY", "EFA", "AGG", "GLD"} or total != Decimal("1"):
        raise ValueError("Rapid-004 gate benchmark weights differ")
    if benchmarks.get("gate_benchmark_id") != gate.get("id") or gate.get("gate") is not True:
        raise ValueError("Rapid-004 gate benchmark identity differs")


def _family_counts(value: list[object]) -> tuple[tuple[str, int, int], ...]:
    expected_ids = tuple(chr(code) for code in range(ord("A"), ord("U") + 1))
    rows: list[tuple[str, int, int]] = []
    for family in value:
        record = _mapping(family, "family")
        family_id = _text(record.get("id"), "family ID")
        if record.get("cohort_diversity_group") != family_id:
            raise ValueError("Rapid-004 cohort diversity group differs")
        discovery = _mapping(record.get("discovery"), f"family {family_id} discovery")
        confirmation = _mapping(record.get("confirmation"), f"family {family_id} confirmation")
        declared_discovery = _integer(
            discovery.get("configuration_count"), f"family {family_id} discovery count"
        )
        declared_confirmation = _integer(
            confirmation.get("configuration_count"), f"family {family_id} confirmation count"
        )
        if (
            _grid_count(discovery) != declared_discovery
            or _grid_count(confirmation) != declared_confirmation
        ):
            raise ValueError(f"Rapid-004 family {family_id} grid count differs")
        rows.append((family_id, declared_discovery, declared_confirmation))
    if tuple(item[0] for item in rows) != expected_ids:
        raise ValueError("Rapid-004 family set or order differs")
    return tuple(rows)


def _validate_mechanics(
    mechanics: Mapping[str, Any],
    families: list[object],
    groups: tuple[tuple[str, tuple[str, ...]], ...],
    symbols: tuple[str, ...],
) -> None:
    contracts = _mapping(mechanics.get("contracts"), "mechanic contracts")
    profiles = _mapping(mechanics.get("strategy_profiles"), "strategy profiles")
    planned: set[str] = {"fixed-weight-configured"}
    for family in families:
        record = _mapping(family, "family")
        for stage_name in ("discovery", "confirmation"):
            stage = _mapping(record.get(stage_name), f"family {stage_name}")
            planned.update(_strings(stage.get("strategy_ids"), "strategy IDs"))
    if set(profiles) != planned:
        raise ValueError("Rapid-004 strategy profiles differ from the frozen family grids")
    group_names = {name for name, _members in groups}
    for strategy_id, profile_value in profiles.items():
        profile = _mapping(profile_value, f"strategy profile {strategy_id}")
        if profile.get("contract") not in contracts:
            raise ValueError("Rapid-004 strategy profile references an unknown contract")
        for field in ("group", "risk_group", "fallback_group", "breadth_group", "core_group"):
            group = profile.get(field)
            if group is not None and group not in group_names:
                raise ValueError("Rapid-004 strategy profile references an unknown role group")
        satellite = profile.get("satellite")
        if satellite is not None and not set(_strings(satellite, "satellite symbols")) <= set(
            symbols
        ):
            raise ValueError("Rapid-004 strategy profile references an unknown symbol")


def _grid_count(stage: Mapping[str, Any]) -> int:
    strategy_ids = _strings(stage.get("strategy_ids"), "strategy IDs")
    parameters = _mapping(stage.get("parameters", {}), "parameter grid")
    parameter_sets = stage.get("parameter_sets", [{}])
    if (
        not isinstance(parameter_sets, list)
        or not parameter_sets
        or any(not isinstance(item, dict) for item in parameter_sets)
    ):
        raise ValueError("Rapid-004 parameter sets are invalid")
    count = len(strategy_ids) * len(parameter_sets)
    for name, values in parameters.items():
        if not isinstance(name, str) or not isinstance(values, list) or not values:
            raise ValueError("Rapid-004 parameter grid is invalid")
        count *= len(values)
    return count


def _validate_screen(screen: Mapping[str, Any]) -> None:
    visible = _mapping(screen.get("visible_base"), "visible-base screen")
    gates = visible.get("gates")
    if not isinstance(gates, list) or len(gates) != 14:
        raise ValueError("Rapid-004 visible-base gates differ")
    metrics = tuple(
        _text(_mapping(gate, "visible-base gate").get("metric"), "gate metric") for gate in gates
    )
    if len(set(metrics)) != len(metrics) or "max_sleeve_profit_share" not in metrics:
        raise ValueError("Rapid-004 visible-base gate metrics differ")
    isolated = screen.get("isolated_sensitivity")
    combined = screen.get("combined_stress")
    if not isinstance(isolated, list) or len(isolated) != 2:
        raise ValueError("Rapid-004 sensitivity scenarios differ")
    if not isinstance(combined, list) or len(combined) != 2:
        raise ValueError("Rapid-004 sensitivity scenarios differ")


def _validate_walk_forward_screen(screen: Mapping[str, Any]) -> None:
    gates = screen.get("gates")
    if not isinstance(gates, list):
        raise ValueError("Rapid-004 walk-forward gates are invalid")
    metrics = tuple(
        _text(_mapping(gate, "walk-forward gate").get("metric"), "gate metric") for gate in gates
    )
    if metrics != (
        "fold_count",
        "completed_fold_count",
        "overall_out_of_sample_return",
        "profitable_fold_rate",
        "worst_fold_return",
    ):
        raise ValueError("Rapid-004 walk-forward gate metrics differ")
    if screen.get("required_fold_count") != 9 or screen.get("report_without_threshold") != [
        "fold_return_dispersion",
        "profitable_fold_count",
        "fold_returns",
    ]:
        raise ValueError("Rapid-004 walk-forward report metrics differ")


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Rapid-004 {label} must be an object")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Rapid-004 {label} must be text")
    return value


def _optional_text(value: object, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Rapid-004 {label} must be a non-negative integer")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
        raise ValueError(f"Rapid-004 {label} must be a nonempty string list")
    result = tuple(value)
    if len(set(result)) != len(result):
        raise ValueError(f"Rapid-004 {label} must be unique")
    return result
