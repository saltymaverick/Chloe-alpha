"""
Run Normal Lane Optimizer - Identify symbols where normal lane outperforms exploration.

This tool flags symbols where the normal lane significantly outperforms the exploration lane,
indicating potential execution optimization opportunities.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.research.normal_lane_optimizer import analyze_normal_lane
from engine_alpha.core.paths import REPORTS

RESEARCH_DIR = REPORTS / "research"
OUTPUT_PATH = RESEARCH_DIR / "normal_lane_opportunities.json"


def main() -> int:
    """Main entry point."""
    print("NORMAL LANE OPTIMIZER")
    print("=" * 70)
    print()
    
    try:
        results = analyze_normal_lane()
        
        if not results:
            print("No symbols where normal lane clearly outperforms exploration.")
            print()
            print("=" * 70)
            print("Note: Normal lane optimizer is advisory-only.")
            print("=" * 70)
            return 0
        
        # Save results
        RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(results, indent=2))
        print(f"✅ Normal lane opportunities written to: {OUTPUT_PATH}")
        print()
        
        # Print summary
        print("NORMAL LANE OPPORTUNITIES")
        print("-" * 70)
        
        for sym in sorted(results.keys()):
            info = results[sym]
            exp_pf = info['exp_pf']
            norm_pf = info['norm_pf']
            ratio = info['ratio']
            print(f"{sym}:")
            # Format ratio safely
            if ratio is not None:
                ratio_str = f"{ratio:.2f}"
            else:
                ratio_str = "nan"
            print(f"  exp_pf={exp_pf:.2f} norm_pf={norm_pf:.2f} ratio={ratio_str}")
            print(f"  note: {info['note']}")
            print()
        
        print("=" * 70)
        print("Note: Normal lane optimizer is advisory-only.")
        print("Investigate exit rules, position sizing, and confidence gating for these symbols.")
        print("=" * 70)
        
        return 0
    
    except Exception as e:
        print(f"❌ Normal lane optimizer failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

