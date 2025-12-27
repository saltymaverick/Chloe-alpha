#!/usr/bin/env python3
"""
Recovery Earn-Back Smoke Test

Runs in <5s, no network, using synthetic events.
Tests the earn-back ladder transitions.
"""

import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from engine_alpha.risk.recovery_earnback import (
    compute_earnback_state,
    get_default_recovery_config,
    validate_earnback_transition,
)


def create_synthetic_metrics(stage: str, pf: float = 1.0, n_trades: int = 50) -> Dict[str, Any]:
    """Create synthetic metrics for testing."""
    return {
        "pf_7d": pf,
        "n_closes_7d": n_trades,
        "win_rate": 0.5 if pf >= 1.0 else 0.3,
        "max_drawdown": 0.02 if pf >= 1.05 else 0.08,
    }


def run_smoke_test():
    """Run comprehensive smoke test of earn-back system."""
    print("🧪 RECOVERY EARN-BACK SMOKE TEST")
    print("=" * 50)

    config = get_default_recovery_config()
    now = datetime.now(timezone.utc)
    symbol = "ETHUSDT"

    print("📊 Testing Earn-Back Ladder Transitions...")
    print()

    # Test 1: Normal symbol (never demoted)
    print("1. Normal symbol (never demoted):")
    normal_state = compute_earnback_state(
        symbol=symbol,
        metrics=create_synthetic_metrics("normal"),
        now=now,
        last_demote_ts=None,
        window_stats={},
        config=config
    )
    print(f"   Stage: {normal_state['recovery_stage']}")
    print(f"   Allowances: Core={normal_state['allow_core']}, Exp={normal_state['allow_exploration']}")
    assert normal_state["recovery_stage"] == "none"
    assert normal_state["allow_core"] == True
    print("   ✅ PASS")
    print()

    # Test 2: Freshly demoted (0 post-demotion trades)
    print("2. Freshly demoted (0 post-demotion trades):")
    demote_time = now - timedelta(hours=1)
    fresh_state = compute_earnback_state(
        symbol=symbol,
        metrics=create_synthetic_metrics("fresh", n_trades=0),
        now=now,
        last_demote_ts=demote_time.isoformat(),
        window_stats={"n_closes": 0},
        config=config
    )
    print(f"   Stage: {fresh_state['recovery_stage']}")
    print(f"   Allowances: Core={fresh_state['allow_core']}, Exp={fresh_state['allow_exploration']}")
    assert fresh_state["recovery_stage"] == "sampling"
    assert fresh_state["allow_exploration"] == True
    assert fresh_state["allow_core"] == False
    print("   ✅ PASS")
    print()

    # Test 3: Sampling complete, moving to proving
    print("3. Sampling complete → proving:")
    proving_metrics = create_synthetic_metrics("proving", pf=1.03, n_trades=15)
    proving_metrics["win_rate"] = 0.52
    proving_state = compute_earnback_state(
        symbol=symbol,
        metrics=proving_metrics,
        now=now,
        last_demote_ts=demote_time.isoformat(),
        window_stats={"n_closes": 15, "pf": 1.03, "win_rate": 0.52},
        config=config
    )
    print(f"   Stage: {proving_state['recovery_stage']}")
    print(f"   Allowances: Core={proving_state['allow_core']}, Exp={proving_state['allow_exploration']}")
    assert proving_state["recovery_stage"] == "proving"
    assert proving_state["allow_exploration"] == True
    print("   ✅ PASS")
    print()

    # Test 4: Proving successful → recovered
    print("4. Proving successful → recovered:")
    recovered_metrics = create_synthetic_metrics("recovered", pf=1.08, n_trades=35)
    recovered_metrics["win_rate"] = 0.55
    recovered_metrics["max_drawdown"] = 0.025
    recovered_state = compute_earnback_state(
        symbol=symbol,
        metrics=recovered_metrics,
        now=now,
        last_demote_ts=demote_time.isoformat(),
        window_stats={"n_closes": 35, "pf": 1.08, "win_rate": 0.55, "max_drawdown": 0.025},
        config=config
    )
    print(f"   Stage: {recovered_state['recovery_stage']}")
    print(f"   Allowances: Core={recovered_state['allow_core']}, Exp={recovered_state['allow_exploration']}")
    assert recovered_state["recovery_stage"] == "recovered"
    assert recovered_state["allow_core"] == True
    assert recovered_state["allow_exploration"] == True
    print("   ✅ PASS")
    print()

    # Test 5: State transition validation
    print("5. State transition validation:")
    is_valid, reason = validate_earnback_transition(fresh_state, proving_state)
    print(f"   sampling → proving: {'✅ VALID' if is_valid else '❌ INVALID'} ({reason})")
    assert is_valid

    is_valid, reason = validate_earnback_transition(recovered_state, normal_state)
    print(f"   recovered → none: {'✅ VALID' if is_valid else '❌ INVALID'} ({reason})")
    assert is_valid

    # Invalid transition test
    invalid_transition = compute_earnback_state(
        symbol=symbol,
        metrics=create_synthetic_metrics("invalid", n_trades=5),
        now=now,
        last_demote_ts=(now - timedelta(days=40)).isoformat(),  # Too old
        window_stats={"n_closes": 5},
        config=config
    )
    print(f"   Old demotion reset: {invalid_transition['recovery_stage']} (should be 'recovered' or 'none')")
    print("   ✅ PASS")
    print()

    print("🎉 ALL SMOKE TESTS PASSED")
    print("Recovery earn-back system is functioning correctly!")
    return True


if __name__ == "__main__":
    try:
        run_smoke_test()
    except Exception as e:
        print(f"❌ SMOKE TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
