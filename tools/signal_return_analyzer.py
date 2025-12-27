#!/usr/bin/env python3
"""
Signal Return Analyzer - Offline analysis tool

Runs Chloe's real signal + regime logic over historical OHLCV from CSV and produces
a summary of performance by regime × confidence bin.

This simulates "if I went long/short with this conf at this bar and closed 1 bar later,
what happened?" and aggregates that data.

Example usage:
    python3 -m tools.signal_return_analyzer \
      --symbol ETHUSDT \
      --timeframe 1h \
      --csv data/ohlcv/ETHUSDT_1h_merged.csv \
      --window 200 \
      --step-horizon 1 \
      --output reports/analysis/conf_ret_summary.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.data.historical_prices import load_ohlcv_csv
from engine_alpha.data import live_prices
from engine_alpha.signals import signal_processor
from engine_alpha.core.regime import classify_regime
from engine_alpha.core.confidence_engine import decide
from engine_alpha.core.paths import REPORTS


def get_conf_bin(conf: float) -> tuple[float, float]:
    """
    Map confidence to bin boundaries.
    Returns (conf_min, conf_max) tuple.
    """
    # Bins: [0.30, 0.35), [0.35, 0.40), ..., [0.95, 1.01)
    if conf < 0.30:
        return (0.30, 0.35)  # Put very low conf into first bin
    if conf >= 0.95:
        return (0.95, 1.01)  # Put very high conf into last bin
    
    # Round down to nearest 0.05
    bin_min = (int(conf * 20) / 20.0)
    bin_max = bin_min + 0.05
    return (bin_min, bin_max)


def compute_median(values: List[float]) -> Optional[float]:
    """Compute median of a list of floats."""
    if not values:
        return None
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n % 2 == 0:
        return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0
    return sorted_vals[n // 2]


def compute_percentile(values: List[float], p: float) -> Optional[float]:
    """Compute percentile p (0.0-1.0) of a list of floats."""
    if not values:
        return None
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    idx = int(p * (n - 1))
    return sorted_vals[idx]


def compute_std(values: List[float], mean: float) -> float:
    """Compute standard deviation given mean."""
    if not values or len(values) < 2:
        return 0.0
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return variance ** 0.5


def main():
    parser = argparse.ArgumentParser(description="Analyze signal returns by regime × confidence bin")
    parser.add_argument("--symbol", default="ETHUSDT", help="Trading symbol")
    parser.add_argument("--timeframe", default="1h", help="Timeframe")
    parser.add_argument("--csv", default="data/ohlcv/ETHUSDT_1h_merged.csv", help="Path to CSV file")
    parser.add_argument("--window", type=int, default=200, help="Window size for signals")
    parser.add_argument("--step-horizon", type=int, default=1, help="[Legacy] Bars forward for return calculation (ignored if --horizons provided)")
    parser.add_argument("--horizons", type=str, default=None, help="Comma-separated list of horizons (e.g., '1,2,4'). Default: use --step-horizon")
    parser.add_argument("--output", default="reports/analysis/conf_ret_summary.json", help="Output JSON path")
    
    args = parser.parse_args()
    
    # Parse horizons
    if args.horizons:
        horizons = [int(h.strip()) for h in args.horizons.split(",") if h.strip()]
        if not horizons or any(h < 1 for h in horizons):
            print("❌ Error: --horizons must be comma-separated positive integers")
            return 1
        horizons = sorted(set(horizons))  # Remove duplicates and sort
    else:
        # Backward compatibility: use --step-horizon
        horizons = [args.step_horizon]
    
    # Set up environment (PAPER mode for consistency)
    os.environ.setdefault("MODE", "PAPER")
    
    print("=" * 80)
    print("Signal Return Analyzer")
    print("=" * 80)
    print(f"\n📋 Configuration:")
    print(f"   Symbol:        {args.symbol}")
    print(f"   Timeframe:     {args.timeframe}")
    print(f"   CSV:           {args.csv}")
    print(f"   Window:        {args.window}")
    print(f"   Horizons:      {horizons}")
    print(f"   Output:        {args.output}")
    
    # Load CSV
    print(f"\n📂 Loading candles from CSV...")
    candles = load_ohlcv_csv(args.symbol, args.timeframe, csv_path=args.csv)
    print(f"   ✅ Loaded {len(candles)} candles")
    
    max_horizon = max(horizons)
    if len(candles) < args.window + max_horizon:
        print(f"❌ Error: Not enough candles ({len(candles)}) for window={args.window} + max_horizon={max_horizon}")
        return 1
    
    # Storage for bins: (regime, horizon, conf_min, conf_max) -> stats
    bin_stats: Dict[tuple[str, int, float, float], Dict[str, Any]] = defaultdict(lambda: {
        "count": 0,
        "wins": 0,
        "losses": 0,
        "pos_sum": 0.0,
        "neg_sum": 0.0,
        "returns": [],  # Store raw returns for statistics
        "long_count": 0,
        "short_count": 0,
    })
    
    # Store original get_live_ohlcv
    original_get_live_ohlcv = live_prices.get_live_ohlcv
    if hasattr(signal_processor, 'get_live_ohlcv'):
        original_signal_get_live_ohlcv = signal_processor.get_live_ohlcv
    else:
        original_signal_get_live_ohlcv = None
    
    # Progress tracking
    total_bars = len(candles) - args.window - max_horizon + 1
    progress_interval = max(1, total_bars // 20)
    
    print(f"\n🔄 Processing {total_bars} bars across {len(horizons)} horizon(s)...")
    
    # Track regime counts for meta
    regime_counts = defaultdict(int)
    
    try:
        # Iterate over bars
        for i in range(args.window - 1, len(candles) - max_horizon):
            if (i - args.window + 1) % progress_interval == 0:
                pct = ((i - args.window + 1) / total_bars) * 100
                print(f"   Progress: {pct:.1f}% ({i - args.window + 1}/{total_bars})")
            
            # Build window ending at current bar
            window_start = i - args.window + 1
            window_candles = candles[window_start:i + 1]
            current_bar = candles[i]
            
            # Mock get_live_ohlcv to return window
            def mock_get_live_ohlcv(symbol: str, timeframe: str, limit: int = 200, no_cache: bool = True):
                return window_candles[-limit:] if len(window_candles) >= limit else window_candles
            
            live_prices.get_live_ohlcv = mock_get_live_ohlcv
            if original_signal_get_live_ohlcv is not None:
                signal_processor.get_live_ohlcv = mock_get_live_ohlcv
            
            try:
                # Get price-based regime (same as run_step_live does)
                regime_window = window_candles[-20:] if len(window_candles) >= 20 else window_candles
                regime_info = classify_regime(regime_window)
                price_based_regime = regime_info.get("regime", "chop")
                
                # Get signal vector
                from engine_alpha.signals.signal_processor import get_signal_vector_live
                out = get_signal_vector_live(symbol=args.symbol, timeframe=args.timeframe, limit=args.window)
                
                # Get decision with regime override
                decision = decide(
                    out["signal_vector"],
                    out["raw_registry"],
                    regime_override=price_based_regime
                )
                
                # Extract final dir and conf from decide()
                final = decision.get("final", {})
                base_final_dir = final.get("dir", 0)
                base_final_conf = final.get("conf", 0.0)
                
                # Apply Phase 54 regime-aware bucket emphasis (same as run_step_live)
                # This matches the actual entry logic
                buckets = decision.get("buckets", {})
                bucket_dirs = {name: buckets.get(name, {}).get("dir", 0) for name in ["momentum", "meanrev", "flow", "positioning", "timing", "sentiment", "onchain_flow"]}
                bucket_confs = {name: buckets.get(name, {}).get("conf", 0.0) for name in ["momentum", "meanrev", "flow", "positioning", "timing", "sentiment", "onchain_flow"]}
                
                # Phase 54 adjustments (PAPER mode only, matching run_step_live)
                bucket_weight_adj = {name: 1.0 for name in bucket_dirs.keys()}
                if os.getenv("MODE", "PAPER").upper() == "PAPER":
                    if price_based_regime in ("trend_down", "trend_up"):
                        bucket_weight_adj["momentum"] = 1.10
                        bucket_weight_adj["flow"] = 1.05
                        bucket_weight_adj["positioning"] = 1.05
                    elif price_based_regime == "chop":
                        bucket_weight_adj["meanrev"] = 1.10
                        bucket_weight_adj["flow"] = 0.90
                
                # Recompute with Phase 54 adjustments (matching run_step_live logic)
                from engine_alpha.core.confidence_engine import REGIME_BUCKET_WEIGHTS, BUCKET_ORDER
                from engine_alpha.loop.autonomous_trader import NEUTRAL_THRESHOLD
                regime_weights = REGIME_BUCKET_WEIGHTS.get(price_based_regime, REGIME_BUCKET_WEIGHTS.get("chop", {}))
                
                weighted_score = 0.0
                weight_sum = 0.0
                
                for bucket_name in BUCKET_ORDER:
                    dir_val = bucket_dirs.get(bucket_name, 0)
                    conf_val = bucket_confs.get(bucket_name, 0.0)
                    base_weight = float(regime_weights.get(bucket_name, 0.0))
                    adjusted_weight = base_weight * bucket_weight_adj.get(bucket_name, 1.0)
                    
                    if dir_val == 0 or adjusted_weight <= 0.0 or conf_val <= 0.0:
                        continue
                    
                    score = dir_val * conf_val
                    weighted_score += adjusted_weight * score
                    weight_sum += adjusted_weight
                
                if weight_sum <= 0.0:
                    final_score = 0.0
                else:
                    final_score = weighted_score / weight_sum
                
                # Apply neutral zone logic (matching run_step_live)
                score_abs = abs(final_score)
                if score_abs < NEUTRAL_THRESHOLD:
                    effective_final_dir = 0
                    effective_final_conf = score_abs
                else:
                    effective_final_dir = 1 if final_score > 0 else -1
                    effective_final_conf = min(score_abs, 1.0)
                
                # Round confidence to match run_step_live output
                effective_final_conf = round(effective_final_conf, 2)
                
                # Skip if no direction (after neutral zone)
                if effective_final_dir == 0:
                    continue
                
                # Use effective values for analysis
                final_dir = effective_final_dir
                final_conf = effective_final_conf
                
                # Track regime for meta
                regime_counts[price_based_regime] += 1
                
                # Get confidence bin
                conf_bin = get_conf_bin(final_conf)
                
                # Compute forward returns for each horizon
                entry_price = current_bar["close"]
                
                for horizon in horizons:
                    # Check if we have enough bars ahead
                    if i + horizon >= len(candles):
                        continue
                    
                    future_bar = candles[i + horizon]
                    exit_price = future_bar["close"]
                    
                    # Compute signed return (multiply by direction so "correct" trades are positive)
                    raw_ret = (exit_price - entry_price) / entry_price
                    signed_ret = raw_ret * final_dir  # Long: positive if price up, Short: positive if price down
                    
                    # Bin key: (regime, horizon, conf_min, conf_max)
                    bin_key = (price_based_regime, horizon, conf_bin[0], conf_bin[1])
                    
                    # Update stats
                    stats = bin_stats[bin_key]
                    stats["count"] += 1
                    if signed_ret > 0:
                        stats["wins"] += 1
                        stats["pos_sum"] += signed_ret
                    elif signed_ret < 0:
                        stats["losses"] += 1
                        stats["neg_sum"] += abs(signed_ret)
                    stats["returns"].append(signed_ret)
                    
                    # Track direction counts
                    if final_dir > 0:
                        stats["long_count"] += 1
                    elif final_dir < 0:
                        stats["short_count"] += 1
                
            except Exception as e:
                # Skip bars that fail (defensive)
                if os.getenv("DEBUG_SIGNALS") == "1":
                    print(f"⚠️  Error processing bar {i}: {e}")
                continue
    
    finally:
        # Restore original functions
        live_prices.get_live_ohlcv = original_get_live_ohlcv
        if original_signal_get_live_ohlcv is not None:
            signal_processor.get_live_ohlcv = original_signal_get_live_ohlcv
    
    # Compute summary statistics
    print(f"\n📊 Computing summary statistics...")
    bins = []
    for (regime, horizon, conf_min, conf_max), stats in sorted(bin_stats.items()):
        count = stats["count"]
        if count == 0:
            continue
        
        pos_sum = stats["pos_sum"]
        neg_sum = stats["neg_sum"]
        returns = stats["returns"]
        
        # Compute PF
        if neg_sum > 0:
            pf = pos_sum / neg_sum
        elif pos_sum > 0:
            pf = float("inf")
        else:
            pf = 0.0
        
        # Compute mean return
        mean_ret = (pos_sum - neg_sum) / count if count > 0 else 0.0
        
        # Compute standard deviation
        std_ret = compute_std(returns, mean_ret)
        
        # Compute percentiles
        p50 = compute_percentile(returns, 0.50)
        p75 = compute_percentile(returns, 0.75)
        p90 = compute_percentile(returns, 0.90)
        p95 = compute_percentile(returns, 0.95)
        p5 = compute_percentile(returns, 0.05)
        
        # Separate positive and negative returns for avg_win/avg_loss
        pos_returns = [r for r in returns if r > 0]
        neg_returns = [r for r in returns if r < 0]
        
        avg_win = sum(pos_returns) / len(pos_returns) if pos_returns else 0.0
        avg_loss = sum(neg_returns) / len(neg_returns) if neg_returns else 0.0
        
        # Win rate
        win_rate = stats["wins"] / count if count > 0 else 0.0
        
        # p95 of positive returns (for TP sizing)
        p95_ret = compute_percentile(pos_returns, 0.95) if pos_returns else 0.0
        
        # p5 of all returns (worst-case tail)
        p5_ret = p5  # Already computed above
        
        bins.append({
            "regime": regime,
            "horizon": horizon,
            "conf_min": conf_min,
            "conf_max": conf_max,
            "count": count,
            "wins": stats["wins"],
            "losses": stats["losses"],
            "pos_sum": pos_sum,
            "neg_sum": neg_sum,
            "pf": pf,
            "mean_ret": mean_ret,
            "std_ret": std_ret,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "p50": p50,
            "p75": p75,
            "p90": p90,
            "p95": p95,
            "p5": p5,
            "p95_ret": p95_ret,  # 95th percentile of positive returns
            "p5_ret": p5_ret,    # 5th percentile of all returns (worst tail)
            "long_count": stats["long_count"],
            "short_count": stats["short_count"],
        })
    
    # Sort bins by regime, horizon, then conf_min
    bins.sort(key=lambda b: (b["regime"], b["horizon"], b["conf_min"]))
    
    # Build output with new format
    output_data = {
        "meta": {
            "symbol": args.symbol,
            "timeframe": args.timeframe,
            "csv": args.csv,
            "window": args.window,
            "horizons": horizons,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "bars_processed": total_bars,
            "regime_counts": dict(regime_counts),
        },
        "bins": bins,
    }
    
    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\n✅ Analysis complete!")
    print(f"   Total bins: {len(bins)}")
    print(f"   Output: {output_path}")
    
    # Print summary by regime
    print(f"\n📈 Summary by regime:")
    for regime in sorted(regime_counts.keys()):
        count = regime_counts[regime]
        print(f"   {regime:12s}: {count:6d} bars")
    
    # Print summary by horizon
    print(f"\n📈 Summary by horizon:")
    horizon_counts = defaultdict(int)
    for bin_data in bins:
        horizon_counts[bin_data["horizon"]] += bin_data["count"]
    
    for horizon in sorted(horizon_counts.keys()):
        count = horizon_counts[horizon]
        print(f"   {horizon} bar(s): {count:6d} samples")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

