#!/usr/bin/env python3
"""
Backfill regime into existing positions that don't have it.
Safe one-time script to patch position_state.json with regime data.
"""

import json
import os
from pathlib import Path
from datetime import datetime

def backfill_regimes():
    """Add regime to positions missing it in position_state.json"""

    position_file = Path("reports/position_state.json")
    if not position_file.exists():
        print("No position_state.json found - nothing to backfill")
        return

    # Load current positions
    try:
        with open(position_file, "r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error loading position_state.json: {e}")
        return

    positions = data.get("positions", {})
    if not positions:
        print("No positions to backfill")
        return

    modified = False

    # Try to get current regime from various sources
    current_regime = "unknown"

    # Try regime_snapshot.json first
    regime_snapshot = Path("reports/regime_snapshot.json")
    if regime_snapshot.exists():
        try:
            with open(regime_snapshot, "r") as f:
                regime_data = json.load(f)
                current_regime = regime_data.get("regime", "unknown")
        except Exception:
            pass

    # Fallback to last known regime from trades
    if current_regime == "unknown":
        trades_file = Path("reports/trades.jsonl")
        if trades_file.exists():
            try:
                with open(trades_file, "r") as f:
                    lines = f.readlines()
                    for line in reversed(lines[-1000:]):  # Check last 1000 trades
                        try:
                            trade = json.loads(line.strip())
                            if trade.get("type") == "open" and trade.get("regime"):
                                current_regime = trade.get("regime")
                                break
                        except:
                            continue
            except Exception:
                pass

    print(f"Using regime '{current_regime}' for backfill")

    # Backfill missing regimes
    for pos_key, pos_data in positions.items():
        if not isinstance(pos_data, dict):
            continue

        has_regime = "regime" in pos_data
        has_regime_at_entry = "regime_at_entry" in pos_data

        if not has_regime or not has_regime_at_entry:
            print(f"Backfilling regime for position {pos_key}")
            pos_data["regime"] = pos_data.get("regime", current_regime)
            pos_data["regime_at_entry"] = pos_data.get("regime_at_entry", current_regime)
            modified = True

    if modified:
        # Write back atomically
        temp_file = position_file.with_suffix('.tmp')
        try:
            with open(temp_file, "w") as f:
                json.dump(data, f, indent=2)

            temp_file.replace(position_file)
            print(f"Backfilled regimes in {len(positions)} positions")
        except Exception as e:
            print(f"Error writing backfilled data: {e}")
            if temp_file.exists():
                temp_file.unlink()
    else:
        print("No positions needed backfilling")

if __name__ == "__main__":
    backfill_regimes()
