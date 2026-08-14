from __future__ import annotations

import csv
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

import pytest

from systematic_trading_lab.calendar import expected_sessions
from systematic_trading_lab.domain import OHLCVBar
from systematic_trading_lab.parquet import to_parquet
from systematic_trading_lab.rapid_data import (
    import_local_data,
    reject_v3_overlap,
    resolve_research_dataset,
)
from systematic_trading_lab.rapid_store import RapidResearchStore

FIELDS = ("timestamp", "symbol", "open", "high", "low", "close", "volume")


def _records(count: int = 8) -> list[dict[str, Any]]:
    sessions = expected_sessions(
        datetime(2025, 1, 6, tzinfo=UTC), datetime(2025, 2, 28, tzinfo=UTC)
    )[:count]
    return [
        {
            "timestamp": datetime.combine(session, time.min, tzinfo=UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "symbol": "SPY",
            "open": str(100 + index),
            "high": str(102 + index),
            "low": str(99 + index),
            "close": str(101 + index),
            "volume": 1_000_000 + index,
        }
        for index, session in enumerate(sessions)
    ]


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)


def test_local_csv_and_parquet_import_are_separate_user_supplied_datasets(
    tmp_path: Path,
) -> None:
    records = _records()
    csv_path = tmp_path / "bars.csv"
    parquet_path = tmp_path / "bars.parquet"
    _write_csv(csv_path, records)
    parquet_path.write_bytes(to_parquet(OHLCVBar.from_record(record) for record in records))
    store = RapidResearchStore(tmp_path / "state")

    csv_dataset = import_local_data(csv_path, store)
    parquet_dataset = import_local_data(parquet_path, store)

    assert csv_dataset["data_origin"] == "user-supplied"
    assert csv_dataset["adjustment_policy"] == "user-supplied-unknown-v1"
    assert parquet_dataset["data_origin"] == "user-supplied"
    assert csv_dataset["dataset_fingerprint"] == parquet_dataset["dataset_fingerprint"]
    assert csv_dataset["dataset_id"] != parquet_dataset["dataset_id"]
    assert len(store.list_datasets()) == 2


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda rows: [rows[0], *rows], "local data validation failed"),
        (lambda rows: [rows[1], rows[0], *rows[2:]], "local data validation failed"),
        (
            lambda rows: [{**rows[0], "timestamp": "not-a-timestamp"}, *rows[1:]],
            "row 1 is malformed",
        ),
        (
            lambda rows: [{**rows[0], "high": "1"}, *rows[1:]],
            "row 1 is malformed",
        ),
        (lambda rows: [*rows[:3], *rows[4:]], "local data validation failed"),
    ],
)
def test_local_csv_rejects_duplicates_ordering_malformed_rows_and_missing_sessions(
    tmp_path: Path,
    mutate: Any,
    message: str,
) -> None:
    path = tmp_path / "invalid.csv"
    _write_csv(path, mutate(_records()))

    with pytest.raises(ValueError, match=message):
        import_local_data(path, RapidResearchStore(tmp_path / "state"))


def test_local_csv_rejects_non_exchange_sessions(tmp_path: Path) -> None:
    records = _records(1)
    records[0]["timestamp"] = "2025-01-11T00:00:00Z"
    path = tmp_path / "weekend.csv"
    _write_csv(path, records)

    with pytest.raises(ValueError, match="non-XNYS sessions"):
        import_local_data(path, RapidResearchStore(tmp_path / "state"))


def test_v3_overlap_is_rejected_before_dataset_metadata_or_artifact_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RapidResearchStore(tmp_path / "state")

    def fail_if_called(_dataset_id: str) -> dict[str, object] | None:
        raise AssertionError("dataset metadata was read")

    monkeypatch.setattr(store, "get_dataset", fail_if_called)

    with pytest.raises(ValueError, match="protected V3 Validation A"):
        resolve_research_dataset(
            tmp_path,
            store,
            "any-dataset",
            datetime(2026, 9, 30, tzinfo=UTC),
            datetime(2026, 10, 1, tzinfo=UTC),
        )

    with pytest.raises(ValueError, match="protected V3 Validation A"):
        resolve_research_dataset(
            tmp_path,
            store,
            "any-dataset",
            datetime(2026, 10, 1, tzinfo=UTC),
            None,
        )

    with pytest.raises(ValueError, match="protected V3 Validation A"):
        resolve_research_dataset(
            tmp_path,
            store,
            "any-dataset",
            None,
            datetime(2026, 10, 1, tzinfo=UTC),
        )


def test_v3_protected_windows_are_fixed_and_have_no_override() -> None:
    reject_v3_overlap(datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 30, tzinfo=UTC))

    with pytest.raises(ValueError, match="there is no casual override"):
        reject_v3_overlap(datetime(2027, 4, 15, tzinfo=UTC), datetime(2027, 4, 15, tzinfo=UTC))


def test_catalog_read_fails_closed_when_controlled_registry_is_invalid(tmp_path: Path) -> None:
    (tmp_path / "experiments.sqlite3").write_bytes(b"not a SQLite database")
    store = RapidResearchStore(tmp_path)

    with pytest.raises(ValueError, match="cannot be verified; Rapid Research fails closed"):
        resolve_research_dataset(
            tmp_path,
            store,
            "any-catalog-dataset",
            datetime(2025, 1, 6, tzinfo=UTC),
            datetime(2025, 1, 7, tzinfo=UTC),
        )
