#!/usr/bin/env python3
"""
Inaction Performance Dashboard

Shows Chloe's discipline and patience metrics. Quantifies the value of restraint
and measures the quality of "no trade" decisions.

Key insights:
- How well Chloe avoids bad trades
- The opportunity cost of her discipline
- Which barriers are most effective
- Overall patience score assessment
"""

from __future__ import annotations
from pathlib import Path
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter
from typing import Dict, List, Any

from engine_alpha.reflect.inaction_performance import inaction_performance_tracker


def format_pct(value: float, decimals: int = 1) -> str:
    """Format percentage with decimals"""
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}%"


def format_score(value: float, decimals: int = 2) -> str:
    """Format score 0-1 with decimals"""
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}"


def get_quality_color(score: float) -> str:
    """Get color indicator for inaction quality"""
    if score is None:
        return "⚪"
    elif score >= 0.8:
        return "🟢"  # Excellent
    elif score >= 0.6:
        return "🟢"  # Good
    elif score >= 0.4:
        return "🟡"  # Moderate
    elif score >= 0.2:
        return "🟠"  # Poor
    else:
        return "🔴"  # Very Poor


def get_patience_assessment(assessment: str) -> str:
    """Get formatted patience assessment"""
    assessment_map = {
        "masterful_patience": "🎯 MASTERFUL PATIENCE",
        "good_discipline": "✅ GOOD DISCIPLINE",
        "moderate_restraint": "🟡 MODERATE RESTRAINT",
        "overly_cautious": "🟠 OVERLY CAUTIOUS",
        "insufficient_data": "⚪ INSUFFICIENT DATA"
    }
    return assessment_map.get(assessment, "❓ UNKNOWN")


