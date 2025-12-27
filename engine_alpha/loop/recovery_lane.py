"""
Recovery Lane (Phase 5H)
------------------------

Micro-trading lane that can open tiny PAPER trades during halt_new_entries
only when Recovery Ramp explicitly allows it.

Safety:
- PAPER-only (hard guard)
- Restrictive-only (never enables exploit/probe)
- Only runs when recovery_ramp.allow_recovery_trading == true
- Max 1 position total
- Tiny sizing (risk_mult_cap = 0.25)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from engine_alpha.core.paths import REPORTS
from engine_alpha.data.live_prices import get_live_ohlcv
from engine_alpha.loop.execute_trade import open_if_allowed

# Paths
RECOVERY_RAMP_PATH = REPORTS / "risk" / "recovery_ramp.json"
LOG_PATH = REPORTS / "loop" / "recovery_lane_log.jsonl"
STATE_PATH = REPORTS / "loop" / "recovery_lane_state.json"

# Constants
MAX_POSITIONS = 1
RISK_MULT_CAP = 0.25
MIN_CONFIDENCE = 0.55

IS_PAPER_MODE = os.getenv("MODE", "PAPER").upper() == "PAPER"


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


def _append_log(entry: Dict[str, Any]) -> None:
    """Append entry to log file."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _check_open_positions() -> int:
    """Check how many recovery positions are open."""
    # Check state file
    state = _load_json(STATE_PATH)
    open_positions = state.get("open_positions", {})
    
    # Count non-zero positions
    count = 0
    for symbol, pos_data in open_positions.items():
        if pos_data.get("direction", 0) != 0:
            count += 1
    
    return count


def _get_signal(symbol: str) -> tuple[int, float]:
    """Get trading signal for symbol.
    
    Returns:
        (direction, confidence)
    """
    try:
        # Try exploit intent first (shared pipeline)
        from engine_alpha.loop.exploit_intent import compute_exploit_intent
        intent = compute_exploit_intent(symbol=symbol, timeframe="15m")
        direction = intent.get("direction", 0)
        confidence = intent.get("confidence", 0.0)
        
        if direction != 0 and confidence >= MIN_CONFIDENCE:
            return direction, confidence
    except Exception:
        pass
    
    # Fallback: try core signal pipeline
    try:
        from engine_alpha.signals.signal_processor import get_signal_vector
        from engine_alpha.core.confidence_engine import decide
        
        signal_result = get_signal_vector(symbol=symbol)
        decision = decide(signal_result["signal_vector"], signal_result["raw_registry"])
        final = decision.get("final", {})
        direction = final.get("dir", 0)
        confidence = final.get("conf", 0.0)
        
        if direction != 0 and confidence >= MIN_CONFIDENCE:
            return direction, confidence
    except Exception:
        pass
    
    return 0, 0.0


def run_recovery_lane(now_iso: Optional[str] = None) -> Dict[str, Any]:
    """
    Run recovery lane evaluation.
    
    Returns:
        Dict with action, reason, symbol, etc.
    """
    now = datetime.now(timezone.utc) if now_iso is None else datetime.fromisoformat(now_iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    
    result = {
        "ts": now.isoformat(),
        "action": "blocked",
        "reason": "",
        "symbol": None,
        "direction": None,
        "confidence": None,
        "notional_usd": None,
    }
    
    # Hard guard: PAPER-only
    if not IS_PAPER_MODE:
        result["reason"] = "not_paper_mode"
        _append_log(result)
        return result
    
    # Check recovery ramp state
    recovery_ramp = _load_json(RECOVERY_RAMP_PATH)
    
    if not recovery_ramp:
        result["reason"] = "recovery_ramp_state_missing"
        _append_log(result)
        return result
    
    # Check if recovery trading is allowed
    allowances = recovery_ramp.get("allowances", {})
    allow_recovery_trading = allowances.get("allow_recovery_trading", False)
    
    if not allow_recovery_trading:
        recovery_mode = recovery_ramp.get("recovery_mode", "OFF")
        reason = recovery_ramp.get("reason", "unknown")
        result["reason"] = f"recovery_ramp_disallowed (mode={recovery_mode}, reason={reason})"
        _append_log(result)
        return result
    
    # Check position limit
    open_count = _check_open_positions()
    if open_count >= MAX_POSITIONS:
        result["reason"] = f"max_positions_reached (count={open_count})"
        _append_log(result)
        return result
    
    # Get allowed symbols
    allowed_symbols = allowances.get("allowed_symbols", [])
    
    if not allowed_symbols:
        result["reason"] = "no_allowed_symbols"
        _append_log(result)
        return result
    
    # Try each allowed symbol (best first)
    for symbol in allowed_symbols:
        # Check if already open
        state = _load_json(STATE_PATH)
        open_positions = state.get("open_positions", {})
        if symbol in open_positions:
            pos_data = open_positions[symbol]
            if pos_data.get("direction", 0) != 0:
                continue  # Skip if already open
        
        # Get signal
        direction, confidence = _get_signal(symbol)
        
        if direction == 0 or confidence < MIN_CONFIDENCE:
            continue  # Skip if no signal
        
        # Get current price
        try:
            rows = get_live_ohlcv(symbol, "15m", limit=1)
            if not rows:
                continue
            
            current_price = float(rows[-1].get("close", 0))
            if current_price <= 0:
                continue
        except Exception:
            continue
        
        # Attempt to open trade (using existing execute_trade path)
        try:
            success = open_if_allowed(
                final_dir=direction,
                final_conf=confidence,
                entry_min_conf=MIN_CONFIDENCE,
                risk_mult=RISK_MULT_CAP,  # Use capped risk multiplier
                symbol=symbol,
                timeframe="15m",
                exploration_pass=False,
                strategy="recovery",  # Tag as recovery trade
            )
            
            if success:
                # Update state
                state = _load_json(STATE_PATH)
                if "open_positions" not in state:
                    state["open_positions"] = {}
                
                state["open_positions"][symbol] = {
                    "direction": direction,
                    "entry_price": current_price,
                    "entry_ts": now.isoformat(),
                    "confidence": confidence,
                    "trade_kind": "recovery",
                }
                _save_json(STATE_PATH, state)
                
                # Compute notional (approximate)
                notional_usd = min(10.0, 50.0 * RISK_MULT_CAP)  # Tiny sizing
                
                result["action"] = "opened"
                result["reason"] = "recovery_trade_opened"
                result["symbol"] = symbol
                result["direction"] = direction
                result["confidence"] = confidence
                result["notional_usd"] = notional_usd
                
                _append_log(result)
                return result
            else:
                result["reason"] = f"open_if_allowed_blocked (symbol={symbol})"
        except Exception as e:
            result["reason"] = f"execution_error: {str(e)}"
            continue
    
    # No trade opened
    result["reason"] = "no_valid_signals"
    _append_log(result)
    return result


__all__ = ["run_recovery_lane"]

