"""
Provider cooldown state management.

Tracks cooldown periods for exchange providers when rate-limited or forbidden.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from engine_alpha.core.atomic_io import atomic_write_json
from engine_alpha.core.paths import REPORTS


STATE_PATH = REPORTS / "provider_cooldown.json"


def load_state(path: Path = STATE_PATH) -> Dict[str, Any]:
    """
    Loads the provider cooldown state from a JSON file.
    Returns empty dict if the file is missing or invalid.
    """
    if not path.exists():
        return {}
    
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        
        if not isinstance(data, dict):
            return {}
        
        return data
    except (json.JSONDecodeError, FileNotFoundError, TypeError):
        return {}
    except Exception:
        return {}


def save_state(state: Dict[str, Any], path: Path = STATE_PATH) -> None:
    """
    Saves the provider cooldown state to a JSON file atomically.
    """
    atomic_write_json(path, state)


def in_cooldown(state: Dict[str, Any], provider: str, now_ts_iso: str) -> bool:
    """
    Check if a provider is currently in cooldown.
    
    Args:
        state: Cooldown state dict
        provider: Provider name (e.g., "BYBIT", "BINANCE")
        now_ts_iso: Current ISO timestamp string
        
    Returns:
        True if provider is in cooldown, False otherwise
    """
    provider_upper = provider.upper()
    entry = state.get(provider_upper)
    
    if not entry or not isinstance(entry, dict):
        return False
    
    cooldown_until_ts = entry.get("cooldown_until_ts")
    if not cooldown_until_ts:
        return False
    
    try:
        # Parse timezone-aware timestamps
        cooldown_until = datetime.fromisoformat(cooldown_until_ts.replace("Z", "+00:00"))
        now = datetime.fromisoformat(now_ts_iso.replace("Z", "+00:00"))
        
        return now < cooldown_until
    except (ValueError, TypeError, AttributeError):
        return False


def set_cooldown(
    state: Dict[str, Any],
    provider: str,
    now_ts_iso: str,
    error_code: str,
    bump: bool = True,
) -> Dict[str, Any]:
    """
    Set cooldown for a provider with exponential backoff.
    
    Args:
        state: Cooldown state dict
        provider: Provider name (e.g., "BYBIT")
        now_ts_iso: Current ISO timestamp string
        error_code: Error code ("429", "403", "timeout", etc.)
        bump: If True, apply exponential backoff based on previous count
        
    Returns:
        Updated state dict
    """
    provider_upper = provider.upper()
    
    # Get current entry
    entry = state.get(provider_upper, {})
    if not isinstance(entry, dict):
        entry = {}
    
    # Progressive backoff (operator-friendly):
    # - Short for transient errors (429/timeout) on first failure
    # - Longer only on consecutive failures
    # - Hard cap at 60 minutes (except you can still "stay down" via repeated 403s, but the cap holds)
    #
    # NOTE: `count` is treated as a consecutive-failure counter; it is reset to 0 by clear_cooldown().
    try:
        count = int(entry.get("count", 0))
    except Exception:
        count = 0
    if count < 0:
        count = 0

    def _cooldown_for_error(code: str, n: int) -> int:
        # n = consecutive failures so far (0 means "first failure")
        # First: 2–5 minutes, Second: ~10 minutes, Third: 30 minutes, 4+: 60 minutes
        if code in ("429", "timeout"):
            steps = [300, 600, 1800, 3600]
        elif code == "403":
            # 403 can be more serious (forbidden/banned). Start longer but still cap at 60m.
            steps = [1800, 3600, 3600, 3600]
        else:
            steps = [300, 600, 1800, 3600]
        idx = n if n < len(steps) else (len(steps) - 1)
        return int(steps[idx])

    cooldown_seconds = _cooldown_for_error(error_code, count)
    if not bump:
        # If bump disabled, force the "first failure" duration for this error type.
        cooldown_seconds = _cooldown_for_error(error_code, 0)

    # Absolute cap (operator expectation): never exceed 60 minutes.
    cooldown_seconds = min(int(cooldown_seconds), 3600)
    
    # Calculate cooldown end time
    try:
        now = datetime.fromisoformat(now_ts_iso.replace("Z", "+00:00"))
        cooldown_until = now + timedelta(seconds=cooldown_seconds)
        cooldown_until_ts = cooldown_until.isoformat()
    except (ValueError, TypeError, AttributeError):
        # Fallback: just add seconds as string offset (not ideal but safe)
        cooldown_until_ts = now_ts_iso
    
    # Update state
    state[provider_upper] = {
        "cooldown_until_ts": cooldown_until_ts,
        "last_error": error_code,
        "count": count + 1,
    }
    
    return state


def clear_cooldown(state: Dict[str, Any], provider: str) -> Dict[str, Any]:
    """
    Clear cooldown for a provider (call on successful fetch).
    
    Args:
        state: Cooldown state dict
        provider: Provider name
        
    Returns:
        Updated state dict
    """
    provider_upper = provider.upper()
    
    if provider_upper in state:
        # Reset count but keep entry (for tracking)
        state[provider_upper] = {
            "cooldown_until_ts": None,
            "last_error": None,
            "count": 0,
        }
    
    return state

