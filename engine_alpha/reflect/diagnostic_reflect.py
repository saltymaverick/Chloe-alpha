#!/usr/bin/env python3
"""
Reflection Diagnostic - Phase 4
Tests reflection, safety, and GPT operator.
"""

import json
import sys
from pathlib import Path

# Add /root/engine_alpha to path for imports
# File is at: /root/engine_alpha/engine_alpha/reflect/diagnostic_reflect.py
# Need to add /root/engine_alpha to path (parent of engine_alpha package)
sys.path.insert(0, "/root/engine_alpha")

from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.safety_governor import evaluate_safety
from engine_alpha.reflect.gpt_reflection import reflect_on_batch
from engine_alpha.reflect.gpt_operator import interpret_command
from engine_alpha.signals.news_tone_fetcher import fetch_news_tone


def main():
    """Run diagnostic checks on reflection system."""
    print("Alpha Chloe - Reflection Diagnostic (Phase 4)")
    print("=" * 50)
    
    try:
        # Evaluate safety
        print("\n1. Evaluating safety...")
        safe_mode = evaluate_safety()
        print(f"   Safe mode: {'ACTIVE' if safe_mode else 'INACTIVE'}")
        
        # Run reflection
        print("\n2. Running reflection on batch...")
        reflection = reflect_on_batch()
        print(f"   PF: {reflection.get('pf', 'N/A'):.4f}")
        print(f"   PF Delta: {reflection.get('pf_delta', 0):.4f}")
        print(f"   Insight: {reflection.get('insight', 'N/A')}")
        
        # Test GPT operator commands
        print("\n3. Testing GPT operator...")
        commands = [
            "show pf",
            "safe mode status",
            "reflect now",
            "why did we exit",
        ]
        
        for cmd in commands:
            result = interpret_command(cmd)
            print(f"   Command: '{cmd}'")
            print(f"   Action: {result.get('action')}")
            print(f"   Output: {result.get('output')}")
        
        # Fetch news tone
        print("\n4. Fetching news tone...")
        news_tone = fetch_news_tone()
        print(f"   Tone: {news_tone.get('tone', 'N/A'):.4f}")
        print(f"   Rationale: {news_tone.get('rationale', 'N/A')}")
        
        # Write reflection snapshot
        snapshot = {
            "timestamp": reflection.get("ts"),
            "safety": {
                "safe_mode": safe_mode,
            },
            "reflection": reflection,
            "news_tone": news_tone,
        }
        
        snapshot_path = REPORTS / "reflection_snapshot.json"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        with open(snapshot_path, "w") as f:
            json.dump(snapshot, f, indent=2)
        
        print(f"\n✅ Reflection snapshot written to: {snapshot_path}")
        print("\n✅ Diagnostic complete")
        return 0
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

