#!/usr/bin/env python3
"""
Recovery Ramp Safety Test (Phase 5H)
------------------------------------

Verifies that recovery lane is PAPER-only and restrictive-only.
"""

from __future__ import annotations

import sys
import ast
import importlib.util
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

RECOVERY_LANE_PATH = REPO_ROOT / "engine_alpha" / "loop" / "recovery_lane.py"


def check_paper_only() -> tuple[bool, str]:
    """Check that recovery lane enforces PAPER-only."""
    if not RECOVERY_LANE_PATH.exists():
        return False, "recovery_lane.py not found"
    
    content = RECOVERY_LANE_PATH.read_text()
    
    # Check for PAPER guard
    if "IS_PAPER_MODE" not in content:
        return False, "Missing IS_PAPER_MODE check"
    
    if "not_paper_mode" not in content:
        return False, "Missing PAPER mode guard"
    
    return True, "PAPER guard present"


def check_recovery_ramp_dependency() -> tuple[bool, str]:
    """Check that recovery lane reads recovery_ramp.json."""
    if not RECOVERY_LANE_PATH.exists():
        return False, "recovery_lane.py not found"
    
    content = RECOVERY_LANE_PATH.read_text()
    
    # Check for recovery ramp check
    if "recovery_ramp" not in content.lower():
        return False, "Missing recovery_ramp dependency"
    
    if "allow_recovery_trading" not in content:
        return False, "Missing allow_recovery_trading check"
    
    return True, "Recovery ramp dependency present"


def check_no_live_executor_imports() -> tuple[bool, str]:
    """Check that recovery lane doesn't import live executor modules."""
    if not RECOVERY_LANE_PATH.exists():
        return False, "recovery_lane.py not found"
    
    try:
        tree = ast.parse(RECOVERY_LANE_PATH.read_text())
        
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
    print("RECOVERY RAMP SAFETY TEST (Phase 5H)")
    print("=" * 70)
    
    all_passed = True
    
    # Test 1: PAPER-only guard
    passed, msg = check_paper_only()
    status = "✓" if passed else "✗"
    print(f"{status} PAPER-only guard: {msg}")
    if not passed:
        all_passed = False
    
    # Test 2: Recovery ramp dependency
    passed, msg = check_recovery_ramp_dependency()
    status = "✓" if passed else "✗"
    print(f"{status} Recovery ramp dependency: {msg}")
    if not passed:
        all_passed = False
    
    # Test 3: No live executor imports
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

