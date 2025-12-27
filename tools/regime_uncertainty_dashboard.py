#!/usr/bin/env python3
"""
Regime Uncertainty Dashboard

Shows Chloe's confidence in regime classification to identify when she's
operating in uncertain market conditions. This enables future gating decisions.

Observer-only - tracks uncertainty without changing behavior.
"""

from __future__ import annotations
from pathlib import Path
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter
from typing import Dict, List, Any

from engine_alpha.reflect.regime_uncertainty import regime_uncertainty_tracker


def format_pct(value: float, decimals: int = 2) -> str:
    """Format percentage with decimals"""
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}"


def format_score(value: float, decimals: int = 3) -> str:
    """Format score 0-1 with decimals"""
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}"


def get_uncertainty_color(score: float) -> str:
    """Get color indicator for uncertainty level"""
    if score is None:
        return "⚪"
    elif score >= 0.8:
        return "🟢"  # Low uncertainty
    elif score >= 0.6:
        return "🟡"  # Moderate uncertainty
    elif score >= 0.4:
        return "🟠"  # High uncertainty
    else:
        return "🔴"  # Extreme uncertainty


def main() -> None:
    """Display regime uncertainty dashboard"""
    print("=" * 80)
    print("REGIME UNCERTAINTY DASHBOARD")
    print("=" * 80)

    # Get metrics for different timeframes
    metrics_60m = regime_uncertainty_tracker.get_uncertainty_metrics(lookback_minutes=60)
    metrics_24h = regime_uncertainty_tracker.get_uncertainty_metrics(lookback_minutes=1440)

    if not metrics_60m:
        print("📊 No regime uncertainty data available yet")
        print("   Uncertainty tracker will populate as decisions are made")
        return

    print(f"📅 Analysis Period: Last 60 minutes")
    print(f"🔢 Total Assessments: {metrics_60m.get('total_assessments', 0)}")
    print()

    # Current uncertainty level
    current_level = metrics_60m.get('current_uncertainty_level', 'UNKNOWN')
    print("🎯 CURRENT UNCERTAINTY LEVEL")
    print("-" * 30)

    level_colors = {
        "LOW_UNCERTAINTY": "🟢",
        "MODERATE_UNCERTAINTY": "🟡",
        "HIGH_UNCERTAINTY": "🟠",
        "EXTREME_UNCERTAINTY": "🔴"
    }

    color = level_colors.get(current_level, "⚪")
    print(f"{color} {current_level}")
    print()

    # Core uncertainty metrics
    print("📊 UNCERTAINTY METRICS (Last 60min)")
    print("-" * 40)

    agg = metrics_60m.get('aggregate_metrics', {})
    print(f"Average Confidence Score: {format_score(agg.get('avg_confidence'))}")
    print(f"Average Stability Score: {format_score(agg.get('avg_stability'))}")
    print(f"Average Transition Prob: {format_pct(agg.get('avg_transition_probability'))}")
    print(f"Average Entropy: {format_score(agg.get('avg_entropy'))}")
    print()

    # Regime-specific breakdown
    print("🌊 REGIME CONFIDENCE BREAKDOWN")
    print("-" * 35)

    regime_breakdown = metrics_60m.get('regime_breakdown', {})
    if regime_breakdown:
        print("Regime         Count   Avg Conf   Avg Stability   Avg Entropy")
        print("-------------- ------- ---------- -------------- -------------")

        for regime, stats in sorted(regime_breakdown.items()):
            count = stats['count']
            conf = stats['avg_confidence']
            stab = stats['avg_stability']
            ent = stats['avg_entropy']

            conf_color = get_uncertainty_color(conf)
            stab_color = get_uncertainty_color(stab)

            print(f"{regime.upper():<14} {count:>7} {conf_color}{format_score(conf):>8} "
                  f"{stab_color}{format_score(stab):>12} {format_score(ent):>11}")
    print()

    # Uncertainty trends (24h vs 1h)
    print("📈 UNCERTAINTY TRENDS (24h vs 1h)")
    print("-" * 35)

    if metrics_24h and metrics_24h.get('aggregate_metrics'):
        h1_agg = metrics_60m.get('aggregate_metrics', {})
        h24_agg = metrics_24h.get('aggregate_metrics', {})

        print("Metric               1h Avg    24h Avg   Change")
        print("------------------- ---------- ---------- --------")

        metrics_to_compare = [
            ('Confidence', 'avg_confidence'),
            ('Stability', 'avg_stability'),
            ('Transition Prob', 'avg_transition_probability'),
            ('Entropy', 'avg_entropy')
        ]

        for label, key in metrics_to_compare:
            h1_val = h1_agg.get(key)
            h24_val = h24_agg.get(key)

            if h1_val is not None and h24_val is not None:
                change = h1_val - h24_val
                change_str = f"{'+' if change >= 0 else ''}{change:.3f}"
                change_color = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
            else:
                change_str = "N/A"
                change_color = "⚪"

            print(f"{label:<19} {format_score(h1_val):>8} {format_score(h24_val):>8} "
                  f"{change_color}{change_str:>6}")
    print()

    # Recent uncertainty assessments
    print("📈 RECENT UNCERTAINTY ASSESSMENTS")
    print("-" * 40)

    # Read recent assessments from log file
    recent_assessments = []
    if regime_uncertainty_tracker.uncertainty_log_file.exists():
        with regime_uncertainty_tracker.uncertainty_log_file.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    recent_assessments.append(record)
                except:
                    continue

    # Sort by timestamp and show last 10
    recent_assessments.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    for assessment in recent_assessments[:10]:
        ts = assessment.get("timestamp", "")[:19]  # YYYY-MM-DDTHH:MM:SS
        regime = assessment.get("regime_label", "UNKNOWN")
        conf = assessment.get("confidence_score")
        stab = assessment.get("stability_score")
        trans = assessment.get("transition_probability")

        conf_color = get_uncertainty_color(conf)
        stab_color = get_uncertainty_color(stab)

        print(f"{ts} {regime.upper():<8} "
              f"{conf_color}Conf:{format_score(conf):>5} "
              f"{stab_color}Stab:{format_score(stab):>5} "
              f"Trans:{format_pct(trans):>5}")

    print()
    print("💡 INTERPRETATION GUIDE")
    print("-" * 40)
    print("🟢 LOW: High confidence, stable regime, low transition risk")
    print("🟡 MODERATE: Decent confidence, some regime stability")
    print("🟠 HIGH: Low confidence, unstable regime, high transition risk")
    print("🔴 EXTREME: Very uncertain, likely regime transition zone")
    print()
    print("Confidence: How sure we are about current regime classification")
    print("Stability: How consistent regime has been over time window")
    print("Transition Prob: Likelihood of regime change soon")
    print("Entropy: Information uncertainty in regime distribution")
    print()
    print("🎯 FUTURE GATING OPPORTUNITIES")
    print("-" * 40)
    print("• High uncertainty periods → reduce position sizes")
    print("• Low stability regimes → delay new entries")
    print("• High transition prob → tighten exit thresholds")
    print("• High entropy → increase diversification requirements")


if __name__ == "__main__":
    main()
