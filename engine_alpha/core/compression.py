"""
Compression/coil detection primitives.

Detects market compression (low volatility periods) using ATR% and Bollinger Band width.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List

from engine_alpha.core.atomic_io import atomic_write_json
from engine_alpha.core.paths import REPORTS


STATE_PATH = REPORTS / "compression_state.json"


def sma(values: List[float], n: int) -> float | None:
    """
    Simple Moving Average.
    
    Args:
        values: List of float values
        n: Window size
        
    Returns:
        SMA value or None if insufficient data
    """
    if not values or n <= 0 or len(values) < n:
        return None
    
    window = values[-n:]
    return sum(window) / len(window)


def stdev(values: List[float], n: int) -> float | None:
    """
    Population standard deviation.
    
    Args:
        values: List of float values
        n: Window size
        
    Returns:
        Standard deviation or None if insufficient data
    """
    if not values or n <= 0 or len(values) < n:
        return None
    
    window = values[-n:]
    mean = sum(window) / len(window)
    
    variance = sum((x - mean) ** 2 for x in window) / len(window)
    return math.sqrt(variance)


def true_range(high: float, low: float, prev_close: float | None) -> float | None:
    """
    True Range calculation.
    
    Args:
        high: Current high
        low: Current low
        prev_close: Previous close (or None)
        
    Returns:
        True Range value or None if prev_close missing
    """
    if prev_close is None:
        return None
    
    tr1 = high - low
    tr2 = abs(high - prev_close)
    tr3 = abs(low - prev_close)
    
    return max(tr1, tr2, tr3)


def atr(ohlcv: List[Dict[str, float]], n: int) -> float | None:
    """
    Average True Range.
    
    Args:
        ohlcv: List of dicts with keys: high, low, close
        n: Window size
        
    Returns:
        ATR value or None if insufficient data
    """
    if not ohlcv or len(ohlcv) < n + 1:
        return None
    
    # Compute TR series
    tr_values = []
    for i in range(1, len(ohlcv)):
        bar = ohlcv[i]
        prev_bar = ohlcv[i - 1]
        
        tr = true_range(
            bar.get("high", 0),
            bar.get("low", 0),
            prev_bar.get("close"),
        )
        if tr is not None:
            tr_values.append(tr)
    
    if len(tr_values) < n:
        return None
    
    # SMA of TR
    return sma(tr_values, n)


def atr_percent(ohlcv: List[Dict[str, float]], n_atr: int) -> float | None:
    """
    ATR as percentage of current close.
    
    Args:
        ohlcv: List of dicts with keys: high, low, close
        n_atr: Window size for ATR calculation
        
    Returns:
        ATR% = (ATR / close) * 100, or None if insufficient data
    """
    if not ohlcv:
        return None
    
    atr_val = atr(ohlcv, n_atr)
    if atr_val is None:
        return None
    
    current_close = ohlcv[-1].get("close")
    if current_close is None or current_close == 0:
        return None
    
    return (atr_val / current_close) * 100


def compression_ratio(current: float | None, baseline: float | None) -> float | None:
    """
    Compute compression ratio: current / baseline.
    
    Clamps to [0, 2] to avoid outliers.
    
    Args:
        current: Current value
        baseline: Baseline value
        
    Returns:
        Ratio (clamped to [0, 2]) or None if inputs invalid
    """
    if current is None or baseline is None or baseline == 0:
        return None
    
    ratio = current / baseline
    return max(0.0, min(2.0, ratio))


def bb_width_percent(closes: List[float], n: int, k: float = 2.0) -> float | None:
    """
    Bollinger Band width as percentage of middle band.
    
    Args:
        closes: List of close prices
        n: Window size for SMA/stddev
        k: Standard deviation multiplier (default 2.0)
        
    Returns:
        BB width % = ((upper - lower) / mid) * 100, or None if insufficient data
    """
    if not closes or len(closes) < n:
        return None
    
    mid = sma(closes, n)
    if mid is None or mid == 0:
        return None
    
    sd = stdev(closes, n)
    if sd is None:
        return None
    
    upper = mid + k * sd
    lower = mid - k * sd
    width = upper - lower
    
    return (width / mid) * 100


def score_compression(atr_ratio: float | None, bb_ratio: float | None) -> float | None:
    """
    Compute compression score (0-1) combining ATR and BB compression.
    
    Args:
        atr_ratio: ATR compression ratio (current/baseline)
        bb_ratio: BB width compression ratio (current/baseline)
        
    Returns:
        Compression score (0-1), or None if inputs invalid
    """
    if atr_ratio is None or bb_ratio is None:
        return None
    
    # Convert ratios to "compression-ness"
    # Lower ratio = more compressed
    # atr_comp = 1 - ratio when ratio <= 1, else 0
    atr_comp = max(0.0, min(1.0, 1.0 - atr_ratio)) if atr_ratio <= 1.0 else 0.0
    bb_comp = max(0.0, min(1.0, 1.0 - bb_ratio)) if bb_ratio <= 1.0 else 0.0
    
    # Weighted average
    score = 0.5 * atr_comp + 0.5 * bb_comp
    
    return score


def load_comp_state(path: Path | str = STATE_PATH) -> Dict[str, Any]:
    """
    Load compression state from JSON file.
    
    Returns empty dict if file is missing or invalid.
    
    Args:
        path: Path to state file
        
    Returns:
        Dict with structure: {"in_compression": bool, "entered_ts": str|None, "last_ts": str|None}
    """
    path_obj = Path(path)
    
    if not path_obj.exists():
        return {}
    
    try:
        content = path_obj.read_text(encoding="utf-8")
        if not content.strip():
            return {}
        return json.loads(content)
    except (json.JSONDecodeError, IOError):
        return {}


def save_comp_state(state: Dict[str, Any], path: Path | str = STATE_PATH) -> None:
    """
    Save compression state atomically.
    
    Args:
        state: State dict
        path: Path to state file
    """
    atomic_write_json(path, state)


def update_time_in_compression(
    state: Dict[str, Any],
    ts_iso: str,
    is_compressed: bool,
    threshold_score: float = 0.6,
) -> tuple[Dict[str, Any], float | None]:
    """
    Update time-in-compression tracking.
    
    Args:
        state: Current state dict (will be modified)
        ts_iso: Current ISO timestamp
        is_compressed: Whether currently compressed (score >= threshold)
        threshold_score: Threshold for compression (default 0.6)
        
    Returns:
        Tuple of (updated_state, time_in_compression_s)
        - time_in_compression_s: Seconds since entering compression, or None if not compressed
    """
    from datetime import datetime, timezone
    
    updated_state = dict(state)
    
    # Initialize state if needed
    if "in_compression" not in updated_state:
        updated_state["in_compression"] = False
        updated_state["entered_ts"] = None
        updated_state["last_ts"] = None
    
    was_compressed = updated_state.get("in_compression", False)
    
    if is_compressed:
        # Entering compression from non-compressed state
        if not was_compressed:
            updated_state["in_compression"] = True
            updated_state["entered_ts"] = ts_iso
            updated_state["last_ts"] = ts_iso
            return updated_state, 0.0
        
        # Staying compressed - compute time elapsed
        updated_state["last_ts"] = ts_iso
        entered_ts = updated_state.get("entered_ts")
        
        if entered_ts:
            try:
                entered_dt = datetime.fromisoformat(entered_ts.replace("Z", "+00:00"))
                current_dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
                time_s = (current_dt - entered_dt).total_seconds()
                return updated_state, max(0.0, time_s)
            except (ValueError, TypeError):
                return updated_state, None
        else:
            return updated_state, None
    else:
        # Leaving compression
        if was_compressed:
            updated_state["in_compression"] = False
            updated_state["entered_ts"] = None
            updated_state["last_ts"] = ts_iso
        
        return updated_state, None

