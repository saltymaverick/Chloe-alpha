"""
Loss-Contributor Quarantine Engine (Phase 5g)
---------------------------------------------

Automatically identifies and quarantines symbols causing the most losses
during de_risk and halt_new_entries modes.

Safety:
- PAPER-only
- Restrictive-only (never enables trading)
- Never blocks exits
- Only applies during specified capital modes
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.research.pf_timeseries import _extract_return, _safe_parse_ts as _parse_timestamp

# Paths
CONFIG_PATH = CONFIG / "quarantine.json"
QUARANTINE_STATE_PATH = REPORTS / "risk" / "quarantine.json"
QUARANTINE_HISTORY_PATH = REPORTS / "risk" / "quarantine_history.jsonl"
CAPITAL_PROTECTION_PATH = REPORTS / "risk" / "capital_protection.json"
TRADES_PATH = REPORTS / "trades.jsonl"
EXPLOIT_TRADES_PATH = REPORTS / "loop" / "exploit_micro_log.jsonl"
SHADOW_TRADES_PATH = REPORTS / "reflect" / "shadow_exploit_log.jsonl"


def _load_json(path: Path) -> Dict[str, Any]:
    """Safely load JSON file."""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load JSONL file."""
    if not path.exists():
        return []
    trades = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trades.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return trades


def _load_config() -> Dict[str, Any]:
    """Load quarantine configuration."""
    defaults = {
        "enabled": True,
        "window_days": 30,
        "max_symbols": 2,
        "min_negative_pnl_usd": 0.05,
        "min_contribution_pct": 20.0,
        "cooldown_hours": 24,
        "modes_apply": ["de_risk", "halt_new_entries"],
        "actions": {
            "block_new_entries": True,
            "reduce_weight": True,
            "weight_floor": 0.00,
            "weight_multiplier": 0.00,
        },
    }
    
    if not CONFIG_PATH.exists():
        return defaults
    
    try:
        config = _load_json(CONFIG_PATH)
        # Merge with defaults
        result = defaults.copy()
        result.update(config)
        if "actions" in config:
            result["actions"] = {**defaults["actions"], **config["actions"]}
        return result
    except Exception:
        return defaults


def _load_trades_all_lanes(window_days: int, now: datetime) -> List[Dict[str, Any]]:
    """Load trades from all lanes (core, exploit, shadow)."""
    all_trades = []
    
    # Core trades
    core_trades = _load_jsonl(TRADES_PATH)
    for trade in core_trades:
        trade["_lane"] = "core"
        all_trades.append(trade)
    
    # Exploit trades
    exploit_trades = _load_jsonl(EXPLOIT_TRADES_PATH)
    for trade in exploit_trades:
        trade["_lane"] = "exploit"
        all_trades.append(trade)
    
    # Shadow trades (for attribution, but not counted in capital impact)
    shadow_trades = _load_jsonl(SHADOW_TRADES_PATH)
    for trade in shadow_trades:
        trade["_lane"] = "shadow"
        all_trades.append(trade)
    
    # Filter by window
    window_trades = []
    for trade in all_trades:
        ts = _parse_timestamp(trade.get("ts") or trade.get("timestamp"))
        if ts is None:
            continue
        delta = now - ts
        if delta.total_seconds() > window_days * 86400.0:
            continue
        
        # Only count closes for PnL
        event_type = str(trade.get("type") or trade.get("event", "")).lower()
        if event_type not in ("close", "would_exit"):
            continue
        
        window_trades.append(trade)
    
    return window_trades


def _compute_symbol_pnl(
    trades: List[Dict[str, Any]],
) -> Dict[str, float]:
    """Compute PnL USD per symbol."""
    by_symbol: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    
    for trade in trades:
        symbol = trade.get("symbol") or trade.get("pair")
        if not symbol or symbol == "UNKNOWN":
            continue
        
        rets = _extract_return(trade)
        if rets is None:
            continue
        
        r, w = rets
        by_symbol[symbol].append((r, w))
    
    results = {}
    for symbol, returns in by_symbol.items():
        total_pnl = sum(r * w for r, w in returns)
        results[symbol] = total_pnl
    
    return results


def _load_quarantine_history() -> List[Dict[str, Any]]:
    """Load quarantine history for cooldown tracking."""
    if not QUARANTINE_HISTORY_PATH.exists():
        return []
    
    history = []
    try:
        with QUARANTINE_HISTORY_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    history.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    
    return history