def main() -> None:
    """Display inaction performance dashboard"""
    print("=" * 80)
    print("INACTION PERFORMANCE DASHBOARD")
    print("=" * 80)

    # Get comprehensive inaction metrics
    metrics = inaction_performance_tracker.get_inaction_performance_metrics(lookback_hours=24)

    if metrics.get("status") == "no_data":
        print("📊 No inaction performance data available yet")
        print("   Inaction tracker will populate as trading decisions are blocked")
        print("   Need blocked trade attempts to measure discipline quality")
        return

    if metrics.get("status") == "insufficient_data":
        print("📊 Insufficient inaction data for analysis")
        print("   Need more blocked trading decisions to generate meaningful metrics")
        print("   Continue normal operation - data will accumulate over time")
        return

    print(f"📅 Analysis Period: Last {metrics['time_period_hours']} hours")
    print(f"🔢 Inaction Decisions Analyzed: {metrics['total_inaction_decisions']}")
    print()

    # Overall performance summary
    perf = metrics["performance_summary"]
    print("🎯 OVERALL INACTION PERFORMANCE")
    print("-" * 35)

    quality_color = get_quality_color(perf["avg_inaction_quality"])
    print(f"Average Inaction Quality: {quality_color} {format_score(perf['avg_inaction_quality'])}")

    print(f"Excellent Inactions: {perf['excellent_inactions']}")
    print(f"Good Inactions: {perf['good_inactions']}")
    print(f"Poor Inactions: {perf['poor_inactions']}")
    print()

    # Net discipline value
    net_value = perf["net_discipline_value"]
    if net_value > 0:
        value_color = "🟢"
        value_desc = "POSITIVE"
    elif net_value < 0:
        value_color = "🔴"
        value_desc = "NEGATIVE"
    else:
        value_color = "⚪"
        value_desc = "NEUTRAL"

    print(f"Net Discipline Value: {value_color} {format_pct(net_value)} ({value_desc})")
    print(f"Total Opportunity Cost: {format_pct(perf['total_opportunity_cost'])}")
    print()

    # Barrier analysis
    barrier_analysis = metrics["barrier_analysis"]
    if barrier_analysis:
        print("🚧 BARRIER EFFECTIVENESS ANALYSIS")
        print("-" * 35)

        # Sort barriers by average quality
        sorted_barriers = sorted(barrier_analysis.items(),
                               key=lambda x: x[1]["avg_quality"], reverse=True)

        print("Barrier Type          Count   Avg Quality   Excellent Rate")
        print("-------------------- ------- ------------- --------------")

        for barrier, stats in sorted_barriers:
            count = stats["count"]
            avg_quality = stats["avg_quality"]
            excellent_rate = stats["excellent_rate"]

            quality_color = get_quality_color(avg_quality)
            excellent_pct = format_pct(excellent_rate)

            barrier_display = barrier.replace("_", " ").title()
            print(f"{barrier_display:<20} {count:>7} {quality_color}{format_score(avg_quality):>11} {excellent_pct:>12}")

        print()

    # Market development analysis
    market_dev = metrics["market_development_breakdown"]
    if market_dev.get("success_rates_by_development"):
        print("🌊 MARKET DEVELOPMENT ANALYSIS")
        print("-" * 35)

        dev_success = market_dev["success_rates_by_development"]
        dev_counts = market_dev["development_counts"]

        print("Market Movement      Count   Avg Quality   Excellent Rate")
        print("-------------------- ------- ------------- --------------")

        for dev in ["strong_uptrend", "moderate_uptrend", "sideways", "moderate_downtrend", "strong_downtrend"]:
            if dev in dev_success:
                stats = dev_success[dev]
                count = dev_counts.get(dev, 0)
                avg_quality = stats["avg_quality"]
                excellent_rate = stats["excellent_rate"]

                quality_color = get_quality_color(avg_quality)
                excellent_pct = format_pct(excellent_rate)

                dev_display = dev.replace("_", " ").title()
                print(f"{dev_display:<20} {count:>7} {quality_color}{format_score(avg_quality):>11} {excellent_pct:>12}")

        print()

    # Patience assessment for key symbols
    print("🧘 PATIENCE SCORES BY SYMBOL")
    print("-" * 35)

    key_symbols = ["ADAUSDT", "ATOMUSDT", "BTCUSDT", "DOTUSDT", "ETHUSDT", "LINKUSDT", "SOLUSDT", "BNBUSDT"]
    patience_scores = []

    for symbol in key_symbols:
        patience = inaction_performance_tracker.get_patience_score(symbol)
        patience_scores.append((symbol, patience))

    # Sort by patience score
    patience_scores.sort(key=lambda x: x[1]["patience_score"], reverse=True)

    print("Symbol      Patience Score   Assessment          Confidence")
    print("---------- ---------------- -------------------- ----------")

    for symbol, patience in patience_scores:
        score = patience["patience_score"]
        assessment = get_patience_assessment(patience["assessment"])
        confidence = patience["confidence"].upper()

        score_color = get_quality_color(score)
        print(f"{symbol:<10} {score_color}{format_score(score):>14} {assessment:<18} {confidence:>8}")

    print()

    # Recommendations
    recommendations = metrics.get("recommendations", [])
    if recommendations:
        print("💡 INACTION PERFORMANCE RECOMMENDATIONS")
        print("-" * 45)

        for i, rec in enumerate(recommendations, 1):
            print(f"{i}. {rec}")

    print()

    # Recent inaction decisions
    print("📈 RECENT INACTION DECISIONS")
    print("-" * 35)

    # Read recent inaction outcomes
    recent_outcomes = []
    if inaction_performance_tracker.inaction_log_file.exists():
        with inaction_performance_tracker.inaction_log_file.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    if record.get("type") == "inaction_outcome":
                        recent_outcomes.append(record)
                except:
                    continue

    # Sort by decision timestamp and show last 5
    recent_outcomes.sort(key=lambda x: x.get("decision_timestamp", ""), reverse=True)
    for outcome in recent_outcomes[:5]:
        ts = outcome.get("decision_timestamp", "")[:19]
        symbol = outcome.get("symbol", "UNKNOWN")
        quality = outcome.get("inaction_quality_score", 0)
        counterfactual = outcome.get("counterfactual_return", 0)
        barrier = outcome.get("decision_context", {}).get("barrier_type", "unknown")

        quality_color = get_quality_color(quality)
        cf_display = format_pct(counterfactual)

        barrier_display = barrier.replace("_", " ").title()
        print(f"{ts} {symbol:<8} {quality_color}Q:{format_score(quality):>4} "
              f"CF:{cf_display:>7} {barrier_display}")

    print()
    print("💡 INTERPRETATION GUIDE")
    print("-" * 40)
    print("Quality Score: How good was the decision not to trade?")
    print("🟢 0.8+: Excellent (avoided major loss or unnecessary trade)")
    print("🟡 0.4-0.8: Moderate (unclear value)")
    print("🔴 <0.4: Poor (missed good opportunity)")
    print()
    print("Counterfactual (CF): What would have happened if traded")
    print("Positive CF = Missed gain, Negative CF = Avoided loss")
    print()
    print("Patience Score: Overall discipline quality")
    print("🎯 Masterful: Excellent balance of caution and opportunity")
    print("✅ Good: Strong discipline with reasonable opportunity capture")
    print("🟡 Moderate: Decent restraint but could improve")
    print("🟠 Overly Cautious: Too restrictive, missing opportunities")
    print()
    print("🎯 META-INTELLIGENCE VALUE")
    print("-" * 40)
    print("• Quantifies the value of patience and discipline")
    print("• Measures opportunity cost of restraint")
    print("• Identifies most effective blocking criteria")
    print("• Builds comprehensive performance models")
    print()
    print("Great traders are defined by what they DON'T do.")


if __name__ == "__main__":
    main()
