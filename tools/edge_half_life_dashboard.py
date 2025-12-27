#!/usr/bin/env python3
"""
Edge Half-Life Dashboard

Shows Chloe's understanding of how long trading edges remain valid.
Enables proactive edge rotation before decay destroys profitability.

Key insights:
- Which edges are strengthening vs decaying
- Optimal rotation timing
- Edge longevity patterns
- Meta-decisions about exploitation duration
"""

from __future__ import annotations
from pathlib import Path
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter
from typing import Dict, List, Any

from engine_alpha.reflect.edge_half_life import edge_half_life_tracker


def format_pct(value: float, decimals: int = 2) -> str:
    """Format percentage with decimals"""
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}"


def format_days(value: float) -> str:
    """Format days with appropriate precision"""
    if value is None:
        return "N/A"
    if value < 1:
        return f"{value*24:.1f}h"
    elif value < 30:
        return f"{value:.1f}d"
    else:
        return f"{value/30:.1f}mo"


def get_strength_color(strength: float) -> str:
    """Get color indicator for edge strength"""
    if strength is None:
        return "⚪"
    elif strength >= 0.8:
        return "🟢"  # Very strong
    elif strength >= 0.6:
        return "🟢"  # Strong
    elif strength >= 0.4:
        return "🟡"  # Moderate
    elif strength >= 0.2:
        return "🟠"  # Weak
    else:
        return "🔴"  # Very weak


def get_trend_indicator(trend: float) -> str:
    """Get trend indicator"""
    if trend > 0.01:
        return "📈 IMPROVING"
    elif trend < -0.01:
        return "📉 DECLINING"
    else:
        return "➡️ STABLE"


