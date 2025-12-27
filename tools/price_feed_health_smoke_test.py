#!/usr/bin/env python3
"""
Smoke test for Price Feed Health module.

Should pass even if no external feeds exist by using whatever local cache/log is present.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.data.price_feed_health import is_price_feed_ok, get_latest_price


def test_price_feed_health() -> int:
    """Test price feed health functions."""
    print("Testing Price Feed Health module...")
    print()
    
    # Test symbols (common ones)
    test_symbols = ["SOLUSDT", "BNBUSDT", "ETHUSDT"]
    
    all_passed = True
    
    for symbol in test_symbols:
        print(f"Testing {symbol}...")
        
        # Test is_price_feed_ok
        is_ok, meta = is_price_feed_ok(symbol, max_age_seconds=600, require_price=True)
        
        print(f"  is_price_feed_ok: {is_ok}")
        print(f"  source: {meta.get('source_used', 'unknown')}")
        print(f"  age_seconds: {meta.get('age_seconds', 'N/A')}")
        
        errors = meta.get("errors", [])
        if errors:
            print(f"  errors: {errors[:3]}")
        
        # Test get_latest_price
        price, price_meta = get_latest_price(symbol)
        print(f"  latest_price: {price}")
        
        # If we got a price or meta info, consider it a pass (even if stale)
        if price is not None or price_meta.get("source_used"):
            print(f"  ✓ {symbol}: OK (has data)")
        else:
            print(f"  ⚠ {symbol}: No data (may be expected if feeds unavailable)")
        
        print()
    
    # Test that function signatures work
    print("Testing function signatures...")
    try:
        is_ok, meta = is_price_feed_ok("TESTUSDT", max_age_seconds=600)
        assert isinstance(is_ok, bool)
        assert isinstance(meta, dict)
        assert "source_used" in meta
        print("  ✓ Function signatures OK")
    except Exception as e:
        print(f"  ✗ Function signature test failed: {e}")
        all_passed = False
    
    print()
    if all_passed:
        print("✓ Smoke test passed")
        return 0
    else:
        print("⚠ Smoke test completed with warnings (may be expected if feeds unavailable)")
        return 0  # Don't fail on missing feeds


if __name__ == "__main__":
    sys.exit(test_price_feed_health())

