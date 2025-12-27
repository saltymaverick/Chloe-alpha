"""
Entry Logic - Module 11 (Unified Entry Decisions)

Unified entry decision function using ConfidenceState + RegimeState + DriftState + position sizing.
"""

from typing import Dict, Any, Optional, Union
from engine_alpha.core.confidence_engine import ConfidenceState
from engine_alpha.core.drift_detector import DriftState

# RegimeState can be a dict or object with 'primary' attribute
RegimeState = Union[Dict[str, Any], Any]


def should_enter_trade(
    ctx: Dict[str, Any],
    signal_vector: list,
    raw_registry: Dict[str, Dict[str, Any]],
    regime_state: RegimeState,
    drift_state: DriftState,
    confidence_state: ConfidenceState,
    size_multiplier: float,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Decide whether to enter a trade using the full quant stack.
    
    Args:
        ctx: SignalContext or context dict
        signal_vector: Normalized signal vector
        raw_registry: Raw signal registry
        regime_state: RegimeState from classify_regime
        drift_state: DriftState from compute_drift
        confidence_state: ConfidenceState from compute_confidence
        size_multiplier: Position size multiplier from compute_position_size
        config: Configuration dict with thresholds
    
    Returns:
        {
            "enter": bool,
            "direction": Optional["long" | "short"],
            "size_multiplier": float,
            "reason": str,
        }
    """
    # Load thresholds from config
    entry_min_confidence = float(config.get("entry_min_confidence", 0.60))
    max_drift_for_entries = float(config.get("max_drift_for_entries", 0.5))
    
    # Gate 1: Confidence threshold
    if confidence_state.confidence < entry_min_confidence:
        return {
            "enter": False,
            "direction": None,
            "size_multiplier": 0.0,
            "reason": f"skip: conf {confidence_state.confidence:.2f} < {entry_min_confidence:.2f} threshold",
        }
    
    # Gate 2: Drift threshold
    if drift_state.drift_score > max_drift_for_entries:
        return {
            "enter": False,
            "direction": None,
            "size_multiplier": 0.0,
            "reason": f"skip: drift {drift_state.drift_score:.2f} > {max_drift_for_entries:.2f} max_drift_for_entries",
        }
    
    # Gate 3: Size multiplier
    if size_multiplier <= 0:
        return {
            "enter": False,
            "direction": None,
            "size_multiplier": 0.0,
            "reason": f"skip: size_multiplier {size_multiplier:.2f} <= 0",
        }
    
    # Gate 4: Regime check (optional - can be disabled in config)
    regime_allows = config.get("regime_allows_entry", True)
    if regime_allows:
        # Check if regime allows entry (e.g., skip CHOP if configured)
        primary_regime = regime_state.primary.lower() if hasattr(regime_state, 'primary') else str(regime_state.get("primary", "")).lower()
        if primary_regime == "chop" and config.get("skip_chop", False):
            return {
                "enter": False,
                "direction": None,
                "size_multiplier": 0.0,
                "reason": f"skip: regime {primary_regime} does not allow entry",
            }
    
    # Determine direction from signal vector or regime
    # Use aggregate direction from signal_vector (positive = long, negative = short)
    direction = None
    if signal_vector:
        # Simple heuristic: sum of signal vector
        signal_sum = sum(signal_vector) if signal_vector else 0.0
        if signal_sum > 0.1:  # Threshold for long bias
            direction = "long"
        elif signal_sum < -0.1:  # Threshold for short bias
            direction = "short"
        else:
            # Neutral - no clear direction
            return {
                "enter": False,
                "direction": None,
                "size_multiplier": 0.0,
                "reason": f"skip: neutral signal direction (sum={signal_sum:.3f})",
            }
    else:
        # Fallback: use regime direction
        primary_regime = regime_state.primary.lower() if hasattr(regime_state, 'primary') else str(regime_state.get("primary", "")).lower()
        if "up" in primary_regime:
            direction = "long"
        elif "down" in primary_regime:
            direction = "short"
        else:
            return {
                "enter": False,
                "direction": None,
                "size_multiplier": 0.0,
                "reason": f"skip: no clear direction from regime {primary_regime}",
            }
    
    # All gates passed - enter trade
    primary_regime_str = regime_state.primary if hasattr(regime_state, 'primary') else regime_state.get("primary", "unknown")
    return {
        "enter": True,
        "direction": direction,
        "size_multiplier": size_multiplier,
        "reason": (
            f"enter: conf={confidence_state.confidence:.2f}, "
            f"drift={drift_state.drift_score:.2f}, "
            f"regime={primary_regime_str}, "
            f"size={size_multiplier:.2f}x"
        ),
    }

