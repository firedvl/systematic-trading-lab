"""Non-authoritative source preassessment for a future V3 campaign."""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal
from zipfile import BadZipFile, ZipFile

from .fingerprints import fingerprint
from .intraday_source_provenance import (
    IntradayExecutionBuildIdentity,
    IntradayRuntimeEnvironmentIdentity,
    _environment_identity,
    _snapshot_file,
    _snapshot_wheelhouse,
    _wheel_file_names,
)
from .runtime_build import (
    AttestationVerifierIdentity,
    _verify_github_attestation,
    verify_attested_build,
    verify_installed_runtime,
)

_FOUNDATION_COMMIT = "d03be5eaa1e5d2d360424a6c0d06c1ce0bc6a723"
_PACKAGE_PREFIX = "systematic_trading_lab/"
_SCHEMA = "intraday-v3-whole-package-source-surface-v1"
_SURFACE_NAME = "intraday-v3-whole-package-surface.json"


class IntradayV3SourceProvenanceError(RuntimeError):
    """The future V3 build surface could not be established exactly."""


@dataclass(frozen=True)
class IntradayV3WholePackageIdentity:
    schema_version: str
    source_commit: str
    source_foundation_commit: str
    lock_sha256: str
    surface_manifest_sha256: str
    wheel_sha256: str
    component_hashes: tuple[tuple[str, str], ...]
    attestation_verifier: AttestationVerifierIdentity

    def __post_init__(self) -> None:
        if (
            self.schema_version != _SCHEMA
            or not _hex(self.source_commit, 40)
            or self.source_foundation_commit != _FOUNDATION_COMMIT
            or any(
                not _hex(value, 64)
                for value in (self.lock_sha256, self.surface_manifest_sha256, self.wheel_sha256)
            )
            or not _valid_components(self.component_hashes)
        ):
            raise ValueError("V3 whole-package identity is invalid")

    @property
    def identity_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class IntradayV3SourcePreassessment:
    build_identity: IntradayExecutionBuildIdentity
    environment_identity: IntradayRuntimeEnvironmentIdentity
    surface_identity: IntradayV3WholePackageIdentity
    assessment_scope: Literal["artifact-preassessment-only"] = "artifact-preassessment-only"

    def __post_init__(self) -> None:
        if (
            self.assessment_scope != "artifact-preassessment-only"
            or self.surface_identity.source_commit != self.build_identity.source_commit
            or self.surface_identity.wheel_sha256 != self.build_identity.wheel_sha256
            or self.surface_identity.lock_sha256 != self.environment_identity.uv_lock_sha256
            or self.surface_identity.attestation_verifier
            != self.build_identity.attestation_verifier
        ):
            raise ValueError("V3 source preassessment identity is inconsistent")

    @property
    def assessment_fingerprint(self) -> str:
        return fingerprint(self)


def assess_intraday_v3_source_preassessment(
    wheel: Path,
    build_manifest: Path,
    whole_package_manifest: Path,
    lockfile: Path,
    dependency_wheelhouse: Path,
    *,
    verified_at: datetime | None = None,
) -> IntradayV3SourcePreassessment:
    """Verify future main artifacts without creating a campaign or authority."""

    timestamp = verified_at or datetime.now(UTC)
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_wheel = _snapshot_file(wheel, root)
            snapshot_build_manifest = _snapshot_file(build_manifest, root)
            snapshot_surface = _snapshot_file(whole_package_manifest, root)
            snapshot_lockfile = _snapshot_file(lockfile, root)
            snapshot_wheelhouse = _snapshot_wheelhouse(dependency_wheelhouse, root / "dependencies")
            lock_bytes = snapshot_lockfile.read_bytes()
            build = verify_attested_build(
                snapshot_wheel, snapshot_build_manifest, verified_at=timestamp
            )
            verifier = build.attestation_verifier
            if verifier is None:
                raise ValueError("attested V3 build lacks verifier identity")
            surface = _surface_identity(
                snapshot_surface,
                snapshot_wheel,
                build.source_commit,
                build.wheel_sha256,
                hashlib.sha256(lock_bytes).hexdigest(),
                verifier,
            )
            # Private reuse keeps the frozen V2 provenance module byte-exact.
            if (
                _verify_github_attestation(snapshot_surface, build.source_commit, verifier)
                != verifier
            ):
                raise ValueError("V3 surface attestation used another verifier")
            installed = verify_installed_runtime(build, snapshot_wheel, verified_at=timestamp)
            stable_build = IntradayExecutionBuildIdentity(
                source_commit=build.source_commit,
                wheel_sha256=build.wheel_sha256,
                manifest_sha256=build.manifest_sha256,
                package_name=build.package_name,
                package_version=build.package_version,
                source_repository=build.source_repository,
                signer_workflow=build.signer_workflow,
                attestation_verifier=verifier,
                distribution_record_sha256=installed.distribution_record_sha256,
                source_files_fingerprint=installed.source_files_fingerprint,
            )
            return IntradayV3SourcePreassessment(
                stable_build,
                _environment_identity(lock_bytes, snapshot_wheelhouse),
                surface,
            )
    except (BadZipFile, csv.Error, KeyError, OSError, TypeError, UnicodeError, ValueError) as error:
        raise IntradayV3SourceProvenanceError("V3 source preassessment failed") from error


