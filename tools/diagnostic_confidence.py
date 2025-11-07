#!/usr/bin/env python3
"""
Confidence diagnostic - Phase 15
Runs confidence tuning and prints summary deltas.
"""

from __future__ import annotations

from engine_alpha.core.confidence_tuner import run_once


def main():
    entries = run_once()
    if not entries:
        print("No confidence data available")
        return
    parts = []
    for entry in entries:
        regime = entry["regime"]
        delta = entry["delta"]
        new_gate = entry["new_gate"]
        parts.append(f"{regime} {delta:+.02f} → {new_gate:.2f}")
    print("  |  ".join(parts))


if __name__ == "__main__":
    main()
