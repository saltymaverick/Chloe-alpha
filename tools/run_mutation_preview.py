"""
Run Mutation Preview - Preview strategy mutations for all symbols.

All mutations are ADVISORY ONLY - no configs are modified.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine_alpha.evolve.mutation_engine import MutationCore

ROOT = Path(__file__).resolve().parents[1]
EVOLVER_OUTPUT_DIR = ROOT / "reports" / "evolver"
MUTATION_PREVIEW_PATH = EVOLVER_OUTPUT_DIR / "mutation_preview.json"


def main() -> None:
    """Main entry point."""
    print("MUTATION PREVIEW")
    print("=" * 70)
    print()
    
    # Initialize mutation engine
    engine = MutationCore()
    
    # Load inputs
    print("Loading inputs...")
    load_summary = engine.load_inputs()
    
    if load_summary["evolver_symbols"] == 0:
        print("⚠️  No evolver output found.")
        print("   Run evolver cycle first: python3 -m tools.run_evolver_cycle")
        return
    
    print(f"   Loaded: {load_summary['evolver_symbols']} symbols from evolver")
    print(f"   Loaded: {load_summary['quality_symbols']} quality scores")
    print(f"   Loaded: {load_summary['are_symbols']} ARE symbols")
    print()
    
    # Propose mutations
    print("Proposing mutations...")
    mutations = engine.propose_mutations()
    
    if not mutations:
        print("   No mutations proposed for any symbols.")
        print("   (This is normal if no symbols meet mutation criteria)")
        return
    
    # Save output
    output_path = engine.save_output(mutations)
    print(f"✅ Mutations written to: {output_path}")
    print()
    
    # Also write preview file
    preview_output = {
        "generated_at": engine.evolver_output.get("generated_at"),
        "mutations": mutations,
        "summary": {
            "total_symbols": len(mutations),
            "total_mutations": sum(len(m) for m in mutations.values()),
        },
    }
    EVOLVER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MUTATION_PREVIEW_PATH.write_text(
        json.dumps(preview_output, indent=2, sort_keys=True)
    )
    print(f"✅ Preview written to: {MUTATION_PREVIEW_PATH}")
    print()
    
    # Print summary
    print("MUTATION SUMMARY")
    print("-" * 70)
    
    for symbol, symbol_mutations in sorted(mutations.items()):
        print(f"\n{symbol}:")
        for mut in symbol_mutations:
            param = mut["param"]
            delta = mut["delta"]
            reason = mut["reason"]
            
            if isinstance(delta, float):
                delta_str = f"{delta:+.3f}"
            else:
                delta_str = f"{delta:+d}"
            
            action = "Decrease" if delta < 0 else "Increase" if delta > 0 else "No change"
            print(f"  • {action} {param} by {delta_str} (reason: {reason})")
    
    print()
    print("=" * 70)
    print("Note: All mutations are PROPOSALS ONLY. No configs were modified.")
    print("=" * 70)


if __name__ == "__main__":
    import json
    main()
