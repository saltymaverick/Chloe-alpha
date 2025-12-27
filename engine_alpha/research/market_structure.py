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

import json
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timezone

try:
    import numpy as np
except ImportError:
    np = None

from engine_alpha.core.paths import REPORTS, DATA
from engine_alpha.core.symbol_registry import load_symbol_registry
from engine_alpha.data.live_prices import get_live_ohlcv
from engine_alpha.data.historical_prices import load_ohlcv_csv

REPORTS_DIR = REPORTS / "research"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


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


def load_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 150) -> List[Dict[str, Any]]:
    """
    Loads OHLCV for the symbol and timeframe.
    
    Tries:
    1. Live OHLCV from exchanges
    2. Historical CSV files
    
    Returns list of dict bars or [] if missing.
    """
    candles: List[Dict[str, Any]] = []
    
    # Try live OHLCV first
    try:
        live_candles = get_live_ohlcv(symbol, timeframe, limit=limit)
        if live_candles and isinstance(live_candles, list):
            candles = live_candles[-limit:]
            if candles:
                return candles
    except Exception:
        pass
    
    # Fallback: try historical CSV
    try:
        csv_candles = load_ohlcv_csv(symbol, timeframe)
        if csv_candles:
            candles = csv_candles[-limit:]
            if candles:
                return candles
    except Exception:
        pass
    
    return candles


def detect_swings(bars: List[Dict[str, Any]]) -> Tuple[List[int], List[int]]:
    """
    Basic swing detection for 1h candles:
    swing high: high[i] > high[i-1] and high[i] > high[i+1]
    swing low:  low[i] < low[i-1] and low[i] < low[i+1]
    
    Returns (swing_highs, swing_lows) as lists of indices.
    """
    swing_highs: List[int] = []
    swing_lows: List[int] = []
    
    if len(bars) < 3:
        return swing_highs, swing_lows
    
    for i in range(1, len(bars) - 1):
        h_prev = float(bars[i-1].get("high", 0))
        h = float(bars[i].get("high", 0))
        h_next = float(bars[i+1].get("high", 0))
        
        l_prev = float(bars[i-1].get("low", 0))
        l = float(bars[i].get("low", 0))
        l_next = float(bars[i+1].get("low", 0))
        
        if h > h_prev and h > h_next:
            swing_highs.append(i)
        if l < l_prev and l < l_next:
            swing_lows.append(i)
    
    return swing_highs, swing_lows


def classify_structure(bars: List[Dict[str, Any]]) -> Tuple[str, List[int], List[int]]:
    """
    Classifies 1h structure as bullish, bearish, neutral.
    Looks at last 2 swing highs and lows.
    """
    if len(bars) < 50:
        return "neutral", [], []
    
    swings_h, swings_l = detect_swings(bars)
    if len(swings_h) < 2 or len(swings_l) < 2:
        return "neutral", swings_h, swings_l
    
    h1 = float(bars[swings_h[-2]].get("high", 0))
    h2 = float(bars[swings_h[-1]].get("high", 0))
    l1 = float(bars[swings_l[-2]].get("low", 0))
    l2 = float(bars[swings_l[-1]].get("low", 0))
    
    if h2 > h1 and l2 > l1:
        return "bullish", swings_h, swings_l
    if h2 < h1 and l2 < l1:
        return "bearish", swings_h, swings_l
    
    return "neutral", swings_h, swings_l


def detect_equal_levels(
    bars: List[Dict[str, Any]],
    swings_h: List[int],
    swings_l: List[int],
    tol: float = 0.001,
) -> Tuple[bool, bool]:
    """
    Detects equal highs/lows within tolerance.
    tol = 0.001 = 0.1%
    """
    equal_highs = False
    equal_lows = False
    
    if len(swings_h) >= 2:
        for i in range(len(swings_h) - 1):
            h1 = float(bars[swings_h[i]].get("high", 0))
            h2 = float(bars[swings_h[i+1]].get("high", 0))
            if h1 > 0 and h2 > 0:
                if abs(h1 - h2) / max(h1, h2) < tol:
                    equal_highs = True
                    break
    
    if len(swings_l) >= 2:
        for i in range(len(swings_l) - 1):
            l1 = float(bars[swings_l[i]].get("low", 0))
            l2 = float(bars[swings_l[i+1]].get("low", 0))
            if l1 > 0 and l2 > 0:
                if abs(l1 - l2) / max(l1, l2) < tol:
                    equal_lows = True
                    break
    
    return equal_highs, equal_lows


