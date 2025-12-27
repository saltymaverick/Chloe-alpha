#!/usr/bin/env python3
"""
Volume Imbalance Scan CLI Tool - Runs volume imbalance analysis for all symbols.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.research.advanced_structure.volume_imbalance import run_volume_imbalance_scan


def main() -> int:
    """Main entry point."""
    try:
        results = run_volume_imbalance_scan()
        
        # Print summary table
        print("VOLUME IMBALANCE SCAN")
        print("=" * 70)
        print(f"{'Symbol':<10} {'AvgImb':<8} {'Strength':<9} {'CVDTrend':<9} {'Absorb':<7} {'Exhaust':<8}")
        print("-" * 70)
        
        for sym in sorted(results.keys()):
            info = results[sym]
            avg_imb = info.get("avg_imbalance")
            strength = info.get("imbalance_strength", 0.0)
            cvd = info.get("cvd_trend", "neutral")
            ab = info.get("absorption_count", 0)
            ex = info.get("exhaustion_count", 0)
            
            if avg_imb is None:
                avg_str = "  —  "
            else:
                avg_str = f"{avg_imb:6.2f}"
            
            print(f"{sym:<10} {avg_str} {strength:>8.2f} {cvd:<9} {ab:>6} {ex:>8}")
        
        print()
        return 0
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

