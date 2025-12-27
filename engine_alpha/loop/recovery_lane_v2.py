"""
Recovery Lane V2 (Phase 5H.2)
------------------------------

Micro recovery executor that reads recovery_ramp_v2.json and places
PAPER trades for eligible symbols under strict caps.

Safety:
- PAPER-only (hard guard)
- Max 1 position total
- Max $10 notional cap
- Only trades symbols allowed by recovery_ramp_v2
- Never bypasses quarantine or policy blocks
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List

from engine_alpha.core.paths import REPORTS
from engine_alpha.data.live_prices import get_live_ohlcv
from engine_alpha.loop.execute_trade import open_if_allowed
from engine_alpha.loop.recovery_intent import compute_recovery_intent
from engine_alpha.loop.recovery_lane_v2_trades import (
    log_open,
    log_close,
    generate_trade_id,
)
from engine_alpha.risk.symbol_state import load_symbol_states

# Paths
RECOVERY_RAMP_V2_PATH = REPORTS / "risk" / "recovery_ramp_v2.json"
RECOVERY_RAMP_V1_PATH = REPORTS / "risk" / "recovery_ramp.json"
LOG_PATH = REPORTS / "loop" / "recovery_lane_v2_log.jsonl"
STATE_PATH = REPORTS / "loop" / "recovery_lane_v2_state.json"
TRADES_PATH = REPORTS / "trades.jsonl"

# Constants (lane cap defaults; per-symbol caps may further reduce)
MAX_POSITIONS = 1
MAX_NOTIONAL_USD = 10.0
# Phase 5H.2 Conservative Tightening: Raised entry thresholds
ENTRY_CONF_MIN = 0.65  # Minimum confidence for entry (normal regime)
ENTRY_CONF_MIN_CHOP = 0.70  # Minimum confidence for entry in chop regime
# Softened threshold for chop when stabilizing (still below clean_closes gate)
ENTRY_CONF_MIN_CHOP_SOFT = 0.65
TP_PCT = 0.20  # Take profit: +0.20%
SL_PCT = 0.15  # Stop loss: -0.15%
MAX_HOLD_MINUTES = 45
# Halt-mode probe tightening: close faster (more closes/day) without increasing exposure.
HALT_MAX_HOLD_SECONDS = 1200
COOLDOWN_SECONDS = 1800
NO_SIGNAL_COOLDOWN_SECONDS = 300  # 5 minutes for no_valid_signals
POST_CLOSE_COOLDOWN_SECONDS = 600  # 10 minutes after any close (Phase 5H.2 rotation)
TP_COOLDOWN_SECONDS = 900  # 15 minutes after successful TP (Phase 5H.2 Conservative Tightening)
MAX_CONSECUTIVE_SAME_SYMBOL = 2  # Block 3rd consecutive open on same symbol (Phase 5H.2 rotation)
DIVERSITY_CONFIDENCE_THRESHOLD = 0.05  # Prefer diversity if conf within this (Phase 5H.2 rotation)
MIN_SECONDS_BETWEEN_OPENS = 12 * 60  # 12 minutes global rate limit (Phase 5H.2 Conservative Tightening)

IS_PAPER_MODE = os.getenv("MODE", "PAPER").upper() == "PAPER"


def _get_current_price(symbol: str, timeframe: str = "15m") -> Optional[float]:
    """Get current price for symbol (robust helper)."""
    try:
        # Try recovery intent first
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


def _compute_recovery_pf_7d(now: Optional[datetime] = None) -> tuple[Optional[float], int]:
    """
    Compute PF over recovery_v2 closes in the last 7 days.
    PF = gross_profit / gross_loss (loss as positive). If loss==0 and profit>0 -> inf.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)
    gross_profit = 0.0
    gross_loss = 0.0
    n = 0
    if not TRADES_PATH.exists():
        return None, 0
    try:
        with TRADES_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    evt = json.loads(line)
                except Exception:
                    continue
                if (evt.get("type") or "").lower() != "close":
                    continue
                tk = (evt.get("trade_kind") or evt.get("strategy") or "").lower()
                if tk != "recovery_v2":
                    continue
                ts = evt.get("ts") or evt.get("timestamp")
                if not ts:
                    continue
                try:
                    ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
                except Exception:
                    continue
                if ts_dt < cutoff:
                    continue
                pct = evt.get("pct")
                if pct is None:
                    pct = evt.get("pnl_pct")
                try:
                    pct_val = float(pct)
                except Exception:
                    pct_val = 0.0
                n += 1
                if pct_val >= 0:
                    gross_profit += pct_val
                else:
                    gross_loss += abs(pct_val)
    except Exception:
        return None, 0

    if n == 0:
        return None, 0
    if gross_loss == 0:
        return (float("inf") if gross_profit > 0 else None), n
    return gross_profit / gross_loss, n


def _save_json(path: Path, data: Dict[str, Any]) -> None:
    """Safely save JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def _should_exit_only(
    allow_recovery_trading_v1: bool,
    allow_recovery_lane_v2: bool,
    needed_ok_v1: int,
    ok_ticks_v1: int,
) -> tuple[bool, str]:
    """
    Decide whether recovery lane must be exit-only.
    NOTE: recovery lane is now per-symbol policy driven; ramp v1 is advisory only.
    """
    return False, ""


def _append_log(entry: Dict[str, Any]) -> None:
    """Append entry to log file."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _check_open_positions() -> int:
    """Check how many recovery v2 positions are open."""
    state = _load_json(STATE_PATH)
    open_positions = state.get("open_positions", {})
    
    count = 0
    for symbol, pos_data in open_positions.items():
        if pos_data.get("direction", 0) != 0:
            count += 1
    
    return count


