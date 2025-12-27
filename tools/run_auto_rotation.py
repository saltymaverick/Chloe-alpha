"""
Run Auto-Rotation Engine - Generate capital rotation recommendations.

This tool analyzes tiers, PF, drift, microstructure, and execution quality to suggest
overweight/underweight/hold recommendations for each symbol.
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.research.auto_rotation_engine import compute_rotation_recommendations
from engine_alpha.core.paths import REPORTS

RESEARCH_DIR = REPORTS / "research"
OUTPUT_PATH = RESEARCH_DIR / "auto_rotation_recs.json"


def main() -> int:
    """Main entry point."""
    print("AUTO ROTATION RECOMMENDATIONS")
    print("=" * 70)
    print()
    
    try:
        recs = compute_rotation_recommendations()
        
        if not recs:
            print("No rotation recommendations available.")
            print("Ensure ARE snapshot, drift report, tiers, and execution quality data exist.")
            return 0
        
        # Save results
        RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(recs, indent=2))
        print(f"✅ Auto-rotation recommendations written to: {OUTPUT_PATH}")
        print()
        
        # Print summary
        print("ROTATION RECOMMENDATIONS")
        print("-" * 70)
        
        for sym in sorted(recs.keys()):
            info = recs[sym]
            print(f"{sym}: tier={info['tier']} drift={info['drift']} exec={info['exec_label']} rotation={info['rotation']}")
            for note in info["notes"]:
                print(f"  - {note}")
        
        print()
        print("=" * 70)
        print("Note: All rotation recommendations are advisory-only.")
        print("Review before making any capital allocation changes.")
        print("=" * 70)
        
        return 0
    
    except Exception as e:
        print(f"❌ Auto-rotation engine failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

