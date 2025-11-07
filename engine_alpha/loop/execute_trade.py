"""
Execute trade - Phase 3
PAPER mode trade execution.
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone

from engine_alpha.loop.position_manager import get_position_manager


def _synthesize_fill_price(raw_registry: Dict[str, Any], base_price: float = 3000.0) -> float:
    """
    Synthesize fill price from VWAP_Dist or use base price proxy.
    
    Args:
        raw_registry: Raw signal registry
        base_price: Base price (default: 3000.0 for ETHUSDT stub)
    
    Returns:
        Fill price
    """
    # Try to get VWAP_Dist and adjust base price
    vwap_dist = raw_registry.get("VWAP_Dist", {}).get("value", 0.0)
    
    # VWAP_Dist is normalized distance, so convert to price adjustment
    # For stub: assume normalized value of -1 to +1 maps to -2% to +2%
    price_adjustment = vwap_dist * 0.02 * base_price
    
    fill_price = base_price + price_adjustment
    return fill_price


def open_if_allowed(final_dir: int, final_conf: float, gates: Dict[str, float],
                   raw_registry: Dict[str, Any], risk_mult: float = 1.0) -> Optional[Dict[str, Any]]:
    """
    Open position if conditions are met.
    
    Args:
        final_dir: Final direction (-1, 0, or +1)
        final_conf: Final confidence [0, 1]
        gates: Gates configuration with entry_min_conf
        raw_registry: Raw signal registry
        risk_mult: Risk multiplier (paper only; logged)
    
    Returns:
        Trade event dictionary if opened, None otherwise
    """
    position_manager = get_position_manager()
    
    # Check if position already open in same direction
    if final_dir == 1 and position_manager.is_long():
        return None  # Already long
    if final_dir == -1 and position_manager.is_short():
        return None  # Already short
    
    # Check entry gate
    entry_min_conf = gates.get("entry_min_conf", 0.58)
    if final_conf < entry_min_conf:
        return None  # Confidence too low
    
    # Determine direction
    if final_dir == 1:
        direction = "LONG"
    elif final_dir == -1:
        direction = "SHORT"
    else:
        return None  # No direction
    
    # Synthesize fill price
    fill_price = _synthesize_fill_price(raw_registry)
    
    # Set position
    open_ts = datetime.now(timezone.utc).isoformat()
    position_manager.set_position(direction, fill_price, open_ts)
    
    return {
        "event": "OPEN",
        "direction": direction,
        "price": fill_price,
        "size": position_manager.size,
        "ts": open_ts,
        "conf": final_conf,
        "risk_mult": float(risk_mult),
    }


def close_if_needed(reason: str = "EXIT") -> Optional[Dict[str, Any]]:
    """
    Close current position if open.
    
    Args:
        reason: Reason for closing (default: "EXIT")
    
    Returns:
        Trade event dictionary if closed, None otherwise
    """
    position_manager = get_position_manager()
    
    if not position_manager.is_open():
        return None
    
    # Get position info
    direction = position_manager.direction
    entry_price = position_manager.entry_price
    open_ts = position_manager.open_ts
    bars_open = position_manager.bars_open
    
    # Synthesize exit price (for stub, use entry price with small random variation)
    # In production, this would be actual market price
    exit_price = entry_price * (1.0 + (0.001 if direction == "LONG" else -0.001))
    
    # Calculate P&L
    if direction == "LONG":
        pnl_pct = (exit_price - entry_price) / entry_price
    else:  # SHORT
        pnl_pct = (entry_price - exit_price) / entry_price
    
    # Close position
    close_ts = datetime.now(timezone.utc).isoformat()
    position_manager.clear_position()
    
    return {
        "event": "CLOSE",
        "direction": direction,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "size": 1.0,
        "pnl_pct": pnl_pct,
        "bars_open": bars_open,
        "entry_ts": open_ts,
        "exit_ts": close_ts,
        "reason": reason,
    }
