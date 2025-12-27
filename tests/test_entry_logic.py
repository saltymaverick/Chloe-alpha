"""
Tests for Entry Logic (Module 11 - Unified Entry Decisions)
"""

import pytest
from engine_alpha.loop.entry_logic import should_enter_trade
from engine_alpha.core.confidence_engine import ConfidenceState
from engine_alpha.core.drift_detector import DriftState


class TestEntryLogic:
    """Test suite for unified entry logic."""
    
    def test_should_enter_trade_high_confidence_low_drift(self):
        """Test entry with high confidence, low drift, positive size."""
        ctx = {"symbol": "ETHUSDT", "timeframe": "1h"}
        signal_vector = [0.5, 0.3, 0.2]  # Positive signals
        raw_registry = {}
        regime_state = {"primary": "trend_up"}
        drift_state = DriftState(pf_local=1.5, drift_score=0.1, confidence_return_corr=0.3)
        confidence_state = ConfidenceState(
            confidence=0.8,
            components={"flow": 0.8, "volatility": 0.7, "microstructure": 0.6, "cross_asset": 0.5},
            penalties={"regime": 1.0, "drift": 0.9},
        )
        size_multiplier = 1.2
        config = {
            "entry_min_confidence": 0.6,
            "max_drift_for_entries": 0.5,
        }
        
        result = should_enter_trade(
            ctx, signal_vector, raw_registry, regime_state, drift_state,
            confidence_state, size_multiplier, config
        )
        
        assert result["enter"] is True
        assert result["direction"] in ["long", "short"]
        assert result["size_multiplier"] == size_multiplier
        assert "conf=" in result["reason"]
    
    def test_should_enter_trade_low_confidence(self):
        """Test entry rejection due to low confidence."""
        ctx = {"symbol": "ETHUSDT", "timeframe": "1h"}
        signal_vector = [0.5, 0.3]
        raw_registry = {}
        regime_state = {"primary": "trend_up"}
        drift_state = DriftState(pf_local=1.5, drift_score=0.1, confidence_return_corr=0.3)
        confidence_state = ConfidenceState(
            confidence=0.2,  # Below threshold
            components={"flow": 0.2, "volatility": 0.2, "microstructure": 0.2, "cross_asset": 0.2},
            penalties={"regime": 1.0, "drift": 0.9},
        )
        size_multiplier = 1.0
        config = {
            "entry_min_confidence": 0.6,
            "max_drift_for_entries": 0.5,
        }
        
        result = should_enter_trade(
            ctx, signal_vector, raw_registry, regime_state, drift_state,
            confidence_state, size_multiplier, config
        )
        
        assert result["enter"] is False
        assert "conf" in result["reason"].lower()
        assert "threshold" in result["reason"].lower()
    
    def test_should_enter_trade_high_drift(self):
        """Test entry rejection due to high drift."""
        ctx = {"symbol": "ETHUSDT", "timeframe": "1h"}
        signal_vector = [0.5, 0.3]
        raw_registry = {}
        regime_state = {"primary": "trend_up"}
        drift_state = DriftState(pf_local=0.8, drift_score=0.9, confidence_return_corr=-0.2)  # High drift
        confidence_state = ConfidenceState(
            confidence=0.8,
            components={"flow": 0.8, "volatility": 0.7, "microstructure": 0.6, "cross_asset": 0.5},
            penalties={"regime": 1.0, "drift": 0.1},
        )
        size_multiplier = 1.0
        config = {
            "entry_min_confidence": 0.6,
            "max_drift_for_entries": 0.5,  # Threshold
        }
        
        result = should_enter_trade(
            ctx, signal_vector, raw_registry, regime_state, drift_state,
            confidence_state, size_multiplier, config
        )
        
        assert result["enter"] is False
        assert "drift" in result["reason"].lower()
    
    def test_should_enter_trade_zero_size_multiplier(self):
        """Test entry rejection due to zero size multiplier."""
        ctx = {"symbol": "ETHUSDT", "timeframe": "1h"}
        signal_vector = [0.5, 0.3]
        raw_registry = {}
        regime_state = {"primary": "trend_up"}
        drift_state = DriftState(pf_local=1.5, drift_score=0.1, confidence_return_corr=0.3)
        confidence_state = ConfidenceState(
            confidence=0.8,
            components={"flow": 0.8, "volatility": 0.7, "microstructure": 0.6, "cross_asset": 0.5},
            penalties={"regime": 1.0, "drift": 0.9},
        )
        size_multiplier = 0.0  # Zero size
        config = {
            "entry_min_confidence": 0.6,
            "max_drift_for_entries": 0.5,
        }
        
        result = should_enter_trade(
            ctx, signal_vector, raw_registry, regime_state, drift_state,
            confidence_state, size_multiplier, config
        )
        
        assert result["enter"] is False
        assert "size_multiplier" in result["reason"].lower() or "size" in result["reason"].lower()
    
    def test_should_enter_trade_neutral_signals(self):
        """Test entry rejection due to neutral signal direction."""
        ctx = {"symbol": "ETHUSDT", "timeframe": "1h"}
        signal_vector = [0.05, -0.03, 0.02]  # Neutral (sum near 0)
        raw_registry = {}
        regime_state = {"primary": "chop"}
        drift_state = DriftState(pf_local=1.5, drift_score=0.1, confidence_return_corr=0.3)
        confidence_state = ConfidenceState(
            confidence=0.8,
            components={"flow": 0.8, "volatility": 0.7, "microstructure": 0.6, "cross_asset": 0.5},
            penalties={"regime": 1.0, "drift": 0.9},
        )
        size_multiplier = 1.0
        config = {
            "entry_min_confidence": 0.6,
            "max_drift_for_entries": 0.5,
        }
        
        result = should_enter_trade(
            ctx, signal_vector, raw_registry, regime_state, drift_state,
            confidence_state, size_multiplier, config
        )
        
        assert result["enter"] is False
        assert "neutral" in result["reason"].lower() or "direction" in result["reason"].lower()

