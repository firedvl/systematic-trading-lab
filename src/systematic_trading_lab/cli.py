"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .config import ConfigurationError, Settings, load_settings
from .datasets import DatasetService, DatasetValidationError, fixture_request, fixture_symbols
from .domain import Timeframe
from .providers import FixtureProvider
from .storage import StorageLayout


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="trading-lab")
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="check runtime safety and local storage")
    commands.add_parser("status", help="show runtime mode and dataset count")
    data = commands.add_parser("data", help="manage local market data").add_subparsers(
        dest="data_command", required=True
    )
    data.add_parser("import-fixture", help="import deterministic offline bars")
    for name in ("validate", "describe"):
        command = data.add_parser(name)
        command.add_argument("dataset_id", nargs="?")
    data.add_parser("rebuild-catalog", help="reconstruct the SQLite index from manifests")
    return root


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = parser().parse_args(argv)
        settings = load_settings()
        return run(arguments, settings)
    except (ConfigurationError, DatasetValidationError, KeyError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def run(arguments: argparse.Namespace, settings: Settings) -> int:
    layout = StorageLayout(settings.home)
    service = DatasetService(layout)
    if arguments.command == "doctor":
        checks = {
            "python_3_12_or_newer": sys.version_info >= (3, 12),
            "mode_is_explicitly_safe": not settings.broker_writes_allowed,
            "runtime_path_is_not_repository_root": settings.home != Path.cwd().resolve(),
            "alpaca_secrets_absent": not any(
                name in os.environ for name in ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY")
            ),
        }
        checks["storage_writable"] = _storage_writable(layout)
        _print({"mode": settings.mode.value, "home": str(settings.home), "checks": checks})
        return 0 if all(checks.values()) else 1
    if arguments.command == "status":
        _print(
            {
                "mode": settings.mode.value,
                "broker_writes_allowed": settings.broker_writes_allowed,
                "datasets": service.catalog.count(),
                "home": str(settings.home),
            }
        )
        return 0
    if arguments.data_command == "import-fixture":
        imported = service.import_from(
            FixtureProvider(), fixture_symbols(), Timeframe.DAILY, fixture_request()
        )
        _print(imported.__dict__)
        return 0
    if arguments.data_command == "describe":
        _print(service.describe(arguments.dataset_id))
        return 0
    if arguments.data_command == "validate":
        validation = service.validate(arguments.dataset_id)
        _print(validation)
        return 0 if validation["valid"] else 1
    if arguments.data_command == "rebuild-catalog":
        _print({"registered": service.rebuild_catalog()})
        return 0
    raise ValueError("unknown command")


def _storage_writable(layout: StorageLayout) -> bool:
    try:
        layout.prepare()
        probe = layout.root / ".doctor"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
