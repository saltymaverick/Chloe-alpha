"""
Flow Signals Module - Phase 2 (Quant Architecture)

Implements flow-based predictive signals:
- Whale accumulation velocity
- Net exchange inflow
- Exchange reserve delta
- Perpetual OI trend
- CVD spot vs perp divergence
- Large wallet bid-ask dominance

Each signal returns a structured dict with:
- raw: float (raw signal value)
- z_score: float (normalized z-score)
- direction_prob: {"up": float, "down": float} (probabilistic direction)
- confidence: float (0-1, signal confidence)
- drift: float (drift score, 0-1)

TODO: Replace simulated values with real data providers:
- Glassnode API for exchange flows
- On-chain analytics for whale tracking
- Exchange APIs for OI and funding data
"""

import math
from typing import Dict, Any, Optional, Union

try:
    from engine_alpha.signals.context import SignalContext
except ImportError:
    SignalContext = None  # Fallback if context module not available

# Type alias for backward compatibility
ContextLike = Union[Any, Dict[str, Any]]  # SignalContext or legacy dict


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
    # Map z-score to probability using sigmoid
    # Positive z-score -> higher "up" probability
    prob_up = 1.0 / (1.0 + math.exp(-z_score))
    prob_down = 1.0 - prob_up
    
    # Ensure probabilities sum to 1.0
    total = prob_up + prob_down
    if total > 0:
        prob_up = prob_up / total
        prob_down = prob_down / total
    
    return {"up": max(0.0, min(1.0, prob_up)), "down": max(0.0, min(1.0, prob_down))}


def _compute_confidence(z_score: float, raw_magnitude: float) -> float:
    """
    Compute confidence score (0-1) based on z-score and signal magnitude.
    
    Higher absolute z-score and larger magnitude -> higher confidence.
    """
    # Normalize z-score to [0, 1] using absolute value
    z_confidence = min(1.0, abs(z_score) / 3.0)  # 3-sigma = max confidence
    
    # Normalize raw magnitude (assuming typical ranges)
    mag_confidence = min(1.0, abs(raw_magnitude) / 10.0)  # Adjust threshold as needed
    
    # Combine (weighted average)
    confidence = 0.6 * z_confidence + 0.4 * mag_confidence
    
    return max(0.0, min(1.0, confidence))


def _compute_drift(raw: float, historical_mean: float = 0.0) -> float:
    """
    Compute drift score (0-1) indicating how far from historical baseline.
    
    For now, simplified: drift increases with distance from mean.
    TODO: Implement rolling window comparison with actual historical data.
    """
    if historical_mean == 0:
        return 0.0  # No drift if no baseline
    
    deviation = abs(raw - historical_mean) / max(abs(historical_mean), 1e-6)
    drift = min(1.0, deviation / 2.0)  # Normalize to [0, 1]
    
    return drift


def _ensure_signal_context(ctx: ContextLike) -> Any:
    """
    Helper: convert legacy context/dict into SignalContext if necessary.
    
    Maintains backward compatibility by accepting either:
    - SignalContext instance (returns as-is)
    - Legacy dict with "rows" key (converts to SignalContext)
    - None (returns None)
    
    Args:
        ctx: SignalContext, dict, or None
    
    Returns:
        SignalContext instance or None
    """
    if ctx is None:
        return None
    
    # If already a SignalContext, return as-is
    if SignalContext is not None and isinstance(ctx, SignalContext):
        return ctx
    
    # If it's a dict, try to convert to SignalContext
    if isinstance(ctx, dict):
        # Check if it has the legacy "rows" format
        if "rows" in ctx:
            # Convert legacy dict to SignalContext
            if SignalContext is not None:
                return SignalContext(
                    symbol=ctx.get("symbol", "ETHUSDT"),
                    timeframe=ctx.get("timeframe", "15m"),
                    ohlcv=ctx["rows"],  # List of dicts
                    onchain=ctx.get("onchain"),
                    derivatives=ctx.get("derivatives"),
                    microstructure=ctx.get("microstructure"),
                    cross_asset=ctx.get("cross_asset"),
                    meta=ctx.get("meta"),
                )
            else:
                # Fallback: return dict as-is if SignalContext not available
                return ctx
        else:
            # Already in some other format, return as-is
            return ctx
    
    # Unknown type, return as-is
    return ctx


