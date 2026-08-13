from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest


def _manifest(package: Path, lockfile: Path, output: Path) -> dict[str, object]:
    subprocess.run(
        [
            sys.executable,
            "scripts/write_intraday_surface_manifest.py",
            "--package",
            str(package),
            "--source-commit",
            "a" * 40,
            "--lockfile",
            str(lockfile),
            "--output",
            str(output),
        ],
        check=True,
    )
    value = json.loads(output.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _hashes(manifest: dict[str, object]) -> dict[str, str]:
    components = manifest["components"]
    assert isinstance(components, list)
    return {
        str(item["path"]): str(item["sha256"]) for item in cast(list[dict[str, object]], components)
    }


def test_whole_package_surface_includes_intraday_v3_and_changes_for_added_missing_or_changed_files(
    tmp_path: Path,
) -> None:
    package = tmp_path / "systematic_trading_lab"
    shutil.copytree("src/systematic_trading_lab", package)
    lockfile = tmp_path / "uv.lock"
    lockfile.write_bytes(Path("uv.lock").read_bytes())

    initial = _manifest(package, lockfile, tmp_path / "initial.json")
    assert _manifest(package, lockfile, tmp_path / "repeat.json") == initial
    initial_hashes = _hashes(initial)
    assert initial["schema_version"] == "intraday-v3-whole-package-source-surface-v1"
    assert initial["source_commit"] == "a" * 40
    assert initial["source_foundation_commit"] == ("d03be5eaa1e5d2d360424a6c0d06c1ce0bc6a723")
    assert "systematic_trading_lab/intraday_v3.py" in initial_hashes
    assert "systematic_trading_lab/intraday_campaign_v1_surface.json" in initial_hashes
    assert "systematic_trading_lab/intraday_campaign_v2_surface.json" in initial_hashes

    intraday_v3 = package / "intraday_v3.py"
    original_v3 = intraday_v3.read_bytes()
    intraday_v3.write_bytes(original_v3 + b"\nSOURCE_SUBSTITUTED = True\n")
    substituted = _manifest(package, lockfile, tmp_path / "substituted.json")
    substituted_hashes = _hashes(substituted)
    assert (
        substituted_hashes["systematic_trading_lab/intraday_v3.py"]
        != initial_hashes["systematic_trading_lab/intraday_v3.py"]
    )

    (package / "intraday_v3.py").unlink()
    with pytest.raises(subprocess.CalledProcessError):
        _manifest(package, lockfile, tmp_path / "missing.json")

    intraday_v3.write_bytes(original_v3)
    added = package / "result_affecting.py"
    added.write_bytes(b"VALUE = 1\n")
    extra = _manifest(package, lockfile, tmp_path / "extra.json")
    extra_hashes = _hashes(extra)
    assert (
        extra_hashes["systematic_trading_lab/result_affecting.py"]
        == hashlib.sha256(added.read_bytes()).hexdigest()
    )


def test_whole_package_surface_rejects_root_and_nested_directory_symlinks(tmp_path: Path) -> None:
    package = tmp_path / "systematic_trading_lab"
    shutil.copytree("src/systematic_trading_lab", package)
    lockfile = tmp_path / "uv.lock"
    lockfile.write_bytes(Path("uv.lock").read_bytes())
    package_alias = tmp_path / "package-alias"
    os.symlink(package, package_alias)

    with pytest.raises(subprocess.CalledProcessError):
        _manifest(package_alias, lockfile, tmp_path / "root-symlink.json")

    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    os.symlink(nested, package / "nested-alias")
    with pytest.raises(subprocess.CalledProcessError):
        _manifest(package, lockfile, tmp_path / "nested-symlink.json")


def test_whole_package_surface_rejects_file_broken_and_lockfile_symlinks(tmp_path: Path) -> None:
    package = tmp_path / "systematic_trading_lab"
    shutil.copytree("src/systematic_trading_lab", package)
    lockfile = tmp_path / "uv.lock"
    lockfile.write_bytes(Path("uv.lock").read_bytes())
    alias = package / "module-alias.py"
    os.symlink(package / "intraday_v3.py", alias)
    with pytest.raises(subprocess.CalledProcessError):
        _manifest(package, lockfile, tmp_path / "file-symlink.json")

    alias.unlink()
    os.symlink(package / "missing.py", alias)
    with pytest.raises(subprocess.CalledProcessError):
        _manifest(package, lockfile, tmp_path / "broken-symlink.json")

    alias.unlink()
    lock_alias = tmp_path / "uv-alias.lock"
    os.symlink(lockfile, lock_alias)
    with pytest.raises(subprocess.CalledProcessError):
        _manifest(package, lock_alias, tmp_path / "lock-symlink.json")
