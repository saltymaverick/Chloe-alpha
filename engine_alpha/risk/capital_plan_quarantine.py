"""
Capital Plan Quarantine Overlay (Phase 5g)
-------------------------------------------

Applies quarantine weight adjustments to capital plan.

Reads:
- reports/risk/capital_plan.json (original allocator output)
- reports/risk/quarantine.json (quarantine state)

Writes:
- reports/risk/capital_plan_quarantine.json (modified plan with quarantine weights)

Safety:
- Never increases weights
- Never reduces weights below floor
- Renormalizes remaining weights to sum to 1.0
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List

from engine_alpha.core.paths import REPORTS

CAPITAL_PLAN_PATH = REPORTS / "risk" / "capital_plan.json"
QUARANTINE_STATE_PATH = REPORTS / "risk" / "quarantine.json"
OUTPUT_PATH = REPORTS / "risk" / "capital_plan_quarantine.json"


def _load_json(path: Path) -> Dict[str, Any]:
    """Safely load JSON file."""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def apply_quarantine_overlay() -> Dict[str, Any]:
    """
    Apply quarantine weight adjustments to capital plan.
    
    Returns:
        Modified capital plan dict
    """
    # Load original capital plan
    capital_plan = _load_json(CAPITAL_PLAN_PATH)
    if not capital_plan:
        return {}
    
    # Load quarantine state
    quarantine = _load_json(QUARANTINE_STATE_PATH)
    if not quarantine.get("enabled", False):
        # No quarantine active, return original plan
        return capital_plan
    
    weight_adjustments = quarantine.get("weight_adjustments", [])
    if not weight_adjustments:
        # No weight adjustments, return original plan
        return capital_plan
    
    # Build adjustment map
    adjustments_map = {adj["symbol"]: adj for adj in weight_adjustments}
    
    # Get symbols data (handle both formats)
    symbols_data = capital_plan.get("symbols", {}) or capital_plan.get("by_symbol", {})
    
    # Apply adjustments
    modified_symbols = {}
    total_weight_remaining = 0.0
    quarantined_symbols = set(adjustments_map.keys())
    
    for symbol, plan_data in symbols_data.items():
        raw_weight = plan_data.get("weight", 0.0) or plan_data.get("capital_weight", 0.0)
        
        if symbol in adjustments_map:
            # Apply quarantine adjustment
            adj = adjustments_map[symbol]
            multiplier = adj.get("multiplier", 0.00)
            floor = adj.get("weight_floor", 0.00)
            
            new_weight = max(floor, raw_weight * multiplier)
            
            # Update adjustment with actual raw_weight
            adj["raw_weight"] = raw_weight
            adj["new_weight"] = new_weight
            
            modified_symbols[symbol] = {
                **plan_data,
                "raw_weight": raw_weight,
                "weight": new_weight,
                "capital_weight": new_weight,
                "quarantined": True,
            }
        else:
            # Keep original weight (will be renormalized)
            modified_symbols[symbol] = {
                **plan_data,
                "raw_weight": raw_weight,
                "quarantined": False,
            }
            total_weight_remaining += raw_weight
    
    # Renormalize non-quarantined weights to sum to 1.0
    if total_weight_remaining > 0:
        scale_factor = 1.0 / total_weight_remaining
        
        for symbol, plan_data in modified_symbols.items():
            if symbol not in quarantined_symbols:
                raw_weight = plan_data.get("raw_weight", 0.0)
                new_weight = raw_weight * scale_factor
                plan_data["weight"] = new_weight
                plan_data["capital_weight"] = new_weight
    
    # Build output
    output = {
        **capital_plan,
        "symbols": modified_symbols,
        "by_symbol": modified_symbols,  # Support both formats
        "meta": {
            **(capital_plan.get("meta", {})),
            "quarantine_applied": True,
            "quarantine_ts": quarantine.get("ts"),
        },
    }
    
    # Write output
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    
    return output


def run_capital_plan_quarantine() -> Dict[str, Any]:
    """
    Run capital plan quarantine overlay.
    
    Returns:
        Modified capital plan dict
    """
    return apply_quarantine_overlay()

