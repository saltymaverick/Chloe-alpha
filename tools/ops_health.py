#!/usr/bin/env python3
"""
Ops health monitor — Phase Ops
Checks key report artifacts and appends status to ops.log.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

from engine_alpha.core.paths import REPORTS, LOGS


PF_MAX_AGE = timedelta(hours=2)
TRADES_MAX_AGE = timedelta(hours=2)
DREAM_MAX_AGE = timedelta(hours=36)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _file_recent(path: Path, max_age: timedelta) -> bool:
    if not path.exists():
        return False
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (_now() - mtime) <= max_age


def _read_latest_ts(path: Path) -> Optional[datetime]:
    try:
        with path.open("r") as f:
            lines = f.readlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            ts = obj.get("ts")
            if ts:
                try:
                    return datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    continue
    except Exception:
        return None
    return None


def evaluate() -> Dict[str, Any]:
    notes = []

    pf_path = REPORTS / "pf_local.json"
    pf_ok = _file_recent(pf_path, PF_MAX_AGE)
    if not pf_ok:
        notes.append("pf_local stale or missing")

    trades_path = REPORTS / "trades.jsonl"
    trades_ok = _file_recent(trades_path, TRADES_MAX_AGE)
    if not trades_ok:
        notes.append("trades stale or missing")

    dream_path = REPORTS / "dream_log.jsonl"
    dream_ok = True
    if not dream_path.exists():
        dream_ok = False
        notes.append("dream_log missing")
    else:
        latest_ts = _read_latest_ts(dream_path)
        if latest_ts is None or (_now() - latest_ts) > DREAM_MAX_AGE:
            dream_ok = False
            notes.append("dream_log stale")

    status = {
        "ts": _now().isoformat(),
        "pf_ok": pf_ok,
        "trades_ok": trades_ok,
        "dream_ok": dream_ok,
        "notes": "; ".join(notes) if notes else "ok",
    }

    log_path = LOGS / "ops.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        f.write(json.dumps(status) + "\n")

    return status


def main() -> None:
    status = evaluate()
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
