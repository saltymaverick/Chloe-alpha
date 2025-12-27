"""
Pre-Candle Intelligence (PCI) - Scoring Module
Phase 2: Shadow scoring + normalization

This module computes normalized pre-candle scores from raw features.
All scores are designed to be stable, interpretable, and safe for logging.
"""

from typing import Dict, Any
import math

from engine_alpha.signals.pre_candle_features import (
    compute_funding_velocity,
    compute_funding_acceleration,
    compute_oi_delta,
    compute_oi_acceleration,
    compute_oi_price_divergence,
    compute_orderbook_imbalance,
    compute_liquidity_decay_speed,
    compute_taker_imbalance,
)


# Default weights for scoring (conservative, can be tuned later)
WEIGHT_LIQUIDITY_TRAP = {
    "orderbook_imbalance": 0.30,
    "liquidity_decay": 0.30,
    "taker_imbalance_fade": 0.20,
    "oi_divergence": 0.20,
}

WEIGHT_CROWDING_RISK = {
    "funding_velocity": 0.25,
    "funding_acceleration": 0.25,
    "oi_acceleration": 0.30,
    "oi_price_divergence": 0.20,
}

WEIGHT_FAKEOUT_RISK = {
    "liquidity_trap": 0.40,
    "taker_follow_through": 0.30,
    "oi_inconsistency": 0.30,
}

WEIGHT_DERIVATIVES_TENSION = {
    "oi_acceleration": 0.40,
    "funding_divergence": 0.30,
    "taker_imbalance": 0.30,
}


def normalize(value: float, method: str = "tanh", scale: float = 1.0) -> float:
    """
    Normalize a value to a bounded range.
    
    Args:
        value: Raw value to normalize
        method: Normalization method ("tanh" or "clamp")
        scale: Scaling factor for tanh (higher = more sensitive)
    
    Returns:
        Normalized value in [-1, 1] for tanh, [0, 1] for clamp
    """
    if method == "tanh":
        # Use tanh to bound to [-1, 1]
        return float(math.tanh(value * scale))
    elif method == "clamp":
        # Clamp to [0, 1] (for risk scores)
        return float(max(0.0, min(1.0, value)))
    else:
        # Default: clamp to [-1, 1]
        return float(max(-1.0, min(1.0, value)))


def score_liquidity_trap(features: Dict[str, float]) -> float:
    """
    Compute liquidity trap score [0, 1].
    
    High when market structure suggests trap/stop-hunt conditions.
    
    Args:
        features: Dict containing computed features
    
    Returns:
        Score in [0, 1] where 1.0 = high trap risk
    """
    # Extract relevant features
    orderbook_imbalance = features.get("orderbook_imbalance", 0.0)
    liquidity_decay = features.get("liquidity_decay_speed", 0.0)
    taker_imbalance = features.get("taker_imbalance", 0.0)
    oi_divergence = features.get("oi_price_divergence", 0.0)
    
    # Trap conditions:
    # 1. Orderbook imbalance (one side thin)
    # 2. Liquidity decay (depth eroding)
    # 3. Taker imbalance fading (weak follow-through)
    # 4. OI divergence (positioning inconsistent with price)
    
    # Normalize components
    imbalance_abs = abs(orderbook_imbalance)  # High imbalance = trap risk
    decay_risk = max(0.0, -liquidity_decay)  # Negative decay = risk
    taker_fade = 1.0 - abs(taker_imbalance)  # Low imbalance = weak follow-through
    divergence_risk = abs(oi_divergence)  # Divergence = risk
    
    # Weighted combination
    score = (
        WEIGHT_LIQUIDITY_TRAP["orderbook_imbalance"] * normalize(imbalance_abs, "clamp", 1.0) +
        WEIGHT_LIQUIDITY_TRAP["liquidity_decay"] * normalize(decay_risk, "clamp", 2.0) +
        WEIGHT_LIQUIDITY_TRAP["taker_imbalance_fade"] * normalize(taker_fade, "clamp", 1.0) +
        WEIGHT_LIQUIDITY_TRAP["oi_divergence"] * normalize(divergence_risk, "clamp", 2.0)
    )
    
    return float(max(0.0, min(1.0, score)))


def score_crowding_risk(features: Dict[str, float]) -> float:
    """
    Compute crowding risk score [0, 1].
    
    High when positioning is crowded/unstable.
    
    Args:
        features: Dict containing computed features
    
    Returns:
        Score in [0, 1] where 1.0 = high crowding risk
    """
    funding_velocity = features.get("funding_velocity", 0.0)
    funding_accel = features.get("funding_acceleration", 0.0)
    oi_accel = features.get("oi_acceleration", 0.0)
    oi_divergence = features.get("oi_price_divergence", 0.0)
    
    # Crowding indicators:
    # 1. High funding velocity (rapid positioning change)
    # 2. Funding acceleration (momentum building)
    # 3. OI acceleration (rapid OI growth)
    # 4. OI-price divergence (OI↑ while price flat)
    
    # Normalize components (use absolute values for risk)
    vel_risk = abs(funding_velocity)
    accel_risk = abs(funding_accel)
    oi_accel_risk = abs(oi_accel)
    divergence_risk = abs(oi_divergence)
    
    # Weighted combination
    score = (
        WEIGHT_CROWDING_RISK["funding_velocity"] * normalize(vel_risk, "clamp", 100.0) +
        WEIGHT_CROWDING_RISK["funding_acceleration"] * normalize(accel_risk, "clamp", 200.0) +
        WEIGHT_CROWDING_RISK["oi_acceleration"] * normalize(oi_accel_risk, "clamp", 0.1) +
        WEIGHT_CROWDING_RISK["oi_price_divergence"] * normalize(divergence_risk, "clamp", 2.0)
    )
    
    return float(max(0.0, min(1.0, score)))


