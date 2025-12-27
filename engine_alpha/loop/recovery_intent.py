"""
Recovery Intent Generator (Phase 5H.2.1)
----------------------------------------

Raw signal pipeline for recovery lane v2.
Does NOT filter by exploit lane intent - uses the same signal pipeline
as autonomous_trader for any symbol.

Safety:
- PAPER-only (inherited from signal pipeline)
- Deterministic
- No exploit filtering
"""

from __future__ import annotations

from typing import Dict, Any
from engine_alpha.signals.signal_processor import get_signal_vector_live
from engine_alpha.core.confidence_engine import decide


def compute_recovery_intent(
    symbol: str,
    timeframe: str = "15m",
    limit: int = 200,
) -> Dict[str, Any]:
    """
    Compute recovery trading intent for a symbol using raw signal pipeline.
    
    This uses the same signal pipeline as autonomous_trader, without
    filtering by exploit lane intent. Used by Recovery Lane V2.
    
    Args:
        symbol: Trading symbol (e.g., "BNBUSDT")
        timeframe: Timeframe (default "15m")
        limit: Number of candles to fetch (default 200)
    
    Returns:
        Dict with:
            - symbol: str
            - direction: int (-1, 0, or +1)
            - confidence: float [0.0, 1.0]
            - entry_ok: bool (direction != 0 and confidence >= 0.50)
            - exit_ok: bool (confidence < 0.42)
            - reason: str (explanation)
            - regime: str (regime name)
            - current_price: Optional[float]
    """
    try:
        # Get signals using the same pipeline as autonomous_trader
        out = get_signal_vector_live(symbol=symbol, timeframe=timeframe, limit=limit)
        
        # Get decision from confidence engine
        decision = decide(out["signal_vector"], out["raw_registry"])
        final = decision.get("final", {})
        regime = decision.get("regime", "unknown")
        
        direction = final.get("dir", 0)
        confidence = final.get("conf", 0.0)
        
        # Get current price from raw_registry if available
        current_price = None
        if "current_price" in out.get("raw_registry", {}):
            current_price = out["raw_registry"]["current_price"]
        elif "close" in out.get("raw_registry", {}):
            current_price = out["raw_registry"]["close"]
        
        # Determine entry/exit eligibility
        entry_ok = (direction != 0 and confidence >= 0.50)
        exit_ok = (confidence is not None and confidence < 0.42)
        
        # Generate reason
        if direction == 0:
            reason = "no_direction"
        elif confidence < 0.50:
            reason = f"confidence_low_{confidence:.2f}"
        else:
            reason = "signal_ready"
        
        return {
            "symbol": symbol,
            "direction": direction,
            "confidence": confidence,
            "entry_ok": entry_ok,
            "exit_ok": exit_ok,
            "reason": reason,
            "regime": regime,
            "current_price": current_price,
        }
    
    except Exception as e:
        # On error, return safe defaults
        return {
            "symbol": symbol,
            "direction": 0,
            "confidence": 0.0,
            "entry_ok": False,
            "exit_ok": False,
            "reason": f"error: {str(e)}",
            "regime": "unknown",
            "current_price": None,
        }


__all__ = ["compute_recovery_intent"]

