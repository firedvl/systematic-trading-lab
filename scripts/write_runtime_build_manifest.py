"""Write deterministic identity metadata for one built wheel."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from email.parser import BytesParser
from pathlib import Path
from zipfile import BadZipFile, ZipFile

SCHEMA_VERSION = "runtime-build-manifest-v1"
SOURCE_REPOSITORY = "firedvl/systematic-trading-lab"
SIGNER_WORKFLOW = ".github/workflows/build-provenance.yml"


def build_manifest(wheel: Path, source_commit: str) -> dict[str, str]:
    if len(source_commit) != 40 or any(value not in "0123456789abcdef" for value in source_commit):
        raise ValueError("source commit must be a full lowercase Git SHA-1")
    if not wheel.is_file() or wheel.suffix != ".whl":
        raise ValueError("wheel path must name one existing .whl file")
    try:
        with ZipFile(wheel) as archive:
            names = [name for name in archive.namelist() if not name.endswith("/")]
            if len(names) != len(set(names)):
                raise ValueError("wheel contains duplicate files")
            metadata_files = [name for name in names if name.endswith(".dist-info/METADATA")]
            if len(metadata_files) != 1:
                raise ValueError("wheel must contain one distribution METADATA file")
            metadata_path = metadata_files[0]
            dist_info = metadata_path.removesuffix("METADATA")
            wheel_path = f"{dist_info}WHEEL"
            record_path = f"{dist_info}RECORD"
            if wheel_path not in names or record_path not in names:
                raise ValueError("wheel metadata is incomplete")
            metadata = BytesParser().parsebytes(archive.read(metadata_path))
            wheel_metadata = BytesParser().parsebytes(archive.read(wheel_path))
            record_names = {
                row[0]
                for row in csv.reader(
                    io.StringIO(archive.read(record_path).decode("utf-8", errors="strict"))
                )
                if row
            }
    except BadZipFile as error:
        raise ValueError("wheel is not a valid ZIP archive") from error
    name = metadata.get("Name")
    version = metadata.get("Version")
    if (
        name != "systematic-trading-lab"
        or not version
        or dist_info != f"systematic_trading_lab-{version}.dist-info/"
        or not wheel.name.startswith(f"systematic_trading_lab-{version}-")
        or not wheel_metadata.get("Wheel-Version", "").startswith("1.")
        or not wheel_metadata.get_all("Tag")
        or record_names != set(names)
    ):
        raise ValueError("wheel package identity is invalid")
    return {
        "package_name": name,
        "package_version": version,
        "schema_version": SCHEMA_VERSION,
        "signer_workflow": SIGNER_WORKFLOW,
        "source_commit": source_commit,
        "source_repository": SOURCE_REPOSITORY,
        "wheel_filename": wheel.name,
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    manifest = build_manifest(arguments.wheel, arguments.source_commit)
    arguments.output.write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
