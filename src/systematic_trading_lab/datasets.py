"""Immutable dataset import, inspection, and integrity checks."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .calendar import expected_bar_timestamps, expected_sessions
from .catalog import DatasetCatalog
from .domain import (
    AdjustmentPolicy,
    DatasetIdentity,
    DatasetManifest,
    OHLCVBar,
    Symbol,
    Timeframe,
    TimestampRange,
)
from .fingerprints import canonical_json, canonicalize, fingerprint
from .parquet import from_parquet, from_parquet_range, to_parquet
from .providers import MarketDataProvider, ProviderRecords
from .storage import StorageLayout
from .universe import UniverseDefinition
from .validation import ValidatedBars, validate_records


class DatasetValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ImportResult:
    dataset_id: str
    fingerprint: str
    created: bool
    bar_count: int
    parent_dataset_id: str | None


_NORMALIZATION_VERSION = "ohlcv-normalization-v1"
_SCHEMA_VERSION = "ohlcv-v1"
_SUPPORTED_ADJUSTMENTS = {
    AdjustmentPolicy.PROVIDER_ADJUSTED_ALL,
    AdjustmentPolicy.YAHOO_ADJUSTED_OHLC,
    AdjustmentPolicy.SYNTHETIC_NO_ACTIONS,
}


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
        universe: UniverseDefinition,
    ) -> ImportResult:
        _require_supported_timeframe(timeframe)
        if not provider.name:
            raise DatasetValidationError("provider name is required")
        if (
            provider.retrieval_timestamp.tzinfo is None
            or provider.retrieval_timestamp.utcoffset() is None
        ):
            raise DatasetValidationError("provider retrieval timestamp must be timezone-aware")
        try:
            adjustment_policy = AdjustmentPolicy(provider.adjustment_policy)
        except (AttributeError, ValueError) as error:
            raise DatasetValidationError(
                "provider adjustment policy is missing or unknown"
            ) from error
        if adjustment_policy not in _SUPPORTED_ADJUSTMENTS:
            raise DatasetValidationError(
                "unadjusted data requires reviewed corporate-action processing"
            )
        universe.require_full_coverage(tuple(symbols), timeframe, requested)
        feed = getattr(provider, "feed", None)
        if feed is not None and (not isinstance(feed, str) or not feed):
            raise DatasetValidationError("provider feed must be a nonempty string when present")
        fetched = provider.fetch(symbols, timeframe, requested)
        records = tuple(fetched)
        raw_records = fetched.raw_records if isinstance(fetched, ProviderRecords) else records
        validated = _validate_records(records, timeframe, requested, symbols)
        if not validated.result.valid:
            evidence = {
                "provider": provider.name,
                "requested_range": requested,
                "validation": validated.result,
                "records": validated.quarantined,
            }
            if isinstance(fetched, ProviderRecords):
                evidence["acquisition_raw_records"] = raw_records
                evidence["acquisition_raw_fingerprint"] = fingerprint(raw_records)
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
        raw_fingerprint = fingerprint(raw_records)
        version_key = _version_key(
            provider.name,
            symbols,
            timeframe,
            requested,
            adjustment_policy,
            _NORMALIZATION_VERSION,
            _SCHEMA_VERSION,
            _calendar_policy(timeframe),
            _timestamp_policy(timeframe),
            universe.universe_id,
            universe.universe_fingerprint,
            feed,
            data_fingerprint,
            raw_fingerprint,
        )
        dataset_id = fingerprint(version_key)
        existing = self.catalog.get(dataset_id)
        if existing is not None:
            if not self.validate(dataset_id)["valid"]:
                raise DatasetValidationError("existing dataset integrity validation failed")
            return ImportResult(
                dataset_id,
                data_fingerprint,
                False,
                len(ordered),
                existing.get("parent_dataset_id"),
            )
        parent_dataset_id = self._lineage_parent(
            provider.name, symbols, timeframe, requested, adjustment_policy, universe, feed
        )
        identity = DatasetIdentity(dataset_id=dataset_id, fingerprint=data_fingerprint)
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
            raw_artifact_hashes=(raw_fingerprint,),
            normalization_version=_NORMALIZATION_VERSION,
            schema_version=_SCHEMA_VERSION,
            adjustment_policy=adjustment_policy.value,
            calendar_policy=_calendar_policy(timeframe),
            timestamp_policy=_timestamp_policy(timeframe),
            universe_id=universe.universe_id,
            universe_fingerprint=universe.universe_fingerprint,
            validation=validated.result,
            feed=feed,
            parent_dataset_id=parent_dataset_id,
        )
        manifest_data = canonicalize(manifest)
        if manifest.timestamp_policy is None:
            manifest_data.pop("timestamp_policy")
        if manifest.feed is None:
            manifest_data.pop("feed")
        raw_text = "".join(canonical_json(record) + "\n" for record in raw_records)
        created = self.layout.publish(
            identity.dataset_id,
            {
                "raw.jsonl": raw_text,
                "bars.parquet": to_parquet(ordered),
                "manifest.json": canonical_json(manifest_data) + "\n",
            },
        )
        manifest_path = self.layout.dataset(identity.dataset_id) / "manifest.json"
        if not created:
            stored = json.loads(manifest_path.read_text(encoding="utf-8"))
            if stored.get("identity") != manifest_data["identity"]:
                raise DatasetValidationError("existing dataset identity does not match import")
            self.catalog.register(stored, manifest_path)
            return ImportResult(
                identity.dataset_id,
                data_fingerprint,
                False,
                len(ordered),
                stored.get("parent_dataset_id"),
            )
        self.catalog.register(manifest_data, manifest_path)
        return ImportResult(
            identity.dataset_id, data_fingerprint, created, len(ordered), parent_dataset_id
        )

    def _lineage_parent(
        self,
        provider: str,
        symbols: Sequence[Symbol],
        timeframe: Timeframe,
        requested: TimestampRange,
        adjustment_policy: AdjustmentPolicy,
        universe: UniverseDefinition,
        feed: str | None,
    ) -> str | None:
        expected = {
            "provider": provider,
            "symbols": sorted(symbol.value for symbol in symbols),
            "timeframe": timeframe.value,
            "requested_range": canonicalize(requested),
            "adjustment_policy": adjustment_policy.value,
            "normalization_version": _NORMALIZATION_VERSION,
            "schema_version": _SCHEMA_VERSION,
            "calendar_policy": _calendar_policy(timeframe),
            "universe_id": universe.universe_id,
            "universe_fingerprint": universe.universe_fingerprint,
            "feed": feed,
        }
        if timeframe.is_supported_intraday:
            expected["timestamp_policy"] = _timestamp_policy(timeframe)
        for manifest in self.catalog.list_manifests():
            candidate = {
                "provider": manifest.get("provider"),
                "symbols": sorted(symbol["value"] for symbol in manifest.get("symbols", [])),
                "timeframe": manifest.get("timeframe"),
                "requested_range": manifest.get("requested_range"),
                "adjustment_policy": manifest.get("adjustment_policy"),
                "normalization_version": manifest.get("normalization_version"),
                "schema_version": manifest.get("schema_version"),
                "calendar_policy": manifest.get("calendar_policy"),
                "universe_id": manifest.get("universe_id"),
                "universe_fingerprint": manifest.get("universe_fingerprint"),
                "feed": manifest.get("feed"),
            }
            if timeframe.is_supported_intraday:
                candidate["timestamp_policy"] = manifest.get("timestamp_policy")
            if candidate == expected:
                return str(manifest["identity"]["dataset_id"])
        return None

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
        timeframe = Timeframe(manifest["timeframe"])
        checked = _validate_records(
            records,
            timeframe,
            requested,
            tuple(Symbol(symbol["value"]) for symbol in manifest["symbols"]),
        )
        actual = fingerprint(tuple(bar.to_record() for bar in checked.bars))
        raw_records = [
            json.loads(line)
            for line in (path / "raw.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]
        raw_matches = fingerprint(raw_records) == manifest["raw_artifact_hashes"][0]
        identity_matches = _manifest_identity_matches(manifest, checked.bars)
        valid = (
            stored_manifest == manifest
            and actual == identity["fingerprint"]
            and raw_matches
            and identity_matches
            and checked.result.valid
        )
        return {
            "dataset_id": identity["dataset_id"],
            "fingerprint": identity["fingerprint"],
            "artifact_fingerprint": actual,
            "catalog_matches_manifest": stored_manifest == manifest,
            "raw_artifact_matches": raw_matches,
            "identity_matches_manifest": identity_matches,
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

    def load_bars_range(
        self,
        dataset_id: str,
        requested: TimestampRange,
        *,
        expected_fingerprint: str,
        expected_universe_id: str,
        expected_universe_fingerprint: str,
    ) -> tuple[OHLCVBar, ...]:
        """Load and validate only one bounded range from a sealed dataset."""
        manifest = self.describe(dataset_id)
        identity = manifest.get("identity")
        if not isinstance(identity, dict) or identity.get("dataset_id") != dataset_id:
            raise DatasetValidationError("cataloged dataset identity is invalid")
        if identity.get("fingerprint") != expected_fingerprint:
            raise DatasetValidationError("cataloged dataset fingerprint differs")
        if (
            manifest.get("universe_id") != expected_universe_id
            or manifest.get("universe_fingerprint") != expected_universe_fingerprint
        ):
            raise DatasetValidationError("cataloged dataset universe differs")

        dataset_path = self.layout.dataset(dataset_id)
        stored_manifest = json.loads((dataset_path / "manifest.json").read_text(encoding="utf-8"))
        if stored_manifest != manifest:
            raise DatasetValidationError("catalog differs from the stored dataset manifest")
        if not _manifest_static_identity_matches(manifest):
            raise DatasetValidationError("cataloged dataset manifest identity is invalid")

        actual_range = manifest.get("actual_range")
        if not isinstance(actual_range, dict):
            raise DatasetValidationError("cataloged dataset range is invalid")
        actual = TimestampRange(
            _parse_utc_timestamp(actual_range.get("start")),
            _parse_utc_timestamp(actual_range.get("end")),
        )
        if requested.start < actual.start or requested.end > actual.end:
            raise DatasetValidationError("requested range exceeds the dataset range")

        symbols = manifest.get("symbols")
        if not isinstance(symbols, list) or any(
            not isinstance(symbol, dict) or not isinstance(symbol.get("value"), str)
            for symbol in symbols
        ):
            raise DatasetValidationError("cataloged dataset symbols are invalid")
        try:
            timeframe = Timeframe(manifest["timeframe"])
        except (KeyError, ValueError) as error:
            raise DatasetValidationError("cataloged dataset timeframe is invalid") from error
        records = from_parquet_range(dataset_path / "bars.parquet", requested.start, requested.end)
        checked = _validate_records(
            records,
            timeframe,
            requested,
            tuple(Symbol(str(symbol["value"])) for symbol in symbols),
        )
        if not checked.result.valid:
            raise DatasetValidationError("requested dataset range failed validation")
        if not checked.bars or any(
            bar.timestamp < requested.start or bar.timestamp > requested.end for bar in checked.bars
        ):
            raise DatasetValidationError("range loader returned bars outside the requested range")
        return checked.bars

    def rebuild_catalog(self) -> int:
        return self.catalog.rebuild(self.layout.datasets)


def fixture_request() -> TimestampRange:
    return TimestampRange(datetime(2025, 1, 6, tzinfo=UTC), datetime(2025, 1, 10, tzinfo=UTC))


def intraday_fixture_request(
    timeframe: Timeframe = Timeframe.FIVE_MINUTES,
) -> TimestampRange:
    """Cover one full session, one holiday, and one early-close session."""
    if not timeframe.is_supported_intraday:
        raise ValueError("intraday fixture request supports only 1m and 5m")
    return TimestampRange(
        datetime(2025, 11, 26, 14, 30, tzinfo=UTC),
        datetime(2025, 11, 28, 18, 0, tzinfo=UTC) - timeframe.duration,
    )


def _parse_utc_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise DatasetValidationError("cataloged dataset timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DatasetValidationError("cataloged dataset timestamp is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise DatasetValidationError("cataloged dataset timestamp must be UTC")
    return parsed.astimezone(UTC)


def fixture_symbols() -> tuple[Symbol, ...]:
    return tuple(Symbol(value) for value in ("SPY", "QQQ", "IWM", "TLT", "GLD"))


def intraday_fixture_symbols() -> tuple[Symbol, ...]:
    return Symbol("SPY"), Symbol("QQQ")


def _validate_records(
    records: Sequence[dict[str, Any]],
    timeframe: Timeframe,
    requested: TimestampRange,
    symbols: Sequence[Symbol],
) -> ValidatedBars:
    _require_supported_timeframe(timeframe)
    symbol_values = tuple(symbol.value for symbol in symbols)
    if timeframe is Timeframe.DAILY:
        return validate_records(
            records,
            timeframe,
            expected_sessions(requested.start, requested.end),
            symbol_values,
        )
    return validate_records(
        records,
        timeframe,
        expected_symbols=symbol_values,
        expected_bar_timestamps=expected_bar_timestamps(requested.start, requested.end, timeframe),
    )


def _require_supported_timeframe(timeframe: Timeframe) -> None:
    if timeframe is not Timeframe.DAILY and not timeframe.is_supported_intraday:
        raise DatasetValidationError("datasets support only 1d, 1m, and 5m bars")


def _calendar_policy(timeframe: Timeframe) -> str:
    return "XNYS-v1" if timeframe is Timeframe.DAILY else "XNYS-regular-session-bars-v1"


def _timestamp_policy(timeframe: Timeframe) -> str | None:
    return "bar-open-utc-v1" if timeframe.is_supported_intraday else None


def _version_key(
    provider: str,
    symbols: Sequence[Symbol],
    timeframe: Timeframe,
    requested: TimestampRange,
    adjustment_policy: AdjustmentPolicy,
    normalization_version: str,
    schema_version: str,
    calendar_policy: str,
    timestamp_policy: str | None,
    universe_id: str,
    universe_fingerprint: str,
    feed: str | None,
    data_fingerprint: str,
    raw_fingerprint: str,
) -> dict[str, object]:
    key: dict[str, object] = {
        "provider": provider,
        "symbols": tuple(sorted(symbol.value for symbol in symbols)),
        "timeframe": timeframe,
        "requested_range": requested,
        "adjustment_policy": adjustment_policy,
        "normalization_version": normalization_version,
        "schema_version": schema_version,
        "calendar_policy": calendar_policy,
        "universe_id": universe_id,
        "universe_fingerprint": universe_fingerprint,
        "data_fingerprint": data_fingerprint,
        "raw_fingerprint": raw_fingerprint,
    }
    if feed is not None:
        key["feed"] = feed
    if timeframe.is_supported_intraday:
        key["timestamp_policy"] = timestamp_policy
    return key


def _manifest_identity_matches(
    manifest: dict[str, Any],
    bars: Sequence[OHLCVBar],
) -> bool:
    if not _manifest_static_identity_matches(manifest):
        return False
    try:
        return bool(bars) and manifest["actual_range"] == canonicalize(
            TimestampRange(min(bar.timestamp for bar in bars), max(bar.timestamp for bar in bars))
        )
    except (KeyError, TypeError, ValueError):
        return False


def _manifest_static_identity_matches(manifest: dict[str, Any]) -> bool:
    try:
        timeframe = Timeframe(manifest["timeframe"])
        symbols = tuple(Symbol(value["value"]) for value in manifest["symbols"])
        requested = TimestampRange(
            _parse_utc_timestamp(manifest["requested_range"]["start"]),
            _parse_utc_timestamp(manifest["requested_range"]["end"]),
        )
        policy_matches = (
            manifest["calendar_policy"] == _calendar_policy(timeframe)
            and manifest.get("timestamp_policy") == _timestamp_policy(timeframe)
            and manifest["normalization_version"] == _NORMALIZATION_VERSION
            and manifest["schema_version"] == _SCHEMA_VERSION
        )
        expected_id = fingerprint(
            _version_key(
                str(manifest["provider"]),
                symbols,
                timeframe,
                requested,
                AdjustmentPolicy(manifest["adjustment_policy"]),
                str(manifest["normalization_version"]),
                str(manifest["schema_version"]),
                str(manifest["calendar_policy"]),
                manifest.get("timestamp_policy"),
                str(manifest["universe_id"]),
                str(manifest["universe_fingerprint"]),
                _optional_text(manifest.get("feed")),
                str(manifest["identity"]["fingerprint"]),
                str(manifest["raw_artifact_hashes"][0]),
            )
        )
        return bool(policy_matches and manifest["identity"]["dataset_id"] == expected_id)
    except (KeyError, TypeError, ValueError):
        return False


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("optional manifest text is invalid")
    return value
