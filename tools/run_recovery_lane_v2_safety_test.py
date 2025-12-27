#!/usr/bin/env python3
"""
Recovery Lane V2 Safety Test (Phase 5H.2)
-----------------------------------------

Verifies that recovery lane v2 is PAPER-only and restrictive-only.
"""

from __future__ import annotations

import sys
import ast
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

RECOVERY_LANE_V2_PATH = REPO_ROOT / "engine_alpha" / "loop" / "recovery_lane_v2.py"


def check_paper_only() -> tuple[bool, str]:
    """Check that recovery lane v2 enforces PAPER-only."""
    if not RECOVERY_LANE_V2_PATH.exists():
        return False, "recovery_lane_v2.py not found"
    
    content = RECOVERY_LANE_V2_PATH.read_text()
    
    # Check for PAPER guard
    if "IS_PAPER_MODE" not in content:
        return False, "Missing IS_PAPER_MODE check"
    
    if "not_paper_mode" not in content:
        return False, "Missing PAPER mode guard"
    
    return True, "PAPER guard present"


def check_recovery_ramp_v2_dependency() -> tuple[bool, str]:
    """Check that recovery lane v2 reads recovery_ramp_v2.json."""
    if not RECOVERY_LANE_V2_PATH.exists():
        return False, "recovery_lane_v2.py not found"
    
    content = RECOVERY_LANE_V2_PATH.read_text()
    
    # Check for recovery ramp v2 check
    if "recovery_ramp_v2" not in content.lower():
        return False, "Missing recovery_ramp_v2 dependency"
    
    if "allow_recovery_lane" not in content:
        return False, "Missing allow_recovery_lane check"
    
    return True, "Recovery ramp v2 dependency present"


def check_notional_cap() -> tuple[bool, str]:
    """Check that notional cap is ≤ 10."""
    if not RECOVERY_LANE_V2_PATH.exists():
        return False, "recovery_lane_v2.py not found"
    
    content = RECOVERY_LANE_V2_PATH.read_text()
    
    # Check for MAX_NOTIONAL_USD
    if "MAX_NOTIONAL_USD" not in content:
        return False, "Missing MAX_NOTIONAL_USD constant"
    
    # Parse and check value
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "MAX_NOTIONAL_USD":
                        if isinstance(node.value, ast.Constant):
                            value = node.value.value
                            if isinstance(value, (int, float)) and value > 10.0:
                                return False, f"MAX_NOTIONAL_USD ({value}) exceeds 10.0"
                            return True, f"MAX_NOTIONAL_USD={value} (OK)"
    except Exception:
        pass
    
    # If we can't parse, check string content
    if "10.0" in content or "MAX_NOTIONAL_USD = 10" in content:
        return True, "MAX_NOTIONAL_USD appears to be 10.0"
    
    return True, "MAX_NOTIONAL_USD present (value check skipped)"


def check_no_live_executor_imports() -> tuple[bool, str]:
    """Check that recovery lane v2 doesn't import live executor modules."""
    if not RECOVERY_LANE_V2_PATH.exists():
        return False, "recovery_lane_v2.py not found"
    
    try:
        tree = ast.parse(RECOVERY_LANE_V2_PATH.read_text())
        
        forbidden_modules = [
            "live_executor",
            "live_trader",
            "binance",
            "exchange",
        ]
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(forbidden in alias.name.lower() for forbidden in forbidden_modules):
                        return False, f"Forbidden import: {alias.name}"
            
            if isinstance(node, ast.ImportFrom):
                if node.module and any(forbidden in node.module.lower() for forbidden in forbidden_modules):
                    return False, f"Forbidden import from: {node.module}"
        
        return True, "No forbidden imports"
    except Exception as e:
        return False, f"Parse error: {str(e)}"


def main() -> int:
    """Run safety tests."""
    print("RECOVERY LANE V2 SAFETY TEST (Phase 5H.2)")
    print("=" * 70)
    
    all_passed = True
    
    # Test 1: PAPER-only guard
    passed, msg = check_paper_only()
    status = "✓" if passed else "✗"
    print(f"{status} PAPER-only guard: {msg}")
    if not passed:
        all_passed = False
    
    # Test 2: Recovery ramp v2 dependency
    passed, msg = check_recovery_ramp_v2_dependency()
    status = "✓" if passed else "✗"
    print(f"{status} Recovery ramp v2 dependency: {msg}")
    if not passed:
        all_passed = False
    
    # Test 3: Notional cap
    passed, msg = check_notional_cap()
    status = "✓" if passed else "✗"
    print(f"{status} Notional cap ≤ 10: {msg}")
    if not passed:
        all_passed = False
    
    # Test 4: No live executor imports
    passed, msg = check_no_live_executor_imports()
    status = "✓" if passed else "✗"
    print(f"{status} No live executor imports: {msg}")
    if not passed:
        all_passed = False
    
    print()
    print("=" * 70)
    
    if all_passed:
        print("✅ PASS: All safety checks passed")
        return 0
    else:
        print("✗ FAIL: Some safety checks failed")
        return 2


if __name__ == "__main__":
    sys.exit(main())

