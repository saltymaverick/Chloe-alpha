#!/usr/bin/env python3
"""
Promotion Sample Count Validator

Validates that all promotion components use the same exploration sample counting rules.

Checks:
- Exploration closes counted under canonical filter (7d/24h)
- Raw exploration closes total (7d/24h)
- Most common excluded exit_reasons per symbol
- Comparison between shadow_promotion_queue.json and promotion_advice.json
"""

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from engine_alpha.reflect.promotion_filters import (
    is_promo_sample_close,
    PROMO_EXCLUDE_EXIT_REASONS,
    get_promotion_filter_metadata,
)

TRADES_PATH = Path("reports/trades.jsonl")
SHADOW_QUEUE_PATH = Path("reports/gpt/shadow_promotion_queue.json")
PROMOTION_ADVICE_PATH = Path("reports/gpt/promotion_advice.json")


def load_json(path: Path) -> dict:
    """Load JSON file safely."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def count_exploration_closes():
    """Count exploration closes under canonical filter vs raw totals."""
    if not TRADES_PATH.exists():
        return {}, {}

    cutoff_7d = datetime.now(timezone.utc) - timedelta(days=7)
    cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)

    canonical_counts = defaultdict(lambda: {"7d": 0, "24h": 0})
    raw_counts = defaultdict(lambda: {"7d": 0, "24h": 0})
    excluded_reasons = defaultdict(Counter)

    with TRADES_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line.strip())
            except Exception:
                continue

            if e.get("type") != "close":
                continue

            ts_str = e.get("ts")
            if not ts_str:
                continue

            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except Exception:
                continue

            symbol = e.get("symbol", "UNKNOWN")
            trade_kind = (e.get("trade_kind") or "").lower()
            exit_reason = (e.get("exit_reason") or "").lower()

            if trade_kind != "exploration":
                continue

            # Raw counts (all exploration closes)
            if ts >= cutoff_7d:
                raw_counts[symbol]["7d"] += 1
            if ts >= cutoff_24h:
                raw_counts[symbol]["24h"] += 1

            # Canonical counts (promotion sample filter)
            if is_promo_sample_close(e, "exploration"):
                if ts >= cutoff_7d:
                    canonical_counts[symbol]["7d"] += 1
                if ts >= cutoff_24h:
                    canonical_counts[symbol]["24h"] += 1
            else:
                # Track excluded reasons
                if exit_reason in PROMO_EXCLUDE_EXIT_REASONS:
                    excluded_reasons[symbol][exit_reason] += 1

    return dict(canonical_counts), dict(raw_counts), dict(excluded_reasons)


def validate_consistency():
    """Validate that promotion components agree on counts."""
    shadow_data = load_json(SHADOW_QUEUE_PATH)
    advice_data = load_json(PROMOTION_ADVICE_PATH)

    print("=== PROMOTION SAMPLE COUNT VALIDATION ===\n")

    # Check filter metadata
    shadow_meta = shadow_data.get("promotion_sample_filter", {})
    advice_meta = advice_data.get("promotion_sample_filter", {})

    print("Filter Metadata:")
    print(f"  Shadow Queue: {shadow_meta.get('version', 'MISSING')}")
    print(f"  Promotion Advice: {advice_meta.get('version', 'MISSING')}")

    if shadow_meta.get("version") != "promo_filter_v1":
        print("  ❌ Shadow queue missing filter metadata")
    if advice_meta.get("version") != "promo_filter_v1":
        print("  ❌ Promotion advice missing filter metadata")

    # Count from trades
    canonical_counts, raw_counts, excluded_reasons = count_exploration_closes()

    print(f"\nCanonical Filter: Exclude {len(PROMO_EXCLUDE_EXIT_REASONS)} exit reasons")
    print(f"  {sorted(PROMO_EXCLUDE_EXIT_REASONS)}")

    # Show top symbols by exploration activity
    print("\n=== EXPLORATION ACTIVITY BY SYMBOL ===")
    symbols = set(canonical_counts.keys()) | set(raw_counts.keys())
    symbol_summary = []

    for sym in sorted(symbols):
        raw_7d = raw_counts.get(sym, {}).get("7d", 0)
        canonical_7d = canonical_counts.get(sym, {}).get("7d", 0)
        raw_24h = raw_counts.get(sym, {}).get("24h", 0)
        canonical_24h = canonical_counts.get(sym, {}).get("24h", 0)

        if raw_7d > 0:  # Only show symbols with activity
            excluded = excluded_reasons.get(sym, Counter())
            top_excluded = ", ".join(f"{r}({c})" for r, c in excluded.most_common(3))

            symbol_summary.append({
                "symbol": sym,
                "raw_7d": raw_7d,
                "canonical_7d": canonical_7d,
                "raw_24h": raw_24h,
                "canonical_24h": canonical_24h,
                "excluded_top": top_excluded or "none"
            })

    # Sort by activity
    symbol_summary.sort(key=lambda x: x["raw_7d"], reverse=True)

    print("Symbol      Raw 7d    Canon 7d    Raw 24h    Canon 24h    Top Excluded Reasons")
    print("-" * 80)
    for s in symbol_summary[:15]:  # Top 15 most active
        print("<8")

    if len(symbol_summary) > 15:
        print(f"... and {len(symbol_summary) - 15} more symbols")

    # Check shadow queue vs advice consistency for ETHUSDT
    print("\n=== ETHUSDT CONSISTENCY CHECK ===")
    eth_shadow = None
    if "candidates" in shadow_data:
        for cand in shadow_data["candidates"]:
            if cand.get("symbol") == "ETHUSDT":
                eth_shadow = cand
                break

    eth_advice = advice_data.get("symbols", {}).get("ETHUSDT", {})

    if eth_shadow:
        shadow_n = eth_shadow.get("n_expl_7d", 0)
        shadow_pf = eth_shadow.get("exploration_pf_7d", 0)
        print(f"Shadow Queue ETH: n={shadow_n}, pf={shadow_pf:.3f}")

    if eth_advice:
        advice_expl = eth_advice.get("exploration", {}).get("7d", {})
        advice_n = advice_expl.get("n_closes", 0)
        advice_pf = advice_expl.get("pf", 0)
        print(f"Promotion Advice ETH: n={advice_n}, pf={advice_pf}")

    # Check against our canonical count
    our_eth = canonical_counts.get("ETHUSDT", {})
    our_n_7d = our_eth.get("7d", 0)
    print(f"Canonical Count ETH 7d: n={our_n_7d}")

    # Validation
    issues = []
    if eth_shadow and our_n_7d != shadow_n:
        issues.append(f"Shadow queue ETH n ({shadow_n}) != canonical ({our_n_7d})")
    if eth_advice and our_n_7d != advice_n:
        issues.append(f"Promotion advice ETH n ({advice_n}) != canonical ({our_n_7d})")

    if issues:
        print("\n❌ CONSISTENCY ISSUES:")
        for issue in issues:
            print(f"  {issue}")
    else:
        print("\n✅ All components consistent with canonical filter")

    print(f"\nTotal symbols with exploration activity: {len(symbol_summary)}")
    total_raw_7d = sum(s["raw_7d"] for s in symbol_summary)
    total_canonical_7d = sum(s["canonical_7d"] for s in symbol_summary)
    print(f"Total exploration closes 7d: {total_raw_7d} raw, {total_canonical_7d} canonical")
    if total_raw_7d > 0:
        excluded_pct = (total_raw_7d - total_canonical_7d) / total_raw_7d * 100
        print(".1f")


if __name__ == "__main__":
    validate_consistency()
