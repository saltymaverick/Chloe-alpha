import json
import subprocess
from datetime import datetime, timezone, timedelta

from dateutil import parser

TRADES_PATH = "reports/trades.jsonl"
STATE_PATH = "reports/gpt/fast_reflect_state.json"
OUT_JSONL = "reports/gpt_reflection_narrative.jsonl"

MIN_NEW_CLOSES = 5
MIN_SECONDS_BETWEEN_RUNS = 600  # 10 minutes
MAX_NEW_CLOSES_FOR_CONTEXT = 50  # cap for “what changed” context


def load_state():
    try:
        return json.load(open(STATE_PATH))
    except Exception:
        return {"last_close_ts": None, "last_run_ts": None}


def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def iter_close_events():
    with open(TRADES_PATH) as f:
        for line in f:
            e = json.loads(line)
            if (e.get("type") or "").lower() != "close":
                continue
            if not e.get("ts"):
                continue

            # Only count core-lane closes; skip recovery_v2 mirrors to avoid double counting
            trade_kind = (e.get("trade_kind") or e.get("strategy") or "").lower()
            if trade_kind == "recovery_v2":
                continue

            yield e


def get_new_close_times(last_close_ts):
    cut_dt = parser.isoparse(last_close_ts) if last_close_ts else None
    closes = []
    for e in iter_close_events():
        dt = parser.isoparse(e["ts"].replace("Z", "+00:00"))
        if cut_dt is None or dt > cut_dt:
            closes.append(dt)
    closes.sort()
    return closes


def append_jsonl(obj):
    with open(OUT_JSONL, "a") as f:
        f.write(json.dumps(obj, separators=(",", ":")) + "\n")


def main():
    state = load_state()

    # rate guard (manual spam protection)
    if state.get("last_run_ts"):
        last_run = parser.isoparse(state["last_run_ts"])
        if datetime.now(timezone.utc) - last_run < timedelta(seconds=MIN_SECONDS_BETWEEN_RUNS):
            print("FAST NARRATIVE skipped: ran too recently")
            return 0

    new_closes = get_new_close_times(state.get("last_close_ts"))
    if len(new_closes) < MIN_NEW_CLOSES:
        print(f"FAST NARRATIVE skipped: only {len(new_closes)}/{MIN_NEW_CLOSES} new closes")
        return 0

    # Cap context to avoid “huge backlog” behavior; still advance state to latest
    capped = new_closes[-MAX_NEW_CLOSES_FOR_CONTEXT:]
    latest_close = new_closes[-1].astimezone(timezone.utc).isoformat()

    # advance state BEFORE running
    state["last_close_ts"] = latest_close
    state["last_run_ts"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    print(f"FAST NARRATIVE allowed: {len(new_closes)} new closes (capped_context={len(capped)} latest={latest_close})")

    # Run the v4-aware reflection cycle (writes reports/gpt/reflection_output.json)
    rc = subprocess.call(["python3", "-m", "tools.run_reflection_cycle"])
    if rc != 0:
        append_jsonl({
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": "fast_reflection_narrative",
            "status": "error",
            "return_code": rc
        })
        return rc

    # Read the reflection output and append to narrative log
    out_path = "reports/gpt/reflection_output.json"
    try:
        out = json.load(open(out_path))
    except Exception as e:
        append_jsonl({
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": "fast_reflection_narrative",
            "status": "error",
            "error": f"could_not_read_reflection_output: {e}"
        })
        return 1

    append_jsonl({
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": "fast_reflection_narrative",
        "status": "ok",
        "new_closes": len(new_closes),
        "capped_context": len(capped),
        "latest_close_ts": latest_close,
        "output": out
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

