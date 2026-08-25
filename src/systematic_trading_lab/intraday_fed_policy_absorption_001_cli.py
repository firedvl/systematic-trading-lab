"""CLI extension for Intraday Fed Policy Absorption 001."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

from .config import ConfigurationError, load_dotenv, load_settings
from .domain import TradingMode
from .fingerprints import canonicalize
from .intraday_fed_policy_absorption_001_plan import PROGRAM_ID
from .intraday_fed_policy_absorption_001_runner import (
    intraday_fed_policy_absorption_001_plan_summary,
    intraday_fed_policy_absorption_001_status,
    run_intraday_fed_policy_absorption_001_campaign,
)
from .intraday_relative_volume_drift_001_cli import main as relative_volume_main
from .research_attempts import AttemptStateError


def intraday_fed_policy_absorption_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"trading-lab research {PROGRAM_ID}",
        description="Run or inspect the frozen Intraday Fed Policy Absorption 001 campaign.",
    )
    parser.add_argument("action", nargs="?", choices=("plan", "run", "status"), default="status")
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="bounded worker processes used within each research stage",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments[:2] != ("research", PROGRAM_ID):
        return relative_volume_main(arguments)
    parsed = intraday_fed_policy_absorption_parser().parse_args(arguments[2:])
    try:
        load_dotenv()
        settings = load_settings()
        if settings.mode not in {TradingMode.OFFLINE, TradingMode.RESEARCH}:
            raise ConfigurationError("Intraday Fed Policy Absorption 001 requires research mode")
        if settings.paper_write_request is not None:
            raise ConfigurationError(
                "Intraday Fed Policy Absorption 001 cannot run with paper-write opt-in"
            )
        repository = Path(__file__).resolve().parents[2]
        if parsed.action == "plan":
            result = intraday_fed_policy_absorption_001_plan_summary(repository)
        elif parsed.action == "status":
            result = intraday_fed_policy_absorption_001_status(settings.home)
        else:
            result = run_intraday_fed_policy_absorption_001_campaign(
                repository,
                settings.home,
                workers=parsed.workers,
                progress=lambda message: print(message, file=sys.stderr),
            )
        print(json.dumps(canonicalize(result), indent=2, sort_keys=True))
        return 0
    except (
        AttemptStateError,
        ConfigurationError,
        KeyError,
        OSError,
        sqlite3.DatabaseError,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return os.EX_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
