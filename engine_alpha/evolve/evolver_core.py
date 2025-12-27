"""
Evolver Core - Tier-Based Evolver for symbol promotion/demotion.

This module evaluates symbols based on tiers, PF, quality scores, and ARE stats
to produce advisory promotion/demotion suggestions. All outputs are READ-ONLY
and ADVISORY ONLY - no config auto-writes, no exchange calls, no live behavior changes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
GPT_REPORT_DIR = ROOT / "reports" / "gpt"
ARE_REPORT_DIR = ROOT / "reports" / "research"
CONFIG_DIR = ROOT / "config"

REFLECTION_OUTPUT_PATH = GPT_REPORT_DIR / "reflection_output.json"
QUALITY_SCORES_PATH = GPT_REPORT_DIR / "quality_scores.json"
ARE_SNAPSHOT_PATH = ARE_REPORT_DIR / "are_snapshot.json"
SELF_EVAL_PATH = ARE_REPORT_DIR / "tuning_self_eval.json"
TUNING_RULES_PATH = CONFIG_DIR / "tuning_rules.yaml"

# Sample-size thresholds
MIN_EXPL_FOR_EVOLVER = 20  # Minimum exploration closes required for evolution decisions


def safe_load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file safely, returning empty dict on error."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def safe_load_yaml(path: Path) -> Dict[str, Any]:
    """Load YAML file safely, returning empty dict on error."""
    if not path.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def load_self_eval_summary() -> Dict[str, Dict[str, int]]:
    """Load tuning self-eval summary for scoring."""
    if not SELF_EVAL_PATH.exists():
        return {}
    try:
        data = json.loads(SELF_EVAL_PATH.read_text())
        return data.get("summary", {})
    except Exception:
        return {}


def load_inputs() -> Dict[str, Dict[str, Any]]:
    """
    Load all input files and return a dict of per-symbol metrics.
    
    Returns:
        Dict mapping symbol -> metrics dict with keys:
            - tier: str (tier1/tier2/tier3)
            - exp_pf: Optional[float]
            - norm_pf: Optional[float]
            - exp_trades: int
            - norm_trades: int
            - quality_score: Optional[float]
            - are_long: Optional[Dict] (ARE long-horizon stats)
            - are_medium: Optional[Dict] (ARE medium-horizon stats)
            - are_short: Optional[Dict] (ARE short-horizon stats)
    """
    metrics: Dict[str, Dict[str, Any]] = {}
    
    # Load reflection output (tiers + symbol insights)
    reflection_output = safe_load_json(REFLECTION_OUTPUT_PATH)
    symbol_insights = reflection_output.get("symbol_insights", {})
    tiers = reflection_output.get("tiers", {})
    
    # Build symbol -> tier mapping from tiers dict (v2/v3 format)
    symbol_to_tier: Dict[str, str] = {}
    for tier_name, symbol_list in tiers.items():
        if isinstance(symbol_list, list):
            for symbol in symbol_list:
                symbol_to_tier[symbol] = tier_name
    
    # Initialize metrics for all symbols found in reflection
    for symbol, insight in symbol_insights.items():
        # Handle both v1 format (dict) and v2/v3 format (list)
        if isinstance(insight, dict):
            # v1 format: insight is a dict with "tier" key
            tier = insight.get("tier", "tier2")
        elif isinstance(insight, list):
            # v2/v3 format: insight is a list, tier comes from tiers dict
            tier = symbol_to_tier.get(symbol, "tier2")
        else:
            # Fallback: try to get tier from tiers dict
            tier = symbol_to_tier.get(symbol, "tier2")
        
        metrics[symbol] = {
            "tier": tier,
            "exp_pf": None,
            "norm_pf": None,
            "exp_trades": 0,
            "norm_trades": 0,
            "quality_score": None,
            "are_long": None,
            "are_medium": None,
            "are_short": None,
        }
    
    # Also add symbols from tiers dict that might not be in symbol_insights
    for tier_name, symbol_list in tiers.items():
        if isinstance(symbol_list, list):
            for symbol in symbol_list:
                if symbol not in metrics:
                    metrics[symbol] = {
                        "tier": tier_name,
                        "exp_pf": None,
                        "norm_pf": None,
                        "exp_trades": 0,
                        "norm_trades": 0,
                        "quality_score": None,
                        "are_long": None,
                        "are_medium": None,
                        "are_short": None,
                    }
    
    # Load quality scores
    quality_scores = safe_load_json(QUALITY_SCORES_PATH)
    for symbol, data in quality_scores.items():
        if symbol not in metrics:
            metrics[symbol] = {
                "tier": "tier2",  # Default tier
                "exp_pf": None,
                "norm_pf": None,
                "exp_trades": 0,
                "norm_trades": 0,
                "quality_score": None,
                "are_long": None,
                "are_medium": None,
                "are_short": None,
            }
        metrics[symbol]["quality_score"] = data.get("score")
    
    # Load ARE snapshot
    are_snapshot = safe_load_json(ARE_SNAPSHOT_PATH)
    are_symbols = are_snapshot.get("symbols", {})
    
    for symbol, are_data in are_symbols.items():
        if symbol not in metrics:
            metrics[symbol] = {
                "tier": "tier2",
                "exp_pf": None,
                "norm_pf": None,
                "exp_trades": 0,
                "norm_trades": 0,
                "quality_score": None,
                "are_long": None,
                "are_medium": None,
                "are_short": None,
            }
        
        # Extract ARE horizon stats
        metrics[symbol]["are_long"] = are_data.get("long")
        metrics[symbol]["are_medium"] = are_data.get("medium")
        metrics[symbol]["are_short"] = are_data.get("short")
        
        # Extract PF and trades from ARE long horizon (most comprehensive)
        long_stats = are_data.get("long", {})
        if long_stats:
            metrics[symbol]["exp_pf"] = long_stats.get("exp_pf")
            metrics[symbol]["exp_trades"] = long_stats.get("exp_trades_count", 0)
    
    # Also try to get normal PF/trades from reflection_input if available
    reflection_input = safe_load_json(GPT_REPORT_DIR / "reflection_input.json")
    symbols_data = reflection_input.get("symbols", {})
    
    for symbol, data in symbols_data.items():
        if symbol not in metrics:
            continue
        
        # Update exp_pf/exp_trades if not already set from ARE
        if metrics[symbol]["exp_pf"] is None:
            metrics[symbol]["exp_pf"] = data.get("exploration_pf")
        if metrics[symbol]["exp_trades"] == 0:
            metrics[symbol]["exp_trades"] = data.get("exploration_trades", 0)
        
        # Set normal PF/trades
        metrics[symbol]["norm_pf"] = data.get("normal_pf")
        metrics[symbol]["norm_trades"] = data.get("normal_trades", 0)
    
    return metrics


def evaluate_symbol(symbol: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluate a symbol for promotion/demotion and suggest tuning adjustments.
    
    Args:
        symbol: Symbol string (e.g., "ETHUSDT")
        metrics: Metrics dict from load_inputs()
    
    Returns:
        Dict with evaluation results:
            - symbol: str
            - tier: str (current tier)
            - promotion_candidate: bool
            - demotion_candidate: bool
            - suggested_conf_min_delta: float
            - suggested_exploration_cap_delta: int
            - notes: List[str]
    """
    tier = metrics.get("tier", "tier2")
    exp_pf = metrics.get("exp_pf")
    norm_pf = metrics.get("norm_pf")
    exp_trades = metrics.get("exp_trades", 0)
    norm_trades = metrics.get("norm_trades", 0)
    quality_score = metrics.get("quality_score")
    are_long = metrics.get("are_long", {})
    
    # Load promotion rules from tuning_rules.yaml
    tuning_rules = safe_load_yaml(TUNING_RULES_PATH)
    promotion_rules = tuning_rules.get("promotion_rules", {})
    to_tier1 = promotion_rules.get("to_tier1", {})
    to_tier3 = promotion_rules.get("to_tier3", {})
    
    result = {
        "symbol": symbol,
        "tier": tier,
        "promotion_candidate": False,
        "demotion_candidate": False,
        "suggested_conf_min_delta": 0.0,
        "suggested_exploration_cap_delta": 0,
        "notes": [],
    }
    
    # Use ARE long-horizon PF if available, otherwise fall back to exp_pf
    effective_exp_pf = are_long.get("exp_pf") if are_long else exp_pf
    effective_exp_trades = are_long.get("exp_trades_count", 0) if are_long else exp_trades
    
    # Load trade counts for sample-size gating
    from engine_alpha.research.trade_stats import load_trade_counts
    trade_counts = load_trade_counts()
    counts = trade_counts.get(symbol, {})
    expl = counts.get("exploration_closes", 0)
    
    # Check sample size before considering promotion
    can_promote = expl >= MIN_EXPL_FOR_EVOLVER
    if not can_promote:
        result["notes"].append(
            f"Under-sampled for evolution: exploration_closes={expl} < {MIN_EXPL_FOR_EVOLVER}"
        )
    
    # Incorporate tuning self-eval into scoring
    self_eval_summary = load_self_eval_summary()
    sym_eval = self_eval_summary.get(symbol, {})
    improved = sym_eval.get("improved", 0)
    degraded = sym_eval.get("degraded", 0)
    
    # Apply tuning bonus/penalty to promotion/demotion logic
    tuning_bonus = 0.0
    if improved >= 2 and degraded == 0:
        tuning_bonus = 0.1  # Small positive bonus for proven tuning success
        result["notes"].append(f"Tuning self-eval: {improved} improved cycles (net positive)")
    elif degraded >= 2 and improved == 0:
        tuning_bonus = -0.1  # Small penalty for proven tuning harm
        result["notes"].append(f"Tuning self-eval: {degraded} degraded cycles (net negative)")
        # Do not consider for promotion if tuning is clearly harmful
        if tier == "tier2":
            result["notes"].append("Promotion blocked: tuning history shows net harm")
    
    # Promotion logic: Tier2 -> Tier1
    if tier == "tier2":
        exp_pf_min = to_tier1.get("exp_pf_min", 1.5)
        exp_trades_min = to_tier1.get("exp_trades_min", 6)
        norm_pf_min = to_tier1.get("norm_pf_min", 1.0)
        norm_trades_min = to_tier1.get("norm_trades_min", 2)
        
        pf_ok = effective_exp_pf is not None and effective_exp_pf >= exp_pf_min
        trades_ok = effective_exp_trades >= exp_trades_min
        norm_pf_ok = norm_pf is not None and norm_pf >= norm_pf_min
        norm_trades_ok = norm_trades >= norm_trades_min
        quality_ok = quality_score is None or quality_score >= 70.0
        
        # Block promotion if tuning history shows net harm
        tuning_ok = not (degraded >= 2 and improved == 0)
        
        if pf_ok and trades_ok and norm_pf_ok and norm_trades_ok and quality_ok and tuning_ok and can_promote:
            result["promotion_candidate"] = True
            result["notes"].append(
                f"Promotion candidate: exp_pf={effective_exp_pf:.2f} >= {exp_pf_min}, "
                f"exp_trades={effective_exp_trades} >= {exp_trades_min}, "
                f"norm_pf={norm_pf:.2f} >= {norm_pf_min}, quality_score={quality_score}"
            )
            # Suggest positive tuning adjustments
            result["suggested_conf_min_delta"] = -0.02
            result["suggested_exploration_cap_delta"] = 1
    
    # Demotion logic: Tier1 -> Tier2 or Tier2 -> Tier3
    if tier in ("tier1", "tier2"):
        # Check for Tier2 -> Tier3 demotion
        exp_pf_max = to_tier3.get("exp_pf_max", 0.0)
        exp_trades_min = to_tier3.get("exp_trades_min", 7)
        norm_pf_max = to_tier3.get("norm_pf_max", 0.5)
        
        pf_bad = effective_exp_pf is not None and effective_exp_pf <= exp_pf_max
        trades_enough = effective_exp_trades >= exp_trades_min
        norm_pf_bad = norm_pf is not None and norm_pf <= norm_pf_max
        
        if pf_bad and trades_enough and norm_pf_bad:
            result["demotion_candidate"] = True
            target_tier = "tier3" if tier == "tier2" else "tier2"
            result["notes"].append(
                f"Demotion candidate ({tier} -> {target_tier}): "
                f"exp_pf={effective_exp_pf:.2f} <= {exp_pf_max}, "
                f"exp_trades={effective_exp_trades} >= {exp_trades_min}, "
                f"norm_pf={norm_pf:.2f} <= {norm_pf_max}"
            )
            # Suggest negative tuning adjustments
            result["suggested_conf_min_delta"] = 0.02
            result["suggested_exploration_cap_delta"] = -1
    
    # Add stability check: downgrade symbols with spiky short-term PF but weak long-term PF
    are_short = metrics.get("are_short", {})
    if are_long and are_short:
        long_pf = are_long.get("exp_pf")
        short_pf = are_short.get("exp_pf")
        
        if long_pf is not None and short_pf is not None:
            if short_pf > 2.0 and long_pf < 1.0:
                result["notes"].append(
                    f"Stability warning: short-term PF={short_pf:.2f} but long-term PF={long_pf:.2f} "
                    "(spiky performance, not promoting)"
                )
                result["promotion_candidate"] = False
    
    # Add notes for symbols with no change
    if not result["promotion_candidate"] and not result["demotion_candidate"]:
        result["notes"].append("No tier change recommended at this time")
    
    return result


def evolve_all_symbols(metrics_dict: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Evaluate all symbols and return complete evolver output.
    
    Args:
        metrics_dict: Dict from load_inputs()
    
    Returns:
        Dict with:
            - generated_at: ISO timestamp
            - symbols: Dict[symbol, evaluation_result]
            - summary: List[str] (human-readable summary lines)
    """
    results: Dict[str, Dict[str, Any]] = {}
    summary: List[str] = []
    
    for symbol, metrics in metrics_dict.items():
        evaluation = evaluate_symbol(symbol, metrics)
        results[symbol] = evaluation
        
        # Build summary line
        tier = evaluation["tier"]
        if evaluation["promotion_candidate"]:
            summary.append(f"{symbol}: {tier}, promotion_candidate=true (flagged for promotion)")
        elif evaluation["demotion_candidate"]:
            summary.append(f"{symbol}: {tier}, demotion_candidate=true (flagged as persistently weak)")
        else:
            summary.append(f"{symbol}: {tier}, no change")
    
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbols": results,
        "summary": summary,
    }


