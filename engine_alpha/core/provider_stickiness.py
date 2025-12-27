"""
Provider stickiness for OHLCV feeds.

Ensures consistent provider selection per (symbol, timeframe) to prevent
rolling indicator wobble from provider switching.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from engine_alpha.core.atomic_io import atomic_write_json
from engine_alpha.core.paths import REPORTS


STATE_PATH = REPORTS / "ohlcv_provider_state.json"


def load_state(path: Path | str = STATE_PATH) -> Dict[str, Any]:
    """
    Load provider state from JSON file.
    
    Returns empty dict if file is missing or invalid.
    
    Args:
        path: Path to state file
        
    Returns:
        Dict with structure: {"SYMBOL:TIMEFRAME": {"source": "...", "ts": "..."}}
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
    Save provider state atomically.
    
    Args:
        state: State dict
        path: Path to state file
    """
    atomic_write_json(path, state)


def _make_key(symbol: str, timeframe: str) -> str:
    """Create state key from symbol and timeframe."""
    return f"{symbol.upper()}:{timeframe}"


def get_preferred_source(state: Dict[str, Any], symbol: str, timeframe: str) -> str | None:
    """
    Get preferred source for (symbol, timeframe) from state.
    
    Args:
        state: Provider state dict
        symbol: Trading symbol
        timeframe: Timeframe string
        
    Returns:
        Preferred source name (e.g., "okx", "binance") or None
    """
    key = _make_key(symbol, timeframe)
    entry = state.get(key)
    if isinstance(entry, dict):
        return entry.get("source")
    return None


def set_preferred_source(
    state: Dict[str, Any],
    symbol: str,
    timeframe: str,
    source: str,
    ts_iso: str | None = None,
) -> Dict[str, Any]:
    """
    Set preferred source for (symbol, timeframe) in state.
    
    Args:
        state: Provider state dict (will be modified)
        symbol: Trading symbol
        timeframe: Timeframe string
        source: Source name (e.g., "okx", "binance")
        ts_iso: ISO timestamp (defaults to now)
        
    Returns:
        Updated state dict (same reference)
    """
    if ts_iso is None:
        ts_iso = datetime.now(timezone.utc).isoformat()
    
    key = _make_key(symbol, timeframe)
    state[key] = {"source": source, "ts": ts_iso}
    return state

