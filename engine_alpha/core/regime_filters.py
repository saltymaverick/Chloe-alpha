"""
Regime Filters - Load tier and microstructure data for filtering decisions.

Provides helper functions to load tiers and microstructure regimes for use in
trade gating logic (e.g., chop-blocker for Tier3 symbols).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional

from engine_alpha.core.paths import REPORTS, CONFIG

TIERS_PATH = REPORTS / "gpt" / "reflection_output.json"
MICRO_PATH = REPORTS / "research" / "microstructure_snapshot_15m.json"

# Cache for loaded data (refresh on each call, but cache within a single call)
_tiers_cache: Optional[Dict[str, str]] = None
_micro_cache: Optional[Dict[str, Dict[str, Any]]] = None


def load_tiers() -> Dict[str, str]:
    """
    Load tier assignments from reflection_output.json.
    
    Returns:
        Dict mapping symbol -> tier (e.g., "ETHUSDT" -> "tier1")
    """
    global _tiers_cache
    
    if not TIERS_PATH.exists():
        return {}
    
    try:
        data = json.loads(TIERS_PATH.read_text())
        tiers = data.get("tiers", {})
        
        result = {}
        for tier_name, symbols_list in tiers.items():
            if isinstance(symbols_list, list):
                for sym in symbols_list:
                    result[sym] = tier_name  # e.g., 'tier1', 'tier2', 'tier3'
        
        _tiers_cache = result
        return result
    except Exception:
        return {}


def load_microstructure_regimes() -> Dict[str, Dict[str, Any]]:
    """
    Load microstructure regimes from microstructure_snapshot_15m.json.
    
    Returns:
        Dict mapping symbol -> {micro_regime: str, metrics: dict}
    """
    global _micro_cache
    
    if not MICRO_PATH.exists():
        return {}
    
    try:
        data = json.loads(MICRO_PATH.read_text())
        symbols_data = data.get("symbols", {})
        
        # Handle both old format (timestamp -> features) and new format (summary)
        result = {}
        for symbol, symbol_data in symbols_data.items():
            if isinstance(symbol_data, dict):
                if "micro_regime" in symbol_data:
                    # New summary format
                    result[symbol] = symbol_data
                else:
                    # Old format: find dominant regime from recent bars
                    # For now, return empty dict (would need to compute from bar-level data)
                    result[symbol] = {}
        
        _micro_cache = result
        return result
    except Exception:
        return {}


def get_symbol_tier(symbol: str) -> Optional[str]:
    """Get tier for a symbol, or None if not found."""
    tiers = load_tiers()
    return tiers.get(symbol)


def get_symbol_micro_regime(symbol: str) -> Optional[str]:
    """Get micro_regime for a symbol, or None if not found."""
    micro = load_microstructure_regimes()
    symbol_data = micro.get(symbol, {})
    if isinstance(symbol_data, dict):
        return symbol_data.get("micro_regime")
    return None


def should_block_tier3_in_chop(symbol: str) -> bool:
    """
    Check if a Tier3 symbol should be blocked from opening in chop/indecision regimes.
    
    Args:
        symbol: Symbol ID (e.g., "ETHUSDT")
    
    Returns:
        True if should be blocked, False otherwise
    """
    tier = get_symbol_tier(symbol)
    if tier != "tier3":
        return False  # Only block Tier3
    
    micro_regime = get_symbol_micro_regime(symbol)
    if not micro_regime:
        return False  # If no microstructure data, don't block
    
    # Block Tier3 in noisy/indecision/chop regimes
    hostile_regimes = {"indecision", "chop_noise", "noisy"}
    return micro_regime in hostile_regimes

