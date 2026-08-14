from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

from systematic_trading_lab.rapid_store import RapidResearchStore

RAPID_MODULES = (
    "rapid_data.py",
    "rapid_research.py",
    "rapid_store.py",
    "rapid_strategies.py",
    "strategy_registry.py",
)
FORBIDDEN = (
    "alpaca_paper",
    "broker_events",
    "execution",
    "experiment_runner",
    "experiments",
    "intraday_v3",
    "orders",
    "paper",
    "qualification",
    "reconciliation",
    "risk",
)


def test_rapid_modules_do_not_import_protected_authority_modules() -> None:
    root = Path("src/systematic_trading_lab")
    imports: list[tuple[str, str]] = []
    for name in RAPID_MODULES:
        for node in ast.walk(ast.parse((root / name).read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.append((name, node.module))
            elif isinstance(node, ast.Import):
                imports.extend((name, alias.name) for alias in node.names)

    violations = [
        (source, imported)
        for source, imported in imports
        if imported.split(".")[-1].startswith(FORBIDDEN)
    ]
    assert violations == []


def test_rapid_store_uses_only_its_own_database_namespace(tmp_path: Path) -> None:
    store = RapidResearchStore(tmp_path)

    with sqlite3.connect(store.path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        }

    assert tables == {"rapid_datasets", "rapid_runs"}
    assert store.path == tmp_path / "rapid-research.sqlite3"
    assert not (tmp_path / "experiments.sqlite3").exists()
    assert not (tmp_path / "execution.sqlite3").exists()
