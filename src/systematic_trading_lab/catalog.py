"""SQLite index over authoritative immutable dataset manifests."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class DatasetCatalog:
    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        self.path = path.resolve()
        self.read_only = read_only
        if read_only:
            if not self.path.is_file():
                raise ValueError("read-only dataset catalog is missing")
            with self._connect() as connection:
                table = connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type = 'table' AND name = 'datasets'"
                ).fetchone()
            if table != ("datasets",):
                raise ValueError("read-only dataset catalog schema is missing")
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    dataset_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    manifest_path TEXT NOT NULL UNIQUE,
                    manifest_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def register(self, manifest: dict[str, Any], path: Path) -> bool:
        if self.read_only:
            raise ValueError("read-only dataset catalog cannot register a dataset")
        identity = manifest["identity"]
        encoded = json.dumps(manifest, separators=(",", ":"), sort_keys=True)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO datasets
                    (dataset_id, fingerprint, manifest_path, manifest_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    identity["dataset_id"],
                    identity["fingerprint"],
                    str(path.resolve()),
                    encoded,
                    manifest["retrieval_timestamp"],
                ),
            )
            return cursor.rowcount == 1

    def get(self, dataset_id: str | None = None) -> dict[str, Any] | None:
        query = "SELECT manifest_json FROM datasets"
        parameters: tuple[str, ...] = ()
        if dataset_id is None:
            query += " ORDER BY created_at DESC, dataset_id DESC LIMIT 1"
        else:
            query += " WHERE dataset_id = ?"
            parameters = (dataset_id,)
        with self._connect() as connection:
            row = connection.execute(query, parameters).fetchone()
        return None if row is None else json.loads(row[0])

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) FROM datasets").fetchone()
        assert row is not None
        return int(row[0])

    def list_manifests(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT manifest_json FROM datasets ORDER BY created_at DESC, dataset_id DESC"
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def rebuild(self, datasets: Path) -> int:
        if self.read_only:
            raise ValueError("read-only dataset catalog cannot rebuild")
        count = 0
        for path in sorted(datasets.glob("*/manifest.json")):
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if self.register(manifest, path):
                count += 1
        return count

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = (
            sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)
            if self.read_only
            else sqlite3.connect(self.path)
        )
        if self.read_only:
            connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()