def detect_simple_order_block(bars: List[Dict[str, Any]]) -> str:
    """
    Simple OB detection:
    - Look for last large impulse (range > 1.5 * avg range)
    - Mark prior opposite candle as OB
    """
    if len(bars) < 20:
        return "none"
    
    ranges = [float(b.get("high", 0)) - float(b.get("low", 0)) for b in bars]
    if not ranges or all(r <= 0 for r in ranges):
        return "none"
    
    avg_range = sum(ranges) / len(ranges) if ranges else 0.0
    if avg_range <= 0:
        return "none"
    
    impulse_idx = None
    
    for i in range(len(bars) - 1, 1, -1):
        candle_range = float(bars[i].get("high", 0)) - float(bars[i].get("low", 0))
        if candle_range > 1.5 * avg_range:
            impulse_idx = i
            break
    
    if impulse_idx is None or impulse_idx < 1:
        return "none"
    
    prev = bars[impulse_idx - 1]
    prev_open = float(prev.get("open", 0))
    prev_close = float(prev.get("close", 0))
    
    if prev_close < prev_open:
        return "bullish"
    else:
        return "bearish"


def detect_fvg(bars: List[Dict[str, Any]]) -> str:
    """
    Detect 1h FVG:
    bullish FVG: low[n] > high[n-2]
    bearish FVG: high[n] < low[n-2]
    """
    if len(bars) < 3:
        return "none"
    
    n = len(bars) - 1
    b0 = bars[n]
    b2 = bars[n - 2]
    
    b0_low = float(b0.get("low", 0))
    b2_high = float(b2.get("high", 0))
    b0_high = float(b0.get("high", 0))
    b2_low = float(b2.get("low", 0))
    
    if b0_low > b2_high and b0_low > 0 and b2_high > 0:
        return "bullish"
    if b0_high < b2_low and b0_high > 0 and b2_low > 0:
        return "bearish"
    
    return "none"


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


def classify_session() -> str:
    """Based on current UTC time. Uses _detect_session helper."""
    return _detect_session(datetime.now(timezone.utc))


def detect_choch(bars: List[Dict[str, Any]], swings_h: List[int], swings_l: List[int]) -> Tuple[bool, float]:
    """
    Detect Change of Character (CHoCH) - v2 enhanced.
    
    CHoCH occurs when:
    - Bullish CHoCH: Price breaks above a previous swing high (BOS) then breaks below a swing low
    - Bearish CHoCH: Price breaks below a previous swing low (BOS) then breaks above a swing high
    
    Returns:
        (choch_recent: bool, choch_quality: float 0-1)
    """
    if len(bars) < 20 or len(swings_h) < 2 or len(swings_l) < 2:
        return False, 0.0
    
    # Get latest price
    latest_close = float(bars[-1].get("close", 0))
    if latest_close <= 0:
        return False, 0.0
    
    # Get recent swing levels
    recent_swing_high = float(bars[swings_h[-1]].get("high", 0)) if swings_h else 0.0
    prev_swing_high = float(bars[swings_h[-2]].get("high", 0)) if len(swings_h) >= 2 else 0.0
    recent_swing_low = float(bars[swings_l[-1]].get("low", 0)) if swings_l else 0.0
    prev_swing_low = float(bars[swings_l[-2]].get("low", 0)) if len(swings_l) >= 2 else 0.0
    
    choch_recent = False
    choch_quality = 0.0
    
    # Check for bullish CHoCH: broke above high, then broke below low
    if recent_swing_high > prev_swing_high:  # BOS occurred
        # Check if price has since broken below a swing low
        if recent_swing_low < prev_swing_low and latest_close < recent_swing_low:
            choch_recent = True
            # Quality based on how clean the break was
            distance_below = (recent_swing_low - latest_close) / recent_swing_low if recent_swing_low > 0 else 0.0
            choch_quality = min(1.0, distance_below * 100)  # Normalize
    
    # Check for bearish CHoCH: broke below low, then broke above high
    if recent_swing_low < prev_swing_low:  # BOS occurred
        # Check if price has since broken above a swing high
        if recent_swing_high > prev_swing_high and latest_close > recent_swing_high:
            choch_recent = True
            # Quality based on how clean the break was
            distance_above = (latest_close - recent_swing_high) / recent_swing_high if recent_swing_high > 0 else 0.0
            choch_quality = min(1.0, distance_above * 100)  # Normalize
    
    return choch_recent, choch_quality


