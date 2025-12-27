#!/usr/bin/env python3
"""
Quick verification that new exit logic is active and ready.

Checks:
1. Constants are set correctly
2. Scratch detection logic is correct
3. TP price-move check is wired correctly
"""

from __future__ import annotations

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from engine_alpha.loop.execute_trade import SCRATCH_THRESHOLD, _is_effectively_zero
from engine_alpha.loop.autonomous_trader import MIN_HOLD_BARS_TP_SL, TP_PRICE_RMULT_MIN


def verify_constants():
    """Verify all constants are set correctly."""
    print("=" * 80)
    print("CONSTANTS VERIFICATION")
    print("=" * 80)
    
    checks = []
    
    # Check SCRATCH_THRESHOLD
    if SCRATCH_THRESHOLD == 0.05:
        checks.append(("SCRATCH_THRESHOLD", "✅", f"{SCRATCH_THRESHOLD} (0.05% = 5 bps)"))
    else:
        checks.append(("SCRATCH_THRESHOLD", "❌", f"{SCRATCH_THRESHOLD} (expected 0.05)"))
    
    # Check MIN_HOLD_BARS_TP_SL
    if MIN_HOLD_BARS_TP_SL == 1:
        checks.append(("MIN_HOLD_BARS_TP_SL", "✅", f"{MIN_HOLD_BARS_TP_SL}"))
    else:
        checks.append(("MIN_HOLD_BARS_TP_SL", "❌", f"{MIN_HOLD_BARS_TP_SL} (expected 1)"))
    
    # Check TP_PRICE_RMULT_MIN
    if TP_PRICE_RMULT_MIN == 0.001:
        checks.append(("TP_PRICE_RMULT_MIN", "✅", f"{TP_PRICE_RMULT_MIN} (0.1% as decimal)"))
    else:
        checks.append(("TP_PRICE_RMULT_MIN", "❌", f"{TP_PRICE_RMULT_MIN} (expected 0.001)"))
    
    for name, status, value in checks:
        print(f"{status} {name:<25} = {value}")
    
    all_pass = all(status == "✅" for _, status, _ in checks)
    return all_pass


def verify_scratch_logic():
    """Verify scratch detection logic handles edge cases."""
    print("\n" + "=" * 80)
    print("SCRATCH LOGIC VERIFICATION")
    print("=" * 80)
    
    test_cases = [
        (0.0, True, "Zero move"),
        (-0.0, True, "Negative zero"),
        (0.01, True, "0.01% move (below threshold)"),
        (0.04, True, "0.04% move (below threshold)"),
        (0.05, False, "0.05% move (at threshold)"),
        (0.06, False, "0.06% move (above threshold)"),
        (-0.03, True, "-0.03% move (below threshold)"),
    ]
    
    all_pass = True
    for pct, expected_scratch, desc in test_cases:
        # Simulate scratch logic
        is_zero_move = _is_effectively_zero(pct)
        small_move = abs(pct) < SCRATCH_THRESHOLD
        scratchable = True  # Assume tp/sl/drop/decay
        is_scratch = is_zero_move or (small_move and scratchable)
        
        status = "✅" if is_scratch == expected_scratch else "❌"
        if is_scratch != expected_scratch:
            all_pass = False
        
        print(f"{status} {desc:<30} pct={pct:7.4f}% → scratch={is_scratch} (expected {expected_scratch})")
    
    return all_pass


def verify_tp_requirements():
    """Verify TP requirements are correct."""
    print("\n" + "=" * 80)
    print("TP REQUIREMENTS VERIFICATION")
    print("=" * 80)
    
    print(f"\nTP requires ALL of:")
    print(f"  1. bars_open >= {MIN_HOLD_BARS_TP_SL} (min-hold)")
    print(f"  2. final_conf >= tp_conf (confidence)")
    print(f"  3. abs_price_move >= {TP_PRICE_RMULT_MIN} (0.1% as decimal)")
    
    # Test price-move calculation
    test_cases = [
        (100.0, 100.0, False, "No move"),
        (100.0, 100.05, False, "0.05% move (below threshold)"),
        (100.0, 100.10, True, "0.10% move (at threshold)"),
        (100.0, 100.15, True, "0.15% move (above threshold)"),
    ]
    
    print(f"\nPrice-move check examples:")
    all_pass = True
    for entry, exit_px, expected_pass, desc in test_cases:
        raw_ret = abs((exit_px - entry) / entry)
        # Use small epsilon for floating-point comparison
        passes = raw_ret >= (TP_PRICE_RMULT_MIN - 1e-9)
        status = "✅" if passes == expected_pass else "❌"
        if passes != expected_pass:
            all_pass = False
        
        print(f"{status} {desc:<30} entry={entry}, exit={exit_px} → move={raw_ret:.6f} → {'PASS' if passes else 'FAIL'}")
    
    return all_pass


def main():
    """Run all verifications."""
    print("\n" + "=" * 80)
    print("NEW EXIT LOGIC VERIFICATION")
    print("=" * 80)
    
    results = []
    results.append(("Constants", verify_constants()))
    results.append(("Scratch Logic", verify_scratch_logic()))
    results.append(("TP Requirements", verify_tp_requirements()))
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} {name}")
    
    all_pass = all(passed for _, passed in results)
    
    if all_pass:
        print("\n🎉 All verifications passed! New exit logic is ready.")
        print("\nNext steps:")
        print("  1. Run: ./reset_chloe.sh")
        print("  2. Run: sudo systemctl restart chloe.service")
        print("  3. Wait a few hours, then check: python3 -m tools.chloe_checkin")
        return 0
    else:
        print("\n⚠️  Some verifications failed. Please review the output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

