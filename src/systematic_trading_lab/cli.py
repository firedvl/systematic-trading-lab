"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from . import __version__
from .alpaca_paper import AlpacaPaperReader
from .backtesting import CostModel
from .campaign_specs import (
    build_planned_intraday_experiments,
    load_intraday_research_campaign_plan,
    load_training_campaign_plan,
    parse_intraday_research_campaign_plan,
)
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
from .execution import JournalIntegrityError
from .experiment_runner import (
    comparison_report,
    execution_model_version,
    run_cataloged_experiment,
    run_cataloged_intraday_experiment,
    run_holdout_experiment,
)
from .experiments import (
    ExperimentError,
    ExperimentRegistry,
    ExperimentSpec,
    ExperimentSplit,
    IntradayExperimentSpec,
)
from .fingerprints import canonicalize
from .intraday_campaigns import get_intraday_campaign_contract
from .intraday_qualification import (
    REVIEWED_POLICY_FINGERPRINT,
    IntradayQualificationPolicy,
    evaluate_registered_intraday_qualification,
    load_intraday_qualification_policy,
    write_intraday_qualification_evidence,
)
from .intraday_source_provenance import (
    IntradayExecutionSourceProvenanceError,
    assess_intraday_execution_source,
)
from .paper_continuation import PaperContinuationStore
from .paper_equivalence import PaperEquivalenceStore, load_action_plan
from .paper_observation import (
    PaperObservation,
    PaperObservationStatus,
    PaperObservationStore,
    record_production_observation,
)
from .paper_planning import write_action_plans
from .paper_startup import assess_paper_startup, initialize_paper_storage
from .paper_supervision import (
    observation_supervisor_lock,
    run_observation_loop,
    validate_observation_supervision,
    verify_observation_runtime,
)
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
from .risk_inputs import AlpacaRiskInputReader, RiskInputEvidenceStore
from .runtime_build import (
    RuntimeBuildAttestationIndeterminateError,
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
    observation_supervisor = paper.add_parser(
        "supervise-observation", help="run one restart-safe broker-read-only observation loop"
    )
    observation_supervisor.add_argument("campaign_id")
    observation_supervisor.add_argument("--runtime", type=Path, required=True)
    observation_supervisor.add_argument("--wheel", type=Path, required=True)
    observation_supervisor.add_argument("--manifest", type=Path, required=True)
    observation_supervisor.add_argument("--repository", type=Path, required=True)
    observation_supervisor.add_argument(
        "--risk-config", type=Path, default=Path("config/risk/alpaca-paper-v1.json")
    )
    observation_supervisor.add_argument("--interval-seconds", type=int, default=600)
    observation_supervisor.add_argument("--check", action="store_true")
    equivalence = paper.add_parser(
        "record-equivalence", help="record one replay, shadow, and paper action comparison"
    )
    equivalence.add_argument("campaign_id")
    equivalence.add_argument("comparison_id")
    equivalence.add_argument("--replay-plan", type=Path, required=True)
    equivalence.add_argument("--shadow-plan", type=Path, required=True)
    equivalence.add_argument("--paper-intent", action="append", required=True)
    continuation = paper.add_parser(
        "authorize-continuation",
        help="declare a short-lived continuation from settled strategy lineage",
    )
    continuation.add_argument("authorization_id")
    continuation.add_argument("--previous-authorization", required=True)
    continuation.add_argument(
        "--risk-config", type=Path, default=Path("config/risk/alpaca-paper-v1.json")
    )
    continuation.add_argument("--authorized-by", required=True)
    continuation.add_argument("--reason", required=True)
    continuation.add_argument("--authorized-at", type=_parse_utc, required=True)
    continuation.add_argument("--expires-at", type=_parse_utc, required=True)
    complete_continuation = paper.add_parser(
        "complete-continuation",
        help="collect fresh GET-only evidence and complete an append-only continuation",
    )
    complete_continuation.add_argument("authorization_id")
    complete_continuation.add_argument(
        "--risk-config", type=Path, default=Path("config/risk/alpaca-paper-v1.json")
    )
    complete_continuation.add_argument("--operator", required=True)
    complete_continuation.add_argument("--reason", required=True)
    plan = paper.add_parser(
        "plan", help="write deterministic broker-free replay and shadow action plans"
    )
    plan.add_argument("--authorization", required=True)
    plan.add_argument("--risk-config", type=Path, default=Path("config/risk/alpaca-paper-v1.json"))
    plan.add_argument("--replay-plan", type=Path, required=True)
    plan.add_argument("--shadow-plan", type=Path, required=True)
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
    intraday = experiment_commands.add_parser(
        "run-intraday",
        help="run one offline M5B training or validation baseline",
    )
    intraday.add_argument("experiment_id")
    intraday.add_argument("--campaign", required=True)
    intraday.add_argument(
        "--strategy",
        choices=("cash", "previous-bar-momentum", "moving-average-trend"),
        required=True,
    )
    intraday.add_argument("--candidate-ordinal", type=int, required=True)
    intraday.add_argument("--code-commit", required=True)
    intraday.add_argument("--dataset", required=True)
    intraday.add_argument("--timeframe", choices=("1m", "5m"), required=True)
    intraday.add_argument("--split", choices=("training", "validation"), required=True)
    intraday.add_argument("--start", required=True)
    intraday.add_argument("--end", required=True)
    intraday.add_argument("--reason", required=True)
    intraday.add_argument("--parent-candidate")
    intraday.add_argument("--slippage-bps", type=_decimal_argument, default=Decimal("5"))
    intraday.add_argument("--commission-bps", type=_decimal_argument, default=Decimal("1"))
    intraday.add_argument("--cost-version")
    intraday.add_argument("--fill-delay-bars", type=int, default=1)
    planned_run = experiment_commands.add_parser(
        "run-planned", help="run one pre-registered sealed training candidate"
    )
    planned_run.add_argument("experiment_id")
    plan_intraday = experiment_commands.add_parser(
        "plan-intraday",
        help="atomically seal all reservations in an intraday research plan",
    )
    plan_intraday.add_argument("--spec", type=Path, required=True)
    bind_intraday = experiment_commands.add_parser(
        "bind-intraday-datasets",
        help="validate and atomically bind all four datasets to a sealed intraday plan",
    )
    bind_intraday.add_argument("--campaign", required=True)
    bind_intraday.add_argument("--training", required=True)
    bind_intraday.add_argument("--validation-a", required=True)
    bind_intraday.add_argument("--validation-b", required=True)
    bind_intraday.add_argument("--validation-c", required=True)
    planned_intraday_run = experiment_commands.add_parser(
        "run-planned-intraday",
        help="run one dataset-bound candidate from a sealed intraday plan",
    )
    planned_intraday_run.add_argument("experiment_id")
    planned_intraday_run.add_argument("--source-review", required=True)
    planned_intraday_run.add_argument("--wheel", type=Path, required=True)
    planned_intraday_run.add_argument("--build-manifest", type=Path, required=True)
    planned_intraday_run.add_argument("--lockfile", type=Path, required=True)
    planned_intraday_run.add_argument("--dependency-wheelhouse", type=Path, required=True)
    assess_intraday_source = experiment_commands.add_parser(
        "assess-intraday-source",
        help="compare a clean campaign build with its reviewed foundation",
    )
    assess_intraday_source.add_argument("--campaign", required=True)
    assess_intraday_source.add_argument("--wheel", type=Path, required=True)
    assess_intraday_source.add_argument("--build-manifest", type=Path, required=True)
    assess_intraday_source.add_argument("--lockfile", type=Path, required=True)
    assess_intraday_source.add_argument("--dependency-wheelhouse", type=Path, required=True)
    record_intraday_source = experiment_commands.add_parser(
        "record-intraday-source",
        help="record one reviewed intraday campaign execution build",
    )
    record_intraday_source.add_argument("review_id")
    record_intraday_source.add_argument("--campaign", required=True)
    record_intraday_source.add_argument("--wheel", type=Path, required=True)
    record_intraday_source.add_argument("--build-manifest", type=Path, required=True)
    record_intraday_source.add_argument("--lockfile", type=Path, required=True)
    record_intraday_source.add_argument("--dependency-wheelhouse", type=Path, required=True)
    record_intraday_source.add_argument("--assessment-fingerprint", required=True)
    record_intraday_source.add_argument("--reviewer", required=True)
    record_intraday_source.add_argument("--reason", required=True)
    inspect_intraday_plan = experiment_commands.add_parser(
        "inspect-intraday-plan",
        help="validate and fingerprint an intraday research preregistration",
    )
    inspect_intraday_plan.add_argument("--spec", type=Path, required=True)
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
    assess_intraday = experiment_commands.add_parser(
        "assess-intraday",
        help="evaluate research-only M5B gates without holdout authority",
    )
    assess_intraday.add_argument("--base", required=True, help="base experiment ID")
    assess_intraday.add_argument("--policy", type=Path, required=True)
    assess_intraday.add_argument(
        "--higher-cost", action="append", default=[], help="repeatable NAME=EXPERIMENT_ID"
    )
    assess_intraday.add_argument(
        "--whole-bar-delay", action="append", default=[], help="repeatable NAME=EXPERIMENT_ID"
    )
    assess_intraday.add_argument(
        "--parameter-neighbor", action="append", default=[], help="repeatable NAME=EXPERIMENT_ID"
    )
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
    except RuntimeBuildAttestationIndeterminateError as error:
        print(f"error: {error}", file=sys.stderr)
        return os.EX_TEMPFAIL
    except (
        ConfigurationError,
        DatasetValidationError,
        ExperimentError,
        IntradayExecutionSourceProvenanceError,
        JournalIntegrityError,
        KeyError,
        OSError,
        RuntimeBuildVerificationError,
        sqlite3.DatabaseError,
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
        if arguments.paper_command == "authorize-continuation":
            if settings.mode is not TradingMode.PAPER:
                raise ConfigurationError("paper continuation requires paper mode")
            limits = load_risk_limits(arguments.risk_config)
            continuation_authorization, declaration = ReconciliationStore(
                layout.execution
            ).authorize_continuation(
                authorization_id=arguments.authorization_id,
                previous_authorization_id=arguments.previous_authorization,
                limits=limits,
                authorized_by=arguments.authorized_by,
                reason=arguments.reason,
                authorized_at=arguments.authorized_at,
                expires_at=arguments.expires_at,
            )
            _print(
                {
                    "authorization_id": continuation_authorization.authorization_id,
                    "authorization_fingerprint": (
                        continuation_authorization.authorization_fingerprint
                    ),
                    "previous_authorization_id": declaration.previous_authorization_id,
                    "declaration_fingerprint": declaration.declaration_fingerprint,
                    "authorized_at": continuation_authorization.authorized_at.isoformat().replace(
                        "+00:00", "Z"
                    ),
                    "expires_at": continuation_authorization.expires_at.isoformat().replace(
                        "+00:00", "Z"
                    ),
                    "continuation_complete": False,
                    "broker_writes_allowed": False,
                }
            )
            return 0
        if arguments.paper_command == "complete-continuation":
            limits = load_risk_limits(arguments.risk_config)
            continuation_store = PaperContinuationStore(layout.execution)
            try:
                existing = continuation_store.get_handoff(arguments.authorization_id)
                handoff = continuation_store.complete_continuation(
                    authorization_id=arguments.authorization_id,
                    portfolio_snapshot_id=existing.current_snapshot_id,
                    risk_input_evidence_id=existing.current_risk_input_evidence_id,
                    limits=limits,
                    operator=arguments.operator,
                    reason=arguments.reason,
                    completed_at=existing.completed_at,
                )
            except KeyError:
                snapshot = _paper_observation_reader(
                    settings, limits.account_id, limits.allowed_symbols
                ).record_portfolio(ReconciliationStore(layout.execution))
                risk_input = AlpacaRiskInputReader(
                    os.environ.get("APCA_API_KEY_ID", ""),
                    os.environ.get("APCA_API_SECRET_KEY", ""),
                    limits=limits,
                ).record(
                    RiskInputEvidenceStore(layout.execution),
                    portfolio_snapshot_id=snapshot.snapshot_id,
                    authorization_id=arguments.authorization_id,
                )
                handoff = continuation_store.complete_continuation(
                    authorization_id=arguments.authorization_id,
                    portfolio_snapshot_id=snapshot.snapshot_id,
                    risk_input_evidence_id=risk_input.evidence_id,
                    limits=limits,
                    operator=arguments.operator,
                    reason=arguments.reason,
                    completed_at=datetime.now(UTC),
                )
            _print(
                {
                    "authorization_id": handoff.authorization_id,
                    "previous_authorization_id": handoff.previous_authorization_id,
                    "handoff_fingerprint": handoff.handoff_fingerprint,
                    "reconciliation_evidence_id": handoff.reconciliation_evidence_id,
                    "settlement_proof_id": handoff.settlement_proof_id,
                    "strategy_equity_checkpoint_id": handoff.strategy_equity_checkpoint_id,
                    "positions": [
                        {"symbol": item.symbol, "quantity": item.quantity}
                        for item in handoff.positions
                    ],
                    "strategy_equity": str(handoff.strategy_equity),
                    "peak_equity": str(handoff.peak_equity),
                    "strategy_drawdown": str(handoff.strategy_drawdown),
                    "completed_at": handoff.completed_at.isoformat().replace("+00:00", "Z"),
                    "broker_writes_allowed": False,
                }
            )
            return 0
        if arguments.paper_command == "plan":
            limits = load_risk_limits(arguments.risk_config)
            present_plan = PaperContinuationStore(layout.execution).plan_strategic_allocation(
                authorization_id=arguments.authorization,
                limits=limits,
                planned_at=datetime.now(UTC),
            )
            replay_path, shadow_path = write_action_plans(
                present_plan,
                replay_path=arguments.replay_plan,
                shadow_path=arguments.shadow_plan,
            )
            _print(
                {
                    "authorization_id": present_plan.authorization_id,
                    "candidate_id": present_plan.candidate_id,
                    "strategy_id": present_plan.strategy_id,
                    "strategy_version": present_plan.strategy_version,
                    "root_exchange_session": present_plan.root_exchange_session,
                    "current_exchange_session": present_plan.current_exchange_session,
                    "session_count": present_plan.session_count,
                    "rebalance_every": present_plan.rebalance_every,
                    "rebalance_due": present_plan.rebalance_due,
                    "trade_required": present_plan.trade_required,
                    "source_data_fingerprint": present_plan.source_data_fingerprint,
                    "source_state_fingerprint": present_plan.source_state_fingerprint,
                    "market_state_fingerprint": present_plan.market_state_fingerprint,
                    "configuration_fingerprint": present_plan.configuration_fingerprint,
                    "plan_fingerprint": present_plan.plan_fingerprint,
                    "current_positions": [
                        canonicalize(item) for item in present_plan.current_positions
                    ],
                    "targets": [canonicalize(item) for item in present_plan.targets],
                    "deltas": [canonicalize(item) for item in present_plan.deltas],
                    "replay_plan": str(replay_path.resolve()),
                    "replay_plan_fingerprint": present_plan.replay.plan_fingerprint,
                    "shadow_plan": str(shadow_path.resolve()),
                    "shadow_plan_fingerprint": present_plan.shadow.plan_fingerprint,
                    "authority": dict(present_plan.authority),
                }
            )
            return 0
        if arguments.paper_command == "start-observation":
            with observation_supervisor_lock(settings.home):
                limits = load_risk_limits(arguments.risk_config)
                reader = _paper_observation_reader(
                    settings, limits.account_id, limits.allowed_symbols
                )
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
            with observation_supervisor_lock(settings.home):
                limits = load_risk_limits(arguments.risk_config)
                store = PaperObservationStore(layout.execution)
                observation = record_production_observation(
                    store,
                    _paper_observation_reader(settings, limits.account_id, limits.allowed_symbols),
                    campaign_id=arguments.campaign_id,
                )
                status = store.assess(arguments.campaign_id, assessed_at=datetime.now(UTC))
            _print(_paper_observation_result(observation, status))
            return 0 if status.healthy_now and status.campaign_passed is not False else 1
        if arguments.paper_command == "assess-observation":
            status = PaperObservationStore(layout.execution).assess(
                arguments.campaign_id, assessed_at=datetime.now(UTC)
            )
            _print(_paper_observation_result(None, status))
            return 0 if status.healthy_now and status.campaign_passed is not False else 1
        if arguments.paper_command == "supervise-observation":
            build_commit = validate_observation_supervision(
                settings,
                campaign_id=arguments.campaign_id,
                interval_seconds=arguments.interval_seconds,
                repository=arguments.repository,
                runtime=arguments.runtime,
                wheel=arguments.wheel,
                manifest=arguments.manifest,
                risk_config=arguments.risk_config,
            )
            supervisor_identity = verify_observation_runtime(
                arguments.wheel, arguments.manifest, expected_commit=build_commit
            )
            limits = load_risk_limits(arguments.risk_config)
            reader = _paper_observation_reader(settings, limits.account_id, limits.allowed_symbols)
            if arguments.check:
                with observation_supervisor_lock(settings.home):
                    _print(
                        {
                            "campaign_id": arguments.campaign_id,
                            "interval_seconds": arguments.interval_seconds,
                            "runtime_source_commit": supervisor_identity.source_commit,
                            "runtime_identity_fingerprint": (
                                supervisor_identity.identity_fingerprint
                            ),
                            "broker_writes_allowed": False,
                        }
                    )
                return 0
            with observation_supervisor_lock(settings.home):
                store = PaperObservationStore(layout.execution)

                def assess() -> PaperObservationStatus:
                    return store.assess(arguments.campaign_id, assessed_at=datetime.now(UTC))

                def record_sample() -> tuple[PaperObservation, PaperObservationStatus]:
                    observation = record_production_observation(
                        store, reader, campaign_id=arguments.campaign_id
                    )
                    return observation, assess()

                status = run_observation_loop(
                    interval_seconds=arguments.interval_seconds,
                    assess=assess,
                    record=record_sample,
                    emit=lambda observation, status: _print(
                        _paper_observation_result(observation, status)
                    ),
                )
            print("campaign complete; observation supervisor exiting")
            return 0
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
        if arguments.experiment_command == "inspect-intraday-plan":
            intraday_plan = load_intraday_research_campaign_plan(arguments.spec)
            _print(
                {
                    "campaign_id": intraday_plan.campaign_id,
                    "status": "preregistered",
                    "plan_fingerprint": intraday_plan.plan_fingerprint,
                    "search_budget": intraday_plan.search_budget,
                    "reserved_candidate_ordinals": [
                        candidate.candidate_ordinal for candidate in intraday_plan.candidates
                    ],
                    "protected_holdout_authority": False,
                    "paper_authority": False,
                    "broker_write_authority": False,
                }
            )
            return 0
        if arguments.experiment_command == "assess-intraday-source":
            get_intraday_campaign_contract(arguments.campaign)
            source_assessment = assess_intraday_execution_source(
                arguments.wheel,
                arguments.build_manifest,
                arguments.lockfile,
                arguments.dependency_wheelhouse,
                campaign_id=arguments.campaign,
            )
            payload = canonicalize(source_assessment)
            assert isinstance(payload, dict)
            _print(
                {
                    **payload,
                    "assessment_fingerprint": source_assessment.assessment_fingerprint,
                    "protected_holdout_authority": False,
                    "paper_authority": False,
                    "broker_write_authority": False,
                    "live_authority": False,
                }
            )
            return 0 if source_assessment.surface_comparison.equivalent else 1
        service = DatasetService(layout)
        registry = ExperimentRegistry(layout.experiments)
        if arguments.experiment_command == "create-campaign":
            _print(
                registry.create_campaign(arguments.campaign_id, arguments.name, arguments.budget)
            )
        elif arguments.experiment_command == "plan-training":
            plan = load_training_campaign_plan(arguments.spec)
            _print(registry.create_planned_campaign(plan.payload))
        elif arguments.experiment_command == "plan-intraday":
            intraday_plan = load_intraday_research_campaign_plan(arguments.spec)
            _print(registry.create_planned_intraday_campaign(intraday_plan.payload))
        elif arguments.experiment_command == "record-intraday-source":
            review = registry.record_intraday_execution_source_review(
                arguments.review_id,
                arguments.wheel,
                arguments.build_manifest,
                arguments.lockfile,
                arguments.dependency_wheelhouse,
                arguments.assessment_fingerprint,
                arguments.reviewer,
                arguments.reason,
                campaign_id=arguments.campaign,
            )
            _print(
                {
                    "review": review,
                    "protected_holdout_authority": False,
                    "paper_authority": False,
                    "broker_write_authority": False,
                    "live_authority": False,
                }
            )
        elif arguments.experiment_command == "bind-intraday-datasets":
            stored_plan = registry.get_campaign_plan(arguments.campaign)
            plan_json = stored_plan["plan_json"]
            if not isinstance(plan_json, Mapping):
                raise ExperimentError("stored intraday campaign plan is malformed")
            intraday_plan = parse_intraday_research_campaign_plan(plan_json)
            if stored_plan["plan_fingerprint"] != intraday_plan.plan_fingerprint:
                raise ExperimentError("stored intraday campaign plan fingerprint differs")
            dataset_ids = {
                "training": arguments.training,
                "validation-a": arguments.validation_a,
                "validation-b": arguments.validation_b,
                "validation-c": arguments.validation_c,
            }
            validations = {
                role: service.validate(dataset_id) for role, dataset_id in dataset_ids.items()
            }
            invalid = [role for role, result in validations.items() if not result["valid"]]
            if invalid:
                raise DatasetValidationError(
                    "planned intraday dataset integrity validation failed: " + ", ".join(invalid)
                )
            manifests = {
                role: service.describe(dataset_id) for role, dataset_id in dataset_ids.items()
            }
            specs = build_planned_intraday_experiments(intraday_plan, manifests)
            registry.bind_planned_intraday_experiments(specs)
            _print(
                {
                    "campaign_id": intraday_plan.campaign_id,
                    "plan_fingerprint": intraday_plan.plan_fingerprint,
                    "bound_candidates": len(specs),
                    "dataset_ids": dataset_ids,
                }
            )
        elif arguments.experiment_command == "run-planned-intraday":
            intraday_spec = registry.get_planned_intraday_spec(arguments.experiment_id)
            run_cataloged_intraday_experiment(
                registry,
                service,
                intraday_spec,
                layout.reports,
                pre_registered=True,
                execution_source_review_id=arguments.source_review,
                execution_source_wheel=arguments.wheel,
                execution_source_manifest=arguments.build_manifest,
                execution_source_lockfile=arguments.lockfile,
                execution_source_dependency_wheelhouse=arguments.dependency_wheelhouse,
            )
            _print(registry.get(arguments.experiment_id))
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
        elif arguments.experiment_command == "run-intraday":
            manifest = service.describe(arguments.dataset)
            identity = manifest["identity"]
            timeframe = Timeframe(arguments.timeframe)
            if manifest.get("timeframe") != timeframe.value:
                raise ValueError("declared intraday timeframe does not match the dataset")
            cost_model = _cost_model(arguments)
            strategy_id, strategy_family, parameters = _intraday_strategy_contract(
                arguments.strategy
            )
            search_budget = registry.get_campaign(arguments.campaign)["search_budget"]
            if not isinstance(search_budget, int):
                raise ExperimentError("campaign search budget is invalid")
            intraday_spec = IntradayExperimentSpec(
                experiment_id=arguments.experiment_id,
                campaign_id=arguments.campaign,
                search_budget=search_budget,
                candidate_ordinal=arguments.candidate_ordinal,
                strategy_id=strategy_id,
                strategy_version="1",
                strategy_family=strategy_family,
                code_commit=arguments.code_commit,
                dataset_id=identity["dataset_id"],
                dataset_fingerprint=identity["fingerprint"],
                universe_id=manifest["universe_id"],
                universe_fingerprint=manifest["universe_fingerprint"],
                parameters=parameters,
                timeframe=timeframe.value,
                session_policy_version="XNYS-regular-session-flat-v1",
                bar_timestamp_semantics_version="bar-open-utc-v1",
                session_return_policy_version="XNYS-session-close-equity-v1",
                benchmark_policy_version="cash-and-continuous-underlying-v1",
                cost_model_version=cost_model.version,
                slippage_bps=cost_model.slippage_bps,
                commission_bps=cost_model.commission_bps,
                execution_model_version="deterministic-next-bar-open-v1",
                earliest_fill_semantics="completed-bar-next-bar-open-v1",
                execution_delay_bars=arguments.fill_delay_bars,
                split=ExperimentSplit(arguments.split),
                start_timestamp=_parse_utc(arguments.start),
                end_timestamp=_parse_utc(arguments.end),
                random_seed=0,
                creation_reason=arguments.reason,
                parent_candidate=arguments.parent_candidate,
            )
            run_cataloged_intraday_experiment(
                registry,
                service,
                intraday_spec,
                layout.reports,
                cost_model=cost_model,
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
        elif arguments.experiment_command == "assess-intraday":
            evidence = evaluate_registered_intraday_qualification(
                registry,
                _load_reviewed_intraday_policy(arguments.policy),
                arguments.base,
                _parse_named_intraday_experiments(arguments.higher_cost),
                _parse_named_intraday_experiments(arguments.whole_bar_delay),
                _parse_named_intraday_experiments(arguments.parameter_neighbor),
            )
            evidence_path = write_intraday_qualification_evidence(layout.reports, evidence)
            _print(
                {
                    "state": evidence["state"],
                    "candidate_id": evidence["candidate_id"],
                    "report": str(evidence_path),
                    "report_fingerprint": evidence["report_fingerprint"],
                    "holdout_authority": False,
                    "broker_write_authority": False,
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


def _parse_named_intraday_experiments(values: Sequence[str]) -> dict[str, str]:
    experiments: dict[str, str] = {}
    for value in values:
        name, separator, experiment_id = value.partition("=")
        if not separator or not name or not experiment_id or name in experiments:
            raise ValueError("intraday evidence must use unique NAME=EXPERIMENT_ID pairs")
        experiments[name] = experiment_id
    return experiments


def _load_reviewed_intraday_policy(path: Path) -> IntradayQualificationPolicy:
    policy = load_intraday_qualification_policy(path)
    if policy.fingerprint != REVIEWED_POLICY_FINGERPRINT:
        raise ValueError("intraday assessment policy differs from the committed reviewed policy")
    return policy


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


def _intraday_strategy_contract(name: str) -> tuple[str, str, dict[str, object]]:
    """Fixed engineering baselines; callers cannot tune them in M5B."""

    contracts: dict[str, tuple[str, str, dict[str, object]]] = {
        "cash": ("intraday-cash", "intraday-cash-baseline", {}),
        "previous-bar-momentum": (
            "intraday-previous-bar-momentum",
            "intraday-directional-momentum",
            {"lookback": 1},
        ),
        "moving-average-trend": (
            "intraday-moving-average-trend",
            "intraday-trend",
            {"window": 12},
        ),
    }
    return contracts[name]


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
        "continuity_held": status.continuity_held,
        "campaign_passed": status.campaign_passed,
        "reasons": status.reasons,
        "campaign_reasons": status.campaign_reasons,
        "success_count": status.success_count,
        "drift_count": status.drift_count,
        "failure_count": status.failure_count,
        "maximum_gap_seconds": status.maximum_gap_seconds,
        "maximum_observed_gap_seconds": status.maximum_observed_gap_seconds,
        "latest_observed_at": status.latest_observed_at.isoformat().replace("+00:00", "Z"),
        "assessed_at": status.assessed_at.isoformat().replace("+00:00", "Z"),
        "broker_writes_allowed": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
