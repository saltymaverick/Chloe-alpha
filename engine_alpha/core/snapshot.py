"""
Snapshot module for Phase A bulletproof core.

Provides canonical snapshot structure and utilities for setting/getting nested values.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Any, Optional


def new_snapshot(ts: str, symbol: str, timeframe: str, mode: str) -> Dict[str, Any]:
    """
    Create a new canonical snapshot dict.
    
    Args:
        ts: ISO8601 timestamp string
        symbol: Trading symbol (e.g., "ETHUSDT")
        timeframe: Timeframe (e.g., "15m")
        mode: Mode string (e.g., "PAPER", "LIVE", "DRY_RUN")
    
    Returns:
        Dict with canonical snapshot schema
    """
    # Generate tick_id as safe string: "{ts}_{symbol}_{timeframe}"
    # Replace colons and other special chars for filesystem safety
    safe_ts = ts.replace(":", "-").replace(" ", "_")
    tick_id = f"{safe_ts}_{symbol}_{timeframe}"
    
    return {
        "ts": ts,
        "symbol": symbol,
        "timeframe": timeframe,
        "mode": mode,
        "market": {},
        "signals": {},
        "primitives": {},
        "regime": {},
        "risk": {},
        "decision": {},
        "execution": {},
        "metrics": {},
        "meta": {
            "tick_id": tick_id,
            "version": "alpha",
            "notes": [],
        },
    }


def snapshot_set(snapshot: Dict[str, Any], path: str, value: Any) -> None:
    """
    Set a nested value in snapshot using dot-separated path.
    
    Creates nested dicts as needed.
    
    Args:
        snapshot: Snapshot dict to modify
        path: Dot-separated path (e.g., "signals.pci", "decision.final.dir")
        value: Value to set
    """
    parts = path.split(".")
    current = snapshot
    
    # Navigate/create nested dicts up to the last part
    for part in parts[:-1]:
        if part not in current:
            current[part] = {}
        elif not isinstance(current[part], dict):
            # Overwrite non-dict with dict
            current[part] = {}
        current = current[part]
    
    # Set the final value
    current[parts[-1]] = value


def snapshot_get(snapshot: Dict[str, Any], path: str, default: Any = None) -> Any:
    """
    Get a nested value from snapshot using dot-separated path.
    
    Args:
        snapshot: Snapshot dict to read from
        path: Dot-separated path (e.g., "signals.pci", "decision.final.dir")
        default: Default value if path doesn't exist
    
    Returns:
        Value at path, or default if not found
    """
    parts = path.split(".")
    current = snapshot
    
    for part in parts:
        if not isinstance(current, dict):
            return default
        if part not in current:
            return default
        current = current[part]
    
    return current

