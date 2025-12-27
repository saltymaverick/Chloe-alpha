"""
Micro Core Ramp (Phase 5H.4)
----------------------------

Micro-core trading lane that runs during halt_new_entries when recovery assist is enabled.
Allows limited PAPER trades with strict caps to test recovery without changing capital_mode.

Safety:
- PAPER-only (hard guard)
- Max 1 position total
- Max $10 notional cap
- Max risk_mult 0.25
- Only trades symbols allowed by recovery_ramp_v2 AND exploration_policy allow==Y
- Never enables exploit/probe/promotion gates
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

from engine_alpha.core.paths import REPORTS
from engine_alpha.data.live_prices import get_live_ohlcv
from engine_alpha.loop.execute_trade import open_if_allowed
from engine_alpha.loop.recovery_intent import compute_recovery_intent

# Paths
CAPITAL_PROTECTION_PATH = REPORTS / "risk" / "capital_protection.json"
RECOVERY_ASSIST_PATH = REPORTS / "risk" / "recovery_assist.json"
RECOVERY_RAMP_V2_PATH = REPORTS / "risk" / "recovery_ramp_v2.json"
EXPLORATION_POLICY_PATHS = [
    REPORTS / "risk" / "exploration_policy_v3.json",
    REPORTS / "risk" / "exploration_policy_v3_state.json",
    REPORTS / "research" / "exploration_policy_v3.json",
    REPORTS / "risk" / "exploration_policy.json",
]
LOG_PATH = REPORTS / "loop" / "micro_core_ramp_log.jsonl"
STATE_PATH = REPORTS / "loop" / "micro_core_ramp_state.json"

# Constants
MAX_POSITIONS = 1
MAX_NOTIONAL_USD = 10.0
MAX_RISK_MULT = 0.25
MIN_CONFIDENCE = 0.55
TP_PCT = 0.20  # Take profit: +0.20%
SL_PCT = 0.15  # Stop loss: -0.15%
MAX_HOLD_MINUTES = 45

IS_PAPER_MODE = os.getenv("MODE", "PAPER").upper() == "PAPER"


def _get_current_price(symbol: str, timeframe: str = "15m") -> Optional[float]:
    """Get current price for symbol (robust helper)."""
    try:
        intent_dict = compute_recovery_intent(symbol, timeframe=timeframe)
        current_price = intent_dict.get("current_price")
        
        if current_price is not None and current_price > 0:
            return current_price
        
        # Fallback to OHLCV
        rows, _ = get_live_ohlcv(symbol, timeframe, limit=1)
        if rows and len(rows) > 0:
            price = float(rows[-1].get("close", 0))
            if price > 0:
                return price
    except Exception:
        pass
    
    return None


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
    """Save JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _append_log(entry: Dict[str, Any]) -> None:
    """Append entry to log file."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _load_exploration_allowset() -> tuple[set[str], Optional[str]]:
    """
    Load exploration policy allowed symbols with fallback paths.
    
    Returns:
        Tuple of (allowed_symbols_set, file_used_path) or (empty_set, None) if no file found.
    """
    for policy_path in EXPLORATION_POLICY_PATHS:
        if not policy_path.exists():
            continue
        
        try:
            policy_data = _load_json(policy_path)
            if not policy_data:
                continue
            
            # Handle different schema formats
            policy_symbols = policy_data.get("symbols", {})
            if not policy_symbols:
                # Try alternative schema: {"blocked": [...], "allowed": [...]}
                blocked = policy_data.get("blocked", [])
                allowed_list = policy_data.get("allowed", [])
                if allowed_list:
                    return set(allowed_list), str(policy_path)
                # If we have blocked list, assume all others are allowed (not ideal, but fallback)
                continue
            
            # Extract allowed symbols from symbols dict
            policy_allowed = set()
            for symbol, data in policy_symbols.items():
                if isinstance(data, dict):
                    # Check for allow_new_entries or allow field
                    if data.get("allow_new_entries", False) is True or data.get("allow", False) is True:
                        policy_allowed.add(symbol)
                elif isinstance(data, bool) and data:
                    policy_allowed.add(symbol)
            
            if policy_allowed:
                return policy_allowed, str(policy_path)
        except Exception:
            continue
    
    # No file found or all empty - return empty set with None path
    return set(), None


def _get_allowed_symbols() -> tuple[list[str], dict[str, Any]]:
    """
    Get allowed symbols: intersection of recovery_ramp_v2 allowed_symbols
    and exploration_policy symbols with allow_new_entries=True.
    
    Returns:
        Tuple of (allowed_symbols_list, diagnostics_dict)
    """
    diagnostics: Dict[str, Any] = {
        "recovery_ramp_v2_count": 0,
        "exploration_policy_count": 0,
        "intersection_count": 0,
        "recovery_ramp_v2_symbols": [],
        "exploration_policy_symbols": [],
        "policy_file_used": None,
        "fallback_reason": None,
    }
    
    recovery_ramp_v2 = _load_json(RECOVERY_RAMP_V2_PATH)
    
    # Get recovery_ramp_v2 allowed symbols
    ramp_allowed = recovery_ramp_v2.get("decision", {}).get("allowed_symbols", [])
    diagnostics["recovery_ramp_v2_count"] = len(ramp_allowed)
    diagnostics["recovery_ramp_v2_symbols"] = ramp_allowed[:10]  # Truncate to avoid spam
    
    if not ramp_allowed:
        diagnostics["fallback_reason"] = "recovery_ramp_v2_empty"
        return [], diagnostics
    
    # Load exploration policy allowed set
    policy_allowed_set, policy_file_used = _load_exploration_allowset()
    diagnostics["exploration_policy_count"] = len(policy_allowed_set)
    diagnostics["exploration_policy_symbols"] = sorted(list(policy_allowed_set))[:10]  # Truncate
    diagnostics["policy_file_used"] = policy_file_used
    
    if policy_file_used is None:
        # No exploration policy file found - fallback behavior
        # PAPER-only: allow all symbols from recovery_ramp_v2
        if IS_PAPER_MODE:
            diagnostics["fallback_reason"] = "exploration_policy_missing_fallback_allow_ramp_symbols"
            _log_entry({
                "ts": datetime.now(timezone.utc).isoformat(),
                "action": "warning",
                "reason": "exploration_policy_missing_fallback_allow_ramp_symbols",
                "ramp_allowed": ramp_allowed,
            })
            return ramp_allowed, diagnostics
        else:
            # LIVE mode: be strict, return empty
            diagnostics["fallback_reason"] = "exploration_policy_missing_live_mode_strict"
            return [], diagnostics
    
    # Intersection
    allowed = [s for s in ramp_allowed if s in policy_allowed_set]
    diagnostics["intersection_count"] = len(allowed)
    
    return allowed, diagnostics


def run_micro_core_ramp() -> Dict[str, Any]:
    """
    Run one evaluation tick of micro core ramp.
    
    Returns:
        Dict with action, reason, symbol, direction, etc.
    """
    now = datetime.now(timezone.utc)
    
    result = {
        "ts": now.isoformat(),
        "action": "blocked",
        "reason": "",
    }
    
    # Hard guard: PAPER-only
    if not IS_PAPER_MODE:
        result["reason"] = "not_paper_mode"
        _append_log(result)
        return result
    
    # Check capital_mode
    capital_protection = _load_json(CAPITAL_PROTECTION_PATH)
    global_mode = capital_protection.get("global", {})
    capital_mode = global_mode.get("mode", "unknown")
    
    if capital_mode != "halt_new_entries":
        result["reason"] = f"capital_mode={capital_mode} (not halt_new_entries)"
        _append_log(result)
        return result
    
    # Check recovery assist
    recovery_assist = _load_json(RECOVERY_ASSIST_PATH)
    assist_enabled = recovery_assist.get("assist_enabled", False)
    
    if not assist_enabled:
        result["reason"] = "recovery_assist_disabled"
        _append_log(result)
        return result
    
    # Load state
    state = _load_json(STATE_PATH)
    open_positions = state.get("open_positions", {})
    
    # Phase 5H.4 Bug Fix: Check exit conditions FIRST, before max_positions check
    # This ensures positions are closed (timeout/TP/SL/etc) even when max_positions is reached
    for symbol in list(open_positions.keys()):
        position = open_positions[symbol]
        entry_price = position.get("entry_price", 0.0)
        entry_ts_str = position.get("entry_ts", "")
        direction = position.get("direction", 0)
        entry_confidence = position.get("confidence", 0.0)
        
        if not entry_price or not entry_ts_str:
            continue
        
        # Check exit conditions
        should_exit = False
        exit_reason = ""
        exit_price = None
        
        # Timeout check (doesn't require current_price, so check first)
        try:
            entry_time = datetime.fromisoformat(entry_ts_str.replace("Z", "+00:00"))
            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=timezone.utc)
            age_minutes = (now - entry_time).total_seconds() / 60.0
            if age_minutes >= MAX_HOLD_MINUTES:
                should_exit = True
                exit_reason = "timeout"
        except Exception:
            pass
        
        # Get current price (needed for TP/SL and exit_price)
        current_price = _get_current_price(symbol, "15m")
        
        # TP/SL check (requires current_price)
        if current_price is not None and current_price > 0:
            exit_price = current_price
            
            if direction == 1:  # Long
                pnl_pct = (current_price - entry_price) / entry_price * 100.0
                if pnl_pct >= TP_PCT:
                    should_exit = True
                    exit_reason = "tp"
                elif pnl_pct <= -SL_PCT:
                    should_exit = True
                    exit_reason = "sl"
            else:  # Short
                pnl_pct = (entry_price - current_price) / entry_price * 100.0
                if pnl_pct >= TP_PCT:
                    should_exit = True
                    exit_reason = "tp"
                elif pnl_pct <= -SL_PCT:
                    should_exit = True
                    exit_reason = "sl"
        
        # Confidence drop check (requires intent_dict)
        try:
            intent_dict = compute_recovery_intent(symbol, timeframe="15m")
            current_confidence = intent_dict.get("confidence", entry_confidence)
            if current_confidence < 0.42:
                should_exit = True
                exit_reason = "confidence_drop"
            
            # Direction flip check
            current_direction = intent_dict.get("direction", 0)
            if current_direction != 0 and current_direction != direction:
                should_exit = True
                exit_reason = "direction_flip"
        except Exception:
            pass
        
        if should_exit:
            # Get exit_price if not already set (fallback to entry_price for timeout if price unavailable)
            if exit_price is None:
                exit_price = _get_current_price(symbol, "15m")
                if exit_price is None or exit_price <= 0:
                    exit_price = entry_price  # Fallback to entry_price if current_price unavailable
            
            # Compute PnL
            if direction == 1:  # Long
                pnl_pct = (exit_price - entry_price) / entry_price * 100.0
            else:  # Short
                pnl_pct = (entry_price - exit_price) / entry_price * 100.0
            
            notional_usd = position.get("notional_usd", MAX_NOTIONAL_USD)
            pnl_usd = notional_usd * (pnl_pct / 100.0) if notional_usd > 0 else 0.0
            
            # Log exit
            exit_result = {
                "ts": now.isoformat(),
                "action": "close",
                "exit_reason": exit_reason,
                "symbol": symbol,
                "direction": direction,
                "entry_px": entry_price,
                "exit_px": exit_price,
                "pnl_pct": pnl_pct,
                "pnl_usd": pnl_usd,
            }
            _append_log(exit_result)
            
            # Remove position
            open_positions.pop(symbol, None)
            state["open_positions"] = open_positions
            state["generated_at"] = now.isoformat()
            _save_json(STATE_PATH, state)
            
            result.update(exit_result)
            return result
    
    # After exit evaluation, reload state in case positions were closed
    state = _load_json(STATE_PATH)
    open_positions = state.get("open_positions", {})
    
    # Check max positions (after exit evaluation)
    if len(open_positions) >= MAX_POSITIONS:
        result["reason"] = f"max_positions_reached (count={len(open_positions)})"
        _append_log(result)
        return result
    
    # Get allowed symbols with diagnostics
    allowed_symbols, diagnostics = _get_allowed_symbols()
    
    if not allowed_symbols:
        # Build detailed reason with diagnostics
        ramp_count = diagnostics.get("recovery_ramp_v2_count", 0)
        policy_count = diagnostics.get("exploration_policy_count", 0)
        fallback_reason = diagnostics.get("fallback_reason")
        
        if fallback_reason:
            result["reason"] = f"no_allowed_symbols ({fallback_reason}, recovery_ramp_v2={ramp_count}, exploration_policy={policy_count})"
        else:
            result["reason"] = f"no_allowed_symbols (recovery_ramp_v2={ramp_count}, exploration_policy={policy_count}, intersection=0)"
        
        # Include diagnostics in result for debugging
        result["diagnostics"] = diagnostics
        _append_log(result)
        return result
    
    # Try to open new position
    for symbol in allowed_symbols:
        if symbol in open_positions:
            continue
        
        # Get signal
        intent_dict = compute_recovery_intent(symbol, timeframe="15m")
        direction = intent_dict.get("direction", 0)
        confidence = intent_dict.get("confidence", 0.0)
        
        if not intent_dict.get("entry_ok", False) or confidence < MIN_CONFIDENCE:
            continue
        
        # Get current price
        current_price = _get_current_price(symbol, "15m")
        if current_price is None or current_price <= 0:
            continue
        
        # Attempt to open trade
        try:
            success = open_if_allowed(
                final_dir=direction,
                final_conf=confidence,
                entry_min_conf=MIN_CONFIDENCE,
                risk_mult=MAX_RISK_MULT,
                symbol=symbol,
                timeframe="15m",
                exploration_pass=False,
                strategy="micro_core_ramp",
            )
            
            if success:
                # Update state
                if "open_positions" not in state:
                    state["open_positions"] = {}
                
                state["open_positions"][symbol] = {
                    "direction": direction,
                    "entry_price": current_price,
                    "entry_ts": now.isoformat(),
                    "confidence": confidence,
                    "trade_kind": "micro_core_ramp",
                    "notional_usd": MAX_NOTIONAL_USD,
                }
                state["generated_at"] = now.isoformat()
                _save_json(STATE_PATH, state)
                
                # Log open
                open_result = {
                    "ts": now.isoformat(),
                    "action": "opened",
                    "reason": "signal_ready",
                    "symbol": symbol,
                    "direction": direction,
                    "confidence": confidence,
                    "entry_px": current_price,
                    "notional_usd": MAX_NOTIONAL_USD,
                }
                _append_log(open_result)
                
                result.update(open_result)
                return result
        
        except Exception as e:
            result["reason"] = f"open_failed: {str(e)}"
            continue
    
    # No valid signals
    result["reason"] = "no_valid_signals"
    _append_log(result)
    return result


def main() -> int:
    """Main entry point."""
    result = run_micro_core_ramp()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

