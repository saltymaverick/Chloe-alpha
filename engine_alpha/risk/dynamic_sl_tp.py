"""
Dynamic SL/TP Engine — Volatility and structure-based exits.

Computes dynamic stop-loss and take-profit levels based on:
- Volatility (from microstructure)
- Microstructure regime
- Symbol archetype

All outputs are advisory-only.
"""

from __future__ import annotations

from typing import Dict, Any, List

DEFAULT_VOLATILITY = 0.002  # 0.2% default volatility


def compute_dynamic_sl_tp(
    symbol: str,
    volatility: float,
    micro_regime: str,
    archetype: str
) -> Dict[str, Any]:
    """
    Compute dynamic stop-loss and take-profit levels.
    
    Args:
        symbol: Symbol string (e.g., "ETHUSDT")
        volatility: Volatility measure (e.g., 0.002 for 0.2%)
        micro_regime: "clean_trend", "indecision", "noisy", etc.
        archetype: "trend_monster", "fragile", "mean_reverter", etc.
    
    Returns:
        Dict with keys: "sl", "tp", "notes"
    """
    notes: List[str] = []
    
    # Default volatility if not provided
    if volatility is None or volatility <= 0:
        volatility = DEFAULT_VOLATILITY
    
    # Base multipliers based on microstructure
    if micro_regime == "clean_trend":
        sl_mult = 1.2
        tp_mult = 3.0
    elif micro_regime in ("indecision", "chop_noise"):
        sl_mult = 0.8
        tp_mult = 1.5
    elif micro_regime == "noisy":
        sl_mult = 0.6
        tp_mult = 1.2
    elif micro_regime == "reversal_hint":
        sl_mult = 1.0
        tp_mult = 2.0
    else:  # unknown or other
        sl_mult = 1.0
        tp_mult = 2.0
    
    # Archetype adjustments
    if archetype == "trend_monster":
        tp_mult *= 1.3
        notes.append("trend_monster: wider TP")
    elif archetype == "mean_reverter":
        sl_mult *= 0.8
        notes.append("mean_reverter: tighter SL")
    elif archetype == "fragile":
        sl_mult *= 0.7
        tp_mult *= 0.9
        notes.append("fragile: tighter SL/TP")
    
    sl = volatility * sl_mult
    tp = volatility * tp_mult
    
    # Clamp to reasonable ranges
    sl = max(0.001, min(sl, 0.05))  # 0.1% to 5%
    tp = max(0.002, min(tp, 0.20))  # 0.2% to 20%
    
    notes.append(f"micro={micro_regime} sl×={sl_mult:.2f} tp×={tp_mult:.2f}")
    notes.append(f"vol={volatility:.5f}")
    
    return {
        "sl": sl,
        "tp": tp,
        "notes": notes
    }

