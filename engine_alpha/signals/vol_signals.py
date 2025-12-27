"""
Volatility Signals Module - Phase 2 (Quant Architecture)

Implements volatility-based predictive signals:
- Vol compression percentile
- Vol expansion probability
- Regime transition heat
- Vol clustering score
- Realized vs implied gap

Each signal returns a structured dict with:
- raw: float (raw signal value)
- z_score: float (normalized z-score)
- direction_prob: {"up": float, "down": float} (probabilistic direction)
- confidence: float (0-1, signal confidence)
- drift: float (drift score, 0-1)

TODO: Replace simulated values with real data providers:
- Options data for implied volatility (Deribit, Deribit API)
- Real-time volatility surfaces
"""

import math
from typing import Dict, Any, Optional, Union

try:
    from engine_alpha.signals.context import SignalContext
except ImportError:
    SignalContext = None

# Type alias for backward compatibility
ContextLike = Union[Any, Dict[str, Any]]


def _compute_z_score(value: float, mean: float = 0.0, std: float = 1.0) -> float:
    """Compute z-score for a value."""
    if std == 0:
        return 0.0
    return (value - mean) / std


def _compute_direction_prob(raw: float, z_score: float) -> Dict[str, float]:
    """
    Convert raw signal and z-score into directional probabilities.
    
    Uses sigmoid to map z-score to [0, 1] probabilities.
    """
    prob_up = 1.0 / (1.0 + math.exp(-z_score))
    prob_down = 1.0 - prob_up
    
    total = prob_up + prob_down
    if total > 0:
        prob_up = prob_up / total
        prob_down = prob_down / total
    
    return {"up": max(0.0, min(1.0, prob_up)), "down": max(0.0, min(1.0, prob_down))}


def _compute_confidence(z_score: float, raw_magnitude: float) -> float:
    """
    Compute confidence score (0-1) based on z-score and signal magnitude.
    """
    z_confidence = min(1.0, abs(z_score) / 3.0)
    mag_confidence = min(1.0, abs(raw_magnitude) / 10.0)
    confidence = 0.6 * z_confidence + 0.4 * mag_confidence
    return max(0.0, min(1.0, confidence))


def _compute_drift(raw: float, historical_mean: float = 0.0) -> float:
    """
    Compute drift score (0-1) indicating how far from historical baseline.
    """
    if historical_mean == 0:
        return 0.0
    
    deviation = abs(raw - historical_mean) / max(abs(historical_mean), 1e-6)
    drift = min(1.0, deviation / 2.0)
    return drift


def _get_rows_from_context(ctx: ContextLike) -> list:
    """
    Extract rows (OHLCV data) from context, handling both SignalContext and legacy formats.
    """
    if ctx is None:
        return []
    
    # If SignalContext, use get_ohlcv_rows()
    if SignalContext is not None and isinstance(ctx, SignalContext):
        return ctx.get_ohlcv_rows()
    
    # Legacy dict format
    if isinstance(ctx, dict):
        if "rows" in ctx:
            return ctx["rows"]
        elif "ohlcv" in ctx:
            ohlcv = ctx["ohlcv"]
            if isinstance(ohlcv, list):
                return ohlcv
            try:
                import pandas as pd
                if isinstance(ohlcv, pd.DataFrame):
                    return ohlcv.to_dict("records")
            except ImportError:
                pass
    
    return []


def _compute_realized_volatility(rows: list, window: int = 20) -> float:
    """
    Compute realized volatility from OHLCV rows.
    
    Returns standard deviation of returns over the window.
    """
    if len(rows) < 2:
        return 0.0
    
    closes = [row.get("close", 0) for row in rows[-window:] if row.get("close")]
    if len(closes) < 2:
        return 0.0
    
    returns = []
    for i in range(1, len(closes)):
        if closes[i-1] > 0:
            ret = (closes[i] - closes[i-1]) / closes[i-1]
            returns.append(ret)
    
    if len(returns) < 2:
        return 0.0
    
    mean_ret = sum(returns) / len(returns)
    variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
    return math.sqrt(variance) if variance > 0 else 0.0


