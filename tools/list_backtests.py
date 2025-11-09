#!/usr/bin/env python3
"""
List recorded backtest runs (Phase 27 helper).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

from engine_alpha.core.paths import REPORTS


def _load_runs(path: Path) -> List[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def main() -> None:
    index_path = REPORTS / "backtest" / "index.json"
    runs = _load_runs(index_path)
    runs.sort(key=lambda item: item.get("ts", ""), reverse=True)
    print(json.dumps(runs, indent=2))


if __name__ == "__main__":
    main()

