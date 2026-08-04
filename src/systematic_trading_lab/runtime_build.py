"""Fail-closed verification of attested runtime build artifacts."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .fingerprints import fingerprint

SCHEMA_VERSION = "runtime-build-manifest-v1"
SOURCE_REPOSITORY = "firedvl/systematic-trading-lab"
SIGNER_WORKFLOW = ".github/workflows/build-provenance.yml"
_MANIFEST_KEYS = {
    "package_name",
    "package_version",
    "schema_version",
    "signer_workflow",
    "source_commit",
    "source_repository",
    "wheel_filename",
    "wheel_sha256",
}


class RuntimeBuildVerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeBuildIdentity:
    source_commit: str
    wheel_sha256: str
    manifest_sha256: str
    package_name: str
    package_version: str
    source_repository: str
    signer_workflow: str
    verified_at: datetime

    def __post_init__(self) -> None:
        _git_sha(self.source_commit)
        _sha256("wheel", self.wheel_sha256)
        _sha256("manifest", self.manifest_sha256)
        if self.package_name != "systematic-trading-lab" or not self.package_version:
            raise ValueError("runtime package identity is invalid")
        if self.source_repository != SOURCE_REPOSITORY or self.signer_workflow != SIGNER_WORKFLOW:
            raise ValueError("runtime build authority is invalid")
        _utc(self.verified_at)

    @property
    def identity_fingerprint(self) -> str:
        return fingerprint(self)


def verify_attested_build(
    wheel: Path, manifest: Path, *, verified_at: datetime
) -> RuntimeBuildIdentity:
    return _verify_attested_build(
        wheel,
        manifest,
        verified_at=verified_at,
        attest=_verify_github_attestation,
    )


def _verify_attested_build(
    wheel: Path,
    manifest: Path,
    *,
    verified_at: datetime,
    attest: Callable[[Path], None],
) -> RuntimeBuildIdentity:
    try:
        _utc(verified_at)
        wheel_bytes = wheel.read_bytes()
        raw = manifest.read_bytes()
        value = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(value, dict) or set(value) != _MANIFEST_KEYS:
            raise ValueError("runtime build manifest has an invalid shape")
        fields = {key: value[key] for key in _MANIFEST_KEYS}
        if any(not isinstance(item, str) for item in fields.values()):
            raise ValueError("runtime build manifest fields must be strings")
        source_commit = fields["source_commit"]
        wheel_sha256 = fields["wheel_sha256"]
        _git_sha(source_commit)
        _sha256("wheel", wheel_sha256)
        if (
            manifest.name != "runtime-build-manifest.json"
            or wheel.name == manifest.name
            or fields["schema_version"] != SCHEMA_VERSION
            or fields["source_repository"] != SOURCE_REPOSITORY
            or fields["signer_workflow"] != SIGNER_WORKFLOW
            or fields["package_name"] != "systematic-trading-lab"
            or not fields["package_version"]
            or fields["wheel_filename"] != wheel.name
            or hashlib.sha256(wheel_bytes).hexdigest() != wheel_sha256
        ):
            raise ValueError("runtime build manifest differs from its wheel")
        with tempfile.TemporaryDirectory() as directory:
            snapshot_wheel = Path(directory, wheel.name)
            snapshot_manifest = Path(directory, manifest.name)
            snapshot_wheel.write_bytes(wheel_bytes)
            snapshot_manifest.write_bytes(raw)
            attest(snapshot_wheel)
            attest(snapshot_manifest)
        return RuntimeBuildIdentity(
            source_commit=source_commit,
            wheel_sha256=wheel_sha256,
            manifest_sha256=hashlib.sha256(raw).hexdigest(),
            package_name=fields["package_name"],
            package_version=fields["package_version"],
            source_repository=fields["source_repository"],
            signer_workflow=fields["signer_workflow"],
            verified_at=verified_at,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise RuntimeBuildVerificationError("runtime build verification failed") from error


def _verify_github_attestation(path: Path) -> None:
    try:
        subprocess.run(
            [
                "gh",
                "attestation",
                "verify",
                str(path),
                "--repo",
                SOURCE_REPOSITORY,
                "--signer-workflow",
                f"{SOURCE_REPOSITORY}/{SIGNER_WORKFLOW}",
                "--deny-self-hosted-runners",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, UnicodeError, subprocess.SubprocessError) as error:
        raise RuntimeBuildVerificationError("runtime build attestation failed") from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("runtime build manifest contains duplicate fields")
    return result


def _git_sha(value: str) -> None:
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("runtime source commit is invalid")


def _sha256(name: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"runtime {name} digest is invalid")


def _utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("runtime build verification time must be UTC-aware")