def _check_cooldown(symbol: str, state: Dict[str, Any]) -> bool:
    """
    Check if symbol is in cooldown (from last_trades, cooldowns map, post_close_cooldowns, or tp_cooldowns).
    
    Phase 5H.2 Conservative Tightening: Added TP cooldown check.
    Phase 5H.2 Cleanup: Expired cooldowns are cleaned up (not returned as True).
    """
    now = datetime.now(timezone.utc)
    needs_save = False
    
    # Check cooldowns map first (for no_valid_signals cooldowns)
    cooldowns = state.get("cooldowns", {})
    cooldown_ts = cooldowns.get(symbol)
    
    if cooldown_ts:
        try:
            cooldown_time = datetime.fromisoformat(cooldown_ts.replace("Z", "+00:00")).astimezone(timezone.utc)
            elapsed = (now - cooldown_time).total_seconds()
            if elapsed < NO_SIGNAL_COOLDOWN_SECONDS:
                return True
            else:
                # Expired - clean up
                del cooldowns[symbol]
                state["cooldowns"] = cooldowns
                needs_save = True
        except Exception:
            pass
    
    # Phase 5H.2 Conservative Tightening: Check TP cooldowns FIRST (15 minutes after successful TP)
    # TP cooldown takes precedence over generic close cooldown
    tp_cooldowns = state.get("tp_cooldowns", {})
    tp_cooldown_ts = tp_cooldowns.get(symbol)
    
    if tp_cooldown_ts:
        try:
            cooldown_time = datetime.fromisoformat(tp_cooldown_ts.replace("Z", "+00:00")).astimezone(timezone.utc)
            elapsed = (now - cooldown_time).total_seconds()
            if elapsed < TP_COOLDOWN_SECONDS:
                return True  # Blocked by TP cooldown
            else:
                # Expired - clean up
                del tp_cooldowns[symbol]
                state["tp_cooldowns"] = tp_cooldowns
                needs_save = True
        except Exception:
            pass
    
    # Check post_close_cooldowns (Phase 5H.2: 10-minute cooldown after any close)
    post_close_cooldowns = state.get("post_close_cooldowns", {})
    post_close_ts = post_close_cooldowns.get(symbol)
    
    if post_close_ts:
        try:
            cooldown_time = datetime.fromisoformat(post_close_ts.replace("Z", "+00:00")).astimezone(timezone.utc)
            elapsed = (now - cooldown_time).total_seconds()
            if elapsed < POST_CLOSE_COOLDOWN_SECONDS:
                return True
            else:
                # Expired - clean up
                del post_close_cooldowns[symbol]
                state["post_close_cooldowns"] = post_close_cooldowns
                needs_save = True
        except Exception:
            pass
    
    # Check last_trades (for post-trade cooldowns - legacy)
    last_trades = state.get("last_trades", {})
    last_trade_ts = last_trades.get(symbol)
    
    if last_trade_ts:
        try:
            last_trade_time = datetime.fromisoformat(last_trade_ts.replace("Z", "+00:00")).astimezone(timezone.utc)
            elapsed = (now - last_trade_time).total_seconds()
            if elapsed < COOLDOWN_SECONDS:
                return True
            # Note: last_trades cleanup is handled elsewhere (legacy)
        except Exception:
            pass
    
    # Phase 5H.2 Cleanup: Save state if we cleaned up expired cooldowns
    if needs_save:
        _save_json(STATE_PATH, state)
    
    return False


def _get_last_open_from_trades(window_hours: int = 24) -> tuple[Optional[str], Optional[str]]:
    """
    Get last open timestamp and symbol from recovery_lane_v2_trades.jsonl (single source of truth).
    
    Phase 5H.2 Rotation Deadlock Fix: Returns (last_open_ts_iso, last_open_symbol) from most recent
    "action":"open" line within window. Falls back to None if not found.
    
    Returns: (last_open_ts_iso, last_open_symbol)
    """
    from engine_alpha.loop.recovery_lane_v2_trades import RECOVERY_TRADES_PATH
    
    if not RECOVERY_TRADES_PATH.exists():
        return None, None
    
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    last_open_ts = None
    last_open_symbol = None
    # Also track latest open even if outside window (fallback)
    latest_open_ts = None
    latest_open_symbol = None
    
    try:
        with RECOVERY_TRADES_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    # Only recovery_v2 opens
                    if trade.get("lane") != "recovery_v2" or trade.get("action") != "open":
                        continue
                    
                    ts_str = trade.get("ts", "")
                    if ts_str:
                        try:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                            
                            # Track latest open regardless of window (fallback)
                            if latest_open_ts is None or ts_str > latest_open_ts:
                                latest_open_ts = ts_str
                                latest_open_symbol = trade.get("symbol", "UNKNOWN")
                            
                            # Keep most recent within window
                            if ts >= cutoff:
                                if last_open_ts is None or ts_str > last_open_ts:
                                    last_open_ts = ts_str
                                    last_open_symbol = trade.get("symbol", "UNKNOWN")
                        except Exception:
                            continue
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    
    # Return windowed result if found, else fallback to latest in file
    if last_open_ts:
        return last_open_ts, last_open_symbol
    elif latest_open_ts:
        return latest_open_ts, latest_open_symbol
    else:
        return None, None


def _get_last_open_anytime_from_trades() -> tuple[Optional[str], Optional[str]]:
    """
    Get the most recent open timestamp and symbol from recovery_lane_v2_trades.jsonl (no time filtering).
    
    Phase 5H.2 Cleanup: Returns the absolute most recent "action":"open" entry in the file,
    regardless of when it occurred. Used for blocked diagnostics to ensure accurate last_open_ts.
    
    Returns: (last_open_ts_iso, last_open_symbol) or (None, None) if file missing/empty/no opens.
    """
    from engine_alpha.loop.recovery_lane_v2_trades import RECOVERY_TRADES_PATH
    
    if not RECOVERY_TRADES_PATH.exists():
        return None, None
    
    last_open_ts = None
    last_open_symbol = None
    
    try:
        # Read entire file and find most recent open (no time filtering)
        with RECOVERY_TRADES_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    # Only recovery_v2 opens
                    if trade.get("lane") != "recovery_v2" or trade.get("action") != "open":
                        continue
                    
                    ts_str = trade.get("ts", "")
                    if ts_str:
                        # Keep most recent (compare as strings for ISO format)
                        if last_open_ts is None or ts_str > last_open_ts:
                            last_open_ts = ts_str
                            last_open_symbol = trade.get("symbol", "UNKNOWN")
                except (json.JSONDecodeError, Exception):
                    continue
    except Exception:
        pass
    
    return last_open_ts, last_open_symbol


def _get_last_opens_from_trades() -> List[Dict[str, str]]:
    """
    Get last opens from recovery_lane_v2_trades.jsonl (last 24h).
    
    Phase 5H.4: Read directly from trades file for stronger enforcement.
    Returns list of {"ts": str, "symbol": str} for last opens.
    """
    from engine_alpha.loop.recovery_lane_v2_trades import RECOVERY_TRADES_PATH
    
    last_opens = []
    
    if not RECOVERY_TRADES_PATH.exists():
        return last_opens
    
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    
    try:
        with RECOVERY_TRADES_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    # Only recovery_v2 opens
                    if trade.get("lane") != "recovery_v2" or trade.get("action") != "open":
                        continue
                    
                    ts_str = trade.get("ts", "")
                    if ts_str:
                        try:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                            if ts >= cutoff:
                                last_opens.append({
                                    "ts": ts_str,
                                    "symbol": trade.get("symbol", "UNKNOWN"),
                                })
                        except Exception:
                            continue
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    
    # Return last 10 opens (most recent first)
    return last_opens[-10:]


