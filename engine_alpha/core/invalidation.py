"""
Invalidation clarity primitives.

Computes thesis health and soft invalidation scores based on position context,
price movement, confidence decay, regime flips, and compression unwinds.
"""

from __future__ import annotations

from typing import Any, Dict, List


def clamp01(x: float | None) -> float | None:
    """
    Clamp value to [0, 1] range.
    
    Args:
        x: Value to clamp (or None)
        
    Returns:
        Clamped value in [0, 1], or None if input is None
    """
    if x is None:
        return None
    return max(0.0, min(1.0, float(x)))


def compute_invalidation(
    snapshot: Dict[str, Any],
    ts_iso: str,
    config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Compute invalidation scores and flags.
    
    Args:
        snapshot: Snapshot dict with market, execution, primitives data
        ts_iso: Current ISO timestamp
        config: Optional config dict (uses defaults if None)
        
    Returns:
        Dict with:
        - thesis_health_score: float | None (0-1, higher = healthier)
        - soft_invalidation_score: float | None (0-1, higher = more invalidated)
        - invalidation_flags: List[str]
        - invalidation_inputs: Dict with component penalties and raw values
    """
    # Default config
    default_config = {
        "mismatch_scale": 0.006,
        "conf_target": 0.55,
        "conf_scale": 0.20,
        "weights": {
            "mismatch": 0.45,
            "confidence": 0.35,
            "regime": 0.15,
            "compression": 0.05,
        },
        "compression_drop_trigger": 0.15,
    }
    
    cfg = config if config is not None else default_config
    mismatch_scale = cfg.get("mismatch_scale", 0.006)
    conf_target = cfg.get("conf_target", 0.55)
    conf_scale = cfg.get("conf_scale", 0.20)
    weights = cfg.get("weights", default_config["weights"])
    compression_drop_trigger = cfg.get("compression_drop_trigger", 0.15)
    
    # Extract current price
    market = snapshot.get("market", {})
    price = market.get("price")
    
    # Fallback to last close from OHLCV if price not set
    if price is None:
        ohlcv = market.get("ohlcv")
        if ohlcv and isinstance(ohlcv, list) and len(ohlcv) > 0:
            last_bar = ohlcv[-1]
            price = last_bar.get("close")
    
    # Extract position
    execution = snapshot.get("execution", {})
    position = execution.get("position", {})
    is_open = position.get("is_open", False)
    side = position.get("side")
    entry_price = position.get("entry_price")
    
    # If no position, return None scores
    if not is_open or side is None or entry_price is None or price is None:
        return {
            "thesis_health_score": None,
            "soft_invalidation_score": None,
            "invalidation_flags": [],
            "invalidation_inputs": {"reason": "no_position" if not is_open else "missing_data"},
        }
    
    # Initialize inputs dict for observability
    inputs: Dict[str, Any] = {
        "price": price,
        "entry_price": entry_price,
        "side": side,
    }
    
    # 1. Direction mismatch penalty
    # LONG: ret = (price - entry) / entry; penalty uses only negative side
    # SHORT: ret = (entry - price) / entry; penalty uses only negative side
    if side.upper() == "LONG":
        ret = (price - entry_price) / entry_price
    elif side.upper() == "SHORT":
        ret = (entry_price - price) / entry_price
    else:
        ret = 0.0
    
    # Penalty only for negative returns (price moving against position)
    mismatch_penalty = clamp01(abs(min(ret, 0)) / mismatch_scale)
    inputs["mismatch_penalty"] = mismatch_penalty
    inputs["return_pct"] = ret * 100
    
    # 2. Confidence penalty
    primitives = snapshot.get("primitives", {})
    decay = primitives.get("decay", {})
    confidence_decayed = decay.get("confidence_decayed")
    
    conf_penalty = None
    if confidence_decayed is not None:
        conf_penalty = clamp01((conf_target - confidence_decayed) / conf_scale)
        inputs["confidence_decayed"] = confidence_decayed
        inputs["conf_penalty"] = conf_penalty
    else:
        inputs["confidence_decayed"] = None
        inputs["conf_penalty"] = None
    
    # 3. Regime flip penalty (optional)
    regime_penalty = 0.0
    regime_flip = False
    regime = snapshot.get("regime", {})
    current_regime = regime.get("name") if isinstance(regime, dict) else None
    decision = snapshot.get("decision", {})
    regime_at_entry = decision.get("regime_at_entry")
    
    if current_regime and regime_at_entry and current_regime != regime_at_entry:
        regime_penalty = 0.35
        regime_flip = True
        inputs["regime_flip"] = True
        inputs["current_regime"] = current_regime
        inputs["regime_at_entry"] = regime_at_entry
    else:
        inputs["regime_flip"] = False
    
    # 4. Compression unwind penalty (optional, mild)
    compression_penalty = 0.0
    compression_release = False
    compression = primitives.get("compression", {})
    compression_score = compression.get("compression_score")
    time_in_compression_s = compression.get("time_in_compression_s")
    
    # Check if compression was high and now dropped
    if compression_score is not None:
        # If we were in compression (time > 0 or score was high) and score dropped
        was_compressed = time_in_compression_s is not None and time_in_compression_s > 0
        if was_compressed and compression_score < (0.6 - compression_drop_trigger):
            compression_penalty = 0.10
            compression_release = True
            inputs["compression_release"] = True
            inputs["compression_score"] = compression_score
            inputs["time_in_compression_s"] = time_in_compression_s
        else:
            inputs["compression_release"] = False
    
    # Combine penalties with weights
    w_m = weights.get("mismatch", 0.45)
    w_c = weights.get("confidence", 0.35)
    w_r = weights.get("regime", 0.15)
    w_x = weights.get("compression", 0.05)
    
    # Use 0.0 for None penalties
    mismatch_val = mismatch_penalty if mismatch_penalty is not None else 0.0
    conf_val = conf_penalty if conf_penalty is not None else 0.0
    
    soft_invalidation_score = clamp01(
        w_m * mismatch_val + w_c * conf_val + w_r * regime_penalty + w_x * compression_penalty
    )
    
    # Thesis health is inverse of invalidation
    thesis_health_score = None
    if soft_invalidation_score is not None:
        thesis_health_score = clamp01(1.0 - soft_invalidation_score)
    
    # Build flags
    flags: List[str] = []
    if mismatch_penalty is not None and mismatch_penalty > 0.35:
        flags.append("PRICE_AGAINST_POSITION")
    if conf_penalty is not None and conf_penalty > 0.35:
        flags.append("CONFIDENCE_DECAYED")
    if regime_flip:
        flags.append("REGIME_FLIP")
    if compression_release:
        flags.append("COMPRESSION_RELEASE_RISK")
    
    inputs["weights"] = weights
    inputs["mismatch_penalty"] = mismatch_penalty
    inputs["regime_penalty"] = regime_penalty
    inputs["compression_penalty"] = compression_penalty
    
    return {
        "thesis_health_score": thesis_health_score,
        "soft_invalidation_score": soft_invalidation_score,
        "invalidation_flags": flags,
        "invalidation_inputs": inputs,
    }
