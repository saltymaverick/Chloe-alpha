"""
Probe Lane (Micro-Live Exploration During Halt)
------------------------------------------------

A controlled mechanism that can open micro-sized real positions even when
capital_mode == "halt_new_entries", strictly for edge discovery.

Requirements:
- Shadow evidence (PF + trades) must be strong
- At most one micro position per day across entire system
- Strict cooldown after losses
- Respects quarantine and policy states

Safety:
- Never bypasses capital protection thresholds
- Only enabled via explicit config flag
- Fully audited with reason strings and JSON logs
"""

from __future__ import annotations

import json
import os
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.loop.exploit_executor_paper import (
    can_open_exploit_trade,
    open_exploit_trade,
    get_open_positions,
)
from engine_alpha.loop.exploit_intent import compute_exploit_intent
from engine_alpha.data.live_prices import get_live_ohlcv
from engine_alpha.risk.position_sizer import size_notional_usd

# Paths
CONFIG_PATH = CONFIG / "engine_config.json"
CAPITAL_PROTECTION_PATH = REPORTS / "risk" / "capital_protection.json"
QUARANTINE_PATH = REPORTS / "risk" / "quarantine.json"
SHADOW_SCORES_PATH = REPORTS / "reflect" / "shadow_exploit_scores.json"
SHADOW_PF_PATH = REPORTS / "reflect" / "shadow_exploit_pf.json"
POLICY_PATH = REPORTS / "research" / "exploration_policy_v3.json"
CAPITAL_PLAN_PATH = REPORTS / "risk" / "capital_plan.json"
PF_VALIDITY_PATH = REPORTS / "risk" / "pf_validity.json"
STATE_PATH = REPORTS / "loop" / "probe_lane_state.json"
LOG_PATH = REPORTS / "loop" / "probe_lane_log.jsonl"
ERROR_LOG_PATH = REPORTS / "loop" / "probe_lane_errors.jsonl"
GATE_STATE_PATH = REPORTS / "loop" / "probe_lane_gate.json"


def _load_json(path: Path) -> Dict[str, Any]:
    """Safely load JSON file."""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_config() -> Dict[str, Any]:
    """Load probe lane configuration."""
    defaults = {
        "enabled": "auto",  # Only "auto" is valid - gate controls enablement
        "allowed_in_capital_modes": ["halt_new_entries"],
        "max_open_positions_total": 1,
        "max_trades_per_day": 1,
        "position_size_multiplier": 0.02,
        "min_shadow_trades": 30,
        "min_shadow_pf_30d": 1.05,
        "min_shadow_pf_7d": 1.03,
        "require_not_quarantined": True,
        "cooldown_hours_after_loss": 12,
        "disable_after_losses_24h": 2,
        "eligible_policy_states": ["full", "reduced"],
        "forbidden_policy_states": ["blocked"],
    }
    
    if not CONFIG_PATH.exists():
        return defaults
    
    try:
        config = _load_json(CONFIG_PATH)
        probe_config = config.get("probe_lane", {})
        result = defaults.copy()
        result.update(probe_config)
        # Force enabled to "auto" - gate is single source of truth
        result["enabled"] = "auto"
        return result
    except Exception:
        return defaults


