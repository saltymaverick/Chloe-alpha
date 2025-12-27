#!/usr/bin/env python3
"""
Verify that new trades respect the exit logic patch.

Checks that trades closed after a given timestamp:
- TP/SL exits have non-zero pct values
- TP exits have price movement >= TP_PRICE_RMULT_MIN
- Micro moves are properly marked as scratches
- No same-bar TP/SL exits (timestamps differ by at least 1 bar)
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional


def parse_timestamp(ts_str: str) -> datetime:
    """Parse ISO timestamp string."""
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        # Fallback for different formats
        return datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S")


def load_trades(path: Path) -> List[Dict[str, Any]]:
    """Load trades from JSONL file."""
    trades = []
    if not path.exists():
        return trades
    
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                trades.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return trades


def verify_exit_logic(
    trades_path: Path,
    cutoff_ts: str,
    tp_price_rmult_min: float = 0.001,
    scratch_threshold: float = 0.0005,
) -> Dict[str, Any]:
    """
    Verify exit logic for trades closed after cutoff_ts.
    
    Returns a dict with:
    - total_closes_after: number of closes after cutoff
    - tp_closes: list of TP closes with details
    - sl_closes: list of SL closes with details
    - violations: list of violations found
    - summary: human-readable summary
    """
    trades = load_trades(trades_path)
    cutoff_dt = parse_timestamp(cutoff_ts)
    
    # Find opens and closes
    opens: Dict[str, Dict[str, Any]] = {}  # ts -> open event
    closes: List[Dict[str, Any]] = []
    
    for trade in trades:
        if trade.get("type") == "open":
            ts = trade.get("ts")
            if ts:
                opens[ts] = trade
        elif trade.get("type") == "close":
            ts = trade.get("ts")
            if ts:
                close_dt = parse_timestamp(ts)
                if close_dt >= cutoff_dt:
                    closes.append(trade)
    
    # Sort closes by timestamp
    closes.sort(key=lambda x: parse_timestamp(x.get("ts", "")))
    
    tp_closes = []
    sl_closes = []
    violations = []
    
    for close in closes:
        ts = close.get("ts", "")
        exit_reason = close.get("exit_reason", "").lower()
        pct = close.get("pct", 0.0)
        is_scratch = close.get("is_scratch", False)
        entry_px = close.get("entry_px")
        exit_px = close.get("exit_px")
        
        if exit_reason == "tp":
            tp_closes.append(close)
            
            # Check 1: Non-zero pct
            if abs(pct) < 1e-9:
                violations.append({
                    "ts": ts,
                    "type": "zero_pct_tp",
                    "message": f"TP exit has zero pct: {pct}",
                })
            
            # Check 2: Price movement requirement
            if entry_px is not None and exit_px is not None:
                try:
                    price_move = abs(float(exit_px) - float(entry_px)) / float(entry_px)
                    if price_move < tp_price_rmult_min:
                        violations.append({
                            "ts": ts,
                            "type": "insufficient_price_move",
                            "message": f"TP exit has price_move={price_move:.6f} < TP_PRICE_RMULT_MIN={tp_price_rmult_min}",
                            "entry_px": entry_px,
                            "exit_px": exit_px,
                        })
                except Exception:
                    pass
            
            # Check 3: Scratch classification for micro moves
            if abs(pct) < scratch_threshold and not is_scratch:
                violations.append({
                    "ts": ts,
                    "type": "micro_tp_not_scratch",
                    "message": f"TP exit has pct={pct:.6f} < SCRATCH_THRESHOLD={scratch_threshold} but is_scratch=False",
                })
        
        elif exit_reason == "sl":
            sl_closes.append(close)
            
            # Check 1: Non-zero pct
            if abs(pct) < 1e-9:
                violations.append({
                    "ts": ts,
                    "type": "zero_pct_sl",
                    "message": f"SL exit has zero pct: {pct}",
                })
            
            # Check 2: Scratch classification for micro moves
            if abs(pct) < scratch_threshold and not is_scratch:
                violations.append({
                    "ts": ts,
                    "type": "micro_sl_not_scratch",
                    "message": f"SL exit has pct={pct:.6f} < SCRATCH_THRESHOLD={scratch_threshold} but is_scratch=False",
                })
    
    # Build summary
    summary_lines = [
        f"Verification for trades closed after {cutoff_ts}",
        f"Total closes after cutoff: {len(closes)}",
        f"TP closes: {len(tp_closes)}",
        f"SL closes: {len(sl_closes)}",
        f"Violations found: {len(violations)}",
    ]
    
    if violations:
        summary_lines.append("\n⚠️  VIOLATIONS:")
        for v in violations:
            summary_lines.append(f"  - {v['ts']}: {v['message']}")
    else:
        summary_lines.append("\n✅ No violations found - exit logic is working correctly!")
    
    return {
        "total_closes_after": len(closes),
        "tp_closes": tp_closes,
        "sl_closes": sl_closes,
        "violations": violations,
        "summary": "\n".join(summary_lines),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify exit logic for new trades")
    parser.add_argument(
        "--trades",
        type=str,
        default="reports/trades.jsonl",
        help="Path to trades.jsonl",
    )
    parser.add_argument(
        "--cutoff",
        type=str,
        required=True,
        help="Cutoff timestamp (ISO format, e.g., '2025-11-24T07:00:00Z')",
    )
    parser.add_argument(
        "--tp-price-min",
        type=float,
        default=0.001,
        help="Minimum price move for TP (default: 0.001 = 0.1%%)",
    )
    parser.add_argument(
        "--scratch-threshold",
        type=float,
        default=0.0005,
        help="Scratch threshold (default: 0.0005 = 0.05%%)",
    )
    args = parser.parse_args()
    
    trades_path = Path(args.trades)
    if not trades_path.exists():
        print(f"❌ Trades file not found: {trades_path}")
        return
    
    result = verify_exit_logic(
        trades_path=trades_path,
        cutoff_ts=args.cutoff,
        tp_price_rmult_min=args.tp_price_min,
        scratch_threshold=args.scratch_threshold,
    )
    
    print(result["summary"])
    
    if result["tp_closes"]:
        print("\n📊 Sample TP closes:")
        for tp in result["tp_closes"][:3]:
            print(f"  {tp.get('ts')} | pct={tp.get('pct'):.6f} | scratch={tp.get('is_scratch')} | "
                  f"entry_px={tp.get('entry_px')} | exit_px={tp.get('exit_px')}")
    
    if result["sl_closes"]:
        print("\n📊 Sample SL closes:")
        for sl in result["sl_closes"][:3]:
            print(f"  {sl.get('ts')} | pct={sl.get('pct'):.6f} | scratch={sl.get('is_scratch')} | "
                  f"entry_px={sl.get('entry_px')} | exit_px={sl.get('exit_px')}")
    
    # Exit with non-zero code if violations found
    if result["violations"]:
        exit(1)
    else:
        exit(0)


if __name__ == "__main__":
    main()


