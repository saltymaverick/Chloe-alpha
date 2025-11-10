#!/usr/bin/env python3
"""Position Doctor - inspect or reset live position state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from engine_alpha.core.paths import REPORTS

POSITION_PATH = REPORTS / "position_state.json"


def _load_state() -> Dict[str, Any]:
    if not POSITION_PATH.exists():
        return {}
    try:
        return json.loads(POSITION_PATH.read_text())
    except Exception:
        return {}


def _reset_state() -> None:
    payload = {"dir": 0, "bars_open": 0, "entry_px": None}
    POSITION_PATH.parent.mkdir(parents=True, exist_ok=True)
    POSITION_PATH.write_text(json.dumps(payload, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect or reset live position state.")
    parser.add_argument("--reset", action="store_true", help="Reset the position state to flat.")
    args = parser.parse_args()

    if args.reset:
        _reset_state()
        print("Position state reset to flat.")
        return 0

    state = _load_state()
    if not state:
        print("Position state: (empty)")
        return 0

    print("Position state:")
    print(json.dumps(state, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
