#!/usr/bin/env python3
"""
Build compact trade outcomes from reports/trades.jsonl.

Extracts open/close pairs and writes a compact JSONL file for research.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Any, Optional, List


def load_trades(input_path: Path) -> List[Dict[str, Any]]:
    """Load all trade events from JSONL file."""
    trades = []
    if not input_path.exists():
        return trades
    
    with input_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                trades.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    
    return trades


def build_outcomes(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Pair open/close events and build compact outcome records.
    
    Returns list of outcome dicts with:
    - open_ts, close_ts
    - symbol, timeframe
    - regime, dir, entry_px, exit_px, pct
    - is_scratch, exit_reason, entry_conf, risk_band
    """
    outcomes = []
    open_trades: Dict[str, Dict[str, Any]] = {}  # key: (symbol, timeframe, open_ts) -> open_event
    
    for event in trades:
        event_type = event.get("type")
        if not event_type:
            continue
        
        symbol = event.get("symbol", "ETHUSDT")
        timeframe = event.get("timeframe", "1h")
        ts = event.get("ts")
        
        if event_type == "open":
            # Store open event
            key = f"{symbol}:{timeframe}:{ts}"
            open_trades[key] = event
        
        elif event_type == "close":
            # Find matching open event
            # Try to match by looking for most recent open with same symbol/timeframe
            matching_key = None
            matching_open = None
            
            for key, open_event in open_trades.items():
                if (open_event.get("symbol") == symbol and 
                    open_event.get("timeframe") == timeframe):
                    # Use the most recent open before this close
                    if matching_open is None or open_event.get("ts", "") < ts:
                        matching_key = key
                        matching_open = open_event
            
            if matching_open:
                # Build outcome record
                outcome = {
                    "open_ts": matching_open.get("ts"),
                    "close_ts": ts,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "regime": event.get("regime", matching_open.get("regime", "unknown")),
                    "dir": matching_open.get("dir", 0),
                    "entry_px": matching_open.get("entry_px", matching_open.get("price", 0.0)),
                    "exit_px": event.get("exit_px", event.get("price", 0.0)),
                    "pct": event.get("pct", 0.0),  # Already fractional return
                    "is_scratch": event.get("is_scratch", False),
                    "exit_reason": event.get("exit_reason", "unknown"),
                    "entry_conf": matching_open.get("conf", matching_open.get("entry_conf", 0.0)),
                    "risk_band": event.get("risk_band", matching_open.get("risk_band", "A")),
                }
                outcomes.append(outcome)
                
                # Remove matched open
                del open_trades[matching_key]
    
    return outcomes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build compact trade outcomes from reports/trades.jsonl"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("reports/trades.jsonl"),
        help="Input trades.jsonl file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/live_learning/trades_compact.jsonl"),
        help="Output compact outcomes JSONL file",
    )
    args = parser.parse_args()
    
    if not args.input.exists():
        print(f"⚠️  Input file not found: {args.input}")
        print("   (This is OK if no trades have been made yet)")
        return
    
    print(f"📖 Loading trades from: {args.input}")
    trades = load_trades(args.input)
    print(f"   Loaded {len(trades)} trade events")
    
    print("🔨 Building outcomes...")
    outcomes = build_outcomes(trades)
    print(f"   Built {len(outcomes)} outcome records")
    
    # Ensure output directory exists
    args.output.parent.mkdir(parents=True, exist_ok=True)
    
    # Write outcomes
    with args.output.open("w") as f:
        for outcome in outcomes:
            f.write(json.dumps(outcome) + "\n")
    
    print(f"✅ Wrote outcomes to: {args.output}")


if __name__ == "__main__":
    main()


