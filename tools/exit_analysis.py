"""
Exit Analysis Tool - Analyzes exit reasons and trade performance.

Groups trades by symbol and exit_reason, computes statistics,
and provides insights into exit behavior patterns.
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
    """Load JSONL file, return empty list if missing."""
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
                # Skip malformed lines
                continue
    return records


def compute_exit_stats(trades: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Compute exit statistics grouped by symbol and exit_reason.
    
    Returns:
        {
            "ETHUSDT": {
                "tp": {"count": 3, "avg": 1.42, "median": 1.31, "wins": 3, "losses": 0, ...},
                "sl": {"count": 1, "avg": -0.82, ...},
                "exploration": {"count": 4, "avg": 1.01, ...},
                "normal": {"count": 1, "avg": 2.11, ...},
            }
        }
    """
    per_symbol: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(lambda: defaultdict(lambda: {
        "count": 0,
        "pct_values": [],
        "wins": 0,
        "losses": 0,
        "scratches": 0,
        "buckets": {
            ">1%": 0,
            "0-1%": 0,
            "-1-0%": 0,
            "<-1%": 0,
        }
    }))
    
    for ev in trades:
        # Only process v2 close events
        if ev.get("logger_version") != "trades_v2":
            continue
        if ev.get("type") != "close":
            continue
        
        symbol = ev.get("symbol")
        if not symbol:
            continue
        
        pct = ev.get("pct")
        try:
            pct = float(pct)
        except (TypeError, ValueError):
            continue
        
        exit_reason = ev.get("exit_reason", "unknown")
        trade_kind = ev.get("trade_kind", "normal")
        
        # Normalize exit reason (handle variations)
        exit_reason = exit_reason.lower()
        if exit_reason in ["take_profit", "tp"]:
            exit_reason = "tp"
        elif exit_reason in ["stop_loss", "sl"]:
            exit_reason = "sl"
        elif exit_reason in ["reverse", "reversal"]:
            exit_reason = "reverse"
        elif exit_reason in ["decay", "time_decay"]:
            exit_reason = "decay"
        elif exit_reason in ["drop", "signal_drop"]:
            exit_reason = "drop"
        else:
            exit_reason = "other"
        
        # Update per exit_reason stats
        exit_bucket = per_symbol[symbol][exit_reason]
        exit_bucket["count"] += 1
        exit_bucket["pct_values"].append(pct)
        
        if pct > 0.001:  # Win threshold
            exit_bucket["wins"] += 1
        elif pct < -0.001:  # Loss threshold
            exit_bucket["losses"] += 1
        else:
            exit_bucket["scratches"] += 1
        
        # Distribution buckets
        if pct > 0.01:
            exit_bucket["buckets"][">1%"] += 1
        elif pct > 0:
            exit_bucket["buckets"]["0-1%"] += 1
        elif pct > -0.01:
            exit_bucket["buckets"]["-1-0%"] += 1
        else:
            exit_bucket["buckets"]["<-1%"] += 1
        
        # Update per trade_kind stats
        kind_bucket = per_symbol[symbol][trade_kind]
        kind_bucket["count"] += 1
        kind_bucket["pct_values"].append(pct)
        
        if pct > 0.001:
            kind_bucket["wins"] += 1
        elif pct < -0.001:
            kind_bucket["losses"] += 1
        else:
            kind_bucket["scratches"] += 1
        
        if pct > 0.01:
            kind_bucket["buckets"][">1%"] += 1
        elif pct > 0:
            kind_bucket["buckets"]["0-1%"] += 1
        elif pct > -0.01:
            kind_bucket["buckets"]["-1-0%"] += 1
        else:
            kind_bucket["buckets"]["<-1%"] += 1
    
    # Compute averages and medians
    result: Dict[str, Dict[str, Any]] = {}
    for symbol, buckets in per_symbol.items():
        symbol_stats: Dict[str, Any] = {}
        
        for key, bucket in buckets.items():
            if bucket["count"] == 0:
                continue
            
            pct_values = bucket["pct_values"]
            avg_pct = sum(pct_values) / len(pct_values) if pct_values else 0.0
            med_pct = median(pct_values) if len(pct_values) >= 2 else (pct_values[0] if pct_values else 0.0)
            
            symbol_stats[key] = {
                "count": bucket["count"],
                "avg": avg_pct,
                "median": med_pct,
                "wins": bucket["wins"],
                "losses": bucket["losses"],
                "scratches": bucket["scratches"],
                "buckets": bucket["buckets"],
            }
        
        if symbol_stats:
            result[symbol] = symbol_stats
    
    return result


def format_pct(pct: float) -> str:
    """Format percentage for display."""
    return f"{pct:+.2f}%"


def main() -> None:
    """Display exit analysis."""
    print("EXIT ANALYSIS")
    print("-" * 70)
    print()
    
    trades = load_jsonl(TRADES_PATH)
    
    if not trades:
        print("⚠️  No trades found in trades.jsonl")
        print(f"   Path: {TRADES_PATH}")
        return
    
    stats = compute_exit_stats(trades)
    
    if not stats:
        print("⚠️  No valid trade data found")
        print("   (No v2 close events with valid pct values)")
        return
    
    # Sort symbols alphabetically
    sorted_symbols = sorted(stats.keys())
    
    # Exit reason order for display
    exit_order = ["tp", "sl", "reverse", "decay", "drop", "other"]
    
    for symbol in sorted_symbols:
        symbol_stats = stats[symbol]
        print(f"{symbol}:")
        
        # Display exit reasons
        for exit_reason in exit_order:
            if exit_reason in symbol_stats:
                bucket = symbol_stats[exit_reason]
                count = bucket["count"]
                avg = bucket["avg"]
                med = bucket["median"]
                wins = bucket["wins"]
                losses = bucket["losses"]
                
                print(f"  {exit_reason:8} {count:3d} trades, "
                      f"avg {format_pct(avg)}, median {format_pct(med)} "
                      f"(W:{wins} L:{losses})")
        
        # Display trade_kind summaries
        if "exploration" in symbol_stats:
            bucket = symbol_stats["exploration"]
            count = bucket["count"]
            avg = bucket["avg"]
            print(f"  exploration: {count:3d} trades, avg {format_pct(avg)}")
        
        if "normal" in symbol_stats:
            bucket = symbol_stats["normal"]
            count = bucket["count"]
            avg = bucket["avg"]
            print(f"  normal:     {count:3d} trades, avg {format_pct(avg)}")
        
        print()
    
    # Summary
    print("-" * 70)
    print(f"Total symbols analyzed: {len(sorted_symbols)}")
    print(f"Total trades analyzed: {len([t for t in trades if t.get('type') == 'close' and t.get('logger_version') == 'trades_v2'])}")
    print()
    print("💡 Exit reasons:")
    print("   tp = take profit, sl = stop loss")
    print("   reverse = signal reversal, decay = time decay")
    print("   drop = signal drop, other = unknown/misc")


if __name__ == "__main__":
    main()


