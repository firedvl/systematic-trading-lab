from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

import pytest

from systematic_trading_lab.runtime_build import (
    RuntimeBuildIdentity,
    RuntimeBuildVerificationError,
    _verify_attested_build,
    _verify_github_attestation,
    _verify_installed_runtime,
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


def _record(contents: bytes) -> tuple[str, str]:
    digest = base64.urlsafe_b64encode(hashlib.sha256(contents).digest()).rstrip(b"=").decode()
    return f"sha256={digest}", str(len(contents))


def _installed_runtime(
    tmp_path: Path,
) -> tuple[RuntimeBuildIdentity, Path, Path, Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    wheel = tmp_path / "systematic_trading_lab-0.1.0-py3-none-any.whl"
    files = {
        "systematic_trading_lab/__init__.py": b'__version__ = "0.1.0"\n',
        "systematic_trading_lab/runtime_build.py": b"RUNTIME = True\n",
        "systematic_trading_lab-0.1.0.dist-info/METADATA": (
            b"Name: systematic-trading-lab\nVersion: 0.1.0\n"
        ),
        "systematic_trading_lab-0.1.0.dist-info/WHEEL": b"Wheel-Version: 1.0\n",
    }
    record_name = "systematic_trading_lab-0.1.0.dist-info/RECORD"
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    for name, contents in files.items():
        writer.writerow((name, *_record(contents)))
    writer.writerow((record_name, "", ""))
    files[record_name] = output.getvalue().encode()
    with ZipFile(wheel, "w") as archive:
        for name, contents in files.items():
            archive.writestr(name, contents)
    build = RuntimeBuildIdentity(
        source_commit="a" * 40,
        wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
        manifest_sha256="b" * 64,
        package_name="systematic-trading-lab",
        package_version="0.1.0",
        source_repository="firedvl/systematic-trading-lab",
        signer_workflow=".github/workflows/build-provenance.yml",
        verified_at=NOW,
    )
    root = tmp_path / "site-packages"
    for name, contents in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    dist_info = root / "systematic_trading_lab-0.1.0.dist-info"
    direct_url = dist_info / "direct_url.json"
    direct_url.write_text(
        json.dumps(
            {
                "archive_info": {
                    "hash": f"sha256={build.wheel_sha256}",
                    "hashes": {"sha256": build.wheel_sha256},
                },
                "url": wheel.as_uri(),
            }
        ),
        encoding="utf-8",
    )
    installed_rows = list(csv.reader(io.StringIO(files[record_name].decode())))
    installed_rows.append(["../../Scripts/trading-lab.exe", *_record(b"generated launcher")])
    installed_rows.append([f"{dist_info.name}/direct_url.json", *_record(direct_url.read_bytes())])
    installed_output = io.StringIO()
    csv.writer(installed_output, lineterminator="\n").writerows(installed_rows)
    installed_record = dist_info / "RECORD"
    installed_record.write_text(installed_output.getvalue(), encoding="utf-8")
    return build, wheel, root, root / "systematic_trading_lab/runtime_build.py", direct_url


def _update_direct_url_record(root: Path, direct_url: Path) -> None:
    record = root / "systematic_trading_lab-0.1.0.dist-info/RECORD"
    rows = list(csv.reader(io.StringIO(record.read_text(encoding="utf-8"))))
    rows[-1] = [rows[-1][0], *_record(direct_url.read_bytes())]
    output = io.StringIO()
    csv.writer(output, lineterminator="\n").writerows(rows)
    record.write_text(output.getvalue(), encoding="utf-8")


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
    monkeypatch.setenv("APCA_API_SECRET_KEY", "must-not-reach-gh")
    monkeypatch.setenv("TRADING_LAB_PAPER_ACTIVATION_ID", "must-not-reach-gh")
    monkeypatch.setenv("GH_TOKEN", "test-github-token")

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    _verify_github_attestation(artifact)
    subprocess_environment = calls[0][1].pop("env")
    assert isinstance(subprocess_environment, dict)
    assert subprocess_environment["GH_TOKEN"] == "test-github-token"
    assert "APCA_API_SECRET_KEY" not in subprocess_environment
    assert "TRADING_LAB_PAPER_ACTIVATION_ID" not in subprocess_environment
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


def test_installed_runtime_binds_loaded_sources_and_wheel_origin(tmp_path: Path) -> None:
    build, wheel, root, module_file, _ = _installed_runtime(tmp_path)
    identity = _verify_installed_runtime(
        build,
        wheel,
        root=root,
        module_file=module_file,
        verified_at=NOW,
    )
    assert identity.build_identity_fingerprint == build.identity_fingerprint
    assert identity.source_commit == build.source_commit
    assert identity.wheel_sha256 == build.wheel_sha256
    assert identity.distribution_record_sha256
    assert identity.source_files_fingerprint
    assert identity.identity_fingerprint

    direct_url = root / "systematic_trading_lab-0.1.0.dist-info/direct_url.json"
    value = json.loads(direct_url.read_text(encoding="utf-8"))
    del value["archive_info"]["hashes"]
    direct_url.write_text(json.dumps(value), encoding="utf-8")
    _update_direct_url_record(root, direct_url)
    assert _verify_installed_runtime(
        build,
        wheel,
        root=root,
        module_file=module_file,
        verified_at=NOW,
    ).identity_fingerprint


def test_installed_runtime_rejects_editable_or_wrong_archive_origin(tmp_path: Path) -> None:
    build, wheel, root, module_file, direct_url = _installed_runtime(tmp_path)
    direct_url.write_text(
        json.dumps({"dir_info": {"editable": True}, "url": tmp_path.as_uri()}),
        encoding="utf-8",
    )
    _update_direct_url_record(root, direct_url)
    with pytest.raises(RuntimeBuildVerificationError, match="verification failed"):
        _verify_installed_runtime(
            build,
            wheel,
            root=root,
            module_file=module_file,
            verified_at=NOW,
        )

    build, wheel, root, module_file, direct_url = _installed_runtime(tmp_path / "wrong-hash")
    value = json.loads(direct_url.read_text(encoding="utf-8"))
    value["archive_info"]["hashes"]["sha256"] = "c" * 64
    direct_url.write_text(json.dumps(value), encoding="utf-8")
    _update_direct_url_record(root, direct_url)
    with pytest.raises(RuntimeBuildVerificationError, match="verification failed"):
        _verify_installed_runtime(
            build,
            wheel,
            root=root,
            module_file=module_file,
            verified_at=NOW,
        )


def test_installed_runtime_rejects_source_tamper_and_extra_source(tmp_path: Path) -> None:
    build, wheel, root, module_file, _ = _installed_runtime(tmp_path)
    module_file.write_text("RUNTIME = False\n", encoding="utf-8")
    with pytest.raises(RuntimeBuildVerificationError, match="verification failed"):
        _verify_installed_runtime(
            build,
            wheel,
            root=root,
            module_file=module_file,
            verified_at=NOW,
        )

    build, wheel, root, module_file, _ = _installed_runtime(tmp_path / "extra")
    (module_file.parent / "injected.pyd").write_bytes(b"unreviewed extension")
    with pytest.raises(RuntimeBuildVerificationError, match="verification failed"):
        _verify_installed_runtime(
            build,
            wheel,
            root=root,
            module_file=module_file,
            verified_at=NOW,
        )

    build, wheel, root, module_file, _ = _installed_runtime(tmp_path / "empty-package-path")
    with pytest.raises(RuntimeBuildVerificationError, match="verification failed"):
        _verify_installed_runtime(
            build,
            wheel,
            root=root,
            module_file=module_file,
            package_paths=(),
            verified_at=NOW,
        )

    build, wheel, root, module_file, _ = _installed_runtime(tmp_path / "foreign-module")
    foreign = tmp_path / "foreign.py"
    foreign.write_text("FOREIGN = True\n", encoding="utf-8")
    with pytest.raises(RuntimeBuildVerificationError, match="verification failed"):
        _verify_installed_runtime(
            build,
            wheel,
            root=root,
            module_file=module_file,
            loaded_files=(module_file, foreign),
            verified_at=NOW,
        )
