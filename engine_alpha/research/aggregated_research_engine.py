"""
Aggregated Research Engine (ARE) - Multi-horizon trade performance analysis.

Aggregates trade performance across short, medium, and long horizons per symbol.
"""

from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, Any, List, Optional
from statistics import median, stdev

ROOT = Path(__file__).resolve().parents[2]
TRADES_PATH = ROOT / "reports" / "trades.jsonl"
RESEARCH_DIR = ROOT / "reports" / "research"


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


def compute_horizon_stats(trades: List[float], horizon_name: str) -> Dict[str, Any]:
    """Compute statistics for a horizon."""
    if not trades:
        return {
            "exp_trades_count": 0,
            "exp_pf": None,
            "avg_pct": None,
            "med_pct": None,
            "win_rate": None,
            "big_win_count": 0,
            "big_loss_count": 0,
        }
    
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t < 0]
    
    # PF
    total_wins = sum(wins) if wins else 0.0
    total_losses = abs(sum(losses)) if losses else 0.0
    exp_pf = None
    if total_losses > 0:
        exp_pf = total_wins / total_losses
    elif total_wins > 0:
        exp_pf = float("inf")
    
    # Win rate
    win_rate = len(wins) / len(trades) if trades else None
    
    # Big wins/losses
    big_wins = sum(1 for t in trades if t >= 0.01)
    big_losses = sum(1 for t in trades if t <= -0.01)
    
    # Volatility
    std_pct = stdev(trades) if len(trades) >= 2 else None
    
    return {
        "exp_trades_count": len(trades),
        "exp_pf": exp_pf,
        "avg_pct": sum(trades) / len(trades) if trades else None,
        "med_pct": median(trades) if len(trades) >= 2 else (trades[0] if trades else None),
        "win_rate": win_rate,
        "big_win_count": big_wins,
        "big_loss_count": big_losses,
        "volatility_std_pct": std_pct,
    }


def compute_exit_reason_counts(trades: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count exit reasons in trades."""
    counts = defaultdict(int)
    for trade in trades:
        exit_reason = trade.get("exit_reason", "unknown")
        exit_reason = exit_reason.lower()
        if exit_reason in ["take_profit", "tp"]:
            counts["tp"] += 1
        elif exit_reason in ["stop_loss", "sl"]:
            counts["sl"] += 1
        elif exit_reason in ["reverse", "reversal"]:
            counts["reverse"] += 1
        elif exit_reason in ["decay", "time_decay"]:
            counts["decay"] += 1
        elif exit_reason in ["drop", "signal_drop"]:
            counts["drop"] += 1
        else:
            counts["other"] += 1
    return dict(counts)


def generate_are_snapshot() -> Dict[str, Any]:
    """Generate ARE snapshot from trades.jsonl."""
    trades = load_jsonl(TRADES_PATH)
    
    # Filter to exploration close events
    exploration_trades: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    
    for ev in trades:
        if ev.get("logger_version") != "trades_v2":
            continue
        if ev.get("type") != "close":
            continue
        if ev.get("trade_kind") != "exploration":
            continue
        
        symbol = ev.get("symbol")
        pct = ev.get("pct")
        
        if not symbol or pct is None:
            continue
        
        try:
            pct = float(pct)
        except (TypeError, ValueError):
            continue
        
        exploration_trades[symbol].append({
            "pct": pct,
            "exit_reason": ev.get("exit_reason"),
        })
    
    # Sort trades by order in file (most recent last)
    for symbol in exploration_trades:
        exploration_trades[symbol].reverse()  # Most recent first
    
    # Compute per-symbol ARE stats
    are_snapshot: Dict[str, Dict[str, Any]] = {}
    
    for symbol, trade_list in exploration_trades.items():
        pct_values = [t["pct"] for t in trade_list]
        
        # Short horizon: last 5 trades
        short_trades = pct_values[:5]
        short_stats = compute_horizon_stats(short_trades, "short")
        short_stats["exit_reason_counts"] = compute_exit_reason_counts(
            trade_list[:5]
        )
        
        # Medium horizon: last 10 trades
        medium_trades = pct_values[:10]
        medium_stats = compute_horizon_stats(medium_trades, "medium")
        medium_stats["exit_reason_counts"] = compute_exit_reason_counts(
            trade_list[:10]
        )
        
        # Long horizon: all trades
        long_trades = pct_values
        long_stats = compute_horizon_stats(long_trades, "long")
        long_stats["exit_reason_counts"] = compute_exit_reason_counts(trade_list)
        
        are_snapshot[symbol] = {
            "short": short_stats,
            "medium": medium_stats,
            "long": long_stats,
        }
    
    return {
        "generated_at": json.dumps({}).split('"')[0] if False else "",  # Placeholder
        "symbols": are_snapshot,
    }


def main() -> None:
    """Generate ARE snapshot."""
    snapshot = generate_are_snapshot()
    
    # Add timestamp
    from datetime import datetime, timezone
    snapshot["generated_at"] = datetime.now(timezone.utc).isoformat()
    
    # Write to reports
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESEARCH_DIR / "are_snapshot.json"
    output_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True))
    
    print(f"✅ ARE snapshot written to: {output_path}")
    print(f"   Symbols analyzed: {len(snapshot.get('symbols', {}))}")
    
    # Print summary
    for symbol, data in sorted(snapshot.get("symbols", {}).items()):
        short_pf = data.get("short", {}).get("exp_pf")
        long_pf = data.get("long", {}).get("exp_pf")
        short_str = "∞" if short_pf == float("inf") else f"{short_pf:.2f}" if short_pf else "—"
        long_str = "∞" if long_pf == float("inf") else f"{long_pf:.2f}" if long_pf else "—"
        print(f"   {symbol}: short_exp_pf={short_str}, long_exp_pf={long_str}")


if __name__ == "__main__":
    main()