def _surface_identity(
    manifest: Path,
    wheel: Path,
    source_commit: str,
    wheel_sha256: str,
    lock_sha256: str,
    verifier: AttestationVerifierIdentity,
) -> IntradayV3WholePackageIdentity:
    raw = manifest.read_bytes()
    value = json.loads(raw, object_pairs_hook=_unique_object)
    if (
        manifest.name != _SURFACE_NAME
        or not isinstance(value, dict)
        or set(value)
        != {
            "components",
            "lock_sha256",
            "schema_version",
            "source_commit",
            "source_foundation_commit",
        }
        or value["schema_version"] != _SCHEMA
        or value["source_commit"] != source_commit
        or value["source_foundation_commit"] != _FOUNDATION_COMMIT
        or value["lock_sha256"] != lock_sha256
        or not isinstance(value["components"], list)
    ):
        raise ValueError("V3 whole-package manifest identity differs")
    components: list[tuple[str, str]] = []
    for component in value["components"]:
        if not isinstance(component, dict) or set(component) != {"path", "sha256"}:
            raise ValueError("V3 whole-package component is invalid")
        path = component["path"]
        digest = component["sha256"]
        if not isinstance(path, str) or not isinstance(digest, str):
            raise ValueError("V3 whole-package component identity is invalid")
        components.append((path, digest))
    expected = tuple(components)
    if not _valid_components(expected):
        raise ValueError("V3 whole-package component set is invalid")
    with ZipFile(wheel) as archive:
        names = _wheel_file_names(archive)
        package_names = tuple(sorted(name for name in names if name.startswith(_PACKAGE_PREFIX)))
        observed = tuple(
            (name, hashlib.sha256(archive.read(name)).hexdigest()) for name in package_names
        )
    if expected != observed or hashlib.sha256(wheel.read_bytes()).hexdigest() != wheel_sha256:
        raise ValueError("V3 whole-package manifest differs from its wheel")
    return IntradayV3WholePackageIdentity(
        _SCHEMA,
        source_commit,
        _FOUNDATION_COMMIT,
        lock_sha256,
        hashlib.sha256(raw).hexdigest(),
        wheel_sha256,
        expected,
        verifier,
    )


def _valid_components(components: tuple[tuple[str, str], ...]) -> bool:
    paths = tuple(path for path, _ in components)
    return (
        bool(components)
        and paths == tuple(sorted(set(paths)))
        and f"{_PACKAGE_PREFIX}intraday_v3.py" in paths
        and all(
            path.startswith(_PACKAGE_PREFIX)
            and path != _PACKAGE_PREFIX
            and PurePosixPath(path).as_posix() == path
            and not PurePosixPath(path).is_absolute()
            and ".." not in PurePosixPath(path).parts
            and "\\" not in path
            and _hex(digest, 64)
            for path, digest in components
        )
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("V3 whole-package manifest contains duplicate fields")
    return value


def _hex(value: str, length: int) -> bool:
    return len(value) == length and all(character in "0123456789abcdef" for character in value)
