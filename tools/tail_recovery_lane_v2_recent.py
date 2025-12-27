#!/usr/bin/env python3
"""
Tail Recovery Lane V2 Recent Logs
----------------------------------

Print recent lines from recovery_lane_v2_log.jsonl with optional time filtering.
Helps distinguish current behavior from historical log entries.
"""

from __future__ import annotations

import sys
import json
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from engine_alpha.core.paths import REPORTS

LOG_PATH = REPORTS / "loop" / "recovery_lane_v2_log.jsonl"


def _parse_iso_timestamp(ts_str: str) -> datetime | None:
    """Parse ISO timestamp string to datetime."""
    if not ts_str:
        return None
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except Exception:
        return None


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Print recent recovery lane v2 log entries"
    )
    parser.add_argument(
        "-n",
        "--lines",
        type=int,
        default=25,
        help="Number of lines to print (default: 25)",
    )
    parser.add_argument(
        "--since-minutes",
        type=int,
        default=None,
        help="Only show lines within last N minutes (default: show all)",
    )
    args = parser.parse_args()

    if not LOG_PATH.exists():
        print(f"Log file not found: {LOG_PATH}")
        return 1

    # Read all lines
    lines = []
    try:
        with LOG_PATH.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Error reading log file: {e}")
        return 1

    if not lines:
        print("Log file is empty")
        return 0

    # Filter by time if requested
    cutoff_time = None
    if args.since_minutes:
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=args.since_minutes)

    # Process lines (most recent first)
    filtered_lines = []
    for line in reversed(lines[-args.lines * 2:]):  # Read extra to account for filtering
        line = line.strip()
        if not line:
            continue

        # Parse JSON
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Filter by time if requested
        if cutoff_time:
            ts_str = entry.get("ts", "")
            ts = _parse_iso_timestamp(ts_str)
            if ts is None or ts < cutoff_time:
                continue

        filtered_lines.append(line)
        if len(filtered_lines) >= args.lines:
            break

    # Print (most recent first, so reverse)
    for line in reversed(filtered_lines):
        print(line)

    return 0


if __name__ == "__main__":
    sys.exit(main())

