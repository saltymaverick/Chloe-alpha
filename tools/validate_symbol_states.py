#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "reports" / "risk" / "symbol_states.json"


def main() -> int:
    if not STATE_PATH.exists():
        print(f"ERROR: {STATE_PATH} not found")
        return 1
    try:
        data = json.loads(STATE_PATH.read_text())
    except Exception as e:
        print(f"ERROR: failed to read symbol_states: {e}")
        return 1
    symbols = data.get("symbols") or {}
    if not isinstance(symbols, dict):
        print("ERROR: symbols field is not a dict")
        return 1

    ok = True
    for sym, st in symbols.items():
        if not isinstance(st, dict):
            print(f"ERROR: symbol {sym} state is not a dict")
            ok = False
            continue
        state = st.get("state")
        pf7 = st.get("pf_7d")
        n7 = st.get("n_closes_7d")
        quar = bool(st.get("quarantined", False))
        allow_core = bool(st.get("allow_core", False))
        allow_expl = bool(st.get("allow_exploration", False))
        allow_rec = bool(st.get("allow_recovery", False))

        if state in {"core", "exploration", "recovery"} and pf7 is None and n7 is None:
            print(f"ERROR: {sym} state={state} but pf_7d/n_closes_7d are None")
            ok = False
        if quar and (allow_core or allow_expl or allow_rec):
            print(f"ERROR: {sym} quarantined=True but allow flags are True")
            ok = False
        # If no allow flag is true but nothing blocks, flag it
        if not (allow_core or allow_expl or allow_rec) and not quar:
            # basic consistency check: must have a policy block in this case
            print(f"WARN: {sym} has no allow flags set (not quarantined) — check ladder thresholds")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())


