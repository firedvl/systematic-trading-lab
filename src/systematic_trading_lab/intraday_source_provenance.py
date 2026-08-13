"""Attested execution-build provenance for Intraday Campaign V1."""

from __future__ import annotations

import ast
import base64
import csv
import hashlib
import io
import os
import platform
import re
import shutil
import sys
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
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
from .runtime_build import verify_attested_build, verify_installed_runtime

INTRADAY_CAMPAIGN_ID = "intraday-research-v1"
INTRADAY_PLAN_FINGERPRINT = "ce81be36d02cc15f421390bf3d3787714bb0b025797ccfb8de2c1d1236052c1a"
INTRADAY_FOUNDATION_COMMIT = "b1774f547da2976348430b820faf2ebdacdf46af"
INTRADAY_FOUNDATION_LOCK_SHA256 = "d6d60aa5d93644dd3bf932ef84f6793bab6d33992659ed48e968850c6673c00d"
_GIT_SHA = 40
_SHA256 = 64
_PACKAGE_PREFIX = "systematic_trading_lab/"
_WHOLE_MODULES = (
    "backtesting.py",
    "calendar.py",
    "catalog.py",
    "fingerprints.py",
    "intraday_reporting.py",
    "parquet.py",
    "storage.py",
    "strategies.py",
    "validation.py",
)
_AST_COMPONENTS = (
    (
        "experiment_runner.py:run_cataloged_intraday_experiment",
        "experiment_runner.py",
        None,
        "run_cataloged_intraday_experiment",
    ),
    (
        "experiment_runner.py:_campaign_v1_execution_inputs",
        "experiment_runner.py",
        None,
        "_campaign_v1_execution_inputs",
    ),
    (
        "experiment_runner.py:_intraday_computation",
        "experiment_runner.py",
        None,
        "_intraday_computation",
    ),
    (
        "experiment_runner.py:_validate_intraday_models",
        "experiment_runner.py",
        None,
        "_validate_intraday_models",
    ),
    ("experiments.py:ExperimentSplit", "experiments.py", None, "ExperimentSplit"),
    ("experiments.py:IntradayExperimentSpec", "experiments.py", None, "IntradayExperimentSpec"),
    ("experiments.py:_experiment_spec", "experiments.py", None, "_experiment_spec"),
    ("experiments.py:_parse_utc", "experiments.py", None, "_parse_utc"),
    ("experiments.py:_stored_positive_int", "experiments.py", None, "_stored_positive_int"),
)
_SURFACE_DEFINITION = {
    "whole_modules": _WHOLE_MODULES,
    "normalized_modules": ("datasets.py:feed-reconciliation-v1", "domain.py:feed-field-v1"),
    "ast_components": _AST_COMPONENTS,
    "lock_sha256": INTRADAY_FOUNDATION_LOCK_SHA256,
}