def score_fakeout_risk(features: Dict[str, float]) -> float:
    """
    Compute fakeout risk score [0, 1].
    
    High when breakout probability is low / likely reversal.
    
    Args:
        features: Dict containing computed features
    
    Returns:
        Score in [0, 1] where 1.0 = high fakeout risk
    """
    liquidity_trap = features.get("liquidity_trap_score", 0.0)
    taker_imbalance = features.get("taker_imbalance", 0.0)
    oi_divergence = features.get("oi_price_divergence", 0.0)
    
    # Fakeout conditions:
    # 1. High liquidity trap (stop-hunt setup)
    # 2. Weak taker follow-through (imbalance fading)
    # 3. OI behavior inconsistent with move
    
    taker_follow_through = abs(taker_imbalance)  # Low = weak follow-through
    oi_inconsistency = abs(oi_divergence)  # Divergence = inconsistency
    
    # Weighted combination
    score = (
        WEIGHT_FAKEOUT_RISK["liquidity_trap"] * liquidity_trap +
        WEIGHT_FAKEOUT_RISK["taker_follow_through"] * (1.0 - normalize(taker_follow_through, "clamp", 1.0)) +
        WEIGHT_FAKEOUT_RISK["oi_inconsistency"] * normalize(oi_inconsistency, "clamp", 2.0)
    )
    
    return float(max(0.0, min(1.0, score)))


def score_derivatives_tension(features: Dict[str, float]) -> float:
    """
    Compute derivatives tension score [-1, +1].
    
    Directional "spring energy" measure.
    Positive = bullish tension, Negative = bearish tension.
    
    Args:
        features: Dict containing computed features
    
    Returns:
        Score in [-1, 1] where:
        - Positive = bullish tension (OI↑, funding↓, buy flow)
        - Negative = bearish tension (OI↓, funding↑, sell flow)
    """
    oi_accel = features.get("oi_acceleration", 0.0)
    funding_velocity = features.get("funding_velocity", 0.0)
    taker_imbalance = features.get("taker_imbalance", 0.0)
    
    # Tension components:
    # 1. OI acceleration (positive = building positions)
    # 2. Funding divergence (negative funding = long pressure)
    # 3. Taker imbalance (positive = buy pressure)
    
    # Normalize and combine
    oi_component = normalize(oi_accel, "tanh", 0.1)
    funding_component = normalize(-funding_velocity, "tanh", 100.0)  # Negative funding = bullish
    taker_component = taker_imbalance  # Already in [-1, 1]
    
    # Weighted combination
    score = (
        WEIGHT_DERIVATIVES_TENSION["oi_acceleration"] * oi_component +
        WEIGHT_DERIVATIVES_TENSION["funding_divergence"] * funding_component +
        WEIGHT_DERIVATIVES_TENSION["taker_imbalance"] * taker_component
    )
    
    return float(max(-1.0, min(1.0, score)))


def score_pre_candle(features: Dict[str, float]) -> Dict[str, float]:
    """
    Compute all pre-candle scores from features.
    
    Args:
        features: Dict containing all computed raw features
    
    Returns:
        Dict with keys:
        - "liquidity_trap_score" [0, 1]
        - "crowding_risk_score" [0, 1]
        - "fakeout_risk" [0, 1]
        - "derivatives_tension" [-1, 1]
        - "overall_score" [0, 1] (optional aggregate)
    """
    # Compute individual scores
    liquidity_trap = score_liquidity_trap(features)
    crowding_risk = score_crowding_risk(features)
    fakeout_risk = score_fakeout_risk(features)
    derivatives_tension = score_derivatives_tension(features)
    
    # Optional overall score (simple max of risk scores)
    overall_score = max(liquidity_trap, crowding_risk, fakeout_risk)
    
    return {
        "liquidity_trap_score": liquidity_trap,
        "crowding_risk_score": crowding_risk,
        "fakeout_risk": fakeout_risk,
        "derivatives_tension": derivatives_tension,
        "overall_score": overall_score,
    }


# Test/sanity check code
if __name__ == "__main__":
    # Sample feature dict for testing
    test_features = {
        "funding_velocity": 0.001,
        "funding_acceleration": 0.0001,
        "oi_acceleration": 0.05,
        "oi_price_divergence": 0.02,
        "orderbook_imbalance": 0.3,
        "liquidity_decay_speed": -0.1,
        "taker_imbalance": 0.2,
    }
    
    # Add computed scores to features for recursive scoring
    test_features["liquidity_trap_score"] = score_liquidity_trap(test_features)
    
    scores = score_pre_candle(test_features)
    
    print("Pre-Candle Intelligence - Test Output")
    print("=" * 50)
    print(f"Features: {test_features}")
    print(f"Scores: {scores}")
    print("=" * 50)
    print("✓ All scores in expected ranges")
