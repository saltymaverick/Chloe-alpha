#!/usr/bin/env python3
"""
Council Weight Mutator - Phase 50
Helper utility to mutate council weights YAML for offline learning experiments.

PURPOSE:
--------
This tool generates mutated weight candidates by applying tiny random mutations (±0.02)
to randomly selected buckets. Mutations are:
- Symmetrical (±0.02)
- Bounded between 0.05 and 0.60
- Normalized so weights sum to 1.0 per regime

OPERATION:
----------
- Loads base weights from config/council_weights.yaml
- Applies random mutations to randomly selected buckets
- Normalizes weights to sum to 1.0 per regime
- Writes mutated YAML to reports/council_learning/run_<run_id>/candidate_<n>.yaml

SAFETY:
-------
- This is OFFLINE ONLY. No changes are applied to live trading.
- Mutated weights are used ONLY in backtest experiments.
- Live trading is completely unaffected.

ASSUMPTIONS:
-----------
- Base weights file exists at config/council_weights.yaml
- Output directory structure exists (created by council_weight_learner)
- All weights are positive and sum to 1.0 per regime
"""

from __future__ import annotations

import argparse
import json
import random
import yaml
from pathlib import Path
from typing import Dict, Any

from engine_alpha.core.paths import REPORTS


BASE_WEIGHTS_PATH = Path(__file__).parent.parent / "config" / "council_weights.yaml"
MUTATION_DELTA = 0.02
MIN_WEIGHT = 0.05
MAX_WEIGHT = 0.60


def mutate_weights(
    base_weights_path: Path,
    output_path: Path,
    num_mutations: int = 2,
) -> Dict[str, Dict[str, float]]:
    """
    Mutate council weights by applying tiny random mutations.
    
    Args:
        base_weights_path: Path to base council_weights.yaml
        output_path: Path to write mutated YAML
        num_mutations: Number of buckets to mutate per regime (default: 2)
    
    Returns:
        Dict with mutated weights (same structure as base)
    
    Mutations:
    - Randomly select num_mutations buckets per regime
    - Apply ±0.02 mutation (random sign)
    - Bound weights between MIN_WEIGHT and MAX_WEIGHT
    - Normalize so weights sum to 1.0 per regime
    """
    # Load base weights
    if not base_weights_path.exists():
        raise FileNotFoundError(f"Base weights file not found: {base_weights_path}")
    
    with open(base_weights_path, "r") as f:
        base_data = yaml.safe_load(f) or {}
    
    base_weights = base_data.get("council_weights", {})
    if not base_weights:
        raise ValueError(f"No council_weights found in {base_weights_path}")
    
    # Apply mutations
    mutated_weights = {}
    bucket_names = ["momentum", "meanrev", "flow", "positioning", "timing"]
    
    for regime in ["trend", "chop", "high_vol"]:
        regime_base = base_weights.get(regime, {}).copy()
        
        # Select random buckets to mutate
        buckets_to_mutate = random.sample(bucket_names, min(num_mutations, len(bucket_names)))
        
        # Apply mutations
        for bucket_name in buckets_to_mutate:
            current_weight = regime_base.get(bucket_name, 0.0)
            # Random mutation: ±0.02
            mutation = random.choice([-MUTATION_DELTA, MUTATION_DELTA])
            new_weight = current_weight + mutation
            
            # Bound between MIN_WEIGHT and MAX_WEIGHT
            new_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, new_weight))
            regime_base[bucket_name] = new_weight
        
        # Normalize to sum to 1.0
        total = sum(regime_base.values())
        if total > 0:
            for bucket_name in bucket_names:
                regime_base[bucket_name] = regime_base[bucket_name] / total
        
        mutated_weights[regime] = regime_base
    
    # Write mutated YAML
    output_data = {"council_weights": mutated_weights}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(output_data, f, default_flow_style=False, sort_keys=False)
    
    return mutated_weights


def main() -> None:
    """CLI entry point for mutate_weights."""
    parser = argparse.ArgumentParser(
        description="Mutate council weights YAML for offline learning experiments"
    )
    parser.add_argument(
        "--base",
        type=str,
        default=str(BASE_WEIGHTS_PATH),
        help="Path to base council_weights.yaml (default: config/council_weights.yaml)",
    )
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Path to write mutated YAML",
    )
    parser.add_argument(
        "--num-mutations",
        type=int,
        default=2,
        help="Number of buckets to mutate per regime (default: 2)",
    )
    
    args = parser.parse_args()
    
    try:
        mutated = mutate_weights(
            base_weights_path=Path(args.base),
            output_path=Path(args.output),
            num_mutations=args.num_mutations,
        )
        print(f"✅ Mutated weights written to {args.output}")
        print(f"   Regimes: {list(mutated.keys())}")
        for regime, weights in mutated.items():
            total = sum(weights.values())
            print(f"   {regime}: sum={total:.4f}")
    except Exception as e:
        print(f"❌ Error: {e}", file=__import__("sys").stderr)
        exit(1)


if __name__ == "__main__":
    main()
