"""
Run SCM State - Generate Sample Collection Mode state for all symbols.

This tool computes per-symbol SCM levels (off/low/normal/high) based on
tier, PF, drift, execution quality, sample size, tuning advisor, and self-eval.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.research.scm_controller import compute_scm_state
from engine_alpha.core.paths import REPORTS

SCM_STATE_PATH = REPORTS / "research" / "scm_state.json"


def main() -> int:
    """Main entry point."""
    print("SAMPLE COLLECTION MODE (SCM) STATE")
    print("=" * 70)
    print()
    
    try:
        state = compute_scm_state()
        
        if not state:
            print("⚠️  No SCM state available; check inputs.")
            print()
            print("Ensure the following files exist:")
            print("  - reports/research/symbol_edge_profile.json")
            print("  - reports/research/tuning_advisor.json")
            print("  - reports/research/tuning_self_eval.json")
            return 0
        
        print("Symbol   Level    ExplTr  Tier   ExecQL    Drift         Archetype")
        print("-" * 90)
        
        for sym in sorted(state.keys()):
            info = state[sym]
            level = info.get("scm_level", "normal")
            expl = info.get("samples", {}).get("exploration_closes", 0)
            tier = info.get("tier", "unknown")
            exec_label = info.get("exec_label", "unknown")
            drift = info.get("drift", "unknown")
            archetype = info.get("archetype", "unknown")
            
            print(f"{sym:<8} {level:<7} {expl:<7} {tier:<6} {exec_label:<8} {drift:<12} {archetype:<}")
        
        print()
        print("=" * 70)
        print(f"✅ Detailed SCM state written to: {SCM_STATE_PATH}")
        print()
        print("SCM Levels:")
        print("  - off: Sampling completed or symbol should not be sampled")
        print("  - low: Reduced sampling (enough data or degrading)")
        print("  - normal: Standard sampling intensity")
        print("  - high: Increased sampling (under-sampled or strong symbol)")
        print()
        print("Note: SCM only affects exploration lane in PAPER mode.")
        print("All effects are advisory-only and respect existing risk gates.")
        print("=" * 70)
        
        return 0
    
    except Exception as e:
        print(f"❌ SCM state failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

