"""
Run Tuning Advisor - Generate per-symbol tuning recommendations.

This tool synthesizes all research intelligence (edge profiles, self-eval, rotation, trade counts)
into clear per-symbol recommendations: relax, tighten, freeze, or observe.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.research.tuning_advisor import build_tuning_advisor
from engine_alpha.core.paths import REPORTS

ADVISOR_PATH = REPORTS / "research" / "tuning_advisor.json"


def main() -> int:
    """Main entry point."""
    print("PER-SYMBOL TUNING ADVISOR")
    print("=" * 70)
    print()
    
    try:
        advisor = build_tuning_advisor()
        
        if not advisor:
            print("⚠️  No advisor data generated; check inputs.")
            print()
            print("Ensure the following files exist:")
            print("  - reports/research/symbol_edge_profile.json")
            print("  - reports/research/tuning_self_eval.json")
            print("  - reports/research/auto_rotation_recs.json")
            return 0
        
        print("Symbol   Rec       ExplTr  Tier   Archetype           ExecQL    Drift")
        print("-" * 90)
        
        for sym in sorted(advisor.keys()):
            info = advisor[sym]
            rec = info.get("recommendation", "observe")
            expl = info.get("samples", {}).get("exploration_closes", 0)
            tier = info.get("tier", "unknown")
            archetype = info.get("archetype", "unknown")
            exec_label = info.get("exec_label", "unknown")
            drift = info.get("drift", "unknown")
            
            print(f"{sym:<8} {rec:<8} {expl:<7} {tier:<6} {archetype:<18} {exec_label:<8} {drift:<12}")
        
        print()
        print("=" * 70)
        print(f"✅ Detailed advisor data written to: {ADVISOR_PATH}")
        print()
        print("Recommendations:")
        print("  - relax: Allow slightly looser tuning (strong symbols with good execution)")
        print("  - tighten: Keep tightening or restrict trading (weak symbols with hostile execution)")
        print("  - freeze: Stop tuning (symbols where tuning has been harmful)")
        print("  - observe: Keep watching and learning (under-sampled or mixed signals)")
        print()
        print("Note: All recommendations are advisory-only and respect sample-size gating.")
        print("No configs or live trading logic are changed.")
        print("=" * 70)
        
        return 0
    
    except Exception as e:
        print(f"❌ Tuning advisor failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

