"""Small repository secret guard for names-only configuration policy."""

from __future__ import annotations

import csv
import io
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from json import JSONDecodeError, loads
from pathlib import Path
from typing import Any

PATTERNS = (
    re.compile(r"(?i)(?:secret|token|password|api[_-]?key)\s*=\s*['\"][^'\"]+['\"]"),
    re.compile(r"(?m)^\s*(?:APCA_API_KEY_ID|APCA_API_SECRET_KEY)\s*=\s*\S+"),
    re.compile(r"(?m)^\s*(?:export\s+)?PROGRAM_00[567]_ALPACA_API_(?:KEY_ID|SECRET_KEY)\s*=\s*\S+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
PROGRAM_JSON_CREDENTIAL = re.compile(
    r"""["']PROGRAM_00[567]_ALPACA_API_(?:KEY_ID|SECRET_KEY)["']\s*:\s*\S+"""
)

PRIVATE_MARKET_DATA_SUFFIXES = frozenset(
    {
        ".arrow",
        ".csv",
        ".db",
        ".feather",
        ".json",
        ".jsonl",
        ".parquet",
        ".sqlite",
        ".sqlite3",
    }
)
PRIVATE_BINARY_DATA_SUFFIXES = frozenset(
    {".arrow", ".db", ".feather", ".parquet", ".sqlite", ".sqlite3"}
)
PUBLIC_MARKET_DATA_ROOTS = (
    "data/",
    "datasets/",
    "market-data/",
    "program-005-free-alpaca/",
    "program-006-free-alpaca/",
    "program-007-free-alpaca/",
    "raw-data/",
)
PUBLIC_PROGRAM_JSON = frozenset(
    {
        "config/research/program-005-alpaca-public-contract-evidence-v1.json",
        "config/research/program-005-authority-binding-repair-implementation-independent-review-v1.json",
        "config/research/program-005-corporate-action-ledger-v1.json",
        "config/research/program-005-free-alpaca-successor-plan-independent-review-v1.json",
        "config/research/program-005-free-alpaca-successor-plan-v1.json",
        "config/research/program-005-private-data-retention-policy-v1.json",
        "config/research/program-005-public-dataset-contract-v1.json",
        "config/research/program-005-source-qualification-authority-proposal-v1.json",
        "config/research/program-005-source-qualification-authority-proposal-independent-review-v2.json",
        "config/research/program-005-source-qualification-authority-proposal-v2.json",
        "config/research/program-005-source-qualification-readiness-independent-review-v1.json",
        "config/research/program-005-source-qualification-terminal-failure-independent-review-v1.json",
        "config/research/program-005-source-qualification-terminal-failure-v1.json",
        "config/research/program-006-credential-safe-qualification-implementation-independent-review-v1.json",
        "config/research/program-006-credential-safe-qualification-implementation-independent-review-v2.json",
        "config/research/program-006-source-qualification-forensic-analysis-independent-review-v1.json",
        "config/research/program-006-source-qualification-forensic-analysis-v1.json",
        "config/research/program-006-source-qualification-authority-proposal-independent-review-v1.json",
        "config/research/program-006-source-qualification-authority-proposal-independent-review-v2.json",
        "config/research/program-006-source-qualification-authority-proposal-v1.json",
        "config/research/program-006-source-qualification-authority-proposal-v2.json",
        "config/research/program-006-source-qualification-terminal-failure-independent-review-v1.json",
        "config/research/program-006-source-qualification-terminal-failure-v1.json",
        "config/research/program-007-unit-changing-action-ledger-v1.json",
        "config/research/program-007-unit-changing-action-ledger-v1.schema.json",
        "config/research/program-007-unit-changing-action-ledger-v2.json",
        "config/research/program-007-unit-changing-action-ledger-v2.schema.json",
        "config/research/program-007-nyse-corpax-retrieval-manifest-v1.json",
        "config/research/program-007-raw-source-contract-implementation-v1.json",
        "config/research/program-007-alpaca-raw-source-qualification-proposal-v1.json",
    }
)
_PROVIDER_BAR_KEYS = frozenset({"t", "o", "h", "l", "c", "v"})
_CANONICAL_BAR_KEYS = frozenset({"timestamp", "symbol", "open", "high", "low", "close", "volume"})


def _contains_market_observation(value: Any) -> bool:
    if isinstance(value, Mapping):
        keys = {str(key).lower() for key in value}
        if keys >= _PROVIDER_BAR_KEYS or keys >= _CANONICAL_BAR_KEYS:
            return True
        return any(_contains_market_observation(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return any(_contains_market_observation(item) for item in value)
    return False


def _contains_json_market_observation(text: str, suffix: str) -> bool:
    try:
        values = (
            [loads(line) for line in text.splitlines() if line.strip()]
            if suffix == ".jsonl"
            else [loads(text)]
        )
    except JSONDecodeError:
        return False
    return any(_contains_market_observation(value) for value in values)


def _contains_csv_market_observation(text: str) -> bool:
    try:
        reader = csv.DictReader(io.StringIO(text))
        keys = {str(key).strip().lower() for key in reader.fieldnames or ()}
        has_bar_schema = keys >= _PROVIDER_BAR_KEYS or keys >= _CANONICAL_BAR_KEYS
        return has_bar_schema and next(reader, None) is not None
    except csv.Error:
        return False


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [Path(name) for name in result.stdout.splitlines()]


def main() -> int:
    findings: list[str] = []
    paths = tracked_files()
    for path in paths:
        normalized = path.as_posix().lower()
        suffix = path.suffix.lower()
        if (
            suffix in PRIVATE_BINARY_DATA_SUFFIXES
            or normalized.startswith(PUBLIC_MARKET_DATA_ROOTS)
            or (
                any(
                    program in normalized
                    for program in ("program-005", "program-006", "program-007")
                )
                and suffix in PRIVATE_MARKET_DATA_SUFFIXES
                and normalized not in PUBLIC_PROGRAM_JSON
            )
        ):
            findings.append(f"{path}:private-market-data-path")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if (suffix in {".json", ".jsonl"} and _contains_json_market_observation(text, suffix)) or (
            suffix == ".csv" and _contains_csv_market_observation(text)
        ):
            findings.append(f"{path}:private-market-data-content")
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if any(pattern.search(line) for pattern in PATTERNS) or (
                suffix in {".json", ".jsonl"} and PROGRAM_JSON_CREDENTIAL.search(line)
            ):
                findings.append(f"{path}:{number}")
    if findings:
        print("possible secrets found:\n" + "\n".join(findings), file=sys.stderr)
        return 1
    print(f"secret check passed ({len(paths)} files scanned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
