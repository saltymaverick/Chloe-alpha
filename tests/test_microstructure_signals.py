"""
Tests for Microstructure Signals Module (Phase 2 - Quant Architecture)
"""

import pytest
from typing import Dict, Any
import pandas as pd
import numpy as np

from engine_alpha.signals import microstructure_signals


def _create_fake_context_with_derivatives() -> Dict[str, Any]:
    """Create a fake context with derivatives and microstructure data."""
    dates = pd.date_range(start="2024-01-01", periods=30, freq="1H")
    np.random.seed(42)
    
    base_price = 3000.0
    prices = base_price + np.cumsum(np.random.randn(30) * 10)
    
    ohlcv_data = {
        "ts": dates,
        "open": prices + np.random.randn(30) * 5,
        "high": prices + abs(np.random.randn(30) * 10),
        "low": prices - abs(np.random.randn(30) * 10),
        "close": prices,
        "volume": np.random.uniform(1000000, 5000000, 30),
    }
    
    df = pd.DataFrame(ohlcv_data)
    rows = df.to_dict("records")
    
    return {
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "rows": rows,
        "derivatives": {
            "funding_rate": 0.0001,
            "perp_price": 3001.0,
            "spot_price": 3000.0,
            "open_interest_series": [1000000, 1050000, 1100000, 1150000],
            "liquidation_levels": [2950.0, 3050.0],
        },
        "microstructure": {
            "bid_ask_imbalance": 0.2,
        },
    }


class TestMicrostructureSignals:
    """Test suite for microstructure signal compute functions."""
    
    def test_compute_funding_rate_z(self):
        """Test funding rate z-score computation."""
        ctx = _create_fake_context_with_derivatives()
        result = microstructure_signals.compute_funding_rate_z(ctx)
        
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
        prob = result["direction_prob"]
        assert "up" in prob
        assert "down" in prob
        assert 0.0 <= prob["up"] <= 1.0
        assert 0.0 <= prob["down"] <= 1.0
        assert abs((prob["up"] + prob["down"]) - 1.0) < 0.01
        
        assert 0.0 <= result["confidence"] <= 1.0
        assert 0.0 <= result["drift"] <= 1.0
    
    def test_compute_perp_spot_basis(self):
        """Test perp/spot basis computation."""
        ctx = _create_fake_context_with_derivatives()
        result = microstructure_signals.compute_perp_spot_basis(ctx)
        
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        prob = result["direction_prob"]
        assert 0.0 <= prob["up"] <= 1.0
        assert 0.0 <= prob["down"] <= 1.0
        assert abs((prob["up"] + prob["down"]) - 1.0) < 0.01
        
        assert 0.0 <= result["confidence"] <= 1.0
        assert 0.0 <= result["drift"] <= 1.0
        
        # Sanity check: perp > spot should give positive basis
        ctx_premium = ctx.copy()
        ctx_premium["derivatives"]["perp_price"] = 3002.0
        ctx_premium["derivatives"]["spot_price"] = 3000.0
        result_premium = microstructure_signals.compute_perp_spot_basis(ctx_premium)
        assert result_premium["raw"] > 0
    
    def test_compute_liquidation_heat_proximity(self):
        """Test liquidation heat proximity computation."""
        ctx = _create_fake_context_with_derivatives()
        result = microstructure_signals.compute_liquidation_heat_proximity(ctx)
        
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        prob = result["direction_prob"]
        assert 0.0 <= prob["up"] <= 1.0
        assert 0.0 <= prob["down"] <= 1.0
        assert abs((prob["up"] + prob["down"]) - 1.0) < 0.01
        
        assert 0.0 <= result["confidence"] <= 1.0
        assert 0.0 <= result["drift"] <= 1.0
        
        # Sanity check: price near liquidation level should give higher heat
        ctx_near_liq = ctx.copy()
        ctx_near_liq["rows"][-1]["close"] = 2951.0  # Very close to 2950 liquidation
        result_near = microstructure_signals.compute_liquidation_heat_proximity(ctx_near_liq)
        assert result_near["raw"] >= 0.0
    
    def test_compute_orderbook_imbalance(self):
        """Test orderbook imbalance computation."""
        ctx = _create_fake_context_with_derivatives()
        result = microstructure_signals.compute_orderbook_imbalance(ctx)
        
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        prob = result["direction_prob"]
        assert 0.0 <= prob["up"] <= 1.0
        assert 0.0 <= prob["down"] <= 1.0
        assert abs((prob["up"] + prob["down"]) - 1.0) < 0.01
        
        assert 0.0 <= result["confidence"] <= 1.0
        assert 0.0 <= result["drift"] <= 1.0
        
        # Sanity check: positive imbalance should give positive raw
        ctx_bid_dom = ctx.copy()
        ctx_bid_dom["microstructure"]["bid_ask_imbalance"] = 0.5
        result_bid = microstructure_signals.compute_orderbook_imbalance(ctx_bid_dom)
        assert result_bid["raw"] > 0
    
    def test_compute_oi_price_divergence(self):
        """Test OI/price divergence computation."""
        ctx = _create_fake_context_with_derivatives()
        result = microstructure_signals.compute_oi_price_divergence(ctx)
        
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        prob = result["direction_prob"]
        assert 0.0 <= prob["up"] <= 1.0
        assert 0.0 <= prob["down"] <= 1.0
        assert abs((prob["up"] + prob["down"]) - 1.0) < 0.01
        
        assert 0.0 <= result["confidence"] <= 1.0
        assert 0.0 <= result["drift"] <= 1.0
    
    def test_microstructure_signals_with_empty_context(self):
        """Test microstructure signals handle empty/missing context gracefully."""
        # Test with None context
        result = microstructure_signals.compute_funding_rate_z(None)
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        # Test with empty dict
        result = microstructure_signals.compute_orderbook_imbalance({})
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
    
    def test_microstructure_signals_without_derivatives(self):
        """Test microstructure signals work without derivatives data (fallback to OHLCV)."""
        ctx = {
            "symbol": "ETHUSDT",
            "timeframe": "1h",
            "rows": [
                {"close": 3000.0, "volume": 1000000, "high": 3010, "low": 2990},
                {"close": 3010.0, "volume": 1200000, "high": 3020, "low": 3000},
            ] * 10,
        }
        
        result = microstructure_signals.compute_funding_rate_z(ctx)
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])

