"""
Tests for Volatility Signals Module (Phase 2 - Quant Architecture)
"""

import pytest
from typing import Dict, Any
import pandas as pd
import numpy as np

from engine_alpha.signals import vol_signals


def _create_fake_context() -> Dict[str, Any]:
    """Create a minimal fake context for testing."""
    # Create a small OHLCV dataframe with varying volatility
    dates = pd.date_range(start="2024-01-01", periods=50, freq="1H")
    np.random.seed(42)
    
    base_price = 3000.0
    
    # Create two regimes: low vol then high vol
    low_vol_returns = np.random.randn(25) * 5  # Small moves
    high_vol_returns = np.random.randn(25) * 20  # Large moves
    
    all_returns = np.concatenate([low_vol_returns, high_vol_returns])
    prices = base_price + np.cumsum(all_returns)
    
    ohlcv_data = {
        "ts": dates,
        "open": prices + np.random.randn(50) * 2,
        "high": prices + abs(np.random.randn(50) * 10),
        "low": prices - abs(np.random.randn(50) * 10),
        "close": prices,
        "volume": np.random.uniform(1000000, 5000000, 50),
    }
    
    df = pd.DataFrame(ohlcv_data)
    rows = df.to_dict("records")
    
    return {
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "rows": rows,
    }


class TestVolSignals:
    """Test suite for volatility signal compute functions."""
    
    def test_compute_vol_compression_percentile(self):
        """Test volatility compression percentile computation."""
        ctx = _create_fake_context()
        result = vol_signals.compute_vol_compression_percentile(ctx)
        
        # Check structure
        assert isinstance(result, dict)
        assert "raw" in result
        assert "z_score" in result
        assert "direction_prob" in result
        assert "confidence" in result
        assert "drift" in result
        
        # Check types
        assert isinstance(result["raw"], (int, float))
        assert isinstance(result["z_score"], (int, float))
        assert isinstance(result["confidence"], (int, float))
        assert isinstance(result["drift"], (int, float))
        
        # Check direction_prob structure
        assert isinstance(result["direction_prob"], dict)
        assert "up" in result["direction_prob"]
        assert "down" in result["direction_prob"]
        
        # Check probabilities are valid
        prob_up = result["direction_prob"]["up"]
        prob_down = result["direction_prob"]["down"]
        assert 0.0 <= prob_up <= 1.0
        assert 0.0 <= prob_down <= 1.0
        assert abs((prob_up + prob_down) - 1.0) < 0.01
        
        # Check confidence is in [0, 1]
        assert 0.0 <= result["confidence"] <= 1.0
        
        # Check drift is in [0, 1]
        assert 0.0 <= result["drift"] <= 1.0
        
        # Sanity check: compression should be higher in low-vol sections
        low_vol_ctx = {
            "symbol": "ETHUSDT",
            "timeframe": "1h",
            "rows": [{"close": 3000.0 + i * 0.1, "high": 3001, "low": 2999, "volume": 1000000} 
                    for i in range(30)],
        }
        high_vol_ctx = {
            "symbol": "ETHUSDT",
            "timeframe": "1h",
            "rows": [{"close": 3000.0 + i * 10, "high": 3010, "low": 2990, "volume": 1000000} 
                    for i in range(30)],
        }
        
        low_vol_result = vol_signals.compute_vol_compression_percentile(low_vol_ctx)
        high_vol_result = vol_signals.compute_vol_compression_percentile(high_vol_ctx)
        
        # Low vol should have higher compression percentile
        assert low_vol_result["raw"] >= high_vol_result["raw"] - 0.2  # Allow some tolerance
    
    def test_compute_vol_expansion_probability(self):
        """Test volatility expansion probability computation."""
        ctx = _create_fake_context()
        result = vol_signals.compute_vol_expansion_probability(ctx)
        
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        prob = result["direction_prob"]
        assert 0.0 <= prob["up"] <= 1.0
        assert 0.0 <= prob["down"] <= 1.0
        assert abs((prob["up"] + prob["down"]) - 1.0) < 0.01
        
        assert 0.0 <= result["confidence"] <= 1.0
        assert 0.0 <= result["drift"] <= 1.0
    
    def test_compute_regime_transition_heat(self):
        """Test regime transition heat computation."""
        ctx = _create_fake_context()
        result = vol_signals.compute_regime_transition_heat(ctx)
        
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        prob = result["direction_prob"]
        assert 0.0 <= prob["up"] <= 1.0
        assert 0.0 <= prob["down"] <= 1.0
        assert abs((prob["up"] + prob["down"]) - 1.0) < 0.01
        
        assert 0.0 <= result["confidence"] <= 1.0
        assert 0.0 <= result["drift"] <= 1.0
    
    def test_compute_vol_clustering_score(self):
        """Test volatility clustering score computation."""
        ctx = _create_fake_context()
        result = vol_signals.compute_vol_clustering_score(ctx)
        
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        prob = result["direction_prob"]
        assert 0.0 <= prob["up"] <= 1.0
        assert 0.0 <= prob["down"] <= 1.0
        assert abs((prob["up"] + prob["down"]) - 1.0) < 0.01
        
        assert 0.0 <= result["confidence"] <= 1.0
        assert 0.0 <= result["drift"] <= 1.0
    
    def test_compute_realized_vs_implied_gap(self):
        """Test realized vs implied volatility gap computation."""
        ctx = _create_fake_context()
        result = vol_signals.compute_realized_vs_implied_gap(ctx)
        
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        prob = result["direction_prob"]
        assert 0.0 <= prob["up"] <= 1.0
        assert 0.0 <= prob["down"] <= 1.0
        assert abs((prob["up"] + prob["down"]) - 1.0) < 0.01
        
        assert 0.0 <= result["confidence"] <= 1.0
        assert 0.0 <= result["drift"] <= 1.0
    
    def test_vol_signals_with_empty_context(self):
        """Test volatility signals handle empty/missing context gracefully."""
        # Test with None context
        result = vol_signals.compute_vol_compression_percentile(None)
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        # Test with empty dict
        result = vol_signals.compute_vol_expansion_probability({})
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
    
    def test_vol_signals_with_minimal_rows(self):
        """Test volatility signals handle minimal OHLCV data."""
        ctx = {
            "symbol": "ETHUSDT",
            "timeframe": "1h",
            "rows": [
                {"close": 3000.0, "volume": 1000000, "high": 3010, "low": 2990},
            ],
        }
        
        result = vol_signals.compute_vol_compression_percentile(ctx)
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])

