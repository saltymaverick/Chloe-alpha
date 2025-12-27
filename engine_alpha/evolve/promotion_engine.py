"""
Promotion Engine - Evaluate variant strategies and identify promotion candidates.

This module evaluates all mutation shadow strategies against the base strategy
and identifies which variants outperform the parent and should be considered
for promotion to active strategy status.

All evaluations are advisory-only. No automatic promotions are performed.
"""

from __future__ import annotations

import json
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from engine_alpha.core.paths import REPORTS, CONFIG

REGISTRY_PATH = CONFIG / "strategy_registry.yaml"
PROMOTION_PATH = REPORTS / "evolver" / "promotion_candidates.json"
VARIANT_DIR = REPORTS / "variant"
EVOLVER_OUTPUT_PATH = REPORTS / "evolver" / "evolver_output.json"
DRIFT_REPORT_PATH = REPORTS / "research" / "drift_report.json"
DREAM_OUTPUT_PATH = REPORTS / "gpt" / "dream_output.json"
QUALITY_SCORES_PATH = REPORTS / "gpt" / "quality_scores.json"
META_REASONER_PATH = REPORTS / "research" / "meta_reasoner_report.json"
ARE_SNAPSHOT_PATH = REPORTS / "research" / "are_snapshot.json"
ALPHA_BETA_PATH = REPORTS / "research" / "alpha_beta.json"
TRADES_PATH = REPORTS / "trades.jsonl"


def safe_load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file safely, return empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def load_variant_stats() -> Dict[str, List[Dict[str, Any]]]:
    """
    Load variant statistics from variant summary files.
    
    Returns:
        Dict mapping symbol -> list of variant stats
    """
    variants_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    
    if not VARIANT_DIR.exists():
        return variants_by_symbol
    
    # Load all variant summaries
    for summary_path in VARIANT_DIR.glob("*_summary.json"):
        try:
            summary = json.loads(summary_path.read_text())
            variant_id = summary.get("variant_id", "")
            symbol = summary.get("symbol", "")
            
            if not symbol or not variant_id:
                continue
            
            stats = summary.get("stats", {})
            mutations = summary.get("mutations", {})
            
            variant_data = {
                "variant_id": variant_id,
                "symbol": symbol,
                "mutations": mutations,
                "exp_trades": stats.get("exp_trades", 0),
                "exp_pf": stats.get("exp_pf"),
                "wins": stats.get("wins", 0),
                "losses": stats.get("losses", 0),
                "total_pnl": stats.get("total_pnl", 0.0),
            }
            
            variants_by_symbol.setdefault(symbol, []).append(variant_data)
        except Exception:
            continue
    
    return variants_by_symbol


def load_parent_stats() -> Dict[str, Dict[str, Any]]:
    """
    Load parent (base) strategy statistics from trades.jsonl.
    
    Returns:
        Dict mapping symbol -> parent stats
    """
    parent_stats: Dict[str, Dict[str, Any]] = {}
    
    if not TRADES_PATH.exists():
        return parent_stats
    
    # Read trades and compute parent stats per symbol
    symbol_trades: Dict[str, List[float]] = {}
    
    try:
        with TRADES_PATH.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    if trade.get("type") != "close":
                        continue
                    
                    symbol = trade.get("symbol")
                    pct = trade.get("pct")
                    
                    if symbol and pct is not None:
                        try:
                            pct_float = float(pct)
                            symbol_trades.setdefault(symbol, []).append(pct_float)
                        except (ValueError, TypeError):
                            continue
                except Exception:
                    continue
    except Exception:
        pass
    
    # Compute PF for each symbol
    for symbol, trades in symbol_trades.items():
        wins = [t for t in trades if t > 0]
        losses = [abs(t) for t in trades if t < 0]
        
        if losses:
            pf = sum(wins) / sum(losses) if sum(losses) > 0 else None
        else:
            pf = float("inf") if wins else None
        
        parent_stats[symbol] = {
            "exp_trades": len(trades),
            "exp_pf": pf,
            "wins": len(wins),
            "losses": len(losses),
        }
    
    return parent_stats


def load_drift_report() -> Dict[str, str]:
    """Load drift report and extract status per symbol."""
    drift_data = safe_load_json(DRIFT_REPORT_PATH)
    symbols = drift_data.get("symbols", {})
    
    drift_status: Dict[str, str] = {}
    for symbol, data in symbols.items():
        if isinstance(data, dict):
            drift_status[symbol] = data.get("status", "unknown")
    
    return drift_status


def load_dream_stats() -> Dict[str, Dict[str, int]]:
    """Load dream output and extract good/bad/improve counts per symbol."""
    dream_data = safe_load_json(DREAM_OUTPUT_PATH)
    reviews = dream_data.get("scenario_reviews", [])
    
    dream_stats: Dict[str, Dict[str, int]] = {}
    
    for review in reviews:
        if not isinstance(review, dict):
            continue
        
        symbol = review.get("symbol")
        label = review.get("label")
        
        if symbol and label:
            if symbol not in dream_stats:
                dream_stats[symbol] = {"good": 0, "bad": 0, "improve": 0}
            
            if label in dream_stats[symbol]:
                dream_stats[symbol][label] += 1
    
    return dream_stats


def load_quality_scores() -> Dict[str, float]:
    """Load quality scores per symbol."""
    quality_data = safe_load_json(QUALITY_SCORES_PATH)
    scores: Dict[str, float] = {}
    
    for symbol, data in quality_data.items():
        if isinstance(data, dict):
            score = data.get("score")
            if score is not None:
                try:
                    scores[symbol] = float(score)
                except (ValueError, TypeError):
                    continue
    
    return scores


