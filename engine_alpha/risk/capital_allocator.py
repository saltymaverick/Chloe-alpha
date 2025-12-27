"""
Capital Allocator V1 (Marksman Edition)
---------------------------------------

Paper-only capital allocation engine for Chloe Alpha.

Reads:
  - reports/pf/pf_timeseries.json        (PF_7D, PF_30D per symbol)
  - reports/research/execution_quality.json (ExecQL per symbol)
  - reports/research/drift_report.json   (Drift status per symbol)
  - reports/research/symbol_edge_profile.json (Tier per symbol)
  - reports/research/exploration_policy_v3.json (Policy level + throttle)

Outputs:
  - reports/risk/capital_plan.json

For each symbol, computes:
  - score          : composite alpha/risk score
  - weight         : softmax-normalized capital weight (0–1)
  - pf_7d, pf_30d  : from PF time-series
  - tier           : tier1/tier2/tier3
  - drift          : improving/neutral/degrading
  - execql         : friendly/neutral/hostile
  - policy_level   : full/reduced/blocked
  - policy_mult    : 1.0 / 0.6 / 0.0
  - tier_mult      : 1.0 / 0.7 / 0.3
  - drift_mult     : 1.15 / 1.0 / 0.7
  - vol_norm       : placeholder (1.0); ready for real volatility input later
  - flags          : kill_lane/de_risk/promotion_candidate

This allocator is ADVISORY-ONLY and PAPER-SAFE.
It does NOT:
  - place orders
  - change configs
  - modify live trading logic
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List


PF_TS_PATH = Path("reports/pf/pf_timeseries.json")
EXECQL_PATH = Path("reports/research/execution_quality.json")
DRIFT_PATH = Path("reports/research/drift_report.json")
EDGE_PROFILE_PATH = Path("reports/research/symbol_edge_profile.json")
POLICY_PATH = Path("reports/research/exploration_policy_v3.json")
PF_VALIDITY_PATH = Path("reports/risk/pf_validity.json")
PF_NORM_PATH = Path("reports/risk/pf_normalized.json")
SCM_PATH = Path("reports/research/scm_state.json")
RISK_SNAPSHOT_PATH = Path("reports/risk/risk_snapshot.json")
OUT_PATH = Path("reports/risk/capital_plan.json")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _fmt_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _safe_pf(entry: Dict[str, Any], key: str) -> Optional[float]:
    win = entry.get(key) or {}
    pf = win.get("pf")
    if pf is None:
        return None
    try:
        return float(pf)
    except Exception:
        return None


def _get_pf_for_symbol(pf_ts: Dict[str, Any], symbol: str) -> tuple[Optional[float], Optional[float]]:
    symbols = pf_ts.get("symbols") or {}
    entry = symbols.get(symbol) or {}
    return _safe_pf(entry, "7d"), _safe_pf(entry, "30d")


def _get_execql_for_symbol(execql: Dict[str, Any], symbol: str) -> Optional[str]:
    """
    Extract overall execution quality label for a symbol.
    Handles both dict-keyed and list-of-dicts structures.
    Also handles execution_quality.json format with 'data' key and 'summary.overall_label'.
    """
    # Handle execution_quality.json format: {"data": {symbol: {...}}}
    data = execql.get("data")
    if isinstance(data, dict):
        entry = data.get(symbol) or {}
        # Check summary.overall_label first (execution_quality.json format)
        summary = entry.get("summary", {})
        if isinstance(summary, dict):
            label = summary.get("overall_label")
            if label:
                return label
        # Fall back to direct fields
        return entry.get("overall_label") or entry.get("label") or entry.get("overall")
    
    # Handle other formats: {"symbols": {...}} or direct dict
    symbols = execql.get("symbols") or execql
    entry: Dict[str, Any] = {}
    if isinstance(symbols, dict):
        # keyed by symbol
        entry = symbols.get(symbol) or {}
    elif isinstance(symbols, list):
        for item in symbols:
            if isinstance(item, dict) and item.get("symbol") == symbol:
                entry = item
                break
    
    # Check summary.overall_label if present
    summary = entry.get("summary", {})
    if isinstance(summary, dict):
        label = summary.get("overall_label")
        if label:
            return label
    
    return entry.get("overall_label") or entry.get("label") or entry.get("overall")


def _get_drift_for_symbol(drift: Dict[str, Any], symbol: str) -> Optional[str]:
    symbols = drift.get("symbols") or {}
    entry = symbols.get(symbol) or {}
    return entry.get("status")


def _get_tier_for_symbol(edge: Dict[str, Any], symbol: str) -> Optional[str]:
    symbols = edge.get("symbols") or edge
    entry: Dict[str, Any] = {}
    if isinstance(symbols, dict):
        entry = symbols.get(symbol) or {}
    elif isinstance(symbols, list):
        for item in symbols:
            if isinstance(item, dict) and item.get("symbol") == symbol:
                entry = item
                break
    tier = entry.get("tier")
    if isinstance(tier, str):
        return tier
    return None


def _get_policy_for_symbol(policy: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    return (policy.get("symbols") or {}).get(symbol, {})


def _get_scm_for_symbol(scm: Dict[str, Any], symbol: str) -> Optional[str]:
    """Get SCM level for a symbol."""
    # Handle scm_state.json format: {"state": {symbol: {...}}}
    state = scm.get("state")
    if isinstance(state, dict):
        entry = state.get(symbol) or {}
        return entry.get("scm_level") or entry.get("level")
    
    # Handle other formats: {"symbols": {...}} or direct dict
    symbols = scm.get("symbols") or scm
    if isinstance(symbols, dict):
        entry = symbols.get(symbol) or {}
    elif isinstance(symbols, list):
        entry = {}
        for item in symbols:
            if isinstance(item, dict) and item.get("symbol") == symbol:
                entry = item
                break
    else:
        entry = {}
    return entry.get("scm_level") or entry.get("level")


def _get_blocked_for_symbol(risk: Dict[str, Any], symbol: str) -> bool:
    """Get blocked status for a symbol."""
    symbols = risk.get("symbols") or risk
    entry: Dict[str, Any] = {}
    if isinstance(symbols, dict):
        entry = symbols.get(symbol) or {}
    elif isinstance(symbols, list):
        for item in symbols:
            if isinstance(item, dict) and item.get("symbol") == symbol:
                entry = item
                break
    blocked = entry.get("blocked")
    if isinstance(blocked, bool):
        return blocked
    if isinstance(blocked, str):
        return blocked.lower() == "yes"
    return False


def _compute_lane_intent(
    scm_level: Optional[str],
    policy_level: Optional[str],
    blocked: bool,
) -> str:
    """Phase 4h: Compute lane intent based on SCM, policy, and blocked status."""
    if blocked or policy_level == "blocked":
        return "none"
    if scm_level == "off":
        return "exploit"
    if scm_level in ("low", "normal", "high"):
        return "explore"
    return "none"


def _execql_factor(label: Optional[str]) -> float:
    if label == "friendly":
        return 1.20
    if label == "neutral":
        return 1.00
    if label == "hostile":
        return 0.80
    return 1.00


def _drift_mult(status: Optional[str]) -> float:
    if status == "improving":
        return 1.15
    if status == "neutral":
        return 1.00
    if status == "degrading":
        return 0.70
    return 1.00


def _tier_mult(tier: Optional[str]) -> float:
    if tier == "tier1":
        return 1.0
    if tier == "tier2":
        return 0.7
    if tier == "tier3":
        return 0.3
    return 0.5


def _policy_mult(level: Optional[str]) -> float:
    if level == "full":
        return 1.0
    if level == "reduced":
        return 0.6
    if level == "blocked":
        return 0.0
    return 0.6


def _safe_geomean(values: List[float]) -> float:
    """
    Geometric mean of positive values. Values <= 0 are clamped to 0.01.
    """
    filtered = [max(v, 0.01) for v in values if v is not None]
    if not filtered:
        return 0.01
    logs = [math.log(v) for v in filtered]
    return float(math.exp(sum(logs) / len(logs)))


def _vol_norm_placeholder(symbol: str) -> float:
    """
    Placeholder volatility normalization factor.
    Real implementation would use realized vol; for now we return 1.0.
    """
    return 1.0


def _load_pf_validity_scores() -> Dict[str, float]:
    """
    Load PF validity scores per symbol from reports/risk/pf_validity.json.
    Returns a dict: { "SOLUSDT": 0.807, ... }.
    Missing entries default to 0.5 (neutral trust).
    """
    if not PF_VALIDITY_PATH.exists():
        return {}

    try:
        with PF_VALIDITY_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}

    scores = {}
    for sym, info in (data.get("symbols") or {}).items():
        try:
            v = float(info.get("validity_score", 0.5))
        except Exception:
            v = 0.5
        scores[sym] = max(0.0, min(1.0, v))
    return scores


def _load_normalized_pf() -> Dict[str, Dict[str, float]]:
    """
    Load normalized exploration PFs per symbol from pf_normalized.json.

    Returns dict:
      {
        "SOLUSDT": {"short": 1.54, "long": 1.21},
        ...
      }

    Missing entries default to 1.0 for both sides.
    """
    path = Path(PF_NORM_PATH)
    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}

    out: Dict[str, Dict[str, float]] = {}
    for sym, info in (data.get("symbols") or {}).items():
        try:
            ns = info.get("short_exp_pf_norm")
            nl = info.get("long_exp_pf_norm")
            short = float(ns) if ns is not None else 1.0
            long = float(nl) if nl is not None else 1.0
        except Exception:
            short, long = 1.0, 1.0
        out[sym] = {"short": max(0.1, short), "long": max(0.1, long)}
    return out


@dataclass
class SymbolAllocation:
    symbol: str
    score: float
    weight: float
    raw_weight: Optional[float]  # Phase 4f: original weight before validity caps
    pf_7d: Optional[float]
    pf_30d: Optional[float]
    norm_pf: Optional[float]
    tier: Optional[str]
    drift: Optional[str]
    execql: Optional[str]
    policy_level: Optional[str]
    policy_mult: float
    tier_mult: float
    drift_mult: float
    vol_norm: float
    flags: Dict[str, bool]
    lane_intent: str  # Phase 4h: "exploit" | "explore" | "none"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


def compute_capital_plan() -> Dict[str, Any]:
    """
    Main entrypoint for capital allocation.
    Computes per-symbol scores and normalized weights.
    """
    now = datetime.now(timezone.utc)

    pf_ts = _load_json(PF_TS_PATH)
    execql = _load_json(EXECQL_PATH)
    drift = _load_json(DRIFT_PATH)
    edge = _load_json(EDGE_PROFILE_PATH)
    policy = _load_json(POLICY_PATH)
    normalized_pf = _load_normalized_pf()  # Phase 4g: normalized PF
    scm = _load_json(SCM_PATH)  # Phase 4h: SCM state
    risk = _load_json(RISK_SNAPSHOT_PATH)  # Phase 4h: risk snapshot for blocked status

    symbol_set = set()
    symbol_set.update((pf_ts.get("symbols") or {}).keys())
    symbol_set.update((policy.get("symbols") or {}).keys())

    allocations: Dict[str, SymbolAllocation] = {}
    raw_scores: Dict[str, float] = {}

    # First pass: compute raw scores using normalized PF (Phase 4g)
    for sym in symbol_set:
        if not isinstance(sym, str):
            continue
        if not sym.endswith("USDT") or not sym.isupper():
            continue

        pf_7d, pf_30d = _get_pf_for_symbol(pf_ts, sym)
        pol = _get_policy_for_symbol(policy, sym)
        level = pol.get("level")
        pol_mult = _policy_mult(level)
        drift_status = _get_drift_for_symbol(drift, sym)
        drift_m = _drift_mult(drift_status)
        exec_label = _get_execql_for_symbol(execql, sym)
        exec_f = _execql_factor(exec_label)
        # Prefer tier from policy (Exploration Policy V3), fall back to edge profile
        tier = pol.get("tier") or _get_tier_for_symbol(edge, sym)
        tier_m = _tier_mult(tier)

        # --- Phase 4g: PF Reality integration (normalized PF) ---
        # 1) Get normalized exploration PFs (short/long)
        norm_entry = normalized_pf.get(sym, {})
        norm_short = norm_entry.get("short", 1.0)
        norm_long = norm_entry.get("long", 1.0)

        # 2) Clamp to >= 1.0 when combining to avoid weirdness around PF<1.0
        pf7_eff = max(1.0, pf_7d or 1.0)
        pf30_eff = max(1.0, pf_30d or 1.0)
        nshort_eff = max(1.0, norm_short or 1.0)
        nlong_eff = max(1.0, norm_long or 1.0)

        # 3) Compute PF alpha as geometric mean of normalized + PF_30D
        #    This keeps SOL/DOGE/etc ranked appropriately, but in a compressed way.
        alpha_pf = (nlong_eff * nshort_eff * pf30_eff) ** (1.0 / 3.0)

        # Keep norm_pf for display (using normalized values)
        norm_pf = (norm_short + norm_long) / 2.0 if norm_short and norm_long else None

        # Volatility placeholder
        vol_norm = _vol_norm_placeholder(sym)

        # Kill lane: hostile + degrading → zero score
        kill_lane = exec_label == "hostile" and drift_status == "degrading"

        # 4) Combine PF alpha with existing multipliers (Phase 4g)
        score = alpha_pf * exec_f * drift_m * tier_m * pol_mult * vol_norm
        if kill_lane:
            score = 0.0

        raw_scores[sym] = score

        # Phase 4h: Compute lane_intent
        scm_level = _get_scm_for_symbol(scm, sym)
        blocked = _get_blocked_for_symbol(risk, sym)
        lane_intent = _compute_lane_intent(scm_level, level, blocked)

        allocations[sym] = SymbolAllocation(
            symbol=sym,
            score=score,
            weight=0.0,  # filled later
            raw_weight=None,  # Phase 4f: will be set after softmax, before validity caps
            pf_7d=pf_7d,
            pf_30d=pf_30d,
            norm_pf=norm_pf,
            tier=tier,
            drift=drift_status,
            execql=exec_label,
            policy_level=level,
            policy_mult=pol_mult,
            tier_mult=tier_m,
            drift_mult=drift_m,
            vol_norm=vol_norm,
            flags={
                "kill_lane": kill_lane,
                "de_risk": False,
                "promotion_candidate": False,
            },
            lane_intent=lane_intent,
        )

    # Softmax normalization
    # Apply PF_30D cap: if PF_30D < 0.85, cap score
    for sym, alloc in allocations.items():
        pf_30d = alloc.pf_30d
        if pf_30d is not None and pf_30d < 0.85:
            # cap score by compressing
            raw_scores[sym] = raw_scores[sym] * 0.3

    # Compute softmax
    scores = [s for s in raw_scores.values() if s > 0.0]
    if scores:
        max_score = max(scores)
    else:
        max_score = 0.0

    exp_scores: Dict[str, float] = {}
    for sym, sc in raw_scores.items():
        if sc <= 0.0:
            exp_scores[sym] = 0.0
        else:
            # subtract max_score for numerical stability
            exp_scores[sym] = math.exp(sc - max_score)

    total_exp = sum(exp_scores.values()) or 1.0

    # Store initial weights from softmax (before tier caps and validity caps)
    for sym, alloc in allocations.items():
        w = exp_scores[sym] / total_exp
        allocations[sym].weight = float(w)

    # Tier caps: sum(tier3) ≤ 15%, sum(tier2) ≤ 35%
    tier1_sum = sum(a.weight for a in allocations.values() if a.tier == "tier1")
    tier2_sum = sum(a.weight for a in allocations.values() if a.tier == "tier2")
    tier3_sum = sum(a.weight for a in allocations.values() if a.tier == "tier3")
    
    tier2_syms = [s for s, a in allocations.items() if a.tier == "tier2"]
    tier3_syms = [s for s, a in allocations.items() if a.tier == "tier3"]
    
    # Apply caps to tier3 and tier2
    if tier3_sum > 0.15 and tier3_sum > 0.0:
        factor = 0.15 / tier3_sum
        for s in tier3_syms:
            allocations[s].weight *= factor
        tier3_sum = 0.15  # Update sum after capping
    
    if tier2_sum > 0.35 and tier2_sum > 0.0:
        factor = 0.35 / tier2_sum
        for s in tier2_syms:
            allocations[s].weight *= factor
        tier2_sum = 0.35  # Update sum after capping
    
    # Renormalize only tier1 to fill remaining weight (ensures tier2/tier3 caps are respected)
    capped_sum = tier2_sum + tier3_sum
    remaining_weight = 1.0 - capped_sum
    
    if remaining_weight > 0.0 and tier1_sum > 0.0:
        tier1_syms = [s for s, a in allocations.items() if a.tier == "tier1"]
        factor = remaining_weight / tier1_sum
        for s in tier1_syms:
            allocations[s].weight *= factor
    elif remaining_weight <= 0.0:
        # If capped tiers exceed 1.0, scale them down proportionally
        total_capped = tier2_sum + tier3_sum
        if total_capped > 0.0:
            scale = 1.0 / total_capped
            for s in tier2_syms + tier3_syms:
                allocations[s].weight *= scale
            # Set tier1 to zero
            tier1_syms = [s for s, a in allocations.items() if a.tier == "tier1"]
            for s in tier1_syms:
                allocations[s].weight = 0.0

    # Store raw weights (after tier caps, before validity caps)
    for sym, alloc in allocations.items():
        alloc.raw_weight = alloc.weight

    # === Phase 4f: Validity-based caps ===
    pf_validity = _load_pf_validity_scores()

    # Hard tier caps (max per-symbol weight at validity=1.0)
    tier_caps = {
        "tier1": 0.35,  # max 35% per tier1 symbol at validity=1.0
        "tier2": 0.30,  # max 30% per tier2 symbol at validity=1.0
        "tier3": 0.10,  # max 10% per tier3 symbol at validity=1.0
    }

    capped_weights: Dict[str, float] = {}

    for sym, alloc in allocations.items():
        tier = alloc.tier or "tier3"
        tier_cap = tier_caps.get(tier, 0.10)

        validity = pf_validity.get(sym, 0.5)  # neutral trust if missing
        effective_cap = tier_cap * validity

        # clamp weight to effective cap
        capped_weights[sym] = min(alloc.weight, max(0.0, effective_cap))

    # Renormalize so capped weights sum to 1.0 (if any positive weight)
    total_capped = sum(capped_weights.values())
    if total_capped > 0:
        for sym in capped_weights:
            capped_weights[sym] /= total_capped
    else:
        # fallback: if everything zero, keep original weights
        capped_weights = {sym: alloc.weight for sym, alloc in allocations.items()}

    # Apply capped weights
    for sym, alloc in allocations.items():
        alloc.weight = capped_weights.get(sym, alloc.weight)

    # Identify promotion candidates (reduced → full, advisory)
    for sym, alloc in allocations.items():
        if alloc.policy_level != "reduced":
            continue
        pf_7d = alloc.pf_7d or 0.0
        pf_30d = alloc.pf_30d or 0.0
        if (
            alloc.tier in ("tier1", "tier2")
            and pf_7d >= 1.10
            and pf_30d >= 1.05
            and (alloc.drift not in ("degrading",))
            and (alloc.execql in ("friendly", "neutral"))
        ):
            alloc.flags["promotion_candidate"] = True

    plan = {
        "meta": {
            "engine": "capital_allocator_v1",
            "version": "1.0.0",
            "generated_at": _fmt_ts(now),
            "advisory_only": True,
        },
        "symbols": {
            sym: alloc.to_dict() for sym, alloc in sorted(allocations.items())
        },
        "marksman_top5": [
            sym
            for sym, _ in sorted(
                allocations.items(), key=lambda kv: kv[1].score, reverse=True
            )[:5]
        ],
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, sort_keys=True)

    return plan


__all__ = ["compute_capital_plan", "OUT_PATH"]

