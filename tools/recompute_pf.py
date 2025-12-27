#!/usr/bin/env python3
"""
Recompute PF from cleaned trades.jsonl.

Only counts "close" events with valid pct values.
"""

import json
import sys
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from engine_alpha.core.paths import REPORTS

TRADES_PATH = REPORTS / "trades.jsonl"
PF_LOCAL_PATH = REPORTS / "pf_local.json"


def main():
    """Recompute PF from cleaned trades."""
    print("=" * 70)
    print("RECOMPUTING PF")
    print("=" * 70)
    print()
    
    if not TRADES_PATH.exists():
        print(f"⚠️  {TRADES_PATH} not found")
        return
    
    # Read all trades
    trades = []
    try:
        with TRADES_PATH.open() as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("type", "").lower() == "close":
                        trades.append(obj)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"❌ Error reading {TRADES_PATH}: {e}")
        return
    
    print(f"Total close events: {len(trades)}")
    
    # Filter valid trades (must have pct)
    valid_trades = [t for t in trades if "pct" in t and t["pct"] is not None]
    
    if not valid_trades:
        print("⚠️  No valid trades found")
        pf = 0.0
        count = 0
    else:
        # Compute PF
        wins = [t for t in valid_trades if float(t["pct"]) > 0]
        losses = [t for t in valid_trades if float(t["pct"]) < 0]
        
        win_sum = sum(float(t["pct"]) for t in wins)
        loss_sum = abs(sum(float(t["pct"]) for t in losses))
        
        if loss_sum > 0:
            pf = win_sum / loss_sum
        else:
            pf = float("inf") if win_sum > 0 else 0.0
        
        count = len(valid_trades)
        
        print(f"  Wins: {len(wins)}")
        print(f"  Losses: {len(losses)}")
        print(f"  Win sum: {win_sum:.6f}")
        print(f"  Loss sum: {loss_sum:.6f}")
    
    # Write PF report
    pf_obj = {
        "pf": pf if pf != float("inf") else 999.0,
        "window": 150,
        "count": count
    }
    
    try:
        PF_LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with PF_LOCAL_PATH.open("w") as f:
            json.dump(pf_obj, f, indent=2)
        print(f"✅ PF recomputed: {pf_obj['pf']:.3f}, trades={count}")
        print(f"✅ Written to {PF_LOCAL_PATH}")
    except Exception as e:
        print(f"❌ Error writing PF: {e}")
        return
    
    print()
    print("=" * 70)
    print("RECOMPUTATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()

