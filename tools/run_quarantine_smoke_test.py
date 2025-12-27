#!/usr/bin/env python3
"""
Quarantine Smoke Test (Phase 5g)
----------------------------------

Runs a smoke test to verify quarantine integration.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.core.paths import REPORTS


def main() -> int:
    """Run smoke test."""
    print("QUARANTINE SMOKE TEST (Phase 5g)")
    print("=" * 70)
    print()
    
    # Check quarantine.json exists
    quarantine_path = REPORTS / "risk" / "quarantine.json"
    if not quarantine_path.exists():
        print("ERROR: quarantine.json not found")
        print("  Run: python3 -m tools.run_quarantine")
        return 1
    
    try:
        with quarantine_path.open("r", encoding="utf-8") as f:
            quarantine = json.load(f)
    except Exception as e:
        print(f"ERROR: Failed to load quarantine.json: {e}")
        return 1
    
    print("✓ quarantine.json exists and is valid JSON")
    
    # Check capital_plan_quarantine.json exists (if quarantine enabled)
    if quarantine.get("enabled", False) and quarantine.get("weight_adjustments"):
        overlay_path = REPORTS / "risk" / "capital_plan_quarantine.json"
        if not overlay_path.exists():
            print("WARNING: capital_plan_quarantine.json not found")
            print("  Run: python3 -m tools.run_quarantine")
        else:
            print("✓ capital_plan_quarantine.json exists")
    
    # Print top quarantined symbols
    quarantined = quarantine.get("quarantined", [])
    if quarantined:
        print()
        print("Top quarantined symbols:")
        for q in quarantined[:2]:
            symbol = q["symbol"]
            contrib = q["contribution_pct"]
            print(f"  {symbol}: {contrib:.1f}% contribution")
    else:
        print()
        print("No symbols quarantined (quarantine may be disabled or no loss contributors)")
    
    print()
    print("=" * 70)
    print("✓ Smoke test passed")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

