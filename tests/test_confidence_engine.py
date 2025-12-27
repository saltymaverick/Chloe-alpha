"""
Tests for Confidence Engine (Module 5 - Flow/Vol/Micro/Cross + Regime + Drift)
"""

import pytest
from typing import Dict, Any

from engine_alpha.core.confidence_engine import (
    compute_confidence,
    ConfidenceState,
    FLOW_WEIGHT,
    VOL_WEIGHT,
    MICRO_WEIGHT,
    CROSS_WEIGHT,
)


def _create_synthetic_raw_registry(
    flow_signals: int = 3,
    vol_signals: int = 2,
    micro_signals: int = 2,
    cross_signals: int = 2,
    flow_conf: float = 0.8,
    vol_conf: float = 0.7,
    micro_conf: float = 0.6,
    cross_conf: float = 0.5,
) -> Dict[str, Dict[str, Any]]:
    """Create a synthetic raw_registry for testing."""
    registry = {}
    
    # Flow signals
    for i in range(flow_signals):
        registry[f"flow_signal_{i}"] = {
            "type": "flow_dict",
            "raw": 0.5 + i * 0.1,
            "z_score": 1.0 + i * 0.2,
            "direction_prob": {"up": 0.6 + i * 0.05, "down": 0.4 - i * 0.05},
            "confidence": flow_conf,
            "drift": 0.1,
        }
    
    # Volatility signals
    for i in range(vol_signals):
        registry[f"vol_signal_{i}"] = {
            "type": "flow_dict",
            "raw": 0.3 + i * 0.1,
            "z_score": 0.8 + i * 0.2,
            "direction_prob": {"up": 0.55 + i * 0.05, "down": 0.45 - i * 0.05},
            "confidence": vol_conf,
            "drift": 0.15,
        }
    
    # Microstructure signals
    for i in range(micro_signals):
        registry[f"micro_signal_{i}"] = {
            "type": "flow_dict",
            "raw": 0.2 + i * 0.1,
            "z_score": 0.6 + i * 0.2,
            "direction_prob": {"up": 0.52 + i * 0.05, "down": 0.48 - i * 0.05},
            "confidence": micro_conf,
            "drift": 0.2,
        }
    
    # Cross-asset signals
    for i in range(cross_signals):
        registry[f"cross_signal_{i}"] = {
            "type": "flow_dict",
            "raw": 0.1 + i * 0.1,
            "z_score": 0.5 + i * 0.2,
            "direction_prob": {"up": 0.51 + i * 0.05, "down": 0.49 - i * 0.05},
            "confidence": cross_conf,
            "drift": 0.25,
        }
    
    return registry