# Generated from the sealed foundation computation and the reviewed Campaign V1 bridge.
_FOUNDATION_COMPONENT_HASHES = (
    (
        "experiment_runner.py:_campaign_v1_execution_inputs",
        "c5cbce7bc150c9e825ec84d41b384d471981d70f47227a2289129d4bbaf64143",
    ),
    (
        "experiment_runner.py:_intraday_computation",
        "1a43a0247527a894030dedbb8d116206512ce9f03e46e6b515f80b57fe40f324",
    ),
    (
        "experiment_runner.py:_validate_intraday_models",
        "9170a97d49374af881ccf3ba86208e6cba96a9eefe52bb59cb13d940cc33fb24",
    ),
    (
        "experiment_runner.py:run_cataloged_intraday_experiment",
        "cdb0987a699d286e7aa3de5f268ea14284442ae39fb2b0bc6fc5a76217799fdd",
    ),
    (
        "experiments.py:ExperimentSplit",
        "96486222da68282d4d9e003ab59adb1caa83898d7d2e01fc462d85f327c616a4",
    ),
    (
        "experiments.py:IntradayExperimentSpec",
        "66bb274a9332b772aa97884dd7239ba8a9f53721833f88e9b8c3a36990918f52",
    ),
    (
        "experiments.py:_experiment_spec",
        "01a4b11bd988b956d4589940a7ae31ff8c354e5a19085e735c1600f8b59dfda1",
    ),
    (
        "experiments.py:_parse_utc",
        "583833f0cd6ce6946cf4c3920515736ecae2cfde0305da14d1fc8876b202fa93",
    ),
    (
        "experiments.py:_stored_positive_int",
        "7542617751085cf52169a23182f05d84f41c95962248f81e711d05a3534629b5",
    ),
    (
        "systematic_trading_lab/backtesting.py",
        "dfe84c05d3cc468a527fa1f18c88eb9d9ba7d03369c700dc01abb88c9e5299c3",
    ),
    (
        "systematic_trading_lab/calendar.py",
        "a7242114f1ae84c89a49d4d8ab5ec37e4a21a0574996268a39ade799f0d1bace",
    ),
    (
        "systematic_trading_lab/catalog.py",
        "0b80464fab4ca6be1516fa7267a1db8f4bc04282d940950acd203f2a35e801cd",
    ),
    (
        "systematic_trading_lab/datasets.py:feed-reconciliation-v1",
        "344e0e59950ceb0de6952bd63324e8b33f2c80e212883e146eaab231cb2d2bf5",
    ),
    (
        "systematic_trading_lab/domain.py:feed-field-v1",
        "a2c387199286ff65d1fb639717339afefcf99cab08c0279e2ba42c3265516f61",
    ),
    (
        "systematic_trading_lab/fingerprints.py",
        "297104abf718502115f5a51093840b09db686d01d9a677a0dfa45dda7c802d47",
    ),
    (
        "systematic_trading_lab/intraday_reporting.py",
        "196ca11cd8e0208984ba746b1b4d58428a879e2c2a808f569483640aab039d15",
    ),
    (
        "systematic_trading_lab/parquet.py",
        "34e97c421d1483dd55b4b179285e7a11fcefee86c16f096eaf711318d62e8799",
    ),
    (
        "systematic_trading_lab/storage.py",
        "d18f7f7e27d76f5979eecdc2790ddc2259b5afd7651f150c74d25fd913d9c07c",
    ),
    (
        "systematic_trading_lab/strategies.py",
        "9917f996e2ddf2a318a72a83e28e4238ef97dac225486f105708b172804ef824",
    ),
    (
        "systematic_trading_lab/validation.py",
        "c1b49854c4289065352b88bec19a2417902c84dabf4132cee157dbb078dd23d4",
    ),
    (
        "uv.lock",
        "d6d60aa5d93644dd3bf932ef84f6793bab6d33992659ed48e968850c6673c00d",
    ),
)


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
        ):
            raise ValueError("intraday execution build authority is invalid")

    @property
    def identity_fingerprint(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True)
