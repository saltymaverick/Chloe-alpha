#!/usr/bin/env python3
"""
Model A Timer Compliance Check
-------------------------------

Verifies that only the three allowed orchestrator timers are active:
- chloe-orchestrator-fast.timer
- chloe-orchestrator-slow.timer
- chloe-orchestrator-nightly.timer

Any other chloe-* timers are flagged as forbidden.

Usage:
    python3 -m tools.run_model_a_compliance

Exit codes:
    0 = PASS (only allowed timers exist)
    2 = FAIL (forbidden timers detected)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
REPORTS_OPS_DIR = ROOT / "reports" / "ops"
REPORTS_OPS_DIR.mkdir(parents=True, exist_ok=True)


ALLOWED_MODEL_A: Set[str] = {
    "chloe-orchestrator-fast.timer",
    "chloe-orchestrator-slow.timer",
    "chloe-orchestrator-nightly.timer",
}

ALLOWED_OPTIONAL: Set[str] = set()  # Empty for now


def get_all_chloe_timers() -> List[str]:
    """Get all timers with 'chloe' in the name."""
    try:
        result = subprocess.run(
            ["systemctl", "list-timers", "--all", "--no-pager"],
            capture_output=True,
            text=True,
            check=True,
        )
        
        timers = []
        lines = result.stdout.splitlines()
        
        # Find header line
        start_idx = 0
        for i, line in enumerate(lines):
            if "next" in line.lower() and "left" in line.lower() and "last" in line.lower():
                start_idx = i + 1
                break
        
        for line in lines[start_idx:]:
            if not line.strip() or "timers listed" in line.lower():
                continue
            
            parts = line.split()
            if len(parts) < 4:
                continue
            
            # Look for timer name (ends with .timer)
            timer_name = None
            for part in parts:
                if part.endswith(".timer") and "chloe" in part.lower():
                    timer_name = part
                    break
            
            if timer_name:
                timers.append(timer_name)
        
        return timers
    except Exception as e:
        print(f"ERROR: Failed to get timers: {e}")
        return []


def check_compliance() -> Tuple[bool, List[str], List[str]]:
    """
    Check Model A compliance.
    
    Returns:
        (is_compliant, allowed_timers, forbidden_timers)
    """
    all_timers = get_all_chloe_timers()
    
    allowed = []
    forbidden = []
    
    for timer in all_timers:
        if timer in ALLOWED_MODEL_A:
            allowed.append(timer)
        elif timer in ALLOWED_OPTIONAL:
            allowed.append(timer)
        else:
            forbidden.append(timer)
    
    is_compliant = len(forbidden) == 0
    
    return is_compliant, allowed, forbidden


def main() -> int:
    """Main entry point."""
    print("MODEL A TIMER COMPLIANCE CHECK")
    print("=" * 70)
    print()
    
    is_compliant, allowed, forbidden = check_compliance()
    
    print("Allowed Model A Timers:")
    if allowed:
        for timer in sorted(allowed):
            print(f"  ✅ {timer}")
    else:
        print("  (none found)")
    print()
    
    if forbidden:
        print("⚠️  FORBIDDEN TIMERS DETECTED:")
        print("-" * 70)
        for timer in sorted(forbidden):
            print(f"  ❌ {timer}")
        print()
        print("RECOMMENDATION: Disable forbidden timers:")
        print("-" * 70)
        for timer in sorted(forbidden):
            print(f"  sudo systemctl disable --now {timer}")
        print()
        print("=" * 70)
        print("❌ FAIL: Model A compliance violation")
        print()
        
        # Write warning file
        warning_path = REPORTS_OPS_DIR / "model_a_warnings.json"
        import json
        warning_data = {
            "ts": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "compliant": False,
            "forbidden_timers": forbidden,
            "allowed_timers": allowed,
        }
        with warning_path.open("w", encoding="utf-8") as f:
            json.dump(warning_data, f, indent=2)
        
        return 2
    else:
        print("=" * 70)
        print("✅ PASS: Model A compliant")
        print()
        
        # Clear warning file if it exists
        warning_path = REPORTS_OPS_DIR / "model_a_warnings.json"
        if warning_path.exists():
            warning_path.unlink()
        
        return 0


if __name__ == "__main__":
    sys.exit(main())

