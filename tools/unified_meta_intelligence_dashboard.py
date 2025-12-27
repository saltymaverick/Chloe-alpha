#!/usr/bin/env python3
"""
Unified Meta-Intelligence Dashboard

The complete view of Chloe's second-order intelligence system.
Combines all meta-layers into comprehensive decision-making insights.

Shows: Counterfactual analysis + Regime uncertainty + Edge decay + Inaction discipline
"""

from __future__ import annotations
from pathlib import Path
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter
from typing import Dict, List, Any

from engine_alpha.reflect.meta_intelligence import (
    meta_intelligence_orchestrator,
    get_meta_intelligence_snapshot,
    assess_meta_decision_quality
)


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


def get_meta_health_color(score: float) -> str:
    """Get color indicator for meta-intelligence health"""
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
        return "🔴"  # Critical


def get_decision_confidence_color(confidence: float) -> str:
    """Get color for decision confidence"""
    if confidence >= 0.8:
        return "🎯"  # High confidence
    elif confidence >= 0.6:
        return "✅"  # Good confidence
    elif confidence >= 0.4:
        return "🟡"  # Moderate confidence
    else:
        return "⚠️"  # Low confidence


def main() -> None:
    """Display unified meta-intelligence dashboard"""
    print("=" * 90)
    print("🎯 UNIFIED META-INTELLIGENCE DASHBOARD")
    print("=" * 90)

    try:
        # Get complete meta-intelligence snapshot
        snapshot = get_meta_intelligence_snapshot()

        print(f"📅 Analysis Period: Last 7 days")
        print(f"⏰ Snapshot Time: {snapshot.timestamp.strftime('%Y-%m-%d %H:%M UTC')}")
        print()

        # Overall System Health
        health_color = get_meta_health_color(snapshot.system_health_score)
        print("🌟 SYSTEM META-INTELLIGENCE HEALTH")
        print("-" * 40)
        print(f"Overall Health Score: {health_color} {format_score(snapshot.system_health_score)}")
        print()

        # Component Status Overview
        print("🧩 META-COMPONENT STATUS")
        print("-" * 30)

        components = [
            ("Counterfactual Analysis", snapshot.counterfactual_metrics),
            ("Regime Uncertainty", snapshot.regime_uncertainty),
            ("Edge Half-Life", snapshot.edge_health),
            ("Inaction Performance", snapshot.inaction_performance)
        ]

        for name, metrics in components:
            if not metrics or (isinstance(metrics, dict) and metrics.get("status") == "no_data"):
                status = "🔄 COLLECTING DATA"
            elif isinstance(metrics, dict) and metrics.get("status") == "insufficient_data":
                status = "⏳ BUILDING SAMPLE"
            else:
                status = "✅ ACTIVE"

            print(f"{name:<22} {status}")

        print()

        # Key Performance Indicators
        print("📊 KEY META-INTELLIGENCE METRICS")
        print("-" * 40)

        # Counterfactual Performance
        cf = snapshot.counterfactual_metrics
        if cf and "pf_7d" in cf:
            pf_color = "🟢" if cf["pf_7d"] > 0 else "🔴"
            print(f"7-Day PF: {pf_color} {format_pct(cf['pf_7d'])}")
            print(f"Total Trades: {cf.get('count_7d', 0)}")

        # Regime Stability
        regime = snapshot.regime_uncertainty
        if regime and regime.get("aggregate_metrics"):
            reg_conf = regime["aggregate_metrics"]["avg_confidence"]
            reg_stab = regime["aggregate_metrics"]["avg_stability"]
            reg_color = get_meta_health_color((reg_conf + reg_stab) / 2)
            print(f"Regime Confidence: {reg_color} {format_score(reg_conf)}")
            print(f"Regime Stability: {reg_color} {format_score(reg_stab)}")

        # Edge Health
        edges = snapshot.edge_health
        if edges and "avg_edge_strength" in edges:
            edge_color = get_meta_health_color(edges["avg_edge_strength"])
            print(f"Average Edge Strength: {edge_color} {format_score(edges['avg_edge_strength'])}")
            print(f"Strong Edges: {edges.get('strong_edges', 0)}/{edges.get('analyzed_symbols', 0)}")

        # Inaction Performance
        inaction = snapshot.inaction_performance
        if inaction.get("status") == "success":
            inact_quality = inaction["performance_summary"]["avg_inaction_quality"]
            inact_color = get_meta_health_color(inact_quality)
            print(f"Inaction Quality: {inact_color} {format_score(inact_quality)}")
            print(f"Total Inaction Events: {inaction.get('total_inaction_decisions', 0)}")

        # Fair Value Gaps (NEW)
        fvgs = snapshot.fvg_metrics
        if fvgs and fvgs.get("status") != "insufficient_data":
            fvg_efficiency = fvgs.get("avg_market_efficiency", 0.5)
            fvg_fill_rate = fvgs.get("overall_fill_rate", 0)
            fvg_color = get_meta_health_color(fvg_efficiency)
            print(f"Market Structure Efficiency: {fvg_color} {format_score(fvg_efficiency)}")
            print(f"FVG Fill Rate: {format_pct(fvg_fill_rate * 100)}")
            print(f"Total Gaps Analyzed: {fvgs.get('total_gaps_analyzed', 0)}")

        print()

        # Meta-Decision Matrix
        print("🎲 META-DECISION MATRIX")
        print("-" * 30)

        symbols = ["ADAUSDT", "ATOMUSDT", "BTCUSDT", "DOTUSDT", "ETHUSDT", "LINKUSDT", "SOLUSDT", "BNBUSDT"]
        decision_matrix = meta_intelligence_orchestrator.get_meta_decision_matrix(symbols)

        print("Symbol      Score   Confidence   Recommendation")
        print("---------- -------- ----------- ------------------------------")

        for symbol in symbols:
            data = decision_matrix.get(symbol, {})
            score = data.get("overall_score", 0)
            confidence = data.get("confidence", 0)
            recommendation = data.get("recommendation", "No data")[:25]

            score_color = get_meta_health_color(score)
            conf_icon = get_decision_confidence_color(confidence)

            print(f"{symbol:<10} {score_color}{format_score(score):>6} {conf_icon}{format_score(confidence):>6} {recommendation}")

        print()

        # Cross-Component Insights
        insights = snapshot.cross_component_insights
        if insights:
            print("🔗 CROSS-COMPONENT INSIGHTS")
            print("-" * 35)

            for insight_key, insight_value in insights.items():
                insight_display = insight_key.replace("_", " ").title()
                print(f"• {insight_display}: {insight_value}")

            print()

        # System Recommendations
        print("💡 SYSTEM RECOMMENDATIONS")
        print("-" * 30)

        recommendations = []

        # Health-based recommendations
        if snapshot.system_health_score > 0.8:
            recommendations.append("🎯 EXCELLENT: All meta-systems operating optimally")
        elif snapshot.system_health_score > 0.6:
            recommendations.append("✅ GOOD: Meta-intelligence performing well")
        elif snapshot.system_health_score > 0.4:
            recommendations.append("🟡 MONITOR: Some meta-components need attention")
        else:
            recommendations.append("⚠️  REVIEW: Meta-intelligence systems need improvement")

        # Data collection status
        components_with_data = sum(1 for name, metrics in components
                                 if metrics and not (isinstance(metrics, dict) and
                                                   metrics.get("status") in ["no_data", "insufficient_data"]))

        if components_with_data < 2:
            recommendations.append("⏳ DATA BUILDING: Continue trading to populate meta-analysis")
        elif components_with_data < 4:
            recommendations.append("📈 DATA GROWING: Meta-insights developing well")

        # Component-specific recommendations
        if cf and "pf_7d" in cf and cf["pf_7d"] < 0.9:
            recommendations.append("🔄 REVIEW: Consider edge rotation strategies")

        if regime and regime.get("aggregate_metrics", {}).get("avg_confidence", 1) < 0.6:
            recommendations.append("🌊 UNCERTAIN: High regime uncertainty detected")

        if edges and edges.get("avg_edge_strength", 1) < 0.5:
            recommendations.append("⏰ EDGES WEAK: Consider waiting for stronger setups")

        if inaction.get("status") == "success" and inaction["performance_summary"]["avg_inaction_quality"] < 0.5:
            recommendations.append("🎭 DISCIPLINE: Review inaction criteria effectiveness")

        # FVG-specific recommendations
        if fvgs and fvgs.get("status") != "insufficient_data":
            fvg_efficiency = fvgs.get("avg_market_efficiency", 0.5)
            fill_rate = fvgs.get("overall_fill_rate", 0)

            if fvg_efficiency < 0.4:
                recommendations.append("🏗️ STRUCTURE: Market showing structural inefficiencies")

            if fill_rate < 0.4:
                recommendations.append("🎯 GAPS: Low FVG fill rates suggest persistent dislocations")

            if fvg_efficiency > 0.7 and fill_rate > 0.6:
                recommendations.append("✅ STRUCTURE: Efficient market structure supports mean reversion")

        for i, rec in enumerate(recommendations[:5], 1):  # Limit to top 5
            print(f"{i}. {rec}")

        print()
        print("🎯 META-INTELLIGENCE MISSION ACCOMPLISHED")
        print("-" * 50)
        print("Chloe now operates with complete second-order intelligence:")
        print("• Counterfactual analysis of decision quality")
        print("• Regime uncertainty awareness")
        print("• Edge decay modeling and rotation timing")
        print("• Inaction performance quantification")
        print("• Fair Value Gap structural analysis")
        print("• Unified meta-decision orchestration")
        print()
        print("From signal processing to market structure intelligence. 🚀")

    except Exception as e:
        print(f"❌ DASHBOARD ERROR: {e}")
        print("   Meta-intelligence systems may still be initializing")
        print("   This is normal during early data collection phase")


if __name__ == "__main__":
    main()
