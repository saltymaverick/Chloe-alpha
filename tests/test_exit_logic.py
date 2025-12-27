"""
Tests for Exit Logic (Module 12 - Unified Exit Decisions)
"""

import pytest
from engine_alpha.loop.exit_logic import should_exit_trade
from engine_alpha.core.confidence_engine import ConfidenceState
from engine_alpha.core.drift_detector import DriftState


class TestExitLogic:
    """Test suite for unified exit logic."""
    
    def test_should_exit_trade_confidence_drop(self):
        """Test exit due to confidence drop below threshold."""
        position = {"side": "long", "entry_confidence": 0.8}
        ctx = {"symbol": "ETHUSDT", "timeframe": "1h"}
        signal_vector = [0.2, 0.1]
        raw_registry = {}
        regime_state = {"primary": "trend_up"}
        drift_state = DriftState(pf_local=1.5, drift_score=0.1, confidence_return_corr=0.3)
        confidence_state = ConfidenceState(
            confidence=0.25,  # Below exit threshold
            components={"flow": 0.3, "volatility": 0.2, "microstructure": 0.2, "cross_asset": 0.2},
            penalties={"regime": 1.0, "drift": 0.9},
        )
        config = {
            "exit_min_confidence": 0.30,
            "max_drift_for_open_positions": 0.7,
            "regime_flip_exit_enabled": True,
        }
        
        result = should_exit_trade(
            position, ctx, signal_vector, raw_registry, regime_state,
            drift_state, confidence_state, config
        )
        
        assert result["exit"] is True
        assert "confidence" in result["reason"].lower()
        assert "dropped" in result["reason"].lower() or "below" in result["reason"].lower()
    
    def test_should_exit_trade_high_drift(self):
        """Test exit due to high drift (safety exit)."""
        position = {"side": "long", "entry_confidence": 0.8}
        ctx = {"symbol": "ETHUSDT", "timeframe": "1h"}
        signal_vector = [0.5, 0.3]
        raw_registry = {}
        regime_state = {"primary": "trend_up"}
        drift_state = DriftState(pf_local=0.7, drift_score=0.85, confidence_return_corr=-0.1)  # High drift
        confidence_state = ConfidenceState(
            confidence=0.7,
            components={"flow": 0.7, "volatility": 0.6, "microstructure": 0.6, "cross_asset": 0.5},
            penalties={"regime": 1.0, "drift": 0.15},
        )
        config = {
            "exit_min_confidence": 0.30,
            "max_drift_for_open_positions": 0.7,  # Threshold
            "regime_flip_exit_enabled": True,
        }
        
        result = should_exit_trade(
            position, ctx, signal_vector, raw_registry, regime_state,
            drift_state, confidence_state, config
        )
        
        assert result["exit"] is True
        assert "drift" in result["reason"].lower() or "safety" in result["reason"].lower()
    
    def test_should_exit_trade_regime_flip(self):
        """Test exit due to regime flip (long position, regime flipped to trend_down)."""
        position = {"side": "long", "entry_confidence": 0.8}
        ctx = {"symbol": "ETHUSDT", "timeframe": "1h"}
        signal_vector = [-0.5, -0.3]  # Negative signals
        raw_registry = {}
        regime_state = {"primary": "trend_down"}  # Flipped against long position
        drift_state = DriftState(pf_local=1.5, drift_score=0.2, confidence_return_corr=0.3)
        confidence_state = ConfidenceState(
            confidence=0.6,
            components={"flow": 0.6, "volatility": 0.5, "microstructure": 0.5, "cross_asset": 0.4},
            penalties={"regime": 1.0, "drift": 0.8},
        )
        config = {
            "exit_min_confidence": 0.30,
            "max_drift_for_open_positions": 0.7,
            "regime_flip_exit_enabled": True,
        }
        
        result = should_exit_trade(
            position, ctx, signal_vector, raw_registry, regime_state,
            drift_state, confidence_state, config
        )
        
        assert result["exit"] is True
        assert "regime" in result["reason"].lower() and "flip" in result["reason"].lower()
    
    def test_should_exit_trade_stable_hold(self):
        """Test no exit when confidence stable and regime favorable."""
        position = {"side": "long", "entry_confidence": 0.8}
        ctx = {"symbol": "ETHUSDT", "timeframe": "1h"}
        signal_vector = [0.5, 0.3]  # Positive signals
        raw_registry = {}
        regime_state = {"primary": "trend_up"}  # Favorable for long
        drift_state = DriftState(pf_local=1.5, drift_score=0.1, confidence_return_corr=0.3)
        confidence_state = ConfidenceState(
            confidence=0.7,  # Above exit threshold
            components={"flow": 0.7, "volatility": 0.6, "microstructure": 0.6, "cross_asset": 0.5},
            penalties={"regime": 1.0, "drift": 0.9},
        )
        config = {
            "exit_min_confidence": 0.30,
            "max_drift_for_open_positions": 0.7,
            "regime_flip_exit_enabled": True,
        }
        
        result = should_exit_trade(
            position, ctx, signal_vector, raw_registry, regime_state,
            drift_state, confidence_state, config
        )
        
        assert result["exit"] is False
        assert "hold" in result["reason"].lower()

