# engine_alpha/loop/position_manager.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from engine_alpha.core.paths import REPORTS

_position = {"dir": 0, "entry_px": None, "bars_open": 0}
POSITION_STATE_PATH = REPORTS / "position_state.json"


def get_open_position():
    return dict(_position) if _position["dir"] != 0 else None


def set_position(p):
    global _position
    _position = dict(p)


def clear_position():
    global _position
    _position = {"dir": 0, "entry_px": None, "bars_open": 0}


def get_live_position() -> Optional[Dict[str, Any]]:
    if not POSITION_STATE_PATH.exists():
        return None
    try:
        data = json.loads(POSITION_STATE_PATH.read_text())
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    dir_val = data.get("dir")
    bars_open = data.get("bars_open")
    if not isinstance(dir_val, (int, float)) or dir_val == 0:
        return None
    try:
        bars = int(bars_open)
    except (TypeError, ValueError):
        bars = 0
    entry_px = data.get("entry_px")
    try:
        entry_px = float(entry_px) if entry_px is not None else None
    except (TypeError, ValueError):
        entry_px = None
    return {
        "dir": int(dir_val),
        "bars_open": max(0, bars),
        "entry_px": entry_px,
        "last_ts": data.get("last_ts"),
    }


def set_live_position(position: Dict[str, Any]) -> None:
    payload = {
        "dir": int(position.get("dir", 0)),
        "bars_open": int(position.get("bars_open", 0)),
        "entry_px": position.get("entry_px"),
        "last_ts": position.get("last_ts"),
    }
    POSITION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    POSITION_STATE_PATH.write_text(json.dumps(payload, indent=2))


def clear_live_position() -> None:
    POSITION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    POSITION_STATE_PATH.write_text(json.dumps({"dir": 0, "bars_open": 0, "entry_px": None}, indent=2))
