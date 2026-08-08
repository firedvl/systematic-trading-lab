import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from systematic_trading_lab.datasets import (
    DatasetService,
    DatasetValidationError,
    fixture_request,
    fixture_symbols,
)
from systematic_trading_lab.domain import AdjustmentPolicy, Symbol, Timeframe, TimestampRange
from systematic_trading_lab.providers import FixtureProvider
from systematic_trading_lab.storage import StorageLayout
from systematic_trading_lab.universe import load_research_universe

UNIVERSE = load_research_universe()


def test_fixture_import_is_immutable_describable_and_rebuildable(tmp_path: Path) -> None:
    layout = StorageLayout(tmp_path)
    service = DatasetService(layout)

    first = service.import_from(
        FixtureProvider(), fixture_symbols(), Timeframe.DAILY, fixture_request(), UNIVERSE
    )
    second = service.import_from(
        FixtureProvider(), fixture_symbols(), Timeframe.DAILY, fixture_request(), UNIVERSE
    )

    assert first.created is True
    assert second.created is False
    assert first.dataset_id == "042e1e94eee7bbc1fe47c2f473bbbf93d773296a135486fa74fb34861c46e06d"
    assert first.fingerprint == second.fingerprint
    assert first.bar_count == 25
    manifest = service.describe()
    assert manifest["identity"]["dataset_id"] == first.dataset_id
    assert manifest["universe_id"] == UNIVERSE.universe_id
    assert manifest["universe_fingerprint"] == UNIVERSE.universe_fingerprint
    assert "timestamp_policy" not in manifest
    assert service.validate()["valid"] is True
    assert len(service.load_bars(first.dataset_id)) == 25

    layout.catalog.unlink()
    rebuilt = DatasetService(layout)
    assert rebuilt.rebuild_catalog() == 1
    assert rebuilt.validate(first.dataset_id)["valid"] is True

    layout.catalog.unlink()
    recovered = DatasetService(layout).import_from(
        FixtureProvider(), fixture_symbols(), Timeframe.DAILY, fixture_request(), UNIVERSE
    )
    assert recovered.created is False
    assert DatasetService(layout).validate(first.dataset_id)["valid"] is True


def test_range_loader_reads_only_complete_requested_sessions(tmp_path: Path) -> None:
    service = DatasetService(StorageLayout(tmp_path))
    imported = service.import_from(
        FixtureProvider(), fixture_symbols(), Timeframe.DAILY, fixture_request(), UNIVERSE
    )
    requested = TimestampRange(datetime(2025, 1, 8, tzinfo=UTC), datetime(2025, 1, 9, tzinfo=UTC))

    bars = service.load_bars_range(
        imported.dataset_id,
        requested,
        expected_fingerprint=imported.fingerprint,
        expected_universe_id=UNIVERSE.universe_id,
        expected_universe_fingerprint=UNIVERSE.universe_fingerprint,
    )

    assert len(bars) == 10
    assert {bar.timestamp for bar in bars} == {
        datetime(2025, 1, 8, tzinfo=UTC),
        datetime(2025, 1, 9, tzinfo=UTC),
    }
    assert {bar.symbol.value for bar in bars} == {"SPY", "QQQ", "IWM", "TLT", "GLD"}


def test_invalid_provider_data_is_rejected_with_evidence(tmp_path: Path) -> None:
    class InvalidProvider(FixtureProvider):
        name = "invalid-test-provider"

        def fetch(self, *args: object, **kwargs: object) -> list[dict[str, object]]:
            return [
                {
                    "symbol": "SPY",
                    "timestamp": "2025-01-06T00:00:00Z",
                    "open": "100",
                    "high": "99",
                    "low": "98",
                    "close": "100",
                    "volume": -1,
                }
            ]

    layout = StorageLayout(tmp_path)
    service = DatasetService(layout)
    try:
        service.import_from(
            InvalidProvider(), fixture_symbols(), Timeframe.DAILY, fixture_request(), UNIVERSE
        )
    except ValueError as error:
        assert "dataset rejected" in str(error)
    else:
        raise AssertionError("invalid dataset was accepted")

    evidence = list(layout.quarantine.glob("*.json"))
    assert len(evidence) == 1
    assert json.loads(evidence[0].read_text(encoding="utf-8"))["validation"]["errors"]
    assert not list(layout.datasets.iterdir())


