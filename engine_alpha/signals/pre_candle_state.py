"""
Pre-Candle Intelligence (PCI) - State Management Module
Phase 2.5: In-memory ring buffer for historical series

Maintains short rolling windows of funding, OI, and orderbook data
per symbol/timeframe to enable velocity/acceleration calculations.
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
from collections import deque

# Global state cache: key = (symbol, timeframe), value = dict of series
_PCI_STATE: Dict[Tuple[str, str], Dict[str, deque]] = {}

# Configuration
MAX_HISTORY_LENGTH = 16  # Maximum entries per series
STALE_THRESHOLD_MINUTES = 30  # Reset buffer if last update > 30 minutes ago


def _get_cache_key(symbol: str, timeframe: str) -> Tuple[str, str]:
    """Normalize symbol/timeframe to cache key."""
    return (symbol.upper(), timeframe.lower())


def _is_stale(last_ts: Optional[datetime]) -> bool:
    """Check if buffer is stale based on TTL."""
    if last_ts is None:
        return True
    age = datetime.now(timezone.utc) - last_ts
    return age > timedelta(minutes=STALE_THRESHOLD_MINUTES)


def update_pci_state(
    symbol: str,
    timeframe: str,
    *,
    funding: Optional[float] = None,
    oi: Optional[float] = None,
    orderbook_depth: Optional[float] = None,
    taker_imbalance: Optional[float] = None,
    ts: Optional[float] = None
) -> Dict[str, List[float]]:
    """
    Update PCI state and return rolling series for feature computation.
    
    Args:
        symbol: Trading symbol (e.g., "ETHUSDT")
        timeframe: Timeframe (e.g., "15m")
        funding: Current funding rate value (optional)
        oi: Current Open Interest value (optional)
        orderbook_depth: Current orderbook depth (bid+ask near depth, optional)
        taker_imbalance: Current taker flow imbalance [-1, 1] (optional)
        ts: Timestamp (Unix epoch or datetime, optional; defaults to now)
    
    Returns:
        Dict with keys:
        - "funding_series": List[float] (most recent last)
        - "oi_series": List[float]
        - "orderbook_depth_series": List[float]
        - "taker_imbalance_series": List[float]
        - "timestamp_series": List[float]
        All lists are capped at MAX_HISTORY_LENGTH and reset if stale.
    """
    key = _get_cache_key(symbol, timeframe)
    
    # Initialize state if needed
    if key not in _PCI_STATE:
        _PCI_STATE[key] = {
            "funding_series": deque(maxlen=MAX_HISTORY_LENGTH),
            "oi_series": deque(maxlen=MAX_HISTORY_LENGTH),
            "orderbook_depth_series": deque(maxlen=MAX_HISTORY_LENGTH),
            "taker_imbalance_series": deque(maxlen=MAX_HISTORY_LENGTH),
            "timestamp_series": deque(maxlen=MAX_HISTORY_LENGTH),
            "last_update": None,
        }
    
    state = _PCI_STATE[key]
    
    # Convert timestamp to datetime if provided
    if ts is not None:
        if isinstance(ts, (int, float)):
            # Unix timestamp
            update_time = datetime.fromtimestamp(ts, tz=timezone.utc)
        else:
            update_time = ts
    else:
        update_time = datetime.now(timezone.utc)
    
    # Check if stale and reset if needed
    if _is_stale(state.get("last_update")):
        state["funding_series"].clear()
        state["oi_series"].clear()
        state["orderbook_depth_series"].clear()
        state["taker_imbalance_series"].clear()
        state["timestamp_series"].clear()
    
    # Update series with new values (only if provided)
    if funding is not None:
        state["funding_series"].append(funding)
    
    if oi is not None:
        state["oi_series"].append(oi)
    
    if orderbook_depth is not None:
        state["orderbook_depth_series"].append(orderbook_depth)
    
    if taker_imbalance is not None:
        state["taker_imbalance_series"].append(taker_imbalance)
    
    # Always update timestamp
    ts_float = update_time.timestamp()
    state["timestamp_series"].append(ts_float)
    state["last_update"] = update_time
    
    # Return current series as lists (most recent last)
    return {
        "funding_series": list(state["funding_series"]),
        "oi_series": list(state["oi_series"]),
        "orderbook_depth_series": list(state["orderbook_depth_series"]),
        "taker_imbalance_series": list(state["taker_imbalance_series"]),
        "timestamp_series": list(state["timestamp_series"]),
    }


def clear_cache(symbol: Optional[str] = None, timeframe: Optional[str] = None) -> None:
    """
    Clear cache entries (for testing or manual reset).
    
    Args:
        symbol: If provided, clear only this symbol (all timeframes)
        timeframe: If provided with symbol, clear only this symbol/timeframe
    """
    global _PCI_STATE
    
    if symbol is None:
        _PCI_STATE.clear()
        return
    
    key_prefix = (symbol.upper(), timeframe.lower() if timeframe else None)
    
    if timeframe:
        # Clear specific symbol/timeframe
        if key_prefix in _PCI_STATE:
            del _PCI_STATE[key_prefix]
    else:
        # Clear all timeframes for symbol
        keys_to_remove = [k for k in _PCI_STATE.keys() if k[0] == key_prefix[0]]
        for k in keys_to_remove:
            del _PCI_STATE[k]
