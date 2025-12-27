"""
Exit engine - Phase 1 + Phase 13 (Structure-Aware Exit Engine v2)
Provides exit reason label mapping for reporting clarity.
Exit logic is handled directly in autonomous_trader.py.

Phase 13 adds structure-aware exit modifiers based on:
- Liquidity sweeps
- Volume imbalance
- Market structure & sessions
- Execution quality & microstructure
"""

from __future__ import annotations

from typing import Optional, Dict, Any, List
from pathlib import Path
import json
import os

from engine_alpha.core.paths import REPORTS as REPORTS_DIR

# Phase 1: Exit reason labels for reporting clarity (non-destructive mapping)
EXIT_REASON_LABELS = {
    "sl": "stop_loss",
    "tp": "take_profit",
    "drop": "signal_drop",
    "decay": "time_decay",
    "reverse": "signal_reverse",
    "low_conf": "low_confidence",
    "flip": "direction_flip",
    "timeout": "timeout",
    "manual": "manual",
    "unknown": "unknown",
}


def get_exit_label(exit_reason: Optional[str]) -> str:
    """
    Get human-readable label for exit reason.
    Returns the mapped label or "unknown" if reason is not recognized.
    
    Args:
        exit_reason: Exit reason string (e.g., "sl", "tp", "drop")
    
    Returns:
        Human-readable label (e.g., "stop_loss", "take_profit", "signal_drop")
    """
    if exit_reason is None:
        return "unknown"
    reason_lower = str(exit_reason).lower()
    return EXIT_REASON_LABELS.get(reason_lower, "unknown")


# Phase 13: Structure-aware exit modifiers
LIQ_SWEEPS_PATH = REPORTS_DIR / "research" / "liquidity_sweeps.json"
VOL_IMB_PATH = REPORTS_DIR / "research" / "volume_imbalance.json"
MSTRUCT_PATH = REPORTS_DIR / "research" / "market_structure.json"
EXECQ_PATH = REPORTS_DIR / "research" / "execution_quality.json"
MICRO_PATH = REPORTS_DIR / "research" / "microstructure_snapshot_15m.json"

_liq_cache: Dict[str, Any] | None = None
_vi_cache: Dict[str, Any] | None = None
_ms_cache: Dict[str, Any] | None = None
_eq_cache: Dict[str, Any] | None = None
_micro_cache: Dict[str, Any] | None = None


