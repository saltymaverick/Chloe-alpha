"""
Pre-Candle Intelligence (PCI) - Feature Computation Module
Phase 1: Pure feature computation functions (no gates, no state)

This module provides pure functions for computing pre-candle features
from raw market data (funding, OI, orderbook, trade flow).
All functions are deterministic and safe to call with missing/incomplete data.
"""

from typing import List, Optional
import math


def compute_funding_velocity(funding_series: List[float]) -> float:
    """
    Compute funding rate velocity (rate of change).
    
    Args:
        funding_series: List of funding rates (most recent last)
                      Minimum 2 values needed for velocity
    
    Returns:
        Velocity (change per period). Returns 0.0 if insufficient data.
    """
    if len(funding_series) < 2:
        return 0.0
    
    try:
        # Simple first difference (most recent - previous)
        velocity = funding_series[-1] - funding_series[-2]
        return float(velocity)
    except (TypeError, IndexError, ValueError):
        return 0.0


def compute_funding_acceleration(funding_series: List[float]) -> float:
    """
    Compute funding rate acceleration (change in velocity).
    
    Args:
        funding_series: List of funding rates (most recent last)
                      Minimum 3 values needed for acceleration
    
    Returns:
        Acceleration (second derivative). Returns 0.0 if insufficient data.
    """
    if len(funding_series) < 3:
        return 0.0
    
    try:
        # Second difference: (v[t] - v[t-1]) - (v[t-1] - v[t-2])
        # = v[t] - 2*v[t-1] + v[t-2]
        v_t = funding_series[-1]
        v_t1 = funding_series[-2]
        v_t2 = funding_series[-3]
        acceleration = v_t - 2.0 * v_t1 + v_t2
        return float(acceleration)
    except (TypeError, IndexError, ValueError):
        return 0.0


def compute_oi_delta(oi_series: List[float]) -> float:
    """
    Compute Open Interest delta (change).
    
    Args:
        oi_series: List of OI values (most recent last)
                  Minimum 2 values needed
    
    Returns:
        OI delta (absolute change). Returns 0.0 if insufficient data.
    """
    if len(oi_series) < 2:
        return 0.0
    
    try:
        delta = oi_series[-1] - oi_series[-2]
        return float(delta)
    except (TypeError, IndexError, ValueError):
        return 0.0


def compute_oi_acceleration(oi_series: List[float]) -> float:
    """
    Compute Open Interest acceleration (change in delta).
    
    Args:
        oi_series: List of OI values (most recent last)
                  Minimum 3 values needed
    
    Returns:
        OI acceleration. Returns 0.0 if insufficient data.
    """
    if len(oi_series) < 3:
        return 0.0
    
    try:
        oi_t = oi_series[-1]
        oi_t1 = oi_series[-2]
        oi_t2 = oi_series[-3]
        acceleration = oi_t - 2.0 * oi_t1 + oi_t2
        return float(acceleration)
    except (TypeError, IndexError, ValueError):
        return 0.0


def compute_oi_price_divergence(oi_series: List[float], price_series: List[float]) -> float:
    """
    Compute OI-Price divergence (OI rising while price flat/falling, or vice versa).
    
    Args:
        oi_series: List of OI values (most recent last)
        price_series: List of price values (most recent last)
                    Must match length of oi_series
    
    Returns:
        Divergence score (positive = OI↑ while price↓ or flat, negative = OI↓ while price↑).
        Returns 0.0 if insufficient data or mismatched lengths.
    """
    if len(oi_series) < 2 or len(price_series) < 2:
        return 0.0
    
    if len(oi_series) != len(price_series):
        return 0.0
    
    try:
        # Compute normalized changes
        oi_delta = oi_series[-1] - oi_series[-2]
        price_delta = price_series[-1] - price_series[-2]
        
        # Normalize by previous values to get percentage changes
        if oi_series[-2] != 0:
            oi_pct = oi_delta / abs(oi_series[-2])
        else:
            oi_pct = 0.0
        
        if price_series[-2] != 0:
            price_pct = price_delta / abs(price_series[-2])
        else:
            price_pct = 0.0
        
        # Divergence: OI moving opposite to price (or OI moving while price flat)
        # Positive when OI↑ but price↓ or flat; negative when OI↓ but price↑
        divergence = oi_pct - price_pct
        return float(divergence)
    except (TypeError, IndexError, ValueError, ZeroDivisionError):
        return 0.0


