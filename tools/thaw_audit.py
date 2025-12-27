"""
Thaw Audit Tool (Phase 3c)
--------------------------

This tool answers:
  • Which symbols are currently blocked by Exploration Policy V3?
  • Which symbols are logically ready to be thawed (based on PF_7D / PF_30D,
    capital stance, drift, and execution quality)?
  • What is the current tuning status per symbol (freeze/observe/etc) and
    whether a symbol is a candidate for future tuning thaw?

Inputs (all read-only):
  - reports/pf/pf_timeseries.json
  - reports/risk/capital_protection.json
  - reports/research/exploration_policy_v3.json
  - reports/research/drift_report.json
  - reports/research/execution_quality.json
  - reports/research/tuning_advisor.json
  - reports/research/tuning_self_eval.json

Outputs:
  - A console report with:
      EXPLORATION THAW STATUS
      TUNING THAW STATUS (ADVISORY)

All outputs are ADVISORY-ONLY and PAPER-SAFE.
Nothing in this tool changes any configs or behavior.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple


PF_TS_PATH = Path("reports/pf/pf_timeseries.json")
CAPITAL_PROTECTION_PATH = Path("reports/risk/capital_protection.json")
EXPL_POLICY_PATH = Path("reports/research/exploration_policy_v3.json")
DRIFT_PATH = Path("reports/research/drift_report.json")
EXECQL_PATH = Path("reports/research/execution_quality.json")
TUNING_ADVISOR_PATH = Path("reports/research/tuning_advisor.json")
TUNING_SELF_EVAL_PATH = Path("reports/research/tuning_self_eval.json")


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _get_pf_for_symbol(pf_ts: Dict[str, Any], symbol: str) -> Tuple[Optional[float], Optional[float]]:
    symbols = pf_ts.get("symbols", {})
    entry = symbols.get(symbol) or {}

    pf_7d = None
    pf_30d = None

    win_7d = entry.get("7d") or {}
    if win_7d.get("pf") is not None:
        try:
            pf_7d = float(win_7d["pf"])
        except Exception:
            pf_7d = None

    win_30d = entry.get("30d") or {}
    if win_30d.get("pf") is not None:
        try:
            pf_30d = float(win_30d["pf"])
        except Exception:
            pf_30d = None

    return pf_7d, pf_30d


def _get_capital_stance(cap: Dict[str, Any], symbol: str) -> Optional[str]:
    for entry in cap.get("symbols", []):
        if entry.get("symbol") == symbol:
            return entry.get("stance")
    return None


def _get_policy_for_symbol(policy: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    return (policy.get("symbols") or {}).get(symbol, {})


def _get_drift_for_symbol(drift: Dict[str, Any], symbol: str) -> Optional[str]:
    symbols = drift.get("symbols") or {}
    entry = symbols.get(symbol) or {}
    return entry.get("status")


def _get_execql_for_symbol(execql: Dict[str, Any], symbol: str) -> Optional[str]:
    # We expect execution_quality.json to be { "symbols": { sym: {...} } } or similar.
    symbols = execql.get("symbols") or execql
    if isinstance(symbols, dict):
        entry = symbols.get(symbol) or {}
    else:
        entry = {}
    return entry.get("overall_label")


def _get_tuning_for_symbol(
    tuning_adv: Dict[str, Any],
    tuning_eval: Dict[str, Any],
    symbol: str,
):
    """
    Extracts tuning recommendation and self-eval counts for a symbol.

    Both tuning_advisor.json and tuning_self_eval.json may be structured as:

      {
        "meta": { ... },
        "symbols": [
           { "symbol": "ADAUSDT", "rec": "freeze", "improved": 2, "degraded": 13, ... },
           ...
        ]
      }

    or as a simple dict keyed by symbol.
    """
    rec: Optional[str] = None
    improved: Optional[int] = None
    degraded: Optional[int] = None
    inconclusive: Optional[int] = None

    # --- Advisor ---
    # Handle structure: {"advisor": {"SYMBOL": {...}}} or {"symbols": [...]} or {"SYMBOL": {...}}
    advisor_data = tuning_adv.get("advisor") or tuning_adv.get("symbols") or tuning_adv
    entry_adv: Dict[str, Any] = {}
    if isinstance(advisor_data, dict):
        # dict keyed by symbol
        entry_adv = advisor_data.get(symbol) or {}
    elif isinstance(advisor_data, list):
        # list of {symbol: ..., rec: ...}
        for item in advisor_data:
            if isinstance(item, dict) and item.get("symbol") == symbol:
                entry_adv = item
                break
    
    # Get recommendation (may be "recommendation" or "rec")
    rec = entry_adv.get("recommendation") or entry_adv.get("rec")
    
    # Get self-eval from advisor entry first (it's embedded), then fall back to tuning_eval
    self_eval_adv = entry_adv.get("self_eval") or {}
    if isinstance(self_eval_adv, dict):
        try:
            improved = int(self_eval_adv.get("improved")) if self_eval_adv.get("improved") is not None else None
        except Exception:
            improved = None
        try:
            degraded = int(self_eval_adv.get("degraded")) if self_eval_adv.get("degraded") is not None else None
        except Exception:
            degraded = None
        try:
            inconclusive = int(self_eval_adv.get("inconclusive")) if self_eval_adv.get("inconclusive") is not None else None
        except Exception:
            inconclusive = None
    else:
        # Fall back to tuning_eval if self_eval not in advisor entry
        symbols_eval = tuning_eval.get("symbols") or tuning_eval
        entry_eval: Dict[str, Any] = {}
        if isinstance(symbols_eval, dict):
            entry_eval = symbols_eval.get(symbol) or {}
        elif isinstance(symbols_eval, list):
            for item in symbols_eval:
                if isinstance(item, dict) and item.get("symbol") == symbol:
                    entry_eval = item
                    break
        
        try:
            improved = int(entry_eval.get("improved")) if entry_eval.get("improved") is not None else None
        except Exception:
            improved = None
        try:
            degraded = int(entry_eval.get("degraded")) if entry_eval.get("degraded") is not None else None
        except Exception:
            degraded = None
        try:
            inconclusive = int(entry_eval.get("inconclusive")) if entry_eval.get("inconclusive") is not None else None
        except Exception:
            inconclusive = None

    return rec, improved, degraded, inconclusive


def _fmt(x: Any, digits: int = 3) -> str:
    if x is None:
        return "—"
    try:
        return f"{float(x):.{digits}f}"
    except Exception:
        return str(x)


def thaw_audit() -> None:
    pf_ts = _load_json(PF_TS_PATH) or {}
    cap = _load_json(CAPITAL_PROTECTION_PATH) or {}
    policy = _load_json(EXPL_POLICY_PATH) or {}
    drift = _load_json(DRIFT_PATH) or {}
    execql = _load_json(EXECQL_PATH) or {}
    tuning_adv = _load_json(TUNING_ADVISOR_PATH) or {}
    tuning_eval = _load_json(TUNING_SELF_EVAL_PATH) or {}

    symbol_set: Set[str] = set()

    # Assemble universe from PF, capital protection, and policy
    for sym in (pf_ts.get("symbols") or {}).keys():
        symbol_set.add(sym)
    for entry in cap.get("symbols", []):
        sym = entry.get("symbol")
        if sym:
            symbol_set.add(sym)
    for sym in (policy.get("symbols") or {}).keys():
        symbol_set.add(sym)

    # Filter to USDT symbols, uppercase
    filtered: Set[str] = set()
    for s in symbol_set:
        if isinstance(s, str) and s.endswith("USDT") and s.isupper():
            filtered.add(s)
    symbol_set = filtered

    print("THAW AUDIT – PHASE 3c")
    print("======================================================================")
    print()

    # --- Exploration thaw status ---
    print("EXPLORATION THAW STATUS")
    print("----------------------------------------------------------------------")
    print("Symbol  Blk  Thaw?  PF_7D  PF_30D  CapSt  Drift       ExecQL   Policy")
    print("----------------------------------------------------------------------")

    for sym in sorted(symbol_set):
        pf_7d, pf_30d = _get_pf_for_symbol(pf_ts, sym)
        cap_stance = _get_capital_stance(cap, sym)
        pol = _get_policy_for_symbol(policy, sym)
        level = pol.get("level")
        allow = pol.get("allow_new_entries")
        drift_status = _get_drift_for_symbol(drift, sym)
        exec_label = _get_execql_for_symbol(execql, sym)

        blocked = (level == "blocked") or (allow is False)

        # Thaw-ready conditions (advisory):
        cond_pf = (pf_7d is not None and pf_7d >= 1.0) and (pf_30d is not None and pf_30d >= 0.95)
        cond_cap = (cap_stance is None) or (cap_stance != "halt")
        cond_exec = (exec_label is None) or (exec_label != "hostile")
        cond_drift = (drift_status is None) or (drift_status != "degrading")

        thaw_ready = cond_pf and cond_cap and cond_exec and cond_drift

        blk_flag = "Y" if blocked else "N"
        thaw_flag = "Y" if thaw_ready else "N"

        print(
            f"{sym:7s} {blk_flag:3s}  {thaw_flag:4s}  "
            f"{_fmt(pf_7d):6s} {_fmt(pf_30d):7s}  "
            f"{(cap_stance or '—'):5s}  {(drift_status or '—'):10s}  "
            f"{(exec_label or '—'):7s}  {(level or '—'):6s}"
        )

    print()
    print("Exploration thaw logic (advisory):")
    print("  • thaw_ready == Y when:")
    print("      PF_7D ≥ 1.00 AND PF_30D ≥ 0.95")
    print("      AND capital stance != 'halt'")
    print("      AND ExecQL != 'hostile'")
    print("      AND Drift != 'degrading'")
    print("  • blocked == Y when policy.level='blocked' or allow_new_entries=False.")
    print()

    # --- Tuning thaw status ---
    print("TUNING THAW STATUS (ADVISORY)")
    print("----------------------------------------------------------------------")
    print("Symbol  Rec      Imp   Deg   Inconcl   ThawHint")
    print("----------------------------------------------------------------------")

    for sym in sorted(symbol_set):
        rec, improved, degraded, inconcl = _get_tuning_for_symbol(tuning_adv, tuning_eval, sym)

        thaw_hint = "frozen"
        if rec != "freeze":
            thaw_hint = "unfrozen"
        if rec == "freeze" and improved is not None and degraded is not None:
            if improved >= degraded:
                thaw_hint = "candidate"

        print(
            f"{sym:7s} {(rec or '—'):7s} "
            f"{(str(improved) if improved is not None else '—'):4s} "
            f"{(str(degraded) if degraded is not None else '—'):5s} "
            f"{(str(inconcl) if inconcl is not None else '—'):7s}   "
            f"{thaw_hint:9s}"
        )

    print()
    print("Tuning thaw logic (advisory):")
    print("  • Rec == 'freeze' and improved < degraded → stay frozen.")
    print("  • Rec != 'freeze' → tuning logically thawed (observe/relax).")
    print("  • Rec == 'freeze' but improved ≥ degraded → 'candidate' for future thaw")
    print("    once PF windows and Meta-Reasoner also agree.")
    print()
    print("Note: This report is informational only. It does NOT change configs or behavior.")
    print("======================================================================")


def main():
    thaw_audit()


if __name__ == "__main__":
    main()

