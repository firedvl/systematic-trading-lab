from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

import systematic_trading_lab.cli as cli
import systematic_trading_lab.paper_supervision as supervision
from systematic_trading_lab.config import ConfigurationError, load_settings
from systematic_trading_lab.paper_observation import PaperObservation, PaperObservationStatus
from systematic_trading_lab.runtime_build import (
    InstalledRuntimeIdentity,
    RuntimeBuildAttestationIndeterminateError,
    RuntimeBuildIdentity,
)

NOW = datetime(2026, 8, 12, tzinfo=UTC)
COMMIT = "a" * 40


def _supervision_files(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path, dict[str, str]]:
    repository = tmp_path / "systematic-trading-lab"
    repository.mkdir(parents=True)
    (repository / "pyproject.toml").write_text(
        '[project]\nname = "systematic-trading-lab"\n', encoding="utf-8"
    )
    risk_config = repository / "config/risk/alpaca-paper-v1.json"
    risk_config.parent.mkdir(parents=True)
    risk_config.write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "add", "pyproject.toml", str(risk_config)], check=True
    )
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-qm", "test repository"],
        check=True,
        env={
            "PATH": os.environ["PATH"],
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )
    commit = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    home = repository / ".trading-lab"
    build = home / "runtime-builds" / commit
    runtime = build / "verified-venv/bin/trading-lab"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("#!/bin/sh\n", encoding="utf-8")
    runtime.chmod(0o700)
    wheel = build / "systematic_trading_lab-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    manifest = build / "runtime-build-manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    home.chmod(0o700)
    environment = {
        "TRADING_LAB_MODE": "paper",
        "TRADING_LAB_HOME": str(home),
        "APCA_API_KEY_ID": "test-key",
        "APCA_API_SECRET_KEY": "test-secret",
        "TRADING_LAB_PAPER_ACTIVATION_ID": "",
        "TRADING_LAB_PAPER_CODE_COMMIT": "",
    }
    environment_file = repository / ".env"
    environment_file.write_text(
        "TRADING_LAB_MODE=paper\n"
        f"TRADING_LAB_HOME={home}\n"
        "APCA_API_KEY_ID=test-key\n"
        "APCA_API_SECRET_KEY=test-secret\n",
        encoding="utf-8",
    )
    environment_file.chmod(0o600)
    return repository, home, runtime, wheel, manifest, environment


def _validate(
    repository: Path,
    home: Path,
    runtime: Path,
    wheel: Path,
    manifest: Path,
    environment: dict[str, str],
    *,
    campaign_id: str = "paper-reboot-drill",
    interval_seconds: int = 600,
    loaded_runtime: Path | None = None,
    runtime_prefix: Path | None = None,
) -> str:
    return supervision.validate_observation_supervision(
        load_settings(environment),
        campaign_id=campaign_id,
        interval_seconds=interval_seconds,
        repository=repository,
        runtime=runtime,
        wheel=wheel,
        manifest=manifest,
        risk_config=repository / "config/risk/alpaca-paper-v1.json",
        environment=environment,
        loaded_runtime=loaded_runtime or runtime,
        runtime_prefix=runtime_prefix or runtime.parent.parent,
    )


def _status(*, complete: bool) -> PaperObservationStatus:
    return PaperObservationStatus(
        campaign_id="paper-reboot-drill",
        healthy_now=True,
        campaign_complete=complete,
        continuity_held=True,
        campaign_passed=True if complete else None,
        reasons=(),
        campaign_reasons=(),
        success_count=2,
        drift_count=0,
        failure_count=0,
        maximum_gap_seconds=900,
        maximum_observed_gap_seconds=600,
        latest_observed_at=NOW,
        assessed_at=NOW,
    )


def _replace_head_with_modified_risk(repository: Path, risk_config: Path) -> None:
    original = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    risk_config.write_text('{"changed":true}\n', encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", str(risk_config)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-qm", "replacement risk"],
        check=True,
        env={
            "PATH": os.environ["PATH"],
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )
    replacement = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "-C", str(repository), "reset", "-q", original], check=True)
    subprocess.run(["git", "-C", str(repository), "replace", original, replacement], check=True)


