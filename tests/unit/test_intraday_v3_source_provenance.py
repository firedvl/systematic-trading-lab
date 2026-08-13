from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest

import systematic_trading_lab.intraday_source_provenance as v2_provenance
import systematic_trading_lab.intraday_v3_source_provenance as provenance
from systematic_trading_lab.fingerprints import canonicalize
from systematic_trading_lab.intraday_campaigns import INTRADAY_FOUNDATION_LOCK_SHA256
from systematic_trading_lab.intraday_source_provenance import IntradayRuntimeEnvironmentIdentity
from systematic_trading_lab.runtime_build import (
    AttestationVerifierIdentity,
    InstalledRuntimeIdentity,
    RuntimeBuildIdentity,
    RuntimeBuildVerificationError,
)

NOW = datetime(2026, 8, 13, tzinfo=UTC)


def _environment() -> IntradayRuntimeEnvironmentIdentity:
    return IntradayRuntimeEnvironmentIdentity(
        uv_lock_sha256=INTRADAY_FOUNDATION_LOCK_SHA256,
        runtime_root="/runtime",
        pyvenv_config_sha256="0" * 64,
        python_executable="/runtime/bin/python",
        python_executable_chain=(("/runtime/bin/python", "file", "1" * 64),),
        python_executable_sha256="1" * 64,
        base_prefix="/base-python",
        base_runtime_fingerprint="2" * 64,
        base_runtime_entry_count=1,
        site_packages_path="/runtime/lib/python3.12/site-packages",
        site_packages_fingerprint="3" * 64,
        site_packages_entry_count=1,
        sys_path=("/base-python/lib/python3.12",),
        python_implementation="CPython",
        python_version="3.12.13",
        python_cache_tag="cpython-312",
        python_flags="sys.flags()",
        platform="test-platform",
        meta_path=(
            ("_frozen_importlib", "BuiltinImporter"),
            ("_frozen_importlib", "FrozenImporter"),
            ("_frozen_importlib_external", "PathFinder"),
            ("six", "_SixMetaPathImporter"),
        ),
        path_hooks=(
            ("zipimport", "zipimporter"),
            (
                "_frozen_importlib_external",
                "FileFinder.path_hook.<locals>.path_hook_for_FileFinder",
            ),
        ),
        decimal_context=v2_provenance._default_decimal_context(),
        timezone_source="tzdata:America/New_York",
        timezone_sha256="4" * 64,
        distributions=(
            (
                "pyarrow",
                "25.0.0",
                "pyarrow-25.0.0-cp312-cp312-manylinux_x86_64.whl",
                "5" * 64,
                "6" * 64,
                "7" * 64,
            ),
        ),
    )


def _write_surface(
    path: Path, package_files: dict[str, bytes], lockfile: Path, **updates: object
) -> dict[str, object]:
    value: dict[str, object] = {
        "components": [
            {"path": name, "sha256": hashlib.sha256(contents).hexdigest()}
            for name, contents in sorted(package_files.items())
        ],
        "source_commit": "a" * 40,
        "source_foundation_commit": "d03be5eaa1e5d2d360424a6c0d06c1ce0bc6a723",
        "lock_sha256": hashlib.sha256(lockfile.read_bytes()).hexdigest(),
        "schema_version": "intraday-v3-whole-package-source-surface-v1",
    }
    value.update(updates)
    path.write_text(
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8"
    )
    return value


def _artifacts(tmp_path: Path) -> tuple[dict[str, Path], dict[str, bytes]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    package_files = {
        "systematic_trading_lab/__init__.py": b"",
        "systematic_trading_lab/data.json": b"{}\n",
        "systematic_trading_lab/intraday_v3.py": b"VALUE = 3\n",
    }
    wheel = tmp_path / "systematic_trading_lab-0.1.0-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        for name, contents in package_files.items():
            archive.writestr(name, contents)
    build_manifest = tmp_path / "runtime-build-manifest.json"
    build_manifest.write_text("{}\n", encoding="utf-8")
    lockfile = tmp_path / "uv.lock"
    lockfile.write_bytes(Path("uv.lock").read_bytes())
    surface = tmp_path / "intraday-v3-whole-package-surface.json"
    _write_surface(surface, package_files, lockfile)
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "dependency.whl").write_bytes(b"dependency")
    return {
        "wheel": wheel,
        "build_manifest": build_manifest,
        "surface": surface,
        "lockfile": lockfile,
        "wheelhouse": wheelhouse,
    }, package_files


def _mock_runtime(
    monkeypatch: pytest.MonkeyPatch, wheel: Path
) -> tuple[RuntimeBuildIdentity, AttestationVerifierIdentity]:
    verifier = AttestationVerifierIdentity(path="/reviewed/bin/gh", sha256="f" * 64)
    build = RuntimeBuildIdentity(
        source_commit="a" * 40,
        wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
        manifest_sha256="b" * 64,
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
        distribution_record_sha256="c" * 64,
        source_files_fingerprint="d" * 64,
        verified_at=NOW,
    )
    monkeypatch.setattr(provenance, "verify_attested_build", lambda *args, **kwargs: build)
    monkeypatch.setattr(provenance, "verify_installed_runtime", lambda *args, **kwargs: installed)
    monkeypatch.setattr(provenance, "_environment_identity", lambda *args: _environment())
    monkeypatch.setattr(provenance, "_verify_github_attestation", lambda *args, **kwargs: verifier)
    return build, verifier