class IntradayRuntimeEnvironmentIdentity:
    """Exact locked interpreter, timezone, and runtime-dependency identity."""

    uv_lock_sha256: str
    python_executable_sha256: str
    python_implementation: str
    python_version: str
    python_cache_tag: str
    python_flags: str
    platform: str
    decimal_context: tuple[tuple[str, object], ...]
    timezone_source: str
    timezone_sha256: str
    distributions: tuple[tuple[str, str, str, str, str, str], ...]

    def __post_init__(self) -> None:
        if self.uv_lock_sha256 != INTRADAY_FOUNDATION_LOCK_SHA256 or any(
            not _lower_hex(value, _SHA256)
            for value in (
                self.python_executable_sha256,
                self.timezone_sha256,
                *(value for item in self.distributions for value in item[3:]),
            )
        ):
            raise ValueError("intraday runtime environment hashes are invalid")
        if (
            not self.python_implementation
            or not self.python_version
            or not self.python_cache_tag
            or not self.python_flags
            or not self.platform
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
    """Mechanical comparison of the result-affecting build surface to M5B."""

    foundation_commit: str
    definition_fingerprint: str
    foundation_surface_fingerprint: str
    observed_surface_fingerprint: str
    foundation_component_hashes: tuple[tuple[str, str], ...]
    observed_component_hashes: tuple[tuple[str, str], ...]
    mismatches: tuple[str, ...]
    equivalent: bool

    def __post_init__(self) -> None:
        if (
            self.foundation_commit != INTRADAY_FOUNDATION_COMMIT
            or self.definition_fingerprint != fingerprint(_SURFACE_DEFINITION)
            or self.foundation_component_hashes != _FOUNDATION_COMPONENT_HASHES
            or self.foundation_surface_fingerprint != fingerprint(_FOUNDATION_COMPONENT_HASHES)
            or self.observed_surface_fingerprint != fingerprint(self.observed_component_hashes)
            or self.mismatches
            != tuple(
                name
                for (name, expected), (_, observed) in zip(
                    self.foundation_component_hashes,
                    self.observed_component_hashes,
                    strict=True,
                )
                if expected != observed
            )
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
        if (
            self.campaign_id != INTRADAY_CAMPAIGN_ID
            or self.plan_fingerprint != INTRADAY_PLAN_FINGERPRINT
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
    verified_at: datetime | None = None,
) -> IntradayExecutionSourceAssessment:
    """Verify the attested installed build, locked environment, and M5B surface."""

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
            if _sha256(lock_bytes) != INTRADAY_FOUNDATION_LOCK_SHA256:
                raise ValueError("Campaign V1 lockfile differs from its foundation")
            build = verify_attested_build(snapshot_wheel, snapshot_manifest, verified_at=timestamp)
            installed = verify_installed_runtime(build, snapshot_wheel, verified_at=timestamp)
            stable_build = IntradayExecutionBuildIdentity(
                source_commit=build.source_commit,
                wheel_sha256=build.wheel_sha256,
                manifest_sha256=build.manifest_sha256,
                package_name=build.package_name,
                package_version=build.package_version,
                source_repository=build.source_repository,
                signer_workflow=build.signer_workflow,
                distribution_record_sha256=installed.distribution_record_sha256,
                source_files_fingerprint=installed.source_files_fingerprint,
            )
            return IntradayExecutionSourceAssessment(
                campaign_id=INTRADAY_CAMPAIGN_ID,
                plan_fingerprint=INTRADAY_PLAN_FINGERPRINT,
                build_identity=stable_build,
                environment_identity=_environment_identity(lock_bytes, snapshot_wheelhouse),
                surface_comparison=_surface_comparison(snapshot_wheel),
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


def _surface_comparison(wheel: Path) -> IntradayExecutionSurfaceComparison:
    observed = _wheel_surface_component_hashes(wheel)
    expected_names = tuple(name for name, _ in _FOUNDATION_COMPONENT_HASHES)
    if tuple(name for name, _ in observed) != expected_names:
        raise IntradayExecutionSourceProvenanceError(
            "intraday execution surface component definitions differ"
        )
    mismatches = tuple(
        name
        for (name, expected), (_, value) in zip(_FOUNDATION_COMPONENT_HASHES, observed, strict=True)
        if expected != value
    )
    return IntradayExecutionSurfaceComparison(
        foundation_commit=INTRADAY_FOUNDATION_COMMIT,
        definition_fingerprint=fingerprint(_SURFACE_DEFINITION),
        foundation_surface_fingerprint=fingerprint(_FOUNDATION_COMPONENT_HASHES),
        observed_surface_fingerprint=fingerprint(observed),
        foundation_component_hashes=_FOUNDATION_COMPONENT_HASHES,
        observed_component_hashes=observed,
        mismatches=mismatches,
        equivalent=not mismatches,
    )


def _wheel_surface_component_hashes(wheel: Path) -> tuple[tuple[str, str], ...]:
    with ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("execution wheel contains duplicate paths")
        sources = {
            path: archive.read(f"{_PACKAGE_PREFIX}{path}") for path in _surface_module_paths()
        }
    components = {
        f"systematic_trading_lab/{path}": _sha256(sources[path]) for path in _WHOLE_MODULES
    }
    components["systematic_trading_lab/datasets.py:feed-reconciliation-v1"] = _sha256(
        _normalized_datasets(sources["datasets.py"])
    )
    components["systematic_trading_lab/domain.py:feed-field-v1"] = _sha256(
        _normalized_domain(sources["domain.py"])
    )
    parsed = {
        path: ast.parse(source.decode("utf-8", errors="strict"), filename=path)
        for path, source in sources.items()
        if path in {item[1] for item in _AST_COMPONENTS}
    }
    for component, path, container, name in _AST_COMPONENTS:
        node = _selected_ast_node(parsed[path], container, name)
        components[component] = _sha256(_ast_bytes(node))
    components["uv.lock"] = INTRADAY_FOUNDATION_LOCK_SHA256
    return tuple(sorted(components.items()))


def _surface_module_paths() -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                *_WHOLE_MODULES,
                "datasets.py",
                "domain.py",
                *(path for _, path, _, _ in _AST_COMPONENTS),
            }
        )
    )


