#!/usr/bin/env python3
"""
Run Chloe's activity/staleness reflection.

Usage:
    python3 -m tools.activity_reflection
"""

from __future__ import annotations

from engine_alpha.reflect.activity_reflection import run_activity_reflection


def main() -> None:
    record = run_activity_reflection()
    print("ACTIVITY REFLECTION")
    print("-------------------")
    print(f"Timestamp      : {record.get('ts', 'unknown')}")
    print(f"Phase          : {record.get('phase', 'unknown')}")
    enabled = record.get("enabled_assets", [])
    print(f"Enabled assets : {', '.join(enabled) if enabled else 'None'}")
    print()
    print(record.get("reflection", "No reflection text generated."))


if __name__ == "__main__":
    main()

