#!/usr/bin/env python3
"""
Run Chloe's temporal meta-activity reflection.

Usage:
    python3 -m tools.activity_meta_reflection
"""

from __future__ import annotations

from engine_alpha.reflect.activity_meta_reflection import run_meta_reflection


def main() -> None:
    record = run_meta_reflection()
    print("META-ACTIVITY REFLECTION")
    print("------------------------")
    print(f"Timestamp : {record.get('ts', 'unknown')}")
    print(f"Phase     : {record.get('phase', 'unknown')}")
    print()
    print(record.get("reflection", "No meta-reflection text available."))


if __name__ == "__main__":
    main()

