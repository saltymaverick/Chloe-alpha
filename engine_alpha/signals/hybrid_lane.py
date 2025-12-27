"""
Aggressive Hybrid Lane Engine - Phase 11

Uses symbol-level intelligence to boost normal-lane confidence for strong symbols
in strong conditions. PAPER-only, advisory-only, fully bounded by safety gates.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Tuple, List

from engine_alpha.core.paths import REPORTS

EDGE_PROFILE_PATH = REPORTS / "research" / "symbol_edge_profile.json"
TUNING_ADVISOR_PATH = REPORTS / "research" / "tuning_advisor.json"
SCM_STATE_PATH = REPORTS / "research" / "scm_state.json"
SELF_EVAL_PATH = REPORTS / "research" / "tuning_self_eval.json"
LIQ_SWEEPS_PATH = REPORTS / "research" / "liquidity_sweeps.json"
VOL_IMB_PATH = REPORTS / "research" / "volume_imbalance.json"
MSTRUCT_PATH = REPORTS / "research" / "market_structure.json"

_edge_profiles_cache: dict | None = None
_tuning_advisor_cache: dict | None = None
_scm_state_cache: dict | None = None
_self_eval_cache: dict | None = None
_liq_cache: dict | None = None
_vi_cache: dict | None = None
_ms_cache: dict | None = None


def _load_json_or_empty(path: Path) -> dict:
    """Load JSON file or return empty dict if missing/invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def load_edge_profiles() -> dict:
    """Load and cache edge profiles."""
    global _edge_profiles_cache
    if _edge_profiles_cache is None:
        data = _load_json_or_empty(EDGE_PROFILE_PATH)
        # Handle both formats: direct dict or wrapped with "profiles" key
        if "profiles" in data:
            _edge_profiles_cache = data.get("profiles", {})
        else:
            _edge_profiles_cache = data
    return _edge_profiles_cache


def load_tuning_advisor() -> dict:
    """Load and cache tuning advisor."""
    global _tuning_advisor_cache
    if _tuning_advisor_cache is None:
        data = _load_json_or_empty(TUNING_ADVISOR_PATH)
        # Handle both formats: direct dict or wrapped with "advisor" key
        if "advisor" in data:
            _tuning_advisor_cache = data.get("advisor", {})
        else:
            _tuning_advisor_cache = data
    return _tuning_advisor_cache


def load_scm_state() -> dict:
    """Load and cache SCM state."""
    global _scm_state_cache
    if _scm_state_cache is None:
        data = _load_json_or_empty(SCM_STATE_PATH)
        # Handle both formats: direct dict or wrapped with "state" key
        if "state" in data:
            _scm_state_cache = data.get("state", {})
        else:
            _scm_state_cache = data
    return _scm_state_cache


def load_self_eval_summary() -> dict:
    """Load and cache self-eval summary."""
    global _self_eval_cache
    if _self_eval_cache is None:
        data = _load_json_or_empty(SELF_EVAL_PATH)
        _self_eval_cache = data.get("summary", {})
    return _self_eval_cache


def load_liquidity_sweeps() -> dict:
    """Load and cache liquidity sweeps data."""
    global _liq_cache
    if _liq_cache is None:
        data = _load_json_or_empty(LIQ_SWEEPS_PATH)
        if "symbols" in data:
            _liq_cache = data.get("symbols", {})
        else:
            _liq_cache = data
    return _liq_cache


def load_volume_imbalance() -> dict:
    """Load and cache volume imbalance data."""
    global _vi_cache
    if _vi_cache is None:
        data = _load_json_or_empty(VOL_IMB_PATH)
        if "symbols" in data:
            _vi_cache = data.get("symbols", {})
        else:
            _vi_cache = data
    return _vi_cache


def load_market_structure() -> dict:
    """Load and cache market structure data."""
    global _ms_cache
    if _ms_cache is None:
        data = _load_json_or_empty(MSTRUCT_PATH)
        if "symbols" in data:
            _ms_cache = data.get("symbols", {})
        else:
            _ms_cache = data
    return _ms_cache


