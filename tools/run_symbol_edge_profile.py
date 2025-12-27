"""
Run Symbol Edge Profile - Generate per-symbol edge profiles and archetypes.

This tool computes hard-quant edge profiles for each symbol, classifying them
into archetypes (trend_monster, fragile, mean_reverter, etc.) based on PF,
drift, microstructure, execution quality, and self-eval history.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.research.symbol_edge_profiler import build_symbol_edge_profile
from engine_alpha.core.paths import REPORTS

PROFILE_PATH = REPORTS / "research" / "symbol_edge_profile.json"


def main() -> int:
    """Main entry point."""
    print("SYMBOL EDGE PROFILER")
    print("=" * 70)
    print()
    
    try:
        profiles = build_symbol_edge_profile()
        
        if not profiles:
            print("⚠️  No symbol profiles generated (missing inputs).")
            print()
            print("Ensure the following files exist:")
            print("  - reports/research/are_snapshot.json")
            print("  - reports/research/drift_report.json")
            print("  - reports/research/microstructure_snapshot_15m.json")
            print("  - reports/research/execution_quality.json")
            print("  - reports/gpt/quality_scores.json")
            print("  - reports/gpt/reflection_output.json")
            return 0
        
        print("Symbol   Tier    Archetype               ShortPF   LongPF   Drift         ExecQL  Qual")
        print("-" * 90)
        
        for sym in sorted(profiles.keys()):
            p = profiles[sym]
            tier = p.get("tier", "unknown")
            archetype = p.get("archetype", "unknown")
            short_pf = p.get("short_pf", "—")
            long_pf = p.get("long_pf", "—")
            drift = p.get("drift", "unknown")
            exec_label = p.get("exec_label", "unknown")
            qual_score = p.get("quality_score", "—")
            
            # Format PF values
            short_str = f"{short_pf:.2f}" if isinstance(short_pf, (int, float)) else str(short_pf)
            long_str = f"{long_pf:.2f}" if isinstance(long_pf, (int, float)) else str(long_pf)
            qual_str = f"{qual_score:.0f}" if isinstance(qual_score, (int, float)) else str(qual_score)
            
            print(f"{sym:<8} {tier:<6} {archetype:<22} {short_str:>7} {long_str:>8} {drift:<12} {exec_label:<8} {qual_str:>4}")
        
        print()
        print("=" * 70)
        print(f"✅ Profiles written to: {PROFILE_PATH}")
        print()
        print("Note: Profiles are used by GPT Tuner v4 for symbol-specific tuning.")
        print("All tuning remains advisory-only and PAPER-only.")
        print("=" * 70)
        
        return 0
    
    except Exception as e:
        print(f"❌ Symbol edge profiler failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

