#!/usr/bin/env python3
"""Diagnostic runner for auto-apply pipeline (Phase 32)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from engine_alpha.core import auto_apply
from engine_alpha.core.paths import REPORTS


def _read_audit_tail(path: Path, lines: int = 3) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw_lines = path.read_text().splitlines()
    except Exception:
        return []
    tail = raw_lines[-lines:]
    out: List[Dict[str, Any]] = []
    for item in tail:
        item = item.strip()
        if not item:
            continue
        try:
            out.append(json.loads(item))
        except Exception:
            continue
    return out


def main() -> int:
    print("== Chloe Auto-Apply (paper-only) timer diagnostic ==")
    print("If run by systemd: daily at 03:25 UTC")
    summary = auto_apply.run_once()
    print(json.dumps(summary, indent=2))

    audit_tail = _read_audit_tail(REPORTS / "auto_apply_audit.jsonl", lines=3)
    if audit_tail:
        print("--- Audit tail (last 3) ---")
        for entry in audit_tail:
            print(json.dumps(entry, indent=2))
    else:
        print("No audit entries yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
