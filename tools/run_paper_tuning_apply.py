"""
Run Paper Tuning Apply - Apply tuner v4 recommendations as paper-only overrides.

This tool reads tuner output, tiers, and rotation recommendations, then applies
small, safe tuning adjustments for Tier1 symbols only, storing them in
config/paper_tuning_overrides.json for use in PAPER mode trading.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.tuning.paper_tuning_overrides import apply_tuner_recommendations
from engine_alpha.core.regime_filters import load_tiers
from engine_alpha.core.paths import REPORTS

TUNER_PATH = REPORTS / "gpt" / "tuner_output.json"
ROTATION_PATH = REPORTS / "research" / "auto_rotation_recs.json"


def main() -> int:
    """Main entry point."""
    print("PAPER TUNING APPLY")
    print("=" * 70)
    print()
    
    # Check if tuner output exists
    if not TUNER_PATH.exists():
        print("⚠️  No tuner_output.json found; exiting.")
        print(f"   Expected at: {TUNER_PATH}")
        return 0
    
    try:
        # Load tuner output
        tuner_output = json.loads(TUNER_PATH.read_text())
        
        # Load tiers
        tiers = load_tiers()
        
        # Load rotation recommendations
        rotation_recs = {}
        if ROTATION_PATH.exists():
            rotation_data = json.loads(ROTATION_PATH.read_text())
            # Handle both formats: direct dict or wrapped
            if isinstance(rotation_data, dict):
                rotation_recs = rotation_data
        
        # Apply recommendations
        overrides = apply_tuner_recommendations(tuner_output, tiers, rotation_recs)
        
        if not overrides:
            print("No overrides applied.")
            print("Ensure:")
            print("  - Tuner proposals exist for Tier1 symbols")
            print("  - Rotation recommendations show 'overweight' or 'hold'")
            print("  - Deltas are within safe bounds [-0.02, 0.02] and [-1, 1]")
            print()
            return 0
        
        # Print summary
        print("APPLIED OVERRIDES")
        print("-" * 70)
        
        for sym in sorted(overrides.keys()):
            info = overrides[sym]
            conf_delta = info.get("conf_min_delta", 0.0)
            cap_delta = info.get("exploration_cap_delta", 0)
            notes = info.get("notes", [])
            
            print(f"{sym}:")
            print(f"  conf_min_delta={conf_delta:+.3f}")
            print(f"  exploration_cap_delta={cap_delta:+d}")
            if notes:
                print(f"  Last note: {notes[-1]}")
            print()
        
        print("=" * 70)
        print("Note: Overrides are PAPER-ONLY and stored in config/paper_tuning_overrides.json")
        print("LIVE mode will ignore these overrides completely.")
        print("=" * 70)
        
        return 0
    
    except Exception as e:
        print(f"❌ Paper tuning apply failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

