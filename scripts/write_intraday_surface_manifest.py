"""Write an exact whole-package source manifest for future V3 review."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

_V3_FOUNDATION_COMMIT = "d03be5eaa1e5d2d360424a6c0d06c1ce0bc6a723"


def _sha256(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _hex(value: str, length: int) -> bool:
    return len(value) == length and all(character in "0123456789abcdef" for character in value)


def build_manifest(package: Path, source_commit: str, lockfile: Path) -> dict[str, object]:
    if (
        not _hex(source_commit, 40)
        or package.is_symlink()
        or not package.is_dir()
        or lockfile.is_symlink()
        or not lockfile.is_file()
    ):
        raise ValueError("intraday surface manifest arguments are invalid")
    paths = sorted(package.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("intraday surface package paths must not be symlinks")
    if any(not path.is_file() and not path.is_dir() for path in paths):
        raise ValueError("intraday surface package paths must be regular files or directories")
    files = [
        path
        for path in paths
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    ]
    if package / "intraday_v3.py" not in files:
        raise ValueError("intraday surface package lacks intraday_v3.py")
    components = [
        {
            "path": f"systematic_trading_lab/{path.relative_to(package).as_posix()}",
            "sha256": _sha256(path.read_bytes()),
        }
        for path in files
    ]
    return {
        "components": components,
        "source_commit": source_commit,
        "source_foundation_commit": _V3_FOUNDATION_COMMIT,
        "lock_sha256": _sha256(lockfile.read_bytes()),
        "schema_version": "intraday-v3-whole-package-source-surface-v1",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--lockfile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    manifest = build_manifest(
        arguments.package,
        arguments.source_commit,
        arguments.lockfile,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
