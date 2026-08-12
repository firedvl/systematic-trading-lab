"""Restart-safe supervision for broker-read-only paper observation."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .config import ConfigurationError, Settings, load_dotenv, non_broker_subprocess_environment
from .domain import TradingMode
from .paper_observation import PaperObservation, PaperObservationStatus
from .runtime_build import (
    InstalledRuntimeIdentity,
    verify_attested_build,
    verify_installed_runtime,
)

_CAMPAIGN_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_DOTENV_KEYS = {
    "TRADING_LAB_MODE",
    "TRADING_LAB_HOME",
    "APCA_API_KEY_ID",
    "APCA_API_SECRET_KEY",
}


def validate_observation_supervision(
    settings: Settings,
    *,
    campaign_id: str,
    interval_seconds: int,
    repository: Path,
    runtime: Path,
    wheel: Path,
    manifest: Path,
    risk_config: Path,
    environment: Mapping[str, str] | None = None,
    loaded_runtime: Path | None = None,
    runtime_prefix: Path | None = None,
) -> str:
    """Validate fixed service inputs without reading broker or campaign state."""
    if not _CAMPAIGN_ID.fullmatch(campaign_id):
        raise ConfigurationError("paper observation campaign ID is invalid")
    if isinstance(interval_seconds, bool) or not 60 <= interval_seconds <= 900:
        raise ConfigurationError("paper observation interval must be between 60 and 900 seconds")

    repository = _regular_directory(repository, "repository")
    if not (repository / ".git").is_dir():
        raise ConfigurationError("paper observation repository is not a Git checkout")
    try:
        project = (repository / "pyproject.toml").read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigurationError("paper observation project marker is missing") from error
    if 'name = "systematic-trading-lab"' not in project:
        raise ConfigurationError("paper observation project marker is invalid")

    runtime = _regular_file(runtime, "runtime", executable=True)
    wheel = _regular_file(wheel, "wheel")
    manifest = _regular_file(manifest, "manifest")
    risk_config = _regular_file(risk_config, "risk configuration")
    build = runtime.parent.parent.parent
    build_commit = build.name
    if (
        runtime.name != "trading-lab"
        or runtime.parent.name != "bin"
        or runtime.parent.parent.name != "verified-venv"
        or not _COMMIT.fullmatch(build_commit)
        or build.parent != repository / ".trading-lab" / "runtime-builds"
        or wheel.parent != build
        or wheel.suffix != ".whl"
        or manifest != build / "runtime-build-manifest.json"
    ):
        raise ConfigurationError("runtime must be an exact project-local verified build")
    if risk_config != repository / "config" / "risk" / "alpaca-paper-v1.json":
        raise ConfigurationError("paper observation risk configuration path is invalid")
    _verify_repository_binding(repository, risk_config, build_commit)

    loaded_runtime = _regular_file(
        loaded_runtime or Path(sys.argv[0]), "loaded runtime", executable=True
    )
    runtime_prefix = _regular_directory(runtime_prefix or Path(sys.prefix), "runtime prefix")
    if loaded_runtime != runtime or runtime_prefix != runtime.parent.parent:
        raise ConfigurationError("loaded runtime differs from the configured verified build")

    values = os.environ if environment is None else environment
    raw_home = Path(values.get("TRADING_LAB_HOME", "").strip())
    if not raw_home.is_absolute() or raw_home.is_symlink():
        raise ConfigurationError("paper observation TRADING_LAB_HOME must be an absolute directory")
    home = _private_directory(settings.home, "TRADING_LAB_HOME")
    if home != repository / ".trading-lab":
        raise ConfigurationError("paper observation TRADING_LAB_HOME must be project-local")
    if settings.mode is not TradingMode.PAPER:
        raise ConfigurationError("paper observation supervision requires paper mode")
    if settings.paper_write_request is not None:
        raise ConfigurationError("paper observation supervision forbids broker-write opt-in")

    environment_file = repository / ".env"
    _private_file(environment_file, "paper observation environment file")
    dotenv: dict[str, str] = {}
    load_dotenv(environment_file, dotenv)
    if set(dotenv) != _DOTENV_KEYS:
        raise ConfigurationError("paper observation environment file has an invalid key set")
    if dotenv["TRADING_LAB_MODE"].strip() != TradingMode.PAPER.value:
        raise ConfigurationError("paper observation environment file must select paper mode")
    dotenv_home = Path(dotenv["TRADING_LAB_HOME"].strip())
    if not dotenv_home.is_absolute() or dotenv_home.resolve() != home:
        raise ConfigurationError("paper observation environment file has the wrong home")
    if not dotenv["APCA_API_KEY_ID"] or not dotenv["APCA_API_SECRET_KEY"]:
        raise ConfigurationError("paper observation environment file lacks credentials")

    for name in _DOTENV_KEYS:
        if values.get(name) != dotenv[name]:
            raise ConfigurationError("paper observation process differs from its environment file")
    if (
        values.get("TRADING_LAB_PAPER_ACTIVATION_ID", "").strip()
        or values.get("TRADING_LAB_PAPER_CODE_COMMIT", "").strip()
    ):
        raise ConfigurationError("paper observation supervision forbids broker-write environment")
    return build_commit


def verify_observation_runtime(
    wheel: Path, manifest: Path, *, expected_commit: str
) -> InstalledRuntimeIdentity:
    """Verify the attested artifacts and the exact loaded distribution."""
    verified_at = datetime.now(UTC)
    build = verify_attested_build(wheel, manifest, verified_at=verified_at)
    if build.source_commit != expected_commit:
        raise ConfigurationError("verified runtime commit differs from its build directory")
    return verify_installed_runtime(build, wheel, verified_at=datetime.now(UTC))


@contextmanager
def observation_supervisor_lock(home: Path) -> Iterator[Path]:
    """Hold the one supervisor lock beside the execution store."""
    try:
        import fcntl
    except ImportError as error:
        raise ConfigurationError(
            "paper observation supervision requires POSIX file locking"
        ) from error
    try:
        home.mkdir(parents=True, mode=0o700, exist_ok=True)
    except OSError as error:
        raise ConfigurationError("cannot create paper observation home") from error
    paths = (home / "paper-observation-screen.lock", home / "paper-observation.lock")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptors: list[int] = []
    try:
        for path in paths:
            try:
                descriptor = os.open(path, flags, 0o600)
            except OSError as error:
                raise ConfigurationError("cannot open paper observation supervisor lock") from error
            descriptors.append(descriptor)
            details = os.fstat(descriptor)
            if (
                not stat.S_ISREG(details.st_mode)
                or details.st_uid != os.geteuid()
                or stat.S_IMODE(details.st_mode) != 0o600
            ):
                raise ConfigurationError("paper observation supervisor lock is unsafe")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ConfigurationError(
                    "another paper observation supervisor holds the lock"
                ) from error
        yield paths[-1]
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def run_observation_loop(
    *,
    interval_seconds: int,
    assess: Callable[[], PaperObservationStatus],
    record: Callable[[], tuple[PaperObservation, PaperObservationStatus]],
    emit: Callable[[PaperObservation | None, PaperObservationStatus], None],
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> PaperObservationStatus:
    """Assess before each sample and stop after either final campaign result."""
    while True:
        cycle_started = monotonic()
        status = assess()
        if status.campaign_complete:
            emit(None, status)
            return status
        observation, status = record()
        emit(observation, status)
        if status.campaign_complete:
            return status
        delay = cycle_started + interval_seconds - monotonic()
        if delay > 0:
            sleep(delay)


def _regular_directory(path: Path, name: str) -> Path:
    try:
        if path.is_symlink():
            raise ConfigurationError(f"paper observation {name} cannot be a symbolic link")
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ConfigurationError(f"paper observation {name} is missing") from error
    if not resolved.is_dir():
        raise ConfigurationError(f"paper observation {name} is not a directory")
    return resolved


def _regular_file(path: Path, name: str, *, executable: bool = False) -> Path:
    try:
        if path.is_symlink():
            raise ConfigurationError(f"paper observation {name} cannot be a symbolic link")
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ConfigurationError(f"paper observation {name} is missing") from error
    if not resolved.is_file() or (executable and not os.access(resolved, os.X_OK)):
        raise ConfigurationError(f"paper observation {name} is invalid")
    return resolved


def _private_directory(path: Path, name: str) -> Path:
    resolved = _regular_directory(path, name)
    details = resolved.stat()
    mode = stat.S_IMODE(details.st_mode)
    service_owned = details.st_uid == os.geteuid() and mode == 0o700
    root_shared = details.st_uid == 0 and details.st_gid == os.getegid() and mode == 0o1770
    if not service_owned and not root_shared:
        raise ConfigurationError(f"paper observation {name} must be owned privately")
    return resolved


def _private_file(path: Path, name: str) -> Path:
    resolved = _regular_file(path, name)
    details = resolved.stat()
    if details.st_uid != os.geteuid() or stat.S_IMODE(details.st_mode) != 0o600:
        raise ConfigurationError(f"{name} must be owned by the service user with mode 0600")
    return resolved


def _verify_repository_binding(repository: Path, risk_config: Path, build_commit: str) -> None:
    git_command = [
        "git",
        "--no-replace-objects",
        "--git-dir",
        str(repository / ".git"),
    ]
    environment = non_broker_subprocess_environment()
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": "/nonexistent",
            "XDG_CONFIG_HOME": "/nonexistent",
        }
    )
    try:
        head = subprocess.run(
            [*git_command, "rev-parse", "--verify", "HEAD"],
            check=True,
            capture_output=True,
            env=environment,
            text=True,
            timeout=10,
        )
        if head.stdout.strip() != build_commit:
            raise ConfigurationError("repository commit differs from the verified runtime")
        committed_risk = subprocess.run(
            [
                *git_command,
                "cat-file",
                "blob",
                f"{build_commit}:{risk_config.relative_to(repository)}",
            ],
            check=True,
            capture_output=True,
            env=environment,
            timeout=10,
        )
        if committed_risk.stdout != risk_config.read_bytes():
            raise ConfigurationError("risk configuration is not clean at the runtime commit")
    except (OSError, subprocess.SubprocessError) as error:
        raise ConfigurationError("risk configuration is not clean at the runtime commit") from error
