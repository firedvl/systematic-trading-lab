"""Read-only disposition for the aborted Intraday Exposed 004 launch."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .fingerprints import fingerprint
from .intraday_exposed_004_plan import (
    PROGRAM_ID,
    REVIEWED_PLAN_REVIEW_FINGERPRINT,
    REVIEWED_PLAN_REVIEW_SHA256,
    load_intraday_exposed_004_plan,
)
from .research_executor import DEFAULT_RESEARCH_WORKERS

DATABASE_NAME = "intraday-exposed-004.sqlite3"
FAILURE_RELATIVE_PATH = Path("config/research/intraday-exposed-004-launch-failure-v1.json")
REVIEWED_FAILURE_SHA256 = "e7e38498c888107b42375cd1323afd2d97068747718bf239f1605bf6c9d09a16"
REVIEWED_FAILURE_FINGERPRINT = "4c5a9a35297f6443dc354da5f08d085bc0c845379cc629a6c26f6f698865ed4a"
_SOURCE_COMMIT = "8856a689a4767041dbfadab00f8da6907beef15d"
_STATUSES = ("pending", "running", "completed", "failed")
_EXPECTED_COUNTS = {"pending": 120, "running": 0, "completed": 0, "failed": 0}
_AUTHORITY = MappingProxyType(
    {
        "research_qualification": False,
        "controlled_evaluation": False,
        "protected_holdout": False,
        "paper_execution": False,
        "broker_writes": False,
        "live_execution": False,
    }
)


def intraday_exposed_004_plan_summary(repository: Path) -> dict[str, object]:
    plan = load_intraday_exposed_004_plan(repository.resolve())
    failure = _load_failure(repository)
    return {
        "program_id": PROGRAM_ID,
        "status": failure["classification"],
        "plan_sha256": plan.sha256,
        "plan_fingerprint": plan.plan_fingerprint,
        "plan_review_sha256": REVIEWED_PLAN_REVIEW_SHA256,
        "plan_review_fingerprint": REVIEWED_PLAN_REVIEW_FINGERPRINT,
        "parent_configuration_count": len(plan.configurations),
        "discovery_run_count": len(plan.configurations) * 2,
        "period_count": len(plan.periods),
        "latest_evaluation_bar": plan.periods[-1].evaluation_end,
        "default_workers": DEFAULT_RESEARCH_WORKERS,
        "launch_failure_sha256": REVIEWED_FAILURE_SHA256,
        "launch_failure_fingerprint": REVIEWED_FAILURE_FINGERPRINT,
        "successor_program_id": "intraday-exposed-005",
        "june_status": "ineligible-no-read-no-substitute",
        "authority": _AUTHORITY,
    }


def intraday_exposed_004_status(data_home: Path) -> dict[str, object]:
    runtime = data_home.resolve() / PROGRAM_ID
    database = runtime / DATABASE_NAME
    counts = {status: 0 for status in _STATUSES}
    attempts = 0
    failures: dict[str, int] = {}
    if database.exists():
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only = ON")
        try:
            for status, count in connection.execute(
                "SELECT status, COUNT(*) FROM research_runs GROUP BY status"
            ).fetchall():
                counts[str(status)] = int(count)
            attempts = int(
                connection.execute(
                    "SELECT COALESCE(SUM(attempt_count), 0) FROM research_runs"
                ).fetchone()[0]
            )
            for failure_class, count in connection.execute(
                "SELECT failure_class, COUNT(*) FROM research_runs "
                "WHERE failure_class IS NOT NULL GROUP BY failure_class"
            ).fetchall():
                failures[str(failure_class)] = int(count)
        finally:
            connection.close()
    evidence_matches = (
        database.is_file()
        and counts == _EXPECTED_COUNTS
        and attempts == 0
        and _sha256_path(database)
        == "9961bc06bc272ab6e7f772a192fe99876a8032ff0bfbf9f830a42715a14389a1"
    )
    return {
        "program_id": PROGRAM_ID,
        "database_exists": database.exists(),
        "run_counts": counts,
        "attempt_count": attempts,
        "failure_counts": failures,
        "terminal": True,
        "outcome": "aborted-before-attempt-task-transport-failure",
        "cohort_size": None,
        "evidence_matches_disposition": evidence_matches,
        "successor_program_id": "intraday-exposed-005",
        "authority": _AUTHORITY,
    }


def run_intraday_exposed_004_campaign(
    repository: Path,
    data_home: Path,
    *,
    workers: int = DEFAULT_RESEARCH_WORKERS,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    del repository, data_home, workers, progress
    raise ValueError(
        "Intraday Exposed 004 is immutable after its pre-attempt transport failure; "
        "use Intraday Exposed 005"
    )


def _load_failure(repository: Path) -> Mapping[str, Any]:
    path = repository.resolve() / FAILURE_RELATIVE_PATH
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != REVIEWED_FAILURE_SHA256:
        raise ValueError("Intraday Exposed 004 launch failure SHA-256 differs")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("Intraday Exposed 004 launch failure is invalid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("Intraday Exposed 004 launch failure differs")
    unsigned = dict(value)
    stored = unsigned.pop("failure_fingerprint", None)
    runtime = value.get("runtime")
    disposition = value.get("disposition")
    if (
        stored != REVIEWED_FAILURE_FINGERPRINT
        or fingerprint(unsigned) != REVIEWED_FAILURE_FINGERPRINT
        or value.get("schema_version") != "intraday-exposed-004-launch-failure-v1"
        or value.get("failure_id") != "intraday-exposed-004-launch-failure-v1"
        or value.get("program_id") != PROGRAM_ID
        or value.get("classification") != "aborted-before-attempt-task-transport-failure"
        or value.get("source_commit") != _SOURCE_COMMIT
        or value.get("authority") != _AUTHORITY
        or not isinstance(runtime, dict)
        or runtime.get("run_counts") != _EXPECTED_COUNTS
        or runtime.get("attempt_count") != 0
        or runtime.get("strategy_execution_started") is not False
        or not isinstance(disposition, dict)
        or disposition.get("terminal") is not True
        or disposition.get("action") != "preserve-do-not-retry-or-rebind"
        or disposition.get("successor_program_id") != "intraday-exposed-005"
    ):
        raise ValueError("Intraday Exposed 004 launch failure differs")
    return MappingProxyType(value)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


__all__ = [
    "DATABASE_NAME",
    "FAILURE_RELATIVE_PATH",
    "REVIEWED_FAILURE_FINGERPRINT",
    "REVIEWED_FAILURE_SHA256",
    "intraday_exposed_004_plan_summary",
    "intraday_exposed_004_status",
    "run_intraday_exposed_004_campaign",
]
