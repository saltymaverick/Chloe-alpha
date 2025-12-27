"""
Symbol Registry - Phase 4.1
Centralized symbol management for easy coin onboarding.

Loads symbols from config/symbols.yaml and provides simple access functions.
"""

from __future__ import annotations

import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional

from engine_alpha.core.paths import CONFIG

SYMBOLS_YAML_PATH = CONFIG / "symbols.yaml"

# Fallback default symbols if registry is missing
DEFAULT_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "ATOMUSDT",
    "BNBUSDT",
    "DOTUSDT",
    "ADAUSDT",
    "XRPUSDT",
    "DOGEUSDT",
]


def _load_yaml(path: Path) -> Dict[str, Any]:
    """Load YAML file, return empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        content = path.read_text().strip()
        if not content:
            return {}
        return yaml.safe_load(content) or {}
    except Exception:
        return {}


def load_symbol_registry() -> List[str]:
    """
    Load list of enabled symbol IDs from config/symbols.yaml.
    
    Returns:
        List of enabled symbol IDs (e.g., ["BTCUSDT", "ETHUSDT", ...])
    
    Falls back to DEFAULT_SYMBOLS if registry is missing or empty.
    """
    data = _load_yaml(SYMBOLS_YAML_PATH)
    symbols_list = data.get("symbols", [])
    
    if not symbols_list:
        return DEFAULT_SYMBOLS
    
    enabled_symbols = []
    for symbol_entry in symbols_list:
        if isinstance(symbol_entry, dict):
            symbol_id = symbol_entry.get("id")
            enabled = symbol_entry.get("enabled", True)
            if symbol_id and enabled:
                enabled_symbols.append(symbol_id)
        elif isinstance(symbol_entry, str):
            # Handle legacy format: just a string
            enabled_symbols.append(symbol_entry)
    
    # If no enabled symbols found, fall back to defaults
    if not enabled_symbols:
        return DEFAULT_SYMBOLS
    
    return enabled_symbols


def load_symbol_metadata() -> Dict[str, Dict[str, Any]]:
    """
    Load symbol metadata from config/symbols.yaml.
    
    Returns:
        Dict keyed by symbol ID, each containing:
        - enabled: bool
        - tier_hint: str (optional, e.g., "tier1", "tier2", "tier3")
        - any extra metadata (future)
    
    Example:
        {
            "ETHUSDT": {
                "enabled": True,
                "tier_hint": "tier1"
            },
            ...
        }
    """
    data = _load_yaml(SYMBOLS_YAML_PATH)
    symbols_list = data.get("symbols", [])
    
    metadata: Dict[str, Dict[str, Any]] = {}
    
    for symbol_entry in symbols_list:
        if isinstance(symbol_entry, dict):
            symbol_id = symbol_entry.get("id")
            if symbol_id:
                metadata[symbol_id] = {
                    "enabled": symbol_entry.get("enabled", True),
                    "tier_hint": symbol_entry.get("tier_hint"),
                }
        elif isinstance(symbol_entry, str):
            # Handle legacy format: just a string
            metadata[symbol_entry] = {
                "enabled": True,
                "tier_hint": None,
            }
    
    return metadata


def is_symbol_enabled(symbol: str) -> bool:
    """
    Check if a symbol is enabled in the registry.
    
    Args:
        symbol: Symbol ID (e.g., "ETHUSDT")
    
    Returns:
        True if symbol is enabled, False otherwise
    """
    metadata = load_symbol_metadata()
    return metadata.get(symbol, {}).get("enabled", False)


def get_symbol_tier_hint(symbol: str) -> Optional[str]:
    """
    Get tier hint for a symbol.
    
    Args:
        symbol: Symbol ID (e.g., "ETHUSDT")
    
    Returns:
        Tier hint string (e.g., "tier1") or None if not set
    """
    metadata = load_symbol_metadata()
    return metadata.get(symbol, {}).get("tier_hint")

