"""
Shadow Promotion Gate (Phase 5b)
---------------------------------

Evaluates shadow exploit candidates for promotion eligibility.

Inputs:
  - reports/reflect/shadow_exploit_scores.json
  - reports/risk/capital_plan.json
  - reports/risk/capital_protection.json
  - reports/risk/pf_validity.json
  - reports/research/exploration_policy_v3.json
  - reports/risk/live_candidates.json

Outputs:
  - reports/evolver/shadow_promotion_candidates.json
  - reports/evolver/shadow_promotion_history.jsonl
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from engine_alpha.core.paths import REPORTS

SCORES_PATH = REPORTS / "reflect" / "shadow_exploit_scores.json"
CAPITAL_PLAN_PATH = REPORTS / "risk" / "capital_plan.json"
CAPITAL_PROTECTION_PATH = REPORTS / "risk" / "capital_protection.json"
PF_VALIDITY_PATH = REPORTS / "risk" / "pf_validity.json"
POLICY_PATH = REPORTS / "research" / "exploration_policy_v3.json"
LIVE_CANDIDATES_PATH = REPORTS / "risk" / "live_candidates.json"
CANDIDATES_PATH = REPORTS / "evolver" / "shadow_promotion_candidates.json"
HISTORY_PATH = REPORTS / "evolver" / "shadow_promotion_history.jsonl"

# Minimum sample requirements for promotion eligibility
MIN_SHADOW_TRADES_7D = 8
MIN_SHADOW_TRADES_30D = 20


@dataclass
class PromotionCandidate:
    """Promotion candidate entry."""
    symbol: str
    composite: float
    reasons_ok: List[str]
    fails: List[str]
    metrics: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _load_json(path: Path) -> Dict[str, Any]:
    """Safely load JSON file."""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp value between min and max."""
    return max(min_val, min(max_val, value))


def _compute_composite_score(
    pf_30d: Optional[float],
    pf_7d: Optional[float],
    mdd: float,
    validity: float,
) -> float:
    """Compute composite promotion score."""
    pf30_norm = _clamp(pf_30d or 1.0, 0, 3) / 3.0
    pf7_norm = _clamp(pf_7d or 1.0, 0, 3) / 3.0
    mdd_norm = 1.0 - _clamp(mdd, 0, 10) / 10.0
    validity_norm = validity
    
    composite = (
        0.45 * pf30_norm +
        0.25 * pf7_norm +
        0.15 * mdd_norm +
        0.15 * validity_norm
    )
    
    return composite


