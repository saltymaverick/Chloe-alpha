#!/usr/bin/env python3
"""
Recovery Lane CLI Tool (Phase 5H)
----------------------------------

Runs recovery lane evaluation and prints actions taken.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from engine_alpha.loop.recovery_lane import run_recovery_lane


def main() -> int:
    """Run recovery lane evaluation."""
    print("RECOVERY LANE (Phase 5H)")
    print("=" * 70)
    
    result = run_recovery_lane()
    
    action = result.get("action", "blocked")
    reason = result.get("reason", "")
    symbol = result.get("symbol")
    direction = result.get("direction")
    confidence = result.get("confidence")
    notional = result.get("notional_usd")
    
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
    
    print()
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

