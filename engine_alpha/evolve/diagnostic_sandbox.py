#!/usr/bin/env python3
"""
Sandbox diagnostic - Phase 18
Runs sandbox cycle and shows recent results.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine_alpha.core.paths import REPORTS
from engine_alpha.evolve.sandbox_manager import run_cycle


def _tail_jsonl(path: Path, lines: int = 3):
    if not path.exists():
        return []
    try:
        return [json.loads(line) for line in path.read_text().splitlines()[-lines:]]
    except Exception:
        return []


def _tail_text(path: Path, lines: int = 5) -> str:
    if not path.exists():
        return ""
    try:
        return "\n".join(path.read_text().splitlines()[-lines:])
    except Exception:
        return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=200)
    parser.add_argument("--max-new", type=int, default=1)
    args = parser.parse_args()

    summary = run_cycle(steps=args.steps, max_new=args.max_new)
    print(f"Sandbox cycle summary: {summary}")

    runs_path = REPORTS / "sandbox" / "sandbox_runs.jsonl"
    runs_tail = _tail_jsonl(runs_path, lines=3)
    if runs_tail:
        print("Recent runs:")
        for entry in runs_tail:
            print(entry)
        last_id = runs_tail[-1].get("id")
        if last_id:
            trades_text = _tail_text(REPORTS / "sandbox" / last_id / "trades.jsonl")
            if trades_text:
                print("Last run trades tail:")
                print(trades_text)
    else:
        print("No sandbox runs yet")


if __name__ == "__main__":
    main()
