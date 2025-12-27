#!/usr/bin/env python3
"""
Count Corrupted Trade Events
-----------------------------

Counts corrupted trade events (entry_px=1.0 or entry_px_invalid=True) 
in reports/trades.jsonl over different time windows.
"""

import sys
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.trade_sanity import is_corrupted_trade_event

TRADES_PATH = REPORTS / "trades.jsonl"


def count_corrupted_in_window(window_days: int) -> int:
    """Count corrupted events in the last N days."""
    if not TRADES_PATH.exists():
        return 0
    
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    count = 0
    
    with TRADES_PATH.open("r") as f:
        for line in f:
            try:
                evt = json.loads(line.strip())
            except Exception:
                continue
            
            # Check timestamp
            ts = evt.get("ts")
            if not ts:
                continue
            
            try:
                ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                continue
            
            if ts_dt < cutoff:
                continue
            
            # Check if corrupted
            if is_corrupted_trade_event(evt):
                count += 1
    
    return count


def main():
    """Main entry point."""
    print("=" * 70)
    print("CORRUPTED TRADE EVENTS COUNT")
    print("=" * 70)
    print()
    
    windows = [
        (1, "24h"),
        (7, "7d"),
        (30, "30d"),
    ]
    
    for days, label in windows:
        count = count_corrupted_in_window(days)
        print(f"Last {label:>4}: {count:>4} corrupted events")
    
    print()
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

