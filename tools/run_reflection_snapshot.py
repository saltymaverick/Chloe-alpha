#!/usr/bin/env python3
"""
Reflection Snapshot Writer
---------------------------

Writes reports/reflection_snapshot.json with current reflection state.
This ensures the check-in script always has fresh reflection data.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.safety_governor import evaluate_safety
from engine_alpha.reflect.gpt_reflection import reflect_on_batch


def compute_reflection_snapshot() -> dict[str, any]:
    """
    Compute reflection snapshot from current state.
    
    Returns:
        Dict with timestamp, safety, reflection, and confidence data
    """
    now = datetime.now(timezone.utc)
    
    # Evaluate safety
    safe_mode = evaluate_safety()
    
    # Run reflection on batch
    reflection = reflect_on_batch()
    
    # Load confidence snapshot if available
    confidence_data = {}
    conf_path = REPORTS / "confidence_snapshot.json"
    if conf_path.exists():
        try:
            with conf_path.open("r", encoding="utf-8") as f:
                confidence_data = json.load(f)
        except Exception:
            pass
    
    snapshot = {
        "timestamp": now.isoformat(),
        "safety": {
            "safe_mode": safe_mode,
        },
        "reflection": reflection,
        "confidence": {
            "confidence_overall": confidence_data.get("confidence_overall"),
            "regime": confidence_data.get("regime", "unknown"),
            "source": confidence_data.get("source", "none"),
        },
        "generated_at": now.isoformat(),
    }
    
    return snapshot


def main() -> int:
    """Main entry point."""
    result = compute_reflection_snapshot()
    
    # Write to reports/reflection_snapshot.json
    output_path = REPORTS / "reflection_snapshot.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    
    conf_str = f"{result.get('confidence', {}).get('confidence_overall'):.3f}" if result.get('confidence', {}).get('confidence_overall') is not None else "None"
    print(f"Reflection snapshot: safe_mode={result.get('safety', {}).get('safe_mode')}, confidence={conf_str}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