def test_supervision_accepts_only_fixed_private_read_only_configuration(tmp_path: Path) -> None:
    repository, home, runtime, wheel, manifest, environment = _supervision_files(tmp_path)
    assert (
        _validate(repository, home, runtime, wheel, manifest, environment)
        == runtime.parent.parent.parent.name
    )

    with pytest.raises(ConfigurationError, match="campaign ID"):
        _validate(
            repository,
            home,
            runtime,
            wheel,
            manifest,
            environment,
            campaign_id="bad campaign",
        )
    with pytest.raises(ConfigurationError, match="interval"):
        _validate(repository, home, runtime, wheel, manifest, environment, interval_seconds=59)

    outside = repository / "unverified/trading-lab"
    outside.parent.mkdir()
    outside.write_text("#!/bin/sh\n", encoding="utf-8")
    outside.chmod(0o700)
    with pytest.raises(ConfigurationError, match="project-local verified build"):
        _validate(
            repository,
            home,
            outside,
            wheel,
            manifest,
            environment,
            loaded_runtime=outside,
            runtime_prefix=outside.parent,
        )

    (repository / ".env").chmod(0o640)
    with pytest.raises(ConfigurationError, match="mode 0600"):
        _validate(repository, home, runtime, wheel, manifest, environment)


def test_supervision_rejects_missing_or_write_enabled_environment(tmp_path: Path) -> None:
    repository, home, runtime, wheel, manifest, environment = _supervision_files(tmp_path)
    (repository / ".env").unlink()
    with pytest.raises(ConfigurationError, match="environment file is missing"):
        _validate(repository, home, runtime, wheel, manifest, environment)


def test_supervision_rejects_stale_or_modified_risk_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, home, runtime, wheel, manifest, environment = _supervision_files(tmp_path)
    risk_config = repository / "config/risk/alpaca-paper-v1.json"
    alternate_worktree = tmp_path / "clean-worktree"
    subprocess.run(
        ["git", "-C", str(repository), "worktree", "add", "--detach", str(alternate_worktree)],
        check=True,
        capture_output=True,
    )
    risk_config.write_text('{"changed":true}\n', encoding="utf-8")
    monkeypatch.setenv("GIT_WORK_TREE", str(alternate_worktree))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "untrusted-git-config"))
    with pytest.raises(ConfigurationError, match="risk configuration is not clean"):
        _validate(repository, home, runtime, wheel, manifest, environment)
    monkeypatch.delenv("GIT_WORK_TREE")
    monkeypatch.delenv("GIT_CONFIG_GLOBAL")

    _replace_head_with_modified_risk(repository, risk_config)
    subprocess.run(
        ["git", "-C", str(repository), "config", "core.worktree", str(alternate_worktree)],
        check=True,
    )
    fsmonitor_marker = tmp_path / "fsmonitor-ran"
    subprocess.run(
        ["git", "-C", str(repository), "config", "core.fsmonitor", f"touch {fsmonitor_marker}"],
        check=True,
    )
    with pytest.raises(ConfigurationError, match="risk configuration is not clean"):
        _validate(repository, home, runtime, wheel, manifest, environment)
    assert not fsmonitor_marker.exists()
    subprocess.run(["git", "-C", str(repository), "replace", "-d", "HEAD"], check=True)
    subprocess.run(
        ["git", "--git-dir", str(repository / ".git"), "config", "--unset", "core.worktree"],
        check=True,
    )

    risk_config.write_text("{}\n", encoding="utf-8")
    (repository / "pyproject.toml").write_text(
        '[project]\nname = "systematic-trading-lab"\n# changed\n', encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(repository), "add", "pyproject.toml"], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-qm", "later commit"],
        check=True,
        env={
            "PATH": os.environ["PATH"],
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )
    with pytest.raises(ConfigurationError, match="repository commit differs"):
        _validate(repository, home, runtime, wheel, manifest, environment)

    repository, home, runtime, wheel, manifest, environment = _supervision_files(
        tmp_path / "write-enabled"
    )
    environment["TRADING_LAB_PAPER_ACTIVATION_ID"] = "b" * 64
    environment["TRADING_LAB_PAPER_CODE_COMMIT"] = "b" * 40
    with pytest.raises(ConfigurationError, match="forbids broker-write opt-in"):
        _validate(repository, home, runtime, wheel, manifest, environment)


def test_runtime_verification_binds_attestation_install_and_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel = tmp_path / "runtime.whl"
    manifest = tmp_path / "runtime-build-manifest.json"
    build = RuntimeBuildIdentity(
        source_commit=COMMIT,
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
        source_commit=COMMIT,
        wheel_sha256=build.wheel_sha256,
        distribution_record_sha256="d" * 64,
        source_files_fingerprint="e" * 64,
        verified_at=NOW,
    )
    calls: list[str] = []

    def verify_attested(*args: object, **kwargs: object) -> RuntimeBuildIdentity:
        calls.append("attested")
        return build

    def verify_installed(*args: object, **kwargs: object) -> InstalledRuntimeIdentity:
        calls.append("installed")
        return installed

    monkeypatch.setattr(supervision, "verify_attested_build", verify_attested)
    monkeypatch.setattr(supervision, "verify_installed_runtime", verify_installed)

    assert (
        supervision.verify_observation_runtime(wheel, manifest, expected_commit=COMMIT) == installed
    )
    assert calls == ["attested", "installed"]
    with pytest.raises(ConfigurationError, match="commit differs"):
        supervision.verify_observation_runtime(wheel, manifest, expected_commit="f" * 40)


