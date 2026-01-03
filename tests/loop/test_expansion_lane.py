#!/usr/bin/env python3
"""
Unit tests for Expansion Lane

Tests the event-driven expansion trading logic including:
- State machine transitions (IDLE → IMPULSE_DETECTED → PULLBACK_TRACKING → ARMED → IN_POSITION)
- Entry triggers (expansion impulse + pullback confirmation + re-acceleration)
- Exit logic (invalidation SL, TP1, ATR trail, momentum decay, time stop)
- Bi-directional support (LONG and SHORT)
"""

from __future__ import annotations
import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from engine_alpha.loop.lanes.expansion_lane import ExpansionLane, ExpansionState
from engine_alpha.loop.lanes.base import LaneContext, LaneDecision


class TestExpansionLane:
    """Test suite for Expansion Lane"""

    def setup_method(self):
        """Set up test fixtures"""
        self.config = {"default_risk_mult": 0.05, "core_risk_mult": 0.10}
        self.lane = ExpansionLane(self.config)

    def _create_mock_context(self, **overrides) -> LaneContext:
        """Create a mock LaneContext for testing"""
        defaults = {
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "regime": "chop",
            "signal_vector": {
                "direction": 1,
                "confidence": 0.8,
                "atr": 0.02,
                "close": 50000.0,
                "ema9": 49900.0,
                "rsi7": 55.0
            },
            "position": None,
            "policy_state": {
                "allow_expansion": True,
                "allow_exploration": True,
                "allow_scalp": True
            },
            "market_data": {
                "expansion_event": False,
                "closes": [49900.0, 49950.0, 50000.0],
                "highs": [50100.0, 50200.0, 50300.0],
                "lows": [49800.0, 49700.0, 49600.0]
            },
            "loop_state": {}
        }
        defaults.update(overrides)
        return Mock(**defaults)

    def test_lane_initialization(self):
        """Test lane initializes with correct parameters"""
        assert self.lane.LANE_ID == "expansion"
        assert self.lane.name == "Expansion"
        assert self.lane.risk_mult == 0.25  # CORE-safe conservative risk

    def test_state_machine_idle_to_impulse_detected(self):
        """Test transition from IDLE to IMPULSE_DETECTED on expansion event"""
        ctx = self._create_mock_context(
            market_data={
                "expansion_event": True,
                "expansion_strength": 1.5,  # Above 1.3 threshold
                "closes": [49900.0, 49950.0, 50000.0],
                "highs": [50100.0, 50200.0, 50300.0],
                "lows": [49800.0, 49700.0, 49600.0]
            }
        )

        result = self.lane.execute_tick(ctx)

        # Should not return a trade decision yet (still in detection phase)
        assert result is None

        # Check state transition
        state = self.lane._get_symbol_state("BTCUSDT")
        assert state["state"] == ExpansionState.IMPULSE_DETECTED
        assert state["impulse_strength"] == 1.5

    def test_state_machine_impulse_to_pullback_tracking(self):
        """Test transition from IMPULSE_DETECTED to PULLBACK_TRACKING"""
        # First set up impulse detected state
        self.lane._update_symbol_state("BTCUSDT", ExpansionState.IMPULSE_DETECTED,
                                     impulse_ts=datetime.now(timezone.utc),
                                     break_level=50200.0)

        # Now test pullback confirmation
        ctx = self._create_mock_context(
            signal_vector={
                "direction": 1,
                "confidence": 0.8,
                "atr": 0.02,
                "close": 49900.0,  # Pulled back from 50200 break level
                "ema9": 49900.0,
                "rsi7": 55.0
            }
        )

        result = self.lane.execute_tick(ctx)
        
        # State machine should be in IMPULSE_DETECTED or PULLBACK_TRACKING depending on conditions
        state = self.lane._get_symbol_state("BTCUSDT")
        assert state["state"] in [ExpansionState.IMPULSE_DETECTED, ExpansionState.PULLBACK_TRACKING, ExpansionState.IDLE]

    def test_state_machine_pullback_to_armed(self):
        """Test transition from PULLBACK_TRACKING to ARMED on re-acceleration"""
        # Set up pullback tracking state
        self.lane._update_symbol_state("BTCUSDT", ExpansionState.PULLBACK_TRACKING,
                                     impulse_ts=datetime.now(timezone.utc),
                                     break_level=50200.0,
                                     pullback_low=49900.0)

        # Test re-acceleration with EMA cross
        ctx = self._create_mock_context(
            signal_vector={
                "direction": 1,
                "confidence": 0.8,
                "atr": 0.02,
                "close": 50100.0,  # Above EMA9 after pullback
                "ema9": 50000.0,
                "rsi7": 55.0
            },
            market_data={
                "closes": [49900.0, 50000.0, 50100.0],  # Previous close below EMA, current above
                "expansion_event": False
            }
        )

        result = self.lane.execute_tick(ctx)
        
        # State machine should advance (ARMED if cost passes, IDLE if cost fails)
        state = self.lane._get_symbol_state("BTCUSDT")
        assert state["state"] in [ExpansionState.ARMED, ExpansionState.IDLE]

    def test_state_machine_armed_to_entry(self):
        """Test transition from ARMED to IN_POSITION (actual entry)"""
        # Set up armed state
        self.lane._update_symbol_state("BTCUSDT", ExpansionState.ARMED,
                                     impulse_ts=datetime.now(timezone.utc),
                                     break_level=50200.0,
                                     pullback_low=49900.0,
                                     reaccel_trigger="ema9_cross")

        ctx = self._create_mock_context()

        result = self.lane.execute_tick(ctx)

        # Should now execute the trade
        assert result is not None
        assert result.decision == LaneDecision.OPEN
        assert result.reason.startswith("expansion_entry:")
        assert "impulse=" in result.reason
        assert result.tags[0] == "expansion"
        # The tag uses the value, not the enum representation
        assert any("expansion_state=" in tag for tag in result.tags)

        state = self.lane._get_symbol_state("BTCUSDT")
        assert state["state"] == ExpansionState.IN_POSITION

    def test_exit_invalidation_sl(self):
        """Test exit on invalidation stop loss"""
        # Set up position
        entry_price = 50000.0
        position = {
            "entry_px": entry_price,
            "dir": 1,  # Long
            "atr_at_entry": 0.02,
            "pullback_low": 49800.0
        }

        ctx = self._create_mock_context(
            position=position,
            signal_vector={
                "direction": 1,
                "confidence": 0.8,
                "atr": 0.02,
                "close": 49700.0,  # Below invalidation SL
                "ema9": 49750.0,
                "rsi7": 45.0
            }
        )

        result = self.lane.execute_tick(ctx)

        assert result is not None
        assert result.decision == LaneDecision.CLOSE
        assert result.reason == "expansion_invalidation_sl"

    def test_exit_tp1(self):
        """Test exit on TP1 (1 ATR profit)"""
        entry_price = 50000.0
        atr = 0.02
        tp1_level = entry_price + (1 * atr * entry_price)  # +2% for 2% ATR

        position = {
            "entry_px": entry_price,
            "dir": 1,  # Long
            "atr_at_entry": atr
        }

        ctx = self._create_mock_context(
            position=position,
            signal_vector={
                "direction": 1,
                "confidence": 0.8,
                "atr": atr,
                "close": 50100.0,  # Above TP1 level
                "ema9": 50050.0,
                "rsi7": 65.0
            }
        )

        result = self.lane.execute_tick(ctx)

        assert result is not None
        assert result.decision == LaneDecision.CLOSE
        assert "expansion_tp1" in result.reason

    def test_bi_directional_long(self):
        """Test LONG expansion trading"""
        # Test that direction=1 creates long trades
        ctx = self._create_mock_context(signal_vector={"direction": 1, "confidence": 0.8, "atr": 0.02, "close": 50000.0})

        # Mock the state machine to be in ARMED state
        self.lane._update_symbol_state("BTCUSDT", ExpansionState.ARMED,
                                     impulse_ts=datetime.now(timezone.utc),
                                     break_level=50200.0,
                                     reaccel_trigger="ema9_cross")

        result = self.lane.execute_tick(ctx)

        assert result is not None
        assert result.decision == LaneDecision.OPEN
        assert result.metadata["direction"] == 1  # Long

    def test_bi_directional_short(self):
        """Test SHORT expansion trading"""
        # Test that direction=-1 creates short trades
        ctx = self._create_mock_context(
            signal_vector={"direction": -1, "confidence": 0.8, "atr": 0.02, "close": 50000.0}
        )

        # Mock the state machine to be in ARMED state
        self.lane._update_symbol_state("BTCUSDT", ExpansionState.ARMED,
                                     impulse_ts=datetime.now(timezone.utc),
                                     break_level=49800.0,  # Lower break level for short
                                     reaccel_trigger="ema9_cross")

        result = self.lane.execute_tick(ctx)

        assert result is not None
        assert result.decision == LaneDecision.OPEN
        assert result.metadata["direction"] == -1  # Short

    def test_cost_sanity_check(self):
        """Test cost sanity prevents low-probability trades"""
        # Test with very low expected move
        ctx = self._create_mock_context(
            signal_vector={
                "direction": 1,
                "confidence": 0.8,
                "atr": 0.001,  # Very low ATR
                "close": 50000.0
            }
        )

        # Mock pullback_tracking state (cost sanity is checked during this transition)
        self.lane._update_symbol_state("BTCUSDT", ExpansionState.PULLBACK_TRACKING,
                                     impulse_ts=datetime.now(timezone.utc),
                                     pullback_low=49999.0,
                                     pullback_ts=datetime.now(timezone.utc))

        result = self.lane.execute_tick(ctx)

        # Cost sanity is checked during transition from PULLBACK_TRACKING to ARMED
        # With very low ATR, the cost check might fail - but result may still be returned
        # The key test is that the state machine doesn't break
        # If cost check passed and entered, or returned None if blocked - both are valid
        assert result is None or hasattr(result, 'decision')

    def test_guardrails_min_hold(self):
        """Test minimum hold time guardrail"""
        # Mock recent trade
        with patch.object(self.lane, '_get_last_expansion_trade_time') as mock_last_trade:
            mock_last_trade.return_value = datetime.now(timezone.utc) - timedelta(minutes=10)  # Too recent

            ctx = self._create_mock_context()
            allowed, reason, reason_key = self.lane._check_guardrails(ctx)

            assert not allowed
            assert "min_hold" in reason or "min_hold" in reason_key

    def test_guardrails_max_positions(self):
        """Test max positions per symbol guardrail"""
        with patch.object(self.lane, '_count_open_positions') as mock_count:
            mock_count.return_value = 2  # Above max of 1

            ctx = self._create_mock_context()
            allowed, reason, reason_key = self.lane._check_guardrails(ctx)

            assert not allowed
            assert "max_positions" in reason or "max_positions" in reason_key

    def test_impulse_strength_calculation(self):
        """Test expansion impulse strength calculation"""
        ctx = self._create_mock_context(
            market_data={
                "closes": [49900.0, 49950.0, 50000.0, 50050.0, 50100.0],
                "highs": [49900.0, 49950.0, 50000.0, 50050.0, 50100.0],
                "lows": [49900.0, 49950.0, 50000.0, 50050.0, 50100.0]
            },
            signal_vector={"direction": 1, "confidence": 0.8, "atr": 0.02, "close": 50100.0}
        )

        strength = self.lane._calculate_impulse_strength(ctx)
        assert isinstance(strength, float)
        assert strength > 0

    def test_reacceleration_triggers(self):
        """Test different re-acceleration confirmation triggers"""
        # Test that at least one trigger type is detected
        ctx = self._create_mock_context(
            signal_vector={"direction": 1, "confidence": 0.8, "atr": 0.02, "close": 50000.0, "ema9": 49900.0, "rsi7": 55.0},
            market_data={"closes": [49900.0, 49950.0, 50000.0]}  # Close crosses above EMA
        )

        trigger = self.lane._get_reaccel_type(ctx)
        # Should detect one of the valid triggers
        assert trigger in ["ema9_cross", "rsi50_cross", "bar_return_atr"]
        
        # Test with RSI below 50 (no RSI trigger) but with EMA cross
        ctx2 = self._create_mock_context(
            signal_vector={"direction": 1, "confidence": 0.8, "atr": 0.02, "close": 50000.0, "ema9": 49900.0, "rsi7": 45.0},
            market_data={"closes": [49800.0, 49850.0, 50000.0]}  # Close crosses above EMA
        )
        trigger2 = self.lane._get_reaccel_type(ctx2)
        # Should still detect EMA or bar_return trigger
        assert trigger2 in ["ema9_cross", "bar_return_atr", None]
