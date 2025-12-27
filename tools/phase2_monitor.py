#!/usr/bin/env python3
"""
Phase 2 Monitoring: Confidence Escalation Dashboard

Tracks Chloe's progress toward 7.5+ confidence with regime-aware analytics.
Run daily to monitor sample accumulation and performance attribution.
"""

import json
import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Any
from dateutil import parser

# Constants
REPORTS = Path("reports")
CONFIDENCE_THRESHOLDS = {
    "regime_edge_separation": 0.05,
    "counterfactual_superiority_net_edge": 0.03,
    "counterfactual_superiority_confidence_gradient": 0.3,
    "counterfactual_superiority_blocking_efficiency": 0.02,
    "edge_persistence_decay_confidence": 0.6
}

def load_trades(hours: int = 168) -> List[Dict]:  # Default 7 days
    """Load trades from the specified time window."""
    trades = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    try:
        with open(REPORTS / "trades.jsonl", "r") as f:
            for line in f:
                try:
                    trade = json.loads(line)
                    ts = trade.get("ts")
                    if ts and parser.isoparse(ts.replace("Z", "+00:00")) >= cutoff:
                        trades.append(trade)
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        print("Warning: trades.jsonl not found")

    return trades

def analyze_symbol_recovery() -> Dict[str, Any]:
    """Analyze which symbols are recovering from auto-demotion."""
    result = {"eth_recovery_status": "unknown", "other_symbols_status": {}}

    # Check ETH specifically
    try:
        import subprocess
        output = subprocess.run([
            "python3", "-m", "tools.why_symbol_blocked", "ETHUSDT"
        ], capture_output=True, text=True, cwd=".")

        if "auto_demote_loss_streak_24h" in output.stdout:
            # Extract expiry time
            lines = output.stdout.split('\n')
            for line in lines:
                if "expires_at" in line and "auto_demote" in line:
                    result["eth_recovery_status"] = f"demoted_until_{line.split()[-1]}"
                    break
        elif "eligible_now" in output.stdout and "True" in output.stdout:
            result["eth_recovery_status"] = "recovered"
        else:
            result["eth_recovery_status"] = "other_restrictions"
    except Exception as e:
        result["eth_recovery_status"] = f"error: {e}"

    return result

def analyze_regime_performance(trades: List[Dict]) -> Dict[str, Any]:
    """Analyze performance by regime with statistical significance."""
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
        except (ValueError, TypeError):
            continue

    # Calculate metrics for regimes with sufficient samples
    result = {}
    for regime, stats in regime_stats.items():
        trades = stats["trades"]
        if len(trades) < 10:  # Need minimum samples for significance
            continue

        wins = stats["wins"]
        losses = stats["losses"]
        total = len(trades)

        # Profit factor
        gross_profit = sum(p for p in trades if p > 0)
        gross_loss = abs(sum(p for p in trades if p < 0))
        pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Win rate and average P&L
        win_rate = wins / total if total > 0 else 0
        avg_pl = sum(trades) / total if total > 0 else 0

        result[regime] = {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "profit_factor": pf,
            "avg_pnl": avg_pl,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "sample_sufficient": total >= 50
        }

    return result

