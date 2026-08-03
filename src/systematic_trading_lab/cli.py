"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from . import __version__
from .backtesting import CostModel
from .config import ConfigurationError, Settings, load_dotenv, load_settings
from .datasets import DatasetService, DatasetValidationError, fixture_request, fixture_symbols
from .domain import OHLCVBar, Timeframe, TimestampRange, TradingMode
from .experiment_runner import (
    comparison_report,
    execution_model_version,
    run_cataloged_experiment,
    run_holdout_experiment,
)
from .experiments import ExperimentError, ExperimentRegistry, ExperimentSpec, ExperimentSplit
from .providers import AlpacaHistoricalProvider, FixtureProvider
from .qualification import load_qualification_proposal
from .qualification_evidence import (
    authorize_holdout_run,
    build_evidence_reports,
    load_evidence_manifest,
    write_evidence_reports,
)
from .reporting import benchmark_suite, build_report, report_json, strategy_result, write_report
from .storage import StorageLayout
from .universe import load_research_universe


def _add_execution_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("experiment_id")
    command.add_argument("--campaign", required=True)
    command.add_argument(
        "--strategy",
        choices=("cash", "buy-and-hold", "fixed-weight", "moving-average", "momentum"),
        required=True,
    )
    command.add_argument("--code-commit", required=True)
    command.add_argument("--dataset", required=True)
    command.add_argument("--start", required=True)
    command.add_argument("--end", required=True)
    command.add_argument("--reason", required=True)
    command.add_argument("--parameter", action="append", default=[], help="repeatable NAME=INTEGER")
    command.add_argument("--slippage-bps", type=_decimal_argument, default=Decimal("5"))
    command.add_argument("--commission-bps", type=_decimal_argument, default=Decimal("1"))
    command.add_argument("--cost-version")
    command.add_argument("--fill-delay-bars", type=int, default=1)


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
    fixture_backtest.add_argument(
        "--strategy",
        choices=("cash", "buy-and-hold", "fixed-weight", "moving-average", "momentum", "all"),
        default="cash",
    )
    fixture_backtest.add_argument("--output", type=Path)
    experiment = commands.add_parser("experiment", help="manage durable research experiments")
    experiment_commands = experiment.add_subparsers(dest="experiment_command", required=True)
    campaign = experiment_commands.add_parser("create-campaign")
    campaign.add_argument("campaign_id")
    campaign.add_argument("--name", required=True)
    campaign.add_argument("--budget", required=True, type=int)
    create = experiment_commands.add_parser("create")
    create.add_argument("experiment_id")
    create.add_argument("--campaign", required=True)
    create.add_argument("--strategy-id", required=True)
    create.add_argument("--strategy-version", required=True)
    create.add_argument("--strategy-family", required=True)
    create.add_argument("--code-commit", required=True)
    create.add_argument("--dataset-id", required=True)
    create.add_argument("--split", choices=("training", "validation"), required=True)
    create.add_argument("--start", required=True)
    create.add_argument("--end", required=True)
    create.add_argument("--reason", required=True)
    for name in ("claim", "status"):
        experiment_commands.add_parser(name).add_argument("experiment_id")
    complete = experiment_commands.add_parser("complete")
    complete.add_argument("experiment_id")
    complete.add_argument(
        "--metric", action="append", required=True, help="repeatable NAME=VALUE metric"
    )
    fail = experiment_commands.add_parser("fail")
    fail.add_argument("experiment_id")
    fail.add_argument("--reason", required=True)
    recover = experiment_commands.add_parser("recover")
    recover.add_argument("--max-age-minutes", type=int, required=True)
    execute = experiment_commands.add_parser(
        "run", help="record and run a bounded training or validation experiment"
    )
    _add_execution_arguments(execute)
    execute.add_argument("--split", choices=("training", "validation"), required=True)
    execute.add_argument("--parent-candidate")
    holdout = experiment_commands.add_parser(
        "run-holdout", help="consume one stored authorization and run its exact holdout"
    )
    _add_execution_arguments(holdout)
    holdout.add_argument("--authorization", required=True)
    holdout.add_argument("--parent-candidate", required=True)
    compare = experiment_commands.add_parser("compare")
    compare.add_argument("experiment_ids", nargs="+")
    qualify = experiment_commands.add_parser(
        "evaluate-qualification",
        help="aggregate registered validation evidence without reading holdout data",
    )
    qualify.add_argument("--evidence-manifest", type=Path, required=True)
    qualify.add_argument("--proposal", type=Path, required=True)
    authorize = experiment_commands.add_parser(
        "authorize-holdout",
        help="store one holdout-run authorization from approved passing evidence",
    )
    authorize.add_argument("authorization_id")
    authorize.add_argument("--candidate", required=True)
    authorize.add_argument("--evidence-manifest", type=Path, required=True)
    authorize.add_argument("--proposal", type=Path, required=True)
    authorize.add_argument("--reviewer", required=True)
    authorize.add_argument("--reason", required=True)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = parser().parse_args(argv)
        load_dotenv()
        settings = load_settings()
        return run(arguments, settings)
    except (
        ConfigurationError,
        DatasetValidationError,
        ExperimentError,
        KeyError,
        OSError,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def run(arguments: argparse.Namespace, settings: Settings) -> int:
    layout = StorageLayout(settings.home)
    service = DatasetService(layout)
    universe = load_research_universe()
    if arguments.command == "experiment":
        registry = ExperimentRegistry(layout.experiments)
        if arguments.experiment_command == "create-campaign":
            _print(
                registry.create_campaign(arguments.campaign_id, arguments.name, arguments.budget)
            )
        elif arguments.experiment_command == "create":
            if not service.validate(arguments.dataset_id)["valid"]:
                raise DatasetValidationError("dataset integrity validation failed")
            manifest = service.describe(arguments.dataset_id)
            identity = manifest["identity"]
            registry.create_experiment(
                ExperimentSpec(
                    experiment_id=arguments.experiment_id,
                    campaign_id=arguments.campaign,
                    strategy_id=arguments.strategy_id,
                    strategy_version=arguments.strategy_version,
                    strategy_family=arguments.strategy_family,
                    code_commit=arguments.code_commit,
                    dataset_id=identity["dataset_id"],
                    dataset_fingerprint=identity["fingerprint"],
                    universe_id=manifest["universe_id"],
                    universe_fingerprint=manifest["universe_fingerprint"],
                    parameters={},
                    cost_model_version="conservative-bps-v1",
                    execution_model_version="next-bar-v1",
                    split=ExperimentSplit(arguments.split),
                    start_timestamp=_parse_utc(arguments.start),
                    end_timestamp=_parse_utc(arguments.end),
                    random_seed=0,
                    creation_reason=arguments.reason,
                )
            )
            _print(registry.get(arguments.experiment_id))
        elif arguments.experiment_command == "claim":
            registry.claim(arguments.experiment_id)
            _print(registry.get(arguments.experiment_id))
        elif arguments.experiment_command == "complete":
            registry.complete(arguments.experiment_id, _parse_metrics(arguments.metric))
            _print(registry.get(arguments.experiment_id))
        elif arguments.experiment_command == "fail":
            registry.fail(arguments.experiment_id, arguments.reason)
            _print(registry.get(arguments.experiment_id))
        elif arguments.experiment_command == "recover":
            _print(
                {"recovered": registry.recover_stale(timedelta(minutes=arguments.max_age_minutes))}
            )
        elif arguments.experiment_command in {"run", "run-holdout"}:
            manifest = service.describe(arguments.dataset)
            identity = manifest["identity"]
            cost_model = _cost_model(arguments)
            strategy_id, strategy_family = _strategy_identity(arguments.strategy)
            parameters = _parse_parameters(arguments.parameter)
            _validate_strategy_parameters(arguments.strategy, parameters)
            is_holdout = arguments.experiment_command == "run-holdout"
            spec = ExperimentSpec(
                experiment_id=arguments.experiment_id,
                campaign_id=arguments.campaign,
                strategy_id=strategy_id,
                strategy_version="1",
                strategy_family=strategy_family,
                code_commit=arguments.code_commit,
                dataset_id=identity["dataset_id"],
                dataset_fingerprint=identity["fingerprint"],
                universe_id=manifest["universe_id"],
                universe_fingerprint=manifest["universe_fingerprint"],
                parameters=parameters,
                cost_model_version=cost_model.version,
                execution_model_version=execution_model_version(arguments.fill_delay_bars),
                split=(ExperimentSplit.HOLDOUT if is_holdout else ExperimentSplit(arguments.split)),
                start_timestamp=_parse_utc(arguments.start),
                end_timestamp=_parse_utc(arguments.end),
                random_seed=0,
                creation_reason=arguments.reason,
                parent_candidate=arguments.parent_candidate,
            )
            if is_holdout:
                run_holdout_experiment(
                    registry,
                    service,
                    arguments.authorization,
                    spec,
                    cost_model=cost_model,
                    fill_delay_bars=arguments.fill_delay_bars,
                )
            else:
                run_cataloged_experiment(
                    registry,
                    service,
                    spec,
                    layout.reports,
                    cost_model=cost_model,
                    fill_delay_bars=arguments.fill_delay_bars,
                )
            _print(registry.get(arguments.experiment_id))
        elif arguments.experiment_command == "compare":
            _print(comparison_report(registry, arguments.experiment_ids))
        elif arguments.experiment_command == "evaluate-qualification":
            reports = build_evidence_reports(
                registry,
                load_evidence_manifest(arguments.evidence_manifest),
                load_qualification_proposal(arguments.proposal),
            )
            path = write_evidence_reports(layout.reports, reports)
            _print(
                {
                    "report": str(path),
                    "candidate_ids": [report["candidate_id"] for report in reports],
                    "evidence_fingerprints": [report["evidence_fingerprint"] for report in reports],
                }
            )
        elif arguments.experiment_command == "authorize-holdout":
            authorization = authorize_holdout_run(
                registry,
                load_evidence_manifest(arguments.evidence_manifest),
                load_qualification_proposal(arguments.proposal),
                arguments.candidate,
                arguments.authorization_id,
                arguments.reviewer,
                arguments.reason,
            )
            _print(
                {
                    "authorization_id": authorization["authorization_id"],
                    "candidate_id": authorization["candidate_id"],
                    "evidence_fingerprint": authorization["evidence_fingerprint"],
                    "authorized_at": authorization["authorized_at"],
                    "consumed_by_experiment_id": authorization["consumed_by_experiment_id"],
                }
            )
        else:
            _print(registry.get(arguments.experiment_id))
        return 0
    if arguments.command == "backtest":
        records = FixtureProvider().fetch(fixture_symbols(), Timeframe.DAILY, fixture_request())
        bars = tuple(OHLCVBar.from_record(record) for record in records)
        initial_cash = Decimal("100000")
        if arguments.strategy == "all":
            results = benchmark_suite(bars, initial_cash)
            results["moving-average"] = strategy_result("moving-average", bars, initial_cash)
            results["momentum"] = strategy_result("momentum", bars, initial_cash)
        else:
            results = {arguments.strategy: strategy_result(arguments.strategy, bars, initial_cash)}
        if arguments.output:
            write_report(arguments.output, results)
            _print(
                {
                    "report": str(arguments.output),
                    "report_fingerprint": build_report(results)["report_fingerprint"],
                }
            )
        else:
            print(report_json(results), end="")
        return 0
    if arguments.command == "doctor":
        checks = {
            "python_3_12_or_newer": sys.version_info >= (3, 12),
            "mode_is_explicitly_safe": not settings.broker_writes_allowed,
            "runtime_path_is_not_repository_root": settings.home != Path.cwd().resolve(),
            "research_credentials_present_or_not_required": settings.mode
            is not TradingMode.RESEARCH
            or all(os.environ.get(name) for name in ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY")),
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
            FixtureProvider(), fixture_symbols(), Timeframe.DAILY, fixture_request(), universe
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
            universe,
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


def _parse_metrics(values: Sequence[str]) -> dict[str, object]:
    metrics: dict[str, object] = {}
    for value in values:
        name, separator, metric = value.partition("=")
        if not separator or not name or not metric or name in metrics:
            raise ValueError("metrics must be unique NAME=VALUE pairs")
        metrics[name] = metric
    return metrics


def _parse_parameters(values: Sequence[str]) -> dict[str, object]:
    parameters: dict[str, object] = {}
    for value in values:
        name, separator, raw = value.partition("=")
        if not separator or not name or not raw or name in parameters:
            raise ValueError("parameters must be unique NAME=INTEGER pairs")
        try:
            parsed = int(raw)
        except ValueError as error:
            raise ValueError("parameters must be unique NAME=INTEGER pairs") from error
        parameters[name] = parsed
    return parameters


def _validate_strategy_parameters(name: str, parameters: dict[str, object]) -> None:
    allowed = {
        "cash": set(),
        "buy-and-hold": set(),
        "fixed-weight": set(),
        "moving-average": {"window"},
        "momentum": {"lookback"},
    }[name]
    unknown = parameters.keys() - allowed
    if unknown:
        raise ValueError(f"unsupported parameters for {name}: {', '.join(sorted(unknown))}")


def _decimal_argument(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except ArithmeticError as error:
        raise argparse.ArgumentTypeError("expected a decimal number") from error
    if not parsed.is_finite():
        raise argparse.ArgumentTypeError("expected a finite decimal number")
    return parsed


def _cost_model(arguments: argparse.Namespace) -> CostModel:
    version = arguments.cost_version
    if version is None:
        if (arguments.slippage_bps, arguments.commission_bps) == (Decimal("5"), Decimal("1")):
            version = "conservative-bps-v1"
        else:
            version = f"bps-{arguments.slippage_bps}-{arguments.commission_bps}-v1"
    return CostModel(version, arguments.slippage_bps, arguments.commission_bps)


def _strategy_identity(name: str) -> tuple[str, str]:
    return {
        "cash": ("cash", "baseline"),
        "buy-and-hold": ("buy-and-hold", "baseline"),
        "fixed-weight": ("fixed-weight", "allocation"),
        "moving-average": ("moving-average-trend", "trend"),
        "momentum": ("time-series-momentum", "momentum"),
    }[name]


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
