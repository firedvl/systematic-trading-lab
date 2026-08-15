"""Exact dataset binding for the frozen Rapid-004 campaign."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .datasets import DatasetService
from .rapid_store import RapidResearchStore
from .storage import StorageLayout
from .universe import load_research_universe

RAPID_004_PROGRAM_ID = "rapid-004-expanded-universe"
_FREEZE_PATH = Path("config/research/rapid-004-universe-freeze-v1.json")
_UNIVERSE_PATH = Path("config/research/rapid-004-final-universe-v1.json")
_FREEZE_SHA256 = "e99cd6e7cd8f4dc11cd80bbe9affadc2e4136945250f44b2eec6d4d83de8efba"


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
    return Rapid004Binding(
        freeze_sha256=_FREEZE_SHA256,
        universe_specification_sha256=universe_sha256,
        universe_id=universe.universe_id,
        universe_fingerprint=universe.universe_fingerprint,
        dataset_id=_text(dataset.get("dataset_id"), "dataset ID"),
        dataset_fingerprint=_text(dataset.get("dataset_fingerprint"), "dataset fingerprint"),
        provider=_text(dataset.get("provider"), "provider"),
        feed=_optional_text(dataset.get("feed"), "feed"),
        adjustment_policy=_text(dataset.get("adjustment_policy"), "adjustment policy"),
        start=_text(dataset.get("requested_start"), "requested start"),
        end=_text(dataset.get("requested_end"), "requested end"),
        raw_record_fingerprint=_text(
            dataset.get("raw_record_fingerprint"), "raw record fingerprint"
        ),
        symbols=symbols,
    )


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


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
        raise ValueError(f"Rapid-004 {label} must be a nonempty string list")
    result = tuple(value)
    if len(set(result)) != len(result):
        raise ValueError(f"Rapid-004 {label} must be unique")
    return result
