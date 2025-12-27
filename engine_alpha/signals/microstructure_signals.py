"""
Microstructure Signals Module - Phase 2 (Quant Architecture)

Implements microstructure-based predictive signals:
- Funding rate z-score
- Perp/spot basis
- Liquidation heat proximity
- Orderbook imbalance
- OI/price divergence

Each signal returns a structured dict with:
- raw: float (raw signal value)
- z_score: float (normalized z-score)
- direction_prob: {"up": float, "down": float} (probabilistic direction)
- confidence: float (0-1, signal confidence)
- drift: float (drift score, 0-1)

TODO: Replace simulated values with real data providers:
- Exchange APIs for funding rates (Bybit, Binance, Deribit)
- Orderbook depth data for imbalance
- Liquidation level tracking
- Open interest feeds
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
    
    if SignalContext is not None and isinstance(ctx, SignalContext):
        return ctx.get_ohlcv_rows()
    
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


def compute_funding_rate_z(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute funding rate z-score signal.
    
    Positive, high z-score = overlevered longs, likely bearish.
    Negative z-score = overlevered shorts, likely bullish.
    
    TODO: Replace with real funding rate data:
    - Exchange APIs (Bybit, Binance, Deribit) for perp funding rates
    - Historical funding rate series for rolling mean/std
    
    Args:
        context: SignalContext or legacy dict with derivatives data
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    # Try to get funding rate from context.derivatives
    funding_rate = None
    if context is not None:
        if SignalContext is not None and isinstance(context, SignalContext):
            if context.derivatives and "funding_rate" in context.derivatives:
                funding_rate = context.derivatives["funding_rate"]
        elif isinstance(context, dict):
            if "derivatives" in context and context["derivatives"]:
                funding_rate = context["derivatives"].get("funding_rate")
    
    if funding_rate is None:
        # Simulate: use price momentum as proxy
        rows = _get_rows_from_context(context)
        if len(rows) >= 5:
            # Positive momentum = long bias = positive funding (bearish)
            price_change = (rows[-1].get("close", 0) - rows[-5].get("close", 0)) / max(rows[-5].get("close", 1), 1e-6)
            funding_rate = price_change * 0.01  # Scale down
        else:
            import random
            random.seed(60)
            funding_rate = random.uniform(-0.001, 0.001)
    
    # Compute z-score vs rolling mean (simulated: mean=0, std=0.0005)
    z_score = _compute_z_score(funding_rate, mean=0.0, std=0.0005)
    direction_prob = _compute_direction_prob(funding_rate, z_score)
    confidence = _compute_confidence(z_score, abs(funding_rate))
    drift = _compute_drift(funding_rate, historical_mean=0.0)
    
    return {
        "raw": float(funding_rate),
        "z_score": float(z_score),
        "direction_prob": direction_prob,
        "confidence": float(confidence),
        "drift": float(drift),
    }


def compute_perp_spot_basis(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute perpetual vs spot basis signal.
    
    Positive = perp premium (bullish)
    Negative = perp discount (bearish)
    
    TODO: Replace with real perp/spot price data:
    - Exchange APIs for perp and spot prices
    - Basis = (perp_price - spot_price) / spot_price
    
    Args:
        context: SignalContext or legacy dict with derivatives data
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    # Try to get perp and spot prices from context.derivatives
    perp_price = None
    spot_price = None
    
    if context is not None:
        if SignalContext is not None and isinstance(context, SignalContext):
            if context.derivatives:
                perp_price = context.derivatives.get("perp_price")
                spot_price = context.derivatives.get("spot_price")
        elif isinstance(context, dict):
            if "derivatives" in context and context["derivatives"]:
                perp_price = context["derivatives"].get("perp_price")
                spot_price = context["derivatives"].get("spot_price")
    
    if perp_price is None or spot_price is None:
        # Simulate: approximate perp vs spot from OHLCV
        rows = _get_rows_from_context(context)
        if len(rows) >= 2:
            spot_price = rows[-1].get("close", 0)
            # Simulate perp as spot + small premium/discount
            price_momentum = (rows[-1].get("close", 0) - rows[-2].get("close", 0)) / max(rows[-2].get("close", 1), 1e-6)
            perp_price = spot_price * (1.0 + price_momentum * 0.1)  # Small premium/discount
        else:
            import random
            random.seed(61)
            spot_price = 3000.0
            perp_price = spot_price * (1.0 + random.uniform(-0.001, 0.001))
    
    # Basis = (perp - spot) / spot
    if spot_price > 0:
        raw = (perp_price - spot_price) / spot_price
    else:
        raw = 0.0
    
    z_score = _compute_z_score(raw, mean=0.0, std=0.001)
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


def compute_liquidation_heat_proximity(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute liquidation heat proximity signal.
    
    Higher when price is close to liquidation clusters.
    Indicates potential liquidation cascades.
    
    TODO: Replace with real liquidation level data:
    - Exchange APIs for liquidation levels
    - On-chain liquidation tracking
    - Large position monitoring
    
    Args:
        context: SignalContext or legacy dict with derivatives data
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    rows = _get_rows_from_context(context)
    
    # Try to get liquidation levels from context.derivatives
    liquidation_levels = None
    current_price = None
    
    if context is not None:
        if SignalContext is not None and isinstance(context, SignalContext):
            if context.derivatives:
                liquidation_levels = context.derivatives.get("liquidation_levels", [])
            if rows:
                current_price = rows[-1].get("close", 0)
        elif isinstance(context, dict):
            if "derivatives" in context and context["derivatives"]:
                liquidation_levels = context["derivatives"].get("liquidation_levels", [])
            if rows:
                current_price = rows[-1].get("close", 0)
    
    if liquidation_levels and current_price:
        # Compute distance to nearest liquidation level
        distances = [abs(current_price - level) / current_price for level in liquidation_levels if level > 0]
        if distances:
            min_distance = min(distances)
            # Closer = higher heat (inverted distance)
            raw = max(0.0, min(1.0, 1.0 - min_distance * 100))  # Scale appropriately
        else:
            raw = 0.0
    else:
        # Simulate: use large wicks + volume spikes as proxy
        if len(rows) >= 5:
            recent_rows = rows[-5:]
            # Large wicks indicate liquidation pressure
            max_wick_ratio = 0.0
            for row in recent_rows:
                high = row.get("high", 0)
                low = row.get("low", 0)
                close = row.get("close", 0)
                open_price = row.get("open", close)
                
                if high > low:
                    body_size = abs(close - open_price)
                    total_range = high - low
                    if total_range > 0:
                        wick_ratio = (total_range - body_size) / total_range
                        max_wick_ratio = max(max_wick_ratio, wick_ratio)
            
            # High wick ratio + high volume = liquidation heat
            recent_vol = sum(row.get("volume", 0) for row in recent_rows)
            avg_vol = sum(row.get("volume", 0) for row in rows[-20:-5]) / max(len(rows) - 5, 1) if len(rows) > 5 else recent_vol
            vol_ratio = recent_vol / max(avg_vol, 1)
            
            raw = min(1.0, max_wick_ratio * min(vol_ratio, 2.0) / 2.0)
        else:
            import random
            random.seed(62)
            raw = random.uniform(0.0, 0.5)
    
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


def compute_orderbook_imbalance(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute orderbook imbalance signal.
    
    Positive = bid dominance (bullish)
    Negative = ask dominance (bearish)
    
    TODO: Replace with real orderbook data:
    - Exchange orderbook depth APIs
    - Bid/ask volume aggregation
    - Large order detection
    
    Args:
        context: SignalContext or legacy dict with microstructure data
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    # Try to get bid_ask_imbalance from context.microstructure
    imbalance = None
    
    if context is not None:
        if SignalContext is not None and isinstance(context, SignalContext):
            if context.microstructure and "bid_ask_imbalance" in context.microstructure:
                imbalance = context.microstructure["bid_ask_imbalance"]
        elif isinstance(context, dict):
            if "microstructure" in context and context["microstructure"]:
                imbalance = context["microstructure"].get("bid_ask_imbalance")
    
    if imbalance is None:
        # Simulate: use price action as proxy
        rows = _get_rows_from_context(context)
        if len(rows) >= 3:
            # Close position in recent range indicates imbalance
            recent_high = max(row.get("high", 0) for row in rows[-3:])
            recent_low = min(row.get("low", 0) for row in rows[-3:])
            current_close = rows[-1].get("close", 0)
            
            if recent_high > recent_low:
                # Position in range: 0 = low, 1 = high
                position = (current_close - recent_low) / (recent_high - recent_low)
                # Map to [-1, 1]: close to high = positive imbalance (bullish)
                imbalance = (position - 0.5) * 2.0
            else:
                imbalance = 0.0
        else:
            import random
            random.seed(63)
            imbalance = random.uniform(-0.5, 0.5)
    
    z_score = _compute_z_score(imbalance, mean=0.0, std=0.3)
    direction_prob = _compute_direction_prob(imbalance, z_score)
    confidence = _compute_confidence(z_score, abs(imbalance))
    drift = _compute_drift(imbalance, historical_mean=0.0)
    
    return {
        "raw": float(imbalance),
        "z_score": float(z_score),
        "direction_prob": direction_prob,
        "confidence": float(confidence),
        "drift": float(drift),
    }


def compute_oi_price_divergence(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute open interest vs price divergence signal.
    
    Positive = OI rising while price falls (risky buildup, bearish)
    Negative = OI falling while price rises (unwinding, bullish)
    
    TODO: Replace with real OI data:
    - Exchange APIs for open interest
    - Historical OI series
    - OI change tracking
    
    Args:
        context: SignalContext or legacy dict with derivatives data
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    rows = _get_rows_from_context(context)
    
    # Try to get OI from context.derivatives
    current_oi = None
    previous_oi = None
    
    if context is not None:
        if SignalContext is not None and isinstance(context, SignalContext):
            if context.derivatives:
                oi_series = context.derivatives.get("open_interest_series", [])
                if len(oi_series) >= 2:
                    current_oi = oi_series[-1]
                    previous_oi = oi_series[-2]
        elif isinstance(context, dict):
            if "derivatives" in context and context["derivatives"]:
                oi_series = context["derivatives"].get("open_interest_series", [])
                if len(oi_series) >= 2:
                    current_oi = oi_series[-1]
                    previous_oi = oi_series[-2]
    
    if current_oi is None or previous_oi is None:
        # Simulate: use volume as proxy for OI
        if len(rows) >= 5:
            current_vol = sum(row.get("volume", 0) for row in rows[-3:])
            previous_vol = sum(row.get("volume", 0) for row in rows[-6:-3]) if len(rows) >= 6 else current_vol
            oi_change = (current_vol - previous_vol) / max(previous_vol, 1)
        else:
            import random
            random.seed(64)
            oi_change = random.uniform(-0.2, 0.2)
    else:
        oi_change = (current_oi - previous_oi) / max(previous_oi, 1) if previous_oi > 0 else 0.0
    
    # Get price change
    if len(rows) >= 5:
        price_change = (rows[-1].get("close", 0) - rows[-5].get("close", 0)) / max(rows[-5].get("close", 1), 1e-6)
    else:
        price_change = 0.0
    
    # Divergence: OI rising while price falling = positive (risky)
    # OI falling while price rising = negative (unwinding)
    raw = oi_change - price_change * 10  # Scale price change
    
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

