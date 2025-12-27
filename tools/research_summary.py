#!/usr/bin/env python3
"""
Research Summary - Quick view of weighted research results

Shows top/bottom regimes by weighted expectancy from the analyzer output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any

ROOT_DIR = Path(__file__).resolve().parents[1]
RESEARCH_DIR = ROOT_DIR / "reports" / "research"
ANALYZER_OUT_PATH = RESEARCH_DIR / "multi_horizon_stats.json"


def load_analyzer_stats(path: Path = ANALYZER_OUT_PATH) -> Dict[str, Any]:
    """Load analyzer output."""
    if not path.exists():
        return {}
    with path.open("r") as f:
        return json.load(f)


def summarize_regimes(stats: Dict[str, Any], horizon: str = "ret_4h") -> None:
    """Print summary of regime performance by weighted expectancy."""
    if not stats:
        print("❌ No analyzer stats found")
        print(f"   Expected: {ANALYZER_OUT_PATH}")
        print("   Run: python3 -m engine_alpha.reflect.nightly_research")
        return
    
    if horizon not in stats:
        available = list(stats.keys())
        if available:
            horizon = available[0]
            print(f"⚠️  Horizon '{horizon}' not found, using '{horizon}'")
        else:
            print("❌ No horizon data found in stats")
            return
    
    horizon_stats = stats[horizon]["stats"]
    
    # Aggregate by regime
    regime_data: Dict[str, Dict[str, Any]] = {}
    
    for key, s in horizon_stats.items():
        regime, bucket_str = key.split("|")
        bucket = int(bucket_str)
        
        if regime not in regime_data:
            regime_data[regime] = {
                "total_count": 0,
                "total_weighted_count": 0.0,
                "weighted_mean": 0.0,
                "weight_sum": 0.0,
                "buckets": [],
            }
        
        count = s.get("count", 0)
        wcount = s.get("weighted_count", 0.0)
        mean = s.get("mean", 0.0)
        
        regime_data[regime]["total_count"] += count
        regime_data[regime]["total_weighted_count"] += wcount
        regime_data[regime]["weight_sum"] += wcount
        regime_data[regime]["weighted_mean"] += mean * wcount
        regime_data[regime]["buckets"].append({
            "bucket": bucket,
            "count": count,
            "weighted_count": wcount,
            "mean": mean,
        })
    
    # Normalize weighted means
    for regime in regime_data:
        wsum = regime_data[regime]["weight_sum"]
        if wsum > 0:
            regime_data[regime]["weighted_mean"] /= wsum
    
    # Sort by weighted mean (expectancy)
    sorted_regimes = sorted(
        regime_data.items(),
        key=lambda x: x[1]["weighted_mean"],
        reverse=True
    )
    
    print("=" * 80)
    print(f"RESEARCH SUMMARY - Horizon: {horizon}")
    print("=" * 80)
    print(f"\n{'Regime':<15} {'Weighted Edge':<15} {'Count':<10} {'W.Count':<10} {'Status'}")
    print("-" * 80)
    
    for regime, data in sorted_regimes:
        edge = data["weighted_mean"]
        count = data["total_count"]
        wcount = data["total_weighted_count"]
        
        if edge > 0.0005:
            status = "✅ Profitable"
        elif edge < -0.0005:
            status = "❌ Losing"
        else:
            status = "➖ Neutral"
        
        print(f"{regime:<15} {edge:>14.6f}  {count:>8}  {wcount:>9.1f}  {status}")
    
    print("\n" + "=" * 80)
    print("Top 3 regimes by weighted expectancy:")
    for i, (regime, data) in enumerate(sorted_regimes[:3], 1):
        edge = data["weighted_mean"]
        print(f"  {i}. {regime}: {edge:.6f} (count={data['total_count']}, wcount={data['total_weighted_count']:.1f})")
    
    if len(sorted_regimes) > 3:
        print("\nBottom 3 regimes:")
        for i, (regime, data) in enumerate(sorted_regimes[-3:], 1):
            edge = data["weighted_mean"]
            print(f"  {i}. {regime}: {edge:.6f} (count={data['total_count']}, wcount={data['total_weighted_count']:.1f})")


def main() -> None:
    stats = load_analyzer_stats()
    summarize_regimes(stats)


if __name__ == "__main__":
    main()


