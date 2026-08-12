from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import os
import pwd
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _migration_module() -> ModuleType:
    path = Path("scripts/migrate_paper_observation_state.py")
    spec = importlib.util.spec_from_file_location("paper_state_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _state(tmp_path: Path) -> tuple[ModuleType, Path, Path, Path, pwd.struct_passwd, int]:
    migration = _migration_module()
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".git").mkdir()
    home = repository / ".trading-lab"
    builds = home / "runtime-builds/build"
    builds.mkdir(parents=True)
    runtime = builds / "runtime"
    runtime.write_bytes(b"protected")
    environment_file = repository / ".env"
    environment_file.write_text("credentials", encoding="utf-8")
    database = home / "execution.sqlite3"
    database.write_bytes(b"sqlite bytes")
    (home / "execution.sqlite3-wal").write_bytes(b"wal bytes")
    account = pwd.struct_passwd(
        ("trading-lab-test", "x", 12345, 12345, "", "/var/lib/trading-lab-test", "/bin/false")
    )
    group_id = account.pw_gid
    if os.geteuid() == 0:
        for path in (repository, home, home / "runtime-builds", builds, runtime):
            os.chown(path, 0, 0, follow_symlinks=False)
    for path in (home / "runtime-builds", builds, runtime):
        path.chmod(0o755)
    return migration, repository, home, database, account, group_id


@pytest.mark.skipif(os.geteuid() != 0, reason="ownership migration requires root")
def test_migrate_state_is_exact_idempotent_and_preserves_bytes(tmp_path: Path) -> None:
    migration, repository, home, database, account, group_id = _state(tmp_path)
    sidecar = home / "execution.sqlite3-wal"
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (database, sidecar)}
    runtime = home / "runtime-builds/build/runtime"
    runtime_identity = (runtime.stat().st_uid, runtime.stat().st_gid, runtime.stat().st_mode)
    migration.__dict__["_observer_state"] = lambda _: None
    migration.__dict__["_open_by_other_process"] = lambda _: None

    migration.migrate_state(repository, home, account, "trading-lab-test", group_id)
    migration.migrate_state(repository, home, account, "trading-lab-test", group_id)

    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before} == before
    assert stat.S_IMODE(home.stat().st_mode) == 0o1770
    for path in (
        repository / ".env",
        database,
        sidecar,
        home / "paper-observation-screen.lock",
        home / "paper-observation.lock",
    ):
        assert (path.stat().st_uid, path.stat().st_gid, stat.S_IMODE(path.stat().st_mode)) == (
            12345,
            group_id,
            0o600,
        )
    assert (
        runtime.stat().st_uid,
        runtime.stat().st_gid,
        runtime.stat().st_mode,
    ) == runtime_identity


@pytest.mark.skipif(os.geteuid() != 0, reason="ownership migration requires root")
def test_migration_refuses_locked_observer_and_restores_home(tmp_path: Path) -> None:
    migration, repository, home, _, account, group_id = _state(tmp_path)
    lock = home / "paper-observation-screen.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    original = home.stat()
    migration.__dict__["_observer_state"] = lambda _: None
    migration.__dict__["_open_by_other_process"] = lambda _: None
    try:
        with pytest.raises(migration.StateMigrationError, match="holds the lock"):
            migration.migrate_state(repository, home, account, "trading-lab-test", group_id)
    finally:
        os.close(descriptor)
    current = home.stat()
    assert (current.st_uid, current.st_gid, stat.S_IMODE(current.st_mode)) == (
        original.st_uid,
        original.st_gid,
        stat.S_IMODE(original.st_mode),
    )


@pytest.mark.skipif(os.geteuid() != 0, reason="open-file detection requires root Linux /proc")
def test_migration_refuses_process_with_database_open(tmp_path: Path) -> None:
    migration, repository, home, database, account, group_id = _state(tmp_path)
    migration.__dict__["_observer_state"] = lambda _: None
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; handle = open(sys.argv[1], 'rb'); print('ready', flush=True); input()",
            str(database),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None and process.stdout.readline().strip() == "ready"
    try:
        with pytest.raises(migration.StateMigrationError, match="open by PID"):
            migration.migrate_state(repository, home, account, "trading-lab-test", group_id)
    finally:
        process.communicate("\n", timeout=5)


@pytest.mark.skipif(os.geteuid() != 0, reason="runtime ownership check requires root")
def test_state_check_requires_service_access_to_protected_runtime(tmp_path: Path) -> None:
    migration, repository, home, _, account, group_id = _state(tmp_path)
    runtime = home / "runtime-builds/build/runtime"
    runtime.chmod(0o700)
    with pytest.raises(migration.StateMigrationError, match="service-readable/executable"):
        migration._check_protected_runtime(home, group_id)


def test_state_check_reports_wrong_mutable_ownership_before_install(tmp_path: Path) -> None:
    migration, repository, home, _, account, group_id = _state(tmp_path)
    with pytest.raises(migration.StateMigrationError, match="run migrate-state"):
        migration.check_state(repository, home, account.pw_uid, group_id)


def test_migration_script_parses() -> None:
    subprocess.run(
        ["python3", "-m", "py_compile", "scripts/migrate_paper_observation_state.py"], check=True
    )
