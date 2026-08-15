"""Fast, non-authoritative daily strategy research."""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import product
from pathlib import Path

from .backtesting import BacktestResult, CostModel
from .config import non_broker_subprocess_environment
from .fingerprints import fingerprint
from .rapid_004 import RAPID_004_PROGRAM_ID, bind_rapid_004_dataset
from .rapid_data import ResearchDataset, parse_utc, resolve_research_dataset
from .rapid_store import RapidResearchStore, rapid_authority
from .strategy_registry import (
    get_strategy_definition,
    run_registered_strategy,
    strategy_names,
    validate_strategy_parameters,
)


@dataclass(frozen=True)
class ResearchInputs:
    dataset_id: str
    strategy: str
    parameters: Mapping[str, int]
    start: datetime | None = None
    end: datetime | None = None
    initial_cash: Decimal = Decimal("100000")
    slippage_bps: Decimal = Decimal("5")
    commission_bps: Decimal = Decimal("1")
    fill_delay_bars: int = 1
    campaign_id: str | None = None

    def __post_init__(self) -> None:
        if self.initial_cash <= 0:
            raise ValueError("initial cash must be positive")
        if self.slippage_bps < 0 or self.commission_bps < 0:
            raise ValueError("research costs must not be negative")
        if self.fill_delay_bars < 1:
            raise ValueError("fill delay must be at least one bar")
        if self.campaign_id not in {None, RAPID_004_PROGRAM_ID}:
            raise ValueError("unsupported Rapid Research campaign")


def list_strategies() -> list[dict[str, object]]:
    return [
        {
            "name": name,
            "strategy_id": definition.strategy_id,
            "version": "1",
            "family": definition.family,
            "description": definition.description,
            "parameters": [
                {
                    "name": parameter.name,
                    "default": parameter.default,
                    "minimum": parameter.minimum,
                }
                for parameter in definition.parameters
            ],
        }
        for name in strategy_names()
        for definition in (get_strategy_definition(name),)
    ]


