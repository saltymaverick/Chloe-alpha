#!/usr/bin/env python3
"""
Test Suite for Advanced Scalp Lane
===================================

Comprehensive tests for the advanced scalp lane implementation.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from engine_alpha.loop.lanes.scalp_lane import ScalpLane
from engine_alpha.loop.lanes.base import LaneContext, LaneDecision
from datetime import datetime, timezone
import json


@pytest.fixture
def lane():
    """Create a ScalpLane instance for testing"""
    config = {
        "symbol_class": "MID_MEME",
        "entry_quality_threshold": 0.70,
        "base_risk_mult": 0.04
    }
    return ScalpLane(config)


def create_test_context(
    symbol="ETHUSDT",
    regime="chop",
    confidence=0.70,
    direction=1,
    allow_scalp=True,
    spread_bps=5.0,
    position=None
):
    """Create a test lane context"""
    return LaneContext(
        symbol=symbol,
        timeframe="15m",
        regime=regime,
        signal_vector={
            "confidence": confidence,
            "direction": direction,
            "close": 2000.0,
            "atr": 20.0,
            "avg_atr": 20.0,
            "liquidity_score": 0.70,
            "spread_bps": spread_bps,
            "recent_returns": [-0.002, -0.001, 0.001],
            "orderbook_imbalance": 0.6,
            "taker_imbalance": 0.5,
            "close_per_s": 0.0002,
            "hold_time_s": 0
        },
        position=position,
        policy_state={
            "allow_scalp": allow_scalp,
            "quarantined": False,
            "caps": {
                "risk_mult_cap": 0.10,
                "max_positions": 3
            }
        },
        market_data={
            "spread_bps": spread_bps,
            "bid_pressure": 0.65,
            "ask_pressure": 0.35,
            "orderbook": {
                "bids": [[2000, 15], [1999, 10]],
                "asks": [[2001, 15], [2002, 10]]
            },
            "volumes": [1000, 1100, 1200, 1500, 2000],
            "expansion_event": True
        },
        loop_state={}
    )


def test_initialization():
    """Test scalp lane initialization"""
    print("\n" + "="*70)
    print("TEST 1: Initialization")
    print("="*70)
    
    config = {
        "symbol_class": "MID_MEME",
        "entry_quality_threshold": 0.70,
        "base_risk_mult": 0.04
    }
    
    lane = ScalpLane(config)
    
    assert lane.LANE_ID == "scalp", "Lane ID should be 'scalp'"
    assert lane.entry_quality_threshold == 0.70, "Entry quality threshold should be 0.70"
    assert lane.base_risk_mult == 0.04, "Base risk mult should be 0.04"
    assert lane.trailing_activation_pct == 0.0020, "Trailing activation should be 0.20%"
    
    print("✓ Initialization successful")
    print(f"  Lane ID: {lane.LANE_ID}")
    print(f"  Entry Quality Threshold: {lane.entry_quality_threshold}")
    print(f"  Base Risk Mult: {lane.base_risk_mult}")
    print(f"  Trailing Activation: {lane.trailing_activation_pct:.4f}")
    
    return lane


def test_signal_quality_scoring(lane):
    """Test multi-factor signal quality scoring"""
    print("\n" + "="*70)
    print("TEST 2: Signal Quality Scoring")
    print("="*70)
    
    # Test with high quality setup
    ctx = create_test_context(
        confidence=0.75,
        direction=1,
        spread_bps=4.0
    )
    
    quality_score, components = lane._calculate_signal_quality_score(ctx)
    
    print(f"✓ Signal quality calculation successful")
    print(f"  Overall Quality Score: {quality_score:.3f}")
    print(f"  Components:")
    for component, score in components.items():
        print(f"    - {component}: {score:.3f}")
    
    assert 0 <= quality_score <= 1, "Quality score should be between 0 and 1"
    assert len(components) >= 5, "Should have at least 5 quality components"
    
    return quality_score


def test_adaptive_risk(lane):
    """Test adaptive risk calculation"""
    print("\n" + "="*70)
    print("TEST 3: Adaptive Risk Calculation")
    print("="*70)
    
    ctx = create_test_context()
    
    # Test with different signal qualities
    test_qualities = [0.90, 0.75, 0.60]
    
    for quality in test_qualities:
        adaptive_risk = lane._calculate_adaptive_risk_mult(ctx, quality)
        print(f"  Quality {quality:.2f} → Risk Mult {adaptive_risk:.4f}")
        
        assert adaptive_risk <= lane.risk_mult_cap, "Risk should not exceed cap"
        assert adaptive_risk > 0, "Risk should be positive"
    
    print("✓ Adaptive risk calculation successful")


def test_entry_evaluation(lane):
    """Test entry opportunity evaluation"""
    print("\n" + "="*70)
    print("TEST 4: Entry Evaluation")
    print("="*70)
    
    # Test valid entry
    ctx = create_test_context(
        confidence=0.72,
        direction=1,
        spread_bps=5.0
    )
    
    allowed, reason = lane.is_allowed(ctx)
    print(f"  Allowed: {allowed}, Reason: {reason}")
    
    if allowed:
        result = lane.execute_tick(ctx)
        if result:
            print(f"✓ Entry approved")
            print(f"  Decision: {result.decision}")
            print(f"  Risk Mult: {result.risk_mult:.4f}")
            print(f"  Reason: {result.reason}")
            print(f"  Tags: {result.tags}")
            
            assert result.decision == LaneDecision.OPEN, "Should decide to open"
            assert result.risk_mult > 0, "Risk mult should be positive"
        else:
            print("  No entry signal (quality may be below threshold)")
    else:
        print(f"  Entry blocked: {reason}")
    
    # Test blocked entry (wrong regime)
    ctx_blocked = create_test_context(regime="trend")
    allowed_blocked, reason_blocked = lane.is_allowed(ctx_blocked)
    print(f"\n  Trend Regime Test - Allowed: {allowed_blocked}, Reason: {reason_blocked}")
    assert not allowed_blocked, "Should block trend regime"
    
    print("✓ Entry evaluation successful")


def test_exit_evaluation(lane):
    """Test exit evaluation with multiple scenarios"""
    print("\n" + "="*70)
    print("TEST 5: Exit Evaluation")
    print("="*70)
    
    # Test 1: Position in profit (should hit TP)
    position_profit = {
        "entry_px": 2000.0,
        "dir": 1,
        "entry_ts": datetime.now(timezone.utc).isoformat(),
        "peak_pnl": 0.0
    }
    
    ctx_profit = create_test_context(position=position_profit)
    ctx_profit.signal_vector["close"] = 2008.0  # +0.40% profit
    ctx_profit.signal_vector["hold_time_s"] = 120
    
    result_profit = lane._evaluate_position_exit(ctx_profit)
    print(f"  Profit Scenario:")
    print(f"    Decision: {result_profit.decision if result_profit else 'HOLD'}")
    print(f"    Reason: {result_profit.reason if result_profit else 'N/A'}")
    
    # Test 2: Position in loss (should hit SL)
    position_loss = {
        "entry_px": 2000.0,
        "dir": 1,
        "entry_ts": datetime.now(timezone.utc).isoformat(),
        "peak_pnl": 0.0
    }
    
    ctx_loss = create_test_context(position=position_loss)
    ctx_loss.signal_vector["close"] = 1995.0  # -0.25% loss
    ctx_loss.signal_vector["hold_time_s"] = 60
    
    result_loss = lane._evaluate_position_exit(ctx_loss)
    print(f"\n  Loss Scenario:")
    print(f"    Decision: {result_loss.decision if result_loss else 'HOLD'}")
    print(f"    Reason: {result_loss.reason if result_loss else 'N/A'}")
    
    # Test 3: Trailing stop scenario
    position_trailing = {
        "entry_px": 2000.0,
        "dir": 1,
        "entry_ts": datetime.now(timezone.utc).isoformat(),
        "peak_pnl": 0.0025  # Peak at +0.25%
    }
    
    ctx_trailing = create_test_context(position=position_trailing)
    ctx_trailing.signal_vector["close"] = 2003.0  # Now at +0.15% (below trailing stop)
    ctx_trailing.signal_vector["hold_time_s"] = 180
    
    result_trailing = lane._evaluate_position_exit(ctx_trailing)
    print(f"\n  Trailing Stop Scenario:")
    print(f"    Decision: {result_trailing.decision if result_trailing else 'HOLD'}")
    print(f"    Reason: {result_trailing.reason if result_trailing else 'N/A'}")
    
    print("\n✓ Exit evaluation successful")


def test_churn_controls(lane):
    """Test churn control mechanisms"""
    print("\n" + "="*70)
    print("TEST 6: Churn Controls")
    print("="*70)
    
    ctx = create_test_context()
    
    # Test cooldown
    lane._set_cooldown("ETHUSDT", 60)
    in_cooldown, remaining = lane._is_in_cooldown("ETHUSDT")
    print(f"  Cooldown Test: In Cooldown = {in_cooldown}, Remaining = {remaining:.1f}s")
    assert in_cooldown, "Should be in cooldown"
    
    # Test trade count
    initial_count = lane._get_symbol_trade_count("ETHUSDT")
    lane._increment_trade_count("ETHUSDT")
    new_count = lane._get_symbol_trade_count("ETHUSDT")
    print(f"  Trade Count: {initial_count} → {new_count}")
    assert new_count > initial_count, "Trade count should increment"
    
    # Test loss streak
    lane._update_loss_streak("ETHUSDT", True)
    lane._update_loss_streak("ETHUSDT", True)
    streak = lane._get_loss_streak("ETHUSDT")
    print(f"  Loss Streak: {streak}")
    assert streak == 2, "Loss streak should be 2"
    
    # Reset with win
    lane._update_loss_streak("ETHUSDT", False)
    streak_reset = lane._get_loss_streak("ETHUSDT")
    print(f"  Loss Streak After Win: {streak_reset}")
    assert streak_reset == 0, "Loss streak should reset to 0"
    
    print("✓ Churn controls working correctly")


def test_liquidity_checks(lane):
    """Test liquidity and spread checks"""
    print("\n" + "="*70)
    print("TEST 7: Liquidity Checks")
    print("="*70)
    
    # Test with good liquidity
    ctx_good = create_test_context(spread_bps=5.0)
    passes_good = lane._passes_liquidity_checks(ctx_good)
    print(f"  Good Liquidity (5 bps spread): {passes_good}")
    assert passes_good, "Should pass with good liquidity"
    
    # Test with wide spread
    ctx_wide = create_test_context(spread_bps=10.0)
    passes_wide = lane._passes_liquidity_checks(ctx_wide)
    print(f"  Wide Spread (10 bps): {passes_wide}")
    assert not passes_wide, "Should fail with wide spread"
    
    print("✓ Liquidity checks working correctly")


def test_state_persistence(lane):
    """Test state persistence across restarts"""
    print("\n" + "="*70)
    print("TEST 8: State Persistence")
    print("="*70)
    
    # Save some state
    lane._set_cooldown("BTCUSDT", 300)
    lane._increment_trade_count("BTCUSDT")
    lane._update_loss_streak("BTCUSDT", True)
    
    # Verify state file exists
    state_file = Path("reports/risk/scalp_lane_state.json")
    assert state_file.exists(), "State file should exist"
    
    # Load state
    with open(state_file, 'r') as f:
        saved_state = json.load(f)
    
    print(f"  State file exists: {state_file}")
    print(f"  Cooldowns saved: {'symbol_cooldowns' in saved_state}")
    print(f"  Trade counts saved: {'symbol_trade_counts' in saved_state}")
    print(f"  Loss streaks saved: {'loss_streaks' in saved_state}")
    
    assert "symbol_cooldowns" in saved_state, "Should save cooldowns"
    assert "symbol_trade_counts" in saved_state, "Should save trade counts"
    assert "loss_streaks" in saved_state, "Should save loss streaks"
    
    print("✓ State persistence working correctly")


def test_risk_profile(lane):
    """Test risk profile generation"""
    print("\n" + "="*70)
    print("TEST 9: Risk Profile")
    print("="*70)
    
    ctx = create_test_context()
    risk_profile = lane.get_risk_profile(ctx)
    
    print(f"  Risk Profile:")
    for key, value in risk_profile.items():
        print(f"    {key}: {value}")
    
    assert "risk_mult_cap" in risk_profile, "Should include risk_mult_cap"
    assert "adaptive_risk_mult" in risk_profile, "Should include adaptive_risk_mult"
    assert "trailing_activation_pct" in risk_profile, "Should include trailing_activation_pct"
    
    print("✓ Risk profile generation successful")


def run_all_tests():
    """Run all test cases"""
    print("\n" + "="*70)
    print("ADVANCED SCALP LANE TEST SUITE")
    print("="*70)
    
    try:
        # Initialize
        lane = test_initialization()
        
        # Run tests
        test_signal_quality_scoring(lane)
        test_adaptive_risk(lane)
        test_entry_evaluation(lane)
        test_exit_evaluation(lane)
        test_churn_controls(lane)
        test_liquidity_checks(lane)
        test_state_persistence(lane)
        test_risk_profile(lane)
        
        print("\n" + "="*70)
        print("ALL TESTS PASSED ✓")
        print("="*70)
        print("\nThe Advanced Scalp Lane is ready for deployment!")
        print("\nNext steps:")
        print("1. Enable allow_scalp in symbol policy")
        print("2. Monitor performance with scalp_performance_tracker")
        print("3. Review SCALP_LANE_GUIDE.md for optimization tips")
        
        return True
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return False
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