def _append_quarantine_history(entry: Dict[str, Any]) -> None:
    """Append to quarantine history."""
    try:
        QUARANTINE_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with QUARANTINE_HISTORY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def compute_quarantine() -> Dict[str, Any]:
    """
    Compute quarantine state.
    
    Returns:
        Dict with quarantine state matching quarantine.json schema
    """
    now = datetime.now(timezone.utc)
    ts = now.isoformat()
    
    # Load config
    config = _load_config()
    
    if not config.get("enabled", True):
        return {
            "ts": ts,
            "enabled": False,
            "capital_mode": "unknown",
            "quarantined": [],
            "blocked_symbols": [],
            "weight_adjustments": [],
            "notes": ["Quarantine is disabled in config."],
        }
    
    # Load capital protection
    capital_protection = _load_json(CAPITAL_PROTECTION_PATH)
    capital_mode = capital_protection.get("mode") or \
                   capital_protection.get("global", {}).get("mode") or "unknown"
    
    # Check if quarantine applies to current mode
    modes_apply = config.get("modes_apply", [])
    if capital_mode not in modes_apply:
        return {
            "ts": ts,
            "enabled": True,
            "capital_mode": capital_mode,
            "quarantined": [],
            "blocked_symbols": [],
            "weight_adjustments": [],
            "notes": [f"Quarantine only applies in modes: {modes_apply}"],
        }
    
    # Load trades and compute PnL
    window_days = config.get("window_days", 30)
    trades = _load_trades_all_lanes(window_days, now)
    symbol_pnl = _compute_symbol_pnl(trades)
    
    # Find loss contributors
    symbol_losses = [
        (sym, pnl)
        for sym, pnl in symbol_pnl.items()
        if pnl < 0
    ]
    
    if not symbol_losses:
        return {
            "ts": ts,
            "enabled": True,
            "capital_mode": capital_mode,
            "window_days": window_days,
            "quarantined": [],
            "blocked_symbols": [],
            "weight_adjustments": [],
            "notes": ["No loss contributors found."],
        }
    
    # Sort by loss (most negative first)
    symbol_losses.sort(key=lambda x: x[1])
    
    # Compute total losses
    total_losses = abs(sum(pnl for _, pnl in symbol_losses))
    
    if total_losses < config.get("min_negative_pnl_usd", 0.05):
        return {
            "ts": ts,
            "enabled": True,
            "capital_mode": capital_mode,
            "window_days": window_days,
            "quarantined": [],
            "blocked_symbols": [],
            "weight_adjustments": [],
            "notes": [f"Total losses {total_losses:.2f} < min threshold {config.get('min_negative_pnl_usd', 0.05)}"],
        }
    
    # Compute contribution percentages
    candidates = []
    for sym, pnl in symbol_losses:
        contribution_pct = (abs(pnl) / total_losses * 100) if total_losses > 0 else 0.0
        if contribution_pct >= config.get("min_contribution_pct", 20.0):
            candidates.append({
                "symbol": sym,
                "pnl_usd": pnl,
                "contribution_pct": contribution_pct,
            })
    
    # Sort by contribution (highest first)
    candidates.sort(key=lambda x: x["contribution_pct"], reverse=True)
    
    # Take top max_symbols
    max_symbols = config.get("max_symbols", 2)
    top_candidates = candidates[:max_symbols]
    
    # Load history for cooldown
    history = _load_quarantine_history()
    cooldown_hours = config.get("cooldown_hours", 24)
    cutoff = now - timedelta(hours=cooldown_hours)
    
    # Check cooldown for each candidate
    quarantined = []
    for candidate in top_candidates:
        symbol = candidate["symbol"]
        
        # Check if recently quarantined
        recently_quarantined = False
        for entry in reversed(history):
            entry_ts_str = entry.get("ts")
            if not entry_ts_str:
                continue
            try:
                entry_ts = datetime.fromisoformat(entry_ts_str.replace("Z", "+00:00")).astimezone(timezone.utc)
                if entry_ts < cutoff:
                    break
                if symbol in entry.get("quarantined_symbols", []):
                    recently_quarantined = True
                    break
            except Exception:
                continue
        
        if recently_quarantined:
            # Still in cooldown, keep quarantined
            cooldown_until = (cutoff + timedelta(hours=cooldown_hours)).isoformat()
        else:
            # New quarantine
            cooldown_until = (now + timedelta(hours=cooldown_hours)).isoformat()
        
        quarantined.append({
            "symbol": symbol,
            "reason": "loss_contribution",
            "pnl_usd": candidate["pnl_usd"],
            "contribution_pct": candidate["contribution_pct"],
            "cooldown_until": cooldown_until,
        })
    
    # Build blocked symbols list
    blocked_symbols = [q["symbol"] for q in quarantined] if config.get("actions", {}).get("block_new_entries", True) else []
    
    # Build weight adjustments
    weight_adjustments = []
    if config.get("actions", {}).get("reduce_weight", True):
        weight_multiplier = config.get("actions", {}).get("weight_multiplier", 0.00)
        weight_floor = config.get("actions", {}).get("weight_floor", 0.00)
        
        for q in quarantined:
            symbol = q["symbol"]
            # We'll get raw_weight from capital_plan in the overlay module
            weight_adjustments.append({
                "symbol": symbol,
                "raw_weight": 0.0,  # Will be filled by overlay
                "new_weight": weight_floor,
                "multiplier": weight_multiplier,
            })
    
    # Append to history
    _append_quarantine_history({
        "ts": ts,
        "capital_mode": capital_mode,
        "quarantined_symbols": blocked_symbols,
    })
    
    return {
        "ts": ts,
        "enabled": True,
        "capital_mode": capital_mode,
        "window_days": window_days,
        "quarantined": quarantined,
        "blocked_symbols": blocked_symbols,
        "weight_adjustments": weight_adjustments,
        "notes": ["Quarantine is restrictive-only; never enables trading."],
    }


def run_quarantine() -> Dict[str, Any]:
    """
    Run quarantine engine and write state file.
    
    Returns:
        Quarantine state dict
    """
    state = compute_quarantine()
    
    # Write state file
    QUARANTINE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with QUARANTINE_STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    
    return state

