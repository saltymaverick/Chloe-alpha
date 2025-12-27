import json
import subprocess
from datetime import datetime, timezone

from dateutil import parser

TRADES_PATH = "reports/trades.jsonl"
STATE_PATH = "reports/gpt/dream_state.json"
MIN_NEW_CLOSES = 20


def load_state():
    try:
        return json.load(open(STATE_PATH))
    except Exception:
        return {"last_close_ts": None}


def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def get_new_close_times(last_close_ts):
    cut_dt = parser.isoparse(last_close_ts) if last_close_ts else None
    closes = []
    with open(TRADES_PATH) as f:
        for line in f:
            e = json.loads(line)
            if (e.get("type") or "").lower() != "close":
                continue
            ts = e.get("ts")
            if not ts:
                continue
            dt = parser.isoparse(ts.replace("Z", "+00:00"))
            if cut_dt is None or dt > cut_dt:
                closes.append(dt)
    closes.sort()
    return closes


def main():
    state = load_state()
    new_closes = get_new_close_times(state.get("last_close_ts"))

    if len(new_closes) < MIN_NEW_CLOSES:
        print(f"🌙 Dream skipped: only {len(new_closes)}/{MIN_NEW_CLOSES} new closes")
        return 0

    latest = new_closes[-1].astimezone(timezone.utc).isoformat()

    print(f"🌙 Dream allowed: {len(new_closes)} new closes (latest={latest})")

    rc = subprocess.call(["python3", "-m", "tools.run_dream_cycle"])
    if rc == 0:
        # Advance state only after a successful run
        state["last_close_ts"] = latest
        save_state(state)
    else:
        print(f"🌙 Dream run failed (rc={rc}); state not advanced")

    return rc


if __name__ == "__main__":
    raise SystemExit(main())

