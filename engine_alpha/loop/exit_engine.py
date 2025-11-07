"""
Exit engine - Phase 3
Handles position exit logic.
"""

from typing import Dict, Any, Optional

from engine_alpha.loop.position_manager import get_position_manager
from engine_alpha.loop.execute_trade import close_if_needed, open_if_allowed


def should_exit(position: Dict[str, Any], decision: Dict[str, Any], gates: Dict[str, float],
                max_bars_open: int = 8) -> tuple[bool, Optional[str]]:
    """
    Determine if position should be exited.
    
    Args:
        position: Current position state
        decision: Decision dictionary from confidence engine
        gates: Gates configuration
        max_bars_open: Maximum bars to hold position (default: 8)
    
    Returns:
        Tuple of (should_exit: bool, reason: Optional[str])
    """
    if position["direction"] == "FLAT":
        return False, None
    
    final_conf = decision["final"]["conf"]
    final_dir = decision["final"]["dir"]
    exit_min_conf = gates.get("exit_min_conf", 0.42)
    reverse_min_conf = gates.get("reverse_min_conf", 0.55)
    
    # Exit if confidence drops below exit threshold
    if final_conf < exit_min_conf:
        return True, "LOW_CONF"
    
    # Exit if direction flip and opposite confidence is high enough
    current_dir = 1 if position["direction"] == "LONG" else -1
    if final_dir != 0 and final_dir != current_dir:
        # Direction flip detected
        if final_conf >= reverse_min_conf:
            return True, "FLIP"
    
    # Exit if position open for too long without progress
    if position.get("bars_open", 0) >= max_bars_open:
        return True, "TIMEOUT"
    
    return False, None


def monitor(decision: Dict[str, Any], raw_registry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Monitor position and handle exits/reversals.
    
    Args:
        decision: Decision dictionary from confidence engine
        raw_registry: Raw signal registry
    
    Returns:
        Trade event dictionary if action taken, None otherwise
    """
    position_manager = get_position_manager()
    position = position_manager.get_open_position()
    gates = decision.get("gates", {})
    
    if not position_manager.is_open():
        return None
    
    # Check if should exit
    should_exit_flag, reason = should_exit(position, decision, gates)
    
    if not should_exit_flag:
        # Increment bars counter
        position_manager.increment_bars()
        return None
    
    # Handle exit
    close_event = close_if_needed(reason=reason or "EXIT")
    
    # If exit was due to flip and confidence is high enough, reopen in opposite direction
    if reason == "FLIP":
        final_dir = decision["final"]["dir"]
        final_conf = decision["final"]["conf"]
        reverse_min_conf = gates.get("reverse_min_conf", 0.55)
        
        if final_conf >= reverse_min_conf and final_dir != 0:
            # Reopen in opposite direction
            open_event = open_if_allowed(final_dir, final_conf, gates, raw_registry)
            if open_event:
                return {
                    "event": "REVERSE",
                    "close": close_event,
                    "open": open_event,
                }
    
    return close_event