def test_provider_corrections_link_versions_without_cross_provider_collisions(
    tmp_path: Path,
) -> None:
    class CorrectedFixture(FixtureProvider):
        retrieval_timestamp = datetime(2025, 1, 12, tzinfo=UTC)

        def fetch(
            self, symbols: Sequence[Symbol], timeframe: Timeframe, requested: TimestampRange
        ) -> list[dict[str, Any]]:
            records = list(super().fetch(symbols, timeframe, requested))
            records[0] = {**records[0], "close": "100.6"}
            return records

    class RawRepresentationCorrection(FixtureProvider):
        retrieval_timestamp = datetime(2025, 1, 11, tzinfo=UTC)

        def fetch(
            self, symbols: Sequence[Symbol], timeframe: Timeframe, requested: TimestampRange
        ) -> list[dict[str, Any]]:
            records = list(super().fetch(symbols, timeframe, requested))
            records[0] = {**records[0], "close": "100.50"}
            return records

    class OtherProvider(FixtureProvider):
        name = "other-fixture-v1"

    layout = StorageLayout(tmp_path)
    service = DatasetService(layout)
    original = service.import_from(
        FixtureProvider(), fixture_symbols(), Timeframe.DAILY, fixture_request(), UNIVERSE
    )
    raw_correction = service.import_from(
        RawRepresentationCorrection(),
        fixture_symbols(),
        Timeframe.DAILY,
        fixture_request(),
        UNIVERSE,
    )
    corrected = service.import_from(
        CorrectedFixture(), fixture_symbols(), Timeframe.DAILY, fixture_request(), UNIVERSE
    )
    duplicate = service.import_from(
        CorrectedFixture(), fixture_symbols(), Timeframe.DAILY, fixture_request(), UNIVERSE
    )
    other = service.import_from(
        OtherProvider(), fixture_symbols(), Timeframe.DAILY, fixture_request(), UNIVERSE
    )

    assert raw_correction.fingerprint == original.fingerprint
    assert raw_correction.dataset_id != original.dataset_id
    assert raw_correction.parent_dataset_id == original.dataset_id
    assert corrected.dataset_id != original.dataset_id
    assert corrected.parent_dataset_id == raw_correction.dataset_id
    assert service.describe(corrected.dataset_id)["parent_dataset_id"] == raw_correction.dataset_id
    assert duplicate.created is False
    assert duplicate.dataset_id == corrected.dataset_id
    assert other.dataset_id != original.dataset_id
    assert other.parent_dataset_id is None

    layout.catalog.unlink()
    rebuilt = DatasetService(layout)
    assert rebuilt.rebuild_catalog() == 4
    assert rebuilt.describe(corrected.dataset_id)["parent_dataset_id"] == raw_correction.dataset_id


def test_universe_revision_creates_a_separate_dataset_lineage(tmp_path: Path) -> None:
    service = DatasetService(StorageLayout(tmp_path))
    original = service.import_from(
        FixtureProvider(), fixture_symbols(), Timeframe.DAILY, fixture_request(), UNIVERSE
    )
    revised = service.import_from(
        FixtureProvider(),
        fixture_symbols(),
        Timeframe.DAILY,
        fixture_request(),
        replace(UNIVERSE, universe_fingerprint="reviewed-universe-revision"),
    )

    assert revised.dataset_id != original.dataset_id
    assert revised.parent_dataset_id is None


def test_unadjusted_data_is_rejected_without_a_corporate_action_processor(tmp_path: Path) -> None:
    class UnadjustedFixture(FixtureProvider):
        adjustment_policy = AdjustmentPolicy.UNADJUSTED

    with pytest.raises(DatasetValidationError, match="corporate-action processing"):
        DatasetService(StorageLayout(tmp_path)).import_from(
            UnadjustedFixture(), fixture_symbols(), Timeframe.DAILY, fixture_request(), UNIVERSE
        )
