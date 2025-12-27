"""
Run Variant Cycle - Execute one step of all active variant strategies.

This tool runs the Strategy Variant Runner for one cycle, simulating
all mutation strategies in parallel without affecting the main trading loop.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.variant.variant_runner import run_variant_cycle, load_active_variants


def main() -> int:
    """Main entry point."""
    print("VARIANT CYCLE")
    print("=" * 70)
    print()
    
    # Load variants
    variants = load_active_variants()
    if not variants:
        print("⚠️  No active variants found.")
        print("   Create mutation shadows first: python3 -m tools.create_mutation_shadows")
        return 0
    
    print(f"Loaded: {len(variants)} variants")
    print()
    
    # Run cycle
    try:
        result = run_variant_cycle(timeframe="15m")
        
        executed = result["variants_executed"]
        errors = result.get("errors", [])
        
        if errors:
            print("⚠️  Errors during execution:")
            for error in errors:
                print(f"   {error}")
            print()
        
        # Print per-variant summary
        print("VARIANT RESULTS")
        print("-" * 70)
        
        from engine_alpha.variant.variant_runner import VARIANT_DIR
        for variant in variants:
            variant_id = variant["id"]
            symbol = variant["symbol"]
            
            summary_path = VARIANT_DIR / f"{variant_id}_summary.json"
            if summary_path.exists():
                import json
                try:
                    summary = json.loads(summary_path.read_text())
                    stats = summary.get("stats", {})
                    exp_pf = stats.get("exp_pf")
                    exp_trades = stats.get("exp_trades", 0)
                    
                    if exp_pf is not None:
                        if exp_pf == float("inf"):
                            pf_str = "inf"
                        else:
                            pf_str = f"{exp_pf:.2f}"
                    else:
                        pf_str = "N/A"
                    
                    print(f"{variant_id}: step OK, PF={pf_str}, trades={exp_trades}")
                except Exception:
                    print(f"{variant_id}: step OK (summary read failed)")
            else:
                print(f"{variant_id}: step OK (no summary yet)")
        
        print()
        print("=" * 70)
        print(f"All variants updated ({executed}/{len(variants)} executed)")
        print("=" * 70)
        
        return 0
    
    except Exception as e:
        print(f"❌ Variant cycle failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

