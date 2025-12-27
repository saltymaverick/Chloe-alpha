#!/usr/bin/env python3
"""
CLI wrapper for PF Time-Series Engine.

Usage:
    python3 -m tools.run_pf_timeseries

This is ADVISORY-ONLY and PAPER-SAFE.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.research.pf_timeseries import compute_pf_timeseries


def main() -> int:
    try:
        result = compute_pf_timeseries()
        print("PF Time-Series computed successfully")
        print(f"Results written to: reports/pf/pf_timeseries.json")
        
        # Print summary
        global_stats = result.get("global", {})
        if global_stats:
            print("\nGlobal PF Summary:")
            print("-" * 50)
            for window in ["1d", "7d", "30d", "90d"]:
                stats = global_stats.get(window, {})
                pf = stats.get("pf")
                trades = stats.get("trades", 0)
                if pf is not None:
                    print(f"PF_{window.upper():<4}: {pf:.3f} ({trades} trades)")
                elif trades > 0:
                    print(f"PF_{window.upper():<4}: ∞ (no losses, {trades} trades)")
                else:
                    print(f"PF_{window.upper():<4}: — (no data)")
        
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

