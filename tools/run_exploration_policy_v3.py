#!/usr/bin/env python3
"""
CLI wrapper for Exploration Policy V3.

Usage:
    python3 -m tools.run_exploration_policy_v3

This is ADVISORY-ONLY and PAPER-SAFE.
It does not modify configs, gates, or live trading behavior.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.research.exploration_policy_v3 import compute_exploration_policy_v3


def main() -> int:
    try:
        result = compute_exploration_policy_v3()
        print("Exploration Policy V3 computed successfully")
        print(f"Results written to: reports/research/exploration_policy_v3.json")
        
        # Print summary
        symbols = result.get("symbols", {})
        if symbols:
            print("\nExploration Policy Summary:")
            print("-" * 80)
            print("Symbol   Level     Allow  Throttle   PF_7D   PF_30D  Tier    Drift        ExecQL  Hybrid")
            print("-" * 80)
            for sym in sorted(symbols.keys()):
                entry = symbols[sym]
                level = entry.get("level", "unknown")
                allow = "Y" if entry.get("allow_new_entries") else "N"
                throttle = entry.get("throttle_factor")
                pf_7d = entry.get("pf_7d")
                pf_30d = entry.get("pf_30d")
                tier = entry.get("tier") or "—"
                drift = entry.get("drift") or "—"
                execql = entry.get("exec_quality") or "—"
                hybrid = entry.get("hybrid_lane") or "—"
                
                def fmt(x: Any) -> str:
                    if x is None:
                        return "—"
                    try:
                        return f"{float(x):.3f}"
                    except Exception:
                        return str(x)
                
                print(
                    f"{sym:<8} {level:<8}  {allow:<5}  {fmt(throttle):<8}  "
                    f"{fmt(pf_7d):<6}  {fmt(pf_30d):<7}  {tier:<6}  {drift:<12}  {execql:<7}  {hybrid:<6}"
                )
        
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

