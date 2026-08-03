"""Immutable dataset import, inspection, and integrity checks."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .calendar import expected_sessions
from .catalog import DatasetCatalog
from .domain import DatasetIdentity, DatasetManifest, OHLCVBar, Symbol, Timeframe, TimestampRange
from .fingerprints import canonical_json, canonicalize, fingerprint
from .parquet import from_parquet, to_parquet
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
        validated = validate_records(
            records,
            timeframe,
            expected_sessions(requested.start, requested.end),
            tuple(symbol.value for symbol in symbols),
        )
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
            calendar_policy="XNYS-v1",
            validation=validated.result,
        )
        manifest_data = canonicalize(manifest)
        raw_text = "".join(canonical_json(record) + "\n" for record in records)
        created = self.layout.publish(
            identity.dataset_id,
            {
                "raw.jsonl": raw_text,
                "bars.parquet": to_parquet(ordered),
                "manifest.json": canonical_json(manifest) + "\n",
            },
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
        records = from_parquet((path / "bars.parquet").read_bytes())
        requested = TimestampRange(
            datetime.fromisoformat(manifest["requested_range"]["start"].replace("Z", "+00:00")),
            datetime.fromisoformat(manifest["requested_range"]["end"].replace("Z", "+00:00")),
        )
        checked = validate_records(
            records,
            Timeframe(manifest["timeframe"]),
            expected_sessions(requested.start, requested.end),
            tuple(symbol["value"] for symbol in manifest["symbols"]),
        )
        actual = fingerprint(tuple(bar.to_record() for bar in checked.bars))
        raw_records = [
            json.loads(line)
            for line in (path / "raw.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]
        raw_matches = fingerprint(raw_records) == manifest["raw_artifact_hashes"][0]
        valid = (
            stored_manifest == manifest
            and actual == identity["fingerprint"]
            and raw_matches
            and checked.result.valid
        )
        return {
            "dataset_id": identity["dataset_id"],
            "fingerprint": identity["fingerprint"],
            "artifact_fingerprint": actual,
            "catalog_matches_manifest": stored_manifest == manifest,
            "raw_artifact_matches": raw_matches,
            "validation": canonicalize(checked.result),
            "valid": valid,
        }

    def load_bars(self, dataset_id: str | None = None) -> tuple[OHLCVBar, ...]:
        validation = self.validate(dataset_id)
        if not validation["valid"]:
            raise DatasetValidationError("dataset integrity validation failed")
        path = self.layout.dataset(str(validation["dataset_id"])) / "bars.parquet"
        bars = tuple(OHLCVBar.from_record(record) for record in from_parquet(path.read_bytes()))
        if fingerprint(tuple(bar.to_record() for bar in bars)) != validation["fingerprint"]:
            raise DatasetValidationError("loaded dataset fingerprint changed after validation")
        return bars

    def rebuild_catalog(self) -> int:
        return self.catalog.rebuild(self.layout.datasets)


def fixture_request() -> TimestampRange:
    return TimestampRange(datetime(2025, 1, 6, tzinfo=UTC), datetime(2025, 1, 10, tzinfo=UTC))


def fixture_symbols() -> tuple[Symbol, ...]:
    return tuple(Symbol(value) for value in ("SPY", "QQQ", "IWM", "TLT", "GLD"))
