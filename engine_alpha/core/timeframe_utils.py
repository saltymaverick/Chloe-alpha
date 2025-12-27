"""
Timeframe utilities for OHLCV staleness and validation.
"""

from __future__ import annotations


def timeframe_to_seconds(tf: str) -> int | None:
    """
    Convert timeframe string to seconds.
    
    Supports: "1m", "3m", "5m", "15m", "30m", "45m", "1h", "2h", "4h", "6h", "12h", "1d"
    
    Args:
        tf: Timeframe string (e.g., "1h", "15m")
        
    Returns:
        Seconds in timeframe, or None if invalid
    """
    if not tf:
        return None
    
    try:
        # Extract numeric value and unit
        value_str = tf[:-1]
        unit = tf[-1].lower()
        
        value = int(value_str)
        
        # Map units to seconds
        multipliers = {
            "m": 60,      # minutes
            "h": 3600,    # hours
            "d": 86400,   # days
        }
        
        multiplier = multipliers.get(unit)
        if multiplier is None:
            return None
        
        return value * multiplier
    except (ValueError, IndexError):
        return None


def allowed_staleness_seconds(tf: str) -> int:
    """
    Compute allowed staleness in seconds for a timeframe.
    
    Rule: max(2 * tf_seconds, 120) with cap at 3 days.
    
    Examples:
        - 15m → 1800s (30 minutes)
        - 1h → 7200s (120 minutes / 2 hours)
        - 4h → 28800s (8 hours)
    
    Args:
        tf: Timeframe string (e.g., "1h", "15m")
        
    Returns:
        Allowed staleness in seconds (minimum 120, maximum 3 days)
    """
    tf_sec = timeframe_to_seconds(tf)
    if tf_sec is None:
        # Default to 30 minutes if invalid timeframe
        return 1800
    
    # Rule: max(2 * tf_seconds, 120)
    staleness = max(2 * tf_sec, 120)
    
    # Cap at 3 days to avoid absurd values
    max_staleness = 3 * 86400  # 3 days
    return min(staleness, max_staleness)

