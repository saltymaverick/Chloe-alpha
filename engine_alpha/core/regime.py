"""
Regime classifier - Phase 2
Classifies market regime using signal outputs.
"""

import collections
from typing import Dict, Any, List, Optional
from statistics import mean, stdev


class RegimeClassifier:
    """Classifies market regime based on signal values."""
    
    def __init__(self, window_size: int = 100):
        """
        Initialize regime classifier.
        
        Args:
            window_size: Size of rolling window for z-score calculation
        """
        self.window_size = window_size
        self.atrp_history: collections.deque = collections.deque(maxlen=window_size)
        self.bb_width_history: collections.deque = collections.deque(maxlen=window_size)
        self.ret_g5_history: collections.deque = collections.deque(maxlen=window_size)
    
    def _compute_z_score(self, value: float, history: collections.deque) -> float:
        """
        Compute z-score of value relative to history.
        
        Args:
            value: Current value
            history: Historical values deque
        
        Returns:
            Z-score (fallback to 0.0 if insufficient history)
        """
        if len(history) < 2:
            return 0.0
        
        hist_list = list(history)
        hist_mean = mean(hist_list)
        hist_std = stdev(hist_list) if len(hist_list) > 1 else 1.0
        
        if hist_std == 0:
            return 0.0
        
        return (value - hist_mean) / hist_std
    
    def classify(self, signal_vector: List[float], raw_registry: Dict[str, Any]) -> Dict[str, Any]:
        """
        Classify market regime.
        
        Args:
            signal_vector: Normalized signal vector (order: Ret_G5, RSI_14, MACD_Hist, VWAP_Dist, ATRp, BB_Width, ...)
            raw_registry: Raw signal registry with values keyed by signal name
        
        Returns:
            Dictionary with "regime" key ("trend", "chop", or "high_vol")
        """
        # Extract values from raw_registry (preferred) or signal_vector
        atrp_value = raw_registry.get("ATRp", {}).get("value", 0.0)
        bb_width_value = raw_registry.get("BB_Width", {}).get("value", 0.0)
        ret_g5_value = raw_registry.get("Ret_G5", {}).get("value", 0.0)
        
        # If not in raw_registry, try to get from signal_vector by position
        # Order: Ret_G5(0), RSI_14(1), MACD_Hist(2), VWAP_Dist(3), ATRp(4), BB_Width(5), ...
        if atrp_value == 0.0 and len(signal_vector) > 4:
            # Use normalized values as fallback (but less ideal)
            atrp_value = signal_vector[4] if len(signal_vector) > 4 else 0.0
        if bb_width_value == 0.0 and len(signal_vector) > 5:
            bb_width_value = signal_vector[5] if len(signal_vector) > 5 else 0.0
        if ret_g5_value == 0.0 and len(signal_vector) > 0:
            ret_g5_value = signal_vector[0] if len(signal_vector) > 0 else 0.0
        
        # Update history
        self.atrp_history.append(atrp_value)
        self.bb_width_history.append(bb_width_value)
        self.ret_g5_history.append(abs(ret_g5_value))  # Use absolute value for Ret_G5
        
        # Compute z-scores
        atrp_z = self._compute_z_score(atrp_value, self.atrp_history)
        bb_width_z = self._compute_z_score(bb_width_value, self.bb_width_history)
        ret_g5_z = self._compute_z_score(abs(ret_g5_value), self.ret_g5_history)
        
        # Classify regime
        # Rule 1: high_vol if BB_Width z > 0.8 OR ATRp z > 0.8
        if abs(bb_width_z) > 0.8 or abs(atrp_z) > 0.8:
            regime = "high_vol"
        # Rule 2: trend if |Ret_G5| z > 0.6 and not high_vol
        elif abs(ret_g5_z) > 0.6:
            regime = "trend"
        # Rule 3: else chop
        else:
            regime = "chop"
        
        return {
            "regime": regime,
            "z_scores": {
                "atrp": atrp_z,
                "bb_width": bb_width_z,
                "ret_g5": ret_g5_z
            }
        }


def get_regime(signal_vector: List[float], raw_registry: Dict[str, Any], 
               classifier: Optional[RegimeClassifier] = None) -> Dict[str, Any]:
    """
    Get market regime classification.
    
    Args:
        signal_vector: Normalized signal vector
        raw_registry: Raw signal registry
        classifier: Optional RegimeClassifier instance (creates new one if None)
    
    Returns:
        Dictionary with "regime" key
    """
    if classifier is None:
        classifier = RegimeClassifier()
    
    return classifier.classify(signal_vector, raw_registry)

