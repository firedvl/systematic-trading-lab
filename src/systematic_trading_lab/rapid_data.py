"""Daily data inputs for non-authoritative Rapid Research."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from .calendar import expected_sessions
from .datasets import DatasetService
from .domain import OHLCVBar, Timeframe, TimestampRange
from .fingerprints import fingerprint
from .parquet import from_parquet, to_parquet
from .rapid_store import RapidResearchStore
from .storage import StorageLayout
from .validation import ValidatedBars, validate_records

_OHLCV_FIELDS = {"timestamp", "symbol", "open", "high", "low", "close", "volume"}
_V3_WINDOWS = (
    ("Validation A", date(2026, 10, 1), date(2026, 12, 3)),
    ("Validation B", date(2026, 12, 4), date(2027, 2, 9)),
    ("Validation C", date(2027, 2, 10), date(2027, 4, 15)),
)


@dataclass(frozen=True)
class ResearchDataset:
    dataset_id: str
    dataset_fingerprint: str
    source: str
    timeframe: str
    start_timestamp: datetime
    end_timestamp: datetime
    symbols: tuple[str, ...]
    bars: tuple[OHLCVBar, ...]


def import_local_data(path: Path, store: RapidResearchStore) -> dict[str, object]:
    source = path.resolve()
    _reject_controlled_dataset_path(store.root, source)
    if not source.is_file():
        raise ValueError(f"local data file not found: {path}")
    source_format, records = _local_records(source)
    checked = _validate_daily_records(records)
    if not checked.result.valid:
        reasons = (
            *checked.result.errors,
            *checked.result.missing_intervals,
            *checked.result.duplicate_intervals,
        )
        raise ValueError("local data validation failed: " + "; ".join(reasons[:5]))
    ordered = tuple(sorted(checked.bars, key=lambda bar: (bar.symbol.value, bar.timestamp)))
    start = min(bar.timestamp for bar in ordered)
    end = max(bar.timestamp for bar in ordered)
    reject_v3_overlap(start, end)
    _reject_controlled_holdout_overlap(store.root, None, start, end)
    with source.open("rb") as file:
        source_sha256 = hashlib.file_digest(file, "sha256").hexdigest()
    dataset_fingerprint = fingerprint(tuple(bar.to_record() for bar in ordered))
    identity = {
        "schema_version": "rapid-user-dataset-v1",
        "source_format": source_format,
        "source_sha256": source_sha256,
        "dataset_fingerprint": dataset_fingerprint,
        "timeframe": Timeframe.DAILY.value,
        "start_timestamp": start,
        "end_timestamp": end,
        "symbols": tuple(sorted({bar.symbol.value for bar in ordered})),
        "adjustment_policy": "user-supplied-unknown-v1",
    }
    dataset_id = f"rrd-{fingerprint(identity)[:20]}"
    existing = store.get_dataset(dataset_id)
    if existing is not None:
        return existing
    return store.put_dataset(
        {
            "dataset_id": dataset_id,
            "dataset_fingerprint": dataset_fingerprint,
            "source_format": source_format,
            "source_sha256": source_sha256,
            "source_path": str(source),
            "data_origin": "user-supplied",
            "adjustment_policy": "user-supplied-unknown-v1",
            "timeframe": Timeframe.DAILY.value,
            "start_timestamp": start,
            "end_timestamp": end,
            "symbols": identity["symbols"],
            "bar_count": len(ordered),
            "imported_at": datetime.now(UTC),
        },
        to_parquet(ordered),
    )


def resolve_research_dataset(
    root: Path,
    store: RapidResearchStore,
    dataset_id: str,
    start: datetime | None,
    end: datetime | None,
    *,
    verify_full_cataloged_dataset: bool = False,
) -> ResearchDataset:
    if start is not None:
        reject_v3_overlap(start, end if end is not None else start)
    elif end is not None:
        reject_v3_overlap(end, end)
    rapid = store.get_dataset(dataset_id)
    if rapid is not None:
        if verify_full_cataloged_dataset:
            raise ValueError("full catalog integrity validation requires a cataloged dataset")
        actual_start = parse_utc(str(rapid["start_timestamp"]))
        actual_end = parse_utc(str(rapid["end_timestamp"]))
        selected = _selected_range(start, end, actual_start, actual_end)
        reject_v3_overlap(selected.start, selected.end)
        _reject_controlled_dataset_path(root, Path(str(rapid["source_path"])))
        _reject_controlled_holdout_overlap(root, None, selected.start, selected.end)
        artifact = Path(str(rapid["artifact_path"]))
        _reject_controlled_dataset_path(root, artifact)
        records = from_parquet(artifact.read_bytes())
        complete = tuple(OHLCVBar.from_record(record) for record in records)
        if fingerprint(tuple(bar.to_record() for bar in complete)) != rapid["dataset_fingerprint"]:
            raise ValueError("Rapid Research dataset artifact fingerprint differs")
        bars = tuple(bar for bar in complete if selected.start <= bar.timestamp <= selected.end)
        _require_complete_range(bars, selected)
        return ResearchDataset(
            dataset_id,
            str(rapid["dataset_fingerprint"]),
            "user-supplied",
            str(rapid["timeframe"]),
            selected.start,
            selected.end,
            _strings(rapid["symbols"], "Rapid Research dataset symbols"),
            bars,
        )

    _reject_controlled_holdout_overlap(root, dataset_id, start, end)
    service = DatasetService(StorageLayout(root))
    manifest = service.describe(dataset_id)
    if manifest.get("timeframe") != Timeframe.DAILY.value:
        raise ValueError("Rapid Research currently supports daily datasets only")
    actual = manifest.get("actual_range")
    identity = manifest.get("identity")
    if not isinstance(actual, dict) or not isinstance(identity, dict):
        raise ValueError("cataloged dataset manifest is malformed")
    selected = _selected_range(
        start,
        end,
        parse_utc(str(actual.get("start"))),
        parse_utc(str(actual.get("end"))),
    )
    reject_v3_overlap(selected.start, selected.end)
    bars = service.load_bars_range(
        dataset_id,
        selected,
        expected_fingerprint=str(identity.get("fingerprint")),
        expected_universe_id=str(manifest.get("universe_id")),
        expected_universe_fingerprint=str(manifest.get("universe_fingerprint")),
        verify_full_dataset=verify_full_cataloged_dataset,
    )
    symbols = manifest.get("symbols")
    if not isinstance(symbols, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("value"), str) for item in symbols
    ):
        raise ValueError("cataloged dataset symbols are malformed")
    return ResearchDataset(
        dataset_id,
        str(identity["fingerprint"]),
        str(manifest.get("provider")),
        Timeframe.DAILY.value,
        selected.start,
        selected.end,
        tuple(sorted(str(symbol.get("value")) for symbol in symbols)),
        bars,
    )


def list_research_datasets(root: Path, store: RapidResearchStore) -> list[dict[str, object]]:
    controlled = []
    for manifest in DatasetService(StorageLayout(root)).catalog.list_manifests():
        identity = manifest.get("identity", {})
        controlled.append(
            {
                "dataset_id": identity.get("dataset_id"),
                "dataset_fingerprint": identity.get("fingerprint"),
                "data_origin": "cataloged",
                "provider": manifest.get("provider"),
                "timeframe": manifest.get("timeframe"),
                "start_timestamp": manifest.get("actual_range", {}).get("start"),
                "end_timestamp": manifest.get("actual_range", {}).get("end"),
                "symbols": [item.get("value") for item in manifest.get("symbols", [])],
            }
        )
    local = [
        {
            "dataset_id": item["dataset_id"],
            "dataset_fingerprint": item["dataset_fingerprint"],
            "data_origin": item["data_origin"],
            "provider": item["source_format"],
            "timeframe": item["timeframe"],
            "start_timestamp": item["start_timestamp"],
            "end_timestamp": item["end_timestamp"],
            "symbols": item["symbols"],
            "adjustment_policy": item["adjustment_policy"],
        }
        for item in store.list_datasets()
    ]
    return sorted((*controlled, *local), key=lambda item: str(item["dataset_id"]))


def reject_v3_overlap(start: datetime, end: datetime) -> None:
    if start > end:
        raise ValueError("research range start must not follow end")
    _verify_repository_v3_windows()
    for name, protected_start, protected_end in _V3_WINDOWS:
        if not (end.date() < protected_start or start.date() > protected_end):
            raise ValueError(
                f"Rapid Research range overlaps protected V3 {name} "
                f"({protected_start.isoformat()} through {protected_end.isoformat()}); "
                "there is no casual override"
            )


def parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid timestamp: {value}") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _local_records(path: Path) -> tuple[str, tuple[dict[str, Any], ...]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "csv", _csv_records(path)
    if suffix in {".parquet", ".pq"}:
        try:
            records = from_parquet(path.read_bytes())
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Parquet file does not contain the required OHLCV schema") from error
        _require_fields(records)
        return "parquet", records
    raise ValueError("local data file must use .csv, .parquet, or .pq")


def _csv_records(path: Path) -> tuple[dict[str, Any], ...]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        if (
            reader.fieldnames is None
            or set(reader.fieldnames) != _OHLCV_FIELDS
            or len(reader.fieldnames) != len(_OHLCV_FIELDS)
        ):
            raise ValueError("CSV columns must be timestamp,symbol,open,high,low,close,volume")
        records: list[dict[str, Any]] = []
        for index, row in enumerate(reader, start=2):
            if set(row) != _OHLCV_FIELDS or any(value is None for value in row.values()):
                raise ValueError(f"CSV row {index} has the wrong number of columns")
            timestamp = row["timestamp"]
            if len(timestamp) == 10:
                timestamp += "T00:00:00Z"
            try:
                volume = int(row["volume"])
            except ValueError as error:
                raise ValueError(f"CSV row {index} volume must be an integer") from error
            records.append({**row, "timestamp": timestamp, "volume": volume})
    return tuple(records)


def _require_fields(records: tuple[dict[str, Any], ...]) -> None:
    for index, record in enumerate(records, start=1):
        if set(record) != _OHLCV_FIELDS:
            raise ValueError(f"local data row {index} must contain exactly the OHLCV columns")


def _validate_daily_records(records: tuple[dict[str, Any], ...]) -> ValidatedBars:
    _require_fields(records)
    if not records:
        raise ValueError("local data file contains no rows")
    parsed: list[OHLCVBar] = []
    for index, record in enumerate(records, start=1):
        try:
            parsed.append(OHLCVBar.from_record(record))
        except (ArithmeticError, TypeError, ValueError) as error:
            raise ValueError(f"local data row {index} is malformed: {error}") from error
    if any(bar.timestamp.time() != time.min for bar in parsed):
        raise ValueError("daily local timestamps must be UTC dates or midnight UTC")
    symbols = tuple(sorted({bar.symbol.value for bar in parsed}))
    start = min(bar.timestamp for bar in parsed)
    end = max(bar.timestamp for bar in parsed)
    sessions = expected_sessions(start, end)
    allowed_sessions = set(sessions)
    unexpected = sorted({bar.timestamp.date() for bar in parsed} - allowed_sessions)
    if unexpected:
        raise ValueError(
            "daily local data contains non-XNYS sessions: "
            + ", ".join(session.isoformat() for session in unexpected[:5])
        )
    return validate_records(
        records,
        Timeframe.DAILY,
        sessions,
        symbols,
    )


def _selected_range(
    start: datetime | None,
    end: datetime | None,
    actual_start: datetime,
    actual_end: datetime,
) -> TimestampRange:
    selected = TimestampRange(start or actual_start, end or actual_end)
    if selected.start < actual_start or selected.end > actual_end:
        raise ValueError("research range exceeds the dataset range")
    return selected


def _require_complete_range(bars: tuple[OHLCVBar, ...], requested: TimestampRange) -> None:
    if not bars:
        raise ValueError("research dataset range contains no bars")
    records = tuple(bar.to_record() for bar in bars)
    symbols = tuple(sorted({bar.symbol.value for bar in bars}))
    checked = validate_records(
        records,
        Timeframe.DAILY,
        expected_sessions(requested.start, requested.end),
        symbols,
    )
    if not checked.result.valid:
        raise ValueError("research dataset range is incomplete")


def _verify_repository_v3_windows() -> None:
    path = Path(__file__).resolve().parents[2] / "config/research/intraday-campaign-v3.json"
    if not path.is_file():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        observed = tuple(
            (
                str(period["role"]),
                date.fromisoformat(str(period["new_york_session_start"])),
                date.fromisoformat(str(period["new_york_session_end"])),
            )
            for period in payload["periods"]
            if period["role"] != "training"
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("repository V3 plan is malformed; Rapid Research fails closed") from error
    expected = tuple(
        (name.lower().replace(" ", "-"), start, end) for name, start, end in _V3_WINDOWS
    )
    if observed != expected:
        raise ValueError("repository V3 windows differ from the Rapid Research protection")


def _reject_controlled_holdout_overlap(
    root: Path,
    dataset_id: str | None,
    start: datetime | None,
    end: datetime | None,
) -> None:
    path = StorageLayout(root).experiments
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("controlled holdout registry path is unsafe; Rapid Research fails closed")
    if not path.exists():
        return
    try:
        with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as connection:
            connection.execute("PRAGMA query_only = ON")
            tables = {
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            if not {"experiments", "holdout_run_authorizations"} <= tables:
                raise ValueError("controlled holdout registry tables are missing")
            authorizations = connection.execute(
                """
                SELECT authorization_id, candidate_spec_json
                FROM holdout_run_authorizations
                WHERE consumed_by_experiment_id IS NULL
                """
            ).fetchall()
            holdouts = connection.execute(
                "SELECT experiment_id, spec_json FROM experiments WHERE split = 'holdout'"
            ).fetchall()
    except sqlite3.DatabaseError as error:
        raise ValueError(
            "controlled holdout registry cannot be verified; Rapid Research fails closed"
        ) from error

    try:
        pending_ranges: list[tuple[str, datetime]] = []
        for authorization_id, raw in authorizations:
            candidate = _protected_record(raw, f"holdout authorization {authorization_id}")
            candidate_dataset = _protected_text(candidate["dataset_id"], "holdout dataset ID")
            validation_start = _protected_timestamp(candidate["validation_start"])
            validation_end = _protected_timestamp(candidate["validation_end"])
            if validation_start > validation_end:
                raise ValueError("holdout authorization validation start follows end")
            pending_ranges.append((candidate_dataset, validation_end))
        protected_ranges: list[tuple[str, datetime, datetime]] = []
        for experiment_id, raw in holdouts:
            spec = _protected_record(raw, f"holdout experiment {experiment_id}")
            if spec.get("split") != "holdout":
                raise ValueError("stored holdout split differs")
            protected_start = _protected_timestamp(spec["start_timestamp"])
            protected_end = _protected_timestamp(spec["end_timestamp"])
            if protected_start > protected_end:
                raise ValueError("stored holdout start follows end")
            protected_ranges.append(
                (
                    _protected_text(spec["dataset_id"], "holdout dataset ID"),
                    protected_start,
                    protected_end,
                )
            )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError(
            "controlled holdout registry is malformed; Rapid Research fails closed"
        ) from error

    if any(
        (dataset_id is None or candidate_dataset == dataset_id)
        and (end is None or end > validation_end)
        for candidate_dataset, validation_end in pending_ranges
    ) or any(
        (dataset_id is None or protected_dataset == dataset_id)
        and (end is None or end >= protected_start)
        and (start is None or start <= protected_end)
        for protected_dataset, protected_start, protected_end in protected_ranges
    ):
        raise ValueError("Rapid Research range overlaps a protected controlled holdout")


def _reject_controlled_dataset_path(root: Path, path: Path) -> None:
    resolved = path.resolve()
    catalog_artifact = (
        resolved.parent.parent.name == "datasets"
        and (resolved.parent / "manifest.json").is_file()
        and (resolved.parent / "raw.jsonl").is_file()
    )
    if resolved.is_relative_to(StorageLayout(root).datasets.resolve()) or catalog_artifact:
        raise ValueError("controlled dataset artifacts cannot be imported into Rapid Research")


def _protected_record(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be JSON text")
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise TypeError(f"{label} must be an object")
    return parsed


def _protected_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("protected timestamp must be text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("protected timestamp must be UTC")
    return parsed.astimezone(UTC)


def _protected_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{label} must be nonempty text")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, str | bytes)
        or not all(isinstance(item, str) for item in value)
    ):
        raise ValueError(f"{label} are malformed")
    return tuple(value)
