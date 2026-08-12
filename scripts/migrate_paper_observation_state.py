#!/usr/bin/env python3
"""Check or migrate the exact mutable paper-observation deployment files."""

from __future__ import annotations

import argparse
import fcntl
import grp
import hashlib
import os
import pwd
import shutil
import stat
import subprocess
import sys
from pathlib import Path

UNIT_NAME = "systematic-trading-lab-paper-observation.service"
SCREEN_NAME = "systematic-trading-lab-observation"
LOCK_NAMES = ("paper-observation-screen.lock", "paper-observation.lock")
DATABASE_NAMES = (
    "execution.sqlite3",
    "execution.sqlite3-wal",
    "execution.sqlite3-shm",
    "execution.sqlite3-journal",
)


class StateMigrationError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("check", "migrate"))
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--service-user", required=True)
    parser.add_argument("--service-group", required=True)
    return parser


def _service_ids(user: str, group: str) -> tuple[pwd.struct_passwd, int]:
    try:
        account = pwd.getpwnam(user)
        group_id = grp.getgrnam(group).gr_gid
    except KeyError as error:
        raise StateMigrationError("service user or group does not exist") from error
    if account.pw_gid != group_id:
        raise StateMigrationError("service group is not the service user's primary group")
    return account, group_id


def _scope(repository: Path, home: Path) -> tuple[Path, Path]:
    if not repository.is_absolute() or not home.is_absolute():
        raise StateMigrationError("repository and TRADING_LAB_HOME must be absolute")
    if repository.is_symlink() or home.is_symlink():
        raise StateMigrationError("repository and TRADING_LAB_HOME cannot be symbolic links")
    try:
        repository = repository.resolve(strict=True)
        home = home.resolve(strict=True)
    except OSError as error:
        raise StateMigrationError("repository or TRADING_LAB_HOME is missing") from error
    if not repository.is_dir() or not (repository / ".git").is_dir():
        raise StateMigrationError("repository is not a Git checkout")
    repository_details = repository.stat()
    if repository_details.st_uid != 0 or stat.S_IMODE(repository_details.st_mode) & 0o022:
        raise StateMigrationError("repository must be root-owned and not group/world writable")
    if not home.is_dir() or home != repository / ".trading-lab":
        raise StateMigrationError("TRADING_LAB_HOME must be the project-local .trading-lab")
    return repository, home


def _regular_file(path: Path, *, required: bool) -> os.stat_result | None:
    try:
        details = path.lstat()
    except FileNotFoundError:
        if required:
            raise StateMigrationError(f"required mutable file is missing: {path}") from None
        return None
    except OSError as error:
        raise StateMigrationError(f"cannot inspect mutable file: {path}") from error
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        raise StateMigrationError(f"mutable file must be regular and singly linked: {path}")
    return details


def _service_permissions(details: os.stat_result, group_id: int) -> int:
    return (stat.S_IMODE(details.st_mode) >> (3 if details.st_gid == group_id else 0)) & 0o7


def _check_service_access(path: Path, details: os.stat_result, group_id: int) -> None:
    permissions = _service_permissions(details, group_id)
    if stat.S_ISDIR(details.st_mode) and permissions & 0o5 != 0o5:
        raise StateMigrationError(
            f"protected runtime directory is not service-readable/traversable: {path}"
        )
    if stat.S_ISREG(details.st_mode) and (
        not permissions & 0o4 or stat.S_IMODE(details.st_mode) & 0o100 and not permissions & 0o1
    ):
        raise StateMigrationError(
            f"protected runtime file is not service-readable/executable: {path}"
        )


def _check_protected_runtime(home: Path, group_id: int) -> None:
    builds = home / "runtime-builds"
    try:
        root_details = builds.lstat()
    except OSError as error:
        raise StateMigrationError("protected runtime-builds directory is missing") from error
    if not stat.S_ISDIR(root_details.st_mode) or builds.is_symlink():
        raise StateMigrationError("protected runtime-builds path is unsafe")
    for directory, names, files in os.walk(builds, followlinks=False):
        for path in (Path(directory), *(Path(directory, name) for name in (*names, *files))):
            try:
                details = path.lstat()
            except OSError as error:
                raise StateMigrationError(
                    f"cannot inspect protected runtime path: {path}"
                ) from error
            if stat.S_ISLNK(details.st_mode):
                try:
                    target_details = path.resolve(strict=True).stat()
                except OSError as error:
                    raise StateMigrationError(
                        f"protected runtime link target is missing: {path}"
                    ) from error
                if target_details.st_uid != 0 or stat.S_IMODE(target_details.st_mode) & 0o022:
                    raise StateMigrationError(
                        f"protected runtime link target is writable or not root-owned: {path}"
                    )
                _check_service_access(path, target_details, group_id)
                continue
            if details.st_uid != 0:
                raise StateMigrationError(f"protected runtime path must remain root-owned: {path}")
            if stat.S_IMODE(details.st_mode) & 0o022:
                raise StateMigrationError(
                    f"protected runtime path cannot be group/world writable: {path}"
                )
            _check_service_access(path, details, group_id)


