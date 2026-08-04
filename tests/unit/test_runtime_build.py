from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from systematic_trading_lab.runtime_build import (
    RuntimeBuildVerificationError,
    _verify_attested_build,
    _verify_github_attestation,
)

NOW = datetime(2026, 8, 4, tzinfo=UTC)


def _artifacts(tmp_path: Path) -> tuple[Path, Path]:
    wheel = tmp_path / "systematic_trading_lab-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"reviewed wheel bytes")
    manifest = tmp_path / "runtime-build-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "package_name": "systematic-trading-lab",
                "package_version": "0.1.0",
                "schema_version": "runtime-build-manifest-v1",
                "signer_workflow": ".github/workflows/build-provenance.yml",
                "source_commit": "a" * 40,
                "source_repository": "firedvl/systematic-trading-lab",
                "wheel_filename": wheel.name,
                "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return wheel, manifest


def test_attested_build_binds_exact_wheel_manifest_and_authority(tmp_path: Path) -> None:
    wheel, manifest = _artifacts(tmp_path)
    calls: list[Path] = []
    identity = _verify_attested_build(
        wheel,
        manifest,
        verified_at=NOW,
        attest=calls.append,
    )
    assert [path.name for path in calls] == [wheel.name, manifest.name]
    assert identity.source_commit == "a" * 40
    assert identity.wheel_sha256 == hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert identity.manifest_sha256 == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert identity.identity_fingerprint


def test_attested_build_rejects_tamper_before_attestation(tmp_path: Path) -> None:
    wheel, manifest = _artifacts(tmp_path)
    wheel.write_bytes(b"changed wheel")
    calls: list[Path] = []
    with pytest.raises(RuntimeBuildVerificationError, match="verification failed"):
        _verify_attested_build(
            wheel,
            manifest,
            verified_at=NOW,
            attest=calls.append,
        )
    assert not calls


def test_attested_build_rejects_wrong_authority_and_attestation_failure(
    tmp_path: Path,
) -> None:
    wheel, manifest = _artifacts(tmp_path)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["source_repository"] = "other/repository"
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RuntimeBuildVerificationError, match="verification failed"):
        _verify_attested_build(wheel, manifest, verified_at=NOW, attest=lambda _: None)

    _, manifest = _artifacts(tmp_path)

    def fail(_path: Path) -> None:
        raise RuntimeBuildVerificationError("runtime build attestation failed")

    with pytest.raises(RuntimeBuildVerificationError, match="attestation failed"):
        _verify_attested_build(wheel, manifest, verified_at=NOW, attest=fail)


def test_attested_build_uses_immutable_snapshots_and_rejects_bad_inputs(
    tmp_path: Path,
) -> None:
    wheel, manifest = _artifacts(tmp_path)
    snapshots: list[bytes] = []

    def mutate_sources(snapshot: Path) -> None:
        snapshots.append(snapshot.read_bytes())
        wheel.write_bytes(b"changed after snapshot")
        manifest.write_text("{}", encoding="utf-8")

    _verify_attested_build(wheel, manifest, verified_at=NOW, attest=mutate_sources)
    assert snapshots[0] == b"reviewed wheel bytes"
    assert b'"source_commit":"aaaaaaaa' in snapshots[1]

    wheel, manifest = _artifacts(tmp_path)
    with pytest.raises(RuntimeBuildVerificationError, match="verification failed"):
        _verify_attested_build(
            wheel,
            manifest,
            verified_at=datetime(2026, 8, 4),
            attest=lambda _: None,
        )
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            '"package_name":"systematic-trading-lab",',
            '"package_name":"systematic-trading-lab","package_name":"duplicate",',
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeBuildVerificationError, match="verification failed"):
        _verify_attested_build(wheel, manifest, verified_at=NOW, attest=lambda _: None)


def test_github_attestation_uses_fixed_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = tmp_path / "artifact.whl"
    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    _verify_github_attestation(artifact)
    assert calls == [
        (
            [
                "gh",
                "attestation",
                "verify",
                str(artifact),
                "--repo",
                "firedvl/systematic-trading-lab",
                "--signer-workflow",
                "firedvl/systematic-trading-lab/.github/workflows/build-provenance.yml",
                "--deny-self-hosted-runners",
            ],
            {"check": True, "capture_output": True, "text": True, "timeout": 30},
        )
    ]
