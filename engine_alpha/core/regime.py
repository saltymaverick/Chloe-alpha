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
from typing import Literal, Dict, Any, List, Tuple, Optional
import math

Regime = Literal["chop", "trend_up", "trend_down", "high_vol", "panic_down"]  # panic_down kept for backward compat, but new classifier doesn't return it


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


def classify_regime_simple(closes: List[float], highs: Optional[List[float]] = None, lows: Optional[List[float]] = None) -> str:
    """
    Realistic regime classifier using price history, slopes, and structure.
    
    Args:
        closes: list of recent close prices, length >= 20
        highs: optional list of high prices (same length as closes)
        lows: optional list of low prices (same length as closes)
    
    Returns:
        "trend_up", "trend_down", "high_vol", or "chop"
    """
    import os
    DEBUG_REGIME = os.getenv("DEBUG_REGIME", "0") == "1"
    
    # Safety for short histories
    if len(closes) < 20:
        if DEBUG_REGIME:
            print(f"REGIME-SIMPLE: insufficient data (n={len(closes)}), defaulting to chop")
        return "chop"
    
    # Helper function for slopes
    def slope(series: List[float]) -> float:
        """Compute average slope over series."""
        if len(series) < 2:
            return 0.0
        return (series[-1] - series[0]) / max(1, len(series) - 1)
    
    # Compute slopes at different horizons
    slope5 = slope(closes[-5:]) if len(closes) >= 5 else 0.0
    slope20 = slope(closes[-20:]) if len(closes) >= 20 else slope(closes) if closes else 0.0
    slope50 = slope(closes[-50:]) if len(closes) >= 50 else slope20
    
    # High/low structure (local peaks/troughs)
    hh = 0  # higher-high count
    ll = 0  # lower-low count
    for i in range(1, len(closes) - 1):
        if closes[i] > closes[i - 1] and closes[i] > closes[i + 1]:
            hh += 1
        if closes[i] < closes[i - 1] and closes[i] < closes[i + 1]:
            ll += 1
    
    # Compute ATR14 and ATR100
    atr14 = None
    atr100 = None
    
    if highs is not None and lows is not None and len(highs) == len(closes) and len(lows) == len(closes):
        def compute_atr_ema(highs_list, lows_list, closes_list, period):
            """Compute ATR using EMA of True Ranges."""
            if len(closes_list) < period + 1:
                return None
            
            trs = []
            for i in range(len(closes_list) - period, len(closes_list)):
                if i == 0:
                    continue
                tr = max(
                    highs_list[i] - lows_list[i],
                    abs(highs_list[i] - closes_list[i-1]),
                    abs(lows_list[i] - closes_list[i-1])
                )
                trs.append(tr)
            
            if not trs:
                return None
            
            # EMA of TRs
            alpha = 2.0 / (period + 1)
            atr = trs[0]
            for tr in trs[1:]:
                atr = alpha * tr + (1 - alpha) * atr
            return atr
        
        # ATR14: last 14 bars
        if len(closes) >= 15:
            atr14 = compute_atr_ema(highs[-15:], lows[-15:], closes[-15:], 14)
        
        # ATR100: last 100 bars (or what we have)
        if len(closes) >= 101:
            atr100 = compute_atr_ema(highs[-101:], lows[-101:], closes[-101:], 100)
        elif len(closes) >= 20:
            atr100 = compute_atr_ema(highs[-len(closes):], lows[-len(closes):], closes[-len(closes):], min(100, len(closes)))
    
    # Compute ATR metrics
    last = closes[-1] if closes else 0.0
    first = closes[0] if closes else last
    atr_ratio = 1.0
    atr_pct = 0.0
    
    if atr14 is not None and atr100 is not None and atr100 > 0:
        atr_ratio = atr14 / atr100
    elif atr14 is not None and atr100 is None and len(closes) >= 20:
        # Fallback: use longer-term ATR estimate
        if highs is not None and lows is not None:
            atr_long = compute_atr_ema(highs[-len(closes):], lows[-len(closes):], closes[-len(closes):], min(50, len(closes)))
            if atr_long is not None and atr_long > 0:
                atr_ratio = atr14 / atr_long
    
    if atr14 is not None and last > 0:
        atr_pct = atr14 / last
    
    # Overall change over window (context)
    change_pct = (last - first) / max(1e-8, first) if first > 0 else 0.0
    
    # Classify regime using realistic rules
    regime_str: str
    
    # 1) High volatility regime: volatility is structurally elevated
    # Lowered threshold from 1.25 to 1.10 to catch more high-vol periods
    if atr_pct >= 0.018 or atr_ratio >= 1.10:
        regime_str = "high_vol"
    # 2) Trend up: persistent upward slopes + more HH than LL + positive context
    # Lowered change_pct from 8% to 1% to catch more trends
    elif (
        change_pct >= 0.01  # ~1%+ move over window (was 0.03, originally 0.08)
        and slope20 > 0
        and slope20 / max(1e-8, first) >= 0.00005  # Lowered from 0.0002
        and hh >= ll
    ):
        regime_str = "trend_up"
    # 3) Trend down: persistent downward slopes + more LL than HH + negative context
    # Lowered change_pct from -8% to -1% to catch more trends
    elif (
        change_pct <= -0.01  # ~1%+ drop over window (was -0.02, originally -0.08)
        and slope20 < 0
        and abs(slope20) / max(1e-8, first) >= 0.00005  # Lowered from 0.0001
        and ll >= hh
    ):
        regime_str = "trend_down"
    # 4) Fallback: if strong slope but doesn't meet trend criteria, check for trend_down
    # This catches periods with consistent downward movement even if change_pct isn't extreme
    elif (
        slope20 < 0
        and abs(slope20) / max(1e-8, first) >= 0.0001  # Strong downward slope (lowered from 0.0002)
        and ll > hh  # More lower lows than higher highs
        and change_pct <= -0.002  # At least 0.2% down (lowered from 0.5%)
    ):
        regime_str = "trend_down"
    # 5) Additional fallback: if we have strong negative slope and more LL, classify as trend_down
    # This is more permissive and catches weak trends
    elif (
        slope20 < 0
        and abs(slope20) / max(1e-8, first) >= 0.00005  # Even weaker slope
        and ll >= hh + 1  # At least one more LL than HH
    ):
        regime_str = "trend_down"
    # 5) Otherwise: chop (rangebound / noisy)
    else:
        regime_str = "chop"
    
    if DEBUG_REGIME:
        print(f"REGIME-SIMPLE: regime={regime_str} slope5={slope5:.6f} slope20={slope20:.6f} hh={hh} ll={ll} atr_ratio={atr_ratio:.3f} change_pct={change_pct:.4f}")
    
    return regime_str


