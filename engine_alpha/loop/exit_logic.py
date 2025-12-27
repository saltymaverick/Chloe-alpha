"""
Exit Logic - Module 12 (Unified Exit Decisions)

Unified exit decision function using ConfidenceState + RegimeState + DriftState.
"""

from typing import Dict, Any, Optional, Union
from engine_alpha.core.confidence_engine import ConfidenceState
from engine_alpha.core.drift_detector import DriftState

# RegimeState can be a dict or object with 'primary' attribute
RegimeState = Union[Dict[str, Any], Any]


def should_exit_trade(
    position: Dict[str, Any],
    ctx: Dict[str, Any],
    signal_vector: list,
    raw_registry: Dict[str, Dict[str, Any]],
    regime_state: RegimeState,
    drift_state: DriftState,
    confidence_state: ConfidenceState,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Decide whether to exit a trade using the full quant stack.
    
    Args:
        position: Current position dict with at least "side" ("long" | "short") and optionally "entry_confidence"
        ctx: SignalContext or context dict
        signal_vector: Normalized signal vector
        raw_registry: Raw signal registry
        regime_state: RegimeState from classify_regime
        drift_state: DriftState from compute_drift
        confidence_state: ConfidenceState from compute_confidence
        config: Configuration dict with thresholds
    
    Returns:
        {
            "exit": bool,
            "reason": str,
        }
    """
    position_side = position.get("side", position.get("direction", "long"))
    entry_confidence = position.get("entry_confidence", confidence_state.confidence)
    
    # Load thresholds from config
    exit_min_confidence = float(config.get("exit_min_confidence", 0.30))
    max_drift_for_open_positions = float(config.get("max_drift_for_open_positions", 0.7))
    regime_flip_exit_enabled = config.get("regime_flip_exit_enabled", True)
    
    # Exit reason 1: Confidence drop
    if confidence_state.confidence < exit_min_confidence:
        return {
            "exit": True,
            "reason": (
                f"exit: confidence dropped {entry_confidence:.2f} -> {confidence_state.confidence:.2f} "
                f"below {exit_min_confidence:.2f} threshold"
            ),
        }
    
    # Exit reason 2: Drift spike (safety exit)
    if drift_state.drift_score > max_drift_for_open_positions:
        return {
            "exit": True,
            "reason": (
                f"exit: drift_score {drift_state.drift_score:.2f} > {max_drift_for_open_positions:.2f} "
                f"(safety exit)"
            ),
        }
    
    # Exit reason 3: Regime flip (if enabled)
    if regime_flip_exit_enabled:
        primary_regime = regime_state.primary.lower() if hasattr(regime_state, 'primary') else str(regime_state.get("primary", "")).lower()
        
        # Check if regime flipped against position
        if position_side == "long":
            # Long position: exit if regime flipped to trend_down
            if "down" in primary_regime and "trend" in primary_regime:
                return {
                    "exit": True,
                    "reason": f"exit: regime flipped TREND_UP -> {regime_state.primary} (unfavorable for long)",
                }
        elif position_side == "short":
            # Short position: exit if regime flipped to trend_up
            if "up" in primary_regime and "trend" in primary_regime:
                return {
                    "exit": True,
                    "reason": f"exit: regime flipped TREND_DOWN -> {regime_state.primary} (unfavorable for short)",
                }
    
    # Exit reason 4: Signal direction flip (optional)
    signal_flip_exit_enabled = config.get("signal_flip_exit_enabled", False)
    if signal_flip_exit_enabled and signal_vector:
        signal_sum = sum(signal_vector) if signal_vector else 0.0
        if position_side == "long" and signal_sum < -0.2:
            return {
                "exit": True,
                "reason": f"exit: signal direction flipped (sum={signal_sum:.3f}, unfavorable for long)",
            }
        elif position_side == "short" and signal_sum > 0.2:
            return {
                "exit": True,
                "reason": f"exit: signal direction flipped (sum={signal_sum:.3f}, unfavorable for short)",
            }
    
    # No exit conditions met
    return {
        "exit": False,
        "reason": (
            f"hold: conf={confidence_state.confidence:.2f}, "
            f"drift={drift_state.drift_score:.2f}, "
            f"regime={regime_state.primary if hasattr(regime_state, 'primary') else regime_state.get('primary', 'unknown')}"
        ),
    }

