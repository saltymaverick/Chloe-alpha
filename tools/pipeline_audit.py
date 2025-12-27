#!/usr/bin/env python3
"""
Pipeline audit tool for Chloe trading system.
Validates critical components and reports PASS/FAIL status.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple
from dateutil import parser

from engine_alpha.core.config_loader import load_engine_config
from engine_alpha.loop.position_manager import load_position_state
from engine_alpha.data.price_feed_health import get_latest_trade_price

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def audit_slot_caps() -> Tuple[bool, str]:
    """Audit slot limits and position caps."""
    try:
        cfg = load_engine_config()
        slot_limits = cfg.get("slot_limits", {}) if isinstance(cfg, dict) else {}

        # Check core caps
        core_caps = slot_limits.get("core", {})
        if not isinstance(core_caps, dict):
            return False, "core caps not dict"
        risk_mult_cap = core_caps.get("risk_mult_cap")
        if risk_mult_cap is None or not isinstance(risk_mult_cap, (int, float)):
            return False, f"core risk_mult_cap invalid: {risk_mult_cap}"

        # Check exploration caps
        expl_caps = slot_limits.get("exploration", {})
        if not isinstance(expl_caps, dict):
            return False, "exploration caps not dict"

        return True, f"core_risk_mult_cap={risk_mult_cap}"
    except Exception as e:
        return False, f"exception: {e}"


def audit_lane_enforcement() -> Tuple[bool, str]:
    """Audit that lane limits are properly enforced."""
    try:
        pos_state = load_position_state()
        positions = pos_state.get("positions", {}) if isinstance(pos_state, dict) else {}

        # Count positions by trade_kind
        counts = {"core": 0, "exploration": 0, "recovery": 0}
        for k, v in positions.items():
            if isinstance(v, dict) and v.get("dir"):
                trade_kind = v.get("trade_kind", "core")
                counts[trade_kind] = counts.get(trade_kind, 0) + 1

        # Check against config limits
        cfg = load_engine_config()
        slot_limits = cfg.get("slot_limits", {}) if isinstance(cfg, dict) else {}

        core_limit = slot_limits.get("core", {}).get("max_positions_total", 1)
        if counts["core"] > core_limit:
            return False, f"core positions {counts['core']} > limit {core_limit}"

        expl_limit = slot_limits.get("exploration", {}).get("max_positions_total", 2)
        if counts["exploration"] > expl_limit:
            return False, f"exploration positions {counts['exploration']} > limit {expl_limit}"

        return True, f"core={counts['core']}/{core_limit}, exploration={counts['exploration']}/{expl_limit}"
    except Exception as e:
        return False, f"exception: {e}"


def audit_per_coin_stage_logic() -> Tuple[bool, str]:
    """Audit per-coin sample stage logic."""
    try:
        from engine_alpha.risk.symbol_state import load_symbol_states
        states = load_symbol_states()
        symbols = states.get("symbols", {}) if isinstance(states, dict) else {}

        issues = []
        for sym, state in symbols.items():
            if not isinstance(state, dict):
                continue

            n_closes = state.get("n_closes_7d", 0)
            sample_stage = state.get("sample_stage", "")
            allow_core = state.get("allow_core", False)

            # Check stage logic
            if n_closes < 30:
                if sample_stage != "sample_building":
                    issues.append(f"{sym}: n_closes={n_closes}, stage={sample_stage} (expected sample_building)")
                if not allow_core:
                    issues.append(f"{sym}: n_closes={n_closes}, allow_core=False (expected True)")
            elif n_closes < 60:
                if sample_stage != "evaluation":
                    issues.append(f"{sym}: n_closes={n_closes}, stage={sample_stage} (expected evaluation)")
            else:
                expected_stage = "eligible" if state.get("pf_7d", 0) >= 1.05 else "quarantined"
                if sample_stage != expected_stage:
                    issues.append(f"{sym}: n_closes={n_closes}, stage={sample_stage} (expected {expected_stage})")

        if issues:
            return False, f"stage logic issues: {len(issues)} ({issues[0][:100]}...)"
        return True, f"checked {len(symbols)} symbols"
    except Exception as e:
        return False, f"exception: {e}"


def audit_mtm_sources() -> Tuple[bool, str]:
    """Audit mark-to-market sources for live positions."""
    try:
        pos_state = load_position_state()
        positions = pos_state.get("positions", {}) if isinstance(pos_state, dict) else {}

        issues = []
        live_positions = 0
        for k, v in positions.items():
            if isinstance(v, dict) and v.get("dir"):
                live_positions += 1
                sym = k.split("_")[0] if "_" in k else k
                px, meta = get_latest_trade_price(sym.upper())
                if px is None or px <= 0:
                    issues.append(f"{k}: no price data")
                elif not meta or not meta.get("source_used"):
                    issues.append(f"{k}: no source metadata")

        if issues:
            return False, f"MTM issues: {len(issues)}/{live_positions} ({issues[0][:50]}...)"
        return True, f"all {live_positions} positions have valid MTM"
    except Exception as e:
        return False, f"exception: {e}"


def audit_pf_math() -> Tuple[bool, str]:
    """Audit PF calculations for edge cases."""
    try:
        pf_data = _read_json(REPORTS / "pf_local.json")
        if not pf_data:
            return False, "no pf_local.json"

        # Check for NaN/Infinite PF values
        pf_fields = [k for k in pf_data.keys() if k.startswith("pf_") and isinstance(pf_data[k], (int, float))]
        for field in pf_fields:
            val = pf_data[field]
            if str(val).lower() in ("nan", "inf", "-inf"):
                return False, f"invalid PF value in {field}: {val}"

        # Check that ex_bootstrap fields make sense
        total_24h = pf_data.get("count_24h", 0)
        ex_bootstrap_24h = pf_data.get("count_24h_ex_bootstrap_timeouts", 0)
        if ex_bootstrap_24h > total_24h:
            return False, f"ex_bootstrap_count {ex_bootstrap_24h} > total {total_24h}"

        return True, f"PF fields valid: {len(pf_fields)} checked"
    except Exception as e:
        return False, f"exception: {e}"


def audit_bootstrap_exclusion() -> Tuple[bool, str]:
    """Audit that bootstrap timeouts are properly excluded from promotion analysis."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        bootstrap_timeouts = 0
        total_closes = 0

        # Count bootstrap timeouts in trades
        for line in open(REPORTS / "trades.jsonl"):
            e = json.loads(line)
            if (e.get("type") or "").lower() != "close":
                continue
            ts = e.get("ts")
            if not ts:
                continue
            if parser.isoparse(ts.replace("Z", "+00:00")) < cutoff:
                continue
            total_closes += 1
            if e.get("exit_reason") == "review_bootstrap_timeout":
                bootstrap_timeouts += 1

        # Check promotion data excludes timeouts
        promo_data = _read_json(REPORTS / "gpt" / "promotion_advice.json")
        if promo_data:
            symbols = promo_data.get("symbols", {})
            total_exploration_closes = sum(
                s.get("exploration", {}).get("7d", {}).get("n_closes", 0)
                for s in symbols.values()
                if isinstance(s, dict)
            )

            if total_exploration_closes > (total_closes - bootstrap_timeouts):
                return False, f"promotion includes {total_exploration_closes} exploration closes but only {total_closes - bootstrap_timeouts} non-timeout closes exist"

        return True, f"bootstrap exclusions working: {bootstrap_timeouts} timeouts excluded"
    except Exception as e:
        return False, f"exception: {e}"


def main() -> int:
    """Run all audits and report results."""
    audits = [
        ("slot_caps", audit_slot_caps),
        ("lane_enforcement", audit_lane_enforcement),
        ("per_coin_stage_logic", audit_per_coin_stage_logic),
        ("mtm_sources", audit_mtm_sources),
        ("pf_math", audit_pf_math),
        ("bootstrap_exclusion", audit_bootstrap_exclusion),
    ]

    print("🔍 Chloe Pipeline Audit")
    print("=" * 50)

    all_pass = True
    for name, audit_func in audits:
        try:
            passed, details = audit_func()
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"{name:<25} {status}")
            if not passed:
                all_pass = False
                print(f"    Details: {details}")
        except Exception as e:
            print(f"{name:<25} ❌ FAIL")
            print(f"    Exception: {e}")
            all_pass = False

    print("=" * 50)
    if all_pass:
        print("🎉 All audits PASSED - pipeline is healthy!")
        return 0
    else:
        print("⚠️  Some audits FAILED - check details above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
