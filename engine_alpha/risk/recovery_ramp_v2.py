"""
Recovery Ramp V2 Engine (Phase 5H.2)
-------------------------------------

Per-symbol recovery ramp evaluator that allows micro recovery entries
per coin under strict caps, while keeping exploit/probe/promotion disabled.

Safety:
- PAPER-only
- Restrictive-only (never enables exploit/probe/promotion)
- Never bypasses quarantine or policy blocks
- Deterministic and auditable
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

from engine_alpha.core.paths import REPORTS
from engine_alpha.data.price_feed_health import is_price_feed_ok

# Paths
CAPITAL_PROTECTION_PATH = REPORTS / "risk" / "capital_protection.json"
PF_TIMESERIES_PATH = REPORTS / "pf" / "pf_timeseries.json"
QUARANTINE_PATH = REPORTS / "risk" / "quarantine.json"
CAPITAL_PLAN_PATH = REPORTS / "risk" / "capital_plan.json"
CAPITAL_PLAN_QUARANTINE_PATH = REPORTS / "risk" / "capital_plan_quarantine.json"
LIVE_CANDIDATES_PATH = REPORTS / "risk" / "live_candidates.json"
EXECUTION_QUALITY_PATH = REPORTS / "research" / "execution_quality.json"
PF_VALIDITY_PATH = REPORTS / "risk" / "pf_validity.json"
RECOVERY_RAMP_V2_STATE_PATH = REPORTS / "risk" / "recovery_ramp_v2.json"

# Thresholds
MIN_SYMBOL_SCORE = 0.65
CHAMPION_OVERRIDE_SCORE = 0.55
CHAMPION_PF_THRESHOLD = 1.10
GLOBAL_RISK_CAP_NOTIONAL_USD = 10.0
MAX_POSITIONS = 1
COOLDOWN_SECONDS = 1800


def _load_json(path: Path) -> Dict[str, Any]:
    """Safely load JSON file."""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_json(path: Path, data: Dict[str, Any]) -> None:
    """Safely save JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def _parse_timestamp(ts_str: str) -> datetime:
    """Parse ISO timestamp."""
    try:
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _check_price_feed(symbol: str, max_age_seconds: int = 900) -> tuple[bool, str, Dict[str, Any]]:
    """
    Check if symbol has valid price feed with staleness check.
    
    Uses unified PriceFeedHealth module (single source of truth).
    
    Args:
        symbol: Trading symbol
        max_age_seconds: Maximum age in seconds for price feed to be considered valid (default 900 = 15 min)
    
    Returns:
        Tuple of (is_valid, reason, meta_dict)
        - is_valid: True if feed is OK
        - reason: Short reason string
        - meta_dict: Rich metadata for debugging
    """
    is_ok, meta = is_price_feed_ok(symbol, max_age_seconds=max_age_seconds, require_price=True)
    
    if is_ok:
        return True, "price_feed_ok", meta
    
    # Build reason from errors
    errors = meta.get("errors", [])
    if errors:
        # Use first meaningful error
        reason = errors[0]
        if "age_exceeded" in reason:
            reason = "price_feed_stale"
        elif "no_rows" in reason or "no_close_price" in reason:
            reason = "no_price_feed"
        else:
            reason = "no_price_feed"
    else:
        reason = "no_price_feed"
    
    return False, reason, meta