def _normalized_domain(source: bytes) -> bytes:
    tree = ast.parse(source.decode("utf-8", errors="strict"), filename="domain.py")
    manifest = _selected_ast_node(tree, None, "DatasetManifest")
    assert isinstance(manifest, ast.ClassDef)
    feed_fields = [
        node
        for node in manifest.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "feed"
    ]
    if len(feed_fields) > 1:
        raise ValueError("DatasetManifest feed reconciliation is ambiguous")
    manifest.body = [node for node in manifest.body if node not in feed_fields]
    return _ast_bytes(tree)


class _DatasetFeedReconciliation(ast.NodeTransformer):
    """Remove only PR #114's reviewed feed-identity additions."""

    removed: int = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST | None:
        if node.name == "_optional_text":
            self.removed += 1
            return None
        if node.name in {"_lineage_parent", "_version_key"}:
            before = len(node.args.args)
            node.args.args = [argument for argument in node.args.args if argument.arg != "feed"]
            self.removed += before - len(node.args.args)
        return self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> ast.AST:
        kept = [
            (key, value)
            for key, value in zip(node.keys, node.values, strict=True)
            if not (isinstance(key, ast.Constant) and key.value == "feed")
        ]
        self.removed += len(node.keys) - len(kept)
        node.keys = [key for key, _ in kept]
        node.values = [value for _, value in kept]
        return self.generic_visit(node)

    def visit_keyword(self, node: ast.keyword) -> ast.AST | None:
        if node.arg == "feed":
            self.removed += 1
            return None
        return self.generic_visit(node)

    def visit_If(self, node: ast.If) -> ast.AST | None:
        if ast.unparse(node.test) in {
            "feed is not None and (not isinstance(feed, str) or not feed)",
            "manifest.feed is None",
            "feed is not None",
        }:
            self.removed += 1
            return None
        return self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> ast.AST | None:
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "feed"
        ):
            self.removed += 1
            return None
        return self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> ast.AST:
        visited = self.generic_visit(node)
        assert isinstance(visited, ast.Call)
        node = visited
        name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else None
        )
        if name == "_lineage_parent" and len(node.args) == 7:
            node.args.pop(6)
            self.removed += 1
        elif name == "_version_key" and len(node.args) == 14:
            node.args.pop(11)
            self.removed += 1
        return node


