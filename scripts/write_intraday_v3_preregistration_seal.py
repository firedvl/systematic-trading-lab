"""Bind the reviewed V3 design to one main build for GitHub attestation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from systematic_trading_lab.intraday_exposure import (
    load_intraday_exposure_inventory,
    load_intraday_v3_period_selection,
)
from systematic_trading_lab.intraday_v3_campaign import load_intraday_v3_campaign_plan
from systematic_trading_lab.intraday_v3_qualification import (
    load_intraday_v3_qualification_binding,
)

_FOUNDATION_COMMIT = "d03be5eaa1e5d2d360424a6c0d06c1ce0bc6a723"
_REPOSITORY = "firedvl/systematic-trading-lab"
_WORKFLOW = ".github/workflows/build-provenance.yml"
_AUTHORITIES = {
    "research_qualification": False,
    "protected_holdout": False,
    "paper_execution": False,
    "broker_writes": False,
    "live_execution": False,
}


def _fingerprint(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("preregistration source contains duplicate fields")
    return value


def _artifact(path: Path, fingerprint_field: str) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("preregistration source path is unsafe")
    raw = path.read_bytes()
    value = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError("preregistration source must be an object")
    claimed = value.get(fingerprint_field)
    unsigned = dict(value)
    unsigned.pop(fingerprint_field, None)
    if not isinstance(claimed, str) or _fingerprint(unsigned) != claimed:
        raise ValueError(f"invalid {fingerprint_field}")
    return {
        "path": path.as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "fingerprint": claimed,
    }


def build_seal(
    source_commit: str,
    inventory: Path,
    selection: Path,
    plan: Path,
    qualification_binding: Path,
) -> dict[str, object]:
    if len(source_commit) != 40 or any(c not in "0123456789abcdef" for c in source_commit):
        raise ValueError("source commit must be a full lowercase Git SHA-1")
    expected_names = {
        inventory: "intraday-known-exposures-v1.json",
        selection: "intraday-v3-period-selection-v2.json",
        plan: "intraday-campaign-v3.json",
        qualification_binding: "intraday-v3-qualification-binding-v1.json",
    }
    if any(path.name != name for path, name in expected_names.items()):
        raise ValueError("preregistration source filename differs")
    artifacts = {
        "exposure_inventory": _artifact(inventory, "inventory_fingerprint"),
        "period_selection": _artifact(selection, "selection_fingerprint"),
        "campaign_plan": _artifact(plan, "plan_fingerprint"),
        "qualification_binding": _artifact(qualification_binding, "binding_fingerprint"),
    }
    inventory_value = load_intraday_exposure_inventory(inventory)
    selection_value = load_intraday_v3_period_selection(selection, inventory_value)
    plan_value = load_intraday_v3_campaign_plan(plan)
    binding_value = load_intraday_v3_qualification_binding(qualification_binding)
    plan_payload = plan_value.payload
    if (
        selection_value.inventory_fingerprint != artifacts["exposure_inventory"]["fingerprint"]
        or selection_value.selection_fingerprint != artifacts["period_selection"]["fingerprint"]
        or plan_value.source_foundation_commit != _FOUNDATION_COMMIT
        or plan_payload.get("prospective_freshness", {}).get("period_selection_fingerprint")
        != artifacts["period_selection"]["fingerprint"]
        or plan_payload.get("prospective_freshness", {}).get("inventory_fingerprint")
        != artifacts["exposure_inventory"]["fingerprint"]
        or binding_value.fingerprint != artifacts["qualification_binding"]["fingerprint"]
        or plan_payload.get("authorities") != _AUTHORITIES
    ):
        raise ValueError("preregistration artifacts do not form one reviewed design")
    unsigned: dict[str, object] = {
        "schema_version": "intraday-v3-preregistration-seal-v1",
        "source_repository": _REPOSITORY,
        "signer_workflow": _WORKFLOW,
        "source_commit": source_commit,
        "source_foundation_commit": _FOUNDATION_COMMIT,
        "first_validation_bar": plan_payload["trusted_time_policy"]["first_validation_bar"],
        "freshness_basis": "main-attested-design-before-first-market-bar-v1",
        "universal_freshness_proven": False,
        "prospective_market_data_freshness": True,
        "artifacts": artifacts,
        "authorities": dict(_AUTHORITIES),
    }
    return {**unsigned, "seal_fingerprint": _fingerprint(unsigned)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--qualification-binding", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    seal = build_seal(
        arguments.source_commit,
        arguments.inventory,
        arguments.selection,
        arguments.plan,
        arguments.qualification_binding,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(seal, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
