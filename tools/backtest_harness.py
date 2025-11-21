#!/usr/bin/env python3
"""
Backtest Harness - Phase 45
Replays historical candles through run_step_live for behavioral analysis.
Writes results to reports/backtest/* (separate from live reports).
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List

from engine_alpha.core.paths import REPORTS
from engine_alpha.data.live_prices import get_live_ohlcv
# Note: run_step_live is imported later, after env vars may be set


def parse_iso8601(ts_str: str) -> datetime:
    """Parse ISO8601 string to timezone-aware datetime."""
    # Handle various formats
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        # Try parsing as timestamp
        try:
            ts = float(ts_str)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except ValueError:
            raise ValueError(f"Invalid timestamp format: {ts_str}")


def filter_candles_by_range(
    candles: List[Dict[str, Any]],
    start_dt: datetime,
    end_dt: datetime,
) -> List[Dict[str, Any]]:
    """Filter candles by start/end datetime range and sort by timestamp."""
    filtered = []
    for candle in candles:
        ts_str = candle.get("ts")
        if not ts_str:
            continue
        try:
            candle_dt = parse_iso8601(ts_str)
            if start_dt <= candle_dt <= end_dt:
                filtered.append(candle)
        except (ValueError, TypeError):
            continue
    
    # Sort by timestamp ascending
    filtered.sort(key=lambda c: parse_iso8601(c.get("ts", "")))
    return filtered


def main() -> None:
    """Main backtest harness entry point."""
    parser = argparse.ArgumentParser(
        description="Chloe Backtest Harness - Replay historical candles through run_step_live"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="ETHUSDT",
        help="Trading symbol (default: ETHUSDT)",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default="1h",
        help="Timeframe (default: 1h)",
    )
    parser.add_argument(
        "--start",
        type=str,
        required=True,
        help="Start timestamp (ISO8601, e.g., 2025-01-01T00:00:00Z)",
    )
    parser.add_argument(
        "--end",
        type=str,
        required=True,
        help="End timestamp (ISO8601, e.g., 2025-01-07T00:00:00Z)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Number of candles to fetch (default: 200)",
    )
    parser.add_argument(
        "--explore",
        action="store_true",
        help="Enable exploration mode (softer thresholds) for backtest only",
    )
    parser.add_argument(
        "--weights-file",
        type=str,
        help="Path to council_weights.yaml file to use (for learning experiments)",
    )
    
    args = parser.parse_args()
    
    # If weights file specified, set env var for confidence_engine to use it
    if args.weights_file:
        weights_path = Path(args.weights_file)
        if weights_path.exists():
            # Temporarily copy to config location (or use env var if supported)
            # For now, we'll set an env var that confidence_engine can check
            os.environ["COUNCIL_WEIGHTS_FILE"] = str(weights_path.absolute())
        else:
            print(f"⚠️  Warning: weights file not found: {weights_path}")
    
    # Exploration mode: soften thresholds for this backtest only
    # IMPORTANT: Set env vars BEFORE importing run_step_live, so autonomous_trader
    # reads the modified values at module import time
    if args.explore:
        # Lower MIN_CONF_LIVE: allow more trades at lower confidence
        os.environ.setdefault("MIN_CONF_LIVE", "0.40")
        # Lower COUNCIL_NEUTRAL_THRESHOLD: require less certainty before committing to a dir
        os.environ.setdefault("COUNCIL_NEUTRAL_THRESHOLD", "0.15")
        print("Exploration mode: softer thresholds enabled for backtest only.")
        print(f"   [explore] MIN_CONF_LIVE set to {os.environ['MIN_CONF_LIVE']}")
        print(f"   [explore] COUNCIL_NEUTRAL_THRESHOLD set to {os.environ['COUNCIL_NEUTRAL_THRESHOLD']}")
        print()
    
    # Import run_step_live AFTER setting env vars (if explore mode)
    # This ensures autonomous_trader reads the modified env vars at import time
    from engine_alpha.loop.autonomous_trader import run_step_live
    
    # Parse timestamps
    try:
        start_dt = parse_iso8601(args.start)
        end_dt = parse_iso8601(args.end)
    except ValueError as e:
        print(f"❌ Error parsing timestamps: {e}")
        return
    
    # Validate start < end
    if start_dt >= end_dt:
        print(f"❌ Error: start timestamp must be before end timestamp")
        print(f"   Start: {start_dt.isoformat()}")
        print(f"   End:   {end_dt.isoformat()}")
        return
    
    print("Backtest Harness - Phase 45")
    print("=" * 60)
    print(f"Symbol:    {args.symbol}")
    print(f"Timeframe: {args.timeframe}")
    print(f"Start:     {start_dt.isoformat()}")
    print(f"End:       {end_dt.isoformat()}")
    print(f"Limit:     {args.limit}")
    print()
    
    # Fetch OHLCV data
    print("1. Fetching OHLCV data...")
    try:
        candles = get_live_ohlcv(
            symbol=args.symbol,
            timeframe=args.timeframe,
            limit=args.limit,
            no_cache=True,
        )
        if not candles:
            print("   ❌ No candles returned from get_live_ohlcv")
            return
        print(f"   ✅ Fetched {len(candles)} candles")
    except Exception as e:
        print(f"   ❌ Error fetching OHLCV: {e}")
        return
    
    # Filter by date range
    print("2. Filtering candles by date range...")
    
    # Show available date range
    if candles:
        available_starts = []
        for c in candles:
            ts_str = c.get("ts")
            if ts_str:
                try:
                    available_starts.append(parse_iso8601(ts_str))
                except (ValueError, TypeError):
                    continue
        if available_starts:
            available_start = min(available_starts)
            available_end = max(available_starts)
            print(f"   Available data: {available_start.isoformat()} to {available_end.isoformat()}")
    
    filtered_candles = filter_candles_by_range(candles, start_dt, end_dt)
    if not filtered_candles:
        print(f"   ❌ No candles found in requested range {start_dt.isoformat()} to {end_dt.isoformat()}")
        if candles:
            print(f"   💡 Tip: Use a date range within the available data shown above")
        return
    print(f"   ✅ {len(filtered_candles)} candles in range")
    
    # Create backtest run directory
    run_id = uuid.uuid4().hex[:8]
    backtest_dir = REPORTS / "backtest" / f"{args.symbol}_{args.timeframe}_{run_id}"
    backtest_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n3. Created backtest directory: {backtest_dir}")
    
    # Write meta.json
    meta = {
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "limit": args.limit,
        "run_id": run_id,
    }
    meta_path = backtest_dir / "meta.json"
    with meta_path.open("w") as f:
        json.dump(meta, f, indent=2, sort_keys=True)
    print(f"   ✅ Wrote meta.json")
    
    # Initialize equity tracking
    initial_equity = 10000.0
    equity_curve: List[Dict[str, Any]] = [
        {
            "ts": filtered_candles[0].get("ts", start_dt.isoformat()),
            "equity": initial_equity,
        }
    ]
    current_equity = initial_equity
    
    # Run backtest
    print(f"\n4. Running backtest over {len(filtered_candles)} candles...")
    bar_count = 0
    
    for i, candle in enumerate(filtered_candles):
        bar_ts = candle.get("ts")
        if not bar_ts:
            continue
        
        try:
            # Call run_step_live with the historical bar timestamp
            result = run_step_live(
                symbol=args.symbol,
                timeframe=args.timeframe,
                limit=args.limit,
                bar_ts=bar_ts,
            )
            
            # Extract equity from result if available
            if isinstance(result, dict):
                equity_from_result = result.get("equity_live")
                if equity_from_result is not None:
                    try:
                        current_equity = float(equity_from_result)
                    except (ValueError, TypeError):
                        # Keep current_equity unchanged if parsing fails
                        pass
            
            # Record equity point
            equity_curve.append({
                "ts": bar_ts,
                "equity": current_equity,
            })
            
            bar_count += 1
            
            # Progress indicator
            if (i + 1) % max(1, len(filtered_candles) // 10) == 0:
                progress = ((i + 1) / len(filtered_candles)) * 100
                print(f"   Progress: {progress:.0f}% ({i + 1}/{len(filtered_candles)})")
        
        except Exception as e:
            print(f"   ⚠️  Error processing candle {i + 1} (ts={bar_ts}): {e}")
            # Continue with next candle
            continue
    
    print(f"   ✅ Processed {bar_count} candles")
    
    # Write equity curve
    equity_curve_path = backtest_dir / "equity_curve.jsonl"
    with equity_curve_path.open("w") as f:
        for point in equity_curve:
            f.write(json.dumps(point) + "\n")
    print(f"\n5. Wrote equity curve: {equity_curve_path}")
    print(f"   Points: {len(equity_curve)}")
    
    # Compute summary metrics
    end_equity = equity_curve[-1]["equity"] if equity_curve else initial_equity
    
    summary = {
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "limit": args.limit,
        "bars_processed": bar_count,
        "start_equity": initial_equity,
        "end_equity": end_equity,
        "equity_change": end_equity - initial_equity,
        "equity_change_pct": ((end_equity - initial_equity) / initial_equity) * 100.0 if initial_equity > 0 else 0.0,
    }
    
    # Write summary
    summary_path = backtest_dir / "summary.json"
    with summary_path.open("w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    print(f"\n6. Wrote summary: {summary_path}")
    print(f"   Bars processed: {bar_count}")
    print(f"   Start equity:   ${initial_equity:,.2f}")
    print(f"   End equity:     ${end_equity:,.2f}")
    print(f"   Change:         ${summary['equity_change']:,.2f} ({summary['equity_change_pct']:+.2f}%)")
    
    print(f"\n✅ Backtest complete!")
    print(f"   Results: {backtest_dir}")


if __name__ == "__main__":
    main()

