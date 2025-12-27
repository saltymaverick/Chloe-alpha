#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.apply_tuner import apply_tuner_if_safe


def main() -> int:
    tuner_path = REPORTS / "gpt" / "tuner_output.json"
    print(f"tuner_output_path: {tuner_path}")
    if tuner_path.exists():
        try:
            obj = json.loads(tuner_path.read_text())
            print(f"tuner_output_present: yes keys={sorted(list(obj.keys()))}")
        except Exception as exc:
            print(f"tuner_output_present: yes (parse_failed: {exc!r})")
    else:
        print("tuner_output_present: no")

    res = apply_tuner_if_safe(dry_run_only=True)
    print("")
    print("=== apply_tuner_if_safe (dry_run_only=True) ===")
    print(f"APPLIED?: {res.get('applied')}")
    print(f"reason: {res.get('reason')}")
    print("blocked_by:")
    for b in (res.get("blocked_by") or []):
        print(f"  - {b}")

    print("")
    print("summary:")
    try:
        print(json.dumps(res.get("summary") or {}, indent=2, sort_keys=True))
    except Exception:
        print(res.get("summary"))

    print("")
    print("changes:")
    changes = res.get("changes") or []
    if not changes:
        print("  (none)")
    else:
        for c in changes:
            print("  - " + json.dumps(c, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


