"""
Liquidity Sweeps Engine - Detects HTF pool sweeps and breaker blocks.

Detects:
- 1h equal highs / equal lows
- 15m and 5m sweeps (wick through HTF pool, close back inside, displacement candle)
- Breaker block confirmation
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from collections import defaultdict

from engine_alpha.research.advanced_structure.multi_timeframe_loader import load_all_timeframes


def _detect_session(ts: datetime) -> str:
    """
    Classify UTC timestamp into a coarse session bucket.
    This is advisory-only and used for research outputs.
    """
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    hour = ts.hour
    
    # Very simple buckets; safe default
    if 0 <= hour < 8:
        return "Asia"
    elif 8 <= hour < 12:
        return "London"
    elif 12 <= hour < 17:
        return "NY_Open"
    elif 17 <= hour < 22:
        return "NY_Close"
    else:
        return "Afterhours"


def _get_session(timestamp: datetime) -> str:
    """Legacy alias for _detect_session."""
    return _detect_session(timestamp)


def _detect_equal_highs_lows(candles_1h: List[Dict[str, Any]], lookback: int = 20) -> Dict[str, bool]:
    """Detect equal highs and equal lows in 1h timeframe."""
    if len(candles_1h) < lookback:
        return {"equal_highs": False, "equal_lows": False}
    
    recent = candles_1h[-lookback:]
    highs = [float(c.get("high", 0)) for c in recent]
    lows = [float(c.get("low", 0)) for c in recent]
    
    if not highs or not lows:
        return {"equal_highs": False, "equal_lows": False}
    
    # Equal highs: multiple candles with same high (within 0.1% tolerance)
    max_high = max(highs)
    equal_high_count = sum(1 for h in highs if abs(h - max_high) / max_high < 0.001)
    equal_highs = equal_high_count >= 2
    
    # Equal lows: multiple candles with same low (within 0.1% tolerance)
    min_low = min(lows)
    equal_low_count = sum(1 for l in lows if abs(l - min_low) / min_low < 0.001)
    equal_lows = equal_low_count >= 2
    
    return {"equal_highs": equal_highs, "equal_lows": equal_lows}


def _detect_sweep(
    candles_ltf: List[Dict[str, Any]],
    pool_level: float,
    pool_type: str,  # "above" or "below"
    lookback: int = 10,
) -> bool:
    """
    Detect if a sweep occurred: wick through pool, close back inside, displacement candle.
    
    Args:
        candles_ltf: Lower timeframe candles (5m or 15m)
        pool_level: HTF pool level to check
        pool_type: "above" for resistance pool, "below" for support pool
        lookback: Number of recent candles to check
    
    Returns:
        True if sweep detected
    """
    if len(candles_ltf) < lookback:
        return False
    
    recent = candles_ltf[-lookback:]
    
    for i, candle in enumerate(recent):
        high = float(candle.get("high", 0))
        low = float(candle.get("low", 0))
        close = float(candle.get("close", 0))
        
        if pool_type == "above":
            # Sweep above: wick goes above pool, close below pool
            if high > pool_level and close < pool_level:
                # Check for displacement candle (next candle moves away)
                if i + 1 < len(recent):
                    next_candle = recent[i + 1]
                    next_close = float(next_candle.get("close", 0))
                    if next_close < pool_level:
                        return True
        elif pool_type == "below":
            # Sweep below: wick goes below pool, close above pool
            if low < pool_level and close > pool_level:
                # Check for displacement candle
                if i + 1 < len(recent):
                    next_candle = recent[i + 1]
                    next_close = float(next_candle.get("close", 0))
                    if next_close > pool_level:
                        return True
    
    return False


def _detect_breaker_block(
    candles_1h: List[Dict[str, Any]],
    candles_ltf: List[Dict[str, Any]],
    pool_level: float,
    pool_type: str,
) -> str:
    """
    Detect breaker block: last opposite candle before impulse, then break.
    
    Returns:
        "bullish", "bearish", or "none"
    """
    if len(candles_1h) < 5 or len(candles_ltf) < 5:
        return "none"
    
    # Find last opposite candle before break
    recent_1h = candles_1h[-5:]
    
    if pool_type == "above":
        # Look for bearish candle before bullish break
        for i in range(len(recent_1h) - 1, 0, -1):
            candle = recent_1h[i]
            prev_candle = recent_1h[i - 1]
            
            prev_close = float(prev_candle.get("close", 0))
            prev_open = float(prev_candle.get("open", 0))
            curr_close = float(candle.get("close", 0))
            
            # Bearish candle (close < open) followed by bullish break
            if prev_close < prev_open and curr_close > pool_level:
                # Check LTF for confirmation
                recent_ltf = candles_ltf[-10:]
                for ltf_candle in recent_ltf:
                    ltf_close = float(ltf_candle.get("close", 0))
                    if ltf_close > pool_level:
                        return "bullish"
    
    elif pool_type == "below":
        # Look for bullish candle before bearish break
        for i in range(len(recent_1h) - 1, 0, -1):
            candle = recent_1h[i]
            prev_candle = recent_1h[i - 1]
            
            prev_close = float(prev_candle.get("close", 0))
            prev_open = float(prev_candle.get("open", 0))
            curr_close = float(candle.get("close", 0))
            
            # Bullish candle (close > open) followed by bearish break
            if prev_close > prev_open and curr_close < pool_level:
                # Check LTF for confirmation
                recent_ltf = candles_ltf[-10:]
                for ltf_candle in recent_ltf:
                    ltf_close = float(ltf_candle.get("close", 0))
                    if ltf_close < pool_level:
                        return "bearish"
    
    return "none"


def compute_liquidity_sweeps(
    symbol: str,
    volume_imbalance_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Compute liquidity sweep signals for a symbol.
    
    Args:
        symbol: Symbol ID (e.g., "ETHUSDT")
        volume_imbalance_data: Optional volume imbalance data for strength scoring
    
    Returns:
        {
            "ETHUSDT": {
                "session": "London",
                "htf_pool": "above" | "below" | "none",
                "equal_highs_1h": bool,
                "equal_lows_1h": bool,
                "sell_sweep_5m": bool,
                "buy_sweep_5m": bool,
                "sell_sweep_15m": bool,
                "buy_sweep_15m": bool,
                "breaker": "bullish" | "bearish" | "none",
                "strength": float (0.0-1.0),
                "notes": List[str],
            },
            ...
        }
    """
    result: Dict[str, Dict[str, Any]] = {}
    
    try:
        # Load multi-timeframe data
        tf_data = load_all_timeframes(symbol, max_bars_5m=500, max_bars_15m=300, max_bars_1h=100)
        
        candles_5m = tf_data.get("5m", [])
        candles_15m = tf_data.get("15m", [])
        candles_1h = tf_data.get("1h", [])
        
        if not candles_1h or len(candles_1h) < 5:
            return {symbol: {
                "session": "Unknown",
                "htf_pool": "none",
                "equal_highs_1h": False,
                "equal_lows_1h": False,
                "sell_sweep_5m": False,
                "buy_sweep_5m": False,
                "sell_sweep_15m": False,
                "buy_sweep_15m": False,
                "breaker": "none",
                "strength": 0.0,
                "notes": ["Insufficient 1h data"],
            }}
        
        # Get current session
        last_ts_str = candles_1h[-1].get("ts", "")
        try:
            if isinstance(last_ts_str, str):
                if "T" in last_ts_str:
                    last_ts = datetime.fromisoformat(last_ts_str.replace("Z", "+00:00"))
                else:
                    last_ts = datetime.fromisoformat(last_ts_str)
            else:
                last_ts = datetime.now(timezone.utc)
        except Exception:
            last_ts = datetime.now(timezone.utc)
        
        session = _get_session(last_ts)
        
        # Detect equal highs/lows
        eq_signals = _detect_equal_highs_lows(candles_1h, lookback=20)
        equal_highs = eq_signals.get("equal_highs", False)
        equal_lows = eq_signals.get("equal_lows", False)
        
        # Determine HTF pool
        htf_pool = "none"
        pool_level = 0.0
        
        if equal_highs:
            # Find the equal high level
            recent_1h = candles_1h[-20:]
            highs = [float(c.get("high", 0)) for c in recent_1h]
            pool_level = max(highs)
            htf_pool = "above"
        elif equal_lows:
            # Find the equal low level
            recent_1h = candles_1h[-20:]
            lows = [float(c.get("low", 0)) for c in recent_1h]
            pool_level = min(lows)
            htf_pool = "below"
        
        # Detect sweeps
        sell_sweep_5m = False
        buy_sweep_5m = False
        sell_sweep_15m = False
        buy_sweep_15m = False
        
        if htf_pool != "none" and pool_level > 0:
            if htf_pool == "above":
                sell_sweep_5m = _detect_sweep(candles_5m, pool_level, "above", lookback=10)
                sell_sweep_15m = _detect_sweep(candles_15m, pool_level, "above", lookback=10)
            elif htf_pool == "below":
                buy_sweep_5m = _detect_sweep(candles_5m, pool_level, "below", lookback=10)
                buy_sweep_15m = _detect_sweep(candles_15m, pool_level, "below", lookback=10)
        
        # Detect breaker block
        breaker = "none"
        if htf_pool != "none" and pool_level > 0:
            breaker = _detect_breaker_block(candles_1h, candles_15m, pool_level, htf_pool)
        
        # Calculate strength score
        strength = 0.0
        notes: List[str] = []
        
        # +0.3 if HTF pool exists & was swept
        if htf_pool != "none":
            strength += 0.3
            notes.append(f"HTF pool detected ({htf_pool})")
            
            if sell_sweep_5m or sell_sweep_15m or buy_sweep_5m or buy_sweep_15m:
                strength += 0.3
                notes.append("Sweep detected")
        
        # +0.3 if displacement / breaker found
        if breaker != "none":
            strength += 0.3
            notes.append(f"Breaker block: {breaker}")
        
        # +0.2 if sweep aligned with session volatility window
        if session in ["London", "NY"] and (sell_sweep_5m or buy_sweep_5m or sell_sweep_15m or buy_sweep_15m):
            strength += 0.2
            notes.append(f"Sweep during {session} session")
        
        # +0.2 if volume-imbalance engine confirms direction
        if volume_imbalance_data:
            vi_symbol = volume_imbalance_data.get(symbol, {})
            delta_5m = vi_symbol.get("delta_5m", 0.0)
            delta_15m = vi_symbol.get("delta_15m", 0.0)
            
            # Confirm bullish if buy sweep and positive delta
            if (buy_sweep_5m or buy_sweep_15m) and (delta_5m > 0.1 or delta_15m > 0.1):
                strength += 0.2
                notes.append("Volume imbalance confirms bullish direction")
            # Confirm bearish if sell sweep and negative delta
            elif (sell_sweep_5m or sell_sweep_15m) and (delta_5m < -0.1 or delta_15m < -0.1):
                strength += 0.2
                notes.append("Volume imbalance confirms bearish direction")
        
        # Cap at 1.0
        strength = min(strength, 1.0)
        
        if not notes:
            notes = ["No significant sweep signals"]
        
        result[symbol] = {
            "session": session,
            "htf_pool": htf_pool,
            "equal_highs_1h": equal_highs,
            "equal_lows_1h": equal_lows,
            "sell_sweep_5m": sell_sweep_5m,
            "buy_sweep_5m": buy_sweep_5m,
            "sell_sweep_15m": sell_sweep_15m,
            "buy_sweep_15m": buy_sweep_15m,
            "breaker": breaker,
            "strength": round(strength, 2),
            "notes": notes,
        }
        
    except Exception as e:
        result[symbol] = {
            "session": "Unknown",
            "htf_pool": "none",
            "equal_highs_1h": False,
            "equal_lows_1h": False,
            "sell_sweep_5m": False,
            "buy_sweep_5m": False,
            "sell_sweep_15m": False,
            "buy_sweep_15m": False,
            "breaker": "none",
            "strength": 0.0,
            "notes": [f"Error: {str(e)}"],
        }
    
    return result

