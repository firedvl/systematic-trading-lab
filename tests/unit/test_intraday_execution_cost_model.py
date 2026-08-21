from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from systematic_trading_lab.domain import Symbol
from systematic_trading_lab.fingerprints import fingerprint
from systematic_trading_lab.intraday_execution_cost_model import (
    MODEL_ID,
    REVIEWED_MODEL_SHA256,
    RegulatoryFill,
    load_intraday_execution_cost_model,
    verify_calibration_analysis,
)

_REPOSITORY = Path(__file__).resolve().parents[2]


def test_frozen_execution_cost_model_is_exact_and_strictly_stressed() -> None:
    model = load_intraday_execution_cost_model(_REPOSITORY)

    assert model.sha256 == REVIEWED_MODEL_SHA256
    assert model.payload["cost_model_id"] == MODEL_ID
    assert model.model_fingerprint == (
        "94fc3ba4663b422fbb0dc0cce7e3d78a7ba81f22d71d5fa986ab6847b7925bb4"
    )
    assert model.scenarios["normal"].slippage_bps_per_fill == {
        Symbol("QQQ"): Decimal("0.17"),
        Symbol("SPY"): Decimal("0.09"),
    }
    assert model.scenarios["stress_a"].execution_delay_bars == 2
    assert model.scenarios["stress_b"].execution_delay_bars == 3
    assert model.scenarios["zero_cost_diagnostic"].regulatory_fee_model_id is None
    assert model.scenarios["zero_cost_diagnostic"].fill_price(
        Symbol("SPY"), Decimal("500"), Decimal("1")
    ) == Decimal("500")


def test_execution_cost_model_rejects_changed_bytes(tmp_path: Path) -> None:
    path = tmp_path / "config/research/intraday-execution-cost-model-001-v1.json"
    path.parent.mkdir(parents=True)
    path.write_bytes((_REPOSITORY / path.relative_to(tmp_path)).read_bytes() + b"\n")

    with pytest.raises(ValueError, match="SHA-256 differs"):
        load_intraday_execution_cost_model(tmp_path)


def test_independent_control_review_binds_frozen_model() -> None:
    path = (
        _REPOSITORY / "config/research/intraday-execution-cost-model-001-independent-review-v1.json"
    )
    raw = path.read_bytes()
    review = json.loads(raw)
    stored_fingerprint = review.pop("review_fingerprint")

    assert hashlib.sha256(raw).hexdigest() == (
        "fb197856b9229349e5de4bca742f328a8f1e5e53f9558dfd7324744e91a795aa"
    )
    assert stored_fingerprint == (
        "8ade5190bb64330af037f88bf0911ed3cdb04578ca7a6d6e27a5fa6d651349b2"
    )
    assert fingerprint(review) == stored_fingerprint
    assert review["reviewed_model"]["sha256"] == REVIEWED_MODEL_SHA256
    assert review["verdict"] == "pass"
    assert len(review["answers"]) == 7
    assert not review["findings"]


def test_daily_regulatory_fees_aggregate_and_round_by_type() -> None:
    model = load_intraday_execution_cost_model(_REPOSITORY).regulatory_fees
    account_day = date(2026, 5, 1)
    executed_at = datetime(2026, 5, 1, 15, tzinfo=UTC)
    charges = model.charges_for_account_day(
        account_day,
        (
            RegulatoryFill(executed_at, "buy-1", "buy", Decimal("200"), Decimal("100000")),
            RegulatoryFill(executed_at, "sell-1", "sell", Decimal("200"), Decimal("100000")),
        ),
    )

    assert charges.sec == Decimal("2.06")
    assert charges.taf == Decimal("0.04")
    assert charges.cat == Decimal("0.01")
    assert charges.total == Decimal("2.11")
    assert model.charges_for_account_day(account_day, ()).total == 0


def test_taf_cap_applies_once_to_split_trade() -> None:
    model = load_intraday_execution_cost_model(_REPOSITORY).regulatory_fees
    account_day = date(2026, 5, 1)
    executed_at = datetime(2026, 5, 1, 15, tzinfo=UTC)

    charges = model.charges_for_account_day(
        account_day,
        (
            RegulatoryFill(executed_at, "trade-1", "sell", Decimal("50000"), Decimal("50000")),
            RegulatoryFill(executed_at, "trade-1", "sell", Decimal("50000"), Decimal("50000")),
            RegulatoryFill(executed_at, "trade-2", "sell", Decimal("100000"), Decimal("100000")),
        ),
    )

    assert charges.taf == Decimal("19.58")


def test_regulatory_fees_reject_mixed_account_days() -> None:
    model = load_intraday_execution_cost_model(_REPOSITORY).regulatory_fees
    account_day = date(2026, 5, 1)
    may_first_in_new_york = datetime(2026, 5, 2, 0, 30, tzinfo=UTC)

    assert model.charges_for_account_day(
        account_day,
        (
            RegulatoryFill(
                may_first_in_new_york,
                "sell-1",
                "sell",
                Decimal("1"),
                Decimal("500"),
            ),
        ),
    ).total == Decimal("0.04")

    with pytest.raises(ValueError, match="one account day"):
        model.charges_for_account_day(
            date(2026, 5, 2),
            (
                RegulatoryFill(
                    may_first_in_new_york,
                    "sell-1",
                    "sell",
                    Decimal("1"),
                    Decimal("500"),
                ),
            ),
        )


def test_calibration_analysis_verification_binds_percentile_values(tmp_path: Path) -> None:
    model = load_intraday_execution_cost_model(_REPOSITORY)
    evidence = dict(model.payload["calibration_evidence"])
    scenarios = model.payload["scenarios"]
    symbols = {
        symbol: {
            "half_spread_bps": {
                percentile: scenarios[name]["source_half_spread_bps"][symbol]
                for name, percentile in (
                    ("normal", "p75"),
                    ("stress_a", "p95"),
                    ("stress_b", "p99"),
                )
            }
        }
        for symbol in ("QQQ", "SPY")
    }
    analysis = {
        "analysis_fingerprint": evidence["analysis_fingerprint"],
        "feed": evidence["feed"],
        "quote_datasets_fingerprint": evidence["quote_datasets_fingerprint"],
        "sample": {
            "dataset_count": evidence["dataset_count"],
            "observation_count": evidence["observation_count"],
            "minimum_eligible_grid_coverage": evidence["minimum_eligible_grid_coverage"],
            "grid_exclusions": {"total": evidence["grid_exclusion_count"]},
            "raw_crossed_market_count": evidence["raw_crossed_market_count"],
        },
        "distributions": {"symbol": symbols},
    }
    encoded = json.dumps(analysis, separators=(",", ":")).encode()
    evidence["analysis_sha256"] = hashlib.sha256(encoded).hexdigest()
    payload = {**model.payload, "calibration_evidence": evidence}
    test_model = replace(
        model,
        payload=payload,
    )
    path = tmp_path / evidence["run_id"] / "analysis" / f"{evidence['analysis_fingerprint']}.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(encoded)

    assert verify_calibration_analysis(test_model, tmp_path) == path

    analysis["distributions"]["symbol"]["QQQ"]["half_spread_bps"]["p75"] = "1"
    path.write_text(json.dumps(analysis, separators=(",", ":")))
    with pytest.raises(ValueError, match="SHA-256 differs"):
        verify_calibration_analysis(test_model, tmp_path)