def main() -> None:
    """Display edge half-life dashboard"""
    print("=" * 80)
    print("EDGE HALF-LIFE DASHBOARD")
    print("=" * 80)

    # Get edge rotation signals for active symbols
    # For now, check a few key symbols
    active_symbols = ["ADAUSDT", "ATOMUSDT", "BTCUSDT", "DOTUSDT", "ETHUSDT", "LINKUSDT", "SOLUSDT", "BNBUSDT"]

    rotation_signals = edge_half_life_tracker.get_edge_rotation_signals(active_symbols)

    if not rotation_signals:
        print("📊 No edge half-life data available yet")
        print("   Edge tracker will populate as trades complete and analyses run")
        return

    print(f"📅 Analysis Period: Last 30 days")
    print(f"🔢 Symbols Analyzed: {len(rotation_signals)}")
    print()

    # Summary statistics
    signal_counts = Counter(sig["signal"] for sig in rotation_signals.values())
    print("🎯 EDGE ROTATION SUMMARY")
    print("-" * 30)
    print(f"Hold Position: {signal_counts.get('hold_position', 0)}")
    print(f"Weak Rotate: {signal_counts.get('weak_rotate', 0)}")
    print(f"Moderate Rotate: {signal_counts.get('moderate_rotate', 0)}")
    print(f"Strong Rotate: {signal_counts.get('strong_rotate', 0)}")
    print()

    # Individual symbol analysis
    print("📊 INDIVIDUAL EDGE ANALYSIS")
    print("-" * 50)
    print("Symbol   Strength   Half-Life   Trend         Signal         Urgency")
    print("-------- ---------- ----------- ------------- -------------- ----------")

    # Sort by strength descending
    sorted_symbols = sorted(rotation_signals.items(),
                          key=lambda x: x[1]["current_strength"],
                          reverse=True)

    for symbol, data in sorted_symbols:
        strength = data["current_strength"]
        half_life = data["days_until_half_life"]
        trend = data["trend_direction"]
        signal = data["signal"]
        urgency = data["urgency"]

        strength_icon = get_strength_color(strength)
        trend_icon = get_trend_indicator(0.01 if trend == "improving" else -0.01 if trend == "declining" else 0)

        signal_display = signal.replace("_", " ").title()

        print(f"{symbol:<8} {strength_icon}{format_pct(strength):>8} "
              f"{format_days(half_life):>9} {trend_icon:<11} "
              f"{signal_display:<12} {urgency.upper():<8}")

    print()

    # Edge longevity patterns
    print("⏱️  EDGE LONGEVITY PATTERNS")
    print("-" * 35)

    # Load historical data for pattern analysis
    longevity_stats = defaultdict(list)
    if edge_half_life_tracker.edge_history_file.exists():
        with edge_half_life_tracker.edge_history_file.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    symbol = record["symbol"]
                    half_life = record["edge_strength"]["half_life_days"]
                    strength = record["edge_strength"]["absolute_strength"]
                    longevity_stats[symbol].append((half_life, strength))
                except (json.JSONDecodeError, KeyError):
                    continue

    if longevity_stats:
        print("Average Edge Longevity by Symbol:")
        for symbol in sorted(longevity_stats.keys()):
            half_lives = [hl for hl, _ in longevity_stats[symbol]]
            if half_lives:
                avg_half_life = sum(half_lives) / len(half_lives)
                print(f"  {symbol}: {format_days(avg_half_life)} average half-life")
    else:
        print("No historical longevity data yet")
    print()

    # Rotation recommendations
    print("🎲 ROTATION RECOMMENDATIONS")
    print("-" * 35)

    urgent_rotates = [s for s, data in rotation_signals.items()
                     if data["urgency"] in ["immediate", "high"]]
    moderate_rotates = [s for s, data in rotation_signals.items()
                       if data["urgency"] == "medium"]

    if urgent_rotates:
        print(f"🚨 URGENT ROTATION NEEDED: {', '.join(urgent_rotates)}")
        print("   These edges are expired or rapidly decaying")

    if moderate_rotates:
        print(f"⚠️  MONITOR CLOSELY: {', '.join(moderate_rotates)}")
        print("   These edges may need rotation soon")

    hold_positions = [s for s, data in rotation_signals.items()
                     if data["signal"] == "hold_position"]
    if hold_positions:
        print(f"✅ CONTINUE EXPLOITING: {', '.join(hold_positions)}")
        print("   These edges remain strong and fresh")
    print()

    # Recent edge strength trends
    print("📈 RECENT EDGE STRENGTH TRENDS")
    print("-" * 40)

    # Get recent analyses (last 10 per symbol)
    recent_analyses = defaultdict(list)
    if edge_half_life_tracker.edge_history_file.exists():
        with edge_half_life_tracker.edge_history_file.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    symbol = record["symbol"]
                    recent_analyses[symbol].append(record)
                except (json.JSONDecodeError, KeyError):
                    continue

    # Show trends for top 3 symbols
    for symbol in list(recent_analyses.keys())[:3]:
        analyses = sorted(recent_analyses[symbol][-5:],  # Last 5 analyses
                         key=lambda x: x["timestamp"])

        if len(analyses) >= 2:
            strengths = [a["edge_strength"]["absolute_strength"] for a in analyses]
            half_lives = [a["edge_strength"]["half_life_days"] for a in analyses]

            strength_trend = "📈" if strengths[-1] > strengths[0] else "📉" if strengths[-1] < strengths[0] else "➡️"
            half_life_trend = "📈" if half_lives[-1] > half_lives[0] else "📉" if half_lives[-1] < half_lives[0] else "➡️"

            print(f"{symbol}: Strength {strength_trend} {format_pct(strengths[-1])} "
                  f"| Half-Life {half_life_trend} {format_days(half_lives[-1])}")

    print()
    print("💡 INTERPRETATION GUIDE")
    print("-" * 40)
    print("🟢 STRONG: Edge >0.6, continue exploiting")
    print("🟡 MODERATE: Edge 0.4-0.6, monitor closely")
    print("🟠 WEAK: Edge 0.2-0.4, reduce exposure")
    print("🔴 EXPIRED: Edge <0.2, rotate immediately")
    print()
    print("Half-Life: Days until edge strength decays by 50%")
    print("Trend: Improving=📈, Declining=📉, Stable=➡️")
    print("Rotation Signals: When to stop exploiting current edge")
    print()
    print("🎯 META-INTELLIGENCE VALUE")
    print("-" * 40)
    print("• Prevents over-exploitation of decaying edges")
    print("• Enables proactive edge rotation")
    print("• Quantifies opportunity cost of holding expired edges")
    print("• Optimizes capital allocation across fresh opportunities")


if __name__ == "__main__":
    main()
