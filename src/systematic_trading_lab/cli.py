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
from .alpaca_paper import AlpacaPaperReader
from .backtesting import CostModel
from .campaign_specs import load_training_campaign_plan
from .config import ConfigurationError, Settings, load_dotenv, load_settings
from .datasets import (
    DatasetService,
    DatasetValidationError,
    fixture_request,
    fixture_symbols,
    intraday_fixture_request,
    intraday_fixture_symbols,
)
from .domain import OHLCVBar, Timeframe, TimestampRange, TradingMode
from .experiment_runner import (
    comparison_report,
    execution_model_version,
    run_cataloged_experiment,
    run_holdout_experiment,
)
from .experiments import ExperimentError, ExperimentRegistry, ExperimentSpec, ExperimentSplit
from .paper_equivalence import PaperEquivalenceStore, load_action_plan
from .paper_observation import (
    PaperObservation,
    PaperObservationStatus,
    PaperObservationStore,
    record_production_observation,
)
from .paper_startup import assess_paper_startup, initialize_paper_storage
from .providers import AlpacaHistoricalProvider, FixtureProvider, IntradayFixtureProvider
from .qualification import load_qualification_proposal, review_holdout
from .qualification_evidence import (
    authorize_holdout_run,
    build_evidence_reports,
    load_evidence_manifest,
    write_evidence_reports,
)
from .reconciliation import ReconciliationStore
from .reporting import benchmark_suite, build_report, report_json, strategy_result, write_report
from .risk import load_risk_limits
from .runtime_build import (
    RuntimeBuildVerificationError,
    verify_attested_build,
    verify_installed_runtime,
)
from .storage import StorageLayout
from .universe import load_intraday_universe, load_research_universe


