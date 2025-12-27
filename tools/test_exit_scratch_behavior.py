#!/usr/bin/env python3
"""
Test script to verify exit scratch behavior.

Tests that:
- Case A (0.05% move): is_scratch == True
- Case B (0.10% move): is_scratch == False
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from engine_alpha.loop.execute_trade import close_now, SCRATCH_THRESHOLD
from engine_alpha.loop.position_manager import set_position, clear_position


def test_scratch_behavior():
    """Test scratch detection for TP exits with different price moves."""
    
    print("=" * 80)
    print("EXIT SCRATCH BEHAVIOR TEST")
    print("=" * 80)
    print(f"\nSCRATCH_THRESHOLD = {SCRATCH_THRESHOLD} (0.05% in percentage units)")
    print(f"TP_PRICE_RMULT_MIN = 0.001 (0.1% as decimal fraction)")
    print("\n" + "-" * 80)
    
    # Test Case A: exit_px = 100.0005 (≈ +0.0005 decimal = +0.05%)
    print("\n📊 CASE A: 0.05% move (at scratch threshold)")
    print("-" * 80)
    
    entry_px_a = 100.0
    exit_px_a = 100.0005  # 0.0005 / 100.0 = 0.000005 = 0.0005% decimal = 0.05% percentage
    
    # Wait, that's wrong. Let me recalculate:
    # For 0.05% move: exit_px = entry_px * (1 + 0.0005) = 100.0 * 1.0005 = 100.05
    # For 0.05% in percentage units: pct = 0.05
    # So: (exit - entry) / entry * 100 = 0.05
    # (exit - entry) / entry = 0.0005
    # exit - entry = 0.05
    # exit = 100.05
    
    # Actually, let me use the correct calculation:
    # 0.05% move means: (exit - entry) / entry * 100 = 0.05
    # (exit - entry) / entry = 0.0005
    # exit = entry * (1 + 0.0005) = 100.0 * 1.0005 = 100.05
    
    exit_px_a = 100.05  # 0.05% move
    
    # Set up fake position
    clear_position()
    set_position({"dir": 1, "entry_px": entry_px_a, "bars_open": 1})
    
    # Capture the close event (we'll need to mock _append_trade)
    captured_events = []
    
    # Mock _append_trade to capture events
    original_append = None
    try:
        from engine_alpha.loop.execute_trade import _append_trade
        original_append = _append_trade
        
        def mock_append(event: dict) -> None:
            captured_events.append(event)
        
        # Replace _append_trade temporarily
        import engine_alpha.loop.execute_trade as et_module
        et_module._append_trade = mock_append
        
        # Call close_now
        close_now(
            entry_price=entry_px_a,
            exit_price=exit_px_a,
            dir=1,
            exit_reason="tp",
            exit_conf=0.93,
            regime="trend_down",
            risk_band="A",
            risk_mult=1.0,
        )
        
        # Restore original
        et_module._append_trade = original_append
        
        if captured_events:
            event_a = captured_events[0]
            pct_a = event_a.get("pct", 0.0)
            is_scratch_a = event_a.get("is_scratch", False)
            exit_reason_a = event_a.get("exit_reason", "unknown")
            
            print(f"  entry_px: {entry_px_a}")
            print(f"  exit_px: {exit_px_a}")
            print(f"  pct: {pct_a:.6f}%")
            print(f"  is_scratch: {is_scratch_a}")
            print(f"  exit_reason: {exit_reason_a}")
            print(f"\n  ✅ Expected: is_scratch == True (move is at threshold)")
            print(f"  {'✅ PASS' if is_scratch_a else '❌ FAIL'}: is_scratch = {is_scratch_a}")
        else:
            print("  ❌ No event captured")
    
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        if original_append:
            import engine_alpha.loop.execute_trade as et_module
            et_module._append_trade = original_append
    
    # Test Case B: exit_px = 100.10 (≈ +0.001 decimal = +0.10%)
    print("\n📊 CASE B: 0.10% move (above TP_PRICE_RMULT_MIN)")
    print("-" * 80)
    
    entry_px_b = 100.0
    exit_px_b = 100.10  # 0.10% move
    
    # Clear and reset
    clear_position()
    set_position({"dir": 1, "entry_px": entry_px_b, "bars_open": 1})
    captured_events.clear()
    
    try:
        import engine_alpha.loop.execute_trade as et_module
        et_module._append_trade = mock_append
        
        close_now(
            entry_price=entry_px_b,
            exit_price=exit_px_b,
            dir=1,
            exit_reason="tp",
            exit_conf=0.93,
            regime="trend_down",
            risk_band="A",
            risk_mult=1.0,
        )
        
        et_module._append_trade = original_append
        
        if captured_events:
            event_b = captured_events[0]
            pct_b = event_b.get("pct", 0.0)
            is_scratch_b = event_b.get("is_scratch", False)
            exit_reason_b = event_b.get("exit_reason", "unknown")
            
            print(f"  entry_px: {entry_px_b}")
            print(f"  exit_px: {exit_px_b}")
            print(f"  pct: {pct_b:.6f}%")
            print(f"  is_scratch: {is_scratch_b}")
            print(f"  exit_reason: {exit_reason_b}")
            print(f"\n  ✅ Expected: is_scratch == False (move is above threshold)")
            print(f"  {'✅ PASS' if not is_scratch_b else '❌ FAIL'}: is_scratch = {is_scratch_b}")
        else:
            print("  ❌ No event captured")
    
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        if original_append:
            import engine_alpha.loop.execute_trade as et_module
            et_module._append_trade = original_append
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    if captured_events:
        event_a = captured_events[0] if len(captured_events) >= 1 else None
        event_b = captured_events[1] if len(captured_events) >= 2 else None
        
        if event_a and event_b:
            case_a_pass = event_a.get("is_scratch", False) == True
            case_b_pass = event_b.get("is_scratch", False) == False
            
            print(f"\nCase A (0.05%): {'✅ PASS' if case_a_pass else '❌ FAIL'}")
            print(f"Case B (0.10%): {'✅ PASS' if case_b_pass else '❌ FAIL'}")
            
            if case_a_pass and case_b_pass:
                print("\n🎉 All tests passed!")
                return 0
            else:
                print("\n⚠️  Some tests failed")
                return 1
        else:
            print("\n⚠️  Missing test results")
            return 1
    else:
        print("\n⚠️  No events captured")
        return 1


if __name__ == "__main__":
    sys.exit(test_scratch_behavior())