def _evaluate_symbol_recovery(
    symbol: str,
    capital_plan: Dict[str, Any],
    live_candidates: Dict[str, Any],
    quarantine: Dict[str, Any],
    execution_quality: Dict[str, Any],
    pf_validity: Dict[str, Any],
    pf_timeseries: Dict[str, Any],
) -> Dict[str, Any]:
    """Evaluate recovery eligibility for a single symbol."""
    result = {
        "eligible": False,
        "score": 0.0,
        "reasons": [],
        "gates": {
            "not_quarantined": False,
            "policy_not_blocked": False,
            "execql_not_hostile": False,
            "price_feed_ok": False,
            "sufficient_sample": False,
        },
        "limits": {
            "notional_usd": 0.0,
            "cooldown_seconds": COOLDOWN_SECONDS,
        },
    }
    
    # Get symbol data
    by_symbol_plan = capital_plan.get("by_symbol", {}) or capital_plan.get("symbols", {})
    plan_data = by_symbol_plan.get(symbol, {})
    
    by_symbol_live = live_candidates.get("by_symbol", {}) or live_candidates.get("symbols", {})
    live_data = by_symbol_live.get(symbol, {})
    
    # Hard blocks
    
    # 1. Quarantine check
    blocked_symbols = quarantine.get("blocked_symbols", [])
    if symbol in blocked_symbols:
        result["reasons"].append("quarantined")
        return result
    result["gates"]["not_quarantined"] = True
    
    # 2. Policy check
    policy = plan_data.get("policy", "") or live_data.get("policy", "")
    if policy == "blocked":
        result["reasons"].append("policy_blocked")
        return result
    result["gates"]["policy_not_blocked"] = True
    
    # 3. Execution quality check
    exec_data = execution_quality.get("data", {}).get(symbol, {}) or \
               execution_quality.get("symbols", {}).get(symbol, {})
    exec_label = exec_data.get("summary", {}).get("overall_label") or \
                exec_data.get("overall_label")
    if exec_label == "hostile":
        result["reasons"].append("execql_hostile")
        return result
    result["gates"]["execql_not_hostile"] = True
    
    # 4. Price feed check (using unified PriceFeedHealth)
    price_feed_ok, price_feed_reason, price_feed_meta = _check_price_feed(symbol, max_age_seconds=900)
    if not price_feed_ok:
        result["reasons"].append(price_feed_reason)
        # Include feed metadata in result for debugging (not in reason string)
        result["feed_meta"] = {
            "source": price_feed_meta.get("source_used"),
            "age_seconds": price_feed_meta.get("age_seconds"),
            "errors": price_feed_meta.get("errors", [])[:3],  # Limit to first 3 errors
        }
        return result
    result["gates"]["price_feed_ok"] = True
    # Include successful feed metadata
    result["feed_meta"] = {
        "source": price_feed_meta.get("source_used"),
        "age_seconds": price_feed_meta.get("age_seconds"),
    }
    
    # 5. Sample sufficiency check (pf_validity)
    # Check champion status first (will be used later for override)
    is_champion = False
    weight = plan_data.get("weight", 0.0) or plan_data.get("capital_weight", 0.0)
    if weight >= 0.15:  # Top capital weight
        # Check PF (use pf_timeseries if available)
        symbol_pf = None
        symbol_pf_data = pf_timeseries.get("symbols", {}).get(symbol, {})
        if symbol_pf_data:
            pf_7d_data = symbol_pf_data.get("7d", {})
            if pf_7d_data:
                symbol_pf = pf_7d_data.get("pf")
        
        # Also check pf_validity for normalized PF
        validity_data = pf_validity.get("by_symbol", {}).get(symbol, {}) or \
                       pf_validity.get("symbols", {}).get(symbol, {})
        pf_norm = validity_data.get("pf_norm_long")
        
        if (symbol_pf and symbol_pf >= CHAMPION_PF_THRESHOLD) or \
           (pf_norm and pf_norm >= CHAMPION_PF_THRESHOLD):
            is_champion = True
    
    validity_data = pf_validity.get("by_symbol", {}).get(symbol, {}) or \
                   pf_validity.get("symbols", {}).get(symbol, {})
    validity_label = validity_data.get("label", "")
    validity_score = validity_data.get("validity_score", 1.0)
    
    # Champion override: bypass sufficient_sample gate
    if is_champion:
        result["gates"]["sufficient_sample"] = True
        # Don't return early - continue to scoring
    elif validity_label == "very_low" or validity_score < 0.40:
        result["reasons"].append("insufficient_sample")
        return result
    else:
        result["gates"]["sufficient_sample"] = True
    
    # Soft gates (for scoring)
    score = 0.35  # Base score
    
    # ReadyNow bonus
    ready_now_val = live_data.get("ready_now")
    if ready_now_val and str(ready_now_val).upper() in ("Y", "YES", "TRUE", "1"):
        score += 0.25
    
    # Drift bonus/penalty
    drift = live_data.get("drift", "") or plan_data.get("drift", "")
    if drift in ("improving", "stable"):
        score += 0.15
    elif drift in ("degrading", "worsening"):
        score -= 0.15
    
    # Policy reduced penalty
    if policy == "reduced":
        score -= 0.10
    
    # Weight bonus
    weight = plan_data.get("weight", 0.0) or plan_data.get("capital_weight", 0.0)
    if weight >= 0.15:
        score += 0.15
    
    # Clamp score
    score = max(0.0, min(1.0, score))
    result["score"] = score
    
    # Eligibility threshold (is_champion was already computed in sufficient_sample check above)
    if is_champion:
        eligible = score >= CHAMPION_OVERRIDE_SCORE
        if eligible:
            result["reasons"].append("champion_override")
    else:
        eligible = score >= MIN_SYMBOL_SCORE
    
    result["eligible"] = eligible
    
    if not eligible:
        result["reasons"].append(f"score_too_low ({score:.2f} < {MIN_SYMBOL_SCORE if not is_champion else CHAMPION_OVERRIDE_SCORE})")
    
    # Set limits
    notional_usd = min(GLOBAL_RISK_CAP_NOTIONAL_USD, GLOBAL_RISK_CAP_NOTIONAL_USD * score)
    result["limits"]["notional_usd"] = notional_usd
    
    return result


