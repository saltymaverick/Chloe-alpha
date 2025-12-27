#!/usr/bin/env python3
"""
PF Doctor Filtered - PF summary for meaningful trades only.

Filters trades by:
- Minimum pct threshold (default: 0.0005 = 0.05%)
- Optional exit_reason filter
- Only includes "close" events

Provides PF breakdown by regime if available.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from engine_alpha.core.paths import REPORTS


def _load_trades(path: Path) -> List[Dict[str, Any]]:
    """Load trades from JSONL file."""
    if not path.exists():
        return []
    trades: List[Dict[str, Any]] = []
    for raw in path.read_text().splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        trades.append(obj)
    return trades


def _filter_meaningful(
    trades: List[Dict[str, Any]],
    threshold: float,
    allowed_reasons: Optional[Set[str]] = None,
    ignore_scratch: bool = True,
) -> List[Dict[str, Any]]:
    """
    Filter to meaningful closes based on threshold, exit_reason, and scratch flag.
    
    Args:
        trades: List of trade events
        threshold: Minimum |pct| threshold
        allowed_reasons: Optional set of allowed exit_reasons
        ignore_scratch: If True, exclude trades with is_scratch=True
    """
    meaningful: List[Dict[str, Any]] = []
    for trade in trades:
        # Only process closes
        event_type = str(trade.get("type") or "").lower()
        if event_type != "close":
            continue

        # Phase 1: Filter out scratch trades if ignore_scratch=True
        if ignore_scratch and trade.get("is_scratch", False):
            continue

        # Check pct exists and is numeric
        try:
            pct = float(trade.get("pct", 0.0))
        except (ValueError, TypeError):
            continue

        # Filter by threshold
        if abs(pct) < threshold:
            continue

        # Filter by exit_reason if provided
        if allowed_reasons is not None:
            exit_reason = trade.get("exit_reason", "")
            if exit_reason not in allowed_reasons:
                continue

        meaningful.append(trade)
    return meaningful


def _compute_metrics(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute PF metrics from filtered trades."""
    wins = 0
    losses = 0
    pos_sum = 0.0
    neg_sum = 0.0

    for trade in trades:
        try:
            pct = float(trade.get("pct", 0.0))
        except (ValueError, TypeError):
            continue

        if pct > 0:
            wins += 1
            pos_sum += pct
        elif pct < 0:
            losses += 1
            neg_sum += abs(pct)

    if neg_sum > 0:
        pf = pos_sum / neg_sum
    elif pos_sum > 0:
        pf = float("inf")
    else:
        pf = 0.0

    return {
        "wins": wins,
        "losses": losses,
        "pos_sum": pos_sum,
        "neg_sum": neg_sum,
        "pf": pf,
    }


def _compute_regime_stats(trades: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Group trades by regime and compute PF per regime."""
    regime_trades: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for trade in trades:
        regime = trade.get("regime", "unknown")
        regime_trades[regime].append(trade)

    regime_stats: Dict[str, Dict[str, Any]] = {}
    for regime, regime_list in regime_trades.items():
        metrics = _compute_metrics(regime_list)
        regime_stats[regime] = {
            "closes": len(regime_list),
            **metrics,
        }

    return regime_stats


def _format_pf(pf: float) -> str:
    """Format PF value for display."""
    if math.isinf(pf):
        return "inf"
    return f"{pf:.3f}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PF Doctor Filtered - PF summary for meaningful trades only"
    )
    parser.add_argument(
        "--run-dir",
        type=str,
        default=None,
        help="Backtest run directory (uses <run-dir>/trades.jsonl). Default: reports/trades.jsonl",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.0005,
        help="Minimum absolute pct threshold for meaningful trades (default: 0.0005 = 0.05%%)",
    )
    parser.add_argument(
        "--reasons",
        type=str,
        default=None,
        help="Comma-separated list of allowed exit_reasons (e.g., 'tp,sl'). Default: all reasons",
    )
    parser.add_argument(
        "--include-scratch",
        action="store_true",
        help="Include scratch trades (default: exclude them)",
    )

    args = parser.parse_args()

    # Determine trades file path
    if args.run_dir:
        run_dir = Path(args.run_dir)
        if not run_dir.is_absolute():
            run_dir = Path.cwd() / run_dir
        trades_path = run_dir / "trades.jsonl"
    else:
        trades_path = REPORTS / "trades.jsonl"

    # Check if file exists
    if not trades_path.exists():
        print(f"❌ Error: trades.jsonl not found at {trades_path}")
        return 1

    # Print source header
    print("=" * 80)
    print("Filtered PF Doctor")
    print("=" * 80)
    if args.run_dir:
        print(f"Source (backtest): {trades_path}")
    else:
        print(f"Source (live): {trades_path}")
    print()

    # Parse exit_reason filter
    allowed_reasons: Optional[Set[str]] = None
    if args.reasons:
        allowed_reasons = {r.strip() for r in args.reasons.split(",") if r.strip()}

    # Load and filter trades
    all_trades = _load_trades(trades_path)
    meaningful = _filter_meaningful(
        all_trades, 
        args.threshold, 
        allowed_reasons,
        ignore_scratch=not args.include_scratch,  # Phase 1: respect is_scratch flag
    )

    # Compute overall metrics
    metrics = _compute_metrics(meaningful)

    # Compute regime stats
    regime_stats = _compute_regime_stats(meaningful)

    # Print summary
    print(f"Threshold: {args.threshold} (|pct| >= {args.threshold})")
    if allowed_reasons:
        reasons_str = ", ".join(sorted(allowed_reasons))
        print(f"Exit reasons filter: {reasons_str}")
    else:
        print("Exit reasons filter: all")
    print()

    if len(meaningful) == 0:
        print(
            f"Meaningful closes: 0 (no trades with |pct| >= {args.threshold}"
            + (f" and exit_reason in [{', '.join(sorted(allowed_reasons))}]" if allowed_reasons else "")
            + ")"
        )
        return 0

    print(f"Meaningful closes: {len(meaningful)}")
    print(f"Wins / Losses: {metrics['wins']} / {metrics['losses']}")
    print(f"Positive pct sum: {metrics['pos_sum']:.6f}")
    print(f"Negative pct sum: {metrics['neg_sum']:.6f}")
    pf_str = _format_pf(metrics["pf"])
    print(f"PF (meaningful only): {pf_str}")
    print()

    # Print regime breakdown
    if regime_stats:
        print("PF by Regime (meaningful only):")
        # Sort regimes for consistent output
        sorted_regimes = sorted(regime_stats.keys())
        for regime in sorted_regimes:
            stats = regime_stats[regime]
            regime_padded = f"[{regime:10s}]"
            print(
                f"  {regime_padded} closes={stats['closes']:4d} "
                f"wins={stats['wins']:3d} losses={stats['losses']:3d} "
                f"pf={_format_pf(stats['pf']):>6s} "
                f"pos_sum={stats['pos_sum']:+.6f} neg_sum={stats['neg_sum']:+.6f}"
            )
        print()

    # Print last 5 meaningful trades
    print("Last 5 meaningful trades:")
    for trade in meaningful[-5:]:
        print(f"  {json.dumps(trade)}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())



