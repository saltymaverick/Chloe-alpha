"""
Run Evolver Cycle - Orchestrate a single Evolver pass.

This tool evaluates all symbols for promotion/demotion and writes advisory output.
"""

from __future__ import annotations

import json
from pathlib import Path
from engine_alpha.evolve.evolver_core import load_inputs, evolve_all_symbols

ROOT = Path(__file__).resolve().parents[1]
EVOLVER_OUTPUT_DIR = ROOT / "reports" / "evolver"
EVOLVER_OUTPUT_PATH = EVOLVER_OUTPUT_DIR / "evolver_output.json"


def main() -> None:
    """Main entry point."""
    print("EVOLVER CYCLE")
    print("=" * 70)
    print()
    
    # Load inputs
    print("Loading inputs...")
    metrics_dict = load_inputs()
    
    if not metrics_dict:
        print("⚠️  No symbol metrics found.")
        print("   Run reflection cycle first: python3 -m tools.run_reflection_cycle")
        return
    
    print(f"   Loaded metrics for {len(metrics_dict)} symbols")
    print()
    
    # Evaluate all symbols
    print("Evaluating symbols for promotion/demotion...")
    evolver_output = evolve_all_symbols(metrics_dict)
    
    # Write output
    EVOLVER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    EVOLVER_OUTPUT_PATH.write_text(json.dumps(evolver_output, indent=2, sort_keys=True))
    print(f"✅ Evolver output written to: {EVOLVER_OUTPUT_PATH}")
    print()
    
    # Print summary
    print("EVOLVER SUMMARY")
    print("-" * 70)
    for line in evolver_output.get("summary", []):
        print(line)
    print()
    
    # Print detailed notes for candidates
    promotion_count = sum(
        1 for s in evolver_output["symbols"].values() if s.get("promotion_candidate")
    )
    demotion_count = sum(
        1 for s in evolver_output["symbols"].values() if s.get("demotion_candidate")
    )
    
    if promotion_count > 0 or demotion_count > 0:
        print("DETAILED CANDIDATES")
        print("-" * 70)
        
        for symbol, evaluation in evolver_output["symbols"].items():
            if evaluation.get("promotion_candidate") or evaluation.get("demotion_candidate"):
                print(f"\n{symbol}:")
                print(f"  Tier: {evaluation['tier']}")
                if evaluation.get("promotion_candidate"):
                    print(f"  → Promotion candidate")
                if evaluation.get("demotion_candidate"):
                    print(f"  → Demotion candidate")
                print(f"  Suggested conf_min_delta: {evaluation['suggested_conf_min_delta']:.3f}")
                print(f"  Suggested exploration_cap_delta: {evaluation['suggested_exploration_cap_delta']}")
                if evaluation.get("notes"):
                    print("  Notes:")
                    for note in evaluation["notes"]:
                        print(f"    - {note}")
        print()
    
    print("=" * 70)
    print("Note: All outputs are ADVISORY ONLY. No configs were modified.")
    print("=" * 70)


if __name__ == "__main__":
    main()


