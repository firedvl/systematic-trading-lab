from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import types
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import cast
from zipfile import ZipFile

import pytest

import systematic_trading_lab.intraday_source_provenance as provenance
from systematic_trading_lab.fingerprints import canonicalize, fingerprint
from systematic_trading_lab.intraday_campaigns import (
    INTRADAY_CAMPAIGN_V1_ID,
    INTRADAY_CAMPAIGN_V2_ID,
    INTRADAY_FOUNDATION_LOCK_SHA256,
)
from systematic_trading_lab.intraday_source_provenance import (
    IntradayExecutionBuildIdentity,
    IntradayExecutionSourceProvenanceError,
    IntradayRuntimeEnvironmentIdentity,
    _locked_runtime_versions,
    _surface_comparison,
)
from systematic_trading_lab.runtime_build import (
    AttestationVerifierIdentity,
    InstalledRuntimeIdentity,
    RuntimeBuildIdentity,
)

NOW = datetime(2026, 8, 13, tzinfo=UTC)
CAMPAIGN_V2_SURFACE = provenance._load_reviewed_surface_manifest(INTRADAY_CAMPAIGN_V2_ID)


def _wheel(
    tmp_path: Path,
    replacements: dict[str, bytes] | None = None,
    *,
    campaign_id: str = INTRADAY_CAMPAIGN_V2_ID,
) -> Path:
    wheel = tmp_path / "systematic_trading_lab-0.1.0-py3-none-any.whl"
    replacements = replacements or {}
    with ZipFile(wheel, "w") as archive:
        for name in provenance._surface_module_paths(campaign_id):
            contents = replacements.get(name, Path("src/systematic_trading_lab", name).read_bytes())
            archive.writestr(f"systematic_trading_lab/{name}", contents)
        for manifest_campaign_id in (INTRADAY_CAMPAIGN_V1_ID, INTRADAY_CAMPAIGN_V2_ID):
            surface = provenance._load_reviewed_surface_manifest(manifest_campaign_id)
            archive.writestr(
                f"systematic_trading_lab/{surface.contract.surface_manifest_name}",
                surface.raw,
            )
    return wheel


def _environment() -> IntradayRuntimeEnvironmentIdentity:
    return IntradayRuntimeEnvironmentIdentity(
        uv_lock_sha256=INTRADAY_FOUNDATION_LOCK_SHA256,
        runtime_root="/runtime",
        pyvenv_config_sha256="0" * 64,
        python_executable="/runtime/bin/python",
        python_executable_chain=(("/runtime/bin/python", "file", "1" * 64),),
        python_executable_sha256="1" * 64,
        base_prefix="/base-python",
        base_runtime_fingerprint="6" * 64,
        base_runtime_entry_count=1,
        site_packages_path="/runtime/lib/python3.12/site-packages",
        site_packages_fingerprint="7" * 64,
        site_packages_entry_count=1,
        sys_path=("/base-python/lib/python3.12",),
        python_implementation="CPython",
        python_version="3.12.13",
        python_cache_tag="cpython-312",
        python_flags="sys.flags()",
        platform="test-platform",
        meta_path=provenance._EXPECTED_META_PATH,
        path_hooks=provenance._DEFAULT_PATH_HOOKS,
        decimal_context=provenance._default_decimal_context(),
        timezone_source="tzdata:America/New_York",
        timezone_sha256="2" * 64,
        distributions=(
            (
                "pyarrow",
                "25.0.0",
                "pyarrow-25.0.0-cp312-cp312-manylinux_x86_64.whl",
                "3" * 64,
                "4" * 64,
                "5" * 64,
            ),
        ),
    )


def test_current_build_surface_exactly_matches_campaign_v2(tmp_path: Path) -> None:
    comparison = _surface_comparison(_wheel(tmp_path), INTRADAY_CAMPAIGN_V2_ID)

    assert comparison.equivalent
    assert comparison.mismatches == ()
    assert comparison.reviewed_component_hashes == comparison.observed_component_hashes
    assert comparison.reviewed_surface_fingerprint
    assert comparison.surface_manifest_fingerprint


