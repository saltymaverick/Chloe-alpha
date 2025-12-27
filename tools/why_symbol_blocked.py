#!/usr/bin/env python3
"""
Quick diagnostic for a symbol's open eligibility under capital protection + promotions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"

CAPITAL_PROTECTION_PATH = REPORTS / "risk" / "capital_protection.json"
PROMOTION_RUNTIME_PATH = REPORTS / "gpt" / "promotion_runtime.json"
ENGINE_CONFIG_PATH = ROOT / "config" / "engine_config.json"
SYMBOL_STATES_PATH = REPORTS / "risk" / "symbol_states.json"
REFLECTION_PACKET_PATH = REPORTS / "reflection_packet.json"
POSITION_STATE_PATH = REPORTS / "position_state.json"
AUTO_PROMOS_PATH = REPORTS / "risk" / "auto_promotions.json"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def main() -> int:
    sym = (sys.argv[1] if len(sys.argv) > 1 else "AVAXUSDT").upper()

    cp = _read_json(CAPITAL_PROTECTION_PATH)
    cp_mode = (cp.get("global") or {}).get("mode") or cp.get("mode") or "unknown"
    stances = {}
    symbols_section = cp.get("symbols") or cp.get("per_symbol") or {}
    if isinstance(symbols_section, dict):
        for k, v in symbols_section.items():
            try:
                stance = (v or {}).get("stance")
                if stance:
                    stances[str(k).upper()] = stance
            except Exception:
                continue
    elif isinstance(symbols_section, list):
        for entry in symbols_section:
            if not isinstance(entry, dict):
                continue
            k = entry.get("symbol") or entry.get("name")
            stance = entry.get("stance")
            if k and stance:
                stances[str(k).upper()] = stance
    stance = stances.get(sym)

    cfg = _read_json(ENGINE_CONFIG_PATH)
    auto_promos = _read_json(AUTO_PROMOS_PATH)
    symbol_states = _read_json(SYMBOL_STATES_PATH)
    top_slot_limits = symbol_states.get("slot_limits", {}) if isinstance(symbol_states, dict) else {}
    sym_state = (symbol_states.get("symbols") or {}).get(sym, {}) if isinstance(symbol_states, dict) else {}
    allow_core = bool(sym_state.get("allow_core", False))
    allow_exploration = bool(sym_state.get("allow_exploration", False))
    allow_recovery = bool(sym_state.get("allow_recovery", False))
    pf_7d = sym_state.get("pf_7d")
    n_closes_7d = sym_state.get("n_closes_7d")
    sym_state_val = sym_state.get("state")
    reasons = sym_state.get("reasons") or {}
    quarantine_override_reason = reasons.get("quarantine_override")
    caps_core = (sym_state.get("caps_by_lane") or {}).get("core", {}) if isinstance(sym_state, dict) else {}
    caps_expl = (sym_state.get("caps_by_lane") or {}).get("exploration", {}) if isinstance(sym_state, dict) else {}
    # Use top-level slot_limits for totals/per-symbol
    top_core_limits = top_slot_limits.get("core", {}) if isinstance(top_slot_limits, dict) else {}
    core_total_limit = top_core_limits.get("max_positions_total")
    core_per_symbol_limit = top_core_limits.get("max_positions_per_symbol")
    auto_entry = (auto_promos.get("all", {}) if isinstance(auto_promos, dict) else {}).get(sym, {}) if isinstance(auto_promos, dict) else {}
    auto_active_entry = (auto_promos.get("active", {}) if isinstance(auto_promos, dict) else {}).get(sym)
    auto_active = bool(auto_active_entry)
    auto_reason = auto_active_entry.get("reason") if isinstance(auto_active_entry, dict) else auto_entry.get("reason")
    auto_expires = auto_active_entry.get("expires_at") if isinstance(auto_active_entry, dict) else auto_entry.get("expires_at")

    promo_active = bool(sym_state.get("promotion_active"))
    promo_expires = sym_state.get("promotion_expires_at")
    promo_expired = False
    if promo_expires:
        try:
            dt = datetime.fromisoformat(promo_expires.replace("Z", "+00:00"))
            promo_expired = dt < datetime.now(timezone.utc)
        except Exception:
            promo_expired = False
    stance = sym_state.get("stance") or stance
    qualifies_for_halt_bypass = False
    halt_bypass_reason = None
    if cp_mode in {"halt_new_entries", "de_risk"}:
        pf_good = pf_7d is not None and pf_7d >= 1.05 and (n_closes_7d or 0) >= 20
        if allow_core and ((promo_active and not promo_expired) or pf_good):
            qualifies_for_halt_bypass = True
            halt_bypass_reason = "promotion" if (promo_active and not promo_expired) else "pf7d_good"

    runtime = _read_json(PROMOTION_RUNTIME_PATH)
    runtime_mode = runtime.get("capital_mode", "unknown")
    bypass_used = runtime.get("bypass_used_last_tick", [])
    bypass_reason = (runtime.get("bypass_reason_by_symbol") or {}).get(sym)

    reflection = _read_json(REFLECTION_PACKET_PATH)
    opp = (reflection.get("primitives") or {}).get("opportunity") or {}
    eligible_now = opp.get("eligible_now")
    eligible_reason = opp.get("eligible_now_reason")
    density_bypass_applied = opp.get("density_bypass_applied")
    density_bypass_due_to_promotion = opp.get("density_bypass_due_to_promotion")

    # Slot counts (core ledger only, excluding recovery)
    open_positions = (_read_json(POSITION_STATE_PATH).get("positions") or {})
    core_positions = {
        k: v
        for k, v in open_positions.items()
        if v.get("trade_kind") != "recovery_v2" and (v.get("dir") or 0) != 0
    }
    core_positions_symbol = {k: v for k, v in core_positions.items() if k.upper().startswith(f"{sym}_")}
    core_open_count = len(core_positions)
    core_symbol_count = len(core_positions_symbol)

    # Block reasons synthesis
    blocked_by = []
    if sym_state.get("quarantined"):
        blocked_by.append("quarantine_block")
    if not allow_core:
        blocked_by.append("policy_block_core")
    if not allow_exploration:
        blocked_by.append("policy_block_exploration")
    if not allow_recovery:
        blocked_by.append("policy_block_recovery")
    if promo_expired and promo_active:
        blocked_by.append("promotion_expired")
        promo_active = False
    if cp_mode in {"halt_new_entries", "de_risk"} and not (stance == "normal" or promo_active):
        blocked_by.append("capital_mode_block")
    if eligible_now is False:
        blocked_by.append("opportunity_block")
    if core_total_limit and core_open_count >= core_total_limit:
        blocked_by.append("core_slot_full")
    if core_per_symbol_limit and core_symbol_count >= core_per_symbol_limit:
        blocked_by.append("per_symbol_slot_full")

    density_bypass_possible = False
    if eligible_now is False and eligible_reason and "density_below_floor" in str(eligible_reason):
        if cp_mode in {"halt_new_entries", "de_risk"} and (stance == "normal" or promo_active):
            density_bypass_possible = True
        elif promo_active:
            density_bypass_possible = True

    # Effective eligibility when promo bypasses density
    effective_eligible = eligible_now
    effective_reason = eligible_reason
    if density_bypass_due_to_promotion or (promo_active and eligible_now is False and eligible_reason and "density_below_floor" in str(eligible_reason)):
        effective_eligible = True
        effective_reason = "density_below_floor_bypassed_promotion"
        blocked_by = [b for b in blocked_by if b != "opportunity_block"]

    print("=== WHY SYMBOL BLOCKED ===")
    print(f"symbol: {sym}")
    print(f"capital_mode: {cp_mode}")
    print(f"stance: {stance}")
    print(f"promotion_active(runtime): {promo_active} expired: {promo_expired} expires_at: {promo_expires}")
    print(f"auto_promotion_active: {auto_active} reason: {auto_reason} expires_at: {auto_expires}")
    print(f"state: {sym_state_val}")
    print(f"pf_7d: {pf_7d} n_closes_7d: {n_closes_7d}")
    if quarantine_override_reason:
        print(f"quarantine_override_reason: {quarantine_override_reason}")
    print(f"symbol_state.allow_core={allow_core} allow_exploration={allow_exploration} allow_recovery={allow_recovery}")
    if isinstance(top_core_limits, dict):
        print(f"slot_limits.core: total={top_core_limits.get('max_positions_total')} per_symbol={top_core_limits.get('max_positions_per_symbol')} risk_mult_cap={top_core_limits.get('risk_mult_cap')}")
    if isinstance(caps_expl, dict):
        print(f"exploration_caps: max_positions={caps_expl.get('max_positions')} risk_mult_cap={caps_expl.get('risk_mult_cap')}")
    print(f"runtime.capital_mode: {runtime_mode}")
    print(f"runtime.bypass_used_last_tick: {bypass_used}")
    print(f"runtime.bypass_reason: {bypass_reason}")
    print(f"opportunity.eligible_now: {eligible_now} reason: {eligible_reason}")
    print(f"effective_eligible_now: {effective_eligible} effective_reason: {effective_reason}")
    print(f"opportunity.density_bypass_applied: {density_bypass_applied}")
    print(f"opportunity.density_bypass_due_to_promotion: {density_bypass_due_to_promotion}")
    print(f"density_bypass_possible_now: {density_bypass_possible}")
    if cp_mode in {"halt_new_entries", "de_risk"}:
        print(f"halt_bypass_possible: {qualifies_for_halt_bypass} reason: {halt_bypass_reason}")
    print(f"core_open_count: {core_open_count} core_symbol_count: {core_symbol_count} "
          f"limits total={core_total_limit} per_symbol={core_per_symbol_limit}")
    print(f"blocked_by: {blocked_by or ['none']}")
    print("Allowed if: (capital_mode in [de_risk, halt_new_entries] AND (stance==normal OR promotion active)) "
          "OR (promotion active and density is the only blocker in normal mode), AND not quarantined/execql/feed-stale/other gates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

