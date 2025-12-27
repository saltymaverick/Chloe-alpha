"""
Regime Risk Filters — Blocks trades under bad regimes,
microstructure, or symbol weakness.

All filters are advisory-only and PAPER-safe.
"""

from __future__ import annotations

from typing import Dict, Any, Tuple, List

TIER3_CHOP_BLOCK = True


def should_block_trade(symbol: str, inputs: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Determine if a trade should be blocked based on risk filters.
    
    Args:
        symbol: Symbol string (e.g., "ETHUSDT")
        inputs: Dict containing:
            - tier: "tier1", "tier2", or "tier3"
            - micro_regime: "clean_trend", "indecision", "noisy", etc.
            - execution_label: "friendly", "neutral", or "hostile"
            - drift_status: "improving", "stable", "degrading", or "insufficient_data"
    
    Returns:
        Tuple of (blocked: bool, reasons: List[str])
    """
    reasons: List[str] = []
    blocked = False
    
    tier = inputs.get("tier")
    micro = inputs.get("micro_regime")
    exec_label = inputs.get("execution_label")
    drift = inputs.get("drift_status")
    
    # Chop-blocker for Tier3 symbols in indecision microstructure
    if TIER3_CHOP_BLOCK and tier == "tier3":
        if micro in ("indecision", "chop_noise", "noisy"):
            blocked = True
            reasons.append(f"tier3 {micro} microstructure: blocked")
    
    # Hostile execution quality
    if exec_label == "hostile":
        blocked = True
        reasons.append("hostile execution regime: blocked")
    
    # Degrading drift
    if drift == "degrading":
        blocked = True
        reasons.append("degrading drift: blocked")
    
    return blocked, reasons

