#!/usr/bin/env python3
"""
Regime Threshold Tuner
Automated tuning of entry confidence thresholds per regime using backtests and filtered PF.

This tool:
- Runs backtests for each regime/threshold combination
- Evaluates using filtered PF (TP/SL, |pct| >= 0.0005, non-scratch)
- Filters by minimum meaningful trade count
- Outputs ranked recommendations to JSON

Safe to run repeatedly - does not modify live config unless explicitly applied.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine_alpha.core.paths import REPORTS


def _filter_meaningful_trades(
    trades_path: Path,
    threshold: float = 0.0005,
) -> Dict[str, Any]:
    """
    Compute filtered PF metrics from trades.jsonl.
    
    Filters:
    - exit_reason in ["tp", "sl"]
    - is_scratch == False (or missing)
    - |pct| >= threshold
    
    Returns:
        {
            "count": int,
            "wins": int,
            "losses": int,
            "pos_sum": float,
            "neg_sum": float,
            "pf": float,
        }
    """
    if not trades_path.exists():
        return {
            "count": 0,
            "wins": 0,
            "losses": 0,
            "pos_sum": 0.0,
            "neg_sum": 0.0,
            "pf": 0.0,
        }
    
    meaningful_closes = []
    with trades_path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                trade = json.loads(line)
                if trade.get("type") != "close":
                    continue
                
                # Filter: TP/SL only
                exit_reason = trade.get("exit_reason", "")
                if exit_reason not in ("tp", "sl"):
                    continue
                
                # Filter: not scratch
                if trade.get("is_scratch", False):
                    continue
                
                # Filter: |pct| >= threshold
                try:
                    pct = float(trade.get("pct", 0.0))
                except (ValueError, TypeError):
                    continue
                
                if abs(pct) < threshold:
                    continue
                
                meaningful_closes.append(pct)
            except Exception:
                continue
    
    # Compute metrics
    wins = [p for p in meaningful_closes if p > 0]
    losses = [p for p in meaningful_closes if p < 0]
    pos_sum = sum(wins)
    neg_sum = abs(sum(losses))
    
    if neg_sum > 0:
        pf = pos_sum / neg_sum
    elif pos_sum > 0:
        pf = float("inf")
    else:
        pf = 0.0
    
    return {
        "count": len(meaningful_closes),
        "wins": len(wins),
        "losses": len(losses),
        "pos_sum": pos_sum,
        "neg_sum": neg_sum,
        "pf": pf,
    }


def _find_latest_backtest_run(symbol: str, timeframe: str) -> Optional[Path]:
    """Find the most recent backtest run directory."""
    backtest_dir = REPORTS / "backtest"
    if not backtest_dir.exists():
        return None
    
    # Pattern: ETHUSDT_1h_<timestamp>
    prefix = f"{symbol}_{timeframe}_"
    candidates = [
        d for d in backtest_dir.iterdir()
        if d.is_dir() and d.name.startswith(prefix)
    ]
    
    if not candidates:
        return None
    
    # Sort by modification time, newest first
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _run_backtest(
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    csv_path: str,
    regime: str,
    entry_conf: float,
    window: int = 200,
) -> Optional[Path]:
    """
    Run a single backtest with the given regime entry threshold override.
    
    Returns:
        Path to the backtest run directory, or None if failed
    """
    # Set up environment for this run
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parent.parent)
    env["MODE"] = "PAPER"
    
    # Set the regime-specific override
    env_map = {
        "trend_down": "TUNE_ENTRY_TREND_DOWN",
        "trend_up": "TUNE_ENTRY_TREND_UP",
        "chop": "TUNE_ENTRY_CHOP",
        "high_vol": "TUNE_ENTRY_HIGH_VOL",
    }
    env_var = env_map.get(regime)
    if env_var:
        env[env_var] = str(entry_conf)
    
    # Clear other regime overrides to avoid interference
    for other_regime, other_var in env_map.items():
        if other_regime != regime:
            env.pop(other_var, None)
    
    # Build command
    cmd = [
        sys.executable,
        "-m",
        "tools.backtest_harness",
        "--symbol",
        symbol,
        "--timeframe",
        timeframe,
        "--start",
        start,
        "--end",
        end,
        "--window",
        str(window),
        "--csv",
        csv_path,
    ]
    
    # Run backtest
    try:
        result = subprocess.run(
            cmd,
            env=env,
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout
        )
        
        if result.returncode != 0:
            print(f"⚠️  Backtest failed for {regime} entry_conf={entry_conf}: {result.stderr[:200]}", file=sys.stderr)
            return None
        
        # Find the latest run directory
        run_dir = _find_latest_backtest_run(symbol, timeframe)
        return run_dir
        
    except subprocess.TimeoutExpired:
        print(f"⚠️  Backtest timed out for {regime} entry_conf={entry_conf}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"⚠️  Error running backtest for {regime} entry_conf={entry_conf}: {e}", file=sys.stderr)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Automated regime threshold tuner using backtests and filtered PF"
    )
    parser.add_argument(
        "--symbol",
        default="ETHUSDT",
        help="Symbol (default: ETHUSDT)",
    )
    parser.add_argument(
        "--timeframe",
        default="1h",
        help="Timeframe (default: 1h)",
    )
    parser.add_argument(
        "--start",
        required=True,
        help="Start timestamp (ISO8601, e.g., 2021-01-01T00:00:00Z)",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="End timestamp (ISO8601, e.g., 2021-06-01T00:00:00Z)",
    )
    parser.add_argument(
        "--csv",
        default="data/ohlcv/ETHUSDT_1h_merged.csv",
        help="Path to CSV file (default: data/ohlcv/ETHUSDT_1h_merged.csv)",
    )
    parser.add_argument(
        "--regimes",
        nargs="+",
        required=True,
        choices=["trend_down", "trend_up", "chop", "high_vol"],
        help="Regimes to tune (one or more)",
    )
    parser.add_argument(
        "--min-trades",
        type=int,
        default=15,
        help="Minimum meaningful closes required (default: 15)",
    )
    parser.add_argument(
        "--threshold-grid",
        nargs="+",
        type=float,
        required=True,
        help="Candidate entry thresholds to test (e.g., 0.40 0.45 0.50 0.55 0.60)",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=200,
        help="Signal window size (default: 200)",
    )
    parser.add_argument(
        "--filter-threshold",
        type=float,
        default=0.0005,
        help="Minimum |pct| for meaningful trades (default: 0.0005)",
    )
    
    args = parser.parse_args()
    
    # Validate threshold grid
    for thresh in args.threshold_grid:
        if not (0.0 <= thresh <= 1.0):
            print(f"❌ Error: Threshold {thresh} must be in [0.0, 1.0]", file=sys.stderr)
            return 1
    
    print("=" * 80)
    print("Regime Threshold Tuner")
    print("=" * 80)
    print(f"\n📋 Configuration:")
    print(f"   Symbol:      {args.symbol}")
    print(f"   Timeframe:   {args.timeframe}")
    print(f"   Period:      {args.start} → {args.end}")
    print(f"   CSV:         {args.csv}")
    print(f"   Regimes:     {', '.join(args.regimes)}")
    print(f"   Thresholds: {', '.join(f'{t:.2f}' for t in args.threshold_grid)}")
    print(f"   Min trades:  {args.min_trades}")
    print(f"   Window:      {args.window}")
    print()
    
    # Results storage
    all_results: List[Dict[str, Any]] = []
    
    # Grid search: for each regime, test each threshold
    total_runs = len(args.regimes) * len(args.threshold_grid)
    run_count = 0
    
    for regime in args.regimes:
        print(f"\n🔍 Tuning {regime}...")
        for entry_conf in args.threshold_grid:
            run_count += 1
            print(f"   [{run_count}/{total_runs}] Testing entry_conf={entry_conf:.2f}...", end=" ", flush=True)
            
            # Run backtest
            run_dir = _run_backtest(
                symbol=args.symbol,
                timeframe=args.timeframe,
                start=args.start,
                end=args.end,
                csv_path=args.csv,
                regime=regime,
                entry_conf=entry_conf,
                window=args.window,
            )
            
            if run_dir is None:
                print("❌ FAILED")
                continue
            
            # Load summary
            summary_path = run_dir / "summary.json"
            summary = {}
            if summary_path.exists():
                try:
                    with open(summary_path, "r") as f:
                        summary = json.load(f)
                except Exception:
                    pass
            
            # Compute filtered PF
            trades_path = run_dir / "trades.jsonl"
            filtered_metrics = _filter_meaningful_trades(trades_path, threshold=args.filter_threshold)
            
            # Store result
            result = {
                "regime": regime,
                "entry_conf": entry_conf,
                "closes": summary.get("closes", 0),
                "meaningful_count": filtered_metrics["count"],
                "pf": filtered_metrics["pf"],
                "pos_sum": filtered_metrics["pos_sum"],
                "neg_sum": filtered_metrics["neg_sum"],
                "wins": filtered_metrics["wins"],
                "losses": filtered_metrics["losses"],
                "run_dir": str(run_dir),
            }
            all_results.append(result)
            
            # Print quick status
            if filtered_metrics["count"] >= args.min_trades:
                pf_str = f"{filtered_metrics['pf']:.2f}" if not math.isinf(filtered_metrics["pf"]) else "inf"
                print(f"✅ PF={pf_str} ({filtered_metrics['count']} trades)")
            else:
                print(f"⚠️  Only {filtered_metrics['count']} trades (< {args.min_trades})")
    
    # Process results: filter, rank, and select best per regime
    print("\n" + "=" * 80)
    print("Tuning Results")
    print("=" * 80)
    
    recommendations: Dict[str, Any] = {
        "meta": {
            "symbol": args.symbol,
            "timeframe": args.timeframe,
            "start": args.start,
            "end": args.end,
            "min_trades": args.min_trades,
            "threshold_grid": args.threshold_grid,
            "filter_threshold": args.filter_threshold,
        },
        "regimes": {},
    }
    
    # Group by regime
    regime_results: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for result in all_results:
        regime_results[result["regime"]].append(result)
    
    # Process each regime
    for regime in args.regimes:
        results = regime_results.get(regime, [])
        
        # Filter by min_trades
        valid_results = [
            r for r in results
            if r["meaningful_count"] >= args.min_trades
        ]
        
        if not valid_results:
            print(f"\n[WARN] regime {regime}: no candidate met min_trades={args.min_trades}; not tuning this regime.")
            continue
        
        # Rank by PF (descending), then by count (descending)
        valid_results.sort(
            key=lambda r: (
                -r["pf"] if not math.isinf(r["pf"]) else -999999,
                -r["meaningful_count"],
            )
        )
        
        best = valid_results[0]
        
        # Print table
        print(f"\n[{regime}]")
        print(f"  {'entry_conf':<12} {'closes':<8} {'meaningful':<10} {'PF':<8} {'pos_sum':<10} {'neg_sum':<10}")
        print("  " + "-" * 60)
        
        for r in valid_results:
            marker = " <-- BEST" if r == best else ""
            pf_str = f"{r['pf']:.2f}" if not math.isinf(r["pf"]) else "inf"
            print(
                f"  {r['entry_conf']:<12.2f} {r['closes']:<8} {r['meaningful_count']:<10} "
                f"{pf_str:<8} {r['pos_sum']:+.3f} {r['neg_sum']:+.3f}{marker}"
            )
        
        # Store recommendation
        recommendations["regimes"][regime] = {
            "best_entry_conf": best["entry_conf"],
            "pf": best["pf"] if not math.isinf(best["pf"]) else None,
            "meaningful_count": best["meaningful_count"],
            "wins": best["wins"],
            "losses": best["losses"],
            "pos_sum": best["pos_sum"],
            "neg_sum": best["neg_sum"],
            "run_dir": best["run_dir"],
        }
    
    # Write recommendations
    tuning_dir = REPORTS / "tuning"
    tuning_dir.mkdir(parents=True, exist_ok=True)
    recommendations_path = tuning_dir / "regime_thresholds.json"
    
    with open(recommendations_path, "w") as f:
        json.dump(recommendations, f, indent=2)
    
    print("\n" + "=" * 80)
    print(f"✅ Recommended thresholds written to {recommendations_path}")
    print("   To apply, update your regime configs or _compute_entry_min_conf defaults manually.")
    print("=" * 80)
    
    return 0


if __name__ == "__main__":
    exit(main())


