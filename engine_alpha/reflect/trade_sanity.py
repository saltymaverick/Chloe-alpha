"""
Trade Sanity Filtering Module
------------------------------

Filters corrupted trade events from analytics and PF attribution.

A trade event is considered corrupted if:
- entry_px == 1.0 (placeholder price)
- entry_px_invalid == True (explicitly flagged)
- entry_px is not None and entry_px <= 0 (invalid price)

This module is ANALYTICS-ONLY and does not affect live trading execution.
"""

from __future__ import annotations

from typing import Dict, Any, List


def is_close_like_event(evt: Dict[str, Any]) -> bool:
    """
    Normalize "close-like" detection across trade analytics.

    Accepts both legacy schema (`event`) and current schema (`type`), and treats:
      - type/event in {"close","exit"} as close-like.
    """
    et = evt.get("event")
    tt = evt.get("type")
    kind = (tt if isinstance(tt, str) and tt else et) or ""
    return str(kind).lower() in {"close", "exit"}


def get_close_return_pct(evt: Dict[str, Any]) -> float | None:
    """
    Extract close return as a float (pct), normalized across schemas.

    Prefers `pct` (trades_v2), falls back to `pnl_pct` (legacy).
    Returns None if not present/parseable.
    """
    val = evt.get("pct", evt.get("pnl_pct"))
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def is_corrupted_trade_event(evt: Dict[str, Any]) -> bool:
    """
    Check if a trade event is corrupted.
    
    Only treats events as corrupted if:
    - entry_px_invalid flag is explicitly True, OR
    - entry_px is a numeric value equal to 1.0 (placeholder)
    
    Missing entry_px is NOT considered corrupted (CLOSE events don't have it).
    
    Args:
        evt: Trade event dictionary
        
    Returns:
        True if the event is corrupted and should be excluded from analytics
    """
    # Check explicit flag (most reliable)
    if evt.get("entry_px_invalid") is True:
        return True
    
    # Only check entry_px if it exists and is numeric
    entry_px = evt.get("entry_px")
    if entry_px is None:
        # Missing entry_px is NOT corrupted (CLOSE events don't have it)
        return False
    
    # Check for placeholder price (1.0) - only if it's numeric
    try:
        entry_px_val = float(entry_px)
        # Check for placeholder (1.0) - use small epsilon for float comparison
        if abs(entry_px_val - 1.0) < 1e-12:
            return True
        # Check for invalid (<= 0) - but only if it's actually present
        if entry_px_val <= 0:
            return True
    except (ValueError, TypeError):
        # If entry_px exists but can't be parsed as float, it's not corrupted
        # (might be a string or other type - don't filter it)
        return False
    
    return False


def filter_corrupted(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filter out corrupted trade events.
    
    Args:
        events: List of trade event dictionaries
        
    Returns:
        List of non-corrupted events
    """
    return [evt for evt in events if not is_corrupted_trade_event(evt)]


__all__ = [
    "is_close_like_event",
    "get_close_return_pct",
    "is_corrupted_trade_event",
    "filter_corrupted",
]