def _evaluate_candidate(
    symbol: str,
    scores: Dict[str, Any],
    capital_plan: Dict[str, Any],
    capital_protection: Dict[str, Any],
    pf_validity: Dict[str, Any],
    policy: Dict[str, Any],
    live_candidates: Dict[str, Any],
) -> Optional[PromotionCandidate]:
    """Evaluate a single symbol for promotion eligibility."""
    
    # Get symbol metrics from scores
    symbol_scores = scores.get("by_symbol", {}).get(symbol, {})
    if not symbol_scores:
        return None
    
    # Get capital mode
    capital_mode = capital_protection.get("mode", "unknown")
    
    # Get live candidate status
    live_cand = live_candidates.get("by_symbol", {}).get(symbol, {})
    ready_now = live_cand.get("ready_now") in (True, "Y", "yes")
    
    # Get shadow metrics (use pf_display for all decisions)
    shadow_pf_7d = symbol_scores.get("pf_7d_display") or symbol_scores.get("pf_7d")  # Fallback for backward compat
    shadow_pf_30d = symbol_scores.get("pf_30d_display") or symbol_scores.get("pf_30d")  # Fallback for backward compat
    shadow_trades_7d = symbol_scores.get("trades_7d", 0)
    shadow_trades_30d = symbol_scores.get("trades_30d", 0)
    max_dd = symbol_scores.get("max_drawdown_pct", 0.0)
    
    # Get PF validity
    validity_data = pf_validity.get("by_symbol", {}).get(symbol, {})
    validity_score = validity_data.get("validity_score", 0.0)
    
    # Get policy level
    policy_data = policy.get("symbols", {}).get(symbol, {})
    policy_level = policy_data.get("level", "unknown")
    
    # Get capital plan data
    plan_data = capital_plan.get("by_symbol", {}).get(symbol, {})
    lane_intent = plan_data.get("lane_intent", "unknown")
    
    # Check all conditions
    reasons_ok = []
    fails = []
    
    # 1. Capital mode (evaluate candidates even in de_risk, but mark as not actionable)
    actionable = (capital_mode == "normal")
    if not actionable:
        # Don't fail - just note it's not actionable
        pass
    else:
        reasons_ok.append("capital_mode=normal")
    
    # 2. Minimum sample requirements (must pass before other checks)
    if shadow_trades_7d < MIN_SHADOW_TRADES_7D:
        fails.append(f"shadow_trades_7d={shadow_trades_7d}<{MIN_SHADOW_TRADES_7D}")
    else:
        reasons_ok.append(f"shadow_trades_7d={shadow_trades_7d}>={MIN_SHADOW_TRADES_7D}")
    
    if shadow_trades_30d < MIN_SHADOW_TRADES_30D:
        fails.append(f"shadow_trades_30d={shadow_trades_30d}<{MIN_SHADOW_TRADES_30D}")
    else:
        reasons_ok.append(f"shadow_trades_30d={shadow_trades_30d}>={MIN_SHADOW_TRADES_30D}")
    
    # 3. Live readiness OR shadow performance (only if sample requirements met)
    if shadow_trades_7d >= MIN_SHADOW_TRADES_7D:
        if ready_now:
            reasons_ok.append("live_candidates.ready_now=True")
        elif shadow_pf_7d is not None and shadow_pf_7d >= 1.10 and shadow_trades_7d >= 8:
            reasons_ok.append(f"shadow_pf_7d={shadow_pf_7d:.2f}>=1.10 AND trades_7d={shadow_trades_7d}>=8")
        else:
            fails.append(f"not ready_now AND (shadow_pf_7d={shadow_pf_7d or 0:.2f}<1.10 OR trades_7d={shadow_trades_7d}<8)")
    
    # 4. Shadow PF 7D (use stable PF)
    if shadow_pf_7d is None or shadow_pf_7d < 1.05:
        fails.append(f"shadow_pf_7d={shadow_pf_7d or 0:.2f}<1.05")
    else:
        reasons_ok.append(f"shadow_pf_7d={shadow_pf_7d:.2f}>=1.05")
    
    # 5. Shadow PF 30D (use stable PF)
    if shadow_pf_30d is None or shadow_pf_30d < 1.03:
        fails.append(f"shadow_pf_30d={shadow_pf_30d or 0:.2f}<1.03")
    else:
        reasons_ok.append(f"shadow_pf_30d={shadow_pf_30d:.2f}>=1.03")
    
    # 6. Max drawdown
    if max_dd > 6.0:
        fails.append(f"max_drawdown_pct={max_dd:.2f}>6.0")
    else:
        reasons_ok.append(f"max_drawdown_pct={max_dd:.2f}<=6.0")
    
    # 7. PF validity
    if validity_score < 0.65:
        fails.append(f"pf_validity={validity_score:.2f}<0.65")
    else:
        reasons_ok.append(f"pf_validity={validity_score:.2f}>=0.65")
    
    # 8. Policy level
    if policy_level == "blocked":
        fails.append(f"policy_level={policy_level} (blocked)")
    else:
        reasons_ok.append(f"policy_level={policy_level} (not blocked)")
    
    # 9. Lane intent
    if lane_intent != "exploit":
        fails.append(f"lane_intent={lane_intent} (need 'exploit')")
    else:
        reasons_ok.append(f"lane_intent={lane_intent}")
    
    # If any fails, return None (not a candidate)
    if fails:
        return None
    
    # Compute composite score
    composite = _compute_composite_score(
        shadow_pf_30d,
        shadow_pf_7d,
        max_dd,
        validity_score,
    )
    
    metrics = {
        "shadow_pf_7d": shadow_pf_7d,
        "shadow_pf_30d": shadow_pf_30d,
        "shadow_trades_7d": shadow_trades_7d,
        "shadow_trades_30d": shadow_trades_30d,
        "max_drawdown_pct": max_dd,
        "pf_validity": validity_score,
        "win_rate": symbol_scores.get("win_rate", 0.0),
        "expectancy_pct": symbol_scores.get("expectancy_pct", 0.0),
        "profit_factor": symbol_scores.get("profit_factor"),
    }
    
    return PromotionCandidate(
        symbol=symbol,
        composite=composite,
        reasons_ok=reasons_ok,
        fails=[],
        metrics=metrics,
    )


