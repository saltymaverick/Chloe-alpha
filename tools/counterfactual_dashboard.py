#!/usr/bin/env python3
"""
Counterfactual Intelligence Dashboard

Shows Chloe's meta-intelligence metrics:
- Opportunity cost analysis
- Edge validation vs null behavior
- Confidence calibration
- Regime-specific counterfactuals

This reveals whether Chloe is truly adding value beyond market participation.
"""

from __future__ import annotations
from pathlib import Path
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter
from typing import Dict, List, Any

from engine_alpha.reflect.counterfactual_ledger import counterfactual_ledger


def format_pct(value: float, decimals: int = 2) -> str:
    """Format percentage with sign and decimals"""
    if value is None:
        return "N/A"
    return f"{value:+.{decimals}f}%"


def format_ratio(value: float, decimals: int = 3) -> str:
    """Format ratio with decimals"""
    if value is None or not (isinstance(value, (int, float)) and abs(value) < float('inf')):
        return "N/A"
    return f"{value:.{decimals}f}"


def main() -> None:
    """Display counterfactual intelligence dashboard"""
    print("=" * 80)
    print("COUNTERFACTUAL INTELLIGENCE DASHBOARD")
    print("=" * 80)

    # Get metrics for different timeframes
    metrics_7d = counterfactual_ledger.get_counterfactual_metrics(lookback_days=7)
    metrics_24h = counterfactual_ledger.get_counterfactual_metrics(lookback_days=1)

    if not metrics_7d:
        print("📊 No counterfactual data available yet")
        print("   Counterfactual ledger will populate as trades complete")
        return

    print(f"📅 Analysis Period: Last 7 days")
    print(f"🔢 Total Decisions Analyzed: {metrics_7d.get('total_decisions', 0)}")
    print()

    # Core opportunity cost metrics
    print("🎯 OPPORTUNITY COST ANALYSIS")
    print("-" * 40)

    avg_cost = metrics_7d.get('avg_opportunity_cost')
    beneficial_rate = metrics_7d.get('beneficial_trade_rate', 0)

    print(f"Average Opportunity Cost: {format_pct(avg_cost)}")
    print(f"Beneficial Trade Rate: {beneficial_rate:.1%}")
    print(f"Total Opportunity Gained: {format_pct(metrics_7d.get('total_opportunity_gain'))}")
    print(f"Total Opportunity Lost: {format_pct(metrics_7d.get('total_opportunity_loss'))}")
    print()

    # Edge validation vs null behavior
    print("⚖️  EDGE VALIDATION (vs Null Behavior)")
    print("-" * 40)

    actual_pf = metrics_7d.get('counterfactual_pf')
    null_pf = metrics_7d.get('null_pf')

    print(f"Trading Performance (PF): {format_ratio(actual_pf)}")
    print(f"Null Behavior (PF): {format_ratio(null_pf)}")

    if actual_pf and null_pf:
        edge_ratio = actual_pf / null_pf if null_pf != 0 else float('inf')
        print(f"Edge Multiplier: {format_ratio(edge_ratio)}x")
        if edge_ratio > 1:
            print("✅ Trading adds value beyond market participation")
        else:
            print("❌ Trading destroys value vs holding cash")
    print()

    # Confidence calibration
    print("🎚️  CONFIDENCE CALIBRATION")
    print("-" * 40)

    conf_quartiles = metrics_7d.get('by_confidence_quartile', {})
    if conf_quartiles:
        print("Confidence Quartile Performance:")
        for quartile in ['Q4_highest', 'Q3', 'Q2', 'Q1_lowest']:
            if quartile in conf_quartiles:
                data = conf_quartiles[quartile]
                print(f"  {quartile}: {data['count']} trades, "
                      f"avg_conf={data['avg_confidence']:.2f}, "
                      f"avg_cost={format_pct(data['avg_opportunity_cost'])}, "
                      f"beneficial={data['beneficial_rate']:.1%}")
    print()

    # Regime-specific counterfactuals
    print("🌊 REGIME-SPECIFIC ANALYSIS")
    print("-" * 40)

    regime_data = metrics_7d.get('by_regime', {})
    if regime_data:
        print("Performance by Market Regime:")
        for regime, data in regime_data.items():
            print(f"  {regime.upper()}: {data['count']} trades, "
                  f"avg_cost={format_pct(data['avg_opportunity_cost'])}, "
                  f"beneficial={data['beneficial_rate']:.1%}")
    print()

    # Recent counterfactual outcomes
    print("📈 RECENT COUNTERFACTUAL OUTCOMES")
    print("-" * 40)

    # Read recent outcomes from ledger file
    recent_outcomes = []
    if counterfactual_ledger.ledger_file.exists():
        with counterfactual_ledger.ledger_file.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    if record.get("type") == "outcome":
                        recent_outcomes.append(record)
                except:
                    continue

    # Sort by decision_ts and show last 10
    recent_outcomes.sort(key=lambda x: x.get("decision_ts", ""), reverse=True)
    for outcome in recent_outcomes[:10]:
        ts = outcome.get("decision_ts", "")[:19]  # YYYY-MM-DDTHH:MM:SS
        symbol = outcome.get("symbol", "UNKNOWN")
        actual = outcome.get("actual_pnl_pct")
        cf = outcome.get("counterfactual_pnl_pct")
        cost = outcome.get("opportunity_cost")
        beneficial = outcome.get("was_trade_beneficial")

        benefit_icon = "✅" if beneficial else "❌"
        print(f"{benefit_icon} {ts} {symbol:8} "
              f"Actual:{format_pct(actual)} CF:{format_pct(cf)} "
              f"Cost:{format_pct(cost)}")

    print()
    print("💡 INTERPRETATION GUIDE")
    print("-" * 40)
    print("• Positive opportunity cost = Trading outperformed null behavior")
    print("• High beneficial rate = System successfully identifies edges")
    print("• Edge multiplier > 1 = Trading adds value beyond participation")
    print("• Confidence correlation = System knows when it's right")
    print("• Regime differences = Context-aware intelligence")
    print()
    print("🎯 META-INTELLIGENCE STATUS")
    print("-" * 40)

    # Overall assessment
    if avg_cost and avg_cost > 0 and beneficial_rate > 0.5:
        print("🚀 HIGH META-INTELLIGENCE: System adds consistent value")
    elif avg_cost and avg_cost > 0:
        print("📈 MODERATE META-INTELLIGENCE: System adds some value")
    elif avg_cost and avg_cost < 0:
        print("📉 LOW META-INTELLIGENCE: System destroys value")
    else:
        print("🔄 BUILDING META-INTELLIGENCE: Insufficient data")


if __name__ == "__main__":
    main()