def _check_global_rate_limit(state: Dict[str, Any]) -> tuple[bool, Optional[str], Optional[str]]:
    """
    Check if global rate limit is exceeded (min time between opens).
    
    Phase 5H.2 Conservative Tightening: Enforce 12-minute minimum between any opens.
    Phase 5H.2 Rotation Deadlock Fix: Use trades.jsonl as single source of truth.
    
    Returns: (is_blocked, last_open_ts_str, last_open_symbol)
    """
    # Phase 5H.2 Rotation Deadlock Fix: Single source of truth from trades.jsonl
    last_open_ts_str, last_open_symbol = _get_last_open_from_trades(window_hours=24)
    
    if not last_open_ts_str:
        # Fallback to state if trades log is empty
        last_opens = state.get("last_opens", [])
        if last_opens:
            last_open = last_opens[-1]
            last_open_ts_str = last_open.get("ts")
            last_open_symbol = last_open.get("symbol")
        else:
            return False, None, None
    
    try:
        last_open_time = datetime.fromisoformat(last_open_ts_str.replace("Z", "+00:00"))
        if last_open_time.tzinfo is None:
            last_open_time = last_open_time.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        elapsed = (now - last_open_time).total_seconds()
        
        if elapsed < MIN_SECONDS_BETWEEN_OPENS:
            return True, last_open_ts_str, last_open_symbol
    except Exception:
        pass
    
    return False, last_open_ts_str, last_open_symbol


# Phase 5H.2 Rotation Deadlock Fix: _check_rotation_limit DEPRECATED
# Rotation is now handled conditionally after candidate evaluation, not during symbol iteration.
# This function should never be called - it exists only for backward compatibility.
def _check_rotation_limit(symbol: str, state: Dict[str, Any], has_alternative_candidate: bool = False) -> bool:
    """
    DEPRECATED: This function should never be called.
    
    Phase 5H.2 Rotation Deadlock Fix: Rotation is now handled conditionally after candidate evaluation.
    This function always returns False - rotation logic is in the candidate selection code.
    """
    # Always return False - rotation is handled in the candidate selection logic (after valid_candidates is built)
    return False


def _get_symbol_close_counts_24h() -> Dict[str, int]:
    """Get close counts per symbol from recovery_lane_v2_trades.jsonl (last 24h)."""
    from engine_alpha.loop.recovery_lane_v2_trades import RECOVERY_TRADES_PATH
    
    symbol_counts: Dict[str, int] = {}
    
    if not RECOVERY_TRADES_PATH.exists():
        return symbol_counts
    
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    
    try:
        with RECOVERY_TRADES_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    if trade.get("action") == "close":
                        ts_str = trade.get("ts", "")
                        if ts_str:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                            if ts >= cutoff:
                                symbol = trade.get("symbol", "UNKNOWN")
                                symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
                except Exception:
                    continue
    except Exception:
        pass
    
    return symbol_counts


def _select_symbol_with_diversity(
    candidates: list[tuple[str, float, Dict[str, Any], float]],
    state: Dict[str, Any],
) -> Optional[tuple[str, float, Dict[str, Any], float]]:
    """
    Select symbol from candidates with diversity preference.
    
    Args:
        candidates: List of (symbol, confidence, intent_dict) tuples
        state: Current state dict
    
    Returns:
        Selected (symbol, confidence, intent_dict) or None
    """
    if not candidates:
        return None
    
    if len(candidates) == 1:
        return candidates[0]
    
    # Sort by confidence (descending)
    candidates_sorted = sorted(candidates, key=lambda x: -x[1])
    
    best_conf = candidates_sorted[0][1]
    best_candidates = [c for c in candidates_sorted if abs(c[1] - best_conf) <= DIVERSITY_CONFIDENCE_THRESHOLD]
    
    if len(best_candidates) == 1:
        return best_candidates[0]
    
    # Multiple candidates within threshold - prefer diversity
    close_counts = _get_symbol_close_counts_24h()
    
    # Sort by close count (ascending - prefer fewer closes)
    best_candidates_sorted = sorted(
        best_candidates,
        key=lambda x: close_counts.get(x[0], 0)
    )
    
    return best_candidates_sorted[0]


def _get_signal(symbol: str) -> tuple[int, float, Dict[str, Any]]:
    """Get trading signal for symbol using raw recovery intent.
    
    Returns:
        (direction, confidence, intent_dict)
    """
    try:
        intent = compute_recovery_intent(symbol=symbol, timeframe="15m")
        direction = intent.get("direction", 0)
        confidence = intent.get("confidence", 0.0)
        
        return direction, confidence, intent
    except Exception:
        return 0, 0.0, {}


