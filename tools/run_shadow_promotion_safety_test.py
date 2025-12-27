"""
Shadow Promotion Safety Test (Phase 5b)
---------------------------------------

Verifies that shadow promotion gate and scorer have zero order placement paths.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Set

ROOT = Path(__file__).resolve().parents[1]


def get_imports(file_path: Path) -> Set[str]:
    """Extract all import statements from a Python file."""
    imports = set()
    try:
        with file_path.open("r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)
    except Exception:
        pass
    
    return imports


def check_forbidden_imports(file_path: Path) -> list[str]:
    """Check for forbidden imports that could lead to order placement."""
    forbidden_patterns = [
        "execute_trade",
        "order_manager",
        "exchange_client",
        "binance",
        "orderbook",
        "place_order",
        "submit_order",
    ]
    
    imports = get_imports(file_path)
    violations = []
    
    for imp in imports:
        for pattern in forbidden_patterns:
            if pattern.lower() in imp.lower():
                violations.append(f"{file_path}: imports '{imp}' (matches '{pattern}')")
    
    return violations


def main() -> int:
    """Main entry point."""
    print("SHADOW PROMOTION SAFETY TEST (Phase 5b)")
    print("=" * 80)
    print()
    
    violations = []
    
    # Check Phase 5b files
    files_to_check = [
        ROOT / "engine_alpha" / "reflect" / "shadow_exploit_scorer.py",
        ROOT / "engine_alpha" / "evolve" / "shadow_promotion_gate.py",
        ROOT / "tools" / "run_shadow_exploit_score.py",
        ROOT / "tools" / "run_shadow_promotion_gate.py",
    ]
    
    for file_path in files_to_check:
        if file_path.exists():
            file_violations = check_forbidden_imports(file_path)
            violations.extend(file_violations)
        else:
            print(f"⚠️  {file_path} not found (skipping)")
    
    if violations:
        print("❌ SAFETY VIOLATIONS FOUND:")
        print("-" * 80)
        for violation in violations:
            print(f"  ✗ {violation}")
        print()
        print("These imports could lead to order placement. Fix before proceeding.")
        return 1
    else:
        print("✓ All safety checks passed")
        print()
        print("Verified files:")
        for file_path in files_to_check:
            if file_path.exists():
                print(f"  ✓ {file_path.relative_to(ROOT)}")
        print()
        print("No forbidden imports detected. Shadow promotion system is safe.")
        return 0


if __name__ == "__main__":
    sys.exit(main())

