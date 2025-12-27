#!/usr/bin/env python3
"""
CLI tool to run meta-strategy reflection.

Usage:
    python3 -m tools.run_meta_strategy_reflection
    
    # View last reflection
    tail -n 1 reports/research/meta_strategy_reflections.jsonl | jq .
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

from engine_alpha.reflect.meta_strategy_reflection import run_meta_strategy_reflection

ROOT_DIR = Path(__file__).resolve().parents[1]
REFLECTIONS_LOG = ROOT_DIR / "reports" / "research" / "meta_strategy_reflections.jsonl"


def main():
    """Run meta-strategy reflection and display results."""
    print("Running meta-strategy reflection...")
    print("=" * 60)
    
    try:
        log_path = run_meta_strategy_reflection()
        
        # Read and display the last reflection
        if log_path.exists():
            with log_path.open("r") as f:
                lines = [line.strip() for line in f if line.strip()]
            
            if lines:
                last_reflection = json.loads(lines[-1])
                print("\n✅ Reflection complete!")
                print(f"\nTimestamp: {last_reflection.get('ts', 'N/A')}")
                
                reflection = last_reflection.get("reflection", {})
                if isinstance(reflection, dict):
                    if "summary" in reflection:
                        print(f"\nSummary:\n{reflection['summary']}")
                    
                    if "patterns" in reflection:
                        print(f"\nPatterns Identified: {len(reflection['patterns'])}")
                        for i, pattern in enumerate(reflection["patterns"][:3], 1):
                            print(f"\n  {i}. {pattern.get('description', 'N/A')}")
                            print(f"     Evidence: {pattern.get('evidence', 'N/A')}")
                    
                    if "strategic_ideas" in reflection:
                        print(f"\nStrategic Ideas: {len(reflection['strategic_ideas'])}")
                        for i, idea in enumerate(reflection["strategic_ideas"][:3], 1):
                            print(f"\n  {i}. {idea.get('name', 'N/A')} [{idea.get('priority', 'N/A')}]")
                            print(f"     {idea.get('intuition', 'N/A')}")
                else:
                    print(f"\nReflection (raw):\n{reflection}")
                
                print(f"\n📄 Full reflection saved to: {log_path}")
                print(f"   View with: tail -n 1 {log_path} | jq .")
            else:
                print("\n⚠️  No reflections found in log file")
        else:
            print(f"\n⚠️  Log file not created: {log_path}")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())


