"""
Sample Collection Mode (SCM) Controller - Automatic exploration intensity adjustment.

SCM adjusts exploration sampling intensity per symbol based on:
- Tier, PF, drift, execution quality, microstructure
- Sample size, tuning self-eval, tuning advisor recommendations

All adjustments are PAPER-only and advisory-only.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any

from engine_alpha.core.paths import REPORTS
from engine_alpha.research.trade_stats import load_trade_counts

EDGE_PROFILE_PATH = REPORTS / "research" / "symbol_edge_profile.json"
TUNING_ADVISOR_PATH = REPORTS / "research" / "tuning_advisor.json"
SELF_EVAL_PATH = REPORTS / "research" / "tuning_self_eval.json"
SCM_STATE_PATH = REPORTS / "research" / "scm_state.json"
LIQ_SWEEPS_PATH = REPORTS / "research" / "liquidity_sweeps.json"
VOL_IMB_PATH = REPORTS / "research" / "volume_imbalance.json"
MSTRUCT_PATH = REPORTS / "research" / "market_structure.json"

# Thresholds
MIN_SAMPLES_LOW = 8      # below this, we need more sample
MIN_SAMPLES_MED = 20     # mid-range
TARGET_SAMPLES_HIGH = 40  # above this, we can slow down


def _load_json_or_empty(path: Path) -> Dict[str, Any]:
    """Load JSON file or return empty dict if missing/invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def compute_scm_state() -> Dict[str, Dict[str, Any]]:
    """
    Compute SCM state for all symbols.
    
    Returns:
        Dict mapping symbol -> SCM state dict with level, reasons, and context
    """
    # Load edge profiles (contains tier, archetype, drift, exec_label, samples, etc.)
    edge_profile_data = _load_json_or_empty(EDGE_PROFILE_PATH)
    if "profiles" in edge_profile_data:
        edge_profiles = edge_profile_data.get("profiles", {})
    else:
        edge_profiles = edge_profile_data
    
    # Load tuning advisor
    tuning_advisor_data = _load_json_or_empty(TUNING_ADVISOR_PATH)
    if "advisor" in tuning_advisor_data:
        tuning_advisor = tuning_advisor_data.get("advisor", {})
    else:
        tuning_advisor = tuning_advisor_data
    
    # Load self-eval summary
    self_eval_data = _load_json_or_empty(SELF_EVAL_PATH)
    self_summary = self_eval_data.get("summary", {})
    
    # Load trade counts for verification
    trade_counts = load_trade_counts()
    
    # Phase 4L+: Load capital plan for exploit-intent handshake
    CAPITAL_PLAN_PATH = REPORTS / "risk" / "capital_plan.json"
    capital_plan = _load_json_or_empty(CAPITAL_PLAN_PATH)
    symbols_plan = capital_plan.get("symbols", {})
    
    # Load exploration policy for blocked status check
    POLICY_PATH = REPORTS / "research" / "exploration_policy_v3.json"
    policy = _load_json_or_empty(POLICY_PATH)
    symbols_policy = policy.get("symbols", {})
    
    # Phase 12: Load ASE data
    liq_sweeps_data = _load_json_or_empty(LIQ_SWEEPS_PATH)
    liq_sweeps = liq_sweeps_data.get("symbols", {}) if "symbols" in liq_sweeps_data else liq_sweeps_data
    
    vol_imb_data = _load_json_or_empty(VOL_IMB_PATH)
    vol_imb = vol_imb_data.get("symbols", {}) if "symbols" in vol_imb_data else vol_imb_data
    
    mkt_struct_data = _load_json_or_empty(MSTRUCT_PATH)
    mkt_struct = mkt_struct_data.get("symbols", {}) if "symbols" in mkt_struct_data else mkt_struct_data
    
    state: Dict[str, Dict[str, Any]] = {}
    
    for sym, profile in edge_profiles.items():
        if not isinstance(profile, dict):
            continue
        
        # Base data
        samples = profile.get("samples", {})
        expl = samples.get("exploration_closes", 0)
        tier = profile.get("tier", "unknown")
        exec_label = profile.get("exec_label", "unknown")
        drift = profile.get("drift", "insufficient_data")
        archetype = profile.get("archetype", "under_sampled")
        short_pf = profile.get("short_pf")
        rotation = profile.get("rotation", "hold")
        
        advisor_info = tuning_advisor.get(sym, {})
        rec = advisor_info.get("recommendation", "observe")
        
        se = self_summary.get(sym, {})
        if isinstance(se, dict):
            improved = se.get("improved", 0)
            degraded = se.get("degraded", 0)
        else:
            improved = degraded = 0
        
        # Decide SCM sampling level per symbol: low / normal / high / off
        level = "normal"
        reasons: list[str] = []
        
        # Tier3 & hostile execution: low or off
        if tier == "tier3" and exec_label == "hostile":
            if expl >= MIN_SAMPLES_LOW:
                level = "off"
                reasons.append("tier3 + hostile exec + enough samples: turn off SCM sampling")
            else:
                level = "low"
                reasons.append("tier3 + hostile exec: minimal sampling")
        else:
            # Under-sampled: increase sampling if symbol is not trash
            if expl < MIN_SAMPLES_LOW:
                level = "high"
                reasons.append(f"exploration_closes={expl} < {MIN_SAMPLES_LOW}: high sampling priority")
            elif expl < MIN_SAMPLES_MED:
                level = "normal"
                reasons.append(f"exploration_closes={expl} < {MIN_SAMPLES_MED}: normal sampling")
            elif expl < TARGET_SAMPLES_HIGH:
                level = "low"
                reasons.append(f"exploration_closes={expl} >= {MIN_SAMPLES_MED}: taper sampling")
            else:
                level = "off"
                reasons.append(f"exploration_closes={expl} >= {TARGET_SAMPLES_HIGH}: sampling completed")
            
            # Execution and drift refine level
            if exec_label == "friendly" and drift in ("improving", "stable") and level != "off":
                if level == "normal":
                    level = "high"
                    reasons.append("friendly exec + good drift: bump to high sampling")
            
            if drift == "degrading" and level != "off":
                level = "low"
                reasons.append("degrading drift: reduce sampling level")
            
            # Tuning advisor & self-eval hints
            if rec == "freeze":
                level = "off"
                reasons.append("tuning advisor: freeze; SCM off")
            elif rec == "tighten" and level == "high":
                level = "normal"
                reasons.append("advisor: tighten; reduce from high to normal")
            
            if degraded >= 2 and improved == 0:
                level = "off"
                reasons.append("self-eval: net harmful tuning; SCM off")
            
            # Phase 12: ASE-based SCM adjustments
            liq_info = liq_sweeps.get(sym, {})
            vi_info = vol_imb.get(sym, {})
            ms_info = mkt_struct.get(sym, {})
            
            sweep_strength = liq_info.get("strength", 0.0)
            struct_conf = ms_info.get("structure_confidence")
            imb_strength = vi_info.get("imbalance_strength", 0.0)
            absorption = vi_info.get("absorption_count", 0) > 0
            exhaustion = vi_info.get("exhaustion_count", 0) > 0
            
            # Strong structure + sweeps: boost to high
            if sweep_strength > 0.7 and struct_conf is not None and struct_conf > 0.6 and level != "off":
                if level in ("low", "normal"):
                    level = "high"
                    reasons.append(f"ASE: sweep_strength={sweep_strength:.2f} + structure_conf={struct_conf:.2f} → high sampling")
            
            # Absorption/exhaustion: reduce sampling
            if (absorption or exhaustion) and level != "off":
                if level == "high":
                    level = "normal"
                    reasons.append("ASE: absorption/exhaustion detected → reduce from high to normal")
                elif level == "normal":
                    level = "low"
                    reasons.append("ASE: absorption/exhaustion detected → reduce from normal to low")
            
            # Positive sweep + delta: maintain or boost
            if sweep_strength > 0.5 and imb_strength > 0.0 and level != "off":
                if level == "normal":
                    level = "high"
                    reasons.append(f"ASE: sweep_strength={sweep_strength:.2f} + positive delta → boost to high")
            
            # Low structure confidence: reduce sampling
            if struct_conf is not None and struct_conf < 0.3 and level != "off":
                if level == "high":
                    level = "normal"
                    reasons.append(f"ASE: low structure_conf={struct_conf:.2f} → reduce from high to normal")
                elif level == "normal":
                    level = "low"
                    reasons.append(f"ASE: low structure_conf={struct_conf:.2f} → reduce from normal to low")
        
        # Phase 4L+: SCM ↔ Exploit handshake
        # If symbol is exploit-intent and has meaningful capital weight, ensure SCM is not "off"
        symbol_plan = symbols_plan.get(sym, {})
        lane_intent = symbol_plan.get("lane_intent")
        capital_weight = symbol_plan.get("weight", 0.0)
        
        symbol_pol = symbols_policy.get(sym, {})
        policy_level = symbol_pol.get("level")
        allow_new_entries = symbol_pol.get("allow_new_entries", True)
        is_blocked = (policy_level == "blocked") or (allow_new_entries is False)
        
        if lane_intent == "exploit" and capital_weight >= 0.15 and not is_blocked:
            # Exploit-intent symbol with meaningful weight: ensure SCM is at least "low"
            if level == "off":
                level = "low"
                reasons.append(f"Phase 4L+: exploit-intent (weight={capital_weight:.3f}) → set SCM to low (was off)")
            # Do NOT promote to "normal" or "high" - only ensure it's not "off"
        
        state[sym] = {
            "scm_level": level,  # "off", "low", "normal", "high"
            "reasons": reasons,
            "samples": {
                "exploration_closes": expl,
                "normal_closes": samples.get("normal_closes", 0),
                "total_closes": samples.get("total_closes", 0),
            },
            "tier": tier,
            "exec_label": exec_label,
            "drift": drift,
            "archetype": archetype,
            "rotation": rotation,
            "tuning_rec": rec,
            "self_eval": {
                "improved": improved,
                "degraded": degraded,
            },
        }
    
    # Save SCM state
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
    }
    
    SCM_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCM_STATE_PATH.write_text(json.dumps(output, indent=2))
    
    return state


def load_scm_state() -> Dict[str, Dict[str, Any]]:
    """
    Load SCM state from disk.
    
    Returns:
        Dict mapping symbol -> SCM state dict
    """
    if not SCM_STATE_PATH.exists():
        return {}
    
    try:
        data = json.loads(SCM_STATE_PATH.read_text())
        # Handle both formats: direct dict or wrapped with "state" key
        if "state" in data:
            return data.get("state", {})
        return data
    except Exception:
        return {}

