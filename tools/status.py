#!/usr/bin/env python3
"""
Lightweight status summary for Alpha Chloe runtime artifacts.
Prints a single-line snapshot covering policy, risk, live loop, and trades.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from engine_alpha.core.paths import REPORTS


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue
    except Exception:
        return []


def _summarize_trades(trades_path: Path) -> Tuple[int, str]:
    close_count = 0
    last_close_ts = "N/A"
    last_seen_ts = None
    for entry in _iter_jsonl(trades_path):
        ts = entry.get("ts")
        event_type = str(entry.get("type") or entry.get("event") or "").lower()
        if event_type == "close":
            close_count += 1
            last_close_ts = ts or "N/A"
            last_seen_ts = ts
    if close_count == 0 and last_seen_ts:
        last_close_ts = last_seen_ts
    return close_count, last_close_ts or "N/A"


def _format_ts(ts_val: Any) -> str:
    if not ts_val:
        return "N/A"
    if isinstance(ts_val, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(ts_val), tz=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            return str(ts_val)
    if isinstance(ts_val, str):
        return ts_val
    return "N/A"


def main() -> int:
    orch = _load_json(REPORTS / "orchestrator_snapshot.json")
    risk = _load_json(REPORTS / "risk_adapter.json")
    live_state = _load_json(REPORTS / "live_loop_state.json")

    policy = orch.get("policy", {}) if isinstance(orch, dict) else {}
    inputs = orch.get("inputs", {}) if isinstance(orch, dict) else {}

    rec = orch.get("recommendation") or inputs.get("rec") or "N/A"
    allow_opens = policy.get("allow_opens")
    allow_pa = policy.get("allow_pa")

    band = risk.get("band", "N/A")
    mult = risk.get("mult", "N/A")
    drawdown = risk.get("drawdown") or risk.get("dd") or risk.get("max_drawdown")

    live_ts = live_state.get("ts") if isinstance(live_state, dict) else None

    close_count, last_close_ts = _summarize_trades(REPORTS / "trades.jsonl")

    summary = (
        f"REC={rec} opens={allow_opens} pa={allow_pa} | "
        f"Risk band={band} mult={mult} dd={drawdown if drawdown is not None else 'N/A'} | "
        f"Live ts={_format_ts(live_ts)} | "
        f"Closes={close_count} last_close={_format_ts(last_close_ts)}"
    )
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

