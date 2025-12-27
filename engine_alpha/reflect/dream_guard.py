from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from dateutil import parser

from engine_alpha.reflect.trade_sanity import is_close_like_event, get_close_return_pct

TRADES_PATH = Path("reports/trades.jsonl")
STATE_PATH = Path("reports/gpt/dream_state.json")
DEFAULT_MIN_NEW_CLOSES = 20


def _load_state() -> Dict[str, Any]:
    """Load guard state, falling back to defaults."""
    if not STATE_PATH.exists():
        return {"last_close_ts": None, "min_new_closes": DEFAULT_MIN_NEW_CLOSES}

    try:
        with STATE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("state not a dict")
        data.setdefault("last_close_ts", None)
        data.setdefault("min_new_closes", DEFAULT_MIN_NEW_CLOSES)
        return data
    except Exception:
        return {"last_close_ts": None, "min_new_closes": DEFAULT_MIN_NEW_CLOSES}


def _save_state(state: Dict[str, Any]) -> None:
    """Persist guard state."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def _parse_ts(raw_ts: str) -> Optional[datetime]:
    try:
        return parser.isoparse(raw_ts.replace("Z", "+00:00"))
    except Exception:
        return None


def should_run_dream(min_needed_override: Optional[int] = None) -> Tuple[bool, Optional[str]]:
    """
    Decide whether Dream Mode should run based on new close events since the last run.

    Returns:
        allowed (bool), latest_close_ts (str|None)
    """
    state = _load_state()
    min_needed = min_needed_override if min_needed_override is not None else int(
        state.get("min_new_closes", DEFAULT_MIN_NEW_CLOSES)
    )
    last_close_raw = state.get("last_close_ts")
    last_close_dt = _parse_ts(last_close_raw) if last_close_raw else None

    if not TRADES_PATH.exists():
        print(f"🌙 Dream skipped: trades log missing at {TRADES_PATH}")
        return False, last_close_raw

    new_closes = []

    with TRADES_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                event = json.loads(line)
            except Exception:
                continue

            if not is_close_like_event(event):
                continue

            pct = get_close_return_pct(event)
            if pct is None:
                continue

            ts_raw = event.get("ts") or event.get("timestamp") or event.get("time")
            if not ts_raw:
                continue

            ts_dt = _parse_ts(ts_raw)
            if ts_dt is None:
                continue

            if last_close_dt and ts_dt <= last_close_dt:
                continue

            new_closes.append(ts_dt)

    new_count = len(new_closes)
    if new_count < min_needed:
        print(f"🌙 Dream skipped: only {new_count}/{min_needed} new closes")
        return False, last_close_raw

    latest_dt = max(new_closes).astimezone(timezone.utc)
    latest_iso = latest_dt.isoformat()

    state["last_close_ts"] = latest_iso
    state["min_new_closes"] = min_needed
    _save_state(state)

    print(f"🌙 Dream allowed: {new_count} new closes (latest={latest_iso})")
    return True, latest_iso

