from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile


def test_runtime_build_manifest_binds_wheel_and_commit(tmp_path: Path) -> None:
    wheel = tmp_path / "systematic_trading_lab-0.1.0-py3-none-any.whl"
    dist_info = "systematic_trading_lab-0.1.0.dist-info"
    with ZipFile(wheel, "w") as archive:
        archive.writestr(
            f"{dist_info}/METADATA",
            "Metadata-Version: 2.4\nName: systematic-trading-lab\nVersion: 0.1.0\n",
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(
            f"{dist_info}/RECORD",
            "\n".join(
                (
                    f"{dist_info}/METADATA,,",
                    f"{dist_info}/WHEEL,,",
                    f"{dist_info}/RECORD,,",
                )
            ),
        )
    output = tmp_path / "runtime-build-manifest.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/write_runtime_build_manifest.py",
            "--wheel",
            str(wheel),
            "--source-commit",
            "a" * 40,
            "--output",
            str(output),
        ],
        check=True,
    )
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "package_name": "systematic-trading-lab",
        "package_version": "0.1.0",
        "schema_version": "runtime-build-manifest-v1",
        "signer_workflow": ".github/workflows/build-provenance.yml",
        "source_commit": "a" * 40,
        "source_repository": "firedvl/systematic-trading-lab",
        "wheel_filename": wheel.name,
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
    }


def test_runtime_build_manifest_rejects_invalid_wheel(tmp_path: Path) -> None:
    wheel = tmp_path / "invalid.whl"
    wheel.write_bytes(b"invalid")
    output = tmp_path / "runtime-build-manifest.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/write_runtime_build_manifest.py",
            "--wheel",
            str(wheel),
            "--source-commit",
            "a" * 40,
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not output.exists()


def test_runtime_build_manifest_rejects_noncanonical_commit(tmp_path: Path) -> None:
    wheel = tmp_path / "missing.whl"
    output = tmp_path / "runtime-build-manifest.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/write_runtime_build_manifest.py",
            "--wheel",
            str(wheel),
            "--source-commit",
            "A" * 40,
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not output.exists()
