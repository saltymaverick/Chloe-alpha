"""
Shadow Promotion Gate CLI (Phase 5b)
------------------------------------

Runs shadow promotion gate and prints candidates.
"""

from __future__ import annotations

import sys
from engine_alpha.evolve.shadow_promotion_gate import compute_promotion_candidates


def main() -> int:
    """Main entry point."""
    print("SHADOW PROMOTION GATE (Phase 5b)")
    print("=" * 80)
    print()
    
    try:
        result = compute_promotion_candidates()
        
        capital_mode = result.get("capital_mode", "unknown")
        candidates = result.get("candidates", [])
        blocked = result.get("blocked", [])
        notes = result.get("notes", [])
        
        print(f"CAPITAL MODE: {capital_mode}")
        print()
        
        if notes:
            print("NOTES")
            print("-" * 80)
            for note in notes:
                print(f"  • {note}")
            print()
        
        if candidates:
            print(f"PROMOTION CANDIDATES ({len(candidates)})")
            print("-" * 80)
            print(
                f"{'Symbol':<10} {'Composite':>10} {'PF_30D':>8} {'PF_7D':>8} "
                f"{'Trades':>8} {'MDD%':>6} {'Validity':>8}"
            )
            print("-" * 80)
            
            for cand in candidates[:20]:  # Top 20
                symbol = cand.get("symbol", "")
                composite = cand.get("composite", 0.0)
                metrics = cand.get("metrics", {})
                pf_30d = metrics.get("shadow_pf_30d")
                pf_7d = metrics.get("shadow_pf_7d")
                trades_30d = metrics.get("shadow_trades_30d", 0)
                mdd = metrics.get("max_drawdown_pct", 0.0)
                validity = metrics.get("pf_validity", 0.0)
                
                pf30_str = f"{pf_30d:.2f}" if pf_30d else "—"
                pf7_str = f"{pf_7d:.2f}" if pf_7d else "—"
                
                print(
                    f"{symbol:<10} {composite:>10.3f} {pf30_str:>8} {pf7_str:>8} "
                    f"{trades_30d:>8} {mdd:>5.2f}% {validity:>7.2f}"
                )
            print()
            
            # Show reasons for top candidate
            if candidates:
                top = candidates[0]
                print(f"TOP CANDIDATE: {top.get('symbol')}")
                print("-" * 80)
                print("Reasons OK:")
                for reason in top.get("reasons_ok", []):
                    print(f"  ✓ {reason}")
                print()
        else:
            print("NO PROMOTION CANDIDATES")
            print("-" * 80)
            print("No symbols meet all promotion criteria.")
            print()
        
        if blocked:
            print(f"BLOCKED SYMBOLS (showing top 10)")
            print("-" * 80)
            for entry in blocked[:10]:
                symbol = entry.get("symbol", "")
                fails = entry.get("fails", [])
                print(f"{symbol}:")
                for fail in fails[:3]:  # Show first 3 fails
                    print(f"  ✗ {fail}")
            print()
        
        print("=" * 80)
        print(f"Candidates written to: reports/evolver/shadow_promotion_candidates.json")
        print(f"History appended to: reports/evolver/shadow_promotion_history.jsonl")
        
        return 0
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

