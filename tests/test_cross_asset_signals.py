"""
Tests for Cross-Asset Signals Module (Phase 2 - Quant Architecture)
"""

import pytest
from typing import Dict, Any
import pandas as pd
import numpy as np

from engine_alpha.signals import cross_asset_signals


def _create_fake_context_with_cross_asset() -> Dict[str, Any]:
    """Create a fake context with cross-asset data."""
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
        "cross_asset": {
            "BTCUSDT": {
                "vol": 0.02,
                "vol_prev": 0.018,
                "return": 0.01,
                "returns": 0.01,
            },
            "ETHUSDT": {
                "vol": 0.015,
                "vol_prev": 0.014,
                "return": 0.008,
                "returns": 0.008,
            },
            "SOLUSDT": {
                "return": 0.015,
                "returns": 0.015,
            },
            "AVAXUSDT": {
                "return": 0.005,
                "returns": 0.005,
            },
            "LINKUSDT": {
                "return": 0.012,
                "returns": 0.012,
            },
            "STABLE": {
                "supply_delta": 1000000000,  # 1B inflow
                "flow": 1000000000,
            },
        },
    }


class TestCrossAssetSignals:
    """Test suite for cross-asset signal compute functions."""
    
    def test_compute_btc_eth_vol_lead_lag(self):
        """Test BTC/ETH volatility lead-lag computation."""
        ctx = _create_fake_context_with_cross_asset()
        result = cross_asset_signals.compute_btc_eth_vol_lead_lag(ctx)
        
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
    
    def test_compute_sol_l1_rotation_score(self):
        """Test SOL vs L1 rotation score computation."""
        ctx = _create_fake_context_with_cross_asset()
        result = cross_asset_signals.compute_sol_l1_rotation_score(ctx)
        
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        prob = result["direction_prob"]
        assert 0.0 <= prob["up"] <= 1.0
        assert 0.0 <= prob["down"] <= 1.0
        assert abs((prob["up"] + prob["down"]) - 1.0) < 0.01
        
        assert 0.0 <= result["confidence"] <= 1.0
        assert 0.0 <= result["drift"] <= 1.0
        
        # Sanity check: SOL outperforming should give positive score
        ctx_sol_strong = ctx.copy()
        ctx_sol_strong["cross_asset"]["SOLUSDT"]["return"] = 0.02
        ctx_sol_strong["cross_asset"]["ETHUSDT"]["return"] = 0.005
        result_strong = cross_asset_signals.compute_sol_l1_rotation_score(ctx_sol_strong)
        assert result_strong["raw"] > 0
    
    def test_compute_eth_ecosystem_momentum(self):
        """Test ETH ecosystem momentum computation."""
        ctx = _create_fake_context_with_cross_asset()
        result = cross_asset_signals.compute_eth_ecosystem_momentum(ctx)
        
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        prob = result["direction_prob"]
        assert 0.0 <= prob["up"] <= 1.0
        assert 0.0 <= prob["down"] <= 1.0
        assert abs((prob["up"] + prob["down"]) - 1.0) < 0.01
        
        assert 0.0 <= result["confidence"] <= 1.0
        assert 0.0 <= result["drift"] <= 1.0
    
    def test_compute_stablecoin_flow_pressure(self):
        """Test stablecoin flow pressure computation."""
        ctx = _create_fake_context_with_cross_asset()
        result = cross_asset_signals.compute_stablecoin_flow_pressure(ctx)
        
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        prob = result["direction_prob"]
        assert 0.0 <= prob["up"] <= 1.0
        assert 0.0 <= prob["down"] <= 1.0
        assert abs((prob["up"] + prob["down"]) - 1.0) < 0.01
        
        assert 0.0 <= result["confidence"] <= 1.0
        assert 0.0 <= result["drift"] <= 1.0
        
        # Sanity check: positive supply delta should give positive pressure
        ctx_inflow = ctx.copy()
        ctx_inflow["cross_asset"]["STABLE"]["supply_delta"] = 2000000000
        result_inflow = cross_asset_signals.compute_stablecoin_flow_pressure(ctx_inflow)
        assert result_inflow["raw"] > 0
    
    def test_compute_sector_risk_score(self):
        """Test sector risk score computation."""
        ctx = _create_fake_context_with_cross_asset()
        result = cross_asset_signals.compute_sector_risk_score(ctx)
        
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        prob = result["direction_prob"]
        assert 0.0 <= prob["up"] <= 1.0
        assert 0.0 <= prob["down"] <= 1.0
        assert abs((prob["up"] + prob["down"]) - 1.0) < 0.01
        
        assert 0.0 <= result["confidence"] <= 1.0
        assert 0.0 <= result["drift"] <= 1.0
        
        # Sanity check: risk score should be in [0, 1]
        assert 0.0 <= result["raw"] <= 1.0
    
    def test_cross_asset_signals_with_empty_context(self):
        """Test cross-asset signals handle empty/missing context gracefully."""
        # Test with None context
        result = cross_asset_signals.compute_btc_eth_vol_lead_lag(None)
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
        
        # Test with empty dict
        result = cross_asset_signals.compute_sol_l1_rotation_score({})
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])
    
    def test_cross_asset_signals_without_cross_asset_data(self):
        """Test cross-asset signals work without cross_asset data (fallback to OHLCV)."""
        ctx = {
            "symbol": "ETHUSDT",
            "timeframe": "1h",
            "rows": [
                {"close": 3000.0, "volume": 1000000, "high": 3010, "low": 2990},
                {"close": 3010.0, "volume": 1200000, "high": 3020, "low": 3000},
            ] * 15,
        }
        
        result = cross_asset_signals.compute_btc_eth_vol_lead_lag(ctx)
        assert isinstance(result, dict)
        assert all(key in result for key in ["raw", "z_score", "direction_prob", "confidence", "drift"])

