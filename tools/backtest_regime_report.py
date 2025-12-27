#!/usr/bin/env python3
"""
Regime Lab Report Tool
Generates detailed reports for regime-specific backtest runs.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Dict, Any, List, Optional


def load_trades(trades_path: Path) -> List[Dict[str, Any]]:
    """Load all trades from trades.jsonl."""
    trades = []
    if not trades_path.exists():
        return trades
    
    with trades_path.open("r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                trades.append(json.loads(line))
            except Exception:
                continue
    
    return trades


def compute_regime_report(trades_path: Path, summary_path: Path) -> Dict[str, Any]:
    """Compute detailed regime-specific report."""
    trades = load_trades(trades_path)
    closes = [t for t in trades if t.get("type") == "close"]
    
    # Load summary for equity info
    summary = {}
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text())
        except Exception:
            pass
    
    if not closes:
        return {
            "closes": 0,
            "wins": 0,
            "losses": 0,
            "pf": 0.0,
            "pos_sum": 0.0,
            "neg_sum": 0.0,
            "exit_reasons": {},
            "avg_bars_open": 0.0,
            "first_trade_ts": None,
            "last_trade_ts": None,
            "start_equity": summary.get("start_equity", 0.0),
            "final_equity": summary.get("final_equity", 0.0),
            "change_pct": summary.get("change_pct", 0.0),
        }
    
    # Basic stats
    wins = [c for c in closes if c.get("pct", 0) > 0]
    losses = [c for c in closes if c.get("pct", 0) < 0]
    pos_sum = sum(c.get("pct", 0) for c in wins)
    neg_sum = abs(sum(c.get("pct", 0) for c in losses))
    pf = pos_sum / neg_sum if neg_sum > 0 else (float("inf") if pos_sum > 0 else 0.0)
    
    # Exit reason counts
    exit_reasons = Counter(c.get("exit_reason", "unknown") for c in closes)
    
    # Average bars_open
    bars_open_list = [c.get("bars_open", 0) for c in closes if c.get("bars_open") is not None]
    avg_bars_open = sum(bars_open_list) / len(bars_open_list) if bars_open_list else 0.0
    
    # First and last trade timestamps
    timestamps = sorted([c.get("ts") for c in closes if c.get("ts")])
    first_ts = timestamps[0] if timestamps else None
    last_ts = timestamps[-1] if timestamps else None
    
    return {
        "closes": len(closes),
        "wins": len(wins),
        "losses": len(losses),
        "pf": pf,
        "pos_sum": pos_sum,
        "neg_sum": -neg_sum,
        "exit_reasons": dict(exit_reasons),
        "avg_bars_open": avg_bars_open,
        "first_trade_ts": first_ts,
        "last_trade_ts": last_ts,
        "start_equity": summary.get("start_equity", 0.0),
        "final_equity": summary.get("final_equity", 0.0),
        "change_pct": summary.get("change_pct", 0.0),
    }


def print_report(report: Dict[str, Any], meta: Dict[str, Any]):
    """Print formatted report."""
    regime = meta.get("regime", "unknown")
    symbol = meta.get("symbol", "UNKNOWN")
    timeframe = meta.get("timeframe", "1h")
    start = meta.get("start", "?")
    end = meta.get("end", "?")
    
    print("=" * 70)
    print(f"Regime Lab Report: {symbol} {regime} ({timeframe})")
    print("=" * 70)
    print(f"Period: {start} to {end}")
    print()
    
    print("📊 Performance Summary:")
    print(f"   Closes:        {report['closes']}")
    print(f"   Wins:          {report['wins']}")
    print(f"   Losses:        {report['losses']}")
    print(f"   PF:            {report['pf']:.3f}")
    print(f"   Positive sum:  +{report['pos_sum']:.6f}")
    print(f"   Negative sum:  {report['neg_sum']:.6f}")
    print()
    
    print("💰 Equity:")
    print(f"   Start:         ${report['start_equity']:,.2f}")
    print(f"   End:           ${report['final_equity']:,.2f}")
    print(f"   Change:        {report['change_pct']:+.2f}%")
    print()
    
    if report['exit_reasons']:
        print("🚪 Exit Reasons:")
        for reason, count in sorted(report['exit_reasons'].items(), key=lambda x: -x[1]):
            print(f"   {reason:12s}: {count:4d}")
        print()
    
    print("⏱️  Trade Duration:")
    print(f"   Avg bars open: {report['avg_bars_open']:.1f}")
    print()
    
    if report['first_trade_ts']:
        print("📅 Trade Timeline:")
        print(f"   First trade:   {report['first_trade_ts']}")
        print(f"   Last trade:    {report['last_trade_ts']}")
        print()
    
    print("=" * 70)


def main() -> None:
    """Main report entry point."""
    parser = argparse.ArgumentParser(
        description="Chloe Regime Lab Report - Generate detailed reports"
    )
    parser.add_argument(
        "--run-dir",
        type=str,
        required=True,
        help="Path to backtest run directory",
    )
    
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    
    if not run_dir.exists():
        print(f"❌ Error: Run directory not found: {run_dir}")
        return
    
    trades_path = run_dir / "trades.jsonl"
    summary_path = run_dir / "summary.json"
    meta_path = run_dir / "meta.json"
    
    # Load meta
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            pass
    
    # Compute report
    report = compute_regime_report(trades_path, summary_path)
    
    # Print report
    print_report(report, meta)


if __name__ == "__main__":
    main()

