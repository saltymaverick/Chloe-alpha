#!/usr/bin/env python3
"""
Dry-Run Mode CLI - Run Chloe's full decision pipeline without affecting real logs/PF.

Usage:
    python tools/run_dry_run.py [--steps N] [--symbol SYMBOL] [--timeframe TIMEFRAME]

Example:
    python tools/run_dry_run.py --steps 20
    MODE=DRY_RUN python tools/run_dry_run.py --steps 50
"""

import sys
import os
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set dry-run mode before importing autonomous_trader
os.environ["MODE"] = "DRY_RUN"

from engine_alpha.loop.autonomous_trader import run_step, run_step_live, DEFAULT_TIMEFRAME
from engine_alpha.loop.position_manager import clear_position, clear_live_position
from engine_alpha.core.paths import REPORTS


def main():
    """Run dry-run mode for N steps."""
    parser = argparse.ArgumentParser(description="Run Chloe in dry-run mode")
    parser.add_argument("--steps", type=int, default=20, help="Number of steps to run")
    parser.add_argument("--symbol", type=str, default="ETHUSDT", help="Trading symbol")
    parser.add_argument("--timeframe", type=str, default=None, help=f"Timeframe (default: from config, currently {DEFAULT_TIMEFRAME})")
    parser.add_argument("--live", action="store_true", help="Use live data (run_step_live)")
    args = parser.parse_args()
    
    # Ensure dry-run mode is set
    if os.getenv("MODE", "").upper() != "DRY_RUN":
        os.environ["MODE"] = "DRY_RUN"
    
    print("=" * 70)
    print("CHLOE DRY-RUN MODE")
    print("=" * 70)
    print(f"Steps: {args.steps}")
    print(f"Symbol: {args.symbol}")
    effective_timeframe = args.timeframe or DEFAULT_TIMEFRAME
    print(f"Timeframe: {effective_timeframe}")
    print(f"Mode: {'LIVE' if args.live else 'PAPER'}")
    print()
    print("⚠️  DRY-RUN MODE: No trades will be written to trades.jsonl")
    print("⚠️  DRY-RUN MODE: No PF reports will be updated")
    print("⚠️  DRY-RUN MODE: Decisions logged to reports/dry_run_*.jsonl")
    print()
    print("=" * 70)
    print()
    
    # Clear any existing positions (start fresh)
    clear_position()
    clear_live_position()
    
    # Run steps
    for tick in range(args.steps):
        try:
            if args.live:
                run_step_live(
                    symbol=args.symbol,
                    timeframe=args.timeframe,  # Will use DEFAULT_TIMEFRAME if None
                    limit=200,
                )
            else:
                run_step(tick=tick)
        except KeyboardInterrupt:
            print("\n\n⚠️  Interrupted by user")
            break
        except Exception as e:
            print(f"\n❌ Error on step {tick}: {e}")
            import traceback
            traceback.print_exc()
            break
    
    print()
    print("=" * 70)
    print("DRY-RUN COMPLETE")
    print("=" * 70)
    print(f"Decisions logged to: {REPORTS / 'dry_run_decisions.jsonl'}")
    print(f"Trades logged to: {REPORTS / 'dry_run_trades.jsonl'}")
    print()
    print("Review the logs to verify decision quality before enabling real trading.")


if __name__ == "__main__":
    main()

