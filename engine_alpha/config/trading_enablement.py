# engine_alpha/config/trading_enablement.py

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Set

ROOT_DIR = Path(__file__).resolve().parents[2]
TRADING_ENABLEMENT_PATH = ROOT_DIR / "config" / "trading_enablement.json"


def load_trading_enablement() -> dict:
    """Load trading enablement config."""
    if not TRADING_ENABLEMENT_PATH.exists():
        return {
            "enabled_for_trading": [],
            "phase": "phase_0",
            "notes": "No trading enabled",
            "last_updated": None,
        }
    
    try:
        with TRADING_ENABLEMENT_PATH.open("r") as f:
            return json.load(f)
    except Exception:
        return {
            "enabled_for_trading": [],
            "phase": "phase_0",
            "notes": "Error loading config",
            "last_updated": None,
        }


def is_trading_enabled(symbol: str) -> bool:
    """Check if a symbol is enabled for trading."""
    cfg = load_trading_enablement()
    enabled = cfg.get("enabled_for_trading", [])
    return symbol.upper() in [s.upper() for s in enabled]


def get_enabled_trading_symbols() -> Set[str]:
    """Get set of symbols enabled for trading."""
    cfg = load_trading_enablement()
    enabled = cfg.get("enabled_for_trading", [])
    return {s.upper() for s in enabled}


def get_current_phase() -> str:
    """Get current rollout phase."""
    cfg = load_trading_enablement()
    return cfg.get("phase", "phase_0")


