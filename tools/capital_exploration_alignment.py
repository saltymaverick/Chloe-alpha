"""
Capital vs Exploration Alignment Tool
-------------------------------------

Shows where capital allocation (Phase 4a) agrees or disagrees with
exploration/risk signals (Phases 2–3).

Reads:
  - reports/risk/capital_plan.json
  - reports/research/exploration_policy_v3.json
  - reports/research/scm_state.json
  - reports/risk/risk_snapshot.json

Outputs a table:

  Symbol  Tier  Wght  Policy  SCM     Block  Align   Notes

Where Align is:
  - OK       : capital and exploration broadly agree
  - Cap>Exp  : capital wants more than exploration/risk support
  - Exp>Cap  : exploration/risk support more than capital is giving

Paper-only, advisory-only. Does NOT change behavior.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


CAPITAL_PLAN_PATH = Path("reports/risk/capital_plan.json")
POLICY_PATH = Path("reports/research/exploration_policy_v3.json")
SCM_PATH = Path("reports/research/scm_state.json")
RISK_SNAPSHOT_PATH = Path("reports/risk/risk_snapshot.json")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _get_policy_for_symbol(policy: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    return (policy.get("symbols") or {}).get(symbol, {})


def _get_scm_for_symbol(scm: Dict[str, Any], symbol: str) -> Optional[str]:
    # Handle scm_state.json format: {"state": {symbol: {...}}}
    state = scm.get("state")
    if isinstance(state, dict):
        entry = state.get(symbol) or {}
        return entry.get("scm_level") or entry.get("level")
    
    # Handle other formats: {"symbols": {...}} or direct dict
    symbols = scm.get("symbols") or scm
    if isinstance(symbols, dict):
        entry = symbols.get(symbol) or {}
    elif isinstance(symbols, list):
        entry = {}
        for item in symbols:
            if isinstance(item, dict) and item.get("symbol") == symbol:
                entry = item
                break
    else:
        entry = {}
    # Try both 'level' and 'scm_level' fields
    return entry.get("scm_level") or entry.get("level")


def _get_blocked_for_symbol(risk: Dict[str, Any], symbol: str) -> bool:
    symbols = risk.get("symbols") or risk
    entry: Dict[str, Any] = {}
    if isinstance(symbols, dict):
        entry = symbols.get(symbol) or {}
    elif isinstance(symbols, list):
        for item in symbols:
            if isinstance(item, dict) and item.get("symbol") == symbol:
                entry = item
                break
    blocked = entry.get("blocked")
    if isinstance(blocked, bool):
        return blocked
    if isinstance(blocked, str):
        return blocked.lower() == "yes"
    return False


def _weight_bucket(w: float) -> str:
    if w >= 0.15:
        return "high"
    if w >= 0.05:
        return "med"
    return "low"


def _exploration_support_score(
    policy_level: Optional[str],
    scm_level: Optional[str],
    blocked: bool,
    weight: float = 0.0,
) -> float:
    # blocked trumps everything
    if blocked or policy_level == "blocked":
        return 0.0
    
    # Phase 4h: If SCM=off + high capital + not blocked → exploit_ready (support ~1.2)
    if scm_level == "off" and policy_level != "blocked" and weight >= 0.10:
        return 1.2
    
    if scm_level == "off":
        # no exploration sampling (but not exploit_ready due to low weight)
        return 0.0

    # reduced vs full combined with SCM
    if policy_level == "reduced":
        if scm_level in ("normal", "high"):
            return 1.3
        return 0.7

    if policy_level == "full":
        if scm_level in ("normal", "high", "low"):
            return 1.8

    # default
    return 0.6


def capital_exploration_alignment() -> None:
    capital_plan = _load_json(CAPITAL_PLAN_PATH)
    policy = _load_json(POLICY_PATH)
    scm = _load_json(SCM_PATH)
    risk = _load_json(RISK_SNAPSHOT_PATH)

    symbols_plan = capital_plan.get("symbols") or {}
    if not symbols_plan:
        print("No capital_plan.json found or no symbols in plan.")
        return

    print("CAPITAL vs EXPLORATION ALIGNMENT")
    print("======================================================================")
    meta = capital_plan.get("meta", {})
    print(f"Engine      : {meta.get('engine')}")
    print(f"GeneratedAt : {meta.get('generated_at')}")
    print()
    print("Symbol  Tier   Wght   Pol    SCM      Blk  Align    Notes")
    print("----------------------------------------------------------------------")

    for sym in sorted(symbols_plan.keys()):
        entry = symbols_plan[sym] or {}
        try:
            w = float(entry.get("weight", 0.0))
        except Exception:
            w = 0.0
        tier = entry.get("tier") or "—"
        pol_level = entry.get("policy_level") or "—"

        # SCM + blocked
        scm_level = _get_scm_for_symbol(scm, sym) or "—"
        is_blocked = _get_blocked_for_symbol(risk, sym)

        support = _exploration_support_score(pol_level, scm_level, is_blocked, w)
        wb = _weight_bucket(w)

        align = "OK"
        notes = []

        # Capital wants more than exploration supports
        if wb == "high" and support <= 0.5:
            align = "Cap>Exp"
            notes.append("high_w_low_support")
        # Exploration supports more than capital allocates
        elif wb == "low" and support >= 1.5:
            align = "Exp>Cap"
            notes.append("low_w_high_support")

        # Tier3 high weighting
        if tier == "tier3" and w > 0.10:
            notes.append("tier3_high_weight")

        # Blocked but non-trivial weight
        if (pol_level == "blocked" or is_blocked) and w > 0.02:
            notes.append("blocked_but_weight")

        # Phase 4h: SCM off but exploit_ready (instead of scm_off_high_weight)
        if scm_level == "off" and w >= 0.10 and pol_level != "blocked" and not is_blocked:
            notes.append("exploit_ready_scm_off")
        elif scm_level == "off" and w > 0.10:
            notes.append("scm_off_high_weight")

        note_str = ",".join(notes)

        print(
            f"{sym:7s} {tier:6s} {w:5.3f}  {pol_level:6s} {scm_level:8s} "
            f"{'Y' if is_blocked else 'N':3s} {align:7s}  {note_str}"
        )

    print()
    print("Legend:")
    print("  Align:")
    print("    OK      - capital allocation broadly matches exploration/risk support")
    print("    Cap>Exp - capital weight is high but exploration/risk support is low")
    print("    Exp>Cap - exploration/risk support is high but capital weight is low")
    print("  Notes:")
    print("    tier3_high_weight      - tier3 symbol with >10% capital weight")
    print("    blocked_but_weight     - blocked policy/risk but non-trivial weight")
    print("    scm_off_high_weight    - SCM=off but weight >10% (not exploit-ready)")
    print("    exploit_ready_scm_off  - SCM=off + weight >=10% + not blocked (exploit lane ready)")
    print()
    print("This tool is ADVISORY ONLY. It does NOT change any behavior.")
    print("======================================================================")
    

def main() -> None:
    capital_exploration_alignment()


if __name__ == "__main__":
    main()

