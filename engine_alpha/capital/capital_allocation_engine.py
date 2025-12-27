"""
Capital Allocation Engine - Advisory capital allocation suggestions.

Read-only, advisory-only. No real fund allocation or exchange operations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional, List

ROOT = Path(__file__).resolve().parents[2]
GPT_REPORT_DIR = ROOT / "reports" / "gpt"
RESEARCH_DIR = ROOT / "reports" / "research"
CAPITAL_DIR = ROOT / "reports" / "capital"
CONFIG_DIR = ROOT / "config"


def load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def load_symbol_metrics() -> Dict[str, Dict[str, Any]]:
    """Load symbol metrics from reflection, quality scores, and ARE."""
    metrics: Dict[str, Dict[str, Any]] = {}
    
    # Load reflection input
    reflection_input = load_json(GPT_REPORT_DIR / "reflection_input.json")
    symbols_data = reflection_input.get("symbols", {})
    
    for sym, data in symbols_data.items():
        metrics[sym] = {
            "exploration_pf": data.get("exploration_pf"),
            "exploration_trades": data.get("exploration_trades", 0),
            "normal_pf": data.get("normal_pf"),
            "normal_trades": data.get("normal_trades", 0),
        }
    
    # Load quality scores if available
    quality_scores = load_json(GPT_REPORT_DIR / "quality_scores.json")
    for sym, score_data in quality_scores.items():
        if sym not in metrics:
            metrics[sym] = {}
        metrics[sym]["quality_score"] = score_data.get("score")
    
    # Load ARE snapshot if available
    are_snapshot = load_json(RESEARCH_DIR / "are_snapshot.json")
    for sym, are_data in are_snapshot.items():
        if sym not in metrics:
            metrics[sym] = {}
        metrics[sym]["are"] = are_data
    
    # Load tiers from reflection output or config
    reflection_output = load_json(GPT_REPORT_DIR / "reflection_output.json")
    symbol_insights = reflection_output.get("symbol_insights", {})
    
    for sym, insight in symbol_insights.items():
        if sym not in metrics:
            metrics[sym] = {}
        metrics[sym]["tier"] = insight.get("tier", "tier2")
    
    # Fallback to config if reflection output missing
    symbol_tiers = load_json(CONFIG_DIR / "symbol_tiers.yaml")
    tiers_config = symbol_tiers.get("tiers", {})
    for tier_name, symbols in tiers_config.items():
        for sym in symbols:
            if sym not in metrics:
                metrics[sym] = {}
            if "tier" not in metrics[sym]:
                metrics[sym]["tier"] = tier_name
    
    return metrics


def compute_symbol_allocation(symbol: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Compute advisory allocation for a single symbol."""
    tier = metrics.get("tier", "tier2").upper()
    quality_score = metrics.get("quality_score")
    exp_pf = metrics.get("exploration_pf")
    norm_pf = metrics.get("normal_pf")
    are_data = metrics.get("are", {})
    
    rationale: List[str] = []
    target_pct = 0.0
    
    # Base allocation by tier
    if tier == "TIER1":
        base_pct = 0.30
        rationale.append("Tier1 classification")
    elif tier == "TIER2":
        base_pct = 0.15
        rationale.append("Tier2 classification")
    else:  # TIER3
        base_pct = 0.05
        rationale.append("Tier3 classification")
    
    target_pct = base_pct
    
    # Adjust by quality score
    if quality_score is not None:
        if quality_score >= 70:
            target_pct *= 1.3
            rationale.append(f"high quality score ({quality_score})")
        elif quality_score < 20:
            target_pct *= 0.5
            rationale.append(f"low quality score ({quality_score})")
    
    # Adjust by exploration PF
    if exp_pf is not None:
        if exp_pf == float("inf") or exp_pf >= 2.0:
            target_pct *= 1.2
            rationale.append(f"strong exploration PF ({exp_pf:.2f})")
        elif exp_pf < 0.5:
            target_pct *= 0.7
            rationale.append(f"weak exploration PF ({exp_pf:.2f})")
    
    # Adjust by ARE long horizon if available
    if are_data:
        long_pf = are_data.get("long", {}).get("exp_pf")
        if long_pf is not None:
            if long_pf >= 1.5:
                target_pct *= 1.1
                rationale.append(f"strong long-horizon PF ({long_pf:.2f})")
            elif long_pf < 0.5:
                target_pct *= 0.8
                rationale.append(f"weak long-horizon PF ({long_pf:.2f})")
    
    # Clamp between 0 and 0.5 (max 50% per symbol)
    target_pct = max(0.0, min(0.5, target_pct))
    
    return {
        "symbol": symbol,
        "tier": tier,
        "quality_score": quality_score,
        "target_pct": round(target_pct, 4),
        "rationale": rationale,
    }


def compute_portfolio_allocations(metrics_dict: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Compute portfolio-wide allocation advice."""
    allocations = {}
    total_pct = 0.0
    
    for symbol, metrics in metrics_dict.items():
        allocation = compute_symbol_allocation(symbol, metrics)
        allocations[symbol] = allocation
        total_pct += allocation["target_pct"]
    
    # Normalize if total exceeds 1.0
    if total_pct > 1.0:
        scale = 1.0 / total_pct
        for symbol in allocations:
            allocations[symbol]["target_pct"] = round(
                allocations[symbol]["target_pct"] * scale, 4
            )
        total_pct = 1.0
    
    return {
        "generated_at": json.dumps({}).split('"')[0] if False else "",  # Placeholder
        "allocations": allocations,
        "total_allocated_pct": round(total_pct, 4),
        "unallocated_pct": round(1.0 - total_pct, 4),
        "notes": [
            "These are advisory allocations only.",
            "No real capital has been allocated.",
            "Review before any real implementation.",
        ],
    }


def main() -> None:
    """Generate allocation advice."""
    metrics = load_symbol_metrics()
    
    if not metrics:
        print("⚠️  No symbol metrics found")
        return
    
    allocations = compute_portfolio_allocations(metrics)
    
    # Write to reports
    CAPITAL_DIR.mkdir(parents=True, exist_ok=True)
    output_path = CAPITAL_DIR / "allocation_advice.json"
    
    # Add timestamp
    from datetime import datetime, timezone
    allocations["generated_at"] = datetime.now(timezone.utc).isoformat()
    
    output_path.write_text(json.dumps(allocations, indent=2, sort_keys=True))
    print(f"✅ Allocation advice written to: {output_path}")
    print(f"   Total symbols: {len(allocations['allocations'])}")
    print(f"   Total allocated: {allocations['total_allocated_pct']:.1%}")


if __name__ == "__main__":
    main()


