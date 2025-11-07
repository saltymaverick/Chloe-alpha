"""
Position manager - Phase 3
Tracks single instrument position state.
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone


class PositionManager:
    """Manages position state for a single instrument."""
    
    def __init__(self):
        """Initialize position manager."""
        self.direction: str = "FLAT"
        self.entry_price: Optional[float] = None
        self.size: float = 1.0  # Paper trading: fixed size
        self.open_ts: Optional[str] = None
        self.bars_open: int = 0  # Track how many bars position has been open
    
    def get_open_position(self) -> Dict[str, Any]:
        """
        Get current position state.
        
        Returns:
            Dictionary with position information
        """
        return {
            "direction": self.direction,
            "entry_price": self.entry_price,
            "size": self.size,
            "open_ts": self.open_ts,
            "bars_open": self.bars_open,
        }
    
    def set_position(self, direction: str, entry_price: float, open_ts: Optional[str] = None) -> None:
        """
        Set position state.
        
        Args:
            direction: Position direction ("LONG" or "SHORT")
            entry_price: Entry price
            open_ts: Optional timestamp (defaults to current UTC ISO8601)
        """
        if direction not in ["LONG", "SHORT"]:
            raise ValueError(f"Invalid direction: {direction}. Must be 'LONG' or 'SHORT'")
        
        self.direction = direction
        self.entry_price = entry_price
        self.size = 1.0
        self.open_ts = open_ts or datetime.now(timezone.utc).isoformat()
        self.bars_open = 0
    
    def clear_position(self) -> None:
        """Clear position (set to FLAT)."""
        self.direction = "FLAT"
        self.entry_price = None
        self.size = 0.0
        self.open_ts = None
        self.bars_open = 0
    
    def increment_bars(self) -> None:
        """Increment bars_open counter."""
        if self.direction != "FLAT":
            self.bars_open += 1
    
    def is_open(self) -> bool:
        """Check if position is open."""
        return self.direction != "FLAT"
    
    def is_long(self) -> bool:
        """Check if position is LONG."""
        return self.direction == "LONG"
    
    def is_short(self) -> bool:
        """Check if position is SHORT."""
        return self.direction == "SHORT"


# Global position manager instance
_position_manager: Optional[PositionManager] = None


def get_position_manager() -> PositionManager:
    """Get global position manager instance."""
    global _position_manager
    if _position_manager is None:
        _position_manager = PositionManager()
    return _position_manager