def run_backtest(
    root: Path,
    store: RapidResearchStore,
    inputs: ResearchInputs,
    *,
    run_type: str = "backtest",
    group_id: str | None = None,
    parent_run_id: str | None = None,
    exploratory_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    dataset, campaign = _resolve_inputs_dataset(root, store, inputs)
    parameters = validate_strategy_parameters(inputs.strategy, inputs.parameters)
    specification = _specification(
        dataset,
        inputs,
        parameters,
        run_type,
        group_id=group_id,
        parent_run_id=parent_run_id,
        exploratory_context=exploratory_context,
        campaign=campaign,
    )
    return _execute(store, specification, dataset, inputs, parameters)


def run_sweep(
    root: Path,
    store: RapidResearchStore,
    inputs: ResearchInputs,
    grid: Mapping[str, Sequence[int]],
    maximum_runs: int,
) -> dict[str, object]:
    configurations = parameter_configurations(grid)
    if maximum_runs < 1:
        raise ValueError("maximum sweep size must be positive")
    if len(configurations) > maximum_runs:
        raise ValueError(
            f"parameter sweep has {len(configurations)} configurations; cap is {maximum_runs}"
        )
    configurations = tuple(
        validate_strategy_parameters(inputs.strategy, configuration)
        for configuration in configurations
    )
    dataset, campaign = _resolve_inputs_dataset(root, store, inputs)
    group_identity = {
        "inputs": _inputs_identity(inputs),
        "grid": grid,
        "maximum_runs": maximum_runs,
        "code": _code_identity(),
    }
    group_id = f"rrg-{fingerprint(group_identity)[:20]}"
    runs: list[dict[str, object]] = []
    for ordinal, parameters in enumerate(configurations, start=1):
        selected = ResearchInputs(
            inputs.dataset_id,
            inputs.strategy,
            parameters,
            inputs.start,
            inputs.end,
            inputs.initial_cash,
            inputs.slippage_bps,
            inputs.commission_bps,
            inputs.fill_delay_bars,
            inputs.campaign_id,
        )
        specification = _specification(
            dataset,
            selected,
            parameters,
            "sweep",
            group_id=group_id,
            exploratory_context={
                "classification": "exploratory-in-sample-parameter-sweep",
                "configuration_ordinal": ordinal,
                "configuration_count": len(configurations),
                "maximum_search_size": maximum_runs,
            },
            campaign=campaign,
        )
        runs.append(_execute(store, specification, dataset, selected, parameters))
    return {
        "group_id": group_id,
        "configuration_count": len(configurations),
        "runs": [_compact_run(run) for run in runs],
        "exploratory_in_sample": True,
        "next_step": "Evaluate selected configurations with walk-forward or untouched data.",
        "authority": rapid_authority(),
    }


def run_walk_forward(
    root: Path,
    store: RapidResearchStore,
    inputs: ResearchInputs,
    training_window: int,
    test_window: int,
    step_size: int,
    *,
    expanding: bool,
) -> dict[str, object]:
    if training_window < 1 or test_window < 1 or step_size < test_window:
        raise ValueError(
            "walk-forward windows must be positive and step size must cover the test window"
        )
    dataset, campaign = _resolve_inputs_dataset(root, store, inputs)
    parameters = validate_strategy_parameters(inputs.strategy, inputs.parameters)
    sessions = tuple(sorted({bar.timestamp for bar in dataset.bars}))
    folds: list[tuple[int, int, int, int]] = []
    test_start = training_window
    while test_start + test_window <= len(sessions):
        training_index_start = 0 if expanding else test_start - training_window
        folds.append(
            (
                training_index_start,
                test_start - 1,
                test_start,
                test_start + test_window - 1,
            )
        )
        test_start += step_size
    if not folds:
        raise ValueError("dataset is too short for the requested walk-forward windows")
    group_context = {
        "inputs": _inputs_identity(inputs),
        "training_window": training_window,
        "test_window": test_window,
        "step_size": step_size,
        "training_mode": "expanding" if expanding else "rolling",
        "code": _code_identity(),
    }
    group_id = f"rrg-{fingerprint(group_context)[:20]}"
    parent_dataset = ResearchDataset(
        dataset.dataset_id,
        dataset.dataset_fingerprint,
        dataset.source,
        dataset.timeframe,
        sessions[folds[0][2]],
        sessions[folds[-1][3]],
        dataset.symbols,
        dataset.bars,
    )
    parent_spec = _specification(
        parent_dataset,
        inputs,
        parameters,
        "walk-forward",
        group_id=group_id,
        exploratory_context={
            "training_window": training_window,
            "test_window": test_window,
            "step_size": step_size,
            "training_mode": "expanding" if expanding else "rolling",
            "fold_count": len(folds),
        },
        campaign=campaign,
    )
    parent = store.begin_run(parent_spec)
    if parent["status"] != "pending":
        stored_folds = (
            run
            for run in reversed(store.list_runs(group_id=group_id))
            if run["run_type"] == "walk-forward-fold"
        )
        return {
            "run": _compact_run(parent),
            "folds": [_compact_run(run) for run in stored_folds],
            "authority": rapid_authority(),
        }
    fold_records: list[dict[str, object]] = []
    for index, (train_index, train_end_index, test_index, test_end_index) in enumerate(
        folds, start=1
    ):
        training_start = sessions[train_index]
        training_end = sessions[train_end_index]
        validation_start = sessions[test_index]
        validation_end = sessions[test_end_index]
        selected_bars = tuple(
            bar for bar in dataset.bars if training_start <= bar.timestamp <= validation_end
        )
        fold_dataset = ResearchDataset(
            dataset.dataset_id,
            dataset.dataset_fingerprint,
            dataset.source,
            dataset.timeframe,
            validation_start,
            validation_end,
            dataset.symbols,
            selected_bars,
        )
        fold_spec = _specification(
            fold_dataset,
            inputs,
            parameters,
            "walk-forward-fold",
            group_id=group_id,
            parent_run_id=str(parent["run_id"]),
            fold={
                "index": index,
                "training_start": training_start,
                "training_end": training_end,
                "validation_start": validation_start,
                "validation_end": validation_end,
                "training_mode": "expanding" if expanding else "rolling",
            },
            campaign=campaign,
        )
        fold_records.append(
            _execute(
                store,
                fold_spec,
                fold_dataset,
                inputs,
                parameters,
                trade_start=validation_start,
            )
        )
    aggregate = _walk_forward_metrics(fold_records)
    details = {
        "folds": [_compact_run(record) for record in fold_records],
        "fold_metrics": [record["metrics"] for record in fold_records],
        "score": None,
    }
    failed = [record for record in fold_records if record["status"] == "failed"]
    parent = store.finish_run(
        str(parent["run_id"]),
        aggregate,
        details,
        error=(f"{len(failed)} walk-forward folds failed" if failed else None),
    )
    return {
        "run": _compact_run(parent),
        "folds": [_compact_run(record) for record in fold_records],
        "authority": rapid_authority(),
    }


def run_stress(
    root: Path,
    store: RapidResearchStore,
    run_id: str,
    slippage_bps: Decimal,
    commission_bps: Decimal,
    fill_delay_bars: int,
) -> dict[str, object]:
    parent = store.get_run(run_id)
    if parent["status"] != "completed" or parent["run_type"] in {
        "walk-forward",
        "walk-forward-fold",
    }:
        raise ValueError("stress requires one completed non-walk-forward Rapid Research run")
    parameters = {
        str(name): _integer(value, "strategy parameter")
        for name, value in _mapping(parent["parameters"]).items()
    }
    source_specification = _mapping(parent["specification"])
    source_costs = _mapping(source_specification["costs"])
    source_execution = _mapping(source_specification["execution"])
    source_slippage = Decimal(str(source_costs["slippage_bps"]))
    source_commission = Decimal(str(source_costs["commission_bps"]))
    source_delay = _integer(source_execution["fill_delay_bars"], "fill delay")
    if (
        slippage_bps < source_slippage
        or commission_bps < source_commission
        or fill_delay_bars < source_delay
        or (slippage_bps, commission_bps, fill_delay_bars)
        == (source_slippage, source_commission, source_delay)
    ):
        raise ValueError("stress assumptions must be strictly worse than the source run")
    inputs = ResearchInputs(
        str(parent["dataset_id"]),
        str(parent["strategy_name"]),
        parameters,
        parse_utc(str(parent["start_timestamp"])),
        parse_utc(str(parent["end_timestamp"])),
        Decimal(str(source_specification["initial_cash"])),
        slippage_bps,
        commission_bps,
        fill_delay_bars,
        (
            str(_mapping(source_specification["campaign"])["id"])
            if source_specification.get("campaign") is not None
            else None
        ),
    )
    group_id = f"rrg-{fingerprint({'parent': run_id, 'inputs': _inputs_identity(inputs)})[:20]}"
    stressed = run_backtest(
        root,
        store,
        inputs,
        run_type="stress",
        group_id=group_id,
        parent_run_id=run_id,
        exploratory_context={
            "classification": "execution-assumption-stress",
            "source_run_id": run_id,
        },
    )
    return {
        "source": _compact_run(parent),
        "stress": _compact_run(stressed),
        "survives_worse_execution": _stress_survival(parent, stressed),
        "authority": rapid_authority(),
    }


def compare_runs(store: RapidResearchStore, run_ids: Sequence[str]) -> dict[str, object]:
    if not run_ids:
        raise ValueError("comparison requires at least one run ID")
    runs = [store.get_run(run_id) for run_id in run_ids]
    return {
        "runs": [_compact_run(run) for run in runs],
        "score": None,
        "authority": rapid_authority(),
    }


def parse_parameters(values: Sequence[str]) -> dict[str, int]:
    parameters: dict[str, int] = {}
    for value in values:
        name, separator, raw = value.partition("=")
        if not separator or not name or not raw or name in parameters:
            raise ValueError("parameters must be unique NAME=INTEGER pairs")
        try:
            parameters[name] = int(raw)
        except ValueError as error:
            raise ValueError("parameters must be unique NAME=INTEGER pairs") from error
    return parameters


def parse_parameter_grid(values: Sequence[str]) -> dict[str, tuple[int, ...]]:
    grid: dict[str, tuple[int, ...]] = {}
    for value in values:
        name, separator, raw = value.partition("=")
        if not separator or not name or not raw or name in grid:
            raise ValueError("sweep parameters must be unique NAME=INTEGER[,INTEGER...] pairs")
        try:
            selected = tuple(int(item) for item in raw.split(","))
        except ValueError as error:
            raise ValueError(
                "sweep parameters must be unique NAME=INTEGER[,INTEGER...] pairs"
            ) from error
        if not selected or len(set(selected)) != len(selected):
            raise ValueError("sweep parameter values must be nonempty and unique")
        grid[name] = selected
    if not grid:
        raise ValueError("sweep requires at least one parameter grid")
    return grid


def parameter_configurations(grid: Mapping[str, Sequence[int]]) -> tuple[dict[str, int], ...]:
    names = tuple(sorted(grid))
    return tuple(
        dict(zip(names, values, strict=True))
        for values in product(*(tuple(grid[name]) for name in names))
    )


def _inputs_identity(inputs: ResearchInputs) -> dict[str, object]:
    identity: dict[str, object] = {
        "dataset_id": inputs.dataset_id,
        "strategy": inputs.strategy,
        "parameters": inputs.parameters,
        "start": inputs.start,
        "end": inputs.end,
        "initial_cash": inputs.initial_cash,
        "slippage_bps": inputs.slippage_bps,
        "commission_bps": inputs.commission_bps,
        "fill_delay_bars": inputs.fill_delay_bars,
    }
    if inputs.campaign_id is not None:
        identity["campaign_id"] = inputs.campaign_id
    return identity


def _resolve_inputs_dataset(
    root: Path, store: RapidResearchStore, inputs: ResearchInputs
) -> tuple[ResearchDataset, Mapping[str, object] | None]:
    campaign = (
        bind_rapid_004_dataset(root, store, inputs.dataset_id)
        if inputs.campaign_id == RAPID_004_PROGRAM_ID
        else None
    )
    return (
        resolve_research_dataset(
            root,
            store,
            inputs.dataset_id,
            inputs.start,
            inputs.end,
            verify_full_cataloged_dataset=campaign is not None,
        ),
        campaign,
    )


def _execute(
    store: RapidResearchStore,
    specification: Mapping[str, object],
    dataset: ResearchDataset,
    inputs: ResearchInputs,
    parameters: Mapping[str, int],
    *,
    trade_start: datetime | None = None,
) -> dict[str, object]:
    record = store.begin_run(specification)
    if record["status"] != "pending":
        return record
    try:
        result = run_registered_strategy(
            inputs.strategy,
            dataset.bars,
            inputs.initial_cash,
            _cost_model(inputs),
            parameters,
            inputs.fill_delay_bars,
            trade_start,
        )
        metrics = research_metrics(
            result,
            evaluation_start=dataset.start_timestamp,
            evaluation_end=dataset.end_timestamp,
        )
        return store.finish_run(
            str(record["run_id"]),
            metrics,
            {
                "result_artifact_fingerprint": result.artifact_fingerprint,
                "input_bar_count": len(dataset.bars),
                "symbols": dataset.symbols,
                "net_of_costs": True,
            },
        )
    except Exception as error:
        return store.finish_run(
            str(record["run_id"]),
            None,
            {"input_bar_count": len(dataset.bars), "symbols": dataset.symbols},
            error=f"{type(error).__name__}: {error}",
        )


def research_metrics(
    result: BacktestResult,
    *,
    evaluation_start: datetime,
    evaluation_end: datetime,
) -> dict[str, object]:
    session_points = {
        point.timestamp: point
        for point in result.equity_curve
        if evaluation_start <= point.timestamp <= evaluation_end
    }
    points = tuple(session_points[timestamp] for timestamp in sorted(session_points))
    if not points:
        raise ValueError("research evaluation contains no sessions")
    previous = result.initial_cash
    returns: list[Decimal] = []
    profits: list[Decimal] = []
    exposures: list[Decimal] = []
    peak = result.initial_cash
    max_drawdown = Decimal("0")
    for point in points:
        returns.append(point.equity / previous - Decimal("1"))
        profits.append(point.equity - previous)
        previous = point.equity
        peak = max(peak, point.equity)
        max_drawdown = max(max_drawdown, (peak - point.equity) / peak if peak else Decimal("0"))
        exposures.append(
            max(Decimal("0"), (point.equity - point.cash) / point.equity)
            if point.equity
            else Decimal("0")
        )
    mean = sum(returns, Decimal("0")) / Decimal(len(returns))
    variance = (
        sum(((value - mean) ** 2 for value in returns), Decimal("0")) / Decimal(len(returns) - 1)
        if len(returns) > 1
        else Decimal("0")
    )
    daily_volatility = variance.sqrt()
    downside = (
        sum((min(value, Decimal("0")) ** 2 for value in returns), Decimal("0"))
        / Decimal(len(returns))
    ).sqrt()
    selected_trades = tuple(
        trade
        for trade in result.trades
        if evaluation_start <= trade.fill_timestamp <= evaluation_end
    )
    commissions = sum((trade.commission for trade in selected_trades), Decimal("0"))
    slippage = sum((trade.slippage for trade in selected_trades), Decimal("0"))
    positive = tuple(profit for profit in profits if profit > 0)
    negative = tuple(profit for profit in profits if profit < 0)
    final_equity = points[-1].equity
    total_return = final_equity / result.initial_cash - Decimal("1")
    annualized_return = (
        (Decimal("1") + total_return) ** (Decimal("252") / Decimal(len(points))) - Decimal("1")
        if len(points) > 1 and total_return > Decimal("-1")
        else None
    )
    total_positive = sum(positive, Decimal("0"))
    return {
        "total_return": total_return,
        "annualized_return": annualized_return,
        "max_drawdown": max_drawdown,
        "annualized_volatility": daily_volatility * Decimal("252").sqrt(),
        "sharpe_ratio": (
            mean / daily_volatility * Decimal("252").sqrt() if daily_volatility else None
        ),
        "sortino_ratio": mean / downside * Decimal("252").sqrt() if downside else None,
        "turnover": sum((trade.gross_notional for trade in selected_trades), Decimal("0"))
        / result.initial_cash,
        "cost_paid": commissions + slippage,
        "commission_paid": commissions,
        "slippage_paid": slippage,
        "trade_count": len(selected_trades),
        "session_win_rate": Decimal(len(positive)) / Decimal(len(profits)),
        "session_profit_factor": (
            total_positive / abs(sum(negative, Decimal("0"))) if negative else None
        ),
        "average_gross_exposure": sum(exposures, Decimal("0")) / Decimal(len(exposures)),
        "max_gross_exposure": max(exposures),
        "active_sessions": sum(exposure > 0 for exposure in exposures),
        "session_count": len(points),
        "best_session_return": max(returns),
        "worst_session_return": min(returns),
        "top_5_session_profit_share": (
            sum(sorted(positive, reverse=True)[:5], Decimal("0")) / total_positive
            if total_positive
            else None
        ),
        "top_instrument_profit_share": result.metrics.top_instrument_profit_share,
        "net_of_costs": True,
    }


def _specification(
    dataset: ResearchDataset,
    inputs: ResearchInputs,
    parameters: Mapping[str, int],
    run_type: str,
    *,
    group_id: str | None = None,
    parent_run_id: str | None = None,
    fold: Mapping[str, object] | None = None,
    exploratory_context: Mapping[str, object] | None = None,
    campaign: Mapping[str, object] | None = None,
) -> dict[str, object]:
    definition = get_strategy_definition(inputs.strategy)
    specification: dict[str, object] = {
        "schema_version": "rapid-research-run-v1",
        "run_type": run_type,
        "dataset": {
            "id": dataset.dataset_id,
            "fingerprint": dataset.dataset_fingerprint,
            "source": dataset.source,
            "timeframe": dataset.timeframe,
            "symbols": dataset.symbols,
        },
        "strategy": {
            "name": definition.name,
            "id": definition.strategy_id,
            "version": "1",
            "family": definition.family,
            "parameters": parameters,
        },
        "start_timestamp": dataset.start_timestamp,
        "end_timestamp": dataset.end_timestamp,
        "initial_cash": inputs.initial_cash,
        "costs": {
            "version": _cost_model(inputs).version,
            "slippage_bps": inputs.slippage_bps,
            "commission_bps": inputs.commission_bps,
        },
        "execution": {
            "model": "deterministic-next-bar-open-v1",
            "fill_delay_bars": inputs.fill_delay_bars,
        },
        "code": _code_identity(),
    }
    if group_id is not None:
        specification["group_id"] = group_id
    if parent_run_id is not None:
        specification["parent_run_id"] = parent_run_id
    if fold is not None:
        specification["fold"] = fold
    if exploratory_context is not None:
        specification["exploratory_context"] = exploratory_context
    if campaign is not None:
        specification["campaign"] = campaign
    return specification


def _walk_forward_metrics(folds: Sequence[Mapping[str, object]]) -> dict[str, object]:
    completed = [fold for fold in folds if fold["status"] == "completed"]
    returns = [Decimal(str(_mapping(fold["metrics"])["total_return"])) for fold in completed]
    drawdowns = [Decimal(str(_mapping(fold["metrics"])["max_drawdown"])) for fold in completed]
    combined = Decimal("1")
    for value in returns:
        combined *= Decimal("1") + value
    mean = sum(returns, Decimal("0")) / Decimal(len(returns)) if returns else None
    dispersion = (
        (
            sum(((value - mean) ** 2 for value in returns), Decimal("0"))
            / Decimal(len(returns) - 1)
        ).sqrt()
        if mean is not None and len(returns) > 1
        else Decimal("0")
        if returns
        else None
    )
    return {
        "fold_count": len(folds),
        "completed_fold_count": len(completed),
        "failed_fold_count": len(folds) - len(completed),
        "overall_out_of_sample_return": combined - Decimal("1") if returns else None,
        "mean_fold_return": mean,
        "fold_return_dispersion": dispersion,
        "best_fold_return": max(returns) if returns else None,
        "worst_fold_return": min(returns) if returns else None,
        "profitable_fold_rate": (
            Decimal(sum(value > 0 for value in returns)) / Decimal(len(returns))
            if returns
            else None
        ),
        "mean_fold_max_drawdown": (
            sum(drawdowns, Decimal("0")) / Decimal(len(drawdowns)) if drawdowns else None
        ),
        "worst_fold_max_drawdown": max(drawdowns) if drawdowns else None,
        "total_trade_count": sum(
            _integer(_mapping(fold["metrics"])["trade_count"], "trade count") for fold in completed
        ),
        "total_cost_paid": sum(
            (Decimal(str(_mapping(fold["metrics"])["cost_paid"])) for fold in completed),
            Decimal("0"),
        ),
        "score": None,
        "net_of_costs": True,
    }


def _stress_survival(parent: Mapping[str, object], stressed: Mapping[str, object]) -> bool | None:
    if parent["status"] != "completed" or stressed["status"] != "completed":
        return None
    stressed_return = Decimal(str(_mapping(stressed["metrics"])["total_return"]))
    return stressed_return > 0


def _compact_run(run: Mapping[str, object]) -> dict[str, object]:
    return {
        "run_id": run["run_id"],
        "run_type": run["run_type"],
        "status": run["status"],
        "group_id": run.get("group_id"),
        "parent_run_id": run.get("parent_run_id"),
        "dataset_id": run["dataset_id"],
        "strategy_name": run["strategy_name"],
        "parameters": run["parameters"],
        "start_timestamp": run["start_timestamp"],
        "end_timestamp": run["end_timestamp"],
        "costs": {
            "slippage_bps": run["slippage_bps"],
            "commission_bps": run["commission_bps"],
        },
        "fill_delay_bars": run["fill_delay_bars"],
        "metrics": run["metrics"],
        "report_path": run["report_path"],
        "error": run["error"],
    }


def _cost_model(inputs: ResearchInputs) -> CostModel:
    version = (
        "conservative-bps-v1"
        if (inputs.slippage_bps, inputs.commission_bps) == (Decimal("5"), Decimal("1"))
        else f"rapid-bps-{inputs.slippage_bps}-{inputs.commission_bps}-v1"
    )
    return CostModel(version, inputs.slippage_bps, inputs.commission_bps)


def _code_identity() -> dict[str, object]:
    try:
        module_directory = Path(__file__).resolve().parent
        git_command = ("git", "--no-replace-objects", "-c", "core.fsmonitor=false")
        environment = non_broker_subprocess_environment()
        environment.update(
            {
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1",
                "HOME": "/nonexistent",
                "XDG_CONFIG_HOME": "/nonexistent",
            }
        )
        repository = Path(
            subprocess.run(
                (*git_command, "-C", str(module_directory), "rev-parse", "--show-toplevel"),
                check=True,
                capture_output=True,
                env=environment,
                text=True,
                timeout=5,
            ).stdout.strip()
        )
        if module_directory != (repository / "src/systematic_trading_lab").resolve():
            raise ValueError("Rapid Research source is not the repository checkout")
        commit = subprocess.run(
            (*git_command, "rev-parse", "HEAD"),
            check=True,
            capture_output=True,
            env=environment,
            text=True,
            timeout=5,
            cwd=repository,
        ).stdout.strip()
        code_paths = ("src/systematic_trading_lab", "pyproject.toml", "uv.lock")
        status = subprocess.run(
            (
                *git_command,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                *code_paths,
            ),
            check=True,
            capture_output=True,
            env=environment,
            timeout=5,
            cwd=repository,
        ).stdout
        dirty = bool(status)
        working_tree_fingerprint = None
        if dirty:
            digest = hashlib.sha256()
            digest.update(
                subprocess.run(
                    (
                        *git_command,
                        "diff",
                        "--binary",
                        "--no-ext-diff",
                        "--no-textconv",
                        "HEAD",
                        "--",
                        *code_paths,
                    ),
                    check=True,
                    capture_output=True,
                    env=environment,
                    timeout=5,
                    cwd=repository,
                ).stdout
            )
            untracked = subprocess.run(
                (
                    *git_command,
                    "ls-files",
                    "--others",
                    "--exclude-standard",
                    "-z",
                    "--",
                    *code_paths,
                ),
                check=True,
                capture_output=True,
                env=environment,
                timeout=5,
                cwd=repository,
            ).stdout.split(b"\0")
            for raw_path in sorted(path for path in untracked if path):
                path = repository / raw_path.decode("utf-8")
                digest.update(raw_path)
                digest.update(hashlib.sha256(path.read_bytes()).digest())
            working_tree_fingerprint = digest.hexdigest()
        if len(commit) != 40:
            raise ValueError("Git commit is not canonical")
        return {
            "commit": commit,
            "dirty": dirty,
            "working_tree_fingerprint": working_tree_fingerprint,
        }
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
        return {"commit": None, "dirty": None, "working_tree_fingerprint": None}


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("Rapid Research record is malformed")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Rapid Research {label} is malformed")
    return value
