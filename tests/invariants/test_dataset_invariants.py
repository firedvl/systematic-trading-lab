import json
from pathlib import Path

from systematic_trading_lab.datasets import DatasetService, fixture_request, fixture_symbols
from systematic_trading_lab.domain import Timeframe
from systematic_trading_lab.providers import FixtureProvider
from systematic_trading_lab.storage import StorageLayout
from systematic_trading_lab.universe import load_research_universe


def test_artifact_tampering_breaks_integrity_check(tmp_path: Path) -> None:
    layout = StorageLayout(tmp_path)
    service = DatasetService(layout)
    imported = service.import_from(
        FixtureProvider(),
        fixture_symbols(),
        Timeframe.DAILY,
        fixture_request(),
        load_research_universe(),
    )
    bars = layout.dataset(imported.dataset_id) / "raw.jsonl"
    records = bars.read_text(encoding="utf-8").splitlines()
    changed = json.loads(records[0])
    changed["close"] = "999"
    records[0] = json.dumps(changed, separators=(",", ":"), sort_keys=True)
    bars.write_text("\n".join(records) + "\n", encoding="utf-8")

    assert service.validate(imported.dataset_id)["valid"] is False
