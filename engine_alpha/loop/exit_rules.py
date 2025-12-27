"""
Regime-aware exit rules module.

Provides clean, configurable exit logic that can be tuned via CSV analysis
and GPT recommendations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple


@dataclass
class ExitParams:
    """Exit parameters for a specific regime."""
    min_hold_bars: int        # minimum bars before any SL/TP
    max_hold_bars: int        # maximum bars to hold (time-based stop-out, 0 = no limit)
    tp_return_min: float      # minimum *fractional* return to allow TP (e.g. 0.005 = +0.5%)
    sl_return: float          # negative fractional return to trigger SL (e.g. -0.01 = -1%)
    tp_conf_min: float        # minimum final_conf for TP
    sl_conf_min: float        # minimum final_conf for SL
    decay_bars: int           # bars after entry before we allow decay exits
    drop_return_max: float    # abs(return) <= this → candidate for scratch/drop


DEFAULT_EXIT = ExitParams(
    min_hold_bars=1,
    max_hold_bars=0,  # 0 = no limit (default)
    tp_return_min=0.003,
    sl_return=-0.01,
    tp_conf_min=0.65,
    sl_conf_min=0.30,
    decay_bars=6,
    drop_return_max=0.0005,
)


def _load_exit_config(path: str | None = None) -> Dict[str, ExitParams]:
    """Load exit rules from JSON config file."""
    if path is None:
        # Default to config/exit_rules.json relative to repo root
        repo_root = Path(__file__).resolve().parents[2]
        cfg_path = repo_root / "config" / "exit_rules.json"
    else:
        cfg_path = Path(path)
    
    if not cfg_path.exists():
        return {"default": DEFAULT_EXIT}
    
    try:
        raw = json.loads(cfg_path.read_text())
    except Exception:
        return {"default": DEFAULT_EXIT}
    
    out: Dict[str, ExitParams] = {}
    for regime, params in raw.items():
        try:
            out[regime] = ExitParams(
                min_hold_bars=int(params.get("min_hold_bars", DEFAULT_EXIT.min_hold_bars)),
                max_hold_bars=int(params.get("max_hold_bars", DEFAULT_EXIT.max_hold_bars)),
                tp_return_min=float(params.get("tp_return_min", DEFAULT_EXIT.tp_return_min)),
                sl_return=float(params.get("sl_return", DEFAULT_EXIT.sl_return)),
                tp_conf_min=float(params.get("tp_conf_min", DEFAULT_EXIT.tp_conf_min)),
                sl_conf_min=float(params.get("sl_conf_min", DEFAULT_EXIT.sl_conf_min)),
                decay_bars=int(params.get("decay_bars", DEFAULT_EXIT.decay_bars)),
                drop_return_max=float(params.get("drop_return_max", DEFAULT_EXIT.drop_return_max)),
            )
        except Exception:
            # Skip invalid entries
            continue
    
    if "default" not in out:
        out["default"] = DEFAULT_EXIT
    
    return out


# Load config at module import time
EXIT_CONFIG: Dict[str, ExitParams] = _load_exit_config()


def get_exit_params(regime: str) -> ExitParams:
    """Get exit parameters for a given regime, falling back to default."""
    return EXIT_CONFIG.get(regime, EXIT_CONFIG["default"])


def reload_exit_config(path: str | None = None) -> None:
    """Reload exit config from file (useful after GPT updates)."""
    global EXIT_CONFIG
    EXIT_CONFIG = _load_exit_config(path)


def evaluate_exit(
    *,
    regime: str,
    bars_open: int,
    direction: int,              # +1 long, -1 short
    entry_price: float,
    last_price: float,
    final_conf: float,
    sl_conf: float | None = None,
    tp_conf: float | None = None,
    now_ts: str | None = None,
    symbol: str | None = None,   # Phase 13: For structure-aware modifiers
    side: str | None = None,     # Phase 13: "long" or "short"
    mode: str = "PAPER",         # Phase 13: Trading mode
) -> Optional[Tuple[str, float, float]]:
    """
    Decide if we should close a position now, and if so, why.
    
    Args:
        regime: Market regime (trend_down, high_vol, chop, trend_up)
        bars_open: Number of bars since entry
        direction: Trade direction (+1 for long, -1 for short)
        entry_price: Entry price
        last_price: Current/last price
        final_conf: Current final confidence
        sl_conf: Stop-loss confidence threshold (optional, uses exit params if None)
        tp_conf: Take-profit confidence threshold (optional, uses exit params if None)
        now_ts: Current timestamp (optional, for logging)
        symbol: Symbol ID (optional, for structure-aware modifiers in PAPER mode)
        side: Position side "long" or "short" (optional, for structure-aware modifiers)
        mode: Trading mode "PAPER" or "LIVE" (default: "PAPER")
    
    Returns:
        (exit_reason, exit_pct, exit_conf) or None if we should hold.
        - exit_pct is *fractional* return (e.g. 0.01 = +1%)
        - exit_conf is the "confidence at exit" (uses final_conf)
    """
    params = get_exit_params(regime)
    
    # Phase 13: Apply structure-aware modifiers in PAPER mode
    tp_return_min = params.tp_return_min
    sl_return = params.sl_return
    
    if mode.upper() == "PAPER" and symbol and side:
        try:
            from engine_alpha.loop.exit_engine import apply_structure_modifiers_to_exit_params
            mods = apply_structure_modifiers_to_exit_params(
                symbol=symbol,
                side=side,
                tp_return_min=tp_return_min,
                sl_return=sl_return,
                mode=mode,
            )
            tp_return_min = mods["tp_return_min"]
            sl_return = mods["sl_return"]
            # Store structure notes for logging (optional)
            structure_notes = mods.get("structure_notes", [])
        except Exception:
            # If modifiers fail, use base params
            pass
    
    # Use provided thresholds or fall back to params
    sl_conf_threshold = sl_conf if sl_conf is not None else params.sl_conf_min
    tp_conf_threshold = tp_conf if tp_conf is not None else params.tp_conf_min
    
    # Compute fractional return in the direction of the trade
    if entry_price <= 0 or last_price <= 0:
        return None
    
    raw_ret = (last_price - entry_price) / entry_price
    signed_ret = raw_ret * float(direction)
    abs_ret = abs(signed_ret)
    
    # Do not exit before min-hold
    if bars_open < params.min_hold_bars:
        return None
    
    # Time-based stop-out: if max_hold_bars is set and exceeded, force exit
    if params.max_hold_bars > 0 and bars_open >= params.max_hold_bars:
        # Force exit as "decay" if we've held too long
        exit_reason = "decay"
        exit_pct = signed_ret
        exit_conf = final_conf
        return (exit_reason, float(exit_pct), float(exit_conf))
    
    # Take-profit condition: require sufficient move + sufficient confidence
    # Use adjusted tp_return_min if structure modifiers were applied
    tp_ok = (
        signed_ret >= tp_return_min
        and final_conf >= tp_conf_threshold
    )
    
    # Stop-loss condition: require sufficient adverse move + confidence
    # Use adjusted sl_return if structure modifiers were applied
    sl_ok = (
        signed_ret <= sl_return
        and final_conf >= sl_conf_threshold
    )
    
    # If neither TP nor SL is valid, consider decay/drop exits
    # but only after decay_bars and only if move is tiny.
    if not tp_ok and not sl_ok:
        if bars_open >= params.decay_bars and abs_ret <= params.drop_return_max:
            # Treat as a scratch/drop exit
            exit_reason = "drop"
            exit_pct = signed_ret
            exit_conf = final_conf
            return (exit_reason, float(exit_pct), float(exit_conf))
        # Otherwise, keep holding
        return None
    
    # Prefer SL over TP if both fire
    if sl_ok:
        return ("sl", float(signed_ret), float(final_conf))
    if tp_ok:
        return ("tp", float(signed_ret), float(final_conf))
    
    return None

