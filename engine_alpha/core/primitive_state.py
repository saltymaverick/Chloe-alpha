"""
Primitive state management for velocity computation.

Maintains a rolling state file with last known values and timestamps
for computing velocity (rate of change over time).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from engine_alpha.core.atomic_io import atomic_write_json
from engine_alpha.core.paths import REPORTS


STATE_PATH = REPORTS / "primitive_state.json"


def load_state(path: Path | str = STATE_PATH) -> Dict[str, Any]:
    """
    Load primitive state from JSON file.
    
    Returns empty dict if file is missing or invalid.
    
    Args:
        path: Path to state file (default: reports/primitive_state.json)
        
    Returns:
        Dict with structure: {key: {"ts": iso_string, "value": scalar}}
    """
    path_obj = Path(path)
    
    if not path_obj.exists():
        return {}
    
    try:
        content = path_obj.read_text(encoding="utf-8")
        if not content.strip():
            return {}
        return json.loads(content)
    except (json.JSONDecodeError, IOError):
        return {}


def save_state(state: Dict[str, Any], path: Path | str = STATE_PATH) -> None:
    """
    Save primitive state atomically.
    
    Args:
        state: Dict with structure: {key: {"ts": iso_string, "value": scalar}}
        path: Path to state file (default: reports/primitive_state.json)
    """
    atomic_write_json(path, state)


def update_last(state: Dict[str, Any], key: str, ts_iso: str, value: Any) -> Dict[str, Any]:
    """
    Update state with last known value for a key.
    
    Args:
        state: Current state dict (will be modified)
        key: Key to update
        ts_iso: ISO timestamp string (timezone-aware)
        value: Scalar value to store
        
    Returns:
        Updated state dict (same reference)
    """
    state[key] = {"ts": ts_iso, "value": value}
    return state


def compute_velocity(
    prev_ts_iso: str | None,
    prev_val: float | None,
    cur_ts_iso: str,
    cur_val: float | None,
) -> float | None:
    """
    Compute velocity (rate of change per second) between two timestamps.
    
    Args:
        prev_ts_iso: Previous ISO timestamp string (timezone-aware) or None
        prev_val: Previous scalar value or None
        cur_ts_iso: Current ISO timestamp string (timezone-aware)
        cur_val: Current scalar value or None
        
    Returns:
        Velocity in units per second, or None if cannot compute
    """
    # Check all inputs are valid
    if prev_ts_iso is None or prev_val is None or cur_val is None:
        return None
    
    try:
        # Parse ISO timestamps (timezone-aware)
        prev_dt = datetime.fromisoformat(prev_ts_iso.replace("Z", "+00:00"))
        cur_dt = datetime.fromisoformat(cur_ts_iso.replace("Z", "+00:00"))
        
        # Compute time delta in seconds
        dt_seconds = (cur_dt - prev_dt).total_seconds()
        
        # Avoid divide-by-zero and negative deltas
        if dt_seconds <= 0:
            return None
        
        # Compute velocity: (current - previous) / time_delta
        velocity = (cur_val - prev_val) / dt_seconds
        
        return velocity
    except (ValueError, TypeError, AttributeError):
        # Invalid timestamp format or value type
        return None

