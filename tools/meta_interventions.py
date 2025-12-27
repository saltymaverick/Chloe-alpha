#!/usr/bin/env python3
"""
Meta-Intervention Framework for Chloe
Ready to deploy when confidence reaches 7.5+

Evaluates regime performance and recommends specific, actionable interventions
to optimize trading performance based on clean sample data.
"""

import json
import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
from dateutil import parser

# Intervention thresholds
CONFIDENCE_THRESHOLD = 7.5
MIN_REGIME_SAMPLES = 50
MIN_SYMBOL_SAMPLES = 25

class MetaInterventionEngine:
    """Engine for evaluating and recommending meta-interventions."""

    def __init__(self):
        self.config_path = Path("config/engine_config.json")
        self.reports_path = Path("reports")

    def load_current_config(self) -> Dict[str, Any]:
        """Load current engine configuration."""
        try:
            with open(self.config_path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load config: {e}")
            return {}

    def load_confidence_report(self) -> Dict[str, Any]:
        """Load latest confidence report."""
        try:
            with open(self.reports_path / "confidence_report.json", "r") as f:
                return json.load(f)
        except Exception as e:
            return {"error": "confidence_report.json not found"}

    def analyze_regime_performance(self, trades: List[Dict]) -> Dict[str, Dict[str, Any]]:
        """Analyze performance by regime from clean trade data."""
        regime_stats = defaultdict(lambda: {"trades": [], "wins": 0, "losses": 0})

        for trade in trades:
            if trade.get("type") != "close":
                continue

            regime = trade.get("regime_at_entry") or trade.get("regime") or "unknown"
            try:
                pct = float(trade.get("pct", 0))
                if math.isfinite(pct):
                    regime_stats[regime]["trades"].append(pct)
                    if pct > 0:
                        regime_stats[regime]["wins"] += 1
                    else:
                        regime_stats[regime]["losses"] += 1
            except:
                continue

        # Calculate metrics for regimes with sufficient samples
        result = {}
        for regime, stats in regime_stats.items():
            trades_list = stats["trades"]
            if len(trades_list) < MIN_REGIME_SAMPLES:
                continue

            wins = stats["wins"]
            losses = stats["losses"]
            total = len(trades_list)

            # Profit factor
            gross_profit = sum(p for p in trades_list if p > 0)
            gross_loss = abs(sum(p for p in trades_list if p < 0))
            pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')

            # Win rate and average P&L
            win_rate = wins / total if total > 0 else 0
            avg_pl = sum(trades_list) / total if total > 0 else 0

            result[regime] = {
                "total_trades": total,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
                "profit_factor": pf,
                "avg_pnl": avg_pl,
                "gross_profit": gross_profit,
                "gross_loss": gross_loss,
                "sample_sufficient": True
            }

        return result

    def evaluate_interventions(self, regime_perf: Dict, confidence: Dict) -> List[Dict[str, Any]]:
        """Evaluate and recommend specific interventions based on performance data."""
        interventions = []

        # Check if we meet intervention criteria
        score = confidence.get("score_0_to_10", 0)
        if score < CONFIDENCE_THRESHOLD:
            return [{
                "type": "waiting",
                "title": "Confidence Threshold Not Met",
                "description": f"Current confidence {score:.1f}/10 < required {CONFIDENCE_THRESHOLD}",
                "priority": "high",
                "action_required": False
            }]

        # Analyze chop regime performance (most common)
        chop_perf = regime_perf.get("chop", {})
        if chop_perf.get("sample_sufficient"):
            pf = chop_perf.get("profit_factor", 0)
            win_rate = chop_perf.get("win_rate", 0)
            total_trades = chop_perf.get("total_trades", 0)

            # Chop regime interventions
            if pf < 1.0:
                interventions.append({
                    "type": "chop_threshold_tightening",
                    "title": "Tighten Chop Entry Threshold",
                    "description": f"Chop PF={pf:.2f} (below 1.0). Consider increasing chop_exploration_entry_min from 0.35",
                    "current_pf": pf,
                    "suggested_threshold": min(0.40, 0.35 + 0.05),  # Gradual increase
                    "expected_impact": "Reduce trade frequency, improve win quality",
                    "risk_level": "low",
                    "priority": "high" if pf < 0.8 else "medium"
                })

            elif pf > 1.2 and win_rate > 0.55:
                interventions.append({
                    "type": "chop_threshold_relaxation",
                    "title": "Loosen Chop Entry Threshold",
                    "description": f"Chop performing well (PF={pf:.2f}, Win%={win_rate:.1%}). Consider decreasing threshold for more opportunities",
                    "current_pf": pf,
                    "suggested_threshold": max(0.25, 0.35 - 0.05),  # Gradual decrease
                    "expected_impact": "Increase trade frequency while maintaining quality",
                    "risk_level": "medium",
                    "priority": "medium"
                })

        # Check for profitable alternative regimes
        profitable_regimes = [
            regime for regime, stats in regime_perf.items()
            if stats.get("profit_factor", 0) > 1.1 and stats.get("sample_sufficient")
        ]

        if profitable_regimes:
            interventions.append({
                "type": "regime_expansion",
                "title": "Expand to Profitable Regimes",
                "description": f"Regimes {profitable_regimes} showing PF > 1.1. Consider regime-specific tuning",
                "profitable_regimes": profitable_regimes,
                "expected_impact": "Diversify across multiple regime strategies",
                "risk_level": "medium",
                "priority": "high"
            })

        # Check for symbol expansion opportunities
        if len(regime_perf) >= 2 and all(stats.get("sample_sufficient") for stats in regime_perf.values()):
            interventions.append({
                "type": "symbol_expansion",
                "title": "Consider Symbol Expansion",
                "description": f"Multiple regimes have sufficient samples. Consider adding BTCUSDT for cross-validation",
                "current_symbols": ["ETHUSDT"],  # Based on current config
                "suggested_symbols": ["BTCUSDT", "ADAUSDT"],
                "expected_impact": "Test strategy robustness across multiple symbols",
                "risk_level": "medium",
                "priority": "medium"
            })

        # Risk management interventions
        total_trades = sum(stats.get("total_trades", 0) for stats in regime_perf.values())
        if total_trades >= 200:
            avg_win_rate = sum(stats.get("win_rate", 0) * stats.get("total_trades", 0) for stats in regime_perf.values()) / total_trades

            if avg_win_rate < 0.45:
                interventions.append({
                    "type": "risk_reduction",
                    "title": "Implement Risk Reduction Measures",
                    "description": f"Overall win rate {avg_win_rate:.1%} below 45%. Consider position size reduction",
                    "current_win_rate": avg_win_rate,
                    "suggested_action": "Reduce position sizes by 20-30%",
                    "expected_impact": "Preserve capital while strategy improves",
                    "risk_level": "low",
                    "priority": "high"
                })

        return interventions if interventions else [{
            "type": "monitoring",
            "title": "Continue Monitoring",
            "description": "Performance is stable. Continue accumulating data for further optimization opportunities",
            "priority": "low",
            "action_required": False
        }]

    def generate_implementation_plan(self, interventions: List[Dict]) -> Dict[str, Any]:
        """Generate concrete implementation plan for approved interventions."""
        plan = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "confidence_score": self.load_confidence_report().get("score_0_to_10", 0),
            "interventions": [],
            "implementation_order": [],
            "rollback_plan": {}
        }

        for intervention in interventions:
            if intervention.get("type") == "waiting":
                continue

            impl = {
                "type": intervention["type"],
                "title": intervention["title"],
                "description": intervention["description"],
                "config_changes": {},
                "monitoring_metrics": [],
                "rollback_steps": [],
                "expected_outcome": intervention.get("expected_impact", ""),
                "test_period_days": 7
            }

            # Generate specific implementation details
            if intervention["type"] == "chop_threshold_tightening":
                new_threshold = intervention["suggested_threshold"]
                impl["config_changes"] = {
                    "file": "config/engine_config.json",
                    "path": "chop_exploration_entry_min",
                    "old_value": 0.35,
                    "new_value": new_threshold
                }
                impl["monitoring_metrics"] = ["chop_regime_pf", "chop_regime_trade_count", "overall_pf"]
                impl["rollback_steps"] = ["Revert chop_exploration_entry_min to 0.35"]

            elif intervention["type"] == "chop_threshold_relaxation":
                new_threshold = intervention["suggested_threshold"]
                impl["config_changes"] = {
                    "file": "config/engine_config.json",
                    "path": "chop_exploration_entry_min",
                    "old_value": 0.35,
                    "new_value": new_threshold
                }
                impl["monitoring_metrics"] = ["chop_regime_pf", "chop_regime_trade_count", "overall_pf"]
                impl["rollback_steps"] = ["Revert chop_exploration_entry_min to 0.35"]

            elif intervention["type"] == "symbol_expansion":
                impl["config_changes"] = {
                    "file": "config/engine_config.json",
                    "path": "symbol",
                    "old_value": "ETHUSDT",
                    "new_value": "BTCUSDT",  # Start with one
                    "note": "Test new symbol in paper mode first"
                }
                impl["monitoring_metrics"] = ["new_symbol_pf", "new_symbol_regime_distribution", "overall_pf"]
                impl["rollback_steps"] = ["Revert symbol to ETHUSDT"]

            plan["interventions"].append(impl)

        # Determine implementation order (highest priority first)
        priority_order = {"high": 0, "medium": 1, "low": 2}
        plan["implementation_order"] = sorted(
            [i["type"] for i in plan["interventions"]],
            key=lambda x: next((priority_order.get(i.get("priority", "low"), 2)
                               for i in plan["interventions"] if i["type"] == x), 2)
        )

        return plan

