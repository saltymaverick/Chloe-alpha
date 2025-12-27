#!/usr/bin/env python3
"""
Debug script to detect scratch exits in trades log.
Scans last 200 closes and reports any tp/sl/drop closes with fallback pricing.
"""

import json
import sys
from pathlib import Path

def main():
    trades_file = Path("reports/trades.jsonl")
    if not trades_file.exists():
        print("ERROR: reports/trades.jsonl not found")
        return 1

    scratch_closes = []
    total_closes = 0

    try:
        with open(trades_file, "r") as f:
            lines = f.readlines()

        # Check last 200 lines for closes
        for line in lines[-200:]:
            if not line.strip():
                continue
            try:
                trade = json.loads(line.strip())
                if trade.get("type") == "close":
                    total_closes += 1
                    exit_reason = trade.get("exit_reason", "")
                    exit_px_source = trade.get("exit_px_source", "")
                    entry_px = trade.get("entry_px")
                    exit_px = trade.get("exit_px")

                    # Check for scratch conditions
                    is_scratch = False
                    reasons = []

                    if exit_reason in ("tp", "sl", "drop", "flip"):
                        if exit_px_source == "position_fallback":
                            is_scratch = True
                            reasons.append("position_fallback")
                        if entry_px is not None and exit_px is not None and entry_px == exit_px:
                            is_scratch = True
                            reasons.append("exit_px==entry_px")

                    if is_scratch:
                        scratch_closes.append({
                            "ts": trade.get("ts"),
                            "symbol": trade.get("symbol"),
                            "exit_reason": exit_reason,
                            "exit_px_source": exit_px_source,
                            "entry_px": entry_px,
                            "exit_px": exit_px,
                            "reasons": reasons
                        })

            except json.JSONDecodeError:
                continue

    except Exception as e:
        print(f"ERROR reading trades file: {e}")
        return 1

    # Report results
    print(f"Scanned {total_closes} closes, found {len(scratch_closes)} scratches")
    print()

    if scratch_closes:
        print("🚨 SCRATCH EXITS FOUND:")
        for scratch in scratch_closes[-10:]:  # Show last 10
            print(f"  {scratch['ts']} {scratch['symbol']} {scratch['exit_reason']} "
                  f"src={scratch['exit_px_source']} "
                  f"px={scratch['entry_px']}→{scratch['exit_px']} "
                  f"reasons={scratch['reasons']}")
        print()
        print(f"❌ EXIT CODE 1: {len(scratch_closes)} scratches found")
        return 1
    else:
        print("✅ NO SCRATCH EXITS FOUND")
        return 0

if __name__ == "__main__":
    sys.exit(main())
