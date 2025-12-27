"""
Symbol Edge Profiler - Hybrid Per-Symbol Optimization Engine (PSOE).

Computes hard-quant edge profiles per symbol, classifying them into archetypes
(trend_monster, fragile, mean_reverter, etc.) based on PF, drift, microstructure,
execution quality, and self-eval history.

These profiles are then exposed to GPT Tuner v4 and Reflection v4 to enable
symbol-specific tuning recommendations.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from engine_alpha.core.paths import REPORTS

ARE_PATH = REPORTS / "research" / "are_snapshot.json"

# Sample-size thresholds
MIN_EXPL_FOR_ARCHETYPE = 15  # Minimum exploration closes required for archetype classification
DRIFT_PATH = REPORTS / "research" / "drift_report.json"
MICRO_PATH = REPORTS / "research" / "microstructure_snapshot_15m.json"
EXEC_PATH = REPORTS / "research" / "execution_quality.json"
QUALITY_PATH = REPORTS / "gpt" / "quality_scores.json"
REFLECTION_PATH = REPORTS / "gpt" / "reflection_output.json"
SELF_EVAL_PATH = REPORTS / "research" / "tuning_self_eval.json"
ROTATION_PATH = REPORTS / "research" / "auto_rotation_recs.json"
PROFILE_PATH = REPORTS / "research" / "symbol_edge_profile.json"


def _load_json_or_empty(path: Path) -> Dict[str, Any]:
    """Load JSON file or return empty dict if missing/invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _classify_archetype(
    short_pf: Optional[float],
    long_pf: Optional[float],
    exec_label: str,
    micro_regime: str,
    drift_status: str,
    quality_score: Optional[float]
) -> str:
    """
    Classify symbol into an archetype based on quant metrics.
    
    Archetypes:
    - trend_monster: High PF, friendly execution, clean microstructure
    - fragile: Low PF, hostile execution, choppy microstructure
    - mean_reverter: Moderate PF, hostile execution, indecision microstructure
    - neutral_trender: Decent PF, neutral execution
    - unknown: Insufficient data
    """
    # Trend monster: High PF, friendly execution
    if short_pf is not None and short_pf > 2.0 and exec_label == "friendly":
        return "trend_monster"
    
    # Fragile: Low PF, hostile execution
    if short_pf is not None and short_pf < 0.8 and exec_label == "hostile":
        return "fragile"
    
    # Mean-reverter-ish: Moderate PF, hostile execution, indecision microstructure
    if (short_pf is not None and 0.5 < short_pf < 1.5 and 
        exec_label == "hostile" and micro_regime in ("indecision", "chop_noise")):
        return "mean_reverter"
    
    # Neutral trender: Decent PF, neutral execution
    if short_pf is not None and short_pf >= 1.0 and exec_label == "neutral":
        return "neutral_trender"
    
    # Strong but choppy: High PF but hostile microstructure
    if short_pf is not None and short_pf > 1.5 and exec_label == "hostile":
        return "strong_but_choppy"
    
    # Weak but improving: Low PF but improving drift
    if (short_pf is not None and short_pf < 1.0 and 
        drift_status == "improving" and exec_label != "hostile"):
        return "weak_but_improving"
    
    return "unknown"


