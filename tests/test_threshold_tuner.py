"""
Tests for GPT Threshold Tuner (Module 13)
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from engine_alpha.reflect.threshold_tuner import (
    propose_thresholds,
    ThresholdProposal,
    build_stats_for_tuning,
    build_gpt_prompt,
    parse_gpt_response,
    clamp_threshold_change,
)


class TestThresholdTuner:
    """Test suite for threshold tuner."""
    
    def test_clamp_threshold_change(self):
        """Test threshold change clamping."""
        # Within limit
        result = clamp_threshold_change(0.60, 0.65, 0.10)
        assert result == 0.65
        
        # Exceeds limit (positive)
        result = clamp_threshold_change(0.60, 0.75, 0.10)
        assert result == 0.70  # Clamped to +0.10
        
        # Exceeds limit (negative)
        result = clamp_threshold_change(0.60, 0.45, 0.10)
        assert result == 0.50  # Clamped to -0.10
    
    def test_parse_gpt_response_json(self):
        """Test parsing GPT response with JSON."""
        response_text = """
        {
          "entry_min_confidence": 0.65,
          "exit_min_confidence": 0.28,
          "max_drift_for_entries": 0.45,
          "max_drift_for_open_positions": 0.65,
          "rationale": "PF_local is below 1.0, suggesting we raise entry threshold"
        }
        """
        
        parsed = parse_gpt_response(response_text)
        assert parsed is not None
        assert parsed["entry_min_confidence"] == 0.65
        assert parsed["exit_min_confidence"] == 0.28
        assert parsed["rationale"] == "PF_local is below 1.0, suggesting we raise entry threshold"
    
    def test_parse_gpt_response_markdown(self):
        """Test parsing GPT response with markdown code block."""
        response_text = """
        Here's my analysis:
        
        ```json
        {
          "entry_min_confidence": 0.70,
          "exit_min_confidence": 0.30,
          "max_drift_for_entries": 0.40,
          "max_drift_for_open_positions": 0.60,
          "rationale": "High drift detected, tightening entry gates"
        }
        ```
        """
        
        parsed = parse_gpt_response(response_text)
        assert parsed is not None
        assert parsed["entry_min_confidence"] == 0.70
        assert parsed["max_drift_for_entries"] == 0.40
    
    def test_build_stats_for_tuning(self):
        """Test stats building from trades."""
        trades = [
            {"type": "open", "confidence": 0.75, "regime": "trend_up"},
            {"type": "close", "pct": 0.02, "confidence": 0.75, "regime": "trend_up"},
            {"type": "open", "confidence": 0.65, "regime": "chop"},
            {"type": "close", "pct": -0.01, "confidence": 0.65, "regime": "chop"},
            {"type": "open", "confidence": 0.85, "regime": "trend_up"},
            {"type": "close", "pct": 0.03, "confidence": 0.85, "regime": "trend_up"},
        ]
        
        risk_config = {"tuning": {}}
        stats = build_stats_for_tuning(trades, risk_config)
        
        assert stats["trade_count"] == 3
        assert stats["pf_local"] > 0
        assert "trend_up" in stats["pf_by_regime"]
        assert "chop" in stats["pf_by_regime"]
        assert "drift_state" in stats
    
    def test_build_gpt_prompt(self):
        """Test GPT prompt building."""
        stats = {
            "trade_count": 50,
            "pf_local": 0.95,
            "pf_by_regime": {"trend_up": 1.2, "chop": 0.8},
            "pf_by_confidence_band": {"0.6-0.8": 1.1, "0.8-1.0": 1.3},
            "drift_state": {"drift_score": 0.3, "pf_local": 0.95, "confidence_return_corr": 0.25},
        }
        current_thresholds = {
            "entry_min_confidence": 0.60,
            "exit_min_confidence": 0.30,
            "max_drift_for_entries": 0.50,
            "max_drift_for_open_positions": 0.70,
        }
        risk_config = {
            "tuning": {
                "max_change_per_step": {
                    "entry_min_confidence": 0.10,
                    "exit_min_confidence": 0.10,
                    "max_drift_for_entries": 0.20,
                    "max_drift_for_open_positions": 0.20,
                }
            }
        }
        
        prompt = build_gpt_prompt(stats, current_thresholds, risk_config)
        
        assert "PF_local" in prompt
        assert "entry_min_confidence" in prompt
        assert "max_change_per_step" in prompt
        assert "JSON" in prompt
    
    @patch('engine_alpha.reflect.threshold_tuner.load_recent_trades')
    @patch('engine_alpha.reflect.threshold_tuner.call_gpt_for_thresholds')
    def test_propose_thresholds_success(self, mock_gpt, mock_load_trades):
        """Test successful threshold proposal."""
        # Mock trades
        mock_trades = [
            {"type": "open", "confidence": 0.75},
            {"type": "close", "pct": 0.02, "confidence": 0.75, "regime": "trend_up"},
        ] * 30  # 60 trades
        
        mock_load_trades.return_value = mock_trades
        
        # Mock GPT response
        mock_gpt.return_value = {
            "entry_min_confidence": 0.65,
            "exit_min_confidence": 0.28,
            "max_drift_for_entries": 0.45,
            "max_drift_for_open_positions": 0.65,
            "rationale": "PF_local below 1.0, raising entry threshold",
        }
        
        risk_config = {
            "thresholds": {
                "entry_min_confidence": 0.60,
                "exit_min_confidence": 0.30,
                "max_drift_for_entries": 0.50,
                "max_drift_for_open_positions": 0.70,
            },
            "tuning": {
                "min_trades_for_tuning": 50,
                "lookback_trades": 150,
                "max_change_per_step": {
                    "entry_min_confidence": 0.10,
                    "exit_min_confidence": 0.10,
                    "max_drift_for_entries": 0.20,
                    "max_drift_for_open_positions": 0.20,
                },
                "enabled": True,
            },
        }
        
        proposal = propose_thresholds(risk_config, min_trades=50)
        
        assert proposal is not None
        assert proposal.current["entry_min_confidence"] == 0.60
        assert proposal.suggested["entry_min_confidence"] == 0.65
        assert "PF_local" in proposal.rationale or "below" in proposal.rationale.lower()
    
    @patch('engine_alpha.reflect.threshold_tuner.load_recent_trades')
    def test_propose_thresholds_insufficient_trades(self, mock_load_trades):
        """Test that proposal returns None when not enough trades."""
        mock_load_trades.return_value = [{"type": "close", "pct": 0.01}] * 10  # Only 10 trades
        
        risk_config = {
            "thresholds": {
                "entry_min_confidence": 0.60,
                "exit_min_confidence": 0.30,
                "max_drift_for_entries": 0.50,
                "max_drift_for_open_positions": 0.70,
            },
            "tuning": {
                "min_trades_for_tuning": 50,
                "enabled": True,
            },
        }
        
        proposal = propose_thresholds(risk_config, min_trades=50)
        assert proposal is None
    
    @patch('engine_alpha.reflect.threshold_tuner.load_recent_trades')
    @patch('engine_alpha.reflect.threshold_tuner.call_gpt_for_thresholds')
    def test_propose_thresholds_clamps_changes(self, mock_gpt, mock_load_trades):
        """Test that threshold changes are clamped within max_change_per_step."""
        mock_trades = [{"type": "close", "pct": 0.01}] * 60
        mock_load_trades.return_value = mock_trades
        
        # GPT suggests a change that exceeds max_change_per_step
        mock_gpt.return_value = {
            "entry_min_confidence": 0.80,  # Suggests +0.20, but max is 0.10
            "exit_min_confidence": 0.30,
            "max_drift_for_entries": 0.50,
            "max_drift_for_open_positions": 0.70,
            "rationale": "Test",
        }
        
        risk_config = {
            "thresholds": {
                "entry_min_confidence": 0.60,
                "exit_min_confidence": 0.30,
                "max_drift_for_entries": 0.50,
                "max_drift_for_open_positions": 0.70,
            },
            "tuning": {
                "min_trades_for_tuning": 50,
                "lookback_trades": 150,
                "max_change_per_step": {
                    "entry_min_confidence": 0.10,  # Max change is 0.10
                    "exit_min_confidence": 0.10,
                    "max_drift_for_entries": 0.20,
                    "max_drift_for_open_positions": 0.20,
                },
                "enabled": True,
            },
        }
        
        proposal = propose_thresholds(risk_config, min_trades=50)
        
        assert proposal is not None
        # Should be clamped to 0.60 + 0.10 = 0.70, not 0.80
        assert proposal.suggested["entry_min_confidence"] == 0.70

