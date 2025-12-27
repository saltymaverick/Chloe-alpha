"""
Paper Tuning Overrides - Safe auto-tuning for Tier1 symbols in PAPER mode only.

This module provides a controlled way to apply small tuning adjustments automatically
based on tuner v4 recommendations, but only for Tier1 symbols with strong evidence
(friendly execution, improving drift, overweight/hold rotation).

All overrides are stored in config/paper_tuning_overrides.json and are ONLY
consumed in PAPER mode. LIVE mode ignores them completely.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from engine_alpha.core.paths import CONFIG

OVERRIDES_PATH = CONFIG / "paper_tuning_overrides.json"


def load_overrides() -> Dict[str, Dict[str, Any]]:
    """
    Load paper tuning overrides from disk.
    
    Returns:
        Dict mapping symbol -> override config
    """
    if not OVERRIDES_PATH.exists():
        return {}
    
    try:
        return json.loads(OVERRIDES_PATH.read_text())
    except Exception:
        return {}


def save_overrides(data: Dict[str, Dict[str, Any]]) -> Path:
    """
    Save paper tuning overrides to disk.
    
    Args:
        data: Overrides dict
    
    Returns:
        Path to saved file
    """
    # Add metadata
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_ONLY",
        "overrides": data,
    }
    
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDES_PATH.write_text(json.dumps(output, indent=2))
    return OVERRIDES_PATH


def get_symbol_override(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Get override for a specific symbol.
    
    Args:
        symbol: Symbol ID (e.g., "ETHUSDT")
    
    Returns:
        Override dict or None if not found
    """
    overrides_data = load_overrides()
    if isinstance(overrides_data, dict):
        # Handle both formats: direct dict or wrapped with "overrides" key
        if "overrides" in overrides_data:
            overrides = overrides_data.get("overrides", {})
        else:
            overrides = overrides_data
        return overrides.get(symbol)
    return None


def apply_tuner_recommendations(
    tuner_output: Dict[str, Any],
    tiers: Dict[str, str],
    rotation_recs: Dict[str, Any]
) -> Dict[str, Dict[str, Any]]:
    """
    Apply tuner recommendations as paper-only overrides, with strict filtering.
    
    Rules:
    - Only apply for tier1 symbols
    - Only apply if rotation is 'overweight' or 'hold' (not underweight)
    - Only apply if conf_min_delta is within [-0.02, 0.02]
    - Only apply if exploration_cap_delta is within [-1, 1]
    - Merge with existing overrides (accumulate slowly, don't jump)
    
    Args:
        tuner_output: Parsed JSON from reports/gpt/tuner_output.json
        tiers: Mapping symbol -> 'tier1'/'tier2'/'tier3'
        rotation_recs: From auto_rotation_recs.json (symbol -> rotation info)
    
    Returns:
        Updated overrides dict
    """
    # Load existing overrides
    existing_data = load_overrides()
    if isinstance(existing_data, dict) and "overrides" in existing_data:
        new_overrides = existing_data.get("overrides", {}).copy()
    else:
        new_overrides = existing_data.copy() if isinstance(existing_data, dict) else {}
    
    proposals = tuner_output.get("proposals", {})
    
    if not proposals:
        return new_overrides
    
    applied_count = 0
    
    for sym, props in proposals.items():
        # Filter: Tier1 only
        tier = tiers.get(sym)
        if tier != "tier1":
            continue
        
        # Filter: Rotation must be overweight or hold (not underweight)
        rot_info = rotation_recs.get(sym, {})
        if isinstance(rot_info, dict):
            rot = rot_info.get("rotation", "hold")
        else:
            rot = "hold"
        
        if rot == "underweight":
            continue
        
        # Extract deltas
        try:
            delta_conf = float(props.get("conf_min_delta", 0.0))
            delta_cap = int(props.get("exploration_cap_delta", 0))
        except (ValueError, TypeError):
            continue
        
        # Filter: Only small deltas
        if not (-0.02 <= delta_conf <= 0.02):
            continue
        if not (-1 <= delta_cap <= 1):
            continue
        
        # Get existing override or create new
        override = new_overrides.get(sym, {
            "conf_min_delta": 0.0,
            "exploration_cap_delta": 0,
            "notes": [],
        })
        
        # Accumulate deltas (merge with existing)
        override["conf_min_delta"] += delta_conf
        override["exploration_cap_delta"] += delta_cap
        
        # Clamp accumulated overrides to safe bounds
        override["conf_min_delta"] = max(-0.05, min(0.05, override["conf_min_delta"]))
        override["exploration_cap_delta"] = max(-3, min(3, override["exploration_cap_delta"]))
        
        # Add note
        note = f"Applied {delta_conf:+.3f}/{delta_cap:+d} from tuner v4 ({datetime.now(timezone.utc).isoformat()})"
        if "notes" not in override:
            override["notes"] = []
        override["notes"].append(note)
        # Keep only last 5 notes
        override["notes"] = override["notes"][-5:]
        
        new_overrides[sym] = override
        applied_count += 1
    
    # Save updated overrides
    save_overrides(new_overrides)
    
    return new_overrides

