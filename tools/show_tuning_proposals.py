#!/usr/bin/env python3
"""
Inspect raw tuner proposals and guardrail results.

Usage:
    python3 -m tools.show_tuning_proposals
"""

from __future__ import annotations

import json
from pathlib import Path

from engine_alpha.overseer.tuner_guardrails import (
    RAW_PROPOSALS_PATH,
    GUARDED_PROPOSALS_PATH,
    apply_guardrails_to_file,
)


def _safe_load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = path.read_text().strip()
        return json.loads(data) if data else {}
    except Exception:
        return {}


def main() -> None:
    raw = _safe_load(RAW_PROPOSALS_PATH)
    if not raw:
        print("No raw tuning proposals found.")
    else:
        print(f"Loaded raw proposals ({len(raw.get('proposals', {}))} symbols).")

    guarded = apply_guardrails_to_file()
    proposals_guarded = guarded.get("proposals", {})
    if not proposals_guarded:
        print("No guarded proposals available.")
        return

    print("\nTUNING PROPOSALS (GUARDED)")
    print("-------------------------")
    for symbol, result in proposals_guarded.items():
        allowed = result.get("allowed_changes", {})
        blocked = result.get("blocked_changes", {})
        reasons = result.get("reason", [])

        print(f"\n{symbol}:")
        print(f"  Reasons : {', '.join(str(r) for r in reasons) if reasons else 'ok'}")
        if allowed:
            print("  Allowed changes:")
            for key, delta in allowed.items():
                print(f"    - {key}: {delta}")
        else:
            print("  Allowed changes: none")
        if blocked:
            print("  Blocked changes:")
            for key, delta in blocked.items():
                print(f"    - {key}: {delta}")
        else:
            print("  Blocked changes: none")


if __name__ == "__main__":
    main()

