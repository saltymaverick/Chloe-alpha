#!/usr/bin/env python3
"""
Sandbox diagnostic - Phase 18
Runs sandbox cycle and tails recent results.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine_alpha.core.paths import REPORTS
from engine_alpha.evolve.sandbox_manager import run_cycle


def tail_jsonl(path: Path, lines: int = 3):
    if not path.exists():
        return []
    try:
        return [json.loads(line) for line in path.read_text().splitlines()[-lines:]]
    except Exception:
        return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=200)
    parser.add_argument("--max-new", type=int, default=1)
    args = parser.parse_args()

    summary = run_cycle(steps=args.steps, max_new=args.max_new)
    print(f"Sandbox cycle summary: {summary}")

    runs_path = REPORTS / "sandbox" / "sandbox_runs.jsonl"
    recent_runs = tail_jsonl(runs_path, lines=3)
    if recent_runs:
        print("Recent runs:")
        for run in recent_runs:
            print(run)
        last_run = recent_runs[-1]
        run_dir = REPORTS / "sandbox" / last_run.get("id", "")
        trades_path = run_dir / "trades.jsonl"
        if trades_path.exists():
            print("Last run trades tail:")
            for line in trades_path.read_text().splitlines()[-5:]:
                try:
                    print(json.loads(line))
                except Exception:
                    print(line)
    else:
        print("No sandbox runs yet")


if __name__ == "__main__":
    main()
