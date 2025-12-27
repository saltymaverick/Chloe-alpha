"""
Meta-Reasoner - Phase 3
Contradiction detection and repair for GPT outputs.

Reads multiple recent GPT outputs (Reflection/Tuner/Dream/Memory) and detects:
- Tier instability (symbols bouncing between tiers)
- Contradictory tuning proposals (deltas flipping direction)
- Persistent disagreements (Reflection says strong, Tuner proposes tightening)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from engine_alpha.research.research_memory import load_recent_memory
from engine_alpha.core.paths import REPORTS

RESEARCH_DIR = REPORTS / "research"
META_REASONER_REPORT_PATH = RESEARCH_DIR / "meta_reasoner_report.json"


def _analyze_tier_instability(memory_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Detect symbols that have moved between tiers across cycles.
    
    Returns list of issues with type="tier_instability".
    """
    issues = []
    
    # Track tier assignments per symbol across cycles
    symbol_tiers: Dict[str, List[str]] = {}
    
    for entry in memory_entries:
        reflection = entry.get("reflection")
        if not reflection:
            continue
        
        tiers = reflection.get("tiers", {})
        if not isinstance(tiers, dict):
            continue
        
        # Map symbol -> tier for this cycle
        for tier_name, symbol_list in tiers.items():
            if not isinstance(symbol_list, list):
                continue
            for symbol in symbol_list:
                if symbol not in symbol_tiers:
                    symbol_tiers[symbol] = []
                symbol_tiers[symbol].append(tier_name)
    
    # Find symbols with instability
    for symbol, tier_history in symbol_tiers.items():
        if len(tier_history) < 2:
            continue  # Need at least 2 cycles to detect instability
        
        # Count unique tiers
        unique_tiers = set(tier_history)
        if len(unique_tiers) > 1:
            # Symbol moved between tiers
            tier_changes = len([i for i in range(1, len(tier_history)) if tier_history[i] != tier_history[i-1]])
            if tier_changes >= 2:  # Changed at least twice
                issues.append({
                    "type": "tier_instability",
                    "symbol": symbol,
                    "details": f"Symbol moved between {', '.join(unique_tiers)} in {len(tier_history)} cycles. Changed tiers {tier_changes} times.",
                    "tier_history": tier_history,
                })
    
    return issues


