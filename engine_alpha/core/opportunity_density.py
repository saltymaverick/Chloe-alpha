"""
Opportunity density primitives.

Tracks rolling opportunity density per regime, measuring how often
the system sees eligible opportunities vs. blocked/no-signal conditions.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

from engine_alpha.core.atomic_io import atomic_write_json
from engine_alpha.core.paths import REPORTS


STATE_PATH = REPORTS / "opportunity_state.json"
HEARTBEAT_PATH = REPORTS / "loop" / "heartbeat.json"


def _now_iso() -> str:
    """Return current ISO timestamp."""
    return datetime.now(timezone.utc).isoformat()


def is_loop_alive(max_age_seconds: int = 90) -> bool:
    """
    Check if trading loop is alive by checking heartbeat file age.
    
    Args:
        max_age_seconds: Maximum age of heartbeat file in seconds
        
    Returns:
        True if heartbeat exists and is fresh, False otherwise
    """
    if not HEARTBEAT_PATH.exists():
        return False
    
    try:
        heartbeat_data = json.loads(HEARTBEAT_PATH.read_text())
        heartbeat_ts_str = heartbeat_data.get("ts")
        if not heartbeat_ts_str:
            return False
        
        heartbeat_ts = datetime.fromisoformat(heartbeat_ts_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age_seconds = (now - heartbeat_ts).total_seconds()
        
        return age_seconds < max_age_seconds
    except Exception:
        return False


def write_heartbeat() -> None:
    """Write heartbeat file to indicate loop is alive."""
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_data = {"ts": _now_iso()}
    atomic_write_json(HEARTBEAT_PATH, heartbeat_data)


def _default_state() -> Dict[str, Any]:
    """Return default state structure."""
    return {
        "global": {
            "ticks": 0,
            "eligible": 0,
            "eligible_ewma": 0.0,
            "ticks_ewma": 0.0,
        },
        "by_regime": {
            "unknown": {
                "ticks": 0,
                "eligible": 0,
                "eligible_ewma": 0.0,
                "ticks_ewma": 0.0,
                "last_ts": None,
            }
        },
        "meta": {
            "last_density_ingest_ts": None,  # ISO timestamp of last density ingest window end
            "last_source": None,  # "loop" or "snapshot" - tracks which updater last modified density
            "last_update_ts": None,  # ISO timestamp of last density update
            "half_life_minutes": 120,  # Half-life for time-aware EWMA decay
        },
        "density_ewma": 0.0,  # Global density EWMA (legacy, kept for compatibility)
        "by_regime_density": {},  # Per-regime density EWMA: {"chop": 0.51, "trend": 0.18, ...}
        "density_floor_by_regime": {  # Per-regime density floors
            "chop": 0.12,
            "trend_up": 0.08,
            "trend_down": 0.08,
            "squeeze": 0.06,
            "high_vol": 0.10,
            "unknown": 0.10,
        },
    }


def load_state(path: Path = STATE_PATH) -> Dict[str, Any]:
    """
    Loads the opportunity state from a JSON file.
    Returns default structure if the file is missing or invalid.
    """
    if not path.exists():
        return _default_state()
    
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Ensure structure is valid
        if not isinstance(data, dict):
            return _default_state()
        
        # Ensure required keys exist
        if "global" not in data:
            data["global"] = _default_state()["global"]
        if "by_regime" not in data:
            data["by_regime"] = _default_state()["by_regime"]
        if "meta" not in data:
            data["meta"] = _default_state()["meta"]
        
        # Ensure new fields exist (backward compatibility)
        default_meta = _default_state()["meta"]
        for key in default_meta:
            if key not in data["meta"]:
                data["meta"][key] = default_meta[key]
        
        # Ensure density fields exist
        if "density_ewma" not in data:
            data["density_ewma"] = 0.0
        if "by_regime_density" not in data:
            data["by_regime_density"] = {}
        if "density_floor_by_regime" not in data:
            data["density_floor_by_regime"] = _default_state()["density_floor_by_regime"]
        
        return data
    except (json.JSONDecodeError, FileNotFoundError, TypeError, KeyError):
        return _default_state()
    except Exception:
        return _default_state()


def save_state(state: Dict[str, Any], path: Path = STATE_PATH) -> None:
    """
    Saves the opportunity state to a JSON file atomically.
    """
    atomic_write_json(path, state)


def ewma(prev: float, x: float, alpha: float) -> float:
    """
    Exponential Weighted Moving Average.
    
    Args:
        prev: Previous EWMA value
        x: New observation
        alpha: Smoothing factor (0 < alpha <= 1), smaller = more smoothing
        
    Returns:
        Updated EWMA value
    """
    return alpha * x + (1.0 - alpha) * prev


def ewma_timeaware(prev: float, x: float, dt_minutes: float, half_life_minutes: float) -> float:
    """
    Time-aware EWMA that accounts for time elapsed.
    
    Args:
        prev: Previous EWMA value
        x: New observation
        dt_minutes: Time elapsed since last update (minutes)
        half_life_minutes: Half-life for decay (minutes)
        
    Returns:
        Updated EWMA value
    """
    if dt_minutes <= 0:
        alpha = 0.05  # Default alpha if no time info
    else:
        # Compute alpha based on time elapsed and half-life
        alpha = 1.0 - math.exp(-dt_minutes / half_life_minutes)
        # Clamp alpha to reasonable range
        alpha = max(0.01, min(0.5, alpha))
    
    return alpha * x + (1.0 - alpha) * prev


def update_opportunity_state(
    state: Dict[str, Any],
    ts_iso: str,
    regime: str,
    is_eligible: bool,
    alpha: float = 0.05,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Update opportunity state and compute density metrics.
    
    Args:
        state: Current state dict
        ts_iso: Current ISO timestamp
        regime: Regime name (e.g., "trend_up", "chop", "unknown")
        is_eligible: Whether this tick is eligible
        alpha: EWMA smoothing factor (default 0.05)
        
    Returns:
        Tuple of (updated_state, metrics_dict)
    """
    # Ensure state structure is valid
    if "global" not in state:
        state["global"] = _default_state()["global"]
    if "by_regime" not in state:
        state["by_regime"] = {}
    
    # Initialize regime entry if missing
    if regime not in state["by_regime"]:
        state["by_regime"][regime] = {
            "ticks": 0,
            "eligible": 0,
            "eligible_ewma": 0.0,
            "ticks_ewma": 0.0,
            "last_ts": None,
        }
    
    # Update global counters
    state["global"]["ticks"] += 1
    if is_eligible:
        state["global"]["eligible"] += 1
    
    # Update global EWMA
    state["global"]["ticks_ewma"] = ewma(state["global"]["ticks_ewma"], 1.0, alpha)
    state["global"]["eligible_ewma"] = ewma(
        state["global"]["eligible_ewma"], 1.0 if is_eligible else 0.0, alpha
    )
    
    # Update regime counters
    regime_entry = state["by_regime"][regime]
    regime_entry["ticks"] += 1
    if is_eligible:
        regime_entry["eligible"] += 1
    
    # Update regime EWMA
    regime_entry["ticks_ewma"] = ewma(regime_entry["ticks_ewma"], 1.0, alpha)
    regime_entry["eligible_ewma"] = ewma(
        regime_entry["eligible_ewma"], 1.0 if is_eligible else 0.0, alpha
    )
    regime_entry["last_ts"] = ts_iso
    
    # Mark source (will be set by caller - loop or snapshot)
    # This is set externally to avoid coupling, but we ensure meta exists
    if "meta" not in state:
        state["meta"] = _default_state()["meta"]
    
    # Update density_ewma and by_regime_density with time-aware EWMA
    meta = state["meta"]
    last_update_ts = meta.get("last_update_ts")
    half_life_minutes = meta.get("half_life_minutes", 120)
    
    # Compute time delta
    try:
        if last_update_ts:
            last_dt = datetime.fromisoformat(last_update_ts.replace("Z", "+00:00"))
            current_dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
            dt_minutes = (current_dt - last_dt).total_seconds() / 60.0
        else:
            dt_minutes = 0.0
    except Exception:
        dt_minutes = 0.0
    
    # Update global density_ewma
    x_value = 1.0 if is_eligible else 0.0
    if dt_minutes > 0:
        state["density_ewma"] = ewma_timeaware(
            state.get("density_ewma", 0.0),
            x_value,
            dt_minutes,
            half_life_minutes
        )
    else:
        # Fallback to standard EWMA if no time info
        state["density_ewma"] = ewma(state.get("density_ewma", 0.0), x_value, alpha)
    
    # Update by_regime_density
    if "by_regime_density" not in state:
        state["by_regime_density"] = {}
    
    regime_density_prev = state["by_regime_density"].get(regime, 0.0)
    if dt_minutes > 0:
        state["by_regime_density"][regime] = ewma_timeaware(
            regime_density_prev,
            x_value,
            dt_minutes,
            half_life_minutes
        )
    else:
        state["by_regime_density"][regime] = ewma(regime_density_prev, x_value, alpha)
    
    # Update last_update_ts
    meta["last_update_ts"] = ts_iso
    
    # Compute density metrics
    global_ticks = state["global"]["ticks"]
    global_eligible = state["global"]["eligible"]
    global_ticks_ewma = state["global"]["ticks_ewma"]
    global_eligible_ewma = state["global"]["eligible_ewma"]
    
    regime_ticks = regime_entry["ticks"]
    regime_eligible = regime_entry["eligible"]
    regime_ticks_ewma = regime_entry["ticks_ewma"]
    regime_eligible_ewma = regime_entry["eligible_ewma"]
    
    # Safe division for densities
    global_density_all_time = global_eligible / max(global_ticks, 1)
    global_density_ewma = global_eligible_ewma / max(global_ticks_ewma, 1e-9)
    
    regime_density_all_time = regime_eligible / max(regime_ticks, 1)
    regime_density_ewma = regime_eligible_ewma / max(regime_ticks_ewma, 1e-9)
    
    # Get regime-specific density (prefer by_regime_density if available)
    regime_density_current = state["by_regime_density"].get(regime, regime_density_ewma)
    
    metrics = {
        "regime": regime,
        "eligible": is_eligible,
        "density_ewma": regime_density_ewma,
        "density_current": regime_density_current,  # Regime-specific density
        "density_all_time": regime_density_all_time,
        "global_density_ewma": global_density_ewma,
        "global_density_all_time": global_density_all_time,
        "by_regime_density": state["by_regime_density"].copy(),  # Include all regime densities
    }
    
    return state, metrics

