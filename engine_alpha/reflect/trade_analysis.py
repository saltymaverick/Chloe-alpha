"""
Trade analysis - Phase 3
PF (Profit Factor) calculations from trades.
"""

import json
from pathlib import Path
from typing import List, Dict, Any


def pf_from_trades(trades: List[Dict[str, Any]]) -> float:
    """
    Calculate profit factor from trades.
    PF = (sum of positive pct) / (abs sum of negative pct)
    
    Args:
        trades: List of trade dictionaries
    
    Returns:
        Profit factor (handle 0-loss edge case)
    """
    if not trades:
        return 1.0
    
    positive_sum = 0.0
    negative_sum = 0.0
    
    for trade in trades:
        pnl_pct = trade.get("pnl_pct", 0.0)
        if pnl_pct > 0:
            positive_sum += pnl_pct
        elif pnl_pct < 0:
            negative_sum += abs(pnl_pct)
    
    # Handle edge case: no losses
    if negative_sum == 0:
        if positive_sum > 0:
            return 999.0  # Use large number instead of inf for JSON compatibility
        else:
            return 1.0  # No wins or losses
    
    return positive_sum / negative_sum


def update_pf_reports(trades_path: Path, out_pf_local: Path, out_pf_live: Path, 
                      window: int = 150) -> None:
    """
    Read trades.jsonl, compute PF_local and PF_live, write JSON files.
    
    Args:
        trades_path: Path to trades.jsonl
        out_pf_local: Path to output pf_local.json
        out_pf_live: Path to output pf_live.json
        window: Window size for PF_local calculation (default: 150)
    """
    # Read trades
    trades = []
    if trades_path.exists():
        with open(trades_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        trade = json.loads(line)
                        trades.append(trade)
                    except json.JSONDecodeError:
                        continue
    
    # Filter for CLOSE events only (these have P&L)
    close_trades = [t for t in trades if t.get("event") == "CLOSE"]
    
    # Calculate PF_live (all trades)
    pf_live = pf_from_trades(close_trades)
    
    # Calculate PF_local (last N trades)
    pf_local_trades = close_trades[-window:] if len(close_trades) > window else close_trades
    pf_local = pf_from_trades(pf_local_trades)
    
    # Write PF_live
    pf_live_data = {
        "pf": pf_live,
        "total_trades": len(close_trades),
        "window": len(close_trades),
    }
    out_pf_live.parent.mkdir(parents=True, exist_ok=True)
    with open(out_pf_live, "w") as f:
        json.dump(pf_live_data, f, indent=2)
    
    # Write PF_local
    pf_local_data = {
        "pf": pf_local,
        "total_trades": len(pf_local_trades),
        "window": window,
    }
    out_pf_local.parent.mkdir(parents=True, exist_ok=True)
    with open(out_pf_local, "w") as f:
        json.dump(pf_local_data, f, indent=2)

