#!/usr/bin/env python3
"""
Debug tool for Micro Core Ramp allowed symbols.

Shows:
- recovery_ramp_v2.allowed_symbols
- exploration policy allowset (and which file was used, or fallback)
- intersection result
- final reason if empty

Read-only; does not trade.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.core.paths import REPORTS
from engine_alpha.loop.micro_core_ramp import _load_exploration_allowset, _load_json

RECOVERY_RAMP_V2_PATH = REPORTS / "risk" / "recovery_ramp_v2.json"


def main() -> int:
    """Print debug info for micro-core allowed symbols."""
    print("=" * 80)
    print("MICRO CORE RAMP - ALLOWED SYMBOLS DEBUG")
    print("=" * 80)
    print()
    
    # Load recovery_ramp_v2
    recovery_ramp_v2 = _load_json(RECOVERY_RAMP_V2_PATH)
    ramp_allowed = recovery_ramp_v2.get("decision", {}).get("allowed_symbols", [])
    ramp_reason = recovery_ramp_v2.get("decision", {}).get("reason", "unknown")
    
    print(f"Recovery Ramp V2:")
    print(f"  Allowed symbols: {ramp_allowed}")
    print(f"  Reason: {ramp_reason}")
    print()
    
    # Load exploration policy
    policy_allowed_set, policy_file_used = _load_exploration_allowset()
    
    print(f"Exploration Policy:")
    if policy_file_used:
        print(f"  File used: {policy_file_used}")
        print(f"  Allowed symbols: {sorted(policy_allowed_set)}")
    else:
        print(f"  File used: (none found - fallback to allow all)")
        print(f"  Allowed symbols: (fallback - all symbols from recovery_ramp_v2)")
    print()
    
    # Compute intersection
    if policy_file_used:
        intersection = [s for s in ramp_allowed if s in policy_allowed_set]
    else:
        # Fallback: return recovery_ramp_v2 allowed symbols
        intersection = ramp_allowed
    
    print(f"Intersection Result:")
    print(f"  Allowed symbols: {intersection}")
    print()
    
    if not intersection:
        print(f"Final Reason: no_allowed_symbols")
        print()
        print("Diagnosis:")
        if not ramp_allowed:
            print(f"  - Recovery Ramp V2 has no allowed symbols (reason: {ramp_reason})")
        elif policy_file_used and not policy_allowed_set:
            print(f"  - Exploration policy file exists but has no allowed symbols")
        elif not policy_file_used:
            print(f"  - Exploration policy file not found (using fallback)")
        else:
            print(f"  - Intersection is empty (no overlap between ramp and policy)")
    else:
        print(f"Final Result: {len(intersection)} symbol(s) allowed")
    
    print()
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())