def build_symbol_edge_profile() -> Dict[str, Dict[str, Any]]:
    """
    Build per-symbol edge profiles from all available research data.
    
    Returns:
        Dict mapping symbol -> edge profile dict
    """
    # Load trade counts for sample-size gating
    from engine_alpha.research.trade_stats import load_trade_counts
    trade_counts = load_trade_counts()
    
    # Load all research inputs
    are = _load_json_or_empty(ARE_PATH)
    are_symbols = are.get("symbols", are)
    
    drift = _load_json_or_empty(DRIFT_PATH).get("symbols", {})
    
    micro = _load_json_or_empty(MICRO_PATH)
    # Handle both formats: direct dict or wrapped with "symbols" key
    if isinstance(micro, dict) and "symbols" in micro:
        micro_symbols = micro.get("symbols", {})
    else:
        micro_symbols = micro
    
    execq = _load_json_or_empty(EXEC_PATH)
    quality = _load_json_or_empty(QUALITY_PATH)
    reflection = _load_json_or_empty(REFLECTION_PATH)
    tiers_data = reflection.get("tiers", {})
    
    self_eval = _load_json_or_empty(SELF_EVAL_PATH)
    auto_rot = _load_json_or_empty(ROTATION_PATH)
    
    # Extract tiers mapping
    tiers: Dict[str, str] = {}
    for tier_name, syms in tiers_data.items():
        if isinstance(syms, list):
            for s in syms:
                tiers[s] = tier_name
    
    self_summary = self_eval.get("summary", {})
    
    profiles: Dict[str, Dict[str, Any]] = {}
    
    # Build profile for each symbol found in ARE
    for sym, stats in are_symbols.items():
        if not isinstance(stats, dict):
            continue
        
        short_pf = stats.get("short_exp_pf")
        long_pf = stats.get("long_exp_pf")
        
        # Parse PF values
        try:
            spf = float(short_pf) if short_pf not in ("—", None, "N/A") else None
        except (ValueError, TypeError):
            spf = None
        
        try:
            lpf = float(long_pf) if long_pf not in ("—", None, "N/A") else None
        except (ValueError, TypeError):
            lpf = None
        
        # Get drift status
        d = drift.get(sym, {})
        drift_status = d.get("status", "insufficient_data")
        
        # Get microstructure regime
        micro_info = micro_symbols.get(sym, {})
        if isinstance(micro_info, dict):
            if "micro_regime" in micro_info:
                micro_regime = micro_info.get("micro_regime", "unknown")
            elif "metrics" in micro_info:
                micro_regime = micro_info.get("metrics", {}).get("micro_regime", "unknown")
            else:
                micro_regime = "unknown"
        else:
            micro_regime = "unknown"
        
        # Get execution quality label
        exec_info = execq.get(sym, {})
        exec_label = "unknown"
        if exec_info and isinstance(exec_info, dict):
            # Pick first regime's label
            for reg, info in exec_info.items():
                if isinstance(info, dict):
                    exec_label = info.get("label", "unknown")
                    if exec_label != "unknown":
                        break
        
        # Get quality score
        q = quality.get(sym, {})
        qual_score = q.get("score")
        
        # Get tier
        tier = tiers.get(sym, "unknown")
        
        # Get rotation recommendation
        rot = auto_rot.get(sym, {})
        if isinstance(rot, dict):
            rot_decision = rot.get("rotation", "hold")
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
        
        # Get sample counts
        counts = trade_counts.get(sym, {})
        expl = counts.get("exploration_closes", 0)
        normal_closes = counts.get("normal_closes", 0)
        total_closes = counts.get("total_closes", 0)
        
        # Check if under-sampled
        under_sampled = expl < MIN_EXPL_FOR_ARCHETYPE
        
        # Classify archetype (only if we have enough samples)
        if under_sampled:
            archetype = "under_sampled"
        else:
            archetype = _classify_archetype(
                spf, lpf, exec_label, micro_regime, drift_status, qual_score
            )
        
        profiles[sym] = {
            "tier": tier,
            "short_pf": short_pf,
            "long_pf": long_pf,
            "drift": drift_status,
            "micro_regime": micro_regime,
            "exec_label": exec_label,
            "quality_score": qual_score,
            "rotation": rot_decision,
            "self_eval": {
                "improved": improved,
                "degraded": degraded,
                "inconclusive": inconclusive,
            },
            "archetype": archetype,
            "samples": {
                "exploration_closes": expl,
                "normal_closes": normal_closes,
                "total_closes": total_closes,
            },
        }
    
    # Save profiles
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profiles": profiles,
    }
    
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(output, indent=2))
    
    return profiles


def load_symbol_edge_profiles() -> Dict[str, Dict[str, Any]]:
    """
    Load symbol edge profiles from disk.
    
    Returns:
        Dict mapping symbol -> edge profile dict
    """
    if not PROFILE_PATH.exists():
        return {}
    
    try:
        data = json.loads(PROFILE_PATH.read_text())
        # Handle both formats: direct dict or wrapped with "profiles" key
        if "profiles" in data:
            return data.get("profiles", {})
        return data
    except Exception:
        return {}

