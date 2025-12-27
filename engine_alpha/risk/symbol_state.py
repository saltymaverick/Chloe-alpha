from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from engine_alpha.core.config_loader import load_engine_config

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
STATE_PATH = REPORTS / "risk" / "symbol_states.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_symbol_states() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {"generated_at": _now_iso(), "symbols": {}}
    try:
        data = json.loads(STATE_PATH.read_text())
        if not isinstance(data, dict):
            return {"generated_at": _now_iso(), "symbols": {}}
        symbols = data.get("symbols") or {}
        if not isinstance(symbols, dict):
            symbols = {}
        data["symbols"] = symbols
        data.setdefault("generated_at", _now_iso())
        return data
    except Exception:
        return {"generated_at": _now_iso(), "symbols": {}}


def atomic_write_symbol_states(payload: Dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    payload = dict(payload)
    payload.setdefault("generated_at", _now_iso())
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(STATE_PATH)


def _caps_dict(risk_mult_cap: float = 0.25, max_positions: int = 1) -> Dict[str, Any]:
    return {
        "risk_mult_cap": float(risk_mult_cap),
        "max_positions": int(max_positions),
    }


def _default_symbol_state() -> Dict[str, Any]:
    return {
        "state": "observe",
        "stance": "observe",
        "quarantined": False,
        "promotion_active": False,
        "promotion_expires_at": None,
        "exploration_override": None,
        "allow_core": False,
        "allow_exploration": False,
        "allow_recovery": False,
        "caps_by_lane": {
            "core": _caps_dict(),
            "exploration": _caps_dict(risk_mult_cap=0.25, max_positions=1),
            "recovery": _caps_dict(),
        },
        "last_updated": _now_iso(),
        "reasons": {},
    }


def derive_symbol_policy(
    symbol: str,
    capital_mode: str,
    defaults: Dict[str, Any],
    engine_cfg: Dict[str, Any],
    capital_protection: Dict[str, Any],
    quarantine: Dict[str, Any],
    promotions: Dict[str, Any],
    exploration_overrides: Dict[str, Any],
    recovery_ramp: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Derive per-symbol policy (allow flags + caps + reasons) using a single consistent rule set.
    """
    sym = symbol.upper()
    state = _default_symbol_state()
    reasons: Dict[str, str] = {}

    # Base caps from slot_limits
    slot_limits = engine_cfg.get("slot_limits") or {}
    core_caps = slot_limits.get("core") or {}
    expl_caps = slot_limits.get("exploration") or {}
    rec_caps = slot_limits.get("recovery") or {}
    state["caps_by_lane"]["core"] = _caps_dict(
        risk_mult_cap=core_caps.get("risk_mult_cap", 0.5),
        max_positions=core_caps.get("max_positions_total", 1),
    )
    state["caps_by_lane"]["exploration"] = _caps_dict(
        risk_mult_cap=expl_caps.get("risk_mult_cap", 0.5),
        max_positions=expl_caps.get("max_positions_total", 2),
    )
    state["caps_by_lane"]["recovery"] = _caps_dict(
        risk_mult_cap=rec_caps.get("risk_mult_cap", 0.25),
        max_positions=rec_caps.get("max_positions_total", 1),
    )

    # Quarantine
    q_enabled = quarantine.get("enabled") if isinstance(quarantine, dict) else False
    q_blocked = (quarantine.get("blocked_symbols") or []) if isinstance(quarantine, dict) else []
    if q_enabled and sym in q_blocked:
        state["quarantined"] = True
        state["allow_core"] = False
        state["allow_exploration"] = False
        state["allow_recovery"] = False
        state["stance"] = "halt"
        state["state"] = "quarantined"
        reasons["quarantine"] = "blocked"
        state["reasons"] = reasons
        state["last_updated"] = _now_iso()
        return state

    # Capital protection stance
    stance = None
    cp_symbols = (capital_protection.get("symbols") or {}) if isinstance(capital_protection, dict) else {}
    sym_cp = cp_symbols.get(sym, {}) if isinstance(cp_symbols, dict) else {}
    stance = sym_cp.get("stance") or (capital_protection.get("stance") if isinstance(capital_protection, dict) else None)
    if stance:
        state["stance"] = stance

    # Promotions
    promo_entry = promotions.get(sym) if isinstance(promotions, dict) else None
    promo_active = bool(promo_entry and promo_entry.get("enabled"))
    state["promotion_active"] = promo_active
    state["promotion_expires_at"] = promo_entry.get("expires_at") if promo_entry else None
    promo_risk_cap = float(promo_entry.get("risk_mult_cap", 0.25)) if promo_entry else None
    promo_max_positions = int(promo_entry.get("max_positions", 1)) if promo_entry else None

    # Exploration override
    state["exploration_override"] = exploration_overrides.get(sym) if isinstance(exploration_overrides, dict) else None

    # Sample-gated allowances: implement meaningful sample threshold before quarantine decisions
    n_closes_7d = sym_cp.get("n_closes_7d") or 0
    pf_7d = sym_cp.get("pf_7d")

    # Store sample metrics for transparency
    state["n_closes_7d"] = n_closes_7d
    state["pf_7d"] = pf_7d

    # Phase 5I: Per-coin lifecycle with meaningful sample thresholds
    if n_closes_7d < 30:
        # Sample-building: allow core + exploration BEFORE any quarantine decisions
        sample_stage = "sample_building"
        state["allow_core"] = True
        state["allow_exploration"] = True
    elif n_closes_7d < 60:
        # Evaluation: soft demotions based on PF, but no hard quarantine yet
        sample_stage = "evaluation"
        pf_good = pf_7d is not None and pf_7d >= 1.05
        state["allow_core"] = pf_good  # Soft demotion for poor performers
        state["allow_exploration"] = True  # Keep exploration for continued research
    else:
        # Enforcement: after meaningful sample, allow quarantine/recovery based on PF
        pf_good = pf_7d is not None and pf_7d >= 1.05
        state["allow_core"] = pf_good
        state["allow_exploration"] = True  # Keep exploration for research even in quarantine

        if pf_good:
            sample_stage = "eligible"
        else:
            sample_stage = "quarantined"

    state["sample_stage"] = sample_stage

    # Recovery: controlled separately, default off
    allow_recovery_trading = False
    if isinstance(recovery_ramp, dict):
        allow_recovery_trading = (recovery_ramp.get("allowances") or {}).get("allow_recovery_trading", False)
    state["allow_recovery"] = False  # placeholder; recovery ladder to decide later

    # Promotions force allow_core even if global is risk-off; stance must not be halt
    if promo_active and stance != "halt":
        state["allow_core"] = True
        # Apply promo caps to core lane
        if promo_risk_cap is not None:
            state["caps_by_lane"]["core"]["risk_mult_cap"] = min(
                state["caps_by_lane"]["core"]["risk_mult_cap"], promo_risk_cap
            )
        if promo_max_positions is not None:
            state["caps_by_lane"]["core"]["max_positions"] = min(
                state["caps_by_lane"]["core"]["max_positions"], promo_max_positions
            )

    # Global capital_mode risk-off: apply caps but do not block stance=normal/promo
    if capital_mode in {"de_risk", "halt_new_entries"}:
        # Tighten caps
        for lane in ("core", "exploration", "recovery"):
            caps_lane = state["caps_by_lane"].get(lane, {})
            caps_lane["risk_mult_cap"] = min(caps_lane.get("risk_mult_cap", 0.25), 0.25)
            caps_lane["max_positions"] = min(caps_lane.get("max_positions", 1), 1)
            state["caps_by_lane"][lane] = caps_lane
        # Only block if stance is halt/observe
        if stance in {"halt", "observe"} and not promo_active:
            state["allow_core"] = False
            state["allow_exploration"] = False

    state["state"] = "core" if state["allow_core"] else ("recovery" if state["allow_recovery"] else "observe")
    state["last_updated"] = _now_iso()
    state["reasons"] = reasons
    return state

