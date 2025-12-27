#!/usr/bin/env python3
"""
One-shot sanitizer for reports/loop/recovery_lane_v2_state.json.

Purpose:
  - Remove stale entries in state["positions"] when the authoritative
    state["open_positions"][symbol]["direction"] == 0 (flat).

This is ops-only hygiene to prevent confusing "fake open" metadata from
persisting after closes or restarts.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict

from engine_alpha.core.atomic_io import atomic_write_json
from engine_alpha.core.paths import REPORTS


STATE_PATH = REPORTS / "loop" / "recovery_lane_v2_state.json"


def _load_json(path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def sanitize_state(state: Dict[str, Any]) -> tuple[Dict[str, Any], int]:
    """
    Returns:
      (updated_state, n_positions_removed)
    """
    open_positions = state.get("open_positions", {})
    positions = state.get("positions", {})

    if not isinstance(open_positions, dict) or not isinstance(positions, dict):
        return state, 0

    removed = 0
    for sym in list(positions.keys()):
        op = open_positions.get(sym, {})
        direction = 0
        if isinstance(op, dict):
            direction = op.get("direction", 0) or 0
        # Authoritative: if missing from open_positions, treat as closed for hygiene.
        if direction == 0:
            try:
                del positions[sym]
                removed += 1
            except Exception:
                pass

    state["positions"] = positions
    state["sanitized_at"] = datetime.now(timezone.utc).isoformat()
    return state, removed


def main() -> int:
    state = _load_json(STATE_PATH)
    if not state:
        print(f"No state found at {STATE_PATH} (nothing to do).")
        return 0

    updated, removed = sanitize_state(state)
    atomic_write_json(STATE_PATH, updated)
    print(f"Sanitized {STATE_PATH}: removed_positions={removed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


