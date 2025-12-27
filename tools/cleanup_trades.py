#!/usr/bin/env python3
"""
Clean up trades.jsonl by removing ghost/phantom close events.

Removes entries that:
- Have no entry_px and no exit_px
- Have regime="unknown"
- Are clearly phantom closes
"""

import json
import sys
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from engine_alpha.core.paths import REPORTS

TRADES_PATH = REPORTS / "trades.jsonl"


def main():
    """Clean trades.jsonl by removing ghost events."""
    if not TRADES_PATH.exists():
        print(f"⚠️  {TRADES_PATH} not found, nothing to clean")
        return
    
    print("=" * 70)
    print("CLEANING TRADES.JSONL")
    print("=" * 70)
    print()
    
    # Read all trades
    all_trades = []
    try:
        with TRADES_PATH.open() as f:
            for line_num, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    all_trades.append((line_num, obj))
                except json.JSONDecodeError as e:
                    print(f"⚠️  Skipping invalid JSON on line {line_num}: {e}")
                    continue
    except Exception as e:
        print(f"❌ Error reading {TRADES_PATH}: {e}")
        return
    
    print(f"Total entries read: {len(all_trades)}")
    
    # Filter out ghost closes
    cleaned = []
    ghost_count = 0
    
    for line_num, obj in all_trades:
        trade_type = obj.get("type", "").lower()
        
        # Keep all "open" events
        if trade_type == "open":
            cleaned.append(obj)
            continue
        
        # For "close" events, check if they're ghosts
        if trade_type == "close":
            entry_px = obj.get("entry_px")
            exit_px = obj.get("exit_px")
            regime = obj.get("regime", "")
            pct = obj.get("pct", 0.0)
            
            # Reject ghost closes
            is_ghost = False
            
            # No prices at all
            if entry_px is None and exit_px is None:
                is_ghost = True
            
            # Unknown regime
            if regime == "unknown":
                is_ghost = True
            
            # Zero pct with no prices (likely ghost)
            if pct == 0.0 and entry_px is None and exit_px is None:
                is_ghost = True
            
            if is_ghost:
                ghost_count += 1
                if ghost_count <= 5:  # Show first 5 ghosts
                    print(f"  Removing ghost close on line {line_num}: regime={regime}, pct={pct}")
                continue
        
        # Keep all other entries
        cleaned.append(obj)
    
    print(f"Ghost closes removed: {ghost_count}")
    print(f"Clean entries kept: {len(cleaned)}")
    print()
    
    # Backup original file
    backup_path = TRADES_PATH.with_suffix(".jsonl.backup")
    try:
        import shutil
        shutil.copy2(TRADES_PATH, backup_path)
        print(f"✅ Backup created: {backup_path}")
    except Exception as e:
        print(f"⚠️  Could not create backup: {e}")
    
    # Write cleaned file
    try:
        with TRADES_PATH.open("w") as f:
            for obj in cleaned:
                f.write(json.dumps(obj) + "\n")
        print(f"✅ Cleaned trades written to {TRADES_PATH}")
    except Exception as e:
        print(f"❌ Error writing cleaned trades: {e}")
        return
    
    print()
    print("=" * 70)
    print("CLEANUP COMPLETE")
    print("=" * 70)
    print(f"Kept {len(cleaned)} real trades")
    print(f"Removed {ghost_count} ghost closes")
    print()


if __name__ == "__main__":
    main()

