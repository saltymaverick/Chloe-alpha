#!/usr/bin/env python3
"""
Trim Core Positions Tool
========================

Removes excess core positions to enforce slot limits.
Closes oldest positions first (by entry_ts, fallback last_ts).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.core.config_loader import load_engine_config
from engine_alpha.core.paths import REPORTS
from engine_alpha.loop.execute_trade import close_now


def _parse_ts(ts_str: str) -> datetime:
    """Parse timestamp string to datetime."""
    if not ts_str:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        # Handle various timestamp formats
        if ts_str.endswith('Z'):
            ts_str = ts_str[:-1] + '+00:00'
        return datetime.fromisoformat(ts_str)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def trim_core_positions() -> int:
    """
    Trim core positions to enforce slot limits.
    Returns number of positions closed.
    """
    # Load slot limits
    cfg = load_engine_config()
    slot_limits = cfg.get("slot_limits", {}).get("core", {})
    max_total = slot_limits.get("max_positions_total", 4)

    # Load positions
    pos_path = REPORTS / "position_state.json"
    if not pos_path.exists():
        print("No position_state.json found")
        return 0

    with pos_path.open("r") as f:
        pos_data = json.load(f)

    positions = pos_data.get("positions", {})

    # Filter core positions (trade_kind == "normal", not recovery_v2)
    core_positions: List[Tuple[str, Dict[str, Any]]] = []
    for key, pos in positions.items():
        if isinstance(pos, dict):
            trade_kind = pos.get("trade_kind", "")
            if trade_kind == "normal" and pos.get("dir", 0) != 0:
                core_positions.append((key, pos))

    core_count = len(core_positions)
    print(f"Found {core_count} core positions, limit is {max_total}")

    if core_count <= max_total:
        print("No trimming needed")
        return 0

    # Sort by entry_ts (oldest first), fallback to last_ts
    def sort_key(item):
        key, pos = item
        entry_ts = _parse_ts(pos.get("entry_ts", ""))
        last_ts = _parse_ts(pos.get("last_ts", ""))
        return entry_ts or last_ts

    core_positions.sort(key=sort_key)

    # Close excess positions (oldest first)
    to_close = core_count - max_total
    closed = []

    for i in range(to_close):
        key, pos = core_positions[i]
        symbol = pos.get("symbol", key.split("_")[0])
        timeframe = pos.get("timeframe", "15m")

        try:
            close_now(
                symbol=symbol,
                timeframe=timeframe,
                reason="trim_to_core_limit",
                exit_reason="trim_to_core_limit",
                exit_label="trim_to_core_limit",
                dir=pos.get("dir"),
                entry_price=pos.get("entry_px")
            )
            closed.append(f"{symbol}_{timeframe}")
            print(f"Closed {symbol}_{timeframe}")
        except Exception as e:
            print(f"Failed to close {symbol}_{timeframe}: {e}")

    remaining = max_total
    print(f"TRIM_CORE closed={len(closed)} remaining={remaining}")

    return len(closed)


def main() -> int:
    """Main entry point."""
    try:
        closed_count = trim_core_positions()
        return 0 if closed_count >= 0 else 1
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
