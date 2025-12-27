#!/usr/bin/env python3
"""
Backtest Report Tool - Regime-based PF Analysis
Analyzes backtest results and computes PF per regime.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, Any, List


def load_trades(trades_path: Path) -> List[Dict[str, Any]]:
    """Load trades from JSONL file."""
    trades = []
    with trades_path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                trades.append(json.loads(line))
            except Exception:
                continue
    return trades


def regime_pf(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute PF statistics grouped by regime."""
    # Group closes by regime
    regime_closes = defaultdict(list)
    for t in trades:
        if t.get("type") == "close":
            regime = t.get("regime", "unknown")
            regime_closes[regime].append(t)

    stats = {}
    for regime, closes in regime_closes.items():
        wins = [c["pct"] for c in closes if c["pct"] > 0]
        losses = [c["pct"] for c in closes if c["pct"] < 0]
        pos_sum = sum(wins)
        neg_sum = abs(sum(losses))
        pf = math.inf if neg_sum == 0 and pos_sum > 0 else (pos_sum / neg_sum if neg_sum > 0 else 0.0)

        stats[regime] = {
            "closes": len(closes),
            "wins": len(wins),
            "losses": len(losses),
            "pos_sum": pos_sum,
            "neg_sum": -neg_sum,
            "pf": pf,
        }

    return stats


def risk_band_pf(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute PF statistics grouped by risk band."""
    band_closes = defaultdict(list)
    for t in trades:
        if t.get("type") == "close":
            band = t.get("risk_band", "unknown")
            band_closes[band].append(t)

    stats = {}
    for band, closes in band_closes.items():
        wins = [c["pct"] for c in closes if c["pct"] > 0]
        losses = [c["pct"] for c in closes if c["pct"] < 0]
        pos_sum = sum(wins)
        neg_sum = abs(sum(losses))
        pf = math.inf if neg_sum == 0 and pos_sum > 0 else (pos_sum / neg_sum if neg_sum > 0 else 0.0)

        stats[band] = {
            "closes": len(closes),
            "wins": len(wins),
            "losses": len(losses),
            "pos_sum": pos_sum,
            "neg_sum": -neg_sum,
            "pf": pf,
        }

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chloe Backtest Report - Regime-based PF Analysis"
    )
    parser.add_argument(
        "--run-dir",
        required=True,
        help="Path to backtest run directory",
    )
    parser.add_argument(
        "--by-band",
        action="store_true",
        help="Also show PF breakdown by risk band",
    )

    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    trades_path = run_dir / "trades.jsonl"
    summary_path = run_dir / "summary.json"

    if not trades_path.exists():
        print(f"❌ Error: No trades.jsonl found at {trades_path}")
        return

    # Load summary if available
    summary = {}
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text())
        except Exception:
            pass

    trades = load_trades(trades_path)
    regime_stats = regime_pf(trades)
    
    # Count scratch vs meaningful closes
    all_closes = [t for t in trades if t.get("type") == "close"]
    scratch_closes = [c for c in all_closes if c.get("is_scratch", False)]
    meaningful_closes = [c for c in all_closes if not c.get("is_scratch", False)]
    
    # Compute meaningful PF (TP/SL, |pct| >= 0.0005, not scratch)
    meaningful_tp_sl = [
        c for c in meaningful_closes
        if c.get("exit_reason") in ("tp", "sl") and abs(float(c.get("pct", 0.0))) >= 0.0005
    ]
    meaningful_wins = [c["pct"] for c in meaningful_tp_sl if c["pct"] > 0]
    meaningful_losses = [c["pct"] for c in meaningful_tp_sl if c["pct"] < 0]
    meaningful_pos_sum = sum(meaningful_wins)
    meaningful_neg_sum = abs(sum(meaningful_losses))
    meaningful_pf = (
        math.inf if meaningful_neg_sum == 0 and meaningful_pos_sum > 0
        else (meaningful_pos_sum / meaningful_neg_sum if meaningful_neg_sum > 0 else 0.0)
    )

    print("=" * 70)
    print(f"Backtest Report: {run_dir.name}")
    print("=" * 70)

    if summary:
        print(f"\n📊 Overall Summary:")
        print(f"   Symbol:      {summary.get('symbol', 'N/A')}")
        print(f"   Timeframe:   {summary.get('timeframe', 'N/A')}")
        print(f"   Period:      {summary.get('start', 'N/A')} to {summary.get('end', 'N/A')}")
        print(f"   Bars:        {summary.get('bars_processed', 'N/A')}")
        print(f"   Closes:      {summary.get('closes', 0)}")
        print(f"   Wins:        {summary.get('wins', 0)}")
        print(f"   Losses:      {summary.get('losses', 0)}")
        print(f"   PF:          {summary.get('pf', 0.0):.3f}")
        print(f"   Start Equity: ${summary.get('start_equity', 0):,.2f}")
        print(f"   End Equity:   ${summary.get('final_equity', 0):,.2f}")
        print(f"   Change:       {summary.get('change_pct', 0.0):+.2f}%")
    
    print(f"\n🔍 Trade Breakdown:")
    print(f"   Total closes:        {len(all_closes)}")
    print(f"   Scratch closes:      {len(scratch_closes)}")
    print(f"   Meaningful closes:   {len(meaningful_closes)}")
    print(f"\n📈 Meaningful PF (TP/SL, |pct| >= 0.0005, not scratch):")
    print(f"   Count:               {len(meaningful_tp_sl)}")
    print(f"   Wins:                {len(meaningful_wins)}")
    print(f"   Losses:              {len(meaningful_losses)}")
    print(f"   PF:                  {meaningful_pf:.3f}")

    print(f"\n📈 PF by Regime:")
    if not regime_stats:
        print("   No closes found with regime information.")
    else:
        # Sort by closes count (descending)
        sorted_regimes = sorted(regime_stats.items(), key=lambda x: x[1]["closes"], reverse=True)
        for regime, s in sorted_regimes:
            print(
                f"   [{regime:10s}] closes={s['closes']:4d} wins={s['wins']:3d} "
                f"losses={s['losses']:3d} pf={s['pf']:.3f} "
                f"pos_sum={s['pos_sum']:+.3f} neg_sum={s['neg_sum']:+.3f}"
            )

    if args.by_band:
        band_stats = risk_band_pf(trades)
        print(f"\n📊 PF by Risk Band:")
        if not band_stats:
            print("   No closes found with risk_band information.")
        else:
            sorted_bands = sorted(band_stats.items(), key=lambda x: x[1]["closes"], reverse=True)
            for band, s in sorted_bands:
                print(
                    f"   [{band:10s}] closes={s['closes']:4d} wins={s['wins']:3d} "
                    f"losses={s['losses']:3d} pf={s['pf']:.3f} "
                    f"pos_sum={s['pos_sum']:+.3f} neg_sum={s['neg_sum']:+.3f}"
                )

    print("=" * 70)


if __name__ == "__main__":
    main()




