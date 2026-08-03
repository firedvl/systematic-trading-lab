"""Immutable dataset import, inspection, and integrity checks."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .catalog import DatasetCatalog
from .domain import DatasetIdentity, DatasetManifest, Symbol, Timeframe, TimestampRange
from .fingerprints import canonical_json, canonicalize, fingerprint
from .providers import MarketDataProvider
from .storage import StorageLayout
from .validation import validate_records


class DatasetValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ImportResult:
    dataset_id: str
    fingerprint: str
    created: bool
    bar_count: int


class DatasetService:
    def __init__(self, layout: StorageLayout) -> None:
        self.layout = layout
        self.catalog = DatasetCatalog(layout.catalog)

    def import_from(
        self,
        provider: MarketDataProvider,
        symbols: Sequence[Symbol],
        timeframe: Timeframe,
        requested: TimestampRange,
    ) -> ImportResult:
        records = provider.fetch(symbols, timeframe, requested)
        validated = validate_records(records, timeframe)
        if not validated.result.valid:
            evidence = {
                "provider": provider.name,
                "requested_range": requested,
                "validation": validated.result,
                "records": validated.quarantined,
            }
            evidence_id = fingerprint(evidence)
            self.layout.write_quarantine(evidence_id, canonical_json(evidence) + "\n")
            raise DatasetValidationError(
                f"dataset rejected; quarantine evidence {evidence_id}; "
                f"{len(validated.result.errors)} errors, "
                f"{len(validated.result.missing_intervals)} missing intervals, "
                f"{len(validated.result.duplicate_intervals)} duplicates"
            )

        ordered = tuple(sorted(validated.bars, key=lambda bar: (bar.symbol.value, bar.timestamp)))
        bar_records = tuple(bar.to_record() for bar in ordered)
        data_fingerprint = fingerprint(bar_records)
        identity = DatasetIdentity(dataset_id=data_fingerprint, fingerprint=data_fingerprint)
        actual = TimestampRange(
            min(bar.timestamp for bar in ordered), max(bar.timestamp for bar in ordered)
        )
        manifest = DatasetManifest(
            identity=identity,
            provider=provider.name,
            symbols=tuple(symbols),
            timeframe=timeframe,
            requested_range=requested,
            actual_range=actual,
            retrieval_timestamp=provider.retrieval_timestamp.astimezone(UTC),
            raw_artifact_hashes=(fingerprint(records),),
            normalization_version="ohlcv-normalization-v1",
            schema_version="ohlcv-v1",
            adjustment_policy="provider-adjusted",
            calendar_policy="weekday-gap-check-v1",
            validation=validated.result,
        )
        manifest_data = canonicalize(manifest)
        bars_text = "".join(canonical_json(record) + "\n" for record in bar_records)
        created = self.layout.publish(
            identity.dataset_id,
            {"bars.jsonl": bars_text, "manifest.json": canonical_json(manifest) + "\n"},
        )
        manifest_path = self.layout.dataset(identity.dataset_id) / "manifest.json"
        self.catalog.register(manifest_data, manifest_path)
        return ImportResult(identity.dataset_id, data_fingerprint, created, len(ordered))

    def describe(self, dataset_id: str | None = None) -> dict[str, Any]:
        manifest = self.catalog.get(dataset_id)
        if manifest is None:
            raise KeyError("dataset not found")
        return manifest

    def validate(self, dataset_id: str | None = None) -> dict[str, object]:
        manifest = self.describe(dataset_id)
        identity = manifest["identity"]
        path = self.layout.dataset(identity["dataset_id"])
        stored_manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        records = [
            json.loads(line)
            for line in (path / "bars.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]
        actual = fingerprint(records)
        valid = stored_manifest == manifest and actual == identity["fingerprint"]
        return {
            "dataset_id": identity["dataset_id"],
            "fingerprint": identity["fingerprint"],
            "artifact_fingerprint": actual,
            "catalog_matches_manifest": stored_manifest == manifest,
            "valid": valid,
        }

    def rebuild_catalog(self) -> int:
        return self.catalog.rebuild(self.layout.datasets)


def fixture_request() -> TimestampRange:
    return TimestampRange(datetime(2025, 1, 6, tzinfo=UTC), datetime(2025, 1, 10, tzinfo=UTC))


def fixture_symbols() -> tuple[Symbol, ...]:
    return tuple(Symbol(value) for value in ("SPY", "QQQ", "IWM", "TLT", "GLD"))
