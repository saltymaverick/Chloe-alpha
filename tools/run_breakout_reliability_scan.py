"""
Run Breakout Reliability Scan - Compute composite breakout reliability scores.

This tool combines signals from market structure, microstructure, liquidity sweeps,
and volume imbalance to produce a breakout reliability score per symbol.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.research.breakout_reliability import run_breakout_reliability_scan


def main() -> int:
    """Main entry point."""
    print("BREAKOUT RELIABILITY SCAN")
    print("=" * 70)
    print()
    
    try:
        results = run_breakout_reliability_scan()
        
        if not results:
            print("⚠️  No breakout reliability data computed.")
            print("   Ensure required research files exist:")
            print("   - reports/research/market_structure.json")
            print("   - reports/research/microstructure_snapshot_15m.json")
            print("   - reports/research/liquidity_sweeps.json")
            print("   - reports/research/volume_imbalance.json")
            return 0
        
        # Print ranked list
        print("BREAKOUT RELIABILITY SCAN")
        print("-" * 70)
        
        # Sort by score descending
        sorted_results = sorted(
            results.items(),
            key=lambda x: x[1].get("score", 0.0),
            reverse=True
        )
        
        for symbol, data in sorted_results:
            score = data.get("score", 0.0)
            label = data.get("label", "unknown")
            print(f"{symbol}: score={score:.2f} label={label}")
        
        print()
        print("=" * 70)
        print(f"✅ Breakout reliability scan complete. {len(results)} symbols analyzed.")
        print(f"   Results written to: reports/research/breakout_reliability.json")
        print("=" * 70)
        
        return 0
    
    except Exception as e:
        print(f"❌ Breakout reliability scan failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
