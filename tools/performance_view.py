"""
Performance View - Textual view on PF with emphasis on sample size and balance.
"""

from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, Any, List, Optional
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
TRADES_PATH = ROOT / "reports" / "trades.jsonl"


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load JSONL file."""
    if not path.exists():
        return []
    records = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    return records


def format_pf(pf: Optional[float]) -> str:
    """Format PF for display."""
    if pf is None:
        return "—"
    if pf == float("inf"):
        return "∞"
    return f"{pf:.2f}"


def format_pct(pct: float) -> str:
    """Format percentage for display."""
    return f"{pct:+.2f}%"


def main() -> None:
    """Display performance view."""
    print("PERFORMANCE VIEW")
    print("=" * 90)
    print()
    
    trades = load_jsonl(TRADES_PATH)
    
    if not trades:
        print("⚠️  No trades found in trades.jsonl")
        return
    
    # Process trades
    per_symbol: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "exploration": {"trades": [], "wins": [], "losses": []},
        "normal": {"trades": [], "wins": [], "losses": []},
    })
    
    for ev in trades:
        if ev.get("logger_version") != "trades_v2":
            continue
        if ev.get("type") != "close":
            continue
        
        symbol = ev.get("symbol")
        pct = ev.get("pct")
        trade_kind = ev.get("trade_kind", "normal")
        
        if not symbol or pct is None:
            continue
        
        try:
            pct = float(pct)
        except (TypeError, ValueError):
            continue
        
        bucket = per_symbol[symbol][trade_kind]
        bucket["trades"].append(pct)
        
        if pct > 0:
            bucket["wins"].append(pct)
        elif pct < 0:
            bucket["losses"].append(pct)
    
    # Compute stats
    results = []
    for symbol, buckets in per_symbol.items():
        exp_bucket = buckets["exploration"]
        norm_bucket = buckets["normal"]
        
        exp_trades = exp_bucket["trades"]
        norm_trades = norm_bucket["trades"]
        
        # Exploration PF
        exp_pf = None
        if exp_trades:
            exp_wins = exp_bucket["wins"]
            exp_losses = exp_bucket["losses"]
            total_wins = sum(exp_wins) if exp_wins else 0.0
            total_losses = abs(sum(exp_losses)) if exp_losses else 0.0
            if total_losses > 0:
                exp_pf = total_wins / total_losses
            elif total_wins > 0:
                exp_pf = float("inf")
        
        # Normal PF
        norm_pf = None
        if norm_trades:
            norm_wins = norm_bucket["wins"]
            norm_losses = norm_bucket["losses"]
            total_wins = sum(norm_wins) if norm_wins else 0.0
            total_losses = abs(sum(norm_losses)) if norm_losses else 0.0
            if total_losses > 0:
                norm_pf = total_wins / total_losses
            elif total_wins > 0:
                norm_pf = float("inf")
        
        # Average and median
        all_trades = exp_trades + norm_trades
        avg_pct = sum(all_trades) / len(all_trades) if all_trades else 0.0
        med_pct = median(all_trades) if len(all_trades) >= 2 else (all_trades[0] if all_trades else 0.0)
        
        # Distribution buckets
        gt_1pct = sum(1 for t in all_trades if t > 0.01)
        lt_neg1pct = sum(1 for t in all_trades if t < -0.01)
        
        results.append({
            "symbol": symbol,
            "exp_trades": len(exp_trades),
            "exp_pf": exp_pf,
            "norm_trades": len(norm_trades),
            "norm_pf": norm_pf,
            "avg_pct": avg_pct,
            "med_pct": med_pct,
            "gt_1pct": gt_1pct,
            "lt_neg1pct": lt_neg1pct,
        })
    
    # Sort by symbol
    results.sort(key=lambda x: x["symbol"])
    
    # Print header
    print(f"{'Symbol':<12} {'ExpTr':<6} {'ExpPF':<7} {'NormTr':<7} {'NormPF':<7} "
          f"{'AvgPct':<8} {'MedPct':<8} {'>1%':<5} {'<-1%':<5}")
    print("-" * 90)
    
    # Print rows
    for r in results:
        print(f"{r['symbol']:<12} {r['exp_trades']:<6} {format_pf(r['exp_pf']):<7} "
              f"{r['norm_trades']:<7} {format_pf(r['norm_pf']):<7} "
              f"{format_pct(r['avg_pct']):<8} {format_pct(r['med_pct']):<8} "
              f"{r['gt_1pct']:<5} {r['lt_neg1pct']:<5}")
    
    print()


if __name__ == "__main__":
    main()
