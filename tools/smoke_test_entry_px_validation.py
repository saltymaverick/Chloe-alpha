#!/usr/bin/env python3
"""
ENTRY_PX VALIDATION SMOKE TEST (TIME-SCOPED)

Fails ONLY if a recent OPEN event has entry_px <= 0 or == 1.0.
Default window: last 180 minutes.
Also prints historical corrupted count but does not fail on historical.
"""

import sys
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.reflect.trade_sanity import is_corrupted_trade_event

LOG_PATH = ROOT / "reports" / "trades.jsonl"
WINDOW_MINUTES = 180  # <-- adjust if desired

cutoff = datetime.now(timezone.utc) - timedelta(minutes=WINDOW_MINUTES)
bad = False
historical_count = 0

print("=" * 70)
print("ENTRY_PX VALIDATION SMOKE TEST (RECENT ONLY)")
print(f"Window: last {WINDOW_MINUTES} minutes")
print("=" * 70)

if not LOG_PATH.exists():
    print("\n✅ PASS: No trades.jsonl file (no recent corruption possible)")
    sys.exit(0)

with open(LOG_PATH, "r") as f:
    for i, line in enumerate(f, 1):
        try:
            evt = json.loads(line)
        except Exception:
            continue

        if evt.get("type") != "open":
            continue

        ts = evt.get("ts")
        if not ts:
            continue

        try:
            ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            continue

        # Check if corrupted
        if is_corrupted_trade_event(evt):
            if ts_dt < cutoff:
                # Historical corruption (outside window)
                historical_count += 1
            else:
                # Recent corruption (within window)
                bad = True
                print(
                    f"❌ BAD OPEN @ line {i}: "
                    f"symbol={evt.get('symbol')} "
                    f"timeframe={evt.get('timeframe')} "
                    f"entry_px={evt.get('entry_px')} "
                    f"ts={ts}"
                )

if bad:
    print("\n❌ FAIL: Recent invalid entry_px detected")
    if historical_count > 0:
        print(f"  (Historical corrupted events: {historical_count})")
    sys.exit(1)

print("\n✅ PASS: No invalid entry_px in recent OPEN events")
if historical_count > 0:
    print(f"  (Historical corrupted events: {historical_count} - excluded from analytics)")
sys.exit(0)
