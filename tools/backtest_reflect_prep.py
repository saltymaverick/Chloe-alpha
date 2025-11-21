#!/usr/bin/env python3
"""
Backtest Reflection Prep - Phase 45
Summarizes a backtest run's results into a reflection-style JSON blob for GPT analysis.
This is a read-only utility that does NOT modify any trading logic or state.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from engine_alpha.core.paths import REPORTS


def build_backtest_reflection_input(run_dir: Path) -> Dict[str, Any]:
    """
    Build reflection_data dict from a backtest run directory.
    
    Args:
        run_dir: Path to backtest run directory (e.g., reports/backtest/ETHUSDT_1h_<run_id>)
    
    Returns:
        Reflection data dict with structure similar to tools.reflect_prep output
    """
    # Resolve run_dir relative to REPORTS if not absolute
    if not run_dir.is_absolute():
        # If path starts with "reports/", strip it first
        run_dir_str = str(run_dir)
        if run_dir_str.startswith("reports/"):
            run_dir_str = run_dir_str[8:]  # Remove "reports/" prefix
            run_dir = Path(run_dir_str)
        
        # Try relative to REPORTS/backtest first
        backtest_dir = REPORTS / "backtest" / run_dir
        if backtest_dir.exists():
            run_dir = backtest_dir
        else:
            # Try relative to REPORTS
            run_dir = REPORTS / run_dir
    
    if not run_dir.exists() or not run_dir.is_dir():
        raise ValueError(f"Backtest run directory does not exist: {run_dir}")
    
    # Read summary.json (required)
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        raise ValueError(f"summary.json not found in {run_dir}")
    
    try:
        with summary_path.open("r") as f:
            summary = json.load(f)
    except Exception as e:
        raise ValueError(f"Failed to read summary.json: {e}")
    
    # Read meta.json (optional, but useful for symbol/timeframe)
    meta = {}
    meta_path = run_dir / "meta.json"
    if meta_path.exists():
        try:
            with meta_path.open("r") as f:
                meta = json.load(f)
        except Exception:
            pass  # Use summary.json values as fallback
    
    # Read equity_curve.jsonl (optional)
    equity_curve_path = run_dir / "equity_curve.jsonl"
    equity_points = []
    if equity_curve_path.exists():
        try:
            with equity_curve_path.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        point = json.loads(line)
                        equity_points.append(point)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass  # Fall back to summary.json values
    
    # Extract values from summary.json
    symbol = meta.get("symbol") or summary.get("symbol", "UNKNOWN")
    timeframe = meta.get("timeframe") or summary.get("timeframe", "UNKNOWN")
    start = summary.get("start", "")
    end = summary.get("end", "")
    bars_processed = summary.get("bars_processed", 0)
    start_equity = summary.get("start_equity", 10000.0)
    end_equity = summary.get("end_equity", start_equity)
    
    # If we have equity_curve, use it to confirm/override values
    if equity_points:
        # Use first and last equity values if available
        first_point = equity_points[0]
        last_point = equity_points[-1]
        if "equity" in first_point:
            start_equity = float(first_point.get("equity", start_equity))
        if "equity" in last_point:
            end_equity = float(last_point.get("equity", end_equity))
        # Use number of equity points as count
        count = len(equity_points) - 1  # Subtract 1 for initial point
    else:
        # Fall back to bars_processed
        count = bars_processed
    
    # Compute equity change metrics
    equity_change = end_equity - start_equity
    equity_change_pct = None
    if start_equity != 0:
        equity_change_pct = (equity_change / start_equity) * 100.0
    
    # Read council_perf.jsonl from backtest run if available
    council_perf_path = run_dir / "council_perf.jsonl"
    bucket_perf = {}
    if council_perf_path.exists():
        try:
            bucket_stats = {}
            with council_perf_path.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        buckets = event.get("buckets", [])
                        for bucket in buckets:
                            bucket_name = bucket.get("name", "unknown")
                            if bucket_name not in bucket_stats:
                                bucket_stats[bucket_name] = {"count": 0, "conf_sum": 0.0}
                            bucket_stats[bucket_name]["count"] += 1
                            bucket_stats[bucket_name]["conf_sum"] += abs(float(bucket.get("conf", 0.0)))
                    except json.JSONDecodeError:
                        continue
            
            # Compute average confidences
            for bucket_name, stats in bucket_stats.items():
                if stats["count"] > 0:
                    bucket_perf[bucket_name] = {
                        "avg_conf": stats["conf_sum"] / stats["count"],
                        "event_count": stats["count"],
                    }
        except Exception:
            pass  # Ignore errors reading council_perf
    
    # Check for weights file used (from meta.json or learning experiment)
    weights_file = meta.get("weights_file") or None
    
    # Build reflection_data
    now = datetime.now(timezone.utc).isoformat()
    
    reflection_data = {
        "timestamp": now,
        "recent_trades": {
            "count": count,
            "pf": None,  # PF not computed for backtest (no per-trade pct yet)
            "avg_win": None,
            "avg_loss": None,
            "wins": None,
            "losses": None,
        },
        "council_summary": {
            "total_events": 0,
            "regime_counts": {},
            "bucket_counts": {},
        },
        "bucket_perf": bucket_perf if bucket_perf else None,
        "weights_file": weights_file,
        "loop_health": {
            "mode": "backtest",
            "symbol": symbol,
            "timeframe": timeframe,
            "start": start,
            "end": end,
            "bars_processed": bars_processed,
            "start_equity": start_equity,
            "end_equity": end_equity,
            "equity_change": equity_change,
            "equity_change_pct": equity_change_pct,
        },
    }
    
    return reflection_data


def main() -> None:
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="Backtest Reflection Prep - Build reflection JSON from backtest run"
    )
    parser.add_argument(
        "--run-dir",
        type=str,
        required=True,
        help="Path to backtest run directory (e.g., reports/backtest/ETHUSDT_1h_<run_id>)",
    )
    
    args = parser.parse_args()
    
    try:
        run_dir = Path(args.run_dir)
        reflection_data = build_backtest_reflection_input(run_dir)
        print(json.dumps(reflection_data, indent=2, sort_keys=True))
    except ValueError as e:
        print(f"❌ Error: {e}", file=__import__("sys").stderr)
        exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=__import__("sys").stderr)
        exit(1)


if __name__ == "__main__":
    main()

