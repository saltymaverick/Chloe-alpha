"""
Decay/half-life primitives for signal/confidence aging.

Computes exponential decay based on time-since-last-confirmation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from engine_alpha.core.primitive_state import update_last


def exp_decay(value: float | None, age_s: float | None, half_life_s: float) -> float | None:
    """
    Compute exponential half-life decay.
    
    Formula: value * 0.5 ** (age_s / half_life_s)
    
    Args:
        value: Previous confirmed value (or None)
        age_s: Age in seconds since last confirmation (or None)
        half_life_s: Half-life in seconds (must be > 0)
        
    Returns:
        Decayed value, or None if inputs invalid
    """
    if value is None or age_s is None:
        return None
    
    if half_life_s <= 0:
        return None
    
    try:
        decayed = value * (0.5 ** (age_s / half_life_s))
        return decayed
    except (TypeError, ValueError, OverflowError):
        return None


def age_seconds(prev_ts_iso: str | None, cur_ts_iso: str) -> float | None:
    """
    Compute age in seconds between two ISO timestamps.
    
    Args:
        prev_ts_iso: Previous ISO timestamp string (timezone-aware) or None
        cur_ts_iso: Current ISO timestamp string (timezone-aware)
        
    Returns:
        Age in seconds (>= 0), or None if invalid
    """
    if prev_ts_iso is None:
        return None
    
    try:
        # Parse ISO timestamps (timezone-aware)
        prev_dt = datetime.fromisoformat(prev_ts_iso.replace("Z", "+00:00"))
        cur_dt = datetime.fromisoformat(cur_ts_iso.replace("Z", "+00:00"))
        
        # Compute time delta in seconds
        dt_seconds = (cur_dt - prev_dt).total_seconds()
        
        # Return None for negative deltas (shouldn't happen, but be safe)
        if dt_seconds < 0:
            return None
        
        return dt_seconds
    except (ValueError, TypeError, AttributeError):
        # Invalid timestamp format
        return None


def compute_decays(
    ts_iso: str,
    current: Dict[str, float | None],
    state: Dict[str, Any],
    spec: Dict[str, Dict[str, float]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Compute decay bundle for given keys.
    
    Args:
        ts_iso: Current ISO timestamp string (timezone-aware)
        current: Dict of current scalar values, e.g., {"pci": 0.62, "confidence": 0.71}
        state: Previous state dict (from primitive_state.json)
        spec: Per-key configuration, e.g.:
            {
                "pci": {"half_life_s": 900},
                "confidence": {"half_life_s": 1800},
            }
        
    Returns:
        Tuple of (decays_dict, updated_state)
        - decays_dict: {
            "pci_age_s": 120.5,
            "pci_half_life_s": 900,
            "pci_decayed": 0.58,
            "pci_prev": 0.60,
            "confidence_age_s": 300.0,
            ...
          }
        - updated_state: State dict after updating with current values
    """
    decays: Dict[str, Any] = {}
    updated_state = dict(state)  # Work on a copy
    
    for key, key_spec in spec.items():
        half_life_s = key_spec.get("half_life_s")
        if half_life_s is None or half_life_s <= 0:
            continue
        
        # Get previous state for this key (always try to compute decay from state)
        prev_entry = state.get(key) or {}
        prev_ts_iso = prev_entry.get("ts") if isinstance(prev_entry, dict) else None
        prev_val = prev_entry.get("value") if isinstance(prev_entry, dict) else None
        
        # Compute age from previous timestamp to current
        age_s = age_seconds(prev_ts_iso, ts_iso)
        
        # Always store age and half-life (even if None)
        decays[f"{key}_age_s"] = age_s
        decays[f"{key}_half_life_s"] = half_life_s
        
        # Compute decayed value (based on previous confirmed value aging forward)
        # This works even if current[key] is missing - decay is about trust degradation over time
        if prev_val is not None and age_s is not None:
            decayed = exp_decay(prev_val, age_s, half_life_s)
            decays[f"{key}_decayed"] = decayed
        else:
            decays[f"{key}_decayed"] = None
        
        # Always store previous value (for reference)
        decays[f"{key}_prev"] = prev_val
        
        # Track whether this key was refreshed (fresh observation resets trust)
        cur_val = current.get(key)
        if cur_val is not None:
            decays[f"{key}_refreshed"] = True
            update_last(updated_state, key, ts_iso, cur_val)
        else:
            decays[f"{key}_refreshed"] = False
    
    return decays, updated_state