def _maybe_exit_open_position(
    symbol: str,
    position: Dict[str, Any],
    now: datetime,
    current_price: Optional[float],
    capital_mode: Optional[str] = None,
) -> tuple[bool, Optional[Dict[str, Any]]]:
    """
    Evaluate exit conditions for an open position.
    
    Exit evaluation order:
    1. Timeout (no price needed)
    2. Confidence drop / direction flip (from signal eval, no price needed)
    3. TP/SL (requires price)
    
    Args:
        symbol: Trading symbol
        position: Position dict with entry_price, entry_ts, direction, etc.
        now: Current datetime
        current_price: Current price (None if unavailable)
    
    Returns:
        Tuple of (did_exit, exit_event_dict)
        exit_event_dict contains: exit_reason, exit_price, pnl_pct, pnl_usd, exit_px_source
    """
    direction = position.get("direction", 0)
    entry_price = position.get("entry_price", 0.0)
    entry_ts = position.get("entry_ts")
    confidence = position.get("confidence", 0.0)
    
    if direction == 0 or entry_price <= 0:
        return False, None
    
    exit_event: Dict[str, Any] = {}
    
    # 1) Timeout check FIRST (no price needed)
    if entry_ts:
        try:
            entry_time = datetime.fromisoformat(entry_ts.replace("Z", "+00:00")).astimezone(timezone.utc)
            elapsed_seconds = (now - entry_time).total_seconds()

            # Default max hold (normal mode): 45 minutes.
            max_hold_seconds = MAX_HOLD_MINUTES * 60
            # If position specifies a hold, prefer it.
            try:
                if position.get("max_hold_seconds") is not None:
                    max_hold_seconds = int(position.get("max_hold_seconds"))
            except Exception:
                pass

            # Clamp in halt_new_entries: enforce 20-minute max hold even for legacy positions.
            if (capital_mode or "") == "halt_new_entries":
                try:
                    max_hold_seconds = min(int(max_hold_seconds), int(HALT_MAX_HOLD_SECONDS))
                except Exception:
                    max_hold_seconds = HALT_MAX_HOLD_SECONDS

            if elapsed_seconds >= float(max_hold_seconds):
                # Timeout exit - use entry_price as fallback if no price
                exit_price = current_price if current_price is not None and current_price > 0 else entry_price
                exit_event = {
                    "exit_reason": "timeout",
                    "exit_price": exit_price,
                    "pnl_pct": 0.0 if current_price is None else None,  # Will compute if price available
                    "pnl_usd": 0.0 if current_price is None else None,  # Will compute if price available
                    "exit_px_source": "entry_fallback_no_price" if current_price is None else "current_price",
                }
                # Compute PnL if price is available
                if current_price is not None and current_price > 0:
                    if direction == 1:  # Long
                        exit_event["pnl_pct"] = (current_price - entry_price) / entry_price * 100.0
                    else:  # Short
                        exit_event["pnl_pct"] = (entry_price - current_price) / entry_price * 100.0
                return True, exit_event
        except Exception:
            pass
    
    # 2) Confidence drop and direction flip (from signal eval, no price needed)
    try:
        _, current_confidence, current_intent = _get_signal(symbol)
        current_direction = current_intent.get("direction", 0)
        
        if current_confidence < 0.42:
            # Confidence drop exit - use entry_price as fallback if no price
            exit_price = current_price if current_price is not None and current_price > 0 else entry_price
            exit_event = {
                "exit_reason": "confidence_drop",
                "exit_price": exit_price,
                "pnl_pct": 0.0 if current_price is None else None,
                "pnl_usd": 0.0 if current_price is None else None,
                "exit_px_source": "entry_fallback_no_price" if current_price is None else "current_price",
            }
            # Compute PnL if price is available
            if current_price is not None and current_price > 0:
                if direction == 1:  # Long
                    exit_event["pnl_pct"] = (current_price - entry_price) / entry_price * 100.0
                else:  # Short
                    exit_event["pnl_pct"] = (entry_price - current_price) / entry_price * 100.0
            return True, exit_event
        
        # Check direction flip
        if current_direction != 0 and current_direction != direction:
            if current_confidence >= 0.55:
                # Direction flip exit - use entry_price as fallback if no price
                exit_price = current_price if current_price is not None and current_price > 0 else entry_price
                exit_event = {
                    "exit_reason": "direction_flip",
                    "exit_price": exit_price,
                    "pnl_pct": 0.0 if current_price is None else None,
                    "pnl_usd": 0.0 if current_price is None else None,
                    "exit_px_source": "entry_fallback_no_price" if current_price is None else "current_price",
                }
                # Compute PnL if price is available
                if current_price is not None and current_price > 0:
                    if direction == 1:  # Long
                        exit_event["pnl_pct"] = (current_price - entry_price) / entry_price * 100.0
                    else:  # Short
                        exit_event["pnl_pct"] = (entry_price - current_price) / entry_price * 100.0
                return True, exit_event
    except Exception:
        pass
    
    # 3) TP/SL check (requires price)
    if current_price is not None and current_price > 0:
        if direction == 1:  # Long
            pct_change = (current_price - entry_price) / entry_price * 100.0
            if pct_change >= TP_PCT:
                return True, {
                    "exit_reason": "tp",
                    "exit_price": current_price,
                    "pnl_pct": pct_change,
                    "pnl_usd": None,  # Will compute from notional
                    "exit_px_source": "current_price",
                }
            if pct_change <= -SL_PCT:
                return True, {
                    "exit_reason": "sl",
                    "exit_price": current_price,
                    "pnl_pct": pct_change,
                    "pnl_usd": None,  # Will compute from notional
                    "exit_px_source": "current_price",
                }
        elif direction == -1:  # Short
            pct_change = (entry_price - current_price) / entry_price * 100.0
            if pct_change >= TP_PCT:
                return True, {
                    "exit_reason": "tp",
                    "exit_price": current_price,
                    "pnl_pct": pct_change,
                    "pnl_usd": None,  # Will compute from notional
                    "exit_px_source": "current_price",
                }
            if pct_change <= -SL_PCT:
                return True, {
                    "exit_reason": "sl",
                    "exit_price": current_price,
                    "pnl_pct": pct_change,
                    "pnl_usd": None,  # Will compute from notional
                    "exit_px_source": "current_price",
                }
    
    return False, None


