"""
Probe → Exploit Promotion Gate
-------------------------------

Automatically promotes from Probe → Full Exploit when live probe performance
confirms shadow edge, and demotes if performance deteriorates.

Modes:
- DISABLED: No exploit opens allowed
- PROBE_ONLY: Only probe lane can open positions
- EXPLOIT_ENABLED: Full exploit lane can open positions

This gate is the single source of truth for whether exploit lane can open new positions.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from engine_alpha.core.paths import REPORTS

# Paths
PROBE_GATE_PATH = REPORTS / "loop" / "probe_lane_gate.json"
PROBE_STATE_PATH = REPORTS / "loop" / "probe_lane_state.json"
PROBE_LOG_PATH = REPORTS / "loop" / "probe_lane_log.jsonl"
CAPITAL_PROTECTION_PATH = REPORTS / "risk" / "capital_protection.json"
SHADOW_SCORES_PATH = REPORTS / "reflect" / "shadow_exploit_scores.json"
SHADOW_PF_PATH = REPORTS / "reflect" / "shadow_exploit_pf.json"
EXPLOIT_TRADES_PATH = REPORTS / "exploit" / "exploit_trades.jsonl"
TRADES_PATH = REPORTS / "trades.jsonl"
GATE_STATE_PATH = REPORTS / "loop" / "promotion_gate.json"
GATE_LOG_PATH = REPORTS / "loop" / "promotion_gate_log.jsonl"

# Thresholds
MIN_PROBE_TRADES = 12
MIN_PROBE_PF = 1.05
MAX_PROBE_DD = 0.15  # 0.15%
MAX_CONSECUTIVE_LOSSES = 2
DEMOTE_PF_THRESHOLD = 1.00
DEMOTE_CONSECUTIVE_LOSSES = 3
DEMOTE_DD_THRESHOLD = 0.20  # 0.20%
MIN_SHADOW_PF_7D = 1.05
DEMOTE_SHADOW_PF_THRESHOLD = 1.02
SHADOW_DATA_STALE_MINUTES = 90
PROBE_GATE_RECENT_ENABLE_HOURS = 6


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
    """Append entry to promotion gate log."""
    GATE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with GATE_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _parse_timestamp(ts_str: str) -> datetime:
    """Parse ISO timestamp."""
    try:
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _is_probe_trade(trade: Dict[str, Any]) -> bool:
    """Check if a trade is a probe trade."""
    # Check various fields that might indicate probe
    intent = str(trade.get("intent", "")).lower()
    reason = str(trade.get("reason", "")).lower()
    tag = str(trade.get("tag", "")).lower()
    lane = str(trade.get("lane", "")).lower()
    
    return (
        "probe" in intent or
        "probe" in reason or
        "probe" in tag or
        "probe" in lane or
        trade.get("probe", False) is True
    )


def _load_probe_trades(now: datetime, window_days: int = 7) -> List[Dict[str, Any]]:
    """Load probe trades from trade logs."""
    probe_trades = []
    cutoff = now - timedelta(days=window_days)
    
    # Try exploit trades log first (most likely for probe)
    for log_path in [EXPLOIT_TRADES_PATH, TRADES_PATH]:
        if not log_path.exists():
            continue
        
        try:
            with log_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        trade = json.loads(line)
                        ts_str = trade.get("ts") or trade.get("timestamp")
                        if not ts_str:
                            continue
                        
                        trade_time = _parse_timestamp(ts_str)
                        if trade_time < cutoff:
                            continue
                        
                        if _is_probe_trade(trade):
                            probe_trades.append(trade)
                    except Exception:
                        continue
        except Exception:
            continue
    
    # Also check probe lane log for opened trades
    if PROBE_LOG_PATH.exists():
        try:
            with PROBE_LOG_PATH.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("action") == "opened":
                            ts_str = entry.get("ts")
                            if ts_str:
                                entry_time = _parse_timestamp(ts_str)
                                if entry_time >= cutoff:
                                    # Create a synthetic trade entry
                                    probe_trades.append({
                                        "ts": ts_str,
                                        "event": "open",
                                        "symbol": entry.get("selected_symbol"),
                                        "intent": "probe",
                                        "reason": entry.get("reason", "probe_lane"),
                                    })
                    except Exception:
                        continue
        except Exception:
            pass
    
    # Sort by timestamp
    probe_trades.sort(key=lambda t: _parse_timestamp(t.get("ts", "") or t.get("timestamp", "")))
    return probe_trades


def _compute_probe_metrics(probe_trades: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    """Compute live probe metrics from trades."""
    if not probe_trades:
        return {
            "trades": 0,
            "pf": 0.0,
            "win_rate": 0.0,
            "max_dd": 0.0,
            "consecutive_losses": 0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
        }
    
    # Extract PnL from trades
    pnls = []
    for trade in probe_trades:
        # Try various PnL fields
        pnl = (
            trade.get("pnl_usd") or
            trade.get("pnl") or
            trade.get("profit_usd") or
            trade.get("profit") or
            0.0
        )
        if isinstance(pnl, (int, float)):
            pnls.append(float(pnl))
    
    if not pnls:
        return {
            "trades": len(probe_trades),
            "pf": 0.0,
            "win_rate": 0.0,
            "max_dd": 0.0,
            "consecutive_losses": 0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
        }
    
    # Compute metrics
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    
    # PF calculation (handle zero loss)
    if gross_loss > 0:
        pf = gross_profit / gross_loss
    elif gross_profit > 0:
        pf = 999.0  # Infinite PF (all wins)
    else:
        pf = 0.0
    
    win_rate = len(wins) / len(pnls) if pnls else 0.0
    
    # Compute max drawdown (peak-to-trough)
    equity_curve = []
    running_total = 0.0
    for pnl in pnls:
        running_total += pnl
        equity_curve.append(running_total)
    
    max_dd = 0.0
    if equity_curve:
        peak = equity_curve[0]
        for equity in equity_curve:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / max(abs(peak), 1.0) * 100.0  # Percentage
            if dd > max_dd:
                max_dd = dd
    
    # Compute consecutive losses (from end)
    consecutive_losses = 0
    for pnl in reversed(pnls):
        if pnl < 0:
            consecutive_losses += 1
        else:
            break
    
    return {
        "trades": len(pnls),
        "pf": pf,
        "win_rate": win_rate,
        "max_dd": max_dd,
        "consecutive_losses": consecutive_losses,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
    }


def _check_shadow_data_freshness(shadow_scores: Dict[str, Any], shadow_pf: Dict[str, Any], now: datetime) -> Tuple[bool, str]:
    """Check if shadow data is fresh (<90 minutes old)."""
    scores_ts = shadow_scores.get("meta", {}).get("generated_at") or shadow_scores.get("generated_at")
    pf_ts = shadow_pf.get("generated_at")
    
    timestamps = [ts for ts in [scores_ts, pf_ts] if ts]
    if not timestamps:
        return False, "no_timestamp"
    
    most_recent = None
    for ts_str in timestamps:
        try:
            ts = _parse_timestamp(ts_str)
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


def evaluate_promotion_gate(now_iso: Optional[str] = None) -> Dict[str, Any]:
    """
    Evaluate promotion gate status.
    
    Returns:
        Dict with mode, decision, reason, and diagnostic data
    """
    now = datetime.now(timezone.utc) if now_iso is None else _parse_timestamp(now_iso)
    
    # Initialize result
    result = {
        "mode": "DISABLED",
        "decision": "hold",
        "reason": "",
        "selected_symbol": None,
        "live_probe": {
            "trades": 0,
            "pf": 0.0,
            "win_rate": 0.0,
            "max_dd": 0.0,
            "consecutive_losses": 0,
        },
        "shadow": {
            "pf_7d": None,
            "pf_30d": None,
            "trades": None,
        },
        "evaluated_at": now.isoformat(),
    }
    
    try:
        # Load required data
        probe_gate = _load_json(PROBE_GATE_PATH)
        probe_state = _load_json(PROBE_STATE_PATH)
        capital_protection = _load_json(CAPITAL_PROTECTION_PATH)
        shadow_scores = _load_json(SHADOW_SCORES_PATH)
        shadow_pf = _load_json(SHADOW_PF_PATH)
        
        # Extract capital mode
        capital_mode = (
            capital_protection.get("mode") or
            capital_protection.get("global", {}).get("mode") or
            "unknown"
        )
        
        # Check probe gate status
        probe_gate_enabled = probe_gate.get("enabled", False)
        probe_gate_evaluated_at = probe_gate.get("evaluated_at")
        
        # Check if probe gate was recently enabled (within last 6h)
        probe_gate_recently_enabled = False
        if probe_gate_evaluated_at:
            try:
                gate_time = _parse_timestamp(probe_gate_evaluated_at)
                hours_since = (now - gate_time).total_seconds() / 3600
                if hours_since < PROBE_GATE_RECENT_ENABLE_HOURS and probe_gate_enabled:
                    probe_gate_recently_enabled = True
            except Exception:
                pass
        
        # DISABLE CONDITION: probe gate disabled AND capital_mode != normal
        if not probe_gate_enabled and not probe_gate_recently_enabled:
            if capital_mode != "normal":
                result["mode"] = "DISABLED"
                result["decision"] = "hold"
                result["reason"] = f"probe_gate_disabled_and_capital_mode={capital_mode}"
                _save_json(GATE_STATE_PATH, result)
                _append_log(result)
                return result
        
        # Load probe trades and compute metrics
        probe_trades = _load_probe_trades(now, window_days=7)
        probe_metrics = _compute_probe_metrics(probe_trades, now)
        result["live_probe"] = probe_metrics
        
        # Get shadow metrics
        global_scores = shadow_scores.get("global", {}) or shadow_scores.get("metrics", {})
        global_pf = shadow_pf.get("global", {}) or shadow_pf.get("metrics", {})
        
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
        
        result["shadow"]["pf_7d"] = shadow_pf_7d
        result["shadow"]["pf_30d"] = shadow_pf_30d
        result["shadow"]["trades"] = shadow_trades
        
        # Check shadow data freshness
        fresh, freshness_reason = _check_shadow_data_freshness(shadow_scores, shadow_pf, now)
        if not fresh:
            result["mode"] = "DISABLED"
            result["decision"] = "demote"
            result["reason"] = f"shadow_data_{freshness_reason}"
            _save_json(GATE_STATE_PATH, result)
            _append_log(result)
            return result
        
        # Get selected symbol from probe state
        selected_symbol = probe_state.get("last_symbol")
        result["selected_symbol"] = selected_symbol
        
        # Load previous gate state to check current mode
        prev_gate = _load_json(GATE_STATE_PATH)
        prev_mode = prev_gate.get("mode", "DISABLED")
        
        # DEMOTION CONDITIONS (check first if currently EXPLOIT_ENABLED)
        if prev_mode == "EXPLOIT_ENABLED":
            # Check demotion triggers
            if probe_metrics["trades"] >= 6:
                if probe_metrics["pf"] < DEMOTE_PF_THRESHOLD:
                    result["mode"] = "PROBE_ONLY"
                    result["decision"] = "demote"
                    result["reason"] = f"live_probe_pf={probe_metrics['pf']:.3f} < {DEMOTE_PF_THRESHOLD}"
                    _save_json(GATE_STATE_PATH, result)
                    _append_log(result)
                    return result
            
            if probe_metrics["consecutive_losses"] >= DEMOTE_CONSECUTIVE_LOSSES:
                result["mode"] = "PROBE_ONLY"
                result["decision"] = "demote"
                result["reason"] = f"consecutive_losses={probe_metrics['consecutive_losses']} >= {DEMOTE_CONSECUTIVE_LOSSES}"
                _save_json(GATE_STATE_PATH, result)
                _append_log(result)
                return result
            
            if probe_metrics["max_dd"] > DEMOTE_DD_THRESHOLD:
                result["mode"] = "PROBE_ONLY"
                result["decision"] = "demote"
                result["reason"] = f"max_dd={probe_metrics['max_dd']:.3f}% > {DEMOTE_DD_THRESHOLD}%"
                _save_json(GATE_STATE_PATH, result)
                _append_log(result)
                return result
            
            if shadow_pf_7d is not None and shadow_pf_7d < DEMOTE_SHADOW_PF_THRESHOLD:
                result["mode"] = "PROBE_ONLY"
                result["decision"] = "demote"
                result["reason"] = f"shadow_pf_7d={shadow_pf_7d:.3f} < {DEMOTE_SHADOW_PF_THRESHOLD}"
                _save_json(GATE_STATE_PATH, result)
                _append_log(result)
                return result
        
        # PROMOTION CONDITIONS (ALL required)
        # Condition 1: Probe gate enabled or recently enabled
        if not probe_gate_enabled and not probe_gate_recently_enabled:
            result["mode"] = "PROBE_ONLY"
            result["decision"] = "hold"
            result["reason"] = "probe_gate_not_enabled"
            _save_json(GATE_STATE_PATH, result)
            _append_log(result)
            return result
        
        # Condition 2: Minimum probe trades
        if probe_metrics["trades"] < MIN_PROBE_TRADES:
            result["mode"] = "PROBE_ONLY"
            result["decision"] = "hold"
            result["reason"] = f"probe_trades={probe_metrics['trades']} < {MIN_PROBE_TRADES}"
            _save_json(GATE_STATE_PATH, result)
            _append_log(result)
            return result
        
        # Condition 3: Live probe PF >= 1.05
        if probe_metrics["pf"] < MIN_PROBE_PF:
            result["mode"] = "PROBE_ONLY"
            result["decision"] = "hold"
            result["reason"] = f"live_probe_pf={probe_metrics['pf']:.3f} < {MIN_PROBE_PF}"
            _save_json(GATE_STATE_PATH, result)
            _append_log(result)
            return result
        
        # Condition 4: Max DD <= 0.15%
        if probe_metrics["max_dd"] > MAX_PROBE_DD:
            result["mode"] = "PROBE_ONLY"
            result["decision"] = "hold"
            result["reason"] = f"max_dd={probe_metrics['max_dd']:.3f}% > {MAX_PROBE_DD}%"
            _save_json(GATE_STATE_PATH, result)
            _append_log(result)
            return result
        
        # Condition 5: Consecutive losses <= 2
        if probe_metrics["consecutive_losses"] > MAX_CONSECUTIVE_LOSSES:
            result["mode"] = "PROBE_ONLY"
            result["decision"] = "hold"
            result["reason"] = f"consecutive_losses={probe_metrics['consecutive_losses']} > {MAX_CONSECUTIVE_LOSSES}"
            _save_json(GATE_STATE_PATH, result)
            _append_log(result)
            return result
        
        # Condition 6: Shadow confirmation
        if shadow_pf_7d is None or shadow_pf_7d < MIN_SHADOW_PF_7D:
            result["mode"] = "PROBE_ONLY"
            result["decision"] = "hold"
            result["reason"] = f"shadow_pf_7d={shadow_pf_7d:.3f if shadow_pf_7d else None} < {MIN_SHADOW_PF_7D}"
            _save_json(GATE_STATE_PATH, result)
            _append_log(result)
            return result
        
        # Check per-symbol shadow confirmation if selected_symbol exists
        if selected_symbol:
            by_symbol_scores = shadow_scores.get("by_symbol", {}) or shadow_scores.get("symbols", {})
            by_symbol_pf = shadow_pf.get("by_symbol", {}) or shadow_pf.get("symbols", {})
            
            symbol_scores = by_symbol_scores.get(selected_symbol, {})
            symbol_pf = by_symbol_pf.get(selected_symbol, {})
            
            symbol_trades_30d = symbol_scores.get("trades_30d", 0) or symbol_pf.get("trades_30d", 0)
            symbol_pf_30d = (
                symbol_scores.get("pf_30d_display") or
                symbol_scores.get("pf_30d") or
                symbol_pf.get("pf_30d_display") or
                symbol_pf.get("pf_30d")
            )
            
            if symbol_trades_30d < 30 or (symbol_pf_30d is not None and symbol_pf_30d < 1.05):
                result["mode"] = "PROBE_ONLY"
                result["decision"] = "hold"
                result["reason"] = f"symbol_{selected_symbol}_shadow_insufficient (trades={symbol_trades_30d}, pf_30d={symbol_pf_30d:.3f if symbol_pf_30d else None})"
                _save_json(GATE_STATE_PATH, result)
                _append_log(result)
                return result
        
        # ALL CONDITIONS MET - PROMOTE TO EXPLOIT_ENABLED
        result["mode"] = "EXPLOIT_ENABLED"
        result["decision"] = "promote"
        result["reason"] = "all_conditions_met"
        _save_json(GATE_STATE_PATH, result)
        _append_log(result)
        return result
    
    except Exception as e:
        # On error, disable for safety
        result["mode"] = "DISABLED"
        result["decision"] = "demote"
        result["reason"] = f"evaluation_error: {str(e)}"
        _save_json(GATE_STATE_PATH, result)
        _append_log(result)
        return result


__all__ = ["evaluate_promotion_gate"]