def load_meta_reasoner_report() -> Dict[str, Any]:
    """Load meta reasoner report."""
    return safe_load_json(META_REASONER_PATH)


def load_alpha_beta() -> Dict[str, Dict[str, float]]:
    """Load alpha/beta decomposition per symbol."""
    ab_data = safe_load_json(ALPHA_BETA_PATH)
    symbols = ab_data.get("symbols", {})
    
    ab_by_symbol: Dict[str, Dict[str, float]] = {}
    for symbol, data in symbols.items():
        if isinstance(data, dict):
            ab_by_symbol[symbol] = {
                "alpha": data.get("alpha"),
                "beta": data.get("beta"),
            }
    
    return ab_by_symbol


def evaluate_candidate(
    symbol: str,
    variant_data: Dict[str, Any],
    parent_data: Dict[str, Any],
    drift_status: str,
    dream_stats: Dict[str, int],
    quality_score: Optional[float],
    alpha_beta: Dict[str, float],
    meta_report: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Evaluate if a variant is a promotion candidate.
    
    Returns:
        Candidate dict if eligible, None otherwise
    """
    # Basic filters
    variant_trades = variant_data.get("exp_trades", 0)
    if variant_trades < 12:  # Minimum sample size
        return None
    
    parent_pf = parent_data.get("exp_pf")
    variant_pf = variant_data.get("exp_pf")
    
    if parent_pf is None or variant_pf is None:
        return None
    
    # Handle infinity PF
    if variant_pf == float("inf"):
        if parent_pf == float("inf"):
            return None  # Both infinite, can't compare
        # Variant has infinite PF, parent doesn't - strong candidate
        pf_improvement = float("inf")
    elif parent_pf == float("inf"):
        return None  # Parent infinite, variant isn't - not better
    else:
        # Both finite, check improvement
        pf_improvement = variant_pf - parent_pf
        if variant_pf < parent_pf * 1.10:  # At least 10% improvement
            return None
    
    # Drift filter
    if drift_status == "degrading":
        return None
    
    # Dream filter
    symbol_dream = dream_stats.get(symbol, {})
    bad_count = symbol_dream.get("bad", 0)
    good_count = symbol_dream.get("good", 0)
    
    if bad_count > good_count:
        return None
    
    # Meta reasoner filter
    meta_issues = meta_report.get("issues", [])
    for issue in meta_issues:
        if not isinstance(issue, dict):
            continue
        issue_symbols = issue.get("symbols", [])
        if symbol in issue_symbols:
            issue_type = issue.get("type", "")
            if issue_type in ("tier_instability", "contradictory_tuning"):
                return None
    
    # Quality score filter (optional, if available)
    if quality_score is not None and quality_score < 50:
        return None
    
    # Build candidate dict
    candidate = {
        "symbol": symbol,
        "variant_id": variant_data.get("variant_id"),
        "parent_id": f"{symbol}_main",
        "stats": {
            "parent_exp_pf": parent_pf,
            "variant_exp_pf": variant_pf,
            "pf_improvement": pf_improvement if pf_improvement != float("inf") else "inf",
            "exp_trades": variant_trades,
            "drift": drift_status,
            "dream_stats": symbol_dream,
            "quality_score": quality_score,
            "beta": alpha_beta.get("beta"),
            "alpha": alpha_beta.get("alpha"),
        },
        "checks": {
            "dream_ok": bad_count <= good_count,
            "meta_ok": True,  # Already filtered above
            "no_contradictions": True,  # Already filtered above
            "drift_ok": drift_status != "degrading",
            "quality_ok": quality_score is None or quality_score >= 50,
        },
        "recommendation": "Candidate for promotion as primary strategy." if pf_improvement != float("inf") and pf_improvement > 0.2 else "Candidate for further testing; do not promote yet.",
    }
    
    return candidate


def run_promotion_engine() -> Dict[str, List[Dict[str, Any]]]:
    """
    Main orchestrator for promotion evaluation.
    
    Returns:
        Dict mapping symbol -> list of promotion candidates
    """
    # Load all data sources
    variant_stats = load_variant_stats()
    parent_stats = load_parent_stats()
    drift_status = load_drift_report()
    dream_stats = load_dream_stats()
    quality_scores = load_quality_scores()
    meta_report = load_meta_reasoner_report()
    alpha_beta = load_alpha_beta()
    
    promotions: Dict[str, List[Dict[str, Any]]] = {}
    
    # Evaluate each variant
    for symbol, variants in variant_stats.items():
        parent_data = parent_stats.get(symbol, {})
        
        if not parent_data:
            continue  # No parent stats, skip
        
        for variant_data in variants:
            symbol_drift = drift_status.get(symbol, "unknown")
            symbol_quality = quality_scores.get(symbol)
            symbol_ab = alpha_beta.get(symbol, {})
            
            candidate = evaluate_candidate(
                symbol,
                variant_data,
                parent_data,
                symbol_drift,
                dream_stats,
                symbol_quality,
                symbol_ab,
                meta_report,
            )
            
            if candidate:
                promotions.setdefault(symbol, []).append(candidate)
    
    # Save promotion candidates
    PROMOTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidates": promotions,
        "summary": {
            "total_symbols": len(promotions),
            "total_candidates": sum(len(c) for c in promotions.values()),
        },
    }
    PROMOTION_PATH.write_text(json.dumps(output, indent=2))
    
    return promotions

