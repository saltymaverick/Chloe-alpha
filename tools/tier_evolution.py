"""
Tier Evolution Viewer - Shows how symbols' PF and tiers evolve over time.

Text-based timeline viewer showing exploration PF by window.
"""

from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, Any, List, Optional
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
TRADES_PATH = ROOT / "reports" / "trades.jsonl"
WINDOW_SIZE = 3  # Number of trades per window


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


def parse_timestamp(ts: Any) -> Optional[datetime]:
    """Parse timestamp from various formats."""
    if ts is None:
        return None
    
    if isinstance(ts, (int, float)):
        # Unix timestamp
        try:
            return datetime.fromtimestamp(ts)
        except Exception:
            return None
    
    if isinstance(ts, str):
        # ISO format
        try:
            # Try various ISO formats
            for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%SZ"]:
                try:
                    return datetime.strptime(ts.replace("Z", ""), fmt)
                except Exception:
                    continue
            return None
        except Exception:
            return None
    
    return None


def compute_pf(wins: List[float], losses: List[float]) -> Optional[float]:
    """Compute profit factor from wins and losses."""
    if not wins and not losses:
        return None
    
    total_wins = sum(wins) if wins else 0.0
    total_losses = abs(sum(losses)) if losses else 0.0
    
    if total_losses == 0:
        if total_wins > 0:
            return float("inf")
        return None
    
    return total_wins / total_losses


def main() -> None:
    """Display tier evolution."""
    print("TIER EVOLUTION (EXPLORATION PF BY WINDOW)")
    print("=" * 70)
    print()
    
    trades = load_jsonl(TRADES_PATH)
    
    if not trades:
        print("⚠️  No trades found in trades.jsonl")
        return
    
    # Filter to exploration close events
    exploration_trades = []
    for ev in trades:
        if ev.get("logger_version") != "trades_v2":
            continue
        if ev.get("type") != "close":
            continue
        if ev.get("trade_kind") != "exploration":
            continue
        
        symbol = ev.get("symbol")
        pct = ev.get("pct")
        ts = ev.get("time") or ev.get("ts")
        
        if not symbol or pct is None:
            continue
        
        try:
            pct = float(pct)
        except (TypeError, ValueError):
            continue
        
        exploration_trades.append({
            "symbol": symbol,
            "pct": pct,
            "ts": ts,
        })
    
    if not exploration_trades:
        print("⚠️  No exploration trades found")
        return
    
    # Group by symbol
    per_symbol: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for trade in exploration_trades:
        per_symbol[trade["symbol"]].append(trade)
    
    # Sort trades by timestamp within each symbol
    for symbol in per_symbol:
        trades_list = per_symbol[symbol]
        # Try to sort by timestamp, fallback to order in file
        try:
            trades_list.sort(key=lambda t: parse_timestamp(t["ts"]) or datetime.min)
        except Exception:
            pass
    
    # Process each symbol
    for symbol in sorted(per_symbol.keys()):
        trades_list = per_symbol[symbol]
        
        print(f"{symbol}:")
        
        # Try date-based windows first, fallback to N-trade windows
        windows = []
        current_window = []
        current_date = None
        
        for trade in trades_list:
            ts = parse_timestamp(trade["ts"])
            
            if ts:
                trade_date = ts.date()
                if current_date is None:
                    current_date = trade_date
                    current_window = [trade]
                elif trade_date == current_date:
                    current_window.append(trade)
                else:
                    # New day, save current window
                    if current_window:
                        windows.append(current_window)
                    current_date = trade_date
                    current_window = [trade]
            else:
                # No timestamp, use sliding window
                current_window.append(trade)
                if len(current_window) >= WINDOW_SIZE:
                    windows.append(current_window)
                    current_window = []
        
        # Add remaining trades
        if current_window:
            windows.append(current_window)
        
        # If no date-based windows, use N-trade windows
        if not windows:
            for i in range(0, len(trades_list), WINDOW_SIZE):
                windows.append(trades_list[i:i + WINDOW_SIZE])
        
        # Compute PF per window
        cumulative_wins = []
        cumulative_losses = []
        
        for i, window in enumerate(windows, 1):
            wins = [t["pct"] for t in window if t["pct"] > 0]
            losses = [t["pct"] for t in window if t["pct"] < 0]
            
            window_pf = compute_pf(wins, losses)
            cumulative_wins.extend(wins)
            cumulative_losses.extend(losses)
            cumulative_pf = compute_pf(cumulative_wins, cumulative_losses)
            
            pf_str = "∞" if window_pf == float("inf") else f"{window_pf:.2f}" if window_pf else "—"
            cum_pf_str = "∞" if cumulative_pf == float("inf") else f"{cumulative_pf:.2f}" if cumulative_pf else "—"
            
            print(f"  window {i}: trades={len(window)}, exp_pf={pf_str}")
        
        # Cumulative
        cum_pf_str = "∞" if cumulative_pf == float("inf") else f"{cumulative_pf:.2f}" if cumulative_pf else "—"
        print(f"  cumulative: trades={len(trades_list)}, exp_pf={cum_pf_str}")
        print()


if __name__ == "__main__":
    main()
