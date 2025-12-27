#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

from engine_alpha.core.config_loader import load_engine_config
from engine_alpha.risk.symbol_state import (
    STATE_PATH,
    atomic_write_symbol_states,
    derive_symbol_policy,
)
from engine_alpha.risk.recovery_earnback import (
    compute_earnback_state,
    get_default_recovery_config,
)

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def main() -> int:
    cfg = load_engine_config()
    capital_protection = _read_json(REPORTS / "risk" / "capital_protection.json")
    quarantine = _read_json(REPORTS / "risk" / "quarantine.json")
    recovery_ramp = _read_json(REPORTS / "risk" / "recovery_ramp.json")

    promotions = (cfg.get("core_promotions") or {}) if isinstance(cfg, dict) else {}
    exploration_overrides = (cfg.get("exploration_overrides") or {}) if isinstance(cfg, dict) else {}
    slot_limits = (cfg.get("slot_limits") or {}) if isinstance(cfg, dict) else {}
    exploration_cfg = (cfg.get("exploration_mode") or {}) if isinstance(cfg, dict) else {}
    exploration_lane_cfg = (cfg.get("exploration_lane") or {}) if isinstance(cfg, dict) else {}

    # Collect symbols from capital_protection, promotions, exploration overrides, and asset registry
    symbols = set()
    if isinstance(capital_protection, dict):
        cp_symbols = capital_protection.get("symbols") or capital_protection.get("per_symbol") or {}
        if isinstance(cp_symbols, dict):
            symbols.update(cp_symbols.keys())
        elif isinstance(cp_symbols, list):
            for entry in cp_symbols:
                if isinstance(entry, dict):
                    sym_name = entry.get("symbol") or entry.get("name")
                    if sym_name:
                        symbols.add(str(sym_name).upper())
    elif isinstance(capital_protection, list):
        for entry in capital_protection:
            if isinstance(entry, dict):
                sym_name = entry.get("symbol") or entry.get("name")
                if sym_name:
                    symbols.add(str(sym_name).upper())

    symbols.update(promotions.keys() if isinstance(promotions, dict) else [])
    symbols.update(exploration_overrides.keys() if isinstance(exploration_overrides, dict) else [])

    # Add asset registry symbols so stances/policy are populated even when capital_protection is empty
    try:
        asset_reg = _read_json(ROOT / "config" / "asset_registry.json")
        reg_syms = asset_reg.get("symbols") if isinstance(asset_reg, dict) else []
        if isinstance(reg_syms, list):
            for s in reg_syms:
                symbols.add(str(s).upper())
    except Exception:
        pass

    # Add quarantined symbols
    if isinstance(quarantine, dict):
        symbols.update(quarantine.get("blocked_symbols") or [])

    # Fallback: anchor symbol if none found
    if not symbols:
        symbols.add(str(cfg.get("symbol", "ETHUSDT")).upper() if isinstance(cfg, dict) else "ETHUSDT")

    capital_mode = (capital_protection.get("global") or {}).get("mode") if isinstance(capital_protection, dict) else "unknown"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "capital_mode": capital_mode,
        "slot_limits": slot_limits,
        "symbols": {},
    }

    # Stance map from list or dict, defaulting missing symbols to "observe"
    stance_map = {}
    if isinstance(capital_protection, dict):
        cp_list = capital_protection.get("symbols") or capital_protection.get("per_symbol") or []
        if isinstance(cp_list, dict):
            for k, v in cp_list.items():
                if isinstance(v, dict):
                    stance_map[str(k).upper()] = v.get("stance", "observe")
        elif isinstance(cp_list, list):
            for entry in cp_list:
                if isinstance(entry, dict):
                    sym = entry.get("symbol") or entry.get("name")
                    if sym:
                        stance_map[str(sym).upper()] = entry.get("stance", "observe")
    elif isinstance(capital_protection, list):
        for entry in capital_protection:
            if isinstance(entry, dict):
                sym = entry.get("symbol") or entry.get("name")
                if sym:
                    stance_map[str(sym).upper()] = entry.get("stance", "observe")

    # Default any symbol not in stance_map to "observe" so policy is usable immediately after reset
    for sym in symbols:
        stance_map.setdefault(sym.upper(), "observe")

    # Basic trade metrics (7d/30d/24h) from trades.jsonl closes
    trades_path = REPORTS / "trades.jsonl"
    now_dt = datetime.now(timezone.utc)
    cutoff_7d = now_dt - timedelta(days=7)
    cutoff_30d = now_dt - timedelta(days=30)
    cutoff_24h = now_dt - timedelta(hours=24)
    trade_events: Dict[str, List[Tuple[datetime, float]]] = {}
    if trades_path.exists():
        try:
            with trades_path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        evt = json.loads(line)
                    except Exception:
                        continue
                    if (evt.get("type") or "").lower() != "close":
                        continue
                    ts = evt.get("ts") or evt.get("timestamp")
                    sym_evt = (evt.get("symbol") or "").upper()
                    if not sym_evt or not ts:
                        continue
                    try:
                        ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
                    except Exception:
                        continue
                    pct = evt.get("pct") or evt.get("pnl_pct")
                    try:
                        pct_val = float(pct)
                    except Exception:
                        pct_val = 0.0
                    trade_events.setdefault(sym_evt, []).append((ts_dt, pct_val))
        except Exception:
            pass

    def _pf_from_pcts(pcts: List[float]) -> float | None:
        if not pcts:
            return None
        pf = 1.0
        for p in pcts:
            pf *= (1.0 + p)
        return pf

    def _loss_streak(pcts: List[Tuple[datetime, float]]) -> int:
        streak = 0
        best = 0
        for _, p in pcts:
            if p < 0:
                streak += 1
                best = max(best, streak)
            else:
                streak = 0
        return best

    def _pf_summary(pcts: List[float]) -> tuple[float | None, int, float, float]:
        """
        Returns (pf, n, gross_profit, gross_loss)
        """
        if not pcts:
            return None, 0, 0.0, 0.0
        pf = 1.0
        gross_profit = 0.0
        gross_loss = 0.0
        for p in pcts:
            pf *= (1.0 + p)
            if p >= 0:
                gross_profit += p
            else:
                gross_loss += p
        return pf, len(pcts), gross_profit, gross_loss

    for sym in sorted(symbols):
        sym_upper = sym.upper()
        stance = stance_map.get(sym_upper, "observe")
        reasons: Dict[str, str] = {}

        promo_entry = promotions.get(sym_upper) if isinstance(promotions, dict) else None
        promo_active = bool(promo_entry and promo_entry.get("enabled"))
        promo_expires = promo_entry.get("expires_at") if isinstance(promo_entry, dict) else None
        promo_risk_cap = float(promo_entry.get("risk_mult_cap", 0.25)) if promo_entry else None
        promo_max_positions = int(promo_entry.get("max_positions", 1)) if promo_entry else None

        # Quarantine override
        quarantined = False
        if isinstance(quarantine, dict):
            if quarantine.get("enabled") and sym_upper in (quarantine.get("blocked_symbols") or []):
                quarantined = True
        if isinstance(quarantine, list) and sym_upper in quarantine:
            quarantined = True

        # Global slot limits
        core_limits = slot_limits.get("core") if isinstance(slot_limits, dict) else {}
        core_total_limit = int(core_limits.get("max_positions_total", 3)) if isinstance(core_limits, dict) else 3
        core_per_limit = int(core_limits.get("max_positions_per_symbol", 1)) if isinstance(core_limits, dict) else 1
        core_risk_cap = float(core_limits.get("risk_mult_cap", 0.25)) if isinstance(core_limits, dict) else 0.25

        # Exploration lane caps
        expl_enabled = bool(exploration_cfg.get("enabled", True)) if isinstance(exploration_cfg, dict) else True
        expl_lane_enabled = bool(exploration_lane_cfg.get("enabled", True)) if isinstance(exploration_lane_cfg, dict) else True
        expl_base_cap = int(exploration_lane_cfg.get("max_positions_per_symbol", exploration_lane_cfg.get("max_open_per_symbol", 1)) or 1) if isinstance(exploration_lane_cfg, dict) else 1
        expl_risk_cap = float(exploration_lane_cfg.get("risk_mult_cap", 0.25)) if isinstance(exploration_lane_cfg, dict) else 0.25
        # Phase 5I: Exploration must produce real signal, not noise
        # Minimum risk_mult >= 0.08 to generate meaningful P&L data
        expl_risk_cap = max(expl_risk_cap, 0.08)
        expl_base_cap = max(1, expl_base_cap)

        # Apply exploration override if enabled
        expl_cap = expl_base_cap
        expl_override = exploration_overrides.get(sym_upper, {}) if isinstance(exploration_overrides, dict) else {}
        if isinstance(expl_override, dict) and expl_override.get("enabled"):
            delta = int(expl_override.get("exploration_cap_delta", 0) or 0)
            expl_cap = max(1, expl_base_cap + delta)

        # Recovery lane caps (fallbacks)
        rec_caps = {}
        if isinstance(recovery_ramp, dict):
            rec_caps = (recovery_ramp.get("caps") or {}) if isinstance(recovery_ramp.get("caps"), dict) else {}
        rec_risk_cap = float(rec_caps.get("risk_mult_cap", 0.25))
        rec_max_positions = int(rec_caps.get("max_positions", 1))

        # Per-symbol performance metrics (sorted events)
        events = sorted(trade_events.get(sym_upper, []), key=lambda x: x[0])
        pct_7d = [p for ts_dt, p in events if ts_dt >= cutoff_7d]
        pct_30d = [p for ts_dt, p in events if ts_dt >= cutoff_30d]
        pct_24h = [p for ts_dt, p in events if ts_dt >= cutoff_24h]

        pf_7d, closes_7d, gross_profit_7d, gross_loss_7d = _pf_summary(pct_7d)
        pf_30d, closes_30d, gross_profit_30d, gross_loss_30d = _pf_summary(pct_30d)
        clean_24h = len([p for p in pct_24h if p > 0])
        loss_24h = len([p for p in pct_24h if p < 0])
        loss_streak_24h = _loss_streak([(ts, p) for ts, p in events if ts >= cutoff_24h])

        # Base allows
        allow_exploration = expl_enabled and expl_lane_enabled and not quarantined
        allow_core = False
        allow_recovery = False

        # REVIEW bootstrap: exploration only, block core/recovery
        # (In sample-building mode we disable review_bootstrap and may force global mode to normal)
        if capital_mode == "review":
            allow_core = False
            allow_recovery = False
            allow_exploration = not quarantined

        # Ladder: quarantine overrides all
        if quarantined:
            state_val = "quarantined"
            allow_core = False
            allow_exploration = False
            allow_recovery = False
        else:
            pf_unknown = pf_7d is None
            # Halted but not quarantined -> apply earn-back logic
            # PHASE 5I FIX: Only allow rehab if symbol has meaningful sample (>=30 closes)
            # AND is past sample_building phase. Prevents premature demotion.
            if stance == "halt" and closes_7d >= 30:
                # Apply earn-back logic for demoted symbols
                print(f"DEBUG_EARNBACK: Applying earn-back for {sym_upper} (stance={stance}, closes={closes_7d})")

                # Get capital protection data for this symbol
                cp_symbols = (capital_protection.get("symbols") or {}) if isinstance(capital_protection, dict) else {}
                sym_cp = cp_symbols.get(sym_upper, {}) if isinstance(cp_symbols, dict) else {}

                demoted_at = sym_cp.get("demoted_at") or sym_cp.get("last_updated") or now_dt.isoformat()
                earnback_config = get_default_recovery_config()

                # Get post-demotion metrics (simplified - use available data)
                post_metrics = {
                    "pf_7d": pf_7d or 0,
                    "n_closes_7d": closes_7d or 0
                }

                earnback_state = compute_earnback_state(
                    symbol=sym_upper,
                    metrics=post_metrics,
                    now=now_dt,
                    last_demote_ts=demoted_at,
                    window_stats=post_metrics,
                    config=earnback_config
                )

                print(f"DEBUG_EARNBACK: {sym_upper} stage={earnback_state['recovery_stage']}, exploration={earnback_state['allow_exploration']}")

                # Apply earn-back allowances
                state_val = f"recovery_{earnback_state['recovery_stage']}"
                allow_core = earnback_state["allow_core"]
                allow_exploration = earnback_state["allow_exploration"]
                allow_recovery = earnback_state["allow_recovery"]

                print(f"DEBUG_EARNBACK: Setting {sym_upper} state={state_val}, core={allow_core}, exploration={allow_exploration}")

                reasons["earnback"] = f"Stage: {earnback_state['recovery_stage']}, PF: {pf_7d:.2f}"
            else:
                # Promotion can lift to core eligibility
                if promo_active:
                    allow_core = True
                    state_val = "core"
                # Phase 5I: Per-coin lifecycle enforcement
                # sample_building (< 30 closes): core + exploration ON, no restrictions
                # evaluation (30-60 closes): PF tracking, no quarantine/recovery
                # enforcement (>= 60 closes): full PF-based decisions allowed
                if closes_7d < 30:
                    state_val = "sample_building"
                    # PHASE 5I: Sample building allows unrestricted core + exploration
                    # regardless of stance - the point is to build meaningful samples
                    allow_exploration = True  # Always allow exploration in sample building
                    allow_core = True  # Always allow core in sample building
                    allow_recovery = False
                    reasons["sample_building"] = "n_closes_7d < 30: allow sampling (core+exploration), defer all PF enforcement"
                elif closes_7d < 60:
                    state_val = "evaluation"
                    allow_exploration = allow_exploration and stance != "halt"
                    allow_core = True if stance != "halt" else False
                    allow_recovery = False
                    reasons["evaluation"] = "n_closes_7d 30-60: PF tracking active, no quarantine/recovery enforcement"
                else:
                    # Phase 5I enforcement phase (>= 60 closes): full PF-based decisions
                    # Use earn-back system for demoted symbols
                    demoted_at = None
                    if sym in stance_map and stance_map[sym] in {"halt", "observe"}:
                        # Check if this symbol was recently demoted
                        cp_symbols = (capital_protection.get("symbols") or {}) if isinstance(capital_protection, dict) else {}
                        sym_cp = cp_symbols.get(sym, {}) if isinstance(cp_symbols, dict) else {}
                        if sym_cp.get("stance") in {"halt", "observe"}:
                            demoted_at = sym_cp.get("demoted_at") or sym_cp.get("last_updated")

                    # Use earn-back system for demoted symbols (halt stance)
                    recovery_config = get_default_recovery_config()
                    window_stats = {
                        "n_closes": closes_7d,
                        "pf": pf_7d,
                        "win_rate": None,  # Would need per-trade analysis
                        "max_drawdown": None  # Would need drawdown calculation
                    }

                    earnback_state = compute_earnback_state(
                        symbol=sym,
                        metrics={"pf_7d": pf_7d, "n_closes_7d": closes_7d},
                        now=now_dt,
                        last_demote_ts=demoted_at,  # May be None
                        window_stats=window_stats,
                        config=recovery_config
                    )

                    # Apply earn-back state
                    state_val = f"recovery_{earnback_state['recovery_stage']}"
                    allow_core = earnback_state["allow_core"]
                    allow_exploration = earnback_state["allow_exploration"]
                    allow_recovery = earnback_state["allow_recovery"]

                    reasons["earnback"] = f"Stage: {earnback_state['recovery_stage']}, PF: {pf_7d:.2f}"
                    if (
                        pf_7d is not None
                        and pf_7d >= 1.05
                        and stance != "halt"
                        and (
                            pf_30d is None
                            or pf_30d >= 1.00
                            or loss_streak_24h == 0
                        )
                    ):
                        state_val = "core"
                        allow_core = True
                        allow_exploration = True
                        allow_recovery = False
                        reasons["core"] = f"PF {pf_7d:.2f} >= 1.05 in enforcement phase"
                    elif pf_unknown:
                        state_val = "exploration"
                        allow_core = False
                        allow_exploration = allow_exploration and stance != "halt"
                        allow_recovery = False
                        reasons["exploration"] = "Unknown PF in enforcement phase"
                    else:
                        # Default fallback in enforcement
                        state_val = "observe"
                        allow_core = False
                        allow_exploration = allow_exploration and stance != "halt"
                        allow_recovery = False
                        reasons["observe"] = "Default enforcement phase fallback"

            # Stance guardrails - but allow sample_building and earn-back recovery unrestricted
            # PHASE 5I: Sample building overrides stance restrictions
            # EARN-BACK: Recovery states from earn-back system override stance restrictions
            if stance == "halt" and state_val != "sample_building" and not state_val.startswith("recovery_"):
                allow_core = False
                allow_exploration = False
                if state_val != "recovery":
                    allow_recovery = False
                    state_val = "halted"

        # Apply promotion caps to core lane if active
        core_risk_cap_eff = core_risk_cap
        if promo_active and promo_risk_cap is not None:
            core_risk_cap_eff = min(core_risk_cap_eff, promo_risk_cap)
        core_max_pos_eff = promo_max_positions if promo_active and promo_max_positions is not None else core_per_limit

        # Phase 5I: Per-coin lifecycle with meaningful sample thresholds
        if closes_7d < 30:
            sample_stage = "sample_building"
        elif closes_7d < 60:
            sample_stage = "evaluation"
        else:
            # enforcement phase: full PF-based decisions allowed
            pf_good = pf_7d is not None and pf_7d >= 1.05
            sample_stage = "enforcement"

        # Phase 5I: Toxic PF quarantine only in enforcement phase (>= 60 closes)
        toxic_pf = closes_7d >= 60 and pf_7d is not None and pf_7d < 0.85
        if toxic_pf:
            quarantined = True
            state_val = "quarantined"
            allow_core = False
            allow_exploration = False
            allow_recovery = False
            sample_stage = "quarantined"
            reasons["quarantine_override"] = "pf7d_floor (pf7d < 0.85 with n>=60)"

        # caps_by_lane
        caps_by_lane = {
            "core": {
                "risk_mult_cap": core_risk_cap_eff,
                "max_positions": core_max_pos_eff,
            },
            "exploration": {
                "risk_mult_cap": expl_risk_cap,  # Phase 5I: >= 0.08 for real signal
                "max_positions": min(max(expl_cap, 1), 2),
            },
            "recovery": {
                "risk_mult_cap": min(rec_risk_cap, 0.10),
                "max_positions": min(rec_max_positions, 1),
            },
        }

        policy = {
            "state": state_val,
            "stance": stance,
            "sample_stage": sample_stage,
            "quarantined": quarantined,
            "promotion_active": promo_active,
            "promotion_expires_at": promo_expires,
            "exploration_override": expl_override if isinstance(expl_override, dict) else None,
            "allow_core": allow_core,
            "allow_exploration": allow_exploration,
            "allow_recovery": allow_recovery,
            "caps_by_lane": caps_by_lane,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "reasons": reasons,
            # Top-level PF metrics for quick diagnostics
            "pf_7d": pf_7d,
            "pf_30d": pf_30d,
            "n_closes_7d": closes_7d,
            "n_closes_30d": closes_30d,
            "metrics": {
                    "pf_7d": pf_7d,
                    "pf_30d": pf_30d,
                    "closes_7d": closes_7d,
                    "closes_30d": closes_30d,
                    "clean_closes_24h": clean_24h,
                    "loss_closes_24h": loss_24h,
                    "loss_streak_24h": loss_streak_24h,
                    "gross_profit_7d": gross_profit_7d,
                    "gross_loss_7d": gross_loss_7d,
                    "gross_profit_30d": gross_profit_30d,
                    "gross_loss_30d": gross_loss_30d,
                },
        }

        payload["symbols"][sym_upper] = policy

    atomic_write_symbol_states(payload)
    print(f"symbol_states written to {STATE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

