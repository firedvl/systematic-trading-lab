"""Public CLI wrapper that keeps historical controlled-command source unchanged."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections.abc import Sequence
from decimal import Decimal, DecimalException
from pathlib import Path

from . import __version__
from .config import ConfigurationError, Settings, load_dotenv, load_settings
from .domain import TradingMode
from .fingerprints import canonicalize
from .rapid_data import import_local_data, list_research_datasets, parse_utc
from .rapid_research import (
    ResearchInputs,
    compare_runs,
    list_strategies,
    parameter_configurations,
    parse_parameter_grid,
    parse_parameters,
    run_backtest,
    run_stress,
    run_sweep,
    run_walk_forward,
)
from .rapid_store import RapidResearchStore, rapid_authority
from .strategy_registry import strategy_names


def _root_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="trading-lab",
        description="Research and guarded paper-trading tools for U.S. ETFs.",
    )
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command")
    for name, help_text in (
        ("doctor", "check runtime safety and local storage"),
        ("data", "import, list, and validate historical market data"),
        ("research", "backtest, sweep, walk forward, stress, and compare strategies"),
        ("backtest", "run the legacy deterministic fixture simulator"),
        ("experiment", "manage advanced controlled research experiments"),
        ("paper", "assess guarded paper execution"),
        ("status", "show runtime mode and dataset count"),
    ):
        commands.add_parser(name, help=help_text)
    return root


def research_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="trading-lab research",
        description=(
            "Run fast historical research. Results are exploratory and grant no qualification, "
            "paper, broker-write, protected-holdout, or live authority."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    commands = root.add_subparsers(dest="research_command", required=True)
    commands.add_parser("list-strategies", help="show built-in daily strategies and parameters")
    backtest = commands.add_parser(
        "backtest",
        help="run one net-of-cost historical simulation",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_inputs(backtest)
    walk_forward = commands.add_parser(
        "walk-forward",
        help="evaluate fixed parameters over chronological out-of-sample folds",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_inputs(walk_forward)
    walk_forward.add_argument("--training-window", type=int, default=252, help="training sessions")
    walk_forward.add_argument("--test-window", type=int, default=63, help="test sessions per fold")
    walk_forward.add_argument(
        "--step-size", type=int, default=63, help="sessions between test-fold starts"
    )
    walk_forward.add_argument(
        "--expanding", action="store_true", help="expand training from the first session"
    )
    sweep = commands.add_parser(
        "sweep",
        help="run a bounded exploratory parameter grid",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_inputs(sweep, parameter_help="repeatable NAME=INTEGER[,INTEGER...]")
    sweep.add_argument("--max-runs", type=int, default=100, help="hard configuration cap")
    stress = commands.add_parser(
        "stress",
        help="rerun a completed run with worse execution",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    stress.add_argument("run_id")
    stress.add_argument(
        "--slippage-bps", type=_decimal, default=Decimal("10"), help="stressed slippage"
    )
    stress.add_argument(
        "--commission-bps",
        type=_decimal,
        default=Decimal("2"),
        help="stressed commission",
    )
    stress.add_argument("--fill-delay-bars", type=int, default=2, help="stressed execution delay")
    commands.add_parser("list", help="list stored Rapid Research runs")
    show = commands.add_parser("show", help="show one stored run")
    show.add_argument("run_id")
    compare = commands.add_parser("compare", help="compare stored runs without a composite score")
    compare.add_argument("run_ids", nargs="+")
    export = commands.add_parser(
        "export-candidate", help="write a review artifact that grants zero authority"
    )
    export.add_argument("run_id")
    return root


def data_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="trading-lab data",
        description="Import, list, inspect, and validate historical market data.",
    )
    commands = root.add_subparsers(dest="data_command", required=True)
    commands.add_parser("list", help="list cataloged and user-supplied daily datasets")
    local = commands.add_parser(
        "import-local", help="import user-supplied daily CSV or Parquet OHLCV data"
    )
    local.add_argument("path", type=Path)
    for name, help_text in (
        ("import-fixture", "import deterministic offline daily bars"),
        ("import-intraday-fixture", "import deterministic offline intraday bars"),
        ("import-alpaca", "import read-only Alpaca historical bars"),
        ("describe", "show one cataloged dataset manifest"),
        ("validate", "validate one cataloged dataset"),
        ("rebuild-catalog", "rebuild the catalog from immutable manifests"),
    ):
        commands.add_parser(name, help=help_text)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if not arguments:
        _root_parser().print_help()
        return 2
    if arguments in {("-h",), ("--help",)}:
        _root_parser().print_help()
        return 0
    if arguments[0] == "research":
        return _run_public(research_parser().parse_args(arguments[1:]))
    if arguments[0] == "data" and (
        len(arguments) == 1 or arguments[1] in {"-h", "--help", "list", "import-local"}
    ):
        return _run_public(data_parser().parse_args(arguments[1:]))

    from .cli import main as legacy_main

    return legacy_main(arguments)


def _run_public(arguments: argparse.Namespace) -> int:
    try:
        load_dotenv()
        settings = load_settings()
        _require_research_mode(settings)
        if hasattr(arguments, "research_command"):
            return _run_research(arguments, settings)
        return _run_data(arguments, settings)
    except (ConfigurationError, KeyError, OSError, sqlite3.DatabaseError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return os.EX_USAGE


def _run_research(arguments: argparse.Namespace, settings: Settings) -> int:
    if arguments.research_command == "list-strategies":
        _print({"strategies": list_strategies(), "authority": rapid_authority()})
        return 0
    store = RapidResearchStore(settings.home)
    if arguments.research_command == "list":
        _print(
            {
                "runs": [_run_summary(run) for run in store.list_runs()],
                "authority": rapid_authority(),
            }
        )
        return 0
    if arguments.research_command == "show":
        _print({**store.get_run(arguments.run_id), "authority": rapid_authority()})
        return 0
    if arguments.research_command == "compare":
        _print(compare_runs(store, arguments.run_ids))
        return 0
    if arguments.research_command == "export-candidate":
        _print(store.export_candidate(arguments.run_id))
        return 0
    if arguments.research_command == "stress":
        _print(
            run_stress(
                settings.home,
                store,
                arguments.run_id,
                arguments.slippage_bps,
                arguments.commission_bps,
                arguments.fill_delay_bars,
            )
        )
        return 0
    inputs = _inputs(arguments)
    if arguments.research_command == "backtest":
        _print(run_backtest(settings.home, store, inputs))
        return 0
    if arguments.research_command == "walk-forward":
        _print(
            run_walk_forward(
                settings.home,
                store,
                inputs,
                arguments.training_window,
                arguments.test_window,
                arguments.step_size,
                expanding=arguments.expanding,
            )
        )
        return 0
    grid = parse_parameter_grid(arguments.parameter)
    count = len(parameter_configurations(grid))
    print(f"parameter configurations: {count} (cap: {arguments.max_runs})", file=sys.stderr)
    _print(run_sweep(settings.home, store, inputs, grid, arguments.max_runs))
    return 0


def _run_data(arguments: argparse.Namespace, settings: Settings) -> int:
    store = RapidResearchStore(settings.home)
    if arguments.data_command == "list":
        _print({"datasets": list_research_datasets(settings.home, store)})
        return 0
    _print(import_local_data(arguments.path, store))
    return 0


def _add_inputs(command: argparse.ArgumentParser, *, parameter_help: str | None = None) -> None:
    command.add_argument("--dataset", required=True, help="dataset ID from `data list`")
    command.add_argument("--strategy", required=True, choices=strategy_names())
    command.add_argument(
        "--parameter",
        action="append",
        default=[],
        help=parameter_help or "repeatable NAME=INTEGER",
    )
    command.add_argument("--start", help="optional UTC date or RFC-3339 start")
    command.add_argument("--end", help="optional UTC date or RFC-3339 end")
    command.add_argument(
        "--initial-cash", type=_decimal, default=Decimal("100000"), help="starting cash"
    )
    command.add_argument(
        "--slippage-bps", type=_decimal, default=Decimal("5"), help="slippage per fill"
    )
    command.add_argument(
        "--commission-bps", type=_decimal, default=Decimal("1"), help="commission per fill"
    )
    command.add_argument(
        "--fill-delay-bars", type=int, default=1, help="bars from decision to fill"
    )


def _inputs(arguments: argparse.Namespace) -> ResearchInputs:
    parameters = (
        {} if arguments.research_command == "sweep" else parse_parameters(arguments.parameter)
    )
    return ResearchInputs(
        arguments.dataset,
        arguments.strategy,
        parameters,
        None if arguments.start is None else parse_utc(arguments.start),
        None if arguments.end is None else parse_utc(arguments.end),
        arguments.initial_cash,
        arguments.slippage_bps,
        arguments.commission_bps,
        arguments.fill_delay_bars,
    )


def _require_research_mode(settings: Settings) -> None:
    if settings.mode not in {TradingMode.OFFLINE, TradingMode.RESEARCH}:
        raise ConfigurationError("Rapid Research requires offline or research mode")
    if settings.paper_write_request is not None:
        raise ConfigurationError("Rapid Research cannot run with paper-write opt-in")


def _decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except DecimalException as error:
        raise argparse.ArgumentTypeError("expected a finite decimal number") from error
    if not parsed.is_finite():
        raise argparse.ArgumentTypeError("expected a finite decimal number")
    return parsed


def _run_summary(run: dict[str, object]) -> dict[str, object]:
    return {
        name: run[name]
        for name in (
            "run_id",
            "run_type",
            "status",
            "dataset_id",
            "strategy_name",
            "parameters",
            "start_timestamp",
            "end_timestamp",
            "metrics",
            "error",
        )
    }


def _print(value: object) -> None:
    print(json.dumps(canonicalize(value), indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
