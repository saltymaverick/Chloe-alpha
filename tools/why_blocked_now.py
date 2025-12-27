#!/usr/bin/env python3
"""
Why Blocked Now - operator smoke tool.

Prints the current capital mode, PF_7D vs floor, failing gates, and opportunity eligibility.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CAPITAL_PROTECTION_PATH = REPO_ROOT / "reports" / "risk" / "capital_protection.json"
RECOVERY_RAMP_PATH = REPO_ROOT / "reports" / "risk" / "recovery_ramp.json"
REFLECTION_PACKET_PATH = REPO_ROOT / "reports" / "reflection_packet.json"


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def main() -> int:
    cp = _load(CAPITAL_PROTECTION_PATH)
    ramp = _load(RECOVERY_RAMP_PATH)
    rp = _load(REFLECTION_PACKET_PATH)

    cp_mode = cp.get("mode") or (cp.get("global") or {}).get("mode") or "unknown"
    ramp_mode = ramp.get("capital_mode", "unknown")

    metrics = ramp.get("metrics", {})
    gates = ramp.get("gates", {})

    pf7d_val = metrics.get("pf7d_value")
    pf7d_floor = metrics.get("pf7d_floor_required")
    pf7d_pass = gates.get("pf7d_floor_pass")

    failing = [k for k, v in gates.items() if v is False]

    opp = (rp.get("primitives") or {}).get("opportunity") or {}
    eligible_now = opp.get("eligible_now")
    eligible_reason = opp.get("eligible_now_reason")

    print("=== WHY BLOCKED NOW ===")
    print(f"Capital mode (capital_protection): {cp_mode}")
    print(f"Capital mode (recovery_ramp):     {ramp_mode}")
    print()
    print("PF7D floor gate:")
    print(f"  pf7d: {pf7d_val}")
    print(f"  floor_required: {pf7d_floor}")
    print(f"  pf7d_floor_pass: {pf7d_pass}")
    print()
    print("Gates failing:", ", ".join(failing) if failing else "(none)")
    reason = ramp.get("reason")
    if reason:
        print(f"Recovery reason: {reason}")
    notes = ramp.get("notes") or []
    if notes:
        print("Notes:")
        for n in notes:
            print(f"  • {n}")
    print()
    print("Opportunity eligibility:")
    print(f"  eligible_now: {eligible_now}")
    print(f"  reason: {eligible_reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