def evaluate_recovery_ramp_v2(now_iso: Optional[str] = None) -> Dict[str, Any]:
    """
    Evaluate per-symbol recovery ramp v2.
    
    Returns:
        Dict with global state, per-symbol eligibility, and decision
    """
    now = datetime.now(timezone.utc) if now_iso is None else _parse_timestamp(now_iso)
    
    result = {
        "ts": now.isoformat(),
        "capital_mode": "unknown",
        "global": {
            "pf_7d": None,
            "pf_30d": None,
            "pf_timeseries_age_minutes": None,
            "pf_timeseries_fresh_pass": False,
            "global_risk_cap_notional_usd": GLOBAL_RISK_CAP_NOTIONAL_USD,
            "max_positions": MAX_POSITIONS,
        },
        "symbols": {},
        "decision": {
            "allow_recovery_lane": False,
            "allowed_symbols": [],
            "reason": "",
        },
    }
    
    try:
        # Load required data
        capital_protection = _load_json(CAPITAL_PROTECTION_PATH)
        pf_timeseries = _load_pf_timeseries()
        quarantine = _load_json(QUARANTINE_PATH)
        
        # Use quarantine-adjusted capital plan if available
        if CAPITAL_PLAN_QUARANTINE_PATH.exists():
            capital_plan = _load_json(CAPITAL_PLAN_QUARANTINE_PATH)
        else:
            capital_plan = _load_json(CAPITAL_PLAN_PATH)
        
        live_candidates = _load_json(LIVE_CANDIDATES_PATH)
        execution_quality = _load_json(EXECUTION_QUALITY_PATH)
        pf_validity = _load_json(PF_VALIDITY_PATH)
        
        # Extract capital mode
        capital_mode = (
            capital_protection.get("mode") or
            capital_protection.get("global", {}).get("mode") or
            "unknown"
        )
        result["capital_mode"] = capital_mode
        
        # Global gates
        
        # 1. Capital mode check
        if capital_mode not in ("halt_new_entries", "de_risk"):
            result["decision"]["reason"] = f"capital_mode={capital_mode} (not in recovery state)"
            _save_json(RECOVERY_RAMP_V2_STATE_PATH, result)
            return result
        
        # 2. PF timeseries freshness
        meta = pf_timeseries.get("meta", {})
        generated_at_str = meta.get("generated_at")
        
        pf_age_minutes = None
        pf_fresh = False
        
        if generated_at_str:
            try:
                gen_time = _parse_timestamp(generated_at_str)
                pf_age_minutes = (now - gen_time).total_seconds() / 60
                pf_fresh = pf_age_minutes < 90
            except Exception:
                pass
        
        result["global"]["pf_timeseries_age_minutes"] = pf_age_minutes
        result["global"]["pf_timeseries_fresh_pass"] = pf_fresh
        
        if not pf_fresh:
            result["decision"]["reason"] = "pf_timeseries_stale"
            _save_json(RECOVERY_RAMP_V2_STATE_PATH, result)
            return result
        
        # Get global PF values
        global_pf = pf_timeseries.get("global", {})
        pf_7d_window = global_pf.get("7d", {})
        pf_30d_window = global_pf.get("30d", {})
        
        result["global"]["pf_7d"] = pf_7d_window.get("pf") if pf_7d_window else None
        result["global"]["pf_30d"] = pf_30d_window.get("pf") if pf_30d_window else None
        
        # Evaluate per-symbol recovery
        by_symbol_plan = capital_plan.get("by_symbol", {}) or capital_plan.get("symbols", {})
        
        symbol_results = {}
        eligible_symbols = []
        
        for symbol, plan_data in by_symbol_plan.items():
            # Only evaluate symbols with lane_intent in {exploit, explore, normal}
            lane_intent = plan_data.get("lane_intent", "")
            if lane_intent not in ("exploit", "explore", "normal"):
                continue
            
            # Evaluate symbol
            symbol_result = _evaluate_symbol_recovery(
                symbol=symbol,
                capital_plan=capital_plan,
                live_candidates=live_candidates,
                quarantine=quarantine,
                execution_quality=execution_quality,
                pf_validity=pf_validity,
                pf_timeseries=pf_timeseries,
            )
            
            symbol_results[symbol] = symbol_result
            
            if symbol_result["eligible"]:
                eligible_symbols.append({
                    "symbol": symbol,
                    "score": symbol_result["score"],
                })
        
        result["symbols"] = symbol_results
        
        # Decision: allow recovery lane if at least 1 eligible symbol
        if eligible_symbols:
            # Sort by score (descending) and take top 3
            eligible_symbols.sort(key=lambda x: -x["score"])
            top_symbols = [e["symbol"] for e in eligible_symbols[:3]]  # Top 3 by score
            top_scores = [f"{e['score']:.2f}" for e in eligible_symbols[:3]]
            
            # Build recommended_order: sort by score, then by capital weight (if available)
            recommended_order = []
            for e in eligible_symbols[:3]:
                symbol = e["symbol"]
                # Get weight from capital plan if available
                symbol_data = capital_plan.get("by_symbol", {}).get(symbol, {}) or capital_plan.get("symbols", {}).get(symbol, {})
                weight = symbol_data.get("weight", 0.0)
                recommended_order.append((symbol, e["score"], weight))
            
            # Sort by score desc, then weight desc
            recommended_order.sort(key=lambda x: (-x[1], -x[2]))
            recommended_order = [x[0] for x in recommended_order]
            
            result["decision"]["allow_recovery_lane"] = True
            result["decision"]["allowed_symbols"] = top_symbols
            result["decision"]["recommended_order"] = recommended_order
            result["decision"]["reason"] = f"eligible_symbols_found (count={len(top_symbols)}, top={top_symbols[0] if top_symbols else 'none'}, scores={top_scores})"
        else:
            result["decision"]["reason"] = "no_eligible_symbols"
        
        # Save state
        _save_json(RECOVERY_RAMP_V2_STATE_PATH, result)
        
        return result
    
    except Exception as e:
        # On error, return safe defaults
        result["decision"]["reason"] = f"evaluation_error: {str(e)}"
        _save_json(RECOVERY_RAMP_V2_STATE_PATH, result)
        return result


def _load_pf_timeseries() -> Dict[str, Any]:
    """Load PF timeseries with fallbacks."""
    if PF_TIMESERIES_PATH.exists():
        return _load_json(PF_TIMESERIES_PATH)
    
    alt_path = REPORTS / "pf_timeseries.json"
    if alt_path.exists():
        return _load_json(alt_path)
    
    return {}


__all__ = ["evaluate_recovery_ramp_v2"]

