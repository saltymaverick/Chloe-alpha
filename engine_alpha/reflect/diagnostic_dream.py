#!/usr/bin/env python3
"""
Dream Mode Diagnostic - Phase 6
Runs counterfactual replay and summarizes proposals.
"""

import json
from pathlib import Path

from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.dream_mode import run_dream


def main():
    result = run_dream()

    snapshot = {
        "ts": result["log"]["ts"],
        "pf_local": result["log"]["pf_local"],
        "baseline_pf_cf": result["log"]["baseline_pf_cf"],
        "best_pf_cf": result["proposal"]["pf_cf"],
        "proposal_kind": result["proposal"]["proposal_kind"],
        "best_combo": result["proposal"].get("best_combo"),
        "combos_tested": result.get("combos_tested"),
    }

    snapshot_path = REPORTS / "dream_snapshot.json"
    with open(snapshot_path, "w") as f:
        json.dump(snapshot, f, indent=2)

    print("Dream mode run complete")
    print(f" Dream log: {REPORTS / 'dream_log.jsonl'}")
    print(f" Proposal file: {REPORTS / 'dream_proposals.json'}")
    print(f" Snapshot: {snapshot_path}")


if __name__ == "__main__":
    main()