def _check_mutable_file(path: Path, user_id: int, group_id: int, *, required: bool) -> None:
    details = _regular_file(path, required=required)
    if details is None:
        return
    if (
        details.st_uid != user_id
        or details.st_gid != group_id
        or stat.S_IMODE(details.st_mode) != 0o600
    ):
        raise StateMigrationError(
            f"mutable file must be service-owned with mode 0600; run migrate-state: {path}"
        )


def check_state(repository: Path, home: Path, user_id: int, group_id: int) -> None:
    details = home.stat()
    if details.st_uid != 0 or details.st_gid != group_id or stat.S_IMODE(details.st_mode) != 0o1770:
        raise StateMigrationError(
            "TRADING_LAB_HOME must be root:service-group mode 1770; run migrate-state"
        )
    _check_mutable_file(repository / ".env", user_id, group_id, required=True)
    for name in DATABASE_NAMES:
        _check_mutable_file(home / name, user_id, group_id, required=name == DATABASE_NAMES[0])
    for name in LOCK_NAMES:
        _check_mutable_file(home / name, user_id, group_id, required=True)
    _check_protected_runtime(home, group_id)


def _observer_state(account: pwd.struct_passwd) -> str | None:
    systemctl = shutil.which("systemctl")
    if systemctl is None:
        raise StateMigrationError("systemctl is required")
    result = subprocess.run(
        [systemctl, "is-active", UNIT_NAME],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.stdout.strip() in {"active", "activating", "reloading", "deactivating"}:
        return f"systemd unit is {result.stdout.strip()}"
    screen = shutil.which("screen")
    if screen is None:
        return None
    commands = ([screen, "-list"],)
    runuser = shutil.which("runuser")
    if account.pw_uid != 0:
        if runuser is None:
            raise StateMigrationError("runuser is required to check service-user Screen sessions")
        commands += (
            [
                runuser,
                "-u",
                account.pw_name,
                "--",
                "env",
                "-i",
                f"HOME={account.pw_dir}",
                "PATH=/usr/local/bin:/usr/bin:/bin",
                screen,
                "-list",
            ],
        )
    for command in commands:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if f".{SCREEN_NAME}" in result.stdout:
            return "GNU Screen observation session is active"
    return None


def _open_lock(path: Path, *, directory_descriptor: int) -> int:
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path.name, flags, 0o600, dir_fd=directory_descriptor)
        details = os.fstat(descriptor)
        path_details = path.lstat()
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or (details.st_dev, details.st_ino) != (path_details.st_dev, path_details.st_ino)
        ):
            raise StateMigrationError(f"observer lock is unsafe: {path}")
        return descriptor
    except (OSError, StateMigrationError) as error:
        if "descriptor" in locals():
            os.close(descriptor)
        if isinstance(error, StateMigrationError):
            raise
        raise StateMigrationError(f"cannot acquire observer lock: {path}") from error


def _open_mutable(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        details = os.fstat(descriptor)
        path_details = path.lstat()
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or (details.st_dev, details.st_ino) != (path_details.st_dev, path_details.st_ino)
        ):
            raise StateMigrationError(f"mutable file changed during migration: {path}")
        return descriptor
    except (OSError, StateMigrationError) as error:
        if "descriptor" in locals():
            os.close(descriptor)
        if isinstance(error, StateMigrationError):
            raise
        raise StateMigrationError(f"cannot open mutable file: {path}") from error


def _digest(descriptor: int) -> str:
    digest = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    while block := os.read(descriptor, 1024 * 1024):
        digest.update(block)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return digest.hexdigest()


def _open_by_other_process(paths: tuple[Path, ...]) -> str | None:
    proc = Path("/proc")
    if not proc.is_dir():
        raise StateMigrationError("Linux /proc is required")
    targets = {
        (details.st_dev, details.st_ino): path
        for path in paths
        if (details := _regular_file(path, required=False)) is not None
    }
    for process in proc.iterdir():
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        try:
            descriptors = (process / "fd").iterdir()
            for descriptor in descriptors:
                try:
                    details = descriptor.stat()
                except PermissionError as error:
                    raise StateMigrationError(
                        f"cannot inspect open files for PID {process.name}"
                    ) from error
                except OSError:
                    continue
                path = targets.get((details.st_dev, details.st_ino))
                if path is not None:
                    return f"mutable file is open by PID {process.name}: {path}"
        except PermissionError as error:
            raise StateMigrationError(
                f"cannot inspect open files for PID {process.name}"
            ) from error
        except OSError:
            continue
    return None


