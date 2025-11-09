#!/usr/bin/env python3
"""
Risk policy note helper — Phase 29.

Writes a policy note when prolonged band C conditions persist.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

from engine_alpha.core.paths import REPORTS

STATE_PATH = REPORTS / "alerts_state.json"
NOTE_PATH = REPORTS / "policy_note.json"
TWENTY_FOUR_HOURS = timedelta(hours=24)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_note() -> None:
    NOTE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": _now().isoformat(),
        "note": "Policy remains PAUSE due to prolonged band C (>24h) and dd>20%.",
    }
    NOTE_PATH.write_text(json.dumps(payload, indent=2))


def _delete_note() -> None:
    try:
        NOTE_PATH.unlink()
    except FileNotFoundError:
        pass


def main() -> None:
    state = _load_json(STATE_PATH)
    active = bool(state.get("prolonged_band_c_active"))
    band_state = state.get("band_c") if isinstance(state.get("band_c"), dict) else {}
    since_ts = _parse_ts(band_state.get("since"))

    if not active or not since_ts:
        _delete_note()
        return

    if _now() - since_ts >= TWENTY_FOUR_HOURS:
        _write_note()
    else:
        _delete_note()


if __name__ == "__main__":
    main()

