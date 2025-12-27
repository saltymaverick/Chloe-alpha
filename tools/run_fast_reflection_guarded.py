import json
import subprocess
from datetime import datetime, timezone, timedelta

from dateutil import parser

TRADES_PATH = "reports/trades.jsonl"
STATE_PATH = "reports/gpt/fast_reflect_state.json"

MIN_NEW_CLOSES = 5
MIN_SECONDS_BETWEEN_RUNS = 600  # 10 minutes


def load_state():
    try:
        return json.load(open(STATE_PATH))
    except Exception:
        return {"last_close_ts": None, "last_run_ts": None}


def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def count_new_closes_since(last_close_ts):
    cut_dt = parser.isoparse(last_close_ts) if last_close_ts else None
    new_close_ts = []
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
                new_close_ts.append(dt)
    return new_close_ts


def main():
    state = load_state()

    if state.get("last_run_ts"):
        last_run = parser.isoparse(state["last_run_ts"])
        if datetime.now(timezone.utc) - last_run < timedelta(seconds=MIN_SECONDS_BETWEEN_RUNS):
            print("FAST REFLECT skipped: ran too recently")
            return 0

    new_closes = count_new_closes_since(state.get("last_close_ts"))
    if len(new_closes) < MIN_NEW_CLOSES:
        print(f"FAST REFLECT skipped: only {len(new_closes)}/{MIN_NEW_CLOSES} new closes")
        return 0

    latest_close = max(new_closes).astimezone(timezone.utc).isoformat()
    state["last_close_ts"] = latest_close
    state["last_run_ts"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    print(f"FAST REFLECT allowed: {len(new_closes)} new closes (latest={latest_close})")

    cmd = ["python3", "-m", "engine_alpha.reflect.gpt_reflection_runner"]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())

