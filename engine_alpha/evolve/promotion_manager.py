from __future__ import annotations
import json, datetime
from pathlib import Path
from typing import Dict, Any

from engine_alpha.core.paths import REPORTS

NOW = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()

def _read_json(p: Path) -> Dict[str, Any] | None:
    try:
        if p.exists():
            return json.loads(p.read_text())
    except Exception:
        pass
    return None

def _append_proposal(obj: Dict[str, Any]) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / "promotion_proposals.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(obj) + "\n")

def run_once(min_trades: int = 100, uplift_min: float = 0.05) -> Dict[str, int]:
    """Evaluate latest evolver snapshot and append PROMOTE/HOLD proposal.
       Returns summary counts dict.
    """
    snap = _read_json(REPORTS / "evolver_snapshot.json")
    pf_adj = _read_json(REPORTS / "pf_local_adj.json")
    baseline = None
    if pf_adj and isinstance(pf_adj.get("pf", None), (int, float)):
        baseline = float(pf_adj["pf"])

    # default HOLD if snapshot missing or malformed
    if not isinstance(snap, dict):
        _append_proposal({
            "ts": NOW(), "recommendation": "HOLD",
            "reason": "no_snapshot", "baseline": baseline
        })
        return {"total": 1, "promote": 0, "hold": 1}

    # try to read best candidate PF and trades from snapshot variations
    best_pf = None
    trades = snap.get("tested") or snap.get("best_trades") or 0
    child = snap.get("child_name")

    # support both formats: {best_pf_cf: x} or {grid_best: {pf: x, params:{...}}}
    if isinstance(snap.get("best_pf_cf", None), (int, float)):
        best_pf = float(snap["best_pf_cf"])
    elif isinstance(snap.get("grid_best", {}), dict):
        gb = snap["grid_best"]
        if isinstance(gb.get("pf"), (int, float)):
            best_pf = float(gb["pf"])
        if not child and isinstance(gb.get("params"), dict):
            # derive a simple name if not provided
            p = gb["params"]
            child = f"Echo-{int(p.get('entry_min',0)*1000):03d}-{int(p.get('exit_min',0)*1000):03d}-{int(p.get('flip_min',0)*1000):03d}"

    # compute uplift if possible
    uplift = None
    if best_pf is not None and baseline is not None:
        uplift = best_pf - baseline

    decision = "HOLD"
    reason = "insufficient_data"
    if best_pf is not None and baseline is not None:
        if trades >= min_trades and (best_pf - baseline) >= uplift_min:
            decision, reason = "PROMOTE", "meets_criteria"
        else:
            reason = "insufficient uplift or trades"

    _append_proposal({
        "ts": NOW(),
        "child": child,
        "pf_cf": best_pf,
        "uplift": uplift,
        "baseline": baseline,
        "trades": trades,
        "recommendation": decision,
        "reason": reason
    })
    return {"total": 1, "promote": 1 if decision == "PROMOTE" else 0, "hold": 1 if decision == "HOLD" else 0}