def _assess(paths: dict[str, Path]) -> provenance.IntradayV3SourcePreassessment:
    return provenance.assess_intraday_v3_source_preassessment(
        paths["wheel"],
        paths["build_manifest"],
        paths["surface"],
        paths["lockfile"],
        paths["wheelhouse"],
        verified_at=NOW,
    )


def test_v3_source_preassessment_is_exact_deterministic_and_non_authoritative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, _ = _artifacts(tmp_path)
    build, verifier = _mock_runtime(monkeypatch, paths["wheel"])

    first = _assess(paths)
    second = _assess(paths)

    assert first == second
    assert first.assessment_fingerprint == second.assessment_fingerprint
    assert first.build_identity.source_commit == build.source_commit
    assert first.surface_identity.attestation_verifier == verifier
    assert first.assessment_scope == "artifact-preassessment-only"
    payload = canonicalize(first)
    assert isinstance(payload, dict)
    assert set(payload) == {
        "assessment_scope",
        "build_identity",
        "environment_identity",
        "surface_identity",
    }
    assert not {"campaign_id", "plan_fingerprint", "authorities"} & payload.keys()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "other"),
        ("source_commit", "b" * 40),
        ("source_foundation_commit", "c" * 40),
        ("lock_sha256", "d" * 64),
    ],
)
def test_v3_source_preassessment_rejects_manifest_identity_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    paths, package_files = _artifacts(tmp_path)
    _mock_runtime(monkeypatch, paths["wheel"])
    _write_surface(paths["surface"], package_files, paths["lockfile"], **{field: value})

    with pytest.raises(provenance.IntradayV3SourceProvenanceError):
        _assess(paths)


def test_v3_source_preassessment_rejects_duplicate_unsafe_and_incomplete_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, package_files = _artifacts(tmp_path)
    _mock_runtime(monkeypatch, paths["wheel"])
    surface = _write_surface(paths["surface"], package_files, paths["lockfile"])
    components = surface["components"]
    assert isinstance(components, list)
    components.append(dict(components[0]))
    paths["surface"].write_text(json.dumps(surface), encoding="utf-8")
    with pytest.raises(provenance.IntradayV3SourceProvenanceError):
        _assess(paths)

    for unsafe_path in (
        "systematic_trading_lab/../rogue.py",
        "systematic_trading_lab//rogue.py",
    ):
        unsafe = dict(surface)
        unsafe["components"] = [{"path": unsafe_path, "sha256": "e" * 64}]
        paths["surface"].write_text(json.dumps(unsafe), encoding="utf-8")
        with pytest.raises(provenance.IntradayV3SourceProvenanceError):
            _assess(paths)

    missing = dict(surface)
    missing["components"] = [
        item for item in components[:-1] if item["path"] != "systematic_trading_lab/intraday_v3.py"
    ]
    paths["surface"].write_text(json.dumps(missing), encoding="utf-8")
    with pytest.raises(provenance.IntradayV3SourceProvenanceError):
        _assess(paths)


def test_v3_source_preassessment_rejects_duplicate_json_fields_and_wheel_substitution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, _ = _artifacts(tmp_path)
    _mock_runtime(monkeypatch, paths["wheel"])
    raw = paths["surface"].read_text(encoding="utf-8").rstrip()
    paths["surface"].write_text(raw[:-1] + ',"schema_version":"duplicate"}\n', encoding="utf-8")
    with pytest.raises(provenance.IntradayV3SourceProvenanceError):
        _assess(paths)

    paths, _ = _artifacts(tmp_path / "changed")
    _mock_runtime(monkeypatch, paths["wheel"])
    with ZipFile(paths["wheel"], "a") as archive:
        archive.writestr("systematic_trading_lab/rogue.py", b"VALUE = 1\n")
    with pytest.raises(provenance.IntradayV3SourceProvenanceError):
        _assess(paths)


def test_v3_source_preassessment_rejects_attestation_and_runtime_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, _ = _artifacts(tmp_path)
    _, verifier = _mock_runtime(monkeypatch, paths["wheel"])
    other = AttestationVerifierIdentity(path="/other/bin/gh", sha256="e" * 64)
    monkeypatch.setattr(provenance, "_verify_github_attestation", lambda *args: other)
    with pytest.raises(provenance.IntradayV3SourceProvenanceError):
        _assess(paths)

    def fail_attestation(*args: Any, **kwargs: Any) -> AttestationVerifierIdentity:
        raise RuntimeBuildVerificationError("attestation failed")

    monkeypatch.setattr(provenance, "_verify_github_attestation", fail_attestation)
    with pytest.raises(RuntimeBuildVerificationError, match="attestation failed"):
        _assess(paths)

    monkeypatch.setattr(provenance, "_verify_github_attestation", lambda *args: verifier)
    monkeypatch.setattr(
        provenance,
        "_environment_identity",
        lambda *args: (_ for _ in ()).throw(ValueError("wrong dependency runtime")),
    )
    with pytest.raises(provenance.IntradayV3SourceProvenanceError):
        _assess(paths)
