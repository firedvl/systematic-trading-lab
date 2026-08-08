from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from systematic_trading_lab.experiments import (
    ExperimentRegistry,
    ExperimentSplit,
    HoldoutAccessError,
    IntradayExperimentSpec,
)


def _spec() -> IntradayExperimentSpec:
    return IntradayExperimentSpec(
        experiment_id="m5b-candidate-001",
        campaign_id="m5b-engineering-baselines-v1",
        search_budget=6,
        candidate_ordinal=1,
        strategy_id="intraday-previous-bar-momentum",
        strategy_version="1",
        strategy_family="intraday-directional-momentum",
        code_commit="abc123",
        dataset_id="dataset-5m",
        dataset_fingerprint="dataset-fingerprint",
        universe_id="liquid-etfs-intraday-5m-v1",
        universe_fingerprint="universe-fingerprint",
        parameters={"lookback": 1},
        timeframe="5m",
        session_policy_version="XNYS-regular-session-flat-v1",
        bar_timestamp_semantics_version="bar-open-utc-v1",
        session_return_policy_version="XNYS-session-close-equity-v1",
        benchmark_policy_version="cash-and-continuous-underlying-v1",
        cost_model_version="conservative-bps-v1",
        slippage_bps=Decimal("5"),
        commission_bps=Decimal("1"),
        execution_model_version="deterministic-next-bar-open-v1",
        earliest_fill_semantics="completed-bar-next-bar-open-v1",
        execution_delay_bars=1,
        split=ExperimentSplit.TRAINING,
        start_timestamp=datetime(2025, 11, 26, 14, 30, tzinfo=UTC),
        end_timestamp=datetime(2025, 11, 28, 17, 55, tzinfo=UTC),
        random_seed=0,
        creation_reason="fixed engineering baseline",
    )


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: replace(value, timeframe="1m"),
        lambda value: replace(value, session_policy_version="reviewed-alternative-session-v2"),
        lambda value: replace(value, execution_model_version="reviewed-alternative-execution-v2"),
        lambda value: replace(value, execution_delay_bars=2),
        lambda value: replace(value, cost_model_version="harsher-costs-v1"),
        lambda value: replace(value, slippage_bps=Decimal("10")),
    ),
)
def test_intraday_configuration_fingerprint_binds_material_assumptions(
    mutation: Callable[[IntradayExperimentSpec], IntradayExperimentSpec],
) -> None:
    baseline = _spec()

    assert mutation(baseline).configuration_fingerprint != baseline.configuration_fingerprint
    assert replace(baseline).configuration_fingerprint == baseline.configuration_fingerprint


def test_intraday_contract_round_trips_through_shared_registry(tmp_path: Path) -> None:
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    registry.create_campaign(_spec().campaign_id, "M5B fixed baselines", 6)
    registry.create_experiment(_spec())

    record = registry.get(_spec().experiment_id)
    stored = cast(dict[str, object], record["spec_json"])

    assert record["status"] == "pending"
    assert stored["schema_version"] == "intraday-experiment-v1"
    assert stored["timeframe"] == "5m"
    assert stored["execution_delay_bars"] == 1
    assert stored["slippage_bps"] == "5"


def test_intraday_contract_cannot_use_holdout_authority(tmp_path: Path) -> None:
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    registry.create_campaign(_spec().campaign_id, "M5B fixed baselines", 6)

    with pytest.raises(HoldoutAccessError, match="cannot use holdout"):
        registry.create_experiment(_spec(), holdout_authorization_id="daily-authority")

    with pytest.raises(ValueError, match="holdout is not authorized"):
        replace(_spec(), split=ExperimentSplit.HOLDOUT)
