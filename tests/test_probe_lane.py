#!/usr/bin/env python3
"""
Tests for Probe Lane (Micro-Live Exploration During Halt)
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine_alpha.loop.probe_lane import run_probe_lane, _load_config, _check_trade_frequency


def test_probe_disabled_when_config_disabled():
    """Test that probe does nothing when disabled."""
    with patch("engine_alpha.loop.probe_lane._load_config") as mock_config, \
         patch("engine_alpha.loop.probe_lane._load_json") as mock_load:
        mock_config.return_value = {"enabled": False}
        # Gate state is what actually determines if probe is enabled
        mock_load.return_value = {"enabled": False, "reason": "probe_lane_disabled"}
        
        result = run_probe_lane()
        
        assert result["action"] == "disabled"
        assert "gate_disabled" in result["reason"] or "disabled" in result["reason"]


def test_probe_blocks_when_capital_mode_not_allowed():
    """Test that probe blocks when capital_mode != halt_new_entries."""
    with patch("engine_alpha.loop.probe_lane._load_config") as mock_config, \
         patch("engine_alpha.loop.probe_lane._load_json") as mock_load:
        
        mock_config.return_value = {
            "enabled": True,
            "allowed_in_capital_modes": ["halt_new_entries"],
        }
        
        def load_side_effect(path):
            path_str = str(path)
            # The gate file is probe_lane_gate.json
            if "probe_lane_gate" in path_str:
                return {"enabled": True, "reason": "test"}  # Gate is enabled
            if "capital_protection" in path_str:
                return {"mode": "normal"}  # Not in allowed list
            return {}
        
        mock_load.side_effect = load_side_effect
        
        result = run_probe_lane()
        
        assert result["action"] == "blocked"
        assert "capital_mode_not_allowed" in result["reason"]


def test_probe_blocks_when_open_position_exists():
    """Test that probe blocks when an open position exists."""
    with patch("engine_alpha.loop.probe_lane._load_config") as mock_config, \
         patch("engine_alpha.loop.probe_lane._load_json") as mock_load, \
         patch("engine_alpha.loop.probe_lane.get_open_positions") as mock_positions:
        
        mock_config.return_value = {
            "enabled": True,
            "allowed_in_capital_modes": ["halt_new_entries"],
            "max_open_positions_total": 1,
        }
        
        def load_side_effect(path):
            path_str = str(path)
            # The gate file is probe_lane_gate.json
            if "probe_lane_gate" in path_str:
                return {"enabled": True, "reason": "test"}  # Gate is enabled
            if "capital_protection" in path_str:
                return {"mode": "halt_new_entries"}
            return {}
        
        mock_load.side_effect = load_side_effect
        mock_positions.return_value = {"SYMBOL": {"dir": 1}}  # One open position
        
        result = run_probe_lane()
        
        assert result["action"] == "blocked"
        assert "open_position" in result["reason"] or "position" in result["reason"]


def test_probe_blocks_when_quarantined_symbol_is_best():
    """Test that probe blocks when quarantined symbol is best candidate."""
    with patch("engine_alpha.loop.probe_lane._load_config") as mock_config, \
         patch("engine_alpha.loop.probe_lane._load_json") as mock_load, \
         patch("engine_alpha.loop.probe_lane.get_open_positions") as mock_positions, \
         patch("engine_alpha.loop.probe_lane._load_state") as mock_state:
        
        mock_config.return_value = {
            "enabled": True,
            "allowed_in_capital_modes": ["halt_new_entries"],
            "max_open_positions_total": 1,
            "require_not_quarantined": True,
            "min_shadow_trades": 30,
            "min_shadow_pf_30d": 1.05,
            "min_shadow_pf_7d": 1.03,
        }
        
        def load_side_effect(path):
            path_str = str(path)
            # The gate file is probe_lane_gate.json
            if "probe_lane_gate" in path_str:
                return {"enabled": True, "reason": "test"}  # Gate is enabled
            if "capital_protection" in path_str:
                return {"mode": "halt_new_entries"}
            elif "quarantine" in path_str:
                return {"blocked_symbols": ["ATOMUSDT"]}
            elif "shadow_exploit_scores" in path_str:
                return {
                    "by_symbol": {
                        "ATOMUSDT": {
                            "trades_30d": 50,
                            "pf_30d_display": 1.10,
                            "pf_7d_display": 1.05,
                        }
                    }
                }
            return {}
        
        mock_load.side_effect = load_side_effect
        mock_positions.return_value = {}
        mock_state.return_value = {"last_trade_at": None, "losses_24h": []}
        
        result = run_probe_lane()
        
        # Should be blocked because only candidate is quarantined
        assert result["action"] == "blocked"
        assert "no_eligible" in result["reason"] or "quarantine" in result["reason"].lower() or result["reason"] == "no_eligible_symbols"


def test_probe_respects_max_trades_per_day():
    """Test that probe respects max_trades_per_day constraint."""
    now = datetime.now(timezone.utc)
    today_ts = now.isoformat()
    
    state = {
        "last_trade_at": today_ts,  # Already traded today
        "losses_24h": [],
    }
    
    config = {
        "max_trades_per_day": 1,
        "cooldown_hours_after_loss": 12,
        "disable_after_losses_24h": 2,
    }
    
    can_trade, reason = _check_trade_frequency(state, config, now)
    
    assert not can_trade
    assert reason == "max_trades_per_day"


def test_probe_respects_cooldown():
    """Test that probe respects cooldown after loss."""
    now = datetime.now(timezone.utc)
    loss_ts = (now - timedelta(hours=6)).isoformat()  # Loss 6 hours ago
    
    state = {
        "last_trade_at": (now - timedelta(days=2)).isoformat(),  # Last trade 2 days ago
        "losses_24h": [loss_ts],  # Loss within cooldown window
    }
    
    config = {
        "max_trades_per_day": 1,
        "cooldown_hours_after_loss": 12,
        "disable_after_losses_24h": 2,
    }
    
    can_trade, reason = _check_trade_frequency(state, config, now)
    
    assert not can_trade
    assert reason == "cooldown_active"


def test_probe_respects_loss_limit():
    """Test that probe respects disable_after_losses_24h limit."""
    now = datetime.now(timezone.utc)
    loss1_ts = (now - timedelta(hours=2)).isoformat()
    loss2_ts = (now - timedelta(hours=1)).isoformat()
    
    state = {
        "last_trade_at": (now - timedelta(days=2)).isoformat(),
        "losses_24h": [loss1_ts, loss2_ts],  # 2 losses in 24h
    }
    
    config = {
        "max_trades_per_day": 1,
        "cooldown_hours_after_loss": 12,
        "disable_after_losses_24h": 2,
    }
    
    can_trade, reason = _check_trade_frequency(state, config, now)
    
    assert not can_trade
    assert reason == "loss_limit"


if __name__ == "__main__":
    print("Running probe lane tests...")
    test_probe_disabled_when_config_disabled()
    print("✓ test_probe_disabled_when_config_disabled")
    
    test_probe_blocks_when_capital_mode_not_allowed()
    print("✓ test_probe_blocks_when_capital_mode_not_allowed")
    
    test_probe_blocks_when_open_position_exists()
    print("✓ test_probe_blocks_when_open_position_exists")
    
    test_probe_blocks_when_quarantined_symbol_is_best()
    print("✓ test_probe_blocks_when_quarantined_symbol_is_best")
    
    test_probe_respects_max_trades_per_day()
    print("✓ test_probe_respects_max_trades_per_day")
    
    test_probe_respects_cooldown()
    print("✓ test_probe_respects_cooldown")
    
    test_probe_respects_loss_limit()
    print("✓ test_probe_respects_loss_limit")
    
    print("\n✅ All tests passed!")

