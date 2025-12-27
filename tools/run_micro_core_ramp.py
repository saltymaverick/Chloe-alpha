#!/usr/bin/env python3
"""
Micro Core Ramp CLI Tool (Phase 5H.4)
---------------------------------------

Runs one evaluation tick of micro core ramp.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from engine_alpha.loop.micro_core_ramp import run_micro_core_ramp


def main() -> int:
    """Main entry point."""
    result = run_micro_core_ramp()
    
    action = result.get("action", "unknown")
    reason = result.get("reason", "")
    symbol = result.get("symbol", "")
    
    if action == "opened":
        print(f"✓ Micro Core Ramp: OPENED {symbol} (conf={result.get('confidence', 0.0):.3f})")
    elif action == "closed":
        print(f"✓ Micro Core Ramp: CLOSED {symbol} ({reason}, PnL={result.get('pnl_pct', 0.0):+.2f}%)")
    else:
        print(f"• Micro Core Ramp: {action.upper()} ({reason})")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

