#!/usr/bin/env python3
"""
Regime Lab Tool
Runs curated backtests for specific regime windows using the same engine as LIVE/PAPER.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from engine_alpha.core.regime_lab_config import REGIME_LAB_WINDOWS
from engine_alpha.core.paths import REPORTS
from tools.backtest_harness import run_backtest


def count_meaningful_closes(trades_path: Path, threshold: float = 0.0005) -> int:
    """Count meaningful closes using pf_doctor_filtered logic."""
    if not trades_path.exists():
        return 0
    
    meaningful = 0
    with trades_path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                trade = json.loads(line)
                if trade.get("type") != "close":
                    continue
                pct = float(trade.get("pct", 0.0))
                exit_reason = trade.get("exit_reason", "")
                is_scratch = trade.get("is_scratch", False)
                
                # Meaningful: TP/SL, |pct| >= threshold, not scratch
                if (
                    exit_reason in ("tp", "sl")
                    and abs(pct) >= threshold
                    and not is_scratch
                ):
                    meaningful += 1
            except Exception:
                continue
    
    return meaningful


def main():
    parser = argparse.ArgumentParser(description="Run a curated regime lab backtest")
    parser.add_argument(
        "--window-id",
        required=True,
        choices=list(REGIME_LAB_WINDOWS.keys()),
        help="Lab window preset ID",
    )
    parser.add_argument(
        "--csv",
        default="data/ohlcv/ETHUSDT_1h_merged.csv",
        help="Path to CSV file (default: data/ohlcv/ETHUSDT_1h_merged.csv)",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=200,
        help="Signal window size (default: 200)",
    )
    
    args = parser.parse_args()
    
    # Look up the window config
    window_config = REGIME_LAB_WINDOWS.get(args.window_id)
    if not window_config:
        print(f"❌ Error: Unknown window-id: {args.window_id}")
        print(f"   Available: {list(REGIME_LAB_WINDOWS.keys())}")
        return 1
    
    print("=" * 80)
    print("REGIME LAB")
    print("=" * 80)
    print(f"\n📋 Window: {args.window_id}")
    print(f"   Notes: {window_config.get('notes', 'N/A')}")
    print(f"   Symbol: {window_config['symbol']}")
    print(f"   Timeframe: {window_config['timeframe']}")
    print(f"   Period: {window_config['start']} to {window_config['end']}")
    print(f"   CSV: {args.csv}")
    print(f"   Window: {args.window}")
    
    # Ensure we're using PAPER mode (same as LIVE/PAPER logic)
    os.environ.setdefault("MODE", "PAPER")
    # Explicitly disable analysis mode - we want the real engine
    os.environ.pop("ANALYSIS_MODE", None)
    
    print(f"\n🔧 Mode: {os.getenv('MODE', 'PAPER')}")
    print(f"   ANALYSIS_MODE: {os.getenv('ANALYSIS_MODE', 'not set')}")
    print("\n🚀 Running backtest...")
    
    # Run the backtest using the existing harness
    try:
        run_dir = run_backtest(
            symbol=window_config["symbol"],
            timeframe=window_config["timeframe"],
            start=window_config["start"],
            end=window_config["end"],
            csv_path=args.csv,
            window=args.window,
        )
        
        print(f"\n✅ Backtest complete!")
        print(f"   Results: {run_dir}")
        
        # Load summary for sanity checks
        summary_path = run_dir / "summary.json"
        if summary_path.exists():
            try:
                with open(summary_path, "r") as f:
                    summary = json.load(f)
                closes = summary.get("closes", 0)
                
                # Count meaningful closes
                trades_path = run_dir / "trades.jsonl"
                meaningful_closes = count_meaningful_closes(trades_path, threshold=0.0005)
                
                print(f"\n📊 Quick Summary:")
                print(f"   Total closes: {closes}")
                print(f"   Meaningful closes (TP/SL, |pct| >= 0.0005): {meaningful_closes}")
                
                # Sanity checks
                if closes == 0:
                    print(
                        "\n⚠️  WARNING: No closes in this window."
                    )
                    print(
                        "   This lab is not informative for strategy tuning."
                    )
                    print(
                        "   Likely reasons: strict thresholds + no strong signals in that period."
                    )
                elif meaningful_closes == 0:
                    print(
                        "\n⚠️  WARNING: Only scratch trades in this window (no meaningful PF)."
                    )
                    print(
                        "   Don't tune based on this lab."
                    )
                else:
                    print(f"\n✅ Lab produced {meaningful_closes} meaningful closes - ready for analysis")
                
            except Exception as e:
                print(f"⚠️  Could not load summary: {e}")
        
        print(f"\n📝 Suggested follow-up commands:")
        print(f"   python3 -m tools.backtest_report --run-dir {run_dir}")
        print(
            f"   python3 -m tools.pf_doctor_filtered --run-dir {run_dir} --threshold 0.0005 --reasons tp,sl"
        )
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Error running backtest: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())

