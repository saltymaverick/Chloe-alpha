#!/usr/bin/env python3
"""
Confidence Escalation Report - Gatekeeper for Advanced Features

Evaluates Chloe's intelligence across three pillars:
1. Regime Edge Separation - Conditional superiority by market regime
2. Counterfactual Superiority - Decision quality vs. naive baselines
3. Edge Persistence - Decay detection and adaptive response

Determines which advanced features Chloe has earned the right to use.

Usage:
    python3 -m tools.confidence_report              # Full report
    python3 -m tools.confidence_report --summary    # 5-line summary
"""

from __future__ import annotations

import json
import sys
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
from collections import defaultdict
import statistics

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"

# Thresholds (hardcoded as specified)
MIN_TOTAL_CLOSES = 60
MIN_PER_REGIME_CLOSES = 15
MIN_REGIMES_WITH_DATA = 2

# Pillar thresholds
REGIME_SEPARATION_MIN = 0.05  # PF advantage
COUNTERFACTUAL_NET_EDGE_MIN = 0.03
COUNTERFACTUAL_CONFIDENCE_GRADIENT_MIN = 0.3
COUNTERFACTUAL_BLOCKING_EFFICIENCY_MIN = 0.02
EDGE_PERSISTENCE_DECAY_CONFIDENCE_MIN = 0.6
EDGE_PERSISTENCE_SAMPLE_MIN = 30

# Feature gate thresholds
META_ORCHESTRATOR_THRESHOLD = 8.5
MINI_REFLECTION_THRESHOLD = 8.5
DREAM_MODE_THRESHOLD = 9.0
TUNER_APPLY_THRESHOLD = 9.2


def atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically using temp file."""
    import tempfile
    import os

    path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False, suffix='.tmp') as f:
        json.dump(data, f, indent=2, default=str)
        temp_path = Path(f.name)

    temp_path.replace(path)


def safe_read_json(path: Path) -> Optional[Any]:
    """Read JSON safely, return None on failure."""
    try:
        if path.exists():
            with path.open('r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return None


def safe_read_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Read JSONL safely, skip bad lines."""
    records = []
    try:
        if path.exists():
            with path.open('r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        continue
    except Exception:
        pass
    return records


def analyze_data_floors() -> Dict[str, Any]:
    """Check if we have minimum data requirements."""
    pf_local = safe_read_json(REPORTS / "pf_local.json")
    if not pf_local:
        return {
            "total_closes": 0,
            "regimes_with_15_plus": 0,
            "floors_met": False,
            "notes": ["pf_local.json missing or unreadable"]
        }

    # Count total closes
    total_closes = 0
    regime_counts = defaultdict(int)

    # Try to get counts from pf_local
    for key, value in pf_local.items():
        if key.startswith('count_') and key.endswith('d'):
            # count_7d, count_30d, etc.
            if isinstance(value, (int, float)):
                if key == 'count_7d':  # Use 7d as representative
                    total_closes = int(value)
        elif key.startswith('count_7d_regime_'):
            # count_7d_regime_chop, etc.
            regime_name = key.replace('count_7d_regime_', '')
            if isinstance(value, (int, float)):
                regime_counts[regime_name] = int(value)

    # If we don't have regime-specific counts, estimate
    if not regime_counts and total_closes > 0:
        # Assume roughly even distribution across common regimes
        regimes_with_data = max(1, min(3, total_closes // 20))  # Rough estimate
        regimes_with_15_plus = regimes_with_data if total_closes >= 60 else 0
    else:
        regimes_with_15_plus = sum(1 for count in regime_counts.values() if count >= MIN_PER_REGIME_CLOSES)

    floors_met = (
        total_closes >= MIN_TOTAL_CLOSES and
        regimes_with_15_plus >= MIN_REGIMES_WITH_DATA
    )

    notes = []
    if total_closes < MIN_TOTAL_CLOSES:
        notes.append(f"Need {MIN_TOTAL_CLOSES - total_closes} more closes (have {total_closes})")
    if regimes_with_15_plus < MIN_REGIMES_WITH_DATA:
        notes.append(f"Need {MIN_REGIMES_WITH_DATA - regimes_with_15_plus} more regimes with {MIN_PER_REGIME_CLOSES}+ closes")

    return {
        "total_closes": total_closes,
        "regimes_with_15_plus": regimes_with_15_plus,
        "floors_met": floors_met,
        "notes": notes
    }


def analyze_regime_edge_separation() -> Dict[str, Any]:
    """Analyze regime-conditional edge separation."""
    pf_local = safe_read_json(REPORTS / "pf_local.json")
    if not pf_local:
        return {"score": 0.0, "pass": False, "sample_count": 0, "details": {"error": "pf_local.json missing"}}

    # Look for regime-specific PF data
    regime_pfs = {}
    global_pf = None

    # Extract regime PFs and global PF from pf_local
    for key, value in pf_local.items():
        if key.startswith('pf_7d_regime_'):  # Use 7d data
            regime_name = key.replace('pf_7d_regime_', '')
            if isinstance(value, (int, float)) and not math.isnan(value):
                regime_pfs[regime_name] = float(value)
        elif key == 'pf_7d':
            if isinstance(value, (int, float)) and not math.isnan(value):
                global_pf = float(value)

    if not regime_pfs or global_pf is None:
        return {"score": 0.0, "pass": False, "sample_count": 0, "details": {"error": "insufficient regime PF data"}}

    # Calculate separations: regime_pf - global_pf
    separations = {}
    positive_separations = []

    for regime, regime_pf in regime_pfs.items():
        separation = regime_pf - global_pf
        separations[regime] = separation
        if separation > 0:
            positive_separations.append(separation)

    # Check pass criteria
    regimes_with_separation = sum(1 for sep in separations.values() if sep > REGIME_SEPARATION_MIN)
    pass_criteria = regimes_with_separation >= 2

    # Calculate score (average positive separation, normalized)
    avg_positive_separation = statistics.mean(positive_separations) if positive_separations else 0.0
    normalized_separation = min(avg_positive_separation, 0.20) / 0.20  # Cap at 20% advantage
    score = normalized_separation

    sample_count = sum(pf_local.get(f'count_7d_regime_{regime}', 0) for regime in regime_pfs.keys())

    return {
        "score": round(score, 3),
        "pass": pass_criteria,
        "sample_count": sample_count,
        "details": {
            "separations": separations,
            "regimes_with_separation": regimes_with_separation,
            "avg_positive_separation": round(avg_positive_separation, 4),
            "global_pf": global_pf
        }
    }


def analyze_counterfactual_superiority() -> Dict[str, Any]:
    """Analyze counterfactual superiority of decisions."""
    # Load counterfactual ledger
    cf_records = safe_read_jsonl(REPORTS / "counterfactual_ledger.jsonl")
    if not cf_records:
        return {"score": 0.0, "pass": False, "sample_count": 0, "details": {"error": "counterfactual_ledger.jsonl missing or empty"}}

    # Load inaction performance log
    inaction_records = safe_read_jsonl(REPORTS / "inaction_performance_log.jsonl")

    # Extract decision outcomes
    actual_pcts = []
    counterfactual_pcts = []
    confidence_scores = []

    for record in cf_records:
        # Look for actual performance and counterfactual
        actual_pct = record.get('actual_pct') or record.get('pct') or record.get('return')
        cf_pct = record.get('counterfactual_pct') or record.get('null_pct') or record.get('hold_pct')
        confidence = record.get('confidence')

        # Try multiple field name variations from the counterfactual ledger
        actual_pct = record.get('actual_pnl_pct')
        if actual_pct is None:
            actual_pct = record.get('actual_pct')
        if actual_pct is None:
            actual_pct = record.get('pct')
        if actual_pct is None:
            actual_pct = record.get('return')

        cf_pct = record.get('counterfactual_pnl_pct')
        if cf_pct is None:
            cf_pct = record.get('counterfactual_pct')
        if cf_pct is None:
            cf_pct = record.get('null_pct')
        if cf_pct is None:
            cf_pct = record.get('hold_pct')

        confidence = record.get('confidence_at_decision')
        if confidence is None:
            confidence = record.get('confidence')

        if actual_pct is not None and cf_pct is not None and confidence is not None:
            # Normalize to decimal if needed (detect percent vs decimal)
            if abs(actual_pct) > 10:  # Likely percentage
                actual_pct /= 100.0
            if abs(cf_pct) > 10:
                cf_pct /= 100.0

            actual_pcts.append(float(actual_pct))
            counterfactual_pcts.append(float(cf_pct))
            confidence_scores.append(float(confidence))

    if len(actual_pcts) < 10:
        return {"score": 0.0, "pass": False, "sample_count": len(actual_pcts), "details": {"error": "insufficient counterfactual data"}}

    # Calculate net edge
    deltas = [a - c for a, c in zip(actual_pcts, counterfactual_pcts)]
    net_edge = statistics.mean(deltas)

    # Calculate confidence gradient (correlation)
    try:
        confidence_gradient = statistics.correlation(confidence_scores, actual_pcts)
        if math.isnan(confidence_gradient):
            confidence_gradient = 0.0
    except Exception:
        confidence_gradient = 0.0

    # Calculate blocking efficiency
    blocked_outcomes = []
    allowed_outcomes = actual_pcts  # Allowed trades' actual outcomes

    for record in inaction_records:
        cf_outcome = record.get('counterfactual_pct') or record.get('missed_pct')
        if cf_outcome is not None:
            if abs(cf_outcome) > 10:  # Normalize
                cf_outcome /= 100.0
            blocked_outcomes.append(float(cf_outcome))

    blocking_efficiency = 0.0
    if blocked_outcomes and allowed_outcomes:
        avg_blocked = statistics.mean(blocked_outcomes)
        avg_allowed = statistics.mean(allowed_outcomes)
        blocking_efficiency = avg_blocked - avg_allowed  # How much worse blocked would have been

    # Check pass criteria
    net_edge_pass = net_edge > COUNTERFACTUAL_NET_EDGE_MIN
    confidence_pass = abs(confidence_gradient) > COUNTERFACTUAL_CONFIDENCE_GRADIENT_MIN
    blocking_pass = blocking_efficiency > COUNTERFACTUAL_BLOCKING_EFFICIENCY_MIN

    pass_criteria = net_edge_pass and confidence_pass and blocking_pass

    # Calculate score (weighted combination)
    net_edge_score = min(abs(net_edge) / 0.10, 1.0)  # Normalize to 0-1 (cap at 10% edge)
    confidence_score = min(abs(confidence_gradient), 1.0)
    blocking_score = min(blocking_efficiency / 0.05, 1.0)  # Normalize to 0-1 (cap at 5% efficiency)

    overall_score = (
        net_edge_score * 0.4 +
        confidence_score * 0.4 +
        blocking_score * 0.2
    )

    return {
        "score": round(overall_score, 3),
        "pass": pass_criteria,
        "sample_count": len(actual_pcts),
        "details": {
            "net_edge": round(net_edge, 4),
            "confidence_gradient": round(confidence_gradient, 3),
            "blocking_efficiency": round(blocking_efficiency, 4),
            "net_edge_pass": net_edge_pass,
            "confidence_pass": confidence_pass,
            "blocking_pass": blocking_pass
        }
    }


def analyze_edge_persistence() -> Dict[str, Any]:
    """Analyze edge persistence and decay detection."""
    edge_data = safe_read_json(REPORTS / "edge_half_life.json")
    if not edge_data:
        return {"score": 0.0, "pass": False, "sample_count": 0, "details": {"error": "edge_half_life.json missing"}}

    # Look for edge clusters with decay analysis
    clusters = edge_data.get('clusters', []) or edge_data.get('edges', [])
    if not clusters:
        return {"score": 0.0, "pass": False, "sample_count": 0, "details": {"error": "no edge clusters found"}}

    # Find best cluster that meets criteria
    best_cluster = None
    best_confidence = 0.0

    for cluster in clusters:
        if isinstance(cluster, dict):
            half_life = cluster.get('half_life_days') or cluster.get('half_life')
            decay_confidence = cluster.get('decay_confidence') or cluster.get('confidence')
            sample_count = cluster.get('sample_count') or cluster.get('samples')

            if (half_life is not None and half_life > 0 and
                decay_confidence is not None and decay_confidence >= EDGE_PERSISTENCE_DECAY_CONFIDENCE_MIN and
                sample_count is not None and sample_count >= EDGE_PERSISTENCE_SAMPLE_MIN):

                if decay_confidence > best_confidence:
                    best_cluster = cluster
                    best_confidence = decay_confidence

    if best_cluster:
        return {
            "score": round(best_confidence, 3),
            "pass": True,
            "sample_count": best_cluster.get('sample_count', 0),
            "details": {
                "best_cluster": {
                    "half_life_days": best_cluster.get('half_life_days'),
                    "decay_confidence": best_confidence,
                    "sample_count": best_cluster.get('sample_count')
                }
            }
        }
    else:
        return {"score": 0.0, "pass": False, "sample_count": 0, "details": {"error": "no qualifying edge clusters"}}


def generate_recommendations(data_floors: Dict, pillars: Dict) -> List[str]:
    """Generate recommendations based on analysis."""
    recommendations = []

    # Data floor recommendations
    if not data_floors["floors_met"]:
        recommendations.append("Accumulate more closes per regime (need 60+ total, 15+ per regime for 2+ regimes)")

    # Pillar-specific recommendations
    regime = pillars["regime_edge_separation"]
    if not regime["pass"]:
        if regime["details"].get("error"):
            recommendations.append(f"Regime analysis: {regime['details']['error']}")
        else:
            regimes_with_sep = regime["details"].get("regimes_with_separation", 0)
            recommendations.append(f"Regime separation: only {regimes_with_sep} regimes show >5% edge (need 2+)")

    cf = pillars["counterfactual_superiority"]
    if not cf["pass"]:
        if cf["details"].get("error"):
            recommendations.append(f"Counterfactual analysis: {cf['details']['error']}")
        else:
            issues = []
            if not cf["details"].get("net_edge_pass"):
                issues.append("net edge too low")
            if not cf["details"].get("confidence_pass"):
                issues.append("confidence gradient weak")
            if not cf["details"].get("blocking_pass"):
                issues.append("blocking efficiency insufficient")
            if issues:
                recommendations.append(f"Counterfactual: {', '.join(issues)}")

    edge = pillars["edge_persistence"]
    if not edge["pass"]:
        if edge["details"].get("error"):
            recommendations.append(f"Edge persistence: {edge['details']['error']}")
        else:
            recommendations.append("Edge persistence: need decay analysis with confidence ≥0.6 and samples ≥30")

    if not recommendations:
        recommendations.append("All pillars passing - consider enabling advanced features")

    return recommendations


def generate_confidence_report() -> Dict[str, Any]:
    """Generate the complete confidence escalation report."""
    # Analyze all components
    data_floors = analyze_data_floors()
    regime_pillar = analyze_regime_edge_separation()
    cf_pillar = analyze_counterfactual_superiority()
    edge_pillar = analyze_edge_persistence()

    pillars = {
        "regime_edge_separation": regime_pillar,
        "counterfactual_superiority": cf_pillar,
        "edge_persistence": edge_pillar
    }

    # Calculate overall score
    if data_floors["floors_met"]:
        pillar_scores = [regime_pillar["score"], cf_pillar["score"], edge_pillar["score"]]
        overall_score = 10 * (pillar_scores[0] * 0.4 + pillar_scores[1] * 0.4 + pillar_scores[2] * 0.2)
    else:
        overall_score = 0.0

    # Determine feature readiness
    floors_met = data_floors["floors_met"]
    gates_ready = {
        "ready_for_meta_orchestrator_enforce": floors_met and overall_score >= META_ORCHESTRATOR_THRESHOLD,
        "ready_for_mini_reflection_enforce": floors_met and overall_score >= MINI_REFLECTION_THRESHOLD,
        "ready_for_dream_mode": floors_met and overall_score >= DREAM_MODE_THRESHOLD,
        "ready_for_tuner_apply": floors_met and overall_score >= TUNER_APPLY_THRESHOLD
    }

    # Generate recommendations
    recommendations = generate_recommendations(data_floors, pillars)

    # Build final report
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "score_0_to_10": round(overall_score, 1),
        "data_floors": data_floors,
        "pillars": pillars,
        "gates_ready": gates_ready,
        "recommendations": recommendations
    }

    return report


def print_summary(report: Dict[str, Any]) -> None:
    """Print 5-line summary."""
    score = report["score_0_to_10"]
    floors = "MET" if report["data_floors"]["floors_met"] else "NOT MET"

    pillar_status = []
    for pillar_name, pillar_data in report["pillars"].items():
        status = "PASS" if pillar_data["pass"] else "FAIL"
        pillar_status.append(f"{pillar_name.split('_')[0]}:{status}")

    gates = [k.replace("ready_for_", "").replace("_", " ") for k, v in report["gates_ready"].items() if v]

    print(f"Overall Confidence: {score}/10")
    print(f"Data Floors: {floors}")
    print(f"Pillars: {' | '.join(pillar_status)}")
    print(f"Ready Gates: {' | '.join(gates) if gates else 'None'}")
    print(f"Next Steps: {report['recommendations'][0] if report['recommendations'] else 'All criteria met'}")


def main() -> int:
    """Main entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Confidence Escalation Report")
    parser.add_argument("--summary", action="store_true", help="Print 5-line summary only")
    args = parser.parse_args()

    # Generate report
    report = generate_confidence_report()

    # Write JSON file
    atomic_write_json(REPORTS / "confidence_report.json", report)

    # Output based on mode
    if args.summary:
        print_summary(report)
    else:
        # Print readable summary
        print("=== CONFIDENCE ESCALATION REPORT ===")
        print(f"Generated: {report['generated_at']}")
        print(f"Overall Score: {report['score_0_to_10']}/10")
        print()

        print("DATA FLOORS:")
        floors = report['data_floors']
        print(f"  Total Closes: {floors['total_closes']} (need {MIN_TOTAL_CLOSES})")
        print(f"  Regimes w/15+ Closes: {floors['regimes_with_15_plus']} (need {MIN_REGIMES_WITH_DATA})")
        print(f"  Floors Met: {floors['floors_met']}")
        if floors['notes']:
            print(f"  Notes: {'; '.join(floors['notes'])}")
        print()

        print("PILLARS:")
        for pillar_name, pillar_data in report['pillars'].items():
            clean_name = pillar_name.replace('_', ' ').title()
            status = "✅ PASS" if pillar_data['pass'] else "❌ FAIL"
            score = pillar_data['score']
            samples = pillar_data['sample_count']
            print(f"  {clean_name}: {status} ({score:.2f}, {samples} samples)")

            # Show key details
            details = pillar_data['details']
            if 'error' not in details:
                if pillar_name == 'regime_edge_separation':
                    sep = details.get('avg_positive_separation', 0)
                    regimes = details.get('regimes_with_separation', 0)
                    print(f"    Avg Separation: {sep:.3f}, Regimes w/Edge: {regimes}")
                elif pillar_name == 'counterfactual_superiority':
                    net_edge = details.get('net_edge', 0)
                    conf_grad = details.get('confidence_gradient', 0)
                    block_eff = details.get('blocking_efficiency', 0)
                    print(f"    Net Edge: {net_edge:.3f}, Conf Gradient: {conf_grad:.2f}, Block Eff: {block_eff:.3f}")
                elif pillar_name == 'edge_persistence' and pillar_data['pass']:
                    cluster = details.get('best_cluster', {})
                    hl = cluster.get('half_life_days', 'N/A')
                    conf = cluster.get('decay_confidence', 0)
                    print(f"    Half-life: {hl}, Decay Conf: {conf:.2f}")
        print()

        print("FEATURE GATES:")
        for gate, ready in report['gates_ready'].items():
            clean_gate = gate.replace('ready_for_', '').replace('_', ' ').title()
            status = "✅ READY" if ready else "⏳ NOT READY"
            print(f"  {clean_gate}: {status}")
        print()

        print("RECOMMENDATIONS:")
        for rec in report['recommendations']:
            print(f"  • {rec}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
