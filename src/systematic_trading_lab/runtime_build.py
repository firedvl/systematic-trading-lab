"""Fail-closed verification of attested runtime build artifacts."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse
from zipfile import BadZipFile, ZipFile

from .config import non_broker_subprocess_environment
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
_TRANSIENT_ATTESTATION_FAILURES = (
    "connection refused",
    "connection reset",
    "could not resolve host",
    "dial tcp",
    "i/o timeout",
    "network is unreachable",
    "no such host",
    "rate limit exceeded",
    "server misbehaving",
    "temporary failure in name resolution",
    "tls handshake timeout",
    "timeout awaiting response headers",
)


class RuntimeBuildVerificationError(RuntimeError):
    pass


class RuntimeBuildAttestationIndeterminateError(RuntimeBuildVerificationError):
    """The remote attestation verdict could not be established for this attempt."""


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


@dataclass(frozen=True)
class InstalledRuntimeIdentity:
    build_identity_fingerprint: str
    source_commit: str
    wheel_sha256: str
    distribution_record_sha256: str
    source_files_fingerprint: str
    verified_at: datetime

    def __post_init__(self) -> None:
        _sha256("build identity", self.build_identity_fingerprint)
        _git_sha(self.source_commit)
        _sha256("wheel", self.wheel_sha256)
        _sha256("distribution record", self.distribution_record_sha256)
        _sha256("source files", self.source_files_fingerprint)
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


def verify_installed_runtime(
    build: RuntimeBuildIdentity, wheel: Path, *, verified_at: datetime
) -> InstalledRuntimeIdentity:
    try:
        distributions = tuple(metadata.distributions(name=build.package_name))
        if len(distributions) != 1:
            raise ValueError("installed runtime must have one distribution")
        distribution = distributions[0]
        if (
            distribution.metadata["Name"] != build.package_name
            or distribution.version != build.package_version
        ):
            raise ValueError("installed distribution identity differs from its build")
        package_module = sys.modules.get("systematic_trading_lab")
        package_file = getattr(package_module, "__file__", None)
        package_paths = getattr(package_module, "__path__", ())
        if not isinstance(package_file, str) or not all(
            isinstance(path, str) for path in package_paths
        ):
            raise ValueError("loaded runtime package identity is invalid")
        loaded_files: list[Path] = []
        for name, module in sys.modules.items():
            if name == "systematic_trading_lab" or name.startswith("systematic_trading_lab."):
                if module is None:
                    continue
                loaded_file = getattr(module, "__file__", None)
                if not isinstance(loaded_file, str):
                    raise ValueError("loaded runtime module identity is invalid")
                loaded_files.append(Path(loaded_file))
        return _verify_installed_runtime(
            build,
            wheel,
            root=Path(str(distribution.locate_file(""))),
            module_file=Path(__file__),
            package_file=Path(package_file),
            package_paths=tuple(Path(path) for path in package_paths),
            loaded_files=tuple(loaded_files),
            verified_at=verified_at,
        )
    except (metadata.PackageNotFoundError, OSError, TypeError, ValueError) as error:
        raise RuntimeBuildVerificationError("installed runtime verification failed") from error


def _verify_installed_runtime(
    build: RuntimeBuildIdentity,
    wheel: Path,
    *,
    root: Path,
    module_file: Path,
    package_file: Path | None = None,
    package_paths: tuple[Path, ...] | None = None,
    loaded_files: tuple[Path, ...] | None = None,
    verified_at: datetime,
) -> InstalledRuntimeIdentity:
    try:
        _utc(verified_at)
        if verified_at < build.verified_at:
            raise ValueError("installed runtime verification predates its build verification")
        wheel_bytes = wheel.read_bytes()
        if hashlib.sha256(wheel_bytes).hexdigest() != build.wheel_sha256:
            raise ValueError("installed runtime wheel differs from its build")
        dist_info_name = f"systematic_trading_lab-{build.package_version}.dist-info"
        record_name = f"{dist_info_name}/RECORD"
        with ZipFile(io.BytesIO(wheel_bytes)) as archive:
            names = [name for name in archive.namelist() if not name.endswith("/")]
            if len(names) != len(set(names)) or record_name not in names:
                raise ValueError("runtime wheel file set is invalid")
            wheel_records = _records(archive.read(record_name))
            if set(wheel_records) != set(names) or wheel_records[record_name] != ("", None):
                raise ValueError("runtime wheel record differs from its files")
            wheel_files = {name: archive.read(name) for name in names if name != record_name}
        root = root.resolve(strict=True)
        dist_info = root / dist_info_name
        package = root / "systematic_trading_lab"
        if module_file.resolve(strict=True) != (package / "runtime_build.py").resolve(strict=True):
            raise ValueError("loaded runtime module is outside the installed distribution")
        installed_record_raw = (dist_info / "RECORD").read_bytes()
        installed_records = _records(installed_record_raw, allow_parent=True)
        if installed_records.get(record_name) != ("", None):
            raise ValueError("installed distribution record self-entry is invalid")
        source_records: list[tuple[str, str]] = []
        for name, contents in wheel_files.items():
            expected = wheel_records[name]
            if installed_records.get(name) != expected or not _record_matches(contents, expected):
                raise ValueError("installed distribution differs from its wheel record")
            installed_path = root / PurePosixPath(name)
            if not installed_path.resolve(strict=True).is_relative_to(root):
                raise ValueError("installed distribution file escapes its root")
            installed_contents = installed_path.read_bytes()
            if installed_contents != contents or not _record_matches(installed_contents, expected):
                raise ValueError("installed distribution file differs from its wheel")
            if name.startswith("systematic_trading_lab/") and name.endswith(".py"):
                source_records.append((name, expected[0]))
        expected_package_files = {
            name for name in wheel_files if name.startswith("systematic_trading_lab/")
        }
        expected_package_entries = set(expected_package_files)
        for name in expected_package_files:
            expected_package_entries.update(
                parent.as_posix()
                for parent in PurePosixPath(name).parents
                if parent.as_posix() != "systematic_trading_lab" and parent.as_posix() != "."
            )
        installed_package_entries: set[str] = set()
        for path in package.rglob("*"):
            if "__pycache__" in path.parts:
                continue
            if path.is_symlink():
                raise ValueError("installed runtime package contains a symbolic link")
            installed_package_entries.add(path.relative_to(root).as_posix())
        if not source_records or installed_package_entries != expected_package_entries:
            raise ValueError("installed runtime package file set differs from its wheel")
        expected_package = package.resolve(strict=True)
        package_file = package_file or package / "__init__.py"
        if package_paths is None:
            package_paths = (package,)
        if loaded_files is None:
            loaded_files = (package_file, module_file)
        if package_file.resolve(strict=True) != (package / "__init__.py").resolve(
            strict=True
        ) or tuple(path.resolve(strict=True) for path in package_paths) != (expected_package,):
            raise ValueError("loaded runtime package is outside the installed distribution")
        for loaded_file in loaded_files:
            loaded = loaded_file.resolve(strict=True)
            if (
                not loaded.is_relative_to(expected_package)
                or loaded.relative_to(root).as_posix() not in expected_package_files
            ):
                raise ValueError("loaded runtime module is outside the installed distribution")
        direct_url = dist_info / "direct_url.json"
        direct_url_raw = direct_url.read_bytes()
        direct_url_name = f"{dist_info_name}/direct_url.json"
        direct_url_record = installed_records.get(direct_url_name)
        if direct_url_record is None or not _record_matches(direct_url_raw, direct_url_record):
            raise ValueError("installed runtime origin record is invalid")
        _verify_direct_url(direct_url_raw, build, wheel.name)
        return InstalledRuntimeIdentity(
            build_identity_fingerprint=build.identity_fingerprint,
            source_commit=build.source_commit,
            wheel_sha256=build.wheel_sha256,
            distribution_record_sha256=hashlib.sha256(installed_record_raw).hexdigest(),
            source_files_fingerprint=fingerprint(sorted(source_records)),
            verified_at=verified_at,
        )
    except (
        BadZipFile,
        csv.Error,
        KeyError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as error:
        raise RuntimeBuildVerificationError("installed runtime verification failed") from error


def _verify_attested_build(
    wheel: Path,
    manifest: Path,
    *,
    verified_at: datetime,
    attest: Callable[[Path, str], None],
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
            attest(snapshot_wheel, source_commit)
            attest(snapshot_manifest, source_commit)
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


def _verify_github_attestation(path: Path, source_commit: str) -> None:
    _git_sha(source_commit)
    try:
        subprocess.run(
            [
                "gh",
                "attestation",
                "verify",
                str(path),
                "--repo",
                SOURCE_REPOSITORY,
                "--hostname",
                "github.com",
                "--signer-workflow",
                f"{SOURCE_REPOSITORY}/{SIGNER_WORKFLOW}",
                "--source-ref",
                "refs/heads/main",
                "--source-digest",
                source_commit,
                "--deny-self-hosted-runners",
            ],
            check=True,
            capture_output=True,
            env=non_broker_subprocess_environment(),
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeBuildAttestationIndeterminateError(
            "runtime build attestation verdict is indeterminate"
        ) from error
    except subprocess.CalledProcessError as error:
        stderr = error.stderr.lower() if isinstance(error.stderr, str) else ""
        if error.returncode == 1 and (
            any(message in stderr for message in _TRANSIENT_ATTESTATION_FAILURES)
            or any(f"http {status}" in stderr for status in (429, 500, 502, 503, 504))
        ):
            raise RuntimeBuildAttestationIndeterminateError(
                "runtime build attestation verdict is indeterminate"
            ) from error
        raise RuntimeBuildVerificationError("runtime build attestation failed") from error
    except (OSError, UnicodeError, subprocess.SubprocessError) as error:
        raise RuntimeBuildVerificationError("runtime build attestation failed") from error


def _records(raw: bytes, *, allow_parent: bool = False) -> dict[str, tuple[str, int | None]]:
    result: dict[str, tuple[str, int | None]] = {}
    for row in csv.reader(io.StringIO(raw.decode("utf-8", errors="strict"))):
        if len(row) != 3 or not row[0] or row[0] in result:
            raise ValueError("distribution record is invalid")
        path = PurePosixPath(row[0])
        if path.is_absolute() or (not allow_parent and ".." in path.parts) or "\\" in row[0]:
            raise ValueError("distribution record path is invalid")
        if bool(row[1]) != bool(row[2]):
            raise ValueError("distribution record hash and size must both be present")
        if row[1]:
            algorithm, separator, digest = row[1].partition("=")
            if algorithm != "sha256" or separator != "=" or not digest:
                raise ValueError("distribution record hash is invalid")
            size = int(row[2])
            if size < 0:
                raise ValueError("distribution record size is invalid")
        else:
            size = None
        result[row[0]] = (row[1], size)
    return result


def _record_matches(contents: bytes, record: tuple[str, int | None]) -> bool:
    digest, size = record
    encoded = base64.urlsafe_b64encode(hashlib.sha256(contents).digest()).rstrip(b"=").decode()
    return digest == f"sha256={encoded}" and size == len(contents)


def _verify_direct_url(raw: bytes, build: RuntimeBuildIdentity, wheel_name: str) -> None:
    value = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(value, dict) or set(value) != {"archive_info", "url"}:
        raise ValueError("installed runtime origin must name one archive")
    archive = value["archive_info"]
    url = value["url"]
    if not isinstance(archive, dict) or not isinstance(url, str):
        raise ValueError("installed runtime origin is invalid")
    if set(archive) not in ({"hash"}, {"hashes"}, {"hash", "hashes"}):
        raise ValueError("installed runtime archive digest is missing")
    if "hashes" in archive and archive["hashes"] != {"sha256": build.wheel_sha256}:
        raise ValueError("installed runtime archive digest differs from its wheel")
    if "hash" in archive and archive["hash"] != f"sha256={build.wheel_sha256}":
        raise ValueError("installed runtime archive hash differs from its wheel")
    parsed_url = urlparse(url)
    if not parsed_url.scheme or PurePosixPath(unquote(parsed_url.path)).name != wheel_name:
        raise ValueError("installed runtime archive name differs from its wheel")


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
