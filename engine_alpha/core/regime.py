"""
Price-based regime classifier - Phase 53
Classifies market regime using OHLCV price data directly with enhanced movement metrics.

Features:
- Slope, acceleration, jerk (velocity derivatives)
- ATR%, volatility expansion
- Body/wick ratios, impulse (body/ATR)
- Displacement from EMA
- Higher high / lower low structure
- RSI collapse detection
- Velocity of move

Regimes: panic_down, trend_down, trend_up, high_vol, chop
"""

from __future__ import annotations
from typing import Literal, Dict, Any, List, Tuple
import math

Regime = Literal["chop", "trend_up", "trend_down", "high_vol", "panic_down"]


def _to_floats(seq):
    """Convert sequence to floats, skipping invalid values."""
    out = []
    for x in seq:
        try:
            out.append(float(x))
        except Exception:
            pass
    return out


def compute_regime_metrics(rows: List[dict]) -> Dict[str, Any]:
    """
    Given a list of OHLCV rows (dicts with open, high, low, close, ts),
    compute regime-relevant metrics:

    - slope: signed % change over window
    - vol: std dev of returns
    - atr: average true range as % of price
    - accel: change in slope between early and late half
    - body_wick_ratio: median |close-open| / (high-low)
    - hh_ll_down: count of consecutive lower highs + lower lows
    - rsi_14: basic RSI estimate
    - velocity: average absolute return per bar
    - jerk: change in acceleration (third-order derivative)
    - displacement: distance from EMA in ATR units
    - impulse: median body size relative to ATR
    - vol_expansion: current ATR vs historical ATR ratio
    """
    if len(rows) < 5:
        return {
            "slope": 0.0,
            "vol": 0.0,
            "atr_pct": 0.0,
            "accel": 0.0,
            "body_wick_ratio": 0.0,
            "hh_ll_down": 0,
            "rsi_14": 50.0,
            "velocity": 0.0,
            "jerk": 0.0,
            "displacement": 0.0,
            "impulse": 0.0,
            "vol_expansion": 1.0,
        }

    closes = _to_floats([r.get("close") for r in rows])
    opens = _to_floats([r.get("open") for r in rows])
    highs = _to_floats([r.get("high") for r in rows])
    lows = _to_floats([r.get("low") for r in rows])

    if not closes or len(closes) < 2:
        return {
            "slope": 0.0,
            "vol": 0.0,
            "atr_pct": 0.0,
            "accel": 0.0,
            "body_wick_ratio": 0.0,
            "hh_ll_down": 0,
            "rsi_14": 50.0,
            "velocity": 0.0,
            "jerk": 0.0,
            "displacement": 0.0,
            "impulse": 0.0,
            "vol_expansion": 1.0,
        }

    n = len(closes)
    p0, p1 = closes[0], closes[-1]
    slope = (p1 - p0) / p0 if p0 else 0.0

    rets = []
    for i in range(1, n):
        if closes[i-1]:
            rets.append((closes[i] - closes[i-1]) / closes[i-1])
    if rets:
        mu = sum(rets) / len(rets)
        vol = math.sqrt(sum((r - mu)**2 for r in rets) / len(rets)) if len(rets) > 1 else 0.0
    else:
        vol = 0.0

    trs = []
    for i in range(n):
        high = highs[i] if i < len(highs) else closes[i]
        low = lows[i] if i < len(lows) else closes[i]
        prev_close = closes[i-1] if i > 0 else closes[i]
        trs.append(max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        ))
    atr = sum(trs) / len(trs) if trs else 0.0
    atr_pct = atr / closes[-1] if closes[-1] else 0.0

    mid = n // 2
    slow = (closes[mid] - closes[0]) / closes[0] if closes[0] and mid > 0 else 0.0
    fast = (closes[-1] - closes[mid]) / closes[mid] if closes[mid] and mid < n - 1 else 0.0
    accel = fast - slow

    body_ratios = []
    for i in range(min(len(opens), len(highs), len(lows), len(closes))):
        o = opens[i]
        h = highs[i]
        l = lows[i]
        c = closes[i]
        rng = h - l
        body = abs(c - o)
        if rng > 0:
            body_ratios.append(body / rng)
    body_wick_ratio = sorted(body_ratios)[len(body_ratios)//2] if body_ratios else 0.0

    hh_ll_down = 0
    for i in range(1, min(len(highs), len(lows))):
        if highs[i] <= highs[i-1] and lows[i] <= lows[i-1]:
            hh_ll_down += 1

    # Simple RSI(14)-like estimate
    period = min(14, len(closes) - 1)
    gains, losses = 0.0, 0.0
    for i in range(max(1, n - period), n):
        if i > 0:
            delta = closes[i] - closes[i-1]
            if delta > 0:
                gains += delta
            elif delta < 0:
                losses += abs(delta)
    if losses > 0:
        rs = gains / losses
        rsi_14 = 100 - (100 / (1 + rs))
    else:
        rsi_14 = 70.0 if gains > 0 else 50.0

    # Velocity: average absolute return per bar
    abs_rets = [abs(r) for r in rets] if rets else []
    velocity = sum(abs_rets) / len(abs_rets) if abs_rets else 0.0

    # Jerk: change in acceleration (third-order derivative)
    # Compute slope over first third, middle third, last third
    jerk = 0.0
    if n >= 6:
        third = n // 3
        if third > 0:
            # First third slope
            p_first = closes[third] if third < n else closes[0]
            slope_first = (p_first - closes[0]) / closes[0] if closes[0] else 0.0
            # Middle third slope
            p_mid = closes[2 * third] if 2 * third < n else closes[third]
            slope_mid = (p_mid - p_first) / p_first if p_first else 0.0
            # Last third slope
            slope_last = (closes[-1] - p_mid) / p_mid if p_mid else 0.0
            # Jerk = (slope_last - slope_mid) - (slope_mid - slope_first)
            jerk = (slope_last - slope_mid) - (slope_mid - slope_first)

    # Displacement: distance from EMA in ATR units
    displacement = 0.0
    if atr > 0 and n >= 5:
        # Simple EMA with alpha = 2/(N+1)
        alpha = 2.0 / (n + 1)
        ema = closes[0]
        for i in range(1, n):
            ema = alpha * closes[i] + (1 - alpha) * ema
        displacement = abs(closes[-1] - ema) / atr if atr > 0 else 0.0

    # Impulse: median body size relative to ATR
    impulse = 0.0
    if atr > 0:
        impulses = []
        for i in range(min(len(opens), len(closes))):
            body = abs(closes[i] - opens[i])
            impulses.append(body / atr)
        impulse = sorted(impulses)[len(impulses)//2] if impulses else 0.0

    # Vol expansion: current ATR vs historical ATR ratio
    vol_expansion = 1.0
    if len(rows) >= 40:  # Need enough data for comparison
        # Current window ATR (already computed)
        current_atr_pct = atr_pct
        # Previous window ATR (earlier 20 bars)
        prev_rows = rows[:20] if len(rows) >= 40 else rows[:len(rows)//2]
        prev_closes = _to_floats([r.get("close") for r in prev_rows])
        prev_highs = _to_floats([r.get("high") for r in prev_rows])
        prev_lows = _to_floats([r.get("low") for r in prev_rows])
        if len(prev_closes) >= 5:
            prev_trs = []
            for i in range(len(prev_closes)):
                high = prev_highs[i] if i < len(prev_highs) else prev_closes[i]
                low = prev_lows[i] if i < len(prev_lows) else prev_closes[i]
                prev_close = prev_closes[i-1] if i > 0 else prev_closes[i]
                prev_trs.append(max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close),
                ))
            prev_atr = sum(prev_trs) / len(prev_trs) if prev_trs else 0.0
            prev_atr_pct = prev_atr / prev_closes[-1] if prev_closes and prev_closes[-1] else 0.0
            if prev_atr_pct > 0:
                vol_expansion = current_atr_pct / prev_atr_pct

    return {
        "slope": slope,
        "vol": vol,
        "atr_pct": atr_pct,
        "accel": accel,
        "body_wick_ratio": body_wick_ratio,
        "hh_ll_down": hh_ll_down,
        "rsi_14": rsi_14,
        "velocity": velocity,
        "jerk": jerk,
        "displacement": displacement,
        "impulse": impulse,
        "vol_expansion": vol_expansion,
    }


def classify_regime(rows: List[dict]) -> Dict[str, Any]:
    """
    Classify regime into one of:
    - "panic_down"  (flush)
    - "trend_down"
    - "trend_up"
    - "high_vol"
    - "chop"

    Returns {"regime": <label>, "metrics": {..}}.
    """
    metrics = compute_regime_metrics(rows)
    slope = metrics["slope"]
    atr_pct = metrics["atr_pct"]
    accel = metrics["accel"]
    body_ratio = metrics["body_wick_ratio"]
    hh_ll_down = metrics["hh_ll_down"]
    rsi_14 = metrics["rsi_14"]
    velocity = metrics["velocity"]
    jerk = metrics["jerk"]
    displacement = metrics["displacement"]
    impulse = metrics["impulse"]
    vol_expansion = metrics["vol_expansion"]

    # Parameter heuristics – tunable thresholds for 1h ETH
    # Module-level constants for later tuning
    PANIC_MOVE = -0.05      # -5% over window
    TREND_MOVE = 0.02       # ±2%
    HIGH_ATR = 0.02         # 2% ATR
    STRONG_BODY = 0.6
    HHLL_DOWN_MIN = 3
    RSI_PANIC = 30.0
    VEL_PANIC = 0.01        # 1% avg move per bar
    DISP_PANIC = 1.5        # close is 1.5 ATR away from EMA
    VOL_EXP_PANIC = 1.5     # ATR% expanded vs history
    IMPULSE_STRONG = 1.0    # body ~ ATR

    regime: Regime

    # Panic flush: strong, fast down with multiple confirmations
    # Require multiple conditions to keep panic_down rare and meaningful
    panic_conditions = [
        slope <= PANIC_MOVE,
        atr_pct >= HIGH_ATR,
        hh_ll_down >= HHLL_DOWN_MIN,
        rsi_14 <= RSI_PANIC,
        velocity >= VEL_PANIC,
        displacement >= DISP_PANIC,
        vol_expansion >= VOL_EXP_PANIC,
        impulse >= IMPULSE_STRONG,
    ]
    # Require at least 6 out of 8 conditions for panic_down
    if sum(panic_conditions) >= 6:
        regime = "panic_down"
    # Trend down: medium sustained move down with structure
    elif (slope <= -TREND_MOVE and 
          hh_ll_down >= 2 and 
          rsi_14 <= 45 and  # mildly low
          body_ratio >= 0.4 and
          velocity > 0.003):  # 0.3% avg per bar
        regime = "trend_down"
    # Trend up: sustained move up with momentum
    elif (slope >= TREND_MOVE and
          rsi_14 >= 55 and
          body_ratio >= 0.4 and
          velocity > 0.003):  # 0.3% avg per bar
        regime = "trend_up"
    # High volatility but not clear direction
    elif (atr_pct >= HIGH_ATR and
          -TREND_MOVE < slope < TREND_MOVE):  # direction not strong
        regime = "high_vol"
    else:
        regime = "chop"

    return {"regime": regime, "metrics": metrics}


def confirm_trend(rows: List[dict], regime: str, metrics: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Confirm whether the price action truly supports a trend regime.
    
    Uses shorter windows (e.g. 3, 5, 7 bars) to validate:
    - persistent slope in same direction,
    - acceleration in that direction,
    - HH/LL pattern,
    - sufficient velocity.
    
    Returns (confirmed: bool, detail: dict).
    """
    n = len(rows)
    if n < 7:
        return False, {"reason": "not_enough_bars"}
    
    closes = [float(r["close"]) for r in rows if r.get("close") is not None]
    if len(closes) < 7:
        return False, {"reason": "not_enough_closes"}
    
    # Use last 7 bars for confirmation window
    w7 = closes[-7:]
    w5 = closes[-5:]
    w3 = closes[-3:]
    
    def _slope(seq):
        if not seq or seq[0] == 0:
            return 0.0
        return (seq[-1] - seq[0]) / seq[0]
    
    slope7 = _slope(w7)
    slope5 = _slope(w5)
    slope3 = _slope(w3)
    
    # Derive short-window HH/LL structure
    hh = 0
    ll = 0
    highs = [float(r["high"]) for r in rows if r.get("high") is not None]
    lows = [float(r["low"]) for r in rows if r.get("low") is not None]
    if len(highs) >= 7 and len(lows) >= 7:
        h7 = highs[-7:]
        l7 = lows[-7:]
        for i in range(1, len(h7)):
            if h7[i] > h7[i-1]:
                hh += 1
            if l7[i] < l7[i-1]:
                ll += 1
    
    velocity = metrics.get("velocity", 0.0)
    accel = metrics.get("accel", 0.0)
    
    confirmed = False
    detail = {
        "slope7": slope7,
        "slope5": slope5,
        "slope3": slope3,
        "hh": hh,
        "ll": ll,
        "velocity": velocity,
        "accel": accel,
    }
    
    # Tuning parameters (heuristics for 1h ETH)
    MIN_TREND_SLOPE7 = 0.02   # 2% up/down over 7 bars
    MIN_VELOCITY = 0.004      # 0.4% average per bar
    MIN_HHLL_COUNT = 3        # at least 3 HH or LL in last 7
    
    if regime == "trend_up":
        if (
            slope7 >= MIN_TREND_SLOPE7 and
            slope5 >= 0 and
            slope3 >= 0 and
            accel >= 0 and
            velocity >= MIN_VELOCITY and
            hh >= MIN_HHLL_COUNT
        ):
            confirmed = True
            detail["reason"] = "trend_up_confirmed"
        else:
            detail["reason"] = "trend_up_unconfirmed"
    
    elif regime == "trend_down":
        if (
            slope7 <= -MIN_TREND_SLOPE7 and
            slope5 <= 0 and
            slope3 <= 0 and
            accel <= 0 and
            velocity >= MIN_VELOCITY and
            ll >= MIN_HHLL_COUNT
        ):
            confirmed = True
            detail["reason"] = "trend_down_confirmed"
        else:
            detail["reason"] = "trend_down_unconfirmed"
    
    else:
        # Only trend_up/trend_down use this confirmation; others treated separately.
        detail["reason"] = "not_trend_regime"
    
    return confirmed, detail


# Legacy support: Keep old RegimeClassifier for backward compatibility
# This is used by confidence_engine.decide() which doesn't have OHLCV data
import collections
from typing import Optional
from statistics import mean, stdev


class RegimeClassifier:
    """Legacy signal-based regime classifier (kept for backward compatibility)."""
    
    def __init__(self, window_size: int = 100):
        """
        Initialize regime classifier.
        
        Args:
            window_size: Size of rolling window for z-score calculation
        """
        self.window_size = window_size
        self.atrp_history: collections.deque = collections.deque(maxlen=window_size)
        self.bb_width_history: collections.deque = collections.deque(maxlen=window_size)
        self.ret_g5_history: collections.deque = collections.deque(maxlen=window_size)
    
    def _compute_z_score(self, value: float, history: collections.deque) -> float:
        """
        Compute z-score of value relative to history.
        
        Args:
            value: Current value
            history: Historical values deque
        
        Returns:
            Z-score (fallback to 0.0 if insufficient history)
        """
        if len(history) < 2:
            return 0.0
        
        hist_list = list(history)
        hist_mean = mean(hist_list)
        hist_std = stdev(hist_list) if len(hist_list) > 1 else 1.0
        
        if hist_std == 0:
            return 0.0
        
        return (value - hist_mean) / hist_std
    
    def classify(self, signal_vector: List[float], raw_registry: Dict[str, Any]) -> Dict[str, Any]:
        """
        Classify market regime.
        
        Args:
            signal_vector: Normalized signal vector (order: Ret_G5, RSI_14, MACD_Hist, VWAP_Dist, ATRp, BB_Width, ...)
            raw_registry: Raw signal registry with values keyed by signal name
        
        Returns:
            Dictionary with "regime" key ("trend", "chop", or "high_vol")
        """
        # Extract values from raw_registry (preferred) or signal_vector
        atrp_value = raw_registry.get("ATRp", {}).get("value", 0.0)
        bb_width_value = raw_registry.get("BB_Width", {}).get("value", 0.0)
        ret_g5_value = raw_registry.get("Ret_G5", {}).get("value", 0.0)
        
        # If not in raw_registry, try to get from signal_vector by position
        # Order: Ret_G5(0), RSI_14(1), MACD_Hist(2), VWAP_Dist(3), ATRp(4), BB_Width(5), ...
        if atrp_value == 0.0 and len(signal_vector) > 4:
            # Use normalized values as fallback (but less ideal)
            atrp_value = signal_vector[4] if len(signal_vector) > 4 else 0.0
        if bb_width_value == 0.0 and len(signal_vector) > 5:
            bb_width_value = signal_vector[5] if len(signal_vector) > 5 else 0.0
        if ret_g5_value == 0.0 and len(signal_vector) > 0:
            ret_g5_value = signal_vector[0] if len(signal_vector) > 0 else 0.0
        
        # Update history
        self.atrp_history.append(atrp_value)
        self.bb_width_history.append(bb_width_value)
        self.ret_g5_history.append(abs(ret_g5_value))  # Use absolute value for Ret_G5
        
        # Compute z-scores
        atrp_z = self._compute_z_score(atrp_value, self.atrp_history)
        bb_width_z = self._compute_z_score(bb_width_value, self.bb_width_history)
        ret_g5_z = self._compute_z_score(abs(ret_g5_value), self.ret_g5_history)
        
        # Classify regime
        # Rule 1: high_vol if BB_Width z > 0.8 OR ATRp z > 0.8
        if abs(bb_width_z) > 0.8 or abs(atrp_z) > 0.8:
            regime = "high_vol"
        # Rule 2: trend if |Ret_G5| z > 0.6 and not high_vol
        elif abs(ret_g5_z) > 0.6:
            regime = "trend"
        # Rule 3: else chop
        else:
            regime = "chop"
        
        return {
            "regime": regime,
            "z_scores": {
                "atrp": atrp_z,
                "bb_width": bb_width_z,
                "ret_g5": ret_g5_z
            }
        }


def get_regime(signal_vector: List[float], raw_registry: Dict[str, Any], 
               classifier: Optional[RegimeClassifier] = None) -> Dict[str, Any]:
    """
    Get market regime classification (legacy signal-based method).
    
    Args:
        signal_vector: Normalized signal vector
        raw_registry: Raw signal registry
        classifier: Optional RegimeClassifier instance (creates new one if None)
    
    Returns:
        Dictionary with "regime" key
    """
    if classifier is None:
        classifier = RegimeClassifier()
    
    return classifier.classify(signal_vector, raw_registry)