def classify_regime(rows: List[dict]) -> Dict[str, Any]:
    """
    Simple, robust regime classifier using only price data.
    
    Classifies into: "trend_up", "trend_down", "high_vol", "chop"
    
    Returns {"regime": <label>, "metrics": {..}}.
    """
    import os
    DEBUG_REGIME = os.getenv("DEBUG_REGIME", "0") == "1"
    
    # Extract closes, highs, lows
    closes = []
    highs = []
    lows = []
    for r in rows:
        c = r.get("close") if isinstance(r, dict) else getattr(r, "close", None)
        h = r.get("high") if isinstance(r, dict) else getattr(r, "high", None)
        l = r.get("low") if isinstance(r, dict) else getattr(r, "low", None)
        if c is not None:
            closes.append(float(c))
            if h is not None:
                highs.append(float(h))
            else:
                highs.append(float(c))  # Fallback to close if high missing
            if l is not None:
                lows.append(float(l))
            else:
                lows.append(float(c))  # Fallback to close if low missing
    
    # Use the simple classifier
    regime_str = classify_regime_simple(closes, highs if highs else None, lows if lows else None)
    
    # Compute metrics for backward compatibility
    close_curr = closes[-1] if closes else 0.0
    
    # Compute slope5 and slope20 for metrics
    slope5 = 0.0
    if len(closes) >= 6:
        slope5 = (closes[-1] - closes[-6]) / closes[-6] if closes[-6] > 0 else 0.0
    
    slope20 = 0.0
    if len(closes) >= 21:
        slope20 = (closes[-1] - closes[-21]) / closes[-21] if closes[-21] > 0 else 0.0
    
    # Compute EMA20 slope
    def compute_ema(prices, period):
        """Simple EMA calculation."""
        if len(prices) < period:
            return None
        alpha = 2.0 / (period + 1)
        ema = prices[0]
        for price in prices[1:period]:
            ema = alpha * price + (1 - alpha) * ema
        return ema
    
    ema20_slope = 0.0
    if len(closes) >= 21:
        ema20_window_now = closes[-20:]
        ema20_window_prev = closes[-21:-1]
        ema20_now = compute_ema(ema20_window_now, 20)
        ema20_prev = compute_ema(ema20_window_prev, 20)
        if ema20_now is not None and ema20_prev is not None and ema20_prev > 0:
            ema20_slope = (ema20_now - ema20_prev) / ema20_prev
    
    # Compute HH/LL (for metrics - also computed in classify_regime_simple but we need them here)
    hh = 0
    ll = 0
    if len(closes) >= 10:
        prev_max = closes[-10]
        prev_min = closes[-10]
        for i in range(-9, 0):
            if closes[i] > prev_max:
                hh += 1
                prev_max = closes[i]
            if closes[i] < prev_min:
                ll += 1
                prev_min = closes[i]
    
    # Use uppercase for backward compatibility in metrics
    HH = hh
    LL = ll
    
    # Compute ATR for metrics
    def compute_atr(rows, period):
        """Compute Average True Range."""
        if len(rows) < period + 1:
            return None
        
        trs = []
        for i in range(len(rows) - period, len(rows)):
            if i == 0:
                continue
            h = rows[i].get("high") if isinstance(rows[i], dict) else getattr(rows[i], "high", None)
            l = rows[i].get("low") if isinstance(rows[i], dict) else getattr(rows[i], "low", None)
            prev_c = rows[i-1].get("close") if isinstance(rows[i-1], dict) else getattr(rows[i-1], "close", None)
            
            if h is None or l is None or prev_c is None:
                continue
            
            tr = max(
                float(h) - float(l),
                abs(float(h) - float(prev_c)),
                abs(float(l) - float(prev_c))
            )
            trs.append(tr)
        
        if not trs:
            return None
        return sum(trs) / len(trs)
    
    atr14 = compute_atr(rows, 14) if len(rows) >= 15 else None
    atr100 = compute_atr(rows, min(100, len(rows))) if len(rows) >= 20 else None
    
    atr_ratio = 1.0
    if atr14 is not None and atr100 is not None and atr100 > 0:
        atr_ratio = atr14 / atr100
    elif atr14 is not None and atr100 is None and len(rows) >= 20:
        atr_long = compute_atr(rows, min(50, len(rows)))
        if atr_long is not None and atr_long > 0:
            atr_ratio = atr14 / atr_long
    
    # Compute backward-compatible metrics
    atr_pct = (atr14 / close_curr) if atr14 is not None and close_curr > 0 else 0.0
    vol_expansion = atr_ratio
    slope = (closes[-1] - closes[0]) / closes[0] if len(closes) >= 2 and closes[0] > 0 else 0.0
    
    regime: Regime = regime_str  # type: ignore
    
    metrics = {
        # New simple metrics
        "slope5": slope5,
        "ema20_slope": ema20_slope,
        "HH": HH,
        "LL": LL,
        "atr_ratio": atr_ratio,
        "atr14": atr14,
        "atr100": atr100,
        # Backward-compatible metrics
        "atr_pct": atr_pct,
        "vol_expansion": vol_expansion,
        "slope": slope,
    }
    
    if DEBUG_REGIME:
        print(f"DEBUG_REGIME: slope5={slope5:.6f} ema20_slope={ema20_slope:.6f} HH={HH} LL={LL} atr_ratio={atr_ratio:.3f} → {regime}")
    
    return {"regime": regime, "metrics": metrics}


# Old classify_regime_simple removed - replaced by new function above


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
