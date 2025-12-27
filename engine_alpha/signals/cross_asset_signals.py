"""
Cross-Asset Signals Module - Phase 2 (Quant Architecture)

Implements cross-asset predictive signals:
- BTC/ETH volatility lead-lag
- SOL vs L1 rotation score
- ETH ecosystem momentum
- Stablecoin flow pressure
- Sector risk score

Each signal returns a structured dict with:
- raw: float (raw signal value)
- z_score: float (normalized z-score)
- direction_prob: {"up": float, "down": float} (probabilistic direction)
- confidence: float (0-1, signal confidence)
- drift: float (drift score, 0-1)

TODO: Replace simulated values with real data providers:
- Cross-asset data feeds (Kaiko, Glassnode, exchange APIs)
- Multi-asset OHLCV loaders
- Sector proxies and rotation tracking
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
    """Extract rows (OHLCV data) from context."""
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


def _compute_realized_volatility(rows: list, window: int = 20) -> float:
    """Compute realized volatility from OHLCV rows."""
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


def _get_cross_asset_data(ctx: ContextLike, symbol: str) -> Optional[Dict[str, Any]]:
    """
    Get cross-asset data for a symbol from context.cross_asset.
    
    Returns dict with ohlcv, returns, vol, etc., or None if not available.
    """
    if ctx is None:
        return None
    
    cross_asset = None
    if SignalContext is not None and isinstance(ctx, SignalContext):
        cross_asset = ctx.cross_asset
    elif isinstance(ctx, dict):
        cross_asset = ctx.get("cross_asset")
    
    if cross_asset and isinstance(cross_asset, dict):
        return cross_asset.get(symbol)
    
    return None


def compute_btc_eth_vol_lead_lag(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute BTC/ETH volatility lead-lag signal.
    
    Positive = BTC leading risk moves (BTC vol changes precede ETH vol changes).
    Negative = ETH leading or no clear lead-lag.
    
    TODO: Replace with real cross-asset volatility data:
    - Multi-asset volatility feeds
    - Lead-lag correlation analysis
    - Cross-asset vol surface data
    
    Args:
        context: SignalContext or legacy dict with cross_asset data
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    # Try to get BTC and ETH data from context.cross_asset
    btc_data = _get_cross_asset_data(context, "BTCUSDT")
    eth_data = _get_cross_asset_data(context, "ETHUSDT")
    
    if btc_data and eth_data:
        # Use provided cross-asset data
        btc_vol = btc_data.get("vol") or btc_data.get("volatility", 0.0)
        eth_vol = eth_data.get("vol") or eth_data.get("volatility", 0.0)
        
        # Simple lead-lag: compare current vol vs previous vol
        btc_vol_prev = btc_data.get("vol_prev", btc_vol)
        eth_vol_prev = eth_data.get("vol_prev", eth_vol)
        
        btc_vol_change = btc_vol - btc_vol_prev if btc_vol_prev > 0 else 0.0
        eth_vol_change = eth_vol - eth_vol_prev if eth_vol_prev > 0 else 0.0
        
        # Positive if BTC vol change precedes ETH vol change
        if abs(eth_vol_change) > 0:
            raw = btc_vol_change / max(abs(eth_vol_change), 1e-9)
        else:
            raw = 0.0
    else:
        # Simulate: use local OHLCV to approximate BTC/ETH relationship
        rows = _get_rows_from_context(context)
        if len(rows) >= 20:
            # Simulate BTC as more volatile version of ETH
            eth_vol = _compute_realized_volatility(rows, window=10)
            # BTC typically has higher vol than ETH
            btc_vol = eth_vol * 1.2
            
            # Simulate lead-lag: BTC vol changes first
            eth_vol_prev = _compute_realized_volatility(rows[:-5], window=10) if len(rows) > 5 else eth_vol
            btc_vol_prev = eth_vol_prev * 1.2
            
            btc_change = btc_vol - btc_vol_prev
            eth_change = eth_vol - eth_vol_prev
            
            if abs(eth_change) > 0:
                raw = btc_change / max(abs(eth_change), 1e-9)
            else:
                raw = 0.0
        else:
            import random
            random.seed(70)
            raw = random.uniform(-0.5, 0.5)
    
    z_score = _compute_z_score(raw, mean=0.0, std=0.5)
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


def compute_sol_l1_rotation_score(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute SOL vs other L1 rotation score signal.
    
    Positive = SOL outperforming other L1s (rotation into SOL).
    Negative = Other L1s outperforming SOL (rotation away).
    
    TODO: Replace with real multi-asset rotation data:
    - L1 basket performance tracking
    - Relative strength analysis
    - Sector rotation models
    
    Args:
        context: SignalContext or legacy dict with cross_asset data
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    # Try to get SOL and other L1 data from context.cross_asset
    sol_data = _get_cross_asset_data(context, "SOLUSDT")
    eth_data = _get_cross_asset_data(context, "ETHUSDT")
    avax_data = _get_cross_asset_data(context, "AVAXUSDT")
    
    if sol_data and (eth_data or avax_data):
        # Use provided cross-asset data
        sol_return = sol_data.get("return") or sol_data.get("returns", 0.0)
        eth_return = eth_data.get("return") or eth_data.get("returns", 0.0) if eth_data else 0.0
        avax_return = avax_data.get("return") or avax_data.get("returns", 0.0) if avax_data else 0.0
        
        # Average of other L1s
        other_l1_returns = [r for r in [eth_return, avax_return] if r != 0.0]
        avg_other = sum(other_l1_returns) / len(other_l1_returns) if other_l1_returns else 0.0
        
        # Rotation score = SOL return - average other L1 return
        raw = sol_return - avg_other
    else:
        # Simulate: use local OHLCV to approximate rotation
        rows = _get_rows_from_context(context)
        if len(rows) >= 10:
            # Simulate SOL as more volatile than ETH
            sol_return = (rows[-1].get("close", 0) - rows[-5].get("close", 0)) / max(rows[-5].get("close", 1), 1e-6)
            # Simulate ETH as baseline
            eth_return = sol_return * 0.8  # ETH moves less
            
            raw = sol_return - eth_return
        else:
            import random
            random.seed(71)
            raw = random.uniform(-0.05, 0.05)
    
    z_score = _compute_z_score(raw, mean=0.0, std=0.02)
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


def compute_eth_ecosystem_momentum(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute ETH ecosystem momentum signal.
    
    Positive = ETH complex gaining vs broader market (BTC).
    Combines ETH + ETH ecosystem proxies if available.
    
    TODO: Replace with real ecosystem data:
    - ETH ecosystem token tracking
    - DeFi sector proxies
    - L2 performance metrics
    
    Args:
        context: SignalContext or legacy dict with cross_asset data
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    # Try to get ETH and BTC data from context.cross_asset
    eth_data = _get_cross_asset_data(context, "ETHUSDT")
    btc_data = _get_cross_asset_data(context, "BTCUSDT")
    
    # Try to get ETH ecosystem proxies
    ecosystem_proxies = []
    for symbol in ["LINKUSDT", "UNIUSDT", "AAVEUSDT"]:
        proxy_data = _get_cross_asset_data(context, symbol)
        if proxy_data:
            ecosystem_proxies.append(proxy_data)
    
    if eth_data and btc_data:
        # Use provided cross-asset data
        eth_return = eth_data.get("return") or eth_data.get("returns", 0.0)
        btc_return = btc_data.get("return") or btc_data.get("returns", 0.0)
        
        # Add ecosystem proxy returns if available
        if ecosystem_proxies:
            proxy_returns = [p.get("return") or p.get("returns", 0.0) for p in ecosystem_proxies]
            avg_proxy = sum(proxy_returns) / len(proxy_returns)
            # Weighted: 70% ETH, 30% ecosystem average
            eth_complex_return = 0.7 * eth_return + 0.3 * avg_proxy
        else:
            eth_complex_return = eth_return
        
        # Momentum = ETH complex return - BTC return
        raw = eth_complex_return - btc_return
    else:
        # Simulate: use local OHLCV
        rows = _get_rows_from_context(context)
        if len(rows) >= 10:
            eth_return = (rows[-1].get("close", 0) - rows[-5].get("close", 0)) / max(rows[-5].get("close", 1), 1e-6)
            # Simulate BTC as baseline
            btc_return = eth_return * 0.9  # BTC moves slightly less
            
            raw = eth_return - btc_return
        else:
            import random
            random.seed(72)
            raw = random.uniform(-0.03, 0.03)
    
    z_score = _compute_z_score(raw, mean=0.0, std=0.015)
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


def compute_stablecoin_flow_pressure(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute stablecoin flow pressure signal.
    
    Positive = net inflow into stablecoins (dry powder, risk-on potential).
    Negative = net outflow from stablecoins (risk-off).
    
    TODO: Replace with real stablecoin data:
    - Stablecoin supply tracking (USDT, USDC, DAI)
    - Exchange stablecoin reserves
    - On-chain flow analytics
    
    Args:
        context: SignalContext or legacy dict with cross_asset data
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    # Try to get stablecoin data from context.cross_asset
    stable_data = _get_cross_asset_data(context, "STABLE")
    usdt_data = _get_cross_asset_data(context, "USDT")
    
    if stable_data or usdt_data:
        # Use provided stablecoin data
        supply_delta = None
        if stable_data:
            supply_delta = stable_data.get("supply_delta") or stable_data.get("flow", 0.0)
        elif usdt_data:
            supply_delta = usdt_data.get("supply_delta") or usdt_data.get("flow", 0.0)
        
        if supply_delta is not None:
            # Normalize: positive = inflow (risk-on potential)
            raw = supply_delta / 1e9  # Scale down
        else:
            raw = 0.0
    else:
        # Simulate: use price/volume patterns as proxy
        rows = _get_rows_from_context(context)
        if len(rows) >= 10:
            # Calm periods + up moves = stablecoin inflow (risk-on)
            recent_vol = _compute_realized_volatility(rows[-5:], window=5)
            price_change = (rows[-1].get("close", 0) - rows[-5].get("close", 0)) / max(rows[-5].get("close", 1), 1e-6)
            
            # Low vol + positive price = stablecoin inflow
            raw = (1.0 - min(1.0, recent_vol * 100)) * max(0.0, price_change) * 0.1
        else:
            import random
            random.seed(73)
            raw = random.uniform(-0.01, 0.01)
    
    z_score = _compute_z_score(raw, mean=0.0, std=0.005)
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


def compute_sector_risk_score(context: ContextLike = None) -> Dict[str, Any]:
    """
    Compute sector risk score signal.
    
    Higher = higher system-wide sector risk (volatility/drawdowns across sectors).
    Summarizes realized vol/drawdowns across sector proxies.
    
    TODO: Replace with real sector data:
    - Sector proxies (L1, DeFi, meme, etc.)
    - Cross-sector volatility aggregation
    - Sector correlation matrices
    
    Args:
        context: SignalContext or legacy dict with cross_asset data
    
    Returns:
        Dict with raw, z_score, direction_prob, confidence, drift
    """
    # Try to get sector proxies from context.cross_asset
    sector_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT"]
    sector_data = []
    
    for symbol in sector_symbols:
        data = _get_cross_asset_data(context, symbol)
        if data:
            sector_data.append(data)
    
    if len(sector_data) >= 2:
        # Use provided sector data
        sector_vols = []
        sector_drawdowns = []
        
        for data in sector_data:
            vol = data.get("vol") or data.get("volatility", 0.0)
            drawdown = data.get("drawdown", 0.0)
            
            if vol > 0:
                sector_vols.append(vol)
            if drawdown < 0:
                sector_drawdowns.append(abs(drawdown))
        
        # Aggregate: average vol + max drawdown
        avg_vol = sum(sector_vols) / len(sector_vols) if sector_vols else 0.0
        max_dd = max(sector_drawdowns) if sector_drawdowns else 0.0
        
        # Combine into risk score [0, 1]
        raw = min(1.0, (avg_vol * 10 + max_dd) / 2.0)
    else:
        # Simulate: use local OHLCV to approximate sector risk
        rows = _get_rows_from_context(context)
        if len(rows) >= 20:
            # Higher vol = higher sector risk
            vol = _compute_realized_volatility(rows, window=20)
            
            # Compute drawdown
            closes = [row.get("close", 0) for row in rows[-20:]]
            if closes:
                peak = max(closes)
                current = closes[-1]
                drawdown = (peak - current) / peak if peak > 0 else 0.0
            else:
                drawdown = 0.0
            
            raw = min(1.0, (vol * 10 + drawdown) / 2.0)
        else:
            import random
            random.seed(74)
            raw = random.uniform(0.0, 0.5)
    
    z_score = _compute_z_score(raw, mean=0.3, std=0.2)
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

