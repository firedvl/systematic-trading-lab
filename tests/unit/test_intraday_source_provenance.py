from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import sys
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import cast
from zipfile import ZipFile

import pytest

import systematic_trading_lab.intraday_source_provenance as provenance
from systematic_trading_lab.fingerprints import canonicalize, fingerprint
from systematic_trading_lab.intraday_source_provenance import (
    INTRADAY_FOUNDATION_LOCK_SHA256,
    IntradayExecutionBuildIdentity,
    IntradayExecutionSourceProvenanceError,
    IntradayRuntimeEnvironmentIdentity,
    _locked_runtime_versions,
    _surface_comparison,
)
from systematic_trading_lab.runtime_build import InstalledRuntimeIdentity, RuntimeBuildIdentity

NOW = datetime(2026, 8, 13, tzinfo=UTC)


def _wheel(tmp_path: Path, replacements: dict[str, bytes] | None = None) -> Path:
    wheel = tmp_path / "systematic_trading_lab-0.1.0-py3-none-any.whl"
    replacements = replacements or {}
    with ZipFile(wheel, "w") as archive:
        for name in provenance._surface_module_paths():
            contents = replacements.get(name, Path("src/systematic_trading_lab", name).read_bytes())
            archive.writestr(f"systematic_trading_lab/{name}", contents)
    return wheel


def _environment() -> IntradayRuntimeEnvironmentIdentity:
    return IntradayRuntimeEnvironmentIdentity(
        uv_lock_sha256=INTRADAY_FOUNDATION_LOCK_SHA256,
        python_executable_sha256="1" * 64,
        python_implementation="CPython",
        python_version="3.12.13",
        python_cache_tag="cpython-312",
        python_flags="sys.flags()",
        platform="test-platform",
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


def test_current_build_surface_exactly_matches_reviewed_foundation(tmp_path: Path) -> None:
    comparison = _surface_comparison(_wheel(tmp_path))

    assert comparison.equivalent
    assert comparison.mismatches == ()
    assert comparison.foundation_component_hashes == comparison.observed_component_hashes
    assert comparison.foundation_surface_fingerprint == (
        "20a5ea0da6bcc4b9284c153a30e5ebe4eb0ade9c3dda6547eb0b6c3623f4713c"
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
            "systematic_trading_lab/datasets.py:feed-reconciliation-v1",
        ),
        (
            "experiment_runner.py",
            b"spec.execution_delay_bars,",
            b"1,",
            "experiment_runner.py:_intraday_computation",
        ),
        (
            "experiment_runner.py",
            b"return result, report, bars",
            b'return result, {**report, "metrics": {}}, bars',
            "experiment_runner.py:_intraday_computation",
        ),
        (
            "experiment_runner.py",
            b"def _intraday_computation(\n",
            b"@staticmethod\ndef _intraday_computation(\n",
            "experiment_runner.py:_intraday_computation",
        ),
        (
            "experiment_runner.py",
            b'initial_cash != Decimal("100000")',
            b'initial_cash != Decimal("1")',
            "experiment_runner.py:_campaign_v1_execution_inputs",
        ),
        (
            "experiment_runner.py",
            b"_intraday_computation(datasets, spec, initial_cash, selected_costs)",
            b'_intraday_computation(datasets, spec, Decimal("1"), selected_costs)',
            "experiment_runner.py:run_cataloged_intraday_experiment",
        ),
    ],
)
def test_surface_rejects_changes_across_the_execution_path(
    tmp_path: Path, path: str, old: bytes, new: bytes, component: str
) -> None:
    source = Path("src/systematic_trading_lab", path).read_bytes()
    assert old in source

    comparison = _surface_comparison(_wheel(tmp_path, {path: source.replace(old, new, 1)}))

    assert not comparison.equivalent
    assert component in comparison.mismatches


def test_surface_requires_every_reviewed_wheel_module(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path)
    missing = tmp_path / "missing.whl"
    with ZipFile(wheel) as source, ZipFile(missing, "w") as output:
        for name in source.namelist():
            if name != "systematic_trading_lab/validation.py":
                output.writestr(name, source.read(name))

    with pytest.raises(KeyError):
        _surface_comparison(missing)


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
    with pytest.raises(ValueError, match="isolated Python with bytecode disabled"):
        provenance._require_isolated_python()


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
        wheel, manifest, lockfile, wheelhouse, verified_at=NOW
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
            verified_at=NOW,
        )
    assert not called


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
