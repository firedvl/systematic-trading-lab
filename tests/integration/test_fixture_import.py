import json
from pathlib import Path

from systematic_trading_lab.datasets import DatasetService, fixture_request, fixture_symbols
from systematic_trading_lab.domain import Timeframe
from systematic_trading_lab.providers import FixtureProvider
from systematic_trading_lab.storage import StorageLayout


def test_fixture_import_is_immutable_describable_and_rebuildable(tmp_path: Path) -> None:
    layout = StorageLayout(tmp_path)
    service = DatasetService(layout)

    first = service.import_from(
        FixtureProvider(), fixture_symbols(), Timeframe.DAILY, fixture_request()
    )
    second = service.import_from(
        FixtureProvider(), fixture_symbols(), Timeframe.DAILY, fixture_request()
    )

    assert first.created is True
    assert second.created is False
    assert first.fingerprint == second.fingerprint
    assert first.bar_count == 25
    assert service.describe()["identity"]["dataset_id"] == first.dataset_id
    assert service.validate()["valid"] is True
    assert len(service.load_bars(first.dataset_id)) == 25

    layout.catalog.unlink()
    rebuilt = DatasetService(layout)
    assert rebuilt.rebuild_catalog() == 1
    assert rebuilt.validate(first.dataset_id)["valid"] is True


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
            InvalidProvider(), fixture_symbols(), Timeframe.DAILY, fixture_request()
        )
    except ValueError as error:
        assert "dataset rejected" in str(error)
    else:
        raise AssertionError("invalid dataset was accepted")

    evidence = list(layout.quarantine.glob("*.json"))
    assert len(evidence) == 1
    assert json.loads(evidence[0].read_text(encoding="utf-8"))["validation"]["errors"]
    assert not list(layout.datasets.iterdir())