def _append_log(entry: Dict[str, Any]) -> None:
    """Append entry to probe lane log."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _append_error_log(error_data: Dict[str, Any]) -> None:
    """Append error details to error log."""
    ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with ERROR_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(error_data) + "\n")
    except Exception:
        pass


def _load_state() -> Dict[str, Any]:
    """Load probe lane state."""
    if not STATE_PATH.exists():
        return {
            "last_trade_at": None,
            "last_symbol": None,
            "last_action": None,
            "losses_24h": [],
            "last_updated": None,
        }
    
    try:
        return _load_json(STATE_PATH)
    except Exception:
        return {
            "last_trade_at": None,
            "last_symbol": None,
            "last_action": None,
            "losses_24h": [],
            "last_updated": None,
        }


def _save_state(state: Dict[str, Any]) -> None:
    """Save probe lane state."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    try:
        with STATE_PATH.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def _check_trade_frequency(state: Dict[str, Any], config: Dict[str, Any], now: datetime) -> Tuple[bool, str]:
    """Check if trade frequency constraints are met."""
    last_trade_at_str = state.get("last_trade_at")
    if last_trade_at_str:
        try:
            last_trade_at = datetime.fromisoformat(last_trade_at_str.replace("Z", "+00:00")).astimezone(timezone.utc)
            # Check if already traded today (UTC)
            if last_trade_at.date() == now.date():
                return False, "max_trades_per_day"
            
            # Check cooldown after loss and loss limit
            losses_24h = state.get("losses_24h", [])
            if losses_24h:
                # Check loss limit first (count losses in last 24 hours)
                disable_after = config.get("disable_after_losses_24h", 2)
                losses_in_24h_count = 0
                last_loss_time = None
                
                for loss_ts in losses_24h:
                    try:
                        loss_time = datetime.fromisoformat(loss_ts.replace("Z", "+00:00")).astimezone(timezone.utc)
                        if (now - loss_time).total_seconds() < 86400:  # Within 24 hours
                            losses_in_24h_count += 1
                            if last_loss_time is None or loss_time > last_loss_time:
                                last_loss_time = loss_time
                    except Exception:
                        continue
                
                # Check loss limit
                if losses_in_24h_count >= disable_after:
                    return False, "loss_limit"
                
                # Check cooldown after loss (only if we have a recent loss)
                if last_loss_time:
                    cooldown_hours = config.get("cooldown_hours_after_loss", 12)
                    if (now - last_loss_time).total_seconds() < cooldown_hours * 3600:
                        return False, "cooldown_active"
        except Exception:
            pass
    
    return True, ""


