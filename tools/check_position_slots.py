#!/usr/bin/env python3
"""
Position slot diagnostic.
Prints open positions (core/exploration) and recovery lane positions separately.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"

POSITION_STATE_PATH = REPORTS / "position_state.json"
RECOVERY_STATE_PATH = REPORTS / "loop" / "recovery_lane_v2_state.json"
SYMBOL_STATES_PATH = REPORTS / "risk" / "symbol_states.json"
ENGINE_CONFIG_PATH = ROOT / "config" / "engine_config.json"


def _read_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def main() -> int:
    cfg = _read_json(ENGINE_CONFIG_PATH)
    cfg_tf = (cfg.get("timeframe") or "15m").lower() if isinstance(cfg, dict) else None

    pos_state = _read_json(POSITION_STATE_PATH)
    positions = pos_state.get("positions", {})
    open_core = {
        k: v for k, v in positions.items() if isinstance(v, dict) and (v.get("dir") or 0) != 0
    }
    open_core_no_recovery = {k: v for k, v in open_core.items() if v.get("trade_kind") != "recovery_v2"}
    open_core_exploration = {k: v for k, v in open_core_no_recovery.items() if v.get("trade_kind") == "exploration"}
    open_core_normal = {k: v for k, v in open_core_no_recovery.items() if v.get("trade_kind") not in {"exploration"}}

    recovery_state = _read_json(RECOVERY_STATE_PATH)
    if recovery_state:
        open_recovery = {
            k: v
            for k, v in (recovery_state.get("open_positions") or {}).items()
            if (v.get("direction") or 0) != 0
        }
    else:
        open_recovery = {}

    symbol_states = _read_json(SYMBOL_STATES_PATH)

    print("=== position_state.json open (all) ===")
    print(json.dumps(open_core, indent=2))
    print("\n=== position_state.json open (exclude recovery_v2) ===")
    print(json.dumps(open_core_no_recovery, indent=2))
    print("\n=== position_state.json open (exploration only) ===")
    print(json.dumps(open_core_exploration, indent=2))
    print("\n=== position_state.json open (core lane only) ===")
    print(json.dumps(open_core_normal, indent=2))
    print(
        f"\ncounts: all={len(open_core)} exclude_recovery={len(open_core_no_recovery)} "
        f"exploration={len(open_core_exploration)} core={len(open_core_normal)}"
    )

    print("\n=== recovery_lane_v2_state.json open ===")
    print(json.dumps(open_recovery, indent=2))
    print(f"\ncounts: recovery_open={len(open_recovery)}")

    if symbol_states:
        print("\n=== symbol_states.json (caps and allowances) ===")
        symbols = symbol_states.get("symbols") or {}
        for k, v in symbols.items():
            caps = (v.get("caps_by_lane") or {}).get("core", {})
            print(
                f"{k}: allow_core={v.get('allow_core')} allow_exploration={v.get('allow_exploration')} "
                f"allow_recovery={v.get('allow_recovery')} caps={caps}"
            )
    # Warning for mismatched timeframes (only core positions)
    if cfg_tf:
        mismatched = {
            k: v for k, v in open_core_normal.items() if (v.get("timeframe") or "").lower() != cfg_tf
        }
        if mismatched:
            print("\nWARNING: core positions with timeframe != config.timeframe")
            print(json.dumps(mismatched, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