def test_campaign_v2_manifest_remains_immutable_closed_evidence() -> None:
    root = Path("src/systematic_trading_lab")
    observed = dict(
        (
            path.relative_to("src").as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(root.rglob("*.py"), key=lambda item: item.relative_to("src").as_posix())
    )

    assert hashlib.sha256(CAMPAIGN_V2_SURFACE.raw).hexdigest() == (
        "3789c1c2549065cc40a9fcc362435a17c75d0cf48f8bb570b146a18fa511ecb6"
    )
    assert len(CAMPAIGN_V2_SURFACE.hashes) == 49
    assert dict(CAMPAIGN_V2_SURFACE.hashes) == {
        path: observed[path] for path, _ in CAMPAIGN_V2_SURFACE.hashes
    }
    assert set(observed) - dict(CAMPAIGN_V2_SURFACE.hashes).keys() == {
        "systematic_trading_lab/intraday_exposure.py",
        "systematic_trading_lab/intraday_v3.py",
        "systematic_trading_lab/intraday_v3_qualification.py",
        "systematic_trading_lab/intraday_v3_source_provenance.py",
    }


def test_current_build_cannot_execute_campaign_v1(tmp_path: Path) -> None:
    comparison = _surface_comparison(_wheel(tmp_path), INTRADAY_CAMPAIGN_V1_ID)

    assert not comparison.equivalent
    assert "extra:systematic_trading_lab/intraday_campaigns.py" in comparison.mismatches
    assert "systematic_trading_lab/providers.py" in comparison.mismatches


def test_surface_manifest_preserves_exact_reviewed_pr_114_deltas() -> None:
    components = {str(item["path"]): item for item in provenance._SURFACE_COMPONENTS}

    assert components["systematic_trading_lab/datasets.py"]["patch_id"] == (
        "3a339ab7866a22a2e200aee617395d9cc05e45c9"
    )
    assert components["systematic_trading_lab/datasets.py"]["diff_sha256"] == (
        "4ac13c3d58d675544a11b4bb00ea9d52996e53b1dc6e84c21658fc0485ec7f92"
    )
    assert components["systematic_trading_lab/domain.py"]["patch_id"] == (
        "952fc104c15c25260b0e29488df7ab61ae4b9a50"
    )
    assert components["systematic_trading_lab/domain.py"]["diff_sha256"] == (
        "c3ded022ed3c9a7a8841c09c8d8c32dac167227c4e4bd084b0ef0605b564a65d"
    )


@pytest.mark.parametrize(
    ("path", "old", "new", "component"),
    [
        (
            "backtesting.py",
            b'raise ValueError("initial cash must be positive")',
            b'raise ValueError("changed computation")',
            "systematic_trading_lab/backtesting.py",
        ),
        (
            "datasets.py",
            b"if requested.start < actual.start or requested.end > actual.end:",
            b"if False:",
            "systematic_trading_lab/datasets.py",
        ),
        (
            "providers.py",
            b'or record["timestamp"] in expected_timestamps',
            b"or True",
            "systematic_trading_lab/providers.py",
        ),
        (
            "experiment_runner.py",
            b"spec.execution_delay_bars,",
            b"1,",
            "systematic_trading_lab/experiment_runner.py",
        ),
        (
            "experiment_runner.py",
            b"return result, report, bars",
            b'return result, {**report, "metrics": {}}, bars',
            "systematic_trading_lab/experiment_runner.py",
        ),
        (
            "experiment_runner.py",
            b"def _intraday_computation(\n",
            b"@staticmethod\ndef _intraday_computation(\n",
            "systematic_trading_lab/experiment_runner.py",
        ),
        (
            "experiment_runner.py",
            b'initial_cash != Decimal("100000")',
            b'initial_cash != Decimal("1")',
            "systematic_trading_lab/experiment_runner.py",
        ),
        (
            "experiment_runner.py",
            b"_intraday_computation(datasets, spec, initial_cash, selected_costs)",
            b'_intraday_computation(datasets, spec, Decimal("1"), selected_costs)',
            "systematic_trading_lab/experiment_runner.py",
        ),
    ],
)
def test_surface_rejects_changes_across_the_execution_path(
    tmp_path: Path, path: str, old: bytes, new: bytes, component: str
) -> None:
    source = Path("src/systematic_trading_lab", path).read_bytes()
    assert old in source

    comparison = _surface_comparison(
        _wheel(tmp_path, {path: source.replace(old, new, 1)}), INTRADAY_CAMPAIGN_V2_ID
    )

    assert not comparison.equivalent
    assert component in comparison.mismatches


def test_surface_requires_every_reviewed_wheel_module(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path)
    missing = tmp_path / "missing.whl"
    with ZipFile(wheel) as source, ZipFile(missing, "w") as output:
        for name in source.namelist():
            if name != "systematic_trading_lab/validation.py":
                output.writestr(name, source.read(name))

    comparison = _surface_comparison(missing, INTRADAY_CAMPAIGN_V2_ID)

    assert not comparison.equivalent
    assert "missing:systematic_trading_lab/validation.py" in comparison.mismatches


@pytest.mark.parametrize(
    ("path", "mutation"),
    [
        (
            "experiment_runner.py",
            b"\nrun_cataloged_intraday_experiment = lambda *args, **kwargs: None\n",
        ),
        (
            "experiments.py",
            b"\nExperimentRegistry.get_planned_intraday_spec = lambda self, value: value\n",
        ),
        (
            "datasets.py",
            b"\nDatasetService.load_bars_range = lambda *args, **kwargs: ()\n",
        ),
    ],
)
def test_surface_rejects_post_definition_and_dataset_rebinding(
    tmp_path: Path, path: str, mutation: bytes
) -> None:
    source = Path("src/systematic_trading_lab", path).read_bytes()

    comparison = _surface_comparison(
        _wheel(tmp_path, {path: source + mutation}), INTRADAY_CAMPAIGN_V2_ID
    )

    assert not comparison.equivalent
    assert f"systematic_trading_lab/{path}" in comparison.mismatches


def test_surface_rejects_verifier_mutation_and_extra_importable_module(tmp_path: Path) -> None:
    source = Path("src/systematic_trading_lab/intraday_source_provenance.py").read_bytes()
    changed = _surface_comparison(
        _wheel(
            tmp_path,
            {"intraday_source_provenance.py": source + b"\nVERIFIER_REBOUND = True\n"},
        ),
        INTRADAY_CAMPAIGN_V2_ID,
    )
    assert not changed.equivalent
    assert "systematic_trading_lab/intraday_source_provenance.py" in changed.mismatches

    wheel = _wheel(tmp_path)
    extra = tmp_path / "extra.whl"
    with ZipFile(wheel) as source_wheel, ZipFile(extra, "w") as output:
        for name in source_wheel.namelist():
            output.writestr(name, source_wheel.read(name))
        output.writestr("systematic_trading_lab/rogue.py", "VALUE = 1\n")

    comparison = _surface_comparison(extra, INTRADAY_CAMPAIGN_V2_ID)
    assert not comparison.equivalent
    assert "extra:systematic_trading_lab/rogue.py" in comparison.mismatches


def test_lockfile_closure_excludes_dev_tools_and_pins_runtime_versions() -> None:
    versions = dict(_locked_runtime_versions(Path("uv.lock").read_bytes()))

    assert versions == {
        "exchange-calendars": "4.13.2",
        "korean-lunar-calendar": "0.4.0",
        "numpy": "2.5.1",
        "pandas": "3.0.5",
        "pyarrow": "25.0.0",
        "pyluach": "2.3.0",
        "python-dateutil": "2.9.0.post0",
        "six": "1.17.0",
        "toolz": "1.1.0",
        "tzdata": "2026.3",
    }
    assert not {"mypy", "pytest", "ruff"} & versions.keys()


def test_dependency_wheelhouse_rejects_a_rebuilt_wheel(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    wheel = wheelhouse / "example-1.0-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("example-1.0.dist-info/METADATA", "Name: example\nVersion: 1.0\n")
        archive.writestr("example-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\n")
        archive.writestr("example-1.0.dist-info/RECORD", "")
    contents = wheel.read_bytes()
    expected = {
        "example": (
            "1.0",
            {hashlib.sha256(contents).hexdigest(): (wheel.name, len(contents))},
        )
    }

    assert (
        provenance._dependency_wheels(wheelhouse, expected)["example"][1]
        == hashlib.sha256(contents).hexdigest()
    )

    with ZipFile(wheel, "a") as archive:
        archive.writestr("example.py", "changed")
    with pytest.raises(ValueError, match="differs from the lockfile"):
        provenance._dependency_wheels(wheelhouse, expected)


def test_campaign_runtime_requires_isolated_bytecode_disabled_python() -> None:
    with pytest.raises(ValueError, match="startup-hook-free isolated Python"):
        provenance._require_isolated_python()


def test_runtime_tree_identity_changes_with_bytes_and_rejects_escaping_symlink(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "base"
    runtime.mkdir()
    library = runtime / "stdlib.py"
    library.write_text("VALUE = 1\n", encoding="utf-8")

    first, first_count, first_files = provenance._tree_identity(
        runtime, allow_internal_symlinks=True
    )
    library.write_text("VALUE = 2\n", encoding="utf-8")
    second, second_count, second_files = provenance._tree_identity(
        runtime, allow_internal_symlinks=True
    )

    assert first != second
    assert first_count == second_count == 2
    assert first_files == second_files == frozenset({library.resolve()})

    outside = tmp_path / "outside.py"
    outside.write_text("VALUE = 3\n", encoding="utf-8")
    os.symlink(outside, runtime / "escape.py")
    with pytest.raises(ValueError, match="prohibited symbolic link"):
        provenance._tree_identity(runtime, allow_internal_symlinks=True)


def test_standard_library_copied_venv_executable_is_accepted_and_mutations_fail(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    subprocess.run(
        [sys.executable, "-m", "venv", "--copies", "--without-pip", str(runtime)],
        check=True,
    )
    executable = runtime / "bin" / f"python{sys.version_info.major}.{sys.version_info.minor}"
    config = provenance._parse_pyvenv_config((runtime / "pyvenv.cfg").read_bytes())

    provenance._require_standard_venv_executable(
        config,
        executable.resolve(strict=True),
        runtime.resolve(strict=True),
        Path(sys.base_prefix).resolve(strict=True),
    )

    executable.write_bytes(executable.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="closed standard-library venv"):
        provenance._require_standard_venv_executable(
            config,
            executable.resolve(strict=True),
            runtime.resolve(strict=True),
            Path(sys.base_prefix).resolve(strict=True),
        )

    configured_executable = Path(config["executable"]).resolve(strict=True)
    external = tmp_path / "external-python"
    external.write_bytes(configured_executable.read_bytes())
    with pytest.raises(ValueError, match="closed standard-library venv"):
        provenance._require_standard_venv_executable(
            config,
            external.resolve(strict=True),
            runtime.resolve(strict=True),
            Path(sys.base_prefix).resolve(strict=True),
        )


def test_loaded_module_inventory_validates_origins_without_becoming_runtime_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "base"
    site_packages = tmp_path / "site-packages"
    base.mkdir()
    site_packages.mkdir()
    first = base / "first.py"
    second = site_packages / "second.py"
    first.write_bytes(b"FIRST = True\n")
    second.write_bytes(b"SECOND = True\n")
    first_module = types.ModuleType("first")
    first_module.__file__ = str(first)
    second_module = types.ModuleType("second")
    second_module.__file__ = str(second)
    monkeypatch.setattr(sys, "modules", {"first": first_module})

    provenance._require_loaded_module_files(
        frozenset({first.resolve(), second.resolve()}), base, site_packages
    )
    sys.modules["second"] = second_module
    provenance._require_loaded_module_files(
        frozenset({first.resolve(), second.resolve()}), base, site_packages
    )

    rogue = tmp_path / "rogue.py"
    rogue.write_bytes(b"ROGUE = True\n")
    second_module.__file__ = str(rogue)
    with pytest.raises(ValueError, match="outside the verified runtime trees"):
        provenance._require_loaded_module_files(
            frozenset({first.resolve(), second.resolve()}), base, site_packages
        )


@pytest.mark.parametrize(
    ("name", "owned", "message"),
    [
        ("_virtualenv.pth", True, "prohibited startup"),
        ("_virtualenv.py", False, "unowned or missing"),
        ("sitecustomize.py", True, "prohibited startup"),
        ("usercustomize.py", True, "prohibited startup"),
        ("cached.pyc", True, "prohibited startup"),
        ("rogue.py", False, "unowned or missing"),
        ("rogue.so", False, "unowned or missing"),
    ],
)
def test_site_packages_rejects_startup_and_unowned_files(
    tmp_path: Path, name: str, owned: bool, message: str
) -> None:
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    injected = site_packages / name
    injected.write_bytes(b"injected")
    expected = {injected.resolve()} if owned else set()

    with pytest.raises(ValueError, match=message):
        provenance._site_packages_identity(site_packages, expected)


def test_site_packages_rejects_symlinks(tmp_path: Path) -> None:
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    target = site_packages / "target.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    os.symlink(target.name, site_packages / "alias.py")

    with pytest.raises(ValueError, match="prohibited symbolic link"):
        provenance._site_packages_identity(site_packages, {target.resolve()})


def test_distribution_identity_rejects_same_version_file_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = tmp_path / "environment"
    (environment / "bin").mkdir(parents=True)
    site_packages = environment / "lib/python3.12/site-packages"
    wheel = tmp_path / "example-1.0-py3-none-any.whl"
    payloads = {
        "example/__init__.py": b"reviewed dependency",
        "example-1.0.dist-info/METADATA": b"Name: example\nVersion: 1.0\n",
        "example-1.0.dist-info/WHEEL": b"Wheel-Version: 1.0\nTag: py3-none-any\n",
    }
    record_rows = [
        (name, f"sha256={_record_hash(contents)}", str(len(contents)))
        for name, contents in payloads.items()
    ]
    record_rows.append(("example-1.0.dist-info/RECORD", "", ""))
    output = io.StringIO()
    csv.writer(output, lineterminator="\n").writerows(record_rows)
    payloads["example-1.0.dist-info/RECORD"] = output.getvalue().encode()
    with ZipFile(wheel, "w") as archive:
        for name, contents in payloads.items():
            archive.writestr(name, contents)
    items: list[metadata.PackagePath] = []
    for name, contents in payloads.items():
        path = site_packages / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        item = metadata.PackagePath(name)
        if not name.endswith("/RECORD"):
            item.hash = metadata.FileHash(f"sha256={_record_hash(contents)}")
            item.size = len(contents)
        else:
            item.hash = None
            item.size = None
        items.append(item)

    class FakeDistribution:
        files = items

        def locate_file(self, path: object) -> Path:
            return site_packages / str(path)

    distribution = cast(metadata.Distribution, FakeDistribution())
    monkeypatch.setattr(sys, "prefix", str(environment))
    provenance._distribution_files(distribution, wheel)

    package = site_packages / "example/__init__.py"
    package.write_bytes(b"tampered dependency")
    items[0].hash = metadata.FileHash(f"sha256={_record_hash(package.read_bytes())}")
    items[0].size = len(package.read_bytes())
    with pytest.raises(ValueError, match="differs from its wheel"):
        provenance._distribution_files(distribution, wheel)


def _record_hash(contents: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(contents).digest()).rstrip(b"=").decode()


def test_assessment_uses_attested_build_and_installed_runtime_without_timestamps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel = _wheel(tmp_path)
    lockfile = tmp_path / "uv.lock"
    lockfile.write_bytes(Path("uv.lock").read_bytes())
    manifest = tmp_path / "runtime-build-manifest.json"
    manifest.write_text(json.dumps({}), encoding="utf-8")
    wheelhouse = tmp_path / "dependency-wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "dependency.whl").write_bytes(b"dependency")
    build = RuntimeBuildIdentity(
        source_commit="a" * 40,
        wheel_sha256="b" * 64,
        manifest_sha256="c" * 64,
        package_name="systematic-trading-lab",
        package_version="0.1.0",
        source_repository="firedvl/systematic-trading-lab",
        signer_workflow=".github/workflows/build-provenance.yml",
        verified_at=NOW,
        attestation_verifier=AttestationVerifierIdentity(path="/usr/local/bin/gh", sha256="f" * 64),
    )
    installed = InstalledRuntimeIdentity(
        build_identity_fingerprint=build.identity_fingerprint,
        source_commit=build.source_commit,
        wheel_sha256=build.wheel_sha256,
        distribution_record_sha256="d" * 64,
        source_files_fingerprint="e" * 64,
        verified_at=NOW,
    )
    calls: list[tuple[str, datetime]] = []

    def verify_build(*args: object, verified_at: datetime) -> RuntimeBuildIdentity:
        calls.append(("build", verified_at))
        return build

    def verify_installed(*args: object, verified_at: datetime) -> InstalledRuntimeIdentity:
        calls.append(("installed", verified_at))
        return installed

    monkeypatch.setattr(provenance, "verify_attested_build", verify_build)
    monkeypatch.setattr(provenance, "verify_installed_runtime", verify_installed)
    monkeypatch.setattr(provenance, "_environment_identity", lambda *_: _environment())

    assessment = provenance.assess_intraday_execution_source(
        wheel,
        manifest,
        lockfile,
        wheelhouse,
        campaign_id=INTRADAY_CAMPAIGN_V2_ID,
        verified_at=NOW,
    )

    assert calls == [("build", NOW), ("installed", NOW)]
    assert assessment.surface_comparison.equivalent
    assert assessment.build_identity == IntradayExecutionBuildIdentity(
        source_commit="a" * 40,
        wheel_sha256="b" * 64,
        manifest_sha256="c" * 64,
        package_name="systematic-trading-lab",
        package_version="0.1.0",
        source_repository="firedvl/systematic-trading-lab",
        signer_workflow=".github/workflows/build-provenance.yml",
        attestation_verifier=AttestationVerifierIdentity(path="/usr/local/bin/gh", sha256="f" * 64),
        distribution_record_sha256="d" * 64,
        source_files_fingerprint="e" * 64,
    )
    assert "verified_at" not in str(canonicalize(assessment))


def test_assessment_rejects_changed_lock_before_attestation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lockfile = tmp_path / "uv.lock"
    lockfile.write_text("changed", encoding="utf-8")
    wheel = tmp_path / "build.whl"
    wheel.write_bytes(b"build")
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b"manifest")
    wheelhouse = tmp_path / "dependency-wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "dependency.whl").write_bytes(b"dependency")
    called = False

    def verify(*args: object, **kwargs: object) -> RuntimeBuildIdentity:
        nonlocal called
        called = True
        raise AssertionError

    monkeypatch.setattr(provenance, "verify_attested_build", verify)

    with pytest.raises(IntradayExecutionSourceProvenanceError, match="verification failed"):
        provenance.assess_intraday_execution_source(
            wheel,
            manifest,
            lockfile,
            wheelhouse,
            campaign_id=INTRADAY_CAMPAIGN_V2_ID,
            verified_at=NOW,
        )
    assert not called


def test_assessment_retains_attestation_verifier_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel = _wheel(tmp_path)
    lockfile = tmp_path / "uv.lock"
    lockfile.write_bytes(Path("uv.lock").read_bytes())
    manifest = tmp_path / "runtime-build-manifest.json"
    manifest.write_bytes(b"manifest")
    wheelhouse = tmp_path / "dependency-wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "dependency.whl").write_bytes(b"dependency")
    verifier = AttestationVerifierIdentity(path="/reviewed/bin/gh", sha256="f" * 64)
    build = RuntimeBuildIdentity(
        source_commit="a" * 40,
        wheel_sha256="b" * 64,
        manifest_sha256="c" * 64,
        package_name="systematic-trading-lab",
        package_version="0.1.0",
        source_repository="firedvl/systematic-trading-lab",
        signer_workflow=".github/workflows/build-provenance.yml",
        verified_at=NOW,
        attestation_verifier=verifier,
    )
    installed = InstalledRuntimeIdentity(
        build_identity_fingerprint=build.identity_fingerprint,
        source_commit=build.source_commit,
        wheel_sha256=build.wheel_sha256,
        distribution_record_sha256="d" * 64,
        source_files_fingerprint="e" * 64,
        verified_at=NOW,
    )
    monkeypatch.setattr(provenance, "verify_attested_build", lambda *args, **kwargs: build)
    monkeypatch.setattr(provenance, "verify_installed_runtime", lambda *args, **kwargs: installed)
    monkeypatch.setattr(provenance, "_environment_identity", lambda *_: _environment())

    assessment = provenance.assess_intraday_execution_source(
        wheel,
        manifest,
        lockfile,
        wheelhouse,
        campaign_id=INTRADAY_CAMPAIGN_V2_ID,
        verified_at=NOW,
    )

    assert assessment.build_identity.attestation_verifier == verifier
    assert assessment.surface_comparison.equivalent


def test_source_bound_report_preserves_sealed_provenance_and_changes_fingerprint() -> None:
    unsigned = {
        "schema_version": "intraday-backtest-report-v1",
        "provenance": {"code_commit": provenance.INTRADAY_FOUNDATION_COMMIT},
        "metrics": {},
    }
    report = {**unsigned, "report_fingerprint": fingerprint(unsigned)}

    bound = provenance.bind_intraday_execution_source(
        report, {"review": {"id": "review"}, "binding": {"id": "candidate"}}
    )

    assert bound["provenance"] == report["provenance"]
    assert bound["report_fingerprint"] != report["report_fingerprint"]
    verified = dict(bound)
    claimed = verified.pop("report_fingerprint")
    assert claimed == fingerprint(verified)
