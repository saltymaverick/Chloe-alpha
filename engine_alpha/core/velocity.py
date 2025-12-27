"""
Velocity computation for primitives.

Computes rate of change (velocity) for scalar primitives over time.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from engine_alpha.core.primitive_state import (
    compute_velocity,
    load_state,
    save_state,
    update_last,
)


def compute_velocities(
    ts_iso: str,
    current: Dict[str, float | None],
    state: Dict[str, Any],
    keys: List[str],
) -> Tuple[Dict[str, float | None], Dict[str, Any]]:
    """
    Compute velocities for given keys and update state.
    
    Args:
        ts_iso: Current ISO timestamp string (timezone-aware)
        current: Dict of current scalar values, e.g., {"pci": 0.62, "confidence": 0.71}
        state: Previous state dict (will be updated)
        keys: List of keys to compute velocities for
        
    Returns:
        Tuple of (velocities_dict, updated_state)
        - velocities_dict: {"pci_per_s": 0.02, "confidence_per_s": -0.01, ...}
        - updated_state: State dict after updating with current values
    """
    velocities: Dict[str, float | None] = {}
    updated_state = dict(state)  # Work on a copy
    
    for key in keys:
        # Get current value
        cur_val = current.get(key)
        
        # Get previous state for this key
        prev_entry = state.get(key)
        prev_ts_iso = prev_entry.get("ts") if isinstance(prev_entry, dict) else None
        prev_val = prev_entry.get("value") if isinstance(prev_entry, dict) else None
        
        # Compute velocity
        velocity = compute_velocity(prev_ts_iso, prev_val, ts_iso, cur_val)
        
        # Store velocity with "{key}_per_s" naming
        velocity_key = f"{key}_per_s"
        velocities[velocity_key] = velocity
        
        # Update state even if velocity is None (so future ticks have prev)
        if cur_val is not None:
            update_last(updated_state, key, ts_iso, cur_val)
    
    return velocities, updated_state

