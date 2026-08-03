"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from . import __version__
from .backtesting import BacktestEngine
from .config import ConfigurationError, Settings, load_settings
from .datasets import DatasetService, DatasetValidationError, fixture_request, fixture_symbols
from .domain import OHLCVBar, Timeframe, TimestampRange, TradingMode
from .providers import AlpacaHistoricalProvider, FixtureProvider
from .storage import StorageLayout
from .strategies import BuyAndHoldStrategy, CashStrategy


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
    alpaca = data.add_parser("import-alpaca", help="import read-only Alpaca historical bars")
    alpaca.add_argument("--start", required=True, help="UTC date or RFC-3339 start")
    alpaca.add_argument("--end", required=True, help="UTC date or RFC-3339 end")
    for name in ("validate", "describe"):
        command = data.add_parser(name)
        command.add_argument("dataset_id", nargs="?")
    data.add_parser("rebuild-catalog", help="reconstruct the SQLite index from manifests")
    backtest = commands.add_parser("backtest", help="run deterministic local simulations")
    backtest_commands = backtest.add_subparsers(dest="backtest_command", required=True)
    fixture_backtest = backtest_commands.add_parser(
        "fixture", help="backtest deterministic fixture bars"
    )
    fixture_backtest.add_argument("--strategy", choices=("cash", "buy-and-hold"), default="cash")
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
    if arguments.command == "backtest":
        records = FixtureProvider().fetch(fixture_symbols()[:1], Timeframe.DAILY, fixture_request())
        bars = tuple(OHLCVBar.from_record(record) for record in records)
        strategy = CashStrategy() if arguments.strategy == "cash" else BuyAndHoldStrategy()
        result = BacktestEngine(Decimal("100000")).run(bars, strategy)
        _print(
            {
                "strategy": result.strategy_id,
                "metrics": {
                    "total_return": str(result.metrics.total_return),
                    "max_drawdown": str(result.metrics.max_drawdown),
                    "turnover": str(result.metrics.turnover),
                    "trade_count": result.metrics.trade_count,
                },
                "artifact_fingerprint": result.artifact_fingerprint,
            }
        )
        return 0
    if arguments.command == "doctor":
        checks = {
            "python_3_12_or_newer": sys.version_info >= (3, 12),
            "mode_is_explicitly_safe": not settings.broker_writes_allowed,
            "runtime_path_is_not_repository_root": settings.home != Path.cwd().resolve(),
            "research_credentials_present_or_not_required": settings.mode
            is not TradingMode.RESEARCH
            or all(name in os.environ for name in ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY")),
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
    if arguments.data_command == "import-alpaca":
        if settings.mode is not TradingMode.RESEARCH:
            raise ValueError("Alpaca data import requires TRADING_LAB_MODE=research")
        provider = AlpacaHistoricalProvider(
            os.environ.get("APCA_API_KEY_ID", ""), os.environ.get("APCA_API_SECRET_KEY", "")
        )
        imported = service.import_from(
            provider,
            fixture_symbols(),
            Timeframe.DAILY,
            TimestampRange(_parse_utc(arguments.start), _parse_utc(arguments.end)),
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


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