def load_confidence_report() -> Dict[str, Any]:
    """Load the latest confidence report."""
    try:
        with open(REPORTS / "confidence_report.json", "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"error": "confidence_report.json not found or invalid"}

def generate_intervention_recommendations(confidence: Dict, regime_perf: Dict) -> List[str]:
    """Generate recommendations for meta-interventions when confidence >= 7.0."""
    recommendations = []

    score = confidence.get("score_0_to_10", 0)

    if score >= 7.0:
        # Analyze regime performance for tuning opportunities
        chop_perf = regime_perf.get("chop", {})
        if chop_perf.get("sample_sufficient", False):
            pf = chop_perf.get("profit_factor", 0)
            if pf < 1.0:
                recommendations.append("chop_pf_below_1.0 - consider increasing chop_exploration_entry_min from 0.35")
            elif pf > 1.2:
                recommendations.append("chop_pf_above_1.2 - chop regime performing well")

        # Check for symbol expansion opportunities
        if len([r for r in regime_perf.values() if r.get("sample_sufficient")]) >= 2:
            recommendations.append("multiple_regimes_sampled - consider expanding to BTCUSDT for cross-validation")

    return recommendations

def main():
    """Main monitoring dashboard."""
    print("🎯 CHLOE PHASE 2 MONITORING DASHBOARD")
    print("=" * 50)

    # 1. Symbol Recovery Status
    print("\n📊 SYMBOL RECOVERY STATUS:")
    recovery = analyze_symbol_recovery()
    print(f"  ETHUSDT: {recovery['eth_recovery_status']}")

    # 2. Load recent trades (7 days)
    print("\n📈 TRADE ACTIVITY (7 DAYS):")
    trades = load_trades(168)  # 7 days
    closes = [t for t in trades if t.get("type") == "close"]
    opens = [t for t in trades if t.get("type") == "open"]

    print(f"  Total trades: {len(closes)} closes, {len(opens)} opens")

    # 3. Regime Performance Analysis
    print("\n🎯 REGIME PERFORMANCE ANALYSIS:")
    regime_perf = analyze_regime_performance(closes)

    if not regime_perf:
        print("  No regimes with sufficient samples (need 10+ trades per regime)")
    else:
        print(f"{'Regime':<12} {'Trades':>6} {'Win%':>6} {'PF':>6} {'Avg P&L':>10} {'Status'}")
        print("-" * 60)
        for regime, stats in sorted(regime_perf.items()):
            status = "✅ SUFFICIENT" if stats["sample_sufficient"] else "⏳ ACCUMULATING"
            print(f"{regime:<12} {stats['total_trades']:>6} {stats['win_rate']:>6.1%} {stats['profit_factor']:>6.2f} {stats['avg_pnl']:>10.4f} {status}")

    # 4. Confidence Report
    print("\n🎯 CONFIDENCE ESCALATION STATUS:")
    confidence = load_confidence_report()

    if "error" in confidence:
        print(f"  ❌ {confidence['error']}")
    else:
        score = confidence.get("score_0_to_10", 0)
        floors_met = confidence.get("data_floors", {}).get("floors_met", False)

        print(f"  Overall Score: {score:.1f}/10")
        print(f"  Data Floors: {'✅ MET' if floors_met else '❌ NOT MET'}")

        pillars = confidence.get("pillars", {})
        for pillar_name, pillar_data in pillars.items():
            status = "✅ PASS" if pillar_data.get("pass", False) else "❌ FAIL"
            samples = pillar_data.get("sample_count", 0)
            print(f"    {pillar_name.replace('_', ' ').title()}: {status} ({samples} samples)")

        gates = confidence.get("gates_ready", {})
        ready_gates = [k for k, v in gates.items() if v]
        if ready_gates:
            print(f"  Ready Gates: {', '.join(ready_gates)}")
        else:
            print("  Ready Gates: None yet")

    # 5. Intervention Recommendations
    if confidence.get("score_0_to_10", 0) >= 7.0:
        print("\n🚀 META-INTERVENTION OPPORTUNITIES:")
        recommendations = generate_intervention_recommendations(confidence, regime_perf)
        if recommendations:
            for rec in recommendations:
                print(f"  • {rec}")
        else:
            print("  No specific recommendations at this time")

    # 6. Next Steps
    print("\n🎯 NEXT STEPS:")
    score = confidence.get("score_0_to_10", 0)
    if score < 6.0:
        print("  Continue sample accumulation - confidence building to 6.0+")
    elif score < 7.0:
        print("  Approaching intervention threshold - monitor closely")
    elif score < 8.5:
        print("  Ready for meta-interventions - evaluate regime tuning options")
    else:
        print("  Ready for advanced features - consider tuner_apply, dream_mode")

    print(f"\n📅 Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

if __name__ == "__main__":
    main()