def _add_execution_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("experiment_id")
    command.add_argument("--campaign", required=True)
    command.add_argument(
        "--strategy",
        choices=(
            "cash",
            "buy-and-hold",
            "fixed-weight",
            "moving-average",
            "mean-reversion",
            "momentum",
            "relative-strength",
            "risk-managed-momentum",
            "strategic-allocation",
            "volatility-balanced",
            "volatility-targeted",
        ),
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
    paper = commands.add_parser("paper", help="assess guarded paper execution").add_subparsers(
        dest="paper_command", required=True
    )
    startup = paper.add_parser("assess-startup", help="read-only paper startup assessment")
    startup.add_argument("--authorization", required=True)
    startup.add_argument(
        "--risk-config", type=Path, default=Path("config/risk/alpaca-paper-v1.json")
    )
    startup.add_argument("--wheel", type=Path)
    startup.add_argument("--manifest", type=Path)
    paper.add_parser(
        "initialize-storage", help="create empty paper schema without adding authority"
    )
    observation_start = paper.add_parser(
        "start-observation", help="start a broker-read-only paper observation campaign"
    )
    observation_start.add_argument("campaign_id")
    observation_start.add_argument(
        "--risk-config", type=Path, default=Path("config/risk/alpaca-paper-v1.json")
    )
    observation_start.add_argument("--maximum-gap-seconds", type=int, default=900)
    observation_start.add_argument("--duration-hours", type=int, default=168)
    observation_record = paper.add_parser(
        "record-observation", help="record one broker-read-only paper observation"
    )
    observation_record.add_argument("campaign_id")
    observation_record.add_argument(
        "--risk-config", type=Path, default=Path("config/risk/alpaca-paper-v1.json")
    )
    observation_status = paper.add_parser(
        "assess-observation", help="assess paper observation continuity and drift"
    )
    observation_status.add_argument("campaign_id")
    equivalence = paper.add_parser(
        "record-equivalence", help="record one replay, shadow, and paper action comparison"
    )
    equivalence.add_argument("campaign_id")
    equivalence.add_argument("comparison_id")
    equivalence.add_argument("--replay-plan", type=Path, required=True)
    equivalence.add_argument("--shadow-plan", type=Path, required=True)
    equivalence.add_argument("--paper-intent", action="append", required=True)
    data = commands.add_parser("data", help="manage local market data").add_subparsers(
        dest="data_command", required=True
    )
    data.add_parser("import-fixture", help="import deterministic offline bars")
    intraday_fixture = data.add_parser(
        "import-intraday-fixture", help="import deterministic offline intraday bars"
    )
    intraday_fixture.add_argument("--timeframe", choices=("1m", "5m"), default="5m")
    alpaca = data.add_parser("import-alpaca", help="import read-only Alpaca historical bars")
    alpaca.add_argument("--start", required=True, help="UTC date or RFC-3339 start")
    alpaca.add_argument("--end", required=True, help="UTC date or RFC-3339 end")
    alpaca.add_argument("--timeframe", choices=("1d", "1m", "5m"), default="1d")
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
        choices=(
            "cash",
            "buy-and-hold",
            "fixed-weight",
            "moving-average",
            "mean-reversion",
            "momentum",
            "volatility-targeted",
            "all",
        ),
        default="cash",
    )
    fixture_backtest.add_argument("--output", type=Path)
    experiment = commands.add_parser("experiment", help="manage durable research experiments")
    experiment_commands = experiment.add_subparsers(dest="experiment_command", required=True)
    campaign = experiment_commands.add_parser("create-campaign")
    campaign.add_argument("campaign_id")
    campaign.add_argument("--name", required=True)
    campaign.add_argument("--budget", required=True, type=int)
    planned_campaign = experiment_commands.add_parser("plan-training")
    planned_campaign.add_argument("--spec", type=Path, required=True)
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
    planned_run = experiment_commands.add_parser(
        "run-planned", help="run one pre-registered sealed training candidate"
    )
    planned_run.add_argument("experiment_id")
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
    review = experiment_commands.add_parser(
        "review-holdout",
        help="log one approved review and evaluate protected holdout metrics",
    )
    review.add_argument("experiment_id")
    review.add_argument("--event-id", required=True)
    review.add_argument("--proposal", type=Path, required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--reason", required=True)
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
        RuntimeBuildVerificationError,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def run(arguments: argparse.Namespace, settings: Settings) -> int:
    layout = StorageLayout(settings.home)
    if arguments.command == "paper":
        if arguments.paper_command == "initialize-storage":
            result = initialize_paper_storage(layout.execution)
            _print(
                {
                    "database_path": result.database_path,
                    "table_count": result.table_count,
                    "journal_event_count": result.journal_event_count,
                    "authority_evidence_unchanged": result.authority_evidence_unchanged,
                    "broker_writes_allowed": False,
                }
            )
            return 0
        if arguments.paper_command == "start-observation":
            limits = load_risk_limits(arguments.risk_config)
            reader = _paper_observation_reader(settings, limits.account_id, limits.allowed_symbols)
            snapshot = reader.record_portfolio(ReconciliationStore(layout.execution))
            store = PaperObservationStore(layout.execution)
            campaign = store.start(
                campaign_id=arguments.campaign_id,
                baseline_snapshot_id=snapshot.snapshot_id,
                maximum_gap_seconds=arguments.maximum_gap_seconds,
                duration=timedelta(hours=arguments.duration_hours),
            )
            _print(
                {
                    "campaign_id": campaign.campaign_id,
                    "baseline_snapshot_id": campaign.baseline_snapshot_id,
                    "expected_positions": [
                        {"symbol": item.symbol, "quantity": item.quantity}
                        for item in campaign.expected_positions
                    ],
                    "maximum_gap_seconds": campaign.maximum_gap_seconds,
                    "starts_at": campaign.starts_at.isoformat().replace("+00:00", "Z"),
                    "ends_at": campaign.ends_at.isoformat().replace("+00:00", "Z"),
                    "broker_writes_allowed": False,
                }
            )
            return 0
        if arguments.paper_command == "record-observation":
            limits = load_risk_limits(arguments.risk_config)
            store = PaperObservationStore(layout.execution)
            observation = record_production_observation(
                store,
                _paper_observation_reader(settings, limits.account_id, limits.allowed_symbols),
                campaign_id=arguments.campaign_id,
            )
            status = store.assess(arguments.campaign_id, assessed_at=datetime.now(UTC))
            _print(_paper_observation_result(observation, status))
            return 0 if status.healthy_now else 1
        if arguments.paper_command == "assess-observation":
            status = PaperObservationStore(layout.execution).assess(
                arguments.campaign_id, assessed_at=datetime.now(UTC)
            )
            _print(_paper_observation_result(None, status))
            return 0 if status.healthy_now else 1
        if arguments.paper_command == "record-equivalence":
            record = PaperEquivalenceStore(layout.execution).record(
                comparison_id=arguments.comparison_id,
                campaign_id=arguments.campaign_id,
                replay=load_action_plan(arguments.replay_plan, mode="replay"),
                shadow=load_action_plan(arguments.shadow_plan, mode="shadow"),
                paper_intent_keys=tuple(arguments.paper_intent),
                recorded_at=datetime.now(UTC),
            )
            _print(
                {
                    "comparison_id": record.comparison_id,
                    "campaign_id": record.campaign_id,
                    "equivalent": record.equivalent,
                    "reasons": record.reasons,
                    "replay_plan_fingerprint": record.replay.plan_fingerprint,
                    "shadow_plan_fingerprint": record.shadow.plan_fingerprint,
                    "paper_plan_fingerprint": record.paper.plan_fingerprint,
                    "record_fingerprint": record.record_fingerprint,
                    "broker_writes_allowed": False,
                }
            )
            return 0 if record.equivalent else 1
        if (arguments.wheel is None) != (arguments.manifest is None):
            raise ValueError("paper startup assessment requires both wheel and manifest")
        assessed_at = datetime.now(UTC)
        runtime_identity = None
        if arguments.wheel is not None:
            build = verify_attested_build(
                arguments.wheel, arguments.manifest, verified_at=assessed_at
            )
            runtime_identity = verify_installed_runtime(
                build, arguments.wheel, verified_at=datetime.now(UTC)
            )
        assessment = assess_paper_startup(
            layout.execution,
            settings,
            load_risk_limits(arguments.risk_config),
            authorization_id=arguments.authorization,
            assessed_at=datetime.now(UTC),
            runtime_identity=runtime_identity,
        )
        _print(
            {
                "ready": assessment.ready,
                "reasons": assessment.reasons,
                "authorization_id": assessment.authorization_id,
                "risk_configuration_fingerprint": assessment.risk_configuration_fingerprint,
                "activation_id": assessment.activation_id,
                "runtime_identity_fingerprint": assessment.runtime_identity_fingerprint,
                "emergency_disabled": assessment.emergency_disabled,
                "submission_unknown_count": assessment.submission_unknown_count,
                "unresolved_cancellation_count": assessment.unresolved_cancellation_count,
                "assessed_at": assessment.assessed_at.isoformat().replace("+00:00", "Z"),
            }
        )
        return 0 if assessment.ready else 1
    if arguments.command == "experiment":
        service = DatasetService(layout)
        registry = ExperimentRegistry(layout.experiments)
        if arguments.experiment_command == "create-campaign":
            _print(
                registry.create_campaign(arguments.campaign_id, arguments.name, arguments.budget)
            )
        elif arguments.experiment_command == "plan-training":
            plan = load_training_campaign_plan(arguments.spec)
            _print(registry.create_planned_campaign(plan.payload))
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
        elif arguments.experiment_command == "run-planned":
            spec = registry.get_planned_spec(arguments.experiment_id)
            run_cataloged_experiment(
                registry,
                service,
                spec,
                layout.reports,
                pre_registered=True,
            )
            _print(registry.get(arguments.experiment_id))
        elif arguments.experiment_command in {"run", "run-holdout"}:
            manifest = service.describe(arguments.dataset)
            if manifest.get("timeframe") != Timeframe.DAILY.value:
                raise ValueError("existing experiment commands accept daily datasets only")
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
        elif arguments.experiment_command == "review-holdout":
            _print(
                review_holdout(
                    registry,
                    arguments.experiment_id,
                    arguments.event_id,
                    arguments.reviewer,
                    arguments.reason,
                    load_qualification_proposal(arguments.proposal),
                )
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
            "broker_writes_require_exact_paper_opt_in": not settings.broker_writes_allowed
            or (settings.mode is TradingMode.PAPER and settings.paper_write_request is not None),
            "runtime_path_is_not_repository_root": settings.home != Path.cwd().resolve(),
            "research_credentials_present_or_not_required": settings.mode
            is not TradingMode.RESEARCH
            or all(os.environ.get(name) for name in ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY")),
        }
        checks["storage_writable"] = _storage_writable(layout)
        _print({"mode": settings.mode.value, "home": str(settings.home), "checks": checks})
        return 0 if all(checks.values()) else 1
    if arguments.command == "status":
        service = DatasetService(layout)
        _print(
            {
                "mode": settings.mode.value,
                "broker_writes_allowed": settings.broker_writes_allowed,
                "datasets": service.catalog.count(),
                "home": str(settings.home),
            }
        )
        return 0
    service = DatasetService(layout)
    if arguments.data_command == "import-fixture":
        imported = service.import_from(
            FixtureProvider(),
            fixture_symbols(),
            Timeframe.DAILY,
            fixture_request(),
            load_research_universe(),
        )
        _print(imported.__dict__)
        return 0
    if arguments.data_command == "import-intraday-fixture":
        timeframe = Timeframe(arguments.timeframe)
        imported = service.import_from(
            IntradayFixtureProvider(),
            intraday_fixture_symbols(),
            timeframe,
            intraday_fixture_request(timeframe),
            load_intraday_universe(timeframe),
        )
        _print(imported.__dict__)
        return 0
    if arguments.data_command == "import-alpaca":
        if settings.mode is not TradingMode.RESEARCH:
            raise ValueError("Alpaca data import requires TRADING_LAB_MODE=research")
        provider = AlpacaHistoricalProvider(
            os.environ.get("APCA_API_KEY_ID", ""), os.environ.get("APCA_API_SECRET_KEY", "")
        )
        timeframe = Timeframe(arguments.timeframe)
        symbols = fixture_symbols() if timeframe is Timeframe.DAILY else intraday_fixture_symbols()
        universe = (
            load_research_universe()
            if timeframe is Timeframe.DAILY
            else load_intraday_universe(timeframe)
        )
        imported = service.import_from(
            provider,
            symbols,
            timeframe,
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
        "mean-reversion": {"window"},
        "momentum": {"lookback"},
        "relative-strength": {"lookback", "rebalance_every", "selection_count"},
        "risk-managed-momentum": {"lookback", "volatility_window", "rebalance_every"},
        "strategic-allocation": {"rebalance_every"},
        "volatility-balanced": {"volatility_window", "rebalance_every"},
        "volatility-targeted": {"volatility_window"},
    }[name]
    unknown = parameters.keys() - allowed
    if unknown:
        raise ValueError(f"unsupported parameters for {name}: {', '.join(sorted(unknown))}")
    minimums = {
        "moving-average": {"window": 2},
        "mean-reversion": {"window": 2},
        "risk-managed-momentum": {"volatility_window": 2},
        "volatility-balanced": {"volatility_window": 2},
        "volatility-targeted": {"volatility_window": 2},
    }.get(name, {})
    for parameter, minimum in minimums.items():
        value = parameters.get(parameter)
        if value is not None and (not isinstance(value, int) or value < minimum):
            raise ValueError(f"{parameter} must be at least {minimum}")


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
        "mean-reversion": ("moving-average-mean-reversion", "mean-reversion"),
        "momentum": ("time-series-momentum", "momentum"),
        "relative-strength": ("relative-strength-portfolio", "portfolio-momentum"),
        "risk-managed-momentum": (
            "risk-managed-momentum-portfolio",
            "portfolio-momentum",
        ),
        "strategic-allocation": (
            "strategic-allocation-portfolio",
            "portfolio-allocation",
        ),
        "volatility-balanced": (
            "volatility-balanced-portfolio",
            "portfolio-allocation",
        ),
        "volatility-targeted": ("volatility-targeted-exposure", "volatility"),
    }[name]


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _paper_observation_reader(
    settings: Settings, account_id: str, allowed_symbols: tuple[str, ...]
) -> AlpacaPaperReader:
    if settings.mode is not TradingMode.PAPER:
        raise ConfigurationError("paper observation requires paper mode")
    return AlpacaPaperReader(
        os.environ.get("APCA_API_KEY_ID", ""),
        os.environ.get("APCA_API_SECRET_KEY", ""),
        account_id=account_id,
        allowed_symbols=frozenset(allowed_symbols),
    )


def _paper_observation_result(
    observation: PaperObservation | None, status: PaperObservationStatus
) -> dict[str, object]:
    return {
        "campaign_id": status.campaign_id,
        "observation_id": (observation.observation_id if observation is not None else None),
        "observation_status": (observation.status if observation is not None else None),
        "healthy_now": status.healthy_now,
        "campaign_complete": status.campaign_complete,
        "reasons": status.reasons,
        "success_count": status.success_count,
        "drift_count": status.drift_count,
        "failure_count": status.failure_count,
        "maximum_observed_gap_seconds": status.maximum_observed_gap_seconds,
        "latest_observed_at": status.latest_observed_at.isoformat().replace("+00:00", "Z"),
        "assessed_at": status.assessed_at.isoformat().replace("+00:00", "Z"),
        "broker_writes_allowed": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