def test_indeterminate_attestation_stops_before_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arguments = cli.parser().parse_args(
        [
            "paper",
            "supervise-observation",
            "paper-reboot-drill",
            "--runtime",
            str(tmp_path / "runtime"),
            "--wheel",
            str(tmp_path / "runtime.whl"),
            "--manifest",
            str(tmp_path / "runtime-build-manifest.json"),
            "--repository",
            str(tmp_path),
        ]
    )
    settings = load_settings(
        {"TRADING_LAB_MODE": "paper", "TRADING_LAB_HOME": str(tmp_path / "state")}
    )
    monkeypatch.setattr(cli, "validate_observation_supervision", lambda *args, **kwargs: COMMIT)

    def indeterminate(*args: object, **kwargs: object) -> None:
        raise RuntimeBuildAttestationIndeterminateError("indeterminate")

    monkeypatch.setattr(cli, "verify_observation_runtime", indeterminate)
    monkeypatch.setattr(
        cli,
        "_paper_observation_reader",
        lambda *args, **kwargs: pytest.fail("observation must not start"),
    )
    with pytest.raises(RuntimeBuildAttestationIndeterminateError):
        cli.run(arguments, settings)


def test_supervisor_lock_blocks_a_second_local_writer(tmp_path: Path) -> None:
    import fcntl

    home = tmp_path / "fresh-home"
    with supervision.observation_supervisor_lock(home) as lock:
        assert lock == home / "paper-observation.lock"
        assert home.stat().st_mode & 0o777 == 0o700

    legacy_lock = os.open(home / "paper-observation-screen.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(legacy_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with (
            pytest.raises(ConfigurationError, match="another paper observation supervisor"),
            supervision.observation_supervisor_lock(home),
        ):
            pytest.fail("legacy Screen lock must block the supervisor")
    finally:
        os.close(legacy_lock)

    with supervision.observation_supervisor_lock(home) as lock:
        assert lock == home / "paper-observation.lock"
        assert lock.stat().st_mode & 0o777 == 0o600
        with (
            pytest.raises(ConfigurationError, match="another paper observation supervisor"),
            supervision.observation_supervisor_lock(home),
        ):
            pytest.fail("second lock must not be acquired")


def test_observation_loop_stops_cleanly_when_campaign_is_already_complete() -> None:
    emitted: list[tuple[PaperObservation | None, PaperObservationStatus]] = []
    status = supervision.run_observation_loop(
        interval_seconds=600,
        assess=lambda: _status(complete=True),
        record=lambda: pytest.fail("completed campaign must not record another sample"),
        emit=lambda observation, result: emitted.append((observation, result)),
        monotonic=lambda: 0,
        sleep=lambda _: pytest.fail("completed campaign must not sleep"),
    )
    assert status.campaign_passed is True
    assert emitted == [(None, status)]


def test_observation_loop_preserves_interval_until_completion() -> None:
    incomplete = _status(complete=False)
    complete = _status(complete=True)
    observation = PaperObservation(
        observation_id="a" * 64,
        campaign_id=incomplete.campaign_id,
        snapshot_id="snapshot",
        snapshot_fingerprint="b" * 64,
        status="healthy",
        reasons=(),
        observed_at=NOW,
    )
    assessments = iter((incomplete, complete))
    monotonic = iter((0.0, 10.0, 600.0))
    sleeps: list[float] = []
    emitted: list[tuple[PaperObservation | None, PaperObservationStatus]] = []

    assert (
        supervision.run_observation_loop(
            interval_seconds=600,
            assess=lambda: next(assessments),
            record=lambda: (observation, incomplete),
            emit=lambda item, result: emitted.append((item, result)),
            monotonic=lambda: next(monotonic),
            sleep=sleeps.append,
        )
        == complete
    )
    assert sleeps == [590.0]
    assert emitted == [(observation, incomplete), (None, complete)]


def test_observation_loop_does_not_sleep_after_final_sample() -> None:
    incomplete = _status(complete=False)
    complete = _status(complete=True)
    observation = PaperObservation(
        observation_id="a" * 64,
        campaign_id=incomplete.campaign_id,
        snapshot_id="snapshot",
        snapshot_fingerprint="b" * 64,
        status="healthy",
        reasons=(),
        observed_at=NOW,
    )
    assert (
        supervision.run_observation_loop(
            interval_seconds=600,
            assess=lambda: incomplete,
            record=lambda: (observation, complete),
            emit=lambda *_: None,
            monotonic=lambda: 0,
            sleep=lambda _: pytest.fail("final sample must stop without another delay"),
        )
        == complete
    )


