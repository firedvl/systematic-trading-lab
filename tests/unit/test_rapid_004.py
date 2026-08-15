from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

import systematic_trading_lab.rapid_004 as rapid_004
from systematic_trading_lab.rapid_004 import (
    load_rapid_004_binding,
    load_rapid_004_predeclaration,
)


def _copy_config(target_root: Path) -> Path:
    source = Path(__file__).resolve().parents[2] / "config/research"
    target = target_root / "config/research"
    target.mkdir(parents=True)
    for name in (
        "rapid-004-universe-freeze-v1.json",
        "rapid-004-final-universe-v1.json",
        "rapid-004-predeclaration-v1.json",
    ):
        (target / name).write_bytes((source / name).read_bytes())
    return target / "rapid-004-predeclaration-v1.json"


def _manifest() -> dict[str, object]:
    binding = load_rapid_004_binding()
    return {
        "identity": {
            "dataset_id": binding.dataset_id,
            "fingerprint": binding.dataset_fingerprint,
        },
        "provider": binding.provider,
        "feed": binding.feed,
        "adjustment_policy": binding.adjustment_policy,
        "timeframe": "1d",
        "requested_range": {
            "start": f"{binding.start}T00:00:00Z",
            "end": f"{binding.end}T00:00:00Z",
        },
        "actual_range": {
            "start": f"{binding.start}T00:00:00Z",
            "end": f"{binding.end}T00:00:00Z",
        },
        "raw_artifact_hashes": [binding.raw_record_fingerprint],
        "universe_id": binding.universe_id,
        "universe_fingerprint": binding.universe_fingerprint,
        "symbols": [{"value": symbol} for symbol in binding.symbols],
        "validation": {
            "errors": [],
            "missing_intervals": [],
            "duplicate_intervals": [],
            "conflicts": [],
            "quarantined_records": 0,
        },
    }


def test_rapid_004_binding_accepts_only_the_frozen_manifest() -> None:
    binding = load_rapid_004_binding()
    manifest = _manifest()

    binding.require_dataset_id(binding.dataset_id)
    binding.require_manifest(manifest)
    assert binding.specification() == {
        "id": "rapid-004-expanded-universe",
        "freeze_sha256": "e99cd6e7cd8f4dc11cd80bbe9affadc2e4136945250f44b2eec6d4d83de8efba",
        "universe_specification_sha256": (
            "100ed3b1f195e35827fb70c418f1a2bce9ef2c7444385c79c2c61278d32f60dc"
        ),
        "universe_id": "rapid-004-expanded-final-universe-v1",
        "universe_fingerprint": (
            "d57039d3a172337c78ad8206644feeb72d76d124ce33a4e5cbe4733dbb2e94e3"
        ),
        "dataset_id": "450e329a8f11f1bd19dcc37ac417b2c59a262e875723eb668332beb22c48d3ff",
        "dataset_fingerprint": ("ac506268e019a03f7e9e202858171141c3f2d63fc88e03649a1dda091ac47304"),
        "predeclaration_sha256": (
            "28f97126d49a9f0f092f2c8159d5b7c48a14a4e5b7ba850c2e58dfd9b6c64996"
        ),
        "role_map_sha256": "94e483271339395e95787d20e13eab8a74a2ea9adfe624658e485955a6132f04",
        "benchmark_suite_sha256": (
            "f8a48f3eb8f2914c36d278c3b98957322b4531defc4d472951f9a15ba0be4a05"
        ),
        "research_plan_sha256": (
            "fd24146ee5fc7e814f2951330ed321db899fd1249fd36e16e268c9c6a2ee2be2"
        ),
        "exposed_screen_sha256": (
            "b76ea757efd35cb8d74157cc9210126607bcabc1ee2cb220b46b988dab8943f9"
        ),
    }

    with pytest.raises(ValueError, match="exact frozen dataset ID"):
        binding.require_dataset_id(
            "1c3b228a7c5fb4dc247f25cd9b4030482c7494533bb2a3fa2af77346d8274799"
        )


@pytest.mark.parametrize(
    ("path", "value", "message"),
    (
        (("identity", "dataset_id"), "0" * 64, "dataset ID differs"),
        (("identity", "fingerprint"), "0" * 64, "dataset fingerprint differs"),
        (("universe_fingerprint",), "0" * 64, "universe fingerprint differs"),
        (("symbols",), [{"value": "SPY"}], "symbols differs"),
        (("provider",), "other", "provider differs"),
        (("adjustment_policy",), "other", "adjustment policy differs"),
    ),
)
def test_rapid_004_binding_rejects_manifest_substitution(
    path: tuple[str, ...], value: object, message: str
) -> None:
    manifest = deepcopy(_manifest())
    target = manifest
    for name in path[:-1]:
        nested = target[name]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = value

    with pytest.raises(ValueError, match=message):
        load_rapid_004_binding().require_manifest(manifest)


def test_rapid_004_predeclaration_fixes_roles_grids_and_budget() -> None:
    plan = load_rapid_004_predeclaration()

    assert plan.group("duration") == ("SHY", "IEF", "TLT")
    assert plan.group("tactical-representatives") == (
        "SPY",
        "EFA",
        "EEM",
        "TLT",
        "LQD",
        "TIP",
        "GLD",
        "DBC",
        "VNQ",
    )
    assert tuple(item[0] for item in plan.family_configuration_counts) == tuple(
        "ABCDEFGHIJKLMNOPQRSTU"
    )
    assert sum(item[1] for item in plan.family_configuration_counts) == 356
    assert sum(item[2] for item in plan.family_configuration_counts) == 186
    assert plan.maximum_parent_records == 2452
    assert plan.maximum_parent_records < 3000


def test_rapid_004_predeclaration_rejects_byte_substitution(tmp_path: Path) -> None:
    predeclaration = _copy_config(tmp_path)
    predeclaration.write_bytes(predeclaration.read_bytes() + b" ")

    with pytest.raises(ValueError, match="predeclaration SHA-256 differs"):
        load_rapid_004_binding(tmp_path)


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("duplicate-role", "must be unique"),
        ("nonpartition-category", "exactly partition"),
        ("missing-profile", "strategy profiles differ"),
        ("over-budget", "exceeds its fixed ceiling"),
        ("wrong-walk-forward-metric", "walk-forward gate metrics differ"),
    ),
)
def test_rapid_004_predeclaration_rejects_semantic_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    message: str,
) -> None:
    predeclaration = _copy_config(tmp_path)
    payload = json.loads(predeclaration.read_text(encoding="utf-8"))
    if case == "duplicate-role":
        payload["role_map"]["groups"]["duration"] = ["SHY", "SHY"]
    elif case == "nonpartition-category":
        payload["role_map"]["categories"]["international"].append("SPY")
    elif case == "missing-profile":
        del payload["mechanics"]["strategy_profiles"]["relative-strength"]
    elif case == "over-budget":
        budget = payload["search"]["parent_budget"]
        budget["maximum_neighbor_fixed_block_parents"] = 2061
        budget["maximum_parent_records"] = 3001
        budget["remaining_below_ceiling"] = -1
    else:
        payload["walk_forward_screen"]["gates"][2]["metric"] = "compounded_out_of_sample_return"
    encoded = (json.dumps(payload, indent=2) + "\n").encode()
    predeclaration.write_bytes(encoded)
    monkeypatch.setattr(rapid_004, "_PREDECLARATION_SHA256", hashlib.sha256(encoded).hexdigest())

    with pytest.raises(ValueError, match=message):
        load_rapid_004_binding(tmp_path)
