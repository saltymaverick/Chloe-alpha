#!/usr/bin/env python3
"""
Dashboard health check utility.
Validates syntax, import readiness, and helper presence for dashboard.py.
"""

from __future__ import annotations

import ast
import os
import runpy
import sys
from pathlib import Path
from typing import Set

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = ROOT / "engine_alpha" / "dashboard" / "dashboard.py"


def _check_syntax(path: Path) -> ast.AST | None:
    try:
        source = path.read_text()
    except Exception as exc:
        print(f"Read error: {exc}")
        return None
    try:
        tree = ast.parse(source, filename=str(path))
        print("Syntax: OK")
        return tree
    except Exception as exc:
        print(f"Syntax error: {exc}")
        return None


def _check_imports(tree: ast.AST) -> None:
    required = {"REPORTS", "LOGS", "DATA"}
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "engine_alpha.core.paths":
            names = {alias.name for alias in node.names}
            if required.issubset(names):
                found = True
                break
    if found:
        print("Imports: engine_alpha.core.paths (REPORTS/LOGS/DATA) present")
    else:
        print("Import warning: expected 'from engine_alpha.core.paths import REPORTS, LOGS, DATA'")


def _check_helpers(tree: ast.AST) -> None:
    required_helpers: Set[str] = {"load_json", "jsonl_tail", "load_equity_df"}
    defined = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    missing = sorted(required_helpers - defined)
    if missing:
        print(f"Helper warning: missing helper(s): {', '.join(missing)}")
    else:
        print("Helpers: load_json/jsonl_tail/load_equity_df present")


def _check_import_execution(path: Path) -> None:
    os.environ["CHLOE_DASH_HEALTHCHECK"] = "1"
    try:
        runpy.run_path(str(path), run_name="__check__")
        print("Import: OK")
    except Exception as exc:
        print(f"Import warning: {exc}")


def main() -> int:
    if not DASHBOARD_PATH.exists():
        print(f"Dashboard file not found at {DASHBOARD_PATH}")
        return 0

    tree = _check_syntax(DASHBOARD_PATH)
    if tree is not None:
        _check_imports(tree)
        _check_helpers(tree)

    _check_import_execution(DASHBOARD_PATH)
    print("Dashboard health check complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

