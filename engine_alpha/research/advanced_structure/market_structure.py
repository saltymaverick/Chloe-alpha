"""
Market Structure + Sessions Engine - Analyzes 1h swing structure, order blocks, FVGs, and sessions.

Detects:
- 1h swing structure (HH-HL bullish, LH-LL bearish)
- Equal highs/lows on 1h
- Order blocks (last opposite candle before impulse)
- Fair Value Gaps (FVGs)
- Session classification (Asia/London/NY Open/NY Close)
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
from collections import defaultdict

from engine_alpha.research.advanced_structure.multi_timeframe_loader import load_all_timeframes


def _get_session(timestamp: datetime) -> str:
    """
    Determine trading session from timestamp (UTC).
    
    Returns:
        "Asia", "London", "NY Open", or "NY Close"
    """
    hour = timestamp.hour
    
    if 0 <= hour < 8:
        return "Asia"
    elif 8 <= hour < 16:
        return "London"
    elif 16 <= hour < 20:
        return "NY Open"
    elif 20 <= hour < 24:
        return "NY Close"
    
    return "Unknown"


def _find_swing_points(candles: List[Dict[str, Any]], lookback: int = 100) -> Tuple[List[float], List[float]]:
    """
    Find swing highs and swing lows in candle data.
    
    Args:
        candles: List of OHLCV candles
        lookback: Maximum number of candles to analyze
    
    Returns:
        (swing_highs, swing_lows) - lists of price levels
    """
    if len(candles) < 3:
        return [], []
    
    recent = candles[-lookback:] if len(candles) > lookback else candles
    
    swing_highs: List[float] = []
    swing_lows: List[float] = []
    
    for i in range(1, len(recent) - 1):
        prev_high = float(recent[i-1].get("high", 0))
        curr_high = float(recent[i].get("high", 0))
        next_high = float(recent[i+1].get("high", 0))
        
        prev_low = float(recent[i-1].get("low", 0))
        curr_low = float(recent[i].get("low", 0))
        next_low = float(recent[i+1].get("low", 0))
        
        # Swing high: higher than neighbors
        if curr_high > prev_high and curr_high > next_high:
            swing_highs.append(curr_high)
        
        # Swing low: lower than neighbors
        if curr_low < prev_low and curr_low < next_low:
            swing_lows.append(curr_low)
    
    return swing_highs, swing_lows


def _determine_structure(swing_highs: List[float], swing_lows: List[float]) -> str:
    """
    Determine structural bias from swing points.
    
    Returns:
        "bullish", "bearish", or "neutral"
    """
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "neutral"
    
    # Get latest two swings
    latest_highs = sorted(swing_highs, reverse=True)[:2]
    latest_lows = sorted(swing_lows)[:2]
    
    # Check for HH-HL pattern (bullish)
    if len(latest_highs) >= 2 and len(latest_lows) >= 2:
        hh = latest_highs[0] > latest_highs[1]
        hl = latest_lows[0] > latest_lows[1]
        
        if hh and hl:
            return "bullish"
    
    # Check for LH-LL pattern (bearish)
    if len(latest_highs) >= 2 and len(latest_lows) >= 2:
        lh = latest_highs[0] < latest_highs[1]
        ll = latest_lows[0] < latest_lows[1]
        
        if lh and ll:
            return "bearish"
    
    return "neutral"


def _detect_equal_highs_lows(swing_highs: List[float], swing_lows: List[float], tolerance: float = 0.001) -> Tuple[bool, bool]:
    """
    Detect equal highs and equal lows within tolerance.
    
    Args:
        swing_highs: List of swing high prices
        swing_lows: List of swing low prices
        tolerance: Price tolerance (0.1% default)
    
    Returns:
        (equal_highs, equal_lows) - boolean flags
    """
    equal_highs = False
    equal_lows = False
    
    # Check for equal highs
    if len(swing_highs) >= 2:
        sorted_highs = sorted(swing_highs, reverse=True)
        for i in range(len(sorted_highs) - 1):
            if abs(sorted_highs[i] - sorted_highs[i+1]) / sorted_highs[i] < tolerance:
                equal_highs = True
                break
    
    # Check for equal lows
    if len(swing_lows) >= 2:
        sorted_lows = sorted(swing_lows)
        for i in range(len(sorted_lows) - 1):
            if abs(sorted_lows[i] - sorted_lows[i+1]) / sorted_lows[i] < tolerance:
                equal_lows = True
                break
    
    return equal_highs, equal_lows


def _detect_order_block(candles: List[Dict[str, Any]], lookback: int = 20) -> str:
    """
    Detect order block: last opposite candle before impulse.
    
    Returns:
        "bullish", "bearish", or "none"
    """
    if len(candles) < 10:
        return "none"
    
    recent = candles[-lookback:]
    
    # Compute average range
    ranges = [float(c.get("high", 0)) - float(c.get("low", 0)) for c in recent]
    avg_range = sum(ranges) / len(ranges) if ranges else 0.0
    
    if avg_range <= 0:
        return "none"
    
    # Look for impulsive move
    for i in range(len(recent) - 5, 0, -1):
        # Check next few candles for impulse
        impulse_range = 0.0
        for j in range(i, min(i + 5, len(recent))):
            candle_range = float(recent[j].get("high", 0)) - float(recent[j].get("low", 0))
            impulse_range = max(impulse_range, candle_range)
        
        # Impulse detected if range > 2x average
        if impulse_range > 2.0 * avg_range:
            # Check previous candle (potential OB)
            prev_candle = recent[i-1]
            prev_open = float(prev_candle.get("open", 0))
            prev_close = float(prev_candle.get("close", 0))
            
            # Check direction of impulse
            curr_candle = recent[i]
            curr_open = float(curr_candle.get("open", 0))
            curr_close = float(curr_candle.get("close", 0))
            
            # Bullish OB: red candle before green impulse
            if prev_close < prev_open and curr_close > curr_open:
                return "bullish"
            
            # Bearish OB: green candle before red impulse
            if prev_close > prev_open and curr_close < curr_open:
                return "bearish"
    
    return "none"


def _detect_fvg(candles: List[Dict[str, Any]], lookback: int = 20) -> str:
    """
    Detect Fair Value Gap (FVG).
    
    FVG up: low[n] > high[n-2]
    FVG down: high[n] < low[n-2]
    
    Returns:
        "bullish", "bearish", or "none"
    """
    if len(candles) < 3:
        return "none"
    
    recent = candles[-lookback:]
    
    # Check recent candles for FVG
    for i in range(len(recent) - 1, 1, -1):
        curr_low = float(recent[i].get("low", 0))
        prev2_high = float(recent[i-2].get("high", 0))
        
        curr_high = float(recent[i].get("high", 0))
        prev2_low = float(recent[i-2].get("low", 0))
        
        # FVG up: current low > previous high (gap up)
        if curr_low > prev2_high and curr_low > 0 and prev2_high > 0:
            return "bullish"
        
        # FVG down: current high < previous low (gap down)
        if curr_high < prev2_low and curr_high > 0 and prev2_low > 0:
            return "bearish"
    
    return "none"


def compute_market_structure(
    symbol: str,
    liquidity_sweeps_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Compute market structure and session classification for a symbol.
    
    Args:
        symbol: Symbol ID (e.g., "ETHUSDT")
        liquidity_sweeps_data: Optional liquidity sweeps data for confidence scoring
    
    Returns:
        {
            "ETHUSDT": {
                "session": str,
                "structure_1h": str,
                "equal_highs_1h": bool,
                "equal_lows_1h": bool,
                "order_block_1h": str,
                "fvg_1h": str,
                "structure_confidence": float or None,
                "notes": List[str],
            },
            ...
        }
    """
    result: Dict[str, Dict[str, Any]] = {}
    
    try:
        # Load multi-timeframe data (focus on 1h)
        tf_data = load_all_timeframes(symbol, max_bars_5m=500, max_bars_15m=300, max_bars_1h=100)
        
        candles_1h = tf_data.get("1h", [])
        
        if not candles_1h or len(candles_1h) < 10:
            result[symbol] = {
                "session": "unknown",
                "structure_1h": "neutral",
                "equal_highs_1h": False,
                "equal_lows_1h": False,
                "order_block_1h": "none",
                "fvg_1h": "none",
                "structure_confidence": None,
                "notes": ["Insufficient 1h data to determine structure."],
            }
            return result
        
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
        
        # Find swing points
        swing_highs, swing_lows = _find_swing_points(candles_1h, lookback=100)
        
        # Determine structure
        structure_1h = _determine_structure(swing_highs, swing_lows)
        
        # Detect equal highs/lows
        equal_highs_1h, equal_lows_1h = _detect_equal_highs_lows(swing_highs, swing_lows)
        
        # Detect order block
        order_block_1h = _detect_order_block(candles_1h, lookback=20)
        
        # Detect FVG
        fvg_1h = _detect_fvg(candles_1h, lookback=20)
        
        # Compute structure confidence
        confidence = 0.0
        notes: List[str] = []
        
        # +0.4 if structure clearly bullish or bearish
        if structure_1h in ["bullish", "bearish"]:
            confidence += 0.4
            notes.append(f"{structure_1h.upper()} structure on 1h")
        
        # +0.2 if OB + FVG agree with structure
        if order_block_1h != "none" and fvg_1h != "none":
            if (structure_1h == "bullish" and order_block_1h == "bullish" and fvg_1h == "bullish") or \
               (structure_1h == "bearish" and order_block_1h == "bearish" and fvg_1h == "bearish"):
                confidence += 0.2
                notes.append(f"OB + FVG aligned with {structure_1h} structure")
        
        # +0.1 if session supports volatility (London/NY Open)
        if session in ["London", "NY Open"]:
            confidence += 0.1
            notes.append(f"Active session: {session}")
        
        # +0.1 if equal highs/lows support coherent liquidity map
        if equal_highs_1h or equal_lows_1h:
            confidence += 0.1
            if equal_highs_1h:
                notes.append("Equal highs indicate resistance liquidity pool")
            if equal_lows_1h:
                notes.append("Equal lows indicate support liquidity pool")
        
        # Clamp confidence
        confidence = min(confidence, 1.0)
        
        # Add liquidity sweep confirmation if available
        if liquidity_sweeps_data:
            sweep_info = liquidity_sweeps_data.get(symbol, {})
            sweep_strength = sweep_info.get("strength", 0.0)
            if sweep_strength > 0.5:
                notes.append(f"Sweep strength {sweep_strength:.2f} confirms structure")
        
        if not notes:
            notes = ["Neutral structure context"]
        
        result[symbol] = {
            "session": session,
            "structure_1h": structure_1h,
            "equal_highs_1h": equal_highs_1h,
            "equal_lows_1h": equal_lows_1h,
            "order_block_1h": order_block_1h,
            "fvg_1h": fvg_1h,
            "structure_confidence": round(confidence, 2),
            "notes": notes,
        }
        
    except Exception as e:
        result[symbol] = {
            "session": "unknown",
            "structure_1h": "neutral",
            "equal_highs_1h": False,
            "equal_lows_1h": False,
            "order_block_1h": "none",
            "fvg_1h": "none",
            "structure_confidence": None,
            "notes": [f"Error: {str(e)}"],
        }
    
    return result