def _normalized_datasets(source: bytes) -> bytes:
    tree = ast.parse(source.decode("utf-8", errors="strict"), filename="datasets.py")
    transformer = _DatasetFeedReconciliation()
    transformed = transformer.visit(tree)
    assert isinstance(transformed, ast.Module)
    remaining = [
        node for node in ast.walk(transformed) if isinstance(node, ast.Name) and node.id == "feed"
    ]
    if remaining or transformer.removed not in {0, 13}:
        raise ValueError("dataset feed reconciliation differs from PR #114")
    return _ast_bytes(transformed)


def _selected_ast_node(tree: ast.Module, container: str | None, name: str) -> ast.AST:
    nodes: Sequence[ast.AST] = tree.body
    if container is not None:
        classes = [
            node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == container
        ]
        if len(classes) != 1:
            raise ValueError("surface class is missing or ambiguous")
        nodes = classes[0].body
    matches = [
        node
        for node in nodes
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name == name
    ]
    if len(matches) != 1:
        raise ValueError(f"surface definition is missing or ambiguous: {name}")
    return matches[0]


def _require_isolated_python() -> None:
    if (
        not sys.flags.isolated
        or not sys.flags.ignore_environment
        or not sys.flags.no_user_site
        or not sys.flags.safe_path
        or not sys.dont_write_bytecode
        or os.environ.get("PYTHONPATH")
    ):
        raise ValueError("Campaign V1 requires isolated Python with bytecode disabled")
    _require_project_no_bytecode()


def _environment_identity(
    lock_bytes: bytes, dependency_wheelhouse: Path
) -> IntradayRuntimeEnvironmentIdentity:
    expected = _locked_runtime_artifacts(lock_bytes)
    wheels = _dependency_wheels(dependency_wheelhouse, expected)
    _require_isolated_python()
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
            candidates[0], wheel_path
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
    _require_loaded_dependency_files(set(expected), verified_files)
    executable = Path(sys.executable).resolve(strict=True)
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
        raise ValueError("decimal context differs from the Campaign V1 foundation")
    cache_tag = sys.implementation.cache_tag
    if not isinstance(cache_tag, str) or not cache_tag:
        raise ValueError("Python cache tag is unavailable")
    return IntradayRuntimeEnvironmentIdentity(
        uv_lock_sha256=_sha256(lock_bytes),
        python_executable_sha256=_sha256(executable.read_bytes()),
        python_implementation=platform.python_implementation(),
        python_version=platform.python_version(),
        python_cache_tag=cache_tag,
        python_flags=repr(sys.flags),
        platform=platform.platform(),
        decimal_context=decimal_context,
        timezone_source=timezone_source,
        timezone_sha256=timezone_sha256,
        distributions=tuple(sorted(distributions)),
    )


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
    distribution: metadata.Distribution, wheel: Path
) -> tuple[str, str, set[Path]]:
    files = distribution.files
    if not files:
        raise ValueError("runtime distribution has no RECORD file set")
    root = Path(str(distribution.locate_file(""))).resolve(strict=True)
    if not root.is_relative_to(Path(sys.prefix).resolve(strict=True)):
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
    environment_root = Path(sys.prefix).resolve(strict=True)
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


def _require_loaded_dependency_files(names: set[str], verified_files: set[Path]) -> None:
    packages = metadata.packages_distributions()
    for module_name, module in sys.modules.items():
        if module is None:
            continue
        providers = packages.get(module_name.partition(".")[0], [])
        if not names.intersection(_canonical_distribution_name(name) for name in providers):
            continue
        module_file = getattr(module, "__file__", None)
        if not isinstance(module_file, str):
            raise ValueError("loaded runtime dependency has no file identity")
        path = Path(module_file).resolve(strict=True)
        if path.suffix == ".pyc" or path not in verified_files:
            raise ValueError("loaded runtime dependency is outside its verified RECORD")


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


def _ast_bytes(node: ast.AST) -> bytes:
    return ast.dump(node, annotate_fields=True, include_attributes=False).encode("utf-8")


def _sha256(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _lower_hex(value: str, length: int) -> bool:
    return len(value) == length and all(character in "0123456789abcdef" for character in value)