def compute_orderbook_imbalance(
    bid_depth_near: float,
    ask_depth_near: float,
    bid_depth_far: Optional[float] = None,
    ask_depth_far: Optional[float] = None
) -> float:
    """
    Compute orderbook imbalance (bid vs ask depth).
    
    Args:
        bid_depth_near: Bid depth near the mid price
        ask_depth_near: Ask depth near the mid price
        bid_depth_far: Optional bid depth further from mid
        ask_depth_far: Optional ask depth further from mid
    
    Returns:
        Imbalance score in [-1, 1]:
        - Positive = bid-heavy (bullish pressure)
        - Negative = ask-heavy (bearish pressure)
        Returns 0.0 if depths are zero or invalid.
    """
    try:
        if bid_depth_near <= 0 or ask_depth_near <= 0:
            return 0.0
        
        # Simple imbalance: (bid - ask) / (bid + ask)
        total_near = bid_depth_near + ask_depth_near
        if total_near == 0:
            return 0.0
        
        imbalance_near = (bid_depth_near - ask_depth_near) / total_near
        
        # If far depth available, weight it less
        if bid_depth_far is not None and ask_depth_far is not None:
            if bid_depth_far > 0 and ask_depth_far > 0:
                total_far = bid_depth_far + ask_depth_far
                if total_far > 0:
                    imbalance_far = (bid_depth_far - ask_depth_far) / total_far
                    # Weight near 70%, far 30%
                    imbalance = 0.7 * imbalance_near + 0.3 * imbalance_far
                else:
                    imbalance = imbalance_near
            else:
                imbalance = imbalance_near
        else:
            imbalance = imbalance_near
        
        # Clamp to [-1, 1]
        return float(max(-1.0, min(1.0, imbalance)))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def compute_liquidity_decay_speed(depth_series: List[float]) -> float:
    """
    Compute liquidity decay speed (how quickly depth erodes).
    
    Args:
        depth_series: List of depth values (most recent last)
                    Minimum 2 values needed
    
    Returns:
        Decay speed (negative = depth decreasing, positive = depth increasing).
        Returns 0.0 if insufficient data.
    """
    if len(depth_series) < 2:
        return 0.0
    
    try:
        # Simple rate of change
        current = depth_series[-1]
        previous = depth_series[-2]
        
        if previous == 0:
            return 0.0
        
        # Percentage change (negative = decay)
        decay_rate = (current - previous) / previous
        return float(decay_rate)
    except (TypeError, IndexError, ValueError, ZeroDivisionError):
        return 0.0


def compute_taker_imbalance(trades_buy_vol: float, trades_sell_vol: float) -> float:
    """
    Compute taker flow imbalance (buy vs sell volume).
    
    Args:
        trades_buy_vol: Total buy volume (taker buys)
        trades_sell_vol: Total sell volume (taker sells)
    
    Returns:
        Imbalance score in [-1, 1]:
        - Positive = buy-heavy (bullish)
        - Negative = sell-heavy (bearish)
        Returns 0.0 if both volumes are zero.
    """
    try:
        total_vol = trades_buy_vol + trades_sell_vol
        if total_vol == 0:
            return 0.0
        
        imbalance = (trades_buy_vol - trades_sell_vol) / total_vol
        # Clamp to [-1, 1]
        return float(max(-1.0, min(1.0, imbalance)))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0
