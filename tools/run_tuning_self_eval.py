"""
Run Tuning Self-Evaluation - Evaluate Chloe's tuning decisions.

This tool analyzes tuning proposals and compares actual trade performance
before vs after each tuning event to determine if tuning helped, hurt, or was inconclusive.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.research.tuning_self_eval import run_tuning_self_eval
from engine_alpha.core.paths import REPORTS

SELF_EVAL_PATH = REPORTS / "research" / "tuning_self_eval.json"


def main() -> int:
    """Main entry point."""
    print("TUNING SELF-EVALUATION")
    print("=" * 70)
    print()
    
    try:
        results = run_tuning_self_eval(window_size=5)
        summary = results.get("summary", {})
        
        if not summary:
            note = results.get("note", "No tuning events or insufficient trade data.")
            print(f"⚠️  {note}")
            print()
            print("=" * 70)
            print("Note: Tuning self-evaluation needs:")
            print("  - Tuning events in reports/gpt/tuning_reason_log.jsonl")
            print("  - Trade data in reports/trades.jsonl")
            print("  - At least 5 trades before and after each tuning event")
            print("=" * 70)
            return 0
        
        print("Per-symbol tuning outcome summary:")
        print()
        print("Symbol   improved  degraded  inconclusive")
        print("-" * 50)
        
        for sym in sorted(summary.keys()):
            s = summary[sym]
            improved = s.get("improved", 0)
            degraded = s.get("degraded", 0)
            inconclusive = s.get("inconclusive", 0)
            print(f"{sym:<8} {improved:>8} {degraded:>9} {inconclusive:>13}")
        
        print()
        print("=" * 70)
        print(f"Detailed results written to: {SELF_EVAL_PATH}")
        print()
        print("Note: All evaluations are advisory-only.")
        print("No configs or trading behavior are changed.")
        print("=" * 70)
        
        return 0
    
    except Exception as e:
        print(f"❌ Tuning self-evaluation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

