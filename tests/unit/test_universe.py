import json
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

from systematic_trading_lab.domain import Symbol, Timeframe, TimestampRange
from systematic_trading_lab.universe import UniverseError, load_research_universe


def date(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def symbols(*values: str) -> tuple[Symbol, ...]:
    return tuple(Symbol(value) for value in values)


def test_research_universe_has_deterministic_full_range_membership() -> None:
    universe = load_research_universe()
    requested = TimestampRange(date("2004-11-18"), date("2025-01-10"))

    universe.require_full_coverage(
        symbols("SPY", "QQQ", "IWM", "TLT", "GLD"), Timeframe.DAILY, requested
    )

    assert universe.universe_fingerprint == load_research_universe().universe_fingerprint


def test_research_universe_rejects_inception_crossing_and_incomplete_requests() -> None:
    universe = load_research_universe()
    all_symbols = symbols("SPY", "QQQ", "IWM", "TLT", "GLD")

    with pytest.raises(UniverseError, match="lack full-range membership"):
        universe.require_full_coverage(
            all_symbols,
            Timeframe.DAILY,
            TimestampRange(date("2004-11-17"), date("2004-11-19")),
        )

    with pytest.raises(UniverseError, match="missing active symbols: GLD"):
        universe.require_full_coverage(
            symbols("SPY", "QQQ", "IWM", "TLT"),
            Timeframe.DAILY,
            TimestampRange(date("2005-01-01"), date("2005-01-31")),
        )


def test_extended_universe_binds_and_enforces_its_acquisition_policy(tmp_path: Path) -> None:
    path = tmp_path / "universe.json"
    payload = {
        "schema_version": "test-universe-v1",
        "id": "test-universe-v1",
        "timeframe": "1d",
        "acquisition": {"start": "2020-01-01", "end": "2020-12-31"},
        "sealed_boundaries": {"independent_access_allowed": False},
        "memberships": [
            {
                "symbol": "SPY",
                "start": "1993-01-22",
                "end": None,
                "source": "https://example.com/spy",
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    universe = load_research_universe(path)

    universe.require_acquisition_range(TimestampRange(date("2020-01-02"), date("2020-12-30")))
    with pytest.raises(UniverseError, match="outside the universe acquisition range"):
        universe.require_acquisition_range(TimestampRange(date("2019-12-31"), date("2020-01-02")))

    payload["sealed_boundaries"] = {"independent_access_allowed": True}
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_research_universe(path).universe_fingerprint != universe.universe_fingerprint


def test_rapid_004_final_universe_freezes_selection_and_dataset_identity() -> None:
    root = Path(__file__).resolve().parents[2]
    seed_path = root / "config" / "research" / "rapid-004-seed-universe-v1.json"
    final_path = root / "config" / "research" / "rapid-004-final-universe-v1.json"
    freeze_path = root / "config" / "research" / "rapid-004-universe-freeze-v1.json"
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    final = json.loads(final_path.read_text(encoding="utf-8"))
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    universe = load_research_universe(final_path)

    dispositions = {item["symbol"]: item for item in final["dispositions"]}
    final_symbols = [item["symbol"] for item in final["memberships"]]
    assert set(dispositions) == {item["symbol"] for item in seed["memberships"]}
    assert len(dispositions) == 40
    assert len(final_symbols) == 37
    assert {symbol for symbol, item in dispositions.items() if not item["included"]} == {
        "IVE",
        "IVW",
        "VWO",
    }
    assert all(item["sessions"] == 614 for item in dispositions.values())
    assert all(
        Decimal(item["median_daily_dollar_volume"]) >= Decimal("10000000")
        for item in dispositions.values()
    )
    assert {
        item["id"]: (item["selected"], item["excluded"])
        for item in final["duplicate_resolution"]["groups"]
    } == {
        "us-large-value": ("IWD", "IVE"),
        "us-large-growth": ("IWF", "IVW"),
        "emerging-markets-equity": ("EEM", "VWO"),
    }
    assert final["selection_result"]["ordered_final_symbols"] == final_symbols
    assert (
        final["selection_source"]["seed_universe_sha256"]
        == sha256(seed_path.read_bytes()).hexdigest()
    )
    assert final["liquidity_screen"]["performance_fields_calculated"] == []
    assert not final["liquidity_screen"]["strategy_results_inspected"]

    assert freeze["universe_specification"]["sha256"] == sha256(final_path.read_bytes()).hexdigest()
    assert freeze["universe_specification"]["symbols"] == final_symbols
    assert freeze["universe_specification"]["universe_fingerprint"] == (
        universe.universe_fingerprint
    )
    assert freeze["immutable_dataset"]["dataset_id"] == (
        "450e329a8f11f1bd19dcc37ac417b2c59a262e875723eb668332beb22c48d3ff"
    )
    assert freeze["immutable_dataset"]["dataset_fingerprint"] == (
        "ac506268e019a03f7e9e202858171141c3f2d63fc88e03649a1dda091ac47304"
    )
    assert freeze["immutable_dataset"]["bar_count"] == 37 * 1511
    assert freeze["immutable_dataset"]["validation"] == {
        "errors": [],
        "missing_intervals": [],
        "duplicate_intervals": [],
        "conflicts": [],
        "quarantined_records": 0,
    }
    assert not any(freeze["protected_state"].values())
