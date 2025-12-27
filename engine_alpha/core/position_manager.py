"""
Position Manager - Module 10 (Positioning & Risk Engine)

Computes position size based on confidence, volatility, and drift.
"""

import yaml
from pathlib import Path
from typing import Dict, Any, Optional, Union

from engine_alpha.core.paths import CONFIG
from engine_alpha.core.confidence_engine import ConfidenceState


def _load_risk_config() -> Dict[str, Any]:
    """Load risk configuration from risk.yaml."""
    risk_path = CONFIG / "risk.yaml"
    if not risk_path.exists():
        return _get_default_risk_config()
    
    try:
        with open(risk_path, "r") as f:
            data = yaml.safe_load(f) or {}
            pos_config = data.get("position_sizing", {})
            if not pos_config:
                return _get_default_risk_config()
            return pos_config
    except Exception:
        return _get_default_risk_config()


def _get_default_risk_config() -> Dict[str, Any]:
    """Return default risk configuration."""
    return {
        "base_position_size": 1.0,
        "max_position_size": 3.0,
        "max_leverage": 3.0,
        "confidence_bands": [
            {"min": 0.0, "max": 0.3, "multiplier": 0.0},
            {"min": 0.3, "max": 0.6, "multiplier": 0.5},
            {"min": 0.6, "max": 0.8, "multiplier": 1.0},
            {"min": 0.8, "max": 1.0, "multiplier": 1.5},
        ],
        "volatility_adjust": {
            "enabled": True,
            "target_vol": 1.0,
            "max_multiplier": 1.5,
        },
        "drift_penalty": {
            "enabled": True,
            "max_penalty": 1.0,
        },
    }


def compute_position_size(
    confidence_state: Union[ConfidenceState, Dict[str, Any]],
    volatility_estimate: float,
    drift_state: Dict[str, Any],
    risk_config: Optional[Dict[str, Any]] = None,
) -> float:
    """
    Compute final position size multiplier based on:
    - base_position_size
    - confidence → confidence_bands
    - volatility adjustment
    - drift penalties
    - max_position_size cap
    
    Args:
        confidence_state: ConfidenceState or Dict with "confidence" key (0-1)
        volatility_estimate: Normalized volatility estimate
        drift_state: Dict with "drift_score" key (0-1)
        risk_config: Optional risk config dict (loads from risk.yaml if None)
    
    Returns:
        Float multiplier (e.g., 0.5 = half size, 2.0 = 2x size)
    """
    if risk_config is None:
        risk_config = _load_risk_config()
    
    # Step 1: Start with base size
    size = float(risk_config.get("base_position_size", 1.0))
    
    # Step 2: Apply confidence band multiplier
    # Handle both ConfidenceState and dict
    if isinstance(confidence_state, ConfidenceState):
        confidence = float(confidence_state.confidence)
    else:
        confidence = float(confidence_state.get("confidence", 0.0))
    confidence_bands = risk_config.get("confidence_bands", [])
    
    conf_multiplier = 0.0
    for band in confidence_bands:
        min_conf = float(band.get("min", 0.0))
        max_conf = float(band.get("max", 1.0))
        if min_conf <= confidence < max_conf:
            conf_multiplier = float(band.get("multiplier", 0.0))
            break
    
    size *= conf_multiplier
    
    # Step 3: Volatility adjustment
    vol_config = risk_config.get("volatility_adjust", {})
    if vol_config.get("enabled", True):
        target_vol = float(vol_config.get("target_vol", 1.0))
        max_multiplier = float(vol_config.get("max_multiplier", 1.5))
        
        # Normalize: shrink when vol is high, grow when vol is low
        vol_factor = min(
            max_multiplier,
            target_vol / max(volatility_estimate, 1e-9)
        )
        size *= vol_factor
    
    # Step 4: Drift penalty
    drift_config = risk_config.get("drift_penalty", {})
    if drift_config.get("enabled", True):
        drift_score = float(drift_state.get("drift_score", 0.0))
        max_penalty = float(drift_config.get("max_penalty", 1.0))
        
        penalty = 1.0 - (drift_score * max_penalty)
        size *= max(0.0, penalty)  # Don't allow negative
    
    # Step 5: Enforce max_position_size cap
    max_size = float(risk_config.get("max_position_size", 3.0))
    size = min(size, max_size)
    
    # Ensure non-negative
    size = max(0.0, size)
    
    return size

