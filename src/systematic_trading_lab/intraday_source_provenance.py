"""Attested execution-build provenance for closed intraday campaigns."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import platform
import re
import shutil
import stat
import sys
import tempfile
import tomllib
import types
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import getcontext
from email.parser import BytesParser
from email.policy import default
from importlib import metadata, resources
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse
from zipfile import BadZipFile, ZipFile
from zoneinfo import TZPATH

from .fingerprints import canonical_json, canonicalize, fingerprint
from .intraday_campaigns import (
    INTRADAY_CAMPAIGN_CONTRACTS,
    INTRADAY_CAMPAIGN_V1_ID,
    INTRADAY_FOUNDATION_LOCK_SHA256,
    IntradayCampaignContract,
    get_intraday_campaign_contract,
)
from .runtime_build import (
    AttestationVerifierIdentity,
    verify_attested_build,
    verify_installed_runtime,
)

INTRADAY_CAMPAIGN_ID = INTRADAY_CAMPAIGN_V1_ID
INTRADAY_PLAN_FINGERPRINT = "ce81be36d02cc15f421390bf3d3787714bb0b025797ccfb8de2c1d1236052c1a"
INTRADAY_FOUNDATION_COMMIT = "b1774f547da2976348430b820faf2ebdacdf46af"
_GIT_SHA = 40
_SHA256 = 64
_PACKAGE_PREFIX = "systematic_trading_lab/"
INTRADAY_RUNTIME_BOOTSTRAP = (
    "import runpy,sys; sys.path.append(sys.argv.pop(1)); "
    'runpy.run_module("systematic_trading_lab.cli", run_name="__main__")'
)
_LOADER_ENVIRONMENT_NAMES = {
    "LD_AUDIT",
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "PYTHONHOME",
    "PYTHONPATH",
}
_EXPECTED_META_PATH = (
    ("_frozen_importlib", "BuiltinImporter"),
    ("_frozen_importlib", "FrozenImporter"),
    ("_frozen_importlib_external", "PathFinder"),
    ("six", "_SixMetaPathImporter"),
)
_DEFAULT_PATH_HOOKS = (
    ("zipimport", "zipimporter"),
    (
        "_frozen_importlib_external",
        "FileFinder.path_hook.<locals>.path_hook_for_FileFinder",
    ),
)


def _sha256(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _lower_hex(value: str, length: int) -> bool:
    return len(value) == length and all(character in "0123456789abcdef" for character in value)


@dataclass(frozen=True)
class _ReviewedSurface:
    contract: IntradayCampaignContract
    raw: bytes
    components: tuple[Mapping[str, object], ...]
    hashes: tuple[tuple[str, str], ...]
    definition: Mapping[str, object]


def _load_reviewed_surface_manifest(campaign_id: str) -> _ReviewedSurface:
    contract = get_intraday_campaign_contract(campaign_id)
    raw = Path(__file__).with_name(contract.surface_manifest_name).read_bytes()
    value = json.loads(raw)
    legacy = campaign_id == INTRADAY_CAMPAIGN_V1_ID
    fields = {
        "components",
        "foundation_commit",
        "lock_sha256",
        "schema_version",
    }
    if not legacy:
        fields |= {"campaign_id", "plan_fingerprint"}
    if not isinstance(value, Mapping) or set(value) != fields:
        raise RuntimeError("intraday campaign surface manifest is invalid")
    components = value["components"]
    if (
        value["schema_version"] != contract.surface_manifest_schema
        or value["foundation_commit"] != contract.foundation_commit
        or value["lock_sha256"] != contract.lock_sha256
        or (not legacy and value["campaign_id"] != contract.campaign_id)
        or (not legacy and value["plan_fingerprint"] != contract.plan_fingerprint)
        or not isinstance(components, list)
        or not components
    ):
        raise RuntimeError("intraday campaign surface manifest identity differs")
    records: list[Mapping[str, object]] = []
    hashes: list[tuple[str, str]] = []
    for component in components:
        component_fields = (
            {
                "classification",
                "diff_sha256",
                "foundation_sha256",
                "patch_id",
                "path",
                "sha256",
            }
            if legacy
            else {"path", "sha256"}
        )
        if not isinstance(component, Mapping) or set(component) != component_fields:
            raise RuntimeError("intraday campaign surface component is invalid")
        path = component["path"]
        digest = component["sha256"]
        if (
            not isinstance(path, str)
            or not path.startswith(_PACKAGE_PREFIX)
            or not path.endswith(".py")
            or PurePosixPath(path).is_absolute()
            or ".." in PurePosixPath(path).parts
            or not isinstance(digest, str)
            or not _lower_hex(digest, _SHA256)
        ):
            raise RuntimeError("intraday campaign surface component identity is invalid")
        if legacy:
            foundation_digest = component["foundation_sha256"]
            classification = component["classification"]
            patch_id = component["patch_id"]
            diff_sha256 = component["diff_sha256"]
            if classification == "foundation-exact":
                valid_classification = (
                    foundation_digest == digest and patch_id is None and diff_sha256 is None
                )
            else:
                valid_classification = (
                    classification in {"reviewed-delta", "reviewed-new-file"}
                    and (foundation_digest is None or _lower_hex(str(foundation_digest), _SHA256))
                    and isinstance(patch_id, str)
                    and _lower_hex(patch_id, _GIT_SHA)
                    and isinstance(diff_sha256, str)
                    and _lower_hex(diff_sha256, _SHA256)
                    and (classification != "reviewed-new-file" or foundation_digest is None)
                )
            if not valid_classification:
                raise RuntimeError("Campaign V1 surface delta identity is invalid")
        records.append(dict(component))
        hashes.append((path, digest))
    if tuple(path for path, _ in hashes) != tuple(sorted({path for path, _ in hashes})):
        raise RuntimeError("intraday campaign surface component paths are invalid")
    definition = {
        "schema_version": (
            "intraday-campaign-v1-whole-package-surface-v1"
            if legacy
            else "intraday-campaign-v2-whole-package-surface-v1"
        ),
        "surface_manifest_sha256": _sha256(raw),
        "components": tuple(records),
        "lock_sha256": contract.lock_sha256,
    }
    return _ReviewedSurface(contract, raw, tuple(records), tuple(hashes), definition)


_V1_SURFACE = _load_reviewed_surface_manifest(INTRADAY_CAMPAIGN_ID)
_SURFACE_MANIFEST_RAW = _V1_SURFACE.raw
_SURFACE_COMPONENTS = _V1_SURFACE.components
_REVIEWED_COMPONENT_HASHES = _V1_SURFACE.hashes
_SURFACE_DEFINITION = _V1_SURFACE.definition


class IntradayExecutionSourceProvenanceError(RuntimeError):
    """The executing build or its foundation equivalence could not be established."""


@dataclass(frozen=True)
class IntradayExecutionBuildIdentity:
    """Stable identity of the attested wheel and the installed project package."""

    source_commit: str
    wheel_sha256: str
    manifest_sha256: str
    package_name: str
    package_version: str
    source_repository: str
    signer_workflow: str
    attestation_verifier: AttestationVerifierIdentity
    distribution_record_sha256: str
    source_files_fingerprint: str

    def __post_init__(self) -> None:
        if not _lower_hex(self.source_commit, _GIT_SHA) or any(
            not _lower_hex(value, _SHA256)
            for value in (
                self.wheel_sha256,
                self.manifest_sha256,
                self.distribution_record_sha256,
                self.source_files_fingerprint,
            )
        ):
            raise ValueError("intraday execution build identity is invalid")
        if (
            self.package_name != "systematic-trading-lab"
            or not self.package_version
            or self.source_repository != "firedvl/systematic-trading-lab"
            or self.signer_workflow != ".github/workflows/build-provenance.yml"
            or not isinstance(self.attestation_verifier, AttestationVerifierIdentity)
        ):
            raise ValueError("intraday execution build authority is invalid")

    @property
    def identity_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class IntradayRuntimeEnvironmentIdentity:
    """Exact startup, interpreter, timezone, and runtime-dependency identity."""

    uv_lock_sha256: str
    runtime_root: str
    pyvenv_config_sha256: str
    python_executable: str
    python_executable_chain: tuple[tuple[str, str, str], ...]
    python_executable_sha256: str
    base_prefix: str
    base_runtime_fingerprint: str
    base_runtime_entry_count: int
    site_packages_path: str
    site_packages_fingerprint: str
    site_packages_entry_count: int
    sys_path: tuple[str, ...]
    python_implementation: str
    python_version: str
    python_cache_tag: str
    python_flags: str
    platform: str
    meta_path: tuple[tuple[str, str], ...]
    path_hooks: tuple[tuple[str, str], ...]
    decimal_context: tuple[tuple[str, object], ...]
    timezone_source: str
    timezone_sha256: str
    distributions: tuple[tuple[str, str, str, str, str, str], ...]

    def __post_init__(self) -> None:
        if self.uv_lock_sha256 != INTRADAY_FOUNDATION_LOCK_SHA256 or any(
            not _lower_hex(value, _SHA256)
            for value in (
                self.pyvenv_config_sha256,
                self.python_executable_sha256,
                self.base_runtime_fingerprint,
                self.site_packages_fingerprint,
                self.timezone_sha256,
                *(value for item in self.distributions for value in item[3:]),
            )
        ):
            raise ValueError("intraday runtime environment hashes are invalid")
        if (
            not Path(self.runtime_root).is_absolute()
            or not Path(self.python_executable).is_absolute()
            or not Path(self.base_prefix).is_absolute()
            or not Path(self.site_packages_path).is_absolute()
            or not self.python_executable_chain
            or self.python_executable_chain[-1][1] != "file"
            or self.python_executable_chain[-1][2] != self.python_executable_sha256
            or any(
                not Path(path).is_absolute() or kind not in {"file", "symlink"} or not value
                for path, kind, value in self.python_executable_chain
            )
            or self.base_runtime_entry_count < 1
            or self.site_packages_entry_count < 1
            or not self.sys_path
            or not self.python_implementation
            or not self.python_version
            or not self.python_cache_tag
            or not self.python_flags
            or not self.platform
            or self.meta_path != _EXPECTED_META_PATH
            or self.path_hooks != _DEFAULT_PATH_HOOKS
            or not self.timezone_source
            or self.distributions != tuple(sorted(self.distributions))
            or any(
                not name or not version or not filename.endswith(".whl")
                for name, version, filename, _, _, _ in self.distributions
            )
        ):
            raise ValueError("intraday runtime environment identity is invalid")

    @property
    def identity_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class IntradayExecutionSurfaceComparison:
    """Exact comparison to one reviewed whole-package campaign surface."""

    foundation_commit: str
    surface_manifest_sha256: str
    surface_manifest_fingerprint: str
    reviewed_surface_fingerprint: str
    observed_surface_fingerprint: str
    reviewed_component_hashes: tuple[tuple[str, str], ...]
    observed_component_hashes: tuple[tuple[str, str], ...]
    mismatches: tuple[str, ...]
    equivalent: bool

    def __post_init__(self) -> None:
        surface = _surface_for_identity(self.foundation_commit, self.surface_manifest_sha256)
        if (
            self.surface_manifest_fingerprint != fingerprint(surface.definition)
            or self.reviewed_component_hashes != surface.hashes
            or self.reviewed_surface_fingerprint != fingerprint(surface.hashes)
            or self.observed_surface_fingerprint != fingerprint(self.observed_component_hashes)
            or self.mismatches
            != _component_mismatches(surface.hashes, self.observed_component_hashes)
            or self.equivalent != (not self.mismatches)
        ):
            raise ValueError("intraday execution surface comparison is inconsistent")

    @property
    def comparison_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class IntradayExecutionSourceAssessment:
    """Stable evidence reviewed once and freshly reproduced before every claim."""

    campaign_id: str
    plan_fingerprint: str
    build_identity: IntradayExecutionBuildIdentity
    environment_identity: IntradayRuntimeEnvironmentIdentity
    surface_comparison: IntradayExecutionSurfaceComparison

    def __post_init__(self) -> None:
        contract = get_intraday_campaign_contract(self.campaign_id)
        if (
            self.plan_fingerprint != contract.plan_fingerprint
            or self.surface_comparison.foundation_commit != contract.foundation_commit
        ):
            raise ValueError("intraday execution source assessment is for another campaign")

    @property
    def assessment_fingerprint(self) -> str:
        return fingerprint(self)


def assess_intraday_execution_source(
    wheel: Path,
    manifest: Path,
    lockfile: Path,
    dependency_wheelhouse: Path,
    *,
    campaign_id: str = INTRADAY_CAMPAIGN_ID,
    verified_at: datetime | None = None,
) -> IntradayExecutionSourceAssessment:
    """Verify the attested installed build, locked environment, and M5B surface."""

    contract = get_intraday_campaign_contract(campaign_id)
    timestamp = verified_at or datetime.now(UTC)
    try:
        with tempfile.TemporaryDirectory() as directory:
            snapshot_root = Path(directory)
            snapshot_wheel = _snapshot_file(wheel, snapshot_root)
            snapshot_manifest = _snapshot_file(manifest, snapshot_root)
            snapshot_lockfile = _snapshot_file(lockfile, snapshot_root)
            snapshot_wheelhouse = _snapshot_wheelhouse(
                dependency_wheelhouse, snapshot_root / "dependencies"
            )
            lock_bytes = snapshot_lockfile.read_bytes()
            if _sha256(lock_bytes) != contract.lock_sha256:
                raise ValueError("intraday campaign lockfile differs from its foundation")
            build = verify_attested_build(snapshot_wheel, snapshot_manifest, verified_at=timestamp)
            if build.attestation_verifier is None:
                raise ValueError("attested build lacks verifier identity")
            installed = verify_installed_runtime(build, snapshot_wheel, verified_at=timestamp)
            stable_build = IntradayExecutionBuildIdentity(
                source_commit=build.source_commit,
                wheel_sha256=build.wheel_sha256,
                manifest_sha256=build.manifest_sha256,
                package_name=build.package_name,
                package_version=build.package_version,
                source_repository=build.source_repository,
                signer_workflow=build.signer_workflow,
                attestation_verifier=build.attestation_verifier,
                distribution_record_sha256=installed.distribution_record_sha256,
                source_files_fingerprint=installed.source_files_fingerprint,
            )
            return IntradayExecutionSourceAssessment(
                campaign_id=contract.campaign_id,
                plan_fingerprint=contract.plan_fingerprint,
                build_identity=stable_build,
                environment_identity=_environment_identity(lock_bytes, snapshot_wheelhouse),
                surface_comparison=_surface_comparison(snapshot_wheel, campaign_id),
            )
    except IntradayExecutionSourceProvenanceError:
        raise
    except (
        BadZipFile,
        csv.Error,
        KeyError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as error:
        raise IntradayExecutionSourceProvenanceError(
            "intraday execution source verification failed"
        ) from error


def _snapshot_file(source: Path, directory: Path) -> Path:
    if source.is_symlink() or not source.is_file() or source.name in {"", ".", ".."}:
        raise ValueError("execution source artifact path is invalid")
    target = directory / source.name
    if target.exists():
        raise ValueError("execution source artifact names collide")
    target.write_bytes(source.read_bytes())
    return target


def _snapshot_wheelhouse(source: Path, target: Path) -> Path:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("runtime dependency wheelhouse is invalid")
    entries = sorted(source.iterdir(), key=lambda path: path.name)
    if not entries or any(
        entry.is_symlink() or not entry.is_file() or entry.suffix != ".whl" for entry in entries
    ):
        raise ValueError("runtime dependency wheelhouse must contain only wheels")
    target.mkdir()
    for entry in entries:
        shutil.copyfile(entry, target / entry.name)
    return target


def bind_intraday_execution_source(
    report: Mapping[str, object], evidence: Mapping[str, object]
) -> dict[str, object]:
    """Bind runtime evidence without changing the sealed candidate provenance."""

    unsigned = dict(report)
    claimed = unsigned.pop("report_fingerprint", None)
    if not isinstance(claimed, str) or fingerprint(unsigned) != claimed:
        raise IntradayExecutionSourceProvenanceError(
            "intraday report fingerprint is invalid before source binding"
        )
    if "execution_source_provenance" in unsigned or set(evidence) != {"review", "binding"}:
        raise IntradayExecutionSourceProvenanceError(
            "intraday execution source report evidence is invalid"
        )
    unsigned["execution_source_provenance"] = canonicalize(evidence)
    return {**unsigned, "report_fingerprint": fingerprint(unsigned)}


def write_intraday_execution_report(path: Path, report: Mapping[str, object]) -> None:
    """Create one immutable source-bound intraday report."""

    unsigned = dict(report)
    claimed = unsigned.pop("report_fingerprint", None)
    if not isinstance(claimed, str) or fingerprint(unsigned) != claimed:
        raise IntradayExecutionSourceProvenanceError(
            "source-bound intraday report fingerprint is invalid"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            file.write(canonical_json(report) + "\n")
            file.flush()
            os.fsync(file.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise FileExistsError(f"report already exists: {path}") from error
    finally:
        temporary.unlink(missing_ok=True)


def _surface_for_identity(foundation_commit: str, surface_manifest_sha256: str) -> _ReviewedSurface:
    for contract in INTRADAY_CAMPAIGN_CONTRACTS:
        surface = _load_reviewed_surface_manifest(contract.campaign_id)
        if (
            surface.contract.foundation_commit == foundation_commit
            and _sha256(surface.raw) == surface_manifest_sha256
        ):
            return surface
    raise ValueError("intraday execution surface identity is unknown")


def _surface_comparison(
    wheel: Path, campaign_id: str = INTRADAY_CAMPAIGN_ID
) -> IntradayExecutionSurfaceComparison:
    surface = _load_reviewed_surface_manifest(campaign_id)
    observed = _wheel_surface_component_hashes(wheel, campaign_id)
    mismatches = _component_mismatches(surface.hashes, observed)
    return IntradayExecutionSurfaceComparison(
        foundation_commit=surface.contract.foundation_commit,
        surface_manifest_sha256=_sha256(surface.raw),
        surface_manifest_fingerprint=fingerprint(surface.definition),
        reviewed_surface_fingerprint=fingerprint(surface.hashes),
        observed_surface_fingerprint=fingerprint(observed),
        reviewed_component_hashes=surface.hashes,
        observed_component_hashes=observed,
        mismatches=mismatches,
        equivalent=not mismatches,
    )


def _wheel_surface_component_hashes(
    wheel: Path, campaign_id: str = INTRADAY_CAMPAIGN_ID
) -> tuple[tuple[str, str], ...]:
    surface = _load_reviewed_surface_manifest(campaign_id)
    with ZipFile(wheel) as archive:
        names = _wheel_file_names(archive)
        package_names = tuple(sorted(name for name in names if name.startswith(_PACKAGE_PREFIX)))
        selected_manifest = f"{_PACKAGE_PREFIX}{surface.contract.surface_manifest_name}"
        known_manifests = {
            f"{_PACKAGE_PREFIX}{contract.surface_manifest_name}"
            for contract in INTRADAY_CAMPAIGN_CONTRACTS
        }
        component_paths = set(_surface_component_paths(campaign_id))
        package_paths = set(package_names)
        if selected_manifest not in package_paths:
            raise ValueError("execution wheel lacks its reviewed surface manifest")
        if package_paths - known_manifests != component_paths:
            return tuple(
                sorted(
                    (name, _sha256(archive.read(name)))
                    for name in package_names
                    if name not in known_manifests
                )
            )
        manifest_raw = archive.read(selected_manifest)
        if manifest_raw != surface.raw:
            raise ValueError("execution wheel surface manifest differs from its reviewed manifest")
        return tuple(
            (path, _sha256(archive.read(path))) for path in _surface_component_paths(campaign_id)
        )


def _surface_module_paths(campaign_id: str = INTRADAY_CAMPAIGN_ID) -> tuple[str, ...]:
    return tuple(
        path.removeprefix(_PACKAGE_PREFIX) for path in _surface_component_paths(campaign_id)
    )


def _surface_component_paths(campaign_id: str = INTRADAY_CAMPAIGN_ID) -> tuple[str, ...]:
    return tuple(path for path, _ in _load_reviewed_surface_manifest(campaign_id).hashes)


def _surface_mismatches(
    observed: tuple[tuple[str, str], ...], campaign_id: str = INTRADAY_CAMPAIGN_ID
) -> tuple[str, ...]:
    return _component_mismatches(_load_reviewed_surface_manifest(campaign_id).hashes, observed)


def _component_mismatches(
    reviewed: tuple[tuple[str, str], ...], observed: tuple[tuple[str, str], ...]
) -> tuple[str, ...]:
    expected = dict(reviewed)
    actual = dict(observed)
    return tuple(
        sorted(
            (
                *(f"missing:{path}" for path in expected.keys() - actual.keys()),
                *(f"extra:{path}" for path in actual.keys() - expected.keys()),
                *(
                    path
                    for path in expected.keys() & actual.keys()
                    if expected[path] != actual[path]
                ),
            )
        )
    )


@dataclass(frozen=True)
class _RuntimeLayoutEvidence:
    runtime_root: Path
    pyvenv_config_sha256: str
    python_executable: Path
    python_executable_chain: tuple[tuple[str, str, str], ...]
    resolved_executable: Path
    base_prefix: Path
    base_runtime_fingerprint: str
    base_runtime_entry_count: int
    base_runtime_files: frozenset[Path]
    site_packages: Path
    sys_path: tuple[str, ...]
    meta_path: tuple[tuple[str, str], ...]
    path_hooks: tuple[tuple[str, str], ...]


def _require_isolated_python() -> _RuntimeLayoutEvidence:
    loader_environment = {
        name
        for name, value in os.environ.items()
        if value
        and (
            name in _LOADER_ENVIRONMENT_NAMES
            or name.startswith("DYLD_")
            and (name.endswith("_PATH") or name == "DYLD_INSERT_LIBRARIES")
        )
    }
    if (
        not sys.flags.isolated
        or not sys.flags.ignore_environment
        or not sys.flags.no_user_site
        or not sys.flags.no_site
        or not sys.flags.safe_path
        or not sys.dont_write_bytecode
        or sys.version_info[:2] != (3, 12)
        or loader_environment
        or {"site", "sitecustomize", "usercustomize", "_virtualenv"} & sys.modules.keys()
    ):
        raise ValueError(
            "intraday campaigns require startup-hook-free isolated Python with bytecode disabled"
        )
    meta_path = _import_hook_identity(sys.meta_path)
    path_hooks = _import_hook_identity(sys.path_hooks)
    if meta_path != _EXPECTED_META_PATH or path_hooks != _DEFAULT_PATH_HOOKS:
        raise ValueError("intraday campaign Python import hooks differ from their defaults")
    _require_meta_path_state()
    if os.name != "posix" or not Path(sys.executable).is_absolute():
        raise ValueError(
            "intraday campaigns require an absolute POSIX virtual-environment interpreter"
        )
    executable = Path(sys.executable)
    runtime_root = executable.parent.parent
    if runtime_root.resolve(strict=True) != runtime_root or executable.parent.name != "bin":
        raise ValueError("intraday campaign virtual-environment path is invalid")
    executable_chain, resolved_executable = _executable_chain(executable)
    base_prefix = Path(sys.base_prefix).resolve(strict=True)
    if Path(sys.base_prefix) != base_prefix or Path(sys.prefix).resolve(strict=True) != base_prefix:
        raise ValueError("intraday campaign base Python identity is invalid")
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site_packages = runtime_root / "lib" / version / "site-packages"
    if site_packages.is_symlink() or not site_packages.is_dir():
        raise ValueError("intraday campaign runtime site-packages path is invalid")
    site_packages = site_packages.resolve(strict=True)
    base_library = base_prefix / sys.platlibdir
    observed_sys_path = tuple(sys.path)
    if (
        len(observed_sys_path) != 4
        or observed_sys_path[0]
        != str(base_library / f"python{sys.version_info.major}{sys.version_info.minor}.zip")
        or Path(observed_sys_path[1]).resolve(strict=True) != base_library / version
        or Path(observed_sys_path[2]).resolve(strict=True) != base_library / version / "lib-dynload"
        or observed_sys_path[3] != str(site_packages)
    ):
        raise ValueError("intraday campaign Python import path differs from its fixed bootstrap")
    original = tuple(sys.orig_argv)
    if (
        len(original) < 7
        or original[1:6] != ("-I", "-B", "-S", "-c", INTRADAY_RUNTIME_BOOTSTRAP)
        or original[6] != str(site_packages)
        or sys.argv[0] != "-c"
    ):
        raise ValueError("intraday campaign Python bootstrap command differs")
    config_path = runtime_root / "pyvenv.cfg"
    if config_path.is_symlink() or not config_path.is_file():
        raise ValueError("intraday campaign pyvenv.cfg is invalid")
    config_raw = config_path.read_bytes()
    config = _parse_pyvenv_config(config_raw)
    _require_standard_venv_executable(config, resolved_executable, runtime_root, base_prefix)
    _require_project_no_bytecode()
    base_fingerprint, base_count, base_files = _tree_identity(
        base_prefix, allow_internal_symlinks=True
    )
    return _RuntimeLayoutEvidence(
        runtime_root=runtime_root,
        pyvenv_config_sha256=_sha256(config_raw),
        python_executable=executable,
        python_executable_chain=executable_chain,
        resolved_executable=resolved_executable,
        base_prefix=base_prefix,
        base_runtime_fingerprint=base_fingerprint,
        base_runtime_entry_count=base_count,
        base_runtime_files=base_files,
        site_packages=site_packages,
        sys_path=observed_sys_path,
        meta_path=meta_path,
        path_hooks=path_hooks,
    )


def _import_hook_identity(hooks: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(hooks, list):
        raise ValueError("Python import hook collection is invalid")
    return tuple(
        (
            str(getattr(hook, "__module__", type(hook).__module__)),
            str(getattr(hook, "__qualname__", type(hook).__qualname__)),
        )
        for hook in hooks
    )


def _require_meta_path_state() -> None:
    for hook in sys.meta_path:
        identity = (
            str(getattr(hook, "__module__", type(hook).__module__)),
            str(getattr(hook, "__qualname__", type(hook).__qualname__)),
        )
        if identity != ("six", "_SixMetaPathImporter"):
            continue
        attributes = vars(hook)
        if set(attributes) != {"known_modules", "name"} or attributes["name"] != "six":
            raise ValueError("intraday campaign six import hook state is invalid")
        known_modules = attributes["known_modules"]
        if not isinstance(known_modules, dict):
            raise ValueError("intraday campaign six import hook module map is invalid")
        for name, value in sorted(known_modules.items()):
            if not isinstance(name, str):
                raise ValueError("intraday campaign six import hook module name is invalid")
            value_type = (type(value).__module__, type(value).__qualname__)
            state = vars(value)
            if isinstance(value, types.ModuleType):
                if not isinstance(value.__name__, str):
                    raise ValueError("intraday campaign six import hook module is invalid")
                _module_spec_identity(value)
            elif value_type == ("six", "MovedModule") and set(state).issubset(
                {"__name__", "__spec__", "mod", "name"}
            ):
                if not all(
                    item is None or isinstance(item, str)
                    for item in (state.get("name"), state.get("mod"))
                ):
                    raise ValueError("intraday campaign six import hook target is invalid")
                _module_spec_identity(value)
            else:
                raise ValueError("intraday campaign six import hook target is invalid")


def _module_spec_identity(value: object) -> tuple[object, ...] | None:
    spec = vars(value).get("__spec__")
    if spec is None:
        return None
    loader = getattr(spec, "loader", None)
    return (
        getattr(spec, "name", None),
        getattr(spec, "origin", None),
        None if loader is None else (type(loader).__module__, type(loader).__qualname__),
    )


def _executable_chain(path: Path) -> tuple[tuple[tuple[str, str, str], ...], Path]:
    records: list[tuple[str, str, str]] = []
    seen: set[Path] = set()
    current = path
    for _ in range(40):
        current = Path(os.path.abspath(current))
        if current in seen:
            raise ValueError("intraday campaign Python executable symlink chain loops")
        seen.add(current)
        status = current.lstat()
        if stat.S_ISLNK(status.st_mode):
            target = os.readlink(current)
            records.append((str(current), "symlink", target))
            current = current.parent / target if not Path(target).is_absolute() else Path(target)
            continue
        if not stat.S_ISREG(status.st_mode):
            raise ValueError("intraday campaign Python executable is not a regular file")
        records.append((str(current), "file", _sha256(current.read_bytes())))
        return tuple(records), current.resolve(strict=True)
    raise ValueError("intraday campaign Python executable symlink chain is too deep")


def _parse_pyvenv_config(raw: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in raw.decode("utf-8", errors="strict").splitlines():
        key, separator, value = line.partition("=")
        key = key.strip().lower()
        if not separator or not key or key in result:
            raise ValueError("intraday campaign pyvenv.cfg fields are invalid")
        result[key] = value.strip()
    return result


def _require_standard_venv_executable(
    config: Mapping[str, str], resolved_executable: Path, runtime_root: Path, base_prefix: Path
) -> None:
    configured_executable = config.get("executable")
    configured_home = config.get("home")
    base_executable = (
        Path(configured_executable).resolve(strict=True) if configured_executable else None
    )
    base_home = Path(configured_home).resolve(strict=True) if configured_home else None
    if (
        config.get("include-system-site-packages") != "false"
        or config.get("version") != platform.python_version()
        or base_executable is None
        or base_home is None
        or base_executable.parent != base_home
        or not base_executable.is_relative_to(base_prefix)
        or (
            resolved_executable != base_executable
            and (
                not resolved_executable.is_relative_to(runtime_root)
                or resolved_executable.read_bytes() != base_executable.read_bytes()
            )
        )
    ):
        raise ValueError("intraday campaign pyvenv.cfg differs from a closed standard-library venv")


def _tree_identity(
    root: Path, *, allow_internal_symlinks: bool
) -> tuple[str, int, frozenset[Path]]:
    root = root.resolve(strict=True)
    records: list[tuple[object, ...]] = []
    regular_files: set[Path] = set()
    paths = (root, *sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix()))
    for path in paths:
        relative = "." if path == root else path.relative_to(root).as_posix()
        status = path.lstat()
        mode = stat.S_IMODE(status.st_mode)
        if stat.S_ISDIR(status.st_mode):
            records.append((relative, "directory", mode))
        elif stat.S_ISLNK(status.st_mode):
            target = os.readlink(path)
            resolved = path.resolve(strict=True)
            if not allow_internal_symlinks or not resolved.is_relative_to(root):
                raise ValueError("runtime tree contains a prohibited symbolic link")
            records.append((relative, "symlink", mode, target))
        elif stat.S_ISREG(status.st_mode):
            contents = path.read_bytes()
            after = path.lstat()
            if (
                status.st_dev,
                status.st_ino,
                status.st_mode,
                status.st_size,
                status.st_mtime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ValueError("runtime tree changed during verification")
            records.append((relative, "file", mode, len(contents), _sha256(contents)))
            regular_files.add(path.resolve(strict=True))
        else:
            raise ValueError("runtime tree contains a special file")
    return fingerprint(tuple(records)), len(records), frozenset(regular_files)


def _environment_identity(
    lock_bytes: bytes, dependency_wheelhouse: Path
) -> IntradayRuntimeEnvironmentIdentity:
    expected = _locked_runtime_artifacts(lock_bytes)
    wheels = _dependency_wheels(dependency_wheelhouse, expected)
    runtime = _require_isolated_python()
    installed_names = {
        _canonical_distribution_name(distribution.metadata["Name"])
        for distribution in metadata.distributions()
        if distribution.metadata["Name"]
    }
    if installed_names != {"systematic-trading-lab", *expected}:
        raise ValueError("installed runtime distributions differ from the locked environment")
    distributions: list[tuple[str, str, str, str, str, str]] = []
    verified_files: set[Path] = set()
    for name, (version, _) in expected.items():
        candidates = tuple(metadata.distributions(name=name))
        if len(candidates) != 1 or candidates[0].version != version:
            raise ValueError(f"locked runtime distribution differs: {name}")
        wheel_path, wheel_sha256 = wheels[name]
        file_fingerprint, wheel_record_sha256, files = _distribution_files(
            candidates[0], wheel_path, runtime_root=runtime.runtime_root
        )
        verified_files.update(files)
        distributions.append(
            (
                name,
                version,
                wheel_path.name,
                wheel_sha256,
                wheel_record_sha256,
                file_fingerprint,
            )
        )
    project_distributions = tuple(metadata.distributions(name="systematic-trading-lab"))
    if len(project_distributions) != 1:
        raise ValueError("installed project distribution is ambiguous")
    verified_files.update(_distribution_owned_files(project_distributions[0], runtime.runtime_root))
    site_fingerprint, site_count, site_files = _site_packages_identity(
        runtime.site_packages, verified_files
    )
    _require_loaded_module_files(
        runtime.base_runtime_files | site_files,
        runtime.base_prefix,
        runtime.site_packages,
    )
    timezone_source, timezone_sha256 = _timezone_identity()
    context = getcontext()
    decimal_context = tuple(
        sorted(
            {
                "precision": context.prec,
                "rounding": context.rounding,
                "minimum_exponent": context.Emin,
                "maximum_exponent": context.Emax,
                "capitals": context.capitals,
                "clamp": context.clamp,
                "traps": tuple(
                    sorted(signal.__name__ for signal, enabled in context.traps.items() if enabled)
                ),
            }.items()
        )
    )
    if decimal_context != _default_decimal_context():
        raise ValueError("decimal context differs from the intraday campaign foundation")
    cache_tag = sys.implementation.cache_tag
    if not isinstance(cache_tag, str) or not cache_tag:
        raise ValueError("Python cache tag is unavailable")
    return IntradayRuntimeEnvironmentIdentity(
        uv_lock_sha256=_sha256(lock_bytes),
        runtime_root=str(runtime.runtime_root),
        pyvenv_config_sha256=runtime.pyvenv_config_sha256,
        python_executable=str(runtime.python_executable),
        python_executable_chain=runtime.python_executable_chain,
        python_executable_sha256=_sha256(runtime.resolved_executable.read_bytes()),
        base_prefix=str(runtime.base_prefix),
        base_runtime_fingerprint=runtime.base_runtime_fingerprint,
        base_runtime_entry_count=runtime.base_runtime_entry_count,
        site_packages_path=str(runtime.site_packages),
        site_packages_fingerprint=site_fingerprint,
        site_packages_entry_count=site_count,
        sys_path=runtime.sys_path,
        python_implementation=platform.python_implementation(),
        python_version=platform.python_version(),
        python_cache_tag=cache_tag,
        python_flags=repr(sys.flags),
        platform=platform.platform(),
        meta_path=runtime.meta_path,
        path_hooks=runtime.path_hooks,
        decimal_context=decimal_context,
        timezone_source=timezone_source,
        timezone_sha256=timezone_sha256,
        distributions=tuple(sorted(distributions)),
    )


def _distribution_owned_files(distribution: metadata.Distribution, runtime_root: Path) -> set[Path]:
    files = distribution.files
    if not files:
        raise ValueError("runtime distribution has no installed file set")
    result: set[Path] = set()
    for item in files:
        path = Path(str(distribution.locate_file(item)))
        if path.is_symlink():
            raise ValueError("runtime distribution contains a symbolic link")
        path = path.resolve(strict=True)
        if not path.is_file() or not path.is_relative_to(runtime_root):
            raise ValueError("runtime distribution file escapes its environment")
        result.add(path)
    return result


def _site_packages_identity(
    site_packages: Path, verified_files: set[Path]
) -> tuple[str, int, frozenset[Path]]:
    fingerprint_value, entry_count, files = _tree_identity(
        site_packages, allow_internal_symlinks=False
    )
    for path in files:
        relative = path.relative_to(site_packages)
        if (
            path.suffix in {".pth", ".pyc"}
            or "__pycache__" in relative.parts
            or path.name in {"sitecustomize.py", "usercustomize.py"}
        ):
            raise ValueError("runtime site-packages contains a prohibited startup or bytecode file")
    expected = frozenset(path for path in verified_files if path.is_relative_to(site_packages))
    if files != expected:
        raise ValueError("runtime site-packages contains an unowned or missing file")
    return fingerprint_value, entry_count, files


def _require_loaded_module_files(
    allowed_files: frozenset[Path], base_prefix: Path, site_packages: Path
) -> None:
    for _name, module in sorted(sys.modules.items()):
        if module is None:
            continue
        module_file = getattr(module, "__file__", None)
        spec = getattr(module, "__spec__", None)
        origin = getattr(spec, "origin", None)
        if module_file is None:
            if origin not in {None, "built-in", "frozen"}:
                raise ValueError("loaded runtime module has no verifiable file identity")
            continue
        if not isinstance(module_file, str):
            raise ValueError("loaded runtime module file identity is invalid")
        path = Path(module_file).resolve(strict=True)
        if path not in allowed_files or not (
            path.is_relative_to(base_prefix) or path.is_relative_to(site_packages)
        ):
            raise ValueError("loaded runtime module is outside the verified runtime trees")


def _require_project_no_bytecode() -> None:
    package = sys.modules.get("systematic_trading_lab")
    package_paths = getattr(package, "__path__", ())
    if not isinstance(package_paths, list | tuple) or len(package_paths) != 1:
        raise ValueError("loaded project package path is invalid")
    root = Path(package_paths[0]).resolve(strict=True)
    if any(root.rglob("*.pyc")):
        raise ValueError("installed project package contains cached Python bytecode")
    for name, module in sys.modules.items():
        if module is None or not (
            name == "systematic_trading_lab" or name.startswith("systematic_trading_lab.")
        ):
            continue
        cached = getattr(module, "__cached__", None)
        if isinstance(cached, str) and Path(cached).exists():
            raise ValueError("loaded project module used cached Python bytecode")


def _locked_runtime_versions(lock_bytes: bytes) -> tuple[tuple[str, str], ...]:
    return tuple(
        (name, version) for name, (version, _) in _locked_runtime_artifacts(lock_bytes).items()
    )


def _locked_runtime_artifacts(
    lock_bytes: bytes,
) -> dict[str, tuple[str, dict[str, tuple[str, int]]]]:
    value = tomllib.loads(lock_bytes.decode("utf-8", errors="strict"))
    packages = value.get("package")
    if not isinstance(packages, list):
        raise ValueError("uv.lock package list is invalid")
    by_name: dict[str, Mapping[str, object]] = {}
    for package in packages:
        if not isinstance(package, Mapping):
            raise ValueError("uv.lock package entry is invalid")
        name = package.get("name")
        if not isinstance(name, str) or name in by_name:
            raise ValueError("uv.lock package names are invalid")
        by_name[name] = package
    root = by_name.get("systematic-trading-lab")
    if root is None:
        raise ValueError("uv.lock lacks the project package")
    pending = list(_dependency_names(root))
    selected: dict[str, tuple[str, dict[str, tuple[str, int]]]] = {}
    while pending:
        name = pending.pop()
        package = by_name.get(name)
        if package is None:
            raise ValueError(f"uv.lock dependency is absent: {name}")
        version = package.get("version")
        if not isinstance(version, str) or not version:
            raise ValueError(f"uv.lock dependency version is invalid: {name}")
        wheels = package.get("wheels")
        if not isinstance(wheels, list) or not wheels:
            raise ValueError(f"uv.lock dependency wheels are invalid: {name}")
        artifacts: dict[str, tuple[str, int]] = {}
        for wheel in wheels:
            if not isinstance(wheel, Mapping):
                raise ValueError(f"uv.lock dependency wheel is invalid: {name}")
            digest = wheel.get("hash")
            url = wheel.get("url")
            size = wheel.get("size")
            if (
                not isinstance(digest, str)
                or not digest.startswith("sha256:")
                or not _lower_hex(digest.removeprefix("sha256:"), _SHA256)
                or not isinstance(url, str)
                or type(size) is not int
                or size <= 0
            ):
                raise ValueError(f"uv.lock dependency wheel hash is invalid: {name}")
            filename = unquote(Path(urlparse(url).path).name)
            if not filename.endswith(".whl") or digest.removeprefix("sha256:") in artifacts:
                raise ValueError(f"uv.lock dependency wheel identity is invalid: {name}")
            artifacts[digest.removeprefix("sha256:")] = (filename, size)
        identity = (version, artifacts)
        if name in selected:
            if selected[name] != identity:
                raise ValueError(f"uv.lock has conflicting versions: {name}")
            continue
        selected[name] = identity
        pending.extend(_dependency_names(package))
    return dict(sorted(selected.items()))


def _dependency_names(package: Mapping[str, object]) -> tuple[str, ...]:
    dependencies = package.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise ValueError("uv.lock dependencies are invalid")
    names: list[str] = []
    for dependency in dependencies:
        if not isinstance(dependency, Mapping) or not isinstance(dependency.get("name"), str):
            raise ValueError("uv.lock dependency is invalid")
        names.append(str(dependency["name"]))
    return tuple(names)


def _dependency_wheels(
    wheelhouse: Path,
    expected: Mapping[str, tuple[str, Mapping[str, tuple[str, int]]]],
) -> dict[str, tuple[Path, str]]:
    result: dict[str, tuple[Path, str]] = {}
    entries = sorted(wheelhouse.iterdir(), key=lambda path: path.name)
    if len(entries) != len(expected):
        raise ValueError("runtime dependency wheel set differs from the lockfile")
    for path in entries:
        if path.is_symlink() or not path.is_file() or path.suffix != ".whl":
            raise ValueError("runtime dependency wheelhouse contains an invalid artifact")
        contents = path.read_bytes()
        digest = _sha256(contents)
        name, version = _wheel_name_and_version(contents)
        locked = expected.get(name)
        artifact = locked[1].get(digest) if locked is not None else None
        if (
            locked is None
            or locked[0] != version
            or artifact is None
            or artifact != (path.name, len(contents))
            or name in result
        ):
            raise ValueError("runtime dependency wheel differs from the lockfile")
        result[name] = (path, digest)
    if set(result) != set(expected):
        raise ValueError("runtime dependency wheel set differs from the lockfile")
    return result


def _wheel_name_and_version(contents: bytes) -> tuple[str, str]:
    with ZipFile(io.BytesIO(contents)) as archive:
        names = _wheel_file_names(archive)
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ValueError("runtime dependency wheel metadata is invalid")
        message = BytesParser(policy=default).parsebytes(archive.read(metadata_names[0]))
    name = message.get("Name")
    version = message.get("Version")
    if not isinstance(name, str) or not isinstance(version, str) or not version:
        raise ValueError("runtime dependency wheel identity is invalid")
    return _canonical_distribution_name(name), version


def _distribution_files(
    distribution: metadata.Distribution, wheel: Path, *, runtime_root: Path | None = None
) -> tuple[str, str, set[Path]]:
    files = distribution.files
    if not files:
        raise ValueError("runtime distribution has no RECORD file set")
    root = Path(str(distribution.locate_file(""))).resolve(strict=True)
    environment_root = (runtime_root or Path(sys.prefix)).resolve(strict=True)
    if not root.is_relative_to(environment_root):
        raise ValueError("runtime distribution escapes its environment")
    with ZipFile(wheel) as archive:
        wheel_names = _wheel_file_names(archive)
        record_names = [name for name in wheel_names if name.endswith(".dist-info/RECORD")]
        metadata_names = [name for name in wheel_names if name.endswith(".dist-info/METADATA")]
        wheel_metadata_names = [name for name in wheel_names if name.endswith(".dist-info/WHEEL")]
        if (
            len(record_names) != 1
            or len(metadata_names) != 1
            or len(wheel_metadata_names) != 1
            or len(
                {
                    PurePosixPath(record_names[0]).parent,
                    PurePosixPath(metadata_names[0]).parent,
                    PurePosixPath(wheel_metadata_names[0]).parent,
                }
            )
            != 1
        ):
            raise ValueError("runtime dependency wheel RECORD is invalid")
        record_name = record_names[0]
        wheel_record_raw = archive.read(record_name)
        wheel_records = _wheel_records(wheel_record_raw)
        if set(wheel_records) != set(wheel_names) or wheel_records[record_name] != ("", None):
            raise ValueError("runtime dependency wheel RECORD differs from its files")
        if any(".data/" in name for name in wheel_names):
            raise ValueError("runtime dependency wheel uses an unsupported install scheme")
        expected_files: set[Path] = set()
        for name in wheel_names:
            if name == record_name:
                continue
            contents = archive.read(name)
            if not _record_matches(contents, wheel_records[name]):
                raise ValueError("runtime dependency wheel file differs from RECORD")
            installed_path = root / PurePosixPath(name)
            if installed_path.is_symlink():
                raise ValueError("runtime distribution file is a symbolic link")
            installed_path = installed_path.resolve(strict=True)
            if not installed_path.is_relative_to(root) or installed_path.read_bytes() != contents:
                raise ValueError("installed runtime distribution differs from its wheel")
            expected_files.add(installed_path)
    records: list[tuple[str, str, int]] = []
    resolved_files: set[Path] = set()
    package_roots: set[Path] = set()
    scripts_root = (environment_root / "bin").resolve(strict=True)
    for item in files:
        located = Path(str(distribution.locate_file(item)))
        if located.is_symlink():
            raise ValueError("runtime distribution file is a symbolic link")
        path = located.resolve(strict=True)
        if (
            not path.is_file()
            or not path.is_relative_to(root)
            and not path.is_relative_to(scripts_root)
        ):
            raise ValueError("runtime distribution file escapes its environment")
        if path.suffix == ".pyc" or "__pycache__" in path.parts:
            raise ValueError("runtime distribution contains cached Python bytecode")
        contents = path.read_bytes()
        if item.size is not None and item.size != len(contents):
            raise ValueError("runtime distribution file size differs from RECORD")
        if item.hash is not None:
            digest = (
                base64.urlsafe_b64encode(hashlib.sha256(contents).digest()).rstrip(b"=").decode()
            )
            if item.hash.mode != "sha256" or item.hash.value != digest:
                raise ValueError("runtime distribution file differs from RECORD")
        records.append((str(item), _sha256(contents), len(contents)))
        resolved_files.add(path)
        if item.parts and item.parts[0] != ".." and ".dist-info" not in item.parts[0]:
            package_roots.add((root / item.parts[0]).resolve(strict=True))
    if not expected_files.issubset(resolved_files):
        raise ValueError("installed runtime distribution RECORD differs from its wheel")
    unexpected: set[Path] = set()
    for path in resolved_files - expected_files:
        if path.is_relative_to(scripts_root):
            continue
        if not path.is_relative_to(root) or ".dist-info" not in path.relative_to(root).parts[0]:
            unexpected.add(path)
    if unexpected:
        raise ValueError("installed runtime distribution has files outside its wheel")
    expected_package_files = {
        path for path in expected_files if ".dist-info" not in path.relative_to(root).parts[0]
    }
    for package_root in package_roots:
        observed = (
            {path.resolve(strict=True) for path in package_root.rglob("*") if path.is_file()}
            if package_root.is_dir()
            else {package_root}
        )
        if any(path.is_symlink() for path in package_root.rglob("*")) or not observed.issubset(
            expected_package_files
        ):
            raise ValueError("runtime dependency package tree differs from its wheel")
    return fingerprint(tuple(sorted(records))), _sha256(wheel_record_raw), resolved_files


def _wheel_file_names(archive: ZipFile) -> tuple[str, ...]:
    infos = tuple(info for info in archive.infolist() if not info.is_dir())
    names = tuple(info.filename for info in infos)
    if len(names) != len(set(names)):
        raise ValueError("runtime dependency wheel contains duplicate paths")
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        file_type = (info.external_attr >> 16) & 0o170000
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in name
            or "__pycache__" in path.parts
            or path.suffix == ".pyc"
            or bool(info.flag_bits & 0x1)
            or file_type == 0o120000
        ):
            raise ValueError("runtime dependency wheel path is invalid")
    return names


def _wheel_records(raw: bytes) -> dict[str, tuple[str, int | None]]:
    result: dict[str, tuple[str, int | None]] = {}
    for row in csv.reader(io.StringIO(raw.decode("utf-8", errors="strict"))):
        if len(row) != 3 or not row[0] or row[0] in result:
            raise ValueError("runtime dependency wheel RECORD is invalid")
        if bool(row[1]) != bool(row[2]):
            raise ValueError("runtime dependency RECORD hash and size differ")
        size = int(row[2]) if row[2] else None
        result[row[0]] = (row[1], size)
    return result


def _record_matches(contents: bytes, record: tuple[str, int | None]) -> bool:
    encoded, size = record
    if not encoded and size is None:
        return True
    if size != len(contents) or not encoded.startswith("sha256="):
        return False
    digest = base64.urlsafe_b64encode(hashlib.sha256(contents).digest()).rstrip(b"=").decode()
    return encoded.removeprefix("sha256=") == digest


def _canonical_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _timezone_identity() -> tuple[str, str]:
    relative = Path("America/New_York")
    for directory in TZPATH:
        candidate = Path(directory) / relative
        if candidate.is_file() and not candidate.is_symlink():
            return str(candidate.resolve(strict=True)), _sha256(candidate.read_bytes())
    resource = resources.files("tzdata.zoneinfo").joinpath("America", "New_York")
    contents = resource.read_bytes()
    return "tzdata:America/New_York", _sha256(contents)


def _default_decimal_context() -> tuple[tuple[str, object], ...]:
    return (
        ("capitals", 1),
        ("clamp", 0),
        ("maximum_exponent", 999999),
        ("minimum_exponent", -999999),
        ("precision", 28),
        ("rounding", "ROUND_HALF_EVEN"),
        ("traps", ("DivisionByZero", "InvalidOperation", "Overflow")),
    )
