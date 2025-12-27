#!/usr/bin/env python3
"""
Confidence Snapshot Writer
--------------------------

Writes reports/confidence_snapshot.json with confidence_overall, regime, and required fields.
This ensures the reflection packet always has confidence data.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.core.paths import REPORTS


def compute_confidence_snapshot() -> dict[str, any]:
    """
    Compute confidence snapshot from council_snapshot.json or confidence.json.
    
    Returns:
        Dict with confidence_overall, regime, and required fields
    """
    # Try council_snapshot.json first (most complete)
    council_path = REPORTS / "council_snapshot.json"
    if council_path.exists():
        try:
            with council_path.open("r", encoding="utf-8") as f:
                council_data = json.load(f)
            
            final = council_data.get("final", {})
            confidence_overall = final.get("conf") or final.get("confidence")
            regime = council_data.get("regime", "unknown")
            
            if confidence_overall is not None:
                return {
                    "confidence_overall": float(confidence_overall),
                    "regime": regime,
                    "source": "council_snapshot",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
        except Exception:
            pass
    
    # Fallback to confidence.json
    confidence_path = REPORTS / "confidence.json"
    confidence_overall = None
    regime = "unknown"
    source = "none"
    
    if confidence_path.exists():
        try:
            with confidence_path.open("r", encoding="utf-8") as f:
                conf_data = json.load(f)
            
            confidence_overall = conf_data.get("confidence") or conf_data.get("conf")
            regime = conf_data.get("regime", "unknown")
            source = "confidence.json"
        except Exception:
            pass
    
    # Quality-of-life: Pull regime from regime_snapshot.json if available (more accurate)
    regime_snapshot_path = REPORTS / "regime_snapshot.json"
    if regime_snapshot_path.exists():
        try:
            with regime_snapshot_path.open("r", encoding="utf-8") as f:
                regime_data = json.load(f)
            snapshot_regime = regime_data.get("regime")
            if snapshot_regime and snapshot_regime != "unknown":
                regime = snapshot_regime
                if source == "none":
                    source = "regime_snapshot.json"
                else:
                    source = f"{source}+regime_snapshot.json"
        except Exception:
            pass
    
    # Return result
    result = {
        "confidence_overall": float(confidence_overall) if confidence_overall is not None else None,
        "regime": regime,
        "source": source,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    
    return result


def main() -> int:
    """Main entry point."""
    result = compute_confidence_snapshot()
    
    # Write to reports/confidence_snapshot.json
    output_path = REPORTS / "confidence_snapshot.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    
    conf_str = f"{result.get('confidence_overall'):.3f}" if result.get("confidence_overall") is not None else "None"
    print(f"Confidence snapshot: overall={conf_str}, regime={result.get('regime')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