def main():
    """Main intervention analysis and recommendation engine."""
    engine = MetaInterventionEngine()

    print("🎯 META-INTERVENTION ANALYSIS ENGINE")
    print("=" * 50)

    # Load current state
    confidence = engine.load_confidence_report()
    config = engine.load_current_config()

    score = confidence.get("score_0_to_10", 0)
    print(f"Overall Confidence: {score:.1f}/10")
    print(f"Data Floors: {'✅ MET' if confidence.get('data_floors', {}).get('floors_met') else '❌ NOT MET'}")

    if score < CONFIDENCE_THRESHOLD:
        print(f"\n⏳ WAITING FOR CONFIDENCE THRESHOLD")
        print(f"Current: {score:.1f}/10 | Required: {CONFIDENCE_THRESHOLD}")
        print("Continue accumulating clean samples...")
        return

    print("\n🎯 INTERVENTION ANALYSIS READY")
    print(f"Confidence threshold met: {score:.1f}/10 >= {CONFIDENCE_THRESHOLD}")

    # Load and analyze recent trades (last 7 days for clean data)
    try:
        trades = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=168)  # 7 days

        with open("reports/trades.jsonl", "r") as f:
            for line in f:
                try:
                    trade = json.loads(line)
                    ts = trade.get("ts")
                    if ts and parser.isoparse(ts.replace("Z", "+00:00")) >= cutoff:
                        trades.append(trade)
                except:
                    continue

        closes = [t for t in trades if t.get("type") == "close"]
        print(f"Analyzing {len(closes)} recent closes for intervention opportunities...")

        # Analyze regime performance
        regime_perf = engine.analyze_regime_performance(closes)

        if not regime_perf:
            print("❌ Insufficient regime samples for interventions")
            print(f"Need at least {MIN_REGIME_SAMPLES} trades per regime")
            return

        print(f"\n📊 REGIME PERFORMANCE SUMMARY:")
        for regime, stats in regime_perf.items():
            pf = stats.get("profit_factor", 0)
            win_rate = stats.get("win_rate", 0)
            total = stats.get("total_trades", 0)
            status = "✅" if pf > 1.0 else "❌"
            print(f"{regime:<12} {total:>6} {win_rate:>6.1%} {pf:>8.2f} {status}")
        # Evaluate interventions
        interventions = engine.evaluate_interventions(regime_perf, confidence)

        print("\n🚀 RECOMMENDED INTERVENTIONS:")
        for i, intervention in enumerate(interventions, 1):
            priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(intervention.get("priority", "low"), "⚪")
            print(f"\n{i}. {priority_emoji} {intervention['title']}")
            print(f"   {intervention['description']}")
            if 'suggested_threshold' in intervention:
                print(f"   Suggested threshold: {intervention['suggested_threshold']}")
            if 'expected_impact' in intervention:
                print(f"   Expected impact: {intervention['expected_impact']}")
            if 'risk_level' in intervention:
                risk_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(intervention['risk_level'], "⚪")
                print(f"   Risk level: {risk_emoji} {intervention['risk_level']}")

        # Generate implementation plan for the first high-priority intervention
        high_priority = [i for i in interventions if i.get("priority") == "high"]
        if high_priority:
            print("\n🔧 IMPLEMENTATION PLAN FOR FIRST HIGH-PRIORITY INTERVENTION:")
            plan = engine.generate_implementation_plan([high_priority[0]])

            for intervention in plan["interventions"]:
                print(f"\nIntervention: {intervention['title']}")
                print(f"Description: {intervention['description']}")

                config_changes = intervention.get("config_changes", {})
                if config_changes:
                    print(f"Config Change Required:")
                    print(f"  File: {config_changes['file']}")
                    print(f"  Path: {config_changes['path']}")
                    print(f"  Change: {config_changes.get('old_value', '?')} → {config_changes.get('new_value', '?')}")

                monitoring = intervention.get("monitoring_metrics", [])
                if monitoring:
                    print(f"Monitor these metrics for {intervention.get('test_period_days', 7)} days:")
                    for metric in monitoring:
                        print(f"  • {metric}")

                rollback = intervention.get("rollback_steps", [])
                if rollback:
                    print(f"Rollback plan:")
                    for step in rollback:
                        print(f"  • {step}")

    except Exception as e:
        print(f"❌ Error during analysis: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