def _load_json_symbols(path: Path) -> Dict[str, Any]:
    """Load JSON file with symbols data, handling both formats."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        # Some files are {"symbols": {...}}, others are plain {...}
        if isinstance(data, dict) and "symbols" in data:
            return data["symbols"]
        return data
    except Exception:
        return {}


def load_liq_sweeps() -> Dict[str, Any]:
    """Load liquidity sweeps data."""
    global _liq_cache
    if _liq_cache is None:
        _liq_cache = _load_json_symbols(LIQ_SWEEPS_PATH)
    return _liq_cache


def load_vol_imb() -> Dict[str, Any]:
    """Load volume imbalance data."""
    global _vi_cache
    if _vi_cache is None:
        _vi_cache = _load_json_symbols(VOL_IMB_PATH)
    return _vi_cache


def load_market_structure() -> Dict[str, Any]:
    """Load market structure data."""
    global _ms_cache
    if _ms_cache is None:
        _ms_cache = _load_json_symbols(MSTRUCT_PATH)
    return _ms_cache


def load_exec_quality() -> Dict[str, Any]:
    """Load execution quality data."""
    global _eq_cache
    if _eq_cache is None:
        _eq_cache = _load_json_symbols(EXECQ_PATH)
    return _eq_cache


def load_microstructure() -> Dict[str, Any]:
    """Load microstructure data."""
    global _micro_cache
    if _micro_cache is None:
        _micro_cache = _load_json_symbols(MICRO_PATH)
    return _micro_cache


def compute_structure_exit_modifiers(symbol: str, side: str) -> Dict[str, Any]:
    """
    Compute structure-aware exit modifiers based on:
      - liquidity_sweeps
      - volume_imbalance
      - market_structure
      - execution quality
      - microstructure
    
    Args:
        symbol: Symbol ID (e.g., "ETHUSDT")
        side: Position side ("long" or "short")
    
    Returns:
        Dict with advisory tweaks:
        {
            "tp_mult_delta": float,   # add to TP multiple/return threshold
            "sl_mult_delta": float,    # reduce SL multiple (tighten)
            "prefer_hold": bool,
            "prefer_early_exit": bool,
            "notes": List[str],
        }
    
    All values are advisory and must be applied ONLY in PAPER mode.
    """
    notes: List[str] = []
    tp_mult_delta = 0.0
    sl_mult_delta = 0.0
    prefer_hold = False
    prefer_early_exit = False
    
    try:
        liq = load_liq_sweeps().get(symbol, {})
        vi = load_vol_imb().get(symbol, {})
        ms = load_market_structure().get(symbol, {})
        eq = load_exec_quality().get(symbol, {})
        micro = load_microstructure()
        
        # Basic fields
        structure = ms.get("structure_1h", "neutral")
        struct_conf = ms.get("structure_confidence")
        session = ms.get("session", "unknown")
        
        # Execution quality / micro
        exec_label = None
        if isinstance(eq, dict) and "label" in eq:
            exec_label = eq.get("label")
        
        # Microstructure can be nested: {"symbol": {"regime": ...}}
        micro_regime = None
        if isinstance(micro, dict):
            symbol_micro = micro.get(symbol, {})
            if isinstance(symbol_micro, dict):
                micro_regime = symbol_micro.get("micro_regime") or symbol_micro.get("regime")
        
        # Volume imbalance
        imb_strength = vi.get("imbalance_strength")
        cvd_trend = vi.get("cvd_trend", "neutral")
        absorption_count = vi.get("absorption_count", 0)
        exhaustion_count = vi.get("exhaustion_count", 0)
        
        # Liquidity sweeps
        swept_high = liq.get("sell_sweep_5m") or liq.get("sell_sweep_15m")
        swept_low = liq.get("buy_sweep_5m") or liq.get("buy_sweep_15m")
        breaker = liq.get("breaker", "none")
        
        # Determine structure shift from sweeps
        struct_shift = "neutral"
        if breaker == "bearish" or swept_high:
            struct_shift = "bearish"
        elif breaker == "bullish" or swept_low:
            struct_shift = "bullish"
        
        # --- Rules ---
        
        # 1) Trend-supportive regime: hold more / loosen TP a bit
        if struct_conf is not None and struct_conf >= 0.6:
            if structure == "bullish" and side == "long":
                if micro_regime == "clean_trend" and cvd_trend == "bullish":
                    tp_mult_delta += 0.002  # Increase TP return threshold by 0.2%
                    prefer_hold = True
                    notes.append("Structure-aware: bullish 1h, clean_trend, bullish CVD → extend TP slightly.")
            
            if structure == "bearish" and side == "short":
                if micro_regime == "clean_trend" and cvd_trend == "bearish":
                    tp_mult_delta += 0.002  # Increase TP return threshold by 0.2%
                    prefer_hold = True
                    notes.append("Structure-aware: bearish 1h, clean_trend, bearish CVD → extend TP slightly.")
        
        # 2) Reversal risk: tighten SL / prefer early exit
        hostile = (exec_label == "hostile") or (micro_regime == "indecision")
        if hostile or (struct_conf is not None and struct_conf < 0.3):
            sl_mult_delta -= 0.001  # Tighten stop (reduce SL return threshold)
            prefer_early_exit = True
            notes.append("Structure-aware: hostile/low-confidence regime → tighten SL and allow early exit.")
        
        # 3) Liquidity sweep against our side: consider early exit
        if side == "long" and swept_high and struct_shift == "bearish":
            sl_mult_delta -= 0.001
            prefer_early_exit = True
            notes.append("Structure-aware: sweep of highs + bearish shift against long → consider faster exit.")
        
        if side == "short" and swept_low and struct_shift == "bullish":
            sl_mult_delta -= 0.001
            prefer_early_exit = True
            notes.append("Structure-aware: sweep of lows + bullish shift against short → consider faster exit.")
        
        # 4) Exhaustion/absorption: don't overstay
        if exhaustion_count > 0 or absorption_count > 0:
            sl_mult_delta -= 0.0005
            tp_mult_delta -= 0.0005
            notes.append("Structure-aware: exhaustion/absorption detected → slightly tighten both SL/TP.")
        
    except Exception as e:
        notes.append(f"struct-exit error: {e}")
    
    return {
        "tp_mult_delta": tp_mult_delta,
        "sl_mult_delta": sl_mult_delta,
        "prefer_hold": prefer_hold,
        "prefer_early_exit": prefer_early_exit,
        "notes": notes,
    }


def apply_structure_modifiers_to_exit_params(
    symbol: str,
    side: str,
    tp_return_min: float,
    sl_return: float,
    mode: str = "PAPER",
) -> Dict[str, float]:
    """
    Apply structure-aware modifiers to exit parameters (PAPER mode only).
    
    Args:
        symbol: Symbol ID
        side: Position side ("long" or "short")
        tp_return_min: Base TP return threshold (fractional, e.g., 0.003 = 0.3%)
        sl_return: Base SL return threshold (fractional, negative, e.g., -0.01 = -1%)
        mode: Trading mode ("PAPER" or "LIVE")
    
    Returns:
        {
            "tp_return_min": adjusted TP threshold,
            "sl_return": adjusted SL threshold,
            "structure_notes": List[str],
        }
    """
    if mode.upper() != "PAPER":
        return {
            "tp_return_min": tp_return_min,
            "sl_return": sl_return,
            "structure_notes": [],
        }
    
    try:
        mods = compute_structure_exit_modifiers(symbol, side)
        
        # Apply deltas
        adjusted_tp = tp_return_min + mods["tp_mult_delta"]
        adjusted_sl = sl_return + mods["sl_mult_delta"]  # sl_mult_delta is negative, so this tightens
        
        # Clamp to sane ranges
        adjusted_tp = max(0.001, min(adjusted_tp, 0.05))  # 0.1% to 5%
        adjusted_sl = max(-0.05, min(adjusted_sl, -0.001))  # -5% to -0.1%
        
        return {
            "tp_return_min": adjusted_tp,
            "sl_return": adjusted_sl,
            "structure_notes": mods["notes"],
            "prefer_hold": mods["prefer_hold"],
            "prefer_early_exit": mods["prefer_early_exit"],
        }
    except Exception as e:
        return {
            "tp_return_min": tp_return_min,
            "sl_return": sl_return,
            "structure_notes": [f"Error applying structure modifiers: {e}"],
            "prefer_hold": False,
            "prefer_early_exit": False,
        }
