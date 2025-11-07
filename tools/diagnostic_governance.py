#!/usr/bin/env python3
"""
Governance diagnostic - Phase 21
Runs governance vote calculation and prints module scores.
"""

from __future__ import annotations

import json

from engine_alpha.core.governor import run_once
from engine_alpha.core.paths import REPORTS


def main():
    result = run_once()
    modules = result.get("modules", {})
    for name, info in modules.items():
        print(f"{name}: score={info.get('score')} note={info.get('note')}")
    print(f"SCI={result.get('sci')} recommendation={result.get('recommendation')}")
    snapshot_path = REPORTS / "governance_snapshot.json"
    snapshot_path.write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