def run_market_structure_scan() -> Dict[str, Dict[str, Any]]:
    """
    Loads 1h (and optionally 15m/5m if needed), computes market structure
    and session classification per symbol, and writes JSON to
    reports/research/market_structure.json
    
    Returns:
        Dict mapping symbol to market structure data
    """
    from engine_alpha.core.paths import REPORTS
    from pathlib import Path
    import json
    from datetime import datetime, timezone
    
    RESEARCH_DIR = REPORTS / "research"
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    
    OUTPUT_PATH = RESEARCH_DIR / "market_structure.json"
    
    # Get enabled symbols (use same pattern as other research modules)
    try:
        from tools.intel_dashboard import load_symbol_registry
        symbols = load_symbol_registry()
    except Exception:
        # Fallback to common symbols
        symbols = [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "AVAXUSDT",
            "LINKUSDT", "DOTUSDT", "ADAUSDT", "ATOMUSDT", "XRPUSDT", "DOGEUSDT"
        ]
    
    # Load liquidity sweeps for cross-reference (optional)
    liquidity_sweeps_data = {}
    try:
        sweep_path = RESEARCH_DIR / "liquidity_sweeps.json"
        if sweep_path.exists():
            sweep_data = json.loads(sweep_path.read_text())
            liquidity_sweeps_data = sweep_data.get("symbols", {})
    except Exception:
        pass
    
    # Compute for each symbol
    all_results: Dict[str, Dict[str, Any]] = {}
    
    for symbol in symbols:
        try:
            symbol_result = compute_market_structure(symbol, liquidity_sweeps_data)
            all_results.update(symbol_result)
        except Exception as e:
            # Continue on error, add empty entry
            all_results[symbol] = {
                "session": "unknown",
                "structure_1h": "neutral",
                "equal_highs_1h": False,
                "equal_lows_1h": False,
                "order_block_1h": "none",
                "fvg_1h": "none",
                "structure_confidence": None,
                "notes": [f"Error processing {symbol}: {str(e)}"],
            }
    
    # Write output
    output_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbols": all_results,
    }
    
    try:
        OUTPUT_PATH.write_text(json.dumps(output_data, indent=2))
    except Exception as e:
        print(f"Warning: Failed to write market_structure.json: {e}")
    
    return all_results