def test_generated_systemd_unit_is_boot_enabled_fixed_and_secret_free(tmp_path: Path) -> None:
    repository, home, runtime, wheel, manifest, _ = _supervision_files(tmp_path)
    service_user = subprocess.run(
        ["id", "-un"], check=True, capture_output=True, text=True
    ).stdout.strip()
    service_group = subprocess.run(
        ["id", "-gn"], check=True, capture_output=True, text=True
    ).stdout.strip()
    scripts = repository / "scripts"
    scripts.mkdir()
    source = Path("scripts/paper_observation_systemd.sh")
    helper = scripts / source.name
    shutil.copyfile(source, helper)
    helper.chmod(0o700)
    result = subprocess.run(
        [
            "bash",
            str(helper),
            "render",
            "paper-reboot-drill",
            str(runtime),
            str(wheel),
            str(manifest),
            str(home),
            service_user,
            service_group,
            "600",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    unit = result.stdout
    assert f"ExecStart={runtime} paper supervise-observation paper-reboot-drill" in unit
    assert f"--wheel {wheel} --manifest {manifest}" in unit
    assert f"Environment=TRADING_LAB_HOME={home}" in unit
    assert "--interval-seconds 600" in unit
    assert "WantedBy=multi-user.target" in unit
    assert "Restart=on-failure" in unit
    assert "RestartPreventExitStatus=2" in unit
    assert "RestartSec=60" in unit
    assert "StartLimitIntervalSec=900" in unit
    assert "StartLimitBurst=5" in unit
    assert "Environment=HOME=/var/lib/systematic-trading-lab" in unit
    assert "Environment=GH_CONFIG_DIR=/var/lib/systematic-trading-lab/.config/gh" in unit
    assert "Environment=GH_HOST=github.com" in unit
    assert "Environment=GH_PROMPT_DISABLED=1" in unit
    for token_name in (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GH_ENTERPRISE_TOKEN",
        "GITHUB_ENTERPRISE_TOKEN",
    ):
        assert f"Environment={token_name}=" in unit
    assert "ReadOnlyPaths=" in unit and "/var/lib/systematic-trading-lab/.config/gh" in unit
    assert "ReadWritePaths=" in unit and "/var/lib/systematic-trading-lab/.cache/gh" in unit
    assert "APCA_API_KEY_ID" not in unit
    assert "APCA_API_SECRET_KEY" not in unit
    if systemd_analyze := shutil.which("systemd-analyze"):
        unit_path = tmp_path / "systematic-trading-lab-paper-observation.service"
        unit_path.write_text(unit, encoding="utf-8")
        subprocess.run([systemd_analyze, "verify", str(unit_path)], check=True)

    invalid = subprocess.run(
        [
            "bash",
            str(helper),
            "render",
            "bad campaign",
            str(runtime),
            str(wheel),
            str(manifest),
            str(home),
            service_user,
            service_group,
        ],
        capture_output=True,
        text=True,
    )
    assert invalid.returncode == 2

    alternate_worktree = tmp_path / "redirected-worktree"
    alternate_risk_config = alternate_worktree / "config/risk/alpaca-paper-v1.json"
    alternate_risk_config.parent.mkdir(parents=True)
    shutil.copyfile(repository / "config/risk/alpaca-paper-v1.json", alternate_risk_config)
    _replace_head_with_modified_risk(repository, repository / "config/risk/alpaca-paper-v1.json")
    subprocess.run(
        ["git", "-C", str(repository), "config", "core.worktree", str(alternate_worktree)],
        check=True,
    )
    fsmonitor_marker = tmp_path / "shell-fsmonitor-ran"
    subprocess.run(
        ["git", "-C", str(repository), "config", "core.fsmonitor", f"touch {fsmonitor_marker}"],
        check=True,
    )
    (repository / "config/risk/alpaca-paper-v1.json").write_text(
        '{"changed":true}\n', encoding="utf-8"
    )
    redirected = subprocess.run(
        [
            "bash",
            str(helper),
            "render",
            "paper-reboot-drill",
            str(runtime),
            str(wheel),
            str(manifest),
            str(home),
            service_user,
            service_group,
            "600",
        ],
        capture_output=True,
        text=True,
    )
    assert redirected.returncode == 2
    assert "risk configuration differs from the runtime commit" in redirected.stderr
    assert not fsmonitor_marker.exists()


def test_supervision_shell_scripts_parse() -> None:
    subprocess.run(
        [
            "bash",
            "-n",
            "scripts/paper_observation_screen.sh",
            "scripts/paper_observation_systemd.sh",
            "scripts/cleanup_vps.sh",
        ],
        check=True,
    )