def compute_structure_conf(
    structure: str,
    eqh: bool,
    eql: bool,
    ob: str,
    fvg: str,
    session: str,
    choch_recent: bool = False,
    choch_quality: float = 0.0,
    bars: Optional[List[Dict[str, Any]]] = None,
) -> float:
    """
    Compute structure confidence score 0.0-1.0 (v2 enhanced).
    
    v2 improvements:
    - Considers CHoCH signals
    - More nuanced confidence based on distance from swing levels
    - Better session weighting
    """
    score = 0.0
    
    # Base structure score
    if structure in ("bullish", "bearish"):
        score += 0.4
    else:
        return 0.3  # Neutral structure gets low confidence
    
    # Alignment bonuses
    if structure == "bullish":
        if ob == "bullish":
            score += 0.15
        if fvg == "bullish":
            score += 0.15
        # CHoCH reduces confidence for bullish structure
        if choch_recent:
            score -= 0.1 * (1.0 - choch_quality)  # Penalty based on CHoCH quality
    
    if structure == "bearish":
        if ob == "bearish":
            score += 0.15
        if fvg == "bearish":
            score += 0.15
        # CHoCH reduces confidence for bearish structure
        if choch_recent:
            score -= 0.1 * (1.0 - choch_quality)  # Penalty based on CHoCH quality
    
    # Equal levels add context
    if eqh or eql:
        score += 0.05
    
    # Session favorability (v2: more nuanced)
    if session == "London":
        score += 0.1
    elif session == "NY_Open":
        score += 0.08
    elif session == "NY_Close":
        score += 0.05
    # Asia gets no bonus (typically lower volatility)
    
    # v2: Distance from swing levels (if bars available)
    if bars and len(bars) >= 10:
        try:
            latest_close = float(bars[-1].get("close", 0))
            if latest_close > 0:
                # Get recent swing high/low
                swings_h, swings_l = detect_swings(bars)
                if swings_h and swings_l:
                    recent_high = float(bars[swings_h[-1]].get("high", 0))
                    recent_low = float(bars[swings_l[-1]].get("low", 0))
                    
                    if structure == "bullish" and recent_high > 0:
                        # Higher confidence if price is well above swing low
                        distance_above_low = (latest_close - recent_low) / recent_low if recent_low > 0 else 0.0
                        score += min(0.1, distance_above_low * 2.0)  # Cap at 0.1
                    
                    if structure == "bearish" and recent_low > 0:
                        # Higher confidence if price is well below swing high
                        distance_below_high = (recent_high - latest_close) / recent_high if recent_high > 0 else 0.0
                        score += min(0.1, distance_below_high * 2.0)  # Cap at 0.1
        except Exception:
            pass  # Ignore errors in distance calculation
    
    return float(max(0.0, min(score, 1.0)))


def run_market_structure_scan() -> Dict[str, Dict[str, Any]]:
    """
    Loads 1h (and optionally 15m/5m if needed), computes market structure
    and session classification per symbol, and writes JSON to
    reports/research/market_structure.json
    """
    symbols = load_symbol_registry()
    
    results: Dict[str, Dict[str, Any]] = {}
    session = classify_session()
    
    for sym in symbols:
        bars = load_ohlcv(sym, "1h", limit=150)
        
        # Determine session from latest bar timestamp or current time
        latest_bar_ts = None
        if bars:
            try:
                latest_bar_ts_str = bars[-1].get("ts", "")
                if latest_bar_ts_str:
                    # Try parsing ISO format
                    latest_bar_ts = datetime.fromisoformat(latest_bar_ts_str.replace("Z", "+00:00"))
            except Exception:
                pass
        
        ts = latest_bar_ts or datetime.now(timezone.utc)
        session = _detect_session(ts)
        
        if len(bars) < 20:
            results[sym] = {
                "session": "unknown",
                "structure_1h": "neutral",
                "equal_highs_1h": False,
                "equal_lows_1h": False,
                "order_block_1h": "none",
                "fvg_1h": "none",
                "structure_confidence": None,
                "notes": ["Insufficient 1h data to determine structure."],
            }
            continue
        
        structure, swings_h, swings_l = classify_structure(bars)
        eqh, eql = detect_equal_levels(bars, swings_h, swings_l)
        ob = detect_simple_order_block(bars)
        fvg = detect_fvg(bars)
        
        # v2: Detect CHoCH
        choch_recent, choch_quality = detect_choch(bars, swings_h, swings_l)
        
        conf = compute_structure_conf(structure, eqh, eql, ob, fvg, session, choch_recent, choch_quality, bars)
        
        note_list: List[str] = []
        if structure == "bullish":
            note_list.append("HH/HL bullish structure.")
        elif structure == "bearish":
            note_list.append("LH/LL bearish structure.")
        else:
            note_list.append("Neutral or choppy structure.")
        
        if ob != "none":
            note_list.append(f"Detected {ob} order block.")
        if fvg != "none":
            note_list.append(f"Detected {fvg} FVG.")
        if eqh:
            note_list.append("Equal highs present.")
        if eql:
            note_list.append("Equal lows present.")
        
        results[sym] = {
            "session": session,
            "structure_1h": structure,
            "equal_highs_1h": eqh,
            "equal_lows_1h": eql,
            "order_block_1h": ob,
            "fvg_1h": fvg,
            "structure_confidence": round(conf, 2),
            "choch_recent": choch_recent,  # v2 field
            "choch_quality": round(choch_quality, 2) if choch_recent else None,  # v2 field
            "notes": note_list,
        }
    
    # Compute health
    health_status = "ok"
    health_reasons = []
    
    unknown_sessions = sum(1 for r in results.values() if r.get("session") == "unknown")
    if unknown_sessions == len(results) and len(results) > 0:
        health_status = "degraded"
        health_reasons.append("unknown_session_for_all")
    
    out = {
        "version": "v2.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "health": {
            "status": health_status,
            "reasons": health_reasons,
        },
        "symbols": results,
    }
    
    output_path = REPORTS_DIR / "market_structure.json"
    output_path.write_text(json.dumps(out, indent=2))
    
    return results