def _analyze_contradictory_tuning(memory_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Detect symbols with tuning proposals that flip direction repeatedly.
    
    Returns list of issues with type="contradictory_tuning".
    """
    issues = []
    
    # Track tuning proposals per symbol across cycles
    symbol_deltas: Dict[str, List[float]] = {}
    
    for entry in memory_entries:
        tuner = entry.get("tuner")
        if not tuner:
            continue
        
        proposals = tuner.get("tuning_proposals") or tuner.get("proposals", {}).get("tuning_proposals", {})
        if not isinstance(proposals, dict):
            continue
        
        for symbol, proposal in proposals.items():
            if not isinstance(proposal, dict):
                continue
            
            conf_delta = proposal.get("conf_min_delta", 0.0)
            try:
                conf_float = float(conf_delta)
            except (ValueError, TypeError):
                continue
            
            if symbol not in symbol_deltas:
                symbol_deltas[symbol] = []
            symbol_deltas[symbol].append(conf_float)
    
    # Find symbols with contradictory tuning
    for symbol, deltas in symbol_deltas.items():
        if len(deltas) < 3:
            continue  # Need at least 3 cycles to detect pattern
        
        # Count sign changes
        sign_changes = 0
        for i in range(1, len(deltas)):
            prev_sign = 1 if deltas[i-1] > 0 else (-1 if deltas[i-1] < 0 else 0)
            curr_sign = 1 if deltas[i] > 0 else (-1 if deltas[i] < 0 else 0)
            if prev_sign != 0 and curr_sign != 0 and prev_sign != curr_sign:
                sign_changes += 1
        
        if sign_changes >= 2:  # Flipped direction at least twice
            issues.append({
                "type": "contradictory_tuning",
                "symbol": symbol,
                "details": f"Tuner proposals alternated between loosening and tightening. Delta history: {deltas}. Sign changes: {sign_changes}.",
                "delta_history": deltas,
            })
    
    return issues


def _analyze_reflection_tuner_disagreement(memory_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Detect cases where Reflection says symbol is strong but Tuner proposes tightening (or vice versa).
    
    Returns list of issues with type="reflection_tuner_disagreement".
    """
    issues = []
    
    for entry in memory_entries:
        reflection = entry.get("reflection")
        tuner = entry.get("tuner")
        
        if not reflection or not tuner:
            continue
        
        # Get tier assignments from reflection
        tiers = reflection.get("tiers", {})
        tier1_symbols = set(tiers.get("tier1", []))
        tier3_symbols = set(tiers.get("tier3", []))
        
        # Get tuning proposals
        proposals = tuner.get("tuning_proposals") or tuner.get("proposals", {}).get("tuning_proposals", {})
        if not isinstance(proposals, dict):
            continue
        
        # Check for disagreements
        for symbol, proposal in proposals.items():
            if not isinstance(proposal, dict):
                continue
            
            conf_delta = proposal.get("conf_min_delta", 0.0)
            try:
                conf_float = float(conf_delta)
            except (ValueError, TypeError):
                continue
            
            # Tier1 but tightening (disagreement)
            if symbol in tier1_symbols and conf_float > 0.01:
                issues.append({
                    "type": "reflection_tuner_disagreement",
                    "symbol": symbol,
                    "details": f"Reflection assigned tier1 (strong) but Tuner proposes tightening (conf_min_delta={conf_float:.3f}).",
                    "tier": "tier1",
                    "tuner_action": "tightening",
                })
            
            # Tier3 but loosening (disagreement)
            if symbol in tier3_symbols and conf_float < -0.01:
                issues.append({
                    "type": "reflection_tuner_disagreement",
                    "symbol": symbol,
                    "details": f"Reflection assigned tier3 (weak) but Tuner proposes loosening (conf_min_delta={conf_float:.3f}).",
                    "tier": "tier3",
                    "tuner_action": "loosening",
                })
    
    return issues


def _analyze_tuner_harm() -> List[Dict[str, Any]]:
    """
    Detect symbols where tuning self-eval shows net harm.
    
    Returns list of issues with type="tuner_harm_warning".
    """
    issues = []
    
    SELF_EVAL_PATH = REPORTS / "research" / "tuning_self_eval.json"
    if not SELF_EVAL_PATH.exists():
        return issues
    
    try:
        data = json.loads(SELF_EVAL_PATH.read_text())
        self_eval_summary = data.get("summary", {})
    except Exception:
        return issues
    
    for sym, summary in self_eval_summary.items():
        if not isinstance(summary, dict):
            continue
        
        improved = summary.get("improved", 0)
        degraded = summary.get("degraded", 0)
        
        # If tuning has clearly done more harm than good
        if degraded >= 2 and degraded > improved:
            issues.append({
                "type": "tuner_harm_warning",
                "symbols": [sym],
                "detail": f"Tuner self-eval: {sym} has {improved} improved vs {degraded} degraded tuning cycles; consider freezing tuning.",
            })
    
    return issues


def analyze(n: int = 5) -> Dict[str, Any]:
    """
    Analyze recent memory entries for contradictions and instability.
    
    Args:
        n: Number of recent memory entries to analyze (default: 5)
    
    Returns:
        Dictionary containing issues and recommendations.
    """
    memory_entries = load_recent_memory(n=n)
    
    if len(memory_entries) < 2:
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "issues": [],
            "recommendations": [
                "Insufficient memory entries for analysis. Run more cycles and take snapshots."
            ],
            "memory_entries_analyzed": len(memory_entries),
        }
    
    # Collect all issues
    issues = []
    issues.extend(_analyze_tier_instability(memory_entries))
    issues.extend(_analyze_contradictory_tuning(memory_entries))
    issues.extend(_analyze_reflection_tuner_disagreement(memory_entries))
    issues.extend(_analyze_tuner_harm())
    
    # Generate recommendations
    recommendations = []
    
    # Recommendations for tier instability
    tier_instability_symbols = [i["symbol"] for i in issues if i["type"] == "tier_instability"]
    if tier_instability_symbols:
        recommendations.append(
            f"Reduce tuning frequency for {', '.join(tier_instability_symbols)} until tiers stabilize."
        )
    
    # Recommendations for contradictory tuning
    contradictory_symbols = [i["symbol"] for i in issues if i["type"] == "contradictory_tuning"]
    if contradictory_symbols:
        recommendations.append(
            f"Require stronger evidence before tuning {', '.join(contradictory_symbols)}."
        )
    
    # Recommendations for disagreements
    disagreement_symbols = [i["symbol"] for i in issues if i["type"] == "reflection_tuner_disagreement"]
    if disagreement_symbols:
        recommendations.append(
            f"Review Reflection and Tuner logic for {', '.join(disagreement_symbols)} - they disagree on symbol strength."
        )
    
    # Recommendations for tuner harm
    tuner_harm_symbols = []
    for i in issues:
        if i["type"] == "tuner_harm_warning":
            tuner_harm_symbols.extend(i.get("symbols", []))
    if tuner_harm_symbols:
        recommendations.append(
            f"Freeze tuning for {', '.join(tuner_harm_symbols)} - tuner self-eval shows net harm."
        )
    
    # General recommendations if no specific issues
    if not recommendations:
        recommendations.append("No major contradictions detected. GPT outputs are consistent.")
    
    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "issues": issues,
        "recommendations": recommendations,
        "memory_entries_analyzed": len(memory_entries),
        "issue_count_by_type": {
            "tier_instability": len([i for i in issues if i["type"] == "tier_instability"]),
            "contradictory_tuning": len([i for i in issues if i["type"] == "contradictory_tuning"]),
            "reflection_tuner_disagreement": len([i for i in issues if i["type"] == "reflection_tuner_disagreement"]),
        },
    }
    
    # Write report
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    META_REASONER_REPORT_PATH.write_text(json.dumps(report, indent=2))
    
    return report

