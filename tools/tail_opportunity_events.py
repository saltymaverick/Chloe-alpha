#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import collections

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
EVENTS_PATH = REPORTS / "opportunity_events.jsonl"


def _parse_ts(ts: str):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def main():
    last_n = 20
    if EVENTS_PATH.exists():
        try:
            lines = EVENTS_PATH.read_text().splitlines()
            tail = lines[-last_n:]
            print(f"=== last {len(tail)} events ===")
            for line in tail:
                print(line)
        except Exception as e:
            print(f"failed to read events: {e}", file=sys.stderr)
    else:
        print("opportunity_events.jsonl not found")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    events = 0
    eligible = 0
    reasons = collections.Counter()
    if EVENTS_PATH.exists():
        with EVENTS_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                ts = _parse_ts(entry.get("ts"))
                if ts and ts < cutoff:
                    continue
                events += 1
                if entry.get("eligible"):
                    eligible += 1
                reasons[entry.get("eligible_reason", "unknown")] += 1
    print(f"\n24h events={events} eligible={eligible}")
    print("top reasons:", reasons.most_common(10))


if __name__ == "__main__":
    raise SystemExit(main())

