"""
Orchestrator Self-Test (Phase 5b)
----------------------------------

Verifies orchestrator outputs exist and are valid.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
OPS_DIR = REPORTS_DIR / "ops"
RUNS_PATH = OPS_DIR / "orchestrator_runs.jsonl"
STATE_PATH = OPS_DIR / "orchestrator_state.json"


def test_runs_file() -> bool:
    """Test that runs file exists and is valid JSONL."""
    if not RUNS_PATH.exists():
        print(f"✗ {RUNS_PATH} does not exist")
        return False
    
    try:
        # Read last line
        with RUNS_PATH.open("r", encoding="utf-8") as f:
            lines = f.readlines()
            if not lines:
                print(f"✗ {RUNS_PATH} is empty")
                return False
            
            # Parse last line
            last_line = lines[-1].strip()
            json.loads(last_line)
        
        print(f"✓ {RUNS_PATH} exists and is valid")
        return True
    except Exception as e:
        print(f"✗ {RUNS_PATH} is invalid: {e}")
        return False


def test_state_file() -> bool:
    """Test that state file exists and is valid JSON."""
    if not STATE_PATH.exists():
        print(f"✗ {STATE_PATH} does not exist")
        return False
    
    try:
        data = json.loads(STATE_PATH.read_text())
        if not isinstance(data, dict):
            print(f"✗ {STATE_PATH} is not a dict")
            return False
        
        print(f"✓ {STATE_PATH} exists and is valid")
        return True
    except Exception as e:
        print(f"✗ {STATE_PATH} is invalid: {e}")
        return False


def main() -> int:
    """Main entry point."""
    print("ORCHESTRATOR SELF-TEST (Phase 5b)")
    print("=" * 80)
    print()
    
    checks_passed = True
    
    print("1. Checking orchestrator_runs.jsonl...")
    if not test_runs_file():
        checks_passed = False
    print()
    
    print("2. Checking orchestrator_state.json...")
    if not test_state_file():
        checks_passed = False
    print()
    
    if checks_passed:
        print("=" * 80)
        print("✓ All checks passed")
        return 0
    else:
        print("=" * 80)
        print("✗ Some checks failed")
        print("Run: python3 -m tools.chloe_orchestrator fast")
        return 1


if __name__ == "__main__":
    sys.exit(main())

