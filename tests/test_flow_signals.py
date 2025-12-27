"""
Tests for Flow Signals Module (Phase 2 - Quant Architecture)
"""

import pytest
from typing import Dict, Any
import pandas as pd
import numpy as np

from engine_alpha.signals import flow_signals


def _create_fake_context() -> Dict[str, Any]:
    """Create a minimal fake context for testing."""
    # Create a small OHLCV dataframe
    dates = pd.date_range(start="2024-01-01", periods=20, freq="1H")
    np.random.seed(42)
    
    base_price = 3000.0
    prices = base_price + np.cumsum(np.random.randn(20) * 10)
    
    ohlcv_data = {
        "ts": dates,
        "open": prices + np.random.randn(20) * 5,
        "high": prices + abs(np.random.randn(20) * 10),
        "low": prices - abs(np.random.randn(20) * 10),
        "close": prices,
        "volume": np.random.uniform(1000000, 5000000, 20),
    }
    
    df = pd.DataFrame(ohlcv_data)
    rows = df.to_dict("records")
    
    return {
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "rows": rows,
    }


class TestFlowSignals:
    """Test suite for flow signal compute functions."""
    
    def test_compute_whale_accumulation_velocity(self):
        """Test whale accumulation velocity computation."""
        ctx = _create_fake_context()
        result = flow_signals.compute_whale_accumulation_velocity(ctx)
        
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
        assert abs((prob_up + prob_down) - 1.0) < 0.01  # Sum should be ~1
        
        # Check confidence is in [0, 1]
        assert 0.0 <= result["confidence"] <= 1.0
        
        # Check drift is in [0, 1]
        assert 0.0 <= result["drift"] <= 1.0
    
    def test_compute_net_exchange_inflow(self):
        """Test net exchange inflow computation."""
        ctx = _create_fake_context()
        result = flow_signals.compute_net_exchange_inflow(ctx)
        
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        prob = result["direction_prob"]
        assert 0.0 <= prob["up"] <= 1.0
        assert 0.0 <= prob["down"] <= 1.0
        assert abs((prob["up"] + prob["down"]) - 1.0) < 0.01
        
        assert 0.0 <= result["confidence"] <= 1.0
        assert 0.0 <= result["drift"] <= 1.0
    
    def test_compute_exchange_reserve_delta(self):
        """Test exchange reserve delta computation."""
        ctx = _create_fake_context()
        result = flow_signals.compute_exchange_reserve_delta(ctx)
        
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        prob = result["direction_prob"]
        assert 0.0 <= prob["up"] <= 1.0
        assert 0.0 <= prob["down"] <= 1.0
        assert abs((prob["up"] + prob["down"]) - 1.0) < 0.01
        
        assert 0.0 <= result["confidence"] <= 1.0
        assert 0.0 <= result["drift"] <= 1.0
    
    def test_compute_perp_oi_trend(self):
        """Test perpetual OI trend computation."""
        ctx = _create_fake_context()
        result = flow_signals.compute_perp_oi_trend(ctx)
        
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        prob = result["direction_prob"]
        assert 0.0 <= prob["up"] <= 1.0
        assert 0.0 <= prob["down"] <= 1.0
        assert abs((prob["up"] + prob["down"]) - 1.0) < 0.01
        
        assert 0.0 <= result["confidence"] <= 1.0
        assert 0.0 <= result["drift"] <= 1.0
    
    def test_compute_cvd_spot_vs_perp(self):
        """Test CVD spot vs perp divergence computation."""
        ctx = _create_fake_context()
        result = flow_signals.compute_cvd_spot_vs_perp(ctx)
        
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        prob = result["direction_prob"]
        assert 0.0 <= prob["up"] <= 1.0
        assert 0.0 <= prob["down"] <= 1.0
        assert abs((prob["up"] + prob["down"]) - 1.0) < 0.01
        
        assert 0.0 <= result["confidence"] <= 1.0
        assert 0.0 <= result["drift"] <= 1.0
    
    def test_compute_large_wallet_bid_ask_dominance(self):
        """Test large wallet bid-ask dominance computation."""
        ctx = _create_fake_context()
        result = flow_signals.compute_large_wallet_bid_ask_dominance(ctx)
        
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        prob = result["direction_prob"]
        assert 0.0 <= prob["up"] <= 1.0
        assert 0.0 <= prob["down"] <= 1.0
        assert abs((prob["up"] + prob["down"]) - 1.0) < 0.01
        
        assert 0.0 <= result["confidence"] <= 1.0
        assert 0.0 <= result["drift"] <= 1.0
    
    def test_flow_signals_with_empty_context(self):
        """Test flow signals handle empty/missing context gracefully."""
        # Test with None context
        result = flow_signals.compute_whale_accumulation_velocity(None)
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        # Test with empty dict
        result = flow_signals.compute_net_exchange_inflow({})
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
    
    def test_flow_signals_with_minimal_rows(self):
        """Test flow signals handle minimal OHLCV data."""
        ctx = {
            "symbol": "ETHUSDT",
            "timeframe": "1h",
            "rows": [
                {"close": 3000.0, "volume": 1000000, "high": 3010, "low": 2990},
            ],
        }
        
        result = flow_signals.compute_whale_accumulation_velocity(ctx)
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])