def run_recovery_lane_v2(now_iso: Optional[str] = None) -> Dict[str, Any]:
    """
    Run recovery lane v2 evaluation.
    
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
    
    # Check recovery ramp v2 state
    recovery_ramp_v2 = _load_json(RECOVERY_RAMP_V2_PATH)
    recovery_ramp_v1 = _load_json(RECOVERY_RAMP_V1_PATH)

    # Load symbol states (for per-symbol recovery allow/quarantine/caps)
    symbol_states = load_symbol_states()
    symbol_state_map = symbol_states.get("symbols") if isinstance(symbol_states, dict) else {}
    
    if not recovery_ramp_v2:
        result["reason"] = "recovery_ramp_v2_state_missing"
        _append_log(result)
        return result
    
    # Check if recovery lane is allowed
    decision = recovery_ramp_v2.get("decision", {})
    allow_recovery_lane = decision.get("allow_recovery_lane", True)

    # Capital mode is used for halt-mode probe tightening (max hold clamp).
    capital_mode = (
        (recovery_ramp_v2.get("global") or {}).get("mode")
        or recovery_ramp_v2.get("capital_mode")
        or (recovery_ramp_v2.get("global") or {}).get("capital_mode")
        or "unknown"
    )
    # Clean closes pass from recovery ramp v1 (for stabilization softening)
    clean_closes_pass_v1 = (recovery_ramp_v1.get("gates") or {}).get("clean_closes_pass")
    if clean_closes_pass_v1 is None:
        clean_closes_pass_v1 = True

    # Hard stop / exit-only mode: authoritative allowances / hysteresis from v1
    hysteresis_v1 = recovery_ramp_v1.get("hysteresis") or {}
    needed_ok_v1 = hysteresis_v1.get("needed_ok_ticks") or recovery_ramp_v1.get("needed_ok_ticks") or 0
    ok_ticks_v1 = hysteresis_v1.get("ok_ticks") or 0
    allow_recovery_trading_v1 = True  # advisory only; per-symbol policy governs

    # Advisory only; do not force exit-only
    exit_only = False
    exit_only_reason = None
    
    # Load state
    state = _load_json(STATE_PATH)
    open_positions = state.get("open_positions", {})
    
    # PHASE 5H EXIT FIX: Evaluate exits FIRST, before any other checks
    # This ensures positions close (timeout/TP/SL/etc) even when price is unavailable
    for symbol, position in list(open_positions.items()):
        if position.get("direction", 0) == 0:
            continue
        
        try:
            # Get current price (may be None - that's OK for timeout/conf_drop/dir_flip)
            current_price = _get_current_price(symbol, "15m")
            
            # Evaluate exit conditions (works even if price is None)
            did_exit, exit_event = _maybe_exit_open_position(
                symbol,
                position,
                now,
                current_price,
                capital_mode=capital_mode,
            )
            
            if did_exit and exit_event:
                # Get full position data (including notional_usd from positions map if needed)
                positions_map = state.get("positions", {})
                full_position = positions_map.get(symbol, position)
                
                # Extract exit event data
                exit_reason = exit_event["exit_reason"]
                exit_price = exit_event["exit_price"]
                exit_px_source = exit_event.get("exit_px_source", "current_price")
                
                # Get position data
                entry_price = position.get("entry_price", 0.0)
                direction = position.get("direction", 0)
                entry_confidence = position.get("confidence", 0.0)
                # Use notional_usd from full_position (more reliable) or fallback to position
                notional_usd = full_position.get("notional_usd") or position.get("notional_usd", 0.0)
                trade_id = position.get("trade_id") or full_position.get("trade_id")
                
                if not trade_id:
                    # Generate trade_id if missing (backward compatibility)
                    trade_id = generate_trade_id()
                
                # Get PnL from exit_event (already computed, or 0.0 if no price)
                pnl_pct = exit_event.get("pnl_pct")
                if pnl_pct is None:
                    # Shouldn't happen, but fallback
                    pnl_pct = 0.0
                
                # Compute PnL in USD using position's notional at exit-time
                pnl_usd = exit_event.get("pnl_usd")
                if pnl_usd is None:
                    # Compute from notional if available
                    if notional_usd > 0:
                        pnl_usd = notional_usd * (pnl_pct / 100.0)
                    else:
                        pnl_usd = 0.0
                
                # Ensure notional_usd is valid (must be > 0 for proper reporting)
                if notional_usd <= 0:
                    # Fallback: use MAX_NOTIONAL_USD as estimate if missing
                    notional_usd = MAX_NOTIONAL_USD
                    if pnl_pct != 0.0:
                        pnl_usd = notional_usd * (pnl_pct / 100.0)
                
                # Get current confidence for exit log
                intent_dict = compute_recovery_intent(symbol, timeframe="15m")
                exit_confidence = intent_dict.get("confidence", entry_confidence)
                
                # Log to trades.jsonl (always include correct notional/pnl_usd)
                log_close(
                    trade_id=trade_id,
                    ts=now.isoformat(),
                    symbol=symbol,
                    direction=direction,
                    confidence=exit_confidence,
                    notional_usd=notional_usd,
                    entry_px=entry_price,
                    exit_px=exit_price,
                    pnl_pct=pnl_pct,
                    pnl_usd=pnl_usd,
                    exit_reason=exit_reason,
                )
                
                # Log to lane log (include exit_px_source diagnostic)
                exit_result = {
                    "ts": now.isoformat(),
                    "action": "closed",
                    "reason": exit_reason,
                    "symbol": symbol,
                    "direction": direction,
                    "entry_px": entry_price,
                    "exit_px": exit_price,
                    "pnl_pct": pnl_pct,
                    "pnl_usd": pnl_usd,
                    "exit_px_source": exit_px_source,
                }
                _append_log(exit_result)
                
                # Remove position
                open_positions[symbol] = {"direction": 0}
                state["open_positions"] = open_positions
                
                # Cleanup: purge stale position metadata on close.
                # Without this, state["positions"][symbol] can look "open" even when
                # open_positions[symbol].direction == 0, which confuses ops checks.
                positions_map = state.get("positions", {})
                if isinstance(positions_map, dict) and symbol in positions_map:
                    try:
                        del positions_map[symbol]
                    except Exception:
                        pass
                    state["positions"] = positions_map
                
                # Phase 5H.2 Conservative Tightening: Set TP cooldown (15 minutes) if exit was TP
                # TP cooldown takes precedence over generic close cooldown
                if exit_reason == "tp":
                    if "tp_cooldowns" not in state:
                        state["tp_cooldowns"] = {}
                    state["tp_cooldowns"][symbol] = now.isoformat()
                    # Phase 5H.2 Conservative Tightening: Remove from post_close_cooldowns if present (mutually exclusive)
                    if "post_close_cooldowns" in state and symbol in state["post_close_cooldowns"]:
                        del state["post_close_cooldowns"][symbol]
                else:
                    # Phase 5H.2: Set post-close cooldown (10 minutes) for non-TP exits
                    if "post_close_cooldowns" not in state:
                        state["post_close_cooldowns"] = {}
                    state["post_close_cooldowns"][symbol] = now.isoformat()
                    # Phase 5H.2 Conservative Tightening: Remove from tp_cooldowns if present (mutually exclusive)
                    if "tp_cooldowns" in state and symbol in state["tp_cooldowns"]:
                        del state["tp_cooldowns"][symbol]
                
                _save_json(STATE_PATH, state)
                
                result.update(exit_result)
                return result
        except Exception:
            continue
    
    # Advisory: ramp v1 exit_only no longer blocks opens; note for observability
    if exit_only and exit_only_reason:
        result["exit_only_reason"] = exit_only_reason

    # Recovery opens are rehab-only: disable opens in normal capital mode (exits already processed above)
    if capital_mode not in {"halt_new_entries", "de_risk"}:
        result["reason"] = "recovery_disabled_in_normal"
        _append_log(result)
        return result
    
    # Recovery PF stop-loss gate: block new opens if recovery PF is bleeding
    pf7, n7 = _compute_recovery_pf_7d(now)
    if n7 >= 10 and pf7 is not None and pf7 < 0.95:
        result["reason"] = f"recovery_pf_gate (pf7d={pf7:.4f}, n={n7})"
        _append_log(result)
        return result
    
    # PHASE 5H EXIT FIX: Only check position limit AFTER exit evaluation
    # Reload state in case exits cleared positions
    state = _load_json(STATE_PATH)
    open_positions = state.get("open_positions", {})
    open_count = sum(1 for p in open_positions.values() if p.get("direction", 0) != 0)
    
    lane_max_positions = MAX_POSITIONS
    if open_count >= lane_max_positions:
        result["reason"] = f"max_positions_reached (count={open_count})"
        _append_log(result)
        return result
    
    # Phase 5H.2 Conservative Tightening: Check global rate limit EARLY (12 minutes between opens)
    # Phase 5H.2 Rotation Deadlock Fix: Use trades.jsonl as single source of truth
    rate_limit_blocked, last_open_ts_from_rate_limit, last_open_symbol_from_rate_limit = _check_global_rate_limit(state)
    if rate_limit_blocked:
        # Phase 5H.2 Cleanup: Use fresh last_open_ts from trades file for accurate diagnostics
        last_open_ts, last_open_symbol = _get_last_open_anytime_from_trades()
        if not last_open_ts:
            # Fallback to rate limit check result if trades file empty
            last_open_ts = last_open_ts_from_rate_limit
            last_open_symbol = last_open_symbol_from_rate_limit
        
        if last_open_ts:
            try:
                last_open_time = datetime.fromisoformat(last_open_ts.replace("Z", "+00:00"))
                if last_open_time.tzinfo is None:
                    last_open_time = last_open_time.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                secs_since = int((now - last_open_time).total_seconds())
            except Exception:
                secs_since = None
        else:
            secs_since = None
        result["reason"] = f"global_open_rate_limit (last_open_ts={last_open_ts[:19] if last_open_ts else '?'}, last_symbol={last_open_symbol or 'unknown'}, secs_since={secs_since}, min_secs={MIN_SECONDS_BETWEEN_OPENS})"
        _append_log(result)
        return result
    
    # Get allowed symbols and recommended order (from ramp v2)
    # Candidate set is driven by symbol_states allow_recovery (policy truth)
    symbol_map = symbol_states.get("symbols") if isinstance(symbol_states, dict) else {}
    policy_allow = [
        s for s, st in (symbol_map.items() if isinstance(symbol_map, dict) else [])
        if isinstance(st, dict) and st.get("allow_recovery") and not st.get("quarantined")
    ]
    ramp_allow = decision.get("allowed_symbols") or []
    # If ramp provides an ordering, keep it but filter by policy_allow
    recommended_order = [s for s in decision.get("recommended_order", ramp_allow) if s in policy_allow] or policy_allow
    allowed_symbols = policy_allow

    # Load symbol states to enforce per-coin recovery policy
    symbol_states = load_symbol_states()
    symbol_map = symbol_states.get("symbols") if isinstance(symbol_states, dict) else {}
    
    if not allowed_symbols:
        result["reason"] = "no_allowed_symbols_policy"
        _append_log(result)
        return result
    
    # Phase 5H.2: Collect all valid candidates first, then apply rotation/diversity
    symbol_diagnostics = []
    attempted_symbols = []
    valid_candidates = []  # (symbol, confidence, intent_dict, required_confidence)
    
    for symbol in recommended_order:
        if symbol not in allowed_symbols:
            continue  # Skip if not policy-allowed

        sym_state = symbol_map.get(symbol, {}) if isinstance(symbol_map, dict) else {}
        if not sym_state.get("allow_recovery", False):
            symbol_diagnostics.append(
                {"symbol": symbol, "blocked": True, "reason": "symbol_policy_block_recovery"}
            )
            continue

        sym_policy = symbol_state_map.get(symbol, {}) if isinstance(symbol_state_map, dict) else {}
        allow_recovery = bool(sym_policy.get("allow_recovery", False))
        if not allow_recovery:
            symbol_diagnostics.append(
                {"symbol": symbol, "blocked": True, "reason": "symbol_policy_block_recovery"}
            )
            continue
        if sym_policy.get("quarantined"):
            symbol_diagnostics.append(
                {"symbol": symbol, "blocked": True, "reason": "quarantined"}
            )
            continue
        # PF floor guard for recovery rehab
        pf7 = sym_policy.get("pf_7d")
        n7 = sym_policy.get("n_closes_7d") or 0
        if n7 >= 10 and pf7 is not None and pf7 < 0.85:
            symbol_diagnostics.append(
                {"symbol": symbol, "blocked": True, "reason": "recovery_pf_floor_block"}
            )
            continue
        rec_caps = (sym_policy.get("caps_by_lane") or {}).get("recovery", {})
        sym_rec_max = int(rec_caps.get("max_positions", MAX_POSITIONS))
        if sym_rec_max <= 0:
            symbol_diagnostics.append(
                {"symbol": symbol, "blocked": True, "reason": "recovery_cap_zero"}
            )
            continue
        
        attempted_symbols.append(symbol)
        # Check if already open
        if symbol in open_positions:
            pos_data = open_positions[symbol]
            if pos_data.get("direction", 0) != 0:
                continue  # Already open
        
        # Check cooldown (includes post-close cooldown, TP cooldown)
        # Phase 5H.2 Cleanup: Check cooldowns directly and only log if secs_remaining > 0
        now = datetime.now(timezone.utc)
        tp_cooldowns = state.get("tp_cooldowns", {})
        post_close_cooldowns = state.get("post_close_cooldowns", {})
        cooldowns_map = state.get("cooldowns", {})
        cooldown_blocked = False
        cooldown_reason = None
        
        # Phase 5H.2 Conservative Tightening: Check TP cooldown first (15 min)
        # Phase 5H.2 Cleanup: Only log cooldown if secs_remaining > 0, otherwise delete expired entry
        if symbol in tp_cooldowns:
            try:
                tp_cooldown_ts = tp_cooldowns.get(symbol)
                if tp_cooldown_ts:
                    cooldown_time = datetime.fromisoformat(tp_cooldown_ts.replace("Z", "+00:00")).astimezone(timezone.utc)
                    elapsed = (now - cooldown_time).total_seconds()
                    secs_remaining = int(TP_COOLDOWN_SECONDS - elapsed)
                    
                    if secs_remaining > 0:
                        # Still on cooldown - log it
                        cooldown_blocked = True
                        cooldown_reason = f"cooldown_after_tp({symbol}) secs_remaining={secs_remaining}"
                    else:
                        # Expired - delete from state and don't log
                        del tp_cooldowns[symbol]
                        state["tp_cooldowns"] = tp_cooldowns
                        _save_json(STATE_PATH, state)
            except Exception:
                pass
        
        # Check post-close cooldown (10 min) - only if TP cooldown not active
        # Phase 5H.2 Cleanup: Only log cooldown if secs_remaining > 0, otherwise delete expired entry
        if not cooldown_blocked and symbol in post_close_cooldowns:
            try:
                post_close_ts = post_close_cooldowns.get(symbol)
                if post_close_ts:
                    cooldown_time = datetime.fromisoformat(post_close_ts.replace("Z", "+00:00")).astimezone(timezone.utc)
                    elapsed = (now - cooldown_time).total_seconds()
                    secs_remaining = int(POST_CLOSE_COOLDOWN_SECONDS - elapsed)
                    
                    if secs_remaining > 0:
                        # Still on cooldown - log it
                        cooldown_blocked = True
                        cooldown_reason = f"cooldown_after_close({symbol}) secs_remaining={secs_remaining}"
                    else:
                        # Expired - delete from state and don't log
                        del post_close_cooldowns[symbol]
                        state["post_close_cooldowns"] = post_close_cooldowns
                        _save_json(STATE_PATH, state)
            except Exception:
                pass
        
        # Check no-signal cooldown (5 min)
        # Phase 5H.2 Cleanup: Only log if still active
        if not cooldown_blocked and symbol in cooldowns_map:
            try:
                cooldown_ts = cooldowns_map.get(symbol)
                if cooldown_ts:
                    cooldown_time = datetime.fromisoformat(cooldown_ts.replace("Z", "+00:00")).astimezone(timezone.utc)
                    elapsed = (now - cooldown_time).total_seconds()
                    secs_remaining = int(NO_SIGNAL_COOLDOWN_SECONDS - elapsed)
                    
                    if secs_remaining > 0:
                        # Still on cooldown - log it
                        cooldown_blocked = True
                        cooldown_reason = "cooldown_active"
                    else:
                        # Expired - delete from state and don't log
                        del cooldowns_map[symbol]
                        state["cooldowns"] = cooldowns_map
                        _save_json(STATE_PATH, state)
            except Exception:
                pass
        
        if cooldown_blocked:
            # Phase 5H.2 Cleanup: Only append diagnostic if cooldown is actually active (secs_remaining > 0)
            symbol_diagnostics.append({
                "symbol": symbol,
                "blocked": True,
                "reason": cooldown_reason,
            })
            continue
        
        # If we get here, cooldown check passed (or was expired and cleaned up)
        # Continue to signal evaluation
        
        # Phase 5H.2 Rotation Deadlock Fix: Rotation limit check moved to after candidate evaluation
        # (Rotation is now conditional on alternatives existing - see below)
        
        # Get signal using raw recovery intent (not exploit-intent filtered)
        direction, confidence, intent_dict = _get_signal(symbol)
        
        # Store diagnostic info
        regime = intent_dict.get("regime", "unknown")
        intent_reason = intent_dict.get("reason", "")
        
        # Phase 5H.2 Conservative Tightening with stabilization softening:
        # Apply regime-specific confidence threshold, but in chop + capital_mode normal + clean_closes not yet passed,
        # soften to 0.65 to encourage one more clean close.
        is_chop = regime.lower() == "chop"
        softened_conf = False
        required_confidence = ENTRY_CONF_MIN_CHOP if is_chop else ENTRY_CONF_MIN
        if (
            is_chop
            and capital_mode == "normal"
            and clean_closes_pass_v1 is False
        ):
            required_confidence = ENTRY_CONF_MIN_CHOP_SOFT
            softened_conf = True
        # Per-symbol regime sunshine: if global=chop but symbol regime is trend_up/down, lower req_conf by 0.05
        try:
            global_regime = None
            sym_regime = None
            reg_global_path = REPORTS / "regime_snapshot.json"
            reg_sym_path = REPORTS / "regimes" / f"regime_snapshot_{symbol}.json"
            if reg_global_path.exists():
                with reg_global_path.open("r", encoding="utf-8") as f:
                    g = json.load(f)
                gr = g.get("regime")
                if isinstance(gr, str):
                    global_regime = gr.lower()
            if reg_sym_path.exists():
                with reg_sym_path.open("r", encoding="utf-8") as f:
                    s = json.load(f)
                sr = s.get("regime")
                if isinstance(sr, str):
                    sym_regime = sr.lower()
            if global_regime == "chop" and sym_regime in ("trend_up", "trend_down"):
                required_confidence = max(0.0, required_confidence - 0.05)
                soft_note = (soft_note or "") + " regime_override(global=chop symbol_trend)"
        except Exception:
            pass
        soft_note = None
        if softened_conf:
            soft_note = f"req_conf_softened({ENTRY_CONF_MIN_CHOP:.2f}->{required_confidence:.2f})"
        
        symbol_diagnostics.append({
            "symbol": symbol,
            "direction": direction,
            "confidence": confidence,
            "regime": regime,
            "reason": intent_reason,
            "entry_ok": intent_dict.get("entry_ok", False),
            "required_confidence": required_confidence,
            "confidence_pass": confidence >= required_confidence,
            "soft_note": soft_note,
        })
        
        # Phase 5H.2 Conservative Tightening: Check if signal is valid for entry (regime-specific threshold)
        if not intent_dict.get("entry_ok", False) or confidence < required_confidence:
            # Set cooldown for no_valid_signals (5 minutes)
            if "cooldowns" not in state:
                state["cooldowns"] = {}
            state["cooldowns"][symbol] = now.isoformat()
            _save_json(STATE_PATH, state)
            continue  # No valid signal for this symbol
        
        # Valid candidate - add to list (store required_confidence for later use)
        if soft_note:
            intent_dict["req_conf_soft_note"] = soft_note
        valid_candidates.append((symbol, confidence, intent_dict, required_confidence))
    
    # Phase 5H.2: Apply diversity preference if multiple candidates
    # Phase 5H.2 Rotation Deadlock Fix: Rotation only enforced if alternative exists
    if valid_candidates:
        # Phase 5H.2 Rotation Deadlock Fix: Check if rotation would apply and if alternatives exist
        last_opens = _get_last_opens_from_trades()
        rotation_applies = False
        last_symbol_for_rotation = None
        
        if len(last_opens) >= MAX_CONSECUTIVE_SAME_SYMBOL:
            recent_opens = last_opens[-MAX_CONSECUTIVE_SAME_SYMBOL:]
            # Check if last N opens are all the same symbol
            if len(set(open_entry.get("symbol") for open_entry in recent_opens)) == 1:
                rotation_applies = True
                last_symbol_for_rotation = recent_opens[-1].get("symbol")
        
        # Phase 5H.2 Rotation Deadlock Fix: Only enforce rotation if there's an alternative candidate
        rotation_enforced = False
        rotation_blocked_symbol = None
        rotation_alt_symbol = None
        rotation_advisory_only = False
        
        if rotation_applies and last_symbol_for_rotation:
            # Check if any candidate is NOT the last symbol (alternative exists)
            alternative_candidates = [c for c in valid_candidates if c[0] != last_symbol_for_rotation]
            
            if alternative_candidates:
                # Alternative exists - enforce rotation (remove blocked symbol from candidates)
                rotation_enforced = True
                rotation_blocked_symbol = last_symbol_for_rotation
                rotation_allowed = alternative_candidates
                
                if rotation_allowed:
                    selected = _select_symbol_with_diversity(rotation_allowed, state)
                    if selected:
                        rotation_alt_symbol = selected[0]
                else:
                    # Fallback (shouldn't happen, but safety)
                    selected = _select_symbol_with_diversity(valid_candidates, state)
            else:
                # No alternative - allow to prevent deadlock (rotation advisory-only)
                rotation_advisory_only = True
                selected = _select_symbol_with_diversity(valid_candidates, state)
        else:
            # Rotation doesn't apply or not enough history - allow all candidates
            selected = _select_symbol_with_diversity(valid_candidates, state)
        
        if selected:
            symbol, confidence, intent_dict, required_confidence = selected
            
            # Final safety: re-check policy allow_recovery
            sym_state_selected = symbol_map.get(symbol, {}) if isinstance(symbol_map, dict) else {}
            if not sym_state_selected.get("allow_recovery", False) or sym_state_selected.get("quarantined"):
                result["reason"] = f"symbol_policy_block_recovery:{symbol}"
                _append_log(result)
                return result
            
            # Get current price (robust helper)
            current_price = _get_current_price(symbol, "15m")
            
            if current_price is None or current_price <= 0:
                # Price unavailable - skip opening this symbol (don't log separately, will be caught by final diagnostics)
                # Fall through to final diagnostics
                pass
            else:
                # Get notional limit for this symbol
                symbol_data = recovery_ramp_v2.get("symbols", {}).get(symbol, {})
                limits = symbol_data.get("limits", {})
                notional_usd = min(MAX_NOTIONAL_USD, limits.get("notional_usd", MAX_NOTIONAL_USD))
                
                # Get direction from intent_dict
                direction = intent_dict.get("direction", 0)
                
                # Attempt to open trade
                try:
                    # Recovery V2 opens are NOT mirrored to core position_state.json
                    success = open_if_allowed(
                        final_dir=direction,
                        final_conf=confidence,
                        entry_min_conf=required_confidence,  # Phase 5H.2 Conservative Tightening: Use regime-specific threshold
                        risk_mult=0.25,  # Capped risk multiplier
                        symbol=symbol,
                        disable_softening=True,  # Phase 5H.2 Conservative Tightening: Disable softening for Recovery V2
                        timeframe="15m",
                        exploration_pass=False,
                        strategy="recovery_v2",
                        persist_position=False,  # Do not write to position_state.json
                    )
                    
                    if success:
                        # Generate trade_id
                        trade_id = generate_trade_id()
                        
                        # Update state with full position info
                        if "open_positions" not in state:
                            state["open_positions"] = {}
                        if "last_trades" not in state:
                            state["last_trades"] = {}
                        if "positions" not in state:
                            state["positions"] = {}
                        
                        # Phase 5H.2: Update last_opens list (keep last 5)
                        if "last_opens" not in state:
                            state["last_opens"] = []
                        state["last_opens"].append({
                            "ts": now.isoformat(),
                            "symbol": symbol,
                        })
                        # Keep only last 5
                        state["last_opens"] = state["last_opens"][-5:]
                        
                        # Store position with full metadata
                        position_data = {
                            "trade_id": trade_id,
                            "symbol": symbol,
                            "direction": direction,
                            "entry_price": current_price,
                            "entry_ts": now.isoformat(),
                            "entry_confidence": confidence,
                            "notional_usd": notional_usd,
                            "tp_pct": TP_PCT / 100.0,  # Convert to decimal
                            "sl_pct": SL_PCT / 100.0,
                            "max_hold_seconds": HALT_MAX_HOLD_SECONDS if capital_mode == "halt_new_entries" else (MAX_HOLD_MINUTES * 60),
                        }
                        
                        state["open_positions"][symbol] = {
                            "direction": direction,
                            "entry_price": current_price,
                            "entry_ts": now.isoformat(),
                            "confidence": confidence,
                            "trade_kind": "recovery_v2",
                            "trade_id": trade_id,
                            "notional_usd": notional_usd,
                            "max_hold_seconds": position_data["max_hold_seconds"],
                        }
                        state["positions"][symbol] = position_data
                        state["last_trades"][symbol] = now.isoformat()
                        state["generated_at"] = now.isoformat()
                        
                        # Clear cooldown for this symbol (successful entry)
                        if "cooldowns" in state and symbol in state["cooldowns"]:
                            del state["cooldowns"][symbol]
                        
                        _save_json(STATE_PATH, state)
                        
                        # Log to recovery lane log only (opens are not mirrored globally to avoid duplicates)
                        log_open(
                            trade_id=trade_id,
                            ts=now.isoformat(),
                            symbol=symbol,
                            direction=direction,
                            confidence=confidence,
                            notional_usd=notional_usd,
                            entry_px=current_price,
                            regime=intent_dict.get("regime", "unknown"),
                            reason=intent_dict.get("reason", "signal_ready"),
                        )
                        
                        result["action"] = "opened"
                        reason = "recovery_v2_trade_opened"
                        soft_note = intent_dict.get("req_conf_soft_note")
                        if soft_note:
                            reason += f" {soft_note}"
                        if rotation_enforced:
                            reason += f" rotation_enforced(blocked_third_consecutive={rotation_blocked_symbol}, alt_used={rotation_alt_symbol})"
                        elif rotation_advisory_only:
                            reason += " rotation_advisory_only(no_alt_candidates)"
                        result["reason"] = reason
                        result["symbol"] = symbol
                        result["direction"] = direction
                        result["confidence"] = confidence
                        result["notional_usd"] = notional_usd
                        
                        _append_log(result)
                        return result
                    else:
                        result["reason"] = f"open_if_allowed_blocked (symbol={symbol})"
                        # Fall through to diagnostics
                except Exception as e:
                    result["reason"] = f"execution_error: {str(e)}"
                    # Fall through to diagnostics
    
    # No trade opened - log diagnostics
    # Phase 5H.2 Cleanup: Build diagnostics first, then retrieve last_open_ts FRESH right before formatting
    if symbol_diagnostics:
        # Build diagnostic reason string with improved context
        diag_parts = []
        for diag in symbol_diagnostics:
            sym = diag.get("symbol", "?")
            if diag.get("blocked"):
                reason = diag.get("reason", "blocked")
                # Phase 5H.2: Format rotation/cooldown reasons
                # Phase 5H.2 Rotation Deadlock Fix: Legacy rotation string removed
                # Rotation is now handled conditionally after candidate evaluation, not during symbol iteration
                # Phase 5H.2 Cleanup: Filter out any cooldown reasons with secs_remaining=0
                if "secs_remaining=0" in reason:
                    # Skip expired cooldown diagnostics
                    continue
                elif reason == "cooldown_after_tp":
                    diag_parts.append(f"{sym}:cooldown_after_tp({sym})")
                elif reason == "cooldown_after_close":
                    diag_parts.append(f"{sym}:cooldown_after_close({sym})")
                elif "rotation_limit" in reason or "skipped_rotation" in reason:
                    # Phase 5H.2 Rotation Deadlock Fix: Convert any old rotation_limit reason to generic blocked
                    diag_parts.append(f"{sym}:blocked")
                else:
                    diag_parts.append(f"{sym}:{reason}")
            else:
                dir_str = "LONG" if diag.get("direction") == 1 else "SHORT" if diag.get("direction") == -1 else "FLAT"
                conf = diag.get("confidence", 0.0)
                entry_ok = diag.get("entry_ok", False)
                regime = diag.get("regime", "unknown")
                required_conf = diag.get("required_confidence", 0.0)
                conf_pass = diag.get("confidence_pass", False)
                soft_note = diag.get("soft_note")
                # Phase 5H.2 Conservative Tightening: Include regime and confidence threshold info
                info = f"{sym}:{dir_str}:conf={conf:.2f}:regime={regime}:req_conf={required_conf:.2f}:pass={'Y' if conf_pass else 'N'}:entry={'Y' if entry_ok else 'N'}"
                if soft_note:
                    info += f":{soft_note}"
                diag_parts.append(info)
        
        # Phase 5H.2 Cleanup: Retrieve last_open_ts/last_symbol FRESH right before formatting reason string
        # Use _get_last_open_anytime_from_trades() (no time filtering) to ensure we get the absolute most recent open
        last_open_ts, last_symbol = _get_last_open_anytime_from_trades()
        
        # Fallback to state only if trades log is completely empty (shouldn't happen, but defensive)
        if not last_open_ts:
            last_opens = state.get("last_opens", [])
            if last_opens:
                last_open = last_opens[-1]
                last_open_ts = last_open.get("ts")
                last_symbol = last_open.get("symbol")
        
        # Phase 5H.2 Rotation Deadlock Fix: Include last open context (from trades.jsonl)
        context_parts = []
        if last_open_ts:
            context_parts.append(f"last_open_ts={last_open_ts[:19]}")
        if last_symbol:
            context_parts.append(f"last_symbol={last_symbol}")
        
        context_str = f" ({', '.join(context_parts)})" if context_parts else ""
        result["reason"] = f"no_valid_signals ({'; '.join(diag_parts)}){context_str}"
    else:
        # Check if all candidates are on cooldown
        if attempted_symbols:
            all_on_cooldown = all(_check_cooldown(sym, state) for sym in attempted_symbols)
            if all_on_cooldown:
                result["reason"] = "all_candidates_on_cooldown"
            else:
                result["reason"] = "no_valid_signals"
        else:
            result["reason"] = "no_valid_signals"
    
    _append_log(result)
    return result


__all__ = ["run_recovery_lane_v2"]

