"""Small repository secret guard for names-only configuration policy."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = (
    re.compile(r"(?i)(?:secret|token|password|api[_-]?key)\s*=\s*['\"][^'\"]+['\"]"),
    re.compile(r"(?m)^\s*(?:APCA_API_KEY_ID|APCA_API_SECRET_KEY)\s*=\s*\S+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


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
    for path in tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if any(pattern.search(line) for pattern in PATTERNS):
                findings.append(f"{path}:{number}")
    if findings:
        print("possible secrets found:\n" + "\n".join(findings), file=sys.stderr)
        return 1
    print(f"secret check passed ({len(tracked_files())} files scanned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
