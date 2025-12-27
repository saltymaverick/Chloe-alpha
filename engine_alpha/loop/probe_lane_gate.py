"""
Probe Lane Auto-Enable Gate
----------------------------

Automatically enables/disables probe lane based on shadow evidence and system performance.
Operator must never manually flip probe_lane.enabled - this gate is the single source of truth.

Enable Conditions (ALL required):
- capital_mode == "halt_new_entries"
- shadow_pf_7d >= 1.05
- shadow_pf_30d >= 1.05
- shadow_completed_trades >= 100
- shadow_max_dd <= 0.10%
- At least one symbol with PF_30D >= 1.05, trades >= 30, not quarantined
- Probe lane not auto-disabled in last 24h due to losses

Disable Conditions (ANY triggers):
- capital_mode != halt_new_entries
- shadow_pf_7d < 1.02
- probe losses in last 24h >= 2
- shadow data stale (>90 minutes old)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from engine_alpha.core.paths import REPORTS

# Paths
CAPITAL_PROTECTION_PATH = REPORTS / "risk" / "capital_protection.json"
QUARANTINE_PATH = REPORTS / "risk" / "quarantine.json"
SHADOW_SCORES_PATH = REPORTS / "reflect" / "shadow_exploit_scores.json"
SHADOW_PF_PATH = REPORTS / "reflect" / "shadow_exploit_pf.json"
PROBE_STATE_PATH = REPORTS / "loop" / "probe_lane_state.json"
GATE_STATE_PATH = REPORTS / "loop" / "probe_lane_gate.json"

# Thresholds
MIN_SHADOW_PF_7D = 1.05
MIN_SHADOW_PF_30D = 1.05
MIN_SHADOW_TRADES = 100
MAX_SHADOW_DD = 0.10  # 0.10%
MIN_SYMBOL_PF_30D = 1.05
MIN_SYMBOL_TRADES = 30
DISABLE_PF_7D_THRESHOLD = 1.02
MAX_PROBE_LOSSES_24H = 2
SHADOW_DATA_STALE_MINUTES = 90


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


def _check_shadow_data_freshness(shadow_scores: Dict[str, Any], shadow_pf: Dict[str, Any], now: datetime) -> Tuple[bool, str]:
    """Check if shadow data is fresh (<90 minutes old)."""
    # Check scores timestamp
    scores_ts = shadow_scores.get("meta", {}).get("generated_at") or shadow_scores.get("generated_at")
    pf_ts = shadow_pf.get("generated_at")
    
    timestamps = [ts for ts in [scores_ts, pf_ts] if ts]
    if not timestamps:
        return False, "no_timestamp"
    
    # Check most recent timestamp
    most_recent = None
    for ts_str in timestamps:
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(timezone.utc)
            if most_recent is None or ts > most_recent:
                most_recent = ts
        except Exception:
            continue
    
    if most_recent is None:
        return False, "invalid_timestamp"
    
    age_minutes = (now - most_recent).total_seconds() / 60
    if age_minutes > SHADOW_DATA_STALE_MINUTES:
        return False, f"stale_data_{age_minutes:.1f}m"
    
    return True, ""


def _check_probe_losses_24h(probe_state: Dict[str, Any], now: datetime) -> Tuple[bool, int]:
    """Check probe losses in last 24 hours."""
    losses_24h = probe_state.get("losses_24h", [])
    if not losses_24h:
        return True, 0
    
    recent_losses = 0
    for loss_ts in losses_24h:
        try:
            loss_time = datetime.fromisoformat(loss_ts.replace("Z", "+00:00")).astimezone(timezone.utc)
            if (now - loss_time).total_seconds() < 86400:  # Within 24 hours
                recent_losses += 1
        except Exception:
            continue
    
    return recent_losses < MAX_PROBE_LOSSES_24H, recent_losses


def _check_auto_disable_cooldown(gate_state: Dict[str, Any], now: datetime) -> Tuple[bool, str]:
    """Check if probe lane was auto-disabled in last 24h."""
    last_disable_ts = gate_state.get("last_auto_disable_at")
    if not last_disable_ts:
        return True, ""
    
    try:
        disable_time = datetime.fromisoformat(last_disable_ts.replace("Z", "+00:00")).astimezone(timezone.utc)
        hours_since = (now - disable_time).total_seconds() / 3600
        if hours_since < 24:
            return False, f"auto_disable_cooldown_{hours_since:.1f}h"
    except Exception:
        pass
    
    return True, ""


def evaluate_probe_lane_enablement(now_iso: Optional[str] = None) -> Dict[str, Any]:
    """
    Evaluate whether probe lane should be auto-enabled.
    
    Returns:
        Dict with enabled, decision, reason, and diagnostic data
    """
    now = datetime.now(timezone.utc) if now_iso is None else datetime.fromisoformat(now_iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    
    # Initialize result
    result = {
        "enabled": False,
        "decision": "hold",
        "reason": "",
        "shadow_pf_7d": None,
        "shadow_pf_30d": None,
        "shadow_trades": None,
        "shadow_max_dd": None,
        "eligible_symbols": [],
        "evaluated_at": now.isoformat(),
        "capital_mode": "unknown",
    }
    
    try:
        # Load required data
        capital_protection = _load_json(CAPITAL_PROTECTION_PATH)
        quarantine = _load_json(QUARANTINE_PATH)
        shadow_scores = _load_json(SHADOW_SCORES_PATH)
        shadow_pf = _load_json(SHADOW_PF_PATH)
        probe_state = _load_json(PROBE_STATE_PATH)
        gate_state = _load_json(GATE_STATE_PATH)
        
        # Extract capital mode
        capital_mode = (
            capital_protection.get("mode") or
            capital_protection.get("global", {}).get("mode") or
            "unknown"
        )
        result["capital_mode"] = capital_mode
        
        # DISABLE CONDITION 1: capital_mode != halt_new_entries
        if capital_mode != "halt_new_entries":
            result["decision"] = "auto_disabled"
            result["reason"] = f"capital_mode={capital_mode} (requires halt_new_entries)"
            result["enabled"] = False
            _save_json(GATE_STATE_PATH, result)
            return result
        
        # Check shadow data freshness
        fresh, freshness_reason = _check_shadow_data_freshness(shadow_scores, shadow_pf, now)
        if not fresh:
            result["decision"] = "auto_disabled"
            result["reason"] = f"shadow_data_{freshness_reason}"
            result["enabled"] = False
            _save_json(GATE_STATE_PATH, result)
            return result
        
        # Get global shadow metrics
        global_scores = shadow_scores.get("global", {}) or shadow_scores.get("metrics", {})
        global_pf = shadow_pf.get("global", {}) or shadow_pf.get("metrics", {})
        
        # Prefer display PF, fallback to raw
        shadow_pf_7d = (
            global_scores.get("pf_7d_display") or
            global_scores.get("pf_7d") or
            global_pf.get("pf_7d_display") or
            global_pf.get("pf_7d")
        )
        shadow_pf_30d = (
            global_scores.get("pf_30d_display") or
            global_scores.get("pf_30d") or
            global_pf.get("pf_30d_display") or
            global_pf.get("pf_30d")
        )
        shadow_trades = (
            global_scores.get("trades_30d", 0) or
            global_pf.get("trades_30d", 0) or
            global_scores.get("trades", 0) or
            global_pf.get("trades", 0)
        )
        shadow_max_dd = (
            global_scores.get("max_drawdown_pct") or
            global_pf.get("max_drawdown_pct") or
            0.0
        )
        
        result["shadow_pf_7d"] = shadow_pf_7d
        result["shadow_pf_30d"] = shadow_pf_30d
        result["shadow_trades"] = shadow_trades
        result["shadow_max_dd"] = shadow_max_dd
        
        # DISABLE CONDITION 2: shadow_pf_7d < 1.02
        if shadow_pf_7d is not None and shadow_pf_7d < DISABLE_PF_7D_THRESHOLD:
            result["decision"] = "auto_disabled"
            result["reason"] = f"shadow_pf_7d={shadow_pf_7d:.3f} < {DISABLE_PF_7D_THRESHOLD}"
            result["enabled"] = False
            result["last_auto_disable_at"] = now.isoformat()
            _save_json(GATE_STATE_PATH, result)
            return result
        
        # Check probe losses
        loss_ok, loss_count = _check_probe_losses_24h(probe_state, now)
        if not loss_ok:
            result["decision"] = "auto_disabled"
            result["reason"] = f"probe_losses_24h={loss_count} >= {MAX_PROBE_LOSSES_24H}"
            result["enabled"] = False
            result["last_auto_disable_at"] = now.isoformat()
            _save_json(GATE_STATE_PATH, result)
            return result
        
        # Check auto-disable cooldown
        cooldown_ok, cooldown_reason = _check_auto_disable_cooldown(gate_state, now)
        if not cooldown_ok:
            result["decision"] = "hold"
            result["reason"] = cooldown_reason
            result["enabled"] = False
            _save_json(GATE_STATE_PATH, result)
            return result
        
        # ENABLE CONDITIONS (ALL required)
        
        # Condition 1: shadow_pf_7d >= 1.05
        if shadow_pf_7d is None or shadow_pf_7d < MIN_SHADOW_PF_7D:
            pf_7d_str = f"{shadow_pf_7d:.3f}" if shadow_pf_7d is not None else "None"
            result["decision"] = "hold"
            result["reason"] = f"shadow_pf_7d={pf_7d_str} < {MIN_SHADOW_PF_7D}"
            result["enabled"] = False
            _save_json(GATE_STATE_PATH, result)
            return result
        
        # Condition 2: shadow_pf_30d >= 1.05
        if shadow_pf_30d is None or shadow_pf_30d < MIN_SHADOW_PF_30D:
            pf_30d_str = f"{shadow_pf_30d:.3f}" if shadow_pf_30d is not None else "None"
            result["decision"] = "hold"
            result["reason"] = f"shadow_pf_30d={pf_30d_str} < {MIN_SHADOW_PF_30D}"
            result["enabled"] = False
            _save_json(GATE_STATE_PATH, result)
            return result
        
        # Condition 3: shadow_completed_trades >= 100
        if shadow_trades < MIN_SHADOW_TRADES:
            result["decision"] = "hold"
            result["reason"] = f"shadow_trades={shadow_trades} < {MIN_SHADOW_TRADES}"
            result["enabled"] = False
            _save_json(GATE_STATE_PATH, result)
            return result
        
        # Condition 4: shadow_max_dd <= 0.10%
        if shadow_max_dd is not None and shadow_max_dd > MAX_SHADOW_DD:
            result["decision"] = "hold"
            result["reason"] = f"shadow_max_dd={shadow_max_dd:.3f}% > {MAX_SHADOW_DD}%"
            result["enabled"] = False
            _save_json(GATE_STATE_PATH, result)
            return result
        
        # Condition 5: At least one eligible symbol
        blocked_symbols = set(quarantine.get("blocked_symbols", []))
        by_symbol_scores = shadow_scores.get("by_symbol", {}) or shadow_scores.get("symbols", {})
        by_symbol_pf = shadow_pf.get("by_symbol", {}) or shadow_pf.get("symbols", {})
        
        eligible_symbols = []
        all_symbols = set(by_symbol_scores.keys()) | set(by_symbol_pf.keys())
        
        for symbol in all_symbols:
            if symbol in blocked_symbols:
                continue
            
            score_data = by_symbol_scores.get(symbol, {})
            pf_data = by_symbol_pf.get(symbol, {})
            
            trades_30d = score_data.get("trades_30d", 0) or pf_data.get("trades_30d", 0)
            if trades_30d < MIN_SYMBOL_TRADES:
                continue
            
            pf_30d = (
                score_data.get("pf_30d_display") or
                score_data.get("pf_30d") or
                pf_data.get("pf_30d_display") or
                pf_data.get("pf_30d")
            )
            
            if pf_30d is None or pf_30d < MIN_SYMBOL_PF_30D:
                continue
            
            eligible_symbols.append({
                "symbol": symbol,
                "pf_30d": pf_30d,
                "trades_30d": trades_30d,
            })
        
        result["eligible_symbols"] = eligible_symbols
        
        if not eligible_symbols:
            result["decision"] = "hold"
            result["reason"] = "no_eligible_symbols"
            result["enabled"] = False
            _save_json(GATE_STATE_PATH, result)
            return result
        
        # ALL CONDITIONS MET - AUTO-ENABLE
        result["decision"] = "auto_enabled"
        result["reason"] = "all_conditions_met"
        result["enabled"] = True
        _save_json(GATE_STATE_PATH, result)
        return result
    
    except Exception as e:
        # On error, disable for safety
        result["decision"] = "auto_disabled"
        result["reason"] = f"evaluation_error: {str(e)}"
        result["enabled"] = False
        _save_json(GATE_STATE_PATH, result)
        return result


__all__ = ["evaluate_probe_lane_enablement"]

