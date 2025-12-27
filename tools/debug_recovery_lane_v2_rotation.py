#!/usr/bin/env python3
"""
Debug Recovery Lane V2 Rotation (Phase 5H.2)
--------------------------------------------

Prints rotation state, cooldowns, and eligible symbols.
"""

from __future__ import annotations

import sys
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from engine_alpha.core.paths import REPORTS
from engine_alpha.loop.recovery_lane_v2_trades import RECOVERY_TRADES_PATH
from engine_alpha.loop.recovery_lane_v2 import _get_last_opens_from_trades

RECOVERY_RAMP_V2_PATH = REPORTS / "risk" / "recovery_ramp_v2.json"
STATE_PATH = REPORTS / "loop" / "recovery_lane_v2_state.json"


def _load_json(path: Path) -> dict:
    """Load JSON file."""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _read_trades_jsonl(path: Path, window_hours: int = 24) -> list:
    """
    Read trades from JSONL filtered by time window.
    
    Phase 5H.4: Filter by last N hours, only recovery_v2 lane, only open actions.
    """
    trades = []
    if not path.exists():
        return trades
    
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    # Phase 5H.4: Filter by lane and action
                    if trade.get("lane") != "recovery_v2":
                        continue
                    if trade.get("action") != "open":
                        continue
                    
                    # Filter by timestamp (last 24h)
                    ts_str = trade.get("ts", "")
                    if ts_str:
                        try:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                            if ts >= cutoff:
                                trades.append(trade)
                        except Exception:
                            continue
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    
    return trades


def main() -> int:
    """Main entry point."""
    print("Recovery Lane V2 Rotation Debug (Phase 5H.2)")
    print("=" * 70)
    print()
    
    # Load state
    state = _load_json(STATE_PATH)
    last_opens = state.get("last_opens", [])
    post_close_cooldowns = state.get("post_close_cooldowns", {})
    cooldowns = state.get("cooldowns", {})
    
    # Load recovery ramp v2
    recovery_ramp_v2 = _load_json(RECOVERY_RAMP_V2_PATH)
    decision = recovery_ramp_v2.get("decision", {})
    allowed_symbols = decision.get("allowed_symbols", [])
    recommended_order = decision.get("recommended_order", allowed_symbols)
    
    # Phase 5H.4: Read last 10 opens from recovery_lane_v2_trades.jsonl (24h window)
    all_trades = _read_trades_jsonl(RECOVERY_TRADES_PATH, window_hours=24)
    last_10_opens = all_trades[-10:] if len(all_trades) >= 10 else all_trades
    
    print("Last 10 Opens (from recovery_lane_v2_trades.jsonl, last 24h):")
    print("-" * 70)
    if last_10_opens:
        for trade in last_10_opens:
            ts = trade.get("ts", "")[:19] if trade.get("ts") else "—"
            symbol = trade.get("symbol", "?")
            conf = trade.get("confidence", 0.0)
            print(f"  {ts}  {symbol:<10}  conf={conf:.3f}")
    else:
        print("  (none)")
    print()
    
    print("Rotation Counters (last_opens from state):")
    print("-" * 70)
    if last_opens:
        for i, open_entry in enumerate(last_opens[-5:], 1):
            ts = open_entry.get("ts", "")[:19] if open_entry.get("ts") else "—"
            symbol = open_entry.get("symbol", "?")
            print(f"  {i}. {ts}  {symbol}")
    else:
        print("  (none)")
    print()
    
    # Phase 5H.2 Rotation Deadlock Fix: Check rotation from trades.jsonl (single source of truth)
    last_opens_from_trades = _get_last_opens_from_trades()
    if len(last_opens_from_trades) >= 2:
        recent_opens = last_opens_from_trades[-2:]
        recent_symbols = [open_entry.get("symbol") for open_entry in recent_opens]
        if len(set(recent_symbols)) == 1:
            last_symbol = recent_symbols[0]
            print(f"⚠ Rotation Advisory: Last 2 opens were {last_symbol}")
            print(f"   Rotation enforced only if an alternative valid candidate exists")
            print(f"   If {last_symbol} is the only valid candidate, it will be allowed (no deadlock)")
        else:
            print("✓ Rotation OK: Last 2 opens are different")
    else:
        print("✓ Rotation OK: Not enough history")
    print()
    
    print("Active Cooldowns:")
    print("-" * 70)
    now = datetime.now(timezone.utc)
    
    # Post-close cooldowns
    if post_close_cooldowns:
        print("  Post-Close Cooldowns (10 min):")
        for symbol, ts_str in post_close_cooldowns.items():
            try:
                cooldown_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(timezone.utc)
                elapsed = (now - cooldown_time).total_seconds()
                remaining = max(0, 600 - elapsed)  # 10 minutes = 600 seconds
                if remaining > 0:
                    print(f"    {symbol}: {remaining/60:.1f} min remaining")
                else:
                    print(f"    {symbol}: expired")
            except Exception:
                print(f"    {symbol}: invalid timestamp")
    else:
        print("  Post-Close Cooldowns: (none)")
    
    # No-signal cooldowns
    if cooldowns:
        print("  No-Signal Cooldowns (5 min):")
        for symbol, ts_str in cooldowns.items():
            try:
                cooldown_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(timezone.utc)
                elapsed = (now - cooldown_time).total_seconds()
                remaining = max(0, 300 - elapsed)  # 5 minutes = 300 seconds
                if remaining > 0:
                    print(f"    {symbol}: {remaining/60:.1f} min remaining")
                else:
                    print(f"    {symbol}: expired")
            except Exception:
                print(f"    {symbol}: invalid timestamp")
    else:
        print("  No-Signal Cooldowns: (none)")
    print()
    
    print("Eligible Symbols (from recovery_ramp_v2.json):")
    print("-" * 70)
    if allowed_symbols:
        print(f"  Allowed Symbols: {', '.join(allowed_symbols)}")
        print(f"  Recommended Order: {', '.join(recommended_order)}")
    else:
        print("  (none)")
    print()
    
    print("=" * 70)
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

