from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path

import pytest

from systematic_trading_lab.fingerprints import fingerprint

_SPEC = importlib.util.spec_from_file_location(
    "write_intraday_v3_preregistration_seal",
    "scripts/write_intraday_v3_preregistration_seal.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
build_seal: Callable[..., dict[str, object]] = _MODULE.build_seal

_INVENTORY = Path("config/research/intraday-known-exposures-v1.json")
_SELECTION = Path("config/research/intraday-v3-period-selection-v2.json")
_PLAN = Path("config/research/intraday-campaign-v3.json")
_BINDING = Path("config/research/intraday-v3-qualification-binding-v1.json")


def test_seal_binds_exact_reviewed_artifacts_without_authority() -> None:
    seal = build_seal("a" * 40, _INVENTORY, _SELECTION, _PLAN, _BINDING)

    assert seal == build_seal("a" * 40, _INVENTORY, _SELECTION, _PLAN, _BINDING)
    assert seal["first_validation_bar"] == "2026-10-01T13:30:00Z"
    assert seal["prospective_market_data_freshness"] is True
    assert seal["universal_freshness_proven"] is False
    authorities = seal["authorities"]
    assert isinstance(authorities, Mapping)
    assert not any(authorities.values())


def test_changed_dates_require_new_selection_review(tmp_path: Path) -> None:
    selection = json.loads(_SELECTION.read_text())
    original = deepcopy(selection)
    selection["periods"][1]["start"] = "2026-10-02"
    changed = tmp_path / _SELECTION.name
    changed.write_text(json.dumps(selection))

    with pytest.raises(ValueError, match="selection_fingerprint"):
        build_seal("a" * 40, _INVENTORY, changed, _PLAN, _BINDING)

    assert selection["selection_fingerprint"] == original["selection_fingerprint"]


def test_duplicate_fields_and_non_main_identity_inputs_fail(tmp_path: Path) -> None:
    duplicate = tmp_path / _SELECTION.name
    raw = _SELECTION.read_text().rstrip()
    duplicate.write_text(raw[:-1] + ',"selection_fingerprint":"0"}')

    with pytest.raises(ValueError, match="duplicate"):
        build_seal("a" * 40, _INVENTORY, duplicate, _PLAN, _BINDING)
    with pytest.raises(ValueError, match="source commit"):
        build_seal("local", _INVENTORY, _SELECTION, _PLAN, _BINDING)


def test_known_acquisition_after_selection_blocks_sealing(tmp_path: Path) -> None:
    inventory = json.loads(_INVENTORY.read_text())
    inventory["entries"].append(
        {
            "id": "post-selection-validation-a-acquisition",
            "source": "known acquisition recorded before sealing",
            "start": "2026-10-01",
            "end": "2026-10-02",
            "symbols": ["SPY", "QQQ"],
            "timeframe": "5m",
            "class": "real-market-data-acquired-no-result",
            "disqualifies_v3_validation": True,
            "evidence_rationale": "Real selected-period bars became known before sealing.",
        }
    )
    inventory_unsigned = dict(inventory)
    inventory_unsigned.pop("inventory_fingerprint")
    inventory["inventory_fingerprint"] = fingerprint(inventory_unsigned)
    inventory_path = tmp_path / _INVENTORY.name
    inventory_path.write_text(json.dumps(inventory))

    selection = json.loads(_SELECTION.read_text())
    selection["inventory_fingerprint"] = inventory["inventory_fingerprint"]
    selection_unsigned = dict(selection)
    selection_unsigned.pop("selection_fingerprint")
    selection["selection_fingerprint"] = fingerprint(selection_unsigned)
    selection_path = tmp_path / _SELECTION.name
    selection_path.write_text(json.dumps(selection))

    with pytest.raises(ValueError, match="overlaps known exposure"):
        build_seal("a" * 40, inventory_path, selection_path, _PLAN, _BINDING)


def test_author_supplied_selection_cutoff_is_not_a_valid_input(tmp_path: Path) -> None:
    selection = json.loads(_SELECTION.read_text())
    selection["reviewed_selection_cutoff"] = "2020-01-01T00:00:00Z"
    unsigned = dict(selection)
    unsigned.pop("selection_fingerprint")
    selection["selection_fingerprint"] = fingerprint(unsigned)
    path = tmp_path / _SELECTION.name
    path.write_text(json.dumps(selection))

    with pytest.raises(ValueError, match="period selection fields differ"):
        build_seal("a" * 40, _INVENTORY, path, _PLAN, _BINDING)
