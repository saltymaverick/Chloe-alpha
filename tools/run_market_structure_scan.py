#!/usr/bin/env python3
"""
Market Structure Scan CLI Tool - Runs market structure analysis for all symbols.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.research.market_structure import run_market_structure_scan


def main() -> int:
    """Main entry point."""
    try:
        results = run_market_structure_scan()
        print("MARKET STRUCTURE SCAN COMPLETE")
        print("=" * 70)
        
        # Print summary
        for symbol in sorted(results.keys()):
            info = results[symbol]
            struct = info.get("structure_1h", "neutral")
            conf = info.get("structure_confidence")
            eqh = "Y" if info.get("equal_highs_1h") else "N"
            eql = "Y" if info.get("equal_lows_1h") else "N"
            ob = info.get("order_block_1h", "none")
            fvg = info.get("fvg_1h", "none")
            
            conf_str = f"{conf:.2f}" if conf is not None else " — "
            print(f"{symbol}:")
            print(f"  - 1h structure: {struct} (conf={conf_str})")
            print(f"  - EqH: {eqh}  EqL: {eql}")
            print(f"  - OB: {ob}")
            print(f"  - FVG: {fvg}")
            if info.get("choch_recent"):
                choch_q = info.get("choch_quality", 0.0)
                print(f"  - CHoCH: detected (quality={choch_q:.2f})")
            print()
        
        print("See reports/research/market_structure.json")
        return 0
    except Exception as e:
        print("Market Structure Scan FAILED:", e)
        import traceback
        traceback.print_exc()
        return 0


if __name__ == "__main__":
    sys.exit(main())