def compute_vol_compression_percentile(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute volatility compression percentile signal.
    
    Measures how low current volatility is vs recent history (high = compressed, bullish for expansion).
    
    TODO: Replace with real volatility data:
    - Use options-implied vol surfaces
    - Historical realized vol databases
    
    Args:
        context: SignalContext or legacy dict with OHLCV data
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    rows = _get_rows_from_context(context)
    
    if len(rows) < 30:
        # Fallback: simulated value
        import random
        random.seed(50)
        raw = random.uniform(0.0, 1.0)
    else:
        # Compute current vol vs historical vol
        current_vol = _compute_realized_volatility(rows, window=10)
        historical_vol = _compute_realized_volatility(rows[:-10], window=min(20, len(rows) - 10))
        
        if historical_vol > 0:
            # Percentile: how low is current vol relative to historical?
            # Lower current vol = higher compression percentile
            vol_ratio = current_vol / historical_vol
            raw = max(0.0, min(1.0, 1.0 - vol_ratio))  # Inverted: low vol = high compression
        else:
            raw = 0.5  # Neutral if no historical vol
    
    z_score = _compute_z_score(raw, mean=0.5, std=0.2)
    direction_prob = _compute_direction_prob(raw, z_score)
    confidence = _compute_confidence(z_score, raw)
    drift = _compute_drift(raw, historical_mean=0.5)
    
    return {
        "raw": float(raw),
        "z_score": float(z_score),
        "direction_prob": direction_prob,
        "confidence": float(confidence),
        "drift": float(drift),
    }


def compute_vol_expansion_probability(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute volatility expansion probability signal.
    
    Higher when compression is extreme (inverted function of compression percentile).
    High expansion probability = likely volatility breakout soon.
    
    TODO: Use real vol expansion models and options skew data.
    
    Args:
        context: SignalContext or legacy dict
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    rows = _get_rows_from_context(context)
    
    if len(rows) < 30:
        import random
        random.seed(51)
        raw = random.uniform(0.0, 1.0)
    else:
        # Expansion probability increases as compression becomes extreme
        compression = compute_vol_compression_percentile(context)["raw"]
        # Extreme compression (near 1.0) → high expansion probability
        # Use a sigmoid-like function
        raw = compression ** 2  # Squared to emphasize extreme compression
    
    z_score = _compute_z_score(raw, mean=0.3, std=0.25)
    direction_prob = _compute_direction_prob(raw, z_score)
    confidence = _compute_confidence(z_score, raw)
    drift = _compute_drift(raw, historical_mean=0.3)
    
    return {
        "raw": float(raw),
        "z_score": float(z_score),
        "direction_prob": direction_prob,
        "confidence": float(confidence),
        "drift": float(drift),
    }


def compute_regime_transition_heat(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute regime transition heat signal.
    
    Higher when volatility is changing rapidly (derivative of vol over time).
    Indicates potential regime shifts.
    
    TODO: Use regime classification models and vol regime transitions.
    
    Args:
        context: SignalContext or legacy dict
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    rows = _get_rows_from_context(context)
    
    if len(rows) < 20:
        import random
        random.seed(52)
        raw = random.uniform(0.0, 1.0)
    else:
        # Compute vol change rate
        recent_vol = _compute_realized_volatility(rows[-10:], window=10)
        older_vol = _compute_realized_volatility(rows[-20:-10], window=10)
        
        if older_vol > 0:
            vol_change_rate = abs(recent_vol - older_vol) / older_vol
            raw = min(1.0, vol_change_rate * 2.0)  # Scale to [0, 1]
        else:
            raw = 0.0
    
    z_score = _compute_z_score(raw, mean=0.2, std=0.3)
    direction_prob = _compute_direction_prob(raw, z_score)
    confidence = _compute_confidence(z_score, raw)
    drift = _compute_drift(raw, historical_mean=0.2)
    
    return {
        "raw": float(raw),
        "z_score": float(z_score),
        "direction_prob": direction_prob,
        "confidence": float(confidence),
        "drift": float(drift),
    }


def compute_vol_clustering_score(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute volatility clustering score signal.
    
    Higher when high volatility tends to follow high volatility (autocorrelation).
    Indicates persistent vol regimes.
    
    TODO: Use advanced vol clustering models (GARCH, etc.).
    
    Args:
        context: SignalContext or legacy dict
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    rows = _get_rows_from_context(context)
    
    if len(rows) < 30:
        import random
        random.seed(53)
        raw = random.uniform(0.0, 1.0)
    else:
        # Compute rolling vol and check autocorrelation
        window_size = 5
        vol_series = []
        
        for i in range(len(rows) - window_size):
            window_rows = rows[i:i+window_size]
            vol = _compute_realized_volatility(window_rows, window=window_size)
            vol_series.append(vol)
        
        if len(vol_series) >= 10:
            # Simple autocorrelation: correlation between vol[t] and vol[t-1]
            vol_t = vol_series[1:]
            vol_t_minus_1 = vol_series[:-1]
            
            if len(vol_t) > 1 and len(vol_t_minus_1) > 1:
                mean_t = sum(vol_t) / len(vol_t)
                mean_tm1 = sum(vol_t_minus_1) / len(vol_t_minus_1)
                
                cov = sum((vol_t[i] - mean_t) * (vol_t_minus_1[i] - mean_tm1) 
                         for i in range(len(vol_t))) / len(vol_t)
                
                var_t = sum((v - mean_t) ** 2 for v in vol_t) / len(vol_t)
                var_tm1 = sum((v - mean_tm1) ** 2 for v in vol_t_minus_1) / len(vol_t_minus_1)
                
                if var_t > 0 and var_tm1 > 0:
                    autocorr = cov / math.sqrt(var_t * var_tm1)
                    raw = max(0.0, min(1.0, (autocorr + 1.0) / 2.0))  # Map [-1, 1] to [0, 1]
                else:
                    raw = 0.5
            else:
                raw = 0.5
        else:
            raw = 0.5
    
    z_score = _compute_z_score(raw, mean=0.5, std=0.2)
    direction_prob = _compute_direction_prob(raw, z_score)
    confidence = _compute_confidence(z_score, raw)
    drift = _compute_drift(raw, historical_mean=0.5)
    
    return {
        "raw": float(raw),
        "z_score": float(z_score),
        "direction_prob": direction_prob,
        "confidence": float(confidence),
        "drift": float(drift),
    }


def compute_realized_vs_implied_gap(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute realized vs implied volatility gap signal.
    
    Positive when realized vol > implied vol (volatility risk premium).
    Negative when implied > realized (overpriced options).
    
    TODO: Replace with real implied volatility data:
    - Deribit options API
    - Options chain data
    - Volatility surface models
    
    Args:
        context: SignalContext or legacy dict
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    rows = _get_rows_from_context(context)
    
    if len(rows) < 20:
        import random
        random.seed(54)
        raw = random.uniform(-0.5, 0.5)
    else:
        # Compute realized vol
        realized_vol = _compute_realized_volatility(rows, window=20)
        
        # Simulate implied vol as smoothed/lagged version of realized
        # In production, this would come from options data
        historical_vol = _compute_realized_volatility(rows[:-5], window=min(20, len(rows) - 5))
        implied_vol = historical_vol * 1.1  # Simulate IV typically above RV
        
        # Gap = realized - implied (positive = RV > IV, bullish for vol)
        if implied_vol > 0:
            raw = (realized_vol - implied_vol) / implied_vol  # Normalized gap
        else:
            raw = 0.0
    
    z_score = _compute_z_score(raw, mean=0.0, std=0.3)
    direction_prob = _compute_direction_prob(raw, z_score)
    confidence = _compute_confidence(z_score, abs(raw))
    drift = _compute_drift(raw, historical_mean=0.0)
    
    return {
        "raw": float(raw),
        "z_score": float(z_score),
        "direction_prob": direction_prob,
        "confidence": float(confidence),
        "drift": float(drift),
    }

