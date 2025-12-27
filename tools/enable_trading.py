#!/usr/bin/env python3
"""
Enable an asset for trading (adds to trading_enablement.json).

Usage:
    python3 -m tools.enable_trading BTCUSDT
    python3 -m tools.enable_trading MATICUSDT --phase phase_2
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT_DIR = Path(__file__).resolve().parents[1]
TRADING_ENABLEMENT_PATH = ROOT_DIR / "config" / "trading_enablement.json"


def load_config() -> dict:
    """Load trading enablement config."""
    if not TRADING_ENABLEMENT_PATH.exists():
        return {
            "enabled_for_trading": [],
            "phase": "phase_0",
            "notes": "",
            "last_updated": None,
        }
    
    try:
        with TRADING_ENABLEMENT_PATH.open("r") as f:
            return json.load(f)
    except Exception:
        return {
            "enabled_for_trading": [],
            "phase": "phase_0",
            "notes": "",
            "last_updated": None,
        }


def save_config(cfg: dict) -> None:
    """Save trading enablement config."""
    TRADING_ENABLEMENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TRADING_ENABLEMENT_PATH.open("w") as f:
        json.dump(cfg, f, indent=2)


def enable_trading(symbol: str, phase: str = None) -> None:
    """Enable a symbol for trading."""
    symbol = symbol.upper()
    cfg = load_config()
    
    enabled = cfg.get("enabled_for_trading", [])
    if symbol in enabled:
        print(f"✅ {symbol} is already enabled for trading.")
        return
    
    enabled.append(symbol)
    cfg["enabled_for_trading"] = sorted(enabled)
    
    if phase:
        cfg["phase"] = phase
    
    cfg["last_updated"] = datetime.now(timezone.utc).isoformat()
    
    save_config(cfg)
    
    print(f"✅ Enabled {symbol} for trading.")
    print(f"   Phase: {cfg['phase']}")
    print(f"   Total trading-enabled assets: {len(enabled)}")
    print(f"   Assets: {', '.join(enabled)}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 -m tools.enable_trading SYMBOL [PHASE]")
        print("Example: python3 -m tools.enable_trading BTCUSDT phase_2")
        sys.exit(1)
    
    symbol = sys.argv[1]
    phase = sys.argv[2] if len(sys.argv) > 2 else None
    
    enable_trading(symbol, phase)


if __name__ == "__main__":
    main()


