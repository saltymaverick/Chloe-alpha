#!/usr/bin/env python3
"""
Threshold Tuner Tool
Reads backtest summaries and proposes updated entry thresholds based on PF by regime.

This tool:
- Scans backtest run directories for summary.json files
- Aggregates PF stats by regime
- Proposes threshold adjustments based on performance
- Optionally writes updated config/entry_thresholds.json

Usage:
    # Dry run (show recommendations only)
    python3 -m tools.threshold_tuner --root reports/backtest

    # Apply and write new thresholds
    python3 -m tools.threshold_tuner --root reports/backtest --apply
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine_alpha.core.paths import CONFIG


# Default thresholds (must match autonomous_trader.py)
ENTRY_THRESHOLDS_DEFAULT = {
    "trend_down": 0.50,
    "high_vol": 0.55,
    "trend_up": 0.60,
    "chop": 0.65,
}


def load_current_thresholds() -> Dict[str, float]:
    """Load current thresholds from config file."""
    cfg_path = CONFIG / "entry_thresholds.json"
    if not cfg_path.exists():
        return dict(ENTRY_THRESHOLDS_DEFAULT)
    try:
        data = json.loads(cfg_path.read_text())
        merged = dict(ENTRY_THRESHOLDS_DEFAULT)
        merged.update({k: float(v) for k, v in data.items() if isinstance(v, (int, float, str))})
        return merged
    except Exception:
        return dict(ENTRY_THRESHOLDS_DEFAULT)


def _compute_pf_by_regime_from_trades(trades_path: Path) -> Dict[str, Dict[str, Any]]:
    """Compute pf_by_regime from trades.jsonl if summary.json doesn't have it."""
    import math
    from collections import defaultdict
    
    closes = []
    try:
        with open(trades_path, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    t = json.loads(line)
                    if t.get("type") == "close":
                        closes.append(t)
                except Exception:
                    continue
    except Exception:
        return {}
    
    regime_closes = defaultdict(list)
    for c in closes:
        regime = c.get("regime", "unknown")
        regime_closes[regime].append(c)
    
    regimes = {}
    for regime, regime_close_list in regime_closes.items():
        regime_wins = [c["pct"] for c in regime_close_list if c["pct"] > 0]
        regime_losses = [c["pct"] for c in regime_close_list if c["pct"] < 0]
        regime_pos_sum = sum(regime_wins)
        regime_neg_sum = abs(sum(regime_losses))
        regime_pf = (
            math.inf if regime_neg_sum == 0 and regime_pos_sum > 0
            else (regime_pos_sum / regime_neg_sum if regime_neg_sum > 0 else 0.0)
        )
        
        regimes[regime] = {
            "closes": len(regime_close_list),
            "wins": len(regime_wins),
            "losses": len(regime_losses),
            "pos_sum": regime_pos_sum,
            "neg_sum": -regime_neg_sum,
            "pf": regime_pf,
        }
    
    return regimes


def scan_backtest_runs(root_dir: Path) -> List[Dict[str, Any]]:
    """
    Scan backtest run directories and load summary.json files.
    
    If summary.json doesn't have pf_by_regime, compute it from trades.jsonl.
    
    Returns:
        List of summary dicts, one per run directory (with pf_by_regime populated)
    """
    summaries = []
    if not root_dir.exists():
        return summaries
    
    for run_dir in root_dir.iterdir():
        if not run_dir.is_dir():
            continue
        
        summary_path = run_dir / "summary.json"
        if not summary_path.exists():
            continue
        
        try:
            with open(summary_path, "r") as f:
                summary = json.load(f)
            
            # If pf_by_regime is missing or empty, try to compute from trades.jsonl
            if not summary.get("pf_by_regime") and not summary.get("regimes"):
                trades_path = run_dir / "trades.jsonl"
                if trades_path.exists():
                    pf_by_regime = _compute_pf_by_regime_from_trades(trades_path)
                    if pf_by_regime:
                        summary["pf_by_regime"] = pf_by_regime
            
            summaries.append(summary)
        except Exception:
            continue
    
    return summaries


def aggregate_by_regime(summaries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Aggregate PF stats by regime across all backtest runs.
    
    Returns:
        Dict mapping regime -> {closes, pos_sum, neg_sum, pf, count}
    """
    regime_stats: Dict[str, Dict[str, float]] = defaultdict(lambda: {
        "closes": 0,
        "pos_sum": 0.0,
        "neg_sum": 0.0,
    })
    
    for summary in summaries:
        # Check if summary has pf_by_regime breakdown (new format)
        pf_by_regime = summary.get("pf_by_regime")
        if pf_by_regime and isinstance(pf_by_regime, dict) and len(pf_by_regime) > 0:
            for regime, regime_data in pf_by_regime.items():
                if isinstance(regime_data, dict):
                    closes = regime_data.get("closes", 0)
                    pos_sum = regime_data.get("pos_sum", 0.0)
                    neg_sum = abs(regime_data.get("neg_sum", 0.0))
                    
                    regime_stats[regime]["closes"] += closes
                    regime_stats[regime]["pos_sum"] += pos_sum
                    regime_stats[regime]["neg_sum"] += neg_sum
            continue  # Skip legacy check if we found pf_by_regime
        
        # Also check legacy "regimes" key for backward compatibility
        if "regimes" in summary and isinstance(summary["regimes"], dict) and len(summary["regimes"]) > 0:
            for regime, regime_data in summary["regimes"].items():
                if isinstance(regime_data, dict):
                    closes = regime_data.get("closes", 0)
                    pos_sum = regime_data.get("pos_sum", 0.0)
                    neg_sum = abs(regime_data.get("neg_sum", 0.0))
                    
                    regime_stats[regime]["closes"] += closes
                    regime_stats[regime]["pos_sum"] += pos_sum
                    regime_stats[regime]["neg_sum"] += neg_sum
    
    # Compute PF for each regime
    result = {}
    for regime, stats in regime_stats.items():
        closes = stats["closes"]
        pos_sum = stats["pos_sum"]
        neg_sum = stats["neg_sum"]
        
        if neg_sum > 0:
            pf = pos_sum / neg_sum
        elif pos_sum > 0:
            pf = float("inf")
        else:
            pf = 0.0
        
        result[regime] = {
            "closes": closes,
            "pos_sum": pos_sum,
            "neg_sum": neg_sum,
            "pf": pf,
        }
    
    return result


def propose_threshold(
    regime: str,
    current_threshold: float,
    closes: int,
    pf: float,
    min_closes: int,
    min_pf: float,
    max_pf: float,
) -> tuple[float, str]:
    """
    Propose a new threshold based on performance.
    
    Returns:
        (new_threshold, action_description)
    """
    if closes < min_closes:
        # Insufficient data - keep current
        return current_threshold, "keep (insufficient data)"
    
    if math.isinf(pf) or pf >= max_pf:
        # Regime is very strong - can afford to be slightly more permissive
        new = max(current_threshold - 0.03, 0.35)
        action = "lower (strong)"
    elif min_pf <= pf < max_pf:
        # Regime is fine - leave threshold unchanged
        new = current_threshold
        action = "keep"
    else:
        # Regime is weak or losing - make it stricter
        new = min(current_threshold + 0.05, 0.90)
        action = "raise (weak)"
    
    return round(new, 2), action


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tune entry thresholds based on backtest performance"
    )
    parser.add_argument(
        "--root",
        type=str,
        default="reports/backtest",
        help="Root directory containing backtest runs (default: reports/backtest)",
    )
    parser.add_argument(
        "--min-closes",
        type=int,
        default=20,
        help="Minimum closes per regime to trust (default: 20)",
    )
    parser.add_argument(
        "--min-pf",
        type=float,
        default=1.1,
        help="PF lower bound for 'good regime' (default: 1.1)",
    )
    parser.add_argument(
        "--max-pf",
        type=float,
        default=1.5,
        help="PF upper bound for 'very good regime' (default: 1.5)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes and write config/entry_thresholds.json (default: dry run)",
    )
    
    args = parser.parse_args()
    
    root_dir = Path(args.root)
    
    print("=" * 70)
    print("Threshold Tuner")
    print("=" * 70)
    print(f"\n📋 Configuration:")
    print(f"   Root directory:  {root_dir}")
    print(f"   Min closes:      {args.min_closes}")
    print(f"   Min PF:          {args.min_pf}")
    print(f"   Max PF:          {args.max_pf}")
    print(f"   Apply changes:   {args.apply}")
    print()
    
    # Load current thresholds
    current_thresholds = load_current_thresholds()
    
    # Scan backtest runs
    print(f"🔍 Scanning backtest runs in {root_dir}...")
    summaries = scan_backtest_runs(root_dir)
    
    if not summaries:
        print(f"⚠️  No backtest summaries found in {root_dir}")
        print("   Make sure you've run some backtests first.")
        return 1
    
    print(f"   Found {len(summaries)} backtest run(s)")
    
    # Aggregate by regime
    regime_stats = aggregate_by_regime(summaries)
    
    if not regime_stats:
        print("⚠️  No regime-specific stats found in summaries")
        print("   Possible reasons:")
        print("   - All backtest runs had 0 closes (no trades)")
        print("   - Summary files missing 'pf_by_regime' or 'regimes' keys")
        print("   - Run some backtests that generate trades first")
        return 1
    
    # Propose new thresholds
    proposed_thresholds = dict(ENTRY_THRESHOLDS_DEFAULT)
    proposals = []
    
    for regime in ["trend_down", "high_vol", "trend_up", "chop"]:
        current = current_thresholds.get(regime, ENTRY_THRESHOLDS_DEFAULT.get(regime, 0.65))
        
        if regime in regime_stats:
            stats = regime_stats[regime]
            closes = stats["closes"]
            pf = stats["pf"]
            
            new_threshold, action = propose_threshold(
                regime,
                current,
                closes,
                pf,
                args.min_closes,
                args.min_pf,
                args.max_pf,
            )
            
            proposed_thresholds[regime] = new_threshold
            proposals.append({
                "regime": regime,
                "closes": closes,
                "pf": pf,
                "old_thr": current,
                "new_thr": new_threshold,
                "action": action,
            })
        else:
            # No data for this regime - keep current
            proposed_thresholds[regime] = current
            proposals.append({
                "regime": regime,
                "closes": 0,
                "pf": 0.0,
                "old_thr": current,
                "new_thr": current,
                "action": "keep (no data)",
            })
    
    # Print table
    print("\n" + "=" * 70)
    print("Threshold Recommendations")
    print("=" * 70)
    print(f"{'Regime':<12} {'Closes':<8} {'PF':<8} {'OldThr':<8} {'NewThr':<8} {'Action':<20}")
    print("-" * 70)
    
    for prop in proposals:
        pf_str = f"{prop['pf']:.2f}" if not math.isinf(prop['pf']) else "inf"
        print(
            f"{prop['regime']:<12} {prop['closes']:<8} {pf_str:<8} "
            f"{prop['old_thr']:<8.2f} {prop['new_thr']:<8.2f} {prop['action']:<20}"
        )
    
    # Check if any changes
    has_changes = any(
        proposals[i]["old_thr"] != proposals[i]["new_thr"]
        for i in range(len(proposals))
    )
    
    if not has_changes:
        print("\n✅ No threshold changes recommended (all regimes performing as expected)")
        return 0
    
    # Apply changes if requested
    if args.apply:
        cfg_path = CONFIG / "entry_thresholds.json"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(cfg_path, "w") as f:
            json.dump(proposed_thresholds, f, indent=2)
        
        print("\n" + "=" * 70)
        print(f"✅ Updated thresholds written to {cfg_path}")
        print("   Restart Chloe to apply new thresholds.")
        print("=" * 70)
    else:
        print("\n" + "=" * 70)
        print("💡 Dry run complete - no changes applied")
        print("   Run with --apply to write updated thresholds to config/entry_thresholds.json")
        print("=" * 70)
    
    return 0


if __name__ == "__main__":
    exit(main())