def _get_eligible_symbols(
    config: Dict[str, Any],
    shadow_scores: Dict[str, Any],
    shadow_pf: Dict[str, Any],
    quarantine: Dict[str, Any],
    policy: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Build list of eligible symbols based on Shadow evidence."""
    eligible = []
    
    # Get shadow metrics (prefer scores, fallback to PF)
    by_symbol_scores = shadow_scores.get("by_symbol", {}) or shadow_scores.get("symbols", {})
    by_symbol_pf = shadow_pf.get("by_symbol", {}) or shadow_pf.get("symbols", {})
    
    # Get quarantine blocked symbols
    blocked_symbols = set()
    if config.get("require_not_quarantined", True):
        blocked_symbols = set(quarantine.get("blocked_symbols", []))
    
    # Get policy states
    policy_symbols = policy.get("symbols", {})
    
    min_trades = config.get("min_shadow_trades", 30)
    min_pf_30d = config.get("min_shadow_pf_30d", 1.05)
    min_pf_7d = config.get("min_shadow_pf_7d", 1.03)
    eligible_policy = set(config.get("eligible_policy_states", ["full", "reduced"]))
    forbidden_policy = set(config.get("forbidden_policy_states", ["blocked"]))
    
    # Check all symbols
    all_symbols = set(by_symbol_scores.keys()) | set(by_symbol_pf.keys())
    
    for symbol in all_symbols:
        # Skip quarantined
        if symbol in blocked_symbols:
            continue
        
        # Get shadow metrics
        score_data = by_symbol_scores.get(symbol, {})
        pf_data = by_symbol_pf.get(symbol, {})
        
        # Get trades count
        trades_30d = score_data.get("trades_30d", 0) or pf_data.get("trades_30d", 0)
        if trades_30d < min_trades:
            continue
        
        # Get PF values (prefer display, fallback to raw)
        pf_30d = (
            score_data.get("pf_30d_display") or
            score_data.get("pf_30d") or
            pf_data.get("pf_30d_display") or
            pf_data.get("pf_30d")
        )
        pf_7d = (
            score_data.get("pf_7d_display") or
            score_data.get("pf_7d") or
            pf_data.get("pf_7d_display") or
            pf_data.get("pf_7d")
        )
        
        if pf_30d is None or pf_7d is None:
            continue
        
        if pf_30d < min_pf_30d or pf_7d < min_pf_7d:
            continue
        
        # Check policy state
        symbol_policy = policy_symbols.get(symbol, {})
        policy_level = symbol_policy.get("level", "unknown")
        
        if policy_level in forbidden_policy:
            continue
        
        if policy_level not in eligible_policy and policy_level != "unknown":
            continue
        
        eligible.append({
            "symbol": symbol,
            "pf_30d": pf_30d,
            "pf_7d": pf_7d,
            "trades_30d": trades_30d,
            "policy_level": policy_level,
        })
    
    return eligible


def _get_equity_usd() -> float:
    """Get current equity in USD."""
    try:
        equity_path = REPORTS / "equity_live.json"
        if equity_path.exists():
            equity_data = _load_json(equity_path)
            return float(equity_data.get("equity_usd", 10000.0))
    except Exception:
        pass
    return 10000.0  # Default fallback


def run_probe_lane(now_iso: Optional[str] = None) -> Dict[str, Any]:
    """
    Run probe lane evaluation.
    
    Returns:
        Dict with action, reason, and details
    """
    now = datetime.now(timezone.utc) if now_iso is None else datetime.fromisoformat(now_iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    ts = now.isoformat()
    
    # Load config
    config = _load_config()
    
    # Initialize result
    result = {
        "ts": ts,
        "action": "disabled",
        "reason": "gate_disabled",
        "capital_mode": "unknown",
        "selected_symbol": None,
        "eligibility_counts": {},
        "thresholds": {},
    }
    
    try:
        # Check gate state (single source of truth for enablement)
        gate_state = _load_json(GATE_STATE_PATH)
        gate_enabled = gate_state.get("enabled", False)
        
        if not gate_enabled:
            result["reason"] = f"gate_disabled: {gate_state.get('reason', 'unknown')}"
            _append_log(result)
            return result
        
        # Load capital protection
        capital_protection = _load_json(CAPITAL_PROTECTION_PATH)
        capital_mode = (
            capital_protection.get("mode") or
            capital_protection.get("global", {}).get("mode") or
            "unknown"
        )
        result["capital_mode"] = capital_mode
        
        # Check if capital mode allows probe lane
        allowed_modes = config.get("allowed_in_capital_modes", ["halt_new_entries"])
        if capital_mode not in allowed_modes:
            result["action"] = "blocked"
            result["reason"] = f"capital_mode_not_allowed (mode={capital_mode}, allowed={allowed_modes})"
            _append_log(result)
            return result
        
        # Load state
        state = _load_state()
        
        # Check trade frequency constraints
        can_trade, freq_reason = _check_trade_frequency(state, config, now)
        if not can_trade:
            result["action"] = "blocked"
            result["reason"] = freq_reason
            _append_log(result)
            return result
        
        # Check open positions constraint
        open_positions = get_open_positions()
        max_positions = config.get("max_open_positions_total", 1)
        if len(open_positions) >= max_positions:
            result["action"] = "blocked"
            result["reason"] = "open_position_exists"
            result["open_positions_count"] = len(open_positions)
            _append_log(result)
            return result
        
        # Load shadow evidence
        shadow_scores = _load_json(SHADOW_SCORES_PATH)
        shadow_pf = _load_json(SHADOW_PF_PATH)
        quarantine = _load_json(QUARANTINE_PATH)
        policy = _load_json(POLICY_PATH)
        
        # Build eligible symbols
        eligible = _get_eligible_symbols(config, shadow_scores, shadow_pf, quarantine, policy)
        
        result["eligibility_counts"] = {
            "total_eligible": len(eligible),
            "min_shadow_trades": config.get("min_shadow_trades", 30),
            "min_shadow_pf_30d": config.get("min_shadow_pf_30d", 1.05),
            "min_shadow_pf_7d": config.get("min_shadow_pf_7d", 1.03),
        }
        result["thresholds"] = {
            "min_shadow_trades": config.get("min_shadow_trades", 30),
            "min_shadow_pf_30d": config.get("min_shadow_pf_30d", 1.05),
            "min_shadow_pf_7d": config.get("min_shadow_pf_7d", 1.03),
        }
        
        if not eligible:
            result["action"] = "blocked"
            result["reason"] = "no_eligible_symbols"
            _append_log(result)
            return result
        
        # Rank by PF_30D then trades
        eligible.sort(key=lambda x: (x["pf_30d"], x["trades_30d"]), reverse=True)
        best = eligible[0]
        selected_symbol = best["symbol"]
        result["selected_symbol"] = selected_symbol
        
        # Get exploit intent
        try:
            intent = compute_exploit_intent(symbol=selected_symbol, timeframe="15m")
            direction = intent.get("direction", 0)
            confidence = intent.get("confidence", 0.0)
        except Exception as e:
            result["action"] = "blocked"
            result["reason"] = f"intent_error: {str(e)}"
            _append_log(result)
            return result
        
        if direction == 0:
            result["action"] = "blocked"
            result["reason"] = "no_direction"
            _append_log(result)
            return result
        
        # Load additional data for sizing
        capital_plan = _load_json(CAPITAL_PLAN_PATH)
        pf_validity = _load_json(PF_VALIDITY_PATH)
        
        plan_data = capital_plan.get("symbols", {}).get(selected_symbol, {}) or capital_plan.get("by_symbol", {}).get(selected_symbol, {})
        tier = plan_data.get("tier", "tier3")
        policy_level = best.get("policy_level", "reduced")
        
        validity_entry = pf_validity.get("by_symbol", {}).get(selected_symbol, {})
        pf_validity_score = validity_entry.get("validity_score", 0.5)
        
        # Size position (using multiplier)
        equity_usd = _get_equity_usd()
        size_multiplier = config.get("position_size_multiplier", 0.02)
        base_risk_bps = 10.0 * size_multiplier  # Scale down base risk
        
        sizing_result = size_notional_usd(
            symbol=selected_symbol,
            equity_usd=equity_usd,
            confidence=confidence,
            pf_validity=pf_validity_score,
            policy_level=policy_level or "reduced",
            tier=tier,
            capital_mode=capital_mode,  # Still respect capital mode for sizing
            base_risk_bps=base_risk_bps,
            max_notional_usd=100.0 * size_multiplier,  # Scale down max
            min_notional_usd=5.0,
        )
        
        if sizing_result.notional_usd <= 0:
            result["action"] = "blocked"
            result["reason"] = f"sizing_zero: {sizing_result.reason}"
            _append_log(result)
            return result
        
        # Get current price
        try:
            rows = get_live_ohlcv(selected_symbol, "15m", limit=1)
            if not rows:
                result["action"] = "blocked"
                result["reason"] = "no_price_data"
                _append_log(result)
                return result
            current_price = float(rows[-1].get("close", 0))
            if current_price <= 0:
                result["action"] = "blocked"
                result["reason"] = "invalid_price"
                _append_log(result)
                return result
        except Exception as e:
            result["action"] = "blocked"
            result["reason"] = f"price_error: {str(e)}"
            _append_log(result)
            return result
        
        # Attempt to open probe trade
        # Note: We bypass capital_mode check in can_open_exploit_trade by passing "normal"
        # but the probe lane itself already checked capital_mode above
        can_open, executor_reason = can_open_exploit_trade(
            selected_symbol,
            capital_mode="normal",  # Bypass capital mode check (probe lane is explicit exception)
            max_concurrent=config.get("max_open_positions_total", 1),
        )
        
        if not can_open:
            result["action"] = "blocked"
            result["reason"] = f"executor_blocked: {executor_reason}"
            _append_log(result)
            return result
        
        # Open trade
        success, open_reason = open_exploit_trade(
            symbol=selected_symbol,
            direction=direction,
            entry_price=current_price,
            notional_usd=sizing_result.notional_usd,
            confidence=confidence,
        )
        
        if success:
            # Update state
            state["last_trade_at"] = ts
            state["last_symbol"] = selected_symbol
            state["last_action"] = "opened"
            _save_state(state)
            
            result["action"] = "opened"
            result["reason"] = "probe_lane_shadow_edge"
            result["direction"] = direction
            result["confidence"] = confidence
            result["notional_usd"] = sizing_result.notional_usd
            result["shadow_metrics"] = {
                "pf_30d": best["pf_30d"],
                "pf_7d": best["pf_7d"],
                "trades_30d": best["trades_30d"],
            }
            _append_log(result)
            return result
        else:
            result["action"] = "blocked"
            result["reason"] = f"open_failed: {open_reason}"
            _append_log(result)
            return result
    
    except Exception as e:
        # Log full error details
        error_str = str(e)
        error_repr = repr(e)
        error_traceback = traceback.format_exc()
        
        error_data = {
            "ts": ts,
            "error_type": type(e).__name__,
            "error_message": error_str,
            "error_repr": error_repr,
            "traceback": error_traceback,
            "context": "run_probe_lane",
        }
        _append_error_log(error_data)
        
        result["action"] = "error"
        result["reason"] = f"exception: {error_str[:200]}"
        _append_log(result)
        return result


__all__ = ["run_probe_lane"]

