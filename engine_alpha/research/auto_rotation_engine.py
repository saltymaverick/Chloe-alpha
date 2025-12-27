"""
Auto-Rotation Engine - Generates advisory recommendations for capital rotation between symbols.

Uses tiers, PF, drift, microstructure, and execution quality to suggest overweight/underweight/hold.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any

from engine_alpha.core.paths import REPORTS

ARE_PATH = REPORTS / "research" / "are_snapshot.json"
DRIFT_PATH = REPORTS / "research" / "drift_report.json"
MICRO_PATH = REPORTS / "research" / "microstructure_snapshot_15m.json"
EXEC_PATH = REPORTS / "research" / "execution_quality.json"
TIERS_PATH = REPORTS / "gpt" / "reflection_output.json"


def load_json_or_empty(path: Path) -> Dict[str, Any]:
    """Load JSON file, return empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def compute_rotation_recommendations() -> Dict[str, Any]:
    """
    Compute rotation recommendations based on tiers, PF, drift, microstructure, and execution quality.
    
    Returns:
        Dict mapping symbol -> {tier, drift, exec_label, short_pf, long_pf, rotation, notes}
    """
    are = load_json_or_empty(ARE_PATH)
    drift = load_json_or_empty(DRIFT_PATH)
    micro = load_json_or_empty(MICRO_PATH)
    execq = load_json_or_empty(EXEC_PATH)
    tiers_data = load_json_or_empty(TIERS_PATH)
    
    # Build tier mapping
    tiers = {}
    for t, syms in tiers_data.get("tiers", {}).items():
        if isinstance(syms, list):
            for s in syms:
                tiers[s] = t
    
    # Get symbols from ARE
    symbols = are.get("symbols", {})
    if not symbols:
        return {}
    
    recs = {}
    
    for sym, stats in symbols.items():
        t = tiers.get(sym, "unknown")
        
        # Get drift status
        drift_symbols = drift.get("symbols", {})
        drift_status = drift_symbols.get(sym, {}).get("status") or drift_symbols.get(sym, {}).get("drift_state", "unknown")
        
        # Get execution quality label
        exec_data = execq.get("data", {})
        eq_info = exec_data.get(sym, {})
        eq_label = "unknown"
        
        if eq_info and isinstance(eq_info, dict):
            # Find dominant regime label (most trades)
            best_trades = 0
            for reg, info in eq_info.items():
                if isinstance(info, dict):
                    trades = info.get("trades", 0)
                    if trades > best_trades:
                        best_trades = trades
                        eq_label = info.get("label", "unknown")
        
        # Get PF stats
        short = stats.get("short", {})
        long_horizon = stats.get("long", {})
        short_pf = short.get("exp_pf")
        long_pf = long_horizon.get("exp_pf")
        
        rec = {
            "tier": t,
            "drift": drift_status,
            "exec_label": eq_label,
            "short_pf": short_pf,
            "long_pf": long_pf,
            "rotation": "hold",
            "notes": [],
        }
        
        # Simple heuristic:
        # - tier1 + friendly + improving/stable drift → overweight
        # - tier3 + hostile → underweight
        if t == "tier1" and eq_label == "friendly" and drift_status in ("improving", "stable"):
            rec["rotation"] = "overweight"
            rec["notes"].append("Strong symbol: consider increasing allocation.")
        elif t == "tier3" and eq_label == "hostile":
            rec["rotation"] = "underweight"
            rec["notes"].append("Weak & hostile: consider reducing allocation.")
        else:
            rec["rotation"] = "hold"
        
        recs[sym] = rec
    
    return recs