class TestConfidenceEngine:
    """Test suite for new confidence engine."""
    
    def test_compute_confidence_basic(self):
        """Test basic confidence computation."""
        raw_registry = _create_synthetic_raw_registry()
        regime_state = {"primary": "trend_up"}
        drift_state = {"drift_score": 0.0}
        
        result = compute_confidence(raw_registry, regime_state, drift_state)
        
        assert isinstance(result, ConfidenceState)
        assert 0.0 <= result.confidence <= 1.0
        assert "flow" in result.components
        assert "volatility" in result.components
        assert "microstructure" in result.components
        assert "cross_asset" in result.components
        assert "regime" in result.penalties
        assert "drift" in result.penalties
    
    def test_compute_confidence_aligned_signals(self):
        """Test confidence with strong, aligned signals."""
        raw_registry = _create_synthetic_raw_registry(
            flow_conf=0.9,
            vol_conf=0.85,
            micro_conf=0.8,
            cross_conf=0.75,
        )
        regime_state = {"primary": "trend_up"}
        drift_state = {"drift_score": 0.0}
        
        result = compute_confidence(raw_registry, regime_state, drift_state)
        
        # Should have high confidence
        assert result.confidence > 0.7
        assert result.components["flow"] > 0.8
        assert result.penalties["drift"] == 1.0  # No drift penalty
    
    def test_compute_confidence_conflicting_signals(self):
        """Test confidence with conflicting signals."""
        raw_registry = _create_synthetic_raw_registry(
            flow_conf=0.9,
            vol_conf=0.3,  # Low vol confidence
            micro_conf=0.4,
            cross_conf=0.2,  # Low cross confidence
        )
        regime_state = {"primary": "trend_up"}
        drift_state = {"drift_score": 0.0}
        
        result = compute_confidence(raw_registry, regime_state, drift_state)
        
        # Should have lower confidence due to conflicting signals
        assert result.confidence < 0.7
        assert result.components["flow"] > result.components["volatility"]
    
    def test_compute_confidence_high_drift(self):
        """Test confidence with high drift."""
        raw_registry = _create_synthetic_raw_registry(
            flow_conf=0.9,
            vol_conf=0.85,
        )
        regime_state = {"primary": "trend_up"}
        drift_state = {"drift_score": 0.8}  # High drift
        
        result = compute_confidence(raw_registry, regime_state, drift_state)
        
        # Drift penalty should reduce confidence
        assert result.penalties["drift"] < 0.5
        assert result.confidence < 0.5  # Should be significantly reduced
    
    def test_compute_confidence_low_drift(self):
        """Test confidence with low drift."""
        raw_registry = _create_synthetic_raw_registry(
            flow_conf=0.9,
            vol_conf=0.85,
        )
        regime_state = {"primary": "trend_up"}
        drift_state = {"drift_score": 0.1}  # Low drift
        
        result_low_drift = compute_confidence(raw_registry, regime_state, drift_state)
        
        # Compare with high drift case
        drift_state_high = {"drift_score": 0.8}
        result_high_drift = compute_confidence(raw_registry, regime_state, drift_state_high)
        
        assert result_low_drift.confidence > result_high_drift.confidence
        assert result_low_drift.penalties["drift"] > result_high_drift.penalties["drift"]
    
    def test_compute_confidence_chop_regime(self):
        """Test confidence in CHOP regime."""
        raw_registry = _create_synthetic_raw_registry(
            flow_conf=0.9,
            vol_conf=0.85,
        )
        regime_state = {"primary": "chop"}
        drift_state = {"drift_score": 0.0}
        
        result = compute_confidence(raw_registry, regime_state, drift_state)
        
        # CHOP regime should apply penalty
        assert result.penalties["regime"] < 1.0
        assert result.penalties["regime"] >= 0.7  # At least 0.7 penalty in CHOP
    
    def test_compute_confidence_trend_regime(self):
        """Test confidence in trend regime."""
        raw_registry = _create_synthetic_raw_registry(
            flow_conf=0.9,
            vol_conf=0.85,
        )
        regime_state = {"primary": "trend_up"}
        drift_state = {"drift_score": 0.0}
        
        result = compute_confidence(raw_registry, regime_state, drift_state)
        
        # Trend regime should have minimal penalty
        assert result.penalties["regime"] == 1.0
    
    def test_compute_confidence_empty_registry(self):
        """Test confidence with empty registry."""
        raw_registry = {}
        regime_state = {"primary": "trend_up"}
        drift_state = {"drift_score": 0.0}
        
        result = compute_confidence(raw_registry, regime_state, drift_state)
        
        # Should return zero confidence
        assert result.confidence == 0.0
        assert all(comp == 0.0 for comp in result.components.values())
    
    def test_compute_confidence_component_weights(self):
        """Test that component weights are applied correctly."""
        # Create registry with only flow signals (highest weight)
        raw_registry = _create_synthetic_raw_registry(
            flow_signals=5,
            vol_signals=0,
            micro_signals=0,
            cross_signals=0,
            flow_conf=0.9,
        )
        regime_state = {"primary": "trend_up"}
        drift_state = {"drift_score": 0.0}
        
        result = compute_confidence(raw_registry, regime_state, drift_state)
        
        # Flow component should dominate
        assert result.components["flow"] > 0.8
        assert result.components["volatility"] == 0.0
        assert result.components["microstructure"] == 0.0
        assert result.components["cross_asset"] == 0.0

