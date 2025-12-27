"""
Run Promotion Engine - Evaluate variant strategies and identify promotion candidates.

This tool runs the Promotion Engine to evaluate all mutation shadow strategies
against the base strategy and identify which variants outperform the parent.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.evolve.promotion_engine import run_promotion_engine, PROMOTION_PATH


def main() -> int:
    """Main entry point."""
    print("PROMOTION ENGINE")
    print("=" * 70)
    print()
    
    try:
        promotions = run_promotion_engine()
        
        print("PROMOTION ENGINE RESULTS")
        print("-" * 70)
        
        total_candidates = 0
        for symbol, candidates in promotions.items():
            print(f"{symbol}: {len(candidates)} candidate(s)")
            total_candidates += len(candidates)
            
            for candidate in candidates:
                variant_id = candidate.get("variant_id", "unknown")
                stats = candidate.get("stats", {})
                variant_pf = stats.get("variant_exp_pf")
                parent_pf = stats.get("parent_exp_pf")
                improvement = stats.get("pf_improvement")
                
                pf_str = f"{variant_pf:.2f}" if variant_pf != float("inf") else "inf"
                parent_pf_str = f"{parent_pf:.2f}" if parent_pf != float("inf") else "inf"
                
                print(f"  → {variant_id}: PF={pf_str} (parent={parent_pf_str}, improvement={improvement})")
                print(f"    Recommendation: {candidate.get('recommendation', 'N/A')}")
        
        print()
        print(f"Total candidates: {total_candidates}")
        print()
        print(f"Full details written to: {PROMOTION_PATH}")
        print("=" * 70)
        print()
        print("Note: All evaluations are advisory-only.")
        print("To apply a promotion in paper mode, use:")
        print("  python3 -m tools.apply_promotion --symbol SYMBOL --variant VARIANT_ID")
        print("=" * 70)
        
        return 0
    
    except Exception as e:
        print(f"❌ Promotion engine failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

