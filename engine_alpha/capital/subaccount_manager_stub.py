"""
Subaccount Manager Stub - Advisory subaccount allocation recommendations.

No real API calls or subaccount operations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
CAPITAL_DIR = ROOT / "reports" / "capital"


def list_subaccounts() -> List[str]:
    """Return stub list of subaccounts."""
    return ["MAIN", "EXPLORE", "VAULT"]


def recommend_subaccount_allocations(allocation_advice: Dict[str, Any]) -> Dict[str, Any]:
    """Recommend subaccount allocations based on tier and allocation advice."""
    allocations = allocation_advice.get("allocations", {})
    recommendations: Dict[str, Dict[str, List[str]]] = {
        "MAIN": [],
        "EXPLORE": [],
        "VAULT": [],
    }
    
    for symbol, alloc in allocations.items():
        tier = alloc.get("tier", "TIER2")
        target_pct = alloc.get("target_pct", 0.0)
        
        if tier == "TIER1":
            recommendations["MAIN"].append(symbol)
        elif tier == "TIER2":
            # Split between MAIN and EXPLORE
            if target_pct >= 0.15:
                recommendations["MAIN"].append(symbol)
            else:
                recommendations["EXPLORE"].append(symbol)
        else:  # TIER3
            recommendations["EXPLORE"].append(symbol)
    
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "subaccounts": list_subaccounts(),
        "recommendations": recommendations,
        "notes": [
            "These are advisory recommendations only.",
            "No real subaccounts have been created or allocated.",
            "Review before any real implementation.",
        ],
    }


def main() -> None:
    """Generate subaccount recommendations."""
    from engine_alpha.capital.capital_allocation_engine import (
        load_symbol_metrics,
        compute_portfolio_allocations,
    )
    
    metrics = load_symbol_metrics()
    if not metrics:
        print("⚠️  No symbol metrics found")
        return
    
    allocation_advice = compute_portfolio_allocations(metrics)
    recommendations = recommend_subaccount_allocations(allocation_advice)
    
    # Write to reports
    CAPITAL_DIR.mkdir(parents=True, exist_ok=True)
    output_path = CAPITAL_DIR / "subaccount_recommendations.json"
    output_path.write_text(json.dumps(recommendations, indent=2, sort_keys=True))
    
    print(f"✅ Subaccount recommendations written to: {output_path}")
    for subaccount, symbols in recommendations["recommendations"].items():
        if symbols:
            print(f"   {subaccount}: {len(symbols)} symbols")


if __name__ == "__main__":
    main()