def compute_hybrid_confidence_boost(symbol: str, base_conf: float) -> Tuple[float, List[str]]:
    """
    Aggressive Hybrid mode:
    
    - Only applies when:
      - Tier1
      - Exec friendly or neutral
      - Drift improving or stable
      - SCM level not 'off'
      - Exploration PF > 2.0
      - exploration_closes >= 15
      - Tuning advisor not 'freeze'
      - Self-eval not net-harmful
    
    - Boost range: +0.00 to +0.08
    - Still clamped to [0, 1] in caller.
    
    Returns:
        (boost_amount, notes_list)
    """
    notes: List[str] = []
    boost = 0.0
    
    edge_profiles = load_edge_profiles()
    advisor = load_tuning_advisor()
    scm = load_scm_state()
    self_eval = load_self_eval_summary()
    
    profile = edge_profiles.get(symbol.upper(), {})
    if not profile:
        notes.append("no edge profile; no hybrid boost")
        return boost, notes
    
    tier = profile.get("tier", "unknown")
    exec_label = profile.get("exec_label", "neutral")
    drift = profile.get("drift", "insufficient_data")
    short_pf = profile.get("short_pf")
    samples = profile.get("samples", {})
    expl_closes = samples.get("exploration_closes", 0)
    archetype = profile.get("archetype", "under_sampled")
    
    # Advisor
    adv = advisor.get(symbol.upper(), {})
    adv_rec = adv.get("recommendation", "observe")
    
    # SCM
    scm_info = scm.get(symbol.upper(), {})
    scm_level = scm_info.get("scm_level", "normal")
    
    # Self-eval
    se = self_eval.get(symbol.upper(), {})
    improved = se.get("improved", 0)
    degraded = se.get("degraded", 0)
    
    # Sample-size gate
    if expl_closes < 15:
        notes.append(f"exploration_closes={expl_closes} < 15; no hybrid boost")
        return boost, notes
    
    # Self-eval harm gate
    if degraded >= 2 and improved == 0:
        notes.append(f"self-eval net harm (improved={improved}, degraded={degraded}); no hybrid boost")
        return boost, notes
    
    # Tier gate
    if tier != "tier1":
        notes.append(f"tier={tier}; hybrid is aggressive only for tier1")
        return boost, notes
    
    # Exec quality gate
    if exec_label not in ("friendly", "neutral"):
        notes.append(f"exec_label={exec_label}; not suitable for aggressive hybrid")
        return boost, notes
    
    # Drift gate
    if drift not in ("improving", "stable"):
        notes.append(f"drift={drift}; not suitable for aggressive hybrid")
        return boost, notes
    
    # SCM gate
    if scm_level == "off":
        notes.append("SCM level=off; no hybrid boost")
        return boost, notes
    
    # PF gate
    try:
        spf = float(short_pf) if short_pf not in ("—", None) else None
    except Exception:
        spf = None
    
    if spf is None or spf <= 2.0:
        notes.append(f"short_pf={short_pf}; requires PF > 2.0 for aggressive hybrid")
        return boost, notes
    
    # Advisor gate
    if adv_rec == "freeze":
        notes.append("advisor: freeze; no hybrid boost")
        return boost, notes
    
    # At this point, symbol is strong and conditions are favorable.
    # Compute boost size: up to +0.08, scaled by PF and SCM level.
    
    base_boost = 0.04  # baseline +0.04
    
    # PF scaling: ETH/strong coins get a bit more (capped)
    extra_pf = min(max(spf - 2.0, 0.0), 3.0)  # up to +3 PF above threshold
    pf_scale = extra_pf / 3.0  # 0.0–1.0
    pf_boost = 0.04 * pf_scale  # up to +0.04
    
    # SCM scaling
    if scm_level == "high":
        scm_boost = 0.02
    elif scm_level == "normal":
        scm_boost = 0.01
    else:  # low
        scm_boost = 0.0
    
    boost = base_boost + pf_boost + scm_boost  # nominally up to ~0.10
    
    # Phase 12: Add ASE-based boosts
    liq = load_liquidity_sweeps()
    vi = load_volume_imbalance()
    ms = load_market_structure()
    
    liq_info = liq.get(symbol.upper(), {})
    vi_info = vi.get(symbol.upper(), {})
    ms_info = ms.get(symbol.upper(), {})
    
    # Liquidity sweep strength boost
    sweep_strength = liq_info.get("strength", 0.0)
    if sweep_strength > 0.7:
        boost += 0.02
        notes.append(f"liquidity sweep strength={sweep_strength:.2f} → +0.02 boost")
    
    # Volume imbalance strength boost
    imb_strength = vi_info.get("imbalance_strength", 0.0)
    if imb_strength > 0.6:
        boost += 0.02
        notes.append(f"volume imbalance strength={imb_strength:.2f} → +0.02 boost")
    
    # Market structure confidence boost
    struct_conf = ms_info.get("structure_confidence")
    if struct_conf is not None and struct_conf > 0.6:
        boost += 0.02
        notes.append(f"market structure confidence={struct_conf:.2f} → +0.02 boost")
    
    # Hard cap aggressive hybrid boost
    boost = min(boost, 0.08)
    
    notes.append(f"hybrid boost={boost:.3f} (base={base_boost:.3f}, pf_boost={pf_boost:.3f}, scm_boost={scm_boost:.3f})")
    notes.append(f"tier={tier}, exec_label={exec_label}, drift={drift}, short_pf={short_pf}, archetype={archetype}")
    notes.append(f"scm_level={scm_level}, adv_rec={adv_rec}, expl_closes={expl_closes}, self_eval_improved={improved}, degraded={degraded}")
    
    return boost, notes