def _get_rows_from_context(ctx: ContextLike) -> list:
    """
    Extract rows (OHLCV data) from context, handling both SignalContext and legacy formats.
    
    Args:
        ctx: SignalContext, dict, or None
    
    Returns:
        List of dicts with OHLCV data, or empty list if unavailable
    """
    if ctx is None:
        return []
    
    sc = _ensure_signal_context(ctx)
    
    # If SignalContext, use get_ohlcv_rows()
    if SignalContext is not None and isinstance(sc, SignalContext):
        return sc.get_ohlcv_rows()
    
    # Legacy dict format
    if isinstance(sc, dict):
        if "rows" in sc:
            return sc["rows"]
        elif "ohlcv" in sc:
            ohlcv = sc["ohlcv"]
            if isinstance(ohlcv, list):
                return ohlcv
            # Try to convert DataFrame if pandas available
            try:
                import pandas as pd
                if isinstance(ohlcv, pd.DataFrame):
                    return ohlcv.to_dict("records")
            except ImportError:
                pass
    
    return []


def compute_whale_accumulation_velocity(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute whale accumulation velocity signal.
    
    Measures the rate of large wallet accumulation (positive = accumulation, bullish).
    
    TODO: Replace with real on-chain data:
    - Track addresses with >X ETH/BTC balance
    - Compute net flow rate over rolling window
    - Use Glassnode or Nansen APIs
    
    Args:
        context: SignalContext or legacy dict with symbol, timeframe, OHLCV data, etc.
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    # Extract rows from context (handles both SignalContext and legacy formats)
    rows = _get_rows_from_context(context)
    
    # Simulated: derive from volume and price action
    # In production, this would query on-chain analytics
    if len(rows) >= 5:
        # Use recent volume as proxy for whale activity
        recent_vol = sum(row.get("volume", 0) for row in rows[-5:])
        price_change = (rows[-1].get("close", 0) - rows[-5].get("close", 0)) / max(rows[-5].get("close", 1), 1e-6)
        raw = recent_vol * price_change * 1e-6  # Scale down
    elif len(rows) > 0:
        # Fallback: use available rows
        recent_vol = sum(row.get("volume", 0) for row in rows)
        if len(rows) > 1:
            price_change = (rows[-1].get("close", 0) - rows[0].get("close", 0)) / max(rows[0].get("close", 1), 1e-6)
        else:
            price_change = 0.0
        raw = recent_vol * price_change * 1e-6
    else:
        # Fallback: simulated value
        import random
        random.seed(42)
        raw = random.uniform(-1000, 5000)
    
    z_score = _compute_z_score(raw, mean=1000.0, std=2000.0)
    direction_prob = _compute_direction_prob(raw, z_score)
    confidence = _compute_confidence(z_score, raw)
    drift = _compute_drift(raw, historical_mean=1000.0)
    
    return {
        "raw": float(raw),
        "z_score": float(z_score),
        "direction_prob": direction_prob,
        "confidence": float(confidence),
        "drift": float(drift),
    }


def compute_net_exchange_inflow(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute net exchange inflow signal.
    
    Negative values = outflow (bullish, coins leaving exchanges)
    Positive values = inflow (bearish, coins entering exchanges)
    
    TODO: Replace with real exchange flow data:
    - Glassnode exchange_netflow metric
    - CryptoQuant exchange flows
    - On-chain exchange address tracking
    
    Args:
        context: Optional context dict
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    # Extract rows from context
    rows = _get_rows_from_context(context)
    
    # Simulated: negative = bullish (outflow)
    if len(rows) >= 10:
        # Use price momentum as proxy (falling price = outflow = bullish)
        price_change = (rows[-1].get("close", 0) - rows[-10].get("close", 0)) / max(rows[-10].get("close", 1), 1e-6)
        raw = -price_change * 1e6  # Negative = outflow = bullish
    elif len(rows) > 1:
        price_change = (rows[-1].get("close", 0) - rows[0].get("close", 0)) / max(rows[0].get("close", 1), 1e-6)
        raw = -price_change * 1e6
    else:
        import random
        random.seed(43)
        raw = random.uniform(-5000, 5000)  # Negative = bullish
    
    z_score = _compute_z_score(raw, mean=0.0, std=3000.0)
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


def compute_exchange_reserve_delta(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute exchange reserve delta signal.
    
    Negative = reserves decreasing (withdrawal, bullish)
    Positive = reserves increasing (deposit, bearish)
    
    TODO: Replace with real exchange reserve tracking:
    - Glassnode exchange_reserves metric
    - Track known exchange addresses on-chain
    
    Args:
        context: Optional context dict
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    # Extract rows from context
    rows = _get_rows_from_context(context)
    
    # Simulated: negative = bullish (withdrawal)
    if len(rows) >= 5:
        volume_change = (rows[-1].get("volume", 0) - rows[-5].get("volume", 0)) / max(rows[-5].get("volume", 1), 1)
        raw = -volume_change * 1e5  # Negative = withdrawal = bullish
    elif len(rows) > 1:
        volume_change = (rows[-1].get("volume", 0) - rows[0].get("volume", 0)) / max(rows[0].get("volume", 1), 1)
        raw = -volume_change * 1e5
    else:
        import random
        random.seed(44)
        raw = random.uniform(-10000, 10000)
    
    z_score = _compute_z_score(raw, mean=0.0, std=5000.0)
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


def compute_perp_oi_trend(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute perpetual open interest trend signal.
    
    Positive = OI increasing (bullish, more leverage long)
    Negative = OI decreasing (bearish, deleveraging)
    
    TODO: Replace with real OI data:
    - Exchange APIs (Bybit, Binance) for OI
    - Compute rolling trend over 24h window
    
    Args:
        context: Optional context dict
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    # Extract rows from context
    rows = _get_rows_from_context(context)
    
    # Simulated: positive = bullish (OI increasing)
    if len(rows) > 0:
        # Use volume trend as proxy
        recent_vol = sum(row.get("volume", 0) for row in rows[-3:])
        older_vol = sum(row.get("volume", 0) for row in rows[-6:-3]) if len(rows) >= 6 else recent_vol
        raw = (recent_vol - older_vol) * 1e-4
    else:
        import random
        random.seed(45)
        raw = random.uniform(-1000, 2000)
    
    z_score = _compute_z_score(raw, mean=500.0, std=1000.0)
    direction_prob = _compute_direction_prob(raw, z_score)
    confidence = _compute_confidence(z_score, abs(raw))
    drift = _compute_drift(raw, historical_mean=500.0)
    
    return {
        "raw": float(raw),
        "z_score": float(z_score),
        "direction_prob": direction_prob,
        "confidence": float(confidence),
        "drift": float(drift),
    }


def compute_cvd_spot_vs_perp(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute cumulative volume delta divergence (spot vs perp).
    
    Positive = spot buying pressure > perp (bullish divergence)
    Negative = perp buying pressure > spot (bearish divergence)
    
    TODO: Replace with real CVD data:
    - Exchange orderbook data for spot CVD
    - Perpetual orderbook data for perp CVD
    - Compute divergence metric
    
    Args:
        context: Optional context dict
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    # Extract rows from context
    rows = _get_rows_from_context(context)
    
    # Simulated: divergence metric
    if len(rows) >= 5:
        # Use price-volume relationship as proxy
        price_change = (rows[-1].get("close", 0) - rows[-5].get("close", 0)) / max(rows[-5].get("close", 1), 1e-6)
        volume_ratio = rows[-1].get("volume", 0) / max(rows[-5].get("volume", 1), 1)
        raw = price_change * volume_ratio * 1e4
    elif len(rows) > 1:
        price_change = (rows[-1].get("close", 0) - rows[0].get("close", 0)) / max(rows[0].get("close", 1), 1e-6)
        volume_ratio = rows[-1].get("volume", 0) / max(rows[0].get("volume", 1), 1)
        raw = price_change * volume_ratio * 1e4
    else:
        import random
        random.seed(46)
        raw = random.uniform(-500, 500)
    
    z_score = _compute_z_score(raw, mean=0.0, std=300.0)
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


def compute_large_wallet_bid_ask_dominance(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute large wallet bid-ask dominance signal.
    
    Positive = bid dominance (large wallets buying, bullish)
    Negative = ask dominance (large wallets selling, bearish)
    
    TODO: Replace with real orderbook analytics:
    - Track large orders (>X size) on bid vs ask
    - Use exchange orderbook depth data
    - Filter by wallet size/whale addresses
    
    Args:
        context: Optional context dict
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    # Extract rows from context
    rows = _get_rows_from_context(context)
    
    # Simulated: positive = bid dominance = bullish
    if len(rows) > 0:
        # Use price action as proxy
        high_low_range = rows[-1].get("high", 0) - rows[-1].get("low", 0)
        close_position = (rows[-1].get("close", 0) - rows[-1].get("low", 0)) / max(high_low_range, 1e-6)
        raw = (close_position - 0.5) * 1e3  # Positive if close near high
    else:
        import random
        random.seed(47)
        raw = random.uniform(-500, 500)
    
    z_score = _compute_z_score(raw, mean=0.0, std=250.0)
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

