"""
Capital Protection Engine
-------------------------

Pro-quant capital protection and withdrawal planner for Chloe.

Responsibilities:
  * Read PF time-series from reports/pf/pf_timeseries.json
  * Read system sanity (loss streak, policy) from reports/system/sanity_report.json
  * Derive:
      - global risk_mode
      - per-symbol risk stance
      - recommended actions
      - suggested withdrawal fraction (for future live mode)
  * Write to:
      reports/risk/capital_protection.json

This module is ADVISORY-ONLY and PAPER-SAFE.
It does not modify configs, positions, or accounts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

from engine_alpha.core.paths import REPORTS
from engine_alpha.core.config_loader import load_engine_config

PF_TS_PATH = REPORTS / "pf" / "pf_timeseries.json"
SANITY_PATH = REPORTS / "system" / "sanity_report.json"
OUT_PATH = REPORTS / "risk" / "capital_protection.json"
MODE_STATE_PATH = REPORTS / "risk" / "capital_mode_state.json"
TRADES_PATH = REPORTS / "trades.jsonl"

# Phase 4j: Min-trade gates
MIN_TRADES_7D = 40
MIN_TRADES_30D = 80
COOLDOWN_MINUTES = 60


@dataclass
class SymbolProtection:
    symbol: str
    tier: Optional[str]
    pf_7d: Optional[float]
    pf_30d: Optional[float]
    drift: str
    stance: str  # "normal" | "de_risk" | "underweight" | "halt"
    notes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "tier": self.tier,
            "pf_7d": self.pf_7d,
            "pf_30d": self.pf_30d,
            "drift": self.drift,
            "stance": self.stance,
            "notes": self.notes,
        }


def _safe_load(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _extract_pf(pf_ts: Dict[str, Any], key: str) -> Optional[float]:
    entry = pf_ts.get(key)
    if not entry:
        return None
    pf = entry.get("pf")
    if pf is None:
        return None
    try:
        return float(pf)
    except Exception:
        return None


def _extract_trades(pf_ts: Dict[str, Any], key: str) -> int:
    """Phase 4j: Extract trade count for a window."""
    entry = pf_ts.get(key)
    if not entry:
        return 0
    trades = entry.get("trades")
    if trades is None:
        return 0
    try:
        return int(trades)
    except Exception:
        return 0


def _count_bootstrap_closes_24h(now: datetime, allowed_reasons: set[str], allowed_kinds: set[str]) -> int:
    if not TRADES_PATH.exists():
        return 0
    cutoff = now - timedelta(hours=24)
    n = 0
    try:
        with TRADES_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    evt = json.loads(line)
                except Exception:
                    continue
                if (evt.get("type") or "").lower() != "close":
                    continue
                tk = (evt.get("trade_kind") or "").lower()
                if tk not in allowed_kinds:
                    continue
                reason = (evt.get("exit_reason") or evt.get("exit_label") or "").lower()
                if not reason or reason.startswith("manual_"):
                    continue
                if reason not in allowed_reasons:
                    continue
                ts = evt.get("ts") or evt.get("timestamp")
                if not ts:
                    continue
                try:
                    ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
                except Exception:
                    continue
                if ts_dt >= cutoff:
                    n += 1
    except Exception:
        return 0
    return n


def _load_mode_state() -> Dict[str, Any]:
    """Phase 4j: Load capital mode state (cooldown memory)."""
    if not MODE_STATE_PATH.exists():
        return {}
    try:
        with MODE_STATE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_mode_state(mode: str, now: datetime) -> None:
    """Phase 4j: Save capital mode state."""
    state = {
        "current_mode": mode,
        "last_mode_change_ts": now.isoformat(),
        "cooldown_minutes": COOLDOWN_MINUTES,
    }
    MODE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MODE_STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def _derive_global_mode(global_ts: Dict[str, Any], sanity: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    pf_7d = _extract_pf(global_ts, "7d")
    pf_30d = _extract_pf(global_ts, "30d")
    pf_1d = _extract_pf(global_ts, "1d")
    
    # Phase 4j: Extract trade counts
    trades_7d = _extract_trades(global_ts, "7d")
    trades_30d = _extract_trades(global_ts, "30d")
    try:
        trades_7d = int(trades_7d)
    except Exception:
        trades_7d = 0
    try:
        trades_30d = int(trades_30d)
    except Exception:
        trades_30d = 0

    loss_streak = None
    rec = None
    if sanity:
        core = sanity.get("core") or sanity  # depending on structure
        loss_streak = core.get("loss_streak")
        rec = core.get("rec") or core.get("recommendation")

    # Phase 4j: Load mode state and check cooldown
    mode_state = _load_mode_state()
    current_mode = mode_state.get("current_mode", "normal")
    last_change_ts_str = mode_state.get("last_mode_change_ts")
    
    now = datetime.now(timezone.utc)
    in_cooldown = False
    if last_change_ts_str:
        try:
            last_change_ts = datetime.fromisoformat(last_change_ts_str.replace("Z", "+00:00"))
            if last_change_ts.tzinfo is None:
                last_change_ts = last_change_ts.replace(tzinfo=timezone.utc)
            age_minutes = (now - last_change_ts).total_seconds() / 60.0
            in_cooldown = age_minutes < COOLDOWN_MINUTES
        except Exception:
            pass

    mode = "normal"
    reasons: List[str] = []
    actions: List[str] = []

    # Phase 4j: Min-trade gates with review bootstrap override
    bootstrap_closes_24h = 0
    rb_threshold = None
    rb_enabled = False
    try:
        cfg = load_engine_config()
        rb = cfg.get("review_bootstrap", {}) if isinstance(cfg, dict) else {}
        rb_enabled = bool(rb.get("enabled", False))
        rb_threshold = int(rb.get("min_closes_to_exit_review", 6))
        now_ts = now
        if rb_enabled:
            allowed_reasons = {
                "review_bootstrap_timeout",
                "review_bootstrap_timeout_manual",
                "timeout_max_hold",
                "tp",
                "sl",
                "reverse",
                "drop",
            }
            allowed_kinds = {"exploration"}
            bootstrap_closes_24h = _count_bootstrap_closes_24h(now_ts, allowed_reasons, allowed_kinds)
    except Exception:
        rb_enabled = False
        rb_threshold = None

    bootstrap_override_used = False
    # Phase 5I: Check if ANY symbol is in sample_building phase (< 30 closes)
    # If so, force normal mode and make capital protection advisory only
    per_coin_sample_building = False
    try:
        from engine_alpha.risk.symbol_state import load_symbol_states
        symbol_states = load_symbol_states()
        if isinstance(symbol_states, dict) and "symbols" in symbol_states:
            symbols = symbol_states["symbols"]
            if isinstance(symbols, dict):
                for sym, state in symbols.items():
                    if isinstance(state, dict):
                        sample_stage = state.get("sample_stage", "")
                        n_closes = state.get("n_closes_7d", 0)
                        if sample_stage == "sample_building" or n_closes < 30:
                            per_coin_sample_building = True
                            break
    except Exception:
        # If we can't load symbol states, assume no sample building
        pass

    # Sample-building advisory: when sample is not meaningful yet, do not force PF-based global risk-off.
    sample_low = (trades_7d < MIN_TRADES_7D) or (trades_30d < MIN_TRADES_30D)

    if sample_low or per_coin_sample_building:
        if per_coin_sample_building:
            mode = "normal"
            reasons.append("Phase 5I: Per-coin sample building active - capital protection advisory only")
        else:
            mode = "review"
            reasons.append(
                f"Insufficient sample: trades_7d={trades_7d} (min {MIN_TRADES_7D}), "
                f"trades_30d={trades_30d} (min {MIN_TRADES_30D})."
            )
            if rb_enabled and rb_threshold is not None and bootstrap_closes_24h >= rb_threshold:
                # Override out of review using bootstrap closes; use de_risk as safe intermediate mode
                mode = "de_risk"
                bootstrap_override_used = True
                # Ensure trade counts reflect bootstrap sample so downstream sees non-zero sample
                trades_7d = max(trades_7d, bootstrap_closes_24h)
                trades_30d = max(trades_30d, bootstrap_closes_24h)
    # Conservative defaults
    elif pf_7d is None or pf_30d is None:
        mode = "observe"
        reasons.append("Insufficient PF history; staying in observe mode.")
    else:
        if pf_7d < 0.90:
            mode = "halt_new_entries"
            reasons.append(f"7d PF {pf_7d:.2f} < 0.90: halt new entries and de-risk.")
        elif pf_7d < 0.95:
            mode = "de_risk"
            reasons.append(f"7d PF {pf_7d:.2f} < 0.95: de-risk and tighten exposure.")
        elif pf_30d >= 1.10 and pf_7d >= 1.05:
            mode = "harvest"
            reasons.append(
                f"30d PF {pf_30d:.2f} and 7d PF {pf_7d:.2f} strong: time to harvest profits and protect capital."
            )
        else:
            mode = "normal"
            reasons.append("PF windows in acceptable range; operate in normal risk mode.")

    if loss_streak is not None and loss_streak >= 7:
        mode = "halt_new_entries"
        reasons.append(f"Loss streak {loss_streak} ≥ 7: override to halt_new_entries.")

    if rec and rec != "GO":
        reasons.append(f"System sanity recommendation: {rec}")

    # If bootstrap override was used, replace reasons with a truthful message
    if bootstrap_override_used:
        reasons = [f"review_bootstrap_exit: clean_closes_24h={bootstrap_closes_24h} >= {rb_threshold}"]

    # Phase 5I: Sample-building override - if any coin in sample_building, keep permissive
    # Do NOT override hard safety (loss streak) above.
    if (sample_low or per_coin_sample_building) and mode in {"de_risk", "halt_new_entries"}:
        if per_coin_sample_building:
            reasons.append(f"Phase 5I per-coin sample building: forced normal mode")
        else:
            reasons.append(f"sample_building_advisory_only: suggested={mode} (trades_7d={trades_7d}, trades_30d={trades_30d})")
        mode = "normal"
    
    # Phase 4j: Cooldown check - if in cooldown and mode changed, keep current mode
    if in_cooldown and mode != current_mode:
        reasons.append(
            f"Mode change suppressed (cooldown): suggested={mode}, keeping={current_mode} "
            f"(cooldown {COOLDOWN_MINUTES}m active)."
        )
        mode = current_mode
    elif mode != current_mode:
        # Mode changed, save new state
        _save_mode_state(mode, now)

    # Optional: suppress global capital protection enforcement (bootstrap sampling phase)
    suggested_mode = None
    try:
        cfg = load_engine_config() or {}
        cp_cfg = (cfg.get("capital_protection") or {}) if isinstance(cfg, dict) else {}
        enforcement = (cp_cfg.get("global_enforcement") or "enforce").strip().lower()
        disabled_mode = (cp_cfg.get("disabled_global_mode") or "normal").strip().lower()
        if enforcement == "disabled":
            # Keep the system trading/sampling; per-symbol quarantine still applies via symbol_states.
            suggested_mode = mode
            if disabled_mode not in {"normal", "observe", "review", "de_risk"}:
                disabled_mode = "normal"
            if mode != disabled_mode:
                reasons.append(f"global_capital_protection_disabled: suggested={mode} -> {disabled_mode}")
            mode = disabled_mode
    except Exception:
        pass

    # Actions implied by mode
    if mode in ("halt_new_entries", "de_risk"):
        actions.append("freeze_tuning")
        actions.append("disable_profit_amplifier")
        actions.append("reduce_exposure")
    if mode == "harvest":
        actions.append("take_partial_withdrawal")
        actions.append("cap_exposure")
        actions.append("disable_profit_amplifier")
    if mode == "normal":
        actions.append("maintain_current_risk")
    if mode == "observe":
        actions.append("collect_more_data")

    # Suggested withdrawal fraction (for future live usage only)
    if mode == "harvest":
        withdraw_frac = 0.15
    elif mode == "halt_new_entries":
        withdraw_frac = 0.0
    else:
        withdraw_frac = 0.0

    return {
        "mode": mode,
        "suggested_mode": suggested_mode,
        "pf_1d": pf_1d,
        "pf_7d": pf_7d,
        "pf_30d": pf_30d,
        "pf_90d": _extract_pf(global_ts, "90d"),
        "trades_7d": trades_7d,  # Phase 4j
        "trades_30d": trades_30d,  # Phase 4j
        "bootstrap_clean_closes_24h": bootstrap_closes_24h,
        "bootstrap_min_required": rb_threshold,
        "loss_streak": loss_streak,
        "sanity_rec": rec,
        "reasons": reasons,
        "actions": actions,
        "suggested_withdrawal_fraction": withdraw_frac,
    }


def _derive_symbol_stances(
    pf_ts: Dict[str, Any],
    sanity: Optional[Dict[str, Any]],
) -> List[SymbolProtection]:
    symbols_ts = pf_ts.get("symbols", {})
    sanity_symbols = (sanity or {}).get("symbols", {})

    results: List[SymbolProtection] = []

    for sym, ts_data in symbols_ts.items():
        pf_7d = _extract_pf(ts_data, "7d")
        pf_30d = _extract_pf(ts_data, "30d")

        san = sanity_symbols.get(sym, {})
        tier = san.get("tier")
        drift = san.get("drift", "unknown")

        stance = "normal"
        notes: List[str] = []

        if pf_7d is None or pf_30d is None:
            stance = "observe"
            notes.append("Insufficient PF history; observe only.")
        else:
            if pf_7d < 0.9 or pf_30d < 0.95:
                stance = "halt"
                notes.append(f"Weak PF (7d={pf_7d:.2f}, 30d={pf_30d:.2f}); halt new capital allocation.")
            elif pf_7d < 1.0:
                stance = "underweight"
                notes.append(f"PF below 1.0 (7d={pf_7d:.2f}); keep symbol underweight.")
            elif pf_30d >= 1.10 and pf_7d >= 1.05:
                stance = "normal"
                notes.append("Strong PF; eligible for normal allocation within risk limits.")
            else:
                stance = "normal"
                notes.append("PF within acceptable range.")

        if drift == "degrading":
            notes.append("Drift degrading; be cautious on scaling.")
            if stance == "normal":
                stance = "underweight"

        results.append(
            SymbolProtection(
                symbol=sym,
                tier=tier,
                pf_7d=pf_7d,
                pf_30d=pf_30d,
                drift=str(drift),
                stance=stance,
                notes=notes,
            )
        )

    return results


def run_capital_protection() -> Dict[str, Any]:
    """
    Main entrypoint used by nightly research / tools.
    """
    pf_ts = _safe_load(PF_TS_PATH)
    if not pf_ts:
        # Nothing to do yet.
        payload = {
            "meta": {
                "engine": "capital_protection_v1",
                "version": "1.0.0",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "advisory_only": True,
                "status": "no_pf_data",
                "issues": ["pf_timeseries not available"],
            },
            "global": {},
            "symbols": [],
        }
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with OUT_PATH.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        return payload

    sanity = _safe_load(SANITY_PATH)

    global_ts = pf_ts.get("global", {})
    global_mode = _derive_global_mode(global_ts, sanity)
    symbols = _derive_symbol_stances(pf_ts, sanity)
    
    # Phase 5H.4: Add recovery assist state if mode is halt_new_entries
    assist_state = None
    if global_mode.get("mode") == "halt_new_entries":
        try:
            from engine_alpha.risk.recovery_assist import evaluate_recovery_assist
            assist_result = evaluate_recovery_assist()
            if assist_result.get("assist_enabled", False):
                assist_state = {
                    "enabled": True,
                    "mode_override": "micro_core_only",
                }
            else:
                assist_state = {
                    "enabled": False,
                    "mode_override": None,
                }
        except Exception:
            # If recovery_assist fails, default to disabled
            assist_state = {
                "enabled": False,
                "mode_override": None,
            }
    
    # Add assist field to global_mode if present
    if assist_state is not None:
        global_mode["assist"] = assist_state

    payload = {
        "meta": {
            "engine": "capital_protection_v1",
            "version": "1.0.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "advisory_only": True,
            "status": "ok",
            "issues": [],
        },
        "global": global_mode,
        "symbols": [s.to_dict() for s in symbols],
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)

    return payload


__all__ = ["run_capital_protection", "OUT_PATH"]