def compute_promotion_candidates() -> Dict[str, Any]:
    """
    Compute shadow promotion candidates.
    
    Returns:
        Dict with candidates data
    """
    # Load all inputs
    scores = _load_json(SCORES_PATH)
    capital_plan = _load_json(CAPITAL_PLAN_PATH)
    capital_protection = _load_json(CAPITAL_PROTECTION_PATH)
    pf_validity = _load_json(PF_VALIDITY_PATH)
    policy = _load_json(POLICY_PATH)
    live_candidates = _load_json(LIVE_CANDIDATES_PATH)
    
    # Extract capital mode (handle different structures)
    capital_mode = capital_protection.get("mode")
    if not capital_mode:
        global_data = capital_protection.get("global", {})
        capital_mode = global_data.get("mode", "unknown")
    
    # Get all symbols from scores
    symbol_scores = scores.get("by_symbol", {})
    if not symbol_scores:
        result = {
            "engine": "shadow_promotion_gate_v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "capital_mode": capital_mode,
            "candidates": [],
            "blocked": [],
            "notes": ["No shadow scores found. Run shadow_exploit_scorer first."],
        }
        
        CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CANDIDATES_PATH.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        
        return result
    
    # Evaluate each symbol
    candidates = []
    blocked = []
    
    for symbol in sorted(symbol_scores.keys()):
        candidate = _evaluate_candidate(
            symbol,
            scores,
            capital_plan,
            capital_protection,
            pf_validity,
            policy,
            live_candidates,
        )
        
        if candidate:
            candidates.append(candidate.to_dict())
        else:
            # Get fails for blocked entry
            symbol_scores_data = symbol_scores.get(symbol, {})
            live_cand = live_candidates.get("by_symbol", {}).get(symbol, {})
            policy_data = policy.get("symbols", {}).get(symbol, {})
            plan_data = capital_plan.get("by_symbol", {}).get(symbol, {})
            validity_data = pf_validity.get("by_symbol", {}).get(symbol, {})
            
            fails = []
            if capital_mode != "normal":
                fails.append(f"capital_mode={capital_mode}")
            
            # Minimum sample requirements
            trades_7d_val = symbol_scores_data.get("trades_7d", 0)
            trades_30d_val = symbol_scores_data.get("trades_30d", 0)
            
            if trades_7d_val < MIN_SHADOW_TRADES_7D:
                fails.append(f"shadow_trades_7d={trades_7d_val}<{MIN_SHADOW_TRADES_7D}")
            
            if trades_30d_val < MIN_SHADOW_TRADES_30D:
                fails.append(f"shadow_trades_30d={trades_30d_val}<{MIN_SHADOW_TRADES_30D}")
            
            # Other criteria (only check if sample requirements met)
            if trades_7d_val >= MIN_SHADOW_TRADES_7D:
                if live_cand.get("ready_now") not in (True, "Y", "yes"):
                    shadow_pf_7d = symbol_scores_data.get("pf_7d_display") or symbol_scores_data.get("pf_7d")
                    if not (shadow_pf_7d and shadow_pf_7d >= 1.10 and trades_7d_val >= 8):
                        fails.append("not ready_now AND shadow criteria not met")
            
            # Use pf_display (never raw) for promotion decisions
            pf_7d_val = symbol_scores_data.get("pf_7d_display") or symbol_scores_data.get("pf_7d")
            if pf_7d_val is None or pf_7d_val < 1.05:
                pf7_str = f"{pf_7d_val:.2f}" if pf_7d_val else "None"
                fails.append(f"pf_7d_display={pf7_str}<1.05")
            pf_30d_val = symbol_scores_data.get("pf_30d_display") or symbol_scores_data.get("pf_30d")
            if pf_30d_val is None or pf_30d_val < 1.03:
                pf30_str = f"{pf_30d_val:.2f}" if pf_30d_val else "None"
                fails.append(f"pf_30d_display={pf30_str}<1.03")
            mdd_val = symbol_scores_data.get("max_drawdown_pct", 0.0)
            if mdd_val > 6.0:
                fails.append(f"mdd={mdd_val:.2f}>6.0")
            validity_val = validity_data.get("validity_score", 0.0)
            if validity_val < 0.65:
                fails.append(f"validity={validity_val:.2f}<0.65")
            if policy_data.get("level") == "blocked":
                fails.append("policy_blocked")
            if plan_data.get("lane_intent") != "exploit":
                fails.append(f"lane_intent={plan_data.get('lane_intent', 'unknown')}")
            
            blocked.append({
                "symbol": symbol,
                "fails": fails,
            })
    
    # Sort candidates by composite score (descending)
    candidates.sort(key=lambda x: x.get("composite", 0.0), reverse=True)
    
    # Separate actionable vs pending candidates
    actionable_candidates = []
    candidates_pending_mode = []
    
    for cand in candidates:
        # Check if candidate meets all criteria except capital_mode
        cand_fails = []
        symbol = cand.get("symbol", "")
        symbol_scores_data = symbol_scores.get(symbol, {})
        live_cand = live_candidates.get("by_symbol", {}).get(symbol, {})
        
        # Re-check criteria (excluding capital_mode check)
        if live_cand.get("ready_now") not in (True, "Y", "yes"):
            shadow_pf_7d = symbol_scores_data.get("pf_7d")
            shadow_trades_7d = symbol_scores_data.get("trades_7d", 0)
            if not (shadow_pf_7d and shadow_pf_7d >= 1.10 and shadow_trades_7d >= 8):
                cand_fails.append("not ready_now AND shadow criteria not met")
        
        if not cand_fails and actionable:
            actionable_candidates.append(cand)
        elif not cand_fails:
            candidates_pending_mode.append(cand)
    
    notes = []
    actionable_flag = (capital_mode == "normal")
    if capital_mode == "unknown":
        notes.append("Capital mode is 'unknown'. Cannot evaluate promotion candidates.")
    elif not actionable_flag:
        notes.append(f"Capital mode is '{capital_mode}'. Candidates evaluated but not actionable (require capital_mode='normal').")
    
    result = {
        "engine": "shadow_promotion_gate_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "capital_mode": capital_mode,
        "actionable": actionable_flag,
        "candidates": actionable_candidates,
        "candidates_pending_mode": candidates_pending_mode,
        "blocked": blocked[:20],  # Limit blocked list
        "notes": notes,
    }
    
    # Save candidates
    CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CANDIDATES_PATH.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    
    # Append to history
    history_entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "capital_mode": capital_mode,
        "candidate_count": len(candidates),
        "top_candidates": [c["symbol"] for c in candidates[:5]],
    }
    
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(history_entry) + "\n")
    
    return result

