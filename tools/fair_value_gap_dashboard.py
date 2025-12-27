#!/usr/bin/env python3
"""
Fair Value Gap Dashboard

Visualizes detected Fair Value Gaps and their fill statistics.
Shows market microstructure intelligence for gap analysis.

Observer-only: FVGs detected but not yet used for trading decisions.
"""

from __future__ import annotations
from pathlib import Path
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter
from typing import Dict, List, Any

from engine_alpha.reflect.fair_value_gaps import fvg_detector


def format_pct(value: float, decimals: int = 1) -> str:
    """Format percentage with decimals"""
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}%"


def format_price(value: float, decimals: int = 2) -> str:
    """Format price with appropriate decimals"""
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}"


def get_gap_status_color(status: str) -> str:
    """Get color indicator for gap status"""
    status_colors = {
        "active": "🔵",  # Active gaps
        "partially_filled": "🟡",  # Partially filled
        "filled": "🟢",  # Completely filled
        "expired": "🔴"  # Expired unfilled
    }
    return status_colors.get(status, "⚪")


def get_direction_icon(direction: str) -> str:
    """Get icon for gap direction"""
    return "🟢📈" if direction == "bullish" else "🔴📉"


def main() -> None:
    """Display Fair Value Gap dashboard"""
    print("=" * 80)
    print("🎯 FAIR VALUE GAP DASHBOARD")
    print("=" * 80)

    # Get FVG statistics for key symbols
    symbols = ["ADAUSDT", "ATOMUSDT", "BTCUSDT", "DOTUSDT", "ETHUSDT", "LINKUSDT", "SOLUSDT", "BNBUSDT"]

    all_stats = {}
    total_gaps = 0
    total_filled = 0

    for symbol in symbols:
        stats = fvg_detector.get_fvg_statistics(symbol, days_back=30)
        if stats.get("status") != "no_data":
            all_stats[symbol] = stats
            total_gaps += stats.get("total_gaps", 0)
            total_filled += stats.get("gaps_by_status", {}).get("filled", 0)

    if not all_stats:
        print("📊 No Fair Value Gap data available yet")
        print("   FVG detector will populate as price data is analyzed")
        print("   Observer-only: detecting gaps for meta-analysis")
        return

    print(f"📅 Analysis Period: Last 30 days")
    print(f"🔢 Total FVGs Detected: {total_gaps}")
    print(f"📊 Fill Rate: {format_pct(total_filled / total_gaps * 100) if total_gaps > 0 else 'N/A'}")
    print()

    # Overall market gap statistics
    print("🌍 MARKET FVG STATISTICS")
    print("-" * 35)

    # Aggregate statistics across all symbols
    all_gaps_data = []
    for stats in all_stats.values():
        all_gaps_data.extend([stats] * stats.get("total_gaps", 0))  # Weight by gap count

    if all_gaps_data:
        total_analyzed = sum(s.get("total_gaps", 0) for s in all_stats.values())
        total_filled_all = sum(s.get("gaps_by_status", {}).get("filled", 0) for s in all_stats.values())
        overall_fill_rate = total_filled_all / total_analyzed if total_analyzed > 0 else 0

        print(f"Symbols with FVGs: {len(all_stats)}/{len(symbols)}")
        print(f"Overall Fill Rate: {format_pct(overall_fill_rate * 100)}")
        print(f"Average Gaps per Symbol: {total_analyzed / len(all_stats):.1f}")
        print()

    # Individual symbol analysis
    print("📊 SYMBOL FVG ANALYSIS")
    print("-" * 35)

    # Sort symbols by gap count
    sorted_symbols = sorted(all_stats.items(),
                          key=lambda x: x[1].get("total_gaps", 0),
                          reverse=True)

    print("Symbol      Gaps   Fill Rate   Avg Size   Avg Impulse   Best Regime")
    print("---------- ------ ----------- ---------- ------------- -------------")

    for symbol, stats in sorted_symbols:
        gaps = stats.get("total_gaps", 0)
        fill_rate = stats.get("fill_rate", 0)
        avg_size = stats.get("avg_gap_size_pct", 0)
        avg_impulse = stats.get("avg_impulse_strength", 0)

        # Find regime with most gaps
        regime_dist = stats.get("regime_distribution", {})
        best_regime = max(regime_dist.items(), key=lambda x: x[1])[0] if regime_dist else "N/A"

        print(f"{symbol:<10} {gaps:>6} {format_pct(fill_rate * 100):>11} "
              f"{format_pct(avg_size):>8} {format_pct(avg_impulse * 100):>11} {best_regime:>11}")

    print()

    # Gap fill analysis
    print("🎯 FVG FILL ANALYSIS")
    print("-" * 30)

    fill_stats = defaultdict(int)
    fill_times = []

    for stats in all_stats.values():
        status_counts = stats.get("gaps_by_status", {})
        for status, count in status_counts.items():
            fill_stats[status] += count

    total_all_gaps = sum(fill_stats.values())

    print("Gap Status Distribution:")
    for status, count in fill_stats.items():
        pct = count / total_all_gaps * 100 if total_all_gaps > 0 else 0
        color = get_gap_status_color(status)
        print(f"  {color} {status.replace('_', ' ').title()}: {count} ({format_pct(pct)})")

    print()

    # Recent FVGs
    print("📈 RECENT FVGs")
    print("-" * 20)

    # Load recent FVGs from log
    recent_gaps = []
    if fvg_detector.gap_log_file.exists():
        with fvg_detector.gap_log_file.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    if not record.get("updated", False):  # Skip updates, show originals
                        gap_ts = datetime.fromisoformat(record["timestamp"])
                        if gap_ts >= datetime.now(timezone.utc) - timedelta(days=7):
                            recent_gaps.append(record)
                except:
                    continue

    # Sort by timestamp and show last 5
    recent_gaps.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    for gap in recent_gaps[:5]:
        ts = gap.get("timestamp", "")[:19]
        symbol = gap.get("symbol", "UNKNOWN")
        direction = gap.get("direction", "unknown")
        size_pct = gap.get("gap_size_pct", 0)
        impulse = gap.get("impulse_strength", 0)
        status = gap.get("status", "unknown")
        regime = gap.get("regime_at_creation", "unknown")

        dir_icon = get_direction_icon(direction)
        status_color = get_gap_status_color(status)

        print(f"{ts} {symbol:<8} {dir_icon} {format_pct(size_pct):>6} "
              f"💪{format_pct(impulse * 100):>5} {status_color} {regime[:8]:<8}")

    print()

    # FVG insights and recommendations
    print("💡 FVG MARKET INSIGHTS")
    print("-" * 30)

    insights = []

    # Fill rate analysis
    if total_gaps > 0:
        fill_rate = total_filled / total_gaps
        if fill_rate > 0.7:
            insights.append("🔥 High fill rate suggests strong mean reversion behavior")
        elif fill_rate < 0.3:
            insights.append("⚠️ Low fill rate indicates weak reversion - gaps may persist longer")

    # Regime analysis
    regime_gaps = defaultdict(int)
    for stats in all_stats.values():
        for regime, count in stats.get("regime_distribution", {}).items():
            regime_gaps[regime] += count

    if regime_gaps:
        top_regime = max(regime_gaps.items(), key=lambda x: x[1])
        insights.append(f"📊 Most FVGs occur in {top_regime[0]} regime ({top_regime[1]} gaps)")

    # Size analysis
    avg_sizes = [s.get("avg_gap_size_pct", 0) for s in all_stats.values() if s.get("avg_gap_size_pct", 0) > 0]
    if avg_sizes:
        avg_size = sum(avg_sizes) / len(avg_sizes)
        if avg_size > 1.0:
            insights.append("💥 Large average gap size indicates volatile dislocation events")
        elif avg_size < 0.3:
            insights.append("🎯 Small, precise gaps suggest structured market behavior")

    # Show insights
    for insight in insights[:4]:  # Limit to top 4
        print(insight)

    print()
    print("🎯 META-INTELLIGENCE INTEGRATION")
    print("-" * 40)
    print("FVGs feed into:")
    print("• Counterfactual Analysis: 'What if we traded gap fills?'")
    print("• Edge Half-Life: 'How long do gaps influence price?'")
    print("• Regime Uncertainty: 'Do gaps resolve differently by regime?'")
    print("• Inaction Scoring: 'Cost of not trading gap opportunities?'")
    print()
    print("🚀 Observer Phase: Detecting FVGs for intelligence gathering")
    print("   Next: Conditional usage for targets, filters, regime validation")


if __name__ == "__main__":
    main()
