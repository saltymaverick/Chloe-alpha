"""
Exploration Policy V3
---------------------

Phase 3a: Pro-quant exploration policy engine for Chloe.

This module synthesizes:
  * PF time-series (PF_7D, PF_30D) from reports/pf/pf_timeseries.json
  * Capital protection stances from reports/risk/capital_protection.json
  * Symbol edge profile (tier, drift, exec quality) from
      reports/research/symbol_edge_profile.json
  * Confidence V2 + Hybrid Lane from reports/confidence/confidence_v2.json

to produce a per-symbol exploration policy:
  * level: "full" | "reduced" | "blocked"
  * allow_new_entries: bool
  * throttle_factor: float in [0.0, 1.0]
  * reasons: list of textual explanations

Outputs:
  * reports/research/exploration_policy_v3.json

All outputs are ADVISORY-ONLY and PAPER-SAFE.
This module does not modify configs, gates, or live behavior.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from engine_alpha.core.paths import REPORTS

PF_TS_PATH = REPORTS / "pf" / "pf_timeseries.json"
CAPITAL_PROTECTION_PATH = REPORTS / "risk" / "capital_protection.json"
EDGE_PROFILE_PATH = REPORTS / "research" / "symbol_edge_profile.json"
CONF_V2_PATH = REPORTS / "confidence" / "confidence_v2.json"
OUT_PATH = REPORTS / "research" / "exploration_policy_v3.json"
OUT_PATH_RISK = REPORTS / "risk" / "exploration_policy_v3.json"  # Also write to risk/ for micro-core


@dataclass
class ExplorationPolicy:
    symbol: str
    level: str  # "full" | "reduced" | "blocked"
    allow_new_entries: bool
    throttle_factor: float  # 1.0=full, 0.5=reduced, 0.0=blocked
    pf_7d: Optional[float]
    pf_30d: Optional[float]
    tier: Optional[str]
    drift: Optional[str]
    exec_quality: Optional[str]
    hybrid_lane: Optional[str]
    confidence_overall: Optional[float]
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "level": self.level,
            "allow_new_entries": self.allow_new_entries,
            "throttle_factor": self.throttle_factor,
            "pf_7d": self.pf_7d,
            "pf_30d": self.pf_30d,
            "tier": self.tier,
            "drift": self.drift,
            "exec_quality": self.exec_quality,
            "hybrid_lane": self.hybrid_lane,
            "confidence_overall": self.confidence_overall,
            "reasons": self.reasons,
        }


def _safe_load(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _extract_pf_symbol(pf_ts: Dict[str, Any], symbol: str, key: str) -> Optional[float]:
    symbols = pf_ts.get("symbols", {})
    entry = symbols.get(symbol)
    if not entry:
        return None
    win = entry.get(key) or {}
    pf = win.get("pf")
    if pf is None:
        return None
    try:
        return float(pf)
    except Exception:
        return None


def _extract_capital_stance(cap: Dict[str, Any], symbol: str) -> Optional[str]:
    symbols = cap.get("symbols", [])
    for entry in symbols:
        if entry.get("symbol") == symbol:
            return entry.get("stance")
    return None


def _extract_edge_profile(edge: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    # Handle different structures: {"symbols": {...}} or {"profiles": {...}} or plain {...}
    data = edge.get("symbols") or edge.get("profiles") or edge
    # Skip if data contains metadata keys (not symbol data)
    if not isinstance(data, dict) or "generated_at" in data or "version" in data:
        # If edge itself looks like metadata, try to find nested symbol data
        if "profiles" in edge and isinstance(edge["profiles"], dict):
            data = edge["profiles"]
        elif "symbols" in edge and isinstance(edge["symbols"], dict):
            data = edge["symbols"]
        else:
            return {"tier": None, "drift": None, "exec_quality": None}
    
    if not isinstance(data, dict):
        return {"tier": None, "drift": None, "exec_quality": None}
    
    entry = data.get(symbol, {})
    if not isinstance(entry, dict):
        return {"tier": None, "drift": None, "exec_quality": None}
    
    return {
        "tier": entry.get("tier"),
        "drift": entry.get("drift"),
        "exec_quality": entry.get("exec_quality") or entry.get("execql") or entry.get("exec_ql"),
    }


def _extract_confidence_v2(conf_v2: Dict[str, Any], symbol: str, timeframe: str = "1h") -> Dict[str, Any]:
    """
    Confidence V2 stored as symbols: { "SYMBOL:TIMEFRAME": { ... } }

    We look for f"{symbol}:{timeframe}" primarily, and fall back to first match
    containing the symbol if needed.
    """
    symbols = conf_v2.get("symbols", {})
    key = f"{symbol}:{timeframe}"
    entry = symbols.get(key)
    if not entry:
        # Fallback: any key starting with symbol:
        for k, v in symbols.items():
            if isinstance(k, str) and k.startswith(symbol + ":"):
                entry = v
                break
    if not entry:
        return {
            "overall": None,
            "hybrid_lane": None,
        }
    hybrid = (entry.get("hybrid_lane") or {}).get("lane")
    overall = entry.get("overall")
    try:
        overall_f = float(overall) if overall is not None else None
    except Exception:
        overall_f = None
    return {
        "overall": overall_f,
        "hybrid_lane": hybrid,
    }


def _initial_level_from_pf_and_cap(
    pf_7d: Optional[float],
    pf_30d: Optional[float],
    capital_stance: Optional[str],
) -> tuple[str, List[str]]:
    """
    Decide initial level based on PF windows and capital protection stance.
    """
    reasons: List[str] = []

    # Default conservative baseline
    level = "reduced"

    if capital_stance == "halt":
        level = "blocked"
        reasons.append("Capital protection stance=halt.")
        return level, reasons

    if pf_7d is None or pf_30d is None:
        level = "reduced"
        reasons.append("Insufficient PF history; using reduced exploration.")
        return level, reasons

    # PF-based rules
    if pf_7d < 0.9 or pf_30d < 0.95:
        level = "blocked"
        reasons.append(f"Weak PF (7d={pf_7d:.2f}, 30d={pf_30d:.2f}); block exploration.")
    elif pf_7d < 1.0:
        level = "reduced"
        reasons.append(f"PF_7D {pf_7d:.2f} < 1.0; reduced exploration.")
    elif pf_30d >= 1.10 and pf_7d >= 1.05:
        level = "full"
        reasons.append(f"Strong PF (7d={pf_7d:.2f}, 30d={pf_30d:.2f}); allow full exploration.")
    else:
        level = "normal"
        reasons.append(f"PF windows acceptable (7d={pf_7d:.2f}, 30d={pf_30d:.2f}); normal exploration.")

    # Map "normal" to "full" at this layer (we only expose full/reduced/blocked)
    if level == "normal":
        level = "full"

    return level, reasons


def _apply_risk_modifiers(
    level: str,
    reasons: List[str],
    tier: Optional[str],
    drift: Optional[str],
    exec_quality: Optional[str],
    hybrid_lane: Optional[str],
    confidence_overall: Optional[float],
) -> tuple[str, List[str]]:
    """
    Adjust level downwards based on drift, exec quality, tier, hybrid lane, and confidence.

    Never upgrades; only adds caution.
    """
    def downgrade(current: str) -> str:
        if current == "full":
            return "reduced"
        if current == "reduced":
            return "blocked"
        return "blocked"

    # Exec quality and drift
    if exec_quality == "hostile":
        new_level = downgrade(level)
        if new_level != level:
            reasons.append("Exec quality=hostile; downgrading exploration.")
            level = new_level

    if drift == "degrading":
        new_level = downgrade(level)
        if new_level != level:
            reasons.append("Drift=degrading; downgrading exploration.")
            level = new_level

    # Hybrid lane (risk-aware confidence engine)
    if hybrid_lane == "brake":
        new_level = downgrade(level)
        if new_level != level:
            reasons.append("Hybrid lane=brake; applying additional caution.")
            level = new_level

    # Confidence threshold
    if confidence_overall is not None and confidence_overall < 0.45:
        new_level = downgrade(level)
        if new_level != level:
            reasons.append(f"Confidence {confidence_overall:.2f} < 0.45; downgrading exploration.")
            level = new_level

    # Tier-specific handling: tier3 should not get Full unless PF is truly strong
    if tier == "tier3" and level == "full":
        level = "reduced"
        reasons.append("Tier3 symbol; capping at reduced exploration.")

    return level, reasons


def _throttle_factor_for_level(level: str) -> float:
    if level == "full":
        return 1.0
    if level == "reduced":
        return 0.5
    return 0.0


def compute_exploration_policy_v3() -> Dict[str, Any]:
    """
    Main entrypoint: compute exploration policy for all symbols
    with PF history and edge profile.
    """
    pf_ts = _safe_load(PF_TS_PATH) or {}
    cap = _safe_load(CAPITAL_PROTECTION_PATH) or {}
    edge = _safe_load(EDGE_PROFILE_PATH) or {}
    conf_v2 = _safe_load(CONF_V2_PATH) or {}

    symbol_set: set[str] = set()

    # Derive symbol universe from PF TS and edge profile and capital_protection
    for sym in (pf_ts.get("symbols") or {}).keys():
        symbol_set.add(sym)

    # Handle edge profile structure: could be {"symbols": {...}} or {"profiles": {...}} or plain {...}
    edge_symbols = edge.get("symbols") or edge.get("profiles") or edge
    if isinstance(edge_symbols, dict):
        # Skip metadata keys
        for sym in edge_symbols.keys():
            if sym not in ("generated_at", "version", "meta", "profiles", "symbols"):
                symbol_set.add(sym)

    for entry in cap.get("symbols", []):
        sym = entry.get("symbol")
        if sym:
            symbol_set.add(sym)

    # Filter to real trading symbols: uppercase strings ending with "USDT"
    filtered: set[str] = set()
    for s in symbol_set:
        if isinstance(s, str) and s.endswith("USDT") and s.isupper():
            filtered.add(s)
    symbol_set = filtered

    policies: List[ExplorationPolicy] = []

    for symbol in sorted(symbol_set):
        pf_7d = _extract_pf_symbol(pf_ts, symbol, "7d")
        pf_30d = _extract_pf_symbol(pf_ts, symbol, "30d")
        capital_stance = _extract_capital_stance(cap, symbol)
        edge_profile = _extract_edge_profile(edge, symbol)
        conf_info = _extract_confidence_v2(conf_v2, symbol, timeframe="1h")

        tier = edge_profile.get("tier")
        drift = edge_profile.get("drift")
        exec_quality = edge_profile.get("exec_quality")
        hybrid_lane = conf_info.get("hybrid_lane")
        confidence_overall = conf_info.get("overall")

        level, reasons = _initial_level_from_pf_and_cap(
            pf_7d=pf_7d,
            pf_30d=pf_30d,
            capital_stance=capital_stance,
        )
        level, reasons = _apply_risk_modifiers(
            level=level,
            reasons=reasons,
            tier=tier,
            drift=drift,
            exec_quality=exec_quality,
            hybrid_lane=hybrid_lane,
            confidence_overall=confidence_overall,
        )

        throttle = _throttle_factor_for_level(level)
        allow_new_entries = level != "blocked"

        policy = ExplorationPolicy(
            symbol=symbol,
            level=level,
            allow_new_entries=allow_new_entries,
            throttle_factor=float(throttle),
            pf_7d=pf_7d,
            pf_30d=pf_30d,
            tier=tier,
            drift=drift,
            exec_quality=exec_quality,
            hybrid_lane=hybrid_lane,
            confidence_overall=confidence_overall,
            reasons=reasons,
        )
        policies.append(policy)

    payload = {
        "meta": {
            "engine": "exploration_policy_v3",
            "version": "3.0.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "advisory_only": True,
        },
        "symbols": {p.symbol: p.to_dict() for p in policies},
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    
    # Also write to risk/ for micro-core and other risk modules
    OUT_PATH_RISK.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH_RISK.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)

    return payload


__all__ = ["compute_exploration_policy_v3", "OUT_PATH"]