def migrate_state(
    repository: Path,
    home: Path,
    account: pwd.struct_passwd,
    group_name: str,
    group_id: int,
) -> None:
    if os.geteuid() != 0:
        raise StateMigrationError("migrate-state must run as root")
    if active := _observer_state(account):
        raise StateMigrationError(f"stop observation before migration: {active}")
    _check_protected_runtime(home, group_id)
    environment_file = repository / ".env"
    environment_details = _regular_file(environment_file, required=True)
    assert environment_details is not None
    data_paths = tuple(home / name for name in DATABASE_NAMES)
    database_details = _regular_file(data_paths[0], required=True)
    assert database_details is not None
    mutable_details = {environment_file: environment_details, data_paths[0]: database_details}
    for path in data_paths[1:]:
        if details := _regular_file(path, required=False):
            mutable_details[path] = details
    for name in LOCK_NAMES:
        _regular_file(home / name, required=False)

    home_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    home_flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        home_descriptor = os.open(home, home_flags)
    except OSError as error:
        raise StateMigrationError("cannot open TRADING_LAB_HOME safely") from error
    original_home = os.fstat(home_descriptor)
    lock_descriptors: list[int] = []
    file_descriptors: dict[Path, int] = {}
    original_files: dict[int, os.stat_result] = {}
    completed = False
    try:
        for name in LOCK_NAMES:
            lock_descriptors.append(_open_lock(home / name, directory_descriptor=home_descriptor))
        os.fchown(home_descriptor, 0, group_id)
        os.fchmod(home_descriptor, 0o700)
        for name, descriptor in zip(LOCK_NAMES, lock_descriptors, strict=True):
            details = os.fstat(descriptor)
            current = (home / name).lstat()
            if (details.st_dev, details.st_ino) != (current.st_dev, current.st_ino):
                raise StateMigrationError(f"observer lock changed during migration: {home / name}")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise StateMigrationError(
                    f"another observer holds the lock: {home / name}"
                ) from error
        if active := _observer_state(account):
            raise StateMigrationError(f"stop observation before migration: {active}")
        present_data_paths = {
            path for path in data_paths if _regular_file(path, required=False) is not None
        }
        if present_data_paths != {path for path in mutable_details if path.parent == home}:
            raise StateMigrationError("SQLite sidecar set changed during migration")
        for path, expected in mutable_details.items():
            current = path.lstat()
            if (expected.st_dev, expected.st_ino) != (current.st_dev, current.st_ino):
                raise StateMigrationError(f"mutable file changed during migration: {path}")
        if active_file := _open_by_other_process(data_paths):
            raise StateMigrationError(active_file)
        for path in mutable_details:
            file_descriptors[path] = _open_mutable(path)
        before = {
            path: _digest(descriptor)
            for path, descriptor in file_descriptors.items()
            if path.parent == home
        }
        original_files = {
            descriptor: os.fstat(descriptor)
            for descriptor in (*file_descriptors.values(), *lock_descriptors)
        }
        for descriptor in (*file_descriptors.values(), *lock_descriptors):
            os.fchown(descriptor, account.pw_uid, group_id)
            os.fchmod(descriptor, 0o600)
        after = {
            path: _digest(descriptor)
            for path, descriptor in file_descriptors.items()
            if path in before
        }
        if before != after:
            raise StateMigrationError("mutable database bytes changed during migration")
        os.fchown(home_descriptor, 0, group_id)
        os.fchmod(home_descriptor, 0o1770)
        check_state(repository, home, account.pw_uid, group_id)
        completed = True
        print(f"verified: {home} owner=root:{group_name} mode=1770")
        for path in (repository / ".env", *data_paths, *(home / name for name in LOCK_NAMES)):
            if path.exists():
                print(f"verified: {path} owner={account.pw_name}:{group_name} mode=0600")
        for path, digest in before.items():
            print(f"preserved: {path} sha256={digest}")
        print(f"protected: {home / 'runtime-builds'} remains root-owned and non-writable")
    finally:
        if not completed:
            for descriptor, details in original_files.items():
                os.fchown(descriptor, details.st_uid, details.st_gid)
                os.fchmod(descriptor, stat.S_IMODE(details.st_mode))
            os.fchown(home_descriptor, original_home.st_uid, original_home.st_gid)
            os.fchmod(home_descriptor, stat.S_IMODE(original_home.st_mode))
        for descriptor in file_descriptors.values():
            os.close(descriptor)
        for descriptor in reversed(lock_descriptors):
            os.close(descriptor)
        os.close(home_descriptor)


def main() -> int:
    arguments = _parser().parse_args()
    try:
        account, group_id = _service_ids(arguments.service_user, arguments.service_group)
        repository, home = _scope(arguments.repository, arguments.home)
        if arguments.action == "check":
            check_state(repository, home, account.pw_uid, group_id)
            print("paper observation mutable-state ownership is valid")
        else:
            migrate_state(repository, home, account, arguments.service_group, group_id)
    except (OSError, StateMigrationError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
