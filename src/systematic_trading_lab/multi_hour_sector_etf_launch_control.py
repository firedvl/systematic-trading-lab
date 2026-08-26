"""Pure prelaunch checks for Program 002; this module never grants execution authority."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .fingerprints import fingerprint
from .multi_hour_sector_etf_plan import (
    PROGRAM_ID,
    REVIEWED_ACQUISITION_PLAN_SHA256,
    REVIEWED_AUTHORITY_SHA256,
    REVIEWED_PLAN_FINGERPRINT,
    REVIEWED_PLAN_SHA256,
    REVIEWED_PLANNING_REVIEW_FINGERPRINT,
    REVIEWED_PLANNING_REVIEW_SHA256,
    REVIEWED_UNIVERSE_FINGERPRINT,
    REVIEWED_UNIVERSE_SHA256,
    load_program_002_account_proof_plan,
    load_program_002_plan,
)
from .program_002_credentials import reject_research_credentials

_IMPLEMENTATION_PATHS = (
    "src/systematic_trading_lab/multi_hour_sector_etf_plan.py",
    "src/systematic_trading_lab/multi_hour_sector_etf_features.py",
    "src/systematic_trading_lab/multi_hour_sector_etf_engine.py",
    "src/systematic_trading_lab/multi_hour_sector_etf_synthetic.py",
    "src/systematic_trading_lab/multi_hour_sector_etf_runner.py",
    "src/systematic_trading_lab/program_002_acquisition.py",
    "src/systematic_trading_lab/program_002_acquisition_cli.py",
    "src/systematic_trading_lab/program_002_account_isolation.py",
    "src/systematic_trading_lab/program_002_credentials.py",
    "src/systematic_trading_lab/multi_hour_sector_etf_launch_control.py",
)
_DATASET_ROLES = (
    "exposed-context-only",
    "exposed-block-1",
    "exposed-block-2",
    "exposed-block-3",
)


def program_002_prelaunch_status(
    repository: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Mapping[str, Any]:
    """Bind the known implementation surface and report every still-missing launch input."""
    reject_research_credentials(os.environ if environ is None else environ)
    repository = repository.resolve()
    plan = load_program_002_plan(repository)
    acquisition = load_program_002_account_proof_plan(repository)
    authority = plan.authority.payload["authority"]
    if acquisition.authority != plan.authority or authority.get("strategy_execution") is not False:
        raise ValueError("Program 002 authority separation differs")
    files = {
        relative: hashlib.sha256((repository / relative).read_bytes()).hexdigest()
        for relative in _IMPLEMENTATION_PATHS
    }
    known = {
        "authority_sha256": REVIEWED_AUTHORITY_SHA256,
        "plan_sha256": REVIEWED_PLAN_SHA256,
        "plan_fingerprint": REVIEWED_PLAN_FINGERPRINT,
        "acquisition_plan_sha256": REVIEWED_ACQUISITION_PLAN_SHA256,
        "universe_sha256": REVIEWED_UNIVERSE_SHA256,
        "universe_fingerprint": REVIEWED_UNIVERSE_FINGERPRINT,
        "planning_review_sha256": REVIEWED_PLANNING_REVIEW_SHA256,
        "planning_review_fingerprint": REVIEWED_PLANNING_REVIEW_FINGERPRINT,
        "implementation_files": files,
        "implementation_surface_fingerprint": fingerprint(files),
    }
    return {
        "schema_version": "program-002-prelaunch-status-v1",
        "program_id": PROGRAM_ID,
        "known_bindings": known,
        "required_dataset_roles": _DATASET_ROLES,
        "blockers": (
            "merged implementation commit binding is absent",
            "reviewed exposed dataset bindings are absent",
            "reviewed quote and cost-model bindings are absent",
            "finding-free implementation/acquisition/cost reviews are absent",
            "reviewed synthetic equivalence binding is absent",
            "separate one-use strategy-execution authority is absent",
        ),
        "ready_for_separate_strategy_execution_authorization": False,
        "strategy_execution_authority_present": False,
        "launch_allowed": False,
        "controlled_evaluation_allowed": False,
        "paper_execution_allowed": False,
        "broker_writes_allowed": False,
        "live_execution_allowed": False,
    }
