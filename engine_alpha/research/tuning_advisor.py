"""
Per-Symbol Tuning Advisor - Synthesizes all research intelligence into per-symbol recommendations.

This module reads all research outputs (edge profiles, self-eval, rotation, trade counts)
and produces a single, human-readable per-symbol recommendation:
- "relax": Allow slightly looser tuning (for strong symbols with good execution)
- "tighten": Keep tightening or restrict trading (for weak symbols with hostile execution)
- "freeze": Stop tuning (for symbols where tuning has been harmful)
- "observe": Keep watching and learning (for under-sampled or mixed signals)

All recommendations are advisory-only and respect sample-size gating.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List

from engine_alpha.core.paths import REPORTS
from engine_alpha.research.trade_stats import load_trade_counts

EDGE_PROFILE_PATH = REPORTS / "research" / "symbol_edge_profile.json"
SELF_EVAL_PATH = REPORTS / "research" / "tuning_self_eval.json"
ROTATION_PATH = REPORTS / "research" / "auto_rotation_recs.json"
ADVISOR_PATH = REPORTS / "research" / "tuning_advisor.json"


def _load_json_or_empty(path: Path) -> Dict[str, Any]:
    """Load JSON file or return empty dict if missing/invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def build_tuning_advisor() -> Dict[str, Dict[str, Any]]:
    """
    Build per-symbol tuning advisor recommendations from all research outputs.
    
    Returns:
        Dict mapping symbol -> advisor dict with recommendation, reasons, and context
    """
    # Load edge profiles (contains archetype, tier, PF, drift, exec quality, samples)
    edge_profile_data = _load_json_or_empty(EDGE_PROFILE_PATH)
    if "profiles" in edge_profile_data:
        edge_profiles = edge_profile_data.get("profiles", {})
    else:
        edge_profiles = edge_profile_data
    
    # Load self-eval summary
    self_eval_data = _load_json_or_empty(SELF_EVAL_PATH)
    self_summary = self_eval_data.get("summary", {})
    
    # Load rotation recommendations
    rotation = _load_json_or_empty(ROTATION_PATH)
    
    # Load trade counts (for sample-size verification)
    trade_counts = load_trade_counts()
    
    advisor: Dict[str, Dict[str, Any]] = {}
    
    for sym, profile in edge_profiles.items():
        if not isinstance(profile, dict):
            continue
        
        samples = profile.get("samples", {})
        expl = samples.get("exploration_closes", 0)
        tier = profile.get("tier", "unknown")
        archetype = profile.get("archetype", "unknown")
        exec_label = profile.get("exec_label", "unknown")
        drift = profile.get("drift", "insufficient_data")
        short_pf = profile.get("short_pf")
        long_pf = profile.get("long_pf")
        qual_score = profile.get("quality_score")
        
        rot_info = rotation.get(sym, {})
        if isinstance(rot_info, dict):
            rot_decision = rot_info.get("rotation", "hold")
        else:
            rot_decision = "hold"
        
        # Get self-eval summary
        se = self_summary.get(sym, {})
        if isinstance(se, dict):
            improved = se.get("improved", 0)
            degraded = se.get("degraded", 0)
            inconclusive = se.get("inconclusive", 0)
        else:
            improved = degraded = inconclusive = 0
        
        rec = "observe"
        reasons: List[str] = []
        
        # Sample-size gating (first priority)
        if expl < 10:
            rec = "observe"
            reasons.append(f"Under-sampled: exploration_closes={expl} < 10")
        else:
            # Self-eval gating (second priority)
            if degraded >= 2 and improved == 0:
                rec = "freeze"
                reasons.append(f"Self-eval: degraded={degraded} > improved={improved}; freeze tuning.")
            elif degraded > improved:
                rec = "freeze"
                reasons.append(f"Self-eval: net negative (degraded={degraded} > improved={improved}); freeze tuning.")
            else:
                # Archetype and PF-based advice (third priority)
                try:
                    spf = float(short_pf) if short_pf not in ("—", None, "N/A") else None
                except (ValueError, TypeError):
                    spf = None
                
                # Strong symbol with good execution -> relax
                if tier == "tier1" and spf is not None and spf > 2.0 and exec_label == "friendly":
                    rec = "relax"
                    reasons.append("Tier1 & strong PF (>2.0) & friendly execution; allow slightly looser tuning.")
                # Strong symbol but moderate PF -> observe
                elif tier == "tier1" and spf is not None and spf > 1.5 and exec_label in ("friendly", "neutral"):
                    rec = "observe"
                    reasons.append("Tier1 & good PF but not exceptional; continue observing.")
                # Weak symbol with hostile execution -> tighten
                elif tier == "tier3" and (spf is None or (spf is not None and spf < 1.0)) and exec_label == "hostile":
                    rec = "tighten"
                    reasons.append("Tier3 & weak PF & hostile execution; keep tightening or restrict trading.")
                # Fragile archetype -> tighten
                elif archetype == "fragile":
                    rec = "tighten"
                    reasons.append("Fragile archetype; maintain strict gates.")
                # Mean-reverter -> observe/tighten
                elif archetype == "mean_reverter":
                    rec = "observe"
                    reasons.append("Mean-reverter archetype; be cautious with loosening.")
                # Trend monster -> relax
                elif archetype == "trend_monster":
                    rec = "relax"
                    reasons.append("Trend monster archetype; allow slightly looser tuning.")
                # Under-sampled archetype -> observe
                elif archetype == "under_sampled":
                    rec = "observe"
                    reasons.append("Under-sampled archetype; need more data.")
                # Default: observe
                else:
                    rec = "observe"
                    reasons.append("Mixed signals; keep observing.")
            
            # Rotation hints (informational, doesn't change recommendation)
            if rot_decision == "overweight":
                reasons.append("Rotation: overweight candidate.")
            elif rot_decision == "underweight":
                reasons.append("Rotation: underweight candidate.")
            
            # Drift hints (informational)
            if drift == "improving":
                reasons.append("Drift: improving trend.")
            elif drift == "degrading":
                reasons.append("Drift: degrading trend; be cautious.")
        
        advisor[sym] = {
            "recommendation": rec,  # "relax", "tighten", "freeze", "observe"
            "reasons": reasons,
            "samples": {
                "exploration_closes": expl,
                "normal_closes": samples.get("normal_closes", 0),
                "total_closes": samples.get("total_closes", 0),
            },
            "tier": tier,
            "archetype": archetype,
            "exec_label": exec_label,
            "drift": drift,
            "short_pf": short_pf,
            "long_pf": long_pf,
            "quality_score": qual_score,
            "self_eval": {
                "improved": improved,
                "degraded": degraded,
                "inconclusive": inconclusive,
            },
            "rotation": rot_decision,
        }
    
    # Save advisor output
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "advisor": advisor,
    }
    
    ADVISOR_PATH.parent.mkdir(parents=True, exist_ok=True)
    ADVISOR_PATH.write_text(json.dumps(output, indent=2))
    
    return advisor


def load_tuning_advisor() -> Dict[str, Dict[str, Any]]:
    """
    Load tuning advisor recommendations from disk.
    
    Returns:
        Dict mapping symbol -> advisor dict
    """
    if not ADVISOR_PATH.exists():
        return {}
    
    try:
        data = json.loads(ADVISOR_PATH.read_text())
        # Handle both formats: direct dict or wrapped with "advisor" key
        if "advisor" in data:
            return data.get("advisor", {})
        return data
    except Exception:
        return {}

