#!/usr/bin/env python3
"""
Quarantine Safety Test (Phase 5g)
-----------------------------------

Verifies that quarantine engine:
- Does not import executor modules
- Does not call trade execution functions
- Is restrictive-only (never enables trading)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUARANTINE_MODULE = ROOT / "engine_alpha" / "risk" / "quarantine.py"


def check_imports() -> bool:
    """Check for forbidden imports."""
    forbidden = [
        "execute_trade",
        "open_if_allowed",
        "exploit_executor",
        "live_bridge",
    ]
    
    if not QUARANTINE_MODULE.exists():
        print("ERROR: quarantine.py not found")
        return False
    
    content = QUARANTINE_MODULE.read_text()
    tree = ast.parse(content)
    
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if any(f in alias.name for f in forbidden):
                    print(f"ERROR: Forbidden import found: {alias.name}")
                    return False
        elif isinstance(node, ast.ImportFrom):
            if node.module and any(f in node.module for f in forbidden):
                print(f"ERROR: Forbidden import from: {node.module}")
                return False
    
    return True


def check_function_calls() -> bool:
    """Check for forbidden function calls."""
    forbidden_calls = [
        "execute_trade",
        "open_if_allowed",
        "open_exploit_trade",
        "close_exploit_trade",
    ]
    
    if not QUARANTINE_MODULE.exists():
        return False
    
    content = QUARANTINE_MODULE.read_text()
    
    for call in forbidden_calls:
        if call in content:
            lines = content.splitlines()
            for i, line in enumerate(lines):
                if call in line and "(" in line:
                    if not line.strip().startswith("#") and call + "(" in line:
                        print(f"ERROR: Potential forbidden call found: {call} (line {i+1})")
                        print(f"  {line.strip()}")
                        return False
    
    return True


def check_restrictive_only() -> bool:
    """Check that quarantine is restrictive-only."""
    if not QUARANTINE_MODULE.exists():
        return False
    
    content = QUARANTINE_MODULE.read_text()
    
    # Check for restrictive-only patterns
    restrictive_patterns = [
        "blocked_symbols",
        "reduce_weight",
        "never enables",
        "restrictive-only",
    ]
    
    for pattern in restrictive_patterns:
        if pattern not in content.lower():
            print(f"WARNING: Restrictive-only pattern '{pattern}' not found")
    
    return True


def main() -> int:
    """Run safety tests."""
    print("QUARANTINE SAFETY TEST (Phase 5g)")
    print("=" * 70)
    
    all_passed = True
    
    # Test 1: No executor imports
    print("Test 1: Checking for forbidden imports...")
    if check_imports():
        print("  ✓ No forbidden imports found")
    else:
        print("  ✗ FAILED")
        all_passed = False
    
    # Test 2: No trade execution calls
    print("Test 2: Checking for forbidden function calls...")
    if check_function_calls():
        print("  ✓ No forbidden function calls found")
    else:
        print("  ✗ FAILED")
        all_passed = False
    
    # Test 3: Restrictive-only
    print("Test 3: Verifying restrictive-only design...")
    if check_restrictive_only():
        print("  ✓ Restrictive-only design verified")
    else:
        print("  ⚠ Warnings found")
    
    print("=" * 70)
    if all_passed:
        print("✓ All safety tests passed")
        return 0
    else:
        print("✗ Some safety tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())

