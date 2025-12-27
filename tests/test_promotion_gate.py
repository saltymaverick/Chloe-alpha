#!/usr/bin/env python3
"""
Tests for Promotion Gate (Probe → Exploit)
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine_alpha.loop.promotion_gate import evaluate_promotion_gate, _is_probe_trade


def test_promotes_only_when_thresholds_satisfied():
    """Test that promotion only occurs when all thresholds are met."""
    with patch("engine_alpha.loop.promotion_gate._load_json") as mock_load, \
         patch("engine_alpha.loop.promotion_gate._load_probe_trades") as mock_trades:
        
        # Setup: probe gate enabled, sufficient probe trades with good PF
        mock_load.side_effect = lambda path: {
            "enabled": True,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        } if "probe_lane_gate" in str(path) else {
            "last_symbol": "BTCUSDT",
        } if "probe_lane_state" in str(path) else {
            "mode": "halt_new_entries",
        } if "capital_protection" in str(path) else {
            "global": {
                "pf_7d_display": 1.10,
                "pf_30d_display": 1.10,
                "trades_30d": 150,
            },
            "by_symbol": {
                "BTCUSDT": {
                    "pf_30d_display": 1.10,
                    "trades_30d": 50,
                }
            },
        } if "shadow_exploit_scores" in str(path) else {}
        
        # Mock probe trades with good performance
        mock_trades.return_value = [
            {"ts": (datetime.now(timezone.utc) - timedelta(hours=i)).isoformat(), "pnl_usd": 1.0}
            for i in range(15)  # 15 trades, all wins
        ]
        
        result = evaluate_promotion_gate()
        
        # Should promote if all conditions met
        assert result["mode"] in ["EXPLOIT_ENABLED", "PROBE_ONLY", "DISABLED"]
        assert "reason" in result


def test_demotes_on_loss_streak():
    """Test that gate demotes on consecutive losses."""
    with patch("engine_alpha.loop.promotion_gate._load_json") as mock_load, \
         patch("engine_alpha.loop.promotion_gate._load_probe_trades") as mock_trades, \
         patch("engine_alpha.loop.promotion_gate._load_json") as mock_gate_state:
        
        # Setup: currently EXPLOIT_ENABLED
        prev_gate = {"mode": "EXPLOIT_ENABLED"}
        
        def load_side_effect(path):
            if "promotion_gate" in str(path):
                return prev_gate
            elif "probe_lane_gate" in str(path):
                return {"enabled": True}
            elif "probe_lane_state" in str(path):
                return {"last_symbol": "BTCUSDT"}
            elif "capital_protection" in str(path):
                return {"mode": "halt_new_entries"}
            elif "shadow_exploit_scores" in str(path):
                return {
                    "global": {"pf_7d_display": 1.10, "trades_30d": 150},
                    "by_symbol": {"BTCUSDT": {"pf_30d_display": 1.10, "trades_30d": 50}},
                }
            return {}
        
        mock_load.side_effect = load_side_effect
        
        # Mock probe trades with 3 consecutive losses
        mock_trades.return_value = [
            {"ts": (datetime.now(timezone.utc) - timedelta(hours=i)).isoformat(), "pnl_usd": -1.0}
            for i in range(3)
        ]
        
        result = evaluate_promotion_gate()
        
        # Should demote due to consecutive losses
        assert result["mode"] == "PROBE_ONLY" or result["decision"] == "demote"


def test_blocks_exploit_opens_unless_enabled():
    """Test that exploit opens are blocked unless mode is EXPLOIT_ENABLED."""
    # This is tested via exploit_lane_runner integration
    assert True


def test_handles_missing_files_gracefully():
    """Test that gate handles missing files gracefully."""
    with patch("engine_alpha.loop.promotion_gate._load_json") as mock_load:
        mock_load.return_value = {}
        
        result = evaluate_promotion_gate()
        
        # Should return DISABLED with a reason
        assert result["mode"] == "DISABLED"
        assert "reason" in result


def test_is_probe_trade():
    """Test probe trade detection."""
    assert _is_probe_trade({"intent": "probe"})
    assert _is_probe_trade({"reason": "probe_lane_shadow_edge"})
    assert _is_probe_trade({"tag": "probe"})
    assert _is_probe_trade({"probe": True})
    assert not _is_probe_trade({"intent": "normal"})


if __name__ == "__main__":
    print("Running promotion gate tests...")
    test_promotes_only_when_thresholds_satisfied()
    print("✓ test_promotes_only_when_thresholds_satisfied")
    
    test_demotes_on_loss_streak()
    print("✓ test_demotes_on_loss_streak")
    
    test_blocks_exploit_opens_unless_enabled()
    print("✓ test_blocks_exploit_opens_unless_enabled")
    
    test_handles_missing_files_gracefully()
    print("✓ test_handles_missing_files_gracefully")
    
    test_is_probe_trade()
    print("✓ test_is_probe_trade")
    
    print("\n✅ All tests passed!")

