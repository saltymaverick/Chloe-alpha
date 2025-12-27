#!/usr/bin/env python3
"""
Paper Trading Loop - Continuous loop that calls run_step_live() on new 15m bars.

This script:
1. Detects when a new 15m bar arrives
2. Calls run_step_live() for each enabled asset (via multi_asset_runner)
3. Waits until the next bar
4. Repeats

Usage:
    python tools/run_paper_loop.py [--timeframe TIMEFRAME]
"""

import sys
import os
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Ensure NOT in dry-run mode
os.environ.pop("MODE", None)
os.environ.pop("CHLOE_DRY_RUN", None)

from engine_alpha.loop.multi_asset_runner import run_all_live_symbols
from engine_alpha.loop.autonomous_trader import DEFAULT_TIMEFRAME
from engine_alpha.data.live_prices import get_live_ohlcv
from engine_alpha.core.paths import CONFIG
from engine_alpha.config.assets import get_enabled_assets
import json
import logging

# Configure logging to output to stdout (which systemd captures)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


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


def get_timeframe_minutes(timeframe: str) -> int:
    """Convert timeframe string to minutes."""
    if timeframe.endswith("m"):
        return int(timeframe[:-1])
    elif timeframe.endswith("h"):
        return int(timeframe[:-1]) * 60
    elif timeframe.endswith("d"):
        return int(timeframe[:-1]) * 1440
    return 15  # Default to 15m


def get_latest_bar_timestamp(timeframe: str) -> str:
    """Get the timestamp of the latest bar for any enabled asset."""
    # Use the first enabled asset to detect new bars
    assets = get_enabled_assets()
    if not assets:
        return ""
    
    # Use the first asset's symbol to detect bar timestamps
    symbol = assets[0].symbol
    rows = get_live_ohlcv(symbol, timeframe, limit=1)
    if rows:
        return rows[-1].get("ts", "")
    return ""


def wait_for_next_bar(timeframe: str, last_bar_ts: str) -> None:
    """Wait until the next bar arrives."""
    tf_minutes = get_timeframe_minutes(timeframe)
    
    # Parse last bar timestamp
    try:
        if "T" in last_bar_ts:
            last_dt = datetime.fromisoformat(last_bar_ts.replace("Z", "+00:00"))
        else:
            last_dt = datetime.fromisoformat(last_bar_ts)
    except Exception:
        # If we can't parse, wait the full timeframe
        print(f"⚠️  Could not parse timestamp {last_bar_ts}, waiting {tf_minutes} minutes")
        time.sleep(tf_minutes * 60)
        return
    
    # Calculate next bar time
    next_bar_dt = last_dt + timedelta(minutes=tf_minutes)
    now_dt = datetime.now(timezone.utc)
    
    # If next bar is in the future, wait
    if next_bar_dt > now_dt:
        wait_seconds = (next_bar_dt - now_dt).total_seconds()
        print(f"⏳ Waiting {wait_seconds/60:.1f} minutes for next {timeframe} bar...")
        time.sleep(wait_seconds)
    else:
        # Next bar should be available, but wait a bit for data to settle
        print(f"⏳ Waiting 30 seconds for bar data to settle...")
        time.sleep(30)


def main():
    """Run continuous paper trading loop for all enabled assets."""
    parser = argparse.ArgumentParser(description="Run Chloe in continuous paper mode (multi-asset)")
    parser.add_argument("--timeframe", type=str, default=None, help="Timeframe (default: from config)")
    parser.add_argument("--check-interval", type=int, default=60, help="Check for new bars every N seconds")
    args = parser.parse_args()
    
    timeframe = args.timeframe or get_config_timeframe()
    
    # Get enabled assets
    assets = get_enabled_assets()
    trading_symbols = [asset.symbol for asset in assets]
    
    print("=" * 70)
    print("CHLOE MULTI-ASSET PAPER TRADING LOOP")
    print("=" * 70)
    print(f"Enabled assets: {', '.join(trading_symbols) if trading_symbols else 'None'}")
    print(f"Timeframe: {timeframe}")
    print(f"Mode: PAPER (trades will be logged)")
    print()
    print("⚠️  This will run continuously. Press Ctrl+C to stop.")
    print("=" * 70)
    print()
    
    last_processed_bar_ts = None
    iteration = 0
    
    try:
        while True:
            iteration += 1
            
            # Get latest bar timestamp (using first enabled asset)
            latest_bar_ts = get_latest_bar_timestamp(timeframe)
            
            if not latest_bar_ts:
                print(f"[Iteration {iteration}] ⚠️  No bars available, waiting...")
                time.sleep(args.check_interval)
                continue
            
            # Check if this is a new bar
            if latest_bar_ts != last_processed_bar_ts:
                print(f"[Iteration {iteration}] 🆕 New bar detected: {latest_bar_ts}")
                print(f"  Processing all enabled assets...", flush=True)
                
                try:
                    # Run multi-asset runner (processes all enabled assets)
                    run_all_live_symbols()
                    
                    print(f"  ✅ Processed bar for all enabled assets", flush=True)
                    
                    last_processed_bar_ts = latest_bar_ts
                    
                except Exception as e:
                    print(f"  ❌ Error processing bar: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                # Same bar, wait a bit
                if iteration % 10 == 0:  # Print status every 10 iterations
                    print(f"[Iteration {iteration}] ⏸  Same bar ({latest_bar_ts}), waiting...")
            
            # Wait before checking again
            time.sleep(args.check_interval)
            
    except KeyboardInterrupt:
        print()
        print("=" * 70)
        print("Loop stopped by user")
        print("=" * 70)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

