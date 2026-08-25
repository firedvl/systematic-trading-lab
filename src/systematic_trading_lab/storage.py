"""Local immutable artifact layout and atomic writes."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StorageLayout:
    root: Path

    @property
    def datasets(self) -> Path:
        return self.root / "datasets"

    @property
    def quarantine(self) -> Path:
        return self.root / "quarantine"

    @property
    def catalog(self) -> Path:
        return self.root / "catalog.sqlite3"

    @property
    def experiments(self) -> Path:
        return self.root / "experiments.sqlite3"

    @property
    def execution(self) -> Path:
        return self.root / "execution.sqlite3"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    def dataset(self, dataset_id: str) -> Path:
        return self.datasets / dataset_id

    def prepare(self) -> None:
        self.datasets.mkdir(parents=True, exist_ok=True)
        self.quarantine.mkdir(parents=True, exist_ok=True)
        _fsync_directory(self.root)
        _fsync_directory(self.datasets)
        _fsync_directory(self.quarantine)

    def publish(self, dataset_id: str, files: dict[str, str | bytes]) -> bool:
        self.prepare()
        destination = self.dataset(dataset_id)
        if destination.exists():
            return False
        temporary = Path(tempfile.mkdtemp(prefix=f".{dataset_id[:12]}-", dir=self.datasets))
        try:
            for name, contents in files.items():
                _write_file(temporary / name, contents)
            _fsync_directory(temporary)
            try:
                os.rename(temporary, destination)
            except FileExistsError:
                return False
            _fsync_directory(self.datasets)
            return True
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def write_quarantine(self, evidence_id: str, contents: str) -> Path:
        self.prepare()
        path = self.quarantine / f"{evidence_id}.json"
        if not path.exists():
            _write_file(path, contents)
            _fsync_directory(self.quarantine)
        return path


def _write_file(path: Path, contents: str | bytes) -> None:
    if isinstance(contents, bytes):
        with path.open("xb") as file:
            file.write(contents)
            file.flush()
            os.fsync(file.fileno())
        return
    with path.open("x", encoding="utf-8", newline="\n") as file:
        file.write(contents)
        file.flush()
        os.fsync(file.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
