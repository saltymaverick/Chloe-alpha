#!/usr/bin/env python3
"""
Mirror diagnostic - Phase 8
Runs mirror mode shadow session end-to-end.
"""

import json
from pathlib import Path

from engine_alpha.core.paths import REPORTS
from engine_alpha.mirror.wallet_hunter import ensure_registry, score_wallets
from engine_alpha.mirror.mirror_manager import run_shadow


def main():
    registry = ensure_registry()
    wallets = score_wallets(registry)
    selected = wallets[:2]

    snapshot = run_shadow(K=len(selected), steps=60)

    snapshot_path = REPORTS / "mirror_snapshot.json"
    with snapshot_path.open("w") as f:
        json.dump(snapshot, f, indent=2)

    print("Mirror mode shadow session complete")
    print(f" Snapshot written to: {snapshot_path}")
    for wallet, pf in snapshot.get("shadow_pnl", {}).items():
        print(f"  Wallet {wallet}: PF={pf}")

    memory_path = REPORTS / "mirror_memory.jsonl"
    if memory_path.exists():
        print("Last 5 shadow trades:")
        with memory_path.open("r") as f:
            lines = f.readlines()[-5:]
        for line in lines:
            print("  ", line.strip())


if __name__ == "__main__":
    main()
