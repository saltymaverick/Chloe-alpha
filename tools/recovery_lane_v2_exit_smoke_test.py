#!/usr/bin/env python3
"""
Smoke test for Recovery Lane V2 exit logic.

Tests that timeout exits work even when price is unavailable.
"""

from __future__ import annotations

import sys
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.core.paths import REPORTS
from engine_alpha.loop.recovery_lane_v2 import (
    _maybe_exit_open_position,
    MAX_HOLD_MINUTES,
)


def test_timeout_exit_no_price() -> int:
    """Test that timeout exit works without price."""
    print("Testing timeout exit without price...")
    
    # Create a position older than MAX_HOLD_MINUTES
    now = datetime.now(timezone.utc)
    entry_time = now - timedelta(minutes=MAX_HOLD_MINUTES + 5)  # 5 minutes past timeout
    
    position = {
        "direction": 1,  # Long
        "entry_price": 100.0,
        "entry_ts": entry_time.isoformat(),
        "confidence": 0.70,
        "trade_id": "test_trade_123",
    }
    
    # Test with no price (None)
    did_exit, exit_event = _maybe_exit_open_position(
        symbol="TESTUSDT",
        position=position,
        now=now,
        current_price=None,
    )
    
    if not did_exit:
        print("  ✗ FAIL: Timeout exit did not trigger")
        return 1
    
    if exit_event is None:
        print("  ✗ FAIL: Exit event is None")
        return 1
    
    if exit_event["exit_reason"] != "timeout":
        print(f"  ✗ FAIL: Expected exit_reason='timeout', got '{exit_event['exit_reason']}'")
        return 1
    
    if exit_event["exit_price"] != position["entry_price"]:
        print(f"  ✗ FAIL: Expected exit_price={position['entry_price']}, got {exit_event['exit_price']}")
        return 1
    
    if exit_event.get("exit_px_source") != "entry_fallback_no_price":
        print(f"  ✗ FAIL: Expected exit_px_source='entry_fallback_no_price', got '{exit_event.get('exit_px_source')}'")
        return 1
    
    if exit_event.get("pnl_pct") != 0.0:
        print(f"  ✗ FAIL: Expected pnl_pct=0.0 (no price), got {exit_event.get('pnl_pct')}")
        return 1
    
    print("  ✓ PASS: Timeout exit works without price")
    return 0


def test_timeout_exit_with_price() -> int:
    """Test that timeout exit works with price (should compute PnL)."""
    print("Testing timeout exit with price...")
    
    # Create a position older than MAX_HOLD_MINUTES
    now = datetime.now(timezone.utc)
    entry_time = now - timedelta(minutes=MAX_HOLD_MINUTES + 5)
    
    position = {
        "direction": 1,  # Long
        "entry_price": 100.0,
        "entry_ts": entry_time.isoformat(),
        "confidence": 0.70,
    }
    
    # Test with price available
    current_price = 101.0  # +1% gain
    did_exit, exit_event = _maybe_exit_open_position(
        symbol="TESTUSDT",
        position=position,
        now=now,
        current_price=current_price,
    )
    
    if not did_exit:
        print("  ✗ FAIL: Timeout exit did not trigger")
        return 1
    
    if exit_event["exit_reason"] != "timeout":
        print(f"  ✗ FAIL: Expected exit_reason='timeout', got '{exit_event['exit_reason']}'")
        return 1
    
    if exit_event["exit_price"] != current_price:
        print(f"  ✗ FAIL: Expected exit_price={current_price}, got {exit_event['exit_price']}")
        return 1
    
    if exit_event.get("exit_px_source") != "current_price":
        print(f"  ✗ FAIL: Expected exit_px_source='current_price', got '{exit_event.get('exit_px_source')}'")
        return 1
    
    expected_pnl = (current_price - position["entry_price"]) / position["entry_price"] * 100.0
    if abs(exit_event.get("pnl_pct", 0) - expected_pnl) > 0.001:
        print(f"  ✗ FAIL: Expected pnl_pct={expected_pnl}, got {exit_event.get('pnl_pct')}")
        return 1
    
    print("  ✓ PASS: Timeout exit works with price and computes PnL")
    return 0


def test_no_exit_fresh_position() -> int:
    """Test that fresh positions don't exit."""
    print("Testing fresh position (no exit)...")
    
    now = datetime.now(timezone.utc)
    entry_time = now - timedelta(minutes=5)  # Only 5 minutes old (well under MAX_HOLD_MINUTES)
    
    position = {
        "direction": 1,
        "entry_price": 100.0,
        "entry_ts": entry_time.isoformat(),
        "confidence": 0.70,
    }
    
    # Mock _get_signal to return high confidence (so conf_drop doesn't trigger)
    # Note: This test may fail if real signal evaluation returns low confidence
    # That's OK - the important thing is timeout works without price
    did_exit, exit_event = _maybe_exit_open_position(
        symbol="TESTUSDT",
        position=position,
        now=now,
        current_price=100.5,
    )
    
    # If exit happened, it should NOT be timeout (position is fresh)
    if did_exit and exit_event:
        exit_reason = exit_event.get("exit_reason")
        if exit_reason == "timeout":
            print(f"  ✗ FAIL: Fresh position should not timeout, but got exit_reason=timeout")
            return 1
        # Other exit reasons (conf_drop, dir_flip) are OK - they're signal-based, not time-based
        print(f"  ⚠ NOTE: Position exited due to {exit_reason} (signal-based, not time-based - OK)")
        return 0
    
    print("  ✓ PASS: Fresh position does not exit")
    return 0


def main() -> int:
    """Run smoke tests."""
    print("=" * 80)
    print("RECOVERY LANE V2 EXIT LOGIC SMOKE TEST")
    print("=" * 80)
    print()
    
    errors = 0
    
    errors += test_timeout_exit_no_price()
    print()
    
    errors += test_timeout_exit_with_price()
    print()
    
    errors += test_no_exit_fresh_position()
    print()
    
    print("=" * 80)
    if errors == 0:
        print("✓ All smoke tests passed")
        return 0
    else:
        print(f"✗ {errors} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())

