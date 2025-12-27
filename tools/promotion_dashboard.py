#!/usr/bin/env python3
"""
Promotion Dashboard - Visualize Phase 5J Evolution

Shows progression toward promotion gates without changing promotion logic.
"""

import json
import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from engine_alpha.reflect.promotion_filters import is_promo_sample_close
from engine_alpha.reflect.promotion_gates import get_promotion_gate_spec


def compute_exploration_metrics():
    """Compute current exploration metrics for all symbols."""
    spec = get_promotion_gate_spec()
    trades_path = Path("reports/trades.jsonl")

    if not trades_path.exists():
        return {}

    cutoff_7d = datetime.now(timezone.utc) - timedelta(days=7)

    by_symbol = defaultdict(list)

    with trades_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line.strip())
                if e.get("type") != "close":
                    continue
                if (e.get("trade_kind") or "").lower() != "exploration":
                    continue
                if not is_promo_sample_close(e, lane="exploration"):
                    continue

                ts_str = e.get("ts")
                if not ts_str:
                    continue

                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts >= cutoff_7d:
                    pct = e.get("pct")
                    if pct is not None and math.isfinite(float(pct)):
                        by_symbol[e.get("symbol", "UNKNOWN")].append(float(pct))
            except Exception:
                continue

    # Compute metrics
    results = {}
    for symbol, returns in by_symbol.items():
        if not returns:
            continue

        # Basic stats
        n = len(returns)
        pf = _compute_pf(returns)
        win_rate = sum(1 for r in returns if r > 0) / n
        avg_return = sum(returns) / n
        max_dd = _compute_max_drawdown(returns)

        # Gate progress
        sample_progress = min(1.0, n / spec.min_exploration_closes_7d)
        pf_progress = min(1.0, pf / spec.min_exploration_pf) if pf > 0 else 0
        wr_progress = min(1.0, win_rate / spec.min_win_rate)

        overall_progress = (sample_progress + pf_progress + wr_progress) / 3

        results[symbol] = {
            "n_closes": n,
            "pf": pf,
            "win_rate": win_rate,
            "avg_return": avg_return,
            "max_drawdown": max_dd,
            "sample_progress": sample_progress,
            "pf_progress": pf_progress,
            "wr_progress": wr_progress,
            "overall_progress": overall_progress,
            "gates_met": {
                "sample": n >= spec.min_exploration_closes_7d,
                "pf": pf >= spec.min_exploration_pf,
                "win_rate": win_rate >= spec.min_win_rate,
            },
            "promotion_ready": all([
                n >= spec.min_exploration_closes_7d,
                pf >= spec.min_exploration_pf,
                win_rate >= spec.min_win_rate,
            ])
        }

    return dict(sorted(results.items(), key=lambda x: x[1]["overall_progress"], reverse=True))


def _compute_pf(returns):
    """Compute profit factor."""
    gp = sum(r for r in returns if r > 0)
    gl = -sum(r for r in returns if r < 0)
    if gp == 0 and gl == 0:
        return 1.0
    if gl == 0:
        return float("inf")
    return gp / gl


def _compute_max_drawdown(returns):
    """Compute max drawdown."""
    cum = 0.0
    peak = 0.0
    mdd = 0.0
    for r in returns:
        cum += r
        peak = max(peak, cum)
        dd = peak - cum
        mdd = max(mdd, dd)
    return mdd


def print_dashboard():
    """Print the promotion dashboard."""
    spec = get_promotion_gate_spec()
    metrics = compute_exploration_metrics()

    print("=" * 80)
    print("PHASE 5J PROMOTION DASHBOARD")
    print("=" * 80)
    print(f"Gate Spec: n≥{spec.min_exploration_closes_7d}, PF≥{spec.min_exploration_pf:.2f}, WR≥{spec.min_win_rate:.2f}")
    print(f"Updated: {datetime.now(timezone.utc).isoformat()}")
    print()

    if not metrics:
        print("No exploration activity found.")
        return

    print("<8")
    print("-" * 80)

    for symbol, m in metrics.items():
        status = "✅ READY" if m["promotion_ready"] else "⏳ BUILDING"

        pf_str = f"{m['pf']:.3f}" if math.isfinite(m['pf']) else "inf"
        wr_str = f"{m['win_rate']:.1%}"
        progress_str = f"{m['overall_progress']:.1%}"

        print("<8")

    print()
    print("LEGEND:")
    print("  ⏳ BUILDING = Accumulating samples toward promotion gates")
    print("  ✅ READY = Meets all promotion criteria")
    print("  Progress = Average completion of n/PF/WR gates (0-100%)")

    # Summary
    ready_count = sum(1 for m in metrics.values() if m["promotion_ready"])
    total_symbols = len(metrics)

    print(f"\nSUMMARY: {ready_count}/{total_symbols} symbols ready for promotion")
    print("Next milestone: First symbol reaches all three gates simultaneously")


if __name__ == "__main__":
    print_dashboard()
