#!/usr/bin/env python3
"""
Recovery Lane V2 CLI Tool (Phase 5H.2)
--------------------------------------

Runs recovery lane v2 evaluation and prints actions taken.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from engine_alpha.loop.recovery_lane_v2 import run_recovery_lane_v2


def main() -> int:
    """Run recovery lane v2 evaluation."""
    print("RECOVERY LANE V2 (Phase 5H.2)")
    print("=" * 70)
    
    result = run_recovery_lane_v2()
    
    action = result.get("action", "blocked")
    reason = result.get("reason", "")
    symbol = result.get("symbol")
    direction = result.get("direction")
    confidence = result.get("confidence")
    notional = result.get("notional_usd")
    entry_px = result.get("entry_px")
    exit_px = result.get("exit_px")
    pnl_pct = result.get("pnl_pct")
    
    print(f"Action: {action.upper()}")
    print(f"Reason: {reason}")
    
    if symbol:
        print(f"Symbol: {symbol}")
    
    if direction is not None:
        dir_str = "LONG" if direction == 1 else "SHORT" if direction == -1 else "NONE"
        print(f"Direction: {dir_str}")
    
    if confidence is not None:
        print(f"Confidence: {confidence:.2f}")
    
    if notional is not None:
        print(f"Notional: ${notional:.2f}")
    
    if entry_px is not None:
        print(f"Entry Price: ${entry_px:.4f}")
    
    if exit_px is not None:
        print(f"Exit Price: ${exit_px:.4f}")
    
    if pnl_pct is not None:
        print(f"PnL: {pnl_pct:+.2f}%")
    
    print()
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

