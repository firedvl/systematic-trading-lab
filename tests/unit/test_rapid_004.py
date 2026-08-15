from __future__ import annotations

from copy import deepcopy

import pytest

from systematic_trading_lab.rapid_004 import load_rapid_004_binding


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
