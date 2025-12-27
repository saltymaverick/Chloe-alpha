#!/usr/bin/env python3
"""
Recovery Lane V2 Status Tool (Phase 5H.2)
------------------------------------------

Shows current recovery position status and recent trade log.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.core.paths import REPORTS
from engine_alpha.loop.recovery_lane_v2_trades import RECOVERY_TRADES_PATH


def _load_json(path: Path) -> dict:
    """Load JSON file."""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _tail_jsonl(path: Path, n: int = 10) -> list:
    """Tail JSONL file."""
    if not path.exists():
        return []
    try:
        lines = path.read_text().splitlines()
        events = []
        for line in lines[-n:]:
            if line.strip():
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
        return events
    except Exception:
        return []


def main() -> int:
    """Main entry point."""
    state_path = REPORTS / "loop" / "recovery_lane_v2_state.json"
    
    print("RECOVERY LANE V2 STATUS (Phase 5H.2)")
    print("=" * 70)
    print()
    
    state = _load_json(state_path)
    
    # Check for open positions
    open_positions = state.get("open_positions", {})
    positions = state.get("positions", {})
    
    has_open = False
    for symbol, pos_data in open_positions.items():
        if pos_data.get("direction", 0) != 0:
            has_open = True
            
            # Get full position data
            full_pos = positions.get(symbol, pos_data)
            entry_price = pos_data.get("entry_price", 0.0)
            entry_ts = pos_data.get("entry_ts", "")
            direction = pos_data.get("direction", 0)
            confidence = pos_data.get("confidence", 0.0)
            notional_usd = full_pos.get("notional_usd", 0.0)
            tp_pct = full_pos.get("tp_pct", 0.002) * 100.0
            sl_pct = full_pos.get("sl_pct", 0.0015) * 100.0
            max_hold_seconds = full_pos.get("max_hold_seconds", 2700)
            
            # Calculate age
            age_str = "—"
            age_seconds = 0
            if entry_ts:
                try:
                    entry_time = datetime.fromisoformat(entry_ts.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
                    now = datetime.now(timezone.utc)
                    age_seconds = int((now - entry_time).total_seconds())
                    age_minutes = age_seconds // 60
                    age_str = f"{age_minutes}m"
                except Exception:
                    pass
            
            dir_str = "LONG" if direction == 1 else "SHORT" if direction == -1 else "FLAT"
            
            print(f"Open Recovery Position:")
            print(f"  Symbol: {symbol}")
            print(f"  Direction: {dir_str}")
            print(f"  Entry Price: ${entry_price:.2f}")
            print(f"  Entry Confidence: {confidence:.3f}")
            print(f"  Notional: ${notional_usd:.2f}")
            print(f"  Age: {age_str} ({age_seconds}s / {max_hold_seconds}s)")
            print(f"  TP Threshold: +{tp_pct:.2f}%")
            print(f"  SL Threshold: -{sl_pct:.2f}%")
            print(f"  Max Hold: {max_hold_seconds // 60}m")
            print()
    
    if not has_open:
        print("No open recovery positions.")
        print()
    
    # Show recent trades
    trades = _tail_jsonl(RECOVERY_TRADES_PATH, n=10)
    
    if trades:
        print("Recent Trades (Last 10):")
        print("-" * 70)
        print(f"{'Time':<20} {'Action':<8} {'Symbol':<10} {'Dir':<6} {'PnL%':<8} {'Reason'}")
        print("-" * 70)
        
        for trade in trades:
            ts = trade.get("ts", "")[:19] if trade.get("ts") else "—"
            action = trade.get("action", "—")
            symbol = trade.get("symbol", "—")
            direction = trade.get("direction", 0)
            dir_str = "LONG" if direction == 1 else "SHORT" if direction == -1 else "—"
            pnl_pct = trade.get("pnl_pct")
            pnl_str = f"{pnl_pct:+.3f}%" if pnl_pct is not None else "—"
            reason = trade.get("reason") or trade.get("exit_reason", "—")
            
            print(f"{ts:<20} {action.upper():<8} {symbol:<10} {dir_str:<6} {pnl_str:<8} {reason}")
        
        print("-" * 70)
    else:
        print("No trades logged yet.")
    
    print()
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

