"""
Normal Lane Optimizer - Identifies symbols where normal lane significantly outperforms exploration lane.

This is advisory-only research to help identify execution optimization opportunities.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any

from engine_alpha.core.paths import REPORTS

ARE_PATH = REPORTS / "research" / "are_snapshot.json"
REFLECTION_INPUT_PATH = REPORTS / "gpt" / "reflection_input.json"


def load_json_or_empty(path: Path) -> Dict[str, Any]:
    """Load JSON file, return empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def analyze_normal_lane(are_path: Path = ARE_PATH) -> Dict[str, Any]:
    """
    Analyze symbols where normal lane significantly outperforms exploration lane.
    
    Args:
        are_path: Path to ARE snapshot
    
    Returns:
        Dict mapping symbol -> {exp_pf, norm_pf, ratio, note}
    
    Note:
        - exp_pf comes from ARE snapshot (short horizon exploration PF)
        - norm_pf comes from reflection_input.json (normal lane PF)
        - Both values are read directly, not recomputed
    """
    are_data = load_json_or_empty(are_path)
    are_symbols = are_data.get("symbols", {})
    
    # Load normal PF from reflection_input.json
    reflection_data = load_json_or_empty(REFLECTION_INPUT_PATH)
    reflection_symbols = reflection_data.get("symbols", {})
    
    if not are_symbols:
        return {}
    
    results = {}
    
    for sym, are_stats in are_symbols.items():
        # Get exploration PF from ARE (short horizon)
        short = are_stats.get("short", {})
        exp_pf = short.get("exp_pf")
        
        # Get normal PF from reflection_input.json
        reflection_stats = reflection_symbols.get(sym, {})
        norm_pf = reflection_stats.get("norm_pf")
        
        # If we don't have both, skip
        if exp_pf is None or norm_pf is None:
            continue
        
        # Handle string "inf" or None
        if exp_pf == "inf" or norm_pf == "inf":
            continue
        
        # Handle string "—" or "N/A"
        if exp_pf in ("—", "N/A") or norm_pf in ("—", "N/A"):
            continue
        
        try:
            exp_pf_val = float(exp_pf)
            norm_pf_val = float(norm_pf)
        except (ValueError, TypeError):
            continue
        
        # Only interested where norm_pf significantly > exp_pf
        # Threshold: norm_pf > exp_pf * 1.5 AND norm_pf > 1.5
        if norm_pf_val > exp_pf_val * 1.5 and norm_pf_val > 1.5:
            results[sym] = {
                "exp_pf": exp_pf_val,  # Actual exploration PF from ARE
                "norm_pf": norm_pf_val,  # Actual normal PF from reflection_input
                "ratio": norm_pf_val / (exp_pf_val + 1e-9),  # Ratio computed from actual values
                "note": "normal lane significantly outperforms exploration",
            }
    
    return results

