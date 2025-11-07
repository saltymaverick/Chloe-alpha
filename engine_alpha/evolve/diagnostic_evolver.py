#!/usr/bin/env python3
"""
Strategy Evolver Diagnostic - Phase 7
Runs the sandbox evolver and summarizes the outcome.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

from engine_alpha.core.paths import REPORTS
from engine_alpha.evolve.strategy_evolver import run_evolver


def main():
    result = run_evolver()
    best = result.get("best") or {}

    snapshot = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "baseline_pf_local": result.get("baseline_pf_local"),
        "best_pf_cf": best.get("pf_cf"),
        "uplift": best.get("uplift"),
        "child_name": best.get("child_name"),
        "params": best.get("params"),
        "tested": result.get("tested"),
    }

    snapshot_path = REPORTS / "evolver_snapshot.json"
    with open(snapshot_path, "w") as f:
        json.dump(snapshot, f, indent=2)

    print("Strategy evolver run complete")
    print(f" Baseline PF_local: {snapshot['baseline_pf_local']}")
    print(f" Best PF_cf: {snapshot['best_pf_cf']}")
    print(f" Uplift: {snapshot['uplift']}")
    print(f" Child name: {snapshot['child_name']}")
    print(f" Snapshot file: {snapshot_path}")


if __name__ == "__main__":
    main()
