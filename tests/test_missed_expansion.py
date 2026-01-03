#!/usr/bin/env python3
"""
Unit tests for Missed Expansion Analytics

Tests the detection and classification of missed vs captured expansion events.
"""

from __future__ import annotations
import pytest
import json
import tempfile
from unittest.mock import patch, mock_open
from pathlib import Path
from datetime import datetime, timezone

from tools.run_missed_expansion import (
    compute_block_reasons, load_regime_fusion, load_symbol_states,
    nearest_open_within, utcnow, parse_ts, iso
)


class TestMissedExpansionAnalytics:
    """Test suite for missed expansion detection"""

    def test_parse_ts(self):
        """Test timestamp parsing"""
        ts_str = "2024-01-01T12:00:00Z"
        dt = parse_ts(ts_str)
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 1
        assert dt.hour == 12

    def test_iso_format(self):
        """Test ISO formatting"""
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        iso_str = iso(dt)
        assert "2024-01-01T12:00:00Z" == iso_str

    def test_compute_block_reasons_permission_denied(self):
        """Test block reason detection for permission issues"""
        sym_state = {"allow_expansion": False}
        reg = {"expansion_event": True}

        reasons = compute_block_reasons(sym_state, reg)
        assert "expansion:allow_expansion=false" in reasons

    def test_compute_block_reasons_fallback_permission(self):
        """Test fallback to exploration/scalp permissions"""
        sym_state = {"allow_expansion": None, "allow_exploration": False, "allow_scalp": False}
        reg = {"expansion_event": True}

        reasons = compute_block_reasons(sym_state, reg)
        assert "expansion:no_fallback_permission" in reasons

    def test_compute_block_reasons_no_expansion_event(self):
        """Test block reason when no expansion event"""
        sym_state = {"allow_expansion": True}
        reg = {"expansion_event": False}

        reasons = compute_block_reasons(sym_state, reg)
        assert "expansion:no_expansion_event" in reasons

    def test_compute_block_reasons_dead_chop(self):
        """Test block reason for dead chop without expansion event"""
        sym_state = {"allow_expansion": True}
        reg = {"expansion_event": False, "micro_regime": "dead_chop"}

        reasons = compute_block_reasons(sym_state, reg)
        assert "expansion:dead_chop_no_event" in reasons

    def test_compute_block_reasons_follow_through_missing(self):
        """Test block reason for missing follow-through"""
        sym_state = {"allow_expansion": True}
        reg = {"expansion_event": True, "follow_through": False}

        reasons = compute_block_reasons(sym_state, reg)
        assert "expansion:no_follow_through" in reasons

    def test_compute_block_reasons_exp_conf_too_low(self):
        """Test block reason for low expansion confidence"""
        sym_state = {"allow_expansion": True}
        reg = {"expansion_event": True, "follow_through": True, "exp_conf": 0.1}

        reasons = compute_block_reasons(sym_state, reg)
        # The reason includes the value in parentheses like "expansion:exp_conf_below_min(0.10)"
        assert any("exp_conf_below_min" in r for r in reasons)

    def test_nearest_open_within_finds_match(self):
        """Test finding nearest trade within time window"""
        center = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        opens = [
            {"symbol": "BTCUSDT", "ts": "2024-01-01T11:50:00Z", "lane_id": "expansion"},
            {"symbol": "BTCUSDT", "ts": "2024-01-01T12:05:00Z", "lane_id": "expansion"},
        ]

        match = nearest_open_within(opens, "BTCUSDT", center, 15)
        assert match is not None
        assert match["ts"] == "2024-01-01T12:05:00Z"  # Closer to center

    def test_nearest_open_within_no_match(self):
        """Test no match when outside time window"""
        center = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        opens = [
            {"symbol": "BTCUSDT", "ts": "2024-01-01T10:00:00Z", "lane_id": "expansion"},  # Too early
        ]

        match = nearest_open_within(opens, "BTCUSDT", center, 15)
        assert match is None

    def test_nearest_open_within_wrong_symbol(self):
        """Test filtering by symbol"""
        center = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        opens = [
            {"symbol": "ETHUSDT", "ts": "2024-01-01T12:05:00Z", "lane_id": "expansion"},
        ]

        match = nearest_open_within(opens, "BTCUSDT", center, 15)
        assert match is None

    def test_nearest_open_within_wrong_lane(self):
        """Test filtering by lane"""
        center = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        opens = [
            {"symbol": "BTCUSDT", "ts": "2024-01-01T12:05:00Z", "lane_id": "core"},  # Wrong lane
        ]

        match = nearest_open_within(opens, "BTCUSDT", center, 15)
        assert match is None

    @patch('tools.run_missed_expansion.safe_load_json')
    def test_load_regime_fusion(self, mock_load):
        """Test loading regime fusion data"""
        mock_data = {
            "symbols": {
                "BTCUSDT:1h": {"expansion_event": True},
                "ETHUSDT:1h": {"expansion_event": False}
            }
        }
        mock_load.return_value = mock_data

        result = load_regime_fusion()
        assert "BTCUSDT:1h" in result
        assert "ETHUSDT:1h" in result

    @patch('tools.run_missed_expansion.safe_load_json')
    def test_load_symbol_states(self, mock_load):
        """Test loading symbol states"""
        mock_data = {
            "symbols": {
                "BTCUSDT": {"allow_expansion": True},
                "ETHUSDT": {"allow_expansion": False}
            }
        }
        mock_load.return_value = mock_data

        result = load_symbol_states()
        assert result["BTCUSDT"]["allow_expansion"] is True
        assert result["ETHUSDT"]["allow_expansion"] is False

    def test_missed_expansion_classification(self):
        """Test the core logic of classifying events as missed vs captured"""
        # This would be an integration test that runs the full script
        # For now, we'll test the individual components

        # Test captured event
        sym_state = {"allow_expansion": True}
        reg = {
            "expansion_event": True,
            "follow_through": True,
            "exp_conf": 0.8,
            "expansion_strength": 1.5
        }

        reasons = compute_block_reasons(sym_state, reg)
        assert len(reasons) == 0  # No blocking reasons = could be captured

        # Test missed event due to permission
        sym_state_blocked = {"allow_expansion": False}
        reasons_blocked = compute_block_reasons(sym_state_blocked, reg)
        assert "expansion:allow_expansion=false" in reasons_blocked

        # Test missed event due to low confidence
        reg_low_conf = reg.copy()
        reg_low_conf["exp_conf"] = 0.1
        reasons_low_conf = compute_block_reasons(sym_state, reg_low_conf)
        # The reason includes the value in parentheses
        assert any("exp_conf_below_min" in r for r in reasons_low_conf)
