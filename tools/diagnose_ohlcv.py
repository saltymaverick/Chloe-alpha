#!/usr/bin/env python3
"""
OHLCV Diagnostic Tool - Verify 15m data loading and pipeline.

Checks:
- Timeframe used
- Number of bars
- Timestamp spacing
- Data freshness
"""

import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from engine_alpha.data.live_prices import get_live_ohlcv
from engine_alpha.loop.autonomous_trader import DEFAULT_TIMEFRAME
from engine_alpha.signals.signal_processor import get_signal_vector_live
from engine_alpha.core.paths import CONFIG
import json


def get_config_timeframe() -> str:
    """Get timeframe from config."""
    try:
        config_path = CONFIG / "engine_config.json"
        if config_path.exists():
            with config_path.open() as f:
                cfg = json.load(f)
                return cfg.get("timeframe", DEFAULT_TIMEFRAME)
    except Exception:
        pass
    return DEFAULT_TIMEFRAME


def analyze_timestamps(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze timestamp spacing in OHLCV data."""
    if len(rows) < 2:
        return {"error": "Need at least 2 rows to analyze spacing"}
    
    timestamps = []
    for row in rows:
        ts_str = row.get("ts", "")
        try:
            if "T" in ts_str:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(ts_str)
            timestamps.append(dt)
        except Exception as e:
            return {"error": f"Failed to parse timestamp: {ts_str}, error: {e}"}
    
    if len(timestamps) < 2:
        return {"error": "Could not parse enough timestamps"}
    
    # Calculate intervals
    intervals = []
    for i in range(1, len(timestamps)):
        delta = timestamps[i] - timestamps[i-1]
        intervals.append(delta.total_seconds() / 60)  # Convert to minutes
    
    avg_interval = sum(intervals) / len(intervals) if intervals else 0
    min_interval = min(intervals) if intervals else 0
    max_interval = max(intervals) if intervals else 0
    
    return {
        "count": len(timestamps),
        "first_ts": timestamps[0].isoformat(),
        "last_ts": timestamps[-1].isoformat(),
        "avg_interval_minutes": round(avg_interval, 2),
        "min_interval_minutes": round(min_interval, 2),
        "max_interval_minutes": round(max_interval, 2),
        "intervals": [round(i, 2) for i in intervals[-10:]],  # Last 10 intervals
    }


def main():
    """Run OHLCV diagnostic for all symbols or a specific one."""
    import argparse
    parser = argparse.ArgumentParser(description="Diagnose OHLCV feeds for symbols")
    parser.add_argument("--symbol", type=str, default=None, help="Specific symbol to check (default: all enabled)")
    parser.add_argument("--timeframe", type=str, default=None, help="Timeframe (default: from config)")
    parser.add_argument("--all", action="store_true", help="Check all enabled symbols")
    args = parser.parse_args()
    
    config_tf = args.timeframe or get_config_timeframe()
    
    # Get symbols to check
    if args.symbol:
        symbols = [args.symbol.upper()]
    elif args.all:
        from engine_alpha.config.assets import get_enabled_assets
        symbols = [asset.symbol for asset in get_enabled_assets()]
    else:
        symbols = ["ETHUSDT"]  # Default to ETHUSDT
    
    print("=" * 70)
    print("OHLCV DIAGNOSTIC - Multi-Symbol Feed Audit")
    print("=" * 70)
    print()
    print(f"Config timeframe: {config_tf}")
    print(f"Symbols to check: {', '.join(symbols)}")
    print()
    
    from engine_alpha.data.live_prices import get_ohlcv_live_multi
    
    for symbol in symbols:
        print(f"Symbol: {symbol}")
        print("-" * 70)
        
        try:
            rows = get_ohlcv_live_multi(symbol, config_tf, limit=10, no_cache=True)
            
            if rows:
                print(f"✅ Loaded {len(rows)} bars")
                
                print(f"\nLast 5 timestamps:")
                for i, row in enumerate(rows[-5:]):
                    ts = row.get("ts", "N/A")
                    close = row.get("close", "N/A")
                    print(f"  [{i+1}] {ts} | close={close}")
                
                # Check staleness
                last_ts_str = rows[-1].get("ts", "")
                try:
                    if "T" in last_ts_str:
                        last_dt = datetime.fromisoformat(last_ts_str.replace("Z", "+00:00"))
                    else:
                        last_dt = datetime.fromisoformat(last_ts_str)
                    now_dt = datetime.now(timezone.utc)
                    age_minutes = (now_dt - last_dt).total_seconds() / 60
                    
                    print(f"\nFreshness check:")
                    print(f"  Last bar: {last_ts_str}")
                    print(f"  Age: {age_minutes:.1f} minutes")
                    
                    if age_minutes < 30:
                        print(f"  ✅ Data is fresh (< 30 minutes old)")
                    else:
                        print(f"  ❌ Data is stale ({age_minutes:.1f} minutes old)")
                except Exception as e:
                    print(f"  ⚠️  Could not parse timestamp: {e}")
                
                # Analyze spacing
                analysis = analyze_timestamps(rows)
                if "error" not in analysis:
                    expected_interval = 15.0 if config_tf == "15m" else 60.0 if config_tf == "1h" else None
                    if expected_interval:
                        if abs(analysis['avg_interval_minutes'] - expected_interval) < 1.0:
                            print(f"  ✅ Interval matches expected {expected_interval}m")
                        else:
                            print(f"  ⚠️  Interval {analysis['avg_interval_minutes']}m doesn't match expected {expected_interval}m")
            else:
                print(f"❌ No fresh data available")
                print(f"  Check logs/live_feeds.log for details")
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
        
        print()
    
    print("=" * 70)
    print("Diagnostic complete")
    print("=" * 70)
    print(f"\nFor detailed feed logs, see: logs/live_feeds.log")


if __name__ == "__main__":
    main()

